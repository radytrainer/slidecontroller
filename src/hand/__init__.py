"""AirSlide hand detection package."""

from src.hand.hand_detector import (
    FINGERTIPS,
    HAND_CONNECTIONS,
    Hand,
    HandDetectionError,
    HandDetector,
    HandLandmark,
    draw_hand,
)
from src.hand.pose_detector import Body, PoseDetector
from src.hand.presenter import FocusResult, PresenterFocus, PresenterHandDetector

__all__ = [
    "Body",
    "FocusResult",
    "PoseDetector",
    "PresenterFocus",
    "PresenterHandDetector",
    "FINGERTIPS",
    "HAND_CONNECTIONS",
    "Hand",
    "HandDetectionError",
    "HandDetector",
    "HandLandmark",
    "draw_hand",
]
