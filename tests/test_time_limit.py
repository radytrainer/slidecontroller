"""Time limit for a normal presentation: countdown, over-time alerts, automatic end."""

import pytest

from src.presentation.time_limit import TimeLimit, alert_message, format_duration


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


def test_countdown_then_overtime(clock):
    limit = TimeLimit(1200, clock=clock)
    limit.start()
    clock.now += 1000
    assert limit.remaining() == 200 and limit.overtime() == 0
    clock.now += 230
    assert limit.remaining() == -30 and limit.overtime() == 30


def test_alerts_fire_once_at_2_3_and_5_minutes_over(clock):
    limit = TimeLimit(1200, warnings=(120, 180), stop_after=300, clock=clock)
    limit.start()
    clock.now += 1200
    assert limit.tick() == []                       # time is up: no alert yet
    clock.now += 119
    assert limit.tick() == []
    clock.now += 1
    first = limit.tick()
    assert [(a.number, a.overtime, a.stop) for a in first] == [(1, 120, False)]
    assert limit.tick() == []                       # only once
    clock.now += 60
    assert [(a.number, a.stop) for a in limit.tick()] == [(2, False)]
    clock.now += 120
    last = limit.tick()
    assert [(a.number, a.overtime, a.stop, a.count) for a in last] == [(3, 300, True, 3)]
    clock.now += 600
    assert limit.tick() == []


def test_late_tick_returns_every_missed_alert_in_order(clock):
    limit = TimeLimit(60, clock=clock)
    limit.start()
    clock.now += 60 + 400
    assert [a.number for a in limit.tick()] == [1, 2, 3]


def test_pause_does_not_count(clock):
    limit = TimeLimit(600, clock=clock)
    limit.start()
    clock.now += 100
    limit.pause()
    clock.now += 1000
    assert limit.remaining() == 500
    assert limit.tick() == []
    limit.resume()
    clock.now += 50
    assert limit.remaining() == 450


def test_stop_disabled_only_warns(clock):
    limit = TimeLimit(60, warnings=(120, 180), stop_after=0, clock=clock)
    assert [a.stop for a in limit.alerts] == [False, False]


def test_warnings_after_stop_or_zero_are_dropped(clock):
    limit = TimeLimit(60, warnings=(0, 400), stop_after=300, clock=clock)
    assert [(a.overtime, a.stop) for a in limit.alerts] == [(300, True)]


def test_messages():
    limit = TimeLimit(1200)
    first, second, stop = limit.alerts
    assert alert_message(first, 300) == ("⚠  2 min over time  (1/3)\n"
                                         "Please finish. The presentation ends at 5 min over.")
    assert alert_message(second, 300).startswith("⚠  3 min over time  (2/3)")
    assert alert_message(stop, 300) == "⏹  5 min over time\nThe presentation has ended."
    assert format_duration(90) == "1:30 min"
