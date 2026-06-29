from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://gruper:gruper@localhost:5432/gruper"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    orchestrator_version: str = "gd-0.1.0"
    heartbeat_timeout_s: int = 90
    heartbeat_check_interval_s: int = 15

    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    @field_validator("jwt_secret")
    @classmethod
    def warn_default_secret(cls, v: str) -> str:
        if v == "change-me-in-production":
            import warnings
            warnings.warn("JWT_SECRET is using the insecure default — set it in .env", stacklevel=2)
        return v


settings = Settings()
