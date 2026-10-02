"""
The gesture engine: connects everything on one background thread.

    Camera -> PresenterHandDetector (presenter's hand only) -> open palm
           -> SwipeDetector -> GestureStateMachine
           -> command_handler(Gesture.NEXT / Gesture.PREVIOUS)

The engine knows nothing about PowerPoint, PDFs or the GUI. It calls
``command_handler(gesture)`` (in AirSlide: PresentationManager.next_slide /
previous_slide) and reports progress through callbacks:

    on_ready()                 camera + hand model are running
    on_update(EngineUpdate)    every frame: gesture status (+ preview image)
    on_command(CommandResult)  a gesture was recognised (and executed or not)
    on_error(message)          camera/model failure; the engine stops

Callbacks are called from the engine thread; the GUI forwards them to the
Qt main thread with signals.
"""

import threading
import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

import config
from src.camera.camera import Camera, CameraError
from src.gesture.debug_view import draw_debug_overlay
from src.gesture.gesture_state import GestureStateMachine, GestureStatus
from src.gesture.hand_tracking import MovementTracker
from src.gesture.swipe_detector import Direction, Gesture, Swipe, SwipeDetector
from src.hand.hand_detector import HandDetectionError, HandDetector
from src.hand.presenter import PresenterHandDetector
from src.utils.logger import get_logger

log = get_logger(__name__)

MSG_PAUSED = "Gestures paused."


@dataclass(frozen=True)
class CommandResult:
    gesture: Gesture
    direction: Direction
    distance: float
    executed: bool       # False when paused or the presentation did not accept it
    timestamp: float


@dataclass(frozen=True)
class EngineUpdate:
    status: GestureStatus
    fps: float
    paused: bool
    image: np.ndarray | None = None   # BGR preview (only when frames are wanted)


class GestureEngine:
    def __init__(
        self,
        command_handler: Callable[[Gesture], bool],
        on_ready: Callable[[], None] | None = None,
        on_update: Callable[[EngineUpdate], None] | None = None,
        on_command: Callable[[CommandResult], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        want_frames: Callable[[], bool] = lambda: config.SHOW_CAMERA_PREVIEW,
        camera_factory: Callable[[], Camera] = Camera,
        detector_factory: Callable[[], HandDetector | PresenterHandDetector] = PresenterHandDetector,
    ):
        self._command_handler = command_handler
        self._on_ready = on_ready or (lambda: None)
        self._on_update = on_update or (lambda update: None)
        self._on_command = on_command or (lambda result: None)
        self._on_error = on_error or (lambda message: None)
        self._want_frames = want_frames
        self._camera_factory = camera_factory
        self._detector_factory = detector_factory

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reload = threading.Event()
        self.paused = False
        self.commands_executed = 0

    # -- control ---------------------------------------------------------------------

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gesture-engine", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def reload_settings(self) -> None:
        """Rebuild the gesture logic with the current config values (next frame)."""
        self._reload.set()

    # -- engine thread -------------------------------------------------------------------

    def _run(self) -> None:
        camera = detector = None
        try:
            try:
                camera = self._camera_factory()
                camera.open()
                detector = self._detector_factory()
            except (CameraError, HandDetectionError) as exc:
                log.error("Gesture engine could not start: %s", exc)
                self._on_error(str(exc))
                return

            log.info("Gesture engine running")
            self._on_ready()
            self._loop(camera, detector)
        except Exception as exc:  # never die silently on the background thread
            log.exception("Gesture engine crashed")
            self._on_error(f"Gesture engine stopped: {exc}")
        finally:
            if detector is not None:
                detector.close()
            if camera is not None:
                camera.release()
            log.info("Gesture engine stopped")

    def _new_machine(self, frame_width: int) -> GestureStateMachine:
        return GestureStateMachine(SwipeDetector(frame_width=frame_width))

    def _loop(self, camera: Camera, detector: HandDetector) -> None:
        machine = self._new_machine(camera.width)
        tracker = MovementTracker()
        last_swipe: Swipe | None = None
        last_swipe_time = 0.0

        while not self._stop.is_set():
            if self._reload.is_set():
                self._reload.clear()
                machine = self._new_machine(camera.width)
                log.info("Gesture settings reloaded")

            try:
                frame = camera.read()
            except CameraError as exc:
                self._on_error(str(exc))
                return
            if frame is None:
                continue

            now = time.monotonic()
            hands = detector.detect(frame)
            status = machine.update(hands, now)
            if status.center:
                tracker.update(status.center)
            else:
                tracker.reset()

            if status.swipe:
                last_swipe, last_swipe_time = status.swipe, now
                self._execute(status.swipe, now)
                machine.mark_executed()

            if self.paused and status.hand_count:
                status = _with_message(status, MSG_PAUSED)

            image = None
            if self._want_frames():
                if config.DEBUG:
                    draw_debug_overlay(frame, hands, status, camera.fps, tracker,
                                       last_swipe, now - last_swipe_time if last_swipe else None,
                                       focus=getattr(detector, "last", None))
                image = _resize(frame, config.PREVIEW_WIDTH)
            self._on_update(EngineUpdate(status, camera.fps, self.paused, image))

    def _execute(self, swipe: Swipe, now: float) -> None:
        executed = False
        if not self.paused:
            try:
                executed = bool(self._command_handler(swipe.gesture))
            except Exception:
                log.exception("Command %s failed", swipe.gesture.value)
        if executed:
            self.commands_executed += 1
        log.info("%s (%s, %.0f px, %.2f s) -> %s", swipe.gesture.value, swipe.direction.value,
                 swipe.distance, swipe.duration,
                 "executed" if executed else ("paused" if self.paused else "not executed"))
        self._on_command(CommandResult(swipe.gesture, swipe.direction, swipe.distance, executed, now))


def _with_message(status: GestureStatus, message: str) -> GestureStatus:
    from dataclasses import replace

    return replace(status, message=message)


def _resize(frame: np.ndarray, width: int) -> np.ndarray:
    height, current = frame.shape[:2]
    if current <= width:
        return frame
    return cv2.resize(frame, (width, int(height * width / current)), interpolation=cv2.INTER_AREA)
