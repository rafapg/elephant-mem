#!/usr/bin/env python3
"""Standalone prose-contract suite for the loop lifecycle.

The loop lane's rules are prose, not code: the model reads them in the skill
files and applies them on every ingest path. Nothing executes them, so nothing
fails when a sentence that carries one is lost in an edit. This suite pins the
sentences that carry the contract:

  (a) the ingest core (`skills/ingest/procedure.md`) holds the three filters
      of the loop bar (the owner owes it or is owed it, an observable closure
      signal, a re-mention updates instead of creating) in step 2, the lane
      confirmation on resolved entities in step 3, and the **Open loops**
      block in step 4: the match against `status: open` loops only, the four
      actions (done, dropped, bump, refine), the bump never moving `updated:`
      backwards, and the `**Closure signal history:**` format;
  (b) every loop write happens at step 7, and the `--review` batches show
      each loop action, so the gate gates them too;
  (c) `catch-up`, `capture` and `init` inherit the core instead of carrying
      their own copy of the rules;
  (d) `core.md` and the docs name the writers as they now are, with
      `close-loops` optional and `decay` acting on silence and scope alone;
  (e) the daily routines (`start-day`, `end-day`, `push-start-day`) carry no
      expiry notice;
  (f) no file under `plugin/`, `docs/` or `README.md` still states a rule this
      lifecycle retired.

Every comparison is over whitespace-normalized text, since the prose wraps
mid-phrase. Pure stdlib, Python 3.10+, in the shape of `tests/test_backlog.py`:
PASS/FAIL per check, exit code 0 only if every check passes.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN = REPO_ROOT / "plugin"
SKILLS = PLUGIN / "skills"
DOCS = REPO_ROOT / "docs"

INGEST = SKILLS / "ingest" / "procedure.md"
CATCH_UP = SKILLS / "catch-up" / "procedure.md"
CAPTURE = SKILLS / "capture" / "SKILL.md"
CORE = SKILLS / "_shared" / "core.md"
INIT = SKILLS / "init" / "procedure.md"
SEED_CONFIG = PLUGIN / "assets" / "seed" / "config.md"
ARCHITECTURE = DOCS / "architecture.md"
INTEGRATIONS = DOCS / "integrations.md"
CONFIGURATION = DOCS / "configuration.md"
DAILY_ROUTINES = ("start-day", "end-day", "push-start-day")

# Sentences this lifecycle retired. Each one stated a rule that is no longer
# true: `updated:` has a writer on every ingest path, `capture` is one of them,
# `close-loops` writes `dropped` on evidence, and `decay` no longer waits for
# `close-loops` to examine a loop before expiring it.
RETIRED = (
    "exactly **two** writers",
    "exactly two writers",
    "`capture` is not a writer",
    "`capture` is not one of them",
    "never writes `dropped`",
    "stays a hand-set state",
    "earns `decay`",
    "once `close-loops` has examined",
    "Run `decay` every three days, after it",
)
TEXT_SUFFIXES = {".md", ".py", ".json", ".toml", ".yml", ".yaml", ".txt", ".sh", ".tsv"}

checks = []  # list of (label, passed)


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in detail.splitlines():
            print(f"       {ln}")
    return passed


def flat(text):
    """Collapse every run of whitespace to one space."""
    return " ".join(text.split())


def read(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def rel(path):
    return path.relative_to(REPO_ROOT).as_posix()


def steps(raw):
    """Split a procedure into its top-level numbered steps.

    Returns {number: flattened text of that step}, where a step runs from its
    `N. **` marker at column zero to the next such marker or to the first
    column-zero paragraph after the list. Nested lists are indented, so their
    own `1. **` markers never split a step.
    """
    marks = [(int(m.group(1)), m.start()) for m in re.finditer(r"(?m)^(\d+)\. \*\*", raw)]
    out = {}
    for i, (num, start) in enumerate(marks):
        if i + 1 < len(marks):
            end = marks[i + 1][1]
        else:
            # the last step keeps its indented continuation only
            nl = raw.find("\n", start)
            nxt = re.compile(r"(?m)^\S").search(raw, nl + 1) if nl != -1 else None
            end = nxt.start() if nxt else len(raw)
        out.setdefault(num, flat(raw[start:end]))
    return out


def contains_all(text, needles):
    missing = [n for n in needles if flat(n) not in text]
    return not missing, missing


def check_contains(label, text, needles):
    ok, missing = contains_all(text, needles)
    record(label, ok, "missing: " + ", ".join(repr(m) for m in missing) if missing else "")


def check_absent(label, text, needles):
    present = [n for n in needles if flat(n) in text]
    record(label, not present, "still present: " + ", ".join(repr(p) for p in present))


def test_ingest_core():
    raw = read(INGEST)
    if not record(f"{rel(INGEST)} exists", bool(raw)):
        return
    body = flat(raw)
    st = steps(raw)
    record("ingest/procedure.md has its numbered steps 2 to 9",
           all(n in st for n in range(2, 10)), f"found steps: {sorted(st)}")

    # (a) the three filters of the loop bar, in step 2
    step2 = st.get(2, "")
    check_contains("step 2 routes an open-loop by the loop bar",
                   step2, ["commitment the owner owes or is owed", "**The loop bar**"])
    check_contains("step 2 keeps a commitment that fails the bar, as a fact",
                   step2, ["That holds for facts.", "one that fails the bar is still kept, as a fact"])
    check_contains("the loop bar, filter 1: owed by or to the owner, judged on names",
                   step2, ["owner.name", "same meeting", "A commitment between other people is a fact"])
    check_contains("the loop bar, filter 2: an observable closure signal",
                   step2, ["**Closure signal:**", "what an ingested source would show on delivery",
                           '"it gets done"'])
    check_contains("the loop bar, filter 3: a re-mention is matched in step 4",
                   step2, ["matched in step 4"])

    # step 3 confirms the lane on resolved entities
    step3 = st.get(3, "")
    check_contains("step 3 confirms the lane on links (owner or owed_to, else a fact)",
                   step3, ["/entities/person/<owner.slug>.md", "`owner`", "`owed_to`",
                           "the candidate is filed as a fact"])

    # the **Open loops** block sits in step 4, after its marker and before 5.
    step4 = st.get(4, "")
    record("the **Open loops** block sits in step 4 (after the 4. marker, before 5.)",
           "**Open loops.**" in step4 and "**Open loops.**" not in st.get(5, "")
           and body.find("**Open loops.**") > body.find("4. **Dedup**")
           and body.find("**Open loops.**") < body.find("5. **Conflict"),
           step4[:300])
    check_contains("the match reads status: open loops only, by owner, owed_to and entities",
                   step4, ["status: open", "manifest.jsonl", '"type":"open-loop"',
                           "`entities`, `owner` or `owed_to`"])
    check_contains("the match leaves the owner's own entity out of the shared-entity test, "
                   "which every open loop carries",
                   step4, ["The bundle owner's own entity (`/entities/person/<owner.slug>.md`) "
                           "does not count as shared",
                           "a candidate naming no one but the owner is compared with the open "
                           "loops that likewise name no one else"])
    check_contains("sibling tasks are separate loops, never merged",
                   step4, ["Sibling tasks", "never merged"])
    check_contains("a terminal loop is never matched, so a re-raised commitment opens a new one",
                   step4, ["A `done`, `dropped` or `expired` loop is never matched", "opens a new loop"])
    check_contains("merely naming the same people or project is not speaking to a loop",
                   step4, ["Merely naming the same people or the same project is not speaking to it"])
    check_contains("the source date is the source's own; capture's is today",
                   step4, ["source's own date", "for `capture`", "the date is today"])
    check_contains("the four actions: done, dropped, bump, refine",
                   step4, ["status: done", "closed: <source date>", "closed_by:",
                           "status: dropped", "Re-raised without closing", "**Refined**"])
    check_contains("dropped cites the fact that killed the premise, never silence",
                   step4, ["the fact that killed the premise", "Not for silence, not for doubt"])
    check_contains("a bump never moves updated: backwards, and no date bumps nothing (A1)",
                   step4, ["never moved backwards", "A source with no date bumps nothing"])
    check_contains("a Resolution lands at the end of the body, after any history",
                   step4, ["appended at the end of the body, after any `**Closure signal history:**` section"])
    check_contains("a refinement rewrites only the closure signal, never silently",
                   step4, ["append the replaced version to `**Closure signal history:**`",
                           "`description` included", "Never a silent edit"])

    # the history format, as a fenced block in step 4
    fences = re.findall(r"```[a-z]*\n(.*?)```", raw, flags=re.S)
    block = next((f for f in fences if "**Closure signal history:**" in f), "")
    record("the history format is a fenced block", bool(block))
    entry = re.search(r"(?m)^[ \t]*- \d{4}-\d{2}-\d{2}, from \[(/sources/[^\]]+)\]\((/sources/[^)]+)\): was \"",
                      block)
    record("the fenced history block: current signal, then history, then a dated sourced entry",
           block.find("**Closure signal:**") != -1
           and block.find("**Closure signal:**") < block.find("**Closure signal history:**")
           and entry is not None and entry.group(1) == entry.group(2),
           block)
    record("the fenced history block carries the **Closure signal:** lead-in exactly once",
           block.count("**Closure signal:**") == 1, block)
    check_contains("the three history rules",
                   step4, ["directly after the current `**Closure signal:**` section",
                           "never appears anywhere else in the body", "oldest first"])

    # (b) every loop write at step 7, and --review gates it
    check_contains("step 7 files an action item by the bar and writes every loop action there",
                   st.get(7, ""), ["clears the loop bar (steps 2 and 3) is an `open-loop`",
                                   "one that fails it is a fact",
                                   "Every loop write step 4 decided (new loop, close, drop, bump, refine) happens here",
                                   "`--review` gates them"])
    check_contains("step 8 logs each loop closed, dropped, bumped or refined",
                   st.get(8, ""), ["per loop closed, dropped, bumped or refined"])
    check_contains("step 9 recaps loops opened, closed, dropped or refined",
                   st.get(9, ""), ["open-loops opened, closed, dropped or refined"])
    review = body[body.find("**`--review` variant:**"):] if "**`--review` variant:**" in body else ""
    check_contains("the --review batches name each loop action",
                   review, ["each loop action (new loop, close, drop, bump, refine, or routed to a fact by the loop bar)"])


def test_inheritors():
    # catch-up points at the core and no longer carries its own bump rule
    raw = read(CATCH_UP)
    if record(f"{rel(CATCH_UP)} exists", bool(raw)):
        body = flat(raw)
        st = steps(raw)
        check_absent("catch-up no longer carries its own close or bump rule",
                     body, ["this rule is its only writer",
                            "A source that re-raises an open loop without closing it bumps it",
                            "**close** open-loops a new source shows done"])
        check_contains("catch-up step 4 applies the core's loop rules from ../ingest/procedure.md",
                       st.get(4, ""), ["../ingest/procedure.md", "the loop bar in steps 2 and 3",
                                       "**Open loops** in step 4", "close, drop, bump or refine",
                                       "this routine adds nothing to them"])
        check_contains("catch-up: precedence settles wording only; a bump takes the latest "
                       "date, never backwards (A1)",
                       st.get(4, ""), ["source precedence (transcripts over Slack) settles only "
                                       "wording and detail",
                                       "the bump takes the latest of their dates"])
        check_absent("catch-up no longer lets precedence pick the date a bump takes",
                     body, ["decides which source dates a bump"])
        check_contains("catch-up step 3: a commitment's spec says who owes it and who waits on it",
                       st.get(3, ""), ["who owes it and who is waiting on it"])

    # capture names the user as the source, today as the date, and recaps loops
    raw = read(CAPTURE)
    if record(f"{rel(CAPTURE)} exists", bool(raw)):
        body = flat(raw)
        check_contains("capture applies the loop bar to a follow-up",
                       body, ["follow-up the owner owes or is owed", "the loop bar of `ingest` steps 2 and 3"])
        check_contains("capture acts on open loops with the user as the source and today as the date",
                       body, ["`ingest` step 4's rules on open loops", "the user is the source",
                              "the capture record is `closed_by`", "the date is today"])
        check_contains("capture's recap names loops closed, dropped, bumped or refined",
                       body, ["any open-loop opened, closed, dropped, bumped or refined"])

    # init seeds its example loop with the owner in owner
    body = flat(read(INIT))
    check_contains("init's example open-loop carries the owner's entity in owner",
                   body, ["**example open-loop** in `tracking/loops/`, with the owner's entity in `owner`"])
    check_contains("init's orientation scopes open loops to the owner",
                   body, ["**open loops** (commitments the owner owes or is owed, which eventually close)"])


def test_shared_prose():
    for path in (CORE, ARCHITECTURE):
        body = flat(read(path))
        record(f"{rel(path)} exists", bool(body))
        check_absent(f"{rel(path)} no longer states the retired writer list",
                     body, ["hand-set state", "survived examination", "Those two are the writers",
                            "Those are the only writers"])
        check_contains(f"{rel(path)} names owed_to, the 30-day default and the hand-set dropped",
                       body, ["`owed_to`", "(default 30)", "can also be set by hand"])
        check_contains(f"{rel(path)}: close-loops only closes or drops, never bumps or refines",
                       body, ["`close-loops`, optional, closes (`done`) or drops (`dropped`) by "
                              "evidence over the backlog, and never bumps or refines a loop it "
                              "leaves open"])
        check_absent(f"{rel(path)} no longer credits close-loops with the ingest core's bump "
                     "and refine", body, ["does the same by evidence"])

    core = flat(read(CORE))
    check_contains("core.md: a commitment is a loop only when the owner owes it or is owed it",
                   core, ["drops nothing for relevance",
                          "a commitment is a loop only when the owner owes it or is owed it",
                          "../ingest/procedure.md"])
    check_contains("core.md: the ingest core closes, drops, bumps and refines; close-loops is optional",
                   core, ["closes (`done`) or drops (`dropped`)", "`close-loops`, optional",
                          "every terminal status is final"])

    arch = flat(read(ARCHITECTURE))
    check_contains("architecture.md: the owner decides only the lane a commitment takes",
                   arch, ["The owner decides only the lane a commitment takes",
                          "and, for facts, at **decay** in `maintain`"])
    check_absent("architecture.md's example commitment is the owner's, not a third party's",
                 arch, ["Jane will draft the migration plan"])
    check_contains("core.md: relevance applies at retrieval and, for facts, at maintain's decay",
                   core, ["and, for facts, at `maintain`'s decay"])

    conf = flat(read(CONFIGURATION))
    check_contains("configuration.md documents decay.loop_expiry_days with its default 30",
                   conf, ["**`decay`** (optional)", "`loop_expiry_days` (default `30`)"])
    check_contains("configuration.md: owner.slug drives the out-of-scope rule, skipped without it",
                   conf, ["in none of `owner`, `owed_to`, `entities`", "Without `slug` that rule is skipped"])
    check_contains("configuration.md: state/closure-sweep.json is close-loops' own, never read by decay",
                   conf, ["`state/closure-sweep.json`", "never read by `decay`"])

    seed = flat(read(SEED_CONFIG))
    check_contains("seed config.md: a commitment is a loop only when it is the owner's",
                   seed, ["a commitment is a loop only when it is the owner's",
                          "Action items the owner owes or is owed"])
    check_absent("seed config.md no longer applies relevance at decay unscoped",
                 seed, ["relevance is applied at retrieval and decay"])
    check_contains("seed config.md: relevance applies at retrieval and, for facts, at maintain's decay",
                   seed, ["applied at retrieval and, for facts, at `maintain`'s decay"])

    integ = flat(read(INTEGRATIONS))
    check_contains("integrations.md marks close-loops optional and decay independent of it",
                   integ, ["Optionally, run `close-loops` daily",
                           "closes or drops the ones the evidence shows delivered or obsolete",
                           "does not wait for `close-loops`"])
    check_absent("integrations.md no longer runs decay after close-loops",
                 integ, ["every three days, after it", "loops `close-loops` has already read"])
    check_contains("integrations.md: a Linear issue becomes a loop only when it is the owner's",
                   integ, ["commitments the owner owes or is owed (an open issue assigned to them, "
                           "or one they are waiting on) can become open loops",
                           "anyone else's become facts"])
    check_absent("integrations.md no longer makes every assigned issue a loop",
                 integ, ["commitments (an assigned, open issue) can become open loops"])


def test_daily_routines_carry_no_expiry():
    """D9, E28: no expiry notice in any daily routine."""
    for name in DAILY_ROUTINES:
        folder = SKILLS / name
        files = sorted(folder.rglob("*.md")) if folder.is_dir() else []
        hits = [rel(f) for f in files if "expir" in read(f).lower()]
        record(f"{name}: skill files present and none mentions expiry",
               bool(files) and not hits,
               f"files: {[rel(f) for f in files]}; mentioning expiry: {hits}")


def test_no_retired_rule_anywhere():
    """Repo-wide: no shipped file still states a rule this lifecycle retired.

    Meant to pass only once every group of the loop-lifecycle change has
    landed (the decay and close-loops skills, and the README).
    """
    paths = [p for root in (PLUGIN, DOCS) for p in root.rglob("*")
             if p.is_file() and p.suffix in TEXT_SUFFIXES and "__pycache__" not in p.parts]
    paths.append(REPO_ROOT / "README.md")
    texts = {}
    for p in sorted(paths):
        try:
            texts[rel(p)] = flat(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    for phrase in RETIRED:
        needle = flat(phrase).lower()
        hits = [name for name, text in texts.items() if needle in text.lower()]
        label = f"repo-wide: no file under plugin/, docs/ or README.md says {phrase!r}"
        if hits:
            label += f" (found in {', '.join(hits)})"
        record(label, not hits)


def test_ci_runs_this_suite():
    """ci.yml lists each suite as its own step, with no glob: a suite whose
    line goes missing stops running with CI still green, which is how
    test_backlog.py went a full release unrun."""
    ci = read(REPO_ROOT / ".github" / "workflows" / "ci.yml")
    record("this suite has its own `- run:` line in ci.yml, which has no glob",
           "python tests/test_loop_lifecycle.py" in ci)


def main():
    test_ingest_core()
    test_inheritors()
    test_shared_prose()
    test_daily_routines_carry_no_expiry()
    test_no_retired_rule_anywhere()
    test_ci_runs_this_suite()

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
