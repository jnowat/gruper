import logging
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class _AgentConn:
    websocket: WebSocket
    last_heartbeat: float = field(default_factory=time.monotonic)


class ConnectionManager:
    """Tracks live WebSocket connections from agent nodes and Manager Console sessions.

    Agent connections: one per agent_id (agents enforce single-connection per agent).
    Console connections: one or more per user_id (multiple windows / tabs allowed).

    All mutations happen on the asyncio event loop thread, so no locking is needed
    for either dict. The heartbeat watchdog calls get_stale_agents() and then
    disconnect() on the same thread via asyncio.create_task.
    """

    def __init__(self) -> None:
        self._agent_connections: dict[str, _AgentConn] = {}
        self._console_connections: dict[str, set[WebSocket]] = {}

    # ── Agent connections ──────────────────────────────────────────────────────

    def connect(self, agent_id: str, websocket: WebSocket) -> None:
        self._agent_connections[agent_id] = _AgentConn(websocket=websocket)

    def disconnect(self, agent_id: str) -> None:
        self._agent_connections.pop(agent_id, None)

    def record_heartbeat(self, agent_id: str) -> None:
        if agent_id in self._agent_connections:
            self._agent_connections[agent_id].last_heartbeat = time.monotonic()

    def is_connected(self, agent_id: str) -> bool:
        return agent_id in self._agent_connections

    def get_stale_agents(self, timeout_s: int) -> list[str]:
        """Return agent IDs whose last heartbeat is older than timeout_s seconds."""
        cutoff = time.monotonic() - timeout_s
        # Snapshot items to avoid dict-changed-during-iteration if disconnect() races.
        return [
            aid
            for aid, conn in list(self._agent_connections.items())
            if conn.last_heartbeat < cutoff
        ]

    async def send_json(self, agent_id: str, data: dict) -> None:
        conn = self._agent_connections.get(agent_id)
        if conn is None:
            return
        try:
            await conn.websocket.send_json(data)
        except Exception as exc:
            # Log WHAT failed, not just that it failed — a serialization bug
            # in a frame once hid here as a mysterious "agent disconnected".
            logger.warning(
                "Failed to send %r message to agent %s (%s: %s) — disconnecting",
                data.get("type"), agent_id, type(exc).__name__, exc,
            )
            self.disconnect(agent_id)

    async def close_agent_ws(self, agent_id: str, reason: str) -> None:
        """Server-side close of a live agent connection (e.g. the agent was
        deleted). The runtime sees the close, reconnects, gets its register
        rejected, and shuts itself down — so deletion works even for agents
        this orchestrator's console never spawned."""
        conn = self._agent_connections.pop(agent_id, None)
        if conn is None:
            return
        try:
            await conn.websocket.close(code=4404, reason=reason)
        except Exception:
            logger.warning("Could not close WS for agent %s cleanly", agent_id)

    # ── Console connections ────────────────────────────────────────────────────

    def connect_console(self, user_id: str, websocket: WebSocket) -> None:
        self._console_connections.setdefault(user_id, set()).add(websocket)

    def disconnect_console(self, user_id: str, websocket: WebSocket) -> None:
        sockets = self._console_connections.get(user_id)
        if sockets:
            sockets.discard(websocket)
            if not sockets:
                del self._console_connections[user_id]

    async def broadcast_to_user(self, user_id: str, data: dict) -> None:
        """Push a JSON message to every open console connection for user_id."""
        sockets = list(self._console_connections.get(user_id, set()))
        failed: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(data)
            except Exception:
                logger.warning("Console WS send failed for user %s — dropping socket", user_id)
                failed.append(ws)
        for ws in failed:
            self.disconnect_console(user_id, ws)


manager = ConnectionManager()
