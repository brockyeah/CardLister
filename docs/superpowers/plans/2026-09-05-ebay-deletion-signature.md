# eBay account-deletion notice signature verification — implementation plan

**Date:** 2026-09-05
**Design:** `docs/superpowers/specs/2026-09-05-ebay-deletion-signature-design.md`
(Approach A: in-process verification, 412 on failure, graceful degrade
without credentials)
**Status:** awaiting owner approval — see the three decisions at the end.

Ordered steps; each is independently testable and lands with its test.
No schema change, no new dependency, no new route, no frontend surface.
Estimated size: one new ~120-line service, ~30 changed handler lines, one
new ~40-line alert function, ~250 lines of tests.

## Step 1 — header decoding as a pure function

`backend/services/ebay_notifications.py` with
`decode_signature_header(header: str) -> Optional[Tuple[str, str]]`:
base64-decode, parse JSON, return `(kid, signature)` only when both are
strings, the kid is non-empty, bounded (≤ 128 chars) and matches a
conservative charset (`[A-Za-z0-9_.-]`), and the signature is valid base64 of
bounded length (≤ 1 KB). Anything else → `None`, never an exception. The kid
is about to be interpolated into a URL we fetch with our own credentials, and
the route is unauthenticated — strictness here is the DoS guard.

**Test** (`backend/tests/test_ebay_notifications.py`, new): a well-formed
header round-trips; each of {not base64, base64-of-non-JSON, missing kid,
missing signature, non-string values, oversized kid, kid with `/` or `..`,
signature that is not base64} returns `None`.

## Step 2 — public key fetch with positive + negative cache

Same module: `fetch_public_key(kid: str) -> Optional[str]` returning the PEM
string eBay serves, or `None`. Uses `ebay_api._get_app_token()` and
`ebay_api._base_url()` (imported as `from . import ebay_api` and called as
module attributes so tests patch `ebay_api` the way `test_callups.py`
patches `callups`). `httpx` GET of
`{base}/commerce/notification/v1/public_key/{kid}` with a bounded timeout
(15.0, matching the module's other calls — invariant #12's shutdown-join
argument). Module-level caches and a global budget (Codex's review caught that
per-kid negative caching alone bounds nothing against a fresh forged kid
per POST): `_key_cache[kid] = pem` (unbounded growth is impossible in
practice — one entry per genuine eBay signing key ever seen — but cap at
32 entries anyway); `_negative_cache[kid] = expiry` with a ~5-minute TTL
**and an entry cap** (~256, evict oldest) so its memory is flat under a
kid-per-POST flood; and a **global miss budget** — a sliding allowance of
outbound key fetches per minute across all kids (~10) — after which
`fetch_public_key` returns `None` with no network call. Genuine traffic
lives entirely in the positive cache; the budget is what turns an
unauthenticated flood from one authenticated eBay GET (and one threadpool
network wait) per POST into a fixed trickle. Never raises.

**Test**: with `ebay_api._get_app_token` patched to a token and `httpx`
patched (or `fetch_public_key`'s inner transport faked): a 200 caches and a
second call does not re-fetch (count calls); a 404 returns `None` and is
negative-cached (second call inside the TTL makes no request); token `None`
(unconfigured) returns `None` without any HTTP call; a flood of *distinct*
kids stops producing HTTP calls once the miss budget is spent (count calls
across the flood), and the negative cache never exceeds its entry cap.
Include a cache-clearing fixture — module-level caches leak between tests otherwise
(the `db_session` fixture precedent: isolation is opt-in here).

## Step 3 — PEM re-flow + dual-path ECDSA verify

**Gate before this step:** manually cross-check the scheme (header fields,
ECDSA/SHA-1, key endpoint, 204/412 semantics) against eBay's own guide
(`developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion`)
from a machine that can reach it. The design is grounded in the reference
Node SDK because the guide is egress-blocked from the scheduled sandbox; a
wrong curve/hash assumption here fails silently by 412-ing every genuine
notice, so the cross-check is a hard prerequisite of steps 3–4, not polish.

Same module: `_reflow_pem(key: str) -> str` inserting the newlines eBay's
compact response omits (after `-----BEGIN PUBLIC KEY-----`, before
`-----END PUBLIC KEY-----`), and
`verify_notice(body: bytes, header: str) -> bool` gluing steps 1–3:
decode header → fetch key → load via
`cryptography.hazmat.primitives.serialization.load_pem_public_key` →
verify with `ec.ECDSA(hashes.SHA1())` against the **two candidate inputs
in order** (per the design's "verifier's input" section, which grounds
why): first the raw `body` bytes, then — only if raw fails — the
`JSON.stringify`-equivalent compact re-serialization
`json.dumps(json.loads(body), separators=(",", ":"),
ensure_ascii=False).encode()`. `True` on either clean verify; every
failure path (unparseable body included, for the fallback) returns
`False`. "Never raises" is the contract, and the handling that delivers it
is **per attempt**, not one blanket except around the pair:
`cryptography`'s `verify()` signals mismatch by raising
`InvalidSignature`, so catch exactly that per candidate input and let the
fallback's own serialization step fail loudly in tests — a bare except
spanning both attempts would report a genuine bug (say, a `TypeError`
building the re-serialization) as an ordinary "signature didn't verify"
(the auto-review's catch). `cryptography` is already in the environment via
`python-jose[cryptography]` (`requirements.txt`); do **not** use the
`ecdsa` package (open PYSEC-2026-1325 backlog item).

**Test**: two anchors, one per path.
*Own-keypair (raw path):* generate a local `SECP256R1` keypair; sign a
body; a newline-stripped PEM of the public key re-flows, loads, and
verifies — pinning the re-flow against the real loader, not string
equality. The body for this case is chosen so a *default* `json.dumps`
round-trip would alter it (non-ASCII player name, no spaces after
separators) and the test asserts
`json.dumps(json.loads(body)).encode() != body`, so the raw path is
demonstrably doing the work. Tampered body → `False`; signature from a
different key → `False`.
*eBay-signed vector (fallback path):* vendor the VALID sample from the
Node SDK's `test/test.json` (payload + genuine signature header + matching
public key; attribute the source in the fixture) into
`backend/tests/fixtures/`, monkeypatch `fetch_public_key` to return its
key, and assert `verify_notice` accepts it — the fixture stores the parsed
payload rather than wire bytes, so it exercises exactly the
re-serialization fallback and proves interop against a signature eBay
actually minted. Also assert the fixture *fails* when the compact
re-serialization is replaced by a default `json.dumps`, so the
separators/`ensure_ascii` choices can't regress silently.

## Step 4 — wire into the handler

`routers/ebay_compliance.py::account_deletion_notice`, after the existing
capped body read (which stays byte-for-byte):

- `ebay_api.is_configured()` false → today's path unchanged: parse, log
  `unverified`, ack `{"ack": true}`.
- Otherwise `verified = await run_in_threadpool(ebay_notifications.verify_notice, bytes(body), header)`
  (the fetch inside is sync `httpx`; `scan.py:112` is the pattern, one
  worker is the reason).
- Verified → log `verified` (same repr+cap userId sanitization) and ack.
  This is the branch the future OAuth feature extends with token deletion.
- Not verified → log at warning, schedule
  `billing_alerts.notify_deletion_notice_rejected()` (step 5) as a
  **FastAPI background task** — never call it inline: it does sync email +
  ntfy network I/O (up to ~20s + ~15s of timeout) and an inline call from
  the async handler would block the lone event loop once per throttle
  window, stalling `/api/health` and every other request (Codex).
  `_sync_card_to_sheets` in `routers/cards.py` is the repo's pattern, and
  the alert's own throttle makes post-response ordering irrelevant. Then:
  **shadow mode by default** — ack `{"ack": true}` anyway unless
  `EBAY_SIGNATURE_ENFORCE=1` is set, in which case raise
  `HTTPException(412)` (eBay retries 412s; forgers get nothing). Shadow
  mode is the auto-review's refinement of the empirical question in step
  3's gate: verification runs and reports on real traffic — the log and
  the alert say exactly what would have been rejected and on which path —
  while a verifier bug cannot yet cost a genuine notice or the endpoint's
  compliance standing. The owner flips `EBAY_SIGNATURE_ENFORCE=1` on
  Railway after the portal's "Send Test Notification" logs `verified`
  against production (see post-merge below). The flag is read per-request
  like the module's other env config, so the flip needs no deploy.
- 413 cap, GET challenge, OAuth landing pages: untouched.

**Test** (extend `test_ebay_compliance.py`): with `EBAY_APP_ID`/`EBAY_CERT_ID`
set (monkeypatch) and `ebay_notifications.fetch_public_key` patched to the
step-3 test key: valid signature → 200 + `verified` in the log record
(caplog, as `test_deletion_notice_sanitizes_user_id_in_log` does). With
`EBAY_SIGNATURE_ENFORCE=1` additionally set: tampered body → 412;
absent/garbage header → 412 **and** the patched `fetch_public_key` was
never called; fetch returning `None` → 412 + alert called (patch the alert
too). Without the enforce flag, the same three failure shapes → 200 ack
**with** the warning log and the alert still fired — shadow mode reports,
never rejects. With credentials unset: existing
`test_deletion_notice_acks_without_stored_data` and the sanitization test
pass **unmodified** — that is the degrade contract. Oversized body still
413 with credentials set (the cap must fire before any verification work).

## Step 5 — owner alert, own throttle clock

`services/billing_alerts.py::notify_deletion_notice_rejected() -> bool`:
same shape as `notify_callup_alerts_undelivered` — email + ntfy, never
raises, and a **separate** module-level throttle timestamp, per the module
docstring's rule that unrelated outages must not share a clock
(`billing_alerts.py:10-12`). Body explains the two readings (someone is
probing the endpoint — ignorable; or eBay's real notices are failing our
verifier — fix before the endpoint is marked non-compliant and the keyset,
i.e. the Browse pricing source, is disabled) because those look identical
from the alert and have opposite urgencies.

**Test** (`test_mailer.py` or the compliance suite): fires both channels
(patched), second call inside the throttle returns `False` without
sending, does not disturb `_last_alert_at` / `_last_callup_alert_at`.

## Step 6 — docs

- `.env.example`: note that `EBAY_APP_ID`/`EBAY_CERT_ID` now also enable
  deletion-notice verification (they are already documented for Browse),
  and document `EBAY_SIGNATURE_ENFORCE` with its confirm-then-enforce
  purpose.
- `CHANGELOG.md`: entry under `[Unreleased]`, moved to a dated heading on
  merge per convention.
- `docs/BACKLOG.md`: move the item to Shipped with the date; annotate the
  "eBay OAuth + Sell API" item that its prerequisite is discharged.

## Post-merge manual verification (the step tests cannot stand in for)

The deploy lands in shadow mode, so this is a confirm-then-enforce
sequence, not a smoke test:

1. eBay's developer portal has a "Send Test Notification" button on the
   notification-endpoint form. Fire it against production.
2. The Railway log must show the `verified` line — and which path (raw vs
   re-serialized) verified it, settling the step-3 question empirically on
   a genuine eBay signature. A warning line instead means the verifier is
   wrong somewhere; shadow mode has already acked the notice, so nothing
   is lost — fix before enforcing.
3. Only then set `EBAY_SIGNATURE_ENFORCE=1` on Railway. From that point a
   412 on a real notice means the alert from step 5 is already on the
   owner's phone — that is the system working.

## Decisions needed before implementation

1. **412 on verification failure (recommended) vs always-2xx.** The backlog
   item's parenthetical assumed "still 2xx on failure per eBay retry
   semantics"; the design reverses that after grounding in eBay's reference
   SDK, whose semantics are 204-verified / 412-failed, precisely *because*
   of retry semantics — a 2xx is a terminal ack, so acking an unverified
   genuine notice discards eBay's redelivery. The risk the reversal buys —
   a systematically broken verifier 412s real notices until fixed — is now
   doubly bounded: by the step-5 alert, and by the shadow-mode rollout in
   step 4, under which 412 is only ever enabled *after* a genuine eBay
   signature has verified against production. Approve the reversal (as the
   enforce-flag end state) or pick Approach B (which is equivalent to
   never setting the flag, minus the intent).
2. **Degrade-to-unverified-ack when `EBAY_APP_ID`/`EBAY_CERT_ID` are unset
   (recommended) vs refusing.** Degrading keeps the portal registration
   valid on a deployment with no Browse credentials — the configuration the
   endpoint originally shipped for. The cost: such a deployment keeps
   today's forgeable log, and nothing but the log line says so. Scoped
   hard (per Codex's review): this fallback is legitimate only while no
   eBay user data is stored, and the OAuth design carries the recorded
   obligation to revoke it — an unverifiable notice on a deployment
   holding seller tokens must 412, not terminally ack — before tokens can
   persist (see the design's credentials-unset bullet).
3. **Alert channel.** Step 5 reuses email + ntfy with its own throttle
   (recommended); log-only is the alternative if a public endpoint being
   probed turns out to page too often in practice. (The throttle should make
   this moot: one push per 6h window, only when credentials are configured.)
