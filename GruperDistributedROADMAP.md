# Gruper Distributed — Engineering Roadmap

**Status as of 2026-06-27:** `gd-0.0` — **Design stage. No code has shipped.**
· Spec `0.2 — Design Draft` committed · All milestones below are planned · Open questions OQ-1 through OQ-5 must be resolved before `gd-0.1` can close (see spec §12.2) · **v1.0 is a future finish line gated on SC-1 through SC-7; it has not been reached.**

**Stack:** Agent Runtime — Python (FastAPI); Rust for security-critical paths · Manager Console — Tauri v2 + Svelte 5 + Tailwind (consistent with SteloPTC) · Orchestrator — FastAPI + PostgreSQL (Docker Compose) · Transport — WSS (WebSocket over TLS) · Inference — Ollama (local-first; same endpoint and parameter conventions as Gruper core v0.4.5) · Containerization — Docker multi-arch (CPU + CUDA)

**Gruper core baseline: `v0.4.5` (`Gruper.html`).** Gruper Distributed is a **companion extension, not a replacement.** Core stays client-only and standalone. Distributed reuses core's Ollama API integration shape (`/api/generate` / `/api/chat`), conversation engine, Chart.js analytics (same visual language and CSV/JSON export), circuit-breaker retry discipline (2 s / 4 s / 8 s / 16 s), 12 agent role templates, and CDN SRI-hash validation discipline (applied here to container layer integrity). The Manager Console embeds Gruper core's conversation UI and analytics dashboard directly — not reimplemented.

**Cross-network principle (read this first):** Every agent makes an *outbound* authenticated persistent connection to the orchestrator. Nothing ever connects *inward* to an agent. This solves NAT traversal, makes consumer desktops and cloud instances indistinguishable to the orchestrator, and is the architectural foundation every WP builds on.

---

## Phase Summary

| Phase | Milestone | Goal | Status |
|-------|-----------|------|--------|
| 0 — Foundations | `gd-0.1` | Wire contracts, schemas, skeleton orchestrator | 🔲 Not started |
| 1 — Walking Skeleton | `gd-0.2` | Single-owner end-to-end relay over the public internet | 🔲 Not started |
| 2 — Cross-Network Sharing | `gd-0.3` | Cross-owner dispatch with scoped tokens; headline milestone | 🔲 Not started |
| 3 — Cloud Burst | `gd-0.4` | AWS spot fleet with hard cost controls | 🔲 Not started |
| 4 — Security Hardening | `gd-0.5` | Sandbox parity, E2E encryption, formal security review | 🔲 Not started |
| 5 — Beta Polish | `gd-0.6–0.9` | Capability dispatch, crew builder, n8n integration, closed beta | 🔲 Not started |
| v1.0 — First Stable Release | `v1.0` | All SC-1…SC-7 met for real users; roadmap rewritten at that point | 🔲 Future finish line |
| Post-v1 | `gd-1.x` | Federation, P2P, mobile, ecosystem | 🔲 Deferred |

---

## Phase 0 — Foundations — 🔲 `gd-0.1`

---

### WP-01 — Wire Contracts & Schema Freeze — 🔲 `gd-0.1`

- **Goal:** Lock every interface that downstream work packages build against, so implementation or contractor handoff can proceed on a stable foundation with no re-opening of architecture decisions.
- **Steps:**
  1. Finalize the **agent ↔ orchestrator WSS message schema**: `register`, `heartbeat`, `task-push`, `progress-stream`, `result`, `revoke` — typed, versioned, documented.
  2. Finalize the **console ↔ orchestrator REST/WS API**: OpenAPI 3.1 spec for task submit, agent query, token mint/revoke, and event stream endpoints.
  3. Map **Gruper core's per-agent configuration schema** (model, temperature, top-p, top-k, repeat penalty, max tokens, context length, role template) to the distributed task input schema — this is the formal bridge between core's local parameter model and the remote execution contract, and must be agreed before any task dispatch code is written.
  4. Define all data models (spec §9) in versioned JSON Schema or Pydantic: `User`, `Agent`, `Task`, `ShareToken`, `Event`.
  5. Resolve **OQ-1** (agent-loop framework — custom ReAct vs LangGraph vs CrewAI) so the task/state schema is frozen.
  6. Resolve **OQ-2** (Pattern A sign-off — shared multi-tenant orchestrator confirmed for the first release) so the multi-tenant data model is finalized.
  7. Produce the `gd-0.1` schema package: spec cross-reference, OpenAPI YAML, WSS schema JSON, ER diagram.
- **Dependencies:** OQ-1 and OQ-2 must be resolved before this WP can close. OQ-3, OQ-4, OQ-5 documented with placeholder decisions acceptable at this stage.
- **Exit gate:** Schemas reviewed and agreed by the implementer(s). An independent contractor can build the orchestrator or agent runtime against these documents without reopening architecture questions.

---

### WP-02 — Skeleton Orchestrator — 🔲 `gd-0.1`

- **Goal:** A runnable Docker Compose stack — PostgreSQL + minimal FastAPI orchestrator — that accepts agent registration and heartbeat. No task dispatch yet.
- **Steps:**
  1. `docker-compose.yml`: PostgreSQL 16 + FastAPI service; all configuration via environment variables; no hardcoded credentials.
  2. Database migrations (001–004): `users`, `agents`, `tasks`, `events` tables with indexes; `SKIP LOCKED` queue pattern on `tasks`.
  3. FastAPI endpoints: `POST /register` (agent registration + JWT issuance), `WS /agent/ws` (heartbeat handling only), `GET /agents` (admin/console list), `GET /health` (load-balancer readiness).
  4. JWT issuance and verification middleware; ed25519 keypair support stubbed (implemented fully in WP-07).
  5. Locked-down CSP from the first commit; no default admin credentials.
  6. `pytest` smoke tests: register a mock agent, receive a JWT, send heartbeats, verify agent appears in `GET /agents`.
- **Files:** `orchestrator/`, `orchestrator/main.py`, `orchestrator/models/`, `orchestrator/migrations/001_initial.sql` through `004_tasks.sql`, `docker-compose.yml`, `tests/test_register.py`
- **Exit gate:** `docker compose up` on a clean machine; a mock agent script can register, heartbeat, and appear in the agent list; all smoke tests pass in CI.

---

## Phase 1 — Walking Skeleton — 🔲 `gd-0.2`

**Goal for this phase:** A single owner's agent receives a task pushed over the outbound-relay WSS path, executes it against local Ollama, and streams the result back to a minimal console. No sharing, no cloud agents. Proves the relay model works over the public internet before any additional complexity is layered on.

---

### WP-03 — Agent Runtime — Desktop MVP — 🔲 `gd-0.2`

- **Goal:** A desktop agent service (Linux; Windows and macOS follow at WP-15) that dials out to the orchestrator, receives tasks, executes them against the local Ollama endpoint using **Gruper core's existing API integration pattern and parameter conventions**, and streams results back.
- **Steps:**
  1. Persistent outbound WSS client with auto-reconnect and **exponential backoff (2 s / 4 s / 8 s / 16 s) mirroring Gruper core's API retry discipline**.
  2. Registration handshake: send capability JSON (spec §4.3 schema) on connect; receive and store JWT.
  3. Task execution loop: receive task JSON → validate dispatching authority → call local Ollama (`/api/generate` or `/api/chat`, same parameter conventions as Gruper core) → stream incremental progress and final result back over WSS.
  4. Per-task offline queue: if the orchestrator is unreachable, queue tasks to local SQLite; drain on reconnect with exponential backoff.
  5. **Circuit-breaker:** after three consecutive task failures, mark runtime degraded and signal the orchestrator to pause routing that task class — mirrors Gruper core's agent auto-disable pattern.
  6. Heartbeat loop (30 s interval); graceful shutdown with in-flight task checkpoint.
  7. Systemd unit file (Linux) for background-service operation; launchd plist stub (macOS, not yet activated).
- **Files:** `agent-runtime/`, `agent-runtime/main.py`, `agent-runtime/ollama_client.py`, `agent-runtime/queue.py`, `agent-runtime/agent.db` (SQLite), `agent-runtime/gruper-agent.service`
- **Exit gate:** Agent running behind a consumer NAT connects to the orchestrator on a VPS; receives a task pushed by the orchestrator; calls local Ollama; streams the result back. All traffic over the public internet relay path — not LAN direct.

---

### WP-04 — Orchestrator — Task Dispatch — 🔲 `gd-0.2`

- **Goal:** The orchestrator dispatches an explicit-assignment task to a registered agent and relays the result stream back to the submitter.
- **Steps:**
  1. `POST /tasks` endpoint: accept task JSON with submitter auth, `assigned_agent_id`, payload, data class, priority, deadline.
  2. Dispatcher: enqueue task with `SKIP LOCKED`; push to the connected agent's WSS channel immediately.
  3. Result relay: forward progress events and final result from agent WSS to the submitter's open connection.
  4. Task status lifecycle: `pending → dispatched → running → complete | failed | timed_out`.
  5. Retry logic: requeue on agent disconnect mid-task; dead-letter after configurable retry count.
  6. Append to `events` table on every state transition (pre-cursor to hash-chained audit log; fully implemented at WP-17).
  7. Integration tests: submit a task, verify dispatch, verify result relay, verify dead-letter on agent disconnect.
- **Exit gate:** End-to-end: console submits task → orchestrator dispatches → agent executes → result relayed. Passing on the internet relay path, not only on LAN.

---

### WP-05 — Manager Console — Minimal Scaffold — 🔲 `gd-0.2`

- **Goal:** A Tauri v2 + Svelte 5 desktop app with a single agent card, a task submission form, and a result view. Establishes the console project scaffold that all later WPs extend.
- **Steps:**
  1. Tauri v2 + Svelte 5 + Tailwind project scaffold (consistent with SteloPTC patterns); `tauri.conf.json` with locked-down CSP from the first commit; no default credentials.
  2. WSS client to the orchestrator; auth token stored in Tauri's secure credential store.
  3. **Fleet view stub:** single agent card — name, status badge (idle / busy / offline), last-seen timestamp, available model list.
  4. **Task composer:** text input + model selector + submit button; UX patterns from Gruper core's task-input conventions.
  5. **Result view:** embed **Gruper core's conversation message rendering** (the round-based message display, markdown rendering, and glassmorphism styling) directly — not reimplemented from scratch.
  6. **Per-agent analytics tab:** embed **Gruper core's Chart.js response-time line chart** scoped to that agent's task history; same visual language and CSV/JSON export format as core.
  7. CI: `tauri build` smoke test on Linux; basic Playwright click-through on the task submission form.
- **Files:** `console/`, `console/src/`, `console/src-tauri/`, `console/src/lib/components/AgentCard.svelte`, `console/src/lib/components/TaskComposer.svelte`, `console/src/lib/components/ResultView.svelte`, `console/src/lib/components/AgentAnalytics.svelte`
- **Exit gate:** Console builds and runs on Linux; submits a task to the WP-04 orchestrator; displays the result using the embedded Gruper core result view.

---

### WP-06 — End-to-End Relay Validation — 🔲 `gd-0.2` exit gate

- **Goal:** Prove the outbound-relay model works reliably over the public internet under realistic conditions before any sharing complexity is added on top of it.
- **Steps:**
  1. Deploy orchestrator to a VPS (Docker Compose); agent running on a workstation behind a consumer NAT router — no port forwarding configured.
  2. Submit 20 tasks from the console; verify all complete; measure round-trip dispatch overhead (target: < 10 s excluding model execution per SC-2).
  3. Simulate agent disconnect mid-task; verify requeue and eventual completion on reconnect.
  4. Simulate orchestrator restart; verify agent reconnects with exponential backoff and resumes queue drain without data loss.
  5. Document baseline SC-2 latency numbers for future comparison.
- **Exit gate:** SC-5 met for the single-owner case (no inbound ports required on any agent). SC-2 baseline documented. The relay model is proven stable before cross-owner sharing is built on top of it.

---

## Phase 2 — Cross-Network Sharing — 🔲 `gd-0.3`

**Goal for this phase:** A cross-location collaborator can receive a scoped share token, install the agent runtime, and have tasks dispatched to their machine by the token issuer — over the public internet, without any inbound port configuration, with instant revocation available to the agent owner at all times. This is the headline milestone.

---

### WP-07 — Multi-Tenant Orchestrator & Identity — 🔲 `gd-0.3`

- **Goal:** The orchestrator supports multiple owners, each with a cryptographically anchored identity and strict namespace isolation — no user can see or task another user's agents without an explicit grant.
- **Steps:**
  1. **User / identity model:** `users` table with `id`, `pubkey (ed25519)`, `display_name`, `org_id (optional)`, `created_at`; ed25519 keypair generated in the console on first launch.
  2. Agent registration upgraded: `owner_id` bound cryptographically (owner signs the registration payload; orchestrator records the corresponding public key as the identity anchor).
  3. AuthN middleware: ed25519-signed auth tokens verified on every API call and WS connection.
  4. Namespace isolation: `GET /agents` returns only agents visible to the authenticated caller (owned + those covered by a valid grant); no cross-namespace bleed.
  5. Database migration to multi-tenant schema; single-owner data from `gd-0.2` migrated cleanly.
  6. Integration tests: two independent users register agents; each sees only their own agents; no bleed between namespaces.
- **Exit gate:** Two users coexist on the same orchestrator instance with zero namespace bleed. Cryptographic identity anchored from this point forward; no anonymous registration accepted.

---

### WP-08 — Share Token System — 🔲 `gd-0.3`

- **Goal:** An agent owner can mint a cryptographically signed, granularly scoped, instantly revocable share token and hand it to any authorized grantee — who can then dispatch tasks to the covered agent(s) within the token's constraints.
- **Steps:**
  1. `ShareToken` data model: `agent_id[]`, `grantee_user_id`, `scopes[]`, `quotas (JSON)`, `conditions (JSON: time_windows, allowed_data_classes, jurisdiction_require)`, `expires_at`, `revoked_at`, `created_by`.
  2. `POST /tokens` — mint token; sign with owner's private key; return as a compact portable string (JWT or biscuit-style) encoding the full grant.
  3. `DELETE /tokens/{id}` — revoke: set `revoked_at`; immediately stop dispatching to covered agents; send abort signal to any in-flight task.
  4. Token verification middleware: validated on **every dispatch** — scope check, quota check, time-window check, data-class check, revocation check. No exceptions.
  5. Per-grantee quota enforcement: max concurrent tasks, max RAM per task, max wall time — enforced at enqueue time, not after the fact.
  6. Audit event appended for every token mint, import, dispatch under a token, and revoke.
  7. Tests: mint → import → dispatch → verify scope enforcement → revoke → verify next dispatch rejected immediately.
- **Exit gate:** Revocation takes effect within one dispatch cycle — no task dispatched after `revoked_at` timestamp. Scope violations (task type, data class, time window) rejected by the orchestrator before reaching the agent.

---

### WP-09 — Agent Runtime — Cross-Owner Dispatch — 🔲 `gd-0.3`

- **Goal:** The agent runtime validates incoming dispatch authority locally, independent of orchestrator enforcement — defense in depth for cross-owner scenarios.
- **Steps:**
  1. Local token cache: agent stores a copy of any grant covering it; validates dispatching authority before executing any task from an external source.
  2. Double-check: `submitter_id` + token scope verified locally even if the orchestrator already cleared it.
  3. Per-task isolated workspace directory provisioned on receipt (pre-cursor to full sandboxing at WP-15): unique tmpdir per task, cleaned on completion.
  4. Availability windows honored: agent checks its configured schedule before accepting tasks from external grantees outside defined hours.
  5. Data-class / jurisdiction check: agent rejects tasks whose `data_class` exceeds the grant's `allowed_data_classes` or `jurisdiction_require`.
  6. Install UX: generate a compact QR-code-friendly registration token; a new collaborator pastes or scans it → agent dials out, registers, appears in the owner's fleet within 30 seconds — no command-line steps required.
- **Exit gate:** A real cross-location collaborator's machine installs the runtime, receives a scoped token, executes a dispatched task, and returns the result. Instant revoke tested live — no task accepted after the revocation timestamp.

---

### WP-10 — Console — Sharing Panel & Full Fleet View — 🔲 `gd-0.3`

- **Goal:** The console surfaces shared agents with clear ownership and scope indicators, and provides a self-contained UI for minting, viewing, and revoking share tokens — no command-line steps required for any sharing operation.
- **Steps:**
  1. **Fleet Overview:** grid/list of all visible agents (owned + shared). Status badges (idle / busy / offline), location tags, ownership indicator ("shared / limited scope"), last-seen, model count, optional location map from `location_tag`.
  2. **Sharing Panel:** form to mint a token — select agents, set task type scopes, resource quotas, time windows, data class, expiry; display all active grants; one-click revoke with confirmation dialog.
  3. **Token import UX:** paste token string or scan QR code → shared agent appears in fleet immediately with granted-scope summary and "shared / limited" badge; no command-line steps.
  4. **Agent Detail view:** for shared agents, only permitted actions are rendered (not merely disabled); non-permitted actions do not appear in the UI.
  5. **Owner audit trail:** per-agent event log showing every dispatch under a grant — grantee, task type, outcome — visible to the owner at all times.
  6. Extend **Gruper core's Chart.js analytics dashboard** with per-grantee task-volume and quota-usage charts; same Chart.js visual language and CSV/JSON export format as core.
- **Exit gate:** All sharing operations (mint, import, revoke) completed in the console with no command-line steps. SC-1 demonstrably met: a new cross-location collaborator goes from zero to first task result in under 5 minutes.

---

### WP-11 — Manager Agent Delegation — 🔲 `gd-0.3`

- **Goal:** A meta-agent (Manager Agent) can decompose a goal and dispatch sub-tasks to worker agents, including across ownership boundaries, while operating strictly within a subset of its human principal's scope — and all dispatches are auditable.
- **Steps:**
  1. `manager_agent` task type: received like any task; the payload is a goal + scope budget from the human principal.
  2. Manager agent reasoning loop: decompose goal into sub-tasks; dispatch each using a **strict subset** of the principal's share token; cannot self-escalate.
  3. Orchestrator enforces: sub-task tokens derived from the manager's grant inherit scope; any attempted escalation beyond the parent grant is rejected.
  4. Delegation chain in the audit log: every sub-dispatch records `parent_task_id` and `delegated_from`; the full chain is queryable.
  5. Console: delegation chains visible in task detail view; aggregated results surface in the parent task's result pane.
  6. Scope-escalation adversarial test: verify manager agent cannot dispatch to agents or task types outside its authority budget.
- **Exit gate:** Manager agent dispatches sub-tasks to at least two worker agents (one owned, one shared cross-owner); all dispatches appear in the audit log with correct delegation chain; scope escalation attempt rejected by orchestrator.

---

## Phase 3 — Cloud Burst & Cost Control — 🔲 `gd-0.4`

**Goal for this phase:** Cloud agent nodes (AWS EC2) spin up on demand, auto-register, accept tasks from the fleet, and self-terminate on idle — with hard budget caps enforced by the orchestrator before any instance is launched.

---

### WP-12 — Container Agent Image — 🔲 `gd-0.4`

- **Goal:** A production-ready multi-arch Docker image that turns any Linux server or cloud instance into a registered agent node with a single `docker run` command.
- **Steps:**
  1. Multi-arch image (`linux/amd64` + `linux/arm64`); CPU variant and CUDA variant published as separate tags.
  2. Entrypoint reads `ORCHESTRATOR_URL`, `REGISTRATION_TOKEN`, `AGENT_TAGS`, `ROLE`, `OLLAMA_BASE_URL` from environment variables or mounted secrets — no hardcoded configuration.
  3. Optional bundled Ollama sidecar for instances without a pre-installed Ollama; GPU passthrough via `--gpus all`.
  4. Boot sequence: env validation → Ollama health check → register with orchestrator → appear in fleet → accept tasks.
  5. Published to `ghcr.io/stelminado/gruper-agent` with `cpu`, `cuda`, `latest-cpu`, `latest-cuda` tags.
  6. CI: multi-arch build on every push to main; smoke test (register + heartbeat + task execution) in GitHub Actions.
  7. **SRI-equivalent integrity:** image layer digests pinned in the Terraform module — mirrors **Gruper core's CDN SRI-hash validation discipline** applied to container layer integrity; CI fails on digest mismatch.
- **Files:** `agent-runtime/Dockerfile`, `agent-runtime/Dockerfile.cuda`, `.github/workflows/build-agent.yml`
- **Exit gate:** `docker run` one-liner on a fresh Ubuntu VM (no prior setup); agent appears in the console fleet within 60 seconds; executes a task; Docker image digest pinned and verified in CI.

---

### WP-13 — AWS Spot Fleet & Hard Cost Controls — 🔲 `gd-0.4`

- **Goal:** A Terraform module launches a pool of AWS spot GPU/CPU instances as agent nodes, with the orchestrator enforcing a hard spend cap before any instance is started.
- **Steps:**
  1. Terraform module: spot fleet request for `g4dn.xlarge` / `g5.xlarge` (GPU inference) and `t3.medium` (light CPU work); spot price cap set; `--instance-interruption-behavior=terminate`.
  2. User Data script: executes the `docker run` one-liner from WP-12; reads secrets from AWS Secrets Manager.
  3. **Hard budget cap (first-class, not afterthought):** orchestrator `POST /pools` accepts `max_spend_usd`; refuses to dispatch new tasks to a pool whose projected accrued cost would breach the cap — enforced at enqueue time, before any instance action.
  4. Orchestrator "drain and stop" signal: `POST /pools/{id}/drain` halts new dispatch and signals running agents to complete the current task and self-terminate.
  5. Idle auto-terminate: agent runtime signals the orchestrator after `IDLE_TIMEOUT` with an empty queue; orchestrator confirms; agent self-terminates — spend stops automatically.
  6. Per-instance cost tracking: estimated cost from instance type × runtime; logged per task and per pool.
- **Files:** `infra/terraform/modules/spot-fleet/main.tf`, `infra/terraform/modules/spot-fleet/variables.tf`, `infra/terraform/modules/spot-fleet/outputs.tf`
- **Exit gate:** Spin up a 2-node spot pool; submit a batch of tasks; verify cost cap halts new dispatch at the configured threshold; verify idle auto-terminate fires within 5 minutes of queue drain. Spend does not exceed the cap under any tested scenario.

---

### WP-14 — Queue-Depth Auto-Scaling — 🔲 `gd-0.4`

- **Goal:** Orchestrator queue depth drives automatic cloud capacity adjustments without manual intervention, within configured budget and agent-count bounds.
- **Steps:**
  1. Orchestrator exposes `GET /metrics/queue-depth` per pool: `pending_tasks`, `active_agents`, `estimated_wait_s`.
  2. Scaling trigger: Lambda function (or lightweight scheduler) polls every 60 s; adds instances when `estimated_wait_s` exceeds a configurable threshold; removes instances when `pending_tasks = 0`.
  3. Scale bounds: `min_agents` / `max_agents` per pool; budget cap enforced before any scale-out action.
  4. Scale-down path: drain running agents gracefully; terminate idle instances only after current task completes.
  5. Cost and utilization dashboard in the console: per-pool spend vs cap, queue depth trend, instance count — extending **Gruper core's Chart.js analytics** with a cost and utilization dimension.
- **Exit gate:** A burst of queued tasks triggers a scale-out event; all tasks complete; idle instances self-terminate; total spend stays within the configured cap. Verified in a staging environment.

---

## Phase 4 — Security Hardening — 🔲 `gd-0.5`

**Goal for this phase:** Cross-owner sharing is safe for sensitive workloads in regulated environments. Desktop and container sandbox containment are demonstrably equivalent. E2E payload encryption is live. A formal security review has been completed. This phase is a hard gate — cross-owner sharing does not advance to beta until all WPs in this phase close.**

---

### WP-15 — Per-Task Sandboxing — All Platforms — 🔲 `gd-0.5`

- **Goal:** Every task on every agent type runs in an isolated per-task sandbox. Desktop and container containment are demonstrably equivalent — this is the exit gate condition, not a best-effort aspiration.
- **Steps:**
  1. **Linux desktop:** Firejail profile per task — isolated tmpfs, dropped Linux capabilities, seccomp filter, empty network namespace with allow-list egress only, cgroup CPU + memory + wall-time limits.
  2. **Windows desktop:** Windows Job Objects + WinSandbox (or AppContainer per-process); hard CPU and memory quotas; network egress via WFP allow-list.
  3. **macOS desktop:** `sandbox-exec` profile restricting filesystem and network; App Sandbox entitlements; outbound-only network control.
  4. **Container (cloud / server):** Docker default seccomp + AppArmor/SELinux profiles; `--read-only` root FS + tmpfs per-task dir; `--network` allow-list mode; `--cpus` and `--memory` hard caps.
  5. **Equivalence validation test suite:** the same task type executed on all four environments; filesystem isolation, network egress blocking, CPU/memory limits, and tool call containment verified identically across platforms; written results documented.
  6. Human-approval gates: high-impact tool calls (`email_send`, external HTTP POST, writes outside the task workspace) pause for explicit operator approval per configurable policy.
  7. Cross-task contamination test: verify no task can read or modify another task's workspace or affect the host OS state.
- **Exit gate:** Written sandbox equivalence report signed off. All four environments pass the validation suite. Cross-user sharing in the console remains locked until this WP closes.

---

### WP-16 — E2E Payload Encryption — 🔲 `gd-0.5`

- **Goal:** E2E payload encryption is a **first-class security requirement** — the orchestrator routes task payloads it cannot read, eliminating Pattern A's central-trust risk for sensitive workloads.
- **Steps:**
  1. Each agent generates an X25519 key pair on first registration; public key stored in the orchestrator's agent record and advertised to authorized dispatchers.
  2. Console (submitter side): encrypts the task payload to the **target agent's X25519 public key** (X25519 ECDH key agreement + ChaCha20-Poly1305 AEAD) before submitting to the orchestrator.
  3. Orchestrator: stores and relays the ciphertext blob without decrypting; records `payload_hash` for audit purposes only.
  4. Agent (receiver side): decrypts the payload inside the task sandbox using its local private key; clears plaintext from memory after use.
  5. Key rotation: agents regenerate X25519 keys on demand; orchestrator invalidates the old key reference on re-registration.
  6. Integration test: inspect the orchestrator's DB at rest; verify the task payload column contains ciphertext, not plaintext.
  7. Simulated compromised-orchestrator test: read access to the full DB; verify task payload content remains confidential.
- **Exit gate:** SC-4 met for payload confidentiality. Simulated compromised-orchestrator test passes and is documented. E2E encryption active for all cross-owner task dispatches.

---

### WP-17 — Hash-Chained Audit Log — 🔲 `gd-0.5`

- **Goal:** The audit event stream is append-only and tamper-evident, providing a verifiable compliance record suitable for regulated-industry audits and run attribution.
- **Steps:**
  1. `events` table upgraded: add `prev_hash TEXT`, `entry_hash TEXT`; `entry_hash = SHA-256(ts ‖ actor_id ‖ action ‖ subject_id ‖ payload_hash ‖ prev_hash)`.
  2. Every state transition (task create, dispatch, progress, complete, fail, revoke, token mint/revoke, delegation) appends an immutable event with hash chain maintained by the orchestrator.
  3. `GET /audit` endpoint: paginated, filterable (by actor, agent, time range, action type); returns events with hashes for client-side chain verification.
  4. Console audit view: per-agent and per-task event logs with chain-verification indicator; exportable as JSON.
  5. Standalone chain-verification CLI: downloads the full event chain and verifies hash continuity — intended for compliance audits independent of the console.
  6. Redaction policy: sensitive payload content appears in the log only as `payload_hash`; no plaintext stored in the event record.
- **Exit gate:** Chain verifies end-to-end for a 500-event test dataset. Tampering a single event (modifying one field on event #250) causes verification to fail at that event and all subsequent. Compliance JSON export tested and validated.

---

### WP-18 — Security Review & Sandbox Parity Sign-off — 🔲 `gd-0.5` exit gate

- **Goal:** A formal security review of the full codebase confirms no critical findings are open; sandbox parity, E2E encryption, and token security are documented and accepted.
- **Steps:**
  1. Run the repository's `/security-review` skill against the full codebase; triage all findings; resolve all critical and high findings before this WP closes.
  2. Threat model review: verify every row in spec §8.5 is mitigated by implemented controls — not just documented, but tested.
  3. **Sandbox parity acceptance:** written equivalence report from WP-15 reviewed and signed off.
  4. **E2E encryption acceptance:** simulated compromised-orchestrator test from WP-16 reviewed and signed off.
  5. Share-token penetration test: scope escalation, replay attack, revocation bypass, and token forgery attempts — all rejected; results documented.
  6. SRI-equivalent integrity check in CI: Docker image layer digests verified on every build, consistent with **Gruper core's CDN SRI-hash CI step**.
  7. SC-4 and SC-6 verified end-to-end with real test data.
- **Exit gate:** No critical or high security findings open. Sandbox equivalence report accepted. E2E encryption adversarial test accepted. Token penetration test documented with all attacks mitigated. Cross-owner sharing unlocked for beta.

---

## Phase 5 — Console Polish, Crews & Beta — 🔲 `gd-0.6–0.9`

**Goal for this phase:** The system is polished, integrated, and documented well enough to hand to 2–3 trusted cross-location collaborators for real-world use. All seven Success Criteria must hold for beta users by `gd-0.9`.

---

### WP-19 — Capability-Based & Policy-Based Auto-Dispatch — 🔲 `gd-0.6`

- **Goal:** Tasks can be routed automatically to the best-fit available agent without requiring an explicit `assigned_agent_id`, with data-class and jurisdiction constraints enforced at dispatch time.
- **Steps:**
  1. Capability-match query: `SELECT` agents satisfying `hardware`, `models`, `tools`, `roles`, `jurisdiction`, and `availability` constraints from the task's requirements.
  2. Policy-priority scoring: prefer local/LAN agents for interactive tasks; prefer cloud agents for batch workloads; prefer lower latency for time-sensitive tasks.
  3. Data-class enforcement at dispatch time: `confidential` tasks route only to agents whose owner, jurisdiction, and compliance posture satisfy policy; rejected at enqueue if no compliant agent is available.
  4. Console: "best match" option in the task composer alongside explicit assignment; shows matched agent(s) and routing rationale before confirming dispatch.
  5. Tests: `confidential` task rejected when no in-scope agent is online; `internal` task dispatched to lowest-latency available agent from a pool of three candidates.
- **Exit gate:** SC-6 met — sensitive tasks demonstrably never dispatched to non-compliant agents. Auto-dispatch covers the three primary routing scenarios (interactive, batch, compliance-restricted).

---

### WP-20 — Crew / Workflow Builder — 🔲 `gd-0.7`

- **Goal:** A visual graph editor for multi-agent pipelines spanning machines and owners, extending **Gruper core's multi-agent round model** to cross-machine, cross-owner execution with explicit data flow.
- **Steps:**
  1. `Crew` data model: ordered DAG of `Task` nodes, each specifying agent target (explicit or capability-match), input sources (inline or prior-node output reference), output handling, and timeout.
  2. Visual editor in the console: drag-and-drop node graph; nodes represent agent task assignments; edges represent data flow between steps.
  3. YAML/JSON import and export for crew definitions — version-controllable and shareable for contractor handoff.
  4. Crew execution engine in the orchestrator: resolves the DAG, dispatches tasks as upstream dependencies complete, aggregates outputs into the final crew result.
  5. Crew result view in the console: extends the embedded **Gruper core conversation UI** to show multi-step crew execution as a conversation thread, one message per agent step — consistent with core's round-based display.
  6. n8n trigger integration: a crew can be launched from an n8n webhook; individual crew steps can invoke n8n workflows as tool calls.
- **Exit gate:** A 3-node crew (at least one owned agent + one cross-owner shared agent) executes a DAG task end-to-end; the result is aggregated and displayed in the console crew result view.

---

### WP-21 — Extended Fleet Analytics & Monitoring — 🔲 `gd-0.7`

- **Goal:** A full fleet-wide monitoring dashboard extending **Gruper core's Chart.js analytics visual language** and export format to distributed fleet metrics and cloud cost tracking.
- **Steps:**
  1. Fleet-level metrics: per-agent success rate, response latency by agent and location tag, task throughput, queue depth over time, agent utilization heatmap.
  2. Cloud cost dashboard: per-pool spend vs budget cap, per-task cost attribution, spend trend over time, projected monthly cost at current utilization.
  3. Live log streaming: real-time task log stream from any connected agent, searchable by keyword — mirrors **Gruper core's debug log search and auto-scroll controls**.
  4. **Identical visual language to Gruper core:** Chart.js line, bar, and pie charts with the same color scheme, tooltip format, and CSV/JSON export behavior — users familiar with core analytics recognize the interface immediately.
  5. Threshold alerting: configurable alerts (agent offline > N minutes, queue depth > N tasks, cost > N% of cap) delivered as console toast notifications and optionally forwarded to an n8n webhook.
- **Exit gate:** Dashboard shows live data for a 3-agent fleet with at least one cloud agent. All charts export to CSV and JSON. Alert triggers correctly on simulated agent-offline and cost-threshold events.

---

### WP-22 — n8n Bidirectional Integration — 🔲 `gd-0.8`

- **Goal:** Agents are callable from n8n workflows and can trigger n8n flows in return — enabling deterministic automation and AI reasoning to operate as peers in the same pipeline.
- **Steps:**
  1. **n8n → agent:** HTTP node or custom n8n community node submits a task to `POST /tasks` with a scoped API token; receives the result via webhook callback or polling.
  2. **Agent → n8n:** `n8n_webhook` tool registered in the agent runtime; calls a configured n8n workflow URL with a structured payload; receives the HTTP response as the tool result.
  3. **Crew → n8n:** a crew node type that wraps an n8n workflow invocation as a step in the DAG (inputs from prior node, output forwarded to next node).
  4. Authentication: n8n integration uses a scoped orchestrator API token (not a full admin credential); per-integration scope enforced.
  5. Documentation and at least one published example workflow for each integration direction.
- **Exit gate:** An n8n workflow dispatches an agent task and receives the result. An agent task triggers an n8n workflow and receives its response. Both tested end-to-end against a real n8n instance.

---

### WP-23 — Closed Beta & Documentation — 🔲 `gd-0.9` exit gate

- **Goal:** 2–3 trusted cross-location collaborators use the system for real work across distinct use cases; all SC-1…SC-7 hold for those real users; complete documentation is published.
- **Steps:**
  1. **Beta participants:** identify 2–3 collaborators representing distinct real-world use cases (at least one involving a regulated or compliance-sensitive environment); confirm participation before `gd-0.6` begins so they can provide feedback throughout the phase.
  2. **Install guide:** step-by-step documentation for all three agent install paths (desktop Linux, desktop Windows, Docker/container); QR token onboarding flow with screenshots; estimated time under 5 minutes for a non-technical user.
  3. **Sharing setup guide:** how to mint a token, configure scope, share with a collaborator, monitor usage, and revoke; no command-line steps assumed.
  4. **Ops runbook:** orchestrator deploy, backup and restore, TLS certificate renewal, log rotation, cost-cap monitoring, incident response checklist.
  5. **Security posture summary (1-page):** for collaborators to review before entering a shared-agent relationship — what the owner can and cannot see, data-class routing behavior, how to revoke at any time.
  6. **SC-1…SC-7 verification checklist:** run against the beta environment with real participants; document evidence for each criterion.
  7. No critical bugs open at beta handoff; all open issues triaged with priorities.
- **Exit gate:** All seven Success Criteria documented as met for real beta users. All documentation complete and reviewed by at least one beta participant. No critical bugs open. Ready to assess v1.0 readiness.

---

## v1.0 — First Stable Release

Declared when the `gd-0.9` exit gate holds for real users. The roadmap is rewritten at that point to record that v1.0 has been reached. Until then, this is the only place "v1.0" appears — as a future target, not a current state.

| SC | Criterion | Target |
|----|-----------|--------|
| SC-1 | Time from install to first remote task result (new cross-location agent node) | **< 5 min** |
| SC-2 | Dispatch overhead, excluding model execution time | **< 5–10 s** typical |
| SC-3 | Owner revocation takes effect | **Immediately** — no new tasks accepted; in-flight tasks killable |
| SC-4 | All traffic authenticated, encrypted, and auditable | **100%** — no anonymous dispatch |
| SC-5 | Works behind consumer NAT / corporate firewall / AWS with no inbound ports | **No port forwarding ever required** |
| SC-6 | Sensitive task never crosses an unauthorized boundary | **Policy-enforced** at dispatch time |
| SC-7 | Agent node loses connectivity mid-task | **Local queue survives; syncs on reconnect; no data loss** |

---

## Post-v1 (`gd-1.x`) — Deferred

The items below are out of scope for the pre-1.0 track. They belong in the `gd-1.x` backlog and are not scheduled until v1.0 is shipped and stable.

| WP | Item | Notes |
|----|------|-------|
| WP-24 | **Pattern B — Federated per-user orchestrators** | Each user self-hosts an orchestrator; sharing authorizes cross-orchestrator dispatch; agent multi-homing. Higher privacy, higher complexity. Token and data model design in WP-08 must not preclude this additive change. |
| WP-25 | **Direct P2P channels (WebRTC / QUIC)** | Orchestrator brokers ICE introduction; agents transfer large artifacts peer-to-peer without relay. Automatic fallback to relay if P2P fails. Added only after the relay path is proven solid in production. |
| WP-26 | **Mobile / PWA console** | Read-only fleet status and approval actions from a mobile device. Console API and data model designed from `gd-0.2` to not preclude this. |
| WP-27 | **Predictive cloud instance pre-warming** | Pre-launch spot instances based on historical task arrival patterns. Requires a stable utilization history baseline. |
| WP-28 | **Cross-machine crews with full scope inheritance** | Full DAG execution across ownership tiers with automatic scope propagation down the delegation chain; requires WP-20 as a base. |
| WP-29 | **Open agent directory with opt-in reputation signals** | Closed-and-invited trust model stays in place until there is a clear operational reason to open it. Not before v1.0 is stable for months. |

**Permanently out of scope:** public trustless compute marketplace; blockchain token incentives; anyone-can-join compute grid; server-side Gruper core (core stays client-only, single-file, and standalone — Distributed does not change this).

---

## Known Technical Debt

| Item | Severity | Notes |
|------|----------|-------|
| OQ-1 / OQ-2 / OQ-3 / OQ-4 / OQ-5 unresolved | **Blocking** | Five open architecture questions (spec §12.2) must be resolved before WP-01 can close. All downstream WPs depend on them. |
| Desktop sandboxing incomplete until WP-15 | **High** | Windows and macOS per-task sandbox not implemented until `gd-0.5`. Cross-owner sharing on Windows/macOS desktop agents blocked until WP-15 and WP-18 close. |
| `events` table lacks hash chain until WP-17 | **Medium** | Event append active from WP-02 (`gd-0.1`); tamper-evidence not in place until `gd-0.5`. Compliance-sensitive deployments should not go live before WP-17 closes. |
| Python agent runtime (memory-unsafe) | **Medium** | Acceptable for prototyping and early milestones. Rust port of sandbox and communication components planned as load and security review demand it; no fixed timeline. |
| Single-orchestrator SPOF | **Medium** | Multi-orchestrator failover interface present in data model from WP-01; full federation (Pattern B) deferred to `gd-1.x`. Agent offline queue (WP-03) mitigates partial impact. |
| No automated integration test suite | **Medium** | Per-WP smoke tests built incrementally. Full integration test suite and Playwright E2E against a mock Ollama endpoint deferred to `gd-0.6+`. |
| Agent loop framework not decided (OQ-1) | **Medium** | Custom ReAct implementation recommended (consistent with Gruper core's hand-built philosophy); task/state schema frozen only after this is resolved at WP-01. |

---

*Last updated: 2026-06-27*
*Companion document: `GruperDistributedSpec.md` (spec `0.2 — Design Draft`) — consult for full architecture, data models, security model, and open questions.*
*Gruper core baseline: `v0.4.5` (`Gruper.html`) — this roadmap builds on core, not over it.*
