"""HTML rendering for course schedules in MkDocs."""

import html
from typing import Any, Callable

from coursemd.core.schedule import Schedule, ScheduleEntry
from coursemd.core.utils import working_days_between


def _render_when(entry: ScheduleEntry) -> str:
    html_when = entry.date.strftime("%a %b ") + str(entry.date.day)
    return f'<td class="when">{html_when}</td>'


def _render_what(entry: ScheduleEntry) -> str:
    output = ""

    if entry.events:
        rendered_events: list[str] = []
        for event in entry.events:
            title = html.escape(event.title)
            kind = event.kind.strip().lower()
            attributes = {"class": "label"}
            if event.link:
                attributes["href"] = html.escape(event.link, quote=True)

            if kind == "lecture":
                title = f"Lecture: {title}"
                attributes["class"] = "label label-gold"
                attributes["target"] = "_blank"
            elif kind == "workshop":
                title = f"Workshop: {title}"
                attributes["class"] = "label label-green"
                attributes["target"] = "_blank"
            elif kind == "recitation":
                title = f"Recitation: {title}"
                attributes["class"] = "label label-blue"
            elif kind == "lab":
                title = f"Lab: {title}"
                attributes["class"] = "label label-blue"
            elif kind == "midterm":
                title = title or "Midterm"
                attributes["class"] = "label label-red"
            elif kind:
                title = f"{html.escape(kind.replace('_', ' ').title())}: {title}"

            html_attributes = " ".join(f'{k}="{v}"' for k, v in attributes.items())
            rendered_events.append(f"<a {html_attributes}>{title}</a>")
        output = "<br>".join(rendered_events)
    elif entry.break_:
        output = f'<a class="label label-break">Break: {html.escape(entry.break_.name)}</a>'

    return f'<td class="what">{output}</td>'


def _render_assignment(entry: ScheduleEntry, num_working_days: int) -> str:
    if assignment := entry.assignment_released:
        end_date = assignment.due_date

        out = (
            f"<b>{html.escape(assignment.title)}</b><br>"
            f"Due {end_date.strftime('%A, %B %d')} @ 11:59pm"
        )

        if checkpoints := assignment.checkpoints:
            out += '<ul class="checkpoints">'
            for checkpoint in checkpoints:
                cp_date = checkpoint.date
                date_str = cp_date.strftime("%a %b ") + str(cp_date.day)
                out += "<li>"
                out += '<span class="checkpoint-badge">🚩</span>'
                out += '<span class="checkpoint-info">'
                out += f'<span class="checkpoint-date">{date_str}</span>'
                out += f'<span class="checkpoint-title">{html.escape(checkpoint.title)}</span>'
                out += "</span>"
                out += "</li>"
            out += "</ul>"
        else:
            out += "<br>"

        attributes = {"class": "label label-red", "href": html.escape(assignment.link, quote=True)}
        html_attributes = " ".join(f'{k}="{v}"' for k, v in attributes.items())
        out += f"<a {html_attributes}>Handout</a>"

        return f'<td class="assignment" rowspan="{num_working_days}">{out}</td>'

    return '<td class="assignment"></td>'


def _render_quiz(entry: ScheduleEntry, num_working_days: int) -> str:
    if quiz := entry.quiz_released:
        due_text = quiz.due_date.strftime("%A, %B %d")

        out = (
            f"<b>{html.escape(quiz.title)}</b><br>"
            f'<span class="quiz-due">Due {due_text} @ 11:59pm</span>'
        )

        if readings := quiz.readings:
            out += (
                '<div class="quiz-readings-wrap">'
                '<span class="quiz-readings-label">Readings</span>'
                '<ul class="quiz-readings">'
            )
            for r in readings:
                title_esc = html.escape(r.title)
                url_esc = html.escape(r.url, quote=True)
                out += (
                    '<li><span class="reading-badge">📖</span>'
                    f'<a href="{url_esc}" target="_blank"'
                    f' rel="noopener noreferrer">{title_esc}</a></li>'
                )
            out += "</ul></div>"

        attributes = {"class": "label label-purple", "href": quiz.link or ""}
        html_attributes = " ".join(f'{k}="{v}"' for k, v in attributes.items())
        out += f"<br><a {html_attributes}>Take Quiz</a>"

        return f'<td class="quiz" rowspan="{num_working_days}">{out}</td>'

    return '<td class="quiz"></td>'


def _compute_rowspans(
    entries: list[ScheduleEntry],
    get_released: Callable[[ScheduleEntry], Any | None],
) -> tuple[dict[int, int], set[int]]:
    """Compute how many rows each released block should span.

    Blocks are keyed by the index of their first (release) entry. A block's
    natural span is however many working days lie between its release and
    due dates, but that's truncated if a *new* block releases before the
    current one would otherwise end -- e.g. Project 2 releasing while
    Project 1 is still open. Without the truncation, the later release
    would silently overwrite the row-span counter without ever being
    rendered, disappearing from the table entirely.

    Returns a ``(rowspans, covered)`` pair: ``rowspans`` maps a block's
    starting index to its row count, and ``covered`` is the set of indices
    absorbed into an earlier block, which should render no cell at all so
    the earlier row's ``rowspan`` can cover them.
    """
    starts = [i for i, entry in enumerate(entries) if get_released(entry) is not None]
    rowspans: dict[int, int] = {}
    for pos, i in enumerate(starts):
        item = get_released(entries[i])
        assert item is not None
        natural_end = i + working_days_between(item.release_date, item.due_date) - 1
        if pos + 1 < len(starts):
            natural_end = min(natural_end, starts[pos + 1] - 1)
        rowspans[i] = max(natural_end, i) - i + 1

    covered: set[int] = set()
    for i, span in rowspans.items():
        covered.update(range(i + 1, i + span))
    return rowspans, covered


def render_schedule(schedule: Schedule) -> str:
    """Render a Schedule as an HTML table."""
    entries = list(schedule.entries)
    if not entries:
        return "<p><em>No events yet.</em></p>"

    has_quizzes = any(entry.quiz_released or entry.quiz_due for entry in entries)

    quiz_header = "<th>Quiz</th>" if has_quizzes else ""
    out = (
        '<div id="schedule"><table><thead><tr><th>Date</th><th>Event</th>'
        f"{quiz_header}<th>Assignment</th></tr></thead><tbody>"
    )

    assignment_rowspans, assignment_covered = _compute_rowspans(
        entries, lambda entry: entry.assignment_released
    )
    quiz_rowspans, quiz_covered = _compute_rowspans(entries, lambda entry: entry.quiz_released)

    for i, entry in enumerate(entries):
        html_quiz = (
            ""
            if not has_quizzes or i in quiz_covered
            else _render_quiz(entry, quiz_rowspans.get(i, 0))
        )
        html_assignment = (
            ""
            if i in assignment_covered
            else _render_assignment(entry, assignment_rowspans.get(i, 0))
        )
        out += f"<tr>{_render_when(entry)}{_render_what(entry)}{html_quiz}{html_assignment}</tr>"

    out += "</tbody></table></div>"
    return out
