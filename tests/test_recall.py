#!/usr/bin/env python3
"""Standalone test suite for elephant-mem's `scripts/recall.py`.

The recall record is the read side of the loop lane: `state/consumption-log.jsonl`
holds one line per answered read, and `state/recall.json` is the rolled-up
lookup over it. This suite covers the storage and the `log` writer:

  (a) **the write can never hurt a read** — a missing or unwritable `state/`
      makes `log` exit 0 and print nothing, on stdout or stderr. The log
      shipped for a year as prose telling every procedure to "swallow any
      exception silently"; moving the write into one script is what makes that
      promise testable at all;
  (b) **one writer normalizes** — a bundle-absolute link, a `knowledge/`-relative
      path and a real filesystem path all name the same file, and the line must
      key them identically or a later consumer counts each one separately;
  (c) **the log stays JSONL** — exactly one parseable line per call, appended,
      never rewriting what is already there;
  (d) `state/recall.json` is disposable: absent or malformed both read as the
      empty record, and the malformed case warns instead of raising;
  (e) the plugin-checkout guard. It was on 9 of the 11 shipped scripts; this
      script is the tenth of twelve, and `smoke.py` derives that census by
      globbing, so the guard is asserted there too rather than only here;
  (f) the suite is registered in CI by its own `- run:` line — the workflow has
      no glob, and `test_backlog.py` went a whole release unrun because of it.

Pure stdlib, Python 3.10+, mirroring `tests/test_backlog.py`'s conventions: a
throwaway bundle in a tempdir, subprocess calls into a copy of the real
`plugin/assets/scripts/recall.py`, PASS/FAIL per check, exit code 0 only if
every check passes. The in-process checks import the bundle's *copy*, never the
repo's, so a helper that writes lands in the tempdir and not in the assets the
marketplace publishes.
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
RECALL_SCRIPT = REPO_ROOT / "plugin" / "assets" / "scripts" / "recall.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

checks = []  # list of (label, passed)


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in detail.splitlines():
            print(f"       {ln}")
    return passed


def run(bundle, args):
    return subprocess.run(
        [sys.executable, str(bundle / "scripts" / "recall.py")] + [str(a) for a in args],
        cwd=str(bundle),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def check(bundle, args, label, expect_zero=True, expect_stdout=None, stdout_contains=None):
    result = run(bundle, args)
    ok = (result.returncode == 0) if expect_zero else (result.returncode != 0)
    bits = []
    if expect_stdout is not None and result.stdout.strip() != expect_stdout:
        ok = False
        bits.append(f"expected stdout {expect_stdout!r}, got {result.stdout.strip()!r}")
    if stdout_contains is not None and stdout_contains not in result.stdout:
        ok = False
        bits.append(f"expected stdout to contain {stdout_contains!r}")
    detail = ""
    if not ok:
        prefix = "\n".join(bits) + "\n" if bits else ""
        detail = f"{prefix}exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    record(label, ok, detail)
    return result


def make_bundle(root, name="bundle", with_state=True):
    bundle = Path(root) / name
    (bundle / "scripts").mkdir(parents=True)
    (bundle / "knowledge" / "facts").mkdir(parents=True)
    if with_state:
        (bundle / "state").mkdir(parents=True)
    shutil.copy(RECALL_SCRIPT, bundle / "scripts" / "recall.py")
    return bundle


def import_copy(bundle, name):
    """Import the bundle's own copy, so anything it writes lands in the tempdir."""
    spec = importlib.util.spec_from_file_location(name, bundle / "scripts" / "recall.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def log_lines(bundle):
    path = bundle / "state" / "consumption-log.jsonl"
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def silent(result):
    return result.stdout.strip() == "" and result.stderr.strip() == ""


def main():
    with tempfile.TemporaryDirectory() as tmp:
        bundle = make_bundle(tmp)

        # --- bootstrap: neither file exists yet ---------------------------
        record(
            "no consumption log and no recall.json before first use",
            not (bundle / "state" / "consumption-log.jsonl").exists()
            and not (bundle / "state" / "recall.json").exists(),
        )
        result = check(bundle, ["show"], "show on a virgin bundle works")
        try:
            virgin = json.loads(result.stdout)
            record(
                "virgin show prints the empty record with its item-agnostic maps",
                virgin["items"] == {} and virgin["entities"] == {}
                and virgin["rolled_through"] is None,
                result.stdout,
            )
            record(
                "virgin show warns against hand-editing the derived file",
                "do not hand-edit" in virgin.get("comment", ""),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            record("virgin show prints the empty record with its item-agnostic maps",
                   False, str(exc))
            record("virgin show warns against hand-editing the derived file", False, str(exc))
        record(
            "show does not materialize recall.json (roll is its only writer)",
            not (bundle / "state" / "recall.json").exists(),
        )

        # --- (a) the write is invisible to the answer ---------------------
        result = check(
            bundle,
            ["log", "--mode", "query",
             "--item", "/facts/2026-08/export-fix.md",
             "--entity", "angelo"],
            "log exits 0",
        )
        record("log prints nothing at all — a read's transcript stays its own",
               silent(result), f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

        # --- (c) one parseable JSONL line, in core.md's shape --------------
        lines = log_lines(bundle)
        record("exactly one line landed", len(lines) == 1, repr(lines))
        try:
            row = json.loads(lines[0])
            record(
                "the line carries core.md's four keys",
                set(row) == {"ts", "mode", "entities", "facts_cited"},
                repr(row),
            )
            record(
                "mode, entities and facts_cited round-trip",
                row["mode"] == "query"
                and row["entities"] == ["angelo"]
                and row["facts_cited"] == ["/facts/2026-08/export-fix.md"],
                repr(row),
            )
            parsed = datetime.fromisoformat(row["ts"])
            record("ts is parseable ISO with a real UTC offset",
                   parsed.utcoffset() is not None, repr(row["ts"]))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            for label in ("the line carries core.md's four keys",
                          "mode, entities and facts_cited round-trip",
                          "ts is parseable ISO with a real UTC offset"):
                record(label, False, str(exc))

        # a second call appends; it never rewrites what is already there
        run(bundle, ["log", "--mode", "briefing", "--item", "/facts/a.md"])
        lines = log_lines(bundle)
        record("a second read appends rather than replaces",
               len(lines) == 2 and json.loads(lines[0])["mode"] == "query"
               and json.loads(lines[1])["mode"] == "briefing", repr(lines))

        # --- --at makes a run replayable -----------------------------------
        run(bundle, ["log", "--mode", "query", "--at", "2026-08-01T12:00:00-03:00"])
        record("--at overrides now",
               json.loads(log_lines(bundle)[-1])["ts"] == "2026-08-01T12:00:00-03:00")
        record("a read that cited nothing still records that the mode ran",
               json.loads(log_lines(bundle)[-1])["facts_cited"] == []
               and json.loads(log_lines(bundle)[-1])["entities"] == [])

        # --- (b) normalization and de-duplication, at the one writer -------
        run(bundle, [
            "log", "--mode", "query",
            "--item", "/facts/dup.md",
            "--item", "knowledge/facts/dup.md",
            "--item", str(bundle / "knowledge" / "facts" / "dup.md"),
            "--item", "  ",
            "--entity", "/entities/person/angelo.md",
            "--entity", "Angelo",
        ])
        row = json.loads(log_lines(bundle)[-1])
        record(
            "three spellings of one path collapse to one bundle-absolute entry",
            row["facts_cited"] == ["/facts/dup.md"], repr(row["facts_cited"]),
        )
        record(
            "an entity path and a bare slug collapse to one slug",
            row["entities"] == ["angelo"], repr(row["entities"]),
        )

        # order is preserved: the first spelling wins its position
        run(bundle, ["log", "--mode", "query", "--item", "/b.md", "--item", "/a.md",
                     "--item", "/b.md"])
        record("de-duplication keeps first-seen order",
               json.loads(log_lines(bundle)[-1])["facts_cited"] == ["/b.md", "/a.md"])

        # a path with a newline in it must not split the JSONL line
        before = len(log_lines(bundle))
        run(bundle, ["log", "--mode", "query", "--item", "/facts/one\ntwo.md"])
        record("a newline inside a path stays inside its line",
               len(log_lines(bundle)) == before + 1)

        # non-ASCII survives (ensure_ascii=False, and Windows' cp1252 console)
        run(bundle, ["log", "--mode", "query", "--entity", "joao-conceição"])
        record("a non-ASCII slug round-trips",
               json.loads(log_lines(bundle)[-1])["entities"] == ["joao-conceição"])

        # in-process, over the bundle's own copy: the normalizers themselves
        mod = import_copy(bundle, "recall_under_test")
        cases = {
            "/facts/x.md": "/facts/x.md",
            "facts/x.md": "/facts/x.md",
            "./facts/x.md": "/facts/x.md",
            "knowledge/facts/x.md": "/facts/x.md",
            "/knowledge/facts/x.md": "/facts/x.md",
            "\\facts\\x.md": "/facts/x.md",
            "/facts//x.md": "/facts/x.md",
            "/facts/../facts/x.md": "/facts/x.md",
            "": None,
            "   ": None,
            "/": None,
        }
        bad = {k: mod.normalize_item(k) for k, v in cases.items() if mod.normalize_item(k) != v}
        record("normalize_item maps every spelling onto the bundle-absolute form",
               not bad, repr(bad))
        record("a traversal cannot climb out of the bundle-absolute root",
               mod.normalize_item("/../../etc/passwd") == "/etc/passwd",
               repr(mod.normalize_item("/../../etc/passwd")))
        record("normalize_entity strips a path, an extension and the case",
               mod.normalize_entity("/entities/org/ACME.md") == "acme"
               and mod.normalize_entity("  ") is None)

        # --- (d) recall.json: disposable, tolerant --------------------------
        mod.save(mod.empty())
        record("save materializes recall.json in the bundle, not in the checkout",
               (bundle / "state" / "recall.json").exists()
               and not (REPO_ROOT / "plugin" / "assets" / "state").exists())
        check(bundle, ["show"], "show reads a saved record back",
              stdout_contains='"schema"')

        (bundle / "state" / "recall.json").write_text("{ not json", encoding="utf-8")
        result = run(bundle, ["show"])
        ok = result.returncode == 0
        try:
            ok = ok and json.loads(result.stdout)["items"] == {}
        except (json.JSONDecodeError, KeyError):
            ok = False
        record("a malformed recall.json reads as empty, exit 0",
               ok, f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        record("…and says so once on stderr rather than raising",
               "recall.json" in result.stderr and "warning" in result.stderr,
               result.stderr)

        (bundle / "state" / "recall.json").write_text('["a list"]', encoding="utf-8")
        result = run(bundle, ["show"])
        record("a JSON value of the wrong shape is also treated as empty",
               result.returncode == 0 and json.loads(result.stdout)["entities"] == {},
               result.stdout + result.stderr)

        (bundle / "state" / "recall.json").write_text(
            '{"schema": 1, "items": "wrong type"}', encoding="utf-8")
        result = run(bundle, ["show"])
        record("a field of the wrong type falls back to its empty default",
               result.returncode == 0 and json.loads(result.stdout)["items"] == {},
               result.stdout + result.stderr)

        # --- (a) E1: state/ absent, then unwritable -------------------------
        stateless = make_bundle(tmp, name="stateless", with_state=False)
        result = check(stateless, ["log", "--mode", "query", "--item", "/facts/x.md"],
                       "log with no state/ dir exits 0")
        record("…silently, and having created state/ for the line",
               silent(result) and len(log_lines(stateless)) == 1,
               f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

        # `state` occupied by a file: mkdir raises, and the read must not care.
        blocked = make_bundle(tmp, name="blocked", with_state=False)
        (blocked / "state").write_text("not a directory\n", encoding="utf-8")
        result = check(blocked, ["log", "--mode", "query", "--item", "/facts/x.md"],
                       "log with an unwritable state/ exits 0")
        record("…silently, and writes nothing", silent(result),
               f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

        # The log path occupied by a directory: the append itself raises.
        # Portable — a chmod-based check would be a no-op on Windows.
        obstructed = make_bundle(tmp, name="obstructed")
        (obstructed / "state" / "consumption-log.jsonl").mkdir()
        result = check(obstructed, ["log", "--mode", "query", "--item", "/facts/x.md"],
                       "log over an unwritable log path exits 0")
        record("…silently there too", silent(result),
               f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

        # --- (e) E22: the plugin-checkout guard ------------------------------
        fake = Path(tmp) / "fake-plugin"
        (fake / ".claude-plugin").mkdir(parents=True)
        (fake / "assets" / "scripts").mkdir(parents=True)
        shutil.copy(RECALL_SCRIPT, fake / "assets" / "scripts" / "recall.py")
        result = subprocess.run(
            [sys.executable, str(fake / "assets" / "scripts" / "recall.py"),
             "log", "--mode", "query", "--item", "/facts/x.md"],
            cwd=str(fake), capture_output=True, text=True, encoding="utf-8",
        )
        record("recall.py refuses to run inside the plugin checkout",
               result.returncode != 0
               and "refusing to run inside" in (result.stdout + result.stderr),
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        record("…and wrote nothing into the published assets",
               not (fake / "assets" / "state").exists())

        plain = Path(tmp) / "plain" / "assets" / "scripts"
        plain.mkdir(parents=True)
        shutil.copy(RECALL_SCRIPT, plain / "recall.py")
        result = subprocess.run(
            [sys.executable, str(plain / "recall.py"), "--help"],
            cwd=str(plain.parent.parent), capture_output=True, text=True, encoding="utf-8",
        )
        record("…and does not trip on a directory merely named assets/",
               "refusing to run inside" not in (result.stdout + result.stderr),
               result.stdout + result.stderr)

        # --- (f) E24: the script ships, and the suite is wired into CI -------
        record("the script lives where update's `cp scripts/*.py` re-sync finds it",
               RECALL_SCRIPT.parent == REPO_ROOT / "plugin" / "assets" / "scripts")
        ci = CI_WORKFLOW.read_text(encoding="utf-8") if CI_WORKFLOW.exists() else ""
        record("this suite has its own `- run:` line in ci.yml, which has no glob",
               "- run: python tests/test_recall.py" in ci)

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
