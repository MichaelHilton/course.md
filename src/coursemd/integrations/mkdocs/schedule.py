"""HTML rendering for course schedules in MkDocs."""

import html

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


def _render_assignment(entry: ScheduleEntry) -> str:
    if assignment := entry.assignment_released:
        num_working_days = working_days_between(assignment.release_date, assignment.due_date)
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


def _render_quiz(entry: ScheduleEntry) -> str:
    if quiz := entry.quiz_released:
        num_working_days = working_days_between(quiz.release_date, quiz.due_date)
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


def _render_entry(
    entry: ScheduleEntry,
    include_quiz: bool = True,
    skip_quiz: bool = False,
    skip_assignment: bool = False,
) -> str:
    html_quiz = "" if not include_quiz or skip_quiz else _render_quiz(entry)
    html_assignment = "" if skip_assignment else _render_assignment(entry)
    return f"<tr>{_render_when(entry)}{_render_what(entry)}{html_quiz}{html_assignment}</tr>"


def render_schedule(schedule: Schedule) -> str:
    """Render a Schedule as an HTML table."""
    if not schedule.entries:
        return "<p><em>No events yet.</em></p>"

    has_quizzes = any(entry.quiz_released or entry.quiz_due for entry in schedule.entries)

    quiz_header = "<th>Quiz</th>" if has_quizzes else ""
    out = (
        '<div id="schedule"><table><thead><tr><th>Date</th><th>Event</th>'
        f"{quiz_header}<th>Assignment</th></tr></thead><tbody>"
    )

    quiz_span_remaining = 0
    assignment_span_remaining = 0

    for entry in schedule.entries:
        skip_quiz = quiz_span_remaining > 0
        skip_assignment = assignment_span_remaining > 0

        if entry.quiz_released:
            quiz_span_remaining = working_days_between(
                entry.quiz_released.release_date, entry.quiz_released.due_date
            )
        if entry.assignment_released:
            assignment_span_remaining = working_days_between(
                entry.assignment_released.release_date,
                entry.assignment_released.due_date,
            )

        out += _render_entry(
            entry,
            include_quiz=has_quizzes,
            skip_quiz=skip_quiz,
            skip_assignment=skip_assignment,
        )

        if quiz_span_remaining > 0:
            quiz_span_remaining -= 1
        if assignment_span_remaining > 0:
            assignment_span_remaining -= 1

    out += "</tbody></table></div>"
    return out
