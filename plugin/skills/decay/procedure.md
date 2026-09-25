# `decay [--yes]`

Load `../_shared/core.md` first (always). This file is the `decay` procedure.

Narrower than `maintain`: this ONLY expires stale or out-of-scope
`status: open` loops in `knowledge/tracking/loops/` — it never touches facts,
entities, or confidence (that stays `maintain`'s job). The deterministic half
lives in `scripts/decay-loops.py`; this procedure is the review/commit wrapper
around it.

## Preflight

Run the check described in `../_shared/core.md` → **Preflight** before step 1.
This procedure's first act is to run two bundle scripts, and both of them —
`recall.py` and `decay-loops.py` — are files the check compares. On the bundle
that motivated it, `recall.py` was missing outright and `decay-loops.py` was
four releases behind: `recall.py roll` failed on every hourly `catch-up`,
`state/recall.json` had never been written, and step 1's scan was reading a
loop's activity without its fourth date. Nothing in the run said so, and it went
on expiring loops.

On **required drift**, the two cadences part, because they differ in whether
anyone is there to read a stop:

- **Interactive** (`elephant-mem:decay`, no `--yes`): stop before step 1 and
  relay the check's stderr — it already names the drifted files and both routes
  out — in `conversation_language`. Nothing is rolled, scanned, expired or
  committed.
- **Unattended** (`--yes`, or fired by the schedule — see **Cadence**): nobody
  reads a stop, so take the environment-failure path `catch-up` uses
  (`../catch-up/procedure.md` → **Degradation**, the stale-scripts branch) and
  end the run there. Roll nothing, expire nothing. Append one dated line to
  `knowledge/log.md` as `**Decay**: environment failure (bundle scripts stale)`,
  naming the drifted files and the two routes out; run `python3
  scripts/backlog.py add bundle-scripts-stale --summary … --evidence …` — the
  same id `catch-up` files, so a bundle whose hourly routine already filed it
  bumps `seen` rather than opening a second item for one cause, and **read its
  exit code**, because a filing that failed is not a record; then commit
  **only** that log line and the backlog file, message
  `decay: environment failure (bundle scripts stale)`. Do not run
  `build-index.py` or `validate-okf.py`: they are two of the drifted files, and
  there is nothing to rebuild. If `backlog.py` is itself among the files the
  check listed — **listed, not missing**: the required set drifts whether a
  file is absent or merely differs, and a `backlog.py` four releases behind is
  the failure this check exists to catch — the log line is the whole record.
  Same if it ran and exited non-zero.

Any other outcome: go on to step 1, and carry the check's one line into this
run's report when it left one.

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
   loop and lists two kinds of candidate. First, at any age, every open loop
   that names the bundle owner (`elephant.json` -> `owner.slug`) in none of
   `owner`, `owed_to`, `entities`, labelled out of scope: a commitment between
   other people, which the loop lane does not track. That test reads no date,
   so neither a recent `updated:` nor a recent citation keeps such a loop in
   the lane. Without `owner.slug` this half is skipped, with one note on
   stderr saying so, and likewise when `owner.slug` names no entity file (the
   owner's entity was renamed or merged and `elephant.json` still has the old
   slug) or when no open loop names the owner at all. Relay that note to the
   user: until `owner.slug` is fixed, only stale loops expire. Then, for every other open loop, it computes its
   last-activity date (the max of `updated` / `opened` / `created`, whichever
   are present, and the date `state/recall.json` last records the loop as
   cited by an answer), and lists every one whose last activity is
   `elephant.json` -> `decay.loop_expiry_days` days back or more (default 30;
   the comparison is `>=`, so a loop exactly that old is a candidate, with the
   same defensive fallback as `hub_max_facts`) as a stale candidate, one per
   line with its age in days. The trailing count splits out of scope from
   stale. The scan is read-only, and the roll before it writes only
   `state/recall.json` — no knowledge file changes yet.

   If the count is 0, say so and stop — there is nothing to do this run.

2. **Review gate.**
   - **Interactive invocation (default):** present the candidates to the
     user **in batches of 5–10**, in the script's order (out of scope first),
     each shown with its path, description, `owner` and the label the script
     gave it (out of scope, or its age in days), and ask which to expire:
     approve all, approve some, or reject some.
     - Any **rejected stale** candidate is *snoozed*, not skipped silently:
       bump its `updated:` field to today (a plain frontmatter edit, no other
       change).
       This is a deliberate, human-reviewed re-affirmation that the loop is
       still alive, so it is fair to reset the clock exactly like a genuine
       re-mention would — it simply won't surface again until it goes stale
       for another full `loop_expiry_days` window.
     - Any **rejected out-of-scope** candidate cannot be snoozed, because the
       scope rule ignores dates. Ask whether the owner owes it or is waiting
       on it. If so, it is a *claim*: add the owner's entity link
       (`/entities/person/<owner.slug>.md`) to `owner` or to `owed_to`
       accordingly, and bump `updated:` to today, so the `--apply` re-scan no
       longer lists it. If neither, write nothing and leave it out of this
       run's `--apply` (step 3), and tell the user that the next unattended
       run will expire it, since a commitment the owner neither owes nor is
       owed is not a loop.
   - **Unattended invocation** (`--yes`, or run from a scheduled task — see
     Cadence): skip the review gate entirely and treat every candidate as
     approved.

3. **Apply.** Run `python3 scripts/decay-loops.py --apply`. It re-scans (so
   any snooze or claim from step 2 already took effect) and, for every
   remaining candidate, flips `status: open` → `status: expired`, stamps
   `expired: YYYY-MM-DD`, and appends a `**Resolution:**` paragraph to the
   body saying which kind of expiry it was: the silence, with its dates, or
   the scope verdict. That is the same place and the same shape `close-loops`
   writes its closure paragraph in, so `tracking/resolved-loops.md` reads both
   the same way. It never deletes a file and never touches `done` /
   `dropped` / already-`expired` loops.

   Pass every out-of-scope candidate rejected without a claim in step 2 as
   `--except <link>` (its bundle-absolute path, one flag per loop), so this
   `--apply` leaves it open and untouched: the re-scan would otherwise list it
   again, since the scope test reads no date. `--skip-sweep` is accepted and
   ignored: this script no longer reads `state/closure-sweep.json`.

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
   `**Decay**: N loops expired (M out of scope, K >=Xd stale)` (X = the
   effective `loop_expiry_days`; N is what was actually written). Then
   `git -C <bundle> add -A && git -C <bundle> commit -m "decay: N loops
   expired (M out of scope, K >=Xd stale)"`. **Never push.** If step 1 found 0
   candidates, there is nothing to commit — skip this step entirely.

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

**Re-mention resets the clock: this is the whole mechanism.** A loop's
`updated:` field is written by the ingest core on every ingest path
(`../ingest/procedure.md`, steps 2 and 4, written at step 7), when a source
that speaks to an open loop re-raises it without closing it: the bump is
dated by the source (today for `capture`, whose source is the user) and never
moved backwards. It is also written by this procedure's own snooze and claim
(step 2). `decay` only ever *reads* `updated` (falling back to
`opened`/`created`) — it never decides on its own that a loop was
re-mentioned. Use is the other half of that clock: a loop the owner's own
answers keep citing carries a recent date in `state/recall.json`, and the scan
reads it as a fourth activity date. So a loop escapes decay indefinitely by
genuine, periodic re-affirmation — from real sources, from a human reviewer, or
from being consulted.
