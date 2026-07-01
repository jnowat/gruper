# Gruper

[![Core Version](https://img.shields.io/badge/core%20version-0.4.5-blue.svg)](Gruper.html)
[![Distributed](https://img.shields.io/badge/distributed-gd--0.2%20%E2%80%94%20walking%20skeleton-orange.svg)](orchestrator/)
[![Build Windows Installer](https://github.com/jnowat/gruper/actions/workflows/build-windows.yml/badge.svg)](https://github.com/jnowat/gruper/actions/workflows/build-windows.yml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Docs:** [User Manual](UserManual.md) · [Distributed Spec](GruperDistributedSpec.md) · [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md)

---

Gruper is a local-first multi-agent AI system built on [Ollama](https://ollama.ai/). It comes in two tiers:

| | **Gruper Core** | **Gruper Distributed** |
|---|---|---|
| What it is | Single-file browser app | Desktop console + relay orchestrator |
| Status | Stable — `v0.4.5` | Pre-v1 — walking skeleton (`gd-0.2`) |
| Agents | Up to 6, on one machine | Unlimited, across machines and owners |
| Sharing | None | Scoped cross-user tokens with instant revocation |
| Infrastructure | None — open the file | Orchestrator (SQLite by default, no Docker) + agent runtime |
| Best for | Quick single-machine sessions | Distributed work, collaboration, cloud burst |

Both tiers share the same Ollama API shape, 12 agent role templates, circuit-breaker discipline, and Chart.js visual language. Core is the proven baseline; Distributed extends it without replacing it.

---

## Gruper Core — `v0.4.5`

A single HTML file. No build step, no server, no dependencies beyond a browser and Ollama.

### Quick Start

```bash
git clone https://github.com/jnowat/gruper.git
cd gruper
open Gruper.html        # macOS
# firefox Gruper.html  # Linux
# double-click the file on Windows
```

Start Ollama first:

```bash
ollama serve
ollama pull llama3.1:8b   # or any other model
```

Open the file, point it at `http://localhost:11434`, select your models, and start a conversation.

### Features

**Multi-agent conversations**
- Up to 6 agents with distinct personalities active in the same conversation
- 12 pre-built role templates: Analyst, Creative, Critic, Synthesizer, Expert, Devil's Advocate, Philosopher, Economist, Ethicist, Scientist, Psychologist, Engineer
- Configurable memory depth, consensus detection, and round limits

**Per-agent inference control**

| Parameter | Range | Notes |
|-----------|-------|-------|
| Temperature | 0–1 | Randomness / creativity |
| Top-P | 0–1 | Nucleus sampling |
| Top-K | 1–100 | Vocabulary cutoff |
| Repeat Penalty | 0.5–2 | Repetition suppression |
| Max Tokens | 128–8192 | Response length cap |
| Context Length | 512–16384 | Context window |
| Seed | Optional | Reproducible outputs |
| Timeout | 60–3600 s | Per-agent or global |

**Reliability**
- Circuit-breaker: agent auto-disables after 3 consecutive Ollama failures
- Exponential backoff on retries: 2 s / 4 s / 8 s / 16 s
- All state persists in localStorage

**UI**
- Dark mode (system preference + manual toggle)
- Multi-conversation tabs
- Command palette (`Cmd+K`)
- Analytics dashboard (Chart.js — response times, success rate, model usage)
- Searchable debug log with drag-to-resize
- Export conversations and configs (JSON)
- DOMPurify XSS protection on all rendered output

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Enter` | Start conversation |
| `Ctrl+P` | Pause |
| `Ctrl+.` | Stop |
| `Ctrl+R` | Reset |
| `Ctrl+E` | Export |
| `Ctrl+A` | Analytics |
| `Ctrl+D` | Debug mode |
| `Cmd+K` | Command palette |
| `Ctrl+T` | New tab |
| `Ctrl+Shift+D` | Toggle dark mode |
| `Ctrl+B` | Toggle sidebar |

---

## Gruper Distributed — `gd-0.2` (walking skeleton)

A companion system that extends Gruper Core across multiple machines and multiple owners. Core continues to work exactly as it does today — nothing is replaced.

### What it adds

- **Cross-machine relay** — agents dial outbound WSS to a shared orchestrator; no inbound ports required, works behind any NAT or corporate firewall
- **Cross-owner sharing** — mint a cryptographically signed, scoped share token; a collaborator imports it and dispatches tasks to your agents within the defined constraints
- **Instant revocation** — token revoke takes effect within one dispatch cycle; no grace period
- **AWS cloud burst** — spot GPU instances on demand with a hard spend cap enforced at enqueue (gd-0.4 / WP-13)
- **Per-task sandboxing** — Firejail (Linux), Job Objects (Windows), sandbox-exec (macOS), Docker seccomp (container); platform-equivalent containment (gd-0.5 / WP-15)
- **E2E payload encryption** — X25519 ECDH + ChaCha20-Poly1305; the orchestrator routes ciphertext it cannot read (gd-0.5 / WP-16)
- **Hash-chained audit log** — SHA-256-chained, append-only event stream for tamper-evident compliance records (gd-0.5 / WP-17)
- **Manager agent delegation** — a manager agent decomposes a goal and dispatches sub-tasks across ownership boundaries within a strict subset of the principal's grant scope (gd-0.3 / WP-11)

### Current status

**Phase 0 (`gd-0.1`) is complete.** Wire contracts frozen, skeleton orchestrator running, agent runtime implemented. Phase 1 (`gd-0.2`) is nearly there — task dispatch, the Manager Console scaffold, **and end-to-end relay validation (WP-06)** are done. The automated E2E harness drives the real relay (console → orchestrator → agent → Ollama → back) and is **17/17 green**; running it for the first time surfaced and fixed five message-contract bugs that had silently prevented dispatch from ever working. **Phase 1.5 (desktop-first foundation) is also code-complete and validated on Linux:** the orchestrator defaults to SQLite (WP-30), both the orchestrator and agent are packaged as self-contained executables (WP-31), and the Console auto-starts and auto-connects to a local orchestrator with zero manual steps (WP-32) — see the desktop quick start below. The remaining gates are the real two-machine public-internet/NAT field run (`gd-0.2`) and running the desktop packaging/auto-run stack on a real Windows machine (`gd-0.2.x`, WP-31/WP-32) — see [ROADMAP.md](ROADMAP.md) for the honest current state.

**What's shipped (`gd-0.1` / `gd-0.2` / `gd-0.2.x`):**

| Component | Status | Notes |
|-----------|--------|-------|
| `spec/contracts/` | ✅ Frozen | OpenAPI 3.1, WSS schema, 5 JSON Schema models, core mapping |
| `orchestrator/` | ✅ Running, packaged | FastAPI, JWT auth (auto-generated on first run), task dispatch + result relay, console WS; **SQLite by default, PostgreSQL opt-in for the server tier (WP-30)**; self-contained executable via PyInstaller (WP-31) |
| `agent-runtime/` | ✅ Code complete, packaged | Outbound WSS client, Ollama, offline queue, circuit breaker; dispatch contract validated in WP-06; self-contained executable via PyInstaller (WP-31) |
| `console/` | ✅ Scaffold complete, auto-connect, agent onboarding | Tauri v2 + Svelte 5; fleet view, task composer, result view, analytics; **auto-starts and auto-connects to a local orchestrator sidecar with zero manual steps (WP-32)**; **"+ Add Local Agent" registers a fresh agent identity, probes local Ollama for models, and spawns it as a second sidecar — no config files, no manual JWT copy-paste, single-machine scope** |
| end-to-end relay | ✅ Automated E2E green | `tests/e2e/` drives the real relay 17/17 on both SQLite and PostgreSQL; real-NAT field run pending ([WP-06 report](docs/WP-06-Validation.md)) |

**⚠️ Honest caveat:** WP-31/WP-32 above were built and verified on **Linux only**. The Windows CI build job (`build-windows.yml`) **has succeeded repeatedly** — 18 green runs as of this writing, including on `main` — so the `.exe`/`.msi` installers it produces do build and bundle correctly. What's still unverified is a human actually downloading one of those installers and running it on **physical Windows hardware**: the sidecar auto-run path, the SQLite/JWT-secret file locations, and the orphan-detection watchdog have only been exercised on Linux. See [ROADMAP.md](ROADMAP.md) for the specifics.

### Desktop quick start (no Docker, no PostgreSQL, no manual Python)

This is the primary way to run the full stack (Console + Orchestrator + Agent) locally. Docker + PostgreSQL remain available as an **advanced / server** option — see [Server deployment](#server-deployment-docker--postgresql-advanced) below.

**Option A — Windows installer (recommended for most users):** download the latest Console installer from the [Build Windows Installer](https://github.com/jnowat/gruper/actions/workflows/build-windows.yml) workflow's Artifacts (see [Downloads](#downloads) below). Install and launch it — the Console bundles the orchestrator as a background process and starts it automatically on launch; you land straight on the fleet dashboard with no separate orchestrator step and no manual configuration. Ollama is the one remaining external prerequisite (see [Quick Start](#quick-start) above).

From the fleet dashboard, click **"+ Add"** to register and start your first agent — the Console generates its identity, probes `localhost:11434` for installed Ollama models, registers it with the local orchestrator, and launches it as a background process, all in one dialog. This closes what used to be the biggest gap in the desktop experience: previously there was no way to get from "Console installed" to "a task actually runs" without hand-editing `agent-runtime/.env` and copy-pasting a JWT from a `curl` command.

Ollama detection runs automatically when the dialog opens and tells you exactly what's wrong if it can't find a usable model — "Ollama isn't running" vs. "Ollama is running but has no models" (with the exact `ollama pull` command to fix it) — with a Retry button once you've acted on it. **The "Add Agent" button stays disabled until at least one real model is confirmed**; it will not register a placeholder agent that can never run a task. If the local agent process fails to start (or crashes right after), the dialog reports the actual failure instead of a generic "should appear online soon."

**Windows note:** Ollama detection runs as a Rust command (`detect_ollama_models`), not a frontend `fetch()`. A real Windows hardware test caught a genuine bug here: the webview's own `fetch()` to `http://localhost:11434` is blocked by Chromium/WebView2's Private Network Access policy even when Ollama is running with models installed, because Ollama's server never sends the `Access-Control-Allow-Private-Network` header that policy requires. Moving the request to a Rust-side socket (which isn't a browser page and isn't subject to that policy) fixed it.

**Option B — build from source (any platform), one command:**

```bash
git clone https://github.com/jnowat/gruper.git
cd gruper
./scripts/build-desktop.sh          # macOS/Linux
# .\scripts\build-desktop.ps1       # Windows PowerShell
```

This creates a build venv, installs both Python runtimes' dependencies, packages the orchestrator and agent as self-contained executables with PyInstaller (`dist/`), and stages the orchestrator as the Console's Tauri sidecar binary. Both executables are zero-config: SQLite database and JWT secret are created automatically on first run, bound to `127.0.0.1` only.

Then launch the Console the same way as any Tauri app in this repo (`cd console && npm install && npm run dev`, then in another terminal `npx tauri dev` — see [Contributing](#contributing) for the full dev loop) — it will detect the staged sidecar, start it, and auto-connect.

`dist/gruper-agent` (or `dist\gruper-agent.exe` on Windows) is meant to be started by the Console's "Add Local Agent" dialog, not run by hand — double-clicking it (or running it with no `AGENT_ID`/`JWT_TOKEN` set) now prints a plain-language explanation of that and points you at the Console instead of the old developer-facing `curl` instructions. If you deliberately want to run it standalone anyway (e.g. a headless machine dialing out to a remote orchestrator), copy `agent-runtime/.env.example` to `.env` next to the executable and fill in `ORCHESTRATOR_URL`/`AGENT_ID`/`JWT_TOKEN`.

To validate the packaged executables end to end without any of the above (useful for CI or a quick sanity check), run `python scripts/validate-desktop-packaging.py` — it spins up a mock Ollama, the real packaged orchestrator and agent binaries, and confirms a task relays through successfully.

### Server deployment (Docker + PostgreSQL, advanced)

Use this tier for multi-user, multi-tenant, or always-on hosting — a VPS, an internal server, or a cloud host serving several collaborators. It is **not** needed for a single desktop user; see the desktop quick start above for that case.

```bash
cd orchestrator
docker compose up      # PostgreSQL + orchestrator, DATABASE_URL set to postgresql://...
```

See [`orchestrator/README.md`](orchestrator/README.md) for the full Docker Compose setup, environment variables, and how to point agents/Console at a shared server-tier orchestrator instead of a local one.

### Architecture

```
Manager Console (Tauri + Svelte)
        │  REST / WSS (/console/ws)
        ▼
   Orchestrator (FastAPI; SQLite default / PostgreSQL opt-in)
      ▲         ▲         ▲
      │ WSS     │ WSS     │ WSS
  Agent A    Agent B    Agent C
 (LAN PC)  (remote PC) (AWS EC2)
     │           │          │
  Ollama      Ollama     Ollama
```

Every agent dials *outbound* WSS to the orchestrator. Nothing connects inward. NAT traversal requires no configuration on any agent host.

### Roadmap at a glance

| Milestone | Phase | Status |
|-----------|-------|--------|
| `gd-0.1` | Wire Contracts & Schema Freeze | ✅ Complete |
| `gd-0.2` | Walking Skeleton — single-owner relay over the internet | 🔄 Automated E2E relay green (17/17); real-NAT field run pending |
| `gd-0.3` | Cross-Network Sharing — scoped tokens, cross-owner dispatch | 🔲 Planned |
| `gd-0.4` | Cloud Burst — AWS spot fleet with hard cost cap | 🔲 Planned |
| `gd-0.5` | Security Hardening — sandbox parity, E2E encryption, audit chain | 🔲 Planned |
| `gd-0.6–0.9` | Beta & Polish — capability dispatch, crew builder, n8n integration | 🔲 Planned |
| `v1.0` | First stable release — SC-1…SC-7 met for real users | 🔲 Future finish line |

Full detail in [ROADMAP.md](ROADMAP.md).

### Ship criteria for v1.0

| SC | Criterion | Target |
|----|-----------|--------|
| SC-1 | Install to first remote task result (new collaborator node) | **< 5 min** |
| SC-2 | Dispatch overhead, excluding model execution | **< 5–10 s** |
| SC-3 | Owner revocation takes effect | **Immediately** |
| SC-4 | All traffic authenticated, encrypted, auditable | **100%** |
| SC-5 | Works behind consumer NAT / corporate firewall / AWS | **No port forwarding required** |
| SC-6 | Sensitive task never crosses an unauthorized boundary | **Policy-enforced at dispatch** |
| SC-7 | Agent loses connectivity mid-task | **Local queue survives; syncs on reconnect** |

---

## Technologies

**Gruper Core**
- Vanilla JS (ES6+), HTML5, CSS3 — single file, zero build step
- [Chart.js](https://www.chartjs.org/) v4.5.1 — analytics visualization
- [DOMPurify](https://github.com/cure53/DOMPurify) v3.4.11 — XSS protection
- Ollama `/api/chat` — local inference

**Gruper Distributed** *(in progress — `gd-0.2`)*
- Agent runtime: Python + FastAPI; Rust for security-critical paths
- Manager Console: Tauri v2 + Svelte 5 + Tailwind
- Orchestrator: FastAPI; SQLite by default (desktop), PostgreSQL opt-in via Docker Compose (server tier)
- Transport: WSS over TLS
- Encryption: X25519 ECDH + ChaCha20-Poly1305 (payload), ed25519 (identity)
- Schemas: JSON Schema 2020-12, generates Pydantic (FastAPI) and TypeScript (console)

---

## Downloads

**Gruper Core** is a single file — no installer needed:

```bash
# Clone and open directly
git clone https://github.com/jnowat/gruper.git
open gruper/Gruper.html   # macOS — or double-click on Windows/Linux
```

**Gruper Console (Manager Console)** — Windows installers are now available. The
[Build Windows Installer](https://github.com/jnowat/gruper/actions/workflows/build-windows.yml)
workflow runs on pushes to `main`, on pull requests into `main`, on `v*` tags, on
`claude/**` feature-branch pushes (so development branches produce installers
without opening a PR), and on manual dispatch. The console scaffold (WP-05)
compiles end-to-end, so the workflow builds **real** installers — download them
from the workflow run's **Artifacts**. Every run leaves a downloadable artifact:
the installers on success, or a `BUILD-DIAGNOSTICS.txt` if the build fails. The
same workflow also builds and uploads the packaged orchestrator and agent
executables (WP-31), and bundles the orchestrator into the Console installer as
a sidecar (WP-32) — so installing the Console is meant to be the entire desktop
setup, with no separate orchestrator step.

| Build leg | Output | How to get it |
|-----------|--------|---------------|
| NSIS | `*-setup.exe` — portable installer, no admin rights | [Latest workflow run](https://github.com/jnowat/gruper/actions/workflows/build-windows.yml) → Artifacts |
| WiX | `*.msi` — enterprise / Group Policy compatible | Same link |
| Orchestrator / Agent | `gruper-orchestrator.exe` / `gruper-agent.exe` — standalone executables, same artifacts page | Same link |
| Tagged `v*` | all of the above, attached to a **draft** GitHub Release | [GitHub Releases](https://github.com/jnowat/gruper/releases) — publish manually |

The `.exe` (NSIS) and `.msi` (WiX) installers are built on **GitHub Actions'
Windows runner** — native Windows MSVC binaries cannot be cross-compiled from
Linux or macOS, so the installers come from CI rather than a local build. The
same is true of the orchestrator/agent `.exe`s (PyInstaller does not cross-compile
either). **Honest caveat:** this Windows CI job has succeeded 18 times to date
(including on `main`), so the build itself is proven — what has **not** yet
happened is a human downloading one of those artifacts and running it on a real
Windows machine as part of the WP-31/WP-32 work — see [ROADMAP.md](ROADMAP.md)
for specifics.

> **Status:** The console scaffold builds end-to-end. Both the frontend
> (`npm ci && npm run build && npm run check`) **and** the Tauri Rust shell
> (`cargo build` in `src-tauri/`, including the `tauri::generate_context!` icon and
> asset validation) compile green on Linux. The Tauri v2 library-naming bug that
> previously broke the Windows compile — `gruper_console_lib` unresolved, because
> `Cargo.toml` had no explicit `[lib]` section — is fixed, and the bundle icons are
> now valid RGBA. The workflow has since run green on `main` multiple times, so
> downloadable `.exe` / `.msi` artifacts are available from any successful
> `main` run or `v*` tag today — not just a future one.

| Platform | Format | Status |
|----------|--------|--------|
| Windows x64 | `.exe` (NSIS) + `.msi` (WiX) | ✅ Build fixed — compiles + bundles on the Windows CI runner |
| macOS | `.dmg` | Planned — `.icns` icon now generated; needs macOS runner job |
| Linux | `.AppImage` / `.deb` | Planned — Linux runner job |

Pre-release builds are unsigned — Windows SmartScreen will show an "Unknown publisher"
warning on first run. This is expected and will be resolved with a code-signing
certificate before v1.0.

---

## Contributing

**Core (`Gruper.html`)** — single-file patches. Keep it browser-only with no build step. Open an issue first for anything beyond a bug fix.

**Distributed (`spec/`, `orchestrator/`, `agent-runtime/`, `console/`)** — start with [`GruperDistributedSpec.md`](GruperDistributedSpec.md) and [`ROADMAP.md`](ROADMAP.md). Read the contracts package (`spec/contracts/`) before writing any code — the schema freeze is the foundation everything else builds against.

**Console dev loop** (hot-reload against source, rather than a packaged sidecar):

> ⚠️ **Mandatory first step — do this before `cargo build` or `npx tauri dev`, not just for auto-connect.** `console/src-tauri/tauri.conf.json` declares `gruper-orchestrator` and `gruper-agent` as `bundle.externalBin` sidecars. Tauri's build script checks that a matching staged binary exists for your host triple **even for a plain debug build** — with nothing staged, `cargo build`/`cargo check`/`npx tauri dev` all hard-fail with `resource path "binaries/gruper-orchestrator-<your-triple>" doesn't exist` before any of your own code even compiles. This is not optional, and it is not documented anywhere else as clearly as this: run the staging step once (below) any time you `git clone` fresh or wipe `console/src-tauri/binaries/`.

```bash
./scripts/build-desktop.sh          # macOS/Linux — from the repo root
# .\scripts\build-desktop.ps1       # Windows PowerShell
```

This builds the orchestrator and agent as PyInstaller executables and copies both into `console/src-tauri/binaries/` under your platform's host triple — the one-time step the warning above requires. Do this once per clone (or whenever you delete `console/src-tauri/binaries/`), then the normal dev loop:

```bash
cd console
npm install          # package-lock.json is committed; this restores the exact tree
npm run dev          # starts Vite dev server on :5173
# in a separate terminal:
npx tauri dev        # launches the desktop app against the running dev server
```

To get auto-connect behavior like a packaged build, the staged orchestrator sidecar from the step above is enough — the Console will spawn it itself. Alternatively, run the orchestrator separately (`uvicorn orchestrator.main:app --port 8080` from the repo root — see [orchestrator/README.md](orchestrator/README.md)) and let the Console detect it as an already-running orchestrator instead.

Issues and pull requests: [github.com/jnowat/gruper/issues](https://github.com/jnowat/gruper/issues)

---

## License

MIT — see [LICENSE](LICENSE).
