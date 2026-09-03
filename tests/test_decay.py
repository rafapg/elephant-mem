#!/usr/bin/env python3
"""Standalone regression tests for `plugin/assets/scripts/decay-loops.py` —
the automatic open-loop decay-to-`expired` script.

Covers: dry-run makes no changes; --apply expires only stale `status: open`
loops; a recent `updated` (re-mention resets the clock) protects an
otherwise-old loop; `done`/`dropped`/already-`expired` loops are never
touched; the `expired: YYYY-MM-DD` field is stamped correctly; the default
45-day threshold vs. a custom `elephant.json` -> `decay.loop_expiry_days`;
that `build-index.py`, run after `--apply`, drops the newly-expired loops
from the open-loop count/board/manifest; that `--apply` refuses a candidate
`state/closure-sweep.json` does not show `close-loops` examining after its own
last activity, names it, prints the command that would examine it and still
exits 0, while `--skip-sweep` bypasses that gate; that every expiry writes a
`**Resolution:**` paragraph in the same shape a closure does; and that a recent
citation in
`state/recall.json` counts as a fourth activity date while every degraded
shape of that record — absent, empty, malformed, no entry for this loop, no
`recall.py` in the bundle at all — leaves the scan behaving exactly as it did
before recall existed.

Pure stdlib, Python 3.10+, same scaffolding style as tests/smoke.py and
tests/test_index.py: every check builds its own throwaway bundle under a
tempdir and drives the shipped scripts via subprocess (sys.executable) — no
shell-outs, no third-party deps.

Exit code 0 only if every check below passes.
"""
import datetime
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


def new_bundle(root, name, expiry_days=None, with_recall=True):
    """Minimal throwaway bundle: decay-loops.py + build-index.py (the latter
    only needed by the cross-script integration check) + recall.py (the sibling
    decay reads the citation date through), a reserved log.md, and an empty
    knowledge/tracking/loops/ dir — mirrors the real bundle path confirmed
    against ~/elephant-mem.

    `with_recall=False` builds the bundle an installed user has when `update`
    has not yet re-synced `scripts/`: decay is there, its sibling is not."""
    bundle = root / name
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    scripts = ["decay-loops.py", "build-index.py", "validate-okf.py"]
    if with_recall:
        scripts.append("recall.py")
    for f in scripts:
        shutil.copy2(ASSETS / "scripts" / f, bundle / "scripts" / f)
    if expiry_days is not None:
        (bundle / "elephant.json").write_text(
            json.dumps({"decay": {"loop_expiry_days": expiry_days}}) + "\n", encoding="utf-8"
        )
    (bundle / "knowledge" / "tracking" / "loops").mkdir(parents=True, exist_ok=True)
    (bundle / "knowledge" / "log.md").write_text("# Log\n", encoding="utf-8")
    return bundle


def write_loop(bundle, name, desc, status="open", opened=None, created=None,
               updated=None, extra="", signal=None):
    opened = opened or TODAY.isoformat()
    created = created or opened
    updated = updated or created
    text = (
        "---\n"
        "type: open-loop\n"
        f"description: {desc}\n"
        "owner: []\n"
        f"status: {status}\n"
        "entities: []\n"
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
    """Write `state/closure-sweep.json`, the record `close-loops` keeps and
    `decay-loops.py --apply` gates on. `entries` maps a loop's bundle-absolute
    path to its examination date, or to an `(examined, outcome)` pair; `raw`
    overrides the whole file with a literal string, for the malformed shape.

    Hand-built rather than produced by running the `close-loops` routine: the
    routine writes this file from prose (its `procedure.md` -> "The sweep
    record"), and tests/test_close_loops.py owns whether that recipe writes what
    this script reads. What this suite pins is decay's reading of it.
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
        loops[link] = {"examined": examined, "outcome": outcome}
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

    # --skip-sweep because this check is about the dates, not about the sweep
    # gate: with the gate on, neither loop would be expirable and the check
    # would pass for the wrong reason.
    result = run_script(bundle, "decay-loops.py", ["--apply", "--skip-sweep"])
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

    run_script(bundle, "decay-loops.py", ["--apply", "--skip-sweep"])
    text = p.read_text(encoding="utf-8")
    record("--apply leaves the recently-updated loop untouched even with the "
           "sweep gate off — it is the date that protects it",
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

    apply_result = run_script(bundle, "decay-loops.py", ["--apply", "--skip-sweep"])
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

    run_script(bundle, "decay-loops.py", ["--apply", "--skip-sweep"])
    text = p.read_text(encoding="utf-8")
    record(f"expired: {TODAY.isoformat()} field stamped", f"expired: {TODAY.isoformat()}" in text, text)
    record("status flipped to expired", "status: expired" in text, text)
    record("file still exists (never deleted)", p.exists())


# ---------------------------------------------------------------------------
# 6. default 45d threshold vs. a custom elephant.json -> decay.loop_expiry_days
# ---------------------------------------------------------------------------

def test_custom_threshold(root):
    # 50 days old IS a candidate under the default (no elephant.json) 45d threshold.
    bundle_default = new_bundle(root, "threshold-default")
    write_loop(bundle_default, "borderline.md", "50-day-old loop",
               opened=days_ago(50), created=days_ago(50), updated=days_ago(50))
    result_default = run_script(bundle_default, "decay-loops.py")
    record("50-day-old loop IS a candidate under the default 45d threshold",
           "borderline.md" in result_default.stdout, result_default.stdout)

    # Raising the threshold via elephant.json protects the same-age loop.
    bundle_raised = new_bundle(root, "threshold-raised", expiry_days=60)
    write_loop(bundle_raised, "borderline.md", "50-day-old loop",
               opened=days_ago(50), created=days_ago(50), updated=days_ago(50))
    result_raised = run_script(bundle_raised, "decay-loops.py")
    record("same 50-day-old loop is NOT a candidate once elephant.json raises the threshold to 60d",
           "borderline.md" not in result_raised.stdout, result_raised.stdout)

    # Lowering the threshold via elephant.json catches a loop the default would miss.
    bundle_lowered = new_bundle(root, "threshold-lowered", expiry_days=10)
    write_loop(bundle_lowered, "young.md", "20-day-old loop",
               opened=days_ago(20), created=days_ago(20), updated=days_ago(20))
    result_lowered = run_script(bundle_lowered, "decay-loops.py")
    record("20-day-old loop becomes a candidate once elephant.json lowers the threshold to 10d",
           "young.md" in result_lowered.stdout, result_lowered.stdout)


# ---------------------------------------------------------------------------
# 7. build-index.py, run after --apply, drops expired loops from the counts
# ---------------------------------------------------------------------------

def test_build_index_excludes_expired_after_apply(root):
    bundle = new_bundle(root, "build-index-integration")
    write_loop(bundle, "old.md", "Old stale loop to expire",
               opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    write_loop(bundle, "fresh.md", "Fresh loop stays open",
               opened=days_ago(2), created=days_ago(2), updated=days_ago(2))
    # The full path, gate included: `close-loops` examined the stale loop after
    # its last activity and left it open, which is what clears it for expiry.
    write_sweep(bundle, {"/tracking/loops/old.md": days_ago(3)})

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
# open-loop.md ships `status: open          # open | done | dropped`, and the
# model that writes a loop from it keeps that comment: it is the documentation.
# field() read the whole line, so `field(block, "status") != "open"` was true
# for every template-derived loop and the entire script was a no-op. On every
# machine — this script has no PyYAML path to fall back to.

STATUS_DOC = "        # open | done | dropped"


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
    record("a loop that kept `# open | done | dropped` is seen as open and "
           "listed as a candidate (the script used to find none, ever)",
           "old.md" in result.stdout and "1 candidate(s)" in result.stdout, result.stdout)
    record("…and its `updated:` is read through its own comment, so the age is "
           "the date's, not a parse failure's",
           "100d stale" in result.stdout, result.stdout)
    record("…while a `done` loop carrying the same comment is still not a "
           "candidate — the reader did not simply learn to match everything",
           "done.md" not in result.stdout, result.stdout)

    run_script(bundle, "decay-loops.py", ["--apply", "--skip-sweep"])
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

    run_script(bundle, "decay-loops.py", ["--apply", "--skip-sweep"])
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
    record("no recall.py in the bundle: and the scan says nothing about it",
           result.stderr.strip() == "", result.stderr)


# ---------------------------------------------------------------------------
# 10. the sweep gate: --apply only expires what close-loops has examined
# ---------------------------------------------------------------------------
# Expiry is a verdict of silence. Silence nothing has read is not evidence, so
# `--apply` consults `state/closure-sweep.json` per loop and refuses a candidate
# `close-loops` has not examined after that loop's own last activity.


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


def test_gate_refuses_the_unexamined(root):
    """E15: a candidate no sweep entry covers is refused by name, the command
    that would examine it is printed, and the run still exits 0."""
    bundle = new_bundle(root, "gate-unexamined")
    p = write_loop(bundle, "old.md", "Old stale loop",
                   opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    before = p.read_text(encoding="utf-8")

    dry = run_script(bundle, "decay-loops.py")
    record("dry-run still lists the unexamined candidate, marked held back",
           "old.md" in dry.stdout and "held back" in dry.stdout, dry.stdout)

    result = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply over an unexamined candidate exits 0 — a lane nothing has "
           "read is not an error", result.returncode == 0,
           f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
    record("…names the loop it refused", "/tracking/loops/old.md" in result.stdout,
           result.stdout)
    record("…prints the close-loops command that would examine it",
           "scripts/close-loops.py" in result.stdout, result.stdout)
    record("…and reports 0 expired", "0 loop(s) expired" in result.stdout, result.stdout)
    record("the refused loop is byte-identical after the run",
           p.read_text(encoding="utf-8") == before, p.read_text(encoding="utf-8"))


def test_gate_expires_the_examined(root):
    """H8: examined after its own last activity, left open — expirable."""
    bundle = new_bundle(root, "gate-examined")
    cleared = write_loop(bundle, "cleared.md", "Examined and still silent",
                         opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    stale_exam = write_loop(bundle, "stale-exam.md", "Examined before it last moved",
                            opened=days_ago(200), created=days_ago(200), updated=days_ago(60))
    closed = write_loop(bundle, "closed.md", "Examined and closed",
                        opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    write_sweep(bundle, {
        "/tracking/loops/cleared.md": days_ago(4),
        "/tracking/loops/stale-exam.md": days_ago(90),
        "/tracking/loops/closed.md": (days_ago(4), "done"),
    })

    result = run_script(bundle, "decay-loops.py", ["--apply"])
    record("--apply exits 0 with a sweep record present", result.returncode == 0,
           result.stdout + result.stderr)
    record("a loop examined after its last activity and left open is expired",
           "status: expired" in cleared.read_text(encoding="utf-8"),
           cleared.read_text(encoding="utf-8"))
    record("a loop whose last activity is newer than its examination is held back "
           "— it moved after the routine read it",
           "status: open" in stale_exam.read_text(encoding="utf-8")
           and "stale-exam.md" in result.stdout,
           stale_exam.read_text(encoding="utf-8") + "\n---\n" + result.stdout)
    record("a loop the sweep records as closed is not decay's to expire",
           "status: open" in closed.read_text(encoding="utf-8"),
           closed.read_text(encoding="utf-8"))
    record("…and the run reports one expiry and two held back",
           "1 loop(s) expired" in result.stdout and "2 candidate(s) held back" in result.stdout,
           result.stdout)


def test_skip_sweep_bypasses_the_gate(root):
    """E16: `--apply --skip-sweep` over the same unexamined lane expires it."""
    bundle = new_bundle(root, "gate-skipped")
    a = write_loop(bundle, "a.md", "Old stale loop",
                   opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    b = write_loop(bundle, "b.md", "Another old stale loop",
                   opened=days_ago(120), created=days_ago(120), updated=days_ago(120))

    result = run_script(bundle, "decay-loops.py", ["--apply", "--skip-sweep"])
    record("--apply --skip-sweep exits 0", result.returncode == 0,
           result.stdout + result.stderr)
    record("every candidate expires with the gate bypassed, examined or not",
           "status: expired" in a.read_text(encoding="utf-8")
           and "status: expired" in b.read_text(encoding="utf-8")
           and "2 loop(s) expired" in result.stdout, result.stdout)
    record("…and nothing is reported as held back",
           "held back" not in result.stdout, result.stdout)
    record("the resolution of a loop no examination reached says exactly that, "
           "rather than claiming one",
           "no `close-loops` examination is on record" in resolution_of(a)
           and "--skip-sweep" in resolution_of(a), resolution_of(a))


def test_lost_sweep_parks_decay(root):
    """E18: absent or malformed, the record reads as empty — every loop reads as
    never examined and nothing expires, rather than everything expiring."""
    for label, raw in (("malformed", "{ not json at all\n"),
                       ("empty object", "{}\n"),
                       ("no loops key", '{"schema": 1}\n')):
        bundle = new_bundle(root, "gate-lost-" + label.replace(" ", "-"))
        p = write_loop(bundle, "old.md", "Old stale loop",
                       opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
        write_sweep(bundle, {}, raw=raw)

        result = run_script(bundle, "decay-loops.py", ["--apply"])
        record(f"closure-sweep.json {label}: --apply exits 0",
               result.returncode == 0, result.stdout + result.stderr)
        record(f"closure-sweep.json {label}: nothing expires — expiry is parked, "
               "not corrupted",
               "status: open" in p.read_text(encoding="utf-8")
               and "0 loop(s) expired" in result.stdout,
               result.stdout + "\n---\n" + p.read_text(encoding="utf-8"))
        if label == "malformed":
            record("closure-sweep.json malformed: one warning on stderr, no crash",
                   "closure-sweep.json is unreadable" in result.stderr, result.stderr)

    # …and the way out is the flag, not a hand-repaired record.
    bundle = new_bundle(root, "gate-lost-escape")
    p = write_loop(bundle, "old.md", "Old stale loop",
                   opened=days_ago(100), created=days_ago(100), updated=days_ago(100))
    write_sweep(bundle, {}, raw="{ not json at all\n")
    result = run_script(bundle, "decay-loops.py", ["--apply", "--skip-sweep"])
    record("--skip-sweep is the deliberate way out of a lost record",
           "status: expired" in p.read_text(encoding="utf-8"), result.stdout)


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
    write_sweep(bundle, {"/tracking/loops/old.md": days_ago(6)})

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
    record("…whose first sentence stands alone: it dates the expiry, gives the "
           "silence in days and says the examination found nothing, so "
           "resolved-loops.md can print it and nothing else",
           first.startswith("**Resolution:**") and TODAY.isoformat() in first
           and "100 days" in first and "close-loops" in first, first)
    record("…and names the last-activity date and the window it fell past",
           days_ago(100) in para and "45-day" in para, para)
    record("…referring to state/closure-sweep.json without a leading slash — a "
           "bundle-absolute link there would point outside knowledge/",
           "state/closure-sweep.json" in para and "/state/closure-sweep.json" not in para,
           para)

    index = run_script(bundle, "build-index.py")
    valid = run_script(bundle, "validate-okf.py")
    record("build-index.py and validate-okf.py both pass over the rewritten loop "
           "— the paragraph is prose the validator accepts",
           index.returncode == 0 and valid.returncode == 0,
           f"index={index.returncode}\n{index.stdout}\n{index.stderr}\n"
           f"valid={valid.returncode}\n{valid.stdout}\n{valid.stderr}")


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
        test_build_index_excludes_expired_after_apply,
        test_template_shaped_loop_decays,
        test_recall_citation_protects,
        test_stale_citation_does_not_protect,
        test_recall_never_ages_a_loop,
        test_recall_degraded_shapes,
        test_gate_refuses_the_unexamined,
        test_gate_expires_the_examined,
        test_skip_sweep_bypasses_the_gate,
        test_lost_sweep_parks_decay,
        test_expiry_writes_a_resolution,
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
