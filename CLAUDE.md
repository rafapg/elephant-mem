# CLAUDE.md

Context for Claude Code working in this repository.

## What this repo is

The **mechanics** of elephant-mem — the plugin, the bundle scripts, the docs. It
holds no knowledge. A user's knowledge lives in their own bundle directory
outside this repo (default `~/elephant`), git-versioned locally and never pushed.

Two plugins ship from one marketplace (`.claude-plugin/marketplace.json`):

| directory | plugin | what it is |
|---|---|---|
| `plugin/` | `elephant-mem` | the memory itself — the mode-skills, scripts, templates |
| `elephant-wiki/` | `elephant-wiki` | optional static wiki over a bundle, a `post_ingest` subscriber |

## Versioning: two independent cycles

`elephant-mem` and `elephant-wiki` version **separately**. They are distinct
plugins, installed separately, and the wiki changes far less often — as of
`elephant-mem` 0.1.0-beta.7 the wiki is on 0.1.0-beta.3. A gap between the two
numbers is expected and is **not** a sign the wiki is behind.

What follows from that:

- **Bump only the plugin whose files changed.** A change under `plugin/` bumps
  `plugin/.claude-plugin/plugin.json`; a change under `elephant-wiki/` bumps
  `elephant-wiki/.claude-plugin/plugin.json`. A change touching both bumps both.
- **`elephant-mem`'s version is the repo's version.** Git tags (`v0.1.0-beta.N`)
  and GitHub releases track `elephant-mem` alone. There are no `elephant-wiki`
  tags.
- **Each plugin owns its CHANGELOG.** `CHANGELOG.md` at the root is
  `elephant-mem`'s; `elephant-wiki/CHANGELOG.md` is the wiki's. A change under
  `elephant-wiki/` is written up there, in the same house style, and **not** in
  the root file. Since the wiki has no tags, date its section by the day it
  lands on `main` — that is what the marketplace serves.
  - Up to wiki 0.1.0-beta.2 the convention was the opposite: those bumps were
    recorded inline in the `elephant-mem` section that shipped them ("Also in
    this release: …", see 0.1.0-beta.5). That history was left where it is and
    is linked from the wiki's own file; don't move it, and don't add new inline
    notes.
- **Only `elephant-mem`'s version is machine-read.** The `update` mode fetches
  `plugin/.claude-plugin/plugin.json` from `main` and compares it to the
  installed one. Nothing reads the wiki's `version`; it is there for the
  marketplace and for humans. So a forgotten wiki bump is cosmetic, while a
  forgotten `elephant-mem` bump silently withholds the update prompt from every
  installed user.

## Cutting a release

Do this on a branch, land it through a PR, then tag the **merge commit** — the
`v0.1.0-beta.6` tag points at the merge of #5, which is the pattern to follow.

1. **Bump** the `version` in the `plugin.json` of each plugin whose files
   changed (see above).
2. **CHANGELOG** — open or finish the `## [<version>] - <date>` section in the
   CHANGELOG of each plugin that was bumped (root for `elephant-mem`,
   `elephant-wiki/CHANGELOG.md` for the wiki). For `elephant-mem` the date is
   the day the release is **tagged**, not the day the section was started; fix
   it at tag time if the work spanned days. Keep the house style: a short lead
   paragraph saying what was actually wrong, then
   `### Added` / `### Changed` / `### Fixed`.
3. **README** — update the version badge(s) in the centered header block.
4. **Tag and release**, annotated, with a title:

   ```
   git tag -a v0.1.0-beta.N <merge-sha> -m "v0.1.0-beta.N — <short title>"
   git push origin v0.1.0-beta.N
   gh release create v0.1.0-beta.N --title "v0.1.0-beta.N — <short title>" --notes "<the CHANGELOG section>"
   ```

5. **Verify** the tag is reachable from `main` and that CI on `main` is green —
   `update` serves `main`, so an untagged bump still reaches users while a tag
   with no bump reaches no one.

## Conventions

- **Prose over bullets in the CHANGELOG.** Entries explain the failure that
  motivated the change, in the past tense, with the measurement when there was
  one. They read as findings, not as a diff summary.
- **Commits** are conventional (`fix(catch-up):`, `feat:`, `chore:`, `docs:`)
  and the subject states the substance, not the file touched.
- **Everything lands through a PR**, with CI green. `main` is the published
  surface — `update` reads `plugin.json` straight off it.
- **Repo docs are in English** (README, CHANGELOG, `docs/`, skill files), even
  when the conversation is in Portuguese. A bundle's own content follows its
  `conversation_language`.

## Tests

**Not pytest.** Every suite in `tests/` is a standalone script run directly with
`python tests/<name>.py`, exiting non-zero on failure — the scripts under test
are Python 3 stdlib only, and the tests keep that property so CI needs no
install step. Run them all before committing:

```
for t in tests/*.py; do python3 "$t" || echo "FAIL $t"; done
python3 plugin/assets/scripts/validate-okf.py
```

`.github/workflows/ci.yml` lists each suite as **its own step**, across a
3-OS × PyYAML-on/off matrix (the frontmatter parser has two paths; both must
run). **A new suite is not picked up by a glob — add the `- run:` line
explicitly.** `test_backlog.py` shipped in 0.1.0-beta.7 and went a full release
unrun in CI because that line was missing.

Locally you likely have no PyYAML, so you exercise the fallback parser only; the
PyYAML path is covered in CI.
