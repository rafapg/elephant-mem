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
     skills) — this resolves regardless of the main agent's or the
     subagent's cwd: procedure.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/start-day/procedure.md and core.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md. If CLAUDE_PLUGIN_ROOT is
     unset, ask the user where the plugin is installed rather than guessing.
     Effort: the Agent tool has no reasoning-effort/thinking param today, so
     the worker inherits the session's effort — no override is set here. -->

# elephant-mem:start-day

This skill runs in a subagent to keep the main context clean — do NOT read
the bundle or `core.md` yourself.

1. Spawn a subagent with the Agent tool: `subagent_type: "elephant-worker"`,
   `model: "sonnet"`. Give it this prompt:
   "Run the elephant-mem start-day procedure. First load
   `${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md` (resolve
   `${CLAUDE_PLUGIN_ROOT}` from the environment), then open and follow the
   procedure at `${CLAUDE_PLUGIN_ROOT}/skills/start-day/procedure.md` exactly.
   start-day takes no user arguments. Do every bundle read, the briefing
   script run, and the update-check state write yourself, in your own
   context. Return ONLY the final user-facing answer in the bundle's
   conversation_language, exactly as the procedure's Final answer section
   specifies."
2. Relay the subagent's final message to the user verbatim. Add nothing.
