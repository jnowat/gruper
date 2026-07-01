"""
Gruper Agent Runtime — entry point.

Run from the agent-runtime/ directory:

    python main.py

Prerequisites (set in .env or environment):
    ORCHESTRATOR_URL  — WSS endpoint of the orchestrator
    AGENT_ID          — UUID assigned by POST /v1/agents
    JWT_TOKEN         — token from POST /v1/auth/token

When GRUPER_EXIT_WITH_PARENT is set (the Console's "Add Local Agent" sidecar
spawn sets this — see console/src-tauri/src/lib.rs::spawn_local_agent), a
background thread self-terminates the process once its ancestry changes.
This mirrors orchestrator/packaging/entry.py's watchdog: relying on the
Console to clean up its spawned agent on exit is not reliable on a forceful
kill (Task Manager's "End Task"/TerminateProcess, or SIGKILL), which no
userspace code running inside the victim process can intercept. See that
module's docstring for why the full ancestor chain is walked rather than
just the immediate parent (PyInstaller's --onefile bootloader process).
Not set for a manually-run agent (`python main.py`, `.env`-configured) — it
must keep running independently of whatever shell started it.
"""

import asyncio
import logging
import os
import signal
import sys
import threading
import time

from config import settings
from structured_log import configure_logging
from ws_client import AgentWSClient

# Structured, category-tagged logging: emits one JSON line per record on stdout,
# which the Console drains and parses into its unified debug log (see
# agent-runtime/structured_log.py and console/src-tauri/src/lib.rs). Replaces
# logging.basicConfig so a freshly-spawned agent's activity is observable.
configure_logging("agent", settings.log_level)
logger = logging.getLogger(__name__)

_MAX_ANCESTOR_DEPTH = 6


def _capture_ancestors() -> list[tuple[int, float]]:
    """Return [(pid, create_time), ...] for this process's ancestors, closest first."""
    import psutil

    ancestors = []
    try:
        proc = psutil.Process()
        for _ in range(_MAX_ANCESTOR_DEPTH):
            parent = proc.parent()
            if parent is None:
                break
            try:
                ancestors.append((parent.pid, parent.create_time()))
            except psutil.Error:
                break
            proc = parent
    except psutil.Error:
        pass
    return ancestors


def _ancestor_unchanged(pid: int, create_time: float) -> bool:
    import psutil

    try:
        return abs(psutil.Process(pid).create_time() - create_time) < 1.0
    except psutil.Error:
        return False


def _exit_if_orphaned(poll_interval_s: float = 2.0) -> None:
    watched = _capture_ancestors()
    if not watched:
        return  # nothing meaningful to watch; don't loop forever on bad data
    while True:
        time.sleep(poll_interval_s)
        if not all(_ancestor_unchanged(pid, ct) for pid, ct in watched):
            os._exit(0)


def _print_standalone_help() -> None:
    """Shown when this program is run without AGENT_ID/JWT_TOKEN configured.

    That combination almost always means a user double-clicked
    gruper-agent.exe (or ran it from a shell) directly, rather than through
    the Console — the Console's "Add Local Agent" flow always sets both (see
    spawn_local_agent in console/src-tauri/src/lib.rs). Previously this
    printed a bare curl one-liner aimed at a developer manually driving the
    REST API; a new desktop user has no way to act on that. This message
    instead assumes the common case (wrong entry point) and gives the rare
    case (deliberate headless/manual run) a concrete next step.
    """
    print(
        "\n"
        "Gruper Agent is a background helper process for the Gruper Console —\n"
        "it isn't meant to be run directly like this.\n"
        "\n"
        "To add an agent:\n"
        "  1. Open the Gruper Console\n"
        "  2. Click \"+ Add\" in the Fleet sidebar\n"
        "  3. Follow the \"Add Local Agent\" dialog — it starts this program for\n"
        "     you automatically, with everything already filled in.\n"
        "\n"
        "Only if you deliberately want to run this agent by hand (e.g. a\n"
        "headless machine dialing out to a remote orchestrator): copy\n"
        ".env.example to .env next to this program and fill in\n"
        "ORCHESTRATOR_URL, AGENT_ID (from POST /v1/agents), and JWT_TOKEN\n"
        "(from POST /v1/auth/token).\n",
        file=sys.stderr,
    )


def _pause_before_exit() -> None:
    # A Windows double-click launch opens a fresh console window that closes
    # the instant the process exits — without this, the message above is
    # never actually seen. Only pause when stdin looks interactive; a
    # non-interactive invocation (CI, a script piping input) should just exit.
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("Press Enter to exit...")
    except (EOFError, OSError):
        pass


async def _run() -> None:
    if not settings.agent_id or not settings.jwt_token:
        _print_standalone_help()
        _pause_before_exit()
        sys.exit(1)

    client = AgentWSClient()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(client.stop()))
        except NotImplementedError:
            # loop.add_signal_handler is Unix-only — Windows' ProactorEventLoop
            # (required there for subprocess support) raises this unconditionally.
            # Without this guard the agent crashes on startup on every Windows
            # machine, which would have silently broken the desktop "Add Local
            # Agent" flow this runs under. Ctrl+C still works via the default
            # KeyboardInterrupt handling; GRUPER_EXIT_WITH_PARENT below covers
            # the Console-spawned shutdown path that matters for that flow.
            logger.warning(
                "Signal handlers are not supported on this platform's event loop "
                "(expected on Windows) — relying on default interrupt handling."
            )
            break

    if os.environ.get("GRUPER_EXIT_WITH_PARENT"):
        threading.Thread(target=_exit_if_orphaned, daemon=True).start()

    logger.info(
        "Gruper Agent Runtime %s starting (agent_id=%s)",
        settings.runtime_version,
        settings.agent_id,
    )
    await client.start()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
