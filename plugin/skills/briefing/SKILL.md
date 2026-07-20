---
name: briefing
description: >
  Time-first digest from elephant-mem (read-only). Use when the user asks
  "what's relevant that I might be missing?" over a time window — e.g.
  "everything in Slack the last 2 days", "what was decided in the team's
  meetings last week". Complements entity-first query. Answers in the bundle's
  conversation_language.
---

<!-- Path resolution: pass the worker BOTH absolute paths, built from
     ${CLAUDE_PLUGIN_ROOT} (the plugin's own convention, see init/update
     skills) — this resolves regardless of the main agent's or the
     subagent's cwd: procedure.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/briefing/procedure.md and core.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md. If CLAUDE_PLUGIN_ROOT is
     unset, ask the user where the plugin is installed rather than guessing.
     Effort: the Agent tool has no reasoning-effort/thinking param today, so
     the worker inherits the session's effort — intended effort for briefing
     is HIGH (heavy time-window synthesis); set it explicitly here if the
     Agent tool ever gains that field. -->

# elephant-mem:briefing

This skill runs in a subagent to keep the main context clean — do NOT read
`core.md`, the bundle, or run any scripts yourself.

1. Spawn a subagent with the Agent tool: `subagent_type: "elephant-worker"`,
   `model: "sonnet"`. Give it this prompt: "Run the elephant-mem briefing
   procedure. First load `${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md`
   (resolve `${CLAUDE_PLUGIN_ROOT}` from the environment), then open and
   follow the procedure at
   `${CLAUDE_PLUGIN_ROOT}/skills/briefing/procedure.md`. Filters from the
   user — time window / channel / tag / entity: <forward exactly what the
   user asked for, e.g. 'last 2 days, Slack only, decisions'>. Do every
   bundle read and script run in your own context. Return ONLY the final
   digest, in the bundle's conversation_language, grouped and cited exactly
   as the procedure requires."
2. Relay the subagent's final message to the user verbatim. Add nothing.
