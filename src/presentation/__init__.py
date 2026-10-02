"""AirSlide presentation control package."""

from src.presentation.base import (
    ApplicationNotFoundError,
    PresentationController,
    PresentationError,
    PresentationOpenError,
    UnsupportedFileError,
)
from src.presentation.presentation_manager import (
    FileType,
    PresentationManager,
    PresentationSession,
    SessionState,
    validate_file,
)

__all__ = [
    "ApplicationNotFoundError",
    "FileType",
    "PresentationController",
    "PresentationError",
    "PresentationManager",
    "PresentationOpenError",
    "PresentationSession",
    "SessionState",
    "UnsupportedFileError",
    "validate_file",
]
