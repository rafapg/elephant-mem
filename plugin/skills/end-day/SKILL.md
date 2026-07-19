---
name: end-day
description: >
  Evening wrap from elephant-mem (read-only + optional capture). Use when the
  user ends their day / wants an end-of-day review: what happened today,
  what's left pending, and a prompt to capture anything worth remembering.
  Answers in the bundle's conversation_language.
---

# elephant-mem:end-day

Evening wrap — what happened / what's pending, with an optional capture
prompt.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`). Obey **Retrieval trust** in
`../_shared/core.md`.

## Procedure

Read-only synthesis + an optional capture prompt, in the bundle's
`conversation_language`:

1. **What happened today.** `scripts/briefing.py --days 1`; surface decisions
   made and open-loops opened/closed today, grouped by channel.
2. **What's left pending.** The owner's (`elephant.json` → `owner.slug`)
   `open` loops touched or opened today, plus any still-open commitment with
   an imminent closure signal.
3. **Wrap-up.** Ask whether there's anything from the day worth capturing that
   automated ingestion wouldn't have caught (a decision made in a dev session,
   a verbal commitment) → route to `capture`. This is the only place the mode
   may write, and only on the user's say-so.
