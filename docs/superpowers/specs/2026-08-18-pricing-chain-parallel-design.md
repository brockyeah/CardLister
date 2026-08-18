# Pricing Chain: Concurrent Sources with a Real Deadline — Design

**Status:** proposed, awaiting owner approval
**Filed:** 2026-08-18
**Scope:** `backend/routers/pricing.py`, `backend/services/*` timeout config,
`CLAUDE.md` (invariants)

## The problem, concretely

`get_pricing` (`routers/pricing.py:31`) tries eBay Browse API → 130point →
Mavin → eBay HTML scrape strictly one after another. The chain expresses only
**preference** — no source's input depends on another's output — yet the user
waits for the sum.

Verified per-source `httpx.Client(timeout=...)` values: eBay API 15s
(`ebay_api.py:79` and again at `:129`), 130point 20s (`onethirtypoint.py:121`),
Mavin 15s (`mavin.py:41`), eBay scrape 15s (`ebay_pricing.py:67`).

On Railway the scrapers routinely 403 from a datacenter IP (CLAUDE.md), so the
**common case is the worst case**: every source fails and the user waits the
full sum before the $9.99 mock lands — on every card. With eBay credentials set
the OAuth path makes two sequential 15s calls (`_get_app_token`, then the
search), pushing the ceiling higher still.

This is amplified by batch scanning: `Scanner.jsx:182,219` awaits
`fetchPricing` per card sequentially, so a 20-card batch multiplies the wait by
twenty.

## Contracts that must survive

- **Note semantics.** When a source succeeds, its own fixed note is what the UI
  shows. Only the final all-failed mock branch joins every attempted source's
  note with `" | "`. Both halves must be preserved exactly.
- **Sources never raise.** Each degrades to empty comps plus a note. Return
  shapes differ: most are `(comps, price, note)`; **Mavin is a 4-tuple**
  `(comps, price, source, note)`.
- **Resolution is by preference, never first-to-finish.** A fast mock-ish
  source must not beat a slow authoritative one. This is the invariant most at
  risk from a naive parallelization.

## Approaches

### A. Full fan-out, resolve in preference order — **recommended**

Submit all independent sources concurrently, then walk the existing preference
order and take the first success.

- Wall clock becomes the latency of the slowest source *up to and including the
  winner*, not the sum. In the all-fail common case that is one source's
  timeout instead of four.
- The preference cascade is untouched, so note semantics and ordering are
  preserved by construction.
- Always pays every request, even when a high-preference source answers first
  (see "cost" below).

### B. Two-stage fan-out (API + 130point, then the rest)

- Avoids hitting the scrapers when a preferred source answers.
- **Rejected.** It optimizes the case that is currently rare (a preferred
  source succeeding) at the cost of complexity, and in the common all-fail case
  it reintroduces exactly the serial penalty being removed — two stages of
  timeout instead of one.

### C. Deadline only, no concurrency

- One-line change, bounds the worst case.
- **Rejected.** It caps the pain without fixing it: a lookup that hits the
  deadline returns *nothing* after a long wait, which is worse than returning a
  real comp from a source that would have answered in parallel.

## Recommendation

**A**, with three corrections that the obvious implementation gets wrong. Each
was proven against the installed runtime, and each would otherwise ship a
regression.

**1. `concurrent.futures.wait(..., timeout=D)` defaults to `ALL_COMPLETED`.**
Submitting everything and then calling `wait()` before cascading makes *every*
lookup take `max(all four sources)` — turning a fast 130point hit from 2s into
20s and making the common case no better than today for a preferred-source
success. The correct shape is to submit all futures, then walk the preference
order calling `future.result(timeout=<remaining budget>)` per source. That
resolves by preference while the waits overlap. Do **not** re-derive completion
with `f.done()` after a `wait()` — that reintroduces a boundary race that makes
the deadline test flaky.

**2. `httpx.Client(timeout=20.0)` is not a 20-second request budget.** Verified
on the installed httpx: a scalar timeout applies to connect, read, write, and
pool *each*, and the read timeout is per read operation — so a slow-drip
response body extends indefinitely. Any "the deadline is just above the slowest
source" reasoning is therefore unfounded. The overall deadline must be enforced
by our own wall clock in the cascade, independent of httpx, and the per-source
clients should move to an explicit `httpx.Timeout(connect=…, read=…, write=…,
pool=…)` so their bounds are stated rather than assumed.

**3. A module-level `ThreadPoolExecutor` delays container shutdown.** Its
workers are non-daemon and joined at interpreter exit, so a future abandoned at
the deadline keeps the process alive until its request finishes — measured at
4s for a 4s task. `Dockerfile:46` runs a bare uvicorn as PID 1. Use a
per-request executor and `shutdown(wait=False, cancel_futures=True)`, and
accept that an already-running request still runs to its (now properly bounded)
timeout. Correction 2 is what makes that bound real.

Also worth stating rather than discovering later: `get_pricing` is a plain
`def` route, so it occupies an anyio worker thread for its whole duration — the
**same pool** `run_in_threadpool` uses for the 15–30s vision call
(`routers/scan.py:112`). Shortening pricing therefore *reduces* pressure on
that pool; the fan-out's own threads are separate and short-lived. At two users
this is not a capacity concern, but it is the reason not to make pricing
`async def` casually.

## What could go wrong

- **Ordering regressions are silent.** If resolution accidentally becomes
  first-to-finish, the app still returns a price — just the wrong one, with the
  wrong note. This needs a test that pins preference order with deliberately
  staggered fake sources, not just a "it was faster" assertion.
- **Mavin's 4-tuple.** A uniform `submit(fn, **args)` fan-out invites treating
  all results alike; the unpacking must stay source-specific or Mavin's `source`
  field silently becomes its note.
- **`_token_cache` is module-level mutable state** (`ebay_api.py:44`, written at
  `:97-98`). A worker abandoned at the deadline can populate it after its result
  was discarded. Harmless under the GIL and arguably beneficial (the next
  request gets a warm token), but it should be stated, not stumbled on.
- **eBay API quota.** Full fan-out calls the Browse API on every lookup even
  when a scraper would have answered. Today's serial chain already calls it
  first every time, so this changes nothing for eBay; the added cost is the
  *scrapers* being hit on every lookup rather than only after eBay fails. Since
  the common case is that all four are attempted anyway, the marginal increase
  is small — but it is not zero, and it is the honest cost of A over B.
- **Batch amplification cuts both ways.** The win multiplies across a 20-card
  batch; so would a regression.

## Cost impact (required check)

No Anthropic tokens. Marginal increase in outbound scraper requests (see quota
note). The user-visible win is the point: the common case drops from the sum of
four timeouts to roughly one.

## Verification

- Preference order holds when a *later* source is much faster — the core
  regression test.
- Every note string is byte-identical to today: per-source note on success, and
  the `" | "`-joined note on the all-fail mock branch.
- Mavin's 4-tuple still unpacks correctly.
- A lookup where every source hangs returns by the deadline with the mock, and
  the elapsed time is bounded — asserted against the wall clock, not mocked out.
- Elapsed time for an all-fail lookup is materially below the serial sum.
