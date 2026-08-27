from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING

from coursemd.core.models.assignment import Assignment
from coursemd.core.models.course_event import CourseEvent
from coursemd.core.schedule import Schedule, ScheduleEntry
from coursemd.integrations.mkdocs.schedule import render_schedule

if TYPE_CHECKING:
    import pytest


def _entry(date: dt.date, events: list[CourseEvent] | None = None) -> ScheduleEntry:
    return ScheduleEntry(
        date=date,
        events=events or [],
        break_=None,
        assignment_released=None,
        assignment_due=None,
        quiz_released=None,
        quiz_due=None,
    )


def test_no_recitation_column() -> None:
    lecture = CourseEvent(kind="lecture", date=dt.date(2026, 1, 12), title="Intro")
    schedule = Schedule(entries=[_entry(dt.date(2026, 1, 12), [lecture])])

    rendered = render_schedule(schedule)

    assert "<th>Recitation</th>" not in rendered
    assert 'class="recitation"' not in rendered


def test_recitation_renders_inline_on_its_own_day() -> None:
    recitation = CourseEvent(
        kind="recitation",
        date=dt.date(2026, 1, 14),
        title="Understand NodeBB",
        link="/recitations/reci1-nodebb/",
    )
    days = [dt.date(2026, 1, 12) + dt.timedelta(days=i) for i in range(5)]
    entries = [_entry(d, [recitation] if d == recitation.date else []) for d in days]
    schedule = Schedule(entries=entries)

    rendered = render_schedule(schedule)

    assert "<th>Recitation</th>" not in rendered
    assert 'class="recitation"' not in rendered
    assert rendered.count(">Recitation: Understand NodeBB<") == 1
    assert 'href="/recitations/reci1-nodebb/"' in rendered


def test_assignment_handout_links_to_assignment_page() -> None:
    assignment = Assignment(
        source_file=Path("assignments/P1/index.md"),
        title="Project 1",
        release_date=dt.date(2026, 1, 12),
        due_date=dt.date(2026, 1, 16),
        link="/assignments/P1/",
    )
    entry = ScheduleEntry(
        date=dt.date(2026, 1, 12),
        events=[],
        break_=None,
        assignment_released=assignment,
        assignment_due=None,
        quiz_released=None,
        quiz_due=None,
    )
    schedule = Schedule(entries=[entry])

    rendered = render_schedule(schedule)

    assert 'href="/assignments/P1/"' in rendered
    assert 'href="index"' not in rendered


def test_future_exam_stays_visible_while_future_lectures_are_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-08-27")

    past_lecture = CourseEvent(kind="lecture", date=dt.date(2026, 8, 25), title="Intro")
    teaser_lecture = CourseEvent(
        kind="lecture", date=dt.date(2026, 9, 1), title="Case Study 737MAX"
    )
    hidden_lecture = CourseEvent(
        kind="lecture", date=dt.date(2026, 9, 3), title="AI Usage"
    )
    midterm = CourseEvent(kind="midterm", date=dt.date(2026, 10, 8), title="Midterm 1")

    schedule = Schedule.build(
        earliest_date=dt.date(2026, 8, 25),
        latest_date=dt.date(2026, 10, 9),
        events=[past_lecture, teaser_lecture, hidden_lecture, midterm],
        breaks=[],
        assignments=[],
        quizzes=[],
    )

    rendered = render_schedule(schedule)

    assert "Midterm 1" in rendered
    assert "Intro" in rendered
    # The lecture past the "next upcoming" teaser is still hidden...
    assert "AI Usage" not in rendered
    # ...but the future midterm's date is shown anyway.
    assert "label-red" in rendered
