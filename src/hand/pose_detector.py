"""
Body detection with MediaPipe Pose Landmarker (Tasks API).

Used to find the PRESENTER: people are much bigger than hands, so the pose
model still finds someone standing several metres away, where the hand model
no longer sees their hand in the full image. Only a few of the 33 landmarks
are used (shoulders and wrists); they are returned in pixel coordinates.

Like ``HandDetector`` it is created once and runs in VIDEO mode.
"""

import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

import config
from src.hand.hand_detector import HandDetectionError, ensure_model
from src.utils.logger import get_logger

log = get_logger(__name__)


class PoseLandmark(IntEnum):
    """The pose landmarks AirSlide uses (of MediaPipe's 33)."""

    NOSE = 0
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_WRIST = 15
    RIGHT_WRIST = 16


NUM_POSE_LANDMARKS = 33

# Shoulders less visible than this (hidden / outside the image) are not trusted.
MIN_SHOULDER_VISIBILITY = 0.3


@dataclass(frozen=True)
class Body:
    """One detected person.

    ``landmarks`` is a (33, 3) float array: x and y in pixels, then the
    landmark's visibility (0..1).
    """

    landmarks: np.ndarray

    def point(self, landmark: int) -> tuple[float, float]:
        x, y, _ = self.landmarks[landmark]
        return float(x), float(y)

    @property
    def shoulder_center(self) -> tuple[float, float]:
        (lx, ly), (rx, ry) = self.point(PoseLandmark.LEFT_SHOULDER), self.point(PoseLandmark.RIGHT_SHOULDER)
        return (lx + rx) / 2, (ly + ry) / 2

    @property
    def shoulder_width(self) -> float:
        """Distance between the shoulders in pixels (the body's size in the image)."""
        (lx, ly), (rx, ry) = self.point(PoseLandmark.LEFT_SHOULDER), self.point(PoseLandmark.RIGHT_SHOULDER)
        return max(1.0, float(np.hypot(lx - rx, ly - ry)))

    @property
    def shoulders_visible(self) -> bool:
        return bool(min(self.landmarks[PoseLandmark.LEFT_SHOULDER, 2],
                        self.landmarks[PoseLandmark.RIGHT_SHOULDER, 2]) >= MIN_SHOULDER_VISIBILITY)

    def distance_to(self, point: tuple[float, float]) -> float:
        """Distance from the shoulder centre to ``point``, in shoulder widths."""
        cx, cy = self.shoulder_center
        return float(np.hypot(point[0] - cx, point[1] - cy)) / self.shoulder_width


def to_bodies(result, width: int, height: int) -> list[Body]:
    """Convert a MediaPipe PoseLandmarkerResult into ``Body`` objects in pixels."""
    bodies = []
    for landmarks in result.pose_landmarks:
        points = np.array([(lm.x * width, lm.y * height, lm.visibility or 0.0) for lm in landmarks],
                          dtype=np.float32)
        body = Body(points)
        if body.shoulders_visible:
            bodies.append(body)
    return bodies


class PoseDetector:
    """Detects up to ``max_poses`` people in BGR frames."""

    def __init__(
        self,
        max_poses: int | None = None,
        min_confidence: float | None = None,
        input_scale: float | None = None,
        model_path: Path | None = None,
    ):
        model = ensure_model(model_path or config.POSE_MODEL_PATH, config.POSE_MODEL_URL)
        confidence = min_confidence or config.MIN_POSE_CONFIDENCE
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=max_poses or config.MAX_NUM_POSES,
            min_pose_detection_confidence=confidence,
            min_pose_presence_confidence=confidence,
            min_tracking_confidence=confidence,
        )
        try:
            self._landmarker = vision.PoseLandmarker.create_from_options(options)
        except (RuntimeError, ValueError) as exc:
            raise HandDetectionError(f"Could not load the pose model {model}: {exc}") from exc
        self.input_scale = config.POSE_INPUT_SCALE if input_scale is None else input_scale
        self._last_timestamp_ms = -1
        log.info("Pose detector ready (max %d people)", options.num_poses)

    def detect(self, frame_bgr: np.ndarray) -> list[Body]:
        """Return the people in ``frame_bgr`` with landmarks in full-frame pixels."""
        if self._landmarker is None:
            raise HandDetectionError("Pose detector is closed.")

        height, width = frame_bgr.shape[:2]
        small = frame_bgr
        if 0 < self.input_scale < 1:
            small = cv2.resize(frame_bgr, (int(width * self.input_scale), int(height * self.input_scale)),
                               interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        timestamp_ms = max(int(time.monotonic() * 1000), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms

        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return to_bodies(result, width, height)  # normalised coordinates -> full-frame pixels

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
