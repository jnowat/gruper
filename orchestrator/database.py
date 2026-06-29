import logging
import os
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def init_db(url: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(url, min_size=2, max_size=10)
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
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for path in migration_files:
            filename = path.name
            already_applied = await conn.fetchval(
                "SELECT 1 FROM schema_migrations WHERE filename = $1", filename
            )
            if already_applied:
                logger.debug("Migration %s already applied — skipping", filename)
                continue

            sql = path.read_text()
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
