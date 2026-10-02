"""Presenter focus and long-distance zoom tests (synthetic bodies and hands, no models)."""

import numpy as np
import pytest

import config
from src.hand.hand_detector import Hand, HandDetectionError
from src.hand.pose_detector import NUM_POSE_LANDMARKS, Body, PoseLandmark
from src.hand.presenter import PresenterFocus, PresenterHandDetector, palm_center, palm_size
from tests.hand_factory import make_hand

FRAME = np.zeros((720, 1280, 3), np.uint8)


def body(cx, cy=300.0, width=100.0, visibility=1.0):
    """A person whose shoulders are centred at (cx, cy), ``width`` px apart."""
    points = np.zeros((NUM_POSE_LANDMARKS, 3), np.float32)
    points[:, 2] = visibility
    points[PoseLandmark.LEFT_SHOULDER, :2] = (cx + width / 2, cy)
    points[PoseLandmark.RIGHT_SHOULDER, :2] = (cx - width / 2, cy)
    return Body(points)


def hand(x, y=400.0, scale=1.0, score=0.9):
    """A hand whose WRIST is at (x, y)."""
    return Hand(make_hand(offset=(x, y), scale=scale).astype("float32"), "Right", score)


@pytest.fixture
def focus():
    return PresenterFocus(reach=2.5, lock_seconds=1.0, hand_lock_radius=6.0)


# -- presenter ---------------------------------------------------------------------------

def test_biggest_person_is_the_presenter(focus):
    near, far = body(900, width=180), body(300, width=60)
    assert focus.choose_presenter([far, near], 0.0) is near


def test_presenter_is_followed_even_when_someone_bigger_appears(focus):
    focus.choose_presenter([body(400, width=100)], 0.0)
    walker = body(1000, width=200)            # someone closer to the camera walks in
    moved = body(430, width=100)              # the presenter moved a little
    assert focus.choose_presenter([walker, moved], 0.1) is moved


def test_hidden_presenter_is_remembered_then_released(focus):
    presenter = body(400)
    focus.choose_presenter([presenter], 0.0)
    other = body(1000, width=150)
    assert focus.choose_presenter([other], 0.5) is presenter   # hidden briefly: keep the last position
    assert focus.choose_presenter([other], 1.5) is other       # gone too long: choose again


def test_no_people(focus):
    assert focus.choose_presenter([], 0.0) is None


# -- hand ----------------------------------------------------------------------------------

def test_only_hands_within_reach_of_the_presenter_count(focus):
    presenter = body(400, width=100)          # reach = 250 px from the shoulder centre
    mine, audience = hand(450, 350), hand(1100, 350, scale=1.5)
    chosen, ignored = focus.choose_hand([audience, mine], presenter, 0.0)
    assert chosen is mine and ignored == [audience]


def test_someone_elses_hand_alone_is_ignored(focus):
    chosen, ignored = focus.choose_hand([hand(1100, 350)], body(400), 0.0)
    assert chosen is None and len(ignored) == 1


def test_without_body_the_biggest_hand_is_chosen(focus):
    small, big = hand(300, scale=0.5), hand(900, scale=1.2)
    assert focus.choose_hand([small, big], None, 0.0)[0] is big


def test_without_body_the_chosen_hand_is_followed(focus):
    focus.choose_hand([hand(400)], None, 0.0)
    other = hand(1250, scale=1.5)             # a bigger hand appears far away (> 6 palms)
    moved = hand(470)                         # mine moved 70 px (fast swipe frame)
    assert focus.choose_hand([other, moved], None, 0.03)[0] is moved
    # my hand blurs away: the other hand still does not take over during the lock
    assert focus.choose_hand([other], None, 0.2)[0] is None
    # after the lock time the other hand may be chosen
    assert focus.choose_hand([other], None, 2.0)[0] is other


def test_presenters_other_hand_can_take_over(focus):
    presenter = body(640, cy=300, width=120)
    focus.choose_hand([hand(560, 380)], presenter, 0.0)
    # left hand lowered, right hand raised - far from the last hand but within the presenter's reach
    far_right = hand(900, 380)
    assert focus.choose_hand([far_right], presenter, 0.1)[0] is far_right


def test_palm_helpers():
    h = hand(400, 400)
    _, y = palm_center(h)
    assert y < 400                            # palm is above the wrist
    assert palm_size(h) == pytest.approx(np.hypot(10, 105), rel=0.01)


# -- detector with zoom ------------------------------------------------------------------------

class FakeHands:
    """Returns the same hands on every call; remembers the image sizes it was given."""

    def __init__(self, hands=()):
        self.hands, self.shapes, self.closed = list(hands), [], False

    def detect(self, image):
        self.shapes.append(image.shape[:2])
        return list(self.hands)

    def close(self):
        self.closed = True


class FakePose:
    def __init__(self, bodies):
        self.bodies, self.calls, self.closed = bodies, 0, False

    def detect(self, frame):
        self.calls += 1
        return list(self.bodies)

    def close(self):
        self.closed = True


def make_detector(bodies, full_hands=(), zoom_hands=()):
    """First hand detector created = full frame, second = zoomed square."""
    made = []

    def hand_factory():
        fake = FakeHands(zoom_hands if made else full_hands)
        made.append(fake)
        return fake

    return PresenterHandDetector(hand_factory, lambda: FakePose(bodies)), made


@pytest.fixture(autouse=True)
def pose_every_frame(monkeypatch):
    monkeypatch.setattr(config, "POSE_EVERY_N_FRAMES", 1)
    monkeypatch.setattr(config, "PRESENTER_FOCUS", True)
    monkeypatch.setattr(config, "LONG_DISTANCE_ZOOM", True)


def test_far_presenter_uses_zoomed_square():
    # far away: shoulders 60 px apart -> square of 5 x 60 = 300 px around them
    det, made = make_detector([body(900, cy=300, width=60)], zoom_hands=[hand(150, 170, scale=0.3)])
    result = det.detect(FRAME, 0.0)
    full, zoom = made
    assert full.shapes == [] and zoom.shapes == [(300, 300)]
    x, y, side = det.last.zoom
    assert side == 300 and det.last.zoom_factor == pytest.approx(1280 / 300)
    # the hand found in the square is moved back to full-frame coordinates
    assert len(result) == 1
    assert result[0].point(0) == pytest.approx((x + 150, y + 170))


def test_close_presenter_uses_full_frame():
    det, made = make_detector([body(640, cy=400, width=250)], full_hands=[hand(700, 450)])
    assert len(det.detect(FRAME, 0.0)) == 1
    assert det.last.zoom is None and made[0].shapes == [(720, 1280)]
    assert len(made) == 1                     # zoom detector never created


def test_audience_hand_is_filtered_by_detector():
    det, _ = make_detector([body(300, cy=300, width=250)], full_hands=[hand(1150, 400)])
    assert det.detect(FRAME, 0.0) == []
    assert len(det.last.ignored) == 1 and det.last.presenter is not None


def test_zoom_square_stays_inside_frame():
    det, _ = make_detector([body(1270, cy=10, width=60)])
    det.detect(FRAME, 0.0)
    x, y, side = det.last.zoom
    assert 0 <= x and x + side <= 1280 and 0 <= y and y + side <= 720


def test_zoom_follows_presenter_smoothly():
    bodies = [body(600, width=60)]
    det, _ = make_detector(bodies)
    det.detect(FRAME, 0.0)
    x0 = det.last.zoom[0]
    bodies[0] = body(650, width=60)           # presenter walked 50 px
    det._pose.bodies = bodies
    det.detect(FRAME, 0.1)
    x1 = det.last.zoom[0]
    assert x0 < x1 < x0 + 50                  # moves towards them, not in one jump


def test_pose_runs_every_n_frames(monkeypatch):
    monkeypatch.setattr(config, "POSE_EVERY_N_FRAMES", 2)
    pose = FakePose([])
    det = PresenterHandDetector(FakeHands, lambda: pose)
    for i in range(6):
        det.detect(FRAME, i / 30)
    assert pose.calls == 3


def test_without_pose_model_all_hands_are_candidates():
    def broken():
        raise HandDetectionError("no pose model")

    det = PresenterHandDetector(lambda: FakeHands([hand(300, scale=0.5), hand(900)]), broken)
    result = det.detect(FRAME, 0.0)
    assert len(result) == 1 and det.last.presenter is None


def test_focus_off_returns_every_hand(monkeypatch):
    monkeypatch.setattr(config, "PRESENTER_FOCUS", False)
    monkeypatch.setattr(config, "LONG_DISTANCE_ZOOM", False)
    det = PresenterHandDetector(lambda: FakeHands([hand(300), hand(900)]), lambda: FakePose([]))
    assert len(det.detect(FRAME, 0.0)) == 2


def test_close_closes_all_models():
    det, made = make_detector([body(900, width=60)])
    det.detect(FRAME, 0.0)
    pose = det._pose
    det.close()
    assert len(made) == 2 and all(m.closed for m in made) and pose.closed
