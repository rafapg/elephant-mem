#!/usr/bin/env python3
"""Standalone regression tests for `plugin/assets/scripts/decay-loops.py` —
the automatic open-loop decay-to-`expired` script.

Covers: dry-run makes no changes; --apply expires only stale `status: open`
loops; a recent `updated` (re-mention resets the clock) protects an
otherwise-old loop; `done`/`dropped`/already-`expired` loops are never
touched; the `expired: YYYY-MM-DD` field is stamped correctly; the default
30-day threshold vs. a custom `elephant.json` -> `decay.loop_expiry_days`;
that `build-index.py`, run after `--apply`, drops the newly-expired loops
from the open-loop count/board/manifest; that `--apply` expires on silence
alone and never reads `state/closure-sweep.json`, with `--skip-sweep` kept as
a deprecated no-op; that an open loop naming the bundle owner (`elephant.json`
-> `owner.slug`) in none of `owner`, `owed_to`, `entities` is an out-of-scope
candidate at any age, compared by slug in every link shape, and that the rule
is skipped with a note when there is no `owner.slug`, or when only a
duplicate of the owner's entity is linked; that `--except` keeps a named loop
out of the run, and refuses the run when it names no loop file; that every expiry writes a `**Resolution:**`
paragraph in the same shape a closure does, naming which kind of expiry it
was; that a recent citation in `state/recall.json` counts as a fourth activity
date while every degraded shape of that record — absent, empty, malformed, no
entry for this loop, no `recall.py` in the bundle at all — leaves the scan
behaving exactly as it did before recall existed; and that the `decay` skill's
prose says what the script now does.

Pure stdlib, Python 3.10+, same scaffolding style as tests/smoke.py and
tests/test_index.py: every check builds its own throwaway bundle under a
tempdir and drives the shipped scripts via subprocess (sys.executable) — no
shell-outs, no third-party deps.

Exit code 0 only if every check below passes.
"""
import datetime
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "plugin" / "assets"

TODAY = datetime.date.today()

checks = []


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    return passed


def run_script(bundle, script_name, args=None):
    script = bundle / "scripts" / script_name
    return subprocess.run(
        [sys.executable, str(script)] + (args or []),
        cwd=str(bundle), capture_output=True, text=True, encoding="utf-8",
    )


def days_ago(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


def days_ahead(n):
    return (TODAY + datetime.timedelta(days=n)).isoformat()


def slug_of(value):
    """The slug decay-loops.py's slug() reads out of `value`: last path
    segment, `.md` stripped, lowercased."""
    s = value.rsplit("/", 1)[-1]
    return (s[:-3] if s.endswith(".md") else s).lower()


def write_entity(bundle, entity_slug, kind="person"):
    """A minimal, valid entity file at knowledge/entities/<kind>/<slug>.md."""
    path = bundle / "knowledge" / "entities" / kind / f"{entity_slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    day = TODAY.isoformat()
    path.write_text(
        "---\n"
        "type: entity\n"
        f"kind: {kind}\n"
        f'title: "{entity_slug}"\n'
        'description: "An entity."\n'
        "aliases: []\n"
        "tags: []\n"
        f"created: {day}\n"
        f"updated: {day}\n"
        f"timestamp: {day}\n"
        "---\n\n"
        f"{entity_slug}.\n",
        encoding="utf-8",
    )
    return path


def new_bundle(root, name, expiry_days=None, with_recall=True, owner_slug=None,
               owner_entity=True):
    """Minimal throwaway bundle: decay-loops.py + build-index.py (the latter
    only needed by the cross-script integration check) + recall.py (the sibling
    decay reads the citation date through), a reserved log.md, and an empty
    knowledge/tracking/loops/ dir — mirrors the real bundle path confirmed
    against ~/elephant-mem.

    `with_recall=False` builds the bundle an installed user has when `update`
    has not yet re-synced `scripts/`: decay is there, its sibling is not.

    `owner_slug` writes `owner.slug` into `elephant.json`, which switches the
    out-of-scope rule on. The default stays None, so every check that predates
    the rule keeps its `owner: []` loops in play as stale candidates only.
    With it, the owner's entity file is written too, since a slug naming no
    entity switches the rule off; `owner_entity=False` builds that bundle."""
    bundle = root / name
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    scripts = ["decay-loops.py", "build-index.py", "validate-okf.py"]
    if with_recall:
        scripts.append("recall.py")
    for f in scripts:
        shutil.copy2(ASSETS / "scripts" / f, bundle / "scripts" / f)
    config = {}
    if expiry_days is not None:
        config["decay"] = {"loop_expiry_days": expiry_days}
    if owner_slug is not None:
        config["owner"] = {"slug": owner_slug}
    if config:
        (bundle / "elephant.json").write_text(json.dumps(config) + "\n", encoding="utf-8")
    (bundle / "knowledge" / "tracking" / "loops").mkdir(parents=True, exist_ok=True)
    (bundle / "knowledge" / "log.md").write_text("# Log\n", encoding="utf-8")
    if owner_slug is not None and owner_entity and slug_of(owner_slug):
        write_entity(bundle, slug_of(owner_slug))
    return bundle


def link_list(value):
    """The text after `key:` for one of a loop's link lists. A sequence is
    written as an inline list; a string is written verbatim, so a check can
    spell the other shapes itself (`" /x.md"` for a bare scalar, `"\\n  - /x.md"`
    for a block sequence)."""
    if isinstance(value, str):
        return value
    return " [" + ", ".join(value) + "]"


def write_loop(bundle, name, desc, status="open", opened=None, created=None,
               updated=None, extra="", signal=None, owner=(), owed_to=None,
               entities=()):
    """One loop file. `owed_to=None` writes no `owed_to:` line at all, the
    shape of every loop filed before the field existed."""
    opened = opened or TODAY.isoformat()
    created = created or opened
    updated = updated or created
    text = (
        "---\n"
        "type: open-loop\n"
        f"description: {desc}\n"
        f"owner:{link_list(owner)}\n"
        + (f"owed_to:{link_list(owed_to)}\n" if owed_to is not None else "")
        + f"status: {status}\n"
        f"entities:{link_list(entities)}\n"
        "sources: []\n"
        f"opened: {opened}\n"
        "closed:\n"
        "closed_by:\n"
        "tags: []\n"
        f"created: {created}\n"
        f"updated: {updated}\n"
        f"timestamp: {updated}\n"
        f"{extra}"
        "---\n\n"
        f"{desc}\n"
        + (f"\n**Closure signal:** {signal}\n" if signal else "")
    )
    path = bundle / "knowledge" / "tracking" / "loops" / name
    path.write_text(text, encoding="utf-8")
    return path


def write_recall(bundle, cited, raw=None):
    """Write `state/recall.json`. `cited` maps a loop's bundle-absolute path to
    the ISO date it was last cited; `raw` overrides the whole file with a
    literal string, for the malformed and empty shapes.

    Hand-built rather than produced by driving `recall.py log` + `roll`: what
    this suite is pinning is decay's reading of the record, and building it here
    keeps the check from passing or failing on the roller's behavior, which
    tests/test_recall.py owns."""
    state = bundle / "state"
    state.mkdir(parents=True, exist_ok=True)
    path = state / "recall.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return path
    items = {
        key: {"total": 1, "last": day, "buckets": {day: 1}}
        for key, day in cited.items()
    }
    path.write_text(
        json.dumps(
            {"schema": 1, "rolled_through": None, "generated": None,
             "items": items, "entities": {}},
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return path


def write_sweep(bundle, entries, raw=None):
    """Write `state/closure-sweep.json`, the record `close-loops` keeps as its
    own queue control and `decay-loops.py` must ignore. `entries` maps a loop's bundle-absolute
    path to its examination date, or to an `(examined, outcome)` pair; `raw`
    overrides the whole file with a literal string, for the malformed shape.

    Hand-built rather than produced by running the `close-loops` routine: the
    routine writes this file from prose (its `procedure.md` -> "The sweep
    record"), and tests/test_close_loops.py owns whether that recipe writes what
    its script reads. What this suite pins is that decay reads none of it.
    """
    state = bundle / "state"
    state.mkdir(parents=True, exist_ok=True)
    path = state / "closure-sweep.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return path
    loops = {}
    for link, value in entries.items():
        examined, outcome = value if isinstance(value, tuple) else (value, "open")
        entry = {"examined": examined}
        if outcome is not None:  # `(date, None)` writes the outcome-less entry
            entry["outcome"] = outcome
        loops[link] = entry
    path.write_text(
        json.dumps({"schema": 1, "generated": None, "loops": loops}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# 1. dry-run changes nothing
# ---------------------------------------------------------------------------

def test_dry_run_no_changes(root):
    bundle = new_bundle(root, "dry-run")
    p = write_loop(bundle, "old.md", "Old stale loop",
                    opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    before = p.read_text(encoding="utf-8")

    result = run_script(bundle, "decay-loops.py")
    record("dry-run exits 0", result.returncode == 0, result.stdout + result.stderr)
    record("dry-run lists the stale candidate with its age",
           "old.md" in result.stdout and "100d stale" in result.stdout, result.stdout)
    record("dry-run reports a count of 1 candidate", "1 candidate(s)" in result.stdout, result.stdout)

    after = p.read_text(encoding="utf-8")
    record("dry-run does not modify the file on disk", before == after,
           f"before:\n{before}\nafter:\n{after}")


# ---------------------------------------------------------------------------
# 2. --apply expires only the stale `status: open` loops
# ---------------------------------------------------------------------------

def test_apply_expires_only_old_open(root):
    bundle = new_bundle(root, "apply-basic")
    old = write_loop(bundle, "old.md", "Old stale loop",
                      opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    fresh = write_loop(bundle, "fresh.md", "Fresh loop",
                        opened=days_ago(2), created=days_ago(2), updated=days_ago(2))

    result = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply exits 0", result.returncode == 0, result.stdout + result.stderr)

    old_text = old.read_text(encoding="utf-8")
    fresh_text = fresh.read_text(encoding="utf-8")
    record("old loop past the threshold is expired", "status: expired" in old_text, old_text)
    record("fresh loop within the threshold stays open and untouched",
           "status: open" in fresh_text and "expired" not in fresh_text.split("---")[1],
           fresh_text)


# ---------------------------------------------------------------------------
# 3. a recent `updated` protects an otherwise-old loop (re-mention resets clock)
# ---------------------------------------------------------------------------

def test_recent_update_protects(root):
    bundle = new_bundle(root, "updated-protects")
    p = write_loop(bundle, "reopened.md", "Old loop re-mentioned recently",
                    opened=days_ago(200), created=days_ago(200), updated=days_ago(1))

    result = run_script(bundle, "decay-loops.py")
    record("dry-run exits 0", result.returncode == 0, result.stdout + result.stderr)
    record("loop opened long ago but updated recently is NOT a candidate",
           "reopened.md" not in result.stdout, result.stdout)
    record("dry-run reports 0 candidates", "0 candidate(s)" in result.stdout, result.stdout)

    run_script(bundle, "decay-loops.py", ["--apply"])
    text = p.read_text(encoding="utf-8")
    record("--apply leaves the recently-updated loop untouched: it is the date "
           "that protects it",
           "status: open" in text and "expired" not in text, text)


# ---------------------------------------------------------------------------
# 4. done / dropped / already-expired loops are never touched
# ---------------------------------------------------------------------------

def test_other_statuses_untouched(root):
    bundle = new_bundle(root, "other-statuses")
    done = write_loop(bundle, "done.md", "Done long ago", status="done",
                       opened=days_ago(200), created=days_ago(200), updated=days_ago(200))
    dropped = write_loop(bundle, "dropped.md", "Dropped long ago", status="dropped",
                          opened=days_ago(200), created=days_ago(200), updated=days_ago(200))
    already_expired = write_loop(
        bundle, "already-expired.md", "Already expired long ago", status="expired",
        opened=days_ago(200), created=days_ago(200), updated=days_ago(200),
        extra="expired: 2025-01-01\n",
    )
    watched = (done, dropped, already_expired)
    before = {p: p.read_text(encoding="utf-8") for p in watched}

    dry = run_script(bundle, "decay-loops.py")
    record("dry-run lists none of done/dropped/already-expired as candidates",
           all(p.name not in dry.stdout for p in watched), dry.stdout)

    apply_result = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply exits 0 with nothing to do",
           apply_result.returncode == 0, apply_result.stdout + apply_result.stderr)

    unchanged = all(before[p] == p.read_text(encoding="utf-8") for p in watched)
    record("done/dropped/already-expired loops are byte-identical after --apply", unchanged)


# ---------------------------------------------------------------------------
# 5. `expired:` field is written with today's date; file is never deleted
# ---------------------------------------------------------------------------

def test_expired_field_written(root):
    bundle = new_bundle(root, "expired-field")
    p = write_loop(bundle, "old.md", "Old stale loop",
                    opened=days_ago(100), created=days_ago(100), updated=days_ago(100))

    run_script(bundle, "decay-loops.py", ["--apply"])
    text = p.read_text(encoding="utf-8")
    record(f"expired: {TODAY.isoformat()} field stamped", f"expired: {TODAY.isoformat()}" in text, text)
    record("status flipped to expired", "status: expired" in text, text)
    record("file still exists (never deleted)", p.exists())


# ---------------------------------------------------------------------------
# 6. default 30d threshold vs. a custom elephant.json -> decay.loop_expiry_days
# ---------------------------------------------------------------------------

def test_custom_threshold(root):
    # 35 days old IS a candidate under the default (no elephant.json) 30d
    # threshold, and 20 days old is not.
    bundle_default = new_bundle(root, "threshold-default")
    write_loop(bundle_default, "borderline.md", "35-day-old loop",
               opened=days_ago(35), created=days_ago(35), updated=days_ago(35))
    write_loop(bundle_default, "recent.md", "20-day-old loop",
               opened=days_ago(20), created=days_ago(20), updated=days_ago(20))
    result_default = run_script(bundle_default, "decay-loops.py")
    record("35-day-old loop IS a candidate under the default 30d threshold",
           "borderline.md" in result_default.stdout, result_default.stdout)
    record("…while a 20-day-old loop is not",
           "recent.md" not in result_default.stdout
           and "1 candidate(s)" in result_default.stdout, result_default.stdout)

    # Raising the threshold via elephant.json protects the same-age loop (E12).
    bundle_raised = new_bundle(root, "threshold-raised", expiry_days=60)
    write_loop(bundle_raised, "borderline.md", "35-day-old loop",
               opened=days_ago(35), created=days_ago(35), updated=days_ago(35))
    result_raised = run_script(bundle_raised, "decay-loops.py")
    record("same 35-day-old loop is NOT a candidate once elephant.json raises the threshold to 60d",
           "borderline.md" not in result_raised.stdout, result_raised.stdout)

    # Lowering the threshold via elephant.json catches a loop the default would miss.
    bundle_lowered = new_bundle(root, "threshold-lowered", expiry_days=10)
    write_loop(bundle_lowered, "young.md", "20-day-old loop",
               opened=days_ago(20), created=days_ago(20), updated=days_ago(20))
    result_lowered = run_script(bundle_lowered, "decay-loops.py")
    record("20-day-old loop becomes a candidate once elephant.json lowers the threshold to 10d",
           "young.md" in result_lowered.stdout, result_lowered.stdout)


def test_invalid_threshold_values(root):
    """A `loop_expiry_days` that is present but not a positive whole number
    takes the default, with a note. `true` is the one that mattered: JSON's
    boolean is a Python int, so it read as a 1-day window and a loop 5 days
    quiet was a candidate."""
    for tag, value in (("bool", True), ("string", "60"), ("float", 60.0), ("zero", 0)):
        bundle = new_bundle(root, "threshold-invalid-" + tag, expiry_days=value)
        write_loop(bundle, "five-days.md", "5-day-old loop",
                   opened=days_ago(5), created=days_ago(5), updated=days_ago(5))
        write_loop(bundle, "forty-days.md", "40-day-old loop",
                   opened=days_ago(40), created=days_ago(40), updated=days_ago(40))
        dry = run_script(bundle, "decay-loops.py")
        record(f"loop_expiry_days {json.dumps(value)}: the default 30 is used "
               "(the 5-day loop is no candidate, the 40-day one is), with one note",
               "five-days.md" not in dry.stdout and "forty-days.md" in dry.stdout
               and "stale >= 30d" in dry.stdout
               and dry.stderr.count("decay.loop_expiry_days is") == 1,
               dry.stdout + dry.stderr)
    valid = new_bundle(root, "threshold-valid-quiet", expiry_days=45)
    dry = run_script(valid, "decay-loops.py")
    record("…while a valid value prints no such note",
           "decay.loop_expiry_days is" not in dry.stderr, dry.stderr)


# ---------------------------------------------------------------------------
# 7. build-index.py, run after --apply, drops expired loops from the counts
# ---------------------------------------------------------------------------

def test_build_index_excludes_expired_after_apply(root):
    bundle = new_bundle(root, "build-index-integration")
    write_loop(bundle, "old.md", "Old stale loop to expire",
               opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    write_loop(bundle, "fresh.md", "Fresh loop stays open",
               opened=days_ago(2), created=days_ago(2), updated=days_ago(2))

    result_pre = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 (pre-decay)", result_pre.returncode == 0,
                   result_pre.stdout + result_pre.stderr):
        return

    open_loops_pre = (bundle / "knowledge" / "tracking" / "open-loops.md").read_text(encoding="utf-8")
    record("pre-decay: open-loops.md board lists both loops",
           "Old stale loop to expire" in open_loops_pre and "Fresh loop stays open" in open_loops_pre,
           open_loops_pre)
    index_pre = (bundle / "knowledge" / "index.md").read_text(encoding="utf-8")
    record("pre-decay: router counts 2 open loops", "(2 open)" in index_pre, index_pre)

    decay_result = run_script(bundle, "decay-loops.py", ["--apply"])
    if not record("decay --apply exits 0", decay_result.returncode == 0,
                   decay_result.stdout + decay_result.stderr):
        return

    result_post = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 (post-decay)", result_post.returncode == 0,
                   result_post.stdout + result_post.stderr):
        return

    open_loops_post = (bundle / "knowledge" / "tracking" / "open-loops.md").read_text(encoding="utf-8")
    record("post-decay: expired loop dropped from the open-loops board, fresh one stays",
           "Old stale loop to expire" not in open_loops_post and "Fresh loop stays open" in open_loops_post,
           open_loops_post)

    index_post = (bundle / "knowledge" / "index.md").read_text(encoding="utf-8")
    record("post-decay: router's open-loop count drops from 2 to 1", "(1 open)" in index_post, index_post)

    manifest_post = (bundle / "knowledge" / "manifest.jsonl").read_text(encoding="utf-8")
    record("post-decay: manifest.jsonl no longer carries the expired loop, keeps the fresh one",
           "Old stale loop to expire" not in manifest_post and "Fresh loop stays open" in manifest_post,
           manifest_post)


# ---------------------------------------------------------------------------
# 8. a loop written from open-loop.md — the trailing vocabulary comment
# ---------------------------------------------------------------------------
# open-loop.md ships `status: open          # open | done | dropped | expired`,
# and the model that writes a loop from it keeps that comment: it is the
# documentation. field() read the whole line, so
# `field(block, "status") != "open"` was true for every template-derived loop
# and the entire script was a no-op. On every machine — this script has no
# PyYAML path to fall back to.

STATUS_DOC = "        # open | done | dropped | expired"


def test_template_shaped_loop_decays(root):
    bundle = new_bundle(root, "template-shape")
    old = write_loop(bundle, "old.md", "Old stale loop",
                     status="open" + STATUS_DOC,
                     opened=days_ago(100), created=days_ago(100),
                     updated=days_ago(100) + "  # bumped by catch-up")
    done = write_loop(bundle, "done.md", "Long-finished loop",
                      status="done" + STATUS_DOC,
                      opened=days_ago(100), created=days_ago(100), updated=days_ago(100))

    result = run_script(bundle, "decay-loops.py")
    record("a loop that kept `# open | done | dropped | expired` is seen as open and "
           "listed as a candidate (the script used to find none, ever)",
           "old.md" in result.stdout and "1 candidate(s)" in result.stdout, result.stdout)
    record("…and its `updated:` is read through its own comment, so the age is "
           "the date's, not a parse failure's",
           "100d stale" in result.stdout, result.stdout)
    record("…while a `done` loop carrying the same comment is still not a "
           "candidate — the reader did not simply learn to match everything",
           "done.md" not in result.stdout, result.stdout)

    run_script(bundle, "decay-loops.py", ["--apply"])
    status_line = next(ln for ln in old.read_text(encoding="utf-8").splitlines()
                       if ln.startswith("status:"))
    record("--apply expires it and keeps the vocabulary comment on the line — "
           "the writer already tolerated the comment; it was the reader that "
           "was wrong, and this pins the asymmetry",
           status_line == "status: expired" + STATUS_DOC, repr(status_line))
    record("…and the `done` loop is still untouched after --apply",
           "status: done" in done.read_text(encoding="utf-8"),
           done.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 8b. one rule for the status field, on both sides of the lane
# ---------------------------------------------------------------------------
# build-index.py normalizes the field through its own `loop_status()`, which
# strips and lowercases, so `status: Open` counts as open on the board, in the
# manifest and on the entity hubs. Decay compared the raw scalar, so the same
# loop was open everywhere and invisible here: it sat on the board as a live
# commitment forever and decay never so much as considered it. The two sides
# now read the field by the same rule, which is what this check pins, run
# across both scripts rather than against decay alone.

def test_status_spelling_agrees_with_build_index(root):
    bundle = new_bundle(root, "status-spelling")
    variants = {
        "capital.md": ("Open", "Capitalized status, edited by hand"),
        "spaced.md": ("open ", "Trailing space after the status"),
        "quoted.md": ('"open"', "Quoted status, as a --fix pass writes it"),
    }
    paths = {}
    for name, (status, desc) in variants.items():
        paths[name] = write_loop(bundle, name, desc, status=status,
                                 opened=days_ago(100), created=days_ago(100),
                                 updated=days_ago(100))
    decoy = write_loop(bundle, "done.md", "Capitalized and long finished",
                       status="Done", opened=days_ago(100),
                       created=days_ago(100), updated=days_ago(100))

    index_pre = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 over the odd spellings",
                   index_pre.returncode == 0,
                   index_pre.stdout + index_pre.stderr):
        return
    board_pre = (bundle / "knowledge" / "tracking" / "open-loops.md").read_text(encoding="utf-8")
    record("build-index reads all three spellings as open and boards them",
           all(desc in board_pre for _status, desc in variants.values()), board_pre)

    dry = run_script(bundle, "decay-loops.py")
    record("…and decay reaches every one of them as a candidate, the count "
           "agreeing with the board rather than reading 0",
           all(name in dry.stdout for name in variants) and "3 candidate(s)" in dry.stdout,
           dry.stdout)
    record("…while a `Done` loop is still no candidate: the reader was "
           "normalized, not taught to match everything",
           "done.md" not in dry.stdout, dry.stdout)

    apply_result = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply expires all three, so the reader and the writer accept the "
           "same spellings", "3 loop(s) expired" in apply_result.stdout,
           apply_result.stdout + apply_result.stderr)
    for name, path in paths.items():
        text = path.read_text(encoding="utf-8")
        status_line = next(ln for ln in text.splitlines() if ln.startswith("status:"))
        record(f"…{name}: the status line now reads expired",
               "expired" in status_line and "open" not in status_line.lower(),
               repr(status_line))
        record(f"…{name}: and carries today's expiry date",
               f"expired: {TODAY.isoformat()}" in text, text)

    index_post = run_script(bundle, "build-index.py")
    board_post = (bundle / "knowledge" / "tracking" / "open-loops.md").read_text(encoding="utf-8")
    record("build-index, run after, drops all three from the board: the two "
           "sides end where they started, agreeing about every file",
           index_post.returncode == 0
           and all(desc not in board_post for _status, desc in variants.values()),
           board_post + index_post.stderr)
    record("…and the untouched `Done` loop is byte-identical",
           "status: Done" in decoy.read_text(encoding="utf-8"),
           decoy.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 9. a recent citation is a fourth activity date
# ---------------------------------------------------------------------------

def test_recall_citation_protects(root):
    """E7: cited 3 days ago, `updated` 100 days old -> not a candidate."""
    bundle = new_bundle(root, "recall-protects")
    cited = write_loop(bundle, "cited.md", "Stale on paper, still consulted",
                       opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    uncited = write_loop(bundle, "uncited.md", "Stale and never consulted",
                         opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    write_recall(bundle, {"/tracking/loops/cited.md": days_ago(3)})

    result = run_script(bundle, "decay-loops.py")
    record("dry-run exits 0 with a recall record present",
           result.returncode == 0, result.stdout + result.stderr)
    record("a loop cited 3 days ago is not a candidate, though `updated` is 100d old",
           "cited.md" not in result.stdout.replace("uncited.md", ""), result.stdout)
    record("…while its uncited twin, identical on every file date, still is",
           "uncited.md" in result.stdout and "1 candidate(s)" in result.stdout,
           result.stdout)

    run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply leaves the cited loop open",
           "status: open" in cited.read_text(encoding="utf-8"),
           cited.read_text(encoding="utf-8"))
    record("…and expires the uncited one",
           "status: expired" in uncited.read_text(encoding="utf-8"),
           uncited.read_text(encoding="utf-8"))


def test_stale_citation_does_not_protect(root):
    """A citation older than the window is not a rescue — it is just a date."""
    bundle = new_bundle(root, "recall-stale-citation")
    write_loop(bundle, "old-cite.md", "Cited once, long ago",
               opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    write_recall(bundle, {"/tracking/loops/old-cite.md": days_ago(80)})

    result = run_script(bundle, "decay-loops.py")
    record("a loop last cited 80 days ago is still a candidate",
           "old-cite.md" in result.stdout and "1 candidate(s)" in result.stdout,
           result.stdout)
    record("…and its age is measured from the citation, the newest of the four dates",
           "80d stale" in result.stdout, result.stdout)


def test_recall_never_ages_a_loop(root):
    """The citation only ever protects: it cannot make a fresh loop a candidate."""
    bundle = new_bundle(root, "recall-only-protects")
    write_loop(bundle, "fresh.md", "Fresh loop, ancient citation",
               opened=days_ago(2), created=days_ago(2), updated=days_ago(2))
    write_recall(bundle, {"/tracking/loops/fresh.md": days_ago(400)})

    result = run_script(bundle, "decay-loops.py")
    record("an old citation on a fresh loop leaves it out of the candidates",
           "fresh.md" not in result.stdout and "0 candidate(s)" in result.stdout,
           result.stdout)


def test_recall_degraded_shapes(root):
    """E2, E8: absent, empty, malformed, no entry, no recall.py — all collapse
    to the behavior this script had before recall existed."""
    shapes = [
        ("absent", None, None),
        ("empty", None, "{}\n"),
        ("malformed", None, "{ not json at all\n"),
        ("no entry for this loop", {"/facts/2026-09/other.md": days_ago(1)}, None),
    ]
    for label, cited, raw in shapes:
        bundle = new_bundle(root, "recall-degraded-" + label.replace(" ", "-"))
        write_loop(bundle, "old.md", "Old stale loop",
                   opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
        if cited is not None or raw is not None:
            write_recall(bundle, cited or {}, raw=raw)

        result = run_script(bundle, "decay-loops.py")
        record(f"recall.json {label}: the scan still exits 0",
               result.returncode == 0, result.stdout + result.stderr)
        record(f"recall.json {label}: the stale loop is a candidate, as it was before recall",
               "old.md" in result.stdout and "1 candidate(s)" in result.stdout,
               result.stdout)

    # A bundle that has decay-loops.py but not yet its sibling — `update`
    # re-syncs scripts/ as a set, but a half-updated bundle must still decay.
    bundle = new_bundle(root, "recall-script-absent", with_recall=False)
    write_loop(bundle, "old.md", "Old stale loop",
               opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    result = run_script(bundle, "decay-loops.py")
    record("no recall.py in the bundle: the scan still exits 0",
           result.returncode == 0, result.stdout + result.stderr)
    record("no recall.py in the bundle: the stale loop is still a candidate",
           "old.md" in result.stdout and "1 candidate(s)" in result.stdout, result.stdout)
    lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
    record("no recall.py in the bundle: and the scan says nothing about it — "
           "the only stderr is the owner.slug note this ownerless bundle earns",
           "recall.py" not in result.stderr
           and all(ln.startswith("note: elephant.json has no owner.slug") for ln in lines),
           result.stderr)


# ---------------------------------------------------------------------------
# 10. no sweep gate: decay expires on silence alone
# ---------------------------------------------------------------------------
# `decay` used to expire only what `close-loops` had examined and left open,
# which paced expiry by a routine whose verdict was almost always "open". The
# gate is gone: `state/closure-sweep.json` is `close-loops`' own queue control,
# and nothing it says, or fails to say, reaches this script.

ME = "/entities/person/me.md"
JANE = "/entities/person/jane.md"
BOB = "/entities/person/bob.md"
NO_OWNER_NOTE = "note: elephant.json has no owner.slug"


def sentences(paragraph):
    """The paragraph split into sentences, the way a reader of the first one
    would: on `. ` only, so `elephant.json` and `decay.loop_expiry_days` are not
    sentence ends."""
    return [part for part in paragraph.replace(". ", ".\n").split("\n") if part.strip()]


def resolution_of(path):
    """The `**Resolution:**` paragraph of a loop file, or ""."""
    for para in path.read_text(encoding="utf-8").split("\n\n"):
        if para.strip().startswith("**Resolution:**"):
            return " ".join(para.split())
    return ""


def test_sweep_is_not_read(root):
    """E11: absent, malformed, or recording the loop as `done`, the sweep
    record changes nothing: the stale loop expires, and nothing on stderr so
    much as names the file."""
    shapes = [
        ("absent", None),
        ("malformed", "raw"),
        ("recording it as done", "done"),
    ]
    for label, shape in shapes:
        bundle = new_bundle(root, "sweep-ignored-" + label.replace(" ", "-"))
        p = write_loop(bundle, "old.md", "Old stale loop",
                       opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
        if shape == "raw":
            write_sweep(bundle, {}, raw="{ not json at all\n")
        elif shape == "done":
            write_sweep(bundle, {"/tracking/loops/old.md": (days_ago(4), "done")})

        dry = run_script(bundle, "decay-loops.py")
        result = run_script(bundle, "decay-loops.py", ["--apply"])
        record(f"closure-sweep.json {label}: --apply exits 0 and expires the stale loop",
               result.returncode == 0
               and "status: expired" in p.read_text(encoding="utf-8")
               and "1 loop(s) expired" in result.stdout,
               result.stdout + result.stderr)
        record(f"closure-sweep.json {label}: no output, dry run or --apply, names "
               "the file, and nothing is held back",
               "closure-sweep.json" not in dry.stdout + dry.stderr
               + result.stdout + result.stderr
               and "held back" not in dry.stdout + result.stdout,
               dry.stdout + dry.stderr + result.stdout + result.stderr)


def test_skip_sweep_is_a_noop(root):
    """E10: `--skip-sweep` is accepted, prints one deprecation note on stderr,
    and changes nothing else: two identical bundles, one run with the flag and
    one without, end byte-identical."""
    runs = {}
    for flag in (False, True):
        bundle = new_bundle(root, "skip-sweep-" + ("on" if flag else "off"))
        a = write_loop(bundle, "a.md", "Old stale loop",
                       opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
        b = write_loop(bundle, "b.md", "Fresh loop",
                       opened=days_ago(2), created=days_ago(2), updated=days_ago(2))
        extra = ["--skip-sweep"] if flag else []
        dry = run_script(bundle, "decay-loops.py", extra)
        applied = run_script(bundle, "decay-loops.py", ["--apply"] + extra)
        runs[flag] = (dry, applied, a.read_text(encoding="utf-8"),
                      b.read_text(encoding="utf-8"))

    dry_on, applied_on, a_on, b_on = runs[True]
    dry_off, applied_off, a_off, b_off = runs[False]
    note = ("note: --skip-sweep is deprecated and does nothing: decay no longer "
            "reads state/closure-sweep.json.")
    record("--skip-sweep is accepted: the dry run and --apply both exit 0, not "
           "argparse's 2",
           dry_on.returncode == 0 and applied_on.returncode == 0,
           f"{dry_on.returncode} {applied_on.returncode}\n{dry_on.stderr}{applied_on.stderr}")
    record("…with exactly one deprecation note on stderr per run",
           dry_on.stderr.count(note) == 1 and applied_on.stderr.count(note) == 1,
           dry_on.stderr + applied_on.stderr)
    record("…and a stdout identical to the run without it, dry run and --apply",
           dry_on.stdout == dry_off.stdout and applied_on.stdout == applied_off.stdout,
           f"with:\n{dry_on.stdout}{applied_on.stdout}\nwithout:\n"
           f"{dry_off.stdout}{applied_off.stdout}")
    record("…and the loop files end byte-identical to the run without it",
           a_on == a_off and b_on == b_off and "status: expired" in a_on
           and "status: open" in b_on, a_on + "\n---\n" + a_off)
    record("without the flag there is no deprecation note",
           "deprecated" not in dry_off.stderr + applied_off.stderr,
           dry_off.stderr + applied_off.stderr)
    help_out = run_script(new_bundle(root, "skip-sweep-help"), "decay-loops.py", ["--help"])
    record("--help describes --skip-sweep as deprecated, with no effect",
           "deprecated, no effect" in " ".join(help_out.stdout.split()),
           help_out.stdout)


# ---------------------------------------------------------------------------
# 11. the expiry resolution, in the same shape a closure's is
# ---------------------------------------------------------------------------


def test_expiry_writes_a_resolution(root):
    """E17: `expired`, the date, and a `**Resolution:**` paragraph naming the
    silence — body prose, never a frontmatter field, first sentence standalone."""
    bundle = new_bundle(root, "expiry-resolution")
    p = write_loop(bundle, "old.md", "Ship the quarterly export",
                   opened=days_ago(100), created=days_ago(100), updated=days_ago(100),
                   signal="a source showing the export was delivered.")

    result = run_script(bundle, "decay-loops.py", ["--apply"])
    text = p.read_text(encoding="utf-8")
    para = resolution_of(p)
    body = text.split("---\n", 2)[2]

    record("--apply exits 0", result.returncode == 0, result.stdout + result.stderr)
    record("the expired loop carries exactly one `**Resolution:**` paragraph",
           text.count("**Resolution:**") == 1, text)
    record("…in the body, after the `**Closure signal:**` section, and not in "
           "the frontmatter — a sentence of judgment carries `: `, which would "
           "break the block",
           "**Resolution:**" in body
           and body.index("**Closure signal:**") < body.index("**Resolution:**"),
           text)
    record("…alongside `status: expired` and today's `expired:` date",
           "status: expired" in text and f"expired: {TODAY.isoformat()}" in text, text)

    parts = sentences(para)
    record("…two to four sentences, like the closure it mirrors",
           2 <= len(parts) <= 4, f"{len(parts)}: {parts}")
    first = parts[0] if parts else ""
    record("…whose first sentence stands alone: it dates the expiry and gives "
           "the silence in days, so resolved-loops.md can print it and nothing else",
           first.startswith("**Resolution:**") and TODAY.isoformat() in first
           and "100 days" in first and "silence" in first, first)
    record("…and names the last-activity date and the window it fell past",
           days_ago(100) in para and "30-day" in para, para)
    record("…and says nothing about state/closure-sweep.json, which decay no "
           "longer reads", "closure-sweep.json" not in para, para)

    index = run_script(bundle, "build-index.py")
    valid = run_script(bundle, "validate-okf.py")
    record("build-index.py and validate-okf.py both pass over the rewritten loop "
           "— the paragraph is prose the validator accepts",
           index.returncode == 0 and valid.returncode == 0,
           f"index={index.returncode}\n{index.stdout}\n{index.stderr}\n"
           f"valid={valid.returncode}\n{valid.stdout}\n{valid.stderr}")


def test_expiry_boundary_day(root):
    """`activity > cutoff` skips, so a loop exactly `loop_expiry_days` old IS
    expired (E13). The magnitude was sensed and the boundary day was not: both
    `> -> >=` and `days=expiry_days -> expiry_days - 1` survived the suite, and
    the run's own message once said `stale > N` for a comparison that is `>=`."""
    bundle = new_bundle(root, "boundary")
    write_loop(bundle, "exactly-30.md", "Exactly at the window",
               opened=days_ago(30), created=days_ago(30), updated=days_ago(30))
    write_loop(bundle, "one-day-short.md", "One day inside the window",
               opened=days_ago(29), created=days_ago(29), updated=days_ago(29))

    result = run_script(bundle, "decay-loops.py")
    record("a loop exactly 30 days old IS a candidate under the default window",
           "exactly-30.md" in result.stdout, result.stdout)
    record("…while one 29 days old is not, so the window is 30 and not 29",
           "one-day-short.md" not in result.stdout
           and "1 candidate(s)" in result.stdout, result.stdout)
    record("…and the run says `stale >= 30d`, which is what the comparison does",
           "stale >= 30d" in result.stdout and "stale > 30d" not in result.stdout,
           result.stdout)

    applied = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply reports the same boundary it applied",
           "stale >= 30d" in applied.stdout and "1 loop(s) expired" in applied.stdout,
           applied.stdout)


def test_resolution_states_only_what_decay_checked(root):
    """The first sentence is the only one `resolved-loops.md` prints, and it
    used to assert absolutes decay never checks. Every claim is window-relative,
    nothing promises a reopen no procedure performs, and a sweep record left on
    purpose in the bundle, examining the loop 6 days ago, reaches none of it:
    decay no longer reads that file, so its paragraph cannot cite it."""
    bundle = new_bundle(root, "resolution-honesty")
    p = write_loop(bundle, "old.md", "Ship the quarterly export",
                   opened=days_ago(100), created=days_ago(100), updated=days_ago(100),
                   signal="a source showing the export was delivered.")
    write_sweep(bundle, {"/tracking/loops/old.md": days_ago(6)})

    result = run_script(bundle, "decay-loops.py", ["--apply"])
    para = resolution_of(p)
    record("--apply exits 0 with a sweep record present",
           result.returncode == 0, result.stdout + result.stderr)
    record("the sweep's examination date reaches no part of the paragraph",
           days_ago(6) not in para, para)
    record("…and neither does the sweep itself: no examination, no "
           "closure-sweep.json, no --skip-sweep",
           "examination" not in para and "closure-sweep.json" not in para
           and "--skip-sweep" not in para, para)
    record("no sentence promises that a later source reopens the loop — nothing "
           "reopens an expired loop, and this text is written permanently into "
           "every expired file", "reopen" not in para, para)
    record("the absolutes are gone: the claim is window-relative, tied to the "
           "last activity date",
           "no answer cited it" not in para
           and "no later source re-raised it" not in para
           and f"nothing re-raised or cited it after {days_ago(100)}" in para, para)

    parts = sentences(para)
    record("…still two to four sentences with the first standing alone",
           2 <= len(parts) <= 4 and parts[0].startswith("**Resolution:**")
           and "100 days" in parts[0], f"{len(parts)}: {parts}")

    index = run_script(bundle, "build-index.py")
    valid = run_script(bundle, "validate-okf.py")
    record("build-index.py and validate-okf.py still pass over the rewritten loop",
           index.returncode == 0 and valid.returncode == 0,
           f"index={index.returncode}\n{index.stderr}\nvalid={valid.returncode}\n{valid.stderr}")


# ---------------------------------------------------------------------------
# 12. the out-of-scope rule: a loop that is not the owner's leaves the lane
# ---------------------------------------------------------------------------
# A loop exists only when it relates to the bundle owner: the owner owes it
# (`owner`), is owed it (`owed_to`), or at least appears in `entities`. An
# open loop naming the owner in none of the three is a commitment between other
# people, and decay expires it at any age.


def fm_of(path):
    return path.read_text(encoding="utf-8").split("---\n", 2)[1]


def test_out_of_scope_expires_at_any_age(root):
    """H10, H11, E3, E4, E7."""
    bundle = new_bundle(root, "scope-any-age", owner_slug="me")
    third = write_loop(bundle, "third.md", "Jane sends Bob the deck",
                       opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                       owner=[JANE], owed_to=[BOB], entities=[BOB])
    mine = write_loop(bundle, "mine.md", "I send the deck",
                      opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                      owner=[ME], owed_to=[])
    owed = write_loop(bundle, "owed.md", "Jane sends me the deck",
                      opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                      owner=[JANE], owed_to=[ME])
    ent = write_loop(bundle, "ent.md", "Jane ships it, I am named",
                     opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                     owner=[JANE], owed_to=[], entities=[ME])
    ent_old = write_loop(bundle, "ent-old.md", "Jane ships it, I am named, long ago",
                         opened=days_ago(40), created=days_ago(40), updated=days_ago(40),
                         owner=[JANE], entities=[ME])
    both = write_loop(bundle, "both.md", "Jane and Bob, long ago",
                      opened=days_ago(100), created=days_ago(100), updated=days_ago(100),
                      owner=[JANE], entities=[BOB])

    dry = run_script(bundle, "decay-loops.py")
    record("a 1-day-old loop naming the owner nowhere is a candidate",
           "third.md" in dry.stdout, dry.stdout)
    record("the owner in `owner`, in `owed_to` only, or in `entities` only: none "
           "of those 1-day-old loops is a candidate (E3, E4)",
           all(n not in dry.stdout for n in ("mine.md", "owed.md", "/ent.md")),
           dry.stdout)
    record("…while the owner-in-entities loop 40 days silent is a stale "
           "candidate, on the 30-day clock (E3)",
           "ent-old.md  (40d stale)" in dry.stdout, dry.stdout)
    record("a loop both out of scope and stale is listed once, as out of scope (E7)",
           dry.stdout.count("both.md") == 1
           and "/tracking/loops/both.md  (out of scope" in dry.stdout, dry.stdout)
    record("no stderr note: this bundle has an owner.slug",
           NO_OWNER_NOTE not in dry.stderr, dry.stderr)

    result = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply exits 0", result.returncode == 0, result.stdout + result.stderr)
    record("--apply expires the 1-day-old third-party loop (H11)",
           "status: expired" in third.read_text(encoding="utf-8"),
           third.read_text(encoding="utf-8"))
    para = resolution_of(third)
    record("…with the out-of-scope resolution, naming the owner link it left out",
           para.startswith(f"**Resolution:** Expired on {TODAY.isoformat()} as out of scope")
           and f"`{ME}`" in para and "third-party commitment" in para, para)
    record("…whose first sentence stands alone, two to four sentences in all",
           2 <= len(sentences(para)) <= 4 and "out of scope" in sentences(para)[0],
           sentences(para))
    record("the in-scope 1-day-old loops stay open, with no resolution written",
           all("status: open" in p.read_text(encoding="utf-8")
               and "**Resolution:**" not in p.read_text(encoding="utf-8")
               for p in (mine, owed, ent)), "")
    record("the stale in-scope loop expires with the silence resolution",
           "days of silence" in resolution_of(ent_old)
           and "out of scope" not in resolution_of(ent_old), resolution_of(ent_old))
    both_text = both.read_text(encoding="utf-8")
    record("the stale and out-of-scope loop expires once, with the out-of-scope "
           "resolution and no silence one (E7)",
           both_text.count("**Resolution:**") == 1
           and both_text.count("expired:") == 1
           and "as out of scope" in resolution_of(both)
           and "days of silence" not in resolution_of(both), both_text)
    record("the summary splits the three expiries by kind",
           "3 loop(s) expired (2 out of scope, 1 stale >= 30d)" in result.stdout,
           result.stdout)

    index = run_script(bundle, "build-index.py")
    valid = run_script(bundle, "validate-okf.py")
    record("build-index.py and validate-okf.py pass over the out-of-scope expiries",
           index.returncode == 0 and valid.returncode == 0,
           f"index={index.returncode}\n{index.stderr}\nvalid={valid.returncode}\n"
           f"{valid.stdout}\n{valid.stderr}")


def test_out_of_scope_ignores_citation_and_dates(root):
    """E5, E6: the scope test reads no date. Updated yesterday, cited today, or
    carrying no parseable date at all, a third-party loop is a candidate."""
    bundle = new_bundle(root, "scope-no-dates", owner_slug="me")
    yesterday = write_loop(bundle, "yesterday.md", "Jane and Bob, touched yesterday",
                           opened=days_ago(200), created=days_ago(200),
                           updated=days_ago(1), owner=[JANE], entities=[BOB])
    cited = write_loop(bundle, "cited.md", "Jane and Bob, cited today",
                       opened=days_ago(200), created=days_ago(200),
                       updated=days_ago(200), owner=[JANE])
    undated = write_loop(bundle, "undated.md", "Jane and Bob, no date at all",
                         opened="someday", created="someday", updated="someday",
                         owner=[JANE])
    mine_undated = write_loop(bundle, "mine-undated.md", "Mine, no date at all",
                              opened="someday", created="someday", updated="someday",
                              owner=[ME])
    write_recall(bundle, {"/tracking/loops/cited.md": TODAY.isoformat()})

    dry = run_script(bundle, "decay-loops.py")
    record("a third-party loop updated yesterday is still a candidate (E5)",
           "yesterday.md  (out of scope" in dry.stdout, dry.stdout)
    record("…and so is one cited today in state/recall.json (E5)",
           "cited.md  (out of scope" in dry.stdout, dry.stdout)
    record("…and one carrying no parseable date at all (E6)",
           "/tracking/loops/undated.md  (out of scope" in dry.stdout, dry.stdout)
    record("…while an in-scope loop with no parseable date is still no candidate: "
           "the stale test is unchanged",
           "mine-undated.md" not in dry.stdout
           and "3 candidate(s) for decay (3 out of scope, 0 stale" in dry.stdout,
           dry.stdout)

    result = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply expires all three",
           all("status: expired" in p.read_text(encoding="utf-8")
               for p in (yesterday, cited, undated))
           and "status: open" in mine_undated.read_text(encoding="utf-8"),
           result.stdout + result.stderr)
    para = resolution_of(undated)
    record("the undated loop's resolution names no age and no activity date (E6)",
           para and "days" not in para and "last activity" not in para
           and "someday" not in para, para)
    record("…and the --apply line names no age either",
           "expired: /tracking/loops/undated.md  (out of scope)" in result.stdout,
           result.stdout)


def test_owner_slug_missing_skips_scope_rule(root):
    """E1: no owner.slug, whatever the reason, skips the rule with one note on
    stderr, rather than expiring every loop as naming nobody."""
    shapes = [
        ("no elephant.json", None),
        ("no owner key", json.dumps({"decay": {"loop_expiry_days": 30}})),
        ("empty slug", json.dumps({"owner": {"slug": "", "name": "Me"}})),
        ("only a name", json.dumps({"owner": {"name": "Me"}})),
        ("owner not a dict", json.dumps({"owner": "me"})),
        ("malformed JSON", "{ not json at all\n"),
    ]
    for label, raw in shapes:
        bundle = new_bundle(root, "no-owner-" + label.replace(" ", "-").replace(".", ""))
        if raw is not None:
            (bundle / "elephant.json").write_text(raw, encoding="utf-8")
        third = write_loop(bundle, "third.md", "Jane and Bob",
                           opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                           owner=[JANE], entities=[BOB])
        write_loop(bundle, "old.md", "Old stale loop",
                   opened=days_ago(100), created=days_ago(100), updated=days_ago(100),
                   owner=[JANE])
        dry = run_script(bundle, "decay-loops.py")
        record(f"{label}: the scan exits 0", dry.returncode == 0,
               dry.stdout + dry.stderr)
        record(f"{label}: the 1-day third-party loop is not a candidate; only the "
               "stale one is",
               "third.md" not in dry.stdout
               and "1 candidate(s) for decay (0 out of scope, 1 stale >= 30d" in dry.stdout,
               dry.stdout)
        record(f"{label}: one stderr note says the rule is skipped",
               dry.stderr.count(NO_OWNER_NOTE) == 1
               and "out-of-scope rule is skipped" in dry.stderr, dry.stderr)
        before = third.read_text(encoding="utf-8")
        applied = run_script(bundle, "decay-loops.py", ["--apply"])
        record(f"{label}: --apply exits 0 and leaves the third-party loop untouched",
               applied.returncode == 0 and third.read_text(encoding="utf-8") == before,
               applied.stdout + applied.stderr)


def test_scope_link_shapes(root):
    """E8, E9: the owner's link is matched by slug in every shape a loop spells
    it, and `owner.slug` is normalized the same way before comparing."""
    in_scope_shapes = [
        ("double-quoted-item", "owner", f' ["{ME}"]'),
        ("single-quoted-item", "owner", f" ['{ME}']"),
        ("block-sequence", "owner", f"\n  - {ME}"),
        ("quoted-block-sequence", "owner", f'\n  - "{ME}"'),
        ("bare-scalar", "owner", f" {ME}"),
        ("bare-slug", "owner", " [me]"),
        ("uppercase-slug", "owner", " [/entities/person/ME.md]"),
        ("other-kind-dir", "entities", " [/entities/org/me.md]"),
        ("owed-to-block-sequence", "owed_to", f"\n  - {JANE}\n  - {ME}"),
        ("with-trailing-comment", "owner", f" [{ME}]   # who owes the delivery"),
        # Valid YAML the first mirror of list_field() misread as empty or
        # partial, each one an out-of-scope expiry on the day the loop opened.
        ("zero-indent-block", "owner", f"\n- {ME}"),
        ("wrapped-flow-list", "entities", f" [/entities/project/a.md,\n  {ME}]"),
        ("comment-in-block", "owner", f"\n  - {JANE}\n  # the owner below\n  - {ME}"),
        # A spelling list_field() does not parse at all: the raw link scan is
        # the floor that keeps it in scope.
        ("yaml-tag", "owner", f" !!seq [{ME}]"),
        ("markdown-link", "owner", f' ["[Me]({ME})"]'),
        ("yaml-tag-bare-slug", "owner", " !!seq [me]"),
        # The first line of a wrapped list carries a comment, and the owner is
        # a bare slug on the next: the comment used to be glued to it.
        ("wrapped-list-comment-bare-slug", "owner", f" [{JANE},  # x\n  me]"),
        # A bare slug in each of the other two fields: the full-path link is
        # caught by the raw scan whatever SCOPE_FIELDS holds, a bare slug only
        # by the field itself being read.
        ("owed-to-bare-slug", "owed_to", " [me]"),
        ("entities-bare-slug", "entities", " [me]"),
        # Only the token test reads this one, and a slug is compared without
        # regard to case everywhere else, so the token test is too.
        ("yaml-tag-capitalized-slug", "owner", " !!seq [Me]"),
        # An apostrophe inside a plain item is content: it used to open a
        # "quote" that swallowed the `]` and glued it to the owner's slug.
        ("apostrophe-item-bare-slug", "owner", " [O'Neil, me]"),
    ]
    for owner_slug in ("me", "ME", ME):
        tag = {"me": "plain", "ME": "upper", ME: "path"}[owner_slug]
        bundle = new_bundle(root, "scope-shapes-" + tag, owner_slug=owner_slug)
        for name, key, raw in in_scope_shapes:
            kwargs = {"owner": [JANE], "owed_to": None, "entities": ()}
            kwargs[key] = raw
            write_loop(bundle, f"{name}.md", f"Shape {name}",
                       opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                       **kwargs)
        spaced = write_loop(bundle, "spaced-colon.md", "Shape spaced-colon",
                            opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                            owner=[ME])
        spaced.write_text(spaced.read_text(encoding="utf-8").replace(
            f"owner: [{ME}]", f"owner : [{ME}]"), encoding="utf-8")
        # A markdown link to the owner under a key the scope test does not
        # read: the entity-link floor covers the whole frontmatter, so it keeps
        # the loop in, the same as a plain link in that key does.
        write_loop(bundle, "markdown-link-other-key.md", "Shape markdown-link-other-key",
                   opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                   owner=[JANE], extra=f'participants: ["[Me]({ME})"]\n')
        write_loop(bundle, "lookalike.md", "A slug the owner's is a prefix of",
                   opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                   owner=["/entities/person/meyer.md"])
        # The slug as an ordinary word outside the three fields' values: in the
        # description, and in a comment on a scope line. Neither is a link.
        write_loop(bundle, "word-in-description.md", "Jane to send me the deck",
                   opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                   owner=[JANE])
        write_loop(bundle, "word-in-comment.md", "Jane's, commented",
                   opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                   owner=f" [{JANE}]   # not me")
        write_loop(bundle, "word-in-item-comment.md", "Jane's, a commented item",
                   opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                   owner=f"\n  - {JANE}  # not me")
        # A comment after a tab on the continuation line of a wrapped list: YAML
        # opens a comment after any whitespace, so the `me` in it is no token.
        write_loop(bundle, "word-in-wrapped-comment.md", "Jane's, wrapped, commented",
                   opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                   owner=f" [{JANE},\n  {BOB}]\t# ping me")
        dry = run_script(bundle, "decay-loops.py")
        names = [name for name, _k, _r in in_scope_shapes] + [
            "spaced-colon", "markdown-link-other-key"]
        missed = [name for name in names if f"/{name}.md" in dry.stdout]
        record(f"owner.slug given as {owner_slug!r}: the owner's link is matched in "
               "every shape (quoted, block sequence at any indent or with a comment "
               "line, a wrapped inline list, bare scalar, bare slug, uppercase, "
               "another kind directory, owed_to, a trailing comment, `owner :`, a "
               "YAML tag, a markdown link in a scope key or any other, a bare slug "
               "in owed_to or entities, a capitalized slug, an apostrophe in "
               "another item)",
               not missed, f"listed as candidates: {missed}\n{dry.stdout}")
        record(f"owner.slug given as {owner_slug!r}: …and the rule is still on: a "
               "lookalike slug, the slug as a word in the description or in a "
               "comment (after a space, or after a tab on a wrapped line), are no "
               "match",
               all(f"{n}.md  (out of scope" in dry.stdout
                   for n in ("lookalike", "word-in-description", "word-in-comment",
                             "word-in-item-comment", "word-in-wrapped-comment"))
               and "5 candidate(s) for decay (5 out of scope" in dry.stdout, dry.stdout)


RAFA_OLD = "/entities/person/rafael-girolineto.md"
RAFA_NEW = "/entities/person/rafael-giro.md"


def test_unresolvable_owner_skips_scope_rule(root):
    """E1, extended: an `owner.slug` that names no entity is no slug. The case
    that motivated it, end to end: the owner merges a duplicate of their own
    entity with `rename-entity.py --merge`, which rewrites every loop's link and
    never touches `elephant.json`. Read as is, the stale slug made every open
    loop out of scope, and the next unattended run expired the whole lane."""
    bundle = new_bundle(root, "owner-renamed", owner_slug="rafael-girolineto")
    write_entity(bundle, "rafael-giro")
    write_entity(bundle, "jane")
    shutil.copy2(ASSETS / "scripts" / "rename-entity.py",
                 bundle / "scripts" / "rename-entity.py")
    fresh = [write_loop(bundle, f"fresh-{i}.md", f"Mine, fresh {i}",
                        opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                        owner=[RAFA_OLD])
             for i in range(3)]
    stale = write_loop(bundle, "stale.md", "Mine, 100 days silent",
                       opened=days_ago(100), created=days_ago(100),
                       updated=days_ago(100), owner=[RAFA_OLD])

    before = run_script(bundle, "decay-loops.py")
    record("before the merge, only the stale loop is a candidate",
           "1 candidate(s) for decay (0 out of scope, 1 stale" in before.stdout
           and "names no entity file" not in before.stderr,
           before.stdout + before.stderr)

    merged = run_script(bundle, "rename-entity.py",
                        ["rafael-girolineto", "rafael-giro", "--merge"])
    record("the fixture holds: rename-entity.py --merge rewrote the loops and left "
           "elephant.json naming the old slug",
           merged.returncode == 0
           and all(RAFA_NEW in p.read_text(encoding="utf-8") for p in fresh)
           and not (bundle / "knowledge" / RAFA_OLD.lstrip("/")).exists()
           and "rafael-girolineto" in (bundle / "elephant.json").read_text(encoding="utf-8"),
           merged.stdout + merged.stderr)

    dry = run_script(bundle, "decay-loops.py")
    record("after the merge, the scope rule is skipped: no fresh loop is listed as "
           "out of scope",
           dry.returncode == 0
           and not any(p.name in dry.stdout for p in fresh)
           and "1 candidate(s) for decay (0 out of scope, 1 stale" in dry.stdout,
           dry.stdout)
    record("…and one stderr note names the slug and says no entity file backs it",
           dry.stderr.count("names no entity file") == 1
           and "`rafael-girolineto`" in dry.stderr
           and "out-of-scope rule is skipped" in dry.stderr, dry.stderr)
    applied = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply leaves the three fresh loops open and expires only the stale one",
           applied.returncode == 0
           and all("status: open" in p.read_text(encoding="utf-8") for p in fresh)
           and "status: expired" in stale.read_text(encoding="utf-8")
           and "days of silence" in resolution_of(stale),
           applied.stdout + applied.stderr)

    # The same guard with no rename in the story: a slug with no entity file.
    bare = new_bundle(root, "owner-no-entity", owner_slug="me", owner_entity=False)
    write_loop(bare, "third.md", "Jane's", owner=[JANE],
               opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    write_loop(bare, "mine.md", "Mine", owner=[ME],
               opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    dry = run_script(bare, "decay-loops.py")
    record("an owner.slug with no entity file under knowledge/entities/ skips the "
           "rule with the note",
           "third.md" not in dry.stdout and "0 candidate(s)" in dry.stdout
           and dry.stderr.count("names no entity file") == 1, dry.stdout + dry.stderr)
    write_entity(bare, "ME")
    dry = run_script(bare, "decay-loops.py")
    record("…while an entity file whose stem differs only in case backs the slug",
           "third.md  (out of scope" in dry.stdout
           and "names no entity file" not in dry.stderr, dry.stdout + dry.stderr)


def test_no_loop_names_the_owner_skips_scope_rule(root):
    """A resolvable `owner.slug` that no open loop names at all reads as the
    wrong entity far more often than as an owner with nothing left, so the rule
    is skipped for the run with one note, and those loops decay on the clock."""
    bundle = new_bundle(root, "owner-named-nowhere", owner_slug="me")
    fresh = [write_loop(bundle, f"third-{i}.md", f"Jane's {i}", owner=[JANE],
                        entities=[BOB], opened=days_ago(1), created=days_ago(1),
                        updated=days_ago(1))
             for i in range(2)]
    old = write_loop(bundle, "third-old.md", "Jane's, 100 days", owner=[JANE],
                     opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    dry = run_script(bundle, "decay-loops.py")
    record("no open loop names the owner: no loop is out of scope, the old one is stale",
           "1 candidate(s) for decay (0 out of scope, 1 stale" in dry.stdout
           and "third-old.md  (100d stale)" in dry.stdout, dry.stdout)
    record("…and one stderr note says why the rule was skipped",
           dry.stderr.count("no open loop names the owner") == 1
           and "rather than expiring all 3" in dry.stderr, dry.stderr)
    applied = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply leaves the fresh third-party loops open, expiring only on silence",
           all("status: open" in p.read_text(encoding="utf-8") for p in fresh)
           and "days of silence" in resolution_of(old), applied.stdout + applied.stderr)

    write_loop(bundle, "mine.md", "Mine", owner=[ME],
               opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    dry = run_script(bundle, "decay-loops.py")
    record("one open loop naming the owner switches the rule back on",
           "2 candidate(s) for decay (2 out of scope, 0 stale" in dry.stdout
           and "no open loop names the owner" not in dry.stderr,
           dry.stdout + dry.stderr)


def write_named_entity(bundle, entity_slug, title, aliases=()):
    """An entity file with a given title and aliases, for the duplicate test."""
    path = write_entity(bundle, entity_slug)
    text = path.read_text(encoding="utf-8")
    text = text.replace(f'title: "{entity_slug}"', f'title: "{title}"').replace(
        "aliases: []", "aliases: [" + ", ".join(aliases) + "]")
    path.write_text(text, encoding="utf-8")
    return path


def test_partial_owner_duplicate(root):
    """The "no open loop names the owner" guard is all or nothing. With a
    duplicate of the owner's entity that only some loops link, it does not
    fire, and those loops used to expire as out of scope. A loop linking an
    entity carrying one of the owner's names is read as naming the owner."""
    bundle = new_bundle(root, "owner-partial-duplicate", owner_slug="rafael-girolineto",
                        owner_entity=False)
    # The alias the duplicate matches comes last, after one holding an
    # apostrophe: the list reader used to take that `'` for an unclosed quote
    # and read the last alias as `Giro]`, which matched nothing.
    write_named_entity(bundle, "rafael-girolineto", "Rafael Girolineto",
                       ["rafapg", "O'Neil", "Giro"])
    write_named_entity(bundle, "giro", "Giro")                  # the duplicate, by alias
    write_named_entity(bundle, "rafael-g", "Rafael Girolineto")  # the duplicate, by title
    write_named_entity(bundle, "zelda-girolineto", "Zelda Girolineto")
    write_named_entity(bundle, "jane", "Jane")
    mine = write_loop(bundle, "mine.md", "Mine", owner=[RAFA_OLD],
                      opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    dup_alias = write_loop(bundle, "dup-alias.md", "Mine, linked to the duplicate",
                           owner=["/entities/person/giro.md"],
                           opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    dup_title = write_loop(bundle, "dup-title.md", "Owed to me, linked to the duplicate",
                           owner=[JANE], owed_to=["/entities/person/rafael-g.md"],
                           opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    write_loop(bundle, "relative.md", "A relative's, not the owner's",
               owner=["/entities/person/zelda-girolineto.md"],
               opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    write_loop(bundle, "third.md", "Jane's", owner=[JANE],
               opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    dry = run_script(bundle, "decay-loops.py")
    record("a loop linking a duplicate of the owner (same alias or same title) is no "
           "out-of-scope candidate",
           "dup-alias.md" not in dry.stdout and "dup-title.md" not in dry.stdout
           and "mine.md" not in dry.stdout, dry.stdout)
    record("…while a relative sharing a surname, and a third party, still are",
           "relative.md  (out of scope" in dry.stdout and "third.md  (out of scope" in dry.stdout
           and "2 candidate(s) for decay (2 out of scope" in dry.stdout, dry.stdout)
    record("…and one stderr note names the duplicates and the merge that fixes them",
           dry.stderr.count("carry one of the owner's names") == 1
           and "/entities/*/giro.md" in dry.stderr and "/entities/*/rafael-g.md" in dry.stderr
           and "zelda" not in dry.stderr and "rename-entity.py --merge" in dry.stderr,
           dry.stderr)
    run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply leaves the loops linking a duplicate open",
           all("status: open" in p.read_text(encoding="utf-8")
               for p in (mine, dup_alias, dup_title)), dry.stdout)


def test_duplicate_never_arms_the_scope_rule(root):
    """The "no open loop names the owner" guard reads the owner's own slug,
    never a duplicate's. `owner.slug` here names the wrong entity (`alex`,
    titled "Alex"), a third party carries "Alex" as an alias, and every loop
    the owner really owes links their actual entity. Counting the duplicate
    let that third party's one loop arm the rule, and the next `--apply`
    expired the owner's whole lane as out of scope."""
    bundle = new_bundle(root, "duplicate-arms-guard", owner_slug="alex",
                        owner_entity=False)
    write_named_entity(bundle, "alex", "Alex")
    write_named_entity(bundle, "alex-moreno", "Alex Moreno", ["Alex"])
    write_named_entity(bundle, "alexandra-lima", "Alexandra Lima")
    owed = [write_loop(bundle, f"owed-{i}.md", f"Mine {i}",
                       owner=["/entities/person/alexandra-lima.md"],
                       opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
            for i in range(3)]
    moreno = write_loop(bundle, "moreno.md", "Moreno's",
                        owner=["/entities/person/alex-moreno.md"],
                        opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    dry = run_script(bundle, "decay-loops.py")
    record("a loop linking only a duplicate does not switch the scope rule on: "
           "the guard's note fires and no loop is out of scope",
           dry.stderr.count("no open loop names the owner") == 1
           and "0 candidate(s) for decay (0 out of scope" in dry.stdout,
           dry.stdout + dry.stderr)
    applied = run_script(bundle, "decay-loops.py", ["--apply"])
    record("…and --apply leaves the owner's loops open",
           applied.returncode == 0
           and all("status: open" in p.read_text(encoding="utf-8")
                   for p in owed + [moreno]),
           applied.stdout + applied.stderr)
    write_loop(bundle, "named.md", "Links the configured owner entity",
               owner=["/entities/person/alex.md"],
               opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    dry = run_script(bundle, "decay-loops.py")
    record("…while one loop linking the configured owner entity arms it, and the "
           "duplicate still keeps its own loop in",
           "no open loop names the owner" not in dry.stderr
           and all(f"owed-{i}.md  (out of scope" in dry.stdout for i in range(3))
           and "moreno.md" not in dry.stdout and "named.md" not in dry.stdout,
           dry.stdout + dry.stderr)


def test_owner_duplicate_name_shapes(root):
    """owner_duplicates() compares every name the same way: an entity file's
    own slug is one of its names, case is ignored, a folded (`>-`) title is
    read as its text rather than as the indicator, and one unreadable entity
    file skips only itself, with a note."""
    bundle = new_bundle(root, "duplicate-name-shapes", owner_slug="alex",
                        owner_entity=False)
    owner_entity = write_named_entity(bundle, "alex", "Alex Doe", ["Lex", "Kit"])
    owner_entity.write_text(owner_entity.read_text(encoding="utf-8").replace(
        'title: "Alex Doe"', "title: >-\n  Alex\n  Doe"), encoding="utf-8")
    write_named_entity(bundle, "lex", "L. Example")       # by slug only
    write_named_entity(bundle, "kit-b", "KIT")            # by title, other case
    folded_dup = write_named_entity(bundle, "alex-d", "x")  # folded title, same text
    folded_dup.write_text(folded_dup.read_text(encoding="utf-8").replace(
        'title: "x"', "title: >-\n  alex doe"), encoding="utf-8")
    other = write_named_entity(bundle, "jane-two", "x")     # folded title, unrelated
    other.write_text(other.read_text(encoding="utf-8").replace(
        'title: "x"', "title: >-\n  Jane Two"), encoding="utf-8")
    (bundle / "knowledge" / "entities" / "person" / "folder.md").mkdir()
    loops = {}
    for name, target in (("mine", "alex"), ("by-slug", "lex"), ("by-case", "kit-b"),
                         ("by-folded", "alex-d"), ("unrelated", "jane-two")):
        loops[name] = write_loop(bundle, f"{name}.md", f"Loop {name}",
                                 owner=[f"/entities/person/{target}.md"],
                                 opened=days_ago(1), created=days_ago(1),
                                 updated=days_ago(1))
    dry = run_script(bundle, "decay-loops.py")
    record("a duplicate by its own slug, by a title in another case, and by a "
           "folded title is no out-of-scope candidate, past a directory named "
           "`folder.md`",
           dry.returncode == 0 and not any(
               f"{n}.md" in dry.stdout for n in ("mine", "by-slug", "by-case", "by-folded")),
           dry.stdout + dry.stderr)
    record("…while an entity whose folded title is unrelated is no duplicate: "
           "two `>-` titles do not match on the indicator",
           "unrelated.md  (out of scope" in dry.stdout
           and "1 candidate(s) for decay (1 out of scope" in dry.stdout
           and "jane-two" not in dry.stderr, dry.stdout + dry.stderr)

    # One entity file that cannot be read, in-process: a permission bit does
    # not hold on every runner, so the read itself is made to fail.
    import contextlib
    import io
    import pathlib
    decay = load_script("decay-loops.py")
    decay.KNOWLEDGE = bundle / "knowledge"
    real_read = pathlib.Path.read_text

    def flaky(self, *a, **kw):
        if self.name == "kit-b.md":
            raise OSError("simulated unreadable file")
        return real_read(self, *a, **kw)

    err = io.StringIO()
    pathlib.Path.read_text = flaky
    try:
        with contextlib.redirect_stderr(err):
            got = decay.owner_duplicates("alex")
    finally:
        pathlib.Path.read_text = real_read
    record("one unreadable entity file skips only itself: the other duplicates "
           "are still found, and one note counts the skipped file",
           got == ["alex-d", "lex"]
           and err.getvalue().count("could not be read") == 1
           and "/entities/person/kit-b.md" in err.getvalue(),
           f"{got}\n{err.getvalue()}")


def test_unreadable_updated_is_no_candidate(root):
    """An `updated:` line that is present but no YYYY-MM-DD date (a pt-BR date,
    an unpadded one, a month 13) used to be skipped as if absent: the loop fell
    back to `opened`, 89 days back, and expired as silent the run after it was
    re-raised. And of two `updated:` lines only the first was read."""
    bundle = new_bundle(root, "unreadable-updated")
    recent = TODAY - datetime.timedelta(days=1)
    spellings = {
        "pt-br": recent.strftime("%d/%m/%Y"),
        "month-13": f"{recent.year}-13-{recent.day:02d}",
        "words": "yesterday",
    }
    loops = {}
    for tag, value in spellings.items():
        path = write_loop(bundle, f"bad-{tag}.md", f"Re-raised, updated as {tag}",
                          opened=days_ago(89), created=days_ago(89))
        path.write_text(path.read_text(encoding="utf-8").replace(
            f"updated: {days_ago(89)}", f"updated: {value}"), encoding="utf-8")
        loops[tag] = path
    dup = write_loop(bundle, "dup-updated.md", "Bumped by appending a second line",
                     opened=days_ago(89), created=days_ago(89), updated=days_ago(89))
    dup.write_text(dup.read_text(encoding="utf-8").replace(
        f"updated: {days_ago(89)}\n", f"updated: {days_ago(89)}\nupdated: {days_ago(1)}\n"),
        encoding="utf-8")
    old = write_loop(bundle, "old.md", "Silent, readable dates",
                     opened=days_ago(89), created=days_ago(89), updated=days_ago(89))
    record("the fixture holds: each bad loop carries its unreadable `updated:`",
           all(f"updated: {spellings[t]}\n" in p.read_text(encoding="utf-8")
               for t, p in loops.items()), "")
    dry = run_script(bundle, "decay-loops.py")
    record("an unreadable `updated:` makes no stale candidate, whatever `opened` says",
           not any(p.name in dry.stdout for p in loops.values())
           and "old.md  (89d stale)" in dry.stdout
           and "1 candidate(s) for decay (0 out of scope, 1 stale" in dry.stdout, dry.stdout)
    record("…with one stderr note per such loop, naming it and the value",
           all(dry.stderr.count(f"/tracking/loops/{p.name} has `updated: {spellings[t]}`") == 1
               for t, p in loops.items()), dry.stderr)
    record("of two `updated:` lines the newer one counts", "dup-updated.md" not in dry.stdout,
           dry.stdout)
    run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply expires only the loop whose dates all read",
           "status: expired" in old.read_text(encoding="utf-8")
           and all("status: open" in p.read_text(encoding="utf-8")
                   for p in (*loops.values(), dup)), "")


def load_script(name):
    """A shipped script loaded in-process from plugin/assets/scripts/, to reach
    its pure functions. The checkout refusal is guarded on __main__."""
    spec = importlib.util.spec_from_file_location(
        "_under_test_" + name.replace("-", "_").replace(".py", ""),
        ASSETS / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_list_field_mirrors_close_loops(root):
    """decay-loops.py and close-loops.py each carry a list_field(). A shape one
    reads and the other misreads costs close-loops a ranking signal and decay an
    irreversible expiry, so the two must agree on every shape, and read each
    the way YAML does."""
    decay = load_script("decay-loops.py")
    close = load_script("close-loops.py")
    shapes = [
        ("inline", "owner", f"owner: [{JANE}, {ME}]\n", [JANE, ME]),
        ("indented block", "owner", f"owner:\n  - {JANE}\n  - {ME}\nstatus: open\n",
         [JANE, ME]),
        ("zero-indent block", "owner", f"owner:\n- {JANE}\n- {ME}\nstatus: open\n",
         [JANE, ME]),
        ("comment in block", "owner",
         f"owner:\n  - {JANE}\n  # next\n  - {ME}\nstatus: open\n", [JANE, ME]),
        ("wrapped inline", "entities",
         f"entities: [/entities/project/a.md,\n  {ME}]\nstatus: open\n",
         ["/entities/project/a.md", ME]),
        ("unclosed inline stops at the next key", "entities",
         f"entities: [{ME},\nstatus: open\n", [ME]),
        ("space before the colon", "owner", f"owner : [{ME}]\n", [ME]),
        ("bare scalar", "owner", f"owner: {ME}\n", [ME]),
        ("another key's prefix is not the key", "owner",
         f"owner_note: [{JANE}]\nowner: [{ME}]\n", [ME]),
        ("missing", "owed_to", f"owner: [{ME}]\n", []),
        ("comment inside a wrapped inline list", "owner",
         f"owner: [{JANE}  # the counterpart\n  , {ME}]  # and the owner\nstatus: open\n",
         [JANE, ME]),
        # An apostrophe inside a plain item is content (a quote opens a quoted
        # item only where an item starts): it used to swallow the `]`.
        ("apostrophe in the first item", "aliases",
         "aliases: [O'Neil, Kit]\ntags: []\n", ["O'Neil", "Kit"]),
        ("apostrophe in a middle item", "aliases",
         "aliases: [Kit, O'Neil, Rowan]\ntags: []\n", ["Kit", "O'Neil", "Rowan"]),
        ("apostrophe in the last item", "aliases",
         "aliases: [Kit, O'Neil]\ntags: []\n", ["Kit", "O'Neil"]),
        ("apostrophe, then a trailing comment", "aliases",
         "aliases: [O'Neil, Kit]  # nick\ntags: []\n", ["O'Neil", "Kit"]),
        ("apostrophe on a wrapped list", "aliases",
         "aliases: [O'Neil,\n  Kit]\ntags: []\n", ["O'Neil", "Kit"]),
        ("apostrophe on a wrapped list with a comment", "aliases",
         "aliases: [O'Neil,  # x\n  Kit]\ntags: []\n", ["O'Neil", "Kit"]),
        ("a single-quoted item with an escaped quote", "aliases",
         "aliases: ['O''Neil', Kit]\n", ["O'Neil", "Kit"]),
        ("a double-quoted item holding an apostrophe", "aliases",
         "aliases: [\"O'Neil\", Kit]\n", ["O'Neil", "Kit"]),
        ("a double-quoted item holding ` #`", "aliases",
         "aliases: [\"a #b\", Kit]\n", ["a #b", "Kit"]),
        ("the owner after an apostrophe", "owner",
         f"owner: [O'Neil, {ME}]\nstatus: open\n", ["O'Neil", ME]),
    ]
    for label_, key, block, expected in shapes:
        got_d, got_c = decay.list_field(block, key), close.list_field(block, key)
        record(f"list_field, {label_}: both scripts read {expected}",
               got_d == expected and got_c == expected,
               f"decay={got_d}\nclose={got_c}")
    # A block item's `-` also starts an item, so a quote after it still opens
    # a quoted scalar and its ` #` stays content: scope_text() cuts every
    # line of the three fields with this function, block items included.
    raw, want = '- "a #b"  # c', '- "a #b"'
    got_d, got_c = decay._cut_line_comment(raw), close._cut_line_comment(raw)
    record("_cut_line_comment: a quoted block item keeps its ` #`, in both scripts",
           got_d == want and got_c == want, f"decay={got_d!r}\nclose={got_c!r}")


def test_legacy_loop_without_owed_to(root):
    """E2: a loop filed before `owed_to` existed carries no such line. It reads
    as an empty list, scope is decided on `owner` and `entities`, and the
    validator accepts the file as it always did."""
    bundle = new_bundle(root, "legacy-owed-to", owner_slug="me")
    mine = write_loop(bundle, "mine.md", "Mine, legacy shape",
                      opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                      owner=[ME], owed_to=None)
    named = write_loop(bundle, "named.md", "Named in entities, legacy shape",
                       opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                       owner=[JANE], owed_to=None, entities=[ME])
    third = write_loop(bundle, "third.md", "Jane's, legacy shape",
                       opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                       owner=[JANE], owed_to=None)
    record("the fixture really is the legacy shape: no `owed_to:` line",
           all("owed_to" not in fm_of(p) for p in (mine, named, third)), fm_of(mine))

    index = run_script(bundle, "build-index.py")
    valid = run_script(bundle, "validate-okf.py")
    record("validate-okf.py passes over loops without `owed_to`",
           index.returncode == 0 and valid.returncode == 0,
           f"{index.stderr}\n{valid.stdout}\n{valid.stderr}")

    dry = run_script(bundle, "decay-loops.py")
    record("owner in `owner` or in `entities`: in scope without the field",
           "mine.md" not in dry.stdout and "named.md" not in dry.stdout, dry.stdout)
    record("…and a legacy third-party loop is out of scope",
           "third.md  (out of scope" in dry.stdout
           and "1 candidate(s) for decay (1 out of scope, 0 stale" in dry.stdout,
           dry.stdout)


def test_dry_run_labels_and_split(root):
    """A3: every line carries its label, out-of-scope lines come first (by path)
    and stale ones after (oldest first), and both summaries split by kind."""
    bundle = new_bundle(root, "labels-and-split", owner_slug="me")
    write_loop(bundle, "b-third.md", "Third party b", owner=[JANE],
               opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    write_loop(bundle, "a-third.md", "Third party a", owner=[JANE],
               opened=days_ago(90), created=days_ago(90), updated=days_ago(90))
    write_loop(bundle, "c-stale.md", "Mine, 40 days", owner=[ME],
               opened=days_ago(40), created=days_ago(40), updated=days_ago(40))
    write_loop(bundle, "d-stale.md", "Mine, 50 days", owner=[ME],
               opened=days_ago(50), created=days_ago(50), updated=days_ago(50))
    write_loop(bundle, "e-fresh.md", "Mine, fresh", owner=[ME],
               opened=days_ago(5), created=days_ago(5), updated=days_ago(5))

    dry = run_script(bundle, "decay-loops.py")
    lines = [ln for ln in dry.stdout.splitlines() if ln.startswith("/tracking/")]
    scope_label = "(out of scope: the owner is in none of owner, owed_to, entities)"
    record("each line carries its label: the scope sentence, or the age",
           lines == [
               f"/tracking/loops/a-third.md  {scope_label}",
               f"/tracking/loops/b-third.md  {scope_label}",
               "/tracking/loops/d-stale.md  (50d stale)",
               "/tracking/loops/c-stale.md  (40d stale)",
           ], "\n".join(lines))
    record("the trailing count splits the kinds",
           "4 candidate(s) for decay (2 out of scope, 2 stale >= 30d, dry-run, "
           "pass --apply to expire)" in dry.stdout, dry.stdout)

    applied = run_script(bundle, "decay-loops.py", ["--apply"])
    expired = [ln for ln in applied.stdout.splitlines() if ln.startswith("expired:")]
    record("--apply labels each expiry the same way, in the same order",
           expired == [
               "expired: /tracking/loops/a-third.md  (out of scope)",
               "expired: /tracking/loops/b-third.md  (out of scope)",
               "expired: /tracking/loops/d-stale.md  (50d stale)",
               "expired: /tracking/loops/c-stale.md  (40d stale)",
           ], "\n".join(expired))
    record("…and its summary splits them too",
           "4 loop(s) expired (2 out of scope, 2 stale >= 30d). Run build-index.py next."
           in applied.stdout, applied.stdout)


def test_except_leaves_a_candidate_open(root):
    """E15, A2: `--except <link>` keeps a named candidate out of the run, dry
    run and `--apply` alike, and counts it in neither split. A claim (H13, E14)
    needs no flag: the re-scan no longer lists a loop the owner's link was
    added to."""
    bundle = new_bundle(root, "except", owner_slug="me")
    kept = write_loop(bundle, "kept.md", "Rejected at the gate, no claim",
                      opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                      owner=[JANE])
    gone = write_loop(bundle, "gone.md", "Approved at the gate",
                      opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                      owner=[JANE])
    stale = write_loop(bundle, "stale.md", "Mine, stale",
                       opened=days_ago(60), created=days_ago(60), updated=days_ago(60),
                       owner=[ME])
    claimed = write_loop(bundle, "claimed.md", "Claimed at the gate",
                         opened=days_ago(60), created=days_ago(60),
                         updated=TODAY.isoformat(), owner=[JANE], owed_to=[ME])
    before = kept.read_text(encoding="utf-8")

    dry = run_script(bundle, "decay-loops.py", ["--except", "/tracking/loops/kept.md"])
    record("dry run with --except leaves the named loop out, counted in neither split",
           "kept.md" not in dry.stdout
           and "2 candidate(s) for decay (1 out of scope, 1 stale >= 30d" in dry.stdout,
           dry.stdout)
    record("a claimed loop (the owner's link in owed_to, updated today) is no "
           "candidate at all (H13)", "claimed.md" not in dry.stdout, dry.stdout)

    result = run_script(bundle, "decay-loops.py",
                        ["--apply", "--except", "/tracking/loops/kept.md",
                         "--except", "/tracking/loops/claimed.md"])
    record("--apply --except exits 0", result.returncode == 0,
           result.stdout + result.stderr)
    record("the excepted loop stays open and byte-identical",
           kept.read_text(encoding="utf-8") == before, kept.read_text(encoding="utf-8"))
    record("…while the rest expire",
           "status: expired" in gone.read_text(encoding="utf-8")
           and "status: expired" in stale.read_text(encoding="utf-8")
           and "status: open" in claimed.read_text(encoding="utf-8")
           and "2 loop(s) expired (1 out of scope, 1 stale >= 30d)" in result.stdout,
           result.stdout)
    record("a link to a loop that is no candidate (the claim took) is ignored "
           "with one stderr note",
           result.stderr.count("--except /tracking/loops/claimed.md matches no candidate") == 1
           and "kept.md" not in result.stderr, result.stderr)

    rerun = run_script(bundle, "decay-loops.py", ["--apply"])
    record("the next run without the flag expires it: the reject held for one run only",
           "status: expired" in kept.read_text(encoding="utf-8")
           and "1 loop(s) expired (1 out of scope, 0 stale" in rerun.stdout,
           rerun.stdout)


def test_except_typo_refuses_the_run(root):
    """A `--except` link that names no loop file is a typo, and the note for a
    loop that is no longer a candidate is the one the procedure reads as a
    snooze or claim having taken. Printed for the typo too, it let `--apply`
    expire the very loops the owner had just rejected. It now ends the run with
    exit 2 before anything is scanned or written."""
    bundle = new_bundle(root, "except-typo", owner_slug="me")
    stale = write_loop(bundle, "stale.md", "Mine, stale, rejected at the gate",
                       opened=days_ago(60), created=days_ago(60), updated=days_ago(60),
                       owner=[ME])
    oos = write_loop(bundle, "oos.md", "Jane's, rejected at the gate",
                     opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                     owner=[JANE])
    before = {p: p.read_text(encoding="utf-8") for p in (stale, oos)}
    applied = run_script(bundle, "decay-loops.py",
                         ["--apply", "--except", "/tracking/loops/stale-.md",
                          "--except", "/tracking/loop/oos.md"])
    record("--apply with two mistyped --except links exits 2 and writes nothing",
           applied.returncode == 2 and "expired:" not in applied.stdout
           and all(p.read_text(encoding="utf-8") == t for p, t in before.items()),
           applied.stdout + applied.stderr)
    record("…with one error per link naming it, and never the `matches no "
           "candidate` note the procedure reads as success",
           applied.stderr.count("names no loop file") == 2
           and "/tracking/loops/stale-.md" in applied.stderr
           and "/tracking/loop/oos.md" in applied.stderr
           and "matches no candidate" not in applied.stderr, applied.stderr)
    mixed = run_script(bundle, "decay-loops.py",
                       ["--apply", "--except", "/tracking/loops/stale.md",
                        "--except", "/tracking/loops/oos"])
    record("one right link does not let a wrong one through: still exit 2, "
           "nothing written",
           mixed.returncode == 2 and mixed.stderr.count("names no loop file") == 1
           and all(p.read_text(encoding="utf-8") == t for p, t in before.items()),
           mixed.stdout + mixed.stderr)
    dry = run_script(bundle, "decay-loops.py", ["--except", "/tracking/loops/stale-.md"])
    record("the dry run refuses the same way", dry.returncode == 2
           and "names no loop file" in dry.stderr and "candidate(s)" not in dry.stdout,
           dry.stdout + dry.stderr)


def test_except_link_spellings(root):
    """`--except` reads its value leniently, the documented safe direction: the
    procedure is prose a model follows, and a spelling that matched nothing
    would print one note and let `--apply` expire the loop the owner had just
    declined to expire."""
    bundle = new_bundle(root, "except-spellings", owner_slug="me")
    kept = write_loop(bundle, "kept.md", "Rejected at the gate, no claim",
                      opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
                      owner=[JANE])
    write_loop(bundle, "gone.md", "Approved at the gate",
               opened=days_ago(1), created=days_ago(1), updated=days_ago(1),
               owner=[JANE])
    write_loop(bundle, "mine.md", "Mine", owner=[ME],
               opened=days_ago(1), created=days_ago(1), updated=days_ago(1))
    spellings = [
        "tracking/loops/kept.md",
        "knowledge/tracking/loops/kept.md",
        "/knowledge/tracking/loops/kept.md",
        "\\tracking\\loops\\kept.md",
        "knowledge\\tracking\\loops\\kept.md",
        "  /tracking/loops/kept.md  ",
    ]
    for spelling in spellings:
        dry = run_script(bundle, "decay-loops.py", ["--except", spelling])
        record(f"--except {spelling!r} leaves kept.md out, counted in neither split, "
               "with no `matches no candidate` note",
               "kept.md" not in dry.stdout
               and "1 candidate(s) for decay (1 out of scope, 0 stale" in dry.stdout
               and "matches no candidate" not in dry.stderr,
               dry.stdout + dry.stderr)
    before = kept.read_text(encoding="utf-8")
    applied = run_script(bundle, "decay-loops.py",
                         ["--apply", "--except", "knowledge/tracking/loops/kept.md"])
    record("--apply with a `knowledge/`-prefixed --except leaves the loop byte-identical",
           applied.returncode == 0 and kept.read_text(encoding="utf-8") == before
           and "1 loop(s) expired (1 out of scope, 0 stale" in applied.stdout,
           applied.stdout + applied.stderr)


# ---------------------------------------------------------------------------
# 13. the decay skill's prose says what the script does
# ---------------------------------------------------------------------------

DECAY_SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "decay"
DEPRECATION = ("`--skip-sweep` is accepted and ignored: this script no longer "
               "reads `state/closure-sweep.json`.")


def flat_text(path):
    return " ".join(path.read_text(encoding="utf-8").split())


def test_decay_prose_contract(root):
    skill = flat_text(DECAY_SKILL_DIR / "SKILL.md")
    proc = flat_text(DECAY_SKILL_DIR / "procedure.md")
    both = skill + " " + proc
    record("the decay skill states the `--skip-sweep` deprecation once",
           both.count(DEPRECATION) == 1, DEPRECATION)
    record("…and names closure-sweep.json nowhere else: decay no longer reads it",
           "closure-sweep.json" not in both.replace(DEPRECATION, ""),
           [i for i in range(len(both)) if both.startswith("closure-sweep.json", i)])
    record("no candidate is `held back` any more", "held back" not in both.lower())
    record("no `exactly two writers` of `updated:` survives",
           "exactly **two** writers" not in both and "exactly two writers" not in both)
    record("the default window is 30 in SKILL.md and in procedure.md",
           "default 30" in skill and "default 30" in proc and "default 45" not in both,
           "")
    record("procedure.md carries the claim rule: `owed_to`, the claim, `--except`",
           all(tok in proc for tok in ("owed_to", "claim", "--except")), "")
    record("the bump is never moved backwards",
           "never moved backwards" in both or "never backwards" in both)
    record("procedure.md's step 5 log line splits the kinds",
           "**Decay**: N loops expired (M out of scope, K >=Xd stale)" in proc, "")
    record("procedure.md passes every rejected candidate, stale or out of scope, as "
           "`--except`, so a reject never becomes an expiry in its own run, and "
           "reads the script's `matches no candidate` note as the edit having taken",
           "Pass every candidate rejected in step 2, stale or out of scope" in proc
           and "Pass every out-of-scope candidate rejected without a claim" not in proc
           and "`--except <link> matches no candidate this run`" in proc
           and "--except {link} matches no candidate this run" in
           (ASSETS / "scripts" / "decay-loops.py").read_text(encoding="utf-8"), "")
    record("procedure.md reads exit 2 as a mistyped `--except` link that expired "
           "nothing, and the `matches no candidate` note as success only for a "
           "link naming a real loop file",
           "makes the script exit 2 before it scans or writes anything" in proc
           and "prints only for a link naming a real loop file" in proc
           and "names no loop file" in
           (ASSETS / "scripts" / "decay-loops.py").read_text(encoding="utf-8"), "")
    record("procedure.md: a failed recall roll ends the run before the scan, and "
           "unattended it is an environment failure filed to the backlog",
           "ends the run before the scan" in proc
           and "**Decay**: environment failure (recall roll failed)" in proc
           and "backlog.py add decay-recall-roll-failed" in proc
           and "a failure is not fatal" not in proc, "")


def guarded(fn, root):
    try:
        fn(root)
    except Exception:  # noqa: BLE001 - report and continue to the next check group
        record(f"{fn.__name__} raised an unexpected exception", False, traceback.format_exc())


def main():
    print("elephant-mem test_decay — decay-loops.py regression tests")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print()

    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-mem-test-decay-"))
    print(f"scratch root: {scratch_root}\n")

    for fn in (
        test_dry_run_no_changes,
        test_apply_expires_only_old_open,
        test_recent_update_protects,
        test_other_statuses_untouched,
        test_expired_field_written,
        test_custom_threshold,
        test_invalid_threshold_values,
        test_build_index_excludes_expired_after_apply,
        test_template_shaped_loop_decays,
        test_status_spelling_agrees_with_build_index,
        test_recall_citation_protects,
        test_stale_citation_does_not_protect,
        test_recall_never_ages_a_loop,
        test_recall_degraded_shapes,
        test_sweep_is_not_read,
        test_skip_sweep_is_a_noop,
        test_expiry_writes_a_resolution,
        test_expiry_boundary_day,
        test_resolution_states_only_what_decay_checked,
        test_out_of_scope_expires_at_any_age,
        test_out_of_scope_ignores_citation_and_dates,
        test_owner_slug_missing_skips_scope_rule,
        test_scope_link_shapes,
        test_unresolvable_owner_skips_scope_rule,
        test_no_loop_names_the_owner_skips_scope_rule,
        test_partial_owner_duplicate,
        test_duplicate_never_arms_the_scope_rule,
        test_owner_duplicate_name_shapes,
        test_unreadable_updated_is_no_candidate,
        test_list_field_mirrors_close_loops,
        test_legacy_loop_without_owed_to,
        test_dry_run_labels_and_split,
        test_except_leaves_a_candidate_open,
        test_except_typo_refuses_the_run,
        test_except_link_spellings,
        test_decay_prose_contract,
    ):
        guarded(fn, scratch_root)

    print()
    print("Summary")
    print("-------")
    n_pass = 0
    for label, passed in checks:
        status = "PASS" if passed else "FAIL"
        if passed:
            n_pass += 1
        print(f"  {status:4s}  {label}")
    total = len(checks)
    print(f"\n{n_pass}/{total} checks passed.")
    shutil.rmtree(scratch_root, ignore_errors=True)
    return 0 if n_pass == total and total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
