"""
Gruper Agent Runtime — entry point.

Run from the agent-runtime/ directory:

    python main.py

Prerequisites (set in .env or environment):
    ORCHESTRATOR_URL  — WSS endpoint of the orchestrator
    AGENT_ID          — UUID assigned by POST /v1/agents
    JWT_TOKEN         — token from POST /v1/auth/token
"""

import asyncio
import logging
import signal
import sys

from config import settings
from ws_client import AgentWSClient

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def _run() -> None:
    if not settings.agent_id:
        logger.error(
            "AGENT_ID is not set. Register this agent first:\n"
            "  curl -X POST <orchestrator>/v1/agents -H 'Authorization: Bearer <jwt>' ...\n"
            "Then set AGENT_ID in .env to the returned id."
        )
        sys.exit(1)
    if not settings.jwt_token:
        logger.error(
            "JWT_TOKEN is not set. Obtain one first:\n"
            "  curl -X POST <orchestrator>/v1/auth/token ...\n"
            "Then set JWT_TOKEN in .env."
        )
        sys.exit(1)

    client = AgentWSClient()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(client.stop()))

    logger.info(
        "Gruper Agent Runtime %s starting (agent_id=%s)",
        settings.runtime_version,
        settings.agent_id,
    )
    await client.start()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
