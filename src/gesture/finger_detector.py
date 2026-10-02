"""
Finger state and open-palm detection.

Each finger is judged by the **angles at its joints**, not by comparing
Y coordinates. A straight finger has angles close to 180 degrees; a curled
finger has much smaller ones. Angles do not change when the hand is rotated,
tilted or moved, so the result is robust to how the presenter holds the hand.

Rules (thresholds in config.py):

* Index, middle, ring, pinky are EXTENDED when
    - the knuckle angle   (wrist - MCP - PIP) >= FINGER_MCP_ANGLE
    - the middle angle    (MCP - PIP - DIP)   >= FINGER_STRAIGHT_ANGLE
    - the end angle       (PIP - DIP - TIP)   >= FINGER_STRAIGHT_ANGLE
    - and the tip is farther from the wrist than the PIP joint
      (ratio >= FINGER_EXTENSION_RATIO)
* The thumb is EXTENDED when
    - its MCP and IP angles are >= THUMB_STRAIGHT_ANGLE
    - and the tip is spread away from the index knuckle
      (distance >= THUMB_SPREAD_RATIO x palm size), so a straight thumb
      tucked across the palm does not count
* OPEN PALM = all five fingers extended.
"""

from dataclasses import dataclass

import numpy as np

import config
from src.hand.hand_detector import HandLandmark as L
from src.hand.hand_detector import landmark_array

FINGER_NAMES = ("thumb", "index", "middle", "ring", "pinky")

# (base, joint 1, joint 2, tip) for each finger
FINGER_JOINTS = {
    "thumb": (L.THUMB_CMC, L.THUMB_MCP, L.THUMB_IP, L.THUMB_TIP),
    "index": (L.INDEX_MCP, L.INDEX_PIP, L.INDEX_DIP, L.INDEX_TIP),
    "middle": (L.MIDDLE_MCP, L.MIDDLE_PIP, L.MIDDLE_DIP, L.MIDDLE_TIP),
    "ring": (L.RING_MCP, L.RING_PIP, L.RING_DIP, L.RING_TIP),
    "pinky": (L.PINKY_MCP, L.PINKY_PIP, L.PINKY_DIP, L.PINKY_TIP),
}


@dataclass(frozen=True)
class FingerState:
    name: str
    extended: bool
    angles: tuple[float, ...]  # joint angles in degrees, base -> tip
    reach: float               # thumb: spread / palm size; others: tip / PIP distance from wrist


@dataclass(frozen=True)
class HandPose:
    fingers: tuple[FingerState, ...]  # in FINGER_NAMES order
    palm_size: float

    @property
    def count(self) -> int:
        """Number of extended fingers (0-5)."""
        return sum(f.extended for f in self.fingers)

    @property
    def is_open_palm(self) -> bool:
        return self.count == len(FINGER_NAMES)

    def finger(self, name: str) -> FingerState:
        return self.fingers[FINGER_NAMES.index(name)]


def joint_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle ABC in degrees (180 = A, B, C in a straight line)."""
    ba, bc = a - b, c - b
    norms = np.linalg.norm(ba) * np.linalg.norm(bc)
    if norms == 0:
        return 0.0
    cosine = np.clip(np.dot(ba, bc) / norms, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosine)))


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def _thumb_state(points: np.ndarray, palm_size: float) -> FingerState:
    cmc, mcp, ip, tip = (points[i] for i in FINGER_JOINTS["thumb"])
    angles = (joint_angle(cmc, mcp, ip), joint_angle(mcp, ip, tip))
    spread = _distance(tip, points[L.INDEX_MCP]) / palm_size if palm_size else 0.0
    extended = all(a >= config.THUMB_STRAIGHT_ANGLE for a in angles) and spread >= config.THUMB_SPREAD_RATIO
    return FingerState("thumb", extended, angles, spread)


def _finger_state(name: str, points: np.ndarray) -> FingerState:
    wrist = points[L.WRIST]
    mcp, pip, dip, tip = (points[i] for i in FINGER_JOINTS[name])
    angles = (joint_angle(wrist, mcp, pip), joint_angle(mcp, pip, dip), joint_angle(pip, dip, tip))
    pip_dist = _distance(wrist, pip)
    reach = _distance(wrist, tip) / pip_dist if pip_dist else 0.0
    extended = (
        angles[0] >= config.FINGER_MCP_ANGLE
        and angles[1] >= config.FINGER_STRAIGHT_ANGLE
        and angles[2] >= config.FINGER_STRAIGHT_ANGLE
        and reach >= config.FINGER_EXTENSION_RATIO
    )
    return FingerState(name, extended, angles, reach)


def analyze_hand(landmarks) -> HandPose:
    """Full per-finger analysis (used by is_open_palm and the debug view)."""
    points = landmark_array(landmarks)
    palm_size = _distance(points[L.WRIST], points[L.MIDDLE_MCP])
    fingers = (_thumb_state(points, palm_size),) + tuple(
        _finger_state(name, points) for name in FINGER_NAMES[1:]
    )
    return HandPose(fingers, palm_size)


def count_extended_fingers(landmarks) -> int:
    return analyze_hand(landmarks).count


def is_open_palm(landmarks) -> bool:
    """True only when all five fingers are extended."""
    return analyze_hand(landmarks).is_open_palm
