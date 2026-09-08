# Automated routine prompts

Canonical copies of the scheduled Claude routines that run against this repo, plus
the rationale for each. **The routines themselves live in the cloud (claude.ai →
Routines) and are not visible from a local session** — this file is the only
readable record of what they say, so it must be updated whenever a prompt changes.

> **Do not rename or move this file.** Its path is hard-coded inside the daily
> routine's prompt (`read docs/notes/daily-routine-prompt.md`). Renaming it
> silently breaks that instruction — the routine reads a missing file and
> proceeds without its rationale.

Last reconciled with the live routines: 2026-08-14.

> **⚠ The live Routine A prompt is currently BEHIND this file — owner action needed.**
> Checked 2026-09-07 against the prompt the scheduler actually delivered. Two gaps:
>
> 1. **Step 11 (changelog housekeeping) is missing the `chore/changelog-<date>` branch
>    rule** that PR #69 added here. The live prompt still says only "move its
>    `[Unreleased]` entries under a dated heading", with no instruction to use a
>    dedicated branch and no "check whether a `chore/changelog-*` PR is already open"
>    guard. CI's `changelog-guard` job now **fails any PR that dates a heading from a
>    non-`chore/changelog-*` branch**, so the live prompt instructs the run to do
>    something that turns its own PR red by construction. It has not bitten yet only
>    because no PR with `[Unreleased]` entries has merged since the guard shipped — the
>    next one will.
> 2. **Steps 10 and 13–14 (reviewer count, queue-depth reporting)** are the changes made
>    here on 2026-09-07 and are not in the live prompt at all.
> 3. **Step 10's two trigger comments** (`@coderabbitai review` and `@codex review` after
>    the final push) were added on 2026-09-08, along with the matching sentence in the
>    Routine B block below.
>
> All of it needs the owner to paste the updated prompt blocks below into claude.ai →
> Routines. Until then this file describes what the routines *should* do, not what they do.

## The weekly rhythm

| Routine | Cadence | Purpose |
|---|---|---|
| **A — Daily build session** | Daily, 9:00 AM EDT | Health check → ideas → ship quick wins → open a PR and drive it to green |
| **B — Weekly deep review** | Sundays, 9:00 PM EDT | Find what diff-scoped PR review structurally cannot see |
| **C — Weekly deep-work design** | Sundays, 10:00 AM EDT | Turn one "large / design first" backlog item into an approved spec + plan |

The division of labour: **A ships small things continuously. C unblocks the big
things A can't touch. B checks that a week of A's output is actually sound.**

Routine A owns its own PRs end to end: its session stays subscribed to GitHub
events and wakes to fix CI failures and answer review findings until the PR is
green. Routines B and C never babysit A's PRs — that is precisely why no separate
PR-shepherd routine exists.

Owner's only standing job: review and merge. No routine ever merges.

---

## Routine A — Daily build session

Runs daily at 9:00 AM EDT.

```text
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
   status on main, and security/dependency alerts. **Measure the review queue
   here, not later: count the open PRs and note the date of the last merge to
   main.** The queue is an input to what you build (step 7) and the lead of your
   report (step 13), so it has to be known before Phase 3, not discovered after
   it. Hit production health at
   https://cardlister-production.up.railway.app/api/health — confirm ok/db true,
   that the reported revision matches origin/main HEAD (if it lags, a deploy
   failed), and that the call-up poller is not stale.
2. Read the changelog AS IT EXISTS ON MAIN (`git show origin/main:CHANGELOG.md`)
   — main is what production runs, so its changelog is the ground truth of what
   has actually merged and is live. It records scope, not quality: a merged bug
   is described there as confidently as a working feature, so never treat an
   entry as evidence the code behind it is correct. Compare against the
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
7. Implement the top 1–2 quick wins from the backlog without asking. **First
   consult the queue depth from step 1: if nothing has merged in 3+ days or 4+
   PRs are already open, the binding constraint is the owner's review time, not
   your output — ship the smallest useful change, or none, and say which you
   chose and why.** Count the PR you are about to open when you apply that
   threshold; it is the one that tips the queue. Gates: full
   backend suite green and frontend build green. Backend: run from the repo
   root as `python3 -m pytest backend/tests -q` (locally, where the repo-root
   venv exists, `.venv/bin/python -m pytest backend/tests -q`). Frontend:
   `cd frontend && npm ci && npm test && npm run build` — the `npm ci` matters
   in a fresh checkout, which has no node_modules. Both gates apply whenever
   either side changed; a backend-only diff still needs the frontend build if
   it touched a shared fixture. The pytest module form
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
    Do NOT review your own PR. Three reviewers cover it, and only one of them
    re-reviews a later push on its own: the Claude Auto Review GitHub Action.
    The other two must be asked, so **after every push that you expect to be
    the last one, post two comments on the PR: `@coderabbitai review` and
    `@codex review`.** CodeRabbit does nothing without that comment (the repo
    is under its 10-star threshold — it posts "this repository does not receive
    automatic reviews" and stops) and a trigger posted before a later push is
    voided by it ("Head commit changed"), so post it last. Codex
    (`chatgpt-codex-connector[bot]`) reviews the PR once when it is opened — a
    👍 reaction on the PR is its "nothing to say", otherwise inline P1/P2
    comments — but never looks at later commits unless told `@codex review`.
    Treat both bots' findings like the Action's: verify each against the code,
    push the fix, re-trigger both. If a trigger produces nothing, say so in the
    report rather than assuming it ran. The owner may also run Codex separately
    and relay findings in chat, so a quiet PR is still not a pass. Stay
    subscribed to the PR and address findings as event wakes deliver them —
    that is how a PR reaches green with no owner intervention. Do not block your
    Phase 4 report waiting on reviews that have not arrived yet; the session
    will wake when they do.
11. Changelog housekeeping: when a previous PR has merged, move its [Unreleased]
    entries under a dated heading with the PR number. Insert the new heading
    ABOVE the entries — never overwrite the [Unreleased] line itself, or the
    entries end up filed under the wrong PR while another stays stranded.
    Verify afterward that every heading's (PR #N) tag matches its entries'.
    **Do this on a `chore/changelog-<date>` branch off main, NOT on your working
    branch — you are explicitly authorized to create and push that one branch,
    as an exception to working only on your assigned branch.** CI's
    `changelog-guard` job fails any PR that adds or removes a dated heading from
    any other branch, so bundling this into a feature PR turns it red by
    construction. First check whether a `chore/changelog-*` PR is already open:
    if one is, do nothing — it owns the task. That check plus the dedicated
    branch is what stops the race where four PRs each dated the same section.

PHASE 4 — Report (always):
12. End with a "Top picks" section: the 2–3 highest-leverage next actions and why.
13. Report the review queue measured in step 1. If nothing has merged in 3+
    days, or 4+ PRs are open (counting any you opened today), say so FIRST in
    the notification, ahead of what you shipped — at that point the binding
    constraint is the owner's review time, not the routine's output, and a run
    that reports only its own work hides the one fact that should change what
    the owner does next. Say which build choice the depth led you to in step 7.
14. Send exactly one notification: lead with queue depth if it tripped the rule
    above, otherwise with what shipped or broke, then top picks — include the PR
    link if one was opened. State plainly anything you could not finish and why.
    If truly nothing changed and nothing shipped, stay silent — **unless the
    queue tripped the step 13 rule, which is never silent.** A run that shipped
    nothing *because* the queue is deep is exactly the run whose one fact the
    owner needs, and the silence rule would otherwise suppress precisely that
    notification.
```

### Rationale

- **Decisions are required output.** The original prompt asked only for ideas; whether
  an item needs planning first, and whether it should be delegated, had to be requested
  after the fact. Now every idea carries an effort/planning/execution verdict.
- **Persistent state.** Without `docs/BACKLOG.md`, each run re-derives the project state
  from scratch and can re-pitch already-shipped ideas. The backlog is the memory.
- **Changelog as prod ground truth — of scope, not of quality.** `main` is continuously
  deployed, so the changelog as it reads on `origin/main` describes exactly what
  production is running; unmerged or abandoned work never appears there. Reading it
  first (instead of raw git log) gives the run an instant, curated picture of recent
  shipped work, and the branch's [Unreleased] diff against it shows what's still
  awaiting review/merge. It is not evidence that the shipped code is *correct* — a
  merged bug is described there just as confidently as a working feature. Correctness
  comes from the health check, the test suites, and review findings.
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
- **Reviewers, none of them the author — but count them honestly.** The Auto Review Action
  authenticates with the owner's subscription (`CLAUDE_CODE_OAUTH_TOKEN`), so it costs no
  API credits and reviews from a context that never saw the code being written.
  **Codex reviews on the PR** as `chatgpt-codex-connector[bot]` — verified 2026-09-07
  on PR #77 (three inline P2 findings, all correct) and 2026-09-08 on PR #78, where it
  found that the fix for its own first finding was inert. The docs had said Codex "will
  never appear on the PR" and told runs not to look for it there, which by then meant
  ignoring the reviewer with the best hit rate on this repo. It reviews once on PR open
  (a 👍 reaction is its "nothing to say" — PRs #72 and #76 got one) and otherwise only
  when told `@codex review`, so the second pass on #78 only happened because the run
  asked for it. The owner may still run Codex separately and relay findings in chat, so
  a quiet PR is not a pass. The routine deliberately does NOT also review in-session:
  the author reviewing their own work is the weakest possible pass.
  **CodeRabbit does not review without being asked** (under its 10-star threshold; the
  loss was noticed and recorded in the backlog on 2026-08-31, and every PR from #71 on
  has carried only the notice *"This repository does not receive automatic reviews
  because it has fewer than 10 stars"* until a `@coderabbitai review` comment was posted
  by hand — it is a policy on their side, not a misconfiguration here). It still reads
  `.coderabbit.yaml` and quotes the config back in the notice, which is what made the
  loss easy to miss. This mattered because the prompt used the *count* of reviewers as
  its reason not to self-review: a premise that has silently gone from three to two is
  worse than no premise. The two trigger comments after the final push are the cheap
  fix and are now step 10; ten stars or a paid plan are the alternatives, and both are
  the owner's call.
- **Queue depth is reported before output.** The routine ships 1–2 quick wins a day and
  cannot merge anything, so if the owner stops merging, its PRs accumulate silently —
  each run reads a `main` that is further behind the work, and every branch's
  `[Unreleased]` changelog entry becomes a conflict against the others. This has already
  bitten twice: eight PRs were open at once on 2026-08-31, and six on 2026-09-07 with
  nothing merged for a week. The run always knew this and never said it, because the
  report was scoped to what the run itself did. "Nothing has merged in N days" is the
  single fact that changes what the owner should do with the run, so it now leads.

---

## Routine B — Weekly deep review

Runs Sundays at 9:00 PM EDT.

```text
Weekly deep review. Every PR this week was already reviewed line-by-line by the
Claude Auto Review Action, by Codex (`chatgpt-codex-connector[bot]`, on the PR),
and by CodeRabbit when a `@coderabbitai review` comment was posted — and possibly
by the owner running Codex outside GitHub, which leaves no record, so do not try
to verify that coverage. Do NOT repeat diff-scoped review; you exist to find what
it structurally cannot see. Read whole files and whole subsystems, not diffs.
If you open a PR, the same rule as the daily routine applies: after your final
push, post `@coderabbitai review` and `@codex review` on it.

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

```text
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
