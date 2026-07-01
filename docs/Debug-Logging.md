# Debug Logging System

*Desktop Hardening — added ahead of Phase 2 (gd-0.3). See `docs/Phase2-gd-0.3-Plan.md` §1.*

Gruper spans four processes — the Rust/Tauri Console, two Python sidecars
(orchestrator + agent-runtime), and the Svelte frontend. Before this system,
each logged somewhere the user could not see: the Rust side and the drained
sidecar output went to `eprintln!` (a stderr nobody reads in a packaged app),
and the frontend to a closed WebView devtools console. The hard flows —
**sidecar spawn**, **agent registration**, and (soon) **cross-owner dispatch +
revocation** — each straddle *all four* tiers, so no single surface could tell
their story.

This system unifies them into **one in-memory ring buffer in the Rust process**,
viewable, filterable, copyable, and exportable from the Console's **Debug**
panel.

## Architecture

```
 orchestrator sidecar ─┐  JSON lines on stdout (sentinel-prefixed)
 agent sidecar(s) ─────┤─────────────────────────────►┌────────────────────┐
                       │  (drained + parsed by lib.rs) │  RUST RING BUFFER   │
 Rust / Tauri ─────────┤  rust_log()                   │  VecDeque<LogEntry> │──► get_logs()  (backfill)
 Svelte frontend ──────┘  invoke("push_log", …)        │  cap 5000, redacted │──► "log-entry" (live tail)
                                                        └────────────────────┘
                                                                 │
                                                        DebugPanel.svelte (filter / copy / export)
```

Rust is the sink because it is the only process alive for the whole session,
already owns the sidecar stdout pipes, and can serve both a command (`get_logs`)
and a live event (`log-entry`) to the frontend.

### The `LogEntry` contract

Every tier emits the same shape:

| field | notes |
|---|---|
| `ts` | ISO-8601 UTC, millisecond precision |
| `level` | `debug` \| `info` \| `warn` \| `error` |
| `category` | `orchestrator`, `agent`, `sidecar`, `auth`, `task`, `ui`, `ws`, `ollama`, `error`, … |
| `tier` | which process emitted it: `orchestrator` \| `agent` \| `rust` \| `frontend` |
| `agent_id` | correlation id (nullable) — a **promoted** field, so you can filter one agent across tiers |
| `task_id` | correlation id (nullable) — filter one task across tiers |
| `msg` | one-line human-readable message |
| `fields` | structured context (post-redaction) |

`tier` (who emitted) and `category` (what it's about) are orthogonal and both
kept: a single `sharing` flow touches frontend, orchestrator, and agent, so
conflating them would make it impossible to filter.

## How each tier feeds the sink

- **Python (both sidecars)** — `structured_log.py` installs a `JsonLineHandler`
  on the root logger (via `configure_logging(tier, level)` in each `main.py`,
  replacing `logging.basicConfig`). It writes one JSON line per record to
  stdout, prefixed with an ASCII **Record Separator** (`0x1e`) sentinel.
  `category` derives from the logger name (`orchestrator.ws.agent_ws` → `ws`);
  cross-cutting call sites can override it and attach correlation ids with
  `logger.info(..., extra={"category": "task", "task_id": tid, "agent_id": aid})`.
- **Rust drain** — the existing stdout/stderr drain loops in `lib.rs`
  (`manage_orchestrator`, `spawn_local_agent`) call `ingest_sidecar_line`: a
  sentinel-prefixed line is parsed into a `LogEntry` (preserving level /
  category / ids); anything else (a traceback, uvicorn's banner, a stray
  `print`) is wrapped verbatim as a raw `sidecar` entry, so nothing is ever lost.
- **Rust itself** — `rust_log(app, level, category, agent_id, msg)` records
  spawn decisions, health-check results, and crash-grace outcomes (previously
  invisible `eprintln!`), still printing to stderr for `cargo tauri dev`.
- **Frontend** — `stores/logs.ts` streams the `log-entry` event into a local
  store (with a `get_logs` backfill on startup, since an event fired before the
  listener attaches is dropped). `installConsoleBridge()` routes existing
  `console.info/warn/error` into the buffer (category `ui`) while preserving
  devtools output. Components can also call `logStore.frontend(level, category,
  msg, { agent_id, task_id })` for explicit UI events (used in the Add-Agent and
  task-submit flows).

## Secret redaction (defense in depth)

Redaction runs **twice**, so a leak requires two independent mistakes:

1. **Python, at emit time** — `structured_log.py` redacts `msg` and `fields`
   before the JSON line is ever written to the pipe.
2. **Rust, at the sink** — `log_push` redacts again before an entry enters the
   ring buffer, covering raw stderr lines and frontend-pushed entries too.

Both apply the same rules: JWTs (`eyJ…`), `?token=`/`?jwt=` query params,
`Authorization: Bearer …`, and any `fields` key matching
`pubkey|x25519|token_string|secret|password|priv…|signature|jwt` (value
replaced with `<redacted>`). Devtools still shows unredacted objects (the
frontend also calls the original `console.*`) — that is acceptable for a
developer with the app open, and documented.

## Using the Debug panel

Open it from the **🐞 Debug** button in the header or with **Ctrl/Cmd + `**.

- **Category chips** toggle streams on/off; **level** is a threshold (show this
  and above); **search** matches `msg`, category, tier, and the promoted
  `agent_id` / `task_id` — so typing a task id gives its full cross-tier trace.
- **Live tail** streams new entries and auto-scrolls; **⏸** freezes the view.
- **Copy** puts the filtered rows on the clipboard as text.
- **Export** downloads the filtered set as `.jsonl` or `.txt`.
- **Copy diagnostics** bundles the logs with a header (orchestrator status, WS
  state, agent count, versions) — the one-click artifact for a bug report.
- **Clear** empties the buffer (`clear_logs`).

Everything is in-memory (last 5000 entries) and redacted; nothing leaves the
machine unless you Copy or Export it.

### Worked example — debugging agent registration

Filter on the new agent's id and you see the whole handshake, in order, across
tiers that were previously three separate invisible streams:

```
ui         registering agent "Local Agent" (default model llama3.1:8b)
ui         agent registered with orchestrator            [agent:…]
ui         starting local agent sidecar                  [agent:…]
sidecar    agent sidecar started; waiting to register    [agent:…]   (rust)
agent      Connecting to wss://…/v1/agents/ws?token=<redacted>       (python)
agent      Registered with orchestrator                  [agent:…]   (python)
ws         Agent … online (owner=…)                                  (orchestrator)
```

If it stalls, the missing line tells you which tier to look at.

## Verbosity

Logging is always on at `info`+ (so a bug report is never empty); the panel's
level filter is client-side. To raise a sidecar to `debug`, set `LOG_LEVEL=debug`
in its environment (the Console passes the environment through at spawn). A
runtime verbosity toggle and a UI enable/disable switch are deferred (see the
plan's "full version").

## Files

| File | Role |
|---|---|
| `orchestrator/structured_log.py`, `agent-runtime/structured_log.py` | Python `JsonLineHandler` + redaction (duplicated so each sidecar packages standalone) |
| `console/src-tauri/src/lib.rs` | `LogEntry`, ring buffer, `ingest_sidecar_line`, `rust_log`, `get_logs` / `push_log` / `clear_logs`, redaction |
| `console/src/lib/stores/logs.ts` | frontend store, live stream, console bridge |
| `console/src/lib/components/DebugPanel.svelte` | the viewer (filter / copy / export / diagnostics) |
| `console/src/lib/types.ts` | `LogEntry` / `LogLevel` types |
