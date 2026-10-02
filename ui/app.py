"""Start the AirSlide desktop application."""

import sys

from PySide6.QtWidgets import QApplication

import config
from src.utils import settings
from src.utils.logger import get_logger
from ui.main_window import MainWindow
from ui.theme import STYLESHEET, make_app_icon

log = get_logger(__name__)


def _install_error_handler() -> None:
    """Log unexpected errors and show them instead of silently crashing."""
    from PySide6.QtWidgets import QMessageBox

    def handle(exc_type, exc, tb):
        log.error("Unexpected error", exc_info=(exc_type, exc, tb))
        if QApplication.instance() is not None:
            QMessageBox.critical(None, config.APP_NAME,
                                 f"Something went wrong:\n{exc}\n\nDetails are in logs/airslide.log.")

    sys.excepthook = handle


def run_app(argv: list[str] | None = None) -> int:
    settings.load()
    _install_error_handler()
    if sys.platform == "win32":
        # Own taskbar identity (so Windows shows AirSlide's icon, not Python's).
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AirSlide.App")

    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(make_app_icon())

    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    return app.exec()
