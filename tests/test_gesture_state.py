"""Gesture state machine tests: open palm + swipe + cooldown, with synthetic hands."""

import pytest

import config
from src.gesture.gesture_state import (
    MSG_MULTIPLE_HANDS,
    MSG_NO_HAND,
    MSG_NO_HAND_ANY,
    MSG_OPEN_HAND,
    GestureState,
    GestureStateMachine,
)
from src.gesture.hand_tracking import MovementTracker, get_hand_center
from src.gesture.swipe_detector import Gesture, SwipeDetector
from src.hand.hand_detector import Hand
from tests.hand_factory import make_hand

DT = 1 / 30  # 30 FPS


def hand_at(x, y=450.0, open_hand=True):
    points = make_hand(offset=(x, y)) if open_hand else make_hand(extended=(), offset=(x, y))
    return Hand(points.astype("float32"), "Right", 0.95)


def machine(**kwargs):
    """Five-finger mode by default here (the spec's original rules); pass palm=False for any-hand mode."""
    detector = SwipeDetector(min_distance=150, max_duration=1.0, horizontal_ratio=1.0, mirrored=True)
    return GestureStateMachine(detector, cooldown_seconds=kwargs.get("cooldown", 1.0),
                               open_palm_min_frames=kwargs.get("min_frames", 3),
                               require_open_palm=kwargs.get("palm", True))


def feed(sm, xs, t0=0.0, open_hand=True, ys=None):
    """Feed one hand along xs; return (statuses, next timestamp)."""
    statuses = []
    ys = ys or [450.0] * len(xs)
    for i, (x, y) in enumerate(zip(xs, ys, strict=True)):
        statuses.append(sm.update([hand_at(x, y, open_hand)], t0 + i * DT))
    return statuses, t0 + len(xs) * DT


def gestures(statuses):
    return [s.gesture for s in statuses if s.gesture]


def sweep(start, end, steps=10):
    return [start + (end - start) * i / steps for i in range(steps + 1)]


# -- hand center ------------------------------------------------------------------

def test_hand_center_is_palm_center_and_follows_hand():
    cx, cy = get_hand_center(make_hand(offset=(640, 500)))
    cx2, _ = get_hand_center(make_hand(offset=(740, 500)))
    assert 560 < cx < 700 and cy < 500  # palm is above the wrist
    assert cx2 - cx == pytest.approx(100)


def test_hand_center_ignores_finger_state():
    open_center = get_hand_center(make_hand())
    fist_center = get_hand_center(make_hand(extended=()))
    assert open_center == pytest.approx(fist_center)


def test_movement_tracker():
    tracker = MovementTracker()
    assert tracker.current is None and tracker.frame_delta == (0.0, 0.0)
    tracker.update((100, 200))
    tracker.update((90, 205))
    assert tracker.previous_x == 100 and tracker.current_x == 90
    assert tracker.frame_delta == (-10, 5)


# -- states --------------------------------------------------------------------------

def test_no_hand_is_idle():
    status = machine().update([], 0.0)
    assert status.state == GestureState.IDLE
    assert status.message == MSG_NO_HAND


def test_multiple_hands_are_rejected():
    status = machine().update([hand_at(400), hand_at(900)], 0.0)
    assert status.state == GestureState.HAND_DETECTED
    assert status.message == MSG_MULTIPLE_HANDS


def test_open_palm_then_tracking():
    statuses, _ = feed(machine(min_frames=3), [640] * 4)
    assert [s.state for s in statuses] == [
        GestureState.OPEN_PALM, GestureState.OPEN_PALM, GestureState.TRACKING, GestureState.TRACKING,
    ]
    assert statuses[-1].fingers == 5 and statuses[-1].open_palm


def test_next_gesture_full_cycle():
    sm = machine()
    t = 0.0
    for x in [800] * 3 + sweep(800, 500):
        fired = sm.update([hand_at(x)], t)
        t += DT
        if fired.gesture:
            break
    assert fired.gesture == Gesture.NEXT
    assert fired.state == GestureState.SWIPE_DETECTED
    sm.mark_executed()
    assert sm.state == GestureState.COMMAND_EXECUTED

    status = sm.update([hand_at(500)], t)
    assert status.state == GestureState.COOLDOWN and status.cooldown_remaining > 0

    status = sm.update([], t + 1.5)  # cooldown over
    assert status.state == GestureState.IDLE


def test_previous_gesture():
    statuses, _ = feed(machine(), [400] * 3 + sweep(400, 700))
    assert gestures(statuses) == [Gesture.PREVIOUS]


# -- spec: invalid movements --------------------------------------------------------

def test_closed_hand_swipe_is_no_command():
    statuses, _ = feed(machine(), [800] * 3 + sweep(800, 400), open_hand=False)
    assert gestures(statuses) == []
    assert statuses[-1].message == MSG_OPEN_HAND


def test_vertical_movement_is_no_command():
    statuses, _ = feed(machine(), [640] * 14, ys=[300.0] * 3 + sweep(300, 600))
    assert gestures(statuses) == []


def test_small_movement_is_no_command():
    statuses, _ = feed(machine(), [500] * 3 + sweep(500, 530))
    assert gestures(statuses) == []


# -- spec: cooldown -----------------------------------------------------------------

def test_only_first_gesture_executes_during_cooldown():
    sm = machine(cooldown=1.0)
    # three quick swipes back and forth within ~1 s
    xs = [800] * 3 + sweep(800, 500, 5) + sweep(500, 800, 5) + sweep(800, 500, 5)
    statuses, t = feed(sm, xs)
    assert gestures(statuses) == [Gesture.NEXT]
    assert any(s.state == GestureState.COOLDOWN for s in statuses)

    # after the cooldown a new swipe works again
    later, _ = feed(sm, [800] * 3 + sweep(800, 500), t0=t + 1.0)
    assert gestures(later) == [Gesture.NEXT]


def test_hand_holding_still_after_swipe_does_not_repeat():
    sm = machine(cooldown=0.5)
    statuses, _ = feed(sm, [800] * 3 + sweep(800, 500) + [500] * 60)
    assert gestures(statuses) == [Gesture.NEXT]


def test_reset():
    sm = machine()
    feed(sm, [800] * 3 + sweep(800, 500))
    sm.reset()
    assert sm.state == GestureState.IDLE and not sm.in_cooldown(0.5)


# -- any-hand mode (default: no five-finger requirement) -------------------------------

def test_any_hand_mode_is_the_default():
    assert config.REQUIRE_OPEN_PALM is False
    assert GestureStateMachine().require_open_palm is False


def test_any_hand_mode_closed_hand_swipe_is_next():
    statuses, _ = feed(machine(palm=False), [800] * 3 + sweep(800, 500), open_hand=False)
    assert gestures(statuses) == [Gesture.NEXT]


def test_any_hand_mode_previous_with_open_hand():
    statuses, _ = feed(machine(palm=False), [400] * 3 + sweep(400, 700))
    assert gestures(statuses) == [Gesture.PREVIOUS]


def test_any_hand_mode_states_and_message():
    sm = machine(palm=False, min_frames=3)
    statuses, _ = feed(sm, [640] * 4, open_hand=False)
    assert [s.state for s in statuses] == [
        GestureState.HAND_DETECTED, GestureState.HAND_DETECTED, GestureState.TRACKING, GestureState.TRACKING,
    ]
    assert statuses[-1].ready
    assert sm.update([], 1.0).message == MSG_NO_HAND_ANY


def test_any_hand_mode_still_rejects_vertical_small_and_two_hands():
    assert gestures(feed(machine(palm=False), [640] * 14, ys=[300.0] * 3 + sweep(300, 600))[0]) == []
    assert gestures(feed(machine(palm=False), [500] * 3 + sweep(500, 530))[0]) == []
    status = machine(palm=False).update([hand_at(400), hand_at(900)], 0.0)
    assert status.message == MSG_MULTIPLE_HANDS and status.gesture is None


def test_any_hand_mode_cooldown_still_applies():
    xs = [800] * 3 + sweep(800, 500, 5) + sweep(500, 800, 5) + sweep(800, 500, 5)
    statuses, _ = feed(machine(palm=False, cooldown=1.0), xs, open_hand=False)
    assert gestures(statuses) == [Gesture.NEXT]


# -- fast swipes ------------------------------------------------------------------------

def test_hand_entering_already_moving_still_swipes():
    # no still frames first: the hand appears mid-movement and crosses in 6 frames (0.2 s)
    statuses, _ = feed(machine(palm=False, min_frames=3), sweep(900, 500, 5), open_hand=False)
    assert gestures(statuses) == [Gesture.NEXT]


def test_single_frame_false_hand_never_swipes():
    sm = machine(palm=False, min_frames=3)
    assert sm.update([hand_at(900)], 0.0).gesture is None
    assert sm.update([], DT).gesture is None
    assert sm.update([hand_at(500)], 2 * DT).gesture is None   # only 2 sightings: not stable yet


def test_blurred_gap_mid_swipe_keeps_the_swipe():
    sm = machine(palm=False, min_frames=3)
    statuses, t = feed(sm, [900, 880, 860], open_hand=False)
    for i in range(6):                     # 0.2 s motion blur: no hand detected
        statuses.append(sm.update([], t + i * DT))
    statuses.append(sm.update([hand_at(600, open_hand=False)], t + 6 * DT))
    assert gestures(statuses) == [Gesture.NEXT]


def test_far_small_hand_swipes_with_short_movement():
    detector = SwipeDetector(min_distance=150, max_duration=1.0, horizontal_ratio=1.0, mirrored=True,
                             distance_palms=1.5, min_distance_far=40)
    sm = GestureStateMachine(detector, cooldown_seconds=1.0, open_palm_min_frames=3, require_open_palm=False)

    def small(x):  # presenter far away: palm about 32 px
        return Hand(make_hand(offset=(x, 400), scale=0.3).astype("float32"), "Right", 0.9)

    statuses = [sm.update([small(x)], i * DT) for i, x in enumerate([700] * 3 + sweep(700, 640, 6))]
    assert gestures(statuses) == [Gesture.NEXT]
    assert statuses[3].required_distance < 60
