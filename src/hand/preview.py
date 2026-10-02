"""
Manual hand-detection test: ``python main.py --hand-test``.

Shows the webcam with the 21 MediaPipe landmarks drawn on each hand, plus
FPS, detection time and the per-finger open/closed analysis (joint angles),
so the open-palm thresholds in config.py can be tuned. The skeleton turns
green when the hand is an OPEN PALM. Press Q or Esc to quit.
"""

import time

import cv2

import config
from src.camera.camera import Camera, CameraError
from src.camera.preview import should_quit
from src.gesture.finger_detector import analyze_hand
from src.hand.hand_detector import BONE_COLOR, HandDetectionError, HandDetector, draw_hand
from src.utils.drawing import GREEN, RED, WHITE, YELLOW, draw_text

WINDOW_TITLE = f"{config.APP_NAME} - hand test (Q / Esc to quit)"

MSG_NO_HAND = "Show your open hand to the camera."
MSG_MULTIPLE_HANDS = "Please use one hand."


def run_hand_preview() -> int:
    """Run the hand-detection preview. Returns a process exit code."""
    frames = frames_with_hand = frames_open = 0
    detect_ms_total = 0.0
    try:
        with Camera() as camera, HandDetector() as detector:
            cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
            while True:
                frame = camera.read()
                if frame is None:
                    continue
                frames += 1

                started = time.perf_counter()
                hands = detector.detect(frame)
                detect_ms = (time.perf_counter() - started) * 1000
                detect_ms_total += detect_ms
                frames_with_hand += bool(hands)

                poses = [analyze_hand(hand) for hand in hands]
                for hand, pose in zip(hands, poses, strict=True):
                    draw_hand(frame, hand, bone_color=GREEN if pose.is_open_palm else BONE_COLOR)

                draw_text(frame, f"FPS: {camera.fps:5.1f}   detect: {detect_ms:4.1f} ms", 0)
                draw_text(frame, f"Hands: {len(hands)}", 1)
                if not hands:
                    draw_text(frame, MSG_NO_HAND, 2, WHITE)
                else:
                    hand, pose = hands[0], poses[0]
                    frames_open += pose.is_open_palm
                    draw_text(frame, f"Hand: {hand.handedness} ({hand.score:.2f})", 2)
                    draw_text(frame, f"Fingers: {pose.count}", 3)
                    draw_text(frame, f"Palm: {'OPEN' if pose.is_open_palm else 'not open'}", 4,
                              GREEN if pose.is_open_palm else YELLOW)
                    for row, finger in enumerate(pose.fingers, start=6):
                        angles = " ".join(f"{a:3.0f}" for a in finger.angles)
                        draw_text(frame, f"{finger.name:<6} {'OPEN ' if finger.extended else 'bent '}"
                                         f" angles {angles}  reach {finger.reach:.2f}",
                                  row, GREEN if finger.extended else RED)
                    if len(hands) > 1:
                        draw_text(frame, MSG_MULTIPLE_HANDS, 12, YELLOW)

                cv2.imshow(WINDOW_TITLE, frame)
                if should_quit(WINDOW_TITLE):
                    break
    except (CameraError, HandDetectionError) as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        cv2.destroyAllWindows()

    if frames:
        print(f"Hand test finished: {frames} frames, hand visible in {frames_with_hand} "
              f"({100 * frames_with_hand / frames:.0f}%), open palm in {frames_open}, average detection "
              f"{detect_ms_total / frames:.1f} ms/frame.")
    return 0
