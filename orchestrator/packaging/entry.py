"""
PyInstaller entry point for the packaged orchestrator (WP-31).

Not used for normal development — `uvicorn orchestrator.main:app --reload` is
still the right way to run from source. This exists only so PyInstaller has a
script to bundle into a self-contained executable for desktop distribution.

The ASGI app is imported as an object (`from orchestrator.main import app`)
rather than passed to uvicorn as the string "orchestrator.main:app". PyInstaller
freezes the import system, so uvicorn's dynamic string-based import lookup
can't resolve the module inside the bundle — confirmed by testing; it fails
at runtime with "Could not import module" even though the build itself
succeeds. Importing directly lets PyInstaller's static analysis trace and
bundle the whole orchestrator package correctly.

Binds to 127.0.0.1 (not 0.0.0.0) by default: a desktop orchestrator has no
business listening on the network by default. Override with
GRUPER_ORCHESTRATOR_HOST / GRUPER_ORCHESTRATOR_PORT for LAN-shared setups.

When GRUPER_EXIT_WITH_PARENT is set (the Console's sidecar spawn sets this —
see console/src-tauri/src/lib.rs), a background thread self-terminates the
process once its ancestry changes. This exists because relying on the parent
to clean up its child on shutdown is NOT reliable: it was verified by testing
that a normal WindowEvent::Destroyed handler in the Console does not fire on
a forceful termination (SIGTERM sent directly to the process, and — by the
same mechanism on Windows — Task Manager's "End Task", which sends
TerminateProcess and cannot be intercepted by ANY code running inside the
victim process at all).

This walks the FULL ancestor chain, not just the immediate parent, and was
built that way only after the naive "did os.getppid() change" version was
tested and found NOT to work: PyInstaller's --onefile mode runs the actual
app as a *child* of its own bootloader process (confirmed by inspecting the
process tree — killing the Console left the bootloader alive as an orphan,
one level removed from us, so our immediate parent never appeared to
change even though the Console two levels up was gone). Recording every
ancestor's (pid, creation time) up to a depth limit and checking they're
ALL still exactly the same processes catches that. Creation time, not just
PID, guards against the OS reusing a dead ancestor's PID for an unrelated
process before this next poll.

Not set when running standalone (`uvicorn`, docker-compose,
scripts/build-desktop.sh's plain executable) — the orchestrator must keep
running independently of whatever shell/terminal happened to start it there.
"""

import os
import threading
import time

import psutil
import uvicorn

from orchestrator.main import app

_MAX_ANCESTOR_DEPTH = 6


def _capture_ancestors() -> list[tuple[int, float]]:
    """Return [(pid, create_time), ...] for this process's ancestors, closest first."""
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
            # At least one recorded ancestor (bootloader, Console, or
            # anything in between) is gone or has been replaced — we've
            # been orphaned. Exit immediately rather than run undetected.
            os._exit(0)


if __name__ == "__main__":
    if os.environ.get("GRUPER_EXIT_WITH_PARENT"):
        threading.Thread(target=_exit_if_orphaned, daemon=True).start()

    host = os.environ.get("GRUPER_ORCHESTRATOR_HOST", "127.0.0.1")
    port = int(os.environ.get("GRUPER_ORCHESTRATOR_PORT", "8080"))
    uvicorn.run(app, host=host, port=port, log_level=os.environ.get("LOG_LEVEL", "info").lower())
