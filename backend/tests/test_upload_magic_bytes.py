"""Content sniffing on /api/scan uploads: the stored file's type comes from its
magic bytes, not the client-supplied filename — non-image content is rejected
with 415 and never lands in uploads/."""
import io

from PIL import Image
from fastapi.testclient import TestClient

from backend.database import uploads_dir
from backend.main import app


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (30, 90, 50)).save(buf, format="PNG")
    buf.seek(0)
    return buf


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _scan(client, headers, **files):
    return client.post("/api/scan", files=files, data={"preset": "balance"}, headers=headers)


def _upload_names():
    d = uploads_dir()
    return set(p.name for p in d.glob("*")) if d.exists() else set()


def test_non_image_content_rejected_and_not_stored():
    # An HTML payload with an image filename/content-type must not be stored
    # (it would be re-served from /uploads in the app's origin).
    with TestClient(app) as client:
        before = _upload_names()
        r = _scan(
            client, _auth(client),
            image=("photo.jpg", io.BytesIO(b"<html><script>alert(1)</script></html>"), "image/jpeg"),
        )
        assert r.status_code == 415, r.text
        assert _upload_names() == before


def test_junk_bytes_rejected():
    with TestClient(app) as client:
        r = _scan(client, _auth(client), image=("card.png", io.BytesIO(b"x" * 512), "image/png"))
        assert r.status_code == 415, r.text


def test_bad_back_file_rejected_and_front_cleaned_up():
    with TestClient(app) as client:
        before = _upload_names()
        r = _scan(
            client, _auth(client),
            image=("front.png", _png_bytes(), "image/png"),
            back=("back.jpg", io.BytesIO(b"not an image"), "image/jpeg"),
        )
        assert r.status_code == 415, r.text
        assert _upload_names() == before


def test_stored_suffix_follows_content_not_filename():
    # A real PNG uploaded as ".jpg" stores (and serves) as .png.
    with TestClient(app) as client:
        r = _scan(client, _auth(client), image=("mislabeled.jpg", _png_bytes(), "image/jpeg"))
        assert r.status_code == 200, r.text
        assert r.json()["image_path"].endswith(".png")


def test_pdf_magic_accepted():
    with TestClient(app) as client:
        r = _scan(client, _auth(client), image=("page.pdf", io.BytesIO(b"%PDF-1.4 test doc"), "application/pdf"))
        assert r.status_code == 200, r.text
        assert r.json()["image_path"].endswith(".pdf")


def test_webp_magic_accepted():
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (10, 20, 30)).save(buf, format="WEBP")
    buf.seek(0)
    with TestClient(app) as client:
        r = _scan(client, _auth(client), image=("card.webp", buf, "image/webp"))
        assert r.status_code == 200, r.text
        assert r.json()["image_path"].endswith(".webp")
