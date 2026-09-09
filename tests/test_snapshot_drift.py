#!/usr/bin/env python3
"""Standalone regression tests for `plugin/assets/scripts/snapshot-drift.py`
— the `snapshot`-tag drift advisory `maintain` runs.

Covers: `field_list()` unquoting a double- or single-quoted inline list item
(the bug that made every `tags: ["snapshot", ...]`-style snapshot invisible
to `main()`'s own `"snapshot" in tags` membership check, reporting zero
drift no matter what actually drifted); the existing trailing-comment strip
this function already had (regression lock, not new coverage); `unquote()`'s
escape handling directly; and an end-to-end sanity pass over the drift
logic itself (`relates-to` vs `shared-entities` buckets, the
`deprecated`/`superseded` exclusion, the no-snapshots message) — none of
which had any test before this file, since the script shipped with zero
coverage.

Pure stdlib, Python 3.10+, same scaffolding style as tests/test_decay.py and
tests/test_recall.py: an in-process import of a throwaway bundle's own copy
for the pure-function checks (so the plugin-checkout `__main__` guard never
fires), and a subprocess run of the same copy for the end-to-end checks.

Exit code 0 only if every check below passes.
"""
import datetime
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "plugin" / "assets"
SCRIPT = ASSETS / "scripts" / "snapshot-drift.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

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


def days_ago(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


def new_bundle(root, name):
    bundle = Path(root) / name
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    (bundle / "knowledge" / "facts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT, bundle / "scripts" / "snapshot-drift.py")
    return bundle


def import_copy(bundle, name):
    """Import the bundle's own copy, so BUNDLE/FACTS resolve into the
    tempdir and the plugin-checkout `__main__` guard never fires (it only
    triggers on a direct script run, not an import)."""
    spec = importlib.util.spec_from_file_location(name, bundle / "scripts" / "snapshot-drift.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_script(bundle):
    return subprocess.run(
        [sys.executable, str(bundle / "scripts" / "snapshot-drift.py")],
        cwd=str(bundle), capture_output=True, text=True, encoding="utf-8",
    )


def write_fact(bundle, slug, tags="[]", entities="[]", relates_to="[]",
               updated=None, occurred=None, status="active"):
    updated = updated or TODAY.isoformat()
    occurred = occurred or updated
    text = (
        "---\n"
        "type: fact\n"
        f"status: {status}\n"
        f"tags: {tags}\n"
        f"entities: {entities}\n"
        "relations:\n"
        f"  relates-to: {relates_to}\n"
        f"occurred: {occurred}\n"
        f"updated: {updated}\n"
        "---\n\n"
        f"{slug}\n"
    )
    path = bundle / "knowledge" / "facts" / f"{slug}.md"
    path.write_text(text, encoding="utf-8")
    return path


# --- unit checks: the pure functions, imported in-process -----------------
# One bundle, one import, reused across every record() below (test_recall.py's
# pattern) — field_list()/unquote() are pure string functions with no
# filesystem dependency, so mounting a fresh bundle per assertion bought
# nothing but six redundant tempdir mounts and module compiles.

def test_field_list_and_unquote_unit_checks(root):
    bundle = new_bundle(root, "unit")
    mod = import_copy(bundle, "sd_unit")

    got = mod.field_list('tags: ["snapshot", "beleza"]', "tags")
    record(
        "field_list() strips double quotes from inline list items",
        got == ["snapshot", "beleza"],
        f"got {got!r}",
    )

    got = mod.field_list("tags: ['snapshot', 'ownership']", "tags")
    record(
        "field_list() strips single quotes from inline list items",
        got == ["snapshot", "ownership"],
        f"got {got!r}",
    )

    got = mod.field_list("tags: [snapshot, ownership]", "tags")
    record(
        "field_list() leaves already-bare items untouched (no regression)",
        got == ["snapshot", "ownership"],
        f"got {got!r}",
    )

    # Regression lock for the older fix (96db93e): a comment on the same line
    # as an inline list must not be swallowed into the list.
    got = mod.field_list(
        "entities: []          # bundle-absolute links, e.g. [/entities/…]", "entities",
    )
    record(
        "field_list() still strips a trailing comment, not just quotes",
        got == [],
        f"got {got!r}",
    )

    # The two fixes composed: a quoted list AND a trailing comment together.
    got = mod.field_list('tags: ["snapshot"]   # editorial rollup', "tags")
    record(
        "field_list() handles quoted items and a trailing comment together",
        got == ["snapshot"],
        f"got {got!r}",
    )

    cases = [
        ('"plain"', "plain"),
        ("'plain'", "plain"),
        ('"she said \\"hi\\""', 'she said "hi"'),
        ("'it''s here'", "it's here"),
        ("bare", "bare"),
    ]
    ok = all(mod.unquote(raw) == expected for raw, expected in cases)
    record(
        "unquote() handles double/single quotes and their escapes",
        ok,
        f"cases: {cases}",
    )


# --- end-to-end checks: the shipped script, via subprocess -----------------

def test_quoted_snapshot_detected_as_drifted(root):
    """The regression this fix exists for: before it, a `tags: ["snapshot",
    ...]` fact was never recognized as a snapshot at all, so main()'s own
    `"snapshot" in f["tags"]` filter silently excluded it — 0 of 0 snapshots,
    indistinguishable from "nothing has drifted"."""
    bundle = new_bundle(root, "e2e-quoted")
    write_fact(bundle, "snap", tags='["snapshot"]', updated=days_ago(30))
    write_fact(bundle, "newer", tags="[]", entities="[]",
               relates_to="[/facts/snap.md]", updated=days_ago(1))
    result = run_script(bundle)
    record(
        'a snapshot tagged tags: ["snapshot"] (double-quoted) is recognized and reported drifted',
        result.returncode == 0
        and "1 of 1 snapshot(s) may have drifted." in result.stdout
        and "DRIFTED: /facts/snap.md" in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_unquoted_snapshot_still_detected(root):
    bundle = new_bundle(root, "e2e-bare")
    write_fact(bundle, "snap", tags="[snapshot]", updated=days_ago(30))
    write_fact(bundle, "newer", tags="[]", entities="[]",
               relates_to="[/facts/snap.md]", updated=days_ago(1))
    result = run_script(bundle)
    record(
        "a snapshot tagged tags: [snapshot] (unquoted) is still recognized (no regression)",
        result.returncode == 0 and "1 of 1 snapshot(s) may have drifted." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_relates_to_bucket_reported_high_signal(root):
    bundle = new_bundle(root, "e2e-relates")
    write_fact(bundle, "snap", tags="[snapshot]", updated=days_ago(30))
    write_fact(bundle, "newer", relates_to="[/facts/snap.md]", updated=days_ago(1))
    result = run_script(bundle)
    record(
        "a relates-to signal is bucketed as high-signal (relates-to), not shared-entities",
        "1 relates-to (high-signal), 0 shared-entities (review)" in result.stdout,
        f"stdout:\n{result.stdout}",
    )


def test_shared_entities_bucket_reported_as_review(root):
    bundle = new_bundle(root, "e2e-shared")
    write_fact(bundle, "snap", tags="[snapshot]", entities='["/entities/person/a.md", "/entities/person/b.md"]',
               updated=days_ago(30))
    write_fact(bundle, "newer", entities='["/entities/person/a.md", "/entities/person/b.md"]',
               updated=days_ago(1))
    result = run_script(bundle)
    record(
        ">=2 shared entities (no relates-to link) is bucketed as shared-entities, not relates-to",
        "0 relates-to (high-signal), 1 shared-entities (review)" in result.stdout,
        f"stdout:\n{result.stdout}",
    )


def test_single_shared_entity_is_not_enough(root):
    bundle = new_bundle(root, "e2e-one-shared")
    write_fact(bundle, "snap", tags="[snapshot]", entities='["/entities/person/a.md"]', updated=days_ago(30))
    write_fact(bundle, "newer", entities='["/entities/person/a.md"]', updated=days_ago(1))
    result = run_script(bundle)
    record(
        "one shared entity (below SHARE_THRESHOLD) never signals drift on its own",
        "0 of 1 snapshot(s) may have drifted." in result.stdout,
        f"stdout:\n{result.stdout}",
    )


def test_deprecated_fact_excluded_from_signal(root):
    bundle = new_bundle(root, "e2e-deprecated")
    write_fact(bundle, "snap", tags="[snapshot]", updated=days_ago(30))
    write_fact(bundle, "newer", relates_to="[/facts/snap.md]",
               updated=days_ago(1), status="deprecated")
    result = run_script(bundle)
    record(
        "a deprecated newer fact never counts as a drift signal",
        "0 of 1 snapshot(s) may have drifted." in result.stdout,
        f"stdout:\n{result.stdout}",
    )


def test_deprecated_fact_excluded_regardless_of_case(root):
    """status is compared case-insensitively, matching build-index.py's
    fact_status() normalization — status: Deprecated excludes a fact from
    the drift signal exactly like status: deprecated does."""
    bundle = new_bundle(root, "e2e-deprecated-case")
    write_fact(bundle, "snap", tags="[snapshot]", updated=days_ago(30))
    write_fact(bundle, "newer", relates_to="[/facts/snap.md]",
               updated=days_ago(1), status="Deprecated")
    result = run_script(bundle)
    record(
        "status: Deprecated (capitalized) is excluded from the drift signal, same as lowercase",
        "0 of 1 snapshot(s) may have drifted." in result.stdout,
        f"stdout:\n{result.stdout}",
    )


def test_deprecated_fact_excluded_when_status_is_quoted(root):
    """field_scalar() unquotes before returning: status: "Deprecated" (valid
    YAML, unusual for an enum field) must exclude the fact exactly like an
    unquoted, lowercase status: deprecated does."""
    bundle = new_bundle(root, "e2e-deprecated-quoted")
    write_fact(bundle, "snap", tags="[snapshot]", updated=days_ago(30))
    write_fact(bundle, "newer", relates_to="[/facts/snap.md]",
               updated=days_ago(1), status='"Deprecated"')
    result = run_script(bundle)
    record(
        'status: "Deprecated" (quoted) is excluded from the drift signal, same as unquoted lowercase',
        "0 of 1 snapshot(s) may have drifted." in result.stdout,
        f"stdout:\n{result.stdout}",
    )


def test_no_snapshots_message(root):
    bundle = new_bundle(root, "e2e-none")
    write_fact(bundle, "plain", tags="[]", updated=days_ago(1))
    result = run_script(bundle)
    record(
        "a bundle with facts but no snapshot tag prints the no-snapshots message and exits 0",
        result.returncode == 0 and "No `snapshot` facts found." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_ci_wiring(root):
    """test_backlog.py shipped in 0.1.0-beta.7 and went a full release unrun in
    CI because ci.yml has no glob — a new suite needs its own `- run:` line, or
    it silently never executes. Assert this one has it, rather than trusting a
    human to remember."""
    ci = CI_WORKFLOW.read_text(encoding="utf-8") if CI_WORKFLOW.exists() else ""
    record(
        "this suite has its own `- run:` line in ci.yml, which has no glob",
        "- run: python tests/test_snapshot_drift.py" in ci,
    )


def guarded(fn, root):
    try:
        fn(root)
    except Exception:  # noqa: BLE001 - report and continue to the next check
        record(f"{fn.__name__} raised an unexpected exception", False, traceback.format_exc())


def main():
    print("elephant-mem test_snapshot_drift — snapshot-drift.py regression tests")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print()

    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-mem-test-snapshot-drift-"))
    print(f"scratch root: {scratch_root}\n")

    for fn in (
        test_field_list_and_unquote_unit_checks,
        test_quoted_snapshot_detected_as_drifted,
        test_unquoted_snapshot_still_detected,
        test_relates_to_bucket_reported_high_signal,
        test_shared_entities_bucket_reported_as_review,
        test_single_shared_entity_is_not_enough,
        test_deprecated_fact_excluded_from_signal,
        test_deprecated_fact_excluded_regardless_of_case,
        test_deprecated_fact_excluded_when_status_is_quoted,
        test_no_snapshots_message,
        test_ci_wiring,
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
