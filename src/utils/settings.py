"""
User settings on top of config.py.

``SETTINGS`` lists every value the Settings window can change, with its
type and allowed range. Saved values are stored as JSON in
config.SETTINGS_FILE and applied to the ``config`` module at start-up, so
the rest of the code simply keeps reading ``config.X``.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import config
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Setting:
    key: str                 # name in config.py
    label: str
    kind: type               # int, float, bool or str
    group: str
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple[str, ...] | None = None
    suffix: str = ""
    restart: bool = False    # True = applies from the next presentation (camera / model)
    help: str = ""
    in_window: bool = True   # False = saved, but edited elsewhere (e.g. a list only known at runtime)


SETTINGS: tuple[Setting, ...] = (
    # Gesture
    Setting("REQUIRE_OPEN_PALM", "Require all five fingers open", bool, "Gesture",
            help="Off: any hand moving left/right changes slides. "
                 "On: only an open hand (fewer accidental swipes)."),
    Setting("MIN_SWIPE_DISTANCE", "Minimum swipe distance", int, "Gesture", 50, 600, 10, suffix=" px",
            help="How far a hand close to the camera must move sideways (in a 1280 px wide image)."),
    Setting("MAX_SWIPE_DURATION", "Maximum swipe duration", float, "Gesture", 0.2, 3.0, 0.1, suffix=" s",
            help="Slower movements are ignored."),
    Setting("COOLDOWN_SECONDS", "Cooldown after a gesture", float, "Gesture", 0.2, 5.0, 0.1, suffix=" s",
            help="Further swipes are ignored for this long."),
    Setting("HORIZONTAL_RATIO", "Horizontal strictness", float, "Gesture", 1.0, 4.0, 0.1, suffix=" x",
            help="Sideways movement must exceed vertical movement times this value."),
    Setting("OPEN_PALM_MIN_FRAMES", "Hand stable frames", int, "Gesture", 1, 15, 1,
            help="Frames the hand must be seen before a swipe can change the slide."),
    # Open palm
    Setting("FINGER_STRAIGHT_ANGLE", "Finger straight angle", float, "Open palm", 110, 175, 5, suffix=" °",
            help="Lower = accepts more bent fingers."),
    Setting("FINGER_MCP_ANGLE", "Knuckle angle", float, "Open palm", 90, 175, 5, suffix=" °"),
    Setting("THUMB_STRAIGHT_ANGLE", "Thumb straight angle", float, "Open palm", 100, 175, 5, suffix=" °"),
    Setting("THUMB_SPREAD_RATIO", "Thumb spread", float, "Open palm", 0.2, 1.2, 0.05, suffix=" x palm"),
    # Presenter
    Setting("PRESENTER_FOCUS", "Focus on the presenter", bool, "Presenter", restart=True,
            help="Only the presenter's hands change slides; other people's hands are ignored."),
    Setting("LONG_DISTANCE_ZOOM", "Long-distance zoom", bool, "Presenter", restart=True,
            help="Searches for the hand in a zoomed area around a presenter standing far away."),
    Setting("SWIPE_DISTANCE_PALMS", "Swipe distance when far away", float, "Presenter", 0.5, 4.0, 0.1,
            suffix=" x palm",
            help="Far away the hand looks small, so the swipe is measured in hand sizes instead of pixels."),
    Setting("SWIPE_LOST_SECONDS", "Fast swipe tolerance", float, "Presenter", 0.1, 1.0, 0.05, suffix=" s",
            help="How long a blurred hand may disappear during a fast swipe."),
    # Hand detection
    Setting("MIN_DETECTION_CONFIDENCE", "Detection confidence", float, "Hand detection", 0.3, 0.95, 0.05,
            restart=True),
    Setting("MIN_TRACKING_CONFIDENCE", "Tracking confidence", float, "Hand detection", 0.3, 0.95, 0.05,
            restart=True),
    # Camera
    Setting("CAMERA_INDEX", "Camera number", int, "Camera", 0, 9, 1, restart=True,
            help="0 = the first webcam."),
    Setting("MIRROR_CAMERA", "Mirror camera image", bool, "Camera", restart=True),
    # Presentation
    Setting("PDF_VIEWER", "PDF viewer", str, "Presentation", choices=("auto", "sumatra", "default"),
            help="auto = SumatraPDF if installed, otherwise the Windows default app."),
    # Debate
    Setting("DEBATE_MODE", "Debate mode (auto-advance)", bool, "Debate",
            help="Slides move on automatically when their time is up. Gestures still work."),
    Setting("DEBATE_TIMING", "Timing", str, "Debate", choices=("total", "per slide"),
            help="total = the total time is divided equally between the slides; "
                 "per slide = every slide gets the same fixed time."),
    Setting("DEBATE_TOTAL_SECONDS", "Total time", int, "Debate", 10, 5 * 3600, 30, suffix=" s",
            help="Whole debate, divided equally between the slides."),
    Setting("DEBATE_SLIDE_SECONDS", "Time per slide", int, "Debate", 5, 3600, 5, suffix=" s",
            help="Used for every slide that has no time of its own."),
    Setting("DEBATE_PER_SLIDE", "Set a time for each slide", bool, "Debate",
            help="After choosing the file, a list of all slides opens so each can get its own time."),
    Setting("DEBATE_WARNING_SECONDS", "Warning before time is up", int, "Debate", 0, 300, 5, suffix=" s",
            help="The countdown turns orange for the last seconds of a slide."),
    Setting("DEBATE_TIMER_ON_SLIDE", "Show timer on the slide", bool, "Debate",
            help="A large countdown in the bottom-right corner of the slide show, "
                 "on the screen the audience sees (debate mode and time limit)."),
    # Time limit
    Setting("TIME_LIMIT_ENABLED", "Time limit (normal mode)", bool, "Time limit",
            help="Presenters spend the time as they like; alerts appear once the total is over."),
    Setting("TIME_LIMIT_SECONDS", "Time limit", int, "Time limit", 60, 5 * 3600, 60, suffix=" s"),
    Setting("OVERTIME_WARNING_1_SECONDS", "First warning after", int, "Time limit", 0, 3600, 30,
            suffix=" s over", help="0 = no first warning."),
    Setting("OVERTIME_WARNING_2_SECONDS", "Second warning after", int, "Time limit", 0, 3600, 30,
            suffix=" s over", help="0 = no second warning."),
    Setting("OVERTIME_STOP_SECONDS", "End presentation after", int, "Time limit", 0, 3600, 30,
            suffix=" s over", help="The presentation is closed automatically. 0 = never."),
    # Subtitles
    Setting("SUBTITLES_ENABLED", "Subtitles from speaker notes", bool, "Subtitles",
            help="While you speak, the slide's notes appear at the bottom of the slide, sentence by sentence."),
    Setting("SUBTITLE_WORDS_PER_MINUTE", "Speaking speed", int, "Subtitles", 60, 260, 10, suffix=" words/min",
            help="Lower if the subtitles run ahead of you, higher if they fall behind."),
    Setting("SUBTITLE_FONT_PT", "Subtitle size", int, "Subtitles", 12, 48, 1, suffix=" pt"),
    Setting("VOICE_MIN_LEVEL", "Microphone threshold", float, "Subtitles", 0.0005, 0.2, 0.0005,
            help="Lower = quieter speech counts as speaking. Raise it if noise shows subtitles."),
    Setting("SUBTITLE_MICROPHONE", "Microphone", str, "Subtitles", in_window=False,
            help="auto = the Windows default (or the next one if it gives no sound)."),
    # Photo slideshow
    Setting("PHOTO_STYLE", "Style", str, "Photo slideshow",
            choices=("classic", "fade", "slide", "zoom", "kenburns", "polaroid", "blur", "carousel",
                     "flip", "wipe", "circle", "tiles", "blinds", "vintage", "mono")),
    Setting("PHOTO_ORDER", "Order", str, "Photo slideshow", choices=("name", "date", "shuffle", "selected")),
    Setting("PHOTO_FILL", "Fill the screen (crop edges)", bool, "Photo slideshow"),
    Setting("PHOTO_TRANSITION_MS", "Transition length", int, "Photo slideshow", 150, 3000, 50, suffix=" ms"),
    Setting("PHOTO_AUTOPLAY", "Play automatically", bool, "Photo slideshow",
            help="The next photo appears on its own. Swipes still work; S pauses. Off in debate mode."),
    Setting("PHOTO_AUTOPLAY_SECONDS", "Time per photo", int, "Photo slideshow", 1, 600, 1, suffix=" s"),
    Setting("PHOTO_LOOP", "Loop", bool, "Photo slideshow",
            help="After the last photo, start again with the first."),
    # Display
    Setting("SHOW_OVERLAY", "Show floating overlay", bool, "Display"),
    Setting("SHOW_CAMERA_PREVIEW", "Show camera preview", bool, "Display"),
    Setting("DEBUG", "Debug drawing on preview", bool, "Display"),
)

BY_KEY = {s.key: s for s in SETTINGS}
DEFAULTS: dict[str, Any] = {s.key: getattr(config, s.key) for s in SETTINGS}


def coerce(setting: Setting, value: Any) -> Any:
    """Convert and clamp a value; raises ValueError if it cannot be used."""
    if setting.kind is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if setting.kind is str:
        value = str(value)
        if setting.choices and value not in setting.choices:
            raise ValueError(f"{setting.key} must be one of {setting.choices}")
        return value
    value = setting.kind(value)
    if setting.minimum is not None:
        value = max(setting.kind(setting.minimum), value)
    if setting.maximum is not None:
        value = min(setting.kind(setting.maximum), value)
    return value


def current_values() -> dict[str, Any]:
    return {s.key: getattr(config, s.key) for s in SETTINGS}


def apply(values: dict[str, Any]) -> list[str]:
    """Apply values to config. Returns the keys that changed."""
    changed = []
    for key, value in values.items():
        setting = BY_KEY.get(key)
        if setting is None:
            log.warning("Ignoring unknown setting %s", key)
            continue
        try:
            value = coerce(setting, value)
        except (TypeError, ValueError) as exc:
            log.warning("Ignoring invalid value for %s: %s", key, exc)
            continue
        if getattr(config, key) != value:
            setattr(config, key, value)
            changed.append(key)
    return changed


def load(path: Path | None = None) -> list[str]:
    """Apply saved settings (if any). Returns the keys that changed."""
    path = Path(path or config.SETTINGS_FILE)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Could not read settings %s: %s", path, exc)
        return []
    if not isinstance(data, dict):
        return []
    changed = apply(data)
    if changed:
        log.info("Loaded settings: %s", ", ".join(changed))
    return changed


def save(values: dict[str, Any] | None = None, path: Path | None = None) -> Path:
    """Save only the values that differ from config.py's defaults."""
    path = Path(path or config.SETTINGS_FILE)
    values = values if values is not None else current_values()
    overrides = {k: v for k, v in values.items() if k in BY_KEY and v != DEFAULTS[k]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overrides, indent=2), encoding="utf-8")
    return path


def reset_to_defaults() -> list[str]:
    return apply(DEFAULTS)
