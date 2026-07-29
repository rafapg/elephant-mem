#!/usr/bin/env python3
"""Standalone test suite for elephant-mem's `scripts/run-hooks.py`.

`run-hooks.py` is the `post_ingest` lifecycle extension point: after an
ingestion cycle, a mode calls it and it runs the subscriber commands declared in
the bundle's `elephant.json` under `hooks.<event>`. The load-bearing guarantees
are (a) it is best-effort — a failing/absent/malformed hook never breaks the
ingestion (the runner still exits 0); (b) it honors the env-var contract
(ELEPHANT_BUNDLE / ELEPHANT_EVENT / ELEPHANT_TRIGGER); (c) hooks are isolated —
one failing hook doesn't stop the next; (d) only the requested event fires.

Pure stdlib, Python 3.10+, mirroring tests/test_state.py's conventions: a
throwaway bundle in a tempdir, subprocess calls into the real
`plugin/assets/scripts/run-hooks.py`, PASS/FAIL per check, exit 0 only if every
check passes.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Force UTF-8 stdio: Windows consoles default to cp1252, which can't encode the
# non-ASCII characters (→, —, …) used in check labels — printing them would
# raise UnicodeEncodeError and fail the suite. Mirrors the bundle scripts.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_HOOKS_SCRIPT = REPO_ROOT / "plugin" / "assets" / "scripts" / "run-hooks.py"

checks = []  # list of (label, passed)


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    return passed


def new_bundle(root, name):
    """A throwaway bundle with scripts/run-hooks.py, state/, and a probe hook."""
    bundle = root / name
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    (bundle / "state").mkdir(parents=True, exist_ok=True)
    shutil.copy2(RUN_HOOKS_SCRIPT, bundle / "scripts" / "run-hooks.py")
    # A probe hook: appends "argv | ELEPHANT_BUNDLE | ELEPHANT_EVENT |
    # ELEPHANT_TRIGGER" to <marker> so tests can assert it ran with the contract.
    probe = bundle / "scripts" / "probe.py"
    probe.write_text(
        "import os, sys\n"
        "marker = sys.argv[1]\n"
        "with open(marker, 'a', encoding='utf-8') as fh:\n"
        "    fh.write('|'.join([\n"
        "        ' '.join(sys.argv[2:]),\n"
        "        os.environ.get('ELEPHANT_BUNDLE', ''),\n"
        "        os.environ.get('ELEPHANT_EVENT', ''),\n"
        "        os.environ.get('ELEPHANT_TRIGGER', ''),\n"
        "    ]) + '\\n')\n",
        encoding="utf-8",
    )
    return bundle


def write_config(bundle, hooks):
    cfg = {"owner": {"name": "T", "slug": "t"}}
    if hooks is not None:
        cfg["hooks"] = hooks
    (bundle / "elephant.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8"
    )


def probe_cmd(bundle, marker, *extra):
    """An argv-list `run` value invoking the probe hook."""
    return [sys.executable, str(bundle / "scripts" / "probe.py"), str(marker), *extra]


def run_hooks(bundle, event, *args):
    return subprocess.run(
        [sys.executable, str(bundle / "scripts" / "run-hooks.py"), event, *args],
        cwd=str(bundle),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def main():
    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-hooks-"))
    try:
        _run(scratch_root)
    finally:
        shutil.rmtree(scratch_root, ignore_errors=True)

    print("\nSummary\n-------")
    n_pass = sum(1 for _, p in checks if p)
    for label, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL':4s}  {label}")
    total = len(checks)
    print(f"\n{n_pass}/{total} checks passed.")
    return 0 if n_pass == total and total > 0 else 1


def _run(root):
    # 1. No elephant.json at all → silent no-op, exit 0.
    b = new_bundle(root, "no-config")
    r = run_hooks(b, "post_ingest")
    record("no elephant.json → exits 0, silent", r.returncode == 0 and not r.stderr.strip(),
           f"rc={r.returncode} stderr={r.stderr}")

    # 2. Config without a `hooks` block → exit 0.
    b = new_bundle(root, "no-hooks")
    write_config(b, None)
    r = run_hooks(b, "post_ingest")
    record("config without hooks → exits 0", r.returncode == 0, r.stderr)

    # 3. Empty post_ingest list → exit 0.
    b = new_bundle(root, "empty-list")
    write_config(b, {"post_ingest": []})
    r = run_hooks(b, "post_ingest")
    record("empty post_ingest list → exits 0", r.returncode == 0, r.stderr)

    # 4. A successful hook runs and receives the env-var contract.
    b = new_bundle(root, "success")
    marker = b / "ran.txt"
    write_config(b, {"post_ingest": [{"name": "probe", "run": probe_cmd(b, marker, "build")}]})
    r = run_hooks(b, "post_ingest", "--trigger", "ingest")
    line = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    parts = line.split("|") if line else []
    record("hook runs (argv list) → exits 0", r.returncode == 0, r.stderr)
    record("hook received argv args", len(parts) == 4 and parts[0] == "build", line)
    record("ELEPHANT_BUNDLE = abs bundle path", len(parts) == 4 and parts[1] == str(b), line)
    record("ELEPHANT_EVENT = post_ingest", len(parts) == 4 and parts[2] == "post_ingest", line)
    record("ELEPHANT_TRIGGER = ingest", len(parts) == 4 and parts[3] == "ingest", line)

    # 5. A string command (not a list) is shell-split (POSIX rules) and runs.
    #    Use forward-slash paths (accepted on Windows too) since backslashes are
    #    shlex escape characters — this is the documented contract for strings.
    b = new_bundle(root, "string-cmd")
    marker = b / "ran.txt"
    exe = sys.executable.replace("\\", "/")
    probe = str(b / "scripts" / "probe.py").replace("\\", "/")
    mk = str(marker).replace("\\", "/")
    cmd = f'"{exe}" "{probe}" "{mk}" strcmd'
    write_config(b, {"post_ingest": [{"name": "s", "run": cmd}]})
    r = run_hooks(b, "post_ingest")
    ran = marker.exists() and "strcmd" in marker.read_text(encoding="utf-8")
    record("string `run` command runs", r.returncode == 0 and ran, f"rc={r.returncode} stderr={r.stderr}")

    # 6. Isolation: a failing hook doesn't stop the next, and runner exits 0.
    b = new_bundle(root, "isolation")
    marker = b / "ran.txt"
    write_config(b, {"post_ingest": [
        {"name": "boom", "run": [sys.executable, "-c", "import sys; sys.exit(3)"]},
        {"name": "probe", "run": probe_cmd(b, marker, "after-boom")},
    ]})
    r = run_hooks(b, "post_ingest")
    second_ran = marker.exists() and "after-boom" in marker.read_text(encoding="utf-8")
    record("failing hook → runner still exits 0", r.returncode == 0, r.stderr)
    record("failing hook doesn't stop the next", second_ran, "second hook did not run")
    record("failing hook is reported on stderr", "boom" in r.stderr and "exit" in r.stderr.lower(), r.stderr)

    # 7. Only the requested event fires.
    b = new_bundle(root, "event-scope")
    marker = b / "ran.txt"
    write_config(b, {"post_maintain": [{"name": "p", "run": probe_cmd(b, marker)}]})
    r = run_hooks(b, "post_ingest")
    record("other-event hook does NOT fire", r.returncode == 0 and not marker.exists(), r.stderr)

    # 8. enabled:false → dormant, not run.
    b = new_bundle(root, "disabled")
    marker = b / "ran.txt"
    write_config(b, {"post_ingest": [{"name": "off", "enabled": False, "run": probe_cmd(b, marker)}]})
    r = run_hooks(b, "post_ingest")
    record("enabled:false hook stays dormant", r.returncode == 0 and not marker.exists(), r.stderr)

    # 9. Malformed entry (no `run`) → skipped, exit 0.
    b = new_bundle(root, "malformed-entry")
    write_config(b, {"post_ingest": [{"name": "nope"}]})
    r = run_hooks(b, "post_ingest")
    record("entry without `run` → skipped, exits 0", r.returncode == 0, r.stderr)

    # 10. --dry-run does not execute the hook.
    b = new_bundle(root, "dry-run")
    marker = b / "ran.txt"
    write_config(b, {"post_ingest": [{"name": "probe", "run": probe_cmd(b, marker)}]})
    r = run_hooks(b, "post_ingest", "--dry-run")
    record("--dry-run runs nothing", r.returncode == 0 and not marker.exists(), r.stderr)

    # 11. A hook exceeding its timeout is killed; runner still exits 0.
    b = new_bundle(root, "timeout")
    write_config(b, {"post_ingest": [
        {"name": "slow", "timeout": 1, "run": [sys.executable, "-c", "import time; time.sleep(30)"]},
    ]})
    r = run_hooks(b, "post_ingest")
    record("timed-out hook killed → exits 0", r.returncode == 0 and "timed out" in r.stderr, r.stderr)

    # 12. hooks.log records a successful run.
    b = new_bundle(root, "logging")
    marker = b / "ran.txt"
    write_config(b, {"post_ingest": [{"name": "probe", "run": probe_cmd(b, marker)}]})
    run_hooks(b, "post_ingest")
    logf = b / "state" / "hooks.log"
    logged = logf.exists() and "probe" in logf.read_text(encoding="utf-8") and "ok" in logf.read_text(encoding="utf-8")
    record("successful run appended to state/hooks.log", logged, "no ok line in hooks.log")

    # 13. Malformed elephant.json → warns, exits 0 (never breaks ingestion).
    b = new_bundle(root, "bad-json")
    (b / "elephant.json").write_text("{ not valid json ", encoding="utf-8")
    r = run_hooks(b, "post_ingest")
    record("malformed elephant.json → exits 0 with warning", r.returncode == 0 and "run-hooks:" in r.stderr, r.stderr)


if __name__ == "__main__":
    sys.exit(main())
