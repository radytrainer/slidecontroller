"""
Debug overlay for the camera image (config.DEBUG).

Draws the hand skeleton, the palm centre and its trail, the swipe being
tracked, the presenter focus (presenter's shoulders, ignored hands in grey,
the zoomed search square) and the debug panel from the specification::

    FPS / Hand / Open Palm / Fingers / Start X / Current X / Delta X /
    Delta Y / Distance / Duration / Direction / Gesture / State / Cooldown
"""

import cv2
import numpy as np

from src.gesture.gesture_state import GestureState, GestureStatus
from src.gesture.hand_tracking import MovementTracker
from src.gesture.swipe_detector import Gesture, Swipe
from src.hand.hand_detector import BONE_COLOR, Hand, draw_hand
from src.hand.pose_detector import PoseLandmark
from src.hand.presenter import FocusResult
from src.utils.drawing import GREEN, RED, WHITE, YELLOW, draw_text

BANNER_SECONDS = 0.8
CENTER_COLOR = (255, 200, 0)
IGNORED_COLOR = (130, 130, 130)
PRESENTER_COLOR = (255, 120, 255)
ZOOM_COLOR = (0, 200, 255)


def _num(value: float | None, fmt: str = "{:.0f}") -> str:
    return "-" if value is None else fmt.format(value)


def draw_debug_overlay(
    frame: np.ndarray,
    hands: list[Hand],
    status: GestureStatus,
    fps: float,
    tracker: MovementTracker | None = None,
    last_swipe: Swipe | None = None,
    last_swipe_age: float | None = None,
    focus: FocusResult | None = None,
) -> None:
    """Draw everything onto ``frame`` in place."""
    if focus is not None:
        _draw_focus(frame, focus)
    for hand in hands:
        draw_hand(frame, hand, label=False, bone_color=GREEN if status.ready else BONE_COLOR)

    # Palm centre trail
    if tracker and len(tracker.trail) > 1:
        pts = np.array(tracker.trail, dtype=np.int32)
        cv2.polylines(frame, [pts], False, CENTER_COLOR, 2, cv2.LINE_AA)
    if status.center:
        cv2.circle(frame, tuple(int(v) for v in status.center), 10, CENTER_COLOR, -1, cv2.LINE_AA)

    # Swipe in progress: start marker and a line to the current point
    progress = status.progress
    if progress and status.state == GestureState.TRACKING:
        start = (int(progress.start_x), int(progress.start_y))
        current = (int(progress.current_x), int(progress.current_y))
        cv2.circle(frame, start, 8, YELLOW, 2, cv2.LINE_AA)
        cv2.arrowedLine(frame, start, current, YELLOW, 3, cv2.LINE_AA, tipLength=0.15)

    shown = progress or last_swipe
    direction = "-"
    if last_swipe and last_swipe_age is not None and last_swipe_age < BANNER_SECONDS:
        direction = last_swipe.direction.ascii
    elif progress and progress.distance > 20:
        direction = "RIGHT -> LEFT" if progress.delta_x < 0 else "LEFT -> RIGHT"

    lines = [
        (f"FPS: {fps:.0f}", GREEN),
        (f"Hand: {'YES' if status.hand_count else 'NO'}" + (f" ({status.hand_count})" if status.hand_count > 1 else ""),
         GREEN if status.hand_count == 1 else YELLOW),
        (f"Open Palm: {'YES' if status.open_palm else 'NO'}", GREEN if status.open_palm else YELLOW),
        (f"Fingers: {status.fingers}", GREEN),
        (f"Palm: {_num(status.pose.palm_size if status.pose else None)} px", WHITE),
        (_focus_line(focus), GREEN if focus and focus.presenter else YELLOW),
        ("", GREEN),
        (f"Start X: {_num(shown.start_x if shown else None)}", WHITE),
        (f"Current X: {_num(shown.current_x if shown else None)}", WHITE),
        (f"Delta X: {_num(shown.delta_x if shown else None, '{:+.0f}')}", WHITE),
        (f"Delta Y: {_num(shown.delta_y if shown else None, '{:+.0f}')}", WHITE),
        (f"Distance: {_num(shown.distance if shown else None)}"
         + (f" / {required:.0f}" if (required := _required(status)) else ""), WHITE),
        (f"Duration: {_num(shown.duration if shown else None, '{:.2f} sec')}", WHITE),
        ("", WHITE),
        (f"Direction: {direction}", WHITE),
        (f"Gesture: {last_swipe.gesture.value if last_swipe else '-'}", WHITE),
        (f"State: {status.state.value}", GREEN),
        (f"Cooldown: {status.cooldown_remaining:.2f}", YELLOW if status.cooldown_remaining else GREEN),
    ]
    panel_height = 32 + 30 * len(lines)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (430, panel_height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
    for row, (text, color) in enumerate(lines):
        if text:
            draw_text(frame, text, row, color)

    # Message for the presenter (bottom-left)
    height = frame.shape[0]
    cv2.putText(frame, status.message, (16, height - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(frame, status.message, (16, height - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.9, WHITE, 2, cv2.LINE_AA)

    # Big banner right after a gesture
    if last_swipe and last_swipe_age is not None and last_swipe_age < BANNER_SECONDS:
        text = "NEXT >>" if last_swipe.gesture == Gesture.NEXT else "<< PREVIOUS"
        size, _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 2.5, 6)
        x = (frame.shape[1] - size[0]) // 2
        cv2.putText(frame, text, (x, 140), cv2.FONT_HERSHEY_DUPLEX, 2.5, (0, 0, 0), 12, cv2.LINE_AA)
        cv2.putText(frame, text, (x, 140), cv2.FONT_HERSHEY_DUPLEX, 2.5,
                    GREEN if last_swipe.gesture == Gesture.NEXT else RED, 6, cv2.LINE_AA)


def _required(status: GestureStatus) -> float | None:
    """Swipe distance needed for the current hand size (smaller when far away)."""
    return status.required_distance


def _focus_line(focus: FocusResult | None) -> str:
    if focus is None:
        return "Presenter: -"
    text = "Presenter: YES" if focus.presenter else "Presenter: NO"
    if focus.zoom_factor:
        text += f"  Zoom {focus.zoom_factor:.1f}x"
    if focus.ignored:
        text += f"  Ignored {len(focus.ignored)}"
    return text


def _draw_focus(frame: np.ndarray, focus: FocusResult) -> None:
    for hand in focus.ignored:
        draw_hand(frame, hand, label=False, bone_color=IGNORED_COLOR)
    for body in focus.bodies:
        if body is focus.presenter:
            continue
        a, b = body.point(PoseLandmark.LEFT_SHOULDER), body.point(PoseLandmark.RIGHT_SHOULDER)
        cv2.line(frame, tuple(int(v) for v in a), tuple(int(v) for v in b), IGNORED_COLOR, 2, cv2.LINE_AA)
    if focus.presenter is not None:
        body = focus.presenter
        a, b = body.point(PoseLandmark.LEFT_SHOULDER), body.point(PoseLandmark.RIGHT_SHOULDER)
        cv2.line(frame, tuple(int(v) for v in a), tuple(int(v) for v in b), PRESENTER_COLOR, 4, cv2.LINE_AA)
        cx, cy = body.shoulder_center
        cv2.putText(frame, "PRESENTER", (int(cx) - 60, int(cy) - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    PRESENTER_COLOR, 2, cv2.LINE_AA)
    if focus.zoom is not None:
        x, y, side = focus.zoom
        cv2.rectangle(frame, (x, y), (x + side, y + side), ZOOM_COLOR, 2, cv2.LINE_AA)
