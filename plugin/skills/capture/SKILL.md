---
name: capture
description: >
  Capture a decision/fact stated in the current conversation into elephant-mem.
  Use when the user reaches a durable decision (architecture choice,
  product/tradeoff call, process decision, a commitment with follow-up) while
  working in Claude Code — offer once, then proceed only on accept. Captures
  the what AND the why.
---

# elephant-mem:capture

A lightweight `ingest` whose source is the **current conversation**.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>` and `elephant.json`). It touches entities — also load
`../_shared/entity-resolution.md`.

## Procedure

A lightweight `ingest` whose source is the **current conversation**, not an
external feed — for a decision/fact stated to Claude Code while working on
something else (a dev task, or just using Claude Code to think a process
through). Default autonomous; same machinery as `ingest`, but:

1. **Provenance.** Create
   `knowledge/sources/<YYYY-MM>/<YYYY-MM-DD>-capture-<slug>.md` from
   `templates/source.md` with `source-kind: manual`, `channel:
   claude-code:<workspace>` (the working dir's basename; bare `claude-code` if
   none), `occurred: <today>`, and a one-line summary of what was decided **and
   why**. No `raw/`.
2. **Extract & route.** Usually one durable `fact` (a decision) — plus an
   `open-loop` when it implies follow-up. Same skip-rules; a decision that merely
   restates an existing fact MERGEs (bump `times_referenced`), never duplicates.
3. **Resolve entities, dedup, persist** as `ingest`: write the fact(s), then
   `build-index` → `validate` → local commit. After the commit lands, fire the
   lifecycle event: `python3 scripts/run-hooks.py post_ingest --trigger capture`.
   Best-effort — this is where subscribers (e.g. the wiki generator) regenerate;
   a hook failure never affects the capture.
4. Recap in the bundle's `conversation_language`: what was filed, where, any
   open-loop opened.

The user is the source, so treat the claim as `confidence: high` unless they
hedge. The **rationale is signal** — capture the why, not just the what.
