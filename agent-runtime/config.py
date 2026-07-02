"""
All configuration is read from environment variables or a .env file.
Copy .env.example to .env and fill in ORCHESTRATOR_URL, AGENT_ID, and JWT_TOKEN
before starting the runtime.
"""

import json

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Orchestrator WSS endpoint — must end with /v1/agents/ws
    orchestrator_url: str = "wss://localhost:8080/v1/agents/ws"

    # UUID assigned by POST /v1/agents; required before connecting
    agent_id: str = ""

    # JWT obtained via POST /v1/auth/token; required before connecting
    jwt_token: str = ""

    # Local Ollama base URL
    ollama_url: str = "http://localhost:11434"

    # SQLite offline queue file; created on first run
    db_path: str = "agent.db"

    # How often to send heartbeat frames (orchestrator times out after 90 s)
    heartbeat_interval_s: int = 30

    # How many Ollama requests may run at once. Default 1: concurrent model
    # runs thrash RAM on typical desktop hardware and make every answer
    # slower; queued tasks show a "waiting for another answer…" step instead.
    ollama_max_concurrency: int = 1

    # Capability descriptor sent to the orchestrator on registration
    capabilities: str = (
        '{"models":[],"roles":[],"tools":[],'
        '"hardware":{"cpu_cores":1,"ram_gb":1}}'
    )

    log_level: str = "INFO"

    # Frozen at build time; must match the ^gd-\d+\.\d+\.\d+ pattern.
    # gd-0.3.0: Ollama-reliability runtime (half-open circuit breaker,
    # classified errors, revoke support, no local queue re-execution).
    runtime_version: str = "gd-0.3.0"

    def capabilities_dict(self) -> dict:
        return json.loads(self.capabilities)


settings = Settings()
