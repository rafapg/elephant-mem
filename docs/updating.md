# Updating

Two things have to stay current, and they are **not** the same act:

- the **installed plugin** — what Claude Code loads when it starts;
- the **bundle's own copy** of `scripts/` and `templates/` — what actually runs
  when a mode does work, because a bundle is standalone by design (see
  [architecture.md](architecture.md)).

`claude plugin update` refreshes the first and never touches the second. A user
who runs it alone ends up with a new plugin driving old scripts, and nothing used
to notice: one bundle sat four releases behind with `close-loops.py` and
`recall.py` absent from it entirely, so `close-loops` could not start,
`recall.py roll` failed on every hourly `catch-up`, and `decay` had been reading
loops without their fourth activity date.

One command closes that gap, and a preflight in every mode makes it impossible
for the gap to reach a run silently.

```
elephant-update
```

---

## 1. What the command does

It is the whole path in one run, in this order:

1. Resolves the bundle — `--bundle`, then `ELEPHANT_BUNDLE`, then the machine
   pointer at `~/.config/elephant-mem/config.json`.
2. Refreshes your local clone of the marketplace
   (`claude plugin marketplace update elephant-mem`).
3. Reads the installed and published versions **off that refreshed clone** and
   prints the version delta and the file-level plan.
4. Asks once. Declining installs and copies nothing.
5. Runs `claude plugin update <plugin>@elephant-mem -y` for each installed plugin
   of the family.
6. Re-reads Claude Code's registry for the directories the install just wrote.
7. Copies the published files into the bundle.
8. Runs `build-index.py`, then `validate-okf.py`.
9. Commits `knowledge`, `scripts` and `templates` locally, never pushing, and
   stamps the gitignored `state/last-update-check.json`.
10. Rewrites the launcher, verifies it, and reports whether Claude Code needs a
    restart to load a newly installed plugin.

That collapses what used to be three steps across two contexts, the last of them
reachable only from inside Claude Code:

| step | where | what it refreshed |
|---|---|---|
| `claude plugin marketplace update elephant-mem` | shell | the local marketplace clone |
| `claude plugin update elephant-mem@elephant-mem` | shell | the installed plugin |
| `elephant-mem:update` | Claude Code | the bundle's `scripts/` + `templates/` |

The mode is still there and still the right route from inside a session — it just
does not carry a procedure of its own any more (see §5).

**The refresh coming first is the point.** `claude plugin update` reads the
version from your local clone of the marketplace, not from the published repo.
Read the delta off a stale clone and the CLI will report `✓ elephant-mem is
already at the latest version` while naming a version older than the one on
GitHub. Nothing is broken and nothing lags on the publishing side — the clone is
just behind, and the run refreshes before it reads.

### Flags

| flag | what it does |
|---|---|
| *(none)* | the full run above |
| `--check` | the preflight: report drift through the exit code, write nothing |
| `--plan` | refresh the clone, print the delta and the plan, install and copy nothing |
| `--yes` | skip the confirmation, for a caller that already asked |
| `--no-refresh` | reuse the clone as it stands, for the run that follows a `--plan` |
| `--bundle <path>` | operate on that bundle instead of the pointer's |
| `--install-launcher` | write and verify the launcher pair and nothing else |

`--plan` then `--yes --no-refresh` is one approval: the delta you approved is the
delta that gets installed, rather than one a second refresh may have moved
underneath it. That pair is exactly what `elephant-mem:update` runs.

### Exit codes

The run and the check share one code space and stay disjoint above zero, so a
code always says which of the two produced it. The full run's four (`--check`'s
are in §2):

| code | meaning |
|---|---|
| `0` | success (also `--plan`, and a run whose launcher would not run) |
| `4` | declined at the confirmation |
| `5` | failed **before** the copy — the bundle is untouched |
| `6` | failed **after** the copy — nothing committed, nothing stamped |

---

## 2. The preflight — `elephant-update --check`

Every mode except the two that repair drift runs this once the bundle is
resolved and **before doing any work**:

```bash
elephant-update --check                    # the bundle the machine pointer names
elephant-update --check --bundle <bundle>  # the bundle this mode resolved
```

| code | outcome | what the mode does |
|---|---|---|
| `0` | in sync | proceed; the check printed nothing |
| `1` | drift in the required set | **stop**, naming both routes out |
| `2` | drift confined to the wiki's optional files | proceed, passing on its one line |
| anything else | could not verify | proceed, and say verification was not possible |

- **Only required-set drift stops a mode.** Everything else lets the run
  continue, which is what keeps a broken check from stopping everything at once.
- Callers match `0`, `1` and `2` and read **everything else** as
  could-not-verify: that covers `3` (it could not resolve the plugin or the
  bundle) and equally a command that was not found or crashed. Those cannot
  report themselves, so the rule belongs to the caller.
- **`--check` writes nothing at all** — no stamp, no launcher, no comparison
  record in the bundle. It reads both sides off disk every time. A record stored
  in the bundle would be absent from exactly the stale bundles the check exists
  to catch, and would say the right number about files someone has since edited.
- On `1` it names the drifted files and **both** ways out on stderr: run
  `elephant-update` in a terminal, or invoke `elephant-mem:update` from inside
  Claude Code. Both every time, because a blocked user may be one whose shell has
  no launcher yet.

`elephant-mem:update` and `init` never run it: `update` is one of the two routes
out, and `init` is copying assets into a bundle that does not exist yet.

### What is compared

The published set is **named, not swept**, and matched against the plugin
directory the run resolved:

| plugin | files | standing |
|---|---|---|
| `elephant-mem` | `assets/scripts/*.py`, `assets/templates/*.md` | **required** |
| `elephant-wiki` | `assets/scripts/{wiki.py,wiki.js,graph.js}` | **optional** |

- A required file the bundle lacks or holds differently is drift, and a run
  installs it.
- An optional file the bundle **does not have** is not drift and installs nothing
  — a bundle that never built a wiki is not behind. One it does have and holds
  stale is drift a run fixes, but never a stop: the wiki renders the memory, it
  does not run it.
- `elephant-wiki` not being installed is not could-not-verify. With no plugin
  publishing them, wiki files in the bundle are files no plugin ships: ignored.
- Files the bundle holds that **neither** plugin ships are never drift and are
  never touched. Nor is anything else under the plugin's `assets/` — `vocab.json`,
  `elephant-plugin.md` and `seed/` reach a bundle through `init` alone, and a
  `__pycache__/` on a development machine is outside the set rather than
  something a directory listing would compare.
- Comparison **normalises line endings**. Git for Windows checks out CRLF and
  this repo carries no `.gitattributes`, so a byte comparison would report every
  file as drifted on Windows and block every mode there.

---

## 3. Reaching the command from a terminal — the launcher

`elephant-update` ships **inside the plugin**, at `<plugin>/bin/`, which Claude
Code puts on the PATH of every process it spawns (a subagent inherits it). A
login shell carries no plugin directory at all, so a terminal needs a launcher.

It cannot be a symlink: plugins install under
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, so every update
lands in a new directory and the link would dangle at exactly the moment you
updated. The launcher resolves the installed directory **at run time** instead —
it reads Claude Code's registry (`~/.claude/plugins/installed_plugins.json`,
keyed `<plugin>@<marketplace>`, carrying an explicit `installPath` and
`version`), falls back to the cache's highest version compared as **semver in
Python**, and hands off to `<installPath>/bin/elephant-update`. Nothing here ever
picks a version by sorting names in a shell: sorted as text, `0.1.0-beta.9`
follows `0.1.0-beta.13`.

**Where it goes**: `~/.local/bin/elephant-update`, the shell path Git Bash shares
with macOS and Linux. Set `ELEPHANT_BIN_DIR` to put it somewhere else. On Windows
a `.cmd` is written beside it, because Git Bash's `chmod` grants no NTFS execute
permission.

**Neither the launcher nor the executable assumes `python3` is on PATH** — it is
frequently absent on Windows. Both walk `python3`, then `python`, then `py -3`,
and take the first that answers Python 3.10 or newer.

**Two routes write it**, and neither is `--check`:

- `init`, at Stage 9, which asks first because it is writing to your own
  directory rather than to the bundle. Declining is an answer, not an error: you
  give up reaching the command from a terminal and nothing else. It runs
  `elephant-update --install-launcher`, which writes the pair and does nothing
  else at all.
- **every full run**, missing or not. The launcher carries its own copy of the
  resolver, so rewriting it unconditionally is the point: repairing only what
  looks broken would strand every launcher on disk at whatever the registry
  looked like the day it was written.

### If the directory is not on your PATH

The launcher is still written. The run prints the line to add and **never edits a
shell profile**:

```
/Users/jane/.local/bin is not on your PATH, so `elephant-update` will not be found
by name yet. Add it — this never edits a profile for you:
  export PATH="/Users/jane/.local/bin:$PATH"
  (in ~/.zshrc or ~/.bashrc, and on Windows in Git Bash's ~/.bash_profile)
```

On Windows it adds the `cmd.exe` and PowerShell form as well
(`setx PATH "%PATH%;<dir>"`). Until you add it, run the launcher by its full
path, or use `elephant-mem:update` from inside Claude Code.

### If the launcher will not run

The installer **verifies rather than asserts**: it invokes the file once,
immediately after writing it, with `--help`, which exercises the whole chain
(shell → interpreter → resolver → registry → the installed executable) and writes
nothing. Whether the pair is reachable from Git Bash — the shell every Windows
instruction in the [README](../README.md) runs in — cannot be settled by reading
this repository, so nothing here claims it.

When that invocation fails, the run says so and prints the interpreter-and-path
line to use instead, plus the other route out:

```
It does not run here, so use the interpreter and the path instead —
nothing else depends on this file: <what happened>
  python3 /Users/jane/.claude/plugins/cache/elephant-mem/elephant-mem/<version>/bin/elephant-update
  or invoke `elephant-mem:update` from inside Claude Code.
```

**A launcher that will not run does not fail the update.** It is written last, on
purpose — after the copy, the commit and the stamp — so nothing that already ran
depends on it. The run reports it and still exits `0`.

---

## 4. What a run writes, and what it never touches

Writes, inside the bundle:

- `<bundle>/scripts/` and `<bundle>/templates/` — the published files. The
  required set in full; the wiki's three only where the bundle already has them.
  A bundle file neither plugin ships is left alone, never removed.
- the derived files under `knowledge/` that `build-index.py` rewrites (entity hub
  blocks, archive shards, the manifest).
- one **local** commit covering `knowledge`, `scripts` and `templates`. Never a
  push. Nothing staged is not a failure: a bundle already in sync has nothing to
  record, and no commit is attempted.
- `<bundle>/state/last-update-check.json`, the gitignored stamp — see
  [configuration.md](configuration.md#3-operational-state--bundlestate).

Never:

- a hand-written fact, loop or source under `knowledge/`;
- `elephant.json`, `config.md` or `vocab.json` — the bundle's own data and
  identity, and `vocab.json` is a vocabulary you may have extended.

Committing `knowledge` alongside the copy is deliberate. The index rebuild is
caused by the copy, and leaving it dirty hands it to whatever routine next runs
`git add -A`.

### When a run fails

- **`5`, before the copy** — the refresh or a plugin install failed. The bundle
  is untouched and there is nothing to undo.
- **`6`, after the copy** — the copy is on disk and unvalidated. The run commits
  nothing, stamps nothing, prints the validator's own output, and prints the undo:

  ```bash
  git -C <bundle> checkout -- knowledge scripts templates
  git -C <bundle> clean -fd knowledge scripts templates
  ```

  Those cover `knowledge` as well as the copied directories, because an undo
  naming only the copied files would leave the index rewrite in place.

**There is no automatic rollback**, deliberately. Validating before and after the
copy would compare the bundle's old validator against the newly copied one, so a
stricter new release would read as damage the update caused. The bundle is a git
repository, so the reliable undo already exists and belongs to you. The next
`--check` reports drift, which is true, and both routes out still work because
neither depends on anything the failure could have left behind.

The stamp belongs to the success path alone: holding the weekly nudge for a week
over a bundle that has just failed is the one thing it must not do.

---

## 5. From inside Claude Code

```
/elephant-mem:update
```

The same executable, not a second procedure. The mode shows `--plan`, asks in the
conversation (which is the one part the executable cannot do from a tool call
with no stdin), then invokes `--yes --no-refresh` and reports the outcome. It is
also the route for a shell that has no launcher yet.

When a plugin was installed, the run says Claude Code must be **restarted** to
load it. Be precise about what is waiting on that: the bundle is fully updated,
since the copy came from the newly installed directory on disk, but the skills
*this session* is running are still the old ones.

---

## 6. The weekly nudge

Separate from the preflight, and it asks a different question. At most once every
seven days, an interactive mode may compare the installed version against
`plugin.json` on `main` and, when a release exists, print `elephant-update` once
alongside what it covers. It never updates anything on its own.

- The **nudge** is about a newer *release* existing.
- The **preflight** is about the bundle's copy not matching the plugin *already
  installed*.

Either fires without the other, and only the preflight ever stops a mode. Both
point at the same command. The seven-day gate lives in
`state/last-update-check.json`, which a full run stamps too, so a nudge you acted
on goes quiet for a week.
