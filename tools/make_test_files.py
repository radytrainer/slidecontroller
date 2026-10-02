"""
Generate the test presentation (spec section 39) with PowerPoint itself.

    python -m tools.make_test_files

Creates tests/assets/:

    airslide_test.pptx   8 slides
        1 normal text
        2 one text animation            (1 click)
        3 three animations              (3 clicks)
        4 slide transition (fade)
        5 image
        6 video
        7 audio
        8 different fonts / colours
    airslide_test.pdf    the same slides exported as PDF (8 pages)
    media/               the generated image, video and audio files

Requires Microsoft PowerPoint. PowerPoint is started hidden and closed again
if it was not already running.
"""

import math
import struct
import sys
import wave
from pathlib import Path

import cv2
import numpy as np
import pythoncom
import pywintypes
import win32com.client

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "tests" / "assets"
MEDIA_DIR = OUT_DIR / "media"
PPTX_PATH = OUT_DIR / "airslide_test.pptx"
PDF_PATH = OUT_DIR / "airslide_test.pdf"

# Office constants
PP_LAYOUT_TITLE, PP_LAYOUT_TEXT, PP_LAYOUT_TITLE_ONLY = 1, 2, 11
ANIM_FLY, ANIM_FADE, ANIM_APPEAR = 2, 10, 1
TRIGGER_ON_CLICK = 1
PP_EFFECT_FADE = 1793
PP_SAVE_AS_PPTX, PP_SAVE_AS_PDF = 24, 32
MSO_TRUE, MSO_FALSE = -1, 0


def rgb(r: int, g: int, b: int) -> int:
    return r + g * 256 + b * 65536


# -- media ------------------------------------------------------------------------

def make_image(path: Path) -> Path:
    height, width = 540, 960
    x = np.linspace(0, 1, width)
    image = np.zeros((height, width, 3), np.uint8)
    image[..., 0] = (255 * x).astype(np.uint8)
    image[..., 1] = 120
    image[..., 2] = (255 * (1 - x)).astype(np.uint8)
    cv2.circle(image, (480, 270), 150, (255, 255, 255), 12, cv2.LINE_AA)
    cv2.putText(image, "AirSlide test image", (230, 290), cv2.FONT_HERSHEY_DUPLEX, 1.6, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.imwrite(str(path), image)
    return path


def make_video(path: Path, seconds: int = 4, fps: int = 25) -> Path | None:
    size = (640, 360)
    writer = None
    for api, fourcc in ((cv2.CAP_MSMF, "H264"), (cv2.CAP_ANY, "mp4v")):
        writer = cv2.VideoWriter(str(path), api, cv2.VideoWriter_fourcc(*fourcc), fps, size)
        if writer.isOpened():
            break
    if writer is None or not writer.isOpened():
        return None
    for i in range(seconds * fps):
        frame = np.full((size[1], size[0], 3), 40, np.uint8)
        x = int((i / (seconds * fps)) * (size[0] - 80)) + 40
        cv2.circle(frame, (x, 180), 40, (80, 220, 80), -1, cv2.LINE_AA)
        cv2.putText(frame, f"AirSlide video {i // fps + 1}s", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    return path


def make_audio(path: Path, seconds: float = 2.0, rate: int = 44100) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * n / rate)))
            for n in range(int(seconds * rate))
        )
        wav.writeframes(frames)
    return path


# -- slides -----------------------------------------------------------------------

def add_slide(presentation, layout: int, title: str):
    slide = presentation.Slides.Add(presentation.Slides.Count + 1, layout)
    slide.Shapes.Title.TextFrame.TextRange.Text = title
    return slide


def add_textbox(slide, text: str, left: float, top: float, width: float = 700, height: float = 50, size: int = 28):
    box = slide.Shapes.AddTextbox(1, left, top, width, height)
    box.TextFrame.TextRange.Text = text
    box.TextFrame.TextRange.Font.Size = size
    return box


def build(presentation, media: dict) -> None:
    # 1 - normal text
    slide = add_slide(presentation, PP_LAYOUT_TITLE, "Slide 1 - Normal text")
    slide.Shapes(2).TextFrame.TextRange.Text = "AirSlide test presentation. Swipe right -> left for NEXT."

    # 2 - one text animation
    slide = add_slide(presentation, PP_LAYOUT_TITLE_ONLY, "Slide 2 - Text animation (1 click)")
    box = add_textbox(slide, "I fly in on the first NEXT.", 80, 200)
    slide.TimeLine.MainSequence.AddEffect(box, ANIM_FLY, 0, TRIGGER_ON_CLICK)

    # 3 - multiple animations
    slide = add_slide(presentation, PP_LAYOUT_TITLE_ONLY, "Slide 3 - Multiple animations (3 clicks)")
    for i, (text, effect) in enumerate((("First (appear)", ANIM_APPEAR),
                                        ("Second (fade)", ANIM_FADE),
                                        ("Third (fly in)", ANIM_FLY))):
        box = add_textbox(slide, text, 80, 180 + i * 80)
        slide.TimeLine.MainSequence.AddEffect(box, effect, 0, TRIGGER_ON_CLICK)

    # 4 - slide transition
    slide = add_slide(presentation, PP_LAYOUT_TITLE_ONLY, "Slide 4 - Fade transition")
    add_textbox(slide, "This slide faded in (1.5 s transition).", 80, 200)
    slide.SlideShowTransition.EntryEffect = PP_EFFECT_FADE
    slide.SlideShowTransition.Duration = 1.5

    # 5 - image
    slide = add_slide(presentation, PP_LAYOUT_TITLE_ONLY, "Slide 5 - Image")
    slide.Shapes.AddPicture(str(media["image"]), MSO_FALSE, MSO_TRUE, 160, 130, 640, 360)

    # 6 - video
    slide = add_slide(presentation, PP_LAYOUT_TITLE_ONLY, "Slide 6 - Video")
    if media.get("video"):
        try:
            slide.Shapes.AddMediaObject2(str(media["video"]), MSO_FALSE, MSO_TRUE, 160, 130, 640, 360)
        except pywintypes.com_error as exc:
            add_textbox(slide, f"Video could not be embedded: {exc.excepinfo[2] if exc.excepinfo else exc}", 80, 200)
    else:
        add_textbox(slide, "No video encoder available - insert a video manually.", 80, 200)

    # 7 - audio
    slide = add_slide(presentation, PP_LAYOUT_TITLE_ONLY, "Slide 7 - Audio")
    add_textbox(slide, "Click the speaker icon to play a 440 Hz tone.", 80, 200)
    slide.Shapes.AddMediaObject2(str(media["audio"]), MSO_FALSE, MSO_TRUE, 440, 300, 64, 64)

    # 8 - different fonts / theme colours
    slide = add_slide(presentation, PP_LAYOUT_TITLE_ONLY, "Slide 8 - Different fonts and colours")
    slide.FollowMasterBackground = MSO_FALSE
    slide.Background.Fill.ForeColor.RGB = rgb(24, 32, 64)
    title = slide.Shapes.Title.TextFrame.TextRange
    title.Font.Name, title.Font.Color.RGB = "Georgia", rgb(255, 210, 90)
    for i, (font, color) in enumerate((("Consolas", rgb(120, 230, 160)),
                                       ("Comic Sans MS", rgb(255, 150, 150)),
                                       ("Times New Roman", rgb(200, 200, 255)))):
        box = add_textbox(slide, f"This line uses {font}", 80, 180 + i * 80)
        box.TextFrame.TextRange.Font.Name = font
        box.TextFrame.TextRange.Font.Color.RGB = color


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    media = {
        "image": make_image(MEDIA_DIR / "test_image.png"),
        "video": make_video(MEDIA_DIR / "test_video.mp4"),
        "audio": make_audio(MEDIA_DIR / "test_audio.wav"),
    }
    print(f"media: {', '.join(f'{k}={v.name if v else None}' for k, v in media.items())}")

    pythoncom.CoInitialize()
    try:
        try:
            win32com.client.GetActiveObject("PowerPoint.Application")
            was_running = True
        except pywintypes.com_error:
            was_running = False
        app = win32com.client.Dispatch("PowerPoint.Application")
        presentation = app.Presentations.Add(MSO_FALSE)  # no window
        try:
            build(presentation, media)
            presentation.SaveAs(str(PPTX_PATH), PP_SAVE_AS_PPTX)
            presentation.SaveAs(str(PDF_PATH), PP_SAVE_AS_PDF)
            print(f"created {PPTX_PATH.relative_to(ROOT)} ({presentation.Slides.Count} slides)")
            print(f"created {PDF_PATH.relative_to(ROOT)}")
        finally:
            presentation.Saved = MSO_TRUE
            presentation.Close()
            if not was_running and app.Presentations.Count == 0:
                app.Quit()
    finally:
        pythoncom.CoUninitialize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
