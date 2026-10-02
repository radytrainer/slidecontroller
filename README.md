# 🖐️ AirSlide

**Present Without Touching.**

## Project Overview

AirSlide is a Windows desktop app that lets a presenter control a PowerPoint
(`.pptx`) or PDF (`.pdf`) presentation with hand gestures in front of a webcam.

> **AirSlide controls the presentation. It does not recreate it.**
> PowerPoint itself shows `.pptx` files, so themes, fonts, animations,
> transitions, video and audio all work exactly as designed. A PDF viewer shows
> `.pdf` files unmodified. AirSlide only sends *Next* and *Previous*.

| Gesture | Result |
| --- | --- |
| ✋ Move one hand **right → left** | ➡️ Next (next animation step or slide) |
| ✋ Move one hand **left → right** | ⬅️ Previous |

## Features

- Opens `.pptx` files in Microsoft PowerPoint and starts the slide show.
- Opens `.pdf` files in SumatraPDF or the Windows default PDF app.
- Real-time hand tracking with MediaPipe (about 23–30 FPS on a laptop webcam).
- Any hand shape works by default. An optional five-finger (open palm) mode uses
  joint angles, so it works whatever the hand's rotation or distance.
- Swipe detection with distance, speed and "horizontal only" checks, plus a cooldown.
- Keeps PowerPoint's own behaviour: each *Next* plays the next animation step.
- Professional PySide6 interface: home screen, live status, camera preview,
  recent commands, pause, and a floating overlay that never steals focus.
- Settings window for every threshold (saved in `%APPDATA%\AirSlide\settings.json`).
- Debug view with FPS, landmarks, swipe numbers and the gesture state.
- Clear messages for every expected problem (no PowerPoint, no camera, wrong file, ...).
- 138 automated tests, plus a real PowerPoint integration test.

## System Architecture

```text
                              AIRSLIDE
                                 │
          ┌──────────────────────┴───────────────────────┐
          │                                              │
   PresentationManager                            GestureEngine  (background thread)
          │                                              │
   ┌──────┴───────┐                      Camera ─▶ HandDetector (MediaPipe)
   │              │                                      │
 .pptx          .pdf                         is_open_palm  +  get_hand_center
   │              │                                      │
PowerPoint-    PDFController                        SwipeDetector
Controller     (viewer window                            │
(COM)           + keys)                         GestureStateMachine (cooldown)
   │              │                                      │
PowerPoint     SumatraPDF /                    NEXT / PREVIOUS ──┐
slide show     default viewer                                   │
   ▲              ▲                                             │
   └──────────────┴──────── next_slide() / previous_slide() ◀───┘

 ui/ (PySide6): MainWindow · OverlayWindow · SettingsWindow
```

| Folder | Responsibility |
| --- | --- |
| `src/camera/` | Webcam capture, FPS, mirroring, camera errors |
| `src/hand/` | MediaPipe Hand Landmarker, 21 landmarks, drawing |
| `src/gesture/` | Open palm, hand centre, swipe detector, state machine, debug overlay |
| `src/engine/` | Background thread tying camera → gesture → command |
| `src/presentation/` | `PresentationController` interface, PowerPoint + PDF controllers, `PresentationManager` |
| `src/utils/` | Logging, settings, health check, Windows helpers, COM thread |
| `ui/` | Main window, overlay, settings window, theme |
| `tools/` | Test-file generator |
| `tests/` | pytest suite |

The gesture engine only calls `next_slide()` and `previous_slide()` on a
`PresentationController`. It never knows whether PowerPoint or a PDF viewer is
behind it.

## Gesture Controls

1. Face the webcam and hold up **one** hand. Any hand shape works.
2. Move it sideways in one smooth movement, like turning a page:
   - **right → left** (towards your left) = **Next**
   - **left → right** = **Previous**
3. Wait for the cooldown (about 1 s) before the next swipe.

These do nothing: vertical movements, small or slow movements.

**Presenter focus.** Only the presenter controls the slides. AirSlide finds
the people in the image (MediaPipe Pose), picks the biggest one (usually the
person nearest the camera) and keeps following them. Hands of other people,
such as someone in the audience waving, are ignored. If no body is visible,
for example just a hand close to the camera, the biggest hand is chosen and
followed. The debug preview marks the presenter in pink and ignored hands in grey.

**Fast swipes and long distance.** A quick swipe may blur the hand so the
model loses it for a moment. The swipe is kept for up to 0.4 s without the hand.
Far from the camera the hand looks small, so the swipe distance is measured
in hand sizes (1.5 palms) instead of a fixed 150 px. The hand is also
searched for in a zoomed square around the presenter (the orange box in the
debug preview), because in the full image a distant hand is too small for the
hand model.

**Photo slideshow.** Click **🖼 Photo slideshow…** (or select several photos with
*Open Presentation*) and choose JPG, PNG or GIF photos. A setup window shows your
photos and a **live preview** of the chosen style:

| Style | Look |
| --- | --- |
| Classic | Photos change instantly, like a projector |
| Fade | Each photo gently fades into the next |
| Slide | Photos slide in from the side, like turning pages |
| Zoom | The next photo softly zooms in |
| Ken Burns | A slow pan and zoom across every photo, like a documentary |
| Polaroid | Framed prints (with the file name) dropped on a dark table |
| Soft backdrop | Each photo in front of a blurred copy of itself, so portrait photos have no black bars |
| Carousel | Photos glide past in a row, with the previous and next ones peeking in at the sides |
| Flip | Each photo turns over like a card |
| Wipe | The next photo sweeps across the screen |
| Circle | The next photo opens from the middle in a growing circle |
| Mosaic | The next photo appears tile by tile |
| Blinds | The next photo opens like window blinds |
| Vintage | Warm sepia tones and darkened corners, like old prints |
| Black & white | Black-and-white photos with soft fades |

Also choose the order (by name, where IMG_2 comes before IMG_10; by date; shuffle; or as
selected) and whether photos *fill the screen* (edges cropped) or are shown whole.

- **Play automatically, every N s:** the next photo appears on its own. A swipe or key
  still works and gives the new photo its full time. **S** pauses and resumes, as in
  PowerPoint. *Ken Burns* stretches its slow move over each photo's time. Debate
  mode switches auto play off because it sets the times itself.
- **Loop:** after the last photo the slideshow starts again with the first (no
  "End of slideshow" screen), and going back from the first photo shows the last.
  With auto play this runs until you press Esc, e.g. at an event.
AirSlide shows the photos itself, full screen on the projector (the second screen
if there is one). Phone photos appear upright and animated GIFs play. Swipes,
the arrow keys, a clicker, the mouse wheel or a click change photos, and **Esc**
ends the slideshow. Debate mode, the time limit and the timer on the slide work
with photos too. Files that are not really photos are skipped.

**Subtitles from speaker notes.** Tick *Subtitles from speaker notes* on the
home screen (works in both modes). While the presenter speaks, the current
slide's **speaker notes** appear at the bottom of the slide, on the audience
screen, **one sentence at a time**. Slides without notes show nothing, and PDFs
have no notes. How it works:

- The microphone only measures *when* the presenter is speaking, compared with the
  room's background noise. The words are not recognised, so it works for any
  language (Khmer `។` is a sentence end too), offline, and no audio is stored.
- Each sentence gets the time it takes to say it (*Speaking speed*, 140 words/min).
  The next sentence appears when the presenter starts speaking again after a pause,
  once they have spoken for at least 60 % of that time. Without any pause it moves on
  at 160 %. Sentences longer than 110 characters are split, at a comma if possible.
- The subtitle hides when the presenter is quiet for 2.5 s, and starts again at the
  first sentence on every new slide.
- The *Subtitles* row on AirSlide's presenting page shows `Speaking · sentence 2/5`.

**Microphone.** Next to the checkbox, choose the microphone the presenter speaks
into. *Auto* uses the Windows default, but if that device gives no sound at all
(e.g. a USB audio adapter or headset nobody speaks into) it switches to the next
microphone after 2 s. During the show the overlay shows what the microphone hears,
e.g. `🎤 ▮▮▮▮▯  Speaking · sentence 2/5`. If the bars stay at `▯▯▯▯▯` while you
talk, choose another microphone or lower *Microphone threshold*.

If the subtitles run ahead of you, lower *Speaking speed* in Settings → *Subtitles*.
If they fall behind, raise it. If noise shows subtitles while nobody talks, raise
*Microphone threshold*. Subtitles only follow the notes: if you say
something else, they drift until the next slide.

**Time limit (normal mode, optional).** Under *Normal*, tick *Time limit* and set
the time, e.g. 0:20:00. Presenters spend the time on the slides however they like,
since only the total counts. The countdown shows on the slide (bottom right), in the
overlay and in AirSlide. It turns orange in the last 2 minutes, and after the limit it
turns red and counts the overtime (`+0:42 over time`). Over time, an alert
appears in the middle of the slide with a warning sound:

| Over the limit | What happens |
| --- | --- |
| +2 min | Warning 1/3: "Please finish. The presentation ends at 5 min over." |
| +3 min | Warning 2/3 |
| +5 min | The slide show is ended automatically, and AirSlide says why on its home screen |

The times can be changed in Settings → *Time limit* (0 = no warning / never end).
*Pause timer* stops the clock, for example for questions.

**Debate presentation (timed slides).** On the home screen, choose
*Debate · slides advance automatically* under **Presentation mode**, then pick the
*Timing*:

- *Total time, divided equally*: e.g. 0:10:00 for 8 slides gives each slide 75 s
  (leftover seconds go to the first slides, so the times add up exactly).
- *Same time for every slide*: e.g. 60 s each.

During the slide show a large countdown sits in the **bottom-right corner of the
slide** (`⏱ 0:42` over `3/10`), on the screen the audience sees, so with a
projector it is on the projector. Clicks pass through it and it never takes
the keyboard focus. If the floating overlay is in the same corner, the timer
sits just above it. Turn it off with *Show timer on the slide* in Settings.
The same countdown also appears in the floating overlay (`⏱ 0:42 · 3/10`).
Both turn orange in the last 10 s. When the time is up, AirSlide
goes to the next slide, skipping any animation steps not yet played. Gestures
still work, and a swipe starts the new slide's full time. *Pause timer* stops
the countdown. *Pause gestures* does not, so the show can run hands-free.
On the last slide the timer shows *TIME UP* and the slide stays on screen.

*Advanced: a time for each slide.* Tick *Edit the time of each slide*. After you
choose the file, a list of every slide opens where each slide gets its own
time. With a total time, the list starts with the total divided equally and shows
the sum of all slides, which turns orange when your edits no longer match the
total (*Divide equally* resets it). With a fixed time, *Set all to* fills every row. The number of slides is read from the
file (hidden PowerPoint slides are skipped). If a PDF's pages cannot be
counted, enter the number. The times are remembered until AirSlide is closed.

**Five-finger mode (optional).** If you talk with your hands and get accidental
slide changes, turn on *Require all five fingers open* in Settings
(`REQUIRE_OPEN_PALM = True`). Then only an open hand 🖐️ can swipe, and a fist
or partly open hand is ignored.

## Supported Files

| Type | Opened with | Navigation |
| --- | --- | --- |
| PowerPoint Presentation (`*.pptx`) | Microsoft PowerPoint (slide show) | COM `View.Next()` / `View.Previous()` |
| PDF Document (`*.pdf`) | SumatraPDF (presentation mode) or the Windows default PDF app | Viewer keys (configurable) |

Files are checked by extension **and** content signature before opening, and
are never modified. PowerPoint files are opened read-only.

## PowerPoint Requirements

- Desktop **Microsoft PowerPoint** (Microsoft 365 or 2016+). The web version and
  PowerPoint Viewer cannot be automated.
- If PowerPoint is already running, AirSlide uses it. It only closes the
  presentation it opened itself, and only quits PowerPoint if AirSlide started it.

## PDF Requirements

- **Recommended:** [SumatraPDF](https://www.sumatrapdfreader.org/)
  (`winget install SumatraPDF.SumatraPDF`). It starts directly in full-screen
  presentation mode and responds to Right/Left.
- **Otherwise:** the Windows default PDF app is used and sent PageDown/PageUp.
  Viewers differ, so set the right keys in `config.PDF_VIEWER_KEYS["default"]`
  (e.g. `"right"`, `"page_down"`, `"ctrl+l"` for full screen in Acrobat).

## Installation

Requirements: Windows 10/11, Python 3.11–3.13 (64-bit), a webcam, PowerPoint for `.pptx`.

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py --check
```

If several Python versions are installed, use for example `py -3.13 -m venv venv`.
The MediaPipe hand model (`assets/models/hand_landmarker.task`, ~8 MB) and pose
model (`assets/models/pose_landmarker_lite.task`, ~6 MB) are downloaded
automatically on first use.

## Build the installer

AirSlide is packaged as a normal Windows installer, `dist\AirSlide-Setup-<version>.exe`.
It includes Python, all libraries and the hand and pose models, so the target PC
needs no Python install and no internet connection.

```bash
powershell -ExecutionPolicy Bypass -File build.ps1               # installer (recommended)
powershell -ExecutionPolicy Bypass -File build.ps1 -SingleFile   # one portable AirSlide.exe
```

The script checks the models, creates `assets\airslide.ico`, runs the tests,
builds the program folder with PyInstaller ([AirSlide.spec](AirSlide.spec)) and
then the installer with [Inno Setup 6](https://jrsoftware.org/isinfo.php)
([installer/AirSlide.iss](installer/AirSlide.iss); `winget install JRSoftware.InnoSetup`).
It takes a few minutes.

**Why an installer?** A single-file `.exe` unpacks itself into a temporary folder
on every start, which is also what much malware does, so antivirus programs
often quarantine it. The installed program is an ordinary folder
(`AirSlide.exe` next to its files), which antivirus trusts far more, and it starts
faster. Only signing with a code-signing certificate removes all warnings.

Installing:

- Run `AirSlide-Setup-<version>.exe` and choose **Install for me only** (no
  administrator rights needed) or **for all users** (Program Files, needs admin).
- It adds a Start menu shortcut, an optional desktop shortcut, and an entry in
  *Settings → Apps* to uninstall. Running a newer installer updates AirSlide
  and keeps the settings.
- Silent install for many computers: `AirSlide-Setup-<version>.exe /VERYSILENT /CURRENTUSER`
  (or `/ALLUSERS` from an administrator prompt).

Using the installed AirSlide:

- The target PC still needs Windows 10/11, a webcam, and PowerPoint for `.pptx` files.
  PDFs work best with SumatraPDF installed. Photo slideshows need nothing extra.
- Subtitles use the microphone: in Windows *Settings → Privacy & security →
  Microphone*, "Let desktop apps access your microphone" must be on.
- The developer options work too: `AirSlide.exe --check`,
  `AirSlide.exe --gesture-test`, and so on. Output appears in the terminal you
  started it from.
- Logs are written to `%LOCALAPPDATA%\AirSlide\logs\airslide.log` and settings
  to `%APPDATA%\AirSlide\settings.json`.
- Unsigned `.exe` files can trigger Windows SmartScreen ("Windows protected
  your PC" → *More info* → *Run anyway*). Signing the file with a
  code-signing certificate removes that warning.

## Configuration

Every threshold lives in [config.py](config.py). The most important values can
also be changed in the app (**⚙ Settings**).

| Setting | Default | Meaning |
| --- | --- | --- |
| `REQUIRE_OPEN_PALM` | False | True = only an open five-finger hand can swipe |
| `MIN_SWIPE_DISTANCE` | 150 px | Sideways travel needed close to the camera (for a 1280 px wide image) |
| `SWIPE_DISTANCE_PALMS` | 1.5 | Far away: travel needed in palm sizes (at least `MIN_SWIPE_DISTANCE_FAR` = 40 px) |
| `SWIPE_LOST_SECONDS` | 0.4 s | How long a blurred hand may vanish during a fast swipe |
| `PRESENTER_FOCUS` | True | Only the presenter's hands count |
| `PRESENTER_REACH` | 2.5 | A hand belongs to the presenter within this many shoulder widths |
| `LONG_DISTANCE_ZOOM` | True | Search for a far presenter's hand in a zoomed square |
| `MAX_SWIPE_DURATION` | 1.0 s | Slower movements are ignored |
| `COOLDOWN_SECONDS` | 1.0 s | Swipes ignored after a command |
| `HORIZONTAL_RATIO` | 1.0 | Sideways movement must exceed vertical × this |
| `FINGER_STRAIGHT_ANGLE` | 150° | Joint angle for a straight finger |
| `THUMB_SPREAD_RATIO` | 0.5 | Thumb distance from the palm |
| `MIN_DETECTION_CONFIDENCE` | 0.5 | MediaPipe confidence (lower finds blurred and distant hands) |
| `CAMERA_INDEX` | 0 | Which webcam |
| `MIRROR_CAMERA` | True | Preview behaves like a mirror |
| `PDF_VIEWER` | auto | `auto`, `sumatra`, `default` or a path to a viewer .exe |
| `DEBATE_MODE` | False | Slides advance automatically when their time is up |
| `DEBATE_TIMING` | total | `total` (divided between the slides) or `per slide` |
| `DEBATE_TOTAL_SECONDS` | 600 s | Total time for the whole presentation |
| `DEBATE_SLIDE_SECONDS` | 60 s | Time for every slide without its own time |
| `DEBATE_PER_SLIDE` | False | Ask for a time for each slide after choosing the file |
| `DEBATE_WARNING_SECONDS` | 10 s | Countdown turns orange for the last seconds |
| `DEBATE_TIMER_ON_SLIDE` | True | Large countdown in the bottom-right corner of the slide show |
| `TIME_LIMIT_ENABLED` | False | Normal mode: time limit for the whole presentation |
| `TIME_LIMIT_SECONDS` | 1200 s | The limit (20 min) |
| `OVERTIME_WARNING_1_SECONDS` / `_2_` | 120 / 180 s | Warnings this long over the limit |
| `OVERTIME_STOP_SECONDS` | 300 s | End the slide show this long over the limit (0 = never) |
| `PHOTO_STYLE` | fade | classic, fade, slide, zoom, kenburns, polaroid, blur, carousel, flip, wipe, circle, tiles, blinds, vintage, mono |
| `PHOTO_ORDER` | name | name, date, shuffle, selected |
| `PHOTO_FILL` | False | True = photos fill the screen (edges cropped) |
| `PHOTO_TRANSITION_MS` | 800 ms | Length of the change animation |
| `PHOTO_AUTOPLAY` / `PHOTO_AUTOPLAY_SECONDS` | False / 5 s | Next photo automatically after this long |
| `PHOTO_LOOP` | False | Start again after the last photo |
| `SUBTITLES_ENABLED` | False | Show speaker notes as subtitles while the presenter speaks |
| `SUBTITLE_WORDS_PER_MINUTE` | 140 | Speaking speed used to pace the sentences |
| `SUBTITLE_FONT_PT` | 22 pt | Subtitle text size |
| `SUBTITLE_MICROPHONE` | auto | Microphone for subtitles (`auto` or a device name, chosen on the home screen) |
| `VOICE_MIN_LEVEL` | 0.003 | Quieter microphone sound never counts as speaking |
| `DEBUG` | True | Debug drawing on the camera preview |

## How to Run

```bash
python main.py                              # the AirSlide app
```

Developer tools:

```bash
python main.py --check                      # environment health check
python main.py --camera-test                # webcam, FPS, resolution
python main.py --hand-test                  # 21 landmarks + finger states + joint angles
python main.py --gesture-test               # full gesture pipeline + debug panel (no presentation)
python main.py --control-test talk.pptx     # presentation control without the camera
```

## How Gesture Detection Works

1. **Camera** (`Camera`): 1280×720 frames at ~30 FPS through Media Foundation,
   mirrored so the preview behaves like a mirror.
2. **Presenter and hand landmarks** (`PresenterHandDetector`): MediaPipe Pose
   finds the people (every 2nd frame) and the presenter is chosen. MediaPipe Hand Landmarker in *video*
   mode tracks up to four hands and returns 21 landmarks per hand, in pixels.
   It searches the full frame, or a zoomed square around a far presenter. Only
   the presenter's hand is passed on (`PresenterFocus`).
3. **Open palm** (`is_open_palm`, only used in five-finger mode): each finger
   is judged by the **angles at its joints**. A straight finger has angles near 180°, a curled one much less.
   Index to pinky must be straight at all three joints, with the tip farther
   from the wrist than the middle joint. The thumb must be straight *and* spread
   away from the palm. All five must be extended, for 3 frames in a row.
4. **Hand centre** (`get_hand_center`): the mean of the wrist and the four
   knuckles. It is stable while the fingers move.
5. **Swipe** (`SwipeDetector`) and **state machine** (`GestureStateMachine`):
   see below.

## Swipe Algorithm

```text
every frame with one hand (an open palm in five-finger mode):
    add (time, x, y) of the palm centre to the path
    drop points older than MAX_SWIPE_DURATION
    start = the point in the path farthest (horizontally) from now
    delta_x = x - start.x,  delta_y = y - start.y
    required = min(MIN_SWIPE_DISTANCE, max(MIN_SWIPE_DISTANCE_FAR, 1.5 × palm size))
    if |delta_x| >= required and |delta_x| > |delta_y|:
        mirrored image:  delta_x < 0  →  presenter moved RIGHT → LEFT  →  NEXT
                         delta_x > 0  →  presenter moved LEFT → RIGHT  →  PREVIOUS
        clear the path; start COOLDOWN
```

States: `IDLE → HAND_DETECTED → OPEN_PALM → TRACKING → SWIPE_DETECTED →
COMMAND_EXECUTED → COOLDOWN → IDLE` (`OPEN_PALM` only in five-finger mode).
Losing the hand for more than `SWIPE_LOST_SECONDS` (0.4 s) resets the swipe.
The movement is recorded from the first frame the hand is seen. A swipe can
only fire once the hand has been seen for `OPEN_PALM_MIN_FRAMES` frames.

## PowerPoint Integration

`PowerPointController` uses COM automation (`pywin32`):

- `Presentations.Open(file, ReadOnly)`, then `SlideShowSettings.Run()`, then the slide show window is brought to the front.
- Next and Previous call `SlideShowWindow.View.Next()` / `.Previous()`. This is
  the same as the arrow keys, so **animations play one step at a time and
  transitions, video and audio behave natively**. Verified by
  `tests/test_powerpoint_integration.py`, which asserts that slide 3's three
  animations each take one Next.
- All COM calls run on one dedicated thread, so the GUI and camera threads can
  both use the controller safely.
- If the presenter ends the show (Esc), AirSlide notices within 1 s and returns
  to the home screen.

## PDF Integration

`PDFController` launches the viewer, finds its window, brings it to the front
and presses that viewer's keys. It never opens or changes the PDF itself.
When AirSlide launched the viewer (SumatraPDF) it closes it at the end. A
shared default viewer is left open, because it may hold your other documents.
The floating overlay is a no-activate window, so it never takes the keyboard
focus away from the viewer.

## Testing

```bash
pytest                                      # 138 unit / GUI tests, no hardware needed
python -m tools.make_test_files             # builds tests/assets/airslide_test.pptx + .pdf (8 slides)
set AIRSLIDE_INTEGRATION=1
pytest tests/test_powerpoint_integration.py # real PowerPoint slide show (~20 s on screen)
ruff check .                                # code style
```

| Test file | Covers |
| --- | --- |
| `test_camera.py` | open/close, errors, mirroring, FPS |
| `test_hand_detector.py` | landmarks, model loading |
| `test_finger_detector.py` | 5 open / fist / 3 fingers / tucked thumb / rotation / scale / noise |
| `test_swipe_detector.py` | next, previous, small, vertical, slow, fast, mirroring |
| `test_gesture_state.py` | states, open palm, cooldown (only the first command executes) |
| `test_gesture_engine.py` | camera → command pipeline, pause, camera loss, model errors |
| `test_presentation_manager.py` | file validation, controller selection, session states, errors |
| `test_settings.py` | validation, save/load |
| `test_debate.py` | debate timer, pause, last slide, slide counting, slide-times dialog |
| `test_time_limit.py` | time limit, over-time alerts at +2 / +3 / +5 min, pause |
| `test_photos.py` | photo files and order, every style (pixel checks), controller, setup dialog |
| `test_subtitles.py` | sentence splitting (English, Khmer, long), voice detection, pacing |
| `test_ui.py` | full GUI workflow offscreen, all error messages |
| `test_powerpoint_integration.py` | real PowerPoint: animations, previous, close |

The manual checklist for lighting, distance, users and the demo scenarios is in
[docs/TESTING.md](docs/TESTING.md).

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "Camera not found" | Connect a webcam, close Teams/Zoom/Camera, or change *Camera number* in Settings. |
| Low FPS | Better lighting helps most. Check `python main.py --camera-test`. |
| Accidental slide changes while talking | Turn on *Require all five fingers open*, raise *Minimum swipe distance*, or use ⏸ Pause gestures. |
| Five-finger mode: "Palm: not open" | Spread all fingers. Run `--hand-test` to see which finger is "bent", then lower its angle in Settings. |
| Swipes not recognised | Swipe wider, or lower *Minimum swipe distance*. Watch `--gesture-test`: *Distance* shows travel / required. |
| Fast swipes missed | Better lighting (the webcam uses a shorter exposure, so less blur), or raise *Fast swipe tolerance*. |
| Far away: hand not found | Face the camera with your upper body visible, so the pose model can find you and zoom. Check "Presenter: YES  Zoom …x" in the debug panel. |
| Someone else changes slides | Stand closest to the camera. If they are within your arm's reach in the image, lower `PRESENTER_REACH`. |
| Next and Previous are swapped | Toggle *Mirror camera image* in Settings. |
| "Microsoft PowerPoint was not found" | Install desktop PowerPoint. |
| PDF pages don't change | Install SumatraPDF, or set the right keys in `config.PDF_VIEWER_KEYS`. |
| Something else | See `logs/airslide.log`. |

## Limitations

- Windows only (PowerPoint COM automation and Windows window control).
- PDF control through the default viewer depends on that viewer's keyboard
  shortcuts. With PDFgear, PageDown did not change pages in testing, so
  SumatraPDF is recommended.
- One presenter. The presenter is the biggest person in the image, so someone
  standing closer to the camera than the presenter takes over when the presenter is out of view for more than 1.5 s.
- Needs reasonable lighting. MediaPipe accuracy drops in very dark rooms, and
  fast swipes blur more because the webcam uses longer exposures.
- Range: with a 720p webcam, hands are found up to about 4–5 m with the zoom
  (about 2 m without). Farther away the hand is only a few pixels wide.

## Future Improvements

- Distance-independent swipes (measure travel relative to palm size).
- Extra gestures (for example, hold an open palm to pause or show a black screen).
- Direct SumatraPDF control through its DDE interface instead of key presses.
- A pointer/laser mode that follows the index finger.
- Packaging as a single `.exe` (PyInstaller).
- A calibration wizard that tunes the thresholds for each presenter.

## Team Members

| Name | Role |
| --- | --- |
| *add name* | *add role* |
