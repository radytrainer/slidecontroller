"""
Write assets/airslide.ico from the app icon drawn in ui/theme.py.

    python -m tools.make_icon

Used by the .exe build (build.ps1) so Explorer and the taskbar show the icon.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ICON_PATH = ROOT / "assets" / "airslide.ico"


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 - needed for fonts
    from ui.theme import make_app_icon

    pixmap = make_app_icon().pixmap(QSize(256, 256))
    ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(ICON_PATH), "ICO"):
        print("Could not write the icon (Qt ICO plugin missing?)")
        return 1
    print(f"created {ICON_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
