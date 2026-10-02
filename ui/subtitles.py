"""
Subtitle bar at the bottom of the slide show (the screen the audience sees)::

    ┌──────────────────────────────────────────────────────┐
    │                    (the slide)                        │
    │                                                       │
    │     ┌───────────────────────────────────────────┐    │
    │     │ Welcome everyone. Over the next three      │    │
    │     │ weeks, 24 student groups will build ...    │    │
    │     └───────────────────────────────────────────┘    │
    └──────────────────────────────────────────────────────┘

Like the debate timer it lets clicks through and never takes the focus.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

import config
from src.utils.logger import get_logger
from ui.overlay import _make_no_activate

log = get_logger(__name__)

PADDING = 22  # px left + right inside the bar


class SubtitleWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("AirSlide subtitles")
        panel = QFrame(self)
        panel.setStyleSheet("QFrame { background: rgba(0, 0, 0, 175); border-radius: 10px; }"
                            "QLabel { background: transparent; color: #ffffff; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(PADDING, 10, PADDING, 12)
        self.label = QLabel("")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self._max_width = 1000   # logical px, updated from the slide show width
        self._placed_at: tuple[int, int] | None = None

    @property
    def text(self) -> str:
        return self.label.text() if self.isVisible() else ""

    def show_text(self, text: str | None, slide_hwnd: int | None) -> None:
        """Show this subtitle (None hides it)."""
        if not text:
            self.hide()
            return
        if text == self.label.text() and self.isVisible():
            return
        self.label.setStyleSheet(f"font-size: {config.SUBTITLE_FONT_PT}pt; font-weight: 600;")
        self.label.setText(text)
        self._fit()
        if not self.isVisible():
            self.show()
            _make_no_activate(int(self.winId()))
        self._placed_at = None
        self.place(slide_hwnd)

    def _fit(self) -> None:
        """As wide as the text needs (up to the maximum), as high as the wrapped lines."""
        self.label.ensurePolished()  # apply the font size from the style sheet before measuring
        width = QFontMetrics(self.label.font()).horizontalAdvance(self.label.text()) + 2 * PADDING + 8
        width = min(width, self._max_width)
        height = self.label.heightForWidth(width - 2 * PADDING) + 10 + 12
        self.setFixedSize(width, height)

    def place(self, slide_hwnd: int | None) -> None:
        """Bottom centre of the slide show window (the projector screen if unknown)."""
        if not self.isVisible() or QGuiApplication.platformName() != "windows":
            return
        from src.utils import windows

        try:
            left, top, right, bottom = windows.window_rect(slide_hwnd) or windows.presentation_area()
            max_width = int((right - left) * config.SUBTITLE_WIDTH_RATIO / self.devicePixelRatioF())
            if max_width != self._max_width:
                self._max_width = max_width
                self._fit()
            own = windows.window_rect(int(self.winId()))
            if own is None:
                return
            width, height = own[2] - own[0], own[3] - own[1]
            x, y = (left + right - width) // 2, bottom - config.SUBTITLE_MARGIN - height
            if (x, y) != self._placed_at:
                windows.move_topmost(int(self.winId()), x, y)
                self._placed_at = (x, y)
        except Exception as exc:  # subtitles in the wrong place must never stop the show
            log.debug("Could not place the subtitles: %s", exc)
