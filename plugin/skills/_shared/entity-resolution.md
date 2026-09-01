# elephant-mem — entity resolution

Shared entity-resolution method. Any mode that creates, matches, or reconciles
entities loads this (in addition to `core.md`). Covers the roster every
resolution runs against, the no-invention rule and its record, correcting
transcription errors, and the anti-contradictory-fact rule.

## The roster is the resolution surface

`knowledge/entities/roster.tsv` is where a name becomes an entity: one
tab-separated row per **active** entity — `slug`, `kind`, `title`, `aliases`
(comma-joined) — behind a single `#`-prefixed header line. It is derived, and
`build-index.py` rewrites it from disk at whatever step the mode rebuilds. A
mode that resolves entities reads it **once, before the first candidate is
resolved**, and holds it for the rest of the run; everything below assumes that
copy is in hand.

**Resolve in context, not on disk.** Match the name as the source wrote it
against `title` first, then `aliases`. The row reconstructs the path on its
own — `/entities/{kind}/{slug}.md` — so a match the roster carries costs no
tool call at all. Do not grep per candidate name, and do not open an
`entities/*.md` file to decide a match; open one only when you need its body
(attributes, timeline), never to confirm an identity the roster already settled.

**Ambiguity is surfaced, never guessed.** When a short name matches more than
one row, the candidate's own context decides it — who said it, which meeting or
channel, what was being discussed — because nicknames are speaker- and
context-dependent (below). When the context does not settle it, do not pick the
likelier row and move on. Leave the item unlinked, write it with
`confidence: low` and the `needs-review` tag, append its line to
`state/needs-review.md` naming **both** candidates as the open question, and
carry one line into this run's `log.md` entry:

```text
roster ambiguous: "<name as written>" → <slug>, <slug>
```

The tag and the queue line are one unit; never write one without the other.

**No row is a miss, and a miss goes on the record.** A name the roster does not
carry is the only case that creates an entity, and creating one costs a line in
this run's `log.md` entry naming what you actually searched:

```text
roster miss: "<name as written>" (checked: <the variants you matched>)
```

Both lines are greppable on purpose — `grep -c 'roster miss' knowledge/log.md`
is how the invented-entity failure gets counted, and a stub filed without its
line looks exactly like a resolution that worked. Append the new entity's row
to the roster you are holding **immediately**, before the next candidate is
resolved: the file on disk is only regenerated at the mode's rebuild step, so
until then the in-context copy *is* the roster, and two candidates naming the
same new person in one run must land on one entity, not two.

**A missing roster degrades, it never fails.** If `roster.tsv` is not there,
run `python3 scripts/build-index.py` once — it is idempotent, and a mode that
writes runs it anyway — then read it. If it is still absent, fall back to
`entities/index.md` (the full catalog, the same names at far greater cost) and
say so in the run's log.

## Correcting transcription errors

Auto-transcripts mangle names (e.g. "Jon Smyth" heard as "John Smith Junior",
or a nickname collapsed onto the wrong person). To fix an entity, use
`scripts/rename-entity.py <old-slug> <new-slug> --title "Name" --alias
<WrongSpelling> [--desc "..."] [--text "OLD=NEW"]`. It moves the file,
rewrites every link, optionally fixes prose, and — crucially — **records the
wrong spelling as an `alias`** so the next ingest resolves it to the right
entity instead of recreating the error. Then rebuild + validate + commit.
Always keep the bad spelling as an alias; that is what makes the correction
stick.

**Nicknames can be speaker- or context-dependent.** The same short name ("JJ",
"Sam") may map to different people depending on who's speaking or which
project the conversation is about — e.g. one team's "JJ" is Jane Johnson, but
in a different meeting's transcript the same token refers to Jamal Jackson.
Don't assume a global default without checking; disambiguate by context (team,
project, topic) the way you would any other ambiguous reference, and when the
resolution is genuinely uncertain, surface it rather than guess silently — the
`roster ambiguous` line and its queue entry, above, are what surfacing it
means.

## Contradiction with an already-instantiated entity

**Contradiction with an already-instantiated entity → consolidate/review,
never a new "fact".** If a candidate contradicts the attributes or timeline of
an entity that already exists and is active (e.g. it claims something is *new*
when an instance is already present — a "new joiner" whose entity has been
active for weeks), do not persist it as an `active` fact linked provisionally
to that entity. Treat it as a `**Conflict**` (or queue it to review) and
reconcile. A fact that is internally self-contradictory, or that contradicts
the very entity it links, is not a fact.
