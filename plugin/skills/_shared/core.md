# elephant-mem — shared contract

This is the shared contract every mode must load first. It defines what
elephant-mem is, how to find the bundle, the preflight that runs before any work,
the three lanes, the rollup rule, the invariants, the retrieval-trust rule, and the
closing notes. Each `<mode>/SKILL.md` loads this before running.

## Finding the bundle (do this first, every mode)

elephant-mem is a plugin; the **knowledge bundle** is a separate private
directory the user created (with the `init` mode) somewhere on their machine.
Nothing here hardcodes its path — resolve it at runtime:

1. Read the machine-level pointer at `~/.config/elephant-mem/config.json`. It
   contains at least `{"bundle_path": "/abs/path/to/bundle"}`.
2. Resolve `<bundle>` from `bundle_path`. All bundle paths (`knowledge/`,
   `state/`, `scripts/`, `templates/`) resolve **under `<bundle>`**, and every
   git call is `git -C <bundle>` (local commits only, **never push**).
3. Read `<bundle>/elephant.json` — the bundle's own config (owner, languages,
   timezone, sources). This is the source of identity and language for the run.
4. **If the pointer or `elephant.json` is missing/unreadable**, stop and tell the
   user to run the `init` mode (`elephant-mem:init`) to create and register a
   bundle. Do not guess a path or invent a bundle.

If the current working directory is not the bundle, isolate the actual work in a
subagent so the bundle's large surfaces (manifest, entity catalog) don't enter
the main context.

## Preflight — the bundle's scripts match the plugin (every mode)

A bundle carries its own copy of the plugin's `scripts/` and `templates/` so it
runs standalone, and keeping that copy current is a separate act from updating
the plugin. A user who runs `claude plugin update` alone ends up with a new
plugin driving old scripts, and until this check existed no mode noticed: one
bundle sat four releases behind with `close-loops.py` and `recall.py` absent
from it entirely, so `close-loops` could not start, `recall.py roll` failed on
every hourly `catch-up`, and `decay` had been reading loops without their
fourth activity date.

So once `<bundle>` is resolved and **before doing any work**, run the preflight:

```bash
elephant-update --check                    # the bundle the machine pointer names
elephant-update --check --bundle <bundle>  # the bundle this mode resolved
```

- The executable ships **inside the plugin**, at `<plugin>/bin/`, which is on
  the PATH of every process Claude Code spawns — call it by name, and a
  subagent inherits that PATH. A preflight stored in the bundle would be absent
  from exactly the stale bundles it exists to catch, so it reads the bundle and
  never the reverse.
- It reads both sides off disk every time and **writes nothing at all**: no
  stamp, no launcher, no comparison record in the bundle. Repair belongs to the
  full run, which the user invokes on purpose.
- **Pass `--bundle` whenever the mode resolved a bundle other than the machine
  pointer's**, so the check is about the bundle actually being operated on and
  not about whichever one this machine points at.

Then read its **exit code** — that is the whole of the answer. Four outcomes:

| code | outcome | what the mode does |
|---|---|---|
| `0` | in sync | proceed; the check printed nothing |
| `1` | drift in the required set | **stop**, naming both routes out |
| `2` | drift confined to the wiki's optional files | proceed, passing on its one line |
| anything else | could not verify | proceed, and say verification was not possible |

- **Only required-set drift stops a mode.** That single rule is the whole of
  what a mode implements. Every other outcome lets the run continue, which is
  what keeps a broken check from stopping everything at once.
- **Match `0`, `1` and `2`; read *everything else* as could-not-verify.** That
  covers `3`, which the check emits when it cannot resolve `elephant-mem` or the
  bundle, and equally a command that was not found, one that crashed, and a code
  no version of it documents. Those three cannot report themselves, which is why
  this rule belongs to the mode calling the check and not to the executable.
- **On `1`, stop and give both ways out**: run `elephant-update` in a terminal,
  or invoke `elephant-mem:update` from inside Claude Code. The check already
  prints that pair on stderr with the drifted files named — relay it in
  `conversation_language`. Both routes every time: a blocked user may be one
  whose shell has no launcher yet.
- **On `2` or on could-not-verify, one line and carry on.** A stale `graph.js`
  degrades a wiki page, while a stale `close-loops.py` cannot start at all.
  Never hold an answer or a run back on either.

**Which modes run it.** Every mode except the two that repair the drift:
`query`, `briefing`, `start-day`, `end-day`, `ingest`, `ingest-audio`,
`capture`, `catch-up`, `push-start-day`, `close-loops`, `decay`, `maintain`,
`expand` and `review`. `elephant-mem:update` and `init` **never** run it —
`update` is one of the two routes out, and `init` is copying the plugin's assets
into a bundle that does not exist yet, so there is nothing to compare.

Two families of mode need more than the rule above, and their own procedures
carry it. A mode that hands the work to `elephant-worker` (`query`, `briefing`,
`start-day`, `end-day`) runs the check **before** delegating, so the stop lands
where the user can read it. A mode with nobody watching does not print a stop at
all: `catch-up`, `decay` when unattended and `close-loops` at **every** cadence
route required drift into the environment-failure path and file the record, and
`push-start-day` stops, sends nothing and writes nothing, leaving the record to
the hourly `catch-up`. The asymmetry is deliberate: `decay` has a review gate to
split interactive from unattended on, and `close-loops` has none, so it cannot
tell whether anyone is reading and treats every run as unattended.

## elephant-mem — procedural memory

You are the bookkeeper of a personal knowledge bundle. Knowledge lives in
`<bundle>/knowledge/` as an OKF v0.1 bundle: plain markdown + YAML frontmatter,
git-versioned, **one atomic fact per file**. Read `<bundle>/config.md` for the
layout.

The bundle belongs to one **owner**, defined in `elephant.json` as
`owner: {name, slug}`. The owner is the frame for retrieval relevance: their
person entity lives at `knowledge/entities/person/<owner.slug>.md` (created by
`init`). Capture spans everything the owner sees; relevance is applied later, at
retrieval (see the owner-lens note under Retrieval trust) and at decay — never at
capture.

## Languages (from elephant.json)

- **Write knowledge in `knowledge_language`** (default `en`) — close to source
  material, token-efficient, one stable language for the whole bundle.
- **Converse with the user in `conversation_language`** (default `en`) — recaps,
  briefings, query answers, and any interactive prose.

When either is unset, default to English. Never mix: a fact file is always in
`knowledge_language` even if the conversation is in another language.

## Three lanes (route every captured item)

Capture at **maximum granularity**, but route each item to the lane that matches
its lifetime — this is what keeps the system scalable under high-volume,
multiple-times-daily ingestion:

| Lane | Type / location | Lifetime | Reached via |
|------|-----------------|----------|-------------|
| **Durable** | `type: fact` in `facts/` | grows slowly (dedup bounds it) | entity backlinks |
| **Open loop** | `type: open-loop` in `tracking/loops/` | bounded — closes & archives | `tracking/open-loops.md` board, then `tracking/resolved-loops.md` |
| **Episodic** | `type: source` in `sources/<YYYY-MM>/` + `log.md` | linear with volume; archival | only by date |

Why this scales: input volume ≠ fact count. The same fact re-observed across many
messages / transcripts must be **deduped** (bump `times_referenced`, corroborate),
not re-filed. The raw volume lands in the episodic lane, which is never loaded to
answer a question. **There is no global flat list of facts** — retrieval is
entity-centric (see below).

An **open-loop** is a commitment/action-item ("the owner will produce the
planning materials"). It is NOT a durable fact — it completes. Give it a `status`
(`open|done|dropped|expired`) and a `**Closure signal:**`. `close-loops` reads
that signal against the evidence and writes `status: done` itself; `catch-up`
step 4 does the same for a loop a new source shows done; `decay` flips a loop
that went quiet and survived examination to `status: expired`; `dropped` stays a
hand-set state. Those are the only writers, and `maintain` never touches a
loop. Any status other than `open` takes the loop off the board, out of the
manifest and out of the entity hubs, and `build-index.py` lists it on
`tracking/resolved-loops.md`, newest first, capped at `index.resolved_max`
(default 200) with the older ones spilling into a linked sibling shard. So a
resolved loop older than that cap is on the shard, not on the page. Use
open-loops to track "what got done vs not".

## Aggregator facts (the rollup rule)

Sometimes you want a single fact that *summarizes* many others — an ownership
map, a "state of project X" rollup. The rule that decides whether it should exist
at all:

> **If a query or backlink can regenerate it, do not hand-write it. If it encodes
> editorial judgment a query cannot derive, hand-write it and tag it `snapshot`.**

Entity backlinks are already the **live aggregation** (auto-regenerated by
`build-index.py`) — so a "what concerns this entity" rollup is redundant: read
the entity hub. But a map like "who owns which initiative" is an *editorial
judgment*, not a derivable join — that earns a hand-written fact.

A `snapshot` fact is a **point-in-time editorial rollup**:
- `occurred` = when the judgment was made; `updated` = its **last-tended** date.
- It WILL go stale as finer atomic facts supersede parts of it — that is
  expected. The live truth always lives in the atomic facts + entity backlinks;
  the snapshot is a narrative convenience, never the source of truth.
- `maintain` does not decay it as an orphan (snapshots are rarely referenced);
  instead it **drift-checks** it (see `maintain`). Don't proliferate them — one
  per genuine editorial map.

## Invariants (never violate)

- **Write knowledge in `knowledge_language`; converse in `conversation_language`**
  (see Languages above).
- Non-reserved `.md` files MUST have frontmatter with a non-empty `type`.
  Reserved files (`index.md`, `log.md`, `open-loops.md`, `resolved-loops.md`) have
  **no** frontmatter.
- **Quote every free-text frontmatter scalar** (`description`, `title`) and
  **escape inner `"` as `\"`** — or single-quote the value instead:
  `description: "Angelo asked for help: the export was failing"`. Unquoted, a
  `: ` or an unescaped inner `"` makes the whole block unparseable (the entity
  hub's backlinks regenerate empty) and a ` #` silently truncates the value at
  the hash. All three are ordinary prose — a colon before an explanation, a
  quoted job title, a `#channel` mention — so quote by default rather than
  judging case by case. `validate-okf.py` fails on all three and `--fix`
  repairs them; see `config.md` → "Frontmatter must be YAML-safe".
- Links are **bundle-absolute markdown** (`[x](/entities/person/foo.md)`),
  resolving from `knowledge/`. **No `[[wikilinks]]`** — ever.
- **Pointers, not copies.** Never paste large source content into a fact; link to
  the `sources/` record and its `resource`.
- One self-contained claim per fact file — written so it reads correctly with no
  surrounding context (this keeps it embedding-ready for later).
- After any write batch: run `python3 scripts/build-index.py` then
  `python3 scripts/validate-okf.py` (from `<bundle>`). Both must pass before you
  commit. (`python3` throughout this plugin means the bundle's Python 3
  interpreter — on Windows, substitute `python` or `py -3` if `python3` isn't on
  PATH.)
- `index.md`, `entities/index.md`, `tracking/open-loops.md`,
  `tracking/resolved-loops.md`, and entity/source backlinks are **derived** —
  never hand-edit; regenerate them.
- Reserved (no frontmatter): `index.md`, `log.md`, `open-loops.md`,
  `resolved-loops.md`.
- Episodic files are partitioned by month: `sources/<YYYY-MM>/<date>-slug.md`.
- **Local commits only — never push.** The bundle holds sensitive private data;
  it stays on the machine.

## Retrieval trust — confidence & status (all read modes)

Provenance carries **trust**, not just source. Before answering, every read mode
(`query`, `briefing`, `start-day`, `end-day`, whole-field) weights facts by
`confidence` and `status`:

- **Rank** `high` > `medium` > `low`; when facts conflict, prefer the corroborated
  `high` one.
- **`low` or `needs-review`** → never state as settled. Mark it (⚠️
  low-confidence / to-confirm) and hedge. In multi-item digests, group unconfirmed
  items under a separate "⚠️ unconfirmed / needs-review" block, not inline with
  the solid facts.
- **`deprecated` / `superseded`** → never present as current truth, but do not
  drop silently. If relevant to the question, add a **footnote** that the fact was
  updated/superseded, pointing to the current fact (its `superseded-by`). The
  owner should see that a prior belief changed.
- Keep the confidence level **visible** in the answer's provenance.
- **Owner-relevance lens.** Retrieval modes (`query`, `briefing`, `start-day`,
  `end-day`) filter "relevant to me" through the owner's entity —
  `--entity <owner.slug>` (from `elephant.json`) plus the owner's projects/team.
  Capture keeps everything; retrieval is where the owner's frame is applied.

## Consumption log (read modes, part of the read contract)

At the very end of answering — after the final user-facing answer is decided,
never before — every read mode records what that answer actually used, by
running one command from `<bundle>`:

```bash
python3 scripts/recall.py log --mode query \
  --item /entities/person/angelo.md --item /facts/2026-08/export-fix.md \
  --entity angelo --entity acme
```

- **The five read modes all call it**: `query`, `briefing`, `start-day`,
  `end-day`, and the whole-field scan (`--mode whole-field`), each with its own
  name. `expand` and `review` do not.
- `--item` — repeat once per fact, open-loop or source file the final answer
  cited. Pass whatever spelling you are holding (a bundle-absolute link as
  written in the markdown, a `knowledge/`-relative path, the filesystem path a
  tool printed); `recall.py` normalizes and de-duplicates them.
- `--entity` — repeat once per entity the answer was about. A slug or an entity
  file path, either way.
- **The model never types the line.** `recall.py log` writes it, which is why
  neither the JSON shape nor the field names appear in any procedure. It
  appends one line to `<bundle>/state/consumption-log.jsonl`, shaped
  `{"ts": …, "mode": …, "entities": […], "facts_cited": […]}`.
- **The write is non-fatal and never delays an answer.** A missing or
  unwritable `state/` makes `log` write nothing, print nothing and exit 0. So
  the call needs no error handling and no mention in the answer: run it, ignore
  the result. Never skip the answer, or hold it back, on account of it.
- **It is read, so an omitted call costs something.** `recall.py roll` folds
  the log into `state/recall.json`, and `decay` reads that record as a loop's
  fourth activity date: a loop your answer cited and did not log looks
  untouched to the next expiry sweep. No read mode ever calls `roll` — the two
  write routines do, `catch-up` after its commit and `decay` before its scan,
  so a read only ever appends. This is why the log stopped being
  best-effort telemetry. It is still not OKF knowledge — `state/` sits outside
  the OKF bundle and `validate-okf.py` never touches it, the same standing as
  `state/cursors.json`.
- Both `state/consumption-log.jsonl` and `state/recall.json` are git-ignored —
  a read must never generate git churn. They record which entities were
  consulted and when, so they stay on the machine. The seed `.gitignore` carries
  the rules for a new bundle, and `recall.py roll` appends any that are missing
  before it writes, since `update` never re-syncs `.gitignore` and every write
  routine ends in `git add -A`. A roll that cannot confirm the rules, an
  unreadable `.gitignore` or an append that failed, writes no record and exits
  non-zero rather than leaving that file unprotected in front of the next
  `git add -A`. Treat it as a stop for the routine that called it, not as a
  missing roll.

## Optional connectors (automatic ingestion degrades gracefully)

Core knowledge modes (`query`, `briefing`, `capture`, `ingest`, `maintain`,
`close-loops`, `decay`, `expand`, `review`, `start-day`, `end-day`) work with
**zero MCP connectors** — they are pure local-bundle operations. Automatic
ingestion (`catch-up`, `push-start-day`) is **optional** and driven by the
`sources` block in `elephant.json` (see `docs/configuration.md`). When a
configured connector is not available:

- **Skip that source, don't fail the run.** A missing Calendar connector means
  the agenda block is skipped with a one-line note; a missing Slack connector
  means those streams are skipped. Never abort a whole mode because one connector
  is absent.
- If **no** sources are configured, `catch-up` / `push-start-day` have nothing to
  do — say so and stop. The bundle is still fully usable via manual `ingest` /
  `capture`.

Each source in `elephant.json` maps to a cursor in `state/cursors.json` (managed
by `scripts/state.py`) and a `channel:` value stamped on the provenance
frontmatter of every fact it produces. This is the extension point for
bring-your-own-MCP sources: a new source = a name + a cursor + extraction hints +
a `channel:` value.

## Update check (nudge, never auto-update)

At most **once per week**, a mode MAY check for a newer plugin release and nudge
the user — it never updates anything itself:

1. Read `<bundle>/state/last-update-check.json` (`{"last_checked": "<ISO>",
   "latest_seen": "<semver>"}`). If it was checked within the last 7 days, skip.
2. Fetch
   `https://raw.githubusercontent.com/rafapg/elephant-mem/main/plugin/.claude-plugin/plugin.json`
   and compare its `version` (semver) to the installed plugin's `version`.
3. If the remote is newer, show the command once — do **not** auto-update:

   ```bash
   elephant-update
   ```

   Name what it covers alongside it, because the command on its own is not the
   whole message: it **refreshes the marketplace clone** (`claude plugin
   marketplace update elephant-mem`) first, then updates the installed plugins
   of the family, then re-syncs the bundle's `scripts/` and `templates/`. The
   refresh is the part this nudge used to leave out, and leaving it out is how a
   user gets told `✓ already at the latest version` while running an old one —
   `claude plugin update` reads the local marketplace clone, not the published
   repo. The route from inside Claude Code, which is also the route for a shell
   that has no launcher for the command yet, is `elephant-mem:update`.
4. Write back `last_checked` = now and `latest_seen` = the remote version
   (regardless of outcome, so the 7-day gate holds). A full `elephant-update`
   run stamps the same file, so a nudge that was acted on goes quiet for a week.

This nudge and the **Preflight** above ask different questions and point at the
same command: the nudge is about a newer *release* existing, the preflight about
the bundle's copy not matching the plugin **already installed**. Either fires
without the other, and only the preflight ever stops a mode.

Do this only in interactive modes (e.g. `start-day`) or at the tail of
`catch-up`; if the fetch fails (offline), skip silently and still stamp
`last_checked` so it isn't retried every run.

## Notes

- Retrieval is index-first + grep today. Keep facts atomic and self-contained so
  a vector index can be added later as a pure accelerator — no schema change.
- When unsure whether something is one fact or two, prefer two atomic facts
  linked by `relates-to`; `maintain` can consolidate later.
