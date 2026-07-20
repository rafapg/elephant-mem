# `query` procedure

Load `../_shared/core.md` first (always). This file is the `query` procedure.
For entity work, also load `../_shared/entity-resolution.md`. Obey **Retrieval
trust** in `../_shared/core.md`. The recall escape hatch is the **whole-field
scan** — see `../_shared/whole-field-scan.md`.

Read-only, entity-centric retrieval from the elephant-mem knowledge bundle.

Read-only, **entity-centric** (this is what keeps retrieval cheap as `facts/`
grows huge). (1) Read the thin `<bundle>/knowledge/index.md` router and
`<bundle>/knowledge/entities/index.md` catalog. (2) Map the question to
entities/tags; open those entity hubs and follow their backlinks to the
relevant facts. Use `rg` over `knowledge/facts` only as a fallback when no
entity matches. (3) Load the bodies of only those facts. (4) Answer in the
bundle's `conversation_language` (from `elephant.json`) **with provenance** —
cite the fact files and their `sources`. Never enumerate the whole `facts/`
dir. Do not write anything (no churn on reads).

> **Recall escape hatch:** when no entity matches and the `rg` fallback is too
> noisy, don't reach for vectors — use the **whole-field scan** (see
> `../_shared/whole-field-scan.md`). The `manifest.jsonl` triage surface keeps
> recall cheap far past the point where a flat `rg` degrades. A vector index
> only earns its keep once even the manifest no longer fits a subagent's context
> (years out at current growth) — and even then it's a disposable derived
> accelerator over fact `description`+body, never the source of truth;
> `index.md` stays for human navigation.
