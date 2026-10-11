"""Focused voice state/worker checks; actual inference remains a separate check."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from pathlib import Path
from io import BytesIO
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import soundfile as sf
from PySide6.QtCore import QEventLoop, QPoint, QSettings, QTimer, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from qwen3_tts_studio.app import create_window
from qwen3_tts_studio.application.voice_profile import VoiceProfile
from qwen3_tts_studio.application.workspace import CloningMode, ProfileStatus
from qwen3_tts_studio.application.generation_settings import GenerationSettings
from qwen3_tts_studio.audio.decoding import prepare_waveform
from qwen3_tts_studio.audio.memory import prepare_memory_recording
from qwen3_tts_studio.integrations.qwen_tts import GeneratedSpeech


class DelayedVoice:
    def __init__(self, models, output):
        self.models, self.output = models, output
        self.loaded = False
        self.gpu_error = ""
        self.preparations = 0
        self.generations = []
        self.generation_settings = []
        self.released_on = None

    def description(self):
        return "CPU · mock · SDPA"

    def prepare(self, arguments, cancelled, report):
        report("Creating voice profile... · CPU · mock · SDPA")
        time.sleep(.12)  # Deliberately emulate a non-interruptible native call.
        self.loaded = True
        self.preparations += 1
        mode = CloningMode.X_VECTOR_ONLY if arguments["x_vector_only_mode"] else CloningMode.ICL
        return VoiceProfile(uuid4().hex, mode, {}, ({},), "fixture", Path(arguments["ref_audio"]))

    def generate(self, profile, text, settings, cancelled, report):
        report("Generating speech... · CPU · mock · SDPA")
        time.sleep(.12)
        self.generations.append((profile.identifier, text))
        self.generation_settings.append(settings)
        recording = prepare_memory_recording(np.sin(np.arange(16000) * .1).astype(np.float32) * .05,
                                             16000, "speech.wav", {"text": text})
        return GeneratedSpeech(recording, profile.identifier, text, .12, "cpu", "mock", "sdpa")

    def release(self):
        self.loaded = False
        self.released_on = threading.get_ident()


class VoiceChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reference = self.root / "reference.wav"
        sf.write(self.reference, np.zeros(8000, dtype=np.float32), 16000)
        self.adapter = None
        def factory(models):
            self.adapter = DelayedVoice(models, self.root)
            return self.adapter
        with patch("qwen3_tts_studio.application.voice_jobs.QwenVoiceModel", side_effect=factory):
            self.w = create_window(self.app, QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat))
        self.w.show()
        self.assertTrue(self.w.select_reference(self.reference))
        self.wait(lambda: not self.w._importing)
        self.w.transcript_editor.setPlainText("Reference words")
        self.w.speech_editor.setPlainText("First text")

    def tearDown(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.w.close()
        self.wait(lambda: not self.w.voice.has_workers)
        self.w.release_resources()
        self.w.reference_loader.wait_for_shutdown()
        self.w.transcription.wait_for_shutdown()
        self.w.voice.wait_for_shutdown()
        self.temp.cleanup()

    def wait(self, condition):
        for _ in range(500):
            if condition():
                return
            QTest.qWait(10)
        self.assertTrue(condition(), "Voice worker timed out")

    def idle(self):
        self.wait(lambda: not self.w.voice.busy and self.w._output_context is None)

    def prepare(self):
        self.assertTrue(self.w.prepare_voice())
        self.idle()
        self.assertIsNotNone(self.w.session.profile)

    def test_cached_profile_generation_export_and_invalidation(self):
        w = self.w
        self.prepare()
        profile = w.session.profile
        for text in ("Same words", "Same words", "Different words"):
            w.speech_editor.setPlainText(text)
            self.assertIs(w.session.profile, profile)
            self.assertTrue(w.generate_speech())
            self.assertFalse(w.generate_speech())
            self.idle()
            self.assertTrue(w.output_player.play_button.isEnabled())
            self.assertTrue(w.export_button.isEnabled())
        self.assertEqual(self.adapter.preparations, 1)
        self.assertEqual(self.adapter.generations, [(profile.identifier, text) for text in ("Same words", "Same words", "Different words")])
        self.assertEqual(len(list(self.root.glob("*.wav"))), 1)
        destination = self.root / "copy.wav"
        self.assertTrue(w.export_wav(destination))
        self.idle()
        self.assertEqual(destination.read_bytes(), w.session.output.wav_data)
        decoded, rate = sf.read(BytesIO(destination.read_bytes()), dtype="float32")
        self.assertEqual(rate, w.session.output.sample_rate)
        np.testing.assert_array_equal(decoded, np.frombuffer(w.session.output.pcm, dtype="<f4"))
        self.assertIn(destination.name, w.output_status.text())
        with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
            w.choose_export_wav()
        self.assertEqual(len(list(self.root.glob("*.wav"))), 2)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(w.export_wav(destination))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(w.export_wav(destination))
            self.idle()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "warning") as warning:
            self.assertTrue(w.select_reference(self.root / "missing.wav"))
            self.wait(lambda: not w._importing)
            warning.assert_called_once()
        self.assertIs(w.session.profile, profile)
        w.transcript_editor.insertPlainText(" correction")
        self.assertIsNone(w.session.profile)
        self.assertEqual(w.session.profile_status, ProfileStatus.NEEDS_PREPARATION)
        self.assertFalse(w.generate_button.isEnabled())
        self.prepare()
        w.cloning_mode.setCurrentIndex(w.cloning_mode.findData(CloningMode.X_VECTOR_ONLY))
        self.assertIsNone(w.session.profile)
        self.prepare()
        self.assertEqual(w.session.profile.mode, CloningMode.X_VECTOR_ONLY)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.clear_reference())
        self.assertIsNone(w.session.profile)
        self.assertEqual(w.session.speech_text, "Different words")

    def test_settings_snapshots_reset_and_profile_reuse(self):
        w = self.w
        self.prepare()
        profile = w.session.profile
        panel = w.advanced_settings
        self.assertFalse(panel.toggle.isChecked())
        w.resize(900, 870)
        panel.toggle.setChecked(True)
        QTest.qWait(50)
        self.assertEqual((w.width(), w.height()), (900, 870))
        self.assertTrue(panel.panel.isVisible())
        for control in (*panel.controls.values(), panel.language, panel.reset):
            origin = control.mapTo(panel, QPoint(0, 0))
            self.assertTrue(panel.rect().contains(origin + control.rect().bottomRight()))
            self.assertGreaterEqual(control.height(), 28)
        panel.controls["temperature"].setValue(1.2)
        first = w.session.generation_settings
        self.assertTrue(w.generate_speech())
        panel.controls["temperature"].setValue(.6)
        panel.controls["top_k"].setValue(20)
        second = w.session.generation_settings
        self.idle()
        self.assertEqual(self.adapter.generation_settings, [first])
        self.assertIs(w.session.profile, profile)
        self.assertTrue(w.generate_speech())
        self.idle()
        self.assertEqual(self.adapter.generation_settings, [first, second])
        self.assertEqual(self.adapter.preparations, 1)
        self.assertEqual(list(self.root.glob("*.wav")), [self.reference])
        panel.reset.click()
        self.assertEqual(w.session.generation_settings, w.generation_defaults)
        self.assertIs(w.session.profile, profile)
        panel.controls["top_p"].setValue(.7)
        w.clear_profile()
        self.assertEqual(w.session.generation_settings.top_p, .7)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.new_voice())
        self.assertEqual(w.session.generation_settings, w.generation_defaults)
        self.assertFalse(w.has_unsaved_changes)

    def test_session_save_open_dirty_and_recovery(self):
        w = self.w
        w.speech_editor.setPlainText("Žltý kôň — 日本語 🎵")
        w.advanced_settings.controls["temperature"].setValue(1.3)
        destination = self.root / "session.qtts.json"
        self.assertTrue(w.save_workspace_session(destination))
        self.assertFalse(w.has_unsaved_changes)
        w.speech_editor.insertPlainText(" edit")
        self.assertTrue(w.has_unsaved_changes)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(w.open_workspace_session(destination))
            self.assertFalse(w.new_voice())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.open_workspace_session(destination))
            self.wait(lambda: w._session_pending is None)
            self.idle()
        self.assertEqual(w.session.speech_text, "Žltý kôň — 日本語 🎵")
        self.assertEqual(w.session.transcript, "Reference words")
        self.assertEqual(w.session.reference, self.reference)
        self.assertEqual(w.session.generation_settings.temperature, 1.3)
        self.assertFalse(w.has_unsaved_changes)
        with patch.object(QMessageBox, "warning") as warning:
            bad = self.root / "bad.json"
            bad.write_text("not json", encoding="utf-8")
            self.assertTrue(w.open_workspace_session(bad))
            self.wait(lambda: w._session_pending is None)
            self.idle()
            warning.assert_called_once()
        self.assertEqual(w.session_path, destination)
        self.assertEqual(w.session.speech_text, "Žltý kôň — 日本語 🎵")
        self.prepare()
        self.assertTrue(w.generate_speech())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.open_workspace_session(destination))
            self.wait(lambda: w._session_pending is None)
            self.idle()
        self.assertIsNone(w.session.output)
        self.assertIsNone(w.session.profile)
        self.assertEqual(w.session.speech_text, "Žltý kôň — 日本語 🎵")

    def test_exit_save_discard_cancel_failure_and_unchanged(self):
        w = self.w
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(w.close())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save), \
             patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
            self.assertFalse(w.close())
            self.assertFalse(w.new_voice())
        destination = self.root / "session.qtts.json"
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save), \
             patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "")):
            self.assertTrue(w.new_voice())
        self.assertTrue(destination.is_file())
        self.assertFalse(w.has_unsaved_changes)
        w.speech_editor.setPlainText("New draft")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save), \
             patch("qwen3_tts_studio.ui.main_window.save_session", side_effect=OSError("Disk failure")), \
             patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "")), \
             patch.object(QMessageBox, "warning"):
            self.assertFalse(w.close())
            self.assertFalse(w._closing)
        self.assertTrue(w.save_workspace_session(destination))
        with patch.object(QMessageBox, "question") as question:
            self.assertTrue(w.close())
            question.assert_not_called()

    def test_exit_save_commits_latest_draft(self):
        import json
        w = self.w
        destination = self.root / "session.qtts.json"
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save), \
             patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "")):
            self.assertTrue(w.close())
        saved = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(saved["speech_text"], "First text")
        self.assertEqual(saved["reference_transcription"], "Reference words")

    def test_profile_import_validation_and_confirmation_preserve_state(self):
        w = self.w
        self.prepare()
        original = w.session.profile
        imported = VoiceProfile(uuid4().hex, CloningMode.X_VECTOR_ONLY, {}, ({},), "fixture", imported_from=self.root / "voice.pt")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(w.load_voice_profile(imported.imported_from))
        self.assertIs(w.session.profile, original)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "warning") as warning, \
             patch("qwen3_tts_studio.application.voice_jobs.load_profile", side_effect=ValueError("Incompatible profile")):
            self.assertTrue(w.load_voice_profile(imported.imported_from))
            self.idle()
            warning.assert_called_once()
        self.assertIs(w.session.profile, original)
        self.assertEqual(w.session.transcript, "Reference words")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch("qwen3_tts_studio.application.voice_jobs.load_profile", return_value=imported):
            self.assertTrue(w.load_voice_profile(imported.imported_from))
            self.idle()
        self.assertIs(w.session.profile, imported)
        self.assertEqual(w.session.cloning_mode, CloningMode.X_VECTOR_ONLY)
        self.assertIsNone(w.session.reference)
        self.assertEqual(w.session.transcript, "")
        self.assertEqual(w.session.speech_text, "First text")
        self.assertTrue(w.session.reference_locked)
        self.assertFalse(w.reference_section.isEnabled())
        self.assertFalse(w.reference_section.acceptDrops())
        self.assertFalse(w.transcription_section.isEnabled())
        self.assertFalse(w.prepare_button.isEnabled())
        self.assertTrue(w.load_profile_button.isEnabled())
        self.assertFalse(w.select_reference(self.reference))
        self.assertFalse(w.transcribe_reference())
        self.assertFalse(w.prepare_voice())
        w.transcript_editor.setPlainText("Programmatic edit rejected")
        w.cloning_mode.setCurrentIndex(w.cloning_mode.findData(CloningMode.ICL))
        self.assertEqual(w.transcript_editor.toPlainText(), "")
        self.assertEqual(w.session.cloning_mode, imported.mode)
        self.assertIs(w.session.profile, imported)
        with self.assertRaises(ValueError):
            w.session.clear_reference()
        self.assertIs(w.session.profile, imported)
        self.assertTrue(w.generate_speech())
        self.idle()
        self.assertIsNotNone(w.session.output)
        saved = self.root / "saved.pt"
        saved.write_bytes(b"previous profile")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(w.save_voice_profile(saved))
        self.assertEqual(saved.read_bytes(), b"previous profile")
        replacement = VoiceProfile(uuid4().hex, CloningMode.ICL, {}, ({},), "fixture", imported_from=self.root / "second.pt")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch("qwen3_tts_studio.application.voice_jobs.load_profile", return_value=replacement):
            self.assertTrue(w.load_voice_profile(replacement.imported_from))
            self.idle()
        self.assertIs(w.session.profile, replacement)
        self.assertEqual(w.session.profile_name, "second")
        self.assertTrue(w.session.reference_locked)
        output = w.session.output
        self.assertTrue(w.clear_profile())
        self.assertEqual(w.session.profile_status, ProfileStatus.NOT_PREPARED)
        self.assertFalse(w.session.reference_locked)
        self.assertTrue(w.reference_section.isEnabled() and w.reference_section.acceptDrops())
        self.assertTrue(w.transcript_editor.isEnabled())
        self.assertEqual(w.session.speech_text, "First text")
        self.assertEqual(w.session.output, output)
        self.assertTrue(self.adapter.loaded)

        self.assertTrue(w.select_reference(self.reference))
        self.wait(lambda: not w._importing)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch("qwen3_tts_studio.application.voice_jobs.load_profile", return_value=replacement):
            self.assertTrue(w.load_voice_profile(replacement.imported_from))
            self.idle()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(w.new_voice())
        self.assertIs(w.session.profile, replacement)
        self.assertTrue(w.session.reference_locked)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.new_voice())
        self.assertIsNone(w.session.profile)
        self.assertFalse(w.session.reference_locked)
        self.assertEqual(w.session.cloning_mode, CloningMode.ICL)
        self.assertTrue(w.reference_section.isEnabled())
        self.assertIsNotNone(output)
        self.assertTrue(self.adapter.loaded)


    def test_memory_playback_stop_and_completion_race(self):
        w = self.w
        w.hide()
        self.prepare()
        profile = w.session.profile
        self.assertTrue(w.generate_speech())
        self.idle()
        previous = w.session.output
        player = w.output_player
        player.audio_output.setMuted(True)
        self.assertIsNotNone(player.media.sourceDevice())
        self.assertFalse(player.media.source().isLocalFile())
        self.assertTrue(player.media.isSeekable())
        player.play_button.click()
        self.wait(lambda: player.media.position() > 100)
        player.play_button.click()
        self.wait(lambda: player.media.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        player.seek(400)
        QTest.qWait(40)
        self.assertAlmostEqual(player.waveform.position_ms, 400, delta=10)
        area = player.waveform._area()
        QTest.mousePress(player.waveform, Qt.MouseButton.LeftButton, pos=area.center())
        QTest.mouseMove(player.waveform, QPoint(area.left() + area.width() * 3 // 4, area.center().y()))
        QTest.mouseRelease(player.waveform, Qt.MouseButton.LeftButton,
                           pos=QPoint(area.left() + area.width() * 3 // 4, area.center().y()))
        self.assertAlmostEqual(player.media.position(), player.duration_ms * .75, delta=20)
        player.play_button.click()
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        def finished(status):
            if status == QMediaPlayer.MediaStatus.EndOfMedia:
                loop.quit()
        player.media.mediaStatusChanged.connect(finished)
        timeout.start(3000)
        loop.exec()
        timeout.stop()
        player.media.mediaStatusChanged.disconnect(finished)
        self.assertEqual(player.media.mediaStatus(), QMediaPlayer.MediaStatus.EndOfMedia)
        player.play_button.click()
        self.wait(lambda: player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState)

        entered, finish = threading.Event(), threading.Event()
        native = self.adapter.generate
        def blocked(*args):
            entered.set()
            finish.wait(3)
            return native(*args)
        with patch.object(self.adapter, "generate", side_effect=blocked):
            self.assertTrue(w.generate_speech())
            self.wait(entered.is_set)
            self.assertTrue(w.stop_generation_button.isEnabled())
            w.stop_generation_button.click()
            self.assertFalse(w.stop_generation())
            self.assertEqual(w.generation_status.text(), "Stopping generation...")
            self.assertTrue(w.generation_progress.active)
            self.assertTrue(w.voice.busy)
            self.assertFalse(w.generate_speech())
            self.assertFalse(w.generate_button.isEnabled())
            QTest.qWait(80)
            self.assertIs(w.session.output, previous)
            self.assertIs(player.recording, previous)
            self.assertIs(w.session.profile, profile)
            finish.set()
            self.idle()
        self.assertEqual(w.generation_status.text(), "Generation canceled.")
        self.assertFalse(w.generation_progress.active)
        self.assertTrue(w.generate_button.isEnabled())
        self.assertFalse(w.stop_generation_button.isEnabled())
        self.assertIs(w.session.output, previous)
        self.assertTrue(self.adapter.loaded)
        self.assertEqual(len(list(self.root.glob("*.wav"))), 1)

        # Cancel after the worker publishes, before Qt accepts the new buffer.
        def cancel_ready(operation, result):
            if operation == "generate":
                self.assertTrue(w.stop_generation())
        w.voice.ready.connect(cancel_ready)
        self.assertTrue(w.generate_speech())
        self.idle()
        w.voice.ready.disconnect(cancel_ready)
        self.assertIs(w.session.output, previous)
        self.assertIs(player.recording, previous)
        self.assertEqual(w.generation_status.text(), "Generation canceled.")

    def test_progress_failure_and_clear_during_profile_loading(self):
        w = self.w
        self.assertTrue(w.prepare_voice())
        self.assertTrue(w.preparation_progress.active)
        self.assertEqual(w.preparation_progress.bar.maximum(), 0)
        self.assertFalse(w.generation_progress.active)
        self.idle()
        self.assertEqual(w.preparation_progress.stage.text(), "Voice profile ready.")
        self.assertFalse(w.preparation_progress.active)
        self.assertIn("CPU", w.preparation_progress.details.text())
        self.assertTrue(w.generate_speech())
        self.assertTrue(w.generation_progress.active)
        self.assertFalse(w.generate_button.isEnabled())
        stages = []
        w.voice.ready.connect(lambda op, result: stages.append((w.generation_progress.active, w.generation_progress.stage.text())) if op == "generate" else None)
        self.idle()
        self.assertIn((True, "Preparing output playback..."), stages)
        self.assertEqual(w.generation_progress.stage.text(), "Generation completed.")
        self.assertIn("Generation completed", w.statusBar().currentMessage())
        self.assertFalse(w.generation_progress.active)
        self.assertTrue(w.generate_button.isEnabled())
        output = w.session.output
        with patch.object(self.adapter, "generate", side_effect=RuntimeError("fixture failure")), \
             patch.object(QMessageBox, "warning") as warning:
            self.assertTrue(w.generate_speech())
            self.idle()
            warning.assert_called_once()
        self.assertEqual(w.session.output, output)
        self.assertIs(w.output_player.recording, output)
        self.assertEqual(w.generation_progress.stage.property("error"), "true")
        self.assertFalse(w.generation_progress.active)
        self.assertTrue(w.generate_button.isEnabled())
        imported = VoiceProfile(uuid4().hex, CloningMode.ICL, {}, ({},), "fixture", imported_from=self.root / "late.pt")
        def delayed_load(*args):
            time.sleep(.1)
            return imported
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch("qwen3_tts_studio.application.voice_jobs.load_profile", side_effect=delayed_load):
            self.assertTrue(w.load_voice_profile(imported.imported_from))
            self.assertTrue(w.clear_profile())
            self.idle()
        self.assertIsNone(w.session.profile)
        self.assertFalse(w.session.reference_locked)
        self.assertFalse(w.preparation_progress.active)
        self.assertTrue(w.reference_section.isEnabled())
        self.assertTrue(self.adapter.loaded)

    def test_reset_during_native_work_and_shutdown(self):
        w = self.w
        heartbeat = []
        timer = QTimer(w)
        timer.setInterval(10)
        timer.timeout.connect(lambda: heartbeat.append(1))
        timer.start()
        self.assertTrue(w.prepare_voice())
        self.assertTrue(w.clear_profile())
        self.idle()
        self.assertIsNone(w.session.profile)
        self.assertEqual(w.session.transcript, "Reference words")
        self.assertTrue(w.prepare_voice())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(w.new_voice())
        self.idle()
        self.assertIsNotNone(w.session.profile)
        self.assertGreater(len(heartbeat), 3)
        self.assertTrue(w.generate_speech())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.new_voice())
        self.idle()
        self.assertIsNone(w.session.profile)
        self.assertIsNone(w.session.output)
        self.assertFalse(w.output_player.has_content)
        self.assertTrue(self.adapter.loaded)
        self.assertTrue(self.reference.exists())
        self.assertTrue(w.select_reference(self.reference))
        self.wait(lambda: not w._importing)
        w.transcript_editor.setPlainText("New transcript")
        self.assertTrue(w.prepare_voice())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.clear_reference())
        self.idle()
        self.assertIsNone(w.session.profile)
        self.assertTrue(w.select_reference(self.reference))
        self.wait(lambda: not w._importing)
        w.transcript_editor.setPlainText("One last transcript")
        self.prepare()
        # Reset after generation has returned but before Qt accepts its pending
        # playback source. Neither the profile nor preview may reappear.
        def reset_on_generation(operation, result):
            if operation == "generate":
                w.new_voice()
        w.voice.ready.connect(reset_on_generation)
        w.speech_editor.setPlainText("Check pending output reset")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(w.generate_speech())
            self.idle()
        w.voice.ready.disconnect(reset_on_generation)
        self.assertIsNone(w.session.output)
        self.assertFalse(w.output_player.has_content)
        self.assertTrue(w.select_reference(self.reference))
        self.wait(lambda: not w._importing)
        w.transcript_editor.setPlainText("Close during preparation")
        self.assertTrue(w.prepare_voice())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            w.close()
        self.wait(lambda: not w.voice.has_workers)
        self.assertNotEqual(self.adapter.released_on, threading.get_ident())
        self.assertFalse(self.adapter.loaded)


class SerializationChecks(unittest.TestCase):
    def test_application_state_guards_reference_inputs(self):
        from qwen3_tts_studio.application.workspace import WorkspaceSession
        reference = Path("reference.wav")
        session = WorkspaceSession(reference=reference, transcript="Reference", speech_text="Speech")
        prepared = VoiceProfile(uuid4().hex, CloningMode.ICL, {}, ({},), "fixture", reference)
        session.accept_profile(prepared)
        session.speech_text = "Changed speech"
        self.assertIs(session.profile, prepared)
        session.transcript = "Corrected reference"
        self.assertIsNone(session.profile)
        self.assertEqual(session.profile_status, ProfileStatus.NEEDS_PREPARATION)
        imported = VoiceProfile(uuid4().hex, CloningMode.X_VECTOR_ONLY, {}, ({},), "fixture", imported_from=Path("imported.pt"))
        session.accept_profile(imported)
        self.assertTrue(session.reference_locked)
        self.assertIsNone(session.reference)
        self.assertEqual(session.transcript, "")
        for attribute, value in (("reference", reference), ("transcript", "New reference"), ("cloning_mode", CloningMode.ICL)):
            with self.assertRaises(ValueError):
                setattr(session, attribute, value)
        with self.assertRaises(ValueError):
            session.voice_clone_arguments()
        self.assertIs(session.profile, imported)
        self.assertTrue(session.can_generate)
        session.clear_profile()
        self.assertFalse(session.reference_locked)
        self.assertEqual(session.speech_text, "Changed speech")
        session.reference = reference
        session.cloning_mode = CloningMode.ICL
        session.transcript = "Now editable"
        self.assertTrue(session.can_prepare)

    def test_tensor_only_round_trip_and_invalid_profiles(self):
        # Isolate Torch so normal desktop checks still verify lazy AI imports.
        code = r'''
from pathlib import Path
import tempfile
import torch
from qwen3_tts_studio.application.workspace import WorkspacePaths, CloningMode
from qwen3_tts_studio.application.voice_profile import *
models = WorkspacePaths.from_source().models
identity = model_identity(models)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "voice.pt"
    for mode in CloningMode:
        icl = mode == CloningMode.ICL
        item = {"ref_spk_embedding": torch.ones(identity["embedding_size"]),
                "ref_code": torch.zeros((4, identity["code_groups"]), dtype=torch.int64) if icl else None,
                "ref_text": "Reference words" if icl else None,
                "icl_mode": icl, "x_vector_only_mode": not icl}
        profile = VoiceProfile("a" * 32, mode, identity, (item,), "fixture")
        save_profile(profile, path, path.exists(), lambda: False)
        loaded = load_profile(path, models, lambda: False)
        assert loaded.mode == mode and loaded.source_reference is None
        assert torch.equal(loaded.items[0]["ref_spk_embedding"], item["ref_spk_embedding"])
        payload = torch.load(path, weights_only=True)
        payload["compatibility"]["configuration_sha256"] = "wrong-model"
        torch.save(payload, path)
        try: load_profile(path, models, lambda: False)
        except ValueError: pass
        else: raise AssertionError("Incompatible model accepted")
        bad = {**item, "ref_spk_embedding": torch.full((identity["embedding_size"],), float("nan"))}
        try: validate_items([bad], mode, identity)
        except ValueError: pass
        else: raise AssertionError("Nonfinite embedding accepted")
    torch.save({"unsafe_object": Path("not-a-tensor")}, path)
    try: load_profile(path, models, lambda: False)
    except Exception as error: assert "Weights only load failed" in str(error)
    else: raise AssertionError("Arbitrary Python object accepted")
print("Safe profile round trips and rejection checks passed")
'''
        completed = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                   capture_output=True, text=True, timeout=90)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
