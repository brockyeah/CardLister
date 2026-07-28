"""Parity guard for the eBay title builder.

The case table in fixtures/ebay_title_cases.json is shared with the frontend
mirror test (frontend/src/lib/ebayTitle.test.js). If build_title's format
changes intentionally, regenerate the expected values and update ebayTitle.js
to match — both suites must stay green off the same table.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.routers.ebay import build_title

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "ebay_title_cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_build_title_matches_shared_table(case):
    assert build_title(SimpleNamespace(**case["card"])) == case["expected"]
