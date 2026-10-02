"""Open-palm / finger-state tests on synthetic hands."""

import numpy as np
import pytest

from src.gesture.finger_detector import (
    FINGER_NAMES,
    analyze_hand,
    count_extended_fingers,
    is_open_palm,
    joint_angle,
)
from src.hand.hand_detector import Hand
from tests.hand_factory import FINGERS, make_hand

# -- spec cases ---------------------------------------------------------------

def test_five_fingers_open_is_open_palm():
    hand = make_hand()
    assert count_extended_fingers(hand) == 5
    assert is_open_palm(hand) is True


def test_closed_hand_is_not_open_palm():
    fist = make_hand(extended=())
    assert count_extended_fingers(fist) == 0
    assert is_open_palm(fist) is False


def test_three_fingers_is_not_open_palm():
    hand = make_hand(extended=("thumb", "index", "middle"))
    assert count_extended_fingers(hand) == 3
    assert is_open_palm(hand) is False


# -- each finger matters ------------------------------------------------------

@pytest.mark.parametrize("closed", FINGERS)
def test_any_single_closed_finger_breaks_open_palm(closed):
    hand = make_hand(extended=tuple(f for f in FINGERS if f != closed))
    pose = analyze_hand(hand)
    assert pose.count == 4
    assert not pose.finger(closed).extended
    assert not pose.is_open_palm


def test_straight_thumb_tucked_across_palm_is_not_extended():
    pose = analyze_hand(make_hand(extended=("index", "middle", "ring", "pinky")))
    assert not pose.finger("thumb").extended
    assert not pose.is_open_palm


def test_pointing_and_peace_sign_are_not_open_palm():
    assert not is_open_palm(make_hand(extended=("index",)))
    assert not is_open_palm(make_hand(extended=("index", "middle")))


# -- robustness ---------------------------------------------------------------

@pytest.mark.parametrize("rotation", [-90, -45, -20, 0, 20, 45, 90, 135, 180])
def test_open_palm_is_rotation_invariant(rotation):
    assert is_open_palm(make_hand(rotation_deg=rotation))
    assert not is_open_palm(make_hand(extended=(), rotation_deg=rotation))


@pytest.mark.parametrize("scale", [0.4, 1.0, 2.5])  # far from / near the camera
def test_open_palm_is_scale_invariant(scale):
    assert is_open_palm(make_hand(scale=scale))
    assert not is_open_palm(make_hand(extended=(), scale=scale))


def test_left_hand_mirror_image_works():
    assert is_open_palm(make_hand(mirror=True))
    assert count_extended_fingers(make_hand(extended=("thumb", "index"), mirror=True)) == 2


def test_naturally_relaxed_open_hand_still_counts():
    assert is_open_palm(make_hand(relaxed=True, rotation_deg=15))


@pytest.mark.parametrize("seed", range(5))
def test_small_landmark_jitter_does_not_change_result(seed):
    assert is_open_palm(make_hand(noise=1.5, seed=seed))
    assert not is_open_palm(make_hand(extended=(), noise=1.5, seed=seed))


# -- API ------------------------------------------------------------------------

def test_accepts_hand_object_and_2d_points():
    points = make_hand()
    assert is_open_palm(Hand(points.astype(np.float32), "Right", 0.9))
    assert is_open_palm(points[:, :2])


def test_pose_reports_all_fingers_in_order():
    pose = analyze_hand(make_hand(extended=("thumb", "pinky")))
    assert tuple(f.name for f in pose.fingers) == FINGER_NAMES
    assert [f.extended for f in pose.fingers] == [True, False, False, False, True]
    assert pose.palm_size > 0


def test_wrong_number_of_landmarks_raises():
    with pytest.raises(ValueError, match="21 landmarks"):
        is_open_palm(np.zeros((20, 3)))


def test_joint_angle():
    a, b = np.array([0.0, 0.0]), np.array([1.0, 0.0])
    assert joint_angle(a, b, np.array([2.0, 0.0])) == pytest.approx(180.0)
    assert joint_angle(a, b, np.array([1.0, 1.0])) == pytest.approx(90.0)
    assert joint_angle(a, a, b) == 0.0  # degenerate
