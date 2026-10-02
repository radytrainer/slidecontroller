"""
Manual presentation-control test, independent of the camera:

    python main.py --control-test path\to\file.pptx
    python main.py --control-test path\to\file.pdf

Opens the file in its application, starts presenting, then runs a short
script (NEXT x3, PREVIOUS x1) with pauses so you can watch, and closes.
"""

import time

from src.presentation.base import PresentationError
from src.presentation.presentation_manager import PresentationManager

SCRIPT = ["next", "next", "next", "previous"]
PAUSE = 2.0


def run_control_test(file_path: str) -> int:
    manager = PresentationManager()
    try:
        manager.open_file(file_path)
        print(f"Opened with {manager.session.app_name}. Starting presentation...")
        manager.start_presentation()
        time.sleep(PAUSE)
        print(f"  start     position={manager.position()}")
        for action in SCRIPT:
            ok = manager.next_slide() if action == "next" else manager.previous_slide()
            time.sleep(PAUSE)
            print(f"  {action:<9} sent={ok} position={manager.position()}")
            if not ok:
                print("  Presentation is no longer running - stopping.")
                break
    except PresentationError as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        manager.exit_presentation()
        print(f"Closed. Session state: {manager.session.presentation_status.value}")
    return 0
