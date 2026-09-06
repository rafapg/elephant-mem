---
name: start-day
description: >
  Morning orientation from elephant-mem (read-only). Use when the user starts
  their day / asks "what's on today" / wants a morning briefing: today's
  agenda + overnight digest of decisions and new facts + their open loops.
  Answers in the bundle's conversation_language.
---

<!-- Path resolution: pass the worker BOTH absolute paths, built from
     ${CLAUDE_PLUGIN_ROOT} (the plugin's own convention, see init/update
     skills). The harness substitutes this when the skill loads, resolving it
     regardless of the main agent's or the subagent's cwd: procedure.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/start-day/procedure.md and core.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md. Effort: the Agent tool has
     no reasoning-effort/thinking param today, so the worker inherits the
     session's effort — no override is set here. -->

# elephant-mem:start-day

This skill runs in a subagent to keep the main context clean — do NOT read
the bundle or `core.md` yourself. The preflight is the exception: it runs here,
before the subagent exists.

1. **Preflight, before delegating.** Run, in this agent:

   ```bash
   elephant-update --check
   ```

   Bare, with no `--bundle` — this mode resolves no bundle of its own, so there
   is none to pass and the check resolves the same machine pointer the worker
   will. Then read the exit code and nothing else (the four outcomes are in
   `_shared/core.md`'s **Preflight** section):

   - **`1` — stop here.** Do not spawn the subagent; the orientation does not
     run, and neither does its update-check stamp. Relay the check's stderr,
     which already names the drifted files and both routes out
     (`elephant-update` in a terminal, `elephant-mem:update` from inside Claude
     Code), in the bundle's `conversation_language` — the pointer at
     `~/.config/elephant-mem/config.json` and `<bundle>/elephant.json` are the
     only files this agent ever opens, and only to relay this.
   - **`0`** — proceed, saying nothing.
   - **`2`, or any other result** — a command not found, a crash, a code no
     version documents — proceed, and hold the check's one line for step 3.

   It runs here and not in the worker because step 3 relays the worker verbatim
   as the morning orientation: a stop printed there would reach the user dressed
   as the orientation.

2. Spawn a subagent with the Agent tool: `subagent_type: "elephant-worker"`,
   `model: "sonnet"`. Give it this prompt:
   "Run the elephant-mem start-day procedure. First load
   `${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md` (the harness
   substitutes this path), then open and follow the
   procedure at `${CLAUDE_PLUGIN_ROOT}/skills/start-day/procedure.md` exactly.
   start-day takes no user arguments. Do every bundle read, the briefing
   script run, the update-check state write, and the closing
   `scripts/recall.py log` call yourself, in your own context. Return ONLY
   the final user-facing answer in the bundle's conversation_language,
   exactly as the procedure's Final answer section specifies. The preflight
   already ran in the main agent — do not run `elephant-update --check`
   yourself."
3. Relay the subagent's final message to the user verbatim. Add nothing beyond
   step 1's one line, when the preflight left one.
