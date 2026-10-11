"""Focused mode, offline adapter, and background-result safety checks; no inference."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

import sys
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from qwen3_tts_studio.app import create_window
from qwen3_tts_studio.application.workspace import CloningMode, WorkspaceSession
from qwen3_tts_studio.integrations.faster_whisper import (
    FasterWhisperTranscriber, TranscriptionResult, small_model_directory,
)
from qwen3_tts_studio.integrations import windows_cuda


class AdapterChecks(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows DLL loading")
    def test_process_local_dll_registration_retains_handles_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "Lib" / "site-packages" / "nvidia"
            for package, filename in (("cublas", "cublas64_12.dll"), ("cudnn", "cudnn64_9.dll"),
                                      ("cuda_nvrtc", "nvrtc64_120_0.dll")):
                folder = base / package / "bin"
                folder.mkdir(parents=True)
                (folder / filename).touch()
            path_before = os.environ.get("PATH")
            kernel32 = SimpleNamespace(SetDefaultDllDirectories=Mock(return_value=1))
            with patch.object(windows_cuda.sys, "prefix", tmp), patch.object(windows_cuda, "_search_configured", False), \
                 patch.object(windows_cuda, "_directory_handles", {}), patch.object(windows_cuda, "_libraries", {}), \
                 patch.object(windows_cuda.os, "add_dll_directory", side_effect=lambda path: object()) as add, \
                 patch.object(windows_cuda.ctypes, "WinDLL", side_effect=lambda name, **kwargs: kernel32 if name == "kernel32" else object()) as load:
                directories = windows_cuda.configure_cuda_dlls()
                handles = tuple(windows_cuda._directory_handles.values())
                self.assertEqual(len(directories), 3)
                self.assertEqual(windows_cuda.configure_cuda_dlls(), directories)
                self.assertEqual(tuple(windows_cuda._directory_handles.values()), handles)
                self.assertEqual(add.call_count, 3)
                self.assertEqual(load.call_count, 3)  # Kernel32 + cuBLAS + cuDNN core.
                kernel32.SetDefaultDllDirectories.assert_called_once_with(0x00001000)
                self.assertEqual(os.environ.get("PATH"), path_before)

    def test_offline_model_validation_lazy_reuse_and_future_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            folder = models / "faster-whisper"
            folder.mkdir()
            with self.assertRaises(FileNotFoundError):
                small_model_directory(models)
            for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
                (folder / name).write_text("fixture", encoding="utf-8")
            calls, unloaded = [], []
            def model(path, **kwargs):
                calls.append((path, kwargs))
                if kwargs["device"] == "cuda":
                    raise RuntimeError("CUDA library unavailable")
                return SimpleNamespace(
                    model=SimpleNamespace(unload_model=lambda: unloaded.append(True),
                                          device=kwargs["device"], compute_type=kwargs["compute_type"]),
                    transcribe=lambda path, **kwargs: (iter([SimpleNamespace(text=" Hello world. ")]),
                        SimpleNamespace(language="en", language_probability=.99)),
                )
            fake_ct2 = SimpleNamespace(get_cuda_device_count=lambda: 1,
                                      get_supported_compute_types=lambda device: {"float16", "int8"})
            adapter = FasterWhisperTranscriber(models)
            self.assertFalse(adapter.loaded)
            with patch("qwen3_tts_studio.integrations.faster_whisper.configure_cuda_dlls") as configure, \
                 patch.dict(sys.modules, ctranslate2=fake_ct2, faster_whisper=SimpleNamespace(WhisperModel=model)), \
                 self.assertLogs("qwen3_tts_studio.integrations.faster_whisper", level="WARNING") as logs:
                for _ in range(2):
                    result = adapter.transcribe(Path("reference.wav"), lambda: False, lambda text: None)
                    self.assertEqual((result.text, result.device), ("Hello world.", "cpu"))
                self.assertEqual(len(calls), 2)  # Failed CUDA load + one reused CPU load.
                configure.assert_called_once()
                self.assertEqual(calls[0][1]["compute_type"], "float16")
                self.assertIn("CUDA library unavailable", result.gpu_error)
                self.assertIn("using CPU fallback", logs.output[0])
                self.assertEqual(calls[-1][0], str(folder.resolve()))
                self.assertTrue(calls[-1][1]["local_files_only"])
                adapter.release()
                configure.side_effect = OSError("DLL registration failed")
                calls.clear()
                result = adapter.transcribe(Path("reference.wav"), lambda: False, lambda text: None)
                self.assertEqual(result.device, "cpu")
                self.assertIn("Windows CUDA DLL setup failed", result.gpu_error)
                self.assertEqual([kwargs["device"] for _, kwargs in calls], ["cpu"])
                adapter.release()
            self.assertEqual(unloaded, [True, True])
            (folder / "tokenizer.json").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "tokenizer.json"):
                small_model_directory(models)
        session = WorkspaceSession(reference=Path("reference.wav"))
        with self.assertRaisesRegex(ValueError, "nonempty"):
            session.voice_clone_arguments()
        session.transcript = " Reviewed reference "
        self.assertEqual(session.voice_clone_arguments()["ref_text"], "Reviewed reference")
        self.assertFalse(session.voice_clone_arguments()["x_vector_only_mode"])
        session.cloning_mode = CloningMode.X_VECTOR_ONLY
        self.assertNotIn("ref_text", session.voice_clone_arguments())
        self.assertTrue(session.voice_clone_arguments()["x_vector_only_mode"])


class DelayedAdapter:
    """A native operation that cannot stop until its next return boundary."""

    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()
        self.started = threading.Event()
        self.loaded = False
        self.loads = 0
        self.calls = []
        self.released_on = None
        self.text = "Recognized reference."
        self.error = None

    def transcribe(self, reference, cancelled, report):
        if not self.loaded:
            self.loads += 1
            self.loaded = True
            report("Loading Small model on CPU")
        self.calls.append((reference, threading.get_ident()))
        self.started.set()
        report("Transcribing · CPU · en")
        if not self.gate.wait(5):
            raise RuntimeError("Test gate timed out")
        if self.error:
            raise self.error
        return TranscriptionResult(self.text, "en", .99, "cpu")

    def release(self):
        self.loaded = False
        self.released_on = threading.get_ident()


class TranscriptionChecks(unittest.TestCase):
    def wait_until(self, predicate, timeout=5000):
        if predicate():
            return
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        poll.start()
        QTimer.singleShot(timeout, loop.quit)
        loop.exec()
        poll.stop()
        self.assertTrue(predicate(), "Background operation timed out")

    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.app.setQuitOnLastWindowClosed(False)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reference = self.root / "reference.wav"
        self.replacement = self.root / "replacement.ogg"
        samples = np.zeros(8000, dtype=np.float32)
        sf.write(self.reference, samples, 16000)
        sf.write(self.replacement, samples, 16000, format="OGG", subtype="VORBIS")
        self.adapter = DelayedAdapter()
        with patch("qwen3_tts_studio.application.transcription.FasterWhisperTranscriber", return_value=self.adapter):
            self.window = create_window(self.app, QSettings(str(self.root / "settings.ini"), QSettings.IniFormat))
        self.window.show()
        self.window.reference_player.audio_output.setMuted(True)
        self.window.select_reference(self.reference)
        self.wait_until(lambda: not self.window._importing)
        self.assertEqual(self.adapter.calls, [])  # Import never auto-transcribes.

    def tearDown(self):
        self.adapter.gate.set()
        self.window.transcript_editor.clear()
        self.window.speech_editor.clear()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.window.close()
        self.wait_until(lambda: not self.window.isVisible())
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def begin_delayed(self):
        self.adapter.gate.clear()
        self.adapter.started.clear()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.window.transcribe_reference())
        self.wait_until(self.adapter.started.is_set)

    def finish_delayed(self):
        self.adapter.gate.set()
        self.wait_until(lambda: not self.window.transcription.busy)

    def test_modes_manual_editing_confirmation_and_model_reuse(self):
        w = self.window
        self.assertEqual(w.session.cloning_mode, CloningMode.ICL)
        w.transcript_editor.setPlainText("Manual draft")
        w.cloning_mode.setCurrentIndex(1)
        self.assertFalse(w.transcript_editor.isEnabled())
        self.assertFalse(w.transcribe_button.isEnabled())
        self.assertFalse(w.transcribe_reference())
        w.cloning_mode.setCurrentIndex(0)
        self.assertTrue(w.transcript_editor.isEnabled())
        self.assertEqual(w.transcript_editor.toPlainText(), "Manual draft")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(w.transcribe_reference())
        self.assertEqual(w.session.transcript, "Manual draft")
        for _ in range(2):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                self.assertTrue(w.transcribe_reference())
            self.wait_until(lambda: not w.transcription.busy)
            self.assertEqual(w.session.transcript, "Recognized reference.")
        self.assertEqual(self.adapter.loads, 1)
        self.assertTrue(all(thread != threading.get_ident() for _, thread in self.adapter.calls))

    def test_responsive_loading_and_obsolete_edits_or_mode_changes(self):
        w = self.window
        self.begin_delayed()
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(10)
        QTest.qWait(250)
        timer.stop()
        self.assertGreater(len(ticks), 5)
        self.assertIn("s", w.transcription_status.text())
        self.assertTrue(w.transcript_editor.isEnabled())
        w.transcript_editor.setPlainText("Edited while transcribing")
        self.finish_delayed()
        self.assertEqual(w.session.transcript, "Edited while transcribing")
        self.begin_delayed()
        w.cloning_mode.setCurrentIndex(1)
        w.cloning_mode.setCurrentIndex(0)
        self.finish_delayed()
        self.assertEqual(w.session.transcript, "Edited while transcribing")

    def test_clear_new_voice_cancel_and_reference_replacement_during_work(self):
        w = self.window
        w.transcript_editor.setPlainText("Keep on cancel")
        w.speech_editor.setPlainText("Speech draft")
        self.begin_delayed()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(w.clear_reference())
            self.assertFalse(w.new_voice())
        self.assertIsNotNone(w._transcription_context)
        self.finish_delayed()
        self.assertEqual(w.session.transcript, "Recognized reference.")
        self.begin_delayed()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.clear_reference())
        self.finish_delayed()
        self.assertIsNone(w.session.reference)
        self.assertEqual(w.session.transcript, "")
        self.assertEqual(w.session.speech_text, "Speech draft")
        w.select_reference(self.reference)
        self.wait_until(lambda: not w._importing)
        self.begin_delayed()
        w.select_reference(self.replacement)
        self.wait_until(lambda: not w._importing)
        self.finish_delayed()
        self.assertEqual(w.session.reference, self.replacement.resolve())
        self.assertEqual(w.session.transcript, "")
        self.begin_delayed()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.new_voice())
        self.finish_delayed()
        self.assertFalse(w.session.has_content)
        self.assertEqual(w.session.cloning_mode, CloningMode.ICL)
        self.assertEqual(self.adapter.loads, 1)  # Resets keep the resident model.
        self.assertTrue(self.reference.is_file() and self.replacement.is_file())

    def test_errors_empty_results_and_close_during_native_work(self):
        w = self.window
        w.transcript_editor.setPlainText("Reviewed text")
        self.adapter.text = ""
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            w.transcribe_reference()
        self.wait_until(lambda: not w.transcription.busy)
        self.assertEqual(w.session.transcript, "Reviewed text")
        self.assertIn("No speech", w.transcription_status.text())
        self.adapter.error = RuntimeError("Broken local model")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), patch.object(QMessageBox, "warning") as warning:
            w.transcribe_reference()
            self.wait_until(lambda: not w.transcription.busy)
            warning.assert_called_once()
        self.assertEqual(w.session.transcript, "Reviewed text")
        self.adapter.error = None
        w.transcript_editor.clear()
        self.begin_delayed()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertFalse(w.close())
        self.assertTrue(w.isVisible())
        self.assertFalse(w.centralWidget().isEnabled())
        self.finish_delayed()
        self.wait_until(lambda: not w.isVisible())
        self.assertNotEqual(self.adapter.released_on, threading.get_ident())


if __name__ == "__main__":
    unittest.main()
