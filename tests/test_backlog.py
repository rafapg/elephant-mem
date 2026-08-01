#!/usr/bin/env python3
"""Standalone test suite for elephant-mem's `scripts/backlog.py`.

The backlog is the mechanism that stops the unattended `catch-up` routine from
re-narrating the same deferred finding in `log.md` every hour. Its contract is
narrow but load-bearing:

  (a) `add` is idempotent — the routine calls it unconditionally for every
      yellow finding, so a known id must bump rather than duplicate, and a
      closed id must reopen;
  (b) the `seen` counter is the green-zone evidence gate (a config field may be
      self-tuned only at `seen >= 3`), so it must count *runs*, never entries;
  (c) `backlog.md` is a rendering — every mutation regenerates it;
  (d) both files bootstrap on first use, so an existing bundle needs no seeding;
  (e) timestamps are Python-generated ISO with a real offset — the routine was
      burned by BSD `date "+%:z"` emitting a literal `:z`.

Pure stdlib, Python 3.10+, mirroring `tests/test_state.py`'s conventions: a
throwaway bundle in a tempdir, subprocess calls into the real
`plugin/assets/scripts/backlog.py`, PASS/FAIL per check, exit code 0 only if
every check passes.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKLOG_SCRIPT = REPO_ROOT / "plugin" / "assets" / "scripts" / "backlog.py"

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
        [sys.executable, str(bundle / "scripts" / "backlog.py")] + [str(a) for a in args],
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


def make_bundle(tmp):
    bundle = Path(tmp) / "bundle"
    (bundle / "scripts").mkdir(parents=True)
    (bundle / "state").mkdir(parents=True)
    shutil.copy(BACKLOG_SCRIPT, bundle / "scripts" / "backlog.py")
    return bundle


def read_json(bundle):
    return json.loads((bundle / "state" / "backlog.json").read_text(encoding="utf-8"))


def read_md(bundle):
    return (bundle / "state" / "backlog.md").read_text(encoding="utf-8")


def item_of(bundle, item_id):
    for item in read_json(bundle)["items"]:
        if item["id"] == item_id:
            return item
    return None


def main():
    with tempfile.TemporaryDirectory() as tmp:
        bundle = make_bundle(tmp)

        # --- (d) bootstrap: neither file exists yet -----------------------
        record(
            "no backlog.json before first use",
            not (bundle / "state" / "backlog.json").exists(),
        )
        check(
            bundle, ["count", "--status", "open"],
            "count on a virgin bundle returns 0 (no crash)",
            expect_stdout="0",
        )
        check(bundle, ["list"], "list on a virgin bundle is a clean no-op",
              stdout_contains="no open backlog items")

        # --- add: new item -----------------------------------------------
        check(
            bundle,
            ["add", "slack-sweep-under-returns",
             "--summary", "single-stopword sweep under-returns",
             "--unblocks", "decide sweep shape: per-channel read vs stopword union",
             "--evidence", "de -> 2 where a -> 14"],
            "add files a new item",
            stdout_contains="new slack-sweep-under-returns (seen=1)",
        )
        record(
            "backlog.json + backlog.md both materialized",
            (bundle / "state" / "backlog.json").exists()
            and (bundle / "state" / "backlog.md").exists(),
        )
        item = item_of(bundle, "slack-sweep-under-returns")
        record("new item starts open at seen=1",
               item["status"] == "open" and item["seen"] == 1)
        record("new item keeps summary/unblocks/evidence",
               item["unblocks"].startswith("decide sweep shape")
               and item["evidence"] == ["de -> 2 where a -> 14"])

        # --- (e) timestamps parse as ISO with an offset -------------------
        try:
            parsed = datetime.fromisoformat(item["first_seen"])
            record("first_seen is parseable ISO with a UTC offset",
                   parsed.utcoffset() is not None, f"got {item['first_seen']!r}")
        except ValueError as exc:
            record("first_seen is parseable ISO with a UTC offset", False, str(exc))

        # --- (a)(b) add is idempotent and counts runs ---------------------
        check(
            bundle,
            ["add", "slack-sweep-under-returns", "--summary", "same finding, sharper",
             "--evidence", "de -> 2 where a -> 17"],
            "re-add bumps instead of duplicating",
            stdout_contains="bumped slack-sweep-under-returns (seen=2)",
        )
        record("no duplicate row created", len(read_json(bundle)["items"]) == 1)
        record("re-add adopts the sharper summary",
               item_of(bundle, "slack-sweep-under-returns")["summary"] == "same finding, sharper")

        check(bundle, ["bump", "slack-sweep-under-returns", "--evidence", "18/24 measured"],
              "bump reaches the seen>=3 config gate",
              stdout_contains="(seen=3)")
        item = item_of(bundle, "slack-sweep-under-returns")
        record("seen counts runs, not evidence lines",
               item["seen"] == 3 and len(item["evidence"]) == 3)
        record("last_seen moved past first_seen", item["last_seen"] >= item["first_seen"])

        # duplicate evidence must not inflate the list
        run(bundle, ["bump", "slack-sweep-under-returns", "--evidence", "18/24 measured"])
        record("identical evidence is de-duplicated, seen still counts",
               len(item_of(bundle, "slack-sweep-under-returns")["evidence"]) == 3
               and item_of(bundle, "slack-sweep-under-returns")["seen"] == 4)

        # evidence stays bounded for an item that nags for months
        for i in range(8):
            run(bundle, ["bump", "slack-sweep-under-returns", "--evidence", f"run {i}"])
        record("evidence list is capped",
               len(item_of(bundle, "slack-sweep-under-returns")["evidence"]) <= 5)

        # --- close / reopen ------------------------------------------------
        run(bundle, ["add", "hash-truncation", "--summary", "unquoted # truncates description"])
        check(bundle, ["close", "hash-truncation", "--note", "already fixed; 25 left are (# and safe"],
              "close marks an item done", stdout_contains="closed hash-truncation")
        closed = item_of(bundle, "hash-truncation")
        record("closed item keeps its history",
               closed["status"] == "closed" and closed["closed"] and closed["seen"] == 1)
        check(bundle, ["count", "--status", "open"], "count excludes closed", expect_stdout="1")
        check(bundle, ["count", "--status", "all"], "count --status all includes closed",
              expect_stdout="2")

        check(bundle, ["add", "hash-truncation", "--summary", "came back"],
              "re-filing a closed id reopens it", stdout_contains="reopened")
        record("reopen preserves the counter",
               item_of(bundle, "hash-truncation")["seen"] == 2)
        run(bundle, ["close", "hash-truncation", "--note", "closed again"])

        # --- error handling -------------------------------------------------
        check(bundle, ["bump", "no-such-item"], "bump on an unknown id fails loudly",
              expect_zero=False)
        check(bundle, ["close", "no-such-item"], "close on an unknown id fails loudly",
              expect_zero=False)
        check(bundle, ["bump", "hash-truncation"], "bump on a closed id fails loudly",
              expect_zero=False)
        check(bundle, ["add", "Bad_ID", "--summary", "x"], "add rejects a non-slug id",
              expect_zero=False)
        check(bundle, ["get", "no-such-item"], "get on an unknown id exits 1",
              expect_zero=False)
        check(bundle, ["add", "orphan-no-summary"], "add requires --summary",
              expect_zero=False)

        # --- (c) backlog.md is a faithful rendering --------------------------
        md = read_md(bundle)
        record("md lists the open item with its counter",
               "slack-sweep-under-returns" in md and "## Open (1)" in md)
        record("md carries the closed item in the history table",
               "## Closed (1)" in md and "closed again" in md)
        record("md warns against hand-editing",
               "do not hand-edit" in md and "backlog.json" in md)
        record("md gives a copy-pasteable close command",
               "backlog.py close slack-sweep-under-returns" in md)

        # a stale md must be reproducible from the canonical json alone
        (bundle / "state" / "backlog.md").write_text("clobbered\n", encoding="utf-8")
        check(bundle, ["render"], "render rebuilds md from json",
              stdout_contains="backlog.md regenerated")
        record("rebuilt md matches the pre-clobber content", read_md(bundle) == md)

        # --- --at makes runs replayable --------------------------------------
        run(bundle, ["add", "dated-item", "--summary", "x", "--at", "2026-08-01T12:00:00-03:00"])
        record("--at overrides now",
               item_of(bundle, "dated-item")["first_seen"] == "2026-08-01T12:00:00-03:00")

        # --- json output is machine-readable ---------------------------------
        result = run(bundle, ["list", "--status", "all", "--json"])
        try:
            rows = json.loads(result.stdout)
            record("list --json emits parseable JSON, most-nagged first",
                   isinstance(rows, list) and len(rows) == 3
                   and rows[0]["id"] == "slack-sweep-under-returns")
        except json.JSONDecodeError as exc:
            record("list --json emits parseable JSON, most-nagged first", False, str(exc))

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
