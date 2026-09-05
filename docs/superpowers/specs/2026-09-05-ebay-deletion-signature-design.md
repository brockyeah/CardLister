# eBay account-deletion notice signature verification — design

**Date:** 2026-09-05
**Status:** awaiting owner approval
**Backlog item:** "eBay deletion-notice signature verification" (Now/next,
found by the 2026-08-16 weekly deep review)
**Plan:** `docs/superpowers/plans/2026-09-05-ebay-deletion-signature.md`

## The problem, concretely

`POST /api/ebay-compliance/account-deletion` acks any POST from anyone. The
handler (`backend/routers/ebay_compliance.py:72-102`) reads the body, pulls
`notification.data.userId` out of it if it parses, logs the notice, and
returns `{"ack": true}` — deliberately, because eBay disables a production
keyset whose deletion endpoint stops acking, and there is no eBay user data
to erase yet. eBay signs every notice with an ECDSA signature in the
`X-EBAY-SIGNATURE` header, and the handler records only whether that header
is *present* (`ebay_compliance.py:97-101` — the log line literally says
`unverified`).

Two things make this worth fixing now rather than "when it matters":

1. **The log is the audit trail, and it is forgeable.** The handler's own
   docstring says the log exists "to audit that duty later" — the duty being
   token deletion once seller OAuth lands. An audit trail that anyone with
   the URL can write fake entries into (the route is public by necessity —
   `test_auth_sweep.py` lists `/api/ebay-compliance` in `PUBLIC_PREFIXES`)
   proves nothing when it is needed.

2. **It is the named hard prerequisite of the eBay OAuth track.** The
   backlog's "eBay OAuth + Sell API direct draft creation" item (Later,
   large) — the feature that replaces the clipboard flow, monetization notes
   Phase A — lists this item as its prerequisite, and the "eBay Orders API
   polling → auto-mark sold" item needs the same OAuth work. Once seller
   tokens are stored, an unverified notice is an unauthenticated
   "delete this user's tokens" request. Doing verification first means the
   OAuth design can simply say "act only in the verified branch" instead of
   growing a security appendix.

The fix costs nothing in Anthropic calls and adds no schema, no new
dependency, and no new route.

## How eBay actually signs a notice (grounded)

Established from eBay's official listener SDK (the Node implementation, which
eBay publishes as the reference — `github.com/eBay/event-notification-nodejs-sdk`,
`lib/validator.js` + `lib/constants.js`) and the Marketplace Account Deletion
guide (`developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion`;
note the guide itself is unreachable from the scheduled sandbox's egress
proxy, so the SDK source is the primary citation here. A manual cross-check
against the guide is a **hard gate** before the verification code lands —
plan steps 3–4 — not optional polish: a wrong curve/hash assumption fails
silently in exactly the shape this design warns about, 412-ing every
genuine notice):

- `X-EBAY-SIGNATURE` is **base64-encoded JSON** carrying at least `kid` (the
  id of the eBay public key that signed this notice) and `signature` (the
  base64 ECDSA signature). Examples also carry `alg`/`digest` fields; treat
  those as informational and validate the two we use.
- The public key is fetched from the **Notification API**:
  `GET {base}/commerce/notification/v1/public_key/{kid}`, authorized with an
  ordinary client-credentials **application token** — the exact token
  `services/ebay_api.py:_get_app_token()` (lines 65-99) already mints and
  caches for the Browse API, same `https://api.ebay.com/oauth/api_scope`
  scope, same `EBAY_APP_ID`/`EBAY_CERT_ID` credentials, same
  production-vs-sandbox base URL (`_base_url()`, lines 47-50).
- The response's `key` field is a SubjectPublicKeyInfo PEM **without
  newlines** — the SDK's `formatKey` re-inserts `\n` after
  `-----BEGIN PUBLIC KEY-----` and before `-----END PUBLIC KEY-----` before
  loading it. Ours must do the same.
- Verification is **ECDSA over SHA-1** (the SDK's `ALGORITHM` constant is
  `'ssl3-sha1'`) of the notification payload. SHA-1 is eBay's choice, not a
  parameter we own; we follow it.
- The SDK caches fetched keys by `kid` (LRU) so repeat notices don't refetch.
- The SDK's own HTTP semantics: **204 when the signature verifies, 412 when
  it does not**. 412 is eBay's documented "delivery failed, retry" signal;
  any 2xx is a terminal ack.

**The verifier's input is the load-bearing detail of the whole
implementation, and what eBay signs is not directly documented — so state
the evidence, not just a conclusion.** What is establishable from the
official SDKs: none verifies the raw received bytes. Node verifies
`JSON.stringify(parsedBody)`; the Ruby community verifier, `to_json` of the
parsed hash; the .NET SDK re-serializes a typed `Message` model with
`System.Text.Json` (compact, `UnsafeRelaxedJsonEscaping`); the PHP SDK,
bare `json_encode($message)`. All four reconstruct a *compact
re-serialization of the parsed payload* — and they disagree among
themselves on escaping edge cases (PHP's default escapes `/` and
non-ASCII; Node's and .NET's do not), so they cannot all be byte-exact
against arbitrary payloads. The interpretation under which they all work
on real notices is that eBay signs the compact JSON it sends — i.e. the
signed bytes *are* the wire bytes — with each SDK's round-trip merely
reconstructing them, fragilely, in its own serializer. But that is an
inference, not a documented contract, and CodeRabbit's review of this
design was right to flag a pure raw-bytes verifier as resting on it.

**Recommendation: verify both candidate inputs, raw first.** The handler
already holds the raw received bytes (it reads the stream into `body` for
the 64 KB cap, `ebay_compliance.py:82-86`); try those, and on mismatch
retry once against the `JSON.stringify`-equivalent compact re-serialization
— `json.dumps(json.loads(body), separators=(",", ":"),
ensure_ascii=False).encode()`. If signed == wire (the likely truth), the
raw path always passes and the fallback never runs; if eBay ever signs a
canonical form that differs from the received bytes, the fallback is the
path every official SDK effectively takes, so genuine notices still
verify; a forged notice fails both. The cost is one extra in-memory verify
call, only on the failure path. Never verify a *default* `json.dumps`
round-trip — its `", "`/`": "` separators match nothing any SDK produces.

**An offline ground-truth fixture exists and the tests must pin it:** the
Node SDK's `test/test.json` carries a VALID sample — a real
MARKETPLACE_ACCOUNT_DELETION payload with its genuine signature header and
the matching public key. Vendored into `backend/tests/fixtures/` (with
attribution), it proves our re-serialization path interoperates with an
actual eBay-signed vector, not just with signatures we minted ourselves.

## Approaches

### A. In-process verification; 412 on failure; graceful degrade without credentials (recommended)

A new `backend/services/ebay_notifications.py` with three seams, each a
module attribute so tests patch the module per the repo's patching
convention:

1. **`decode_signature_header(header) -> (kid, signature) | None`** — pure:
   base64 → JSON → validate `kid` (bounded length, `[A-Za-z0-9_-]`-ish
   charset) and `signature` (valid base64, bounded length). Strict
   validation here means a garbage header is refused without any network
   call — the route is unauthenticated, and the kid is about to be
   interpolated into a URL we fetch.
2. **`fetch_public_key(kid) -> pem | None`** — reuses
   `ebay_api._get_app_token()` and `ebay_api._base_url()`; bounded
   `httpx` timeout (the shutdown-join argument in invariant #12 applies to
   any network call on this container); positive cache by `kid` in a
   module-level dict like `ebay_api._token_cache`, plus a short **negative
   cache** (minutes) so a forged-kid spammer costs eBay's API one 404 per
   window, not one per POST.
3. **`verify_notice(body_bytes, header) -> bool`** — glue: decode, fetch,
   re-flow the PEM, then `cryptography`'s
   `public_key.verify(sig, data, ec.ECDSA(hashes.SHA1()))` against the two
   candidate inputs in order: the raw `body_bytes`, then the compact
   re-serialization (see "the verifier's input" above). Never raises.

Handler changes (`routers/ebay_compliance.py`):

- The handler is `async` and the key fetch is sync `httpx` — wrap the
  verification in `run_in_threadpool`, the same pattern `scan.py:112` uses
  for the same reason (one worker; a blocked event loop stalls `/api/health`
  and everything else).
- **Verified** → today's `{"ack": true}` 200, log `verified` with the
  sanitized userId (the existing repr+cap treatment stays). This branch is
  where the future OAuth feature deletes tokens.
- **Not verified** (bad header, unknown kid, signature mismatch, key fetch
  failed) → log at warning, fire a throttled owner alert (see below), and
  answer per a **confirm-then-enforce rollout**: shadow mode by default
  (ack anyway — verification reports on real traffic but cannot yet cost a
  genuine notice), **412** once `EBAY_SIGNATURE_ENFORCE=1` is set, which
  the owner does only after a genuine eBay signature — the portal's "Send
  Test Notification" — has logged `verified` against production. eBay
  retries a 412, so from then on a *genuine* notice that failed because
  our key fetch was down gets redelivered when it recovers; a forged
  notice gets 412 and nobody cares. (The shadow stage is the auto-review's
  refinement: it settles the verifier-input question empirically before
  the failure mode with teeth is armed.)
- **Credentials unset** (`EBAY_APP_ID`/`EBAY_CERT_ID` missing —
  `ebay_api.is_configured()` false) → verification is impossible; keep
  today's behavior exactly: ack 2xx, log `unverified`. This keeps the
  portal registration working on a deployment that has a verification token
  but no Browse credentials, which is a real configuration this app has
  already lived in (the Browse source is described as "dormant until
  credentials are configured", `ebay_api.py:3-7`).
- The 64 KB body cap and 413 behavior are untouched; so is the GET
  challenge handshake; so is `test_auth_sweep.py`'s PUBLIC list (no new
  routes).

Alerting: a new `notify_deletion_notice_rejected()` in
`services/billing_alerts.py`, with its **own throttle clock** — the module's
docstring already states the rule that unrelated outages must not share one
(`billing_alerts.py:10-12`). Rationale for alerting at all: if eBay's real
notices start failing verification (our bug, or eBay changing scheme), every
one gets 412'd and retried, and sustained failure is what gets an endpoint
marked non-compliant and the keyset — the Browse pricing source — disabled.
The alert turns "our verifier is broken" from a silent countdown into a
phone push on the first rejected notice.

**Tradeoffs:** matches eBay's own SDK semantics; genuine notices are never
silently dropped (412 → retry); the one new risk is that a systematic
verifier bug answers 412 to *every* genuine notice, which — sustained and
ignored — risks the keyset. Three bounds on it: the alert bounds
"ignored"; the shadow-then-enforce rollout means 412 is armed only after a
genuine eBay signature has verified in production; and the challenge
handshake (what the portal actually probes) is untouched.

### B. Verify, but always ack 2xx; act only on verified

What the backlog item's parenthetical assumed ("still 2xx on failure per
eBay retry semantics"): verify identically, log/alert on failure, but return
`{"ack": true}` regardless, so eBay never sees a failure from us.

**Tradeoffs:** zero keyset risk — and it quietly discards eBay's retry
mechanism. A 2xx is a terminal ack: a genuine notice that failed because our
key fetch was mid-outage is *gone*, never redelivered. Today that costs an
audit line; once OAuth tokens are stored it means keeping data we are
obligated to delete, with only a throttled push saying so. It also
contradicts the reference SDK, which is the behavior eBay's compliance
tooling is presumably tested against. Rejecting the backlog line's
assumption is a real reversal and is called out as decision 1 in the plan.

### C. Defer again; harden the log instead

Keep acking everything, but split the log line into `signature-present` vs
`signature-absent` streams and only call the former "audit". Rejected: the
header is copyable from any description of the scheme, so presence proves
nothing; and it leaves the OAuth prerequisite standing, which is the reason
this item is worth a design at all.

### Rejected implementation variant: the `ecdsa` pip package

The `ecdsa` package (already present transitively via `python-jose`) could do
the verify, but it is the subject of the open PYSEC-2026-1325 backlog item
(no fixed release; timing-attack class) and adds nothing over
`cryptography`, which `python-jose[cryptography]` already pins into the
environment. Use `cryptography`; add nothing to `requirements.txt`.

## What could go wrong

- **Choosing the wrong verifier input** — the deepest risk here, treated at
  length above: what eBay signs is inferred from its SDKs, not documented.
  Mitigated three ways: the dual-path verifier (raw bytes, then the
  stringify-equivalent compact re-serialization) passes under either
  interpretation; the vendored Node-SDK VALID vector pins interop against a
  genuinely eBay-signed sample; and the plan's own-keypair test signs a body
  that a *default* `json.dumps` round-trip would alter (non-compact
  separators, non-ASCII), so the trap of verifying a casually re-serialized
  body stays fenced.
- **PEM re-flow wrong** → every fetch "succeeds" and every verify fails.
  Pinned by a test that runs `formatKey`-equivalent on a newline-stripped
  PEM of a locally generated key and successfully loads + verifies with it.
- **Event-loop block on the key fetch** → wrapped in `run_in_threadpool`;
  the test asserts the handler still answers with the fetch patched to a
  slow function is *not* attempted (that's overreach for a unit suite — the
  threadpool wrap is instead kept honest by code review and the scan.py
  precedent; noted rather than tested).
- **Forged-kid spam turning us into a proxy for eBay's key API** → strict
  header validation before any fetch, negative cache, and the existing
  64 KB cap. The remaining cost per attacker window is one outbound GET.
- **Key rotation** → a rotated key arrives as a *new* kid, which misses the
  cache and fetches fresh; cache-by-kid handles rotation with no TTL logic.
  A small max-size guard on the positive cache (it can only grow by one
  entry per *valid* eBay key ever seen) keeps it honest.
- **Sandbox vs production** → base URL comes from `ebay_api._base_url()`,
  so `EBAY_ENV=sandbox` points key fetches at the sandbox API alongside
  everything else.
- **The one un-mockable step** — eBay's portal has a "Send Test
  Notification" button; the verification plan ends with firing it against
  production and reading the `verified` log line. That is the only step a
  test suite cannot stand in for.

## Cost

Zero Anthropic calls. Network cost is one eBay `public_key` GET per
never-before-seen kid (cached thereafter), on an endpoint that receives a
handful of POSTs a year.

## Verification

Full test list is per-step in the plan doc. The shape: tests generate a
local EC keypair, monkeypatch `ebay_notifications.fetch_public_key` (module
attribute, per the repo's patching convention) to return its public half,
and sign real bodies with the private half — valid signature acks and logs
`verified`; tampered body 412s; malformed header 412s with the fetch never
called; fetch failure 412s and fires the (patched) alert; unset credentials
preserves today's unverified ack; the existing 413 and challenge tests keep
passing untouched. Ship gates as always: full backend suite green, frontend
build green (no frontend surface in this change).
