# Feedback Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the five approved feedback features: quantity column (+ column migration helper), front & back scanning, refractor detection upgrades, learning-from-corrections, and a sequential batch-scan queue.

**Architecture:** FastAPI + SQLAlchemy + SQLite backend (`backend/`), React 18 + Vite frontend (`frontend/src/`). Vision calls go through `backend/services/claude_vision.py` (Anthropic API, adaptive thinking + effort presets). New learning logic lives in `backend/services/learning.py`. Tables are created by `create_all`; columns added to *existing* tables need the new `ensure_columns` helper.

**Tech Stack:** Python 3.12 (`.venv`), pytest (new dev dep), FastAPI TestClient, Pillow, React/Vite/Tailwind.

## Global Constraints

- Branch: `feat/feedback-features` (already created, stacked on `feat/cardlister-improvements`). Commit after every task.
- Backend tests: run from repo root with `.venv/bin/python -m pytest backend/tests -q`. All must pass before each commit.
- Frontend gate: `cd frontend && npm run build` must succeed before each commit that touches `frontend/`.
- **Never override copy-specific fields** (`parallel_color`, `serial_number`, `is_refractor`, `is_autograph`, `is_patch`, `condition`) from learned corrections — identity fields only.
- Google Sheet column order is append-only: new columns go at the END of `SHEET_HEADERS`.
- Match existing code style: comments explain constraints, not narration; no type-hint retrofits of untouched code.
- Do not modify `docs/`, `.env`, or anything under `uploads/`.

---

### Task 1: Test infra + column-migration helper + Quantity

**Files:**
- Create: `backend/requirements-dev.txt`, `backend/tests/conftest.py`, `backend/tests/test_migrations.py`, `backend/tests/test_quantity.py`
- Modify: `backend/database.py` (add `ensure_columns` + registry; call in `init_db`), `backend/models.py` (Card.quantity), `backend/schemas.py` (CardBase/CardUpdate), `backend/services/google_sheets.py` (headers/row/ranges), `backend/routers/ebay.py` (description line), `frontend/src/pages/Scanner.jsx` (EMPTY_FORM), `frontend/src/components/CardForm.jsx` (FIELDS), `frontend/src/components/CardTable.jsx` (Qty column)

**Interfaces:**
- Produces: `ensure_columns(target_engine=None) -> None` and module list `_COLUMN_MIGRATIONS: list[tuple[str, str, str]]` in `backend/database.py` (Task 2 appends an entry); `Card.quantity: int` default 1; `CardBase.quantity: int = 1`.

- [ ] **Step 1: Install pytest and create test infra**

```bash
.venv/bin/pip install pytest==8.3.3
```

Create `backend/requirements-dev.txt`:
```
pytest==8.3.3
```

Create `backend/tests/conftest.py`:
```python
"""Shared test setup. Env must be set BEFORE any backend import — the engine
binds DB_PATH at module import time."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("CARDLISTER_USERS", "tester:pw")
os.environ.pop("ANTHROPIC_API_KEY", None)  # endpoint tests run in mock mode

import pytest  # noqa: E402


@pytest.fixture
def db_session():
    from backend.database import SessionLocal, init_db
    from backend.models import Correction, Scan  # exists from Task 4 on; see note

    init_db()
    db = SessionLocal()
    db.query(Correction).delete()
    db.query(Scan).delete()
    db.commit()
    yield db
    db.close()
```
> NOTE for Task 1 implementer: the `Correction`/`Scan` imports don't exist until Task 4. In Task 1, create the fixture WITHOUT those two model imports/deletes (just `init_db()`, yield a session, close). Task 4 upgrades the fixture to the version above.

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_migrations.py`:
```python
from sqlalchemy import create_engine, text

from backend.database import ensure_columns


def _cols(engine, table):
    with engine.connect() as conn:
        return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def test_ensure_columns_adds_missing_quantity(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cards (id INTEGER PRIMARY KEY, player_name VARCHAR)"))
    ensure_columns(engine)
    assert "quantity" in _cols(engine, "cards")


def test_ensure_columns_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cards (id INTEGER PRIMARY KEY)"))
    ensure_columns(engine)
    ensure_columns(engine)  # second run must not raise
    assert "quantity" in _cols(engine, "cards")


def test_ensure_columns_skips_missing_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    ensure_columns(engine)  # no cards table yet — create_all will build it complete
```

Create `backend/tests/test_quantity.py`:
```python
from backend.models import Card
from backend.routers.ebay import build_description
from backend.services.google_sheets import SHEET_HEADERS, _card_to_row


def _card(**kw):
    defaults = dict(player_name="Wander Franco", year=2021, brand="Bowman",
                    set_name="Chrome", card_number="BCP-100", condition="NM", quantity=1)
    defaults.update(kw)
    return Card(**defaults)


def test_sheet_row_matches_header_length_and_includes_quantity():
    row = _card_to_row(_card(quantity=3))
    assert len(row) == len(SHEET_HEADERS)
    assert SHEET_HEADERS[-1] == "Quantity"
    assert row[-1] == 3


def test_description_mentions_quantity_only_above_one():
    assert "Quantity available: 4" in build_description(_card(quantity=4))
    assert "Quantity available" not in build_description(_card(quantity=1))
```

- [ ] **Step 3: Run tests, verify failure**

Run: `.venv/bin/python -m pytest backend/tests -q`
Expected: FAIL — `ImportError: cannot import name 'ensure_columns'` and quantity assertions failing.

- [ ] **Step 4: Implement backend**

`backend/database.py` — after the `engine = create_engine(...)` block, add:
```python
# Columns added to tables that already exist. create_all() only creates missing
# tables — it never ALTERs existing ones — so every new column on an existing
# table needs a registry entry here; it is added idempotently at startup.
_COLUMN_MIGRATIONS = [
    ("cards", "quantity", "INTEGER NOT NULL DEFAULT 1"),
]


def ensure_columns(target_engine=None) -> None:
    """Add any registered missing columns (idempotent, SQLite ALTER TABLE)."""
    from sqlalchemy import text

    eng = target_engine or engine
    with eng.begin() as conn:
        for table, column, ddl in _COLUMN_MIGRATIONS:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if not rows:
                continue  # table doesn't exist yet — create_all builds it complete
            if column not in {r[1] for r in rows}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
```
and in `init_db()` after `Base.metadata.create_all(bind=engine)` add:
```python
    ensure_columns()
```

`backend/models.py` — in `Card`, after the `condition` column line, add:
```python
    quantity = Column(Integer, nullable=False, default=1, server_default="1")
```

`backend/schemas.py` — `CardBase`: after `condition: str = "NM"` add `quantity: int = 1`. `CardUpdate`: after `condition: Optional[str] = None` add `quantity: Optional[int] = None`.

`backend/services/google_sheets.py`:
- `SHEET_HEADERS`: append `"Quantity"` as the LAST element (after `"Notes"`).
- `_card_to_row`: append `card.quantity if card.quantity is not None else 1` as the last element (after the notes entry).
- Replace both `Q`-column range strings: `f"{SHEET_TAB}!A1:Q1"` → `f"{SHEET_TAB}!A1:R1"` and `f"{SHEET_TAB}!A{card.sheets_row}:Q{card.sheets_row}"` → `f"{SHEET_TAB}!A{card.sheets_row}:R{card.sheets_row}"`.
- `_ensure_header`: change `if not result.get("values"):` to
```python
        values = result.get("values")
        if not values or len(values[0]) < len(SHEET_HEADERS):
```
so pre-existing sheets get the new header written.

`backend/routers/ebay.py` — in `build_description`, immediately after the closing `]` of the initial `lines = [...]` list, add:
```python
    if card.quantity and card.quantity > 1:
        lines.append(f"Quantity available: {card.quantity}")
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/bin/python -m pytest backend/tests -q`
Expected: all PASS.

- [ ] **Step 6: Frontend edits + build**

`frontend/src/pages/Scanner.jsx` — in `EMPTY_FORM`, after `condition: 'NM',` add:
```js
  quantity: 1,
```

`frontend/src/components/CardForm.jsx` — in `FIELDS`, after the `condition` entry add:
```js
  { key: 'quantity', label: 'Quantity', type: 'number' },
```

`frontend/src/components/CardTable.jsx` — in `<thead>`, after `<th className="px-3 py-3">Cond</th>` add:
```jsx
            <th className="px-3 py-3 text-right">Qty</th>
```
and in the body row, after the condition `<td>` add:
```jsx
              <td className="px-3 py-2 text-right">{c.quantity ?? 1}</td>
```

Run: `cd frontend && npm run build` — Expected: success.

- [ ] **Step 7: Commit**

```bash
git add backend frontend
git commit -m "feat: quantity column + idempotent column-migration helper"
```

---

### Task 2: Front & back scanning

**Files:**
- Create: `backend/tests/test_scan_endpoint.py`
- Modify: `backend/models.py` (Card.back_image_path), `backend/database.py` (registry entry), `backend/schemas.py` (CardBase/CardUpdate/ScanResponse), `backend/services/claude_vision.py` (`_file_block` helper, `back_image_path` param), `backend/routers/scan.py` (back upload), `frontend/src/api.js` (scanCard back file), `frontend/src/pages/Scanner.jsx` (back slot UI + review thumb)

**Interfaces:**
- Consumes: `ensure_columns` registry from Task 1.
- Produces: `extract_card_from_image(image_path, model=None, effort=None, back_image_path=None) -> (dict, bool, Optional[str], Optional[dict])`; `_file_block(path: Path) -> dict`; `ScanResponse.back_image_path: Optional[str]`; JS `scanCard(file, preset, backFile=null)`.

- [ ] **Step 1: Write failing endpoint test**

Create `backend/tests/test_scan_endpoint.py`:
```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/bin/python -m pytest backend/tests/test_scan_endpoint.py -q`
Expected: FAIL — `back_image_path` missing / 422 on unexpected `back` field.

- [ ] **Step 3: Implement backend**

`backend/models.py` — in `Card`, after `image_path = Column(String, default="")` add:
```python
    back_image_path = Column(String, nullable=True)
```

`backend/database.py` — append to `_COLUMN_MIGRATIONS`:
```python
    ("cards", "back_image_path", "VARCHAR"),
```

`backend/schemas.py` — `CardBase`: after `image_path: str = ""` add `back_image_path: Optional[str] = None`. `CardUpdate`: after `image_path: Optional[str] = None` add `back_image_path: Optional[str] = None`. `ScanResponse`: after `image_path: str` add `back_image_path: Optional[str] = None`.

`backend/services/claude_vision.py` — replace the inline pdf/image block construction inside `extract_card_from_image` with a module-level helper (place after `_guess_media_type`):
```python
def _file_block(path: Path) -> dict:
    """Build the API content block for one uploaded file (image or PDF)."""
    media_type = _guess_media_type(path)
    data_b64, media_type = _encode_for_api(path, media_type)
    if media_type == "application/pdf":
        return {"type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data_b64}}
    return {"type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data_b64}}
```
Change the signature to `def extract_card_from_image(image_path, model=None, effort=None, back_image_path=None):` (update the docstring to mention the optional back image) and build the message content as:
```python
        content = [_file_block(Path(image_path))]
        instruction = ("Extract this card's attributes as JSON. Use your knowledge of card sets "
                       "to fill in fields that aren't 100% visible but can be confidently inferred.")
        if back_image_path:
            content.append(_file_block(Path(back_image_path)))
            instruction = ("The first image is the card FRONT and the second is the card BACK. "
                           "Use the back for the copyright year, full card number, serial numbering, "
                           "and any printed parallel/Refractor text. ") + instruction
        content.append({"type": "text", "text": instruction})
```
and pass `messages=[{"role": "user", "content": content}]` in the API call. Delete the now-unused inline `file_block` construction.

`backend/routers/scan.py` — add `from typing import Optional` and refactor:
```python
async def _save_upload(upload: UploadFile, uploads: Path) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        # Unknown extension — coerce to .jpg so downstream stays predictable.
        suffix = ".jpg"
    filename = f"{uuid.uuid4().hex}{suffix}"
    contents = await upload.read()
    with open(uploads / filename, "wb") as f:
        f.write(contents)
    return filename
```
Endpoint signature gains `back: Optional[UploadFile] = File(None),` after `image`. Body becomes:
```python
    uploads = uploads_dir()
    uploads.mkdir(parents=True, exist_ok=True)
    try:
        front_name = await _save_upload(image, uploads)
        back_name = await _save_upload(back, uploads) if back and back.filename else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    model, effort = resolve_preset(preset)
    back_path = str(uploads / back_name) if back_name else None
    extracted, is_mock, error, usage = await run_in_threadpool(
        extract_card_from_image, str(uploads / front_name), model, effort, back_path
    )
```
(keep the UsageEvent block unchanged) and return:
```python
    return ScanResponse(
        image_path=f"/uploads/{front_name}",
        back_image_path=f"/uploads/{back_name}" if back_name else None,
        extracted=extracted, mock=is_mock, error=error,
    )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest backend/tests -q` — Expected: all PASS.

- [ ] **Step 5: Frontend**

`frontend/src/api.js` — replace `scanCard`:
```js
export const scanCard = (file, preset = 'balance', backFile = null) => {
  const fd = new FormData()
  fd.append('image', file)
  fd.append('preset', preset)
  if (backFile) fd.append('back', backFile)
  return api
    .post('/api/scan', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((r) => r.data)
}
```

`frontend/src/pages/Scanner.jsx`:
1. `EMPTY_FORM`: after `image_path: '',` add `back_image_path: '',`.
2. New state next to the staged-front state:
```js
  const [stagedBack, setStagedBack] = useState(null)
  const [stagedBackPreview, setStagedBackPreview] = useState('')
  const backInputRef = useRef(null)
```
3. `clearStaged` additionally does:
```js
    if (stagedBackPreview) URL.revokeObjectURL(stagedBackPreview)
    setStagedBack(null)
    setStagedBackPreview('')
```
4. `runScan`: call `scanCard(stagedFile, mode, stagedBack)`; after `setImagePath(result.image_path)` the form spread already carries `back_image_path` via `result` — set it explicitly:
```js
      const next = { ...EMPTY_FORM, ...result.extracted, image_path: result.image_path, back_image_path: result.back_image_path || '' }
```
5. In the STAGE 2 panel, under the "Choose a Different File" button, add the back slot:
```jsx
              <input
                ref={backInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (!f) return
                  if (stagedBackPreview) URL.revokeObjectURL(stagedBackPreview)
                  setStagedBack(f)
                  setStagedBackPreview(URL.createObjectURL(f))
                }}
              />
              {stagedBack ? (
                <div className="flex items-center gap-3 text-sm text-gray-300">
                  <img src={stagedBackPreview} alt="Back" className="w-12 h-16 object-cover rounded" />
                  <span className="flex-1 truncate">Back: {stagedBack.name}</span>
                  <button type="button" className="text-red-400 underline text-xs"
                          onClick={() => { URL.revokeObjectURL(stagedBackPreview); setStagedBack(null); setStagedBackPreview('') }}>
                    Remove
                  </button>
                </div>
              ) : (
                <button type="button" onClick={() => backInputRef.current?.click()} disabled={scanning}
                        className="btn-secondary w-full">
                  + Add Back of Card (optional, improves accuracy)
                </button>
              )}
```
6. In the STAGE 3 image panel, under the front `<img ...>` add:
```jsx
              {form.back_image_path && (
                <img src={form.back_image_path} alt="Card back" className="w-full rounded-lg mb-3" />
              )}
```

Run: `cd frontend && npm run build` — Expected: success.

- [ ] **Step 6: Commit**

```bash
git add backend frontend
git commit -m "feat: optional back-of-card image in scans (front+back vision call)"
```

---

### Task 3: Refractor detection — prompt + per-preset resolution

**Files:**
- Create: `backend/tests/test_presets.py`
- Modify: `backend/services/claude_vision.py` (PRESETS max_px, `resolve_preset` 3-tuple, `_encode_for_api`/`_file_block`/`extract_card_from_image` max_px param, SYSTEM_PROMPT item 6), `backend/routers/scan.py` (3-tuple unpack), `frontend/src/pages/Scanner.jsx` (SCAN_MODES descriptions)

**Interfaces:**
- Consumes: Task 2's `extract_card_from_image(..., back_image_path=None)` / `_file_block`.
- Produces: `resolve_preset(key) -> (model, effort, max_px)`; `extract_card_from_image(image_path, model=None, effort=None, back_image_path=None, max_px=None)`; `_encode_for_api(path, media_type, max_px=None)`; `_file_block(path, max_px=None)`.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_presets.py`:
```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/bin/python -m pytest backend/tests/test_presets.py -q`
Expected: FAIL — 2-tuple returns / unexpected `max_px` kwarg.

- [ ] **Step 3: Implement**

`backend/services/claude_vision.py`:
1. PRESETS — add `"max_px"` to each entry:
```python
PRESETS = {
    "cost":     {"label": "Cost",     "model": "claude-sonnet-4-6", "effort": "low",    "max_px": 1100},
    "balance":  {"label": "Balanced", "model": "claude-opus-4-7",   "effort": "medium", "max_px": 1300},
    "accuracy": {"label": "Accuracy", "model": "claude-opus-4-7",   "effort": "high",   "max_px": 2000},
}
```
2. `resolve_preset` returns a 3-tuple (update its docstring):
```python
def resolve_preset(key: Optional[str]) -> Tuple[str, str, int]:
    """Map a preset key to (model, effort, max_image_px). Unknown/None falls
    back to the env defaults."""
    preset = PRESETS.get(key or "")
    if preset is None:
        return CLAUDE_MODEL, THINKING_EFFORT, VISION_MAX_IMAGE_PX
    return preset["model"], preset["effort"], preset["max_px"]
```
3. `_encode_for_api(path, media_type, max_px=None)` — inside, compute `cap = VISION_MAX_IMAGE_PX if max_px is None else max_px` and use `cap` everywhere `VISION_MAX_IMAGE_PX` was used (the `<= 0` disable check, the `long_edge <=` comparison, and the scale divisor).
4. `_file_block(path, max_px=None)` — pass `max_px` through to `_encode_for_api`.
5. `extract_card_from_image(..., max_px=None)` — pass `max_px` to both `_file_block` calls. Parameter order: `(image_path, model=None, effort=None, back_image_path=None, max_px=None)`.
6. SYSTEM_PROMPT — replace the entire item `6. Identify parallels:` block (through the `"/99" ... identifies the parallel` line) with:
```
6. Identify parallels — and be rigorous about base chrome vs. Refractor:
   - Base Chrome: mirror-like silver gloss but NO rainbow/prismatic pattern.
   - Refractor: a prismatic rainbow sheen that shifts hue across the surface.
   - The card (front or back) often literally prints "REFRACTOR" — look for it.
   - Serial numbering like "/99" or "/50" means it IS a numbered parallel; identify which one from border/background color.
   - Gold parallel: gold-tinted borders, often /50. Orange: /25. Red: /5.
   - Atomic, Wave, Shimmer, Sepia: distinct etched/patterned refractor backgrounds.
   - If you cannot clearly see a prismatic pattern or printed Refractor text, set is_refractor to false and flag the uncertainty in confidence_notes instead of guessing true.
```

`backend/routers/scan.py` — change the unpack and call:
```python
    model, effort, max_px = resolve_preset(preset)
    ...
    extracted, is_mock, error, usage = await run_in_threadpool(
        extract_card_from_image, str(uploads / front_name), model, effort, back_path, max_px
    )
```

`frontend/src/pages/Scanner.jsx` — update SCAN_MODES descriptions:
```js
const SCAN_MODES = [
  { key: 'cost', label: 'Cost', desc: 'Sonnet 4.6 · low thinking · smaller image — cheapest' },
  { key: 'balance', label: 'Balanced', desc: 'Opus 4.7 · medium thinking' },
  { key: 'accuracy', label: 'Accuracy', desc: 'Opus 4.7 · high thinking · hi-res image — most thorough' },
]
```

- [ ] **Step 4: Run all tests + build, verify pass**

Run: `.venv/bin/python -m pytest backend/tests -q` — Expected: all PASS.
Run: `cd frontend && npm run build` — Expected: success.

- [ ] **Step 5: Commit**

```bash
git add backend frontend
git commit -m "feat: refractor-focused prompt + per-preset image resolution"
```

---

### Task 4: Learning from corrections

**Files:**
- Create: `backend/services/learning.py`, `backend/tests/test_learning.py`
- Modify: `backend/models.py` (Scan, Correction), `backend/tests/conftest.py` (upgrade `db_session` fixture per Task 1 note), `backend/services/claude_vision.py` (`extra_context` param), `backend/routers/scan.py` (cheatsheet + overlay + Scan row + scan_id), `backend/schemas.py` (ScanResponse.scan_id, CardCreate.scan_id, AnalyticsTotals.corrections), `backend/routers/cards.py` (record correction on create), `backend/routers/analytics.py` (corrections count), `frontend/src/pages/Scanner.jsx` (scanId state → save payload), `frontend/src/pages/Analytics.jsx` (corrections tile)

**Interfaces:**
- Consumes: Task 3's `extract_card_from_image(image_path, model, effort, back_image_path, max_px)`.
- Produces: `extract_card_from_image(..., extra_context: Optional[str] = None)` (appended after `max_px`); `learning.diff_correction(extracted, saved) -> dict`; `learning.record_correction(db, scan, saved, card_id, username) -> Optional[Correction]`; `learning.build_cheatsheet(db) -> str`; `learning.apply_exact_match(db, extracted) -> dict`; `ScanResponse.scan_id: Optional[int]`; `CardCreate.scan_id: Optional[int]`; `AnalyticsTotals.corrections: int`.

- [ ] **Step 1: Add models + upgrade conftest**

`backend/models.py` — append after `UsageEvent`:
```python
class Scan(Base):
    """One row per real (non-mock) vision extraction — the raw model output as
    shown to the user, kept so we can diff it against what they actually save."""
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True, nullable=False, default="")
    image_path = Column(String, default="")
    back_image_path = Column(String, nullable=True)
    model = Column(String, default="")
    extracted_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Correction(Base):
    """A user's fix to a scan: what the model said vs. what got saved. Feeds the
    cheat-sheet prompt injection and the exact-card identity override."""
    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, index=True, nullable=True)
    card_id = Column(Integer, index=True, nullable=True)
    username = Column(String, index=True, nullable=False, default="")
    # Corrected identity, denormalized for exact-card matching
    year = Column(Integer, nullable=True)
    brand = Column(String, default="")
    set_name = Column(String, default="")
    card_number = Column(String, default="")
    extracted_json = Column(Text, default="{}")
    corrected_json = Column(Text, default="{}")
    diff_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
```
Upgrade `backend/tests/conftest.py`'s `db_session` fixture to the full version shown in Task 1 Step 1 (with the `Correction`/`Scan` cleanup).

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_learning.py`:
```python
import json

from fastapi.testclient import TestClient

from backend.models import Correction, Scan
from backend.services.learning import apply_exact_match, build_cheatsheet, diff_correction


def test_diff_ignores_case_and_blank_differences():
    extracted = {"player_name": "wander franco", "brand": "", "set_name": "Chrome"}
    saved = {"player_name": "Wander Franco", "brand": None, "set_name": "Chrome Prospects"}
    diff = diff_correction(extracted, saved)
    assert "player_name" not in diff
    assert "brand" not in diff
    assert diff["set_name"]["to"] == "Chrome Prospects"


def test_exact_match_overlays_identity_but_never_parallel(db_session):
    db_session.add(Correction(
        username="tester", year=2024, brand="Bowman", set_name="Chrome Prospects",
        card_number="BCP-132",
        corrected_json=json.dumps({
            "player_name": "Tony Blanco Jr.", "year": 2024, "brand": "Bowman",
            "set_name": "Chrome Prospects", "card_number": "BCP-132",
            "team": "Washington Nationals", "is_rookie": False,
            "parallel_color": "Gold", "serial_number": "/50",
        }),
        diff_json=json.dumps({"set_name": {"from": "Chrome", "to": "Chrome Prospects"}}),
    ))
    db_session.commit()

    extracted = {"player_name": "", "year": 2024, "brand": "bowman", "set_name": "Chrome",
                 "card_number": "bcp-132", "parallel_color": None, "confidence_notes": ""}
    merged = apply_exact_match(db_session, extracted)
    assert merged["set_name"] == "Chrome Prospects"
    assert merged["player_name"] == "Tony Blanco Jr."
    assert merged["parallel_color"] is None  # copy-specific: never overridden
    assert "saved corrections" in merged["confidence_notes"]


def test_cheatsheet_dedupes_identical_rules(db_session):
    for i in range(40):
        db_session.add(Correction(
            username="tester", year=2024, brand="Bowman", set_name="Chrome",
            card_number=f"BCP-{i}",
            diff_json=json.dumps({"set_name": {"from": "Chrome", "to": "Chrome Prospects"}}),
        ))
    db_session.commit()
    sheet = build_cheatsheet(db_session)
    assert sheet
    assert sheet.count("\n") == 0  # 40 identical rules collapse to one line


def test_create_card_with_scan_id_records_correction(db_session):
    from backend.main import app

    scan = Scan(username="tester", image_path="/uploads/x.jpg", model="claude-opus-4-7",
                extracted_json=json.dumps({"player_name": "Tony Blanco", "year": 2024,
                                           "brand": "Bowman", "set_name": "Chrome",
                                           "card_number": "BCP-132"}))
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)

    with TestClient(app) as client:
        tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
        r = client.post("/api/cards",
                        json={"player_name": "Tony Blanco Jr.", "year": 2024, "brand": "Bowman",
                              "set_name": "Chrome Prospects", "card_number": "BCP-132",
                              "scan_id": scan.id},
                        headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text

    corrections = db_session.query(Correction).all()
    assert len(corrections) == 1
    diff = json.loads(corrections[0].diff_json)
    assert diff["set_name"]["to"] == "Chrome Prospects"
    assert diff["player_name"]["to"] == "Tony Blanco Jr."
```

- [ ] **Step 3: Run, verify failure**

Run: `.venv/bin/python -m pytest backend/tests/test_learning.py -q`
Expected: FAIL — `No module named 'backend.services.learning'`.

- [ ] **Step 4: Implement `backend/services/learning.py`**

```python
"""Learning-from-corrections: capture user fixes to scans, feed them back.

Two mechanisms (approved design):
- Cheat-sheet: a bounded digest of recent corrections appended to each scan
  prompt so the model learns this collection's naming/numbering conventions.
- Exact-match override: when the same card (brand + card number + year) was
  corrected before, overlay the corrected IDENTITY fields onto the extraction.

Copy-specific attributes are recorded (the cheat-sheet may reference them) but
are NEVER overridden — the same card number exists as base, refractor, gold /50…
"""
import json
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Correction, Scan

# Safe to overlay on an exact card match — facts tied to the card's identity.
IDENTITY_FIELDS = ["player_name", "year", "brand", "set_name", "card_number", "team", "is_rookie"]
# Recorded in corrections but never overridden (vary per physical copy).
COPY_SPECIFIC_FIELDS = ["is_autograph", "is_patch", "is_refractor", "parallel_color", "serial_number"]
TRACKED_FIELDS = IDENTITY_FIELDS + COPY_SPECIFIC_FIELDS

CHEATSHEET_MAX_RULES = 30
CHEATSHEET_MAX_CHARS = 4000


def _norm(value):
    """Normalize for comparison: strings casefolded/stripped; ''/None equal."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def diff_correction(extracted: dict, saved: dict) -> dict:
    """{field: {"from": x, "to": y}} for tracked fields the user changed."""
    diff = {}
    for field in TRACKED_FIELDS:
        before, after = extracted.get(field), saved.get(field)
        if _norm(before) != _norm(after):
            diff[field] = {"from": before, "to": after}
    return diff


def record_correction(db: Session, scan: Scan, saved: dict, card_id, username) -> Optional[Correction]:
    """Diff the scan's extraction against the saved payload; store if non-empty."""
    extracted = json.loads(scan.extracted_json or "{}")
    diff = diff_correction(extracted, saved)
    if not diff:
        return None
    correction = Correction(
        scan_id=scan.id,
        card_id=card_id,
        username=username,
        year=saved.get("year"),
        brand=saved.get("brand") or "",
        set_name=saved.get("set_name") or "",
        card_number=saved.get("card_number") or "",
        extracted_json=json.dumps({f: extracted.get(f) for f in TRACKED_FIELDS}, default=str),
        corrected_json=json.dumps({f: saved.get(f) for f in TRACKED_FIELDS}, default=str),
        diff_json=json.dumps(diff, default=str),
    )
    db.add(correction)
    db.commit()
    return correction


def build_cheatsheet(db: Session) -> str:
    """Bounded plain-text digest of recent corrections for prompt injection."""
    rows = db.query(Correction).order_by(Correction.created_at.desc()).limit(200).all()
    lines, seen = [], set()
    for row in rows:
        diff = json.loads(row.diff_json or "{}")
        context = " ".join(str(p) for p in (row.year, row.brand, row.set_name) if p) or "unknown set"
        for field, change in diff.items():
            rule = f"- {context}: you said {field}={change.get('from')!r}; the user corrected it to {change.get('to')!r}."
            if rule in seen:
                continue
            seen.add(rule)
            lines.append(rule)
            if len(lines) >= CHEATSHEET_MAX_RULES:
                break
        if len(lines) >= CHEATSHEET_MAX_RULES:
            break
    return "\n".join(lines)[:CHEATSHEET_MAX_CHARS]


def find_exact_match(db: Session, extracted: dict) -> Optional[dict]:
    """Corrected IDENTITY fields from the latest correction of the same card
    (normalized brand + card number + year), or None."""
    card_number = _norm(extracted.get("card_number"))
    brand = _norm(extracted.get("brand"))
    year = extracted.get("year")
    if not card_number or not brand or not year:
        return None
    rows = (
        db.query(Correction)
        .filter(Correction.year == year)
        .order_by(Correction.created_at.desc())
        .limit(100)
        .all()
    )
    for row in rows:
        if _norm(row.brand) == brand and _norm(row.card_number) == card_number:
            corrected = json.loads(row.corrected_json or "{}")
            return {f: corrected.get(f) for f in IDENTITY_FIELDS if corrected.get(f) not in (None, "")}
    return None


def apply_exact_match(db: Session, extracted: dict) -> dict:
    """Overlay identity fields from a past correction of the same card, if any."""
    overlay = find_exact_match(db, extracted)
    if not overlay:
        return extracted
    merged = {**extracted, **overlay}
    note = "Applied your saved corrections for this exact card (identity fields only)."
    existing = merged.get("confidence_notes") or ""
    merged["confidence_notes"] = f"{existing} {note}".strip()
    return merged
```

- [ ] **Step 5: Wire the backend**

`backend/services/claude_vision.py` — signature becomes
`def extract_card_from_image(image_path, model=None, effort=None, back_image_path=None, max_px=None, extra_context=None):`
and after the `instruction` is built (Task 2/3 code), add:
```python
        if extra_context:
            instruction += (
                "\n\nThe user has corrected past scans as follows. Use these to learn this "
                "collection's naming and numbering conventions, but do NOT copy parallel, "
                "refractor, or serial-number status from them — those vary per physical copy:\n"
                + extra_context
            )
```

`backend/routers/scan.py` — add `import json`, import `Scan` alongside `UsageEvent`, and `from ..services.learning import apply_exact_match, build_cheatsheet`. Before the threadpool call:
```python
    cheatsheet = build_cheatsheet(db)
```
Pass it: `..., back_path, max_px, cheatsheet or None)`. After the UsageEvent block:
```python
    public_front = f"/uploads/{front_name}"
    public_back = f"/uploads/{back_name}" if back_name else None

    # Learning: overlay identity fields from past corrections of this exact card,
    # then persist the extraction (as shown to the user) so the save can be diffed.
    scan_id = None
    if not is_mock and not error:
        extracted = apply_exact_match(db, extracted)
        scan_row = Scan(
            username=username,
            image_path=public_front,
            back_image_path=public_back,
            model=(usage or {}).get("model", ""),
            extracted_json=json.dumps(extracted, default=str),
        )
        db.add(scan_row)
        db.commit()
        db.refresh(scan_row)
        scan_id = scan_row.id

    return ScanResponse(image_path=public_front, back_image_path=public_back,
                        extracted=extracted, mock=is_mock, error=error, scan_id=scan_id)
```

`backend/schemas.py`:
- `ScanResponse`: add `scan_id: Optional[int] = None`.
- `CardCreate`:
```python
class CardCreate(CardBase):
    # Ties the save back to the scan that produced it, for correction capture.
    scan_id: Optional[int] = None
```
- `AnalyticsTotals`: add `corrections: int = 0`.

`backend/routers/cards.py` — import `Scan` alongside `Card`, `from ..auth import require_auth` already imported; add `from ..services.learning import record_correction`. `create_card` becomes:
```python
@router.post("", response_model=CardOut)
def create_card(payload: CardCreate, background_tasks: BackgroundTasks,
                username: str = Depends(require_auth), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude={"scan_id"})
    card = Card(**data)
    # Anything saved here is going on eBay next, so always mark it "active".
    card.status = "active"
    db.add(card)
    db.commit()
    db.refresh(card)
    # Learning: diff what the model extracted vs. what the user actually saved.
    if payload.scan_id:
        scan = db.query(Scan).filter(Scan.id == payload.scan_id).first()
        if scan is not None:
            record_correction(db, scan, data, card.id, username)
    background_tasks.add_task(_sync_card_to_sheets, card.id)
    return card
```

`backend/routers/analytics.py` — import `Correction` alongside `UsageEvent`; before building the return value:
```python
    corr_q = db.query(Correction)
    if since is not None:
        corr_q = corr_q.filter(Correction.created_at >= since)
    if user:
        corr_q = corr_q.filter(Correction.username == user)
    corrections_count = corr_q.count()
```
and add `corrections=corrections_count,` to the `AnalyticsTotals(...)` constructor.

- [ ] **Step 6: Run tests, verify pass**

Run: `.venv/bin/python -m pytest backend/tests -q` — Expected: all PASS.

- [ ] **Step 7: Frontend**

`frontend/src/pages/Scanner.jsx`:
1. Add state near `mock`: `const [scanId, setScanId] = useState(null)`.
2. In `runScan` after `setMock(...)`: `setScanId(result.scan_id ?? null)`.
3. In `handleSubmit`: `const created = await createCard({ ...data, image_path: imagePath, scan_id: scanId })` and in the post-save reset add `setScanId(null)`.
4. In the "Discard & Start Over" onClick reset add `setScanId(null)`.

`frontend/src/pages/Analytics.jsx`:
1. Summary grid: change `grid-cols-2 lg:grid-cols-4` to `grid-cols-2 lg:grid-cols-5` and add:
```jsx
            <Tile label="Corrections" value={fmt(t.corrections)} />
```

Run: `cd frontend && npm run build` — Expected: success.

- [ ] **Step 8: Commit**

```bash
git add backend frontend
git commit -m "feat: learning from corrections (cheat-sheet injection + exact-card identity override)"
```

---

### Task 5: Sequential batch-scan queue (frontend only)

**Files:**
- Modify: `frontend/src/pages/Scanner.jsx`

**Interfaces:**
- Consumes: `scanCard(file, preset)` (front-only in batch v1), `getPricing`, `createCard(payload incl. scan_id)`, existing form flow.
- Produces: no new exports — UI behavior only. Single-file flow must remain byte-for-byte behaviorally identical.

- [ ] **Step 1: Implement the queue**

All edits in `frontend/src/pages/Scanner.jsx`.

1. Import `useRef, useState, useEffect` from react (add `useEffect`).
2. New state after the scan-mode state:
```js
  // Batch mode (2+ files staged at once). Scans run strictly one at a time;
  // pricing is fetched only when the user opens a card for review.
  const [queue, setQueue] = useState([])            // [{key, file, status, result, error}]
  const [activeKey, setActiveKey] = useState(null)  // queue item currently in the form
  const processingRef = useRef(false)
```
3. Extract the pricing block from `runScan` into a reusable helper (place above `runScan`):
```js
  const fetchPricing = async (next) => {
    setPricingLoading(true)
    try {
      const pricing = await getPricing({
        player_name: next.player_name,
        year: next.year,
        brand: next.brand,
        set_name: next.set_name,
        card_number: next.card_number,
      })
      setComps(pricing.comps || [])
      setPricingNote(pricing.note || '')
      setPricingSource(pricing.source || '')
      if (pricing.suggested_price) {
        setForm((prev) => ({ ...prev, suggested_price: pricing.suggested_price }))
      }
    } catch {
      setPricingNote('Pricing lookup failed — set price manually.')
    } finally {
      setPricingLoading(false)
    }
  }
```
`runScan` calls `await fetchPricing(next)` where the inline block was.
4. Multi-file staging — replace the two `onChange={(e) => stageFile(e.target.files?.[0])}` handlers with `onChange={(e) => stageFiles(e.target.files)}`, add `multiple` to the FRONT file inputs (not the back input), change `onDrop` to `stageFiles(e.dataTransfer.files)`, and add:
```js
  const stageFiles = (fileList) => {
    const files = Array.from(fileList || [])
    if (files.length === 0) return
    if (files.length === 1) {
      stageFile(files[0])
      return
    }
    // Batch mode: front images only, no back slot.
    clearStaged()
    setActiveKey(null)
    setQueue(files.map((file, i) => ({
      key: `${Date.now()}-${i}`, file, status: 'queued', result: null, error: null,
    })))
  }
```
5. Sequential processor (one scan in flight, ever):
```js
  useEffect(() => {
    const next = queue.find((q) => q.status === 'queued')
    if (!next || processingRef.current) return
    processingRef.current = true
    const mark = (key, patch) =>
      setQueue((prev) => prev.map((q) => (q.key === key ? { ...q, ...patch } : q)))
    mark(next.key, { status: 'scanning' })
    scanCard(next.file, mode)
      .then((result) => mark(next.key, { status: 'ready', result }))
      .catch((e) => mark(next.key, { status: 'error', error: e.response?.data?.detail || 'Scan failed' }))
      .finally(() => { processingRef.current = false })
  }, [queue, mode])
```
6. Review a queue item (loads it into the existing form + fetches pricing):
```js
  const reviewQueueItem = async (item) => {
    const result = item.result
    if (!result) return
    setError(result.error || '')
    setImagePath(result.image_path)
    setMock(!!result.mock)
    setScanId(result.scan_id ?? null)
    setComps([])
    setPricingNote('')
    setPricingSource('')
    const next = { ...EMPTY_FORM, ...result.extracted, image_path: result.image_path, back_image_path: result.back_image_path || '' }
    setForm(next)
    setActiveKey(item.key)
    await fetchPricing(next)
  }
```
7. `handleSubmit` — after the existing reset block, add batch bookkeeping:
```js
      if (activeKey) {
        let nextReady = null
        setQueue((prev) => {
          const updated = prev.map((q) => (q.key === activeKey ? { ...q, status: 'saved' } : q))
          nextReady = updated.find((q) => q.status === 'ready') || null
          return updated
        })
        setActiveKey(null)
        if (nextReady) setTimeout(() => reviewQueueItem(nextReady), 0)
      }
```
8. Queue panel — render above the stage panels whenever `queue.length > 0`:
```jsx
      {queue.length > 0 && (
        <div className="card-panel">
          <div className="flex items-center justify-between mb-3">
            <div className="font-bold">Batch queue ({queue.filter((q) => q.status === 'saved').length}/{queue.length} saved)</div>
            <button
              type="button"
              className="text-xs text-gray-400 underline"
              onClick={() => { setQueue([]); setActiveKey(null) }}
            >
              Clear queue
            </button>
          </div>
          <div className="space-y-1.5">
            {queue.map((q) => (
              <div key={q.key} className="flex items-center gap-3 text-sm">
                <span className="flex-1 truncate text-gray-300">{q.file.name}</span>
                {q.status === 'queued' && <span className="text-gray-500 text-xs">waiting…</span>}
                {q.status === 'scanning' && <span className="text-yellow-400 text-xs">scanning…</span>}
                {q.status === 'error' && <span className="text-red-400 text-xs">{q.error}</span>}
                {q.status === 'saved' && <span className="text-emerald-500 text-xs">saved ✓</span>}
                {q.status === 'ready' && (
                  <button
                    type="button"
                    onClick={() => reviewQueueItem(q)}
                    className={`text-xs rounded px-2 py-1 ${activeKey === q.key ? 'bg-emerald-600 text-white' : 'bg-ink-700 text-gray-200 hover:bg-ink-600'}`}
                  >
                    {activeKey === q.key ? 'Reviewing' : 'Review'}
                  </button>
                )}
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-500 mt-3">Cards scan one at a time. Back-of-card images aren't supported in batch mode — scan those individually.</p>
        </div>
      )}
```
9. Stage-1 dropzone visibility: change its condition from `{!isStaged && !isScanned && (` to `{!isStaged && !isScanned && queue.length === 0 && (` so the queue panel replaces the dropzone while a batch is active. Also update the dropzone copy line "JPG, PNG, WEBP, or PDF" to "JPG, PNG, WEBP, or PDF — select multiple files to batch scan".

- [ ] **Step 2: Build + manual sanity**

Run: `cd frontend && npm run build` — Expected: success.
Run: `.venv/bin/python -m pytest backend/tests -q` — Expected: all PASS (no backend change; regression gate).

- [ ] **Step 3: Commit**

```bash
git add frontend
git commit -m "feat: sequential batch-scan queue on the scan page"
```

---

## Final verification (after Task 5)

- [ ] `.venv/bin/python -m pytest backend/tests -q` — all pass
- [ ] `cd frontend && npm run build` — clean
- [ ] `CARDLISTER_USERS="tester:pw" JWT_SECRET=s DB_PATH=/tmp/final.db` TestClient smoke: login → mock scan (with + without back) → create card with scan_id → GET /api/analytics shows corrections count
- [ ] Push branch, open PR against `feat/cardlister-improvements`
