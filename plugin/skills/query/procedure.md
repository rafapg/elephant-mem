# `query` procedure

Load `../_shared/core.md` first (always). This file is the `query` procedure.
For entity work, also load `../_shared/entity-resolution.md`. Obey **Retrieval
trust** in `../_shared/core.md`. The recall escape hatch is the **whole-field
scan** — see `../_shared/whole-field-scan.md`.

Read-only, **entity-centric** retrieval from the elephant-mem knowledge bundle.
Answer in the bundle's `conversation_language` (from `elephant.json`) **with
provenance**: cite the fact files and their `sources`. Never enumerate the
whole `facts/` dir. Do not write knowledge (no OKF churn on reads); the one
write this mode does make is the consumption-log line in the last step, into
git-ignored `state/`.

**Navigation goes through `scripts/search.py`, not through the catalog and the
hubs.** Reading `knowledge/entities/index.md` whole and then one hub per entity
cost ~208 KB per query on a mature bundle before a single fact body, and grew
with the bundle. `search.py` filters `knowledge/manifest.jsonl` (active facts
and open loops), prints one page of `desc` lines inside a 32 KB budget, newest
first, and ends with the facets of the whole matched set to refine by. So this
procedure **never reads `entities/index.md` whole and never opens a hub** for an
ordinary question. Run every command from `<bundle>`.

Keep a running total of the bytes you read, for the log: each `search.py`
output ends with `bytes: <n>`, its exact size; add those, the size of each fact
body you open, and the size of any fallback output.

## Levels, cheapest first, each with its ceiling

1. **Names, all in one call.** Pass every person, project or thing named in
   the question to a **single** search, each as written, with `--any` when
   there is more than one:

   ```bash
   python3 scripts/search.py --entity "<name 1>" --entity "<name 2>" … --any
   ```

   (one name: `python3 scripts/search.py --entity "<name as written>"`). Never
   one call per name: each call that resolves prints a page, and one page per
   name would spend the query's page ceiling (level 3) before the first real
   look. The script resolves every name against
   `knowledge/entities/roster.tsv` (slug, title, aliases), case- and
   accent-folded: exact, then a whole word of a name, then similarity. It
   prints rows only when **every** name resolved, so branch on the exit code:

   - **`0`** — all resolved, and the output is already the first look of level
     3 (page 1 of the union), counting as one page. When the header's
     `resolved:` lines say `by similarity`, check that entity against the
     question before you trust it; a fuzzy match on the wrong person answers
     about someone else. When one says `also matches: …`, make sure the exact
     match is the one the question means.
   - **`3`** — at least one name is ambiguous: each such name's deciding tier
     is listed with slug, kind and title, and no rows were printed, so no page
     was spent. Settle each from the question's context and run the same
     single call again with the slugs; when the context does not settle it,
     ask the user rather than pick.
   - **`4`** — a name was not found, or there is no roster; no page was spent.
     Read `knowledge/entities/roster.tsv` whole, once, and resolve there
     (`../_shared/entity-resolution.md`); when the roster is absent,
     `knowledge/entities/index.md` instead, as that file prescribes. Log
     `roster` as a level, then run the single call again with the slugs.

2. **Themes with no entity.** When the question names a topic rather than an
   entity, find entities by description with `rg -i '<term>'
   knowledge/entities/index.md` (matching lines only, never the file whole;
   log `catalog-rg`), and/or search the manifest's descriptions directly with
   `python3 scripts/search.py --text "<words>"`.

3. **Search.** The first look is the page level 1 already printed: the
   resolved entities, `--any` when there is more than one (a union, interleaved
   so each entity gets its share of the page). Do not repeat it. Then refine by
   what the footer offers instead of descending the same list:
   - both entities on one row matter (the answer turns on the pair): the same
     `--entity` flags without `--any`, an intersection;
   - a co-occurring entity from the `entities:` facet: add it as `--entity`;
   - a tag from the `tags:` facet: `--tag`;
   - a period the question implies, or a month from the `months:` facet:
     `--since YYYY-MM-DD` / `--until YYYY-MM-DD`. **When the question points to
     the past, refine by date rather than paging toward it**: the footer's
     `cut at <date>: N more behind it, none newer than <date>` says how many
     matches the page did not reach and that every one of them is dated on or
     before `<date>` (the newest row left behind, in either ordering);
   - words the answer must contain: `--text "<words>"`.

   The next page of the same list is `--page N`, the exact suffix the footer's
   `next:` line prints. **At most 4 search pages per query, across every
   `search.py` call**, level 1's included (each call that prints rows prints
   one page; a call that exits 3 or 4 prints none). After the fourth, do not
   read a fifth: answer from what you have, or fall back (level 5) and record
   it.

4. **Bodies.** Open the fact or loop files the answer will cite or must check,
   and only those: **at most 20**. The `desc` lines already printed are the
   triage; a body is for the detail, the `sources` and the provenance.

5. **Fallbacks**, in this order, each recorded as the log's `--fallback`:
   - `facts-rg`: `rg` over `knowledge/facts` for the question's terms, when no
     entity matched and the search's `--text` came back empty;
   - `whole-field`: the whole-field scan (`../_shared/whole-field-scan.md`),
     when the `rg` fallback is still empty or too noisy.

   **History** is the one exception to "never open a hub": when the question
   explicitly asks for it ("what did we used to think about X", "everything,
   including old stuff"), you may open that entity's hub and follow its
   `→ N older/superseded facts: [archive](...)` link (build-index.py's hub
   sharding), which also lists superseded facts the manifest does not carry.
   Log `archive` as a level. For an ordinary "what do we know about X", the
   search is the current truth and the archive is out of scope.

6. **Consumption log.** After the answer is finalized, run from `<bundle>`,
   with one `--item` per fact/loop/source file the answer cited, one
   `--entity` per entity it was about, and what the read cost:

   ```bash
   python3 scripts/recall.py log --mode query --item <path>… --entity <slug>… \
     --question "<the user's question, verbatim>" --pages <search pages read> \
     --bytes <the running total> --level <level>… --fallback <name>
   ```

   `--level` once per level you used: `names`, `roster`, `catalog-rg`,
   `search`, `body`, `archive`, `facts-rg`, `whole-field`. `--fallback` is
   `facts-rg` or `whole-field` when you took one, and omitted otherwise (it
   records `none`). See `../_shared/core.md`'s Consumption log section. The
   script writes the line, guesses who ran the read on its own, swallows any
   failure and always exits 0, so there is nothing to handle and nothing to say
   about it in the answer.

> **Recall escape hatch:** when no entity matches and the `rg` fallback is too
> noisy, don't reach for vectors — use the **whole-field scan** (see
> `../_shared/whole-field-scan.md`), pre-filtered as that file requires. The
> manifest no longer fits a subagent's context whole (a mature one is millions
> of bytes), which is why the search pages it and the scan filters it first. A
> vector index is the next phase's question, and it is decided from the data
> this log now records (pages, bytes, levels, fallbacks) rather than guessed:
> hybrid search with embeddings, configurable local or external, local by
> default and its key outside `elephant.json`. It would be a disposable derived
> accelerator over fact `description`+body, never the source of truth; nothing
> of it is built here, and `index.md` stays for human navigation.
