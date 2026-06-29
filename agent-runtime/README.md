# Gruper Agent Runtime

**Milestone:** `gd-0.2` (WP-03) · **Status:** Desktop MVP

The agent runtime runs on any machine that has Ollama installed. It makes a
single persistent outbound WSS connection to the orchestrator — no inbound
connections, no port forwarding required.

When the connection drops, the runtime reconnects with exponential backoff
(2 s → 4 s → 8 s → 16 s), mirroring Gruper core's circuit-breaker discipline.
Tasks that arrive while Ollama is unavailable are queued to SQLite and drained
automatically on reconnect.

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai/) running locally
- A running Gruper Orchestrator (see `orchestrator/`)

### 2. Install dependencies

```bash
cd agent-runtime
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Register this agent

First, obtain a JWT from the orchestrator (replace `<orchestrator>` with your
orchestrator's base URL, e.g. `http://localhost:8080`):

```bash
# Generate a pubkey (base64url, 43 chars — mimics an ed25519 key)
PUBKEY=$(python3 -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())")

# Get a JWT
TOKEN=$(curl -s -X POST <orchestrator>/v1/auth/token \
  -H "Content-Type: application/json" \
  -d "{\"pubkey\": \"$PUBKEY\", \"display_name\": \"My Agent Host\"}" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Register the agent node
AGENT_PUBKEY=$(python3 -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode())")
AGENT_ID=$(curl -s -X POST <orchestrator>/v1/agents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"My Workstation\",
    \"pubkey\": \"$AGENT_PUBKEY\",
    \"runtime_version\": \"gd-0.1.0\",
    \"capabilities\": {
      \"models\": [\"llama3.1:8b\"],
      \"roles\": [\"analyst\"],
      \"tools\": [],
      \"hardware\": {\"cpu_cores\": 8, \"ram_gb\": 16}
    }
  }" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "AGENT_ID=$AGENT_ID"
echo "JWT_TOKEN=$TOKEN"
```

### 4. Configure

```bash
cp .env.example .env
```

Edit `.env` and paste in the `AGENT_ID` and `JWT_TOKEN` values from above.
Set `ORCHESTRATOR_URL` to your orchestrator's WSS address.

### 5. Start the runtime

```bash
python main.py
```

You should see:

```
2026-01-01T00:00:00 INFO __main__ Gruper Agent Runtime gd-0.1.0 starting (agent_id=...)
2026-01-01T00:00:00 INFO ws_client Connecting to wss://...
2026-01-01T00:00:00 INFO ws_client Registered with orchestrator (agent_id=...)
```

The agent will appear as `idle` in `GET /v1/agents`.

---

## Configuration

All settings are read from environment variables or `.env`. No secrets appear
in code.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ORCHESTRATOR_URL` | `wss://localhost:8080/v1/agents/ws` | **Yes** | Orchestrator WSS endpoint |
| `AGENT_ID` | _(none)_ | **Yes** | UUID from `POST /v1/agents` |
| `JWT_TOKEN` | _(none)_ | **Yes** | JWT from `POST /v1/auth/token` |
| `OLLAMA_URL` | `http://localhost:11434` | No | Local Ollama base URL |
| `DB_PATH` | `agent.db` | No | SQLite offline queue file |
| `HEARTBEAT_INTERVAL_S` | `30` | No | Heartbeat interval (must be < orchestrator's 90 s timeout) |
| `CAPABILITIES` | `{"models":[],...}` | No | JSON capability descriptor |
| `LOG_LEVEL` | `INFO` | No | Python logging level |

---

## Connection Behaviour

**Reconnection:** The runtime reconnects automatically after any disconnect.
Backoff delays follow Gruper core's schedule: 2 s → 4 s → 8 s → 16 s (capped).

**Offline queue:** Tasks received while Ollama is unavailable are written to
`agent.db` (SQLite). They are retried in FIFO order on the next successful
reconnect.

**Circuit breaker:** Three consecutive Ollama failures trip the circuit open.
The runtime sends `{"type": "status_update", "status": "degraded"}` to the
orchestrator so the dispatcher stops routing new tasks here. The circuit resets
automatically on the first successful Ollama call.

**Heartbeat:** A `{"type": "heartbeat"}` frame is sent every
`HEARTBEAT_INTERVAL_S` seconds. If the orchestrator receives no heartbeat for
90 s (its default), it marks this agent `offline`.

**Graceful shutdown:** On `SIGINT` or `SIGTERM`, in-flight tasks are cancelled
and their payloads are written to the offline queue before the process exits.

---

## Systemd (Linux)

See [`gruper-agent.service`](gruper-agent.service) for the full unit file with
installation instructions in the header comments.

Quick install:

```bash
sudo cp gruper-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gruper-agent
sudo systemctl start gruper-agent
sudo journalctl -u gruper-agent -f
```

---

## Windows

Windows Service via NSSM (Non-Sucking Service Manager):

```powershell
# Install NSSM: https://nssm.cc/download
nssm install GruperAgent "C:\opt\gruper-agent\venv\Scripts\python.exe" "C:\opt\gruper-agent\main.py"
nssm set GruperAgent AppDirectory "C:\opt\gruper-agent"
nssm set GruperAgent AppEnvironmentExtra ORCHESTRATOR_URL=wss://... AGENT_ID=... JWT_TOKEN=...
nssm set GruperAgent Start SERVICE_AUTO_START
nssm start GruperAgent
```

---

## macOS

launchd plist stub — save as `~/Library/LaunchAgents/com.gruper.agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>           <string>com.gruper.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/gruper-agent/venv/bin/python</string>
    <string>/opt/gruper-agent/main.py</string>
  </array>
  <key>WorkingDirectory</key> <string>/opt/gruper-agent</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ORCHESTRATOR_URL</key> <string>wss://orchestrator.example.com/v1/agents/ws</string>
    <key>AGENT_ID</key>         <string><!-- paste UUID here --></string>
    <key>JWT_TOKEN</key>        <string><!-- paste token here --></string>
  </dict>
  <key>RunAtLoad</key>        <true/>
  <key>KeepAlive</key>        <true/>
  <key>StandardOutPath</key>  <string>/var/log/gruper-agent.log</string>
  <key>StandardErrorPath</key><string>/var/log/gruper-agent.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.gruper.agent.plist
```

---

## Project Layout

```
agent-runtime/
├── main.py              Entry point; signal handlers; startup validation
├── config.py            pydantic-settings: all env-var knobs
├── ws_client.py         Persistent WSS client; reconnect loop; task dispatch
├── ollama_client.py     Async /api/chat wrapper; Gruper core parameter conventions
├── offline_queue.py     SQLite FIFO queue; drain-on-reconnect
├── circuit_breaker.py   Three-strike breaker; degraded/idle status signals
├── requirements.txt
├── .env.example         All supported env vars with descriptions
├── gruper-agent.service Systemd unit (Linux); Windows/macOS stubs in README
└── README.md
```

---

## What's Not Implemented Yet

| Feature | Notes | Work Packet |
|---------|-------|-------------|
| Task dispatch from orchestrator (`task_push` frames) | Orchestrator dispatcher not yet implemented | WP-04 |
| ed25519 identity verification | JWT auth only in gd-0.1 | WP-07 |
| Cross-owner authority validation | Local token cache; double-check before executing | WP-09 |
| Per-task isolated workspace | Shared working directory for now | WP-09 |
| E2E payload encryption (X25519 + ChaCha20-Poly1305) | Plaintext WSS acceptable in gd-0.1 LAN testing | WP-16 |
