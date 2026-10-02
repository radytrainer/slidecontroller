"""
Microsoft PowerPoint control through COM automation (pywin32).

PowerPoint itself opens and renders the original .pptx - themes, fonts,
animations, transitions, video, audio all stay PowerPoint's job.

Navigation uses the running slide show's own ``View.Next()`` and
``View.Previous()``: exactly what the arrow keys / clicker do. If a slide has
animations, Next plays the next animation step first and only moves to the
next slide when the animations are done - AirSlide never skips them.

All COM calls run on one dedicated thread (see ``ComThread``), so the
controller can be used safely from the GUI thread and the camera thread.
"""

import time
import winreg
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pywintypes
import win32com.client

import config
from src.presentation.base import (
    MSG_INVALID_FILE,
    MSG_POWERPOINT_NOT_FOUND,
    ApplicationNotFoundError,
    PresentationController,
    PresentationOpenError,
)
from src.presentation.pptx_notes import read_pptx_notes
from src.utils import windows
from src.utils.com_thread import ComThread
from src.utils.logger import get_logger
from src.utils.windows import bring_to_foreground

log = get_logger(__name__)

PROG_ID = "PowerPoint.Application"

# Office constants (msoTriState / PpSlideShow*)
MSO_TRUE = -1
MSO_FALSE = 0
PP_SHOW_TYPE_SPEAKER = 1       # full screen, presenter-controlled
PP_SHOW_ALL = 1
PP_SLIDE_SHOW_DONE = 5         # View.State at the "End of slide show" screen

ADVANCE = "Advance"            # _navigate action: next slide, skipping remaining animations
PP_PLACEHOLDER_BODY = 2           # the notes text box on a notes page
NOTES_ATTEMPTS = 5                # asking PowerPoint for the notes (only if the file cannot be read)
NOTES_RETRY_SECONDS = 0.5
SLIDE_SHOW_CLASS = "screenClass"   # window class of the audience slide show (Presenter View: "PodiumParent")

# Seconds to wait for status / navigation calls before giving up, so a busy
# PowerPoint (e.g. a dialog box) can never freeze AirSlide.
STATUS_TIMEOUT = 3.0
NAVIGATION_TIMEOUT = 10.0


RPC_BUSY = {-2147418111, -2147417846}  # RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER


def _is_busy(exc: pywintypes.com_error) -> bool:
    """PowerPoint rejected the call because it is busy (e.g. just starting the show)."""
    return bool(exc.args) and exc.args[0] in RPC_BUSY


def is_powerpoint_installed() -> bool:
    """True when PowerPoint's COM server is registered (does not launch it)."""
    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, PROG_ID).Close()
        return True
    except OSError:
        return False


def powerpoint_version() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{PROG_ID}\CurVer") as key:
            return winreg.QueryValue(key, None)
    except OSError:
        return None


class PowerPointController(PresentationController):
    app_name = "Microsoft PowerPoint"

    def __init__(self, read_only: bool | None = None, close_on_exit: bool | None = None):
        super().__init__()
        self.read_only = config.POWERPOINT_OPEN_READ_ONLY if read_only is None else read_only
        self.close_on_exit = config.POWERPOINT_CLOSE_ON_EXIT if close_on_exit is None else close_on_exit
        self._com: ComThread | None = None
        self._app = None
        self._presentation = None
        self._show_window = None
        self._hwnd: int | None = None     # slide show window (the audience screen)
        self._we_started_powerpoint = False
        self._we_opened_presentation = False

    # -- public API (thread-safe) ----------------------------------------------

    def open(self, file_path) -> None:
        if not is_powerpoint_installed():
            raise ApplicationNotFoundError(MSG_POWERPOINT_NOT_FOUND)
        self.file_path = Path(file_path).resolve()
        if self._com is None:
            self._com = ComThread("powerpoint-com")
        self._com.call(self._open)

    def start(self) -> None:
        self._require_open()
        hwnd = self._com.call(self._start)
        self._hwnd = hwnd
        if hwnd and not bring_to_foreground(hwnd):
            log.warning("Could not bring the slide show to the front")

    def next_slide(self) -> bool:
        return self._navigate("Next")

    def previous_slide(self) -> bool:
        return self._navigate("Previous")

    def advance_slide(self) -> bool:
        return self._navigate(ADVANCE)

    @property
    def is_running(self) -> bool:
        if self._com is None or self._presentation is None:
            return False
        try:
            return self._com.call(self._is_running, timeout=STATUS_TIMEOUT)
        except TimeoutError:
            return True  # PowerPoint is busy (e.g. showing a dialog), not gone

    def position(self) -> tuple[int, int] | None:
        if self._com is None or self._presentation is None:
            return None
        try:
            return self._com.call(self._position, timeout=STATUS_TIMEOUT)
        except TimeoutError:
            return None

    def slide_notes(self) -> dict[int, str]:
        """Read from the .pptx file itself; PowerPoint is only asked if that fails
        (right after the slide show starts it often rejects calls while busy)."""
        if self.file_path is not None:
            try:
                notes = read_pptx_notes(self.file_path)
                log.info("Speaker notes on %d slides (read from the file)", len(notes))
                return notes
            except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
                log.warning("Could not read the notes from the file (%s) - asking PowerPoint", exc)
        for attempt in range(1, NOTES_ATTEMPTS + 1):
            if self._com is None or self._presentation is None:
                return {}
            try:
                return self._com.call(self._slide_notes, timeout=NAVIGATION_TIMEOUT)
            except (TimeoutError, pywintypes.com_error, AttributeError) as exc:
                # Late-bound COM reports a busy PowerPoint as com_error or AttributeError.
                log.info("PowerPoint busy while reading the notes (attempt %d): %s", attempt, exc)
                time.sleep(NOTES_RETRY_SECONDS)
        log.warning("PowerPoint did not return the speaker notes")
        return {}

    def window_handle(self) -> int | None:
        """The full-screen slide show window the audience sees (no COM call).

        With Presenter View, PowerPoint shows two windows: the slides on the
        projector (class "screenClass") and the presenter's own screen
        ("PodiumParent"). The HWND reported through COM is not always the
        audience window, so it is checked by class and searched for if needed."""
        if self._show_window is None:
            return None
        if windows.is_window(self._hwnd) and windows.class_name(self._hwnd) == SLIDE_SHOW_CLASS:
            return self._hwnd
        found = windows.find_windows(SLIDE_SHOW_CLASS)
        if found:
            self._hwnd = found[0]
            return self._hwnd
        return None

    def click_position(self) -> tuple[int, int] | None:
        """(animation clicks done, animation clicks on this slide) - for tests."""
        if self._com is None or self._presentation is None:
            return None
        return self._com.call(self._click_position)

    def close(self) -> None:
        if self._com is None:
            return
        try:
            self._com.call(self._close)
        finally:
            self._com.shutdown()
            self._com = None

    # -- COM-thread implementation -----------------------------------------------

    def _require_open(self) -> None:
        if self._com is None or self._presentation is None:
            raise PresentationOpenError("No presentation is open.")

    def _open(self) -> None:
        try:
            win32com.client.GetActiveObject(PROG_ID)
            was_running = True
        except pywintypes.com_error:
            was_running = False

        try:
            app = win32com.client.Dispatch(PROG_ID)
        except pywintypes.com_error as exc:
            raise ApplicationNotFoundError(MSG_POWERPOINT_NOT_FOUND) from exc
        self._app = app
        self._we_started_powerpoint = not was_running

        existing = self._find_open_presentation(app)
        if existing is not None:
            log.info("Presentation already open in PowerPoint - reusing it")
            self._presentation = existing
            self._we_opened_presentation = False
            return

        log.info("Opening %s in PowerPoint (read-only=%s)", self.file_path.name, self.read_only)
        try:
            self._presentation = app.Presentations.Open(
                str(self.file_path),
                MSO_TRUE if self.read_only else MSO_FALSE,  # ReadOnly
                MSO_FALSE,                                  # Untitled
                MSO_TRUE,                                   # WithWindow
            )
        except pywintypes.com_error as exc:
            log.error("PowerPoint could not open %s: %s", self.file_path, exc)
            self._quit_if_ours()
            raise PresentationOpenError(MSG_INVALID_FILE) from exc
        self._we_opened_presentation = True

    def _find_open_presentation(self, app):
        target = str(self.file_path).lower()
        for index in range(1, app.Presentations.Count + 1):
            presentation = app.Presentations.Item(index)
            if str(presentation.FullName).lower() == target:
                return presentation
        return None

    def _start(self) -> int | None:
        settings = self._presentation.SlideShowSettings
        settings.ShowType = PP_SHOW_TYPE_SPEAKER
        settings.RangeType = PP_SHOW_ALL
        try:
            self._show_window = settings.Run()
        except pywintypes.com_error as exc:
            raise PresentationOpenError(f"PowerPoint could not start the slide show: {exc}") from exc
        log.info("Slide show started (%d slides)", self._presentation.Slides.Count)
        try:
            self._show_window.Activate()
            hwnd = self._show_window.HWND
            # Late-bound COM sometimes exposes this property as a method.
            return int(hwnd() if callable(hwnd) else hwnd)
        except (pywintypes.com_error, TypeError, ValueError):
            return None

    def _navigate(self, action: str) -> bool:
        if self._com is None or self._show_window is None:
            return False

        def run() -> bool:
            try:
                if action == ADVANCE:
                    return self._goto_next_slide()
                getattr(self._show_window.View, action)()
                return True
            except pywintypes.com_error:
                log.info("Slide show is no longer running (%s ignored)", action)
                self._show_window = None
                return False

        try:
            return self._com.call(run, timeout=NAVIGATION_TIMEOUT)
        except TimeoutError:
            log.warning("PowerPoint did not respond to %s", action)
            return False

    def _goto_next_slide(self) -> bool:
        """Jump to the next visible slide (GotoSlide would also show hidden ones)."""
        view = self._show_window.View
        slides = self._presentation.Slides
        index = int(view.Slide.SlideIndex) + 1
        while index <= slides.Count and slides.Item(index).SlideShowTransition.Hidden == MSO_TRUE:
            index += 1
        if index > slides.Count:
            view.Next()  # last slide: continue to the end of the show, as the arrow key would
        else:
            view.GotoSlide(index)
        return True

    def _slide_notes(self) -> dict[int, str]:
        """Notes by slide show position (hidden slides are skipped, like CurrentShowPosition)."""
        notes: dict[int, str] = {}
        slides = self._presentation.Slides
        position = 0
        for index in range(1, slides.Count + 1):
            slide = slides.Item(index)
            try:
                if slide.SlideShowTransition.Hidden == MSO_TRUE:
                    continue
                position += 1
                if not slide.HasNotesPage:
                    continue
                placeholders = slide.NotesPage.Shapes.Placeholders
                for k in range(1, placeholders.Count + 1):
                    shape = placeholders.Item(k)
                    if shape.PlaceholderFormat.Type == PP_PLACEHOLDER_BODY and shape.HasTextFrame:
                        text = str(shape.TextFrame.TextRange.Text).strip()
                        if text:
                            notes[position] = text
                        break
            except pywintypes.com_error as exc:
                log.debug("No notes for slide %d: %s", index, exc)
        log.info("Speaker notes on %d of %d slides", len(notes), position)
        return notes

    def _is_running(self) -> bool:
        if self._show_window is None:
            return False
        try:
            _ = self._show_window.View.State  # raises once the show has ended
            return True
        except AttributeError:
            return True  # late-bound COM: PowerPoint busy, not gone
        except pywintypes.com_error as exc:
            if _is_busy(exc):
                return True
            self._show_window = None
            return False

    def _position(self) -> tuple[int, int] | None:
        try:
            total = self._presentation.Slides.Count
            if self._show_window is None:
                return None
            view = self._show_window.View
            if view.State == PP_SLIDE_SHOW_DONE:
                return total + 1, total  # black "end of slide show" screen
            return int(view.CurrentShowPosition), total
        except (pywintypes.com_error, AttributeError):
            return None  # busy or ended: unknown for now (callers keep the last slide)

    def _click_position(self) -> tuple[int, int] | None:
        try:
            view = self._show_window.View
            return int(view.GetClickIndex()), int(view.GetClickCount())
        except (pywintypes.com_error, AttributeError):
            return None

    def _close(self) -> None:
        if self._show_window is not None:
            try:
                self._show_window.View.Exit()
            except pywintypes.com_error:
                pass
            self._show_window = None

        if self._presentation is not None and self._we_opened_presentation and self.close_on_exit:
            try:
                self._presentation.Saved = MSO_TRUE  # never prompt to save; the file is not modified
                self._presentation.Close()
                log.info("Presentation closed")
            except pywintypes.com_error as exc:
                log.warning("Could not close the presentation: %s", exc)
        self._presentation = None
        self._quit_if_ours()
        self._app = None

    def _quit_if_ours(self) -> None:
        """Quit PowerPoint only if AirSlide started it and nothing else is open."""
        if self._app is None or not self._we_started_powerpoint or not self.close_on_exit:
            return
        try:
            if self._app.Presentations.Count == 0:
                self._app.Quit()
                log.info("PowerPoint closed")
        except pywintypes.com_error:
            pass
