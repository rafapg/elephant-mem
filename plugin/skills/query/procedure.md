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
dir. Do not write knowledge (no OKF churn on reads); the one write this mode
does make is the consumption-log line in step 5, into git-ignored `state/`.

**Sharded hubs:** when an entity/source hub's auto-facts block ends with
`→ N older/superseded facts: [archive](...)` (see build-index.py's hub
sharding), that link is a sibling shard holding older/history facts pushed out
of the inline block. Follow it **only** when the question actually asks for
history that isn't in the inline block (e.g. "what did we used to think about
X", "show me everything, including old stuff"); for an ordinary "what do we
know about X" question, the inline block is the current truth and the archive
is out of scope.

5. **Consumption log.** After the answer is finalized, run from `<bundle>`,
   with one `--item` per fact/loop/source file the answer cited and one
   `--entity` per entity it was about:

   ```bash
   python3 scripts/recall.py log --mode query --item <path>… --entity <slug>…
   ```

   See `../_shared/core.md`'s Consumption log section. The script writes the
   line, swallows any failure and always exits 0, so there is nothing to
   handle and nothing to say about it in the answer.

> **Recall escape hatch:** when no entity matches and the `rg` fallback is too
> noisy, don't reach for vectors — use the **whole-field scan** (see
> `../_shared/whole-field-scan.md`). The `manifest.jsonl` triage surface keeps
> recall cheap far past the point where a flat `rg` degrades. A vector index
> only earns its keep once even the manifest no longer fits a subagent's context
> (years out at current growth) — and even then it's a disposable derived
> accelerator over fact `description`+body, never the source of truth;
> `index.md` stays for human navigation.
