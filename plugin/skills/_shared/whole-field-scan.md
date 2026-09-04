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

**Delegate to a subagent — never load it into the main context.** A mature
`knowledge/manifest.jsonl` can run tens of thousands of tokens (one compact
line per active fact + open loop: `path`, `type`, `desc`, `entities`, `tags`,
`occurred`, `confidence`, `status`). The subagent loads it, triages against the
question (weighting by `confidence`/`status` per **Retrieval trust** above),
deep-reads only the chosen `path`s, and returns the distilled answer **with
provenance** — the manifest stays isolated in the subagent, never polluting
the main conversation's budget.

Because it's JSONL it degrades gracefully: pre-filter with `rg` (e.g.
`rg '"strategy"' knowledge/manifest.jsonl`) to load only matching lines when an
axis exists, or load the whole file when it doesn't. Regenerated every build, so
always fresh — no bodies, no embeddings.

**Consumption log.** The scan logs its own line, under its own mode name, once
its distilled answer is settled and before it returns. The subagent that ran it
makes the call, in the context that knows what was cited:

```bash
python3 scripts/recall.py log --mode whole-field --item <path>… --entity <slug>…
```

See `core.md`'s Consumption log section. One `--item` per path the scan
deep-read and actually used, one `--entity` per entity the answer was about;
the triaged-away manifest lines are not citations. This line is the scan's, not
the caller's: `query` and `briefing` still log theirs for what their own final
answer cited, and `expand` logs nothing, so a scan run for `expand` is still
recorded here. The script swallows any failure and always exits 0, and nothing
about it belongs in what the subagent returns.
