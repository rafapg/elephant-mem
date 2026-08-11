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
own `scripts/build-index.py` frontmatter parser), plus sibling JS assets it
inlines at build time — `wiki.js` (the SPA) and `graph.js` (the local
knowledge-graph view). It resolves the bundle from the machine pointer
`~/.config/elephant-mem/config.json` (override with `--bundle`).

1. **Use the plugin's generator.** For a manual build, always run this
   plugin's `${CLAUDE_PLUGIN_ROOT}/assets/scripts/wiki.py` — never
   `<bundle>/scripts/wiki.py`. That in-bundle copy (written by `--register`)
   exists only to keep the `post_ingest` hook self-contained; it can lag the
   plugin's own copy, and running it directly can run stale, already-fixed
   code.

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

   `--register` copies the generator AND its sibling JS assets (`wiki.js`,
   `graph.js`) into `<bundle>/scripts/` (so the hook is self-contained and
   survives plugin updates), adds a `wiki` entry to `hooks.post_ingest` in
   `elephant.json`, git-ignores `wiki-out/`, and builds immediately. Requires
   the `elephant-mem` plugin's `post_ingest` hook support (v0.1.0-beta.3+). Use
   `--unregister` to remove the subscription.

   An already-registered bundle self-heals: any plain build in step 2, run
   from the plugin's own copy, detects the `wiki` subscriber in `elephant.json`
   and refreshes `<bundle>/scripts/` (the `wiki.py` plus `wiki.js` /
   `graph.js`) before building, so the hook never keeps running a stale copy.

## Notes

- **Read-only over `knowledge/`.** Only `--register`/`--unregister` write, and
  only to `elephant.json` and `.gitignore`.
- **Scope.** Renders entities, facts, and sources with entity-centric
  navigation, backlinks, relations (supersedes/contradicts/derived-from),
  confidence/status badges, and client-side search/filter. Open loops are out
  of scope by design.
- **Private.** The wiki can contain everything the bundle does. It lives on disk
  under `wiki-out/` and is never published. Never serve it on a public interface.
