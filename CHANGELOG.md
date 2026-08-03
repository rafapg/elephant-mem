# Changelog

All notable changes to elephant-mem are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-beta.7] - 2026-08-01

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
