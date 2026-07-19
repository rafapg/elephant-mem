# elephant-mem (personal memory)

The `elephant-mem` plugin is installed on this machine. The user keeps a private,
local **memory bundle** — durable facts, open loops, and episodic sources as
plain markdown + git. Locate it via the pointer at
`~/.config/elephant-mem/config.json` (`bundle_path`). If that file is missing,
the user hasn't run `elephant-mem:init` yet — suggest it, don't guess a path.

- When the user asks to recall a person, project, decision, or topic ("what do
  we know about…", "remind me about…") → use `elephant-mem:query` (entity-first)
  or `elephant-mem:briefing` (time-first, "what's relevant lately").
- When the user reaches a durable decision in conversation (an architecture,
  product, or process call, or a commitment with follow-up) → offer
  `elephant-mem:capture` **once**, then proceed only if they accept. Don't nag.
- The bundle holds sensitive private data and is **local-only**: never publish,
  push, or paste its contents anywhere external.

All modes are namespaced `elephant-mem:<mode>`. Run `elephant-mem:init` to create
a bundle, `elephant-mem:update` to check for a newer plugin release.
