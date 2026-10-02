"""
AirSlide configuration.

Every tunable value lives here so no magic numbers are scattered through the
code. Modules import this file (``import config``) and read values at runtime,
which also lets the Settings window change them while the app is running.
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
APP_NAME = "AirSlide"
APP_TAGLINE = "Present Without Touching."
APP_VERSION = "0.3.0"

# True when running as the packaged AirSlide.exe (PyInstaller).
FROZEN = getattr(sys, "frozen", False)

# Read-only resources (the hand model). In the .exe they are unpacked to a
# temporary folder (sys._MEIPASS) that is deleted when the app exits.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ASSETS_DIR = BASE_DIR / "assets"

# Writable files must live outside that temporary folder when packaged.
USER_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AirSlide"
LOG_DIR = USER_DATA_DIR / "logs" if FROZEN else BASE_DIR / "logs"

# Show the debug overlay (FPS, landmarks, swipe numbers, state) on the preview.
DEBUG = True

# Logging: "DEBUG", "INFO", "WARNING", "ERROR"
LOG_LEVEL = "INFO"
LOG_TO_FILE = True

# ---------------------------------------------------------------------------
# Supported files
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {
    ".pptx": "PowerPoint Presentation",
    ".pdf": "PDF Document",
    ".jpg": "Photo",
    ".jpeg": "Photo",
    ".png": "Photo",
    ".gif": "Photo",
}

# ---------------------------------------------------------------------------
# Photo slideshow (AirSlide shows the photos itself, full screen)
# ---------------------------------------------------------------------------
# Style: "classic" (instant), "fade", "slide", "zoom", "kenburns" (slow pan and
# zoom), "polaroid" (framed prints on a dark table), "blur" (in front of a blurred
# copy), "carousel", "flip", "wipe", "circle", "tiles" (mosaic), "blinds",
# "vintage" (sepia) and "mono" (black and white). See ui/photo_show.py STYLES.
PHOTO_STYLE = "fade"
# Order: "name" (IMG_2 before IMG_10), "date" (file date, oldest first),
# "shuffle", or "selected" (as chosen in the file dialog).
PHOTO_ORDER = "name"
PHOTO_FILL = False                  # True = fill the screen (crop the edges), False = whole photo
PHOTO_TRANSITION_MS = 800           # length of the change animation
PHOTO_KEN_BURNS_SECONDS = 12        # one slow zoom lasts this long, then the photo holds still
# Auto play: the next photo appears after this many seconds (swipes and keys still
# work and restart the time; S pauses). Not used in debate mode, which sets the times.
PHOTO_AUTOPLAY = False
PHOTO_AUTOPLAY_SECONDS = 5
# Loop: after the last photo, start again with the first (no "End of slideshow").
PHOTO_LOOP = False

# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
CAMERA_INDEX = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
CAMERA_FPS = 30

# Capture backend: "msmf" (Media Foundation), "dshow" (DirectShow) or "any".
# MSMF is the default: measured 30 FPS at 1280x720 on the development webcam,
# where DirectShow only delivered uncompressed YUY2 at ~10 FPS.
CAMERA_BACKEND = "msmf"
# Tried automatically if CAMERA_BACKEND cannot open the webcam (None = no fallback).
CAMERA_FALLBACK_BACKEND = "dshow"
# Ask the webcam for MJPG frames (many USB webcams only reach 720p@30 in MJPG).
# Set to None to keep the driver default.
CAMERA_FOURCC = "MJPG"

# Number of frames used to average the FPS measurement.
FPS_AVERAGE_FRAMES = 30

# Flip the frame horizontally so the preview behaves like a mirror.
# With mirroring ON, a hand moving from the presenter's RIGHT to their LEFT
# moves from the right side of the image to the left side (delta_x < 0).
# This is verified against a real webcam in STEP 5.
MIRROR_CAMERA = True

# Seconds of consecutive failed frame reads before the camera is reported lost.
CAMERA_READ_TIMEOUT = 2.0

# Seconds to wait for the FIRST frame after opening. Some webcams need a moment
# (e.g. right after another app released them) before MSMF delivers images.
CAMERA_FIRST_FRAME_TIMEOUT = 1.5

# ---------------------------------------------------------------------------
# Hand detection (MediaPipe)
# ---------------------------------------------------------------------------
# Several hands are detected so the presenter's hand is still found when
# other people raise theirs; the presenter focus below picks one of them.
MAX_NUM_HANDS = 4
# 0.5 instead of 0.7: blurred (fast) and small (far away) hands score lower.
MIN_DETECTION_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5
MIN_PRESENCE_CONFIDENCE = 0.5

HAND_MODEL_PATH = ASSETS_DIR / "models" / "hand_landmarker.task"
HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)

# ---------------------------------------------------------------------------
# Presenter focus and long-distance zoom (MediaPipe Pose)
# ---------------------------------------------------------------------------
# Find the people in the image with the pose model, choose the presenter
# (the biggest person, then keep following them) and only accept hands within
# the presenter's arm reach. Hands of other people are ignored.
PRESENTER_FOCUS = True
MAX_NUM_POSES = 3

# A hand belongs to the presenter when its wrist is within this many shoulder
# widths of the presenter's shoulder centre (a stretched arm is about 2).
PRESENTER_REACH = 2.5

# Once a presenter (or, without a visible body, a hand) is chosen, it stays
# chosen while it is out of sight for up to this many seconds.
PRESENTER_LOCK_SECONDS = 1.5

# Without a visible body, a hand only replaces the chosen hand when it is
# within this many palm sizes of it (fast swipes move a few palm sizes).
HAND_LOCK_RADIUS = 6.0

# Far from the camera the hand is too small for the hand model to find in the
# full image. Hands are then searched in a zoomed square around the presenter:
# ZOOM_BODY_SPAN shoulder widths wide (enough for both stretched arms), at
# least ZOOM_MIN_SIZE pixels. Zoom is used while that square is smaller than
# the frame height (the presenter is about 2 m or more away).
LONG_DISTANCE_ZOOM = True
ZOOM_BODY_SPAN = 5.0
ZOOM_MIN_SIZE = 256
# How quickly the zoom square follows the presenter (0..1, 1 = instantly).
# Smoothing keeps the hand tracking stable while the presenter walks.
ZOOM_SMOOTHING = 0.3

POSE_MODEL_PATH = ASSETS_DIR / "models" / "pose_landmarker_lite.task"
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)
# The pose model works on a small image anyway; halving the frame first saves time.
POSE_INPUT_SCALE = 0.5
# People move slowly compared with hands, so the pose model (about 20 ms) only
# runs every N frames and its result is reused in between.
POSE_EVERY_N_FRAMES = 2
MIN_POSE_CONFIDENCE = 0.5

# ---------------------------------------------------------------------------
# Open palm detection
# ---------------------------------------------------------------------------
# False (default): any single hand moving left/right changes slides - easiest.
# True: the hand must show all five fingers open before a swipe counts
# (fewer accidental swipes for presenters who talk with their hands).
REQUIRE_OPEN_PALM = False

# A finger counts as extended when its joints are nearly straight
# (angle at each joint close to 180 degrees). Angle-based, so it is robust
# to hand rotation rather than relying on a simple Y comparison.
FINGER_STRAIGHT_ANGLE = 150.0  # degrees, PIP and DIP joints of index..pinky
FINGER_MCP_ANGLE = 120.0       # degrees, knuckle joint (wrist-MCP-PIP) of index..pinky
THUMB_STRAIGHT_ANGLE = 140.0   # degrees, thumb MCP and IP joints (thumb bends less)

# Fingertip must be farther from the wrist than its PIP joint by this ratio.
FINGER_EXTENSION_RATIO = 1.1

# Thumb tip must be at least this far from the index knuckle, as a fraction
# of the palm size (wrist -> middle knuckle). Rejects a thumb tucked across the palm.
THUMB_SPREAD_RATIO = 0.5

# The hand (open, in five-finger mode) must be seen in this many consecutive
# frames before a swipe can fire (debounce). The movement is recorded from the
# first frame, so a hand that enters already moving still counts.
OPEN_PALM_MIN_FRAMES = 3

# ---------------------------------------------------------------------------
# Swipe detection
# ---------------------------------------------------------------------------
# Distances are in pixels of the (FRAME_WIDTH x FRAME_HEIGHT) frame.
MIN_SWIPE_DISTANCE = 150       # minimum horizontal travel (hand close to the camera)
MAX_SWIPE_DURATION = 1.0       # seconds from swipe start to threshold
# Horizontal means |dx| > |dy| * HORIZONTAL_RATIO (1.0 = spec's |dx| > |dy|).
HORIZONTAL_RATIO = 1.0

# Far from the camera the hand moves fewer pixels: the distance is lowered to
# this many palm sizes (wrist -> middle knuckle, about 9 cm) ...
SWIPE_DISTANCE_PALMS = 1.5
# ... but never below this many pixels (landmark jitter).
MIN_SWIPE_DISTANCE_FAR = 40

# A fast swipe blurs the hand, so it may disappear for a moment. The swipe
# keeps being tracked while the hand is missing for up to this many seconds.
SWIPE_LOST_SECONDS = 0.4

# ---------------------------------------------------------------------------
# Gesture state machine
# ---------------------------------------------------------------------------
COOLDOWN_SECONDS = 1.0

# ---------------------------------------------------------------------------
# Presentation control
# ---------------------------------------------------------------------------
# PowerPoint is driven through COM automation (pywin32). Next/Previous use
# the slide show's own View.Next()/View.Previous(), so animations and
# transitions play exactly as PowerPoint defines them.
POWERPOINT_OPEN_READ_ONLY = True
POWERPOINT_CLOSE_ON_EXIT = True

# PDF viewer:
#   "auto"     - use SumatraPDF if found, otherwise the Windows default viewer
#   "sumatra"  - require SumatraPDF (best: real presentation mode via CLI)
#   "default"  - the Windows default PDF app (Edge, Acrobat, PDFgear, ...)
#   a path     - any other viewer .exe (uses the "default" key profile below)
PDF_VIEWER = "auto"
# Optional explicit path to SumatraPDF.exe; None = search common locations.
SUMATRA_PATH = None

# Keys AirSlide presses in the PDF viewer window ("right", "page_down",
# "f5", "ctrl+l", ...). "fullscreen" is pressed once after opening (None = skip)
# and "exit" when the presentation ends.
PDF_VIEWER_KEYS = {
    "sumatra": {"next": "right", "previous": "left", "fullscreen": None, "exit": None},
    "default": {"next": "page_down", "previous": "page_up", "fullscreen": None, "exit": None},
}

# Seconds to wait for a viewer window to appear after launching.
VIEWER_STARTUP_TIMEOUT = 15.0

# ---------------------------------------------------------------------------
# Debate presentation (timed slides)
# ---------------------------------------------------------------------------
# Debate mode moves to the next slide automatically when the slide's time is
# up. Gestures keep working; a swipe restarts the timer for the new slide.
DEBATE_MODE = False
# "total": DEBATE_TOTAL_SECONDS is divided equally between the slides.
# "per slide": every slide gets DEBATE_SLIDE_SECONDS.
DEBATE_TIMING = "total"
DEBATE_TOTAL_SECONDS = 600
# Time for every slide, unless a slide has its own time (advanced option).
DEBATE_SLIDE_SECONDS = 60
# Ask for a separate time for each slide after choosing the file.
DEBATE_PER_SLIDE = False
# The countdown turns orange in the last this-many seconds of a slide.
DEBATE_WARNING_SECONDS = 10
# Show a large countdown in the bottom-right corner of the slide show itself
# (on the projector / audience screen), not only in the overlay.
DEBATE_TIMER_ON_SLIDE = True
DEBATE_TIMER_FONT_PT = 28
DEBATE_TIMER_MARGIN = 24    # px from the slide's bottom-right corner
# How often (ms) the countdown is refreshed and checked.
DEBATE_TICK_MS = 250

# ---------------------------------------------------------------------------
# Time limit (normal presentation, optional)
# ---------------------------------------------------------------------------
# Presenters spend the time on the slides as they like; only the total counts.
# Over the limit, alerts appear on the slide (with a sound) this many seconds
# over time, and at OVERTIME_STOP_SECONDS the presentation is ended.
TIME_LIMIT_ENABLED = False
TIME_LIMIT_SECONDS = 1200
OVERTIME_WARNING_1_SECONDS = 120
OVERTIME_WARNING_2_SECONDS = 180
OVERTIME_STOP_SECONDS = 300          # 0 = only warn, never end the presentation
# The countdown turns orange for the last this-many seconds before the limit.
TIME_LIMIT_WARNING_SECONDS = 120
# How long an alert stays on the slide.
OVERTIME_ALERT_SECONDS = 8

# ---------------------------------------------------------------------------
# Subtitles from speaker notes
# ---------------------------------------------------------------------------
# While the presenter speaks (detected with the microphone), the current
# slide's speaker notes are shown at the bottom of the slide, one sentence at
# a time. Slides without notes show nothing. The words are NOT recognised:
# each sentence stays for about as long as it takes to say (see the speaking
# speed below), and the next one appears when the presenter pauses after it.
SUBTITLES_ENABLED = False
SUBTITLE_WORDS_PER_MINUTE = 140     # the presenter's speaking speed
SUBTITLE_MIN_SECONDS = 1.2          # even a short sentence takes this long
SUBTITLE_MAX_CHARS = 110            # longer sentences are split (at commas if possible)
SUBTITLE_ADVANCE_AT = 0.6           # a pause moves on after this share of the sentence's time ...
SUBTITLE_FORCE_AT = 1.6             # ... and without a pause after this share
SUBTITLE_HIDE_AFTER_SECONDS = 2.5   # hide the subtitle when the presenter is quiet this long
SUBTITLE_FONT_PT = 22
SUBTITLE_MARGIN = 40                # px from the bottom of the slide
SUBTITLE_WIDTH_RATIO = 0.62         # max width as a share of the slide width

# "auto" = the Windows default microphone (or the next one if it gives no sound
# at all), or the name of a microphone as listed on the home screen.
SUBTITLE_MICROPHONE = "auto"

# Voice detection: loudness (RMS, 0..1) of the microphone signal. A laptop
# microphone hears a quiet room at about 0.001 and a presenter 2 m away at 0.005+.
VOICE_MIN_LEVEL = 0.003             # never count quieter sound as speech
VOICE_NOISE_RATIO = 3.0             # speech = this many times louder than the room's background noise
VOICE_START_SECONDS = 0.12          # loud this long = speaking
VOICE_PAUSE_SECONDS = 0.35          # quiet this long = a pause (after the smoothed loudness falls)

# ---------------------------------------------------------------------------
# User interface
# ---------------------------------------------------------------------------
SHOW_OVERLAY = True
SHOW_CAMERA_PREVIEW = True

# The camera preview in the window is scaled to this width before it is sent
# to the GUI (the full-resolution frame is still used for detection).
PREVIEW_WIDTH = 640

# Floating overlay: which screen corner and the distance from the edges (px).
OVERLAY_CORNER = "bottom-right"   # "bottom-right", "bottom-left", "top-right", "top-left"
OVERLAY_MARGIN = 24

# How often (ms) the window checks whether the presentation is still running
# (e.g. the presenter pressed Esc in PowerPoint).
PRESENTATION_POLL_MS = 1000

# Settings changed in the Settings window are saved here and loaded at start.
SETTINGS_FILE = Path.home() / "AppData" / "Roaming" / "AirSlide" / "settings.json"
