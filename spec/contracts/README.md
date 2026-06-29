# Gruper Distributed — Wire Contracts Package

**Milestone:** `gd-0.1` — Wire Contracts & Schema Freeze  
**Status:** ✅ Frozen — schemas published; WP-02 built against them with no amendments; OQ-1 and OQ-2 resolved (see below)  
**Spec version:** `0.2 — Design Draft`

This directory is the **gd-0.1 schema package** — the frozen interface layer that every downstream work packet builds against. An independent implementer can build the orchestrator, agent runtime, and Manager Console from these files without reopening architecture decisions.

---

## Contents

| File | Description |
|------|-------------|
| `openapi.yaml` | OpenAPI 3.1 — console ↔ orchestrator REST + WebSocket API |
| `wss-messages.schema.json` | JSON Schema — agent ↔ orchestrator WSS message protocol |
| `core-mapping.md` | Gruper core v0.4.5 config schema → distributed task input schema |
| `models/user.schema.json` | User / identity data model |
| `models/agent.schema.json` | Agent registration and capability data model |
| `models/task.schema.json` | Task submission and lifecycle data model |
| `models/share-token.schema.json` | ShareToken / grant data model |
| `models/event.schema.json` | Audit event (append-only, hash-chained) data model |

---

## Resolved Open Questions

These decisions were required before schema freeze (see companion spec §12.2).

### OQ-1 — Agent Loop Framework

**Decision: Custom ReAct implementation.**

Rationale: consistent with Gruper core's hand-built philosophy; maximum control over the task/state schema; designed to accept a LangGraph-style graph-engine replacement as an additive change without breaking the wire contract. The `task.input.context` field and `task.result` structure are intentionally loose to accommodate future state machine upgrades.

### OQ-2 — Sharing Model (Pattern A vs B)

**Decision: Pattern A — Shared multi-tenant orchestrator for the first release.**

Rationale: lowest moving-part count for the headline use case (Locale 1 console → Locale 2 agent); all task traffic routes through one orchestrator; owner retains global kill switch; E2E payload encryption (gd-0.5, WP-16) ensures orchestrator cannot read task content even with full DB access. Pattern B (federated per-user orchestrators) is deferred to gd-1.x; the token and agent data models do not preclude it.

---

## Schema Versioning

All schemas carry a `$id` in the form `https://gruper.dev/schemas/gd-0.1/<name>`. Breaking changes to these schemas increment the version segment and are documented in `CHANGELOG.md`. Pre-v1 schemas may change between `gd-0.x` milestones; each WP notes which schema version it targets.

---

## Generating Implementation Artifacts

These JSON Schema files are the ground truth. From them you can generate:

- **Python Pydantic models** (FastAPI, WP-02): `datamodel-codegen --input models/ --output orchestrator/models/`
- **TypeScript types** (Tauri/Svelte console, WP-05): `json-schema-to-typescript`
- **PostgreSQL migrations** (WP-02): See `models/` schemas for field names and types; migration 001-004 maps directly

No code generation tooling is required for gd-0.1. The schemas are human-readable and can be implemented by hand. Code generation is recommended from gd-0.2 onward to keep implementations in sync.

---

## WP-01 Exit Gate Checklist

- [x] Agent ↔ orchestrator WSS message schema defined (`wss-messages.schema.json`)
- [x] Console ↔ orchestrator REST/WS API defined (`openapi.yaml`)
- [x] Gruper core config schema mapped to distributed task input (`core-mapping.md`)
- [x] All data models defined (`models/`)
- [x] OQ-1 resolved (custom ReAct)
- [x] OQ-2 resolved (Pattern A)
- [ ] Schemas reviewed by independent implementer
- [ ] WP-02 implementation confirms schemas are buildable (skeleton orchestrator)
