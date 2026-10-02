"""Hand detector tests (use the real MediaPipe model; no webcam needed)."""

from types import SimpleNamespace

import numpy as np
import pytest

import config
from src.hand.hand_detector import (
    FINGERTIPS,
    HAND_CONNECTIONS,
    NUM_LANDMARKS,
    Hand,
    HandDetectionError,
    HandDetector,
    HandLandmark,
    draw_hand,
    ensure_model,
    to_hands,
)


def fake_result(hands):
    """Build an object shaped like HandLandmarkerResult. ``hands`` = [(label, score, x, y)]."""
    return SimpleNamespace(
        hand_landmarks=[
            [SimpleNamespace(x=x, y=y, z=-0.01) for _ in range(NUM_LANDMARKS)] for _, _, x, y in hands
        ],
        handedness=[[SimpleNamespace(category_name=label, score=score)] for label, score, _, _ in hands],
    )


@pytest.fixture(scope="module")
def detector():
    with HandDetector() as det:
        yield det


def test_there_are_21_landmarks_and_valid_connections():
    assert NUM_LANDMARKS == 21
    assert HandLandmark.WRIST == 0 and HandLandmark.PINKY_TIP == 20
    assert len(FINGERTIPS) == 5
    assert all(0 <= a < 21 and 0 <= b < 21 for a, b in HAND_CONNECTIONS)
    # every landmark is connected to the skeleton
    assert {i for pair in HAND_CONNECTIONS for i in pair} == set(range(21))


def test_to_hands_converts_normalized_to_pixels():
    hands = to_hands(fake_result([("Right", 0.9, 0.5, 0.25)]), width=1280, height=720)
    assert len(hands) == 1
    hand = hands[0]
    assert hand.landmarks.shape == (21, 3)
    assert hand.point(HandLandmark.WRIST) == pytest.approx((640.0, 180.0))
    assert hand.handedness == "Right"
    assert hand.score == pytest.approx(0.9)


def test_to_hands_sorts_most_confident_first():
    hands = to_hands(fake_result([("Left", 0.6, 0.2, 0.5), ("Right", 0.95, 0.8, 0.5)]), 1280, 720)
    assert [h.handedness for h in hands] == ["Right", "Left"]


def test_to_hands_empty_result():
    assert to_hands(fake_result([]), 1280, 720) == []


def test_blank_frame_has_no_hands(detector):
    frame = np.zeros((config.FRAME_HEIGHT, config.FRAME_WIDTH, 3), dtype=np.uint8)
    assert detector.detect(frame) == []


def test_detector_is_reused_across_frames(detector):
    """VIDEO mode needs increasing timestamps - fast consecutive calls must not fail."""
    frame = np.full((480, 640, 3), 127, dtype=np.uint8)
    for _ in range(5):
        assert detector.detect(frame) == []


def test_closed_detector_raises():
    det = HandDetector()
    det.close()
    with pytest.raises(HandDetectionError, match="closed"):
        det.detect(np.zeros((480, 640, 3), dtype=np.uint8))


def test_draw_hand_draws_on_frame():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    points = np.array([(300 + 20 * i, 200 + 10 * i, 0) for i in range(21)], dtype=np.float32)
    draw_hand(frame, Hand(points, "Right", 0.99))
    assert frame.any()


def test_ensure_model_returns_existing_file():
    assert ensure_model() == config.HAND_MODEL_PATH


def test_missing_model_with_bad_url_raises_clear_error(tmp_path):
    missing = tmp_path / "models" / "hand.task"
    with pytest.raises(HandDetectionError, match="could not be downloaded"):
        ensure_model(missing, url=(tmp_path / "nope.task").as_uri())
    assert not missing.exists()
