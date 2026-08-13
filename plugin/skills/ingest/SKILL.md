---
name: ingest
description: >
  File a source (URL / file / pasted text) into elephant-mem as durable facts.
  Use when the user asks for a source to be REMEMBERED — "ingest this", "save
  this to memory", "remember this article / doc / thread". A source merely
  APPEARING in the conversation is not a trigger: never ingest a pasted stack
  trace, log, diff, test output, error message, code, a page fetched while
  working on some other task, or the repository being worked in. If it is
  unclear whether the user wants it retained, offer once and wait — never
  ingest on a guess. Writes and commits, so it confirms scope first unless
  invoked by name. --review adds a per-candidate approval gate.
---

# elephant-mem:ingest

Ingest an external source into the elephant-mem knowledge bundle.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`). It touches entities — also load
`../_shared/entity-resolution.md`.

The full procedure is in [`procedure.md`](procedure.md) — open it and follow it.
**Start at step 0** — the scope confirmation — whenever you reached for this
skill yourself rather than being invoked by name.
