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


def test_scan_accepts_optional_back_image():
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.post(
            "/api/scan",
            files={"image": ("front.png", _png_bytes(), "image/png"),
                   "back": ("back.png", _png_bytes(), "image/png")},
            data={"preset": "balance"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["image_path"].startswith("/uploads/")
        assert body["back_image_path"].startswith("/uploads/")


def test_scan_without_back_returns_null_back_path():
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.post(
            "/api/scan",
            files={"image": ("front.png", _png_bytes(), "image/png")},
            data={"preset": "balance"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["back_image_path"] is None
