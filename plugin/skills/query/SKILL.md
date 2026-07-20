---
name: query
description: >
  Recall what elephant-mem knows about X (entity-first retrieval, read-only).
  Use when the user asks to recall / "what do we know about …" / look up a
  person, project, decision, or topic in their personal memory. Answers in the
  bundle's conversation_language with provenance (cited fact + source files).
---

<!-- Path resolution: pass the worker BOTH absolute paths, built from
     ${CLAUDE_PLUGIN_ROOT} (the plugin's own convention, see init/update
     skills) — this resolves regardless of the main agent's or the
     subagent's cwd: procedure.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/query/procedure.md and core.md at
     ${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md. If CLAUDE_PLUGIN_ROOT is
     unset, ask the user where the plugin is installed rather than guessing. -->

# elephant-mem:query

This skill runs in a subagent to keep the main context clean — do NOT read the
bundle or `core.md` yourself.

1. Spawn a subagent with the Agent tool: `subagent_type: "elephant-worker"`,
   `model: "sonnet"`. Give it this prompt: "Run the elephant-mem query
   procedure. First load `${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md`
   (resolve `${CLAUDE_PLUGIN_ROOT}` from the environment), then open and
   follow the procedure at `${CLAUDE_PLUGIN_ROOT}/skills/query/procedure.md`.
   The user's question is: `<the user's verbatim question/topic>`. Do every
   bundle read in your own context. Return ONLY the final user-facing answer
   in the bundle's `conversation_language`, with provenance exactly as the
   procedure requires."
   <!-- Effort: medium intended. The Agent tool has no reasoning-effort/thinking
        param today, so the worker inherits the session's effort setting. -->
2. Relay the subagent's final message to the user verbatim. Add nothing.
