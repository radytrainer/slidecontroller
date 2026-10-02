"""
Which sentence of the notes to show, from when the presenter speaks.

The words are not recognised. Each sentence has an estimated speaking time;
the pacer counts how long the presenter has spoken during the sentence:

* a pause after at least ``advance_at`` of that time finishes the sentence,
  and the next one appears when the presenter speaks again;
* speaking on without a pause for ``force_at`` of the time moves on anyway;
* nothing is shown before the presenter speaks on the slide, after the last
  sentence, or when they have been quiet for ``hide_after`` seconds.

    pacer.load(["Welcome everyone.", "Today we cover three things."])
    text = pacer.update(speaking=True, now=12.3)   # for every bit of audio
"""

from dataclasses import dataclass

import config
from src.subtitles.sentences import estimate_seconds


@dataclass(frozen=True)
class Sentence:
    text: str
    seconds: float


class SubtitlePacer:
    def __init__(self, advance_at: float | None = None, force_at: float | None = None,
                 hide_after: float | None = None):
        self.advance_at = config.SUBTITLE_ADVANCE_AT if advance_at is None else advance_at
        self.force_at = config.SUBTITLE_FORCE_AT if force_at is None else force_at
        self.hide_after = config.SUBTITLE_HIDE_AFTER_SECONDS if hide_after is None else hide_after
        self.load([])

    def load(self, sentences: list[str], words_per_minute: float | None = None) -> None:
        """Start over with the sentences of a (new) slide."""
        self.sentences = [Sentence(s, estimate_seconds(s, words_per_minute)) for s in sentences]
        self.index = 0
        self._spoken = 0.0
        self._finished = False       # current sentence said, waiting for the next one to start
        self._last: float | None = None
        self._last_voice: float | None = None

    @property
    def done(self) -> bool:
        return self.index >= len(self.sentences)

    def update(self, speaking: bool, now: float) -> str | None:
        """The subtitle to show now (None = nothing)."""
        dt = 0.0 if self._last is None else max(0.0, now - self._last)
        self._last = now
        if self.done:
            return None
        if speaking:
            if self._finished:
                self._next()                              # speaking again: next sentence
                if self.done:
                    return None
            self._spoken += dt
            self._last_voice = now
            if self._spoken >= self.sentences[self.index].seconds * self.force_at:
                self._next()                              # long without a pause
                if self.done:
                    return None
                self._last_voice = now
        elif self._spoken >= self.sentences[self.index].seconds * self.advance_at:
            self._finished = True                         # paused at the end of the sentence
            if self.index == len(self.sentences) - 1 and now - self._last_voice > self.hide_after:
                self._next()                              # the last sentence is over
                return None

        if self._last_voice is None or (not speaking and now - self._last_voice > self.hide_after):
            return None
        return self.sentences[self.index].text

    def _next(self) -> None:
        self.index += 1
        self._spoken = 0.0
        self._finished = False
