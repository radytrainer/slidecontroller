"""
Hand position tracking.

``get_hand_center`` returns a stable point for the hand: the centre of the
palm, i.e. the mean of the wrist and the four finger knuckles (MCP joints).
These points barely move when fingers wiggle, so the centre follows the
whole hand rather than a single fingertip.

``MovementTracker`` remembers recent centres (previous_x / current_x, the
frame-to-frame motion and a short trail for the debug view).
"""

from collections import deque

from src.hand.hand_detector import HandLandmark as L
from src.hand.hand_detector import landmark_array

PALM_LANDMARKS = (L.WRIST, L.INDEX_MCP, L.MIDDLE_MCP, L.RING_MCP, L.PINKY_MCP)


def get_hand_center(landmarks) -> tuple[float, float]:
    """(x, y) of the palm centre, in the same units as the landmarks (pixels)."""
    palm = landmark_array(landmarks)[list(PALM_LANDMARKS), :2]
    x, y = palm.mean(axis=0)
    return float(x), float(y)


class MovementTracker:
    """Recent palm-centre positions of one hand."""

    def __init__(self, trail_length: int = 30):
        self.trail: deque[tuple[float, float]] = deque(maxlen=trail_length)

    def update(self, center: tuple[float, float]) -> None:
        self.trail.append(center)

    def reset(self) -> None:
        self.trail.clear()

    @property
    def current(self) -> tuple[float, float] | None:
        return self.trail[-1] if self.trail else None

    @property
    def previous(self) -> tuple[float, float] | None:
        return self.trail[-2] if len(self.trail) > 1 else None

    @property
    def current_x(self) -> float | None:
        return self.current[0] if self.current else None

    @property
    def previous_x(self) -> float | None:
        return self.previous[0] if self.previous else None

    @property
    def frame_delta(self) -> tuple[float, float]:
        """Movement (dx, dy) since the previous frame."""
        if self.previous is None:
            return 0.0, 0.0
        return self.current[0] - self.previous[0], self.current[1] - self.previous[1]
