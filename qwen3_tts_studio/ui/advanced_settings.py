"""Compact collapsible controls, independent of voice preparation."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QToolButton,
                              QDoubleSpinBox, QSpinBox, QComboBox, QPushButton, QLabel, QLayout)
from ..application.generation_settings import GenerationSettings


class AdvancedSettings(QWidget):
    changed = Signal(object)

    def __init__(self, defaults, languages, parent=None):
        super().__init__(parent)
        self.defaults, self.languages = defaults, languages
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.toggle = QToolButton()
        self.toggle.setText("Advanced Settings")
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.toggle)
        self.panel = QWidget()
        grid = QGridLayout(self.panel)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(3)
        self.controls = {}
        specifications = (
            ("temperature", "Temperature", .01, 5., .05, "Higher values increase sampling randomness; lower values narrow choices."),
            ("top_p", "Top P", .01, 1., .05, "Samples from tokens whose combined probability reaches this threshold."),
            ("top_k", "Top K", 0, 3072, 1, "Limits sampling to the K most likely tokens. 0 disables this filter."),
            ("repetition_penalty", "Repetition Penalty", .01, 5., .05, "1 leaves repetition unchanged; values above 1 discourage repeated tokens."),
        )
        for index, (name, title, low, high, step, tooltip) in enumerate(specifications):
            control = QSpinBox() if name == "top_k" else QDoubleSpinBox()
            if isinstance(control, QDoubleSpinBox):
                control.setDecimals(3)
            control.setRange(low, high)
            control.setMinimumHeight(28)
            control.setSingleStep(step)
            control.setAccessibleName(title)
            control.setToolTip(tooltip)
            caption = QLabel(title)
            caption.setBuddy(control)
            caption.setToolTip(tooltip)
            row, column = divmod(index, 2)
            grid.addWidget(caption, row, column * 2)
            grid.addWidget(control, row, column * 2 + 1)
            self.controls[name] = control
            control.valueChanged.connect(self._edited)
        self.language = QComboBox()
        self.language.addItems(languages)
        self.language.setAccessibleName("Generation language")
        self.language.setToolTip("Language of the generated speech. Auto lets Qwen infer it from the text.")
        grid.addWidget(QLabel("Language"), 2, 0)
        grid.addWidget(self.language, 2, 1)
        self.reset = QPushButton("Reset to Defaults")
        self.reset.setToolTip("Restore the local model's original generation settings and Auto language.")
        grid.addWidget(self.reset, 2, 2, 1, 2)
        self.language.currentTextChanged.connect(self._edited)
        self.reset.clicked.connect(self.reset_defaults)
        layout.addWidget(self.panel)
        self.panel.hide()
        self.toggle.toggled.connect(self._expanded)
        self.set_settings(defaults)

    def _expanded(self, expanded):
        self.panel.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def settings(self):
        return GenerationSettings(**{name: control.value() for name, control in self.controls.items()},
                                  language=self.language.currentText()).validate(self.languages)

    def set_settings(self, settings):
        settings.validate(self.languages)
        for name, control in self.controls.items():
            with QSignalBlocker(control):
                control.setValue(getattr(settings, name))
        with QSignalBlocker(self.language):
            self.language.setCurrentIndex(self.language.findText(settings.language, Qt.MatchFlag.MatchFixedString))

    def _edited(self):
        self.changed.emit(self.settings())

    def reset_defaults(self):
        self.set_settings(self.defaults)
        self.changed.emit(self.defaults)
