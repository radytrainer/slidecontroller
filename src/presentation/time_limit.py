"""
Optional time limit for a normal (gesture) presentation.

The presenter spends the time on the slides as they like; only the total
counts. After the limit the presentation runs over time and alerts fire once
each, e.g. with a 20 minute limit::

    20:00  time is up        (the timer turns red and counts the overtime)
    22:00  alert 1           +2 min  warning
    23:00  alert 2           +3 min  warning
    25:00  alert 3 (stop)    +5 min  the presentation is ended

    limit = TimeLimit(1200, warnings=(120, 180), stop_after=300)
    limit.start()
    for alert in limit.tick():          # called a few times per second
        ...
"""

import time
from dataclasses import dataclass
from typing import Callable

from src.presentation.debate import format_seconds


@dataclass(frozen=True)
class OvertimeAlert:
    number: int      # 1, 2, 3 ...
    overtime: int    # seconds over the limit when it fires
    stop: bool       # True = end the presentation now
    count: int       # number of alerts in total


class TimeLimit:
    def __init__(self, limit_seconds: int, warnings: tuple[int, ...] = (120, 180), stop_after: int = 300,
                 clock: Callable[[], float] = time.monotonic):
        """stop_after = 0: only warn, never end the presentation."""
        self.limit = int(limit_seconds)
        self.stop_after = int(stop_after)
        self._clock = clock
        marks = sorted({int(w) for w in warnings if w > 0 and (not stop_after or w < stop_after)})
        count = len(marks) + (1 if stop_after else 0)
        self.alerts = [OvertimeAlert(n, mark, False, count) for n, mark in enumerate(marks, start=1)]
        if stop_after:
            self.alerts.append(OvertimeAlert(count, self.stop_after, True, count))
        self._next = 0
        self._started = 0.0
        self._paused_at: float | None = None

    def start(self) -> None:
        self._started = self._clock()
        self._paused_at = None
        self._next = 0

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def pause(self) -> None:
        if not self.paused:
            self._paused_at = self._clock()

    def resume(self) -> None:
        if self.paused:
            self._started += self._clock() - self._paused_at   # the pause does not count
            self._paused_at = None

    def elapsed(self) -> float:
        return (self._paused_at if self.paused else self._clock()) - self._started

    def remaining(self) -> float:
        """Seconds left; negative once over time."""
        return self.limit - self.elapsed()

    def overtime(self) -> float:
        return max(0.0, -self.remaining())

    def tick(self) -> list[OvertimeAlert]:
        """Alerts that are due now (each is returned only once)."""
        due = []
        while self._next < len(self.alerts) and self.overtime() >= self.alerts[self._next].overtime:
            due.append(self.alerts[self._next])
            self._next += 1
        return due


def format_duration(seconds: int) -> str:
    """120 -> '2 min', 90 -> '1:30 min'."""
    seconds = int(seconds)
    return f"{seconds // 60} min" if seconds % 60 == 0 else f"{format_seconds(seconds)} min"


def alert_message(alert: OvertimeAlert, stop_after: int) -> str:
    over = format_duration(alert.overtime)
    if alert.stop:
        return f"⏹  {over} over time\nThe presentation has ended."
    if stop_after:
        return f"⚠  {over} over time  ({alert.number}/{alert.count})\n" \
               f"Please finish. The presentation ends at {format_duration(stop_after)} over."
    return f"⚠  {over} over time\nPlease finish your presentation."
