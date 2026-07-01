"""
Shared fixtures for Gruper Orchestrator smoke tests.

Tests run against an in-process ASGI app. By default they run against a
fresh SQLite temp file — the desktop-tier default, no external service
required. Set TEST_DATABASE_URL to opt into the PostgreSQL/server tier:

    TEST_DATABASE_URL=postgresql://gruper:gruper@localhost:5432/gruper_test pytest

Both legs run the identical test suite; CI runs both as separate matrix jobs
(see .github/workflows/orchestrator-tests.yml).

pytest.ini sets pythonpath = .. (repo root) so that "from orchestrator.main import app"
resolves whether pytest is invoked from orchestrator/ or from the repo root.
"""

import asyncio
import base64
import os
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pytest
from starlette.testclient import TestClient

# Set env vars before importing the app so pydantic-settings picks them up.
_env_db_url = os.environ.get("TEST_DATABASE_URL")
if _env_db_url:
    # PostgreSQL leg — explicit opt-in, e.g. in the server-tier CI matrix job.
    _TEST_DB_URL = _env_db_url
    _sqlite_tmp_path: Path | None = None
else:
    # SQLite leg (default) — a fresh temp file for this test session, no
    # external service required. This is what a plain `pytest` run uses.
    _fd, _sqlite_tmp_name = tempfile.mkstemp(prefix="gruper_test_", suffix=".db")
    os.close(_fd)
    _sqlite_tmp_path = Path(_sqlite_tmp_name)
    _sqlite_tmp_path.unlink()  # SQLiteDatabase.connect() creates it fresh
    _TEST_DB_URL = f"sqlite:///{_sqlite_tmp_path}"

os.environ.setdefault("DATABASE_URL", _TEST_DB_URL)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from orchestrator.main import app  # noqa: E402 — must come after env vars are set


def _rand_pubkey() -> str:
    """Return a random base64url-encoded 32-byte value (43 chars, no padding).

    32 bytes → ceil(32 × 4/3) = 44 chars with padding, 43 chars stripped.
    This satisfies the pubkey min_length=43 constraint from the user/agent schemas.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


@pytest.fixture(scope="session", autouse=True)
def reset_test_db():
    """Ensure each test session starts clean, then clean up afterwards.

    PostgreSQL: drop all tables; the app's own migration runner rebuilds
    them on TestClient startup. SQLite: the temp file is already fresh
    (never created until SQLiteDatabase.connect() runs the migrations);
    just remove it when the session ends.
    """
    scheme = urlparse(_TEST_DB_URL).scheme
    if scheme in ("postgresql", "postgres"):
        import asyncpg

        async def _reset() -> None:
            conn = await asyncpg.connect(_TEST_DB_URL)
            try:
                await conn.execute(
                    "DROP TABLE IF EXISTS events, tasks, agents, users, schema_migrations CASCADE"
                )
            finally:
                await conn.close()

        asyncio.run(_reset())

    yield

    if _sqlite_tmp_path is not None:
        _sqlite_tmp_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(_sqlite_tmp_path) + suffix).unlink(missing_ok=True)


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def pubkey() -> str:
    """Return a unique random pubkey per test (base64url, 43 chars, no padding)."""
    return _rand_pubkey()


@pytest.fixture
def auth_token(client: TestClient, pubkey: str) -> tuple[str, str]:
    """Register (or re-identify) a user and return (jwt_token, user_id)."""
    resp = client.post(
        "/v1/auth/token",
        json={"pubkey": pubkey, "display_name": "Test User"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["token"], data["user_id"]
