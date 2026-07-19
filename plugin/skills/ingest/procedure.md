# `ingest <source> [--review]`

Load `../_shared/core.md` first (always). This file is the `ingest` procedure.
It touches entities — also load `../_shared/entity-resolution.md`.

`<source>` may be a URL, a local file path, or pasted text. Default is
**autonomous**; `--review` adds a human approval gate (see below).

1. **Capture provenance.** Read the source fully (WebFetch for URLs, Read for
   files). Create `knowledge/sources/<YYYY-MM>/<YYYY-MM-DD>-<slug>.md` from
   `templates/source.md`: set `resource`, `source-kind`, `channel` (precise
   origin: `slack:#channel`, `meeting`, `email`, `gdoc`…), `occurred` (when the
   event/thread happened — NOT today), and a concise summary (a recall aid, not
   a copy). Optionally save the raw capture to `raw/`.
2. **Extract & route candidates.** Each candidate = one atomic, self-contained
   item; route it to its lane — a durable `fact`, an `open-loop` (a
   commitment/action-item that will complete), or nothing (already episodic).
   Apply **skip-rules** — do NOT extract:
   - trivia, formatting, or the source's own boilerplate;
   - anything that merely restates knowledge already in the bundle;
   - unverifiable speculation presented as fact (unless you mark it `low` and
     say so in the provenance note).

   Filter on **signal, not relevance.** The owner may span multiple teams or
   projects, so a distant team's problem may still be an input for their own
   work — keep every durable item from any channel/team and only drop
   ephemeral chatter. **Never skip a durable fact just because it concerns a
   team outside the owner's immediate orbit.** Relevance is applied later (at
   retrieval and at decay), never at capture.
3. **Resolve entities.** For each candidate, identify the entities it concerns.
   Read `knowledge/index.md` and matching `entities/` files (check `aliases`).
   Reuse an existing entity if it matches; create a stub from
   `templates/entity.md` if genuinely new; if the match is ambiguous, pick the
   best and flag it in the log for `maintain`.
4. **Dedup** (5-dimension scoring vs. existing facts — load only likely
   matches): (1) the claim, (2) the why/root, (3) entities + referenced things,
   (4) tags, (5) source overlap.
   - **4–5 dims match** → update the existing fact (merge nuance, bump
     `updated`/`timestamp`, raise `confidence` if now corroborated).
   - **2–3 dims** → create new, add tag `consolidate-candidate`.
   - **0–1 dims** → create new.

   **Cross-source corroboration & precedence:** a fact re-observed in a
   different source is an UPDATE, not a new file — append the new source to
   `sources`, raise `confidence` (independent corroboration), and keep the most
   precise wording. A chat "report" often summarizes a meeting whose transcript
   gets ingested later; expect heavy overlap and merge it. On wording/detail
   conflict, prefer the **primary** source (the meeting transcript / actual
   artifact) over a **secondary** one (a chat summary/report); note which won in
   the provenance line.
5. **Conflict handling.** If a candidate contradicts an existing `active` fact:
   keep **both**, set `relations.contradicts` on each pointing to the other,
   lower `confidence` on the less-supported one, and log a `**Conflict**` entry
   for `maintain`. **Never silently overwrite.**

   For contradictions against an already-instantiated active entity (a candidate
   that contradicts the entity's own attributes/timeline → consolidate/review,
   never a new active fact), see `../_shared/entity-resolution.md`.
6. **Assign confidence.** `high` = explicitly stated by a reliable source or
   corroborated by ≥2 sources; `medium` = single plausible source; `low` =
   inferred, speculative, or uncorroborated.
7. **Persist.** Write facts from `templates/fact.md`. Set each fact's `occurred`
   to the source's event date (NOT today's ingestion date) — time-windowed
   briefings depend on this. Link `entities` and `sources` (bundle-absolute).
   Create/extend entity stubs as needed. Apply **consistent tags** so filters
   work: always tag a decision `decision`, an action item is an `open-loop`
   (not a fact); reuse existing tags before inventing new ones.
8. **Rebuild + validate + log + commit.** Run `build-index.py`, then
   `validate-okf.py`. Append one dated line per created/updated fact (and any
   flags) to `knowledge/log.md` (newest first). `git add -A && git commit` with
   a message like `ingest: <source slug> (+N facts, ~M updated)`. **Local
   commit only — never push.**
9. **Recap (interactive ingests only).** When the ingest was user-requested (not
   an automated routine), close with a short recap in the bundle's
   `conversation_language`: one paragraph naming the source and the headline,
   then a few bullets of the highlights — key facts/decisions, open-loops
   opened or advanced, notable dedup/correlation with existing knowledge, new
   entities, and anything flagged for review. Not exhaustive — just the main
   points. An automated routine skips this and relies on `log.md`.

**Chat channels over a time window** (Slack etc.): treat the whole window
generically — group messages into threads/topics and extract durable facts,
decisions (tag `decision`), and open-loops. Apply skip-rules hard: greetings,
status pings ("back from PTO", "out sick today"), "is the link down?" support
unless it reveals a durable fact, and bot / CI / notifier noise. **Do NOT
special-case any channel's summary/digest bot** — a pre-summarized "report"
message is just one more input, deduped like the rest. The rule must hold for
any channel.

**`--review` variant:** run steps 1–6, then present candidates **in batches of
5–10** showing description, target entities, confidence, and the dedup verdict
(new / update / conflict). The user approves, edits the statement/entities, or
discards each. Persist (step 7–8) only what survives review.
