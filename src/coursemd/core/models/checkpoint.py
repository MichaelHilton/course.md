"""Assignment checkpoint specification and loading logic."""

from __future__ import annotations

__all__ = ("AssignmentCheckpoint",)

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from coursemd.core.loaders.validation import (
    optional_string,
    require_date,
    require_due_at,
    require_non_empty_string,
)

if TYPE_CHECKING:
    import datetime as dt


@dataclass(frozen=True)
class AssignmentCheckpoint:
    """A dated checkpoint associated with an assignment."""

    date: dt.date
    title: str
    due_at: dt.datetime
    description: str | None = None
    doc_anchor: str | None = None
    link: str | None = None

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        index: int,
    ) -> AssignmentCheckpoint:
        checkpoint_date = require_date(value.get("date"), f"checkpoints[{index}].date")
        checkpoint_title = require_non_empty_string(
            value.get("title"),
            f"checkpoints[{index}].title",
        )
        checkpoint_due_at_raw = value.get("due_at")
        if checkpoint_due_at_raw is None:
            raise ValueError(f"'checkpoints[{index}].due_at' is required.")
        checkpoint_due_at = require_due_at(
            checkpoint_due_at_raw,
            f"checkpoints[{index}]",
        )

        return cls(
            date=checkpoint_date,
            title=checkpoint_title,
            description=optional_string(value.get("description")),
            due_at=checkpoint_due_at,
            doc_anchor=optional_string(value.get("doc_anchor")),
            link=optional_string(value.get("link")),
        )

    @classmethod
    def from_list(
        cls,
        values: list[dict[str, Any]] | None,
        *,
        release_date: dt.date,
        due_date: dt.date,
    ) -> list[AssignmentCheckpoint]:
        if values is None:
            return []

        checkpoints: list[AssignmentCheckpoint] = []
        previous_date: dt.date | None = None

        for index, item in enumerate(values):
            if not isinstance(item, dict):
                raise TypeError(f"checkpoints[{index}] must be an object.")
            checkpoint = cls.from_dict(
                cast("dict[str, Any]", item),
                index=index,
            )
            if checkpoint.date < release_date or checkpoint.date > due_date:
                raise ValueError(
                    f"checkpoints[{index}].date must fall between "
                    "'release_date' and 'due_date'."
                )
            if checkpoint.due_at.date() != checkpoint.date:
                raise ValueError(
                    f"checkpoints[{index}].due_at must fall on "
                    f"the same calendar date as checkpoints[{index}].date."
                )
            if previous_date is not None and checkpoint.date < previous_date:
                raise ValueError("checkpoints must be ordered by ascending date.")

            checkpoints.append(checkpoint)
            previous_date = checkpoint.date

        return checkpoints


def _parse_checkpoints(
    value: Any,
    *,
    release_date: dt.date,
    due_date: dt.date,
) -> list[AssignmentCheckpoint]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("'checkpoints' must be a list of objects.")
    return AssignmentCheckpoint.from_list(
        cast("list[dict[str, Any]]", value),
        release_date=release_date,
        due_date=due_date,
    )
