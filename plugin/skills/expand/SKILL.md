---
name: expand
disable-model-invocation: true
description: >
  Synthesis loop over elephant-mem — propose derived facts, relations,
  contradictions, and promotions (generative, flagged for confirmation before
  writing). An explicit, deliberate operation; invoke only when the user asks
  (elephant-mem:expand).
---

# elephant-mem:expand

Synthesis loop — generative, so proposals are flagged for confirmation.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`). It touches entities — also load
`../_shared/entity-resolution.md`. For cross-entity correlation where the
connecting facts aren't linked to any entity you'd think to open, use the
**whole-field scan** (see `../_shared/whole-field-scan.md`).

## Procedure

Synthesis loop. Pick a cluster (by entity, tag, or recent activity). Propose:
new **derived facts** (inferences resting on ≥2 existing facts), new
**relations** (`relates-to` / `derived-from`), detected **contradictions**, and
**promotion** candidates (recurring patterns → a curated `concept` entity).
Because this is generative, **present proposals flagged for confirmation** —
do not persist blindly. On confirm, write derived facts with
`relations.derived-from` pointing to their parents, `confidence: low|medium`,
and tag `synthesized`.
