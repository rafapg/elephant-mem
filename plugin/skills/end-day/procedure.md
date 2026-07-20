# `end-day` procedure

Load `../_shared/core.md` first (always). This file is the `end-day`
procedure — it runs the **read/synthesis half** of the mode inside a
disposable subagent. Obey **Retrieval trust** in `../_shared/core.md`.

Read-only synthesis, in the bundle's `conversation_language`:

1. **What happened today.** `scripts/briefing.py --days 1`; surface decisions
   made and open-loops opened/closed today, grouped by channel.
2. **What's left pending.** The owner's (`elephant.json` → `owner.slug`)
   `open` loops touched or opened today, plus any still-open commitment with
   an imminent closure signal.
3. **Return — do not write, do not capture.** You are running inside a
   disposable subagent. The interactive "want to capture anything?" dialogue
   is NOT part of this procedure — it happens back in the main agent, which
   you cannot reach. You **MUST NOT** write anything to the bundle and
   **MUST NOT** invoke or route to `capture` yourself. Your final message is
   everything the caller gets back, so it must contain exactly two parts, in
   the bundle's `conversation_language`:
   - **The digest** — the full synthesis from steps 1–2 (what happened +
     what's pending), written ready to relay to the user verbatim.
   - **Capture suggestion** — a short (1–3 bullet) note on what from today
     looks worth capturing that automated ingestion wouldn't have caught (a
     decision made in a dev session, a verbal commitment). This is a
     suggestion for the main agent to put to the user — not a capture, and
     not a decision.
