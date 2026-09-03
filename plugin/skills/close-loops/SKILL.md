---
name: close-loops
disable-model-invocation: true
description: >
  Closes open loops by evidence: each run examines a bounded, ranked slice of
  `knowledge/tracking/loops/` and, where the evidence shows the commitment was
  delivered, writes `status: done`, `closed`, `closed_by` and a
  `**Resolution:**` paragraph saying why. Every loop it looks at is recorded in
  `state/closure-sweep.json`, closed or not — that record is what lets `decay`
  expire anything at all. A deliberate operation with side effects (edits loop
  files, rebuilds, validates, commits). Invoke only when the user explicitly
  asks (elephant-mem:close-loops), or unattended from a daily schedule.
---

# elephant-mem:close-loops

The open-loop lane is close to write-only without this routine: the criterion
for closing a loop is written on the loop file itself, in a
`**Closure signal:**` section that nothing used to read, and the one closing
rule that existed (`catch-up` step 4) fires only on the loops a window's new
items happen to name. Measured on the owner's bundle: 2036 loop files, 1794 of
them `open`, a 12% closure rate. This is the routine that sweeps the backlog
instead of waiting for a coincidence.

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

The two routines are **never coordinated**, and that is the design. `decay`
expires a loop only if `state/closure-sweep.json` shows it was examined **on or
after** its own last activity and not closed — so this routine is what earns `decay`
the right to act, and `decay` reads the record as it stands on its own three-day
clock. A loop examined yesterday is as examined as one examined an hour ago;
there is no race to lose here, only a record to keep.

## Scheduling

Daily, unattended, same mechanism as `catch-up` and `decay` — see
`procedure.md`'s Cadence section. No review gate at any cadence: unlike
`decay`, this routine has none to skip, because every decision it makes is
already written in prose inside the file it changed.
