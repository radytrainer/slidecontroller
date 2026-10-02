"""
Builds synthetic 21-landmark hands for tests.

The hand is drawn upright (fingers pointing up, image Y grows downward) with
the wrist at the origin, then rotated / scaled / mirrored / moved. Each
finger is a chain of segments; a joint "bend" turns the chain, so a straight
finger has 0-degree bends (180-degree joint angles) and a curled one large bends.
"""

import math

import numpy as np

FINGERS = ("thumb", "index", "middle", "ring", "pinky")

# Where each finger chain starts (thumb CMC, other fingers' MCP), wrist = (0, 0).
BASES = {
    "thumb": (-30.0, -30.0),
    "index": (-35.0, -100.0),
    "middle": (-10.0, -105.0),
    "ring": (15.0, -100.0),
    "pinky": (38.0, -90.0),
}
SEGMENTS = {
    "thumb": (35.0, 30.0, 25.0),
    "index": (40.0, 25.0, 20.0),
    "middle": (45.0, 28.0, 22.0),
    "ring": (42.0, 26.0, 20.0),
    "pinky": (32.0, 20.0, 18.0),
}
FIRST_INDEX = {"thumb": 1, "index": 5, "middle": 9, "ring": 13, "pinky": 17}

# Bends (degrees) applied at each joint of the chain.
STRAIGHT = (0.0, 0.0, 0.0)
RELAXED = (10.0, 12.0, 6.0)        # a natural, slightly soft open finger
CURLED = (95.0, 100.0, 60.0)       # fist
THUMB_OPEN_DIRECTION = -50.0       # degrees from "up", negative = toward the left
THUMB_TUCKED = (-20.0, (55.0, 55.0))  # start direction, bends at MCP and IP -> across the palm


def _unit(angle_deg: float) -> np.ndarray:
    """Direction for an angle measured clockwise from 'up' in image coordinates."""
    rad = math.radians(angle_deg)
    return np.array([math.sin(rad), -math.cos(rad)])


def _angle_of(vector) -> float:
    return math.degrees(math.atan2(vector[0], -vector[1]))


def make_hand(
    extended=FINGERS,
    relaxed: bool = False,
    rotation_deg: float = 0.0,
    scale: float = 1.0,
    offset=(640.0, 500.0),
    mirror: bool = False,
    noise: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """Return a (21, 3) landmark array. ``extended`` names the open fingers."""
    points = np.zeros((21, 2))

    for name in FINGERS:
        base = np.array(BASES[name])
        first = FIRST_INDEX[name]
        points[first] = base
        is_open = name in extended

        if name == "thumb":
            # Thumb chain: CMC -> MCP -> IP -> TIP, bends at MCP and IP.
            if is_open:
                direction, bends = THUMB_OPEN_DIRECTION, (0.0, 0.0)
                if relaxed:
                    bends = (8.0, 10.0)
            else:
                direction, bends = THUMB_TUCKED
            turns = (0.0, *bends)
        else:
            # Finger chain: MCP -> PIP -> DIP -> TIP, starts in the wrist->MCP direction.
            direction = _angle_of(base)
            turns = (RELAXED if relaxed else STRAIGHT) if is_open else CURLED

        current = base
        for step, (length, turn) in enumerate(zip(SEGMENTS[name], turns, strict=True), start=1):
            direction += turn
            current = current + _unit(direction) * length
            points[first + step] = current

    if mirror:
        points[:, 0] *= -1
    rad = math.radians(rotation_deg)
    rotation = np.array([[math.cos(rad), -math.sin(rad)], [math.sin(rad), math.cos(rad)]])
    points = points @ rotation.T * scale + np.asarray(offset)
    if noise:
        points += np.random.default_rng(seed).normal(0.0, noise, points.shape)

    return np.column_stack([points, np.zeros(21)])
