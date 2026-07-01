# Gruper Distributed — Phase 2 Plan: Desktop Hardening, Identity, and Scoped Sharing

*Planning document — 2026-07-01. Scope: Desktop Hardening + Phase 2 / gd-0.3 (WP-07…WP-11). Status: proposal for review.*

## Strategic Overview

Gruper Distributed faces one governing tension. The product is **desktop-first**: a single-user Tauri app with a bundled SQLite orchestrator sidecar, whose whole promise is "it just works for me, with no ceremony." Phase 2 (gd-0.3, WP-07…WP-11) asks that same codebase to grow **server-grade multi-tenant sharing** — cross-owner dispatch, scoped and expiring tokens, instant revocation, delegation. Those are opposite design pressures. Every branch, flag, and token concept added to the dispatch path and the console taxes the solo experience; every shortcut taken for the solo case becomes a security hole the moment a second person is involved.

The headline recommendation is to **not start gd-0.3 yet**. Insert a tight **2–3 week Desktop Hardening phase** first — structured logging, the task-result re-layout, a model picker, result-safety fixes, and a reliability pass — and only then ship a **deliberately narrow, feature-flagged Phase-2 MVP** that adds *real cryptographic identity* and *single-agent, single-grantee sharing* while leaving the solo path byte-for-byte unchanged. Hardening first is not cosmetic sequencing: Phase 2 is a security feature, and **you cannot build a credible security feature on a foundation whose failures are invisible.** Today every Rust-side and sidecar log line goes to `eprintln!`, discarded in a packaged app. Every cross-owner feature has a silent-failure mode — a task dispatched under a revoked token, a scope check that wrongly rejects, an agent that never receives an abort — and you would be debugging all of them through a keyhole. Debug logging is the instrument panel you need to fly Phase 2.

The single most important risk is that **identity is currently unauthenticated.** "Identity" today is possession of a random 32-byte value: the console generates it via `crypto.getRandomValues`, and `POST /v1/auth/token` find-or-creates a user by that value alone — ed25519 verification is explicitly stubbed in `security.py`. Whoever presents the value *becomes* that user. Building sharing on this means the "grantee" is unforgeable only by design failure. WP-07's ed25519 challenge-response is therefore the gate for everything else: **if identity slips, sharing must slip with it — they are one deliverable.** A red-team pass surfaced a second identity-adjacent gap that must be fixed in the same breath: share tokens, session tokens, and registration grants must not be minted or verified with the same key and the same type-blind `verify_token()`, or a share token becomes a full session token by confusion.

**TL;DR / recommended path.** Spend 2–3 weeks hardening the desktop (debug-logging MVP with sink-side redaction; wide master/detail result view; markdown+copy; model picker; connection status). In parallel, run a 1-week spike on ed25519/Web-Crypto across the three target webviews, because that is the most under-estimated item in the plan. Then spend 5–6 weeks on a flagged Phase-2 MVP: ed25519 login + the `visible_agent_ids` isolation funnel + a crash-safe re-key upgrade migration (WP-07); `share_tokens` mint/list/revoke/import + solo-short-circuit dispatch authorization + revocation-stops-dispatch, with a `task_abort` channel built once (WP-08); a trimmed agent-side grant re-check and abort handler (WP-09); and a trimmed console with import, mint/revoke, and shared-agent gating (WP-10). Cross-owner sharing ships behind a `cross_owner_enabled=false` "trusted-parties technical preview" flag until Phase 4 lands sandboxing (WP-15) and E2E encryption (WP-16). **Defer WP-11 (manager delegation) entirely** — land only its dormant columns and event names. Honest calendar: ~7–9 weeks total; hold a 4–6 week ceiling only by cutting WP-09 install UX, WP-10 audit/analytics, and WP-11 in all forms.

---

## 1. Debug Logging System

Gruper today has four independent, unstructured log surfaces and no way for a user — or a maintainer reading a bug report — to see what actually happened. The orchestrator and agent write Python `logging` to their own stdout; `console/src-tauri/src/lib.rs` drains those pipes into `eprintln!` (`manage_orchestrator` at lib.rs:298–313, `spawn_local_agent` at lib.rs:476–499), which in a packaged desktop app goes to a stderr nobody sees; and the frontend scatters `console.warn/error` into a WebView devtools console that is closed by default. The three hard flows the owner cares about — sidecar spawn, agent registration, and the future cross-owner dispatch + revocation path — each straddle *all four* tiers, so no existing surface can tell their story. The design unifies them into one sink and makes that sink visible, filterable, and exportable in one click.

### 1.1 Architecture: one Rust ring buffer, three feeds

The core decision: **there is exactly one log sink — a bounded in-memory ring buffer in the Rust/Tauri process** — and every tier feeds into it. Rust is the only process that (a) is always running for the whole session, (b) already owns the sidecar stdout pipes, and (c) can serve both a Tauri command and a live event to the frontend. Putting the buffer anywhere else means shipping logs *across* a process boundary to reach the UI.

```
 ┌─────────────────────┐   JSON lines on stdout    ┌──────────────────────────┐
 │ orchestrator sidecar │──────────────────────────▶│                          │
 │  (Python logging)    │   (drained by lib.rs)     │   RUST RING BUFFER        │
 └─────────────────────┘                            │   VecDeque<LogEntry>      │
 ┌─────────────────────┐   JSON lines on stdout    │   cap = 5000, Mutex       │
 │ agent sidecar(s)     │──────────────────────────▶│                          │
 │  (Python logging)    │                           │   ── redaction runs HERE ─│
 └─────────────────────┘                            │                          │
 ┌─────────────────────┐   tracing / log crate     │   get_logs()  ───────────┼──▶ frontend
 │ Rust (lib.rs)        │──────────────────────────▶│   export_logs()          │    (DebugPanel)
 └─────────────────────┘                            │   emit("log-entry", …)───┼──▶ live tail
 ┌─────────────────────┐   invoke("push_log", …)   │                          │
 │ Svelte frontend      │──────────────────────────▶│                          │
 │  (logStore wraps      │                           └──────────────────────────┘
 │   console.*)         │
 └─────────────────────┘
```

The ring buffer is bounded (`VecDeque<LogEntry>`, default **5000 entries**, dropping oldest) so a chatty DEBUG session can never exhaust desktop RAM. At ~300 bytes/entry that is ~1.5 MB, enough to cover a full spawn→register→dispatch→complete cycle plus slack. **Trade-off:** an in-memory buffer loses history on crash. That is the wrong default for the orchestrator's own durability but the right default for a *debug* surface for live diagnosis and immediate bug-report capture — this is not an audit log (that is the separate, hash-chained `events` table deferred to WP-17). An opt-in file mirror (§1.4) mitigates the crash-loss case.

#### The canonical `LogEntry`

Every tier — Python, Rust, JS — must produce this exact shape. It is the contract.

```jsonc
{
  "ts": "2026-07-01T14:03:22.481Z",   // ISO-8601 UTC, millisecond precision
  "level": "info",                     // trace|debug|info|warn|error
  "category": "task",                  // fixed enum below
  "tier": "orchestrator",              // orchestrator|agent|sidecar|rust|frontend
  "agent_id": "a1b2…",                 // nullable — correlation id
  "task_id": "t9f0…",                  // nullable — correlation id
  "msg": "dispatched task to agent",   // human-readable, one line
  "fields": { "share_token_id": "…",   // structured context, post-redaction, allowlisted
              "retry_count": 0 }
}
```

- **`tier` vs `category` are orthogonal, both kept.** `tier` says *which process emitted it*; `category` says *what it is about*. A single `sharing` operation touches frontend, orchestrator, and agent, so conflating them makes the cross-owner flow impossible to filter.
- **`agent_id`/`task_id` are first-class columns, not buried in `fields`.** They are the correlation keys — "click a task, see every line from every tier for that `task_id`" only works if the key is a promoted, indexable field.

Fixed **category enum**: `orchestrator`, `agent`, `sidecar`, `auth`, `task`, `ui`, `ws`, `ollama`, `db`, `sharing`. `sharing` is reserved *now*, ahead of WP-07 — the revocation flow is the single hardest thing to debug in the roadmap, and reserving the category costs nothing so that share-token code slots in with zero logging retrofit. `ws` and `ollama` get their own chips because connection churn and circuit-breaker trips are the highest-volume, most diagnostically-loaded streams.

### 1.2 Python side: structured lines out, structured entries in

The two Python sidecars already write to stdout, and lib.rs already drains it. We change the *shape* of what flows through the existing pipe from free text to one JSON object per line and teach Rust to parse it — no new sockets, no new file handles, no IPC. A shared `structured_log.py` (dropped into both `orchestrator/` and `agent-runtime/`) defines a `logging.Handler` whose `emit()` writes one JSON line prefixed with `\x1e` (ASCII Record Separator):

```python
class JsonLineHandler(logging.Handler):
    def emit(self, record):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": _LEVEL.get(record.levelname, "info"),
            "category": getattr(record, "category", _category_from_name(record.name)),
            "tier": self.tier,
            "agent_id": getattr(record, "agent_id", None),
            "task_id":  getattr(record, "task_id",  None),
            "msg": record.getMessage(),
            "fields": getattr(record, "fields", {}),
        }
        sys.stdout.write("\x1e" + json.dumps(entry) + "\n")
        # flush behavior is GATED on debug.enabled — see §1.5 and the desktop-cost note below
```

- **The `\x1e` prefix** distinguishes a structured line from anything the process prints around our logging (a traceback, a third-party `print`, uvicorn's banner). Lines starting with `\x1e` are parsed as JSON; others are wrapped verbatim as `{level:"info", category:"sidecar", msg:<raw>}`, so we never *lose* output. A sentinel byte is unambiguous where `{`-detection would be fragile against pretty-printed JSON in tracebacks.
- **Category derives from the logger name** (`orchestrator.ws.agent_ws` → `ws`), so most call sites need zero changes. Only cross-cutting emits (dispatch, registration, revocation) pass `extra={"category":"sharing","task_id":tid,"agent_id":aid}` to promote correlation keys.

Wiring is one line after the existing `logging.basicConfig(...)` in each `main.py`: `logging.getLogger().addHandler(JsonLineHandler(tier="agent"))`.

**On the Rust side**, the parse point is the existing drain loop. The `CommandEvent::Stdout(line) | CommandEvent::Stderr(line)` arm strips the `\x1e` prefix and parses to `LogEntry`, falling back to `LogEntry::raw("sidecar", &text)` for unprefixed lines, then calls `log_sink::push(&app, entry)`. The agent's `agent_id` (already in scope in the `spawn_local_agent` closure) stamps `entry.agent_id` as a fallback, so even a raw traceback from a crashing agent is correctly attributed.

**Desktop-cost guardrail (from the simplicity critique).** A naive `sys.stdout.flush()` on *every* record adds a syscall per line to the orchestrator/agent hot path for a feature 99% of solo users never open — and the frontend `console.*` wrapper (§1.4) would cross the Tauri IPC boundary on every call even when the panel is closed, turning a reconnect storm into an IPC storm. Therefore: **when `debug.enabled=false`, DEBUG is dropped at the source, per-line flushing is off (buffer stdout normally), and the frontend `push_log` wrapper no-ops** (calls only the original `console.*`). The off-by-default promise means *zero added per-line I/O*, not merely a hidden panel.

### 1.3 Rust side: a macro, four commands, one event

Rust logs — spawn decisions, health-poll results, the 800 ms crash-grace outcome (`AGENT_SPAWN_GRACE_MS`, lib.rs:359), sidecar `Terminated` payloads — are the most important for a "failed to start" report and today the least visible. A `glog!` macro replaces every `eprintln!`: it keeps the `eprintln!` (so `cargo tauri dev` is unchanged) *and* calls `log_sink::push`, which (1) runs redaction (§1.6), (2) pushes under the `Mutex` evicting oldest past cap, and (3) `app.emit("log-entry", &entry)` for the live tail.

| Command | Signature | Purpose |
|---|---|---|
| `get_logs` | `(filter) -> Vec<LogEntry>` | Snapshot for panel open / backfill before the live stream attaches (same "event-before-listener" hazard the codebase solved for `orchestrator-status`). |
| `export_logs` | `(format, filter) -> String` | Serialized bundle; frontend triggers the download. |
| `set_log_level` | `(level, category?)` | Raises/lowers verbosity globally or per-category (§1.5). |
| `push_log` | `(entry)` | Frontend→Rust feed. |

**Capabilities.** `capabilities/default.json` currently grants only `["core:default","store:default"]`. Add `core:event:default` (for `listen("log-entry")`) and an `allow-command` block for the four commands. No CSP change: these are `invoke()` IPC, not network fetches. This beats `tauri-plugin-log`, which would add a dependency, an init, and a permission grant while being unable to ingest the Python sidecar JSON lines the drain-parse handles.

### 1.4 Frontend: `logStore` + `DebugPanel.svelte`

`console/src/lib/stores/logs.ts` (1) wraps `console.warn/error/info` so scattered frontend calls (`orchestrator.ts:53`, `console_ws.ts`, `+page.svelte:61`) flow into the same system — forwarding to Rust via `invoke("push_log", …)` (gated off when disabled) *and* calling the original method so devtools still work; and (2) `listen("log-entry", …)` to receive the live stream, appending into a bounded local `writable<LogEntry[]>` mirroring the Rust cap.

**`DebugPanel.svelte`** is a right-side slide-over (reusing the existing glassmorphism), opened by **Ctrl/Cmd+`** and a subtle bug icon in the top bar:

```
┌─ Debug ────────────────────────────── [Copy] [Copy diagnostics] [Export ▾] [×] ─┐
│ Categories: (orchestrator)(agent)(sidecar)(auth)(task)(ws)(ollama)(sharing)(ui) │
│ Level: [ trace  debug ●info  warn  error ]    Search: [ agent a1b2______ ]  ⏸/▶ │
├─────────────────────────────────────────────────────────────────────────────────┤
│ 14:03:21.910  info  sidecar   agent survived 800ms grace window                  │
│ 14:03:22.004  info  ws        agent registered (owner=u7) [agent:a1b2]           │
│ 14:03:22.481  warn  sharing   dispatch blocked: share_token revoked [task:t9f0]  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

- **Category chips** toggle a `Set<category>`; **Level** is a threshold slider; **Search** matches `msg` + `fields` + promoted `agent_id`/`task_id`, so typing a task id gives the cross-tier trace.
- **Live tail** with a pause (⏸) so a user can freeze the view to read a line.
- **Copy** puts the currently-filtered rows on the clipboard as text.
- **Export** downloads `.jsonl` or `.txt` of the filtered set.
- **Copy diagnostics** bundles the buffer plus a header (`ORCHESTRATOR_VERSION`, `get_orchestrator_status()`, OS/arch, agent count, WS state). This turns "it doesn't work" into a triageable report — the highest-leverage feature for a solo-maintained app. **But it must exclude task input/output and cross-owner content by default** (see §1.6 redaction hardening) with an explicit opt-in and warning, or it becomes one-click cross-tenant data exfil into a forum paste.

### 1.5 Enable & verbosity: off-by-default, one click to loud

A persisted setting via `tauri-plugin-store`: `debug.enabled` (bool, default **false**) and `debug.levels` (`{category: level}` map, default `info`). When disabled, the sink still captures `info`+ (so a bug report is never empty) but DEBUG is dropped at the source, per-line flush is off, and the frontend IPC wrapper no-ops (§1.2). Propagating verbosity to sidecars: (1) at spawn via `GRUPER_LOG_LEVEL=debug` (`config.py` already reads `LOG_LEVEL`) — always available; (2) at runtime via `POST /v1/debug/log-level` (guarded by `get_current_user_id`) and, for agents, a `set_log_level` control frame. **Security note (from the critique):** the runtime level endpoint and the WS `set_log_level` frame add attacker-useful capability (flip an agent to DEBUG to force secret-adjacent logging) and ride the same channel as `task_abort`/`revoke`; keep DEBUG redaction identical to INFO and rate-limit level flips. The runtime path is full-version, not MVP.

### 1.6 Secret redaction: allowlist first, sink-choke second

Redaction converges at one place — `log_sink::push` in Rust, before an entry enters the buffer — so every feed benefits regardless of which tier was careless. **The security critique correctly warns that a sink-only, pattern-based denylist is insufficient as the *only* net.** The design therefore uses two layers:

1. **Allowlist of emitted fields, enforced at the emit site.** Structured entries carry only fields explicitly marked safe. Free-text `msg` from sidecars is treated as untrusted and truncated/dropped from exports. **Private keys (WP-07) and auth nonces are NEVER logged at all** — enforced with a lint/test at the emit site, not merely at the sink. A private key logged under a field named `identity`/`sk`/`priv`, or a 32-byte nonce (matched by no pattern), would sail past a regex denylist and enable the H1 replay attack; the emit-site rule is the real defense.
2. **Sink-side pattern redaction as defense-in-depth**, applied to `msg` and every string in `fields`:

| Target | Pattern | Replacement |
|---|---|---|
| JWT | `eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+` | `<jwt:…####>` (last 4 kept for correlation) |
| `?token=` in URLs | `([?&]token=)[^&\s]+` | `$1<redacted>` |
| pubkey/x25519/token_string | field key `/pubkey|x25519|token_string|secret/i` | `<redacted:len=N>` |
| `Authorization: Bearer …` | `(Bearer\s+)\S+` | `$1<redacted>` |

The `?token=` rule closes the leak at `ws_client.py:91`. The frontend also calls the original `console.*`, so **devtools remains an unredacted surface** — acceptable for dev, documented. "Copy diagnostics" excludes task prompts/outputs and cross-owner content unless explicitly opted in.

### 1.7 Walking a hard flow: cross-owner dispatch + revocation, filtered

Filtered to `task:t9f0` across all four tiers — impossible to see today (Rust stderr + two Python stdouts + a devtools console simultaneously):

```
[frontend]     14:03:20.001 info  sharing  submitting task under share_token <jwt:…a41f> [task:t9f0]
[orchestrator] 14:03:20.044 info  task     task created submitter=u7 owner=u3 [task:t9f0][agent:a1b2]
[orchestrator] 14:03:20.061 info  sharing  share_token active, scopes ok, quota 1/2 [task:t9f0]
[orchestrator] 14:03:20.070 info  task     dispatched (FOR UPDATE SKIP LOCKED) [task:t9f0][agent:a1b2]
[agent]        14:03:20.190 info  task     task_ack → running [task:t9f0]
[frontend]     14:03:22.400 warn  sharing  grantee revoked share_token <jwt:…a41f>
[orchestrator] 14:03:22.455 warn  sharing  revoke: token→revoked_at set, is_active=false [task:t9f0]
[orchestrator] 14:03:22.460 warn  sharing  sending abort frame to agent [task:t9f0][agent:a1b2]
[agent]        14:03:22.520 warn  sharing  abort received, cancelling in-flight task [task:t9f0]
[orchestrator] 14:03:22.590 warn  sharing  result rejected: token revoked; task→dead_letter [task:t9f0]
```

Every question the spec raises becomes answerable by reading: did the quota check pass (line 3)? did the abort reach the agent, or did the WS frame drop (the `sending`/`received` pair)? was the result suppressed even if generation finished (last line — the guarantee the honest revocation model actually provides, §4/WP-08)? This trace *is* the acceptance test for WP-08 and is exactly why `sharing` was reserved before a line of share-token code exists.

### 1.8 Effort & slicing

| | Scope | Effort |
|---|---|---|
| **First slice (MVP) — the Phase-2 prerequisite** | Python `JsonLineHandler` + one-line wiring; Rust `LogEntry`, ring buffer, drain-parse replacing the 4 `eprintln!` sites; `get_logs`/`export_logs` + capability grant; read-only `DebugPanel` with chips, level filter, Copy, Export. **Sink redaction + emit-site allowlist are in this slice — non-negotiable.** No live event, spawn-env verbosity only. | ~2–3 days |
| **Full version (deferrable, NOT on the Phase-2 critical path)** | `glog!` everywhere; frontend `console.*` wrapping + `push_log`; live event + tail/pause/search; runtime verbosity; "Copy diagnostics"; store enable-flag; optional file mirror. | +3–4 days |

Only the MVP slice gates sharing. Its redaction guarantee is what lets us safely ask users to paste logs.

---

## 2. Immediate Desktop UX Improvements

These make the desktop app *feel* finished before any sharing work lands. They touch only the Console and one backward-compatible change in `agent-runtime/ws_client.py`. None require an orchestrator schema change or are gated on WP-07. The layout rework is deliberately done here, in the hardening phase, so the WP-10 sharing UI is a drop-in rather than a co-refactor — refactoring the layout *after* wiring sharing into it is the "refactor twice" trap.

### 2.1 Model selection: make the agent's model a choice, not a silent accident

**The defect.** `AddAgentDialog.svelte` builds `capabilities.models = detectedModels` — every model Ollama reports, unordered — serialized into `CAPABILITIES` by `spawn_local_agent`. At execution, `ws_client.py::_model_and_options` uses `configured_models[0] if configured_models else "llama3.1:8b"`. So the default is `detectedModels[0]`, the first entry of an unordered list the user never saw. If Ollama lists `codellama:13b` first, every task runs on the 13B code model, invisibly.

**Fix: an explicit `default_model` field, not list-order.** Coupling a *policy* decision to an *inventory* fact and array ordering is the most fragile thing you can depend on.

```jsonc
// AgentCapabilities (console/src/lib/types.ts) + its mirror in spec/contracts/models/
{ "models": ["llama3.1:8b","codellama:13b"], "default_model": "llama3.1:8b",
  "roles": ["analyst"], "tools": [], "hardware": {"cpu_cores": 8, "ram_gb": 16} }
```

Runtime change is strictly additive so existing registered agents keep working — **and must treat empty-string/whitespace as "fall through," not "use empty"** (a `default_model:""` from an unselected picker would otherwise send an empty model name → every solo task fails with `ollama_error`):

```python
default_model = (caps.get("default_model") or "").strip() \
                or (configured_models[0] if configured_models else None) \
                or "llama3.1:8b"
model = prefs.get("name") or default_model
```

Update `types.ts` and the JSON schema in the **same PR** to avoid contract drift. No `spawn_local_agent` change — it already forwards the whole `capabilities_json` blob.

**Dialog UX.** After detection, replace the passive "Found N models" line with a `<select>` for the default, initialized via `$effect` to `detectedModels[0]`. **TaskComposer** turns the free-text `modelName` input into a `<select>` populated from the agent's advertised models plus an "Agent default" sentinel (`''` → omit `model_preferences.name`, existing behavior). **AgentCard** leads with the bolded default (`{default_model} · +N more`); **ResultView** already renders `result.model_used` — it just needs to survive the layout rework.

**Security note (cross-owner, from the critique):** because `model_preferences.name` can pin *any* advertised model and `max_ram_gb_per_task` is unenforceable in Phase 2, model choice is the de-facto resource lever. For cross-owner tasks, clamp to the agent's `default_model` unless the grant explicitly permits override (a cheap addition to token conditions). This is a WP-08/WP-10 concern flagged here because it originates in the model surface.

### 2.2 Task result display: reclaim the wide pane with master/detail

**The defect.** In `+page.svelte`, the result lives in a `w-[28rem]` fixed right rail, rendered *below* `TaskComposer` (~420px tall) inside one scroll container. Meanwhile the `flex-1` center pane — the widest region — renders nothing but a list of 2-line task rows. The information architecture is upside down: the least valuable content owns the most space.

**Recommendation: make the CENTER pane a master/detail reader; move the composer to a modal.** The task list is navigation → a narrow column; the selected task's progress + result is content → the wide area; the composer is a transient action → behind a "+ New task" button. The modal is also the natural future home of the WP-10 share UI, so this pays forward into Phase 2 instead of being thrown away.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Gruper Console   gd-0.2      ● orchestrator: ready   ● ws: live   3/4 online  │
├──────────┬──────────────────────────────────────────────────────────────────┤
│  FLEET   │  [ + New task ]                    task: analyst · llama3.1:8b · ✓ │
│ (w-56)   │  ─────────────────────────────────────────────────────────────── │
│ ●Agent A │  Progress ▸  1.9s [round 1] Drafting summary …                    │
│ ●Agent B │                                                                    │
│ ○Agent C │  Result · llama3.1:8b · 4.2s              [ Copy ]  [ Re-run ]      │
│  TASKS   │  ┌──────────────────────────────────────────────────────────────┐ │
│ (w-64)   │  │  ## Executive summary   (real markdown)                      │ │
│ ▸ #a1b2  │  └──────────────────────────────────────────────────────────────┘ │
└──────────┴──────────────────────────────────────────────────────────────────┘
```

The task list collapses to a `w-64` master column inside the wide center; `ResultView` fills the rest (it already handles `taskId===null` with a clean empty state, so mounting it unconditionally Just Works). The composer opens as a centered modal reusing `AddAgentDialog`'s proven overlay shell; on submit, close and set `activeTaskId` (the existing `onTaskSubmitted` callback) so the user drops into live progress. `AgentAnalytics` becomes a tab in the detail area.

**Solo-ergonomics guardrails (from the simplicity critique):**
- **Cold-start.** Don't add a click to the daily solo flow. When no task is selected, land the user in compose (open the modal on load, or keep a lightweight inline "New task" entry), so a solo user who lives in the composer isn't taxed by the "future share modal" rationale.
- **Markdown must render offline or degrade visibly.** The async `import('marked')`/`import('dompurify')` in a `$effect` must be **statically bundled**, not runtime-fetched, or a strict packaged-app CSP makes the import silently reject and `renderedHtml` stays empty → a *blank* result, worse than today's ugly-but-present regex. Keep a synchronous escaped-plaintext fallback so a failed import degrades to visible text, and test in the packaged app, not just dev.

**What the reader needs beyond layout (all in `ResultView.svelte`):**
1. **Live progress** already streams via `tasksStore.applyProgress`; bump `max-h-48` → `max-h-[40vh]` and auto-scroll.
2. **Real markdown, finally.** The current `renderMarkdown` is a naive regex whose own comment admits it. Route through `marked` + `DOMPurify` (already project deps). This is a genuine security hardening: task output is untrusted model text rendered with `{@html}`; DOMPurify closes the door permanently. Rank high.
3. **Copy-result button** in the Result header (raw markdown source by default).
4. **Distinguish fetch-error from empty result.** `getTask()`'s `.catch(() => { resultText = null })` collapses "fetch failed" into "no output." Add a `fetchError` state and a retry, so a network blip doesn't masquerade as an empty answer.

The `failed`/`timed_out`/`dead_letter` panels already exist and are good.

### 2.3 Other quick wins, ranked by impact ÷ effort

| # | Win | Where | Impact | Effort |
|---|-----|-------|--------|--------|
| 1 | Real markdown pipeline (also XSS hardening) | `ResultView.svelte` | High | S |
| 2 | Copy-result button | `ResultView.svelte` header | High | XS |
| 3 | Connection status in header | `+page.svelte` header + new `wsStatus` store | High | S |
| 4 | Model picker + visible default | §2.1 | High | M |
| 5 | Keyboard submit (⌘/Ctrl-Enter) | `TaskComposer.svelte` | Med | XS |
| 6 | Fetch-error vs empty result | `ResultView.svelte` | Med | XS |
| 7 | Toasts instead of inline red boxes | composer/dialog/page | Med | M |
| 8 | Analytics empty-state guidance | `AgentAnalytics.svelte` | Low | XS |
| 9 | Role/tool badge on AgentCard | `AgentCard.svelte` | Low | XS |

**On #3 (connection status) — more valuable than it looks.** The header shows only "N/M online." Two connections the user can't see: the orchestrator sidecar (tracked via `get_orchestrator_status`) and the console WS (`console_ws.ts`, which only `console.*`-logs its lifecycle). Add a tiny `wsStatus` writable (`'connecting'|'live'|'reconnecting'`) set from the socket's existing `onopen`/`onclose`/`_scheduleReconnect` handlers, and render two header dots. This matters because a WS drop fires `fleetStore.markAllOffline()`, so the whole fleet *appears* offline during a reconnect — a scary phantom outage. **Do not infer WS health from agent statuses** (circular: the WS drop is what set them offline); use an explicit store fed by the socket lifecycle. These handlers are the same branch points a frontend log surface (§1) would tap, so build `wsStatus` thin — the log store will later subsume it.

**On #7 (toasts):** lower priority than it sounds. The three inline error boxes are ugly but functional and contextual. Sequence after the layout rework so the toast host lives in the new shell.

### 2.4 Sequencing & cross-cutting flags

| Order | Item | Effort | Notes |
|-------|------|--------|-------|
| 1 | Markdown + copy + fetch-error (`ResultView`) | ~0.5 day | Self-contained; ship first for instant credibility. |
| 2 | Model picker + `default_model` + surfacing | ~1–1.5 days | Touches dialog, composer, `types.ts`, one line in `ws_client.py` + schema. No Rust change. |
| 3 | Layout rework: master/detail + composer modal | ~1.5–2 days | Biggest structural change; do after `ResultView` is already good. |
| 4 | Header status + keyboard submit | ~0.5 day | New `wsStatus` store from existing handlers. |
| 5 | Toasts, analytics empty-state, badges | ~1 day | Polish. |

≈ **5–6 focused days.**

Cross-cutting flags: `default_model` touches a contract (keep runtime additive). The `wsStatus` handlers become log emit-points later (don't over-invest). The composer-modal is the future WP-10 share-UI home, and the master/detail reader is where a grantee's received results render — don't paint into a single-owner corner (e.g., don't hardcode "the result author is always me"). Not in scope: there is still no `DELETE /v1/agents/{id}` — "remove agent" stays "stop the local process + mark offline"; the layout must not imply a delete affordance the backend can't honor.

---

## 3. Strategic Assessment

Four questions, answered decisively, with the feasibility and simplicity critiques folded in.

### 3.1 Should we harden the desktop before starting gd-0.3? — Yes, firmly.

Sequence a **2–3 week Desktop Hardening phase before WP-07.** The primary argument is observability: Phase 2 is a security feature, every cross-owner feature has a silent-failure mode, and today those failures vanish into discarded `eprintln!`. Debug logging is the instrument panel. The secondary argument is that the known UX bugs sit on the *exact* surfaces Phase 2 must extend — fix the layout while it's still simple, or refactor twice.

| Item | Scope | Why it de-risks Phase 2 |
|---|---|---|
| Structured logging (MVP slice) | §1 | The instrument panel; every WP-07..WP-10 failure becomes observable from a user's export. |
| Task-result re-layout | §2.2 | Stabilizes the surface the WP-10 sharing panel plugs into. |
| Model picker | §2.1 | Removes "which model ran my task?" *before* it becomes a cross-tenant support question. |
| Result safety + copy | §2.3 | XSS in rendered output is worse under sharing (one owner's output in another's console). |
| Reliability trio | WS indicator; killed-agent soak test of `requeue_or_deadletter` + timeout watchdog; `agent-sidecar-exited` toast | These paths carry revocation/abort semantics later; prove them green first. |

**The feasibility critique refines the scope: only the logging MVP slice gates Phase 2.** Live-tail, runtime verbosity, `console.*` wrapping, and the file mirror are deferrable off the critical path.

### 3.2 What is the minimum-viable Phase 2? — One owner shares one agent with one grantee, scoped/expiring/revocable, on real identity.

**IN scope (4–6 weeks of sharing work, on top of hardening):**
- **WP-07** — ed25519 challenge-response identity + owned-agent isolation hardening via a single `visible_agent_ids` funnel. The non-negotiable core.
- **WP-08** — single-agent, single-grantee `share_tokens` (mint/list/revoke/import), dispatch-time authorization with a solo short-circuit, and **revocation-stops-dispatch** plus a best-effort in-flight abort + **server-side result suppression**.
- **WP-09** — agent-side grant re-check (defense-in-depth) + `task_abort` handler. **Trimmed** — no install UX, no workspace isolation.
- **WP-10** — types/client/fleet-tagging/import/mint-revoke panel + shared-agent gating in the composer. **Trimmed** — no audit log, no per-grantee analytics.

**OUT / deferred (stored-not-enforced or dormant, safe to defer):**

| Deferred | Why deferring preserves the full design |
|---|---|
| **WP-11 (manager delegation) in ALL forms** | Highest complexity/blast-radius; hard-depends on WP-07/08/09/10 being *finished*, plus WP-15/16. Even the "static decomposer" needs most of WP-08's hardest surface plus a new one. Land only `parent_token_id` + the `delegation_*` event names. |
| WP-09 cross-machine QR onboarding | Loopback-only orchestrator has **no reachability story** without server-tier/tunnel; the QR solves credential handoff and nothing about reachability. Cut. |
| WP-09 per-task workspace isolation | A seam for WP-15 with nothing to isolate yet (tasks are prompt→text). |
| Quotas `max_ram_gb_per_task` / full `max_tasks_total` | RAM needs cgroups (WP-15). Store, surface, don't claim enforcement. |
| Multi-agent / multi-grantee tokens; jurisdiction routing; time-window conditions; approval-tool gates | `agent_ids[]`/`grantee_user_id` are already parametric; `conditions{}` is nullable JSON; MVP populates single-element / leaves empty. |
| Result-visibility `full`/`none` server filtering | Keep the field; enforce only `output_only` for MVP. |
| E2E encryption (WP-16), sandboxing (WP-15), hash-chained audit (WP-17) | Phase 4; the reason cross-owner stays behind a "not production-safe" flag. |

The discipline: **every deferred field is stored schema-complete, none is silently dropped.** MVP writes complete `share_tokens` rows and enforces a named subset.

### 3.3 How do we keep multi-tenancy from degrading the solo desktop? — Six guardrails, backed by an enforced regression suite.

1. **Solo fast path is a literal no-op.** The first branch in dispatch authorization remains `agent.owner_id == submitter_id → return ALLOW` on the identical code path. The share-token lookup is an `else` a solo user never enters. **Critically, that short-circuit must not call `visible_agent_ids` or read `share_tokens` first** — that helper is a fleet-wide scan for the *list* endpoint; using it for single-dispatch authorization would replace one indexed PK lookup with a full owned-fleet fetch on every solo task. Dispatch authorization is a point check.
2. **Verification is free for the solo case** — the ownership check short-circuits before any token query.
3. **Migration safety.** `005` only *adds* tables; `tasks.share_token_id` already exists and is NULL for every historical row. **But (simplicity critique F2): SQLite cannot `ALTER TABLE ADD COLUMN ... REFERENCES`.** Do not retrofit an FK onto `tasks.share_token_id` (impossible on SQLite, pointless — the relationship is app-enforced); add only the partial index. FK columns go in `CREATE TABLE` of new tables.
4. **One code path across SQLite and Postgres.** Write PG-style, pass through `adapt_sql()`, use `db.q(pg=…, lite=…)` only for structurally-different DDL. **But this cuts both ways (critique H2):** a COUNT-then-INSERT quota check that is accidentally safe on SQLite's single-writer is *unsafe* on Postgres READ COMMITTED. Concurrency guards must be atomic compare-and-swap, not COUNT-then-write (§WP-08).
5. **Feature-flag sharing; hide the UI when unused.** Default the panel off for desktop builds; hide the entry point unless the user has minted/received a token. Flag it server-side too. **Tuck the `[Share]` button** behind "has ≥1 owned agent AND (ever minted OR flag)" or into an overflow menu, so the default solo header is byte-identical to today.
6. **A pure-desktop regression suite that must stay green on both dialects, as a merge gate** — the tripwire that converts intentions into a guarantee. The rule: **no Phase-2 PR merges if it changes any solo-path observable behavior or per-solo-task query/IO cost.** Enumerated tests below.

**Required solo-path regression tests (from the simplicity critique — must exist *before* the sharing endpoints merge):**
1. Full migration chain 001→latest against a real SQLite file (catches Postgres-only DDL, `;`-split breakage).
2. Populated-DB upgrade test, killed at each re-key step boundary, asserting same `users.id` and zero orphans.
3. Solo dispatch **query-count** assertion: own-agent submit never touches `share_tokens`.
4. Solo agent-disconnect retry: kill mid-task (no token) → re-enqueue + completion unchanged.
5. Auth-expiry returns **401**, own-agent submit returns **200** (never 404).
6. Idempotency: same `(submitter_id, correlation_id)` dedupes to one task.
7. Model fallback: no/empty `default_model` resolves to `models[0]`.
8. Packaged-app markdown renders offline; failed import degrades to visible text, not blank.
9. Solo (zero-grant) console screenshot-diff identical to pre-Phase-2.
10. Event-action enum conformance: every emitted action ∈ schema enum.

### 3.4 Risks of building WP-07..WP-11 on this foundation

| # | Risk | Rating | Mitigation |
|---|---|---|---|
| 1 | **Identity is a random localStorage pubkey; ed25519 stubbed.** The grantee identity is unforgeable by design failure. | **High** | WP-07 is the gate for all of Phase 2. No share-token endpoint ships until challenge-response is real and the console holds a private key it never transmits. Identity and sharing are one deliverable. |
| 2 | **Token-class confusion** (critique C1): share, session, and registration JWTs minted with the same secret and verified by a type-blind `verify_token`. A share JWT whose `sub` is the owner becomes a full session token. | **High** | Separate signing keys per token class; enforce `typ`/`aud`/`iss` on **every** decode (`verify_token(token, *, expected_typ)`), no call site decodes without declaring the expected type. Ideally sign grants with the owner's ed25519 key (below). |
| 3 | **Agent "independent" verification is false in Phase 2** (critique C2): grants are HS256-signed with the secret the orchestrator holds, so a malicious orchestrator forges any grant; short TTL bounds replay of a *leaked honest* grant but not a re-minting signer. | **High** | State plainly: the agent check defends against a *buggy*, not *malicious*, orchestrator until WP-16. The only pre-WP-16 independence primitive is **signing grants with the owner's ed25519 key (already introduced by WP-07)** — a modest reordering, not new crypto. Cross-owner stays flag-off. |
| 4 | **No mechanism to abort a running task**; the `task_abort`/`revoke` frame does not exist and the agent's `CancelledError` branch **re-enqueues unconditionally** (`ws_client.py:226`), so a naive abort resurrects revoked work. | **High** | Build the `task_abort` channel once (WP-08). Gate re-enqueue on an abort flag (tested merge gate). Add **server-side result rejection** for revoked/expired `share_token_id` so revocation is effective even against a non-cooperating agent. Restate the guarantee honestly (below). |
| 5 | **Upgrade re-key data loss** (simplicity F1): the WP-07 first-launch re-key can orphan an existing user's whole fleet if interrupted. | **High** | Never delete the legacy pubkey until a post-adopt challenge-response login succeeds; idempotent `adopt-key`; a "migration complete" store sentinel; release-gated end-to-end test on a populated DB killed at each step. |
| 6 | **SQLite single-writer under multi-tenant load.** | **Med** | A Postgres-tier concern by design; keep the share-token check a cheap read; steer real multi-grantee deployments to Postgres. Document SQLite as single-user-plus-occasional-sharing. |
| 7 | **Audit is not tamper-evident until WP-17** (critique M3), yet WP-10/WP-11 present `events` as compliance-grade provenance. | **Med** | Label the audit surface "operational log, not tamper-evident until WP-17." On Postgres, revoke UPDATE/DELETE on `events` for the app role as a cheap partial mitigation. |
| 8 | **Audit action-string drift** (dotted vs underscore). | **Med** | Reconcile toward the schema enum in one PR before adding sharing events; a single `Action` enum + a conformance test. |
| 9 | **Hard Phase-4 gate:** no sandboxing/E2E; cross-owner runs a stranger's prompt on your Ollama/filesystem with plaintext I/O. | **High** | Keep cross-owner behind a "trusted-parties-only, not production-safe" flag until Phase 4. The `scopes[]` exclusion of `execute_arbitrary` is a mitigation, not a substitute for a sandbox. |
| 10 | **Simplicity erosion.** | **Med** | The §3.3 guardrails + the regression suite are the mitigation; "did a solo user's experience change?" is a per-PR review item. |

**Two claims must be corrected wherever they appear.** (1) **"Revocation within one dispatch cycle — no grace period"** is true only for *not-yet-dispatched* work; in-flight is *best-effort cancel + guaranteed result-suppression + `max_wall_time_s` ceiling*. (2) **"The agent verifies independently of the orchestrator"** is false while grants are HS256-signed with the orchestrator's secret; it becomes true only if grant-signing moves to the owner's ed25519 key or waits for WP-16. State both in those exact terms so the plan implies no guarantee the Phase-2 code cannot meet.

**Bottom line:** Risks 1–5 and 9 determine whether Phase 2 is *honest*. The single highest-leverage change is **C1 + C2 together** — give share/budget/registration grants their own signing key (ideally the owner's ed25519 key WP-07 already introduces) and enforce `typ`/`aud` on every decode. That one move closes the token-confusion bypass, makes the agent's defense-in-depth check genuinely independent, and removes the malicious-orchestrator forgery hole a full phase earlier than WP-16.

---

## 4. Phase 2 Implementation Plan (WP-07 to WP-11)

### WP-07 — Multi-Tenant Orchestrator & Identity

**The one sentence that governs this packet.** Today identity is the bearer of a random 32-byte string: the console generates it via `crypto.getRandomValues`, and `POST /v1/auth/token` does a bare find-or-create by pubkey with no signature check (ed25519 stubbed). WP-07 makes the pubkey a *claim* and the private key the *proof*. The session layer is unchanged — after proving key possession, the user still gets the same short-lived HS256 bearer JWT, and every route keeps using `get_current_user_id`. We upgrade *login*, not *sessions*.

**Identity: ed25519 challenge-response.**

```
POST /v1/auth/challenge { pubkey } → { nonce, expires_at }   // nonce stored server-side, 120s TTL, single-use
sig = ed25519_sign(privkey, "gruper-auth:" ‖ ephemeral ‖ nonce)
POST /v1/auth/token { pubkey, nonce, signature, ephemeral, display_name }
   → verify nonce (consume) → verify ed25519 → find-or-create user → issue_token (HS256, unchanged)
```

Server verification centralizes in `security.py::verify_ed25519` using the `cryptography` package (wheels everywhere, no libsodium build pain). The nonce lives in a **DB table `auth_challenges`**, not process memory — an in-memory dict breaks the moment `DATABASE_URL` points at Postgres with two replicas (challenge issued by A, redeemed against B). Redemption is a `DELETE ... WHERE nonce=$1 AND pubkey=$2 RETURNING expires_at` (atomic single-use on both dialects; SQLite 3.35+ supports `RETURNING`, else `SELECT`+`DELETE` under the single-writer lock). Expiry checked in Python to avoid `NOW()`/`datetime()` divergence.

**Key data model & SQLite-compatible schema.** One migration `005_identity.sql` (both dialects, written to the WP-30 abstraction — `TEXT` for UUID/JSON/timestamps on SQLite, app-supplied `new_id()`/`now_iso()`, no `gen_random_uuid()`/`NOW()` defaults):
- `auth_challenges(nonce TEXT PK, pubkey TEXT, created_at TEXT, expires_at TEXT)` + index on `expires_at`. The only genuinely new table.
- `agents ADD COLUMN key_verified_at TEXT NULL` — additive, no `REFERENCES` (so the SQLite ALTER is legal), set on first successful WS key-proof.
- `users` optionally `ADD COLUMN key_version INTEGER DEFAULT 1` to track legacy-vs-ed25519 keys during the deprecation window.
- `users.pubkey` is unchanged structurally: an ed25519 key is 43 base64url chars, within the existing column. The drift is that the *value* is now a real key.

**Identity / authorization / revocation.** Identity = proof of possession of the private key behind `users.pubkey`. Authorization = derived from `user_id` via the `visible_agent_ids` funnel (§below). Revocation in WP-07 is coarse (rotate the session secret, or refuse new logins); fine-grained per-share revocation is WP-08. The one revocation primitive WP-07 owns: if an agent's key-proof fails on reconnect, the WS register is rejected and the agent stays offline.

**Namespace isolation — one choke-point helper.** Today isolation is ad hoc across `list_agents`, `submit_task`, the console fleet snapshot, and broadcasts. A single `orchestrator/authz.py::visible_agent_ids(db, user_id)` returns the complete set a user may see (WP-07: owned; WP-10: UNION granted). All 13 tenant-scoped surfaces route through it *now*, so WP-10 widens one function atomically. **This helper is under-sized in the drafts** (the feasibility critique flags it): it changes 13 call sites and the 403→404 semantics — real M, not "trivial."

Two isolation rules with teeth:
- **No endpoint returns a PK-looked-up row without a scope predicate.** `GET /agents/{id}` and `/tasks/{id}` must be `WHERE id=$1 AND <scope>` so a non-owner gets an indistinguishable **404**, never a 403 (a 403 confirms existence — an enumeration oracle). **But (simplicity F6) preserve 401 for auth failures** — an expired token must return 401, never collapse into 404, or a solo user whose session lapsed sees a phantom "agent doesn't exist" for an agent in their own sidebar. The 404-not-403 rule applies only to *authenticated-but-unauthorized* cross-tenant access.
- **Broadcasts are scoped by the same helper**, not ad-hoc owner lookups, so a lost grant can't leak an agent's status. WP-07 keeps the owner/submitter split faithfully (they're equal now) so WP-10 can activate cross-owner flows without rewiring.

**Interaction with the sidecar architecture — the solo path stays frictionless.** On a fresh install, `identity.ts` generates the ed25519 keypair, stores the **private key via `tauri-plugin-store`** (app-data dir, same trust zone as `orchestrator.db`; *not* `localStorage`, which is web-exploitable now that the key is a real secret), and logs in via challenge-response automatically. The private-key storage is interface-isolated behind `signChallenge()` so Phase 4 can swap to the OS keychain without touching call sites. Add Agent generates the agent keypair, the console signs the registration with the owner key, and `spawn_local_agent` passes the agent key + `OWNER_USER_ID` in env — zero new user-facing steps.

**Agent identity binding.** Two gaps: registration trusts the session not a signature (a stolen JWT lets an attacker register agents), and WS connect proves nothing about the agent's key (impersonation). Fix: the owner signs the agent registration (`owner_signature` over `"gruper-agent-register:" ‖ agent_pubkey ‖ owner_pubkey`, verified against the user's pubkey), and on WS register the agent signs a server-issued nonce with its own key (verified against `agents.pubkey`, sets `key_verified_at`). This slots between the existing owner-match check and `manager.connect()` in `_handle_register`. **MVP-trim option:** if schedule pressure demands, the agent WS key-proof can be a fast-follow *provided* the threat-model note is honest that MVP agent identity is JWT-owner-bound only.

**The upgrade migration nobody can skip.** Existing desktop users have a random pubkey, a `users` row keyed by it, and agents/tasks/events FK-bound to that `users.id`. A naive fresh-keypair-on-launch orphans the entire fleet — a data-loss regression. **Strategy: pubkey re-binding on the same user row** via a narrow `POST /v1/auth/adopt-key`: the console generates the ed25519 key, logs in one last time the legacy way (gated by `ALLOW_LEGACY_PUBKEY_LOGIN`), then `UPDATE users SET pubkey=$new WHERE id=$session_sub` — one row, no FK churn.

The critiques harden this into a crash-safe protocol:
- **Never delete the legacy pubkey until the new key has completed a challenge-response login at least once** (keep both; the legacy key is the recovery anchor).
- **Idempotent adopt-key:** `UPDATE users SET pubkey=$new WHERE id=$sub AND pubkey IN ($old,$new)` — safe to re-run, returns 200.
- **A "migration complete" store sentinel** written only after a post-adopt challenge-response login succeeds; until it exists, always fall back to legacy login and re-attempt.
- **Release-gate:** the populated-DB upgrade test, killed at each step boundary, asserting same `users.id` and zero orphans.

The **deprecation window** (`ALLOW_LEGACY_PUBKEY_LOGIN`) re-opens the exact hole WP-07 closes and lets a signature-less legacy session rebind identity via `adopt-key` (critique M1). Mitigations: **restrict legacy login to loopback only** (the desktop sidecar is `127.0.0.1`); make the flag a **build-time flag physically absent from server builds**, not a runtime setting; require the new key to sign over the *old pubkey* too. Bind the auth challenge to a client ephemeral (echoed on redemption) and rate-limit `/v1/auth/challenge` per pubkey/IP to blunt nonce harvesting and MITM front-running (critique H1) — "TLS assumed" is not enough when the whole point of ed25519 is to not trust the transport.

**Events action-string reconciliation.** Code writes dotted (`agent.connected`); `event.schema.json` enumerates underscore (`agent_registered`). Reconcile toward the schema enum in one PR (code + contract together so the append-only log never mixes forms), add WP-07 events (`user_key_adopted`, `agent_key_verified`, optional `auth_succeeded/failed`), and a test asserting every emitted action ∈ enum. No historical rewrite (append-only; WP-17's chain starts fresh).

**Major risks / open questions / dependencies.** Risks: upgrade data-loss (highest — release-gated test); 3-OS Web-Crypto Ed25519 availability across WebView2/WKWebView/WebKitGTK (feature-detect + `@noble/ed25519` fallback — **the most under-sized item, run a hardware spike in week 1**); private-key storage on Linux (`tauri-plugin-store` now, keychain later); nonce store on multi-replica (DB-backed, comment loudly); the token-confusion and challenge-binding issues above. Open questions: account recovery (`recovery_method` exists, unimplemented — lean defer); agent key custody (ephemeral vs persisted — recommend ephemeral for WP-07); deprecation-window length (a policy call that **must be decided in week 1** or the migration is unschedulable). Dependencies: WP-30 (done), `cryptography`, `tauri-plugin-store`; WP-07 must land *first* and land the `visible_agent_ids` helper even though it only implements the owned branch.

**Suggested order:** (1) events reconciliation PR; (2) migration `005_identity`; (3) `verify_ed25519` + nonce helpers (pure, test with known vectors); (4) `/v1/auth/challenge` + upgraded `/token` behind the flag; (5) `visible_agent_ids` + refactor all sites (owned-only, no behavior change); (6) agent WS key-proof + owner-signed registration; (7) console `identity.ts` + rewire login + agent-key plumbing; (8) the re-key upgrade flow, tested against a real populated DB as a release gate; (9) flip `ALLOW_LEGACY_PUBKEY_LOGIN=false` in gd-0.3. Steps 1–5 are low-risk and independently shippable; 6–8 are the coordinated crypto surface.

---

### WP-08 — Share Token System

**Organizing principle.** The share-token contract is fully specified; the runtime is empty (no table, no endpoints, no verification hook, and — the load-bearing gap — no orchestrator→agent abort channel; `ws_client.py` ignores unknown frames at line 166). One principle dictates every choice:

> **The database row is the sole authority. The token string is a bearer credential that names a row; it never carries authorization state.**

Everything scoped/quota'd/revocable lives in `share_tokens`, looked up fresh on every dispatch, changeable the instant a write lands. A self-describing token that embedded its own scopes could not be revoked without a blocklist — which is the DB row by another name. "No grace period" is only achievable when the authority is a mutable row read on the critical path.

**Key data model & SQLite-compatible schema.** Migration `005_share_tokens.sql` (both dialects; `UUID→TEXT`, `JSONB→TEXT`, `TIMESTAMPTZ→TEXT`, `BOOLEAN→INTEGER`; `id`/`created_at` from `new_id()`/`now_iso()`, never DB functions):

```sql
CREATE TABLE share_tokens (
  id UUID PRIMARY KEY, created_by UUID NOT NULL REFERENCES users(id),
  grantee_user_id UUID NOT NULL REFERENCES users(id),
  scopes JSONB NOT NULL DEFAULT '[]', quotas JSONB NOT NULL DEFAULT '{}',
  conditions JSONB NOT NULL DEFAULT '{}',
  result_visibility TEXT NOT NULL DEFAULT 'output_only'
    CHECK (result_visibility IN ('full','output_only','none')),
  expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,          -- derived CACHE, never trusted alone
  import_count INTEGER NOT NULL DEFAULT 0,
  tasks_used INTEGER NOT NULL DEFAULT 0,            -- enforcement counter for max_tasks_total
  last_used_at TIMESTAMPTZ,
  parent_token_id UUID NULL REFERENCES share_tokens(id)  -- reserved for WP-11 delegation
);
CREATE TABLE share_token_agents (                   -- normalized join, not JSON array
  share_token_id UUID NOT NULL REFERENCES share_tokens(id) ON DELETE CASCADE,
  agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  PRIMARY KEY (share_token_id, agent_id)
);
CREATE INDEX idx_share_tokens_grantee_active ON share_tokens(grantee_user_id) WHERE is_active;
CREATE INDEX idx_share_tokens_owner ON share_tokens(created_by);
CREATE INDEX idx_sta_agent ON share_token_agents(agent_id);
CREATE INDEX idx_tasks_share_token_active ON tasks(share_token_id) WHERE status IN ('dispatched','running');
```

Design choices: **normalized `share_token_agents`** (not a JSON array) because the fleet-visibility query "which agents can grantee G see?" is a full scan + JSON-membership with an array but one indexed lookup with a join, and it gives referential integrity via `ON DELETE CASCADE`. `scopes`/`quotas`/`conditions` stay JSON (read as a unit; add them to `db/sqlite.py::_JSON_COLUMNS` or reads return raw `str` — a silent-failure one-liner). `tasks_used` is a real dispatch counter (the contract's `import_count` is informational). `is_active` is a *cache* for narrow partial indexes; the dispatch check re-evaluates `revoked_at`/`expires_at` live, since a token expires by the clock with no write.

**Critical SQLite constraint (simplicity F2/F3):** the FK columns above are in `CREATE TABLE`, which is legal. Do **not** add an FK to the pre-existing `tasks.share_token_id` via `ALTER` (SQLite rejects `ADD COLUMN ... REFERENCES`) — leave it FK-less TEXT (app-enforced) and add only the partial index. Keep SQLite migrations single-statement-per-`;` with **no triggers / no `BEGIN...END`** (the migration runner splits on `;`); push `is_active` aging and revocation sweeps into the Python app layer.

**Token string.** A compact HS256 JWT minted by `POST /v1/tokens`, claims `{sub: grantee_user_id, jti: row.id, iss, typ:"share", iat, exp}` — the whole token; no scopes/quotas/agents embedded. **Signing-key decision (folding critiques C1/C2):** it must NOT reuse the session secret with the type-blind `verify_token`, or a share JWT becomes a session token by confusion. Enforce `typ`/`aud` on every decode via `verify_token(token, *, expected_typ="share")`, and — the strong recommendation — **sign grants with the owner's ed25519 key** (available from WP-07). That gives token-class separation *and* makes WP-09's agent check genuinely independent of a malicious orchestrator a phase before WP-16. An owner `owner_sig` over `(jti, grantee, sorted(agent_ids), scopes, expires_at)` is captured for non-repudiation.

**Endpoints** (new `routers/tokens.py`, all via `get_current_user_id`):
- `POST /v1/tokens` (mint, owner) — validate fail-fast: `expires_at` ≤ created_at+90d; `agent_ids` valid; **ownership** (`COUNT(*) WHERE id=ANY($ids) AND owner_id=$caller` = `len`, else 403 without leaking which); `grantee != caller`; `scopes ⊆` enum (excludes `execute_arbitrary`/`email_external`); fill defaults server-side. INSERT parent + N join rows in one transaction, mint JWT, `append_event("token_minted")`, return `token_string` **once**.
- `GET /v1/tokens` (list) — union of `created_by=me` and `grantee_user_id=me`, `token_string` always null, grantee sees a redacted projection (not the owner's other grants).
- `POST /v1/tokens/import` (grantee) — verify `typ=="share"`, `sub==caller`, active; `import_count += 1`.
- `DELETE /v1/tokens/{id}` (revoke, owner-only) — `UPDATE ... SET revoked_at=$now, is_active=FALSE WHERE id AND created_by=$caller AND revoked_at IS NULL RETURNING id`; then `append_event("token_revoked")` and **fire the in-flight abort sweep synchronously** so the response returns only after the kill order is on the wire.

Use the schema's **underscore** action forms on all new events to stop the drift.

**Verification on every dispatch.** A single `authorize_dispatch(db, agent_row, submitter_id, requested)` called from both `submit_task` and the reconnect drain. **First line is the solo short-circuit** — `if agent_row.owner_id == submitter_id: return ALLOW` — touching no token table, no `visible_agent_ids`. The cross-owner branch, cheapest-fail-first: (1) token row exists; (2) `grantee==submitter`; (3) `revoked_at IS NULL`; (4) `expires_at>now` (live, not `is_active`); (5) agent ∈ join table; (6) `task.scopes ⊆ token.scopes`; (7) `data_class ∈ allowed_data_classes`; (8) time-window; (9) jurisdiction; (10) quotas. Two point reads + one aggregate, O(1)-ish. Effective timeout = `min(task.timeout_s, max_wall_time_s)` (clamp down only). On success, **stamp `tasks.share_token_id`** so the row self-identifies for the sweep and result-visibility routing. **The reconnect drain is not exempt** — a token can be revoked while its task sits pending for an offline agent, so the drain re-runs authorization and dead-letters tasks whose token died.

**Revocation semantics — the honest hard part.** Split the guarantee:
- **(a) Stop new dispatch — trivial.** Once `revoked_at` is set, checks 3/4 fail. No new machinery.
- **(b) Abort in-flight — genuinely hard, plumbing must be built.** New frame `{type:"task_abort", task_id, reason}` sent via `ConnectionManager.send_json`. Agent handler cancels `self._in_flight[task_id]`. **The load-bearing hazard (confirmed at `ws_client.py:226`): the `CancelledError` branch re-enqueues unconditionally**, so a naive abort *resurrects the revoked task on reconnect* — a security hole. Gate the re-enqueue on an `_aborted` set (reconciled with WP-09 to **one** set name), cleaned in a `finally`. A **revocation sweep** in `main.py` (folded into the heartbeat loop) uses `idx_tasks_share_token_active` to find in-flight cross-owner tasks whose token is revoked/expired and re-sends abort; the DELETE handler fires it synchronously for immediacy, and the sweep backstops clock-expiry.

**The honest guarantee (critique C3), stated to the owner:** a non-cooperating or malicious agent can ignore the abort frame — re-sending it is no backstop. So the real guarantee is **new-dispatch stops immediately; in-flight is best-effort-cancelled AND its result is server-side refused** (the orchestrator dead-letters any result whose `share_token_id` is revoked/expired, regardless of agent compliance), **bounded by `max_wall_time_s`**. Revocation stops future work and cancels in-progress generation and suppresses the result; it does not retroactively unwind a computation that already completed. Cryptographic non-execution needs WP-15. Say this plainly.

**Quota enforcement (at enqueue; breach → 429).** `max_concurrent_tasks` (default 2), `max_tasks_total` (auto-revoke on exhaustion), `max_wall_time_s` (clamp). **`max_ram_gb_per_task` is unenforceable in Phase 2 — store, surface, do not claim enforcement** (needs cgroups/WP-15). **The concurrency check must be atomic (critique H2):** COUNT-then-INSERT is unsafe on Postgres READ COMMITTED — a manager loop or a burst of two submits both read count=1 and both pass a limit of 2. Use a per-token counter CAS — `UPDATE ... SET active=active+1 WHERE active<max RETURNING` (dialect-clean, atomic on both) — not COUNT-then-write. A concurrency stress test is a merge gate.

**Auditability.** `token_minted/imported/used/revoked` (underscore forms; `token_used` on first dispatch, not every one). Hash-chaining deferred to WP-17 — WP-08 writes well-formed entries. Label the surface "operational, not tamper-evident until WP-17."

**Major risks / open questions / dependencies.** Risks: abort is best-effort (C3); `max_ram` inert; time-window tz/DST fragility (H3 — single shared evaluator, **fail-closed everywhere**, require explicit IANA tz at mint, evaluate against one authoritative clock, DST fixtures); `token_used` granularity; result-visibility routing intersecting the progress/complete broadcast split (for cross-owner the grantee is submitter and owner is someone else — `output_only` strips progress detail, `none` withholds output; a real change in `_handle_progress/_handle_result`); the concurrency race (H2). **Client-side gates are UX, not security (M4):** every disabled dropdown / hidden field needs a server-side rejection test that bypasses the UI, and the reconnect-drain re-check is a named merge gate. Dependencies: WP-07 (a token to a spoofable grantee is a token to nobody). Idempotency: keep the existing `UNIQUE(submitter_id, correlation_id)` exactly — **do not add `share_token_id` to the idempotency key** (F7), or solo dedup semantics change.

**Order:** (1) migration + `_JSON_COLUMNS` + `tasks.share_token_id` index only; (2) `authorize_dispatch` with solo short-circuit (a no-op for existing users); (3) mint/list/import/revoke + audit; (4) `task_abort` frame + agent handler + the re-enqueue gate; (5) revocation/expiry sweep + reconnect re-check + server-side result suppression; (6) quota CAS + auto-revoke. Steps 1–2 are pure infrastructure with zero user-visible change.

---

### WP-09 — Agent Runtime — Cross-Owner Dispatch (defense in depth)

**Thesis.** Today the agent is a trusting appliance: `_dispatch` accepts a `task_push` and runs it, with no notion of *who asked* or *under what authority* — safe only because upstream, submitter always equals owner. WP-08 breaks that. The moment `submitter_id != owner_id` is possible, a single upstream bug converts into "a stranger runs prompts on your hardware." WP-09 makes that require **two independent failures** — the orchestrator must wrongly dispatch *and* the agent must wrongly accept.

**Honest scope boundary (folding critique C2).** The orchestrator is the transport for every frame the agent sees, and in Phase 2 grants are signed with a secret the orchestrator holds — so a malicious orchestrator can forge a valid-looking grant, and the agent's check is *redundant with*, not *independent of*, the orchestrator for the malicious case. **WP-09 does not defend against a hostile orchestrator in Phase 2; it defends against a buggy/over-eager one.** The drafts' "short TTL is a cryptographic guarantee / full independence" language is wrong and is removed: a re-minting signer defeats TTL trivially; TTL only bounds replay of a *leaked honest* grant. The single pre-WP-16 path to real independence is **signing grants with the owner's ed25519 key** (WP-07 already ships the keypair) — adopt it, and the agent check becomes genuine. Cross-owner stays behind `cross_owner_enabled=False` (default) regardless, per the Phase-4 hard gate.

**Local grant verification.** For cross-owner tasks the `task_push` frame carries a `grant` (the compact JWT + a *untrusted* decoded preview for logging). A new pure, synchronous `agent-runtime/grant_verifier.py::verify_dispatch` runs a gate **before** `task_ack` (so a rejected task never spawns an `asyncio.Task` or acks): fast-path return if `submitter==owner`; else verify signature (the single swap point for WP-16), grantee binding, `agent_id ∈ agent_ids`, owner binding, expiry (own clock, bounded skew ≤60s — never let the orchestrator set agent time), local revocation, `required_scopes ⊆ granted`, data-class ceiling, jurisdiction, time-window. On rejection the agent sends a structured `failed` result (`grant_<code>`) rather than silently dropping (which would look like a network hiccup) and records a local audit event. **Dependency on WP-08:** the orchestrator currently accepts results only for `running` tasks; a pre-ack rejection sends `failed` for a `dispatched` task, so WP-08 must relax that specific transition for grant-rejections.

**New config the agent must learn.** `owner_user_id`, `grant_verify_key`, `jurisdiction`, `cross_owner_enabled` (default False). Delivered in the `registered` response and threaded via `spawn_local_agent` env (three more `.env()` calls). When `cross_owner_enabled=False`, any `submitter != owner` task is rejected `grant_disabled` — the plumbing ships dormant behind a flag, the safest rollout for the highest-risk feature.

**Revocation learning (three layers, ship A+B).** (A) short grant TTL (≤15 min effective, 5 min for `confidential`) as the *ceiling*; (B) an orchestrator `grant_revoked` frame → local `RevocationCache` (in-memory + `agent.db`) that also cancels matching in-flight tasks, the fast path for the honest case. (C) an owner-signed revocation list is **WP-16 only** — in Phase 2 it would be signed with the same shared secret, adding a distribution mechanism for zero independence (security theater). TTL is the honest security knob and trades revocation-ceiling against re-mint churn.

**Abort handling — the `task_abort` frame.** Plumbing is 90% present (`_in_flight` tracks the `asyncio.Task`). The critical difference from graceful shutdown: today's `CancelledError` branch **re-enqueues for retry** (`ws_client.py:226`); an aborted cross-owner task must **not** be retried and its partials discarded. **Reconcile WP-08 and WP-09 into ONE `_aborted` set** (the drafts used two names — a merge hazard); the branch: `if task_id in self._aborted: discard partials, no enqueue, no result; else existing enqueue unchanged`. Clean the marker in `finally`. Guarantee idempotency (a second abort is a no-op) and race-safety (abort vs. natural completion). **Gate the orchestrator's abort *send* on `submitter != owner`** so a solo task can never receive an abort frame (belt-and-suspenders, protects the solo retry path — F5).

**Per-task isolation — DEFERRED from MVP.** The workspace context manager (fresh cleaned dir for cross-owner tasks, resource *hints* only) is a seam for WP-15 with nothing to isolate yet (tasks are prompt→text). Build it when WP-15 lands. Be honest: on Windows/macOS pre-WP-15, "isolation" is a temp dir + cooperative timeout, not enforcement.

**Install UX (QR/registration token) — CUT from MVP.** The registration-grant token solves credential handoff and **nothing about reachability**: the desktop orchestrator is loopback-only (`127.0.0.1:8080`), so a second machine cannot connect without the server tier or a tunnel, and `wss://localhost` self-signed won't validate cross-machine. The "30-second onboarding" is a one-LAN lab demo, not a shippable claim. If demoed, label it "requires server tier or tunnel." (If built later, the `reg_grant` JWT needs its own signing key/`typ` enforcement per C1 and atomic single-use `jti` burn per the nonce pattern — L2.)

**Sidecar interaction.** Env-passing, per-agent data dirs, and the `GRUPER_EXIT_WITH_PARENT` orphan watchdog already exist — WP-09 adds three env vars and no new Tauri command/capability (the agent is privileged only at the orchestrator layer). Grant tokens must be redaction-enforced in logs (a manager/grantee-scoped grant leaking is the principal). **Grant-decision events must be auditable, but the only agent log surface today is invisible `eprintln!`** — persist decisions to an `agent.db` `grant_events` table so the owner can audit them (a hard dependency on the §1 log surface).

**Risks / dependencies.** R1 shared-secret ≠ independence (state honestly; owner-key signing closes it). R2 pre-ack `failed` needs WP-08 transition relaxation. R3 agent doesn't know its owner/jurisdiction/key (config + registration + env). R4 TTL trades security for churn. R5 clock skew (bounded). R6 "isolation" is cooperative on Win/mac (deferred anyway). R7 cross-machine needs a reachable orchestrator. R8 grant-decision audit depends on the log surface. Upstream: WP-07 (identity), WP-08 (`task_abort`/`grant_revoked` frames, grant-in-dispatch, relaxed result transition). Forward: WP-15 (sandbox seam), WP-16 (swap the verify function).

**Order:** (1) `grant_verifier.py` pure + table-tested against forged/expired/mismatched/out-of-scope grants; (2) config plumbing; (3) wire the gate into `_dispatch` behind the flag (regression-test the same-owner path unchanged); (4) abort handling + the non-re-enqueue fork + idempotency/race tests (useful even before cross-owner, for owner-cancel); (5) revocation cache + `grant_revoked`; (6) grant-event audit persistence. **Cut for MVP:** workspace isolation, QR install.

The invariant throughout: **the orchestrator checks AND the agent checks, and neither trusts the other.** Cross-owner ships only when both locks are proven, and even then behind `cross_owner_enabled=False` until Phase 4 makes the agent's check independent rather than merely redundant.

---

### WP-10 — Console — Sharing Panel & Full Fleet View

**Framing and the honest tension.** WP-10 is the entire human surface of sharing; everything WP-07/08 build is invisible until it renders. Its success criterion — a collaborator reaches a first task result quickly — is almost entirely a WP-10 problem. The tension: **the solo user is the majority and must never pay a sharing tax.** The resolving principle is **progressive disclosure** — a user with zero grants sees *nothing new*; the sharing surface materializes only when they open the panel or import a token. Note the fleet store today has **no ownership axis** (`Agent` carries `owner_id` but nothing reads it); WP-10 is where ownership becomes a first-class rendered concept — changing what actions each `AgentCard` offers, what `TaskComposer` submits, and what `ResultView` shows.

**Data model (types.ts).** Add `ShareToken` mirroring the contract exactly (so JWT payload, REST response, and TS type are one shape), plus `ShareScope`, `ResultVisibility`, `TokenQuotas`, `TokenConditions`, `MintTokenRequest`, `MintResult` (with the once-only `token_string`). Add a client-derived `relationship: 'owned'|'shared'` to `Agent` (computed from `owner_id` vs `auth.userId` — no server field needed) and a server-provided `grant?: SharedAgentGrant` (scopes/visibility/data-classes/quotas/expiry — the *authoritative enforcement contract*, must not be guessed client-side or the UI lies).

**API client (client.ts).** `mintToken`, `listTokens`, `revokeToken`, `importToken` (returns the now-visible `Agent[]` so import+resolve is one round-trip), `listAgentEvents` (owner audit — deferred). `listAgents` gains shared-in agents + `grant` (server-side). `_fetch` already surfaces `${status} ${text}`.

**Field-level redaction (critique M2).** The grant governs *dispatch*, but the fleet listing exposes agent metadata (models, hardware, jurisdiction, location_tag, capabilities). A narrow-scope grantee should not see the full inventory. Define a **grantee projection** enforced server-side in `list_agents` (name + online status + granted scopes only; strip hardware/location/full model list unless a jurisdiction condition needs it). `visible_agent_ids` is necessary but not sufficient — field-level redaction per relationship is also required.

**Fleet overview.** `fleetStore` gains `mergeShared` (dedupe by id, tag `shared`) and `removeShared`. Relationship is tagged in `+page.svelte` where `auth.userId` is in scope, before `setSnapshot`. **Live revocation for the grantee** requires WP-08 to emit a grantee-scoped `fleet_event` (`grant_revoked`/`grant_expired`) → `removeShared`; without it, a grantee keeps a dead agent card until reload. Rendering extends the *existing* `w-56` sidebar (not a new pane): a "shared · limited" badge on `AgentCard` (with a hover grant summary), the ✕ remove button suppressed for shared agents, and a "Shared with you" subheader **omitted entirely when empty** so the solo view is byte-identical.

**Sharing Panel (new `SharingPanel.svelte`, modal, not a fourth pane).** Reached via a tucked `[Share]` header affordance (gated so a never-sharing solo user's header is unchanged — F11). Two tabs. **Mint** is opinionated toward safe defaults (three-click common grant; quotas/time-windows/jurisdiction under a collapsed "Advanced"), mintable agents filtered to *owned only*, 90-day cap enforced client-side. **The mint-result screen is the most important UX moment** — `token_string` is returned once and unrecoverable, so swap the form for a "grant created" panel with the token in monospace, Copy + Download + (fast-follow) QR, and a blunt one-time warning. **Active Grants** lists via `listTokens()` (backed by a small `stores/tokens.ts`), each with a confirm-gated Revoke (destructive — aborts in-flight per spec).

**Import UX (grantee) — the SC-1 critical path.** Lives as a third mode inside `AddAgentDialog` (importing a shared agent *is* "adding an agent" — no new top-level control). Paste/scan → `importToken` → `mergeShared` → auto-select → composer ready. A pre-import decode-then-explain preview (pure client-side base64 of the JWT payload, no network) lets the grantee consent knowingly and catches truncated pastes.

**Shared-agent gating (render only what's permitted).** `TaskComposer`: scopes → tool/role filtering; data-class selector clamped to `allowed_data_classes`; wall-time hint = `min(user, quota)`; concurrency guard disables Submit at the quota. `ResultView`: `full` shows everything, `output_only` (default) shows final output only, `none` shows a status chip. **Client hiding is UX, not security** — the authoritative filter is WP-08 not *transmitting* hidden fields; annotate this in code and back every client gate with a server-side bypass test (M4).

**Owner audit trail — DEFERRED from MVP.** `GET /v1/events?agent_id=` authorizes owner-only by joining `events.subject_id → agents.owner_id` (events carry no owner column, so this join **is** the entire security boundary — the highest-severity surface in an otherwise cosmetic packet; a bug leaks one owner's history to another). `AgentAuditLog.svelte` renders it, gated to owned agents with active grants, tolerating both dotted and underscore action forms via a normalizer. Valuable but not MVP — defer with the per-grantee analytics.

**Per-grantee analytics — DEFERRED.** Owner-side per-grantee volume/quota gauges need the audit feed (task events broadcast to *submitter*, and for cross-owner the owner isn't the submitter), so this is poll-on-open unless WP-08 adds an owner fan-out — a WP-08 decision not forced from the console. Defer.

**Major risks / open questions / dependencies.** Hard deps: WP-07 (a stable resolvable grantee identity — until then "Grant to" is a raw uuid/pubkey paste), WP-08 endpoints + the extended `GET /v1/agents` + grantee-scoped WS events. Open questions (owner's call): **how is a grantee identified at mint** (uuid paste is error-prone — recommend an invite-bound flow where the owner mints against an invite code the grantee derived from their key, per critique H1, before cross-owner ships); result-visibility enforcement is server-side (sign-off needed); owner-sees-grantee-results-live (a WP-08 fan-out decision); QR now vs fast-follow; action-string drift reconciliation before beta. The audit-authorization join deserves a dedicated test and security review.

**Order (each demoable, solo path never broken):** (1) types + client (unblocks all, mergeable behind stubs); (2) fleet tagging + badges (validates "no solo regression" first — badge just never appears solo); (3) **import UX** (delivers the SC-1 grantee path end-to-end — highest value, prioritize); (4) SharingPanel Mint + tokens store + mint-result screen; (5) Active Grants + Revoke; (6) shared-agent gating in composer/result. **Deferred to fast-follow/Phase-2.5:** (7) owner audit log + endpoint; (8) per-grantee analytics. Steps 1–3 are the SC-1 slice and should be one reviewable increment.

---

### WP-11 — Manager Agent Delegation

**Why this packet is different — and the verdict.** Every other packet has a human at the top of every authorization decision. WP-11 removes the human from the inner loop: a Manager Agent (a process, possibly running a jailbroken LLM) receives a goal, decomposes it, and *itself* dispatches sub-tasks across ownership boundaries. The security model must survive an actor that loops, retries, and probes the authorization boundary far faster and more systematically than any human. The core invariant is not "the manager does the right thing" but **the manager physically cannot dispatch anything its principal could not have dispatched by hand** — a convenience over the principal's authority, never an amplifier.

**Verdict: defer the LLM manager; WP-11 is NOT in the MVP.** It is the highest-complexity, highest-blast-radius packet, most entangled with Phase-4-gated features. Cross-owner is already gated out of beta until Phase 4; a *loop* doing cross-owner dispatch inherits all of WP-15/16/17 and adds an autonomous decision-maker inside the trust boundary. It hard-depends on WP-07/08/09/10 being *finished and hardened*, not merely present — it cannot be correct before WP-08's verify path is correct. **The feasibility critique is decisive that even the "static decomposer" is a trap:** it still requires `parent_token_id`, child-grant minting, `assert_subset` + property tests, the adversarial `escalation-attempt-rejected` suite on both dialects, and revocation-subtree cascade — most of WP-08's hardest surface plus a new one. **Land only the dormant `parent_token_id` column (already in WP-08's `005`) and the `delegation_created/dispatched/complete` event names.** The design below is how to do it right when it *is* scheduled (Phase 4), written so the static-manager slice is a strict subset.

**Task type + scope budget.** A manager task is an ordinary `tasks` row with `input._type: "manager_agent"`, a `goal`, a `budget_grant_id`, `max_subtasks` (fuel), `max_depth` (1 for any first version — no nested managers), and an `aggregation` mode. **The budget IS an attenuated WP-08 `ShareToken`**, not a new concept — `grantee_user_id` = the principal, every field a strict attenuation of the principal's authority. This is the single most important decision: the budget and a normal grant are the same object, so the manager's dispatches flow through the *exact same verify path*, avoiding a second authorization code path where escalation bugs live. Attenuation is monotone: every child field ≤ parent under a partial order (subset for sets, ≤ for scalars, future ≤ parent expiry). If that holds at mint *and* re-checked at dispatch, self-escalation is structurally impossible.

**DB-derived child grants, not macaroons.** Gruper is desktop-first, single-orchestrator — the orchestrator is always on the request path, so macaroons' offline-attenuation value evaporates, biscuits are hard to revoke (the contract demands instant revocation), and a DB row per child grant *is* the audit record. The trade-off (a DB write per mint, a PK read per verify) is negligible on an already-serialized SQLite path. Child minting (`POST /v1/grants` with `parent_token_id`) computes the child server-side as `min(requested, parent)` field-by-field and **rejects (fail-closed, loud) any superset request** rather than silently clamping.

**The manager loop and where the check lives.** The manager runs inside the agent-runtime as a specialization of the task handler; instead of a final answer it produces a *plan* and submits each sub-task **back through the same `POST /v1/tasks`** carrying the budget grant — no privileged endpoint. The only change to `submit_task` is that the owner-only gate becomes *own-the-agent OR hold-a-covering-grant* (which WP-08 already introduces for human grantees), and WP-11 adds **one predicate** guarded by `parent_token_id`: `assert_subset(child, parent)` — a small, total, pure comparison, property-tested (fuzz random parent/child pairs, assert child⊆parent ⇔ accept). Defense-in-depth on the agent too: the leaf refuses any tool outside the delivered scope.

**Delegation chain and audit.** `tasks.parent_task_id` (self-FK) and `share_token_id` already exist — no task-schema migration. Each sub-task sets `parent_task_id` (task tree), `share_token_id` (authority tree), and a `delegated_from` = manager agent id. Emit `delegation_created/dispatched/complete` (underscore forms, born correct). A recursive CTE reconstructs the complete delegation-of-authority provenance of any leaf result — the compliance artifact the schema was designed for, though **not tamper-evident until WP-17** (label it operational). Aggregation: ship `concatenate` (deterministic, no second LLM call); `reduce` (a synthesis LLM pass) is Phase 4+. Partial failure is first-class (`partial: true` with per-child status).

**Ancestor-chain liveness (critique H5).** At dispatch, verify the **entire ancestor chain is live** (a single recursive CTE: reject if any ancestor has `revoked_at` set or `expires_at<=now`), not just the leaf grant's lazy `is_active` cache — otherwise a child whose parent was revoked but whose own cache wasn't swept yet authorizes a dispatch. The revoke-subtree and the dispatch-liveness check must **share the same recursive query** so they cannot diverge. Keep `max_depth=1` until the chain checks are property-tested.

**Revocation propagation.** Revoking a parent grant kills every descendant via a `WITH RECURSIVE` subtree `UPDATE ... SET revoked_at, is_active=0` — the payoff for DB grants over biscuits. In-flight children reuse WP-08's abort frame (WP-11 invents no abort mechanism — if WP-08's abort isn't done and tested, WP-11 has no revocation story and cannot ship).

**The adversarial acceptance test `escalation-attempt-rejected`** models the manager as *actively hostile* (a jailbroken LLM is exactly that): wider agent set, foreign agent, scope escalation, data-class escalation, quota escalation, broader child-mint — each a **hard reject at the orchestrator AND an independent reject at the agent**, each writing an audit event (a silent reject fails the test). Plus: no self-escalation via re-mint loop, fuel exhaustion at `max_subtasks+1`, and a **concurrency stress sub-case** firing N simultaneous sub-dispatches asserting at most `max_concurrent_tasks` ever run (the SQLite-vs-Postgres race from WP-08 H2). Runs on both dialects.

**Identity/authz/revocation & sidecar.** The manager authenticates as its *principal* carrying the budget grant — no elevated identity. A leaked manager token *is* the principal, so WP-11 hard-depends on WP-07/WP-16 real key-bound identity (a second reason it's post-Phase-4). Planner output is **untrusted**: a strict validating parser; parse failure ⇒ `delegation_created` never emitted ⇒ nothing dispatched (fail-closed at the planner boundary, L4). The manager is a mode of the existing agent-runtime spawned by the existing `spawn_local_agent` (roles: ["manager"]) — no new Tauri command/capability.

**Risks / dependencies.** All of WP-07/08/09/10 *done and hardened*, plus realistically WP-15/16. Ship **intra-owner delegation first** (manager among the principal's *own* agents — same machinery, zero cross-owner exposure, still useful). Escalation reduces entirely to `assert_subset` + `authorize_dispatch` correctness (one funnel, property-tested). Open: nested managers (hard-cap `max_depth=1` well past MVP); whether `derived_scope` is manager-declared or orchestrator-inferred from `allowed_tools` (inferring is safer; needs a canonical tool→scope map — a WP-08 decision).

**Order (when scheduled, Phase 4):** (1) `parent_token_id` + child-mint with fail-closed attenuation; (2) `assert_subset` + property tests in isolation; (3) fold the predicate into `authorize_dispatch`; (4) `delegation_*` events; (5) static decomposer + sidecar sub-task submission; (6) `concatenate` aggregation; (7) the adversarial suite on both dialects; (8) revocation-subtree + reuse the abort path + ancestor-liveness CTE; (9) console delegation-tree view; (10) swap in the LLM planner behind the `decompose(goal) -> list[SubTaskSpec]` interface, gated behind sandboxing. Build the cage first; put the animal in it last.

---

## 5. Recommended Next Steps

The plan's engineering is strong and its sequencing instinct (harden → identity → narrow sharing) is right, but the calendar in the drafts is optimistic by ~40–60% for a very small team. Present Phase 2 honestly as **~7–9 weeks** (2–3 hardening + 5–6 sharing) behind a "trusted-parties technical preview" flag, or hold a 4–6 week ceiling only by cutting WP-09 install UX, WP-10 audit/analytics, and WP-11 in all forms (as this plan does). Three items are materially under-sized and are called out below: the 3-OS ed25519/webview spike (biggest), the `visible_agent_ids` funnel + 403→404 change, and the `task_abort` channel three packets assume already exists.

### Next 1–3 weeks — Desktop Hardening + identity spike

Build the instrument panel and the UI shell sharing will hang off, and de-risk the crypto before committing WP-07's schedule.

1. **Debug-logging MVP slice** — the prerequisite for everything. Python JSON lines → Rust ring buffer → `get_logs`/`export_logs` → read-only panel, with **sink redaction + emit-site allowlist** (non-negotiable). This turns every future sharing bug and user report from "unobservable" to "one Export away."
2. **ResultView fixes** — markdown (`marked`+`DOMPurify`, statically bundled with a plaintext fallback), copy button, fetch-error state. Ship day one; also a real XSS hardening.
3. **ed25519 3-OS webview spike** — Web-Crypto `Ed25519` availability across WebView2/WKWebView/WebKitGTK, `@noble` fallback, `tauri-plugin-store` keygen/persist, degrade path. **Run on real hardware** (the Ollama-PNA history proves this class of surprise is real); its outcome sizes all of WP-07.
4. **Layout rework** — master/detail center + composer modal. The shell WP-10 hangs off; do it before sharing, not after.
5. **Resolve the blocking policy questions** — legacy-login deprecation window; how a grantee is identified at mint (uuid vs invite code); result-visibility enforcement boundary. Cheap to decide, expensive to leave open, and the WP-07 migration and WP-10 mint form are unschedulable until they are.
6. **Header status indicator + Ctrl-Enter submit** — cheap, high perceived quality; `wsStatus` from the socket's existing lifecycle handlers (never inferred from agent status).

The model picker (§2.1) is genuinely useful but **not on the sharing critical path** — slot it into week-2/3 slack.

### Following 4–6 weeks — the flagged Phase-2 MVP vertical slice

> **One owner mints a scoped, expiring, revocable token for one agent to one grantee; the grantee pastes it, sees the agent, submits one scoped task; the owner revokes and new dispatch stops — all observable in the debug panel.**

Everything not in this slice is dormant-column or fast-follow. The `task_abort` channel — assumed by WP-08, WP-09, and WP-11 but existing in none — is built **once**, here, as a named deliverable with its own test matrix. The pure-desktop regression suite (§3.3) exists *before* the sharing endpoints merge, as a merge gate on both dialects.

### Phase table (S/M/L sizing; feasibility-critique ordering)

| Wk | Phase | Item | Size |
|----|-------|------|------|
| 1 | Harden | Debug-logging MVP (redaction non-negotiable) | M |
| 1 | Harden | ResultView: markdown + copy + fetch-error | S |
| 1 | Harden (parallel) | ed25519 / 3-OS webview **spike** | M (spike) |
| 1 | Harden | Resolve policy questions (deprecation window, grantee identity, visibility) | S (decisions) |
| 2 | Harden | Layout rework: master/detail + composer modal | M |
| 2–3 | Harden | Header status + Ctrl-Enter; (slack) model picker | S / M |
| 4 | Phase 2 | Events action-string reconciliation (code + schema, one PR) | S |
| 4 | Phase 2 | Migration `005` (auth_challenges + share_tokens, dual-dialect) | M |
| 4–5 | Phase 2 | ed25519 primitives + `/v1/auth/challenge` + upgraded `/token` | M |
| 5 | Phase 2 | `visible_agent_ids` funnel + 13 sites + 401/404 semantics (**under-sized in drafts**) | M |
| 5 | Phase 2 | Pure-desktop regression suite, both dialects (merge gate — exists *before* sharing merges) | M |
| 6 | Phase 2 | Upgrade re-key migration (`adopt-key` + crash-safe console flow); release-gated on populated DB | M–L |
| 6–7 | Phase 2 | `share_tokens` mint/list/revoke/import + `authorize_dispatch` (solo short-circuit) + revocation-stops-dispatch | L |
| 7 | Phase 2 | `task_abort` channel (built once) + agent handler + non-re-enqueue fork + revocation sweep + **server-side result suppression** | M–L |
| 7–8 | Phase 2 | WP-10 trimmed console: types/client/fleet-tagging/import/mint-revoke + composer gating (SC-1 import path first) | L |
| 8 | Phase 2 | WP-09 trimmed: agent-side grant re-check (honest: redundant-not-independent until WP-16) | M |
| — | Deferred | WP-11 (all forms; dormant columns/events only); WP-09 install UX + workspace isolation; WP-10 audit log + per-grantee analytics; full-logging half | — |

If a hard 4–6 week ceiling is imposed, cut the agent re-check (row 8) before the core (rows 6–8 of the sharing block); resist cutting the upgrade migration, since fresh-install-only ships a data-loss trap for existing users.

### De-risking moves, up front

1. **Hardware webview crypto spike in week 1** — the single most under-sized item; its result sizes WP-07.
2. **Real-DB upgrade migration as a release gate** — the highest data-loss risk; never let the console generate a fresh keypair without the crash-safe adopt-key path proven against a copy of a real user DB.
3. **Build the `task_abort` channel once, early, as an explicit deliverable** — three packets "reuse" a mechanism none of them has; feature-flag it on before WP-08 claims any revocation guarantee.
4. **Feature-flag cross-owner off (`cross_owner_enabled=false`) until Phase 4**, and keep the "trusted-parties technical preview, not production-safe" framing — the identity gap (Risk 1) and the absence of sandboxing/E2E (Risk 9) make any stronger claim dishonest. The single highest-leverage security change, worth pulling into this window: give share/budget/registration grants their own signing key (ideally the owner's ed25519 key WP-07 already introduces) and enforce `typ`/`aud` on every decode — closing the token-confusion bypass and making the agent's check genuinely independent a full phase before WP-16.