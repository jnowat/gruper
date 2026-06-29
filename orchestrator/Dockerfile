# Build context must be the repo root (gruper/), not the orchestrator/ subdirectory.
# docker-compose.yml sets context: .. to ensure this.
#
# The orchestrator package lives at /app/orchestrator/ so that
# "uvicorn orchestrator.main:app" resolves correctly with relative imports.

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY orchestrator/requirements.txt orchestrator/requirements.txt
RUN pip install --no-cache-dir -r orchestrator/requirements.txt

COPY orchestrator/ orchestrator/

EXPOSE 8080

# Development: --reload watches for file changes (requires the volume mount in docker-compose.yml).
# Production: remove --reload and the volume mount.
CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]
