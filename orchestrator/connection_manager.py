import asyncio
import time
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class _AgentConn:
    websocket: WebSocket
    last_heartbeat: float = field(default_factory=time.monotonic)


class ConnectionManager:
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
        cutoff = time.monotonic() - timeout_s
        return [aid for aid, conn in self._connections.items() if conn.last_heartbeat < cutoff]

    async def send_json(self, agent_id: str, data: dict) -> None:
        conn = self._connections.get(agent_id)
        if conn:
            await conn.websocket.send_json(data)


manager = ConnectionManager()
