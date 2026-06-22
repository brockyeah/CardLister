# CardLister

A dead-simple internal tool for listing baseball cards on eBay faster.

**Workflow:** snap a photo → Claude vision extracts the card details → sold-comp lookup (130point → Mavin → eBay) suggests a price → review and tweak the form → click Save to copy a ready-to-paste listing to your clipboard and open eBay's sell page. Every card is mirrored to a Google Sheet.

---

## Tech Stack

- **Backend:** FastAPI (Python 3.11), SQLAlchemy, SQLite
- **Frontend:** React 18 + Tailwind CSS, built with Vite
- **AI:** Anthropic Claude `claude-opus-4-7` with vision + adaptive thinking
- **Pricing:** eBay API when configured (primary), else a sold-comp scrape chain — 130point → Mavin → eBay (BeautifulSoup + httpx)
- **Inventory mirror:** Google Sheets API (write-only)
- **Deploy:** Single Docker container on Railway (one service, one URL)

---

## Local Development

You can run it as one process (Docker) or as two dev servers (recommended for active development).

### Two-server dev mode

**Backend (port 8000):**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # then edit .env with your secrets
export $(grep -v '^#' ../.env | xargs)   # or use a tool like direnv / dotenv
uvicorn backend.main:app --reload --port 8000
```

> Run `uvicorn` from the **project root** (one level above `backend/`) so the `backend.` package import path resolves.

**Frontend (port 5173):**

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` and `/uploads` to the FastAPI server.

### One-process production-style mode

```bash
cd frontend && npm install && npm run build
mkdir -p ../backend/static && cp -r dist/* ../backend/static/
cd ..
uvicorn backend.main:app --port 8000
```

Open <http://localhost:8000>.

### Docker

```bash
docker build -t cardlister .
docker run --rm -p 8000:8000 \
  -e CARDLISTER_PASSWORD=changeme \
  -e JWT_SECRET=$(openssl rand -hex 32) \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v $(pwd)/data:/data \
  cardlister
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `CARDLISTER_USERS` | optional | Comma-separated `username:password` pairs for multi-user access + per-user cost tracking, e.g. `brock:s3cret,sam:hunter2`. If unset, the app falls back to a single `owner` user (see `CARDLISTER_PASSWORD`). |
| `CARDLISTER_PASSWORD` | yes* | Password for the fallback single `owner` user when `CARDLISTER_USERS` is not set (log in with a blank username). Defaults to `changeme`; in production (`APP_ENV=production` or a Railway deploy) the app refuses to start if left at the default. |
| `JWT_SECRET` | yes | Long random string used to sign session tokens. Use `openssl rand -hex 32`. Same production fail-fast as above. |
| `APP_ENV` | optional | Set to `production` to enforce the secret checks above. Auto-detected on Railway; defaults to development locally. |
| `ANTHROPIC_API_KEY` | recommended | From <https://console.anthropic.com>. If missing, `/api/scan` returns mock data so the UI still works end-to-end. |
| `CLAUDE_MODEL` | optional | Vision model id. Defaults to `claude-opus-4-7`. Set to `claude-sonnet-4-6` to cut cost (test accuracy first). |
| `CLAUDE_EFFORT` | optional | Thinking depth: `low` \| `medium` \| `high`. Defaults to `medium`. Lower = cheaper. |
| `VISION_MAX_IMAGE_PX` | optional | Long-edge pixel cap applied to images before they're sent to the vision API (the on-disk upload is untouched). Defaults to `1300`; set `0` to disable downsampling. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | optional | The full JSON contents of a Google service account key file, as a single string. |
| `GOOGLE_SHEET_ID` | optional | The Sheet ID from the URL (`docs.google.com/spreadsheets/d/<THIS-PART>/edit`). |
| `EBAY_APP_ID` | optional | eBay App ID (OAuth client_id). With `EBAY_CERT_ID`, the eBay API becomes the **primary** comp source; without it the app falls back to the HTML scrapers. |
| `EBAY_CERT_ID` | optional | eBay Cert ID (OAuth client_secret), paired with `EBAY_APP_ID`. |
| `EBAY_MARKETPLACE_ID` | optional | eBay marketplace, default `EBAY_US`. |
| `EBAY_ENV` | optional | `production` (default) or `sandbox`. |
| `DB_PATH` | optional | Path to the SQLite file. Defaults to `./cardlister.db`. **On Railway, set to `/data/cardlister.db`.** |

---

## Railway Deployment

1. **Create a new Railway project** and connect this repo (or push it to GitHub first and link from there).
2. Railway auto-detects the `Dockerfile` and `railway.toml`.
3. **Add a Volume** (in the service Settings → Volumes):
   - Mount path: `/data`
   - Any size — a few GB is plenty.
4. **Set environment variables** in Railway (Service → Variables):
   - `CARDLISTER_PASSWORD`
   - `JWT_SECRET`
   - `ANTHROPIC_API_KEY`
   - `GOOGLE_SERVICE_ACCOUNT_JSON` (paste the whole JSON object as a single line)
   - `GOOGLE_SHEET_ID`
   - `DB_PATH=/data/cardlister.db`
5. Deploy. Railway exposes the URL — log in with your password.

> ⚠️ **Without the `/data` volume, every redeploy wipes your SQLite DB and uploaded images.** This is the single biggest deployment mistake to avoid. The volume is what makes the data persistent across deploys.

---

## Google Sheets Setup

The Sheets sync is a write-only mirror — the SQLite DB remains the source of truth.

1. Go to <https://console.cloud.google.com>, create (or pick) a project.
2. Enable the **Google Sheets API** for that project.
3. Under **APIs & Services → Credentials**, create a **Service Account**.
4. On the service account, go to **Keys → Add Key → JSON**. A JSON file downloads.
5. Open the file. The whole contents — including `{` and `}` — is what you paste into `GOOGLE_SERVICE_ACCOUNT_JSON`.
6. Create the target Google Sheet (or reuse one). Copy its ID from the URL into `GOOGLE_SHEET_ID`.
7. **Share the sheet with the service account's email address** (`...@<project>.iam.gserviceaccount.com`) with **Editor** access. This is the step everyone forgets.
8. Save a card. The `Inventory` tab will be created automatically with the correct headers.

If sync fails for any reason it is logged but never blocks the API request — Sheets is non-critical.

---

## Sheet Column Order

`Player | Year | Brand | Set | Card # | Team | RC | Auto | Patch | Condition | Listed Price | eBay URL | Status | Date Listed | Date Sold | Sale Price | Notes`

---

## eBay Listing Title Format

```
{year} {brand} {set_name} {player_name} #{card_number} {flags} {team}
```

Where flags is any combination of `RC`, `AUTO`, `PATCH`, `REFRACTOR`, `/99`, etc. Capped at 80 characters (eBay's limit).

Example: `2021 Bowman Chrome Wander Franco #BCP-100 RC /99 Tampa Bay Rays`

---

## Mock Mode

The app is fully usable without any API keys:

- **No `ANTHROPIC_API_KEY`** → `/api/scan` returns a hardcoded mock card and labels it `mock: true` in the response (the UI shows a yellow banner). If the key *is* set but the vision call fails, the response instead carries an `error` string and a blank card, and the UI shows a red error banner — distinct from mock mode.
- **All comp sources return nothing** (130point, Mavin, eBay) → pricing returns `$9.99` with `source: "mock"` and a note explaining what failed.

This is intentional — it lets you exercise the full flow during development.

---

## Phase 2 (Stubbed, Not Built)

Look for `# TODO (Phase 2)` comments throughout the codebase:

- **eBay OAuth + Sell API** — direct listing creation, replaces the pre-fill URL flow.
- **eBay Orders API polling cron** — auto-mark cards sold when they sell on eBay.
- **Bulk CSV import** — migrate existing inventory in one shot.
- **PSA/BGS grade detection** — vision step extracts grade slab info if present.

---

## Updating the Database Schema

The app uses SQLAlchemy's `create_all` on startup, which only adds *new* tables — it won't migrate existing ones. If you change a column on the `cards` table:

- **Local dev:** delete `cardlister.db` (you'll lose data) and restart, OR run a one-off migration with `sqlite3` (`ALTER TABLE cards ADD COLUMN ...`).
- **Production (Railway):** SSH-equivalent isn't trivial here. Easier: scale the service to 0, attach to the volume from a one-shot job that runs the `ALTER TABLE`, then redeploy.
- **Long-term:** add Alembic when the schema starts changing more than once or twice.

---

## Project Layout

```
cardlister/
├── backend/
│   ├── main.py              # FastAPI app, mounts routers + static frontend
│   ├── database.py          # Engine, session, Base
│   ├── models.py            # Card SQLAlchemy model
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── auth.py              # Named users + JWT
│   ├── routers/
│   │   ├── cards.py         # CRUD + mark sold + attach eBay listing
│   │   ├── scan.py          # Image upload → Claude vision (records usage)
│   │   ├── pricing.py       # eBay API + scraper comp chain
│   │   ├── ebay.py          # Listing text builder
│   │   ├── sheets.py        # Manual resync endpoints
│   │   └── usage.py         # Per-user cost-split report
│   ├── services/
│   │   ├── claude_vision.py # Claude API call
│   │   ├── ebay_api.py      # eBay API pricing (primary)
│   │   ├── onethirtypoint.py / mavin.py / ebay_pricing.py  # scraper fallbacks
│   │   ├── pricing_utils.py # shared query/price helpers
│   │   └── google_sheets.py # Sheets API write layer
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Router + nav
│   │   ├── api.js           # Axios wrapper + token storage
│   │   ├── pages/
│   │   │   ├── Login.jsx
│   │   │   ├── Scanner.jsx  # Upload + review (default page)
│   │   │   ├── Inventory.jsx
│   │   │   └── Usage.jsx    # Per-user cost split
│   │   └── components/
│   │       ├── CardForm.jsx
│   │       ├── CardTable.jsx
│   │       └── StatusBadge.jsx
│   ├── index.html
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── package.json
├── Dockerfile
├── railway.toml
├── .env.example
└── README.md
```
