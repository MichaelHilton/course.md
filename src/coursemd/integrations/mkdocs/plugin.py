"""MkDocs backend adapter for coursemd course repositories."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import frontmatter
from jinja2 import Environment, FileSystemLoader, select_autoescape
from mkdocs.config import config_options
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import File, Files

if TYPE_CHECKING:
    import datetime as dt

    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.nav import Navigation

from coursemd.core.config import CourseConfig
from coursemd.core.loaders.assignments import discover_assignment_sources
from coursemd.core.loaders.dates import parse_date
from coursemd.core.models.repository import CourseRepository
from coursemd.core.utils import current_date, set_course_timezone
from coursemd.integrations.canvas.config import CanvasConfig
from coursemd.integrations.canvas.schedule import inject_quiz_links
from coursemd.integrations.mkdocs.config import MkdocsIntegrationConfig
from coursemd.integrations.mkdocs.macros import define_env

MacroFunction = Callable[..., Any]

_ASSIGNMENTS_OVERVIEW_TEMPLATE = """\
---
title: Assignments
hide:
- navigation
- toc
---

<table style="width:100%; font-size:0.95rem">
<thead>
<tr>
  <th>Assignment</th>
  <th style="text-align:center">Released</th>
  <th style="text-align:center">Due</th>
</tr>
</thead>
<tbody>
{% for hw in released_assignments(schedule) %}
<tr>
  <td><a href="{{ hw.link }}">{{ hw.title }}</a></td>
  <td style="text-align:center">{{ hw.release_date.strftime("%b %-d, %Y") }}</td>
  <td style="text-align:center">{{ hw.due_date.strftime("%b %-d, %Y") }} @ 11:59 pm ET</td>
</tr>
{% endfor %}
</tbody>
</table>
"""

_LABS_OVERVIEW_TEMPLATE = """\
---
title: Labs
hide:
- navigation
- toc
---

<table style="width:100%; font-size:0.95rem">
<thead>
<tr>
  <th>Lab</th>
  <th style="text-align:center">Date</th>
</tr>
</thead>
<tbody>
{% for lab in released_labs(schedule) %}
<tr>
  <td><a href="{{ lab.link }}">{{ lab.title }}</a></td>
  <td style="text-align:center">{{ lab.date.strftime("%b %-d, %Y") }}</td>
</tr>
{% endfor %}
</tbody>
</table>
"""

_RECITATIONS_OVERVIEW_TEMPLATE = """\
---
title: Recitations
hide:
- navigation
- toc
---

<table style="width:100%; font-size:0.95rem">
<thead>
<tr>
  <th>Recitation</th>
  <th style="text-align:center">Date</th>
</tr>
</thead>
<tbody>
{% for recitation in released_recitations(schedule) %}
<tr>
  <td><a href="{{ recitation.source_file.stem }}">{{ recitation.title }}</a></td>
  <td style="text-align:center">{{ recitation.date.strftime("%b %-d, %Y") }}</td>
</tr>
{% endfor %}
</tbody>
</table>
"""


@dataclass
class _MacroRegistry:
    """Small compatibility layer for functions written for mkdocs-macros."""

    conf: dict[str, Any]
    variables: dict[str, Any]
    macros: dict[str, MacroFunction] = field(default_factory=dict)

    def macro(self, func: MacroFunction) -> MacroFunction:
        self.macros[func.__name__] = func
        return func


class CoursemdPlugin(BasePlugin):
    """MkDocs plugin that adapts a coursemd repository into a MkDocs site."""

    config_scheme = (
        ("config_file", config_options.Optional(config_options.Type(str))),
        ("generate_nav", config_options.Type(bool, default=True)),
        ("assignment_card_template", config_options.Optional(config_options.Type(str))),
    )

    course_config: CourseConfig
    mkdocs_integration: MkdocsIntegrationConfig
    course_repository: CourseRepository
    course_data: dict[str, Any]
    current_date: dt.date
    in_preview: bool
    preview_spec_pages: dict[dt.date, Path]
    removed_files: set[str]
    macro_registry: _MacroRegistry

    def on_startup(self, command: str, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        self.in_preview = command == "serve"
        self.current_date = current_date()
        self.removed_files = set()

    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        config_path = self._resolve_coursemd_config_path(config)
        self.course_config = CourseConfig.load(start_dir=config_path.parent)
        self.mkdocs_integration = MkdocsIntegrationConfig.require(self.course_config)
        set_course_timezone(self.course_config.timezone)
        self.course_repository = self._load_course_repository()
        self.course_config = self.course_repository.config
        self.in_preview = getattr(self, "in_preview", False) or self._env_truthy("COURSEMD_PREVIEW")
        self.preview_spec_pages = (
            self._load_preview_spec_pages()
            if self.in_preview and self.mkdocs_integration.include_specs
            else {}
        )
        self.course_data = self._build_course_data()
        self.current_date = current_date()
        self.removed_files = getattr(self, "removed_files", set())

        extra = {
            **dict(config.get("extra", {})),
            "canvas_course_id": self.course_data.get("schedule", {})
            .get("course", {})
            .get("canvas_course_id"),
        }
        canvas_config = self.course_repository.get_integration("canvas", CanvasConfig)
        if canvas_config is not None:
            extra["canvas_base_url"] = canvas_config.base_url
        extra["course_timezone"] = self.course_repository.timezone
        config["extra"] = extra

        self._configure_watch(config)
        if self.config.get("generate_nav", True):
            config["nav"] = self._generated_nav(config.get("nav") or [])
        return config

    def on_files(self, files: Files, *, config: MkDocsConfig, **kwargs: Any) -> Files:  # noqa: ARG002
        self._add_generated_pages(files, config)
        if not self.in_preview:
            for file in list(files.documentation_pages()):
                metadata = self._load_file_metadata(file)
                if self._should_remove_file(metadata):
                    print(f"Removing file: {file.src_path}")
                    self.removed_files.add(file.src_uri)
                    files.remove(file)
        return files

    def on_nav(self, nav: Navigation, **kwargs: Any) -> Navigation:  # noqa: ARG002
        if not self.in_preview and self.removed_files:
            nav.items = list(self._filter_nav_items(nav.items))
        self._inject_section_urls(nav.items)
        return nav

    def on_page_markdown(
        self,
        markdown: str,
        *,
        page: Any,
        config: MkDocsConfig,
        files: Files,  # noqa: ARG002
    ) -> str:
        markdown = self._normalize_generated_frontmatter(markdown, page)
        registry = self._macro_registry(config=config, page=page)
        template_env = Environment(
            loader=FileSystemLoader(str(config.docs_dir)),
            autoescape=select_autoescape(),
        )
        template_env.globals.update(registry.variables)
        template_env.globals.update(registry.macros)
        markdown = self._prepend_assignment_card(markdown, page, template_env)
        return template_env.from_string(markdown).render()

    def on_env(self, env: Any, *, config: MkDocsConfig, files: Files) -> Any:  # noqa: ARG002
        registry = self._macro_registry(config=config, page=None)
        env.globals.update(registry.variables)
        env.globals.update(registry.macros)
        return env

    def _resolve_coursemd_config_path(self, config: MkDocsConfig) -> Path:
        configured = self.config.get("config_file")
        if configured:
            config_dir = Path(config.config_file_path).parent
            path = Path(configured)
            return path if path.is_absolute() else (config_dir / path).resolve()
        return Path(config.config_file_path).parent

    def _load_course_repository(self) -> CourseRepository:
        return CourseRepository.build(self.course_config)

    def _build_course_data(self) -> dict[str, Any]:
        course_data = dict(self.course_repository.data)
        if self.course_repository.staff:
            course_data["staff"] = self.course_repository.staff
        schedule_config = self.course_repository.config.schedule
        if schedule_config is not None:
            schedule = course_data.get("schedule")
            schedule_data = dict(schedule) if isinstance(schedule, dict) else {}
            course = dict(schedule_data.get("course", {}))
            course["start_date"] = schedule_config.start_date
            course["end_date"] = schedule_config.end_date
            schedule_data["course"] = course
            labs = [
                lab.with_labs_url_path(self.mkdocs_integration.labs_url_path)
                for lab in self.course_repository.labs
            ]
            recitations = [
                recitation.with_recitations_url_path(self.mkdocs_integration.recitations_url_path)
                for recitation in self.course_repository.recitations
            ]
            schedule_data["events"] = [
                *schedule_config.events,
                *(lab.as_course_event() for lab in labs),
                *(recitation.as_course_event() for recitation in recitations),
            ]
            schedule_data["breaks"] = schedule_config.breaks
            schedule_data["meeting_days"] = schedule_config.meeting_days
            schedule_data["show_unreleased_content"] = self.mkdocs_integration.show_unreleased_content
            canvas_cfg = self.course_repository.get_integration("canvas", CanvasConfig)
            canvas_course_id = schedule_data.get("course", {}).get("canvas_course_id")

            schedule_data["assignments"] = [
                assignment.with_assignment_url_path(self.mkdocs_integration.assignments_url_path)
                for assignment in self.course_repository.assignments
            ]
            schedule_data["labs"] = labs
            schedule_data["recitations"] = recitations
            quizzes = self.course_repository.quizzes
            if canvas_cfg is not None and canvas_course_id is not None:
                quizzes = inject_quiz_links(quizzes, canvas_cfg.base_url, canvas_course_id)
            schedule_data["quizzes"] = quizzes
            if self.preview_spec_pages:
                schedule_data["preview_spec_links"] = {
                    date: f"/specs/{path.stem}/"
                    for date, path in self.preview_spec_pages.items()
                }
            course_data["schedule"] = schedule_data
        else:
            course_data.pop("schedule", None)
        return course_data

    def _configure_watch(self, config: MkDocsConfig) -> None:
        watched = list(config.get("watch") or [])
        for path in (
            self.course_repository.paths.data_dir,
            self.course_repository.paths.assignments_dir,
            self.course_repository.paths.quizzes_dir,
            self.course_repository.paths.labs_dir,
            self.course_repository.paths.recitations_dir,
            self.course_repository.paths.specs_dir,
        ):
            if not path.exists():
                continue
            text = str(path)
            if text not in watched:
                watched.append(text)
        config["watch"] = watched

    def _generated_nav(self, nav: list[Any]) -> list[Any]:
        assignments_label = self.mkdocs_integration.assignments_label
        assignment_nav = self._nav_items_for_assignments_dir()
        if self._should_generate_assignments_index():
            overview_uri = f"{self.mkdocs_integration.assignments_url_path}/index.md"
            assignment_nav = [overview_uri, *assignment_nav]
        lab_nav = self._nav_items_for_markdown_dir(
            self.course_repository.paths.labs_dir,
            base_uri=self.mkdocs_integration.labs_url_path,
            include_index=True,
        )
        if self._should_generate_labs_index():
            lab_overview_uri = f"{self.mkdocs_integration.labs_url_path}/index.md"
            lab_nav = [lab_overview_uri, *lab_nav]
        recitation_nav = self._nav_items_for_markdown_dir(
            self.course_repository.paths.recitations_dir,
            base_uri=self.mkdocs_integration.recitations_url_path,
            include_index=True,
        )
        if self._should_generate_recitations_index():
            recitation_overview_uri = f"{self.mkdocs_integration.recitations_url_path}/index.md"
            recitation_nav = [recitation_overview_uri, *recitation_nav]

        output: list[Any] = []
        saw_assignments = False
        saw_labs = False
        saw_recitations = False
        for item in nav:
            key = self._nav_key(item)
            if key == assignments_label:
                saw_assignments = True
                if assignment_nav:
                    output.append({assignments_label: assignment_nav})
                continue
            if key == "Labs":
                saw_labs = True
                if lab_nav:
                    output.append({"Labs": lab_nav})
                continue
            if key == "Recitations":
                saw_recitations = True
                if recitation_nav:
                    output.append({"Recitations": recitation_nav})
                continue
            output.append(item)

        if assignment_nav and not saw_assignments:
            output.append({assignments_label: assignment_nav})
        if lab_nav and not saw_labs:
            output.append({"Labs": lab_nav})
        if recitation_nav and not saw_recitations:
            output.append({"Recitations": recitation_nav})
        return output

    def _nav_items_for_markdown_dir(
        self,
        directory: Path,
        *,
        base_uri: str,
        include_index: bool,
    ) -> list[Any]:
        if not directory.is_dir():
            return []
        paths = sorted(directory.glob("*.md"))
        if not include_index:
            paths = [path for path in paths if path.name != "index.md"]
        else:
            paths = sorted(paths, key=lambda path: (path.name != "index.md", path.name))
        items: list[Any] = []
        for path in paths:
            metadata = self._load_markdown_metadata(path)
            if not self.in_preview and self._should_remove_file(metadata):
                continue
            uri = f"{base_uri}/{path.name}"
            if path.name == "index.md":
                # Bare path lets MkDocs/Material recognise this as the section index page
                items.append(uri)
            else:
                title = str(metadata.get("title") or path.stem).strip()
                items.append({title: uri})
        return items

    def _nav_items_for_assignments_dir(self) -> list[Any]:
        """Build nav entries for assignments_dir, one level deeper than labs/recitations.

        A top-level ``<slug>.md`` file is a single-page assignment, listed like any
        other markdown-dir entry. A top-level directory with an ``index.md`` is a
        multi-page assignment: its ``index.md`` becomes the section's index page and
        every other ``*.md`` file found under that directory becomes a nested child.
        """
        directory = self.course_repository.paths.assignments_dir
        if not directory.is_dir():
            return []
        base_uri = self.mkdocs_integration.assignments_url_path
        items: list[Any] = []
        for source in discover_assignment_sources(directory):
            index_metadata = self._load_markdown_metadata(source.record_file)
            if not self.in_preview and self._should_remove_file(index_metadata):
                continue
            index_uri = self._assignment_uri(source.record_file, directory, base_uri)
            if source.record_file.name != "index.md":
                title = str(index_metadata.get("title") or source.record_file.stem).strip()
                items.append({title: index_uri})
                continue
            if not source.satellite_files:
                items.append(index_uri)
                continue
            group_title = str(
                index_metadata.get("title") or source.record_file.parent.name
            ).strip()
            children: list[Any] = [index_uri]
            for satellite in self._sorted_assignment_satellites(source.satellite_files):
                satellite_metadata = self._load_markdown_metadata(satellite)
                if not self.in_preview and self._should_remove_file(satellite_metadata):
                    continue
                title = str(satellite_metadata.get("title") or satellite.stem).strip()
                children.append({title: self._assignment_uri(satellite, directory, base_uri)})
            items.append({group_title: children})
        return items

    def _sorted_assignment_satellites(self, paths: list[Path]) -> list[Path]:
        def sort_key(path: Path) -> tuple[int, str]:
            order = self._load_markdown_metadata(path).get("nav_order")
            return (order if isinstance(order, int) else 1_000_000, path.name)

        return sorted(paths, key=sort_key)

    def _assignment_uri(self, path: Path, directory: Path, base_uri: str) -> str:
        return f"{base_uri}/{path.relative_to(directory).as_posix()}"

    def _should_generate_assignments_index(self) -> bool:
        assignments_dir = self.course_repository.paths.assignments_dir
        return assignments_dir.is_dir() and not (assignments_dir / "index.md").exists()

    def _should_generate_labs_index(self) -> bool:
        labs_dir = self.course_repository.paths.labs_dir
        return labs_dir.is_dir() and not (labs_dir / "index.md").exists()

    def _should_generate_recitations_index(self) -> bool:
        recitations_dir = self.course_repository.paths.recitations_dir
        return recitations_dir.is_dir() and not (recitations_dir / "index.md").exists()

    def _add_generated_assignment_pages(self, files: Files, config: MkDocsConfig) -> None:
        directory = self.course_repository.paths.assignments_dir
        if not directory.is_dir():
            return
        base_uri = self.mkdocs_integration.assignments_url_path

        def register(path: Path) -> None:
            src_uri = f"{base_uri}/{path.relative_to(directory).as_posix()}"
            if files.get_file_from_path(src_uri) is not None:
                return
            files.append(File.generated(config, src_uri, abs_src_path=str(path)))

        for source in discover_assignment_sources(directory):
            for path in source.all_files:
                register(path)
            if source.record_file.name == "index.md":
                project_dir = source.record_file.parent
                for asset in project_dir.rglob("*"):
                    if asset.is_file() and asset.suffix != ".md":
                        register(asset)

        top_level_index = directory / "index.md"
        if top_level_index.is_file():
            register(top_level_index)

    def _add_generated_pages(self, files: Files, config: MkDocsConfig) -> None:
        self._add_generated_assignment_pages(files, config)
        for directory, base_uri, include_index in (
            (
                self.course_repository.paths.labs_dir,
                self.mkdocs_integration.labs_url_path,
                True,
            ),
            (
                self.course_repository.paths.recitations_dir,
                self.mkdocs_integration.recitations_url_path,
                True,
            ),
        ):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                if not include_index and path.name == "index.md":
                    continue
                src_uri = f"{base_uri}/{path.name}"
                if files.get_file_from_path(src_uri) is not None:
                    continue
                files.append(File.generated(config, src_uri, abs_src_path=str(path)))

        if self.in_preview:
            for path in self.preview_spec_pages.values():
                src_uri = f"specs/{path.name}"
                if files.get_file_from_path(src_uri) is None:
                    files.append(File.generated(config, src_uri, abs_src_path=str(path)))

        if self._should_generate_assignments_index():
            src_uri = f"{self.mkdocs_integration.assignments_url_path}/index.md"
            if files.get_file_from_path(src_uri) is None:
                overview_content = _ASSIGNMENTS_OVERVIEW_TEMPLATE.replace(
                    "title: Assignments",
                    f"title: {self.mkdocs_integration.assignments_label}",
                )
                files.append(
                    File.generated(config, src_uri, content=overview_content),
                )

        if self._should_generate_labs_index():
            src_uri = f"{self.mkdocs_integration.labs_url_path}/index.md"
            if files.get_file_from_path(src_uri) is None:
                files.append(
                    File.generated(config, src_uri, content=_LABS_OVERVIEW_TEMPLATE),
                )

        if self._should_generate_recitations_index():
            src_uri = f"{self.mkdocs_integration.recitations_url_path}/index.md"
            if files.get_file_from_path(src_uri) is None:
                files.append(
                    File.generated(config, src_uri, content=_RECITATIONS_OVERVIEW_TEMPLATE),
                )

    def _macro_registry(self, *, config: MkDocsConfig, page: Any | None) -> _MacroRegistry:
        variables = {
            **self.course_data,
            "coursemd_preview": self.in_preview,
        }
        if page is not None:
            variables["page"] = page

        registry = _MacroRegistry(
            conf={
                "docs_dir": str(config.docs_dir),
                "extra": dict(config.get("extra", {})),
            },
            variables=variables,
        )
        define_env(registry)
        return registry

    def _load_preview_spec_pages(self) -> dict[dt.date, Path]:
        """Find dated lecture specs that should be visible only in previews."""
        specs_dir = self.course_repository.paths.specs_dir
        if not specs_dir.is_dir():
            return {}

        pages: dict[dt.date, Path] = {}
        for path in sorted(specs_dir.glob("*.md")):
            metadata = self._load_markdown_metadata(path)
            if metadata.get("kind") != "lecture_spec":
                continue
            date = parse_date(metadata.get("date"))
            if date is not None:
                pages[date] = path
        return pages

    def _load_file_metadata(self, file: File) -> dict[str, Any]:
        if not file.abs_src_path:
            return {}
        path = Path(file.abs_src_path)
        return self._assignment_release_metadata(path, self._load_markdown_metadata(path))

    def _assignment_release_metadata(self, path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """Satellite assignment pages inherit release gating from their project's index.md.

        A satellite page (e.g. ``assignments/P3/1_checkpoint.md``) rarely declares its
        own ``release_date``/``reveal_date``/``draft``, so without this it would stay
        reachable (and appear in search) even while its project's index page is hidden.
        """
        if metadata.get("draft") or metadata.get("reveal_date") or metadata.get("release_date"):
            return metadata
        assignments_dir = self.course_repository.paths.assignments_dir
        try:
            relative = path.relative_to(assignments_dir)
        except ValueError:
            return metadata
        if len(relative.parts) < 2:
            return metadata
        index_file = assignments_dir / relative.parts[0] / "index.md"
        if index_file.is_file() and index_file != path:
            return self._load_markdown_metadata(index_file)
        return metadata

    def _load_markdown_metadata(self, path: Path) -> dict[str, Any]:
        try:
            return cast("dict[str, Any]", frontmatter.load(path).metadata)
        except Exception:  # noqa: BLE001
            return {}

    def _is_assignment_page(self, page: Any) -> bool:
        prefix = self.mkdocs_integration.assignments_url_path.strip("/") + "/"
        return page.file.src_uri.startswith(prefix)

    def _normalize_generated_frontmatter(self, markdown: str, page: Any) -> str:
        if not markdown.startswith("---"):
            return markdown
        try:
            post = frontmatter.loads(markdown)
        except Exception:  # noqa: BLE001
            return markdown
        if post.metadata:
            page.meta.update(post.metadata)
        return cast("str", post.content)

    def _prepend_assignment_card(self, markdown: str, page: Any, template_env: Environment) -> str:
        """Render the configured card before each assignment page's Markdown."""
        template_path = self.config.get("assignment_card_template")
        if not template_path or not self._is_assignment_page(page):
            return markdown

        card = page.meta.get("card")
        if not isinstance(card, dict):
            return markdown

        template = template_env.get_template(str(template_path))
        return template.render(assignment=page.meta, card=card) + "\n\n" + markdown

    def _should_remove_file(self, metadata: dict[str, Any]) -> bool:
        if metadata.get("draft"):
            return True

        if self.mkdocs_integration.show_unreleased_content:
            return False

        check_date = parse_date(metadata.get("reveal_date") or metadata.get("release_date"))
        return check_date is not None and check_date > self.current_date

    def _filter_nav_items(self, items: Any) -> Any:
        for item in items:
            if hasattr(item, "url") and item.url in self.removed_files:
                continue
            if hasattr(item, "children") and item.children:
                filtered_children = list(self._filter_nav_items(item.children))
                if filtered_children:
                    item.children = filtered_children
                    yield item
            else:
                yield item

    def _inject_section_urls(self, items: Any) -> None:
        """Set url on Section objects whose first child is an index page.

        MkDocs Section has no url attribute. Templates that access nav_item.url
        on a section get Jinja2 Undefined, which the url filter renders as ".".
        Setting url explicitly lets any template (including custom overrides)
        resolve the correct link for sections that have an index page.
        """
        for item in items:
            if item.is_section:
                children = getattr(item, "children", [])
                if children and children[0].is_page and children[0].is_index:
                    item.url = children[0].url
                self._inject_section_urls(children)

    def _nav_key(self, item: Any) -> str | None:
        if isinstance(item, dict) and len(item) == 1:
            return cast("str", next(iter(item)))
        return None

    def _env_truthy(self, name: str) -> bool:
        return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
