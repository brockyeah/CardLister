# Call-Up Alerts + Prospect News + User-Data Admin — Design

**Date:** 2026-07-09 · **Status:** Approved by owner (design conversation)

## Motivation

Prospect cards — above all "1st Bowman" cards (`BCP-###` etc.) — spike in value the day a player is called up from the minor leagues to the Majors. Alan (the second user) sells into that pop and asked for automatic email alerts when a call-up happens, plus a news section in the app. Being early to the news is the value; the app already knows which players' cards are in inventory, so it can turn a league-wide transaction feed into a personal sell signal.

A small unrelated fix rides along: Analytics shows a ghost username `cardlister-user` (scans attributed via a pre-multi-user JWT that stayed valid after deploy). The owner wants to merge/delete that data and prevent recurrence.

## Detection source (decided)

**MLB Stats API** (`https://statsapi.mlb.com/api/v1/transactions?startDate=…&endDate=…`) — free, no key, structured JSON. Verified live 2026-07-09: returns typed transactions including `typeDesc: "Selected"` (contract selected from minors = **first-ever call-up**, the big value event) and `"Recalled"` (returning from Triple-A, smaller bump), each with player person id/name, teams, date, description, and a stable transaction `id` usable for dedup. RSS keyword-scanning was rejected for detection (fuzzy, late, misses quiet transactions) but **is** used for the news display, porting the proven `feedparser` + keyword/recency-scoring engine from the owner's Daryls-Digest project.

## Component 1 — Alert engine (`backend/services/callups.py`)

- `fetch_callup_transactions(start_date, end_date) -> list[dict]`: GET the transactions endpoint, keep only `typeDesc in {"Selected", "Recalled"}`, normalize to `{tx_id, date, type_desc, player_name, person_id, to_team, description}`. Any network/parse failure returns `[]` (logged) — the poller just tries next cycle.
- **Inventory matching:** `normalize_name(s)` (casefold, strip accents via `unicodedata`, collapse punctuation/whitespace) compares transaction player names against `Card.player_name`. Match ⇒ sell signal; count matched cards (sum of `quantity`).
- **Alert rule (decided):** email-worthy = inventory match (either type) **or** `Selected` league-wide. `Recalled` without inventory match is recorded for the ticker but not emailed.
- `run_poll_cycle(db) -> dict`: fetch trailing 2-day window → dedup against `callup_events.tx_id` → insert new rows (with `inventory_match`, `matched_card_count`) → collect alertable rows with `emailed_at IS NULL` and age < 48h → send ONE digest email per cycle → stamp `emailed_at` on success. Email failure leaves `emailed_at` null so the next cycle retries (bounded by the 48h age check). Returns counts for logging/tests.
- **Scheduler:** asyncio background task created on FastAPI startup; loops `run_poll_cycle` every `CALLUP_POLL_MINUTES` (default 60). Skipped entirely when `DISABLE_CALLUP_POLLER=1` (tests). Railway keeps the process alive, so an in-process loop suffices; off-season cycles are cheap no-ops.

## Component 2 — Mailer (`backend/services/mailer.py`)

- Stdlib `smtplib` + `email.message.EmailMessage`, STARTTLS. Env: `SMTP_HOST` (default `smtp.gmail.com`), `SMTP_PORT` (587), `SMTP_USERNAME`, `SMTP_PASSWORD` (Gmail App Password — set directly in Railway, never in chat), `ALERT_EMAILS` (comma-separated recipients).
- `is_configured() -> bool`; `send_email(subject, text_body) -> bool` (never raises; logs failures).
- Unconfigured ⇒ poller still records events (ticker works), logs one notice, sends nothing.
- Digest format: subject `🚨 Call-up alert: <first player> (+N more)`; body lists each event — player, team, FIRST CALL-UP vs recalled, MLB description, and `You own N card(s) of this player` for inventory matches, matches listed first.

## Component 3 — News (`backend/services/prospect_news.py` + `GET /api/news` + `NewsSection.jsx`)

- RSS engine ported from Daryls-Digest `rss_parser.py`: fetch via `requests` w/ browser UA, parse via `feedparser` (new dep), score = keyword hits (title bonus) + recency bonus. Keywords: call-up phrases ("called up", "call-up", "contract selected", "promoted", "top prospect", "debut", "recalled"). Default feeds: MLB.com news RSS + configurable via `NEWS_FEEDS` env (comma-separated URLs).
- `GET /api/news` (auth required): `{callups: [...last 7 days of callup_events, inventory matches flagged...], articles: [top 8 scored]}`. In-process TTL cache (15 min) so the scan page stays fast and feeds aren't hammered; the callups half reads the DB fresh (cheap).
- `NewsSection.jsx` below the scan dropzone, collapsible (default open, state in localStorage): **Call-Up Ticker** (date, player, team, type badge; inventory matches get an emerald "YOU OWN N" badge) above a compact article list (title · source · age; `target="_blank" rel="noopener"`). Section renders nothing (not an error box) when both lists are empty.

## Component 4 — User-data admin + ghost-token fix

- `require_auth` additionally rejects tokens whose `sub` is not in `get_users()` (401) — pre-multi-user tokens (`cardlister-user`) and tokens for renamed/removed users die immediately instead of in 30 days.
- `POST /api/analytics/users/reassign` `{from_user, to_user}`: UPDATE `usage_events`, `scans`, `corrections` usernames; `to_user` must be a configured user; `from_user != to_user`. Returns per-table row counts.
- `DELETE /api/analytics/users/{username}/data`: delete that username's rows in the same three tables. Returns counts.
- Analytics UI "Manage data" panel: distinct usernames from the data with **Merge into [configured-user dropdown]** and **Delete** (confirm dialog). Any authenticated user may act (two trusted users; no roles — consistent with the app's documented trust model). Cards are NOT touched (shared inventory has no owner column).

## Data model

`callup_events` (new table; `create_all` picks it up): `id` PK, `tx_id` (Integer, unique, indexed — MLB transaction id), `date` (String YYYY-MM-DD), `type_desc` (String), `player_name` (String), `person_id` (Integer nullable), `to_team` (String), `description` (Text), `inventory_match` (Boolean), `matched_card_count` (Integer default 0), `emailed_at` (DateTime nullable), `created_at` (DateTime default now).

## New env vars

| Var | Default | Purpose |
|---|---|---|
| `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `587` | Mail relay |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | — | Gmail address + App Password |
| `ALERT_EMAILS` | — | Comma-separated recipients |
| `CALLUP_POLL_MINUTES` | `60` | Poll cadence |
| `DISABLE_CALLUP_POLLER` | unset | `1` disables scheduler (tests/dev) |
| `NEWS_FEEDS` | built-in list | Override RSS feed URLs |

## Testing

- Transactions: fixture JSON (real API shape) → filter, normalization ("Acuña Jr." ≡ "acuna jr"), dedup on second cycle, alert-rule selection, 48h retry window.
- Mailer: mocked `smtplib.SMTP`; unconfigured ⇒ `send_email` False without network.
- Poll cycle: fake fetch + fake mailer; asserts rows inserted, digest composed once, `emailed_at` stamped only on success.
- News: mocked feed content → scoring order; endpoint shape; cache TTL respected.
- Admin: reassign moves counts across the three tables; delete removes; unknown `to_user` 400; ghost-token 401 (token minted for a non-configured user).
- Existing suite (18) keeps passing; `DISABLE_CALLUP_POLLER=1` in test conftest env.

## Out of scope (explicit)

Price tracking/repricing, sub-hour or push/SMS alerts, per-user alert preferences, article summarization, prospect rankings ingestion, retroactive backfill of historical call-ups.
