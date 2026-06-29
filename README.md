# Gruper

[![Core Version](https://img.shields.io/badge/core-v0.4.5-blue.svg)](Gruper.html)
[![Distributed](https://img.shields.io/badge/distributed-gd--0.1%20%E2%80%94%20contracts-orange.svg)](spec/contracts/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Docs:** [User Manual](UserManual.md) · [Distributed Spec](GruperDistributedSpec.md) · [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md)

---

Gruper is a local-first multi-agent AI system built on [Ollama](https://ollama.ai/). It comes in two tiers:

| | **Gruper Core** | **Gruper Distributed** |
|---|---|---|
| What it is | Single-file browser app | Desktop console + relay orchestrator |
| Status | Stable — `v0.4.5` | Pre-v1 — contracts phase (`gd-0.1`) |
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

## Gruper Distributed — `gd-0.1` (contracts phase)

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

The `gd-0.1` milestone (Wire Contracts & Schema Freeze) is underway. The wire contracts are being frozen before any code is written — an independent implementer can build against them without reopening architecture decisions.

**What exists now in `spec/contracts/`:**

| File | Contents |
|------|----------|
| `openapi.yaml` | OpenAPI 3.1 — all REST and WebSocket endpoints |
| `wss-messages.schema.json` | JSON Schema — full WSS message protocol (16 message types) |
| `models/user.schema.json` | User identity, ed25519 keypair-anchored |
| `models/agent.schema.json` | Agent node — capabilities, availability, share policies |
| `models/task.schema.json` | Task lifecycle, plaintext/encrypted input, result, error |
| `models/share-token.schema.json` | Share grant — scopes, quotas, conditions, revocation |
| `models/event.schema.json` | Audit event — append-only, hash-chain fields pre-wired |
| `core-mapping.md` | Gruper Core v0.4.5 per-agent config → distributed task input |
| `README.md` | Contracts package index, OQ resolutions, code-generation notes |

Open questions resolved in gd-0.1:
- **OQ-1** → **Custom ReAct implementation**, consistent with Gruper Core's hand-built philosophy
- **OQ-2** → **Pattern A — shared multi-tenant orchestrator** for the first release

**Remaining before WP-01 closes:** independent implementer review; WP-02 skeleton orchestrator confirms schemas are buildable.

**Next milestone — `gd-0.2`:** Skeleton orchestrator (WP-02), desktop agent runtime (WP-03), task dispatch (WP-04), minimal console scaffold (WP-05), end-to-end relay validation (WP-06).

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
| `gd-0.1` | Wire Contracts & Schema Freeze | 🔄 In progress |
| `gd-0.2` | Walking Skeleton — single-owner relay over the internet | 🔲 Next |
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

**Gruper Distributed** *(planned — no code shipped yet)*
- Agent runtime: Python + FastAPI; Rust for security-critical paths
- Manager Console: Tauri v2 + Svelte 5 + Tailwind
- Orchestrator: FastAPI + PostgreSQL (Docker Compose)
- Transport: WSS over TLS
- Encryption: X25519 ECDH + ChaCha20-Poly1305 (payload), ed25519 (identity)
- Schemas: JSON Schema 2020-12, generates Pydantic (FastAPI) and TypeScript (console)

---

## Contributing

**Core (`Gruper.html`)** — single-file patches. Keep it browser-only with no build step. Open an issue first for anything beyond a bug fix.

**Distributed (`spec/`, `orchestrator/`, `agent-runtime/`, `console/`)** — start with [`GruperDistributedSpec.md`](GruperDistributedSpec.md) and [`ROADMAP.md`](ROADMAP.md). Read the contracts package (`spec/contracts/`) before writing any code — the schema freeze is the foundation everything else builds against.

Issues and pull requests: [github.com/jnowat/gruper/issues](https://github.com/jnowat/gruper/issues)

---

## License

MIT — see [LICENSE](LICENSE).
