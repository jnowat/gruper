"""Dialect-aware migration runner.

Each backend has its own `migrations/<dialect>/*.sql` directory (DDL differs
too much to auto-translate: UUID vs TEXT primary keys, JSONB vs TEXT
columns, TIMESTAMPTZ vs TEXT, etc.). Filenames are shared 1:1 across both
directories so the two schemas stay obviously in sync.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import Database

logger = logging.getLogger(__name__)

MIGRATIONS_ROOT = Path(__file__).parent.parent / "migrations"


async def run_migrations(db: Database) -> None:
    """Apply any unapplied SQL migration files in order, idempotently.

    Each migration runs in its own transaction (PostgreSQL) or its own
    committed statement (SQLite — see SQLiteDatabase.execute). If the SQL
    fails, the filename is NOT recorded, so the migration is retried next
    startup rather than silently skipped.
    """
    migrations_dir = MIGRATIONS_ROOT / db.dialect
    if not migrations_dir.is_dir():
        raise RuntimeError(f"No migrations directory for dialect {db.dialect!r}: {migrations_dir}")

    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)

    for path in sorted(migrations_dir.glob("*.sql")):
        filename = path.name
        already_applied = await db.fetchval(
            "SELECT 1 FROM schema_migrations WHERE filename = $1", filename
        )
        if already_applied:
            logger.debug("Migration %s already applied — skipping", filename)
            continue

        sql = path.read_text()
        await _run_migration_file(db, sql)
        await db.execute(
            "INSERT INTO schema_migrations (filename, applied_at) VALUES ($1, $2)",
            filename,
            _now_iso(),
        )
        logger.info("Applied migration: %s", filename)


async def _run_migration_file(db: Database, sql: str) -> None:
    if db.dialect == "postgres":
        # PostgresDatabase.execute delegates straight to asyncpg.Pool.execute,
        # which happily runs a multi-statement script in one call, wrapped
        # in an implicit transaction.
        await db.execute(sql)
    else:
        # sqlite3 (and therefore aiosqlite) does not support multiple
        # statements in a single execute() call — split on statement
        # boundaries and run them individually. Strip "--" line comments
        # first: a semicolon in prose inside a comment (e.g. "JSON-encoded);
        # encode/decode happens...") would otherwise be mistaken for a
        # statement boundary. Migration DDL itself contains no string
        # literals with embedded semicolons, so splitting the
        # comment-stripped text on ";" is safe.
        for statement in _strip_sql_comments(sql).split(";"):
            statement = statement.strip()
            if statement:
                await db.execute(statement)


def _strip_sql_comments(sql: str) -> str:
    lines = []
    for line in sql.splitlines():
        idx = line.find("--")
        lines.append(line[:idx] if idx != -1 else line)
    return "\n".join(lines)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
