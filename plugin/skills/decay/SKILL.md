---
name: decay
disable-model-invocation: true
description: >
  Automatic decay of stale open loops: expire a `status: open` loop into
  `status: expired` once it has gone quiet (no `updated`/`opened`/`created`
  activity, and no citation recorded in `state/recall.json`) for
  elephant.json -> decay.loop_expiry_days days or more (default 45), and only
  once `close-loops` has examined it and left it open — every expiry writes a
  `**Resolution:**` paragraph saying so. Re-mention resets the clock via
  `updated`, which has two writers: `catch-up` step 4, and this mode's own
  review-gate snooze. A deliberate operation with side effects (edits loop
  files, rebuilds, validates, commits). Invoke only when the user explicitly asks (elephant-mem:decay),
  or unattended with --yes from a schedule.
---

# elephant-mem:decay

"Loops are noise that, when it keeps recurring, earns the right to stay
alive — otherwise it decays automatically." Re-mention resets that clock, and
it has exactly **two** writers. The first is `catch-up` step 4, which bumps a
loop's `updated:` field to a source's date when that source re-raises the loop
without closing it. The second is **this procedure's own review-gate snooze**
(`procedure.md` step 2): a candidate the human rejects at the gate is snoozed,
not skipped — its `updated:` is bumped to today, because a human saying "this
one is still alive" is a re-affirmation and earns the same reset a genuine
re-mention would. Skip that write and a loop the human just rejected comes
back as a candidate on the next run, which throws away the verdict the gate
exists to collect. `capture` is not a writer — it opens loops and never
revisits one. Beyond the snooze, this skill only reads the signal.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`).

The full procedure is in [`procedure.md`](procedure.md) — open it and follow it.

## Scheduling

Designed to also run as a scheduled task (e.g. every 3 days), unattended,
same mechanism as `catch-up` — see `procedure.md`'s Cadence section.
