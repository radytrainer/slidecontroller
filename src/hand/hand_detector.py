r"""
Hand detection with MediaPipe Hand Landmarker (Tasks API).

``HandDetector`` is created once and reused for every frame (never rebuilt
per frame). It runs in VIDEO mode, so MediaPipe tracks the hand between frames
instead of searching the whole image each time - faster and steadier.

Each detected hand is returned as a ``Hand`` with its 21 landmarks in
**pixel coordinates** of the frame that was passed in::

        8   12  16  20          tips
        |   |   |   |
        7   11  15  19
        |   |   |   |
    4   6   10  14  18
    |   |   |   |   |
    3   5---9---13--17          MCP knuckles
     \  |          /
      2 |         /
       \|        /
        1       /
         \     /
          0 (wrist)
"""

import time
import urllib.request
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

import config
from src.utils.logger import get_logger

log = get_logger(__name__)


class HandLandmark(IntEnum):
    """The 21 MediaPipe hand landmarks."""

    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


NUM_LANDMARKS = len(HandLandmark)

FINGERTIPS = (
    HandLandmark.THUMB_TIP,
    HandLandmark.INDEX_TIP,
    HandLandmark.MIDDLE_TIP,
    HandLandmark.RING_TIP,
    HandLandmark.PINKY_TIP,
)

# Bones drawn between landmarks: 5 fingers + the palm.
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # index
    (9, 10), (10, 11), (11, 12),             # middle
    (13, 14), (14, 15), (15, 16),            # ring
    (0, 17), (17, 18), (18, 19), (19, 20),   # pinky
    (5, 9), (9, 13), (13, 17),               # palm
)


class HandDetectionError(RuntimeError):
    """Raised when the hand model cannot be found, downloaded or loaded."""


@dataclass(frozen=True)
class Hand:
    """One detected hand.

    ``landmarks`` is a (21, 3) float array: x and y in pixels, z is relative
    depth (smaller = closer to the camera), scaled like x.
    """

    landmarks: np.ndarray
    handedness: str  # "Left" or "Right" (as seen by the presenter when the frame is mirrored)
    score: float

    def point(self, landmark: int) -> tuple[float, float]:
        """(x, y) pixel position of one landmark."""
        x, y, _ = self.landmarks[landmark]
        return float(x), float(y)


def landmark_array(landmarks) -> np.ndarray:
    """Accept a ``Hand`` or a (21, 2|3) array and return float64 coordinates."""
    points = np.asarray(getattr(landmarks, "landmarks", landmarks), dtype=np.float64)
    if points.ndim != 2 or points.shape[0] != NUM_LANDMARKS:
        raise ValueError(f"expected 21 landmarks, got array of shape {points.shape}")
    return points


def ensure_model(path: Path | None = None, url: str | None = None) -> Path:
    """Return the model path, downloading the model on first use."""
    path = Path(path or config.HAND_MODEL_PATH)
    if path.is_file():
        return path

    url = url or config.HAND_MODEL_URL
    log.info("Downloading hand model to %s", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".download")
    try:
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise HandDetectionError(
            f"Hand model not found and could not be downloaded ({exc}).\n"
            f"Download it manually from:\n{url}\nand save it as:\n{path}"
        ) from exc
    return path


def to_hands(result, width: int, height: int) -> list[Hand]:
    """Convert a MediaPipe HandLandmarkerResult into ``Hand`` objects in pixels."""
    hands = []
    for landmarks, handedness in zip(result.hand_landmarks, result.handedness, strict=True):
        points = np.array([(lm.x * width, lm.y * height, lm.z * width) for lm in landmarks],
                          dtype=np.float32)
        category = handedness[0]
        hands.append(Hand(points, category.category_name, float(category.score)))
    # Most confident hand first, so callers can simply use hands[0].
    hands.sort(key=lambda hand: hand.score, reverse=True)
    return hands


class HandDetector:
    """Detects up to ``max_hands`` hands in BGR frames."""

    def __init__(
        self,
        max_hands: int | None = None,
        min_detection_confidence: float | None = None,
        min_presence_confidence: float | None = None,
        min_tracking_confidence: float | None = None,
        model_path: Path | None = None,
    ):
        model = ensure_model(model_path)
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=max_hands or config.MAX_NUM_HANDS,
            min_hand_detection_confidence=min_detection_confidence or config.MIN_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=min_presence_confidence or config.MIN_PRESENCE_CONFIDENCE,
            min_tracking_confidence=min_tracking_confidence or config.MIN_TRACKING_CONFIDENCE,
        )
        try:
            self._landmarker = vision.HandLandmarker.create_from_options(options)
        except (RuntimeError, ValueError) as exc:
            raise HandDetectionError(f"Could not load the hand model {model}: {exc}") from exc
        self._last_timestamp_ms = -1
        log.info("Hand detector ready (max %d hands)", options.num_hands)

    def detect(self, frame_bgr: np.ndarray) -> list[Hand]:
        """Return the hands in ``frame_bgr`` (most confident first)."""
        if self._landmarker is None:
            raise HandDetectionError("Hand detector is closed.")

        height, width = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        # VIDEO mode needs strictly increasing timestamps.
        timestamp_ms = max(int(time.monotonic() * 1000), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms

        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return to_hands(result, width, height)

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None

    def __enter__(self) -> "HandDetector":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# -- debug drawing -----------------------------------------------------------

BONE_COLOR = (255, 255, 255)
JOINT_COLOR = (80, 80, 255)
TIP_COLOR = (80, 220, 80)


def draw_hand(frame: np.ndarray, hand: Hand, label: bool = True, bone_color=BONE_COLOR) -> None:
    """Draw the 21 landmarks and bones of ``hand`` onto ``frame`` in place."""
    points = [(int(x), int(y)) for x, y, _ in hand.landmarks]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, points[a], points[b], bone_color, 3, cv2.LINE_AA)
    for index, point in enumerate(points):
        is_tip = index in FINGERTIPS
        cv2.circle(frame, point, 7 if is_tip else 5, TIP_COLOR if is_tip else JOINT_COLOR, -1, cv2.LINE_AA)
    if label:
        x, y = points[HandLandmark.WRIST]
        text = f"{hand.handedness} {hand.score:.2f}"
        cv2.putText(frame, text, (x - 40, y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, text, (x - 40, y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, TIP_COLOR, 2, cv2.LINE_AA)
