"""
PowerPoint integration test - opens a REAL slide show on screen.

Skipped unless enabled, because it takes over the display for ~15 s:

    python -m tools.make_test_files          # once, creates tests/assets/
    set AIRSLIDE_INTEGRATION=1
    pytest tests/test_powerpoint_integration.py -v

Verifies spec section 16: NEXT plays every animation step before moving on,
exactly like PowerPoint's own arrow key.
"""

import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AIRSLIDE_INTEGRATION") != "1", reason="set AIRSLIDE_INTEGRATION=1 to run"
)

PPTX = Path(__file__).parent / "assets" / "airslide_test.pptx"
STEP_PAUSE = 0.6  # let animations/transitions play so the run can be watched


@pytest.fixture
def controller():
    if not PPTX.exists():
        pytest.skip("run: python -m tools.make_test_files")
    from src.presentation.powerpoint_controller import PowerPointController, is_powerpoint_installed

    if not is_powerpoint_installed():
        pytest.skip("PowerPoint not installed")
    ctrl = PowerPointController()
    ctrl.open(PPTX)
    yield ctrl
    ctrl.close()


def step(ctrl, action):
    assert getattr(ctrl, action)() is True
    time.sleep(STEP_PAUSE)
    # PowerPoint reports position 0 while a slide transition is still playing.
    deadline = time.monotonic() + 5
    while (ctrl.position() or (0,))[0] == 0 and time.monotonic() < deadline:
        time.sleep(0.2)
    return ctrl.position()[0], ctrl.click_position()[0]


def test_next_respects_animations_and_previous_goes_back(controller):
    controller.start()
    time.sleep(1.0)
    assert controller.is_running
    assert controller.position() == (1, 8)

    # (slide, animation clicks done) after each NEXT
    expected = [
        (2, 0),  # slide 2, text not yet shown
        (2, 1),  # its animation
        (3, 0),  # slide 3
        (3, 1), (3, 2), (3, 3),  # three animations, one per NEXT
        (4, 0),  # fade transition
        (5, 0),
    ]
    for want in expected:
        assert step(controller, "next_slide") == want

    assert step(controller, "previous_slide")[0] == 4
    assert step(controller, "previous_slide")[0] == 3


def test_close_ends_show_and_navigation_then_fails(controller):
    controller.start()
    time.sleep(1.0)
    controller.close()
    assert not controller.is_running
    assert controller.next_slide() is False
