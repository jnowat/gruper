import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .connection_manager import manager
from .database import close_db, get_pool, init_db, run_migrations
from .routers import agents, auth, health
from .ws.agent_ws import handle_agent_ws

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


async def _heartbeat_watchdog() -> None:
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
            logger.warning("Agent %s marked offline (missed heartbeat)", agent_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await init_db(settings.database_url)
    await run_migrations(pool)
    app.state.pool = pool

    watchdog = asyncio.create_task(_heartbeat_watchdog())
    logger.info("Gruper Orchestrator %s started", settings.orchestrator_version)

    yield

    watchdog.cancel()
    try:
        await watchdog
    except asyncio.CancelledError:
        pass
    await close_db()


app = FastAPI(
    title="Gruper Orchestrator",
    version=settings.orchestrator_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/v1")
app.include_router(auth.router, prefix="/v1")
app.include_router(agents.router, prefix="/v1")


@app.websocket("/v1/agents/ws")
async def agent_ws(
    websocket: WebSocket,
    token: str = Query(..., description="JWT issued by POST /v1/auth/token"),
) -> None:
    await handle_agent_ws(websocket, token)
