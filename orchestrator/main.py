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
from .ws.agent_ws import handle_agent_ws
from .ws.console_ws import handle_console_ws

logging.basicConfig(level=settings.log_level)
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
    RETURNING id::text, assigned_agent_id::text
"""
_TIMEOUT_WATCHDOG_SQL_SQLITE = """
    UPDATE tasks SET status = 'timed_out', completed_at = ?1
    WHERE status IN ('dispatched', 'running')
      AND datetime(dispatched_at, '+' || timeout_s || ' seconds') < datetime(?1)
    RETURNING id, assigned_agent_id
"""


async def _timeout_watchdog() -> None:
    """Background task: mark dispatched/running tasks timed_out when their deadline expires."""
    while True:
        await asyncio.sleep(30)
        db = get_pool()
        rows = await db.fetch(db.q(pg=_TIMEOUT_WATCHDOG_SQL_PG, lite=_TIMEOUT_WATCHDOG_SQL_SQLITE), now_iso())
        for row in rows:
            logger.warning("Task %s timed out (agent=%s)", row["id"], row["assigned_agent_id"])


async def _heartbeat_watchdog() -> None:
    """Background task: poll for agents that have stopped sending heartbeats.

    Runs every heartbeat_check_interval_s seconds. Any agent whose last
    heartbeat is older than heartbeat_timeout_s is disconnected from the
    connection manager and marked offline in the database.
    """
    while True:
        await asyncio.sleep(settings.heartbeat_check_interval_s)
        stale = manager.get_stale_agents(settings.heartbeat_timeout_s)
        if not stale:
            continue
        pool = get_pool()
        for agent_id in stale:
            manager.disconnect(agent_id)
            await pool.execute(
                "UPDATE agents SET status = 'offline' WHERE id = $1::uuid", agent_id
            )
            logger.warning("Agent %s marked offline — missed heartbeat", agent_id)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    pool = await init_db(settings.database_url)
    await run_migrations(pool)
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
