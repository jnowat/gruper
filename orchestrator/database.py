import json
import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs so asyncpg can accept Python dicts as JSONB parameters."""
    await conn.set_type_codec("json",  encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def init_db(url: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(url, min_size=2, max_size=10, init=_init_connection)
    logger.info("Database pool established")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialised — call init_db() first")
    return _pool


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Apply any unapplied SQL migration files in order, idempotently.

    Each migration runs inside its own transaction. If the SQL fails, the
    transaction rolls back and the filename is NOT recorded, so the migration
    will be retried on the next startup rather than silently skipped.
    """
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   TEXT        PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            filename = path.name
            already_applied = await conn.fetchval(
                "SELECT 1 FROM schema_migrations WHERE filename = $1", filename
            )
            if already_applied:
                logger.debug("Migration %s already applied — skipping", filename)
                continue

            sql = path.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)", filename
                )
            logger.info("Applied migration: %s", filename)


async def append_event(
    pool: asyncpg.Pool,
    *,
    actor_id: str,
    action: str,
    subject_id: str,
    secondary_subject_id: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Append an audit event and return its UUID string."""
    row = await pool.fetchrow(
        """
        INSERT INTO events (actor_id, action, subject_id, secondary_subject_id, metadata)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id::text
        """,
        actor_id,
        action,
        subject_id,
        secondary_subject_id,
        metadata,
    )
    return row["id"]
