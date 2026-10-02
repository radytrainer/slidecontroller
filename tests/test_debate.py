"""Debate mode: slide timer, slide counting and the slide-times dialog."""

import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.presentation.debate import DebatePlan, DebateTimer, count_slides, format_seconds, split_total


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


# -- plan and timer --------------------------------------------------------------------

def test_plan_uses_slide_time_or_default():
    plan = DebatePlan(60, {2: 90})
    assert plan.seconds_for(1) == 60
    assert plan.seconds_for(2) == 90


def test_split_total_adds_up_exactly():
    assert split_total(600, 7) == {1: 86, 2: 86, 3: 86, 4: 86, 5: 86, 6: 85, 7: 85}
    assert sum(split_total(600, 7).values()) == 600
    assert split_total(300, 5) == {n: 60 for n in range(1, 6)}
    assert split_total(3, 5) == {n: 1 for n in range(1, 6)}   # never 0 s


def test_plan_from_total():
    plan = DebatePlan.from_total(100, 3)
    assert [plan.seconds_for(n) for n in (1, 2, 3)] == [34, 33, 33]


def test_timer_counts_down_and_advances(clock):
    timer = DebateTimer(DebatePlan(30), clock)
    timer.start_slide(1)
    clock.now += 29.5
    assert timer.tick(1, 5) is False
    assert timer.remaining() == pytest.approx(0.5)
    clock.now += 0.5
    assert timer.tick(1, 5) is True     # time is up: move on
    assert timer.slide == 2
    assert timer.remaining() == 30      # the next slide's full time


def test_timer_restarts_when_presenter_changes_slide(clock):
    timer = DebateTimer(DebatePlan(30, {3: 45}), clock)
    timer.start_slide(1)
    clock.now += 20
    assert timer.tick(3, 5) is False    # presenter swiped ahead
    assert timer.slide == 3
    assert timer.remaining() == 45


def test_timer_stops_on_last_slide(clock):
    timer = DebateTimer(DebatePlan(10), clock)
    timer.start_slide(3)
    clock.now += 10
    assert timer.tick(3, 3) is False
    assert timer.finished
    clock.now += 100
    assert timer.tick(3, 3) is False
    assert timer.slide == 3


def test_timer_finished_on_end_of_show_screen(clock):
    timer = DebateTimer(DebatePlan(10), clock)
    timer.start_slide(3)
    assert timer.tick(4, 3) is False    # PowerPoint's black "end of slide show" screen
    assert timer.finished


def test_timer_without_known_total_keeps_advancing(clock):
    timer = DebateTimer(DebatePlan(10), clock)
    timer.start_slide(1)
    clock.now += 10
    assert timer.tick(1, None) is True
    assert timer.slide == 2


def test_pause_freezes_the_countdown(clock):
    timer = DebateTimer(DebatePlan(30), clock)
    timer.start_slide(1)
    clock.now += 10
    timer.pause()
    clock.now += 100
    assert timer.tick(1, 5) is False
    assert timer.remaining() == 20
    timer.resume()
    clock.now += 20
    assert timer.tick(1, 5) is True


def test_slide_change_while_paused_keeps_it_paused(clock):
    timer = DebateTimer(DebatePlan(30, {2: 50}), clock)
    timer.start_slide(1)
    timer.pause()
    timer.tick(2, 5)
    clock.now += 100
    assert timer.paused and timer.remaining() == 50


@pytest.mark.parametrize("seconds, text", [(0, "0:00"), (0.2, "0:01"), (59.1, "1:00"), (62, "1:02"), (600, "10:00")])
def test_format_seconds(seconds, text):
    assert format_seconds(seconds) == text


# -- slide counting ---------------------------------------------------------------------

def _slide_xml(hidden=False):
    show = ' show="0"' if hidden else ""
    return f'<?xml version="1.0"?><p:sld xmlns:p="x"{show}><p:cSld/></p:sld>'


def test_count_pptx_slides_skips_hidden(tmp_path):
    path = tmp_path / "talk.pptx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("ppt/presentation.xml", "<p:presentation/>")
        package.writestr("ppt/slides/slide1.xml", _slide_xml())
        package.writestr("ppt/slides/slide2.xml", _slide_xml(hidden=True))
        package.writestr("ppt/slides/slide3.xml", _slide_xml())
        package.writestr("ppt/slides/_rels/slide1.xml.rels", "<Relationships/>")
    assert count_slides(path) == 2


def test_count_pdf_pages(tmp_path):
    path = tmp_path / "handout.pdf"
    path.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /Pages /Count 3 >>\n"
                     + b"".join(b"%d 0 obj << /Type /Page /Parent 1 0 R >>\n" % n for n in (2, 3, 4)))
    assert count_slides(path) == 3


def test_count_unknown_is_none(tmp_path):
    broken = tmp_path / "broken.pptx"
    broken.write_bytes(b"PK\x03\x04 not really a zip")
    compressed = tmp_path / "compressed.pdf"
    compressed.write_bytes(b"%PDF-1.7\n<< /Type /ObjStm >> stream ... endstream")
    assert count_slides(broken) is None
    assert count_slides(compressed) is None
    assert count_slides(tmp_path / "missing.pdf") is None


# -- slide times dialog -----------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_dialog_known_slide_count(app):
    from ui.debate_dialog import SlideTimesDialog

    dialog = SlideTimesDialog(None, "talk.pptx", 3, 60, {2: 90})
    assert not dialog.count.isEnabled()          # read from the file
    assert dialog.times() == {1: 60, 2: 90, 3: 60}
    dialog.all_seconds.setValue(45)
    dialog.set_all()
    assert dialog.times() == {1: 45, 2: 45, 3: 45}


def test_dialog_total_time_divides_and_shows_sum(app):
    from ui.debate_dialog import SlideTimesDialog

    dialog = SlideTimesDialog(None, "talk.pptx", 4, 60, total_seconds=600)
    assert dialog.times() == {1: 150, 2: 150, 3: 150, 4: 150}
    assert dialog.sum_label.text() == "All slides: 10:00"
    dialog._editors[0].setValue(240)                 # slide 1 gets more time
    assert dialog.times()[1] == 240
    assert "total is 10:00" in dialog.sum_label.text()
    dialog.total.set_seconds(400)
    dialog.divide_equally()
    assert dialog.times() == {1: 100, 2: 100, 3: 100, 4: 100}


def test_dialog_total_time_unknown_count_redivides(app):
    from ui.debate_dialog import SlideTimesDialog

    dialog = SlideTimesDialog(None, "handout.pdf", None, 60, total_seconds=300)
    dialog.count.setValue(5)
    assert dialog.times() == {n: 60 for n in range(1, 6)}


def test_dialog_unknown_slide_count_keeps_values(app):
    from ui.debate_dialog import SlideTimesDialog

    dialog = SlideTimesDialog(None, "handout.pdf", None, 30)
    assert dialog.count.isEnabled()
    dialog.count.setValue(2)
    dialog._editors[1].setValue(120)
    dialog.count.setValue(4)
    assert dialog.times() == {1: 30, 2: 120, 3: 30, 4: 30}
