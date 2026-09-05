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
`core.md`, the bundle, or run any scripts yourself. The preflight is the
exception: it runs here, before the subagent exists.

1. **Preflight, before delegating.** Run, in this agent:

   ```bash
   elephant-update --check
   ```

   Bare, with no `--bundle` — this mode resolves no bundle of its own, so there
   is none to pass and the check resolves the same machine pointer the worker
   will. Then read the exit code and nothing else (the four outcomes are in
   `_shared/core.md`'s **Preflight** section):

   - **`1` — stop here.** Do not spawn the subagent and do not produce a digest.
     Relay the check's stderr, which already names the drifted files and both
     routes out (`elephant-update` in a terminal, `elephant-mem:update` from
     inside Claude Code), in the bundle's `conversation_language` — the pointer
     at `~/.config/elephant-mem/config.json` and `<bundle>/elephant.json` are
     the only files this agent ever opens, and only to relay this.
   - **`0`** — proceed, saying nothing.
   - **`2`, or any other result** — a command not found, a crash, a code no
     version documents — proceed, and hold the check's one line for step 3.

   It runs here and not in the worker because step 3 relays the worker verbatim
   as the digest: a stop printed there would reach the user dressed as the
   digest they asked for.

2. Spawn a subagent with the Agent tool: `subagent_type: "elephant-worker"`,
   `model: "sonnet"`. Give it this prompt: "Run the elephant-mem briefing
   procedure. First load `${CLAUDE_PLUGIN_ROOT}/skills/_shared/core.md`
   (resolve `${CLAUDE_PLUGIN_ROOT}` from the environment), then open and
   follow the procedure at
   `${CLAUDE_PLUGIN_ROOT}/skills/briefing/procedure.md`. Filters from the
   user — time window / channel / tag / entity: <forward exactly what the
   user asked for, e.g. 'last 2 days, Slack only, decisions'>. Do every
   bundle read and script run in your own context, the procedure's closing
   `scripts/recall.py log` call included. Return ONLY the final
   digest, in the bundle's conversation_language, grouped and cited exactly
   as the procedure requires. The preflight already ran in the main agent — do
   not run `elephant-update --check` yourself."
3. Relay the subagent's final message to the user verbatim. Add nothing beyond
   step 1's one line, when the preflight left one.
