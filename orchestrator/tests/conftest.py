"""
Shared fixtures for Gruper Orchestrator smoke tests.

Tests run against an in-process ASGI app backed by a real PostgreSQL database.
Set TEST_DATABASE_URL before running (defaults to a local gruper_test database):

    TEST_DATABASE_URL=postgresql://gruper:gruper@localhost:5432/gruper_test pytest

The test database schema is wiped at the start of each test session and rebuilt
by the app's own migration runner on first startup, so tests always start clean.

pytest.ini sets pythonpath = .. (repo root) so that "from orchestrator.main import app"
resolves whether pytest is invoked from orchestrator/ or from the repo root.
"""

import asyncio
import base64
import os
import secrets

import asyncpg
import pytest
from starlette.testclient import TestClient

# Set env vars before importing the app so pydantic-settings picks them up.
_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://gruper:gruper@localhost:5432/gruper_test"
)
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
def reset_test_db() -> None:
    """Drop and re-migrate all tables so each test session starts clean."""
    async def _reset() -> None:
        conn = await asyncpg.connect(_TEST_DB_URL)
        try:
            await conn.execute(
                "DROP TABLE IF EXISTS events, tasks, agents, users, schema_migrations CASCADE"
            )
        finally:
            await conn.close()

    asyncio.run(_reset())


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
