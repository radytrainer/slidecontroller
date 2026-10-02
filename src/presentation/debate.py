"""
Debate presentation: every slide gets a fixed time, then the show moves on.

    plan = DebatePlan(default_seconds=60, per_slide={1: 30, 4: 120})
    plan = DebatePlan.from_total(600, slide_count=8)    # or: 10 minutes shared equally
    timer = DebateTimer(plan)
    timer.start_slide(1)
    ...
    if timer.tick(slide, total):      # called a few times per second
        manager.advance_slide()

The timer follows the slide actually on screen: when the presenter swipes to
another slide, ``tick`` notices the new slide number and restarts the
countdown with that slide's time.

``count_slides`` reads the number of slides from the file itself, so the
per-slide times can be edited before PowerPoint / the PDF viewer is started.
"""

import math
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.utils.logger import get_logger

log = get_logger(__name__)

_PPTX_SLIDE = re.compile(r"ppt/slides/slide\d+\.xml")
_PPTX_HIDDEN = re.compile(rb"<p:sld\b[^>]*\bshow=\"(0|false)\"")
_PDF_PAGE = re.compile(rb"/Type\s*/Page(?![A-Za-z])")


@dataclass
class DebatePlan:
    default_seconds: int
    per_slide: dict[int, int] = field(default_factory=dict)   # slide number (1-based) -> seconds

    def seconds_for(self, slide: int) -> int:
        return self.per_slide.get(slide, self.default_seconds)

    @classmethod
    def from_total(cls, total_seconds: int, slide_count: int) -> "DebatePlan":
        times = split_total(total_seconds, slide_count)
        return cls(min(times.values()), times)


def split_total(total_seconds: int, slide_count: int) -> dict[int, int]:
    """Divide the total time equally: 600 s / 7 slides -> 86 s for slides 1-5, 85 s for 6-7.

    The first slides get the leftover seconds, so the times add up to the total exactly
    (every slide gets at least 1 s)."""
    slide_count = max(1, slide_count)
    base, extra = divmod(int(total_seconds), slide_count)
    return {n: max(1, base + (1 if n <= extra else 0)) for n in range(1, slide_count + 1)}


class DebateTimer:
    """Countdown for the current slide. Not thread-safe: use from the GUI thread."""

    def __init__(self, plan: DebatePlan, clock: Callable[[], float] = time.monotonic):
        self.plan = plan
        self._clock = clock
        self.slide = 0
        self.finished = False            # time is up on the last slide
        self._deadline = 0.0
        self._paused_left: float | None = None

    @property
    def paused(self) -> bool:
        return self._paused_left is not None

    def start_slide(self, slide: int) -> None:
        self.slide = slide
        self.finished = False
        seconds = float(self.plan.seconds_for(slide))
        if self.paused:
            self._paused_left = seconds
        else:
            self._deadline = self._clock() + seconds

    def pause(self) -> None:
        if not self.paused:
            self._paused_left = self.remaining()

    def resume(self) -> None:
        if self.paused:
            self._deadline = self._clock() + self._paused_left
            self._paused_left = None

    def remaining(self) -> float:
        if self.paused:
            return self._paused_left
        return max(0.0, self._deadline - self._clock())

    def tick(self, slide: int, total: int | None) -> bool:
        """Follow the slide on screen. True = time is up, move to the next slide now."""
        if total is not None and slide > total:
            self.finished = True         # "end of slide show" screen
            return False
        if slide != self.slide:
            self.start_slide(slide)
        if self.paused or self.finished or self.remaining() > 0:
            return False
        if total is not None and slide >= total:
            self.finished = True         # the last slide stays on screen
            return False
        self.start_slide(slide + 1)
        return True


def format_seconds(seconds: float) -> str:
    """62.3 -> '1:03' (rounded up, so '0:00' only shows when the time is really up)."""
    whole = max(0, math.ceil(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def count_slides(file_path: str | Path) -> int | None:
    """Number of slides (visible slides of a .pptx, pages of a .pdf), or None if unknown."""
    path = Path(file_path)
    try:
        if path.suffix.lower() == ".pptx":
            return _count_pptx_slides(path)
        if path.suffix.lower() == ".pdf":
            return _count_pdf_pages(path)
    except (OSError, zipfile.BadZipFile) as exc:
        log.warning("Could not count the slides of %s: %s", path.name, exc)
    return None


def _count_pptx_slides(path: Path) -> int | None:
    count = 0
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            if not _PPTX_SLIDE.fullmatch(name):
                continue
            with package.open(name) as slide:
                head = slide.read(4096)   # the <p:sld ...> start tag holds show="0" for hidden slides
            if not _PPTX_HIDDEN.search(head):
                count += 1
    return count or None


def _count_pdf_pages(path: Path) -> int | None:
    # Page objects inside compressed object streams cannot be seen this way;
    # then the count is unknown and the user enters it.
    count = len(_PDF_PAGE.findall(path.read_bytes()))
    return count or None
