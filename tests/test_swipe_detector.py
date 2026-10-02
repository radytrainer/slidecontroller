"""Swipe detector tests with simulated coordinates (mirrored frame, 1280 px wide)."""

import pytest

from src.gesture.swipe_detector import Direction, Gesture, SwipeDetector


def run(detector, xs, ys=None, dt=0.05, t0=0.0, scales=None):
    """Feed a path; return the list of swipes produced. ``scales`` = palm size in px."""
    ys = ys or [360.0] * len(xs)
    swipes = []
    for i, (x, y) in enumerate(zip(xs, ys, strict=True)):
        swipe = detector.update(x, y, t0 + i * dt, scale=scales)
        if swipe:
            swipes.append(swipe)
    return swipes


def path(start, end, steps=8):
    return [start + (end - start) * i / steps for i in range(steps + 1)]


@pytest.fixture
def detector():
    return SwipeDetector(min_distance=150, max_duration=1.0, horizontal_ratio=1.0, mirrored=True)


# -- spec cases ---------------------------------------------------------------

def test_right_to_left_is_next(detector):
    swipes = run(detector, path(700, 400))
    assert len(swipes) == 1
    swipe = swipes[0]
    assert swipe.direction == Direction.RIGHT_TO_LEFT
    assert swipe.gesture == Gesture.NEXT
    assert swipe.delta_x <= -150


def test_left_to_right_is_previous(detector):
    swipes = run(detector, path(400, 700))
    assert [s.gesture for s in swipes] == [Gesture.PREVIOUS]
    assert swipes[0].direction == Direction.LEFT_TO_RIGHT


def test_small_movement_is_no_action(detector):
    assert run(detector, path(500, 530)) == []


def test_vertical_movement_is_no_action(detector):
    # delta_x = 20, delta_y = 200
    assert run(detector, path(500, 520), ys=path(300, 500)) == []


def test_big_vertical_with_some_horizontal_is_no_action(detector):
    # 180 px sideways but 300 px down: more vertical than horizontal
    assert run(detector, path(600, 420), ys=path(200, 500)) == []


def test_diagonal_but_mostly_horizontal_still_counts(detector):
    swipes = run(detector, path(800, 500), ys=path(300, 400))
    assert [s.gesture for s in swipes] == [Gesture.NEXT]


# -- timing -------------------------------------------------------------------

def test_slow_movement_is_no_action(detector):
    # 300 px over 3 s: never 150 px within any 1 s window
    assert run(detector, path(700, 400, steps=30), dt=0.1) == []


def test_fast_movement_counts(detector):
    swipes = run(detector, path(700, 400, steps=4), dt=0.03)
    assert [s.gesture for s in swipes] == [Gesture.NEXT]
    assert swipes[0].duration <= 1.0


def test_swipe_reports_distance_and_duration(detector):
    swipe = run(detector, [700, 650, 600, 540], dt=0.1)[0]
    assert swipe.start_x == 700 and swipe.current_x == 540
    assert swipe.distance == pytest.approx(160)
    assert swipe.duration == pytest.approx(0.3)


def test_path_restarts_after_a_swipe(detector):
    # 700 -> 500 fires once; the path restarts, so the remaining 50 px do nothing
    assert len(run(detector, path(700, 500, steps=20), dt=0.01)) == 1
    # 700 -> 300 fires at 550 and again after another full 150 px (at 390).
    # The detector alone would fire twice - the state machine's cooldown prevents that.
    swipes = run(SwipeDetector(150, 1.0, 1.0, True), path(700, 300, steps=40), dt=0.01)
    assert [round(s.current_x) for s in swipes] == [550, 390]


def test_start_is_farthest_point_so_hesitation_does_not_matter(detector):
    # hand pauses, drifts slightly right, then swipes left
    xs = [600, 600, 610, 620, 560, 500, 450]
    assert [s.gesture for s in run(detector, xs)] == [Gesture.NEXT]


# -- lost palm / fast swipes ------------------------------------------------------

def test_brief_loss_is_tolerated(detector):
    detector.update(700, 360, 0.0)
    detector.update(640, 360, 0.05)
    detector.missed(0.1)  # one blurred frame
    assert detector.update(520, 360, 0.15).gesture == Gesture.NEXT


def test_long_loss_resets_tracking():
    detector = SwipeDetector(150, 1.0, 1.0, True, lost_seconds=0.3)
    detector.update(700, 360, 0.0)
    for t in (0.1, 0.2, 0.35):
        detector.missed(t)
    assert not detector.is_tracking
    assert detector.update(520, 360, 0.4) is None


def test_fast_blurred_swipe_with_gap_counts(detector):
    # 30 FPS: hand seen for 2 frames, blurred (lost) for 8 frames = 0.27 s, seen again at the end
    detector.update(900, 360, 0.0)
    detector.update(860, 360, 1 / 30)
    for i in range(2, 10):
        detector.missed(i / 30)
    assert detector.update(420, 360, 10 / 30).gesture == Gesture.NEXT


def test_can_fire_false_records_but_does_not_fire(detector):
    assert detector.update(700, 360, 0.0, can_fire=False) is None
    assert detector.update(500, 360, 0.05, can_fire=False) is None
    assert detector.is_tracking
    # the next allowed frame uses the whole recorded movement
    assert detector.update(490, 360, 0.1).gesture == Gesture.NEXT


# -- far away (small hand) -----------------------------------------------------------

def test_far_hand_needs_less_distance():
    detector = SwipeDetector(150, 1.0, 1.0, True, distance_palms=1.5, min_distance_far=40)
    # palm 30 px (presenter ~4 m away): 1.5 x 30 = 45 px is enough
    swipes = run(detector, path(700, 640), scales=30.0)
    assert [s.gesture for s in swipes] == [Gesture.NEXT]


def test_far_hand_small_jitter_is_still_ignored():
    detector = SwipeDetector(150, 1.0, 1.0, True, distance_palms=1.5, min_distance_far=40)
    assert run(detector, path(700, 670), scales=30.0) == []   # 30 px < 45 px


def test_required_distance_limits():
    detector = SwipeDetector(150, 1.0, 1.0, True, distance_palms=1.5, min_distance_far=40)
    assert detector.required_distance == 150                  # no hand size known
    detector.update(700, 360, 0.0, scale=200.0)               # very close hand
    assert detector.required_distance == 150                  # never more than MIN_SWIPE_DISTANCE
    detector.reset()
    detector.update(700, 360, 0.0, scale=10.0)                # tiny hand
    assert detector.required_distance == 40                   # never below MIN_SWIPE_DISTANCE_FAR


def test_close_hand_behaves_as_before(detector):
    assert run(detector, path(700, 600), scales=120.0) == []  # 100 px < 150 px
    assert len(run(detector, path(700, 540), scales=120.0)) == 1


# -- mirroring & scaling -----------------------------------------------------------

def test_unmirrored_camera_flips_image_direction():
    detector = SwipeDetector(150, 1.0, 1.0, mirrored=False)
    # raw camera: presenter's right -> left appears as image left -> right
    assert run(detector, path(400, 700))[0].gesture == Gesture.NEXT


def test_min_distance_scales_with_frame_width():
    detector = SwipeDetector(min_distance=150, frame_width=640, min_distance_far=40)
    assert detector.min_distance == pytest.approx(75)
    assert detector.min_distance_far == pytest.approx(20)


def test_progress_snapshot(detector):
    assert detector.progress is None
    detector.update(700, 360, 0.0)
    detector.update(640, 370, 0.2)
    progress = detector.progress
    assert progress.start_x == 700 and progress.current_x == 640
    assert progress.delta_x == -60 and progress.delta_y == 10
    assert progress.duration == pytest.approx(0.2)


def test_direction_labels():
    assert Direction.RIGHT_TO_LEFT.value == "RIGHT → LEFT"
    assert Direction.RIGHT_TO_LEFT.ascii == "RIGHT -> LEFT"
