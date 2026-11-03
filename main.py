"""StreamSniper application entry point."""
import ctypes
import sys

if getattr(sys, "frozen", False) and sys.argv[1:2] == ["--yt-dlp-worker"]:
    from yt_dlp import main as yt_dlp_main

    sys.exit(yt_dlp_main(sys.argv[2:]))

import logging

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from config import APP_ICON_PATH, configure_logging
from database import initialize
from ui.main_window import MainWindow
from ui.theme import build_stylesheet, detect_color_scheme


def main():
    if sys.platform == "win32":
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "GoonerNga.StreamSniper"
        )
        if result != 0:
            raise OSError(result, "Could not set the StreamSniper Windows app identity.")

    configure_logging()
    logging.info("StreamSniper started.")
    initialize()
    app = QApplication(sys.argv)
    app.setApplicationName("StreamSniper")
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    app.setFont(QFont("Segoe UI", 11))

    window = None

    def apply_system_theme(*_):
        scheme = detect_color_scheme(app)
        app.setProperty("streamSniperTheme", scheme)
        app.setStyleSheet(build_stylesheet(scheme))
        if window is not None:
            window.refresh_channels()
            window.render_logs()
            window.render_recent_logs()

    apply_system_theme()
    window = MainWindow()
    app.styleHints().colorSchemeChanged.connect(apply_system_theme)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
