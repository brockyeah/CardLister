"""Password check + JWT issue/verify. One hardcoded password, no user accounts."""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "changeme"
DEFAULT_JWT_SECRET = "dev-insecure-secret-change-me"

JWT_SECRET = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = 24 * 30  # 30 days — this is a single-user tool, long sessions are fine

# auto_error=False so we can return our own clean 401 message instead of FastAPI's default
bearer_scheme = HTTPBearer(auto_error=False)


def get_password() -> str:
    """Read the configured password. Defaults to 'changeme' for first-run convenience."""
    return os.getenv("CARDLISTER_PASSWORD", DEFAULT_PASSWORD)


def check_password(submitted: str) -> bool:
    return submitted == get_password()


def _is_production() -> bool:
    """Best-effort production detection.

    Explicit APP_ENV wins; otherwise treat a Railway-deployed service as production
    (Railway injects RAILWAY_ENVIRONMENT into every deploy).
    """
    env = os.getenv("APP_ENV", "").strip().lower()
    if env:
        return env in ("production", "prod")
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_ENVIRONMENT_NAME"))


def validate_secrets() -> None:
    """Fail fast in production if auth secrets are missing or left at their defaults.

    In local dev the defaults are allowed (with a loud warning) so the app still
    boots for first-run convenience.
    """
    problems = []
    if get_password() == DEFAULT_PASSWORD:
        problems.append("CARDLISTER_PASSWORD is unset or still 'changeme'")
    if JWT_SECRET == DEFAULT_JWT_SECRET:
        problems.append("JWT_SECRET is unset or still the insecure default")

    if not problems:
        return

    detail = "; ".join(problems)
    if _is_production():
        raise RuntimeError(
            f"Refusing to start with insecure auth secrets: {detail}. "
            "Set CARDLISTER_PASSWORD and JWT_SECRET in the environment "
            "(or set APP_ENV=development to bypass this check)."
        )
    logger.warning("Insecure auth secrets (acceptable for local dev only): %s", detail)


def create_token() -> str:
    payload = {
        "sub": "cardlister-user",
        "exp": datetime.utcnow() + timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    """Dependency: rejects the request if no/invalid Bearer token is present."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return True
