---
name: briefing
description: >
  Time-first digest from elephant-mem (read-only). Use when the user asks
  "what's relevant that I might be missing?" over a time window — e.g.
  "everything in Slack the last 2 days", "what was decided in the team's
  meetings last week". Complements entity-first query. Answers in the bundle's
  conversation_language.
---

# elephant-mem:briefing

Read-only, **time-first** digest (complements entity-first `query`).

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`). Obey **Retrieval trust** in
`../_shared/core.md`. When neither time nor entity gives a good entry point,
use the **whole-field scan** (see `../_shared/whole-field-scan.md`).

## Procedure

Answers "what's relevant that I might be missing?" — e.g. "everything in Slack
the last 2 days", "what was decided in the team's meetings last week". Run
`scripts/briefing.py` from `<bundle>` with the right filters, then synthesize
in the bundle's `conversation_language`:

- window: `--days N` or `--since/--until` (filters `occurred`, the event
  date);
- `--channel slack|meeting|…`, `--tag decision`, `--entity <slug>`,
  `--kind fact|open-loop`.
- "relevant to me" ≈ `--entity <owner.slug>` (the owner's slug from
  `elephant.json`) plus the owner's projects/team, and decisions/open-loops in
  their channels — tune per request.

Group the result by channel or chronologically; surface **decisions** and
**open-loops opened/closed** in the window prominently. The digest is a
frontmatter-only scan (no bodies, no embeddings), so it stays cheap at scale.
Then load bodies only for the few items the user drills into. If a filter
returns suspiciously little (e.g. one `decision` when a meeting clearly had
more), say so — it usually means inconsistent tagging upstream, a `maintain`
fix.
