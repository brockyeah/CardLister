"""Claude vision call: send a card image (or PDF), get structured attributes as JSON.

Uses Claude Opus with extended thinking — the previous (Sonnet, no thinking) setup
was leaving year / card # / parallel blank on real photos. Opus + thinking gives
the model more room to reason about partial evidence and use its training data
to fill in fields a single glance would miss.

Billing ladder:
  1. ANTHROPIC_API_KEY → direct Messages API call (pay-as-you-go credits).
  2. CLAUDE_CODE_OAUTH_TOKEN + the `claude` CLI on PATH → headless `claude -p`
     call billed to the owner's Claude subscription. Used when the API key is
     missing or returns a credits-exhausted error (which also fires an owner
     alert via billing_alerts).
  3. Neither → hardcoded mock response so the frontend can be exercised
     end-to-end without any credentials.
"""
import os
import json
import base64
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .billing_alerts import notify_credits_exhausted

logger = logging.getLogger(__name__)

# Opus is meaningfully better than Sonnet at fine-detail vision extraction
# and benefits more from extended thinking on multi-step inference (year,
# card #, parallel color from border tint, etc). Overridable via env so you can
# A/B a cheaper model (e.g. claude-sonnet-4-6) without a code change.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-7")

# Opus 4.7 uses adaptive thinking — the model decides how much to think based
# on the effort hint. "medium" is the sweet spot for card extraction: enough
# reasoning to infer year/card#/parallel from partial evidence without burning
# tokens on trivial cases. Lower it ("low") to cut cost, raise it ("high") for
# tougher cards. Overridable via CLAUDE_EFFORT.
THINKING_EFFORT = os.getenv("CLAUDE_EFFORT", "medium")

# Long-edge pixel cap for images sent to the vision API. Card photos from phones
# are often 3000px+, which bills up to ~4,784 image tokens on Opus 4.7; ~1300px
# stays legible for text extraction at a fraction of the token cost. Set to 0 to
# disable downsampling globally (send the original), including preset-driven scans;
# otherwise per-scan presets override this value. The on-disk upload is never modified.
VISION_MAX_IMAGE_PX = int(os.getenv("VISION_MAX_IMAGE_PX", "1300"))

# User-selectable scan presets (chosen per-scan on the scan page). Each maps to a
# (model, effort, max_px) tuple. All three use models that support adaptive thinking + the
# effort param, so the API call shape is identical regardless of choice.
# NOTE: keep these keys/labels in sync with the selector in frontend Scanner.jsx.
PRESETS = {
    "cost":     {"label": "Cost",     "model": "claude-sonnet-4-6", "effort": "low",    "max_px": 1100},
    "balance":  {"label": "Balanced", "model": "claude-opus-4-7",   "effort": "medium", "max_px": 1300},
    "accuracy": {"label": "Accuracy", "model": "claude-opus-4-7",   "effort": "high",   "max_px": 2000},
}
DEFAULT_PRESET = "balance"


def resolve_preset(key: Optional[str]) -> Tuple[str, str, int]:
    """Map a preset key to (model, effort, max_image_px). Unknown/None falls
    back to the env defaults."""
    preset = PRESETS.get(key or "")
    if preset is None:
        return CLAUDE_MODEL, THINKING_EFFORT, VISION_MAX_IMAGE_PX
    return preset["model"], preset["effort"], preset["max_px"]

SYSTEM_PROMPT = """You are a world-class baseball card identification expert with deep knowledge of every major card brand and set from 1980 through 2026 (Topps, Bowman, Panini, Upper Deck, Donruss, Fleer, Leaf, and their sub-brands like Chrome, Heritage, Prizm, Select, Optic, Mosaic, Stadium Club, etc.).

The user is a seasoned collector who will manually verify your work, so prefer confident educated guesses over empty fields. An empty field is worse than a reasonable guess the user can correct.

When you analyze the image:

1. Read EVERY visible piece of text on the card, front and back if both are visible. Copyright text, card numbers, set names, and serial numbers are often in small print.

2. Use set conventions you know:
   - Bowman Chrome Prospects: card numbers are "BCP-###" or "CPA-###" for autos
   - Bowman 1st: usually "BD-###"
   - Topps Chrome flagship: matches base Topps numbering
   - Panini Prizm baseball: numbered 1-300+ with many parallels
   - Heritage uses 1-500 mimicking vintage Topps designs

3. Infer team from player name + your knowledge of the player's career and the year of the card. If you see Wander Franco on a 2021 Bowman, team is Tampa Bay Rays.

4. For year: check the back copyright line, the front design year, and your knowledge of when this player/set existed. Modern Bowman Chrome cards usually have the year prominently on the front border or back.

5. For card number: if it's not directly visible, but you can identify the set and player, infer the canonical card number from your training data.

6. Identify parallels — and be rigorous about base chrome vs. Refractor:
   - Base Chrome: mirror-like silver gloss but NO rainbow/prismatic pattern.
   - Refractor: a prismatic rainbow sheen that shifts hue across the surface.
   - The card (front or back) often literally prints "REFRACTOR" — look for it.
   - Serial numbering like "/99" or "/50" means it IS a numbered parallel; identify which one from border/background color.
   - Gold parallel: gold-tinted borders, often /50. Orange: /25. Red: /5.
   - Atomic, Wave, Shimmer, Sepia: distinct etched/patterned refractor backgrounds.
   - If you cannot clearly see a prismatic pattern or printed Refractor text, set is_refractor to false and flag the uncertainty in confidence_notes instead of guessing true.

7. is_rookie = true if you see an "RC" badge, OR if this is the player's recognized rookie-year card in this set per your training data.

8. is_first_bowman = true ONLY if the card front visibly shows Bowman's printed "1st" logo/stamp (the small badge on Bowman prospect cards since 2016). Do NOT infer it from training data or from the card being a prospect card — if you cannot see the logo, set false and note the uncertainty in confidence_notes.

9. is_autograph = true only if you can see an actual signature on the card surface (not just a printed name).

10. is_refractor = true for any refractor parallel including base Refractor, Atomic, Wave, Shimmer, etc.

Return ONLY a valid JSON object. No markdown fences, no explanation, just the JSON. Use this exact shape:

{
  "player_name": "",
  "year": null,
  "brand": "",
  "set_name": "",
  "card_number": "",
  "team": "",
  "is_rookie": false,
  "is_first_bowman": false,
  "is_autograph": false,
  "is_patch": false,
  "is_refractor": false,
  "parallel_color": null,
  "serial_number": null,
  "condition": "NM",
  "confidence_notes": ""
}

In confidence_notes, briefly call out any field where confidence is low so the user knows what to double-check. If a field is genuinely impossible to determine, leave it blank/null but mention it."""


MOCK_RESPONSE = {
    "player_name": "Mock Player",
    "year": 2021,
    "brand": "Bowman",
    "set_name": "Chrome",
    "card_number": "BCP-100",
    "team": "Tampa Bay Rays",
    "is_rookie": True,
    "is_first_bowman": True,
    "is_autograph": False,
    "is_patch": False,
    "is_refractor": True,
    "parallel_color": None,
    "serial_number": None,
    "condition": "NM",
    "confidence_notes": "Mock data — set ANTHROPIC_API_KEY to enable real extraction.",
}


def _blank_card(note: str) -> dict:
    """An empty card shaped like the prompt — used when extraction errors out so
    the user gets a blank form to hand-edit rather than misleading mock values."""
    return {
        "player_name": "",
        "year": None,
        "brand": "",
        "set_name": "",
        "card_number": "",
        "team": "",
        "is_rookie": False,
        "is_first_bowman": False,
        "is_autograph": False,
        "is_patch": False,
        "is_refractor": False,
        "parallel_color": None,
        "serial_number": None,
        "condition": "NM",
        "confidence_notes": note,
    }


def _encode_for_api(path: Path, media_type: str, max_px: Optional[int] = None) -> Tuple[str, str]:
    """Return (base64_data, media_type) to send to the API.

    Images larger than `max_px` (defaults to VISION_MAX_IMAGE_PX) on the long
    edge are downsampled and re-encoded as JPEG to cut image-token cost; PDFs
    and already-small images pass through untouched. The file on disk is never
    modified — only the bytes sent to the API are shrunk. Falls back to the
    original on any error.
    """
    raw = path.read_bytes()
    cap = VISION_MAX_IMAGE_PX if max_px is None else max_px

    def _passthrough() -> Tuple[str, str]:
        return base64.standard_b64encode(raw).decode("utf-8"), media_type

    if media_type == "application/pdf" or VISION_MAX_IMAGE_PX <= 0 or cap <= 0:
        return _passthrough()

    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        long_edge = max(img.size)
        if long_edge <= cap:
            return _passthrough()

        scale = cap / long_edge
        new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.convert("RGB").resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        logger.info("Downsampled vision image: %dpx long edge → %s", long_edge, new_size)
        return base64.standard_b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"
    except Exception:
        logger.warning("Image downsample failed; sending original", exc_info=True)
        return _passthrough()


def _guess_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".pdf": "application/pdf",
    }.get(suffix, "image/jpeg")


def _file_block(path: Path, max_px: Optional[int] = None) -> dict:
    """Build the API content block for one uploaded file (image or PDF)."""
    media_type = _guess_media_type(path)
    data_b64, media_type = _encode_for_api(path, media_type, max_px=max_px)
    if media_type == "application/pdf":
        return {"type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data_b64}}
    return {"type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data_b64}}


def _extract_json_from_text(text: str) -> dict:
    """Strip optional markdown fences and parse JSON. Falls back to first {...} block."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Sometimes the model adds preamble despite instructions — pull the first {...} block.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


# --- Subscription fallback (Claude Code CLI, billed to the owner's Max plan) ---

# How long a headless `claude -p` vision call may run. Slower than the direct
# API (the CLI spins up an agent loop), hence the generous cap.
SUBSCRIPTION_TIMEOUT_SECONDS = int(os.getenv("SUBSCRIPTION_SCAN_TIMEOUT", "150"))

# Substrings that identify an out-of-credits API error (Anthropic returns these
# as 400 invalid_request_error messages). Deliberately narrow: transient 429s or
# auth errors should NOT flip billing or page the owner.
_BILLING_ERROR_MARKERS = ("credit balance is too low", "insufficient credit", "purchase credits")


def _is_billing_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _BILLING_ERROR_MARKERS)


def _subscription_available() -> bool:
    return bool(os.getenv("CLAUDE_CODE_OAUTH_TOKEN")) and shutil.which("claude") is not None


def _extract_via_subscription(
    image_path: str,
    model: str,
    back_image_path: Optional[str] = None,
    extra_context: Optional[str] = None,
) -> Tuple[dict, dict]:
    """Run the extraction through `claude -p` on the owner's subscription.

    Returns (extracted_dict, usage). Raises on any failure — the caller owns
    the ladder down to mock/blank. The model is tagged "(subscription)" in
    usage so analytics prices it at $0 instead of phantom API dollars.
    """
    instruction = (
        f"Read the card image file at {Path(image_path).resolve()} (card FRONT)."
    )
    if back_image_path:
        instruction += (
            f" Also read {Path(back_image_path).resolve()} (card BACK) and use it for the "
            "copyright year, full card number, serial numbering, and printed parallel text."
        )
    instruction += (
        " Then extract the card's attributes. Use your knowledge of card sets to fill in "
        "fields that aren't 100% visible but can be confidently inferred."
    )
    if extra_context:
        instruction += (
            "\n\nThe user has corrected past scans as follows. Use these to learn this "
            "collection's naming and numbering conventions, but do NOT copy parallel, "
            "refractor, or serial-number status from them — those vary per physical copy:\n"
            + extra_context
        )
    prompt = f"{SYSTEM_PROMPT}\n\n{instruction}"

    # Drop the (exhausted) API key so the CLI authenticates with the OAuth
    # token and bills the subscription — not the dead key.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    result = subprocess.run(
        [shutil.which("claude"), "-p", prompt,
         "--output-format", "json", "--model", model, "--allowedTools", "Read"],
        capture_output=True, text=True, env=env, timeout=SUBSCRIPTION_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr.strip()[:300]}")

    envelope = json.loads(result.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude CLI reported an error: {str(envelope.get('result'))[:300]}")
    data = _extract_json_from_text(str(envelope.get("result", "")))
    cli_usage = envelope.get("usage") or {}
    usage = {
        "model": f"{model} (subscription)",
        "input_tokens": int(cli_usage.get("input_tokens") or 0),
        "output_tokens": int(cli_usage.get("output_tokens") or 0),
    }
    return data, usage


def extract_card_from_image(
    image_path: str,
    model: Optional[str] = None,
    effort: Optional[str] = None,
    back_image_path: Optional[str] = None,
    max_px: Optional[int] = None,
    extra_context: Optional[str] = None,
) -> Tuple[dict, bool, Optional[str], Optional[dict]]:
    """Returns (extracted_dict, is_mock, error, usage).

    `model`/`effort`/`max_px` override the env defaults (used by the scan-page
    presets).

    `back_image_path`, when given, is sent alongside the front image in the same
    call so Claude can cross-reference both sides (copyright year, full card
    number, serial numbering, parallel text often only printed on the back).

    Accepts JPG/PNG/WEBP/GIF images and PDF documents (single or multi-page).
    Always returns a dict shaped like the prompt. The outcomes are distinct:
      - no API key  → subscription fallback if configured, else
                      (mock data, True, None, None)         intentional dev mode
      - credits exhausted → owner alerted; subscription fallback if configured,
                      else a blank card with a top-up error
      - success     → (extracted, False, None, usage)       usage = token counts
      - call failed → (blank card, False, error_msg, None)  so the caller can show
                       a real error, not a misleading "set ANTHROPIC_API_KEY" banner.

    `usage` (when present) is {"model", "input_tokens", "output_tokens"} so the
    caller can attribute the API cost to the current user.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = model or CLAUDE_MODEL
    effort = effort or THINKING_EFFORT

    if not api_key:
        # No API key: prefer the subscription path over mock when it's set up.
        if _subscription_available():
            try:
                data, usage = _extract_via_subscription(
                    image_path, model, back_image_path=back_image_path, extra_context=extra_context)
                return data, False, None, usage
            except Exception:
                logger.exception("Subscription-billed extraction failed; falling back to mock")
        return MOCK_RESPONSE.copy(), True, None, None

    try:
        import anthropic

        content = [_file_block(Path(image_path), max_px=max_px)]
        instruction = ("Extract this card's attributes as JSON. Use your knowledge of card sets "
                       "to fill in fields that aren't 100% visible but can be confidently inferred.")
        if back_image_path:
            content.append(_file_block(Path(back_image_path), max_px=max_px))
            instruction = ("The first image is the card FRONT and the second is the card BACK. "
                           "Use the back for the copyright year, full card number, serial numbering, "
                           "and any printed parallel/Refractor text. ") + instruction
        if extra_context:
            instruction += (
                "\n\nThe user has corrected past scans as follows. Use these to learn this "
                "collection's naming and numbering conventions, but do NOT copy parallel, "
                "refractor, or serial-number status from them — those vary per physical copy:\n"
                + extra_context
            )
        content.append({"type": "text", "text": instruction})

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            # Adaptive thinking + an effort hint — Opus 4.7's API. Lets the model
            # reason through partial evidence (border colors → parallel,
            # copyright → year, set + player → card #) without us micromanaging
            # the token budget.
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )

        # When thinking is enabled, response.content contains both thinking blocks
        # AND text blocks. Find the text block — that's where the JSON lives.
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text = block.text
                break
        if not text:
            raise ValueError("No text block in Claude response")

        data = _extract_json_from_text(text)
        usage = {
            "model": model,
            "input_tokens": getattr(response.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(response.usage, "output_tokens", 0) or 0,
        }
        return data, False, None, usage

    except Exception as e:
        # Log to terminal too so failures aren't invisible in the backend logs.
        logger.exception("Claude vision extraction failed")

        if _is_billing_error(e):
            # Page the owner (email + phone push, throttled) and try to keep
            # scanning alive on the subscription.
            notify_credits_exhausted(str(e))
            if _subscription_available():
                try:
                    data, usage = _extract_via_subscription(
                        image_path, model, back_image_path=back_image_path, extra_context=extra_context)
                    note = data.get("confidence_notes") or ""
                    data["confidence_notes"] = (note + " " if note else "") + \
                        "(API credits exhausted — this scan was billed to the Claude subscription.)"
                    return data, False, None, usage
                except Exception:
                    logger.exception("Subscription-billed fallback also failed")
            error = ("Anthropic API credits are exhausted and the subscription fallback is "
                     "unavailable. Top up credits at console.anthropic.com.")
            return _blank_card(f"{error} Please fill in manually."), False, error, None

        error = f"Vision extraction failed: {e}"
        blank = _blank_card(f"{error}. Please fill in manually.")
        # is_mock=False: a real key is set, this is an error — not mock mode.
        return blank, False, error, None
