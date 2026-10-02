"""
GUI workflow tests, run offscreen (no window appears) with a fake
presentation app and a fake gesture engine.
"""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

import config
from src.engine.gesture_engine import CommandResult, EngineUpdate
from src.gesture.gesture_state import GestureState, GestureStatus
from src.gesture.swipe_detector import Direction, Gesture
from src.presentation.presentation_manager import FileType, PresentationManager, SessionState
from tests.test_presentation_manager import FakeController


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def dispose(app, window):
    """Delete a window through Qt now, instead of leaving it to Python's garbage
    collector at interpreter exit (which can crash with heap corruption)."""
    window.overlay.hide()
    window.close()
    window.overlay.deleteLater()
    window.slide_timer.deleteLater()
    window.alert.deleteLater()
    window.subtitle_window.deleteLater()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


def wait_until(app, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


class FakeEngine:
    """Stands in for GestureEngine; ``fail`` simulates a missing camera."""

    instances: list["FakeEngine"] = []
    fail: str | None = None

    def __init__(self, command_handler, on_ready, on_update, on_command, on_error, want_frames):
        self.command_handler, self.on_ready, self.on_error = command_handler, on_ready, on_error
        self.on_update, self.on_command = on_update, on_command
        self.paused = False
        self.running = False
        self.reloaded = False
        FakeEngine.instances.append(self)

    def start(self):
        self.running = True
        if FakeEngine.fail:
            self.on_error(FakeEngine.fail)
        else:
            self.on_ready()

    def stop(self):
        self.running = False

    def reload_settings(self):
        self.reloaded = True


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    from ui.main_window import MainWindow

    FakeEngine.instances.clear()
    FakeEngine.fail = None
    controllers = {FileType.PPTX: FakeController("Microsoft PowerPoint"), FileType.PDF: FakeController("PDF viewer")}
    manager = PresentationManager({t: (lambda c=c: c) for t, c in controllers.items()})
    win = MainWindow(manager=manager, engine_factory=FakeEngine, run_checks=False)
    win.errors = []
    monkeypatch.setattr(win, "show_error", win.errors.append)
    win.controllers = controllers
    win.show()
    yield win
    dispose(app, win)


@pytest.fixture
def pptx(tmp_path):
    path = tmp_path / "talk.pptx"
    path.write_bytes(b"PK\x03\x04" + b"\0" * 64)
    return path


def start(window, app, path):
    window.load_file(str(path))
    assert wait_until(app, lambda: window.pages.currentWidget() is window.presenting), window.errors


def test_home_screen_content(window):
    assert window.pages.currentWidget() is window.home
    assert "Open Presentation" in window.open_button.text()
    assert window.env_status.text("Presentation") == "None selected"


def test_full_workflow_open_present_gesture_stop(window, app, pptx):
    start(window, app, pptx)
    manager = window.manager
    assert manager.session.presentation_status == SessionState.PRESENTING
    assert window.overlay.isVisible() == config.SHOW_OVERLAY
    assert window.file_label.text() == "talk.pptx"

    # the engine thread calls the handler -> PowerPoint controller moves
    engine = FakeEngine.instances[-1]
    assert engine.command_handler(Gesture.NEXT) is True
    assert engine.command_handler(Gesture.NEXT) is True
    assert engine.command_handler(Gesture.PREVIOUS) is True
    assert window.controllers[FileType.PPTX].slide == 2

    window._on_command(CommandResult(Gesture.NEXT, Direction.RIGHT_TO_LEFT, 240, True, 0))
    assert window.history.count() == 1
    assert window.live_status.text("Gesture") == "NEXT"

    window.stop_presentation()
    assert wait_until(app, lambda: window.pages.currentWidget() is window.home)
    assert manager.session.presentation_status == SessionState.CLOSED
    assert not engine.running
    assert not window.overlay.isVisible()


def test_unsupported_file_shows_spec_message(window, tmp_path):
    path = tmp_path / "notes.docx"
    path.write_bytes(b"PK\x03\x04")
    window.load_file(str(path))
    assert window.errors == ["Only PPTX and PDF files are supported."]
    assert window.pages.currentWidget() is window.home


def test_invalid_file_shows_spec_message(window, tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf")
    window.load_file(str(path))
    assert window.errors == ["Unable to open presentation.\nPlease check the file."]


def test_powerpoint_not_installed_shows_spec_message(app, monkeypatch, pptx):
    from src.presentation.base import MSG_POWERPOINT_NOT_FOUND, ApplicationNotFoundError
    from ui.main_window import MainWindow

    failing = FakeController(open_error=ApplicationNotFoundError(MSG_POWERPOINT_NOT_FOUND))
    win = MainWindow(manager=PresentationManager({FileType.PPTX: lambda: failing}),
                     engine_factory=FakeEngine, run_checks=False)
    errors = []
    monkeypatch.setattr(win, "show_error", errors.append)
    win.load_file(str(pptx))
    assert wait_until(app, lambda: errors)
    assert errors == [MSG_POWERPOINT_NOT_FOUND]
    assert win.pages.currentWidget() is win.home
    dispose(app, win)


def test_camera_missing_stops_before_presenting(window, app, pptx):
    FakeEngine.fail = "Camera not found. Please connect a webcam."
    window.load_file(str(pptx))
    assert wait_until(app, lambda: window.errors)
    assert window.errors == ["Camera not found. Please connect a webcam."]
    assert window.pages.currentWidget() is window.home
    assert window.manager.controller is None  # the presentation was closed again


def test_camera_lost_while_presenting_keeps_presentation(window, app, pptx):
    start(window, app, pptx)
    window._on_engine_error("Camera stopped responding. Please check the webcam connection.")
    assert window.manager.session.presentation_status == SessionState.PRESENTING
    assert "stopped responding" in window.live_status.text("Status")
    assert window.errors == []


def test_presenter_ending_show_returns_home(window, app, pptx):
    start(window, app, pptx)
    window.controllers[FileType.PPTX].running = False  # Esc in PowerPoint
    window._check_still_presenting()
    assert wait_until(app, lambda: window.pages.currentWidget() is window.home)


def test_pause_blocks_navigation(window, app, pptx):
    start(window, app, pptx)
    window.toggle_pause()
    assert FakeEngine.instances[-1].paused
    assert window.manager.next_slide() is False
    window.toggle_pause()
    assert window.manager.next_slide() is True


def test_live_status_updates(window, app, pptx):
    start(window, app, pptx)
    window.showNormal()
    status = GestureStatus(GestureState.IDLE, "Please use one hand.", hand_count=2)
    window._on_engine_update(EngineUpdate(status, 30.0, False))
    assert window.live_status.text("Hand") == "2 hands"
    assert window.live_status.text("Status") == "Please use one hand."


def test_overlay_toggle(window, app, pptx):
    start(window, app, pptx)
    before = config.SHOW_OVERLAY
    try:
        window.toggle_overlay()
        assert window.overlay.isVisible() == (not before)
    finally:
        config.SHOW_OVERLAY = before


# -- debate mode -------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def debate(window, monkeypatch):
    """Debate mode on (without writing the user's settings file), with a fake clock."""
    from src.utils import settings

    monkeypatch.setattr(settings, "save", lambda *args, **kwargs: None)
    before = settings.current_values()
    window.debate_radio.setChecked(True)
    window.timing_combo.setCurrentIndex(window.timing_combo.findData("per slide"))
    window.slide_seconds.setValue(30)
    window.clock = Clock()
    yield window.clock
    settings.apply(before)


def test_mode_card_updates_config(window, debate):
    assert config.DEBATE_MODE is True
    assert config.DEBATE_TIMING == "per slide"
    assert config.DEBATE_SLIDE_SECONDS == 30
    assert not window.debate_options.isHidden()
    assert not window.slide_seconds.isHidden() and window.total_time.isHidden()

    window.timing_combo.setCurrentIndex(window.timing_combo.findData("total"))
    window.total_time.set_seconds(450)
    assert config.DEBATE_TIMING == "total" and config.DEBATE_TOTAL_SECONDS == 450
    assert window.slide_seconds.isHidden() and not window.total_time.isHidden()

    window.normal_radio.setChecked(True)
    assert config.DEBATE_MODE is False
    assert window.debate_options.isHidden()


def _real_pptx(path, slides):
    import zipfile

    with zipfile.ZipFile(path, "w") as package:
        for number in range(1, slides + 1):
            package.writestr(f"ppt/slides/slide{number}.xml", "<p:sld><p:cSld/></p:sld>")
    return path


def test_debate_total_time_is_divided_between_slides(window, app, tmp_path, debate, monkeypatch):
    monkeypatch.setattr(window, "_ask_slide_times", lambda *args: pytest.fail("no dialog expected"))
    window.timing_combo.setCurrentIndex(window.timing_combo.findData("total"))
    window.total_time.set_seconds(100)
    pptx = _real_pptx(tmp_path / "debate.pptx", 3)
    controller = window.controllers[FileType.PPTX]
    controller.total = 3
    start(window, app, pptx)
    window._debate_tick()
    assert window.timer_label.text() == "⏱ 0:34  ·  1/3"    # 100 s = 34 + 33 + 33
    debate.now += 34
    window._debate_tick()
    assert wait_until(app, lambda: controller.slide == 2 and not window._advancing)
    window._debate_tick()
    assert window.timer_label.text() == "⏱ 0:33  ·  2/3"


def test_debate_total_time_unknown_slide_count_asks(window, app, pptx, debate, monkeypatch):
    asked = []
    monkeypatch.setattr(window, "_ask_slide_times", lambda path, count, previous: asked.append(count) or {1: 50, 2: 50})
    window.timing_combo.setCurrentIndex(window.timing_combo.findData("total"))
    start(window, app, pptx)                    # the fake .pptx cannot be counted
    assert asked == [None]
    assert window._slide_total == 2


def test_normal_mode_has_no_timer(window, app, pptx):
    config.DEBATE_MODE = False
    window._load_mode_controls()
    start(window, app, pptx)
    assert window._debate is None
    assert window.timer_button.isHidden()


def test_debate_mode_advances_on_time_and_follows_swipes(window, app, pptx, debate):
    controller = window.controllers[FileType.PPTX]
    controller.total = 3
    start(window, app, pptx)
    assert not window.timer_button.isHidden()

    window._debate_tick()
    assert window.timer_label.text() == "⏱ 0:30  ·  1/3"
    debate.now += 29
    window._debate_tick()
    assert controller.slide == 1

    debate.now += 1
    window._debate_tick()                       # time is up -> next slide
    assert wait_until(app, lambda: controller.slide == 2 and not window._advancing)
    assert "TIME UP" in window.history.item(0).text()

    debate.now += 10
    FakeEngine.instances[-1].command_handler(Gesture.NEXT)  # presenter swipes to slide 3
    window._debate_tick()
    assert window.timer_label.text() == "⏱ 0:30  ·  3/3"   # full time for the new slide

    debate.now += 30
    window._debate_tick()                       # last slide: stays, shows TIME UP
    assert controller.slide == 3
    assert window.timer_label.text().startswith("⏱ TIME UP")

    window.stop_presentation()
    assert wait_until(app, lambda: window.pages.currentWidget() is window.home)
    assert window._debate is None and not window._debate_timer.isActive()


def test_debate_timer_shown_on_the_slide(window, app, pptx, debate):
    controller = window.controllers[FileType.PPTX]
    controller.total = 3
    start(window, app, pptx)
    assert window.slide_timer.isVisible()
    window._debate_tick()
    assert window.slide_timer.time_label.text() == "⏱ 0:30"
    assert window.slide_timer.slide_label.text() == "1/3"
    window.stop_presentation()
    assert wait_until(app, lambda: window.pages.currentWidget() is window.home)
    assert not window.slide_timer.isVisible()


def test_debate_timer_on_slide_can_be_turned_off(window, app, pptx, debate):
    config.DEBATE_TIMER_ON_SLIDE = False     # restored by the debate fixture
    start(window, app, pptx)
    assert not window.slide_timer.isVisible()
    assert not window.timer_label.isHidden()  # the countdown is still in AirSlide's window


def test_normal_mode_has_no_slide_timer(window, app, pptx):
    config.DEBATE_MODE = False
    window._load_mode_controls()
    start(window, app, pptx)
    assert not window.slide_timer.isVisible()


def test_slide_timer_sits_bottom_right_of_the_slide_show(app, monkeypatch):
    from src.utils import windows
    from ui import slide_timer as module

    timer = module.SlideTimerWindow()
    timer.show()
    moves = []
    own = (0, 0, 200, 90)
    rects = {1: (1920, 0, 3840, 1080), 2: (3530, 900, 3810, 1060), int(timer.winId()): own}
    monkeypatch.setattr(module.QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setattr(windows, "window_rect", lambda hwnd: rects.get(hwnd))
    monkeypatch.setattr(windows, "presentation_area", lambda: (0, 0, 1920, 1040))
    monkeypatch.setattr(windows, "move_topmost", lambda hwnd, x, y: moves.append((x, y)))
    margin = config.DEBATE_TIMER_MARGIN

    timer.place(1)                           # slide show on the second screen
    assert moves[-1] == (3840 - margin - 200, 1080 - margin - 90)
    timer.place(1)
    assert len(moves) == 1                   # not moved again when nothing changed

    timer.place(1, avoid_hwnd=2)             # the overlay is in that corner: go above it
    assert moves[-1] == (3840 - margin - 200, 900 - module.GAP - 90)

    timer.place(None)                        # slide window unknown: presentation_area()
    assert moves[-1] == (1920 - margin - 200, 1040 - margin - 90)
    timer.hide()
    timer.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_powerpoint_timer_goes_on_audience_window_not_presenter_view(monkeypatch):
    """With Presenter View the COM HWND can be the presenter's window; the timer
    must go on the slide show the audience sees (class screenClass)."""
    pytest.importorskip("win32com")
    from src.presentation import powerpoint_controller as ppt
    from src.utils import windows

    classes = {10: "PodiumParent", 20: "screenClass", 30: "screenClass"}
    monkeypatch.setattr(windows, "is_window", lambda hwnd: hwnd in classes)
    monkeypatch.setattr(windows, "class_name", lambda hwnd: classes.get(hwnd, ""))
    monkeypatch.setattr(windows, "find_windows",
                        lambda cls: [h for h in (20, 30) if classes.get(h) == cls])  # biggest first

    controller = ppt.PowerPointController()
    assert controller.window_handle() is None          # not presenting
    controller._show_window = object()
    controller._hwnd = 10                               # COM gave the Presenter View window
    assert controller.window_handle() == 20
    assert controller.window_handle() == 20             # kept while it is valid
    del classes[20]                                     # slide show window closed/recreated
    assert controller.window_handle() == 30


def test_presentation_area_prefers_the_projector(monkeypatch):
    pytest.importorskip("win32api")
    from src.utils import windows

    laptop = {"Monitor": (0, 0, 1920, 1080), "Work": (0, 0, 1920, 1032), "Flags": 1}
    projector = {"Monitor": (1920, 0, 3840, 1080), "Work": (1920, 0, 3840, 1080), "Flags": 0}
    monitors = {"laptop": laptop, "projector": projector}
    monkeypatch.setattr(windows.win32api, "EnumDisplayMonitors", lambda: [(m, None, None) for m in monitors])
    monkeypatch.setattr(windows.win32api, "GetMonitorInfo", lambda m: monitors[m])
    monkeypatch.setattr(windows.win32api, "MonitorFromPoint", lambda *args: "laptop")
    assert windows.presentation_area() == (1920, 0, 3840, 1080)
    del monitors["projector"]
    assert windows.presentation_area() == (0, 0, 1920, 1032)  # one screen: above the taskbar


# -- photo slideshow ------------------------------------------------------------------------

def _photos(tmp_path, count=3):
    from PySide6.QtGui import QImage

    paths = []
    for n in range(1, count + 1):
        image = QImage(64, 36, QImage.Format_RGB32)
        image.fill(0x336699 * n)
        path = tmp_path / f"photo_{n}.png"
        image.save(str(path))
        paths.append(path)
    return paths


@pytest.fixture
def photo_window(window, monkeypatch):
    from src.utils import settings

    monkeypatch.setattr(settings, "save", lambda *args, **kwargs: None)
    before = settings.current_values()
    photos_controller = FakeController("AirSlide photo slideshow")
    window.manager._factories[FileType.PHOTOS] = lambda: photos_controller
    window.controllers[FileType.PHOTOS] = photos_controller
    window.asked_photos = []

    def ask(photos, skipped):
        window.asked_photos.append((len(photos), skipped))
        return {"PHOTO_STYLE": "kenburns", "PHOTO_ORDER": "name", "PHOTO_FILL": False}

    monkeypatch.setattr(window, "_ask_photo_options", ask)
    yield window
    settings.apply(before)


def test_photo_slideshow_workflow(photo_window, app, tmp_path):
    window = photo_window
    photos = _photos(tmp_path)
    notes = tmp_path / "readme.txt"
    notes.write_text("not a photo")
    window.load_paths([str(p) for p in reversed(photos)])
    assert wait_until(app, lambda: window.pages.currentWidget() is window.presenting), window.errors
    assert window.asked_photos == [(3, 0)]
    assert config.PHOTO_STYLE == "kenburns"                   # the chosen style is kept
    controller = window.controllers[FileType.PHOTOS]
    assert [p.name for p in controller.file_path] == ["photo_1.png", "photo_2.png", "photo_3.png"]  # by name
    assert window.file_label.text() == "3 photos"
    assert FakeEngine.instances[-1].command_handler(Gesture.NEXT) is True
    assert controller.slide == 2


def test_mixed_selection_is_refused(photo_window, tmp_path, pptx):
    photos = _photos(tmp_path, 1)
    photo_window.load_paths([str(pptx), str(photos[0])])
    assert photo_window.errors == ["Choose one PowerPoint or PDF file, or one or more photos."]


def test_setup_cancelled_opens_nothing(photo_window, monkeypatch, tmp_path):
    monkeypatch.setattr(photo_window, "_ask_photo_options", lambda photos, skipped: None)
    photo_window.load_paths([str(p) for p in _photos(tmp_path)])
    assert photo_window.manager.controller is None
    assert photo_window.pages.currentWidget() is photo_window.home


def test_photos_in_debate_mode_use_the_number_of_photos(photo_window, app, tmp_path, debate):
    window = photo_window
    window.timing_combo.setCurrentIndex(window.timing_combo.findData("total"))
    window.total_time.set_seconds(90)
    window.load_paths([str(p) for p in _photos(tmp_path)])
    assert wait_until(app, lambda: window.pages.currentWidget() is window.presenting), window.errors
    assert [window._debate_plan.seconds_for(n) for n in (1, 2, 3)] == [30, 30, 30]


# -- subtitles --------------------------------------------------------------------------

class FakeMicrophone:
    """Stands in for the Qt microphone; tests call ``speak`` / ``silence``."""

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class Signals(QObject):
            level = Signal(float, float)
            error = Signal(str)

        self._signals = Signals()
        self.level, self.error = self._signals.level, self._signals.error
        self.running = False
        self.fail: str | None = None

    def start(self):
        if self.fail:
            self.error.emit(self.fail)
            return False
        self.running = True
        return True

    def stop(self):
        self.running = False

    def deleteLater(self):
        self._signals.deleteLater()

    def _feed(self, level, seconds):
        for _ in range(round(seconds / 0.02)):
            self.level.emit(level, 0.02)

    def speak(self, seconds):
        self._feed(0.2, seconds)

    def silence(self, seconds):
        self._feed(0.002, seconds)


@pytest.fixture
def subtitles(window, monkeypatch):
    from src.utils import settings

    monkeypatch.setattr(settings, "save", lambda *args, **kwargs: None)
    before = settings.current_values()
    settings.apply({"SUBTITLE_WORDS_PER_MINUTE": 120, "DEBATE_MODE": False, "TIME_LIMIT_ENABLED": False})
    window._load_mode_controls()
    window.subtitles_check.setChecked(True)
    mic = FakeMicrophone()
    window._microphone_factory = lambda: mic
    yield mic
    settings.apply(before)


def test_subtitles_show_notes_sentence_by_sentence_while_speaking(window, app, pptx, subtitles):
    controller = window.controllers[FileType.PPTX]
    controller.total = 3
    controller.notes = {1: "Welcome everyone. Today we build gesture apps.", 3: "Thank you."}
    start(window, app, pptx)
    assert wait_until(app, lambda: subtitles.running)

    subtitles.silence(1.0)
    assert not window.subtitle_window.isVisible()          # nothing until the presenter speaks
    subtitles.speak(0.5)
    assert window.subtitle_window.isVisible()
    assert window.subtitle_window.label.text() == "Welcome everyone."
    subtitles.speak(0.8)                                    # 2 words at 120/min = 1.2 s minimum
    subtitles.silence(0.6)                                  # pause after the sentence
    subtitles.speak(0.3)
    assert window.subtitle_window.label.text() == "Today we build gesture apps."
    subtitles.silence(3.5)                                  # pause is noticed ~0.6 s after the voice fades
    assert not window.subtitle_window.isVisible()           # quiet: hidden

    controller.slide = 2                                    # a slide without notes
    window._subtitle_tick()
    subtitles.speak(2.0)
    assert not window.subtitle_window.isVisible()
    assert window.live_status.text("Subtitles") == "Listening · no notes on this slide"

    controller.slide = 3
    window._subtitle_tick()
    subtitles.speak(0.3)
    assert window.subtitle_window.label.text() == "Thank you."

    window.stop_presentation()
    assert wait_until(app, lambda: window.pages.currentWidget() is window.home)
    assert not subtitles.running and not window.subtitle_window.isVisible()


def test_subtitles_keep_their_place_when_powerpoint_is_busy(window, app, pptx, subtitles):
    controller = window.controllers[FileType.PPTX]
    controller.total = 2
    controller.notes = {1: "First sentence here. Second sentence here."}
    start(window, app, pptx)
    assert wait_until(app, lambda: subtitles.running)
    subtitles.speak(1.5)
    subtitles.silence(0.8)
    subtitles.speak(0.3)
    assert window.subtitle_window.label.text() == "Second sentence here."
    controller.total = None                       # position() unknown for a moment (busy)
    window._subtitle_tick()
    controller.total = 2
    window._subtitle_tick()
    subtitles.speak(0.2)
    assert window.subtitle_window.label.text() == "Second sentence here."   # not back to the first


def test_subtitles_overlay_shows_the_microphone_state(window, app, pptx, subtitles):
    controller = window.controllers[FileType.PPTX]
    controller.total = 1
    controller.notes = {1: "Hello everyone."}
    start(window, app, pptx)
    assert wait_until(app, lambda: subtitles.running)
    subtitles.silence(0.5)
    window._subtitle_tick()
    quiet = window.overlay.voice_label.text()
    assert quiet.endswith("Listening · sentence 1/1")
    assert quiet.count("▮") <= 1                  # room noise: at most one bar
    subtitles.speak(0.3)
    window._subtitle_tick()
    assert window.overlay.voice_label.text() == "🎤 ▮▮▮▮▮  Speaking · sentence 1/1"


def test_quiet_laptop_microphone_counts_as_speaking(window, app, pptx, subtitles):
    """A presenter a few metres from a laptop microphone: room ~0.001, voice ~0.006."""
    controller = window.controllers[FileType.PPTX]
    controller.total = 1
    controller.notes = {1: "Hello everyone."}
    start(window, app, pptx)
    assert wait_until(app, lambda: subtitles.running)
    subtitles._feed(0.001, 1.0)
    subtitles._feed(0.006, 0.4)
    assert window.subtitle_window.label.text() == "Hello everyone."


def test_microphone_choice_is_saved(window, subtitles):
    window.mic_combo.addItem("🎤 Headset", "Headset")
    window.mic_combo.setCurrentIndex(window.mic_combo.findData("Headset"))
    assert config.SUBTITLE_MICROPHONE == "Headset"
    window.mic_combo.setCurrentIndex(0)
    assert config.SUBTITLE_MICROPHONE == "auto"


def test_subtitles_without_notes_do_not_use_the_microphone(window, app, pptx, subtitles):
    start(window, app, pptx)
    assert wait_until(app, lambda: window.live_status.text("Subtitles") == "No speaker notes in this file")
    assert not subtitles.running


def test_subtitles_missing_microphone(window, app, pptx, subtitles):
    window.controllers[FileType.PPTX].notes = {1: "Hello."}
    subtitles.fail = "No microphone found - subtitles are off."
    start(window, app, pptx)
    assert wait_until(app, lambda: window.live_status.text("Subtitles") == subtitles.fail)
    assert window.manager.session.presentation_status == SessionState.PRESENTING


def test_subtitles_off_by_default(window, app, pptx):
    config.SUBTITLES_ENABLED = False
    window._load_mode_controls()
    start(window, app, pptx)
    assert window.live_status.text("Subtitles") == "Off"
    assert window.microphone is None


# -- time limit (normal mode) -----------------------------------------------------------

@pytest.fixture
def limited(window, monkeypatch):
    """Normal mode with a 20 minute limit, a fake clock and no sounds."""
    from src.utils import settings

    monkeypatch.setattr(settings, "save", lambda *args, **kwargs: None)
    monkeypatch.setattr(window, "_beep", lambda stop: None)
    before = settings.current_values()
    settings.apply({"OVERTIME_WARNING_1_SECONDS": 120, "OVERTIME_WARNING_2_SECONDS": 180,
                    "OVERTIME_STOP_SECONDS": 300})
    window._load_mode_controls()
    window.normal_radio.setChecked(True)
    window.time_limit_check.setChecked(True)
    window.limit_time.set_seconds(20 * 60)
    window.clock = Clock()
    yield window.clock
    settings.apply(before)


def test_time_limit_controls(window, limited):
    assert config.TIME_LIMIT_ENABLED is True and config.TIME_LIMIT_SECONDS == 1200
    assert not window.normal_options.isHidden() and window.debate_options.isHidden()
    assert window.limit_hint.text() == "warnings at +2 min and +3 min over  ·  ends at +5 min over"
    window.debate_radio.setChecked(True)
    assert window.normal_options.isHidden()


def test_time_limit_warns_twice_then_ends_the_presentation(window, app, pptx, limited):
    controller = window.controllers[FileType.PPTX]
    start(window, app, pptx)
    assert window._limit is not None and window._debate is None
    assert window.slide_timer.isVisible()
    window._timer_tick()
    assert window.slide_timer.time_label.text() == "⏱ 20:00"

    limited.now += 20 * 60 + 30                  # 30 s over: red, no alert yet
    window._timer_tick()
    assert window.slide_timer.time_label.text() == "+0:30"
    assert window.slide_timer.slide_label.text() == "over time"
    assert not window.alert.isVisible()

    limited.now += 90                            # +2 min: first warning
    window._timer_tick()
    assert window.alert.isVisible()
    assert window.alert.label.text().startswith("⚠  2 min over time  (1/3)")

    limited.now += 60                            # +3 min: second warning
    window._timer_tick()
    assert window.alert.label.text().startswith("⚠  3 min over time  (2/3)")
    assert window.manager.session.presentation_status == SessionState.PRESENTING

    limited.now += 120                           # +5 min: the presentation is ended
    window._timer_tick()
    assert window.alert.label.text().startswith("⏹  5 min over time")
    assert wait_until(app, lambda: window.pages.currentWidget() is window.home)
    assert not controller.running
    assert "ended automatically: 5 min over the 20 min limit" in window.home_message.text()
    assert window._limit is None and not window.slide_timer.isVisible()


def test_time_limit_pause(window, app, pptx, limited):
    start(window, app, pptx)
    window.toggle_timer()
    limited.now += 60 * 60
    window._timer_tick()
    assert window.manager.session.presentation_status == SessionState.PRESENTING
    assert "⏸" in window.slide_timer.time_label.text()


def test_no_time_limit_by_default(window, app, pptx):
    config.DEBATE_MODE = config.TIME_LIMIT_ENABLED = False
    window._load_mode_controls()
    start(window, app, pptx)
    assert window._limit is None and window.timer_button.isHidden()


def test_debate_timer_pause(window, app, pptx, debate):
    controller = window.controllers[FileType.PPTX]
    controller.total = 3
    start(window, app, pptx)
    window.toggle_timer()
    debate.now += 100
    window._debate_tick()
    assert controller.slide == 1
    assert "⏸" in window.timer_label.text()
    window.toggle_timer()
    debate.now += 30
    window._debate_tick()
    assert wait_until(app, lambda: controller.slide == 2)


def test_debate_keeps_running_while_gestures_paused(window, app, pptx, debate):
    controller = window.controllers[FileType.PPTX]
    controller.total = 3
    start(window, app, pptx)
    window.toggle_pause()
    debate.now += 30
    window._debate_tick()
    assert wait_until(app, lambda: controller.slide == 2)


def test_debate_per_slide_times(window, app, pptx, debate, monkeypatch):
    asked = []

    def ask(path, count, previous):
        asked.append(count)
        return {1: 10, 2: 45, 3: 20}

    monkeypatch.setattr(window, "_ask_slide_times", ask)
    window.per_slide_check.setChecked(True)
    controller = window.controllers[FileType.PPTX]
    controller.total = 3
    start(window, app, pptx)
    assert asked == [None]                      # the fake .pptx cannot be counted
    window._debate_tick()
    assert window.timer_label.text() == "⏱ 0:10  ·  1/3"
    debate.now += 10
    window._debate_tick()
    assert wait_until(app, lambda: controller.slide == 2 and not window._advancing)
    window._debate_tick()
    assert window.timer_label.text() == "⏱ 0:45  ·  2/3"


def test_debate_cancelled_slide_times_does_not_open(window, app, pptx, debate, monkeypatch):
    monkeypatch.setattr(window, "_ask_slide_times", lambda *args: None)
    window.per_slide_check.setChecked(True)
    window.load_file(str(pptx))
    assert window.manager.controller is None
    assert window.pages.currentWidget() is window.home
    assert window.errors == []


def test_debate_without_slide_position_counts_itself(window, app, tmp_path, debate):
    pdf = tmp_path / "handout.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"\0" * 64)   # no countable pages, viewer reports nothing
    controller = window.controllers[FileType.PDF]
    start(window, app, pdf)
    debate.now += 30
    window._debate_tick()
    assert wait_until(app, lambda: controller.slide == 2 and not window._advancing)
    assert window._debate.slide == 2
    window._on_command(CommandResult(Gesture.PREVIOUS, Direction.LEFT_TO_RIGHT, 240, True, 0))
    assert window._debate.slide == 1           # a swipe restarts the timer on the new slide


def test_settings_window_round_trip(app):
    from src.utils import settings
    from ui.settings_window import SettingsWindow

    dialog = SettingsWindow()
    values = dialog.values()
    shown = {s.key for s in settings.SETTINGS if s.in_window}
    assert set(values) == shown
    assert values == {k: v for k, v in settings.current_values().items() if k in shown}
    dialog.restore_defaults()
    assert dialog.values() == {k: v for k, v in settings.DEFAULTS.items() if k in shown}


def test_settings_window_shows_small_thresholds(app):
    from ui.settings_window import SettingsWindow

    dialog = SettingsWindow()
    editor = dialog._editors["VOICE_MIN_LEVEL"]
    editor.setValue(0.003)
    assert editor.value() == pytest.approx(0.003)   # not rounded to 0.00
