"""
AirSlide main window.

Two pages:

* Home        - Open Presentation, supported files, gestures, environment status
* Presenting  - camera preview, live gesture status, recent commands, controls

Workflow (each slow step runs off the GUI thread)::

    Open Presentation -> file picker -> validate
      -> debate mode: slide times (optional dialog)
      -> open file in PowerPoint / PDF viewer        (background task)
      -> start camera + gesture engine               (engine thread, waits for "ready")
      -> start slide show / full screen              (background task)
      -> PRESENTING: window minimises, overlay shows, gestures drive the slides
      -> Stop (or presenter ends the show)  -> close -> back to Home
"""

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import config
from src.engine.gesture_engine import CommandResult, EngineUpdate, GestureEngine
from src.gesture.gesture_state import GestureState
from src.gesture.swipe_detector import Gesture
from src.presentation.base import PresentationError
from src.presentation.debate import DebatePlan, DebateTimer, count_slides, format_seconds
from src.presentation.photos import is_photo_path, order_photos, valid_photos
from src.presentation.presentation_manager import (
    MSG_NO_PHOTOS,
    FileType,
    PresentationManager,
    SessionState,
    validate_file,
)
from src.presentation.time_limit import OvertimeAlert, TimeLimit, alert_message, format_duration
from src.subtitles.microphone import Microphone, list_microphones
from src.subtitles.pacer import SubtitlePacer
from src.subtitles.sentences import split_sentences
from src.subtitles.voice import VoiceDetector
from src.utils import settings
from src.utils.logger import get_logger
from ui.debate_dialog import SlideTimesDialog
from ui.overlay import OverlayWindow
from ui.photo_dialog import PhotoSetupDialog
from ui.settings_window import SettingsWindow
from ui.slide_timer import AlertWindow, SlideTimerWindow
from ui.subtitles import SubtitleWindow
from ui.theme import STATUS_COLORS
from ui.widgets import CameraView, Card, DurationEdit, StatusGrid
from ui.workers import EngineBridge, run_task

log = get_logger(__name__)

FILE_FILTER = ("Presentations and photos (*.pptx *.pdf *.jpg *.jpeg *.png *.gif);;"
               "PowerPoint Presentation (*.pptx);;"
               "PDF Document (*.pdf);;"
               "Photos (*.jpg *.jpeg *.png *.gif)")
PHOTO_FILTER = "Photos (*.jpg *.jpeg *.png *.gif)"
MSG_MIXED_FILES = "Choose one PowerPoint or PDF file, or one or more photos."
MAX_HISTORY = 6
LEVEL = {"OK": "ok", "WARN": "warn", "FAIL": "error"}


def environment_checks() -> dict[str, tuple[str, str]]:
    """Run the start-up checks (slow: opens the camera). {row: (text, level)}"""
    from src.utils import health_check as hc

    rows = {}
    camera = hc.check_camera()
    rows["Camera"] = ("Ready" if camera.status == hc.OK else camera.detail, LEVEL[camera.status])
    model, mediapipe = hc.check_hand_model(), hc.check_package("mediapipe", "MediaPipe")
    engine_ok = mediapipe.status == hc.OK
    rows["Gesture Engine"] = ("Ready" if engine_ok else mediapipe.detail,
                              LEVEL[hc.OK if engine_ok else hc.FAIL] if model.status != hc.WARN else "warn")
    ppt = hc.check_powerpoint()
    rows["PowerPoint"] = ("Detected" if ppt.status == hc.OK else "Not found", LEVEL[ppt.status])
    pdf = hc.check_pdf_viewer()
    rows["PDF viewer"] = (pdf.detail.split(" (")[0] if pdf.status != hc.FAIL else "Not found",
                          LEVEL[pdf.status] if pdf.status != hc.WARN else "ok")
    return rows


class MainWindow(QMainWindow):
    def __init__(
        self,
        manager: PresentationManager | None = None,
        engine_factory: Callable[..., GestureEngine] = GestureEngine,
        run_checks: bool = True,
        microphone_factory: Callable[[], Microphone] = Microphone,
    ):
        super().__init__()
        self.setWindowTitle(f"{config.APP_NAME} - {config.APP_TAGLINE}")
        self.setMinimumSize(980, 680)

        self.manager = manager or PresentationManager()
        self._engine_factory = engine_factory
        self.engine: GestureEngine | None = None
        self.overlay = OverlayWindow()
        self.slide_timer = SlideTimerWindow()  # debate countdown on the slide show itself
        self._busy = False

        # Debate mode: plan chosen before opening, timer running while presenting.
        self.clock = time.monotonic
        self._debate_plan: DebatePlan | None = None
        self._debate: DebateTimer | None = None
        self._slide_total: int | None = None
        self._slide_times: dict[str, dict[int, int]] = {}  # per file, kept for this session
        self._advancing = False
        # Normal mode: optional time limit with over-time alerts.
        self._limit: TimeLimit | None = None
        self.alert = AlertWindow()
        self._ended_for_time: str | None = None
        # Subtitles: speaker notes shown sentence by sentence while the presenter speaks.
        self._microphone_factory = microphone_factory
        self.microphone: Microphone | None = None
        self.subtitle_window = SubtitleWindow()
        self._notes: dict[int, str] = {}
        self._notes_slide: int | None = None
        self._voice = VoiceDetector()
        self._pacer = SubtitlePacer()
        self._audio_time = 0.0
        self._voice_level = 0.0
        self._subtitle_timer = QTimer(self, interval=config.DEBATE_TICK_MS, timeout=self._subtitle_tick)
        # One clock for both: the debate countdown or the time limit.
        self._debate_timer = QTimer(self, interval=config.DEBATE_TICK_MS, timeout=self._timer_tick)

        self.bridge = EngineBridge()
        self.bridge.ready.connect(self._on_engine_ready)
        self.bridge.update.connect(self._on_engine_update)
        self.bridge.command.connect(self._on_command)
        self.bridge.error.connect(self._on_engine_error)

        self.pages = QStackedWidget()
        self.home = self._build_home()
        self.presenting = self._build_presenting()
        self.pages.addWidget(self.home)
        self.pages.addWidget(self.presenting)
        self.setCentralWidget(self.pages)

        self._poll = QTimer(self, interval=config.PRESENTATION_POLL_MS, timeout=self._check_still_presenting)

        if run_checks:
            self.env_status.set("Camera", "Checking…", "muted")
            run_task(environment_checks, self._show_environment, lambda exc: log.warning("Checks failed: %s", exc))

    # =====================================================================
    # Pages
    # =====================================================================

    def _build_home(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(48, 28, 48, 24)
        root.setSpacing(18)
        root.addStretch(1)

        title = QLabel("🖐️ AirSlide")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        tagline = QLabel(config.APP_TAGLINE.rstrip("."))
        tagline.setObjectName("tagline")
        tagline.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        root.addWidget(tagline)

        self.open_button = QPushButton("📂   Open Presentation")
        self.open_button.setObjectName("primary")
        self.open_button.setCursor(Qt.PointingHandCursor)
        self.open_button.setMinimumWidth(380)
        self.open_button.clicked.connect(self.open_presentation)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.open_button)
        button_row.addStretch(1)
        root.addSpacing(8)
        root.addLayout(button_row)

        self.photos_button = QPushButton("🖼   Photo slideshow…")
        self.photos_button.setCursor(Qt.PointingHandCursor)
        self.photos_button.setToolTip("Choose photos (JPG, PNG, GIF) and show them as a slideshow.")
        self.photos_button.clicked.connect(self.open_photos)
        photo_row = QHBoxLayout()
        photo_row.addStretch(1)
        photo_row.addWidget(self.photos_button)
        photo_row.addStretch(1)
        root.addLayout(photo_row)

        self.home_message = QLabel("")
        self.home_message.setAlignment(Qt.AlignCenter)
        self.home_message.setObjectName("muted")
        root.addWidget(self.home_message)
        root.addWidget(self._build_mode_card())

        cards = QHBoxLayout()
        cards.setSpacing(16)

        supported = Card("Supported")
        for text in ("✓  PowerPoint (.pptx)", "✓  PDF (.pdf)", "✓  Photos (.jpg .png .gif)"):
            supported.body.addWidget(QLabel(text))
        supported.body.addStretch(1)

        gestures = Card("Gesture")
        for text in ("✋  Right → Left   =   Next", "✋  Left → Right   =   Previous"):
            gestures.body.addWidget(QLabel(text))
        hint = QLabel()
        hint.setObjectName("muted")
        self.gesture_hint = hint
        self._update_gesture_hint()
        gestures.body.addWidget(hint)
        gestures.body.addStretch(1)

        status = Card("Status")
        self.env_status = StatusGrid(["Camera", "Presentation", "Gesture Engine", "PowerPoint", "PDF viewer"])
        self.env_status.set("Presentation", "None selected", "muted")
        status.body.addWidget(self.env_status)

        cards.addWidget(supported, 1)
        cards.addWidget(gestures, 1)
        cards.addWidget(status, 2)
        root.addLayout(cards)
        root.addStretch(2)

        footer = QHBoxLayout()
        version = QLabel(f"{config.APP_NAME} {config.APP_VERSION}")
        version.setObjectName("muted")
        settings_button = QPushButton("⚙  Settings")
        settings_button.clicked.connect(self.open_settings)
        footer.addWidget(version)
        footer.addStretch(1)
        footer.addWidget(settings_button)
        root.addLayout(footer)
        return page

    def _build_mode_card(self) -> Card:
        """
        ◉ Normal · gestures only      ○ Debate · slides advance automatically
        normal:  ☐ Time limit [0:20:00]   warnings at +2 and +3 min over · ends at +5 min over
        debate:  Timing [Total time, divided equally ▾]  [0:10:00]   ☐ Edit the time of each slide
        """
        card = Card("Presentation mode")
        row = QHBoxLayout()
        row.setSpacing(28)
        self.normal_radio = QRadioButton("Normal  ·  gestures only")
        self.debate_radio = QRadioButton("Debate  ·  slides advance automatically")
        for radio in (self.normal_radio, self.debate_radio):
            radio.setCursor(Qt.PointingHandCursor)
        group = QButtonGroup(card)
        group.addButton(self.normal_radio)
        group.addButton(self.debate_radio)
        row.addWidget(self.normal_radio)
        row.addWidget(self.debate_radio)
        row.addStretch(1)
        self.subtitles_check = QCheckBox("Subtitles from speaker notes")
        self.subtitles_check.setToolTip(settings.BY_KEY["SUBTITLES_ENABLED"].help)
        self.mic_combo = QComboBox()
        self.mic_combo.setToolTip("The microphone the presenter speaks into.\n"
                                  "Auto = the Windows default, or the next microphone if it gives no sound.")
        self.mic_combo.setMinimumWidth(200)
        row.addWidget(self.subtitles_check)
        row.addWidget(self.mic_combo)
        self._watch_microphones()
        card.body.addLayout(row)

        self.debate_options = QWidget()
        self.debate_options.setObjectName("transparent")  # show the card behind it
        options = QHBoxLayout(self.debate_options)
        options.setContentsMargins(0, 6, 0, 0)
        options.setSpacing(12)
        self.timing_combo = QComboBox()
        self.timing_combo.addItem("Total time, divided equally", "total")
        self.timing_combo.addItem("Same time for every slide", "per slide")
        self.timing_combo.setToolTip(settings.BY_KEY["DEBATE_TIMING"].help)

        total = settings.BY_KEY["DEBATE_TOTAL_SECONDS"]
        self.total_time = DurationEdit(int(total.minimum), int(total.maximum))
        self.total_time.setToolTip("Hours:minutes:seconds for the whole presentation.")
        seconds = settings.BY_KEY["DEBATE_SLIDE_SECONDS"]
        self.slide_seconds = QSpinBox()
        self.slide_seconds.setRange(int(seconds.minimum), int(seconds.maximum))
        self.slide_seconds.setSingleStep(int(seconds.step))
        self.slide_seconds.setSuffix(seconds.suffix)
        self.slide_seconds.setToolTip(seconds.help)
        self.per_slide_check = QCheckBox("Edit the time of each slide")
        self.per_slide_check.setToolTip(settings.BY_KEY["DEBATE_PER_SLIDE"].help)

        options.addWidget(QLabel("Timing"))
        for widget in (self.timing_combo, self.total_time, self.slide_seconds):
            options.addWidget(widget)
        options.addSpacing(12)
        options.addWidget(self.per_slide_check)
        options.addStretch(1)
        card.body.addWidget(self.debate_options)

        # Normal mode: optional time limit for the whole presentation.
        self.normal_options = QWidget()
        self.normal_options.setObjectName("transparent")
        normal = QHBoxLayout(self.normal_options)
        normal.setContentsMargins(0, 6, 0, 0)
        normal.setSpacing(12)
        self.time_limit_check = QCheckBox("Time limit")
        self.time_limit_check.setToolTip(settings.BY_KEY["TIME_LIMIT_ENABLED"].help)
        limit = settings.BY_KEY["TIME_LIMIT_SECONDS"]
        self.limit_time = DurationEdit(int(limit.minimum), int(limit.maximum))
        self.limit_time.setToolTip("Hours:minutes:seconds for the whole presentation.")
        self.limit_hint = QLabel("")
        self.limit_hint.setObjectName("muted")
        for widget in (self.time_limit_check, self.limit_time, self.limit_hint):
            normal.addWidget(widget)
        normal.addStretch(1)
        card.body.addWidget(self.normal_options)

        self._load_mode_controls()
        self.time_limit_check.toggled.connect(self._on_mode_changed)
        self.subtitles_check.toggled.connect(self._on_mode_changed)
        self.mic_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.limit_time.timeChanged.connect(self._on_mode_changed)
        self.debate_radio.toggled.connect(self._on_mode_changed)
        self.timing_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.total_time.timeChanged.connect(self._on_mode_changed)
        self.slide_seconds.valueChanged.connect(self._on_mode_changed)
        self.per_slide_check.toggled.connect(self._on_mode_changed)
        return card

    def _build_presenting(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(14)

        header = QHBoxLayout()
        self.file_label = QLabel("")
        self.file_label.setObjectName("fileName")
        self.timer_label = QLabel("")  # debate countdown
        self.timer_label.setObjectName("fileName")
        self.timer_label.setVisible(False)
        self.state_label = QLabel("")
        header.addWidget(self.file_label)
        header.addStretch(1)
        header.addWidget(self.timer_label)
        header.addSpacing(24)
        header.addWidget(self.state_label)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.camera_view = CameraView()
        body.addWidget(self.camera_view, 3)

        side = QVBoxLayout()
        side.setSpacing(14)
        live = Card("Live")
        self.gesture_big = QLabel("—")
        self.gesture_big.setObjectName("bigGesture")
        live.body.addWidget(self.gesture_big)
        self.live_status = StatusGrid(["Hand", "Fingers", "Palm", "Direction", "Distance", "Gesture", "Status",
                                       "Subtitles"])
        live.body.addWidget(self.live_status)
        side.addWidget(live)

        history = Card("Recent commands")
        self.history = QListWidget()
        self.history.setFocusPolicy(Qt.NoFocus)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history.setWordWrap(True)
        history.body.addWidget(self.history)
        side.addWidget(history, 1)
        body.addLayout(side, 2)
        root.addLayout(body, 1)

        controls = QHBoxLayout()
        self.pause_button = QPushButton("⏸  Pause gestures")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.timer_button = QPushButton("⏸  Pause timer")
        self.timer_button.clicked.connect(self.toggle_timer)
        self.timer_button.setVisible(False)
        self.overlay_button = QPushButton("")
        self.overlay_button.clicked.connect(self.toggle_overlay)
        settings_button = QPushButton("⚙  Settings")
        settings_button.clicked.connect(self.open_settings)
        self.stop_button = QPushButton("■  Stop presentation")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self.stop_presentation)
        for button in (self.pause_button, self.timer_button, self.overlay_button, settings_button):
            controls.addWidget(button)
        controls.addStretch(1)
        controls.addWidget(self.stop_button)
        root.addLayout(controls)
        self._update_overlay_button()
        return page

    # =====================================================================
    # Environment status
    # =====================================================================

    def _show_environment(self, rows: dict[str, tuple[str, str]]) -> None:
        for name, (text, level) in rows.items():
            self.env_status.set(name, text, level)

    # =====================================================================
    # Workflow
    # =====================================================================

    def open_presentation(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open Presentation or Photos", str(Path.home()), FILE_FILTER)
        self.load_paths(paths)

    def open_photos(self) -> None:
        start = Path.home() / "Pictures"
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose photos for the slideshow",
                                                str(start if start.is_dir() else Path.home()), PHOTO_FILTER)
        self.load_paths(paths)

    def load_paths(self, paths: list[str]) -> None:
        """One presentation (.pptx / .pdf), or one or more photos."""
        if not paths:
            return
        if all(is_photo_path(p) for p in paths):
            self.load_photos(paths)
        elif len(paths) == 1:
            self.load_file(paths[0])
        else:
            self.show_error(MSG_MIXED_FILES)

    def load_photos(self, paths: list[str]) -> None:
        if self._busy:
            return
        photos, skipped = valid_photos(paths)
        if not photos:
            self.show_error(MSG_NO_PHOTOS)
            return
        options = self._ask_photo_options(photos, len(skipped))
        if options is None:
            return  # setup cancelled
        if settings.apply(options):
            settings.save()
        photos = order_photos(photos, config.PHOTO_ORDER)

        self._debate_plan = None
        if config.DEBATE_MODE:
            self._debate_plan = self._prepare_debate(str(photos[0]), count=len(photos))
            if self._debate_plan is None:
                return

        name = f"{len(photos)} photo{'s' if len(photos) != 1 else ''}"
        self.env_status.set("Presentation", name, "info")
        self._set_busy(True, f"Preparing the slideshow of {name}…")
        run_task(lambda: self.manager.open_photos(photos), self._on_file_opened, self._on_start_failed)

    def _ask_photo_options(self, photos: list[Path], skipped: int) -> dict | None:
        """Style, order and fit from the setup dialog (None = cancelled)."""
        dialog = PhotoSetupDialog(self, photos, skipped)
        return dialog.values() if dialog.exec() else None

    def load_file(self, path: str) -> None:
        if self._busy:
            return
        try:
            file_type = validate_file(path)
        except PresentationError as exc:
            self.show_error(str(exc))
            return

        self._debate_plan = None
        if config.DEBATE_MODE:
            self._debate_plan = self._prepare_debate(path)
            if self._debate_plan is None:
                return  # slide times dialog cancelled

        name = Path(path).name
        app = "PowerPoint" if file_type == FileType.PPTX else "the PDF viewer"
        self.env_status.set("Presentation", name, "info")
        self._set_busy(True, f"Opening {name} in {app}…")
        run_task(lambda: self.manager.open_file(path), self._on_file_opened, self._on_start_failed)

    def _on_file_opened(self, _=None) -> None:
        self._set_busy(True, "Starting camera…")
        self.engine = self._engine_factory(
            self._handle_gesture,
            on_ready=self.bridge.ready.emit,
            on_update=self.bridge.update.emit,
            on_command=self.bridge.command.emit,
            on_error=self.bridge.error.emit,
            want_frames=self._wants_frames,
        )
        self.engine.start()

    def _on_engine_ready(self) -> None:
        if self.manager.session.presentation_status != SessionState.FILE_SELECTED:
            return  # already presenting (or cancelled)
        self._set_busy(True, "Starting presentation…")
        run_task(self.manager.start_presentation, self._on_presenting, self._on_start_failed)

    def _on_presenting(self, _=None) -> None:
        self._set_busy(False)
        session = self.manager.session
        self.file_label.setText(session.name)
        self.history.clear()
        self.pause_button.setText("⏸  Pause gestures")
        self._set_state_label("PRESENTING", "ok")
        self.camera_view.show_message("Camera preview" if config.SHOW_CAMERA_PREVIEW
                                      else "Camera preview is off (Settings)")
        self.pages.setCurrentWidget(self.presenting)
        if config.SHOW_OVERLAY:
            self.overlay.show()
        self._update_overlay_button()
        self._poll.start()
        if self._debate_plan is not None:
            self._start_debate()
        elif config.TIME_LIMIT_ENABLED:
            self._start_limit()
        self.live_status.set("Subtitles", "Off", "muted")
        if config.SUBTITLES_ENABLED:
            log.info("Subtitles: reading the speaker notes")
            self.live_status.set("Subtitles", "Reading speaker notes…", "muted")
            run_task(self.manager.slide_notes, self._start_subtitles, self._on_notes_failed)
        self.showMinimized()  # keep the slide show in front
        log.info("Presenting %s%s", session.name, " (debate mode)" if self._debate else "")

    def _on_start_failed(self, exc: Exception) -> None:
        self._stop_timers()
        self._stop_engine()
        self.manager.exit_presentation()
        self._set_busy(False)
        self.env_status.set("Presentation", "None selected", "muted")
        self.show_error(str(exc) if isinstance(exc, PresentationError) else f"Unable to open presentation.\n{exc}")

    def stop_presentation(self) -> None:
        if self._busy:
            return
        self._poll.stop()
        self._stop_timers()
        self._stop_engine()
        self.overlay.hide()
        self._set_busy(True, "Closing presentation…")
        run_task(self.manager.exit_presentation, self._on_closed, lambda exc: self._on_closed())

    def _on_closed(self, _=None) -> None:
        self._set_busy(False)
        if self._ended_for_time:
            self.home_message.setText(self._ended_for_time)
            self._ended_for_time = None
        self.env_status.set("Presentation", "None selected", "muted")
        self.pages.setCurrentWidget(self.home)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _check_still_presenting(self) -> None:
        if not self._busy and not self.manager.is_presenting:
            log.info("Presentation ended in the application")
            self.stop_presentation()

    def _stop_engine(self) -> None:
        if self.engine is not None:
            self.engine.stop()
            self.engine = None

    # =====================================================================
    # Debate mode
    # =====================================================================

    def _prepare_debate(self, path: str, count: int | None = None) -> DebatePlan | None:
        """The slide times for this file (``count`` slides if known, e.g. photos),
        or None if the presenter cancelled."""
        self._slide_total = count if count is not None else count_slides(path)
        total_mode = config.DEBATE_TIMING == "total"
        if not config.DEBATE_PER_SLIDE:
            if not total_mode:
                return DebatePlan(config.DEBATE_SLIDE_SECONDS)
            if self._slide_total:
                return DebatePlan.from_total(config.DEBATE_TOTAL_SECONDS, self._slide_total)
            # The slides cannot be counted, so the dialog asks for the number to divide by.
        # Edited times are remembered for the same file and the same timing.
        key = (str(Path(path).resolve()).lower(), config.DEBATE_TIMING,
               config.DEBATE_TOTAL_SECONDS if total_mode else config.DEBATE_SLIDE_SECONDS)
        times = self._ask_slide_times(path, self._slide_total, self._slide_times.get(key))
        if times is None:
            return None
        self._slide_times[key] = times
        self._slide_total = len(times)
        return DebatePlan(min(times.values()) if total_mode else config.DEBATE_SLIDE_SECONDS, times)

    def _ask_slide_times(self, path: str, count: int | None, previous: dict[int, int] | None) -> dict[int, int] | None:
        total = config.DEBATE_TOTAL_SECONDS if config.DEBATE_TIMING == "total" else None
        dialog = SlideTimesDialog(self, Path(path).name, count, config.DEBATE_SLIDE_SECONDS, previous, total)
        return dialog.times() if dialog.exec() else None

    def _start_debate(self) -> None:
        self._debate = DebateTimer(self._debate_plan, self.clock)
        position = self.manager.position()
        self._debate.start_slide(position[0] if position else 1)
        self._advancing = False
        self.timer_button.setText("⏸  Pause timer")
        self.timer_button.setVisible(True)
        self.timer_label.setVisible(True)
        if position:
            self._slide_total = position[1]
        self._show_debate()
        if config.DEBATE_TIMER_ON_SLIDE:
            self.slide_timer.show()
            self._place_slide_timer()
        self._debate_timer.start()

    def _stop_timers(self) -> None:
        """Stop the debate countdown or the time limit (the alert may stay a few seconds),
        and the subtitles."""
        self._stop_subtitles()
        self._debate_timer.stop()
        self._debate = None
        self._limit = None
        self._advancing = False
        self.timer_button.setVisible(False)
        self.timer_label.setVisible(False)
        self.timer_label.clear()  # so the next presentation redraws the overlay countdown
        self.overlay.show_timer(None)
        self.slide_timer.hide()

    def _place_slide_timer(self) -> None:
        # Checked every tick: the slide show may still be going full screen, or move screens.
        if not self.slide_timer.isVisible():
            return
        overlay = int(self.overlay.winId()) if self.overlay.isVisible() else None
        self.slide_timer.place(self.manager.window_handle(), avoid_hwnd=overlay)

    def _debate_tick(self) -> None:
        if self._debate is None or self._advancing or self._busy:
            return
        position = self.manager.position()
        if position:
            slide, self._slide_total = position
        else:
            slide = self._debate.slide  # the app cannot report the slide: count it ourselves
        if self._debate.tick(slide, self._slide_total):
            log.info("Debate: time is up on slide %d", slide)
            self._advancing = True
            run_task(self.manager.advance_slide, self._on_timed_advance, lambda exc: self._on_timed_advance(False))
        self._show_debate()
        self._place_slide_timer()

    def _on_timed_advance(self, ok) -> None:
        self._advancing = False
        if self._debate is None:
            return
        outcome = "Executed" if ok else "Not executed"
        self._add_history(f"{time.strftime('%H:%M:%S')}  ⏱ TIME UP  {outcome}  → slide {self._debate.slide}")

    def _show_debate(self) -> None:
        timer, total = self._debate, self._slide_total
        if timer is None:
            return
        if timer.finished:
            text, level = "⏱ TIME UP", "error"
        else:
            left = timer.remaining()
            text = f"⏱ {format_seconds(left)}"
            level = "warn" if left <= config.DEBATE_WARNING_SECONDS else "ok"
            if timer.paused:
                text, level = f"{text}  ⏸", "info"
        where = f"{min(timer.slide, total)}/{total}" if total else f"slide {timer.slide}"
        self._show_countdown(text, where, level)

    def _show_countdown(self, text: str, detail: str, level: str) -> None:
        """Same countdown in the window header, the overlay and on the slide."""
        full = f"{text}  ·  {detail}"
        if self.timer_label.text() != full:
            self.timer_label.setText(full)
            self.timer_label.setStyleSheet(f"color: {STATUS_COLORS[level]};")
            self.overlay.show_timer(full, STATUS_COLORS[level])
            self.slide_timer.show_time(text, detail, STATUS_COLORS[level])

    def _timer_tick(self) -> None:
        if self._debate is not None:
            self._debate_tick()
        elif self._limit is not None:
            self._limit_tick()

    def toggle_timer(self) -> None:
        timer = self._debate or self._limit
        if timer is None:
            return
        if timer.paused:
            timer.resume()
            self.timer_button.setText("⏸  Pause timer")
        else:
            timer.pause()
            self.timer_button.setText("▶  Resume timer")
        if self._debate is not None:
            self._show_debate()
        else:
            self._show_limit()

    # =====================================================================
    # Subtitles from speaker notes
    # =====================================================================

    def _start_subtitles(self, notes: dict[int, str]) -> None:
        if not self.manager.is_presenting:
            log.info("Subtitles: not started, the presentation already ended")
            return
        self._notes = notes or {}
        if not self._notes:
            log.info("Subtitles: this file has no speaker notes")
            self.live_status.set("Subtitles", "No speaker notes in this file", "muted")
            self.overlay.show_voice("🎤 Subtitles: no speaker notes in this file")
            return
        self._voice = VoiceDetector()
        self._voice_level = 0.0
        self._notes_slide = None
        self._audio_time = 0.0
        self.microphone = self._microphone_factory()
        self.microphone.level.connect(self._on_voice_level)
        self.microphone.error.connect(self._on_microphone_error)
        if hasattr(self.microphone, "changed"):
            self.microphone.changed.connect(self._on_microphone_changed)
        if not self.microphone.start():
            self.microphone = None
            return
        self._subtitle_tick()
        self._subtitle_timer.start()
        log.info("Subtitles on (%d slides with notes, microphone: %s)",
                 len(self._notes), getattr(self.microphone, "name", "?"))

    def _on_notes_failed(self, exc: Exception) -> None:
        log.error("Subtitles: could not read the speaker notes: %s", exc)
        self.live_status.set("Subtitles", f"Notes unavailable: {exc}", "warn")

    def _on_microphone_changed(self, name: str) -> None:
        self._voice = VoiceDetector()  # a new microphone has its own background noise
        self.live_status.set("Subtitles", f"Microphone: {name}", "muted")

    def _stop_subtitles(self) -> None:
        self._subtitle_timer.stop()
        if self.microphone is not None:
            self.microphone.stop()
            self.microphone.deleteLater()
            self.microphone = None
        self._notes = {}
        self._notes_slide = None
        self._pacer.load([])
        self.subtitle_window.hide()
        self.overlay.show_voice(None)

    def _subtitle_tick(self) -> None:
        """Follow the slide on screen and keep the bar in place."""
        if self.microphone is None:
            return
        position = self.manager.position()
        if position is None and self._notes_slide is not None:
            return  # PowerPoint busy for a moment: keep the slide (and sentence) we are on
        slide = position[0] if position else None
        if slide != self._notes_slide:
            self._notes_slide = slide
            self._pacer.load(split_sentences(self._notes.get(slide, "")))
            self.subtitle_window.hide()
        self.subtitle_window.place(self.manager.window_handle())
        self._show_subtitle_status()

    def _on_voice_level(self, level: float, seconds: float) -> None:
        self._audio_time += seconds
        self._voice_level = max(level, self._voice_level * 0.9)  # for the level meter
        speaking = self._voice.update(level, seconds)
        text = self._pacer.update(speaking, self._audio_time)
        if (text or "") != self.subtitle_window.text:
            self.subtitle_window.show_text(text, self.manager.window_handle())

    def _level_meter(self) -> str:
        """'▮▮▮▯▯': 2-3 bars = about the speech threshold, 5 = clearly speaking."""
        bars = min(5, int(self._voice_level / max(self._voice.threshold, 1e-6) * 2.5))
        return "▮" * bars + "▯" * (5 - bars)

    def _show_subtitle_status(self) -> None:
        pacer = self._pacer
        if not pacer.sentences:
            text, level = "Listening · no notes on this slide", "muted"
        elif pacer.done:
            text, level = "Notes finished on this slide", "muted"
        else:
            where = f"sentence {pacer.index + 1}/{len(pacer.sentences)}"
            text, level = (f"Speaking · {where}", "ok") if self._voice.speaking else (f"Listening · {where}", None)
        if self.live_status.text("Subtitles") != text:
            self.live_status.set("Subtitles", text, level)
        self.overlay.show_voice(f"🎤 {self._level_meter()}  {text}",
                                STATUS_COLORS["ok"] if self._voice.speaking else STATUS_COLORS["muted"])

    def _on_microphone_error(self, message: str) -> None:
        log.warning(message)
        self.live_status.set("Subtitles", message, "warn")
        self.overlay.show_voice(f"🎤 {message}", STATUS_COLORS["warn"])

    # =====================================================================
    # Time limit (normal mode)
    # =====================================================================

    def _start_limit(self) -> None:
        self._limit = TimeLimit(
            config.TIME_LIMIT_SECONDS,
            (config.OVERTIME_WARNING_1_SECONDS, config.OVERTIME_WARNING_2_SECONDS),
            config.OVERTIME_STOP_SECONDS,
            self.clock,
        )
        self._limit.start()
        self.timer_button.setText("⏸  Pause timer")
        self.timer_button.setVisible(True)
        self.timer_label.setVisible(True)
        self._show_limit()
        if config.DEBATE_TIMER_ON_SLIDE:
            self.slide_timer.show()
            self._place_slide_timer()
        self._debate_timer.start()
        log.info("Time limit: %s", format_duration(config.TIME_LIMIT_SECONDS))

    def _limit_tick(self) -> None:
        if self._limit is None or self._busy:
            return
        for alert in self._limit.tick():
            self._on_overtime(alert)
            if self._limit is None:  # the presentation was ended
                return
        self._show_limit()
        self._place_slide_timer()

    def _show_limit(self) -> None:
        limit = self._limit
        if limit is None:
            return
        left = limit.remaining()
        if left > 0:
            text, detail = f"⏱ {format_seconds(left)}", "left"
            level = "warn" if left <= config.TIME_LIMIT_WARNING_SECONDS else "ok"
        else:
            text, detail, level = f"+{format_seconds(-left)}", "over time", "error"
        if limit.paused:
            text, level = f"{text}  ⏸", "info"
        self._show_countdown(text, detail, level)

    def _on_overtime(self, alert: OvertimeAlert) -> None:
        message = alert_message(alert, config.OVERTIME_STOP_SECONDS)
        log.warning("Over time: %s", message.replace("\n", " "))
        color = STATUS_COLORS["error" if alert.stop or alert.number > 1 else "warn"]
        self.alert.show_alert(message, color, self.manager.window_handle())
        self._beep(alert.stop)
        self._add_history(f"{time.strftime('%H:%M:%S')}  ⚠ {message.splitlines()[0].strip('⚠⏹ ')}")
        if alert.stop:
            limit = format_duration(config.TIME_LIMIT_SECONDS)
            self._ended_for_time = (f"The presentation was ended automatically: "
                                    f"{format_duration(alert.overtime)} over the {limit} limit.")
            self.stop_presentation()

    @staticmethod
    def _beep(stop: bool) -> None:
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.platformName() != "windows":
            return
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONHAND if stop else winsound.MB_ICONEXCLAMATION)
        except (ImportError, RuntimeError):
            QApplication.beep()

    # -- called on the ENGINE thread --------------------------------------------------------------

    def _handle_gesture(self, gesture: Gesture) -> bool:
        if gesture == Gesture.NEXT:
            return self.manager.next_slide()
        return self.manager.previous_slide()

    def _wants_frames(self) -> bool:
        return config.SHOW_CAMERA_PREVIEW and self.pages.currentWidget() is self.presenting \
            and not self.isMinimized() and self.isVisible()

    # =====================================================================
    # Engine updates (GUI thread)
    # =====================================================================

    def _on_engine_update(self, update: EngineUpdate) -> None:
        if self.overlay.isVisible():
            self.overlay.show_update(update)
        if self.pages.currentWidget() is not self.presenting or self.isMinimized():
            return
        if update.image is not None:
            self.camera_view.show_frame(update.image)

        status = self.live_status
        s = update.status
        status.set("Hand", {0: "Not detected", 1: "Detected"}.get(s.hand_count, f"{s.hand_count} hands"),
                   "ok" if s.hand_count == 1 else "warn")
        status.set("Fingers", str(s.fingers) if s.hand_count == 1 else "—")
        status.set("Palm", "Open" if s.open_palm else ("Closed" if s.hand_count == 1 else "—"),
                   "ok" if s.open_palm else None)
        progress = s.progress
        if progress and progress.distance > 20:
            status.set("Direction", "RIGHT → LEFT" if progress.delta_x < 0 else "LEFT → RIGHT")
            status.set("Distance", f"{progress.distance:.0f} px")
        elif s.state != GestureState.COOLDOWN:
            status.set("Direction", "—")
            status.set("Distance", "—")
        status.set("Status", s.message, "warn" if update.paused else None)
        self._set_state_label("PAUSED" if update.paused else f"{update.fps:.0f} FPS · {s.state.value}",
                              "warn" if update.paused else "ok")

    def _on_command(self, result: CommandResult) -> None:
        self.overlay.show_command(result)
        label = "NEXT ➡" if result.gesture == Gesture.NEXT else "⬅ PREVIOUS"
        outcome = "Executed" if result.executed else ("Paused" if self.engine and self.engine.paused
                                                      else "Not executed")
        self.gesture_big.setText(label)
        self.live_status.set("Gesture", result.gesture.value, "ok")
        self.live_status.set("Direction", result.direction.value)
        self.live_status.set("Distance", f"{result.distance:.0f} px")
        self.live_status.set("Status", outcome, "ok" if result.executed else "warn")
        position = self.manager.position()
        where = f"  → slide {position[0]}/{position[1]}" if position else ""
        self._add_history(f"{time.strftime('%H:%M:%S')}  {label}  {outcome}{where}")
        if self._debate is not None and result.executed and position is None:
            # The app cannot report the slide, so follow the swipe to restart the timer.
            step = 1 if result.gesture == Gesture.NEXT else -1
            self._debate.start_slide(max(1, self._debate.slide + step))

    def _add_history(self, text: str) -> None:
        self.history.insertItem(0, text)
        while self.history.count() > MAX_HISTORY:
            self.history.takeItem(self.history.count() - 1)

    def _on_engine_error(self, message: str) -> None:
        self._stop_engine()
        if self.manager.session.presentation_status in (SessionState.PRESENTING, SessionState.PAUSED):
            # Keep presenting (keyboard / clicker still work) but tell the presenter.
            self.overlay.show_error(message)
            self.camera_view.show_message(message)
            self._set_state_label("CAMERA ERROR", "error")
            self.live_status.set("Status", message, "error")
            return
        self._on_start_failed(PresentationError(message))

    # =====================================================================
    # Controls
    # =====================================================================

    def toggle_pause(self) -> None:
        if self.engine is None:
            return
        self.engine.paused = not self.engine.paused
        if self.engine.paused:
            self.manager.pause()
            self.pause_button.setText("▶  Resume gestures")
        else:
            self.manager.resume()
            self.pause_button.setText("⏸  Pause gestures")

    def toggle_overlay(self) -> None:
        config.SHOW_OVERLAY = not config.SHOW_OVERLAY
        presenting = self.pages.currentWidget() is self.presenting
        self.overlay.setVisible(config.SHOW_OVERLAY and presenting)
        self._update_overlay_button()

    def _update_gesture_hint(self) -> None:
        self.gesture_hint.setText("Open all five fingers, then swipe." if config.REQUIRE_OPEN_PALM
                                  else "Move one hand sideways, like turning a page.")

    def _update_overlay_button(self) -> None:
        self.overlay_button.setText("🗔  Hide overlay" if config.SHOW_OVERLAY else "🗔  Show overlay")

    def _load_mode_controls(self) -> None:
        """Show the mode settings from config (they can also change in Settings)."""
        controls = (self.normal_radio, self.debate_radio, self.timing_combo, self.total_time,
                    self.slide_seconds, self.per_slide_check, self.time_limit_check, self.limit_time,
                    self.subtitles_check, self.mic_combo)
        for widget in controls:
            widget.blockSignals(True)
        (self.debate_radio if config.DEBATE_MODE else self.normal_radio).setChecked(True)
        self.timing_combo.setCurrentIndex(max(0, self.timing_combo.findData(config.DEBATE_TIMING)))
        self.total_time.set_seconds(config.DEBATE_TOTAL_SECONDS)
        self.slide_seconds.setValue(config.DEBATE_SLIDE_SECONDS)
        self.per_slide_check.setChecked(config.DEBATE_PER_SLIDE)
        self.time_limit_check.setChecked(config.TIME_LIMIT_ENABLED)
        self.limit_time.set_seconds(config.TIME_LIMIT_SECONDS)
        self.subtitles_check.setChecked(config.SUBTITLES_ENABLED)
        self._fill_microphones()
        for widget in controls:
            widget.blockSignals(False)
        self._update_mode_controls()

    def _fill_microphones(self) -> None:
        """Auto + every microphone Windows knows, with the chosen one selected."""
        try:
            names = list_microphones()
        except Exception as exc:  # no audio system: subtitles simply cannot start
            log.warning("Could not list microphones: %s", exc)
            names = []
        wanted = config.SUBTITLE_MICROPHONE
        blocked = self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        self.mic_combo.addItem("🎤 Auto (default microphone)", "auto")
        for name in names:
            self.mic_combo.addItem(f"🎤 {name}", name)
        if wanted != "auto" and wanted not in names:
            self.mic_combo.addItem(f"🎤 {wanted} (not connected)", wanted)
        self.mic_combo.setCurrentIndex(max(0, self.mic_combo.findData(wanted)))
        self.mic_combo.blockSignals(blocked)

    def _watch_microphones(self) -> None:
        """Refresh the list when a microphone is plugged in or removed."""
        try:
            from PySide6.QtMultimedia import QMediaDevices

            self._media_devices = QMediaDevices(self)
            self._media_devices.audioInputsChanged.connect(self._fill_microphones)
        except Exception as exc:
            log.warning("Microphone changes are not watched: %s", exc)

    def _on_mode_changed(self, *_) -> None:
        changed = settings.apply({
            "DEBATE_MODE": self.debate_radio.isChecked(),
            "DEBATE_TIMING": self.timing_combo.currentData(),
            "DEBATE_TOTAL_SECONDS": self.total_time.seconds(),
            "DEBATE_SLIDE_SECONDS": self.slide_seconds.value(),
            "DEBATE_PER_SLIDE": self.per_slide_check.isChecked(),
            "TIME_LIMIT_ENABLED": self.time_limit_check.isChecked(),
            "TIME_LIMIT_SECONDS": self.limit_time.seconds(),
            "SUBTITLES_ENABLED": self.subtitles_check.isChecked(),
            "SUBTITLE_MICROPHONE": self.mic_combo.currentData() or "auto",
        })
        if changed:
            settings.save()
        self._update_mode_controls()

    def _update_mode_controls(self) -> None:
        debate = self.debate_radio.isChecked()
        self.debate_options.setVisible(debate)
        self.normal_options.setVisible(not debate)
        total = self.timing_combo.currentData() == "total"
        self.total_time.setVisible(total)
        self.slide_seconds.setVisible(not total)
        self.limit_time.setEnabled(self.time_limit_check.isChecked())
        self.limit_hint.setVisible(self.time_limit_check.isChecked())
        self.limit_hint.setText(self._limit_hint_text())
        self.mic_combo.setVisible(self.subtitles_check.isChecked())

    @staticmethod
    def _limit_hint_text() -> str:
        warnings = sorted(w for w in (config.OVERTIME_WARNING_1_SECONDS, config.OVERTIME_WARNING_2_SECONDS)
                          if w and (not config.OVERTIME_STOP_SECONDS or w < config.OVERTIME_STOP_SECONDS))
        parts = []
        if warnings:
            parts.append("warnings at " + " and ".join(f"+{format_duration(w)}" for w in warnings) + " over")
        if config.OVERTIME_STOP_SECONDS:
            parts.append(f"ends at +{format_duration(config.OVERTIME_STOP_SECONDS)} over")
        return "  ·  ".join(parts)

    def open_settings(self) -> None:
        presenting = self.pages.currentWidget() is self.presenting
        dialog = SettingsWindow(self, presenting)
        if dialog.exec() and dialog.changed:
            if self.engine is not None:
                self.engine.reload_settings()
            self.overlay.setVisible(config.SHOW_OVERLAY and presenting)
            self._update_overlay_button()
            self._update_gesture_hint()
            self._load_mode_controls()
            timing = self._debate is not None or self._limit is not None
            self.slide_timer.setVisible(config.DEBATE_TIMER_ON_SLIDE and timing)
            restart = [k for k in dialog.changed if settings.BY_KEY[k].restart]
            if restart and presenting:
                QMessageBox.information(self, config.APP_NAME,
                                        "Camera and detection settings apply from the next presentation.")

    # =====================================================================
    # Helpers
    # =====================================================================

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.open_button.setEnabled(not busy)
        self.photos_button.setEnabled(not busy)
        self.stop_button.setEnabled(not busy)
        self.home_message.setText(message)
        if busy:
            self.setCursor(Qt.BusyCursor)
        else:
            self.unsetCursor()

    def _set_state_label(self, text: str, level: str) -> None:
        from ui.theme import STATUS_COLORS

        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color: {STATUS_COLORS[level]}; font-weight: 600;")

    def show_error(self, message: str) -> None:
        log.error(message.replace("\n", " "))
        QMessageBox.critical(self, config.APP_NAME, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._poll.stop()
        self._stop_timers()
        self._stop_engine()
        self.overlay.close()
        self.slide_timer.close()
        self.alert.close()
        self.subtitle_window.close()
        self.manager.exit_presentation()
        super().closeEvent(event)
