"""Password check + JWT issue/verify. One hardcoded password, no user accounts."""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = 24 * 30  # 30 days — this is a single-user tool, long sessions are fine

# auto_error=False so we can return our own clean 401 message instead of FastAPI's default
bearer_scheme = HTTPBearer(auto_error=False)


def get_password() -> str:
    """Read the configured password. Defaults to 'changeme' for first-run convenience."""
    return os.getenv("CARDLISTER_PASSWORD", "changeme")


def check_password(submitted: str) -> bool:
    return submitted == get_password()


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
