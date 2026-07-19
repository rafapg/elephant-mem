---
name: update
disable-model-invocation: true
description: >
  Check for a newer elephant-mem plugin release and, after the user updates,
  re-sync the bundle's copied scripts/templates from the installed plugin assets.
  Compares the installed plugin version against the published one, shows the
  update command, and never touches knowledge/ or state/. Invoke only when the
  user explicitly asks (elephant-mem:update). Supports a check-only mode.
---

# elephant-mem:update

Keep the plugin and the bundle's copied assets in sync. Two things can drift:
the **installed plugin** (updated via `claude plugin update`) and the **bundle's
own copies** of `scripts/` and `templates/` (written by `init`, so the bundle is
self-contained). This mode reconciles both — it never modifies your knowledge.

**Load `../_shared/core.md` first** to resolve `<bundle>` and `elephant.json`. If
the pointer or `elephant.json` is missing, stop and tell the user to run
`elephant-mem:init`.

## Procedure

### 1. Check for a newer release

- Read the installed plugin version from
  `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` (`version`).
- Fetch the published manifest (WebFetch):
  `https://raw.githubusercontent.com/rafapg/elephant-mem/main/plugin/.claude-plugin/plugin.json`
  and read its `version`.
- Compare as semver. Stamp `<bundle>/state/last-update-check.json`
  (`{"last_checked": "<ISO now>", "latest_seen": "<remote version>"}`) regardless
  of the outcome. If the fetch fails (offline), say so, stamp `last_checked`, and
  stop — don't error out.

Report in the bundle's `conversation_language`:

- **Up to date** → say so and stop (unless the user asked to re-sync assets
  anyway — see step 3).
- **Newer available** → show the version delta, the changelog link
  (`https://github.com/rafapg/elephant-mem/releases`), and the exact command:
  ```
  claude plugin update elephant-mem@elephant-mem
  ```
  Do **not** run it yourself — updating the plugin is the user's action.

**Check-only mode** (user asked to "just check" / "check only"): stop here after
reporting. Do not re-sync assets.

### 2. Wait for the user to update the plugin

The asset re-sync (step 3) reads from `${CLAUDE_PLUGIN_ROOT}/assets/`, which only
reflects the new version **after** `claude plugin update` runs and the plugin
reloads. If a newer version was found, tell the user to run the update command and
re-invoke `elephant-mem:update` to finish the asset sync. If the plugin was
already current, proceed straight to step 3.

### 3. Re-sync bundle assets (scripts + templates only)

Reconcile the bundle's copies with the installed plugin's assets. **Only**
`scripts/` and `templates/` — never `knowledge/`, never `state/`, never
`elephant.json` or `config.md` (those are the user's data/identity).

1. Diff first, show a summary, and **ask before writing** (AskUserQuestion):
   ```
   diff -rq ${CLAUDE_PLUGIN_ROOT}/assets/scripts   <bundle>/scripts
   diff -rq ${CLAUDE_PLUGIN_ROOT}/assets/templates <bundle>/templates
   ```
   Present which files would change / be added. If nothing differs, say the bundle
   is already in sync and stop.
2. On approval, copy the plugin's versions over the bundle's:
   ```
   cp ${CLAUDE_PLUGIN_ROOT}/assets/scripts/*.py   <bundle>/scripts/
   cp ${CLAUDE_PLUGIN_ROOT}/assets/templates/*.md <bundle>/templates/
   ```
   (Copy, don't delete extras the user may have added — surface any bundle-only
   files in the summary instead of removing them.)
3. Re-run the pipeline to confirm the refreshed scripts still validate the
   bundle, then commit **only** the asset changes:
   ```
   python3 <bundle>/scripts/build-index.py
   python3 <bundle>/scripts/validate-okf.py
   git -C <bundle> add scripts templates
   git -C <bundle> commit -m "update: re-sync scripts + templates from plugin assets"
   ```
   Local commit only — never push.

### 4. Recap

Short recap in `conversation_language`: installed vs. published version, whether a
plugin update is pending, and which assets were re-synced (or that everything was
already current).
