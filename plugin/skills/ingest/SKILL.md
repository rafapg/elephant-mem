---
name: ingest
disable-model-invocation: true
description: >
  Ingest a source (URL / file / pasted text) into elephant-mem — extract
  atomic facts, resolve entities, dedup, and persist. A deliberate operation
  with large side effects (writes facts, rebuilds the index, commits). Invoke
  only when the user explicitly asks (elephant-mem:ingest). --review adds an
  approval gate.
---

# elephant-mem:ingest

Ingest an external source into the elephant-mem knowledge bundle.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`). It touches entities — also load
`../_shared/entity-resolution.md`.

The full procedure is in [`procedure.md`](procedure.md) — open it and follow it.
