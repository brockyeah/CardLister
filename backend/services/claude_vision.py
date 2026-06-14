"""Claude vision call: send a card image (or PDF), get structured attributes as JSON.

Uses Claude Opus with extended thinking — the previous (Sonnet, no thinking) setup
was leaving year / card # / parallel blank on real photos. Opus + thinking gives
the model more room to reason about partial evidence and use its training data
to fill in fields a single glance would miss.

If ANTHROPIC_API_KEY is not set, a hardcoded mock response is returned so the
frontend can be exercised end-to-end without a live API key.
"""
import os
import json
import base64
import logging
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

# Opus is meaningfully better than Sonnet at fine-detail vision extraction
# and benefits more from extended thinking on multi-step inference (year,
# card #, parallel color from border tint, etc).
CLAUDE_MODEL = "claude-opus-4-7"

# Opus 4.7 uses adaptive thinking — the model decides how much to think based
# on the effort hint. "medium" is the sweet spot for card extraction: enough
# reasoning to infer year/card#/parallel from partial evidence without burning
# tokens on trivial cases.
THINKING_EFFORT = "medium"

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

6. Identify parallels:
   - Refractor: rainbow shimmer pattern in the chrome surface
   - Gold parallel: gold-tinted borders, often /50
   - Orange: orange borders, often /25
   - Red: red borders, often /5
   - Atomic, Wave, Shimmer, Sepia: distinct background patterns
   - Serial numbering like "/99" visible on the card directly identifies the parallel

7. is_rookie = true if you see an "RC" badge, OR if this is the player's recognized rookie-year card in this set per your training data.

8. is_autograph = true only if you can see an actual signature on the card surface (not just a printed name).

9. is_refractor = true for any refractor parallel including base Refractor, Atomic, Wave, Shimmer, etc.

Return ONLY a valid JSON object. No markdown fences, no explanation, just the JSON. Use this exact shape:

{
  "player_name": "",
  "year": null,
  "brand": "",
  "set_name": "",
  "card_number": "",
  "team": "",
  "is_rookie": false,
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
    "is_autograph": False,
    "is_patch": False,
    "is_refractor": True,
    "parallel_color": None,
    "serial_number": None,
    "condition": "NM",
    "confidence_notes": "Mock data — set ANTHROPIC_API_KEY to enable real extraction.",
}


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


def extract_card_from_image(image_path: str) -> Tuple[dict, bool]:
    """Returns (extracted_dict, is_mock).

    Accepts JPG/PNG/WEBP/GIF images and PDF documents (single or multi-page).
    Always returns a dict shaped like the prompt — on any error we degrade to
    mock data with an explanation in confidence_notes so the user can still hand-edit.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return MOCK_RESPONSE.copy(), True

    try:
        import anthropic

        path = Path(image_path)
        media_type = _guess_media_type(path)
        with open(path, "rb") as f:
            file_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

        # PDFs use the "document" content block; images use "image".
        # Both encode the bytes the same way (base64), so the only difference
        # is the type discriminator and media_type string.
        if media_type == "application/pdf":
            file_block = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": file_b64,
                },
            }
        else:
            file_block = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": file_b64,
                },
            }

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            # Adaptive thinking + an effort hint — Opus 4.7's API. Lets the model
            # reason through partial evidence (border colors → parallel,
            # copyright → year, set + player → card #) without us micromanaging
            # the token budget.
            thinking={"type": "adaptive"},
            output_config={"effort": THINKING_EFFORT},
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        file_block,
                        {
                            "type": "text",
                            "text": "Extract this card's attributes as JSON. Use your knowledge of card sets to fill in fields that aren't 100% visible but can be confidently inferred.",
                        },
                    ],
                }
            ],
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
        return data, False

    except Exception as e:
        # Log to terminal too so failures aren't invisible in the backend logs.
        logger.exception("Claude vision extraction failed")
        fallback = MOCK_RESPONSE.copy()
        fallback["confidence_notes"] = f"Vision extraction failed: {e}. Please fill in manually."
        return fallback, True
