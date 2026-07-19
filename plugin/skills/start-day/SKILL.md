---
name: start-day
description: >
  Morning orientation from elephant-mem (read-only). Use when the user starts
  their day / asks "what's on today" / wants a morning briefing: today's
  agenda + overnight digest of decisions and new facts + their open loops.
  Answers in the bundle's conversation_language.
---

# elephant-mem:start-day

Morning orientation — a 30-second read, not an exhaustive dump.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`). Obey **Retrieval trust** in
`../_shared/core.md`.

## Procedure

Read-only synthesis in the bundle's `conversation_language` — a 30-second
morning read, not an exhaustive dump. Three blocks:

1. **Today's agenda** (prospective, live). If a Calendar connector is
   available, list today's events → meetings with times. If it isn't
   connected, say so and skip this block — **never fail the whole mode for a
   missing connector** (Calendar is optional here; see core.md's degradation
   rules).
2. **What's relevant / what happened** (retrospective, bundle). Run
   `scripts/briefing.py --since <last-working-day> --entity <owner.slug>`
   (the owner's slug from `elephant.json`, plus their team/projects); surface
   **decisions** and new facts since the user last looked, grouped by
   channel. This is the overnight digest served from already-ingested facts
   (`catch-up` keeps it fresh, where configured) — no live connector needed
   for this block.
3. **What I need to do** (loops). From `tracking/open-loops.md`, list the
   owner's `open` loops, oldest-opened first; flag any with a near closure
   signal.

Load fact bodies only for items needing detail. Write nothing.

## Update check

At most once per week, nudge the user if a newer plugin release exists —
never auto-update. Follow `../_shared/core.md`'s **Update check** convention:

1. Read `<bundle>/state/last-update-check.json`; skip if it was checked less
   than 7 days ago.
2. Fetch
   `https://raw.githubusercontent.com/rafapg/elephant-mem/main/plugin/.claude-plugin/plugin.json`
   and compare its `version` to the installed plugin's.
3. If the remote is newer, show `claude plugin update elephant-mem@elephant-mem`
   once — do not auto-update.
4. Always stamp `last_checked` (even on fetch failure — offline just skips
   silently) so the 7-day gate holds.

Run this after the three orientation blocks above, so a slow or offline check
never delays the orientation itself.
