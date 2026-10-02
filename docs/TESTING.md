# AirSlide – Manual Test Checklist

Automated tests cover the logic (`pytest`). These checks need a real person,
camera and room. Record the result (✅ / ❌ + note) for each row.

**Tools:** `python main.py --gesture-test` shows the debug panel and prints each
gesture, so no presentation is needed. `python main.py` is the full app.

## 1. Real-world gesture tests (spec §38)

Do 10 swipes each way per row. Write down how many were recognised correctly
and how many were wrong or missed.

| Condition | NEXT ok /10 | PREVIOUS ok /10 | False triggers | Notes |
| --- | --- | --- | --- | --- |
| Bright room | | | | |
| Low light | | | | |
| Busy background | | | | |
| Plain background | | | | |
| User 2 | | | | |
| User 3 | | | | |
| Near camera (~0.5 m) | | | | |
| Far from camera (~2 m) | | | | |
| Far from camera (~3 m, check "Zoom" in debug panel) | | | | |
| Far from camera (~4–5 m) | | | | |
| Standing left of frame | | | | |
| Standing centre | | | | |
| Standing right of frame | | | | |
| Fast swipe | | | | |
| Very fast swipe (hand blurred in preview) | | | | |
| Slow swipe (should NOT trigger if > 1 s) | | | | |
| Small swipe (should NOT trigger) | | | | |
| Large swipe | | | | |
| Diagonal (mostly sideways → triggers) | | | | |
| Vertical movement (should NOT trigger) | | | | |
| Closed hand swipe (triggers by default; should NOT in five-finger mode) | | | | |
| Partially open hand (triggers by default; should NOT in five-finger mode) | | | | |
| Talking with hands for 1 min (count accidental triggers) | | | | |
| Presenter's two hands (one is chosen, swipes still work) | | | | |
| Someone else waving beside the presenter (should NOT trigger) | | | | |
| Only someone else's hand in view, presenter visible (should NOT trigger) | | | | |

**Direction check (spec §29):** with the default mirrored preview, moving your
hand towards **your left** must show `Direction: RIGHT -> LEFT` and `NEXT >>`.
If it is reversed, toggle *Mirror camera image* in Settings.

## 2. PowerPoint tests (spec §39)

```bash
python -m tools.make_test_files      # creates tests/assets/airslide_test.pptx
python main.py                       # open it via "Open Presentation"
```

| Slide | Content | Expected with 🖐️ NEXT | Result |
| --- | --- | --- | --- |
| 1 | Normal text | Goes to slide 2 | |
| 2 | 1 text animation | 1st NEXT plays the fly-in, 2nd goes to slide 3 | |
| 3 | 3 animations | 3 NEXTs play them one by one, 4th goes to slide 4 | |
| 4 | Fade transition | Slide fades in (1.5 s) | |
| 5 | Image | Image shown sharp, as designed | |
| 6 | Video | Video frame visible; plays when clicked / per its settings | |
| 7 | Audio | Speaker icon; tone plays when clicked | |
| 8 | Fonts / colours | Georgia, Consolas, Comic Sans, Times; dark blue background | |
| – | PREVIOUS on slide 4 | Back to slide 3 | |
| – | Esc in PowerPoint | AirSlide returns to its home screen within ~1 s | |
| – | ■ Stop presentation | Slide show ends, PowerPoint closes (if AirSlide started it) | |
| – | File unchanged | Modified date of the .pptx unchanged afterwards | |

Automated version: `set AIRSLIDE_INTEGRATION=1` then `pytest tests/test_powerpoint_integration.py -v`.

## 3. PDF tests (spec §40)

| Test | Expected | Result |
| --- | --- | --- |
| Multi-page PDF (`tests/assets/airslide_test.pdf`) | NEXT/PREVIOUS change exactly one page | |
| PDF with images | Rendered by the viewer unchanged | |
| Different fonts | Rendered unchanged | |
| Landscape pages | Fit the screen | |
| Portrait pages | Fit the screen | |
| Large PDF (100+ pages) | Opens; navigation stays responsive | |
| Full-screen mode | SumatraPDF starts in presentation mode | |
| File unchanged | Modified date and size unchanged | |

## 4. Error handling (spec §34)

| Situation | Expected message | Result |
| --- | --- | --- |
| Select a `.docx` | "Only PPTX and PDF files are supported." | |
| Rename a `.txt` to `.pptx` and open it | "Unable to open presentation. Please check the file." | |
| Unplug the webcam, then open a file | "Camera not found. Please connect a webcam." | |
| Unplug the webcam while presenting | Overlay shows CAMERA ERROR; slides still work with the keyboard | |
| No hand in view | "Show your hand to the camera." | |
| Another person's hand in view | Ignored (grey in the debug preview) | |
| PowerPoint not installed (test on another PC) | "Microsoft PowerPoint was not found. …" | |

## 5. Final demonstration (spec §47)

| Demo | Action | Expected | Result |
| --- | --- | --- | --- |
| 1 | Open Presentation → .pptx | PowerPoint slide show, original design and animations | |
| 2 | 🖐️ right → left | NEXT (animation or slide) | |
| 3 | 🖐️ left → right | PREVIOUS | |
| 4 | 🖐️ up / down | No command | |
| 5 | ✊ swipe | NEXT by default; no command in five-finger mode | |
| 6 | 🖐️ small movement | No command | |
