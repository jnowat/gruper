#!/usr/bin/env python3
"""
WP-31 — validates the PACKAGED executables (dist/gruper-orchestrator,
dist/gruper-agent), not the Python source. This is deliberately separate from
tests/e2e/wp06_relay_validation.py, which validates the *code* by running it
via `python`/`uvicorn` with a --backend flag — this script validates that the
PyInstaller *build artifacts* actually work standalone, with no Python
installed conceptually on the "target machine" (in practice: this process's
own Python isn't on the executables' PATH requirement — they're self-contained).

Prerequisites: build the executables first —
    pyinstaller orchestrator/packaging/gruper-orchestrator.spec --distpath dist
    pyinstaller agent-runtime/packaging/gruper-agent.spec --distpath dist

Usage:
    python scripts/validate-desktop-packaging.py [--dist dist]

Exit code 0 if the full happy path completes, 1 otherwise.
"""

import argparse
import base64
import json
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ORCH_PORT = 8930
OLLAMA_PORT = 8931
ORCH_URL = f"http://127.0.0.1:{ORCH_PORT}"


def _rand_pubkey() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(url: str, body: dict, token: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _wait_http(url: str, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _ = _get(url)
            if status < 500:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=str(REPO / "dist"))
    args = ap.parse_args()
    dist = Path(args.dist)
    orch_exe = dist / "gruper-orchestrator"
    agent_exe = dist / "gruper-agent"

    for exe in (orch_exe, agent_exe):
        if not exe.is_file():
            print(f"FAIL: {exe} not found — build it first (see script docstring)")
            return 1

    scratch = Path(tempfile.mkdtemp(prefix="gruper-desktop-validate-"))
    print(f"Scratch dir: {scratch}")
    procs: list[subprocess.Popen] = []
    try:
        print("== Starting mock Ollama ==")
        ollama_log = open(scratch / "ollama.log", "w")
        procs.append(subprocess.Popen(
            [sys.executable, str(REPO / "tests/e2e/mock_ollama.py"), str(OLLAMA_PORT)],
            cwd=str(scratch), stdout=ollama_log, stderr=subprocess.STDOUT,
        ))
        if not _wait_http(f"http://127.0.0.1:{OLLAMA_PORT}/api/tags", 15):
            print("FAIL: mock Ollama did not come up")
            return 1
        print("  OK")

        print("== Starting bundled orchestrator executable (zero-config) ==")
        orch_dir = scratch / "orch"
        orch_dir.mkdir()
        orch_log = open(scratch / "orchestrator.log", "w")
        procs.append(subprocess.Popen(
            [str(orch_exe)],
            cwd=str(orch_dir),
            env={"GRUPER_ORCHESTRATOR_PORT": str(ORCH_PORT)},
            stdout=orch_log, stderr=subprocess.STDOUT,
        ))
        if not _wait_http(f"{ORCH_URL}/v1/health", 20):
            print("FAIL: bundled orchestrator did not come up — see", orch_log.name)
            return 1
        db_exists = (orch_dir / "orchestrator.db").is_file()
        secret_exists = (orch_dir / ".gruper_jwt_secret").is_file()
        print(f"  OK — orchestrator.db created: {db_exists}, JWT secret auto-generated: {secret_exists}")
        if not (db_exists and secret_exists):
            print("FAIL: zero-config artifacts missing")
            return 1

        print("== Registering user + agent via REST ==")
        status, token_resp = _post(f"{ORCH_URL}/v1/auth/token",
                                    {"pubkey": _rand_pubkey(), "display_name": "Desktop Validation"})
        if status != 200:
            print("FAIL: token issuance", status, token_resp)
            return 1
        token = token_resp["token"]

        status, agent_resp = _post(
            f"{ORCH_URL}/v1/agents",
            {
                "name": "desktop-packaged-agent",
                "pubkey": _rand_pubkey(),
                "capabilities": {"models": ["llama3.1:8b"], "roles": ["analyst"], "tools": [], "hardware": {}},
                "runtime_version": "gd-0.1.0",
            },
            token=token,
        )
        if status != 201:
            print("FAIL: agent registration", status, agent_resp)
            return 1
        agent_id = agent_resp["id"]
        print(f"  OK — agent_id={agent_id[:8]}…")

        print("== Starting bundled agent executable ==")
        agent_dir = scratch / "agent"
        agent_dir.mkdir()
        agent_log = open(scratch / "agent.log", "w")
        procs.append(subprocess.Popen(
            [str(agent_exe)],
            cwd=str(agent_dir),
            env={
                "ORCHESTRATOR_URL": f"ws://127.0.0.1:{ORCH_PORT}/v1/agents/ws",
                "AGENT_ID": agent_id,
                "JWT_TOKEN": token,
                "OLLAMA_URL": f"http://127.0.0.1:{OLLAMA_PORT}",
                "LOG_LEVEL": "INFO",
            },
            stdout=agent_log, stderr=subprocess.STDOUT,
        ))

        print("== Waiting for agent to come online ==")
        online = False
        for _ in range(50):
            req = urllib.request.Request(f"{ORCH_URL}/v1/agents", headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=5) as r:
                agents = json.loads(r.read())
            if any(a["id"] == agent_id and a["status"] == "idle" for a in agents):
                online = True
                break
            time.sleep(0.3)
        if not online:
            print("FAIL: bundled agent never came online — see", agent_log.name)
            return 1
        print("  OK — agent status=idle")

        print("== Submitting a task ==")
        status, task = _post(
            f"{ORCH_URL}/v1/tasks",
            {
                "assigned_agent_id": agent_id,
                "data_class": "public",
                "input": {"prompt": "Validate packaged desktop binaries.", "role_template": "analyst"},
                "priority": 50,
                "timeout_s": 60,
            },
            token=token,
        )
        if status != 201:
            print("FAIL: task submit", status, task)
            return 1
        task_id = task["id"]

        print("== Waiting for task to complete ==")
        done = False
        for _ in range(60):
            req = urllib.request.Request(f"{ORCH_URL}/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=5) as r:
                trow = json.loads(r.read())
            if trow["status"] == "complete":
                done = True
                break
            time.sleep(0.3)
        if not done:
            print("FAIL: task never completed —", trow.get("status"))
            return 1
        print("  OK — task complete, output:", (trow.get("result") or {}).get("output"))

        print("\nRESULT: ALL GREEN — packaged orchestrator + packaged agent validated end to end")
        return 0
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


if __name__ == "__main__":
    sys.exit(main())
