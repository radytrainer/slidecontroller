"""
The presentation-controller interface.

The gesture engine only ever calls ``next_slide()`` / ``previous_slide()``;
it never knows whether PowerPoint or a PDF viewer is behind them.
"""

from abc import ABC, abstractmethod
from pathlib import Path

MSG_POWERPOINT_NOT_FOUND = (
    "Microsoft PowerPoint was not found.\n"
    "Please install Microsoft PowerPoint to open PPTX files."
)
MSG_INVALID_FILE = "Unable to open presentation.\nPlease check the file."
MSG_UNSUPPORTED_FILE = "Only PPTX and PDF files are supported."


class PresentationError(RuntimeError):
    """Base class for presentation problems shown to the user."""


class ApplicationNotFoundError(PresentationError):
    """The application needed for this file type is not installed."""


class PresentationOpenError(PresentationError):
    """The file could not be opened or started."""


class UnsupportedFileError(PresentationError):
    """The file type is not supported."""


class PresentationController(ABC):
    """Opens a file in its own application and navigates it."""

    #: Human-readable application name, e.g. "Microsoft PowerPoint".
    app_name: str = "presentation app"

    def __init__(self) -> None:
        self.file_path: Path | None = None

    @abstractmethod
    def open(self, file_path: str | Path) -> None:
        """Open the file in the application (not yet presenting)."""

    @abstractmethod
    def start(self) -> None:
        """Start full-screen presentation mode and bring it to the front."""

    @abstractmethod
    def next_slide(self) -> bool:
        """Advance (next animation step or slide). Returns False if not presenting."""

    @abstractmethod
    def previous_slide(self) -> bool:
        """Go back one step. Returns False if not presenting."""

    def advance_slide(self) -> bool:
        """Go to the next slide, skipping animation steps still left on this one
        (used by the debate timer). Without animations this is the same as Next."""
        return self.next_slide()

    @abstractmethod
    def close(self) -> None:
        """Leave presentation mode and clean up what this controller opened."""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """True while the presentation is being shown."""

    def slide_notes(self) -> dict[int, str]:
        """{slide number: speaker notes} for slides that have notes (slide numbers
        as position() reports them). Empty when the format has no notes (PDF)."""
        return {}

    def window_handle(self) -> int | None:
        """Handle (HWND) of the window showing the slides, when known."""
        return None

    def position(self) -> tuple[int, int] | None:
        """(current slide/page, total) when the application can report it."""
        return None
