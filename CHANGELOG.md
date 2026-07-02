# Gruper Changelog

All notable changes to this project will be documented in this file.

> **Scope note (added 2026-07-01):** entries below `v0.4.5` track **Gruper Core** (`Gruper.html`) only. Starting with the entry immediately below, this changelog also tracks **Gruper Distributed** (`spec/`, `orchestrator/`, `agent-runtime/`, `console/`) — the companion desktop console + orchestrator system that is now the project's primary forward direction. Gruper Core remains the stable, maintained, single-file legacy/fallback tier; its own version stays `0.4.5` unless noted.

---

## Gruper Distributed — `gd-0.2.x` (2026-07-02) — Lifecycle Reliability: no more ghost agents, zombie tasks, or silent failures

Driven by a real Windows testing session whose debug log told one story: agents that looked "ready" but were long dead. Agent statuses live in `orchestrator.db`, which outlives every console install and orchestrator restart — and nothing ever reset them. The heartbeat watchdog only inspects connections it knows about, so a stale `idle` row was invisible to every cleanup path. Everything else cascaded from that lie: Round Table seated dead agents (turns queued forever, Ollama never engaged, "couldn't respond this time"), removal was refused ("it can be removed once it goes offline" — which never happened), and tasks piled up as unclearable "queued" zombies.

**Truthful agent presence (the root-cause fix):**
- FIXED: orchestrator startup now sweeps every non-offline agent to `offline` — no WebSocket can survive a restart, so any `idle`/`busy` row at boot is definitionally a leftover
- FIXED: the heartbeat watchdog now broadcasts a `fleet_event` when it marks an agent offline (previously it updated the database silently, so every open console kept the green "ready" dot forever)
- FIXED: the task-timeout watchdog now broadcasts `task_complete` to the submitter's consoles, so an open answer view stops saying "answering…" for a task the orchestrator already gave up on

**Agents can actually be removed:**
- ADDED: `DELETE /v1/agents/{id}` (owner-scoped soft delete, migration 005 `deleted_at`): the agent leaves every listing, can't take new tasks, can't re-register; a live connection is closed server-side; its queued/in-flight work is failed with error `agent_removed` (and broadcast) instead of stranding
- CHANGED: agent-runtime treats a rejected registration as **fatal** and exits (was: doomed reconnect every 16s forever) — this is what makes deletion stick even for agents this console never spawned
- CHANGED: the console's ✕ now stops the local process best-effort and then deletes server-side — the "wasn't started by this app, so it can't be stopped" dead end is gone, along with the localStorage hidden-agents workaround it forced

**Tasks can actually be deleted (and cancelled):**
- ADDED: `DELETE /v1/tasks/{id}` — for a `pending` task this is a full cancel (the escape hatch for a question queued to an agent that never returns); dispatched/running refused with 409
- ADDED: `DELETE /v1/tasks?scope=failed|all` — the History "Clear" buttons now really delete server-side; "old tasks reappear in every new build" is fixed by making Clear mean clear (in-flight work is never touched)
- ADDED: a Cancel button on queued questions in the answer view

**Round Table reliability:**
- ADDED: pre-flight roster check — the fleet is re-fetched over REST before anyone is seated, so a stale snapshot can't send a round of turns into the void; "No one at the table is reachable" instead of three minutes of silence
- ADDED: fail-fast on turns that are never picked up — a turn still `pending` after 12s is cancelled server-side and marked failed with a pointed message ("isn't picking up work — check its dot"), instead of stalling the table for the full deadline
- CHANGED: failed turns now say **why**: never dispatched / Ollama unreachable / ran out of time / lost connection / agent removed — no more one-size-fits-all "couldn't respond this time"
- CHANGED: turn polling backs off (0.8s → 2.5s after 15s), ending the constant `GET /v1/tasks/…` spam in the debug log

**Fleet identity:**
- ADDED: leftover generic "Local Agent" entries show a one-click "✎ Give this agent a real name" nudge on the card

+13 orchestrator tests (61 total): agent delete (listing / owner scoping / outstanding-task failing / register rejection / live-connection kick), task delete (cancel, 409-while-running, bulk scopes), and the startup sweep.

---

## Gruper Distributed — `gd-0.2.x` (2026-07-01) — Desktop Experience Overhaul

A structural pass at the Console's single-user experience, going after the root causes behind three rounds of recurring Windows-testing feedback (agent identity, model confusion, technical leaks, mechanical Round Table, weak first-run) rather than another layer of label polish.

**Agent identity — specialties are now real, visible, and editable:**
- ADDED: `console/src/lib/roles.ts` — a specialty catalog (icon, human label, one-line "good at" tagline, full persona) ported from Gruper Core v0.4.5's 12 agent templates; every surface that mentions a role renders from it, so `devil_advocate` reads as "😈 Devil's Advocate — argues the other side on purpose" everywhere
- CHANGED: specialties change *behaviour*, not just badges — the persona is sent as the task's `system_prompt` (already supported end-to-end by the orchestrator and agent runtime but never used), replacing the generic "You are a focused {role} assistant" one-liner
- CHANGED: agent cards redesigned for scanning — name, plain-language specialty line, then a quiet model + humanized status line ("ready", "working…", "having trouble"); raw enums, "seen 34s ago", and the full model list moved to the hover tooltip
- ADDED: specialty is editable in place on the agent card (like rename), backed by an extended owner-scoped `PATCH /v1/agents/{id}` that now accepts `{name?, role?}` (+6 orchestrator tests, 46 total)
- ADDED: agents can finally be *removed* — ✕ asks first, stops the local process, and hides the entry (persisted locally; auto-unhides if the agent ever comes back online). Dead grey rows no longer accumulate forever
- FIXED: renames from another console session now apply live (fleet_event `name` was previously discarded)

**Ask flow — one decision, in plain language:**
- CHANGED: the composer is now "Ask a question": pick who answers from a card grid (avatar, name, specialty — no dropdown), type the question, done. Role and Data-class selects removed from the primary flow; "Answer style" (per-question role override) joins the model override under Advanced
- CHANGED: Advanced sliders trimmed and translated (Creativity, Answer length, Context window, Time limit); the Priority slider — meaningless for a single-user desktop — is gone
- ADDED: Ctrl/Cmd+Enter submits; the draft survives closing the dialog (a stray backdrop click no longer destroys a half-typed question)

**Answers — the main event:**
- CHANGED: completed answers lead with the text under one quiet summary line ("Answered in 12.3s · ~41 tok/s"); model/token pills moved behind a "details" toggle
- CHANGED: failures read as plain sentences with a **Try again** button that resubmits the same question to the same agent; error codes sit behind "details"
- FIXED: the History list and the answer pane no longer disagree about the same task — both use one shared status vocabulary (`taskDisplay.ts`); raw statuses (`dispatched`, `dead_letter`) and truncated UUIDs no longer appear anywhere outside the Debug panel
- CHANGED: `task_complete` metrics (duration, model) now fold into the task immediately instead of being discarded until the full-result re-fetch

**Round Table — a conversation, not a batch job:**
- CHANGED: rebuilt as a group chat: the user opens with a message, everyone at the table responds in turn (streaming), and the user can interject at any time — or click "Let them keep going". No more "Start round" / "Round N" machinery
- FIXED: the transcript now lives in a store (`stores/roundtable.ts`), so switching tabs mid-discussion no longer silently destroys the whole conversation (previously component-local state)
- CHANGED: turns are tagged (`input.context.source = 'round_table'`) and filtered out of History, which now shows only questions the user actually asked; failed turns read as a quiet "couldn't respond this time" note instead of raw errors in the transcript; offline agents can't be seated
- CHANGED: model tags moved out of the conversation flow into hover tooltips

**First-run & chrome — no internal nouns:**
- CHANGED: a normal desktop launch never shows a connection form — just a brief "Starting up…" splash; the manual form (engine address, device identity) appears only when the automatic path fails, or via "Advanced setup"
- CHANGED: "Add an agent" reordered for a person: silent Ollama detection reads as one status line (with a "download Ollama" link and URL field surfaced only on failure), then name, specialty grid, and a model picker only when there's actually a choice; polling internals removed from the waiting copy
- ADDED: a three-step first-run checklist (add an agent → ask a question → try Round Table) that checks itself off, replacing the single-step welcome card
- CHANGED: header jargon ("orchestrator local", "live 3/4", `gd-0.2`) collapsed into one health indicator ("3 of 4 agents online") with technical detail in the tooltip; "Fleet"→"Agents", "Tasks"→"History", "+ New task"→"+ Ask"; version string moved to a tooltip
- CHANGED: Analytics no longer shows a wall of zeroes before the first answer, and says whose numbers it's showing

---

## Gruper Distributed — `gd-0.1` → `gd-0.2.x` (2026-06-27 → 2026-07-01) — Foundations Through Desktop Hardening

This is the first changelog entry for Gruper Distributed. In five days the project went from a design spec to a code-complete desktop-first stack (Console + Orchestrator + Agent, SQLite by default, no Docker required) validated end-to-end on Linux, plus a detailed Phase 2 (cross-network sharing) plan. **No Gruper Core version bump** — `Gruper.html` stayed at `v0.4.5` throughout; see its own maintenance entry below for the small number of core-adjacent doc fixes made alongside this work.

**Phase 0 — Foundations (`gd-0.1`) — complete:**
- ADDED: `spec/contracts/` — OpenAPI 3.1 REST/WS API (17 endpoints), WSS message schema (16 message types), 5 versioned JSON Schema 2020-12 data models, and the Gruper-core-to-distributed parameter mapping doc (WP-01)
- ADDED: Skeleton orchestrator — FastAPI + PostgreSQL 16 + Docker Compose, JWT auth, agent registration/heartbeat, watchdog for stale agents (WP-02)
- RESOLVED: OQ-1 (custom ReAct agent loop) and OQ-2 (Pattern A — shared multi-tenant orchestrator) open questions

**Phase 1 — Walking Skeleton (`gd-0.2`) — code complete, automated E2E green:**
- ADDED: Agent runtime desktop MVP — outbound WSS client with Gruper-core-matching exponential backoff (2/4/8/16s), Ollama integration using core's parameter conventions, SQLite offline queue, circuit breaker (WP-03)
- ADDED: Orchestrator task dispatch — submit/dispatch/lifecycle/retry/dead-letter, `SKIP LOCKED` queue, timeout watchdog (WP-04)
- ADDED: Manager Console minimal scaffold — Tauri v2 + Svelte 5 + Tailwind; fleet view, task composer, result view (embeds Gruper core's conversation rendering), per-agent Chart.js analytics (WP-05)
- ADDED: `.github/workflows/build-windows.yml` — Windows installer CI (NSIS + WiX), fixed the Tauri v2 `[lib]`-naming build break, now green and producing downloadable `.exe`/`.msi` artifacts on every `main` push
- ADDED: End-to-end relay validation harness (`tests/e2e/wp06_relay_validation.py`) — drives the real relay against a mock Ollama; **17/17 green**; the first run surfaced and fixed 5 real message-contract bugs (task ID field mismatch, missing `task_ack`, wrong progress/result shapes, missing Ollama `messages` array, missing `fleet_event` broadcast) (WP-06)
- OPEN: real two-machine public-internet/NAT field run (automated E2E proves the logic; the physical field run is still pending)

**Phase 1.5 — Desktop-First Foundation (`gd-0.2.x`) — pivot from Docker+PostgreSQL-first to SQLite/no-Docker-first:**
- CHANGED: Orchestrator now defaults to an embedded **SQLite** backend (`orchestrator.db`) with **PostgreSQL opt-in** via `DATABASE_URL` for the server tier; both dialects pass the same 35-test suite (5× repeated for determinism) with near-identical dispatch latency (~10ms) (WP-30)
- ADDED: `.github/workflows/orchestrator-tests.yml` — first-ever orchestrator CI, as two separate jobs (SQLite with no services; PostgreSQL with a service container) so the SQLite job structurally cannot depend on a database server
- FIXED: a genuine pre-existing concurrency bug in `ws/agent_ws.py` (agent ID could be lost on rapid disconnect, leaving a phantom idle agent) — found and fixed while pursuing SQLite/PostgreSQL test parity, confirmed to pre-date this work
- ADDED: PyInstaller packaging for both the orchestrator and agent runtime — one-command build (`scripts/build-desktop.sh`/`.ps1`) producing self-contained executables; zero-config JWT secret auto-generation replacing a shared hardcoded default (a real security fix, not just UX) (WP-31)
- ADDED: `scripts/validate-desktop-packaging.py` — proves the packaged orchestrator + agent relay a real task end to end with no Docker, no PostgreSQL, no manual Python setup
- ADDED: Tauri Console now spawns, health-checks, and auto-connects to a local orchestrator sidecar with zero manual steps; `tauri-plugin-single-instance` prevents duplicate sidecars; graceful and forceful-kill (SIGKILL/orphan) shutdown handling verified against the real production `tauri build` binary via screenshot (WP-32)
- ADDED: "+ Add Local Agent" onboarding flow — generates an agent identity, detects installed Ollama models, registers and spawns a second sidecar with no config files or manual JWT copy-paste (WP-32.1)
- FIXED (3 rounds of real-Windows hardware bug reports, each found and closed): a placeholder-agent registration path that could never run a task; the detected Ollama model never reaching the spawned agent process; a Chromium/WebView2 Private Network Access policy silently blocking the webview's Ollama probe (moved to a Rust-side raw socket, `detect_ollama_models`); an indefinitely-hanging "waiting for agent to connect" state (rewritten as a bounded polling loop with 3 independent signals); a white-on-white Role Template dropdown; missing stale-task-clearing and per-agent stop controls
- FIXED: a Windows-crashing bug in `agent-runtime/main.py` (`loop.add_signal_handler` unconditionally called — unsupported on Windows' `ProactorEventLoop`)
- ADDED: unified cross-tier **debug logging system** — a Rust ring-buffer sink (5,000 entries) fed by structured JSON log lines from both Python sidecars and the Rust layer itself, plus the frontend; a Debug panel (category/level filters, live tail, search by `agent_id`/`task_id`, copy, `.jsonl`/`.txt` export, "Copy diagnostics"); two-stage secret redaction (Python emit-time + Rust sink-time) against JWTs, tokens, and key material (WP-32.2, `docs/Debug-Logging.md`)
- ADDED: explicit `capabilities.default_model` selection end to end (schema → agent runtime → Console UI), replacing a silent hardcoded model fallback (WP-32.2)
- ADDED: master/detail result view — Fleet | Tasks | wide Detail pane replacing the old cramped 28rem right-rail; real `marked` + DOMPurify markdown rendering, copy-result, distinct fetch-error state (WP-32.2)
- **Open:** WP-31/WP-32/WP-32.1 are Linux-validated and Windows-CI-green (18 runs) but not yet re-verified by a human running the installers on physical Windows hardware — the single biggest remaining risk on the desktop-first push

**Planning:**
- ADDED: `docs/Phase2-gd-0.3-Plan.md` — a grounded, codebase-referenced plan for WP-07…WP-11 (cross-network sharing), including the recommendation (since acted on) to harden the desktop tier first

**Documentation & congruence (this session, 2026-07-01):**
- FIXED: `GruperDistributedSpec.md` §5.1 (recommended stack) and §9 (data models) updated from "PostgreSQL-first, SQLite-footnote" to "SQLite-default, PostgreSQL-opt-in," matching the desktop-first pivot already shipped in `ROADMAP.md` and `README.md` — closes the "companion spec not yet desktop-first" item that had been open in `ROADMAP.md`'s Known Technical Debt table since the WP-30 pass
- ADDED: `ROADMAP.md` WP-32.2 section documenting the debug logging / model selection / result view work, which had shipped in code but was previously undocumented in the roadmap
- UPDATED: `README.md` — Distributed badge (`gd-0.2 walking skeleton` → `gd-0.2.x desktop-first`), "what's shipped" table, positioning language clarifying Core is now the legacy/standalone fallback and Distributed the primary forward direction
- UPDATED: `UserManual.md` — added a scope banner clarifying it documents Gruper Core specifically, with a pointer to the Distributed spec for multi-machine/cross-owner use
- UPDATED: `WeeklyClaudeRoutineCheckup.md` — first entry to review the whole repository (previously scoped to `Gruper.html` only)

---

## Maintenance (2026-06-15 → 2026-06-27) — Infrastructure & Documentation

No version bump — these are infrastructure, security, and documentation changes only. `APP_VERSION` remains `0.4.5`.

**Security & Dependencies:**
- UPGRADED: Chart.js 4.4.1 → 4.5.1 (latest stable)
- UPGRADED: DOMPurify 3.0.8 → 3.4.10 → 3.4.11 (latest stable; 3.4.11 fixes a `setConfig` hook leak)
- FIXED: Removed duplicate CDN `<script>` tags (was loading Chart.js and DOMPurify twice each, with mismatched SRI hashes — silent load failure in strict browsers)
- VERIFIED: All SRI integrity hashes confirmed correct via npm tarball hash computation

**Code Quality:**
- ADDED: `localStorage` `QuotaExceededError` guard in `saveState()` with retry logic and user-facing warning toast
- ADDED: 18 JS section delimiter banners across the `<script>` block for navigability (all unambiguous, version-prefix-free)
- FIXED: Shield icon tooltip now describes security features instead of showing the version tagline
- FIXED: `<noscript>` fallback added for JS-disabled browsers
- FIXED: Disambiguated duplicate `INITIALIZATION` section headers in the JS block
- FIXED: Cleaned up all legacy/version-prefixed and provenance-annotated section headers (JS and CSS blocks; 11 headers renamed across Jun 18–21, 1 redundant header removed)
- FIXED: WeeklyClaudeRoutineCheckup.md internal title corrected from "Daily" to "Weekly" (file renamed 2026-06-26, title lagged)
- FIXED: `ROADMAP.md` onclick handler count corrected from `~64` to `62` (confirmed by grep)

**Infrastructure:**
- ADDED: `LICENSE` (MIT)
- ADDED: `.github/workflows/check.yml` — CI checks CDN reachability, JS syntax, version consistency (fatal on mismatch), and duplicate CDN tag detection
- FIXED: CI version-consistency check made fatal on actual mismatch; CDN versions now extracted dynamically from `Gruper.html`
- FIXED: Four incorrect version dates in `README.md` (wrong year 2025 → correct 2026)

**Documentation:**
- ADDED: `ROADMAP.md` — roadmap with architecture philosophy, near/medium/long-term plans, and known tech debt
- ADDED: `UserManual.md` — full user manual covering setup, agents, controls, analytics, and troubleshooting
- UPDATED: `README.md` — library versions, doc cross-links, screenshot placeholder cleanup
- ADDED: GitHub Actions SRI hash re-verification step — downloads CDN files at CI time, computes SHA-384, fails if hashes diverge from `Gruper.html` `integrity` attributes
- ADDED: GitHub Actions line-count reporting step — prints `Gruper.html` line/byte counts and warns if > 7,000 lines
- UPDATED: `CHANGELOG.md` with this maintenance record

---

## v0.4.5 (2026-01-31) - Streamlined UX

**BREAKING CHANGES:**
- REMOVED: Full Gruper Analysis display (collapsible sections, word frequency, divergence detection)
- REMOVED: `toggleRoundSummary()` function (no longer needed)

**NEW FEATURES:**
- ADDED: Minimal round summary badge - simple one-liner: "📊 Round X complete • N agents responded"
- ADDED: New `.round-summary-badge` CSS class with subtle glassmorphism styling

**IMPROVEMENTS:**
- REDUCED: Round summary from ~200-300px height to ~40px
- IMPROVED: Conversation flow no longer interrupted by verbose analysis blocks
- CLEANED: Removed ~100 lines of analysis code and ~80 lines of CSS

---

## v0.4.4 (2026-01-31) - Reliability & UX Polish

**🏷️ BUG FIXES:**
- Updated all UI version displays to v0.4.4
- Fixed version inconsistencies across the application

**📝 DOCUMENTATION:**
- Removed embedded changelog from HTML
- Moved full version history to separate CHANGELOG.md file

---

## v0.4.3 (2026-01-24)

**BUG FIXES:**
- Fixed 'state.agents.find is not a function' error
- Updated page title to v0.4.3

---

## v0.4.2 (2026-01-23) - Reliability + UX Polish + Analytics + Debug Tools

**NEW FEATURES:**
- ADDED: Reliable skeleton placeholders with retry attempt tracking and time estimates
- ADDED: Collapsible round summary UI with compact design and deduplication
- ADDED: Analytics export (JSON/CSV) and enhanced empty states with axis labels
- ADDED: Debug log search filter and auto-scroll toggle with persistence
- ADDED: Version badge in footer
- ADDED: Prominent consensus toast with green border and 8s duration

**IMPROVEMENTS:**
- ENHANCED: Skeleton messages persist through retries with attempt counters
- ENHANCED: Estimated wait time shown for long-running requests (>60s)
- ENHANCED: Round summary quotes truncated to 120 chars with full text on hover
- ENHANCED: Bar charts show all agents (gray bar for zero successes)
- ENHANCED: Smooth CSS transitions for text scaling
- FIXED: Skeleton messages only removed on success or permanent failure
- IMPROVED: Debug log filtering and auto-scroll controls

---

## v0.4.1 (2026-01-22) - Timeout Control, Text Scaling, Analytics & Consensus Polish

**NEW FEATURES:**
- Global timeout control (Fast/Balanced/Patient/Custom) with per-agent overrides
- Global text scale control (80%-140%) for improved accessibility
- Resizable debug log panel with drag handle and persistent sizing
- Success rate pie chart in analytics dashboard

**IMPROVEMENTS & FIXES:**
- Analytics charts now handle empty/sparse data gracefully with placeholders
- Consensus reached now shows toast + green completion message in conversation
- Analytics auto-refreshes on conversation end (if modal open)
- Consensus flag correctly set and exported
- Removed all hardcoded model-specific timeouts

---

## v0.4.0 (2026-01-21) - Accessibility, Analytics Visuals & New Agents

**NEW FEATURES:**
- Added three new agent templates (Scientist, Psychologist, Engineer)
- Skeleton loading states replacing spinner for thinking indicators
- Chart.js analytics with response time trend and per-agent charts
- Comprehensive ARIA labels for icon-only buttons
- Semantic HTML structure (header, aside, main)
- Focus trapping for all modals
- Semi-opaque backdrops on message content & improved badge contrast
- aria-live and role attributes on messages container
- Smooth skeleton loading animations
- Enhanced text readability over glass backgrounds

---

## v0.3.0 (2024-11-21) - Stunning Glassmorphism + UX Polish

**NEW FEATURES:**
- Floating nebula particles background with smooth animation
- Animated SVG AI orb placeholder (replaced static rocket emoji)
- Message entrance animations with staggered fade-up + scale
- Premium glowing focus ring on task input with pulsing animation
- Pulsing glow on Start button when ready
- Minimizable prompt panel with toggle button
- Custom glass confirmation modals (replaced native alert/confirm)
- Enhanced visual hierarchy with depth and glow effects
- All animations respect prefers-reduced-motion
- File size: 206KB (41% under target)

---

## v0.2.0 (2024-11-20) - Production-Ready Refactor

**MAJOR IMPROVEMENTS:**
- State management with closures and clean getters/setters
- Exponential backoff (2s, 4s, 8s, 16s) for failed API calls
- Circuit breaker—agents auto-disable after 3 consecutive failures
- Security Shield icon and hardened prompt injection protection
- Chart.js lifecycle management and <80ms init performance
- Human-in-the-Loop for active user participation

---

## v0.1.7 (2024-10-31)

**BUG FIXES:**
- Fixed consensus logic bug
- Fixed tooltip z-index issues
- Fixed control panel layout

**IMPROVEMENTS:**
- Implemented DOMPurify sanitization (XSS protection)
- Enhanced security with safe HTML tag whitelist
- Converted to semantic HTML with ARIA roles
- Improved keyboard navigation

---

## v0.1.6

**IMPROVEMENTS:**
- Model-aware timeouts
- Enhanced error handling
- Consensus toggle
- IP preset switcher
- Enlarged task textarea
- Comprehensive tooltips

---

## v0.1.2

**INITIAL FEATURES:**
- Initial state management system
- Local storage persistence
