"""
Debate countdown shown on the slide itself.

A small always-on-top window in the bottom-right corner of the slide show
window, so it is on the screen the audience (and the speaker) look at, also
when the slides are on a projector::

    ┌──────────────────────────────────────────┐
    │                                          │
    │               (the slide)                │
    │                               ┌────────┐ │
    │                               │ ⏱ 0:42 │ │
    │                               │  3/10  │ │
    │                               └────────┘ │
    └──────────────────────────────────────────┘

Mouse clicks go through it to the slide and it never takes the keyboard focus.
It is placed in screen pixels with the Windows API, so it lands correctly on
monitors with different scaling.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

import config
from src.utils.logger import get_logger
from ui.overlay import _make_no_activate
from ui.theme import TEXT_MUTED

log = get_logger(__name__)

GAP = 8  # px between the timer and the overlay when both are in the same corner


class SlideTimerWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("AirSlide timer")
        self._placed_at: tuple[int, int] | None = None

        panel = QFrame(self)
        panel.setStyleSheet("QFrame { background: rgba(10, 14, 18, 190); border-radius: 14px; }"
                            "QLabel { background: transparent; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(0)

        self.time_label = QLabel("")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.slide_label = QLabel("")
        self.slide_label.setAlignment(Qt.AlignCenter)
        self.slide_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: {config.DEBATE_TIMER_FONT_PT * 0.4:.0f}pt;")
        layout.addWidget(self.time_label)
        layout.addWidget(self.slide_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._placed_at = None
        _make_no_activate(int(self.winId()))

    def show_time(self, text: str, slide_text: str, color: str) -> None:
        """e.g. ('⏱ 0:42', '3/10', green)."""
        self.time_label.setText(text)
        self.time_label.setStyleSheet(f"color: {color}; font-weight: 700; "
                                      f"font-size: {config.DEBATE_TIMER_FONT_PT}pt;")
        self.slide_label.setText(slide_text)
        self.adjustSize()
        self._placed_at = None  # the size may have changed

    def place(self, slide_hwnd: int | None, avoid_hwnd: int | None = None) -> None:
        """Keep the window in the bottom-right corner of the slide show window
        (the projector screen if unknown), above ``avoid_hwnd`` if they would overlap."""
        if not self.isVisible() or QGuiApplication.platformName() != "windows":
            return
        from src.utils import windows

        try:
            own = windows.window_rect(int(self.winId()))
            if own is None:
                return
            width, height = own[2] - own[0], own[3] - own[1]
            _, _, right, bottom = windows.window_rect(slide_hwnd) or windows.presentation_area()
            margin = config.DEBATE_TIMER_MARGIN
            x, y = right - margin - width, bottom - margin - height
            other = windows.window_rect(avoid_hwnd) if avoid_hwnd else None
            if other and x < other[2] and other[0] < x + width and y < other[3] and other[1] < y + height:
                y = other[1] - GAP - height   # stack above the overlay
            if (x, y) != self._placed_at:
                windows.move_topmost(int(self.winId()), x, y)
                self._placed_at = (x, y)
        except Exception as exc:  # a timer in the wrong place must never stop the show
            log.debug("Could not place the slide timer: %s", exc)


class AlertWindow(QWidget):
    """A large banner in the middle of the slide show for a few seconds (time limit alerts)."""

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("AirSlide alert")
        self.panel = QFrame(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.panel)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(40, 24, 40, 24)
        self.label = QLabel("")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        self._hide_timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_alert(self, message: str, color: str, slide_hwnd: int | None) -> None:
        self.panel.setStyleSheet(f"QFrame {{ background: {color}; border-radius: 18px; }}"
                                 "QLabel { background: transparent; }")
        self.label.setText(message)
        self.label.setStyleSheet(f"color: #101418; font-weight: 700; font-size: {config.DEBATE_TIMER_FONT_PT}pt;")
        self.adjustSize()
        self.show()
        _make_no_activate(int(self.winId()))
        self._hide_timer.start(config.OVERTIME_ALERT_SECONDS * 1000)
        if QGuiApplication.platformName() != "windows":
            return
        from src.utils import windows

        try:
            own = windows.window_rect(int(self.winId()))
            left, top, right, bottom = windows.window_rect(slide_hwnd) or windows.presentation_area()
            width, height = own[2] - own[0], own[3] - own[1]
            windows.move_topmost(int(self.winId()), (left + right - width) // 2, (top + bottom - height) // 2)
        except Exception as exc:
            log.debug("Could not place the alert: %s", exc)
