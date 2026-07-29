---
name: build
description: >
  Generate (and optionally auto-maintain) a human-navigable wiki from an
  elephant-mem bundle. Use when the user wants to browse their memory as a
  local website — "build the wiki", "open my knowledge as a wiki", "make the
  bundle navigable" — or to wire the wiki to regenerate automatically after
  every ingestion. Produces a local, zero-server static site; nothing leaves
  disk.
---

# elephant-wiki:build

Renders the bundle's markdown (entities, facts, sources) into a local,
single-page **wiki** under `<bundle>/wiki-out/`. You open `wiki-out/wiki.html`
directly in a browser — no server, no port. Data loads via `<script src>` (never
`fetch`), so it works straight off `file://`; heavy fact/source bodies are
sharded by month and loaded lazily, so it stays fast on a large bundle.

The wiki is a **derived, read-only** view — like the bundle's own
`manifest.jsonl`. The markdown stays the single source of truth; the wiki never
mutates it. `wiki-out/` is git-ignored.

## Procedure

The generator is `assets/scripts/wiki.py` (pure stdlib; it reuses the bundle's
own `scripts/build-index.py` frontmatter parser). It resolves the bundle from
the machine pointer `~/.config/elephant-mem/config.json` (override with
`--bundle`).

1. **Locate the generator.** Prefer the bundle's own copy if present
   (`<bundle>/scripts/wiki.py`, written by `--register`); otherwise use this
   plugin's `${CLAUDE_PLUGIN_ROOT}/assets/scripts/wiki.py`.

2. **Build once** — regenerate the wiki from the current bundle:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/wiki.py" build
   ```

   Then tell the user the path it printed and how to open it (e.g. `open
   <bundle>/wiki-out/wiki.html` on macOS, or just double-click it).

3. **Register for auto-refresh** (opt-in) — subscribe the wiki to the bundle's
   `post_ingest` event so it regenerates after every `capture` / `ingest` /
   `catch-up`, with no manual step:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/wiki.py" build --register
   ```

   `--register` copies the generator into `<bundle>/scripts/wiki.py` (so the
   hook is self-contained and survives plugin updates), adds a `wiki` entry to
   `hooks.post_ingest` in `elephant.json`, git-ignores `wiki-out/`, and builds
   immediately. Requires the `elephant-mem` plugin's `post_ingest` hook support
   (v0.1.0-beta.3+). Use `--unregister` to remove the subscription.

## Notes

- **Read-only over `knowledge/`.** Only `--register`/`--unregister` write, and
  only to `elephant.json` and `.gitignore`.
- **Scope.** Renders entities, facts, and sources with entity-centric
  navigation, backlinks, relations (supersedes/contradicts/derived-from),
  confidence/status badges, and client-side search/filter. Open loops are out
  of scope by design.
- **Private.** The wiki can contain everything the bundle does. It lives on disk
  under `wiki-out/` and is never published. Never serve it on a public interface.
