# Design note: Claude-subscription fallback for scan billing

*Status: planned, not implemented. Touches billing/auth, so per the routine's rules it
gets this design doc + owner sign-off before code.*

## The ask

Card scans call the Anthropic Messages API directly (`backend/services/claude_vision.py`)
with `ANTHROPIC_API_KEY`, billing pay-as-you-go console credits. Brock wants scans to
draw from his Claude Max subscription instead — or at minimum fall back to it when the
API key runs out of credits, so scanning never hard-stops.

## What's actually possible

- A Max subscription cannot authenticate raw Messages API calls — API keys are the only
  auth there. So the current call path can never bill the subscription directly.
- Subscription billing IS available to programmatic callers via Claude Code / the Agent
  SDK authenticated with an OAuth token (`claude setup-token` →
  `CLAUDE_CODE_OAUTH_TOKEN`). Per Anthropic's 2026-06 statement, Agent SDK /
  `claude -p` usage keeps drawing from Pro/Max subscription limits.
- Claude Code can read images, so a vision extraction can be reproduced as a headless
  `claude -p` call: point it at the saved upload, reuse the existing extraction prompt,
  ask for the same JSON schema, parse stdout.

## Recommended shape: fallback, not primary

Keep the Messages API as the primary path — it's the supported way to power an app,
has lower latency, and honors the per-scan model/effort presets exactly. Add a
`subscription_fallback` layer in `claude_vision.py` that triggers only when:

1. `ANTHROPIC_API_KEY` is unset, or
2. the API returns a billing/credit error (HTTP 400 "credit balance is too low") or
   persistent 429s.

Fallback behavior: shell out to `claude -p` with `CLAUDE_CODE_OAUTH_TOKEN` in env,
reusing the same prompt + cheat-sheet injection, timeout ~90s, and tag the
`ScanResponse` with `source: "subscription"` so the UI can show a small "billed to
subscription" badge. Record the scan in `usage_events` with model + a zero cost
estimate flagged as subscription-billed.

## Costs and caveats (why fallback-only)

- **Terms/positioning**: fine for a personal/internal tool; NOT a path for the
  commercial version (see monetization notes — production must be API-key metered,
  because tenant costs must be meterable and subscription terms don't cover powering
  a public product).
- **Shared quota**: heavy scanning eats the same Max allowance used for interactive
  Claude Code sessions and the daily routine itself.
- **Runtime deps**: the Railway image must add Node + the Claude Code CLI (~100MB),
  and the OAuth token expires yearly (rotation chore).
- **Latency**: a `claude -p` round trip is slower than a direct Messages call; batch
  scans will feel it.

## Implementation sketch (when approved)

1. Dockerfile: install Node 20 + `@anthropic-ai/claude-code`; document
   `CLAUDE_CODE_OAUTH_TOKEN` in `.env.example` + README env table.
2. `claude_vision.py`: extract the prompt-building into a shared helper; add
   `_extract_via_subscription(image_path, prompt) -> dict` using `claude -p
   --output-format json`; wire the two trigger conditions; never raise (mirror the
   existing mock/error fallback ladder: API → subscription → mock).
3. Tests: fake the subprocess; cover trigger conditions (no key, credit error) and
   JSON-parse failures falling through to mock.
4. Effort: medium (~1 day). Execution: inline (single service file + Dockerfile).
