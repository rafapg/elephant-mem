---
status: in-progress
created: 2026-09-02
slug: loop-decay
review: resolved
---

# Loop decay: give the lane an exit before tightening the clock

The open-loop lane is close to write-only. Measured on the owner's bundle on
2026-09-03: 2036 loop files, 1794 `open`, 236 `done`, 6 `dropped`, a 12% closure
rate. The one mechanism meant to bound the lane reads a field nothing writes.
The framing, the measurements and the cuts are in
`.bb/loop-decay/discovery.md`; this spec builds what survived it.

Both halves of the fix already exist on disk and neither is read. The criterion
for closing a loop is written on 2025 of those 2036 files, in a
`**Closure signal:**` section no code opens. The record of what the owner
actually uses is `state/consumption-log.jsonl`, which ships with the right
trigger and is written by 2 of the ~14 modes. So this is mostly wiring, one new
routine and one new script.

Success is closure by evidence: the share of loops reaching `status: done` with
a `closed_by` source, per creation cohort. An `--apply` of decay cannot inflate
that number, which is why it is the gate rather than board size. `dropped` stays
a hand-set state this build never writes, so it is not part of the measure.

## What is already there, and what is wrong with it

**`decay-loops.py`** computes `last_activity` as `max(updated, opened, created)`
and expires anything past `decay.loop_expiry_days` (default 45). It never
deletes; it flips `status` and stamps `expired:`. It treats a `None` activity
date as "can't tell, not a candidate", which is the precedent this spec extends.

**The re-mention claim is false.** `decay/procedure.md:71`, `decay/SKILL.md` and
`decay-loops.py`'s own docstring all state that `catch-up`/`capture` bump a
re-mentioned loop's `updated:`. No procedure does. The `bump` rules those two
carry are about a fact's `times_referenced` and `confidence`, or about
`backlog.py`'s `seen` counter; none is about a loop. `updated` differs from
`created` on 180 of the open loops, 10%.

**The closing rule exists; its input does not.** `catch-up/procedure.md:273`
already says to close open-loops a new source shows done, setting `status`,
`closed`, `closed_by`. It fires only on loops the consolidator happens to
recognise while merging the window's new items, it never reads the loop's own
closure criterion, and nothing sweeps the backlog. `maintain/procedure.md`
mentions loops nowhere, though `open-loop.md` annotates `closed:` as "set by
maintain".

**`state/consumption-log.jsonl`** is appended by `query` and `briefing` at the
end of an answer: `facts_cited` holds the bundle-absolute paths the answer
actually cited, loops included. `core.md` declares it best-effort and instructs
the mode to swallow any exception silently. 26 lines over 33 days; 100 loops
ever cited.

## Why a resolved loop stays where it is

A resolved loop already leaves the three surfaces that filter on
`status == "open"`: `manifest.jsonl`, `tracking/open-loops.md` and the router
count. The bundle's manifest carries 6699 rows, 4904 active facts and 1795 open
loops, and zero `done` or `expired` of either kind.

It does not yet leave two others, and task 9 closes both. `briefing.py` scans
the files directly rather than the manifest and applies no status filter to
loops, so a resolved loop whose `opened` date falls in the window is printed
under `## Open loops` with its status in brackets. And on entity hubs an
`expired` loop renders as a current item, for the reason the last decision
below records. What survives beyond that is the file on disk.

Moving or deleting that file is not available. Loop paths are cited 4136 times
from durable, non-regenerated files: 2784 in the bodies of 1069 source files,
745 in 466 facts, 603 in `log.md`, 4 in hand-written parts of entity pages.
`validate-okf.py`'s third check requires every bundle-absolute link to resolve,
and it runs before every routine's commit. So a move costs a rewrite of those
4136 links on first migration and again on every resolution, forever, over text
people wrote. The remaining 9802 references are derived surfaces and repair
themselves on the next rebuild.

So resolution is a state change plus a written justification, and the archive is
a **generated page**: `build-index.py` already opens every loop, and it emits
`tracking/resolved-loops.md`, newest first, one line per resolved loop with its
date, its outcome and the first sentence of its resolution. That is where the
question "what already got settled with this person" is answered.

## The routine that closes loops

A new mode, `elephant-mem:close-loops`, scheduled daily and unattended, in the
same shape as `catch-up` and `decay`: no review gate, permissive permissions,
commits in place, never pushes.

Its queue is bounded rather than exhaustive, and ordered so the loops blocking
decay are reached first. Each run takes, in order: loops examined before whose
entities have gained a fact or a source since that examination; then everything
else, **oldest last activity first**, up to `close_loops_max` (default 25).
Ordering that second band by last activity rather than by last examination puts
the 735 already-stale loops at its front, and gives a never-examined loop a
defined position, which a last-examination date cannot. At 25 per run the stale
backlog is examined in about a month and the whole open lane in about two and a
half. A verdict is never permanent: new material returns a loop to the first
band.

Its bar is the judgment of the evidence set as a whole, not the literal
satisfaction of the closure criterion. That is a deliberate trade: it closes
more loops and reads more like a person would, at the cost of a criterion two
runs could apply differently. The compensation is that every closure writes its
own justification into the loop file, so a wrong `done` is legible where it was
written rather than only in a diff.

**The two routines are never coordinated.** `close-loops` runs daily; `decay`
keeps its own three-day cadence and reads `state/closure-sweep.json` as it
stands, so it always acts on examinations from earlier runs. That is the
intended relation and not a race: the record is durable, and a loop examined
yesterday is as examined as one examined an hour ago.

## Decisions

- **The consumption line is written by `recall.py log`, not typed by the model.**
  Kills the malformed-JSON and missing-field classes and puts the
  swallow-and-continue in one place instead of in every procedure.
- **`core.md`'s Consumption log section stops saying "best-effort telemetry".**
  The write stays non-fatal and never delays an answer, but it becomes part of
  the read contract. A signal with no consumer had no quality pressure.
- **The five adopting modes are the five `core.md` already lists**: `query`,
  `briefing`, `start-day`, `end-day`, and the whole-field scan. `expand` and
  `review` stay out.
- **New script `plugin/assets/scripts/recall.py`**, modeled on `backlog.py`:
  canonical JSON in `state/`, subcommands, `--at <iso>` on every mutation for
  tests, stdlib only, the same plugin-checkout refusal guard every bundle script
  carries. It reaches installed bundles through `update`, which re-syncs
  `scripts/`.
- **`state/recall.json` is disposable.** Derived from a git-ignored log and
  rebuildable only forward. Every consumer behaves correctly when it is absent,
  empty or malformed.
- **Recall enters decay as a fourth activity date** inside `last_activity()`,
  not as a veto pass with its own window. No new config key, and an empty record
  collapses to today's behavior.
- **The pyramid is item-agnostic**: day-by-day for 14 days, week-by-week to 90,
  month-by-month to 365, one aggregate beyond, over whatever paths the log
  carries. Bought for read cost, not disk.
- **`close-loops` is its own skill, daily and unattended**, not a step of
  `catch-up` and not a review-gated mode.
- **Evidence ranking**: facts sharing the loop's non-owner entities first, then
  content-word overlap against the loop's `description` plus its closure signal,
  then recency. Capped at 10 per loop. Ranking on the owner's entity alone is why
  the median candidate count is 684.
- **Resolution is written as prose in the loop file's body**, under a
  `**Resolution:**` heading, by both `close-loops` and `decay`, identically. Not
  a frontmatter field: the justification is a sentence of judgment, and the
  frontmatter breaks on `: ` and truncates silently on ` #`, which the template
  already carries three lines of warning about. The structured parts
  (`closed`, `closed_by`, `expired`) are existing frontmatter fields and stay
  there.
- **One commit per run**, short conventional message with the count. The
  per-loop detail lives in the files, so the commit body carries none.
- **`state/closure-sweep.json` is control state, not audit.** It records which
  loops were examined and when, so decay knows what was looked at and the queue
  knows what to revisit.
- **Losing that record parks decay rather than corrupting it.** Every loop then
  reads as never examined, and at 25 examinations per run the backlog takes
  weeks to earn expiry again. `--skip-sweep` is the deliberate way out, and it
  is the same flag that restores today's behavior.
- **`--apply` gates per loop on that record**: a loop is expirable only if it
  was examined after its own last activity and was not closed. The gate only
  ever meets loops that are already decay candidates, so a loop whose `updated:`
  was just bumped is out of scope for a different reason before the gate is
  consulted.
- **Resolved loops leave the entity pages.** `build-index.py` stops re-filing
  non-`open` loops as history lines on entity hubs;
  `tracking/resolved-loops.md` becomes their one listing. Both surfaces are
  derived, so this is one line to reverse and loses no data.
- **`tracking/resolved-loops.md` caps inline at `resolved_max` (default 200)**
  and overflows into a sibling archive shard, the same mechanism
  `hub_max_facts` already uses, so it cannot become a second 541 KB board.
- **The false re-mention claim is deleted from all three places and made true in
  one.** `catch-up` step 4 gains the bump rule next to the close rule it already
  carries: a source that re-raises an open loop without closing it bumps
  `updated:` to that source's date.
- **`roll` is called by `decay` step 1 and by `catch-up`'s commit step**, so the
  pyramid is fresh where it is read and the raw log does not grow unbounded.
- **`expired` joins `build-index.py`'s hardcoded `loop_status` default, and
  `init` starts copying `vocab.json` into new bundles.** This is not defensive:
  no bundle has ever received that file. `init` copies `scripts/`, `templates/`,
  `config.md`, `README.md` and `cursors.json`; `update` re-syncs `scripts/` and
  `templates/`. So the hardcoded default is what runs in the field, and under it
  `LOOP_HISTORY_STATUS` is `{done, dropped}`, which puts an expired loop in
  neither bucket. It does not vanish, which is the failure that would be
  tolerable: `is_history()` returns false, so the hub renders it as a current
  item and it consumes a slot of `hub_max_facts`. `update` still never re-syncs
  `vocab.json`, since a bundle may have edited its own vocabulary.

## Behavior

**A read.**

- **H1** — A read mode finishes its answer, then calls `recall.py log --mode
  <mode> --item <bundle path>... --entity <slug>...`. One JSON line lands in
  `state/consumption-log.jsonl`. The answer is already decided.

**The daily `close-loops` run.**

- **H2** — It builds its queue: loops examined before whose entities gained a
  fact or a source since that examination, then everything else oldest last
  activity first, up to `close_loops_max`.
- **H3** — `close-loops.py` emits, per queued loop, its closure criterion and up
  to 10 ranked evidence candidates.
- **H4** — The routine judges each evidence set as a whole. On delivery it
  writes `status: done`, `closed`, `closed_by` and a `**Resolution:**`
  paragraph.
- **H5** — Every examined loop gets a dated entry in
  `state/closure-sweep.json`, whether it closed or not.
- **H6** — `build-index.py`, `validate-okf.py`, a `log.md` line, one commit for
  the run.

**The `decay` run, every three days.**

- **H7** — It runs `recall.py roll`, folding the log into `state/recall.json`'s
  buckets, then scans for candidates with the citation date as a fourth
  activity date.
- **H8** — It expires only loops examined after their own last activity and not
  closed, writing `expired`, the date and a `**Resolution:**` paragraph of its
  own.
- **H9** — Either run's rebuild writes `tracking/resolved-loops.md`, newest
  first, with date, outcome and the first sentence of each resolution; resolved
  loops no longer appear on entity pages.

| # | WHEN | THEN |
| --- | --- | --- |
| E1 | `state/` is absent or unwritable | `recall.py log` exits 0 silently; the answer is unaffected |
| E2 | `state/recall.json` is absent | `score` reports no citation; decay behaves as today |
| E3 | `state/recall.json` is malformed | treated as absent, one stderr warning, decay never crashes |
| E4 | `roll` runs twice over the same lines | counts are not double-added |
| E5 | `roll` runs on an empty or absent log | exits 0, writes nothing |
| E6 | a cited path no longer exists on disk | its entry is pruned at the next `roll` |
| E7 | a loop was cited 3 days ago, `updated` is 100 days old | not a decay candidate |
| E8 | a loop has no recall entry at all | candidate iff its file dates are stale, as today |
| E9 | more loops qualify than `close_loops_max` | the excess waits, the second band ordered oldest last activity first |
| E10 | a fact or source touches an examined loop's entities | it returns to the first band |
| E11 | a queued loop has no evidence candidates | examined, recorded, left `open`, no file write |
| E12 | a loop carries no `**Closure signal:**` section | its `description` is the criterion, and the proposal says so |
| E13 | the routine closes a loop | `status: done`, `closed`, a `closed_by` that resolves, and a `**Resolution:**` |
| E14 | the evidence does not show delivery | the loop stays `open`, is recorded as examined, and nothing is queued for a human |
| E15 | `--apply` meets a candidate never examined | refuses that loop, names it, prints the `close-loops` command, exits 0 |
| E16 | `--apply --skip-sweep` | the gate is bypassed; every candidate expires |
| E17 | decay expires a loop | `expired`, the date and a `**Resolution:**` naming the silence, same shape as a closure |
| E18 | `state/closure-sweep.json` is lost | every loop reads as never examined; decay expires nothing until they are, or until `--skip-sweep` |
| E19 | a source re-raises an open loop without closing it | `catch-up` bumps its `updated:` to that source's date |
| E20 | resolved loops exceed `resolved_max` | the overflow moves to the sibling archive shard, newest kept inline |
| E21 | a bundle has no `vocab.json` | `expired` still reads as history: off the hub, onto the resolved page |
| E22 | `recall.py` or `close-loops.py` is run from the plugin checkout | refuses, with the guard 9 of the 11 shipped scripts carry |
| E25 | a resolved loop's `opened` date falls in a briefing window | it is not listed under `## Open loops` |
| E23 | a run's rebuild or validation fails | nothing is committed; the files are already written, so the next run continues |
| E24 | an installed bundle runs `update` | the new scripts arrive via its `scripts/` re-sync; each suite has its own CI step |

## Tasks

- [x] **1. `recall.py` storage and `log`**: script, checkout guard, `log`, `show`, `--at`, and the suite's own `- run:` line in `.github/workflows/ci.yml`, which has no glob
      → E1, E22, E24 · dep: — · verify: `tests/test_recall.py`
- [x] **2. `roll` and `score`**: pyramid buckets, idempotence, pruning, the lookup decay reads
      → E2, E3, E4, E5, E6 · dep: 1 · verify: `tests/test_recall.py`
- [x] **3. Adopt the log across the read modes**: the five modes call `recall.py log`; `core.md`'s section rewritten
      → H1 · dep: 1 · verify: reading
- [x] **4. Wire `roll` into the routines**: `decay` step 1 and `catch-up`'s commit step
      → H7 · dep: 2 · verify: reading
- [x] **5. Recall as a fourth activity date**: `last_activity()` in `decay-loops.py`
      → H7, E2, E7, E8 · dep: 2 · verify: `tests/test_decay.py`
- [x] **6. `close-loops.py`**: the two-band bounded queue and the ranked capped evidence proposal, plus the suite's own `- run:` line in `.github/workflows/ci.yml`
      → H2, H3, E9, E10, E11, E12, E22, E24 · dep: — · verify: `tests/test_close_loops.py`
- [x] **7. The `close-loops` skill**: `SKILL.md` + `procedure.md`, daily unattended, the judgment, the `**Resolution:**` and `closed`/`closed_by` write, the sweep record, one commit
      → H4, H5, H6, E13, E14, E23 · dep: 6 · verify: `tests/test_close_loops.py`
- [x] **8. Decay's half**: `**Resolution:**` on expiry, the per-loop gate, `--skip-sweep`
      → H8, E15, E16, E17, E18 · dep: 5, 7 · verify: `tests/test_decay.py`
- [x] **9. The resolved surface**: `tracking/resolved-loops.md` with its cap and overflow shard; the new filename added to the derived-name set each of the four scripts keeps its own copy of (`build-index.py`, `validate-okf.py`, `briefing.py`, `rename-entity.py`); a status filter on `briefing.py`'s loop list; resolved loops dropped from entity pages; `expired` in the hardcoded status default and `vocab.json` copied by `init`
      → H9, E20, E21, E25 · dep: — · verify: `tests/test_index.py`
- [ ] **10. Correct the false claims about loops**: delete the re-mention claim from three places and add the real bump rule to `catch-up` step 4; correct `decay/procedure.md:45-47`, which says the rebuild re-files expired loops into entity history and today does not
      → E19, E21 · dep: — · verify: reading
- [ ] **11. Release plumbing**: the bundle-scripts line in `docs/architecture.md`, CHANGELOG, `plugin.json` bump, README badge, and `close-loops` in the README's explicit-modes table alongside `decay`, which that table omits today. Each new suite registered its own CI step in the task that created it
      → E24 · dep: 1-10 · verify: every suite green

## Out of scope

- Fact decay as a state change. Cut upstream; surface decay for facts already
  ships through `build-index.py`'s archive shards.
- A new frontmatter field on the loop template. Every bundle on disk would carry
  loops without it and only its owner could fix that.
- Backfilling a recall signal over the existing loops.
- A one-time clock reset over the 735 stale loops.
- Moving or deleting resolved loop files, and any rewrite of the 4136 durable
  links that point at them.
- Writing `status: dropped`. It stays a hand-set state.
- A decay exemption for `origin: pr` loops: no loop carries `origin` at all.
- Consolidating the pyramid inside `build-index.py`.
- Routing undecided loops to `state/needs-review.md`. The routine re-examines
  them when new material arrives instead.
- Shrinking `tracking/open-loops.md`, currently 541 KB. It shrinks as a
  consequence of closure, not as a target here.
- _revisit_: fact ranking off the pyramid. `times_referenced` is 0 on 89.5% of
  facts because every writer of it is an ingest-side dedup rule; it counts
  re-capture, not usefulness. The pyramid is item-agnostic so this is a consumer
  rather than a rewrite.
- _revisit_: the template drift found while measuring, loops carrying
  `relations` or `confidence` and facts missing `description`.

## Open

Nothing.
