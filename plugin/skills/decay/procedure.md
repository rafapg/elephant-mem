# `decay [--yes]`

Load `../_shared/core.md` first (always). This file is the `decay` procedure.

Narrower than `maintain`: this ONLY expires stale `status: open` loops in
`knowledge/tracking/loops/` — it never touches facts, entities, or
confidence (that stays `maintain`'s job). The deterministic half lives in
`scripts/decay-loops.py`; this procedure is the review/commit wrapper around
it.

## Procedure

1. **Roll the recall record, then dry-run.** From `<bundle>`, first run
   `python3 scripts/recall.py roll`. It folds every consumption line written
   since the last roll into `state/recall.json`'s buckets — that record is an
   input to the scan below, so rolling here is what keeps it fresh where it is
   read. It writes nothing when the log is empty or absent, and a failure is
   not fatal to this run: carry on and let the scan read the record as it
   stands (an unrolled line only makes a loop look less recently cited than it
   is).

   Then run `python3 scripts/decay-loops.py`. It scans every `status: open`
   loop, computes its last-activity date (the max of `updated` / `opened` /
   `created`, whichever are present, and the date `state/recall.json` last
   records the loop as cited by an answer), and lists every one older than
   `elephant.json` -> `decay.loop_expiry_days` (default 45 — same defensive
   fallback as `hub_max_facts`) as a candidate, one per line with its age in
   days, plus a trailing count. The scan is read-only, and the roll before it
   writes only `state/recall.json` — no knowledge file changes yet.

   If the count is 0, say so and stop — there is nothing to do this run.

2. **Review gate.**
   - **Interactive invocation (default):** present the candidates to the
     user **in batches of 5–10** — path, description, age in days — and ask
     which to expire: approve all, approve some, or reject some.
     - Any **rejected** candidate is *snoozed*, not skipped silently: bump its
       `updated:` field to today (a plain frontmatter edit, no other change).
       This is a deliberate, human-reviewed re-affirmation that the loop is
       still alive, so it is fair to reset the clock exactly like a genuine
       re-mention would — it simply won't surface again until it goes stale
       for another full `loop_expiry_days` window.
   - **Unattended invocation** (`--yes`, or run from a scheduled task — see
     Cadence): skip the review gate entirely and treat every candidate as
     approved.

3. **Apply.** Run `python3 scripts/decay-loops.py --apply`. It re-scans (so
   any snooze from step 2 already took effect) and, for every remaining
   candidate, flips `status: open` → `status: expired` and stamps
   `expired: YYYY-MM-DD`. It never deletes a file and never touches
   `done` / `dropped` / already-`expired` loops.

4. **Rebuild + validate.** `python3 scripts/build-index.py` then
   `python3 scripts/validate-okf.py` — both must pass. This is what actually
   removes the newly-expired loops from `tracking/open-loops.md`, the
   router's open-loop count in `knowledge/index.md`, and `manifest.jsonl`,
   and re-files them into the history section of any entity backlinks that
   reference them. On failure: do NOT commit; log the error and stop (the
   next run retries — loop files are already written, so nothing is lost,
   only the derived surfaces need a successful rebuild).

5. **Log + commit.** Append one dated line to `knowledge/log.md`:
   `**Decay**: N loops expired (>Xd stale)` (X = the effective
   `loop_expiry_days`). Then `git -C <bundle> add -A && git -C <bundle>
   commit -m "decay: N loops expired (>Xd stale)"`. **Never push.** If step 1
   found 0 candidates, there is nothing to commit — skip this step entirely.

## Cadence

Run every 3 days (daily is also fine; loop staleness moves slowly, so there is
no benefit to running more often than `catch-up`). Configure it as a
scheduled task with `--yes` so it runs unattended, exactly like `catch-up`'s
scheduling model (see `../catch-up/SKILL.md`) — permissive permission mode,
worktree off (it commits in place), one manual "Run once" after creating the
schedule to pre-approve prompts. A manual, review-gated
`elephant-mem:decay` invocation any time the open-loops board feels cluttered
also works — the two modes share the same script and procedure, they only
differ at the review gate in step 2.

**Re-mention resets the clock — this is the whole mechanism.** A loop's
`updated:` field is bumped by `catch-up`/`capture` whenever a later source
corroborates the same commitment, or by this procedure's own review-gate
snooze (step 2). `decay` only ever *reads* `updated` (falling back to
`opened`/`created`) — it never decides on its own that a loop was
re-mentioned. Use is the other half of that clock: a loop the owner's own
answers keep citing carries a recent date in `state/recall.json`, and the scan
reads it as a fourth activity date. So a loop escapes decay indefinitely by
genuine, periodic re-affirmation — from real sources, from a human reviewer, or
from being consulted.
