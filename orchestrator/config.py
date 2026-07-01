import secrets
import warnings
from contextlib import suppress
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT = "change-me-in-production"

# Where a zero-config desktop run persists an auto-generated JWT secret so
# restarts don't invalidate every previously issued token. Same relative-to-
# CWD convention as the default SQLite file (orchestrator.db) and the
# agent's agent.db.
_JWT_SECRET_FILE = Path(".gruper_jwt_secret")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database — desktop-first default: an embedded SQLite file, no server
    # to install or run. Set DATABASE_URL to a postgresql:// DSN to opt
    # into the PostgreSQL/server tier (multi-user, production deployments).
    database_url: str = "sqlite:///orchestrator.db"

    # JWT — HS256 for gd-0.1; ed25519 signing added at WP-07
    jwt_secret: str = _INSECURE_DEFAULT
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Orchestrator identity
    orchestrator_version: str = "gd-0.1.0"

    # Heartbeat watchdog
    heartbeat_timeout_s: int = 90
    heartbeat_check_interval_s: int = 15

    # CORS — restrict in production; wildcard is only appropriate for dev/testing
    cors_origins: list[str] = ["*"]

    log_level: str = "INFO"

    @field_validator("jwt_secret")
    @classmethod
    def resolve_jwt_secret(cls, v: str) -> str:
        """Auto-generate and persist a JWT secret for zero-config desktop runs.

        Without this, an unconfigured orchestrator would sign every token
        with a literal, publicly-known string — anyone who's read this file
        could forge a valid JWT. That's a real vulnerability, not just a
        packaging inconvenience, so this resolves unconditionally (desktop
        AND server tier), not only in the packaged/frozen build. Explicitly
        setting JWT_SECRET (env var or .env — including docker-compose's
        required JWT_SECRET) always wins; this only ever fires when the
        setting was left at its class default.
        """
        if v != _INSECURE_DEFAULT:
            return v

        if _JWT_SECRET_FILE.exists():
            with suppress(OSError):
                return _JWT_SECRET_FILE.read_text().strip()

        generated = secrets.token_hex(32)
        try:
            _JWT_SECRET_FILE.write_text(generated)
            with suppress(OSError):
                _JWT_SECRET_FILE.chmod(0o600)
            warnings.warn(
                f"JWT_SECRET not set — generated one and saved it to {_JWT_SECRET_FILE.resolve()} "
                "(delete that file to generate a new one; existing sessions will be invalidated). "
                "Set JWT_SECRET explicitly for reproducible/server deployments.",
                stacklevel=2,
            )
        except OSError:
            warnings.warn(
                "JWT_SECRET not set and a generated secret could not be saved "
                f"to {_JWT_SECRET_FILE.resolve()} — using a one-time secret for this "
                "run only; every session will need to re-authenticate after restart.",
                stacklevel=2,
            )
        return generated


settings = Settings()
