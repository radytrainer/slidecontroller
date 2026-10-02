"""Subtitles: notes -> sentences, voice detection, pacing sentence by sentence."""

import numpy as np
import pytest

from src.subtitles.pacer import SubtitlePacer
from src.subtitles.sentences import estimate_seconds, split_sentences
from src.subtitles.voice import VoiceDetector

# -- sentences ------------------------------------------------------------------------------

def test_split_english_sentences():
    notes = ("Welcome everyone. Over the next three weeks, 24 groups will build apps! "
             "Ready?\rTransition: first, the program in numbers.")
    assert split_sentences(notes) == [
        "Welcome everyone.",
        "Over the next three weeks, 24 groups will build apps!",
        "Ready?",
        "Transition: first, the program in numbers.",
    ]


def test_split_keeps_quotes_and_numbering_together():
    assert split_sentences('He said "stop." Then left.\n1. First point.') == [
        'He said "stop."', "Then left.", "1. First point.",
    ]


def test_split_khmer_sentences():
    notes = "សូមស្វាគមន៍។ថ្ងៃនេះយើងនឹងនិយាយអំពីគម្រោង។ សូមអរគុណ៕"
    assert split_sentences(notes) == ["សូមស្វាគមន៍។", "ថ្ងៃនេះយើងនឹងនិយាយអំពីគម្រោង។", "សូមអរគុណ៕"]


def test_long_sentence_is_cut_at_a_comma():
    sentence = ("This project connects a webcam to a gesture model, which then controls the slides "
                "without touching anything, and it works from far away.")
    parts = split_sentences(sentence, max_chars=90)
    assert parts[0].endswith("model,")
    assert all(len(p) <= 90 for p in parts)
    assert " ".join(parts) == sentence


def test_long_text_without_spaces_is_cut_at_the_limit():
    parts = split_sentences("ក" * 250, max_chars=100)
    assert [len(p) for p in parts] == [100, 100, 50]


def test_empty_notes():
    assert split_sentences("") == [] and split_sentences(" \r\n ") == []


def test_estimate_seconds():
    assert estimate_seconds("one two three four five six seven", 140, 1.0) == pytest.approx(3.0)
    assert estimate_seconds("Hi.", 140, 1.2) == 1.2                  # minimum
    assert estimate_seconds("ក" * 50, 150, 0) == pytest.approx(4.0)  # 50 chars ~ 10 words


# -- voice detection --------------------------------------------------------------------

def feed(detector, level, seconds, step=0.02):
    state = False
    for _ in range(round(seconds / step)):
        state = detector.update(level, step)
    return state


def test_voice_start_and_pause():
    detector = VoiceDetector(min_level=0.01, noise_ratio=3, start_seconds=0.1, pause_seconds=0.4)
    assert feed(detector, 0.004, 1.0) is False     # quiet room
    assert feed(detector, 0.1, 0.06) is False      # a click is not speech
    feed(detector, 0.004, 0.5)                     # (the click has faded)
    assert feed(detector, 0.1, 0.2) is True        # speaking
    assert feed(detector, 0.004, 0.2) is True      # a gap between words
    assert feed(detector, 0.004, 0.6) is False     # a real pause (after the loudness has faded)


def test_voice_bridges_dips_between_syllables():
    detector = VoiceDetector(min_level=0.003, noise_ratio=3, start_seconds=0.12, pause_seconds=0.35)
    feed(detector, 0.001, 1.0)
    for _ in range(20):                            # syllables: 80 ms loud, 60 ms dip
        feed(detector, 0.008, 0.08)
        state = feed(detector, 0.001, 0.06)
    assert state is True                           # still speaking through the dips


def test_voice_threshold_follows_background_noise():
    detector = VoiceDetector(min_level=0.01, noise_ratio=3, start_seconds=0.1, pause_seconds=0.4)
    feed(detector, 0.03, 20.0)                     # noisy room (air conditioning), learned in seconds
    assert detector.threshold == pytest.approx(0.09, rel=0.1)
    assert feed(detector, 0.05, 1.0) is False      # noise alone is not speech
    assert feed(detector, 0.3, 0.3) is True


def test_presenter_already_talking_when_subtitles_start():
    """The first sound must not be taken as background noise."""
    detector = VoiceDetector(min_level=0.003, noise_ratio=3, start_seconds=0.12, pause_seconds=0.35)
    assert feed(detector, 0.2, 0.3) is True


def test_long_speech_does_not_become_background_noise():
    detector = VoiceDetector(min_level=0.003, noise_ratio=3, start_seconds=0.12, pause_seconds=0.35)
    for _ in range(60):                            # 60 s of talking: words with short dips between them
        feed(detector, 0.05, 0.8)
        state = feed(detector, 0.002, 0.1)
    assert state is True
    assert detector.threshold < 0.05 / 2          # the voice stays clearly above the threshold


# -- pacing ---------------------------------------------------------------------------------

class Talk:
    """Drives a pacer like the microphone does: 20 ms steps."""

    def __init__(self, pacer):
        self.pacer, self.now, self.shown = pacer, 0.0, None

    def run(self, speaking, seconds):
        for _ in range(round(seconds / 0.02)):
            self.now += 0.02
            self.shown = self.pacer.update(speaking, self.now)
        return self.shown


@pytest.fixture
def talk():
    pacer = SubtitlePacer(advance_at=0.6, force_at=1.6, hide_after=2.5)
    # 7 words at 140 words/min = 3 s each
    pacer.load(["one two three four five six seven.", "eight nine ten eleven twelve thirteen fourteen."], 140)
    return Talk(pacer)


def test_nothing_before_the_presenter_speaks(talk):
    assert talk.run(False, 5) is None


def test_sentence_by_sentence_at_pauses(talk):
    assert talk.run(True, 1.0) == "one two three four five six seven."
    assert talk.run(False, 0.5) == "one two three four five six seven."   # too early: same sentence
    assert talk.run(True, 1.2) == "one two three four five six seven."    # 2.2 s spoken > 60 % of 3 s
    assert talk.run(False, 0.5) == "one two three four five six seven."   # pause: stays until ...
    assert talk.run(True, 0.1) == "eight nine ten eleven twelve thirteen fourteen."  # ... speaking again
    assert talk.pacer.index == 1


def test_long_speech_without_pause_moves_on(talk):
    talk.run(True, 4.7)                           # 1.6 x 3 s = 4.8 s
    assert talk.pacer.index == 0
    assert talk.run(True, 0.2) == "eight nine ten eleven twelve thirteen fourteen."


def test_hidden_when_quiet_and_after_the_last_sentence(talk):
    talk.run(True, 1.0)
    assert talk.run(False, 3.0) is None           # quiet for longer than hide_after
    assert talk.run(True, 1.0) is not None        # speaking again: back (same sentence)
    talk.run(False, 0.5)
    talk.run(True, 3.0)                           # last sentence
    assert talk.pacer.index == 1
    assert talk.run(False, 3.0) is None
    assert talk.pacer.done
    assert talk.run(True, 2.0) is None            # nothing more to show on this slide


# -- microphone ---------------------------------------------------------------------------

@pytest.fixture
def mic():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from src.subtitles.microphone import Microphone

    microphone = Microphone()
    microphone._rate, microphone._channels, microphone._dtype = 1000, 2, np.float32
    microphone.name = "USB dongle"
    levels, errors = [], []
    microphone.level.connect(lambda level, seconds: levels.append(level))
    microphone.error.connect(errors.append)
    microphone.levels, microphone.errors = levels, errors
    return microphone


class FakeIO:
    def __init__(self, samples):
        self.data = np.asarray(samples, dtype=np.float32).tobytes()

    def readAll(self):
        from PySide6.QtCore import QByteArray

        data, self.data = self.data, b""
        return QByteArray(data)


def test_microphone_uses_the_loudest_channel(mic):
    # left channel silent, right channel carries the voice
    stereo = np.column_stack([np.zeros(200), np.full(200, 0.1)]).ravel()
    mic._io = FakeIO(stereo)
    mic._checked_seconds = 99   # silence check done
    mic._read()
    assert mic.levels and all(level == pytest.approx(0.1) for level in mic.levels)


def test_switch_on_click_is_ignored(mic):
    click_then_quiet = np.concatenate([np.full(2 * 100, 0.5), np.full(2 * 500, 0.001)])  # 0.1 s click
    mic._io = FakeIO(click_then_quiet)
    mic._read()
    assert mic.levels and max(mic.levels) == pytest.approx(0.001)
    assert len(mic.levels) == 15   # 0.6 s of audio minus the 0.3 s warm-up = 0.3 s, in 20 ms blocks


def test_silent_default_microphone_switches_to_the_next(mic):
    opened = []
    mic._auto = True
    mic._candidates = ["laptop microphone"]
    mic._open_next = lambda: opened.append("next") or True
    mic._io = FakeIO(np.zeros(2 * 2100))          # 2.1 s of pure digital silence
    mic._read()
    assert opened == ["next"]


def test_silent_chosen_microphone_reports_it(mic):
    mic._auto = False
    mic._candidates = []
    mic._io = FakeIO(np.zeros(2 * 2100))
    mic._read()
    assert mic.errors == ['No sound from the microphone "USB dongle" - choose another microphone.']


def test_quiet_room_is_not_digital_silence(mic):
    opened = []
    mic._auto, mic._candidates = True, ["other"]
    mic._open_next = lambda: opened.append("next") or True
    mic._io = FakeIO(np.random.default_rng(1).normal(0, 0.001, 2 * 2100))
    mic._read()
    assert opened == [] and mic.errors == []


def test_no_notes_shows_nothing():
    pacer = SubtitlePacer()
    pacer.load([])
    assert pacer.update(True, 1.0) is None and pacer.done
