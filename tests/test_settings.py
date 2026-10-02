"""Settings: validation, save/load round trip, defaults."""

import json

import pytest

import config
from src.utils import settings


@pytest.fixture(autouse=True)
def restore_config():
    before = settings.current_values()
    yield
    settings.apply(before)


def test_every_setting_exists_in_config():
    for setting in settings.SETTINGS:
        assert hasattr(config, setting.key), setting.key
        assert isinstance(getattr(config, setting.key), setting.kind), setting.key


def test_apply_changes_config_and_reports_changes():
    changed = settings.apply({"MIN_SWIPE_DISTANCE": 200, "COOLDOWN_SECONDS": 1.5})
    assert set(changed) == {"MIN_SWIPE_DISTANCE", "COOLDOWN_SECONDS"}
    assert config.MIN_SWIPE_DISTANCE == 200 and config.COOLDOWN_SECONDS == 1.5
    assert settings.apply({"MIN_SWIPE_DISTANCE": 200}) == []  # unchanged


def test_values_are_clamped_to_range():
    settings.apply({"MIN_SWIPE_DISTANCE": 5000, "COOLDOWN_SECONDS": -3})
    assert config.MIN_SWIPE_DISTANCE == 600
    assert config.COOLDOWN_SECONDS == 0.2


def test_invalid_and_unknown_values_are_ignored():
    before = config.MIN_SWIPE_DISTANCE
    assert settings.apply({"MIN_SWIPE_DISTANCE": "lots", "NOT_A_SETTING": 1, "PDF_VIEWER": "notepad"}) == []
    assert config.MIN_SWIPE_DISTANCE == before
    assert config.PDF_VIEWER in ("auto", "sumatra", "default")


def test_bool_from_text():
    settings.apply({"MIRROR_CAMERA": "false"})
    assert config.MIRROR_CAMERA is False


def test_save_stores_only_changes_and_load_restores_them(tmp_path):
    path = tmp_path / "settings.json"
    settings.apply({"MIN_SWIPE_DISTANCE": 220, "DEBUG": False})
    settings.save(path=path)
    assert json.loads(path.read_text()) == {"MIN_SWIPE_DISTANCE": 220, "DEBUG": False}

    settings.reset_to_defaults()
    assert config.MIN_SWIPE_DISTANCE == settings.DEFAULTS["MIN_SWIPE_DISTANCE"]
    assert set(settings.load(path)) == {"MIN_SWIPE_DISTANCE", "DEBUG"}
    assert config.MIN_SWIPE_DISTANCE == 220


def test_missing_or_corrupt_file_is_harmless(tmp_path):
    assert settings.load(tmp_path / "missing.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert settings.load(bad) == []


def test_new_thresholds_reach_the_swipe_detector():
    from src.gesture.swipe_detector import SwipeDetector

    settings.apply({"MIN_SWIPE_DISTANCE": 300})
    assert SwipeDetector().min_distance == 300
