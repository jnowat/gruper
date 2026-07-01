"""
Smoke tests: task submission, dispatch, lifecycle, retry, and idempotency.
"""

import base64
import secrets
import time
import uuid

import pytest
from starlette.testclient import TestClient


def _rand_pubkey() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def _wait_for_server_processing() -> None:
    """Give the ASGI app's background-thread event loop a moment to process
    a just-sent WebSocket frame before asserting on its side effect.

    Starlette's TestClient runs the app in a separate thread via a blocking
    portal. `ws.send_json()` only guarantees the frame was handed to that
    thread's receive queue — not that the server's `while True:
    receive_json()` loop has resumed and finished handling it. Messages
    with no response frame (task_ack, result) have no built-in
    synchronization point, unlike `register` (which the tests already wait
    on via `ws.receive_json()`). This is a pre-existing gap in the test
    harness's synchronization (confirmed by reproducing the same failures
    against unmodified pre-WP-30 code and a live PostgreSQL backend — it is
    not specific to SQLite or to this work packet), made newly visible by
    the currently-installed anyio/starlette versions' scheduling behavior.
    A short real-time sleep is safe here because the portal runs on its own
    thread and keeps making progress while this thread sleeps.
    """
    time.sleep(0.05)


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
            "name": "Task Test Agent",
            "pubkey": _rand_pubkey(),
            "capabilities": _capabilities(),
            "runtime_version": "gd-0.2.0",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"], token


def _submit_task(
    client: TestClient,
    token: str,
    agent_id: str,
    *,
    correlation_id: str | None = None,
    priority: int = 50,
) -> dict:
    body = {
        "assigned_agent_id": agent_id,
        "data_class": "internal",
        "input": {"prompt": "Hello, agent!"},
        "priority": priority,
        "timeout_s": 60,
    }
    if correlation_id is not None:
        body["correlation_id"] = correlation_id
    resp = client.post(
        "/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    return resp


def _get_task(client: TestClient, token: str, task_id: str) -> dict:
    resp = client.get(
        f"/v1/tasks/{task_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    return resp.json()


class TestTaskSubmit:
    def test_submit_agent_offline_returns_pending(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        """Task submitted while agent is offline should be pending."""
        agent_id, token = registered_agent
        resp = _submit_task(client, token, agent_id)
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["assigned_agent_id"] == agent_id

    def test_submit_invalid_agent_uuid_returns_422(
        self,
        client: TestClient,
        auth_token: tuple[str, str],
    ) -> None:
        token, _ = auth_token
        resp = client.post(
            "/v1/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "assigned_agent_id": "not-a-uuid",
                "data_class": "internal",
                "input": {"prompt": "Hi"},
                "timeout_s": 60,
            },
        )
        assert resp.status_code == 422

    def test_submit_nonexistent_agent_returns_404(
        self,
        client: TestClient,
        auth_token: tuple[str, str],
    ) -> None:
        token, _ = auth_token
        resp = client.post(
            "/v1/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "assigned_agent_id": str(uuid.uuid4()),
                "data_class": "internal",
                "input": {"prompt": "Hi"},
                "timeout_s": 60,
            },
        )
        assert resp.status_code == 404

    def test_submit_other_users_agent_returns_403(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        """A user cannot submit tasks to an agent they do not own."""
        agent_id, _ = registered_agent
        # Register a different user
        other_token = client.post(
            "/v1/auth/token",
            json={"pubkey": _rand_pubkey(), "display_name": "Other User"},
        ).json()["token"]
        resp = client.post(
            "/v1/tasks",
            headers={"Authorization": f"Bearer {other_token}"},
            json={
                "assigned_agent_id": agent_id,
                "data_class": "internal",
                "input": {"prompt": "Hi"},
                "timeout_s": 60,
            },
        )
        assert resp.status_code == 403

    def test_submit_invalid_data_class_returns_422(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        agent_id, token = registered_agent
        resp = client.post(
            "/v1/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "assigned_agent_id": agent_id,
                "data_class": "top-secret",
                "input": {"prompt": "Hi"},
                "timeout_s": 60,
            },
        )
        assert resp.status_code == 422

    def test_correlation_id_idempotency(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        """Two submissions with the same correlation_id return the same task."""
        agent_id, token = registered_agent
        corr_id = str(uuid.uuid4())
        resp1 = _submit_task(client, token, agent_id, correlation_id=corr_id)
        resp2 = _submit_task(client, token, agent_id, correlation_id=corr_id)
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] == resp2.json()["id"]

    def test_invalid_correlation_id_returns_422(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        agent_id, token = registered_agent
        resp = _submit_task(client, token, agent_id, correlation_id="not-a-uuid")
        assert resp.status_code == 422


class TestTaskGet:
    def test_get_own_task(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        agent_id, token = registered_agent
        task_id = _submit_task(client, token, agent_id).json()["id"]
        data = _get_task(client, token, task_id)
        assert data["id"] == task_id

    def test_get_other_users_task_returns_403(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        agent_id, token = registered_agent
        task_id = _submit_task(client, token, agent_id).json()["id"]
        other_token = client.post(
            "/v1/auth/token",
            json={"pubkey": _rand_pubkey(), "display_name": "Spy"},
        ).json()["token"]
        resp = client.get(
            f"/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    def test_get_missing_task_returns_404(
        self,
        client: TestClient,
        auth_token: tuple[str, str],
    ) -> None:
        token, _ = auth_token
        resp = client.get(
            f"/v1/tasks/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_get_invalid_uuid_returns_422(
        self,
        client: TestClient,
        auth_token: tuple[str, str],
    ) -> None:
        token, _ = auth_token
        resp = client.get(
            "/v1/tasks/not-a-uuid",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_list_tasks_returns_own_tasks_only(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        agent_id, token = registered_agent
        task_id = _submit_task(client, token, agent_id).json()["id"]

        # Owner can see it
        resp = client.get("/v1/tasks", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()]
        assert task_id in ids

        # Other user sees empty list (or at least not this task)
        other_token = client.post(
            "/v1/auth/token",
            json={"pubkey": _rand_pubkey(), "display_name": "Other"},
        ).json()["token"]
        resp2 = client.get("/v1/tasks", headers={"Authorization": f"Bearer {other_token}"})
        assert resp2.status_code == 200
        other_ids = [t["id"] for t in resp2.json()]
        assert task_id not in other_ids


class TestTaskDispatch:
    def test_submit_while_agent_connected_dispatches_immediately(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        """When agent is online during submit, task is pushed over WS and status=dispatched."""
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # "registered"

            # Submit task via REST while WS is open
            resp = _submit_task(client, token, agent_id)
            assert resp.status_code == 201
            assert resp.json()["status"] == "dispatched"

            # Agent should receive a task_push frame
            msg = ws.receive_json()
        assert msg["type"] == "task_push"
        assert msg["task"]["id"] == resp.json()["id"]
        assert "ack_deadline_s" in msg

    def test_submit_offline_then_connect_dispatches_on_register(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        """Tasks submitted while agent is offline are dispatched when agent reconnects."""
        agent_id, token = registered_agent
        # Submit when agent is offline
        resp = _submit_task(client, token, agent_id)
        assert resp.status_code == 201
        task_id = resp.json()["id"]
        assert resp.json()["status"] == "pending"

        # Now connect — dispatch_pending_for_agent should push the task
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            registered_msg = ws.receive_json()
            assert registered_msg["type"] == "registered"

            # Pending task should arrive immediately after registration
            msg = ws.receive_json()
        assert msg["type"] == "task_push"
        assert msg["task"]["id"] == task_id

    def test_task_ack_transitions_to_running(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # "registered"

            resp = _submit_task(client, token, agent_id)
            task_id = resp.json()["id"]
            ws.receive_json()  # consume task_push

            ws.send_json({"type": "task_ack", "task_id": task_id})
            # No response frame for ack; give the server a moment then verify via REST
            _wait_for_server_processing()
            data = _get_task(client, token, task_id)
        assert data["status"] == "running"

    def test_result_complete_closes_task(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # "registered"

            resp = _submit_task(client, token, agent_id)
            task_id = resp.json()["id"]
            ws.receive_json()  # consume task_push

            ws.send_json({"type": "task_ack", "task_id": task_id})
            ws.send_json({
                "type":    "result",
                "task_id": task_id,
                "status":  "complete",
                "result":  {"answer": "42"},
                "error":   None,
            })
            _wait_for_server_processing()
            data = _get_task(client, token, task_id)
        assert data["status"] == "complete"
        assert data["result"] == {"answer": "42"}
        assert data["completed_at"] is not None

    def test_result_failed_closes_task(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # "registered"

            resp = _submit_task(client, token, agent_id)
            task_id = resp.json()["id"]
            ws.receive_json()  # consume task_push

            ws.send_json({"type": "task_ack", "task_id": task_id})
            ws.send_json({
                "type":    "result",
                "task_id": task_id,
                "status":  "failed",
                "result":  None,
                "error":   {"message": "Ollama unavailable"},
            })
            _wait_for_server_processing()
            data = _get_task(client, token, task_id)
        assert data["status"] == "failed"
        assert data["error"] == {"message": "Ollama unavailable"}

    def test_disconnect_requeues_dispatched_task(
        self,
        client: TestClient,
        registered_agent: tuple[str, str],
    ) -> None:
        """On agent disconnect, an unacked task is requeued to pending (retry_count=1)."""
        agent_id, token = registered_agent
        with client.websocket_connect(f"/v1/agents/ws?token={token}") as ws:
            ws.send_json({"type": "register", "agent_id": agent_id})
            ws.receive_json()  # "registered"

            resp = _submit_task(client, token, agent_id)
            task_id = resp.json()["id"]
            ws.receive_json()  # consume task_push — task is now 'dispatched', not acked
        # WS disconnected — requeue_or_deadletter should run in the server's
        # disconnect handler; give it a moment (see _wait_for_server_processing).
        _wait_for_server_processing()

        data = _get_task(client, token, task_id)
        assert data["status"] == "pending"
        assert data["retry_count"] == 1
