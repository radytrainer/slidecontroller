"""
Manual gesture test: ``python main.py --gesture-test``.

Runs the full gesture pipeline (camera -> hand -> open palm -> swipe ->
state machine) WITHOUT controlling any presentation. Shows the debug panel,
the palm-centre trail and a big NEXT / PREVIOUS banner for each gesture.
Use it to verify directions and tune thresholds. Press Q or Esc to quit.
"""

import time
from collections import Counter

import cv2

import config
from src.camera.camera import Camera, CameraError
from src.camera.preview import should_quit
from src.gesture.debug_view import draw_debug_overlay
from src.gesture.gesture_state import GestureStateMachine
from src.gesture.hand_tracking import MovementTracker
from src.gesture.swipe_detector import SwipeDetector
from src.hand.hand_detector import HandDetectionError
from src.hand.presenter import PresenterHandDetector

WINDOW_TITLE = f"{config.APP_NAME} - gesture test (Q / Esc to quit)"


def run_gesture_preview() -> int:
    counts: Counter[str] = Counter()
    try:
        with Camera() as camera, PresenterHandDetector() as detector:
            machine = GestureStateMachine(SwipeDetector(frame_width=camera.width))
            tracker = MovementTracker()
            last_swipe = None
            last_swipe_time = 0.0
            cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)

            while True:
                frame = camera.read()
                if frame is None:
                    continue
                now = time.monotonic()
                hands = detector.detect(frame)
                status = machine.update(hands, now)

                if status.center:
                    tracker.update(status.center)
                else:
                    tracker.reset()

                if status.swipe:
                    last_swipe, last_swipe_time = status.swipe, now
                    counts[status.swipe.gesture.value] += 1
                    print(f"{status.swipe.gesture.value:<8} {status.swipe.direction.value}  "
                          f"dx={status.swipe.delta_x:+.0f} dy={status.swipe.delta_y:+.0f} "
                          f"t={status.swipe.duration:.2f}s")
                    machine.mark_executed()

                draw_debug_overlay(frame, hands, status, camera.fps, tracker,
                                   last_swipe, now - last_swipe_time if last_swipe else None,
                                   focus=detector.last)
                cv2.imshow(WINDOW_TITLE, frame)
                if should_quit(WINDOW_TITLE):
                    break
    except (CameraError, HandDetectionError) as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        cv2.destroyAllWindows()

    print(f"Gesture test finished: NEXT x{counts['NEXT']}, PREVIOUS x{counts['PREVIOUS']}.")
    return 0
