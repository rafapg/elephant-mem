---
name: update
disable-model-invocation: true
description: >
  Run the whole update path from inside Claude Code: refresh the marketplace
  clone, update the installed plugins of the elephant-mem family, and re-sync
  this bundle's copied scripts/ and templates/. Shows the plan, asks once in the
  conversation, then calls `elephant-update` — the same executable a terminal
  runs. It rewrites the derived files under knowledge/ and stamps state/, and
  never touches a hand-written fact, loop or source, nor elephant.json,
  config.md or vocab.json. Invoke only when the user explicitly asks
  (elephant-mem:update). Supports a check-only mode.
---

# elephant-mem:update

A bundle carries its own copy of the plugin's `scripts/` and `templates/` so it
runs standalone, and keeping that copy current is a separate act from updating
the plugin. This mode is one of the two ways to do both at once. The other is
`elephant-update` in a terminal, and they are the same thing: **this mode is a
caller of that executable**, not a procedure of its own.

What the mode adds is the one part the executable cannot do from here: the
confirmation happens **in the conversation**, where the user is, instead of on a
stdin a tool call does not have. Everything else belongs to the run — the
marketplace refresh, the per-plugin install, the copy, the index rebuild, the
validation, the commit, the stamp, and the launcher.

That is also what removed this mode's old two-visit shape. It used to read
`${CLAUDE_PLUGIN_ROOT}/assets/` and copy from there, which only reflects a new
release **after** the plugin reloads, so it could do nothing but tell the user to
run `claude plugin update` and re-invoke it. The run installs the plugin itself
and then re-reads Claude Code's registry for the directory the install just
wrote, so the copy never depends on what this session has loaded. One invocation
finishes the path.

**Load `../_shared/core.md` first** to resolve `<bundle>`, `elephant.json` and
`conversation_language`. If the pointer or `elephant.json` is missing, stop and
tell the user to run `elephant-mem:init`.

**This mode does not run the preflight.** core.md's **Preflight** section names
`elephant-mem:update` and `init` as its two exceptions, and this is the reason:
the preflight stops a mode on required-set drift and names this mode as a way
out, so running it here would block the repair on the very drift it repairs.
Drift is the expected state when someone invokes this mode, and the run reports
it file by file anyway.

## Procedure

Call the executable **by name** — it ships inside the plugin at `<plugin>/bin/`,
which is on the PATH of every process Claude Code spawns:

```bash
elephant-update --plan
```

If the name is not found, run the file with an interpreter: try `python3`, then
`python`, then `py -3` (in that order — `python3` often isn't on PATH on
Windows), and use `<python> ${CLAUDE_PLUGIN_ROOT}/bin/elephant-update` with the
same flags for the rest of the session.

Add `--bundle <bundle>` to **both** invocations below whenever the bundle you
resolved is not the one the machine pointer names, so the plan the user approves
and the run that follows are about the same bundle.

### 1. Show the plan

`--plan` refreshes the marketplace clone (`claude plugin marketplace update
elephant-mem`), reads the installed and the published versions off it, and
prints the version delta and the file-level plan. It installs nothing, copies
nothing, commits nothing and stamps nothing, which is what makes it safe to show
before asking. It exits `0`. Relay what it printed in `conversation_language`.

**The refresh comes first, and that ordering is the point.** `claude plugin
update` reads the version from the user's local clone of the marketplace
(`~/.claude/plugins/marketplaces/elephant-mem`, a git checkout tracking `main`),
not from the published repo. Read the delta off a stale clone and it can report
"current" about a release that exists — the contradiction where this mode
announces a new version and the CLI answers `✓ elephant-mem is already at the
latest version (<older>)`. If the user reports exactly that, the diagnosis is
the stale clone every time, **not** a lag between the repo and a published
catalog. The run refreshes before it reads, so the delta it shows is true.

**Check-only** (the user asked to "just check" / "check only"): stop here after
reporting. `--plan` has already written nothing beyond the refreshed clone.

### 2. Ask once

Ask in the conversation (AskUserQuestion), in `conversation_language`, showing
what the plan said would change: the version delta and the files that would be
installed or updated in the bundle.

If the user declines, stop. Nothing is installed and nothing is copied. The
refreshed clone stays as it is, which is deliberate and harmless.

### 3. Run it

On approval:

```bash
elephant-update --yes --no-refresh
```

- **`--yes`** because the question was asked and answered in the conversation.
  The run's own prompt reads EOF as a decline, so an invocation without it from
  a tool call declines silently and copies nothing.
- **`--no-refresh`** because step 1 already refreshed the clone. A second
  refresh could move it between the plan and the run, and then the delta that
  gets installed is not the delta the user approved.

### 4. Read the exit code

| code | outcome | what to report |
|---|---|---|
| `0` | the run finished | what moved, what was copied, the commit, the stamp, any restart |
| `4` | declined | nothing installed, nothing copied — unexpected with `--yes`, so say so |
| `5` | failed before the copy | the refresh or a plugin install failed; **the bundle is untouched** |
| `6` | failed after the copy | the copy is on disk and unvalidated; nothing committed, nothing stamped |

On `6`, relay the validator's own output and the git commands the run printed:
they cover `knowledge`, `scripts` and `templates`, because the index rebuild
touched files the copy did not. The run does not roll back — the bundle is a git
repository, so the undo already exists and belongs to the user. Say that the
next preflight will report drift, which is true, and that both routes out still
work.

### 5. Recap

Short recap in `conversation_language`, from what the run printed:

- **Versions**: which plugins of the family moved, and from what to what.
- **Files**: what was installed or updated in `<bundle>/scripts/` and
  `<bundle>/templates/`, and whether a commit was made.
- **Already in sync**: when there was nothing to copy and nothing staged, no
  commit is attempted and that is **not** a failure. The run still stamps
  `state/last-update-check.json`, which holds the weekly update nudge for a week.
- **Restart**: when a plugin was installed, the run says Claude Code must be
  restarted to load it. Pass that on, and be precise about what is waiting on
  it: the bundle is fully updated, since the copy came from the newly installed
  directory on disk, but the skills **this session** is running are still the
  old ones.
- **Launcher**: the run rewrites `~/.local/bin/elephant-update` last and then
  verifies it instead of asserting it works. One that will not run is reported
  and the run still exits `0`; relay the fallback line, and the `export PATH=...`
  line when the directory is not on the user's PATH. Never pass
  `--install-launcher` from here — that flag is `init`'s, for a stage that
  installs nothing else, and the full run has already done it.

## What the run writes, and what it never touches

Writes, inside the bundle:

- `<bundle>/scripts/` and `<bundle>/templates/` — the files the two plugins
  publish. `elephant-mem`'s set is required and is copied in full; the wiki's
  three files are optional and are updated only where the bundle already has
  them. A bundle file neither plugin ships is left alone rather than removed.
- the derived files under `knowledge/` that `build-index.py` rewrites (entity hub
  blocks, archive shards, the manifest).
- one **local** commit covering `knowledge`, `scripts` and `templates` — never a
  push.
- `<bundle>/state/last-update-check.json`, the gitignored stamp, and only on a
  run that validated.

Never:

- a hand-written fact, loop or source under `knowledge/`.
- `elephant.json`, `config.md` or `vocab.json` — the bundle's own data and
  identity, and `vocab.json` is a vocabulary the owner may have extended.

That list replaces the one this mode used to state, "never `knowledge/`, never
`state/`", which was untrue on both halves and untrue in this file: the old step 1
stamped `state/last-update-check.json` itself, and the re-sync it performed ran
`build-index.py` and then committed `scripts` and `templates` alone, leaving the
`knowledge/` rewrite dirty for whatever routine next ran `git add -A`. The run
rewrites those derived files on purpose and commits them with the copy that
caused them. What it never writes is anything a person wrote.
