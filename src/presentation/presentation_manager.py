"""
PresentationManager - one entry point for any supported file.

    manager = PresentationManager()
    manager.open_file("talk.pptx")     # validate + open in PowerPoint
    manager.start_presentation()       # full-screen slide show
    manager.next_slide()               # from the gesture engine
    manager.previous_slide()
    manager.advance_slide()            # from the debate timer
    manager.exit_presentation()

It picks the controller from the file type::

    .pptx -> PowerPointController
    .pdf  -> PDFController

and keeps a ``PresentationSession`` with the current state:

    NO_FILE -> FILE_SELECTED -> LOADING -> PRESENTING <-> PAUSED -> ENDING -> CLOSED

Only files the user selected are opened; they are checked (extension and
file signature) first and never modified.
"""

import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from src.presentation.base import (
    MSG_INVALID_FILE,
    MSG_UNSUPPORTED_FILE,
    PresentationController,
    PresentationError,
    PresentationOpenError,
    UnsupportedFileError,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

MSG_NO_PHOTOS = "None of the selected files is a photo.\nPhotos must be JPG, PNG or GIF files."


class FileType(Enum):
    PPTX = "pptx"
    PDF = "pdf"
    PHOTOS = "photos"   # a photo slideshow (several .jpg / .png / .gif files)


# Every valid file of the type starts with these bytes.
FILE_SIGNATURES = {
    FileType.PPTX: b"PK\x03\x04",   # .pptx is a ZIP package
    FileType.PDF: b"%PDF-",
}
EXTENSIONS = {".pptx": FileType.PPTX, ".pdf": FileType.PDF}


class SessionState(Enum):
    NO_FILE = "No file"
    FILE_SELECTED = "File selected"
    LOADING = "Loading"
    PRESENTING = "Presenting"
    PAUSED = "Paused"
    ENDING = "Ending"
    CLOSED = "Closed"


@dataclass
class PresentationSession:
    selected_file: Path | None = None
    file_type: FileType | None = None
    presentation_status: SessionState = SessionState.NO_FILE
    camera_status: str = "Not started"
    gesture_status: str = "Not started"
    app_name: str = ""
    error: str | None = None
    display_name: str = ""        # shown instead of the file name (e.g. "12 photos")

    @property
    def name(self) -> str:
        return self.display_name or (self.selected_file.name if self.selected_file else "")


def validate_file(file_path: str | Path) -> FileType:
    """Return the file type, or raise UnsupportedFileError / PresentationOpenError."""
    path = Path(file_path)
    file_type = EXTENSIONS.get(path.suffix.lower())
    if file_type is None:
        raise UnsupportedFileError(MSG_UNSUPPORTED_FILE)
    if not path.is_file():
        raise PresentationOpenError(MSG_INVALID_FILE)
    try:
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError as exc:
        raise PresentationOpenError(MSG_INVALID_FILE) from exc
    if not header.startswith(FILE_SIGNATURES[file_type]):
        log.warning("%s does not look like a real %s file", path.name, file_type.value.upper())
        raise PresentationOpenError(MSG_INVALID_FILE)
    return file_type


def _default_factories() -> dict[FileType, Callable[[], PresentationController]]:
    # Imported lazily so the manager (and its tests) do not need pywin32 loaded.
    def powerpoint():
        from src.presentation.powerpoint_controller import PowerPointController
        return PowerPointController()

    def pdf():
        from src.presentation.pdf_controller import PDFController
        return PDFController()

    def photos():
        from src.presentation.photo_controller import PhotoController
        return PhotoController()

    return {FileType.PPTX: powerpoint, FileType.PDF: pdf, FileType.PHOTOS: photos}


class PresentationManager:
    def __init__(self, controller_factories: dict[FileType, Callable[[], PresentationController]] | None = None):
        self._factories = controller_factories or _default_factories()
        self.session = PresentationSession()
        self.controller: PresentationController | None = None
        self._lock = threading.RLock()  # GUI thread and camera thread both call in

    # -- lifecycle ------------------------------------------------------------------

    def open_file(self, file_path: str | Path) -> None:
        """Validate the file and open it in its application (not presenting yet)."""
        with self._lock:
            if self.controller is not None:
                self.exit_presentation()

            path = Path(file_path).resolve()
            file_type = validate_file(path)
            self.session = PresentationSession(path, file_type, SessionState.FILE_SELECTED)
            self._open_controller(file_type, path)

    def open_photos(self, photos: list[str | Path]) -> None:
        """A photo slideshow of these photos, in this order (not presenting yet)."""
        from src.presentation.photos import valid_photos

        with self._lock:
            if self.controller is not None:
                self.exit_presentation()
            valid, skipped = valid_photos(photos)
            if skipped:
                log.warning("Skipped %d files that are not photos: %s", len(skipped),
                            ", ".join(p.name for p in skipped[:5]))
            if not valid:
                raise PresentationOpenError(MSG_NO_PHOTOS)
            name = f"{len(valid)} photo{'s' if len(valid) != 1 else ''}"
            self.session = PresentationSession(valid[0], FileType.PHOTOS, SessionState.FILE_SELECTED,
                                               display_name=name)
            self._open_controller(FileType.PHOTOS, valid)

    def _open_controller(self, file_type: FileType, target) -> None:
        controller = self._factories[file_type]()
        self.session.presentation_status = SessionState.LOADING
        try:
            controller.open(target)
        except PresentationError as exc:
            self._fail(exc)
            raise
        self.controller = controller
        self.session.app_name = controller.app_name
        self.session.presentation_status = SessionState.FILE_SELECTED
        log.info("Opened %s with %s", self.session.name, controller.app_name)

    def start_presentation(self) -> None:
        with self._lock:
            if self.controller is None:
                raise PresentationOpenError("Open a presentation first.")
            self.session.presentation_status = SessionState.LOADING
            try:
                self.controller.start()
            except PresentationError as exc:
                self._fail(exc)
                raise
            self.session.presentation_status = SessionState.PRESENTING
            self.session.error = None

    def pause(self) -> None:
        """Ignore gestures until resume() (e.g. while the presenter talks with their hands)."""
        with self._lock:
            if self.session.presentation_status == SessionState.PRESENTING:
                self.session.presentation_status = SessionState.PAUSED

    def resume(self) -> None:
        with self._lock:
            if self.session.presentation_status == SessionState.PAUSED:
                self.session.presentation_status = SessionState.PRESENTING

    def exit_presentation(self) -> None:
        with self._lock:
            if self.controller is None:
                return
            self.session.presentation_status = SessionState.ENDING
            try:
                self.controller.close()
            except Exception as exc:  # closing must never leave the app stuck
                log.warning("Error while closing the presentation: %s", exc)
            self.controller = None
            self.session.presentation_status = SessionState.CLOSED

    # -- navigation (called by the gesture engine) ---------------------------------------

    def next_slide(self) -> bool:
        return self._navigate("next_slide")

    def previous_slide(self) -> bool:
        return self._navigate("previous_slide")

    def advance_slide(self) -> bool:
        """Debate timer: next slide (skipping animation steps). Also while gestures are paused."""
        return self._navigate("advance_slide", (SessionState.PRESENTING, SessionState.PAUSED))

    def _navigate(self, action: str, allowed: tuple[SessionState, ...] = (SessionState.PRESENTING,)) -> bool:
        with self._lock:
            if self.controller is None or self.session.presentation_status not in allowed:
                return False
            ok = getattr(self.controller, action)()
            if not ok and not self.controller.is_running:
                # The presenter ended the show in the application (e.g. pressed Esc).
                log.info("Presentation is no longer running")
                self.session.presentation_status = SessionState.CLOSED
            return ok

    # -- status -----------------------------------------------------------------------

    @property
    def is_presenting(self) -> bool:
        with self._lock:
            if self.session.presentation_status not in (SessionState.PRESENTING, SessionState.PAUSED):
                return False
            if self.controller is None or not self.controller.is_running:
                self.session.presentation_status = SessionState.CLOSED
                return False
            return True

    def position(self) -> tuple[int, int] | None:
        with self._lock:
            return self.controller.position() if self.controller else None

    def slide_notes(self) -> dict[int, str]:
        """Speaker notes by slide number (for subtitles). Call off the GUI thread.
        Without the lock: it reads the file and must not hold up slide changes."""
        controller = self.controller
        return controller.slide_notes() if controller else {}

    def window_handle(self) -> int | None:
        """The window showing the slides (for the debate timer on the slide).

        Called several times a second from the GUI thread, so it does not wait
        for the lock (a slow slide change holds it); it only reads window handles."""
        controller = self.controller
        return controller.window_handle() if controller else None

    def _fail(self, exc: Exception) -> None:
        self.session.error = str(exc)
        self.session.presentation_status = SessionState.FILE_SELECTED
        log.error("%s", exc)
