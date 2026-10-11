"""Compose the desktop workspace without importing AI dependencies."""

# Copyright (c) 2026 Nendis. SPDX-License-Identifier: MIT

import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .application.workspace import WorkspacePaths
from .ui.main_window import MainWindow
from .ui.theme import ThemeController


def create_window(app: QApplication, settings: QSettings | None = None) -> MainWindow:
    app.setApplicationName("Qwen3 TTS Studio")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Nendis")
    app.setFont(QFont("Segoe UI", 10))
    icon_path = Path(__file__).resolve().parent / "ui" / "assets" / "Qwen3-TTS-Studio-icon.ico"
    icon = QIcon(str(icon_path))
    if icon.isNull():
        raise RuntimeError(f"Cannot load the application icon: {icon_path}")
    app.setWindowIcon(icon)
    if settings is None:
        settings = QSettings()
    theme = ThemeController(app, settings)
    return MainWindow(WorkspacePaths.from_source(), theme)


def main() -> int:
    if sys.platform == "win32":
        import ctypes

        # Give Windows a stable taskbar identity before creating any UI.
        set_app_id = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        result = set_app_id("Nendis.Qwen3TTSStudio")
        if result < 0:
            raise OSError(f"Cannot set the Windows application identity (HRESULT {result:#x}).")
    app = QApplication(sys.argv)
    window = create_window(app)
    window.show()
    try:
        return app.exec()
    finally:
        window.release_resources()
        window.reference_loader.wait_for_shutdown()
