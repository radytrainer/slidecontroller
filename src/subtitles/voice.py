"""
Is the presenter speaking? Decided from the microphone loudness only.

Speech is sound clearly louder than the room's background noise, which is
learned continuously from the quiet moments (so a humming projector or air
conditioning does not count as speaking). Short loud clicks are ignored, and
short gaps between words do not count as a pause::

    level:     ▁▁▁▁▆▇▆▅▇▆▁▆▇▆▁▁▁▁▁▁▁▁▆▇▇
    speaking:  ______‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾____‾‾
                     ^start       ^pause (VOICE_PAUSE_SECONDS of quiet)
"""

import config

HOLD_SECONDS = 0.15        # a dip shorter than this (between syllables) is not silence
NOISE_FALL_SECONDS = 0.1   # background noise estimate: follows a quieter moment fast ...
NOISE_RISE_SECONDS = 4.0   # ... and a louder room slowly


class VoiceDetector:
    def __init__(self, min_level: float | None = None, noise_ratio: float | None = None,
                 start_seconds: float | None = None, pause_seconds: float | None = None):
        self.min_level = config.VOICE_MIN_LEVEL if min_level is None else min_level
        self.noise_ratio = config.VOICE_NOISE_RATIO if noise_ratio is None else noise_ratio
        self.start_seconds = config.VOICE_START_SECONDS if start_seconds is None else start_seconds
        self.pause_seconds = config.VOICE_PAUSE_SECONDS if pause_seconds is None else pause_seconds
        self.speaking = False
        self.noise: float | None = None
        self._since_loud = float("inf")
        self._loud_for = 0.0
        self._quiet_for = 0.0

    @property
    def threshold(self) -> float:
        return max(self.min_level, (self.noise or 0.0) * self.noise_ratio)

    def update(self, level: float, seconds: float) -> bool:
        """Feed the loudness of the next ``seconds`` of audio; returns ``speaking``."""
        if self.noise is None:
            # Assume a quiet room: the presenter may already be talking, and the
            # first sound must not become the "background noise".
            self.noise = self.min_level / self.noise_ratio
        # Speech is loud in bursts (syllables) with short dips between them. Sound
        # counts as continuing for HOLD_SECONDS after the last loud moment, which
        # bridges those dips - equally for loud and quiet voices.
        if level >= self.threshold:
            self._since_loud = 0.0
        else:
            self._since_loud += seconds
        if self._since_loud <= HOLD_SECONDS:
            self._quiet_for = 0.0
            if level >= self.threshold:
                # Only really loud time counts towards starting, so a short click
                # (made longer by the envelope) does not.
                self._loud_for += seconds
        else:
            self._quiet_for += seconds
            self._loud_for = 0.0
        # Background noise = the quietest recent sound: it falls quickly (every dip
        # between words pulls it down) and rises slowly (NOISE_RISE_SECONDS), so a
        # steady hum is learned but continuous speech never becomes "background".
        if level < self.noise:
            self.noise += (level - self.noise) * min(1.0, seconds / NOISE_FALL_SECONDS)
        else:
            self.noise += (level - self.noise) * min(1.0, seconds / NOISE_RISE_SECONDS)
        if not self.speaking and self._loud_for >= self.start_seconds:
            self.speaking = True
        elif self.speaking and self._quiet_for >= self.pause_seconds:
            self.speaking = False
        return self.speaking
