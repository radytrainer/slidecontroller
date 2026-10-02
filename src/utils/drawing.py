"""Small OpenCV drawing helpers for the debug previews."""

import cv2
import numpy as np

GREEN = (80, 220, 80)
WHITE = (230, 230, 230)
YELLOW = (40, 210, 250)
RED = (60, 60, 240)


def draw_text(frame: np.ndarray, text: str, row: int, color=GREEN, x: int = 16) -> None:
    """Draw outlined text on line ``row`` (0 = top) so it is readable on any background."""
    y = 32 + row * 30
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)
