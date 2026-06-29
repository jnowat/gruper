"""
Smoke tests: WebSocket agent connection, register message, heartbeat, disconnect.
"""

import base64
import secrets

import pytest
from starlette.testclient import TestClient


def _rand_pubkey() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def _capabilities() -> dict:
    return {
        "models": ["llama3.1:8b"],
        "roles": ["analyst"],
        "tools": [],
        "hardware": {},
    }


@pytest.fixture
def registered_agent(client: TestClient, auth_token: tuple[str, str]) -> tuple[str, str]:
    """Return (agent_id, token) for a freshly registered agent."""
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


class TestAgentWebSocket:
    def test_ws_register_and_heartbeat(
        self, client: TestClient, registered_agent: tuple[str, str]
    ) -> None:
        agent_id, token = registered_agent

        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            msg = ws.receive_json()
            assert msg["type"] == "registered"
            assert msg["agent_id"] == agent_id

            ws.send_json({"type": "heartbeat"})
            # heartbeat has no response — just verify no error is received
            # (the server updates last_seen silently)

        # After disconnect, agent should be offline
        resp = client.get(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        agent = next((a for a in resp.json() if a["id"] == agent_id), None)
        assert agent is not None
        assert agent["status"] == "offline"

    def test_ws_invalid_token_rejected(self, client: TestClient) -> None:
        with client.websocket_connect("/v1/agents/ws?token=not-a-valid-token") as ws:
            # Server closes with 4401
            with pytest.raises(Exception):
                ws.receive_json()

    def test_ws_unknown_agent_rejected(
        self, client: TestClient, auth_token: tuple[str, str]
    ) -> None:
        token, _ = auth_token
        fake_agent_id = "00000000-0000-0000-0000-000000000000"

        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": fake_agent_id})
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_agent_appears_in_list_after_ws_register(
        self, client: TestClient, registered_agent: tuple[str, str]
    ) -> None:
        agent_id, token = registered_agent

        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # {"type": "registered"}

            resp = client.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
            agent = next((a for a in resp.json() if a["id"] == agent_id), None)
            assert agent is not None
            assert agent["status"] == "idle"
