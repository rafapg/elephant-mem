# Changelog

All notable changes to elephant-mem are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
