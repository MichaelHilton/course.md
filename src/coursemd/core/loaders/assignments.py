"""Assignment loading helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_ASSIGNMENTS_URL_PATH = "assignments"


def assignment_link_for(
    source_file: Path,
    *,
    assignment_url_path: str = DEFAULT_ASSIGNMENTS_URL_PATH,
) -> str:
    """Build the published site path for an assignment page."""

    slug = source_file.parent.name if source_file.name == "index.md" else source_file.stem
    return f"/{assignment_url_path.strip('/')}/{slug}/"


@dataclass(frozen=True)
class AssignmentSource:
    """A single assignment's markdown files: its record page plus any satellite pages.

    An assignment is either a single top-level ``<slug>.md`` file, or a
    top-level directory containing an ``index.md``. In the directory case,
    ``index.md`` carries the assignment front matter (title/release_date/
    due_date/etc.) and every other ``*.md`` file found anywhere under the
    directory is a satellite content page nested under that assignment.
    """

    record_file: Path
    satellite_files: list[Path] = field(default_factory=list)

    @property
    def all_files(self) -> list[Path]:
        return [self.record_file, *self.satellite_files]


def discover_assignment_sources(assignments_dir: Path) -> list[AssignmentSource]:
    """Find assignment sources directly inside ``assignments_dir``.

    Does not recurse into subdirectories other than to look for satellite
    pages beneath a discovered ``index.md``; this mirrors how labs and
    recitations are discovered, one level deeper for multi-page assignments.
    """

    if not assignments_dir.is_dir():
        return []

    sources: list[AssignmentSource] = []
    for entry in sorted(assignments_dir.iterdir()):
        if entry.is_dir():
            index_file = entry / "index.md"
            if not index_file.is_file():
                continue
            satellites = sorted(
                path for path in entry.rglob("*.md") if path != index_file
            )
            sources.append(AssignmentSource(record_file=index_file, satellite_files=satellites))
        elif entry.suffix == ".md" and entry.name != "index.md":
            sources.append(AssignmentSource(record_file=entry))
    return sources
