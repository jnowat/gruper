import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..database import append_event
from ..security import issue_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    pubkey: str = Field(..., min_length=43, max_length=88)
    display_name: str = Field(..., min_length=1, max_length=64)


class TokenResponse(BaseModel):
    token: str
    expires_at: str
    user_id: str


@router.post("/token", response_model=TokenResponse)
async def get_token(body: TokenRequest, request: Request) -> TokenResponse:
    """
    Find-or-create a user by pubkey, then issue a HS256 JWT.

    Signature verification is stubbed in gd-0.1 (WP-07 adds ed25519 challenge-response).
    """
    pool = request.app.state.pool

    row = await pool.fetchrow(
        "SELECT id::text FROM users WHERE pubkey = $1", body.pubkey
    )

    if row:
        user_id = row["id"]
        action = "user.token_issued"
    else:
        row = await pool.fetchrow(
            "INSERT INTO users (pubkey, display_name) VALUES ($1, $2) RETURNING id::text",
            body.pubkey,
            body.display_name,
        )
        user_id = row["id"]
        action = "user.created"
        logger.info("Created user %s", user_id)

    await append_event(pool, actor_id=user_id, action=action, subject_id=user_id)

    token, expires_at = issue_token(user_id)
    return TokenResponse(token=token, expires_at=expires_at.isoformat(), user_id=user_id)
