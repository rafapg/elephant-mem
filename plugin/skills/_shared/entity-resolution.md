# elephant-mem — entity resolution

Shared entity-resolution method. Any mode that creates, matches, or reconciles
entities loads this (in addition to `core.md`). Covers correcting
transcription errors and the anti-contradictory-fact rule.

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
resolution is genuinely uncertain, surface it rather than guess silently.

## Contradiction with an already-instantiated entity

**Contradiction with an already-instantiated entity → consolidate/review,
never a new "fact".** If a candidate contradicts the attributes or timeline of
an entity that already exists and is active (e.g. it claims something is *new*
when an instance is already present — a "new joiner" whose entity has been
active for weeks), do not persist it as an `active` fact linked provisionally
to that entity. Treat it as a `**Conflict**` (or queue it to review) and
reconcile. A fact that is internally self-contradictory, or that contradicts
the very entity it links, is not a fact.
