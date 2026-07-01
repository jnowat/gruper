"""
Task dispatch logic shared between the REST submission path and the WebSocket
registration path.

  submit → try_dispatch()           → pushes immediately if agent online
  register → dispatch_pending_for_agent() → drains pending queue on connect
  disconnect → requeue_or_deadletter()   → reschedules or dead-letters

Dispatch claiming works identically on both backends despite using the same
SQL text: PostgreSQL's `FOR UPDATE SKIP LOCKED` clause is stripped by the
SQLite backend's generic adapter (see db/sqlite.py) because SQLite
serializes all writes through a single connection anyway, so no row-level
lock hint is needed there.
"""

import logging
from typing import TYPE_CHECKING

from .db import Database, Row
from .db.util import now_iso, ts_or_none

if TYPE_CHECKING:
    from .connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3

# Columns returned to the caller; all UUID columns cast to text.
_TASK_COLS = """
    id::text,
    submitter_id::text,
    assigned_agent_id::text,
    data_class,
    input,
    allowed_tools,
    status,
    priority,
    deadline,
    timeout_s,
    retry_count,
    created_at,
    dispatched_at
"""

# Same columns but qualified with the table alias used in CTE-based UPDATEs.
_TASK_COLS_Q = """
    tasks.id::text,
    tasks.submitter_id::text,
    tasks.assigned_agent_id::text,
    tasks.data_class,
    tasks.input,
    tasks.allowed_tools,
    tasks.status,
    tasks.priority,
    tasks.deadline,
    tasks.timeout_s,
    tasks.retry_count,
    tasks.created_at,
    tasks.dispatched_at
"""


async def try_dispatch(
    db: Database,
    manager: "ConnectionManager",
    task_id: str,
) -> bool:
    """
    Atomically claim a pending task and push it to its assigned agent.

    The UPDATE WHERE status='pending' acts as a compare-and-swap: only one
    concurrent caller can claim the task. Returns True if the task was
    dispatched over WebSocket; False if the agent is offline or the task
    is no longer pending.
    """
    row = await db.fetchrow(
        f"""
        UPDATE tasks SET status = 'dispatched', dispatched_at = $2
        WHERE id = $1::uuid AND status = 'pending'
        RETURNING {_TASK_COLS}
        """,
        task_id,
        now_iso(),
    )
    if row is None:
        return False  # task gone or already claimed

    agent_id = row["assigned_agent_id"]
    if not manager.is_connected(agent_id):
        # Agent is offline — revert to pending so dispatch_pending_for_agent picks it up on reconnect.
        await db.execute(
            "UPDATE tasks SET status = 'pending', dispatched_at = NULL WHERE id = $1::uuid",
            task_id,
        )
        return False

    await manager.send_json(agent_id, _build_task_push(row))
    logger.info("Task %s dispatched to agent %s", task_id, agent_id)
    return True


async def dispatch_pending_for_agent(
    db: Database,
    manager: "ConnectionManager",
    agent_id: str,
) -> int:
    """
    Dispatch all pending tasks for a newly-connected agent, in priority order.

    On PostgreSQL, `FOR UPDATE SKIP LOCKED` (dropped for SQLite by the
    generic adapter — see module docstring) guards against double-dispatch
    if concurrent orchestrator instances or reconnects race. Returns the
    number of tasks sent.
    """
    rows = await db.fetch(
        f"""
        WITH to_dispatch AS (
            SELECT id FROM tasks
            WHERE assigned_agent_id = $1::uuid AND status = 'pending'
            ORDER BY priority DESC, created_at ASC
            FOR UPDATE SKIP LOCKED
        )
        UPDATE tasks SET status = 'dispatched', dispatched_at = $2
        FROM to_dispatch
        WHERE tasks.id = to_dispatch.id
        RETURNING {_TASK_COLS_Q}
        """,
        agent_id,
        now_iso(),
    )
    count = 0
    for row in rows:
        await manager.send_json(agent_id, _build_task_push(row))
        count += 1
    if count:
        logger.info("Dispatched %d pending task(s) to agent %s on connect", count, agent_id)
    return count


async def requeue_or_deadletter(db: Database, agent_id: str) -> None:
    """
    On agent disconnect, reschedule or dead-letter all active tasks.

    Tasks in 'dispatched' or 'running' state are either:
    - Requeued to 'pending' (retry_count incremented) while retries remain.
    - Moved to 'dead_letter' after _MAX_RETRIES attempts.
    """
    rows = await db.fetch(
        """
        SELECT id::text, retry_count
        FROM tasks
        WHERE assigned_agent_id = $1::uuid AND status IN ('dispatched', 'running')
        """,
        agent_id,
    )
    for row in rows:
        task_id = row["id"]
        new_retry = row["retry_count"] + 1
        if new_retry >= _MAX_RETRIES:
            await db.execute(
                "UPDATE tasks SET status = 'dead_letter' WHERE id = $1::uuid",
                task_id,
            )
            logger.warning("Task %s dead-lettered after %d retries", task_id, new_retry)
        else:
            await db.execute(
                """
                UPDATE tasks
                SET status = 'pending', retry_count = $2, dispatched_at = NULL
                WHERE id = $1::uuid
                """,
                task_id,
                new_retry,
            )
            logger.info("Task %s requeued (retry %d/%d)", task_id, new_retry, _MAX_RETRIES)


def _build_task_push(row: Row) -> dict:
    """Build a task_push WebSocket message from a tasks row."""
    return {
        "type": "task_push",
        "task": {
            "id":                row["id"],
            "submitter_id":      row["submitter_id"],
            "assigned_agent_id": row["assigned_agent_id"],
            "data_class":        row["data_class"],
            "input":             dict(row["input"]) if row["input"] else {},
            "allowed_tools":     list(row["allowed_tools"]) if row["allowed_tools"] else [],
            "status":            "dispatched",
            "priority":          row["priority"],
            "deadline":          ts_or_none(row["deadline"]),
            "timeout_s":         row["timeout_s"],
            "retry_count":       row["retry_count"],
            "created_at":        ts_or_none(row["created_at"]),
            "dispatched_at":     ts_or_none(row["dispatched_at"]),
        },
        "ack_deadline_s": 10,
    }
