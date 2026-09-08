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


def test_scan_wires_learning_into_the_real_extraction_branch(db_session, monkeypatch):
    """Pins the seam mock mode never exercises. Every other endpoint test runs
    without an API key, where `extract_card_from_image` returns before touching
    anything past `image_path` — so the cheatsheet could stop being sent, the
    threadpool call's positional argument order could rot, or the exact-match
    overlay could be disconnected, all with the suite green.

    The threadpool call passes positionals, so the order asserted here is the
    contract: (image_path, model, effort, back_image_path, max_px,
    extra_context).
    """
    from backend.routers import scan as scan_module
    from backend.services.claude_vision import resolve_preset

    captured = {}

    def fake_extract(image_path, model, effort, back_image_path, max_px, extra_context):
        captured.update(image_path=image_path, model=model, effort=effort,
                        back_image_path=back_image_path, max_px=max_px,
                        extra_context=extra_context)
        return ({"player_name": "Extracted"}, False, None,
                {"model": model, "input_tokens": 10, "output_tokens": 5})

    monkeypatch.setattr(scan_module, "extract_card_from_image", fake_extract)
    monkeypatch.setattr(scan_module, "build_cheatsheet", lambda db: "PAST CORRECTIONS")
    monkeypatch.setattr(scan_module, "apply_exact_match",
                        lambda db, extracted: {**extracted, "team": "Overlaid"})

    with TestClient(app) as client:
        headers = _auth(client)
        r = client.post(
            "/api/scan",
            files={"image": ("front.png", _png_bytes(), "image/png")},
            data={"preset": "balance"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()

        model, effort, max_px = resolve_preset("balance")
        assert captured["model"] == model
        assert captured["effort"] == effort
        assert captured["max_px"] == max_px
        assert captured["back_image_path"] is None
        assert captured["extra_context"] == "PAST CORRECTIONS"
        assert captured["image_path"].endswith(body["image_path"].split("/")[-1])

        # The overlay ran and its result is both returned and persisted for
        # the correction diff.
        assert body["mock"] is False and body["error"] is None
        assert body["extracted"]["team"] == "Overlaid"
        assert body["scan_id"] is not None

        # An empty cheatsheet must arrive as None, not "" — the prompt
        # builders append the corrections block whenever the argument is
        # truthy-checked, and "" would still skip it silently on only one side.
        monkeypatch.setattr(scan_module, "build_cheatsheet", lambda db: "")
        r = client.post(
            "/api/scan",
            files={"image": ("front.png", _png_bytes(), "image/png")},
            data={"preset": "balance"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert captured["extra_context"] is None
