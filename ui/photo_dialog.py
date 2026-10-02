"""
Photo slideshow setup: style (with a live preview on the chosen photos),
order and fit - shown after the photos are chosen.

    ┌ Photo slideshow - 12 photos ─────────────────────────────┐
    │ [thumb][thumb][thumb][thumb][thumb][thumb] +6            │
    │ Style  [Ken Burns ▾]   A slow pan and zoom across ...    │
    │ ┌──────────────── live preview ────────────────┐         │
    │ │                                               │         │
    │ └───────────────────────────────────────────────┘         │
    │ Order  [By name ▾]      ☐ Fill the screen (crop edges)    │
    │ ☐ Play automatically, every [5 s]   ☐ Loop                │
    │                           [Start slideshow]  [Cancel]     │
    └───────────────────────────────────────────────────────────┘
"""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import config
from src.presentation.photos import ORDERS
from src.utils.settings import BY_KEY
from ui.photo_show import STYLES, PhotoView

THUMBNAILS = 8
THUMB_SIZE = 72
PREVIEW_SIZE = QSize(480, 270)
PREVIEW_PHOTOS = 4
PREVIEW_STEP_MS = 2200


def thumbnail(path: Path, size: int = THUMB_SIZE) -> QPixmap:
    """A small, upright preview (decoded at reduced size, so it is fast)."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    full = reader.size()
    if full.isValid() and max(full.width(), full.height()) > size * 2:
        reader.setScaledSize(full.scaled(size * 2, size * 2, Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        return QPixmap()
    return QPixmap.fromImage(image.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                             .copy(0, 0, size, size))


class PhotoSetupDialog(QDialog):
    def __init__(self, parent: QWidget | None, photos: list[Path], skipped: int = 0):
        super().__init__(parent)
        count = len(photos)
        self.setWindowTitle(f"{config.APP_NAME} - Photo slideshow - {count} photo{'s' if count != 1 else ''}")
        self.photos = photos

        thumbs = QHBoxLayout()
        thumbs.setSpacing(6)
        for path in photos[:THUMBNAILS]:
            label = QLabel()
            label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
            label.setPixmap(thumbnail(path))
            label.setToolTip(path.name)
            thumbs.addWidget(label)
        if count > THUMBNAILS:
            more = QLabel(f"+{count - THUMBNAILS}")
            more.setObjectName("muted")
            thumbs.addWidget(more)
        thumbs.addStretch(1)

        self.style_combo = QComboBox()
        for key, spec in STYLES.items():
            self.style_combo.addItem(spec.name, key)
        self.style_combo.setMaxVisibleItems(len(STYLES))
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(config.PHOTO_STYLE)))
        self.style_text = QLabel()
        self.style_text.setObjectName("muted")
        self.style_text.setWordWrap(True)
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style"))
        style_row.addWidget(self.style_combo)
        style_row.addWidget(self.style_text, 1)

        self.preview = PhotoView(photos[:PREVIEW_PHOTOS], config.PHOTO_STYLE, config.PHOTO_FILL, self)
        self.preview.setFixedSize(PREVIEW_SIZE)
        self._preview_timer = QTimer(self, interval=PREVIEW_STEP_MS, timeout=self._next_preview)

        self.order_combo = QComboBox()
        for key, name in ORDERS.items():
            self.order_combo.addItem(name, key)
        self.order_combo.setCurrentIndex(max(0, self.order_combo.findData(config.PHOTO_ORDER)))
        self.fill_check = QCheckBox("Fill the screen (crop the edges)")
        self.fill_check.setChecked(config.PHOTO_FILL)
        options = QHBoxLayout()
        options.addWidget(QLabel("Order"))
        options.addWidget(self.order_combo)
        options.addSpacing(18)
        options.addWidget(self.fill_check)
        options.addStretch(1)

        self.autoplay_check = QCheckBox("Play automatically, every")
        self.autoplay_check.setChecked(config.PHOTO_AUTOPLAY)
        seconds = BY_KEY["PHOTO_AUTOPLAY_SECONDS"]
        self.autoplay_seconds = QSpinBox()
        self.autoplay_seconds.setRange(int(seconds.minimum), int(seconds.maximum))
        self.autoplay_seconds.setSuffix(" s")
        self.autoplay_seconds.setValue(config.PHOTO_AUTOPLAY_SECONDS)
        self.loop_check = QCheckBox("Loop (start again after the last photo)")
        self.loop_check.setChecked(config.PHOTO_LOOP)
        playback = QHBoxLayout()
        playback.addWidget(self.autoplay_check)
        playback.addWidget(self.autoplay_seconds)
        playback.addSpacing(18)
        playback.addWidget(self.loop_check)
        playback.addStretch(1)
        if config.DEBATE_MODE:
            # Debate mode already times every photo.
            self.autoplay_check.setEnabled(False)
            self.autoplay_check.setToolTip("Debate mode sets the time for each photo.")
        self.autoplay_check.toggled.connect(self._update_playback)
        self._update_playback()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Start slideshow")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addLayout(thumbs)
        if skipped:
            note = QLabel(f"{skipped} selected file{'s are' if skipped != 1 else ' is'} not a photo and "
                          f"will be skipped.")
            note.setObjectName("muted")
            layout.addWidget(note)
        layout.addLayout(style_row)
        layout.addWidget(self.preview, 0, Qt.AlignHCenter)
        layout.addLayout(options)
        layout.addLayout(playback)
        if config.DEBATE_MODE:
            debate = QLabel("Debate mode is on: it sets the time for each photo, so auto play is off.")
            debate.setObjectName("muted")
            layout.addWidget(debate)
        hint = QLabel("During the slideshow: swipe, the arrow keys, a clicker or the mouse change photos. "
                      "S pauses auto play. Esc ends the slideshow.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        self.fill_check.toggled.connect(self._on_style_changed)
        self._on_style_changed()
        self._preview_timer.start()

    # -- preview ---------------------------------------------------------------------------

    def _on_style_changed(self, *_) -> None:
        style = self.style_combo.currentData()
        self.style_text.setText(STYLES[style].description)
        self.fill_check.setEnabled(STYLES[style].uses_fill)   # the other looks decide the fit themselves
        self.preview.set_style(style, self.fill_check.isChecked())

    def _update_playback(self, *_) -> None:
        self.autoplay_seconds.setEnabled(self.autoplay_check.isEnabled() and self.autoplay_check.isChecked())

    def _next_preview(self) -> None:
        if self.preview.count:
            self.preview.show_index((self.preview.index + 1) % self.preview.count, 1)

    def done(self, result: int) -> None:
        self._preview_timer.stop()
        self.preview.shutdown()
        super().done(result)

    # -- result ------------------------------------------------------------------------------

    def values(self) -> dict:
        return {
            "PHOTO_STYLE": self.style_combo.currentData(),
            "PHOTO_ORDER": self.order_combo.currentData(),
            "PHOTO_FILL": self.fill_check.isChecked(),
            "PHOTO_AUTOPLAY": self.autoplay_check.isChecked(),
            "PHOTO_AUTOPLAY_SECONDS": self.autoplay_seconds.value(),
            "PHOTO_LOOP": self.loop_check.isChecked(),
        }
