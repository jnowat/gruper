"""
Structured, category-tagged logging for the Gruper sidecars (Desktop Hardening).

Both the orchestrator and the agent-runtime run as Tauri sidecar processes whose
stdout is drained by the Console (see console/src-tauri/src/lib.rs). This module
turns each Python log record into a single JSON line on stdout, prefixed with an
ASCII Record Separator (0x1e) sentinel, so the Rust side can tell a structured
log line apart from an arbitrary print()/traceback and feed it into the one
unified, exportable debug log the Console shows the user.

The same JSON shape is produced by the Rust and Svelte tiers — see LogEntry in
console/src-tauri/src/lib.rs and console/src/lib/stores/logs.ts — so a single
flow (sidecar spawn, agent registration, task dispatch) can be filtered
end-to-end across all four tiers by task_id / agent_id.

Secrets (JWTs, ?token= URLs, Bearer headers, pubkeys, signatures) are redacted
here, at emit time, before the line is ever written — defense in depth with the
Rust sink, which redacts again before an entry enters the ring buffer.

NOTE: this file is intentionally duplicated verbatim in agent-runtime/ so each
sidecar packages standalone (PyInstaller bundles each directory separately).
Keep the two copies in sync.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

# A line that starts with this byte is a structured Gruper log line; anything
# else on the pipe (a traceback, a third-party print, uvicorn's own banner) is
# passed through by the Rust drain as a raw 'sidecar' entry. A sentinel byte is
# unambiguous where '{'-sniffing would be fragile against pretty-printed JSON
# inside a traceback.
SENTINEL = "\x1e"

_LEVEL = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warn",
    "ERROR": "error",
    "CRITICAL": "error",
}

# Map a (dotted) logger name to a debug category. First match wins, so list
# more specific prefixes before their parents.
_CATEGORY_BY_PREFIX = [
    ("orchestrator.ws", "ws"),
    ("orchestrator.routers.auth", "auth"),
    ("orchestrator.routers.tasks", "task"),
    ("orchestrator.routers.agents", "agent"),
    ("orchestrator.dispatcher", "task"),
    ("orchestrator.security", "auth"),
    ("orchestrator", "orchestrator"),
    ("ws_client", "agent"),
    ("ollama_client", "ollama"),
    ("offline_queue", "agent"),
    ("circuit_breaker", "agent"),
]


def _category_from_name(name: str, default: str) -> str:
    for prefix, cat in _CATEGORY_BY_PREFIX:
        if name == prefix or name.startswith(prefix + "."):
            return cat
    return default


# ── Redaction (mirrors the Rust sink's rules in lib.rs) ───────────────────────
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")
_TOKEN_QS_RE = re.compile(r"([?&](?:token|jwt)=)[^&\s\"']+", re.IGNORECASE)
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")
_SECRET_KEY_RE = re.compile(
    r"(?i)(pub_?key|x25519|token_string|secret|password|priv(?:_?key)?|signature|jwt)"
)


def _redact_str(s: str) -> str:
    s = _JWT_RE.sub("<jwt:redacted>", s)
    s = _TOKEN_QS_RE.sub(r"\1<redacted>", s)
    s = _BEARER_RE.sub(r"\1<redacted>", s)
    return s


def _redact_fields(fields: dict) -> dict:
    out: dict = {}
    for k, v in fields.items():
        if isinstance(k, str) and _SECRET_KEY_RE.search(k):
            out[k] = "<redacted>"
        elif isinstance(v, str):
            out[k] = _redact_str(v)
        elif isinstance(v, dict):
            out[k] = _redact_fields(v)
        else:
            out[k] = v
    return out


class JsonLineHandler(logging.Handler):
    """A logging.Handler that writes one sentinel-prefixed JSON line per record."""

    def __init__(self, tier: str) -> None:
        super().__init__()
        self.tier = tier

    def emit(self, record: logging.LogRecord) -> None:
        try:
            fields = getattr(record, "fields", None)
            if not isinstance(fields, dict):
                fields = {}
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "level": _LEVEL.get(record.levelname, "info"),
                "category": getattr(record, "category", None)
                or _category_from_name(record.name, self.tier),
                "tier": self.tier,
                "agent_id": getattr(record, "agent_id", None),
                "task_id": getattr(record, "task_id", None),
                "msg": _redact_str(record.getMessage()),
                "fields": _redact_fields(fields),
            }
            sys.stdout.write(SENTINEL + json.dumps(entry, default=str) + "\n")
            sys.stdout.flush()
        except Exception:  # logging must never crash the process
            self.handleError(record)


def configure_logging(tier: str, level: str = "INFO") -> None:
    """Install the structured JSON handler on the root logger.

    Replaces logging.basicConfig for the sidecars. Called once at startup from
    each main.py, before uvicorn.run / the WS client starts. uvicorn installs
    its own stderr handlers for the uvicorn* loggers when it runs; those lines
    arrive at the Console as raw 'sidecar' entries, while every application
    logger (which propagates to root) is captured structured on stdout.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(JsonLineHandler(tier))
    try:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
    except Exception:
        root.setLevel(logging.INFO)
