"""Headers on served uploads: nosniff everywhere; non-image files (PDFs) must
download rather than render in the app's origin; stored names are content-stable
so responses carry an immutable long-lived cache header."""
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


def test_uploads_carry_immutable_cache_headers():
    # Upload URLs are uuid-hex, so the bytes behind one never change. Without
    # this header every inventory render refetched every full-size photo.
    with TestClient(app) as client:
        path = _scan_upload(client, _auth(client), "front.png", _png_bytes(), "image/png")
        r = client.get(path)
        assert r.status_code == 200
        cache_control = r.headers["cache-control"]
        assert "public" in cache_control
        assert "immutable" in cache_control
        assert "max-age=31536000" in cache_control


def test_upload_answers_head_with_headers_and_no_body():
    # `@app.get` registers GET only, so a HEAD probe for an existing photo used
    # to miss this route, fall through to the static mount, and 404 — the same
    # answer a genuinely missing file gives.
    with TestClient(app) as client:
        path = _scan_upload(client, _auth(client), "front.png", _png_bytes(), "image/png")
        r = client.head(path)
        assert r.status_code == 200
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "immutable" in r.headers["cache-control"]
        # FileResponse sends headers only for HEAD; Content-Length still
        # describes the real file so a size probe stays meaningful.
        assert r.content == b""
        assert int(r.headers["content-length"]) > 0

        assert client.head("/uploads/does-not-exist.png").status_code == 404


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


def test_upload_path_resolving_to_the_directory_is_a_404_not_a_500():
    """`/uploads/%2e` decodes to "." and `Path(".").name` is "", so the path
    resolved to the uploads *directory*, passed the old `exists()` check, and
    raised inside FileResponse — a 500 with a traceback on a public route where
    404 is the honest answer."""
    # Encoded so the dot segment survives client-side URL normalization and
    # actually reaches the route. (A bare `..` is resolved away before the
    # request is sent, which is why this needed %2e to surface at all.)
    with TestClient(app) as client:
        for encoded in ("%2e", "%2e%2e", "%2e/"):
            r = client.get(f"/uploads/{encoded}")
            assert r.status_code == 404, f"/uploads/{encoded} -> {r.status_code}"
            assert client.head(f"/uploads/{encoded}").status_code == 404


def test_symlink_out_of_the_uploads_volume_is_not_served():
    """`Path(filename).name` strips directory components but says nothing about
    where the resolved path lands, so a name that is a symlink pointing out of
    the uploads volume would still have been served. The containment re-check
    (resolve both sides, require the file to sit under the uploads root) is what
    actually closes that, so pin it."""
    from backend.database import uploads_dir

    with TestClient(app) as client:
        uploads = uploads_dir()
        uploads.mkdir(parents=True, exist_ok=True)
        secret = uploads.parent / "outside-the-volume.txt"
        secret.write_text("not a card photo")
        link = uploads / "escape.png"
        link.unlink(missing_ok=True)
        link.symlink_to(secret)
        try:
            r = client.get("/uploads/escape.png")
            assert r.status_code == 404, f"symlink escape served: {r.status_code}"
            assert "not a card photo" not in r.text
            assert client.head("/uploads/escape.png").status_code == 404
        finally:
            link.unlink(missing_ok=True)
            secret.unlink(missing_ok=True)
