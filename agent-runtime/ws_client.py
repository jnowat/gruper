"""
Persistent outbound WebSocket client for the Gruper Agent Runtime.

Connection lifecycle
--------------------
1. Connect to orchestrator with JWT in query string.
2. Send {"type": "register", "agent_id": "<uuid>"} and wait for "registered".
3. Drain the offline queue (tasks that accumulated while disconnected).
4. Run the heartbeat loop (every HEARTBEAT_INTERVAL_S seconds).
5. Dispatch incoming "task_push" frames to the task executor.
6. On disconnect, cancel the heartbeat task and retry with exponential backoff:
   2 s → 4 s → 8 s → 16 s → 16 s … (mirrors Gruper core's retry schedule).

Graceful shutdown
-----------------
Call stop(). In-flight asyncio tasks are cancelled and their payloads are
checkpointed to the offline queue so they are retried on reconnect.
"""

import asyncio
import json
import logging
import time

import websockets
from websockets.exceptions import ConnectionClosed

from circuit_breaker import CircuitBreaker
from config import settings
from offline_queue import OfflineQueue
from ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# Exponential backoff delays (seconds) — mirrors Gruper core.
_BACKOFF = [2, 4, 8, 16]


class AgentWSClient:
    def __init__(self) -> None:
        self._ollama = OllamaClient(settings.ollama_url)
        self._queue = OfflineQueue(settings.db_path)
        self._cb = CircuitBreaker(
            on_open=self._on_circuit_open,
            on_close=self._on_circuit_close,
        )
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._running = False
        self._heartbeat_task: asyncio.Task | None = None
        self._in_flight: dict[str, asyncio.Task] = {}

    # ── Public interface ──────────────────────────────────────────────────────

    async def start(self) -> None:
        await self._queue.open()
        self._running = True
        attempt = 0
        while self._running:
            try:
                await self._connect()
                attempt = 0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
                logger.warning(
                    "Orchestrator connection failed (%s); retrying in %ds", exc, delay
                )
                attempt += 1
                await asyncio.sleep(delay)

        await self._checkpoint_in_flight()
        await self._queue.close()
        logger.info("Agent runtime stopped cleanly")

    async def stop(self) -> None:
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def _connect(self) -> None:
        url = f"{settings.orchestrator_url}?token={settings.jwt_token}"
        logger.info("Connecting to %s", settings.orchestrator_url)
        async with websockets.connect(url) as ws:
            self._ws = ws
            await self._register(ws)
            await self._drain_queue()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
            try:
                async for raw in ws:
                    await self._dispatch(raw)
            finally:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
                self._ws = None

    async def _register(self, ws: websockets.WebSocketClientProtocol) -> None:
        await ws.send(json.dumps({
            "type": "register",
            "agent_id": settings.agent_id,
        }))
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("type") == "registered":
            logger.info("Registered with orchestrator (agent_id=%s)", settings.agent_id)
        elif msg.get("type") == "error":
            raise RuntimeError(f"Registration rejected: {msg.get('detail')}")
        else:
            raise RuntimeError(f"Unexpected registration response: {msg}")

    async def _heartbeat_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        while True:
            await asyncio.sleep(settings.heartbeat_interval_s)
            try:
                await ws.send(json.dumps({"type": "heartbeat"}))
            except ConnectionClosed:
                break

    # ── Queue drain ───────────────────────────────────────────────────────────

    async def _drain_queue(self) -> None:
        count = await self._queue.size()
        if count == 0:
            return
        logger.info("Draining %d queued task(s)", count)
        async for task_id, payload in self._queue.drain():
            await self._run_task(task_id, payload, from_queue=True)

    # ── Incoming message dispatch ─────────────────────────────────────────────

    async def _dispatch(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Malformed frame from orchestrator: %r", raw)
            return

        msg_type = msg.get("type")
        if msg_type == "task_push":
            # The orchestrator sends {"type":"task_push","task":{...},"ack_deadline_s":N}.
            # The task UUID is task["id"] — there is no top-level "task_id" field.
            task = msg.get("task") or {}
            task_id = task.get("id", "")
            if not task_id:
                logger.warning("task_push received with no task.id — ignored")
                return
            runner = asyncio.create_task(self._run_task(task_id, task, from_queue=False))
            self._in_flight[task_id] = runner
            runner.add_done_callback(lambda _: self._in_flight.pop(task_id, None))
        elif msg_type in ("registered", "heartbeat_ack"):
            pass  # 'registered' is consumed in _register; heartbeat_ack needs no action
        elif msg_type == "error":
            logger.warning("Orchestrator error: %s", msg.get("detail"))
        else:
            logger.debug("Ignored orchestrator frame type=%r", msg_type)

    # ── Task execution ────────────────────────────────────────────────────────

    async def _run_task(
        self, task_id: str, task: dict, *, from_queue: bool
    ) -> None:
        """Execute one task: ack → stream from Ollama → report result.

        `task` is the full Task record from the orchestrator's task_push
        (task["input"] is a TaskInputPlaintext: prompt/system_prompt/
        role_template/model_preferences). The same shape is checkpointed to the
        offline queue, so drained tasks re-enter here unchanged.
        """
        if self._cb.is_open:
            logger.warning("Circuit open — queuing task %s", task_id)
            if not from_queue:
                await self._queue.enqueue(task_id, task)
            return

        # Acknowledge receipt FIRST: the orchestrator only transitions the task
        # dispatched → running on task_ack, and rejects results for tasks that
        # are not 'running'. Skipping this silently drops the result.
        await self._send({"type": "task_ack", "task_id": task_id})

        task_input = task.get("input") or {}
        model, options = self._model_and_options(task_input)
        messages = self._build_messages(task_input)
        started = time.monotonic()

        try:
            parts: list[str] = []
            async for chunk in self._ollama.chat(messages, model=model, options=options):
                parts.append(chunk)
                await self._send({
                    "type": "progress",
                    "task_id": task_id,
                    "partial_output": chunk,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "tokens_so_far": len(parts),
                })

            await self._send({
                "type": "result",
                "task_id": task_id,
                "status": "complete",
                "result": {
                    "output": "".join(parts),
                    "model_used": model,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "tokens_used": len(parts),
                },
            })
            await self._cb.record_success()
            if from_queue:
                await self._queue.mark_complete(task_id)

        except asyncio.CancelledError:
            # Checkpoint for retry on reconnect.
            if not from_queue:
                await self._queue.enqueue(task_id, task)
            raise

        except Exception as exc:
            logger.error("Task %s failed: %s", task_id, exc)
            await self._cb.record_failure()
            if not from_queue:
                await self._queue.enqueue(task_id, task)
            await self._send({
                "type": "result",
                "task_id": task_id,
                "status": "failed",
                "error": {"code": "ollama_error", "message": str(exc)},
            })

    # Gruper core model_preferences → Ollama option fields (see ollama_client.py
    # and spec/contracts/core-mapping.md for the canonical mapping).
    _OPTION_MAP = {
        "temperature":    "temperature",
        "top_p":          "top_p",
        "top_k":          "top_k",
        "repeat_penalty": "repeat_penalty",
        "max_tokens":     "num_predict",
        "context_length": "num_ctx",
        "seed":           "seed",
    }

    def _model_and_options(self, task_input: dict) -> tuple[str, dict]:
        prefs = task_input.get("model_preferences") or {}
        model = prefs.get("name") or "llama3.1:8b"
        options = {
            ollama_key: prefs[core_key]
            for core_key, ollama_key in self._OPTION_MAP.items()
            if prefs.get(core_key) is not None
        }
        return model, options

    @staticmethod
    def _build_messages(task_input: dict) -> list[dict]:
        """Build the Ollama messages array from a TaskInputPlaintext.

        system_prompt (or a role-template-derived default) becomes the system
        message; prompt becomes the final user message — matching the contract
        described in task.schema.json.
        """
        system = task_input.get("system_prompt")
        if not system:
            role = task_input.get("role_template", "analyst")
            system = f"You are a focused {role} assistant. Respond concisely."
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": task_input.get("prompt", "")},
        ]

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _send(self, msg: dict) -> None:
        if self._ws:
            try:
                await self._ws.send(json.dumps(msg))
            except ConnectionClosed:
                pass

    async def _on_circuit_open(self) -> None:
        await self._send({"type": "status_update", "status": "degraded"})

    async def _on_circuit_close(self) -> None:
        await self._send({"type": "status_update", "status": "idle"})

    async def _checkpoint_in_flight(self) -> None:
        if not self._in_flight:
            return
        logger.info(
            "Checkpointing %d in-flight task(s) to offline queue", len(self._in_flight)
        )
        for task in list(self._in_flight.values()):
            task.cancel()
        await asyncio.gather(*self._in_flight.values(), return_exceptions=True)
