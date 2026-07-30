from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest
import typer
from mkdocs.commands.build import build as mkdocs_build
from mkdocs.config import load_config
from typer.testing import CliRunner

import coursemd.integrations
import coursemd.integrations.canvas.cli
import coursemd.integrations.github.client
import coursemd.integrations.github.setup
import coursemd.integrations.mkdocs.cli
import coursemd.integrations.quarto.cli
from coursemd import cli
from coursemd.core.config import CourseConfig, CoursePathsConfig, ScheduleConfig
from coursemd.core.exceptions import CoursemdError, CoursemdValidationError
from coursemd.core.loaders.assignments import discover_assignment_sources
from coursemd.core.loaders.validation import normalize_release_date
from coursemd.core.models.assignment import Assignment, AssignmentCheckpoint
from coursemd.core.models.course_break import CourseBreak
from coursemd.core.models.course_event import CourseEvent
from coursemd.core.models.repository import CourseRepository
from coursemd.core.models.staff import StaffMember
from coursemd.core.schedule import Schedule, ScheduleEntry
from coursemd.integrations.canvas.config import CanvasConfig
from coursemd.integrations.mkdocs.config import MkdocsIntegrationConfig
from coursemd.integrations.mkdocs.schedule import render_schedule

runner = CliRunner()
HW3_RAW_MAX = 100


def test_validation_error_is_a_coursemd_error() -> None:
    assert issubclass(CoursemdValidationError, CoursemdError)


def _write_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(contents), encoding="utf-8")


def _build_repo_fixture(repo_root: Path) -> None:
    _write_file(
        repo_root / ".coursemd.yml",
        """
                schedule:
                    start_date: 2026-01-12
                    end_date: 2026-01-16
                    events:
                        - kind: lecture
                          date: 2026-01-12
                          title: Course Introduction
                    breaks:
                        - name: No Class
                          start: 2026-01-14
                          end: 2026-01-14
                integrations:
                    mkdocs:
                        base_url: https://example.edu/course
                        project_dir: website
                    quarto:
                        dir: slides
                    github:
                        organization: example-course-org
                        instructors_team_slug: instructors
                    canvas:
                        base_url: https://canvas.example.edu
                        course_id: 12345
                paths:
                    data_dir: data
                    assignments_dir: assignments
                    quizzes_dir: quizzes
        """,
    )
    _write_file(
        repo_root / "data" / "schedule.yaml",
        """
        course:
          start_date: 2026-01-12
          end_date: 2026-01-16
          title: Test Course
          canvas_course_id: 12345
        """,
    )
    _write_file(
        repo_root / "assignments" / "hw1.md",
        """
        ---
        title: Homework 1
        kind: homework
        release_date: 2026-01-12
        due_date: 2026-01-16
        due_at: "2026-01-16T23:59:00-05:00"
        points: 100
        ---

        # Homework 1
        """,
    )
    _write_file(
        repo_root / "quizzes" / "week1.md",
        """
        ---
        title: Week 1 Reading Quiz
        release_date: 2026-01-12
        due_at: "2026-01-16T23:59:00-05:00"
        questions:
          - question_type: multiple_choice
            question_text: What is quality?
            answers:
              - text: Fitness for purpose
                correct: true
              - text: Just test coverage
                correct: false
        ---

        # Quiz
        """,
    )
    _write_file(
        repo_root / "website" / "mkdocs.yml",
        """
        site_name: Test Course
        plugins:
          - coursemd:
              config_file: ../.coursemd.yml
        markdown_extensions:
          - tables
        nav:
          - Home: index.md
        """,
    )
    _write_file(
        repo_root / "website" / "docs" / "index.md",
        """
        # Home

        {{ schedule_table(schedule) }}
        """,
    )
    _write_file(
        repo_root / "slides" / "_quarto.yml",
        """
        project:
          type: website
        """,
    )
    _write_file(
        repo_root / "slides" / "index.qmd",
        """
        # Slides
        """,
    )


def test_validate_uses_repository_defaults(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    nested_dir = tmp_path / "website" / "docs"
    nested_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(nested_dir)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 0
    assert "Validated 1 data file(s), 1 assignment spec(s), and 1 quiz spec(s)." in result.stdout
    assert "Validation passed." in result.stdout


def test_validate_discovers_assignment_files_without_hw_prefix(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    (tmp_path / "assignments" / "hw1.md").unlink()
    _write_file(
        tmp_path / "assignments" / "phase-a.md",
        """
        ---
        title: Phase A
        kind: homework
        release_date: 2026-01-12
        due_date: 2026-01-16
        due_at: "2026-01-16T23:59:00-05:00"
        points: 100
        ---

        # Phase A
        """,
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 0
    assert "Validated 1 data file(s), 1 assignment spec(s), and 1 quiz spec(s)." in result.stdout


def test_assignment_load_uses_canonical_loader(tmp_path: Path) -> None:
    _build_repo_fixture(tmp_path)

    assignment = Assignment.load(tmp_path / "assignments" / "hw1.md")

    assert assignment.name == "Homework 1"
    assert assignment.source_file == tmp_path / "assignments" / "hw1.md"
    assert assignment.due_at == "2026-01-16T23:59:00-05:00"
    assert assignment.description == "# Homework 1"


def test_discover_assignment_sources_finds_nested_project_folders(tmp_path: Path) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "assignments" / "P1" / "index.md",
        """
        ---
        title: "Project 1: Hello, World"
        release_date: 2026-01-12
        due_date: 2026-01-16
        ---

        # Project 1
        """,
    )
    _write_file(
        tmp_path / "assignments" / "P1" / "1_checkpoint.md",
        """
        ---
        title: Build Checkpoint
        ---

        # Build Checkpoint
        """,
    )
    _write_file(
        tmp_path / "assignments" / "P1" / "images" / "diagram.png",
        "not a real png, just needs to exist",
    )

    sources = discover_assignment_sources(tmp_path / "assignments")

    by_slug = {source.record_file.parent.name: source for source in sources if source.record_file.name == "index.md"}
    assert "P1" in by_slug
    p1 = by_slug["P1"]
    assert p1.record_file == tmp_path / "assignments" / "P1" / "index.md"
    assert p1.satellite_files == [tmp_path / "assignments" / "P1" / "1_checkpoint.md"]

    flat = {source.record_file.name for source in sources if source.record_file.name != "index.md"}
    assert flat == {"hw1.md"}


def test_nested_assignment_index_loads_with_parent_folder_slug(tmp_path: Path) -> None:
    _write_file(
        tmp_path / "assignments" / "P1" / "index.md",
        """
        ---
        title: "Project 1: Hello, World"
        release_date: 2026-01-12
        due_date: 2026-01-16
        ---

        # Project 1
        """,
    )

    assignment = Assignment.load(tmp_path / "assignments" / "P1" / "index.md")

    assert assignment.title == "Project 1: Hello, World"
    assert assignment.link == "/assignments/P1/"


def test_coursemd_mkdocs_plugin_builds_nested_project_pages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "assignments" / "P1" / "index.md",
        """
        ---
        title: "Project 1: Hello, World"
        release_date: 2026-01-12
        due_date: 2026-01-16
        ---

        # Project 1

        See the [checkpoint](1_checkpoint.md) for details.
        """,
    )
    _write_file(
        tmp_path / "assignments" / "P1" / "1_checkpoint.md",
        """
        ---
        title: Build Checkpoint
        ---

        # Build Checkpoint
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    assert (tmp_path / "site" / "assignments" / "P1" / "index.html").is_file()
    assert (tmp_path / "site" / "assignments" / "P1" / "1_checkpoint" / "index.html").is_file()
    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Project 1: Hello, World" in index_html
    project_html = (tmp_path / "site" / "assignments" / "P1" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "Build Checkpoint" in project_html


def test_coursemd_mkdocs_plugin_hides_satellite_pages_of_unreleased_assignment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "assignments" / "P1" / "index.md",
        """
        ---
        title: "Project 1: Hello, World"
        release_date: 2026-02-01
        due_date: 2026-02-05
        ---

        # Project 1
        """,
    )
    _write_file(
        tmp_path / "assignments" / "P1" / "1_checkpoint.md",
        """
        ---
        title: Build Checkpoint
        ---

        # Build Checkpoint
        """,
    )
    _write_file(
        tmp_path / "assignments" / "P1" / "always-visible-guide.md",
        """
        ---
        title: Dev Tools Guide
        release_date: 2026-01-01
        ---

        # Dev Tools Guide
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    # The project isn't released yet: its index and undated satellite are hidden.
    assert not (tmp_path / "site" / "assignments" / "P1" / "index.html").exists()
    assert not (tmp_path / "site" / "assignments" / "P1" / "1_checkpoint" / "index.html").exists()
    # A satellite with its own past release_date opts out of the inherited gating.
    assert (
        tmp_path / "site" / "assignments" / "P1" / "always-visible-guide" / "index.html"
    ).is_file()


def test_coursemd_mkdocs_plugin_uses_configured_assignments_label(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "        project_dir: website\n",
            "        project_dir: website\n        assignments_label: Projects\n",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert ">Projects<" in index_html
    assert ">Assignments<" not in index_html


def test_assignment_loads_homework_meta_and_rubric_from_hw3() -> None:
    assignment = Assignment.load(Path("examples/hw3.md"))

    assert assignment.name == "Phase C: Extend"
    assert assignment.kind == "homework"
    assert assignment.group_assignment is True
    assert assignment.meta["grading"]["raw_max"] == HW3_RAW_MAX
    assert [tier["name"] for tier in assignment.meta["grading"]["tiers"]] == [
        "Platinum",
        "Gold",
        "Silver",
        "Bronze",
        "Copper",
        "Fail",
    ]
    assert assignment.meta["template_gdoc_id"] == "1eO83EOS7jzQGuiTmwQezaY6KTLHr02-HEhuiModxVOA"
    assert [checkpoint.title for checkpoint in assignment.checkpoints] == [
        "C0: Scope Check",
        "C1: Hazard Analysis & Draft Launch Argument",
        "C2: Complete Launch Argument",
        "C3: Final Presentation",
    ]
    assert [section.section for section in assignment.rubric.sections] == [
        "Hazard Analysis & Launch Scope",
        "Launch Argument",
        "Presentation & Reflection",
    ]


def test_assignment_checkpoint_from_dict_loads_checkpoint() -> None:
    checkpoint = AssignmentCheckpoint.from_dict(
        {
            "date": "2026-01-14",
            "title": "Draft Due",
            "description": "Share a draft.",
            "due_at": "2026-01-14T23:59:00-05:00",
            "doc_anchor": "draft-due",
        },
        index=0,
    )

    assert checkpoint == AssignmentCheckpoint(
        date=dt.date(2026, 1, 14),
        title="Draft Due",
        due_at=dt.datetime.fromisoformat("2026-01-14T23:59:00-05:00"),
        description="Share a draft.",
        doc_anchor="draft-due",
    )


def test_course_event_constructors_parse_event_data() -> None:
    event = CourseEvent.from_dict(
        {
            "kind": "Lecture",
            "date": "2026-01-12",
            "title": " Course Introduction ",
            "link": " /slides/intro.pdf ",
            "learning-goals": [" Explain flow ", "Describe feedback"],
            "speakers": [" Instructor One ", "Instructor Two"],
        }
    )

    assert event == CourseEvent(
        kind="lecture",
        date=dt.date(2026, 1, 12),
        title="Course Introduction",
        link="/slides/intro.pdf",
        learning_goals=("Explain flow", "Describe feedback"),
        speakers=("Instructor One", "Instructor Two"),
    )
    assert CourseEvent.parse(event) is event
    assert CourseEvent.from_list([{"kind": "workshop", "date": "2026-01-13", "title": "Lab"}]) == [
        CourseEvent(kind="workshop", date=dt.date(2026, 1, 13), title="Lab")
    ]


def test_validate_allows_multiple_schedule_events_on_same_date(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / ".coursemd.yml",
        "\n".join(
            [
                "schedule:",
                "  start_date: 2026-01-12",
                "  end_date: 2026-01-16",
                "  events:",
                "    - kind: lecture",
                "      date: 2026-01-12",
                "      title: Course Introduction",
                "    - kind: workshop",
                "      date: 2026-01-12",
                "      title: Duplicate Slot",
                "integrations:",
                "  mkdocs:",
                "    base_url: https://example.edu/course",
                "    project_dir: website",
                "  quarto:",
                "    dir: slides",
                "  github:",
                "    organization: example-course-org",
                "    instructors_team_slug: instructors",
                "  canvas:",
                "    base_url: https://canvas.example.edu",
                "    course_id: 12345",
                "paths:",
                "  data_dir: data",
                "  assignments_dir: assignments",
                "  quizzes_dir: quizzes",
                "",
            ]
        ),
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 0
    assert "Validation passed." in result.stdout


def test_validate_rejects_legacy_schedule_events_in_data_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "data" / "schedule.yaml",
        """
        course:
          start_date: 2026-01-12
          end_date: 2026-01-16
          title: Test Course
        events:
          - kind: lecture
            date: 2026-01-12
            title: Course Introduction
        """,
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "'events' must be configured in .coursemd.yml under schedule.events." in result.output


def test_validate_fails_for_assignment_missing_release_date(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "assignments" / "hw1.md",
        """\
---
title: Homework 1
kind: homework
due_date: 2026-01-16
due_at: "2026-01-16T23:59:00-05:00"
points: 100
---

# Homework 1
""",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "'release_date' must be a valid date or ISO-8601 timestamp" in result.output


def test_validate_fails_for_assignment_checkpoint_outside_assignment_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "assignments" / "hw1.md",
        "\n".join(
            [
                "---",
                "title: Homework 1",
                "kind: homework",
                "release_date: 2026-01-12",
                "due_date: 2026-01-16",
                "checkpoints:",
                "  - date: 2026-01-20",
                "    title: Late checkpoint",
                '    due_at: "2026-01-20T23:59:00-05:00"',
                'due_at: "2026-01-16T23:59:00-05:00"',
                "points: 100",
                "---",
                "",
                "# Homework 1",
                "",
            ]
        ),
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "checkpoints[0].date must fall between 'release_date' and" in result.output
    assert "'due_date'." in result.output


def test_validate_fails_for_assignment_checkpoint_missing_due_at(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "assignments" / "hw1.md",
        """\
---
title: Homework 1
kind: homework
release_date: 2026-01-12
due_date: 2026-01-16
checkpoints:
  - date: 2026-01-14
    title: Draft checkpoint
due_at: "2026-01-16T23:59:00-05:00"
points: 100
---

# Homework 1
""",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "'checkpoints[0].due_at' is required." in result.output


def test_validate_fails_for_assignment_checkpoint_due_at_on_wrong_date(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "assignments" / "hw1.md",
        """\
---
title: Homework 1
kind: homework
release_date: 2026-01-12
due_date: 2026-01-16
checkpoints:
  - date: 2026-01-14
    title: Draft checkpoint
    due_at: "2026-01-15T23:59:00-05:00"
due_at: "2026-01-16T23:59:00-05:00"
points: 100
---

# Homework 1
""",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "checkpoints[0].due_at must fall on the same calendar date" in result.output


def test_validate_fails_for_quiz_missing_release_date(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "quizzes" / "week1.md",
        "\n".join(
            [
                "---",
                "title: Week 1 Reading Quiz",
                'due_at: "2026-01-16T23:59:00-05:00"',
                "questions:",
                "  - question_type: multiple_choice",
                "    question_text: What is quality?",
                "    answers:",
                "      - text: Fitness for purpose",
                "        correct: true",
                "      - text: Just test coverage",
                "        correct: false",
                "---",
                "",
                "# Quiz",
                "",
            ]
        ),
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "'release_date' must be a valid date or ISO-8601 timestamp" in result.output


def test_sync_command_discovers_config_in_parent_directory(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    nested_dir = tmp_path / "website" / "docs"
    nested_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(nested_dir)

    result = runner.invoke(
        cli.app,
        [
            "canvas",
            "assignments",
            "--plan-only",
            "assignments/hw1.md",
        ],
    )

    assert result.exit_code == 0
    assert "Loaded 1 assignment spec(s) for the Canvas integration:" in result.stdout


def test_github_setup_uses_repository_defaults_in_dry_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    local_runner = CliRunner()
    commands: list[tuple[list[str], str | None]] = []

    def fake_run_command(
        args: list[str] | tuple[str, ...],
        *,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        argv = list(args)
        commands.append((argv, input_text))
        if argv == ["gh", "auth", "status"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[-1] == "/orgs/example-course-org/teams/instructors":
            return subprocess.CompletedProcess(argv, 0, '{"id": 42}', "")
        if argv[-1] == "/orgs/example-course-org":
            return subprocess.CompletedProcess(
                argv,
                0,
                '{"default_repository_permission": "read"}',
                "",
            )
        raise AssertionError(f"Unexpected command: {argv}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coursemd.integrations.github.setup, "_run_command", fake_run_command)
    monkeypatch.setattr(
        coursemd.integrations.github.client.shutil,
        "which",
        lambda _program: "/usr/bin/gh",
    )

    result = local_runner.invoke(cli.app, ["github", "setup", "--dry-run"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "Resolved team 'instructors' in org 'example-course-org' (ID: 42)." in result.stdout
    assert "Default repository permission: 'read' -> 'none'" in result.stdout
    assert "Dry run: would update organization default repository permission." in result.stdout
    assert "Dry run: would configure ruleset 'Protect main branch'" in result.stdout
    assert not any("--method" in command and "PATCH" in command for command, _ in commands)
    assert not any("--input" in command for command, _ in commands)


def test_validate_fails_without_coursemd_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "Could not find .coursemd.yml" in result.output


def test_optional_site_commands_report_missing_mkdocs_dependency(monkeypatch) -> None:
    local_app = typer.Typer(no_args_is_help=True)
    monkeypatch.setattr(
        coursemd.integrations.mkdocs.cli,
        "_MKDOCS_IMPORT_ERROR",
        ModuleNotFoundError("No module named 'mkdocs'", name="mkdocs"),
    )

    coursemd.integrations.mkdocs.cli.register_site_cli(local_app)

    result = runner.invoke(local_app, ["site", "preview"])

    assert result.exit_code == 1
    assert "coursemd[mkdocs]" in result.output


def test_optional_canvas_commands_report_missing_canvas_dependency(monkeypatch) -> None:
    local_app = typer.Typer(no_args_is_help=True)
    monkeypatch.setattr(
        coursemd.integrations.canvas.cli,
        "register_sync_canvas_assignments_command",
        lambda _app: (_ for _ in ()).throw(
            ModuleNotFoundError("No module named 'requests'", name="requests")
        ),
    )

    coursemd.integrations.canvas.cli.register_canvas_cli(local_app)

    result = runner.invoke(local_app, ["canvas", "assignments"])

    assert result.exit_code == 1
    assert "coursemd[canvas]" in result.output


def test_entry_point_integrations_can_register_config_and_cli(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    package_dir = tmp_path / "coursemd_demo_plugin"
    _write_file(
        package_dir / "__init__.py",
        "",
    )
    _write_file(
        package_dir / "config.py",
        """
        from __future__ import annotations

        import typer

        from coursemd.core.integration_config import IntegrationConfig, IntegrationConfigContext


        class DemoIntegrationConfig(IntegrationConfig):
            metavar = "demo"

            @classmethod
            def parse(cls, raw_value, *, context: IntegrationConfigContext):
                del raw_value
                del context
                return cls()

            @classmethod
            def register_cli(cls, app: typer.Typer) -> None:
                del cls
                demo_app = typer.Typer(no_args_is_help=True)
                app.add_typer(demo_app, name="demo")

                @demo_app.command("ping")
                def ping() -> int:
                    typer.echo("demo ok")
                    return 0
        """,
    )
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "paths:\n",
            "    demo: {}\npaths:\n",
            1,
        ),
        encoding="utf-8",
    )

    def fake_entry_points(*, group: str) -> list[object]:
        if group != "coursemd.integrations":
            return []
        return [type("EntryPoint", (), {"value": "coursemd_demo_plugin.config"})()]

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(coursemd.integrations, "_builtin_integrations_loaded", False)
    monkeypatch.setattr(coursemd.integrations, "entry_points", fake_entry_points)

    config = CourseConfig.load(start_dir=tmp_path)

    assert "demo" in config.integrations
    assert config.integrations["demo"].__class__.metavar == "demo"

    local_app = typer.Typer(no_args_is_help=True)
    coursemd.integrations.register_integration_clis(local_app)

    result = runner.invoke(local_app, ["demo", "ping"])

    assert result.exit_code == 0
    assert "demo ok" in result.stdout


def test_config_reads_course_timezone(tmp_path: Path) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        "timezone: America/Los_Angeles\n" + config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    config = CourseConfig.load(start_dir=tmp_path / "website")

    assert config.timezone == "America/Los_Angeles"


def test_course_paths_config_defaults_all_paths(tmp_path: Path) -> None:
    paths = CoursePathsConfig.default(repo_root=tmp_path)

    assert paths.data_dir == (tmp_path / "data").resolve()
    assert paths.assignments_dir == (tmp_path / "assignments").resolve()
    assert paths.quizzes_dir == (tmp_path / "quizzes").resolve()
    assert paths.env_file == ".env"


def test_course_paths_config_from_dict_defaults_missing_fields(tmp_path: Path) -> None:
    paths = CoursePathsConfig.from_dict({"data": "course-data"}, repo_root=tmp_path)

    assert paths.data_dir == (tmp_path / "course-data").resolve()
    assert paths.assignments_dir == (tmp_path / "assignments").resolve()
    assert paths.quizzes_dir == (tmp_path / "quizzes").resolve()
    assert paths.env_file == ".env"


def test_course_paths_config_accepts_dir_suffixed_keys(tmp_path: Path) -> None:
    paths = CoursePathsConfig.from_dict(
        {
            "data_dir": "course-data",
            "assignments_dir": "hw",
            "quizzes_dir": "graded-quizzes",
            "labs_dir": "sections",
            "recitations_dir": "recitations",
        },
        repo_root=tmp_path,
    )

    assert paths.data_dir == (tmp_path / "course-data").resolve()
    assert paths.assignments_dir == (tmp_path / "hw").resolve()
    assert paths.quizzes_dir == (tmp_path / "graded-quizzes").resolve()
    assert paths.labs_dir == (tmp_path / "sections").resolve()
    assert paths.recitations_dir == (tmp_path / "recitations").resolve()


def test_course_paths_config_defaults_recitations_dir(tmp_path: Path) -> None:
    paths = CoursePathsConfig.default(repo_root=tmp_path)

    assert paths.recitations_dir == (tmp_path / "recitations").resolve()


def test_config_load_defaults_paths_for_repository_without_quizzes(tmp_path: Path) -> None:
    _write_file(
        tmp_path / ".coursemd.yml",
        """
        integrations:
          mkdocs:
            base_url: https://example.edu/course
            project_dir: website
        paths:
          data_dir: data
          assignments_dir: assignments
        """,
    )

    config = CourseConfig.load(start_dir=tmp_path)
    repository = CourseRepository.build(config)

    assert config.paths.quizzes_dir == (tmp_path / "quizzes").resolve()
    assert repository.quizzes == []


def test_config_reads_staff_members(tmp_path: Path) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        dedent(
            """
        staff:
          - name: Ada Lovelace
            role: Teaching-Assistant
            email: ada@example.edu
            website: https://example.edu/ada
            photo: ada.png
            github: ada
            teams:
              - 1
              - Team B
        """
        )
        + config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    config = CourseConfig.load(start_dir=tmp_path / "website")
    repository = CourseRepository.build(config)

    assert config.staff == [
        StaffMember(
            name="Ada Lovelace",
            role="teaching-assistant",
            email="ada@example.edu",
            website="https://example.edu/ada",
            photo="ada.png",
            github="ada",
            teams=("1", "Team B"),
        )
    ]
    assert repository.staff == config.staff


def test_config_rejects_invalid_staff_member(tmp_path: Path) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        dedent(
            """
        staff:
          - role: instructor
        """
        )
        + config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(CoursemdValidationError, match=r"staff\[0\].name"):
        CourseConfig.load(start_dir=tmp_path)


def test_config_rejects_invalid_timezone(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        "timezone: Not/A_Timezone\n" + config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert "timezone must be a valid IANA timezone" in result.output


def test_config_load_raises_core_validation_error_for_invalid_timezone(tmp_path: Path) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        "timezone: Not/A_Timezone\n" + config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(CoursemdValidationError, match="timezone must be a valid IANA timezone"):
        CourseConfig.load(start_dir=tmp_path)


def test_repository_build_raises_core_validation_error_for_invalid_assignment(
    tmp_path: Path,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "assignments" / "hw1.md",
        """\
---
title: Homework 1
kind: homework
due_date: 2026-01-16
due_at: "2026-01-16T23:59:00-05:00"
points: 100
---

# Homework 1
""",
    )
    config = CourseConfig.load(start_dir=tmp_path)

    with pytest.raises(CoursemdValidationError, match="'release_date' must be a valid date"):
        CourseRepository.build(config)


def test_repository_build_retains_loaded_config(tmp_path: Path) -> None:
    _build_repo_fixture(tmp_path)
    config = CourseConfig.load(start_dir=tmp_path)

    repository = CourseRepository.build(config)
    mkdocs_config = MkdocsIntegrationConfig.require(config)

    assert repository.config is config
    assert repository.repo_root == config.repo_root
    assert repository.timezone == config.timezone
    assert repository.paths == config.paths
    assert repository.get_integration("mkdocs", MkdocsIntegrationConfig) == mkdocs_config
    assert MkdocsIntegrationConfig.get(repository) == mkdocs_config
    assert MkdocsIntegrationConfig.require(repository) == mkdocs_config


def test_config_load_parses_schedule_config(tmp_path: Path) -> None:
    _build_repo_fixture(tmp_path)

    config = CourseConfig.load(start_dir=tmp_path)

    assert config.schedule == ScheduleConfig(
        start_date=dt.date(2026, 1, 12),
        end_date=dt.date(2026, 1, 16),
        events=[
            CourseEvent(
                kind="lecture",
                date=dt.date(2026, 1, 12),
                title="Course Introduction",
            )
        ],
        breaks=[
            CourseBreak(
                name="No Class",
                start=dt.date(2026, 1, 14),
                end=dt.date(2026, 1, 14),
            )
        ],
    )


def test_schedule_config_builds_full_schedule_from_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "labs" / "lab1.md",
        """
        ---
        kind: lab
        title: Lab 1
        date: 2026-01-13
        ---

        # Lab 1
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    config = CourseConfig.load(start_dir=tmp_path)
    repository = CourseRepository.build(config)

    assert config.schedule is not None
    schedule = config.schedule.build(repository)

    by_date = {entry.date: entry for entry in schedule.entries}
    assert by_date[dt.date(2026, 1, 12)].events == [
        CourseEvent(
            kind="lecture",
            date=dt.date(2026, 1, 12),
            title="Course Introduction",
        )
    ]
    assert by_date[dt.date(2026, 1, 12)].assignment_released is repository.assignments[0]
    assert by_date[dt.date(2026, 1, 13)].events == [
        CourseEvent(
            kind="lab",
            date=dt.date(2026, 1, 13),
            title="Lab 1",
            link="/labs/lab1/",
        )
    ]
    assert by_date[dt.date(2026, 1, 14)].break_ == CourseBreak(
        name="No Class",
        start=dt.date(2026, 1, 14),
        end=dt.date(2026, 1, 14),
    )
    assert by_date[dt.date(2026, 1, 16)].quiz_due is repository.quizzes[0]


def test_render_schedule_omits_quiz_column_when_schedule_has_no_quizzes() -> None:
    schedule = Schedule(
        entries=[
            ScheduleEntry(
                date=dt.date(2026, 1, 12),
                events=[
                    CourseEvent(
                        kind="lecture",
                        date=dt.date(2026, 1, 12),
                        title="Course Introduction",
                    )
                ],
                break_=None,
                assignment_released=None,
                assignment_due=None,
                quiz_released=None,
                quiz_due=None,
            )
        ]
    )

    rendered = render_schedule(schedule)

    assert "<th>Quiz</th>" not in rendered
    assert '<td class="quiz"' not in rendered
    assert "<th>Assignment</th>" in rendered


def test_release_date_normalization_uses_configured_timezone_dst(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        "timezone: America/New_York\n" + config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 0
    assert normalize_release_date("2026-01-12") == "2026-01-12T00:00:00-05:00"
    assert normalize_release_date("2026-07-01") == "2026-07-01T00:00:00-04:00"


def test_config_allows_repositories_without_canvas(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        """
integrations:
    mkdocs:
        base_url: https://example.edu/course
        project_dir: website
paths:
    data_dir: data
    assignments_dir: assignments
    quizzes_dir: quizzes
        """,
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = CourseConfig.load(start_dir=tmp_path)
    result = runner.invoke(cli.app, ["validate"])

    assert CanvasConfig.get(config) is None
    assert result.exit_code == 0
    assert "Validation passed." in result.stdout


def test_repository_load_rejects_non_quiz_content_in_quizzes_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / ".coursemd.yml",
        """
        integrations:
          mkdocs:
            base_url: https://example.edu/course
            project_dir: website
        paths:
          data_dir: data
          assignments_dir: assignments
          quizzes_dir: quizzes
        """,
    )
    _write_file(
        tmp_path / "assignments" / "hw1.md",
        """
        ---
        title: Homework 1
        kind: homework
        release_date: 2026-01-12
        due_date: 2026-01-16
        ---

        # Homework 1
        """,
    )
    _write_file(
        tmp_path / "quizzes" / "week1.md",
        """
        ---
        title: Week 1 Reading Quiz
        release_date: 2026-01-12
        due_at: "2026-01-16T23:59:00-05:00"
        link: https://example.edu/quiz
        ---

        # Quiz
        """,
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["validate"])

    assert result.exit_code == 1
    assert result.exception is not None
    assert "'questions' is required." in str(result.exception)


def test_config_reads_site_url_paths(tmp_path: Path) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "        project_dir: website\n",
            "        project_dir: website\n"
            "        assignments_url_path: coursework\n"
            "        include_specs: true\n",
        ),
        encoding="utf-8",
    )

    config = CourseConfig.load(start_dir=tmp_path / "website")

    mkdocs_config = MkdocsIntegrationConfig.require(config)
    assert mkdocs_config.assignments_url_path == "coursework"
    assert mkdocs_config.include_specs is True


def test_site_build_uses_project_dir_from_config(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    recorded: dict[str, object] = {}

    class FakePlugins:
        def on_startup(self, *, command: str, dirty: bool) -> None:
            recorded["startup"] = {"command": command, "dirty": dirty}

        def on_shutdown(self) -> None:
            recorded["shutdown"] = True

    class FakeConfig:
        def __init__(self) -> None:
            self.plugins = FakePlugins()

    def fake_load_config(
        *,
        config_file: str,
        site_dir: str | None = None,
        strict: bool,
    ) -> FakeConfig:
        recorded["load_config"] = {
            "config_file": config_file,
            "site_dir": site_dir,
            "strict": strict,
            "cwd": str(Path.cwd()),
        }
        return FakeConfig()

    def fake_build(config: FakeConfig, *, dirty: bool, serve_url: str | None = None) -> None:
        recorded["build"] = {
            "dirty": dirty,
            "serve_url": serve_url,
            "cwd": str(Path.cwd()),
            "config": config,
        }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coursemd.integrations.mkdocs.cli, "load_config", fake_load_config)
    monkeypatch.setattr(coursemd.integrations.mkdocs.cli, "mkdocs_build", fake_build)

    result = runner.invoke(cli.app, ["site", "build", "--output-dir", "build/website", "--strict"])

    assert result.exit_code == 0
    assert recorded["load_config"] == {
        "config_file": str(tmp_path / "website" / "mkdocs.yml"),
        "site_dir": str((tmp_path / "build" / "website").resolve()),
        "strict": True,
        "cwd": str(tmp_path / "website"),
    }
    assert recorded["startup"] == {"command": "build", "dirty": False}
    assert recorded["build"] == {
        "dirty": False,
        "serve_url": None,
        "cwd": str(tmp_path / "website"),
        "config": recorded["build"]["config"],
    }
    assert recorded["shutdown"] is True


def test_site_preview_sets_current_date_override(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    recorded: dict[str, object] = {}

    def fake_serve(
        *,
        config_file: str | None = None,
        livereload: bool = True,
        build_type: str | None = None,
        watch_theme: bool = False,
        watch: list[str] | None = None,
        open_in_browser: bool = False,
        **kwargs: object,
    ) -> None:
        recorded["serve"] = {
            "config_file": config_file,
            "livereload": livereload,
            "build_type": build_type,
            "watch_theme": watch_theme,
            "watch": watch,
            "open_in_browser": open_in_browser,
            "kwargs": kwargs,
            "cwd": str(Path.cwd()),
            "current_date_override": os.environ.get("CURRENT_DATE_OVERRIDE"),
            "coursemd_preview": os.environ.get("COURSEMD_PREVIEW"),
        }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coursemd.integrations.mkdocs.cli, "mkdocs_serve", fake_serve)

    result = runner.invoke(cli.app, ["site", "preview", "--dev-addr", "127.0.0.1:9000", "--dirty"])

    assert result.exit_code == 0
    assert "Previewing site at http://127.0.0.1:9000/" in result.stdout
    assert recorded["serve"] == {
        "config_file": str(tmp_path / "website" / "mkdocs.yml"),
        "livereload": True,
        "build_type": "dirty",
        "watch_theme": False,
        "watch": None,
        "open_in_browser": False,
        "kwargs": {"dev_addr": "127.0.0.1:9000"},
        "cwd": str(tmp_path / "website"),
        "current_date_override": "2999-12-12",
        "coursemd_preview": "1",
    }


def test_site_build_preview_sets_coursemd_preview_mode(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    recorded: dict[str, object] = {}

    class SearchPlugin:
        def on_startup(self, *, command: str, dirty: bool) -> None:
            recorded["startup"] = {"command": command, "dirty": dirty}

        def on_shutdown(self) -> None:
            recorded["shutdown"] = True

    class FakeConfig:
        def __init__(self) -> None:
            plugins = coursemd.integrations.mkdocs.cli.PluginCollection()
            plugins["search"] = SearchPlugin()
            self.plugins = plugins

    def fake_load_config(
        *,
        config_file: str,
        site_dir: str | None = None,
        strict: bool,
    ) -> FakeConfig:
        recorded["load_config"] = {
            "config_file": config_file,
            "site_dir": site_dir,
            "strict": strict,
            "cwd": str(Path.cwd()),
            "current_date_override": os.environ.get("CURRENT_DATE_OVERRIDE"),
            "coursemd_preview": os.environ.get("COURSEMD_PREVIEW"),
        }
        return FakeConfig()

    def fake_build(config: FakeConfig, *, dirty: bool, serve_url: str | None = None) -> None:
        recorded["build"] = {
            "dirty": dirty,
            "serve_url": serve_url,
            "cwd": str(Path.cwd()),
            "current_date_override": os.environ.get("CURRENT_DATE_OVERRIDE"),
            "coursemd_preview": os.environ.get("COURSEMD_PREVIEW"),
            "plugins": tuple(config.plugins.keys()),
        }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coursemd.integrations.mkdocs.cli, "load_config", fake_load_config)
    monkeypatch.setattr(coursemd.integrations.mkdocs.cli, "mkdocs_build", fake_build)

    result = runner.invoke(
        cli.app,
        ["site", "build-preview", "--output-dir", "build/website/_preview/test"],
    )

    assert result.exit_code == 0
    assert recorded["load_config"] == {
        "config_file": str(tmp_path / "website" / "mkdocs.yml"),
        "site_dir": str((tmp_path / "build" / "website" / "_preview" / "test").resolve()),
        "strict": False,
        "cwd": str(tmp_path / "website"),
        "current_date_override": "2999-12-12",
        "coursemd_preview": "1",
    }
    assert recorded["startup"] == {"command": "build", "dirty": False}
    assert recorded["build"] == {
        "dirty": False,
        "serve_url": None,
        "cwd": str(tmp_path / "website"),
        "current_date_override": "2999-12-12",
        "coursemd_preview": "1",
        "plugins": ("search",),
    }
    assert recorded["shutdown"] is True


def test_slides_build_uses_default_output_dir(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    recorded: dict[str, object] = {}

    def fake_run(args: list[str], *, cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        recorded["run"] = {
            "args": args,
            "cwd": str(cwd),
            "check": check,
        }
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coursemd.integrations.quarto.cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["quarto", "build"])

    assert result.exit_code == 0
    assert recorded["run"] == {
        "args": [
            "quarto",
            "render",
            ".",
            "--output-dir",
            str((tmp_path / "build" / "slides" / "html").resolve()),
        ],
        "cwd": str(tmp_path / "slides"),
        "check": False,
    }


def test_slides_preview_uses_configured_directory(tmp_path: Path, monkeypatch) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / ".coursemd.yml",
        """
                schedule:
                    start_date: 2026-01-12
                    end_date: 2026-01-16
                    events:
                        - kind: lecture
                          date: 2026-01-12
                          title: Course Introduction
                integrations:
                    mkdocs:
                        base_url: https://example.edu/course
                        project_dir: website
                    quarto:
                        dir: lecture-slides
                    canvas:
                        base_url: https://canvas.example.edu
                        course_id: 12345
                paths:
                    data_dir: data
                    assignments_dir: assignments
                    quizzes_dir: quizzes
        """,
    )
    _write_file(
        tmp_path / "lecture-slides" / "_quarto.yml",
        """
        project:
          type: website
        """,
    )
    recorded: dict[str, object] = {}

    def fake_run(args: list[str], *, cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        recorded["run"] = {
            "args": args,
            "cwd": str(cwd),
            "check": check,
        }
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coursemd.integrations.quarto.cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["quarto", "preview", "--output-dir", "build/slides/preview"])

    assert result.exit_code == 0
    assert recorded["run"] == {
        "args": [
            "quarto",
            "preview",
            ".",
            "--output-dir",
            str((tmp_path / "build" / "slides" / "preview").resolve()),
        ],
        "cwd": str(tmp_path / "lecture-slides"),
        "check": False,
    }


def test_coursemd_mkdocs_plugin_builds_without_symlinked_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    assert (tmp_path / "site" / "assignments" / "hw1" / "index.html").is_file()
    assert not (tmp_path / "site" / "quizzes" / "week1" / "index.html").exists()
    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Homework 1" in index_html
    assert "Week 1 Reading Quiz" in index_html
    assert "quizzes/week1" not in index_html


def test_coursemd_mkdocs_plugin_builds_without_course_content_dirs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_file(
        tmp_path / ".coursemd.yml",
        """
        integrations:
          mkdocs:
            base_url: https://example.edu/course
            project_dir: website
        paths:
          data: data
          assignments: assignments
          quizzes: quizzes
        """,
    )
    _write_file(
        tmp_path / "website" / "mkdocs.yml",
        """
        site_name: Test Course
        plugins:
          - coursemd:
              config_file: ../.coursemd.yml
        nav:
          - Home: index.md
        """,
    )
    _write_file(
        tmp_path / "website" / "docs" / "index.md",
        """
        # Home
        """,
    )
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    watched = set(config.get("watch") or [])
    assert (tmp_path / "site" / "index.html").is_file()
    assert str(tmp_path / "data") not in watched
    assert str(tmp_path / "assignments") not in watched
    assert str(tmp_path / "quizzes") not in watched


def test_coursemd_mkdocs_plugin_builds_non_canvas_course(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / ".coursemd.yml",
        """
                schedule:
                    start_date: 2026-01-12
                    end_date: 2026-01-16
                    events:
                        - kind: lecture
                          date: 2026-01-12
                          title: Course Introduction
                integrations:
                    mkdocs:
                        base_url: https://example.edu/course
                        project_dir: website
                paths:
                    data_dir: data
                    assignments_dir: assignments
                    quizzes_dir: quizzes
        """,
    )
    _write_file(
        tmp_path / "data" / "schedule.yaml",
        """
        course:
          start_date: 2026-01-12
          end_date: 2026-01-16
          title: Test Course
        """,
    )
    _write_file(
        tmp_path / "assignments" / "hw1.md",
        """
        ---
        title: Homework 1
        kind: homework
        release_date: 2026-01-12
        due_date: 2026-01-16
        ---

        # Homework 1
        """,
    )
    _write_file(
        tmp_path / "quizzes" / "week1.md",
        """
        ---
        title: Week 1 Reading Quiz
        release_date: 2026-01-12
        due_at: "2026-01-16T23:59:00-05:00"
        link: https://example.edu/quiz
        questions:
          - question_type: multiple_choice
            question_text: What is quality?
            answers:
              - text: Fitness for purpose
                correct: true
              - text: Just test coverage
                correct: false
        ---

        # Quiz
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    assert (tmp_path / "site" / "assignments" / "hw1" / "index.html").is_file()
    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Homework 1" in index_html
    assert "Week 1 Reading Quiz" in index_html
    assert "https://example.edu/quiz" in index_html


def test_coursemd_mkdocs_plugin_does_not_generate_quiz_nav(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Assignments" in index_html
    assert "Homework 1" in index_html
    assert ">Quizzes<" not in index_html
    assert "quizzes/week1" not in index_html


def test_coursemd_mkdocs_plugin_filters_future_generated_pages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-01")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    assert not (tmp_path / "site" / "assignments" / "hw1" / "index.html").exists()


def test_coursemd_mkdocs_plugin_exposes_lecture_specs_only_in_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "        project_dir: website\n",
            "        project_dir: website\n        include_specs: true\n",
        ),
        encoding="utf-8",
    )
    _write_file(
        tmp_path / "specs" / "00-course-introduction.md",
        """
        ---
        kind: lecture_spec
        title: Course Introduction Spec
        date: 2026-01-12
        ---

        # Course Introduction Spec
        """,
    )
    _write_file(
        tmp_path / "website" / "docs" / "index.md",
        """
        # Home

        {{ schedule_cards(schedule) }}
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    public_config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "public-site"))
    public_config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(public_config, dirty=False)
    finally:
        public_config.plugins.on_shutdown()

    public_html = (tmp_path / "public-site" / "index.html").read_text(encoding="utf-8")
    assert "View lecture spec" not in public_html
    public_spec = tmp_path / "public-site" / "specs" / "00-course-introduction" / "index.html"
    assert not public_spec.exists()

    monkeypatch.setenv("COURSEMD_PREVIEW", "1")
    preview_config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "preview-site"))
    preview_config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(preview_config, dirty=False)
    finally:
        preview_config.plugins.on_shutdown()

    preview_html = (tmp_path / "preview-site" / "index.html").read_text(encoding="utf-8")
    assert "View lecture spec" in preview_html
    assert "/specs/00-course-introduction/" in preview_html
    preview_spec = tmp_path / "preview-site" / "specs" / "00-course-introduction" / "index.html"
    assert preview_spec.is_file()
    spec_html = preview_spec.read_text(encoding="utf-8")
    assert 'data-md-type="navigation" hidden' in spec_html
    assert 'data-md-type="toc" hidden' in spec_html
    assert 'data-md-component="header-nav"' in spec_html


def test_coursemd_mkdocs_plugin_renders_instructor_only_blocks_only_in_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "website" / "docs" / "index.md",
        """
        # Home

        Public verification marker.

        {% call instructor_only() %}
        Instructor-only verification marker.
        {% endcall %}
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.delenv("COURSEMD_PREVIEW", raising=False)
    monkeypatch.chdir(tmp_path / "website")

    public_config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "public-site"))
    public_config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(public_config, dirty=False)
    finally:
        public_config.plugins.on_shutdown()

    public_html = (tmp_path / "public-site" / "index.html").read_text(encoding="utf-8")
    assert "Public verification marker." in public_html
    assert "Instructor-only verification marker." not in public_html

    monkeypatch.setenv("COURSEMD_PREVIEW", "1")
    preview_config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "preview-site"))
    preview_config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(preview_config, dirty=False)
    finally:
        preview_config.plugins.on_shutdown()

    preview_html = (tmp_path / "preview-site" / "index.html").read_text(encoding="utf-8")
    assert "Instructor-only verification marker." in preview_html


def test_coursemd_mkdocs_plugin_renders_injected_assignment_includes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "website" / "docs" / "partials" / "note.md",
        """
        Included {{ page.meta.title }}
        """,
    )
    _write_file(
        tmp_path / "assignments" / "hw1.md",
        """
        ---
        title: Homework 1
        kind: homework
        release_date: 2026-01-12
        due_date: 2026-01-16
        due_at: "2026-01-16T23:59:00-05:00"
        points: 100
        ---

        # Homework 1

        {% include "partials/note.md" %}
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    html = (tmp_path / "site" / "assignments" / "hw1" / "index.html").read_text(encoding="utf-8")
    assert "Included Homework 1" in html


def test_coursemd_mkdocs_plugin_uses_configured_urls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "        project_dir: website\n",
            "        project_dir: website\n        assignments_url_path: coursework\n",
        ),
        encoding="utf-8",
    )
    _write_file(
        tmp_path / "assignments" / "hw1.md",
        "\n".join(
            [
                "---",
                "title: Homework 1",
                "kind: homework",
                "release_date: 2026-01-12",
                "due_date: 2026-01-16",
                'due_at: "2026-01-16T23:59:00-05:00"',
                "points: 100",
                "integrations:",
                "  canvas:",
                "    id: 456",
                "---",
                "",
                "# Homework 1",
                "",
                "{{ canvas_submission(456) }}",
                "",
            ]
        ),
    )
    _write_file(
        tmp_path / "quizzes" / "week1.md",
        "\n".join(
            [
                "---",
                "title: Week 1 Reading Quiz",
                "release_date: 2026-01-12",
                'due_at: "2026-01-16T23:59:00-05:00"',
                "integrations:",
                "  canvas:",
                "    id: 987",
                "questions:",
                "  - question_type: multiple_choice",
                "    question_text: What is quality?",
                "    answers:",
                "      - text: Fitness for purpose",
                "        correct: true",
                "      - text: Just test coverage",
                "        correct: false",
                "---",
                "",
                "# Quiz",
                "",
            ]
        ),
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    assert (tmp_path / "site" / "coursework" / "hw1" / "index.html").is_file()
    assignment_html = (tmp_path / "site" / "coursework" / "hw1" / "index.html").read_text(
        encoding="utf-8"
    )
    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "https://canvas.example.edu/courses/12345/assignments/456" in assignment_html
    assert "https://canvas.example.edu/courses/12345/quizzes/987" in index_html
    assert "/coursework/hw1/" in index_html


def test_coursemd_macros_do_not_discover_quizzes_from_docs_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "website" / "docs" / "quizzes" / "week99.md",
        """
        ---
        title: Public Quiz Leak
        release_date: 2026-01-12
        due_at: "2026-01-16T23:59:00-05:00"
        questions:
          - question_type: multiple_choice
            question_text: Should this be public?
            answers:
              - text: No
                correct: true
              - text: Yes
                correct: false
        ---

        # Public Quiz Leak
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Public Quiz Leak" not in index_html


def test_coursemd_mkdocs_plugin_uses_preloaded_quiz_schedule_data(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    plugin = config.plugins["coursemd"]
    plugin.on_config(config)
    (tmp_path / "quizzes" / "week1.md").unlink()
    registry = plugin._macro_registry(config=config, page=None)

    rendered = registry.macros["schedule_table"](plugin.course_data["schedule"])

    assert "Week 1 Reading Quiz" in rendered


def test_coursemd_mkdocs_plugin_discovers_labs_for_schedule_table(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "labs" / "lab1.md",
        """
        ---
        kind: lab
        title: Lab 1
        date: 2026-01-13
        ---

        # Lab 1
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    plugin = config.plugins["coursemd"]
    plugin.on_config(config)
    registry = plugin._macro_registry(config=config, page=None)

    rendered = registry.macros["schedule_table"](plugin.course_data["schedule"])

    assert 'href="/labs/lab1/"' in rendered
    assert "Lab: Lab 1" in rendered


def test_coursemd_mkdocs_plugin_loads_all_yaml_data_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "data" / "resources.yaml",
        """
        message: Extra data works
        """,
    )
    _write_file(
        tmp_path / "website" / "docs" / "index.md",
        """
        # Home

        {{ resources.message }}
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Extra data works" in index_html


def test_coursemd_mkdocs_plugin_exposes_configured_staff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    config_path = tmp_path / ".coursemd.yml"
    config_path.write_text(
        dedent(
            """
        staff:
          - name: Grace Hopper
            role: instructor
            email: grace@example.edu
            website: https://example.edu/grace
            photo: grace.png
          - name: Ada Lovelace
            role: teaching-assistant
            email: ada@example.edu
        """
        )
        + config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_file(
        tmp_path / "website" / "docs" / "index.md",
        """
        # Staff

        ## Staff

        ### Instructors

        <div id="course-instructors">
        {%- set instructors = staff | selectattr("role", "==", "instructor") | list -%}
        {% for instructor in instructors %}
        {{ render_staffer(instructor) }}
        {% endfor %}
        </div>

        {%- set assistants = staff | selectattr("role", "==", "teaching-assistant") | list -%}

        {% if assistants %}

        ### Teaching Assistants

        <div id="course-assistants">
        {% for assistant in assistants %}
        {{ render_staffer(assistant) }}
        {% endfor %}
        </div>
        {% endif %}
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
        plugin = config.plugins["coursemd"]
        assert isinstance(plugin.course_data["staff"][0], StaffMember)
    finally:
        config.plugins.on_shutdown()

    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert 'id="course-instructors"' in index_html
    assert 'id="course-assistants"' in index_html
    assert "Grace Hopper" in index_html
    assert "Ada Lovelace" in index_html
    assert 'src="/assets/images/grace.png"' in index_html
    assert "mailto:grace@example.edu" in index_html
    assert "mailto:ada@example.edu" in index_html
    assert "https://example.edu/grace" in index_html
    assert "staffer-image-placeholder" in index_html


def test_grade_boundaries_table_without_grading_data_returns_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _build_repo_fixture(tmp_path)
    _write_file(
        tmp_path / "website" / "docs" / "index.md",
        """
        # Home

        before
        {{ grade_boundaries_table() }}
        after
        """,
    )
    monkeypatch.setenv("CURRENT_DATE_OVERRIDE", "2026-01-13")
    monkeypatch.chdir(tmp_path / "website")

    config = load_config(config_file="mkdocs.yml", site_dir=str(tmp_path / "site"))
    config.plugins.on_startup(command="build", dirty=False)
    try:
        mkdocs_build(config, dirty=False)
    finally:
        config.plugins.on_shutdown()

    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "before" in index_html
    assert "after" in index_html
