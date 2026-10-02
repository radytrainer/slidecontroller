"""Central logging setup for AirSlide."""

import logging
import sys

import config

_configured = False


def setup_logging() -> None:
    """Configure the root logger once (console + optional log file)."""
    global _configured
    if _configured:
        return

    handlers: list[logging.Handler] = []
    if sys.stdout is not None:  # None in the windowed .exe without a console
        handlers.append(logging.StreamHandler(sys.stdout))
    if config.LOG_TO_FILE:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.FileHandler(config.LOG_DIR / "airslide.log", encoding="utf-8")
        )

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger, configuring logging on first use."""
    setup_logging()
    return logging.getLogger(name)
