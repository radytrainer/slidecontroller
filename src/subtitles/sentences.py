"""
Speaker notes -> subtitle lines, one sentence at a time.

    split_sentences("Welcome everyone. Today we cover three things!")
    -> ["Welcome everyone.", "Today we cover three things!"]

Sentences end at . ! ? … and the Khmer signs ។ ៕ (which are often not followed
by a space). Every line of the notes is its own subtitle too. Sentences longer
than ``max_chars`` are cut, at a comma or similar if possible, so a subtitle
never needs more than about two lines.
"""

import re

import config

# After . ! ? … (a closing quote or bracket stays with the sentence), or after ។ ៕.
_SENTENCE_END = re.compile(r"(?<=[.!?…][\"'”’)\]])\s+|(?<=[.!?…])\s+|(?<=[។៕])\s*")
_SOFT_BREAKS = (", ", "; ", ": ", " - ", " – ", " — ", "، ")
_MIN_FRAGMENT = 3    # "1." or "a)" belongs to the sentence after it


def split_sentences(text: str, max_chars: int | None = None) -> list[str]:
    max_chars = max_chars or config.SUBTITLE_MAX_CHARS
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x0b", "\n")
    sentences: list[str] = []
    for line in text.split("\n"):
        line = " ".join(line.split())
        if not line:
            continue
        pending = ""
        for part in _SENTENCE_END.split(line):
            part = part.strip()
            if not part:
                continue
            part = f"{pending} {part}".strip() if pending else part
            if len(part) <= _MIN_FRAGMENT:
                pending = part
                continue
            pending = ""
            sentences.extend(_chunk(part, max_chars))
        if pending:
            sentences.append(pending)
    return sentences


def _chunk(sentence: str, max_chars: int) -> list[str]:
    chunks = []
    while len(sentence) > max_chars:
        window = sentence[:max_chars + 1]
        cut = max((window.rfind(mark) + len(mark.rstrip()) for mark in _SOFT_BREAKS), default=-1)
        if cut < max_chars * 0.4:
            cut = window.rfind(" ")
        if cut < max_chars * 0.4:
            cut = max_chars  # no break (e.g. Khmer without spaces): cut at the limit
        chunks.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    if sentence:
        chunks.append(sentence)
    return chunks


def estimate_seconds(sentence: str, words_per_minute: float | None = None,
                     minimum: float | None = None) -> float:
    """About how long it takes to say the sentence."""
    words_per_minute = words_per_minute or config.SUBTITLE_WORDS_PER_MINUTE
    minimum = config.SUBTITLE_MIN_SECONDS if minimum is None else minimum
    words = len(sentence.split())
    if words * 12 < len(sentence):
        # Hardly any spaces: a script that does not separate words (e.g. Khmer).
        # Count about five characters per word.
        words = len(sentence) / 5
    return max(minimum, words * 60.0 / words_per_minute)
