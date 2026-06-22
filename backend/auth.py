"""Auth: a small fixed set of named users (owner + one other), JWT sessions.

Users are configured via the CARDLISTER_USERS env var as a comma-separated list
of `username:password` pairs, e.g. `brock:s3cret,sam:hunter2`. If it's unset we
fall back to a single `owner` user whose password is CARDLISTER_PASSWORD — so
existing single-user setups keep working unchanged.
"""
import hmac
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "changeme"
DEFAULT_JWT_SECRET = "dev-insecure-secret-change-me"
DEFAULT_USERNAME = "owner"

JWT_SECRET = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = 24 * 30  # 30 days — small trusted user set, long sessions are fine

# auto_error=False so we can return our own clean 401 message instead of FastAPI's default
bearer_scheme = HTTPBearer(auto_error=False)


def get_password() -> str:
    """The fallback single-user password. Defaults to 'changeme' for first-run."""
    return os.getenv("CARDLISTER_PASSWORD", DEFAULT_PASSWORD)


def get_users() -> Dict[str, str]:
    """Parse CARDLISTER_USERS into {username: password}.

    Falls back to a single `owner` user (CARDLISTER_PASSWORD) when unset/empty.
    """
    raw = os.getenv("CARDLISTER_USERS", "").strip()
    if not raw:
        return {DEFAULT_USERNAME: get_password()}

    users: Dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        username, _, password = entry.partition(":")
        username = username.strip()
        if username:
            users[username] = password
    # If parsing yielded nothing usable, keep the app usable via the fallback.
    return users or {DEFAULT_USERNAME: get_password()}


def authenticate(username: str, password: str) -> bool:
    """Constant-time check of a username/password pair against configured users."""
    expected = get_users().get(username)
    if expected is None:
        return False
    return hmac.compare_digest(password, expected)


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
    if not os.getenv("CARDLISTER_USERS", "").strip():
        # Single-user fallback path — the default password is the risk.
        if get_password() == DEFAULT_PASSWORD:
            problems.append("CARDLISTER_PASSWORD is unset or still 'changeme' (and CARDLISTER_USERS is not set)")
    else:
        weak = [u for u, p in get_users().items() if not p or p == DEFAULT_PASSWORD]
        if weak:
            problems.append(f"CARDLISTER_USERS has empty/default passwords for: {', '.join(weak)}")
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


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """Dependency: reject unauthenticated requests; return the current username.

    Works both as a route guard (`dependencies=[Depends(require_auth)]`) and as a
    value dependency (`user: str = Depends(require_auth)`) to attribute usage.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return username
