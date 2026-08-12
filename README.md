# CardLister

A dead-simple internal tool for listing baseball cards on eBay faster.

**Workflow:** snap a photo → Claude vision extracts the card details → comp lookup suggests a price → review and tweak the form → click Save to copy a ready-to-paste listing to your clipboard and open eBay's sell page. Every card is mirrored to a Google Sheet.

---

## Tech Stack

- **Backend:** FastAPI (Python 3.11), SQLAlchemy, SQLite
- **Frontend:** React 19 + React Router 8 + Tailwind CSS, built with Vite
- **AI:** Anthropic Claude with vision + adaptive thinking; model and thinking depth
  are chosen per scan by the Cost / Balanced / Accuracy selector
- **Pricing:** eBay Browse API when configured (primary — note it returns *active*
  listings), else a sold-comp scrape chain — 130point → Mavin → eBay (BeautifulSoup + httpx)
- **Inventory mirror:** Google Sheets API (write-only)
- **Deploy:** Single Docker container on Railway (one service, one URL, **one worker**)

---

## Local Development

You can run it as one process (Docker) or as two dev servers (recommended for active development).

### Two-server dev mode

**Backend (port 8000):** run everything from the **project root** — the venv lives there, and the `backend.` package import path only resolves from there.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cp .env.example .env         # then edit .env with your secrets
export $(grep -v '^#' .env | xargs)   # or use a tool like direnv / dotenv
uvicorn backend.main:app --reload --port 8000
```

> Set `DISABLE_CALLUP_POLLER=1` to silence the background call-up poller during local work.

**Frontend (port 5173):**

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` and `/uploads` to the FastAPI server.

### Tests

```bash
# Backend — from the project root (module form puts the root on sys.path)
python -m pytest backend/tests -q
python -m pytest backend/tests/test_ebay_title_parity.py -q          # one file
python -m pytest backend/tests/test_presets.py::test_unknown_preset_falls_back_to_env_defaults -q

# Frontend
cd frontend && npm test                              # vitest run
cd frontend && npx vitest run src/lib/ebayTitle.test.js
```

There is no linter or formatter configured. CI runs the backend suite, the frontend
tests + build, and a non-blocking dependency audit.

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
| `ANTHROPIC_API_KEY` | recommended | From <https://console.anthropic.com>. If missing, `/api/scan` uses the subscription fallback (below) if configured, else returns mock data so the UI still works end-to-end. |
| `CLAUDE_CODE_OAUTH_TOKEN` | optional | From `claude setup-token` (Claude Pro/Max plan; expires ~yearly). Scan fallback: when the API key is missing **or out of credits**, scans run headlessly through the Claude Code CLI and bill the subscription instead of failing. Personal-use setups only. |
| `NTFY_TOPIC` | optional | [ntfy.sh](https://ntfy.sh) topic for phone-push alerts when API credits run out (email also goes to `ALERT_EMAILS`). Pick a long random topic name and subscribe to it in the ntfy app. `BILLING_ALERT_THROTTLE_SECONDS` spaces repeats (default 6h). |
| `CLAUDE_MODEL` | optional | Fallback vision model id (default `claude-opus-4-7`). Per-scan choice is normally driven by the **Scan mode** selector (Cost / Balanced / Accuracy); this is the fallback when no preset is sent. |
| `CLAUDE_EFFORT` | optional | Fallback thinking depth: `low` \| `medium` \| `high` (default `medium`). Also superseded per-scan by the Scan mode selector. |
| `VISION_MAX_IMAGE_PX` | optional | Long-edge pixel cap applied to images before they're sent to the vision API (the on-disk upload is untouched). Defaults to `1300`; set `0` to disable downsampling. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | optional | The full JSON contents of a Google service account key file, as a single string. |
| `GOOGLE_SHEET_ID` | optional | The Sheet ID from the URL (`docs.google.com/spreadsheets/d/<THIS-PART>/edit`). |
| `EBAY_APP_ID` | optional | eBay App ID (OAuth client_id). With `EBAY_CERT_ID`, the eBay API becomes the **primary** comp source; without it the app falls back to the HTML scrapers. |
| `EBAY_CERT_ID` | optional | eBay Cert ID (OAuth client_secret), paired with `EBAY_APP_ID`. |
| `EBAY_MARKETPLACE_ID` | optional | eBay marketplace, default `EBAY_US`. |
| `EBAY_ENV` | optional | `production` (default) or `sandbox`. |
| `EBAY_VERIFICATION_TOKEN` | optional | 32–80 chars, required to enable a production eBay keyset. The same value goes in the developer portal's marketplace account-deletion form; the app answers eBay's challenge handshake at `/api/ebay-compliance/account-deletion`. |
| `EBAY_DELETION_ENDPOINT_URL` | optional | The full public URL of that endpoint (`https://<host>/api/ebay-compliance/account-deletion`). It is part of the challenge hash, so it must match the portal field exactly. |
| `SMTP_HOST` / `SMTP_PORT` | optional | SMTP server for alert emails, default `smtp.gmail.com:587`. Unused when `SENDGRID_API_KEY` is set. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | optional | Gmail address + App Password for call-up alert emails. Without them the call-up ticker still works; only emails are skipped. |
| `ALERT_EMAILS` | optional | Comma-separated alert recipients. |
| `SENDGRID_API_KEY` | optional | SendGrid API key — the preferred email path on Railway (SMTP is blocked there). Takes precedence over SMTP when set. |
| `ALERT_FROM` | optional | Verified SendGrid single-sender address. Defaults to `SMTP_USERNAME`. |
| `CALLUP_POLL_MINUTES` | optional | Minutes between MLB call-up polls. Default `15`. |
| `NEWS_FEEDS` | optional | Comma-separated RSS feed URLs for the news section (defaults to MLB.com feeds). |
| `DB_PATH` | optional | Path to the SQLite file. Defaults to `./cardlister.db`. **On Railway, set to `/data/cardlister.db`.** Uploaded images are stored in an `uploads/` directory *derived from this path*, so one volume covers both. |
| `DISABLE_CALLUP_POLLER` | optional | Set to `1` to skip starting the background call-up poller (used by the test suite and handy in local dev). |

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

**Production URL:** _not recorded yet — after deploying, paste the Railway URL
here so tooling (e.g. the daily review routine) can ping `GET /api/health`._
The health endpoint is unauthenticated and reports DB reachability, the
deployed revision, and the call-up poller heartbeat; it returns 503 when the
database is unreachable so any HTTP uptime monitor can alert on status alone.

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

SQLAlchemy's `create_all` runs on startup but only creates *missing tables* — it never
alters existing ones. A lightweight migration list closes that gap:

- **New table:** nothing to do; `create_all` builds it complete.
- **New column on an existing table:** add a `(table, column, ddl)` entry to
  `_COLUMN_MIGRATIONS` in `backend/database.py`. It's applied idempotently at startup,
  so deployed databases pick it up on the next boot. **Skipping this means the column
  works on a fresh local DB and is missing in production.**
- Alembic is still the long-term answer if the schema starts changing often.

---

## Project Layout

```
cardlister/
├── backend/
│   ├── main.py              # FastAPI app: routers, health, call-up poller, static mount
│   ├── database.py          # Engine, session, uploads_dir, _COLUMN_MIGRATIONS
│   ├── models.py            # Card, Scan, Correction, UsageEvent, CallupEvent
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── auth.py              # Named users + JWT + production secret checks
│   ├── routers/             # cards, scan, pricing, ebay, ebay_compliance,
│   │                        #   sheets, analytics, news
│   ├── services/            # claude_vision, learning, ebay_api, comp scrapers
│   │                        #   (onethirtypoint/mavin/ebay_pricing), pricing_utils,
│   │                        #   google_sheets, callups, prospect_news, mailer,
│   │                        #   billing_alerts
│   ├── tests/               # pytest suite + shared fixtures/
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.jsx          # Routes + nav shell + auth gate
│       ├── api.js           # Axios wrapper + token storage
│       ├── pages/           # Login, Scanner (default), Inventory, Analytics
│       ├── components/      # CardForm, CardTable, StatusBadge, NewsSection
│       └── lib/             # ebayTitle, downscaleImage, sortCards (+ their tests)
├── docs/                    # BACKLOG.md, notes/, superpowers/{specs,plans}
├── CHANGELOG.md             # on `main`, this is the record of what production runs
├── CLAUDE.md                # architecture + invariants for AI coding agents
├── Dockerfile
├── railway.toml
└── .env.example
```

## License

[MIT](LICENSE)
