# `elephant-mem:init` — the walkthrough

Load `../_shared/core.md` first. This file is the `init` procedure: a guided,
conversational first-run. Run it top to bottom. For every choice, use the
**AskUserQuestion** tool (don't free-type questions). Keep your own output between
stages short — the user is being onboarded, not lectured.

**Idempotence.** `init` is safe to re-run. Before creating anything, check whether
it already exists (pointer, bundle dir, owner entity). If it does, show the
current value and ask (AskUserQuestion) whether to keep it, update it, or start
fresh. Never silently overwrite user data.

**Asset location.** The bundle is scaffolded from assets that ship *inside the
installed plugin* at `${CLAUDE_PLUGIN_ROOT}/assets/`:
`${CLAUDE_PLUGIN_ROOT}/assets/seed/`, `.../assets/scripts/`, `.../assets/templates/`.
Resolve `${CLAUDE_PLUGIN_ROOT}` from the environment; if it is unset, ask the user
where the plugin is installed rather than guessing.

---

## Stage 0 — Pre-flight (environment check)

Before anything else, confirm the machine has what `init` needs:

- **Python 3.10+**: try `python3 --version`, then `python --version`, then
  `py -3 --version` (in that order — `python3` often isn't on PATH on
  Windows). Remember whichever spelling succeeds and use it for every
  `python3 scripts/...` command for the rest of this session. If none report a
  working 3.10+ interpreter, stop and tell the user to install Python (from
  python.org or the Microsoft Store) before continuing.
- **Git**: `git --version`. On Windows this doubles as confirming Git for
  Windows is installed (it ships Git Bash, the shell Claude Code requires
  there). If missing, stop and point the user to https://git-scm.com/downloads.

## Stage 1 — Orientation

Give a short (≈10 lines) plain-language intro, then continue. Cover:

- elephant-mem is a **personal memory / second brain** for Claude Code. Your
  knowledge lives as **plain markdown + git** in a bundle directory on *your*
  machine — `cat`-readable, diffable, and private. No database, no cloud, no
  embeddings.
- It has **three lanes**: **durable facts** (things that stay true), **open
  loops** (commitments/action items that eventually close), and **episodic
  sources** (the raw provenance each fact came from).
- Retrieval is **entity-centric** — people, projects, tools, and concepts are the
  navigation spine, and facts hang off them. You ask "what do we know about X"
  and it walks the entity's links.
- **Core modes work with zero connectors.** Automatic ingestion from Slack /
  Calendar is optional and set up later (Stage 6).

Then: "I'll walk you through creating your bundle. Takes about a minute."

## Stage 2 — Bundle location

Ask (AskUserQuestion) where to create the bundle. Offer `~/elephant` as the
default, plus an "other path" option.

- **Guardrail:** the bundle must **not** live inside a git repo that gets
  published (it holds private data). If the chosen path is inside an existing repo
  or a cloud-synced/publishable tree, warn and re-ask. A fresh dedicated directory
  in `$HOME` is ideal.
- If the directory already exists and is non-empty, show its contents and ask
  before proceeding (it may be an existing bundle — treat this as a re-run).
- Create it and initialize git:
  ```
  mkdir -p <bundle>
  git -C <bundle> init
  ```
  From here on, `<bundle>` is that absolute path.

## Stage 3 — Identity

Collect the owner identity (this fills `elephant.json` and the owner entity).

1. **Owner name** — free text (e.g. "Jane Doe").
2. **Slug** — derive kebab-case from the name (`jane-doe`) and confirm via
   AskUserQuestion (offer the derived value + "let me type a different one").
   The slug is permanent-ish: it names `entities/person/<slug>.md` and is the
   retrieval owner-lens.
3. **knowledge_language** — the language every fact/entity/source file is written
   in. Default `en`. Explain it's usually best to keep this stable and close to
   your source material.
4. **conversation_language** — the language recaps, briefings, and query answers
   come back in. Default `en`. May differ from `knowledge_language`.
5. **timezone** — detect the machine's (`date +%z` → format as `±HH:MM`, or read
   the IANA zone) and confirm. Accept an IANA name (`America/New_York`) or a fixed
   offset (`-05:00`).

## Stage 4 — Scaffold the bundle

Create the directory tree and copy the shipped assets **into the bundle** (the
bundle is self-contained — it owns its own copy of the scripts and templates so it
keeps working regardless of the plugin):

```
mkdir -p <bundle>/knowledge/facts \
         <bundle>/knowledge/entities/person \
         <bundle>/knowledge/entities/org \
         <bundle>/knowledge/tracking/loops \
         <bundle>/knowledge/sources \
         <bundle>/state <bundle>/scripts <bundle>/templates <bundle>/raw

cp ${CLAUDE_PLUGIN_ROOT}/assets/scripts/*.py       <bundle>/scripts/
cp ${CLAUDE_PLUGIN_ROOT}/assets/templates/*.md     <bundle>/templates/
cp ${CLAUDE_PLUGIN_ROOT}/assets/seed/config.md     <bundle>/config.md
cp ${CLAUDE_PLUGIN_ROOT}/assets/seed/README.md     <bundle>/README.md
cp ${CLAUDE_PLUGIN_ROOT}/assets/seed/state/cursors.json <bundle>/state/cursors.json
```

Then generate the files that depend on the user's answers:

- **`<bundle>/elephant.json`** — build it from Stage 3 (and Stage 6 if sources are
  configured). For a manual-only setup, omit `sources` entirely:
  ```json
  {
    "owner": { "name": "<name>", "slug": "<slug>" },
    "knowledge_language": "<knowledge_language>",
    "conversation_language": "<conversation_language>",
    "timezone": "<timezone>"
  }
  ```
- **`<bundle>/state/cursors.json`** — patch the copied file's `config.timezone`
  to the user's timezone (leave `channels` empty; `catch-up` fills it later).
- **`<bundle>/.gitignore`** — copy `${CLAUDE_PLUGIN_ROOT}/assets/seed/.gitignore`
  (covers `state/phone/`, `.cache/`, `__pycache__/`, OS noise).
- **`<bundle>/knowledge/log.md`** — a reserved file (NO frontmatter), just a
  heading, e.g. `# Log\n`. The episodic ledger; modes append to it.

Do **not** hand-write `index.md`, `entities/index.md`, or `tracking/open-loops.md`
— they are derived and generated in Stage 8.

## Stage 5 — Register the pointer

Write the machine-level pointer so every other mode can find the bundle:

```
mkdir -p ~/.config/elephant-mem
```
`~/.config/elephant-mem/config.json`:
```json
{ "bundle_path": "<bundle>" }
```

If a pointer **already exists** and points elsewhere, show the existing
`bundle_path` and ask (AskUserQuestion) before overwriting — the user may be
re-pointing to a new bundle or may have run `init` by mistake.

## Stage 6 — Integrations (optional, skippable)

Ask first (AskUserQuestion): "Set up automatic ingestion now, or keep it
manual-only for now?" Explain the two layers plainly:

- **Core modes need zero connectors** — `capture`, `ingest`, `query`, `briefing`,
  `maintain`, etc. all work on the local bundle alone.
- **`catch-up` and `push-start-day` are optional** and need MCP connectors (Slack,
  and/or Google Calendar + Drive — e.g. via Claude Desktop's connectors). They are
  driven by the `sources` block you configure here.

If the user **skips**: omit `sources` from `elephant.json`, tell them the bundle
is manual-ingest only and that's completely fine — they can re-run `init` or edit
`elephant.json` later. Move on.

If the user wants **Slack**, collect it conversationally and write
`sources.slack`. Offer the **four canonical streams** as a starting preset (they
can trim):

| Stream | `channel_types` | Notes |
|---|---|---|
| `slack:all-public` | `public_channel` | `deny` noisy prefixes (e.g. `notif-*`), `exclude_bots: true` |
| `slack:private` | `private_channel` | `exclude_bots: true` |
| `slack:social` | `public_channel` | `allow`-list only a couple of curated channels |
| `slack:dm` | `im` | `skip_logistics: true` (DMs are mostly logistics) |

Each stream carries a `channel:` value (its own name) stamped on the provenance of
facts it produces. Also collect:

- **`sweep_query`** — leave it at the default `"-zzqqxxjj"` unless that nonsense
  token could plausibly appear in the workspace. It is a **pure negation**, which
  is how a Slack search returns *everything* in a window (there is no match-all
  operator and no boolean OR). Don't offer a "pick a common word" option: a
  stopword sweep under-returns silently, and messages with no body text — bot
  posts that are only a link unfurl — can never match a term at all.

If the user wants **Calendar** (meeting transcripts), write `sources.calendar`:

- **`notes_doc_marker`** — the title fragment of the auto-generated meeting-notes
  doc attached to events (e.g. `"Meeting notes"`), read via the Drive connector.
- `gcal_lag_hours` (default 3), `gcal_lookback_hours` (default 48), and
  `channel` (e.g. `"meeting"`).

**Bring-your-own:** mention that any MCP source can be added later under `sources`
with the same shape (a name, a `channel:` value, a cursor entry). See
`docs/configuration.md`.

If the user wants `push-start-day`, also collect **delivery** (a separate,
top-level block — `sources` is inbound, `delivery` is outbound). Ask
(AskUserQuestion) which transport: **Slack self-DM** / **email (SMTP)** /
**skip**.

**Slack self-DM** (needs `sources.slack` configured above): ask for the
destination channel id (usually the owner's own Slack user id, so a self-DM)
and write:

```json
"delivery": {
  "start_day": { "via": "slack", "channel_id": "<channel_id>" }
}
```

**Email (SMTP)** — needs no MCP connector at all; `push-start-day` sends
directly via `scripts/send-email.py`. Collect two things:

1. **Bundle-side `to` address** — the recipient, written into
   `elephant.json`:
   ```json
   "delivery": {
     "start_day": { "via": "smtp", "to": "jane@example.com" }
   }
   ```
2. **Machine-side `smtp` block** — walk the user through the sending server,
   and write it into the **pointer file**
   (`~/.config/elephant-mem/config.json`), **merging** with the existing
   `bundle_path` rather than clobbering it:
   - `host`, `port` (e.g. `smtp.gmail.com`, `587`)
   - `username` (the SMTP auth user, usually same as `from`)
   - `from` (the sender address)
   - `password_env` — **recommended**: the name of an environment variable
     holding the password (e.g. `ELEPHANT_SMTP_PASSWORD`). Tell the user to
     export it in their shell profile (or wherever the scheduled task's
     environment is set) — the pointer file itself then holds no secret.
     Mention that Gmail requires an **app password** (needs 2FA enabled),
     generated at https://myaccount.google.com/apppasswords.
   - Alternative: an inline `password` field (simpler, but plaintext on disk —
     if used, `chmod 600 ~/.config/elephant-mem/config.json` (macOS/Linux); on
     Windows, restrict the file instead via its Properties → Security tab, or
     `icacls ~/.config/elephant-mem/config.json /inheritance:r /grant:r "$env:USERNAME:F"`
     in PowerShell — `chmod` in Git Bash does not enforce real ACLs on an NTFS
     file).

   Resulting pointer file:
   ```json
   {
     "bundle_path": "<bundle>",
     "smtp": {
       "host": "smtp.gmail.com",
       "port": 587,
       "username": "jane@example.com",
       "from": "jane@example.com",
       "password_env": "ELEPHANT_SMTP_PASSWORD"
     }
   }
   ```

   Offer a test: run `python3 <bundle>/scripts/send-email.py --config
   ~/.config/elephant-mem/config.json --to <to> --subject "elephant-mem test"
   --body-file <a small temp file> --dry-run` to confirm the config resolves
   (host/port/from/password source) without sending anything. If the user
   wants, follow up with a real send (drop `--dry-run`) to confirm delivery
   end-to-end.

Explain that `"slack"` and `"smtp"` are both implemented `via` transports in
`0.1.0`. If the user **skips**, omit `delivery` entirely — `push-start-day`
explains it has nowhere to post and stops, which is fine.

## Stage 7 — Seed knowledge

Create the starting entities and a few **clearly-marked, fictional** examples so
the bundle isn't empty and the shapes are visible. Tag every example
`example-seed` so they are trivial to find and delete.

1. **Owner entity** — `<bundle>/knowledge/entities/person/<slug>.md` from
   `templates/entity.md`: `kind: person`, `title: <owner name>`, a one-line
   description, empty `aliases`/`tags`, dates = today. This is real, not an
   example — leave it untagged.
2. **Example entity** — an org, e.g. `entities/org/acme-corp.md` (`kind: org`,
   `title: Acme Corp`, `tags: [example-seed]`).
3. **Example source** — `sources/<YYYY-MM>/<today>-example.md` from
   `templates/source.md` (`source-kind: note`, `channel: manual`,
   `tags: [example-seed]`), so the example facts have provenance to cite.
4. **2–3 example facts** — from `templates/fact.md`, `tags: [example-seed]`,
   linking the owner and/or Acme Corp entities and the example source with
   **bundle-absolute** links (`/entities/org/acme-corp.md`, `/sources/…`). For
   example: "Acme Corp is a fictional example entity used to demonstrate the
   elephant-mem fact shape." Optionally one **example open-loop** in
   `tracking/loops/`.

Tell the user these are placeholders: `elephant-mem:capture` and
`elephant-mem:ingest` add real knowledge, and the examples can be removed any time
with `rg -l example-seed <bundle>/knowledge` (then delete + re-run `build-index`).
That search also matches the derived `knowledge/manifest.jsonl` — don't delete
it; it regenerates on the next `build-index.py` run.

## Stage 8 — Verify + first commit

From the bundle, regenerate the derived surfaces and validate, then commit:

```
python3 <bundle>/scripts/build-index.py
python3 <bundle>/scripts/validate-okf.py
```

Both must succeed (validate exits 0). If validation fails, fix the offending file
(usually a broken bundle-absolute link or a missing `type`) and re-run before
committing — do not commit a failing bundle. Then:

```
git -C <bundle> add -A
git -C <bundle> commit -m "init: create elephant-mem bundle"
```

**Local commit only — never push.** The bundle is private.

## Stage 9 — Global awareness (optional)

Offer to make Claude aware of the bundle in every session by installing the
global snippet. **Ask first** (AskUserQuestion) — this touches the user's own
config.

- Copy `${CLAUDE_PLUGIN_ROOT}/assets/elephant-plugin.md` (bundled with the
  plugin) to `~/.claude/elephant-plugin.md`.
- Show the **exact line** you'd add to `~/.claude/CLAUDE.md` and ask before
  editing:
  ```
  @elephant-plugin.md
  ```
- If the user declines, skip silently — the plugin's modes still work when invoked
  explicitly.

## Stage 10 — Wrap

Short recap in the bundle's `conversation_language`:

- Where the bundle lives, that the pointer is registered, and what's in it (owner
  entity + N example items, sources configured or manual-only).
- Suggested first steps:
  1. Capture a real fact — `elephant-mem:capture` (or `elephant-mem:ingest <file/url>`).
  2. Try recall — `elephant-mem:query <name/topic>` or `elephant-mem:briefing`.
  3. If sources were configured, set up the `catch-up` schedule (a recurring
     Claude Desktop task pointed at the bundle) to keep memory fresh.
  4. Delete the `example-seed` items once you've seen the shapes.
