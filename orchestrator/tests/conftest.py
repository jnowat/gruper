"""
Smoke-test fixtures for the Gruper Orchestrator.

Tests run against an in-process ASGI app backed by a real PostgreSQL database.
Set TEST_DATABASE_URL in the environment (or a local .env) before running:

    TEST_DATABASE_URL=postgresql://gruper:gruper@localhost:5432/gruper_test pytest

The test database is wiped and re-migrated at the start of each session.
"""

import asyncio
import os

import asyncpg
import pytest
from starlette.testclient import TestClient

# Override the database URL before the app module is imported so config picks it up.
_test_db_url = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://gruper:gruper@localhost:5432/gruper_test"
)
os.environ.setdefault("DATABASE_URL", _test_db_url)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
os.environ.setdefault("POSTGRES_PASSWORD", "gruper")

from orchestrator.main import app  # noqa: E402 — must come after env vars are set


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def reset_test_db(event_loop):
    """Drop and re-create all tables so tests always start clean."""

    async def _reset():
        conn = await asyncpg.connect(_test_db_url)
        await conn.execute(
            "DROP TABLE IF EXISTS events, tasks, agents, users, schema_migrations CASCADE"
        )
        await conn.close()

    event_loop.run_until_complete(_reset())


@pytest.fixture(scope="session")
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def pubkey() -> str:
    """Return a deterministic fake ed25519 pubkey (base64url, 44 chars)."""
    import secrets
    import base64
    raw = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture
def auth_token(client, pubkey) -> tuple[str, str]:
    """Register a user and return (token, user_id)."""
    resp = client.post(
        "/v1/auth/token",
        json={"pubkey": pubkey, "display_name": "Test User"},
    )
    assert resp.status_code == 200
    data = resp.json()
    return data["token"], data["user_id"]
