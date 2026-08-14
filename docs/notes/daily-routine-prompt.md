# Automated routine prompts

Canonical copies of the scheduled Claude routines that run against this repo, plus
the rationale for each. **The routines themselves live in the cloud (claude.ai →
Routines) and are not visible from a local session** — this file is the only
readable record of what they say, so it must be updated whenever a prompt changes.

> **Do not rename or move this file.** Its path is hard-coded inside the daily
> routine's prompt (`read docs/notes/daily-routine-prompt.md`). Renaming it
> silently breaks that instruction — the routine reads a missing file and
> proceeds without its rationale.

Last reconciled with the live routines: 2026-08-12.

## The weekly rhythm

| Routine | Cadence | Purpose |
|---|---|---|
| **A — Daily build session** | Daily, 9:00 AM EDT | Health check → ideas → ship quick wins → open a PR and drive it to green |
| **B — Weekly deep review** | Sundays, 9:00 PM EDT | Find what diff-scoped PR review structurally cannot see |
| **C — Weekly deep-work design** | Sundays, 10:00 AM EDT | Turn one "large / design first" backlog item into an approved spec + plan |

The division of labour: **A ships small things continuously. C unblocks the big
things A can't touch. B checks that a week of A's output is actually sound.** A's
own PRs are self-healing — the session stays subscribed to GitHub events and wakes
to fix CI failures and answer review findings — so none of these routines exists to
babysit a PR.

Owner's only standing job: review and merge. No routine ever merges.

---

## Routine A — Daily build session

Runs daily at 9:00 AM EDT.

```
Daily project review + build session. Work through these phases in order.
If any step needs more detail or context on WHY it exists, read
docs/notes/daily-routine-prompt.md in the repo — it holds the canonical version
of this prompt plus the rationale, and it should be updated whenever this
prompt changes.

PHASE 0 — Ground yourself (always):
0. Read CLAUDE.md before touching anything. It holds the architecture and the
   "invariants that break silently" — failures that pass CI and break in
   production or cost money. Everything you build today must respect them.
   If you change an invariant, update CLAUDE.md and .coderabbit.yaml (which
   encodes the same invariants as review path instructions) in the same PR.

PHASE 1 — Health check (always):
1. Check repo state: open PRs (drive any of ours toward green), open issues, CI
   status on main, and security/dependency alerts. Hit production health at
   https://cardlister-production.up.railway.app/api/health — confirm ok/db true,
   that the reported revision matches origin/main HEAD (if it lags, a deploy
   failed), and that the call-up poller is not stale.
2. Read the changelog AS IT EXISTS ON MAIN (`git show origin/main:CHANGELOG.md`)
   — main is what production runs, so its changelog is the ground truth of what
   has actually shipped; nothing half-baked appears there. Compare against the
   working branch's [Unreleased] section to see what's built but not yet merged,
   and treat unmerged work as "get it reviewed/merged" before piling more on top.
3. Read docs/BACKLOG.md — it is the persistent ledger between runs. Never
   re-propose anything in its Shipped section or already recorded in the changelog.
4. Branch hygiene BEFORE any building: if the previous run's PR has merged,
   restart the working branch from origin/main. Never stack new work on a branch
   that has fallen behind — a stale branch silently misses merged work, and
   resolving its conflicts later risks deleting another PR's changelog entry.

PHASE 2 — Ideas (always):
5. Propose 3–5 new feature/implementation ideas not already in the backlog,
   grounded in the current code. For EVERY idea, you must decide and state:
   - effort: quick win (≤ half day) / medium / long-term
   - planning: implement directly, or write a plan/spec doc first (anything
     touching schema, auth, money, or 3+ subsystems requires a plan doc)
   - execution: inline, or delegated to subagents (delegate only when work items
     don't touch overlapping files; otherwise stay inline)
   These decisions are required output, not optional commentary.
   Prefer ideas that fix something the owner has actually hit in real use over
   speculative features.
6. Merge the surviving ideas into docs/BACKLOG.md, keeping the sizing tag format
   already used there.

PHASE 3 — Build (standing authorization):
7. Implement the top 1–2 quick wins from the backlog without asking. Gates: full
   backend suite green and frontend build green. Run the suite from the repo
   root as `python3 -m pytest backend/tests -q` (locally, where the repo-root
   venv exists, `.venv/bin/python -m pytest backend/tests -q`). The module form
   is required either way — there is no pytest config, so bare `pytest` can't
   resolve the `backend.` import path. Then commit per feature and push to the working
   branch. In the same push: update the backlog's Shipped section with a date AND
   add a CHANGELOG.md entry under [Unreleased] for every shipped feature — a
   feature without a changelog entry is not done. Never edit dated (merged)
   changelog sections; those only change when a PR merges to main.
8. Use Claude skills where they apply — /security-review after auth/upload/query
   changes, /simplify after large diffs, dataviz before building any chart or
   dashboard UI. On Mondays, run a deeper pass: dependency updates +
   /security-review of the full app.
9. Verify before claiming done: run the tests you just wrote, and for anything
   user-visible, actually exercise it (start the app, hit the endpoint, click the
   flow) rather than asserting it works. Never weaken or skip a test to get green.
10. Open a PR automatically: if the branch has shipped work and no open PR, open
    one against main whose body summarizes the [Unreleased] changelog entries.
    Never merge it yourself — merging is the owner's call.
    Do NOT review your own PR. Three reviewers cover it: the Claude Auto Review
    GitHub Action, CodeRabbit, and Codex — which the owner runs himself outside
    GitHub and relays back in chat, so never wait for Codex on the PR or read its
    absence as a pass. Stay subscribed to the PR and address action/CodeRabbit
    findings as event wakes deliver them — that is how a PR reaches green with no
    owner intervention. Do not block your Phase 4 report waiting on reviews that
    have not arrived yet; the session will wake when they do.
11. Changelog housekeeping: when a previous PR has merged, move its [Unreleased]
    entries under a dated heading with the PR number (this lands in the next PR).

PHASE 4 — Report (always):
12. End with a "Top picks" section: the 2–3 highest-leverage next actions and why.
13. Send exactly one notification: lead with what shipped or broke, then top picks
    — include the PR link if one was opened. State plainly anything you could not
    finish and why. If truly nothing changed and nothing shipped, stay silent.
```

### Rationale

- **Decisions are required output.** The original prompt asked only for ideas; whether
  an item needs planning first, and whether it should be delegated, had to be requested
  after the fact. Now every idea carries an effort/planning/execution verdict.
- **Persistent state.** Without `docs/BACKLOG.md`, each run re-derives the project state
  from scratch and can re-pitch already-shipped ideas. The backlog is the memory.
- **Changelog as prod ground truth.** `main` is continuously deployed, so the changelog
  as it reads on `origin/main` describes exactly what production runs — bad or unmerged
  implementations never appear there. Reading it first (instead of raw git log) gives
  the run an instant, curated picture of recent shipped work, and the branch's
  [Unreleased] diff against it shows what's still awaiting review/merge.
- **Standing build authorization.** The review-only loop wastes the run; pre-approving
  gated quick wins (tests + build + push) turns the routine from a reporter into a
  contributor while keeping risky work behind plan docs.
- **Phase 0 exists because CLAUDE.md does.** The invariants documented there (append-only
  `SHEET_HEADERS`, `_COLUMN_MIGRATIONS`, the `" (subscription)"` cost suffix, route
  ordering) all pass CI and fail in production. A run that hasn't read them can ship a
  green PR that breaks the deployed app. `.coderabbit.yaml` encodes the same list as
  review instructions, so the two files have to move together.
- **Branch hygiene is step 4 for a reason.** PR #33 sat a week behind main; when it was
  finally refreshed, the obvious conflict resolution would have silently deleted PR #34's
  changelog entry, and a test that was green on both sides failed on the combination.
  Restarting from `origin/main` before building is cheaper than untangling that later.
- **Skills are named, not implied.** `/security-review`, `/simplify`, and `dataviz` only
  get used if the prompt tells the run when they apply.
- **Health check first.** A red CI run or a down production instance matters more than
  brainstorming; check it before spending the run on ideas. The revision-vs-main
  comparison catches the failure mode a plain 200 OK misses: a deploy that never landed.
- **Auto-PR with a hard stop at merge.** Each run's shipped work gets a PR opened and
  babysat automatically (CI green, review comments addressed), but merging stays a
  human decision — that's the gate that keeps main (and therefore the prod changelog)
  trustworthy.
- **Three reviewers, none of them the author.** The Auto Review Action authenticates with
  the owner's subscription (`CLAUDE_CODE_OAUTH_TOKEN`), so it costs no API credits and
  reviews from a context that never saw the code being written. CodeRabbit adds a second
  automated pass driven by `.coderabbit.yaml`'s repo-specific path instructions. Codex is
  run by the owner outside GitHub and relayed in chat — it will never appear on the PR,
  so its absence must not be read as approval. The routine deliberately does NOT also
  review in-session: the author reviewing their own work is the weakest possible pass.

---

## Routine B — Weekly deep review

Runs Sundays at 9:00 PM EDT.

```
Weekly deep review. Three reviewers already covered every PR line-by-line this
week (Claude Auto Review, CodeRabbit, Codex). Do NOT repeat that — you exist to
find what diff-scoped review structurally cannot see. Read whole files and whole
subsystems, not diffs.

SCOPE: everything merged to main in the last 7 days
(`git log origin/main --since=7.days`), plus any subsystem those commits touched.

Dispatch parallel subagents, one per area, then synthesize. Hunt specifically for:

1. Cross-PR inconsistency: the same problem solved three different ways across
   the week's commits; a pattern established in one PR and quietly violated in
   the next; duplicated logic that should have been shared.
2. Dead weight: functions, endpoints, env vars, config keys, and CSS/component
   classes that nothing references anymore. Check .env.example against what the
   code actually reads, and .coderabbit.yaml/CLAUDE.md against what the code
   actually does.
3. Test quality, not test count: tests that would still pass if the feature
   were deleted, assert-nothing tests, and — most important — features shipped
   this week with no test covering their actual failure mode.
4. Invariant drift: re-derive CLAUDE.md's "Invariants that break silently" list
   from the current code. Is each one still true? Did this week's work add a new
   invariant that belongs on the list, or make an existing one obsolete?
5. Cost and performance drift: has anything increased Anthropic token spend,
   added an N+1 query, or put blocking I/O on the event loop? Check
   /api/analytics for a week-over-week scan-cost change and explain any jump.
6. The thing you'd flag if you owned this codebase and had to maintain it for a
   year. One honest judgment call, even if it's uncomfortable.

VERIFY BEFORE REPORTING. An unconstrained hunt for problems generates
plausible-sounding noise. For every candidate finding, prove it against the
actual code — cite file:line, and state the concrete failure (inputs → wrong
behavior). Discard anything you cannot prove. A short list of real findings
beats a long list of maybes.

OUTPUT:
- File every confirmed finding in docs/BACKLOG.md under "Now / next" with the
  standard sizing tag. Findings that live only in a run log do not exist.
- You may implement fixes that are unambiguous and low-risk (dead code removal,
  a missing test, a stale doc line) directly: gates are full backend suite green
  and frontend build green, changelog entry under [Unreleased], then open a PR.
  Anything touching schema, auth, money, or 3+ subsystems gets a backlog entry
  and a plan doc instead — never a same-session fix.
- Never merge. Merging is the owner's call.

REPORT: lead with the single most important finding and why it matters. Then the
rest, ranked. Then what you fixed vs. what you filed. If the week's work is
genuinely clean, say so in two lines and stop — do not manufacture findings to
justify the run.
```

### Rationale

- **It replaced a daily `/code-review` run that did nothing useful.** The previous routine
  ran `/code-review` with no target against a fresh checkout of `main` — where there is no
  diff to review — and reported into a run log that nothing acted on. Every PR was already
  reviewed by two bots minutes after opening, so a daily third pass was pure duplication.
- **Weekly, because daily has nothing to find.** At 1–2 PRs a day, a nightly deep pass
  reviews the same code repeatedly. A week accumulates enough change for cross-PR patterns
  to become visible at all.
- **The blind-spot list is the whole point.** Per-PR reviewers are diff-scoped (they can't
  see that a function went dead or that three files now duplicate logic), have no cross-PR
  memory (each PR passes in isolation; together they're inconsistent), can't run anything
  (unreachable paths, unused env vars), and rarely judge whether a test would still pass
  with the feature deleted. Re-reviewing diffs would find none of that.
- **Verification is mandatory because "find problems" prompts hallucinate.** An open-ended
  hunt reliably produces confident, plausible, wrong findings. Requiring a file:line proof
  and a concrete failure path — and explicitly permitting a two-line "it's clean" report —
  is what keeps the output trustworthy enough to act on without re-checking it by hand.
- **Findings go in the backlog, not the report.** The failure mode of the old routine was
  producing observations nobody ever read. A finding that isn't written to `docs/BACKLOG.md`
  doesn't survive to the next run.

---

## Routine C — Weekly deep-work design

Runs Sundays at 10:00 AM EDT.

```
Weekly deep-work session. The daily routine only ships quick wins, so the
large items never move. Your job is to unblock exactly one of them.

1. Read docs/BACKLOG.md and pick the single highest-leverage item tagged
   "large" or "design first". Prefer items that unblock others or fix a
   problem the owner has hit in real use.
2. Write a design doc in docs/superpowers/specs/YYYY-MM-DD-<feature>-design.md:
   the problem in concrete terms, 2-3 approaches with tradeoffs, a
   recommendation with reasoning, what could go wrong, and how it will be
   verified. Ground every claim in the actual code — cite file:line.
3. Write the implementation plan in docs/superpowers/plans/YYYY-MM-DD-<feature>.md
   as ordered, independently testable steps, each with its test.
4. Cost check: if the feature adds Anthropic calls, estimate per-scan cost
   delta explicitly. This is a two-person hobby tool — a feature that doubles
   scan cost needs to say so up front.
5. Open a PR with the docs only — no implementation. The owner approves the
   approach before code exists, which is the whole point.
6. Report: which item, the recommended approach in three sentences, the
   estimated effort, and what you need decided before implementation starts.
```

### Rationale

- **The daily routine structurally cannot build the big features.** Its standing
  authorization covers "the top 1–2 quick wins," and anything touching schema, auth,
  money, or 3+ subsystems requires a plan doc first. So every large item — batch
  front/back pairing, the comps variant filter, the interactive pricing agent — stays
  permanently parked. Nothing in the loop was producing plan docs.
- **Design is the bottleneck, not ideation.** The backlog already holds more good ideas
  than throughput. Adding a fourth routine that generates more ideas would make that
  worse; converting parked ideas into approved, step-by-step plans is what actually moves
  them, because the daily run can then execute a plan step as a quick win.
- **Docs-only PRs make approval cheap.** The owner approves an approach by reading a spec,
  not by reviewing a large implementation that may be built on the wrong premise.
- **Explicit cost estimates.** Two users split the Anthropic bill; a feature that quietly
  doubles per-scan cost is a real decision, and it belongs in the spec rather than being
  discovered on the invoice.

---

## Conventions every routine shares

- **Never merge.** Every routine opens PRs and drives them to green; the owner merges.
- **A feature without a changelog entry is not done.** Ship gates are the full backend
  suite green and the frontend build green.
- **Never edit dated changelog sections** — they are the record of what production runs.
  Only `[Unreleased]` moves.
- **Move backlog items to Shipped with a date instead of deleting them**, so later runs
  don't re-propose finished work.
- **Report once, and stay silent when there's nothing to say.** A routine that notifies on
  every run trains the owner to ignore it.

## Possible future upgrades

- Track a simple metric in the backlog (cards listed/week from the DB if reachable) so
  ideas can be prioritized against actual usage instead of intuition.
- A lightweight production watchdog (2–3×/day): health endpoint, deployed revision vs
  main, failed Railway deploys, and a scan-cost spike check — reporting only on anomaly.
  Currently the worst case is ~12 hours between the evening merge and the next morning's
  health check.
