"""
Smoke tests: WebSocket agent registration, heartbeat, status update, disconnect lifecycle.
"""

import base64
import secrets

import pytest
from starlette.testclient import TestClient


def _rand_pubkey() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def _capabilities() -> dict:
    return {
        "models":   ["llama3.1:8b"],
        "roles":    ["analyst"],
        "tools":    [],
        "hardware": {},
    }


@pytest.fixture
def registered_agent(client: TestClient, auth_token: tuple[str, str]) -> tuple[str, str]:
    """Register a fresh agent and return (agent_id, jwt_token)."""
    token, _ = auth_token
    resp = client.post(
        "/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "WS Test Agent",
            "pubkey": _rand_pubkey(),
            "capabilities": _capabilities(),
            "runtime_version": "gd-0.1.0",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"], token


def _get_agent(client: TestClient, token: str, agent_id: str) -> dict | None:
    resp = client.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    return next((a for a in resp.json() if a["id"] == agent_id), None)


class TestAgentWebSocket:
    def test_register_handshake(
        self, client: TestClient, registered_agent: tuple[str, str]
    ) -> None:
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            msg = ws.receive_json()
        assert msg["type"] == "registered"
        assert msg["agent_id"] == agent_id

    def test_agent_becomes_idle_after_register(
        self, client: TestClient, registered_agent: tuple[str, str]
    ) -> None:
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # "registered"
            agent = _get_agent(client, token, agent_id)
        assert agent is not None
        assert agent["status"] == "idle"

    def test_agent_becomes_offline_after_disconnect(
        self, client: TestClient, registered_agent: tuple[str, str]
    ) -> None:
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # "registered"
        # WebSocket closed — agent should be offline
        agent = _get_agent(client, token, agent_id)
        assert agent is not None
        assert agent["status"] == "offline"

    def test_heartbeat_is_accepted_silently(
        self, client: TestClient, registered_agent: tuple[str, str]
    ) -> None:
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # "registered"
            ws.send_json({"type": "heartbeat"})
            # Heartbeat has no response frame; connection must still be healthy.
            ws.send_json({"type": "heartbeat"})

    def test_invalid_status_returns_error(
        self, client: TestClient, registered_agent: tuple[str, str]
    ) -> None:
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # "registered"
            ws.send_json({"type": "status_update", "status": "exploded"})
            msg = ws.receive_json()
        assert msg["type"] == "error"

    def test_invalid_token_closes_connection(self, client: TestClient) -> None:
        with client.websocket_connect("/v1/agents/ws?token=not.a.valid.jwt") as ws:
            with pytest.raises(Exception):
                ws.receive_json()

    def test_unknown_agent_id_returns_error(
        self, client: TestClient, auth_token: tuple[str, str]
    ) -> None:
        token, _ = auth_token
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": "00000000-0000-0000-0000-000000000000"})
            msg = ws.receive_json()
        assert msg["type"] == "error"

    def test_malformed_uuid_returns_error(
        self, client: TestClient, auth_token: tuple[str, str]
    ) -> None:
        token, _ = auth_token
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": "not-a-uuid"})
            msg = ws.receive_json()
        assert msg["type"] == "error"
