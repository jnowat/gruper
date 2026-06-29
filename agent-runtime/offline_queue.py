"""
SQLite-backed FIFO queue for tasks that cannot be executed immediately.

Tasks are enqueued when:
  - The circuit breaker is open (Ollama unavailable).
  - The orchestrator connection drops mid-execution.

They are drained in FIFO order on the next successful reconnect.
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

    async def size(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM queued_tasks") as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0
