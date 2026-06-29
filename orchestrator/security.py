import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .config import settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer()


def issue_token(user_id: str) -> tuple[str, datetime]:
    """Create a signed JWT for the given user and return (token_string, expiry)."""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "exp": expires_at}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def verify_token(token: str) -> dict:
    """Decode and verify a JWT.  Raises ValueError on any failure.

    Use this in non-HTTP contexts (e.g. WebSocket handlers) where raising an
    HTTPException would be semantically wrong.  HTTP routes should use the
    get_current_user_id dependency instead, which converts the ValueError to a
    proper 401 response.
    """
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError(f"Invalid or expired token: {exc}") from exc


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """FastAPI dependency: extract user_id from a Bearer JWT.

    Returns the subject claim (user UUID string) on success.
    Raises HTTP 401 if the token is missing, malformed, or expired.
    Raises HTTP 403 if no Authorization header is present at all
    (HTTPBearer's default behaviour when auto_error=True).
    """
    try:
        payload = verify_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return payload["sub"]
