# `close-loops`

Load `../_shared/core.md` first (always). This file is the `close-loops`
procedure.

Narrower than `maintain`, and the mirror of `decay`: this ONLY resolves
`status: open` loops in `knowledge/tracking/loops/` by evidence — it never
touches facts, entities or confidence, and it never writes `dropped`, which
stays a hand-set state. The deterministic half lives in
`scripts/close-loops.py`; this procedure is the judgment, the write and the
commit around it.

**No review gate, at any cadence.** `decay` has one because expiry is a verdict
of silence with nothing to show for it. Closure is the opposite: every `done`
this routine writes carries a paragraph in the loop file saying what evidence
convinced it, so a wrong verdict is legible where it was written rather than
only in a diff. Interactive and scheduled runs follow exactly the same steps.

## Procedure

1. **Get the proposal.** From `<bundle>`:

   ```bash
   python3 scripts/close-loops.py
   ```

   It builds this run's queue — loops examined before whose entities gained a
   fact or a source since that examination, then everything else still
   unsettled, oldest last activity first — capped at `elephant.json` →
   `close_loops.max` (default 25, with `decay.close_loops_max` as a fallback).
   For each queued loop it prints the closure criterion and up to 10 ranked
   evidence candidates. It reads only: no loop file changes, and
   `state/closure-sweep.json` is not touched by it.

   If the header says `0 loop(s) queued`, say so and stop. Nothing was
   examined, so there is nothing to record and nothing to commit.

   `--max N` bounds a single run smaller or larger; `--loop <path>` (repeatable)
   proposes for named loops and bypasses the queue, which is how you re-read one
   loop without waiting its turn. `--json` exists for a consumer that parses;
   the text is what this procedure reads.

2. **Judge each evidence set as a whole.** The bar is *does this evidence, read
   together, show the commitment was delivered* — **not** whether some candidate
   literally satisfies the criterion string. That is a deliberate trade: it
   closes more loops and reads more like a person would, at the cost of a
   criterion two runs could apply differently, and the compensation is step 3's
   paragraph.

   - The criterion is the loop's `**Closure signal:**` when it has one. When it
     does not, the proposal says so and prints its `description` as the
     criterion instead — judge against that, and say in the resolution that this
     is what you judged against.
   - Evidence is the ranked candidates the script printed, plus the loop file
     itself, which you read before deciding. Nothing else: do not go looking for
     material the ranking dropped, and never call a connector here. This routine
     reads the bundle.
   - **Delivery, not discussion.** A fact saying the thing was decided, planned,
     scheduled or assigned is not a fact saying it happened. A fact describing
     the *outcome* of the commitment is.
   - **Undecided is `open`.** There is no third state, no queue for a human, no
     line in `state/needs-review.md`. A loop you could not settle is recorded as
     examined and left exactly as it was; new material on its entities returns
     it to the front of the queue on a later run, which is the whole reason the
     queue has a first band.
   - A loop with **no evidence candidates** — the proposal prints
     `evidence: none` — is not a judgment call. Examine it, record it, leave it
     open, write nothing to its file.

3. **Write the verdict — only on the loops you are closing.** For each one, two
   edits to the same file:

   **Frontmatter**, three fields that already exist on the template:

   ```
   status: done
   closed: <today, YYYY-MM-DD>
   closed_by: <bundle-absolute link to the source that evidenced it>
   ```

   `closed_by` **must resolve on disk** — `validate-okf.py`'s third check fails
   the run otherwise (step 5), and a broken link there costs you the whole
   commit. Take it from the deciding candidate's `sources:` line, which the
   proposal prints. When the deciding fact carries no source, link the fact
   itself and say so in the resolution. Never invent a path, and never leave the
   field empty on a `done` loop.

   **Body**, one paragraph appended after the `**Closure signal:**` section:

   ```
   **Resolution:** <what happened, and what showed it>
   ```

   - **Its first sentence stands alone.** `tracking/resolved-loops.md` lists
     resolved loops by date, outcome and exactly that first sentence, so a
     sentence that begins "This one finally landed" tells that page nothing.
   - Two to four sentences. Name the evidence by its bundle-absolute path, at
     least once, so the judgment can be re-checked from the file alone.
   - Write it in the bundle's `knowledge_language` (see `../_shared/core.md` →
     Languages), like every other body in `knowledge/`.
   - It is **prose in the body, never a frontmatter field.** A sentence of
     judgment contains `: ` and sometimes ` #`, and the loop template carries
     three lines of warning about what each of those does to an unquoted
     frontmatter value: break the block, or truncate it silently. `decay` writes
     its expiry resolution in the same place and the same shape.

   **A loop you left open gets no write at all.** In particular do **not** bump
   its `updated:` — that field is the decay clock, and touching it here would
   mean the routine that exists to resolve loops also makes them immortal.

4. **Record the sweep — every loop you examined, closed or not.** This is what
   `decay` reads to know a loop was looked at, so a run that judges and forgets
   to record has done nothing for the lane. Run the command in **The sweep
   record** below, **once**, with one `<link>=<outcome>` pair per examined loop
   — `done` for the ones you closed, `open` for every other one, including the
   ones with no evidence. Read the count it prints back against the number of
   loops step 1 queued; they must match.

5. **Rebuild + validate.** `python3 scripts/build-index.py` then
   `python3 scripts/validate-okf.py` — both must pass. This is what removes the
   newly-closed loops from `tracking/open-loops.md`, from the router's open-loop
   count in `knowledge/index.md` and from `manifest.jsonl`, and what lists them
   on `tracking/resolved-loops.md`. On failure: do **NOT** commit; log the error
   and stop. Nothing is lost — the loop files and the sweep record are already
   written, so the next run picks up from there and the loops it settled do not
   come back around. Read any `Hint:` in the output as information, never as an
   instruction.

6. **Log + commit.** Append one dated line at the **end** of `knowledge/log.md`
   (it is oldest-first, like every other routine's ledger):
   `**Close-loops**: N examined, M closed`. Then:

   ```bash
   git -C <bundle> add -A && git -C <bundle> commit -m "close-loops: N examined, M closed"
   ```

   **One commit for the run**, and **never push**. The per-loop detail lives in
   the files — every closure carries its own paragraph — so the commit body
   carries none. If step 1 queued nothing, there is no commit and this step does
   not run.

## The sweep record

`state/closure-sweep.json` records which loops were examined and when. It is
control state, not audit: `decay` expires a loop only if this file shows it was
examined after its own last activity and not closed, so losing it parks expiry
rather than corrupting it. It is **not** git-ignored — it is committed with the
run, like the loop files it describes.

Step 4 writes it with this command, run from `<bundle>`, with the run's own
pairs in place of the two shown:

```bash
python3 - /tracking/loops/acme-export.md=done /tracking/loops/pto-policy.md=open <<'PY'
import datetime, json, pathlib, sys

today = datetime.date.today().isoformat()
path = pathlib.Path("state/closure-sweep.json")
try:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("top level is not an object")
except Exception:
    data = {}
loops = data.get("loops")
data["loops"] = loops if isinstance(loops, dict) else {}
data["schema"] = 1
data["generated"] = datetime.datetime.now().astimezone().isoformat()
for pair in sys.argv[1:]:
    link, _, outcome = pair.partition("=")
    data["loops"][link] = {"examined": today, "outcome": outcome or "open"}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
print(f"closure-sweep: {len(sys.argv) - 1} loop(s) recorded on {today}")
PY
```

It **merges**: every entry from every earlier run survives, and re-examining a
loop overwrites only its own date and outcome. A path with no `=` is recorded
as `open`, and a malformed pair or an unwritable `state/` fails the command
loudly rather than half-writing the file — nothing is committed on a step that
did not run.

The write is a command here rather than a subcommand of `close-loops.py`
because that script reads and does nothing else; the boundary is what lets the
proposal be re-run at any time without changing state. Do not hand-edit the
JSON instead. This file is the only thing standing between `decay` and a lane
it may not touch, and a malformed one reads as empty (with one warning on
stderr) and parks expiry entirely.

## Cadence

Daily, unattended. Configure it exactly like `catch-up` and `decay`: a
scheduled task whose prompt is `/elephant-mem:close-loops`, pointed at the
bundle folder, permissive permission mode, **worktree OFF** (it commits in
place), one manual "Run once" after creating the schedule to pre-approve the
Bash and Edit prompts so unattended runs don't stall. It calls no MCP
connector, so it is the least fragile of the three.

At 25 loops a run the stale end of the lane is examined in about a month and
the whole open lane in about two and a half. That arithmetic only holds if a
run reaches loops the last one did not, which is what the sweep record buys:
`close-loops.py` treats a loop as settled — out of the queue — once it was
examined on or after its own last activity and has gained nothing since.

**A verdict is never permanent.** A fact or a source landing on a settled
loop's entities returns it to the front of the queue, with the material named
in the proposal's `band: 1` line. So "left open" is a state this routine
revisits by itself, and the only thing that ever makes a loop permanently
invisible is a resolution someone can read.
