"""
Environment health check: ``python main.py --check``.

Verifies everything AirSlide needs without starting a presentation:
Python version, Windows, installed packages, Microsoft PowerPoint,
a PDF viewer and the webcam.
"""

import importlib
import platform
import sys
from dataclasses import dataclass

import config

MIN_PYTHON = (3, 11)

OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def check_python() -> CheckResult:
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] >= MIN_PYTHON:
        return CheckResult("Python", OK, f"{version} ({sys.executable})")
    return CheckResult("Python", FAIL, f"{version} - Python 3.11+ is required")


def check_platform() -> CheckResult:
    system = platform.system()
    if system == "Windows":
        return CheckResult("Platform", OK, f"Windows {platform.release()} ({platform.version()})")
    return CheckResult("Platform", FAIL, f"{system} - AirSlide targets Windows 10/11")


def check_package(module: str, label: str) -> CheckResult:
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        return CheckResult(label, FAIL, f"not installed ({exc}) - run: pip install -r requirements.txt")
    version = getattr(mod, "__version__", "installed")
    return CheckResult(label, OK, str(version))


def check_powerpoint() -> CheckResult:
    """Detect PowerPoint via its COM registration (does not launch it)."""
    if platform.system() != "Windows":
        return CheckResult("PowerPoint", FAIL, "Windows only")
    from src.presentation.base import MSG_POWERPOINT_NOT_FOUND
    from src.presentation.powerpoint_controller import is_powerpoint_installed, powerpoint_version

    if not is_powerpoint_installed():
        return CheckResult("PowerPoint", FAIL, MSG_POWERPOINT_NOT_FOUND.replace("\n", " "))
    version = powerpoint_version() or "PowerPoint.Application"
    return CheckResult("PowerPoint", OK, f"COM automation available ({version})")


def check_pdf_viewer() -> CheckResult:
    if platform.system() != "Windows":
        return CheckResult("PDF viewer", FAIL, "Windows only")
    from src.presentation.pdf_controller import default_pdf_app, find_sumatra

    sumatra = find_sumatra()
    default_app = default_pdf_app()

    if sumatra:
        return CheckResult("PDF viewer", OK, f"SumatraPDF ({sumatra})")
    if config.PDF_VIEWER == "sumatra":
        return CheckResult("PDF viewer", FAIL, "PDF_VIEWER='sumatra' but SumatraPDF.exe was not found")
    if default_app:
        return CheckResult(
            "PDF viewer",
            WARN,
            f"default app '{default_app}' (SumatraPDF recommended for presentation mode)",
        )
    return CheckResult("PDF viewer", FAIL, "no PDF viewer registered for .pdf files")

def check_hand_model() -> CheckResult:
    path = config.HAND_MODEL_PATH
    if not path.is_file():
        return CheckResult("Hand model", WARN, "not downloaded yet - it is downloaded automatically on first use")
    # Actually load it: proves the MediaPipe native library works (important in the .exe).
    try:
        from src.hand.hand_detector import HandDetector

        HandDetector().close()
    except Exception as exc:
        return CheckResult("Hand model", FAIL, f"{path.name} could not be loaded: {exc}")
    return CheckResult("Hand model", OK, f"{path.name} ({path.stat().st_size / 1e6:.1f} MB), loads OK")


def check_pose_model() -> CheckResult:
    path = config.POSE_MODEL_PATH
    if not path.is_file():
        return CheckResult("Pose model", WARN, "not downloaded yet - it is downloaded automatically on first use")
    try:
        from src.hand.pose_detector import PoseDetector

        PoseDetector().close()
    except Exception as exc:
        return CheckResult("Pose model", WARN,
                           f"{path.name} could not be loaded ({exc}) - presenter focus and zoom are off")
    return CheckResult("Pose model", OK, f"{path.name} ({path.stat().st_size / 1e6:.1f} MB), loads OK")


def check_camera() -> CheckResult:
    try:
        from src.camera.camera import Camera, CameraError
    except ImportError as exc:
        return CheckResult("Camera", FAIL, f"camera module unavailable ({exc})")

    try:
        with Camera() as camera:
            width, height = camera.resolution
            backend = camera.active_backend
    except CameraError as exc:
        return CheckResult("Camera", FAIL, f"index {config.CAMERA_INDEX}: {exc}")

    detail = f"index {config.CAMERA_INDEX}, {width}x{height} via {backend}"
    if (width, height) != (config.FRAME_WIDTH, config.FRAME_HEIGHT):
        return CheckResult("Camera", WARN, f"{detail} (requested {config.FRAME_WIDTH}x{config.FRAME_HEIGHT})")
    return CheckResult("Camera", OK, detail)


def run_health_check(include_camera: bool = True) -> bool:
    """Run all checks, print a report and return True when nothing FAILED."""
    checks = [
        check_python,
        check_platform,
        lambda: check_package("numpy", "NumPy"),
        lambda: check_package("cv2", "OpenCV"),
        lambda: check_package("mediapipe", "MediaPipe"),
        lambda: check_package("PySide6", "PySide6"),
        lambda: check_package("win32com.client", "pywin32"),
        check_hand_model,
        check_pose_model,
        check_powerpoint,
        check_pdf_viewer,
    ]
    if include_camera:
        checks.append(check_camera)

    print(f"\n{config.APP_NAME} {config.APP_VERSION} - health check\n" + "-" * 60)
    results = []
    for check in checks:
        try:
            result = check()
        except Exception as exc:  # a broken check must not hide the others
            result = CheckResult(getattr(check, "__name__", "check"), FAIL, repr(exc))
        results.append(result)
        print(f"  [{result.status:<4}] {result.name:<11} {result.detail}")

    failed = [r for r in results if r.status == FAIL]
    print("-" * 60)
    print("  All required checks passed." if not failed else f"  {len(failed)} check(s) failed.")
    return not failed
