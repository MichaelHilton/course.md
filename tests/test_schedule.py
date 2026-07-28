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


def test_no_recitation_column_when_no_recitation_events() -> None:
    lecture = CourseEvent(kind="lecture", date=dt.date(2026, 1, 12), title="Intro")
    schedule = Schedule(entries=[_entry(dt.date(2026, 1, 12), [lecture])])

    rendered = render_schedule(schedule)

    assert "<th>Recitation</th>" not in rendered
    assert 'class="recitation"' not in rendered


def test_recitation_cell_spans_its_week() -> None:
    # Monday 2026-01-12 through Friday 2026-01-16, recitation on the Wednesday.
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

    assert "<th>Recitation</th>" in rendered
    assert rendered.count('<td class="recitation"') == 1
    assert 'rowspan="5"' in rendered
    assert 'href="/recitations/reci1-nodebb/"' in rendered
    assert ">Recitation: Understand NodeBB<" in rendered


def test_weeks_without_recitation_get_empty_cells() -> None:
    recitation = CourseEvent(
        kind="recitation",
        date=dt.date(2026, 1, 14),
        title="Understand NodeBB",
    )
    week_one = [dt.date(2026, 1, 12) + dt.timedelta(days=i) for i in range(5)]
    week_two = [dt.date(2026, 1, 19) + dt.timedelta(days=i) for i in range(5)]
    entries = [_entry(d, [recitation] if d == recitation.date else []) for d in [*week_one, *week_two]]
    schedule = Schedule(entries=entries)

    rendered = render_schedule(schedule)

    assert rendered.count('<td class="recitation"></td>') == 5
    assert rendered.count('<td class="recitation" rowspan="5">') == 1
