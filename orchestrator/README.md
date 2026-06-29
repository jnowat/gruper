# Gruper Orchestrator

**Milestone:** `gd-0.1` (WP-02) · **Status:** Skeleton — registration and heartbeat only

The orchestrator is the relay hub for Gruper Distributed. Agent nodes dial
*outbound* WebSocket connections to it; the Manager Console manages it over REST.
No inbound connections are made to any agent node — NAT traversal is free by design.

This work packet (WP-02) establishes the database schema, auth layer, and WebSocket
relay foundation that every subsequent work packet builds on. Task dispatch (WP-04),
the Manager Console (WP-05), and cross-owner sharing (WP-08) extend this foundation
without replacing it.

---

## Quick Start

```bash
cd orchestrator
cp .env.example .env
```

Edit `.env` — at minimum, set `POSTGRES_PASSWORD` and `JWT_SECRET`:

```bash
# Generate a secure signing key
openssl rand -hex 32   # paste the output as JWT_SECRET
```

Then start the stack:

```bash
docker compose up
```

The orchestrator starts on **`http://localhost:8080`**. PostgreSQL is exposed on
`5432` for local development only — remove that port binding before deploying.

Verify it's up:

```bash
curl http://localhost:8080/v1/health
# {"status":"ok","version":"gd-0.1.0","db":"ok"}
```

---

## API Overview

All endpoints are under `/v1`. Full machine-readable spec: `spec/contracts/openapi.yaml`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/v1/health` | None | Liveness + DB readiness |
| `POST` | `/v1/auth/token` | None | Issue JWT (find-or-create user by pubkey) |
| `POST` | `/v1/agents` | Bearer JWT | Register an agent node |
| `GET` | `/v1/agents` | Bearer JWT | List your agent nodes |
| `WS` | `/v1/agents/ws?token=<jwt>` | JWT query param | Agent heartbeat channel |

Interactive docs are available at `http://localhost:8080/docs` while the server is running.

---

## Auth Flow

```bash
# 1. Generate a test pubkey (base64url, 43 chars — mimics an ed25519 public key)
python3 -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())"

# 2. Get a JWT (signature verification is stubbed in gd-0.1 — WP-07 adds ed25519)
curl -s -X POST http://localhost:8080/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"pubkey": "<paste-pubkey-here>", "display_name": "Alice"}' | jq
# → {"token": "eyJ...", "expires_at": "...", "user_id": "..."}

# 3. Register an agent (use the token from step 2)
curl -s -X POST http://localhost:8080/v1/agents \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Agent",
    "pubkey": "<a-different-pubkey-for-the-agent>",
    "runtime_version": "gd-0.1.0",
    "capabilities": {
      "models": ["llama3.1:8b"],
      "roles": ["analyst"],
      "tools": [],
      "hardware": {"cpu_cores": 8, "ram_gb": 16}
    }
  }' | jq
# → {"id": "...", "status": "offline", "owner_id": "...", ...}

# 4. Connect the agent via WebSocket (wscat: npm install -g wscat)
wscat -c "ws://localhost:8080/v1/agents/ws?token=<token>"
# Send: {"type": "register", "agent_id": "<id-from-step-3>"}
# Recv: {"type": "registered", "agent_id": "..."}   ← agent is now idle
# Send: {"type": "heartbeat"}                         ← last_seen updated, no reply
# (close the connection → agent becomes offline)
```

---

## WebSocket Protocol

**Agent → Orchestrator**

| `type` | Required fields | Effect |
|--------|-----------------|--------|
| `register` | `agent_id: str` | Marks agent `idle`; must be the first message sent |
| `heartbeat` | _(none)_ | Updates `last_seen`; no response frame |
| `status_update` | `status: idle\|busy\|degraded\|draining` | Updates agent status |

**Orchestrator → Agent**

| `type` | Fields | Condition |
|--------|--------|-----------|
| `registered` | `agent_id: str` | Successful register handshake |
| `error` | `detail: str` | Invalid message, bad UUID, unknown agent, forbidden |

**Heartbeat watchdog:** if no heartbeat is received for 90 s (configurable), the
orchestrator marks the agent `offline` automatically. The watchdog polls every 15 s.

**Re-registration:** if an agent reconnects after a crash and calls `register` while
a stale entry exists for its `agent_id`, the orchestrator replaces the stale entry
and continues normally.

---

## Configuration

All settings are read from environment variables or `.env`. No secrets appear in code.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE_URL` | `postgresql://gruper:gruper@localhost:5432/gruper` | **Yes** | asyncpg connection DSN |
| `JWT_SECRET` | _(insecure default)_ | **Yes** | HS256 signing key; generate with `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | _(none)_ | **Yes** (compose) | Password for the `postgres` compose service |
| `POSTGRES_DB` | `gruper` | No | Database name |
| `POSTGRES_USER` | `gruper` | No | Database user |
| `JWT_EXPIRE_MINUTES` | `60` | No | Token lifetime |
| `HEARTBEAT_TIMEOUT_S` | `90` | No | Seconds of silence before an agent goes offline |
| `HEARTBEAT_CHECK_INTERVAL_S` | `15` | No | Watchdog polling interval |
| `CORS_ORIGINS` | `["*"]` | No | JSON array of allowed origins; restrict in production |
| `LOG_LEVEL` | `INFO` | No | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

> **`CORS_ORIGINS` format:** the value must be a JSON array string.
> Example: `CORS_ORIGINS=["https://console.example.com","https://app.example.com"]`

---

## Running Tests

Tests require a live PostgreSQL instance (separate from your dev database).
The session fixture drops and re-migrates all tables on startup.

```bash
# From the repo root or from inside orchestrator/ — pytest.ini adds .. to sys.path
TEST_DATABASE_URL=postgresql://gruper:<password>@localhost:5432/gruper_test \
  pytest orchestrator/tests/ -v
```

Or with a Docker-based database:

```bash
docker run -d --name pg-test -e POSTGRES_USER=gruper -e POSTGRES_PASSWORD=gruper \
  -e POSTGRES_DB=gruper_test -p 5433:5432 postgres:16-alpine

TEST_DATABASE_URL=postgresql://gruper:gruper@localhost:5433/gruper_test \
  pytest orchestrator/tests/ -v

docker rm -f pg-test
```

**Test coverage:**

| File | What it covers |
|------|----------------|
| `test_register.py` | Auth token issuance, find-or-create idempotency, agent registration (201), duplicate pubkey (409), invalid `runtime_version` (422), unauthenticated (403), `GET /agents`, `GET /health` |
| `test_heartbeat.py` | WS register handshake, `idle` on register, `offline` on disconnect, heartbeat (silent), invalid status error, invalid token close (4401), unknown agent error, malformed UUID error |

---

## Project Layout

```
orchestrator/
├── main.py                  FastAPI app: lifespan, CORS, heartbeat watchdog, WS route
├── config.py                pydantic-settings: all env-var knobs in one place
├── database.py              asyncpg pool, JSON/JSONB codecs, migration runner, append_event
├── security.py              JWT issue/verify; get_current_user_id dependency
├── connection_manager.py    In-memory WS tracker, heartbeat timestamps, stale detection
├── routers/
│   ├── health.py            GET /v1/health
│   ├── auth.py              POST /v1/auth/token
│   └── agents.py            POST /v1/agents · GET /v1/agents
├── ws/
│   └── agent_ws.py          WS /v1/agents/ws — full connection lifecycle
├── migrations/
│   ├── 001_users.sql        User identity, anchored to ed25519 pubkey
│   ├── 002_agents.sql       Agent nodes with capability/availability metadata
│   ├── 003_tasks.sql        Task queue (SKIP LOCKED dispatch index, added in WP-04)
│   └── 004_events.sql       Append-only audit log (hash chain fields null until WP-17)
├── tests/
│   ├── conftest.py          Session-scoped fixtures, DB reset, TestClient
│   ├── test_register.py     REST smoke tests
│   └── test_heartbeat.py    WebSocket smoke tests
├── docker-compose.yml       PostgreSQL 16 + orchestrator (hot reload for dev)
├── Dockerfile               Build context: repo root (see inline comment)
├── requirements.txt
├── pytest.ini               asyncio_mode=auto · pythonpath=..
└── .env.example             All supported env vars with descriptions
```

---

## What's Not Implemented Yet

| Feature | Stub notes | Work Packet |
|---------|-----------|-------------|
| ed25519 signature verification on `POST /v1/auth/token` | Any caller with a syntactically valid pubkey receives a token | WP-07 |
| Task submission and dispatch (`POST /v1/tasks`) | Schema and queue index exist; no dispatcher | WP-04 |
| Console WebSocket (`GET /v1/console/ws`) | Defined in `openapi.yaml`; not implemented | WP-05 |
| Cross-owner share tokens | Schema designed in `models/share-token.schema.json` | WP-08 |
| E2E payload encryption (X25519 + ChaCha20-Poly1305) | `x25519_pubkey` column exists in agents; null | WP-16 |
| Audit log hash chain | `prev_hash` / `entry_hash` columns exist; all null | WP-17 |

---

## Alignment with `spec/contracts/`

The implementation stays deliberately close to the frozen contracts:

- **Request/response shapes** conform to `spec/contracts/openapi.yaml`. Field names, types, and required-ness match the OpenAPI spec.
- **`runtime_version`** is validated against the `^gd-\d+\.\d+\.\d+` pattern from `agent.schema.json`.
- **`pubkey` bounds** (43–88 chars base64url) match `user.schema.json` and `agent.schema.json`.
- **Task `timeout_s` range** (60–86400) matches `task.schema.json`, extending Gruper Core's 3600 s cap to support overnight batch tasks.
- **Status enum** (`idle`, `busy`, `offline`, `degraded`, `draining`) matches `agent.schema.json`.
- **Event `action` values** (`agent.registered`, `agent.connected`, `agent.disconnected`, `agent.status_changed`, `user.created`, `user.token_issued`) are a strict subset of the 28-value enum in `event.schema.json`.
