---
name: maintain
disable-model-invocation: true
description: >
  Safety-net maintenance of elephant-mem — resolve conflicts, consolidate,
  decay, promote, drift-check snapshots, reconcile the review queue. A
  deliberate operation with side effects (edits facts, rebuilds, commits).
  Invoke only when the user explicitly asks (elephant-mem:maintain).
---

# elephant-mem:maintain

Safety net for autonomous ingestion.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`). It touches entities — also load
`../_shared/entity-resolution.md`.

The full procedure is in [`procedure.md`](procedure.md) — open it and follow it.
