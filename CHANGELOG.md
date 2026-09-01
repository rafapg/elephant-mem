# Changelog

All notable changes to elephant-mem are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
