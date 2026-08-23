"""Recitation models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast

from coursemd.core.exceptions import validation_error_boundary
from coursemd.core.loaders.dates import parse_date
from coursemd.core.loaders.markdown import load_markdown_post
from coursemd.core.loaders.validation import optional_string, require_date, require_non_empty_string
from coursemd.core.models.course_event import CourseEvent

if TYPE_CHECKING:
    import datetime as dt
    from pathlib import Path

    from coursemd.core.config import CourseConfig


DEFAULT_RECITATIONS_URL_PATH = "recitations"


def _parse_card(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return optional presentation metadata for a recitation."""
    card_raw = metadata.get("card")
    if card_raw is None:
        return {}
    if not isinstance(card_raw, dict):
        raise TypeError("'card' must be an object/map.")
    return dict(cast("dict[str, Any]", card_raw))


@dataclass(frozen=True)
class Recitation:
    """A recitation session page specification."""

    source_file: Path
    title: str
    date: dt.date
    link: str
    description: str | None = None
    card: dict[str, Any] = field(default_factory=dict)
    reveal_date: dt.date | None = None

    @property
    def name(self) -> str:
        return self.title

    def with_recitations_url_path(self, recitations_url_path: str) -> Recitation:
        return replace(
            self,
            link=f"/{recitations_url_path.strip('/')}/{self.source_file.stem}/",
        )

    def as_course_event(self) -> CourseEvent:
        """Return the recitation as an event for inclusion in a course schedule."""
        return CourseEvent(
            kind="recitation",
            date=self.date,
            title=self.title,
            link=self.link,
            reveal_date=self.reveal_date,
        )

    @classmethod
    def load(cls, filename: Path) -> Recitation | None:
        """Load a single recitation from a Markdown file, or None if kind != 'recitation'."""

        with validation_error_boundary(filename):
            post = load_markdown_post(filename)
            metadata: dict[str, Any] = post.metadata

            if str(metadata.get("kind", "")).strip().lower() != "recitation":
                return None

            title = require_non_empty_string(metadata.get("title"), "title")
            date = require_date(metadata.get("date"), "date")
            description = optional_string(metadata.get("description"))
            reveal_date = parse_date(metadata.get("reveal_date") or metadata.get("release_date"))

            return cls(
                source_file=filename,
                title=title,
                date=date,
                link=f"/{DEFAULT_RECITATIONS_URL_PATH}/{filename.stem}/",
                description=description,
                card=_parse_card(metadata),
                reveal_date=reveal_date,
            )

    @classmethod
    def find(
        cls,
        config: CourseConfig,
        path: Path | None = None,
    ) -> list[Recitation]:
        """Discover and load all recitations from a directory."""
        directory = path if path is not None else config.paths.recitations_dir
        if not directory.is_dir():
            return []
        files = sorted(p for p in directory.glob("*.md") if p.name != "index.md")
        recitations = [recitation for f in files if (recitation := cls.load(f)) is not None]
        return sorted(recitations, key=lambda recitation: recitation.date)
