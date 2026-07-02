"""
Tests for POST /v1/tasks/{id}/revoke (single-user abort channel) and the
startup purge of soft-deleted agents.
"""

import asyncio
import base64
import os
import secrets
from urllib.parse import urlparse

from starlette.testclient import TestClient


def _rand_pubkey() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def _capabilities() -> dict:
    return {
        "models": ["llama3.1:8b"],
        "default_model": "llama3.1:8b",
        "roles": ["analyst"],
        "tools": [],
        "hardware": {"cpu_cores": 4, "ram_gb": 8},
    }


def _new_user(client: TestClient) -> str:
    resp = client.post("/v1/auth/token", json={"pubkey": _rand_pubkey(), "display_name": "U"})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _register_agent(client: TestClient, token: str) -> str:
    resp = client.post(
        "/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Sage",
            "pubkey": _rand_pubkey(),
            "capabilities": _capabilities(),
            "runtime_version": "gd-0.3.0",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _submit_task(client: TestClient, token: str, agent_id: str) -> dict:
    resp = client.post(
        "/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "assigned_agent_id": agent_id,
            "data_class": "internal",
            "input": {"prompt": "hi"},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestTaskRevoke:
    def test_revoke_pending_task(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        task = _submit_task(client, token, agent_id)  # agent offline → pending

        resp = client.post(f"/v1/tasks/{task['id']}/revoke", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "failed"
        assert body["error"]["code"] == "revoked"
        assert body["completed_at"] is not None

    def test_revoke_running_task_sends_ws_frame(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)

        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            assert ws.receive_json()["type"] == "registered"

            task = _submit_task(client, token, agent_id)
            assert task["status"] == "dispatched"
            assert ws.receive_json()["type"] == "task_push"
            ws.send_json({"type": "task_ack", "task_id": task["id"]})
            for _ in range(20):
                current = client.get(f"/v1/tasks/{task['id']}", headers=_auth(token)).json()
                if current["status"] == "running":
                    break

            resp = client.post(
                f"/v1/tasks/{task['id']}/revoke",
                headers=_auth(token),
                json={"reason": "changed my mind"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "failed"
            assert resp.json()["error"] == {"code": "revoked", "message": "changed my mind"}

            frame = ws.receive_json()
            assert frame["type"] == "revoke"
            assert frame["payload"]["task_id"] == task["id"]
            assert frame["payload"]["reason"] == "submitter_request"

            # A late result from the agent is ignored (task no longer running).
            ws.send_json({
                "type": "result",
                "task_id": task["id"],
                "status": "complete",
                "result": {"output": "too late"},
            })

        final = client.get(f"/v1/tasks/{task['id']}", headers=_auth(token)).json()
        assert final["status"] == "failed"
        assert final["error"]["code"] == "revoked"

    def test_revoke_finished_task_is_409(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        task = _submit_task(client, token, agent_id)
        # Settle it first via revoke, then revoke again.
        assert client.post(f"/v1/tasks/{task['id']}/revoke", headers=_auth(token)).status_code == 200
        resp = client.post(f"/v1/tasks/{task['id']}/revoke", headers=_auth(token))
        assert resp.status_code == 409

    def test_revoke_other_users_task_is_403(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        task = _submit_task(client, token, agent_id)

        other = _new_user(client)
        resp = client.post(f"/v1/tasks/{task['id']}/revoke", headers=_auth(other))
        assert resp.status_code == 403


class TestDeletedAgentPurge:
    def test_purge_removes_agents_without_tasks(self, client: TestClient) -> None:
        token = _new_user(client)
        keeper = _register_agent(client, token)   # deleted, but keeps a task
        goner = _register_agent(client, token)    # deleted, no tasks

        task = _submit_task(client, token, keeper)
        assert client.delete(f"/v1/agents/{keeper}", headers=_auth(token)).status_code == 204
        assert client.delete(f"/v1/agents/{goner}", headers=_auth(token)).status_code == 204

        from orchestrator.main import purge_deleted_agents

        db_url = os.environ["DATABASE_URL"]

        async def _exercise() -> tuple[bool, bool]:
            scheme = urlparse(db_url).scheme
            if scheme in ("postgresql", "postgres"):
                from orchestrator.db.postgres import PostgresDatabase

                db = await PostgresDatabase.connect(db_url)
            else:
                from orchestrator.db.connect import _sqlite_path_from_url
                from orchestrator.db.sqlite import SQLiteDatabase

                db = await SQLiteDatabase.connect(_sqlite_path_from_url(db_url))
            try:
                await purge_deleted_agents(db)
                keeper_exists = await db.fetchval(
                    "SELECT 1 FROM agents WHERE id = $1::uuid", keeper
                )
                goner_exists = await db.fetchval(
                    "SELECT 1 FROM agents WHERE id = $1::uuid", goner
                )
                return bool(keeper_exists), bool(goner_exists)
            finally:
                await db.close()

        keeper_exists, goner_exists = asyncio.run(_exercise())
        # The one with task history survives (FK safety); the other is gone.
        assert keeper_exists
        assert not goner_exists
        # And the surviving task is still readable.
        assert client.get(f"/v1/tasks/{task['id']}", headers=_auth(token)).status_code == 200
