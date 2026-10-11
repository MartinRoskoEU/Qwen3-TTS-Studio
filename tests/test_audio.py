"""Focused codec, transport, drop, and cancellation checks using local fixtures."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PySide6.QtCore import QAbstractAnimation, QEvent, QEventLoop, QMimeData, QObject, QPoint, QPointF, QSettings, QTimer, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from qwen3_tts_studio.app import create_window
from qwen3_tts_studio.application.audio_loader import AudioLoader
from qwen3_tts_studio.audio.decoding import DecodeCancelled, prepare_waveform
from qwen3_tts_studio.ui.audio_player import AudioPlayer
from qwen3_tts_studio.ui.theme import DARK, LIGHT


class AudioChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        t = np.arange(48000) / 16000
        # A changing envelope makes incorrect or synthetic waveform data evident.
        samples = 0.25 * np.sin(2 * np.pi * 220 * t) * (0.2 + 0.8 * np.sin(np.pi * t / 3) ** 2)
        cls.wav = cls.root / "reference.wav"
        cls.ogg = cls.root / "reference.ogg"
        sf.write(cls.wav, np.column_stack((samples, -samples)), 16000)
        sf.write(cls.ogg, samples, 16000, format="OGG", subtype="VORBIS")

    @classmethod
    def tearDownClass(cls):
        cls.app.processEvents()
        cls.temp.cleanup()

    def wait_until(self, predicate, timeout=5000):
        if predicate():
            return
        # Multimedia completion needs the same native event-loop dispatch as
        # the application, rather than repeated processEvents-style polling.
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(timeout)
        loop.exec()
        poll.stop()
        deadline.stop()
        self.assertTrue(predicate(), "Timed out waiting for the audio backend/worker")

    def make_window(self):
        return create_window(self.app, QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat))

    def test_decode_envelope_validation_and_cancellation(self):
        digest = hashlib.sha256(self.wav.read_bytes()).digest()
        for path in (self.wav, self.ogg):
            recording = prepare_waveform(path)
            self.assertEqual(recording.duration_ms, 3000)
            self.assertLessEqual(len(recording.lower), 4096)
            self.assertEqual(len(recording.lower), len(recording.upper))
            self.assertGreater(max(recording.upper), 0.24)
            self.assertLess(min(recording.lower), -0.24)
            self.assertGreater(max(recording.upper) - min(recording.upper), 0.15)
        self.assertEqual(hashlib.sha256(self.wav.read_bytes()).digest(), digest)
        corrupt = self.root / "corrupt.wav"
        corrupt.write_bytes(b"not audio")
        empty = self.root / "empty.wav"
        sf.write(empty, np.empty(0), 16000)
        disguised = self.root / "disguised.wav"
        sf.write(disguised, np.zeros(100), 16000, format="FLAC")
        for path in (corrupt, empty, disguised, self.root / "missing.ogg", self.root / "unsupported.mp3"):
            with self.assertRaises((ValueError, OSError, sf.SoundFileError)):
                prepare_waveform(path)
        with self.assertRaises(DecodeCancelled):
            prepare_waveform(self.wav, lambda: True)

    def test_play_pause_resume_seek_scrub_complete_and_replace(self):
        player = AudioPlayer()
        player.resize(650, 190)
        player.show()
        player.audio_output.setMuted(True)
        errors = []
        player.load_failed.connect(errors.append)
        player.playback_error.connect(errors.append)
        try:
            for path in (self.wav, self.ogg):
                old_media = player.media
                destroyed = QSignalSpy(old_media.destroyed) if old_media else None
                player.load_recording(prepare_waveform(path))
                self.wait_until(lambda: player.recording is not None and player.recording.path == path and player.waveform.seekable)
                self.assertEqual(player.duration_ms, 3000)
                if destroyed is not None:
                    self.wait_until(lambda: destroyed.count() == 1)
                player.play_button.click()
                self.wait_until(lambda: player.media.position() > 100)
                self.assertEqual(player.media.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
                self.wait_until(lambda: player.play_button.text() == "Pause")
                self.assertTrue(player.play_button.isEnabled())
                first_head = player.waveform.position_ms
                QTest.qWait(25)
                self.assertGreater(player.waveform.position_ms, first_head)
                self.assertLess(abs(player.waveform.position_ms - player.media.position()), 220)
                player.play_button.click()
                paused = player.media.position()
                QTest.qWait(100)
                self.assertEqual(player.media.position(), paused)
                self.assertEqual(player.waveform.position_ms, paused)
                self.assertEqual(player.play_button.text(), "Play")
                self.assertEqual(player._animation.state(), QAbstractAnimation.State.Stopped)
                view = player.waveform
                area = view._area()
                middle = QPoint(area.center().x(), area.center().y())
                QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=middle)
                self.assertAlmostEqual(player.media.position(), 1500, delta=15)
                self.assertEqual(player.media.playbackState(), QMediaPlayer.PlaybackState.PausedState)
                target = QPoint(area.left() + round((area.width() - 1) * 0.75), area.center().y())
                QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=middle)
                QTest.mouseMove(view, target)
                self.assertAlmostEqual(view.position_ms, 2250, delta=15)
                # A late backend notification must not override the mouse.
                player.media.positionChanged.emit(paused)
                QTest.qWait(20)
                self.assertAlmostEqual(view.position_ms, 2250, delta=15)
                QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=target)
                self.assertAlmostEqual(player.media.position(), 2250, delta=15)
                player.play_button.click()
                self.wait_until(lambda: player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
                QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=target)
                self.assertEqual(player.media.playbackState(), QMediaPlayer.PlaybackState.PausedState)
                QTest.mouseMove(view, middle)
                QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=middle)
                self.wait_until(lambda: player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
                player.seek(player.duration_ms - 150)
                self.wait_until(lambda: player.media.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia)
                self.assertEqual(view.position_ms, player.duration_ms)
                self.assertTrue(player.play_button.isEnabled())
                self.assertEqual(player.play_button.text(), "Play")
                self.assertEqual(player._animation.state(), QAbstractAnimation.State.Stopped)
                # Seeking away from completion must retain the chosen position.
                QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=middle)
                self.assertAlmostEqual(view.position_ms, 1500, delta=15)
                player.play_button.click()
                self.wait_until(lambda: player.media.position() > 1600)
                player.seek(player.duration_ms - 100)
                self.wait_until(lambda: player.media.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia)
                player.play_button.click()
                self.wait_until(lambda: 0 < player.media.position() < 1000)
                player.pause()
            self.assertEqual(errors, [])
        finally:
            player.release()
            player.close()
            QTest.qWait(50)
        self.assertIsNone(player.media)

    def test_drop_invalid_replacement_and_latest_import_wins(self):
        window = self.make_window()
        window.show()
        try:
            for path in (self.wav, self.ogg):
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(path))])
                enter = QDragEnterEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(window.reference_section, enter)
                self.assertTrue(enter.isAccepted())
                drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(window.reference_section, drop)
                self.assertTrue(drop.isAccepted())
                self.wait_until(lambda: not window._importing)
                self.assertEqual(window.session.reference, path.resolve())
            window.transcript_editor.setPlainText("Keep the reviewed transcript")
            previous = window.reference_player.media
            corrupt = self.root / "corrupt.ogg"
            corrupt.write_bytes(b"not audio")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), patch.object(QMessageBox, "warning") as warning:
                window.select_reference(corrupt)
                self.wait_until(lambda: not window._importing)
                warning.assert_called_once()
            self.assertIs(window.reference_player.media, previous)
            self.assertEqual(window.transcript_editor.toPlainText(), "Keep the reviewed transcript")
            self.assertFalse(window.transcript_editor.isReadOnly())
            with patch.object(QMessageBox, "warning") as warning:
                self.assertFalse(window.select_reference(self.root / "unsupported.mp3"))
                warning.assert_called_once()
            window.transcript_editor.clear()
            window.select_reference(self.wav)
            window.select_reference(self.ogg)
            self.wait_until(lambda: not window._importing and not window.reference_loader.has_workers)
            self.assertEqual(window.session.reference, self.ogg.resolve())
            self.assertFalse(window.output_player.play_button.isEnabled())
            self.assertFalse(window.output_player.waveform.seekable)
        finally:
            window.transcript_editor.clear()
            window.close()
            self.wait_until(lambda: not window.reference_loader.has_workers and not window.isVisible())

    def test_obsolete_completion_and_close_during_preparation(self):
        old_recording = prepare_waveform(self.wav)
        new_recording = prepare_waveform(self.ogg)
        started = threading.Event()
        finish = threading.Event()
        loader = AudioLoader()
        ready = []
        loader.ready.connect(ready.append)

        def controlled_decode(path, cancelled):
            if path == self.wav:
                started.set()
                finish.wait(3)
                # Simulate completion racing with an interruption request.
                return old_recording
            return new_recording

        try:
            with patch("qwen3_tts_studio.application.audio_loader.prepare_waveform", controlled_decode):
                loader.load(self.wav)
                self.wait_until(started.is_set)
                loader.load(self.ogg)
                self.wait_until(lambda: len(ready) == 1)
                finish.set()
                self.wait_until(lambda: not loader.has_workers)
                self.assertEqual([r.path for r in ready], [self.ogg.resolve()])
        finally:
            finish.set()
            loader.shutdown()
            self.wait_until(lambda: not loader.has_workers)

        started.clear()
        finish.clear()
        window = self.make_window()
        window.show()
        try:
            with patch("qwen3_tts_studio.application.audio_loader.prepare_waveform", controlled_decode):
                window.select_reference(self.wav)
                self.wait_until(started.is_set)
                window.close()
                self.assertTrue(window.reference_loader.has_workers)
                self.assertTrue(window.isVisible())
                QTest.qWait(40)  # The UI event loop remains responsive while closing.
                self.assertIsNone(window.reference_player.media)
                finish.set()
                self.wait_until(lambda: not window.isVisible() and not window.reference_loader.has_workers)
                self.assertIsNone(window.session.reference)
        finally:
            finish.set()
            window.release_resources()
            self.wait_until(lambda: not window.reference_loader.has_workers)
            window.close()

    def test_cached_rendering_and_continuous_animation(self):
        window = self.make_window()
        window.show()
        player = window.reference_player
        player.audio_output.setMuted(True)
        try:
            window.select_reference(self.wav)
            self.wait_until(lambda: not window._importing)
            view = player.waveform
            for mode, colors in (("light", LIGHT), ("dark", DARK)):
                window.theme.set_mode(mode)
                QTest.qWait(50)
                player.seek(1500)
                image = view.grab().toImage()
                area = view._area()
                played_x = area.left() + area.width() // 4
                unplayed_x = area.left() + 3 * area.width() // 4
                self.assertEqual(image.pixelColor(played_x, area.center().y()).name(), colors.waveform_played)
                self.assertEqual(image.pixelColor(unplayed_x, area.center().y()).name(), colors.waveform_unplayed)
                self.assertNotEqual(image.pixelColor(played_x, area.top() + 4), image.pixelColor(unplayed_x, area.top() + 4))
            player.seek(0)
            QTest.qWait(40)
            view.grab()
            positions, paint_widths = [], []

            class PaintObserver(QObject):
                def eventFilter(self, watched, event):
                    if event.type() == QEvent.Type.Paint:
                        positions.append(view.position_ms)
                        paint_widths.append(event.region().boundingRect().width())
                    return False

            observer = PaintObserver()
            view.installEventFilter(observer)
            with patch.object(view, "_rebuild_envelope", wraps=view._rebuild_envelope) as geometry, patch.object(view, "_rebuild_cache", wraps=view._rebuild_cache) as cache:
                player.play_button.click()
                self.wait_until(lambda: player.media.position() >= 900)
                self.assertGreater(len(positions), 15)
                self.assertTrue(all(b >= a - 0.1 for a, b in zip(positions, positions[1:])), positions)
                self.assertLess(abs(view.position_ms - player.media.position()), 150)
                self.assertGreater(sum(width < view.width() // 4 for width in paint_widths), len(paint_widths) // 2)
                geometry.assert_not_called()
                cache.assert_not_called()
                player.play_button.click()
                self.wait_until(lambda: player._animation.state() == QAbstractAnimation.State.Stopped)
                paused = view.position_ms
                QTest.qWait(100)
                self.assertEqual(view.position_ms, paused)
            view.removeEventFilter(observer)
        finally:
            window.close()
            self.wait_until(lambda: not window.isVisible() and not window.reference_loader.has_workers)

    def test_clear_new_voice_confirmation_space_and_reuse(self):
        window = self.make_window()
        window.show()
        player = window.reference_player
        player.audio_output.setMuted(True)
        output = window.output_player
        output.audio_output.setMuted(True)
        original = self.wav.read_bytes(), self.ogg.read_bytes()
        try:
            window.select_reference(self.wav)
            self.wait_until(lambda: not window._importing)
            window.transcript_editor.setPlainText("Reviewed transcript")
            window.speech_editor.setPlainText("Speech to keep")
            player.waveform.setFocus()
            QTest.keyClick(player.waveform, Qt.Key.Key_Space)
            self.wait_until(lambda: player.play_button.text() == "Pause")
            window.choose_reference_button.setFocus()
            with patch("qwen3_tts_studio.ui.main_window.QFileDialog.getOpenFileName", return_value=("", "")) as chooser:
                QTest.keyClick(window.choose_reference_button, Qt.Key.Key_Space)
                self.wait_until(lambda: player.play_button.text() == "Play")
                chooser.assert_not_called()
                QTest.keyClick(window.choose_reference_button, Qt.Key.Key_Space)
                self.wait_until(lambda: player.play_button.text() == "Pause")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
                window.clear_reference_button.click()
                question.assert_called_once()
            self.assertEqual(window.session.reference, self.wav.resolve())
            self.assertEqual(window.session.transcript, "Reviewed transcript")
            self.assertEqual(player.media.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
            # Space in editors inserts a space and never toggles playback.
            for editor in (window.speech_editor, window.transcript_editor):
                editor.setFocus()
                before = editor.toPlainText()
                QTest.keyClick(editor, Qt.Key.Key_Space)
                self.assertEqual(len(editor.toPlainText()), len(before) + 1)
                self.assertEqual(player.media.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
            speech = window.speech_editor.toPlainText()
            old_media = player.media
            destroyed = QSignalSpy(old_media.destroyed)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                self.assertTrue(window.clear_reference())
            self.wait_until(lambda: destroyed.count() == 1)
            self.assertIsNone(player.media)
            self.assertIsNone(window.session.reference)
            self.assertEqual(window.transcript_editor.toPlainText(), "")
            self.assertEqual(window.speech_editor.toPlainText(), speech)
            self.assertEqual(window.reference_path.text(), "")
            self.assertEqual(player.duration_label.text(), "--:--")
            self.assertEqual(player.waveform.position_ms, 0)
            self.assertFalse(player.play_button.isEnabled())
            self.assertFalse(window.clear_reference_button.isEnabled())
            # Both components remain reusable after clear/reset.
            window.select_reference(self.ogg)
            output.load_recording(prepare_waveform(self.wav))  # Stand-in for future generated audio.
            self.wait_until(lambda: not window._importing and output.recording is not None)
            player.play_button.click()
            output.play_button.click()
            self.wait_until(lambda: player.play_button.text() == "Pause" and output.play_button.text() == "Pause")
            mode, sizes = window.theme.mode, window.workspace_splitter.sizes()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
                window.new_voice_action.trigger()
                question.assert_called_once()
            self.assertTrue(player.has_content and output.has_content)
            self.assertEqual(window.speech_editor.toPlainText(), speech)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                self.assertTrue(window.new_voice())
            self.assertFalse(window.session.has_content)
            self.assertEqual(window.character_count.text(), "0 characters")
            self.assertEqual((window.theme.mode, window.workspace_splitter.sizes()), (mode, sizes))
            for component in (player, output):
                self.assertIsNone(component.media)
                self.assertFalse(component.has_content)
                self.assertFalse(component.play_button.isEnabled())
                self.assertFalse(component.waveform.seekable)
                self.assertIsNone(component.waveform.recording)
                self.assertEqual(component.waveform.position_ms, 0)
                self.assertEqual(component.duration_label.text(), "--:--")
            with patch.object(QMessageBox, "question") as question:
                self.assertTrue(window.new_voice())  # Empty workspaces need no prompt.
                question.assert_not_called()
            self.assertEqual((self.wav.read_bytes(), self.ogg.read_bytes()), original)
        finally:
            window.transcript_editor.clear()
            window.speech_editor.clear()
            window.close()
            self.wait_until(lambda: not window.isVisible() and not window.reference_loader.has_workers)

    def test_reset_during_worker_loading_and_qt_preflight(self):
        recording = prepare_waveform(self.wav)
        window = self.make_window()
        window.show()
        started, finish = threading.Event(), threading.Event()

        def controlled_decode(path, cancelled):
            started.set()
            finish.wait(3)
            return recording  # Deliberately ignore cancellation to test stale completions.

        try:
            for reset in (window.clear_reference, window.new_voice):
                started.clear()
                finish.clear()
                with patch("qwen3_tts_studio.application.audio_loader.prepare_waveform", controlled_decode), patch.object(QMessageBox, "warning") as warning:
                    window.select_reference(self.wav)
                    self.wait_until(started.is_set)
                    self.assertTrue(window.clear_reference_button.isEnabled())
                    if reset == window.new_voice:
                        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
                            self.assertFalse(reset())
                        self.assertTrue(window._importing)
                        self.assertTrue(window.reference_loader.has_workers)
                    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                        self.assertTrue(reset())
                    finish.set()
                    self.wait_until(lambda: not window.reference_loader.has_workers)
                    QTest.qWait(30)
                    self.assertFalse(window._importing)
                    self.assertFalse(window.transcript_editor.isReadOnly())
                    self.assertFalse(window.session.has_content)
                    self.assertIsNone(window.reference_player.media)
                    warning.assert_not_called()
            window.reference_player.load_recording(recording)
            window.output_player.load_recording(recording)
            self.assertTrue(window.reference_player.has_content)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                window.new_voice()
            QTest.qWait(100)
            self.assertFalse(window.reference_player.has_content or window.output_player.has_content)
            self.assertIsNone(window.reference_player.media)
            # A new import still succeeds after cancellation.
            window.select_reference(self.ogg)
            self.wait_until(lambda: not window._importing)
            self.assertEqual(window.session.reference, self.ogg.resolve())
        finally:
            finish.set()
            window.close()
            self.wait_until(lambda: not window.isVisible() and not window.reference_loader.has_workers)


if __name__ == "__main__":
    unittest.main()
