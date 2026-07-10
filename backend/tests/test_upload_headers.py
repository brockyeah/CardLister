"""Security headers on served uploads: nosniff everywhere; non-image files
(PDFs) must download rather than render in the app's origin."""
import io

from PIL import Image
from fastapi.testclient import TestClient

from backend.main import app


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (30, 90, 50)).save(buf, format="PNG")
    buf.seek(0)
    return buf


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _scan_upload(client, headers, filename, content, content_type):
    r = client.post(
        "/api/scan",
        files={"image": (filename, content, content_type)},
        data={"preset": "balance"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["image_path"]


def test_image_upload_served_inline_with_nosniff():
    with TestClient(app) as client:
        path = _scan_upload(client, _auth(client), "front.png", _png_bytes(), "image/png")
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["x-content-type-options"] == "nosniff"
        # Images stay inline so <img> thumbnails and direct viewing keep working.
        assert "attachment" not in r.headers.get("content-disposition", "")


def test_pdf_upload_forced_to_download():
    with TestClient(app) as client:
        pdf = io.BytesIO(b"%PDF-1.4 fake test document")
        path = _scan_upload(client, _auth(client), "scan.pdf", pdf, "application/pdf")
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-disposition"].startswith("attachment")


def test_upload_save_failure_returns_generic_detail(monkeypatch):
    # Force the save to blow up with a message containing an internal path;
    # the client-visible detail must not echo it.
    import backend.routers.scan as scan_module

    async def _boom(upload, uploads):
        raise OSError("/data/uploads is on fire: secret internal detail")

    monkeypatch.setattr(scan_module, "_save_upload", _boom)
    with TestClient(app) as client:
        r = client.post(
            "/api/scan",
            files={"image": ("front.png", _png_bytes(), "image/png")},
            data={"preset": "balance"},
            headers=_auth(client),
        )
        assert r.status_code == 500
        assert r.json()["detail"] == "Failed to save upload."
        assert "secret internal detail" not in r.text
