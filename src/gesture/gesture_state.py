"""
Gesture state machine.

Turns the hands detected in each frame into NEXT / PREVIOUS gestures.

By default (config.REQUIRE_OPEN_PALM = False) ANY single hand moving left or
right is a swipe - easiest for presenters. With REQUIRE_OPEN_PALM = True all
five fingers must be open, which avoids accidental swipes from presenters who
talk with their hands. Five-finger mode::

    IDLE ──hand──▶ HAND_DETECTED ──5 fingers──▶ OPEN_PALM ──stable──▶ TRACKING
      ▲                                                                   │
      │                                                        swipe threshold
      │                                                                   ▼
    COOLDOWN ◀── COMMAND_EXECUTED ◀────────────────────────────── SWIPE_DETECTED
      (ignores all swipes for COOLDOWN_SECONDS, then back to IDLE)

Call ``update(hands, timestamp)`` once per frame. When the returned status
has a ``gesture``, execute it and call ``mark_executed()``.
"""

import time
from dataclasses import dataclass
from enum import Enum

import config
from src.gesture.finger_detector import HandPose, analyze_hand
from src.gesture.hand_tracking import get_hand_center
from src.gesture.swipe_detector import Gesture, Swipe, SwipeDetector, SwipeProgress
from src.hand.hand_detector import Hand

MSG_NO_HAND = "Show your open hand to the camera."   # five-finger mode
MSG_NO_HAND_ANY = "Show your hand to the camera."     # any-hand mode (default)
MSG_MULTIPLE_HANDS = "Please use one hand."
MSG_OPEN_HAND = "Open all five fingers to swipe."
MSG_READY = "Ready - swipe to change slides."
MSG_COOLDOWN = "Gesture received."


class GestureState(Enum):
    IDLE = "IDLE"
    HAND_DETECTED = "HAND_DETECTED"
    OPEN_PALM = "OPEN_PALM"
    TRACKING = "TRACKING"
    SWIPE_DETECTED = "SWIPE_DETECTED"
    COMMAND_EXECUTED = "COMMAND_EXECUTED"
    COOLDOWN = "COOLDOWN"


@dataclass(frozen=True)
class GestureStatus:
    """Everything the UI / debug view needs to know about one frame."""

    state: GestureState
    message: str
    hand_count: int = 0
    pose: HandPose | None = None
    center: tuple[float, float] | None = None
    progress: SwipeProgress | None = None
    swipe: Swipe | None = None           # set only on the frame a swipe completes
    cooldown_remaining: float = 0.0
    required_distance: float | None = None   # swipe distance (px) needed for this hand size

    @property
    def gesture(self) -> Gesture | None:
        return self.swipe.gesture if self.swipe else None

    @property
    def fingers(self) -> int:
        return self.pose.count if self.pose else 0

    @property
    def open_palm(self) -> bool:
        return bool(self.pose and self.pose.is_open_palm)

    @property
    def ready(self) -> bool:
        """True while a swipe can be made right now (hand accepted and tracked)."""
        return self.state in (GestureState.TRACKING, GestureState.SWIPE_DETECTED)


class GestureStateMachine:
    def __init__(
        self,
        swipe_detector: SwipeDetector | None = None,
        cooldown_seconds: float | None = None,
        open_palm_min_frames: int | None = None,
        require_open_palm: bool | None = None,
    ):
        self.swipe_detector = swipe_detector or SwipeDetector()
        self.cooldown_seconds = config.COOLDOWN_SECONDS if cooldown_seconds is None else cooldown_seconds
        self.open_palm_min_frames = (
            config.OPEN_PALM_MIN_FRAMES if open_palm_min_frames is None else open_palm_min_frames
        )
        # False (default): any single hand can swipe. True: all five fingers must be open.
        self.require_open_palm = config.REQUIRE_OPEN_PALM if require_open_palm is None else require_open_palm
        self.state = GestureState.IDLE
        self.last_swipe: Swipe | None = None
        self._open_frames = 0
        self._cooldown_until = 0.0

    def reset(self) -> None:
        self.state = GestureState.IDLE
        self.swipe_detector.reset()
        self._open_frames = 0
        self._cooldown_until = 0.0

    def mark_executed(self) -> None:
        """Tell the machine the command for the last gesture was sent."""
        if self.state == GestureState.SWIPE_DETECTED:
            self.state = GestureState.COMMAND_EXECUTED

    def _missed(self, now: float) -> None:
        """No usable hand this frame. A short gap (blur) keeps the swipe and the
        stable-frame count; only when the swipe is dropped does the count restart."""
        self.swipe_detector.missed(now)
        if not self.swipe_detector.is_tracking:
            self._open_frames = 0

    def in_cooldown(self, now: float) -> bool:
        return now < self._cooldown_until

    def update(self, hands: list[Hand], timestamp: float | None = None) -> GestureStatus:
        now = time.monotonic() if timestamp is None else timestamp
        pose = center = None
        if len(hands) == 1:
            pose = analyze_hand(hands[0])
            center = get_hand_center(hands[0])

        def status(state: GestureState, message: str, swipe: Swipe | None = None) -> GestureStatus:
            self.state = state
            return GestureStatus(
                state, message, len(hands), pose, center,
                self.swipe_detector.progress, swipe,
                max(0.0, self._cooldown_until - now),
                self.swipe_detector.required_distance if center else None,
            )

        # Cooldown: ignore every swipe until it has elapsed.
        if self.in_cooldown(now):
            self.swipe_detector.reset()
            self._open_frames = 0
            return status(GestureState.COOLDOWN, MSG_COOLDOWN)

        if not hands:
            self._missed(now)
            return status(GestureState.IDLE, MSG_NO_HAND if self.require_open_palm else MSG_NO_HAND_ANY)

        if len(hands) > 1:
            self._open_frames = 0
            self.swipe_detector.reset()
            return status(GestureState.HAND_DETECTED, MSG_MULTIPLE_HANDS)

        if self.require_open_palm and not pose.is_open_palm:
            self._missed(now)  # tolerate a few blurred frames mid-swipe
            return status(GestureState.HAND_DETECTED, MSG_OPEN_HAND)

        # The hand must be seen for a few frames in a row before a swipe can fire.
        # Its movement is recorded from the first frame, so a fast hand that
        # enters the image already moving still produces a swipe.
        self._open_frames += 1
        stable = self._open_frames >= self.open_palm_min_frames
        swipe = self.swipe_detector.update(center[0], center[1], now, scale=pose.palm_size, can_fire=stable)
        if swipe is None:
            if not stable:
                waiting = GestureState.OPEN_PALM if self.require_open_palm else GestureState.HAND_DETECTED
                return status(waiting, MSG_READY)
            return status(GestureState.TRACKING, MSG_READY)

        self.last_swipe = swipe
        self._cooldown_until = now + self.cooldown_seconds
        self._open_frames = 0
        return status(GestureState.SWIPE_DETECTED, f"{swipe.gesture.value} ({swipe.direction.value})", swipe)
