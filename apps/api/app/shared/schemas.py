"""Response shapes shared across modules.

Only genuinely cross-cutting envelopes belong here. A module importing another
module's schemas is a layering violation waiting to become a circular import;
the pagination envelope is common to every list endpoint in the product, so it
lives one level down instead of in whichever module happened to need it first.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Pagination(BaseModel):
    next_cursor: str | None = Field(
        default=None,
        description="Opaque. Pass it back as `cursor` for the next page; never parse it.",
    )
    has_more: bool
    limit: int


class Page[T](BaseModel):
    """Cursor-paginated results, newest first.

    Cursor rather than offset because every list in this system reads a table
    that is continuously inserted into, and offset pagination silently skips and
    duplicates rows under concurrent writes (docs/07-api-design.md §2).
    """

    data: list[T]
    pagination: Pagination
