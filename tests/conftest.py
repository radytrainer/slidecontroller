"""Make the project root importable (``import config``, ``from src...``) in tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
