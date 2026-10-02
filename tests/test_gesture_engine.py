"""Gesture engine tests with a fake camera and a fake hand detector (no hardware)."""

import threading
import time

import numpy as np

from src.camera.camera import CameraError
from src.engine.gesture_engine import MSG_PAUSED, GestureEngine
from src.gesture.swipe_detector import Gesture
from src.hand.hand_detector import Hand, HandDetectionError
from tests.hand_factory import make_hand


class FakeCamera:
    """Delivers numbered blank frames; ``fail_after`` simulates unplugging."""

    width, height, fps, mirror = 1280, 720, 30.0, True

    def __init__(self, frames: int = 10_000, fail_after: int | None = None, fail_open: bool = False):
        self.frames, self.fail_after, self.fail_open = frames, fail_after, fail_open
        self.count = 0
        self.released = False

    def open(self):
        if self.fail_open:
            raise CameraError("Camera not found. Please connect a webcam.")
        return self

    def read(self):
        if self.fail_after is not None and self.count >= self.fail_after:
            raise CameraError("Camera stopped responding. Please check the webcam connection.")
        self.count += 1
        time.sleep(0.005)
        return np.zeros((self.height, self.width, 3), np.uint8)

    def release(self):
        self.released = True


class FakeDetector:
    """Returns an open hand moving along ``xs`` (one x per frame), then nothing."""

    def __init__(self, xs):
        self.xs = list(xs)
        self.closed = False

    def detect(self, frame):
        if not self.xs:
            return []
        x = self.xs.pop(0)
        return [Hand(make_hand(offset=(x, 500)).astype("float32"), "Right", 0.95)]

    def close(self):
        self.closed = True


def swipe(start, end, steps=10):
    return [start] * 4 + [start + (end - start) * i / steps for i in range(steps + 1)]


def run_engine(xs, handler=None, camera=None, paused=False, wait_for=None, timeout=5.0, **kwargs):
    events = {"ready": threading.Event(), "commands": [], "errors": [], "updates": [], "handled": []}
    camera = camera or FakeCamera()
    detector = FakeDetector(xs)

    def default_handler(gesture):
        events["handled"].append(gesture)
        return True

    engine = GestureEngine(
        handler or default_handler,
        on_ready=events["ready"].set,
        on_update=events["updates"].append,
        on_command=events["commands"].append,
        on_error=events["errors"].append,
        camera_factory=lambda: camera,
        detector_factory=lambda: detector,
        **kwargs,
    )
    engine.paused = paused
    engine.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not (wait_for or (lambda e: False))(events):
        if not engine.is_running and events["errors"]:
            break
        time.sleep(0.01)
    engine.stop()
    events.update(engine=engine, camera=camera, detector=detector)
    return events


def test_swipe_right_to_left_runs_next_command():
    # default any-hand mode; FakeDetector hands are open, so this also holds in five-finger mode
    events = run_engine(swipe(900, 500), wait_for=lambda e: e["commands"])
    assert events["ready"].is_set()
    assert events["handled"] == [Gesture.NEXT]
    result = events["commands"][0]
    assert result.gesture == Gesture.NEXT and result.executed
    assert events["engine"].commands_executed == 1


def test_swipe_left_to_right_runs_previous_command():
    events = run_engine(swipe(400, 800), wait_for=lambda e: e["commands"])
    assert events["handled"] == [Gesture.PREVIOUS]


def test_no_hand_sends_no_command_but_status_updates():
    events = run_engine([], wait_for=lambda e: len(e["updates"]) > 20)
    assert events["handled"] == []
    assert events["updates"][-1].status.message == "Show your hand to the camera."


def test_paused_engine_recognises_but_does_not_execute():
    events = run_engine(swipe(900, 500) + [500] * 5, paused=True,
                        wait_for=lambda e: e["commands"] and len(e["updates"]) > 20)
    assert events["handled"] == []
    assert events["commands"][0].executed is False
    assert any(u.status.message == MSG_PAUSED for u in events["updates"])


def test_command_failure_is_reported_not_crashing():
    def broken(gesture):
        raise RuntimeError("PowerPoint went away")

    events = run_engine(swipe(900, 500) + [500] * 10, handler=broken,
                        wait_for=lambda e: e["commands"] and len(e["updates"]) > 20)
    assert events["commands"][0].executed is False
    assert events["errors"] == []


def test_camera_missing_reports_error():
    events = run_engine([], camera=FakeCamera(fail_open=True), wait_for=lambda e: e["errors"])
    assert events["errors"] == ["Camera not found. Please connect a webcam."]
    assert not events["ready"].is_set()


def test_camera_unplugged_during_presentation_reports_error_and_releases():
    events = run_engine([], camera=FakeCamera(fail_after=5), wait_for=lambda e: e["errors"])
    assert "stopped responding" in events["errors"][0]
    assert events["camera"].released and events["detector"].closed


def test_model_error_reports_error():
    def no_model():
        raise HandDetectionError("Hand model not found")

    events = {"errors": []}
    engine = GestureEngine(lambda g: True, on_error=events["errors"].append,
                           camera_factory=FakeCamera, detector_factory=no_model)
    engine.start()
    for _ in range(200):
        if events["errors"]:
            break
        time.sleep(0.01)
    engine.stop()
    assert events["errors"] == ["Hand model not found"]


def test_preview_frames_only_when_wanted():
    with_frames = run_engine([], want_frames=lambda: True, wait_for=lambda e: len(e["updates"]) > 5)
    without = run_engine([], want_frames=lambda: False, wait_for=lambda e: len(e["updates"]) > 5)
    image = with_frames["updates"][-1].image
    assert image is not None and image.shape[1] == 640  # scaled to PREVIEW_WIDTH
    assert without["updates"][-1].image is None


def test_stop_releases_camera():
    events = run_engine([], wait_for=lambda e: len(e["updates"]) > 3)
    assert not events["engine"].is_running
    assert events["camera"].released
