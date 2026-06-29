import logging

from fastapi import WebSocket, WebSocketDisconnect

from ..connection_manager import manager
from ..database import get_pool
from ..security import verify_token

logger = logging.getLogger(__name__)


async def handle_console_ws(websocket: WebSocket, token: str) -> None:
    """Handle a Manager Console WebSocket connection at GET /v1/console/ws.

    The console is a receive-side subscriber: the orchestrator pushes
    fleet_event, task_progress, task_complete, and queue_depth frames.
    Console mutations (task submission, agent registration) go through the
    REST API; the WS channel carries only the real-time event stream.

    On connect, the orchestrator immediately sends a fleet_snapshot with all
    agents owned by the authenticated user so the console can populate its
    fleet view without an extra REST round-trip.
    """
    try:
        payload = verify_token(token)
        user_id: str = payload["sub"]
    except ValueError:
        await websocket.accept()
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    await websocket.accept()
    manager.connect_console(user_id, websocket)
    logger.info("Console connected (user=%s)", user_id)

    pool = get_pool()
    try:
        # Initial fleet snapshot — avoids an extra REST call from the console.
        rows = await pool.fetch(
            """
            SELECT id::text, name, status, runtime_version,
                   capabilities, last_seen::text, created_at::text
            FROM agents
            WHERE owner_id = $1::uuid
            ORDER BY name
            """,
            user_id,
        )
        await websocket.send_json({
            "type": "fleet_snapshot",
            "agents": [dict(r) for r in rows],
        })
        logger.debug("Sent fleet_snapshot (%d agents) to user=%s", len(rows), user_id)

        # Block on receive so we detect clean close frames from the client.
        # The console does not send messages on this channel (WP-10 adds
        # interactive console → orchestrator commands if needed).
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected error on console WS (user=%s)", user_id)
    finally:
        manager.disconnect_console(user_id, websocket)
        logger.info("Console disconnected (user=%s)", user_id)
