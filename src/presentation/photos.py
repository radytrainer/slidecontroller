"""
Photo files for the photo slideshow: which files are photos, and their order.

Files are checked by extension AND by their first bytes (like .pptx / .pdf),
so a renamed document is not shown as a broken photo.
"""

import random
import re
from pathlib import Path

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}
_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a")

ORDERS = {
    "name": "By name",
    "date": "By date (oldest first)",
    "shuffle": "Shuffle",
    "selected": "As selected",
}


def is_photo_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in PHOTO_EXTENSIONS


def is_valid_photo(path: str | Path) -> bool:
    path = Path(path)
    if not is_photo_path(path) or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError:
        return False
    return head.startswith(_SIGNATURES)


def valid_photos(paths) -> tuple[list[Path], list[Path]]:
    """(photos that can be shown, files that were skipped). Duplicates are shown once."""
    valid, skipped, seen = [], [], set()
    for path in paths:
        path = Path(path).resolve()
        if path in seen:
            continue
        seen.add(path)
        (valid if is_valid_photo(path) else skipped).append(path)
    return valid, skipped


def _natural_key(path: Path):
    """'IMG_2.jpg' before 'IMG_10.jpg'."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.name.lower())]


def order_photos(paths: list[Path], order: str, seed: int | None = None) -> list[Path]:
    if order == "name":
        return sorted(paths, key=_natural_key)
    if order == "date":
        return sorted(paths, key=lambda p: (p.stat().st_mtime, _natural_key(p)))
    if order == "shuffle":
        shuffled = list(paths)
        random.Random(seed).shuffle(shuffled)
        return shuffled
    return list(paths)
