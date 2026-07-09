import base64
import io

from PIL import Image

from backend.services.claude_vision import (
    CLAUDE_MODEL, THINKING_EFFORT, VISION_MAX_IMAGE_PX, _encode_for_api, resolve_preset,
)


def test_known_presets_resolve_model_effort_and_resolution():
    assert resolve_preset("cost") == ("claude-sonnet-4-6", "low", 1100)
    assert resolve_preset("balance") == ("claude-opus-4-7", "medium", 1300)
    assert resolve_preset("accuracy") == ("claude-opus-4-7", "high", 2000)


def test_unknown_preset_falls_back_to_env_defaults():
    assert resolve_preset("bogus") == (CLAUDE_MODEL, THINKING_EFFORT, VISION_MAX_IMAGE_PX)
    assert resolve_preset(None) == (CLAUDE_MODEL, THINKING_EFFORT, VISION_MAX_IMAGE_PX)


def test_encode_honors_max_px_override(tmp_path):
    p = tmp_path / "big.png"
    Image.new("RGB", (3000, 2000)).save(p)
    b64, mt = _encode_for_api(p, "image/png", max_px=2000)
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert max(img.size) == 2000
    assert mt == "image/jpeg"


def test_env_disable_beats_preset_max_px(tmp_path, monkeypatch):
    from backend.services import claude_vision as cv

    p = tmp_path / "big.png"
    Image.new("RGB", (3000, 2000)).save(p)
    monkeypatch.setattr(cv, "VISION_MAX_IMAGE_PX", 0)  # operator disabled downsampling
    b64, mt = cv._encode_for_api(p, "image/png", max_px=1300)
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert max(img.size) == 3000  # original passes through untouched
    assert mt == "image/png"
