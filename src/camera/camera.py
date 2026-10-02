"""
Webcam capture.

``Camera`` wraps ``cv2.VideoCapture`` and adds:

* configurable index / resolution / FPS / backend (defaults from config.py)
* optional mirroring, so the preview behaves like a mirror
* clear ``CameraError`` messages when the webcam is missing or stops
* an FPS measurement

Typical use::

    with Camera() as camera:
        while True:
            frame = camera.read()      # BGR numpy array, or None for a dropped frame
            ...
"""

import time
from collections import deque
from typing import Callable

import cv2  # MSMF speed-up env var is set in src/__init__.py before this import
import numpy as np

import config
from src.utils.logger import get_logger

log = get_logger(__name__)

BACKENDS = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "any": cv2.CAP_ANY,
}


class CameraError(RuntimeError):
    """Raised when the webcam cannot be opened or stops delivering frames."""


class FPSCounter:
    """Frames per second averaged over the last ``window`` frames."""

    def __init__(self, window: int | None = None, clock: Callable[[], float] = time.perf_counter):
        self._times: deque[float] = deque(maxlen=max(2, window or config.FPS_AVERAGE_FRAMES))
        self._clock = clock

    def tick(self) -> float:
        """Record one frame and return the current FPS."""
        self._times.append(self._clock())
        return self.fps

    @property
    def fps(self) -> float:
        if len(self._times) < 2:
            return 0.0
        elapsed = self._times[-1] - self._times[0]
        return (len(self._times) - 1) / elapsed if elapsed > 0 else 0.0

    def reset(self) -> None:
        self._times.clear()


class Camera:
    """A webcam that delivers BGR frames at the configured resolution."""

    def __init__(
        self,
        index: int | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        mirror: bool | None = None,
        backend: str | None = None,
        read_timeout: float | None = None,
        capture_factory: Callable[..., cv2.VideoCapture] = cv2.VideoCapture,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.index = config.CAMERA_INDEX if index is None else index
        self.requested_width = width or config.FRAME_WIDTH
        self.requested_height = height or config.FRAME_HEIGHT
        self.requested_fps = fps or config.CAMERA_FPS
        self.mirror = config.MIRROR_CAMERA if mirror is None else mirror
        self.backend = (backend or config.CAMERA_BACKEND).lower()
        fallback = config.CAMERA_FALLBACK_BACKEND if backend is None else None
        self.fallback_backend = fallback.lower() if fallback and fallback.lower() != self.backend else None
        self.read_timeout = config.CAMERA_READ_TIMEOUT if read_timeout is None else read_timeout

        self._capture_factory = capture_factory
        self._clock = clock
        self._cap: cv2.VideoCapture | None = None
        self._first_failure: float | None = None
        self._fps = FPSCounter()

        # Actual values reported once the camera is open.
        self.active_backend: str | None = None
        self.width = 0
        self.height = 0

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> "Camera":
        """Open the webcam (trying the fallback backend if needed) and verify it delivers a frame."""
        if self.is_opened:
            return self
        for name in filter(None, (self.backend, self.fallback_backend)):
            if name not in BACKENDS:
                raise CameraError(f"Unknown CAMERA_BACKEND '{name}'. Use one of: {', '.join(BACKENDS)}.")

        try:
            return self._open_with(self.backend)
        except CameraError as exc:
            if not self.fallback_backend:
                raise
            log.warning("Camera backend '%s' failed (%s) - trying '%s'", self.backend, exc, self.fallback_backend)
            return self._open_with(self.fallback_backend)

    def _open_with(self, backend: str) -> "Camera":
        log.info("Opening camera %d (%s, requested %dx%d@%d)",
                 self.index, backend, self.requested_width, self.requested_height, self.requested_fps)
        cap = self._capture_factory(self.index, BACKENDS[backend])
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            raise CameraError("Camera not found. Please connect a webcam.")

        # FOURCC must be set before the resolution for DirectShow to honour it.
        if config.CAMERA_FOURCC:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.CAMERA_FOURCC))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.requested_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.requested_height)
        cap.set(cv2.CAP_PROP_FPS, self.requested_fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # always process the newest frame (low latency)

        frame = self._first_frame(cap)
        if frame is None:
            cap.release()
            raise CameraError(
                "The camera opened but returned no image. "
                "Close other apps that use the webcam (Teams, Zoom, Camera) and try again."
            )

        self._cap = cap
        self.active_backend = backend
        self.height, self.width = frame.shape[:2]
        self._first_failure = None
        self._fps.reset()
        if (self.width, self.height) != (self.requested_width, self.requested_height):
            log.warning("Camera delivers %dx%d instead of the requested %dx%d",
                        self.width, self.height, self.requested_width, self.requested_height)
        log.info("Camera ready: %dx%d", self.width, self.height)
        return self

    @staticmethod
    def _first_frame(cap) -> np.ndarray | None:
        """Read until the webcam delivers its first image (short warm-up allowed)."""
        deadline = time.monotonic() + config.CAMERA_FIRST_FRAME_TIMEOUT
        while True:
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.05)

    def release(self) -> None:
        """Release the webcam. Safe to call more than once."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            log.info("Camera released")

    @property
    def is_opened(self) -> bool:
        return self._cap is not None

    def __enter__(self) -> "Camera":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.release()

    # -- frames --------------------------------------------------------------

    def read(self) -> np.ndarray | None:
        """
        Return the next BGR frame, or ``None`` for a single dropped frame.

        Raises ``CameraError`` when the camera is not open, or when it has
        delivered no frames for ``read_timeout`` seconds (e.g. unplugged).
        """
        if self._cap is None:
            raise CameraError("Camera is not open.")

        ok, frame = self._cap.read()
        if not ok or frame is None:
            now = self._clock()
            if self._first_failure is None:
                self._first_failure = now
            if now - self._first_failure >= self.read_timeout:
                raise CameraError("Camera stopped responding. Please check the webcam connection.")
            return None

        self._first_failure = None
        self._fps.tick()
        return cv2.flip(frame, 1) if self.mirror else frame

    @property
    def fps(self) -> float:
        """Measured frames per second (0.0 until two frames were read)."""
        return self._fps.fps

    @property
    def resolution(self) -> tuple[int, int]:
        """Actual (width, height) once open, otherwise (0, 0)."""
        return self.width, self.height
