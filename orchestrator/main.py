import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .connection_manager import manager
from .database import close_db, get_pool, init_db, run_migrations
from .db.util import now_iso
from .routers import agents, auth, health, tasks
from .structured_log import configure_logging
from .ws.agent_ws import broadcast_fleet_event, handle_agent_ws
from .ws.console_ws import handle_console_ws

# Structured, category-tagged logging: emits one JSON line per record on stdout,
# which the Console drains and parses into its unified debug log (see
# orchestrator/structured_log.py and console/src-tauri/src/lib.rs). Replaces
# logging.basicConfig so the desktop tier gets observable, exportable logs.
configure_logging("orchestrator", settings.log_level)
logger = logging.getLogger(__name__)

# PostgreSQL's INTERVAL arithmetic has no SQLite equivalent (dispatched_at
# and "now" are both ISO-8601 text on SQLite) — this is one of the few
# queries that genuinely needs dialect-specific SQL text rather than the
# generic placeholder/cast adapter. Both sides of the SQLite comparison are
# normalized through datetime() so the TEXT comparison isn't thrown off by
# datetime()'s space-separated output vs. Python's "T"-separated isoformat()
# (verified empirically — see WP-30 notes; a naive string comparison of the
# two different formats silently produces wrong results).
_TIMEOUT_WATCHDOG_SQL_PG = """
    UPDATE tasks SET status = 'timed_out', completed_at = $1
    WHERE status IN ('dispatched', 'running')
      AND dispatched_at + (timeout_s * INTERVAL '1 second') < $1
    RETURNING id::text, assigned_agent_id::text, submitter_id::text
"""
_TIMEOUT_WATCHDOG_SQL_SQLITE = """
    UPDATE tasks SET status = 'timed_out', completed_at = ?1
    WHERE status IN ('dispatched', 'running')
      AND datetime(dispatched_at, '+' || timeout_s || ' seconds') < datetime(?1)
    RETURNING id, assigned_agent_id, submitter_id
"""


async def _timeout_watchdog() -> None:
    """Background task: mark dispatched/running tasks timed_out when their deadline expires.

    Each transition is also broadcast to the submitter's consoles as a
    task_complete frame — without it, a console sitting on an open answer
    view keeps showing "answering…" for a task the orchestrator has already
    given up on, until the user happens to trigger a full REST reload.
    """
    while True:
        await asyncio.sleep(30)
        db = get_pool()
        rows = await db.fetch(db.q(pg=_TIMEOUT_WATCHDOG_SQL_PG, lite=_TIMEOUT_WATCHDOG_SQL_SQLITE), now_iso())
        for row in rows:
            logger.warning("Task %s timed out (agent=%s)", row["id"], row["assigned_agent_id"])
            await manager.broadcast_to_user(row["submitter_id"], {
                "type": "task_complete",
                "payload": {
                    "task_id": row["id"],
                    "agent_id": row["assigned_agent_id"],
                    "final_status": "timed_out",
                    "duration_ms": None,
                    "model_used": None,
                    "error_code": "timeout",
                    "output_preview": None,
                },
            })


async def _heartbeat_watchdog() -> None:
    """Background task: poll for agents that have stopped sending heartbeats.

    Runs every heartbeat_check_interval_s seconds. Any agent whose last
    heartbeat is older than heartbeat_timeout_s is disconnected from the
    connection manager, marked offline in the database, AND broadcast to the
    owner's consoles as a fleet_event. The broadcast matters: without it a
    silently-dead agent kept its green "ready" dot in every open console
    until the next full reconnect, which is exactly the ghost-fleet state
    observed in real Windows testing.
    """
    while True:
        await asyncio.sleep(settings.heartbeat_check_interval_s)
        stale = manager.get_stale_agents(settings.heartbeat_timeout_s)
        if not stale:
            continue
        pool = get_pool()
        for agent_id in stale:
            manager.disconnect(agent_id)
            row = await pool.fetchrow(
                "UPDATE agents SET status = 'offline' WHERE id = $1::uuid RETURNING owner_id::text",
                agent_id,
            )
            logger.warning("Agent %s marked offline — missed heartbeat", agent_id)
            if row:
                await broadcast_fleet_event(pool, agent_id, row["owner_id"], "agent_offline", "offline")


async def sweep_stale_agent_statuses(pool) -> int:
    """Mark every non-offline agent offline. Runs once at startup.

    Agent liveness is a property of a WebSocket connection to THIS process;
    no connection can survive an orchestrator restart, so any 'idle'/'busy'
    row at boot is a leftover from a previous run (common on Windows, where
    the sidecar is routinely killed rather than shut down). Without this
    sweep those rows read as "ready" forever: the heartbeat watchdog only
    inspects connections it knows about, so a stale row is invisible to
    every other cleanup path. This single lie was upstream of most of the
    ghost-fleet symptoms (Round Table seating dead agents, tasks queuing
    forever, un-removable agents).
    """
    rows = await pool.fetch(
        "UPDATE agents SET status = 'offline' WHERE status != 'offline' RETURNING id::text"
    )
    if rows:
        logger.info(
            "Startup sweep: marked %d agent(s) offline (statuses left over from a previous run)",
            len(rows),
        )
    return len(rows)


async def purge_deleted_agents(pool) -> int:
    """Hard-delete soft-deleted agents whose task history is gone.

    Soft delete exists only because tasks reference assigned_agent_id; once a
    deleted agent's last task has been cleared (History "Clear all", single
    deletes), nothing references the row and keeping it is pure data-model
    debt. Runs once at startup, so the agents table converges back to only
    the rows that mean something.
    """
    rows = await pool.fetch(
        """
        DELETE FROM agents
        WHERE deleted_at IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM tasks WHERE tasks.assigned_agent_id = agents.id)
        RETURNING id::text
        """
    )
    if rows:
        logger.info("Purged %d soft-deleted agent(s) with no remaining tasks", len(rows))
    return len(rows)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    pool = await init_db(settings.database_url)
    await run_migrations(pool)
    await sweep_stale_agent_statuses(pool)
    await purge_deleted_agents(pool)
    app.state.pool = pool

    watchdog = asyncio.create_task(_heartbeat_watchdog())
    timeout_watchdog = asyncio.create_task(_timeout_watchdog())
    logger.info("Gruper Orchestrator %s ready", settings.orchestrator_version)

    yield

    watchdog.cancel()
    timeout_watchdog.cancel()
    for t in (watchdog, timeout_watchdog):
        try:
            await t
        except asyncio.CancelledError:
            pass
    await close_db()
    logger.info("Gruper Orchestrator shut down cleanly")


app = FastAPI(
    title="Gruper Orchestrator",
    version=settings.orchestrator_version,
    description=(
        "Relay orchestrator for Gruper Distributed (gd-0.1). "
        "Accepts agent registrations over REST and heartbeats over WebSocket. "
        "Task dispatch added in WP-04."
    ),
    lifespan=lifespan,
)

# CORS: allow_credentials is intentionally omitted — the API uses JWT Bearer
# tokens (Authorization header), not cookies, so browser credential inclusion
# is not required. Wildcard origin is safe without credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/v1")
app.include_router(auth.router,   prefix="/v1")
app.include_router(agents.router, prefix="/v1")
app.include_router(tasks.router,  prefix="/v1")


@app.websocket("/v1/agents/ws")
async def agent_ws(
    websocket: WebSocket,
    token: str = Query(..., description="JWT issued by POST /v1/auth/token"),
) -> None:
    """WebSocket endpoint for agent heartbeat and task dispatch."""
    await handle_agent_ws(websocket, token)


@app.websocket("/v1/console/ws")
async def console_ws(
    websocket: WebSocket,
    token: str = Query(..., description="JWT issued by POST /v1/auth/token"),
) -> None:
    """WebSocket endpoint for the Manager Console — real-time fleet and task events."""
    await handle_console_ws(websocket, token)
