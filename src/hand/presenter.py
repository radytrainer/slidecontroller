"""
Presenter focus and long-distance zoom.

``PresenterFocus`` (pure logic, no MediaPipe) decides which ONE hand controls
the slides when several people are in view:

1. Presenter: the biggest person (widest shoulders) found by the pose model.
   Once chosen, the same person is followed from frame to frame and kept
   for PRESENTER_LOCK_SECONDS when briefly hidden - someone else walking
   through the image does not take over.
2. Hand: only hands whose wrist is within PRESENTER_REACH shoulder widths of
   the presenter count; other people's hands are ignored. Without a visible
   body (e.g. only a hand close to the camera) every hand is a candidate.
3. Of the candidates, the hand chosen last time is followed (nearest to where
   it was, within HAND_LOCK_RADIUS palm sizes); a new choice is the biggest.

``PresenterHandDetector`` runs the models and uses ``PresenterFocus``. It has
the same ``detect(frame) -> list[Hand]`` interface as ``HandDetector`` and
returns at most one hand: the presenter's. When the presenter stands far away
it searches for hands in a zoomed square around them, because in the full
image a distant hand is too small for the hand model to find.
"""

import time
from dataclasses import dataclass

import numpy as np

import config
from src.hand.hand_detector import Hand, HandDetectionError, HandDetector
from src.hand.hand_detector import HandLandmark as L
from src.hand.pose_detector import Body, PoseDetector
from src.utils.logger import get_logger

log = get_logger(__name__)

PALM_LANDMARKS = [L.WRIST, L.INDEX_MCP, L.MIDDLE_MCP, L.RING_MCP, L.PINKY_MCP]

# A followed person is the same person when their shoulders moved less than
# this many shoulder widths since the last detection.
PRESENTER_MAX_MOVE = 1.5


def palm_center(hand: Hand) -> tuple[float, float]:
    x, y = hand.landmarks[PALM_LANDMARKS, :2].mean(axis=0)
    return float(x), float(y)


def palm_size(hand: Hand) -> float:
    """Wrist -> middle knuckle in pixels (same measure as finger_detector)."""
    wrist, knuckle = hand.landmarks[L.WRIST, :2], hand.landmarks[L.MIDDLE_MCP, :2]
    return max(1.0, float(np.hypot(*(wrist - knuckle))))


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


@dataclass(frozen=True)
class FocusResult:
    """What the presenter focus saw in one frame (for the debug view)."""

    hand: Hand | None = None
    presenter: Body | None = None
    bodies: tuple[Body, ...] = ()
    ignored: tuple[Hand, ...] = ()
    zoom: tuple[int, int, int] | None = None   # (x, y, side) of the zoomed square
    frame_long_side: float = 0.0

    @property
    def zoom_factor(self) -> float | None:
        """How much bigger a hand looks to the hand model thanks to the zoom."""
        return None if self.zoom is None else self.frame_long_side / self.zoom[2]


class PresenterFocus:
    """Chooses the presenter and their hand (see module docstring)."""

    def __init__(
        self,
        reach: float | None = None,
        lock_seconds: float | None = None,
        hand_lock_radius: float | None = None,
    ):
        self.reach = config.PRESENTER_REACH if reach is None else reach
        self.lock_seconds = config.PRESENTER_LOCK_SECONDS if lock_seconds is None else lock_seconds
        self.hand_lock_radius = config.HAND_LOCK_RADIUS if hand_lock_radius is None else hand_lock_radius
        self._presenter: Body | None = None
        self._presenter_time = -1e9
        self._hand: tuple[tuple[float, float], float] | None = None   # (centre, palm size)
        self._hand_time = -1e9

    def reset(self) -> None:
        self._presenter, self._hand = None, None

    # -- presenter -------------------------------------------------------------

    def choose_presenter(self, bodies: list[Body], now: float) -> Body | None:
        """The presenter's body: followed while visible, remembered while hidden."""
        locked = self._presenter is not None and now - self._presenter_time <= self.lock_seconds
        chosen = None
        if locked:
            last = self._presenter
            near = [b for b in bodies
                    if last.distance_to(b.shoulder_center) <= PRESENTER_MAX_MOVE]
            if near:
                chosen = min(near, key=lambda b: _distance(b.shoulder_center, last.shoulder_center))
            else:
                return last   # hidden for a moment: keep the last known position
        elif bodies:
            chosen = max(bodies, key=lambda b: b.shoulder_width)

        if chosen is None:
            self._presenter = None
            return None
        self._presenter, self._presenter_time = chosen, now
        return chosen

    # -- hand ------------------------------------------------------------------

    def choose_hand(
        self, hands: list[Hand], presenter: Body | None, now: float
    ) -> tuple[Hand | None, list[Hand]]:
        """Return (the presenter's hand or None, the ignored hands)."""
        if presenter is not None:
            candidates = [h for h in hands if presenter.distance_to(h.point(L.WRIST)) <= self.reach]
        else:
            candidates = list(hands)

        chosen = None
        locked = self._hand is not None and now - self._hand_time <= self.lock_seconds
        if locked and candidates:
            center, size = self._hand
            nearest = min(candidates, key=lambda h: _distance(palm_center(h), center))
            if _distance(palm_center(nearest), center) <= self.hand_lock_radius * size:
                chosen = nearest
        if chosen is None and candidates and (not locked or presenter is not None):
            # A new choice. With a known presenter any of their hands is fine;
            # without one, a locked hand is not replaced by someone else's.
            chosen = max(candidates, key=palm_size)

        if chosen is not None:
            self._hand, self._hand_time = (palm_center(chosen), palm_size(chosen)), now
        return chosen, [h for h in hands if h is not chosen]


class PresenterHandDetector:
    """Hand detection focused on the presenter, with zoom for far distances."""

    def __init__(
        self,
        hand_detector_factory=HandDetector,
        pose_detector_factory=PoseDetector,
        focus: PresenterFocus | None = None,
    ):
        self._hand_factory = hand_detector_factory
        self._hands = hand_detector_factory()
        self._zoom_hands = None   # second hand detector for the zoomed square, created on first use
        self._pose = None
        if config.PRESENTER_FOCUS or config.LONG_DISTANCE_ZOOM:
            try:
                self._pose = pose_detector_factory()
            except HandDetectionError as exc:
                # Still works without it: every hand is a candidate, no zoom.
                log.warning("Presenter focus / zoom disabled: %s", exc)
        self.focus = focus or PresenterFocus()
        self.last = FocusResult()
        self._bodies: list[Body] = []
        self._frame_count = 0
        self._zoom_state: tuple[float, float, float] | None = None   # smoothed (cx, cy, side)

    def detect(self, frame_bgr: np.ndarray, timestamp: float | None = None) -> list[Hand]:
        now = time.monotonic() if timestamp is None else timestamp
        height, width = frame_bgr.shape[:2]

        presenter = None
        if self._pose is not None:
            # People move slowly compared with hands: the pose model runs every
            # POSE_EVERY_N_FRAMES frames and its result is reused in between.
            if self._frame_count % max(1, config.POSE_EVERY_N_FRAMES) == 0:
                self._bodies = self._pose.detect(frame_bgr)
            presenter = self.focus.choose_presenter(self._bodies, now)
        self._frame_count += 1

        zoom = self._zoom_square(presenter, width, height) if config.LONG_DISTANCE_ZOOM else None
        if zoom is not None:
            x, y, side = zoom
            if self._zoom_hands is None:
                self._zoom_hands = self._hand_factory()
            hands = [_shift(hand, x, y) for hand in self._zoom_hands.detect(frame_bgr[y:y + side, x:x + side])]
        else:
            hands = self._hands.detect(frame_bgr)

        if config.PRESENTER_FOCUS:
            hand, ignored = self.focus.choose_hand(hands, presenter, now)
            result = [hand] if hand is not None else []
        else:
            hand, ignored, result = None, [], hands   # every hand, as before
        self.last = FocusResult(hand, presenter, tuple(self._bodies), tuple(ignored), zoom,
                                float(max(width, height)))
        return result

    def _zoom_square(self, presenter: Body | None, width: int, height: int) -> tuple[int, int, int] | None:
        """The square around a far presenter to search for hands in, or None (use the full frame)."""
        if presenter is None:
            self._zoom_state = None
            return None
        size = presenter.shoulder_width
        side = max(float(config.ZOOM_MIN_SIZE), config.ZOOM_BODY_SPAN * size)
        # Hysteresis so the zoom does not switch on and off at the boundary.
        limit = height if self._zoom_state is not None else 0.9 * height
        if side >= limit:
            self._zoom_state = None
            return None
        cx, cy = presenter.shoulder_center
        target = (cx, cy + 0.25 * size, side)   # a little below the shoulders: chest height
        if self._zoom_state is None:
            self._zoom_state = target
        else:
            a = config.ZOOM_SMOOTHING
            self._zoom_state = tuple(old + a * (new - old) for old, new in zip(self._zoom_state, target, strict=True))
        cx, cy, side = self._zoom_state
        side = int(min(side, height, width))
        x = int(np.clip(cx - side / 2, 0, width - side))
        y = int(np.clip(cy - side / 2, 0, height - side))
        return x, y, side

    def close(self) -> None:
        for detector in (self._hands, self._zoom_hands, self._pose):
            if detector is not None:
                detector.close()

    def __enter__(self) -> "PresenterHandDetector":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _shift(hand: Hand, dx: float, dy: float) -> Hand:
    """Move a hand found in a crop back to full-frame pixel coordinates."""
    points = hand.landmarks.copy()
    points[:, 0] += dx
    points[:, 1] += dy
    return Hand(points, hand.handedness, hand.score)
