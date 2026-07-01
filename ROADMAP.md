# Gruper Distributed — Engineering Roadmap

**Status as of 2026-07-01:** `gd-0.1` / `gd-0.2` / `gd-0.2.x` — **Phase 0 complete; WP-03/04/05 code complete; WP-06 automated end-to-end relay validation is green (17/17 — five dispatch-contract bugs found and fixed); WP-30 (SQLite backend) is complete; WP-31 (desktop packaging) and WP-32 (orchestrator auto-run) are code-complete and validated on Linux, including against a real production Tauri build — Windows hardware validation is the one gate left across all three.** Remaining gates on the desktop-first push:
- The `gd-0.2` field gate — the real two-machine public-internet/NAT run (runbook in [`docs/WP-06-Validation.md`](docs/WP-06-Validation.md) §7) — is still pending.
- **WP-31/WP-32 have not been run on real Windows hardware.** Everything was built and verified on Linux. The Windows CI job (`build-windows.yml`) itself **has succeeded repeatedly** — 18 green runs as of this writing, including on `main` — so it reliably produces `.exe`/`.msi`/agent-orchestrator artifacts; what's still open is a human downloading and running one of those artifacts on a physical Windows machine, and the `.ps1` script is likewise unverified there. This is now the single biggest remaining risk on the desktop-first push — see each WP's own section for specifics.

· WP-01 ✅ · WP-02 ✅ · WP-03 ✅ code complete · WP-04 ✅ code complete · WP-05 ✅ complete · WP-06 ✅ automated E2E validated on **both backends** (17/17 SQLite; 17/17 PostgreSQL; SC-2 ~10 ms on either) · 🔲 real two-machine NAT field run pending · **WP-30 ✅ complete** (SQLite default, PostgreSQL opt-in, dual CI) · **WP-31 🟡 Linux-validated, Windows CI green (18 runs) but installers not yet run on real hardware** · **WP-32 🟡 sidecar auto-connect implemented and validated on Linux against a real `tauri build` production binary; agent onboarding flow hardened — no more placeholder-model registration, detected models now actually reach the spawned agent, spawn failures are reported instead of silently timing out, and a real-Windows test run's Ollama-detection failure (blocked by Chromium's Private Network Access policy) is now fixed but not yet re-verified on Windows hardware** · OQ-1 and OQ-2 resolved · **v1.0 is a future finish line gated on SC-1…SC-9; it has not been reached.**

---

## ⚠️ Honest current state (read this first)

**Updated 2026-07-01 — WP-31 and WP-32 landed (Linux-validated).** The gaps called out in the previous revision of this section (no packaging, no auto-start) are closed on Linux, with real evidence, not just plans. Be precise about what's true now vs. what's still open:

| Component | Runs on a stock Windows desktop with **no Docker**? | Backing store today |
|-----------|------------------------------------------------------|---------------------|
| **Gruper core** (`Gruper.html`) | ✅ Yes — double-click the file; needs only a browser + Ollama | none (client-only) |
| **Agent runtime** | ✅ Yes on Linux, packaged as a self-contained executable (`agent-runtime/packaging/`) — Windows `.exe` built successfully by CI (18 green runs), but not yet downloaded and run on real Windows hardware | **SQLite** (`agent.db`, local offline queue) |
| **Manager Console** (Tauri) | ✅ Yes — native desktop app; **auto-starts and auto-connects to a local orchestrator with zero manual steps** (WP-32), verified against a real production build on Linux; **"+ Add Local Agent" (WP-32.1) takes a user from zero agents to a running one without touching a config file** | `localStorage` / tauri-store (auth token); pubkey identity auto-generated, no manual command |
| **Orchestrator** | ✅ Yes on Linux, packaged as a self-contained executable (`orchestrator/packaging/`), zero-config (auto-generates JWT secret, auto-creates SQLite file) — Windows `.exe` built successfully by CI (18 green runs), but not yet downloaded and run on real Windows hardware | **SQLite by default** (`orchestrator.db`); **PostgreSQL opt-in** via `DATABASE_URL=postgresql://...` |

**What changed in WP-31/WP-32:** the orchestrator and agent are now built into self-contained executables via PyInstaller (`scripts/build-desktop.sh`/`.ps1`, one command), the orchestrator auto-generates a JWT secret on first run instead of using a shared insecure default, and the Tauri Console spawns the orchestrator as a managed sidecar process, auto-detects when it's healthy, and auto-connects — no manual URL entry, no manual pubkey generation, no separate "start the orchestrator" step. `scripts/validate-desktop-packaging.py` proves the packaged orchestrator + packaged agent relay a task end to end; a screenshot-verified run against the actual `tauri build` production binary (not just `cargo build` or a dev server) proves the Console reaches its authenticated dashboard with zero user interaction.

**What changed this pass (WP-32.1 — agent onboarding, plus fixes):** the orchestrator sidecar's working directory is now explicitly resolved to the Tauri app-data directory instead of an arbitrary CWD (a real crash risk on a Windows installer launch, where the CWD is often a non-writable `Program Files` path); the previously-broken `orchestrator/README.md` Quick Start command is fixed; a Windows-only crash bug in `agent-runtime/main.py` (unconditional `loop.add_signal_handler`, unsupported on Windows' event loop) is fixed; and the Console can now register and launch a local agent end to end via a new "+ Add Local Agent" flow — see WP-32.1 below for the full detail. This directly closes the "zero onboarding path for a normal user" gap called out in prior audits.

**What is still honestly incomplete (do not overclaim this either):**
- **Not run on a real Windows machine, at all.** Every functional verification above — the packaged executables, the sidecar auto-connect, the forceful-kill orphan-detection watchdog — was built and tested on Linux. There is no Windows hardware available here. The Windows CI job **does** build and bundle successfully (18 green runs to date, including on `main`), so the artifacts exist and are downloadable — but the actual `.exe` outputs have not yet been downloaded and run by a human on Windows. This is the single largest remaining risk — see WP-31/WP-32's own sections for the specific unknowns (PyInstaller Windows quirks, antivirus false-positives on unsigned executables, Windows process-model differences for the orphan watchdog).
- **`asyncpg` is still bundled into the orchestrator executable** even on a pure-SQLite desktop build — unused weight, not a functional problem.
- **Windows Service (auto-run option B) was not built.** Only the Console-sidecar approach (option A) shipped; a service is still the right answer for a machine hosting agents for others on a LAN, but that's a different use case than what this push targeted.
- **Not validated on Windows.** WP-06's E2E re-run (both backends, 17/17) was on Linux, same as the original run. The SQLite path has not yet been exercised on an actual Windows machine.
- **Mock Ollama only.** WP-06 still uses the deterministic mock, on both backends — a real model has never been exercised through this harness.
- CI now has a real orchestrator test job (previously entirely missing) — `.github/workflows/orchestrator-tests.yml`, one job per backend — but it, too, runs on `ubuntu-latest`, not Windows.

See WP-30's own section below for the full list of what was built, what broke during the port and how it was fixed, and specific trade-offs.

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
| **1.5 — Desktop-First Foundation** | **`gd-0.2.x`** | **SQLite-default orchestrator; whole stack on a Windows desktop, no Docker; orchestrator auto-run** | **🔄 WP-30 ✅ complete; WP-31 🟡 + WP-32 🟢 code-complete, Linux-validated — Windows hardware validation is the last gate** |
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
- **Re-validated on both backends (2026-07-01, after WP-30):** the harness now takes `--backend {sqlite,postgres}` (SQLite default). **17/17 green on SQLite** (no PostgreSQL, no Docker — the desktop tier) **and 17/17 green on PostgreSQL** (unchanged server-tier path), with near-identical dispatch latency (SQLite p50 ~10.0 ms vs. Postgres p50 ~9.8 ms). This is the first time the relay has been proven end to end without any database server running.
- **Exit gate:** SC-2 baseline documented ✅ on both backends. Relay model proven at the protocol/logic level ✅ (automated E2E, both backends). **Remaining for full `gd-0.2` sign-off:** the real two-machine public-internet/NAT field run (§7 runbook) — SC-5 single-owner case on real hardware — and a real-Windows / real-Ollama run of the same harness (tracked under WP-31).

**🔧 Desktop-first follow-up — updated 2026-07-01, WP-30 closes most of this:** The original 17/17 run was **Docker-free** but ran **against a real PostgreSQL 16 instance**, with a **mock** Ollama, on **Linux, loopback only**. WP-30 added a `--backend sqlite` leg that is now **also** 17/17 green, closing the "never run without a database server" gap. What's **still** open:
- **SC-8 desktop gate — partially met.** The SQLite/no-Postgres/no-Docker leg is proven ✅ on Linux. **Not yet proven:** on a **real Windows desktop**, or with a **real Ollama** (both still owned by WP-31).
- The existing **SC-5 field gate** (two-machine NAT over the public internet) remains the server/relay proof and is unchanged — still pending, independent of backend choice.

---

## Phase 1.5 — Desktop-First Foundation — 🟡 `gd-0.2.x` — code-complete, Windows hardware validation is the last gate

**Goal of the phase:** make the desktop tier real. After this phase, a solo user on a stock Windows desktop can run Console + Orchestrator + Agent with SQLite, no Docker, and no separate database server — ideally without ever manually starting the orchestrator. PostgreSQL and Docker remain fully supported for the server tier but become opt-in.

**Where this phase actually stands:** all three work packets (WP-30, WP-31, WP-32) are code-complete and each has been directly, empirically verified — not just implemented and assumed to work. WP-30 is fully done including CI. WP-31 and WP-32 are fully validated on Linux, including against the real production `tauri build` binary (not just a debug build or dev server) for the sidecar/auto-connect path, and the packaged orchestrator+agent executables relay a real task end to end. The one thing this phase has **not** done is prove any of it on an actual Windows machine — no Windows hardware was available in this session, so that verification is explicitly called out as open in each WP's section rather than assumed to work by extension from the Linux results.

> **Dependency ordering:** WP-30 (SQLite backend) is the keystone and lands first. WP-31 (local setup/packaging) and WP-32 (auto-run) build on it. Phase 2's multi-tenant migration (WP-07) should be written against WP-30's abstraction.

### WP-30 — Orchestrator SQLite Backend (default for desktop) — ✅ complete · `gd-0.2.x`

- **Goal:** Make **SQLite the default** orchestrator backend for local/desktop use, with **PostgreSQL selectable** via `DATABASE_URL` for the server tier. Both pass the same test suite and expose identical API/wire behavior.
- **Steps:**
  1. ✅ **Backend selection:** `DATABASE_URL` scheme parsed in `orchestrator/db/connect.py`; unset → `sqlite:///orchestrator.db` (mirrors the agent's `agent.db` convention); `postgresql://`/`postgres://` selects the Postgres path. `aiosqlite` added to `requirements.txt` alongside `asyncpg` (see trade-off below).
  2. ✅ **DDL ported** to a dual `migrations/postgres/` + `migrations/sqlite/` layout (same filenames, same order, dialect-appropriate types: `UUID→TEXT`, `JSONB→TEXT`, `TIMESTAMPTZ→TEXT`; `gen_random_uuid()`/`NOW()` DB-side defaults dropped in favor of explicit application-generated values on *both* dialects — see design note below).
  3. ✅ **Queries ported.** Turned out to need far less dialect-specific SQL than expected: a generic adapter in `db/sqlite.py` handles `$N → ?N` (SQLite's numbered-parameter form — verified empirically to bind correctly regardless of where a placeholder appears in the SQL text, not just in ascending order), strips `::type` casts, and drops the literal `FOR UPDATE SKIP LOCKED` clause. Only the timeout watchdog's `INTERVAL` arithmetic needed genuinely dialect-specific SQL (`main.py`, via `db.q(pg=..., lite=...)`), using SQLite's `datetime()` function — both sides of the comparison must be run through `datetime()` to normalize format, or the TEXT comparison silently gives the wrong answer (caught by testing, not by inspection).
  4. ✅ **Dispatch strategy.** `dispatch_pending_for_agent`'s `WITH cte AS (...) UPDATE ... FROM ... RETURNING` pattern turned out to work on SQLite too (3.35+, bundled with Python 3.11) once `FOR UPDATE SKIP LOCKED` is dropped — SQLite has no row-level lock, but doesn't need one: all writes on the desktop tier serialize through one shared `aiosqlite` connection guarded by an `asyncio.Lock` (added after testing surfaced a real race — see trade-offs). WAL mode + `busy_timeout` enabled on connect.
  5. ✅ **Tests parametrized.** `conftest.py`: SQLite (fresh temp file, zero services) by default; PostgreSQL when `TEST_DATABASE_URL` is set. **35/35 passing on both**, verified across 5 repeated runs each for determinism (not just one green run).
  6. ✅ **CI added** — previously **completely missing** (the only prior workflows were static `Gruper.html` checks and the Windows console build; the orchestrator was never built or tested in CI). New `.github/workflows/orchestrator-tests.yml`: `test-sqlite` (no services) and `test-postgres` (service container) as two separate jobs, not one matrix job — deliberately, so the SQLite job structurally cannot depend on a database service, proving the desktop claim rather than just asserting it.
  7. ✅ **Docs updated:** `orchestrator/README.md` (SQLite quick start first, PostgreSQL moved under "Advanced"), `.env.example`, root `README.md` (light touch — full restructure is WP-31), `docs/WP-06-Validation.md`.
- **Design decisions made while implementing (not fully knowable in advance):**
  - **No ORM** — confirmed the right call. A ~150-line hand-rolled `Database` abstraction (`db/base.py`, `db/postgres.py`, `db/sqlite.py`) with a generic SQL adapter covers the whole codebase; introducing SQLAlchemy Core would have been strictly more machinery for no behavioral benefit here.
  - **UUIDs and timestamps became Python-generated** (`uuid.uuid4()`, `datetime.now(timezone.utc)`), passed explicitly on every INSERT/UPDATE, instead of relying on `gen_random_uuid()` / `NOW()` DB defaults. This was necessary (SQLite has neither), and it's a net simplification on the PostgreSQL side too — no behavior change for well-formed requests, verified by the full suite passing unchanged on that backend.
  - **UUID format validation moved to Python** (`db/util.py::is_valid_uuid`, using `uuid.UUID()`) at the ~4 call sites that used to rely on PostgreSQL's `::uuid` cast raising `InvalidTextRepresentationError` for malformed input. SQLite has no equivalent cast-time validation, so without this change a malformed UUID would 404 on SQLite but 422 on PostgreSQL — a real cross-backend behavior difference, now eliminated on both.
- **Trade-offs / limitations found and documented (be honest about these):**
  - **`asyncpg` is still a hard dependency**, even for a pure-SQLite desktop run — `orchestrator/db/connect.py` imports `PostgresDatabase` unconditionally, which imports `asyncpg` at module load. Trimming this (lazy import, or a `requirements-desktop.txt` / `requirements-server.txt` split) is left to WP-31, since it's a packaging/dependency-footprint concern, not a "does SQLite work" concern.
  - **`SQLiteDatabase` needed an `asyncio.Lock`** around every method, not just a shared connection. Initial assumption ("aiosqlite serializes calls, so one connection is enough") was wrong: a single logical operation issues several sequential `execute()`/`commit()` calls, and without an explicit lock a *different* concurrently-running asyncio task (the WS handler runs as a background task alongside HTTP requests) can interleave its own commit mid-sequence, which SQLite rejects with `"cannot commit transaction - SQL statements in progress"`. Caught by the test suite, not by design review.
  - **A genuine, pre-existing concurrency bug was found and fixed in `ws/agent_ws.py`, independent of database backend.** `_handle_register` used to return the connected `agent_id` to its caller only *after* also sending the "registered" ack, broadcasting a fleet event, and dispatching queued tasks. If the WebSocket disconnected in that window — confirmed to happen with the currently-installed anyio/Starlette test-client versions, and structurally possible in production (e.g. a client disconnecting immediately after registering) — the caller's `finally:` cleanup never learned the `agent_id` and skipped it entirely, leaving a phantom "idle" agent that was never marked offline or cleaned up. Fixed by having `_handle_register` hand `agent_id` back to the caller (via a callback) as soon as the agent is logically connected, *before* the best-effort follow-up work. **Verified this bug pre-dates WP-30**, via a clean git-worktree checkout of the pre-WP-30 commit — not something this work packet introduced, but found and fixed while pursuing dual-backend test parity.
  - **Two other pre-existing test failures, unrelated to any database backend, were found and fixed while chasing "why doesn't the suite pass identically on both backends":** (1) `test_register_without_token_returns_403` — FastAPI's `HTTPBearer` now returns 401 (not 403) for a missing Authorization header on the currently-installed fastapi/starlette versions; test updated to assert 401. (2) Several WS message tests (`task_ack`, `result`) that send a "fire and forget" frame with no response, then immediately assert its side effect via a separate REST call — Starlette's `TestClient` runs the app in a background-thread portal, so "sent" doesn't mean "processed yet"; a short synchronization wait was added at those specific points. Both confirmed to reproduce identically on a pristine pre-WP-30 checkout against real PostgreSQL — dependency drift, not a WP-30 regression.
- **Files:** `orchestrator/db/` (new: `base.py`, `postgres.py`, `sqlite.py`, `connect.py`, `migrate.py`, `util.py`), `orchestrator/database.py` (now a thin façade preserving the old public API), `orchestrator/config.py`, `orchestrator/dispatcher.py`, `orchestrator/main.py`, `orchestrator/routers/{auth,agents,tasks}.py`, `orchestrator/ws/agent_ws.py`, `orchestrator/migrations/{postgres,sqlite}/*.sql`, `orchestrator/requirements.txt`, `orchestrator/tests/{conftest,test_tasks,test_heartbeat,test_register}.py`, `.github/workflows/orchestrator-tests.yml` (new), `orchestrator/README.md`, `orchestrator/.env.example`, `README.md`, `docs/WP-06-Validation.md`, `tests/e2e/wp06_relay_validation.py` (`--backend {sqlite,postgres}` flag added).
- **Exit gate — met, verified directly (not just by reading the diff):** `DATABASE_URL` unset → real `uvicorn orchestrator.main:app` process starts with **no PostgreSQL and no Docker**, creates `orchestrator.db`, runs migrations, and `curl /v1/health` → `{"status":"ok","db":"ok"}`. Full smoke suite (35/35) green on both backends, repeated 5× each. WP-06 E2E harness 17/17 green on both backends (`--backend sqlite` and `--backend postgres`), with near-identical dispatch latency.

---

### WP-31 — One-Click Local Setup & Packaging (Windows-first) — 🟡 `gd-0.2.x` · Linux-validated, Windows CI green but installers not yet run on real hardware

- **Goal:** A non-technical user on a stock **Windows** desktop can get the full local stack running with **minimal extra dependencies** — no Docker, no PostgreSQL, no manual venv/Python juggling. macOS and Linux get the same experience where practical.
- **Depends on:** WP-30 (SQLite default) — ✅ done, unblocks this.
- **What's built and verified (2026-07-01, this session — on Linux; see caveat below):**
  1. **`orchestrator/packaging/entry.py` + `gruper-orchestrator.spec`** — PyInstaller `--onefile` entry point and spec. Produces a single ~15–30 MB self-contained executable: no Python install, no Docker, no PostgreSQL needed on the target. Binds `127.0.0.1` by default (not `0.0.0.0` — a desktop orchestrator has no business listening on the network by default), overridable via `GRUPER_ORCHESTRATOR_HOST`/`GRUPER_ORCHESTRATOR_PORT`. Confirmed relocatable (copied to an unrelated directory, still ran and created its SQLite file there).
  2. **`agent-runtime/packaging/gruper-agent.spec`** — same treatment for the agent runtime; builds cleanly since the agent's flat module layout bundles `main.py` directly.
  3. **Zero-config secrets, for real this session, not just planned:** `orchestrator/config.py`'s `jwt_secret` validator now auto-generates a secret with `secrets.token_hex(32)` and persists it to `.gruper_jwt_secret` (mode `0600`) on first run if `JWT_SECRET` isn't set — replacing what was previously just a warning against the insecure hardcoded default. This closes a real security gap, not just a UX one: previously every zero-config desktop install shared the *same* hardcoded JWT secret.
  4. **`scripts/build-desktop.sh`** (Linux/macOS) **and `scripts/build-desktop.ps1`** (Windows, written but not personally run on Windows hardware — see caveat) — one-command build: creates/reuses a build venv, installs both runtimes' requirements + PyInstaller, runs both `.spec` files, and stages the orchestrator executable as the current platform's Tauri sidecar binary (auto-detects the host's Rust target triple).
  5. **`scripts/validate-desktop-packaging.py`** — end-to-end validation script, committed as a reusable tool: spawns a mock Ollama, the *actual bundled orchestrator executable* (not `python main.py` — the real PyInstaller output), registers a user + agent over REST, spawns the *actual bundled agent executable*, submits a task, and polls it to completion. **Verified green**: "RESULT: ALL GREEN — packaged orchestrator + packaged agent validated end to end", full relay round-trip confirmed against the real bundled binaries, not source.
  6. **`.github/workflows/build-windows.yml` extended** — added a `windows-latest` build leg (not a new workflow) that installs Python 3.11, runs both PyInstaller specs, stages both the orchestrator and agent as Tauri sidecar binaries (see WP-32.1's note on a staging bug that briefly regressed this), and uploads both executables as build artifacts (30-day retention) alongside the existing NSIS/WiX console installers.
  - Two non-obvious PyInstaller pitfalls, worth knowing if this breaks again: (a) the ASGI app must be **imported as an object** (`from orchestrator.main import app`), not passed to uvicorn as the string `"orchestrator.main:app"` — the frozen import system can't resolve a dynamic string-based import target and fails at runtime with `Could not import module`, even though the build itself succeeds; (b) PyInstaller needs `pathex`/`--paths <repo-root>` to discover the local `orchestrator` package, since the entry script lives outside the package directory.
- **⚠️ Honest caveat — not yet run on a real Windows machine.** Everything above was built and verified on Linux (no Windows hardware available here). The Windows CI job (`build-windows.yml`) **has been triggered and watched succeed** on a `windows-latest` runner — 18 green runs as of this writing, including on `main` and on feature branches — so the build/bundle steps themselves are proven, not just reviewed. What's still open: **no human has downloaded one of those artifacts and double-clicked it on physical Windows hardware.** The `.ps1` script is likewise unverified in that sense. This is the single biggest remaining risk in WP-31: PyInstaller's Windows behavior (path separators, `.exe` extension handling, antivirus false-positives on freshly-built unsigned executables) can differ from Linux in ways CI succeeding cannot catch.
- **Remaining open steps:**
  1. Download the CI-produced `.exe`/`.msi` and confirm they install and run correctly on a real Windows machine — CI succeeding is not the same as a human confirming the installed app works.
  2. ~~Ollama detection & guidance in the desktop happy path~~ — ✅ addressed this pass: the Console's "Add Local Agent" flow (see WP-32.1 below) now distinguishes "Ollama unreachable" from "Ollama running, no models" from "unexpected response," auto-detects on dialog open, offers a Retry, and **refuses to register an agent until at least one real model is confirmed** — it no longer silently falls back to a placeholder model tag. Still open: no first-run nudge to *install* Ollama if it's entirely absent (the dialog links to ollama.ai but doesn't walk the user through installation).
  3. First-class Windows agent install (promote the agent's NSSM stub to a documented, supported Windows install).
  4. Trim the `asyncpg` hard dependency for a pure-SQLite desktop build (see Known Technical Debt) — currently still bundled into the orchestrator executable even though it's unused on the desktop path, adding avoidable size.
  5. Real Windows + real Ollama run of the WP-06 E2E harness (still the open half of the SC-8 gate).
- **Files:** `orchestrator/packaging/` (new), `agent-runtime/packaging/` (new), `orchestrator/config.py` (JWT auto-gen), `orchestrator/requirements.txt` (+`psutil`, used by the WP-32 watchdog below), `scripts/build-desktop.sh` / `.ps1` (new), `scripts/validate-desktop-packaging.py` (new), `.github/workflows/build-windows.yml` (extended), `.gitignore` (build output / secrets / sidecar staging dir excluded).
- **Exit gate:** partially met. On Linux, one command (`scripts/build-desktop.sh`) produces working orchestrator + agent executables and `scripts/validate-desktop-packaging.py` proves they relay a task end to end with **no Docker, no PostgreSQL, no manual Python setup** at runtime. **Not yet met:** the same proof on a real clean Windows machine — CI produces the artifacts, but nobody has downloaded and run them on Windows yet.

---

### WP-32 — Orchestrator Auto-Run: Background Service / Bundled with Console — 🟢 `gd-0.2.x` · sidecar approach (A) implemented and validated on Linux; service approach (B) not attempted

- **Goal:** The desktop user should not have to start the orchestrator manually. Launching the Console (or booting the machine) brings up a working local orchestrator automatically.
- **Depends on:** WP-30 (SQLite default) — ✅ done; WP-31 (bundled runtime) — ✅ the PyInstaller executable is exactly what the Tauri sidecar spawns.
- **Approach taken: A — Console-managed sidecar.** Option B (Windows Service) was **not attempted** this session — see "Sidecar vs. Windows Service" below for when B would still be worth building.
- **What's built and verified (2026-07-01, this session):**
  1. **`console/src-tauri/src/lib.rs` rewritten** to own the full sidecar lifecycle: on launch, checks whether something is already answering `/v1/health` on `127.0.0.1:8080` (an existing sidecar from another launch, a manually-started orchestrator, or the server-tier docker-compose stack) and reuses it instead of spawning a duplicate; otherwise spawns the bundled `gruper-orchestrator` sidecar binary (via `tauri-plugin-shell`'s `Command::sidecar`) and polls health for up to 15 s.
  2. **`tauri-plugin-single-instance`** added — a second Console launch focuses the existing window instead of starting a second sidecar and racing for the port.
  3. **Status reporting to the frontend, done two ways because one alone isn't reliable:** an `orchestrator-status` event (`checking` / `existing` / `ready` / `failed`, with an error message on failure) AND a queryable `get_orchestrator_status` Tauri command backed by shared `Mutex` state. **Both are necessary** — this was discovered by testing, not assumed: a plain Tauri event fired before the frontend's `listen()` call has attached is silently dropped, not queued, and the sidecar's health check can easily resolve *before* the webview finishes loading its JS bundle. The first version of this feature (event-only) silently failed to auto-connect for exactly this reason; adding the queryable command as a "catch up on what I missed" fallback fixed it.
  4. **Frontend auto-connect wired up** (`console/src/lib/stores/orchestrator.ts` new, `console/src/lib/components/ConnectDialog.svelte` updated): the Connect dialog listens for sidecar status, auto-fills the orchestrator URL, and auto-submits the connect flow the moment the local orchestrator is healthy — no user action required. Manual entry remains fully available and unchanged for a remote/server orchestrator.
  5. **The "run a Python command to generate a pubkey" instruction is gone.** `authStore.getOrCreatePubkey()` generates a random 32-byte client identity via `crypto.getRandomValues` on first launch and persists it in `localStorage`, reused on every subsequent launch. This works because gd-0.1's `/v1/auth/token` find-or-creates a user by pubkey alone (ed25519 signature verification is stubbed until WP-07) — a random value serves as a stable identity just as well. The pubkey field still exists in the UI behind an "Advanced" disclosure for anyone who wants to inspect or deliberately reuse an identity across installs.
  6. **Graceful shutdown, two redundant paths:** `WindowEvent::Destroyed` and `RunEvent::ExitRequested`/`Exit` both call `child.kill()` on the tracked sidecar handle. Verified: closing the Console window cleanly stops the sidecar orchestrator.
  7. **Forceful-kill (orphan) handling — the harder problem, also solved and verified:** `WindowEvent::Destroyed` does **not** fire on `kill -9` (confirmed by testing) — and the equivalent is true on Windows for Task Manager's "End Task" (`TerminateProcess`), which cannot be intercepted by *any* code running inside the victim process, full stop. This is solved from the *other* side: `orchestrator/packaging/entry.py` accepts a `GRUPER_EXIT_WITH_PARENT` env var (set by the sidecar spawn code) and runs a background watchdog thread that walks its **full ancestor chain** (not just the immediate parent) and self-terminates if any ancestor's `(pid, create_time)` changes. Walking the full chain, not just the immediate parent, was necessary because PyInstaller's `--onefile` mode runs the actual app as a child of its own bootloader process — a naive "did my immediate parent's PID change" check never fires, because the immediate parent (the bootloader) is untouched even when the Console two levels up is gone; this was found by testing the naive version and watching it fail to detect the orphan.
- **End-to-end validation performed this session (Linux, headless via Xvfb):**
  - Launched the real built Console binary; confirmed the sidecar orchestrator spawns, becomes healthy, and is reachable via `curl`.
  - `kill -9`'d the Console process directly; confirmed the orphaned orchestrator self-terminates within one watchdog poll interval (~2 s) with no lingering process, re-confirmed after removing temporary debug instrumentation from the final production code.
  - Ran the Console against a live Vite dev server (`npm run dev`) first and captured an X11 screenshot of the actual rendered window: **the auto-connect flow works end to end with zero user interaction** — the Console goes straight from launch to the authenticated fleet dashboard, with the orchestrator issuing a real JWT, the console WebSocket connecting, and `GET /v1/agents` / `GET /v1/tasks` succeeding, all without the user typing a URL, generating a pubkey, or clicking Connect.
  - Along the way, a real bug was caught and fixed by this screenshot-driven testing (see point 3 above): the first cut of the auto-connect feature relied on the Tauri event alone and silently never fired in practice — a plain debug `cargo build` Console binary loads `build.devUrl` (the Vite dev server) rather than the bundled static frontend, which is why the dev-server run was needed to exercise the frontend at all.
  - **Then re-verified against the actual production build** (`npx tauri build --no-bundle`, the same underlying build `tauri-apps/tauri-action` runs in CI) — no dev server involved, the real `frontendDist`-embedded bundle serving from the compiled binary. Same result: screenshot confirms the fully auto-connected dashboard, orchestrator log confirms the full token → WebSocket → agents/tasks sequence, and the forceful-kill (`SIGKILL`) orphan-detection re-test against this exact release binary also passed — sidecar self-terminated with no lingering process. This closes what was the single biggest open risk in this feature (an untested gap between dev-mode and real shipped-binary behavior).
- **⚠️ Honest caveats:**
  - **Not validated on Windows at all** — the entire lifecycle (spawn, health-check, single-instance guard, graceful and forceful shutdown, production-build auto-connect) was built and tested only on Linux. Windows' process model differs meaningfully from Linux's (no POSIX signals, `TerminateProcess` instead of SIGKILL, different child-process/job-object semantics) — the `psutil`-based ancestor-walk approach *should* port cleanly since `psutil` abstracts this, but it has not been run on a real Windows machine.
  - **Windows Service (option B) was not attempted.** It remains the right choice for a machine that hosts agents for *other* people on a LAN and needs the orchestrator to survive a Console restart or run headless at boot — a genuinely different use case from "launch the Console, it just works," which is what this session targeted.
- **Sidecar vs. Windows Service — when to use which:**
  | | Sidecar (built, option A) | Windows Service (not built, option B) |
  |---|---|---|
  | Starts when | Console launches | Machine boots, independent of the Console |
  | Survives | Console restart? No — tied to Console's lifetime | Console restart, and the Console never launching at all |
  | Best for | The default single-user "launch Console, everything works" desktop experience | A machine acting as a standing LAN orchestrator host for other people's agents, or a headless box with no one ever opening the Console |
  | Extra complexity | None beyond what's shipped — no install/uninstall step, no admin rights needed | Requires a service installer, admin rights to install/uninstall, separate start/stop/log surface from the Console |
  For the "normal Windows desktop user" audience this roadmap targets, the sidecar is the right default and is what's shipped. Revisit option B only if/when a real LAN-host or headless-server desktop use case shows up.

#### WP-32.1 — Minimum Viable Agent Onboarding ("Add Local Agent") — 🟡 implemented and verified end-to-end on Linux; a real Windows test run found and fixed one Windows-only detection bug, re-verification on Windows still pending

Prior audits of this codebase were consistent and correct: the orchestrator + Console sidecar story worked, but **the agent side had zero onboarding path for a normal user.** A desktop user who successfully launched the Console still landed on an empty fleet with no way to add an agent short of hand-editing `agent-runtime/.env` and copy-pasting a JWT out of a `curl` command. That gap is now closed for the single-machine case:

- **`console/src-tauri/src/lib.rs`**: new `spawn_local_agent` Tauri command. Spawns the bundled `gruper-agent` sidecar (new `bundle.externalBin` entry, staged by `scripts/build-desktop.sh`/`.ps1` alongside the orchestrator) with `AGENT_ID`/`JWT_TOKEN`/`ORCHESTRATOR_URL` (converted from the Console's http(s) URL to the agent's expected `ws(s)://.../v1/agents/ws`)/`OLLAMA_URL`/`CAPABILITIES` env vars. Each spawned agent gets its own working directory under the Tauri app-data dir so multiple local agents' SQLite offline queues (`agent.db`) don't collide. `SidecarState` was generalized from "one orchestrator child" to "one orchestrator child + a map of agent children by id" so every spawned process — not just the orchestrator — gets killed on Console exit.
- **`console/src/lib/components/AddAgentDialog.svelte`** (new) + a "+ Add" button in the fleet sidebar: generates a fresh agent identity the same way the Console generates its own (`generateRandomPubkey`, factored out of `stores/auth.ts`), probes `http://localhost:11434/api/tags` for installed Ollama models, calls `POST /v1/agents` with the **Console's own JWT** — verified correct because gd-0.1 tokens are per-owner, not per-agent (`orchestrator/ws/agent_ws.py` only checks the token's `sub` against the agent's `owner_id`) — then invokes `spawn_local_agent`. The new agent is pushed into `fleetStore` immediately (new `fleetStore.add()`) so it's visible before its first heartbeat, rather than waiting on the next full REST reload.
- **This pass — three root-cause fixes, not just surface polish:**
  1. **No more placeholder registration.** The dialog used to fall back to a fake `llama3.1:8b` capability and register/spawn the agent anyway whenever Ollama wasn't running or had no models — producing a fleet entry that could never actually run a task. Ollama detection is now a real state machine (`unreachable` / `no_models` / `ready` / `error`, distinguished by response — not just "success or fail"), runs automatically the instant the dialog opens (previously only on a manual button click), offers a **Retry**, and the **"Add Agent" button is disabled until at least one real model is confirmed**, with the reason shown inline.
  2. **The detected model never actually reached the agent process.** `spawn_local_agent` set `AGENT_ID`/`JWT_TOKEN`/`ORCHESTRATOR_URL`/`OLLAMA_URL` but never `CAPABILITIES` — and even if it had, `agent-runtime/ws_client.py`'s `_model_and_options()` hardcoded `"llama3.1:8b"` as the fallback model for any task that didn't explicitly name one, ignoring the agent's own configured capabilities entirely. Both are fixed: the dialog now passes the detected models as `CAPABILITIES` (JSON), and the agent runtime falls back to its own `capabilities.models[0]` instead of a hardcoded tag.
  3. **Silent spawn failures.** `spawn_local_agent` used to return success the instant the OS accepted the process, even if it crashed 50 ms later (bad env, AV-quarantined binary, missing DLL) — the dialog would then just say "should appear online in a few seconds" and go quiet forever. It now (a) watches the freshly-spawned process for ~800 ms and returns a synchronous error with the captured stderr tail if it dies immediately, (b) emits an `agent-sidecar-exited` Tauri event on any later crash, and (c) the dialog actively waits (up to 20 s) for the new agent's fleet status to leave `offline`, reporting a concrete crash reason or an honest "hasn't come online yet" timeout instead of a blind success message.
- **A real Windows test run of the above surfaced a fourth, more fundamental bug: Ollama detection reported "not reachable" on a machine where Ollama was demonstrably running with multiple models** (`ollama list` showed them, and legacy `Gruper.html` served via `python -m http.server` could reach the same Ollama instance fine). Root cause, confirmed against Tauri/Chromium's own documented behavior, not guessed: the dialog's Ollama probe was a plain frontend `fetch("http://localhost:11434/api/tags")`, and Chromium/WebView2 (which powers the Tauri webview on Windows) enforces **Private Network Access (PNA)** — any request from the app's own origin into a private/loopback address space requires the target to answer a CORS preflight with `Access-Control-Allow-Private-Network: true`, which Ollama's server never sends, so the request is silently blocked with a generic network error that looks identical to "Ollama isn't running." `Gruper.html` never hit this because a page served by `python -m http.server` is itself already `localhost`-hosted, so no such preflight is required — the exact same reason this bug could never have been caught by this project's own dev-server-served frontend, only by testing the real packaged app. **Fix:** the actual HTTP call moved out of the webview entirely into a new `detect_ollama_models` Tauri command (`console/src-tauri/src/lib.rs`) that talks a raw `tokio::net::TcpStream` — not a browser page, so none of CORS/PNA/mixed-content applies. It distinguishes "couldn't connect" from "connected but got an unexpected response" from "connected, JSON parsed, zero models," sends the request as HTTP/1.0 (matching `check_health`'s existing convention) so a well-behaved server doesn't switch to chunked transfer encoding, and includes a defensive chunked-decoder fallback anyway. `AddAgentDialog.svelte` calls this command when running under Tauri and only falls back to a plain `fetch()` for the non-Tauri browser-dev-tab case (a Vite dev server is itself `localhost`-hosted, so PNA doesn't apply there either — consistent with why `Gruper.html` worked). Covered by 9 new Rust tests in `lib.rs` (`ollama_probe_tests`), including an end-to-end test against a real loopback `TcpListener` standing in for Ollama, a not-listening-port case, and a chunked-transfer-encoding case — the latter caught a real off-by-one in the test's own hand-computed chunk size the first time it was written, which is exactly the kind of mistake that motivated writing an actual runtime test instead of trusting the logic by inspection.
- **`agent-runtime/main.py`**: while wiring this up, found and fixed a real Windows-breaking bug directly in the code path this feature spawns — `loop.add_signal_handler(SIGINT/SIGTERM, ...)` is Unix-only and raises `NotImplementedError` unconditionally on Windows' `ProactorEventLoop` (required there for subprocess support), which would have crashed every Windows-spawned agent on startup. Now caught and logged as a warning instead of propagating. Also added the same ancestor-walk orphan-detection watchdog `orchestrator/packaging/entry.py` already had (`GRUPER_EXIT_WITH_PARENT`, now set by `spawn_local_agent`), so a force-killed Console doesn't leave agent processes running forever — `psutil` added to `agent-runtime/requirements.txt`.
- **Standalone `gruper-agent.exe` is no longer developer-only.** Running it directly (double-click, or from a shell) without `AGENT_ID`/`JWT_TOKEN` set used to print a `curl -X POST .../v1/agents` one-liner aimed at a developer manually driving the REST API, then exit — on Windows, the console window closes before anyone can read it. It now prints a plain-language explanation that this program is meant to be started by the Console's "+ Add Local Agent" button, points there first, and only then gives the `.env`-based manual path for a deliberate headless run — and pauses on an interactive terminal so the message is actually visible before the window closes.
- **Verified end-to-end on Linux** (not just code-reviewed): stood up a real orchestrator, registered a real agent via the same REST calls the dialog makes, ran `agent-runtime/main.py` against it with `GRUPER_EXIT_WITH_PARENT=1` and a `CAPABILITIES` env var carrying a real detected model, confirmed it registered over the WebSocket, the orchestrator's `GET /v1/agents` reported it `idle`, and a submitted task with no `model_preferences.name` resolved to the configured model rather than the old hardcoded default. Separately verified the orphan watchdog: spawned the agent as a child of a throwaway parent process, `SIGKILL`'d the parent, confirmed the agent process exited on its own within one poll interval. `cargo check`, `cargo test` (9/9 green, including the new `ollama_probe_tests`), and `svelte-check` all pass clean.
- **⚠️ Important: "verified end-to-end on Linux" is explicitly NOT the same claim as "will work on Windows."** The PNA bug above is the concrete proof — it passed every Linux check performed in the prior pass (code review, `cargo check`, manual REST/WebSocket verification) and still failed the moment a real user ran it on real Windows hardware, because the failure mode is specific to Chromium/WebView2's network-layer policy, which nothing on Linux exercises the same way. Treat every "Linux-validated" claim elsewhere in this document with that same caveat until Windows hardware validation actually happens.
- **Scope, deliberately:** single machine, same owner as the Console — matches the primary desktop persona this roadmap targets. Remote/cross-machine agent registration is untouched by this work and remains manual (register via `curl`, run `agent-runtime` yourself with the right env vars — see `orchestrator/README.md`'s Auth Flow section).
- **⚠️ Honest caveats:**
  - **Now actually run on Windows once, and it was broken** — the Ollama-detection PNA bug above was found by a real user on real Windows hardware, not in this development environment (no Windows hardware is available here either). The fix has been unit/integration-tested against a real loopback socket standing in for Ollama, and matches Tauri/Chromium's documented PNA behavior, but has **not yet been re-verified on physical Windows hardware** — that re-verification (confirm the dialog now detects real installed models and a resulting agent runs a real task) is the single most important remaining step for this work packet, more so than any other open item below. The rest of the sidecar-spawn code path (grace-period crash detection) and the `agent-runtime` fixes (signal-handler fix, standalone-exe pause) remain unverified on physical Windows hardware in the same way they were before this pass.
  - **No "install Ollama for me" flow.** The dialog now blocks a useless registration and links to ollama.ai, but doesn't walk the user through installing it.
  - **No "remove/stop agent" UI yet.** An agent can be added through the Console; stopping one still means killing the process or closing the Console (which kills all locally-spawned agents together). Good enough for "add my first agent," not yet a full lifecycle UI.
  - **No dedicated automated test** for `spawn_local_agent` or `AddAgentDialog` — verification here was manual (see above), not a new entry in `orchestrator/tests/` or a Playwright/component test for the Svelte side.
- **Files:** `console/src-tauri/src/lib.rs` (`spawn_local_agent`, `SidecarState` generalized), `console/src-tauri/tauri.conf.json` (`bundle.externalBin` +`binaries/gruper-agent`), `console/src/lib/components/AddAgentDialog.svelte` (new), `console/src/routes/+page.svelte` (+"Add" button), `console/src/lib/stores/auth.ts` (`generateRandomPubkey` factored out), `console/src/lib/stores/fleet.ts` (+`add()`), `console/src/lib/api/client.ts` (+`registerAgent`), `console/src/lib/types.ts` (+`AgentRegistrationRequest`), `agent-runtime/main.py` (signal-handler guard + orphan watchdog), `agent-runtime/requirements.txt` (+`psutil`), `scripts/build-desktop.sh`/`.ps1` (stage both sidecars).
- **⚠️ CI regression found and fixed in a follow-up pass:** adding `binaries/gruper-agent` to `tauri.conf.json`'s `externalBin` (above) without also updating `.github/workflows/build-windows.yml`'s staging step broke the Windows build — it still only copied the orchestrator executable into `console/src-tauri/binaries/`, so Tauri's bundler hard-failed with `resource path "binaries/gruper-agent-x86_64-pc-windows-msvc.exe" doesn't exist`. This is exactly the kind of drift a purely-Linux verification pass cannot catch, since `cargo check`/`cargo build` on Linux only need the Linux-triple sidecar staged, not the Windows one CI needs — the gap was invisible locally and only surfaced as a real Windows CI failure. Fixed by staging both binaries together in one step (`cp dist/gruper-orchestrator.exe ...` and `cp dist/gruper-agent.exe ...` side by side, so they can't drift apart again silently) plus a new "Verify sidecar binaries are staged" preflight step that checks every `externalBin` entry in `tauri.conf.json` against what's actually on disk and fails with a clear message before the Tauri build even starts, rather than surfacing as a cryptic bundler error. Verified locally: reproduced the missing-file check logic against the real `tauri.conf.json` (correctly reports both entries `MISSING` with nothing staged, both `OK` once staged), and re-ran `scripts/build-desktop.sh` + `cargo check` end to end with real PyInstaller-built binaries for the host (Linux) triple. **Still open:** this exact fix has not been watched succeed on an actual `windows-latest` CI run yet — the failure was reported after the prior pass, not reproduced on Windows hardware directly.
- **Exit gate:** met for the sidecar path on Linux, against the actual production build. Fresh Console launch → local orchestrator auto-starts → Console auto-connects with zero manual steps, screenshot-verified against both a dev-server run and the real `tauri build` binary. Connecting to a remote/server orchestrator still works via manual URL entry (untouched code path). **Not yet met:** the same proof on a real Windows machine.

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
| ~~Orchestrator is PostgreSQL-only; no SQLite/embedded path~~ | ✅ **Resolved (WP-30)** | SQLite is now the default backend (`orchestrator/db/`); PostgreSQL is opt-in via `DATABASE_URL`. Verified: orchestrator starts and passes the full suite on both, with no Docker/Postgres required for the SQLite path. |
| ~~Orchestrator has no CI~~ | ✅ **Resolved (WP-30)** | `.github/workflows/orchestrator-tests.yml` now runs the pytest suite as two separate jobs — SQLite (no services) and PostgreSQL (service container). |
| **`asyncpg` is a hard dependency even for pure-SQLite runs** | **Low-Medium** (found during WP-30, still open after WP-31) | `orchestrator/db/connect.py` imports `PostgresDatabase` unconditionally, which imports `asyncpg` at module load — so both `pip install` for a desktop-only setup *and* the WP-31 PyInstaller executable still pull in / bundle the Postgres driver. Not a functional blocker (SQLite works fine regardless), but adds avoidable size/build time and works against "minimal extra dependencies." Still open: lazy-import `asyncpg` only when a `postgresql://` URL is actually used, or split `requirements.txt` into desktop/server variants. |
| ~~Console/agent do not auto-start an orchestrator~~ | ✅ **Resolved (WP-32), Linux-validated** | The Tauri Console now spawns, health-checks, and auto-connects to a local orchestrator sidecar with zero manual steps — verified against a real production `tauri build` binary via screenshot. Not yet verified on Windows. |
| ~~No packaging/installer for the orchestrator or agent~~ | ✅ **Resolved (WP-31), Linux-validated** | PyInstaller produces self-contained orchestrator + agent executables (`orchestrator/packaging/`, `agent-runtime/packaging/`); `scripts/build-desktop.sh`/`.ps1` build both with one command. `scripts/validate-desktop-packaging.py` proves the packaged binaries relay a task end to end. Windows CI job is green (18 runs) but the resulting installers haven't been run on real hardware yet — see WP-31's section. |
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

*Last updated: 2026-07-01 (Two execution passes today. First pass hardened the "Add Local Agent" flow end to end: Ollama detection became a real state machine (unreachable / no models / ready / error) gating the "Add Agent" button so it no longer silently registers a placeholder-model agent; fixed a root-cause bug where the detected model never reached the spawned agent process (`spawn_local_agent` didn't set `CAPABILITIES`, and `agent-runtime/ws_client.py` hardcoded `"llama3.1:8b"` regardless); `spawn_local_agent` gained a crash-detection grace period and an exit event instead of reporting false success; `agent-runtime/main.py`'s standalone-run error was replaced with plain-language guidance toward the Console; fleet's empty state now explains the Ollama prerequisite. **Second pass, triggered by an actual Windows hardware test report:** that test found the "Add Local Agent" dialog still reported "Ollama is not running" against a machine where Ollama demonstrably was running with multiple models. Root cause tracked down and confirmed against Tauri/Chromium's documented behavior: the dialog's Ollama probe was a plain frontend `fetch()`, and Chromium/WebView2's Private Network Access policy silently blocks exactly that kind of request (webview origin → loopback service) unless the target sends an `Access-Control-Allow-Private-Network` header, which Ollama's server never does — indistinguishable from "not running" at the JS layer, and impossible to catch by testing only on Linux or against a plain browser tab (both of which are themselves `localhost`-hosted and never trigger the policy). Fixed by moving the actual HTTP call out of the webview into a new `detect_ollama_models` Rust command that talks a raw socket directly, with 9 new Rust tests (including a real loopback-socket end-to-end test) backing it. Real Windows hardware re-verification of this specific fix is now the single most important open item — everything else that says "Linux-validated" in this document carries the same "not proven on Windows" caveat this bug just demonstrated concretely.)*
*Companion document: `GruperDistributedSpec.md` — architecture diagrams, data models, wire schemas, security threat table, and open questions (OQ-1…OQ-5). Pending a desktop-first alignment pass.*
*Gruper core baseline: `v0.4.5` (`Gruper.html`) — this roadmap builds on core, not over it.*
