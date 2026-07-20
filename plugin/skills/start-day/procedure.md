# `elephant-mem:start-day` — the procedure

Load `../_shared/core.md` first (always) — the shared contract; it resolves
`<bundle>` and `elephant.json`. Obey **Retrieval trust** in `../_shared/core.md`.

Morning orientation — a 30-second read, not an exhaustive dump.

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

Load fact bodies only for items needing detail. Write nothing (to the
knowledge bundle) in these three blocks.

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
   silently) so the 7-day gate holds. This is the one write this procedure
   makes — write it to `<bundle>/state/last-update-check.json` directly.

Run this after the three orientation blocks above, so a slow or offline check
never delays the orientation itself.

## Final answer

Return only the three-block orientation (agenda / what happened / open loops)
in the bundle's `conversation_language`, plus the update-check nudge line when
it fires. No preamble, no step-by-step narration.
