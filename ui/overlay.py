"""
Small floating status panel shown while presenting.

It stays on top of the slide show in a screen corner, never takes keyboard
focus (so PowerPoint / the PDF viewer keep receiving keys), and can be
dragged elsewhere with the mouse.

    ┌───────────────────────────┐
    │ 🖐️ AIRSLIDE          ● │
    │ ⏱ 0:42  ·  3/10          │   (debate mode only)
    │ Hand: ✓   Gesture: READY  │
    │ ✋ ←  Next   ✋ →  Previous │
    └───────────────────────────┘
"""

import sys

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import config
from src.engine.gesture_engine import CommandResult, EngineUpdate
from src.gesture.gesture_state import GestureState
from src.gesture.swipe_detector import Gesture
from ui.theme import ACCENT, BORDER, ERROR, INFO, SURFACE, TEXT, TEXT_MUTED, WARNING

FLASH_MS = 900


class OverlayWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("AirSlide overlay")
        self._drag_offset: QPoint | None = None
        self._flash_until = False

        panel = QFrame(self)
        panel.setStyleSheet(
            f"QFrame {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}"
            f"QLabel {{ border: none; color: {TEXT}; background: transparent; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("🖐️ AIRSLIDE")
        title.setStyleSheet("font-weight: 700; font-size: 10pt;")
        self.dot = QLabel("●")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.dot)
        layout.addLayout(header)

        self.hand_label = QLabel("Hand: —")
        self.gesture_label = QLabel("Gesture: —")
        self.gesture_label.setStyleSheet("font-weight: 700; font-size: 11pt;")
        self.message_label = QLabel("")
        self.message_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8.5pt;")
        hints = QLabel("✋ ← Next     ✋ → Previous")
        hints.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9pt;")
        self.timer_label = QLabel("")  # debate mode countdown
        self.timer_label.setVisible(False)
        self.voice_label = QLabel("")  # subtitles: is the microphone hearing the presenter?
        self.voice_label.setVisible(False)
        for widget in (self.timer_label, self.hand_label, self.gesture_label, self.message_label,
                       self.voice_label, hints):
            layout.addWidget(widget)

        self.setFixedWidth(250)
        self._flash_timer = QTimer(self, singleShot=True, timeout=self._end_flash)

    # -- positioning / no-focus -----------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.adjustSize()
        self.move_to_corner()
        _make_no_activate(int(self.winId()))

    def move_to_corner(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        margin = config.OVERLAY_MARGIN
        corner = config.OVERLAY_CORNER
        x = screen.left() + margin if "left" in corner else screen.right() - self.width() - margin
        y = screen.top() + margin if "top" in corner else screen.bottom() - self.height() - margin
        self.move(x, y)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None

    # -- content -------------------------------------------------------------------------------

    def show_update(self, update: EngineUpdate) -> None:
        status = update.status
        if status.hand_count == 1:
            hand = "Hand: ✓"
        elif status.hand_count > 1:
            hand = "Hand: ✗  use one hand"
        else:
            hand = "Hand: ✗"
        self.hand_label.setText(hand)
        self.message_label.setText(status.message)

        if self._flash_timer.isActive():
            return
        if update.paused:
            self._set_gesture("PAUSED", WARNING)
        elif status.state == GestureState.COOLDOWN:
            self._set_gesture("WAIT", INFO)
        elif status.ready:
            self._set_gesture("READY", ACCENT)
        else:
            self._set_gesture("—", TEXT_MUTED)

    def show_command(self, result: CommandResult) -> None:
        if not result.executed:
            return
        text = "NEXT  ➡" if result.gesture == Gesture.NEXT else "⬅  PREVIOUS"
        self._set_gesture(text, ACCENT)
        self._flash_timer.start(FLASH_MS)

    def show_error(self, message: str) -> None:
        self._set_gesture("CAMERA ERROR", ERROR)
        self.message_label.setText(message)

    def show_timer(self, text: str | None, color: str = TEXT) -> None:
        """Debate countdown, e.g. '⏱ 0:42  ·  3/10'; None hides it."""
        visible = text is not None
        if visible != self.timer_label.isVisible():
            self.timer_label.setVisible(visible)
            if self.isVisible():
                self.adjustSize()
                self.move_to_corner()
        if visible:
            self.timer_label.setText(text)
            self.timer_label.setStyleSheet(f"font-weight: 700; font-size: 18pt; color: {color};")

    def show_voice(self, text: str | None, color: str = TEXT_MUTED) -> None:
        """Subtitles line, e.g. '🎤 ▮▮▮▯▯ Speaking · 2/5'; None hides it."""
        visible = text is not None
        if visible != self.voice_label.isVisible():
            self.voice_label.setVisible(visible)
            if self.isVisible():
                self.adjustSize()
                self.move_to_corner()
        if visible and text != self.voice_label.text():
            self.voice_label.setText(text)
            self.voice_label.setStyleSheet(f"color: {color}; font-size: 9pt;")

    def _set_gesture(self, text: str, color: str) -> None:
        self.gesture_label.setText(f"Gesture: {text}")
        self.gesture_label.setStyleSheet(f"font-weight: 700; font-size: 11pt; color: {color};")
        self.dot.setStyleSheet(f"color: {color};")

    def _end_flash(self) -> None:
        self._set_gesture("READY", ACCENT)


def _make_no_activate(hwnd: int) -> None:
    """Belt and braces: tell Windows this window must never be activated by clicks."""
    if sys.platform != "win32":
        return
    import win32con
    import win32gui

    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,
                           style | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW)
