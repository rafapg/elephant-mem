# whole-field scan  (the recall escape hatch)   (obey **Retrieval trust** in `core.md`)

Load `core.md` first (always). This file is the `whole-field scan` procedure —
a **shared retrieval technique** referenced by `query`, `briefing`, and `expand`
as their recall escape hatch, not a standalone mode. Obey **Retrieval trust** in
`core.md`.

Read-only, **whole-field** — complements entity-first `query` and time-first
`briefing`. Not a default: reach for it only when neither has a good entry point.
Its sweet spot is open-ended discovery ("is there *anything* about X?"),
exhaustive sweeps ("everything that touches Y", "what am I forgetting about Z"),
and cross-entity correlation (`expand`) where the connecting facts aren't linked
to any entity you'd think to open. It is the antidote to entity-first's blind
spot — it finds what isn't where you looked.

**Delegate to a subagent — never load it into the main context.** The
subagent filters the manifest, triages the filtered lines against the question
(weighting by `confidence`/`status` per **Retrieval trust** above), deep-reads
only the chosen `path`s, and returns the distilled answer **with provenance** —
the triage stays isolated in the subagent, never polluting the main
conversation's budget.

**The manifest is never loaded whole, not even by the subagent.**
`knowledge/manifest.jsonl` carries one compact line per active fact and open
loop (`path`, `type`, `desc`, `entities`, `tags`, `occurred`, `confidence`,
`status`), and a mature bundle's runs to millions of bytes: 7,818 rows and
4.8 MB, ~1.2 million tokens, on the bundle that set this rule. That no longer
fits any context. So **pre-filtering is mandatory**, in this order:

1. **`scripts/search.py` first.** Its filters (`--entity`, `--tag`, `--text`,
   `--since`/`--until`, `--status`) and the facets in its footer (co-occurring
   entities, months, tags of the whole matched set) narrow the field, one page
   of 32 KB at a time. Use the facets to choose the next filter rather than
   paging down an unfiltered list.
2. **`rg` over the manifest** for an axis the search lacks (a `confidence`
   value, a word in `entities` or `owner` the roster does not resolve, a
   regular expression): `rg '"confidence":"low"' knowledge/manifest.jsonl`,
   combined with a second `rg` to narrow further. Count before you read
   (`rg -c`), and narrow again when the count is in the hundreds.
3. **Triage the filtered lines only**, then deep-read the chosen `path`s.

Regenerated every build, so always fresh — no bodies, no embeddings.

**Consumption log.** The scan logs its own line, under its own mode name, once
its distilled answer is settled and before it returns. The subagent that ran it
makes the call, in the context that knows what was cited:

```bash
python3 scripts/recall.py log --mode whole-field --item <path>… --entity <slug>… \
  --question "<the question, verbatim>" --pages <search pages read> \
  --bytes <bytes read> --level <level>…
```

See `core.md`'s Consumption log section. One `--item` per path the scan
deep-read and actually used, one `--entity` per entity the answer was about;
the triaged-away manifest lines are not citations. The read-cost flags are the
same as `query`'s (see its procedure): `--bytes` adds every `search.py`
`bytes:` line, the size of each `rg` output and of each body read; `--level`
names each level used (`search`, `facts-rg`, `body`, `whole-field`).

This line is the scan's, not the caller's: `query` and `briefing` still log
theirs for what their own final answer cited, and `expand` logs nothing, so a scan run for `expand` is still
recorded here. The script swallows any failure and always exits 0, and nothing
about it belongs in what the subagent returns.
