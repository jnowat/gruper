import logging

import asyncpg
from fastapi import WebSocket, WebSocketDisconnect

from ..connection_manager import manager
from ..database import append_event, get_pool
from ..security import decode_token

logger = logging.getLogger(__name__)

# Inbound message types (agent → orchestrator)
_MSG_REGISTER  = "register"
_MSG_HEARTBEAT = "heartbeat"
_MSG_STATUS    = "status_update"

# Agent statuses the agent may self-report (offline is set by the orchestrator only)
_SELF_REPORTABLE_STATUSES = frozenset({"idle", "busy", "degraded", "draining"})


async def handle_agent_ws(websocket: WebSocket, token: str) -> None:
    """Handle the lifecycle of a single agent WebSocket connection.

    Protocol (agent → orchestrator):
      1. Agent connects: GET /v1/agents/ws?token=<jwt>
      2. Agent sends:    {"type": "register", "agent_id": "<uuid>"}
      3. Orchestrator:   {"type": "registered", "agent_id": "<uuid>"}   (status → idle)
      4. Agent sends:    {"type": "heartbeat"}  every ~30 s
      5. Agent sends:    {"type": "status_update", "status": "busy|idle|degraded|draining"}
      6. Disconnect:     status → offline

    The JWT must be the token issued to the agent's owner via POST /v1/auth/token.
    ed25519 challenge-response will replace this in WP-07.
    """
    # Validate the token before accepting the upgrade so we can reject it cleanly.
    try:
        payload = decode_token(token)
        user_id: str = payload["sub"]
    except Exception:
        # Accept then immediately close — Starlette requires accept() before close().
        await websocket.accept()
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    await websocket.accept()

    pool = get_pool()
    agent_id: str | None = None

    try:
        while True:
            msg: dict = await websocket.receive_json()
            msg_type = msg.get("type")

            if msg_type == _MSG_REGISTER:
                agent_id = await _handle_register(websocket, pool, user_id, msg)

            elif msg_type == _MSG_HEARTBEAT:
                if agent_id is None:
                    await websocket.send_json({"type": "error", "detail": "send register before heartbeat"})
                else:
                    await _handle_heartbeat(pool, agent_id)

            elif msg_type == _MSG_STATUS:
                if agent_id is None:
                    await websocket.send_json({"type": "error", "detail": "send register before status_update"})
                else:
                    await _handle_status_update(websocket, pool, agent_id, user_id, msg)

            else:
                await websocket.send_json({"type": "error", "detail": f"unknown message type: {msg_type!r}"})

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected error on agent WS for agent %s", agent_id)
    finally:
        if agent_id:
            manager.disconnect(agent_id)
            await _set_status(pool, agent_id, "offline")
            await append_event(pool, actor_id=user_id, action="agent.disconnected", subject_id=agent_id)
            logger.info("Agent %s disconnected", agent_id)


async def _handle_register(
    websocket: WebSocket, pool: asyncpg.Pool, user_id: str, msg: dict
) -> str | None:
    agent_id = msg.get("agent_id", "")
    if not agent_id:
        await websocket.send_json({"type": "error", "detail": "agent_id is required"})
        return None

    try:
        row = await pool.fetchrow(
            "SELECT id::text, owner_id::text FROM agents WHERE id = $1::uuid",
            agent_id,
        )
    except asyncpg.InvalidTextRepresentationError:
        await websocket.send_json({"type": "error", "detail": "agent_id must be a valid UUID"})
        return None

    if row is None:
        await websocket.send_json({"type": "error", "detail": "agent not found"})
        return None

    if row["owner_id"] != user_id:
        await websocket.send_json({"type": "error", "detail": "forbidden"})
        return None

    manager.connect(agent_id, websocket)
    await _set_status(pool, agent_id, "idle")
    await append_event(pool, actor_id=user_id, action="agent.connected", subject_id=agent_id)

    await websocket.send_json({"type": "registered", "agent_id": agent_id})
    logger.info("Agent %s online (owner=%s)", agent_id, user_id)
    return agent_id


async def _handle_heartbeat(pool: asyncpg.Pool, agent_id: str) -> None:
    manager.record_heartbeat(agent_id)
    await pool.execute(
        "UPDATE agents SET last_seen = NOW() WHERE id = $1::uuid", agent_id
    )


async def _handle_status_update(
    websocket: WebSocket,
    pool: asyncpg.Pool,
    agent_id: str,
    user_id: str,
    msg: dict,
) -> None:
    new_status = msg.get("status")
    if new_status not in _SELF_REPORTABLE_STATUSES:
        await websocket.send_json({
            "type": "error",
            "detail": f"invalid status {new_status!r}; allowed: {sorted(_SELF_REPORTABLE_STATUSES)}",
        })
        return
    await _set_status(pool, agent_id, new_status)
    await append_event(
        pool,
        actor_id=user_id,
        action="agent.status_changed",
        subject_id=agent_id,
        metadata={"status": new_status},
    )


async def _set_status(pool: asyncpg.Pool, agent_id: str, status: str) -> None:
    await pool.execute(
        "UPDATE agents SET status = $1, last_seen = NOW() WHERE id = $2::uuid",
        status,
        agent_id,
    )
