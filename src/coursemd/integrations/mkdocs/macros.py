"""MkDocs macros for course websites."""

from __future__ import annotations

import typing as t

from jinja2 import Environment, FileSystemLoader, select_autoescape

from coursemd.core.loaders.dates import parse_date as _parse_date
from coursemd.core.schedule import Schedule
from coursemd.core.utils import current_date
from coursemd.integrations.canvas.config import DEFAULT_CANVAS_BASE_URL
from coursemd.integrations.mkdocs.schedule import render_schedule
from coursemd.integrations.mkdocs.schedule_cards import (
    render_schedule_cards,
    render_this_week_card,
)

if t.TYPE_CHECKING:
    from coursemd.core.models.assignment import Assignment
    from coursemd.core.models.lab import Lab
    from coursemd.core.models.recitation import Recitation
    from coursemd.core.models.staff import StaffMember

_TH_EXCEPTION_MIN = 11  # 11th, 12th, 13th are exceptions to ordinal suffix rules
_TH_EXCEPTION_MAX = 13
_DEFAULT_STAFF_PHOTO_BASE_PATH = "/assets/images"
_DEFAULT_STAFFER_TEMPLATE = """
{%- macro render_staffer(person) -%}
<div class="staffer card">
    <div class="container">
        {% if person.photo %}
        <img class="staffer-image" src="{{ photo_base_path }}/{{ person.photo }}" alt="">
        {% else %}
        <div class="staffer-image-placeholder"></div>
        {% endif %}
        <div>
            <h3 class="staffer-name">
                {{ person.name }}
            </h3>
            <div class="staffer-links">
                {% if person.email %}
                <a href="mailto:{{ person.email }}"><span class="material-symbols-outlined">
                    mail
                </span></a>
                {% endif %}
                {% if person.website %}
                <a href="{{ person.website }}" target="_blank">
                    <span class="material-symbols-outlined">
                    public
                    </span>
                </a>
                {% endif %}
            </div>
        </div>
    </div>
</div>
{%- endmacro -%}
""".strip()


def _configured_canvas_base_url(env: t.Any) -> str:
    raw_value = env.conf.get("extra", {}).get("canvas_base_url") or DEFAULT_CANVAS_BASE_URL
    return str(raw_value).rstrip("/")


def _template_environment(env: t.Any) -> Environment:
    docs_dir = env.conf.get("docs_dir")
    template_env = Environment(
        loader=FileSystemLoader(str(docs_dir)) if docs_dir else None,
        autoescape=select_autoescape(),
    )
    template_env.globals.update(getattr(env, "variables", {}))
    template_env.globals.update(getattr(env, "macros", {}))
    return template_env


def _staffer_template(
    env: t.Any,
    *,
    template_path: str | None,
    photo_base_path: str,
) -> t.Any:
    template_env = _template_environment(env)
    template_env.globals["photo_base_path"] = photo_base_path.rstrip("/")
    return (
        template_env.get_template(template_path)
        if template_path
        else template_env.from_string(_DEFAULT_STAFFER_TEMPLATE)
    )


def _render_staffer(
    env: t.Any,
    *,
    person: StaffMember,
    template_path: str | None,
    photo_base_path: str,
) -> str:
    template = _staffer_template(
        env,
        template_path=template_path,
        photo_base_path=photo_base_path,
    )
    module = template.make_module({"photo_base_path": photo_base_path.rstrip("/")})
    return t.cast("str", module.render_staffer(person))


def _current_page_url(env: t.Any) -> str | None:
    page = getattr(env, "variables", {}).get("page")
    url = getattr(page, "url", None)
    return str(url) if url is not None else None


def define_env(env: t.Any) -> None:
    """
    Define MkDocs macros for use in course websites.

    This function is called by the coursemd MkDocs plugin or mkdocs-macros-plugin
    compatibility setups to register macros.
    """

    @env.macro
    def instructor_only(caller: t.Callable[[], str] | None = None) -> str:
        """Render a call block only when coursemd is building a preview site.

        Usage::

            {% call instructor_only() %}
            Content visible only in ``coursemd site preview`` and
            ``coursemd site build-preview``.
            {% endcall %}
        """
        if not env.variables.get("coursemd_preview", False):
            return ""
        return caller() if caller is not None else ""

    @env.macro
    def schedule_table(schedule: dict[str, t.Any]) -> str:
        """
        Render a course schedule table from schedule data.

        Args:
            schedule: Dictionary containing course, events, breaks, assignments, and quizzes

        Returns:
            HTML string for the schedule table
        """
        return render_schedule(Schedule.build(
            earliest_date=schedule["course"]["start_date"],
            latest_date=schedule["course"]["end_date"],
            events=schedule.get("events", []),
            breaks=schedule.get("breaks", []),
            assignments=schedule.get("assignments", []),
            quizzes=schedule.get("quizzes", []),
        ))

    @env.macro
    def schedule_cards(schedule: dict[str, t.Any]) -> str:
        """
        Render a course schedule as weekly cards from schedule data.

        Groups the schedule into weekly cards, each listing that week's events
        and the homework released that week. An alternative to ``schedule_table``.

        Args:
            schedule: Dictionary containing course, events, breaks, assignments, and quizzes

        Returns:
            HTML string for the weekly schedule cards
        """
        return render_schedule_cards(
            Schedule.build(
                earliest_date=schedule["course"]["start_date"],
                latest_date=schedule["course"]["end_date"],
                events=schedule.get("events", []),
                breaks=schedule.get("breaks", []),
                assignments=schedule.get("assignments", []),
                quizzes=schedule.get("quizzes", []),
            ),
            meeting_days=schedule.get("meeting_days"),
            labs=schedule.get("labs", []),
            preview_spec_links=schedule.get("preview_spec_links"),
            current_page_url=_current_page_url(env),
        )

    @env.macro
    def this_week_card(schedule: dict[str, t.Any]) -> str:
        """
        Render a single weekly card for the current week (or nearest upcoming week).

        Intended for a compact "This Week" preview, e.g. in a page hero. Reuses the
        same card markup as ``schedule_cards``.

        Args:
            schedule: Dictionary containing course, events, breaks, assignments, and quizzes

        Returns:
            HTML string for a single week card, or an empty string if there is nothing to show
        """
        return render_this_week_card(
            Schedule.build(
                earliest_date=schedule["course"]["start_date"],
                latest_date=schedule["course"]["end_date"],
                events=schedule.get("events", []),
                breaks=schedule.get("breaks", []),
                assignments=schedule.get("assignments", []),
                quizzes=schedule.get("quizzes", []),
            ),
            meeting_days=schedule.get("meeting_days"),
            labs=schedule.get("labs", []),
            preview_spec_links=schedule.get("preview_spec_links"),
            current_page_url=_current_page_url(env),
        )

    @env.macro
    def released_assignments(schedule: dict[str, t.Any]) -> list[Assignment]:
        """
        Return a list of assignments that have been released.

        If ``integrations.mkdocs.show_unreleased_content`` is set, all assignments are
        returned regardless of release date.

        Args:
            schedule: Dictionary containing schedule data

        Returns:
            List of assignment dictionaries that have been released
        """
        assignments = t.cast("list[Assignment]", schedule.get("assignments", []))
        if schedule.get("show_unreleased_content"):
            return list(assignments)
        now = current_date()
        return [assignment for assignment in assignments if assignment.release_date <= now]

    @env.macro
    def released_labs(schedule: dict[str, t.Any]) -> list[Lab]:
        """
        Return a list of labs whose session date has passed.

        If ``integrations.mkdocs.show_unreleased_content`` is set, all labs are returned
        regardless of date.

        Args:
            schedule: Dictionary containing schedule data

        Returns:
            List of lab objects whose date is on or before today
        """
        labs = t.cast("list[Lab]", schedule.get("labs", []))
        if schedule.get("show_unreleased_content"):
            return list(labs)
        now = current_date()
        return [lab for lab in labs if lab.date <= now]

    @env.macro
    def released_recitations(schedule: dict[str, t.Any]) -> list[Recitation]:
        """
        Return a list of recitations whose session date has passed.

        If ``integrations.mkdocs.show_unreleased_content`` is set, all recitations are
        returned regardless of date.

        Args:
            schedule: Dictionary containing schedule data

        Returns:
            List of recitation objects whose date is on or before today
        """
        recitations = t.cast("list[Recitation]", schedule.get("recitations", []))
        if schedule.get("show_unreleased_content"):
            return list(recitations)
        now = current_date()
        return [recitation for recitation in recitations if recitation.date <= now]

    @env.macro
    def grade_table(
        platinum_min_score: int = 93,
        platinum_grade_points: int = 10,
        gold_min_score: int = 85,
        gold_grade_points: int = 9,
        silver_min_score: int = 80,
        silver_grade_points: int = 8,
        bronze_min_score: int = 70,
        bronze_grade_points: int = 7,
        copper_min_score: int = 60,
        copper_grade_points: int = 6,
        max_score: int = 100,
    ) -> str:
        """
        Generate a Markdown table showing grade tiers and their requirements.

        Args:
            platinum_min_score: Minimum score for platinum tier
            platinum_grade_points: Points awarded for platinum tier
            ... (similar for other tiers)
            max_score: Maximum possible score

        Returns:
            Markdown string for the grade table
        """
        rows = [
            (
                "platinum",
                "Platinum",
                platinum_grade_points,
                platinum_min_score,
                ":material-trophy:",
            ),
            ("gold", "Gold", gold_grade_points, gold_min_score, ":material-medal:"),
            ("silver", "Silver", silver_grade_points, silver_min_score, ":material-medal-outline:"),
            ("bronze", "Bronze", bronze_grade_points, bronze_min_score, ":material-medal-outline:"),
            (
                "copper",
                "Copper",
                copper_grade_points,
                copper_min_score,
                ":material-certificate-outline:",
            ),
        ]

        out = [
            f"| Grade | Points | Minimum Score (out of {int(max_score)}) |",
            "|:--:|:--:|:--:|",
        ]

        for key, label, pts, cutoff, icon in rows:
            chip = f'<span class="chip" data-grade="{key}">{icon} {label}</span>'
            out.append(f"| {chip} | **{pts}** | ≥ {int(cutoff)} |")

        fail = '<span class="chip" data-grade="fail">:material-alert-circle-outline: Fail</span>'
        out.append(f"| {fail} | **0** | < {int(copper_min_score)} |")

        return "\n".join(out)

    @env.macro
    def grade_table_from_component(component: dict[str, t.Any]) -> str:
        """
        Generate a grade boundaries table from a grading component dict.

        The component should have ``raw_max`` and a ``tiers`` list whose entries
        each have ``name``, ``min_score``, and ``points``.  Tiers should be ordered
        from best (Platinum) to worst (Fail); the last tier is treated as Fail and
        rendered separately.

        Usage in Markdown: {{ grade_table_from_component(page.meta.grading) }}

        Args:
            component: A grading component dict (e.g. from page frontmatter).

        Returns:
            Markdown string for the grade boundaries table.
        """
        tier_styles: dict[str, tuple[str, str]] = {
            "platinum": ("platinum", ":material-trophy:"),
            "gold": ("gold", ":material-medal:"),
            "silver": ("silver", ":material-medal-outline:"),
            "bronze": ("bronze", ":material-medal-outline:"),
            "copper": ("copper", ":material-certificate-outline:"),
        }

        raw_max: int = int(component.get("raw_max", 100))
        tiers: list[dict[str, t.Any]] = component.get("tiers", [])
        # Last tier is "Fail"; all others are scored tiers
        scored_tiers = tiers[:-1]
        fail_tier = tiers[-1] if tiers else None

        out = [
            f"| Grade | Points | Minimum Score (out of {raw_max}) |",
            "|:--:|:--:|:--:|",
        ]

        for tier in scored_tiers:
            name: str = tier.get("name", "")
            key = name.lower()
            style_key, icon = tier_styles.get(key, (key, ":material-star:"))
            pts = int(tier.get("points", 0))
            min_score = int(tier.get("min_score", 0))
            chip = f'<span class="chip" data-grade="{style_key}">{icon} {name}</span>'
            out.append(f"| {chip} | **{pts}** | ≥ {min_score} |")

        if fail_tier is not None:
            copper_min = int(scored_tiers[-1].get("min_score", 0)) if scored_tiers else 0
            fail_chip = (
                '<span class="chip" data-grade="fail">:material-alert-circle-outline: Fail</span>'
            )
            out.append(f"| {fail_chip} | **0** | < {copper_min} |")

        return "\n".join(out)

    @env.macro
    def grade_boundaries_table() -> str:
        """
        Generate a Markdown table showing letter grade boundaries from preloaded grading data.

        Returns:
            Markdown string for the grade boundaries table
        """
        grading_data = env.variables.get("grading")
        if grading_data is None:
            return ""

        out = [
            "| Course Grade | Minimum Points |",
            "|:--:|:--:|",
        ]

        out.extend(
            f"| **{boundary['letter']}** | **{boundary['min']}** |"
            for boundary in grading_data["scale"]
        )

        out.append(f"| **R** | < {grading_data['scale'][-1]['min']} |")

        return "\n".join(out)

    @env.macro
    def rubric_table(rubric: list[dict[str, t.Any]]) -> str:
        """
        Render a rubric from structured front-matter data.

        Expects a list of sections, each with a 'section' name, 'points' total,
        and a 'criteria' list. Each criterion has a 'name', 'points', and 'tiers'
        list (ordered best-to-worst), where each tier has 'points', 'label', and 'desc'.

        Args:
            rubric: List of rubric section dicts (from page front matter)

        Returns:
            HTML string for the rubric
        """
        html_parts: list[str] = []

        for section in rubric:
            section_name = section["section"]
            section_points = section["points"]
            criteria = section.get("criteria", [])

            html_parts.append(
                f'<div class="rubric-section">'
                f'<h3 class="rubric-section__title">'
                f"{section_name}"
                f'<span class="rubric-section__points">{section_points} pts</span>'
                f"</h3>"
            )

            for criterion in criteria:
                crit_name = criterion["name"]
                crit_points = criterion["points"]
                crit_desc = criterion.get("desc", "")
                tiers = criterion.get("tiers", [])

                desc_html = (
                    f'<span class="rubric-criterion__desc">{crit_desc}</span>' if crit_desc else ""
                )

                html_parts.append(
                    f'<details class="rubric-criterion">'
                    f'<summary class="rubric-criterion__header">'
                    f'<span class="rubric-criterion__summary">'
                    f'<span class="rubric-criterion__name">{crit_name}</span>'
                    f"{desc_html}"
                    f"</span>"
                    f'<span class="rubric-criterion__points">{crit_points} pts</span>'
                    f"</summary>"
                    f'<table class="rubric-criterion__table">'
                    f"<thead><tr>"
                    f"<th>Points</th><th>Level</th><th>Description</th>"
                    f"</tr></thead>"
                    f"<tbody>"
                )

                for tier in tiers:
                    tier_points = tier["points"]
                    tier_label = tier["label"]
                    tier_desc = tier["desc"]
                    is_top = tier_points == crit_points
                    is_zero = tier_points == 0
                    tier_class = (
                        "rubric-tier--top" if is_top else ("rubric-tier--zero" if is_zero else "")
                    )
                    html_parts.append(
                        f'<tr class="rubric-tier {tier_class}">'
                        f'<td class="rubric-tier__points">{tier_points}</td>'
                        f'<td class="rubric-tier__label">{tier_label}</td>'
                        f'<td class="rubric-tier__desc">{tier_desc}</td>'
                        f"</tr>"
                    )

                html_parts.append("</tbody></table></details>")

            html_parts.append("</div>")

        return "\n".join(html_parts)

    @env.macro
    def render_staffer(
        person: StaffMember,
        template_path: str | None = None,
        photo_base_path: str = _DEFAULT_STAFF_PHOTO_BASE_PATH,
    ) -> str:
        """
        Render a single staff member using the built-in staffer template.

        Args:
            person: Staff member loaded from .coursemd.yml.
            template_path: Optional template path relative to the MkDocs docs directory.
            photo_base_path: URL path prefix for staff photos.

        Returns:
            HTML string for the staff member card.
        """
        return _render_staffer(
            env,
            person=person,
            template_path=template_path,
            photo_base_path=photo_base_path,
        )

    @env.macro
    def ta_team_table(staff: list[StaffMember]) -> str:
        """
        Render a Markdown table mapping TAs to their assigned teams.

        Only teaching assistants with assigned teams are included.

        Args:
            staff: List of staff members loaded from .coursemd.yml.

        Returns:
            Markdown string for the TA-team mapping table.
        """
        rows = [
            "| TA | Teams |",
            "| --- | --- |",
        ]
        for person in staff:
            if person.role != "teaching-assistant":
                continue
            if not person.teams or person.email is None:
                continue
            teams_str = ", ".join(person.teams)
            rows.append(f"| [{person.name}](mailto:{person.email}) | {teams_str} |")
        return "\n".join(rows)

    @env.macro
    def checkpoints_list(heading: str = "Checkpoints and Deadlines") -> str:
        """
        Render a heading and Markdown bullet list of checkpoints for an assignment page.

        Reads ``checkpoints`` from the current page's frontmatter. Each entry should
        have a ``title`` and optionally ``doc_anchor`` (for an in-page link) and
        ``due_at`` (ISO datetime string, used to format the due date).
        Entries without ``due_at`` are listed without a date.

        The ``heading`` argument controls the ``##`` heading text.

        Usage in Markdown: {{ checkpoints_list() }}

        Returns:
            Markdown string with a ## heading and bullet list.
        """
        page = env.variables.get("page")
        if page is None:
            return ""

        checkpoints: list[dict[str, t.Any]] = getattr(page, "meta", {}).get("checkpoints", [])
        if not checkpoints:
            return ""

        lines: list[str] = [f"## {heading}", ""]
        for cp in checkpoints:
            name: str = cp.get("title", "")
            anchor: str = cp.get("doc_anchor", "")
            due_at_raw = cp.get("due_at", "")
            due_date = _parse_date(due_at_raw) if due_at_raw else None

            if due_date:
                day_name = due_date.strftime("%A")
                month_name = due_date.strftime("%B")
                day = due_date.day
                suffix = (
                    "th"
                    if _TH_EXCEPTION_MIN <= day <= _TH_EXCEPTION_MAX
                    else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                )
                date_str = f"{day_name}, {month_name} {day}{suffix}"
                due_str = f"due {date_str} at 11:59 pm ET"
            else:
                due_str = ""

            suffix_str = f" ({due_str})" if due_str else ""
            if anchor:
                lines.append(f"* [**{name}**](#{anchor}){suffix_str}")
            else:
                lines.append(f"* **{name}**{suffix_str}")

        return "\n".join(lines)

    @env.macro
    def gdoc_copy(doc_id: str) -> str:
        """
        Return a Google Doc "make a copy" link for a document id.

        Usage in Markdown: {{ gdoc_copy(page.meta.quality_plan_gdoc_id) }}
        """
        if not doc_id:
            return ""
        return f"https://docs.google.com/document/d/{doc_id}/copy"

    @env.macro
    def canvas_submission(canvas_id: int) -> str:
        """
        Render a Canvas submission callout for a specific assignment.

        Looks up the assignment by canvas_id in the page's assignments
        frontmatter list and renders an admonition with a direct submission link.
        When the Canvas submission defines a ``submission_form`` list, each field is
        rendered as a labelled item so students know exactly what to paste into
        the Canvas text-entry box.
        Falls back to a generic link if the assignment is not found in frontmatter.

        Usage in Markdown: {{ canvas_submission(958737) }}

        Args:
            canvas_id: The Canvas assignment ID to link to.

        Returns:
            Markdown string for the submission admonition.
        """
        canvas_course_id: int | None = env.conf.get("extra", {}).get(
            "canvas_course_id"
        ) or env.variables.get("schedule", {}).get("course", {}).get("canvas_course_id")
        canvas_base_url = _configured_canvas_base_url(env)
        url = (
            f"{canvas_base_url}/courses/{canvas_course_id}/assignments/{canvas_id}"
            if canvas_course_id
            else f"{canvas_base_url}/assignments/{canvas_id}"
        )

        # Try to find the Canvas submission config from the current page first,
        # then from any assignment list injected into the page.
        assignment_cfg: dict[str, t.Any] = {}
        page = env.variables.get("page")
        if page is not None:
            page_meta = getattr(page, "meta", {})
            page_integrations = page_meta.get("integrations", {})
            if isinstance(page_integrations, dict):
                page_canvas = page_integrations.get("canvas", {})
                if isinstance(page_canvas, dict):
                    checkpoints = page_canvas.get("checkpoints", [])
                    if isinstance(checkpoints, list):
                        for checkpoint in checkpoints:
                            if not isinstance(checkpoint, dict):
                                continue
                            checkpoint_id = checkpoint.get("canvas_id") or checkpoint.get("id")
                            if checkpoint_id == canvas_id:
                                assignment_cfg = checkpoint
                                break
                    if not assignment_cfg:
                        page_id = page_canvas.get("canvas_id") or page_canvas.get("id")
                        if page_id == canvas_id:
                            assignment_cfg = page_canvas
            assignments = getattr(page, "meta", {}).get("assignments", [])
            if not assignment_cfg:
                for assignment in assignments:
                    integration_map = assignment.get("integrations", {})
                    if not isinstance(integration_map, dict):
                        continue
                    canvas = integration_map.get("canvas", {})
                    if not isinstance(canvas, dict):
                        continue
                    canvas_id_value = canvas.get("canvas_id") or canvas.get("id")
                    if canvas_id_value == canvas_id:
                        assignment_cfg = assignment
                        break

        name: str | None = assignment_cfg.get("name")
        link_text = f"Click here to submit {name}" if name else "Click here to submit"

        # Build submission form field lines.
        form_fields: list[dict[str, t.Any]] = assignment_cfg.get("submission_form", [])
        field_icons: dict[str, str] = {
            "url": ":material-link:",
            "gdoc": ":material-google-drive:",
            "text": ":material-text:",
            "confirm": ":material-checkbox-marked-outline:",
        }
        lines: list[str] = [
            '!!! warning "Canvas Submission"',
            f"    [**{link_text}**]({url})",
        ]
        if form_fields:
            lines.append("")
            lines.append("    **What to include in your submission:**")
            lines.append("")
            for field in form_fields:
                field_label: str = field.get("label", "")
                field_type: str = str(field.get("type", "text")).lower()
                field_hint: str = field.get("hint", "")
                icon = field_icons.get(field_type, ":material-text:")
                label_md = f"**{field_label}**" if field_label else ""
                hint_md = f" — *{field_hint}*" if field_hint else ""
                lines.append(f"    - {icon} {label_md}{hint_md}")

        return "\n".join(lines)
