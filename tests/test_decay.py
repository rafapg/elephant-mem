#!/usr/bin/env python3
"""Standalone regression tests for `plugin/assets/scripts/decay-loops.py` —
the automatic open-loop decay-to-`expired` script.

Covers: dry-run makes no changes; --apply expires only stale `status: open`
loops; a recent `updated` (re-mention resets the clock) protects an
otherwise-old loop; `done`/`dropped`/already-`expired` loops are never
touched; the `expired: YYYY-MM-DD` field is stamped correctly; the default
45-day threshold vs. a custom `elephant.json` -> `decay.loop_expiry_days`;
and that `build-index.py`, run after `--apply`, drops the newly-expired loops
from the open-loop count/board/manifest.

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


def new_bundle(root, name, expiry_days=None):
    """Minimal throwaway bundle: decay-loops.py + build-index.py (the latter
    only needed by the cross-script integration check), a reserved log.md,
    and an empty knowledge/tracking/loops/ dir — mirrors the real bundle path
    confirmed against ~/elephant-mem."""
    bundle = root / name
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    for f in ("decay-loops.py", "build-index.py"):
        shutil.copy2(ASSETS / "scripts" / f, bundle / "scripts" / f)
    if expiry_days is not None:
        (bundle / "elephant.json").write_text(
            json.dumps({"decay": {"loop_expiry_days": expiry_days}}) + "\n", encoding="utf-8"
        )
    (bundle / "knowledge" / "tracking" / "loops").mkdir(parents=True, exist_ok=True)
    (bundle / "knowledge" / "log.md").write_text("# Log\n", encoding="utf-8")
    return bundle


def write_loop(bundle, name, desc, status="open", opened=None, created=None, updated=None, extra=""):
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
    )
    path = bundle / "knowledge" / "tracking" / "loops" / name
    path.write_text(text, encoding="utf-8")
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
    record("--apply leaves the recently-updated loop untouched",
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
