"""Shared, percentage-free presentation of real background operation stages."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget


class OperationProgress(QWidget):
    def __init__(self, idle_text: str, parent=None):
        super().__init__(parent)
        self.idle_text = idle_text
        self.active = False
        self.stage = QLabel()
        self.stage.setTextFormat(Qt.TextFormat.PlainText)
        self.stage.setProperty("role", "muted")
        self.stage.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.details = QLabel()
        self.details.setProperty("role", "muted")
        self.details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setAccessibleName("Operation progress")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        status = QHBoxLayout()
        status.setSpacing(6)
        status.addWidget(self.stage, 1)
        self.details.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        status.addWidget(self.details)
        layout.addLayout(status)
        layout.addWidget(self.bar)
        self.reset()

    def reset(self, text: str | None = None):
        self.active = False
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self._stage(text or self.idle_text, False)
        self.details.setText("")
        self.details.setToolTip("")

    def _stage(self, text: str, error: bool):
        self.stage.setText(text)
        self.stage.setToolTip(text)
        self.stage.setProperty("error", "true" if error else "false")
        self.stage.style().unpolish(self.stage)
        self.stage.style().polish(self.stage)

    def update_status(self, text: str, elapsed: float, device: str = ""):
        if not self.active:
            self.active = True
            self.bar.setRange(0, 0)
        if text != self.stage.text():
            self._stage(text, False)
        short_device = "GPU (CUDA)" if device.startswith("GPU") else "CPU" if device.startswith("CPU") else "Device pending"
        self.details.setText(f"{elapsed:.1f} s · {short_device}")
        self.details.setToolTip(f"{elapsed:.1f} s · {device or 'Device not yet known'}")

    def finish(self, text: str, elapsed: float, device: str = "", error: bool = False, technical: str = ""):
        self.update_status(text, elapsed, device)
        self.active = False
        self.bar.setRange(0, 1)
        self.bar.setValue(0 if error else 1)
        self._stage(text, error)
        self.stage.setToolTip(technical or text)
