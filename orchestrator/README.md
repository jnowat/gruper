# Gruper Orchestrator

**Milestone:** `gd-0.1` (WP-02) · **Status:** Skeleton — registration and heartbeat only

The orchestrator is the relay hub for Gruper Distributed. Agent nodes dial outbound
WebSocket connections to it; the Manager Console controls it over REST. No agent ever
receives an inbound connection — NAT traversal is free by design.

This work packet (WP-02) establishes the database schema, auth layer, and WebSocket
relay foundation that every subsequent work packet builds on.

---

## Quick Start

```bash
cd orchestrator
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD and JWT_SECRET (see Configuration below)

docker compose up
```

The orchestrator starts on **`http://localhost:8080`**. PostgreSQL is on `5432` (dev-only
exposure; remove the port binding before deploying).

Health check:

```bash
curl http://localhost:8080/v1/health
# {"status":"ok","version":"gd-0.1.0","db":"ok"}
```

---

## API Overview

All endpoints are under `/v1`. Full schema: `spec/contracts/openapi.yaml`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/v1/health` | None | Liveness + DB readiness |
| `POST` | `/v1/auth/token` | None | Issue JWT (find-or-create user by pubkey) |
| `POST` | `/v1/agents` | Bearer JWT | Register an agent node |
| `GET` | `/v1/agents` | Bearer JWT | List your agent nodes |
| `WS` | `/v1/agents/ws?token=<jwt>` | JWT query param | Agent heartbeat channel |

### Auth flow (gd-0.1)

```
# 1. Get a JWT (signature verification stubbed — WP-07 adds ed25519 challenge-response)
curl -X POST http://localhost:8080/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"pubkey": "<base64url-ed25519-pubkey>", "display_name": "Alice"}'
# → {"token": "eyJ...", "expires_at": "...", "user_id": "..."}

# 2. Register an agent
curl -X POST http://localhost:8080/v1/agents \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Agent",
    "pubkey": "<agent-pubkey>",
    "runtime_version": "gd-0.1.0",
    "capabilities": {
      "models": ["llama3.1:8b"],
      "roles": ["analyst"],
      "tools": [],
      "hardware": {"cpu_cores": 8, "ram_gb": 16}
    }
  }'
# → {"id": "...", "status": "offline", ...}

# 3. Agent connects via WebSocket
#    wscat -c "ws://localhost:8080/v1/agents/ws?token=<token>"
#    Send: {"type": "register", "agent_id": "<id>"}
#    Recv: {"type": "registered", "agent_id": "<id>"}   → status: idle
#    Send: {"type": "heartbeat"}                         → last_seen updated (no response)
```

### WebSocket message types

**Agent → Orchestrator**

| `type` | Payload | Effect |
|--------|---------|--------|
| `register` | `agent_id: str` | Marks agent `idle`; required before any other message |
| `heartbeat` | _(none)_ | Updates `last_seen`; no response frame |
| `status_update` | `status: idle\|busy\|degraded\|draining` | Updates agent status |

**Orchestrator → Agent**

| `type` | Payload | Condition |
|--------|---------|-----------|
| `registered` | `agent_id: str` | Successful register |
| `error` | `detail: str` | Invalid message, unknown agent, forbidden |

---

## Configuration

All settings are read from environment variables (or `.env`). No secrets in code.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE_URL` | `postgresql://gruper:gruper@localhost:5432/gruper` | Yes | asyncpg DSN |
| `JWT_SECRET` | _(insecure default)_ | **Yes** | HS256 signing key — set to `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | _(none)_ | Yes (compose) | Password for the `postgres` service |
| `POSTGRES_DB` | `gruper` | No | Database name |
| `POSTGRES_USER` | `gruper` | No | Database user |
| `LOG_LEVEL` | `INFO` | No | Python logging level |
| `JWT_ALGORITHM` | `HS256` | No | Token algorithm (do not change in gd-0.1) |
| `JWT_EXPIRE_MINUTES` | `60` | No | Token TTL |
| `HEARTBEAT_TIMEOUT_S` | `90` | No | Seconds before a silent agent goes offline |
| `HEARTBEAT_CHECK_INTERVAL_S` | `15` | No | Watchdog polling interval |
| `CORS_ORIGINS` | `["*"]` | No | Restrict in production |

Generate a secure secret:

```bash
openssl rand -hex 32
```

---

## Running Tests

Tests require a live PostgreSQL instance. The test session wipes and re-migrates
`gruper_test` at startup so it never touches your dev database.

```bash
# From the repo root or from orchestrator/ — pytest.ini sets pythonpath = ..
TEST_DATABASE_URL=postgresql://gruper:<password>@localhost:5432/gruper_test \
  pytest orchestrator/tests/ -v
```

Coverage by test file:

| File | What it covers |
|------|----------------|
| `test_register.py` | Auth token issuance, find-or-create idempotency, agent registration, duplicate-pubkey 409, invalid runtime_version 422, unauthenticated 403, GET /agents, GET /health |
| `test_heartbeat.py` | WS register handshake, idle/offline status transitions, heartbeat, invalid status error, invalid token close, unknown agent error, malformed UUID error |

---

## Project Layout

```
orchestrator/
├── main.py                  FastAPI app: lifespan, CORS, watchdog, WS route
├── config.py                pydantic-settings: all env-var knobs
├── database.py              asyncpg pool, JSON codecs, migration runner, append_event
├── security.py              JWT issue/verify, get_current_user_id dependency
├── connection_manager.py    In-memory WS tracker, heartbeat timestamps, stale detection
├── routers/
│   ├── health.py            GET /v1/health
│   ├── auth.py              POST /v1/auth/token
│   └── agents.py            POST /v1/agents, GET /v1/agents
├── ws/
│   └── agent_ws.py          WS /v1/agents/ws lifecycle handler
├── migrations/
│   ├── 001_users.sql
│   ├── 002_agents.sql
│   ├── 003_tasks.sql        SKIP LOCKED queue index (dispatch added in WP-04)
│   └── 004_events.sql       Append-only audit log; hash chain null until WP-17
├── tests/
│   ├── conftest.py          Session fixtures, DB reset, TestClient
│   ├── test_register.py     REST smoke tests
│   └── test_heartbeat.py    WebSocket smoke tests
├── docker-compose.yml       PostgreSQL 16 + orchestrator (hot reload for dev)
├── Dockerfile               Build context: repo root (see comment in file)
├── requirements.txt
├── pytest.ini
└── .env.example
```

---

## What's Stubbed (not yet implemented)

| Feature | Status | Work Packet |
|---------|--------|-------------|
| ed25519 signature verification on `POST /v1/auth/token` | Stubbed — any pubkey accepted | WP-07 |
| Task dispatch (`POST /v1/tasks`) | Not implemented | WP-04 |
| Console WebSocket (`/v1/console/ws`) | Not implemented | WP-05 |
| Cross-owner share tokens | Not implemented | WP-08 |
| E2E payload encryption (X25519 + ChaCha20) | Not implemented | WP-16 |
| Audit log hash chain | Fields exist, values are NULL | WP-17 |

---

## Alignment with `spec/contracts/`

All request/response shapes conform to `spec/contracts/openapi.yaml` and the JSON
Schema models in `spec/contracts/models/`. The `runtime_version` field is validated
against the `gd-<major>.<minor>.<patch>` pattern from `agent.schema.json`. The
`pubkey` length bounds (43–88 chars) match `user.schema.json` and `agent.schema.json`.
The `timeout_s` range on tasks (60–86400) matches `task.schema.json`, extending the
Gruper Core cap of 3600 s to allow overnight batch tasks.
