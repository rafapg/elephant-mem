---
name: decay
disable-model-invocation: true
description: >
  Automatic decay of stale open loops: expire a `status: open` loop into
  `status: expired` once it has gone quiet (no `updated`/`opened`/`created`
  activity, and no citation recorded in `state/recall.json`) for longer than
  elephant.json -> decay.loop_expiry_days (default 45 days), and only once
  `close-loops` has examined it and found nothing — every expiry writes a
  `**Resolution:**` paragraph saying so. Re-mention
  already resets the clock via `updated`. A deliberate
  operation with side effects (edits loop files, rebuilds, validates,
  commits). Invoke only when the user explicitly asks (elephant-mem:decay),
  or unattended with --yes from a schedule.
---

# elephant-mem:decay

"Loops are noise that, when it keeps recurring, earns the right to stay
alive — otherwise it decays automatically." Re-mention (a later `catch-up` /
`capture` corroborating the same commitment) already bumps a loop's
`updated:` field, which resets the clock; this skill only reads that signal,
it never writes it.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`).

The full procedure is in [`procedure.md`](procedure.md) — open it and follow it.

## Scheduling

Designed to also run as a scheduled task (e.g. every 3 days), unattended,
same mechanism as `catch-up` — see `procedure.md`'s Cadence section.
