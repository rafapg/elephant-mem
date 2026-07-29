# elephant-mem — bundle conventions

This is **your private knowledge bundle**. It stores, accesses, correlates, and
expands facts from the methodical ingestion of your sources. Never publish it.

## Conventions

- **Knowledge is written in `knowledge_language`** (see `elephant.json`; default
  English — close to source material, token-efficient).
- **Conversation happens in `conversation_language`** (see `elephant.json`).
- **Storage**: OKF v0.1 bundle under `knowledge/`, git-versioned, plain markdown
  + YAML frontmatter, one atomic fact per file.
- **Default ingestion**: autonomous (persist following the mode's rules). Opt into
  human review per-source with `ingest <source> --review`.
- **Retrieval v0**: index-first + entity hubs + tags + `ripgrep`. No embeddings
  yet — facts are written self-contained so a vector index can be bolted on later
  without a schema change.

## Three lanes

Capture at maximum granularity, route by lifetime (keeps the system scalable):

- **Durable** — `facts/` (`type: fact`). Grows slowly; dedup bounds it. Reached
  via entity backlinks, never a global list.
- **Open loops** — `tracking/loops/` (`type: open-loop`). Action items that
  complete; tracked on a derived board, then archived.
- **Episodic** — `sources/<YYYY-MM>/` + `log.md`. Raw volume; archival; loaded
  only when querying by date.

Retrieval is **entity-centric** (`query`): the entity catalog is the navigation
spine, facts hang off entities. There is no flat global fact index. A second,
**time-first** path (`briefing`) filters by event time / channel / tag for
"what's relevant in the last N days / decided last week" — hence facts carry
`occurred` (event date, ≠ `created`) and sources carry `channel`. Both paths are
frontmatter-only scans; add embeddings only when `facts/` crosses a few thousand
(no schema change).

The bundle belongs to one **owner** (`elephant.json` → `owner`). The owner's
person entity (`entities/person/<owner.slug>.md`) is the frame for retrieval
relevance. Capture spans everything; relevance is applied at retrieval and decay,
never at capture.

## Layout

```
knowledge/                   # OKF v0.1 bundle (the queryable surface)
  facts/<slug>.md            # atomic durable facts (type: fact)
  entities/<kind>/<slug>.md  # hubs: person|org|project|tool|concept|event|place
  entities/index.md          # derived: the entity CATALOG (navigation spine)
  tracking/loops/<slug>.md   # open-loops (type: open-loop)
  tracking/open-loops.md     # derived: board of open loops
  sources/<YYYY-MM>/<date>-<slug>.md  # provenance, one per source, month-partitioned
  index.md                   # derived: thin router (reserved, no frontmatter)
  log.md                     # episodic ledger (reserved, no frontmatter)
elephant.json                # bundle config: owner, languages, timezone, sources
config.md                    # this file
raw/                         # optional unprocessed capture of a source
state/                       # incremental-routine cursors (NOT in the OKF bundle)
templates/                   # fact / entity / source / open-loop skeletons
scripts/                     # validate-okf.py, build-index.py, state.py, briefing.py
```

## Date

Use ISO 8601 (`YYYY-MM-DD`). Stamp `created`/`updated`/`timestamp` on writes,
interpreting the local day in the bundle's configured `timezone`.

## Frontmatter must be YAML-safe

**Always quote free-text scalars** (`description`, `title`) and **escape every
inner `"` as `\"`** — or wrap the value in single quotes instead. Both halves
matter: quoting without escaping just trades one failure for another.

```yaml
description: "Angelo asked for help: the export was failing"
description: "Angelo asked for help in #suporte-produto"
description: "Thayane took the informal role of \"Chief Legal Officer\""
description: 'Thayane took the informal role of "Chief Legal Officer"'
```

Unquoted, three things go wrong — none of which used to announce itself:

| In the value | What YAML does | What you see |
|---|---|---|
| `: ` (colon-space) | raises; the **whole block** is unparsed | entity hub's `## Related facts` regenerates **empty** |
| ` #` (space-hash) | parses, treats the rest as a comment | description silently **truncated** mid-sentence |
| unescaped inner `"` | raises; same as `: ` | backlinks **empty**, but the value *is* quoted |

All three are routine in real prose: a colon before an explanation, a Slack
channel mention, a quoted job title or something someone actually said. Since a
model writes this frontmatter, the invariant is enforced by a check rather than
by convention — `scripts/validate-okf.py` fails on all three and reports the
line; `validate-okf.py --fix` repairs them in place, preserving inner quotes.
Run it after any batch ingestion, and before trusting a regenerated hub.

A `#` with no space before it (`(#9-channel)`, `https://x#frag`) is not a
comment and is safe. Trailing comments on enum/date fields
(`kind: concept  # person | org | ...`) are fine — that is what the templates do.

Install **PyYAML** (`pip install pyyaml`) in the environment that runs the
scripts. Without it they fall back to a lenient hand-rolled parser that cannot
read nested mappings (`relations:`); they now warn instead of degrading quietly.
