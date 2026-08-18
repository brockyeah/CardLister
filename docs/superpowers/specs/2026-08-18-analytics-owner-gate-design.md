# Analytics User-Admin Owner Gate — Design

**Status:** proposed, awaiting owner approval
**Filed:** 2026-08-18
**Scope:** `backend/auth.py`, `backend/routers/analytics.py`,
`frontend/src/pages/Analytics.jsx`, `backend/tests/test_user_admin.py`

## The problem, concretely

`POST /api/analytics/users/reassign` and
`DELETE /api/analytics/users/{username}/data` are guarded only by the
router-level `Depends(require_auth)` (`routers/analytics.py:28`), which proves
*some* configured user is logged in and nothing more. Neither handler takes the
caller's username, though `require_auth` is already used as a value dependency
elsewhere (`routers/scan.py:84`, `routers/cards.py:355`).

`reassign_user` validates only the **target** (`analytics.py:157-160`: target
must be configured, and must differ from the source). Nothing constrains the
source. `delete_user_data` validates nothing at all (`analytics.py:170-177`).

**Reproduced against a running app** with `CARDLISTER_USERS="brock:pw1,alan:pw2"`:
Alan reassigned every one of Brock's usage/scan/correction rows onto himself and
then deleted them — both `200 OK`, corrections left in the DB: 0.

Two consequences, and the second is the one that matters:

- **The ledger can be rewritten in either direction.** The backlog frames the
  risk as pulling the other user's rows onto yourself, which merely inflates
  your own bill. The damaging move is the opposite: `{from_user: "alan",
  to_user: "brock"}` returns 200 and `GET /api/analytics?range=all` then bills
  the entire spend to Brock. This is the ledger the two users split real API
  costs with.
- **The delete is unrecoverable data loss, and it is not "a user's" data.**
  `_USER_TABLES = (UsageEvent, Scan, Correction)` (`analytics.py:152`).
  `Correction` rows are the learning loop's training data and are
  **deliberately shared across users** — `build_cheatsheet()`
  (`services/learning.py:73`) and `find_exact_match()` (`learning.py:99-105`)
  filter on card identity, never on username. So deleting "Alan's" corrections
  degrades *Brock's* scan accuracy too. And they cannot be rebuilt in-app,
  because the same call deletes the `Scan` rows they would have to be
  re-derived from (`learning.py:48-68`).

## This supersedes an earlier decision — deliberately

This was not an oversight. `docs/superpowers/specs/2026-07-09-callup-alerts-design.md:41`
(status: *approved by owner*) states: "Any authenticated user may act (two
trusted users; no roles — consistent with the app's documented trust model)."
`git log -- backend/routers/analytics.py` shows the handlers unchanged since.

That reasoning still holds for **reading** and for **cards**, which are shared
inventory with no owner column. It does not hold for the two routes that can
silently rewrite the cost ledger or destroy shared training data. The trust
model is not the issue; the absence of an undo is. Nothing here changes the
shared-inventory design.

## Root cause

`CARDLISTER_USERS` has no roles. `get_users()` (`auth.py:42-56`) returns a flat
`{username: password}` dict, and `require_auth` (`auth.py:118-137`) returns a
username after verifying the JWT and that the subject is still configured. There
is no notion of *who may administer whom*, so the only available check today is
"is anyone logged in".

## Approaches

### A. `CARDLISTER_OWNER` env var, 403 for everyone else — **recommended**

A new optional env var names the administrator. Unset, it resolves to the first
entry of `CARDLISTER_USERS` (insertion-ordered since Python 3.7), or to
`owner` under the single-user fallback (`auth.py:22,44`) — so a single-user
deployment behaves exactly as today.

- Fits the feature's actual purpose (see B for why that is decisive).
- Reusable: the same `require_owner` dependency is the obvious gate for any
  future destructive admin action.
- Introduces a role concept the app has so far avoided — a real, if small,
  increase in configuration surface.

### B. Require `from_user == caller` / `username == caller` — **rejected**

Let a user touch only their own attribution.

- **Rejected, because it breaks the feature's only real use case.** The panel
  exists to merge a *ghost* username — `cardlister-user`, left behind by the
  pre-multi-user JWT (`2026-07-09-callup-alerts-design.md:9`). Since
  `auth.py:135-136` now 401s any token whose subject is not in `get_users()`, a
  ghost can never be the caller. Under B, the ghost merge becomes impossible —
  and per `project_open_threads`, that merge may still be pending in production.
  The UI's source dropdown is fed from distinct `UsageEvent` usernames
  (`analytics.py:125,147` → `Analytics.jsx:193,375`), i.e. exactly the set of
  ghosts plus real users.
- **It also fails to stop the attack that matters.** Pushing your own spend onto
  the other user satisfies `from_user == caller` perfectly.

### C. Retire the routes entirely

Delete the panel; do ghost merges with a one-off script.

- Smallest attack surface, no new config.
- **Rejected for now**, on sequencing: the ghost merge may be unperformed in
  production, and removing the only tool for it before it has run trades a
  fixable authorization gap for a manual database edit. Worth revisiting once
  the ghost is confirmed merged.

## Recommendation

**A**, with the following non-obvious details — three of which are corrections
to the obvious implementation, each of which would otherwise ship a bug.

**1. A bad `CARDLISTER_OWNER` must not be a boot failure.** The natural
instinct is to validate it in `validate_secrets()`. Do not: that function has a
single `problems` list and *any* non-empty list raises `RuntimeError` in
production (`auth.py:79-107`), production is auto-detected on Railway
(`auth.py:70-77`), and `main.py:67-69` calls it at startup. A typo in an
optional variable would take the whole app down — strictly worse than the gap
being fixed. Log a warning and fall back to the positional default instead.

**2. The gate belongs on the photo cleanup too.** `POST /api/analytics/uploads/cleanup`
(`analytics.py:266-279`) permanently `unlink()`s files, and uploads are the only
data in the system with **no backup path** — `GET /analytics/backup.db`
(`analytics.py:186-214`) snapshots the SQLite file only. Gating the two
recoverable routes while leaving the unrecoverable one open would miss the
point. `GET /analytics/storage` and `GET /uploads/orphans` are read-only and
stay open.

**3. Ownership resolution should fail loud, not drift silently.** The positional
default means re-pasting `CARDLISTER_USERS` in a different order silently
transfers ownership. A subtler variant: `get_users()` skips an entry with an
empty username (`auth.py:53`), so a stray leading colon (`:pw,alan:pw2`)
promotes Alan to first. Mitigation: log the resolved owner at startup, and
document in README/`.env.example` that `CARDLISTER_OWNER` should be set
explicitly in any multi-user deployment.

Deliberately unchanged: cards, scanning, pricing, and every read route. This is
two destructive routes plus one unrecoverable one.

## What could go wrong

- **`configured_users()` response shape.** Surfacing the owner to the UI means
  adding a key to `analytics.py:180-183` — which breaks
  `test_user_admin.py:55-58`, an exact-dict-equality assertion. It is a
  one-line test update, but it *will* go red on the first run and the plan must
  say so.
- **The new gate gets no coverage by default.** `conftest.py:6-9` sets
  `CARDLISTER_USERS="tester:pw"` — one user — so `resolve_owner()` returns
  `tester`, every existing test stays green, and the gate is never exercised.
  The cross-user test must mint a second user at runtime with
  `monkeypatch.setenv`; this works because `get_users()` re-reads the env on
  every call (`auth.py:42`), verified by logging in as a user added after import.
- **`UsageEvent` fixture pollution.** `db_session` (`conftest.py:18-26`) deletes
  `Card`, `Correction`, `Scan`, `CallupEvent` — not `UsageEvent`, and
  `test_user_admin.py:34` leaves rows behind. Adding `UsageEvent` to that list
  is necessary but **not sufficient**: the deletes run at setup, before
  `yield`, so a test that does not request the fixture (e.g.
  `test_configured_users_lists_env_users`) still sees leftovers.
- **The UI gate's initial state.** `ManageData` fetches configured users in a
  `useEffect` with `.catch(() => setTargets([]))` (`Analytics.jsx:210-213`). If
  the owner arrives through the same call, it is `undefined` on first render and
  after any transient failure — so the buttons must default to *hidden/disabled*
  and the frontend gate must be treated as cosmetic. The server check is the
  real one.
- **Confidentiality is unchanged and still shared.** Any configured user can
  still download the entire database via `GET /analytics/backup.db`. This design
  is about destructive writes, not secrecy; say so plainly rather than implying
  the gate makes per-user data private.
- **Dependency composition is fine** (verified): `require_owner` as a
  route-level dependency composes with the router-level `require_auth` —
  FastAPI caches sub-dependency results per request, so the JWT is decoded once
  and an unauthenticated request still 401s before reaching the owner check.

## Cost impact (required check)

None. No Anthropic calls, no new external requests, no schema change.

## Verification

- A second configured user is **403**'d from reassign, delete-user-data, and
  uploads cleanup — the test the current suite cannot express, since it only
  ever has one user.
- The owner is still allowed all three.
- The ghost merge still works for the owner (the use case B would have broken).
- An unconfigured `CARDLISTER_OWNER` falls back to the first entry **and the app
  still boots** — the regression test for correction 1.
- Single-user deployments are unaffected: with one entry, that user is the owner.
