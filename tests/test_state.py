#!/usr/bin/env python3
"""Standalone test suite for elephant-mem's `scripts/state.py` cursor handling.

Exercises the fixes for two known bugs found in audit: (a) a `null`/
never-initialized `live_cursor` or `backfill_oldest` — exactly the state a
freshly registered BYO source starts in — crashing `after`/`next-backfill`
with a `TypeError`; (b) writing to a channel not yet present in
`cursors.json` crashing with a `KeyError` instead of bootstrapping the entry.
Also covers the typed-cursor feature: a bare ISO string is the legacy `date`
cursor, or a cursor can be a typed `{"type": "date"|"commit", "value": ...}`
object, with `commit` cursors rejecting date arithmetic cleanly.

Pure stdlib, Python 3.10+, mirroring `tests/smoke.py`'s conventions: a
throwaway bundle in a tempdir, subprocess calls into the real
`plugin/assets/scripts/state.py`, PASS/FAIL per check, exit code 0 only if
every check passes.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_SCRIPT = REPO_ROOT / "plugin" / "assets" / "scripts" / "state.py"
REAL_CURSORS = Path.home() / "elephant-mem" / "state" / "cursors.json"

checks = []  # list of (label, passed)


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in detail.splitlines():
            print(f"       {ln}")
    return passed


def run_state(bundle, args):
    script = bundle / "scripts" / "state.py"
    return subprocess.run(
        [sys.executable, str(script)] + [str(a) for a in args],
        cwd=str(bundle),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def check(bundle, args, label, expect_zero=True, expect_stdout=None, expect_stderr_contains=None):
    result = run_state(bundle, args)
    ok = (result.returncode == 0) if expect_zero else (result.returncode != 0)
    detail_bits = []
    if expect_stdout is not None and result.stdout.strip() != expect_stdout:
        ok = False
        detail_bits.append(f"expected stdout {expect_stdout!r}, got {result.stdout.strip()!r}")
    if expect_stderr_contains is not None and expect_stderr_contains not in result.stderr:
        ok = False
        detail_bits.append(f"expected stderr to contain {expect_stderr_contains!r}")
    detail = ""
    if not ok:
        prefix = "\n".join(detail_bits) + "\n" if detail_bits else ""
        detail = f"{prefix}exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    record(label, ok, detail)
    return result


def read_cursors(bundle):
    return json.loads((bundle / "state" / "cursors.json").read_text(encoding="utf-8"))


def write_cursors(bundle, cursors):
    (bundle / "state" / "cursors.json").write_text(json.dumps(cursors, indent=2) + "\n", encoding="utf-8")


def scaffold_bundle(bundle):
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    (bundle / "state").mkdir(parents=True, exist_ok=True)
    shutil.copy2(STATE_SCRIPT, bundle / "scripts" / "state.py")
    cursors = {
        "channels": {
            "legacy": {
                "live_cursor": "2026-01-01T00:00:00-03:00",
                "backfill_oldest": "2025-12-15",
                "last_run": "2026-01-01T00:00:00-03:00",
            },
            "never-touched": {
                "live_cursor": None,
                "backfill_oldest": None,
                "last_run": None,
            },
        },
        "config": {
            "timezone": "-03:00",
            "gcal_lag_hours": 3,
            "gcal_lookback_hours": 48,
            "backfill_window_start": "2025-06-01",
        },
    }
    write_cursors(bundle, cursors)
    (bundle / "state" / "processed-events.json").write_text(
        json.dumps({"processed": []}, indent=2) + "\n", encoding="utf-8"
    )


def main():
    print("elephant-mem state.py test suite")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print()

    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-mem-test-state-"))
    bundle = scratch_root / "bundle"
    print(f"scratch bundle: {bundle}\n")

    try:
        scaffold_bundle(bundle)
        record("scaffold throwaway bundle + seed cursors.json", True)
    except Exception as e:  # noqa: BLE001 - report and stop
        record("scaffold throwaway bundle + seed cursors.json", False, str(e))
        shutil.rmtree(scratch_root, ignore_errors=True)
        return 1

    # --- (a) null live_cursor / backfill_oldest must not crash ---
    check(
        bundle, ["after", "never-touched"],
        "after on a null live_cursor returns epoch 0 (not a TypeError)",
        expect_stdout="0",
    )

    today = datetime.now().strftime("%Y-%m-%d")
    result = check(
        bundle, ["next-backfill", "never-touched"],
        "next-backfill on a null backfill_oldest starts from today (not a TypeError)",
        expect_stdout=today,
    )

    # --- (b) unregistered channel: reads stay safe, writes bootstrap ---
    check(
        bundle, ["after", "brand-new-channel"],
        "after on a channel absent from cursors.json returns epoch 0 (not KeyError)",
        expect_stdout="0",
    )

    check(
        bundle, ["advance-live", "brand-new-channel", "2026-02-01T00:00:00-03:00"],
        "advance-live bootstraps a brand-new channel instead of KeyError",
    )
    cursors = read_cursors(bundle)
    record(
        "bootstrapped channel present in cursors.json with the set value",
        cursors["channels"].get("brand-new-channel", {}).get("live_cursor")
        == "2026-02-01T00:00:00-03:00",
        json.dumps(cursors["channels"].get("brand-new-channel"), indent=2),
    )

    check(
        bundle, ["advance-backfill", "another-new-channel", "2026-01-15"],
        "advance-backfill bootstraps a brand-new channel instead of KeyError",
    )
    check(
        bundle, ["set-last-run", "yet-another-new-channel", "2026-02-01T00:00:00-03:00"],
        "set-last-run bootstraps a brand-new channel instead of KeyError",
    )

    # --- legacy bare-string cursor (backward compatibility) ---
    result = check(
        bundle, ["after", "legacy"],
        "after on a legacy bare-string live_cursor",
    )
    expected_ts = int(datetime.fromisoformat("2026-01-01T00:00:00-03:00").timestamp())
    record(
        "legacy cursor's Unix ts matches the expected value",
        result.stdout.strip() == str(expected_ts),
        f"expected {expected_ts}, got {result.stdout.strip()!r}",
    )

    # --- typed cursor: explicit {"type": "date", ...} behaves like a bare string ---
    cursors = read_cursors(bundle)
    cursors["channels"]["typed-date"] = {
        "live_cursor": {"type": "date", "value": "2026-03-01T00:00:00-03:00"},
        "backfill_oldest": None,
        "last_run": None,
    }
    write_cursors(bundle, cursors)
    result = check(
        bundle, ["after", "typed-date"],
        "after on an explicit typed {type: date} cursor",
    )
    expected_ts = int(datetime.fromisoformat("2026-03-01T00:00:00-03:00").timestamp())
    record(
        "typed date cursor's Unix ts matches the expected value",
        result.stdout.strip() == str(expected_ts),
        f"expected {expected_ts}, got {result.stdout.strip()!r}",
    )

    # --- typed cursor: commit — set / get / equality, arithmetic errors cleanly ---
    check(
        bundle, ["advance-live", "docs-repo", "abc1234", "--type", "commit"],
        "advance-live --type commit sets a typed commit cursor",
    )
    cursors = read_cursors(bundle)
    record(
        "commit cursor stored as a typed object on disk",
        cursors["channels"].get("docs-repo", {}).get("live_cursor")
        == {"type": "commit", "value": "abc1234"},
        json.dumps(cursors["channels"].get("docs-repo"), indent=2),
    )
    check(
        bundle, ["live-cursor", "docs-repo"],
        "live-cursor prints the raw commit value",
        expect_stdout="abc1234",
    )
    check(
        bundle, ["cursor-eq", "docs-repo", "abc1234"],
        "cursor-eq reports 'same' for an unchanged commit (no-op gate)",
        expect_stdout="same",
    )
    check(
        bundle, ["cursor-eq", "docs-repo", "def5678"],
        "cursor-eq reports 'changed' (exit 1) for a moved commit",
        expect_zero=False,
        expect_stdout="changed",
    )
    check(
        bundle, ["after", "docs-repo"],
        "after on a commit cursor is a friendly error, not a crash",
        expect_zero=False,
        expect_stderr_contains="has no date",
    )

    # --- null config.backfill_window_start must not crash next-backfill either ---
    cursors = read_cursors(bundle)
    cursors["config"]["backfill_window_start"] = None
    write_cursors(bundle, cursors)
    check(
        bundle, ["next-backfill", "legacy"],
        "next-backfill with a null config.backfill_window_start falls back to a "
        "30-day horizon instead of a TypeError",
        expect_stdout="NONE",  # legacy's backfill_oldest (2025-12-15) is well past a 30-day horizon
        expect_stderr_contains="backfill_window_start not set",
    )

    # --- read-only regression check against the real bundle's cursors.json ---
    if REAL_CURSORS.exists():
        try:
            spec = importlib.util.spec_from_file_location("state_under_test", STATE_SCRIPT)
            state_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(state_mod)
            real_cur = json.loads(REAL_CURSORS.read_text(encoding="utf-8"))
            all_ok = True
            detail_lines = []
            for name, c in real_cur.get("channels", {}).items():
                ctype, value = state_mod.cursor_type_and_value(c.get("live_cursor"))
                if ctype != "date":
                    all_ok = False
                    detail_lines.append(f"{name}: expected legacy type 'date', got {ctype!r}")
                    continue
                try:
                    state_mod.parse_iso(value)
                except Exception as e:  # noqa: BLE001
                    all_ok = False
                    detail_lines.append(f"{name}: parse_iso failed on {value!r}: {e}")
            record(
                "real bundle cursors.json (~/elephant-mem/state/cursors.json) still parses "
                "as legacy bare-string date cursors, unmigrated (read-only, not written to)",
                all_ok,
                "\n".join(detail_lines),
            )
        except Exception as e:  # noqa: BLE001
            record(
                "real bundle cursors.json (~/elephant-mem/state/cursors.json) still parses "
                "as legacy bare-string date cursors, unmigrated (read-only, not written to)",
                False,
                str(e),
            )
    else:
        record(
            "real bundle cursors.json check skipped — ~/elephant-mem/state/cursors.json not found",
            True,
        )

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
