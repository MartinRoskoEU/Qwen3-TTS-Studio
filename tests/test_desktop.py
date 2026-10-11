"""Small desktop checks using temporary audio; no models or downloads."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, QSettings, QTimer, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QSlider

from qwen3_tts_studio.app import create_window
from qwen3_tts_studio.application.workspace import (
    WorkspacePaths, WorkspaceSession,
)
from qwen3_tts_studio.ui.dialogs import SettingsDialog
from qwen3_tts_studio.ui.main_window import Section
from qwen3_tts_studio.ui.theme import DARK, LIGHT


class WorkspaceChecks(unittest.TestCase):
    def test_project_paths_do_not_depend_on_working_directory(self):
        paths = WorkspacePaths.from_source()
        self.assertEqual(paths.root, Path(__file__).resolve().parents[1])
        for folder in (paths.models, paths.samples, paths.output):
            self.assertTrue(folder.is_dir())
            self.assertTrue((folder / ".gitkeep").is_file())

    def test_reference_validation_and_session_consistency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.WAV"
            second = root / "second.ogg"
            bad = root / "unsupported.mp3"
            for path in (first, second, bad):
                path.write_bytes(b"selection-only fixture; not valid audio")
            session = WorkspaceSession(speech_text="Keep this speech draft")
            session.select_reference(first)
            session.transcript = "First reference transcript"
            session.select_reference(first)
            self.assertEqual(session.transcript, "First reference transcript")
            for path, error in ((bad, ValueError), (root, ValueError),
                                (root / "missing.wav", FileNotFoundError)):
                with self.assertRaises(error):
                    session.select_reference(path)
                self.assertEqual(session.reference, first.resolve())
                self.assertEqual(session.transcript, "First reference transcript")
            session.select_reference(second)
            self.assertEqual(session.transcript, "")
            self.assertEqual(session.speech_text, "Keep this speech draft")
            self.assertEqual(first.read_bytes(), b"selection-only fixture; not valid audio")


class DesktopChecks(unittest.TestCase):
    def wait_until(self, predicate, timeout=5000):
        for _ in range(timeout // 10):
            if predicate():
                return
            QTest.qWait(10)
        self.assertTrue(predicate(), "Timed out waiting for audio import")

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.temp = tempfile.TemporaryDirectory()
        cls.settings = QSettings(str(Path(cls.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        cls.window = create_window(cls.app, cls.settings)
        cls.window.show()
        if not QTest.qWaitForWindowExposed(cls.window):
            raise AssertionError("The desktop window did not become visible")

    @classmethod
    def tearDownClass(cls):
        cls.window.transcript_editor.clear()
        cls.window.speech_editor.clear()
        cls.window.close()
        cls.app.processEvents()
        cls.temp.cleanup()

    def test_appearance_preferences_and_live_system_notification(self):
        window = self.window
        window.speech_editor.setPlainText("Draft retained across appearance changes")
        for mode, colors in (("light", LIGHT), ("dark", DARK), ("light", LIGHT)):
            window.theme.set_mode(mode)
            QTest.qWait(50)
            self.assertEqual(window.theme.current_theme, mode)
            self.assertEqual(self.app.palette().color(QPalette.ColorRole.Window).name(), colors.background)
            self.assertEqual(window.speech_editor.toPlainText(), "Draft retained across appearance changes")
        window.theme.set_mode("system")
        QTest.qWait(50)
        # Simulate Qt's supported notification, without changing Windows settings.
        for scheme, colors in ((Qt.ColorScheme.Light, LIGHT), (Qt.ColorScheme.Dark, DARK)):
            self.app.styleHints().colorSchemeChanged.emit(scheme)
            QTest.qWait(50)
            self.assertEqual(self.app.palette().color(QPalette.ColorRole.Window).name(), colors.background)
        self.app.styleHints().colorSchemeChanged.emit(self.app.styleHints().colorScheme())
        QTest.qWait(50)
        dialog = SettingsDialog(window.theme, window)
        self.assertEqual(dialog.selected_mode, "system")
        dialog.appearance.setCurrentIndex(dialog.appearance.findData("light"))
        dialog.reject()
        self.assertEqual(window.theme.mode, "system")
        def accept_settings():
            active = self.app.activeModalWidget()
            active.appearance.setCurrentIndex(active.appearance.findData("light"))
            active.accept()
        QTimer.singleShot(50, accept_settings)
        window.show_settings()
        self.assertEqual(window.theme.mode, "light")
        window.theme.set_mode("system")
        QTest.qWait(50)
        self.settings.sync()
        reloaded = QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
        self.assertEqual(reloaded.value("appearance"), "system")
        window.speech_editor.clear()

    def test_reference_and_draft_protection(self):
        import numpy as np
        import soundfile as sf

        window = self.window
        reference = Path(self.temp.name) / "reference.wav"
        replacement = Path(self.temp.name) / "replacement.ogg"
        samples = 0.1 * np.sin(2 * np.pi * 220 * np.arange(16000) / 16000)
        sf.write(reference, samples, 16000)
        sf.write(replacement, samples, 16000, format="OGG", subtype="VORBIS")
        with patch("qwen3_tts_studio.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(reference), "")):
            window.choose_reference_button.click()
        self.wait_until(lambda: not window._importing)
        self.assertEqual(window.session.reference, reference.resolve())
        self.assertEqual(window.reference_path.text(), reference.name)
        self.assertEqual(window.reference_player.duration_ms, 1000)
        window.transcript_editor.setPlainText("Reference draft")
        window.speech_editor.setPlainText("Hello")
        self.assertEqual(window.character_count.text(), "5 characters")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(window.select_reference(replacement))
        self.assertEqual(window.session.reference, reference.resolve())
        self.assertEqual(window.transcript_editor.toPlainText(), "Reference draft")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(window.select_reference(replacement))
        self.wait_until(lambda: not window._importing)
        self.assertEqual(window.transcript_editor.toPlainText(), "")
        self.assertEqual(window.speech_editor.toPlainText(), "Hello")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(window.close())
        self.assertTrue(window.isVisible())
        with patch.object(QMessageBox, "warning") as warning:
            self.assertTrue(window.select_reference(Path(self.temp.name) / "missing.wav"))
            self.wait_until(lambda: not window._importing)
            warning.assert_called_once()
        self.assertEqual(window.session.reference, replacement.resolve())
        window.speech_editor.clear()

    def test_resize_and_placeholder_boundaries(self):
        window = self.window

        def check_visible_contents():
            workspace = window.centralWidget()
            self.assertEqual(len(window.findChildren(Section)), 5)
            for section in window.findChildren(Section):
                origin = section.mapTo(workspace, section.rect().topLeft())
                self.assertTrue(workspace.rect().contains(origin))
                self.assertTrue(workspace.rect().contains(origin + section.rect().bottomRight()))
                for child in section.findChildren(QPushButton):
                    origin = child.mapTo(section, child.rect().topLeft())
                    self.assertTrue(section.rect().contains(origin + child.rect().bottomRight()), child.text())
            self.assertFalse(window.generate_button.isEnabled())
            for editor in (window.transcript_editor, window.speech_editor):
                self.assertGreaterEqual(editor.height(), editor.minimumHeight())
            self.assertEqual(window.output_section.width(), window.workspace_splitter.width())
            for player in (window.reference_player, window.output_player):
                self.assertGreaterEqual(player.waveform.height(), player.waveform.minimumHeight())
                self.assertTrue(player.rect().contains(player.waveform.geometry()))
                self.assertTrue(player.rect().contains(player.play_button.geometry()))
                self.assertGreaterEqual(player.play_button.y(), player.waveform.geometry().bottom() + player.layout().spacing())
            self.assertEqual(window.findChildren(QSlider), [])
            for control in (window.output_player.play_button, window.export_button):
                self.assertFalse(control.isEnabled())

        window.resize(1120, 900)
        QTest.qWait(50)
        self.assertGreaterEqual(window.output_section.height(), 200)
        self.assertLess(window.transcription_section.height(), window.speech_section.height())
        self.assertGreaterEqual(window.generation_section.height(), 200)
        window.speech_editor.setPlainText("Keep this draft while resizing")
        for width, height in ((900, 870), (1120, 900), (1500, 1080)):
            window.resize(width, height)
            QTest.qWait(50)
            self.assertEqual(window.width(), width)
            self.assertEqual(window.height(), height)
            check_visible_contents()

        window.resize(900, 870)
        for sizes in ([400, 450], [450, 400]):
            window.splitter.setSizes(sizes)
            QTest.qWait(50)
            check_visible_contents()
        for splitter in (window.left_splitter, window.right_splitter, window.workspace_splitter):
            self.assertFalse(splitter.childrenCollapsible())
            for position in (0, splitter.height()):
                splitter.moveSplitter(position, 1)
                QTest.qWait(50)
                self.assertTrue(all(size > 0 for size in splitter.sizes()))
                check_visible_contents()

        window.resize(1120, 900)
        window.workspace_splitter.setSizes([520, 230])
        window.left_splitter.setSizes([300, 220])
        window.right_splitter.setSizes([290, 230])
        QTest.qWait(50)
        handle = window.workspace_splitter.handle(1)
        before = window.workspace_splitter.sizes()
        point = handle.rect().center()
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseMove(handle, point + QPoint(0, -25))
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=point + QPoint(0, -25))
        QTest.qWait(50)
        self.assertNotEqual(window.workspace_splitter.sizes(), before)
        check_visible_contents()
        self.assertEqual(window.speech_editor.toPlainText(), "Keep this draft while resizing")
        window.speech_editor.clear()
        for module in ("torch", "qwen_tts", "faster_whisper"):
            self.assertNotIn(module, sys.modules)
        with patch("qwen3_tts_studio.ui.main_window.QDesktopServices.openUrl", return_value=True) as open_url:
            window.open_output_button.click()
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), str(window.paths.output).replace("\\", "/"))
        about_titles = []
        def close_about():
            active = self.app.activeModalWidget()
            about_titles.append(active.windowTitle())
            active.accept()
        QTimer.singleShot(50, close_about)
        window.show_about()
        self.assertEqual(about_titles, ["About Qwen3 TTS Studio"])

    def test_shutdown_through_exit_menu(self):
        self.window.speech_editor.clear()
        self.window.transcript_editor.clear()
        self.window.reference_player.audio_output.setMuted(True)
        self.window.reference_player.play()
        self.app.setQuitOnLastWindowClosed(True)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: self.app.exit(99))
        watchdog.start(3000)
        QTimer.singleShot(50, self.window.exit_action.trigger)
        self.assertEqual(self.app.exec(), 0)
        watchdog.stop()
        self.assertFalse(self.window.isVisible())
        self.assertIsNone(self.window.reference_player.media)
        self.assertFalse(self.window.reference_loader.has_workers)
        self.app.setQuitOnLastWindowClosed(False)


if __name__ == "__main__":
    unittest.main()
