"""Gradescope integration configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from coursemd.core.config_helpers import (
    optional_version,
    require_mapping,
    require_string,
    require_text,
)
from coursemd.core.integration_config import (
    IntegrationConfig,
    IntegrationConfigContext,
)

INTEGRATION_NAME = "gradescope"
DEFAULT_GRADESCOPE_BASE_URL = "https://www.gradescope.com"

@dataclass(frozen=True)
class GradescopeConfig(IntegrationConfig):
    metavar: ClassVar[str] = INTEGRATION_NAME

    base_url: str
    course_id: str

    @classmethod
    def parse(cls, raw_value: Any, *, context: IntegrationConfigContext) -> GradescopeConfig:
        del context
        config_map = require_mapping(raw_value, label=f"integrations.{cls.metavar}")
        optional_version(
            config_map.get("version"),
            label=f"integrations.{cls.metavar}.version",
        )
        return cls(
            base_url=require_string(
                config_map.get("base_url", DEFAULT_GRADESCOPE_BASE_URL),
                label=f"integrations.{cls.metavar}.base_url",
            ),
            course_id=require_text(
                config_map.get("course_id"),
                label=f"integrations.{cls.metavar}.course_id",
            ),
        )


__all__ = [
    "DEFAULT_GRADESCOPE_BASE_URL",
    "GradescopeConfig",
]
