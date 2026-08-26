"""SPA deep links must survive a hard load.

`StaticFiles(html=True)` only serves index.html for directory requests, so
refreshing or bookmarking /inventory used to return `{"detail":"Not Found"}`.
`SpaStaticFiles` falls back to index.html for unmatched page loads while
leaving API and upload paths as real 404s.

The mount is only wired up when `backend/static` exists (the Dockerfile builds
it), so these tests mount the class on a throwaway app over a temp directory
rather than depending on a built frontend being present.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.main import SpaStaticFiles

INDEX_HTML = "<!doctype html><title>CardLister</title><div id=root></div>"


@pytest.fixture
def client(tmp_path):
    (tmp_path / "index.html").write_text(INDEX_HTML)
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-abc123.js").write_text("console.log('bundle')")

    app = FastAPI()
    app.mount("/", SpaStaticFiles(directory=str(tmp_path), html=True), name="static")
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/inventory",
        "/analytics",
        "/inventory?card=123",
        # Shares a prefix with an excluded root but is a distinct segment.
        "/apikeys",
    ],
)
def test_page_loads_serve_the_spa_shell(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "CardLister" in r.text


def test_head_requests_are_page_loads_too(client):
    # Link previews and uptime checks HEAD deep links; they must get the shell.
    r = client.head("/inventory")
    assert r.status_code == 200
    # Same cache contract as GET — the header logic is shared, but only GET was
    # pinned, so a HEAD-specific regression would have been silent.
    assert r.headers["cache-control"] == "no-cache"
    assert client.head("/assets/index-abc123.js").headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )


def test_real_assets_still_win_over_the_fallback(client):
    r = client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert "bundle" in r.text


def test_shell_revalidates_but_hashed_assets_cache_forever(client):
    # A heuristically cached shell outlives its bundles across a deploy and
    # white-screens on the /assets 404 — the shell must always revalidate.
    for path in ("/", "/inventory"):
        assert client.get(path).headers["cache-control"] == "no-cache"
    # Bundle names are content-hashed, so they get the /uploads treatment.
    r = client.get("/assets/index-abc123.js")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize(
    "path",
    [
        "/api/nope",
        "/api/cards/999999",
        "/uploads/missing.png",
        "/assets/index-deadbeef.js",
        # Case-folded: an API path is an API path however it's typed.
        "/API/nope",
        "/Uploads/missing.png",
        # Bare roots, not just descendants.
        "/api",
        "/uploads",
        "/assets",
    ],
)
def test_api_upload_and_asset_paths_keep_their_404(client, path):
    r = client.get(path)
    assert r.status_code == 404
    assert "CardLister" not in r.text


def test_non_page_methods_keep_their_404(client):
    # A POST to a bad path is a client bug, not a page load.
    r = client.post("/inventory")
    assert r.status_code in (404, 405)
    assert "CardLister" not in r.text
