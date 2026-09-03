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
the bundle, `core.md`, or run `scripts/briefing.py` yourself.

1. Spawn a subagent: `subagent_type: "elephant-worker"`, `model: "sonnet"`,
   prompt: "Run the elephant-mem end-day procedure. First load
   `${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md` (resolve
   `${CLAUDE_PLUGIN_ROOT}` from the environment), then open and follow the
   procedure at `${CLAUDE_PLUGIN_ROOT}/skills/end-day/procedure.md`. Do
   every bundle read, the `scripts/briefing.py` run and the closing
   `scripts/recall.py log` call yourself, in your own context. Apart from that
   one git-ignored `state/` line you MUST NOT write anything, and you MUST NOT
   invoke or route to `capture`. Return only: (a) the digest (what happened
   today + what's pending) and (b) a short suggestion of what from today might
   be worth capturing."
2. Relay the subagent's digest (a) to the user verbatim — add nothing.
3. Back in this main agent (not the subagent), ask the user whether there's
   anything from the day worth capturing that automated ingestion wouldn't
   have caught — offer the subagent's suggestion (b) as a prompt, not a
   verdict. On yes, route to the `capture` skill exactly as today. This is
   the only step in this mode that may write knowledge, and only on the
   user's say-so.
