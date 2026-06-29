import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..connection_manager import manager
from ..database import append_event, get_pool
from ..security import decode_token

logger = logging.getLogger(__name__)

# Message types the agent sends to the orchestrator
_MSG_REGISTER = "register"
_MSG_HEARTBEAT = "heartbeat"
_MSG_STATUS = "status_update"


async def handle_agent_ws(websocket: WebSocket, token: str) -> None:
    """
    WebSocket handler for agent connections.

    Protocol (agent → orchestrator):
      1. Agent connects with ?token=<jwt>
      2. Agent sends {"type": "register", "agent_id": "<uuid>"}
      3. Agent sends {"type": "heartbeat"} every ~30 s
      4. Disconnect → agent status set to offline

    The token must be the JWT issued to the agent's owner at POST /v1/auth/token.
    """
    try:
        payload = decode_token(token)
        user_id: str = payload["sub"]
    except Exception:
        await websocket.close(code=4401, reason="Invalid token")
        return

    await websocket.accept()

    pool = get_pool()
    agent_id: str | None = None

    try:
        while True:
            msg: Any = await websocket.receive_json()
            msg_type = msg.get("type")

            if msg_type == _MSG_REGISTER:
                agent_id = await _handle_register(websocket, pool, user_id, msg)

            elif msg_type == _MSG_HEARTBEAT:
                if agent_id:
                    await _handle_heartbeat(pool, agent_id)
                else:
                    await websocket.send_json({"type": "error", "detail": "send register first"})

            elif msg_type == _MSG_STATUS:
                if agent_id:
                    await _handle_status_update(pool, agent_id, user_id, msg)
                else:
                    await websocket.send_json({"type": "error", "detail": "send register first"})

            else:
                await websocket.send_json({"type": "error", "detail": f"unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        pass
    finally:
        if agent_id:
            manager.disconnect(agent_id)
            await _set_status(pool, agent_id, "offline")
            await append_event(pool, actor_id=user_id, action="agent.disconnected", subject_id=agent_id)
            logger.info("Agent %s disconnected", agent_id)


async def _handle_register(
    websocket: WebSocket, pool: Any, user_id: str, msg: dict
) -> str | None:
    agent_id = msg.get("agent_id")
    if not agent_id:
        await websocket.send_json({"type": "error", "detail": "agent_id required"})
        return None

    row = await pool.fetchrow(
        "SELECT id::text, owner_id::text FROM agents WHERE id = $1::uuid",
        agent_id,
    )
    if not row:
        await websocket.send_json({"type": "error", "detail": "agent not found"})
        return None

    if row["owner_id"] != user_id:
        await websocket.send_json({"type": "error", "detail": "forbidden"})
        return None

    manager.connect(agent_id, websocket)
    await _set_status(pool, agent_id, "idle")
    await append_event(pool, actor_id=user_id, action="agent.connected", subject_id=agent_id)

    await websocket.send_json({"type": "registered", "agent_id": agent_id})
    logger.info("Agent %s registered over WS", agent_id)
    return agent_id


async def _handle_heartbeat(pool: Any, agent_id: str) -> None:
    manager.record_heartbeat(agent_id)
    await pool.execute(
        "UPDATE agents SET last_seen = NOW() WHERE id = $1::uuid", agent_id
    )


async def _handle_status_update(pool: Any, agent_id: str, user_id: str, msg: dict) -> None:
    new_status = msg.get("status")
    valid = {"idle", "busy", "degraded", "draining"}
    if new_status not in valid:
        return
    await _set_status(pool, agent_id, new_status)
    await append_event(
        pool,
        actor_id=user_id,
        action="agent.status_changed",
        subject_id=agent_id,
        metadata={"status": new_status},
    )


async def _set_status(pool: Any, agent_id: str, status: str) -> None:
    await pool.execute(
        "UPDATE agents SET status = $1, last_seen = NOW() WHERE id = $2::uuid",
        status,
        agent_id,
    )
