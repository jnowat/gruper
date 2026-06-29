"""
Smoke tests: user registration flow, JWT issuance, agent registration, GET /agents.
"""

import pytest
from starlette.testclient import TestClient


def _capabilities() -> dict:
    return {
        "models": ["llama3.1:8b"],
        "roles": ["analyst"],
        "tools": [],
        "hardware": {"cpu_cores": 8, "ram_gb": 16},
    }


class TestAuthToken:
    def test_new_user_gets_token(self, client: TestClient, pubkey: str) -> None:
        resp = client.post(
            "/v1/auth/token",
            json={"pubkey": pubkey, "display_name": "Alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert "user_id" in data
        assert "expires_at" in data

    def test_same_pubkey_returns_same_user(self, client: TestClient, pubkey: str) -> None:
        r1 = client.post("/v1/auth/token", json={"pubkey": pubkey, "display_name": "Alice"})
        r2 = client.post("/v1/auth/token", json={"pubkey": pubkey, "display_name": "Alice Again"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["user_id"] == r2.json()["user_id"]

    def test_invalid_pubkey_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/auth/token",
            json={"pubkey": "too-short", "display_name": "Bad"},
        )
        assert resp.status_code == 422


class TestAgentRegistration:
    def test_register_agent(self, client: TestClient, auth_token: tuple[str, str], pubkey: str) -> None:
        token, user_id = auth_token
        import base64, secrets
        agent_pubkey = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()

        resp = client.post(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "My Test Agent",
                "pubkey": agent_pubkey,
                "capabilities": _capabilities(),
                "runtime_version": "gd-0.1.0",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Test Agent"
        assert data["status"] == "offline"
        assert data["owner_id"] == user_id

    def test_duplicate_pubkey_rejected(self, client: TestClient, auth_token: tuple[str, str]) -> None:
        token, _ = auth_token
        import base64, secrets
        agent_pubkey = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()

        payload = {
            "name": "Agent Alpha",
            "pubkey": agent_pubkey,
            "capabilities": _capabilities(),
            "runtime_version": "gd-0.1.0",
        }
        r1 = client.post("/v1/agents", headers={"Authorization": f"Bearer {token}"}, json=payload)
        r2 = client.post("/v1/agents", headers={"Authorization": f"Bearer {token}"}, json=payload)
        assert r1.status_code == 201
        assert r2.status_code == 409

    def test_register_requires_auth(self, client: TestClient) -> None:
        import base64, secrets
        agent_pubkey = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()

        resp = client.post(
            "/v1/agents",
            json={
                "name": "Unauthorised",
                "pubkey": agent_pubkey,
                "capabilities": _capabilities(),
                "runtime_version": "gd-0.1.0",
            },
        )
        assert resp.status_code == 403

    def test_list_agents(self, client: TestClient, auth_token: tuple[str, str]) -> None:
        token, _ = auth_token
        resp = client.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_health(self, client: TestClient) -> None:
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] in {"ok", "degraded"}
