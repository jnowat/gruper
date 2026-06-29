import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..database import append_event
from ..security import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCapabilities(BaseModel):
    models: list[str] = Field(..., min_length=1)
    roles: list[str] = Field(..., min_length=1)
    tools: list[str] = Field(default_factory=list)
    hardware: dict[str, Any] = Field(default_factory=dict)


class AgentAvailability(BaseModel):
    always_on: bool = False
    windows: list[str] = Field(default_factory=list)


class AgentRegistrationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    pubkey: str = Field(..., min_length=43, max_length=88)
    capabilities: AgentCapabilities
    availability: AgentAvailability | None = None
    runtime_version: str
    location_tag: str | None = None
    jurisdiction: str | None = Field(None, max_length=8)
    metadata: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    pubkey: str
    status: str
    runtime_version: str
    capabilities: dict[str, Any]
    availability: dict[str, Any] | None
    location_tag: str | None
    jurisdiction: str | None
    last_seen: str | None
    created_at: str


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def register_agent(
    body: AgentRegistrationRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> AgentResponse:
    pool = request.app.state.pool

    existing = await pool.fetchrow(
        "SELECT id::text FROM agents WHERE pubkey = $1", body.pubkey
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An agent with this pubkey is already registered",
        )

    capabilities_json = body.capabilities.model_dump()
    availability_json = body.availability.model_dump() if body.availability else None

    row = await pool.fetchrow(
        """
        INSERT INTO agents
            (owner_id, pubkey, name, capabilities, availability, runtime_version,
             location_tag, jurisdiction, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING
            id::text, owner_id::text, name, pubkey, status, runtime_version,
            capabilities, availability, location_tag, jurisdiction,
            last_seen, created_at
        """,
        user_id,
        body.pubkey,
        body.name,
        capabilities_json,
        availability_json,
        body.runtime_version,
        body.location_tag,
        body.jurisdiction,
        body.metadata,
    )

    await append_event(
        pool,
        actor_id=user_id,
        action="agent.registered",
        subject_id=row["id"],
        metadata={"name": body.name, "runtime_version": body.runtime_version},
    )
    logger.info("Agent %s registered by user %s", row["id"], user_id)

    return _row_to_response(row)


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> list[AgentResponse]:
    pool = request.app.state.pool
    rows = await pool.fetch(
        """
        SELECT
            id::text, owner_id::text, name, pubkey, status, runtime_version,
            capabilities, availability, location_tag, jurisdiction,
            last_seen, created_at
        FROM agents
        WHERE owner_id = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
    return [_row_to_response(r) for r in rows]


def _row_to_response(row: Any) -> AgentResponse:
    return AgentResponse(
        id=row["id"],
        owner_id=row["owner_id"],
        name=row["name"],
        pubkey=row["pubkey"],
        status=row["status"],
        runtime_version=row["runtime_version"],
        capabilities=dict(row["capabilities"]),
        availability=dict(row["availability"]) if row["availability"] else None,
        location_tag=row["location_tag"],
        jurisdiction=row["jurisdiction"],
        last_seen=row["last_seen"].isoformat() if row["last_seen"] else None,
        created_at=row["created_at"].isoformat(),
    )
