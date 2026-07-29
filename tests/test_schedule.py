from __future__ import annotations

import datetime as dt

from coursemd.core.models.course_event import CourseEvent
from coursemd.core.schedule import Schedule, ScheduleEntry
from coursemd.integrations.mkdocs.schedule import render_schedule


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
