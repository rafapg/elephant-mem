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
   read. It writes no record when the log is empty or absent, and a failure is
   not fatal to this run: carry on and let the scan read the record as it
   stands (an unrolled line only makes a loop look less recently cited than it
   is). It also appends the `state/` ignore rules to `<bundle>/.gitignore` when
   a bundle predates them, so this run's own `git add -A` cannot commit the
   record of which people were looked up and when. If it cannot confirm those
   rules it writes nothing and exits non-zero. That one is not the ordinary
   failure above: the scan still runs and still reads the record as it stands,
   but nothing in this run may commit until the `.gitignore` is fixed, so stop
   before the write step and report the refusal with the reason the roll
   printed.

   Then run `python3 scripts/decay-loops.py`. It scans every `status: open`
   loop, computes its last-activity date (the max of `updated` / `opened` /
   `created`, whichever are present, and the date `state/recall.json` last
   records the loop as cited by an answer), and lists every one whose last
   activity is `elephant.json` -> `decay.loop_expiry_days` days back or more
   (default 45; the comparison is `>=`, so a loop exactly that old is a
   candidate — same defensive fallback as `hub_max_facts`) as a candidate, one
   per line with its age in days, plus a trailing count. Each line also says whether
   `state/closure-sweep.json` clears that loop for expiry or holds it back, and
   the trailing count is followed by the split — the dry run is where you see
   how much of this run's lane `close-loops` has actually examined. The scan is
   read-only, and the roll before it writes only `state/recall.json` — no
   knowledge file changes yet.

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
   candidate the gate below clears, flips `status: open` → `status: expired`,
   stamps `expired: YYYY-MM-DD`, and appends a `**Resolution:**` paragraph to
   the body saying what the silence was — the same place and the same shape
   `close-loops` writes its closure paragraph in, so
   `tracking/resolved-loops.md` reads both the same way. It never deletes a
   file and never touches `done` / `dropped` / already-`expired` loops.

   **The gate.** `--apply` expires a candidate only if
   `state/closure-sweep.json` shows `close-loops` examined it on or after its
   own last activity and recorded `outcome: open` for it. Two details the
   script is strict about, because both once let a loop through on something
   nobody checked: "last activity" here is the loop's three **file** dates
   only, the same ones `close-loops` reads, so a citation can keep a loop out
   of the candidate list but never out of the gate; and the outcome is a
   whitelist, so an unreadable or future examination date, an off-vocabulary
   outcome and an entry carrying no outcome at all all read as never examined.
   That record is written by the
   `close-loops` routine — see `../close-loops/procedure.md` → **The sweep
   record** for its shape and the one command that writes it; nothing here
   writes it, and it must not be hand-edited. A candidate the record does not
   cover is **held back**: the script names it, prints
   `python3 scripts/close-loops.py`, and exits 0. That is not a failure, and
   not something to work around — expiry is a verdict of silence, and silence
   no routine has read is not evidence. Report the held-back count to the user
   and let the next run take them, once `close-loops` has been round.

   Losing the record therefore parks decay rather than corrupting it: every
   loop reads as never examined and nothing expires. `--skip-sweep` is the
   deliberate way out, and the only one — it bypasses the gate entirely and
   expires every candidate on its dates alone, which is what this script did
   before the gate existed. Use it when the record is genuinely gone, say so
   in the run's report, and never as the default of a scheduled run.

   **If everything was held back, nothing was written.** Skip steps 4 and 5:
   there is no rebuild to do and nothing to commit.

4. **Rebuild + validate.** `python3 scripts/build-index.py` then
   `python3 scripts/validate-okf.py` — both must pass. This is what actually
   removes the newly-expired loops from `tracking/open-loops.md`, the
   router's open-loop count in `knowledge/index.md`, `manifest.jsonl`, and the
   entity hubs that backlink them. A resolved loop is **not** re-filed as a
   history line on those hubs — it leaves them outright, and its one listing
   from then on is `tracking/resolved-loops.md`, which this rebuild writes
   newest first with each loop's date, its outcome and the first sentence of
   its `**Resolution:**`. On failure: do NOT commit; log the error and stop (the
   next run retries — loop files are already written, so nothing is lost,
   only the derived surfaces need a successful rebuild).

5. **Log + commit.** Append one dated line to `knowledge/log.md`:
   `**Decay**: N loops expired (>=Xd stale)` (X = the effective
   `loop_expiry_days`; N is what was actually written, held-back candidates
   excluded). Then `git -C <bundle> add -A && git -C <bundle>
   commit -m "decay: N loops expired (>=Xd stale)"`. **Never push.** If step 1
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
`updated:` field has exactly two writers: `catch-up` step 4, which bumps it to
a source's date when that source re-raises an open loop without showing it
done, and this procedure's own review-gate snooze (step 2). `capture` is not
one of them — it opens loops and never returns to one, so nothing it does
resets a clock. `decay` only ever *reads* `updated` (falling back to
`opened`/`created`) — it never decides on its own that a loop was
re-mentioned. Use is the other half of that clock: a loop the owner's own
answers keep citing carries a recent date in `state/recall.json`, and the scan
reads it as a fourth activity date. So a loop escapes decay indefinitely by
genuine, periodic re-affirmation — from real sources, from a human reviewer, or
from being consulted.
