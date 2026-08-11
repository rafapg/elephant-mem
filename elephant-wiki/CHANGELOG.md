# Changelog — elephant-wiki

Notable changes to the **`elephant-wiki`** plugin. `elephant-mem` has its own
[CHANGELOG](../CHANGELOG.md); the two plugins version independently, so a gap
between their numbers is expected and is not a sign either one is behind.

`elephant-wiki` carries no git tags of its own — tags and GitHub releases track
`elephant-mem` alone. A version here is dated by the day it landed on `main`,
which is what the marketplace serves.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-beta.3] - 2026-08-11

The wiki grew a local graph, and its generator stopped being one file.

An entity page listed its facts and each fact listed its entities, but nothing
showed the *shape* around a node: to learn that two entities share 399 facts you
had to read 399 cards. Entity and fact pages now carry a **local graph** — the
page's own node at the centre, its neighbours one hop out, drawn on a canvas.
For an entity a neighbour is an entity it co-occurs with in a fact (the fact is
the edge, weighted by how many they share); for a fact it is the entities the
fact names. Hovering names a node, clicking navigates, dragging rearranges.
Source pages get no panel: which facts cite a source lives only in a month
shard, and the panel refuses to load one to find out.

A real bundle is power-law and the first cut ignored it. On the bundle this was
built against, the busiest entity touches 1712 facts and has 329 distinct
neighbours while the median entity has 4, so the panel caps at the 40 heaviest
neighbours — tie-broken by title, because the cap lands mid-tie and the same
page must draw the same graph twice — and says so in its header. The simulation
anneals rather than damps: a 41-node star still jittered at 0.78 px/frame after
3000 frames with plain damping, so every busy page burned its frame cap and
stopped mid-wobble. It settles at 141 frames now, and small pages at 33.

Two things only showed up in a browser, not in a harness. With no labels the
graph was decorative — forty anonymous dots you had to hover one at a time — so
labels stand while the graph is small and go hover-only once it is dense. And
the star sat at 0.6 of its rest length because neighbours were pulled to the
centre as well as sprung to it; only the centre is pulled now, and the radius is
derived from the panel's real vertical budget instead of a guessed ratio.

### Added

- **A local graph panel** on entity and fact pages, capped at the 40 neighbours
  with the most shared facts, with standing labels while the graph is small and
  hover-only labels once it is dense. Click navigates through the app's own
  router; drag rearranges without navigating.

### Changed

- **The generator ships as `wiki.py` plus the `wiki.js` / `graph.js` assets it
  inlines**, instead of a single Python string with the whole app pasted into
  it. They are inlined as two separate `<script>` blocks: one block would have
  meant a typo in the graph blanking the whole wiki instead of costing only the
  panel. `--register` carries all three into `<bundle>/scripts/`.
- **A build run from the plugin refreshes an already-registered bundle's
  in-bundle copy.** Without it, the first `post_ingest` after an upgrade would
  quietly regenerate the page with the old generator, exit 0, and say nothing —
  so a new feature would appear once, then vanish on the next ingestion.

### Fixed

- **A link in a bundle body could carry a script.** Bodies are third-party text
  — Slack messages, transcripts, forwarded documents — and the rendered HTML
  goes into `innerHTML` on a page holding the whole knowledge base, so
  `[x](javascript:…)` was a click away from running there. Only `http`, `https`,
  `mailto`, rewritten hash routes, and scheme-less relative paths keep their
  `href` now; anything else renders as inert text. The scheme is read the way a
  browser reads it, with whitespace and control characters stripped, so
  `java&#9;script:` does not slip past.
- **A drag whose `mouseup` was lost outside the window** left the node stuck to
  the cursor and the frame loop running indefinitely — measured at 3000 frames
  with a frame still pending, against ≤141 for any settled page. It now ends on
  the first button-less pointer move or on window blur.
- **The assets are read before any output is written**, so a stale install fails
  with a message naming the missing file instead of leaving a fresh `data/`
  beside a stale `wiki.html`.

## [0.1.0-beta.2] - 2026-07-30

`wiki.py` reuses `build-index.py`'s frontmatter parser, so it inherits the
bundle's own parsing rules, and it passes the file path in — an unparseable
block now names the file instead of warning about an anonymous `<frontmatter>`.

Shipped with `elephant-mem` 0.1.0-beta.5; see
[that section](../CHANGELOG.md#010-beta5---2026-07-30) for the full context.

## [0.1.0-beta.1] - 2026-07-29

First release: a local, zero-server static wiki generated from a bundle's
`knowledge/`, and the first subscriber to `elephant-mem`'s `post_ingest`
lifecycle hook, so it stays current without a manual step.

Shipped alongside `elephant-mem` 0.1.0-beta.3; see
[that section](../CHANGELOG.md#010-beta3---2026-07-29) for the hook itself.
