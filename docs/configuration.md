# Configuration

elephant-mem has **two** config files. They have distinct jobs and live in
different places:

| File | Location | Scope | Job |
|---|---|---|---|
| **Pointer** | `~/.config/elephant-mem/config.json` | Machine | Tells the plugin *where the bundle is*. |
| **Bundle config** | `<bundle>/elephant.json` | Bundle | Describes *the knowledge* — owner, languages, timezone, sources. |

The split is deliberate: the pointer is machine-local and never travels; the
bundle config lives **inside** the bundle, so a bundle stays self-contained and
portable (move it to another machine, re-register the pointer, done).

---

## 1. Pointer file — `~/.config/elephant-mem/config.json`

Written by the `init` mode. Read first by every mode to resolve the bundle. The
only required key is `bundle_path` (absolute).

```json
{
  "bundle_path": "/Users/jane/notes/my-memory"
}
```

If this file is missing or unreadable, modes stop and ask the user to run
`elephant-mem:init`. A mode never guesses a bundle path.

On Windows, `~` expands to `C:\Users\<name>\.config\elephant-mem\config.json`
rather than the more idiomatic `%APPDATA%` — that's intentional, so the
pointer path resolves the same way (via `expanduser`) on every platform.

### Optional `smtp` block

For the `via: "smtp"` email delivery transport (see `delivery.start_day`
below), the pointer file may also carry an `smtp` block — server + credentials
are machine-local, so a bundle can be moved or synced to another machine
without carrying secrets with it:

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

- `host`, `port` — the SMTP server. Port `465` connects over implicit TLS;
  any other port (e.g. `587`) uses plain SMTP + STARTTLS.
- `username` — the SMTP auth username (usually the same as `from`).
- `from` — the sender address on outgoing mail.
- `password_env` — the name of an **environment variable** holding the SMTP
  password/app-password. **Preferred**: the secret never touches disk in the
  pointer file itself; export it in your shell profile (or wherever the
  scheduled task's environment is configured).
- `password` — an alternative: the password inline, in plaintext, in the
  pointer file. Simpler to set up but means a secret lives on disk — if you
  use this, `chmod 600 ~/.config/elephant-mem/config.json` (the same model as
  `.netrc` or `msmtp` config files; on Windows, restrict the file via its
  Properties → Security tab or `icacls`). If both `password_env` and
  `password` are present, `password_env` wins.

`plugin/assets/scripts/send-email.py` reads this block; see
[integrations.md](integrations.md#email-delivery-smtp) for a worked example.

---

## 2. Bundle config — `<bundle>/elephant.json`

Describes the knowledge itself. Committed **inside** the bundle (it is not
sensitive on its own, but it lives with the bundle so identity travels with the
data). Fully annotated example with **fictional** data:

```json
{
  "owner": {
    "name": "Jane Doe",
    "slug": "jane-doe"
  },
  "knowledge_language": "en",
  "conversation_language": "en",
  "timezone": "-05:00",
  "sources": {
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
    },
    "calendar": {
      "notes_doc_marker": "Meeting notes",
      "gcal_lag_hours": 3,
      "gcal_lookback_hours": 48,
      "channel": "meeting"
    }
  },
  "delivery": {
    "start_day": { "via": "slack", "channel_id": "U0EXAMPLE01" }
  }
}
```

### Field reference

**`owner`** (required)
- `name` — display name, used in conversational prose.
- `slug` — kebab-case; the owner's person entity is
  `knowledge/entities/person/<slug>.md`, and the retrieval owner-lens is
  `--entity <slug>`. `init` creates this entity.

**`knowledge_language`** (default `"en"`) — language every fact/entity/source file
is written in. One stable language for the whole bundle.

**`conversation_language`** (default `"en"`) — language for recaps, briefings, and
query answers. May differ from `knowledge_language`.

**`timezone`** (default the machine's) — IANA name or fixed offset (e.g.
`"America/New_York"` or `"-05:00"`). Used to interpret cursors and window math.

**`sources`** (optional) — configures automatic ingestion. Absent/empty means the
bundle is manual-ingest only; `catch-up` and `push-start-day` have nothing to do
and say so. Each source is optional and independent.

#### `sources.slack`

- `streams` — a map of **independent** streams, each with its own cursor in
  `state/cursors.json`. A stream has:
  - `channel_types` — Slack search filter: `public_channel` | `private_channel` |
    `im`.
  - `allow` — allow-list of channels; when present, **only** these are swept
    (used for a curated `slack:social` stream).
  - `deny` — glob patterns to exclude (e.g. `notif-*`).
  - `exclude_bots` — drop bot messages.
  - `skip_logistics` — apply skip-rules hard (for DMs, mostly logistics); keep
    only durable facts and commitments.
  - `channel` — the `channel:` value stamped on provenance frontmatter of facts
    from this stream.
- `sweep_query` (default `"-zzqqxxjj"`) — the broad query used to return
  *everything* in a window. It is a **pure negation**, not a search term: Slack
  has no match-all operator and no boolean OR, but a query consisting only of
  `-<token nobody ever types>` matches every message. Change it only if that
  nonsense token could plausibly appear in your workspace.

  **Do not replace it with a common word.** The obvious-looking approach — query
  a high-frequency stopword (`"the"`, `"de"`) — under-returns badly and silently:

  | query, same window, same workspace | messages returned |
  |---|---|
  | `-zzqqxxjj` (negation) | paginated, unbounded |
  | `de` (Portuguese stopword) | **3, for an entire day** |

  Two independent reasons, either one fatal: Slack's index drops common terms
  unpredictably (measured recall for one term swung between 0% and 75% across
  windows), and **a message with no body text cannot match any term at all** —
  bot posts carrying only a link unfurl or an attachment are structurally
  invisible to a stopword sweep and visible to the negation query.

- `query_stopword` — **legacy**, superseded by `sweep_query`. Still honored as a
  fallback when `sweep_query` is absent, so old bundles keep working, but such a
  bundle is under-returning; `catch-up` files a backlog item when it sees one.

> **These three fields are self-tuning.** `sweep_query`, and each stream's
> `allow` / `deny`, are the only part of `elephant.json` the unattended
> `catch-up` routine may rewrite on its own — and only after measuring the same
> problem on three consecutive runs, one change per run, in its own commit
> (`git log --grep='catch-up: config'` is the audit trail; a single `git revert`
> undoes one). Everything else in this file is human-only. See the `catch-up`
> skill's `procedure.md` → **Autonomy envelope**.
>
> The reason is that sweep recall is only observable in production, against a
> real workspace's traffic — the routine is the only thing positioned to notice
> a regression, run after run.

#### `sources.calendar`

- `notes_doc_marker` — the title fragment identifying the meeting-notes document
  attached to a calendar event (e.g. an auto-generated "Meeting notes" doc). The
  doc is read via the Drive connector and ingested as a transcript.
- `gcal_lag_hours` — after a run, the transcript cursor is set to `now − lag` so a
  just-ended meeting stays in the window next run (notes are generated with a
  delay).
- `gcal_lookback_hours` — how far back of the cursor to re-scan for events, to
  catch notes docs that were not ready on an earlier run.
- `channel` — the `channel:` value for facts from transcripts (e.g. `meeting`).

#### Bring-your-own source

Any MCP-backed source can be added under `sources` following the same shape: a
name, a `channel:` value for provenance, and whatever extraction hints the source
needs. Register a matching cursor entry in `state/cursors.json` (see below) so the
forward/backfill routine tracks it. The plugin's `catch-up` treats every
configured source uniformly: read its cursor → sweep after it → extract → advance.

**`delivery`** (optional) — where **outbound** messages go, as opposed to
`sources` (which is always inbound). Each key names something the plugin can
push out; `0.1.0` defines one, with two supported transports:

- `delivery.start_day` — the destination for `push-start-day`'s morning
  message. Two shapes, chosen by `via`:
  - `{ "via": "slack", "channel_id": "<id>" }` — `channel_id` is usually
    **your own Slack user id**, so posting there lands in your self-DM — but
    it can be any channel id (e.g. a dedicated private channel) if you'd
    rather it post somewhere else.
  - `{ "via": "smtp", "to": "jane@example.com" }` — `to` is the recipient
    address; the sending server + credentials come from the pointer file's
    `smtp` block (above), not from this bundle-side config. This transport
    needs no MCP connector at all — it sends directly via
    `scripts/send-email.py`.
  - `via` — the delivery transport. `"slack"` and `"smtp"` are both
    implemented in `0.1.0`. Any other value is accepted in config but
    `push-start-day` will say it isn't implemented yet and point you at the
    bring-your-own-source guide in [integrations.md](integrations.md) instead
    of silently doing nothing.
  - If `delivery` is absent, or `delivery.start_day` is unset, `push-start-day`
    has nowhere to post — it explains that and stops.

**`audio`** (optional) — settings for the `ingest-audio` mode.

- `audio.inbox_dir` — where transferred recordings land before transcription
  (e.g. a Taildrop/AirDrop/synced-drive destination folder). Resolution order:
  the `ELEPHANT_TAILDROP_DIR` environment variable (highest priority, useful
  for a one-off override) → this key, expanded from `~` → `~/Downloads`
  (default). A missing or malformed `elephant.json` is not an error here —
  `scripts/ingest-audio.py` just falls through to the next option in the
  order above.

**`hooks`** (optional) — lifecycle extension points. elephant-mem emits events
at well-defined moments; any plugin can subscribe by adding a command here,
without the ingestion modes ever knowing about it. `hooks` is a **map** of event
name → list of subscriber entries, so new events can be added without breaking
the schema.

```json
"hooks": {
  "post_ingest": [
    { "name": "wiki", "run": ["/usr/bin/python3", "/abs/path/wiki.py", "build"] }
  ]
}
```

- **`post_ingest`** — the only event today. Fired **once** at the end of a
  `capture`, `ingest`, or `catch-up` cycle, *after* the derived surfaces
  (`manifest.jsonl`, backlinks) are regenerated and the commit has landed. So a
  subscriber sees final, committed state. (It is NOT fired on every internal
  `build-index.py` rebuild — e.g. `maintain`'s many rebuilds stay silent.)
- Each entry: **`run`** (required) — the command, either an argv **list**
  (`["python3", "x.py", "build"]`, preferred — no quoting pitfalls, portable) or
  a **string** (`"python3 x.py build"`, split with POSIX shell rules). It is a
  program + args, not a shell pipeline; wrap in `bash -c "…"` yourself if you
  need one. In a **string** on Windows, write paths with forward slashes (the OS
  accepts them; backslashes are shlex escapes) — or just use the list form,
  which `--register` writes and which never has this caveat. **`name`**
  (optional) — a label for logs. **`timeout`** (optional, default 120s).
  **`enabled`** (optional) — set `false` to keep an entry registered but dormant.
- Every hook runs with `ELEPHANT_BUNDLE` (absolute bundle path), `ELEPHANT_EVENT`
  (the event name), and `ELEPHANT_TRIGGER` (`capture` | `ingest` | `catch-up`)
  in its environment.
- Hooks are **best-effort and isolated**: a hook that fails, times out, or is
  malformed is logged to `state/hooks.log` and skipped — it never breaks the
  ingestion, and one failing hook never stops the next. The runner
  (`scripts/run-hooks.py`) always exits 0 when the event was processed.
- Subscribers register themselves (see e.g. `elephant-wiki`'s `--register`);
  you rarely hand-edit this block.

---

## 3. Operational state — `<bundle>/state/`

Not part of the OKF bundle (not under `knowledge/`), so `validate-okf.py` never
touches it. Managed by `scripts/state.py`.

- `state/cursors.json` — one entry per source with two cursors: `live_cursor`
  (newest content ingested; read strictly after it) and `backfill_oldest` (how
  far back the day-sweep reached). Seeded empty by `init`; the first `catch-up`
  fills them. A `config` block holds `timezone`, `gcal_lag_hours`,
  `gcal_lookback_hours`, and `backfill_window_start` (the backfill horizon).
- `state/watermarks.md` — human-readable rendering of `cursors.json`, regenerated
  by `state.py`. **Never hand-edit.**
- `state/processed-events.json` — IDs of calendar events / source documents
  already ingested, so re-observed items merge instead of duplicating. Managed
  by `catch-up`.
- `state/needs-review.md` — the low-confidence review queue.
- `state/last-update-check.json` — throttles the weekly update nudge (see
  core.md).
- `state/hooks.log` — append-only trace of `post_ingest` hook runs (one
  tab-separated line per hook: timestamp, event, name, outcome). Best-effort
  debug aid for unattended runs; safe to delete.
- `state/phone/` — the audio inbox and diarized transcripts kept by
  `ingest-audio` (git-ignored in the bundle by default).

---

## Quick start

1. `claude plugin marketplace add rafapg/elephant-mem`
2. `claude plugin install elephant-mem@elephant-mem`
3. Run `elephant-mem:init` — it walks you through creating a bundle directory,
   writes the pointer and `elephant.json`, seeds `config.md`, `state/`, and your
   owner entity, and does the first `git init` + commit.
4. (Optional) Fill in the `sources` block to enable `catch-up` /
   `push-start-day`.
