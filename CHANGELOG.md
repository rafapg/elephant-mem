# Changelog

All notable changes to elephant-mem are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-beta.13] - 2026-09-03

The open-loop lane had no exit. Measured on the owner's bundle: 2036 loop files,
1794 still `open`, 236 `done`, 6 `dropped` — a 12% closure rate over the life of
the bundle, and a `tracking/open-loops.md` board of 541 KB. The one mechanism
meant to bound the lane, `decay-loops.py`, read staleness off
`max(updated, opened, created)` and expired anything past 45 days, which sounds
like a bound until you look at what writes `updated`. Nothing did.
`decay/procedure.md`, `decay/SKILL.md` and the script's own docstring all stated
that `catch-up` and `capture` bump a re-mentioned loop's `updated:`; no procedure
did, and none ever had — the `bump` rules those two carry are about a fact's
`times_referenced` and `confidence`, or about `backlog.py`'s `seen` counter, and
none of them is about a loop. `updated` differs from `created` on 180 of the open
loops, 10%. So the clock ran on creation dates, and the only safe decay was no
decay.

Both halves of the fix were already on disk and neither was read. The criterion
for closing a loop is written on 2025 of those 2036 files, under a
`**Closure signal:**` heading no code ever opened. The record of what the owner
actually consults is `state/consumption-log.jsonl`, which shipped with the right
trigger and was written by 2 of the ~14 modes, as a JSON object every adopting
procedure re-typed by hand. This release reads both, and puts a routine that
closes loops by evidence in front of the one that expires them by silence.

### Added

- **`close-loops`, a daily unattended mode**, and the read-only
  `close-loops.py` behind it. Each run takes a bounded, ordered slice of
  `tracking/loops/` — first the loops examined before whose entities have gained
  a fact or a source since that examination, then everything else oldest last
  activity first, up to `close_loops_max` (default 25). The second band is
  ordered by activity rather than by last examination on purpose: it puts the 735
  already-stale loops at the front, and gives a never-examined loop a defined
  position, which a last-examination date cannot. For each queued loop the script
  emits its closure criterion (its `description` when it carries no
  `**Closure signal:**`, saying so) and up to 10 ranked evidence candidates —
  facts sharing the loop's non-owner entities first, then content-word overlap,
  then recency. The cap and the non-owner rule are the whole point of the
  ranking: on the owner's entity alone the median candidate count is 684. The
  mode judges each evidence set as a whole rather than matching the criterion
  literally, and every closure writes its own justification, so a wrong `done` is
  legible where it was written and not only in a diff.
- **`recall.py`**, the consumption record, modeled on `backlog.py`: `log` appends
  one citation line per answered read, `roll` folds the log into
  `state/recall.json`'s buckets, `show` and `score` read it back, `--at` on every
  mutation for tests. The pyramid is item-agnostic and bought for read cost, not
  disk — day-by-day for 14 days, week-by-week to 90, month-by-month to 365, one
  aggregate beyond. 26 lines over 33 days is 26.8 KB; what does not scale is the
  question decay asks once per open loop, against a log that only grows. `roll` makes that a dict lookup.
- **`state/closure-sweep.json`**, control state rather than audit: which loops
  were examined and when, written for every examined loop whether it closed or
  not. It is what lets decay know something was actually looked at. Losing it
  parks decay instead of corrupting it — every loop then reads as never examined,
  and `--skip-sweep` is the deliberate way out, the same flag that restores the
  behavior this release replaced.
- **`tracking/resolved-loops.md`**, generated newest first with each resolved
  loop's date, outcome and the first sentence of its resolution, capped at
  `index.resolved_max` (default 200) and overflowing into a sibling archive shard
  by the mechanism `hub_max_facts` already uses, so it cannot become a second
  541 KB board. Moving or deleting a resolved loop file was never available:
  loop paths are cited 4136 times from durable, non-regenerated text — 2784 in
  source bodies, 745 in facts, 603 in `log.md` — and `validate-okf.py` requires
  every one of them to resolve before any routine commits.
- **`tests/test_recall.py` (81 checks) and `tests/test_close_loops.py` (69)**,
  each with its own `- run:` line in `ci.yml`, added in the same change that
  created the suite. A glob does not pick up a new suite; `test_backlog.py` went
  a full release unrun for want of that line. `tests/test_decay.py` grew to 84
  checks and `tests/test_index.py` to 80.

### Changed

- **`decay` expires only what `close-loops` has already read, and says why.**
  A candidate is expirable only if it was examined after its own last activity
  and was not closed; a candidate never examined is refused by name, with the
  `close-loops` command printed, exit 0. The gate only ever meets loops that are
  already stale, so a freshly bumped loop is out of scope before it is consulted.
- **Recall enters decay as a fourth activity date** inside `last_activity()`,
  not as a veto pass with its own window. No new config key, and an empty or
  absent record collapses to the previous behavior exactly. `decay` step 1 now
  runs `recall.py roll`, and so does `catch-up`'s commit step, so the pyramid is
  fresh where it is read and the raw log does not grow unbounded.
- **A resolution is prose in the loop file's body**, under a `**Resolution:**`
  heading, written identically by `close-loops` and by `decay`. Not a frontmatter
  field: the justification is a sentence of judgment, and frontmatter breaks on
  `: ` and truncates silently on ` #`, which the loop template already carries
  three lines of warning about. The structured parts (`closed`, `closed_by`,
  `expired`) are existing fields and stayed there. No new frontmatter field was
  added, because every bundle on disk would carry loops without it and only its
  owner could fix that.
- **The consumption log stopped being "best-effort telemetry" and became part of
  the read contract.** The write is still non-fatal and still never delays an
  answer, but it now has a consumer, and a signal with no consumer had no quality
  pressure. All five read modes `core.md` lists call it — `query`, `briefing`,
  `start-day`, `end-day` and the whole-field scan; `expand` and `review` stay
  out. The model no longer types the JSON: `recall.py log` writes it, which kills
  the malformed-line and missing-field classes and puts the swallow-and-continue
  in one place instead of in every procedure.
- **Resolved loops leave the entity hubs.** `build-index.py` no longer re-files
  a non-`open` loop as a history line, and `briefing.py` no longer prints one
  under `## Open loops` because its `opened` date fell in the window
  (`--include-resolved` shows them). `tracking/resolved-loops.md` is their one
  listing. Both surfaces are derived, so this is one line to reverse and loses
  no data.
- **`expired` joined `build-index.py`'s hardcoded `loop_status` default, and
  `init` now copies `vocab.json` into new bundles.** Not defensive: no bundle had
  ever received that file, so the hardcoded fallback is what runs in the field,
  and under it an expired loop was in neither the open bucket nor the history
  one. It did not vanish, which would have been the tolerable failure — it
  rendered on the hub as a current item and consumed a slot of `hub_max_facts`.
  `update` still never re-syncs `vocab.json`; a bundle may have extended its own.

### Fixed

- **The re-mention claim was deleted from all three places and made true in
  one.** `catch-up` step 4 now carries the bump rule next to the close rule it
  already had: a source that re-raises an open loop without showing it done bumps
  `updated:` to **that source's own date**, never today's, and leaves it alone
  when the source has no date. That plus `decay`'s review-gate snooze are the two
  documented writers of the field, and `capture` is named as not being one — it
  opens loops and never revisits one.
- **`decay/procedure.md` said the rebuild re-files an expired loop into entity
  history.** It did not, and after this release it deliberately does the
  opposite: a resolved loop leaves the hubs outright and
  `tracking/resolved-loops.md` is where it is listed.

## [0.1.0-beta.12] - 2026-09-02

0.1.0-beta.11 closed one accident and left an intent open in the same breath: the
four templates under `assets/templates/` are copied into every new bundle by
`init` and re-synced by `update`, and nothing validated them. Writing the check
found the reason a check would have been worth having. `validate-okf.py` compared
the raw frontmatter line to the controlled vocabulary, so the documenting comment
the templates carry on each vocabulary field counted as part of the value. A
bundle built from the four templates warned five times about itself
(`out-of-vocab kind='concept         # person | org | …'`), and so did every file
a model wrote keeping that comment, which is what a template is for.

### Added

- **`tests/test_templates.py`**, 22 checks, mounting the four templates as a
  real bundle and driving it. That they exist and each declares the `type` its
  filename claims: a suite that only ran the validator would pass vacuously on a
  template deleted or renamed, the exact shape of the pass 0.1.0-beta.11 removed
  from CI. That the bundle passes `validate-okf.py` with exit 0 **and** no
  warnings, checked separately because a warning leaves the exit code at 0. And
  that **every** script which reads a bundle runs over it, six of them, each
  asserting something substantive rather than exit 0 — exit 0 while saying
  nothing is what all six defects below looked like. A template is a contract
  with every script that reads a bundle, so the reader list is derived from a
  glob minus named exemptions carrying their reason, and a twelfth script is red
  until someone writes a driver or an exemption for it. Restoring any of
  `decay-loops.py`, `snapshot-drift.py`, `rename-entity.py` or `validate-okf.py`
  to its pre-fix version turns the suite red; `build-index.py` and `briefing.py`
  are held by `tests/test_frontmatter.py` instead, which forces the fallback
  parser in-process and so catches them on both legs of the matrix rather than
  only where PyYAML is absent. Its `- run:` line is in `ci.yml`: a glob does not
  pick up a new suite, and `test_backlog.py` went a full release unrun for want
  of that line.

### Fixed

- **`vocab_warnings()` reads a vocabulary value without its trailing YAML
  comment.** The rule already existed one function above, in `classify_value()`,
  and is now a shared `strip_comment()` helper: the cut is on `" #"` and never a
  bare `#`, so `(#9-channel)` stays content. Both readings in the function were
  wrong, not just the reported one. The second is `type_val`, which decides
  *which* fields get checked at all, so a `type: fact  # …` misrouted the whole
  dispatch and the file's vocabulary went unchecked in silence.
- **The fallback frontmatter parser strips a trailing YAML comment too.** The
  same defect as the entry above, one layer deeper and with a far wider blast
  radius. `build-index.py` and `briefing.py` parse frontmatter with PyYAML when
  it is installed and with a naive parser when it is not, and the naive one read
  the documenting comment as part of the value. A bundle built from the four
  shipped templates came out wrong three ways at once: the entity's `kind`
  reached `roster.tsv` as `concept         # person | org | project | …`,
  `aliases: []           # other names…` stopped matching the inline-list
  pattern and became that whole string instead of an empty list, and
  `status: open          # open | done | dropped` no longer equalled `open`, so
  the open loop was invisible to the surface that lists them —
  `1 entities, 1 facts, 0 open loops, 1 sources`. Not a template-only problem:
  those comments are the documentation the model reads while filling the file,
  so every user file that keeps one was misread the same way, on any machine
  without PyYAML — which CLAUDE.md describes as the ordinary local case, and
  which is half of CI's matrix. Both copies of the parser now mirror
  `validate-okf.py`'s rule and its quote scanning, so a `#` opens a comment only
  after a space and only outside quotes and inline lists: `resource:
  "slack:#canal"` and `(#9-channel)` survive intact, and a greedy cut is the
  regression the new cases guard against. 41 checks in
  `tests/test_frontmatter.py` hold it, among them an oracle that parses one
  block both ways and requires the fallback to agree with PyYAML field by field.
  One check that used to be skipped without PyYAML — that an unquoted ` #` is
  silently truncated before repair — now runs on both parsers, because they
  finally damage it identically.

- **The rule now reaches the regex readers, one of which was destroying data.**
  `strip_comment()` had reached the two `parse_fm()` copies and the validator's
  `vocab_warnings()`, and stopped there. Six other places read the same
  frontmatter of the same files with their own regexes and none had been taught
  it. `rename-entity.py`'s `merge_aliases()` anchored on `^aliases:\s*\[(.*)\]\s*$`,
  which cannot match past a comment sitting after the `]`, so the existing list
  read as empty and the merge became a replacement: `rename-entity.py t t2
  --alias Newname` over the shipped `entity.md` turned `["Tee", "T."]` into
  `[Newname]`, exit 0 and no warning, on the column `roster.tsv` resolves
  against. `decay-loops.py`'s `field()` glued the comment, so a
  template-derived loop never matched `status != "open"` and the whole decay
  mode was a no-op — and that script has no PyYAML branch at all, so it failed
  on every machine rather than half the matrix. `snapshot-drift.py` glued
  `occurred`, and since `newest()` compares those as strings, a fact tended the
  same day as the snapshot sorted *newer* and produced a false DRIFTED verdict
  with the comment printed in the report. The validator's own
  `alias_title_collisions()` was blind the same way through `ALIASES_KEY` and
  `TITLE_KEY`, which is the check that exists to surface entity conflation.
  `merge_aliases()` now also fails closed: an `aliases:` line it cannot read as
  an inline list aborts the write instead of replacing it.
- **`rename-entity.py` says what already landed when it refuses.** The guard
  leaves the `aliases:` line untouched, but it reported that as "Nothing was
  written to that file" — and in the plain rename path the move and the
  bundle-wide link rewrite run *before* the merge, so both had already landed.
  The message read as "the command did nothing" and sent the next run at a slug
  that no longer resolved.

## [0.1.0-beta.11] - 2026-09-02

Every script under `assets/scripts/` resolves its bundle as the parent of its own
directory. That is correct where they live once installed, `<bundle>/scripts/`,
and wrong in this repo, where the parent is `plugin/assets/` — the assets the
marketplace publishes. Run from a checkout, a script did not fail: it created the
bundle it expected to find, inside the shipped package. That is not a
hypothetical. `plugin/assets/knowledge/` held `index.md`, `manifest.jsonl`,
`entities/index.md` and `tracking/open-loops.md`, four empty derived files a
stray run had created and a `git add -A` had swept into 0.1.0-beta.2's Windows
UTF-8 fix. They have shipped in every release since.

Nothing read them and nothing leaked — `init` seeds from `assets/seed/` and
`update` re-syncs only `scripts/` and `templates/` — but the next run would have
added `entities/roster.tsv` to the pile, and a script pointed at a real bundle by
mistake is the same class of accident with content in it.

### Fixed

- **The nine bundle scripts refuse to run inside the plugin checkout**
  (`backlog`, `briefing`, `build-index`, `decay-loops`, `ingest-audio`,
  `rename-entity`, `snapshot-drift`, `state`, `validate-okf`). The signal is
  exact — the resolved root is named `assets` and carries a `.claude-plugin`
  sibling — so a bundle that merely lives in a directory called `assets` is
  untouched, which is its own check in `tests/smoke.py`. The guard sits under
  `__name__ == "__main__"`, because the suites import these modules to exercise
  their pure functions and only *execution* is the accident. Eighteen new checks
  cover both halves across all nine.
- **`plugin/assets/knowledge/` is gone**, and it plus `plugin/assets/state/` are
  now ignored. The ignore is the second lock: the guard is what stops the files
  being written at all.

### Changed

- **The `validate-okf.py` step is out of CI.** It ran the script straight from
  the checkout, where the only bundle it could find was that accidental
  directory, so "OKF validation passed" was a pass over four empty files. The
  script is exercised properly by the suites: 10 executions across `smoke`,
  `test_frontmatter` and `test_index`, each against a real throwaway bundle, plus
  three in-process imports that reach its functions directly. Its
  line in `CLAUDE.md`'s pre-commit block goes with it, and the reason is recorded
  there so it does not get added back.

  The deleted step carried a comment stating an intent it never met — that the
  shipped seed bundle satisfies the rules it asks users to satisfy. There is no
  `knowledge/` under `assets/seed/` for `validate-okf.py` to walk, so nothing was
  ever checked. The comment went with the step rather than being left to assert a
  check that is not there, and the intent stays open: the four templates under
  `assets/templates/` ship into every new bundle and nothing validates them,
  before this change or after it.

## [0.1.0-beta.10] - 2026-09-01

Extraction entered the bundle blind, and the pipeline made inventing an entity
the cheapest thing to do. `ingest` step 3 said to read `knowledge/index.md` and
the "matching `entities/` files", but `index.md` is a 4.8 KB router that names
no entity at all, and the only real catalog, `entities/index.md`, is 128 KB
because it carries a full description per entity. So a run grepped once per
candidate name and opened entity files averaging 12.2 KB to read the ~60 bytes
that actually decide a match — `title` and `aliases`. When a grep missed, and a
grep misses on every nickname the source spelled its own way, writing a new stub
was the shortest path available. That is the invented-entity failure, and it was
the pipeline's doing rather than the model's. This release gives resolution a
surface of its own: one bounded file, loaded once before extraction starts,
instead of a search performed during it.

### Added

- **`knowledge/entities/roster.tsv`, the resolution surface**
  (`assets/scripts/build-index.py`). One self-contained tab-separated row per
  **active** entity — `slug`, `kind`, `title`, `aliases` comma-joined — behind a
  single `#`-prefixed header, sorted by kind then title so a rebuild produces a
  stable diff. The bundle path is not stored: it reconstructs as
  `/entities/{kind}/{slug}.md`, which held for 639 of 639 entities in the bundle
  this was measured against. That, plus TSV having no repeated keys, puts a row
  at 58 bytes and the whole roster at 36 KB (~9k tokens) for all 639 entities,
  against 128 KB for the catalog and against the ~30k tokens a run already spent
  opening ten entity files. The same rows as JSONL would have cost ~25 KB more
  in key overhead alone, on the exact axis the change exists to reduce.

  It is emitted by `build-index.py` immediately after the catalog, from the same
  `active(entities)` list — no new traversal and no new script — and it writes
  through its own writer rather than the shared `write()` helper, which ends
  with `"\n".join(lines).rstrip() + "\n"` and would have eaten the trailing tab
  of a last row with no aliases, silently emitting three columns instead of
  four. Tab, CR and LF collapse to a space in any field, and a comma collapses
  inside a single alias, since that column is itself comma-joined; a comma in a
  `title` is left alone, because the column is tab-delimited and law-firm names
  carry real commas. The build summary now reports the roster's row count and
  byte size next to the existing counts, so growth is visible on every build
  without anyone going looking — the format is born shardable, and at the
  observed rate of entity creation the file passes 100 KB in 8 to 18 months.

  `entities/index.md` is untouched and byte-identical: it is what humans and the
  wiki read, and its descriptions are what the roster deliberately drops.

  A missing roster degrades rather than failing, and so does a **stale** one — a
  run that died between creating a stub and its rebuild leaves entities the file
  does not carry, and that is worse than an absent roster, because the resolver
  then creates a second entity for a name that already exists and files a
  `roster miss` line that reads as legitimate. Freshness is settled by the
  bundle's own git tree, which every writing mode leaves clean at its last step:
  clean means current, dirty means rebuild first. It is deliberately **not**
  settled by modification time, because `build-index.py` emits the roster before
  it rewrites the auto-facts blocks, so entity files are routinely newer than a
  roster that is perfectly current and `find … -newer` would report every run as
  stale.

- **Roster coverage in `tests/test_index.py`** — rows and sort order, the
  four-column last row with empty aliases, the three sanitized characters, the
  comma split inside an alias, deprecated entities excluded, an empty bundle
  yielding the header alone, the catalog unchanged, and `validate-okf.py` clean
  over a bundle carrying the roster. It extends the suite that already drives
  `build-index.py` instead of opening a new one, because a new suite needs its
  own explicit `- run:` line in `ci.yml` and `test_backlog.py` went a full
  release unrun for exactly that reason.

### Changed

- **`ingest` resolves against the roster** (`skills/ingest/procedure.md`). Step
  3 loads it once before the first candidate and holds it for the run, matches
  `title` then `aliases` in context, and reconstructs the path from the row, so
  a resolution the roster carries opens no `entities/*.md` file and costs no
  tool call. An entity file is opened only for its body — attributes, timeline —
  never to confirm an identity. A new entity's row is appended to the in-context
  copy **immediately**, before the next candidate is resolved: the file on disk
  is only regenerated at step 8, and two candidates naming the same new person
  in one run have to land on one entity.

- **`catch-up` loads the roster before the fan-out, and its subagents stopped
  returning slugs** (`skills/catch-up/procedure.md`). The load could not be
  inherited, and that was the easy thing to get wrong: step 4 reuses the
  `ingest` loop's core (steps 2–6), so a load written only into `ingest` step 3
  would have arrived *inside* step 4 — after the subagents had already run. It
  therefore carries its own explicit load, ahead of step 3, to the **main agent
  alone**, once per run rather than ~9k tokens × N.

  The second thing that did not survive the fan-out was context. Nicknames are
  speaker- and context-dependent — one meeting's "JJ" is a different person in
  the next — and the subagent reading the transcript holds that while the
  candidate spec it returned threw it away. So a candidate spec now carries
  **the name exactly as the source wrote it plus what disambiguates it** (who
  said it, which meeting or channel, what was being discussed) and **never a
  slug**: a subagent carries no roster, so a slug from there is invention rather
  than resolution. That costs ~20 tokens a mention against 9k per subagent, and
  it leaves the main agent holding both halves of the decision.

- **The no-invention rule became shared, with one artifact per failure**
  (`skills/_shared/entity-resolution.md`). Every mode that touches entities now
  inherits the roster as the resolution surface, in mode-neutral wording. A name
  the roster does not carry is the only case that creates an entity, and it
  costs a line in the run's log — `roster miss: "<as written>" (checked:
  <variants>)`. An ambiguity the mention's context cannot settle is not resolved
  to the likelier row: it gets the sibling line, `roster ambiguous: "<as
  written>" → <slug>, <slug>`, a `needs-review` tag and a `state/needs-review.md`
  entry naming both candidates. Both lines are greppable on purpose, so
  `grep -c 'roster miss' knowledge/log.md` is the instrumented form of the
  failure this release set out to reduce, and a stub filed without its line
  looks exactly like a resolution that worked. A missing roster degrades and
  never fails: run `build-index.py` once, then read it; if it is still absent,
  fall back to the catalog and say so in the log.

### Fixed

- **The docstring promised the manifest loads cheaply**
  (`assets/scripts/build-index.py`). Item 5 described `manifest.jsonl` as an
  "ultra-slim triage surface" a subagent "loads cheaply". It grows with every
  fact and is already 3.7 MB on a mature bundle, so the one place a reader looks
  to size it was telling them the opposite. It now says the surface is **not**
  cheap to load and points at the delegation rule in
  `skills/_shared/whole-field-scan.md`: hand it to a subagent, pre-filter with
  `rg`, never read it whole. Right-sizing the file itself is its own change.

- **The seed layout omitted two of the bundle's derived files**
  (`assets/seed/config.md`). `manifest.jsonl` had been missing from the `##
  Layout` block since it shipped, and the roster would have joined it; both are
  listed now. Note that `init` copies the seed once and `update` deliberately
  re-syncs only `scripts/` and `templates/`, so every bundle already on disk
  carries a diverged copy this edit never reaches — correcting it there is a
  manual step for its owner.

## [0.1.0-beta.9] - 2026-09-01

Two modes reported a state that was true of where they were running and false of
the system, and both messages were reassuring. `update` announced a new release
and then printed a command that reads the user's local marketplace clone, so the
CLI answered that they already had the latest — naming a version that was
current at whatever commit the clone had stopped on. `catch-up`, when a run
handed itself to a subagent with no MCP connectors, found every configured
source unavailable and logged an unremarkable empty window. Neither looked like
a failure from inside, and both survived being investigated, because in each
case the wrong explanation fit the evidence. This release makes the reports
name what is actually true.

### Fixed

- **`update` sent users into a loop it could not resolve** (`skills/update/SKILL.md`,
  `README.md`). The mode checks for a release by fetching the published manifest
  over the network, then printed `claude plugin update elephant-mem@elephant-mem`
  as the whole remedy. But that command does not read the repo — it reads the
  user's **local clone of the marketplace**, a git checkout of `main` under
  `~/.claude/plugins/marketplaces/`, refreshed only by `claude plugin marketplace
  update`. With a stale clone the two halves contradict each other: the mode
  announces a new release and the CLI answers `✓ elephant-mem is already at the
  latest version (0.1.0-beta.6)`, naming whatever `plugin.json` held at the commit
  the clone stopped at. Nothing is broken, nothing is actionable, and the obvious
  reading — that the published catalog lags the repo — is wrong, so the loop
  survives being investigated.

  The mode now prints `claude plugin marketplace update elephant-mem` first and
  states why it is not optional, the README documents updating as two commands,
  and the contradiction is written down as a symptom with a single diagnosis, so
  the next report resolves in one step instead of an archaeology session. Reported
  from the field against 0.1.0-beta.6; reproduced locally against 0.1.0-beta.8.

- **`catch-up` reported every connector unavailable when it was delegated to a
  subagent** (`skills/catch-up/SKILL.md`, `skills/catch-up/procedure.md`,
  `agents/elephant-worker.md`). Scheduled runs intermittently ended having swept
  nothing, logging *"toolset limited to Read/Bash/Write"* while the session that
  fired them had Slack, Calendar and Drive fully authenticated. The cause was
  not authentication: the run had been handed to `elephant-worker`, whose
  definition fixes `tools: Read, Grep, Glob, Bash, Write` and carries no MCP
  connector at all. That agent exists for the launcher modes, which read
  the bundle off disk and need no connector; nothing said `catch-up` was excluded, and it is the
  only elephant-mem agent in the registry, so a run that decided to isolate
  itself had exactly one place to go. Measured in one bundle: 33 occurrences
  before diagnosis.

  Three changes. `catch-up` now states that it runs on the invoking thread and
  why delegation buys nothing (a scheduled task already has a context of its
  own), keeping the one legitimate fan-out — step 3, over text already fetched.
  `elephant-worker` says in its own description and body that it holds no
  connectors and must refuse a sweep. And the routine no longer accepts the
  silence: a single connector missing is still skipped with a note, but **all**
  of them missing is now an environment failure — no cursor advances, nothing is
  ingested, the log entry names the toolset actually present, and the finding is
  filed as `catchup-invoked-without-mcp-connectors`. Connectors do not all
  drop on the same tick; that reading means the run is in the wrong place. The
  mislabel was the reason this survived 33 runs, since a silent no-op is
  indistinguishable from a quiet hour in `log.md`.

## [0.1.0-beta.8] - 2026-08-24

`ingest` is the primary verb of a memory system and Claude could not see it.
`disable-model-invocation: true` does more than block the Skill tool — it
removes the skill from the model's listing entirely, so "save this text for me"
produced no offer and no suggestion, because from inside the session that verb
did not exist. The only route in was typing its name, which is the one thing a
user has to already know. Meanwhile `capture` writes facts, rebuilds the index,
and commits — the same side effects — and has always been model-invocable. So
the flag was never protecting against side effects; it was protecting against
*unbounded input*, and that is an argument about what counts as a source, not
about who may invoke. This release moves the protection into the skill, where it
can say no to a stack trace and yes to an article.

### Changed

- **`ingest` is model-invocable** (`skills/ingest/SKILL.md`). The flag is gone
  and the description is written **negatively**, because the failure mode of an
  auto-invocable writer is a bundle full of debris. The trigger is the user
  asking for a source to be *remembered* — never a source merely appearing in
  the conversation. Named non-triggers: pasted stack traces, logs, diffs, test
  output, error messages, code, a page fetched while working on some other task,
  and the repository being worked in. When retention is unclear the instruction
  is to offer once and wait, never to ingest on a guess.

- **`ingest` is documented as auto-invocable** (`README.md`) and called out as
  the one auto-invocable mode that writes, with the confirmation behaviour and
  the "appearing is not a trigger" rule stated where users read the mode table.

### Added

- **A scope gate — step 0 of `skills/ingest/procedure.md`.** When Claude reached
  for the skill itself, it states the source, the kind of facts expected, and
  that this writes and commits, then waits. Silence, a topic change, or a hedge
  is explicitly **not** an accept, and it is one offer per source per
  conversation — a decline holds for the session, in the same shape `capture`
  already uses. Nothing is read, fetched, or written before the accept.

  The gate is skipped where it would be noise or harm: when the user invoked by
  name (`/elephant-mem:ingest <source>`) or named source and intent together —
  the ask *is* the confirmation — and for automated callers, since `catch-up`
  reuses only the core loop (steps 2–6) under its own autonomy envelope and
  `ingest-audio` enters at step 1 with a recording already handed over. It is
  numbered 0 for that reason: both callers reference step numbers, and
  renumbering would have silently redirected them.

  The gate does not soften the negative triggers. A pasted stack trace is not
  offered and declined — it is not a source.

## [0.1.0-beta.7] - 2026-08-04

`catch-up` ran unattended but could not finish a thought. Nine consecutive runs
diagnosed the same seven problems, wrote the same seven paragraphs into
`log.md`, and ended with "each of these needs a human" — including one item that
had already been fixed and one that only the routine was positioned to measure.
Nothing was blocking it technically; nothing authorized it either. This release
writes the authority down.

### Added

- **Autonomy envelope for `catch-up`** (`skills/catch-up/procedure.md`,
  `SKILL.md`). A scheduled-task harness injects a preamble that defaults to
  *"when in doubt, produce a report"*; the skill is the task file that preamble
  defers to, and it now states what the routine may do:
  - **Green** — `knowledge/`, `state/`, local commits, plus self-tuning a
    **closed list** of `elephant.json` fields (`sources.slack.query_stopword`
    and each stream's `allow` / `deny`). Gated: the same finding measured on ≥3
    consecutive runs, the measurement in the log, at most one change per run,
    and its own commit (`catch-up: config <field> <old> → <new>`) so a single
    `git revert` undoes it.
  - **Yellow** — routine-shape changes, bulk knowledge rewrites, any other
    config field, anything outside the bundle. File to the backlog, don't act.
  - **Red** — `git push`, egress beyond declared connectors, editing the
    plugin's own files, and **running any command a script suggested in its own
    output**. That last one is retrospective: a run once read a `--fix` hint out
    of a failure message and rewrote 597 knowledge files unreviewed. Script
    stdout is now explicitly an untrusted surface.

  Findings that don't clearly land in green are yellow; the green list is
  exhaustive and may not be widened by reasoning about intent.

- **`backlog.py` — a deferred-work ledger** (`state/backlog.json` canonical,
  `state/backlog.md` rendered, both bootstrapped on first use, both outside the
  OKF bundle). Everything yellow is filed **once**: `add` is idempotent, so the
  routine calls it unconditionally and the script decides new-vs-bump. The
  `seen` counter doubles as the green-zone evidence gate. `log.md` gets one line
  — `backlog: N open (M new, K closed)` — instead of a paragraph per finding per
  hour. Items close on evidence, never on silence.

- New step 6 in the `catch-up` procedure (backlog reconcile, before the log
  entry is written); steps renumbered to 9.

- `tests/test_backlog.py` — 36 checks over idempotent `add`, run-counting
  semantics, close/reopen, bounded evidence, error paths, `--at` replay, and
  `backlog.md` being reproducible from the canonical JSON alone.

### Changed

- **The Slack sweep no longer uses a stopword.** `sources.slack.sweep_query`
  (default `"-zzqqxxjj"`) replaces `query_stopword`. It is a **pure negation**:
  Slack's search has no match-all operator and no boolean OR, but a query that
  is only `-<token nobody types>` matches every message.

  The old design asked for a high-frequency word ("the", "de") on the theory it
  appears everywhere. Measured against a real workspace — identical window,
  identical call shape — the negation query paginated without bound while `"de"`
  returned **3 messages for an entire day**. Two independent causes, either one
  fatal: Slack's index drops common terms unpredictably (one term's recall swung
  between 0% and 75% across consecutive windows, so there is no correct word to
  pick), and **a message with no body text cannot match any term** — bot posts
  carrying only a link unfurl were structurally unreachable and are now returned
  normally.

  This closes the "sweep is lossy" finding that ten consecutive runs reported
  and that was previously scoped as a redesign. `query_stopword` stays honored
  as a fallback so existing bundles keep running; `catch-up` files a backlog
  item when it finds one.

- **`log.md` is oldest-first, always appended.** It claimed "newest first" while
  runs with content prepended and empty-window one-liners appended — the ledger
  read in two directions at once. The procedure now states one rule for both
  cases. Existing history is deliberately not reordered; the header says so.

### Fixed

- `state.py mark` had recorded the literal string `--help` as a processed Drive
  fileId (someone expecting usage text; `mark` treats every argument as an id).
  Harmless in itself — no file has that id — and now removed.

- **A cursor is a coverage watermark, not an ingestion watermark.** The old rule
  — "advance only past content you actually ingested" — was written to survive a
  partial failure, and it caused two opposite bugs, both seen in production:

  - A stream whose only new messages are all skip-ruled (bot noise, CI chatter,
    one-word acks) files nothing, so its cursor never moved and every later run
    re-read and re-rejected the same messages, at compounding cost. Examined and
    deliberately skipped **is** covered.
  - Reading a thread for context legitimately reaches messages outside the swept
    window, including days the backfill walk hasn't reached. Those may be
    ingested, but must **not** move a cursor — the sweep didn't cover them, and
    jumping the cursor would silently skip every day in between. Dedup absorbs
    the overlap when the day-walk arrives.

  The rule is now: **advance on successful coverage, hold only on failure.**

- **`exclude_bots` was relying on a default that doesn't hold.** The Slack search
  tool documents `include_bots` as defaulting to `false`; measured, omitting it
  returns bot messages normally while passing `include_bots=false` on the
  identical query returns nothing. Any stream with `exclude_bots: true` that left
  the parameter off was silently ingesting bot noise. The procedure now requires
  the flag be sent explicitly on every call, in both directions.

- **New-source seeding lost its first day.** `next-backfill` returns
  `backfill_oldest − 1`, so `backfill_oldest` means "already done" — seeding it
  to *today* claims today as done and starts the walk at yesterday, leaving
  everything posted earlier that day in a gap neither the forward sweep (strictly
  after `live_cursor = now`) nor the backfill walk covers. The procedure now
  spells out the off-by-one and says to seed `seed date + 1`. Found by the
  routine itself, via the backlog this release adds, on the stream this release
  added.

## [0.1.0-beta.6] - 2026-08-01

Two defects in the rule 5 that shipped in beta.5, plus a fourth failure mode it
never modelled. All three came from first contact with a real 5695-file bundle
rather than from the 63-check suite. If you ran `validate-okf.py` on beta.5 and
saw an "unterminated quote" on a line that looked fine, this is why — and
`--fix` could not clear it.

### Fixed

- **Fourth failure mode: a value starting with a YAML indicator.** A plain
  scalar may not begin with `` ` ``, `@`, `%`, `&`, `*`, `!`, `,`, `>` or `|`.
  Most of those raise, but **`&` does not** — `description: &foo bar` parses as
  an anchor named `foo` with the value `bar`, silently dropping the first word,
  the same invisible damage as ` #`. Backticks around a command name are
  ordinary technical prose (``description: `lexflow init` generates …``), which
  is how this turned up. Rule 5 now detects all of them lexically and `--fix`
  quotes the whole value, indicator included. This had to move into the lexical
  scan rather than stay with the PyYAML backstop: the backstop doesn't run where
  PyYAML is absent — including CI — so the mode was invisible there, and `&` was
  invisible everywhere.

  Also covered, after review of that change: `-` and `?` are indicators only when
  they *open a token* — when the value is just the indicator, or the indicator is
  followed by a space. `description: - handed off to Ana` raises and destroys the
  block exactly like the group above, and the first pass at this mode let it
  through. The test has to be narrower than a plain first-character check, or it
  would fire on `-5% growth`, `--force`, `-> arrow` and `--- separator`, all of
  which are valid plain scalars. A lone `~` stays unflagged on purpose: it is the
  idiomatic YAML null, so `confidence: ~` meaning "unset" is intent, not damage.

- **False positive on a quoted value containing ` #`, with no possible repair.**
  For a non-free-text field the trailing comment was stripped *before* the
  quoting was analyzed, so `resource: "Slack #team-a, #team-b"` — valid YAML —
  was cut mid-string and reported as an unterminated quote. Because the finding
  carried no inferable value, `--fix` could not repair it and the bundle stayed
  red permanently. Quoting is now analyzed first, and comment-stripping only
  ever applies to an **unquoted** scalar, the only place a ` #` can be a YAML
  comment at all.
- **`--fix` refused to repair 34 of 445 real findings.** It recovered the value
  only when the line ended in its own opening quote, which misses the commonest
  shape by far — a quoted title opening a sentence
  (`description: "Search API - Nova Onda" meeting on …`). There the leading
  quote is *content*, not YAML quoting, so the intended value is the whole line.
  The two are distinguished by whether the line ends in its opening quote. A
  never-closed quote is now preserved verbatim rather than guessed away — in
  someone's knowledge base, lossless beats clever.

Measured on that bundle: 442 files / 445 findings / 34 unrepairable before,
441 / 444 / **0** after. The file that disappeared was the false positive.

The wider lesson, worth recording: the beta.5 suite tested the three modes from
the bug report plus shapes I invented. Both defects here came from *real prose* —
a `resource:` listing Slack channels, and meeting titles in quotes. Synthetic
cases validated the logic; only real data found its edges.

[0.1.0-beta.6]: https://github.com/rafapg/elephant-mem/releases/tag/v0.1.0-beta.6

## [0.1.0-beta.5] - 2026-07-30

Fixes a class of silent frontmatter corruption reported against
`0.1.0-beta.2`. Ingestion is model-driven — the `ingest` skill mirrors the
shape of `templates/*.md` — so an unsafe free-text scalar was a matter of when,
not if. Three failure modes followed, and **`validate-okf.py` caught none of
them**: it checked `type:` with a regex and never parsed YAML, so a bundle could
accumulate corrupted files for weeks while every check reported clean. One
reported bundle had 52 of 53 `person` hubs with empty auto-facts blocks and
~140 files with truncated descriptions before anyone noticed.

### Upgrading

Existing bundles will now **fail** `validate-okf.py` where they silently passed.
That is the fix working. To remediate:

```sh
python3 scripts/validate-okf.py --fix   # repairs unsafe scalars in place
python3 scripts/build-index.py          # regenerate hubs, index, manifest
python3 scripts/validate-okf.py         # confirm clean
```

`--fix` preserves the value verbatim, including inner quotes and `#channel`
mentions. Review the diff before committing. Also `pip install pyyaml` if it
isn't present — without it every file takes a lenient fallback parser, which
widens the damage from per-file to bundle-wide.

### Fixed

- **`validate-okf.py` now fails on unsafe frontmatter scalars** (new rule 5),
  reporting the offending line and which of the three modes it is:
  an unquoted value containing `: ` (raises — the whole block is unparsed and
  the entity hub's `## Related facts` regenerates **empty**); an unquoted value
  containing ` #` (parses fine, value **silently truncated** at the hash — no
  exception, nothing in the manifest to grep for); and a quoted value with
  unescaped inner quotes (same as the first, but the value *is* quoted — what a
  model writes once told to quote but not to escape). Detection is purely
  lexical, so it needs no PyYAML and can localize already-quoted lines.
  `--fix` repairs all three in place. This is the fix that holds: the others
  reduce how often the bug fires, but only a check makes it non-silent.
- **Silent degradation in `build-index.py` / `briefing.py`** — a missing PyYAML
  and an unparseable block both switched parsers with no output at all. Both now
  warn on stderr, naming the file. Not a hard failure: the fallback is a
  supported path that CI exercises.
- **The fallback parser no longer mangles quoted values** — it didn't strip
  quotes, so `entities: ['/x.md']` became the literal `"'/x.md'"`, matched no
  entity, and emptied the hub. It now unwraps quotes and undoes `\"` / `\\` /
  `''`, so it reads back what `--fix` writes instead of rendering visible
  backslashes.
- **`assets/templates/entity.md` shipped a broken placeholder** —
  `description: <one sentence: who/what this is>` contains `: `, so every bundle
  created with `elephant-mem:init` already had a file that raises in
  `safe_load` before the user typed anything.

### Changed

- **Templates quote their free-text scalars** (`description`, `title`, plus
  `resource`/`channel`, which routinely carry a colon) and state the escaping
  rule next to them. Telling a model to quote without telling it to escape is
  what converts failure mode 1 into failure mode 3 — one bundle saw exactly
  that: 24 newly-broken files in a single day's catch-up after a
  "quote your descriptions" convention was added.
- **The rule is documented where writers read it** — as an invariant in
  `_shared/core.md` (loaded by `ingest` while it writes frontmatter) and in full
  in `assets/seed/config.md`.
- **CI runs both parser paths** (`pyyaml=[true, false]`). It previously ran only
  the fallback, so the PyYAML path most bundles actually use was never
  exercised. CI also validates the shipped seed bundle, so a seed template
  can't violate the rule it asks users to follow.

### Added

- **`tests/test_frontmatter.py`** — 63 checks covering the three modes, the safe
  shapes that must *not* be flagged (trailing comments on enum fields, quoted
  colons, `(#9-channel)`), template safety, `--fix` fidelity, and the
  end-to-end effect on hub backlinks and manifest descriptions.

Also in this release: **`elephant-wiki` 0.1.0-beta.2** — `wiki.py` reuses
`build-index.py`'s frontmatter parser, so it inherits rule 5's handling; it now
passes the file path in, so an unparseable block names the file instead of
warning about an anonymous `<frontmatter>`. And a third Windows-only test
failure, found because the two fixed in beta.4 had been hiding it: the rule-5
assertions hardcoded `/` separators, while `validate-okf.py` reports positions
via `os.path.relpath`. The validator was correct on Windows; only the test was
OS-naive — and it had never run there, because `tests/test_hooks.py` aborted the
job first. Three Windows failures in a row, each masked by the previous one.

Reported with a full diagnosis and suggested fixes by a plugin user, including
the observation that quoting the templates is necessary but not sufficient.

[0.1.0-beta.5]: https://github.com/rafapg/elephant-mem/releases/tag/v0.1.0-beta.5

## [0.1.0-beta.4] - 2026-07-30

Windows fixes for the `post_ingest` hook path shipped in beta.3. CI's
`smoke (windows-latest)` had regressed while Linux/macOS stayed green.

### Fixed

- **`run-hooks.py` string commands on Windows** — a `hooks.post_ingest` entry
  whose `run` is a **string** was split with `shlex.split(posix=False)` on
  Windows, which keeps the surrounding quotes inside each token, so a quoted
  path became `"…python.exe"` and the hook failed to start (`WinError 2`). Now
  split with POSIX rules on every platform; a string command on Windows should
  use forward-slash paths, or the **list** form (which `--register` writes — so
  the wiki hook was never affected). See
  [docs/configuration.md](docs/configuration.md#field-reference).
- **Test suites on Windows** — `tests/test_hooks.py` and `tests/test_wiki.py`
  print check labels containing non-ASCII (`→`); on Windows's cp1252 console
  `print()` raised `UnicodeEncodeError`. They now force UTF-8 stdio like the
  bundle scripts. CI is green on Linux/macOS/Windows again.

[0.1.0-beta.4]: https://github.com/rafapg/elephant-mem/releases/tag/v0.1.0-beta.4

## [0.1.0-beta.3] - 2026-07-29

Turns elephant-mem into a small platform: ingestion now emits a lifecycle event
that other plugins can subscribe to, instead of reactors having to reach into
the bundle's internals. The first intended subscriber is a human-navigable wiki
generator, shipped separately.

### Added

- **`post_ingest` lifecycle hook** — after a `capture`, `ingest`, or `catch-up`
  cycle commits, the mode fires `scripts/run-hooks.py post_ingest`, which runs
  the subscriber commands declared in `elephant.json`'s `hooks.post_ingest`
  array. Hooks receive `ELEPHANT_BUNDLE` / `ELEPHANT_EVENT` / `ELEPHANT_TRIGGER`
  in their environment and run only after the derived surfaces are regenerated
  and the commit has landed. `hooks` is a map keyed by event name, leaving room
  for future events. See [docs/configuration.md](docs/configuration.md#field-reference).
- **`scripts/run-hooks.py`** — best-effort, isolated runner: a hook that fails,
  times out, or is malformed is logged to `state/hooks.log` and skipped, and one
  failing hook never stops the next — a subscriber can never break an ingestion.
  Pure stdlib. Covered by `tests/test_hooks.py` (19 checks).

### Changed

- **`capture`, `ingest`, `catch-up`** — each now fires the `post_ingest` event as
  the final step after its commit. `catch-up` skips it on an empty window.

[0.1.0-beta.3]: https://github.com/rafapg/elephant-mem/releases/tag/v0.1.0-beta.3

## [0.1.0-beta.2] - 2026-07-20

Context-minimization refactor of the model-invocable read modes: each now runs
its heavy bundle reads and synthesis in a disposable subagent, so the main
agent's context only receives the distilled answer.

### Changed

- **`query`, `briefing`, `start-day`, `end-day`** — each `SKILL.md` is now a thin
  launcher that spawns a subagent and relays its final answer verbatim; the full
  step-by-step procedure moved into a sibling `procedure.md` loaded only inside
  that subagent. `_shared/core.md` and the other shared docs no longer load into
  the main context on every invocation. Behavior (provenance, conversation
  language, whole-field-scan escape hatch, read-only guarantees, end-day's
  interactive capture tail) is preserved. `capture` is unchanged.

### Added

- **`elephant-worker` agent** (`plugin/agents/elephant-worker.md`) — generic
  worker that runs a given `procedure.md` end-to-end in an isolated context
  (default model `sonnet`, overridable per call) and returns only the
  user-facing answer.

[0.1.0-beta.2]: https://github.com/rafapg/elephant-mem/releases/tag/v0.1.0-beta.2

## [0.1.0-beta.1] - 2026-07-19

Public beta — mechanics complete and CI-tested on Linux/macOS/Windows;
promoted to 0.1.0 after cross-platform manual testing of the guided modes.

Initial release. elephant-mem is a personal memory for Claude Code: a private,
local, git-versioned knowledge bundle of durable facts, open loops, and episodic
sources as plain markdown (OKF v0.1), with entity-centric retrieval and optional
automatic ingestion from your work sources.

### Added

- **`init` mode** — guided walkthrough that scaffolds a bundle, writes the machine
  pointer and `elephant.json`, seeds the owner entity, and makes the first commit.
- **Core knowledge modes (zero connectors)** — `query`, `briefing`, `capture`,
  `ingest`, `maintain`, `expand`, `review`, `start-day`, `end-day`.
- **Automatic ingestion (optional, sources-driven)** — `catch-up` (scheduled,
  autonomous forward ingestion over timestamp cursors), `push-start-day` (post the
  morning orientation to Slack or email it via SMTP), and `ingest-audio` (locally
  transcribe a voice recording and ingest it).
- **`update` mode** — check for a newer release and re-sync the bundle's copied
  scripts and templates from the installed plugin.
- **OKF v0.1 bundle format** — three lanes (durable facts / open loops / episodic
  sources), entity-centric retrieval with backlinks, source precedence with fact
  merging, and the snapshot rollup rule.
- **SMTP email delivery** — `push-start-day` can deliver the morning briefing by
  email via any SMTP provider, no MCP connector required; credentials live
  machine-local in the pointer file, separate from the portable bundle config.
- **Scripts** — `build-index.py`, `validate-okf.py`, `rename-entity.py`,
  `briefing.py`, `state.py`, `snapshot-drift.py`, `ingest-audio.py`,
  `send-email.py`.
- **Tested integrations** — Slack, Google Calendar, and Google Drive via claude.ai
  connectors, plus a bring-your-own-MCP-source contract.
- **Documentation** — README, architecture, configuration, and integrations
  guides.

[0.1.0-beta.1]: https://github.com/rafapg/elephant-mem/releases/tag/v0.1.0-beta.1
