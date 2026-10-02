"""Reusable widgets: cards, status rows and the camera preview."""

import numpy as np
from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QTimeEdit, QVBoxLayout, QWidget

from ui.theme import STATUS_COLORS


class Card(QFrame):
    """A rounded panel with an optional small uppercase title."""

    def __init__(self, title: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 16, 20, 18)
        self.body.setSpacing(8)
        if title:
            label = QLabel(title.upper())
            label.setObjectName("sectionTitle")
            self.body.addWidget(label)


class StatusGrid(QWidget):
    """Two-column 'Name: value' list whose values can be coloured."""

    def __init__(self, names: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(7)
        self._values: dict[str, QLabel] = {}
        for row, name in enumerate(names):
            key = QLabel(name)
            key.setObjectName("muted")
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(key, row, 0)
            layout.addWidget(value, row, 1)
            self._values[name] = value
        layout.setColumnStretch(1, 1)

    def set(self, name: str, text: str, level: str | None = None) -> None:
        label = self._values[name]
        if label.text() != text:
            label.setText(text)
        color = STATUS_COLORS.get(level or "", "")
        style = f"color: {color}; font-weight: 600;" if color else ""
        if label.styleSheet() != style:
            label.setStyleSheet(style)

    def text(self, name: str) -> str:
        return self._values[name].text()


class DurationEdit(QTimeEdit):
    """A length of time shown as h:mm:ss, read and written in seconds."""

    def __init__(self, minimum: int, maximum: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setDisplayFormat("H:mm:ss")
        self.setTimeRange(QTime(0, 0).addSecs(minimum), QTime(0, 0).addSecs(maximum))
        self.setCurrentSection(QTimeEdit.MinuteSection)

    def seconds(self) -> int:
        return QTime(0, 0).secsTo(self.time())

    def set_seconds(self, seconds: int) -> None:
        self.setTime(QTime(0, 0).addSecs(int(seconds)))


class CameraView(QLabel):
    """Shows BGR numpy frames, scaled to fit while keeping the aspect ratio."""

    PLACEHOLDER = "Camera preview"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(self.PLACEHOLDER, parent)
        self.setObjectName("cameraView")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 270)

    def show_frame(self, frame: np.ndarray) -> None:
        frame = np.ascontiguousarray(frame)
        height, width = frame.shape[:2]
        image = QImage(frame.data, width, height, frame.strides[0], QImage.Format_BGR888)
        pixmap = QPixmap.fromImage(image).scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(pixmap)

    def show_message(self, text: str) -> None:
        self.clear()
        self.setText(text)
