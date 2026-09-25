---
status: done
created: 2026-09-24
slug: loop-lifecycle
review: resolved
---

# Loop lifecycle: a loop is the owner's, and silence alone ends it

The loop lane files commitments nobody owes the owner and nobody asked the owner
for, then waits for a sweep that almost never reaches a verdict before it lets
silence end them. This spec narrows what becomes a loop, moves the rules that
keep a live loop alive into the one core every ingest path runs, and lets
`decay` act on silence without waiting for `close-loops`.

It reverses three decisions of `.bb/loop-decay/spec.md`: the per-loop sweep
gate on `--apply` (its E15, E16, E18), "`dropped` stays a hand-set state", and
"no new frontmatter field on the loop template". The last one is reversed
deliberately and safely: `owed_to` is optional, and every rule that reads it
also reads `owner` and `entities`, so a legacy loop without the field behaves
exactly as the rules say it should.

## The problem, measured

Measured on the owner's bundle (`~/elephant-mem`) on 2026-09-24.

- **2317 loop files**: 987 `open`, 1015 `expired`, 307 `done`, 8 `dropped`.
- **60% of them (1390) are not the owner's.** The bundle owner is neither in
  `owner` nor in `entities`. Among the 987 open loops the share is higher: 740
  name the owner nowhere, 173 carry the owner in `owner`, 74 only in
  `entities`.
- **Duplicates are not the problem.** Among open loops there is about 1 true
  duplicate pair. The 263 "similar" pairs (same owner, shared entities, at most
  14 days apart) are sibling tasks with distinct deliverables, not duplicates.
- **The sweep does not close.** The last three `close-loops` runs closed 0, 0
  and 1 of 25 examined. Since `decay --apply` expires only what that sweep has
  examined and left open, expiry is paced by a routine whose verdict is almost
  always "open". Today's dry run: 202 candidates at 45 days, 5 cleared, 197
  held back.
- **The window is too wide.** Of the owner's own `done` loops, 66% closed
  within 7 days of opening, 86% within 21, 86% within 30 and 93% within 45. The
  curve is flat between 21 and 30, so 30 days loses almost nothing that 45
  catches. 109 of the owner's open loops (the 247 in scope: owner in `owner` or
  in `entities`) are silent for 30 days or more on their file dates: 72 of the
  173 owner-owned, 37 of the 74 entities-only.
- **The clock only resets on one path.** The rule that closes a loop a source
  shows delivered, and the rule that bumps `updated:` when a source re-raises
  it, live only in `catch-up` step 4. `ingest`, `ingest-audio` and `capture`
  never touch an existing loop, so a commitment re-raised through them ages as
  if nobody had spoken of it.

**What the first run does.** Re-measured on the same bundle with the
`state/recall.json` citation counted as the fourth activity date: 73 of those
109 were cited within the last 30 days (72 owner-owned, 61 of them on
2026-09-05), so only 36 are stale candidates. The first `decay` run after this
change therefore expires about 776 loops (740 out of scope, 36 stale) and
leaves about 211 open. The 61 cited on 2026-09-05 reach 30 days of silence
around 2026-10-05 unless cited or re-raised again.

## Decisions

- **D1. Scope.** A loop exists only when it relates to the bundle owner.
  "I owe": the owner's entity is in `owner`. "Owed to me": someone else is in
  `owner` and the owner is waiting on the delivery, recorded in `owed_to`. A
  commitment between third parties becomes a **fact**, still visible to
  `briefing` and `query`, never a loop. Nothing is dropped for relevance: only
  the lane changes.
- **D2. Creation bar**, in the shared ingest core, three filters, strongest
  first. The lane decision is made at `ingest` step 2 routing, as decided;
  the parts that need resolved entities run where entities exist:
  1. relation to the owner (I owe, or owed to me). Being in the same meeting,
     channel or thread does not count. Step 2 decides it on names (the owner by
     `owner.name` and context); step 3 confirms it on links, and a loop
     candidate whose resolution leaves the owner's entity in neither `owner`
     nor `owed_to` is filed as a fact;
  2. an **observable** closure signal: if you cannot write what an ingested
     source would show on delivery, it is a fact, not a loop (step 2);
  3. a re-mention updates instead of creating: after entity resolution, next
     to step 4 dedup, the candidate is compared against existing
     `status: open` loops, and if one already covers the same commitment, the
     source acts on that loop. Sibling tasks (same project, distinct
     deliverables) are not merged.

  Every loop write the core decides (new loop, close, drop, bump, refine) is
  performed at step 7 (persist), so `--review`, which persists only what
  survives its gate, gates loop writes too.
- **D3. The closure signal is mutable, with provenance.** It may be refined
  after creation (deadline moved, scope shrank, deliverable changed) only by a
  source that speaks to the commitment, the same bar as a re-mention. The
  previous version is kept in the loop body with the date and the
  bundle-absolute source link of the change, in a `**Closure signal
  history:**` section directly after the `**Closure signal:**` section. Never a
  silent edit. A `**Resolution:**` written later goes at the end of the body,
  after any history section. `close-loops.py` keeps reading only the current
  `**Closure signal:**` paragraph: its regex already stops at a blank line or
  at the next bolded lead-in (`\n\*\*[^*\n]+:\*\*`), which
  `**Closure signal history:**` is, and a test pins that.
- **D4. The clock resets on every ingest path.** The close and bump rules move
  out of `catch-up` step 4 into the ingest core, so `ingest`, `ingest-audio`,
  `catch-up` and `capture` inherit them. A source showing delivery closes the
  loop (`done`). A source re-raising it without closing it bumps `updated:` to
  the source's own date (for `capture`, the user in the conversation is the
  source and the date is today). Same re-mention bar as before: chasing,
  rescheduling or reporting it blocked counts; merely naming the same people or
  project does not. Every doc that says `updated` has "exactly two writers" or
  that "`capture` is not a writer" is rewritten. See addition A1 for the
  never-backwards guard.
- **D5. Expiry is silence alone, at 30 days.** `decay.loop_expiry_days`
  defaults to 30 (was 45), a single value. The sweep gate is removed from
  `decay` entirely: `decay-loops.py` no longer reads
  `state/closure-sweep.json`. Kept: the `**Resolution:**` paragraph on expiry,
  the interactive review gate with its snooze, and the `state/recall.json`
  citation as the fourth activity date. `close-loops` stays, as an optional
  sweep hunting loops that are done or obsolete; `state/closure-sweep.json`
  remains only its own queue control.
  - **`--skip-sweep` stays accepted as a deprecated no-op.** It prints one
    stderr note and changes nothing. Removing it would make argparse exit 2 on
    any schedule prompt, script or habit that still passes it, and an
    unattended `decay` that exits 2 simply stops expiring with nobody reading
    the error. One argparse line is the cheaper side of that trade.
- **D6. Obsolete by evidence.** Reuse `status: dropped`, no new vocabulary, with
  a `**Resolution:**` citing the fact that killed the premise (counterpart left
  the company, project cancelled, a later decision made it irrelevant), plus
  `closed` and `closed_by` exactly like `done`. Writers: `close-loops` (the
  sweep) and the ingest core (the flow), the same two that write `done`.
  `dropped` can still also be set by hand. Every "`close-loops` never writes
  `dropped`" and "`dropped` stays a hand-set state" is removed.
- **D7. No due-date field.**
- **D8. Every terminal status is final.** `done`, `dropped` and `expired` are
  never reopened. A re-mention of an expired loop creates a **new** loop, and
  the D2 dedup compares against `open` loops only.
- **D9. No expiry notices in any daily routine.** `start-day`, `end-day` and
  `push-start-day` carry none today (checked: none of their files mentions
  expiry), and none is added.
- **Migration of third-party loops: a continuous rule, not a one-off.**
  `decay-loops.py` expires, immediately and regardless of age, any
  `status: open` loop where the bundle owner's slug (`elephant.json` ->
  `owner.slug`, the entity `/entities/person/<slug>.md`) appears in none of
  `owner`, `owed_to`, `entities`. Its `**Resolution:**` says the loop is out of
  the lane's scope, a third-party commitment. Loops that mention the owner in
  `entities` stay and decay normally on the 30-day clock. If `owner.slug` is
  missing, the out-of-scope rule is skipped (never expire everything);
  likewise when it names no entity file under `knowledge/entities/`, or when
  no open loop names the owner at all (added at review: `rename-entity.py`
  never updates `elephant.json`, so a renamed owner leaves a stale slug).
  Interactive `decay` shows these candidates in the review batches like the
  others; unattended runs apply them.
  - **The scope test ignores every activity date**, citations included: a
    recent `updated:` or a citation does not keep a third-party loop in the
    lane.
  - **Compared by slug, kind-agnostic**, with the same `slug()` normalization
    `close-loops.py` uses (last path segment, `.md` stripped, lowercased,
    quotes removed). A stricter full-path match would expire a loop whose owner
    link was hand-written as a bare slug, and expiry is the irreversible side,
    so the permissive comparison is the safe one.
  - **Only `owner.slug` is read**, never `owner.name`, unlike
    `close-loops.py`'s `owner_slug()`. A name is not an entity link.
- **`owed_to` field.** `templates/open-loop.md` gains `owed_to: []`,
  bundle-absolute entity links of who is waiting on the delivery. An "owed to
  me" loop carries the bundle owner there.
  - **`validate-okf.py` does not check it.** It validates no frontmatter link
    list today (see "Found while mapping"), so the condition for adding a check
    is not met. A legacy loop lacking the field can therefore never fail
    validation.
  - **Readers, kept to the minimum the rules need**: `decay-loops.py` (the
    scope test); `close-loops.py`, which only prints it (text proposal and
    `--json`), with no change to ranking or to what counts as new material;
    and `build-index.py`, whose `manifest.jsonl` rows for open loops carry
    `owner` and `owed_to` (addition A4, required by D2 filter 3).
    `rename-entity.py` needs no change for `owed_to`: it rewrites links by
    whole-text replacement. It never rewrites `elephant.json`, which is why
    `decay` checks that `owner.slug` names an entity (E1). Not readers, by choice: the
    entity hub backlinks and `briefing.py --entity` (see Out of scope).
- **Entity trigger (cascade obsolete when a person leaves): out of scope.**
- **`close-loops.py` does not skip out-of-scope loops.** They leave the lane on
  the next `decay` run (every 3 days, unattended), and no new ones are created
  once D2 is live, so the population is transient. A second copy of the scope
  rule inside the queue would be one more mirrored rule between the two scripts,
  and every earlier mirror between them (the examination date, the settled
  test) ended in a deadlock that took a fix to find. And a `done` by evidence
  is a better end for such a loop than an out-of-scope expiry.
- **Release.** `elephant-mem` only, `0.1.0-beta.16` -> `1.0.0-rc.1`, in the
  same PR. No file under `elephant-wiki/` changes (`wiki.py` reads no loop
  field), so the wiki is not bumped. The default of `loop_expiry_days` lives in
  exactly three places: `DEFAULT_EXPIRY_DAYS` in `decay-loops.py`, and the
  prose of `decay/SKILL.md` and `decay/procedure.md`. It is in neither the seed
  `elephant.json.example` nor `docs/configuration.md`, which documents no
  `decay` key at all; this change adds the entry there. A bundle with an
  explicit `decay.loop_expiry_days` keeps its value (`update` never re-syncs
  `elephant.json`), which the CHANGELOG says. The owner's bundle carries no
  `decay` key, so it moves to 30 on update.

## Additions beyond the agreed design

Four rules this spec adds that the owner did not state. Each is the smallest
answer to a gap the agreed design leaves, and each can be vetoed on its own
without touching the rest: the tasks that carry it are named.

- **A1. `updated:` is never moved backwards.** A re-raising source older than
  the loop's current `updated:` does not bump (E21). Without it, a late or
  backfilled window would set `updated:` to an older date and shorten the
  clock, the opposite of what D4 exists for. Carried by tasks 3, 8, 11 and the
  CHANGELOG **Fixed** entry in task 13; a veto drops E21 and those sentences.
- **A2. Rejecting an out-of-scope candidate at the interactive gate.** A snooze
  cannot save one, since the scope rule ignores dates, so a reject needs its
  own meaning. When the owner says they owe it or are waiting on it, the
  procedure adds the owner's entity link to `owner` or to `owed_to` and bumps
  `updated:` to today (the claim, H13, E14). When the owner rejects it but
  neither owes nor is owed it, nothing is written and it is not expired this
  run (E15): the conservative default, never turning a reject into an expiry.
  It is listed again at the next interactive run, and the next unattended run
  expires it; the procedure says so when it happens. Keeping it out of this
  run's `--apply` takes a new `decay-loops.py --except <link>` argument, since
  the re-scan would list it again. Carried by tasks 1, 3, 4.
- **A3. Out-of-scope candidates are listed first.** `find_candidates()` sorts
  them ahead of stale ones, so the dry run and the review batches group the two
  kinds. Only an order; nothing else depends on it. Carried by tasks 1, 3.
- **A4. `owner` and `owed_to` on the open-loop rows of `manifest.jsonl`.** The
  D2 re-mention lookup reads the manifest, whose rows carry `entities` only,
  and the board groups loops by `owner`. An "owed to me" loop with the
  counterpart only in `owner` and the bundle owner only in `owed_to` would be
  invisible to that lookup, so re-mentions would file duplicates and never bump
  or close it. Fact rows gain no key. Carried by tasks 8, 12.

## Behavior

**Ingest, any path** (`ingest`, `ingest-audio`, `catch-up`, `capture`).

- **H1**: a candidate commitment the owner owes is filed as an `open-loop` with
  the owner's entity in `owner` and an observable `**Closure signal:**`.
- **H2**: a candidate where someone else owes the owner a delivery is filed with
  that person in `owner` and the owner's entity in `owed_to`.
- **H3**: a candidate commitment between two other people is filed as a fact,
  its people in `entities`; no loop.
- **H4**: a candidate whose closure cannot be written as something an ingested
  source would show is filed as a fact.
- **H5**: a candidate matching an existing `status: open` loop on the same
  commitment files no new loop; the source acts on the existing one (H6 to H9).
- **H6**: a source showing delivery closes the loop: `status: done`,
  `closed: <source date>`, `closed_by: <this run's source record>`, and a
  `**Resolution:**` paragraph at the end of the body.
- **H7**: a source showing the premise is gone drops it: `status: dropped`, the
  same three fields, a `**Resolution:**` citing the fact that killed it.
- **H8**: a source re-raising the loop without closing it bumps `updated:` to
  the source's own date; `capture` bumps to today.
- **H9**: a source refining the commitment rewrites `**Closure signal:**`,
  appends the previous version under `**Closure signal history:**` with the
  date and the source link, and bumps `updated:`.
- All of H1 to H9 are decided before persist and written at step 7; under
  `--review` they are shown in the batches and written only if approved.

**`decay`, every three days, or interactively.**

- **H10**: the scan lists two kinds of candidate: out of scope (the owner in none
  of `owner`, `owed_to`, `entities`), at any age; and stale (last activity 30
  days back or more, `>=`).
- **H11**: `--apply` expires every candidate; no sweep record is read. Each
  expiry writes `expired:` and a `**Resolution:**` naming which kind it was.
- **H12**: interactively, candidates are shown in batches of 5 to 10, in the
  script's order (out of scope first, A3), with the same options as today. A
  rejected stale candidate is snoozed; a rejected out-of-scope candidate is
  handled by A2.
- **H13**: a claim adds the owner's link to `owner` or `owed_to` and bumps
  `updated:` to today, so the `--apply` re-scan no longer lists it.

**`close-loops`, optional, daily.**

- **H14**: unchanged queue and ranking; its proposal also prints `owed_to`.
- **H15**: the routine writes `done` on delivery, `dropped` when the evidence
  shows the premise is gone, and records `=done`, `=dropped` or `=open` in
  `state/closure-sweep.json`.

| # | WHEN | THEN |
| --- | --- | --- |
| E1 | `elephant.json` has no `owner.slug` (absent, empty, malformed file, no file), or it names no entity file, or no open loop names it | the out-of-scope rule is skipped; one stderr note says so; only stale loops are candidates; exit 0 |
| E2 | a legacy loop has no `owed_to` line | read as an empty list; scope decided on `owner` and `entities`; `validate-okf.py` passes |
| E3 | the owner is only in `entities` | in scope; decays on the 30-day clock |
| E4 | the owner is only in `owed_to` | in scope |
| E5 | an out-of-scope loop was updated yesterday, or cited today in `state/recall.json` | still an out-of-scope candidate, expired on `--apply` |
| E6 | an out-of-scope loop carries no parseable date | still a candidate; its resolution names no age |
| E7 | a loop is both out of scope and stale | expired once, with the out-of-scope resolution |
| E8 | the owner link is quoted, a block sequence, a bare scalar, or a bare slug | matched by slug in every shape |
| E9 | `owner.slug` is given in another case, or as a path | normalized by `slug()` before comparing |
| E10 | `--skip-sweep` is passed | accepted, one stderr deprecation note, behavior identical to without it, exit 0 |
| E11 | `state/closure-sweep.json` is absent, malformed, or records a stale loop as `done` | irrelevant to `decay`: the stale loop expires |
| E12 | the bundle sets `decay.loop_expiry_days: 45` explicitly | 45 is used; the default only applies when the key is absent or invalid |
| E13 | a loop is exactly 30 days silent under the default | a candidate; 29 days is not |
| E14 | an interactive user rejects an out-of-scope candidate and says they owe it | the owner's link is added to `owner`, `updated:` bumped, and `--apply` skips it (A2) |
| E15 | an interactive user rejects an out-of-scope candidate that is neither owed by nor to them | nothing is written and it is not expired this run; the user is told the next unattended run expires it (A2) |
| E16 | an expired loop's commitment is re-mentioned | a new loop is filed; the expired one is untouched (D8) |
| E17 | a candidate matches a `done` or `dropped` loop only | not matched; a new loop if it clears the bar |
| E18 | a candidate matches two open loops | it acts on the one covering the same deliverable; the two are never merged |
| E19 | a sibling task (same project, distinct deliverable) is raised | a separate loop |
| E20 | a source only names the loop's people or project | no bump, no close, no refinement |
| E21 | a re-raising source is older than the loop's current `updated:` | no bump (A1) |
| E22 | a re-raising source carries no date | no bump (except `capture`, whose date is today) |
| E23 | a loop has a `**Closure signal history:**` section after its signal, with or without a blank line between | `close-loops.py` reads only the current criterion; a fact sharing only a history word does not rank |
| E24 | a refined loop later expires or closes | the `**Resolution:**` lands after the history section; `tracking/resolved-loops.md` prints its first sentence as before |
| E25 | `close-loops` meets an out-of-scope loop before `decay` runs | examined like any other; may close it by evidence |
| E26 | the sweep recipe gets `=dropped` | recorded; `=closed` is still refused |
| E27 | an "owed to me" open loop carries `owner: [/entities/person/jane.md]`, `owed_to: [/entities/person/<owner>.md]`, `entities: []` | its `manifest.jsonl` row carries `owner` and `owed_to`, so the D2 lookup finds it; fact rows carry neither key (A4) |
| E28 | `start-day`, `end-day`, `push-start-day` run after a large expiry | nothing in them mentions expiry (D9) |
| E29 | `--review` ingest of a source that closes an open loop | the close is shown in a batch and written only if approved |

## Tasks

Five groups. **File sets are disjoint between groups**, so groups 1 to 4 can
be built concurrently in one working tree; group 5 runs last. Within a group,
tasks run in order. Quoted text is the exact current text to replace; the
replacement text is given in full where the wording matters. Prose follows the
bb doc style: no em dashes in new text.

**Suites cross-read other groups' files**, so disjoint files do not mean
independent suites. `tests/test_close_loops.py`'s `test_procedure_contract`
flattens `plugin/skills/decay/*.md` (group 1) and counts "on or after"; it goes
red as soon as task 3 lands and is expected green only once task 7 lands too.
Task 11's repo-wide check reads files of groups 1, 2 and 5 and is expected
green only at task 13. Each task's verify names the suite that must be green
when its whole group has landed; the whole tree is only asserted green at task
13.

### Group 1: `decay` and the loop template

Files: `plugin/assets/scripts/decay-loops.py`,
`plugin/assets/templates/open-loop.md`, `plugin/skills/decay/SKILL.md`,
`plugin/skills/decay/procedure.md`, `tests/test_decay.py`,
`tests/test_templates.py`.

- [ ] **1. `decay-loops.py`: drop the gate, add the scope rule, default 30**
      → H10, H11, E1 to E13, E15, A2, A3 · dep: none · verify: `tests/test_decay.py`
  - `DEFAULT_EXPIRY_DAYS = 30`.
  - Delete `SWEEP`, `DATE_TAIL`, `load_sweep()`, `examination_date()`,
    `sweep_verdict()`, `gate()`, and in `main()` the `sweep_record` / `sweep`
    / `verdict()` machinery, the "cleared / held back" dry-run notes, the
    `held` list and both held-back summary prints. `find_candidates()` stops
    returning `file_activity`.
  - Add, mirrored from `close-loops.py` (same names, same behavior):
    `unquote()`, `list_field()` (inline list, block sequence, bare scalar),
    `slug()` and `slugs()`. Keep `strip_comment()` byte-compatible:
    `tests/test_frontmatter.py` compares its copies across scripts.
  - Add `owner_slug()`: reads `elephant.json` -> `owner.slug` only, through
    `slug()`; returns None on a missing file, malformed JSON, non-dict
    `owner`, or an empty value. Never raises.
  - Add `in_scope(block, owner)`: True iff `owner` is in
    `slugs(list_field(block, k))` for any `k` in `owner`, `owed_to`,
    `entities`.
  - `find_candidates(expiry_days, owner)` returns each candidate with a
    `kind` of `"out-of-scope"` or `"stale"`. Out-of-scope is tested first,
    ignores every date and the citation, and requires `owner` not None. Then
    the existing stale test, unchanged (`activity is None` still skips a stale
    candidate). Sort: out-of-scope first by path, then stale oldest first.
  - When `owner` is None, print once to stderr:
    `note: elephant.json has no owner.slug, so the out-of-scope rule is skipped this run; only loops stale for {N}+ days are candidates.`
  - Dry run prints `"{link}  (out of scope: the owner is in none of owner, owed_to, entities)"`
    or `"{link}  ({age}d stale)"`, then
    `"\n{n} candidate(s) for decay ({m} out of scope, {k} stale >= {N}d, dry-run, pass --apply to expire)"`.
    Keep the substrings `candidate(s)` and `stale >= {N}d`, which the suites
    read.
  - `--apply` prints `expired: {link}  (out of scope)` or
    `expired: {link}  ({age}d stale)`, then
    `"\n{n} loop(s) expired ({m} out of scope, {k} stale >= {N}d). Run build-index.py next."`
  - `resolution_paragraph()` becomes two shapes, no sweep argument, no em
    dashes, first sentence standing alone:
    - stale: `**Resolution:** Expired on {today} after {age} days of silence: nothing re-raised or cited it after {activity}. Its last activity was {activity}, at or past the {N}-day window `decay.loop_expiry_days` sets in `elephant.json`. Expiry states silence, not a verdict on the commitment: closure by evidence would have been written here by an ingest or by `close-loops` instead.`
    - out of scope: `**Resolution:** Expired on {today} as out of scope: a third-party commitment, with the bundle owner (`/entities/person/{owner}.md`) in none of its owner, owed_to or entities. The loop lane tracks only what the owner owes or is owed; a commitment between other people belongs in the fact lane, where briefing and query still reach it. Expiry here is a scope verdict, not a verdict on the commitment.`
  - Rewrite the `resolution_paragraph()` docstring for the two shapes: keep
    the "first sentence stands alone" and "every claim is window-relative"
    rationale; drop every mention of `catch-up` bumping `updated:`, of
    `--skip-sweep`, of the `examined` / `skipped` arguments and of the sweep's
    `outcome: open`; say the out-of-scope shape names no age because the scope
    test reads no date (E6).
  - `--skip-sweep`: keep the argument, `help="deprecated, no effect: decay no longer reads state/closure-sweep.json"`;
    when passed, print to stderr
    `note: --skip-sweep is deprecated and does nothing: decay no longer reads state/closure-sweep.json.`
  - `--except <link>` (repeatable, bundle-absolute loop path): removes the
    named loops from this run's candidates, in the dry run and on `--apply`,
    and they are counted in neither split. A link matching no candidate is
    ignored with one stderr note. It exists for A2's E15 case: the procedure
    cannot otherwise keep a rejected out-of-scope loop out of `--apply`,
    whose re-scan lists it again because the scope test reads no date.
  - Module docstring: replace the "Re-mention resets the clock elsewhere, in
    exactly one place: `catch-up` step 4 bumps ... (`capture` opens loops and
    never returns to one; it writes no bump.)" sentences with: re-mention
    resets the clock through `updated:`, written by the ingest core (the
    plugin's `skills/ingest/procedure.md`, steps 2 and 4, written at step 7)
    on every ingest path and by the review-gate snooze and claim. Change
    "(default 45;" to "(default 30;". Delete the two paragraphs starting
    "**`--apply` is gated per loop on `state/closure-sweep.json`**" and
    "`--skip-sweep` bypasses that gate entirely"; add one paragraph on the
    out-of-scope rule (what it tests, that it ignores dates, the
    `owner.slug`-missing skip, slug comparison and why) and one line on
    `--skip-sweep` as a deprecated no-op.
- [ ] **2. `templates/open-loop.md`: `owed_to` and the expiry comment**
      → E2 · dep: none · verify: `tests/test_templates.py`
  - Replace `owner: []             # bundle-absolute entity links of who owns it`
    with two lines:
    `owner: []             # bundle-absolute entity links of who owes the delivery`
    `owed_to: []           # who is waiting on it; the bundle owner goes here on an "owed to me" loop`
    (`owed_to` right after `owner`, before `status`). Check that the comment
    contains no ` #` and that `validate-okf.py` still passes the template with
    no warnings.
  - Replace `closed:               # date it was completed/dropped (set by close-loops)`
    with `closed:               # date it was completed/dropped (set by close-loops or an ingest)`.
  - Replace the four comment lines starting
    `# A loop can also end as \`status: expired\`: \`decay\` flips it there when the loop`
    with:
    `# A loop can also end as \`status: expired\`: \`decay\` flips it there when the loop`
    `# has been silent for decay.loop_expiry_days, or at once when the bundle owner is`
    `# in none of owner, owed_to, entities, and inserts its own \`expired: YYYY-MM-DD\``
    `# line right under \`status:\`. Written by the routine only, so this template`
    `# declares no field for it: never set it by hand.`
  - The body is unchanged. Do not put the literal `**Closure signal
    history:**` in the placeholder text: it would sit inside the current
    criterion paragraph.
- [ ] **3. `decay/SKILL.md` and `decay/procedure.md`**
      → H10 to H13, E14, E15, A1 to A3 · dep: 1 · verify: `tests/test_decay.py` (prose checks)
  - `SKILL.md` description (the whole folded `description: >` block) becomes:
    "Automatic expiry of open loops: expire a `status: open` loop into
    `status: expired` once it has gone quiet (no `updated`/`opened`/`created`
    activity, and no citation recorded in `state/recall.json`) for
    elephant.json -> decay.loop_expiry_days days or more (default 30), or at
    once when it names the bundle owner in none of `owner`, `owed_to`,
    `entities`, a third-party commitment outside the lane's scope. Every expiry
    writes a `**Resolution:**` paragraph saying which. Silence alone suffices:
    it does not wait for `close-loops`. Re-mention resets the clock via
    `updated`, written by every ingest path and by this mode's own review-gate
    snooze. A deliberate operation with side effects (edits loop files,
    rebuilds, validates, commits). Invoke only when the user explicitly asks
    (elephant-mem:decay), or unattended with --yes from a schedule."
  - `SKILL.md` body: replace from "Re-mention resets that clock, and it has
    exactly **two** writers." through "Beyond the snooze, this skill only
    reads the signal." with a paragraph saying: the first writer is the ingest
    core (`../ingest/procedure.md`, steps 2 and 4), which `ingest`,
    `ingest-audio`, `catch-up` and `capture` all run, bumping `updated:` to
    the source's own date and never backwards (today for `capture`, whose
    source is the user); the second is this procedure's review-gate snooze,
    keeping the existing explanation of why a rejected candidate is snoozed
    and not skipped; and the scope claim at the same gate (step 2 below). End
    with "Beyond the snooze and the claim, this skill only reads the signal."
  - `procedure.md` intro: "this ONLY expires stale `status: open` loops in"
    becomes "this ONLY expires stale or out-of-scope `status: open` loops in".
  - Step 1: "(default 45; the comparison is `>=`, so a loop exactly that old
    is a candidate — same defensive fallback as `hub_max_facts`)" becomes
    "(default 30; the comparison is `>=`, so a loop exactly that old is a
    candidate, with the same defensive fallback as `hub_max_facts`)". Before
    it, add that the scan also lists, at any age and first, every open loop
    naming the owner (`owner.slug`) in none of `owner`, `owed_to`, `entities`,
    labelled out of scope, and that without `owner.slug` that half is skipped
    with a note. Delete "Each line also says whether `state/closure-sweep.json`
    clears that loop for expiry or holds it back, and the trailing count is
    followed by the split — the dry run is where you see how much of this
    run's lane `close-loops` has actually examined." and replace with one
    sentence: the trailing count splits out of scope from stale.
  - Step 2, interactive: batches of 5 to 10 as today, in the script's order
    (out of scope first), each shown with path, description, `owner` and the
    label. The options stay as today: approve all, approve some, or reject
    some. The existing snooze bullet becomes "Any **rejected stale**
    candidate is *snoozed*" (rest unchanged). Add the bullet: "Any **rejected
    out-of-scope** candidate cannot be snoozed, because the scope rule ignores
    dates. Ask whether the owner owes it or is waiting on it. If so, it is a
    *claim*: add the owner's entity link (`/entities/person/<owner.slug>.md`)
    to `owner` or to `owed_to` accordingly, and bump `updated:` to today. If
    neither, write nothing and leave it out of this run's `--apply`, and tell
    the user that the next unattended run will expire it, since a commitment
    the owner neither owes nor is owed is not a loop."
  - Step 3: "for every remaining candidate the gate below clears, flips" becomes
    "for every remaining candidate, flips"; add that the paragraph names
    which kind of expiry it was, and that every out-of-scope candidate
    rejected without a claim (E15) is passed as `--except <link>`, so this
    `--apply` leaves it open and untouched. Delete the whole "**The gate.**"
    paragraph, the "Losing the record therefore parks decay ..." paragraph
    and "**If everything was held back, nothing was written.** Skip steps 4
    and 5: there is no rebuild to do and nothing to commit." Add one
    sentence: "`--skip-sweep` is accepted and ignored: this script no longer
    reads `state/closure-sweep.json`."
  - Step 5: the log line becomes
    `**Decay**: N loops expired (M out of scope, K >=Xd stale)` and the commit
    message `decay: N loops expired (M out of scope, K >=Xd stale)`; delete
    "held-back candidates excluded".
  - Cadence: "Run every 3 days" stays. Replace the last paragraph, from
    "**Re-mention resets the clock — this is the whole mechanism.**" to the
    end, with the same content in the new shape: the writers of `updated:` are
    the ingest core on every ingest path (a source that speaks to the loop,
    dated by the source, never moved backwards) and this procedure's snooze
    and claim; `decay` only reads it; recall is the other half of the clock;
    and "a loop escapes decay indefinitely by genuine, periodic
    re-affirmation" stays.
- [ ] **4. Tests for group 1** → E1 to E15 · dep: 1, 2, 3 · verify: `tests/test_decay.py` and `tests/test_templates.py` green
  - `tests/test_decay.py`: `new_bundle()` gains `owner_slug=None` (written to
    `elephant.json` alongside `decay` when given; the default stays None so
    every existing check keeps its `owner: []` loops in play as stale ones);
    `write_loop()` gains `owner=()`, `owed_to=None` (None writes no line, the
    legacy shape) and `entities=()`.
  - `test_recall_degraded_shapes`, the no-`recall.py` bundle: the check
    "and the scan says nothing about it" (`result.stderr.strip() == ""`)
    would now fail on E1's owner.slug note. Rewrite it to assert that
    `recall.py` is not mentioned in stderr and that every non-empty stderr
    line starts with `note: elephant.json has no owner.slug`.
  - Drop `--skip-sweep` from every `--apply` call. Delete
    `test_gate_expires_the_examined`, `test_lost_sweep_parks_decay`,
    `test_gate_reads_the_file_dates_not_the_citation`,
    `test_gate_clears_a_same_day_examination`,
    `test_gate_refuses_an_unvalidated_examination` and
    `test_gate_outcome_is_a_whitelist`, and their `main()` registrations.
  - **Keep `write_sweep()`**, with its docstring reworded: it writes the record
    `close-loops` keeps, and decay must ignore it. Remove its calls in
    `test_build_index_excludes_expired_after_apply`,
    `test_expiry_writes_a_resolution` and
    `test_resolution_states_only_what_decay_checked` except where a check below
    uses it on purpose.
  - Rewrite `test_gate_refuses_the_unexamined` as `test_sweep_is_not_read`
    (E11: a stale loop expires with `state/closure-sweep.json` absent,
    malformed (`write_sweep(bundle, {}, raw=...)`), and recording it
    `(date, "done")`; no stderr line mentions `closure-sweep.json`). Rewrite
    `test_skip_sweep_bypasses_the_gate` as `test_skip_sweep_is_a_noop` (E10).
  - `test_expiry_writes_a_resolution`: drop the `"close-loops" in first`
    condition and the "referring to state/closure-sweep.json without a
    leading slash" check. The first-sentence check asserts
    `startswith("**Resolution:**")`, today's date, `"100 days"` and
    `"silence"`; the window check asserts `days_ago(100)` and `"30-day"`; a new
    check asserts `"closure-sweep.json" not in para`.
  - `test_resolution_states_only_what_decay_checked`: run `--apply` without
    `--skip-sweep`, with a `write_sweep()` record of the loop as examined 6 days
    ago kept on purpose. Assert: `days_ago(6)` not in the paragraph,
    `"examination"` and `"closure-sweep.json"` and `"--skip-sweep"` not in it,
    `"reopen"` not in it, the window-relative
    `nothing re-raised or cited it after {days_ago(100)}` still in it, two to
    four sentences with the first standing alone and carrying "100 days".
    Rewrite its docstring and drop the "did not close it" check.
  - `test_custom_threshold`: 35 days is a candidate under the default, 20 is
    not, and a custom 60 excludes 35. `test_expiry_boundary_day`: exactly-30
    is a candidate, 29 is not, "stale >= 30d".
  - New: `test_out_of_scope_expires_at_any_age` (H10, H11, E3, E4, E7: a
    1-day-old third-party loop expires with the out-of-scope resolution;
    owner in `owner`, in `owed_to`, only in `entities` are not candidates;
    stale plus out of scope expires once, out-of-scope resolution);
    `test_out_of_scope_ignores_citation_and_dates` (E5, E6);
    `test_owner_slug_missing_skips_scope_rule` (E1: no file, no `owner`,
    empty slug, malformed JSON; a 1-day third-party loop is not a candidate;
    the stderr note is printed; exit 0); `test_scope_link_shapes` (E8, E9:
    quoted items, block sequence, bare scalar, bare slug, uppercase slug,
    slug given as a path); `test_legacy_loop_without_owed_to` (E2);
    `test_dry_run_labels_and_split` (label per line, out-of-scope lines
    before stale ones, trailing split count, the `--apply` summary);
    `test_except_leaves_a_candidate_open` (E15: `--apply --except <link>`
    leaves that loop `open` and untouched and expires the rest). Register
    each in `main()`.
  - New prose checks in `tests/test_decay.py` over `plugin/skills/decay/*.md`,
    whitespace-normalized: no `closure-sweep.json` except in the
    `--skip-sweep` deprecation sentence, no "held back", no "exactly **two**
    writers", "default 30" present, the claim rule present ("owed_to",
    "claim" and "--except" in `procedure.md`), "never moved backwards" or
    "never backwards" present. Update the module docstring (45-day, the gate
    paragraph).
  - `tests/test_templates.py`: `drive_decay_loops` drops `--skip-sweep` and
    its comment, and "the default expiry is 45 days" becomes 30. New check:
    `open-loop.md` declares `owed_to:` on the line after `owner:`, with an
    empty list value.

### Group 2: `close-loops`

Files: `plugin/assets/scripts/close-loops.py`,
`plugin/skills/close-loops/SKILL.md`, `plugin/skills/close-loops/procedure.md`,
`tests/test_close_loops.py`.

- [ ] **5. `close-loops.py`: print `owed_to`, the history, and no decay coupling**
      → H14, E23, E25 · dep: none · verify: `tests/test_close_loops.py`
  - `read_loops()` adds `"owed_to": slugs(list_field(block, "owed_to"))`
    (so `--json` carries it with no other change). `render_text()` prints
    `entities: … | owner: … | owed_to: …`. `rank_evidence()` and
    `new_material()` are unchanged: `owed_to` joins no signal.
  - No queue change: out-of-scope loops are queued like any other (see
    Decisions).
  - `CLOSURE_SIGNAL`: no regex change. Add to its comment block that a
    `**Closure signal history:**` section after the current signal ends the
    match at the blank line or at its own bolded lead-in, and that history
    entries never repeat the `**Closure signal:**` lead-in, so `search()`
    finds the current one first.
  - Docstrings and comments. Module: replace "That is deliberately the same
    shape as the gate `decay-loops.py --apply` applies before expiring a loop,
    one band earlier: what leaves this queue is exactly what decay is then
    allowed to consider." with a sentence saying settled loops wait for new
    material instead of being re-read. `DATE_TAIL` comment: drop "The twin of
    decay-loops.py's DATE_TAIL, and the two have to agree". `load_sweep()`:
    replace "so this queue knows what to revisit and `decay-loops.py --apply`
    knows what was looked at. Losing it parks decay rather than corrupting it
    — every loop then reads as never examined and returns to band 2, which at
    25 a run takes weeks to work through (E18)." with: it is this queue's own
    control state; losing it returns every loop to band 2, which at 25 a run
    takes weeks to work through, and `decay` does not read it. In its last
    paragraph, "refusing it would park decay over a formatting opinion"
    becomes "refusing it would send the loop back to band 2 over a formatting
    opinion". `examined_on()`: replace the mirror-of-decay and deadlock
    paragraphs with the rule on its own terms (a value has to be a readable,
    non-future date, anchored at the start, or the loop reads as never
    examined and returns to band 2). `build_queue()` comment: "band 2 is
    where the loops decay is waiting on live" becomes "band 2 is the cold end
    of the lane, the loops nothing has re-raised"; keep the measurement.
- [ ] **6. `close-loops` skill: the `dropped` verdict and the decoupling**
      → H15, E24, E26 · dep: 5 · verify: `tests/test_close_loops.py`
  - `SKILL.md` description: "and, where the evidence shows the commitment was
    delivered, writes `status: done`, `closed`, `closed_by` and a
    `**Resolution:**` paragraph saying why." gains "or, where it shows the
    premise is gone, `status: dropped` with the same fields"; "that record is
    what lets `decay` expire anything at all" becomes "that record is this
    routine's own queue control". The intro sentence "and the one closing
    rule that existed (`catch-up` step 4) fires only on the loops a window's
    new items happen to name" becomes "and the flow-side closing rules (the
    ingest core, `../ingest/procedure.md` step 4) fire only on the loops a new
    source happens to speak to". Replace the whole "## Its relation to
    `decay`" section with: the two routines are independent; `decay` expires
    on silence and scope alone and never reads `state/closure-sweep.json`;
    this routine is the optional sweep that ends loops by evidence, done or
    obsolete, before silence does.
  - `procedure.md` intro: replace "and it never writes `dropped`, which stays
    a hand-set state." with "and it writes `dropped` only on evidence that the
    premise is gone (it can also be set by hand)."
  - Preflight: replace "an unexamined loop recorded as examined is the one
    output of this routine `decay` acts on, and it would expire loops on the
    strength of a sweep that never ran." with "an unexamined loop recorded as
    examined leaves the queue as settled, and is not read again until new
    material reaches its entities."
  - Step 2: add a bullet "**Obsolete by evidence is `dropped`.** When the
    evidence shows the commitment no longer makes sense (the counterpart left,
    the project was cancelled, a later decision made it moot), the verdict is
    `dropped`. Silence is not evidence and doubt is not a verdict: those stay
    `open`."
  - Step 3: "only on the loops you are closing" covers both verdicts; the
    frontmatter block shows `status: done` (or `status: dropped`); the
    `**Resolution:**` of a `dropped` loop cites by path the fact that killed
    the premise; `closed_by` is that fact's source, as for `done`. "**Body**,
    one paragraph appended after the `**Closure signal:**` section:" becomes
    "**Body**, one paragraph appended at the end of the body, after the
    `**Closure signal:**` section and any `**Closure signal history:**`
    section:" (E24).
  - Step 4: the opening "This is what `decay` reads to know a loop was looked
    at, so a run that judges and forgets to record has done nothing for the
    lane." becomes "This is what the queue reads to know a loop was looked
    at, so a run that judges and forgets to record sends the same loops back
    next run." "`done` for the ones you closed, `open` for every other one"
    becomes "`done` or `dropped` for the ones you closed, `open` for every
    other one". Step 6 log/commit: `N examined, M closed, D dropped`.
  - The sweep record: "It is control state, not audit: `decay` expires a loop
    only if this file shows it was examined **on or after** its own last
    activity and not closed, so losing it parks expiry rather than corrupting
    it." becomes "It is control state, not audit: it is what lets the queue
    treat a loop as settled, and losing it returns every loop to the second
    band. `decay` does not read it." Recipe: `OUTCOMES = {"done", "dropped",
    "open"}`; prose "be `done` or `open`" becomes "be `done`, `dropped` or
    `open`". Replace "and `decay` would then hold every loop back as never
    examined" with "and the queue would re-read every loop as never
    examined". Replace "This file is the only thing standing between `decay`
    and a lane it may not touch, and a malformed one reads as empty (with one
    warning on stderr) and parks expiry entirely." with "A malformed one reads
    as empty, with one warning on stderr, and sends every loop back to the
    second band."
- [ ] **7. Tests for group 2** → E23, E25, E26 · dep: 5, 6 · verify: `tests/test_close_loops.py` green (needs task 3 landed too)
  - `write_loop()` gains `owed_to=()` and `after=""` (text appended after the
    signal block).
  - New `test_history_is_not_the_criterion` (E23): a loop whose
    `**Closure signal:**` is followed by `**Closure signal history:**`, once
    after a blank line and once on the next line, with distinctive words only
    in the history. Through `--json`: `criterion` equals the current text and
    `criterion_source` is `closure-signal` (`--json` strips `terms`, so terms
    are not read there). Indirectly: a fact that shares only a history word
    with the loop does not rank among its evidence.
  - New `test_owed_to_is_read` (H14): `owed_to` is printed in the text
    proposal and present in `--json`; a legacy loop without the field still
    proposes, with an empty `owed_to`.
  - New `test_out_of_scope_is_queued` (E25): a third-party loop is in the
    queue.
  - `test_sweep_recipe_writes_what_the_script_reads`: `=dropped` is recorded;
    `=closed` still refused. `test_procedure_contract`: "=dropped" present;
    the "on or after" check flattens only the close-loops files (no longer
    `DECAY_SKILL_DIR`, which goes if nothing else uses it), keeps
    `"examined after" not in flat`, and requires at least one "on or after"
    in `procedure.md` (the settled rule); rewrite the comment above it (the
    decay-gate rationale) and its label. New prose checks: no "hand-set", no
    "never writes `dropped`", no "earns `decay`", "dropped" in the step 2
    bullet, and "Closure signal history" in the step 3 body sentence.
  - Labels and comments that still describe the decay gate, printed on every
    run: the module docstring's (h) ("where it would silently park `decay`
    instead"); `test_settled_boundary_is_on_or_after`'s docstring (the
    `tests/test_decay.py` same-day reference, whose check task 4 deletes) and
    its label ("which is the boundary decay's gate ..."); the docstring and
    labels of `test_unreadable_examination_date` that cite `decay-loops.py`'s
    `examination_date()`; the comments at the `tests/test_decay.py [109]`
    reference and the "decay-loops.py anchors the match at position 0"
    paragraph; the band-2 sentence "where the loops `decay` is waiting on
    live"; the comment ending "which is what `decay` then acts on"; the
    `test_sweep_recipe_writes_what_the_script_reads` docstring ("`decay` would
    read an empty record, and expiry would park"); the recipe-test label
    "decay's per-loop gate both compare against" and the comments on "the
    only thing standing between `decay`" and "`decay` then held every loop
    back". Each is restated on the queue's own terms or deleted.

### Group 3: the ingest core and the shared prose

Files: `plugin/skills/ingest/procedure.md`, `plugin/skills/capture/SKILL.md`,
`plugin/skills/catch-up/procedure.md`, `plugin/skills/_shared/core.md`,
`plugin/skills/init/procedure.md`, `plugin/assets/seed/config.md`,
`docs/architecture.md`, `docs/integrations.md`, `docs/configuration.md`,
`tests/test_loop_lifecycle.py` (new).

`ingest-audio` needs no edit: its step 6 already says "run ingest steps 2–8",
which is where the new rules live. `start-day`, `end-day`, `push-start-day`
need none either (D9).

- [ ] **8. `ingest/procedure.md`: the loop bar and the rules on open loops**
      → H1 to H9, E16 to E22, E29, A1, A4 · dep: none · verify: `tests/test_loop_lifecycle.py`
  - Step 2, the route definition: "an `open-loop` (a
    commitment/action-item that will complete)" becomes "an `open-loop` (a
    commitment the owner owes or is owed, which will complete: see **The
    loop bar** below)".
  - In the "Filter on **signal, not relevance.**" paragraph, after "Relevance
    is applied later (at retrieval and at decay), never at capture." add:
    "That holds for facts. A commitment is routed by its relation to the
    owner, by the loop bar below, and one that fails the bar is still kept, as
    a fact."
  - Add under step 2 a block **The loop bar**, the lane decision, written for
    the model: (1) the owner owes it or is owed it, judged here on names (the
    owner by `elephant.json` -> `owner.name` and the source's context), and
    being in the same meeting, channel or thread does not count; a commitment
    between other people is a fact with its people in `entities`; (2) write
    the `**Closure signal:**` as what an ingested source would show on
    delivery, who posts, sends, merges or confirms what, and where; if you can
    only write "it gets done", it is a fact; (3) a commitment that may already
    be an open loop is matched in step 4, once its entities are resolved.
  - Step 3: add one paragraph after the resolution method: a loop candidate
    carries the owner's entity (`/entities/person/<owner.slug>.md`) in `owner`
    ("I owe") or in `owed_to` ("owed to me", the other party in `owner`); if
    resolution leaves it in neither, the candidate is filed as a fact.
  - Step 4: add a block **Open loops** after the fact dedup. The match:
    compare the candidate against `status: open` loops only, the
    `manifest.jsonl` rows with `"type":"open-loop"` whose `entities`, `owner`
    or `owed_to` share a resolved entity with the candidate (open only likely
    matches). A manifest built before this release has no `owner`/`owed_to`
    keys on its rows; the step 3 freshness rule's one `build-index.py` run
    rewrites it. Same deliverable and same parties is the same commitment
    and this source acts on it (below); sibling tasks are separate loops,
    never merged; a `done`, `dropped` or `expired` loop is never matched, so
    the same commitment raised again opens a new loop, which may name its
    predecessor in its details.
  - In the same block, **What a source does to an open loop it speaks to**:
    the bar (delivering, chasing, rescheduling, reporting blocked,
    cancelling; merely naming the same people or project is not speaking to
    it), the source date (its `occurred`; for `capture` the user is the
    source and the date is today), and the four actions, decided here and
    written at step 7:
    - delivery -> `status: done`, `closed: <source date>`,
      `closed_by: <the source record step 1 created>`, a `**Resolution:**`
      appended at the end of the body, after any history section (first
      sentence stands alone, two to four sentences, evidence named by
      bundle-absolute path, in `knowledge_language`, prose never
      frontmatter);
    - premise gone -> `status: dropped`, the same three fields, the
      `**Resolution:**` citing the fact that killed the premise by path; not
      for silence, not for doubt;
    - re-raised without closing -> `updated:` set to the source date only if
      later than its current value (never moved backwards); no date, no bump;
      nothing else changes;
    - refined (deadline moved, scope shrank, deliverable changed) -> rewrite
      the `**Closure signal:**` paragraph, append the replaced version to
      `**Closure signal history:**`, bump `updated:` as above. Nothing else is
      rewritten (`description` included). Never a silent edit.
  - The history format, as a fenced example in that block:

    ```
    **Closure signal:** <the current criterion>

    **Closure signal history:**

    - 2026-09-20, from [/sources/2026-09/2026-09-20-standup.md](/sources/2026-09/2026-09-20-standup.md): was "<the replaced criterion, verbatim>"
    ```

    with three rules: the section always sits directly after the current
    `**Closure signal:**` section; the `**Closure signal:**` lead-in never
    appears anywhere else in the body (`close-loops.py` reads the first one
    it finds); oldest entry first, one line per change.
  - Step 7: "an action item is an `open-loop` (not a fact)" becomes "an action
    item that clears the loop bar (steps 2 and 3) is an `open-loop`; one that
    fails it is a fact". Add: "Every loop write step 4 decided (new loop,
    close, drop, bump, refine) happens here, so `--review` gates them."
    Step 8: "one dated line per created/updated fact (and any flags)" becomes
    "one dated line per created/updated fact and per loop closed, dropped,
    bumped or refined (and any flags)". Step 9: "open-loops opened or
    advanced" becomes "open-loops opened, closed, dropped or refined".
    `--review` variant: the batches also show each loop action (new loop,
    close, drop, bump, refine, or routed to a fact by the bar), persisted at
    step 7 only if approved.
- [ ] **9. `catch-up`, `capture`, `init`: inherit the core**
      → H6 to H9 on those paths · dep: 8 · verify: `tests/test_loop_lifecycle.py`
  - `catch-up/procedure.md` step 3, in "**A candidate spec carries the name
    as written plus its context, never a slug.**": add one sentence: a
    commitment's spec also says, as names with context, who owes it and who
    is waiting on it, so the main agent can apply the loop bar after
    resolution.
  - `catch-up/procedure.md` step 4: replace "**close** open-loops a new source
    shows done (set `status: done`, `closed`, `closed_by`)." with "and apply
    the core's loop rules (`../ingest/procedure.md`: the loop bar in steps 2
    and 3, **Open loops** in step 4, written at step 7): the bar for new
    loops, and close, drop, bump or refine for every open loop a source
    speaks to." Delete the whole paragraph starting "**A source that re-raises
    an open loop without closing it bumps it.**" and ending "loop of an active
    project alive forever." Replace it with: "Those rules live in the core so
    every ingest path applies them the same way; this routine adds nothing to them. When two sources in one window speak
    to the same loop, source precedence (transcripts over Slack) settles only
    wording and detail, as it does for facts; the bump takes the latest of
    their dates, since `updated:` is never moved backwards." (Corrected at
    review: the first wording let precedence pick the bump's date, against A1.)
  - `capture/SKILL.md` step 2: replace "Usually one durable `fact` (a
    decision) — plus an `open-loop` when it implies follow-up." with "Usually
    one durable `fact` (a decision), plus an `open-loop` when it implies
    follow-up the owner owes or is owed: the loop bar of `ingest` steps 2 and
    3 applies." Add a sentence: "When the user says something about an open
    loop (it shipped, it moved, it is off), apply `ingest` step 4's rules on
    open loops: the user is the source, the capture record is `closed_by`, and
    the date is today." Step 4: "any open-loop opened" becomes "any open-loop
    opened, closed, dropped, bumped or refined".
  - `init/procedure.md`: "Optionally one **example open-loop** in
    `tracking/loops/`." becomes "Optionally one **example open-loop** in
    `tracking/loops/`, with the owner's entity in `owner` (a loop naming the
    owner nowhere is expired by `decay` as out of scope)."
- [ ] **10. `core.md` and the docs**
      → D1, D4, D5, D6 in prose · dep: none · verify: `tests/test_loop_lifecycle.py`
  - `core.md`, the owner paragraph: replace "Capture spans everything the
    owner sees; relevance is applied later, at retrieval (see the owner-lens
    note under Retrieval trust) and at decay — never at capture." with
    "Capture spans everything the owner sees and drops nothing for relevance,
    which is applied at retrieval (see the owner-lens note under Retrieval
    trust). The one routing decision the owner frames is the loop lane: a
    commitment is a loop only when the owner owes it or is owed it
    (`../ingest/procedure.md`, the loop bar), and anyone else's commitment is
    kept as a fact."
  - `core.md`, the open-loop paragraph: replace from "`close-loops` reads that
    signal against the evidence and writes `status: done` itself;" through
    "Those are the only writers, and `maintain` never touches a loop." with:
    a loop is the owner's (owed by them in `owner`, or to them in `owed_to`);
    the ingest core (`../ingest/procedure.md` step 4) closes (`done`) or drops
    (`dropped`) a loop a new source shows delivered or obsolete, bumps
    `updated:` when a source re-raises it, and refines its closure signal
    with history; `close-loops`, optional, closes (`done`) or drops (`dropped`) by evidence
    over the backlog, and never bumps or refines a loop it leaves open; `decay` expires a loop silent for `decay.loop_expiry_days`
    (default 30) or naming the owner nowhere; `dropped` can also be set by
    hand; `maintain` never touches a loop; every terminal status is final.
    Keep the rest of the paragraph (the board, manifest, hubs, resolved page
    and its cap).
  - `docs/architecture.md`: replace "`close-loops` reads that signal against
    the evidence and flips the loop to `done`, and `decay` flips one that went
    quiet and survived examination to `expired`. Those two are the writers —
    `maintain` never touches a loop." with the same writer list as `core.md`,
    compact. In "the owner lens", after "**capture keeps everything**, from
    every channel and every team, without judging relevance." add one
    sentence: the owner decides only the lane a commitment takes, a loop when
    the owner owes it or is owed it, a fact otherwise. In the next sentence,
    "and at **decay** (distant, never-referenced facts age out faster)" becomes
    "and, for facts, at **decay** (distant, never-referenced facts age out
    faster)".
  - `docs/integrations.md`: replace "Run `close-loops` daily and unattended"
    with "Optionally, run `close-loops` daily and unattended"; "and closes the
    ones the evidence shows delivered" with "and closes or drops the ones the
    evidence shows delivered or obsolete"; and "Run `decay` every three days,
    after it, so it only ever expires loops `close-loops` has already read."
    with "Run `decay` every three days; it expires on silence and scope alone
    and does not wait for `close-loops`."
  - `docs/configuration.md`: in the Field reference, after **`timezone`**, add
    **`decay`** (optional): `loop_expiry_days` (default 30), the silence
    window; a bundle that sets it keeps its value across updates. In
    **`owner`** add: `decay` expires any open loop naming this slug in none
    of `owner`, `owed_to`, `entities`; without `slug` that rule is skipped.
    In section 3 add a bullet for `state/closure-sweep.json`: written by the
    `close-loops` routine, its queue control only, committed with the run,
    never read by `decay`.
  - `plugin/assets/seed/config.md`: "Action items that complete; tracked on a
    derived board, then archived." becomes "Action items the owner owes or is
    owed, which complete; tracked on a derived board, then archived." and
    "Capture spans everything; relevance is applied at retrieval and decay,
    never at capture." becomes "Capture spans everything and drops nothing for
    relevance, which is applied at retrieval; a commitment is a loop only when
    it is the owner's, a fact otherwise." (New bundles only: `update` never
    re-syncs `config.md`.)
- [ ] **11. `tests/test_loop_lifecycle.py`, a new prose-contract suite**
      → the contract of tasks 8 to 10 · dep: 8, 9, 10 · verify: `python3 tests/test_loop_lifecycle.py` (the repo-wide check only at task 13)
  - Standalone script, stdlib only, `record()` / summary / exit code in the
    shape of `tests/test_backlog.py`. Every text comparison is over
    whitespace-normalized text, since the prose wraps mid-phrase. Its CI line
    is added in task 13.
  - Checks over group 3 files: `ingest/procedure.md` carries the three
    filters ("owed_to", "same meeting", "status: open", "sibling"), the
    lane-confirmation paragraph in step 3, the **Open loops** block in step
    4 (checked by position: after the "4." marker and before "5."), the four
    actions ("status: done", "status: dropped", "source's own date" or
    equivalent, "never moved backwards"), "**Closure signal history:**" and
    the history format block, the step 7 sentence that loop writes happen
    there, and the `--review` batch naming loop actions; `catch-up/procedure.md`
    no longer contains "this rule is its only writer" and points at
    `../ingest/procedure.md`; `capture/SKILL.md` names the user as the source
    and today as the date, and its recap names closed/dropped loops;
    `core.md` and `docs/architecture.md` no longer say "hand-set state",
    "survived examination" or "Those two are the writers";
    `docs/configuration.md` documents `loop_expiry_days` with 30;
    `init/procedure.md` puts the owner's entity in the example loop's `owner`;
    `seed/config.md` says a commitment is a loop only when it is the owner's;
    `docs/integrations.md` marks `close-loops` optional and no longer says
    "after it"; `start-day`, `end-day` and `push-start-day` files contain no
    "expir" (D9, E28).
  - One repo-wide check, meant to pass only once groups 1, 2 and 5 have
    landed: no file under `plugin/`, `docs/`, or `README.md` says "exactly
    **two** writers", "exactly two writers", "`capture` is not a writer",
    "`capture` is not one of them", "never writes `dropped`", "stays a
    hand-set state", "earns `decay`", "once `close-loops` has examined", or
    "Run `decay` every three days, after it". Label it so a failure names the
    file.

### Group 4: `build-index.py` and the manifest

Files: `plugin/assets/scripts/build-index.py`, `tests/test_index.py`.

- [ ] **12. `owner` and `owed_to` on the open-loop manifest rows**
      → E24, E27, A4 · dep: none · verify: `tests/test_index.py`
  - `build-index.py`, section 5 (`manifest.jsonl`): an open-loop row gains
    `"owner": as_list(c["fm"].get("owner"))` and
    `"owed_to": as_list(c["fm"].get("owed_to"))`, placed after `entities`;
    fact rows are unchanged. The module docstring's field list for
    `knowledge/manifest.jsonl` ("path, type, desc, entities, tags, occurred,
    confidence, status") adds "and, on open-loop rows, owner and owed_to".
    The backlinks loop and the board are unchanged.
  - `resolution_sentence()` docstring: "Both writers put the sentence that
    stands alone first (`close-loops` by hand, decay-loops.py's
    resolution_paragraph())" becomes "Every writer puts the sentence that
    stands alone first (the ingest core and `close-loops` by hand,
    decay-loops.py's resolution_paragraph())".
  - `tests/test_index.py`: new check group: an open loop with
    `owner: [/entities/person/jane.md]` and `owed_to: [/entities/person/me.md]`
    has both keys on its manifest row with those values; a legacy loop
    without `owed_to` gets `"owed_to": []`; a fact row carries neither key; a
    refined loop (history section, then a `**Resolution:**`) prints the
    resolution's first sentence on `tracking/resolved-loops.md` (E24).
    `test_resolution_sentence_unit`'s docstring "both appear in every
    resolution the two writers produce" becomes "every writer". Update the
    module docstring's list.

### Group 5: release (last)

Files: `plugin/.claude-plugin/plugin.json`, `CHANGELOG.md`, `README.md`,
`.github/workflows/ci.yml`.

- [ ] **13. Release plumbing** → all · dep: 1 to 12 · verify: every suite green
  - `plugin.json`: `0.1.0-beta.16` -> `1.0.0-rc.1`. The wiki is not bumped.
  - `.github/workflows/ci.yml`: add `- run: python tests/test_loop_lifecycle.py`
    after the `test_close_loops.py` line (no glob picks it up).
  - `README.md`: the `elephant--mem` badge to `v1.0.0--rc.1`. "**open
    loops** — commitments and action items that eventually close." becomes
    "**open loops**: commitments the owner owes or is owed, which eventually
    close." Mode rows: `close-loops` becomes "optional daily sweep: close or
    drop open loops the evidence shows delivered or obsolete"; `decay` becomes
    "expire open loops silent for 30 days, and loops that are not the
    owner's".
  - `CHANGELOG.md`: a `## [1.0.0-rc.1] - <tag date>` section above
    beta.16, house style. A lead paragraph with the measurements (2317 loops,
    987 open; 60% not the owner's, 740 of the open ones; about 1 duplicate
    pair against 263 sibling pairs; `close-loops` closing 0, 0, 1 of 25 and
    197 of 202 candidates held back; the 66/86/86/93% closure curve and why
    30; 109 of the 247 in-scope open loops silent 30 days on their file
    dates, 73 of them protected by a recent citation; the first-run forecast
    of about 776 expiries, 740 out of scope and 36 stale, leaving about 211
    open). Then prose entries: **Added** (`owed_to`; the out-of-scope rule;
    closure signal history; `dropped` by evidence from `close-loops` and the
    ingest core; the loop bar; `decay-loops.py --except`; `owner` and
    `owed_to` on open-loop manifest rows); **Changed** (default 30; `decay`
    no longer gated on `state/closure-sweep.json`; `--skip-sweep` a
    deprecated no-op and why it was kept; the clock resets on every ingest
    path; `close-loops` optional); **Fixed** (a loop re-raised through
    `ingest`, `ingest-audio` or `capture` aged as if silent, because only
    `catch-up` bumped `updated:`; a bump could move `updated:` backwards on a
    late source, A1). State that a bundle with an explicit
    `decay.loop_expiry_days` keeps its value and needs a manual edit to move
    to 30, and that the first run expires most of the lane: an interactive
    `elephant-mem:decay` before the schedule's next run is the way to claim
    loops, knowing it reviews the whole candidate list in batches. Suite
    counts from the final run, per the house style.
  - Run `for t in tests/*.py; do python3 "$t" || echo "FAIL $t"; done`: zero
    failures, including task 11's repo-wide check.

## Found while mapping (out of scope, flagged)

- **`validate-okf.py` enforces neither rule 3 (bundle-absolute links
  resolve) nor rule 4 (no wikilinks).** Both loops were removed in `46cb76b`
  (2026-07-29, "fail on unsafe frontmatter scalars") and never restored; the
  docstring still lists them and `ABS_LINK` / `WIKILINK` are defined and
  unused. And even the old rule 3 read only markdown body links, never a
  frontmatter value like `closed_by`. So `close-loops/procedure.md`'s
  "`closed_by` **must resolve on disk** — `validate-okf.py`'s third check
  fails the run otherwise" is false, and `test_close_loops.py` pins that
  sentence. Worth its own fix; this spec neither relies on the check nor
  changes it.
- `.bb/loop-decay/spec.md` is still `status: in-progress`, with decisions this
  spec reverses. Closing or annotating it is a separate edit.

## Out of scope

- A due-date field (D7).
- The entity trigger: cascading `dropped` when a person leaves.
- Merging existing duplicate or sibling loops.
- Reopening any terminal loop, including a hand-edit path for it.
- A "waiting on" block in `start-day` / `end-day` / `push-start-day`, or a
  `waiting on` section on `tracking/open-loops.md`. An "owed to me" loop
  reaches the owner on the board, under the counterpart's `owner` section,
  and on the counterpart's entity hub.
- `owed_to` in the entity hub backlinks, in `briefing.py --entity`, and in
  `close-loops.py`'s ranking and new-material signal. Each is a reader the
  agreed design did not ask for; a later change can add them.
- Rewriting a loop's `description` when it is refined (D3 makes only the
  closure signal mutable).
- `validate-okf.py` checks on frontmatter link lists, `owed_to` included.
- Any change under `elephant-wiki/`.

## Open

Nothing blocks the build. A1 to A4 stand unless the owner vetoes one; each
names the tasks that carry it.
