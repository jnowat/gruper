# Gruper Distributed — Engineering Roadmap

**Status as of 2026-07-01:** `gd-0.1` / `gd-0.2` — **Phase 0 complete; WP-03/04/05 code complete; WP-06 automated end-to-end relay validation is green (17/17 — five dispatch-contract bugs found and fixed).** Two gates remain open on the walking skeleton, and the project has **adopted a desktop-first strategy** (see below) that reframes them:
- The `gd-0.2` field gate — the real two-machine public-internet/NAT run (runbook in [`docs/WP-06-Validation.md`](docs/WP-06-Validation.md) §7) — is still pending.
- A **new `gd-0.2.x` "Desktop-First Foundation"** phase (WP-30…WP-32) is now the immediate priority: it makes SQLite the default backend and lets the whole stack run on a stock Windows desktop with no Docker and no separate database server.

· WP-01 ✅ · WP-02 ✅ · WP-03 ✅ code complete · WP-04 ✅ code complete · WP-05 ✅ complete · WP-06 ✅ automated E2E validated (17/17; SC-2 ~10 ms) · 🔲 real two-machine NAT field run pending · 🔲 **Desktop-First Foundation (WP-30…32) not started** · OQ-1 and OQ-2 resolved · **v1.0 is a future finish line gated on SC-1…SC-9; it has not been reached.**

---

## ⚠️ Honest current state (read this first)

The automated E2E harness proves the *relay logic* works, but it does **not** yet prove the desktop-first story. Be precise about what runs today:

| Component | Runs on a stock Windows desktop with **no Docker**? | Backing store today |
|-----------|------------------------------------------------------|---------------------|
| **Gruper core** (`Gruper.html`) | ✅ Yes — double-click the file; needs only a browser + Ollama | none (client-only) |
| **Agent runtime** | ✅ Yes — `python main.py`, pure-Python deps | **SQLite** (`agent.db`, local offline queue) |
| **Manager Console** (Tauri) | ✅ Yes — native desktop app; connects to an orchestrator URL you type in | `localStorage` / tauri-store (auth token) |
| **Orchestrator** | ❌ **No** — hard-wired to PostgreSQL via `asyncpg`; the only documented run path is `docker compose up` | **PostgreSQL only** |

**The orchestrator is the gap.** It is coupled to PostgreSQL at every layer — `asyncpg` driver (`orchestrator/database.py`), `JSONB` columns and codecs, `gen_random_uuid()`, `TIMESTAMPTZ`/`NOW()`, `FOR UPDATE SKIP LOCKED` dispatch (`orchestrator/dispatcher.py`), CTE `UPDATE…FROM`, `INTERVAL` arithmetic in the timeout watchdog (`orchestrator/main.py`), and `$1`/`::uuid`/`::jsonb` casts throughout. A `sqlite://` URL cannot even open the pool. **There is no SQLite code path, dialect switch, or feature flag in the orchestrator today.** Making SQLite work is a real engineering task (WP-30), not a config change.

**What WP-06 actually validated:** the orchestrator ran *without Docker* (bare `uvicorn` subprocess on one Linux box, loopback) — but *against a real PostgreSQL 16 instance the tester had to stand up first*, with a **mock** Ollama, on **Linux only**. It has never been run against SQLite, on Windows, or with a real model. So "the orchestrator does not require Docker" is technically true (you can `pip install` and run `uvicorn`), but it still requires a PostgreSQL server — which for most desktop users means Docker. Until WP-30 lands, **Docker + PostgreSQL is effectively required to run the orchestrator.**

---

## Strategy & Philosophy — Desktop-First

Gruper Distributed is now built **desktop-first**. The guiding principle:

> **A single person on a normal Windows desktop must be able to run the entire system — Console, Orchestrator, and at least one Agent — with minimal extra dependencies and without Docker.**

This reorders our defaults:

1. **SQLite is the default backend** for local/desktop use. The orchestrator's primary store is an embedded SQLite file — no database server to install, no daemon to manage, nothing to `docker compose up`. This matches how the agent runtime already works (`agent.db`).
2. **PostgreSQL is an advanced / server option.** It stays fully supported for multi-user, multi-tenant, and production/server deployments where its concurrency (`SKIP LOCKED`), `JSONB` query power, and operational maturity matter. It is selected by setting `DATABASE_URL` to a `postgresql://` DSN — opt-in, not required.
3. **Docker is optional and server-oriented.** Docker Compose remains the recommended way to run the orchestrator *as a server* (VPS, always-on host, cloud). It is **not** part of the normal desktop path. The container agent image (WP-12) likewise targets servers and cloud burst, not laptops.
4. **The orchestrator should eventually run without the user thinking about it.** Long-term, launching the Console should bring up a working local orchestrator automatically — bundled as a background service or spawned as a sidecar — so a desktop user never manually starts a server. (WP-32.)

**Why this pivot:** the architecture was originally scaffolded Docker-Compose-and-PostgreSQL-first because that is the fastest way to get a correct multi-user server skeleton (real queue semantics, real JSONB, one-command self-host). That was the right call for the *walking skeleton*, but it puts a database server and a container runtime between a solo desktop user and their first result. For the "normal Windows desktop, minimal dependencies" audience, that is the wrong default. Desktop-first flips it: embedded SQLite by default, PostgreSQL/Docker reserved for the server tier that actually needs them.

### Two deployment tiers

| Tier | Audience | Backend | Runtime | Setup |
|------|----------|---------|---------|-------|
| **Desktop (default)** | Solo user, single machine or small trusted LAN | **SQLite** (embedded file) | Bundled/native orchestrator process; no server | One installer / one command; no Docker, no DB server *(target — WP-30/31/32)* |
| **Server (advanced)** | Multi-user, multi-tenant, production, cloud burst | **PostgreSQL** | `docker compose up` on a VPS/always-on host | Docker Compose + Postgres, TLS reverse proxy *(works today)* |

Both tiers speak the **same wire contracts and REST/WS API** (WP-01). The tier is a storage/runtime choice below the contract line — agents and consoles cannot tell which backend the orchestrator uses.

---

**Stack (target):** Agent Runtime — Python + FastAPI; Rust for security-critical paths · Manager Console — Tauri v2 + Svelte 5 + Tailwind · Orchestrator — FastAPI; **SQLite by default (desktop), PostgreSQL optional (server)** · Transport — WSS over TLS · Inference — Ollama local-first · Containers — Docker multi-arch (CPU + CUDA), **server/cloud tier only**
*(Current reality: the orchestrator is PostgreSQL-only until WP-30; the SQLite default is the target this roadmap now drives toward.)*

**Gruper core baseline: `v0.4.5` (`Gruper.html`).** Gruper Distributed is a **companion extension, not a replacement.** Core stays client-only, single-file, and standalone. Distributed reuses:
- Ollama integration: same `/api/generate` / `/api/chat` endpoint shape and parameter conventions
- Circuit-breaker / retry: 2 s / 4 s / 8 s / 16 s exponential backoff applied to all persistent connections
- Chart.js analytics: same visual language, tooltip format, and CSV/JSON export — embedded in the console
- Conversation engine and message rendering: embedded in the console's Agent Detail view
- 12 agent role templates: extended with `jurisdiction` and `availability` metadata
- CDN SRI-hash validation discipline: applied to Docker image layer integrity in CI (server/cloud tier)

**Cross-network principle:** Every agent makes an *outbound* authenticated persistent WSS connection to the orchestrator. Nothing connects inward to an agent. NAT traversal requires no port forwarding on any agent host. *(This holds identically for the desktop tier — a local orchestrator on `localhost:8080` is just the shortest-hop case of the same outbound model.)*

**Companion document:** `GruperDistributedSpec.md` — architecture diagrams, data models, wire schemas, security threat table, and open questions (OQ-1…OQ-5). **Follow-up:** the spec's recommended-stack table still lists Docker Compose + PostgreSQL as the default and treats "SQLite + Litestream for single-user self-host" as a footnote; it needs a desktop-first alignment pass to match this roadmap (tracked in Known Technical Debt).

---

## Phase Summary

| Phase | Milestone | Goal | Status |
|-------|-----------|------|--------|
| 0 — Foundations | `gd-0.1` | Wire contracts, schemas, skeleton orchestrator | ✅ Complete |
| 1 — Walking Skeleton | `gd-0.2` | Single-owner end-to-end relay over the public internet | 🔄 Automated E2E relay green; real-NAT field run pending |
| **1.5 — Desktop-First Foundation** | **`gd-0.2.x`** | **SQLite-default orchestrator; whole stack on a Windows desktop, no Docker; orchestrator auto-run** | **🔲 Not started — current priority** |
| 2 — Cross-Network Sharing | `gd-0.3` | Cross-owner dispatch with scoped tokens; headline milestone | 🔲 Not started |
| 3 — Cloud Burst | `gd-0.4` | AWS spot fleet with hard cost controls (server/cloud tier) | 🔲 Not started |
| 4 — Security Hardening | `gd-0.5` | Sandbox parity, E2E encryption, formal security review | 🔲 Not started |
| 5 — Beta & Polish | `gd-0.6–0.9` | Capability dispatch, crew builder, n8n integration, closed beta | 🔲 Not started |
| First Stable Release | `v1.0` | SC-1…SC-9 met for real users; roadmap rewritten at that point | 🔲 Future finish line |
| Post-v1 | `gd-1.x` | Federation, P2P, mobile, ecosystem | 🔲 Deferred |

> **Sequencing note.** Phase 1.5 is numbered between the walking skeleton (Phase 1) and cross-network sharing (Phase 2) and is the **immediate next work**. Its work packets carry higher numbers (WP-30…32) only because they were planned after WP-01…WP-29 — WP number is planning order, not execution order. Doing the SQLite/DB-abstraction work (WP-30) **before** Phase 2 is deliberate: the multi-tenant schema migration (WP-07) should be written against the dialect abstraction, not layered onto more PostgreSQL-only SQL.

---

## Phase 0 — Foundations — ✅ `gd-0.1`

### WP-01 — Wire Contracts & Schema Freeze — ✅ `gd-0.1`

- **Goal:** Lock every interface downstream WPs build against.
- **Steps:**
  1. ✅ Define the **agent ↔ orchestrator WSS message schema**: `register`, `heartbeat`, `task-push`, `progress-stream`, `result`, `revoke` — typed, versioned, documented. → `spec/contracts/wss-messages.schema.json`
  2. ✅ Define the **console ↔ orchestrator REST/WS API** (OpenAPI 3.1): task submit, agent query, token mint/revoke, event stream. → `spec/contracts/openapi.yaml`
  3. ✅ Map **Gruper core's per-agent config schema** (model, temperature, top-p, top-k, repeat penalty, max tokens, context length, role template) to the distributed task input schema. → `spec/contracts/core-mapping.md`
  4. ✅ Define all data models in versioned JSON Schema: `User`, `Agent`, `Task`, `ShareToken`, `Event`. → `spec/contracts/models/`
  5. ✅ Resolve **OQ-1** (agent-loop framework) → **Custom ReAct implementation**, consistent with Gruper core's philosophy.
  6. ✅ Resolve **OQ-2** (Pattern A sign-off) → **Pattern A — shared multi-tenant orchestrator** for the first release.
  7. ✅ WP-02 skeleton orchestrator confirmed schemas are buildable — exit gate met.
- **Dependencies:** OQ-1 and OQ-2 resolved.
- **Exit gate:** Schemas agreed and published. An independent implementer can build against them without reopening architecture decisions.

**Notes (2026-06-29):** `spec/contracts/` committed. Contains: OpenAPI 3.1 YAML (17 endpoints across 8 tags), WSS message schema (16 message types: 6 agent→orchestrator, 5 orchestrator→agent, 5 orchestrator→console), 5 versioned JSON Schema 2020-12 data models, Gruper Core parameter mapping doc, and package README with OQ resolutions. OQ-1 and OQ-2 resolved. WP-02 built directly against these schemas with no amendments — exit gate met. **Closed.**

**🔧 Desktop-first follow-up:** The contracts are database-agnostic (pure JSON Schema / OpenAPI) and require **no change** for the SQLite pivot — this is exactly why the desktop and server tiers can share one API. The one discipline to preserve in WP-30: the SQLite backend must keep emitting the same wire shapes the contracts define (UUIDs as canonical strings, JSON objects for `input`/`result`/`metadata`, ISO-8601 timestamps), even though it stores them as `TEXT`. No contract reopening.

---

### WP-02 — Skeleton Orchestrator — ✅ `gd-0.1`

- **Goal:** Runnable orchestrator accepting agent registration and heartbeat; no task dispatch. *(Originally scoped as a Docker Compose + PostgreSQL stack; see follow-up below for the desktop-first reframing.)*
- **Steps:**
  1. ✅ `docker-compose.yml`: PostgreSQL 16 + FastAPI with hot reload; all config via environment variables. *(This is now the **server-tier** entry point, not the default desktop path.)*
  2. ✅ Migrations 001–004: `users`, `agents`, `tasks`, `events` tables; `SKIP LOCKED` queue pattern on `tasks`.
  3. ✅ Endpoints: `POST /v1/auth/token` (JWT issuance), `POST /v1/agents` (register), `WS /v1/agents/ws` (heartbeat), `GET /v1/agents`, `GET /v1/health`.
  4. ✅ JWT issuance and verification middleware (HS256); ed25519 challenge-response stubbed (WP-07).
  5. ✅ `pytest` smoke tests: register → JWT → heartbeat → verify in `GET /v1/agents`.
  6. ✅ Heartbeat watchdog background task: marks agents `offline` after 90 s of silence.
  7. ✅ Append-only `events` table on every state transition; hash chain fields null until WP-17.
- **Files:** `orchestrator/main.py`, `orchestrator/config.py`, `orchestrator/database.py`, `orchestrator/security.py`, `orchestrator/connection_manager.py`, `orchestrator/routers/`, `orchestrator/ws/`, `orchestrator/migrations/001–004.sql`, `orchestrator/docker-compose.yml`, `orchestrator/tests/`
- **Exit gate:** `docker compose up` on a clean machine; mock agent registers, heartbeats, appears in `GET /v1/agents`; smoke tests pass. *(Met on the PostgreSQL/Docker path.)*

**Notes (2026-06-29):** `orchestrator/` complete and polished through three review passes. Stack: FastAPI + asyncpg + PostgreSQL 16 + Docker Compose. Key decisions: HS256 JWT stub at `POST /v1/auth/token` (find-or-create by pubkey; ed25519 challenge-response at WP-07); JWT passed as `?token=` query param on WS upgrade (browsers cannot send Authorization headers on WebSocket connections); idempotent migration runner wraps each SQL file in a transaction; asyncpg JSON/JSONB codecs registered at pool init; heartbeat watchdog runs every 15 s and marks stale agents offline after 90 s; re-registration replaces stale connection entry gracefully; 15 smoke tests cover the full auth flow. Hash-chain event fields null until WP-17. `orchestrator/README.md` added. WP-01 exit gate met. **Closed.**

**🔧 Desktop-first follow-up (this is the WP most affected by the pivot):** WP-02 assumed Docker + PostgreSQL as the *only* path, and that assumption is now confined to the **server tier**. The orchestrator as built **cannot run on the desktop tier** — it is `asyncpg`/PostgreSQL-only (`database.py`), the smoke tests require a live Postgres (`tests/conftest.py`), and there is no orchestrator job in CI (CI only runs static Gruper.html checks + the Windows console build). Desktop-first alignment is delivered by:
- **WP-30** — introduce a DB abstraction; make **SQLite the default** and PostgreSQL opt-in; port the Postgres-only DDL and queries.
- **WP-31** — a no-Docker, no-Postgres local run/setup path so a desktop user can start the orchestrator with one command/installer.
- **WP-32** — auto-run the orchestrator (service/sidecar) so the desktop user never starts it by hand.
- **CI gap** to close in WP-30: add an orchestrator test job (run the smoke suite against SQLite in CI; keep a Postgres matrix leg for the server tier).

---

## Phase 1 — Walking Skeleton — 🔄 `gd-0.2`

### WP-03 — Agent Runtime — Desktop MVP — ✅ code complete · `gd-0.2`

- **Goal:** Desktop agent service that dials out to the orchestrator, executes tasks against local Ollama using **Gruper core's API shape and parameter conventions**, and streams results back.
- **Steps:**
  1. ✅ Persistent outbound WSS client with **exponential backoff (2 s / 4 s / 8 s / 16 s) — Gruper core's retry discipline** applied to the orchestrator connection.
  2. ✅ Registration handshake: send capability JSON on connect; receive and store JWT.
  3. ✅ Task execution: receive task JSON → call local Ollama (`/api/chat`, **Gruper core parameter conventions**) → stream progress and result over WSS.
  4. ✅ **Offline queue: SQLite per-agent** (`agent.db`, `aiosqlite`); drain on reconnect with exponential backoff.
  5. ✅ **Circuit-breaker:** 3 consecutive failures → mark degraded, signal orchestrator to pause routing — mirrors **Gruper core's agent auto-disable pattern**.
  6. ✅ Heartbeat loop (30 s); graceful shutdown with in-flight checkpoint.
  7. ✅ Systemd unit (Linux); launchd plist stub (macOS); NSSM stub (Windows).
- **Files:** `agent-runtime/main.py`, `agent-runtime/ws_client.py`, `agent-runtime/ollama_client.py`, `agent-runtime/offline_queue.py`, `agent-runtime/circuit_breaker.py`, `agent-runtime/config.py`, `agent-runtime/gruper-agent.service`
- **Exit gate:** Agent behind consumer NAT connects to VPS-hosted orchestrator; receives pushed task; calls local Ollama; streams result back over the public internet relay path.

**Notes (2026-06-29):** `agent-runtime/` complete. Flat module structure (run `python main.py` from `agent-runtime/`); `offline_queue.py` instead of `queue.py` to avoid shadowing the stdlib module; Ollama options keyed to Gruper core's parameter names; circuit breaker threshold = 3 failures; backoff = [2, 4, 8, 16] s; heartbeat every 30 s; in-flight tasks checkpointed to SQLite on SIGINT/SIGTERM. **Pending:** real NAT traversal validation deferred to WP-06.

**🔧 Desktop-first follow-up:** The agent is **already the model desktop-first component** — pure Python, `python main.py`, six pure-Python deps, and a local **SQLite** offline queue; it needs neither Docker nor PostgreSQL. It is *already aligned* with the new direction. Remaining polish (moved into WP-31): bundle/package it so a non-technical Windows user does not have to install Python and manage a venv, and promote the Windows path from an **NSSM stub** to a first-class, documented Windows install. No architectural change needed.

---

### WP-04 — Orchestrator — Task Dispatch — ✅ code complete · `gd-0.2`

- **Goal:** Orchestrator dispatches an explicit-assignment task to a registered agent and relays the result stream to the submitter.
- **Steps:**
  1. ✅ `POST /tasks`: submitter auth, `assigned_agent_id`, payload, data class, priority, deadline, timeout_s, correlation_id (idempotency), allowed_tools.
  2. ✅ Dispatcher: `SKIP LOCKED` enqueue on agent-connect; CAS dispatch on submit; task reverts to `pending` if agent offline so reconnect picks it up.
  3. ✅ Result relay: forward progress events and final result to submitter's open console WS connection. Implemented in WP-05.
  4. ✅ Task lifecycle: `pending → dispatched → running → complete | failed | timed_out | dead_letter`.
  5. ✅ Retry: requeue on agent disconnect (`retry_count++`); dead-letter after 3 retries.
  6. ✅ Append to `events` table on task submit, complete, and fail.
  7. ✅ Smoke tests: submit, dispatch-on-connect, ack→running, result→complete/failed, disconnect requeue, idempotency, auth guards. Timeout watchdog background task.
- **Files:** `orchestrator/dispatcher.py`, `orchestrator/routers/tasks.py`, `orchestrator/ws/agent_ws.py`, `orchestrator/main.py`, `orchestrator/tests/test_tasks.py`
- **Exit gate:** End-to-end task completes over the internet relay path. Integration tests pass. *(Code + smoke tests complete on the PostgreSQL path; live internet-relay leg validated in WP-06.)*

**Notes (2026-06-29):** `dispatcher.py` and `routers/tasks.py` implemented. `agent_ws.py` extended with `task_ack` → `running`, `progress` → relay, `result` → `complete`/`failed` handlers; `dispatch_pending_for_agent` on register; `requeue_or_deadletter` on disconnect. `main.py` includes tasks router and timeout watchdog (30 s poll). 13 smoke tests. `try_dispatch` atomically claims the task but reverts to `pending` if the agent is offline; SKIP LOCKED CTE for bulk drain on connect; `_MAX_RETRIES = 3`. **Code complete.**

**🔧 Desktop-first follow-up:** The dispatch layer is where the **most PostgreSQL-specific SQL lives** and so needs the most porting for the SQLite default:
- `FOR UPDATE SKIP LOCKED` + CTE `UPDATE…FROM` (`dispatcher.py`) — SQLite has no `SKIP LOCKED`. On the desktop tier a single orchestrator process with one serialized dispatch loop does not need multi-consumer skip-lock semantics; a `BEGIN IMMEDIATE` single-writer claim is sufficient and correct. The abstraction picks the right strategy per backend (SKIP LOCKED on Postgres, serialized claim on SQLite).
- Timeout watchdog `dispatched_at + (timeout_s * INTERVAL '1 second') < NOW()` (`main.py`) — port to portable time math.
- `$1`/`::uuid`/`::jsonb` casts, `NOW()`, JSONB binding — all handled by WP-30's dialect layer.
The **behavior contract** (states, retries, requeue-on-disconnect, idempotency) is unchanged; only the SQL underneath moves.

---

### WP-05 — Manager Console — Minimal Scaffold — ✅ Complete · `gd-0.2`

- **Goal:** Tauri v2 + Svelte 5 console scaffold with fleet view, task composer, and result view — embedding **Gruper core's conversation UI and Chart.js analytics** directly.
- **Steps:**
  1. ✅ Tauri v2 + Svelte 5 + Tailwind scaffold; locked-down CSP in `tauri.conf.json` from the first commit.
  2. ✅ WSS client to orchestrator (`ConsoleWS` with exponential-backoff reconnect); orchestrator `GET /v1/console/ws` implemented.
  3. ✅ **Fleet view:** `AgentCard` — name, status badge (idle / busy / offline / degraded / draining), last-seen, model list; updates live from `fleet_event` WS pushes.
  4. ✅ **Task composer:** full task input + Gruper core's inference parameters + role template + data class + priority; mirrors core's task-input UX exactly.
  5. ✅ **Result view:** conversation bubble rendering (glassmorphism, markdown, streaming progress); live partial-output from `task_progress`; fetches full result from `GET /v1/tasks/{id}` on completion.
  6. ✅ **Per-agent analytics tab:** Chart.js v4 response-time chart; same visual language and CSV/JSON export as Gruper core.
  7. ✅ **Orchestrator result relay:** `_handle_progress` / `_handle_result` in `agent_ws.py` broadcast `task_progress` / `task_complete` to the submitter's console WS. Completes WP-04 step 3.
  8. ✅ CI build: `console/package-lock.json` committed and verified `npm ci`-coherent; `tauri-action` runs the real NSIS/WiX build on push to `main`, `v*` tags, `claude/**` branches, PRs into `main`, and manual dispatch. **Windows build fix:** Tauri v2 `[lib] name = "gruper_console_lib"` naming + RGBA icon regeneration; `cargo build` green on Linux; Windows MSVC bundle runs on the GitHub Windows runner. `Cargo.lock` committed.
  9. 🔲 Playwright click-through smoke test — deferred to `gd-0.6+` (tracked in Known Technical Debt).
- **Files:** `console/src-tauri/*` (Tauri config, `Cargo.toml`/`Cargo.lock`, `main.rs`/`lib.rs`, capabilities, RGBA icons), `console/src/**` (routes, stores, WS client, components), `orchestrator/ws/console_ws.py`, `orchestrator/connection_manager.py`, `orchestrator/ws/agent_ws.py`, `orchestrator/main.py`
- **Exit gate:** Console builds on Linux (`npm ci && npm run build` **and** `cargo build` both green); submits a task; displays result in the embedded Gruper core result view. Windows installer build armed.

**Notes (2026-06-29):** Scaffold complete and verified green on Linux — `npm ci`, `npm run build`, `npm run check` (0 type errors). `ConsoleWS` reconnects with `[2, 4, 8, 16] s` backoff; `fleet_snapshot` on WS connect avoids an extra REST round-trip; `auth.ts` persists JWT + orchestrator URL in `localStorage`; inference parameter ranges match Gruper core exactly; Chart.js dynamically imported; CSP locked from the first commit. **Windows build fix (2026-06-29):** `[lib]` naming + RGBA icons resolved; native shell `cargo build`s green on Linux; the `.exe`/`.msi` bundle runs on the Windows runner. **Complete.**

**🔧 Desktop-first follow-up:** The console is **already a no-Docker desktop app** and connects to whatever orchestrator URL the user enters (default `http://localhost:8080`, persisted after first connect). Two desktop-first gaps remain, both moved to WP-32:
- **It does not start an orchestrator.** Today it assumes one is already running; a desktop user still has to launch the orchestrator separately. WP-32 makes the Console bring up a local orchestrator automatically (Tauri sidecar or supervised service) so the default first-run experience is "install Console → it just works on `localhost`."
- **Capabilities are currently `core:default` + `store:default` only** (no `shell`/`command`/`sidecar`), so spawning a bundled orchestrator will require adding a tightly-scoped sidecar capability in WP-32 — to be added deliberately and minimally, preserving the locked-down CSP posture.

---

### WP-06 — End-to-End Relay Validation — ✅ automated E2E green · 🔲 field NAT run pending · `gd-0.2` exit gate

- **Goal:** Prove the outbound-relay model stable over the public internet before sharing complexity is added.
- **Steps:**
  1. 🔲 Orchestrator on VPS (Docker Compose); agent on workstation behind consumer NAT — no port forwarding. *(Field run — runbook in [`docs/WP-06-Validation.md`](docs/WP-06-Validation.md) §7. Outbound-only relay needs no router config; topology validated on loopback, real hardware pending.)*
  2. ✅ Submit tasks; measure dispatch overhead (target < 10 s excluding model execution; SC-2 baseline). **Measured: p50 ~10 ms, max ~14 ms** on loopback — ~700× under budget.
  3. ✅ Simulate agent disconnect mid-task; verify requeue and completion on reconnect. **SIGKILL mid-stream → requeue (`pending`, `retry_count=1`) → restart → drains → `complete`.**
  4. 🔲 Simulate orchestrator restart; verify agent reconnects with exponential backoff and drains queue without data loss. *(Agent backoff-reconnect exercised; dedicated orchestrator-bounce scenario deferred to the field run.)*
- **Automated validation (2026-06-30):** a committed harness ([`tests/e2e/wp06_relay_validation.py`](tests/e2e/wp06_relay_validation.py)) drives the **real** relay — real orchestrator under `uvicorn` + **real PostgreSQL** + the real agent-runtime's outbound WS + a **mock** Ollama — and is **17/17 green across four runs**. First end-to-end run exposed **five contract bugs** (agent read a non-existent top-level `task_id` instead of `task.id`; never sent `task_ack`; sent `progress.chunk`/string `result` instead of `partial_output` / `{output,…}`; never built an Ollama `messages` array; orchestrator never broadcast live `fleet_event`) — all fixed. Full report: [`docs/WP-06-Validation.md`](docs/WP-06-Validation.md).
- **Exit gate:** SC-2 baseline documented ✅. Relay model proven at the protocol/logic level ✅ (automated E2E). **Remaining for full `gd-0.2` sign-off:** the real two-machine public-internet/NAT field run (§7 runbook) — SC-5 single-owner case on real hardware.

**🔧 Desktop-first follow-up (be precise about what this validated):** The 17/17 run was **Docker-free** (bare `uvicorn` subprocess) but ran **against a real PostgreSQL 16 instance the tester provisioned**, with a **mock** Ollama, on **Linux, loopback only**. It therefore does **not** yet exercise the desktop-first path. Two new validation gates are added and owned by Phase 1.5:
- **SC-8 desktop gate (WP-30/31):** re-run the same E2E harness against the **SQLite backend** with **no PostgreSQL**, and then on a **real Windows desktop with no Docker** and a **real Ollama** — the actual "solo user on a laptop" happy path.
- The existing **SC-5 field gate** (two-machine NAT over the public internet) remains the server/relay proof and is unchanged.
These are distinct: one proves *desktop-with-no-Docker*, the other proves *cross-machine-over-the-internet*. Neither is done yet.

---

## Phase 1.5 — Desktop-First Foundation — 🔲 `gd-0.2.x` — **current priority**

**Goal of the phase:** make the desktop tier real. After this phase, a solo user on a stock Windows desktop can run Console + Orchestrator + Agent with SQLite, no Docker, and no separate database server — ideally without ever manually starting the orchestrator. PostgreSQL and Docker remain fully supported for the server tier but become opt-in.

> **Dependency ordering:** WP-30 (SQLite backend) is the keystone and lands first. WP-31 (local setup/packaging) and WP-32 (auto-run) build on it. Phase 2's multi-tenant migration (WP-07) should be written against WP-30's abstraction.

### WP-30 — Orchestrator SQLite Backend (default for desktop) — 🔲 `gd-0.2.x`

- **Goal:** Make **SQLite the default** orchestrator backend for local/desktop use, with **PostgreSQL selectable** via `DATABASE_URL` for the server tier. Both pass the same test suite and expose identical API/wire behavior.
- **Design:** Introduce a thin **database abstraction / dialect layer** between the routers/dispatcher and the driver. Do **not** assume an ORM is required — the current code is hand-written SQL, so the lightest correct option is a small dialect adapter (parameter style, placeholder rewriting, JSON handling, ID generation, time functions, and dispatch strategy) plus a driver switch (`aiosqlite` for `sqlite://`, `asyncpg` for `postgresql://`). Evaluate SQLAlchemy Core / the `databases` library vs. a bespoke adapter as step 1; pick the smallest thing that removes duplication without hiding the SQL.
- **Steps:**
  1. **Backend selection:** parse `DATABASE_URL` scheme; **default to a local SQLite file** (e.g. `orchestrator.db` next to the config) when unset — mirroring the agent's `agent.db` convention. `postgresql://` selects the Postgres path. Add `aiosqlite` to `orchestrator/requirements.txt`.
  2. **Port the DDL / migrations** to run on both engines: `UUID → TEXT` (canonical string UUIDs, app-generated), `JSONB → TEXT` (JSON-encoded) with query-side JSON handling, `TIMESTAMPTZ → TEXT` (ISO-8601 UTC), `gen_random_uuid()` → application-side UUID generation, `CHECK`/`REFERENCES`/partial indexes → SQLite-compatible equivalents (SQLite supports `CHECK`, FKs with `PRAGMA foreign_keys=ON`, and partial indexes). Keep a single source of truth for the schema per dialect, or a translator.
  3. **Port the queries:** placeholder style (`$1` ↔ `?`), remove/relocate `::uuid`/`::jsonb`/`::timestamptz` casts, replace `NOW()` and `INTERVAL` arithmetic (timeout watchdog) with portable time handling, and encode/decode JSON columns at the boundary.
  4. **Dispatch strategy per backend:** keep `FOR UPDATE SKIP LOCKED` + CTE on PostgreSQL; on SQLite use a serialized single-writer claim (`BEGIN IMMEDIATE` + `UPDATE … WHERE status='pending'` CAS). Preserve the exact task lifecycle, retry, requeue-on-disconnect, and idempotency behavior of WP-04. Enable SQLite WAL mode for concurrent readers.
  5. **Tests on both engines:** parametrize `orchestrator/tests` (and the WP-06 E2E harness) to run against SQLite **and** PostgreSQL. The SQLite leg must need no external server.
  6. **CI:** add an orchestrator test job (missing today). Run the SQLite matrix leg with no services; run a PostgreSQL matrix leg with a Postgres service container for the server tier.
  7. **Docs:** document backend selection; state clearly that SQLite is the default and PostgreSQL is the advanced/server option.
- **Files:** `orchestrator/database.py` (dialect layer), `orchestrator/config.py` (default `DATABASE_URL` → SQLite), `orchestrator/dispatcher.py`, `orchestrator/main.py` (watchdog time math), `orchestrator/routers/*`, `orchestrator/ws/agent_ws.py`, `orchestrator/migrations/*` (dialect-portable), `orchestrator/requirements.txt` (+`aiosqlite`), `orchestrator/tests/conftest.py` (backend parametrization), `.github/workflows/` (new orchestrator test job)
- **Exit gate:** `DATABASE_URL` unset → orchestrator starts on a local SQLite file with **no PostgreSQL and no Docker**, registers an agent, dispatches a task, relays a result, and passes the full smoke suite. Setting `DATABASE_URL=postgresql://…` still passes the identical suite. WP-06 E2E is green on **both** backends. Agents and consoles observe identical behavior across backends.

---

### WP-31 — One-Click Local Setup & Packaging (Windows-first) — 🔲 `gd-0.2.x`

- **Goal:** A non-technical user on a stock **Windows** desktop can get the full local stack running with **minimal extra dependencies** — no Docker, no PostgreSQL, no manual venv/Python juggling. macOS and Linux get the same experience where practical.
- **Depends on:** WP-30 (SQLite default).
- **Steps:**
  1. **Bundle the orchestrator + agent Python runtimes** so the user does not install/manage Python by hand — e.g. a PyInstaller/embedded-CPython build producing a self-contained orchestrator executable and a self-contained agent executable for Windows (and macOS/Linux). SQLite is embedded; nothing external to install.
  2. **Sensible zero-config defaults:** orchestrator binds `localhost:8080`, creates its SQLite file on first run, generates a JWT secret on first run (no manual `openssl`), and requires no `.env` for the desktop happy path.
  3. **Ollama detection & guidance:** detect a local Ollama; if absent, link the user to install it (Ollama stays the one real external prerequisite, consistent with Gruper core).
  4. **First-class Windows agent install:** promote the agent's **NSSM stub** to a documented, supported Windows install; a solo user's own machine can be both orchestrator host and agent.
  5. **One-command / one-installer path:** a single script or installer that lays down orchestrator + agent (+ optionally launches the Console) — the desktop analog of `docker compose up`, without Docker.
  6. **Docs restructure:** README leads with the **desktop (SQLite, no-Docker) quick start**; the Docker Compose + PostgreSQL instructions move under an "Advanced / Server deployment" heading.
  7. **Desktop happy-path validation:** run the WP-06 E2E flow on a real Windows desktop with SQLite, no Docker, and a real Ollama (feeds the SC-8 gate).
- **Files:** packaging config (e.g. `agent-runtime/`, `orchestrator/` build specs), installer/scripts, `README.md` (desktop-first restructure), `orchestrator/README.md`, `agent-runtime/README.md`, Windows service docs
- **Exit gate:** On a clean Windows machine with only Ollama installed, a user runs one installer/command and reaches a working local stack (orchestrator + agent registered + Console connected) — **no Docker, no PostgreSQL, no manual Python setup** — and completes a task. SC-8 demonstrated end-to-end.

---

### WP-32 — Orchestrator Auto-Run: Background Service / Bundled with Console — 🔲 `gd-0.2.x`

- **Goal:** The desktop user should not have to start the orchestrator manually. Launching the Console (or booting the machine) brings up a working local orchestrator automatically.
- **Depends on:** WP-30 (SQLite default), WP-31 (bundled runtime).
- **Approach (pick per platform; both may ship):**
  - **A — Console-managed sidecar:** the Tauri Console spawns and supervises a bundled orchestrator process on launch (Tauri sidecar), pointing itself at `localhost`. Adds a **tightly-scoped** sidecar/command capability to `console/src-tauri/capabilities/` (today only `core:default` + `store:default`), preserving the locked-down CSP posture. Health-check before connecting; single-instance guard so multiple Console windows share one orchestrator; graceful shutdown.
  - **B — Background OS service:** install the orchestrator as a **Windows Service** (and launchd/systemd on macOS/Linux) that starts on boot and survives Console restarts — the right choice when the machine also hosts agents for others on a LAN.
- **Steps:**
  1. Implement local-orchestrator lifecycle: detect an already-running orchestrator on the configured port; if none, start the bundled one; supervise and restart on crash; stop cleanly on exit (sidecar) or via service manager (service).
  2. Port/instance management: fixed default port with graceful fallback; single-instance lock; the Console's `ConnectDialog` auto-fills and auto-connects to the managed local orchestrator (manual URL entry stays available for connecting to a remote/server orchestrator).
  3. Windows Service packaging for boot-start (option B); document when to prefer sidecar vs. service.
  4. First-run UX: installing the Console yields a working local stack with no separate orchestrator launch step.
  5. Security review of the added capability/service surface (scoped sidecar permission, localhost-only binding by default, no new inbound exposure).
- **Files:** `console/src-tauri/` (sidecar wiring, scoped capability, bundled orchestrator binary), Console store/WS auto-connect logic, Windows Service installer, docs
- **Exit gate:** Fresh install → launching the Console brings up a working local orchestrator automatically (no manual start); the Console connects on its own; the service option survives a reboot. Connecting to a remote server-tier orchestrator still works via manual URL entry. SC-9 demonstrated.

---

## Phase 2 — Cross-Network Sharing — 🔲 `gd-0.3`

### WP-07 — Multi-Tenant Orchestrator & Identity — 🔲 `gd-0.3`

- **Goal:** Multiple owners coexist on one orchestrator with cryptographically anchored identity and strict namespace isolation.
- **Steps:**
  1. `users` table: `id`, `pubkey (ed25519)`, `display_name`, `org_id`, `created_at`; keypair generated in console on first launch.
  2. Agent registration: `owner_id` bound cryptographically — owner signs registration; orchestrator records public key as identity anchor.
  3. AuthN middleware: ed25519-signed tokens verified on every API call and WS connection.
  4. Namespace isolation: `GET /agents` returns only agents visible to the caller (owned + granted); zero cross-namespace bleed.
  5. Migration to multi-tenant schema; prior single-owner data migrated cleanly.
  6. Integration tests: two users; no namespace bleed; each sees only their own agents.
- **Exit gate:** Two users coexist with zero namespace bleed. Anonymous registration rejected at all endpoints.

**🔧 Desktop-first note:** Write step 5's migration against **WP-30's dialect abstraction** so it runs on both SQLite and PostgreSQL — do not add new PostgreSQL-only SQL. Multi-tenant sharing is primarily a **server-tier** concern (a shared orchestrator), but the schema must remain SQLite-valid so the desktop tier stays on one code path.

---

### WP-08 — Share Token System — 🔲 `gd-0.3`

- **Goal:** Owner mints a cryptographically signed, granularly scoped, instantly revocable token granting a specific grantee dispatch rights to covered agents within defined constraints.
- **Steps:**
  1. `ShareToken` model: `agent_id[]`, `grantee_user_id`, `scopes[]`, `quotas (JSON)`, `conditions (JSON: time_windows, allowed_data_classes, jurisdiction_require)`, `expires_at`, `revoked_at`, `created_by`.
  2. `POST /tokens`: sign with owner key; return compact string (JWT or biscuit-style).
  3. `DELETE /tokens/{id}`: set `revoked_at`; stop dispatch immediately; signal in-flight task abort.
  4. Token verification on **every dispatch**: scope, quota, time-window, data-class, revocation — no exceptions.
  5. Per-grantee quota enforcement at enqueue: max concurrent tasks, RAM per task, wall time.
  6. Audit event on every token mint, import, dispatch, and revoke.
  7. Tests: mint → import → dispatch → scope enforcement → revoke → verify immediate rejection.
- **Exit gate:** Revocation takes effect within one dispatch cycle. Scope violations rejected before reaching the agent.

---

### WP-09 — Agent Runtime — Cross-Owner Dispatch — 🔲 `gd-0.3`

- **Goal:** Agent validates incoming dispatch authority locally, independent of orchestrator — defense in depth for cross-owner scenarios.
- **Steps:**
  1. Local token cache: store grants covering this agent; validate authority before executing any external task.
  2. Double-check: `submitter_id` + scope verified locally even after orchestrator clearance.
  3. Per-task isolated workspace provisioned on receipt; cleaned on completion.
  4. Availability windows honored before accepting tasks from grantees outside configured hours.
  5. Data-class / jurisdiction check: reject tasks exceeding grant's `allowed_data_classes` or `jurisdiction_require`.
  6. Install UX: QR-code-friendly registration token; paste or scan → agent registers and appears in owner's fleet within 30 s, no command-line required.
- **Exit gate:** Cross-location collaborator machine installs runtime, receives scoped token, executes dispatched task, returns result. Revoke tested live — no task accepted after revocation timestamp.

---

### WP-10 — Console — Sharing Panel & Full Fleet View — 🔲 `gd-0.3`

- **Goal:** Console surfaces all owned and shared agents with clear scope indicators; provides self-contained UI for minting, viewing, and revoking tokens — no command-line required.
- **Steps:**
  1. **Fleet Overview:** grid of all visible agents — status badges, location tags, ownership indicator ("shared / limited"), last-seen, model count.
  2. **Sharing Panel:** mint form (agents, scopes, quotas, time windows, data class, expiry); active grant list; one-click revoke with confirmation.
  3. **Token import UX:** paste string or scan QR → shared agent appears in fleet with scope summary and "shared / limited" badge; no command-line.
  4. **Agent Detail:** for shared agents, only permitted actions rendered.
  5. **Owner audit trail:** per-agent event log (grantee, task type, outcome) visible to owner at all times.
  6. Extend **Gruper core's Chart.js analytics** with per-grantee task-volume and quota-usage charts.
- **Exit gate:** All sharing operations (mint, import, revoke) completed in console with no command-line. SC-1 met: new collaborator reaches first task result in < 5 min.

---

### WP-11 — Manager Agent Delegation — 🔲 `gd-0.3`

- **Goal:** A Manager Agent decomposes a goal and dispatches sub-tasks across ownership boundaries within a strict subset of its human principal's scope; all dispatches audited.
- **Steps:**
  1. `manager_agent` task type: payload is a goal + scope budget from the human principal.
  2. Manager loop: decompose → dispatch sub-tasks using a **strict subset** of the principal's token; cannot self-escalate.
  3. Orchestrator enforces: sub-task tokens inherit parent grant scope; escalation rejected.
  4. Delegation chain in `events`: every sub-dispatch records `parent_task_id` and `delegated_from`.
  5. Console: delegation chain in task detail; aggregated result in parent task pane.
  6. Adversarial test: scope escalation attempt rejected by orchestrator.
- **Exit gate:** Manager agent dispatches to ≥ 2 worker agents (one owned, one cross-owner shared); full delegation chain in audit log; escalation attempt rejected.

---

## Phase 3 — Cloud Burst & Cost Control — 🔲 `gd-0.4` (server / cloud tier)

*This phase is inherently server/cloud-tier: Docker and PostgreSQL are appropriate and expected here. It does not apply to the desktop tier.*

### WP-12 — Container Agent Image — 🔲 `gd-0.4`

- **Goal:** Multi-arch Docker image that turns any Linux host into a registered agent node with a single `docker run`. *(Server/cloud tier — Docker is the point here, not a default imposed on desktop users.)*
- **Steps:**
  1. Multi-arch build: `linux/amd64` + `linux/arm64`; separate CPU and CUDA tags.
  2. Entrypoint reads `ORCHESTRATOR_URL`, `REGISTRATION_TOKEN`, `AGENT_TAGS`, `ROLE`, `OLLAMA_BASE_URL` from env or mounted secrets.
  3. Optional Ollama sidecar; GPU passthrough via `--gpus all`.
  4. Boot: env validate → Ollama health check → register → accept tasks.
  5. Published to `ghcr.io/stelminado/gruper-agent` (`cpu`, `cuda`, `latest-cpu`, `latest-cuda`).
  6. CI: multi-arch build + smoke test (register → heartbeat → task) on every push.
  7. **Image layer digests pinned in Terraform module** — mirrors **Gruper core's CDN SRI-hash CI discipline** applied to container integrity; CI fails on digest mismatch.
- **Files:** `agent-runtime/Dockerfile`, `agent-runtime/Dockerfile.cuda`, `.github/workflows/build-agent.yml`
- **Exit gate:** `docker run` one-liner on a fresh Ubuntu VM; agent appears in fleet within 60 s; executes a task; digest pinned and CI-verified.

---

### WP-13 — AWS Spot Fleet & Hard Cost Controls — 🔲 `gd-0.4`

- **Goal:** Terraform module launches AWS spot agent nodes; orchestrator enforces a hard spend cap before any instance starts.
- **Steps:**
  1. Terraform module: spot fleet for `g4dn.xlarge` / `g5.xlarge` and `t3.medium`; `--instance-interruption-behavior=terminate`.
  2. User Data: runs WP-12 `docker run` one-liner; reads secrets from AWS Secrets Manager.
  3. **Hard budget cap:** `POST /pools` accepts `max_spend_usd`; orchestrator refuses dispatch if projected pool cost would breach cap — enforced at enqueue.
  4. Drain signal: `POST /pools/{id}/drain` halts dispatch; agents complete current task and self-terminate.
  5. Idle auto-terminate: agent signals orchestrator on empty queue after `IDLE_TIMEOUT`; self-terminates on confirmation.
  6. Per-instance cost logged per task and pool (instance type × runtime).
- **Files:** `infra/terraform/modules/spot-fleet/main.tf`, `variables.tf`, `outputs.tf`
- **Exit gate:** 2-node spot pool launched; batch of tasks completes; cap halts dispatch at threshold; idle auto-terminate fires within 5 min of queue drain. Spend does not exceed cap under any tested scenario.

---

### WP-14 — Queue-Depth Auto-Scaling — 🔲 `gd-0.4`

- **Goal:** Orchestrator queue depth drives automatic cloud capacity adjustments within configured budget and count bounds.
- **Steps:**
  1. `GET /metrics/queue-depth` per pool: `pending_tasks`, `active_agents`, `estimated_wait_s`.
  2. Scaling trigger (Lambda or scheduler): poll every 60 s; scale out when `estimated_wait_s` exceeds threshold; scale in when `pending_tasks = 0`.
  3. Bounds: `min_agents` / `max_agents` per pool; budget cap enforced before any scale-out.
  4. Scale-down: drain gracefully; terminate only after current task completes.
  5. Cost and utilization dashboard: per-pool spend vs cap, queue depth trend — extends **Gruper core's Chart.js analytics** with cloud cost dimension.
- **Exit gate:** Queue burst triggers scale-out; all tasks complete; idle instances self-terminate; spend within cap. Verified in staging.

---

## Phase 4 — Security Hardening — 🔲 `gd-0.5`

**Hard gate: cross-owner sharing does not advance to beta until all WPs in this phase close.**

### WP-15 — Per-Task Sandboxing — All Platforms — 🔲 `gd-0.5`

- **Goal:** Every task on every agent type runs in an isolated per-task sandbox. Desktop and container containment demonstrably equivalent — the exit gate condition.
- **Steps:**
  1. **Linux desktop:** Firejail — isolated tmpfs, dropped capabilities, seccomp, empty netns with egress allow-list, cgroup CPU/memory/wall-time limits.
  2. **Windows desktop:** Job Objects + AppContainer; WFP egress allow-list; hard CPU and memory quotas.
  3. **macOS desktop:** `sandbox-exec` profile; App Sandbox entitlements; outbound-only network.
  4. **Container:** Docker seccomp + AppArmor/SELinux; `--read-only` rootfs + tmpfs per task; `--network` allow-list; `--cpus` / `--memory` hard caps.
  5. **Equivalence validation suite:** same task type on all four environments; filesystem isolation, egress blocking, resource limits verified identically; written results documented.
  6. Approval gates: `email_send`, external POST, out-of-workspace writes require explicit operator approval.
  7. Cross-task contamination test: no task reads or modifies another task's workspace or host OS state.
- **Exit gate:** Written equivalence report signed off. All four environments pass the validation suite. Cross-user sharing locked in console until this WP closes.

---

### WP-16 — E2E Payload Encryption — 🔲 `gd-0.5`

- **Goal:** E2E payload encryption is a **first-class security requirement** — the orchestrator routes payloads it cannot read.
- **Steps:**
  1. Each agent generates an X25519 keypair on first registration; public key stored in orchestrator and advertised to authorized dispatchers.
  2. Submitter: encrypt task payload to **target agent's X25519 public key** (X25519 ECDH + ChaCha20-Poly1305 AEAD) before submitting.
  3. Orchestrator: store and relay ciphertext; never decrypt; record `payload_hash` for audit only.
  4. Agent: decrypt payload inside sandbox; clear plaintext from memory after use.
  5. Key rotation: agent regenerates X25519 keypair on demand; orchestrator invalidates old reference.
  6. Integration test: orchestrator DB at rest — payload column contains ciphertext, not plaintext. *(Applies to both SQLite and PostgreSQL stores.)*
  7. Simulated compromised-orchestrator test: full DB read access; payload content remains confidential.
- **Exit gate:** SC-4 met for payload confidentiality. Compromised-orchestrator simulation passes and documented. E2E encryption active for all cross-owner dispatches.

---

### WP-17 — Hash-Chained Audit Log — 🔲 `gd-0.5`

- **Goal:** Audit event stream is append-only and tamper-evident — verifiable compliance record for regulated deployments and run attribution.
- **Steps:**
  1. `events` table: add `prev_hash`, `entry_hash`; `entry_hash = SHA-256(ts ‖ actor_id ‖ action ‖ subject_id ‖ payload_hash ‖ prev_hash)`.
  2. Every state transition appends an immutable hash-chained event.
  3. `GET /audit`: paginated, filterable; returns events with hashes for client-side chain verification.
  4. Console audit view: per-agent and per-task event logs with chain-verification indicator; JSON export.
  5. Standalone chain-verification CLI: downloads full chain, verifies hash continuity.
  6. Redaction: sensitive payload content appears only as `payload_hash`; no plaintext in event record.
- **Exit gate:** Chain verifies end-to-end for 500-event dataset. Tampering any field causes verification failure at that event and all subsequent. Compliance JSON export tested. *(Hash-chain logic must be identical across SQLite and PostgreSQL backends.)*

---

### WP-18 — Security Review & Sandbox Parity Sign-off — 🔲 `gd-0.5` exit gate

- **Goal:** Formal security review confirms no critical findings open; sandbox parity, E2E encryption, and token security accepted.
- **Steps:**
  1. Run `/security-review` against full codebase; resolve all critical and high findings before this WP closes.
  2. Threat model verification: every row in the spec threat table verified by implemented controls — tested, not just documented.
  3. **Sandbox parity acceptance:** WP-15 equivalence report reviewed and signed off.
  4. **E2E encryption acceptance:** WP-16 compromised-orchestrator test reviewed and signed off.
  5. Token penetration test: scope escalation, replay attack, revocation bypass, forgery — all rejected; results documented.
  6. Container image digest verification in CI — consistent with **Gruper core's CDN SRI-hash CI step**.
  7. SC-4 and SC-6 verified end-to-end with real test data.
  8. **Desktop-tier surface review:** the WP-32 orchestrator sidecar/service capability, localhost binding, and single-instance handling reviewed for the desktop tier (in addition to the server tier).
- **Exit gate:** No critical or high findings open. Equivalence report accepted. Token penetration test documented with all attacks mitigated. Cross-owner sharing unlocked for beta.

---

## Phase 5 — Console Polish, Crews & Beta — 🔲 `gd-0.6–0.9`

### WP-19 — Capability-Based & Policy-Based Auto-Dispatch — 🔲 `gd-0.6`

- **Goal:** Tasks route automatically to best-fit agents; data-class and jurisdiction constraints enforced at dispatch time.
- **Steps:**
  1. Capability-match query: `SELECT` agents satisfying `hardware`, `models`, `tools`, `roles`, `jurisdiction`, `availability` from task requirements. *(Capability queries must work on both backends — on SQLite the `JSONB`-style capability filters become JSON-function queries; on PostgreSQL they stay JSONB.)*
  2. Policy-priority scoring: prefer local/LAN for interactive; prefer cloud for batch; prefer lower latency for time-sensitive.
  3. Data-class enforcement at enqueue: `confidential` tasks rejected if no in-scope compliant agent available.
  4. Console: "best match" option alongside explicit assignment; shows matched agent(s) and routing rationale before dispatch.
  5. Tests: `confidential` task rejected with no in-scope agent; `internal` task dispatched to lowest-latency candidate.
- **Exit gate:** SC-6 met — sensitive tasks demonstrably never reach non-compliant agents. Auto-dispatch covers interactive, batch, and compliance-restricted routing scenarios.

---

### WP-20 — Crew / Workflow Builder — 🔲 `gd-0.7`

- **Goal:** Visual DAG editor for multi-agent pipelines spanning machines and owners, extending **Gruper core's multi-agent round model** to cross-machine, cross-owner execution.
- **Steps:**
  1. `Crew` model: DAG of `Task` nodes with agent target, input sources, output handling, and timeout.
  2. Visual editor in console: drag-and-drop node graph; nodes = agent tasks; edges = data flow.
  3. YAML/JSON import/export for crew definitions.
  4. Crew execution engine in orchestrator: resolves DAG, dispatches as upstream deps complete, aggregates outputs.
  5. Crew result view: extends **Gruper core's conversation UI** — execution as a conversation thread, one message per agent step.
  6. n8n integration: crew launchable from n8n webhook; crew steps can call n8n workflows as tool calls.
- **Exit gate:** 3-node crew (≥ 1 owned + ≥ 1 cross-owner shared agent) completes a DAG task end-to-end; result displayed in the console crew result view.

---

### WP-21 — Extended Fleet Analytics & Monitoring — 🔲 `gd-0.7`

- **Goal:** Fleet-wide monitoring dashboard extending **Gruper core's Chart.js visual language** and export format to distributed metrics and cloud cost tracking.
- **Steps:**
  1. Fleet metrics: per-agent success rate, response latency, task throughput, queue depth, utilization heatmap.
  2. Cloud cost dashboard: per-pool spend vs cap, per-task cost attribution, spend trend.
  3. Live log streaming: real-time task logs from any connected agent, searchable.
  4. Chart.js line/bar/pie with same color scheme, tooltip format, and CSV/JSON export as **Gruper core's analytics dashboard**.
  5. Threshold alerting: agent offline, queue depth, or cost exceeds threshold → console toast + optional n8n webhook.
- **Exit gate:** Dashboard shows live data for ≥ 3 agents (LAN + shared + cloud). All charts export to CSV/JSON. Alert fires on simulated offline and cost-threshold events.

---

### WP-22 — n8n Bidirectional Integration — 🔲 `gd-0.8`

- **Goal:** Agents callable from n8n workflows; agent tasks can trigger n8n flows — deterministic automation and AI reasoning as peers.
- **Steps:**
  1. **n8n → agent:** HTTP node or custom n8n community node posts to `POST /tasks`; receives result via webhook or polling.
  2. **Agent → n8n:** `n8n_webhook` tool in agent runtime; calls configured n8n URL; receives HTTP response as tool result.
  3. **Crew → n8n:** crew node type wrapping n8n workflow as a DAG step.
  4. Authentication: scoped orchestrator API token per integration.
  5. Published example workflow for each integration direction.
- **Exit gate:** n8n workflow dispatches agent task and receives result. Agent task triggers n8n workflow and receives response. Both tested against a real n8n instance.

---

### WP-23 — Closed Beta & Documentation — 🔲 `gd-0.9` exit gate

- **Goal:** 2–3 trusted cross-location beta collaborators use the system for real work; all SC-1…SC-9 hold; complete documentation published.
- **Steps:**
  1. **Beta participants:** 2–3 collaborators across distinct use cases (≥ 1 regulated environment); confirmed before `gd-0.6` begins.
  2. **Install guide:** the **desktop (SQLite, no-Docker) path first**, then all agent paths (desktop Windows, desktop Linux/macOS, Docker container for servers); QR onboarding; < 5 min for a non-technical user.
  3. **Sharing setup guide:** mint token, configure scope, share, monitor, revoke — no command-line assumed.
  4. **Ops runbook (server tier):** orchestrator deploy (Docker + PostgreSQL), backup/restore, TLS renewal, log rotation, cost-cap monitoring.
  5. **Desktop runbook:** SQLite file location/backup, orchestrator service management, upgrade path.
  6. **Security posture summary (1-page):** what the owner can/cannot see, data-class routing, how to revoke.
  7. **SC-1…SC-9 verification checklist:** run against beta environment; document evidence per criterion.
  8. No critical bugs open at handoff.
- **Exit gate:** All SC-1…SC-9 met for real beta users. Documentation reviewed by ≥ 1 beta participant. No critical bugs open. Ready to assess v1.0.

---

## v1.0 — First Stable Release

Declared when the `gd-0.9` exit gate holds for real users. **This roadmap is rewritten at that point.** Until then, v1.0 appears here only as a future target.

| SC | Criterion | Target |
|----|-----------|--------|
| SC-1 | Install to first remote task result (new cross-location agent node) | **< 5 min** |
| SC-2 | Dispatch overhead, excluding model execution | **< 5–10 s** typical |
| SC-3 | Owner revocation takes effect | **Immediately** — no new tasks; in-flight killable |
| SC-4 | All traffic authenticated, encrypted, auditable | **100%** — no anonymous dispatch |
| SC-5 | Works behind consumer NAT / corporate firewall / AWS, no inbound ports | **No port forwarding ever required** |
| SC-6 | Sensitive task never crosses an unauthorized boundary | **Policy-enforced at dispatch** |
| SC-7 | Agent loses connectivity mid-task | **Local queue survives; syncs on reconnect; no data loss** |
| **SC-8** | **Full local stack (Console + Orchestrator + Agent) on a stock Windows desktop** | **No Docker, no separate DB server; SQLite is the default store** |
| **SC-9** | **Desktop user starts the orchestrator** | **Automatic — Console/service brings it up; no manual launch** |

---

## Post-v1 (`gd-1.x`) — Deferred

Out of scope for the pre-1.0 track. Not scheduled until v1.0 is shipped and stable.

| WP | Item | Notes |
|----|------|-------|
| WP-24 | **Pattern B — Federated per-user orchestrators** | Each user self-hosts; sharing authorizes cross-orchestrator dispatch; agent multi-homing. The desktop tier (WP-30/32) — each user already runs a personal local orchestrator — is a natural stepping stone to federation. Token/data model (WP-08) must not preclude this. |
| WP-25 | **Direct P2P channels (WebRTC / QUIC)** | Orchestrator brokers ICE; large artifacts peer-to-peer; automatic relay fallback. Added only after relay proven in production. |
| WP-26 | **Mobile / PWA console** | Read-only fleet status and approval actions. Console API must not preclude this from `gd-0.2`. |
| WP-27 | **Predictive cloud instance pre-warming** | Pre-launch spot instances from historical arrival patterns. Requires stable utilization baseline. |
| WP-28 | **Cross-machine crews with full scope inheritance** | Full DAG across ownership tiers with automatic scope propagation. Requires WP-20. |
| WP-29 | **Open agent directory with opt-in reputation signals** | Closed-and-invited trust model stays until there is a clear operational reason to open it. |

**Permanently out of scope:** public trustless compute marketplace; blockchain token incentives; anyone-can-join compute grid; server-side Gruper core.

---

## Known Technical Debt

| Item | Severity | Notes |
|------|----------|-------|
| **Orchestrator is PostgreSQL-only; no SQLite/embedded path** | **High** | `asyncpg` driver, `JSONB`, `gen_random_uuid()`, `TIMESTAMPTZ`/`NOW()`, `FOR UPDATE SKIP LOCKED`, CTE `UPDATE…FROM`, `INTERVAL` math, `$1`/`::uuid`/`::jsonb` casts throughout. A `sqlite://` URL cannot open the pool. **Docker + PostgreSQL is effectively required to run the orchestrator until WP-30 lands.** This is the central blocker to the desktop-first goal. |
| **Orchestrator has no CI** | **High** | The only workflows are static Gruper.html checks (`check.yml`) and the Windows console build (`build-windows.yml`). The orchestrator is never started, tested, or built in CI, and its `pytest` suite requires a live PostgreSQL. Add an orchestrator test job (SQLite leg + Postgres leg) in WP-30. |
| **Console/agent do not auto-start an orchestrator** | **Medium** | A desktop user must launch the orchestrator separately today; the Console only connects to a URL. Closed by WP-32. |
| **Companion spec not yet desktop-first** | **Medium** | `GruperDistributedSpec.md` still lists Docker Compose + PostgreSQL as the default and treats "SQLite + Litestream for single-user self-host" as a footnote. Needs a desktop-first alignment pass to match this roadmap. |
| Desktop sandboxing (Linux only until WP-15) | **High** | Windows and macOS per-task sandbox absent until `gd-0.5`. Cross-owner sharing on Windows/macOS blocked until WP-15 and WP-18 close. |
| `events` table lacks hash chain until WP-17 | **Medium** | Event append active from WP-02; tamper-evidence absent until `gd-0.5`. Compliance deployments must not go live before WP-17 closes. |
| Python agent runtime (memory-unsafe) | **Medium** | Acceptable for prototyping. Rust port of sandbox and comms planned as load and security review demand it. |
| Single-orchestrator SPOF | **Medium** | Failover interface in data model from WP-01; full federation deferred to `gd-1.x`. Agent offline queue (WP-03) mitigates partial impact. On the desktop tier the orchestrator is local, so this is a server-tier concern. |
| No full integration test suite | **Medium** | Per-WP smoke tests built incrementally. Full suite and Playwright E2E against mock Ollama deferred to `gd-0.6+`. |

---

## Future Considerations

Not assigned to any phase or work packet. Long-term items to keep in mind for later.

- Automatic self-updating system for the desktop app (Console and bundled orchestrator/agent)
- Proper crash reporting and error telemetry
- First-launch onboarding / setup wizard (pairs naturally with WP-31/32)
- Code-signing and notarization for Windows/macOS installers (needed for a smooth desktop install)

---

*Last updated: 2026-07-01 (strategic pivot to desktop-first: SQLite becomes the default orchestrator backend, PostgreSQL/Docker become the advanced server tier; new Phase 1.5 "Desktop-First Foundation" WP-30…32 added; WP-01…06 kept complete with desktop-first follow-ups; honest current state — the orchestrator is PostgreSQL-only today and Docker/Postgres is effectively required until WP-30)*
*Companion document: `GruperDistributedSpec.md` — architecture diagrams, data models, wire schemas, security threat table, and open questions (OQ-1…OQ-5). Pending a desktop-first alignment pass.*
*Gruper core baseline: `v0.4.5` (`Gruper.html`) — this roadmap builds on core, not over it.*
