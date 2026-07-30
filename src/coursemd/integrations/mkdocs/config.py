"""MkDocs integration configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from pathlib import Path

    import typer

from coursemd.core.config_helpers import (
    optional_version,
    require_mapping,
    require_string,
    require_url_path,
    resolve_relative_path,
)
from coursemd.core.exceptions import CoursemdValidationError
from coursemd.core.integration_config import (
    IntegrationConfig,
    IntegrationConfigContext,
)
from coursemd.core.loaders.validation import optional_string

INTEGRATION_NAME = "mkdocs"
DEFAULT_INIT_SITE_BASE_URL = "https://example.edu/course"
DEFAULT_INIT_SITE_ASSIGNMENTS_URL_PATH = "assignments"
DEFAULT_ASSIGNMENTS_LABEL = "Assignments"
DEFAULT_INIT_SITE_LABS_URL_PATH = "labs"
DEFAULT_INIT_SITE_RECITATIONS_URL_PATH = "recitations"
DEFAULT_INIT_SITE_PROJECT_DIR = "website"

@dataclass(frozen=True)
class MkdocsIntegrationConfig(IntegrationConfig):
    metavar: ClassVar[str] = INTEGRATION_NAME
    required: ClassVar[bool] = True

    base_url: str
    project_dir: Path
    assignments_url_path: str = DEFAULT_INIT_SITE_ASSIGNMENTS_URL_PATH
    assignments_label: str = DEFAULT_ASSIGNMENTS_LABEL
    labs_url_path: str = DEFAULT_INIT_SITE_LABS_URL_PATH
    recitations_url_path: str = DEFAULT_INIT_SITE_RECITATIONS_URL_PATH
    include_specs: bool = False
    show_unreleased_content: bool = False

    @classmethod
    def parse(
        cls,
        raw_value: Any,
        *,
        context: IntegrationConfigContext,
    ) -> MkdocsIntegrationConfig:
        config_map = require_mapping(raw_value, label=f"integrations.{cls.metavar}")
        optional_version(
            config_map.get("version"),
            label=f"integrations.{cls.metavar}.version",
        )
        include_specs = config_map.get("include_specs", False)
        if not isinstance(include_specs, bool):
            raise CoursemdValidationError(
                f"integrations.{cls.metavar}.include_specs must be a boolean."
            )
        show_unreleased_content = config_map.get("show_unreleased_content", False)
        if not isinstance(show_unreleased_content, bool):
            raise CoursemdValidationError(
                f"integrations.{cls.metavar}.show_unreleased_content must be a boolean."
            )
        return cls(
            base_url=require_string(
                config_map.get("base_url"),
                label=f"integrations.{cls.metavar}.base_url",
            ),
            project_dir=resolve_relative_path(
                context.repo_root,
                config_map.get("project_dir", DEFAULT_INIT_SITE_PROJECT_DIR),
                label=f"integrations.{cls.metavar}.project_dir",
            ),
            assignments_url_path=require_url_path(
                config_map.get(
                    "assignments_url_path",
                    DEFAULT_INIT_SITE_ASSIGNMENTS_URL_PATH,
                ),
                label=f"integrations.{cls.metavar}.assignments_url_path",
            ),
            assignments_label=(
                optional_string(config_map.get("assignments_label")) or DEFAULT_ASSIGNMENTS_LABEL
            ),
            labs_url_path=require_url_path(
                config_map.get(
                    "labs_url_path",
                    DEFAULT_INIT_SITE_LABS_URL_PATH,
                ),
                label=f"integrations.{cls.metavar}.labs_url_path",
            ),
            recitations_url_path=require_url_path(
                config_map.get(
                    "recitations_url_path",
                    DEFAULT_INIT_SITE_RECITATIONS_URL_PATH,
                ),
                label=f"integrations.{cls.metavar}.recitations_url_path",
            ),
            include_specs=include_specs,
            show_unreleased_content=show_unreleased_content,
        )

    @classmethod
    def register_cli(cls, app: typer.Typer) -> None:
        del cls
        from coursemd.integrations.mkdocs.cli import register_site_cli  # noqa: PLC0415

        register_site_cli(app)


__all__ = [
    "MkdocsIntegrationConfig",
]
