"""
Debate mode, advanced option: a time for each slide.

Shown after the file is chosen, with one row per slide. When the number of
slides could not be read from the file, the presenter enters it.

With a total time, the rows start as the total divided equally; the sum of
all rows is shown so the presenter sees when edits no longer match it.

    ┌ Slide times - talk.pptx ─────────────────────────┐
    │ Slides: [ 8 ]    Total [0:10:00] [Divide equally] │
    │ Slide 1   [ 75 s ]                               │
    │ Slide 2   [ 75 s ]                               │
    │ ...                                              │
    │ All slides: 10:00                                │
    │                        [Start presentation] [Cancel] │
    └──────────────────────────────────────────────────┘
"""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import config
from src.presentation.debate import format_seconds, split_total
from src.utils.settings import BY_KEY
from ui.theme import STATUS_COLORS
from ui.widgets import DurationEdit

MAX_SLIDES = 500
MAX_SLIDE_SECONDS = 3600
_TOTAL = BY_KEY["DEBATE_TOTAL_SECONDS"]


def _seconds_editor(value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(1, MAX_SLIDE_SECONDS)  # a divided total can be only a few seconds per slide
    spin.setSingleStep(5)
    spin.setSuffix(" s")
    spin.setValue(value)
    return spin


class SlideTimesDialog(QDialog):
    def __init__(self, parent: QWidget | None, file_name: str, slide_count: int | None,
                 default_seconds: int, times: dict[int, int] | None = None,
                 total_seconds: int | None = None):
        """total_seconds: divide this total between the slides (None = default_seconds each)."""
        super().__init__(parent)
        self.setWindowTitle(f"{config.APP_NAME} - Slide times - {file_name}")
        self.setMinimumSize(600, 560)
        self._default = default_seconds
        self._times = dict(times or {})
        self._editors: list[QSpinBox] = []
        self.total: DurationEdit | None = None

        top = QHBoxLayout()
        top.addWidget(QLabel("Slides"))
        self.count = QSpinBox()
        self.count.setRange(1, MAX_SLIDES)
        self.count.setValue(slide_count or max(self._times, default=10))
        self.count.setEnabled(slide_count is None)  # known from the file: fixed
        self.count.setToolTip("Read from the file." if slide_count else
                              "The number of slides could not be read from the file. Please enter it.")
        self.count.valueChanged.connect(self._on_count_changed)
        top.addWidget(self.count)
        top.addStretch(1)
        if total_seconds is not None:
            top.addWidget(QLabel("Total"))
            self.total = DurationEdit(int(_TOTAL.minimum), int(_TOTAL.maximum))
            self.total.set_seconds(total_seconds)
            top.addWidget(self.total)
            divide = QPushButton("Divide equally")
            divide.clicked.connect(self.divide_equally)
            top.addWidget(divide)
            if not self._times:
                self._times = split_total(total_seconds, self.count.value())
        else:
            top.addWidget(QLabel("Set all to"))
            self.all_seconds = _seconds_editor(default_seconds)
            top.addWidget(self.all_seconds)
            apply_all = QPushButton("Apply")
            apply_all.clicked.connect(self.set_all)
            top.addWidget(apply_all)

        self._rows = QWidget()
        self._form = QFormLayout(self._rows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._rows)

        self.sum_label = QLabel("")
        self.sum_label.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Start presentation")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        text = ("When a slide's time is up, the next slide is shown. Swiping still works "
                "and starts the new slide's time.")
        if slide_count is None:
            text = "The number of slides could not be read from the file - please enter it.\n" + text
        hint = QLabel(text)
        hint.setObjectName("muted")
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(hint)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.sum_label)
        layout.addWidget(buttons)
        self._rebuild()
        if self.total is not None:
            self.total.timeChanged.connect(self._update_sum)

    # -- rows -------------------------------------------------------------------------------

    def _on_count_changed(self) -> None:
        if self.total is not None:
            self._times = split_total(self.total.seconds(), self.count.value())
            self._editors = []  # the old values do not fit the new count
        self._rebuild()

    def _rebuild(self) -> None:
        # Keep the values already entered when the number of slides changes.
        for number, spin in enumerate(self._editors, start=1):
            self._times[number] = spin.value()
        while self._form.rowCount():
            self._form.removeRow(0)
        self._editors = []
        for number in range(1, self.count.value() + 1):
            spin = _seconds_editor(self._times.get(number, self._default))
            spin.valueChanged.connect(self._update_sum)
            self._form.addRow(f"Slide {number}", spin)
            self._editors.append(spin)
        self._update_sum()

    def _update_sum(self, *_) -> None:
        total = sum(spin.value() for spin in self._editors)
        text = f"All slides: {format_seconds(total)}"
        color = STATUS_COLORS["muted"]
        if self.total is not None and total != self.total.seconds():
            text += f"   (total is {format_seconds(self.total.seconds())} - press Divide equally to match)"
            color = STATUS_COLORS["warn"]
        self.sum_label.setText(text)
        self.sum_label.setStyleSheet(f"color: {color};")

    # -- actions ----------------------------------------------------------------------------

    def divide_equally(self) -> None:
        times = split_total(self.total.seconds(), len(self._editors))
        for number, spin in enumerate(self._editors, start=1):
            spin.setValue(times[number])

    def set_all(self) -> None:
        for spin in self._editors:
            spin.setValue(self.all_seconds.value())

    def slide_count(self) -> int:
        return len(self._editors)

    def total_seconds(self) -> int | None:
        return self.total.seconds() if self.total is not None else None

    def times(self) -> dict[int, int]:
        """{slide number: seconds} for every slide."""
        return {number: spin.value() for number, spin in enumerate(self._editors, start=1)}
