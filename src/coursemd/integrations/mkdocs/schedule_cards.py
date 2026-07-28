"""HTML rendering for course schedules as weekly cards in MkDocs.

This is an alternative presentation to :mod:`coursemd.integrations.mkdocs.schedule`
(which renders a flat day-by-day table).  Instead of one row per working day, the
schedule is grouped into weekly cards: each card lists that week's events (lectures,
labs, breaks) and the homework released that week.
"""

import datetime as dt
import html
import posixpath
from urllib.parse import urlsplit, urlunsplit

from coursemd.core.models.assignment import Assignment
from coursemd.core.models.course_event import CourseEvent
from coursemd.core.models.lab import Lab
from coursemd.core.schedule import Schedule, ScheduleEntry
from coursemd.core.utils import current_date
from coursemd.core.utils import week_start as _week_start

# Map an event kind to the CSS modifier used for its colour dot / accent.
# Kinds not listed fall back to ``other``.
_KIND_MODIFIERS = {
    "lecture": "lecture",
    "workshop": "workshop",
    "recitation": "recitation",
    "lab": "lab",
    "midterm": "exam",
    "exam": "exam",
}

# Kinds whose title is prefixed with a human-readable label (e.g. "Lecture: ...").
_KIND_LABELS = {
    "lecture": "Lecture",
    "workshop": "Workshop",
    "recitation": "Recitation",
    "lab": "Lab",
}

# Kinds that link out to external material (open in a new tab).
_EXTERNAL_KINDS = {"lecture", "workshop"}


def _relative_site_url(link: str, current_page_url: str | None = None) -> str:
    """Convert root-relative internal URLs to page-relative URLs."""
    parsed = urlsplit(link)
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
    ):
        return link

    current_path = (current_page_url or "").strip("/")
    if not current_path:
        current_dir = "."
    else:
        last_segment = current_path.rsplit("/", 1)[-1]
        if "." in last_segment:
            current_dir = posixpath.dirname(current_path) or "."
        else:
            current_dir = current_path

    target_path = parsed.path.strip("/") or "."
    target_has_trailing_slash = parsed.path.endswith("/")
    relative_path = posixpath.relpath(target_path, start=current_dir)
    if target_has_trailing_slash and not relative_path.endswith("/"):
        relative_path += "/"

    return urlunsplit(("", "", relative_path, parsed.query, parsed.fragment))


def _format_range(start: dt.date, end: dt.date) -> str:
    """Format a date range, collapsing a single day and omitting a shared month."""
    left = start.strftime("%b ") + str(start.day)
    if start == end:
        return left
    right = str(end.day) if start.month == end.month else end.strftime("%b ") + str(end.day)
    return f"{left} – {right}"  # noqa: RUF001 (en dash is intentional for ranges)


def _render_event(
    event: CourseEvent,
    *,
    labs_by_date: dict[dt.date, Lab] | None = None,
    preview_spec_links: dict[dt.date, str] | None = None,
    current_page_url: str | None = None,
) -> str:
    kind = event.kind.strip().lower()
    modifier = _KIND_MODIFIERS.get(kind, "other")

    title = html.escape(event.title)
    if label := _KIND_LABELS.get(kind):
        title = f"{label}: {title}"
    elif kind in {"midterm", "exam"}:
        title = title or kind.title()
    elif kind:
        title = f"{html.escape(kind.replace('_', ' ').title())}: {title}"

    day_label = event.date.strftime("%a ") + str(event.date.day)

    link = event.link
    if link is None and kind == "lab" and labs_by_date is not None:
        lab = labs_by_date.get(event.date)
        if lab is not None:
            link = lab.link

    if kind == "lecture" and event.learning_goals:
        goals = "".join(f"<li>{html.escape(goal)}</li>" for goal in event.learning_goals)
        slides = ""
        if link:
            href = html.escape(_relative_site_url(link, current_page_url), quote=True)
            slides = (
                f'<a class="wevent__slides-link" href="{href}" '
                'target="_blank" rel="noopener noreferrer">Open slides <span '
                'aria-hidden="true">↗</span></a>'
            )
        spec = ""
        if preview_spec_links and (spec_link := preview_spec_links.get(event.date)):
            href = html.escape(_relative_site_url(spec_link, current_page_url), quote=True)
            spec = f'<a class="wevent__spec-link" href="{href}">View lecture spec</a>'
        return (
            f'<li class="wevent wevent--{modifier} wevent--expandable">'
            '<details class="wevent__details">'
            '<summary class="wevent__summary">'
            f'<span class="wevent__day">{day_label}</span>'
            f'<span class="wevent__title">{title}</span>'
            "</summary>"
            '<div class="wevent__details-content">'
            '<p class="wevent__goals-heading">Learning goals</p>'
            f'<ul class="wevent__goals">{goals}</ul>{slides}{spec}'
            "</div>"
            "</details>"
            "</li>"
        )

    if link:
        href = html.escape(_relative_site_url(link, current_page_url), quote=True)
        target = ' target="_blank" rel="noopener noreferrer"' if kind in _EXTERNAL_KINDS else ""
        body = f'<a class="wevent__title" href="{href}"{target}>{title}</a>'
    else:
        body = f'<span class="wevent__title">{title}</span>'

    return (
        f'<li class="wevent wevent--{modifier}">'
        f'<span class="wevent__day">{day_label}</span>'
        f"{body}"
        f"</li>"
    )


def _render_break_day(entry: ScheduleEntry) -> str:
    """Render a single break day as a dated row, like the event rows."""
    assert entry.break_ is not None
    day_label = entry.date.strftime("%a ") + str(entry.date.day)
    name = f"No Class: {html.escape(entry.break_.name)}"
    return (
        '<li class="wevent wevent--break">'
        f'<span class="wevent__day">{day_label}</span>'
        f'<span class="wevent__title">{name}</span>'
        "</li>"
    )


def _render_homework_row(
    assignment: Assignment,
    *,
    current_page_url: str | None = None,
) -> str:
    """Render a homework as a dated row placed on its due date (usually Sunday)."""
    due = assignment.due_date
    day_label = due.strftime("%a ") + str(due.day)
    title = f"Due: {html.escape(assignment.title)}"
    if assignment.link:
        href = html.escape(_relative_site_url(assignment.link, current_page_url), quote=True)
        body = f'<a class="wevent__title" href="{href}">{title}</a>'
    else:
        body = f'<span class="wevent__title">{title}</span>'
    return (
        '<li class="wevent wevent--homework">'
        f'<span class="wevent__day">{day_label}</span>'
        f"{body}"
        "</li>"
    )


def _render_week(
    *,
    week_start: dt.date,
    week_number: int,
    entries: list[ScheduleEntry],
    homework: list[Assignment],
    labs_by_date: dict[dt.date, Lab],
    preview_spec_links: dict[dt.date, str] | None,
    today_week_start: dt.date,
    meeting_days: tuple[int, ...] | None,
    current_page_url: str | None = None,
    show_status: bool = True,
) -> str:
    rows: list[str] = []
    for entry in entries:
        if entry.events:
            rows.extend(
                _render_event(
                    event,
                    labs_by_date=labs_by_date,
                    preview_spec_links=preview_spec_links,
                    current_page_url=current_page_url,
                )
                for event in entry.events
            )
        elif entry.break_ is not None and (
            meeting_days is None or entry.date.weekday() in meeting_days
        ):
            # Only flag a break on days the class would otherwise meet.
            rows.append(_render_break_day(entry))

    # Homework is due on the weekend, so it follows the week's Mon-Fri events.
    rows.extend(
        _render_homework_row(a, current_page_url=current_page_url)
        for a in sorted(homework, key=lambda a: a.due_date)
    )

    # Skip weeks with nothing to show (e.g. unrevealed future weeks).
    if not rows:
        return ""

    if week_start == today_week_start:
        status_class = " week-card--current"
        status = '<span class="week-card__status">You are here</span>' if show_status else ""
    elif week_start > today_week_start:
        status_class = " week-card--upcoming"
        status = ""
    else:
        status_class = " week-card--past"
        status = ""

    date_range = _format_range(entries[0].date, entries[-1].date)

    return (
        f'<section class="week-card{status_class}">'
        '<header class="week-card__head">'
        f'<span class="week-card__num">Week {week_number}</span>'
        f'<span class="week-card__dates">{date_range}</span>'
        f"{status}"
        "</header>"
        f'<ul class="week-card__events">{"".join(rows)}</ul>'
        "</section>"
    )


def _build_weeks(
    schedule: Schedule,
) -> tuple[dict[dt.date, list[ScheduleEntry]], dict[dt.date, list[Assignment]]]:
    """Group entries by week (Monday) and released homework by its due-date week."""
    weeks: dict[dt.date, list[ScheduleEntry]] = {}
    for entry in schedule.entries:
        weeks.setdefault(_week_start(entry.date), []).append(entry)

    homework_by_week: dict[dt.date, list[Assignment]] = {}
    seen: set[int] = set()
    for entry in schedule.entries:
        assignment = entry.assignment_released
        if assignment is None or id(assignment) in seen:
            continue
        seen.add(id(assignment))
        homework_by_week.setdefault(_week_start(assignment.due_date), []).append(assignment)

    return weeks, homework_by_week


def render_schedule_cards(
    schedule: Schedule,
    meeting_days: tuple[int, ...] | None = None,
    labs: list[Lab] | None = None,
    preview_spec_links: dict[dt.date, str] | None = None,
    current_page_url: str | None = None,
) -> str:
    """Render a Schedule as a stack of weekly cards.

    ``meeting_days`` are the weekday numbers (Mon=0) the class meets; when given,
    breaks are only flagged on those days. When None, breaks show on every working day.
    """
    if not schedule.entries:
        return "<p><em>No events yet.</em></p>"

    weeks, homework_by_week = _build_weeks(schedule)
    labs_by_date = {lab.date: lab for lab in labs or []}
    first_week_start = min(weeks)
    today_week_start = _week_start(current_date())

    cards: list[str] = []
    for week_start in sorted(weeks):
        week_number = ((week_start - first_week_start).days // 7) + 1
        cards.append(
            _render_week(
                meeting_days=meeting_days,
                week_start=week_start,
                week_number=week_number,
                entries=weeks[week_start],
                homework=homework_by_week.get(week_start, []),
                labs_by_date=labs_by_date,
                preview_spec_links=preview_spec_links,
                today_week_start=today_week_start,
                current_page_url=current_page_url,
            )
        )

    return f'<div id="schedule" class="schedule-cards">{"".join(cards)}</div>'


def render_this_week_card(
    schedule: Schedule,
    meeting_days: tuple[int, ...] | None = None,
    labs: list[Lab] | None = None,
    preview_spec_links: dict[dt.date, str] | None = None,
    current_page_url: str | None = None,
) -> str:
    """Render a single card for the current week (or the nearest upcoming one)."""
    if not schedule.entries:
        return ""

    weeks, homework_by_week = _build_weeks(schedule)
    labs_by_date = {lab.date: lab for lab in labs or []}
    first_week_start = min(weeks)
    today_week_start = _week_start(current_date())
    week_starts = sorted(weeks)

    # Prefer this week; otherwise the next upcoming week; otherwise the last week.
    upcoming = [start for start in week_starts if start >= today_week_start]
    target = upcoming[0] if upcoming else week_starts[-1]

    week_number = ((target - first_week_start).days // 7) + 1
    card = _render_week(
        meeting_days=meeting_days,
        week_start=target,
        week_number=week_number,
        entries=weeks[target],
        homework=homework_by_week.get(target, []),
        labs_by_date=labs_by_date,
        preview_spec_links=preview_spec_links,
        today_week_start=today_week_start,
        current_page_url=current_page_url,
        show_status=False,
    )
    return f'<div class="this-week">{card}</div>' if card else ""
