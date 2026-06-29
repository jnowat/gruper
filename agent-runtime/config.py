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

    # Capability descriptor sent to the orchestrator on registration
    capabilities: str = (
        '{"models":[],"roles":[],"tools":[],'
        '"hardware":{"cpu_cores":1,"ram_gb":1}}'
    )

    log_level: str = "INFO"

    # Frozen at build time; must match the ^gd-\d+\.\d+\.\d+ pattern
    runtime_version: str = "gd-0.1.0"

    def capabilities_dict(self) -> dict:
        return json.loads(self.capabilities)


settings = Settings()
