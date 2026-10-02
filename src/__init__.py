"""AirSlide core package."""

import os
import sys

# OpenCV reads this when cv2 is first imported, so it must be set before any
# module imports cv2. Skipping MSMF hardware-transform enumeration cuts the
# webcam open time from ~7-11 s to under 1 s.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

# In the packaged .exe, PyInstaller points matplotlib (imported by MediaPipe)
# at a new temporary cache on every start, which costs ~2 s rebuilding its
# font list. Keep that cache in AirSlide's own folder instead.
if getattr(sys, "frozen", False):
    os.environ["MPLCONFIGDIR"] = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AirSlide", "matplotlib"
    )
