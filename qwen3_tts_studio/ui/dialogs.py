"""Small, functional settings and application information dialogs."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout,
)

from .theme import ThemeController


class SettingsDialog(QDialog):
    def __init__(self, theme: ThemeController, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        form = QFormLayout()
        self.appearance = QComboBox()
        self.appearance.addItem("Follow Windows (default)", "system")
        self.appearance.addItem("Light", "light")
        self.appearance.addItem("Dark", "dark")
        self.appearance.setCurrentIndex(self.appearance.findData(theme.mode))
        form.addRow("&Appearance", self.appearance)
        layout.addLayout(form)
        note = QLabel("Follow Windows updates the application automatically when the system appearance changes.")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_mode(self) -> str:
        return self.appearance.currentData()
