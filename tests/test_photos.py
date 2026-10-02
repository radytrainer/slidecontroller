"""Photo slideshow: photo files, the styles, the controller and the setup dialog."""

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import config
from src.presentation.photos import is_photo_path, order_photos, valid_photos

RED, GREEN, BLUE = QColor(220, 30, 30), QColor(30, 200, 60), QColor(40, 60, 220)
# A 1x1 GIF (the classic transparent pixel), to check .gif files are accepted.
TINY_GIF = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_photo(path, color, size=(320, 180)):
    image = QImage(*size, QImage.Format_RGB32)
    image.fill(color)
    assert image.save(str(path))
    return path


@pytest.fixture
def photos(app, tmp_path):
    return [make_photo(tmp_path / "IMG_1.jpg", RED), make_photo(tmp_path / "IMG_2.png", GREEN),
            make_photo(tmp_path / "IMG_10.png", BLUE)]


def pixel(image: QImage, fx: float, fy: float) -> QColor:
    return image.pixelColor(int(image.width() * fx), int(image.height() * fy))


def close_to(color: QColor, expected: QColor, tolerance: int = 40) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(color.getRgb()[:3], expected.getRgb()[:3], strict=True))


def dispose(app, widget):
    widget.hide()
    if hasattr(widget, "shutdown"):
        widget.shutdown()
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


# -- files -------------------------------------------------------------------------------

def test_photo_files(tmp_path, photos):
    gif = tmp_path / "anim.GIF"
    gif.write_bytes(TINY_GIF)
    fake = tmp_path / "virus.jpg"
    fake.write_bytes(b"MZ this is an exe")
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")
    valid, skipped = valid_photos([*photos, gif, fake, notes, photos[0]])   # photos[0] twice
    assert [p.name for p in valid] == ["IMG_1.jpg", "IMG_2.png", "IMG_10.png", "anim.GIF"]
    assert [p.name for p in skipped] == ["virus.jpg", "notes.txt"]
    assert is_photo_path("a.JPEG") and not is_photo_path("a.pptx")


def test_photo_order(photos):
    reversed_selection = list(reversed(photos))
    assert [p.name for p in order_photos(reversed_selection, "name")] == ["IMG_1.jpg", "IMG_2.png", "IMG_10.png"]
    assert order_photos(reversed_selection, "selected") == reversed_selection
    now = time.time()
    for age, path in zip((30, 10, 20), photos, strict=True):
        os.utime(path, (now - age, now - age))
    assert [p.name for p in order_photos(photos, "date")] == ["IMG_1.jpg", "IMG_10.png", "IMG_2.png"]
    shuffled = order_photos(photos, "shuffle", seed=3)
    assert sorted(shuffled) == sorted(photos)
    assert order_photos(photos, "shuffle", seed=3) == shuffled


# -- drawing each style ------------------------------------------------------------------

def view_for(app, photos, style, fill=False):
    from ui.photo_show import PhotoView

    view = PhotoView(photos, style, fill)
    view.resize(320, 180)
    view.show()
    app.processEvents()
    return view


def halfway(view):
    view._anim.setCurrentTime(view._anim.duration() // 2)
    return view.grab().toImage()


@pytest.mark.parametrize("style", ["classic", "fade", "slide", "zoom", "kenburns", "blur", "carousel",
                                   "flip", "wipe", "circle", "tiles", "blinds"])
def test_style_shows_the_photo(app, photos, style):
    view = view_for(app, photos, style)
    assert close_to(pixel(view.grab().toImage(), 0.5, 0.5), RED)
    view.show_index(1)
    view._anim.setCurrentTime(view._anim.duration())
    assert close_to(pixel(view.grab().toImage(), 0.5, 0.5), GREEN)
    dispose(app, view)


def test_fade_blends_the_photos(app, photos):
    view = view_for(app, photos, "fade")
    view.show_index(1)
    middle = pixel(halfway(view), 0.5, 0.5)
    assert not close_to(middle, RED, 30) and not close_to(middle, GREEN, 30)
    assert middle.red() > 60 and middle.green() > 60          # a mix of both
    dispose(app, view)


def test_slide_moves_the_new_photo_in_from_the_side(app, photos):
    view = view_for(app, photos, "slide")
    view.show_index(1, direction=1)
    frame = halfway(view)
    assert close_to(pixel(frame, 0.1, 0.5), RED) and close_to(pixel(frame, 0.9, 0.5), GREEN)
    dispose(app, view)


def at(view, share):
    """The frame at ``share`` (0..1) of the change time, and the eased progress there."""
    view._anim.setCurrentTime(int(view._anim.duration() * share))
    return view.grab().toImage(), float(view._anim.currentValue())


@pytest.mark.parametrize("style", sorted(__import__("ui.photo_show", fromlist=["STYLES"]).STYLES))
def test_every_style_animates_forward_and_back(app, photos, style):
    view = view_for(app, photos, style)
    for index, direction in ((1, 1), (2, 1), (3, 1), (1, -1)):   # 3 = the end screen
        view.show_index(index, direction)
        for share in (0.25, 0.5, 0.75):
            frame, _ = at(view, share)
            assert not frame.isNull()
    dispose(app, view)


def test_wipe_sweeps_in_from_the_side(app, photos):
    view = view_for(app, photos, "wipe")
    view.show_index(1, direction=1)
    frame = halfway(view)
    assert close_to(pixel(frame, 0.1, 0.5), RED) and close_to(pixel(frame, 0.9, 0.5), GREEN)
    view.show_index(0, direction=-1)                           # going back: from the other side
    view._anim.setCurrentTime(view._anim.duration() // 2)
    frame = view.grab().toImage()
    assert close_to(pixel(frame, 0.1, 0.5), RED) and close_to(pixel(frame, 0.9, 0.5), GREEN)
    dispose(app, view)


def test_circle_opens_from_the_middle(app, photos):
    view = view_for(app, photos, "circle")
    view.show_index(1)
    frame = halfway(view)
    assert close_to(pixel(frame, 0.5, 0.5), GREEN) and close_to(pixel(frame, 0.02, 0.03), RED)
    dispose(app, view)


def test_blinds_open_slat_by_slat(app, photos):
    view = view_for(app, photos, "blinds")
    view.show_index(1)
    frame = halfway(view)
    slat = 1 / 10
    assert close_to(pixel(frame, 5.5 * slat, 0.5), GREEN)      # the middle of a slat is open
    assert close_to(pixel(frame, 5 * slat + 0.004, 0.5), RED)  # its edge not yet
    dispose(app, view)


def test_mosaic_starts_with_a_few_tiles(app, photos):
    view = view_for(app, photos, "tiles")
    view.show_index(1)
    frame, t = at(view, 0.35)
    assert 0 < t < 0.5
    samples = [pixel(frame, (x + 0.5) / 16, (y + 0.5) / 9) for x in range(16) for y in range(9)]
    started = sum(not close_to(s, RED) for s in samples)       # tiles already fading in
    assert 0 < started < len(samples) / 2                      # some tiles in, most still to come
    dispose(app, view)


def test_flip_turns_like_a_card(app, photos):
    view = view_for(app, photos, "flip")
    view.show_index(1)
    frame, t = at(view, 0.3)
    assert t < 0.5
    assert close_to(pixel(frame, 0.5, 0.5), RED, 90)           # the old photo, turning away (dimmed)
    assert pixel(frame, 0.01, 0.5).value() < 20                # narrower than the screen: black at the edge
    frame, t = at(view, 0.7)
    assert t > 0.5 and pixel(frame, 0.5, 0.5).green() > pixel(frame, 0.5, 0.5).red()
    dispose(app, view)


def test_vintage_is_sepia_with_dark_corners(app, photos):
    view = view_for(app, photos, "vintage")
    frame = view.grab().toImage()
    middle, corner = pixel(frame, 0.5, 0.5), pixel(frame, 0.01, 0.02)
    assert middle.red() > middle.green() > middle.blue()       # warm brown, no longer bright red
    assert middle.red() < 180
    assert corner.value() < middle.value()                     # vignette
    dispose(app, view)


def test_black_and_white(app, photos):
    view = view_for(app, photos, "mono")
    middle = pixel(view.grab().toImage(), 0.5, 0.5)
    assert max(middle.red(), middle.green(), middle.blue()) - min(middle.red(), middle.green(), middle.blue()) <= 3
    dispose(app, view)


def test_soft_backdrop_instead_of_black_bars(app, tmp_path):
    square = [make_photo(tmp_path / "square.png", RED, (200, 200))]
    view = view_for(app, square, "blur")
    side = pixel(view.grab().toImage(), 0.04, 0.5)
    assert side.red() > 60 and side.red() > side.green() + 30  # blurred, darkened red - not black
    dispose(app, view)


def wait_for_neighbours(app, view, timeout=5.0):
    """Side photos load in the background; wait until they are ready."""
    keys = [view._key(i) for i in (view.index - 1, view.index + 1) if 0 <= i < view.count]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        view.grab()                                  # a paint asks for them
        app.processEvents()
        if all(k in view._pixmaps or (k in view._loading and view._loading[k].done()) for k in keys):
            view.grab()
            return True
        time.sleep(0.01)
    return False


def test_carousel_never_waits_for_a_side_photo(app, photos):
    view = view_for(app, photos, "carousel")
    view._pool.shutdown(wait=True)                   # nothing can load any more ...
    from concurrent.futures import Future
    view._loading[view._key(1)] = Future()           # ... photo 2 is "still loading"
    started = time.perf_counter()
    view.grab()
    assert time.perf_counter() - started < 1.0       # the frame is drawn without it
    assert view._key(1) in view._waiting
    dispose(app, view)


def test_carousel_shows_the_neighbours(app, photos):
    view = view_for(app, photos, "carousel")
    view.show_index(1)
    view._anim.setCurrentTime(view._anim.duration())
    assert wait_for_neighbours(app, view)
    frame = view.grab().toImage()
    left, middle, right = pixel(frame, 0.02, 0.5), pixel(frame, 0.5, 0.5), pixel(frame, 0.98, 0.5)
    assert close_to(middle, GREEN)
    assert left.red() > left.green() and left.red() > left.blue()         # the previous photo, dimmed
    assert right.blue() > right.red() and right.blue() > right.green()    # the next photo, dimmed
    dispose(app, view)


def test_classic_changes_at_once(app, photos):
    view = view_for(app, photos, "classic")
    view.show_index(1)
    assert view._old is None
    assert close_to(pixel(view.grab().toImage(), 0.5, 0.5), GREEN)
    dispose(app, view)


def test_polaroid_prints_on_a_dark_table(app, photos):
    view = view_for(app, photos, "polaroid")
    frame = view.grab().toImage()
    assert close_to(pixel(frame, 0.5, 0.45), RED)             # the photo in the print
    corner = pixel(frame, 0.02, 0.03)
    assert corner.value() < 70                                 # dark table around it
    dispose(app, view)


def test_fit_keeps_the_whole_photo_and_fill_covers_the_screen(app, tmp_path):
    square = [make_photo(tmp_path / "square.png", RED, (200, 200))]
    fit = view_for(app, square, "classic", fill=False)
    assert pixel(fit.grab().toImage(), 0.05, 0.5).value() < 20      # black bars at the sides
    dispose(app, fit)
    fill = view_for(app, square, "classic", fill=True)
    assert close_to(pixel(fill.grab().toImage(), 0.05, 0.5), RED)   # photo reaches the edge
    dispose(app, fill)


def test_end_screen_and_broken_photo(app, tmp_path, photos):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n not really")
    view = view_for(app, [photos[0], broken], "classic")
    view.show_index(1)
    assert view.grab().toImage() is not None                  # "Could not open broken.png", no crash
    view.show_index(2)
    assert view.index == 2                                    # the end screen
    dispose(app, view)


# -- controller --------------------------------------------------------------------------

@pytest.fixture
def controller(app, photos):
    from src.presentation.photo_controller import PhotoController

    ctrl = PhotoController()
    ctrl.open(photos)
    yield ctrl
    ctrl.close()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


def pump(app, seconds=0.1):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def test_controller_navigation(app, controller):
    assert controller.next_slide() is False                   # not started
    controller.start()
    assert controller.is_running and controller.position() == (1, 3)
    assert controller.window_handle()
    assert controller.previous_slide() is True and controller.position() == (1, 3)   # stays on the first
    for expected in ((2, 3), (3, 3), (4, 3), (4, 3)):         # 4/3 = the end screen, then no further
        controller.next_slide()
        assert controller.position() == expected
    pump(app)
    assert controller._window.index == 3
    controller.previous_slide()
    controller.go_to(0)
    pump(app)
    assert controller.position() == (1, 3) and controller._window.index == 0


def test_controller_is_driven_from_the_gesture_thread(app, controller):
    controller.start()
    worker = threading.Thread(target=lambda: [controller.next_slide() for _ in range(2)])
    worker.start()
    while worker.is_alive():
        pump(app, 0.02)
    pump(app)
    assert controller.position() == (3, 3) and controller._window.index == 2


def test_controller_started_from_a_worker_thread(app, controller):
    """The manager starts presentations in a worker thread; the window is still made on the GUI thread."""
    errors = []

    def start():
        try:
            controller.start()
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=start)
    worker.start()
    while worker.is_alive():
        pump(app, 0.02)
    assert not errors and controller.is_running
    assert controller._window.thread() is app.thread()


def test_escape_ends_the_slideshow(app, controller):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    controller.start()
    QTest.keyClick(controller._window, Qt.Key_Right)
    assert controller.position() == (2, 3)
    QTest.keyClick(controller._window, Qt.Key_Escape)
    pump(app)
    assert not controller.is_running


@pytest.fixture
def playback(monkeypatch):
    """Set loop / auto play for one test (config is restored afterwards)."""
    def set_options(loop=False, autoplay=False, seconds=1, debate=False):
        monkeypatch.setattr(config, "PHOTO_LOOP", loop)
        monkeypatch.setattr(config, "PHOTO_AUTOPLAY", autoplay)
        monkeypatch.setattr(config, "PHOTO_AUTOPLAY_SECONDS", seconds)
        monkeypatch.setattr(config, "DEBATE_MODE", debate)
    return set_options


def test_loop_starts_again_after_the_last_photo(app, controller, playback):
    playback(loop=True)
    controller.start()
    positions = []
    for _ in range(4):
        controller.next_slide()
        positions.append(controller.position())
    assert positions == [(2, 3), (3, 3), (1, 3), (2, 3)]   # no end screen
    controller.go_to(0)
    controller.previous_slide()
    assert controller.position() == (3, 3)                  # back from the first = the last


def test_without_loop_the_end_screen_comes_after_the_last_photo(app, controller, playback):
    playback(loop=False)
    controller.start()
    for _ in range(5):
        controller.next_slide()
    assert controller.position() == (4, 3)


def test_autoplay_moves_on_by_itself(app, controller, playback, monkeypatch):
    playback(autoplay=True)
    monkeypatch.setattr(controller, "autoplay_seconds", lambda: 0.15)
    controller.start()
    pump(app, 0.25)
    assert controller.position() == (2, 3)
    pump(app, 0.15)
    assert controller.position() == (3, 3)
    pump(app, 0.5)
    assert controller.position() == (4, 3)                  # the end screen, where auto play stops
    pump(app, 0.4)
    assert controller.position() == (4, 3)


def test_autoplay_with_loop_keeps_going(app, controller, playback, monkeypatch):
    playback(autoplay=True, loop=True)
    monkeypatch.setattr(controller, "autoplay_seconds", lambda: 0.1)
    controller.start()
    seen = set()
    end = time.monotonic() + 0.8
    while time.monotonic() < end:
        pump(app, 0.02)
        seen.add(controller.position())
    assert seen == {(1, 3), (2, 3), (3, 3)}                # round and round, never the end screen


def test_swipe_restarts_the_time_and_s_pauses(app, controller, playback, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    playback(autoplay=True)
    monkeypatch.setattr(controller, "autoplay_seconds", lambda: 0.3)
    controller.start()
    pump(app, 0.2)
    controller.next_slide()                                 # a swipe just before auto play
    pump(app, 0.2)
    assert controller.position() == (2, 3)                  # the new photo got its full 0.3 s
    QTest.keyClick(controller._window, Qt.Key_S)            # pause
    assert controller._window.autoplay_paused and "Paused" in controller._window.badge
    pump(app, 0.5)
    assert controller.position() == (2, 3)
    QTest.keyClick(controller._window, Qt.Key_S)            # continue
    pump(app, 0.4)
    assert controller.position() == (3, 3)


def test_debate_mode_turns_autoplay_off(app, controller, playback):
    playback(autoplay=True, seconds=5, debate=True)
    assert controller.autoplay_seconds() == 0
    playback(autoplay=True, seconds=5, debate=False)
    assert controller.autoplay_seconds() == 5


def test_ken_burns_lasts_as_long_as_each_photo(app, photos, playback):
    from ui.photo_show import PhotoShowWindow

    window = PhotoShowWindow(photos, "kenburns", False, autoplay_seconds=6)
    assert window.ken_burns_seconds == pytest.approx(6 + config.PHOTO_TRANSITION_MS / 1000)
    window.close()
    dispose(app, window)


def test_manager_opens_photos(app, photos, tmp_path):
    from src.presentation.base import PresentationOpenError
    from src.presentation.presentation_manager import FileType, PresentationManager
    from tests.test_presentation_manager import FakeController

    fake = FakeController("AirSlide photo slideshow")
    manager = PresentationManager({FileType.PHOTOS: lambda: fake})
    manager.open_photos([*photos, tmp_path / "missing.jpg"])
    assert fake.file_path == [p.resolve() for p in photos]
    assert manager.session.file_type == FileType.PHOTOS and manager.session.name == "3 photos"
    text = tmp_path / "a.txt"
    text.write_text("x")
    with pytest.raises(PresentationOpenError, match="None of the selected files is a photo"):
        manager.open_photos([text])


# -- setup dialog --------------------------------------------------------------------------

def test_setup_dialog(app, photos):
    from ui.photo_dialog import PhotoSetupDialog

    dialog = PhotoSetupDialog(None, photos, skipped=1)
    dialog.style_combo.setCurrentIndex(dialog.style_combo.findData("kenburns"))
    assert dialog.preview.style == "kenburns" and not dialog.fill_check.isEnabled()
    dialog.style_combo.setCurrentIndex(dialog.style_combo.findData("slide"))
    dialog.order_combo.setCurrentIndex(dialog.order_combo.findData("shuffle"))
    dialog.fill_check.setChecked(True)
    dialog.autoplay_check.setChecked(True)
    dialog.autoplay_seconds.setValue(7)
    dialog.loop_check.setChecked(True)
    assert dialog.values() == {"PHOTO_STYLE": "slide", "PHOTO_ORDER": "shuffle", "PHOTO_FILL": True,
                               "PHOTO_AUTOPLAY": True, "PHOTO_AUTOPLAY_SECONDS": 7, "PHOTO_LOOP": True}
    dialog.autoplay_check.setChecked(False)
    assert not dialog.autoplay_seconds.isEnabled()
    dialog._next_preview()
    assert dialog.preview.index == 1
    dialog.reject()
    dispose(app, dialog)


def test_settings_have_the_photo_styles():
    from src.utils.settings import BY_KEY
    from ui.photo_show import STYLES

    assert set(BY_KEY["PHOTO_STYLE"].choices) == set(STYLES)
    assert config.PHOTO_STYLE in STYLES
