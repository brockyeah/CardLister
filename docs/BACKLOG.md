# CardLister Backlog

Persistent idea ledger, maintained by the daily review routine. One line per idea;
move items to **Shipped** (with date) instead of deleting so runs don't re-propose them.

## Now / next

- [ ] Call-up alerts are silently abandoned after 48 hours of mailer failure
      (2026-08-25 review): `run_poll_cycle` collects un-emailed events with
      `CallupEvent.created_at >= cutoff`, cutoff = now − `ALERT_MAX_AGE_HOURS`
      (48), and only stamps `emailed_at` when `mailer.send_email` returns
      true. So a failing mailer — wrong SMTP credentials after a Railway env
      edit, a provider outage, a rate limit — retries the same events every
      cycle until they cross 48h, at which point they leave the pending window
      **permanently, unemailed, with nothing recording that an alert was
      dropped**. Being told a prospect got called up while you hold his 1st
      Bowman is the feature this app was built around, and this is the one
      failure mode where it stays quiet and looks healthy: `/api/health`
      reports the poller fresh, because the heartbeat is stamped after a
      failure too. The window itself is right (it bounds retries); what's
      missing is the record. Count events aging out unemailed and surface it —
      log + the existing ntfy `billing_alerts` push is the cheapest version,
      and it reuses what's already wired (quick win; implement directly;
      inline — `services/callups.py` plus a test that fails the mailer and
      advances the clock past the cutoff)
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
      same day): `lib/fees.js` reads `VITE_EBAY_FEE_RATE` /
      `VITE_EBAY_FEE_FIXED`, but Vite inlines those at **build** time and the
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
- [ ] `find_exact_match` silently stops applying old corrections as a year
      fills up (found 2026-08-24, re-filed 2026-08-25 — one bug, two entries,
      merged here): `services/learning.py:99-110` filters
      `Correction.year == year`, orders by `created_at desc`, `limit(100)`,
      then linear-scans that page in Python for a brand + card-number match.
      A baseball inventory concentrates hard in a few years — 2023 Bowman
      Chrome alone can carry hundreds of corrections — so once one year passes
      100 rows, a correction the user made for that exact card falls out of the
      window and the overlay just stops happening. No error, no note: the
      learning loop quietly degrades for the earliest cards, which are exactly
      the ones the user is most likely to have already taught, and it gets
      worse the more the tool is used.
      **Fix: move the match into SQL and drop the limit** — both fields are
      already normalized on write (`_norm` casefolds and strips), so a
      `func.lower(func.trim(...))` filter works directly, the way
      `check_duplicate` already does it in `routers/cards.py`. Bounded by the
      match, not by recency.
      A `match_key` column written at record time was the other proposal and is
      **rejected**: it is a schema change on an existing table, so it needs a
      `_COLUMN_MIGRATIONS` entry plus a backfill whose normalization has to
      reproduce `_norm` exactly or old corrections stay invisible anyway — all
      to solve something the existing normalized columns already answer
      (quick win–medium; implement directly; inline — needs a test with >100
      corrections in one year pinning that the 101st still matches)
- [ ] Orphaned uploads accumulate with nothing reporting them (2026-08-25
      review): `/api/scan` writes the upload to the volume before extraction
      and only records a `Scan` row when the extraction both succeeded and was
      real (`not is_mock and not error`), so every failed or mock scan leaves a
      file on the Railway volume referenced by nothing. Deleting it there is
      wrong — the review form still previews that image — and the cleanup tool
      shipped 2026-07-30 can sweep them, but nothing tells anyone there is
      something to sweep, so it only runs when someone thinks to look. The
      storage tiles on Analytics manage-data already report DB and uploads
      size; add orphan count and bytes beside them so the existing tool gets
      used before the volume fills (quick win; implement directly; inline —
      reuses the cleanup endpoint's own preview query)
- [ ] The cheat-sheet teaches the model both halves of a reversed correction
      (2026-08-24 review): `build_cheatsheet` (`services/learning.py:74-87`)
      dedups on the **whole rendered rule string**, so two corrections of the
      same field in the same set produce two different strings and both survive
      into the prompt. Correct "Chrome" → "Chrome Prospects" today and
      "Chrome Prospects" → "Chrome" next week — because the first fix was
      wrong — and every subsequent scan carries a pair of contradictory
      instructions for the same field, with nothing marking the newer one as
      the one that stands. Rows are already ordered `created_at desc`, so the
      fix is a one-line change of the dedup key to `(context, field)`: the
      first rule seen for a field is the newest and the only one that should
      be taught. It also stops a much-corrected field from eating the 30-rule
      budget and crowding out every other lesson, and it gets *worse* the
      longer the app is used — the contradiction rate rises with the
      correction count (quick win; implement directly; inline — learning.py
      plus a test that a reversed correction yields one rule, not two)
- [ ] A failed row-number parse duplicates a card in the Sheets mirror
      (2026-08-24 review): `sync_card`'s append branch
      (`services/google_sheets.py:292-306`) writes the row, then parses
      `updates.updatedRange` to learn which row it landed on, and returns
      `None` if that parse raises. `_sync_card_to_sheets` only persists
      `sheets_row` when a row comes back, so the card keeps a NULL
      `sheets_row` — and its **next** edit takes the append branch again,
      adding a second row for the same card while the first stays behind.
      Every later edit appends again. Nothing raises, nothing logs, and the
      inventory silently grows copies in the sheet. The append itself
      succeeded, so the recovery is to find the row rather than give up:
      fall back to `_last_used_row` (already written, already called under
      the same lock by `rewrite_all_rows`) when the range is unparseable.
      Note the resync repair tool fixes the symptom but only when someone
      notices (medium; implement directly; inline — needs a fake whose append
      returns a malformed `updatedRange`)
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
- [ ] Scan requests have no client timeout, and a hung one wedges the batch
      queue unrecoverably (2026-08-23 weekly review): `api.js` sets no axios
      timeout, so a request that never settles leaves the item `scanning`
      forever — the one status with no Retry — and `processingRef` stays
      `true`, so every queued item waits forever and even Clear-queue + a new
      batch stays stuck at "waiting…" because nothing resets the ref. Add a
      generous timeout to `scanCard` (must exceed `SUBSCRIPTION_SCAN_TIMEOUT`
      = 150s plus headroom, e.g. 180s, so a slow-but-legitimate paid scan is
      never aborted client-side while the server still bills it) and reset
      `processingRef` on the way out (quick win–medium; implement directly;
      inline — api.js + Scanner.jsx)
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
- [ ] `storage_usage` under-reports the volume it exists to watch (2026-08-21
      review, noticed while moving backup snapshots onto that volume): the
      panel adds `os.path.getsize(DB_PATH)` to the uploads directory and calls
      that the footprint, so anything else on the volume is invisible — the
      SQLite `-wal`/`-shm` sidecars if journal mode is ever changed, a backup
      snapshot mid-download, and a snapshot leaked by a client that
      disconnected (bounded to an hour by the new sweep, but a full copy of the
      database while it lasts). The tiles are the only view of volume pressure
      the app has, and the number they show is the one that will be believed
      when Railway starts refusing writes. Walk the DB's directory instead of
      naming one file, and report the remainder as a third figure rather than
      folding it into `db_bytes`, so a growing "other" is legible rather than
      looking like database growth (quick win; implement directly; inline —
      `routers/analytics.py` plus the Analytics tile)
- [ ] `suggested_price` has no `ge=0` floor, but `listed_price` does
      (2026-08-21 review): `CardBase`/`CardUpdate` validate
      `listed_price: Optional[float] = Field(default=None, ge=0)` and leave
      `suggested_price` a bare `Optional[float]`, so a negative comp median —
      or a hand-crafted PATCH — is stored and mirrored to the Sheet's price
      column. The listing-text endpoint now treats a non-positive price as
      unset, which contains the worst of it, but the two fields are the same
      kind of value read by the same consumers and only one is guarded. Add the
      floor to both models and a validation test alongside
      `test_card_validation.py` (quick win; implement directly; inline)
- [ ] Orphan cleanup leaves `Scan.image_path` pointing at a file it deleted
      (2026-08-21 review): `_orphaned_uploads` deliberately lets scan rows go
      unprotected — an unsaved scan's photo is exactly the disk growth the tool
      reclaims — but the `Scan` row survives with a path to nothing. Harmless
      today, because nothing renders scan photos; it stops being harmless the
      moment the "Scan history browser" item below ships, which would show a
      broken thumbnail for every scan older than the 48h grace window that was
      never saved. Null the two path columns on the scans whose files the
      cleanup removed, in the same call, so the record stays honest about what
      it still has and the history browser can say "photo reclaimed" instead of
      rendering a hole (quick win; implement directly; inline —
      `routers/analytics.py:cleanup_uploads` plus a test)
- [ ] Scanner treats the $9.99 pricing mock as a real suggested price
      (2026-08-20 review): `fetchPricing` in `Scanner.jsx` writes
      `pricing.suggested_price` into the form whenever it is truthy, with no
      look at `pricing.source` — so when every comp source fails and the chain
      falls through to its `MOCK_PRICE` last resort, the card is saved carrying
      $9.99 as if a median of ten sales had produced it. The Inventory Comps
      modal already refuses exactly this (`const suggested = result?.source
      !== 'mock' ? result?.suggested_price : null`), so the two pricing surfaces
      disagree about whether a mock counts, and the one that disagrees is the
      one whose value gets *persisted*. On Railway this is the common case, not
      the edge: CLAUDE.md notes the scrapers routinely 403 from a datacenter IP.
      It also defeats the 2026-08-20 listing-text fix — a mocked $9.99 makes
      `has_price` true, so the seller gets a confident wrong price where they
      would otherwise be told the card has no price yet. Skip the write when
      the source is mock and let the field stay empty, matching the modal
      (quick win; implement directly; inline — Scanner.jsx only)
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
- [ ] Production health monitoring does not depend on the routine's network
      policy (2026-08-20 review, hit during that run): Phase 1 of the daily
      routine pings
      `https://cardlister-production.up.railway.app/api/health`, and from the
      scheduled cloud sandbox that request is refused by the egress proxy
      (403 to CONNECT), so the health check silently cannot run — the one step
      of the routine meant to notice a failed deploy or a stale call-up poller.
      Nothing is wrong with the app; the check just has no route to it. Move
      the ping into a scheduled GitHub Actions workflow that fails the run when
      `ok`/`db` is false or the poller is stale, so health is watched from
      somewhere that can reach it and a failure shows up as a red run rather
      than a missing sentence in a report. Keep the routine's own attempt —
      when it works it is free — but have it report the block explicitly rather
      than the result (quick win; implement directly; inline — new workflow
      plus a note in `docs/notes/daily-routine-prompt.md`)
- [ ] Mark-sold accepts a date in the future (2026-08-20 review, found while
      fixing the UTC default): the picker carries no `max`, and
      `MarkSoldRequest` validates only `sold_price > 0` — nothing bounds
      `sold_at` at all. A mistyped year (2062) is accepted silently, and from
      there it is permanent furniture: it appears in the `sold-years` picker
      forever, it sorts to the end of every tax export, and the only way back
      is unmark-sold and redo. Cap the input at today's local date and reject a
      `sold_at` more than a day ahead server-side (a day of slack, since the
      client submits an instant and the two clocks need not agree). Pair it
      with a floor on how far back a sale can be dated only if the owner wants
      one — backdating a sale is legitimate, post-dating one is not (quick win;
      implement directly; inline — Inventory.jsx plus a schema validator and
      its test)
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
- [ ] Mark-sold date is computed in UTC, so it is off by a day for part of the
      day: `MarkSoldModal` defaults the picker to `new Date().toISOString()
      .slice(0, 10)` — the *UTC* date — so from 8pm EDT onward it pre-fills
      **tomorrow**, and a card sold in the evening gets stamped a day late
      unless the user notices. On submit it does `new Date(date).toISOString()`,
      and a bare `YYYY-MM-DD` parses as UTC midnight per spec, which renders as
      the *previous* day anywhere west of UTC. Sold dates feed the Sheets "Date
      Sold" column, the now-shipped tax-year export (2026-08-19), and
      days-to-sell analytics, so the error propagates — a late-evening Dec 31
      sale lands in the wrong year's tax file. The backend fallbacks
      (`mark_sold`'s `datetime.utcnow()` and the CSV import's stamp) carry the
      same skew. Fix by composing the default from local date parts
      and submitting local noon, in a tested pure helper (quick win; implement
      directly; inline — Inventory.jsx plus a lib function)
      Sold" column, the planned tax-year export, and days-to-sell analytics, so
      the error propagates. Fix by composing the default from local date parts
      and submitting the picked `YYYY-MM-DD` string as-is — the server owns
      the date semantics (quick win; implement directly; inline —
      Inventory.jsx plus a lib function) — **do not implement separately:
      covered as step 6 of
      `docs/superpowers/plans/2026-08-22-local-timezone.md`**, and the
      backend half (aware-datetime normalization at the boundary) is step 3
      there
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
      scraper block pins $9.99 to a card for the whole TTL). **Sequence this
      after or alongside the parallel fan-out item below — both restructure
      the same function, and landing them separately means resolving the same
      conflict twice** (medium; implement directly; inline)
- [ ] Analytics day boundaries are UTC, so the owner's evening scans land on
      the wrong day (2026-08-19 review): `_range_start` builds the `today` and
      `month` windows from `datetime.utcnow()`, and `by_day` buckets on
      `ev.created_at.strftime("%Y-%m-%d")` — both UTC. East-coast, that means
      the day rolls over at 8pm EDT: a card scanned at 9pm appears on
      *tomorrow's* bar in the daily cost chart, and the "Today" filter after
      8pm reports a window that started yesterday evening. On the first of the
      month the "This month" total is wrong for four hours. Same root cause as
      the mark-sold UTC item above, and the fix should be the same one applied
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
      mark-sold item above, the Sheets date columns, and the tax-year export
      in one pass. **Awaiting owner approval on the three decisions listed at
      the end of the plan doc.**
- [ ] Listing text offers `$0.00` for a card with no price (2026-08-19
      review): `ebay_listing_text` computes
      `card.listed_price if not None else (card.suggested_price or 0)`, so a
      card saved before pricing resolved yields `PRICE:\n$0.00` in the
      clipboard block — pasted straight into eBay's sell form, which is the
      entire point of the feature. `$0.00` is not a plausible typo a seller
      catches on review the way a wrong player name is; it reads as a filled-in
      field. Either omit the price section and say the card has no price yet,
      or keep it but label it, and have the Scanner/Inventory copy buttons
      surface that (quick win; implement directly; inline — `routers/ebay.py`
      plus its test)
- [ ] Backup snapshots are written to container-local disk, not the volume
      (2026-08-19 review): `download_backup` calls `tempfile.mkstemp()`, which
      lands in the container's `/tmp` rather than on the Railway volume that
      holds the database. `VACUUM INTO` writes a full copy of the DB there, so
      the one recovery tool the app has gets less reliable exactly as the
      database it protects grows, and it fails with a bare 500 ("Backup
      snapshot failed") that says nothing about disk. Point the temp file at
      the DB's own directory (guaranteed to be sized for at least one copy of
      it) or honour a `TMPDIR`, and distinguish "out of space" from "snapshot
      failed" in the error. Note the export must still be deleted on the way
      out — the existing `BackgroundTask(os.unlink, …)` covers that, and moving
      the file onto the volume makes forgetting it much more expensive (quick
      win; implement directly; inline)
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
      2026-08-16 weekly deep review)
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
- [ ] Condition dropdown with canonical values: `condition` is a free-text input
      (defaults "NM"), so typos like "nm "/"Near Mint" fragment the data; replace
      with a select (RAW, GEM-MT, NM-MT, NM, EX, VG, POOR) and normalize known
      variants on CSV import (quick win; implement directly; inline — touches
      CardForm.jsx)
- [ ] eBay fee + net-proceeds estimate: show the final-value fee (env-configurable
      rate, default ~13.25% + $0.30) and net proceeds next to the price in the
      Comps modal and mark-sold dialog — pricing today shows gross only, so
      thin-margin cards look better than they are (quick win; implement directly —
      display-only math, no schema; inline)
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
