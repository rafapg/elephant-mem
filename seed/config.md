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
