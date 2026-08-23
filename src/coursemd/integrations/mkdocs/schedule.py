"""HTML rendering for course schedules in MkDocs."""

import datetime as dt
import html
from dataclasses import dataclass
from typing import Any, Callable

from coursemd.core.models.assignment import Assignment
from coursemd.core.models.checkpoint import AssignmentCheckpoint
from coursemd.core.schedule import Schedule, ScheduleEntry
from coursemd.core.utils import current_date, working_days_between


def _render_when(entry: ScheduleEntry) -> str:
    html_when = entry.date.strftime("%a %b ") + str(entry.date.day)
    return f'<td class="when">{html_when}</td>'


def _render_what(entry: ScheduleEntry, now: dt.date) -> str:
    output = ""

    if entry.events:
        rendered_events: list[str] = []
        for event in entry.events:
            title = html.escape(event.title)
            kind = event.kind.strip().lower()
            attributes = {"class": "label"}
            # ``preview_next`` (see core/schedule.py) teases the next day's
            # events before their own reveal date has passed, so their pages
            # are still filtered out of the build -- linking to one would be a
            # dead link. Only link events whose page has actually been
            # revealed -- ``reveal_date`` when the event carries one (e.g. an
            # asynchronous recitation revealed ahead of its calendar date),
            # otherwise the event's own date.
            revealed_on = event.reveal_date or entry.date
            if event.link and revealed_on <= now:
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


@dataclass(frozen=True)
class _AssignmentBlock:
    """A single box in the Assignment column: either a whole assignment (no
    checkpoints defined) or one checkpoint within an assignment that has them.

    ``start_index``/``end_index`` are this block's *natural* row range --
    before resolving conflicts with other blocks that might cover some of the
    same rows (e.g. one assignment's checkpoint landing inside another
    assignment's still-open window). ``due_date`` drives that conflict
    resolution: the block with the nearer deadline wins a contested row.
    """

    start_index: int
    end_index: int
    due_date: dt.date
    parent_title: str | None
    title: str
    due_label: str
    link: str


def _checkpoint_link(assignment: Assignment, checkpoint: AssignmentCheckpoint) -> str:
    """Resolve a checkpoint's own page URL from its satellite filename.

    A checkpoint's ``link`` front-matter value (e.g. ``1_checkpoint.md``) names
    a satellite Markdown file living alongside the assignment's ``index.md``;
    its published URL is the assignment's own URL with that file's slug
    appended. Falls back to the parent assignment's page when no ``link`` is set.
    """
    if not checkpoint.link:
        return assignment.link
    stem = checkpoint.link.rsplit("/", 1)[-1].removesuffix(".md")
    return f"{assignment.link.rstrip('/')}/{stem}/"


def _format_due_label(due_date: dt.date, due_at: dt.datetime | None) -> str:
    time_label = due_at.strftime("%I:%M%p").lstrip("0").lower() if due_at else "11:59pm"
    return f"{due_date.strftime('%A, %B %d')} @ {time_label}"


def _build_assignment_blocks(entries: list[ScheduleEntry]) -> list[_AssignmentBlock]:
    """Expand each released assignment into one or more row-spanning blocks.

    An assignment with ``checkpoints`` becomes one block per checkpoint, each
    covering the working days from the previous checkpoint (or the
    assignment's release) up to its own date. An assignment with no
    checkpoints becomes a single block covering its full release-to-due span,
    matching the previous single-box behavior.
    """
    num_entries = len(entries)

    blocks: list[_AssignmentBlock] = []
    seen: set[int] = set()
    for release_index, entry in enumerate(entries):
        assignment = entry.assignment_released
        if assignment is None or id(assignment) in seen:
            continue
        seen.add(id(assignment))

        # entry.date is where the release marker actually landed, which may be
        # later than assignment.release_date if the real release date fell
        # outside the displayed range and got clamped to the first visible day.
        effective_release_date = entry.date

        if assignment.checkpoints:
            cursor_date = effective_release_date
            cursor_index = release_index
            for checkpoint in assignment.checkpoints:
                # Checkpoint dates aren't guaranteed to land on working days (or
                # even to strictly increase), so floor the span at 1 row -- a
                # weekend-only gap between two checkpoints would otherwise
                # produce a span of 0 and collapse both into the same start
                # index, silently dropping one from the table.
                checkpoint_date = max(checkpoint.date, cursor_date)
                span = max(working_days_between(cursor_date, checkpoint_date), 1)
                end_index = min(cursor_index + span - 1, num_entries - 1)
                blocks.append(
                    _AssignmentBlock(
                        start_index=cursor_index,
                        end_index=end_index,
                        due_date=checkpoint.date,
                        parent_title=assignment.title,
                        title=checkpoint.title,
                        due_label=_format_due_label(checkpoint.date, checkpoint.due_at),
                        link=_checkpoint_link(assignment, checkpoint),
                    )
                )
                cursor_date = checkpoint_date + dt.timedelta(days=1)
                cursor_index += span
        else:
            span = working_days_between(effective_release_date, assignment.due_date)
            blocks.append(
                _AssignmentBlock(
                    start_index=release_index,
                    end_index=min(release_index + span - 1, num_entries - 1),
                    due_date=assignment.due_date,
                    parent_title=None,
                    title=assignment.title,
                    due_label=_format_due_label(assignment.due_date, None),
                    link=assignment.link,
                )
            )

    return blocks


def _render_assignment_cells(blocks: list[_AssignmentBlock], num_entries: int) -> list[str]:
    """Render the Assignment column's ``<td>`` for every row.

    Two different assignments' blocks can cover the same rows -- e.g. one
    project's checkpoint falls inside another project's still-open window.
    The column can only show one box per row, so each contested row goes to
    whichever block is due soonest (the more urgent one to show a student).
    Consecutive rows won over by the same block are merged into one
    ``rowspan`` cell; a block that loses its middle rows to a nearer deadline
    simply reappears in a second cell once that conflict ends.
    """
    winners: list[_AssignmentBlock | None] = [None] * num_entries
    for block in blocks:
        for i in range(block.start_index, block.end_index + 1):
            current = winners[i]
            if current is None or block.due_date < current.due_date:
                winners[i] = block

    cells: list[str] = []
    i = 0
    while i < num_entries:
        block = winners[i]
        if block is None:
            cells.append('<td class="assignment"></td>')
            i += 1
            continue
        j = i + 1
        while j < num_entries and winners[j] is block:
            j += 1
        cells.append(_render_assignment_block(block, j - i))
        cells.extend([""] * (j - i - 1))
        i = j
    return cells


def _render_assignment_block(block: _AssignmentBlock, rowspan: int) -> str:
    out = ""
    if block.parent_title:
        out += f'<span class="assignment-parent">{html.escape(block.parent_title)}</span><br>'
    out += f"<b>{html.escape(block.title)}</b><br>"
    out += f"Due {block.due_label}<br>"

    attributes = {"class": "label label-red", "href": html.escape(block.link, quote=True)}
    html_attributes = " ".join(f'{k}="{v}"' for k, v in attributes.items())
    out += f"<a {html_attributes}>Handout</a>"

    return f'<td class="assignment" rowspan="{rowspan}">{out}</td>'


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

    assignment_blocks = _build_assignment_blocks(entries)
    assignment_cells = _render_assignment_cells(assignment_blocks, len(entries))
    quiz_rowspans, quiz_covered = _compute_rowspans(entries, lambda entry: entry.quiz_released)
    now = current_date()

    for i, entry in enumerate(entries):
        html_quiz = (
            ""
            if not has_quizzes or i in quiz_covered
            else _render_quiz(entry, quiz_rowspans.get(i, 0))
        )
        html_assignment = assignment_cells[i]
        out += f"<tr>{_render_when(entry)}{_render_what(entry, now)}{html_quiz}{html_assignment}</tr>"

    out += "</tbody></table></div>"
    return out
