"""PostgreSQL backend — thin wrapper over an asyncpg pool.

This is the server/advanced-tier backend. It is unchanged in behavior from
the pre-WP-30 orchestrator: same driver, same JSON/JSONB codec, same pool
sizing. Application SQL written for this backend keeps using asyncpg's
native `$1`-style parameters and `::type` casts.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from .base import Database, Row


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs so asyncpg accepts Python dicts as JSONB params."""
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


class PostgresDatabase(Database):
    dialect = "postgres"

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> "PostgresDatabase":
        pool = await asyncpg.create_pool(url, min_size=2, max_size=10, init=_init_connection)
        return cls(pool)

    async def execute(self, query: str, *args: Any) -> None:
        await self._pool.execute(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[Row]:
        rows = await self._pool.fetch(query, *args)
        return [Row(dict(r)) for r in rows]

    async def fetchrow(self, query: str, *args: Any) -> Row | None:
        row = await self._pool.fetchrow(query, *args)
        return Row(dict(row)) if row is not None else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self._pool.fetchval(query, *args)

    async def close(self) -> None:
        await self._pool.close()

    @property
    def raw_pool(self) -> asyncpg.Pool:
        """Escape hatch for the migration runner, which needs direct transaction control."""
        return self._pool
