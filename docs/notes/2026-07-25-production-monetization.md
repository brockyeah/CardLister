# CardLister: Path to Production & Monetization

*Working notes, 2026-07-25. This is a strategy/planning doc — no code should be written
against it until the open questions at the bottom are settled.*

## Where we are

CardLister is a single-tenant internal tool: one Docker container on Railway, SQLite on a
volume, a shared password list in an env var, and a Google Sheet mirror. That architecture
is exactly right for its current job and exactly wrong for a public product. The good news:
the core loop (photo → vision extraction → comps → listing text) **is** the product, and it
already works. Everything below is about wrapping that loop in the boring machinery a paid
product needs.

## Who would pay

- **Volume sellers / card-shop owners** — list 50–500 cards a week; pay for time saved.
  The batch queue + learning-from-corrections features are already aimed at them.
- **Collectors doing a one-time liquidation** — a big box to sell once. Ideal for
  pay-per-scan credits rather than a subscription.
- **Breakers** (live-stream pack openers) — high card throughput, need fast turnaround
  and inventory tracking; the call-up alerts are genuinely differentiating here.

Adjacent competitors: CollX, Ludex, CardDealerPro (scanning/ID), and eBay's own
computer-vision listing flow. Differentiation to lean on: end-to-end *listing* automation
(not just ID), sold-comp pricing chain, prospect intelligence (call-ups + 1st Bowman),
and correction-learning that gets better per user.

## Technical gaps, in dependency order

1. **Multi-tenancy** — the schema has no `owner`/`tenant` column on `cards`, `scans`,
   `corrections`; usernames are strings in one env var. Needed: a `users` table, real
   signup (email + OAuth), per-user data isolation on every query, and per-user
   Sheets/eBay credentials. This is the single biggest refactor and touches everything.
2. **Postgres + Alembic** — SQLite-on-a-volume can't serve concurrent tenants; the
   `ensure_columns` registry should become real migrations at the same time.
3. **Object storage for uploads** — card images to S3/R2 instead of the container volume.
4. **Job infrastructure** — the in-process asyncio poller becomes a real worker/queue
   (or at minimum a separate Railway service) so web deploys don't drop scheduled work.
5. **Billing** — Stripe. Metered usage fits naturally: we already record per-user token
   costs in `usage_events`, which is the internal prototype of a billing meter.
6. **Hardening** — rate limits, per-tenant API cost caps, audit logging, TOS/privacy
   policy, backup/restore story.

## Legal / compliance flags (resolve before launch)

- **Scraper risk**: 130point/Mavin/eBay HTML scraping is fine for personal use but a
  liability in a paid product (ToS violations, breakage, IP blocks). Production pricing
  should be **eBay API only** (Marketplace Insights / Browse), with the scrape chain kept
  strictly for self-hosted/dev mode.
- **eBay developer program**: production keys, application growth check, and eventually
  OAuth per user for direct listing creation (the Phase 2 Sell API work becomes a
  launch requirement — the clipboard flow is a demo, not a product).
- **Anthropic usage**: vision costs are the marginal cost of goods; terms allow this
  use, but costs must be metered and capped per tenant (already half-built).

## Monetization model (recommendation)

Unit economics: a Balanced-mode scan costs roughly $0.01–0.05 in API tokens; pricing
lookups are near-free. So price per *listing*, not per seat:

- **Free**: ~10 scans/month, watermark-free, no card. Funnel + word of mouth.
- **Hobbyist $9/mo**: ~150 scans, call-up alerts, CSV export.
- **Dealer $29–49/mo**: ~1,000 scans, batch mode, priority Accuracy-mode scans,
  multi-user, API access.
- **Credit packs** for the liquidation crowd (e.g. $15 / 200 scans, never expire).

Margin holds at ~80–90% even at heavy usage; the metering table already exists.

## Suggested sequencing

1. **Phase A (product-complete for one tenant)**: eBay OAuth + Sell API, Orders polling,
   PSA/BGS detection. Makes the single-tenant product undeniably good.
2. **Phase B (multi-tenant foundation)**: users table, Postgres, S3, Alembic, job worker.
   No visible features; do it before any public signup.
3. **Phase C (commercial)**: Stripe, plans/limits, marketing site, onboarding, support.
4. **Phase D (moat)**: shared (opt-in, anonymized) correction corpus to make extraction
   better than any solo competitor; pricing history charts; portfolio analytics.

## Open questions for Brock

- Solo bootstrap or looking for this to stay a side tool with a few invited users?
  (Phase B is only worth it for a real public launch.)
- Appetite for eBay's developer program process (takes weeks, needs a production app
  review)?
- Brand/name check: "CardLister" is descriptive but likely hard to trademark.
