"""
Photo slideshow controller: AirSlide shows the photos itself.

Like the PowerPoint and PDF controllers it is driven by next_slide() /
previous_slide() - from the gesture thread, the debate timer, or the
slideshow window's own keys. The current photo is kept here (thread-safe);
the window (GUI thread) only draws it.

    position()   (3, 12)  = photo 3 of 12;  (13, 12) = the "End of slideshow" screen

Options (config): PHOTO_LOOP - after the last photo the first comes again (no
end screen); PHOTO_AUTOPLAY - the window requests the next photo every
PHOTO_AUTOPLAY_SECONDS (not in debate mode, which times the photos itself).
"""

import threading
from pathlib import Path

import config
from src.presentation.base import PresentationController, PresentationOpenError
from src.utils.gui_thread import run_on_gui
from src.utils.logger import get_logger

log = get_logger(__name__)


class PhotoController(PresentationController):
    app_name = "AirSlide photo slideshow"

    def __init__(self) -> None:
        super().__init__()
        self.photos: list[Path] = []
        self._index = 0                  # 0-based; == len(photos) on the end screen
        self._running = False
        self._window = None
        self._hwnd: int | None = None
        self._lock = threading.Lock()

    # -- PresentationController ---------------------------------------------------------

    def open(self, file_path) -> None:
        """``file_path``: the list of photos (already checked and ordered)."""
        paths = file_path if isinstance(file_path, (list, tuple)) else [file_path]
        self.photos = [Path(p) for p in paths]
        if not self.photos:
            raise PresentationOpenError("No photos selected.")
        self.file_path = self.photos[0]
        self._index = 0

    def start(self) -> None:
        if not self.photos:
            raise PresentationOpenError("No photos selected.")
        run_on_gui(self._show_window)
        autoplay = self.autoplay_seconds()
        log.info("Photo slideshow started (%d photos, style %s%s%s)", len(self.photos), config.PHOTO_STYLE,
                 f", auto play every {autoplay:g} s" if autoplay else "", ", loop" if self.loop else "")

    def next_slide(self) -> bool:
        return self._move(+1)

    def previous_slide(self) -> bool:
        return self._move(-1)

    def go_to(self, index: int) -> bool:
        """0-based photo number (keys Home / End)."""
        with self._lock:
            if not self._running:
                return False
            target = max(0, min(index, len(self.photos) - 1))
            direction = 1 if target >= self._index else -1
            self._index = target
        self._show(target, direction)
        return True

    def close(self) -> None:
        with self._lock:
            self._running = False
        if self._window is not None:
            try:
                run_on_gui(self._close_window)
            except (RuntimeError, TimeoutError) as exc:
                log.warning("Could not close the slideshow window: %s", exc)

    @property
    def is_running(self) -> bool:
        return self._running

    def position(self) -> tuple[int, int] | None:
        with self._lock:
            return (self._index + 1, len(self.photos)) if self._running else None

    def window_handle(self) -> int | None:
        return self._hwnd if self._running else None

    # -- internals -----------------------------------------------------------------------

    @property
    def loop(self) -> bool:
        return config.PHOTO_LOOP

    @staticmethod
    def autoplay_seconds() -> float:
        """0 = no auto play. Debate mode times the photos itself."""
        return config.PHOTO_AUTOPLAY_SECONDS if config.PHOTO_AUTOPLAY and not config.DEBATE_MODE else 0

    def _move(self, step: int) -> bool:
        with self._lock:
            if not self._running:
                return False
            count = len(self.photos)
            if self.loop:
                # After the last photo comes the first again (and back from the first to the last).
                target = (min(self._index, count - 1) + step) % count
            else:
                # The end screen (index == count) comes after the last photo, like PowerPoint's.
                target = max(0, min(self._index + step, count))
            if target == self._index:
                return True              # first photo / end screen, or only one photo
            self._index = target
        self._show(target, step)
        return True

    def _show(self, index: int, direction: int) -> None:
        window = self._window
        if window is not None:
            run_on_gui(lambda: window.show_index(index, direction), wait=False)

    def _show_window(self) -> None:
        from ui.photo_show import PhotoShowWindow

        window = PhotoShowWindow(self.photos, config.PHOTO_STYLE, config.PHOTO_FILL, self.autoplay_seconds())
        window.next_requested.connect(self.next_slide)
        window.previous_requested.connect(self.previous_slide)
        window.first_requested.connect(lambda: self.go_to(0))
        window.last_requested.connect(lambda: self.go_to(len(self.photos) - 1))
        window.closed.connect(self._on_window_closed)
        self._window = window
        with self._lock:
            self._index = 0
            self._running = True
        window.present()
        self._hwnd = int(window.winId())

    def _on_window_closed(self) -> None:
        """Esc in the slideshow (or AirSlide closed it)."""
        with self._lock:
            self._running = False
        log.info("Photo slideshow window closed")

    def _close_window(self) -> None:
        window, self._window = self._window, None
        if window is not None:
            window.close()
            window.deleteLater()
        self._hwnd = None
