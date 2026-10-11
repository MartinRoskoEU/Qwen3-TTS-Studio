"""Voice preparation, local transcription, and future generation workspace."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEvent, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QTextEdit,
    QSplitter, QVBoxLayout, QWidget,
)

from .. import __version__
from ..application.audio_loader import AudioLoader
from ..application.transcription import TranscriptionController
from ..application.workspace import CloningMode, WorkspacePaths, WorkspaceSession
from .audio_player import AudioPlayer, format_time
from .dialogs import SettingsDialog
from .theme import ThemeController


def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


class Section(QFrame):
    def __init__(self, title: str, description: str):
        super().__init__()
        self.setProperty("section", "true")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(10)
        self.body.addWidget(label(title, "sectionTitle"))
        self.body.addWidget(label(description, "muted", True))


class ReferenceSection(Section):
    file_dropped = Signal(object)

    def __init__(self):
        super().__init__("Reference Audio", "Choose or drop a WAV/OGG reference recording.")
        self.setAcceptDrops(True)
        self.setProperty("dropTarget", "true")
        self.setProperty("dragActive", "false")

    def _highlight(self, active: bool) -> None:
        self.setProperty("dragActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    @staticmethod
    def _drop_path(event):
        urls = event.mimeData().urls()
        return Path(urls[0].toLocalFile()) if len(urls) == 1 and urls[0].isLocalFile() else None

    def dragEnterEvent(self, event) -> None:
        if self._drop_path(event) is not None:
            self._highlight(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._highlight(False)
        event.accept()

    def dropEvent(self, event) -> None:
        self._highlight(False)
        path = self._drop_path(event)
        if path is not None:
            event.acceptProposedAction()
            self.file_dropped.emit(path)
        else:
            event.ignore()


def unavailable_button(text: str, reason: str) -> QPushButton:
    button = QPushButton(text)
    button.setEnabled(False)
    button.setToolTip(reason)
    return button


class MainWindow(QMainWindow):
    def __init__(self, paths: WorkspacePaths, theme: ThemeController):
        super().__init__()
        self.paths = paths
        self.theme = theme
        self.session = WorkspaceSession()
        self._closing = False
        self._importing = False
        self._transcription_context = None
        self._transcription_phase = ""
        self.transcription = TranscriptionController(paths.models, self)
        self.transcription.ready.connect(self._transcription_ready)
        self.transcription.failed.connect(self._transcription_failed)
        self.transcription.phase.connect(self._transcription_progress)
        self.transcription.busy_changed.connect(self._transcription_busy_changed)
        self.transcription.drained.connect(self._workers_drained)
        self._transcription_elapsed = QElapsedTimer()
        self._transcription_timer = QTimer(self)
        self._transcription_timer.setInterval(200)
        self._transcription_timer.timeout.connect(self._update_transcription_status)
        self.reference_loader = AudioLoader(self)
        self.reference_loader.ready.connect(self._reference_decoded)
        self.reference_loader.failed.connect(self._reference_failed)
        self.reference_loader.drained.connect(self._workers_drained)
        self._import_elapsed = QElapsedTimer()
        self._import_timer = QTimer(self)
        self._import_timer.setInterval(200)
        self._import_timer.timeout.connect(self._update_import_status)
        self.setWindowTitle("Qwen3 TTS Studio")
        self.resize(1120, 900)
        self.setMinimumSize(900, 870)
        self._create_menus()
        self._create_workspace()
        QApplication.instance().installEventFilter(self)
        self.statusBar().showMessage("Ready. Import a reference to transcribe locally, or enter its transcript manually.")
        self.appearance_status = label("", "muted")
        self.statusBar().addPermanentWidget(self.appearance_status)
        theme.changed.connect(self._update_appearance_status)
        self._update_appearance_status(theme.current_theme)

    def _create_menus(self) -> None:
        app_menu = self.menuBar().addMenu("&Application")
        self.new_voice_action = QAction("&New Voice", self)
        self.new_voice_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_voice_action.triggered.connect(self.new_voice)
        app_menu.addAction(self.new_voice_action)
        app_menu.addSeparator()
        settings = QAction("&Settings…", self)
        settings.setShortcut(QKeySequence("Ctrl+,"))
        settings.triggered.connect(self.show_settings)
        app_menu.addAction(settings)
        app_menu.addSeparator()
        self.exit_action = QAction("E&xit", self)
        self.exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.exit_action.triggered.connect(self.close)
        app_menu.addAction(self.exit_action)
        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("&About Qwen3 TTS Studio…", self)
        about.triggered.connect(self.show_about)
        help_menu.addAction(about)

    def _create_workspace(self) -> None:
        workspace = QWidget()
        workspace.setObjectName("workspace")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(4)
        heading.addWidget(label("Voice workspace", "title"))
        heading.addWidget(label("Prepare a reference and text for speech synthesis.", "muted", True))
        header.addLayout(heading, 1)
        header.addWidget(label("LOCAL WORKSPACE", "badge"))
        layout.addLayout(header)

        self.workspace_splitter = self._make_splitter(Qt.Orientation.Vertical, "Workspace and output sizes")
        self.splitter = self._make_splitter(Qt.Orientation.Horizontal, "Workspace column widths")
        self.left_splitter = self._make_splitter(Qt.Orientation.Vertical, "Reference and transcription sizes")
        self.right_splitter = self._make_splitter(Qt.Orientation.Vertical, "Speech text and generation sizes")
        self.left_splitter.setMinimumWidth(400)
        self.right_splitter.setMinimumWidth(400)
        self.reference_section = self._reference_section()
        self.transcription_section = self._transcription_section()
        self.speech_section = self._speech_section()
        self.generation_section = self._generation_section()
        self.output_section = self._output_section()
        self.left_splitter.addWidget(self.reference_section)
        self.left_splitter.addWidget(self.transcription_section)
        self.right_splitter.addWidget(self.speech_section)
        self.right_splitter.addWidget(self.generation_section)
        self.left_splitter.setSizes([300, 220])
        self.right_splitter.setSizes([290, 230])
        self.splitter.addWidget(self.left_splitter)
        self.splitter.addWidget(self.right_splitter)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([490, 540])
        self.workspace_splitter.addWidget(self.splitter)
        self.workspace_splitter.addWidget(self.output_section)
        self.workspace_splitter.setStretchFactor(0, 2)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([520, 230])
        layout.addWidget(self.workspace_splitter, 1)
        self.setCentralWidget(workspace)
        QWidget.setTabOrder(self.choose_reference_button, self.clear_reference_button)
        QWidget.setTabOrder(self.clear_reference_button, self.reference_player.waveform)
        QWidget.setTabOrder(self.reference_player.waveform, self.reference_player.play_button)
        QWidget.setTabOrder(self.reference_player.play_button, self.cloning_mode)
        QWidget.setTabOrder(self.cloning_mode, self.transcript_editor)
        QWidget.setTabOrder(self.transcript_editor, self.transcribe_button)
        QWidget.setTabOrder(self.transcribe_button, self.speech_editor)
        QWidget.setTabOrder(self.speech_editor, self.open_output_button)

    @staticmethod
    def _make_splitter(orientation: Qt.Orientation, accessible_name: str) -> QSplitter:
        splitter = QSplitter(orientation)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setAccessibleName(accessible_name)
        return splitter

    def _reference_section(self) -> Section:
        section = ReferenceSection()
        section.body.setSpacing(6)
        section.body.setContentsMargins(16, 12, 16, 12)
        section.file_dropped.connect(self.select_reference)
        self.reference_path = QLineEdit()
        self.reference_path.setReadOnly(True)
        self.reference_path.setAcceptDrops(False)
        self.reference_path.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.reference_path.setPlaceholderText("No reference selected")
        self.reference_path.setAccessibleName("Reference audio filename")
        row = QHBoxLayout()
        row.addWidget(self.reference_path, 1)
        self.choose_reference_button = QPushButton("&Choose reference…")
        self.choose_reference_button.setShortcut(QKeySequence("Ctrl+O"))
        self.choose_reference_button.clicked.connect(self.choose_reference)
        row.addWidget(self.choose_reference_button)
        self.clear_reference_button = QPushButton("Clear reference")
        self.clear_reference_button.setToolTip("Unload the reference and clear its transcription; keep Speech Text")
        self.clear_reference_button.setEnabled(False)
        self.clear_reference_button.clicked.connect(self.clear_reference)
        row.addWidget(self.clear_reference_button)
        section.body.addLayout(row)
        self.reference_player = AudioPlayer()
        self.reference_player.audio_ready.connect(self._reference_loaded)
        self.reference_player.load_failed.connect(self._reference_failed)
        self.reference_player.playback_error.connect(self._playback_failed)
        section.body.addWidget(self.reference_player, 1)
        self.reference_status = label("No reference loaded", "muted")
        section.body.addWidget(self.reference_status)
        return section

    def _transcription_section(self) -> Section:
        section = Section("Transcription", "Review and correct the reference transcript.")
        section.body.setSpacing(6)
        section.body.setContentsMargins(16, 12, 16, 12)
        self.transcription_status = section.body.itemAt(1).widget()
        self.cloning_mode = QComboBox()
        self.cloning_mode.setAccessibleName("Voice cloning mode")
        self.cloning_mode.addItem("ICL Mode – With Transcription", CloningMode.ICL)
        self.cloning_mode.addItem("X-Vector Only – Without Transcription", CloningMode.X_VECTOR_ONLY)
        self.cloning_mode.setToolTip("ICL uses reviewed reference text. X-Vector Only uses audio without reference text.")
        self.cloning_mode.currentIndexChanged.connect(self._cloning_mode_changed)
        section.body.addWidget(self.cloning_mode)
        self.transcript_editor = QPlainTextEdit()
        self.transcript_editor.setTabChangesFocus(True)
        self.transcript_editor.setPlaceholderText("Type or paste the reference transcript here,\nor choose Transcribe reference after loading audio.")
        self.transcript_editor.setAccessibleName("Reference transcript")
        self.transcript_editor.setMinimumHeight(80)
        self.transcript_editor.textChanged.connect(self._transcript_changed)
        section.body.addWidget(self.transcript_editor, 1)
        row = QHBoxLayout()
        self.transcribe_button = QPushButton("Transcribe reference")
        self.transcribe_button.setEnabled(False)
        self.transcribe_button.clicked.connect(self.transcribe_reference)
        row.addWidget(self.transcribe_button)
        row.addStretch()
        row.addWidget(label("Draft · not saved", "muted"))
        section.body.addLayout(row)
        return section

    def _speech_section(self) -> Section:
        section = Section("Speech Text", "Write the words you want the cloned voice to speak.")
        self.speech_editor = QPlainTextEdit()
        self.speech_editor.setTabChangesFocus(True)
        self.speech_editor.setPlaceholderText("Enter speech text…")
        self.speech_editor.setAccessibleName("Speech text")
        self.speech_editor.setMinimumHeight(120)
        self.speech_editor.textChanged.connect(self._speech_changed)
        section.body.addWidget(self.speech_editor, 1)
        row = QHBoxLayout()
        row.addWidget(label("Session draft · not saved", "muted"))
        row.addStretch()
        self.character_count = label("0 characters", "muted")
        row.addWidget(self.character_count)
        section.body.addLayout(row)
        return section

    def _generation_section(self) -> Section:
        section = Section("Generation", "Speech synthesis and voice cloning will be available in a future update.")
        section.setMinimumHeight(180)
        section.body.addWidget(label("No model loaded", "muted"))
        section.body.addStretch(1)
        row = QHBoxLayout()
        row.addStretch()
        self.generate_button = unavailable_button("Generate speech", "Speech generation is not implemented yet.")
        self.generate_button.setProperty("primary", "true")
        row.addWidget(self.generate_button)
        section.body.addLayout(row)
        return section

    def _output_section(self) -> Section:
        section = Section("Output", "No audio loaded. Generated speech will appear here for review and WAV export.")
        self.output_player = AudioPlayer()
        self.output_player.playback_error.connect(self._playback_failed)
        section.body.addWidget(self.output_player, 1)
        self.export_button = unavailable_button("Export WAV…", "WAV export is not implemented yet.")
        self.output_player.controls.addWidget(self.export_button)
        self.open_output_button = QPushButton("Open output &folder")
        self.open_output_button.setToolTip(str(self.paths.output))
        self.open_output_button.clicked.connect(self.open_output_folder)
        self.output_player.controls.addWidget(self.open_output_button)
        return section

    def _transcript_changed(self) -> None:
        self._cancel_transcription("Transcription cancelled · edited draft kept")
        self.session.transcript = self.transcript_editor.toPlainText()
        self._update_reference_actions()

    def _cloning_mode_changed(self) -> None:
        self._cancel_transcription("Transcription cancelled · mode changed")
        self.session.cloning_mode = CloningMode(self.cloning_mode.currentData())
        self._update_transcription_controls()

    def _update_transcription_controls(self) -> None:
        icl = self.session.cloning_mode == CloningMode.ICL
        self.transcript_editor.setEnabled(icl and not self._closing)
        self.transcript_editor.setReadOnly(self._importing)
        self.transcribe_button.setEnabled(icl and self.session.reference is not None
                                         and not self._importing and not self.transcription.busy
                                         and not self._closing)
        if not icl:
            hint = "X-Vector Only uses reference audio without a transcript. Your draft is kept."
        elif self.transcription.busy:
            hint = "Wait for the current transcription worker to finish."
        elif self.session.reference is None:
            hint = "Load a WAV or OGG reference first; manual transcription is available now."
        else:
            hint = "Transcribe locally with Faster Whisper Small; existing text requires confirmation."
        self.transcribe_button.setToolTip(hint)

    def transcribe_reference(self) -> bool:
        if (self._closing or self._importing or self.transcription.busy
                or self.session.reference is None or self.session.cloning_mode != CloningMode.ICL):
            return False
        if self.session.transcript:
            answer = QMessageBox.question(
                self, "Replace transcription?",
                "Replace the current transcript with automatic transcription? Your text is kept if transcription fails or finds no speech.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self._transcription_context = (self.session.reference, self.transcript_editor.document().revision(),
                                       self.session.cloning_mode)
        self._transcription_elapsed.start()
        self._transcription_phase = "Preparing transcription"
        self._transcription_timer.start()
        self._update_transcription_status()
        if not self.transcription.start(self.session.reference):
            self._transcription_context = None
            self._transcription_timer.stop()
            return False
        return True

    def _cancel_transcription(self, message: str) -> None:
        if self._transcription_context is None:
            return
        self._transcription_context = None
        self.transcription.cancel()
        self._transcription_timer.stop()
        self.transcription_status.setText(message)
        self.transcription_status.setToolTip("The pending result is discarded. Native model work stops at the next cancellation checkpoint.")

    def _transcription_progress(self, message: str) -> None:
        self._transcription_phase = message
        self._update_transcription_status()

    def _update_transcription_status(self) -> None:
        if self._transcription_context is not None and not self._closing:
            short_phase = self._transcription_phase
            if short_phase.startswith("CUDA"):
                short_phase = "CUDA unavailable · using CPU"
            self.transcription_status.setText(f"{short_phase} · {self._transcription_elapsed.elapsed() / 1000:.1f} s")
            self.transcription_status.setToolTip(self._transcription_phase)

    def _transcription_ready(self, result) -> None:
        context = (self.session.reference, self.transcript_editor.document().revision(), self.session.cloning_mode)
        if self._closing or self._importing or self._transcription_context != context:
            return
        self._transcription_context = None
        self._transcription_timer.stop()
        elapsed = self._transcription_elapsed.elapsed() / 1000
        if result.text.strip():
            self.transcript_editor.setPlainText(result.text)
            device_label = "GPU (CUDA)" if result.device == "cuda" else "CPU"
            message = f"Transcribed · {result.language} · {elapsed:.1f} s · {device_label}"
            details = f"Device: {device_label}. Precision: {result.compute_type or 'default'}. Detected language: {result.language} ({result.language_probability:.0%}). Review and correct the transcript before generation."
            if result.gpu_error:
                details += f"\nGPU initialization/transcription error: {result.gpu_error}"
            self.transcription_status.setToolTip(details)
        else:
            message = f"No speech recognized · {elapsed:.1f} s · draft kept"
            device_label = "GPU (CUDA)" if result.device == "cuda" else "CPU"
            message += f" · {device_label}"
            self.transcription_status.setToolTip("No usable transcript was returned. Check the recording or enter its text manually." + (f"\nGPU error: {result.gpu_error}" if result.gpu_error else ""))
        self.transcription_status.setText(message)
        self.statusBar().showMessage(message)

    def _transcription_failed(self, message: str) -> None:
        if self._closing or self._transcription_context is None:
            return
        self._transcription_context = None
        self._transcription_timer.stop()
        self.transcription_status.setText(f"Transcription failed · {self._transcription_elapsed.elapsed() / 1000:.1f} s · draft kept")
        self.transcription_status.setToolTip(message)
        QMessageBox.warning(self, "Cannot transcribe reference", f"{message}\n\nCheck the local Small model in models/faster-whisper and the reference recording. You can still enter a transcript manually.")

    def _transcription_busy_changed(self, busy: bool) -> None:
        self._update_transcription_controls()

    def _speech_changed(self) -> None:
        self.session.speech_text = self.speech_editor.toPlainText()
        count = len(self.session.speech_text)
        self.character_count.setText(f"{count:,} {'character' if count == 1 else 'characters'}")

    def choose_reference(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose reference audio", str(self.paths.samples),
            "Reference audio (*.wav *.ogg);;WAV audio (*.wav);;OGG audio (*.ogg)",
        )
        if filename:
            self.select_reference(Path(filename))

    def select_reference(self, path: Path) -> bool:
        """Queue an import; success is committed only after decoding and Qt load."""
        if self._closing:
            return False
        try:
            path = Path(path)
            if path.suffix.lower() not in {".wav", ".ogg"}:
                raise ValueError("Select a WAV or OGG reference recording.")
            if path != self.session.reference and self.session.transcript:
                answer = QMessageBox.question(
                    self, "Replace reference?",
                    "Selecting a different reference clears the current transcript draft. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return False
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Cannot select reference", f"{error}\n\nChoose a readable WAV or OGG file.")
            return False
        self._cancel_transcription("Transcription cancelled · reference changing")
        self.reference_player.cancel_pending()
        self._importing = True
        # Keep the reviewed transcript safe while replacement is pending. Speech
        # text, playback, menus, and the rest of the interface remain available.
        self.transcript_editor.setReadOnly(True)
        self._import_elapsed.start()
        self._import_timer.start()
        self._update_import_status()
        self.reference_loader.load(path)
        self._update_reference_actions()
        return True

    def _reference_decoded(self, recording) -> None:
        if not self._closing and self._importing:
            self.reference_player.load_recording(recording)

    def _finish_import(self) -> None:
        self._importing = False
        self._import_timer.stop()
        self.transcript_editor.setReadOnly(False)
        self._update_reference_actions()

    def _reference_loaded(self, recording) -> None:
        if self._closing or not self._importing:
            return
        changed = recording.path != self.session.reference
        self.session.apply_reference(recording.path)
        self.reference_path.setText(recording.path.name)
        self.reference_path.setCursorPosition(0)
        self.reference_path.setToolTip(str(recording.path))
        if self.transcript_editor.toPlainText() != self.session.transcript:
            self.transcript_editor.setPlainText(self.session.transcript)
        if changed:
            self.transcription_status.setText("Review and correct the reference transcript.")
            self.transcription_status.setToolTip("")
        self._finish_import()
        self.reference_status.setText("Ready · Click or drag on the waveform to seek")
        self.statusBar().showMessage(f"Loaded {recording.path.name} · {format_time(recording.duration_ms)} · prepared in {self._import_elapsed.elapsed() / 1000:.1f} s")

    def _update_reference_actions(self) -> None:
        self.clear_reference_button.setEnabled(not self._closing and (
            self.session.reference is not None or bool(self.session.transcript) or self._importing))
        self._update_transcription_controls()

    def _reset_reference(self) -> None:
        # Invalidate worker completions before resetting either the UI or state.
        self._cancel_transcription("Reference cleared")
        self.reference_loader.cancel()
        self.reference_player.clear()
        self.session.clear_reference()
        self.reference_path.clear()
        self.reference_path.setToolTip("")
        self.transcript_editor.clear()
        self._finish_import()
        self.reference_status.setText("No reference loaded")
        self.transcription_status.setText("Review and correct the reference transcript.")
        self.transcription_status.setToolTip("")

    def clear_reference(self) -> bool:
        if self._closing:
            return False
        if self.session.transcript:
            answer = QMessageBox.question(
                self, "Clear reference?", "Clear the reference and discard its transcription draft?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return False
        self._reset_reference()
        self.statusBar().showMessage("Reference cleared. Speech Text was kept; audio files were not changed.")
        return True

    def new_voice(self) -> bool:
        if self._closing:
            return False
        if self.session.has_content or self._importing or self.output_player.has_content:
            answer = QMessageBox.question(
                self, "New Voice?", "Start a new voice and discard the current reference, text drafts, and output preview?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return False
        self._reset_reference()
        self.session.new_voice()
        self.cloning_mode.setCurrentIndex(self.cloning_mode.findData(CloningMode.ICL))
        self._update_transcription_controls()
        self.speech_editor.clear()
        self.output_player.clear()
        self.export_button.setEnabled(False)
        self.statusBar().showMessage("New voice ready. Audio files and application preferences were kept.")
        self.choose_reference_button.setFocus()
        return True

    def eventFilter(self, watched, event) -> bool:
        if (event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
                and event.key() == Qt.Key.Key_Space
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
                and isinstance(watched, QWidget) and watched.window() is self
                and QApplication.activeModalWidget() is None and not self._closing):
            focus = QApplication.focusWidget() or watched
            widget = focus
            while widget is not None and widget is not self:
                if isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
                    return super().eventFilter(watched, event)
                if isinstance(widget, QComboBox) and widget.isEditable():
                    return super().eventFilter(watched, event)
                widget = widget.parentWidget()
            event.accept()
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self._space_player(focus).toggle_playback()
            return True
        return super().eventFilter(watched, event)

    def _space_player(self, focus: QWidget) -> AudioPlayer:
        widget = focus
        while widget is not None and widget is not self:
            if isinstance(widget, AudioPlayer):
                return widget
            if widget is self.reference_section:
                return self.reference_player
            widget = widget.parentWidget()
        for player in (self.reference_player, self.output_player):
            if player.media and player.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                return player
        return self.reference_player if self.reference_player.has_content else self.output_player

    def _reference_failed(self, message: str) -> None:
        if self._closing or not self._importing:
            return
        self._finish_import()
        self.reference_status.setText("Import failed · Previous reference kept" if self.session.reference else "Import failed")
        self.statusBar().showMessage("Reference import failed. Your existing recording and drafts were preserved.")
        QMessageBox.warning(self, "Cannot import reference", f"{message}\n\nChoose a readable, valid WAV or OGG recording.")

    def _update_import_status(self) -> None:
        self.reference_status.setText(f"Loading reference · {self._import_elapsed.elapsed() / 1000:.1f} s")

    def _playback_failed(self, message: str) -> None:
        if not self._closing:
            QMessageBox.warning(self, "Audio playback failed", f"{message}\n\nCheck your audio output device and reload the recording.")

    def open_output_folder(self) -> None:
        if not self.paths.output.is_dir():
            QMessageBox.warning(self, "Output folder unavailable", f"The output folder does not exist:\n{self.paths.output}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.output))):
            QMessageBox.warning(self, "Cannot open folder", f"Open this folder in File Explorer:\n{self.paths.output}")

    def show_settings(self) -> None:
        dialog = SettingsDialog(self.theme, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.theme.set_mode(dialog.selected_mode)

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About Qwen3 TTS Studio",
            f"<b>Qwen3 TTS Studio</b> {__version__}<br><br>"
            "A local workspace for future voice cloning and speech synthesis.<br>"
            "This version provides reference import, waveform playback, local Faster Whisper transcription, cloning mode selection, and text drafts. "
            "Generation and audio post-processing are not implemented.<br><br>"
            "Copyright © 2026 Nendis<br>Application source: MIT License<br>"
            "Built with PySide6 / Qt. See THIRD_PARTY_NOTICES.md for third-party licenses.",
        )

    def _update_appearance_status(self, name: str) -> None:
        source = "Windows" if self.theme.mode == "system" else "Appearance"
        self.appearance_status.setText(f"{source}: {name.capitalize()}  ")

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closing and self.session.has_drafts:
            answer = QMessageBox.question(
                self, "Discard text drafts?",
                "Your transcript and speech text drafts are not saved. Discard them and exit?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        self._closing = True
        self.release_resources()
        if self.reference_loader.has_workers or self.transcription.has_workers:
            event.ignore()
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage("Closing · waiting for background work and model cleanup…")
            return
        event.accept()

    def _workers_drained(self) -> None:
        if self._closing and not self.reference_loader.has_workers and not self.transcription.has_workers:
            QTimer.singleShot(0, self.close)

    def release_resources(self) -> None:
        self._import_timer.stop()
        self._transcription_timer.stop()
        self.transcription.shutdown()
        self.reference_loader.shutdown()
        self.reference_player.release()
        self.output_player.release()
