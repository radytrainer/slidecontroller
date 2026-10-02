"""
PDF control through an external PDF viewer.

The viewer renders the original PDF; AirSlide never modifies it. PDF viewers
have no common automation API, so the controller:

1. launches the viewer with the file,
2. finds the viewer's window,
3. brings it to the front and presses the viewer's navigation keys.

Viewers (config.PDF_VIEWER):

* SumatraPDF (recommended) - started with ``-presentation``, so it opens
  directly in full-screen presentation mode; Right/Left change pages.
* The Windows default PDF app - opened like a double-click; PageDown/PageUp
  change pages. Full-screen depends on the app (see config.PDF_VIEWER_KEYS).
* Any other viewer .exe given as a path.
"""

import os
import shutil
import subprocess
import time
import winreg
from pathlib import Path

import config
from src.presentation.base import (
    MSG_INVALID_FILE,
    ApplicationNotFoundError,
    PresentationController,
    PresentationOpenError,
)
from src.presentation.debate import count_slides
from src.utils import windows
from src.utils.logger import get_logger

log = get_logger(__name__)

SUMATRA_ARGS = ["-presentation", "-new-window"]
KEY_PRESS_DELAY = 0.05  # s between focusing the window and pressing a key


def find_sumatra() -> Path | None:
    """Locate SumatraPDF.exe (config path, PATH, or common install folders)."""
    if config.SUMATRA_PATH:
        path = Path(config.SUMATRA_PATH)
        return path if path.is_file() else None
    on_path = shutil.which("SumatraPDF")
    if on_path:
        return Path(on_path)
    for base in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(base)
        if root and (Path(root) / "SumatraPDF" / "SumatraPDF.exe").is_file():
            return Path(root) / "SumatraPDF" / "SumatraPDF.exe"
    return None


def default_pdf_app() -> str | None:
    """ProgId of the user's default .pdf handler (e.g. 'MSEdgePDF'), if any."""
    keys = [
        (winreg.HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice", "ProgId"),
        (winreg.HKEY_CLASSES_ROOT, r".pdf", ""),
    ]
    for hive, sub_key, value_name in keys:
        try:
            with winreg.OpenKey(hive, sub_key) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                if value:
                    return value
        except OSError:
            continue
    return None


class PDFController(PresentationController):
    def __init__(self, viewer: str | None = None):
        super().__init__()
        self.viewer_setting = (viewer or config.PDF_VIEWER).strip()
        self.viewer: str = ""                 # "sumatra", "default" or "custom"
        self.viewer_exe: Path | None = None
        self.keys: dict = {}
        self.app_name = "PDF viewer"
        self._process: subprocess.Popen | None = None
        self._hwnd: int | None = None
        # Viewers do not report the page, so it is counted from the keys pressed
        # (only when the number of pages could be read from the file).
        self._page = 1
        self._pages: int | None = None

    # -- viewer selection ----------------------------------------------------------

    def _choose_viewer(self) -> None:
        setting = self.viewer_setting.lower()
        sumatra = find_sumatra()
        if setting in ("auto", "sumatra"):
            if sumatra:
                self.viewer, self.viewer_exe, self.app_name = "sumatra", sumatra, "SumatraPDF"
            elif setting == "sumatra":
                raise ApplicationNotFoundError(
                    "SumatraPDF was not found.\nInstall it or set PDF_VIEWER = \"default\" in config.py."
                )
            else:
                setting = "default"
        if setting == "default":
            app = default_pdf_app()
            if not app:
                raise ApplicationNotFoundError("No PDF viewer was found.\nPlease install a PDF viewer.")
            self.viewer, self.viewer_exe, self.app_name = "default", None, f"default PDF app ({app})"
        elif not self.viewer:
            exe = Path(self.viewer_setting)
            if not exe.is_file():
                raise ApplicationNotFoundError(f"PDF viewer not found:\n{exe}")
            self.viewer, self.viewer_exe, self.app_name = "custom", exe, exe.stem
        profile = "sumatra" if self.viewer == "sumatra" else "default"
        self.keys = config.PDF_VIEWER_KEYS[profile]

    # -- PresentationController ------------------------------------------------------

    def open(self, file_path) -> None:
        path = Path(file_path).resolve()
        if not path.is_file():
            raise PresentationOpenError(MSG_INVALID_FILE)
        self.file_path = path
        self._choose_viewer()
        self._pages = count_slides(path)
        self._page = 1
        log.info("PDF viewer: %s", self.app_name)

    def start(self) -> None:
        if self.file_path is None:
            raise PresentationOpenError("No PDF is open.")
        existing = {hwnd for hwnd, _ in windows.list_windows()}
        name, stem = self.file_path.name.lower(), self.file_path.stem.lower()

        if self.viewer == "default":
            os.startfile(self.file_path)  # same as double-clicking the file
            pid = None
        else:
            args = [str(self.viewer_exe), *(SUMATRA_ARGS if self.viewer == "sumatra" else []), str(self.file_path)]
            self._process = subprocess.Popen(args)
            pid = self._process.pid

        def is_viewer_window(hwnd: int, title: str) -> bool:
            if pid is not None:
                return windows.window_pid(hwnd) == pid
            return hwnd not in existing and (name in title.lower() or stem in title.lower())

        self._hwnd = windows.wait_for_window(is_viewer_window, config.VIEWER_STARTUP_TIMEOUT)
        if self._hwnd is None and pid is None:
            # The file may already have been open in the viewer: reuse that window.
            self._hwnd = next((h for h, t in windows.list_windows() if name in t.lower() or stem in t.lower()), None)
        if self._hwnd is None:
            raise PresentationOpenError(f"{self.app_name} did not open a window for {self.file_path.name}.")

        log.info("PDF window found: %s", windows.win32gui.GetWindowText(self._hwnd))
        self._focus()
        if self.keys.get("fullscreen"):
            time.sleep(0.5)  # let the viewer finish loading before going full screen
            windows.send_key(self.keys["fullscreen"])

    def next_slide(self) -> bool:
        ok = self._press("next")
        if ok and self._pages is not None:
            self._page = min(self._page + 1, self._pages)
        return ok

    def previous_slide(self) -> bool:
        ok = self._press("previous")
        if ok:
            self._page = max(self._page - 1, 1)
        return ok

    @property
    def is_running(self) -> bool:
        return windows.is_window(self._hwnd)

    def position(self) -> tuple[int, int] | None:
        return (self._page, self._pages) if self._pages is not None and self.is_running else None

    def window_handle(self) -> int | None:
        return self._hwnd

    def close(self) -> None:
        if not self.is_running:
            self._hwnd = None
            return
        if self._process is not None:
            # We launched this viewer process just for the presentation: close it.
            windows.post_close(self._hwnd)
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.warning("PDF viewer did not close within 5 s")
        elif self.keys.get("exit") and self._focus():
            # Shared default viewer (may hold other documents): only leave full screen.
            windows.send_key(self.keys["exit"])
        self._hwnd = None
        self._process = None

    # -- helpers ----------------------------------------------------------------------

    def _focus(self) -> bool:
        if windows.is_foreground(self._hwnd):
            return True
        ok = windows.bring_to_foreground(self._hwnd)
        if not ok:
            log.warning("Could not bring the PDF viewer to the front")
        return ok

    def _press(self, action: str) -> bool:
        if not self.is_running:
            return False
        if not self._focus():
            return False
        time.sleep(KEY_PRESS_DELAY)
        windows.send_key(self.keys[action])
        return True
