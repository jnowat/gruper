"""
Task submission and retrieval endpoints.

POST /v1/tasks    — submit a task for dispatch to a registered agent
GET  /v1/tasks    — list tasks submitted by the caller
GET  /v1/tasks/{task_id} — get a specific task

Dispatch happens synchronously in POST /v1/tasks: if the assigned agent is
connected when the task is submitted, it is pushed immediately over WebSocket
and the response reflects status='dispatched'. If the agent is offline, the
task stays 'pending' and is dispatched on the agent's next WebSocket connect.
"""

import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from ..connection_manager import manager
from ..database import append_event
from ..dispatcher import try_dispatch
from ..security import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])

_DATA_CLASSES = {"public", "internal", "confidential"}

_TASK_SELECT = """
    id::text,
    submitter_id::text,
    assigned_agent_id::text,
    correlation_id::text,
    data_class,
    input,
    allowed_tools,
    status,
    priority,
    deadline,
    timeout_s,
    retry_count,
    created_at,
    dispatched_at,
    completed_at,
    result,
    error
"""


# ── Pydantic models ──────────────────────────────────────────────────────────

class _TaskInput(BaseModel):
    """Plaintext task input — mirrors task.schema.json TaskInputPlaintext."""
    prompt:            str                  = Field(..., min_length=1)
    system_prompt:     str | None           = None
    role_template:     str                  = "analyst"
    model_preferences: dict[str, Any] | None = None
    input_files:       list[Any]            = Field(default_factory=list)
    context:           dict[str, Any] | None = None


class TaskSubmitRequest(BaseModel):
    assigned_agent_id: str
    data_class:        str
    input:             _TaskInput
    priority:          int               = Field(50, ge=0, le=100)
    deadline:          str | None        = None   # ISO 8601 UTC; null = no deadline
    timeout_s:         int               = Field(300, ge=60, le=86400)
    correlation_id:    str | None        = None   # UUID; for idempotency
    allowed_tools:     list[str]         = Field(default_factory=list)

    @field_validator("data_class")
    @classmethod
    def _check_data_class(cls, v: str) -> str:
        if v not in _DATA_CLASSES:
            raise ValueError(f"data_class must be one of: {sorted(_DATA_CLASSES)}")
        return v


class TaskResponse(BaseModel):
    id:                str
    submitter_id:      str
    assigned_agent_id: str
    correlation_id:    str | None
    data_class:        str
    input:             dict[str, Any]
    allowed_tools:     list[str]
    status:            str
    priority:          int
    deadline:          str | None
    timeout_s:         int
    retry_count:       int
    created_at:        str
    dispatched_at:     str | None
    completed_at:      str | None
    result:            dict[str, Any] | None
    error:             dict[str, Any] | None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a task for dispatch to an agent",
    description=(
        "Creates a task and attempts immediate dispatch if the assigned agent "
        "is connected. If the agent is offline, the task stays 'pending' and "
        "is dispatched on the agent's next WebSocket connection. "
        "Providing `correlation_id` makes the call idempotent: a second request "
        "with the same submitter + correlation_id returns the existing task."
    ),
)
async def submit_task(
    body: TaskSubmitRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> TaskResponse:
    pool: asyncpg.Pool = request.app.state.pool

    # Validate agent exists and belongs to the caller.
    try:
        agent = await pool.fetchrow(
            "SELECT id::text, owner_id::text FROM agents WHERE id = $1::uuid",
            body.assigned_agent_id,
        )
    except asyncpg.InvalidTextRepresentationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="assigned_agent_id must be a valid UUID",
        )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent["owner_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this agent",
        )

    # Idempotency: return existing task if correlation_id already used.
    if body.correlation_id:
        try:
            existing_id = await pool.fetchval(
                """
                SELECT id::text FROM tasks
                WHERE submitter_id = $1::uuid AND correlation_id = $2::uuid
                """,
                user_id,
                body.correlation_id,
            )
        except asyncpg.InvalidTextRepresentationError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="correlation_id must be a valid UUID",
            )
        if existing_id:
            existing = await pool.fetchrow(
                f"SELECT {_TASK_SELECT} FROM tasks WHERE id = $1::uuid",
                existing_id,
            )
            return _row_to_response(existing)

    task_input = {
        "_type": "plaintext",
        "prompt":            body.input.prompt,
        "system_prompt":     body.input.system_prompt,
        "role_template":     body.input.role_template,
        "model_preferences": body.input.model_preferences,
        "input_files":       body.input.input_files,
        "context":           body.input.context,
    }

    row = await pool.fetchrow(
        f"""
        INSERT INTO tasks
            (submitter_id, assigned_agent_id, data_class, input, allowed_tools,
             priority, deadline, timeout_s, correlation_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7::timestamptz, $8, $9::uuid)
        RETURNING {_TASK_SELECT}
        """,
        user_id,
        body.assigned_agent_id,
        body.data_class,
        task_input,
        body.allowed_tools,
        body.priority,
        body.deadline,        # PostgreSQL parses ISO 8601 strings as TIMESTAMPTZ
        body.timeout_s,
        body.correlation_id,  # NULL when not provided
    )

    await append_event(
        pool,
        actor_id=user_id,
        action="task.submitted",
        subject_id=row["id"],
        metadata={"assigned_agent_id": body.assigned_agent_id, "data_class": body.data_class},
    )

    # Dispatch immediately if the agent is connected.
    await try_dispatch(pool, manager, row["id"])

    # Re-fetch to reflect the dispatched status if it was updated.
    final = await pool.fetchrow(
        f"SELECT {_TASK_SELECT} FROM tasks WHERE id = $1::uuid", row["id"]
    )
    return _row_to_response(final)


@router.get(
    "",
    response_model=list[TaskResponse],
    summary="List tasks submitted by the authenticated user",
)
async def list_tasks(
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> list[TaskResponse]:
    pool: asyncpg.Pool = request.app.state.pool
    rows = await pool.fetch(
        f"""
        SELECT {_TASK_SELECT} FROM tasks
        WHERE submitter_id = $1::uuid
        ORDER BY created_at DESC
        """,
        user_id,
    )
    return [_row_to_response(r) for r in rows]


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Get a task by ID",
)
async def get_task(
    task_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> TaskResponse:
    pool: asyncpg.Pool = request.app.state.pool
    try:
        row = await pool.fetchrow(
            f"SELECT {_TASK_SELECT} FROM tasks WHERE id = $1::uuid",
            task_id,
        )
    except asyncpg.InvalidTextRepresentationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="task_id must be a valid UUID",
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if row["submitter_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your task")
    return _row_to_response(row)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_response(row: asyncpg.Record) -> TaskResponse:
    def ts(val) -> str | None:
        return val.isoformat() if val is not None else None

    return TaskResponse(
        id=row["id"],
        submitter_id=row["submitter_id"],
        assigned_agent_id=row["assigned_agent_id"],
        correlation_id=row["correlation_id"],
        data_class=row["data_class"],
        input=dict(row["input"]) if row["input"] else {},
        allowed_tools=list(row["allowed_tools"]) if row["allowed_tools"] else [],
        status=row["status"],
        priority=row["priority"],
        deadline=ts(row["deadline"]),
        timeout_s=row["timeout_s"],
        retry_count=row["retry_count"],
        created_at=ts(row["created_at"]),
        dispatched_at=ts(row["dispatched_at"]),
        completed_at=ts(row["completed_at"]),
        result=dict(row["result"]) if row["result"] else None,
        error=dict(row["error"]) if row["error"] else None,
    )
