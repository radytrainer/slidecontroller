"""
Manual camera test: ``python main.py --camera-test``.

Shows the live webcam with FPS and resolution. Press Q or Esc to quit
(or close the window). Prints a short summary when it ends.
"""

import time

import cv2

import config
from src.camera.camera import Camera, CameraError
from src.utils.drawing import WHITE, draw_text

WINDOW_TITLE = f"{config.APP_NAME} - camera test (Q / Esc to quit)"


def should_quit(window_title: str) -> bool:
    """True when Q/Esc was pressed or the preview window was closed."""
    key = cv2.waitKey(1) & 0xFF
    if key in (ord("q"), ord("Q"), 27):
        return True
    return cv2.getWindowProperty(window_title, cv2.WND_PROP_VISIBLE) < 1


def run_camera_preview() -> int:
    """Run the preview loop. Returns a process exit code."""
    frames = dropped = 0
    started = time.perf_counter()
    try:
        with Camera() as camera:
            cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
            while True:
                frame = camera.read()
                if frame is None:
                    dropped += 1
                    continue
                frames += 1

                width, height = camera.resolution
                draw_text(frame, f"FPS: {camera.fps:5.1f}", 0)
                draw_text(frame, f"Resolution: {width}x{height} ({camera.active_backend})", 1)
                draw_text(frame, f"Mirror: {'ON' if camera.mirror else 'OFF'}", 2)
                draw_text(frame, "Raise your RIGHT hand: it should appear on the RIGHT side", 3, WHITE)
                cv2.imshow(WINDOW_TITLE, frame)
                if should_quit(WINDOW_TITLE):
                    break
            final_fps = camera.fps
            resolution = camera.resolution
    except CameraError as exc:
        print(f"Camera error: {exc}")
        return 1
    finally:
        cv2.destroyAllWindows()

    elapsed = time.perf_counter() - started
    print(f"Camera test finished: {frames} frames in {elapsed:.1f}s "
          f"(average {frames / elapsed if elapsed else 0:.1f} FPS, last {final_fps:.1f} FPS), "
          f"{dropped} dropped, resolution {resolution[0]}x{resolution[1]}. Camera released.")
    return 0
