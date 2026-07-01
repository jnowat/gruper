"""Thin façade over `orchestrator/db/` preserving the pre-WP-30 public API.

`main.py`, `dispatcher.py`, the routers, and the WS handlers all import
`init_db` / `close_db` / `get_pool` / `run_migrations` / `append_event`
from this module. Keeping those names and signatures stable here means
none of those call sites needed to change import paths when the SQLite
backend was introduced — only the SQL text and a handful of call sites
that relied on PostgreSQL-only behavior (DB-generated UUIDs/timestamps,
`InvalidTextRepresentationError`) needed updates.
"""

from __future__ import annotations

from .db import Database, connect_db, get_db, close_db as _close_db
from .db.migrate import run_migrations
from .db.util import new_id, now_iso

__all__ = ["init_db", "close_db", "get_pool", "run_migrations", "append_event"]


async def init_db(url: str) -> Database:
    return await connect_db(url)


async def close_db() -> None:
    await _close_db()


def get_pool() -> Database:
    """Named get_pool() for historical/API-stability reasons — returns the
    active Database handle (PostgreSQL pool or SQLite connection wrapper),
    not literally a connection pool on the SQLite path."""
    return get_db()


async def append_event(
    db: Database,
    *,
    actor_id: str,
    action: str,
    subject_id: str,
    secondary_subject_id: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Append an audit event and return its UUID string."""
    event_id = new_id()
    await db.execute(
        """
        INSERT INTO events (id, ts, actor_id, action, subject_id, secondary_subject_id, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        event_id,
        now_iso(),
        actor_id,
        action,
        subject_id,
        secondary_subject_id,
        metadata,
    )
    return event_id
