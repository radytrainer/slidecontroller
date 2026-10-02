"""PresentationManager tests with fake controllers (no PowerPoint / PDF viewer needed)."""

import pytest

from src.presentation.base import (
    MSG_INVALID_FILE,
    MSG_POWERPOINT_NOT_FOUND,
    MSG_UNSUPPORTED_FILE,
    ApplicationNotFoundError,
    PresentationController,
    PresentationOpenError,
    UnsupportedFileError,
)
from src.presentation.presentation_manager import (
    FileType,
    PresentationManager,
    SessionState,
    validate_file,
)


class FakeController(PresentationController):
    def __init__(self, app_name="Fake", open_error=None):
        super().__init__()
        self.app_name = app_name
        self.open_error = open_error
        self.calls: list[str] = []
        self.running = False
        self.slide = 1
        self.total: int | None = None  # set to report position() like PowerPoint does
        self.notes: dict[int, str] = {}

    def open(self, file_path):
        self.calls.append("open")
        if self.open_error:
            raise self.open_error
        self.file_path = file_path

    def start(self):
        self.calls.append("start")
        self.running = True

    def next_slide(self):
        self.calls.append("next")
        if not self.running:
            return False
        self.slide += 1
        return True

    def previous_slide(self):
        self.calls.append("previous")
        if not self.running:
            return False
        self.slide -= 1
        return True

    def close(self):
        self.calls.append("close")
        self.running = False

    @property
    def is_running(self):
        return self.running

    def position(self):
        return (self.slide, self.total) if self.total else None

    def slide_notes(self):
        return dict(self.notes)


@pytest.fixture
def pptx(tmp_path):
    path = tmp_path / "talk.pptx"
    path.write_bytes(b"PK\x03\x04" + b"\0" * 100)
    return path


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "Handout.PDF"
    path.write_bytes(b"%PDF-1.7\n" + b"\0" * 100)
    return path


@pytest.fixture
def fakes():
    return {FileType.PPTX: FakeController("PowerPoint"), FileType.PDF: FakeController("PDF viewer")}


@pytest.fixture
def manager(fakes):
    return PresentationManager({t: (lambda c=c: c) for t, c in fakes.items()})


# -- file validation ------------------------------------------------------------------

def test_validate_supported_files(pptx, pdf):
    assert validate_file(pptx) == FileType.PPTX
    assert validate_file(pdf) == FileType.PDF  # extension is case-insensitive


@pytest.mark.parametrize("name", ["slides.ppt", "notes.docx", "movie.mp4", "script.exe", "noextension"])
def test_unsupported_extensions(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"data")
    with pytest.raises(UnsupportedFileError, match=MSG_UNSUPPORTED_FILE):
        validate_file(path)


def test_missing_file_is_invalid(tmp_path):
    with pytest.raises(PresentationOpenError, match="Unable to open presentation"):
        validate_file(tmp_path / "gone.pptx")


@pytest.mark.parametrize("name", ["fake.pptx", "fake.pdf"])
def test_renamed_file_with_wrong_content_is_invalid(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"MZ\x90\x00 this is really an exe")
    with pytest.raises(PresentationOpenError, match="Unable to open presentation"):
        validate_file(path)


def test_error_messages_match_spec():
    assert MSG_UNSUPPORTED_FILE == "Only PPTX and PDF files are supported."
    assert MSG_INVALID_FILE == "Unable to open presentation.\nPlease check the file."
    assert MSG_POWERPOINT_NOT_FOUND.startswith("Microsoft PowerPoint was not found.")


# -- controller selection ------------------------------------------------------------

def test_pptx_uses_powerpoint_controller(manager, fakes, pptx):
    manager.open_file(pptx)
    assert manager.controller is fakes[FileType.PPTX]
    assert manager.session.file_type == FileType.PPTX
    assert manager.session.app_name == "PowerPoint"


def test_pdf_uses_pdf_controller(manager, fakes, pdf):
    manager.open_file(pdf)
    assert manager.controller is fakes[FileType.PDF]
    assert manager.session.file_type == FileType.PDF


# -- session states ------------------------------------------------------------------

def test_full_session_lifecycle(manager, fakes, pptx):
    assert manager.session.presentation_status == SessionState.NO_FILE
    manager.open_file(pptx)
    assert manager.session.presentation_status == SessionState.FILE_SELECTED
    assert manager.session.selected_file == pptx.resolve()

    manager.start_presentation()
    assert manager.session.presentation_status == SessionState.PRESENTING
    assert manager.is_presenting

    assert manager.next_slide() and manager.next_slide() and manager.previous_slide()
    assert fakes[FileType.PPTX].slide == 2

    manager.exit_presentation()
    assert manager.session.presentation_status == SessionState.CLOSED
    assert fakes[FileType.PPTX].calls == ["open", "start", "next", "next", "previous", "close"]
    assert not manager.is_presenting


def test_navigation_ignored_before_start(manager, fakes, pptx):
    manager.open_file(pptx)
    assert manager.next_slide() is False
    assert "next" not in fakes[FileType.PPTX].calls


def test_navigation_without_file(manager):
    assert manager.next_slide() is False
    with pytest.raises(PresentationOpenError):
        manager.start_presentation()


def test_pause_ignores_gestures(manager, fakes, pptx):
    manager.open_file(pptx)
    manager.start_presentation()
    manager.pause()
    assert manager.session.presentation_status == SessionState.PAUSED
    assert manager.next_slide() is False
    manager.resume()
    assert manager.next_slide() is True


def test_debate_advance_works_while_gestures_are_paused(manager, fakes, pptx):
    manager.open_file(pptx)
    assert manager.advance_slide() is False  # not presenting yet
    manager.start_presentation()
    manager.pause()
    assert manager.next_slide() is False     # gestures are paused ...
    assert manager.advance_slide() is True   # ... the debate timer is not
    assert fakes[FileType.PPTX].slide == 2


def test_presenter_ending_show_in_app_is_detected(manager, fakes, pptx):
    manager.open_file(pptx)
    manager.start_presentation()
    fakes[FileType.PPTX].running = False  # presenter pressed Esc in PowerPoint
    assert manager.next_slide() is False
    assert manager.session.presentation_status == SessionState.CLOSED


def test_opening_new_file_closes_previous(manager, fakes, pptx, pdf):
    manager.open_file(pptx)
    manager.start_presentation()
    manager.open_file(pdf)
    assert fakes[FileType.PPTX].calls[-1] == "close"
    assert manager.controller is fakes[FileType.PDF]


# -- errors ---------------------------------------------------------------------------

def test_powerpoint_not_installed(pptx):
    failing = FakeController(open_error=ApplicationNotFoundError(MSG_POWERPOINT_NOT_FOUND))
    manager = PresentationManager({FileType.PPTX: lambda: failing})
    with pytest.raises(ApplicationNotFoundError, match="PowerPoint was not found"):
        manager.open_file(pptx)
    assert manager.controller is None
    assert manager.session.error.startswith("Microsoft PowerPoint was not found.")
    assert manager.session.presentation_status == SessionState.FILE_SELECTED


def test_unsupported_file_leaves_session_untouched(manager, tmp_path):
    path = tmp_path / "x.docx"
    path.write_bytes(b"PK\x03\x04")
    with pytest.raises(UnsupportedFileError):
        manager.open_file(path)
    assert manager.session.presentation_status == SessionState.NO_FILE


def test_exit_is_safe_when_nothing_open(manager):
    manager.exit_presentation()
    assert manager.session.presentation_status == SessionState.NO_FILE
