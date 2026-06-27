# Gruper Distributed — Engineering Roadmap

**Status as of 2026-06-27:** `gd-0.0` — **Design stage; no code shipped.**
· Spec `0.2 — Design Draft` committed · All milestones planned · OQ-1 through OQ-5 must be resolved before `gd-0.1` closes · **v1.0 is a future finish line gated on SC-1…SC-7; it has not been reached.**

**Stack:** Agent Runtime — Python + FastAPI; Rust for security-critical paths · Manager Console — Tauri v2 + Svelte 5 + Tailwind · Orchestrator — FastAPI + PostgreSQL (Docker Compose) · Transport — WSS over TLS · Inference — Ollama local-first · Containers — Docker multi-arch (CPU + CUDA)

**Gruper core baseline: `v0.4.5` (`Gruper.html`).** Gruper Distributed is a **companion extension, not a replacement.** Core stays client-only, single-file, and standalone. Distributed reuses:
- Ollama integration: same `/api/generate` / `/api/chat` endpoint shape and parameter conventions
- Circuit-breaker / retry: 2 s / 4 s / 8 s / 16 s exponential backoff applied to all persistent connections
- Chart.js analytics: same visual language, tooltip format, and CSV/JSON export — embedded in the console
- Conversation engine and message rendering: embedded in the console's Agent Detail view
- 12 agent role templates: extended with `jurisdiction` and `availability` metadata
- CDN SRI-hash validation discipline: applied to Docker image layer integrity in CI

**Cross-network principle:** Every agent makes an *outbound* authenticated persistent WSS connection to the orchestrator. Nothing connects inward to an agent. NAT traversal requires no port forwarding on any agent host.

**Companion document:** `GruperDistributedSpec.md` — architecture diagrams, data models, wire schemas, security threat table, and open questions (OQ-1…OQ-5).

---

## Phase Summary

| Phase | Milestone | Goal | Status |
|-------|-----------|------|--------|
| 0 — Foundations | `gd-0.1` | Wire contracts, schemas, skeleton orchestrator | 🔲 Not started |
| 1 — Walking Skeleton | `gd-0.2` | Single-owner end-to-end relay over the public internet | 🔲 Not started |
| 2 — Cross-Network Sharing | `gd-0.3` | Cross-owner dispatch with scoped tokens; headline milestone | 🔲 Not started |
| 3 — Cloud Burst | `gd-0.4` | AWS spot fleet with hard cost controls | 🔲 Not started |
| 4 — Security Hardening | `gd-0.5` | Sandbox parity, E2E encryption, formal security review | 🔲 Not started |
| 5 — Beta & Polish | `gd-0.6–0.9` | Capability dispatch, crew builder, n8n integration, closed beta | 🔲 Not started |
| First Stable Release | `v1.0` | SC-1…SC-7 met for real users; roadmap rewritten at that point | 🔲 Future finish line |
| Post-v1 | `gd-1.x` | Federation, P2P, mobile, ecosystem | 🔲 Deferred |

---

## Phase 0 — Foundations — 🔲 `gd-0.1`

### WP-01 — Wire Contracts & Schema Freeze — 🔲 `gd-0.1`

- **Goal:** Lock every interface downstream WPs build against.
- **Steps:**
  1. Define the **agent ↔ orchestrator WSS message schema**: `register`, `heartbeat`, `task-push`, `progress-stream`, `result`, `revoke` — typed, versioned, documented.
  2. Define the **console ↔ orchestrator REST/WS API** (OpenAPI 3.1): task submit, agent query, token mint/revoke, event stream.
  3. Map **Gruper core's per-agent config schema** (model, temperature, top-p, top-k, repeat penalty, max tokens, context length, role template) to the distributed task input schema.
  4. Define all data models in versioned JSON Schema or Pydantic: `User`, `Agent`, `Task`, `ShareToken`, `Event`.
  5. Resolve **OQ-1** (agent-loop framework) to freeze the task/state schema.
  6. Resolve **OQ-2** (Pattern A sign-off) to confirm the multi-tenant orchestrator model.
  7. Publish the `gd-0.1` schema package: OpenAPI YAML, WSS schema JSON, ER diagram.
- **Dependencies:** OQ-1 and OQ-2 must be resolved before this WP closes.
- **Exit gate:** Schemas agreed and published. An independent implementer can build against them without reopening architecture decisions.

---

### WP-02 — Skeleton Orchestrator — 🔲 `gd-0.1`

- **Goal:** Runnable Docker Compose stack (PostgreSQL + FastAPI) accepting agent registration and heartbeat; no task dispatch.
- **Steps:**
  1. `docker-compose.yml`: PostgreSQL 16 + FastAPI; all config via environment variables.
  2. Migrations 001–004: `users`, `agents`, `tasks`, `events` tables; `SKIP LOCKED` queue pattern on `tasks`.
  3. Endpoints: `POST /register` (JWT issuance), `WS /agent/ws` (heartbeat only), `GET /agents`, `GET /health`.
  4. JWT issuance and verification middleware; ed25519 keypair support stubbed.
  5. `pytest` smoke tests: register → JWT → heartbeat → verify in `GET /agents`.
- **Files:** `orchestrator/main.py`, `orchestrator/models/`, `orchestrator/migrations/001–004.sql`, `docker-compose.yml`, `tests/test_register.py`
- **Exit gate:** `docker compose up` on a clean machine; mock agent registers, heartbeats, appears in `GET /agents`; smoke tests pass in CI.

---

## Phase 1 — Walking Skeleton — 🔲 `gd-0.2`

### WP-03 — Agent Runtime — Desktop MVP — 🔲 `gd-0.2`

- **Goal:** Desktop agent service that dials out to the orchestrator, executes tasks against local Ollama using **Gruper core's API shape and parameter conventions**, and streams results back.
- **Steps:**
  1. Persistent outbound WSS client with **exponential backoff (2 s / 4 s / 8 s / 16 s) — Gruper core's retry discipline** applied to the orchestrator connection.
  2. Registration handshake: send capability JSON on connect; receive and store JWT.
  3. Task execution: receive task JSON → validate authority → call local Ollama (`/api/generate` or `/api/chat`, **Gruper core parameter conventions**) → stream progress and result over WSS.
  4. Offline queue: SQLite per-agent; drain on reconnect with exponential backoff.
  5. **Circuit-breaker:** 3 consecutive failures → mark degraded, signal orchestrator to pause routing — mirrors **Gruper core's agent auto-disable pattern**.
  6. Heartbeat loop (30 s); graceful shutdown with in-flight checkpoint.
  7. Systemd unit (Linux); launchd plist stub (macOS).
- **Files:** `agent-runtime/main.py`, `agent-runtime/ollama_client.py`, `agent-runtime/queue.py`, `agent-runtime/agent.db`, `agent-runtime/gruper-agent.service`
- **Exit gate:** Agent behind consumer NAT connects to VPS-hosted orchestrator; receives pushed task; calls local Ollama; streams result back over the public internet relay path.

---

### WP-04 — Orchestrator — Task Dispatch — 🔲 `gd-0.2`

- **Goal:** Orchestrator dispatches an explicit-assignment task to a registered agent and relays the result stream to the submitter.
- **Steps:**
  1. `POST /tasks`: submitter auth, `assigned_agent_id`, payload, data class, priority, deadline.
  2. Dispatcher: `SKIP LOCKED` enqueue; push to agent's WSS channel.
  3. Result relay: forward progress events and final result to submitter's open connection.
  4. Task lifecycle: `pending → dispatched → running → complete | failed | timed_out`.
  5. Retry: requeue on agent disconnect; dead-letter after configurable retry count.
  6. Append to `events` table on every state transition.
  7. Integration tests: submit → dispatch → result relay → dead-letter on disconnect.
- **Exit gate:** End-to-end task completes over the internet relay path. Integration tests pass in CI.

---

### WP-05 — Manager Console — Minimal Scaffold — 🔲 `gd-0.2`

- **Goal:** Tauri v2 + Svelte 5 console scaffold with fleet view stub, task composer, and result view — embedding **Gruper core's conversation UI and Chart.js analytics** directly.
- **Steps:**
  1. Tauri v2 + Svelte 5 + Tailwind scaffold; locked-down CSP in `tauri.conf.json` from the first commit.
  2. WSS client to orchestrator; auth token in Tauri secure store.
  3. **Fleet view stub:** single agent card — name, status badge (idle / busy / offline), last-seen, model list.
  4. **Task composer:** task input + model selector; mirrors **Gruper core's task-input UX conventions**.
  5. **Result view:** embed **Gruper core's conversation message rendering** (round-based display, markdown, glassmorphism styling).
  6. **Per-agent analytics tab:** embed **Gruper core's Chart.js response-time line chart** scoped to that agent; same visual language and CSV/JSON export as core.
  7. CI: `tauri build` smoke test; Playwright click-through on task form.
- **Files:** `console/src-tauri/tauri.conf.json`, `console/src/lib/components/AgentCard.svelte`, `console/src/lib/components/TaskComposer.svelte`, `console/src/lib/components/ResultView.svelte`, `console/src/lib/components/AgentAnalytics.svelte`
- **Exit gate:** Console builds on Linux; submits a task; displays result in the embedded Gruper core result view.

---

### WP-06 — End-to-End Relay Validation — 🔲 `gd-0.2` exit gate

- **Goal:** Prove the outbound-relay model stable over the public internet before sharing complexity is added.
- **Steps:**
  1. Orchestrator on VPS (Docker Compose); agent on workstation behind consumer NAT — no port forwarding.
  2. Submit 20 tasks; measure dispatch overhead (target < 10 s excluding model execution; SC-2 baseline).
  3. Simulate agent disconnect mid-task; verify requeue and completion on reconnect.
  4. Simulate orchestrator restart; verify agent reconnects with exponential backoff and drains queue without data loss.
- **Exit gate:** SC-5 met for single-owner case. SC-2 baseline documented. Relay model proven before WP-07 builds on it.

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
  1. **Fleet Overview:** grid of all visible agents — status badges (idle / busy / offline), location tags, ownership indicator ("shared / limited"), last-seen, model count.
  2. **Sharing Panel:** mint form (agents, scopes, quotas, time windows, data class, expiry); active grant list; one-click revoke with confirmation.
  3. **Token import UX:** paste string or scan QR → shared agent appears in fleet with scope summary and "shared / limited" badge; no command-line.
  4. **Agent Detail:** for shared agents, only permitted actions rendered — non-permitted actions absent from the UI.
  5. **Owner audit trail:** per-agent event log (grantee, task type, outcome) visible to owner at all times.
  6. Extend **Gruper core's Chart.js analytics** with per-grantee task-volume and quota-usage charts; same visual language and export format as core.
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

## Phase 3 — Cloud Burst & Cost Control — 🔲 `gd-0.4`

### WP-12 — Container Agent Image — 🔲 `gd-0.4`

- **Goal:** Multi-arch Docker image that turns any Linux host into a registered agent node with a single `docker run`.
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
  5. Cost and utilization dashboard: per-pool spend vs cap, queue depth trend — extends **Gruper core's Chart.js analytics** with cloud cost dimension; same CSV/JSON export format.
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
  6. Integration test: orchestrator DB at rest — payload column contains ciphertext, not plaintext.
  7. Simulated compromised-orchestrator test: full DB read access; payload content remains confidential.
- **Exit gate:** SC-4 met for payload confidentiality. Compromised-orchestrator simulation passes and documented. E2E encryption active for all cross-owner dispatches.

---

### WP-17 — Hash-Chained Audit Log — 🔲 `gd-0.5`

- **Goal:** Audit event stream is append-only and tamper-evident — verifiable compliance record for regulated deployments and run attribution.
- **Steps:**
  1. `events` table: add `prev_hash`, `entry_hash`; `entry_hash = SHA-256(ts ‖ actor_id ‖ action ‖ subject_id ‖ payload_hash ‖ prev_hash)`.
  2. Every state transition (task create, dispatch, progress, complete, fail, revoke, token mint/revoke, delegation) appends an immutable hash-chained event.
  3. `GET /audit`: paginated, filterable by actor / agent / time range / action; returns events with hashes for client-side chain verification.
  4. Console audit view: per-agent and per-task event logs with chain-verification indicator; JSON export.
  5. Standalone chain-verification CLI: downloads full chain, verifies hash continuity.
  6. Redaction: sensitive payload content appears only as `payload_hash`; no plaintext in event record.
- **Exit gate:** Chain verifies end-to-end for 500-event dataset. Tampering any field causes verification failure at that event and all subsequent. Compliance JSON export tested.

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
- **Exit gate:** No critical or high findings open. Equivalence report accepted. Token penetration test documented with all attacks mitigated. Cross-owner sharing unlocked for beta.

---

## Phase 5 — Console Polish, Crews & Beta — 🔲 `gd-0.6–0.9`

### WP-19 — Capability-Based & Policy-Based Auto-Dispatch — 🔲 `gd-0.6`

- **Goal:** Tasks route automatically to best-fit agents; data-class and jurisdiction constraints enforced at dispatch time.
- **Steps:**
  1. Capability-match query: `SELECT` agents satisfying `hardware`, `models`, `tools`, `roles`, `jurisdiction`, `availability` from task requirements.
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
  3. Live log streaming: real-time task logs from any connected agent, searchable — mirrors **Gruper core's debug log search and auto-scroll**.
  4. Chart.js line/bar/pie with same color scheme, tooltip format, and CSV/JSON export as **Gruper core's analytics dashboard** — recognizable to core users immediately.
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

- **Goal:** 2–3 trusted cross-location beta collaborators use the system for real work; all SC-1…SC-7 hold; complete documentation published.
- **Steps:**
  1. **Beta participants:** 2–3 collaborators across distinct use cases (≥ 1 regulated environment); confirmed before `gd-0.6` begins.
  2. **Install guide:** all three agent paths (desktop Linux, desktop Windows, Docker); QR onboarding; < 5 min for a non-technical user.
  3. **Sharing setup guide:** mint token, configure scope, share, monitor, revoke — no command-line assumed.
  4. **Ops runbook:** orchestrator deploy, backup/restore, TLS renewal, log rotation, cost-cap monitoring.
  5. **Security posture summary (1-page):** what the owner can/cannot see, data-class routing, how to revoke.
  6. **SC-1…SC-7 verification checklist:** run against beta environment; document evidence per criterion.
  7. No critical bugs open at handoff.
- **Exit gate:** All SC-1…SC-7 met for real beta users. Documentation reviewed by ≥ 1 beta participant. No critical bugs open. Ready to assess v1.0.

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

---

## Post-v1 (`gd-1.x`) — Deferred

Out of scope for the pre-1.0 track. Not scheduled until v1.0 is shipped and stable.

| WP | Item | Notes |
|----|------|-------|
| WP-24 | **Pattern B — Federated per-user orchestrators** | Each user self-hosts; sharing authorizes cross-orchestrator dispatch; agent multi-homing. Token/data model (WP-08) must not preclude this. |
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
| OQ-1 through OQ-5 unresolved | **Blocking** | Must be resolved before WP-01 closes; all downstream WPs depend on them. See companion spec §12.2. |
| Desktop sandboxing (Linux only until WP-15) | **High** | Windows and macOS per-task sandbox absent until `gd-0.5`. Cross-owner sharing on Windows/macOS blocked until WP-15 and WP-18 close. |
| `events` table lacks hash chain until WP-17 | **Medium** | Event append active from WP-02; tamper-evidence absent until `gd-0.5`. Compliance deployments must not go live before WP-17 closes. |
| Python agent runtime (memory-unsafe) | **Medium** | Acceptable for prototyping. Rust port of sandbox and comms planned as load and security review demand it. |
| Single-orchestrator SPOF | **Medium** | Failover interface in data model from WP-01; full federation deferred to `gd-1.x`. Agent offline queue (WP-03) mitigates partial impact. |
| No full integration test suite | **Medium** | Per-WP smoke tests built incrementally. Full suite and Playwright E2E against mock Ollama deferred to `gd-0.6+`. |

---

*Last updated: 2026-06-27*
*Companion document: `GruperDistributedSpec.md` — architecture diagrams, data models, wire schemas, security threat table, and open questions (OQ-1…OQ-5).*
*Gruper core baseline: `v0.4.5` (`Gruper.html`) — this roadmap builds on core, not over it.*
