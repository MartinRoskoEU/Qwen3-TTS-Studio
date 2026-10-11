"""Reusable Qt Multimedia transport with a synchronized waveform playhead."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from PySide6.QtCore import QAbstractAnimation, QElapsedTimer, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .waveform import WaveformView


def format_time(milliseconds: int) -> str:
    seconds, tenths = divmod(int(max(0, milliseconds)) // 100, 10)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    prefix = f"{hours:02}:" if hours else ""
    return f"{prefix}{minutes:02}:{seconds:02}.{tenths}"


class PlaybackAnimation(QAbstractAnimation):
    """Let Qt's shared animation driver schedule repaint opportunities."""

    def __init__(self, callback, parent):
        super().__init__(parent)
        self._callback = callback

    def duration(self) -> int:
        return -1

    def updateCurrentTime(self, current_time: int) -> None:
        self._callback()


class AudioPlayer(QWidget):
    audio_ready = Signal(object)
    load_failed = Signal(str)
    playback_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.recording = None
        self.media = None
        self._candidate = None
        self._candidate_recording = None
        self._closed = False
        self._failed_playback = False
        self._scrubbing = False
        self._resume_after_scrub = False
        self._base_position = 0
        self._correction = 0.0
        self._correction_window = 0.0
        self._clock = QElapsedTimer()
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.75)
        self._load_timeout = QTimer(self)
        self._load_timeout.setSingleShot(True)
        self._load_timeout.timeout.connect(lambda: self._reject_candidate("Qt could not open the recording within 15 seconds. Try another local WAV or OGG file."))
        self._animation = PlaybackAnimation(self._update_display, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.waveform = WaveformView()
        layout.addWidget(self.waveform, 1)
        self.controls = QHBoxLayout()
        self.controls.setSpacing(8)
        self.play_button = QPushButton("Play")
        self.play_button.setMinimumWidth(65)
        self.play_button.setToolTip("Play or pause audio (Space outside text editors)")
        self.play_button.clicked.connect(self.toggle_playback)
        self.controls.addWidget(self.play_button)
        self.controls.addStretch()
        self.position_label = QLabel("00:00.0")
        self.position_label.setAccessibleName("Current playback position")
        self.duration_label = QLabel("--:--")
        self.duration_label.setAccessibleName("Audio duration")
        for widget in (self.position_label, QLabel("/"), self.duration_label):
            widget.setProperty("role", "muted")
            self.controls.addWidget(widget)
        layout.addLayout(self.controls)
        self.waveform.seek_requested.connect(self.seek)
        self.waveform.scrub_started.connect(self._begin_scrub)
        self.waveform.scrub_finished.connect(self._finish_scrub)
        self._update_controls()

    @property
    def duration_ms(self) -> int:
        if self.media and self.media.duration() > 0:
            return self.media.duration()
        return self.recording.duration_ms if self.recording else 0

    @property
    def has_content(self) -> bool:
        return self.recording is not None or self._candidate is not None

    def cancel_pending(self) -> None:
        self._load_timeout.stop()
        candidate, self._candidate = self._candidate, None
        self._candidate_recording = None
        if candidate:
            self._dispose_media(candidate)

    @staticmethod
    def _dispose_media(media: QMediaPlayer) -> None:
        media.stop()
        media.setAudioOutput(None)
        media.setSource(QUrl())
        media.deleteLater()

    def load_recording(self, recording) -> None:
        """Preflight Qt's decoder while preserving the currently playing source."""
        if self._closed:
            return
        self.cancel_pending()
        candidate = QMediaPlayer(self)
        self._candidate = candidate
        self._candidate_recording = recording
        candidate.mediaStatusChanged.connect(self._candidate_status, Qt.ConnectionType.QueuedConnection)
        candidate.errorOccurred.connect(self._candidate_error, Qt.ConnectionType.QueuedConnection)
        self._load_timeout.start(15000)
        candidate.setSource(QUrl.fromLocalFile(str(recording.path)))

    @Slot(QMediaPlayer.Error, str)
    def _candidate_error(self, error, message: str) -> None:
        candidate = self.sender()
        if candidate is not None and candidate is self._candidate:
            self._reject_candidate(message or "Qt could not decode this recording.")

    def _reject_candidate(self, message: str) -> None:
        if self._candidate is not None:
            self.cancel_pending()
            self.load_failed.emit(message)

    @Slot(QMediaPlayer.MediaStatus)
    def _candidate_status(self, status) -> None:
        candidate = self.sender()
        if candidate is None or candidate is not self._candidate or self._closed:
            return
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._reject_candidate(candidate.errorString() or "Qt could not decode this recording.")
        elif status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if not candidate.hasAudio():
                self._reject_candidate("This file contains no playable audio stream.")
                return
            self._load_timeout.stop()
            recording = self._candidate_recording
            self._candidate = None
            self._candidate_recording = None
            self._animation.stop()
            if self.media:
                self._dispose_media(self.media)
            self.media = candidate
            self.recording = recording
            self._failed_playback = False
            self._scrubbing = False
            self._resume_after_scrub = False
            candidate.setAudioOutput(self.audio_output)
            # Handle backend notifications after Qt finishes each transition;
            # all widget updates stay on the GUI thread, without reentering it.
            candidate.positionChanged.connect(self._position_changed, Qt.ConnectionType.QueuedConnection)
            candidate.durationChanged.connect(self._duration_changed, Qt.ConnectionType.QueuedConnection)
            candidate.seekableChanged.connect(self._update_controls, Qt.ConnectionType.QueuedConnection)
            candidate.playbackStateChanged.connect(self._state_changed, Qt.ConnectionType.QueuedConnection)
            candidate.mediaStatusChanged.connect(self._status_changed, Qt.ConnectionType.QueuedConnection)
            candidate.errorOccurred.connect(self._active_error, Qt.ConnectionType.QueuedConnection)
            self.waveform.set_recording(recording)
            self._duration_changed(self.duration_ms)
            self._anchor(0)
            self._update_display()
            self._update_controls()
            self.audio_ready.emit(recording)

    @Slot(QMediaPlayer.Error, str)
    def _active_error(self, error, message: str) -> None:
        if self.media is None or self.sender() is not self.media or self._closed:
            return
        self._failed_playback = True
        self._animation.stop()
        self._update_controls()
        self.playback_error.emit(message or "Audio playback failed. Check your output device and reload the recording.")

    @Slot()
    def _update_controls(self) -> None:
        ready = self.media is not None and not self._closed and not self._failed_playback
        state = self.media.playbackState() if ready else QMediaPlayer.PlaybackState.StoppedState
        self.play_button.setEnabled(ready and not self._scrubbing)
        self.play_button.setText("Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play")
        self.waveform.set_seekable(ready and self.media.isSeekable())

    @Slot(int)
    def _duration_changed(self, duration: int) -> None:
        if self.media is None or self.sender() is not self.media or self._closed:
            return
        self.waveform.duration_ms = duration if duration > 0 else self.duration_ms
        self.duration_label.setText(format_time(self.waveform.duration_ms))
        self.waveform.update()

    @Slot(int)
    def _position_changed(self, position: int) -> None:
        if self.media is None or self.sender() is not self.media or self._closed:
            return
        # Queued notifications can predate a seek. Read the current Qt value and
        # ignore obsolete notifications rather than restoring an old position.
        if not self._scrubbing and position == self.media.position():
            self._anchor(position, smooth=self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
            self._update_display()

    @Slot(QMediaPlayer.PlaybackState)
    def _state_changed(self, state) -> None:
        if self.media is None or self.sender() is not self.media or self._closed:
            return
        if state != self.media.playbackState():
            return
        if not self._scrubbing:
            self._anchor(self.media.position())
        self._sync_animation()
        self._update_controls()
        self._update_display()

    @Slot(QMediaPlayer.MediaStatus)
    def _status_changed(self, status) -> None:
        if self.media is None or self.sender() is not self.media or self._closed:
            return
        if status != self.media.mediaStatus():
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if not self._scrubbing:
                self._anchor(self.duration_ms)
        elif status == QMediaPlayer.MediaStatus.StalledMedia and not self._scrubbing:
            self._anchor(self.media.position())
        self._sync_animation()
        self._update_display()
        self._update_controls()

    def _anchor(self, position: int, smooth: bool = False) -> None:
        elapsed = self._clock.nsecsElapsed() / 1_000_000 if self._clock.isValid() else 0
        correction = self._visual_position() - position if smooth else 0.0
        # Ease ordinary notification jitter over the observed update cadence.
        # Large corrections (seeks/discontinuities) align immediately with Qt.
        if not smooth or elapsed <= 0 or abs(correction) > elapsed * self.media.playbackRate():
            correction = 0.0
        self._correction = correction
        self._correction_window = elapsed
        self._base_position = position
        self._clock.restart()

    def _can_animate(self) -> bool:
        return (self.media is not None and not self._closed and not self._failed_playback
                and not self._scrubbing
                and self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                and self.media.mediaStatus() in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia))

    def _sync_animation(self) -> None:
        if self._can_animate():
            if self._animation.state() != QAbstractAnimation.State.Running:
                self._animation.start()
        else:
            self._animation.stop()

    def _visual_position(self) -> float:
        position = self._base_position
        if self._scrubbing:
            return position
        if self.media and self.media.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
            position = self.duration_ms
        elif self._can_animate() and self._clock.isValid():
            elapsed = self._clock.nsecsElapsed() / 1_000_000
            position += elapsed * self.media.playbackRate()
            position += self._correction * max(0, 1 - elapsed / max(1, self._correction_window))
        return max(0, min(position, self.duration_ms))

    def _update_display(self) -> None:
        position = self._visual_position()
        self.waveform.set_position(position)
        text = format_time(position)
        if text != self.position_label.text():
            self.position_label.setText(text)

    def toggle_playback(self) -> None:
        if self.media is None or not self.play_button.isEnabled():
            return
        if self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if not self.play_button.isEnabled():
            return
        if self.media.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia or self.media.position() >= self.duration_ms:
            self.seek(0)
        self.media.play()

    def pause(self) -> None:
        if self.media and not self._closed and self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media.pause()

    def seek(self, position_ms: int) -> None:
        if not self.waveform.seekable:
            return
        self._anchor(max(0, min(position_ms, self.duration_ms)))
        # While dragging, render immediately without repeated backend seeks.
        # The paused source is synchronized once on release.
        if not self._scrubbing:
            self.media.setPosition(self._base_position)
        self._update_display()

    def _begin_scrub(self) -> None:
        if self.media is None or self._closed:
            return
        self._scrubbing = True
        self._animation.stop()
        self._resume_after_scrub = self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if self._resume_after_scrub:
            self.media.pause()
        self._update_controls()

    def _finish_scrub(self) -> None:
        self._scrubbing = False
        if self.media is None or self._closed:
            self._resume_after_scrub = False
            return
        self.media.setPosition(self._base_position)
        self._anchor(self._base_position)
        if self._resume_after_scrub:
            self.media.play()
        self._resume_after_scrub = False
        self._sync_animation()
        self._update_controls()
        self._update_display()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if not event.isAutoRepeat():
                self.toggle_playback()
            event.accept()
        else:
            super().keyPressEvent(event)

    def clear(self) -> None:
        """Reset a reusable player without destroying its output device."""
        self.cancel_pending()
        self._animation.stop()
        media, self.media = self.media, None
        if media:
            self._dispose_media(media)
        self.recording = None
        self._failed_playback = False
        self._scrubbing = False
        self._resume_after_scrub = False
        self._base_position = 0
        self._correction = 0.0
        self._clock.invalidate()
        self.waveform.set_recording(None)
        self.position_label.setText("00:00.0")
        self.duration_label.setText("--:--")
        self._update_controls()

    def release(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.clear()
        self.audio_output.deleteLater()
