# `maintain`

Load `../_shared/core.md` first (always). This file is the `maintain` procedure.
It touches entities — also load `../_shared/entity-resolution.md`.

Safety net for autonomous ingestion. Review recent `log.md` and all flags:
- resolve `**Conflict**` entries (choose a winner → `supersedes` /
  `superseded-by` + `status: superseded`, or document the contradiction);
- consolidate `consolidate-candidate` facts;
- **decay** (relevance-weighted): old + unreferenced + `low` confidence → lower
  confidence or `status: deprecated` (never delete — git keeps history). Facts
  **far from the owner's orbit** (no link to the owner / their team / their
  projects) that stay unreferenced decay **faster** — relevance is a retention
  criterion here, never a capture one. Decisions, launches, and cross-team
  signals resist decay even when distant.
- **promote**: a fact recurring across many sources/entities → curated concept;
- **snapshots** (`tags: snapshot`, the hand-written editorial rollups): do NOT
  decay these as orphans even when unreferenced — they encode judgment, not
  signal volume. Instead **drift-check** them: run `scripts/snapshot-drift.py`,
  which flags any snapshot whose facts became newer than its `updated` (last-tended)
  date via a `relates-to` link (in EITHER direction — the snapshot lists the fact, or
  the newer fact lists the snapshot) or ≥2 shared entities. Output is bucketed:
  **`relates-to` (high-signal) first, `shared-entities` (noisier) after** — but scan
  the shared-entities tail too (genuine deltas often arrive as new unlinked facts
  caught only by entity overlap; do not skip it). For each drifted snapshot,
  queue a line to `state/needs-review.md` (`snapshot <path> may have drifted —
  re-tend or archive`); the owner then re-tends it (merge the newer nuance, add the
  drifting facts to the snapshot's `relates-to` so the next check flags them in the
  high-signal bucket, bump `updated`) or, when a finer fact clearly **supersedes** part of it,
  deprecate-and-archive it (`status: deprecated`, keep for provenance) rather
  than let it rot silently. This is the periodic-review ritual, automated as a
  *surfacing* — never an auto-rewrite.
- **entity hubs** (`type: entity`, not `status: deprecated`): do NOT decay these as
  orphans — they are authoritative knowledge summaries. Instead **drift-check** them:
  run `scripts/entity-drift.py`, which flags any hub whose `description` (hand-written
  prose above the auto-facts block) has fallen behind the newest fact that names it
  (via the fact's `entities:` backlink). Candidates are ranked by count of newer facts
  (worst offenders first), then by date gap, then by path. Output is capped at
  `entity_drift_max` (elephant.json, default 25). Queue nothing — this is drift-finding,
  not review-queuing. Overwrite `state/entity-drift.md` wholesale with the ranked,
  capped list (one line per candidate: path, hub's `updated`, count of newer facts, and
  newest fact's date), or with "no stale hubs" if zero candidates found — not a log,
  a current truth snapshot. Include `state/entity-drift.md` in the run's commit. For each
  candidate in the output, consider whether the description's **content** is now wrong
  (a fact has arrived that changes the context), and if so, re-tend it (merge the newer
  nuance, bump `updated`) or, if outdated but not wrong, simply bump the date. This is
  advisory only — never auto-rewrite.
- flag **orphans** (no entities, no links) for review.
- **reconcile the review queue** (tag↔queue invariant): every file with the
  `needs-review` tag must appear in `state/needs-review.md`, and vice-versa.
  Find desyncs (`grep -rl '^tags:.*needs-review' knowledge/` vs the queue) and
  fix them — re-queue tagged-but-unqueued items; drop the tag from items already
  resolved/removed from the queue. This catches orphans the autonomous runs left.
Then rebuild, validate, log a `**Maintenance**` entry, and commit.
