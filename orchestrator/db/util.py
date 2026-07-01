"""Small helpers used at call sites to keep behavior identical across backends.

Two things the database engines used to do for free on PostgreSQL —
UUID generation (`gen_random_uuid()`) and "now" (`NOW()`) — are generated
in application code instead, for both backends. This removes a dependency
on PostgreSQL-only DDL defaults that SQLite has no equivalent for, and
means every INSERT explicitly states the identity/timestamp it wrote
rather than needing a RETURNING round-trip to find out what the database
picked.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_id() -> str:
    """Generate a new primary-key value. Same format on both backends."""
    return str(uuid.uuid4())


def now_iso() -> datetime:
    """Current instant, timezone-aware UTC.

    Bind this directly as a query parameter. asyncpg accepts a `datetime`
    for a TIMESTAMPTZ column natively; the SQLite backend's generic
    argument adapter converts it to ISO-8601 text automatically.
    """
    return datetime.now(timezone.utc)


def ts_or_none(value: object) -> str | None:
    """Render a timestamp value returned from either backend as ISO-8601 text.

    PostgreSQL returns a native `datetime` for uncast timestamp columns;
    SQLite returns the ISO-8601 string it was stored as, unchanged. This
    accepts either so call sites don't need to know which backend is active.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def is_valid_uuid(value: str) -> bool:
    """Validate UUID *format* only — existence/ownership checks happen separately.

    PostgreSQL used to reject a malformed UUID at the `::uuid` cast with
    `InvalidTextRepresentationError`. SQLite stores UUIDs as plain TEXT, so
    an invalid string would otherwise just fail to match any row (a 404)
    instead of being rejected as malformed (a 422). Validating in Python
    keeps that distinction identical on both backends.
    """
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False
