"""
Microphone loudness through Qt Multimedia (part of PySide6, no extra install).

Emits ``level(rms, seconds)`` for every 20 ms of audio on the GUI thread; the
audio itself is never stored or sent anywhere.

Choosing the microphone (config.SUBTITLE_MICROPHONE):

* ``"auto"`` - the Windows default microphone. Some default "microphones" give
  pure digital silence (a USB audio dongle or headset nobody speaks into), so
  if the chosen one delivers no sound at all for ``SILENT_CHECK_SECONDS``, the
  next microphone is tried automatically.
* a device name - exactly that microphone (see ``list_microphones()``).
"""

import numpy as np
from PySide6.QtCore import QObject, Signal

import config
from src.utils.logger import get_logger

log = get_logger(__name__)

BLOCK_SECONDS = 0.02
SILENT_CHECK_SECONDS = 2.0
DIGITAL_SILENCE = 1e-5   # RMS below this is no signal at all (not even room noise)
WARMUP_SECONDS = 0.3     # a microphone often clicks when it is switched on: not speech


def list_microphones() -> list[str]:
    """Names of the audio inputs, the Windows default first."""
    from PySide6.QtMultimedia import QMediaDevices

    devices = QMediaDevices.audioInputs()
    return [d.description() for d in sorted(devices, key=lambda d: not d.isDefault())]


class Microphone(QObject):
    level = Signal(float, float)   # RMS loudness 0..1, seconds of audio
    error = Signal(str)
    changed = Signal(str)          # name of the microphone now in use

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._source = None
        self._io = None
        self._dtype = None
        self._scale = 1.0
        self._offset = 0.0
        self._channels = 1
        self._rate = 48000
        self._pending = np.zeros(0, dtype=np.float32)
        self._candidates = []          # devices still to try in "auto" mode
        self._auto = True
        self._checked_seconds = 0.0
        self._peak = 0.0
        self.name = ""

    def start(self) -> bool:
        from PySide6.QtMultimedia import QMediaDevices

        devices = sorted(QMediaDevices.audioInputs(), key=lambda d: not d.isDefault())
        if not devices:
            self.error.emit("No microphone found - subtitles are off.")
            return False
        wanted = (config.SUBTITLE_MICROPHONE or "auto").strip()
        self._auto = wanted.lower() == "auto"
        if not self._auto:
            chosen = [d for d in devices if d.description() == wanted]
            if not chosen:
                log.warning("Microphone '%s' not found - using the default microphone", wanted)
                self._auto = True
            devices = chosen or devices
        self._candidates = list(devices)
        return self._open_next()

    def _open_next(self) -> bool:
        while self._candidates:
            if self._open(self._candidates.pop(0)):
                return True
        self.error.emit("The microphone could not be opened - subtitles are off.")
        return False

    def _open(self, device) -> bool:
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource

        self._close()
        fmt = device.preferredFormat()
        kinds = {
            QAudioFormat.SampleFormat.Float: (np.float32, 1.0, 0.0),
            QAudioFormat.SampleFormat.Int16: (np.int16, 1 / 32768, 0.0),
            QAudioFormat.SampleFormat.Int32: (np.int32, 1 / 2 ** 31, 0.0),
            QAudioFormat.SampleFormat.UInt8: (np.uint8, 1 / 128, -128.0),
        }
        if fmt.sampleFormat() not in kinds:
            log.warning("Microphone %s: unsupported audio format", device.description())
            return False
        self._dtype, self._scale, self._offset = kinds[fmt.sampleFormat()]
        self._channels = max(1, fmt.channelCount())
        self._rate = fmt.sampleRate() or 48000
        self._source = QAudioSource(device, fmt, self)
        self._io = self._source.start()
        if self._io is None:
            log.warning("Microphone %s could not be opened", device.description())
            self._source = None
            return False
        self._io.readyRead.connect(self._read)
        self.name = device.description()
        self._checked_seconds = 0.0
        self._peak = 0.0
        log.info("Microphone: %s (%d Hz, %d ch)", self.name, self._rate, self._channels)
        self.changed.emit(self.name)
        return True

    def stop(self) -> None:
        self._candidates = []
        self._close()

    def _close(self) -> None:
        if self._source is not None:
            self._source.stop()
            self._source = None
            self._io = None
        self._pending = np.zeros(0, dtype=np.float32)

    def _read(self) -> None:
        if self._io is None:
            return
        data = self._io.readAll().data()
        if not data:
            return
        samples = np.frombuffer(data, dtype=self._dtype)
        frames = len(samples) // self._channels
        samples = samples[:frames * self._channels].reshape(frames, self._channels)
        # Loudest channel, not the average: some microphones deliver sound on one channel only.
        channels = (samples.astype(np.float32) + self._offset) * self._scale
        mono = channels[:, np.argmax(np.abs(channels).mean(axis=0))] if frames else channels[:, 0]
        self._pending = np.concatenate([self._pending, mono])
        block = max(1, int(self._rate * BLOCK_SECONDS))
        while len(self._pending) >= block:
            chunk, self._pending = self._pending[:block], self._pending[block:]
            rms = float(np.sqrt(np.mean(chunk * chunk)))
            seconds = block / self._rate
            warming_up = self._checked_seconds < WARMUP_SECONDS
            if self._check_silence(rms, seconds):
                return  # switched to another microphone
            if not warming_up:
                self.level.emit(rms, seconds)

    def _check_silence(self, rms: float, seconds: float) -> bool:
        """Auto mode: a microphone with no sound at all is not the one being spoken into."""
        if self._checked_seconds >= SILENT_CHECK_SECONDS:
            return False
        self._checked_seconds += seconds
        self._peak = max(self._peak, rms)
        if self._checked_seconds < SILENT_CHECK_SECONDS or self._peak >= DIGITAL_SILENCE:
            return False
        if self._auto and self._candidates:
            log.warning("Microphone %s gives no sound - trying the next microphone", self.name)
            return self._open_next()
        self.error.emit(f"No sound from the microphone \"{self.name}\" - choose another microphone.")
        return False
