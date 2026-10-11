"""Voice preparation, local transcription, and future generation workspace."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEvent, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QTextEdit,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from .. import __version__
from ..application.audio_loader import AudioLoader
from ..application.transcription import TranscriptionController
from ..application.workspace import CloningMode, ProfileStatus, WorkspacePaths, WorkspaceSession
from ..application.voice_jobs import VoiceController
from .audio_player import AudioPlayer, format_time
from .dialogs import SettingsDialog
from .theme import ThemeController
from .progress import OperationProgress


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
        if self.isEnabled() and self._drop_path(event) is not None:
            self._highlight(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self.isEnabled() and self._drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._highlight(False)
        event.accept()

    def dropEvent(self, event) -> None:
        self._highlight(False)
        path = self._drop_path(event)
        if self.isEnabled() and path is not None:
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
        self._voice_context = None
        self._generation_stopping = False
        self._output_context = None
        self._voice_phase = ""
        self._voice_device = ""
        self.voice = VoiceController(paths, self)
        self.voice.ready.connect(self._voice_ready)
        self.voice.failed.connect(self._voice_failed)
        self.voice.phase.connect(self._voice_progress)
        self.voice.busy_changed.connect(self._voice_busy_changed)
        self.voice.drained.connect(self._workers_drained)
        self._voice_elapsed = QElapsedTimer()
        self._voice_timer = QTimer(self)
        self._voice_timer.setInterval(200)
        self._voice_timer.timeout.connect(self._update_voice_status)
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
        self._update_voice_actions()
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
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(4)
        heading.addWidget(label("Voice workspace", "title"))
        heading.addWidget(label("Reference + transcript → Prepare Voice → Generate Speech → Output", "muted", True))
        header.addLayout(heading, 1)
        header.addWidget(label("LOCAL WORKSPACE", "badge"))
        layout.addLayout(header)

        self.workspace_splitter = self._make_splitter(Qt.Orientation.Vertical, "Workspace and output sizes")
        self.splitter = self._make_splitter(Qt.Orientation.Horizontal, "Workspace column widths")
        self.left_splitter = self._make_splitter(Qt.Orientation.Vertical, "Reference, transcription, and voice profile sizes")
        self.right_splitter = self._make_splitter(Qt.Orientation.Vertical, "Speech text and generation sizes")
        self.left_splitter.setMinimumWidth(400)
        self.right_splitter.setMinimumWidth(400)
        self.reference_section = self._reference_section()
        self.transcription_section = self._transcription_section()
        self.profile_section = self._profile_section()
        self.speech_section = self._speech_section()
        self.generation_section = self._generation_section()
        self.output_section = self._output_section()
        self.left_splitter.addWidget(self.reference_section)
        self.left_splitter.addWidget(self.transcription_section)
        self.left_splitter.addWidget(self.profile_section)
        self.right_splitter.addWidget(self.speech_section)
        self.right_splitter.addWidget(self.generation_section)
        self.left_splitter.setSizes([195, 165, 180])
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
        self.workspace_splitter.setSizes([545, 215])
        layout.addWidget(self.workspace_splitter, 1)
        self.setCentralWidget(workspace)
        QWidget.setTabOrder(self.choose_reference_button, self.clear_reference_button)
        QWidget.setTabOrder(self.clear_reference_button, self.reference_player.waveform)
        QWidget.setTabOrder(self.reference_player.waveform, self.reference_player.play_button)
        QWidget.setTabOrder(self.reference_player.play_button, self.cloning_mode)
        QWidget.setTabOrder(self.cloning_mode, self.transcript_editor)
        QWidget.setTabOrder(self.transcript_editor, self.transcribe_button)
        QWidget.setTabOrder(self.transcribe_button, self.prepare_button)
        QWidget.setTabOrder(self.prepare_button, self.load_profile_button)
        QWidget.setTabOrder(self.load_profile_button, self.save_profile_button)
        QWidget.setTabOrder(self.save_profile_button, self.clear_profile_button)
        QWidget.setTabOrder(self.clear_profile_button, self.speech_editor)
        QWidget.setTabOrder(self.speech_editor, self.generate_button)
        QWidget.setTabOrder(self.generate_button, self.stop_generation_button)
        QWidget.setTabOrder(self.stop_generation_button, self.output_player.waveform)

    @staticmethod
    def _make_splitter(orientation: Qt.Orientation, accessible_name: str) -> QSplitter:
        splitter = QSplitter(orientation)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.setAccessibleName(accessible_name)
        return splitter

    def _reference_section(self) -> Section:
        section = ReferenceSection()
        section.body.setSpacing(4)
        section.body.setContentsMargins(16, 6, 16, 6)
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
        self.reference_player.waveform.setMinimumHeight(56)
        self.reference_player.audio_ready.connect(self._reference_loaded)
        self.reference_player.load_failed.connect(self._reference_failed)
        self.reference_player.playback_error.connect(self._playback_failed)
        section.body.addWidget(self.reference_player, 1)
        self.reference_status = section.body.itemAt(1).widget()
        return section

    def _transcription_section(self) -> Section:
        section = Section("Transcription", "Review and correct the reference transcript.")
        section.body.setSpacing(4)
        section.body.setContentsMargins(16, 6, 16, 6)
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
        self.transcript_editor.setMinimumHeight(60)
        self.transcript_editor.textChanged.connect(self._transcript_changed)
        section.body.addWidget(self.transcript_editor, 1)
        row = QHBoxLayout()
        self.transcribe_button = QPushButton("Transcribe reference")
        self.transcribe_button.setEnabled(False)
        self.transcribe_button.clicked.connect(self.transcribe_reference)
        row.addWidget(section.body.takeAt(0).widget())
        row.addStretch()
        row.addWidget(self.transcribe_button)
        section.body.insertLayout(0, row)
        return section

    def _profile_section(self) -> Section:
        section = Section("Voice Profile", "")
        section.body.itemAt(1).widget().hide()
        section.body.setContentsMargins(16, 6, 16, 6)
        section.body.setSpacing(4)
        identity = QHBoxLayout()
        self.profile_name = label("No profile", "muted")
        self.profile_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.profile_name.setAccessibleName("Current voice profile name")
        self.profile_status = label(ProfileStatus.NOT_PREPARED.value, "muted")
        identity.addWidget(self.profile_name, 1)
        identity.addWidget(self.profile_status)
        section.body.addLayout(identity)
        self.prepare_button = QPushButton("Prepare Voice")
        self.prepare_button.clicked.connect(self.prepare_voice)
        self.save_profile_button = QPushButton("Save Profile")
        self.save_profile_button.clicked.connect(self.choose_save_profile)
        self.load_profile_button = QPushButton("Load Profile")
        self.load_profile_button.clicked.connect(self.choose_load_profile)
        self.clear_profile_button = QPushButton("Clear Profile")
        self.clear_profile_button.clicked.connect(self.clear_profile)
        for buttons in ((self.prepare_button, self.load_profile_button), (self.save_profile_button, self.clear_profile_button)):
            actions = QHBoxLayout()
            actions.setSpacing(6)
            for button in buttons:
                actions.addWidget(button)
            section.body.addLayout(actions)
        self.preparation_progress = OperationProgress("Prepare a voice or load a profile.")
        section.body.addWidget(self.preparation_progress)
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
        section = Section("Generation", "Generate a new recording using the prepared voice and current Speech Text.")
        section.setMinimumHeight(180)
        self.model_status = label("Qwen3-TTS Base · loaded on first use", "muted", True)
        section.body.addWidget(self.model_status)
        self.generation_progress = OperationProgress("Prepare or load a voice profile to begin.")
        self.generation_status = self.generation_progress.stage
        section.body.addWidget(self.generation_progress)
        section.body.addStretch(1)
        row = QHBoxLayout()
        row.addStretch()
        self.generate_button = QPushButton("Generate Speech")
        self.generate_button.clicked.connect(self.generate_speech)
        self.generate_button.setProperty("primary", "true")
        row.addWidget(self.generate_button)
        self.stop_generation_button = QPushButton("Stop Generation")
        self.stop_generation_button.setToolTip("Discard this generation safely; native inference may need to finish.")
        self.stop_generation_button.clicked.connect(self.stop_generation)
        row.addWidget(self.stop_generation_button)
        section.body.addLayout(row)
        return section

    def _output_section(self) -> Section:
        section = Section("Output", "Generated audio stays in memory until you export WAV.")
        section.body.setContentsMargins(16, 8, 16, 8)
        section.body.setSpacing(6)
        self.output_status = section.body.itemAt(1).widget()
        self.output_player = AudioPlayer()
        self.output_player.playback_error.connect(self._playback_failed)
        self.output_player.audio_ready.connect(self._output_loaded)
        self.output_player.load_failed.connect(self._output_failed)
        section.body.addWidget(self.output_player, 1)
        self.export_button = QPushButton("Export WAV…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.choose_export_wav)
        self.output_player.controls.addWidget(self.export_button)
        return section

    def _transcript_changed(self) -> None:
        if self.session.reference_locked:
            with QSignalBlocker(self.transcript_editor):
                self.transcript_editor.setPlainText(self.session.transcript)
            return
        self._cancel_transcription("Transcription cancelled · edited draft kept")
        self.session.transcript = self.transcript_editor.toPlainText()
        self._invalidate_voice()
        self._update_reference_actions()

    def _cloning_mode_changed(self) -> None:
        if self.session.reference_locked:
            with QSignalBlocker(self.cloning_mode):
                self.cloning_mode.setCurrentIndex(self.cloning_mode.findData(self.session.cloning_mode))
            return
        self._cancel_transcription("Transcription cancelled · mode changed")
        self.session.cloning_mode = CloningMode(self.cloning_mode.currentData())
        self._invalidate_voice()
        self._update_transcription_controls()
        self._update_voice_actions()

    def _update_transcription_controls(self) -> None:
        icl = self.session.cloning_mode == CloningMode.ICL
        unlocked = not self.session.reference_locked
        self.transcription_section.setEnabled(unlocked and not self._closing)
        self.cloning_mode.setEnabled(unlocked and not self._closing)
        self.transcript_editor.setEnabled(icl and unlocked and not self._closing)
        self.transcript_editor.setReadOnly(self._importing)
        self.transcribe_button.setEnabled(icl and self.session.reference is not None
                                         and not self._importing and not self.transcription.busy
                                         and not self.voice.busy
                                         and unlocked and not self._closing)
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
        if (self._closing or self.session.reference_locked or self._importing or self.transcription.busy or self.voice.busy
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
        self._update_voice_actions()

    def _speech_changed(self) -> None:
        self.session.speech_text = self.speech_editor.toPlainText()
        count = len(self.session.speech_text)
        self.character_count.setText(f"{count:,} {'character' if count == 1 else 'characters'}")
        self._update_voice_actions()

    def choose_reference(self) -> None:
        if self._closing or self.session.reference_locked:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose reference audio", str(self.paths.samples),
            "Reference audio (*.wav *.ogg);;WAV audio (*.wav);;OGG audio (*.ogg)",
        )
        if filename:
            self.select_reference(Path(filename))

    def select_reference(self, path: Path) -> bool:
        """Queue an import; success is committed only after decoding and Qt load."""
        if self._closing or self.session.reference_locked:
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
        self._cancel_voice_work()
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
        self._invalidate_voice()
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
        unlocked = not self.session.reference_locked and not self._closing
        self.reference_section.setEnabled(unlocked)
        self.reference_section.setAcceptDrops(unlocked)
        self.choose_reference_button.setEnabled(unlocked)
        self.clear_reference_button.setEnabled(not self._closing and (
            self.session.reference is not None or bool(self.session.transcript) or self._importing) and unlocked)
        self._update_transcription_controls()
        self._update_voice_actions()

    def _reset_reference(self) -> None:
        # Invalidate worker completions before resetting either the UI or state.
        self._cancel_transcription("Reference cleared")
        self._invalidate_voice()
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
        if self._closing or self.session.reference_locked:
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
        if self.session.has_content or self._importing or self.output_player.has_content or self.voice.busy:
            answer = QMessageBox.question(
                self, "New Voice?", "Start a new voice and discard the current reference, text drafts, voice profile, and output preview? Saved files are kept.",
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
        self._output_context = None
        self.output_status.setText("Generated audio stays in memory until you export WAV.")
        self.preparation_progress.reset()
        self.generation_progress.reset()
        self.export_button.setEnabled(False)
        self._update_voice_actions()
        self.statusBar().showMessage("New voice ready. Audio files and application preferences were kept.")
        self.choose_reference_button.setFocus()
        return True

    def _update_voice_actions(self) -> None:
        if not hasattr(self, "generate_button"):
            return
        idle = not self._closing and not self.voice.busy and not self._importing and self._output_context is None
        available = self.session.profile is not None and self.session.profile_status == ProfileStatus.READY
        can_prepare = self.session.can_prepare
        self.prepare_button.setEnabled(idle and can_prepare and not self.transcription.busy)
        self.prepare_button.setToolTip("Cache this reference voice for repeated generation. ICL requires reviewed transcription.")
        self.save_profile_button.setEnabled(idle and available)
        self.load_profile_button.setEnabled(idle and not self.transcription.busy)
        self.clear_profile_button.setEnabled(not self._closing and (self.session.profile is not None
                                             or self._voice_context is not None or self._output_context is not None))
        self.generate_button.setEnabled(idle and self.session.can_generate
                                        and not self.transcription.busy and self._output_context is None)
        self.stop_generation_button.setEnabled(not self._closing and not self._generation_stopping
            and ((self.voice.busy and self._voice_context is not None and self._voice_context[1] == "generate")
                 or self._output_context is not None))
        self.generate_button.setToolTip("Each click generates a new variation using the cached voice profile.")
        self.export_button.setEnabled(idle and self.session.output is not None and self.output_player.has_content)
        self.profile_status.setText(self.session.profile_status.value)
        self.profile_name.setText(self.session.profile_name or "No profile")
        self.profile_name.setToolTip(self.session.profile_name)
        profile = self.session.profile
        if profile is not None:
            origin = str(profile.imported_from or profile.source_reference or "In-memory profile")
            self.profile_status.setToolTip(f"{profile.mode.value} · {origin}\nProfiles are saved separately from text drafts.")
        else:
            self.profile_status.setToolTip("Changes to reference audio, transcription, or mode require preparation. Speech Text can change freely.")

    def _cancel_voice_work(self) -> None:
        self._generation_stopping = False
        self.voice.cancel()
        operation = self._voice_context[1] if self._voice_context else "generate" if self._output_context else None
        if operation is not None:
            self._operation_progress(operation).reset("Operation cancelled.")
        self._voice_context = None
        self._voice_timer.stop()
        pending_output = self._output_context is not None
        self._output_context = None
        if pending_output and hasattr(self, "output_player"):
            self.output_player.cancel_pending()
        if self.session.profile_status == ProfileStatus.PREPARING:
            self.session.profile_status = ProfileStatus.READY if self.session.profile else ProfileStatus.NEEDS_PREPARATION

    def _invalidate_voice(self) -> None:
        self._cancel_voice_work()
        self.session.invalidate_profile()
        if hasattr(self, "generation_progress"):
            self.generation_progress.reset()
            self.preparation_progress.reset("Reference inputs changed; prepare the voice again.")
        self._update_voice_actions()

    def clear_profile(self) -> bool:
        if self._closing:
            return False
        self._cancel_voice_work()
        self.session.clear_profile()
        if self.session.reference is None:
            self.reference_status.setText("No reference loaded")
            self.transcription_status.setText("Review and correct the reference transcript.")
        self.preparation_progress.reset()
        self.generation_progress.reset()
        self._update_reference_actions()
        self.statusBar().showMessage("Voice profile cleared. Speech Text, output, loaded models, and files were kept.")
        return True

    def _operation_progress(self, operation: str) -> OperationProgress:
        return self.preparation_progress if operation in {"prepare", "load", "save"} else self.generation_progress

    def _start_voice_job(self, operation: str, *arguments) -> bool:
        if (self._closing or self.voice.busy or self._importing or self.transcription.busy
                or self._output_context is not None):
            return False
        if operation == "prepare" and not self.session.can_prepare:
            return False
        if operation == "generate" and not self.session.can_generate:
            return False
        self._voice_context = (self.session.voice_revision, operation)
        if operation in {"prepare", "load"}:
            self._output_context = None
            self.output_player.cancel_pending()
        self._voice_phase = {"prepare": "Preparing voice", "generate": "Generating speech",
                             "save": "Saving profile", "load": "Loading profile", "export": "Exporting WAV"}[operation]
        self._voice_elapsed.start()
        self._voice_device = ("CPU · file I/O" if operation in {"load", "save", "export"}
                              else self.voice.model_description if self.voice.model_loaded else "")
        self._voice_timer.start()
        if operation == "prepare":
            self.session.profile_status = ProfileStatus.PREPARING
        if not self.voice.start(operation, *arguments):
            self._voice_context = None
            self._voice_timer.stop()
            return False
        self._update_voice_status()
        return True

    def prepare_voice(self) -> bool:
        if self.voice.busy or self._closing or self.session.reference_locked or self._importing or self.transcription.busy:
            return False
        try:
            arguments = self.session.voice_clone_arguments()
        except ValueError as error:
            QMessageBox.warning(self, "Cannot prepare voice", str(error))
            return False
        return self._start_voice_job("prepare", arguments)

    def generate_speech(self) -> bool:
        if not self.session.can_generate or self._output_context is not None:
            return False
        return self._start_voice_job("generate", self.session.profile, self.session.speech_text)

    def stop_generation(self) -> bool:
        if self._closing or self._generation_stopping:
            return False
        if not ((self.voice.busy and self._voice_context is not None and self._voice_context[1] == "generate")
                or self._output_context is not None):
            return False
        # Invalidates queued completion before touching the preview candidate.
        # The accepted Output and cached profile/model remain untouched.
        self._cancel_voice_work()
        self._generation_stopping = self.voice.busy
        if self._generation_stopping:
            self._voice_phase = "Stopping generation..."
            self._voice_timer.start()
            self._update_voice_status()
        else:
            self._finish_generation_cancellation()
        self._update_voice_actions()
        return True

    def _finish_generation_cancellation(self) -> None:
        self._generation_stopping = False
        self._voice_timer.stop()
        self.generation_progress.finish("Generation canceled.", self._voice_elapsed.elapsed() / 1000,
                                        self._voice_device)
        self.statusBar().showMessage("Generation canceled. Previous Output and voice profile were kept.")

    def _confirm_overwrite(self, path: Path) -> bool:
        if not path.exists():
            return True
        return QMessageBox.question(
            self, "Replace existing file?", f"Replace this existing file?\n{path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def choose_save_profile(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save voice profile", str(self.paths.samples / "voice-profile.pt"), "Voice profile (*.pt)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if filename:
            path = Path(filename)
            self.save_voice_profile(path if path.suffix else path.with_suffix(".pt"))

    def save_voice_profile(self, path: Path) -> bool:
        if self.session.profile is None or self.voice.busy or self._closing:
            return False
        path = Path(path)
        overwrite = path.exists()
        if not self._confirm_overwrite(path):
            return False
        return self._start_voice_job("save", self.session.profile, path, overwrite)

    def choose_load_profile(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load voice profile", str(self.paths.samples), "Voice profile (*.pt)",
        )
        if filename:
            self.load_voice_profile(Path(filename))

    def load_voice_profile(self, path: Path) -> bool:
        if (self.voice.busy or self._closing or self._importing or self.transcription.busy
                or self._output_context is not None):
            return False
        if self.session.reference is not None or self.session.transcript or self.session.profile is not None:
            answer = QMessageBox.question(
                self, "Replace voice preparation?",
                "Load this profile in place of the current reference, transcript, and voice profile? Speech Text and saved files are kept. Invalid profiles leave your workspace unchanged.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        return self._start_voice_job("load", Path(path))

    def choose_export_wav(self) -> None:
        if self.session.output is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export WAV", str(self.paths.output / self.session.output.suggested_filename), "WAV audio (*.wav)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if filename:
            path = Path(filename)
            self.export_wav(path if path.suffix else path.with_suffix(".wav"))

    def export_wav(self, path: Path) -> bool:
        if self.session.output is None or self.voice.busy or self._closing:
            return False
        path = Path(path)
        overwrite = path.exists()
        if not self._confirm_overwrite(path):
            return False
        return self._start_voice_job("export", self.session.output, path, overwrite)

    def _voice_progress(self, message: str) -> None:
        parts = message.split(" · ", 1)
        self._voice_phase = parts[0]
        if len(parts) == 2:
            self._voice_device = parts[1]
        self._update_voice_status()

    def _update_voice_status(self) -> None:
        if (self._voice_context is None and self._output_context is None and not self._generation_stopping) or self._closing:
            return
        operation = self._voice_context[1] if self._voice_context else "generate"
        elapsed = self._voice_elapsed.elapsed() / 1000
        message = f"{self._voice_phase} · {elapsed:.1f} s"
        self._operation_progress(operation).update_status(self._voice_phase, elapsed, self._voice_device)
        self.statusBar().showMessage(message)

    def _voice_busy_changed(self, busy: bool) -> None:
        if not busy and self._generation_stopping and not self._closing:
            self._finish_generation_cancellation()
        self._update_voice_actions()
        self._update_transcription_controls()

    def _voice_ready(self, operation: str, result) -> None:
        if self._closing or self._voice_context != (self.session.voice_revision, operation):
            return
        self._voice_context = None
        self._voice_timer.stop()
        elapsed = self._voice_elapsed.elapsed() / 1000
        if self.voice.model_loaded:
            self.model_status.setText(f"Qwen3-TTS Base · {self.voice.model_description}")
            self.model_status.setToolTip(self.voice.gpu_error)
        if operation == "load":
            # Commit only after safe deserialization and compatibility validation.
            # Suppress editor/mode signals while restoring the imported workspace.
            self._cancel_transcription("Imported profile loaded")
            self.reference_loader.cancel()
            self.reference_player.clear()
            self.session.accept_profile(result)
            with QSignalBlocker(self.transcript_editor), QSignalBlocker(self.cloning_mode):
                self.transcript_editor.clear()
                self.cloning_mode.setCurrentIndex(self.cloning_mode.findData(result.mode))
            self.reference_path.clear()
            self.reference_path.setToolTip("")
            self.reference_status.setText("Imported profile · reference inputs locked")
            self.transcription_status.setText("ICL reference text is stored in the profile."
                if result.mode == CloningMode.ICL else "X-Vector profile · no reference text required.")
            self._update_reference_actions()
            message = f"Profile loaded · {result.mode.value} · {elapsed:.1f} s"
        elif operation == "prepare":
            self.session.accept_profile(result)
            message = f"Voice ready · {elapsed:.1f} s · {self.voice.model_description}"
        elif operation == "generate":
            self._output_context = (self.session.voice_revision, result.profile_identifier, result)
            self._voice_phase = "Preparing output playback..."
            self._voice_timer.start()
            self._update_voice_status()
            self.output_player.load_recording(result.recording)
            self._update_voice_actions()
            return
        else:
            if operation == "save":
                self.session.profile_name = result.stem
            if operation == "export":
                self.output_status.setText(f"In memory · Exported: {result.name}")
                self.output_status.setToolTip(str(result))
            message = f"{'Profile saved' if operation == 'save' else 'WAV exported'} · {result}"
        success = "Voice profile ready." if operation == "prepare" else "Profile loaded." if operation == "load" else "Profile saved." if operation == "save" else "WAV exported."
        self._operation_progress(operation).finish(success, elapsed, self._voice_device)
        self.statusBar().showMessage(message)
        self._update_voice_actions()
        self._update_transcription_controls()

    def _voice_failed(self, message: str) -> None:
        if self._closing or self._voice_context is None:
            return
        operation = self._voice_context[1]
        self._voice_context = None
        self._voice_timer.stop()
        if operation == "prepare":
            self.session.profile_status = ProfileStatus.READY if self.session.profile else ProfileStatus.NEEDS_PREPARATION
        self._operation_progress(operation).finish(f"{operation.capitalize()} failed.",
            self._voice_elapsed.elapsed() / 1000, self._voice_device, error=True, technical=message)
        self.statusBar().showMessage(f"{operation.capitalize()} failed. Existing drafts, profiles, and recordings were kept.")
        self._update_voice_actions()
        QMessageBox.warning(self, "Voice operation failed", f"{message}\n\nYour text drafts and existing saved files are kept.")

    def _output_loaded(self, recording) -> None:
        context = self._output_context
        if context is None or self._closing:
            return
        revision, identifier, result = context
        self._output_context = None
        if (revision != self.session.voice_revision or self.session.profile is None
                or identifier != self.session.profile.identifier or recording is not result.recording):
            return
        self.session.output = recording
        self._voice_timer.stop()
        self.generation_progress.finish("Generation completed.", self._voice_elapsed.elapsed() / 1000, self._voice_device)
        self.statusBar().showMessage(f"Generation completed · in memory · {self._voice_elapsed.elapsed() / 1000:.1f} s")
        self.output_status.setText(f"In memory · {format_time(recording.duration_ms)} · Export WAV to keep this recording.")
        self.output_status.setToolTip(f"{recording.sample_rate} Hz · {recording.channels} channel · float32 PCM\n{recording.suggested_filename}")
        self._update_voice_actions()

    def _output_failed(self, message: str) -> None:
        if self._output_context is None or self._closing:
            return
        self._output_context = None
        self._voice_timer.stop()
        self.generation_progress.finish("Output loading failed; previous preview kept.",
            self._voice_elapsed.elapsed() / 1000, self._voice_device, error=True, technical=message)
        self.statusBar().showMessage("In-memory preview failed. Previous recording was kept.")
        self._update_voice_actions()
        QMessageBox.warning(self, "Cannot preview generated WAV", f"{message}\n\nNo audio was saved. Any previous preview is kept.")

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

    def show_settings(self) -> None:
        dialog = SettingsDialog(self.theme, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.theme.set_mode(dialog.selected_mode)

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About Qwen3 TTS Studio",
            f"<b>Qwen3 TTS Studio</b> {__version__}<br><br>"
            "An offline workspace for voice preparation and speech synthesis.<br>"
            "Includes local Faster Whisper transcription, reusable Qwen3-TTS voice profiles, speech generation, waveform playback, and WAV export. "
            "Audio post-processing is not implemented.<br><br>"
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
        if self.reference_loader.has_workers or self.transcription.has_workers or self.voice.has_workers:
            event.ignore()
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage("Closing · waiting for background work and model cleanup…")
            return
        event.accept()

    def _workers_drained(self) -> None:
        if (self._closing and not self.reference_loader.has_workers
                and not self.transcription.has_workers and not self.voice.has_workers):
            QTimer.singleShot(0, self.close)

    def release_resources(self) -> None:
        self._import_timer.stop()
        self._transcription_timer.stop()
        self._voice_timer.stop()
        self._voice_context = None
        self._output_context = None
        self.voice.shutdown()
        self.transcription.shutdown()
        self.reference_loader.shutdown()
        self.reference_player.release()
        self.output_player.release()
