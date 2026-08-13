# Changelog — elephant-wiki

Notable changes to the **`elephant-wiki`** plugin. `elephant-mem` has its own
[CHANGELOG](../CHANGELOG.md); the two plugins version independently, so a gap
between their numbers is expected and is not a sign either one is behind.

`elephant-wiki` has its own tag namespace, `wiki-v0.1.0-beta.N`, starting at
`wiki-v0.1.0-beta.4`; plain `v0.1.0-beta.N` tags are `elephant-mem`'s. Versions
before beta.4 were never tagged and are dated by the day they landed on `main`,
which is what the marketplace serves — nothing machine-reads a wiki tag, so it
is a record rather than a delivery mechanism.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-beta.4] - 2026-08-13

The page looked amateurish for reasons that turned out to be nameable, and two
of them were rendering bugs rather than taste.

Every link was the accent brown, and a fact card is a link, so a busy entity
page was 492 brown paragraphs with no hierarchy: a fact's own sentence carried
the same visual weight as a person's name in a list. There was no dark mode at
all. Navigation existed only on the home page — every detail page dropped the
sidebar, floated a 960px column in a 1728px window and offered a grey `← back`
as the only way to orient. The type scale barely separated its levels (h1 24px
against a 15px body), and every fact sat in its own bordered rounded box,
stacked 492 deep.

The wiki is now a three-pane workspace, in the shape the Obsidian app uses: a
persistent explorer on the left, a reading column in the middle, the local graph
and linked mentions on the right. Colour comes from one warm-neutral ramp with a
semantic layer over it, so a theme is a swap of about fifteen values rather
than a second stylesheet. Body text is ink, and the accent is rationed to the
seven places where it means something.

Two of the defects were in the markdown renderer, and they were the larger part
of why prose looked ragged. Paragraph lines were joined with `<br>`, so a body
hard-wrapped at 72 columns kept that wrap forever — breaking at ~490px inside a
1130px column no matter how wide the window was. And a wrapped list item's
continuation lines fell out of the list loop and were emitted as their own
paragraph *after* the closing `</ul>`, so a hard-wrapped list rendered as
alternating bullets and orphaned half-sentences.

Shown on a 32-inch 4K display the result drew a second round of complaints, and
each one turned out to have a measurement behind it rather than a preference.

The shell was built from two fixed rails around a fixed centred measure, which
leaves the surplus exactly one destination. At the 3200×1800 the display
actually reports, 935px of empty pane sat on each side of the article and the
graph — the part of the page its owner liked most — was 286px, 8.9% of the
screen, separated from the text it annotates by 949px of nothing. The rails are
fluid now, and above 2400px the article stops being the flexible track and the
graph column becomes it: at 3200px the canvas is 1472×1104, **46% of the
viewport against 8.9%, with the pane gutter at exactly zero**, and what the
canvas does not take becomes canvas margin rather than empty pane.

Light mode read yellow for a reason that is arithmetic. The old surface ramp
carried a red-minus-blue split climbing to +22, and the ink was warm too — warm
text on warm paper is what newsprint is. The surfaces now hold +3 to +7 and the
ink is cool at −6 to −8, while the accent moves the other way: `#8d4002`
carries eighteen times the ramp's chroma and appears in seven places instead of
fourteen. That is the split that makes one colour read as a decision rather
than as a theme.

The typography was weak because it barely differentiated. Seven sizes lived
inside a 4.5px band, and six declarations of `font-weight:650` resolve to plain
Bold wherever the system font is not variable — so page titles, section heads,
badges and the wordmark all rendered at one identical weight, and there was no
weight hierarchy above 400 anywhere in the sheet. Worse, `--faint` carried all
543 explorer counts and every date at **2.65:1**, well under the 4.5:1 floor.
The scale is now seven steps across 19.5px with real weights, and the token
that invited faint text no longer exists.

### Added

- **A three-pane shell.** The explorer is present on every view, with
  collapsible kind groups (chevron toggles, the row opens the kind's page),
  counts in tabular figures, and the active entity's group auto-expanded and
  scrolled into view. Group headers stick to the top of the tree while their
  own entities scroll under them.
- **Light and dark themes**, resolved before first paint by an inline script in
  `<head>` — deferring it to the app script gave a dark-mode reader a full white
  flash on every load. Follows the OS on first visit, remembers the choice after.
- **Hover previews** on entity, fact and source links, on the data `core.js`
  already holds, so hovering a list of 300 facts never loads a shard. One
  delegated listener pair rather than 300. A row's own title is excluded: the row
  already shows the whole description, and previewing it put a floating copy of
  the sentence on top of the sentence.
- **An expandable graph.** The rail draws the heaviest neighbours its width can
  carry — eighteen on a laptop, all forty from 2400px up — and `⤢` opens the
  full forty in a sheet larger than the rail canvas at any viewport. There is
  still only one simulation: expanding hands it over, closing hands it back.
- **Linked mentions** beside the graph — the same model the canvas draws, as an
  ordered list of who this page shares facts with and how many, so the two can
  never disagree.
- **Clickable tags** (they were inert text) and **keyboard search**: `/` or
  `⌘K`/`Ctrl-K` focuses the box, `Esc` clears it.
- **Breadcrumbs** in place of the `← back` link.
- **A ledger spine.** Above 1400px a fact row is two columns — the sentence in a
  66-to-72-character measure, its apparatus (date, entities, tags, confidence)
  hanging in a margin column — divided by one continuous hairline running the
  whole list, in place of 492 full-width horizontal rules. The first track is a
  fixed length rather than `minmax(0,…)`: every `.item` is its own grid
  container, so a content-sized track resolves per row and the "continuous" line
  would miss most of them. It is gated at 1400px so a 1440px laptop gets it.
- **A per-kind lightness axis in the graph.** Simulating deuteranopia and
  protanopia over the nine node hues at a matched lightness collapses
  person/team/org and tool/concept/repo to a worst-pair distance below any
  just-noticeable difference. Hue is the channel dichromacy destroys; lightness
  is the one it leaves. Every hue is unchanged and the collapsing clusters are
  separated by lightness instead, which moves the worst pair out by 3.2×.

### Changed

- **A semantic token system** (`--b00`..`--b100` plus `--text`/`--muted`/
  `--line`/`--accent`) replaces eight hand-picked browns. The canvas cannot read
  a CSS variable, so `graph.js` resolves the palette off the root element and
  re-reads it when the theme flips; a test now asserts every token it reads is
  actually declared, since a renamed variable would otherwise leave the graph
  drawn in the light palette on a dark page.
- **Facts and sources are rows, not cards** — hairline separated with a hover
  surface, the whole row clickable.
- **A real type scale**: seven steps across a 19.5px band, 30px page titles with
  tight tracking, and section heads as larger lowercase ink with a rule.
- **`person` moved off the accent's hue** in the graph. This bundle is
  person-heavy, and tinting the commonest kind the same warm tone as the accent
  made every graph read as one colour and as if every node were selected.
- **The centred fact is a neutral diamond** rather than a full-contrast mark: at
  `--text` it was the heaviest thing on a canvas of pastels and read as a hole.
- **Standing labels are placed outward from the centre.** With forty labels all
  sitting under their node, every label on the top of the ring landed inside the
  ring.
- **The right rail collapses** on views that have no graph and no mentions, which
  otherwise reserved 286px of empty tinted column that read as a panel that had
  failed to load.
- **The rails are fluid and the graph takes the surplus.** Both rails are
  `clamp()` tracks, and above 2400px the article is fixed while the graph column
  flexes. The node cap follows: 18 at 1440px, 29 at 1920px, and the full 40 —
  with every node labelled — at 2400px and beyond, derived from
  `window.innerWidth` rather than a box's `clientWidth`, which reads 0 while the
  rail is `display:none` and would pin every graph to 18 nodes.
- **Uppercase means one thing.** It was the only hierarchy device in play,
  applied to five structurally unrelated roles with nothing else varying between
  them. Section heads are now larger, heavier lowercase ink with a rule; the
  confidence badge is the only uppercase on the page, and a test enforces it.
- **Dates and counts leave the monospace.** `tabular-nums` gives the same
  alignment guarantee without a second typeface, and lifts them from `--faint`
  at 2.65:1 to `--muted` at 5.77:1. Nothing on this page is code.
- **`--faint` is retired for `--ghost`**, which is declared for non-text marks
  only. A name that says "faint text" invites text reuse; the constraint is the
  name, and it outlives a review convention.
- **The graph is embedded, not framed.** The canvas paints straight onto the
  rail with no fill or border, edges move to a token with 2.26:1 against the
  page rather than a 1.39:1 UI hairline, and hovering a node drops everything
  else to a third — a 40-node star becomes a readable one-hop query.

### Fixed

- **A hard-wrapped paragraph now reflows.** Markdown's soft line break is not a
  line break; only two trailing spaces still force one, which is why the check
  runs before the strip that would erase it.
- **A wrapped list item stays inside its `<li>`**, per CommonMark's lazy
  continuation, instead of escaping as a paragraph after the list.
- **The graph is centred in a rail it shares.** Under 1180px the panel shares a
  flex line with the mentions block, and the canvas was measured while its
  sibling was still empty — so it was handed the whole band and stayed seeded for
  a box that no longer existed. Mentions is filled first now, and a
  `ResizeObserver` re-measures from the element so the layout no longer depends
  on when the caller happened to call.
- **The phone layout.** A media query adds no specificity, so the responsive
  block sat above the base rules it meant to override and lost to them: the rail
  stayed a centred column, and an open group of 184 orgs pushed the article three
  screens down. The responsive blocks are last in the sheet now, the tree keeps
  its own bounded scroll, and a test asserts the ordering.
- **The reading pane keeps its height** at intermediate widths. With the default
  `1fr` grid rows the graph band took half the viewport and left the article with
  four visible lines.
- **The accent no longer lightens on hover in light mode.** Storing it as HSL
  components made a single `--accent-lift` serve both themes by raising
  lightness — which lowers contrast on a light ground, to 4.51:1, under AA. It
  is a literal per theme now: darker on light, lighter on dark. The modal scrim
  was tinted with the accent's hue for the same reason and is neutral.
- **A line was 96 characters, not the 72 it was specified as.** The CSS `ch`
  unit is the advance of "0" (9.45px in this stack), not the average character
  (7.08px), so a measure set in `ch` ran a third wider than intended and past
  every guideline the design cites. Measured against the real corpus and reset;
  it is 67 to 74 characters at every width now.
- **Expanding the graph made it smaller.** The sheet was a fixed 1400×920 while
  the rail canvas had grown to 1472×1104, so on the display the feature exists
  for, `⤢` shrank the thing it expands. The sheet is viewport-relative and now
  opens at just over twice the rail canvas's area.
- **The apparatus column no longer sets the row height.** Stacking each of up to
  eight tags on its own line ran a metadata column nine lines deep beside a
  three-line sentence; it wraps as rows inside its own width instead.
- **Linked mentions is a list, not a canvas.** It inherited the canvas's width,
  so at 3200px each count sat some 1300px from the name it belongs to.

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
