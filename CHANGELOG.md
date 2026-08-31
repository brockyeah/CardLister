# Changelog

All notable changes to CardLister are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com); since the app is continuously
deployed from `main` (no version tags), entries are grouped by merge date and
PR instead of version numbers.

**Convention:** work lands under `[Unreleased]` on the feature branch; the
entry moves under a dated heading when its PR merges to `main`. The changelog
as it reads **on `main` is the record of what production runs** — anything
only in `[Unreleased]` on a branch is not in prod yet.

## [Unreleased] — branch `claude/sweet-rubin-l1g3u3`

<!--
The #52–#58 integration section below is still headed `[Unreleased]` even
though PR #59 has merged. Left alone deliberately, for the same reason PRs #63,
#64 and #65 left it alone: PRs #60, #61 and #62 were each opened to date that
one line, PR #67 dates it too, and a sixth edit of the same heading would be a
sixth conflicting change. Whichever of those merges owns it.
-->

### Fixed
- A sale can no longer be dated in the future. Nothing bounded `sold_at` at
  all — `MarkSoldRequest` validated only that `sold_price > 0`, and the picker
  carried no `max` — so a mistyped year was accepted in silence and then
  became permanent furniture: it joins the sold-years picker forever, sorts to
  the end of every tax export, and the only way back is unmark-sold and redo.
  The picker is now capped at the local date it already defaults to, the
  server rejects anything more than a day ahead of its own clock, and the
  modal renders the rejection instead of dropping it — a failed confirm used
  to reject its promise into nothing, leaving the dialog open and unchanged as
  though the click had not happened. A day of slack is deliberate: the client
  submits an instant built from *its* clock and the two need not agree.
  Backdating stays unbounded, because recording a sale weeks after the fact is
  ordinary and a floor would refuse it.
- The bound is checked on the value as it will be **stored**, not as it was
  sent. SQLAlchemy's SQLite dialect drops tzinfo without converting (a
  runtime-proven fact recorded in the local-timezone design doc), so an aware
  `2026-09-01T12:00+14:00` validated as the instant it really is would then be
  stored as the wall-clock `2026-09-01 12:00` — a day past the bound that had
  just admitted it. Submitted values are normalized to naive UTC first, which
  is what the rest of the app already assumes (`mark_sold`'s own fallback is
  `datetime.utcnow()`) and what the modal already sends. When
  `backend/timeutils.py` lands from the local-timezone plan, that normalization
  becomes a call to its `utc_naive()`.
- The CSV importer applies the same bound to a `Date Sold` column, because that
  is the other route a sale date takes into the database and the one where the
  value came out of a file someone else edited. A future date is dropped with a
  per-row warning rather than failing the row — the rest of it is fine, and the
  row falls back to the same default a sold row carrying no date at all already
  gets.
- `suggested_price` has the `ge=0` floor `listed_price` has always had. The two
  are the same kind of value read by the same consumers — the Sheets price
  column, the eBay listing text, the inventory value tile — and only one was
  guarded, so a negative comp median or a hand-crafted PATCH was stored and
  mirrored. The floors are stated on the **input** models only:
  FastAPI validates responses too, so inheriting them onto `CardOut` would turn
  a single legacy row saved before the floor existed into a 500 on
  `GET /api/cards` — the entire inventory unreadable because one price is
  wrong. Reads report what is stored; only writes are bounded, and a test pins
  that distinction (it fails, with a 500, if the floors are inherited).
- A test fixture that had been quietly ahead of the calendar. The sold-export
  ordering test marked a card sold on `2026-12-20`, which is a *future* sale
  for most of the year it names — harmless while nothing bounded a sale date,
  and a date-dependent failure the moment one existed. Its sales now sit in a
  year that has fully elapsed, which is stable in both directions.

## [Unreleased] — branch `integration/prs-52-58` (integrates PRs #52–#58)

### PR #52 — Pricing sources run concurrently

#### Changed
- Pricing sources now run concurrently instead of one after another. The chain
  only ever expressed *preference* — no source's input comes from another's
  output — yet the user waited for the sum of four timeouts (15 + 20 + 15 +
  15s). On Railway the scrapers routinely 403, so the common case was the
  worst case, on every card, and `Scanner.jsx` awaits one lookup per card, so a
  twenty-card batch multiplied it. Measured on the real timeout values, an
  all-fail lookup drops from 65s to about 20s — roughly the slowest single
  source, which is the floor for this shape.
- Resolution still walks the preference order and is **never** first-to-finish:
  a fast weak source beating a slow strong one would return the wrong comp
  under the wrong note and look perfectly healthy. Every note string is
  unchanged — per-source on success, `" | "`-joined on the all-failed mock —
  and an unconfigured eBay API still contributes nothing. `PRICING_DEADLINE_SECONDS`
  caps the whole lookup on our own wall clock rather than trusting the
  per-source `httpx` timeouts, which apply per connect/read/write/pool
  operation rather than as a request budget.

#### Added
- First tests for the pricing endpoint (`test_pricing_chain.py`, 12 cases),
  which had none. The ten contract cases were written against the serial
  implementation and pass unchanged after the refactor, so they pin the
  behaviour rather than describing what it became; the two concurrency cases
  fail against the old code.

### PR #53 — Listing text stops inventing $0.00; local mark-sold date

#### Fixed
- The eBay listing text no longer offers `$0.00` for a card that has no price.
  `ebay_listing_text` fell back to `card.suggested_price or 0`, so a card saved
  before the comps lookup resolved — or one where every pricing source failed —
  produced `PRICE:\n$0.00` in the clipboard block that is pasted straight into
  eBay's sell form. That is not a shortened truth the way a dropped title flag
  is: a zero reads as a filled-in field, and unlike a wrong player name it is
  not the kind of thing a seller catches on review, so the listing can go live
  priced at nothing. The endpoint now says the price is not set instead of
  inventing one, and returns `price: null` plus a `has_price` flag; a
  non-positive price counts as unset for the same reason the comps panel renders
  an unusable comp as unavailable. Both copy paths surface it before the paste —
  the Scanner save toast and the Inventory Copy Text / Open eBay buttons say the
  card has no price yet and point at Comps.
- The mark-sold date picker pre-fills the day the user is actually having.
  `MarkSoldModal` defaulted it from `new Date().toISOString().slice(0, 10)`,
  which is the *UTC* date, so from 8pm EDT onward it offered **tomorrow** and an
  evening sale was stamped a day late unless the user noticed and corrected it.
  The submit half had the mirror-image problem: a bare `YYYY-MM-DD` handed to
  `new Date()` parses as UTC midnight per spec, which sits against a boundary
  that a reader west of UTC crosses. Sold dates feed the Sheets "Date Sold"
  column, the tax-year CSV export and the planned days-to-sell analytics, so a
  date off by one propagates — and a sale that slides across New Year's lands in
  the wrong tax return. The default now comes from local calendar parts and the
  submitted instant is anchored at noon UTC on the picked day, which keeps the
  picked calendar date intact for every consumer that reads the stored
  datetime's date part. Both halves live in a tested pure helper
  (`frontend/src/lib/soldDate.js`). This is deliberately only the mark-sold
  half of the app's UTC problem; the analytics day-boundary item stays
  design-first, since changing it re-buckets every historical reading.
- A four-digit year below 100 in the sold-date helper is taken literally.
  `Date.UTC(year, …)` applies the legacy two-digit-year remapping, so
  `0050-08-20` came back as **1950** — a year the user never typed, changed
  with no error anywhere, which is precisely the class of silent substitution
  the helper exists to prevent. It now builds the date with `setUTCFullYear`
  and checks the year alongside the month and day, so a remap cannot slip past
  the rollover guard (CodeRabbit, PR #53).
- The frontend suite runs in a fixed non-UTC timezone (`America/New_York`, set
  in `vite.config.js`). CI runners default to UTC, where a local date and a UTC
  date are the same string — so the regression test for the mark-sold bug
  passed just as happily against the bug it was written to catch. The zone is
  the owner's own, west of UTC where the bug bit, and observes DST. A test
  asserts the zone is not UTC rather than trusting the config silently, in the
  spirit of the auth sweep's non-empty self-check (CodeRabbit, PR #53).

### PR #54 — Backups on the volume; download race fix

#### Fixed
- Database backups are staged on the volume that holds the database, not on
  container-local disk. `download_backup` called `tempfile.mkstemp()` with no
  directory, which on Railway resolves to the container's `/tmp` — ephemeral
  disk that is neither sized for a full copy of the database nor persistent —
  while the database itself lives on the mounted volume. `VACUUM INTO` writes
  exactly such a copy, so the app's one recovery tool got less reliable
  precisely as the data it protects grew, and it failed with a bare 500 that
  said nothing about disk. Snapshots now stage beside the database (a
  directory sized for at least one copy of it by definition), an out-of-space
  failure returns 507 and says so — SQLite reports it in a message, the OS as
  ENOSPC, and both now read the same to the person looking at the screen —
  and anything else still returns the generic 500 rather than guessing.
- An abandoned backup snapshot is reclaimed instead of sitting on the volume
  forever. The staging file is unlinked by a `BackgroundTask` once the
  response is delivered, which does not run if the client disconnects
  mid-download. That leak used to die with the container; on the volume it is
  permanent, and `storage_usage` reports only the database file and the
  uploads directory, so nothing would ever have shown it. Each backup request
  now sweeps snapshots older than an hour before staging its own, leaving one
  a concurrent request is still streaming alone.
- File downloads no longer race the browser's own fetch of the blob. All three
  authenticated downloads — database backup, inventory CSV, sold-cards CSV —
  fetch bytes and synthesize an `<a download>`, because a plain href cannot
  carry the Bearer header. Each revoked the object URL in the same tick as the
  click, but `click()` only *schedules* the download and the browser reads the
  `blob:` URL after the current task ends, so the URL could already be dead
  when it got there — a download that silently does nothing, most reliably on
  Firefox. The anchor was also never attached to the document. Both are now
  handled in one shared helper (`frontend/src/lib/download.js`), which revokes
  on a later task.
- A failed download shows what the server said. With `responseType: 'blob'`
  axios hands back the *error* body as a Blob too, so `detail` was unreadable
  and every caller fell through to a fixed string — the new "not enough disk
  space" message would have been swallowed by "Backup failed." on the way to
  the screen. The blob body is now re-read as JSON before the promise rejects,
  and all three call sites — the backup and sold-export handlers on Analytics
  and Inventory's Export CSV button — render the API's message rather than a
  fixed one (the Inventory site by way of the Claude review action on PR #54,
  which caught it still discarding the detail the others now show).
- Downloads are named by the server rather than by the browser clock. The
  backup filename was built from `new Date().toISOString()` — the UTC date,
  the same class of bug as the mark-sold default — and carried no time, so two
  snapshots taken on one day collided in the downloads folder. The
  `Content-Disposition` filename is used when present (parsed in a tested pure
  helper, RFC 5987 form included, basenamed and sanitized), falling back to the
  old name.
- The RFC 5987 filename parser drops a language tag instead of keeping it in
  the name. The ext-value grammar is `charset "'" [ language ] "'" value`, and
  the language half is optional but legal, so matching the literal prefix
  `UTF-8''` missed `UTF-8'en'caf%C3%A9.db` entirely and left `UTF-8'en'` sitting
  in the downloaded filename. It now splits on the two apostrophes and takes
  what follows, treating a value with no ext-value structure as the whole name
  rather than discarding it (CodeRabbit, PR #54).

#### Added
- `saveBlob`'s lifecycle is pinned by tests: the anchor is attached before the
  click, and the object URL survives it, being revoked only on a later task.
  That ordering *is* the download fix, and nothing tested it — a later
  simplification could have folded the revoke back into the same tick and the
  suite would have stayed green. The four DOM/URL calls it makes are stubbed
  rather than pulling in jsdom, so the suite stays pure-function and
  node-environment as CLAUDE.md requires; the tests were checked to fail
  against a same-tick revoke (CodeRabbit, PR #54).
- A test that every model the scan presets can select is priced explicitly in
  `analytics.MODEL_PRICES`. Nothing connected those two tables. The
  `_DEFAULT_PRICE` fallback is right for a model nobody chose — overcounting
  is the safe direction — but wrong for a preset: the Cost preset exists to be
  cheaper, and priced at Opus rates its whole reason for existing is invisible
  in the one report that would show it. A preset refresh that updated
  `PRESETS` alone would have mispriced every scan taken through it with no
  error anywhere.

### PR #55 — CARDLISTER_TZ design + plan (docs only)

#### Added
- Design doc + implementation plan for a configured local timezone
  (`docs/superpowers/specs/2026-08-22-local-timezone-design.md`,
  `docs/superpowers/plans/2026-08-22-local-timezone.md`). Every timestamp is
  naive UTC and every calendar-day conversion happens in UTC, so for an
  east-coast owner the day rolls over at 8pm: evening scans land on
  tomorrow's analytics bar, the mark-sold picker pre-fills tomorrow and then
  stores an instant that renders as yesterday, and a Dec-31-evening sale is
  exported into the wrong tax year. Recommends keeping storage UTC and
  converting at the edges via a `CARDLISTER_TZ` zone (default
  America/New_York), with exact-midnight values defined as date-only — the
  mark-sold and CSV-import paths have been minting UTC-midnight rows all
  along, and converting those naively would shift every historical sold
  date back a day. Revised after CodeRabbit's review of the first draft
  from a legacy-only read rule into an explicit contract: the mark-sold
  modal submits the bare picked date (pydantic already parses it to naive
  midnight — verified, no schema change), so legacy rows and new writes
  share one representation, export/import round-trips are value-exact, and
  the browser's timezone can never shift a stored date. Records three facts
  proven against the runtime: that pydantic parse, the pinned SQLAlchemy
  SQLite dialect dropping tzinfo *without converting* (a `+05:00` payload
  stores its local clock reading), and the `python:3.11-slim` image having
  no timezone database, so without a `tzdata` pip pin the deploy crashes
  while CI stays green. Docs only; awaiting approval on the no-migration
  approach and midnight contract, the default zone, and the Sheets
  date-column format change.


#### Changed (reconciled in this integration)
- The design and plan were written before PR #53 shipped and assumed mark-sold
  would submit a bare date stored at midnight. #53 anchors the picked day at
  noon UTC instead, which is timezone-safe under ordinary conversion — verified
  for America/New_York in both EDT (noon UTC → 08:00 same day) and EST
  (→ 07:00 same day), where midnight UTC renders as the *previous* day. Both
  docs now record that: the exact-midnight carve-out narrows from "the
  canonical representation of every date-only field" to "legacy rows and
  CSV-imported bare dates", which puts strictly less weight on the one rule
  with a documented misread case. Plan steps 3 and 6 become verification
  rather than change, and a new step 6b pins the noon anchor with an EDT/EST
  rendering test so a later simplification can't quietly revert it.

### PR #56 — Weekly deep review: uploads NUL 500, title parity, dead weight

#### Fixed
- A NUL byte in an `/uploads` filename (`/uploads/%00`) no longer raises a 500
  with a traceback on a public route. `.resolve()` throws "embedded null byte"
  before the containment check runs — the same 500-where-404-is-honest class
  the `/uploads/%2e` fix closed, one syscall later, and reachable by any
  unauthenticated scanner. Unresolvable names now 404 like every other
  non-file, with a test pinning `%00` in both bare and embedded positions.
- The eBay title preview now splits words on exactly the whitespace Python
  does. The mirror used `\s`, which misses the C1 separators and NEL
  (`\x85` — reachable as cp1252 `…` mojibake in a paste or CSV import) and
  wrongly includes BOM/ZWNBSP, so near the 80-character cap the preview and
  the backend could truncate at different unit boundaries — the exact
  divergence the shared fixture exists to prevent, on characters no fixture
  case contained. The mirror now uses a character class verified equal to
  Python's whitespace set across the whole BMP, the serial number is stripped
  the same way, and three new fixture cases pin NEL splitting, BOM
  preservation, and a title whose truncation is decided by code-point (not
  UTF-16) measurement. The JS parity test itself measured the cap in UTF-16
  units — it would have *failed a correct implementation* on any fixture case
  straddling the cap — and now measures in code points like the code it tests.
- A 200 from `/api/scan` whose body is truthy but not a scan response (a proxy
  or gateway answering with its own JSON or HTML) is now classified as a scan
  failure. The nullish-body fix caught empty bodies, but a shapeless truthy one
  still landed in `ready` — an inert Review button and no Retry, the same dead
  end through a third door — and in single-scan mode it silently discarded the
  staged photo. Both paths now key on the one field every real scan response
  carries (`image_path`, stored before extraction in mock mode and on failure
  alike); the batch item gets Retry and the single-scan photo stays staged.
- Analytics and its manage-data panel no longer render a raw FastAPI `detail`
  into JSX. Six catch blocks set `e.response?.data?.detail` directly into
  state, and a 422's `detail` is an array of objects — rendering it crashes
  React and white-screens the page, the exact bug class the Scanner's
  `formatApiError` helper was built for in the same week. All six now go
  through the helper; the one guarded spot (CSV import) loses its ad-hoc
  `typeof` check for the shared one.
- "Discard & Start Over" is disabled while a save is in flight. A discard
  mid-save cannot stop the save — the request is already gone — so the form
  cleared and then a "Card saved" toast contradicted the user's last action.

#### Removed
- Two dependencies nothing imports: `passlib` (auth compares plaintext env
  passwords with `hmac.compare_digest`; hashing never shipped) and
  `python-dotenv` (the README tells the user to export `.env` themselves —
  the app never loads it). Both were installed and pip-audited in every CI run
  and deploy for zero imports. Also gone: the root `package-lock.json` (an
  empty lockfile with no root `package.json`, untouched since the initial
  commit), a dead `export default` in `api.js` every consumer ignores in
  favour of named exports, and the stray `eslint-disable` comment CLAUDE.md
  itself documented as reading to nothing.

#### Tests
- The Sheets-mirror fake now slices `values().get` responses to the requested
  column span like the real API. It answered every probe at full width, so
  `test_resync_clears_residue_invisible_to_a_column_a_probe` passed even
  against the regression it is named after (verified by reintroducing the
  `A:A` probe: the suite stayed green before this change and fails after).
- `UsageEvent` joins the `db_session` hard-delete list, per the repo's own
  isolation rule — `test_user_admin`'s exact-count assertions only passed
  because no alphabetically-earlier test happened to write usage rows.
- The sold-CSV export's documented null-`sold_at` contract (excluded from a
  year filter, listed last with an empty Date Sold in the unfiltered file) is
  now pinned; previously a sort key that crashed on `None` passed the suite.
  HEAD cache headers on the SPA shell and hashed assets are pinned too —
  the header logic is shared with GET, but only GET was asserted.

#### Docs
- CLAUDE.md refreshed against a re-derivation of every invariant: the
  `(subscription)` cost rule is an `endswith` check with no leading space and
  is now test-pinned on both sides; invariant #9 (single process) now names
  the Sheets mirror lock as a second thing that silently breaks under
  `--workers`; invariant #1 notes `SOLD_EXPORT_HEADERS` is a deliberately
  separate contract from `SHEET_HEADERS`; the "two download endpoints" count
  caught up with the third.

### PR #57 — Condition dropdown of canonical grades

#### Changed
- Condition is chosen from a list of grades instead of typed. The field
  defaulted to "NM" but accepted any string, and three different paths wrote
  to it — the review form, vision extraction, and CSV import — so the same
  grade accumulated under several spellings: "NM", `"nm "` with the trailing
  space a text box invites, and "Near Mint" as the model tends to phrase it.
  Nothing downstream treated those as equal, so one physical grade fragmented
  across the inventory table, the Google Sheet's `Condition` column, and the
  sold-cards tax export, and no filter or grouping over condition could ever
  be trusted. The review form now offers `RAW / GEM-MT / NM-MT / NM / EX / VG
  / POOR`, and folds a recognized spelling to its canonical grade the moment
  the form receives it — a scanned "Near Mint" shows, and saves, as NM.
- The CSV importer folds the same way, because that is the one entry point
  that sees spellings this app did not produce: a hand-edited sheet says
  "Near Mint" where the app says "NM". `POST /api/cards` deliberately does
  **not** fold. That path stores strings byte-for-byte, which is precisely
  what the formula-injection tests in `test_export_csv.py` pin — a condition
  of `" =cmd|' /c calc'!A1"` has to reach the exporter intact for the escape
  to have something to escape.

#### Added
- `normalize_condition` (`backend/services/card_fields.py`), deliberately
  conservative in two ways that matter more than the tidying it does. It
  returns anything it does not recognize **unchanged**: "LP" and "PSA 10" are
  real grades this app has no opinion on, and `-NM` must keep its leading
  hyphen or the CSV formula escape and the export/import round-trip both stop
  being identities. And it folds only spellings that name the *same* grade —
  "Mint" and "PR" are left alone on purpose, because "Mint" sits between
  GEM-MT and NM-MT and picking one would restate what the seller is claiming
  about the card. That is a different act from correcting a typo, and the
  seller is the only one entitled to it.
- An unrecognized value is appended to the dropdown as its own option rather
  than dropped. A `<select>` whose value matches no option renders the first
  one, so without this a card stored as "PSA 10" would have shown as RAW and
  been saved that way on the next edit — the field silently rewriting itself
  on a form the user opened for an unrelated reason.
- `backend/tests/fixtures/condition_cases.json`, a case table both suites
  read — the same shape as the eBay-title parity fixture, and for the same
  reason: `frontend/src/lib/condition.js` mirrors the backend table, so drift
  on any listed case fails one suite or the other rather than diverging
  quietly. 46 backend and 51 frontend cases, including the pass-through
  guarantees above and a check that a card whose condition reads
  `constructor` is not resolved off the lookup object's prototype.

### PR #58 — eBay fee + net-proceeds estimate

#### Added
- Every price the app puts in front of a pricing decision is gross, and eBay
  takes ~13.25% + $0.30 off the top of a sale. The Comps modal and the Mark as
  Sold dialog now show the estimated net beside the figure they already
  showed: comps say $10, the seller receives $8.37. The gap is proportionally
  worst on the cheap raw cards that make up most of the inventory — the flat
  $0.30 alone is 3% of a $10 sale, and below about $0.35 the fee exceeds the
  sale entirely, which the estimate reports as a negative net rather than
  rounding it up to zero. In Mark as Sold the figure tracks the price as it is
  typed, so it lands while the seller is deciding whether to accept the number,
  not afterwards. It is labelled an estimate everywhere it renders and says
  what it leaves out: eBay charges the fee on the total the buyer pays, which
  includes shipping and the sales tax eBay collects and remits — money the
  seller never receives but is charged a percentage of — and
  promoted-listing fees are not modelled, so real proceeds run a little lower.
  An unusable price shows the same em dash the comps list uses rather than a
  plausible-looking `$0.00`.
- Both halves of eBay's fee are **tiered**, and modelling either as a flat
  number is wrong inside this inventory's ordinary range. The per-order charge
  is $0.30 at or under $10 and **$0.40 above it**, so a flat $0.30 understated
  the fee on every card over $10 — most of them; a $24.99 card nets $21.28,
  not $21.38. The percentage is 13.25% up to $7,500 and 2.35% only on the
  portion **above** that, applied per tier rather than as one rate chosen by
  the total: a $10,000 card pays 13.25% on the first $7,500 and 2.35% on the
  rest, and charging the low rate on the whole sale would understate the fee
  by ~$820 on exactly the card where the number matters most. eBay's standing
  50%-off promotion on singles at $1,000+ is deliberately not modelled — it is
  a promotion rather than the schedule, and an estimate that errs optimistic
  is worse than useless on a pricing decision. Every rate and threshold is
  printed under the figure, so a stale rate is visible the day eBay changes
  one. The flat-fee bug was caught by CodeRabbit on the PR and confirmed
  against eBay's published 2026 schedule before the math changed.
- The schedule lives in one place (`lib/fees.js`) and each field honours a
  `VITE_EBAY_FEE_*` build override, rejecting a percentage written where a
  fraction belongs — `13.25` would charge 1325% and turn every net negative.
  The production Dockerfile passes no build args, so a Railway deploy uses the
  defaults; wiring the override through the image is a backlog item.

## 2026-08-19 — Empty scan responses classified as errors (PR #51)

### Fixed
- An empty response from `/api/scan` no longer strands a batch item. PR #48
  routed a *failed* extraction to `error` — it arrives as a 200 carrying an
  `error` field — but a nullish or empty body still fell through to `ready`,
  and `ready` is the one status that renders Review while hiding Retry, with
  `reviewQueueItem` bailing on `!result`. The row therefore offered a button
  that did nothing and no way back: the same dead end #48 closed, reached
  through a different door. Empty responses are now classified as errors,
  which also keeps them out of the clear-queue "paid for" warning, since no
  extraction was billed. Found by the daily review routine against the merged
  code, and it reverses a case the #48 tests had pinned the other way — that
  assertion was about null-safety and did not follow through to what `ready`
  means downstream.

## 2026-08-19 — eBay title truncation on unit boundaries + sold-cards tax export (PR #49)

### Fixed
- An eBay title over the 80-character limit no longer says something false
  about the card. The cap was applied with `title[:80]`, which slices wherever
  the 80th character happens to land — so a `/99` serial rendered as `/9`,
  `REFRACTOR` as `REFRACTO`, and `1ST BOWMAN` as a bare `1ST`. These are not
  shortened titles; they are wrong ones, and the wrongness is invisible at the
  point it matters, because the title goes on the clipboard and straight into
  eBay's sell form. A buyer searching `/9` finds a listing for a card numbered
  to 99 that the seller does not own. `build_title` now assembles the title
  from units — one per word for free text like the set or player name, where a
  prefix is still true of the card, and one per flag even when the flag
  contains a space — and drops any unit that does not fit whole. It stops at
  the first unit that doesn't fit rather than skipping ahead to a shorter one,
  because keeping `AUTO` in place of a dropped `1ST BOWMAN` would silently
  invert a flag priority that is deliberate. A single unit longer than the cap
  still hard-slices: there is no boundary left to fall back to, and an empty
  title would be worse. The form preview is unchanged in shape — it strikes
  through the dropped tail and still counts the *full* length against the
  limit, so the over-length warning does not disappear now that the rendered
  title comes in under it.
- The card number is treated as one indivisible unit, so a card number
  containing a space (`#US 44`) can no longer be cut to `#US` — a card number
  the seller does not own, the same class of falsehood as `/9`. These are not
  hypothetical: CSV import strips only the outer whitespace of the `Card #`
  column, and vision reads the number off the card as printed. A
  whitespace-only card number now contributes nothing rather than a bare `#`,
  matching how the serial number field has always been normalized.
- A whitespace-only Parallel Color no longer injects a stray space into the
  title. Such a value is truthy, so it reached the flag list and then
  normalized to an empty unit — producing a double space before the team, or a
  trailing space with no team. The old implementation ended with
  `" ".join(title.split())`, which scrubbed exactly this; unit-boundary
  truncation removed that pass. Flags that normalize to nothing are now
  dropped, matching the guards `serial_number` and `card_number` already have.
  Pinned by a shared-fixture case, so both suites hold the two sides together.
- The title preview counts characters the way the backend does. Python's `len`
  counts Unicode code points and JavaScript's `.length` counts UTF-16 code
  units, so a single emoji in a player name measured 1 server-side and 2 in the
  preview. The preview could therefore call a title over the limit, and
  truncate it on screen, while the backend copied the whole thing to the
  clipboard — and the shared parity fixture could not catch the disagreement,
  because the two sides did not mean the same thing by "80". The mirror now
  measures and slices by code point, which also stops a hard slice from landing
  inside a surrogate pair.

### Added
- Sold cards can be exported for one tax year:
  `GET /api/cards/export-sold.csv?year=2026`, with `GET /api/cards/sold-years`
  behind a picker so the UI offers only years that actually have sales rather
  than a free-text box that can quietly produce an empty file. Omitting `year`
  exports every recorded sale instead, which the picker offers as "All years"
  (the default when nothing has sold yet); the two modes are named apart on
  disk as `cardlister-sold-2026.csv` and `cardlister-sold-all.csv`, so a year's
  file can't be mistaken for the whole history once it is off the machine. Sold rows did
  already leave the app — mixed into the full inventory dump, with no sale date
  to sort or filter on — so preparing a return meant hand-filtering the whole
  collection every year. The file is ordered by sale date ascending, the order
  a return is prepared in, and carries its own column set rather than reusing
  `SHEET_HEADERS`: that list is the Google Sheet round-trip contract and is
  append-only, so binding a second consumer to it would mean every future
  mirror column silently widening a tax report. Formula-leading cells are
  escaped exactly as in the inventory export — this file is opened in a
  spreadsheet by definition, and the player name is model-extracted from a
  photo. Gross proceeds only, stated as such in the UI, because the app records
  no purchase price yet. Sits on the Analytics manage-data panel beside the
  backup and import tools.

## 2026-08-19 — Two-agent coordination rules in CLAUDE.md (PR #50)

### Changed
- CLAUDE.md records how the two agents that commit here stay out of each
  other's way. On 2026-08-19 both an interactive session and the daily routine
  pushed fixes to the same `claude/*` branch hours apart, and both then dated
  PR #48's changelog entries independently — the same housekeeping written
  twice. The rules: `claude/*` branches belong to the scheduled routines and an
  interactive session does not push to them (branch off `main` and open a
  separate PR instead); changelog housekeeping is idempotent, so check whether
  a dated heading already exists before adding one; and check `git log` on a
  branch before pushing, since a rejected push usually means the other agent
  got there first. Also notes that a routine's uncommitted work lives in its
  own sandbox and is unreachable from a local machine, so leaving changes
  uncommitted for the owner to push does not work across the two.

## 2026-08-19 — Batch scan retry + comp spread readout (PR #48)

### Fixed
- A failed batch scan is no longer a dead end. The batch queue moves each photo
  through `queued → scanning → ready → saved`, and `error` was a one-way exit
  with no affordance attached to it — so a single transient failure in a
  twenty-card batch (a dropped connection, a 500, an Anthropic timeout) meant
  clearing the whole queue and re-staging that file by hand. Errored items now
  carry a Retry button that sends them back to `queued`, which is all the
  sequential processor needs to pick them up again; the failure message stays
  visible next to it. Only `error` items are retryable — re-queueing a `ready`
  item would quietly pay for the same extraction a second time.
- "Clear queue" asks first when it would destroy work. A `ready` item is a
  completed Opus extraction waiting to be reviewed, so discarding it throws
  away tokens already spent as well as the review effort, and the button did it
  on a single click with no confirm. The prompt counts the scanned-but-unsaved
  cards separately from the ones still waiting, because only the first group is
  unrecoverable.
- Retry now appears for the failure it exists to handle. A failed Anthropic
  extraction is not an HTTP failure — `claude_vision` returns a blank card and
  `scan.py` sends it as a 200 carrying an `error` field — so the queue resolved
  it as `ready` and offered a Review button over an empty form, with Retry
  hidden behind the one status that never renders it. Clearing the whole queue
  and re-staging the photo was the only way back, which is the dead end this
  feature set out to remove. The same fix stops the clear-queue warning
  claiming an unbilled scan was "paid for": `scan.py` records a UsageEvent only
  when the call returned usage, and it returns none on that path.

### Added
- The suggested price now says what it was drawn from. It is the **median** of
  up to ten comps, and a median cannot distinguish a set clustered at $8–$9
  from one running $4, $6, $8, $70, $90 — yet the second is exactly where the
  number is least trustworthy, because a wide spread usually means parallels,
  serial-numbered or graded copies contaminated a base card's comps. The review
  form and the inventory Comps modal now caption the price with its comp count
  and low–high range, and raise a warning naming the multiple when the top comp
  is 3× the bottom or more. Deliberately no second median is computed here: the
  server's `suggested_price` is the one the form fills in and the one "Set Price
  to $X" applies, and a locally-derived rival would eventually disagree with it
  on screen with no way to tell which was real. The modal also now says when its
  list is truncated to 8 of N, since the median is over all of them.
- Two pure helpers with unit tests (`lib/scanQueue.js`, `lib/compStats.js`) —
  the frontend suite is node-only with no jsdom, so behaviour is testable only
  through the functions a component delegates to. Both features were also
  exercised end-to-end in a real browser against the running app.

### Changed
- Both comp lists now render each price through one formatter that applies the
  same usable-price test the range above them uses, showing `—` for anything it
  rejects. Comps are an untyped `List[dict]` server-side: the review form used
  to call `c.price.toFixed(2)` directly, so a string price would have thrown
  inside render and taken the reviewed card with it, and coercing with a bare
  `Number()` traded that for a worse failure — `null` renders as a confident
  `$0.00`, an unparseable value as `$NaN`, either one sitting in a list whose
  own summary had silently excluded it.

## 2026-08-17 — Design docs: analytics owner gate, parallel pricing chain (PR #47)

### Added
- Design doc for gating the analytics user-admin routes
  (`docs/superpowers/specs/2026-08-18-analytics-owner-gate-design.md`).
  `reassign` and `delete-user-data` are guarded only by "some user is logged
  in", so either configured user can rewrite the cost ledger in either
  direction or delete the other's usage/scan/**correction** history —
  reproduced against a running app. Corrections are deliberately shared
  training data, so that delete degrades both users' scans and cannot be
  rebuilt, since the same call removes the scans it would be re-derived from.
  Recommends a `CARDLISTER_OWNER` gate over caller-scoping, because the
  panel's real purpose is merging a *ghost* username that can never be the
  caller — and because caller-scoping would still permit pushing your own
  spend onto the other user. Explicitly supersedes the July "any authenticated
  user may act" decision for these routes only. Docs only; awaiting approval.
- Design doc for running the pricing sources concurrently
  (`docs/superpowers/specs/2026-08-18-pricing-chain-parallel-design.md`). The
  chain expresses preference, not dependency, yet charges the user the sum of
  every source's timeout — and on Railway, where the scrapers 403, the common
  case is the worst case. Recommends full fan-out resolved in preference
  order, and records three corrections proven against the runtime that the
  obvious implementation gets wrong: `concurrent.futures.wait` defaults to
  ALL_COMPLETED (which would make every lookup as slow as the slowest source),
  a scalar `httpx` timeout is per-operation rather than a request budget, and a
  module-level thread pool delays container shutdown. Docs only; awaiting
  approval.

## 2026-08-17 — Sheets mirror integrity (PR #46)

### Fixed
- The Google Sheet mirror no longer drifts permanently, and the button offered
  to repair it no longer makes things worse. Three defects compounded: pressing
  "resync" nulled every card's stored row index and re-synced, which took the
  **append** branch and added a complete second copy of the inventory on every
  press; `delete_card` was the only mutating card route that never touched the
  mirror, so a deleted card's row survived in the sheet forever; and CSV import
  skips the mirror by design but said nothing, so an importer saw an empty sheet
  and reached for the duplicating resync. Resync is now a clear-then-rewrite of
  the Inventory tab — running it twice produces the same sheet, which is the
  property a repair tool needs and the old one lacked, and it uses three API
  calls rather than one per card. Delete blanks its row in place rather than
  removing it, because removing a row shifts every row below it and silently
  invalidates every later card's stored index. Import now says plainly that its
  cards need a resync to appear.
- Concurrency: every Sheet write is serialized behind a module-level lock (the
  app runs one worker by invariant). A save that read its row index before a
  rewrite reassigned it now re-reads inside the lock and lands on the new row
  instead of overwriting a different card's data — and is not dropped. The
  delete-path blank checks row *ownership* under the same lock rather than
  trusting the row number, so a resync landing between the delete and the
  background task can't erase a live card's row.
- The resync endpoint reports failures instead of swallowing them, and
  distinguishes the two partial-failure orders because they need opposite
  recovery: cleared-but-not-rewritten nulls every index (the sheet is empty, so
  each card must re-append), while rewritten-but-not-recorded deliberately does
  not (the sheet is correct and positions are deterministic — nulling there
  would make every card append a second copy, recreating the exact duplication
  this fixes).

### Added
- A "Resync sheet" button on the Analytics manage-data panel, with a
  confirm dialog and copy stating that the tab is rewritten from the database
  and anything typed directly into the sheet is discarded. The endpoint
  previously had no UI at all, so the only way to mirror imported cards was a
  manual API call — and the failure reason is now surfaced rather than silent.

## 2026-08-17 — Formula escaping, symlink containment, HEAD support, stat tiles (PR #44)

### Added
- Design doc + implementation plan for Sheets mirror integrity
  (`docs/superpowers/specs/2026-08-17-sheets-mirror-integrity-design.md`,
  `docs/superpowers/plans/2026-08-17-sheets-mirror-integrity.md`). Three defects
  compound today: `delete_card` is the only mutating card route that never
  touches the mirror, so deleted cards keep a row forever; `resync_all` clears
  every `sheets_row` and then appends, so the one-click "full resync" adds a
  complete second copy of the inventory each run — and it is the button the UI
  offers precisely when the sheet looks wrong; and CSV import skips the mirror
  entirely, which funnels an importer straight into that resync. The root cause
  is that `sheets_row` is an absolute row index, so no operation in the current
  model can remove a row without invalidating every later card's index. The
  recommendation is clear-then-rewrite for the repair path (making it idempotent
  and self-healing for existing damage) plus blank-in-place on delete. Docs only;
  implementation awaits owner approval, since the rewrite is a destructive write
  to a user-visible sheet.

### Security
- `/uploads/{filename}` proves the resolved path is inside the uploads volume
  before serving it. `Path(filename).name` drops every directory component, so
  traversal was already blocked — but `.name` says nothing about where the
  resolved path *lands*, and a name that happened to be a symlink pointing out
  of the volume was served with a 200 and its contents. Reproduced before
  fixing, and the new test fails on revert. Both sides are now resolved and
  containment re-checked. Note this does *not* clear the CodeQL
  `py/path-injection` alerts on the route — the query models neither `.name` nor
  `is_relative_to()` as a barrier, so the reported count actually rose from one
  to two as the extra check added another path expression. Those alerts are a
  modelling limitation rather than a defect and need dismissing as false
  positives; the escape they were chased down to find was real, and is fixed.
- CSV export escapes formulas hidden behind leading whitespace. The escape
  tested `value.lstrip("'").startswith(("=", "+", "-", "@"))`, which strips
  only apostrophes — so a cell beginning with a tab, CR, LF, space, or NUL had
  its formula character one byte out of reach and was written unescaped. Excel
  and Sheets discard exactly those leading characters before deciding whether a
  cell is a formula, so a `"\t=HYPERLINK(…)"` saved in Notes evaluated on the
  owner's machine when the exported inventory was opened. Nothing on the write
  path normalizes strings, so such a value reached the CSV verbatim from
  `POST /api/cards`. The check now peels the whole noise set (apostrophes plus
  whitespace and control characters) before testing, in any mix or repetition,
  and the import-side unescape stays symmetric so every value still
  round-trips. Found by the Monday full-app security pass.

### Fixed
- `/uploads/%2e` answers 404 instead of 500. `Path(".").name` and
  `Path("..").name` are both `""`, so an encoded dot segment resolved to the
  uploads *directory*, satisfied the `exists()` check, and then raised inside
  `FileResponse` ("is not a file") — an unhandled 500 with a traceback on a
  public, unauthenticated route where 404 is the honest answer. The check is
  now `is_file()`, which rejects the resolved uploads directory. No information was
  disclosed (the generic 500 body carries no path), but the tracebacks were
  noise in the logs that a real error would have to compete with.
- `/api/health` and `/uploads/{filename}` answer HEAD requests. FastAPI's
  `@app.get` registers GET alone (unlike Starlette's bare `Route`, which adds
  HEAD for free), so a HEAD probe missed both routes, fell through to the static
  mount, and — `api` and `uploads` being non-SPA roots — came back 404. Uptime
  monitors default to HEAD, which meant a healthy deploy and a database-down
  deploy both reported 404: exactly the distinction the deep health check's 503
  exists to make. Both are now registered for HEAD as well, kept out of the
  OpenAPI schema (HEAD is implied by GET there, and the auth sweep skips it).
  Registered as a second route rather than `methods=["GET", "HEAD"]` because
  FastAPI derives an operation id from a route's first method, so one
  two-method route emits a duplicate id and warns.

### Changed
- Inventory stat tiles describe whatever the table below is showing. The tiles
  were computed from the full card list while the table showed the filtered
  set, so narrowing to "sold" or searching a player left five tiles describing
  the whole collection — there was no way to ask "what are my Bowman autos
  worth". Filtered values now carry an "of N overall" caption so a narrowed
  tile can't be mistaken for a data bug, and a badge by the heading names how
  many rows the totals cover (or says plainly that nothing matched, so a $0
  tile reads as an empty filter rather than lost data).
- Monday dependency pass clears a new high-severity advisory:
  GHSA-2v37-7h3g-55p8 (nanoid below 3.3.18 can loop indefinitely in a custom
  generator when size is zero), which reaches the frontend transitively via
  postcss — so the fix is a lockfile bump rather than a dependency change.
  Taken with the rest of the semver-compatible drift (axios 1.18.1 → 1.19.0,
  vite 8.1.5 → 8.2.1, `@vitejs/plugin-react` 6.0.4 → 6.0.5, postcss
  8.5.23 → 8.5.26), so `package.json` is untouched and only the lockfile moves.
  `npm audit` is back to zero. Tailwind 3.4 → 4.x remains the only outstanding
  drift and stays deferred — it is a major with a config/PostCSS pipeline
  change. `pip-audit` is unchanged: ecdsa PYSEC-2026-1325 still has no fixed
  release upstream and the app signs HS256, so its ECDSA paths stay unused.
- CI no longer fails open on a missing test suite. The backend-test and
  frontend-test steps were wrapped in `if [ -f … ]` / `if [ -d … ]` guards
  added so CI would pass on refs predating those suites; both conditions have
  been permanently true for months, and the frontend guard keyed on one
  specific test *filename* — renaming `ebayTitle.test.js` would have stopped
  the entire frontend suite from running while the job stayed green. Both steps
  now run unconditionally.

## 2026-08-16 — Weekly deep review: caching, event loop, quantity crash (PR #43)

### Fixed
- The SPA shell now ships `Cache-Control: no-cache` and Vite's content-hashed
  bundles under `/assets/` get the same year-long immutable header as uploads.
  Neither carried any cache header, so browsers applied heuristic freshness to
  the shell — a cached copy could outlive its bundles across a deploy, request
  a hashed bundle that no longer exists, hit the (deliberate) `/assets` 404,
  and white-screen. The shell revalidating every load (a cheap 304 via the
  existing ETag) closes the very failure PR #40's fallback work reasoned
  about, and immutable bundles drop a 304 round-trip per file per navigation.
- Clearing the Quantity field no longer white-screens the Scanner on save.
  An emptied number input stored `null`, the server 422'd it (`quantity` is
  non-Optional, `ge=1`), and the FastAPI validation *array* in `detail` was
  rendered directly into JSX — React throws on object children, losing the
  reviewed form. Quantity now coerces to 1 at submit, and a shared
  `lib/apiError.js` formatter normalizes every API error to a string across
  Scanner and Inventory.
- The call-up poller no longer blocks the event loop. Each cycle did sync
  network I/O (MLB fetch + digest email, up to ~35s of timeouts) directly on
  the loop of the single worker, stalling every request — including saves and
  scans — while it ran. The cycle now runs via `run_in_threadpool`, same as
  the vision call.

### Changed
- The public eBay account-deletion endpoint caps its request body at 64 KB
  (413 above it). Real notices are ~1 KB; the route is unauthenticated, so an
  arbitrary-size POST could balloon memory on the lone worker.
- New tests pin previously unguarded invariants: `_cost()`'s subscription-$0
  rule and pricing table (CLAUDE.md invariant #2 had no test), the cheatsheet's
  30-rule cap with *distinct* corrections (the cap is what keeps per-scan
  prompt tokens at a plateau), the compliance log sanitization (`repr()` + cap
  could be "simplified" away silently), and HEAD requests in the SPA
  page-load contract.

## 2026-08-15 — Batch front/back pairing design (PR #42)

### Added
- Design doc + implementation plan for batch scan front/back auto-pairing
  (`docs/superpowers/specs/2026-08-15-batch-front-back-pairing-design.md`,
  `docs/superpowers/plans/2026-08-15-batch-front-back-pairing.md`). Batch mode
  scans every image as its own card, so a camera roll alternating front/back
  yields double the rows, double the Opus spend, and none of the back-side
  detail the extraction prompt itself says to read (year, full card number,
  serial). The backend and API client already support paired scans — the
  recommended Phase 1 is frontend-only: heuristic adjacent pairing plus a
  mandatory review step before any tokens are spent. Docs only; implementation
  awaits owner approval of the approach.

## 2026-08-14 — SPA deep links, copy-counting stats, upload caching (PR #40)

### Fixed
- Hard loads of client routes no longer 404. `StaticFiles(html=True)` only
  serves `index.html` for *directory* requests, so the router only ever ran
  when navigating from `/` — refreshing the page on /inventory or /analytics,
  or opening a bookmark to one, returned a bare `{"detail":"Not Found"}`. A
  `SpaStaticFiles` subclass now falls back to the app shell for unmatched page
  loads, while `api/`, `uploads/`, and `assets/` paths keep their real 404 so a
  mistyped endpoint or a stale bundle can't come back as 200 + HTML. This also
  unblocks the backlogged card-permalink item, which assumed deep links loaded.
- Inventory stat tiles count copies instead of rows. `quantity` is how many
  physical copies a row stands for, and the save-time "increase count" flow
  makes multi-copy rows routinely — so Total Cards undercounted the collection
  and Est. Active Value valued a qty-3 row at a single listed price. Counts and
  active value are now quantity-weighted, with a "N rows" caption on Total
  Cards whenever the two differ. Revenue stays per-row on purpose: `sold_price`
  is what a sale actually brought in, and multiplying it would invent money —
  but it is now restricted to sold rows, since the CSV importer fills
  `sold_price` from the "Sale Price" column whatever the row's status, so an
  imported active row carrying one used to be counted as revenue for a card
  still on the shelf. The math moved into `lib/inventoryStats.js` so it's
  unit-tested.

### Changed
- Served uploads carry `Cache-Control: public, max-age=31536000, immutable`.
  Stored names are uuid-hex, so the bytes behind a URL never change, but no
  cache header meant every inventory render refetched every full-size photo.

## 2026-08-14 — Daily-routine gate fixes (PR #39)

### Changed
- The daily routine's build gate is now executable: it required a green
  frontend build but supplied only the backend test command, so a run could
  satisfy every written instruction and never build the frontend. Now spells
  out `cd frontend && npm ci && npm test && npm run build` (the `npm ci`
  matters — a fresh checkout has no `node_modules`) and notes that both gates
  apply even for a backend-only diff, since the eBay title fixture is read by
  both suites.
- Corrected the changelog rationale in the same doc: it claimed bad
  implementations never reach main's changelog, which is false — a merged bug
  is described there as confidently as a working feature. It is evidence of
  shipped *scope*; correctness comes from the health check, the test suites,
  and review findings.

## 2026-08-14 — All three scheduled routines documented (PR #38)

### Changed
- `docs/notes/daily-routine-prompt.md` now documents all three scheduled
  routines instead of one: the daily build session (updated for CLAUDE.md,
  `.coderabbit.yaml`, branch-freshness before building, and all three
  reviewers), a new Sunday deep review that hunts what diff-scoped PR review
  structurally can't see, and a new Sunday design session that turns parked
  "large / design first" backlog items into approved specs and plans. The
  routines live in the cloud and aren't readable from a local session, so this
  file is their only record — it now says so, and warns against renaming the
  file whose path is hard-coded inside the daily prompt.

## 2026-08-14 — CodeRabbit config (PR #37)

### Added
- `.coderabbit.yaml`: CodeRabbit review config whose path instructions carry
  this repo's real invariants (auth sweep, `_COLUMN_MIGRATIONS`, append-only
  `SHEET_HEADERS`, literal routes above `/{card_id}`, the `" (subscription)"`
  cost suffix, the Scanner `pricingSeq` guard) so automated review catches what
  fails silently in production rather than generic lint. Two fixes to the
  starting template: the lockfile filter was `!**/*.lock`, which matches nothing
  here (the lockfiles are `package-lock.json`), and the frontend glob covered
  `ts`/`tsx`, which don't exist in this repo.

## 2026-08-12 — Integration of PRs #29–#32 (PR #33)

### Added
- Unmark-sold undo: `POST /api/cards/{id}/unmark-sold` restores a mis-clicked
  sold card to Active and clears the sale price/date (409 if the card isn't
  sold), with an "Unmark Sold" button on sold rows behind a confirm dialog.
  Previously mark-sold was irreversible in the UI — fixing a misclick needed a
  manual PATCH, and the phantom sale polluted revenue analytics until then.
  (PR #29)
- Row-level "Copy Text" button on non-sold inventory rows: copies the eBay
  listing text to the clipboard quietly (transient "Copied ✓" on the button,
  prompt fallback when the clipboard API is blocked). Previously the only way
  to get listing text was the Open eBay flow, which also opens a tab and fires
  an alert. (PR #29)
- Parallel, Serial #, and Refractor columns in the CSV export and the Google
  Sheets mirror (appended after 1st Bowman so existing sheet columns keep
  their positions). A Gold /50 refractor is no longer indistinguishable from
  the base card in the export; the CSV importer already read these columns by
  header name, so the export ↔ import round-trip now preserves all three.
  (PR #31)
- Storage usage tiles on the Analytics manage-data panel: database file size,
  photo count, and photo bytes on the server (`GET /api/analytics/storage`),
  refreshed after a CSV import or orphan cleanup. Railway volume pressure was
  previously invisible until a deploy failed or the volume filled — now it sits
  next to the cleanup tools that relieve it. (PR #32)

### Security
- Scan uploads are validated by content, not filename: the first bytes must
  carry a JPEG/PNG/WebP/PDF magic signature or the request is rejected with
  415 before anything is written, and the stored suffix now comes from the
  sniffed content instead of the client-supplied extension. Previously only
  the extension was checked (with unknown extensions coerced to `.jpg`), so
  arbitrary non-image content — e.g. an HTML payload named `photo.jpg` —
  was stored and re-served from `/uploads` in the app's origin. (PR #30)
- Router-wide auth sweep test: a parametrized test asserts every `/api`
  route returns 401 without a token — except login, the health check, and
  the deliberately public `/api/ebay-compliance/*` routes (eBay's servers
  and browser-facing landing pages) — so a future router (or route) that
  forgets `Depends(require_auth)` fails CI automatically. Collected from
  the OpenAPI schema with a self-check that the sweep is non-empty. (PR #30)
- CSV export escapes formula-leading cells (`=`, `+`, `-`, `@` get a leading
  apostrophe) so a crafted value — e.g. a Notes cell imported from a
  third-party CSV — can't execute as a formula when the export is opened in
  Excel or Google Sheets. The importer strips the escape on the way back in,
  so exported values round-trip unchanged. The Sheets mirror needs no change
  (rows are written with `valueInputOption=RAW`). (PR #31)

### Fixed
- Scanner pricing lookups can no longer land on the wrong card: switching
  batch-review items (or saving/discarding) while a comps lookup was in flight
  let the stale response overwrite the newer card's comps, pricing note, and
  suggested price. Lookups now carry a monotonic id and only the latest may
  write state; save/discard/new-scan invalidate anything in flight. (PR #32)

## 2026-08-12 — CLAUDE.md and README refresh (PR #36)

### Added
- `CLAUDE.md`: architecture guide for AI coding agents — the scan billing ladder,
  pricing chain (and why the primary source returns active rather than sold
  listings), the corrections learning loop, and an "invariants that break
  silently" list covering the append-only `SHEET_HEADERS` contract, the
  `" (subscription)"` cost suffix, `_COLUMN_MIGRATIONS`, route ordering, the
  three-file eBay title change, and the single-worker/`$PORT` deploy constraints.

### Changed
- README refreshed against the code: React 19 + React Router 8 (it still said
  React 18), venv at the repo root rather than `backend/`, a Tests section
  (there was none), the `_COLUMN_MIGRATIONS` schema workflow in place of the
  "delete the DB or hand-write ALTER TABLE" advice, the four env vars missing
  from the table (`EBAY_VERIFICATION_TOKEN`, `EBAY_DELETION_ENDPOINT_URL`,
  `SMTP_HOST`/`SMTP_PORT`, `DISABLE_CALLUP_POLLER`), and a project layout that
  had drifted by five routers, seven services, and the whole `lib/` and `docs/`
  trees.

## 2026-08-10 — eBay portal prerequisites (PR #34)

### Added
- Public eBay compliance router (`/api/ebay-compliance/*`, no auth — eBay's
  servers call these): marketplace account-deletion notification endpoint
  (challenge handshake per eBay's sha256(challengeCode + verificationToken +
  endpointUrl) formula, fast-ack for deletion notices, config via
  `EBAY_VERIFICATION_TOKEN` + `EBAY_DELETION_ENDPOINT_URL`), plus OAuth
  accepted/declined landing pages and a privacy-policy page so the RuName
  form can be filled once. Unlocks the production keyset without claiming
  the data-storage exemption, so nothing in the developer portal has to
  change when seller-OAuth draft listings land.

## 2026-08-02 — React Router v8 + React 19 (PR #28)

### Changed
- React Router v6.30 → v8.3 and React 18.3 → 19.2 (v8's peer requirement).
  Clears all three Dependabot advisories against the v6 line (open-redirect
  XSS, backslash-path bypass CVE-2025-68470, SSR deserializeErrors injection —
  none exploitable here, but unfixable on v6) and skips the 7.12–8.2 range,
  which carries an unpatched RSC-CSRF advisory. `npm audit` is now clean.
  Package moves from `react-router-dom` to `react-router` per the v7+ layout;
  no API changes were needed (BrowserRouter/Routes/Route/Navigate/NavLink/
  useNavigate/Link all unchanged). Verified: 24 frontend tests, build, and a
  live click-through of login → scan → inventory → analytics → logout.

## 2026-08-02 — Post-#24 follow-ups (PR #25)

### Fixed
- CSV import enforces sold-row consistency: a SOLD row without a Sale Price
  greater than 0 is skipped with a reason (the import path bypasses the
  mark-sold validators, so a bad row would corrupt revenue analytics), and a
  SOLD row missing Date Sold gets today's date with a warning, mirroring
  mark-sold's default.
- Orphaned-photo cleanup warns before bulk deletion: when the orphan set is
  half or more of all uploads (and at least 10 files), the confirm dialog
  explains the likely cause — cards that lost their photo links, e.g. after a
  CSV restore (the CSV carries no photo columns) — instead of presenting the
  files as safe-to-delete junk. The orphans preview endpoint now reports
  `total_files` to support this.
- Orphan grace window computed with `time.time()` instead of a naive
  `utcnow().timestamp()`, which shrank the 48h window on non-UTC hosts.
- Prospect-news article links get the same scheme guard as listing links:
  a non-http(s) `link` from an external RSS feed renders as plain text
  instead of a clickable href.

### Changed
- The CI dependency-audit job no longer exits non-zero when advisories are
  found — it emits a warning annotation and a step summary instead. The job
  never blocked merges, so its red X only taught people to ignore red.

## 2026-08-02 — One-click integration of PRs #18–#23 (PR #24)

### Added
- Bulk CSV inventory import: `POST /api/cards/import.csv` plus an "Import
  inventory CSV" button on the Analytics manage-data panel. Accepts the CSV
  export's column layout with columns matched by header name (order-independent,
  unknown columns ignored, optional Parallel / Serial # / Refractor columns
  picked up), skips bad rows individually with per-row reasons instead of
  aborting the file, and enforces the same https-only rule for eBay URLs as the
  attach-listing endpoint. Round-trips the export, so backup-restore and bulk
  hand-edited sheets both work.
- Orphaned photo cleanup: scanned photos previously stayed on the Railway
  volume forever even when the card was never saved or later deleted.
  `GET /api/analytics/uploads/orphans` previews reclaimable files (not
  referenced by any card, older than a 48-hour grace window so unsaved
  batch-queue scans survive); `POST /api/analytics/uploads/cleanup` deletes
  them behind a count-and-size confirm on the manage-data panel.
- Sortable inventory columns: every data column header (player, year, brand,
  set, card #, condition, qty, listed price, status, added) is clickable to
  sort ascending/descending, with blanks always sorted last and card numbers
  compared numerically ("BCP-9" before "BCP-100").
- Inventory search now matches across player, team, brand, set, card number,
  parallel color, notes, and year — previously player name only.
- Deep health endpoint: `GET /api/health` now pings the database, reports the
  deployed revision (Railway commit SHA), and exposes a call-up poller
  heartbeat (enabled / interval / last cycle / stale after 3 missed
  intervals). Returns 503 when the database is unreachable so plain HTTP
  uptime monitors can alert on status code alone. README gains a placeholder
  for recording the production URL so tooling can actually ping prod.
- Non-blocking `audit` job in CI: `pip-audit` over the backend requirements and
  `npm audit` (high and above) over the frontend on every PR and push to main,
  so new dependency advisories surface between Monday deep passes — the repo
  has no Dependabot. The job never blocks a merge; npm's bar is set to high
  because the two known moderate react-router advisories are already tracked
  in the backlog pending the v7 migration. On its first run the job surfaced
  ecdsa PYSEC-2026-1325 (transitive via python-jose, no fix released, ECDSA
  unused here — JWTs are HS256); that advisory is pinned as ignored with a
  backlog entry to revisit, so the job's red state stays reserved for
  genuinely new findings.

### Changed
- `ebay_listing_url` is now validated server-side: the attach-listing endpoint
  rejects anything that doesn't start with `https://` (hardening item from the
  2026-07-27 security review — the value is rendered as a clickable link). The
  Attach eBay modal validates the prefix client-side too and surfaces server
  rejections instead of failing silently (auto-review follow-up).
- Card photos are downscaled in the browser before scan upload: at most
  2000px on the long side (matching the largest server-side vision preset, so
  no scan mode loses input quality), JPEG-encoded at q0.85 with EXIF rotation
  baked in. Cuts multi-MB phone photos to a few hundred KB — faster mobile
  scans and far less Railway volume growth — with automatic fallback to the
  original file if in-browser decoding fails. PDFs pass through untouched.

### Security
- `/api/scan` uploads are now streamed to disk in 1 MB chunks with a 25 MB
  per-file cap (front and back images independently) — previously the whole
  file was read into memory with no size limit, so a single oversized upload
  could exhaust memory or fill the Railway volume. Over-cap requests get a
  `413` with a clean error message and leave no partial file behind.
  (Hardening note from the 2026-08-01 code review.)
- Stored-XSS path via listing links closed end-to-end (PR #22): `ebay_listing_url`
  is validated server-side (https-only, unified with the PR #18 rule), the
  Inventory table's link render carries a defensive scheme guard, and the Attach
  eBay modal validates client-side before submitting.

### Fixed
- `PATCH /api/cards/{id}` no longer accepts `status` — sold/active can only
  change through the mark-sold flow, so a stray PATCH can't silently flip a
  card's state (PR #22).
- Data-integrity guards: `/mark-sold` rejects `sold_price <= 0`,
  `listed_price` rejects negative values, and `quantity` must be ≥ 1 on both
  create and patch (a negative
  quantity could render "Quantity available: -3" in an eBay description and
  suppress call-up alerts by dragging the summed inventory match count to
  zero). Quantity input in the card form now enforces `min=1` too (PR #22 +
  auto-review follow-up).
- Call-up inventory matches exclude sold cards (PR #22).
- CSV import rejects negative Listed/Sale Price values (row skipped with a
  reason, like other malformed values) — the import path builds rows directly
  against the model, so it bypassed the ge=0 guards above (auto-review finding
  on this PR).

## 2026-07-28 — Lightbox, title parity tests, dependency refresh (PR #17)

### Added
- Inventory image lightbox: clicking a card's thumbnail opens a full-size
  overlay showing the front (and back, when one was scanned); Esc or a click
  anywhere closes it.
- Frontend test runner (vitest) with a shared parity table: 12 cases in
  `backend/tests/fixtures/ebay_title_cases.json` are asserted by both the
  backend (`build_title`) and the client-side title mirror (`ebayTitle.js`),
  so the live preview can no longer silently drift from the real listing
  title. CI now runs the frontend unit tests before the build.

### Changed
- Dependency refresh (Monday deep pass): all backend pins brought current —
  notably python-jose 3.5.0 and python-multipart 0.0.32 (both clear known
  CVEs), fastapi 0.140, pydantic 2.13, SQLAlchemy 2.0.51, httpx 0.28,
  Pillow 12, anthropic 0.120, pytest 9 — plus frontend vite 8 / vitest 4 /
  plugin-react 6 (clears the esbuild/vite/vitest dev-server advisories) and
  in-range minors. Remaining: two moderate react-router advisories whose only
  fix is the v7 major, deferred to the backlog (no SSR, no user-controlled
  link targets here).

## 2026-07-26 — Title preview & database backup (PR #16)

### Added
- Live eBay title preview in the card form: shows the exact title the listing
  flow will generate (client-side mirror of `build_title`) with an 80-character
  counter; anything past the cap renders struck-through in red so truncation is
  visible before saving instead of after pasting into eBay.
- One-click database backup: `GET /api/analytics/backup.db` streams a
  consistent point-in-time SQLite snapshot (`VACUUM INTO`, safe against
  concurrent writes), with a "Download database backup" button on the
  Analytics manage-data panel. Inventory, scans, and usage history all live in
  this one file on a single Railway volume, which previously had no backup
  story at all.

### Fixed
- A whitespace-only serial number no longer renders a bare `/` flag in the
  eBay title (backend now matches the preview mirror's behavior).

## 2026-07-26 — 1st Bowman follow-ups (PR #15)

### Added
- Call-up ticker shows a "1st Bowman ×N" badge when a call-up matches owned
  1st Bowman cards (`first_bowman_count` now included in `/api/news`), matching
  the email digest's behavior.

### Fixed
- eBay title flag order: `RC` now renders ahead of `1ST BOWMAN` in
  `build_title`, so the rookie flag is less likely to be dropped by the
  80-character title truncation.

## 2026-07-26 — Duplicate detection, CSV export, comps, PWA, billing fallback (PR #14)

### Added
- Duplicate detection on save: the Scanner checks for an owned (non-sold) copy of
  the same card and offers "increase your card count" instead of creating a new
  row. Identity matching is case-insensitive; parallel color, serial number, and
  print flags must match exactly so a Gold /50 never merges with a base card.
  (`POST /api/cards/check-duplicate`)
- Inventory CSV export (`GET /api/cards/export.csv` + button), same column
  layout as the Google Sheets mirror.
- Per-row "Comps" modal in Inventory: re-runs the pricing chain for a card,
  shows the delta against the listed price, and offers a one-click reprice.
- Mobile camera capture ("Take a Photo" button) and a PWA manifest + icon so
  the app installs to a phone home screen.
- `docs/BACKLOG.md` idea ledger, production/monetization strategy notes, and
  the daily-routine prompt doc.
- Subscription-billed scan fallback: when `ANTHROPIC_API_KEY` is missing or out
  of credits, scans run headlessly through the Claude Code CLI
  (`CLAUDE_CODE_OAUTH_TOKEN`) and bill the owner's Claude plan instead of
  failing; analytics prices those scans at $0. The Docker image now bundles the
  Claude Code CLI.
- Credits-exhausted alerts: out-of-credit API errors page the owner by email
  (existing mailer) and phone push (ntfy topic via `NTFY_TOPIC`), throttled to
  one alert per 6h. `POST /api/analytics/alerts/test` fires both channels on
  demand (no throttle) to verify the wiring.

### Changed
- GitHub Actions workflows (@claude assistant + auto-review) authenticate with
  `CLAUDE_CODE_OAUTH_TOKEN` (owner's Claude subscription) instead of
  `ANTHROPIC_API_KEY` pay-as-you-go credits.

## 2026-07-12 — 1st Bowman flag (PR #13)

### Added
- `is_first_bowman` flag end-to-end: vision extraction (printed "1st" logo
  only, no guessing), card form checkbox, inventory "1st" badge, `1ST BOWMAN`
  eBay title token, trailing Sheets column, and learning-system identity field.
- Call-up digest emails call out and sort first any inventory matches that are
  1st Bowman cards (`first_bowman_count` on call-up events).

### Fixed
- Sheets range end column derived from the header count so future column adds
  can't silently truncate rows.

## 2026-07-10 — News UI & email provider (PRs #11, #12)

### Added
- Newspaper-clipping styled news section below the scan area, with article
  summaries, recolored to the app's ink+emerald theme.

### Fixed
- Call-up alert emails switched to SendGrid's HTTP API (Railway blocks
  outbound SMTP); SMTP kept as the local-dev fallback.

## 2026-07-10 — Call-up alerts, prospect news, user-data admin (PR #10)

### Added
- MLB call-up detection: transaction polling, inventory matching, and an
  in-process poll scheduler (`CALLUP_POLL_MINUTES`, default 15).
- Alert email digest (never-raise mailer); digests lead with inventory matches
  and retry unsent events within a 48-hour cutoff.
- Prospect news RSS aggregation (`/api/news`) and a call-up ticker on the scan
  page.
- Analytics "Manage data" panel: merge or delete usernames, with the
  merge-target dropdown limited to configured users.

### Security
- Ghost tokens (JWTs for users no longer configured) are rejected.

## 2026-07-10 — Upload hardening & CI (PRs #8, #9)

### Added
- GitHub Actions: pytest + frontend-build CI, Claude auto-review, and the
  @claude assistant workflow.

### Security
- Served uploads restricted to safe inline image types (everything else forced
  to download with nosniff); API errors no longer leak exception text.

## 2026-07-10 — Feedback features (PR #7)

### Added
- Quantity column with an idempotent `ensure_columns` migration helper.
- Optional back-of-card image in scans (front + back in one vision call).
- Refractor-focused extraction prompt and per-preset image resolution
  (`VISION_MAX_IMAGE_PX`, `0` disables downsampling).
- Learning from corrections: cheat-sheet prompt injection plus exact-card
  identity overrides.
- Sequential batch-scan queue (multi-file staging, one scan in flight,
  auto-advance through review).
- pytest test infrastructure (`backend/tests`).

## 2026-06-22 — Improvements batch (PR #6)

### Added
- eBay API as the primary comp source when credentials are configured
  (scrapers 130point → Mavin → eBay kept as fallback).
- Multi-user auth (`CARDLISTER_USERS`) with per-user cost tracking, and the
  Analytics page (usage, tokens, estimated cost by user/model/day).
- Scan-mode presets (Cost / Balanced / Accuracy) controlling model, thinking
  effort, and image resolution.
- Production secret checks: refuses to boot with default password/JWT secret.

## 2026-06-14 — Initial release

### Added
- Core loop: photo upload → Claude vision extraction → sold-comp pricing
  (130point → Mavin → eBay scrape) → editable form → clipboard listing text +
  eBay sell page.
- SQLite inventory with mark-sold and eBay-listing attachment, Google Sheets
  write-only mirror, JWT auth, mock mode without API keys.
- Single-container Docker deploy on Railway (fixed port binding 2026-06-20).
