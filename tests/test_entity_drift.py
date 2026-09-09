#!/usr/bin/env python3
"""Standalone regression tests for `plugin/assets/scripts/entity-drift.py`
— the entity-hub staleness advisory `maintain` will run alongside the
existing snapshot drift-check (`.bb/entity-hub-staleness/spec.md`).

Covers every row of the spec's `## Behavior` table (E1-E13): a hub with no
qualifying newer fact, a never-backlinked hub, a missing/unparseable
`updated`, `deprecated`/`superseded` facts excluded from the signal (case-
insensitively, on both the fact and the hub side), the `entity_drift_max`
cap (config default, config override, `--max` override, `--max` refused
below 1), the zero-candidates message, the plugin-checkout refusal guard,
PyYAML-indifference, a re-tended hub dropping out of the next run, the
zero-hubs message, a fact with no parseable date never contributing to
`n_newer`, and `day_gap()`'s defensive degrade-to-0 on unparseable/missing
input.

Pure stdlib, Python 3.10+, same scaffolding as tests/test_snapshot_drift.py:
a throwaway bundle per check, each copy of the script run standalone via
subprocess so its own `ROOT`/`BUNDLE` resolve into the tempdir.

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
SCRIPT = ASSETS / "scripts" / "entity-drift.py"
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
    (bundle / "knowledge" / "entities").mkdir(parents=True, exist_ok=True)
    (bundle / "knowledge" / "facts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT, bundle / "scripts" / "entity-drift.py")
    return bundle


def import_copy(bundle, name):
    """Import the bundle's own copy in-process, for the one pure function
    (day_gap()) with no CLI-observable path of its own to drive via
    subprocess. Mirrors tests/test_snapshot_drift.py's helper of the same
    name."""
    spec = importlib.util.spec_from_file_location(name, bundle / "scripts" / "entity-drift.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_hub(bundle, slug, updated="__unset__", status="active", subdir="concept"):
    """A `type: entity` hub at knowledge/entities/<subdir>/<slug>.md, its
    bundle-absolute path is `/entities/<subdir>/<slug>.md`. `updated="__unset__"`
    writes today; pass `None` to write the key with no value (E3), or a string
    for an explicit (possibly unparseable) date."""
    if updated == "__unset__":
        updated = TODAY.isoformat()
    updated_line = "updated:\n" if updated is None else f"updated: {updated}\n"
    text = (
        "---\n"
        "type: entity\n"
        f"status: {status}\n"
        f"{updated_line}"
        "---\n\n"
        f"{slug}\n"
    )
    d = bundle / "knowledge" / "entities" / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.md").write_text(text, encoding="utf-8")
    return f"/entities/{subdir}/{slug}.md"


def write_fact(bundle, slug, entities="[]", occurred="__unset__", updated=None,
               status="active"):
    """A `type: fact` at knowledge/facts/<slug>.md. `occurred="__unset__"`
    writes today; `None` for either date writes the key with no value
    (unparseable/missing, E13)."""
    if occurred == "__unset__":
        occurred = TODAY.isoformat()
    occurred_line = "occurred:\n" if occurred is None else f"occurred: {occurred}\n"
    updated_line = "updated:\n" if updated is None else f"updated: {updated}\n"
    text = (
        "---\n"
        "type: fact\n"
        f"status: {status}\n"
        f"entities: {entities}\n"
        f"{occurred_line}"
        f"{updated_line}"
        "---\n\n"
        f"{slug}\n"
    )
    (bundle / "knowledge" / "facts" / f"{slug}.md").write_text(text, encoding="utf-8")


def run_script(bundle, args=None):
    return subprocess.run(
        [sys.executable, str(bundle / "scripts" / "entity-drift.py"), *(args or [])],
        cwd=str(bundle), capture_output=True, text=True, encoding="utf-8",
    )


def write_config(bundle, entity_drift_max):
    (bundle / "elephant.json").write_text(
        json.dumps({"maintain": {"entity_drift_max": entity_drift_max}}),
        encoding="utf-8",
    )


# --- E1 / E2 — no signal, no candidate -------------------------------------

def test_no_newer_fact_is_not_a_candidate(root):
    """E1: a hub with no qualifying fact newer than its `updated` never
    appears, even though it does have a backlink."""
    bundle = new_bundle(root, "e1-no-newer")
    hub = write_hub(bundle, "acme", updated=days_ago(1))
    write_fact(bundle, "old", entities=f"[{hub}]", occurred=days_ago(30))
    result = run_script(bundle)
    record(
        "a hub with only an older backlinking fact is not flagged",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_never_backlinked_hub_is_not_a_candidate(root):
    """E2: a hub with zero backlinking facts at all has no signal to compare
    against, and is not flagged."""
    bundle = new_bundle(root, "e2-no-backlink")
    write_hub(bundle, "lonely", updated=days_ago(90))
    write_fact(bundle, "unrelated", entities="[]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "a hub never named by any fact's entities: is not flagged",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


# --- E3 — missing/unparseable hub `updated` --------------------------------

def test_hub_missing_updated_is_skipped_not_flagged(root):
    """E3: a hub with no `updated` at all is skipped from the check entirely
    — not flagged, even with a newer backlinking fact."""
    bundle = new_bundle(root, "e3-missing-updated")
    hub = write_hub(bundle, "noupdated", updated=None)
    write_fact(bundle, "fresh", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "a hub with a missing updated: is skipped, not flagged",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_hub_unparseable_updated_is_skipped_not_flagged(root):
    """E3: same, for an `updated` that fails to parse as an ISO date rather
    than being merely absent."""
    bundle = new_bundle(root, "e3-bad-updated")
    hub = write_hub(bundle, "badupdated", updated="not-a-date")
    write_fact(bundle, "fresh", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "a hub with an unparseable updated: is skipped, not flagged",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


# --- E4 — deprecated/superseded facts excluded -----------------------------

def test_deprecated_fact_excluded_from_signal(root):
    """E4: a deprecated qualifying fact does not count toward n_newer."""
    bundle = new_bundle(root, "e4-deprecated")
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "dep", entities=f"[{hub}]", occurred=days_ago(1),
               status="deprecated")
    result = run_script(bundle)
    record(
        "a deprecated backlinking fact never counts toward n_newer",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_superseded_fact_excluded_from_signal(root):
    """E4: same, for status: superseded."""
    bundle = new_bundle(root, "e4-superseded")
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "sup", entities=f"[{hub}]", occurred=days_ago(1),
               status="superseded")
    result = run_script(bundle)
    record(
        "a superseded backlinking fact never counts toward n_newer",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_active_fact_still_counts(root):
    """Sanity counterpart to E4: an active qualifying fact does flag the hub,
    and the printed line carries the right shape."""
    bundle = new_bundle(root, "e4-active-control")
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "fresh", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle)
    newest = days_ago(1)
    tended = days_ago(30)
    record(
        "an active newer fact flags the hub, with the documented line shape",
        result.returncode == 0
        and f"{hub}  updated {tended}  n_newer 1  newest {newest}" in result.stdout
        and "1 of 1 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_deprecated_fact_excluded_regardless_of_case(root):
    """A fact's `status` is compared case-insensitively, matching
    build-index.py's fact_status() normalization — `status: Deprecated`
    excludes a fact from n_newer exactly like `status: deprecated` does."""
    bundle = new_bundle(root, "e4-deprecated-case")
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "dep", entities=f"[{hub}]", occurred=days_ago(1),
               status="Deprecated")
    result = run_script(bundle)
    record(
        "status: Deprecated (capitalized) is excluded from n_newer, same as lowercase",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_superseded_fact_excluded_regardless_of_case(root):
    bundle = new_bundle(root, "e4-superseded-case")
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "sup", entities=f"[{hub}]", occurred=days_ago(1),
               status="SUPERSEDED")
    result = run_script(bundle)
    record(
        "status: SUPERSEDED (uppercase) is excluded from n_newer, same as lowercase",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_deprecated_hub_excluded_regardless_of_case(root):
    """A hub's `status` is compared case-insensitively too — `status:
    Deprecated` excludes the hub itself from `load_hubs()` entirely. A
    second hub, otherwise identical and genuinely stale, is planted
    alongside it: both would qualify as candidates on their dates alone, so
    only the deprecated one being absent from the total ("of 1", not "of
    2") and from the printed rows is what actually proves the exclusion —
    a hub merely not-yet-stale would prove nothing (render()'s "total" only
    counts candidates, not every hub loaded)."""
    bundle = new_bundle(root, "e-hub-deprecated-case")
    acme = write_hub(bundle, "acme", updated=days_ago(30), status="Deprecated")
    write_fact(bundle, "acme-fresh", entities=f"[{acme}]", occurred=days_ago(1))
    other = write_hub(bundle, "other", updated=days_ago(30))
    write_fact(bundle, "other-fresh", entities=f"[{other}]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "a hub with status: Deprecated (capitalized) is excluded, its equally-stale sibling is not",
        result.returncode == 0
        and "1 of 1 entity hub(s) may be stale." in result.stdout
        and other in result.stdout
        and acme not in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_day_gap_degrades_to_zero_on_bad_input(root):
    """day_gap() is defense-in-depth (compute_candidates only ever calls it
    with already-validated dates) but is untested directly and its except
    clause only caught ValueError, not the TypeError datetime.date.fromisoformat
    raises on None — both now covered directly."""
    bundle = new_bundle(root, "day-gap-unit")
    mod = import_copy(bundle, "ed_day_gap_unit")
    ok = (
        mod.day_gap("not-a-date", "2026-01-01") == 0
        and mod.day_gap("2026-01-01", "not-a-date") == 0
        and mod.day_gap(None, "2026-01-01") == 0
        and mod.day_gap("2026-01-01", None) == 0
    )
    record(
        "day_gap() returns 0 on an unparseable or missing date, never raises",
        ok,
        f"day_gap results: "
        f"{mod.day_gap('not-a-date', '2026-01-01')!r}, "
        f"{mod.day_gap('2026-01-01', 'not-a-date')!r}, "
        f"{mod.day_gap(None, '2026-01-01')!r}, "
        f"{mod.day_gap('2026-01-01', None)!r}",
    )


# --- E5 / E6 / E7 / E7b — the cap -------------------------------------------

def test_cap_truncates_and_reports_true_total(root):
    """E5: with more candidates than the cap, only the top-N ranked print,
    and the trailing line states the true total and the count shown."""
    bundle = new_bundle(root, "e5-cap")
    write_config(bundle, 3)
    for i in range(5):
        hub = write_hub(bundle, f"hub{i}", updated=days_ago(30))
        write_fact(bundle, f"fact{i}", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle)
    lines = [ln for ln in result.stdout.splitlines() if ln.startswith("/entities/")]
    record(
        "5 candidates, cap 3: only 3 rows print, trailing line reads 3 of 5",
        result.returncode == 0 and len(lines) == 3
        and "3 of 5 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_config_default_used_when_no_max_flag(root):
    """E6 (default branch): elephant.json's maintain.entity_drift_max is
    read and used as the cap when --max is not passed."""
    bundle = new_bundle(root, "e6-config-cap")
    write_config(bundle, 2)
    for i in range(4):
        hub = write_hub(bundle, f"hub{i}", updated=days_ago(30))
        write_fact(bundle, f"fact{i}", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "maintain.entity_drift_max: 2 caps a 4-candidate run at 2",
        result.returncode == 0 and "2 of 4 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_config_absent_falls_back_to_default_25(root):
    """E6: no elephant.json at all falls back to the hardcoded default (25),
    so 30 candidates are capped at 25 with no config present."""
    bundle = new_bundle(root, "e6-no-config")
    for i in range(30):
        hub = write_hub(bundle, f"hub{i:02d}", updated=days_ago(30))
        write_fact(bundle, f"fact{i:02d}", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "no elephant.json: the default cap (25) applies to a 30-candidate run",
        result.returncode == 0 and "25 of 30 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_config_non_numeric_falls_back_to_default(root):
    """E6: a non-numeric maintain.entity_drift_max falls back to 25, same as
    an absent one."""
    bundle = new_bundle(root, "e6-bad-config")
    (bundle / "elephant.json").write_text(
        json.dumps({"maintain": {"entity_drift_max": "lots"}}), encoding="utf-8",
    )
    for i in range(30):
        hub = write_hub(bundle, f"hub{i:02d}", updated=days_ago(30))
        write_fact(bundle, f"fact{i:02d}", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "a non-numeric maintain.entity_drift_max falls back to the default (25)",
        result.returncode == 0 and "25 of 30 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_config_zero_or_negative_falls_back_to_default(root):
    """E6: <= 0 falls back to the default, same defensive shape as
    close-loops.py's close_loops_max()."""
    bundle = new_bundle(root, "e6-zero-config")
    write_config(bundle, 0)
    for i in range(30):
        hub = write_hub(bundle, f"hub{i:02d}", updated=days_ago(30))
        write_fact(bundle, f"fact{i:02d}", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "maintain.entity_drift_max: 0 falls back to the default (25), not to 0",
        result.returncode == 0 and "25 of 30 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_max_flag_overrides_config_for_one_run(root):
    """E7: --max, 1 or greater, overrides the configured cap for that run
    only (the config value on disk is untouched)."""
    bundle = new_bundle(root, "e7-max-flag")
    write_config(bundle, 2)
    for i in range(4):
        hub = write_hub(bundle, f"hub{i}", updated=days_ago(30))
        write_fact(bundle, f"fact{i}", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle, ["--max", "3"])
    record(
        "--max 3 overrides a configured cap of 2 for this run",
        result.returncode == 0 and "3 of 4 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_max_flag_of_1_is_legal(root):
    """E7: --max 1 is a legal run size, not treated as falsy/absent."""
    bundle = new_bundle(root, "e7-max-one")
    for i in range(2):
        hub = write_hub(bundle, f"hub{i}", updated=days_ago(30))
        write_fact(bundle, f"fact{i}", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle, ["--max", "1"])
    record(
        "--max 1 runs at size 1, not silently treated as absent",
        result.returncode == 0 and "1 of 2 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_max_flag_non_numeric_is_refused(root):
    """E7b: a non-numeric --max is an argparse error, run refused."""
    bundle = new_bundle(root, "e7b-non-numeric")
    result = run_script(bundle, ["--max", "abc"])
    record(
        "--max abc is refused by argparse, not silently ignored",
        result.returncode != 0 and "--max" in result.stderr,
        f"exit={result.returncode}\nstderr:\n{result.stderr}",
    )


def test_max_flag_zero_is_refused(root):
    """E7b: --max 0 used to fall through to the configured default with no
    trace in the output (close-loops.py's own history); refused instead."""
    bundle = new_bundle(root, "e7b-zero")
    write_config(bundle, 5)
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "fresh", entities=f"[{hub}]", occurred=days_ago(1))
    result = run_script(bundle, ["--max", "0"])
    record(
        "--max 0 is refused by argparse rather than silently running the "
        "configured default",
        result.returncode != 0 and "--max" in result.stderr,
        f"exit={result.returncode}\nstderr:\n{result.stderr}",
    )


def test_max_flag_negative_is_refused(root):
    """E7b: a negative --max is refused the same way as 0."""
    bundle = new_bundle(root, "e7b-negative")
    result = run_script(bundle, ["--max", "-1"])
    record(
        "--max -1 is refused by argparse",
        result.returncode != 0 and "--max" in result.stderr,
        f"exit={result.returncode}\nstderr:\n{result.stderr}",
    )


# --- E8 — zero candidates ---------------------------------------------------

def test_zero_candidates_prints_zero_of_zero(root):
    """E8: a bundle with hubs and facts but no candidate prints a zero-count
    line — the "no stale hubs" writer (maintain, task 3) branches on this."""
    bundle = new_bundle(root, "e8-zero-candidates")
    hub = write_hub(bundle, "acme", updated=days_ago(1))
    write_fact(bundle, "old", entities=f"[{hub}]", occurred=days_ago(30))
    result = run_script(bundle)
    record(
        "zero candidates: the trailing line still prints, at 0 of N",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


# --- E9 — plugin-checkout refusal -------------------------------------------

def test_refuses_to_run_in_plugin_checkout(root):
    """E9: run from plugin/assets/ itself (not a copy), the same guard
    snapshot-drift.py uses. This is generically covered again by smoke.py's
    glob over every assets/scripts/*.py, exercised here directly too since
    it is one of this task's assigned behaviors."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    record(
        "entity-drift.py refuses to run from the plugin checkout",
        result.returncode != 0
        and "refusing to run inside" in (result.stdout + result.stderr),
        f"exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


# --- E10 — PyYAML indifference ----------------------------------------------

def test_never_imports_yaml(root):
    """E10: the script never imports yaml, so PyYAML being installed or not
    changes nothing about its behavior — asserted at the source level, the
    same thing the 3-OS x PyYAML matrix in ci.yml exercises at the process
    level for every suite, this one included."""
    text = SCRIPT.read_text(encoding="utf-8")
    record(
        "entity-drift.py never imports yaml (pure stdlib, regex frontmatter reader)",
        "import yaml" not in text and "from yaml" not in text,
        text.splitlines()[:5],
    )


# --- E11 — re-tended hub drops out ------------------------------------------

def test_retended_hub_drops_out_of_next_run(root):
    """E11: bumping a hub's updated past the newest qualifying fact's date
    removes it from the next run's candidates."""
    bundle = new_bundle(root, "e11-retended")
    hub_path = bundle / "knowledge" / "entities" / "concept" / "acme.md"
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "fresh", entities=f"[{hub}]", occurred=days_ago(1))
    before = run_script(bundle)
    record(
        "before re-tending: the hub is a candidate",
        before.returncode == 0 and "1 of 1 entity hub(s) may be stale." in before.stdout,
        f"stdout:\n{before.stdout}",
    )
    # re-tend: bump `updated` to today, past the fact's date
    write_hub(bundle, "acme", updated=TODAY.isoformat())
    after = run_script(bundle)
    record(
        "after re-tending (updated bumped past the fact): the hub drops out",
        after.returncode == 0 and "0 of 0 entity hub(s) may be stale." in after.stdout,
        f"stdout:\n{after.stdout}",
    )


# --- E12 — zero entity hubs --------------------------------------------------

def test_zero_hubs_prints_the_no_hubs_message(root):
    """E12: a bundle with zero entity hubs at all prints the dedicated
    message, distinct from the zero-candidates line."""
    bundle = new_bundle(root, "e12-zero-hubs")
    write_fact(bundle, "orphan", entities="[]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "zero entity hubs: prints 'No entity hubs found.' exactly",
        result.returncode == 0 and result.stdout.strip() == "No entity hubs found.",
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_zero_hubs_directory_missing_entirely(root):
    """E12, edge of the edge: knowledge/entities/ doesn't even exist."""
    bundle = new_bundle(root, "e12-no-entities-dir")
    shutil.rmtree(bundle / "knowledge" / "entities")
    write_fact(bundle, "orphan", entities="[]", occurred=days_ago(1))
    result = run_script(bundle)
    record(
        "no knowledge/entities/ directory at all: still prints the no-hubs message",
        result.returncode == 0 and result.stdout.strip() == "No entity hubs found.",
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


# --- E13 — undated qualifying fact never contributes ------------------------

def test_fact_missing_both_dates_never_contributes(root):
    """E13: a fact whose occurred and updated are both missing/unparseable
    never counts toward n_newer, even though it names the hub."""
    bundle = new_bundle(root, "e13-no-dates")
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "undated", entities=f"[{hub}]", occurred=None, updated=None)
    result = run_script(bundle)
    record(
        "a fact with no parseable occurred/updated never contributes to n_newer",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_fact_unparseable_dates_never_contribute(root):
    """E13: same, for dates present but not ISO-parseable (a typo), not just
    absent keys."""
    bundle = new_bundle(root, "e13-bad-dates")
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "typo", entities=f"[{hub}]", occurred="2026-99-99",
               updated="also-not-a-date")
    result = run_script(bundle)
    record(
        "a fact with unparseable occurred/updated never contributes to n_newer",
        result.returncode == 0 and "0 of 0 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def test_fact_with_one_parseable_date_still_contributes(root):
    """Sanity counterpart to E13: only one of the two dates needs to parse
    (max(occurred, updated)) for the fact to still count."""
    bundle = new_bundle(root, "e13-one-good-date")
    hub = write_hub(bundle, "acme", updated=days_ago(30))
    write_fact(bundle, "partial", entities=f"[{hub}]", occurred=None,
               updated=days_ago(1))
    result = run_script(bundle)
    record(
        "a fact with only updated: parseable still counts toward n_newer",
        result.returncode == 0 and "1 of 1 entity hub(s) may be stale." in result.stdout,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


# --- ranking sanity (spec's ## How it works, not its own E-row) -------------

def test_ranking_orders_by_n_newer_then_day_gap_then_path(root):
    """Two hubs, both candidates: n_newer descending puts real accumulation
    first, ahead of a hub with a single but larger day-gap fact."""
    bundle = new_bundle(root, "ranking")
    hub_a = write_hub(bundle, "a-few-facts", updated=days_ago(10))
    hub_b = write_hub(bundle, "b-one-old-fact", updated=days_ago(100))
    write_fact(bundle, "a1", entities=f"[{hub_a}]", occurred=days_ago(1))
    write_fact(bundle, "a2", entities=f"[{hub_a}]", occurred=days_ago(2))
    write_fact(bundle, "b1", entities=f"[{hub_b}]", occurred=days_ago(1))
    result = run_script(bundle)
    lines = [ln for ln in result.stdout.splitlines() if ln.startswith("/entities/")]
    record(
        "n_newer descending outranks a larger day-gap with fewer facts",
        result.returncode == 0 and len(lines) == 2
        and lines[0].startswith(hub_a) and lines[1].startswith(hub_b),
        f"stdout:\n{result.stdout}",
    )


def test_ci_wiring(root):
    """test_backlog.py shipped in 0.1.0-beta.7 and went a full release unrun
    in CI because ci.yml has no glob — a new suite needs its own `- run:`
    line, or it silently never executes. Assert this one has it, rather than
    trusting a human to remember."""
    ci = CI_WORKFLOW.read_text(encoding="utf-8") if CI_WORKFLOW.exists() else ""
    record(
        "this suite has its own `- run:` line in ci.yml, which has no glob",
        "- run: python tests/test_entity_drift.py" in ci,
    )


def guarded(fn, root):
    try:
        fn(root)
    except Exception:  # noqa: BLE001 - report and continue to the next check
        record(f"{fn.__name__} raised an unexpected exception", False, traceback.format_exc())


def main():
    print("elephant-mem test_entity_drift — entity-drift.py regression tests")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print()

    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-mem-test-entity-drift-"))
    print(f"scratch root: {scratch_root}\n")

    for fn in (
        test_no_newer_fact_is_not_a_candidate,
        test_never_backlinked_hub_is_not_a_candidate,
        test_hub_missing_updated_is_skipped_not_flagged,
        test_hub_unparseable_updated_is_skipped_not_flagged,
        test_deprecated_fact_excluded_from_signal,
        test_superseded_fact_excluded_from_signal,
        test_active_fact_still_counts,
        test_deprecated_fact_excluded_regardless_of_case,
        test_superseded_fact_excluded_regardless_of_case,
        test_deprecated_hub_excluded_regardless_of_case,
        test_day_gap_degrades_to_zero_on_bad_input,
        test_cap_truncates_and_reports_true_total,
        test_config_default_used_when_no_max_flag,
        test_config_absent_falls_back_to_default_25,
        test_config_non_numeric_falls_back_to_default,
        test_config_zero_or_negative_falls_back_to_default,
        test_max_flag_overrides_config_for_one_run,
        test_max_flag_of_1_is_legal,
        test_max_flag_non_numeric_is_refused,
        test_max_flag_zero_is_refused,
        test_max_flag_negative_is_refused,
        test_zero_candidates_prints_zero_of_zero,
        test_refuses_to_run_in_plugin_checkout,
        test_never_imports_yaml,
        test_retended_hub_drops_out_of_next_run,
        test_zero_hubs_prints_the_no_hubs_message,
        test_zero_hubs_directory_missing_entirely,
        test_fact_missing_both_dates_never_contributes,
        test_fact_unparseable_dates_never_contribute,
        test_fact_with_one_parseable_date_still_contributes,
        test_ranking_orders_by_n_newer_then_day_gap_then_path,
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
