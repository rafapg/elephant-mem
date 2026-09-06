---
name: push-start-day
disable-model-invocation: true
description: >
  Autonomous variant of start-day that DELIVERS the morning orientation via
  the configured transport (Slack self-DM or SMTP email) instead of printing
  it in the conversation. Runs unattended, fired by a scheduled task.
  Read-only on the bundle (writes nothing, no commit). Invoke only explicitly
  or via the scheduled task (elephant-mem:push-start-day).
---

# elephant-mem:push-start-day

The scheduled morning push — the `start-day` synthesis, delivered via
whichever transport `elephant.json` configures.

**Load `../_shared/core.md` first** (the shared contract; it resolves
`<bundle>`, `elephant.json`, and the sources block). Obey **Retrieval trust** in
`../_shared/core.md`. Runs **unattended** — no conversational recap, no review
gate, **writes nothing to the bundle** (no facts, no commit). Its only side
effect is one outbound message (Slack post or email send).

## Destination and preconditions

The destination is `delivery.start_day` from `elephant.json`. If `delivery` is
absent or `delivery.start_day` is unset, there is nowhere to deliver to —
**explain and stop**; this mode has nothing else to do. Dispatch on
`delivery.start_day.via`:

- **`"slack"`** — post to `delivery.start_day.channel_id`, typically the
  owner's own Slack `user_id` (posting to yourself lands in your self-DM). If
  the Slack connector isn't available, say so and stop.
- **`"smtp"`** — send an email to `delivery.start_day.to`. This transport
  needs **no MCP connector at all**; it runs `scripts/send-email.py` directly.
  If the pointer file (`~/.config/elephant-mem/config.json`) has no `smtp`
  block, or the block is missing required fields, or the password can't be
  resolved (`send-email.py` will say which), **explain what's missing and
  stop** — point to `docs/configuration.md` for the pointer-file `smtp` shape.
- **Anything else** — say that transport isn't implemented in `0.1.0` yet and
  point to the bring-your-own-source guide in `docs/integrations.md`, then
  stop.

All conversational output is rendered in the bundle's `conversation_language`
(the example block headers below are English defaults; use the configured
language). The relevance lens is the owner: `owner.slug` from `elephant.json`,
plus the owner's projects/team.

## Preflight

Run the check described in `../_shared/core.md` → **Preflight** before step 1.

On **required drift** this mode **stops and sends nothing**, and that is the
whole of its response. It writes nothing to the bundle under any circumstance —
no `log.md` line, no backlog item, no commit — so unlike `catch-up`, `decay` and
`close-loops` it has nowhere to file the finding, and it must not acquire one
here. The record belongs to the hourly `catch-up`, which meets the same drift
and files it under `bundle-scripts-stale`. What the owner sees is a morning that
did not arrive, and the notice waits until someone reads it. That consequence is
accepted rather than worked around: a second channel for a halted routine is out
of scope until a halt actually goes unnoticed.

Stopping is right here, rather than pushing something degraded. Step 1's second
block runs `scripts/briefing.py` out of the bundle and its third reads
`tracking/open-loops.md`, a surface `build-index.py` writes — stale copies of
either deliver an orientation that reads as ordinary and is not, to a channel
where nobody can tell it was built from the wrong scripts. That is the opposite
of the missing Calendar connector step 1 skips in one line: an absent block
announces itself, a wrong one does not.

Any other outcome: send as usual, and on `2` or could-not-verify put the check's
one line in the message footer. The message is this mode's only channel to the
owner, so a line dropped here is a line nobody ever sees.

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

2. **Format the message.** One message, **under 5000 chars**, mobile-readable.
   A dated header (e.g. `🐘 start-day · <weekday> DD/MM`), then the three
   blocks as short bullet lists with bold sub-headers. Keep only the headline
   of each item; no fact bodies, no provenance dump. If a block is empty, say
   so in one line rather than omitting it silently. For `via: "slack"`, use
   Slack markdown (`*bold*`); for `via: "smtp"`, use plain text (no Slack
   markup).

3. **Deliver, dispatched on `delivery.start_day.via`:**
   - **`"slack"`** — `slack_send_message` with
     `channel_id: <delivery.start_day.channel_id>`. On send failure, report
     the error and stop; do not retry blindly.
   - **`"smtp"`** — write the composed briefing (plain text) to a temp file,
     then run:
     ```
     python3 <bundle>/scripts/send-email.py \
       --to <delivery.start_day.to> \
       --subject "start-day — <YYYY-MM-DD>" \
       --body-file <tmp>
     ```
     The subject date is "today" in the bundle's `timezone`. On a non-zero
     exit, report the script's error message and stop; do not retry blindly.

4. **Done.** Return the message link (Slack) or confirmation of the send
   (SMTP). No `log.md` entry, no commit — this mode never touches the bundle.

## Scheduling

Same mechanism as `catch-up`: a **scheduled task** (e.g. a Claude Desktop
scheduled task whose prompt is `/elephant-mem:push-start-day`, pointed at your
bundle folder). It must be **Local** — not a cloud runner — because the
Calendar MCP (agenda) authenticates interactively through the desktop app's
connectors, which a headless runner can't reach, and the bundle is local-only.
For `via: "slack"` the same applies to the Slack MCP (posting); `via: "smtp"`
needs no MCP connector for delivery at all — `send-email.py` connects to the
SMTP server directly — but still runs on the same local schedule since the
Calendar step needs it.

- Suggested cadence: **weekday mornings** (e.g. 08:00 Mon–Fri). Set the time,
  days, model, and permission mode in the scheduling app — they live there, not
  in this file. Use a permissive permission mode and **worktree OFF**, then "Run
  once" after creating it to pre-approve the Calendar / Slack / Bash prompts so
  unattended runs don't stall.
- It only fires while the app is running (like `catch-up`). A missed morning
  simply means no push that day — there is no state to fast-forward, the
  synthesis is always "today".
- To change the destination — a different Slack channel id, or switch
  transports entirely — edit `delivery.start_day` in `elephant.json`.
