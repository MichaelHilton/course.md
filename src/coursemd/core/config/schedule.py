"""Schedule configuration for course repositories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from coursemd.core.config_helpers import CONFIG_FILENAME, require_mapping
from coursemd.core.exceptions import CoursemdValidationError
from coursemd.core.loaders.dates import parse_date
from coursemd.core.models.course_break import CourseBreak
from coursemd.core.models.course_event import CourseEvent
from coursemd.core.schedule import Schedule

if TYPE_CHECKING:
    import datetime as dt

    from coursemd.core.models.repository import CourseRepository


def _require_date(value: Any, *, label: str) -> dt.date:
    parsed = parse_date(value)
    if parsed is None:
        raise CoursemdValidationError(
            f"{label} must be a valid date or ISO-8601 timestamp in {CONFIG_FILENAME}."
        )
    return parsed


# Weekday names (and common abbreviations) mapped to Python weekday numbers (Mon=0).
_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def _parse_meeting_days(value: Any) -> tuple[int, ...] | None:
    """Parse ``schedule.meeting_days`` into sorted weekday numbers, or None if unset."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise CoursemdValidationError(
            f"schedule.meeting_days must be a list of weekday names in {CONFIG_FILENAME}."
        )
    days: set[int] = set()
    for index, raw in enumerate(value):
        key = raw.strip().lower() if isinstance(raw, str) else None
        if key not in _WEEKDAYS:
            raise CoursemdValidationError(
                f"schedule.meeting_days[{index}] must be a weekday name (e.g. 'monday') "
                f"in {CONFIG_FILENAME}."
            )
        days.add(_WEEKDAYS[key])
    return tuple(sorted(days))


@dataclass(frozen=True)
class ScheduleConfig:
    start_date: dt.date
    end_date: dt.date
    events: list[CourseEvent]
    breaks: list[CourseBreak]
    meeting_days: tuple[int, ...] | None = None

    @classmethod
    def parse(cls, raw_value: Any) -> Self:
        schedule_map = require_mapping(raw_value, label="schedule")
        start_date = _require_date(schedule_map.get("start_date"), label="schedule.start_date")
        end_date = _require_date(schedule_map.get("end_date"), label="schedule.end_date")
        if end_date < start_date:
            raise CoursemdValidationError(
                f"schedule.end_date must not be earlier than schedule.start_date in "
                f"{CONFIG_FILENAME}."
            )

        events = CourseEvent.from_list(schedule_map.get("events", []))

        breaks_raw = schedule_map.get("breaks", [])
        if not isinstance(breaks_raw, list):
            raise CoursemdValidationError(f"schedule.breaks must be a list in {CONFIG_FILENAME}.")

        breaks: list[CourseBreak] = []
        for index, raw_break in enumerate(breaks_raw):
            break_map = require_mapping(raw_break, label=f"schedule.breaks[{index}]")
            start = _require_date(
                break_map.get("start"),
                label=f"schedule.breaks[{index}].start",
            )
            end = _require_date(
                break_map.get("end"),
                label=f"schedule.breaks[{index}].end",
            )
            if end < start:
                raise CoursemdValidationError(
                    f"schedule.breaks[{index}].end must not be earlier than "
                    f"schedule.breaks[{index}].start in {CONFIG_FILENAME}."
                )
            name = break_map.get("name")
            if not isinstance(name, str) or not name.strip():
                raise CoursemdValidationError(
                    f"schedule.breaks[{index}].name must be a non-empty string in "
                    f"{CONFIG_FILENAME}."
                )
            breaks.append(CourseBreak(name=name.strip(), start=start, end=end))

        sorted_breaks = sorted(enumerate(breaks), key=lambda item: item[1].start)
        previous_index: int | None = None
        previous_break: CourseBreak | None = None
        for index, break_ in sorted_breaks:
            if previous_break is not None and break_.start <= previous_break.end:
                raise CoursemdValidationError(
                    f"schedule.breaks[{index}] overlaps schedule.breaks[{previous_index}] "
                    f"in {CONFIG_FILENAME}."
                )
            previous_index = index
            previous_break = break_

        meeting_days = _parse_meeting_days(schedule_map.get("meeting_days"))

        return cls(
            start_date=start_date,
            end_date=end_date,
            events=events,
            breaks=breaks,
            meeting_days=meeting_days,
        )

    def build(self, repository: CourseRepository) -> Schedule:
        return Schedule.build(
            earliest_date=self.start_date,
            latest_date=self.end_date,
            events=[
                *self.events,
                *(lab.as_course_event() for lab in repository.labs),
                *(recitation.as_course_event() for recitation in repository.recitations),
            ],
            breaks=self.breaks,
            assignments=repository.assignments,
            quizzes=repository.quizzes,
        )
