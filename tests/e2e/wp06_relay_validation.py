#!/usr/bin/env python3
"""
WP-06 — End-to-End Relay Validation harness.

Exercises the *real* Gruper Distributed relay end to end on one host, using real
processes and real WebSockets:

    console (this harness, httpx + websockets)
        │  REST: POST /v1/auth/token, POST /v1/agents, POST /v1/tasks
        │  WS:   GET /v1/console/ws   (receives fleet_snapshot/fleet_event/
        │                              task_progress/task_complete)
        ▼
    orchestrator   (real FastAPI app under uvicorn — SQLite by default, the
                    desktop tier; PostgreSQL via --backend postgres, the
                    server tier)
        ▲
        │  outbound WS from the agent — GET /v1/agents/ws
        │  (this is the whole point of the relay model: the agent dials OUT,
        │   never listens, so no port forwarding / NAT hole is needed)
        ▼
    agent-runtime  (real agent process: ws_client.py, circuit breaker,
                    offline queue) → mock Ollama (deterministic streaming)

What it validates (maps to ROADMAP WP-06 steps):
  1. Console connects; agent registers and appears in the fleet (live fleet_event).
  2. Happy path: submit → dispatch → ack → streamed progress → result delivered
     to the console, and GET /v1/tasks/{id} shows the stored result.
  3. Resilience: kill the agent mid-task → orchestrator requeues → restart agent →
     task drains on reconnect and completes.
  4. Latency: dispatch overhead (submit → running, i.e. excluding model execution)
     measured over a batch of tasks (SC-2 target < 5–10 s).

The "public internet / consumer NAT" leg is a *deployment topology*, not a code
path: because the agent's only socket is an outbound WS to the orchestrator, the
relay works identically across NAT. This harness validates the protocol and
relay logic on loopback; docs/WP-06-Validation.md carries the field runbook for
the real two-machine run.

Usage:
    python tests/e2e/wp06_relay_validation.py [--json OUT.json]
    python tests/e2e/wp06_relay_validation.py --backend sqlite    # default — desktop tier, no services
    python tests/e2e/wp06_relay_validation.py --backend postgres  # server tier — needs a running PostgreSQL

Exit code 0 if every check passes, 1 otherwise.
"""

import argparse
import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import websockets

REPO = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO / "agent-runtime"
VENV_PY = sys.executable

ORCH_HOST = "127.0.0.1"
ORCH_PORT = 8799
OLLAMA_PORT = 11500
ORCH_HTTP = f"http://{ORCH_HOST}:{ORCH_PORT}"
ORCH_WS = f"ws://{ORCH_HOST}:{ORCH_PORT}"
OLLAMA_URL = f"http://127.0.0.1:{OLLAMA_PORT}"

JWT_SECRET = "wp06-e2e-secret"

SCRATCH = Path(os.environ.get("WP06_SCRATCH", "/tmp/wp06"))
SCRATCH.mkdir(parents=True, exist_ok=True)

# Backend selection mirrors the orchestrator's own DATABASE_URL convention
# (see orchestrator/db/connect.py). SQLite is the default — the desktop
# tier, no external service required, same as `pytest` with no setup.
# PostgreSQL is opt-in via --backend postgres — the server tier, exercising
# the real SKIP LOCKED / CTE dispatch SQL against a live Postgres instance.
SQLITE_DB_PATH = SCRATCH / "gruper_e2e.db"
POSTGRES_DB_URL = "postgresql://gruper:gruper@localhost:5432/gruper_e2e"


def _db_url(backend: str) -> str:
    return f"sqlite:///{SQLITE_DB_PATH}" if backend == "sqlite" else POSTGRES_DB_URL


async def _reset_db(backend: str) -> None:
    if backend == "sqlite":
        for suffix in ("", "-wal", "-shm"):
            Path(str(SQLITE_DB_PATH) + suffix).unlink(missing_ok=True)
        return

    import asyncpg  # server-tier only — not a desktop dependency

    sys_conn = await asyncpg.connect("postgresql://gruper:gruper@localhost:5432/postgres")
    try:
        exists = await sys_conn.fetchval("SELECT 1 FROM pg_database WHERE datname='gruper_e2e'")
        if not exists:
            await sys_conn.execute("CREATE DATABASE gruper_e2e OWNER gruper")
    finally:
        await sys_conn.close()
    conn = await asyncpg.connect(POSTGRES_DB_URL)
    try:
        await conn.execute(
            "DROP TABLE IF EXISTS events, tasks, agents, users, schema_migrations CASCADE"
        )
    finally:
        await conn.close()


# ── result tracking ───────────────────────────────────────────────────────────

class Results:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.metrics: dict = {}

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""), flush=True)
        return ok

    @property
    def passed(self) -> bool:
        return all(c["ok"] for c in self.checks)


R = Results()


# ── helpers ───────────────────────────────────────────────────────────────────

def _rand_pubkey() -> str:
    import base64
    return base64.urlsafe_b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes).rstrip(b"=").decode()


async def _wait_http(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as c:
        while time.monotonic() < deadline:
            try:
                r = await c.get(url)
                if r.status_code < 500:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.25)
    return False


def _spawn_orchestrator(db_url: str) -> subprocess.Popen:
    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "JWT_SECRET": JWT_SECRET,
        "LOG_LEVEL": "INFO",
        "HEARTBEAT_CHECK_INTERVAL_S": "5",
        "HEARTBEAT_TIMEOUT_S": "30",
    }
    log = open(SCRATCH / "orchestrator.log", "w")
    return subprocess.Popen(
        [VENV_PY, "-m", "uvicorn", "orchestrator.main:app",
         "--host", ORCH_HOST, "--port", str(ORCH_PORT), "--log-level", "info"],
        cwd=str(REPO), env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def _spawn_ollama() -> subprocess.Popen:
    log = open(SCRATCH / "ollama.log", "w")
    return subprocess.Popen(
        [VENV_PY, str(REPO / "tests/e2e/mock_ollama.py"), str(OLLAMA_PORT)],
        cwd=str(REPO), env={**os.environ}, stdout=log, stderr=subprocess.STDOUT,
    )


def _spawn_agent(agent_id: str, token: str, tag: str = "") -> subprocess.Popen:
    env = {
        **os.environ,
        "ORCHESTRATOR_URL": f"{ORCH_WS}/v1/agents/ws",
        "AGENT_ID": agent_id,
        "JWT_TOKEN": token,
        "OLLAMA_URL": OLLAMA_URL,
        "DB_PATH": str(SCRATCH / "agent_offline.db"),
        "HEARTBEAT_INTERVAL_S": "2",
        "LOG_LEVEL": "INFO",
    }
    log = open(SCRATCH / f"agent{tag}.log", "w")
    return subprocess.Popen(
        [VENV_PY, "main.py"],
        cwd=str(AGENT_DIR), env=env, stdout=log, stderr=subprocess.STDOUT,
    )


class ConsoleClient:
    """Background reader of the console WS; records every frame with arrival time."""

    def __init__(self, token: str) -> None:
        self._token = token
        self.frames: list[tuple[float, dict]] = []
        self._task: asyncio.Task | None = None
        self._ws = None
        self.snapshot: dict | None = None

    async def start(self) -> None:
        url = f"{ORCH_WS}/v1/console/ws?token={self._token}"
        self._ws = await websockets.connect(url)
        first = json.loads(await self._ws.recv())
        if first.get("type") == "fleet_snapshot":
            self.snapshot = first
        else:
            self.frames.append((time.monotonic(), first))
        self._task = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                self.frames.append((time.monotonic(), json.loads(raw)))
        except Exception:
            pass

    async def stop(self) -> None:
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()

    def of_type(self, t: str) -> list[tuple[float, dict]]:
        return [(ts, f) for ts, f in self.frames if f.get("type") == t]

    async def wait_for(self, predicate, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for ts, f in list(self.frames):
                if predicate(f):
                    return ts, f
            await asyncio.sleep(0.05)
        return None


async def _get_token(client: httpx.AsyncClient) -> tuple[str, str]:
    r = await client.post(f"{ORCH_HTTP}/v1/auth/token",
                          json={"pubkey": _rand_pubkey(), "display_name": "WP-06 Owner"})
    r.raise_for_status()
    d = r.json()
    return d["token"], d["user_id"]


async def _register_agent(client: httpx.AsyncClient, token: str) -> str:
    r = await client.post(
        f"{ORCH_HTTP}/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "wp06-agent",
            "pubkey": _rand_pubkey(),
            "capabilities": {"models": ["llama3.1:8b"], "roles": ["analyst"],
                             "tools": [], "hardware": {"cpu_cores": 4, "ram_gb": 16}},
            "runtime_version": "gd-0.1.0",
        },
    )
    r.raise_for_status()
    return r.json()["id"]


async def _submit_task(client: httpx.AsyncClient, token: str, agent_id: str,
                       prompt: str, timeout_s: int = 300) -> dict:
    r = await client.post(
        f"{ORCH_HTTP}/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "assigned_agent_id": agent_id,
            "data_class": "public",
            "input": {"prompt": prompt, "role_template": "analyst",
                      "model_preferences": {"name": "llama3.1:8b", "temperature": 0.5}},
            "priority": 50,
            "timeout_s": timeout_s,
        },
    )
    r.raise_for_status()
    return r.json()


async def _get_task(client: httpx.AsyncClient, token: str, task_id: str) -> dict:
    r = await client.get(f"{ORCH_HTTP}/v1/tasks/{task_id}",
                         headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


async def _poll_task_status(client, token, task_id, want, timeout) -> tuple[bool, dict]:
    deadline = time.monotonic() + timeout
    last = {}
    wants = {want} if isinstance(want, str) else set(want)
    while time.monotonic() < deadline:
        last = await _get_task(client, token, task_id)
        if last["status"] in wants:
            return True, last
        await asyncio.sleep(0.05)
    return False, last


async def _poll_agent_status(client, token, agent_id, want, timeout) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = await client.get(f"{ORCH_HTTP}/v1/agents",
                             headers={"Authorization": f"Bearer {token}"})
        for a in r.json():
            if a["id"] == agent_id and a["status"] == want:
                return True
        await asyncio.sleep(0.1)
    return False


# ── main scenario ─────────────────────────────────────────────────────────────

async def run(backend: str) -> None:
    procs: dict[str, subprocess.Popen] = {}
    console: ConsoleClient | None = None
    try:
        print(f"== Setup (backend={backend}) ==", flush=True)
        await _reset_db(backend)
        procs["ollama"] = _spawn_ollama()
        procs["orch"] = _spawn_orchestrator(_db_url(backend))
        ok_orch = await _wait_http(f"{ORCH_HTTP}/openapi.json", 40)
        ok_oll = await _wait_http(f"{OLLAMA_URL}/api/tags", 20)
        R.check("orchestrator process is up", ok_orch)
        R.check("mock Ollama process is up", ok_oll)
        if not (ok_orch and ok_oll):
            return

        async with httpx.AsyncClient(timeout=30) as client:
            token, user_id = await _get_token(client)
            agent_id = await _register_agent(client, token)
            R.check("REST: token issued + agent registered", bool(token and agent_id),
                    f"agent_id={agent_id[:8]}…")

            # Console connects BEFORE the agent so we can observe the agent
            # appearing live (fleet_event), not just via the connect snapshot.
            console = ConsoleClient(token)
            await console.start()
            R.check("console WS connected + fleet_snapshot received",
                    console.snapshot is not None,
                    f"{len(console.snapshot.get('agents', []))} agent(s) in snapshot"
                    if console.snapshot else "no snapshot")

            # ── Step 1: agent registers and appears in the fleet ──────────────
            print("== Step 1: agent registers and appears in the fleet ==", flush=True)
            procs["agent"] = _spawn_agent(agent_id, token)
            online = await _poll_agent_status(client, token, agent_id, "idle", 25)
            R.check("agent comes online (status=idle via REST)", online)
            ev = await console.wait_for(
                lambda f: f.get("type") == "fleet_event"
                and f.get("payload", {}).get("agent_id") == agent_id,
                timeout=10,
            )
            R.check("console receives live fleet_event for the agent", ev is not None,
                    f"event={ev[1]['payload'].get('event')} status={ev[1]['payload'].get('status')}"
                    if ev else "no fleet_event arrived within 10s")

            # ── Step 2: happy path ────────────────────────────────────────────
            print("== Step 2: happy path (submit → dispatch → stream → result) ==", flush=True)
            t_submit = time.monotonic()
            task = await _submit_task(client, token, agent_id, "Summarise the relay design.")
            task_id = task["id"]
            R.check("POST /v1/tasks dispatched immediately", task["status"] == "dispatched",
                    f"status={task['status']}")

            ran, trow = await _poll_task_status(client, token, task_id, "running", 15)
            t_running = time.monotonic()
            R.check("task acknowledged by agent (status=running)", ran,
                    f"status={trow.get('status')}")

            prog = await console.wait_for(
                lambda f: f.get("type") == "task_progress"
                and f.get("payload", {}).get("task_id") == task_id,
                timeout=15,
            )
            t_first_prog = prog[0] if prog else None
            R.check("console receives streamed task_progress", prog is not None,
                    (f"partial={prog[1]['payload'].get('partial_output')!r}") if prog else "none")

            done, drow = await _poll_task_status(client, token, task_id, "complete", 20)
            t_complete = time.monotonic()
            R.check("task reaches status=complete", done, f"status={drow.get('status')}")
            output = (drow.get("result") or {}).get("output")
            R.check("stored result has non-empty output", bool(output),
                    f"output={output!r}")

            comp = await console.wait_for(
                lambda f: f.get("type") == "task_complete"
                and f.get("payload", {}).get("task_id") == task_id,
                timeout=10,
            )
            R.check("console receives task_complete", comp is not None,
                    f"final_status={comp[1]['payload'].get('final_status')}" if comp else "none")

            R.metrics["happy_path"] = {
                "dispatch_overhead_ms": round((t_running - t_submit) * 1000, 1),
                "first_progress_ms": round((t_first_prog - t_submit) * 1000, 1) if t_first_prog else None,
                "total_ms": round((t_complete - t_submit) * 1000, 1),
            }

            # ── Step 3: resilience — kill mid-task, requeue, reconnect ────────
            print("== Step 3: resilience (kill mid-task → requeue → reconnect → complete) ==", flush=True)
            stask = await _submit_task(client, token, agent_id,
                                       "[SLOW] long running analysis", timeout_s=300)
            stask_id = stask["id"]
            ran2, _ = await _poll_task_status(client, token, stask_id, "running", 15)
            R.check("slow task running before kill", ran2)
            await asyncio.sleep(0.8)  # let it stream a bit
            procs["agent"].send_signal(signal.SIGKILL)
            procs["agent"].wait(timeout=10)
            requeued, rrow = await _poll_task_status(client, token, stask_id,
                                                     ("pending", "dead_letter"), 20)
            R.check("orchestrator requeues task after agent disconnect",
                    requeued and rrow.get("status") == "pending",
                    f"status={rrow.get('status')} retry_count={rrow.get('retry_count')}")

            procs["agent"] = _spawn_agent(agent_id, token, tag="_restart")
            back = await _poll_agent_status(client, token, agent_id, "idle", 25)
            R.check("agent reconnects after restart", back)
            done2, drow2 = await _poll_task_status(client, token, stask_id, "complete", 30)
            R.check("requeued task drains on reconnect and completes", done2,
                    f"status={drow2.get('status')} retry_count={drow2.get('retry_count')}")

            # ── Step 4: dispatch latency over a batch ─────────────────────────
            print("== Step 4: dispatch latency batch ==", flush=True)
            N = 10
            overheads = []
            totals = []
            for i in range(N):
                ts = time.monotonic()
                t = await _submit_task(client, token, agent_id, f"batch task {i}")
                r_ok, _ = await _poll_task_status(client, token, t["id"], "running", 15)
                overheads.append((time.monotonic() - ts) * 1000)
                c_ok, _ = await _poll_task_status(client, token, t["id"], "complete", 20)
                totals.append((time.monotonic() - ts) * 1000)
            overheads.sort()
            R.metrics["batch"] = {
                "n": N,
                "dispatch_overhead_ms": {
                    "min": round(min(overheads), 1),
                    "p50": round(overheads[len(overheads) // 2], 1),
                    "max": round(max(overheads), 1),
                    "mean": round(sum(overheads) / len(overheads), 1),
                },
                "total_ms": {
                    "min": round(min(totals), 1),
                    "max": round(max(totals), 1),
                    "mean": round(sum(totals) / len(totals), 1),
                },
            }
            sc2_ok = max(overheads) < 10_000
            R.check(f"SC-2: dispatch overhead < 10s for all {N} tasks", sc2_ok,
                    f"max={round(max(overheads), 1)}ms p50={round(overheads[len(overheads)//2],1)}ms")

    finally:
        if console:
            await console.stop()
        for name, p in procs.items():
            with contextlib.suppress(Exception):
                p.send_signal(signal.SIGTERM)
        for name, p in procs.items():
            with contextlib.suppress(Exception):
                p.wait(timeout=8)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(SCRATCH / "wp06_results.json"))
    ap.add_argument(
        "--backend", choices=["sqlite", "postgres"], default="sqlite",
        help="Orchestrator DB backend to validate against. sqlite (default) is the "
             "desktop tier — no external service required. postgres is the server "
             "tier — needs a reachable PostgreSQL (gruper/gruper, CREATEDB).",
    )
    args = ap.parse_args()

    print(f"WP-06 End-to-End Relay Validation (backend={args.backend})\n" + "=" * 50, flush=True)
    await run(args.backend)

    summary = {
        "passed": R.passed,
        "checks": R.checks,
        "metrics": R.metrics,
    }
    Path(args.json).write_text(json.dumps(summary, indent=2))
    n_pass = sum(1 for c in R.checks if c["ok"])
    print("\n" + "=" * 50, flush=True)
    print(f"RESULT: {n_pass}/{len(R.checks)} checks passed — "
          f"{'ALL GREEN' if R.passed else 'FAILURES PRESENT'}", flush=True)
    print(f"metrics: {json.dumps(R.metrics)}", flush=True)
    print(f"summary written to {args.json}", flush=True)
    return 0 if R.passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
