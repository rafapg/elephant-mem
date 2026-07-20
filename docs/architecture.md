# Architecture

This document explains how elephant-mem stores and retrieves knowledge, and the
reasoning behind each choice — enough to decide whether to trust it with your
memory. The short version: knowledge is **plain markdown + git**, organized as an
**OKF v0.1 bundle**, with entities as the navigation spine and a set of scripts
that keep derived surfaces and invariants honest.

## The OKF bundle

Everything lives in one self-contained, git-versioned directory — the **bundle**.
It is created and registered by `elephant-mem:init` outside this repo, on your own
machine, and never travels except by you moving the folder.

```
<bundle>/
  knowledge/                          # the OKF v0.1 bundle — the queryable surface
    facts/<slug>.md                   # atomic durable facts (type: fact)
    entities/<kind>/<slug>.md         # hubs: person | org | project | tool | concept | event | place
    entities/index.md                 # derived: the entity CATALOG (navigation spine)
    tracking/loops/<slug>.md          # open loops (type: open-loop)
    tracking/open-loops.md            # derived: board of active open loops
    sources/<YYYY-MM>/<date>-<slug>.md # provenance, one per source, month-partitioned
    index.md                          # derived: thin router (reserved, no frontmatter)
    log.md                            # episodic ledger (reserved, no frontmatter)
  elephant.json                       # bundle config: owner, languages, timezone, sources
  config.md                           # bundle conventions (human + agent readable)
  raw/                                # optional unprocessed capture of a source
  state/                              # incremental-routine cursors (NOT part of the OKF bundle)
  templates/                          # fact / entity / source / open-loop skeletons
  scripts/                            # build-index, validate-okf, state, briefing, ...
```

Two properties fall out of this: you can `cat` any fact and read it, and you can
`git log` any file to see how a belief evolved.

## The three lanes

Capture happens at **maximum granularity**, but every captured item is routed to
one of three lanes by its **lifetime**. This is the single decision that keeps the
system scalable when you ingest many times a day.

| Lane | Type / location | Lifetime | Reached via |
|---|---|---|---|
| **Durable** | `type: fact` in `facts/` | grows slowly (dedup bounds it) | entity backlinks |
| **Open loop** | `type: open-loop` in `tracking/loops/` | bounded — closes and archives | the open-loops board |
| **Episodic** | `type: source` in `sources/<YYYY-MM>/` + `log.md` | linear with volume; archival | only by date |

Why three lanes instead of one big pile:

- **Input volume ≠ fact count.** The same fact re-observed across dozens of
  messages and transcripts should be *deduped*, not re-filed. The raw volume lands
  in the **episodic** lane, which is never loaded to answer a question — it exists
  for provenance and audit.
- **A durable fact and a commitment are different things.** A fact ("the billing
  service runs on Acme Cloud") stays true; a commitment ("Jane will draft the
  migration plan") *completes*. Open loops carry a `status` (`open | done |
  dropped`) and a **closure signal**; when a later source shows the work was done,
  `maintain` flips it to `done`. The lane is what lets you answer "what got done
  vs. what's still hanging".

### event time vs. record time

Every fact carries two dates: **`occurred`** — when the event in the world
happened — and **`created`** — when the fact file was written. They are usually
different (you ingest Monday's meeting on Tuesday). Sources carry a `channel`.
This is what makes the time-first `briefing` mode possible: "what was decided last
week" filters on `occurred`, not on when you happened to record it.

## Entity-centric retrieval

There is **no flat global list of facts**. Retrieval is entity-centric:

- **Entities are the navigation spine.** People, orgs, projects, tools, and
  concepts each get a hub file under `entities/<kind>/`. `entities/index.md` is the
  catalog.
- **Facts hang off entities via backlinks.** A fact links to the entities it
  mentions with bundle-absolute markdown links (`/entities/person/jane-doe.md`).
  `build-index.py` walks those links and writes a backlinks block onto each entity
  hub, so an entity page *is* the live aggregation of everything known about it.
- **`query` walks the entity, not a search index.** Ask "what do we know about the
  billing rewrite" and it resolves the entity, reads its backlinks, and answers
  with provenance — every claim cites the fact file and the source it came from.

### the owner lens

The bundle belongs to one **owner** (`elephant.json` → `owner`). "Relevant to me"
in the read modes (`query`, `briefing`, `start-day`, `end-day`) is the owner's
entity plus their projects and team — expressed as `--entity <owner.slug>`.

This is deliberate: **capture keeps everything**, from every channel and every
team, without judging relevance. Relevance is applied only at **retrieval** (the
owner lens) and at **decay** (distant, never-referenced facts age out faster).
Filtering at capture time would silently throw away the fact you need six months
later; filtering at retrieval time keeps it available but out of your face.

## Source precedence and fact merging

When the same fact shows up from two places, elephant-mem **merges** rather than
duplicates:

- A re-observed fact bumps `times_referenced`, appends the new source to its
  provenance, and can raise `confidence` (corroboration) — it does not create a
  second file.
- **Transcripts outrank chat.** Meeting transcripts are primary; Slack and other
  chat sources are secondary. When they conflict, the higher-precedence source
  wins and the disagreement is recorded, not lost.

### retrieval trust

Provenance carries **trust**, not just origin. Every read mode weights facts by
`confidence` (`high > medium > low`) and `status`:

- `low` / `needs-review` facts are never stated as settled — they're flagged and
  grouped separately in digests.
- `deprecated` / `superseded` facts aren't presented as current truth, but they're
  not dropped silently either: if relevant, the answer footnotes that a prior
  belief changed and points to the current fact.

## Aggregator facts (the rollup rule)

Occasionally you want one fact that *summarizes* many — an ownership map, a "state
of project X". The rule:

> **If a query or backlink can regenerate it, don't hand-write it. If it encodes
> editorial judgment a query can't derive, hand-write it and tag it `snapshot`.**

Entity backlinks are already a live aggregation, so a "what concerns this entity"
rollup is redundant — read the hub. But "who owns which initiative" is an
editorial call, not a derivable join, so it earns a hand-written `snapshot` fact.
A snapshot is a point-in-time editorial rollup: it *will* go stale as finer facts
supersede parts of it, and that's expected — the atomic facts remain the source of
truth, and `maintain` drift-checks the snapshot rather than decaying it.

## Derived files are never hand-edited

Some files are **generated**, never authored by hand:

- `index.md` (the router)
- `entities/index.md` (the catalog)
- `tracking/open-loops.md` (the board)
- the backlinks blocks on entity and source files

`build-index.py` regenerates all of them from the atomic facts and their links.
Editing a derived file by hand is pointless — the next build overwrites it. Add a
fact, add a link, rebuild.

## Validation invariants

`validate-okf.py` enforces the invariants that keep the bundle consistent, and
must exit 0 before any commit:

- Every non-reserved `.md` file has frontmatter with a non-empty `type`.
- Reserved files (`index.md`, `log.md`, `open-loops.md`) have **no** frontmatter.
- Links are **bundle-absolute markdown** (`/entities/...`) — **no `[[wikilinks]]`**
  — and resolve to real files.
- Episodic files are month-partitioned under `sources/<YYYY-MM>/`.
- One self-contained claim per fact file.

The workflow after any write batch is fixed: run `build-index.py`, then
`validate-okf.py`, both must pass, then commit.

## The scripts

| script | what it does |
|---|---|
| `build-index.py` | regenerate the index, entity catalog, open-loops board, and all backlink blocks |
| `validate-okf.py` | enforce the OKF + elephant-mem invariants (run before every commit) |
| `rename-entity.py` | fix a mangled entity name — moves the file, rewrites links, keeps the old spelling as an alias |
| `briefing.py` | time-first digest (`--days` / `--since` / `--until` / `--channel` / `--tag` / `--entity` / `--kind`) |
| `state.py` | catch-up cursor bookkeeping (advance live/backfill, mark seen ids, render watermarks) |
| `snapshot-drift.py` | flag `snapshot` rollups whose underlying facts became newer than the snapshot's last-tended date |
| `ingest-audio.py` | pull a transferred voice recording and transcribe it locally (WhisperX, diarized) for `ingest-audio` |

## Why git

- **Versioning + audit trail.** Every change to a belief is a commit. You can see
  when a fact appeared, when it was corrected, and what superseded it.
- **Local commits, never push.** The bundle holds private data; it stays on the
  machine. Nothing in elephant-mem pushes to a remote.
- **Portability.** The bundle is a directory. Move it, back it up, or re-register
  the pointer on another machine — no export step.

## Why no database / embeddings (yet)

elephant-mem stores facts as flat markdown and retrieves with an index + entity
hubs + `ripgrep`. That's a deliberate v0 choice:

- **Grep-ability** — you can find anything with standard tools, no query language.
- **Portability** — no schema to migrate, no server to run.
- **Transparency** — you can read exactly what the system believes and why, and
  correct it by editing a file.

The honest limits: pure lexical retrieval misses paraphrase and semantic
similarity, and scanning frontmatter grows linear with the fact count. Facts are
written **atomic and self-contained** precisely so that a vector index can be
added later as a pure accelerator — no schema change — once `facts/` crosses a few
thousand files. Until then, the transparency is worth more than the recall.
