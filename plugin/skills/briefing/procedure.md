# `briefing` — time-first digest

Load `../_shared/core.md` first (always). This file is the `briefing`
procedure. Obey **Retrieval trust** in `../_shared/core.md`. When neither
time nor entity gives a good entry point, use the **whole-field scan** (see
`../_shared/whole-field-scan.md`).

Read-only, **time-first** digest (complements entity-first `query`).

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

**Sharded hubs:** if you open an entity/source hub while drilling into a
result and its auto-facts block ends with `→ N older/superseded facts:
[archive](...)` (build-index.py's hub sharding), follow that link only when
the user's question needs history beyond the window/inline block — not by
default.

**Consumption log.** After the digest is finalized, run from `<bundle>`, with
one `--item` per fact/loop/source file the digest cited and one `--entity` per
entity it was about:

```bash
python3 scripts/recall.py log --mode briefing --item <path>… --entity <slug>…
```

See `../_shared/core.md`'s Consumption log section. The script writes the line,
swallows any failure and always exits 0, so there is nothing to handle and
nothing to say about it in the digest. It is this mode's only write, and it
lands in git-ignored `state/`.
