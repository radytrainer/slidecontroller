"""Camera tests with a fake capture device (no webcam needed)."""

import numpy as np
import pytest

import config
from src.camera.camera import Camera, CameraError, FPSCounter


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


class FakeCapture:
    """Mimics cv2.VideoCapture. ``script`` lists read() results: frame or None."""

    def __init__(self, opened=True, script=None, width=1280, height=720):
        self.opened = opened
        self.frame = np.zeros((height, width, 3), dtype=np.uint8)
        self.frame[:, 0] = 255  # mark the left column so mirroring is visible
        self.script = list(script) if script is not None else []
        self.released = False
        self.props = {}

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def read(self):
        item = self.script.pop(0) if self.script else self.frame
        return (item is not None), (None if item is None else item.copy())

    def release(self):
        self.released = True
        self.opened = False


def make_camera(capture, **kwargs):
    return Camera(capture_factory=lambda index, backend: capture, **kwargs)


def test_open_reports_actual_resolution():
    capture = FakeCapture(width=640, height=480)
    with make_camera(capture) as camera:
        assert camera.is_opened
        assert camera.resolution == (640, 480)


def test_camera_not_found_raises_clear_error():
    capture = FakeCapture(opened=False)
    with pytest.raises(CameraError, match="Camera not found"):
        make_camera(capture).open()
    assert capture.released


def test_camera_opened_but_no_image_raises(monkeypatch):
    monkeypatch.setattr(config, "CAMERA_FIRST_FRAME_TIMEOUT", 0.2)
    capture = FakeCapture(script=[None] * 1000)
    with pytest.raises(CameraError, match="returned no image"):
        make_camera(capture, backend="msmf").open()  # explicit backend = no fallback
    assert capture.released


def test_slow_first_frame_is_waited_for():
    capture = FakeCapture(script=[None, None, None])  # webcam still warming up
    with make_camera(capture, backend="msmf") as camera:
        assert camera.active_backend == "msmf"
        assert camera.resolution == (1280, 720)


def test_falls_back_to_second_backend():
    import cv2

    captures = {cv2.CAP_MSMF: FakeCapture(opened=False), cv2.CAP_DSHOW: FakeCapture()}
    camera = Camera(capture_factory=lambda index, backend: captures[backend])
    assert camera.backend == "msmf" and camera.fallback_backend == "dshow"
    with camera:
        assert camera.active_backend == "dshow"
        assert camera.read() is not None


def test_release_is_idempotent_and_closes_capture():
    capture = FakeCapture()
    camera = make_camera(capture).open()
    camera.release()
    camera.release()
    assert capture.released
    assert not camera.is_opened


def test_read_before_open_raises():
    with pytest.raises(CameraError, match="not open"):
        make_camera(FakeCapture()).read()


def test_mirror_flips_frame_horizontally():
    with make_camera(FakeCapture(), mirror=True) as camera:
        frame = camera.read()
    assert frame[0, -1, 0] == 255 and frame[0, 0, 0] == 0


def test_no_mirror_keeps_frame():
    with make_camera(FakeCapture(), mirror=False) as camera:
        frame = camera.read()
    assert frame[0, 0, 0] == 255


def test_single_dropped_frame_returns_none_then_recovers():
    capture = FakeCapture()
    clock = FakeClock()
    with make_camera(capture, clock=clock, read_timeout=2.0) as camera:
        capture.script = [None]
        assert camera.read() is None
        assert camera.read() is not None


def test_camera_lost_after_timeout():
    capture = FakeCapture()
    clock = FakeClock()
    with make_camera(capture, clock=clock, read_timeout=2.0) as camera:
        capture.script = [None, None, None]
        assert camera.read() is None
        clock.now = 1.0
        assert camera.read() is None
        clock.now = 2.5
        with pytest.raises(CameraError, match="stopped responding"):
            camera.read()


def test_unknown_backend_raises():
    with pytest.raises(CameraError, match="Unknown CAMERA_BACKEND"):
        make_camera(FakeCapture(), backend="nope").open()


def test_fps_counter_measures_rate():
    clock = FakeClock()
    counter = FPSCounter(window=10, clock=clock)
    assert counter.fps == 0.0
    for i in range(10):
        clock.now = i / 30
        counter.tick()
    assert counter.fps == pytest.approx(30.0)


def test_fps_counter_uses_sliding_window():
    clock = FakeClock()
    counter = FPSCounter(window=5, clock=clock)
    for i in range(5):  # 10 FPS
        clock.now = i * 0.1
        counter.tick()
    for i in range(1, 6):  # then 50 FPS
        clock.now = 0.4 + i * 0.02
        counter.tick()
    assert counter.fps == pytest.approx(50.0)
