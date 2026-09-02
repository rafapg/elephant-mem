<div align="center">

# elephant-mem

*an elephant never forgets*

![license](https://img.shields.io/badge/license-MIT-black?style=flat-square)
![elephant-mem](https://img.shields.io/badge/elephant--mem-v0.1.0--beta.12-black?style=flat-square)
![elephant-wiki](https://img.shields.io/badge/elephant--wiki-v0.1.0--beta.4-black?style=flat-square)
![claude code](https://img.shields.io/badge/claude--code-plugin-black?style=flat-square)
![ci](https://img.shields.io/github/actions/workflow/status/rafapg/elephant-mem/ci.yml?branch=main&style=flat-square&label=ci)

</div>

## what it is

elephant-mem is a personal memory for Claude Code. It accumulates the **facts**,
**people**, **decisions**, and **open loops** from your work sources into a
private knowledge base you can query from any Claude Code session — "what do we
know about Jane Doe", "what did we decide about the billing rewrite", "what's
still open on my plate".

Your knowledge lives as plain **markdown + git** in a bundle directory on your
own machine. It is `cat`-readable, `git diff`-able, and never leaves disk. No
database, no cloud, no embeddings — just files you can read, grep, and version.

## how it works

Three lanes, routed by lifetime, reached through entities:

- **durable facts** — atomic, one claim per file, that stay true over time.
- **open loops** — commitments and action items that eventually close.
- **episodic sources** — the raw provenance every fact was extracted from.

Entities (people, projects, tools, concepts) are the **navigation spine**: facts
hang off them via backlinks, and retrieval walks the entity, not a flat list.

```
my-memory/                     # your bundle (private, git-versioned, off in $HOME)
  knowledge/
    facts/<slug>.md            # atomic durable facts
    entities/<kind>/<slug>.md  # people | org | project | tool | concept | ...
    tracking/loops/<slug>.md   # open loops
    sources/<YYYY-MM>/...       # provenance, one file per source
    index.md  log.md           # derived / episodic ledger
  elephant.json                # owner, languages, timezone, sources
  state/  scripts/  templates/
```

## install

**Prerequisites** — have these on the machine first:

- **Claude Code** (the CLI) — [install guide](https://docs.claude.com/en/docs/claude-code).
- **git** — used to version your bundle.
- **Python 3.10+** — the bundle scripts are stdlib-only, nothing to `pip install`.

**1. Add the marketplace** (this repo hosts it):

```
claude plugin marketplace add rafapg/elephant-mem
```

**2. Install the plugin** (user scope, so it's available in every project):

```
claude plugin install elephant-mem@elephant-mem --scope user
```

The name is `<plugin>@<marketplace>` — here both are `elephant-mem`.

**3. Verify** — run `/plugin` and confirm `elephant-mem` and its `elephant-mem:*`
modes are listed.

**4. Create your bundle** — in any Claude Code session:

```
/elephant-mem:init
```

`init` walks you through creating the bundle (default `~/elephant`), registers a
machine-level pointer to it, seeds your owner entity, and makes the first commit.
Under two minutes to a working bundle.

> **Windows** (no WSL needed): the commands are identical — they run in the Git
> Bash shell Claude Code already uses. See [platforms](#platforms) for the Python
> note.

## the modes

Every mode is namespaced `elephant-mem:<mode>`.

**Auto-invocable** — Claude reaches for these on its own when the conversation
calls for it (you can also invoke them explicitly):

| mode | what it does | invocation |
|---|---|---|
| `query` | recall what's known about a person / project / topic (entity-first) | `/elephant-mem:query <topic>` |
| `briefing` | time-first digest — "what's relevant in the last N days" | `/elephant-mem:briefing` |
| `capture` | save a durable decision reached in the current conversation | `/elephant-mem:capture` |
| `start-day` | morning orientation: agenda + overnight digest + your open loops | `/elephant-mem:start-day` |
| `end-day` | evening wrap: what happened, what's pending | `/elephant-mem:end-day` |
| `ingest` | extract facts from a URL / file / pasted text you want remembered | `/elephant-mem:ingest <source>` |

`ingest` is the one auto-invocable mode that **writes**. Ask for a source to be
remembered and Claude reaches for it; when it reaches for it on its own it first
states what it is about to file and waits for you to accept. Invoking it by name
skips that confirmation. A source merely appearing in the conversation — a
pasted stack trace, a page opened while debugging — is never a trigger.

**Explicit** — deliberate operations you invoke by name (they have side effects
or run unattended):

| mode | what it does | invocation |
|---|---|---|
| `init` | create and register a new bundle (the front door) | `/elephant-mem:init` |
| `catch-up` | scheduled autonomous ingestion of everything new since last run | `/elephant-mem:catch-up` |
| `push-start-day` | post the morning orientation to your Slack self-DM | `/elephant-mem:push-start-day` |
| `ingest-audio` | transcribe a voice recording and ingest it | `/elephant-mem:ingest-audio` |
| `maintain` | resolve conflicts, consolidate, decay, drift-check | `/elephant-mem:maintain` |
| `review` | clear the low-confidence needs-review queue | `/elephant-mem:review` |
| `expand` | propose derived facts, relations, and promotions | `/elephant-mem:expand` |
| `update` | check for a newer release and re-sync bundle scripts/templates | `/elephant-mem:update` |

## integrations

The **core modes need zero connectors** — they operate on the local markdown
bundle alone. Automatic ingestion (`catch-up`, `push-start-day`) is optional and
driven by a `sources` block in `elephant.json`.

Tested integrations, via claude.ai connectors (e.g. Claude Desktop): **Slack**,
**Google Calendar**, **Google Drive**. Any MCP-backed source can be added with
the same shape — see [`docs/integrations.md`](docs/integrations.md) for setup and
the bring-your-own-source contract.

## platforms

Tested on **macOS** and **Linux**. **Native Windows is supported — no WSL
required**: Claude Code on Windows already requires Git for Windows, and its
bundled Git Bash is the shell every command here runs in. You need Python
3.10+ (from python.org or the Microsoft Store); all bundle scripts read and
write files with explicit UTF-8 encoding, so non-ASCII content in your
knowledge is handled the same way on every platform. Core scripts
(`build-index.py`, `validate-okf.py`, `briefing.py`, `state.py`, etc.) are
**Python 3 stdlib only**, no dependencies to install. Windows support is
**community-tested — reports welcome** (the maintainer develops on macOS).
The exception is the optional `ingest-audio` mode: WhisperX is not supported
(and not recommended) on Windows — see its own prerequisites in
[`plugin/skills/ingest-audio/procedure.md`](plugin/skills/ingest-audio/procedure.md).

## privacy

- The bundle is **local and private**. It is created outside this repo, lives on
  your machine, and is git-versioned with **local commits only — never pushed**.
- This repo ships **mechanics only** — the plugin, scripts, and docs. It contains
  no knowledge.
- Never point the plugin at data you can't keep on disk. The bundle can hold
  sensitive material (financials, personnel, private-channel content); treat it
  accordingly and never publish it.

## updating

```
/elephant-mem:update
```

Compares your installed plugin against the published `version` in
[`plugin.json`](plugin/.claude-plugin/plugin.json), shows the update commands if
newer, and — after you update — re-syncs the bundle's copied scripts and
templates. Read modes also nudge you at most once a week when a release is
available; they never update anything on their own.

Updating the plugin is **two** commands, in this order:

```
claude plugin marketplace update elephant-mem
claude plugin update elephant-mem@elephant-mem
```

The first one is easy to miss and it matters. `claude plugin update` does not
read this repo — it reads your **local clone of the marketplace**, a git
checkout of `main` under `~/.claude/plugins/marketplaces/`. Until you refresh
that clone, the CLI will cheerfully report `✓ elephant-mem is already at the
latest version` and name a version older than the badge above. Nothing is
broken and nothing is lagging on the publishing side — your clone is just
behind.

### two plugins, two version cycles

This marketplace ships **two** plugins: `elephant-mem` (the memory) and
`elephant-wiki` (an optional [static wiki](elephant-wiki/) over your bundle).
They are installed separately and **versioned independently** — the wiki changes
far less often, so the two numbers in the badges above drift apart on purpose. A
lower `elephant-wiki` version does not mean it is out of date.

Releases, git tags, and [changelog](CHANGELOG.md) sections track `elephant-mem`;
a wiki bump is noted inside the `elephant-mem` release that shipped it. `update`
only checks `elephant-mem` — update the wiki with
`claude plugin update elephant-wiki@elephant-mem` when a release mentions it.

## docs

- [architecture](docs/architecture.md) — the OKF model, the three lanes, entity
  retrieval, and why markdown + git (and no DB).
- [configuration](docs/configuration.md) — the pointer file, `elephant.json`, and
  operational state.
- [integrations](docs/integrations.md) — Slack / Calendar / Drive setup,
  scheduling the routine, and bring-your-own MCP sources.
- [changelog](CHANGELOG.md).

## license

MIT — see [LICENSE](LICENSE).
