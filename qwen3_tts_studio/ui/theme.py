"""Light/dark styling driven by Qt's supported system appearance API."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

from dataclasses import dataclass

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Colors:
    background: str
    surface: str
    editor: str
    text: str
    muted: str
    border: str
    hover: str
    accent: str
    accent_hover: str
    selection_text: str
    disabled: str
    waveform_played: str
    waveform_unplayed: str


LIGHT = Colors(
    "#f3f4f6", "#ffffff", "#ffffff", "#20252c", "#596373", "#d3d8df",
    "#edf0f4", "#245fbc", "#1d509e", "#ffffff", "#757f8c", "#317fea", "#8d9fb5",
)
DARK = Colors(
    "#191c21", "#22262d", "#1c2026", "#e6e9ef", "#a6afbd", "#3d4551",
    "#303640", "#8bb6ff", "#b1ceff", "#14233d", "#87909e", "#79b1ff", "#61758f",
)


def stylesheet(colors: Colors) -> str:
    return f"""
        QMainWindow, QDialog, QWidget#workspace {{ background: {colors.background}; }}
        QFrame[section="true"] {{
            background: {colors.surface}; border: 1px solid {colors.border};
            border-radius: 3px;
        }}
        QFrame[dropTarget="true"][dragActive="true"] {{ border-color: {colors.accent}; }}
        QLabel {{ color: {colors.text}; background: transparent; }}
        QLabel[role="muted"] {{ color: {colors.muted}; }}
        QLabel[error="true"] {{ color: {"#f28b82" if colors == DARK else "#b42318"}; }}
        QProgressBar {{
            border: 1px solid {colors.border}; border-radius: 1px;
            background: {colors.editor};
        }}
        QProgressBar::chunk {{ background: {colors.accent}; border-radius: 0px; }}
        QLabel[role="title"] {{ font-size: 20px; font-weight: 600; }}
        QLabel[role="sectionTitle"] {{ font-size: 15px; font-weight: 600; }}
        QLabel[role="badge"] {{
            color: {colors.muted}; border: 1px solid {colors.border};
            padding: 5px 9px; border-radius: 3px;
        }}
        QPlainTextEdit, QLineEdit {{
            color: {colors.text}; background: {colors.editor};
            border: 1px solid {colors.border}; border-radius: 2px; padding: 7px;
            selection-background-color: {colors.accent};
            selection-color: {colors.selection_text};
        }}
        QPlainTextEdit:focus, QLineEdit:focus {{ border-color: {colors.accent}; }}
        QFrame#waveformView {{
            background: {colors.editor}; border: 1px solid {colors.border}; border-radius: 2px;
        }}
        QPushButton {{
            color: {colors.text}; background: {colors.surface};
            border: 1px solid {colors.border}; border-radius: 3px;
            padding: 6px 12px; min-height: 18px;
        }}
        QPushButton:hover {{ background: {colors.hover}; }}
        QPushButton:pressed {{ border-color: {colors.accent}; }}
        QPushButton:focus {{ border-color: {colors.accent}; }}
        QPushButton[primary="true"] {{
            color: {colors.selection_text}; background: {colors.accent};
            border-color: {colors.accent}; font-weight: 600;
        }}
        QPushButton[primary="true"]:hover {{ background: {colors.accent_hover}; }}
        QPushButton:disabled, QPushButton[primary="true"]:disabled {{
            color: {colors.disabled}; background: {colors.background};
            border-color: {colors.border};
        }}
        QComboBox {{ padding: 5px 8px; min-height: 20px; }}
        QSpinBox, QDoubleSpinBox {{
            color: {colors.text}; background: {colors.editor};
            border: 1px solid {colors.border}; border-radius: 2px; padding: 3px;
            selection-background-color: {colors.accent};
            selection-color: {colors.selection_text};
        }}
        QToolButton {{ color: {colors.text}; background: transparent; padding: 3px; }}
        QToolButton:hover {{ background: {colors.hover}; }}
        QMenuBar {{
            background: {colors.surface}; color: {colors.text};
            border-bottom: 1px solid {colors.border};
        }}
        QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
        QMenuBar::item:selected {{ background: {colors.hover}; }}
        QMenu {{
            background: {colors.surface}; color: {colors.text};
            border: 1px solid {colors.border}; padding: 4px;
        }}
        QMenu::item {{ padding: 6px 24px 6px 12px; }}
        QMenu::item:selected {{ background: {colors.accent}; color: {colors.selection_text}; }}
        QMenu::separator {{ height: 1px; background: {colors.border}; margin: 4px; }}
        QStatusBar {{ background: {colors.surface}; color: {colors.muted}; }}
        QStatusBar::item {{ border: none; }}
        QSplitter::handle {{ background: {colors.background}; }}
        QSplitter::handle:hover {{ background: {colors.border}; }}
        QToolTip {{
            color: {colors.text}; background: {colors.surface};
            border: 1px solid {colors.border}; padding: 4px;
        }}
    """


class ThemeController(QObject):
    changed = Signal(str)
    MODES = {"system": Qt.ColorScheme.Unknown,
             "light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}

    def __init__(self, app: QApplication, settings: QSettings):
        super().__init__(app)
        self.app = app
        self.settings = settings
        stored = str(settings.value("appearance", "system"))
        self.mode = stored if stored in self.MODES else "system"
        self.current_theme = ""
        # Qt updates its default palette after emitting this signal. Queue our
        # styling so Qt's update cannot overwrite the application palette.
        app.styleHints().colorSchemeChanged.connect(
            self._scheme_changed, Qt.ConnectionType.QueuedConnection,
        )
        app.styleHints().setColorScheme(self.MODES[self.mode])
        self._apply(app.styleHints().colorScheme())

    def set_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(f"Unknown appearance mode: {mode}")
        self.mode = mode
        self.settings.setValue("appearance", mode)
        self.app.styleHints().setColorScheme(self.MODES[mode])
        self._apply(self.app.styleHints().colorScheme())

    def _scheme_changed(self, scheme: Qt.ColorScheme) -> None:
        self._apply(scheme)

    def _apply(self, scheme: Qt.ColorScheme) -> None:
        if scheme == Qt.ColorScheme.Unknown:
            # Use the platform palette only when it cannot report a scheme.
            dark = self.app.style().standardPalette().color(QPalette.ColorRole.Window).lightness() < 128
        else:
            dark = scheme == Qt.ColorScheme.Dark
        self.current_theme = "dark" if dark else "light"
        colors = DARK if dark else LIGHT
        palette = QPalette()
        roles = {
            QPalette.ColorRole.Window: colors.background,
            QPalette.ColorRole.WindowText: colors.text,
            QPalette.ColorRole.Base: colors.editor,
            QPalette.ColorRole.AlternateBase: colors.hover,
            QPalette.ColorRole.Text: colors.text,
            QPalette.ColorRole.Button: colors.surface,
            QPalette.ColorRole.ButtonText: colors.text,
            QPalette.ColorRole.ToolTipBase: colors.surface,
            QPalette.ColorRole.ToolTipText: colors.text,
            QPalette.ColorRole.Highlight: colors.accent,
            QPalette.ColorRole.HighlightedText: colors.selection_text,
            QPalette.ColorRole.Link: colors.accent,
            QPalette.ColorRole.PlaceholderText: colors.muted,
            QPalette.ColorRole.Light: colors.border,
            QPalette.ColorRole.Midlight: colors.hover,
            QPalette.ColorRole.Mid: colors.border,
            QPalette.ColorRole.Dark: colors.border,
            QPalette.ColorRole.Shadow: colors.background,
            QPalette.ColorRole.BrightText: colors.text,
        }
        for role, color in roles.items():
            palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                     QPalette.ColorRole.WindowText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors.disabled))
        self.app.setPalette(palette)
        self.app.setStyleSheet(stylesheet(colors))
        self.changed.emit(self.current_theme)
