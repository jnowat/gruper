# WP-06 — End-to-End Relay Validation Report

**Milestone:** `gd-0.2` Walking Skeleton — exit gate
**Date:** 2026-06-30
**Status:** ✅ Automated end-to-end relay **validated and green**; 🔲 real two-machine
public-internet/NAT field run pending (runbook in §7).

> **TL;DR** — The full relay (console → orchestrator → agent → Ollama → back to
> console) was driven end to end with real processes and real WebSockets. Doing
> so surfaced **five contract bugs that meant the happy path had never actually
> worked**; all five are fixed. After the fixes the harness is **17/17 green,
> reproduced across four runs** (including a fresh-container rebuild), with
> dispatch overhead of **~10–13 ms (p50)** — roughly **800–1000× under** the
> SC-2 target of < 5–10 s.

---

## 1. Test environment

| Component | What ran | Notes |
|-----------|----------|-------|
| Orchestrator | the real FastAPI app (`orchestrator.main:app`) under **uvicorn** | real ASGI server on a real TCP port — not `TestClient` |
| Database | **PostgreSQL 16** (`gruper_e2e`) | exercises the real `SKIP LOCKED` / CTE dispatch + requeue SQL |
| Agent runtime | the real **`agent-runtime`** process (`main.py` → `ws_client.py`) | makes an **outbound** WS connection; real circuit breaker + offline queue |
| Inference | **mock Ollama** (`tests/e2e/mock_ollama.py`) | deterministic streaming `/api/chat`; no GPU / model download in CI |
| Console | the harness, using `httpx` (REST) + `websockets` (console WS) | speaks the exact console contract from `console/src/lib/types.ts` |
| Host | single Linux box (Ubuntu 24.04, Python 3.11), all on loopback | see §6 for why loopback is sufficient for the *protocol*, and §7 for the field run |

The harness is committed at **`tests/e2e/wp06_relay_validation.py`** (+ `mock_ollama.py`)
and is re-runnable:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r orchestrator/requirements.txt -r agent-runtime/requirements.txt websockets
# PostgreSQL reachable as gruper/gruper on localhost:5432 with CREATEDB
python tests/e2e/wp06_relay_validation.py        # exit 0 ⇒ all checks passed
```

### Why loopback is a faithful test of the relay model

The "no port forwarding / works behind consumer NAT" property is a **topology**
property, not a separate code path. The agent's *only* socket is an **outbound**
WebSocket it dials to the orchestrator (`ws_client.py` → `websockets.connect`);
it never opens a listening port. Dispatch, progress, and results all travel back
down that one agent-initiated connection. NAT and home routers permit outbound
connections by default, so a relay that is correct on loopback is correct across
NAT — the bytes and the connection direction are identical. What loopback does
**not** exercise is real-world latency/jitter/TLS and a real Ollama model; those
are covered by the field runbook in §7.

---

## 2. Steps performed

The harness runs setup, then four scenarios mapped to the WP-06 requirements:

1. **Console connects; agent registers and appears in the fleet.**
   Console opens its WS (receives `fleet_snapshot`) *before* the agent process
   starts, then the agent connects — verifying the fleet updates **live**.
2. **Happy path.** Submit a task via `POST /v1/tasks`; assert it is dispatched,
   acknowledged (→ `running`), streamed back as `task_progress`, completed, the
   result stored (`GET /v1/tasks/{id}`), and a `task_complete` pushed to the
   console.
3. **Resilience.** Submit a long task; once it is `running`, **SIGKILL the agent**
   mid-stream (simulating a network drop / crash); assert the orchestrator
   **requeues** it (`pending`, `retry_count=1`); restart the agent and assert the
   task **drains on reconnect and completes**.
4. **Dispatch latency.** Submit 10 tasks back-to-back and measure dispatch
   overhead (submit → `running`, i.e. **excluding** model execution) per SC-2.

---

## 3. Issues found and fixed

Running the relay end to end for the first time exposed that the **agent runtime
and the orchestrator had been built against incompatible WebSocket contracts** —
the agent was never integration-tested against the orchestrator, so dispatch had
**never worked**. Five bugs, all now fixed:

| # | Symptom (observed) | Root cause | Fix |
|---|--------------------|-----------|-----|
| 1 | Agent logs `task_push received with no task_id — ignored`; task stuck `dispatched` forever | Orchestrator sends `{"type":"task_push","task":{"id":…}}` but the agent read a top-level `msg["task_id"]` | `ws_client._dispatch` now reads `msg["task"]["id"]` |
| 2 | Even with a task run, the result was rejected; task never reached `complete` | Orchestrator only accepts a `result` for a task in `running` state, reached via `task_ack` — but the agent never sent `task_ack` | `ws_client._run_task` sends `task_ack` before executing |
| 3 | Console `task_progress` frames carried no text | Agent sent `{"progress","chunk":…}`; orchestrator/console expect `partial_output` + `elapsed_ms` | Agent now emits `partial_output`, `elapsed_ms`, `tokens_so_far` |
| 4 | Stored result unusable / `GET /tasks/{id}` could 500 | Agent sent `result` as a **string**; orchestrator/console expect an object `{output, model_used, duration_ms}` (and `dict(jsonb_string)` raises) | Agent sends a result **object**; errors as `{code,message}` |
| 5 | Console fleet view never updated after connect (agent stayed shown as it was in the snapshot) | Orchestrator only sent `fleet_snapshot` on console connect; it never broadcast `fleet_event` on status change | Orchestrator broadcasts `fleet_event` on register / status-change / disconnect |

Bug #4 also meant the agent never built an Ollama `messages` array from the task
input (it read non-existent `payload["messages"]`). The agent now constructs
messages from `TaskInputPlaintext` (`system_prompt`/`role_template` → system
message, `prompt` → user message) and maps `model_preferences` → Ollama options
per `core-mapping.md`.

**Files changed:** `agent-runtime/ws_client.py` (contract alignment, dispatch +
execution), `orchestrator/ws/agent_ws.py` (live `fleet_event` broadcasts).

> **Known divergence (tracked, non-blocking):** the frozen spec
> (`spec/contracts/wss-messages.schema.json`) defines a richer
> `{type,id,ts,payload}` envelope than either the orchestrator or the agent
> currently uses. WP-06 aligned the agent to the orchestrator's de-facto
> contract (the orchestrator + console already agree and have smoke tests),
> which is the minimal change to make the skeleton work. Migrating all three
> components to the full spec envelope is recommended hardening for a later WP.

---

## 4. Observed behavior

**Before the fixes** (`tests/e2e` against the original code) — dispatch silently
dropped:

```
[PASS] agent comes online (status=idle via REST)
[FAIL] console receives live fleet_event for the agent — no fleet_event arrived within 10s
[PASS] POST /v1/tasks dispatched immediately — status=dispatched
[FAIL] task acknowledged by agent (status=running) — status=dispatched
[FAIL] console receives streamed task_progress — none
[FAIL] task reaches status=complete — status=dispatched
[FAIL] stored result has non-empty output — output=None
[FAIL] console receives task_complete — none
```

**After the fixes** — 17/17 green:

```
== Step 1: agent registers and appears in the fleet ==
  [PASS] agent comes online (status=idle via REST)
  [PASS] console receives live fleet_event for the agent — event=agent_registered status=idle
== Step 2: happy path ==
  [PASS] POST /v1/tasks dispatched immediately — status=dispatched
  [PASS] task acknowledged by agent (status=running)
  [PASS] console receives streamed task_progress — partial='Gruper '
  [PASS] task reaches status=complete
  [PASS] stored result has non-empty output — output='Gruper relay validated end to end.'
  [PASS] console receives task_complete — final_status=complete
== Step 3: resilience (kill mid-task → requeue → reconnect → complete) ==
  [PASS] slow task running before kill
  [PASS] orchestrator requeues task after agent disconnect — status=pending retry_count=1
  [PASS] agent reconnects after restart
  [PASS] requeued task drains on reconnect and completes — status=complete retry_count=1
== Step 4: dispatch latency batch ==
  [PASS] SC-2: dispatch overhead < 10s for all 10 tasks — max=13.9ms p50=10.3ms

RESULT: 17/17 checks passed — ALL GREEN
```

The result was reproduced across repeated runs (identical 17/17; latency within
noise).

---

## 5. Latency observations

Dispatch overhead = wall-clock from `POST /v1/tasks` to the task reaching
`running` (agent received the push and acked) — i.e. **excluding** model
execution, which is the SC-2 definition.

| Metric | Value |
|--------|-------|
Numbers below are the range observed across **four green runs** (including one in
a freshly rebuilt container), each a 10-task batch:

| Metric | Observed |
|--------|----------|
| Dispatch overhead — p50 | **~10–13 ms** |
| Dispatch overhead — mean | ~10–19 ms |
| Dispatch overhead — worst single task | **64 ms** (occasional cold outlier) |
| First `task_progress` to console | ~180–250 ms |
| Full task round-trip (submit → `complete`, mean) | ~570–615 ms |

**SC-2 target: < 5–10 s dispatch overhead. Observed p50 ~10–13 ms — roughly
800–1000× under the 10 s ceiling**, with even the worst single task (64 ms)
~150× under it (loopback; a real WAN adds one network RTT, typically tens of ms,
which keeps it comfortably within target). The ~0.6 s round-trip is dominated by
the mock model's deliberate streaming delay (6 chunks × ~80 ms), not orchestration.

Raw numbers: `tests/e2e` writes a JSON summary (`--json`) with the full check
list and metrics for each run; the result was reproduced 4/4 (all 17/17 green).

---

## 6. What this validates — and what it does not

**Validated (automated, reproducible):**
- The complete happy-path relay across real processes and real WebSockets.
- The **outbound-only** agent connection model (no inbound port; the core of the
  no-port-forwarding claim).
- Orchestrator-side resilience: dispatch claim/CAS, agent-disconnect requeue with
  `retry_count`, and drain-on-reconnect (`dispatch_pending_for_agent`).
- Live console fleet + task event stream (`fleet_event`, `task_progress`,
  `task_complete`) against the real console contract.
- SC-2 dispatch-overhead budget.

**Not yet validated (needs real hardware — §7):**
- Real public-internet transport with TLS (`wss://`), real latency/jitter.
- A genuine consumer-NAT topology (agent on a home connection, orchestrator on a
  VPS) — architecturally equivalent here, but not yet run on two machines.
- A real Ollama model (correctness/perf of actual inference, not a mock).
- Orchestrator-restart recovery (agent backoff-reconnect across an orchestrator
  bounce) — partially exercised by the agent's reconnect loop but not as a
  dedicated two-machine scenario.

---

## 7. Field runbook — real two-machine NAT validation

To close the remaining field leg (the only part not reproducible in CI):

1. **Orchestrator** on a VPS with a public DNS name + TLS:
   `docker compose -f orchestrator/docker-compose.yml up` behind a reverse proxy
   terminating `wss://`. Set `DATABASE_URL`, a strong `JWT_SECRET`.
2. **Agent** on a workstation behind a consumer router (no port-forwarding rule):
   real Ollama running (`ollama pull llama3.1:8b`); set `ORCHESTRATOR_URL=wss://<host>/v1/agents/ws`,
   `AGENT_ID`, `JWT_TOKEN`, `OLLAMA_URL=http://localhost:11434`; `python main.py`.
3. **Console** on a third network: connect, confirm the agent appears, submit
   ~20 tasks; confirm streamed progress + results.
4. **Resilience:** pull the agent's network mid-task → confirm requeue; restore →
   confirm completion. Bounce the orchestrator → confirm agent backoff-reconnect
   and queue drain.
5. **Record** dispatch overhead (target SC-2 < 10 s) and note any TLS/keepalive
   tuning. Append results to this report.

Because the relay is outbound-only, step 2 requires **no router configuration** —
that is the property this milestone exists to prove, and the runbook is the final
confirmation on real hardware.

---

## 8. Conclusion

The `gd-0.2` Walking Skeleton **works end to end**: a task submitted from the
console is dispatched over the agent's outbound WebSocket, executed against
(mock) Ollama, streamed back live, and delivered as a stored result — and it
recovers correctly when the agent drops mid-task. The five contract bugs that
previously made this impossible are fixed and guarded by a committed, repeatable
end-to-end harness. The automated exit-gate criteria are met; the real
two-machine NAT run (§7) is the remaining field confirmation.
