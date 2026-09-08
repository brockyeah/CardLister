# CardLister Backlog

Persistent idea ledger, maintained by the daily review routine. One line per idea;
move items to **Shipped** (with date) instead of deleting so runs don't re-propose them.

## Now / next

- [ ] A total alert-delivery failure buys six hours of silence (2026-09-08
      review): both `notify_credits_exhausted` and
      `notify_callup_alerts_undelivered` in `services/billing_alerts.py` stamp
      their throttle clock (`_last_alert_at = now`) **before** attempting
      delivery, then return whether either channel worked. So when *both*
      channels fail — no `ALERT_EMAILS`, a revoked SendGrid key, ntfy
      unreachable — the outage is recorded as alerted and suppressed for six
      hours with nothing having been delivered. That is the exact failure shape
      PR #64 removed from the call-up poller one layer down: the poller now
      escalates undelivered alerts to `billing_alerts`, and `billing_alerts`
      then drops the escalation on the floor if its own channels are also down,
      which is precisely the case where both are most likely to be down at
      once. Fix: stamp the clock only when at least one channel delivered, so a
      failed attempt is retried on the next scan or poll cycle; keep the stamp
      unconditional for a *partial* success (one channel is enough). Worth
      deciding at the same time whether a shorter retry interval should apply
      to the all-failed case so a transient provider blip does not wait a full
      cycle. Note also that both clocks are module-level process state, so a
      Railway deploy resets them and an ongoing outage re-alerts — the
      opposite error, and the harmless one (quick win; implement directly;
      inline — `services/billing_alerts.py` plus tests that patch both
      channels to fail and assert the second call still attempts delivery)
- [ ] The ntfy push is an unauthenticated public channel carrying raw provider
      error text (2026-09-08 review): `_push_via_ntfy` posts to
      `https://ntfy.sh/<NTFY_TOPIC>` with no credential, and an ntfy topic is
      public by construction — the topic name *is* the secret, and anyone who
      knows or guesses it can read every alert **and publish to it**, so a
      forged "credits exhausted" push is as easy as reading a real one. The
      body is not nothing: `notify_credits_exhausted` interpolates the raw
      Anthropic API error string, which is provider text this app does not
      control the contents of. Low severity — this is a two-user internal tool
      and no card or price data goes over it — but the cost of closing it is
      one header. Fix: support an optional `NTFY_TOKEN` sent as
      `Authorization: Bearer`, document in `.env.example` that the topic name
      is a shared secret and should be long and random, and truncate the
      interpolated provider error to a bounded prefix (quick win; implement
      directly; inline — `services/billing_alerts.py`, `.env.example`)
- [ ] There is no migration path for an **index** on an existing table
      (2026-09-08 review, found while moving `find_exact_match`'s match into
      SQL): `_COLUMN_MIGRATIONS` closes exactly one hole in the no-Alembic
      setup — a new *column* — and `init_db` otherwise relies on
      `create_all`, which skips a table that already exists and therefore never
      creates an index added to a model later. So an `Index(...)` on
      `Correction` or `Card` would exist on a fresh DB and on every test run,
      and silently not exist on the deployed one: the same failure shape as
      invariant #4, in the one direction that invariant's wording ("New
      *tables* need nothing") reads as already covered. It is not hypothetical
      any more: `find_exact_match` now filters `year` + `lower(trim(brand))` +
      `lower(trim(card_number))` in SQL on **every scan**, against a
      `corrections` table that grows forever and has an index on none of those
      three. Measured at 401 rows it is 2.5 ms, so this is a ceiling to raise
      before it is hit, not a fire — but the fix has to land before the index
      does, or the index is a lie on production only. Sketch: an
      `_INDEX_MIGRATIONS` list applied by `ensure_columns`' sibling using
      `CREATE INDEX IF NOT EXISTS` (idempotent by construction, unlike ALTER
      TABLE), a `test_migrations.py` case that builds a pre-index DB and
      asserts the index appears, and an invariant-list entry so the next
      person does not have to rediscover it. Function-based indexes on
      `lower(trim(...))` are supported by SQLite but only used when the
      expression matches exactly — worth pinning with an `EXPLAIN QUERY PLAN`
      assertion rather than assuming (medium; **design doc first** — it is a
      schema-migration mechanism, which CLAUDE.md puts behind a spec + plan;
      inline — `backend/database.py`, `backend/tests/test_migrations.py`,
      CLAUDE.md invariant #4)
- [ ] `storage_usage` guards only one of its three file loops against a file
      vanishing mid-scan (2026-09-07, Claude Auto Review on PR #77; pre-existing
      and deliberately left out of that PR rather than widening it): the
      `other_bytes` walk added there wraps `is_file()`/`stat()` in
      `try/except OSError`, because a backup snapshot can be unlinked by its own
      `BackgroundTask` while the endpoint is reading. The `db_bytes` line and
      the `uploads/` counting loop immediately above it do the same `stat()`
      with no guard, so the identical race still 500s a read-only readout — and
      the inconsistency is now *within a single function*, which is worse for
      the next reader than either extreme. The window is small and the endpoint
      is not hot, so this is robustness rather than a live bug; the fix is to
      hoist one small helper that stats a path and returns 0 on `OSError`, and
      use it in all three places (quick win; implement directly; inline —
      `routers/analytics.py` only)
- [ ] The storage tiles report usage but never **capacity**, so there is no
      warning before the volume fills (2026-09-07 daily run, found while adding
      the `other_bytes` figure): nothing in `backend/` calls `shutil.disk_usage`
      or `statvfs` — verified by grep — so `/api/analytics/storage` answers "how
      much am I using" and cannot answer "how much is left". The Railway volume
      is a fixed size, and the app's only reaction to running out today is
      *after* the fact: `GET /api/analytics/backup.db` returns 507 once
      `VACUUM INTO` fails, which is the moment a backup is most wanted and least
      possible. A backup briefly **doubles** the DB's footprint on that volume
      (CLAUDE.md says so), so the threshold that matters is not "full" but "less
      than one DB-size free" — a figure the panel now has every input for except
      the total. Add `total_bytes`/`free_bytes` from `shutil.disk_usage` on the
      DB's directory, and have the tile warn when free space is under ~2× the
      database size, so the owner learns before the backup button stops working
      rather than from a 507 (quick win; implement directly; inline —
      `routers/analytics.py` plus the Analytics tile, alongside `other_bytes`)
- [ ] Unknown models undercount cost, despite a comment promising they can't
      (2026-09-07 daily run): `analytics.py:44` says *"Unknown/overridden models
      price at Opus rates so estimates never undercount"* and sets
      `_DEFAULT_PRICE = (5.0, 25.0)`. But the table directly above it prices
      `claude-fable-5` at `(10.0, 50.0)` — **double** Opus — so the default is
      not the maximum of the table and the promise is false for exactly the
      newest, most expensive family. A model string the table doesn't know
      (a new Fable revision, a `VISION_MODEL` env override) is billed at half
      its real rate in the one readout the two users split the Anthropic bill
      with, and it looks entirely healthy. Either set the default to the
      table's max and fix the comment to say "the most expensive known rate",
      or report unknown models as a distinct "unpriced" line rather than
      guessing — the second is more honest but changes the shape of the report.
      Worth pairing with the item below, since both are about this table going
      stale (quick win; implement directly; inline — `analytics.py` plus a case
      in `test_analytics_cost.py`)
- [ ] `MODEL_PRICES` is an undated snapshot with no staleness signal — the same
      trap as invariant #15 (2026-09-07 daily run): the eBay fee schedule in
      `frontend/src/lib/fees.js` is documented as "a dated snapshot with
      build-time-only overrides" and carries an invariant explaining that
      nothing in the repo notices when it goes stale. `analytics.py:36-43` is
      the identical shape — six hardcoded per-1M-token prices, no date, no
      source link, no env override at all — and it is worse in one way: the fee
      schedule at least renders its live numbers in prose via
      `feeDisclaimer()`, so a human reading the UI can spot a wrong rate, while
      the model prices are only ever seen already multiplied into a dollar
      total nobody can sanity-check. When Anthropic changes a price, every cost
      figure in the app silently drifts and the invoice is the only correction.
      Cheapest fix is a dated comment plus a line in CLAUDE.md's invariant list
      so the next reader knows what they're looking at; an env override is the
      sturdier version (quick win; implement directly; inline — `analytics.py`
      and CLAUDE.md)
- [ ] Nothing ever prunes the `scans` table, and it is now the DB's main growth
      (2026-09-07 daily run, direct follow-on to the orphan-path fix shipped the
      same day): grep finds no delete of `Scan` anywhere outside the test
      fixture — `routers/cards.py:486` only reads one. Every real (non-mock)
      extraction writes a row carrying the full `extracted_json`, and unlike the
      photos there is no grace window, no sweep, and no tile showing the cost.
      Deleting a card does not remove its scan; the orphan sweep removes the
      *file* and (as of today) nulls the path, which leaves the row as pure
      dead weight: no photo, no card, and — for a scan that never became a card
      — no `Correction` derived from it either. That is the population worth
      pruning, and it is precisely identifiable now that the paths are nulled.
      Note what must NOT be pruned: a scan whose corrections feed
      `build_cheatsheet` is training data, and `Correction` rows reference
      scans, so any retention rule has to preserve those or it silently
      degrades the learning loop. Decide the rule (age? no-card-and-no-
      correction? both?) before writing it (medium; implement directly; inline —
      needs the retention predicate pinned by a test that a scan with a
      correction survives)
- [ ] Backend tests share one real uploads directory and wipe it, so filesystem
      isolation is by luck (2026-09-07 daily run, hit while adding a cleanup
      test): `db_session` isolates DB rows, but nothing isolates the disk —
      `uploads_dir()` resolves off the real `DB_PATH`, and
      `test_upload_cleanup.py` opens two tests with `for f in root.iterdir():
      f.unlink()` while `test_cleanup_with_no_uploads_dir` goes further and
      `rmdir`s the shared directory outright. Any new test that writes an upload
      is therefore order-dependent on those three, which is why the existing
      ones defensively wipe first — the workaround has already been copied three
      times, and a fourth author who doesn't notice gets a failure that depends
      on `-p no:randomly` and reproduces only sometimes. `test_storage.py` and
      `test_backup.py` write into the same directory. Fix with a fixture that
      points `uploads_dir()` at a `tmp_path` per test (monkeypatch the module
      attribute — several modules already import a module rather than a function
      to stay patchable), then delete the defensive wipes (medium; implement
      directly; inline — `conftest.py` plus the four test files)
- [ ] Ten stars or a paid CodeRabbit plan — **owner's call, not a code change**
      (2026-08-31, re-verified 2026-09-07): CodeRabbit reviews nothing
      automatically now (*"this repository does not receive automatic reviews
      because it has fewer than 10 stars"*), and the routine's workaround as of
      today is to post `@coderabbitai review` by hand on each PR. That is a
      manual trigger on every PR forever, and it only works while the free tier
      honours it. Worth deciding whether the second automated reviewer is worth
      ten stars or a paid plan, or whether the Claude Auto Review Action alone
      is enough — in which case `.coderabbit.yaml` should stop being maintained
      (PR #67 updated it this week for a reviewer that was not running) and the
      manual trigger should come back out of the routine prompt (no effort;
      owner decision; not implementable here)
- [ ] `resetAfterSave` runs from `doSave`'s click-time closure and can stomp a
      concurrently reviewed item (2026-09-06 review): with two `ready` items,
      pressing Save on A and then Review on B during the 1–2s save window let
      A's completion wipe B's freshly loaded form (`setForm(EMPTY_FORM)`),
      null the active key, and `setTimeout`-reload B from the stale queue
      snapshot — silently discarding anything typed into B meanwhile. The
      2026-09-06 review shipped the stopgap (the queue's Review button is
      `disabled={submitting}`; the integration PR for #71–#78 gave "Clear
      queue" the same guard, since it also switches the active item mid-save),
      but the underlying shape remains: `resetAfterSave` reads
      `activeKey` and `queue` from the render that created the click handler.
      The durable fix is the same one `pricingSeq` embodies — track the active
      key in a ref and have `resetAfterSave` bail when the item it is
      finishing is no longer the active one (small; implement directly; inline
      — `Scanner.jsx`, no test possible without jsdom, so the guard comment
      must carry the rationale)
- [ ] Alert throttle clocks are consumed before delivery is attempted
      (2026-09-06 review): `notify_credits_exhausted` and
      `notify_callup_alerts_undelivered` both stamp `_last_*_alert_at = now`
      before trying either channel, so a cycle where both channels fail —
      for the call-up alert, precisely the triggering scenario when ntfy is
      unconfigured and the mailer is down — delivers nothing yet suppresses
      the next attempt for the full 6h window, and both callers ignore the
      return value. Stamping only when `emailed or pushed` (or retrying
      sooner after a total failure) is strictly better; while in there, add
      the missing end-to-end case where a cycle has both a failed send and
      abandoned events (`notify(pending, abandoned)` with both non-zero is
      pinned only at the unit level today), and consider an autouse fixture
      for the throttle-clock reset that tests currently do by hand
      (small; implement directly; inline — `services/billing_alerts.py` +
      `test_poll_cycle.py`)
- [ ] The pricing `source` strings deserve the shared-fixture treatment the
      eBay title and condition tables got (2026-09-06 review, now invariant
      #16): `pricing.js` refusing `source === 'mock'` is the only thing
      keeping the $9.99 placeholder out of saved cards, and each side pins its
      own literal — a backend rename that updates its own test leaves both
      suites green while the frontend guard silently stops refusing mocks. A
      fixture both suites read (like `condition_cases.json`) closes it; fold
      in the duplicated source-label mapping while there (`Scanner.jsx` and
      `Inventory.jsx` both hand-roll `source === 'ebay_sold' ? 'eBay sold
      listings' : source`) (small; implement directly; inline —
      `backend/tests/fixtures/`, both pricing test files, `lib/pricing.js`)
- [ ] Actions and container images are pinned by tag, not by digest
      (2026-09-04, raised by CodeRabbit on PR #74 and noted independently by
      the Claude auto-review): every workflow step here references a mutable
      identifier — `actions/checkout@v4`, `actions/setup-python@v5`,
      `actions/setup-node@v4`, and now `docker://rhysd/actionlint:1.7.12`. A
      tag can be repointed by whoever owns it, so a compromised upstream reaches
      CI without anything in this repo changing. Both reviewers called it
      non-blocking and consistent with how the repo already works, which is
      exactly why it belongs here rather than in whichever PR happens to add
      the next step: pinning one job's checkout to a SHA while five others stay
      on `@v4` buys almost nothing and leaves the file looking like nobody
      decided. Worth doing as one sweep, with a note on how the pins get
      updated afterwards — a digest-pinned repo with no refresh habit is how
      you end up running a two-year-old checkout with known bugs, which is a
      different failure, not a smaller one (quick win; implement directly;
      inline — all four workflow files at once, plus a line in CLAUDE.md or a
      Dependabot `github-actions` entry to keep them moving)

- [ ] Nothing exercises the shell inside the workflows, only its syntax
      (2026-09-04 daily run, found while adding actionlint): the new
      `workflows` job catches a YAML typo or an unquoted expansion, and that
      is a real gain — it caught its own step name on the first run — but it
      cannot tell whether `health.yml`'s probe *decides correctly*. That probe
      is now ~130 lines of bash making eight pass/fail/warn judgements, and
      `changelog-guard` is another block of real logic; between them they are
      the two things standing between a broken production and nobody noticing,
      and both are verified today only by whoever last edited them running the
      script by hand (which this run did, against seven fabricated bodies, in
      a throwaway harness that was then deleted). Make that harness a checked-in
      one: extract a named step's `run:` block from the workflow YAML, run it
      with a stubbed `curl` on PATH and a fixture body, and assert the exit
      code and the annotations. Cheap, and it means the next edit to the probe
      cannot quietly invert a condition — the failure mode this whole workflow
      exists to escape (medium; implement directly; inline — one test module
      plus a fixtures directory; note it needs `bash` and `jq` on the runner,
      both present on ubuntu-latest, and pytest would have to skip on a host
      without them)
- [ ] A restart blanks the poller's alert counts for up to one poll interval
      (2026-09-04 daily run, honest follow-on to the health fields shipped the
      same day): `alerts_pending` / `alerts_abandoned` / `last_cycle_ok` live
      on `_poller_state`, which starts empty in a fresh process, so between a
      Railway restart and the first completed cycle — up to
      `CALLUP_POLL_MINUTES`, 15 minutes by default — `/api/health` reports
      `abandoned: 0` and `last_cycle_ok: null` while alerts really are
      abandoned, and the 3-hourly probe passes clean if it lands in that
      window. Nothing is lost permanently: `_recently_abandoned` recomputes
      the count from the database on the next cycle, so the signal returns.
      Two candidate fixes and they differ in more than effort — compute the
      abandoned count on demand inside `/api/health` (exact, but adds a DB
      query with the alertable filter to an unauthenticated endpoint that is
      polled by monitors), or report the pre-first-cycle state as `unknown`
      rather than `0` so the probe can say "not yet known" instead of "fine".
      The second is smaller and honest; the first is the one that actually
      closes the window (quick win; implement directly; inline — `main.py`
      plus `health.yml`'s unknown handling, which already exists for the
      deploy-window case)
- [ ] Changing a user's password does not invalidate their existing sessions
      (2026-09-04 daily run): `require_auth` re-reads `CARDLISTER_USERS` on
      every request and rejects a token whose `sub` is no longer in it — which
      is why removing a user takes effect immediately, as CLAUDE.md says. But
      the token carries nothing about the *password*, so editing a user's
      password on Railway leaves every token minted under the old one valid
      for the rest of its 30-day TTL. That is exactly backwards from what
      changing a password is for: the one action taken when a credential is
      believed compromised is the one that does not end the compromised
      session, and the only lever that does is rotating `JWT_SECRET`, which
      signs everyone out and is nowhere written down as the actual remedy.
      Fix shape without a schema change: put a short fingerprint of the
      password (an HMAC under `JWT_SECRET`, truncated) in the token and
      compare it against the current password in `require_auth` — a changed
      password then fails the comparison and the session ends, while the
      existing "unknown user" check keeps working unchanged. Decide as part of
      it what the 30-day TTL should be if sessions can now be ended
      deliberately (medium; **design first** — auth; per CLAUDE.md's
      design-doc rule, and because getting the fingerprint wrong locks both
      users out of a single-container app with no admin path back in)
- [ ] Nothing records *which preset* produced a scan, so the cost/accuracy
      trade cannot be measured (2026-09-04 daily run): the three presets exist
      precisely to trade money against accuracy — `cost` is sonnet-4-6 at
      1100px, `accuracy` is opus-4-7 at 2000px with high thinking effort — and
      the app already stores both halves of the evidence needed to judge them.
      `UsageEvent` has the tokens and the model, and every `Correction` row is
      a measured miss on a specific scan. What is missing is the join: `Scan`
      records `model` only, so a `balance` scan and an `accuracy` scan are
      indistinguishable in the data (both are opus-4-7), and the question the
      owner actually has — "is accuracy mode worth roughly double the money?"
      — is unanswerable from the database. Recording the preset on the `Scan`
      row makes it a one-query answer: corrections per scan, grouped by
      preset. Worth doing before the fee/cost work further down, since it is
      the input that decides whether the default preset is the right default
      (medium; **design first** — schema: a new column on an existing table,
      so it needs a `_COLUMN_MIGRATIONS` entry per invariant #4, and the
      design should settle whether the effort/px cap are worth storing beside
      it or whether the preset key is enough to derive them)

- [ ] `Card.notes` has no upper length bound anywhere in the pipeline
      (2026-09-03 review): `notes` is `Text nullable=True` on the model and
      `Optional[str]` on `CardBase` / `CardUpdate` with no `max_length`, and
      it reaches the DB from three seams — the review form, vision extraction
      (`confidence_notes` is separate but the model can and does put text into
      `notes` too), and CSV import. A runaway extraction, a mis-selected
      textarea paste, or a mangled `Notes` column in an imported CSV can
      therefore land arbitrary bytes into the row, then into the Sheets
      `Notes` column (which stops rendering usefully past a few thousand
      characters) and into the pasted eBay description (which is capped at
      500,000 but reads as wrong text long before that). A `Field(max_length=4000)`
      on both schema classes rejects the runaway with a 422 rather than storing
      something unmanageable; 4000 is comfortably above every legitimate note
      today (the longest in production is ~180 chars) and below what makes the
      three consumers behave badly (quick win; implement directly; inline —
      `backend/schemas.py` plus a test)
- [ ] `POST /api/analytics/alerts/test` fires two real channels with no
      cooldown (2026-09-03 review): the endpoint deliberately bypasses the
      throttle so the owner can verify the ntfy topic + email recipients are
      wired up, but nothing bounds repeat calls either. A stuck button, a
      rapid double-click, or a hostile logged-in user (both configured users
      pass `require_auth`, and the analytics owner gate is still in design
      per the 2026-08-17 spec) can hammer SendGrid credits and the ntfy
      topic. Add a small module-level cooldown separate from the outage
      throttle — 30-60s — so a repeat call inside the window returns
      `{"skipped": true, "seconds_until_next": N}` without touching either
      channel. Testing works exactly the way it does today on the first
      press; a debounced re-press says why nothing was sent (quick win;
      implement directly; inline — `services/billing_alerts.py` plus a test
      that patches `time.time` and asserts the second call skips)
- [ ] `build_description` renders empty always-emitted lines as blank rows in
      the pasted eBay description (2026-09-03 review): the seven "always"
      lines (Player, Year, Brand, Set, Card Number, Team, Condition) are
      emitted with `card.field or ''`, so an autograph patch with no card
      number pastes into eBay's sell form as `Player: …\nYear: …\nBrand:
      …\nSet: …\nCard Number: \nTeam: \nCondition: NM`, which reads as an
      unfinished description rather than an intentionally-sparse one. Drop
      lines whose value is empty or whitespace-only, parallel to how the flag
      lines already do (`if card.is_rookie:`). Keep Player as a hint the field
      is missing — a listing with no player at all is unusual enough to leave
      the placeholder in as a red flag. Quick win, but *is* the eBay listing
      text: verify by regenerating an existing card's clipboard text and eyeballing
      it, since a change here affects every seller-visible listing (quick
      win; implement directly; inline — `routers/ebay.py` plus a test)
- [ ] An alert that fails to send starts its own six-hour silence (2026-09-02
      daily run): both `notify_credits_exhausted` and
      `notify_callup_alerts_undelivered` stamp their throttle clock
      (`_last_alert_at = now`) **before** attempting delivery, and then return
      `emailed or pushed`. So when both channels fail — SendGrid down, ntfy
      unreachable, `NTFY_TOPIC` unset, `ALERT_EMAILS` empty — the outage is
      recorded as alerted and every call for the next six hours returns early
      without trying again. The two alerts this affects are the two the app has
      *because* something is already broken, and one of them is specifically
      about email not working: "call-up alerts are not being delivered" is most
      likely to fire exactly when the mailer is the thing that is down, which is
      also when its own send fails and buys six hours of silence. The throttle
      is right in shape (a burst of failing scans must not produce one alert
      each) and wrong in placement. Stamp it on a *delivered* alert, and give a
      failed attempt its own much shorter back-off — a few minutes — so a hard
      outage retries without hammering the provider on every scan. Note the
      poll cycle calls the call-up one at most every `CALLUP_POLL_MINUTES`
      anyway, so the failure back-off only really bounds the credits alert
      (quick win; implement directly; inline — `services/billing_alerts.py`
      plus tests that fail both channels and assert the next call retries, and
      that a successful one still suppresses)
- [ ] A failed news refresh blanks the Prospect Wire, and the feed walk has no
      total budget (2026-09-02 daily run, direct follow-on to the empty-result
      caching that shipped the same day): `fetch_articles` walks `_feeds()`
      serially and each `_fetch_feed` carries its own 10s timeout, so the wall
      clock is N × 10s with nothing capping the total — and `NEWS_FEEDS` is an
      env var, so N is an operator decision, not a constant. There is one
      worker. Worse than the latency: when a refresh fails, the empty result
      *replaces* whatever was cached, so a panel that had perfectly good
      headlines two minutes ago goes blank because two feeds timed out once.
      Today's fix bounds how *often* that costs (the empty result is now held
      for 2 minutes instead of re-fetched every request); it does not change
      what it costs or what the user sees. Two changes, both small: keep the
      last good payload and serve it stale-on-error up to some max staleness
      (an hour reads as "yesterday's wire", a day does not), and give the whole
      refresh one wall-clock budget the way `PRICING_DEADLINE_SECONDS` does for
      the comps chain — a scalar httpx timeout is per-connect/read, never a
      request budget (quick win; implement directly; inline —
      `services/prospect_news.py` plus a test that fails the feeds after a good
      fetch and asserts the good articles are still served)
- [ ] Every mock or failed scan leaves its photo on the volume with nothing
      referencing it (2026-09-02 daily run): `scan_card` saves the upload
      first and only writes a `Scan` row `if not is_mock and not error`, so
      the two paths that produce no row still produce a file. Mock mode is not
      an edge case — it is what runs whenever `ANTHROPIC_API_KEY` is unset or
      out of credits, which is precisely when the user retries — and each retry
      writes another uuid-named file that nothing will ever reference. They are
      reclaimable (the orphan sweep on Analytics finds them by definition), but
      only by someone who thinks to click it, and `storage_usage` counts them
      as legitimate usage in the meantime. Cheapest fix is to unlink the saved
      files on the mock/error return, the same way the endpoint already unlinks
      the front image when the back save fails — the file is useless without a
      row to point at it. Decide with it whether an *error* scan should keep
      its photo for the retry to reuse, which is the one argument for leaving
      it (quick win; implement directly; inline — `routers/scan.py` plus a test
      asserting the uploads dir is empty after a mock scan)
- [ ] Nothing in the repo can start the app the way production runs it
      (2026-09-02 daily run, hit while verifying a UI change): the backend
      serves the SPA from `backend/static`, which only the Dockerfile ever
      creates (`COPY --from=frontend /app/dist ./backend/static`), and
      `backend/static/` is gitignored. So the documented dev flow is two
      processes and a Vite proxy, and there is no way to exercise the app as
      deployed — the mode where the SPA fallback, the cache headers and the
      `/uploads` mount actually apply — without hand-assembling a venv, a JWT
      secret, a `CARDLISTER_USERS` pair, a `DB_PATH`, and a manual
      `cp -r frontend/dist backend/static`. That matters beyond convenience:
      step 9 of the daily routine requires actually exercising anything
      user-visible, and a ten-minute reconstruction is the step a run under
      pressure quietly skips. A `scripts/dev.sh` that builds the frontend,
      stages it into `backend/static`, and boots uvicorn with safe local
      defaults makes it one command, and gives the Playwright E2E item further
      down something to point at (quick win; implement directly; inline — one
      script plus a README line)
- [ ] The call-up fetch window is a fixed trailing 2 days, so an outage longer
      than that loses call-ups permanently (2026-09-01 daily run): every cycle
      of `run_poll_cycle` computes `start = today - 2 days` from *now*, never
      from the last window it actually covered, and only transactions returned
      by that request are ever written to `CallupEvent`. So any span the poller
      does not run through — a Railway restart loop, a container asleep, a
      three-day MLB Stats API outage (`fetch_callup_transactions` degrades to
      `[]` on failure, which is indistinguishable from "no transactions") —
      is skipped and never revisited. Nothing records the gap, and
      `/api/health` makes it worse rather than better: `poller.stale` only
      proves the loop is alive *now*, so a container that was down for a week
      comes back reporting perfectly healthy while three days of call-ups were
      never fetched. This is a different failure from the two already fixed —
      those are about events that *were* recorded not being emailed; these
      events never exist at all, so no digest, count or abandoned-alert push
      can mention them. Fix needs no schema: derive `start` from the newest
      `CallupEvent.date` already in the table (falling back to the current 2
      days when it is empty), clamped to a ceiling — ~10 days — so a long
      absence widens the request once instead of asking for a season. Decide
      with it whether a widened window should be reported, since silently
      backfilling a week of transactions and emailing them all as fresh
      call-ups is its own surprise (medium; implement directly; inline —
      `services/callups.py` plus a test that skips a cycle and asserts the
      next one still sees the missed transaction)
- [ ] An unpriced model bills silently at Opus rates (2026-09-01 daily run):
      `analytics.py:_cost` looks the model up in `MODEL_PRICES` and falls back
      to `_DEFAULT_PRICE` (Opus $5/$25) for anything missing. The fallback
      itself is the right call — deliberately never undercount — but it is
      completely silent, and the table is a hardcoded snapshot with no
      staleness signal, the same shape as the eBay fee schedule in invariant
      #15. Reaching it is ordinary rather than exotic: `resolve_preset` falls
      back to env defaults, so a `VISION_MODEL` set on Railway to any id not in
      the table (a newer model, a dated variant) prices every scan at Opus
      rates from then on, in the ledger the two users split real API spend
      with, with nothing anywhere saying the number is a guess. Log once per
      unknown model id and mark those rows in the Analytics by-model table as
      estimated-at-Opus, so a wrong figure is visibly a wrong figure (quick
      win; implement directly; inline — `routers/analytics.py` plus the model
      table in `Analytics.jsx`)
- [ ] Nothing pins that an endpoint's rejection paths stay typed rather than
      500ing (2026-09-01 daily run, the general form of a bug fixed that day):
      the CSV importer's `csv.reader` call raised `_csv.Error` on a field past
      its 128 KB limit and nothing caught it, so a bad file reached the client
      as a blank 500 — and it was found only because a test written for an
      unrelated cap happened to push a field past that limit. The class is not
      fixed: this app parses other people's bytes at several seams (CSV import,
      the eBay compliance webhook body, `_parse_date`/`_parse_money`,
      `resolve_preset`, the multipart upload itself), each hand-guarded against
      the failures whoever wrote it thought of. A small hostile-payload sweep
      would cover the rest for one file's worth of effort: post a handful of
      plausible-but-broken bodies (a NUL byte mid-CSV, a zero-byte file, a file
      that is only a BOM, a multipart part with no filename, a CSV whose header
      row is 200 columns wide) at the two upload endpoints and assert the
      status is never 5xx. Cheap, and it fails loudly the next time a stdlib
      limit is discovered in production instead of in a test (quick win;
      implement directly; inline — one new test module, plus whatever typed
      rejections it turns out to need)
- [ ] The Analytics "By day" chart omits days with no scans (2026-09-01 daily
      run): `analytics()` builds `by_day` from a `defaultdict` keyed on the
      days that have events, so a day with no scanning is absent from the
      response rather than present with a zero. Every row carries its own date
      label, so nothing displayed is *wrong* — but five scattered scan days in
      a 30-day range render as five adjacent bars, which reads as continuous
      activity, and "how often do I actually sit down and scan" is a question
      the panel currently cannot answer. Zero-fill the range server-side (it
      already knows `since` and `until`) so the gaps are visible as gaps. Small
      enough to fold into whichever analytics item lands next rather than
      shipping alone (quick win; implement directly; inline; dataviz skill
      first — `routers/analytics.py` plus the bar list in `Analytics.jsx`)
- [ ] A call-up is judged against inventory once, at first sight, and never
      re-judged (2026-08-26 review): `run_poll_cycle` calls
      `count_inventory_matches` only inside the `if tx["tx_id"] in existing:
      continue` branch — that is, only for a transaction it has never seen —
      and stores `inventory_match` / `matched_card_count` /
      `first_bowman_count` on the row permanently. The pending-alert filter
      then reads the *stored* flag (`is_alertable(e.type_desc,
      e.inventory_match)`), so a **Recalled** transaction for a player whose
      cards the owner had not scanned yet is stamped un-alertable and stays
      that way, even though the 48h retry window is still open and the card is
      now in the database. The order of events is the normal one, not an edge
      case: news of a call-up is often *why* the owner goes and scans that
      player's cards. The same staleness shows in the Prospect Wire ticker for
      its whole 7-day window — the "You Own 3" and "1st Bowman ×1" badges are
      the sell signal the app exists to surface, and they never appear for a
      card acquired after the transaction posted. Fix: recompute the three
      counts for un-emailed in-window events at the top of each cycle (the
      pending set is small and `count_inventory_matches` already scans all
      cards), and re-derive the ticker's badges rather than trusting the
      stamp. Decide as part of it whether *emailed* events should also refresh
      their badges for the ticker's benefit — the alert has already gone out,
      but the ticker is still lying (medium; implement directly; inline —
      `services/callups.py` plus a test that adds a matching card between two
      poll cycles and asserts the second one alerts)
- [ ] The routines open duplicate housekeeping PRs, and the review queue has
      stopped draining (2026-08-31 daily run, observed rather than predicted):
      **PRs #60, #61 and #62 are three separate PRs that each date the same
      `[Unreleased]` heading for PR #59** — one line, three conflicting
      changes — and PR #67 dates it a fourth time as part of a larger diff.
      PRs #63, #64 and #65 each had to carry an HTML comment in the changelog
      explaining why they were *not* touching it. Nothing has merged since
      2026-08-25, so eight PRs are open at once and every new branch now starts
      from a `main` that is a week behind the work. — **both halves shipped
      2026-09-07** (step-11 check in PR #69, queue-depth reporting today), but
      the underlying question is still open and is **the owner's to answer**:
      should a run *stop shipping* past some queue depth? Reporting depth makes
      the pileup visible; it does not stop the routine adding to it. Re-observed
      2026-09-07 — six PRs open (#71–#76), all green, nothing merged since
      2026-09-01
- [ ] A scan the client gave up on is billed, stored, and unreachable
      (2026-08-28 review, direct follow-on to the scan timeout that shipped the
      same day): `/api/scan` writes its `UsageEvent` and its `Scan` row —
      `extracted_json` and all — from the server side, and none of that depends
      on the client still listening. Aborting the request does not stop the
      work, so a scan that times out (or a tab closed mid-scan, or a dropped
      connection on a phone) has been paid for in Opus tokens, has a complete
      extraction sitting in the database, and offers the user nothing but a
      Retry button that will bill them a second time for the same photo. The
      pieces to fix it already exist: the `Scan` table keys on `username` and
      carries `image_path` and the extraction, so a "recent scans" list — or
      simply an offer to restore the last unsaved scan when one exists for this
      user in the last hour — turns a lost scan into a resumed one. Decide as
      part of it whether restoring should re-run the pricing lookup or leave
      the price empty, since the comps at scan time were never stored (medium;
      implement directly; inline — a read-only endpoint beside `/api/scan`
      plus a Scanner affordance)
- [ ] Nothing shows the user what the scanner has *learned*, or lets them
      unteach it (2026-08-28 review): every save that differs from its scan
      writes a `Correction` row, `build_cheatsheet` renders the 200 most recent
      into up to 30 rules appended to every scan prompt, and `find_exact_match`
      overlays identity fields on a brand + card # + year hit. All of that is
      invisible from the app. One mis-saved card — a typo'd set name, a player
      corrected onto the wrong card — becomes a standing instruction to the
      model that shapes every later scan, and the only way to see it is to read
      the database, the only way to remove it is to make an equal and opposite
      correction and hope it wins the dedup. The learning loop is the feature
      that makes the tool get better with use, and it currently has no undo. A
      read-only "what the scanner has learned" list of the current rules on
      Analytics would be most of the value on its own; deleting a rule is the
      other half (medium; implement directly; inline — a `GET` beside the
      existing analytics endpoints plus a panel, reusing `build_cheatsheet`'s
      own selection so the list is the rules actually sent)
- [ ] Fold the orphan figures into `GET /api/analytics/storage` (2026-08-28,
      honest follow-on to the reclaimable tile that shipped the same day): the
      manage-data panel now calls `/storage` and `/uploads/orphans` on mount,
      and both walk the uploads directory and stat every file — two full scans
      per page load where one would do, plus an extra round trip. Nothing hurts
      today at four figures of photos, and the split kept the shipped change to
      one small diff, but the two endpoints answer one question about one
      directory and should share one walk. `/uploads/orphans` needs a DB
      session that `/storage` does not, which is the only reason they are
      separate — a decision worth revisiting rather than inheriting (quick win;
      implement directly; inline — `routers/analytics.py` plus the two tiles)
- [ ] `GET /api/cards/{card_id}` has no caller anywhere (2026-08-30 weekly
      review): `routers/cards.py:454-459` serves a single card, but `api.js`
      never fetches one (the frontend works off the list endpoint and PATCHes
      by id) and no test requests it — it is auth-guarded, correct, and dead.
      Not deleted in the review because it is plausible deliberate REST
      surface, and the "Card permalink deep link" item below is the natural
      first caller — decide together: either that feature lands and uses it,
      or it goes. If it goes, keep invariant #3's literal-before-`/{card_id}`
      ordering note anchored on the PATCH/DELETE routes, which still carry the
      same hazard (quick win; implement directly; inline — cards.py only,
      or fold into the permalink item)
- [ ] The call-up digest has no size cap and is all-or-nothing (2026-08-27
      review): `_compose_digest` renders every pending event into one email and
      `run_poll_cycle` treats the send as atomic — one `send_email` for the
      whole batch, and no row is stamped unless it returns true. That is fine
      for the ordinary two or three transactions a day, and wrong on the one
      date it matters most: MLB roster expansion on September 1 produces dozens
      of `Selected` transactions inside a single two-day window. The owner's
      actual sell signal — the handful of players he owns cards of — leads the
      sort but is then buried in a wall of text, and a single failed send holds
      *all* of them for retry together and can abandon them together. Cap the
      rendered body at N events with a "+M more — see the Prospect Wire" tail
      (matches already sort first, so the cap keeps the signal), and consider
      sending in bounded chunks so one failure cannot lose the whole batch
      (medium; implement directly; inline — `services/callups.py` plus a test
      with a batch larger than the cap)
- [ ] Price *to* a target net, now that the fee math exists (2026-08-25
      review): the Comps modal's "Set Price to $X" applies the comps median
      gross, and the seller who wants to clear $20 has to invert the fee
      schedule in their head. `estimateFees` inverts exactly but **piecewise**
      — `price = (target + fixed) / (1 - rate)` holds only within one tier, and
      the candidate price has to be re-checked against both the $10 per-order
      step and the $7,500 rate tier (and re-solved in the other band when it
      crosses), which is the part to get right rather than eyeball. A small
      "net target" input beside the apply button then turns the modal from a
      report into the pricing tool it is trying to be. Same pass should decide whether the Inventory
      **Revenue** tile (gross `sold_price`, `lib/inventoryStats.js`) grows a
      net-of-fees companion: realized profit computed gross is the number that
      makes a thin-margin month look fine (quick win; implement directly;
      inline — `lib/fees.js` + `Inventory.jsx`, and `inventoryStats.js` if the
      tile is included)
- [ ] The eBay fee rate cannot actually be changed on the deployed app
      (2026-08-25 review, honest follow-up to the estimate that shipped the
      same day): `lib/fees.js` reads six `VITE_EBAY_FEE_*` vars — `_RATE`,
      `_RATE_ABOVE`, `_TIER`, `_FIXED`, `_FIXED_ABOVE`, `_FIXED_THRESHOLD`
      (the tiered-schedule rework widened the original two; whoever implements
      this must plumb all six or the tier half of the schedule stays frozen) —
      but Vite inlines those at **build** time and the
      Dockerfile's frontend stage passes no build args, so Railway always gets
      the compiled-in defaults. eBay changes category rates, and a store
      subscription changes them per seller; when that happens the only lever
      today is editing the constant and redeploying. Two options, and they
      differ in more than effort: a Dockerfile `ARG`/`ENV` pair plumbed into
      `npm run build` keeps it a pure frontend concern but still needs a
      rebuild to change; serving the rate from the backend alongside the other
      integration config makes it a restart-free env var and puts it where a
      future *server-side* net (P&L, tax export) could share it. Pick before
      building — the second one is the one that scales (quick win; implement
      directly; inline)
- [ ] Backfill the conditions already in the database (2026-08-24, follow-on
      to the condition dropdown shipped the same day): `normalize_condition`
      is applied at the two seams where new values arrive — the review form
      and CSV import — so everything saved *before* today keeps whatever
      spelling it has, in both the DB and the Sheets `Condition` column. The
      fragmentation the dropdown was built to stop is therefore still sitting
      in the existing inventory. Add a one-shot action on the Analytics
      manage-data panel that reports how many rows would change and to what
      **before** applying (the same dry-run-then-apply shape the CSV import
      preview item asks for), then applies the fold and triggers the existing
      Sheets resync. Unrecognized values are left alone by construction, so
      the blast radius is exactly the rows whose spelling the app already
      recognizes (quick win; implement directly; inline — reuses
      `services/card_fields.py` and `POST /api/sheets/resync`)
- [ ] Sheets mirror: the `sheets_row` DB commit happens *outside*
      `_sheets_lock`, defeating the race protocol PR #46 built (2026-08-23
      weekly review). The lock's own comment (`google_sheets.py`) claims it is
      "held across re-read → Sheet write → sheets_row commit", but every
      writer releases it on return and the commit runs in the caller:
      `sync_card`'s row is committed at `cards.py:_sync_card_to_sheets`, and
      `rewrite_all_rows`' stamping loop at `sheets.py` after the `with` exits.
      Two concrete losses: (a) a save's background task can commit a stale row
      index *over* a resync's fresh one, so the card's next edit writes into a
      row that now belongs to another card; (b) `blank_row`'s under-lock
      `_is_owned` check reads DB state a concurrent resync hasn't committed
      yet, so a delete racing a resync can blank a row the resync just gave to
      a live card. `resync_one` (`POST /api/sheets/sync/{card_id}`) bypasses
      both halves of the protocol entirely and has no caller — fix or delete
      it. Fix shape: pass a `commit(rows)` callback into the three writers so
      the DB commit executes before the lock releases (mirroring the existing
      `reread_row` pattern), plus a two-thread interleaving test (the whole
      lock currently has zero concurrency coverage — moving the reread outside
      the lock passes all 14 mirror tests), a test for the resync `"commit"`
      failure branch, and a post-resync assertion that every `sheets_row`
      matches its sheet position (large; **design first** — data integrity
      across `google_sheets.py`/`cards.py`/`sheets.py`; extend the existing
      2026-08-17 Sheets integrity design doc rather than starting a new one)
      — **design + plan written 2026-08-29** (addendum in
      `docs/superpowers/specs/2026-08-17-sheets-mirror-integrity-design.md`,
      plan in `docs/superpowers/plans/2026-08-29-sheets-lock-commit.md`):
      recommends caller-supplied commit callbacks invoked inside the lock
      (mirroring the `reread_row` shape), deleting the caller-less
      `resync_one`, and names the SQLite ABBA deadlock the move introduces
      plus its fix (background tasks `rollback()` before waiting on the
      lock). Zero scan-cost delta. **Awaiting owner approval on the three
      decisions at the end of the plan doc.**
- [ ] Scanner `resetAfterSave` advances the batch queue from a stale snapshot
      (2026-08-23 weekly review): it computes `nextReady` from the render
      closure captured when Save was pressed, but `doSave` awaits two network
      calls plus the clipboard before calling it, and the queue can change
      underneath — clear the queue (confirming the loss warning) while a save
      is in flight and the closure still schedules `reviewQueueItem` on the
      discarded item, resurrecting its form and firing a fresh pricing lookup
      for a card the user just threw away. Track the live queue in a ref (or
      compute inside the functional update) and bail if the item is no longer
      present and `ready` (quick win; implement directly; inline —
      Scanner.jsx only)
- [ ] `scan_card` runs sync SQLite work on the event loop (2026-08-23 weekly
      review): the poller fix moved `run_poll_cycle` to the threadpool, but
      async `scan_card` still calls `build_cheatsheet(db)`, `db.commit()`, and
      `apply_exact_match` directly, and `_save_upload` does sync 1MB disk
      writes. If a Sheets background thread holds the SQLite write lock
      mid-commit, the event loop itself blocks for up to the busy timeout,
      stalling every request including `/api/health` — the exact class the
      poller fix closed. Wrap the DB block and the upload write loop in
      `run_in_threadpool` (async `import_csv` has the same shape but is
      milliseconds-scale; fix opportunistically) (medium; implement directly;
      inline — scan.py only)
- [ ] CI guards for the two invariants that break an already-deployed install
      (2026-08-20 review): invariants #1 and #4 are the two whose failure mode
      is silent *and* remote — they work on a fresh DB and a fresh sheet, and
      corrupt the deployed one. Neither has a test. (a) `_COLUMN_MIGRATIONS`
      completeness: `test_migrations.py` exercises the *mechanism*
      (`ensure_columns` adds `quantity`, runs twice safely, skips a missing
      table) and nothing at all asserts the list is complete, so a new model
      column with no entry passes the whole suite and breaks every deployed
      database. A checked-in baseline schema snapshot, migrated forward and
      diffed against `Base.metadata`, turns that into a CI failure. (b)
      `SHEET_HEADERS` order: `test_export_csv.py` compares the CSV header row to
      `SHEET_HEADERS` itself, so a column *inserted mid-list* — the exact move
      invariant #1 forbids, because it misaligns every already-synced row —
      passes as long as `_card_to_row` moves with it. A golden literal list
      pinned in the test makes the insert fail and the append pass. Decide with
      it what the migrations baseline is (earliest deployed shape vs. today's
      production shape) (medium; implement directly; inline)
- [ ] `Date Listed` is the one date the CSV importer still takes on faith
      (2026-08-31, direct follow-on to the sale-date bound that shipped the
      same day): `_parse_date` feeds both columns, and `sold_at` is now bounded
      while `created_at` is not — so a mistyped `2062` in **Date Listed** is
      still accepted in full. It is quieter than the sold-date version and not
      harmless: `created_at` is the Sheets "Date Listed" column, it is the
      primary sort key of the resync (`created_at, id` — the ordering
      invariant #1 depends on), and the planned days-to-sell analytics measures
      created→sold, which a future listing date makes negative. The
      2026-09-06 review added the normalization half: an aware `+14:00` value
      is stored as its wall clock (SQLite drops tzinfo without converting —
      the exact bug `normalize_sold_at` exists to prevent), while the same
      offset on `Date Sold` in the same row is converted to UTC, and a future
      `created_at` also pins the row to the top of the `created_at desc`
      inventory list forever. Apply the same
      `reject_future_sold_at` bound (rename it for both callers) with the same
      drop-and-warn treatment plus the naive-UTC normalization, and decide
      with it whether `created_at` should
      fall back to now the way a missing `sold_at` does (quick win; implement
      directly; inline — `routers/cards.py` plus a warn-path case in
      `test_import_csv.py`)
- [ ] Test fixtures that are ahead of the calendar fail on a date, not on a
      change (2026-08-31, hit while adding the sale-date bound): the sold-export
      ordering test marked a card sold on `2026-12-20`, so the new bound turned
      it red — correctly, but the fixture had been describing a *future* sale
      for most of the year it names, and nothing said so. That one is fixed;
      the class is not. Sweep the suites for hardcoded dates that are or will
      be ahead of the runner's clock (`backend/tests/test_export_sold_csv.py`
      still seeds several 2026 dates, all currently past) and prefer either a
      fully elapsed year or an offset from `utcnow()`. Worth pairing with a
      note in the testing section of CLAUDE.md, since the frontend suite has
      the same exposure through its pinned `America/New_York` zone (quick win;
      implement directly; inline)
- [ ] Save-flow clipboard + eBay tab run after `await`, so both can be
      silently blocked (2026-08-18 review): `doSave` in `Scanner.jsx` awaits
      `createCard`, then `getEbayListingText`, and only then calls
      `navigator.clipboard.writeText` and `window.open(EBAY_SELL_URL)`. Both
      APIs are gated on *transient user activation*, which the click that
      started the save has already spent by the time two network round trips
      finish — Chrome's window is ~5s, and Safari requires a clipboard write in
      the same task as the gesture. The app's whole payoff is "save copies the
      listing text and opens eBay to paste", and this is the mobile flow (phone
      camera → iOS Safari) where the restriction is strictest. The existing
      `clipboardOk` fallback proves the clipboard half already fails sometimes;
      the popup half has no fallback at all, so a blocked tab looks like
      nothing happened. Fix by moving both behind a fresh gesture — fetch the
      listing text with the card, then put "Copy text" and "Open eBay" buttons
      in the success toast — rather than firing them from the async tail.
      **Cannot be verified headlessly**; needs a real iOS Safari pass (quick
      win–medium; implement directly; inline — Scanner.jsx only)
- [ ] `PricingResponse.comps` is an untyped `List[dict]` with no contract test:
      all four sources hand-build `{"title": …, "price": …}` and the frontend
      reads both keys directly. Nothing pins the key names, so a scraper
      refactor that renamed `price` would pass the whole backend suite and
      break the median with no error anywhere. Both render sites now go through
      `formatCompPrice`, which shares its usable-price test with
      `summarizeComps` and shows `—` for anything unusable (2026-08-18) — so a
      bad price degrades visibly instead of throwing mid-render or posing as a
      real `$0.00` sale. That caps the blast radius on the display side and
      pins nothing on the wire: the contract is still unenforced. Give comps
      a pydantic model and add a parity test asserting every source's parser
      emits it, using the saved fixture HTML the scraper tests already carry
      (medium; implement directly; inline)
- [ ] Pricing lookups are never cached, so the same card re-runs the whole
      chain every time (2026-08-19 review): `get_pricing` takes a
      `PricingRequest` and goes straight to the sources — no memoization
      anywhere. Opening the Inventory Comps modal twice on one card, or
      re-reviewing a batch item, pays the full serial chain again, and on
      Railway (where the scrapers 403) that is the ~50s worst case *each
      time*. A small TTL cache keyed on the normalized query
      (player/year/brand/set/card #) would make a repeat lookup instant and
      cut scraper traffic, which is also what makes the scrapers block. Two
      decisions to make with it: how long a sold comp stays fresh (hours, not
      minutes — these are completed sales, not live prices), and whether the
      `mock` fallback is cached at all (it should not be, or a transient
      scraper block pins $9.99 to a card for the whole TTL). The parallel
      fan-out this was once told to wait for **has shipped** (2026-08-19,
      PR #52), so the sequencing constraint is discharged: build the cache on
      top of the concurrent implementation, in front of the fan-out, so a hit
      skips submitting every source rather than racing them and discarding
      the results (medium; implement directly; inline)
- [ ] Analytics day boundaries are UTC, so the owner's evening scans land on
      the wrong day (2026-08-19 review): `_range_start` builds the `today` and
      `month` windows from `datetime.utcnow()`, and `by_day` buckets on
      `ev.created_at.strftime("%Y-%m-%d")` — both UTC. East-coast, that means
      the day rolls over at 8pm EDT: a card scanned at 9pm appears on
      *tomorrow's* bar in the daily cost chart, and the "Today" filter after
      8pm reports a window that started yesterday evening. On the first of the
      month the "This month" total is wrong for four hours. Same root cause as
      the mark-sold picker's UTC default — whose *frontend* half shipped
      2026-08-20 (PR #53, `lib/soldDate.js`), leaving the backend stamps
      (`mark_sold`'s `datetime.utcnow()` and the CSV import's) still skewed —
      and the fix should be the same one applied
      once: a configured local timezone (`CARDLISTER_TZ`, defaulting to
      America/New_York) with a shared helper, used by analytics windows,
      mark-sold's default date, the Sheets "Date Listed"/"Date Sold" columns,
      and the sold-cards tax export — a sale stamped in the wrong year is a
      wrong tax return. Worth doing as one pass because a half-converted app
      is harder to reason about than a consistently-UTC one (medium; **design
      first** — a timezone change silently re-buckets every historical
      analytics reading, and the choice of "what does a stored naive datetime
      mean" has to be made explicitly; inline) — **design + plan written
      2026-08-22**
      (`docs/superpowers/specs/2026-08-22-local-timezone-design.md`,
      `docs/superpowers/plans/2026-08-22-local-timezone.md`): recommends
      storage staying naive UTC with conversion at the edges via
      `CARDLISTER_TZ` (default America/New_York), an explicit
      midnight-means-date-only contract (mark-sold and CSV import have been
      minting UTC-midnight rows, so naive conversion would shift every
      historical sold date back a day; the modal now submits the bare date
      so new writes share the representation — no data migration), and a
      `tzdata` pip pin (the `python:3.11-slim` image has no zoneinfo, so the
      gap crashes only in production while CI stays green). Covers the
      backend half of the mark-sold skew (whose picker shipped 2026-08-20 in
      PR #53), the Sheets date columns, and the tax-year export in one pass. **Awaiting owner approval on the three decisions listed at
      the end of the plan doc.**
- [ ] eBay title truncation cannot spare the flags, because it can only cut a
      prefix (2026-08-19 review, deferred out of the truncation fix that
      shipped the same day). **Current behaviour:** unit order is
      `year brand set player #num flags team`, and `truncate_title` keeps a
      prefix and discards everything from the first unit that doesn't fit
      onward. The team is last, so it is always among the discarded — but the
      flags sit immediately before it, so anything that costs the team its
      place costs `/99`, `REFRACTOR`, `AUTO` and the parallel colour first.
      A real 2023 Bowman Chrome Prospects card renders as
      `2023 Bowman Chrome Prospects Jackson Chourio #BCP-100 RC 1ST BOWMAN
      REFRACTOR`, having dropped both `/99` **and** `Brewers` together; there
      is no cut that keeps the serial and drops only the team.
      **Proposed change:** give units a drop *priority* independent of their
      position in the string — team goes first, then the parallel colour, then
      the lesser flags — so the high-value search terms survive a long set
      name. Buyers search the flags; nobody searches "Brewers" to find a
      specific card. That is a genuine **format change** (invariant #7 — three
      files plus regenerated fixtures) and needs owner sign-off on the drop
      order before it lands (medium; **design first** — changes what a listing
      says; inline)
- [ ] Unmount guards on Analytics' async state writes, applied consistently
      (CodeRabbit on PR #49, deferred deliberately): `.coderabbit.yaml` asks
      reviewers to flag "state updates after unmount", and `ManageData` has
      five async paths that write state after an await — `getConfiguredUsers`,
      `loadStorage`, `getSoldYears`, and the `exportSold`/`backup`/`importCsv`
      handlers — none of which is guarded. The reviewer flagged only the two
      the PR added; guarding those alone would leave the same component
      half-converted, which is harder to reason about than either extreme.
      Worth noting the impact is nil today: React 18 removed the
      setState-after-unmount warning and such a write is a silent no-op, so
      this is convention rather than a live defect. Do it in one pass over the
      file (a single `mountedRef` set false in the effect's cleanup, checked
      before each write) or decide the convention doesn't apply to React 19 and
      amend `.coderabbit.yaml` instead — either is fine, but pick one (quick
      win; implement directly; inline — Analytics.jsx only)
- [ ] Analytics user-admin routes have no caller check (found by the
      2026-08-17 Monday security pass; **confirmed by reproducing it against a
      running app**): `POST /api/analytics/users/reassign` and
      `DELETE /api/analytics/users/{username}/data` are guarded only by the
      router-level `Depends(require_auth)`, which proves *some* configured user
      is logged in and nothing more. Neither handler takes the caller's
      username — available as a value dependency, the way `scan.py` and
      `create_card` already use it — so either configured user can move the
      other's `UsageEvent` rows onto them (the ledger the two users split API
      spend with) or delete another user's usage/scan/**correction** history
      outright. The `Correction` rows are the learning loop's training data, so
      the delete is data loss, not just accounting. Cards are deliberately
      shared; per-user attribution is deliberately not. The fix needs an owner
      concept that does not exist yet (`CARDLISTER_USERS` has no roles), which
      is the design question: a `CARDLISTER_OWNER` env var defaulting to the
      first entry and 403 for everyone else, versus simply requiring
      `from_user == caller` / `username == caller` so a user can only touch
      their own attribution. Needs a test that a *second* configured user is
      refused — `test_user_admin.py` only ever exercises one user, so today's
      cross-user authority is unpinned either way (medium; **design first** —
      touches auth; inline) — **design written 2026-08-18**
      (`docs/superpowers/specs/2026-08-18-analytics-owner-gate-design.md`):
      recommends a `CARDLISTER_OWNER` gate and REJECTS caller-scoping, since
      the panel exists to merge a ghost username that can never be the caller,
      and caller-scoping still permits pushing your own spend onto the other
      user. Also covers `uploads/cleanup` (the only unrecoverable route).
      **Needs a plan doc next, then owner approval.**
- [ ] `CARDLISTER_USERS` parsing silently mangles passwords containing a comma
      (found by the 2026-08-17 Monday security pass): `get_users()` splits the
      whole variable on `,` before splitting each entry on `:`, and drops any
      resulting fragment without a `:`. So `brock:a,B9xQ7` yields a
      **one-character** password for `brock` with no warning, and
      `validate_secrets()` waves it through because it only rejects empty or
      literally-`changeme` passwords. Worse, a password containing both a comma
      and a colon mints an unintended extra account: `brock:pa,ss:word` also
      creates user `ss` with password `word`. Not remotely exploitable on its
      own — it needs a specific password shape, and the owner's own login would
      fail — but it is a config footgun that can quietly leave production with a
      trivial credential or a phantom user. The fix is to fail loud rather than
      degrade: treat an entry without a `:` as a `validate_secrets()` problem
      instead of skipping it. A delimiter change (newline-separated entries, or
      one env var per user) is the sturdier fix but needs a coordinated Railway
      env-var migration, and the constraint should be documented in README and
      `.env.example` either way (quick win–medium; **design first** — touches
      auth and requires a deploy-config migration; inline)
- [ ] Scanner loses reviewed work on a refresh or an accidental back/close: the
      batch queue and the reviewed form live only in React state, and there is
      no `beforeunload` guard anywhere in `frontend/src`. Every `ready` queue
      item represents Opus tokens already spent, so a stray gesture on a phone
      throws away both the review effort and real money. In-app navigation is
      the same hole and `beforeunload` does not cover it: the save toast's own
      "View Inventory →" link unmounts Scanner and destroys the rest of the
      batch with no warning (2026-08-23 review). Register a `beforeunload`
      handler while any queue item is unsaved or the form is dirty, plus a
      react-router blocker (or confirm-on-nav) for SPA navigation (quick win;
      implement directly; inline — Scanner.jsx only)
- [ ] Integration-configuration readout on Analytics manage-data: Sheets
      (`_get_service` returns None with no credentials), the eBay Browse API
      (`is_configured()`), the vision billing ladder (api key → subscription →
      mock), and the email/ntfy alert paths all degrade to silent no-ops. A
      save that never reaches the sheet looks exactly like a working save, and
      a deploy running in mock mode looks like a deploy that is scanning. Add
      an authenticated endpoint reporting configured/not for each integration
      (never the secret values) plus a small panel — the pull-side complement
      to the "Sheets sync failure visibility" item below, which reports errors
      from syncs that were actually attempted (quick win–medium; implement
      directly; inline)
- [ ] `listed_at` timestamp on cards: the Sheets/CSV "Date Listed" column is
      filled from `created_at` (`_card_to_row`), which is when the row was
      saved, not when it went live on eBay — `attach_ebay_listing` stamps no
      date at all. A card saved two weeks before it was listed reports the
      wrong listing date in the mirror, and the planned days-to-sell analytics
      inherits the same imprecision (it measures created→sold). Fold into the
      same schema pass as the `previous_status` / soft-delete items in Later
      (quick win once the column exists; **plan doc first** — schema change,
      needs a `_COLUMN_MIGRATIONS` entry; inline)
- [ ] eBay deletion-notice signature verification: the account-deletion
      endpoint acks any POST — eBay signs notices with `X-EBAY-SIGNATURE`
      (ECDSA, public key from the Notification API) and the handler never
      checks it, so the log it keeps as the future audit trail is forgeable by
      anyone with the URL. Harmless while nothing is stored, but a **hard
      prerequisite** of the draft-listing/OAuth feature: once seller tokens
      exist, an unverified notice becomes an unauthenticated "delete this
      user's tokens" request (medium; **design first** — key fetch + cache +
      verify, still 2xx on failure per eBay retry semantics; found by the
      2026-08-16 weekly deep review) — **design + plan written 2026-09-05**
      (`docs/superpowers/specs/2026-09-05-ebay-deletion-signature-design.md`,
      `docs/superpowers/plans/2026-09-05-ebay-deletion-signature.md`):
      recommends in-process ECDSA/SHA-1 verification with a **dual-path
      verifier input** (raw received bytes first, the official SDKs'
      compact re-serialization as fallback — what eBay signs is inferred
      from its SDKs, not documented, so the design verifies under either
      reading and pins interop with a genuinely eBay-signed vector from the
      reference SDK's test data), key fetch via the app token
      `ebay_api._get_app_token()` already mints, cached by kid with an
      entry-capped negative cache and a global per-minute fetch budget
      (per-kid caching alone bounds nothing against a fresh forged kid per
      POST), and **412 on failure behind a confirm-then-enforce
      rollout** — the 412 reverses this item's own "still 2xx" parenthetical
      after grounding in eBay's reference SDK (204-verified / 412-failed; a
      2xx is a terminal ack that discards eBay's redelivery), but ships in
      shadow mode (ack + log + alert) until `EBAY_SIGNATURE_ENFORCE=1` is
      set after a genuine signature verifies in production. Degrades to
      today's unverified ack when `EBAY_APP_ID`/`EBAY_CERT_ID` are unset,
      scoped to the era before seller OAuth tokens can exist. Zero Anthropic-call delta; no
      new dependency (`cryptography` via python-jose), no schema, no new
      route. **Awaiting owner approval on the three decisions at the end of
      the plan doc.**
- [ ] SPA mount wiring test: `test_spa_fallback.py` exercises `SpaStaticFiles`
      on a throwaway app over a temp dir, and `backend/static` doesn't exist
      in CI — so reverting `main.py`'s mount to plain `StaticFiles(html=True)`
      passes the whole suite. Cleanest fix is an app-factory refactor so a
      test can build the app with a temp static dir; note the prefix check
      also runs on the normalized path, so raw `/api/..`-style requests get
      the shell (cosmetic — browsers normalize before sending) (medium;
      implement directly; inline — found by the 2026-08-16 weekly deep review)
- [ ] Batch scan front/back auto-pairing: uploading 20 images of 10 cards
      currently treats each image as its own card; match front+back pairs
      before extraction. Candidate signals: upload order/adjacency (phone
      camera rolls alternate front,back), filename timestamps, then a cheap
      vision pass ("is this a card back?") to pair each back with the
      preceding front; unpaired images fall back to single-sided scan. UI:
      pairing review step in the batch queue with drag-to-repair before
      Claude extraction runs (large; design first — touches Scanner queue,
      /api/scan, and scan cost per card) — **design + plan written 2026-08-15**
      (`docs/superpowers/specs/2026-08-15-batch-front-back-pairing-design.md`,
      `docs/superpowers/plans/2026-08-15-batch-front-back-pairing.md`):
      Phase 1 is frontend-only (heuristic pairing + review step, $0 added
      cost, ~40% cheaper on the target workload). **Approved by owner
      2026-08-15 — Approach A, pairs proposed by default in front-then-back
      order; cleared for implementation per the plan doc.** Subsumes the
      "Batch-mode back images" item below.
- [ ] Comps accuracy — parallel/variant contamination: suggested price
      factors in parallel + serialized listings when pricing a base card
      (and vice versa), skewing high, and it's worst on exactly the cards
      worth the most. Two halves of one fix: (a) plumb the attributes
      through — `PricingRequest` carries only player/year/brand/set/card #,
      so parallel color, serial number, refractor, and auto never reach the
      pricing chain at all (schemas, pricing router, service query builders,
      CompsModal/Scanner callers); (b) filter results against the card's own
      parallel_color/serial/refractor flags — exclude comps whose titles
      carry non-matching variant markers (Gold, /99, Refractor, Auto, etc.),
      require matching markers when the card HAS them, and surface which
      comps were excluded in the modal so mispricing is auditable (medium;
      implement directly — title-token filter shared across ebay_api and
      scrapers; needs a title-marker test table)
- [ ] Interactive pricing agent on the post-scan page: instead of a single
      suggested price, collect the full comp set (eBay API + scrapers, raw
      titles/prices/dates) into context and open a chat box — "my card is a
      PSA 10, what should I list at?", "now price it without parallels",
      "why is this one $40?". Agent answers from the gathered comps, can
      re-query sources with refined terms (graded, base-only), and can
      write its conclusion back into the listed-price field on request.
      Cost-aware: comps gathered once per card, cheap model for chat
      turns, usage metered into the existing UsageEvent tracking (large;
      design first — new agent loop endpoint + chat UI on review form;
      pairs with the comp variant-filter item above)
- [ ] Scan-accuracy report on Analytics: Corrections table already stores
      extracted-vs-corrected diffs — chart correction rate over time and
      most-corrected fields (medium; implement directly; inline; dataviz skill first)
- [ ] eBay Orders API polling → auto-mark cards sold (reuses call-up scheduler
      pattern; Phase 2 stub in `backend/routers/ebay.py`) (large; design first —
      needs eBay OAuth + a second poller concern, see invariant #9)
- [ ] Stale-listing reprice digest (scheduler + mailer + pricing chain all
      exist) (medium; implement directly; inline)
- [ ] Inventory value / P&L dashboard on Analytics (est. value, realized profit
      by player/brand) (medium; implement directly; inline; dataviz skill first)
- [ ] Edit saved cards from Inventory: after save the only mutable field is price via
      the Comps modal — typos require delete + rescan; reuse CardForm in a modal
      (medium; implement directly; inline)
- [ ] Partial-quantity mark-sold: selling 1 of a qty-3 row currently marks the whole
      row sold; should decrement quantity and record a sold row (medium; implement
      directly — no schema change, split logic in mark_sold; inline)
- [ ] Days-to-sell analytics: avg/median `created_at → sold_at` interval plus a
      distribution view on Analytics, so pricing strategy gets feedback ("Bowman
      autos sell in 4 days, base sits for 60") (medium; implement directly;
      inline; dataviz skill first)
- [ ] CSV import duplicate handling: import blindly creates rows even when an
      identical non-sold card exists — reuse the check-duplicate identity rules
      per row to warn (or opt-in merge quantities), preventing double-ups on
      re-import of an edited export (medium; implement directly; inline —
      builds on the import parser + `check_duplicate` matcher)
- [ ] Re-scan in a higher mode without re-upload: extraction misses currently mean
      re-staging the photo; the file and Scan row are already on the server, so add
      `POST /api/scan/{scan_id}/rescan` with a preset param + a "Re-scan in
      Accuracy" button on the review form (medium; implement directly; inline)
- [ ] Batch-mode back images: batch queue is front-only today (UI says "scan
      those individually"); add a per-item back slot before scanning starts
      (medium; implement directly; inline) — **do not implement separately:
      subsumed by the batch front/back auto-pairing design above**
      (`docs/superpowers/specs/2026-08-15-batch-front-back-pairing-design.md`);
      its review step is the per-item back slot
- [ ] Remember inventory sort choice in localStorage (builds on the 2026-07-28
      sortable columns; touches Inventory.jsx) (quick win; implement directly;
      inline)
- [ ] CSV import dry-run preview: run the 2026-07-30 import parser without
      committing and show would-be created/skipped counts before the real import
      (quick win; implement directly; inline)
- [ ] Duplicate sweep over existing inventory: check-duplicate only fires at save
      time; add a "Find duplicates" tool that applies the same identity rules
      across all non-sold rows and offers merge (sum quantities, keep earliest row)
      (medium; implement directly — no schema change; inline)
- [ ] Scan history browser: the Scans table keeps every real extraction + photos,
      but nothing surfaces them — list past scans and allow saving one that was
      never saved as a card (medium; implement directly; inline; UI as its own
      panel so it doesn't collide with in-flight Scanner.jsx work)
- [ ] Weekly inventory digest email: Sunday summary via the existing mailer —
      cards added, scans + est. API cost, actives missing a listing URL, stale
      actives (medium; **plan doc first** — touches 3 subsystems: scheduler,
      mailer, analytics queries; inline)
- [ ] Sheets drift detector on Analytics manage-data: on-demand compare of the
      Sheets mirror vs DB (row count + per-card diff), showing mismatches next
      to the existing one-click full resync — today drift is invisible until
      someone eyeballs the sheet; `resync` endpoints already exist in
      `backend/routers/sheets.py` (medium; implement directly; inline)
- [ ] Bulk row selection in Inventory: checkbox column + bulk mark-sold /
      delete / copy-listing-text over the selection; today every action is
      one row at a time, which hurts at 100+ cards (medium; implement
      directly; inline — builds on CardTable.jsx)
- [ ] Photo backup zip: the SQLite snapshot backs up the database only — card
      photos on the Railway volume still have no backup story; add
      `GET /api/analytics/backup-photos.zip` streaming all card-referenced
      uploads (medium; implement directly; inline)
- [ ] Server-side thumbnails: the inventory table's `<img>` cells load the
      original scan photos; generate a ~256px thumbnail at upload time (Pillow
      already a dependency) and serve that in `CardTable`, keeping the original
      for the lightbox (medium; implement directly; inline — touches CardTable;
      NOTE: thumbnails must be new files, never in-place rewrites — invariant
      #12, /uploads is cached immutable)
- [ ] Backend error visibility: unhandled 500s only live in Railway logs; add
      exception middleware that records recent errors to a small table with a
      "recent errors" readout on Analytics manage-data, reusing the ntfy push
      for spikes (medium; **plan doc first** — new table/schema; inline)
- [ ] Scanner batch-review keyboard shortcuts: Enter = save & advance, ←/→ move
      through the queue — batch review is the highest-repetition flow in the app
      and is entirely mouse-driven today (quick win–medium; implement directly;
      inline — touches Scanner.jsx)
- [ ] Monthly scan-cost budget alert: usage table already tracks est. cost per
      scan; add an env-configurable monthly cap with an Analytics banner and the
      existing ntfy push when 80% / 100% is crossed, checked in the poll cycle
      (medium; implement directly — reuses usage table + alerts, no schema; inline)
- [ ] Card permalink deep link: `/inventory?card=123` scrolls to and highlights
      the row (clearing the search/filters if they hide it) — the QR-labels
      item below explicitly needs a permalink first, and shared links/bookmarks
      get it for free (quick win; implement directly; inline — touches
      Inventory.jsx only)
- [ ] Player-name autocomplete in CardForm: a `<datalist>` fed from existing
      inventory player names, so repeat players are picked instead of retyped —
      free-text typos ("Jackson Holiday") fragment search and the planned
      per-player analytics (quick win; implement directly; inline — CardForm.jsx
      plus a tiny names endpoint or reuse of the already-loaded card list)
- [ ] Backup-staleness nudge on Analytics manage-data: remember the last
      "Download database backup" click (localStorage) and show a banner when
      it's older than 14 days — the backup story is entirely manual until the
      plan-doc-gated nightly delivery ships, and nothing reminds anyone today
      (quick win; implement directly; inline — Analytics.jsx only)
- [ ] Call-up poller stale push alert: `/api/health` already computes poller
      staleness (3 missed intervals) but only reports it to whoever looks; fire
      the existing ntfy push (billing_alerts) once per stale episode from the
      poll-cycle watchdog so a silently dead poller gets noticed — prospects
      can get called up during the outage (medium; implement directly — reuses
      `_poller_state` + ntfy, no schema; inline)
- [ ] eBay Seller Hub bulk-listing CSV export: export active cards in eBay's
      bulk-upload template (title from `build_title`, price, condition,
      category) so a batch of drafts can be created in one Seller Hub upload —
      a no-OAuth stepping stone to the Sell API item in Later (medium;
      implement directly; inline — new endpoint beside `export.csv`)
- [ ] Inventory pagination / windowed rendering: `GET /api/cards` returns every
      row and CardTable renders them all — payload and DOM both grow unbounded
      with the collection; add `limit`/`offset` (or cursor) + a "load more" or
      windowing on the table (medium; implement directly; inline — touches
      Inventory.jsx)
- [ ] Scanner paste-from-clipboard upload: accept Ctrl+V image paste on the
      stage area for desktop workflows (quick win; implement directly; inline —
      Scanner.jsx only, no open-PR overlap). **Corrected 2026-08-18:** this
      item previously claimed staging was "file-picker/camera only" and asked
      for drag-and-drop too — `Scanner.jsx` has had a working drop zone
      (`dropRef`/`onDrop`/`stageFiles`) all along, so only the paste half is
      outstanding. Note the drop zone renders only in stage 1
      (`!isStaged && !isScanned && queue.length === 0`), so paste should be
      bound to the same condition.
- [ ] Inventory filter chips: status / RC / Auto / 1st Bowman / Refractor
      toggle filters next to the existing search box — search can't express
      "all my active autos" today (quick win; implement directly; inline —
      touches Inventory.jsx + CardTable.jsx)
- [ ] QR labels for physical storage: print a sheet of QR codes (selected rows
      or a filter) that deep-link back to the card in Inventory, so a physical
      box/toploader can be matched to its row; needs a card permalink/filter
      param first (medium; implement directly; inline)
- [ ] Sheets sync failure visibility: `_sync_card_to_sheets` runs as a
      fire-and-forget background task, so a dead Google credential or quota
      error means the mirror silently drifts forever; add bounded retries plus
      an in-memory "last sync error" readout on manage-data — push-side
      complement to the on-demand drift detector above (medium; implement
      directly — no schema, in-memory state only; inline)
- [ ] "See sold comps on eBay" deep link: build the eBay sold/completed search
      URL from player/year/brand/set/card # next to the suggested price in the
      Scanner pricing panel and the Comps modal — a zero-API sanity check on
      the five-source pricing chain, especially when it quietly falls back to
      mock (quick win; implement directly; inline — touches Scanner.jsx +
      Inventory comps modal)
- [ ] Scan preset refresh to the current model lineup: PRESETS pin Sonnet 4.6 /
      Opus 4.7 and the Scanner mode cards hardcode the same names — evaluate
      newer models (e.g. Haiku 4.5 for Cost, current Sonnet/Opus for
      Balanced/Accuracy) on a sample of corrected scans before switching, and
      update analytics MODEL_PRICES + Scanner labels in the same change
      (medium; implement directly, gated on a small accuracy eval; inline —
      touches claude_vision.py, analytics.py, Scanner.jsx)
- [ ] Research cheaper extraction paths than Claude vision: vision is the only
      per-card cost that scales with the collection, and the preset item above
      only shops within the Claude lineup. Survey the alternatives on the same
      corrected-scan sample — cheaper vision models from other providers, plain
      OCR (Tesseract/PaddleOCR, or a cloud OCR) feeding a *text*-only model,
      card-database lookup by set + card # (TCDB/Sportlots/Beckett) with vision
      reduced to reading the number off the card, and a local model on the
      Railway container. Score each on per-card cost, accuracy vs. the
      Corrections table, latency, and setup burden; a hybrid is the likely
      answer (cheap path first, escalate to Claude when confidence is low or
      the user hits Re-scan). Output is a findings note in `docs/notes/`, not
      code (medium; research spike — write the note before any implementation
      item is opened; pairs with the preset-refresh item above)

## Later

- [ ] `POST /api/news/poll-now` can interleave with the background poller
      (2026-09-06 review): both run `run_poll_cycle` on separate sessions in
      the threadpool, so a manual poll landing between the background cycle's
      pending query and its `emailed_at` stamp double-sends the digest, and
      concurrent inserts of the same `tx_id` hit the unique constraint and 500
      the manual poll. Window is seconds wide with two users and the endpoint
      is curl-only — note the shape before adding any UI button for it; an
      asyncio lock around the cycle would close it (small; implement directly;
      inline — `routers/news.py` / `main.py`)
- [ ] Batch-pairing vision assist (rainy-day; explicitly deferred by owner
      2026-08-15): one cheap Haiku call per batch classifying thumbnails as
      front/back to improve the pairing proposal — Approach B in
      `docs/superpowers/specs/2026-08-15-batch-front-back-pairing-design.md`,
      <$0.01 per batch. Only worth building if the shipped order-based
      heuristic proposes wrong pairs often in real use; needs its own design
      pass (new authenticated endpoint, threadpool pattern, mock-mode
      degrade, new UsageEvent kind) (medium; **plan doc first** — new
      Anthropic call path; inline)
- [ ] Offline scan queue (PWA): stage photos while offline (IndexedDB) and
      auto-upload when connectivity returns — card shows and garage sales have
      bad signal, and the PWA manifest already exists (long-term; **plan doc
      first** — service worker, upload queue, and Scanner UI; inline)
- [ ] Inventory mutation audit trail: multi-user households share one
      inventory, but deletes / mark-solds / imports are anonymous today; add a
      small `audit_events` table (who, what, when) with a recent-activity
      readout on manage-data (medium; **plan doc first** — new table/schema;
      inline)
- [ ] Login rate limiting on `/api/auth/login`: sliding window per IP+username —
      currently unlimited attempts (quick win–medium; **plan doc first** — touches
      auth; inline). Same pass should cap the request body: login shares the
      unbounded-buffer exposure the compliance endpoint closed 2026-08-16
      (pydantic buffers the whole body before validating).
- [ ] Early request-body size reject on `/api/scan`: the 25 MB per-file cap
      (2026-08-01) stops oversized files landing in `uploads/`, but Starlette's
      multipart parser still receives/spools the whole request body before the
      cap fires — reject early on the `Content-Length` header (or add an
      ASGI-level body limit) so an oversized request is refused before upload
      completes (quick win; implement directly; inline — auto-review note on
      PR #23)
- [ ] ecdsa PYSEC-2026-1325 (transitive via python-jose, surfaced by the CI
      audit job on its first run 2026-08-01): no fixed ecdsa release exists;
      ignored in the pip-audit step since JWTs here are HS256 (ECDSA paths
      unused). Revisit when a fix ships — or swap python-jose for PyJWT, which
      drops the ecdsa dependency entirely (quick win–medium; implement
      directly; inline — touches auth)
- [x] 2026-08-02 — React Router v6 → v8 migration (with React 19): went past v7
      because 7.12.0–8.2.0 carries an unpatched RSC-CSRF advisory; 8.3.0 clears
      every react-router advisory (npm audit: 0 vulnerabilities). React 19 was
      required by v8's peer range.
- [ ] eBay OAuth + Sell API direct draft creation (replaces clipboard flow — see
      monetization notes Phase A) (large; design first — prerequisites: the
      deletion-notice signature verification item in Now/next, and note the
      `oauth/accepted` landing receives `?code=…` which lands in access logs
      today; the token exchange must address that) (2026-08-16 weekly review)
- [ ] PSA/BGS grade slab detection in vision + grade-aware pricing queries
      (large; design first — touches vision prompts + pricing chain)
- [ ] Prospect watchlist: players whose 1st Bowmans you own, cross-referenced
      with news/call-ups (medium; implement directly; inline)
- [ ] Sold-comp price history per card (store lookups over time, sparkline in
      inventory) (large; design first — new table/schema)
- [ ] Production/multi-tenant track — see
      `docs/notes/2026-07-25-production-monetization.md` (large; design first)
- [ ] Auth on `/uploads` photo serving: `/uploads/{filename}` is deliberately
      unauthenticated and relies on unguessable uuid names (capability URLs) —
      a leaked URL (browser history, pasted link) exposes the photo forever,
      and `<img>` tags can't carry the Bearer token; needs short-lived signed
      URLs or a cookie-scheme decision (medium; **plan doc first** — touches
      auth; inline)
- [ ] Restore-from-snapshot: backup download exists but there is no restore
      path — recovering a Railway volume means manual SQLite surgery; add an
      upload-snapshot flow with integrity check (`PRAGMA integrity_check` +
      expected schema) and a pre-restore safety copy (medium; **plan doc
      first** — destructive, replaces the live DB; inline)
- [ ] Soft-delete with undo: Delete is permanent behind a single confirm; add
      `deleted_at` + undo toast + periodic purge (medium; **plan doc first** —
      schema change; inline)
- [ ] Unmark-sold restores CSV-imported "unlisted" cards to "active" (PR #29
      auto-review note): a correct restore needs a `previous_status` column set
      by mark-sold — the no-schema heuristic (unlisted iff no listing attached)
      would wrongly demote saved-but-unattached active cards; fold into the
      same schema pass as soft-delete (quick win once the column exists;
      **plan doc first** — schema change; inline)
- [ ] Nightly automated backup delivery: email the SQLite snapshot (or push it to
      Drive) on a schedule — backup endpoint, scheduler, and mailer all exist
      (medium; **plan doc first** — touches 3 subsystems: scheduler, mailer,
      backup service; inline)
- [ ] Cost basis (`purchase_price`) field on cards: record what was paid so the
      planned P&L dashboard can show true realized profit instead of revenue only
      (medium; **plan doc first** — schema change; inline)
- [ ] Pricing-source telemetry: the comps chain silently falls through five
      sources to a $9.99 mock, so a blocked scraper looks like "pricing works
      but is weird" — log source/hit/latency per lookup and chart hit rates on
      Analytics, with a callout when mock share spikes (medium; **plan doc
      first** — new table/schema; inline; dataviz skill for the panel)
- [ ] Playwright E2E smoke in CI: login → scan (mocked vision) → save →
      inventory round-trip against a real dev server; unit suites can't catch
      broken page wiring like a bad api.js import (medium; implement directly;
      inline)
- [ ] Tailwind CSS 3.4 → 4.x migration: surfaced by the 2026-08-03 Monday
      dependency pass (only major-version drift left; npm/pip audits clean) —
      v4 changes the config/PostCSS pipeline, so defer until a quiet window
      (medium; implement directly; inline)

## Shipped

- [x] 2026-09-08 — `downloadBackup` and `resyncSheet` carry their own client
      timeouts (5 min and 2 min) rather than the 30s instance default from
      PR #73: both grow with the data instead of being bounded server-side,
      and an aborted backup hands the user no recovery file while the server
      finishes the snapshot anyway. Per-request overrides, the shape the scan
      already uses (integration PR for #71–#78, raised again there by Codex)
- [x] 2026-09-06 — `send_test_alert` reports `email_configured` from
      `mailer.is_configured()`, the same predicate `send_email` gates on, so
      provider credentials without recipients no longer read as a configured
      channel that then fails to send (PR #76; re-filed by PR #78 from a
      branch that predated the fix, and moved here on integration)
- [x] 2026-09-08 — CLAUDE.md and the routine prompts say how the review bots
      actually trigger: Codex reviews a PR once on open (👍 reaction = nothing
      to say) and only re-reviews a later push when told `@codex review`;
      CodeRabbit reviews only when told `@coderabbitai review`, and a trigger
      posted before a later push is voided. The rule is now: after the final
      push, post both comments. Previously the NOTE said Codex would never
      appear on the PR, which by PR #78 meant ignoring the reviewer with the
      best hit rate here (integration PR for #71–#78)
- [x] 2026-09-08 — The exact-card correction overlay is bounded by the match
      instead of by recency: `find_exact_match` filtered corrections to the
      year, took the 100 most recent, and scanned that page in Python, so once
      a year passed 100 corrections — 2024 Bowman Chrome alone can — the
      card's own correction fell out of the window and the overlay stopped
      happening, with no error and no note, worst for the earliest cards the
      user had already taught. Brand and card number now match in SQL
      (`lower(trim(...))`, the same shape `check_duplicate` uses) with no
      limit. Exercised against a real 401-correction year: the overlay lands in
      2.5 ms where it previously did not land at all
- [x] 2026-09-08 — An unparseable `updatedRange` no longer duplicates a card in
      the Sheets mirror: `sync_card`'s append branch returned `None` when it
      could not read the row number out of the API response, so the caller
      never persisted `sheets_row`, and the card's next edit appended a second
      row — and every edit after that another one, silently. The append had
      succeeded, so the row is recoverable: it is now read from the append
      response's own root-level `tableRange` (the table's extent before the
      append, so its last row + 1), never from a later probe of the sheet that
      another writer could have appended to, and returns `None` only when
      neither range is readable or the recovered row would be the header

- [x] 2026-09-07 — `storage_usage` reports what else is on the volume: it added
      `getsize(DB_PATH)` to the uploads directory and called that the
      footprint, so WAL sidecars, a backup snapshot mid-download, and a
      snapshot leaked by a disconnect (a full copy of the DB) were all
      invisible to the app's only view of volume pressure. The endpoint now
      walks the DB's directory and reports the remainder as a separate
      `other_bytes` figure with an "Other on volume" tile — separate, not
      folded into `db_bytes`, so a leak reads as a leak rather than as database
      growth. `uploads/` is pruned from the walk, symlinks are skipped rather
      than followed off-volume, and a file vanishing mid-walk is stepped over
- [x] 2026-09-07 — Orphan cleanup clears the `Scan` paths it invalidates:
      scan rows deliberately don't protect their files, so the sweep left every
      never-saved scan holding a path to a deleted photo, with nothing
      recording that it had been reclaimed rather than lost. `cleanup_uploads`
      now nulls `image_path`/`back_image_path` on exactly the scans whose files
      it removed and reports `scans_cleared`. Unblocks the scan-history browser,
      which would otherwise have rendered a broken thumbnail per swept scan
- [x] 2026-09-07 — The daily routine reports review-queue depth before its own
      output, and no longer claims three automated reviewers when one is
      running. Both halves of the 2026-08-31 process item: the queue-depth half
      (nothing merged in 3+ days, or 4+ PRs open, now leads the notification and
      tells the run to prefer the smallest useful change) and the CodeRabbit
      correction (it stopped reviewing automatically — the prompt now names the
      Claude Action as the one automatic pass and posts `@coderabbitai review`
      by hand). The step-11 half had already shipped in PR #69. **The live cloud
      prompt still has to be updated by the owner** — see the warning at the top
      of `docs/notes/daily-routine-prompt.md`
- [x] 2026-09-04 — The workflow files are checked by CI. Four workflows run
      here and two carry non-trivial embedded shell (`health.yml`'s probe,
      CI's own `changelog-guard`), but nothing validated any of it — a YAML
      typo or an unquoted expansion surfaced only when that workflow next
      fired, and for a watchdog workflow that means it silently stops
      reporting, which is indistinguishable from production being healthy. An
      `actionlint` job now checks workflow schema and expression syntax and
      runs shellcheck over every run block, via the project's own pinned image
      (which bundles shellcheck — without it the shell half no-ops silently).
      All four existing workflows were already clean, contrary to this item's
      own prediction; the first thing the job caught was the new step's name,
      which contained a colon and broke the YAML parse
- [x] 2026-09-04 — `/api/health` stops reporting the call-up poller healthy
      while every alert it produces goes undelivered. `stale` tracks only
      whether the loop is alive — the heartbeat is stamped after a failed
      cycle as deliberately as after a good one — so it stayed false through a
      mailer outage dropping every alert, and `health.yml` fails its run on
      `stale`, so the probe sailed straight past the one failure this app
      cannot afford to be quiet about. The poller now keeps the counts
      `run_poll_cycle` already computed and the endpoint reports
      `alerts_pending`, `alerts_abandoned` and `last_cycle_ok` under `poller`.
      The probe acts on them by severity: an abandoned alert (past the 48h
      window, never recovered) fails the run and self-clears when the ~2-day
      band moves past it, while held alerts and an errored cycle warn, since
      the next cycle legitimately clears both. A cycle that raises reports
      `last_cycle_ok: false` with its counts left at their last known values
      rather than zeroed — an errored cycle did not un-abandon anything. All
      seven probe outcomes were exercised against fabricated bodies, not just
      reasoned about

- [x] 2026-09-03 — Every non-scan request in `api.js` now carries a 30-second
      client-side ceiling. The axios instance had no `timeout` and today's
      earlier fix set one on `scanCard` alone; the others were failing the
      same way, more quietly — a hung `/api/pricing` left the Comps modal
      spinning with `pricingLoading` stuck true, a hung save left the Save
      button disabled with the card unsaved, and a hung `listCards` showed
      an empty inventory that looked like an empty inventory. `scanCard`'s
      longer per-request timeout still overrides the default (axios uses the
      request-level value when both are given), so the one call that
      legitimately runs longer is not capped. `formatApiError`'s existing
      timeout wording covers what the user sees on an ECONNABORTED
- [x] 2026-09-03 — Marking a card sold at an implausible price asks once
      before it lands. `MarkSoldRequest` validated only `sold_price > 0`, so
      a fat-fingered `2500` for a `$25` card was stored, mirrored to the
      Sheets price column, counted in the Inventory Revenue tile, and filed
      in the tax export — and the only way back was unmark-sold and redo. A
      hard cap would refuse a real five-figure sale, so the modal asks
      instead: when the entered price is ~20× or ~1/20 the card's listed
      price, a confirm names the ratio and the baseline. The confirm is
      latched to the price the user actually confirmed, so editing the
      field afterwards re-arms the check for the new value; a card with no
      listed price has nothing to compare against and skips the check
      entirely. Same shape as the duplicate-detection confirm and the
      bulk-orphan warning — a question at the moment of the mistake, not a
      refusal. `salePriceSanity.js` is a pure helper with a dedicated test
- [x] 2026-09-02 — An empty prospect-news result is cached like any other:
      `fetch_articles` keyed freshness on the truthiness of the payload rather
      than the timestamp beside it, so an empty result never satisfied the
      guard and both feeds were re-fetched on every request — 20s of blocked
      worker thread on a total outage, on a page that fires `GET /api/news`
      on every Scanner mount, and there is one worker. The guard now reads
      the timestamp, with its own shorter TTL for an empty result (2 min
      against 15) so a transient feed failure recovers on the next page load
      instead of blanking the panel for a quarter hour. `limit` joined the
      cache key in the same pass — it shapes the payload, so a cached top-8
      served to a caller asking for three would have been silently wrong
- [x] 2026-09-02 — Prospect Wire headlines print their source once: the
      emerald kicker above the headline and the gray byline below the summary
      both rendered `{a.source}`, so every item read "MLB.com … MLB.com · 2d
      ago". The byline now carries the age alone, via a pure helper
      (`lib/articleAge.js`) that returns an empty string for an article with
      no publish date so the byline is dropped rather than rendering a bare
      separator — and reads a feed stamped ahead of the server's clock as
      "today" instead of "-1d ago". Verified in the built app, not just by
      unit test
- [x] 2026-09-01 — Mark-sold refuses to overwrite a sale that is already
      recorded: `unmark_sold` had always guarded its side, `mark_sold` had no
      mirror, so a double-submit, a stale second tab or a re-import replaced
      the original `sold_price`/`sold_at` with no warning and no way back —
      quietly, since the row still looked like a normal sold card, and in the
      two columns the tax-year export and the Sheets "Date Sold" column read.
      The second mark is a 409; correcting a sale still works through the
      existing reversible unmark-then-remark path. No frontend change needed —
      `MarkSoldModal` already surfaces a server rejection
- [x] 2026-09-01 — The CSV importer is capped in bytes as well as rows:
      `import_csv` read, decoded and parsed the whole file — three copies
      resident — before `MAX_IMPORT_ROWS` could reject it, so the row cap
      protected the database and nothing else. It now reads in 1 MB chunks
      against a 10 MB cap and refuses with a 413, the shape `/api/scan` has
      used since the magic-byte work. Honest about its limit: Starlette has
      already spooled the body by the time the handler runs, so this bounds
      our in-process copies rather than the transfer — the ASGI-level
      early-reject item stays open in Later
- [x] 2026-09-01 — A CSV field over the parser's 128 KB limit is a 422, not a
      500: `csv.reader` raised and nothing caught it, so a bad file reached the
      client as a blank 500 that reads as a broken app. Found while testing the
      byte cap above, and reachable well under it. The general "nothing pins
      that rejections stay typed" case is now its own item in Now/next
- [x] 2026-08-26 — Production health is watched from somewhere that can reach
      it: a scheduled `health.yml` workflow probes `/api/health` every 3 hours
      and fails the run on a non-200, an unreachable or non-JSON response, an
      `ok`/`db` false, or a stale call-up poller. Deploy lag (a `revision` that
      does not match main HEAD) warns rather than fails, so a merge does not
      flap the check red while Railway is still building. The daily routine's
      own ping stays, but it runs from a sandbox whose egress proxy 403s the
      Railway host, so the check it was meant to perform had simply been
      silently skipped — and a missing sentence in a report nobody diffs is a
      worse failure shape than a red run
- [x] 2026-08-26 — The cheat-sheet teaches only the newest correction per
      field: `build_cheatsheet` deduped on the rendered rule string, so
      reversing a correction left both halves in every later scan prompt with
      nothing marking which one still stood. Dedup is now `(context, field)`
      over newest-first rows, which also stops one much-corrected field from
      eating the 30-rule budget. `created_at` ties now break on `id` in both
      `build_cheatsheet` and `find_exact_match`, so "newest wins" is
      deterministic rather than left to SQLite's row order
- [x] 2026-08-27 — A failing mailer no longer swallows call-up alerts in
      silence: `run_poll_cycle` logs and fires an out-of-band owner alert the
      moment a digest cannot be sent, and counts the alertable events that pass
      the 48h retry window unsent. Both counts (`pending`, `abandoned`) come
      back from the cycle and through `POST /api/news/poll-now`. The alert goes
      via the ntfy push `billing_alerts` already had wired — the app's own
      email is the thing that is broken — on its own throttle clock, and says
      whether email is unconfigured or configured-and-failing, because those
      look identical from outside and have different fixes. No schema change:
      the abandoned figure is a rolling count over a bounded 48–96h band rather
      than a per-row stamp
- [x] 2026-08-27 — The Scanner stops saving the pricing chain's $9.99 mock as a
      real suggested price: `fetchPricing` wrote any truthy `suggested_price`
      into the review form without looking at `source`, so a card priced by a
      fully failed lookup was saved, mirrored to the Sheet and pasted into eBay
      at a number no sale supports — the common case on Railway, where the
      scrapers 403 from a datacenter IP (reproduced against a running app).
      Both pricing surfaces now share one tested helper
      (`frontend/src/lib/pricing.js`); the Inventory modal had always refused a
      mock, and the surface that disagreed was the one whose value persists
- [x] 2026-08-31 — A sale can no longer be dated in the future: nothing bounded
      `sold_at` at all, so a mistyped year was accepted in silence and became
      permanent furniture — it joins the sold-years picker forever, sorts to
      the end of every tax export, and the only way out is unmark-sold and
      redo. The picker is capped at the local date it already defaults to, the
      server rejects anything more than a day ahead of its own clock (slack for
      the two clocks disagreeing, not for post-dating), and the CSV importer
      applies the same bound to `Date Sold`, dropping a future value with a
      per-row warning. The check runs on the value as it will be *stored*:
      SQLite drops tzinfo without converting, so an aware `+14:00` instant
      validated as the moment it really is would then be stored as its wall
      clock, a day past the bound that admitted it. Backdating stays unbounded.
      The mark-sold modal also renders a rejected confirm instead of dropping
      it — the failed promise used to leave the dialog open and unchanged, as
      though the click had not happened. Verified against a running app: 2062
      refused, the modal's real payload stored as noon UTC on the picked day, a
      400-day-old sale still accepted
- [x] 2026-08-31 — `suggested_price` has the `ge=0` floor `listed_price` always
      had: the two are the same kind of value read by the same consumers (the
      Sheets price column, the eBay listing text, the inventory value tile) and
      only one was guarded. Both floors are stated on the input models only —
      FastAPI validates responses too, so inheriting them onto `CardOut` would
      turn one legacy row saved before the floor existed into a 500 on
      `GET /api/cards`, the whole inventory unreadable because one price is
      wrong. A test pins that split and fails (with the 500) if the floors are
      inherited
- [x] 2026-08-28 — A hung scan no longer wedges the batch queue: `scanCard`
      carries a 5-minute client timeout (above the server's own 150s
      subscription ceiling, so it can only fire on a scan that was never coming
      back) and clearing the queue aborts the request in flight, which is what
      finally releases the single-flight guard. Verified against a running app
      with `/api/scan` held open: before the fix, a cleared queue left every
      later batch at "waiting…" forever; after it, the next batch scans
      normally. A timed-out request now says the server may have finished the
      work anyway rather than reporting a bare "Scan failed."
- [x] 2026-08-28 — Reclaimable photos are reported beside the storage figures
      on the Analytics manage-data panel, instead of only behind the button
      that offers to delete them: nothing said there was anything to sweep, so
      the cleanup tool ran when someone thought to look. The "this is most of
      the photos on the server" guard — the one that catches a CSV restore
      having orphaned the whole photo library — now warns on the tile, before
      the destructive press rather than during it, and is a tested pure helper
      shared with the confirmation dialog
- [x] 2026-08-25 — eBay fee + net-proceeds estimate in the Comps modal and the
      Mark as Sold dialog: both showed gross only, so a $10 comp read as $10
      when the seller receives $8.37. `lib/fees.js` holds the schedule — both
      halves tiered, 13.25% to $7,500 then 2.35% on the portion above, $0.30
      per order at or under $10 and $0.40 above — and the estimate; Mark as
      Sold tracks the price as it is typed, a loss below ~$0.35 renders as a
      negative net rather than being clamped to zero, and an unusable price
      shows the comps list's em dash instead of a plausible `$0.00`. Verified
      in a browser, not just in tests. The tiering was a CodeRabbit catch on
      the PR: the first cut charged a flat $0.30, understating the fee on every
      card over $10. Two follow-ups are open above: pricing *to* a target net,
      and making the schedule settable on the Railway image.
- [x] 2026-08-24 — Condition is a dropdown of canonical grades instead of a
      free-text box: the field defaulted to "NM" but accepted anything, from
      the form, from vision extraction, and from CSV import, so "NM", `"nm "`
      and "Near Mint" all accumulated as distinct values in the inventory, the
      Sheets `Condition` column and the sold-cards tax export. `CardForm` now
      renders `RAW / GEM-MT / NM-MT / NM / EX / VG / POOR` and folds a
      recognized spelling to its canonical grade on receipt, so a scanned
      "Near Mint" arrives as NM; the CSV importer folds the same way, which is
      where other people's spellings come in. `normalize_condition` returns
      anything it does not recognize **unchanged** — "LP" and "PSA 10" survive
      and are offered as their own dropdown option (a `<select>` with no
      matching option renders the first one, which would have rewritten a
      graded card to RAW on the next save), "Mint" and "PR" are deliberately
      not folded because mapping a value onto a *different* grade restates
      what the seller is claiming, and "-NM" keeps its leading `-` so the CSV
      formula escape and the export/import round-trip still hold. Backend is
      the source of truth (`services/card_fields.py`), the frontend mirrors it,
      and both suites read `backend/tests/fixtures/condition_cases.json`.
      `POST /api/cards` deliberately does not fold — that path stores strings
      verbatim, which is what the formula-injection tests pin. (PR #57)
- [x] 2026-08-19 — Pricing sources run concurrently, resolved in preference
      order: the chain expressed preference, not dependency, but charged the
      user the sum of four timeouts (15 + 20 + 15 + 15s) — and on Railway,
      where the scrapers 403, the common case was the worst case on every
      card. Measured 65s → 20s for an all-fail lookup. Resolution walks the
      preference order rather than taking the first finisher, and
      `PRICING_DEADLINE_SECONDS` caps the whole lookup on our own wall clock.
      First tests for this endpoint (`test_pricing_chain.py`, 12 cases) —
      written against the serial code first so they pin the contract rather
      than the refactor. Implements
      `docs/superpowers/specs/2026-08-18-pricing-chain-parallel-design.md`.
- [x] 2026-08-21 — Backup snapshots stage on the volume, not container-local
      disk: `download_backup` called `tempfile.mkstemp()` with no directory,
      which on Railway is the container's ephemeral `/tmp`, while the database
      lives on the mounted volume — so `VACUUM INTO` wrote a full copy of the
      database onto the one disk sized for neither it nor its growth, and the
      app's only recovery tool got less reliable as the data it protects got
      more valuable. Snapshots now stage beside the database; out-of-space
      returns 507 and says so (SQLite reports it in a message, the OS as
      ENOSPC — both read the same now), and every other failure still returns
      the generic 500 rather than guessing. Each request also sweeps snapshots
      older than an hour first: the unlink runs in a `BackgroundTask` that a
      client disconnect skips, and on the volume that leak is permanent and
      invisible to the storage tiles. Verified end to end against a running
      app — staged beside the DB, gone after the response, and a readable
      SQLite file at the other end.
- [x] 2026-08-21 — File downloads stop racing the browser: all three
      authenticated downloads revoked the object URL in the same tick as
      `a.click()`, but a click only *schedules* the download and the browser
      reads the `blob:` URL after the current task ends, so it could already be
      revoked — a download that silently does nothing, most reliably on
      Firefox. The anchor was never in the document either. One shared helper
      (`frontend/src/lib/download.js`) now owns the object-URL lifetime, uses
      the server's `Content-Disposition` filename (the backup's carries the
      time, from the server's clock, instead of a UTC date from the browser's),
      and re-reads a blob error body as JSON so the API's `detail` survives to
      the screen — without which the new out-of-space message would have been
      swallowed by "Backup failed."
- [x] 2026-08-21 — Preset models are priced explicitly: nothing connected
      `claude_vision.PRESETS` to `analytics.MODEL_PRICES`, so a preset refresh
      that changed one alone would fall through to `_DEFAULT_PRICE`. That
      fallback is right for a model nobody chose — overcounting is the safe
      direction — and wrong for a preset: the Cost preset exists to be cheaper,
      and priced at Opus rates its whole reason for existing is invisible in
      the one report that would show it. Now a test failure instead of a silent
      67% overstatement.
- [x] 2026-08-20 — Listing text says a card has no price instead of offering
      `$0.00`: `ebay_listing_text` fell back to `suggested_price or 0`, so a
      card saved before the comps lookup resolved put `PRICE:\n$0.00` on the
      clipboard — and that block is pasted straight into eBay's sell form. A
      zero reads as a filled-in field rather than a missing one, so unlike a
      wrong player name it is not caught on review. The endpoint now returns
      `price: null` plus a `has_price` flag (non-positive counts as unset), and
      both copy paths — the Scanner save toast and Inventory's Copy Text /
      Open eBay — say the card has no price yet and point at Comps.
- [x] 2026-08-20 — Mark-sold picker pre-fills the local date, not the UTC one:
      the default came from `new Date().toISOString().slice(0, 10)`, so from
      8pm EDT onward it offered **tomorrow** and an evening sale was stamped a
      day late; submit had the mirror-image problem, since a bare
      `YYYY-MM-DD` parses as UTC midnight, a boundary readers west of UTC
      cross. The default now comes from local calendar parts and the submitted
      instant is anchored at noon UTC on the picked day, which keeps the picked
      date intact for every consumer that reads the stored datetime's date part
      (Sheets "Date Sold", the tax-year export, days-to-sell). Tested pure
      helper in `frontend/src/lib/soldDate.js`; verified in a real browser with
      the clock at 9pm EDT. Deliberately only the mark-sold half — the
      analytics day-boundary item stays design-first.
- [x] 2026-08-19 — eBay titles truncate on unit boundaries instead of mid-token:
      an over-length title was cut with `title[:80]`, which sliced wherever the
      80th character landed — turning a `/99` serial into `/9`, `REFRACTOR`
      into `REFRACTO` and `1ST BOWMAN` into a bare `1ST`. Those aren't shorter
      titles, they're wrong ones: a `/9` listing advertises a card the seller
      doesn't own. `build_title` now assembles the title from units (one per
      word for free text, one per flag even when the flag contains a space) and
      drops any that doesn't fit whole, stopping at the first rather than
      skipping to a shorter one so the deliberate flag priority can't be
      reordered. A single unit longer than the cap still hard-slices — there is
      no boundary to fall back to. The card number is one unit too, so
      `#US 44` can't become `#US`. Three-file change per invariant #7 with
      regenerated fixtures; the form preview strikes through the dropped tail
      as before, and still counts the full length against the limit — now in
      code points, so an emoji no longer measures 2 in the preview and 1 in
      the backend (CodeRabbit).
- [x] 2026-08-19 — Sold-cards tax-year CSV export
      (`GET /api/cards/export-sold.csv?year=`, or no `year` for every recorded
      sale — offered as "All years" in the picker and named
      `cardlister-sold-all.csv` rather than `-2026.csv` so the two can't be
      confused once downloaded; plus `GET /api/cards/sold-years` so the picker
      offers only years that have sales). Sold rows already left
      in the full inventory dump, but mixed with everything else and with no
      sale date to sort on, so preparing a return meant hand-filtering the
      whole collection. Ordered oldest-first with its own column set —
      deliberately not `SHEET_HEADERS`, which is the append-only mirror
      contract and would drag every future mirror column into a tax report.
      Same formula-injection escaping as the inventory export. Lives on the
      Analytics manage-data panel beside the backup and import tools.
- [x] 2026-08-18 — Batch queue retry + clear-queue confirm: an errored batch
      item was a one-way exit, so one transient failure in a twenty-card batch
      meant clearing the queue and re-staging that photo by hand; errored items
      now carry a Retry that sends them back to `queued`. "Clear queue" now
      confirms when the queue holds scanned-but-unsaved (`ready`/`scanning`)
      cards, counting those separately from still-waiting ones because only the
      paid scans are unrecoverable. Logic lives in a tested
      `frontend/src/lib/scanQueue.js`.
- [x] 2026-08-18 — Comp spread readout: the suggested price is a median of up
      to ten comps, and the UI showed the number with no sense of the
      distribution behind it. The review form and the inventory Comps modal now
      caption it with comp count and low–high range and warn when the top comp
      is ≥3× the bottom — the signature of the parallel/variant contamination
      that the "Comps accuracy" item above fixes properly. Deliberately does not
      compute a rival median. Tested pure helper in
      `frontend/src/lib/compStats.js`.
- [x] 2026-08-17 — Sheets mirror integrity: `resync_all` is now a
      clear-then-rewrite of the Inventory tab (idempotent — running it twice
      produces the same sheet, where the old per-card append loop added a
      complete second copy of the inventory each press), `delete_card` blanks
      its row in place, and CSV import says plainly that imported cards need a
      resync to reach the mirror. Every Sheet write is serialized behind a
      module-level lock, with `sync_card` re-reading its `sheets_row` inside it
      and the delete-path blank checking row *ownership*, so a save or delete
      racing a rewrite can neither be dropped nor erase a live card's row. The
      resync button and its destructive-action warning are new — the endpoint
      previously had no UI at all. Implements
      `docs/superpowers/plans/2026-08-17-sheets-mirror-integrity.md` (PR #46).
- [x] 2026-08-17 — `/uploads/{filename}` re-checks that the resolved path is
      inside the uploads volume: `Path().name` blocked traversal but not a
      symlink pointing out of the volume, which was served 200 with its
      contents (found via a CodeQL path-injection alert on the route)
- [x] 2026-08-17 — `/uploads/%2e` 404s instead of 500ing: an encoded dot segment
      has an empty `Path().name`, so it resolved to the uploads directory and
      raised inside `FileResponse` (Monday security pass)
- [x] 2026-08-17 — CSV export escape widened to catch formulas hidden behind a
      leading tab/CR/space/NUL, which spreadsheets discard before deciding a
      cell is a formula (Monday security pass; import unescape kept symmetric)
- [x] 2026-08-17 — HEAD support on `/api/health` and `/uploads/{filename}`:
      `@app.get` registers GET only, so HEAD probes fell through to the static
      mount and 404'd whether the app was healthy or not, defeating the deep
      health check's 503 for the status-code-only monitors that default to HEAD
- [x] 2026-08-17 — Filter-aware inventory stat tiles: totals describe the rows
      the table is showing, with an "of N overall" caption on every narrowed
      tile and a badge naming the matching row count
- [x] 2026-08-17 — CI fail-open guards dropped: backend and frontend test steps
      run unconditionally, so a moved test directory or a renamed test file
      can't skip a whole suite while the job stays green

- [x] 2026-08-16 — Cache headers for the built frontend: `index.html` is
      `no-cache` (a cached shell could outlive its bundles across a deploy and
      white-screen), Vite's content-hashed `/assets/*` bundles are immutable
      like `/uploads` (weekly deep review PR)
- [x] 2026-08-16 — Railway production URL recorded in README (was a
      placeholder; the daily-routine doc already pinged it)

- [x] 2026-08-14 — SPA deep-link fallback: hard loads of /inventory, /analytics
      and friends served the app shell instead of a 404, with `api/`,
      `uploads/`, and `assets/` prefixes keeping their real 404s
- [x] 2026-08-14 — Quantity-aware inventory stats: Total Cards / Listed / Sold
      count copies and Est. Active Value multiplies by quantity, with a
      "N rows" caption when rows and copies differ (revenue stays per-row)
- [x] 2026-08-14 — Immutable cache headers on `/uploads` (uuid-hex names never
      change content, so `public, max-age=31536000, immutable`)

- [x] 2026-08-06 — Storage usage tiles on Analytics manage-data: DB file size +
      photo count/bytes via `GET /api/analytics/storage`, refreshed after
      import/cleanup
- [x] 2026-08-06 — Scanner pricing race fix: comps lookups carry a monotonic id
      so a stale response can't overwrite the currently reviewed card's
      comps/suggested price (was listed under Later as "Scanner batch-review
      race")

- [x] 2026-08-05 — Parallel / Serial # / Refractor columns in CSV export +
      Sheets mirror (appended after 1st Bowman; importer already read them,
      so the round-trip now preserves all three)
- [x] 2026-08-05 — CSV formula-injection escaping on export (leading `'` for
      `=` `+` `-` `@` cells, stripped back out on import; Sheets mirror
      unaffected — RAW input)

- [x] 2026-08-04 — Magic-byte validation of scan uploads (415 on unrecognized
      content before write; stored suffix derived from sniffed content, not the
      client filename)
- [x] 2026-08-04 — Router-wide auth sweep test: every `/api` route except
      login/health must 401 without a token (walks the OpenAPI schema, with a
      self-check that the sweep is non-empty)

- [x] 2026-08-03 — Unmark-sold undo: `POST /api/cards/{id}/unmark-sold` restores
      status to active and clears sold_price/sold_at, with confirm-gated
      "Unmark Sold" button on sold rows
- [x] 2026-08-03 — Row-level "Copy Text" button: quiet clipboard-only listing
      text on non-sold rows (transient Copied ✓, prompt fallback)

- [x] 2026-08-01 — 25 MB streamed per-file cap on `/api/scan` uploads (413 over
      limit, no partial file left behind; closes the unbounded-upload hardening
      note from the 2026-08-01 code review)
- [x] 2026-08-01 — Non-blocking dependency-audit CI job (`pip-audit` + `npm audit`
      high+) so advisories surface between Monday deep passes
- [x] 2026-08-01 — Code review: eBay listing URL http(s)-only validation (server +
      client + defensive render guard) — closed a stored-XSS/token-theft path via
      `javascript:` URLs; PATCH no longer accepts `status` directly; mark-sold and
      listed-price now reject non-positive values; call-up matches exclude sold cards

- [x] 2026-07-30 — Bulk CSV inventory import (export layout round-trip, header-name
      column mapping, per-row skip reasons, https-only eBay URLs)
- [x] 2026-07-30 — Orphaned photo cleanup with preview + confirm on Analytics
      manage-data (unreferenced by any card, 48h grace window)

- [x] 2026-07-29 — Deep `/api/health` (DB ping, revision, poller heartbeat, 503 on DB failure)
- [x] 2026-07-29 — Client-side photo downscale to ≤2000px before scan upload (server's largest preset — no accuracy loss; faster mobile uploads, smaller volume)
- [x] 2026-07-28 — Sortable inventory columns + multi-field search (player, team, brand, set, card #, parallel, notes, year)
- [x] 2026-07-28 — Server-side https-only validation of `ebay_listing_url` (2026-07-27 security-review hardening note)
- [x] 2026-07-27 — Inventory image lightbox (front/back full-size overlay)
- [x] 2026-07-27 — Vitest + shared JSON parity table for the eBay title mirror; CI runs frontend tests

- [x] 2026-07-26 — One-click SQLite backup download (VACUUM INTO snapshot) on Analytics
- [x] 2026-07-26 — Live eBay title preview with 80-char truncation warning in the card form
- [x] 2026-07-25 — Subscription-billed scan fallback + credits-exhausted alerts (email + ntfy phone push); Actions workflows moved to subscription auth
- [x] 2026-07-25 — Duplicate detection at save time with "increase count" confirm pop-up
- [x] 2026-07-25 — Inventory CSV export (Sheets column layout)
- [x] 2026-07-25 — Mobile camera capture + PWA manifest/icon
- [x] 2026-07-25 — Per-row "Comps" re-check modal with one-click reprice
- [x] 2026-07-10 — 1st Bowman flag end-to-end (PR #13)
- [x] 2026-07-09 — Call-up alerts, prospect news, analytics manage-data (PRs #10–#12)
- [x] 2026-07-09 — Quantity, front/back scan, refractor detection, learning, batch queue
