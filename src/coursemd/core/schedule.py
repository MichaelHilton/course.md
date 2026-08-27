"""Core schedule data model."""

import datetime as dt
import typing as t
from dataclasses import dataclass

from coursemd.core.models.assignment import Assignment
from coursemd.core.models.course_break import CourseBreak
from coursemd.core.models.course_event import CourseEvent
from coursemd.core.models.quiz import Quiz
from coursemd.core.utils import current_date, working_days


@dataclass(frozen=True)
class ScheduleEntry:
    """Stores information for a single day in the course schedule."""

    date: dt.date
    events: list[CourseEvent]
    break_: CourseBreak | None
    assignment_released: Assignment | None
    assignment_due: Assignment | None
    quiz_released: Quiz | None
    quiz_due: Quiz | None


@dataclass(frozen=True)
class Schedule:
    """Represents a complete course schedule."""

    entries: t.Sequence[ScheduleEntry]

    @classmethod
    def build(
        cls,
        earliest_date: dt.date,
        latest_date: dt.date,
        events: list[CourseEvent],
        breaks: list[CourseBreak],
        assignments: list[Assignment],
        quizzes: list[Quiz],
        show_unreleased_content: bool = False,
    ) -> t.Self:
        """
        Build a schedule from course data.

        Args:
            earliest_date: Start date of the course
            latest_date: End date of the course
            events: List of course events (lectures, recitations, exams)
            breaks: List of break periods
            assignments: List of assignments
            quizzes: List of quizzes
            show_unreleased_content: If set, include events/assignments/quizzes
                regardless of release date, matching the whole-page filtering
                behavior controlled by the same flag elsewhere.

        Returns:
            A Schedule object with all entries populated
        """
        now = current_date()

        def break_at_date(d: dt.date) -> CourseBreak | None:
            """Find if there's a break on the given date."""
            for break_ in breaks:
                if break_.contains(d):
                    return break_
            return None

        # Exam-like events stay on the schedule regardless of their date, so
        # students can always see when the next exam is even while the
        # surrounding lecture content is still hidden.
        always_visible_kinds = {"midterm", "exam", "final"}

        def preview_next(
            events_by_date: dict[dt.date, list[CourseEvent]],
        ) -> dict[dt.date, list[CourseEvent]]:
            """Keep all previous events and the next upcoming event, hide future
            ones -- except exam-like events, whose dates are always shown."""
            filtered: dict[dt.date, list[CourseEvent]] = {}

            # We keep all previous events as well as the next upcoming event
            # We ignore all other future events
            sorted_dates = sorted(events_by_date)
            for d in sorted_dates:
                filtered[d] = events_by_date[d]
                if d > now:
                    break

            # Re-add exam-like events that fall past the preview cutoff. Only the
            # exam events for that day are surfaced, so a future lecture sharing
            # the date is not leaked.
            for d in sorted_dates:
                if d in filtered:
                    continue
                exam_events = [
                    e
                    for e in events_by_date[d]
                    if e.kind.strip().lower() in always_visible_kinds
                ]
                if exam_events:
                    filtered[d] = exam_events

            return filtered

        # Build event dictionaries
        events_by_date: dict[dt.date, list[CourseEvent]] = {}
        for event in events:
            events_by_date.setdefault(event.date, []).append(event)
        date_to_events = (
            events_by_date if show_unreleased_content else preview_next(events_by_date)
        )

        # The displayed schedule only covers working_days(earliest_date, latest_date),
        # which floors to the Monday of earliest_date's week. An assignment released
        # before that floor (e.g. a prep assignment released before the term starts)
        # would otherwise never land on any visible entry and silently vanish from
        # the table, so clamp its release marker to the first visible day instead.
        schedule_start = earliest_date - dt.timedelta(days=earliest_date.weekday())

        # Build assignment dictionaries
        date_to_assignment_release = {
            max(assignment.release_date, schedule_start): assignment
            for assignment in assignments
            if show_unreleased_content or assignment.reveal_on <= now
        }
        date_to_assignment_due = {
            assignment.due_date: assignment
            for assignment in assignments
            if show_unreleased_content or assignment.release_date <= now
        }

        # Build quiz dictionaries
        date_to_quiz_release = {
            quiz.release_date: quiz
            for quiz in quizzes
            if show_unreleased_content or quiz.release_date <= now
        }
        date_to_quiz_due = {
            quiz.due_date: quiz
            for quiz in quizzes
            if show_unreleased_content or quiz.release_date <= now
        }

        # Build schedule entries
        entries: list[ScheduleEntry] = []
        for date in working_days(earliest_date, latest_date):
            entry = ScheduleEntry(
                date=date,
                events=date_to_events.get(date, []),
                break_=break_at_date(date),
                assignment_released=date_to_assignment_release.get(date),
                assignment_due=date_to_assignment_due.get(date),
                quiz_released=date_to_quiz_release.get(date),
                quiz_due=date_to_quiz_due.get(date),
            )
            entries.append(entry)

        return cls(entries)
