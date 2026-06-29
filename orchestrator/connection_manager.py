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
    """Tracks live WebSocket connections from agent nodes.

    All mutations happen on the asyncio event loop thread, so no locking is
    needed for the dict itself. The watchdog calls get_stale_agents() followed
    by disconnect() on the same thread via asyncio.create_task, so there is no
    cross-thread mutation.
    """

    def __init__(self) -> None:
        self._connections: dict[str, _AgentConn] = {}

    def connect(self, agent_id: str, websocket: WebSocket) -> None:
        self._connections[agent_id] = _AgentConn(websocket=websocket)

    def disconnect(self, agent_id: str) -> None:
        self._connections.pop(agent_id, None)

    def record_heartbeat(self, agent_id: str) -> None:
        if agent_id in self._connections:
            self._connections[agent_id].last_heartbeat = time.monotonic()

    def is_connected(self, agent_id: str) -> bool:
        return agent_id in self._connections

    def get_stale_agents(self, timeout_s: int) -> list[str]:
        """Return agent IDs whose last heartbeat is older than timeout_s seconds."""
        cutoff = time.monotonic() - timeout_s
        # Snapshot items to avoid dict-changed-during-iteration if disconnect() races.
        return [
            aid
            for aid, conn in list(self._connections.items())
            if conn.last_heartbeat < cutoff
        ]

    async def send_json(self, agent_id: str, data: dict) -> None:
        conn = self._connections.get(agent_id)
        if conn is None:
            return
        try:
            await conn.websocket.send_json(data)
        except Exception:
            logger.warning("Failed to send message to agent %s — disconnecting", agent_id)
            self.disconnect(agent_id)


manager = ConnectionManager()
