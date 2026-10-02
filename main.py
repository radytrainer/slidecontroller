"""
AirSlide - Present Without Touching.

Entry point.

    python main.py                   start AirSlide
    python main.py --check           verify the environment (incl. webcam)
    python main.py --check --no-camera
    python main.py --camera-test     live webcam preview with FPS
    python main.py --hand-test       webcam + MediaPipe hand landmarks + finger states
    python main.py --gesture-test    full gesture pipeline with debug panel
    python main.py --control-test F  open F (pptx/pdf) and run NEXT/PREVIOUS

The packaged AirSlide.exe accepts the same options (AirSlide.exe --check).
"""

import argparse
import sys


def _attach_console() -> None:
    """The .exe is a windowed app with no console. When it is started with
    command-line options from a terminal, print into that terminal."""
    if not getattr(sys, "frozen", False) or sys.stdout is not None or len(sys.argv) < 2:
        return
    import ctypes

    if ctypes.windll.kernel32.AttachConsole(-1):  # -1 = the parent process's console
        sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        print()


_attach_console()  # before logging is configured, so log lines reach the terminal too

import config  # noqa: E402
from src.utils.health_check import run_health_check  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402

log = get_logger("airslide")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    prog = "AirSlide.exe" if config.FROZEN else "python main.py"
    parser = argparse.ArgumentParser(prog=prog, description=f"{config.APP_NAME} - {config.APP_TAGLINE}")
    parser.add_argument("--check", action="store_true", help="run the environment health check and exit")
    parser.add_argument("--no-camera", action="store_true", help="skip the webcam probe in --check")
    parser.add_argument("--camera-test", action="store_true", help="show the live webcam preview with FPS")
    parser.add_argument("--hand-test", action="store_true", help="show the webcam with MediaPipe hand landmarks")
    parser.add_argument("--gesture-test", action="store_true",
                        help="run the gesture pipeline with the debug panel (no presentation control)")
    parser.add_argument("--control-test", metavar="FILE",
                        help="open a PPTX/PDF and run NEXT/PREVIOUS without the camera")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.check:
        return 0 if run_health_check(include_camera=not args.no_camera) else 1
    if args.camera_test:
        from src.camera.preview import run_camera_preview

        return run_camera_preview()
    if args.hand_test:
        from src.hand.preview import run_hand_preview

        return run_hand_preview()
    if args.gesture_test:
        from src.gesture.preview import run_gesture_preview

        return run_gesture_preview()
    if args.control_test:
        from src.presentation.control_test import run_control_test

        return run_control_test(args.control_test)

    log.info("%s %s starting - %s", config.APP_NAME, config.APP_VERSION, config.APP_TAGLINE)
    from ui.app import run_app

    return run_app()


if __name__ == "__main__":
    sys.exit(main())
