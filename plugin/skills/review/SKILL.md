---
name: review
disable-model-invocation: true
description: >
  Clear the elephant-mem needs-review queue — an explicit, deliberate
  maintenance operation with side effects (edits fact/loop files and the
  queue). Invoke only when the user explicitly asks (elephant-mem:review).
---

# elephant-mem:review

Clear the `state/needs-review.md` queue.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`). It touches entities — also load
`../_shared/entity-resolution.md`.

## Procedure

Clear the `state/needs-review.md` queue. Read it, load each referenced
fact/loop, and present them **in batches of 5–10** in the bundle's
`conversation_language` (the item, why it was flagged, the open question). For
each, the user confirms (raise confidence, drop the tag), corrects (fix
entity/name — use `rename-entity.py` for entity slugs), or drops it.

**Alias by default on identity items.** Whenever an item resolves *who a
person is* (a nickname or auto-transcript mangling → a real entity), recording
the resolved-from token as an `alias` on that entity is the **default step,
not optional** — it's what makes future ingests self-correct (see
`entity-resolution.md`). `rename-entity.py --alias` does this on a
merge/rename; for a plain confirm where the entity is already correct, add the
alias to its frontmatter directly. The **only** exception is a token that
collides with another entity's title/alias (a genuinely ambiguous share, e.g.
a common first name): do NOT silently alias it to one side or silently drop
it — surface the collision and the tradeoff to the user and let them decide.

Apply, remove cleared lines from the queue, then rebuild + validate + commit.
Read-light otherwise; no churn on untouched items.
