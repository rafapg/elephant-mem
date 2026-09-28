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
   (steps 2–7) under its own autonomy envelope, and `ingest-audio` enters at
   step 1 with a recording the user already handed over.

1. **Capture provenance.** Read the source fully (WebFetch for URLs, Read for
   files). Create `knowledge/sources/<YYYY-MM>/<YYYY-MM-DD>-<slug>.md` from
   `templates/source.md`: set `resource`, `source-kind`, `channel` (precise
   origin: `slack:#channel`, `meeting`, `email`, `gdoc`…), `occurred` (when the
   event/thread happened — NOT today), and a concise summary (a recall aid, not
   a copy). Optionally save the raw capture to `raw/<context>/<topic>/` (e.g.
   `raw/work/meetings/`) rather than loose at the root — see
   `../../assets/seed/config.md` → **Layout** for the convention.
2. **Extract & route candidates.** Each candidate = one atomic, self-contained
   item; route it to its lane — a durable `fact`, an `open-loop` (a
   commitment the owner owes or is owed, which will complete: see **The loop
   bar** below), or nothing (already episodic).
   Apply **skip-rules** — do NOT extract:
   - trivia, formatting, or the source's own boilerplate;
   - anything that merely restates knowledge already in the bundle;
   - unverifiable speculation presented as fact (unless you mark it `low` and
     say so in the provenance note).

   One exception: a message that delivers, chases, reschedules, reports
   blocked or cancels a commitment that may already be an open loop is not a
   restatement and not chatter. Carry it through steps 3 and 4 as a loop-action
   candidate, even when it yields no fact: step 4 matches it and acts on the
   loop.

   Filter on **signal, not relevance.** The owner may span multiple teams or
   projects, so a distant team's problem may still be an input for their own
   work — keep every durable item from any channel/team and only drop
   ephemeral chatter. **Never skip a durable fact just because it concerns a
   team outside the owner's immediate orbit.** Relevance is applied later (at
   retrieval and at `maintain`'s decay), never at capture. That holds for
   facts. A commitment is routed by its relation to the owner, by the loop bar
   below, and one that fails the bar is still kept, as a fact.

   **The loop bar.** A commitment becomes an `open-loop` only when it clears all
   three filters, strongest first; one that fails any of them is filed as a
   fact, never dropped:

   1. **The owner owes it or is owed it.** "I owe": the owner is the one who
      delivers. "Owed to me": someone else delivers and the owner is the one
      waiting on it. Judge it here on names: the owner by `elephant.json` ->
      `owner.name` and the source's own context (who speaks, who is asked, who
      answers). Being in the same meeting, channel or thread does not count. A
      commitment between other people is a fact, with its people in
      `entities`; `briefing` and `query` still reach it there.
   2. **Its closure is observable.** Write the `**Closure signal:**` as what an
      ingested source would show on delivery: who posts, sends, merges or
      confirms what, and where. If all you can write is "it gets done", it is a
      fact, not a loop.
   3. **It is not already open.** A commitment that may already be an open loop
      is matched in step 4, once its entities are resolved; a match acts on
      that loop instead of filing a new one.
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

   **Resolution confirms the loop lane.** A loop candidate carries the owner's
   entity (`/entities/person/<owner.slug>.md`) in `owner` ("I owe") or in
   `owed_to` ("owed to me", with the other party in `owner`). If resolution
   leaves the owner's entity in neither, the candidate is filed as a fact, its
   people in `entities`. When `owner.slug` is absent from `elephant.json`, or
   names no roster row (a `rename-entity.py` never rewrites `elephant.json`),
   the owner's entity is the row the roster resolves for `owner.name`; say so
   in this run's `log.md` entry. When that resolves nothing either, every
   commitment is filed as a fact and the `log.md` entry says the loop lane was
   skipped for want of an owner entity.
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

   **Open loops.** A loop candidate, and any source that may speak to a
   commitment already in the lane, is matched against the open loops before
   anything is filed.

   - **The match.** Compare against `status: open` loops only: the
     `knowledge/manifest.jsonl` rows with `"type":"open-loop"` whose
     `entities`, `owner` or `owed_to` share a resolved entity with the
     candidate (load only likely matches, as for facts). The bundle owner's
     own entity (`/entities/person/<owner.slug>.md`) does not count as shared:
     every open loop and every loop candidate carries it, so matching on it
     would load the whole lane. Match on the other parties (the counterpart in
     `owner` or `owed_to`) and on the projects in `entities`; a candidate
     naming no one but the owner is compared with the open loops that likewise
     name no one else. Loops filed earlier in this run are matched too: the
     manifest on disk is only rebuilt at the end of the run (step 8 here,
     step 7 in `catch-up`), so hold each loop you file
     with the manifest rows, as the roster is held in step 3. A manifest built
     before this release has no `owner`/`owed_to` keys on its rows; the
     `update` re-sync that installs this release runs `build-index.py`, which
     rewrites it. Same deliverable
     and same parties is the same commitment, and this source acts on that
     loop (below) instead of filing a new one. Sibling tasks (same project,
     distinct deliverables) are separate loops, never merged; when a candidate
     matches two open loops, it acts on the one covering the same deliverable.
     A `done`, `dropped` or `expired` loop is never matched: every terminal
     status is final, so the same commitment raised again opens a new loop,
     which may name its predecessor in its details.
   - **What speaks to a loop.** A source speaks to an open loop when it
     delivers it, chases it, reschedules it, reports it blocked or cancels it.
     Merely naming the same people or the same project is not speaking to it,
     and acting on that would keep every loop of an active project alive
     forever. The **source date** is the source's own date, its `occurred`,
     never today's; for `capture`, the user in the conversation is the source
     and the date is today.
   - **What a source does to it.** One of four actions, decided here and
     written at step 7. An action you are unsure of is not taken: the loop
     stays exactly as it is, since every terminal status is final.
     `catch-up` step 5's write-anyway rule for guessed items does not apply
     to loop actions.
     - **Delivered** -> `status: done`, `closed: <source date>`,
       `closed_by: <the source record step 1 created>`, and a
       `**Resolution:**` paragraph appended at the end of the body, after any
       `**Closure signal history:**` section. Its first sentence stands alone;
       two to four sentences, the evidence named by bundle-absolute path, in
       `knowledge_language`, prose and never frontmatter.
     - **Premise gone** (the counterpart left, the project was cancelled, a
       later decision made it moot) -> `status: dropped`, the same three
       fields, and a `**Resolution:**` citing by path the fact that killed the
       premise. Not for silence, not for doubt: those leave it `open`.
     - **Re-raised without closing** -> `updated:` set to the source's own
       date, only if that is later than its current value: `updated:` is
       never moved backwards, so a late or backfilled source cannot shorten
       the clock `decay` reads. A source with no date bumps nothing. Nothing
       else on the file changes.
     - **Refined** (deadline moved, scope shrank, deliverable changed) ->
       rewrite the `**Closure signal:**` paragraph, append the replaced version
       to `**Closure signal history:**`, and bump `updated:` as above. Nothing
       else is rewritten, `description` included. Never a silent edit.

     The history keeps every replaced criterion with its date and the
     bundle-absolute link of the source that changed it:

     ```markdown
     **Closure signal:** <the current criterion>

     **Closure signal history:**

     - 2026-09-20, from [/sources/2026-09/2026-09-20-standup.md](/sources/2026-09/2026-09-20-standup.md): was "<the replaced criterion, verbatim>"
     ```

     Three rules hold it in shape. The section always sits directly after the
     current `**Closure signal:**` section. The `**Closure signal:**` lead-in
     never appears anywhere else in the body, since `close-loops.py` reads the
     first one it finds. Entries run oldest first, one line per change.
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
   work: always tag a decision `decision`; an action item that clears the loop
   bar (steps 2 and 3) is an `open-loop`, written from `templates/open-loop.md`
   with the owner's entity in `owner` or `owed_to`, and one that fails it is a
   fact; reuse existing tags before inventing new ones. Every loop write step 4
   decided (new loop, close, drop, bump, refine) happens here, so `--review`
   gates them.
8. **Rebuild + validate + log + commit.** Run `build-index.py`, then
   `validate-okf.py`. Append one dated line per created/updated fact and per
   loop closed, dropped, bumped or refined (and any flags) to `knowledge/log.md`
   (newest first). `git add -A && git commit` with a message like
   `ingest: <source slug> (+N facts, ~M updated)`. **Local commit only — never
   push.** After the commit lands, fire the lifecycle event:
   `python3 scripts/run-hooks.py post_ingest --trigger ingest`.
   Best-effort — subscribers (e.g. the wiki generator) regenerate here; a hook
   failure never fails the ingest.
9. **Recap (interactive ingests only).** When the ingest was user-requested (not
   an automated routine), close with a short recap in the bundle's
   `conversation_language`: one paragraph naming the source and the headline,
   then a few bullets of the highlights — key facts/decisions, open-loops
   opened, closed, dropped or refined, notable dedup/correlation with existing
   knowledge, new entities, and anything flagged for review. Not exhaustive —
   just the main points. An automated routine skips this and relies on `log.md`.

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
(new / update / conflict). The batches also show each loop action (new loop,
close, drop, bump, refine, or routed to a fact by the loop bar), so a loop write
is gated like a fact. The user approves, edits the statement/entities, or
discards each. Persist (step 7–8) only what survives review.
