"""
SQLite-backed local task queue — RETIRED as an execution path.

Older runtimes checkpointed tasks here (circuit open, connection dropped) and
re-executed the backlog on every reconnect. That duplicated the orchestrator's
own requeue-on-disconnect (double execution), burned Ollama on stale tasks
whose results were rejected, and the drain could starve heartbeats long enough
to get the agent killed mid-drain. The orchestrator is now the single source
of truth for retries; this module survives only so that startup can detect and
discard entries left behind by older builds (see AgentWSClient.start()).
"""

import json
import logging
from typing import AsyncIterator

import aiosqlite

logger = logging.getLogger(__name__)


class OfflineQueue:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS queued_tasks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id      TEXT    NOT NULL UNIQUE,
                payload      TEXT    NOT NULL,
                enqueued_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                attempts     INTEGER NOT NULL DEFAULT 0
            )
        """)
        await self._db.commit()
        pending = await self.size()
        if pending:
            logger.info("Offline queue opened with %d pending task(s)", pending)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def enqueue(self, task_id: str, payload: dict) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO queued_tasks (task_id, payload) VALUES (?, ?)",
            (task_id, json.dumps(payload)),
        )
        await self._db.commit()
        logger.info("Task %s queued for later delivery", task_id)

    async def drain(self) -> AsyncIterator[tuple[str, dict]]:
        """Yield (task_id, payload) in insertion order, oldest first."""
        async with self._db.execute(
            "SELECT task_id, payload FROM queued_tasks ORDER BY id"
        ) as cursor:
            rows = await cursor.fetchall()
        for task_id, payload_json in rows:
            yield task_id, json.loads(payload_json)

    async def mark_complete(self, task_id: str) -> None:
        await self._db.execute(
            "DELETE FROM queued_tasks WHERE task_id = ?", (task_id,)
        )
        await self._db.commit()

    async def clear(self) -> None:
        """Discard every queued entry (stale checkpoints from older builds)."""
        await self._db.execute("DELETE FROM queued_tasks")
        await self._db.commit()

    async def size(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM queued_tasks") as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0
