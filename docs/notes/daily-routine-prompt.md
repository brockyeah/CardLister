# Daily Review Routine — Improved Prompt

Drop-in replacement for the scheduled prompt that drives the daily project review.
Revised 2026-07-25 based on what the first runs were missing.

---

## The prompt

```
Daily project review + build session. Work through these phases in order.

PHASE 1 — Health check (always):
1. Check repo state: open PRs (drive any of ours toward green), open issues, CI status
   on main, and security/dependency alerts. If production is reachable, hit /api/health.
2. Read the changelog AS IT EXISTS ON MAIN (`git show origin/main:CHANGELOG.md`) — main
   is what production runs, so its changelog is the ground truth of what has actually
   shipped; nothing half-baked appears there. Compare against the working branch's
   [Unreleased] section to see what's built but not yet merged, and treat unmerged
   work as "get it reviewed/merged" before piling more on top.
3. Read docs/BACKLOG.md — it is the persistent ledger between runs. Never re-propose
   anything in its Shipped section or already recorded in the changelog.

PHASE 2 — Ideas (always):
4. Propose 3–5 new feature/implementation ideas not already in the backlog, grounded in
   the current code. For EVERY idea, you must decide and state:
   - effort: quick win (≤ half day) / medium / long-term
   - planning: implement directly, or write a plan/spec doc first (anything touching
     schema, auth, money, or 3+ subsystems requires a plan doc)
   - execution: inline, or delegated to subagents (delegate only when work items don't
     touch overlapping files; otherwise stay inline)
   These decisions are required output, not optional commentary.
5. Merge the surviving ideas into docs/BACKLOG.md.

PHASE 3 — Build (standing authorization):
6. Implement the top 1–2 quick wins from the backlog without asking. Gates: full backend
   test suite green, frontend build green, then commit per feature and push to the
   designated branch. In the same push: update the backlog's Shipped section AND add a
   CHANGELOG.md entry under [Unreleased] for every shipped feature — a feature without
   a changelog entry is not done. Never edit dated (merged) changelog sections; those
   only change when a PR merges to main.
7. Use Claude skills where they apply — /security-review after auth/upload/query changes,
   /simplify after large diffs, dataviz before building any chart or dashboard UI.
   On Mondays, run a deeper pass: dependency updates + /security-review of the full app.
8. Open a PR automatically: if the branch has shipped work and no open PR, open one
   against main whose body summarizes the [Unreleased] changelog entries, then
   subscribe to its activity and drive it to green — fix CI failures and address
   review comments in follow-up wakes. Never merge it yourself; merging is the
   owner's call.
   After opening (or when new commits land on an open PR), run the /review skill on
   it as a second-opinion code review and post the findings on the PR. This runs
   inside this session, so it draws from the Claude subscription — it replaces the
   retired API-credit auto-review workflow.
9. Changelog housekeeping: if the previous run's PR has merged since last run,
   restart the branch from origin/main, then move the merged [Unreleased] entries
   under a dated heading with the PR number (this lands in the next PR).

PHASE 4 — Report (always):
10. End with a "Top picks" section: the 2–3 highest-leverage next actions and why.
11. Send exactly one notification: lead with what shipped or broke, then top picks —
    include the PR link if one was opened. If truly nothing changed and nothing
    shipped, stay silent.
```

## Rationale for the changes

- **Decisions are required output.** The original prompt asked only for ideas; whether an
  item needs planning first, and whether it should be delegated, had to be requested
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
- **Skills are named, not implied.** `/security-review`, `/simplify`, and `dataviz` only
  get used if the prompt tells the run when they apply.
- **Health check first.** A red CI run or a down production instance matters more than
  brainstorming; check it before spending the run on ideas.
- **Top picks + notification discipline.** Always end with ranked recommendations, and
  cap it at one notification so the routine stays worth subscribing to.

- **Auto-PR with a hard stop at merge.** Each run's shipped work gets a PR opened and
  babysat automatically (CI green, review comments addressed), but merging stays a
  human decision — that's the gate that keeps main (and therefore the prod changelog)
  trustworthy. The post-merge housekeeping step keeps branch and changelog cycling
  cleanly run over run.

## Possible future upgrades

- Split cadences: daily light run (phases 1, 3, 4) vs weekly deep run (adds ideation,
  dependency updates, full security pass) to keep daily token cost down.
- Track a simple metric in the backlog (cards listed/week from the DB if reachable) so
  ideas can be prioritized against actual usage instead of intuition.
