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
  (e) **the pyramid holds its shape** — `roll` places a citation on the right
      step for its age, coarsens a bucket as it ages and never refines one back,
      folds each log line exactly once however often it runs, and drops items
      whose file is gone. Counts are exact across every coarsening; only the
      labels get lossy. `score` reads it, and reads an absent or malformed
      record as "never cited" rather than as an error;
  (f) the plugin-checkout guard. It was on 9 of the 11 shipped scripts; this
      script is the tenth of twelve, and `smoke.py` derives that census by
      globbing, so the guard is asserted there too rather than only here;
  (g) the suite is registered in CI by its own `- run:` line — the workflow has
      no glob, and `test_backlog.py` went a whole release unrun because of it;
  (h) **the leak cannot outlive a roll** — the seed `.gitignore` reaches new
      bundles only, so `roll` appends the `state/` rules any bundle is missing
      before it writes the record naming which people were looked up and when.
      Appending only, once, never a line it did not write, and when the rules
      cannot be confirmed at all the roll is refused rather than written
      unprotected;
  (i) **a partial write costs one line, and `roll` says what it dropped** — an
      append onto an unterminated fragment starts its own line instead of being
      swallowed by it, and "0 line(s) folded" no longer covers "nothing new",
      "a citation arrived behind the watermark" and "unreadable" with one
      number. The drop count is what THIS run dropped, so a quiet run reports
      none at all rather than re-counting what earlier runs folded.

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
import traceback
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


def recall_json(bundle):
    path = bundle / "state" / "recall.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# The pyramid's boundaries, seen from REF. Hardcoded rather than recomputed
# with isocalendar(), which would just re-derive the implementation and assert
# it against itself.
REF = "2026-09-03"
AGES = {
    0: ("2026-09-03", "2026-09-03"),   # today — its own day bucket
    13: ("2026-08-21", "2026-08-21"),  # last day that keeps its own date
    14: ("2026-08-20", "2026-W34"),    # first day that folds into its week
    89: ("2026-06-06", "2026-W23"),    # last week
    90: ("2026-06-05", "2026-06"),     # first month
    364: ("2025-09-04", "2025-09"),    # last month
    365: ("2025-09-03", "older"),      # the aggregate
}


def roll_and_score(tmp):
    """(e) — the pyramid, its idempotence, its pruning, and the lookup over it."""
    bundle = make_bundle(tmp, name="rolled")
    (bundle / "knowledge" / "loops").mkdir()
    (bundle / "knowledge" / "sources").mkdir()

    # --- E5: nothing to derive from, so nothing is derived ------------------
    result = check(bundle, ["roll"], "roll with no consumption log exits 0")
    record(
        "…and writes no recall.json: a bundle never read carries no record of it",
        not (bundle / "state" / "recall.json").exists(),
    )
    (bundle / "state" / "consumption-log.jsonl").write_text("\n\n", encoding="utf-8")
    check(bundle, ["roll"], "roll over an empty log exits 0")
    record("…and still writes nothing",
           not (bundle / "state" / "recall.json").exists())

    # --- E2: score before anything was ever rolled --------------------------
    result = check(bundle, ["score", "--item", "/loops/l1.md", "--json"],
                   "score with no recall.json exits 0")
    scored = json.loads(result.stdout)
    record(
        "an item with no record scores as never cited, not as missing",
        scored["items"]["/loops/l1.md"] == {"total": 0, "last": None, "buckets": {}},
        result.stdout,
    )
    record("score does not materialize recall.json either",
           not (bundle / "state" / "recall.json").exists())

    # --- the pyramid: one citation per step, placed by age ------------------
    (bundle / "state" / "consumption-log.jsonl").unlink()
    for age, (day, _bucket) in sorted(AGES.items()):
        run(bundle, ["log", "--mode", "query", "--item", "/loops/l1.md",
                     "--at", f"{day}T09:00:00-03:00"])
    # item-agnostic: a fact, a loop and a source ride the same roll-up, and so
    # do the entity slugs, which are not paths at all.
    for path in ("/facts/x.md", "/loops/l1.md", "/sources/s.md"):
        (bundle / "knowledge" / path.lstrip("/")).write_text("x\n", encoding="utf-8")
    run(bundle, ["log", "--mode", "briefing",
                 "--item", "/facts/x.md", "--item", "/sources/s.md",
                 "--item", "/facts/deleted.md", "--entity", "angelo",
                 "--at", f"{REF}T10:00:00-03:00"])

    check(bundle, ["roll", "--at", f"{REF}T12:00:00-03:00"], "roll folds the log")
    data = recall_json(bundle)
    expected = {}
    for _age, (_day, bucket) in AGES.items():
        expected[bucket] = expected.get(bucket, 0) + 1
    loop = (data or {}).get("items", {}).get("/loops/l1.md", {})
    record(
        "each citation lands on the pyramid step its age calls for",
        loop.get("buckets") == expected,
        f"expected {expected}\ngot {loop.get('buckets')}",
    )
    record(
        "the exact last-citation date survives the bucketing decay reads it",
        loop.get("last") == AGES[0][0] and loop.get("total") == len(AGES),
        repr(loop),
    )
    record(
        "a fact, a source and an entity roll up beside the loop, same shape",
        set(data["items"]) == {"/loops/l1.md", "/facts/x.md", "/sources/s.md"}
        and data["entities"]["angelo"]["last"] == REF,
        repr(sorted(data["items"])) + " / " + repr(data["entities"]),
    )
    record(
        "E6 — a cited path that no longer exists is pruned at the roll",
        "/facts/deleted.md" not in data["items"],
        repr(sorted(data["items"])),
    )
    record("rolled_through watermarks the newest line folded",
           (data.get("rolled_through") or "").startswith(f"{REF}T10:00:00"),
           repr(data.get("rolled_through")))

    # --- E4: idempotence over a log re-read whole ---------------------------
    before = json.dumps(data["items"], sort_keys=True)
    check(bundle, ["roll", "--at", f"{REF}T13:00:00-03:00"], "a second roll exits 0")
    again = recall_json(bundle)
    record(
        "E4 — re-rolling the same lines adds nothing to any count",
        json.dumps(again["items"], sort_keys=True) == before,
        f"before {before}\nafter  {json.dumps(again['items'], sort_keys=True)}",
    )
    record("…and leaves the watermark where it was",
           again["rolled_through"] == data["rolled_through"])

    # a genuinely new line, past the watermark, still lands
    run(bundle, ["log", "--mode", "query", "--item", "/loops/l1.md",
                 "--at", f"{REF}T18:00:00-03:00"])
    run(bundle, ["roll", "--at", f"{REF}T19:00:00-03:00"])
    data = recall_json(bundle)
    record("a line written after the watermark is folded on the next roll",
           data["items"]["/loops/l1.md"]["total"] == len(AGES) + 1,
           repr(data["items"]["/loops/l1.md"]))

    # a backdated replay at-or-before the watermark is the watermark's cost
    run(bundle, ["log", "--mode", "query", "--item", "/loops/l1.md",
                 "--at", "2026-09-01T09:00:00-03:00"])
    run(bundle, ["roll", "--at", f"{REF}T20:00:00-03:00"])
    record("…while one backdated behind the watermark is the watermark's known cost",
           recall_json(bundle)["items"]["/loops/l1.md"]["total"] == len(AGES) + 1)

    # --- coarsening: lossy in labels, exact in counts -----------------------
    total_before = recall_json(bundle)["items"]["/loops/l1.md"]["total"]
    run(bundle, ["roll", "--at", "2026-09-20T12:00:00-03:00"])
    aged = recall_json(bundle)["items"]["/loops/l1.md"]
    record(
        "a day bucket past 14 days folds into its ISO week",
        "2026-09-03" not in aged["buckets"] and "2026-W36" in aged["buckets"],
        repr(aged["buckets"]),
    )
    record("…and the week it lands in carries every citation that was in those days",
           aged["buckets"]["2026-W36"] == 2, repr(aged["buckets"]))
    record("…and the last-citation date is untouched by the coarsening",
           aged["last"] == AGES[0][0], repr(aged["last"]))

    run(bundle, ["roll", "--at", "2026-12-20T12:00:00-03:00"])
    aged = recall_json(bundle)["items"]["/loops/l1.md"]
    record("a week bucket past 90 days folds into its calendar month",
           "2026-W36" not in aged["buckets"] and aged["buckets"].get("2026-09") == 2,
           repr(aged["buckets"]))

    run(bundle, ["roll", "--at", "2030-01-01T12:00:00-03:00"])
    aged = recall_json(bundle)["items"]["/loops/l1.md"]
    record("everything past a year collapses into the one aggregate",
           list(aged["buckets"]) == ["older"], repr(aged["buckets"]))
    record("no citation was lost or invented across three coarsenings",
           aged["total"] == total_before == sum(aged["buckets"].values()),
           f"{aged['total']} vs {total_before} vs {aged['buckets']}")

    # monotone: a week bucket holds days as new as its Sunday, and must not be
    # reclassified by that Sunday back into a single day.
    mono = make_bundle(tmp, name="monotone")
    (mono / "knowledge" / "loops").mkdir()
    (mono / "knowledge" / "loops" / "m.md").write_text("x\n", encoding="utf-8")
    for day in ("2026-08-17", "2026-08-23"):  # Monday and Sunday of one ISO week
        run(mono, ["log", "--mode", "query", "--item", "/loops/m.md",
                   "--at", f"{day}T09:00:00-03:00"])
    run(mono, ["roll", "--at", "2026-09-06T12:00:00-03:00"])  # Sunday is 14d old
    buckets = recall_json(mono)["items"]["/loops/m.md"]["buckets"]
    record("both days of that week are in the week bucket to begin with",
           buckets == {"2026-W34": 2}, repr(buckets))
    run(mono, ["roll", "--at", "2026-08-30T12:00:00-03:00"])  # a ref that moved back
    buckets = recall_json(mono)["items"]["/loops/m.md"]["buckets"]
    record("a coarsened bucket never refines back into a finer one",
           buckets == {"2026-W34": 2}, repr(buckets))

    # --- E3: a malformed record is rebuilt forward, not fatal ---------------
    (bundle / "state" / "recall.json").write_text("{ not json", encoding="utf-8")
    result = check(bundle, ["score", "--item", "/loops/l1.md", "--json"],
                   "score over a malformed record exits 0")
    record("E3 — …reporting no citation, and saying so once on stderr",
           json.loads(result.stdout)["items"]["/loops/l1.md"]["total"] == 0
           and "warning" in result.stderr,
           result.stdout + result.stderr)
    result = check(bundle, ["roll", "--at", "2030-01-02T12:00:00-03:00"],
                   "roll over a malformed record exits 0")
    record("…and roll rebuilds it forward from the lines past the lost watermark",
           isinstance(recall_json(bundle), dict)
           and recall_json(bundle)["items"] != {},
           json.dumps(recall_json(bundle))[:400])

    # a bucket key that is not a key at all: the count is real, the label is not
    (bundle / "state" / "recall.json").write_text(json.dumps({
        "schema": 1, "rolled_through": None, "generated": None,
        "items": {"/loops/l1.md": {"total": 9, "last": "nonsense",
                                   "buckets": {"junk": 4, "2026-09-03": 5}}},
        "entities": {},
    }), encoding="utf-8")
    run(bundle, ["roll", "--at", "2030-01-03T12:00:00-03:00"])
    item = recall_json(bundle)["items"]["/loops/l1.md"]
    record("a hand-mangled bucket key folds into the aggregate instead of raising",
           item["buckets"].get("older", 0) >= 9, repr(item))
    record("…and a `last` that is not a date is replaced, never carried through",
           item["last"] != "nonsense"
           and (item["last"] is None or len(item["last"]) == 10), repr(item["last"]))

    # --- pruning is skipped when knowledge/ is not there at all -------------
    orphan = make_bundle(tmp, name="orphan")
    (orphan / "knowledge" / "facts" / "keep.md").write_text("x\n", encoding="utf-8")
    run(orphan, ["log", "--mode", "query", "--item", "/facts/keep.md",
                 "--at", f"{REF}T09:00:00-03:00"])
    run(orphan, ["roll", "--at", f"{REF}T10:00:00-03:00"])
    shutil.rmtree(orphan / "knowledge")
    run(orphan, ["log", "--mode", "query", "--item", "/facts/keep.md",
                 "--at", f"{REF}T11:00:00-03:00"])
    result = check(orphan, ["roll", "--at", f"{REF}T12:00:00-03:00"],
                   "roll with no knowledge/ dir exits 0")
    record("…and prunes nothing: a missing knowledge/ is a partial checkout, not 300 deletions",
           "/facts/keep.md" in recall_json(orphan)["items"],
           json.dumps(recall_json(orphan)["items"]))

    # --- score: the shape decay reads --------------------------------------
    scored = check(bundle, ["score", "--item", "knowledge/loops/l1.md"],
                   "score normalizes the spelling it is handed",
                   stdout_contains="/loops/l1.md")
    record("score's rows are tab-separated kind/key/last/count",
           scored.stdout.strip().split("\t")[0] == "item"
           and len(scored.stdout.strip().split("\t")) == 4, repr(scored.stdout))
    result = check(bundle, ["score"], "bare score reports the whole record",
                   stdout_contains="entity\t")

    mod = import_copy(bundle, "recall_roll_under_test")
    loaded = mod.load()
    record(
        "last_cited is the per-item lookup decay makes over one load()",
        mod.last_cited(loaded, "/loops/l1.md") == mod.entry(
            loaded["items"]["/loops/l1.md"])["last"],
    )
    record("…and an item never cited answers None rather than raising",
           mod.last_cited(loaded, "/loops/never.md") is None)
    record("…as does a lookup against the empty record (E2)",
           mod.last_cited(mod.empty(), "/loops/l1.md") is None)

    # a malformed log line costs its own line and no other
    (bundle / "state" / "consumption-log.jsonl").write_text(
        '{"ts": "2030-02-01T09:00:00-03:00", "mode": "query", "entities": [], '
        '"facts_cited": ["/loops/l1.md"]}\n'
        "not json at all\n"
        '{"ts": "nope", "mode": "query", "entities": [], "facts_cited": ["/x.md"]}\n'
        '{"ts": "2030-02-02T09:00:00-03:00", "mode": "query", "entities": ["ana"], '
        '"facts_cited": []}\n',
        encoding="utf-8",
    )
    (bundle / "state" / "recall.json").unlink()
    result = check(bundle, ["roll", "--at", "2030-02-03T12:00:00-03:00"],
                   "roll over a log with two bad lines exits 0")
    data = recall_json(bundle)
    record("…folding the two good lines and skipping only the bad ones",
           data["items"]["/loops/l1.md"]["total"] == 1
           and data["entities"]["ana"]["total"] == 1,
           json.dumps(data["items"]) + json.dumps(data["entities"]))


def gitignore_guarantee(tmp):
    """(h) — both writers guarantee the leaking files are ignored, on any bundle.

    The seed carries the rules, but `init` copies the seed `.gitignore` once and
    `update` re-syncs only `scripts/` and `templates/`, while `catch-up`,
    `decay`, `close-loops` and `ingest` all end in `git add -A`. So on every
    bundle that predates a rule the files naming which people were looked up and
    when would be committed. The rules used to be `roll`'s business alone, which
    is one step too late for the file `log` writes: `catch-up` commits before it
    rolls, and two of the four routines never roll at all. Each writer protects
    the file it creates, `log` loudly enough to be seen only when it refuses.
    """
    rules = ("state/consumption-log.jsonl", "state/recall.json",
             "state/last-update-check.json")

    # a bundle carrying main's older seed: two rules of the three, plus lines
    # of its own that must survive untouched.
    older = make_bundle(tmp, name="older-seed")
    (older / "knowledge" / "facts" / "x.md").write_text("x\n", encoding="utf-8")
    before = (
        "# elephant-mem bundle — ignore operational / machine-local artifacts\n"
        "state/phone/\n"
        "state/consumption-log.jsonl\n"
        ".cache/\n"
    )
    (older / ".gitignore").write_text(before, encoding="utf-8")
    logged = check(older, ["log", "--mode", "query", "--item", "/facts/x.md",
                           "--at", f"{REF}T09:00:00-03:00"],
                   "log on a bundle whose .gitignore predates the rules exits 0")
    text = (older / ".gitignore").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines()]
    record(
        "…having written the missing rules before the line it appended: the "
        "writer of the file that leaks is the one that protects it",
        all(rule in lines for rule in rules) and len(log_lines(older)) == 1,
        text + repr(log_lines(older)),
    )
    record("…and saying nothing at all about it, because a read's transcript "
           "is the answer's and not the bookkeeping's",
           silent(logged),
           f"stdout:\n{logged.stdout}\nstderr:\n{logged.stderr}")
    record("…appending only: every line the bundle already had is still there",
           text.startswith(before), text)
    record("…and the rule it already carried was not duplicated",
           lines.count("state/consumption-log.jsonl") == 1, text)
    frozen_by_log = text
    run(older, ["log", "--mode", "briefing", "--item", "/facts/x.md",
                "--at", f"{REF}T09:30:00-03:00"])
    record(
        "…and the read after it appends its line and nothing to .gitignore: "
        "the rules are written once per bundle, not once per citation",
        (older / ".gitignore").read_text(encoding="utf-8") == frozen_by_log
        and len(log_lines(older)) == 2,
        (older / ".gitignore").read_text(encoding="utf-8"),
    )
    result = check(older, ["roll", "--at", f"{REF}T10:00:00-03:00"],
                   "the roll behind that read exits 0")
    record("…and finds nothing left to add, so it says nothing either",
           (older / ".gitignore").read_text(encoding="utf-8") == frozen_by_log
           and ".gitignore" not in result.stdout,
           result.stdout)

    # the same bundle shape, but with the line written straight to disk so no
    # read ever ran: `roll` is the first writer here, and it is the loud one.
    # An unattended catch-up leaves a trace that the bundle was missing a rule.
    quiet_seed = make_bundle(tmp, name="older-seed-unread")
    (quiet_seed / "knowledge" / "facts" / "x.md").write_text("x\n", encoding="utf-8")
    (quiet_seed / ".gitignore").write_text(before, encoding="utf-8")
    (quiet_seed / "state" / "consumption-log.jsonl").write_text(
        json.dumps({"ts": f"{REF}T09:00:00-03:00", "mode": "query",
                    "entities": [], "facts_cited": ["/facts/x.md"]}) + "\n",
        encoding="utf-8",
    )
    result = check(quiet_seed, ["roll", "--at", f"{REF}T10:00:00-03:00"],
                   "roll on a bundle whose .gitignore predates the rules exits 0")
    quiet_lines = [ln.strip() for ln in
                   (quiet_seed / ".gitignore").read_text(encoding="utf-8").splitlines()]
    record(
        "…and the missing rules are there before the record it just wrote is",
        all(rule in quiet_lines for rule in rules)
        and (quiet_seed / "state" / "recall.json").exists(),
        repr(quiet_lines),
    )
    record("…said once on stdout, so an unattended run leaves a trace of it",
           "state/recall.json" in result.stdout, result.stdout)

    frozen = text
    result = check(older, ["roll", "--at", f"{REF}T11:00:00-03:00"],
                   "a second roll exits 0")
    record("…and adds nothing: the file is byte-identical",
           (older / ".gitignore").read_text(encoding="utf-8") == frozen)
    record("…and says nothing about .gitignore either",
           ".gitignore" not in result.stdout, result.stdout)

    # a bundle with no .gitignore at all — every bundle predating the seed file
    naked = make_bundle(tmp, name="no-gitignore")
    (naked / "knowledge" / "facts" / "x.md").write_text("x\n", encoding="utf-8")
    run(naked, ["log", "--mode", "query", "--item", "/facts/x.md",
                "--at", f"{REF}T09:00:00-03:00"])
    check(naked, ["roll", "--at", f"{REF}T10:00:00-03:00"],
          "roll on a bundle with no .gitignore at all exits 0")
    naked_lines = [ln.strip() for ln in
                   (naked / ".gitignore").read_text(encoding="utf-8").splitlines()]
    record("…and it gets one carrying every rule",
           all(rule in naked_lines for rule in rules), repr(naked_lines))

    # a bundle already ignoring the whole directory needs none of them
    blanket = make_bundle(tmp, name="blanket")
    (blanket / "knowledge" / "facts" / "x.md").write_text("x\n", encoding="utf-8")
    (blanket / ".gitignore").write_text("state/\n", encoding="utf-8")
    run(blanket, ["log", "--mode", "query", "--item", "/facts/x.md",
                  "--at", f"{REF}T09:00:00-03:00"])
    run(blanket, ["roll", "--at", f"{REF}T10:00:00-03:00"])
    record("a bundle that ignores state/ as a block gains no redundant rule",
           (blanket / ".gitignore").read_text(encoding="utf-8") == "state/\n",
           (blanket / ".gitignore").read_text(encoding="utf-8"))

    # the seed is where a new bundle gets them, and `init` copies it once
    seed = REPO_ROOT / "plugin" / "assets" / "seed" / ".gitignore"
    seed_lines = [ln.strip() for ln in seed.read_text(encoding="utf-8").splitlines()]
    record("the seed .gitignore carries the same three rules, for new bundles",
           all(rule in seed_lines for rule in rules), repr(seed_lines))

    # the protection failing is not the protection being unnecessary. Here
    # `.gitignore` cannot be written (a directory occupies the path, which is
    # portable where a chmod check is a no-op on Windows) while `state/` is
    # perfectly writable: the roll-up would land unignored, and the next
    # `git add -A` in decay or catch-up would publish which entities were
    # consulted and when. `ensure_gitignore()` answered `[]` for this and for
    # "nothing needed adding" alike, so `roll` saved either way.
    obstructed = make_bundle(tmp, name="gitignore-obstructed")
    (obstructed / "knowledge" / "facts" / "x.md").write_text("x\n", encoding="utf-8")
    (obstructed / ".gitignore").mkdir()
    logged = check(obstructed, ["log", "--mode", "query", "--item", "/facts/x.md",
                                "--at", f"{REF}T09:00:00-03:00"],
                   "log still exits 0 when the ignore rules cannot be confirmed")
    record(
        "…and writes no line at all: the citation is the payload, and one "
        "written unignored is taken by the next `git add -A` for good",
        log_lines(obstructed) == [], repr(log_lines(obstructed)),
    )
    record(
        "…saying why on stderr and nothing on stdout, so the answer is untouched "
        "while the skip is not silent",
        "skipped one consumption line" in logged.stderr
        and ".gitignore" in logged.stderr
        and logged.stdout.strip() == "",
        f"stdout:\n{logged.stdout}\nstderr:\n{logged.stderr}",
    )

    # a line that predates the obstruction, written straight to disk: `roll`
    # refuses over it and must leave it exactly where it is.
    (obstructed / "state" / "consumption-log.jsonl").write_text(
        json.dumps({"ts": f"{REF}T09:00:00-03:00", "mode": "query",
                    "entities": [], "facts_cited": ["/facts/x.md"]}) + "\n",
        encoding="utf-8",
    )
    result = check(obstructed, ["roll", "--at", f"{REF}T10:00:00-03:00"],
                   "roll refuses when the ignore rules cannot be confirmed",
                   expect_zero=False)
    record("…and writes no recall.json, which is the file that would leak",
           not (obstructed / "state" / "recall.json").exists())
    record("…and says on stderr what it refused and why, rather than failing mute",
           "refusing to roll" in result.stderr and ".gitignore" in result.stderr,
           result.stderr)
    record("…while the log it could not roll is left exactly as it was",
           len(log_lines(obstructed)) == 1, repr(log_lines(obstructed)))

    # The other half of the same promise. Above, `.gitignore` is a directory,
    # so `read_text` never runs and it is the append that fails; here it is a
    # file of bytes that are not UTF-8, which is the read failing. That branch
    # was unguarded: mutated to answer `(True, [])`, all eleven suites stayed
    # green while an unreadable .gitignore read as an ignoring one.
    unreadable = make_bundle(tmp, name="gitignore-unreadable")
    (unreadable / "knowledge" / "facts" / "x.md").write_text("x\n", encoding="utf-8")
    raw = b"# elephant-mem bundle\nstate/phone/\n\xff\xfe not utf-8\n"
    (unreadable / ".gitignore").write_bytes(raw)
    logged = check(unreadable, ["log", "--mode", "query", "--item", "/facts/x.md",
                                "--at", f"{REF}T09:00:00-03:00"],
                   "log exits 0 when .gitignore cannot be read either")
    record("…and writes no line: a .gitignore that cannot be read is not a "
           ".gitignore that ignores",
           log_lines(unreadable) == [] and "skipped one consumption line" in logged.stderr,
           repr(log_lines(unreadable)) + logged.stderr)
    result = check(unreadable, ["roll", "--at", f"{REF}T10:00:00-03:00"],
                   "roll refuses over an unreadable .gitignore too",
                   expect_zero=False)
    record("…writing no record, and leaving the file it could not read "
           "byte-identical rather than appending to what it cannot parse",
           not (unreadable / "state" / "recall.json").exists()
           and (unreadable / ".gitignore").read_bytes() == raw,
           repr((unreadable / ".gitignore").read_bytes()))


def partial_write_and_report(tmp):
    """(i) — a fragment costs its own line and no other, and `roll` says so."""
    bundle = make_bundle(tmp, name="fragment")
    (bundle / "knowledge" / "facts" / "real.md").write_text("x\n", encoding="utf-8")
    log = bundle / "state" / "consumption-log.jsonl"

    # what a mid-flush disk-full leaves behind: a line with no terminator.
    log.write_text(
        '{"ts": "2026-09-01T09:00:00-03:00", "mode": "query", "entities": [], '
        '"facts_ci',
        encoding="utf-8",
    )
    run(bundle, ["log", "--mode", "query", "--item", "/facts/real.md",
                 "--at", f"{REF}T09:00:00-03:00"])
    raw = log.read_text(encoding="utf-8")
    record(
        "an append onto an unterminated fragment starts its own physical line",
        len(log_lines(bundle)) == 2 and raw.endswith("\n"),
        repr(raw),
    )
    mod = import_copy(bundle, "recall_fragment_under_test")
    rows, unparseable = mod.log_rows()
    record(
        "…so the fragment costs its own line and no other: 1 row, 1 unparseable",
        len(rows) == 1 and unparseable == 1,
        f"{len(rows)} rows, {unparseable} unparseable",
    )
    result = check(bundle, ["roll", "--at", f"{REF}T10:00:00-03:00"],
                   "roll over a log with a fragment in it exits 0")
    record("…and the good line lands in the pyramid",
           recall_json(bundle)["items"]["/facts/real.md"]["total"] == 1,
           json.dumps(recall_json(bundle)["items"]))
    record("…and roll names the unparseable line rather than staying mute",
           "1 unparseable" in result.stdout, result.stdout)

    # the three situations that all used to print "0 line(s) folded". The
    # counter names what THIS run dropped, so a run with nothing new says
    # nothing about drops at all: it used to report every line at or below the
    # watermark, which is mostly what earlier runs already folded, so the
    # number grew with the log and the two runs below differed by a figure the
    # operator had nothing to compare against.
    quiet = check(bundle, ["roll", "--at", f"{REF}T10:30:00-03:00"],
                  "a roll over an unchanged log exits 0")
    record(
        "…and reports no drop: the line an earlier run folded is not this "
        "run's news",
        "0 line(s) folded" in quiet.stdout and "dropped" not in quiet.stdout,
        quiet.stdout,
    )

    run(bundle, ["log", "--mode", "query", "--item", "/facts/real.md",
                 "--at", "2026-08-01T09:00:00-03:00"])  # behind the watermark
    result = check(bundle, ["roll", "--at", f"{REF}T11:00:00-03:00"],
                   "a roll over a line behind the watermark exits 0")
    record(
        "…and reports exactly the one line that arrived late, not the two at "
        "or below the watermark",
        "0 line(s) folded" in result.stdout
        and "1 line(s) dropped for arriving since the last roll" in result.stdout,
        result.stdout,
    )
    record(
        "…so a dropped citation reads apart from a quiet run by a whole clause, "
        "not by a number with nothing to compare it against",
        "dropped" in result.stdout and "dropped" not in quiet.stdout,
        f"quiet:\n{quiet.stdout}\nlate:\n{result.stdout}",
    )
    record("…while the unparseable fragment is still counted, and separately",
           "1 unparseable" in result.stdout and "1 unparseable" in quiet.stdout,
           result.stdout + quiet.stdout)
    record("…while the count itself is unchanged, as the watermark promises",
           recall_json(bundle)["items"]["/facts/real.md"]["total"] == 1)

    # a third run over the same log repeats the one drop rather than growing
    # it: the late line is permanently unfolded, and saying so once per run is
    # the honest report. It is the accumulation of already-folded rows that was
    # the bug.
    again = check(bundle, ["roll", "--at", f"{REF}T12:00:00-03:00"],
                  "a further roll over the same log exits 0")
    record("…and still reports 1 dropped, not 2: the number tracks the late "
           "line, not the length of the log",
           "1 line(s) dropped for arriving since the last roll" in again.stdout,
           again.stdout)

    junk = make_bundle(tmp, name="junk-log")
    (junk / "state" / "consumption-log.jsonl").write_text(
        "not json at all\nnor this\n", encoding="utf-8")
    result = check(junk, ["roll"], "roll over a log of nothing but junk exits 0")
    record(
        "…and reads apart from an empty log, which prints the same 0 today",
        "2 unparseable" in result.stdout
        and "empty or absent" not in result.stdout,
        result.stdout,
    )
    record("…and still derives no record from it",
           not (junk / "state" / "recall.json").exists())


def rotated_log_silence(tmp):
    """(j) — the one branch where a dropped citation is reported by nothing.

    `resume_index()` locates this run's territory by finding the row the
    watermark names. A rotated, truncated or hand-edited log carries no such
    row, and the tail of that function then calls the whole log already seen:
    nothing is folded, and a line below the watermark is dropped without a word.
    The alternative, treating the whole log as this run's news, would accuse
    every line of a rotated log on every roll forever, so the silence is the
    trade the docstring picks. It is pinned here because it is the branch this
    lane set out to remove and deliberately kept: a change to that tail should
    fail a named check rather than quietly start reporting, or quietly stop.
    """
    bundle = make_bundle(tmp, name="rotated")
    (bundle / "knowledge" / "facts" / "real.md").write_text("x\n", encoding="utf-8")
    for stamp in ("2026-09-01T10:00:00-03:00", "2026-09-01T11:00:00-03:00"):
        run(bundle, ["log", "--mode", "query", "--item", "/facts/real.md",
                     "--at", stamp])
    check(bundle, ["roll", "--at", f"{REF}T12:00:00-03:00"],
          "roll folds a two-line log")
    watermark = recall_json(bundle)["rolled_through"]
    record("…and watermarks the newest line it folded",
           watermark == "2026-09-01T11:00:00-03:00", repr(watermark))

    # rotation: the log is replaced wholesale, so no row carries the watermark
    # any more, and the single line in it is backdated below it.
    (bundle / "state" / "consumption-log.jsonl").write_text(
        json.dumps({"ts": "2026-08-15T09:00:00-03:00", "mode": "query",
                    "entities": [], "facts_cited": ["/facts/real.md"]}) + "\n",
        encoding="utf-8",
    )
    result = check(bundle, ["roll", "--at", f"{REF}T13:00:00-03:00"],
                   "a roll over a rotated log exits 0")
    record("…folding nothing, because a log with no watermark row in it reads "
           "as one this run has already seen whole",
           "0 line(s) folded" in result.stdout, result.stdout)
    record(
        "…and reporting no drop at all: the run accuses no row it cannot place, "
        "which is where a lost citation is still silent",
        "dropped" not in result.stdout and "dropped" not in result.stderr,
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )
    record("…and the citation really is lost, not merely unreported",
           recall_json(bundle)["items"]["/facts/real.md"]["total"] == 2,
           json.dumps(recall_json(bundle)["items"]))


def not_committed(tmp):
    """(k) — the leak measured where it happened: what `git add -A` takes.

    Every check above is about a `.gitignore` line. This one is about the
    consequence, and it is the check whose absence let the leak ship: a bundle
    predating the rules, one read, then the commit its routine makes. `roll`
    guaranteed the rules, but `catch-up` commits *before* it rolls
    (`_shared/core.md` fixes that order) and `close-loops` and `ingest` never
    roll, so the log went into the commit and no later rule untracked it. On a
    bundle with a remote, that is a per-query record of which people were looked
    up and which facts were cited, pushed.
    """
    git = shutil.which("git")
    labels = (
        "a read's citation is not in the commit that follows it",
        "…and the line was still written, so the protection cost no recall",
        "…nor is the roll-up, in the commit after the roll",
    )
    if not git:
        for label in labels:
            record(label, False,
                   "git not found on PATH — expected on every GitHub-hosted runner")
        return

    bundle = make_bundle(tmp, name="git-bundle")
    (bundle / "knowledge" / "facts" / "salary-2026.md").write_text(
        "x\n", encoding="utf-8")
    # the seed as it was before the rules existed: this is the bundle already
    # on disk that `update` will never reach, since it re-syncs scripts/ and
    # templates/ and deliberately not .gitignore.
    (bundle / ".gitignore").write_text(
        "# elephant-mem bundle\n.cache/\n", encoding="utf-8")

    def git_run(*args):
        return subprocess.run(
            [git, "-c", "user.email=ci@example.com", "-c", "user.name=Elephant CI",
             "-c", "commit.gpgsign=false"] + list(args),
            cwd=str(bundle), capture_output=True, text=True, encoding="utf-8",
        )

    git_run("init", "-q")
    git_run("add", "-A")
    git_run("commit", "-qm", "initial")

    run(bundle, ["log", "--mode", "query", "--item", "/facts/salary-2026.md",
                 "--entity", "alice-smith", "--at", f"{REF}T09:00:00-03:00"])
    git_run("add", "-A")
    git_run("commit", "-qm", "catch-up: sweep")
    tracked = git_run("ls-files", "state/").stdout.split()
    record(labels[0], tracked == [], repr(tracked))
    record(labels[1], len(log_lines(bundle)) == 1, repr(log_lines(bundle)))

    run(bundle, ["roll", "--at", f"{REF}T10:00:00-03:00"])
    git_run("add", "-A")
    git_run("commit", "-qm", "catch-up: roll")
    tracked = git_run("ls-files", "state/").stdout.split()
    record(labels[2], tracked == [], repr(tracked))


def guarded(fn, tmp):
    """Run one check group so a break in it costs its own checks and no others.

    Mirrors tests/test_index.py's guarded(). Called directly, an exception in
    any of these took the whole suite down with a raw traceback instead of a
    named FAIL, and the checks after it never ran at all: the group that raised
    would have looked like a passing run one check short.
    """
    try:
        fn(tmp)
    except Exception:  # noqa: BLE001 — report it and go on to the next group
        record(f"{fn.__name__} raised an unexpected exception", False,
               traceback.format_exc())


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

        # The version is written into every record, so it is read back out of
        # one: a record from a newer writer cannot be interpreted with v1
        # bucket semantics, and this file is disposable, so it reads as empty.
        (bundle / "state" / "recall.json").write_text(json.dumps({
            "schema": 99, "rolled_through": None, "generated": None,
            "items": {"/facts/x.md": {"total": 4, "last": "2026-09-03",
                                      "buckets": {"2026-09-03": 4}}},
            "entities": {},
        }), encoding="utf-8")
        result = run(bundle, ["show"])
        record("a record from a newer schema is not read with this one's semantics",
               result.returncode == 0
               and json.loads(result.stdout)["items"] == {}
               and "schema 99" in result.stderr,
               result.stdout + result.stderr)
        (bundle / "state" / "recall.json").unlink()

        for group in (roll_and_score, gitignore_guarantee,
                      partial_write_and_report, rotated_log_silence,
                      not_committed):
            guarded(group, tmp)

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

        # --- (f) E22: the plugin-checkout guard ------------------------------
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

        # --- (g) E24: the script ships, and the suite is wired into CI -------
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
