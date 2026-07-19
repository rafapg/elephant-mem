# Integrations

elephant-mem has **two layers**:

- **Core modes need zero connectors.** `query`, `briefing`, `capture`, `ingest`,
  `maintain`, `expand`, `review`, `start-day`, and `end-day` all operate on the
  local markdown bundle alone. You can run the whole system this way, adding
  knowledge by hand with `ingest` and `capture`.
- **Automatic ingestion is optional** and driven by the `sources` block in
  `elephant.json`. `catch-up` (scheduled autonomous ingestion) and
  `push-start-day` (post the morning orientation to Slack) are the only modes that
  touch connectors.

This doc covers the tested integrations, how to schedule the routine, and how to
bring your own MCP source. For the full config field reference, see
[configuration.md](configuration.md).

## Prerequisites

- **Claude Code** with the plugin installed (see the [README](../README.md)).
- **claude.ai connectors** for the sources you want — e.g. Slack, Google Calendar,
  and Google Drive, authenticated through a harness like Claude Desktop.

A missing connector never fails a run: `catch-up` skips that source with a
one-line note and carries on. If **no** sources are configured at all, `catch-up`
and `push-start-day` have nothing to do and say so.

## Slack

Slack is configured as a set of **independent streams**, each with its own cursor,
under `sources.slack.streams`. A useful starting preset is four streams:

```json
"slack": {
  "streams": {
    "slack:all-public": {
      "channel_types": "public_channel",
      "deny": ["notif-*", "social-*"],
      "exclude_bots": true,
      "channel": "slack:all-public"
    },
    "slack:private": {
      "channel_types": "private_channel",
      "exclude_bots": true,
      "channel": "slack:private"
    },
    "slack:social": {
      "channel_types": "public_channel",
      "allow": ["#eng-learning", "#industry-news"],
      "channel": "slack:social"
    },
    "slack:dm": {
      "channel_types": "im",
      "skip_logistics": true,
      "channel": "slack:dm"
    }
  },
  "self_dm_channel_id": "U0EXAMPLE01",
  "query_stopword": "the"
}
```

### allow / deny

- **`deny`** — glob patterns to exclude (e.g. `notif-*`, `social-*`). Use it to
  drop noisy channels from a broad sweep.
- **`allow`** — an allow-list. When present, **only** those channels are swept.
  This is how a curated `slack:social` stream stays narrow (just the couple of
  channels worth keeping) instead of pulling every public channel.
- **`exclude_bots`** — drop bot messages.
- **`skip_logistics`** — apply skip-rules hard, keeping only durable facts and
  commitments. DMs are mostly logistics ("running 5 late", "can you send that
  link"), so the `slack:dm` stream uses this to avoid filing noise.

### the one-word `query_stopword` rule

`catch-up` sweeps a stream by issuing a broad search and paginating the whole
window. To make "return everything in this window" work, it queries a single
**high-frequency stopword** — a word that appears in nearly every message in your
workspace's dominant language (English `"the"`, Portuguese `"de"`, Spanish
`"de"`).

**Use exactly one word.** A multi-word query ANDs its terms, so a two-word
stopword only matches messages containing *both* — which most messages don't,
producing false **"empty window"** runs where real content is silently skipped.
One word, chosen so it's present in almost every message, is the whole trick.

### self-DM for `push-start-day`

`sources.slack.self_dm_channel_id` is **your own Slack user id**. `push-start-day`
posts the morning orientation there — posting a message to yourself lands in your
self-DM, so the briefing shows up as a Slack message instead of terminal output.
Leave it out if you don't use `push-start-day`.

## Google Calendar + Google Drive

Meeting transcripts come from the Calendar + Drive pair, configured under
`sources.calendar`:

```json
"calendar": {
  "notes_doc_marker": "Meeting notes",
  "gcal_lag_hours": 3,
  "gcal_lookback_hours": 48,
  "channel": "meeting"
}
```

- **`notes_doc_marker`** — the title fragment that identifies the meeting-notes
  document attached to a calendar event (e.g. an auto-generated "Meeting notes"
  doc). `catch-up` lists events, finds the attachment whose title contains this
  marker, reads it via the **Drive** connector, and ingests it as a transcript
  source. Empty or garbled notes docs are skipped.
- **`gcal_lag_hours`** (default 3) — after a run, the transcript cursor is set to
  `now − lag` so a meeting that *just* ended stays in the window on the next run.
  Notes docs are generated with a delay, so reading immediately would miss them.
- **`gcal_lookback_hours`** (default 48) — how far back of the cursor to re-scan
  for events, to catch notes docs that weren't ready on an earlier run.
- **`channel`** — the provenance value stamped on facts from transcripts
  (e.g. `meeting`).

Transcripts are the **primary** source and outrank chat when facts conflict (see
[architecture.md](architecture.md#source-precedence-and-fact-merging)).

## Scheduling the catch-up routine

`catch-up` is designed to run as a **scheduled task** — for example, a Claude
Desktop scheduled task whose prompt is `/elephant-mem:catch-up`, pointed at your
bundle folder.

### why a desktop scheduled task, not headless cron

The MCP connectors `catch-up` uses (Slack / Calendar / Drive / any BYO source)
authenticate **interactively** through the desktop app. A headless OS `cron`
generally can't reach them — there's no authenticated session. And because the
bundle is local-only sensitive data that must never be pushed to a cloud runner,
a hosted cron isn't an option either. A scheduled task in a harness where the
connectors are already authenticated is the durable mechanism: it survives
restarts and needs no open terminal.

### setup notes

- Configure the task with a permissive permission mode and **worktree off** — it
  commits in place.
- Do a **"Run once"** after creating it, to pre-approve the MCP / Bash / Edit
  prompts so unattended runs don't stall.
- **Hourly is a good default.** Sub-hourly buys little: meeting-notes docs lag
  their meeting by minutes-to-hours, and empty windows cost almost nothing under
  the timestamp cursor.

### freshness vs. gap-recovery

These are orthogonal, and it's worth understanding why:

- **Freshness comes from the schedule.** The task only fires while the harness is
  running; when the machine is off, there's no run.
- **Gap-recovery comes from the cursor.** Every source cursor is a timestamp, so
  whenever the routine next runs it fast-forwards the entire offline gap in one
  pass.

Don't raise the cadence to "cover" being offline — it can't. The cursor already
handles it.

Run `maintain` on a slower cadence (e.g. daily) and `review` whenever the
`needs-review` queue grows.

## Bring your own MCP source

`catch-up` treats every source uniformly, so adding a new one is a matter of
declaring it. A new source must fulfill this contract:

1. **A name under `sources.*`** in `elephant.json`.
2. **A `channel:` value** — the provenance tag stamped on the frontmatter of every
   fact this source produces, so you can later filter by it in `briefing`.
3. **Extraction hints** — whatever the source needs to be swept and parsed.
4. **A cursor entry** in `state/cursors.json` (managed by `scripts/state.py`), so
   the forward/backfill routine tracks how far it has read.
5. **Skip-rules** as appropriate (the equivalent of `skip_logistics` for a chatty
   source).

`catch-up` then handles it like any other source: read its cursor → sweep after it
→ extract with its hints → stamp its `channel:` on provenance → advance its
cursor.

### worked example — adding a "linear" source

Say you want to pull issue activity from Linear via its MCP connector. Add a
source block:

```json
"sources": {
  "linear": {
    "channel": "linear",
    "teams": ["ENG"],
    "include": ["issue_created", "issue_completed", "comment"]
  }
}
```

Register its cursor in `state/cursors.json` so the routine tracks it:

```json
"channels": {
  "linear": { "live_cursor": null, "backfill_oldest": null }
}
```

Now `catch-up` sweeps Linear alongside Slack and Calendar: durable facts (a
project's scope changed, an owner was reassigned) become `type: fact` files
stamped `channel: linear`; commitments (an assigned, open issue) can become open
loops. `briefing --channel linear` then filters to just that source.

The same pattern fits an **email** source, a ticketing system, a docs tool — any
MCP-backed connector. If you build a tested recipe for one, **PRs adding
integration recipes are welcome.**
