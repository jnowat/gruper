"""SQLite backend — the default for local/desktop use.

Design notes (see ROADMAP.md WP-30 for the full rationale):

- One shared `aiosqlite.Connection` for the whole process, guarded by an
  `asyncio.Lock`. This is what gives single-writer claim semantics for
  free and is why the dispatch queries below can be one atomic UPDATE
  statement instead of needing PostgreSQL's `FOR UPDATE SKIP LOCKED`. The
  lock is required, not optional: aiosqlite serializes individual
  execute()/commit() calls onto a background-thread queue, but each public
  method here issues several of those calls in sequence
  (execute -> fetch -> close -> commit), and without the lock a different
  concurrently-running asyncio task (the WS handler runs as a background
  task alongside HTTP requests) can interleave its own commit in the
  middle of that sequence, which sqlite3 rejects with "cannot commit
  transaction - SQL statements in progress" — this was caught empirically
  by the test suite, not designed away in advance (see WP-30 notes).
- WAL mode + a busy_timeout are enabled on connect for reasonable
  read/write concurrency and to avoid immediate "database is locked"
  errors under load.
- SQL text written for PostgreSQL (`$1`-style params, `::type` casts, the
  literal `FOR UPDATE SKIP LOCKED` clause) is mechanically adapted here:
  casts are stripped (SQLite is dynamically typed, so the cast has no
  runtime effect beyond documentation), `$N` becomes SQLite's numbered
  `?N` form (verified empirically to bind correctly regardless of the
  order placeholders appear in the SQL text — see WP-30 notes), and the
  SKIP LOCKED clause (meaningless on a single-writer engine) is dropped.
- Bound arguments are converted generically: dict/list -> JSON text
  (sqlite3 cannot bind a dict/list directly), datetime -> ISO-8601 text.
  This requires no per-query configuration because it only depends on the
  Python type of the value being bound, not on which column it targets.
- JSON columns are decoded back to dict/list on read via a fixed
  column-name allowlist (`_JSON_COLUMNS`). This is safe — not "magic" —
  specifically because no query in this codebase ever casts a JSON column
  to `::text` expecting a raw string (that pattern is only used for UUID
  and timestamp columns, which SQLite already returns as plain strings
  with no coercion needed).
- Timestamps are stored and returned as plain ISO-8601 UTC text (whatever
  Python's `datetime.isoformat()` produces) with NO read-side coercion to
  a `datetime` object. This is a deliberate simplification: the few call
  sites that used to assume a `datetime` (calling `.isoformat()` on it)
  are updated to accept either a `datetime` or an already-ISO string (see
  `orchestrator/db/util.py::ts_or_none`). Coercing every known
  "timestamp-looking" column back to `datetime` here would silently break
  the handful of queries that explicitly cast a timestamp `::text`
  expecting a raw string for JSON serialization (e.g. the console fleet
  snapshot).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any

import aiosqlite

from .base import Database, Row

# Columns that are stored as JSON text and must be encoded/decoded at the
# boundary. Safe as a global, column-name-keyed allowlist because no query
# in this codebase casts any of these to `::text` expecting a raw string.
_JSON_COLUMNS = frozenset({
    "input", "allowed_tools", "result", "error",
    "capabilities", "availability", "share_policies", "metadata",
})

_CAST_RE = re.compile(r"::[A-Za-z_]+")
_PARAM_RE = re.compile(r"\$(\d+)")
_SKIP_LOCKED_RE = re.compile(r"\s*FOR UPDATE SKIP LOCKED\s*", re.IGNORECASE)


def adapt_sql(query: str) -> str:
    """Rewrite PostgreSQL-flavoured SQL text for SQLite.

    Strips `::type` casts, converts `$N` positional params to SQLite's
    numbered `?N` form, and drops the (meaningless on a single-writer
    engine) `FOR UPDATE SKIP LOCKED` clause. Exposed as a module function
    so it can be unit tested directly without a live connection.
    """
    query = _SKIP_LOCKED_RE.sub(" ", query)
    query = _CAST_RE.sub("", query)
    query = _PARAM_RE.sub(r"?\1", query)
    return query


def _adapt_arg(value: Any) -> Any:
    """Convert a Python value into something sqlite3 can bind.

    Generic and type-driven only — does not need to know which column a
    value targets. dict/list become JSON text; datetime becomes ISO-8601
    text (matching what PostgreSQL's own `.isoformat()` output looks
    like, so downstream string handling doesn't need to branch on
    backend).
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row_from_mapping(data: dict) -> Row:
    decoded = dict(data)
    for col in _JSON_COLUMNS:
        val = decoded.get(col)
        if isinstance(val, str):
            decoded[col] = json.loads(val)
    return Row(decoded)


class SQLiteDatabase(Database):
    dialect = "sqlite"

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = aiosqlite.Row
        # aiosqlite serializes individual execute()/commit() calls onto one
        # background-thread queue, but a single Database method here issues
        # SEVERAL of those calls in sequence (execute -> fetch -> close ->
        # commit). Without a lock, a different concurrently-running asyncio
        # task (e.g. the WS handler's background task interleaved with an
        # HTTP request) can slip its own execute/commit in between those
        # steps and hit "cannot commit transaction - SQL statements in
        # progress". This lock makes each public method atomic with respect
        # to every other call on this connection — verified empirically
        # against the concurrent WS+REST test paths (see WP-30 notes).
        self._lock = asyncio.Lock()

    @classmethod
    async def connect(cls, path: str) -> "SQLiteDatabase":
        conn = await aiosqlite.connect(path)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.commit()
        return cls(conn)

    async def execute(self, query: str, *args: Any) -> None:
        async with self._lock:
            cursor = await self._conn.execute(adapt_sql(query), tuple(_adapt_arg(a) for a in args))
            await cursor.close()
            await self._conn.commit()

    async def fetch(self, query: str, *args: Any) -> list[Row]:
        async with self._lock:
            cursor = await self._conn.execute(adapt_sql(query), tuple(_adapt_arg(a) for a in args))
            rows = await cursor.fetchall()
            await cursor.close()
            await self._conn.commit()
            return [_row_from_mapping(dict(r)) for r in rows]

    async def fetchrow(self, query: str, *args: Any) -> Row | None:
        async with self._lock:
            cursor = await self._conn.execute(adapt_sql(query), tuple(_adapt_arg(a) for a in args))
            row = await cursor.fetchone()
            await cursor.close()
            await self._conn.commit()
            return _row_from_mapping(dict(row)) if row is not None else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self._lock:
            cursor = await self._conn.execute(adapt_sql(query), tuple(_adapt_arg(a) for a in args))
            row = await cursor.fetchone()
            await cursor.close()
            await self._conn.commit()
            if row is None:
                return None
            return tuple(row)[0]

    async def close(self) -> None:
        await self._conn.close()

    @property
    def raw_conn(self) -> aiosqlite.Connection:
        """Escape hatch for the migration runner."""
        return self._conn
