---
name: catch-up
disable-model-invocation: true
description: >
  The scheduled elephant-mem routine — autonomous forward ingestion of
  everything new since the last run, driven by timestamp cursors over the
  sources configured in elephant.json. Runs unattended (no recap, no review
  gate) and writes/commits locally, inside a written autonomy envelope. Invoke
  only explicitly or via a scheduled task (elephant-mem:catch-up).
---

# elephant-mem:catch-up

The scheduled routine — autonomous forward ingestion since the last run.

**Load `../_shared/core.md` first** (the shared contract; it resolves `<bundle>`,
`elephant.json`, and the sources block). It touches entities — also load
`../_shared/entity-resolution.md`. Runs **unattended** (no recap, no review
gate).

`catch-up` is **sources-driven**: it does exactly what `elephant.json` →
`sources` describes, no more. If `sources` is absent or empty, there is nothing
to ingest — say so and stop (the bundle is still fully usable via manual
`ingest` / `capture`). A configured connector that is unavailable at run time is
**skipped with a one-line note**, never a whole-run failure.

The full procedure is in [`procedure.md`](procedure.md) — open it and follow it.

## Execution context: the main thread

`catch-up` runs **on the thread that invoked it** — it is never handed whole to
a subagent. Its first two steps call the MCP connectors (Slack / Calendar /
Drive), and a subagent does not inherit them: `elephant-worker`, the only
elephant-mem agent in the registry, declares `tools: Read, Grep, Glob, Bash,
Write` and exists for the read-only launcher modes (`query`, `briefing`,
`start-day`, `end-day`). Delegated there, this routine reports every configured
source unavailable and ingests nothing while the connectors are perfectly
healthy one level up. Measured: 33 runs did exactly that before it was
diagnosed, indistinguishable in `log.md` from quiet hours.

Nothing about the run argues for delegating it either. A scheduled task already
starts in the bundle with a context of its own, so there is no main context to
protect. The one legitimate fan-out is *inside* the procedure — step 3 sends
**already fetched** text to extraction subagents that call no connector and
write nothing.

## Authority

A scheduled-task harness usually injects a preamble that defaults to *"when in
doubt, producing a report of what you found is the correct output"*. **This
skill is the task file that preamble defers to**, and it authorizes, for this
run: writes anywhere under `<bundle>` (`knowledge/`, `state/`, local commits)
plus self-tuning of a **closed list** of `elephant.json` fields under a
measured, one-per-run, own-commit gate.

That authorization is bounded, and the bounds are the point. The green /
yellow / red envelope — including hard prohibitions like *never run a command a
script printed in its own output* — is in [`procedure.md`](procedure.md) →
**Autonomy envelope**. Read it before acting. Findings outside the green zone go
to the backlog (`state/backlog.md`) and are reported **once**, not re-narrated
every run.

## Scheduling

`catch-up` is designed to run as a **scheduled task** (e.g. a Claude Desktop
scheduled task whose prompt is `/elephant-mem:catch-up`, pointed at your bundle
folder). A scheduled task is the durable mechanism: it survives restarts and
needs no open terminal. It matters because the MCP connectors this routine
uses (Slack / Calendar / Drive / any BYO source) authenticate interactively
through the desktop app; a headless OS `cron` generally can't reach them, and
the bundle is local-only sensitive data that must not be pushed to a cloud
runner.

- **Freshness comes from the schedule; gap-recovery comes from the cursor.**
  The task fires only while the app is running; when the machine is off there is
  no run. That is fine — every source cursor is a timestamp, so whenever the
  routine next runs it fast-forwards the entire offline gap in one pass. The two
  are orthogonal; don't raise the cadence to "cover" being offline (it can't).
- Configure the task with a permissive permission mode and **worktree OFF** (it
  commits in place), then do a "Run once" after creating it to pre-approve the
  MCP / Bash / Edit prompts so unattended runs don't stall.
- Hourly is a good default. Sub-hourly buys little: meeting-notes docs lag their
  meeting by minutes-to-hours, and empty windows already cost almost nothing
  under the timestamp cursor.

Run `maintain` on a slower cadence (e.g. daily) and `review` whenever the
`needs-review` queue grows.
