import json
import logging
from typing import Callable

import anyio
from fastapi import WebSocket, WebSocketDisconnect

from ..connection_manager import manager
from ..database import append_event, get_pool
from ..db import Database
from ..db.util import is_valid_uuid, now_iso
from ..dispatcher import dispatch_pending_for_agent, requeue_or_deadletter
from ..security import verify_token

logger = logging.getLogger(__name__)

# Inbound message types (agent → orchestrator)
_MSG_REGISTER  = "register"
_MSG_HEARTBEAT = "heartbeat"
_MSG_STATUS    = "status_update"
_MSG_TASK_ACK  = "task_ack"
_MSG_PROGRESS  = "progress"
_MSG_RESULT    = "result"

# Statuses an agent may self-report; "offline" is set by the orchestrator only.
_SELF_REPORTABLE_STATUSES = frozenset({"idle", "busy", "degraded", "draining"})

# Maps an agent status to the fleet_event "event" label the console renders.
# (see ConsoleFleetEventMessage in spec/contracts/wss-messages.schema.json)
_STATUS_EVENT = {
    "idle":     "agent_recovered",
    "busy":     "agent_heartbeat",
    "degraded": "agent_degraded",
    "draining": "agent_draining",
    "offline":  "agent_offline",
}


async def broadcast_fleet_event(
    pool: Database, agent_id: str, owner_id: str, event: str, status: str
) -> None:
    """Push a fleet_event to every console owned by the agent's owner.

    Keeps the console fleet view live without polling: agents that connect,
    change status, or drop off after the initial fleet_snapshot are reflected
    immediately. Best-effort — a console with no open WS simply misses it.
    """
    try:
        row = await pool.fetchrow(
            "SELECT name, location_tag, last_seen::text FROM agents WHERE id = $1::uuid",
            agent_id,
        )
        running = await pool.fetchval(
            "SELECT COUNT(*) FROM tasks "
            "WHERE assigned_agent_id = $1::uuid AND status IN ('dispatched', 'running')",
            agent_id,
        )
        await manager.broadcast_to_user(owner_id, {
            "type": "fleet_event",
            "payload": {
                "agent_id": agent_id,
                "event": event,
                "status": status,
                "name": row["name"] if row else None,
                "location_tag": row["location_tag"] if row else None,
                "running_task_count": int(running or 0),
                "last_seen": row["last_seen"] if row else None,
            },
        })
    except Exception:
        logger.warning("Could not broadcast fleet_event for agent %s", agent_id)


async def handle_agent_ws(websocket: WebSocket, token: str) -> None:
    """Handle the full lifecycle of one agent WebSocket connection.

    Protocol (agent → orchestrator):
      1. Agent connects: GET /v1/agents/ws?token=<jwt>
      2. Agent sends:    {"type": "register", "agent_id": "<uuid>"}
      3. Orchestrator:   {"type": "registered", "agent_id": "<uuid>"}  → status: idle
                         Orchestrator dispatches any pending tasks immediately.
      4. Agent sends:    {"type": "heartbeat"}  every ~30 s (no response frame)
      5. Agent sends:    {"type": "status_update", "status": "busy|idle|degraded|draining"}
      6. Agent sends:    {"type": "task_ack", "task_id": "<uuid>"}  → task status: running
      7. Agent sends:    {"type": "progress", "task_id": "<uuid>", "text": "..."}  (log)
      8. Agent sends:    {"type": "result", "task_id": "<uuid>",
                          "status": "complete"|"failed",
                          "result": {...}|null, "error": {...}|null}
      9. Disconnect:     active tasks requeued or dead-lettered; status → offline

    The JWT must be the token issued to the agent's owner via POST /v1/auth/token.
    ed25519 challenge-response replaces the JWT stub at WP-07.
    """
    # Validate the token before completing the upgrade handshake.
    # Starlette requires accept() before close(), so we accept then reject.
    try:
        payload = verify_token(token)
        user_id: str = payload["sub"]
    except ValueError:
        await websocket.accept()
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    await websocket.accept()

    pool = get_pool()
    agent_id: str | None = None

    try:
        while True:
            try:
                msg: dict = await websocket.receive_json()
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "message must be valid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == _MSG_REGISTER:
                def _set_agent_id(value: str) -> None:
                    nonlocal agent_id
                    agent_id = value
                await _handle_register(websocket, pool, user_id, msg, _set_agent_id)

            elif msg_type == _MSG_HEARTBEAT:
                if agent_id is None:
                    await websocket.send_json({"type": "error", "detail": "send register before heartbeat"})
                else:
                    await _handle_heartbeat(pool, agent_id)

            elif msg_type == _MSG_STATUS:
                if agent_id is None:
                    await websocket.send_json({"type": "error", "detail": "send register before status_update"})
                else:
                    await _handle_status_update(websocket, pool, agent_id, user_id, msg)

            elif msg_type == _MSG_TASK_ACK:
                if agent_id is None:
                    await websocket.send_json({"type": "error", "detail": "send register before task_ack"})
                else:
                    await _handle_task_ack(pool, agent_id, msg)

            elif msg_type == _MSG_PROGRESS:
                if agent_id is None:
                    await websocket.send_json({"type": "error", "detail": "send register before progress"})
                else:
                    await _handle_progress(pool, agent_id, msg)

            elif msg_type == _MSG_RESULT:
                if agent_id is None:
                    await websocket.send_json({"type": "error", "detail": "send register before result"})
                else:
                    await _handle_result(pool, agent_id, user_id, msg)

            else:
                await websocket.send_json({"type": "error", "detail": f"unknown message type: {msg_type!r}"})

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected error on agent WS (agent_id=%s)", agent_id)
    finally:
        if agent_id:
            # Disconnect cleanup must complete even if this task's own scope
            # is being cancelled (e.g. server shutdown, or — confirmed by
            # direct testing — Starlette's TestClient WebSocket session,
            # whose __exit__ cancels an anyio CancelScope around the same
            # time it delivers the disconnect message). anyio enforces
            # cancellation at EVERY checkpoint within a cancelled scope, so
            # plain asyncio.shield() is not sufficient here — it creates a
            # new asyncio Task but does not escape anyio's own scope-based
            # cancellation tracking. anyio.CancelScope(shield=True) is the
            # construct anyio provides specifically for this: cleanup code
            # that must run to completion regardless of the enclosing
            # scope's cancellation state.
            with anyio.CancelScope(shield=True):
                await _cleanup_on_disconnect(pool, agent_id, user_id)


async def _cleanup_on_disconnect(pool: Database, agent_id: str, user_id: str) -> None:
    try:
        await requeue_or_deadletter(pool, agent_id)
    except Exception:
        logger.warning("Could not requeue tasks for agent %s", agent_id)
    manager.disconnect(agent_id)
    await _set_status(pool, agent_id, "offline")
    try:
        await append_event(pool, actor_id=user_id, action="agent.disconnected", subject_id=agent_id)
    except Exception:
        logger.warning("Could not append disconnect event for agent %s", agent_id)
    await broadcast_fleet_event(pool, agent_id, user_id, "agent_offline", "offline")
    logger.info("Agent %s offline (owner=%s)", agent_id, user_id)


async def _handle_register(
    websocket: WebSocket,
    pool: Database,
    user_id: str,
    msg: dict,
    set_agent_id: Callable[[str], None],
) -> None:
    agent_id = msg.get("agent_id", "")
    if not agent_id:
        await websocket.send_json({"type": "error", "detail": "agent_id is required"})
        return

    if not is_valid_uuid(agent_id):
        await websocket.send_json({"type": "error", "detail": "agent_id must be a valid UUID"})
        return

    row = await pool.fetchrow(
        "SELECT id::text, owner_id::text, deleted_at::text FROM agents WHERE id = $1::uuid",
        agent_id,
    )

    if row is None:
        await websocket.send_json({"type": "error", "detail": "agent not found"})
        return

    if row["owner_id"] != user_id:
        await websocket.send_json({"type": "error", "detail": "forbidden"})
        return

    if row["deleted_at"]:
        # The agent was removed via DELETE /v1/agents/{id}. Rejecting the
        # registration is what makes deletion stick for a runtime process
        # that is still alive somewhere: it treats this as fatal and exits
        # (see agent-runtime/ws_client.py RegistrationRejected).
        await websocket.send_json({
            "type": "error",
            "detail": "agent deleted — this agent was removed and can no longer connect",
        })
        return

    if manager.is_connected(agent_id):
        # Agent is reconnecting after a crash or network blip; replace the stale entry.
        manager.disconnect(agent_id)
        logger.info("Agent %s re-registering — replacing stale connection", agent_id)

    manager.connect(agent_id, websocket)
    await _set_status(pool, agent_id, "idle")
    await append_event(pool, actor_id=user_id, action="agent.connected", subject_id=agent_id)

    # The agent is logically connected as of here: tracked in
    # ConnectionManager and marked idle in the DB. Tell the caller now,
    # before doing the best-effort follow-up below (ack, console notify,
    # queue drain). If the connection drops or this coroutine is cancelled
    # partway through that follow-up, the caller's disconnect handler still
    # needs to know this agent_id to mark it offline and requeue its tasks
    # — otherwise a client that disconnects immediately after registering
    # leaves a phantom "idle" agent that's never cleaned up. (Confirmed via
    # a clean pre-WP-30 checkout that this race pre-dates this work packet;
    # not something introduced here.)
    set_agent_id(agent_id)

    await websocket.send_json({"type": "registered", "agent_id": agent_id})
    logger.info("Agent %s online (owner=%s)", agent_id, user_id)

    # Tell the owner's console(s) the agent is live now (the initial
    # fleet_snapshot was sent when the console connected, possibly before this).
    await broadcast_fleet_event(pool, agent_id, user_id, "agent_registered", "idle")

    # Drain any tasks that arrived while this agent was offline.
    await dispatch_pending_for_agent(pool, manager, agent_id)


async def _handle_heartbeat(pool: Database, agent_id: str) -> None:
    manager.record_heartbeat(agent_id)
    await pool.execute(
        "UPDATE agents SET last_seen = $2 WHERE id = $1::uuid", agent_id, now_iso()
    )


async def _handle_status_update(
    websocket: WebSocket,
    pool: Database,
    agent_id: str,
    user_id: str,
    msg: dict,
) -> None:
    new_status = msg.get("status")
    if new_status not in _SELF_REPORTABLE_STATUSES:
        await websocket.send_json({
            "type": "error",
            "detail": f"invalid status {new_status!r}; allowed: {sorted(_SELF_REPORTABLE_STATUSES)}",
        })
        return
    await _set_status(pool, agent_id, new_status)
    await append_event(
        pool,
        actor_id=user_id,
        action="agent.status_changed",
        subject_id=agent_id,
        metadata={"status": new_status},
    )
    await broadcast_fleet_event(
        pool, agent_id, user_id,
        _STATUS_EVENT.get(new_status, "agent_heartbeat"), new_status,
    )


async def _handle_task_ack(
    pool: Database,
    agent_id: str,
    msg: dict,
) -> None:
    """Mark a dispatched task as running once the agent acknowledges receipt."""
    task_id = msg.get("task_id", "")
    if not task_id or not is_valid_uuid(task_id):
        logger.warning("task_ack from agent %s missing/invalid task_id", agent_id)
        return
    updated = await pool.fetchval(
        """
        UPDATE tasks SET status = 'running'
        WHERE id = $1::uuid
          AND assigned_agent_id = $2::uuid
          AND status = 'dispatched'
        RETURNING id::text
        """,
        task_id,
        agent_id,
    )
    if updated:
        logger.debug("Task %s running on agent %s", task_id, agent_id)
    else:
        logger.warning("task_ack ignored for task %s (not dispatched to agent %s)", task_id, agent_id)


async def _handle_progress(pool: Database, agent_id: str, msg: dict) -> None:
    """Forward a progress frame from the agent to the task submitter's console."""
    task_id = msg.get("task_id", "?")
    partial = msg.get("partial_output") or msg.get("text") or None
    elapsed = msg.get("elapsed_ms", 0)
    step = msg.get("step")
    tokens = msg.get("tokens_so_far")

    logger.info("Progress task=%s agent=%s: %s", task_id, agent_id, (partial or step or "")[:200])

    if not is_valid_uuid(task_id):
        return

    row = await pool.fetchrow(
        "SELECT submitter_id::text FROM tasks WHERE id = $1::uuid", task_id
    )
    if row:
        await manager.broadcast_to_user(row["submitter_id"], {
            "type": "task_progress",
            "payload": {
                "task_id": task_id,
                "agent_id": agent_id,
                "elapsed_ms": elapsed,
                "step": step,
                "tokens_so_far": tokens,
                "partial_output": partial,
            },
        })


async def _handle_result(
    pool: Database,
    agent_id: str,
    user_id: str,
    msg: dict,
) -> None:
    """Record a task result (complete or failed) received from the agent."""
    task_id = msg.get("task_id", "")
    terminal_status = msg.get("status")
    if not task_id or terminal_status not in ("complete", "failed") or not is_valid_uuid(task_id):
        logger.warning(
            "Invalid result frame from agent %s: task_id=%r status=%r",
            agent_id, task_id, terminal_status,
        )
        return

    result_payload = msg.get("result")
    error_payload  = msg.get("error")

    updated = await pool.fetchval(
        """
        UPDATE tasks
        SET status       = $3,
            completed_at = $6,
            result       = $4::jsonb,
            error        = $5::jsonb
        WHERE id                = $1::uuid
          AND assigned_agent_id = $2::uuid
          AND status            = 'running'
        RETURNING id::text
        """,
        task_id,
        agent_id,
        terminal_status,
        result_payload,
        error_payload,
        now_iso(),
    )
    if updated:
        action = "task.completed" if terminal_status == "complete" else "task.failed"
        await append_event(
            pool,
            actor_id=user_id,
            action=action,
            subject_id=task_id,
            metadata={"agent_id": agent_id},
        )
        logger.info("Task %s %s (agent=%s)", task_id, terminal_status, agent_id)

        # Relay terminal status to the submitter's open console connections.
        output_preview: str | None = None
        duration_ms: int | None = None
        model_used: str | None = None
        if isinstance(result_payload, dict):
            raw_output = result_payload.get("output", "")
            if raw_output:
                output_preview = str(raw_output)[:256]
            duration_ms = result_payload.get("duration_ms")
            model_used = result_payload.get("model_used")
        error_code: str | None = None
        if isinstance(error_payload, dict):
            error_code = error_payload.get("code")

        await manager.broadcast_to_user(user_id, {
            "type": "task_complete",
            "payload": {
                "task_id": task_id,
                "agent_id": agent_id,
                "final_status": terminal_status,
                "duration_ms": duration_ms,
                "model_used": model_used,
                "error_code": error_code,
                "output_preview": output_preview,
            },
        })
    else:
        logger.warning(
            "result ignored for task %s (not running on agent %s)", task_id, agent_id
        )


async def _set_status(pool: Database, agent_id: str, status: str) -> None:
    await pool.execute(
        "UPDATE agents SET status = $1, last_seen = $3 WHERE id = $2::uuid",
        status,
        agent_id,
        now_iso(),
    )
