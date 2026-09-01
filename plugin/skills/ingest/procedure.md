# `ingest <source> [--review]`

Load `../_shared/core.md` first (always). This file is the `ingest` procedure.
It touches entities — also load `../_shared/entity-resolution.md`.

`<source>` may be a URL, a local file path, or pasted text. Default is
**autonomous**; `--review` adds a human approval gate (see below).

0. **Confirm scope before writing.** This step exists because this skill is
   model-invocable and it writes: it creates files, rebuilds the index, and
   commits. **Skip it** when the user invoked the skill by name
   (`/elephant-mem:ingest <source>`) or named both the source and the intent to
   file it ("ingest this thread", "save that doc to memory") — the ask *is* the
   confirmation. Otherwise, when **you** reached for this skill, state in one or
   two lines what you are about to do — the source you identified, the kind of
   facts you expect from it, and that it writes to the bundle and commits — then
   **wait**.

   Proceed only on an accept. Silence, a topic change, or a hedge is **not** an
   accept: drop the offer and carry on with whatever the user was actually
   doing. **One offer per source per conversation** — a decline holds for the
   rest of the session; do not re-offer the same source in different words.

   Do not read the source, fetch the URL, or write anything before the accept.
   The negative triggers in `SKILL.md` are not softened by this gate — a pasted
   stack trace or a page opened during a dev task is not offered at all, it is
   simply not a source.

   **Automated callers skip this step:** `catch-up` reuses only the core loop
   (steps 2–6) under its own autonomy envelope, and `ingest-audio` enters at
   step 1 with a recording the user already handed over.

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
3. **Resolve entities against the roster.** For each candidate, identify the
   entities it concerns. Before you resolve the first one, read
   `knowledge/entities/roster.tsv` once and hold it — one tab-separated row per
   active entity (`slug`, `kind`, `title`, `aliases` comma-joined, a
   `#`-prefixed header first), the whole bundle in a single read. That roster is
   the resolution surface for the rest of the run.

   **Resolve in context.** Match the name as the source wrote it against `title`
   first, then `aliases`; the row reconstructs the path on its own —
   `/entities/{kind}/{slug}.md`. Do not grep per candidate name and do not open
   `entities/*.md` to decide a match; open an entity file only when you need its
   body (attributes, timeline), never to confirm one. When a short name matches
   more than one row, the candidate's own context (speaker, meeting or channel,
   topic) decides it; when that still leaves it genuinely ambiguous, do not
   guess — see `../_shared/entity-resolution.md`.

   **No row is a miss, and a miss goes on the record.** Create the stub from
   `templates/entity.md` only after the roster gave you nothing, and carry with
   it, into this run's `log.md` entry (step 8), one line naming what you
   actually searched:

   ```text
   roster miss: "<name as written>" (checked: <the variants you matched>)
   ```

   That line is what makes the invented-entity failure countable
   (`grep -c 'roster miss' knowledge/log.md`); a stub filed without it looks
   exactly like a resolution that worked.

   **Append the new entity's row to the roster you are holding, immediately** —
   before the next candidate is resolved. The file on disk is only regenerated
   at step 8, so until then the in-context copy *is* the roster, and two
   candidates naming the same new person in one run must land on one entity, not
   two.

   **A missing or stale roster degrades, it never fails.** Check freshness
   before you read: `git -C <bundle> status --porcelain` empty means the last
   mode finished its rebuild-and-commit step, so the roster is current. Not
   empty, or the file absent, run `python3 scripts/build-index.py` once — it is
   idempotent and step 8 runs it anyway — then read it. If it is still absent,
   fall back to `entities/index.md` (the full catalog, far heavier, same names)
   and say so in this run's `log.md` entry. Never test freshness by modification
   time; `../_shared/entity-resolution.md` says why it lies here.
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
   commit only — never push.** After the commit lands, fire the lifecycle
   event: `python3 scripts/run-hooks.py post_ingest --trigger ingest`.
   Best-effort — subscribers (e.g. the wiki generator) regenerate here; a hook
   failure never fails the ingest.
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
