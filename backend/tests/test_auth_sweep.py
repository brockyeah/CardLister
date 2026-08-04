"""Every /api route must reject unauthenticated requests with 401.

Walks the app's OpenAPI schema so a future router (or a route added to an
existing router) that forgets `Depends(require_auth)` fails this sweep
automatically. The schema is used instead of `app.routes` because FastAPI
keeps included routers nested there (they stopped being flattened into
APIRoute entries), while the schema always lists every route with its full
path. Only login and the health check are public by design.
"""
import re

import pytest
from fastapi.testclient import TestClient

from backend.main import app

PUBLIC = {
    ("/api/auth/login", "POST"),
    ("/api/health", "GET"),
}


def _protected_routes():
    for path, methods in app.openapi()["paths"].items():
        if not path.startswith("/api"):
            continue
        for method in methods:
            method = method.upper()
            if method in ("HEAD", "OPTIONS") or (path, method) in PUBLIC:
                continue
            yield path, method


def test_sweep_finds_routes():
    # Guard the sweep itself: if route collection ever breaks, the
    # parametrized test below would silently pass with zero cases.
    assert len(list(_protected_routes())) >= 20


@pytest.mark.parametrize("path,method", sorted(_protected_routes()))
def test_api_route_requires_auth(path, method):
    url = re.sub(r"\{[^}]+\}", "1", path)  # fill path params with a dummy id
    with TestClient(app) as client:
        r = client.request(method, url)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}: {r.text[:200]}"
