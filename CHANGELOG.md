# Changelog

All notable changes to elephant-mem are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
