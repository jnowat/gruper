"""Backend selection: parse `DATABASE_URL`'s scheme and connect the right driver.

`sqlite://` (or a bare filesystem path) selects SQLite — the desktop
default. `postgresql://` / `postgres://` selects PostgreSQL — the
server/advanced tier. This is the only place in the orchestrator that
needs to know both backends exist; everything downstream talks to the
`Database` interface.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from .base import Database
from .postgres import PostgresDatabase
from .sqlite import SQLiteDatabase

logger = logging.getLogger(__name__)

_db: Database | None = None


def _sqlite_path_from_url(url: str) -> str:
    """Extract a filesystem path from a `sqlite:///relative/or/absolute.db` URL.

    `sqlite:///orchestrator.db` -> `orchestrator.db` (relative to CWD)
    `sqlite:////abs/path.db`    -> `/abs/path.db` (absolute)
    """
    parsed = urlparse(url)
    path = parsed.path
    # urlparse keeps a leading "/" for sqlite:///relative -> "/relative";
    # a genuinely absolute path arrives as "//abs/path" (four slashes total
    # after the scheme, and urlparse leaves a DOUBLE leading slash in
    # .path). Strip all leading slashes and re-add exactly one for the
    # absolute case so we never return a doubled "//abs/path".
    if url.startswith("sqlite:////"):
        return "/" + path.lstrip("/")
    return path.lstrip("/")


async def connect_db(url: str) -> Database:
    """Connect to whichever backend `url`'s scheme selects."""
    global _db
    scheme = urlparse(url).scheme
    if scheme in ("postgresql", "postgres"):
        logger.info("Connecting to PostgreSQL backend (server/advanced tier)")
        _db = await PostgresDatabase.connect(url)
    elif scheme == "sqlite":
        path = _sqlite_path_from_url(url)
        logger.info("Connecting to SQLite backend at %r (desktop default)", path)
        _db = await SQLiteDatabase.connect(path)
    else:
        raise ValueError(
            f"Unsupported DATABASE_URL scheme {scheme!r}. "
            "Use sqlite:///path/to/file.db (default) or postgresql://... (server tier)."
        )
    return _db


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("Database not initialised — call connect_db() first")
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
