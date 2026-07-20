---
name: push-start-day
disable-model-invocation: true
description: >
  Autonomous variant of start-day that POSTS the morning orientation to Slack
  (the owner's self-DM) instead of printing it in the conversation. Runs
  unattended, fired by a scheduled task. Read-only on the bundle (writes
  nothing, no commit). Invoke only explicitly or via the scheduled task
  (elephant-mem:push-start-day).
---

# elephant-mem:push-start-day

The scheduled morning push — the `start-day` synthesis, delivered to Slack.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>`, `elephant.json`, and the sources block). Obey **Retrieval trust** in
`../_shared/core.md`. Runs **unattended** — no conversational recap, no review
gate, **writes nothing to the bundle** (no facts, no commit). Its only side
effect is one Slack message.

## Destination and preconditions

The message goes to `delivery.start_day.channel_id` from `elephant.json`,
typically the owner's own Slack `user_id` (posting to yourself lands in your
self-DM). If `delivery` is absent or `delivery.start_day` is unset, there is
nowhere to post — **explain and stop**; this mode has nothing else to do. If
`delivery.start_day.via` is anything other than `"slack"`, say that transport
isn't implemented in `0.1.0` yet and point to the bring-your-own-source guide
in `docs/integrations.md`, then stop. Likewise, if the Slack connector isn't
available, say so and stop (there is nothing to write to the bundle either
way).

All conversational output is rendered in the bundle's `conversation_language`
(the example block headers below are English defaults; use the configured
language). The relevance lens is the owner: `owner.slug` from `elephant.json`,
plus the owner's projects/team.

## Procedure

1. **Build the orientation.** Produce the exact three-block `start-day`
   synthesis (see `../start-day/SKILL.md`) in `conversation_language` — a
   30-second read, not a dump:
   1. **Today's agenda** — Calendar MCP `list_events` for today (times +
      meetings). If Calendar isn't connected, **skip this block** and note it in
      one line — never fail the whole run for a missing connector.
   2. **What's relevant / what happened** — `python3 scripts/briefing.py --since
      <last-working-day> --entity <owner.slug>` (plus the owner's team/projects);
      surface **decisions** and new facts since the last working day, grouped by
      channel. `--since`: use the previous weekday (Mon → last Fri; else
      yesterday). Served from already-ingested facts — no live Slack needed.
   3. **What I need to do** — the owner's `open` loops from
      `tracking/open-loops.md`, oldest-opened first; flag any with a near
      closure signal.

   Obey **Retrieval trust**: group any `low` / `needs-review` items under a
   separate "⚠️ to confirm" line, never inline with solid facts.

2. **Format for Slack.** One message, Slack markdown, **under 5000 chars**,
   mobile-readable. A dated header (e.g. `*🐘 start-day · <weekday> DD/MM*`),
   then the three blocks as short bullet lists with bold sub-headers. Keep only
   the headline of each item; no fact bodies, no provenance dump. If a block is
   empty, say so in one line rather than omitting it silently.

3. **Post to Slack.** `slack_send_message` with
   `channel_id: <delivery.start_day.channel_id>`. On send failure, report the
   error and stop; do not retry blindly.

4. **Done.** Return the message link. No `log.md` entry, no commit — this mode
   never touches the bundle.

## Scheduling

Same mechanism as `catch-up`: a **scheduled task** (e.g. a Claude Desktop
scheduled task whose prompt is `/elephant-mem:push-start-day`, pointed at your
bundle folder). It must be **Local** — not a cloud runner — because both the
Calendar MCP (agenda) and the Slack MCP (posting) authenticate interactively
through the desktop app's connectors, which a headless runner can't reach, and
the bundle is local-only.

- Suggested cadence: **weekday mornings** (e.g. 08:00 Mon–Fri). Set the time,
  days, model, and permission mode in the scheduling app — they live there, not
  in this file. Use a permissive permission mode and **worktree OFF**, then "Run
  once" after creating it to pre-approve the Calendar / Slack / Bash prompts so
  unattended runs don't stall.
- It only fires while the app is running (like `catch-up`). A missed morning
  simply means no push that day — there is no state to fast-forward, the
  synthesis is always "today".
- To change the destination (e.g. a dedicated private channel instead of the
  self-DM), set a different `channel_id` in `delivery.start_day`.
