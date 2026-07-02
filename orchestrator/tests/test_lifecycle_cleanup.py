"""
Tests for the desktop lifecycle-cleanup work:

- DELETE /v1/agents/{id} (soft delete): listing exclusion, owner scoping,
  outstanding-task failing, WS register rejection after deletion, live
  connection kick.
- DELETE /v1/tasks/{id} and DELETE /v1/tasks?scope=… (real deletion behind
  the console's Clear buttons, and cancel-a-queued-question).
- The startup status sweep that kills ghost "ready" agents left over from a
  previous orchestrator run.
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


def _register_agent(client: TestClient, token: str, name: str = "Sage") -> str:
    resp = client.post(
        "/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": name,
            "pubkey": _rand_pubkey(),
            "capabilities": _capabilities(),
            "runtime_version": "gd-0.1.0",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _submit_task(client: TestClient, token: str, agent_id: str, prompt: str = "hi") -> dict:
    resp = client.post(
        "/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "assigned_agent_id": agent_id,
            "data_class": "internal",
            "input": {"prompt": prompt},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestAgentDelete:
    def test_delete_removes_from_listing(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)

        resp = client.delete(f"/v1/agents/{agent_id}", headers=_auth(token))
        assert resp.status_code == 204, resp.text

        listing = client.get("/v1/agents", headers=_auth(token))
        assert agent_id not in {a["id"] for a in listing.json()}

        # Deleting again (or patching) is an indistinguishable 404.
        assert client.delete(f"/v1/agents/{agent_id}", headers=_auth(token)).status_code == 404
        assert (
            client.patch(
                f"/v1/agents/{agent_id}", headers=_auth(token), json={"name": "x"}
            ).status_code
            == 404
        )

    def test_delete_other_owners_agent_is_404(self, client: TestClient) -> None:
        owner = _new_user(client)
        agent_id = _register_agent(client, owner)
        other = _new_user(client)

        resp = client.delete(f"/v1/agents/{agent_id}", headers=_auth(other))
        assert resp.status_code == 404, resp.text

        listing = client.get("/v1/agents", headers=_auth(owner))
        assert agent_id in {a["id"] for a in listing.json()}

    def test_delete_fails_outstanding_tasks(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        task = _submit_task(client, token, agent_id)  # agent not connected → pending
        assert task["status"] == "pending"

        resp = client.delete(f"/v1/agents/{agent_id}", headers=_auth(token))
        assert resp.status_code == 204, resp.text

        refreshed = client.get(f"/v1/tasks/{task['id']}", headers=_auth(token)).json()
        assert refreshed["status"] == "failed"
        assert refreshed["error"]["code"] == "agent_removed"

    def test_deleted_agent_cannot_reregister(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        assert client.delete(f"/v1/agents/{agent_id}", headers=_auth(token)).status_code == 204

        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            reply = ws.receive_json()
            assert reply["type"] == "error"
            assert "deleted" in reply["detail"]

    def test_deleted_agent_cannot_receive_tasks(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        assert client.delete(f"/v1/agents/{agent_id}", headers=_auth(token)).status_code == 204

        resp = client.post(
            "/v1/tasks",
            headers=_auth(token),
            json={
                "assigned_agent_id": agent_id,
                "data_class": "internal",
                "input": {"prompt": "hi"},
            },
        )
        assert resp.status_code == 404, resp.text

    def test_delete_kicks_live_connection(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)

        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            assert ws.receive_json()["type"] == "registered"

            resp = client.delete(f"/v1/agents/{agent_id}", headers=_auth(token))
            assert resp.status_code == 204, resp.text

            # The server closes the socket; the next receive surfaces the close.
            import starlette.websockets

            try:
                ws.receive_json()
                raised = False
            except (starlette.websockets.WebSocketDisconnect, Exception):
                raised = True
            assert raised


class TestTaskDelete:
    def test_delete_pending_task_cancels_it(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        task = _submit_task(client, token, agent_id)
        assert task["status"] == "pending"

        resp = client.delete(f"/v1/tasks/{task['id']}", headers=_auth(token))
        assert resp.status_code == 204, resp.text
        assert client.get(f"/v1/tasks/{task['id']}", headers=_auth(token)).status_code == 404

    def test_delete_other_users_task_is_403(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)
        task = _submit_task(client, token, agent_id)

        other = _new_user(client)
        resp = client.delete(f"/v1/tasks/{task['id']}", headers=_auth(other))
        assert resp.status_code == 403, resp.text

    def test_delete_bad_uuid_is_422(self, client: TestClient) -> None:
        token = _new_user(client)
        resp = client.delete("/v1/tasks/not-a-uuid", headers=_auth(token))
        assert resp.status_code == 422

    def test_delete_running_task_is_409(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)

        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            assert ws.receive_json()["type"] == "registered"

            task = _submit_task(client, token, agent_id)
            assert task["status"] == "dispatched"
            push = ws.receive_json()
            assert push["type"] == "task_push"

            ws.send_json({"type": "task_ack", "task_id": task["id"]})
            # task_ack has no reply frame; poll REST for the running flip.
            for _ in range(20):
                current = client.get(f"/v1/tasks/{task['id']}", headers=_auth(token)).json()
                if current["status"] == "running":
                    break

            resp = client.delete(f"/v1/tasks/{task['id']}", headers=_auth(token))
            assert resp.status_code == 409, resp.text

    def test_bulk_delete_scopes(self, client: TestClient) -> None:
        token = _new_user(client)
        agent_id = _register_agent(client, token)

        # One FAILED task (agent connected: dispatch → ack → result failed)...
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            assert ws.receive_json()["type"] == "registered"
            failed_task = _submit_task(client, token, agent_id, prompt="will fail")
            assert ws.receive_json()["type"] == "task_push"
            ws.send_json({"type": "task_ack", "task_id": failed_task["id"]})
            ws.send_json({
                "type": "result",
                "task_id": failed_task["id"],
                "status": "failed",
                "result": None,
                "error": {"code": "ollama_error", "message": "boom"},
            })
            for _ in range(20):
                current = client.get(f"/v1/tasks/{failed_task['id']}", headers=_auth(token)).json()
                if current["status"] == "failed":
                    break
            assert current["status"] == "failed"

        # ...and one PENDING task (agent disconnected again by now).
        pending_task = _submit_task(client, token, agent_id, prompt="queued")

        resp = client.delete("/v1/tasks?scope=failed", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] >= 1
        assert client.get(f"/v1/tasks/{failed_task['id']}", headers=_auth(token)).status_code == 404
        # The pending one survives scope=failed…
        assert client.get(f"/v1/tasks/{pending_task['id']}", headers=_auth(token)).status_code == 200

        # …and goes with scope=all.
        resp = client.delete("/v1/tasks?scope=all", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert client.get(f"/v1/tasks/{pending_task['id']}", headers=_auth(token)).status_code == 404

    def test_bulk_delete_bad_scope_is_422(self, client: TestClient) -> None:
        token = _new_user(client)
        resp = client.delete("/v1/tasks?scope=everything", headers=_auth(token))
        assert resp.status_code == 422


class TestStartupSweep:
    def test_sweep_marks_stale_statuses_offline(self, client: TestClient) -> None:
        """A non-offline status row with no live connection is a leftover from
        a previous orchestrator run; the startup sweep must flip it offline."""
        token = _new_user(client)
        agent_id = _register_agent(client, token)

        from orchestrator.main import sweep_stale_agent_statuses

        db_url = os.environ["DATABASE_URL"]

        async def _exercise() -> str:
            # An independent connection (no shared globals with the app).
            scheme = urlparse(db_url).scheme
            if scheme in ("postgresql", "postgres"):
                from orchestrator.db.postgres import PostgresDatabase

                db = await PostgresDatabase.connect(db_url)
            else:
                from orchestrator.db.connect import _sqlite_path_from_url
                from orchestrator.db.sqlite import SQLiteDatabase

                db = await SQLiteDatabase.connect(_sqlite_path_from_url(db_url))
            try:
                # Simulate the pre-restart leftover: agent looks "ready".
                await db.execute(
                    "UPDATE agents SET status = 'idle' WHERE id = $1::uuid", agent_id
                )
                swept = await sweep_stale_agent_statuses(db)
                assert swept >= 1
                return await db.fetchval(
                    "SELECT status FROM agents WHERE id = $1::uuid", agent_id
                )
            finally:
                await db.close()

        final_status = asyncio.run(_exercise())
        assert final_status == "offline"
