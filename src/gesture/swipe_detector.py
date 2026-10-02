"""
Horizontal swipe detection.

Feed the palm centre of an OPEN hand every frame with ``update(x, y, t)``.
The detector keeps the path of the last ``MAX_SWIPE_DURATION`` seconds and
reports a swipe as soon as, measured from the farthest point in that window:

* |delta_x| >= the minimum distance          (big enough, see below)
* |delta_x| >  |delta_y| * HORIZONTAL_RATIO  (horizontal, not vertical)
* duration  <= MAX_SWIPE_DURATION           (fast enough - older points are dropped)

The minimum distance is MIN_SWIPE_DISTANCE pixels for a hand close to the
camera. A presenter standing far away has a small hand that moves fewer
pixels, so when the palm size is passed to ``update`` the distance becomes
SWIPE_DISTANCE_PALMS palm sizes, capped at MIN_SWIPE_DISTANCE and never
below MIN_SWIPE_DISTANCE_FAR.

Fast swipes blur the hand, so it can vanish for a few frames mid-movement.
The path is kept while the hand is missing for up to SWIPE_LOST_SECONDS.

Direction is expressed from the PRESENTER's point of view:

    presenter moves hand RIGHT -> LEFT  =>  NEXT
    presenter moves hand LEFT -> RIGHT  =>  PREVIOUS

With a mirrored frame (config.MIRROR_CAMERA = True) the image behaves like a
mirror, so the presenter's right -> left is image delta_x < 0. Without
mirroring it is the opposite; ``mirrored`` handles both.
"""

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum

import config


class Direction(Enum):
    RIGHT_TO_LEFT = "RIGHT → LEFT"
    LEFT_TO_RIGHT = "LEFT → RIGHT"

    @property
    def ascii(self) -> str:
        """Label for OpenCV text, which cannot draw the arrow character."""
        return self.value.replace("→", "->")


class Gesture(Enum):
    NEXT = "NEXT"
    PREVIOUS = "PREVIOUS"


DIRECTION_TO_GESTURE = {
    Direction.RIGHT_TO_LEFT: Gesture.NEXT,
    Direction.LEFT_TO_RIGHT: Gesture.PREVIOUS,
}


@dataclass(frozen=True)
class SwipeProgress:
    """Snapshot of the swipe being tracked (for the debug view)."""

    start_x: float
    start_y: float
    current_x: float
    current_y: float
    start_time: float
    current_time: float

    @property
    def delta_x(self) -> float:
        return self.current_x - self.start_x

    @property
    def delta_y(self) -> float:
        return self.current_y - self.start_y

    @property
    def distance(self) -> float:
        """Horizontal travel in pixels."""
        return abs(self.delta_x)

    @property
    def duration(self) -> float:
        return self.current_time - self.start_time


@dataclass(frozen=True)
class Swipe(SwipeProgress):
    """A completed swipe."""

    direction: Direction = Direction.RIGHT_TO_LEFT

    @property
    def gesture(self) -> Gesture:
        return DIRECTION_TO_GESTURE[self.direction]


class SwipeDetector:
    """Detects one horizontal open-palm swipe at a time."""

    def __init__(
        self,
        min_distance: float | None = None,
        max_duration: float | None = None,
        horizontal_ratio: float | None = None,
        mirrored: bool | None = None,
        frame_width: int | None = None,
        lost_seconds: float | None = None,
        distance_palms: float | None = None,
        min_distance_far: float | None = None,
    ):
        min_distance = config.MIN_SWIPE_DISTANCE if min_distance is None else min_distance
        min_distance_far = config.MIN_SWIPE_DISTANCE_FAR if min_distance_far is None else min_distance_far
        # Pixel distances are defined for a FRAME_WIDTH-wide frame; scale them
        # when the camera delivers another width so the gesture feels the same.
        if frame_width:
            min_distance *= frame_width / config.FRAME_WIDTH
            min_distance_far *= frame_width / config.FRAME_WIDTH
        self.min_distance = min_distance
        self.min_distance_far = min(min_distance_far, min_distance)
        self.distance_palms = config.SWIPE_DISTANCE_PALMS if distance_palms is None else distance_palms
        self.max_duration = config.MAX_SWIPE_DURATION if max_duration is None else max_duration
        self.horizontal_ratio = config.HORIZONTAL_RATIO if horizontal_ratio is None else horizontal_ratio
        self.mirrored = config.MIRROR_CAMERA if mirrored is None else mirrored
        self.lost_seconds = config.SWIPE_LOST_SECONDS if lost_seconds is None else lost_seconds
        self._path: deque[tuple[float, float, float]] = deque()  # (t, x, y)
        self._scales: deque[float] = deque(maxlen=15)  # recent palm sizes

    # -- input -----------------------------------------------------------------

    def update(
        self,
        x: float,
        y: float,
        timestamp: float | None = None,
        scale: float | None = None,
        can_fire: bool = True,
    ) -> Swipe | None:
        """Add the palm centre of this frame. Returns a ``Swipe`` when one completes.

        ``scale`` is the palm size in pixels (lowers the distance for a far hand).
        With ``can_fire=False`` the point is recorded but no swipe is reported yet.
        """
        now = time.monotonic() if timestamp is None else timestamp
        self._path.append((now, x, y))
        if scale:
            self._scales.append(scale)
        while self._path and now - self._path[0][0] > self.max_duration:
            self._path.popleft()
        if not can_fire:
            return None

        start = self._best_start(x)
        if start is None:
            return None
        start_t, start_x, start_y = start
        delta_x, delta_y = x - start_x, y - start_y

        if abs(delta_x) < self.required_distance:
            return None
        if abs(delta_x) <= abs(delta_y) * self.horizontal_ratio:
            return None

        image_leftward = delta_x < 0
        presenter_right_to_left = image_leftward if self.mirrored else not image_leftward
        direction = Direction.RIGHT_TO_LEFT if presenter_right_to_left else Direction.LEFT_TO_RIGHT

        self.reset()  # one movement = one swipe
        return Swipe(start_x, start_y, x, y, start_t, now, direction)

    def missed(self, timestamp: float | None = None) -> None:
        """Call when this frame has no usable hand. Resets once it is gone too long."""
        now = time.monotonic() if timestamp is None else timestamp
        if self._path and now - self._path[-1][0] > self.lost_seconds:
            self.reset()

    def reset(self) -> None:
        self._path.clear()
        self._scales.clear()

    # -- state -------------------------------------------------------------------

    @property
    def is_tracking(self) -> bool:
        return bool(self._path)

    @property
    def required_distance(self) -> float:
        """Horizontal travel (px) needed for a swipe with the current hand size."""
        if not self._scales:
            return self.min_distance
        palm = sorted(self._scales)[len(self._scales) // 2]  # median: ignores one bad frame
        return min(self.min_distance, max(self.min_distance_far, self.distance_palms * palm))

    @property
    def progress(self) -> SwipeProgress | None:
        if not self._path:
            return None
        now, x, y = self._path[-1]
        start_t, start_x, start_y = self._best_start(x) or self._path[0]
        return SwipeProgress(start_x, start_y, x, y, start_t, now)

    def _best_start(self, x: float) -> tuple[float, float, float] | None:
        """The point in the window farthest (horizontally) from the current x."""
        if len(self._path) < 2:
            return None
        return max(self._path, key=lambda point: abs(x - point[1]))
