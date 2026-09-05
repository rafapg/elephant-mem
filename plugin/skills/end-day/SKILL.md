---
name: end-day
description: >
  Evening wrap from elephant-mem (read-only + optional capture). Use when the
  user ends their day / wants an end-of-day review: what happened today,
  what's left pending, and a prompt to capture anything worth remembering.
  Answers in the bundle's conversation_language.
---

<!-- Path resolution: pass the worker BOTH absolute paths, built from
     ${CLAUDE_PLUGIN_ROOT} (the plugin's own convention, see init/update
     skills) — this resolves regardless of the main agent's or the
     subagent's cwd: procedure.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/end-day/procedure.md and core.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md. If CLAUDE_PLUGIN_ROOT is
     unset, ask the user where the plugin is installed rather than guessing.
     Effort: neither the Agent tool nor the `elephant-worker` agent
     definition exposes a reasoning-effort/thinking parameter, so "high
     effort" is a target we can't force here — the worker inherits whatever
     effort level the current session is already running at. -->

# elephant-mem:end-day

This skill runs in a subagent to keep the main context clean — do NOT read
the bundle, `core.md`, or run `scripts/briefing.py` yourself. The preflight is
the exception: it runs here, before the subagent exists.

1. **Preflight, before delegating.** Run, in this agent:

   ```bash
   elephant-update --check
   ```

   Bare, with no `--bundle` — this mode resolves no bundle of its own, so there
   is none to pass and the check resolves the same machine pointer the worker
   will. Then read the exit code and nothing else (the four outcomes are in
   `_shared/core.md`'s **Preflight** section):

   - **`1` — stop here.** Do not spawn the subagent, and do not open step 4's
     capture dialogue: a mode that cannot read the day must not offer to write
     it. Relay the check's stderr, which already names the drifted files and
     both routes out (`elephant-update` in a terminal, `elephant-mem:update`
     from inside Claude Code), in the bundle's `conversation_language` — the
     pointer at `~/.config/elephant-mem/config.json` and
     `<bundle>/elephant.json` are the only files this agent ever opens, and
     only to relay this.
   - **`0`** — proceed, saying nothing.
   - **`2`, or any other result** — a command not found, a crash, a code no
     version documents — proceed, and hold the check's one line for step 3.

   It runs here and not in the worker because step 3 relays the worker verbatim
   as the digest: a stop printed there would reach the user dressed as the
   day's wrap.

2. Spawn a subagent: `subagent_type: "elephant-worker"`, `model: "sonnet"`,
   prompt: "Run the elephant-mem end-day procedure. First load
   `${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md` (resolve
   `${CLAUDE_PLUGIN_ROOT}` from the environment), then open and follow the
   procedure at `${CLAUDE_PLUGIN_ROOT}/skills/end-day/procedure.md`. Do
   every bundle read, the `scripts/briefing.py` run and the closing
   `scripts/recall.py log` call yourself, in your own context. Apart from that
   one git-ignored `state/` line you MUST NOT write anything, and you MUST NOT
   invoke or route to `capture`. The preflight already ran in the main agent —
   do not run `elephant-update --check` yourself. Return only: (a) the digest
   (what happened today + what's pending) and (b) a short suggestion of what
   from today might be worth capturing."
3. Relay the subagent's digest (a) to the user verbatim — add nothing beyond
   step 1's one line, when the preflight left one.
4. Back in this main agent (not the subagent), ask the user whether there's
   anything from the day worth capturing that automated ingestion wouldn't
   have caught — offer the subagent's suggestion (b) as a prompt, not a
   verdict. On yes, route to the `capture` skill exactly as today. This is
   the only step in this mode that may write knowledge, and only on the
   user's say-so.
