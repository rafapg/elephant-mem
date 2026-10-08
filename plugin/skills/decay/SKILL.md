---
name: decay
description: >
  Automatic expiry of open loops: a `status: open` loop becomes
  `status: expired` once it has gone quiet (no activity and no recorded
  citation) for decay.loop_expiry_days days (default 30), or at once when it
  names the bundle owner nowhere, a third-party commitment outside the lane.
  Each expiry writes a `**Resolution:**` saying which. Side effects: edits loop
  files, rebuilds, validates, commits. Use ONLY when the prompt names it
  (/elephant-mem:decay), typed by the user or carried by a scheduled task
  (with --yes). Never on a guess: "clean up my loops" or "too many open items"
  is a question to answer, not an expiry to run.
---

# elephant-mem:decay

"Loops are noise that, when it keeps recurring, earns the right to stay
alive — otherwise it decays automatically." Re-mention resets that clock
through `updated:`. The first writer is the ingest core
(`../ingest/procedure.md`, steps 2 and 4), which `ingest`, `ingest-audio`, `catch-up` and `capture` all
run: when a source re-raises an open loop without closing it, the loop's
`updated:` is bumped to the source's own date, and never backwards (today for
`capture`, whose source is the user in the conversation). The second is **this
procedure's own review-gate snooze** (`procedure.md` step 2): a stale candidate
the human rejects at the gate is snoozed, not skipped — its `updated:` is
bumped to today, because a human saying "this one is still alive" is a
re-affirmation and earns the same reset a genuine re-mention would. Skip that
write and a loop the human just rejected comes back as a candidate on the next
run, which throws away the verdict the gate exists to collect. The third is the
scope claim at the same gate: an out-of-scope candidate the owner says they owe
or are waiting on gets the owner's entity link in `owner` or `owed_to`, and its
`updated:` bumped to today. Beyond the snooze and the claim, this skill only
reads the signal.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`).

The full procedure is in [`procedure.md`](procedure.md) — open it and follow it.

## Scheduling

Designed to also run as a scheduled task (e.g. every 3 days), unattended,
same mechanism as `catch-up` — see `procedure.md`'s Cadence section.
