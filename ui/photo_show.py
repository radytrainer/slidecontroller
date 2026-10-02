"""
The photo slideshow: AirSlide shows the photos itself, full screen.

``PhotoView`` draws the photos in one of the STYLES and animates the change
from one photo to the next. It is used full screen (``PhotoShowWindow``) and
as the small live preview in the setup dialog.

A style is a recipe of three parts:

* transition - how one photo changes into the next (fade, slide, flip, wipe, ...)
* look       - how a photo is shown: plain (whole or filling the screen), a
               white print on a table, in front of a blurred copy of itself,
               in a carousel row, or with a slow Ken Burns pan and zoom
* tone       - colours: natural, warm sepia (vintage) or black and white

Photos are decoded in background threads, already scaled to the screen and
toned, so changing photos stays smooth with large camera photos. Phone photos
are turned upright (EXIF orientation) and animated GIFs play.

    plain                        print (polaroid)              carousel
    ┌──────────────────────┐     ┌──────────────────────┐      ┌──────────────────────┐
    │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│     │   ┌────────────┐     │      │░░┌──────────────┐░░│
    │▓▓▓▓▓▓ photo ▓▓▓▓▓▓▓▓▓│     │   │▓▓ photo ▓▓▓│     │      │░░│▓▓▓ photo ▓▓▓▓│░░│
    │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│     │   │  caption   │     │      │░░└──────────────┘░░│
    └──────────────────────┘     └───┴────────────┴─────┘      └──────────────────────┘
                                                               previous / next at the sides
"""

import math
import random
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QImageReader,
    QLinearGradient,
    QMovie,
    QPainter,
    QPainterPath,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

import config
from src.utils.gui_thread import run_on_gui
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Style:
    name: str
    description: str
    transition: str          # none, fade, slide, zoom, drop, flip, wipe, circle, tiles, blinds, carousel
    look: str = "plain"      # plain, kenburns, print, blur, carousel
    tone: str = ""           # "", "sepia", "mono"

    @property
    def uses_fill(self) -> bool:
        """Only plain photos can be shown whole or filling the screen; the other looks decide."""
        return self.look == "plain"


STYLES: dict[str, Style] = {
    "classic": Style("Classic", "Photos change instantly, like a projector.", "none"),
    "fade": Style("Fade", "Each photo gently fades into the next.", "fade"),
    "slide": Style("Slide", "Photos slide in from the side, like turning pages.", "slide"),
    "zoom": Style("Zoom", "The next photo softly zooms in.", "zoom"),
    "kenburns": Style("Ken Burns", "A slow pan and zoom across every photo, like a documentary.", "fade",
                      look="kenburns"),
    "polaroid": Style("Polaroid", "Framed prints dropped one after another on a dark table.", "drop",
                      look="print"),
    "blur": Style("Soft backdrop", "Each photo in front of a blurred copy of itself - great for portrait "
                  "phone photos, no black bars.", "fade", look="blur"),
    "carousel": Style("Carousel", "The photos glide past in a row; the previous and next ones peek in "
                      "at the sides.", "carousel", look="carousel"),
    "flip": Style("Flip", "Each photo turns over like a card to show the next.", "flip"),
    "wipe": Style("Wipe", "The next photo sweeps across the screen.", "wipe"),
    "circle": Style("Circle", "The next photo opens up from the middle in a growing circle.", "circle"),
    "tiles": Style("Mosaic", "The next photo appears tile by tile.", "tiles"),
    "blinds": Style("Blinds", "The next photo opens like window blinds.", "blinds"),
    "vintage": Style("Vintage", "Warm sepia tones and darkened corners, like old prints.", "fade", tone="sepia"),
    "mono": Style("Black & white", "Classic black-and-white photos with soft fades.", "fade", tone="mono"),
}

KEN_BURNS_ZOOM = 0.12              # zoom in by 12 % over the photo's time
KEN_BURNS_PAN = 0.03               # and move by 3 % of the screen
KEN_BURNS_OVERSCAN = 1.0 + KEN_BURNS_ZOOM
PAN_DIRECTIONS = ((1, 0.5), (-1, -0.5), (0.5, -1), (-0.5, 1))
CACHE_SIZE = 12                    # scaled photos kept in memory
TILE_COLUMNS = 8
BLIND_COUNT = 10
CAROUSEL_SLOT = 0.66               # distance between carousel photos (share of the width)
BLUR_SMALL = 48                    # the backdrop is shrunk to this size and enlarged again = blurred

# How a look scales the photo: (width share, height share, cover the box?)
LOOK_BOX = {
    "print": (0.64, 0.66, False),
    "blur": (0.94, 0.94, False),
    "carousel": (0.6, 0.78, False),
    "kenburns": (KEN_BURNS_OVERSCAN, KEN_BURNS_OVERSCAN, True),
}
LIVE_TRANSITIONS = {"fade", "slide", "zoom", "drop"}      # draw the new photo live (Ken Burns keeps moving)
FRAME_TRANSITIONS = {"flip", "wipe", "circle", "tiles", "blinds"}   # blend two finished frames


# -- loading (worker threads) --------------------------------------------------------------

def _read(path: Path) -> QImage | None:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)       # phone photos: apply the EXIF rotation
    image = reader.read()
    if image.isNull():
        log.warning("Could not open %s: %s", path.name, reader.errorString())
        return None
    return image


def _tone(image: QImage, tone: str) -> QImage:
    """Sepia or black and white, computed once per photo."""
    if not tone:
        return image
    image = image.convertToFormat(QImage.Format_RGB32)
    width, height, line = image.width(), image.height(), image.bytesPerLine()
    pixels = np.frombuffer(image.constBits(), np.uint8, count=line * height).reshape(height, line // 4, 4)
    b, g, r = (pixels[:, :width, c].astype(np.float32) for c in range(3))
    out = np.empty((height, width, 4), np.uint8)
    out[..., 3] = 255
    if tone == "mono":
        grey = 0.299 * r + 0.587 * g + 0.114 * b
        grey = np.clip((grey - 128) * 1.12 + 128, 0, 255)          # a little more contrast
        out[..., 0] = out[..., 1] = out[..., 2] = grey
    else:                                                          # sepia
        out[..., 2] = np.clip(0.393 * r + 0.769 * g + 0.189 * b, 0, 255)
        out[..., 1] = np.clip(0.349 * r + 0.686 * g + 0.168 * b, 0, 255)
        out[..., 0] = np.clip(0.272 * r + 0.534 * g + 0.131 * b, 0, 255)
    return QImage(out.tobytes(), width, height, width * 4, QImage.Format_RGB32).copy()


def _load(path: Path, size: QSize, cover: bool, tone: str) -> QImage | None:
    """Decode, scale to fit / cover ``size`` and tone a photo."""
    image = _read(path)
    if image is None:
        return None
    mode = Qt.KeepAspectRatioByExpanding if cover else Qt.KeepAspectRatio
    return _tone(image.scaled(size, mode, Qt.SmoothTransformation), tone)


def _load_backdrop(path: Path, size: QSize, tone: str) -> QImage | None:
    """A blurred copy that covers the screen: shrunk to a few pixels, then enlarged smoothly."""
    image = _read(path)
    if image is None:
        return None
    small = image.scaled(BLUR_SMALL, BLUR_SMALL, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    middle = small.scaled(max(1, size.width() // 6), max(1, size.height() // 6),
                          Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return _tone(middle.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation), tone)


def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class PhotoView(QWidget):
    def __init__(self, photos, style: str = "fade", fill: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.photos = [Path(p) for p in photos]
        self.style = style if style in STYLES else "fade"
        self.fill = fill
        self.index = 0
        self._from_index = 0                       # carousel: where the glide started
        self._direction = 1
        self._old: QPixmap | None = None           # the previous frame, during a change
        self._new: QPixmap | None = None           # the next frame (frame transitions)
        self._tile_delays: list[float] = []
        self._changing = False
        self._shown_at = time.monotonic()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="photos")
        self._loading: dict[tuple, Future] = {}
        self._waiting: set[tuple] = set()           # still loading; drawn when ready
        self._pixmaps: dict[tuple, QPixmap] = {}
        self._movie: QMovie | None = None
        self._movie_image: QImage | None = None
        self.ken_burns_seconds = float(config.PHOTO_KEN_BURNS_SECONDS)
        self.badge = ""                              # small text top right (e.g. "⏸ Paused")
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self.update)
        self._anim.finished.connect(self._on_change_done)
        self._ticker = QTimer(self, interval=33, timeout=self.update)   # Ken Burns motion

    # -- control -----------------------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self.photos)

    @property
    def spec(self) -> Style:
        return STYLES[self.style]

    def set_style(self, style: str, fill: bool) -> None:
        self.style = style if style in STYLES else "fade"
        self.fill = fill
        self._pixmaps.clear()
        self._shown_at = time.monotonic()
        self._update_ticker()
        self.update()

    def show_index(self, index: int, direction: int = 1) -> None:
        """Change to photo ``index`` (``count`` = the end screen) with the style's animation."""
        index = max(0, min(index, self.count))
        if index == self.index:
            return
        if self._anim.state() == QAbstractAnimation.Running:
            self._anim.stop()
        self._old = self._new = None
        self._changing = False
        transition = self.spec.transition
        animate = transition != "none" and self.isVisible() and not self.size().isEmpty()
        old = self.grab() if animate and transition != "carousel" else None   # the frame on screen now
        self._from_index = self.index
        self.index, self._direction = index, direction
        self._shown_at = time.monotonic()
        self._start_movie()
        ahead = 2 if self.spec.look == "carousel" else 1          # the carousel shows its neighbours
        for near in (index, *(index + direction * k for k in range(1, ahead + 1)), index - direction):
            self._preload(near)
        if animate:
            self._old = old
            if transition in FRAME_TRANSITIONS:
                self._new = self._render_frame()
            if transition == "tiles":
                rows = max(1, round(TILE_COLUMNS * self.height() / max(1, self.width())))
                chance = random.Random(index)
                self._tile_delays = [chance.uniform(0, 0.6) for _ in range(TILE_COLUMNS * rows)]
            self._changing = True
            self._anim.setDuration(max(1, config.PHOTO_TRANSITION_MS))
            self._anim.start()
        self._update_ticker()
        self.update()

    def shutdown(self) -> None:
        self._ticker.stop()
        self._anim.stop()
        if self._movie is not None:
            self._movie.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _on_change_done(self) -> None:
        self._old = self._new = None
        self._changing = False
        self.update()

    def _update_ticker(self) -> None:
        if self.spec.look == "kenburns" and self.index < self.count:
            self._ticker.start()
        else:
            self._ticker.stop()

    # -- photos ------------------------------------------------------------------------

    def _mode(self) -> str:
        look = self.spec.look
        if look != "plain":
            return look
        return "cover" if self.fill else "fit"

    def _target_size(self, mode: str) -> QSize:
        ratio = self.devicePixelRatioF()
        width, height = self.width() * ratio, self.height() * ratio
        if mode in LOOK_BOX:
            share_w, share_h, _ = LOOK_BOX[mode]
            return QSize(max(1, int(width * share_w)), max(1, int(height * share_h)))
        return QSize(max(1, int(width)), max(1, int(height)))

    def _cover(self, mode: str) -> bool:
        return mode == "cover" or (mode in LOOK_BOX and LOOK_BOX[mode][2])

    def _key(self, index: int, part: str = "photo") -> tuple:
        mode = "backdrop" if part == "backdrop" else self._mode()
        size = self._target_size("cover" if part == "backdrop" else mode)
        return index, mode, self.spec.tone, size.width(), size.height()

    def _preload(self, index: int) -> None:
        if not 0 <= index < self.count or self.size().isEmpty():
            return
        parts = ("photo", "backdrop") if self.spec.look == "blur" else ("photo",)
        for part in parts:
            key = self._key(index, part)
            if key in self._pixmaps or key in self._loading:
                continue
            tone = self.spec.tone
            if part == "backdrop":
                task = (_load_backdrop, self.photos[index], self._target_size("cover"), tone)
            else:
                mode = self._mode()
                task = (_load, self.photos[index], self._target_size(mode), self._cover(mode), tone)
            self._loading[key] = self._pool.submit(*task)

    def _pixmap(self, index: int, part: str = "photo", wait: bool = True) -> QPixmap | None:
        """The scaled photo. ``wait=False``: None if it is still loading (it is drawn
        as soon as it is ready) - for photos at the side, so the animation never stutters."""
        if part == "photo" and index == self.index and self._movie_image is not None:
            mode = self._mode()
            aspect = Qt.KeepAspectRatioByExpanding if self._cover(mode) else Qt.KeepAspectRatio
            image = self._movie_image.scaled(self._target_size(mode), aspect, Qt.SmoothTransformation)
            return self._to_pixmap(_tone(image, self.spec.tone))
        key = self._key(index, part)
        if key not in self._pixmaps:
            self._preload(index)
            if not wait and key in self._loading and not self._loading[key].done():
                if key not in self._waiting:
                    self._waiting.add(key)
                    self._loading[key].add_done_callback(self._repaint_when_loaded)
                return None
            self._waiting.discard(key)
            future = self._loading.pop(key, None)
            image = future.result() if future is not None else None   # waits only if not ready yet
            if image is None:
                return None
            self._pixmaps[key] = self._to_pixmap(image)
            while len(self._pixmaps) > CACHE_SIZE:
                self._pixmaps.pop(next(iter(self._pixmaps)))
        return self._pixmaps[key]

    def _repaint_when_loaded(self, _future) -> None:
        """Runs in the loading thread: ask the GUI thread to draw again."""
        def repaint() -> None:
            try:
                self.update()
            except RuntimeError:
                pass  # the slideshow was closed meanwhile

        try:
            run_on_gui(repaint, wait=False)
        except RuntimeError:
            pass  # the application is closing

    def _to_pixmap(self, image: QImage) -> QPixmap:
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        return pixmap

    @staticmethod
    def _logical_size(pixmap: QPixmap):
        return QRectF(pixmap.rect()).size() / pixmap.devicePixelRatio()

    def _start_movie(self) -> None:
        """Animated GIFs play while they are on screen."""
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
        self._movie, self._movie_image = None, None
        if self.index >= self.count or self.photos[self.index].suffix.lower() != ".gif":
            return
        movie = QMovie(str(self.photos[self.index]), parent=self)
        if movie.isValid() and movie.frameCount() != 1:
            movie.frameChanged.connect(self._on_movie_frame)
            self._movie = movie
            movie.start()

    def _on_movie_frame(self, _frame: int) -> None:
        if self._movie is not None:
            self._movie_image = self._movie.currentImage()
            self.update()

    # -- drawing: transitions ------------------------------------------------------------

    def _render_frame(self) -> QPixmap:
        """The new photo as a finished frame (for transitions that cut frames apart)."""
        ratio = self.devicePixelRatioF()
        frame = QPixmap(max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio)))
        frame.setDevicePixelRatio(ratio)
        painter = QPainter(frame)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self._draw_frame(painter, time.monotonic())
        painter.end()
        return frame

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        now = time.monotonic()
        t = float(self._anim.currentValue()) if self._changing else 1.0
        rect = QRectF(self.rect())
        transition = self.spec.transition
        if not self._changing or t >= 1.0:
            self._draw_frame(painter, now)
        elif transition == "carousel":
            self._draw_frame(painter, now, carousel_at=self._from_index + (self.index - self._from_index) * t)
        elif transition in FRAME_TRANSITIONS and self._old is not None and self._new is not None:
            getattr(self, f"_transition_{transition}")(painter, rect, t)
        elif self._old is not None:
            self._transition_live(painter, rect, t, now, transition)
        else:
            self._draw_frame(painter, now)
        if self.badge:
            self._draw_badge(painter, rect)
        painter.end()

    def _blit(self, painter: QPainter, pixmap: QPixmap, target: QRectF, source: QRectF | None = None) -> None:
        """Draw (part of) a full-frame pixmap; ``source`` is in widget coordinates."""
        ratio = pixmap.devicePixelRatio()
        source = source if source is not None else QRectF(self.rect())
        painter.drawPixmap(target, pixmap, QRectF(source.x() * ratio, source.y() * ratio,
                                                  source.width() * ratio, source.height() * ratio))

    def _transition_live(self, painter: QPainter, rect: QRectF, t: float, now: float, transition: str) -> None:
        if transition == "slide":
            shift = self._direction * rect.width()
            self._blit(painter, self._old, rect.translated(-shift * t, 0))
            painter.translate(shift * (1 - t), 0)
            self._draw_frame(painter, now)
            return
        self._blit(painter, self._old, rect)
        if transition == "zoom":
            painter.setOpacity(t)
            self._scale_about_center(painter, rect, 0.82 + 0.18 * t)
            self._draw_frame(painter, now)
        elif transition == "drop":                              # a print dropped on the earlier ones
            painter.setOpacity(min(1.0, t * 1.6))
            self._scale_about_center(painter, rect, 1.3 - 0.3 * t)
            self._draw_frame(painter, now, background=False)
        else:                                                   # fade
            painter.setOpacity(t)
            self._draw_frame(painter, now)

    @staticmethod
    def _scale_about_center(painter: QPainter, rect: QRectF, sx: float, sy: float | None = None) -> None:
        painter.translate(rect.center())
        painter.scale(sx, sx if sy is None else sy)
        painter.translate(-rect.center())

    def _transition_flip(self, painter: QPainter, rect: QRectF, t: float) -> None:
        """The frame turns like a card: it narrows to an edge, then the next one widens."""
        painter.fillRect(rect, Qt.black)
        frame, width = (self._old, 1 - 2 * t) if t < 0.5 else (self._new, 2 * t - 1)
        width = max(0.001, _smooth(width))
        painter.save()
        painter.setOpacity(0.55 + 0.45 * width)                 # a little darker while turned away
        self._scale_about_center(painter, rect, width, 1.0)
        self._blit(painter, frame, rect)
        painter.restore()

    def _transition_wipe(self, painter: QPainter, rect: QRectF, t: float) -> None:
        """The next frame sweeps in from the side it comes from, behind a soft bright edge."""
        self._blit(painter, self._old, rect)
        width = rect.width() * t
        new = QRectF(rect.right() - width, 0, width, rect.height()) if self._direction > 0 \
            else QRectF(0, 0, width, rect.height())
        self._blit(painter, self._new, new, new)
        edge_x = new.left() if self._direction > 0 else new.right()
        glow = QLinearGradient(edge_x - 30, 0, edge_x + 30, 0)
        glow.setColorAt(0.0, QColor(255, 255, 255, 0))
        glow.setColorAt(0.5, QColor(255, 255, 255, 90))
        glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(QRectF(edge_x - 30, 0, 60, rect.height()), glow)

    def _transition_circle(self, painter: QPainter, rect: QRectF, t: float) -> None:
        self._blit(painter, self._old, rect)
        radius = math.hypot(rect.width(), rect.height()) / 2 * t
        path = QPainterPath()
        path.addEllipse(rect.center(), radius, radius)
        painter.save()
        painter.setClipPath(path)
        self._blit(painter, self._new, rect)
        painter.restore()

    def _transition_tiles(self, painter: QPainter, rect: QRectF, t: float) -> None:
        """Tiles of the next frame appear in a random order, each growing into place."""
        self._blit(painter, self._old, rect)
        rows = max(1, len(self._tile_delays) // TILE_COLUMNS)
        tile_w, tile_h = rect.width() / TILE_COLUMNS, rect.height() / rows
        for number, delay in enumerate(self._tile_delays):
            progress = _clamp((t - delay) / 0.4)
            if progress <= 0:
                continue
            column, row = number % TILE_COLUMNS, number // TILE_COLUMNS
            tile = QRectF(column * tile_w, row * tile_h, tile_w, tile_h)
            scale = 0.6 + 0.4 * progress
            target = QRectF(0, 0, tile_w * scale, tile_h * scale)
            target.moveCenter(tile.center())
            painter.setOpacity(progress)
            self._blit(painter, self._new, target, tile)
        painter.setOpacity(1.0)

    def _transition_blinds(self, painter: QPainter, rect: QRectF, t: float) -> None:
        """Vertical slats of the next frame open from their middle, one shortly after another."""
        self._blit(painter, self._old, rect)
        slat = rect.width() / BLIND_COUNT
        for number in range(BLIND_COUNT):
            order = number if self._direction > 0 else BLIND_COUNT - 1 - number
            opened = _clamp((t - order * 0.025) / (1 - 0.025 * (BLIND_COUNT - 1)))
            if opened <= 0:
                continue
            strip = QRectF(number * slat + slat * (1 - opened) / 2, 0, slat * opened, rect.height())
            self._blit(painter, self._new, strip, strip)

    # -- drawing: looks ---------------------------------------------------------------------

    def _draw_frame(self, painter: QPainter, now: float, background: bool = True,
                    carousel_at: float | None = None) -> None:
        rect = QRectF(self.rect())
        look = self.spec.look
        if look == "carousel":
            self._draw_carousel(painter, rect, self.index if carousel_at is None else carousel_at)
            return
        if background:
            self._draw_background(painter, rect)
        if self.index >= self.count:
            self._draw_end(painter, rect)
            return
        pixmap = self._pixmap(self.index)
        if pixmap is None:
            self._draw_message(painter, rect, f"Could not open {self.photos[self.index].name}")
            return
        size = self._logical_size(pixmap)
        if look == "print":
            self._draw_print(painter, rect, pixmap, size)
            return
        target = QRectF(QPointF(0, 0), size)
        if look == "kenburns":
            progress = _smooth(min(1.0, (now - self._shown_at) / max(1.0, self.ken_burns_seconds)))
            zoom = (1.0 + KEN_BURNS_ZOOM * progress) / KEN_BURNS_OVERSCAN
            dx, dy = PAN_DIRECTIONS[self.index % len(PAN_DIRECTIONS)]
            if progress >= 1.0 and not self._changing:
                self._ticker.stop()
            target = QRectF(QPointF(0, 0), size * zoom)
            target.moveCenter(rect.center() + QPointF(dx, dy) * (KEN_BURNS_PAN * rect.width() * progress))
        else:
            target.moveCenter(rect.center())
        if look == "blur":
            self._draw_shadow(painter, target, max(4.0, rect.height() * 0.012))
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        if self.spec.tone == "sepia":
            self._draw_vignette(painter, rect)

    def _draw_background(self, painter: QPainter, rect: QRectF) -> None:
        look = self.spec.look
        if look == "print":
            gradient = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.75)
            gradient.setColorAt(0.0, QColor("#3a332d"))
            gradient.setColorAt(1.0, QColor("#15120f"))
            painter.fillRect(rect, gradient)
            return
        painter.fillRect(rect, Qt.black)
        if look == "blur" and self.index < self.count:
            backdrop = self._pixmap(self.index, "backdrop")
            if backdrop is not None:
                target = QRectF(QPointF(0, 0), self._logical_size(backdrop))
                target.moveCenter(rect.center())
                painter.drawPixmap(target, backdrop, QRectF(backdrop.rect()))
                painter.fillRect(rect, QColor(0, 0, 0, 110))       # darker, so the photo stands out

    def _draw_shadow(self, painter: QPainter, target: QRectF, unit: float) -> None:
        painter.save()
        painter.setPen(Qt.NoPen)
        for spread, alpha in ((unit * 2.5, 20), (unit * 1.5, 35), (unit * 0.6, 55)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(target.translated(0, unit).adjusted(-spread, -spread, spread, spread),
                                    spread, spread)
        painter.restore()

    def _draw_vignette(self, painter: QPainter, rect: QRectF) -> None:
        vignette = QRadialGradient(rect.center(), math.hypot(rect.width(), rect.height()) / 2)
        vignette.setColorAt(0.55, QColor(20, 12, 4, 0))
        vignette.setColorAt(1.0, QColor(20, 12, 4, 190))
        painter.fillRect(rect, vignette)

    def _draw_carousel(self, painter: QPainter, rect: QRectF, position: float) -> None:
        """A row of photos; ``position`` (may be between two photos) is in the middle."""
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0.0, QColor("#1c232b"))
        gradient.setColorAt(1.0, QColor("#07090b"))
        painter.fillRect(rect, gradient)
        slot = rect.width() * CAROUSEL_SLOT
        nearby = [i for i in range(math.floor(position) - 2, math.ceil(position) + 3)
                  if 0 <= i < self.count and abs(i - position) < 1.9]
        for number in sorted(nearby, key=lambda i: -abs(i - position)):     # the middle one last (on top)
            pixmap = self._pixmap(number, wait=number == self.index)       # side photos never hold up the glide
            if pixmap is None:
                continue
            distance = min(1.0, abs(number - position))
            scale = 1.0 - 0.28 * distance
            target = QRectF(QPointF(0, 0), self._logical_size(pixmap) * scale)
            target.moveCenter(rect.center() + QPointF((number - position) * slot, 0))
            painter.save()
            painter.setOpacity(1.0 - 0.55 * distance)
            self._draw_shadow(painter, target, max(3.0, rect.height() * 0.01))
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
            painter.restore()
        if self.index >= self.count and position >= self.count - 0.05:
            self._draw_end(painter, rect)

    def _draw_badge(self, painter: QPainter, rect: QRectF) -> None:
        painter.resetTransform()
        painter.setOpacity(1.0)
        size = max(9, int(rect.height() * 0.018))
        painter.setFont(QFont("Segoe UI", size, QFont.DemiBold))
        metrics = painter.fontMetrics()
        pad = size * 0.8
        box = QRectF(0, 0, metrics.horizontalAdvance(self.badge) + 2 * pad, metrics.height() + pad)
        box.moveTopRight(QPointF(rect.right() - pad * 2, rect.top() + pad * 2))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawRoundedRect(box, pad, pad)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(box, Qt.AlignCenter, self.badge)

    def _draw_print(self, painter: QPainter, rect: QRectF, pixmap: QPixmap, size) -> None:
        """A white-framed print, slightly turned, with a soft shadow and the file name."""
        unit = max(6.0, min(rect.width(), rect.height()) * 0.022)
        border, bottom = unit, unit * 4.2
        card = QRectF(0, 0, size.width() + 2 * border, size.height() + border + bottom)
        angle = ((self.index * 7919) % 9) - 4          # -4 .. 4 degrees, fixed per photo
        painter.save()
        painter.translate(rect.center())
        painter.rotate(angle)
        card.moveCenter(QPointF(0, 0))
        painter.setPen(Qt.NoPen)
        for spread, alpha in ((unit * 1.2, 26), (unit * 0.7, 40), (unit * 0.3, 60)):   # shadow
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(card.translated(unit * 0.5, unit * 0.8).adjusted(-spread, -spread, spread, spread),
                                    spread, spread)
        painter.setBrush(QColor("#fbfaf7"))
        painter.drawRect(card)
        photo = QRectF(card.left() + border, card.top() + border, size.width(), size.height())
        painter.drawPixmap(photo, pixmap, QRectF(pixmap.rect()))
        font = QFont("Segoe Print", max(8, int(unit * 0.95)))
        painter.setFont(font)
        painter.setPen(QColor("#5b5650"))
        caption = QRectF(card.left(), photo.bottom(), card.width(), bottom)
        name = painter.fontMetrics().elidedText(self.photos[self.index].stem, Qt.ElideRight, int(card.width() * 0.8))
        painter.drawText(caption, Qt.AlignCenter, name)
        painter.restore()

    def _draw_end(self, painter: QPainter, rect: QRectF) -> None:
        self._draw_message(painter, rect, "End of slideshow", "Swipe back, or press Esc to finish.")

    def _draw_message(self, painter: QPainter, rect: QRectF, title: str, detail: str = "") -> None:
        size = max(10, int(rect.height() * 0.035))
        painter.setPen(QColor("#e6edf3"))
        painter.setFont(QFont("Segoe UI", size, QFont.DemiBold))
        painter.drawText(rect.adjusted(0, 0, 0, -size * 2), Qt.AlignCenter, title)
        if detail:
            painter.setPen(QColor("#8b98a5"))
            painter.setFont(QFont("Segoe UI", max(8, int(size * 0.55))))
            painter.drawText(rect.adjusted(0, size * 2, 0, 0), Qt.AlignCenter, detail)


def presentation_screen():
    """The screen the audience sees: the biggest secondary screen (projector), else the primary."""
    primary = QGuiApplication.primaryScreen()
    others = [s for s in QGuiApplication.screens() if s is not primary]
    if not others:
        return primary
    return max(others, key=lambda s: s.geometry().width() * s.geometry().height())


class PhotoShowWindow(PhotoView):
    """The full-screen slideshow. Keys, clicker and mouse work like in PowerPoint; Esc ends it."""

    next_requested = Signal()
    previous_requested = Signal()
    first_requested = Signal()
    last_requested = Signal()
    closed = Signal()

    NEXT_KEYS = {Qt.Key_Right, Qt.Key_Down, Qt.Key_Space, Qt.Key_PageDown, Qt.Key_Return, Qt.Key_Enter, Qt.Key_N}
    PREVIOUS_KEYS = {Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp, Qt.Key_Backspace, Qt.Key_P}

    def __init__(self, photos, style: str = "fade", fill: bool = False, autoplay_seconds: float = 0):
        """autoplay_seconds > 0: the next photo is requested after that long."""
        super().__init__(photos, style, fill, None)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle(f"{config.APP_NAME} photo slideshow")
        self.setCursor(Qt.BlankCursor)
        self._closed = False
        self.autoplay_seconds = autoplay_seconds
        self.autoplay_paused = False
        self._autoplay = QTimer(self, singleShot=True, timeout=self.next_requested.emit)
        if autoplay_seconds > 0:
            # The slow Ken Burns move lasts exactly as long as the photo is shown.
            self.ken_burns_seconds = autoplay_seconds + config.PHOTO_TRANSITION_MS / 1000

    def show_index(self, index: int, direction: int = 1) -> None:
        super().show_index(index, direction)
        self._restart_autoplay()     # a swipe or key also gives the new photo its full time

    def toggle_autoplay(self) -> None:
        """S key, like PowerPoint's automatic show."""
        if self.autoplay_seconds <= 0:
            return
        self.autoplay_paused = not self.autoplay_paused
        self.badge = "⏸  Paused - press S to continue" if self.autoplay_paused else ""
        self._restart_autoplay()
        self.update()

    def _restart_autoplay(self) -> None:
        self._autoplay.stop()
        if self.autoplay_seconds > 0 and not self.autoplay_paused and self.index < self.count and not self._closed:
            self._autoplay.start(int(self.autoplay_seconds * 1000))

    def present(self) -> None:
        screen = presentation_screen()
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        for index in (0, 1, 2):
            self._preload(index)
        self._start_movie()
        self._update_ticker()
        self._shown_at = time.monotonic()
        self._restart_autoplay()
        self._focus()
        QTimer.singleShot(400, self._focus)   # after AirSlide's own window has been minimised

    def _focus(self) -> None:
        if self.isVisible():
            self.raise_()
            self.activateWindow()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self.close()
        elif key in self.NEXT_KEYS:
            self.next_requested.emit()
        elif key in self.PREVIOUS_KEYS:
            self.previous_requested.emit()
        elif key == Qt.Key_Home:
            self.first_requested.emit()
        elif key == Qt.Key_End:
            self.last_requested.emit()
        elif key == Qt.Key_S:
            self.toggle_autoplay()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.next_requested.emit()
        elif event.button() == Qt.RightButton:
            self.previous_requested.emit()

    def wheelEvent(self, event) -> None:
        (self.next_requested if event.angleDelta().y() < 0 else self.previous_requested).emit()

    def closeEvent(self, event) -> None:
        if not self._closed:
            self._closed = True
            self._autoplay.stop()
            self.shutdown()
            self.closed.emit()
        super().closeEvent(event)


def describe(style: str) -> str:
    spec = STYLES.get(style, STYLES["fade"])
    return f"{spec.name} - {spec.description}"
