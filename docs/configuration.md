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
      "self_dm_channel_id": "U0EXAMPLE01",
      "query_stopword": "the"
    },
    "calendar": {
      "notes_doc_marker": "Meeting notes",
      "gcal_lag_hours": 3,
      "gcal_lookback_hours": 48,
      "channel": "meeting"
    }
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
- `self_dm_channel_id` — the owner's own Slack user_id, used by `push-start-day`
  as the destination for the morning message (posting to yourself = your self-DM).
- `query_stopword` — a single high-frequency word in the workspace's dominant
  language, used as the broad search query so a sweep returns everything in the
  window. **Use exactly one stopword** — multi-word queries AND their terms and
  cause false "empty window" runs. Pick a word that appears in nearly every
  message in your workspace's main language (English `"the"`, Portuguese `"de"`,
  Spanish `"de"`, etc.).

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
- `state/phone/` — diarized transcripts kept by `from-phone-tts` (git-ignored
  in the bundle by default).

---

## Quick start

1. `claude plugin marketplace add rafapg/elephant-mem`
2. `claude plugin install elephant-mem@elephant-mem`
3. Run `elephant-mem:init` — it walks you through creating a bundle directory,
   writes the pointer and `elephant.json`, seeds `config.md`, `state/`, and your
   owner entity, and does the first `git init` + commit.
4. (Optional) Fill in the `sources` block to enable `catch-up` /
   `push-start-day`.
