"""
Smoke tests: auth token issuance, agent registration, duplicate rejection, GET /agents.
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
        "hardware": {"cpu_cores": 8, "ram_gb": 16},
    }


class TestAuthToken:
    def test_new_user_gets_token(self, client: TestClient, pubkey: str) -> None:
        resp = client.post("/v1/auth/token", json={"pubkey": pubkey, "display_name": "Alice"})
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

    def test_short_pubkey_rejected(self, client: TestClient) -> None:
        resp = client.post("/v1/auth/token", json={"pubkey": "too-short", "display_name": "Bad"})
        assert resp.status_code == 422


class TestAgentRegistration:
    def test_register_agent_returns_201(
        self, client: TestClient, auth_token: tuple[str, str]
    ) -> None:
        token, user_id = auth_token
        resp = client.post(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "My Test Agent",
                "pubkey": _rand_pubkey(),
                "capabilities": _capabilities(),
                "runtime_version": "gd-0.1.0",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Test Agent"
        assert data["status"] == "offline"
        assert data["owner_id"] == user_id

    def test_duplicate_pubkey_returns_409(
        self, client: TestClient, auth_token: tuple[str, str]
    ) -> None:
        token, _ = auth_token
        shared_pubkey = _rand_pubkey()
        payload = {
            "name": "Agent Alpha",
            "pubkey": shared_pubkey,
            "capabilities": _capabilities(),
            "runtime_version": "gd-0.1.0",
        }
        r1 = client.post("/v1/agents", headers={"Authorization": f"Bearer {token}"}, json=payload)
        r2 = client.post("/v1/agents", headers={"Authorization": f"Bearer {token}"}, json=payload)
        assert r1.status_code == 201
        assert r2.status_code == 409

    def test_invalid_runtime_version_rejected(
        self, client: TestClient, auth_token: tuple[str, str]
    ) -> None:
        token, _ = auth_token
        resp = client.post(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Bad Version",
                "pubkey": _rand_pubkey(),
                "capabilities": _capabilities(),
                "runtime_version": "1.0.0",  # must start with gd-
            },
        )
        assert resp.status_code == 422

    def test_register_without_token_returns_401(self, client: TestClient) -> None:
        # FastAPI's HTTPBearer (auto_error=True) returns 401 for a missing
        # Authorization header on currently-installed fastapi/starlette
        # versions (this test asserted 403 pre-WP-30; confirmed via a clean
        # checkout that the mismatch is a library-version behavior change,
        # not something this work packet introduced — see WP-30 notes).
        resp = client.post(
            "/v1/agents",
            json={
                "name": "No Auth",
                "pubkey": _rand_pubkey(),
                "capabilities": _capabilities(),
                "runtime_version": "gd-0.1.0",
            },
        )
        assert resp.status_code == 401

    def test_list_agents_returns_list(
        self, client: TestClient, auth_token: tuple[str, str]
    ) -> None:
        token, _ = auth_token
        resp = client.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_health_endpoint(self, client: TestClient) -> None:
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in {"ok", "degraded"}
        assert "version" in body
        assert "db" in body
