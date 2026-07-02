"""
Persistent outbound WebSocket client for the Gruper Agent Runtime.

Connection lifecycle
--------------------
1. Connect to orchestrator with JWT in query string.
2. Send {"type": "register", "agent_id": "<uuid>"} and wait for "registered".
3. Start the heartbeat loop IMMEDIATELY (every HEARTBEAT_INTERVAL_S seconds) —
   nothing may run between register and the first heartbeats, or a slow step
   gets this agent killed by the orchestrator's 90 s heartbeat watchdog.
4. Run a quick Ollama preflight (reachability + installed models) so the log
   says up front whether tasks can actually run.
5. Dispatch incoming "task_push" / "revoke" frames.
6. On disconnect, cancel the heartbeat task and retry with exponential backoff:
   2 s → 4 s → 8 s → 16 s → 16 s … (mirrors Gruper core's retry schedule).

Interrupted work
----------------
The orchestrator is the single source of truth for retries: when this agent
disconnects, it requeues the agent's dispatched/running tasks and re-pushes
them on the next register. The runtime therefore does NOT re-execute work
from its local queue any more — a previous version checkpointed tasks locally
and re-ran the backlog on every reconnect, which duplicated the orchestrator's
own requeue (double execution), burned Ollama on tasks whose results were
rejected as stale, and — because the drain ran between register and the first
heartbeat — could starve heartbeats long enough that the orchestrator killed
the connection mid-drain and the whole cycle repeated. Leftover local queue
entries from older builds are discarded at startup with a log line.
"""

import asyncio
import contextlib
import json
import logging
import time

import websockets
from websockets.exceptions import ConnectionClosed

from circuit_breaker import CircuitBreaker
from config import settings
from offline_queue import OfflineQueue
from ollama_client import OllamaClient, OllamaError

logger = logging.getLogger(__name__)

# Exponential backoff delays (seconds) — mirrors Gruper core.
_BACKOFF = [2, 4, 8, 16]


class RegistrationRejected(RuntimeError):
    """The orchestrator explicitly refused this agent's register frame.

    Every register rejection is identity-level and permanent ("agent not
    found", "forbidden", "agent deleted") — retrying can never succeed, so
    the runtime treats it as fatal and shuts down instead of hammering the
    orchestrator with a doomed reconnect every 16 seconds forever. This is
    also what makes DELETE /v1/agents/{id} stick for a still-running agent:
    the orchestrator closes its socket, the reconnect's register is
    rejected, and the process exits.
    """


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
        # Task ids cancelled via an orchestrator "revoke" frame — the contract
        # says no result may be sent for these (see wss-messages.schema.json).
        self._revoked: set[str] = set()
        # Serialize Ollama calls (default 1): on modest desktop hardware,
        # running several models concurrently thrashes RAM and makes every
        # answer slower than running them back to back.
        self._ollama_sem = asyncio.Semaphore(max(1, settings.ollama_max_concurrency))

    # ── Public interface ──────────────────────────────────────────────────────

    async def start(self) -> None:
        await self._queue.open()
        # See the module docstring: local re-execution is retired; the
        # orchestrator's requeue-on-disconnect is the single retry path.
        leftover = await self._queue.size()
        if leftover:
            logger.warning(
                "Discarding %d checkpointed task(s) from a previous run — "
                "the orchestrator re-dispatches interrupted work itself",
                leftover,
            )
            await self._queue.clear()
        self._running = True
        attempt = 0
        while self._running:
            try:
                await self._connect()
                attempt = 0
            except asyncio.CancelledError:
                break
            except RegistrationRejected as exc:
                logger.error(
                    "Orchestrator permanently rejected this agent's registration (%s) — shutting down",
                    exc,
                )
                self._running = False
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

        await self._cancel_in_flight()
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
            # Heartbeats start before anything else — a slow step here would
            # get this agent declared dead by the orchestrator's watchdog.
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
            try:
                # Registering resets this agent to 'idle' orchestrator-side;
                # if the breaker is open that's a lie — re-assert degraded so
                # the fleet never shows a green dot on a struggling agent.
                if self._cb.is_open:
                    await self._send({"type": "status_update", "status": "degraded"})
                await self._preflight_ollama()
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
            raise RegistrationRejected(str(msg.get("detail")))
        else:
            raise RuntimeError(f"Unexpected registration response: {msg}")

    async def _heartbeat_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        while True:
            await asyncio.sleep(settings.heartbeat_interval_s)
            try:
                await ws.send(json.dumps({"type": "heartbeat"}))
            except ConnectionClosed:
                break

    # ── Ollama preflight ──────────────────────────────────────────────────────

    async def _preflight_ollama(self) -> None:
        """Log up front whether tasks can actually run.

        Cheap (one GET with a 10 s cap) and purely diagnostic: it never blocks
        registration or task flow, but it turns "agent looks fine yet nothing
        ever reaches Ollama" from a mystery into two obvious log lines —
        unreachable endpoint, or a configured model that is no longer
        installed.
        """
        caps = settings.capabilities_dict()
        configured = caps.get("models") or []
        default_model = (caps.get("default_model") or "").strip() or (
            configured[0] if configured else None
        )
        try:
            installed = await self._ollama.list_models()
        except Exception as exc:
            logger.error(
                "Ollama preflight FAILED: %s is unreachable (%s) — every task will fail "
                "until Ollama is running there",
                settings.ollama_url,
                exc,
            )
            return
        logger.info(
            "Ollama preflight OK: %d model(s) installed at %s",
            len(installed),
            settings.ollama_url,
        )
        if default_model and default_model not in installed:
            logger.error(
                'Ollama preflight: this agent\'s model "%s" is NOT installed '
                '(installed: %s) — tasks will fail until you run "ollama pull %s" '
                "or change the agent's model",
                default_model,
                ", ".join(installed) or "none",
                default_model,
            )

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
            runner = asyncio.create_task(self._run_task(task_id, task))
            self._in_flight[task_id] = runner
            runner.add_done_callback(lambda _: self._in_flight.pop(task_id, None))
        elif msg_type == "revoke":
            # {"type":"revoke", ..., "payload":{"task_id":...,"reason":...}} —
            # abort the in-flight task; per the contract, NO result frame may
            # follow for a revoked task (the orchestrator already settled it).
            payload = msg.get("payload") or {}
            task_id = payload.get("task_id") or msg.get("task_id") or ""
            runner = self._in_flight.get(task_id)
            if runner:
                self._revoked.add(task_id)
                runner.cancel()
                logger.info("Task %s revoked by orchestrator — aborting Ollama call", task_id)
            else:
                logger.info("Revoke for unknown/finished task %s — nothing to abort", task_id)
        elif msg_type in ("registered", "heartbeat_ack"):
            pass  # 'registered' is consumed in _register; heartbeat_ack needs no action
        elif msg_type == "error":
            logger.warning("Orchestrator error: %s", msg.get("detail"))
        else:
            logger.debug("Ignored orchestrator frame type=%r", msg_type)

    # ── Task execution ────────────────────────────────────────────────────────

    async def _run_task(self, task_id: str, task: dict) -> None:
        """Execute one task: ack → stream from Ollama → report result.

        `task` is the full Task record from the orchestrator's task_push
        (task["input"] is a TaskInputPlaintext: prompt/system_prompt/
        role_template/model_preferences).
        """
        # Acknowledge receipt FIRST: the orchestrator only transitions the task
        # dispatched → running on task_ack, and rejects results for tasks that
        # are not 'running'. Skipping this silently drops the result — and it
        # must precede the circuit check so a fast failure below is accepted.
        await self._send({"type": "task_ack", "task_id": task_id})

        # Circuit open (and not yet due for a half-open trial): fail FAST with
        # a specific reason. A previous version silently queued the task here,
        # which left the user staring at "thinking…" while nothing would ever
        # reach Ollama.
        if not self._cb.should_attempt():
            logger.warning("Circuit open — failing task %s fast", task_id)
            await self._send({
                "type": "result",
                "task_id": task_id,
                "status": "failed",
                "error": {
                    "code": "ollama_unreachable",
                    "message": (
                        f"Ollama has been failing repeatedly — check that it is running "
                        f"at {settings.ollama_url}. This agent retries automatically."
                    ),
                },
            })
            return

        task_input = task.get("input") or {}
        model, options = self._model_and_options(task_input)
        messages = self._build_messages(task_input)
        started = time.monotonic()

        async def _step(text: str) -> None:
            """Progress frame with a step note (no output text) — turns the
            silent pre-first-token window into visible, honest status."""
            await self._send({
                "type": "progress",
                "task_id": task_id,
                "step": text,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            })

        try:
            parts: list[str] = []
            stats: dict = {}
            if self._ollama_sem.locked():
                await _step("waiting for another answer to finish…")
            async with self._ollama_sem:
                await _step("contacting Ollama…")
                # Until the first token arrives, prove liveness periodically —
                # a cold model can take a minute or more to load, and this
                # window used to render as an information-free "thinking…".
                first_token = asyncio.Event()

                async def _keepalive() -> None:
                    waited = 0
                    while not first_token.is_set():
                        await asyncio.sleep(20)
                        if first_token.is_set():
                            return
                        waited += 20
                        await _step(
                            f"still waiting for {model} to start answering ({waited}s) — "
                            "loading a model for the first time can take a while"
                        )

                keepalive = asyncio.create_task(_keepalive())
                try:
                    async for chunk in self._ollama.chat(messages, model=model, options=options, stats=stats):
                        first_token.set()
                        parts.append(chunk)
                        await self._send({
                            "type": "progress",
                            "task_id": task_id,
                            "partial_output": chunk,
                            "elapsed_ms": int((time.monotonic() - started) * 1000),
                            "tokens_so_far": len(parts),
                        })
                finally:
                    first_token.set()
                    keepalive.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await keepalive

            duration_ms = int((time.monotonic() - started) * 1000)
            # Prefer Ollama's real counts (eval_count = generated tokens) over the
            # streamed-chunk count; compute tokens/sec from generation time only
            # (eval_duration, nanoseconds) so it reflects decode speed, not queue
            # or prompt-eval time. Fall back gracefully when the stats are absent.
            eval_count = stats.get("eval_count")
            eval_duration_ns = stats.get("eval_duration")
            result: dict = {
                "output": "".join(parts),
                "model_used": model,
                "duration_ms": duration_ms,
                "tokens_used": eval_count if eval_count is not None else len(parts),
            }
            if eval_count and eval_duration_ns:
                result["tokens_per_sec"] = round(eval_count / (eval_duration_ns / 1e9), 1)
            if stats.get("prompt_eval_count") is not None:
                result["prompt_tokens"] = stats["prompt_eval_count"]

            await self._send({
                "type": "result",
                "task_id": task_id,
                "status": "complete",
                "result": result,
            })
            await self._cb.record_success()

        except asyncio.CancelledError:
            # Two cancel paths, neither sends a result: an orchestrator revoke
            # (the contract forbids a result frame), or runtime shutdown (the
            # orchestrator requeues the task itself on our disconnect).
            was_revoked = task_id in self._revoked
            self._revoked.discard(task_id)
            logger.info(
                "Task %s cancelled (%s) — no result sent",
                task_id,
                "revoked" if was_revoked else "shutdown",
            )
            raise

        except OllamaError as exc:
            logger.error("Task %s failed: [%s] %s", task_id, exc.code, exc)
            # A missing model is a configuration problem, not Ollama being
            # down — it must not trip the breaker and block other models.
            if exc.code != "model_not_found":
                await self._cb.record_failure()
            await self._send({
                "type": "result",
                "task_id": task_id,
                "status": "failed",
                "error": {"code": exc.code, "message": str(exc)},
            })

        except Exception as exc:
            logger.exception("Task %s failed unexpectedly", task_id)
            await self._cb.record_failure()
            await self._send({
                "type": "result",
                "task_id": task_id,
                "status": "failed",
                "error": {"code": "agent_error", "message": str(exc)},
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
        # Resolve the model in priority order:
        #   1. the task's explicit model_preferences.name (per-task override),
        #   2. the agent's chosen capabilities.default_model (picked in "Add
        #      Local Agent" — no longer a silent models[0] accident),
        #   3. the first advertised model, then a hardcoded last resort.
        # An empty/whitespace default_model is treated as "unset" so a blank
        # picker never sends an empty model name (which Ollama rejects with a
        # confusing error). Capabilities come from the CAPABILITIES env var —
        # see config.py and spawn_local_agent in console/src-tauri/src/lib.rs.
        caps = settings.capabilities_dict()
        configured_models = caps.get("models") or []
        default_model = (
            (caps.get("default_model") or "").strip()
            or (configured_models[0] if configured_models else None)
            or "llama3.1:8b"
        )
        model = prefs.get("name") or default_model
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

    async def _cancel_in_flight(self) -> None:
        """Shutdown: cancel in-flight work and let the orchestrator requeue it
        (it does so on our disconnect — see dispatcher.requeue_or_deadletter)."""
        if not self._in_flight:
            return
        logger.info("Cancelling %d in-flight task(s) for shutdown", len(self._in_flight))
        for task in list(self._in_flight.values()):
            task.cancel()
        await asyncio.gather(*self._in_flight.values(), return_exceptions=True)
