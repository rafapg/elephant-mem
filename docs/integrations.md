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
  "sweep_query": "-zzqqxxjj"
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

### `sweep_query` — why it's a negation, not a stopword

`catch-up` sweeps a stream by issuing one broad search and paginating the whole
window. Slack's search offers no match-all operator and no boolean OR (a space
ANDs the terms), so "return everything since the cursor" has to be expressed
some other way. It does support `-term` exclusion — and a query that is
**nothing but a negation of a token nobody ever types** matches every message.
That is `sweep_query`, default `"-zzqqxxjj"`.

The intuitive alternative — query a high-frequency stopword — does not work, and
fails in the worst possible way: quietly, with a plausible-looking non-empty
result. Measured on a real workspace, identical window and call shape, the
negation query paginated without bound while `"de"` returned **3 messages for an
entire day**.

Two independent causes:

1. **Slack's index drops common terms unpredictably.** The same term's recall
   swung from 0% to 75% across consecutive windows. No term was ever complete,
   so this is not a tuning problem — there is no correct word to pick.
2. **A message with no body text can never match a term.** Bot posts that carry
   only a link unfurl or an attachment have no words to match. They are
   structurally unreachable by any stopword and returned normally by the
   negation query.

Older bundles may still carry `query_stopword`; it is honored as a fallback so
they keep running, but they are under-returning and `catch-up` says so.

### delivery: self-DM for `push-start-day`

Outbound delivery is configured separately from inbound `sources`, under a
top-level `delivery` block:

```json
"delivery": {
  "start_day": { "via": "slack", "channel_id": "U0EXAMPLE01" }
}
```

`delivery.start_day.channel_id` is typically **your own Slack user id** —
`push-start-day` posts the morning orientation there, and posting a message to
yourself lands in your self-DM, so the briefing shows up as a Slack message
instead of terminal output. It can also be any other channel id if you'd
rather it post elsewhere. `via: "slack"` and `via: "smtp"` (below) are both
implemented in `0.1.0`; see [configuration.md](configuration.md) for the full
field reference. Leave `delivery` out entirely if you don't use
`push-start-day`.

## Email delivery (SMTP)

The `via: "smtp"` transport for `delivery.start_day` sends the morning
orientation as a plain-text email instead of (or as an alternative to) a Slack
post. It works with **any** SMTP provider — Gmail, a company mail server,
Fastmail, SES SMTP, etc. — and needs **no MCP connector**, since
`plugin/assets/scripts/send-email.py` talks to the SMTP server directly with
Python's stdlib `smtplib`.

Configuration is split, same as the pointer/bundle split everywhere else in
elephant-mem:

- **Bundle side** (`elephant.json`, travels with the bundle) — just the
  recipient:
  ```json
  "delivery": {
    "start_day": { "via": "smtp", "to": "jane@example.com" }
  }
  ```
- **Machine side** (`~/.config/elephant-mem/config.json`, the pointer file,
  never travels) — the sending server and credentials, under an `smtp` block:
  ```json
  {
    "bundle_path": "/Users/jane/notes/my-memory",
    "smtp": {
      "host": "smtp.gmail.com",
      "port": 587,
      "username": "jane@example.com",
      "from": "jane@example.com",
      "password_env": "ELEPHANT_SMTP_PASSWORD"
    }
  }
  ```

### worked example — Gmail

1. Enable 2-factor authentication on the Google account (required for app
   passwords).
2. Generate an app password at
   https://myaccount.google.com/apppasswords — a 16-character password scoped
   to this one use, separate from the account password.
3. Export it where the scheduled task's environment picks it up:
   ```bash
   export ELEPHANT_SMTP_PASSWORD="xxxx xxxx xxxx xxxx"
   ```
4. Pointer file `smtp` block: `host: smtp.gmail.com`, `port: 587`, `username`
   and `from` = the Gmail address, `password_env: ELEPHANT_SMTP_PASSWORD`.
5. Test without sending anything:
   ```bash
   python3 <bundle>/scripts/send-email.py \
     --to jane@example.com --subject "test" --body-file <a text file> \
     --dry-run
   ```
   This validates the config and prints a summary (host, port, from, to,
   subject, body length, password source) without connecting. Drop
   `--dry-run` to send for real.

Any other provider follows the same shape — just point `host`/`port` at that
provider's SMTP endpoint and use its credentials.

### why SMTP and not the Gmail MCP connector

The claude.ai **Gmail** connector is read/draft-only — it can search, read,
and create drafts, but has no send tool. That's fine for triaging inbox
content, but it can't deliver an autonomous push. SMTP is the direct,
connector-free path to actually sending mail, which is why `push-start-day`'s
email transport goes straight to `send-email.py` instead of through Gmail's
MCP tools.

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

Register its cursor with `scripts/state.py` — no manual JSON editing needed, it
bootstraps the channel entry for you:

```bash
python3 scripts/state.py advance-live linear 2026-07-26T00:00:00-03:00
```

This creates the `linear` entry in `state/cursors.json` (if it doesn't exist
yet) and sets its `live_cursor` to the given timestamp, so the very first
`catch-up` run sweeps forward from that point instead of pulling the source's
entire history.

Leaving the channel unregistered entirely — or setting `live_cursor: null` by
hand — is also supported and won't break anything: `state.py after linear`
then returns Unix epoch `0` (with a warning), and `next-backfill` starts its
day-by-day sweep from today. That's a deliberate "first run backfills
everything" mode; only rely on it if you actually want a full historical
sweep, since it can mean a much larger first run.

Now `catch-up` sweeps Linear alongside Slack and Calendar: durable facts (a
project's scope changed, an owner was reassigned) become `type: fact` files
stamped `channel: linear`; commitments (an assigned, open issue) can become open
loops. `briefing --channel linear` then filters to just that source.

The same pattern fits an **email** source, a ticketing system, a docs tool — any
MCP-backed connector. If you build a tested recipe for one, **PRs adding
integration recipes are welcome.**

### typed cursors — beyond timestamps

`live_cursor` is usually a bare ISO datetime string (the `date` type, implicit
for backward compatibility). Some sources aren't naturally date-based — e.g. a
docs-repo source you want to re-sweep only when its `HEAD` commit changes, not
on a schedule. For that, store a **typed** cursor instead:

```bash
python3 scripts/state.py advance-live docs-repo abc1234 --type commit
```

This stores `{"type": "commit", "value": "abc1234"}` as `live_cursor`. A
`commit` cursor supports get and equality, but deliberately **not** date
arithmetic — running `state.py after docs-repo` on it is a clear error, not a
crash, since "Unix ts of a commit hash" isn't a meaningful operation:

```bash
# get the current value (works for either cursor type)
python3 scripts/state.py live-cursor docs-repo

# no-op gate: skip the sweep unless HEAD moved
python3 scripts/state.py cursor-eq docs-repo "$(git -C /path/to/repo rev-parse HEAD)" \
  && echo "unchanged, skip" || python3 scripts/state.py advance-live docs-repo "$(git -C /path/to/repo rev-parse HEAD)" --type commit
```
