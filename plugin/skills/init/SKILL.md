---
name: init
disable-model-invocation: true
description: >
  Create and register a new elephant-mem knowledge bundle — a guided,
  conversational first-run walkthrough. Scaffolds the OKF markdown bundle, writes
  the machine pointer and elephant.json, seeds the owner entity, and does the
  first git commit. Invoke only when the user explicitly asks (elephant-mem:init);
  this is the project's front door. Safe to re-run to add/repair pieces.
---

# elephant-mem:init

A guided walkthrough that stands up a working elephant-mem bundle from nothing.
Run it conversationally: explain each stage briefly, use the **AskUserQuestion**
tool for every choice, and confirm before any write outside the new bundle
directory (the pointer file and — optionally — the user's `~/.claude/CLAUDE.md`).

**Load `../_shared/core.md` first** (the shared contract). Note the twist: core's
"find the bundle" protocol assumes a bundle already exists — `init` is the mode
that *creates* it, so a missing pointer / `elephant.json` here is the expected
starting state, not an error to send the user back with.

## What this produces

- A **bundle directory** (default `~/elephant`) holding `knowledge/`, `state/`,
  `scripts/`, `templates/`, `config.md`, `elephant.json`, `vocab.json`,
  `.gitignore`, `README.md` — a self-contained, git-versioned OKF bundle.
  `vocab.json` is the controlled vocabulary every script prefers over its own
  hard-coded default; `update` never re-syncs it, since it is yours to extend.
- The machine **pointer** `~/.config/elephant-mem/config.json` → `bundle_path`,
  so every other mode can find the bundle.
- The **owner entity** plus a few clearly-marked example items, an initial
  `build-index` + `validate` pass, and the first local commit.
- Optionally: a `sources` block for automatic ingestion, and a global-awareness
  line in `~/.claude/CLAUDE.md`.

## Run it

The full stage-by-stage walkthrough is in [`procedure.md`](procedure.md) — open
it and follow it in order. It is designed to be idempotent: if a piece already
exists (a pointer, a bundle, the owner entity), show what's there and ask before
overwriting rather than clobbering it.
