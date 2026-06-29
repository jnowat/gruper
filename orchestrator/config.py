import warnings

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql://gruper:gruper@localhost:5432/gruper"

    # JWT — HS256 for gd-0.1; ed25519 signing added at WP-07
    jwt_secret: str = "change-me-in-production"
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
    def warn_default_secret(cls, v: str) -> str:
        if v == "change-me-in-production":
            warnings.warn(
                "JWT_SECRET is using the insecure default — set JWT_SECRET in .env",
                stacklevel=2,
            )
        return v


settings = Settings()
