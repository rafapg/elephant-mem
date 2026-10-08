---
name: close-loops
description: >
  Closes open loops by evidence: each run examines a bounded, ranked slice of
  `knowledge/tracking/loops/` and marks a loop `done` when the evidence shows
  it was delivered, or `dropped` when its premise is gone, with a
  `**Resolution:**` saying why. Side effects: edits loop files, rebuilds,
  validates, commits. Use ONLY when the prompt names it
  (/elephant-mem:close-loops), typed by the user or carried by a daily
  scheduled task. Never on a guess: "what's still open", "is X done" or "my
  pending items" are read questions for query or start-day, not this sweep.
---

# elephant-mem:close-loops

The open-loop lane is close to write-only without this routine: the criterion
for closing a loop is written on the loop file itself, in a
`**Closure signal:**` section that nothing used to read, and the flow-side
closing rules (the ingest core, `../ingest/procedure.md` step 4) fire only on
the loops a new source happens to speak to. Measured on the owner's bundle: 2036 loop files,
1794 of them `open`, a 12% closure rate. This is the routine that sweeps the
backlog instead of waiting for a coincidence.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`).

The full procedure is in [`procedure.md`](procedure.md) — open it and follow it.

## What it is, in one paragraph

`scripts/close-loops.py` reads: it picks the loops it is this run's turn to
examine (bounded at `close_loops.max`, default 25) and prints, per loop, its
closure criterion and up to 10 ranked evidence candidates. **The judgment is
yours, not the script's** — "did this get delivered" is not a string match, so
the script never decides and never writes. You read each evidence set as a
whole, write the verdict into the loop file with a paragraph justifying it, and
record every loop you examined. One commit for the run.

## Its relation to `decay`

The two routines are **independent**. `decay` expires a loop on silence and
scope alone, on its own three-day clock, and never reads
`state/closure-sweep.json`. This routine is the optional sweep that ends loops
by evidence, done or obsolete, before silence does.

## Scheduling

Daily, unattended, same mechanism as `catch-up` and `decay` — see
`procedure.md`'s Cadence section. No review gate at any cadence: unlike
`decay`, this routine has none to skip, because every decision it makes is
already written in prose inside the file it changed.
