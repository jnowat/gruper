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
| Infrastructure | None — open the file | Docker Compose orchestrator + agent runtime |
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

**Phase 0 (`gd-0.1`) is complete.** Wire contracts frozen, skeleton orchestrator running, agent runtime implemented. Phase 1 (`gd-0.2`) is underway — task dispatch and the Manager Console scaffold are code complete; the remaining gate is live end-to-end relay validation (WP-06).

**What's shipped (`gd-0.1` / `gd-0.2`):**

| Component | Status | Notes |
|-----------|--------|-------|
| `spec/contracts/` | ✅ Frozen | OpenAPI 3.1, WSS schema, 5 JSON Schema models, core mapping |
| `orchestrator/` | ✅ Running | FastAPI + PostgreSQL, JWT auth, task dispatch + result relay, console WS (WP-04/05) |
| `agent-runtime/` | ✅ Code complete | Outbound WSS client, Ollama, offline queue, circuit breaker |
| `console/` | ✅ Scaffold complete | Tauri v2 + Svelte 5; fleet view, task composer, result view, analytics; frontend build verified |

**Manager Console (`gd-0.2` / WP-05) — run it locally:**

```bash
cd console
npm install          # package-lock.json is committed; this restores the exact tree
npm run dev          # starts Vite dev server on :5173
cd src-tauri && cargo build   # verify the Tauri Rust shell compiles
# Then in a separate terminal:
npx tauri dev        # launches the desktop app against the running dev server
```

To connect the console, start the orchestrator first (`docker compose up` in `orchestrator/`), then enter the orchestrator URL and your public key in the Connect dialog.

**Next:** end-to-end relay validation over a real NAT path (WP-06) — the `gd-0.2` exit gate.

### Architecture

```
Manager Console (Tauri + Svelte)
        │  REST / WSS (/console/ws)
        ▼
   Orchestrator (FastAPI + PostgreSQL)
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
| `gd-0.2` | Walking Skeleton — single-owner relay over the internet | 🔄 In progress |
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
- Orchestrator: FastAPI + PostgreSQL (Docker Compose)
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

**Gruper Console (Manager Console)** — the [Build Windows Installer](https://github.com/jnowat/gruper/actions/workflows/build-windows.yml)
workflow runs on pushes to `main`, on pull requests into `main`, on `v*` tags, and
on manual dispatch. The console scaffold (WP-05) and its committed `package-lock.json`
mean the readiness check now passes, so the workflow builds **real** installers
rather than the placeholder:

| Build leg | Output | How to get it |
|-----------|--------|---------------|
| NSIS | `*-setup.exe` — portable installer, no admin rights | [Latest workflow run](https://github.com/jnowat/gruper/actions/workflows/build-windows.yml) → Artifacts |
| WiX | `*.msi` — enterprise / Group Policy compatible | Same link |
| Tagged `v*` | both, attached to a **draft** GitHub Release | [GitHub Releases](https://github.com/jnowat/gruper/releases) — publish manually |

> **Status:** the frontend build (`npm ci && npm run build`) is verified green on
> Linux and the pipeline is armed. The installers become downloadable once the
> first build completes on `main` (GitHub registers workflows from the default
> branch only) — the very first Windows run is the point at which the Rust/bundle
> leg is confirmed end-to-end.

| Platform | Format | Status |
|----------|--------|--------|
| Windows x64 | `.exe` (NSIS) + `.msi` (WiX) | Build armed — runs on next push to `main` |
| macOS | `.dmg` | Planned — needs `.icns` icon + macOS runner job |
| Linux | `.AppImage` / `.deb` | Planned — Linux runner job |

Pre-release builds are unsigned — Windows SmartScreen will show an "Unknown publisher"
warning on first run. This is expected and will be resolved with a code-signing
certificate before v1.0.

---

## Contributing

**Core (`Gruper.html`)** — single-file patches. Keep it browser-only with no build step. Open an issue first for anything beyond a bug fix.

**Distributed (`spec/`, `orchestrator/`, `agent-runtime/`, `console/`)** — start with [`GruperDistributedSpec.md`](GruperDistributedSpec.md) and [`ROADMAP.md`](ROADMAP.md). Read the contracts package (`spec/contracts/`) before writing any code — the schema freeze is the foundation everything else builds against.

Issues and pull requests: [github.com/jnowat/gruper/issues](https://github.com/jnowat/gruper/issues)

---

## License

MIT — see [LICENSE](LICENSE).
