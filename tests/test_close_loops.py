#!/usr/bin/env python3
"""Standalone test suite for elephant-mem's `scripts/close-loops.py`.

`close-loops.py` is the read half of the closing routine: it decides which of a
1794-loop lane this run examines, and what evidence the routine judges. Nothing
it does is visible in a file afterwards, so a suite is the only place its two
decisions are observable at all. What is covered:

  (a) **the queue is two-banded and bounded** — band 1 is the loops examined
      before whose entities gained material since that examination, band 2 is
      everything else still unsettled, oldest last activity first, and the run
      stops at `close_loops_max` (H2, E9, E10). The band-2 order is the whole
      reason a run reaches the stale end of the lane first, the settling rule is
      the whole reason run N+1 reaches loops run N did not, and band 2's
      reserved fifth is the whole reason it is reached at all while band 1
      overflows;
  (b) **the evidence is scored additively and capped** — 2 a shared non-owner
      entity plus 1 a shared content word, then recency, then path, capped at 10,
      with the noise dropped rather than padded in (H3). The owner is on nearly
      every fact in a real bundle, which is why sharing only the owner ranks as
      nothing. The score's *composition* is pinned, not only its direction: the
      two counts have incomparable ranges, so nesting them reads as a working
      ranking right up to the point where it cuts the one fact that satisfies
      the criterion;
  (c) **the two degenerate readings answer in words** — a loop with no evidence
      is examined and left alone (E11), and a loop with no `**Closure signal:**`
      section is judged against its `description`, with the proposal saying so
      (E12);
  (d) **it reads and only reads** — no knowledge file changes, and
      `state/closure-sweep.json` is neither created nor rewritten. The routine
      writes; this script proposes;
  (e) **the template's trailing comments** — every loop in a real bundle carries
      `status: open  # open | done | dropped` and `entities: []  # …`, and a
      reader that keeps the comment goes silently blind. tests/test_templates.py
      drives the shipped templates; this suite pins the same rule on hand-built
      files so a failure localizes here;
  (f) the plugin-checkout guard (E22) — asserted in tests/smoke.py too, which
      derives its census by globbing, and again here so it fails close to home;
  (g) the suite is registered in CI by its own `- run:` line (E24) — the
      workflow has no glob, and `test_backlog.py` went a whole release unrun
      because of exactly that.
  (h) **the routine that consumes all of it** — `plugin/skills/close-loops/`
      is the write half, and it is prose, so what a suite can pin is the
      contract that prose carries: the judgment of the evidence set as a whole,
      the `status: done` / `closed` / `closed_by` / `**Resolution:**` write, the
      sweep entry for every examined loop whether it closed or not, the
      rebuild-validate-log-commit tail and its don't-commit-on-failure branch
      (H4, H5, H6, E13, E14, E23). One piece of that prose is executable and is
      executed here: the procedure prescribes the exact command that writes
      `state/closure-sweep.json`, and this suite lifts it out of the markdown,
      runs it, and hands the result back to `close-loops.py` — so a recipe that
      writes a shape the script cannot read fails here rather than in the field,
      where it would silently park `decay` instead.

Pure stdlib, Python 3.10+, mirroring `tests/test_recall.py`'s conventions: a
throwaway bundle in a tempdir, subprocess calls into a copy of the real
`plugin/assets/scripts/close-loops.py`, PASS/FAIL per check, exit code 0 only if
every check passes. Dates are fixed rather than relative to today: this script
has no staleness threshold, it only orders, so nothing here needs the calendar.
"""
import datetime
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugin" / "assets" / "scripts" / "close-loops.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "close-loops"
DECAY_SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "decay"

OWNER = "jane-doe"

checks = []  # (label, passed)


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    return passed


# --- a bundle -------------------------------------------------------------


def make_bundle(root, name):
    bundle = Path(root) / name
    (bundle / "scripts").mkdir(parents=True)
    (bundle / "knowledge" / "tracking" / "loops").mkdir(parents=True)
    (bundle / "knowledge" / "facts").mkdir(parents=True)
    (bundle / "knowledge" / "sources").mkdir(parents=True)
    (bundle / "state").mkdir(parents=True)
    shutil.copy2(SCRIPT, bundle / "scripts" / "close-loops.py")
    (bundle / "elephant.json").write_text(
        json.dumps({"owner": {"name": "Jane Doe", "slug": OWNER}}, indent=2),
        encoding="utf-8",
    )
    return bundle


def entity_link(slug, kind="person"):
    return f"/entities/{kind}/{slug}.md"


def write_loop(bundle, name, description="a commitment", owner=(OWNER,),
               entities=(), opened="2026-01-01", updated=None, created=None,
               status="open", signal="a source showing it shipped", body="Details."):
    """A loop in the shape open-loop.md ships — trailing comments and all.

    The comments are not decoration: `status: open  # open | done | dropped |
    expired` is what every loop written from the template carries, and it is
    what a naive reader glues onto the value. The fixtures below build the
    three-value comment the template used to ship, which is what the loops
    already on disk carry, so both spellings are exercised.
    """
    dates = ""
    for key, value in (("opened", opened), ("created", created or opened),
                       ("updated", updated or created or opened)):
        if value:
            dates += f"{key}: {value}\n"
    owners = ", ".join(entity_link(o) for o in owner)
    ents = ", ".join(entity_link(e) for e in entities)
    signal_block = f"\n\n**Closure signal:** {signal}" if signal else ""
    path = bundle / "knowledge" / "tracking" / "loops" / f"{name}.md"
    path.write_text(
        "---\n"
        "type: open-loop\n"
        f'description: "{description}"\n'
        f"owner: [{owners}]             # bundle-absolute entity links of who owns it\n"
        f"status: {status}          # open | done | dropped\n"
        f"entities: [{ents}]          # other entities this loop concerns\n"
        "sources: []           # source(s) where it was raised\n"
        f"{dates}"
        "closed:               # date it was completed/dropped (set by maintain)\n"
        "closed_by:            # bundle-absolute source link that evidenced closure\n"
        "tags: []\n"
        "timestamp: 2026-01-01\n"
        "---\n"
        f"\n{body}{signal_block}\n",
        encoding="utf-8",
    )
    return path


def write_fact(bundle, name, description="a claim", entities=(), occurred="2026-01-01",
               sources=(), status="active"):
    ents = ", ".join(entity_link(e) for e in entities)
    srcs = ", ".join(sources)
    path = bundle / "knowledge" / "facts" / f"{name}.md"
    path.write_text(
        "---\n"
        "type: fact\n"
        f'description: "{description}"\n'
        f"entities: [{ents}]          # bundle-absolute links, e.g. [/entities/person/foo.md]\n"
        f"sources: [{srcs}]           # bundle-absolute links\n"
        "confidence: medium    # low | medium | high\n"
        f"status: {status}        # active | deprecated | superseded\n"
        "tags: []\n"
        f"created: {occurred}\nupdated: {occurred}\noccurred: {occurred}"
        "     # when the content actually happened\n"
        "---\n\nBody.\n",
        encoding="utf-8",
    )
    return path


def write_source(bundle, name, ingested="2026-01-01"):
    path = bundle / "knowledge" / "sources" / f"{name}.md"
    path.write_text(
        "---\n"
        "type: source\n"
        'description: "a source"\n'
        'resource: "https://example.test/x"\n'
        "source-kind: conversation  # article | conversation | document\n"
        'channel: "meeting"\n'
        f"occurred: {ingested}\ningested: {ingested}\n"
        f"created: {ingested}\nupdated: {ingested}\n"
        "---\n\nSummary.\n",
        encoding="utf-8",
    )
    return f"/sources/{name}.md"


def write_sweep(bundle, examined, raw=None):
    """`state/closure-sweep.json` as the routine writes it: loop link ->
    {"examined": iso}. `raw` writes the file verbatim instead, for the shapes a
    hand-repair produces."""
    path = bundle / "state" / "closure-sweep.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return path
    path.write_text(
        json.dumps({
            "schema": 1,
            "generated": "2026-09-01T09:00:00-03:00",
            "loops": {k: {"examined": v, "outcome": "open"} for k, v in examined.items()},
        }, indent=2),
        encoding="utf-8",
    )
    return path


def run(bundle, args=()):
    return subprocess.run(
        [sys.executable, str(bundle / "scripts" / "close-loops.py")] + [str(a) for a in args],
        cwd=str(bundle), capture_output=True, text=True, encoding="utf-8",
    )


def proposal(bundle, args=()):
    """The run's JSON payload, or None with the failure reported by the caller."""
    result = run(bundle, list(args) + ["--json"])
    if result.returncode != 0:
        return None, result
    try:
        return json.loads(result.stdout), result
    except json.JSONDecodeError:
        return None, result


def queued_paths(payload):
    return [lp["path"] for lp in payload["loops"]]


# --- (a) the queue --------------------------------------------------------


def test_queue_order_and_bound(root):
    """H2/E9: band 2 is oldest last activity first, and the run stops at the cap."""
    bundle = make_bundle(root, "queue")
    # 30 open loops, activity dates spread over 30 days. Written newest-first so
    # a queue that merely preserved directory order would fail.
    for i in range(30):
        write_loop(bundle, f"loop-{i:02d}", opened=f"2026-03-{30 - i:02d}",
                   entities=("acme",))
    write_loop(bundle, "already-done", status="done", opened="2026-01-01")
    write_loop(bundle, "already-expired", status="expired", opened="2026-01-01")

    payload, result = proposal(bundle)
    if payload is None:
        record("close-loops.py --json runs over a 32-loop bundle", False,
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    record("close-loops.py --json runs over a 32-loop bundle", True)
    record("only `status: open` loops are counted — done and expired never queue, "
           "and the comment on `status: open  # open | done | dropped` did not "
           "hide the other 30",
           payload["counts"]["open"] == 30, json.dumps(payload["counts"]))
    record("the run stops at close_loops_max (default 25), the excess waits",
           payload["counts"]["queued"] == 25 and len(payload["loops"]) == 25,
           json.dumps(payload["counts"]))

    paths = queued_paths(payload)
    activities = [lp["last_activity"] for lp in payload["loops"]]
    record("band 2 is ordered oldest last activity first, which is what puts the "
           "stale end of the lane at the front of the queue",
           activities == sorted(activities), activities)
    record("…so the oldest loop is first and the five newest are the ones left "
           "waiting",
           paths[0] == "/tracking/loops/loop-29.md"
           and "/tracking/loops/loop-00.md" not in paths,
           paths)

    capped, _ = proposal(bundle, ["--max", "3"])
    record("--max overrides the cap for one run",
           capped["counts"]["queued"] == 3
           and queued_paths(capped) == paths[:3],
           queued_paths(capped))

    (bundle / "elephant.json").write_text(
        json.dumps({"owner": {"slug": OWNER}, "close_loops": {"max": 4}}),
        encoding="utf-8")
    configured, _ = proposal(bundle)
    record("elephant.json's close_loops.max is read, and a bundle without the key "
           "keeps the 25 above",
           configured["counts"]["queued"] == 4, json.dumps(configured["counts"]))


def test_undated_loop_sorts_last(root):
    """A loop whose file carries no parseable date is not evidence of age."""
    bundle = make_bundle(root, "undated")
    write_loop(bundle, "old", opened="2026-01-01")
    write_loop(bundle, "recent", opened="2026-08-01")
    write_loop(bundle, "undated", opened=None, created=None, updated=None)

    payload, result = proposal(bundle)
    if payload is None:
        record("a dateless loop does not crash the queue", False,
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    record("a dateless loop is still examinable — it is queued, not skipped",
           len(payload["loops"]) == 3, queued_paths(payload))
    record("…and sorts last rather than claiming the front of the stale end",
           queued_paths(payload) == ["/tracking/loops/old.md",
                                     "/tracking/loops/recent.md",
                                     "/tracking/loops/undated.md"],
           queued_paths(payload))


def test_bands(root):
    """E10: new material on a loop's entities returns it to band 1; a loop
    examined after its own last activity with nothing new is settled and waits."""
    bundle = make_bundle(root, "bands")
    # Examined, entity gained a fact afterwards → band 1, even though it is the
    # newest loop in the bundle.
    write_loop(bundle, "revisit", opened="2026-08-01", entities=("acme",))
    # Examined after its last activity, nothing new since → settled, not queued.
    write_loop(bundle, "settled", opened="2026-01-01", entities=("nobody",))
    # Examined, and a fact filed the SAME day as the examination → not new
    # material: that is what the examination read.
    write_loop(bundle, "sameday", opened="2026-01-02", entities=("beta",))
    # Never examined → band 2.
    write_loop(bundle, "fresh", opened="2026-02-01", entities=("acme",))

    write_fact(bundle, "new-acme", description="acme shipped the export",
               entities=("acme",), occurred="2026-08-20")
    write_fact(bundle, "sameday-beta", description="beta said something",
               entities=("beta",), occurred="2026-08-10")
    write_sweep(bundle, {
        "/tracking/loops/revisit.md": "2026-08-10",
        "/tracking/loops/settled.md": "2026-08-10",
        "/tracking/loops/sameday.md": "2026-08-10",
    })

    payload, result = proposal(bundle)
    if payload is None:
        record("close-loops.py reads state/closure-sweep.json", False,
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    paths = queued_paths(payload)
    bands = {lp["path"]: lp["band"] for lp in payload["loops"]}
    record("a fact on an examined loop's entity returns that loop to band 1",
           bands.get("/tracking/loops/revisit.md") == 1, json.dumps(bands))
    record("…and band 1 is served before band 2, however new the loop is",
           paths and paths[0] == "/tracking/loops/revisit.md", paths)
    record("a loop examined after its own last activity, with nothing new since, "
           "is settled — it waits for material instead of being re-read every run",
           "/tracking/loops/settled.md" not in paths, paths)
    record("a fact filed the same day as the examination is not new material — "
           "otherwise the loop returns to band 1 forever",
           "/tracking/loops/sameday.md" not in paths, paths)
    record("a never-examined loop is in band 2",
           bands.get("/tracking/loops/fresh.md") == 2, json.dumps(bands))
    record("the band-1 reason names the entity and the date, so the routine can "
           "see why the loop came back",
           "acme gained material on 2026-08-20"
           in payload["loops"][0]["reason"], payload["loops"][0]["reason"])

    # A source ingested later than its fact counts too: a source reaches an
    # entity only through the facts that cite it.
    b2 = make_bundle(root, "bands-source")
    write_loop(b2, "revisit", opened="2026-01-01", entities=("acme",))
    src = write_source(b2, "2026-08-25-late", ingested="2026-08-25")
    write_fact(b2, "old-fact", description="an old claim about acme",
               entities=("acme",), occurred="2026-01-05", sources=(src,))
    write_sweep(b2, {"/tracking/loops/revisit.md": "2026-08-20"})
    payload2, _ = proposal(b2)
    record("a source ingested after the examination counts as new material, "
           "through the fact that cites it",
           payload2["loops"] and payload2["loops"][0]["band"] == 1,
           json.dumps(payload2["loops"][0] if payload2["loops"] else {}))


def test_settled_boundary_is_on_or_after(root):
    """`examined == last_activity` is settled: on or after, not strictly after.

    The deciding case of the rule, and nothing exercised it on this side.
    Mutating `>` to `>=` in build_queue()'s settling test left all 97 checks
    green while the run went from `0 loop(s) queued of 1 open` to `1 loop(s)
    queued` with a reason that contradicts itself, `active since it was examined
    (2026-01-05 > 2026-01-05)`. tests/test_decay.py pins the same day at the
    other end of the pair, where the same mutation is already red.
    """
    bundle = make_bundle(root, "settled-boundary")
    write_loop(bundle, "same-day", description="Examined the day it last moved",
               opened="2026-01-05", created="2026-01-05", updated="2026-01-05",
               entities=("acme",))
    write_sweep(bundle, {"/tracking/loops/same-day.md": "2026-01-05"})

    payload, result = proposal(bundle)
    if payload is None:
        record("close-loops.py runs over a loop examined on its own activity date",
               False, f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    record("a loop examined on the very day of its last activity is settled: on "
           "or after, not strictly after, which is the boundary decay's gate "
           "implements too",
           queued_paths(payload) == [] and payload["counts"]["band2"] == 0,
           f"{queued_paths(payload)}\n{json.dumps(payload['counts'])}")
    text = run(bundle).stdout
    record("…and the header says so rather than queueing it with a reason that "
           "reads `2026-01-05 > 2026-01-05`",
           "0 loop(s) queued of 1 open" in text, text[:400])


def test_unreadable_examination_date(root):
    """A future or malformed examination date reads as never examined.

    `DATE.search` alone finds ten digits in the right shape and nothing more, so
    `examined: "2099-01-01"` used to read as an examination here while
    `decay-loops.py`'s examination_date() refused it and parked the loop as
    never examined. That disagreement is a deadlock: decay waits forever for an
    examination this queue will never propose, because it already calls the loop
    settled. The same deadlock the previous round fixed, reached through a
    different input, so the two readers have to validate the same way.
    """
    bundle = make_bundle(root, "bad-examination")
    write_loop(bundle, "future", description="Examined in 2099",
               opened="2026-01-01", entities=("acme",))
    write_loop(bundle, "nonsense", description="Examined on the 99th",
               opened="2026-01-02", entities=("acme",))
    write_sweep(bundle, {"/tracking/loops/future.md": "2099-01-01",
                         "/tracking/loops/nonsense.md": "2026-99-99"})

    payload, result = proposal(bundle)
    if payload is None:
        record("close-loops.py runs over a sweep carrying unreadable dates", False,
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    by_path = {lp["path"]: lp for lp in payload["loops"]}
    record("an examination dated in the future is refused, exactly as "
           "decay-loops.py's examination_date() refuses it: the loop reads as "
           "never examined and is queued instead of being dropped as settled",
           by_path.get("/tracking/loops/future.md", {}).get("examined") is None
           and by_path.get("/tracking/loops/future.md", {}).get("reason")
           == "never examined",
           json.dumps([{"path": p, "examined": lp["examined"],
                        "reason": lp["reason"]} for p, lp in by_path.items()],
                      indent=2))
    record("…and so is ten digits in the right shape that are not a date",
           by_path.get("/tracking/loops/nonsense.md", {}).get("examined") is None
           and by_path.get("/tracking/loops/nonsense.md", {}).get("reason")
           == "never examined",
           json.dumps(sorted(by_path)))

    # The other half of the mirror: the shape tolerances survive. The date is
    # validated on the **matched group** and not on the whole value, because
    # `datetime.date.fromisoformat()` over the whole thing rejects the
    # `2026-09-01T09:00:00-03:00` shape `load_sweep()` documents and tolerates on
    # purpose, and a loop the routine did examine would then read as never
    # examined and be queued forever. tests/test_decay.py [109] pins the same
    # shape at the other end of the pair; validating the whole value survives
    # every suite without this check.
    iso = make_bundle(root, "iso-datetime-examination")
    write_loop(iso, "examined", description="Examined at 09:00, not at midnight",
               opened="2026-01-01", entities=("acme",))
    write_sweep(iso, {"/tracking/loops/examined.md": "2026-01-05T09:00:00-03:00"})
    payload_iso, result_iso = proposal(iso)
    record("an ISO datetime is still read as its date — validating the whole "
           "value would have rejected the shape load_sweep() tolerates on "
           "purpose, and the loop the routine examined would come back as never "
           "examined",
           payload_iso is not None and queued_paths(payload_iso) == []
           and payload_iso["counts"]["band2"] == 0,
           f"exit={result_iso.returncode}\n{result_iso.stdout}\n{result_iso.stderr}")

    # And the third shape of the same mirror: a date sitting inside prose. A
    # human writing a refusal into the sweep record leaves a readable past date
    # in it, and finding ten digits anywhere in the value read that as an
    # examination. decay-loops.py anchors the match at position 0 and allows
    # only a time of day after it, so it parks both of these; this reader has to
    # park them too, or the two disagree again and the loop deadlocks: decay
    # waits for an examination this queue already counted.
    prose = make_bundle(root, "prose-examination")
    write_loop(prose, "refused", description="A refusal written into the record",
               opened="2026-01-01", entities=("acme",))
    write_loop(prose, "twodates", description="Two dates in one value",
               opened="2026-01-02", entities=("acme",))
    write_sweep(prose, {
        "/tracking/loops/refused.md": "could not decide on 2026-01-05",
        "/tracking/loops/twodates.md": "2026-01-05 then 2025-07-30",
    })
    payload_prose, result_prose = proposal(prose)
    if payload_prose is None:
        record("close-loops.py runs over a sweep carrying dates buried in prose",
               False,
               f"exit={result_prose.returncode}\n{result_prose.stdout}"
               f"\n{result_prose.stderr}")
    else:
        by_prose = {lp["path"]: lp for lp in payload_prose["loops"]}
        record("a past date written inside a sentence is not an examination "
               "here either, so the loop is queued as never examined instead of "
               "being dropped as settled on a record nobody wrote",
               by_prose.get("/tracking/loops/refused.md", {}).get("examined")
               is None
               and by_prose.get("/tracking/loops/refused.md", {}).get("reason")
               == "never examined",
               json.dumps([{"path": p, "examined": lp["examined"],
                            "reason": lp["reason"]}
                           for p, lp in by_prose.items()], indent=2))
        record("…and two dates in one value do not let the first win silently",
               by_prose.get("/tracking/loops/twodates.md", {}).get("examined")
               is None
               and by_prose.get("/tracking/loops/twodates.md", {}).get("reason")
               == "never examined",
               json.dumps(sorted(by_prose)))


def test_band_two_quota_at_every_reachable_cap(root):
    """The reserved fifth has to exist at the caps a bundle can actually ask for.

    `cap - cap // 5` is the whole cap for every cap below 5, so band 2 received
    0 slots at 1, 2, 3 and 4 and exactly 1 at 5, and nothing said so: the
    reservation read as present at the default and was absent everywhere else.
    Those caps are reachable, not theoretical. `close_loops_max()` accepts any
    int above 0 from `elephant.json` and `--max 3` is a legal run size.

    Measured with both bands overflowing, so no split here is a shortfall being
    handed back. At a cap of 1 band 1 keeps absolute priority: a single slot
    cannot serve both bands, and band 1 is the priority lane.
    """
    bundle = make_bundle(root, "quota")
    for i in range(30):
        write_loop(bundle, f"revisit-{i:02d}", opened="2026-05-01",
                   entities=("acme",))
    for i in range(40):
        write_loop(bundle, f"cold-{i:02d}", opened=f"2026-01-{i % 28 + 1:02d}",
                   entities=("nobody",))
    write_fact(bundle, "new-acme", entities=("acme",), occurred="2026-08-20")
    write_sweep(bundle, {f"/tracking/loops/revisit-{i:02d}.md": "2026-08-01"
                         for i in range(30)})

    for cap, want1, want2 in ((1, 1, 0), (2, 1, 1), (3, 2, 1), (4, 3, 1),
                              (25, 20, 5)):
        payload, result = proposal(bundle, ["--max", cap])
        if payload is None:
            record(f"--max {cap} runs over a bundle with 30 in band 1 and 40 in "
                   "band 2", False,
                   f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
            continue
        paths = queued_paths(payload)
        got1 = len([p for p in paths if p.startswith("/tracking/loops/revisit-")])
        got2 = len([p for p in paths if p.startswith("/tracking/loops/cold-")])
        record(f"at --max {cap} the run splits {want1} band 1 / {want2} band 2, "
               "so the cold end advances at every cap and not only at the default",
               len(paths) == cap and (got1, got2) == (want1, want2),
               f"queued {len(paths)}: {got1} band 1, {got2} band 2\n{paths}")


def test_band_one_does_not_starve_band_two(root):
    """E9: band 1 is served first but takes at most four fifths of the run.

    Absolute precedence is what it looked like at first, and it starves the
    cold end for as long as band 1 keeps overflowing — measured on the owner's
    bundle, 0 of 40 never-examined loops were reached over 30 simulated runs,
    while band 2 is precisely where the loops `decay` is waiting on live.
    """
    bundle = make_bundle(root, "band1-overflow")
    for i in range(10):
        write_loop(bundle, f"revisit-{i}", opened="2026-05-01", entities=("acme",))
    write_loop(bundle, "ancient", opened="2020-01-01", entities=("nobody",))
    write_loop(bundle, "old", opened="2021-01-01", entities=("nobody",))
    write_fact(bundle, "new-acme", entities=("acme",), occurred="2026-08-20")
    write_sweep(bundle, {f"/tracking/loops/revisit-{i}.md": "2026-08-01"
                         for i in range(10)})

    payload, _ = proposal(bundle, ["--max", "5"])
    paths = queued_paths(payload)
    band1 = [p for p in paths if p.startswith("/tracking/loops/revisit-")]
    record("band 1 is served first and takes the bulk of the run",
           len(paths) == 5 and paths[:4] == band1 and len(band1) == 4, paths)
    record("…but a fifth of the run is reserved for band 2, so the cold end of "
           "the lane advances even while band 1 overflows every time",
           paths[4:] == ["/tracking/loops/ancient.md"], paths)
    record("…and the counts still report the whole of both bands, not just what fit",
           payload["counts"]["band1"] == 10 and payload["counts"]["band2"] == 2,
           json.dumps(payload["counts"]))

    # The reservation is not a hole: with no band 2 to fill it, band 1 takes the
    # whole run rather than the run coming up short.
    solo = make_bundle(root, "band1-only")
    for i in range(10):
        write_loop(solo, f"revisit-{i}", opened="2026-05-01", entities=("acme",))
    write_fact(solo, "new-acme", entities=("acme",), occurred="2026-08-20")
    write_sweep(solo, {f"/tracking/loops/revisit-{i}.md": "2026-08-01"
                       for i in range(10)})
    payload2, _ = proposal(solo, ["--max", "5"])
    record("with band 2 empty the reserved slots go back to band 1 — the run is "
           "never short of its cap",
           payload2["counts"]["queued"] == 5 and payload2["counts"]["band2"] == 0,
           json.dumps(payload2["counts"]))


# --- (b) the evidence -----------------------------------------------------


def test_evidence_ranking(root):
    """H3: an additive score — 2 per shared non-owner entity, 1 per shared
    content word — then recency, then path. Capped at 10."""
    bundle = make_bundle(root, "ranking")
    write_loop(bundle, "export", description="Ship the export pipeline fix to Acme",
               entities=("acme", "angelo"),
               signal="a source showing the export pipeline released to Acme")

    # 2 entities, no wording → 4. The newest fact in the bundle, so recency
    # cannot be what puts the criterion match ahead of it.
    write_fact(bundle, "two-shared", description="unrelated wording entirely",
               entities=("acme", "angelo"), occurred="2026-09-01")
    # 1 entity + {export, pipeline, acme} → 5. The oldest, and still first.
    write_fact(bundle, "one-shared-overlap",
               description="the export pipeline shipped to Acme",
               entities=("acme",), occurred="2026-01-01")
    write_fact(bundle, "one-shared-recent", description="unrelated wording entirely",
               entities=("acme",), occurred="2026-09-01")
    write_fact(bundle, "owner-noise", description="unrelated wording entirely",
               entities=(OWNER,), occurred="2026-09-02")
    write_fact(bundle, "owner-overlap", description="the export pipeline was discussed",
               entities=(OWNER,), occurred="2026-01-01")
    write_fact(bundle, "elsewhere", description="the export pipeline shipped",
               entities=("other",), occurred="2026-09-03")

    payload, result = proposal(bundle)
    if payload is None:
        record("close-loops.py proposes evidence", False,
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    loop = payload["loops"][0]
    order = [c["path"] for c in loop["evidence"]]
    scored = {c["path"]: c["score"] for c in loop["evidence"]}
    record("the score is additive — 2 a shared non-owner entity plus 1 a shared "
           "content word — and every candidate carries it",
           all(c["score"] == 2 * len(c["shared_entities"]) + len(c["overlap"])
               for c in loop["evidence"]) and len(scored) == len(order),
           json.dumps(scored, indent=2))
    record("the fact that quotes the criterion back outranks the fact sharing "
           "two entities and not one word, though it is the older of the two — "
           "nesting the two counts made the entity count absolute",
           order and order[0] == "/facts/one-shared-overlap.md"
           and scored["/facts/one-shared-overlap.md"] == 5
           and scored["/facts/two-shared.md"] == 4,
           json.dumps(scored, indent=2))
    record("…and a shared entity is still worth more than a single word: two "
           "entities and no wording beat one entity and no wording",
           order[1:3] == ["/facts/two-shared.md",
                          "/facts/one-shared-recent.md"], order)
    record("a fact sharing only the owner and no content word is dropped, not "
           "padded in — the owner is on nearly every fact, so it ranks nothing",
           "/facts/owner-noise.md" not in order, order)
    record("…while sharing only the owner but overlapping the criterion's words "
           "is still evidence",
           "/facts/owner-overlap.md" in order, order)
    record("a fact on an entity the loop does not name is not a candidate at all, "
           "however well it reads",
           "/facts/elsewhere.md" not in order, order)
    record("the ranking counts the closure signal's words too, not the "
           "description's alone",
           any("released" in c["overlap"] or "export" in c["overlap"]
               for c in loop["evidence"]),
           json.dumps([c["overlap"] for c in loop["evidence"]]))
    record("each candidate carries the sources that would become `closed_by`",
           all("sources" in c for c in loop["evidence"]),
           json.dumps(loop["evidence"][:1]))


def test_evidence_score_composes_not_nests(root):
    """The blocker, pinned by composition rather than by direction.

    Reversing a comparator is caught by test_evidence_ranking. *Nesting* the
    two counts instead of adding them is not: it preserves every pairwise order
    those checks assert, and only shows itself where the ranges diverge. A loop
    names one to three entities and carries fifteen-odd content words, so a
    nested key lets the entity count decide absolutely. Here one fact quotes the
    closure criterion back and shares a single entity; twelve share all three of
    the loop's entities and not one word. Nested, all twelve outrank it and the
    cap of 10 cuts the only useful candidate out of the proposal entirely.
    """
    bundle = make_bundle(root, "additive")
    write_loop(
        bundle, "migration",
        description="Ship the export pipeline migration fix to Acme before the "
                    "audit deadline",
        entities=("acme", "angelo", "beta"),
        signal="a source showing the export pipeline migration released to Acme "
               "customers after the audit",
        opened="2026-01-01",
    )
    write_fact(bundle, "the-match",
               description="the export pipeline migration released to Acme "
                           "customers, closing the audit deadline fix",
               entities=("acme",), occurred="2026-01-02")
    for i in range(12):
        write_fact(bundle, f"decoy-{i:02d}", description="unrelated wording entirely",
                   entities=("acme", "angelo", "beta"), occurred=f"2026-09-{i + 1:02d}")

    payload, result = proposal(bundle)
    if payload is None:
        record("close-loops.py ranks a 13-candidate pool", False,
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    loop = payload["loops"][0]
    order = [c["path"] for c in loop["evidence"]]
    by_path = {c["path"]: c for c in loop["evidence"]}
    record("all 13 candidates are pooled and the proposal is capped at 10",
           loop["candidates_total"] == 13 and len(order) == 10, order)
    record("the one fact that satisfies the closure criterion is in the "
           "proposal at all — three shared entities do not get to be absolute, "
           "which is the whole reason the criterion is read",
           "/facts/the-match.md" in order, order)
    record("…and it is first: 1 entity + 10 words scores 12, three entities and "
           "no wording score 6",
           order and order[0] == "/facts/the-match.md"
           and by_path["/facts/the-match.md"]["score"]
           > max(c["score"] for p, c in by_path.items() if p != "/facts/the-match.md"),
           json.dumps({p: c["score"] for p, c in by_path.items()}, indent=2))
    record("the decoys still rank above nothing — a shared entity is evidence, "
           "it is just not a veto",
           all(by_path[p]["score"] == 6 for p in order if p != "/facts/the-match.md"),
           json.dumps({p: c["score"] for p, c in by_path.items()}, indent=2))


def test_evidence_cap(root):
    """H3: capped at 10 per loop, with the total still reported."""
    bundle = make_bundle(root, "cap")
    write_loop(bundle, "wide", description="Ship the export pipeline fix",
               entities=("acme",), signal="a source showing the export shipped")
    for i in range(14):
        write_fact(bundle, f"f{i:02d}", description="the export pipeline shipped",
                   entities=("acme",), occurred=f"2026-0{1 + i % 9}-01")

    payload, _ = proposal(bundle)
    loop = payload["loops"][0]
    record("the evidence is capped at 10 candidates per loop",
           len(loop["evidence"]) == 10, len(loop["evidence"]))
    record("…and the proposal still says how many there were, so the routine "
           "knows it is reading a top slice",
           loop["candidates_total"] == 14, loop["candidates_total"])
    text = run(bundle).stdout
    record("the text rendering says both numbers",
           "10 of 14 candidate(s), ranked, capped at 10" in text, text[:600])


# --- (c) the degenerate readings ------------------------------------------


def test_no_evidence(root):
    """E11: examined, recorded, left open, and nothing written."""
    bundle = make_bundle(root, "no-evidence")
    loop = write_loop(bundle, "lonely", description="Call the plumber",
                      entities=("plumber",), signal="a source showing the call happened")
    write_fact(bundle, "unrelated", description="something else entirely",
               entities=("other",), occurred="2026-05-01")
    before = loop.read_text(encoding="utf-8")

    payload, _ = proposal(bundle)
    record("a loop with no candidate is still queued and examined, not skipped",
           len(payload["loops"]) == 1 and payload["loops"][0]["evidence"] == []
           and payload["loops"][0]["candidates_total"] == 0,
           json.dumps(payload["loops"]))
    text = run(bundle).stdout
    record("…and the proposal says so in words rather than printing an empty list",
           "evidence: none" in text and "leave it open" in text, text)
    record("nothing was written: the loop file is byte-identical",
           loop.read_text(encoding="utf-8") == before)
    record("…and no state/closure-sweep.json was created — the routine records "
           "the examination, this script proposes",
           not (bundle / "state" / "closure-sweep.json").exists())


def test_criterion_fallback(root):
    """E12: no `**Closure signal:**` section — the description is the criterion,
    and the proposal says where it came from."""
    bundle = make_bundle(root, "criterion")
    write_loop(bundle, "with-signal", description="Ship the thing",
               signal="a release note naming the thing", opened="2026-01-01")
    write_loop(bundle, "no-signal", description="Ship the other thing",
               signal=None, opened="2026-01-02")

    payload, _ = proposal(bundle)
    by_path = {lp["path"]: lp for lp in payload["loops"]}
    signalled = by_path["/tracking/loops/with-signal.md"]
    bare = by_path["/tracking/loops/no-signal.md"]
    record("the closure criterion is read out of the `**Closure signal:**` "
           "section the template ships — the field no code had ever opened",
           signalled["criterion"] == "a release note naming the thing"
           and signalled["criterion_source"] == "closure-signal",
           json.dumps(signalled["criterion"]))
    record("a loop without the section falls back to its description",
           bare["criterion"] == "Ship the other thing"
           and bare["criterion_source"] == "description",
           json.dumps(bare["criterion"]))
    text = run(bundle).stdout
    record("…and the proposal names the fallback, so the routine judges against "
           "a criterion whose provenance it can see",
           "carries no\n**Closure signal:** section" in text
           or "carries no **Closure signal:** section" in text,
           text)

    # A second bolded lead-in after the signal must not be swallowed into it.
    b2 = make_bundle(root, "criterion-multi")
    write_loop(b2, "multi", description="Ship it", signal="a source showing it shipped",
               body="Details.\n\n**Context:** background that is not the criterion.")
    payload2, _ = proposal(b2)
    record("the criterion stops at the paragraph the section owns",
           payload2["loops"][0]["criterion"] == "a source showing it shipped",
           json.dumps(payload2["loops"][0]["criterion"]))

    # An EMPTY heading is the reverse mistake and the worse one: the reader ran
    # past the blank line and returned the NEXT section, labelled as the closure
    # criterion. Nothing downstream can tell a criterion from a background note,
    # so the routine judges delivery against the wrong sentence and says nothing.
    b3 = make_bundle(root, "criterion-empty")
    write_loop(b3, "empty", description="Ship the thing", signal=None,
               body="Details.\n\n**Closure signal:**\n\n"
                    "**Context:** background that is not the criterion.")
    write_loop(b3, "empty-eof", description="Ship the other thing", signal=None,
               body="Details.\n\n**Closure signal:**")
    payload3, _ = proposal(b3)
    empty = {lp["path"]: lp for lp in payload3["loops"]}
    record("an empty `**Closure signal:**` heading does not swallow the section "
           "after it — the loop falls back to its description, and says so",
           all(empty[p]["criterion_source"] == "description"
               for p in ("/tracking/loops/empty.md",
                         "/tracking/loops/empty-eof.md"))
           and empty["/tracking/loops/empty.md"]["criterion"] == "Ship the thing",
           json.dumps({p: (lp["criterion"], lp["criterion_source"])
                       for p, lp in empty.items()}, indent=2))

    # 2025 loop bodies were written by hand and nothing has ever checked the
    # capital C.
    b4 = make_bundle(root, "criterion-case")
    write_loop(b4, "lower", description="Ship it", signal=None,
               body="Details.\n\n**closure signal:** a release note naming it")
    payload4, _ = proposal(b4)
    record("the heading is matched case-insensitively — a hand-typed `**closure "
           "signal:**` is the same section",
           payload4["loops"][0]["criterion"] == "a release note naming it"
           and payload4["loops"][0]["criterion_source"] == "closure-signal",
           json.dumps(payload4["loops"][0]["criterion"]))


def test_closure_signal_shapes(root):
    """Every Markdown shape the section is written in, pinned in both directions.

    Nothing here was covered, and 97 checks stayed green under two different
    separators between the bolded lead-in and its criterion. That is how a
    regression shipped: a separator crossing at most one newline misses the
    criterion written in the paragraph *below* the lead-in, after a blank line,
    which is the most idiomatic of the three shapes. The loop then falls back to
    its `description` while the proposal states it carries no `**Closure
    signal:**` section at all, and because `terms` is built from the description
    plus the criterion, the words that identify the right fact go with it.

    The two guards that make `\\s*` safe get a fixture each, so removing either
    one turns this suite red on its own.
    """
    bundle = make_bundle(root, "signal-shapes")
    crit = "a release note naming the export"
    parsed_shapes = {
        # (a) on the same line as the lead-in
        "same-line": f"Details.\n\n**Closure signal:** {crit}",
        # (b) on the line directly below it, no blank line
        "next-line": f"Details.\n\n**Closure signal:**\n{crit}",
        # (c) in the paragraph below it, after a blank line: the regressed shape
        "paragraph-below": f"Details.\n\n**Closure signal:**\n\n{crit}",
        # (f) hand-typed capitals: 2025 loop bodies were written by hand
        "mixed-case": f"Details.\n\n**closure Signal:** {crit}",
    }
    fallback_shapes = {
        # (d) the next non-blank line is another section
        "next-section": "Details.\n\n**Closure signal:**\n\n"
                        "**Context:** background that is not the criterion.",
        # (e) an empty section at end of file
        "empty-eof": "Details.\n\n**Closure signal:**",
        # the guard's own fixture: an empty section with the next section
        # butted straight against it, no blank line between them
        "guard-adjacent": "Details.\n\n**Closure signal:**\n"
                          "**Blocked by:** legal review.",
        # the anchor's own fixture: the same, indented, so the guard's
        # lookahead no longer sits on the `**` and only `(\\S` refuses it
        "anchor-indented": "Details.\n\n**Closure signal:**\n\n"
                           "  **Context:** background that is not the criterion.",
        # One fixture per remaining block shape the lookahead refuses. All four
        # fell through it while the bolded-lead-in guard was the only one, and
        # came back as the closure criterion: the heading was printed as the
        # criterion's provenance and its words entered `terms`, which lifted a
        # noise fact's score. Only hand-written bodies reach this, since the
        # shipped template writes the criterion inline, and that is the same
        # population `re.IGNORECASE` exists for.
        "heading-below": "Details.\n\n**Closure signal:**\n\n"
                         "## Context that is not the criterion\n\nBackground.",
        "bullet-below": "Details.\n\n**Closure signal:**\n\n"
                        "- background that is not the criterion",
        "bold-no-colon": "Details.\n\n**Closure signal:**\n\n"
                         "**Background** that is not the criterion.",
        "fence-below": "Details.\n\n**Closure signal:**\n\n"
                       "```\nbackground that is not the criterion\n```",
    }
    for name, body in {**parsed_shapes, **fallback_shapes}.items():
        write_loop(bundle, name, description=f"Ship {name}", signal=None,
                   body=body, opened="2026-01-01")

    payload, result = proposal(bundle)
    if payload is None:
        record("close-loops.py reads a bundle of hand-written closure signals",
               False, f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    got = {lp["path"].rsplit("/", 1)[-1][:-3]: lp for lp in payload["loops"]}

    for name in parsed_shapes:
        lp = got.get(name, {})
        record(f"the criterion is read when it is written {name.replace('-', ' ')}",
               lp.get("criterion") == crit
               and lp.get("criterion_source") == "closure-signal",
               json.dumps({"criterion": lp.get("criterion"),
                           "source": lp.get("criterion_source")}))
    for name in fallback_shapes:
        lp = got.get(name, {})
        record(f"an empty section written {name.replace('-', ' ')} falls back to "
               "the description rather than returning the section after it",
               lp.get("criterion") == f"Ship {name}"
               and lp.get("criterion_source") == "description",
               json.dumps({"criterion": lp.get("criterion"),
                           "source": lp.get("criterion_source")}))
    record("in particular a `**Blocked by:**` line butted against the lead-in is "
           "never returned as the closure criterion, which is what the "
           "negative lookahead refuses",
           "legal review" not in (got.get("guard-adjacent", {}).get("criterion")
                                  or ""),
           json.dumps(got.get("guard-adjacent", {}).get("criterion")))
    record("no other block shape is returned as the criterion either: not a "
           "heading, not a list item, not a bolded run without a colon, and not "
           "a fenced block. Each is refused by its own alternative of the same "
           "lookahead, so dropping any one of them turns this check and that "
           "shape's own red, and leaves the other three shapes green",
           all("not the criterion"
               not in (got.get(name, {}).get("criterion") or "")
               for name in ("heading-below", "bullet-below", "bold-no-colon",
                            "fence-below")),
           json.dumps({name: got.get(name, {}).get("criterion")
                       for name in ("heading-below", "bullet-below",
                                    "bold-no-colon", "fence-below")}, indent=2))

    # The other half of the regression: the criterion's words are what identify
    # the right fact. Read from the paragraph below the lead-in, the fact that
    # satisfies the criterion outranks a newer fact sharing the same entity and
    # not one word; lost to the fallback, both score 2 and recency picks the
    # wrong one.
    b2 = make_bundle(root, "signal-shapes-ranking")
    write_loop(b2, "export", description="Ship it", entities=("acme",),
               signal=None, opened="2026-01-01",
               body="Details.\n\n**Closure signal:**\n\n"
                    "a release note showing the export pipeline reached Acme")
    write_fact(b2, "the-match",
               description="the export pipeline release reached Acme",
               entities=("acme",), occurred="2026-01-02")
    write_fact(b2, "decoy", description="unrelated wording entirely",
               entities=("acme",), occurred="2026-09-01")
    payload2, _ = proposal(b2)
    loop = payload2["loops"][0]
    order = [c["path"] for c in loop["evidence"]]
    record("…and the criterion read out of that paragraph reaches the ranking: "
           "the fact that satisfies it outranks the newer fact that shares the "
           "entity and not one word",
           order and order[0] == "/facts/the-match.md",
           json.dumps({c["path"]: (c["score"], c["overlap"])
                       for c in loop["evidence"]}, indent=2))


# --- (d) degraded inputs --------------------------------------------------


def test_degraded_inputs(root):
    """Control state is disposable; an unattended run must survive its shapes."""
    bundle = make_bundle(root, "degraded")
    write_loop(bundle, "l1", opened="2026-01-01", entities=("acme",))

    write_sweep(bundle, {}, raw="{ not json")
    result = run(bundle, ["--json"])
    ok = result.returncode == 0
    record("a malformed closure-sweep.json does not crash the run", ok,
           f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
    record("…it warns once on stderr and reads every loop as never examined",
           "closure-sweep.json" in result.stderr and "warning" in result.stderr
           and json.loads(result.stdout)["loops"][0]["examined"] is None,
           result.stderr)

    # Without a sweep the loop queues; with the hand-repaired shape it is
    # settled. Both halves are asserted, or "read as a date" would go green on
    # a reader that ignored the file entirely.
    (bundle / "state" / "closure-sweep.json").unlink()
    unswept, _ = proposal(bundle)
    write_sweep(bundle, {}, raw='{"loops": {"/tracking/loops/l1.md": "2026-08-01"}}')
    payload, _ = proposal(bundle)
    record("a bare ISO string in place of the entry dict is read as the "
           "examination date rather than being ignored",
           queued_paths(unswept) == ["/tracking/loops/l1.md"]
           and payload["loops"] == [],
           f"unswept: {queued_paths(unswept)}\nswept: {json.dumps(payload['loops'])}")

    bare = make_bundle(root, "bare")
    shutil.rmtree(bare / "knowledge" / "tracking")
    result = run(bare)
    record("a bundle with no loops directory exits 0 and says so",
           result.returncode == 0 and "0 loop(s) queued" in result.stdout,
           f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")


def test_named_loop_bypasses_the_queue(root):
    """--loop is how the routine re-reads one loop without waiting its turn."""
    bundle = make_bundle(root, "named")
    write_loop(bundle, "a", opened="2026-01-01", entities=("acme",))
    write_loop(bundle, "b", opened="2026-01-02", entities=("acme",))
    write_sweep(bundle, {"/tracking/loops/b.md": "2026-08-01"})

    payload, _ = proposal(bundle, ["--loop", "/tracking/loops/b.md"])
    record("--loop proposes for the named loop even when the queue has settled it",
           queued_paths(payload) == ["/tracking/loops/b.md"], queued_paths(payload))

    # An empty proposal and an exit code of 0 read, to the routine, exactly like
    # a loop with no evidence. It cannot tell that from a typo or from a loop
    # that closed last week, and it would record an examination that never
    # happened — which is what `decay` then acts on.
    write_loop(bundle, "shipped", status="done", opened="2026-01-03")
    missing = run(bundle, ["--loop", "/tracking/loops/nope.md"])
    record("--loop over a path that does not exist warns instead of exiting 0 "
           "in silence",
           missing.returncode == 0 and "warning" in missing.stderr
           and "nope" in missing.stderr, missing.stderr or missing.stdout)
    closed = run(bundle, ["--loop", "/tracking/loops/shipped.md"])
    record("--loop over a loop that is no longer open says so, and names the "
           "status it found",
           closed.returncode == 0 and "warning" in closed.stderr
           and "done" in closed.stderr, closed.stderr or closed.stdout)
    both = run(bundle, ["--loop", "/tracking/loops/nope.md",
                        "--loop", "/tracking/loops/a.md", "--json"])
    record("…and one bad name does not cost the run: the good loop is still "
           "proposed for",
           both.returncode == 0
           and queued_paths(json.loads(both.stdout)) == ["/tracking/loops/a.md"],
           both.stdout[:400] + both.stderr)


def test_max_is_refused_at_the_boundary(root):
    """`--max 0` used to fall through to the configured default and examine 25
    loops — a run that asked for none and got a full one, silently."""
    bundle = make_bundle(root, "max-boundary")
    for i in range(3):
        write_loop(bundle, f"l{i}", opened=f"2026-01-0{i + 1}")

    for bad in ("0", "-5"):
        result = run(bundle, ["--max", bad])
        record(f"--max {bad} is refused by argparse rather than silently "
               "becoming the default",
               result.returncode != 0 and "--max" in result.stderr,
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
    ok, _ = proposal(bundle, ["--max", "1"])
    record("--max 1 is still a legal run size", ok["counts"]["queued"] == 1,
           json.dumps(ok["counts"]))


def test_owner_is_what_the_file_declares(root):
    """The bundle owner is a ranking input, not a fact about the loop.

    Injecting it into `loop["owner"]` made `--json` and the printed proposal
    report a loop declaring `owner: []` as owned by the bundle owner — a claim
    the bundle never recorded, coming out of a script that only reads.
    """
    bundle = make_bundle(root, "owner")
    write_loop(bundle, "unowned", description="Nobody signed up for this",
               owner=(), entities=("acme",))
    write_loop(bundle, "owned", description="Jane signed up for this",
               owner=(OWNER,), entities=("acme",))
    write_fact(bundle, "acme-news", description="acme said something",
               entities=("acme",), occurred="2026-02-01")

    payload, result = proposal(bundle)
    if payload is None:
        record("close-loops.py runs over an unowned loop", False,
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    by_path = {lp["path"]: lp for lp in payload["loops"]}
    record("a loop declaring `owner: []` is still reported as unowned",
           by_path["/tracking/loops/unowned.md"]["owner"] == [],
           json.dumps({p: lp["owner"] for p, lp in by_path.items()}))
    record("…and the declared owner is passed through unchanged",
           by_path["/tracking/loops/owned.md"]["owner"] == [OWNER],
           json.dumps({p: lp["owner"] for p, lp in by_path.items()}))
    text = run(bundle).stdout
    record("the text rendering prints the same thing it emits — an unowned loop "
           "reads `owner: —`",
           "owner: —" in text, text[:800])
    record("the owner is still excluded from the ranking's shared-entity signal, "
           "which is what it was folded in for",
           all(OWNER not in c["shared_entities"]
               for lp in payload["loops"] for c in lp["evidence"]),
           json.dumps([c["shared_entities"] for lp in payload["loops"]
                       for c in lp["evidence"]]))


# --- (h) the routine --------------------------------------------------------


def read_skill(name, directory=SKILL_DIR):
    path = directory / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def sweep_recipe():
    """The python the procedure tells the routine to run, lifted out of it.

    The block is a heredoc inside a fenced ```bash example: everything between
    the line opening `<<'PY'` and the line that closes it. Returned with the
    sample argv pairs the procedure shows, so a drift in either half is visible
    from one place.
    """
    text = read_skill("procedure.md")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("python3 -") and line.rstrip().endswith("<<'PY'"):
            body = []
            for follow in lines[i + 1:]:
                if follow.strip() == "PY":
                    pairs = [tok for tok in line.split()[2:] if tok != "<<'PY'"]
                    return "\n".join(body) + "\n", pairs
                body.append(follow)
            break
    return "", []


def test_skill_shape():
    """The skill ships in the same shape as catch-up and decay."""
    skill = read_skill("SKILL.md")
    procedure = read_skill("procedure.md")
    record("plugin/skills/close-loops/ ships a SKILL.md and a procedure.md",
           bool(skill) and bool(procedure), str(SKILL_DIR))
    record("SKILL.md declares `name: close-loops` and blocks model invocation, "
           "so the routine only ever starts from an explicit call or a schedule",
           "name: close-loops" in skill
           and "disable-model-invocation: true" in skill, skill[:200])
    record("SKILL.md points at procedure.md and at the shared contract",
           "procedure.md" in skill and "_shared/core.md" in skill)
    low = skill.lower()
    record("it is scheduled daily and unattended, with no review gate",
           "daily" in low and "unattended" in low and "review gate" in low, low[:400])


def test_procedure_contract():
    """H4/H5/H6, E13, E14, E23 — what the prose has to commit the routine to."""
    p = read_skill("procedure.md")
    low = p.lower()

    record("H4: the bar is the evidence set judged as a whole, not a criterion "
           "matched literally",
           "as a whole" in low and "not** whether some candidate" in low,
           low[:0])
    record("H4/E13: the closing write is the three frontmatter fields plus the "
           "prose paragraph — status: done, closed, closed_by, **Resolution:**",
           all(tok in p for tok in ("status: done", "closed: <today",
                                    "closed_by:", "**Resolution:**")))
    record("E13: closed_by has to resolve on disk, which is what validate-okf.py "
           "checks and what a hand-written link gets wrong",
           "must resolve on disk" in low and "validate-okf.py" in p)
    record("the resolution is prose in the body and never a frontmatter field — "
           "a sentence of judgment carries `: ` and ` #`",
           "never a frontmatter field" in low)
    record("…and its first sentence stands alone, because that is all "
           "tracking/resolved-loops.md prints of it",
           "first sentence" in low and "resolved-loops.md" in p)

    record("E14: evidence that does not show delivery leaves the loop open, "
           "recorded, and queued for nobody",
           "undecided is" in low and "needs-review" in low
           and "no write at all" in low)
    record("E14: and explicitly does not bump `updated:`, which would hand the "
           "loop immortality from the routine meant to resolve it",
           "updated:" in p and "immortal" in low)

    record("H5: every examined loop is recorded, closed or not",
           "closed or not" in low and "closure-sweep.json" in p)
    record("H5: the outcome vocabulary is the one close-loops.py reads back",
           "=done" in p and "=open" in p)
    record("H5: the sweep write validates every pair before writing anything, "
           "and the prose says what it validates — the recipe below is executed "
           "against exactly these claims",
           "bundle-absolute loop path" in low and "nothing was written" in low
           and "actually recorded" in low)

    # Theme: the boundary of an irreversible operation, stated in prose four
    # times and implemented as on-or-after at both ends. A document that says
    # "after" invites a maintainer to "fix" the code and invert it, with the
    # whole suite still green.
    #
    # `decay`'s two files are flattened in with `close-loops`' because the
    # sentence that matters most is over there: `plugin/skills/decay/
    # procedure.md` states the gate for `--apply`, the irreversible end of the
    # pair, and nothing sensed it. Flipping that one line to "after" left
    # test_decay, this suite and smoke all green, and test_decay.py reads no
    # procedure at all. The count is what catches it: the decay line spells the
    # boundary "examined it on or after", so a flip there reads "examined it
    # after" and slips past the substring test.
    flat = " ".join("\n".join((
        p,
        read_skill("SKILL.md"),
        read_skill("procedure.md", DECAY_SKILL_DIR),
        read_skill("SKILL.md", DECAY_SKILL_DIR),
    )).replace("**", "").lower().split())
    record("the sweep gate's boundary reads `on or after` wherever either skill "
           "of the pair states it, `decay`'s own gate included, which is what "
           "both scripts implement",
           "examined after" not in flat and flat.count("on or after") >= 4,
           flat.count("on or after"))

    record("H6: the run rebuilds, validates, writes one log.md line and makes "
           "one commit",
           all(tok in p for tok in ("scripts/build-index.py",
                                    "scripts/validate-okf.py",
                                    "knowledge/log.md",
                                    "git -C <bundle> add -A"))
           and "one commit for the run" in low)
    record("H6: and never pushes", "never push" in low)
    record("E23: a failed rebuild or validation commits nothing, and the next "
           "run continues because the files are already written",
           "do **not** commit" in low and "already" in low
           and "next run" in low)
    record("the empty run is a stop, not an empty commit",
           "0 loop(s) queued" in p)


def test_sweep_recipe_writes_what_the_script_reads(root):
    """The one executable line of the procedure, executed.

    A recipe that writes a shape `close-loops.py` cannot read would not fail
    anywhere: the routine would report loops examined, `decay` would read an
    empty record, and expiry would park with nothing in any output saying so.
    """
    body, pairs = sweep_recipe()
    if not body:
        record("procedure.md carries the closure-sweep write as a runnable block",
               False, "no `python3 - … <<'PY'` heredoc found in procedure.md")
        return
    record("procedure.md carries the closure-sweep write as a runnable block, "
           "with its sample pairs", bool(body) and len(pairs) == 2, str(pairs))

    bundle = make_bundle(root, "sweep-recipe")
    recipe = bundle / "recipe.py"
    recipe.write_text(body, encoding="utf-8")

    write_loop(bundle, "closed-one", opened="2026-01-01", entities=("acme",))
    write_loop(bundle, "left-open", opened="2026-01-02", entities=("beta",))
    write_loop(bundle, "untouched", opened="2026-01-03", entities=("gamma",))

    def sweep(*args):
        return subprocess.run([sys.executable, str(recipe), *args],
                              cwd=str(bundle), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    first = sweep("/tracking/loops/closed-one.md=done")
    record("the block runs from <bundle> with no state file present and reports "
           "its count",
           first.returncode == 0 and "1 loop(s) recorded" in first.stdout,
           f"exit={first.returncode}\n{first.stdout}\n{first.stderr}")

    second = sweep("/tracking/loops/left-open.md=open")
    data = json.loads((bundle / "state" / "closure-sweep.json").read_text(
        encoding="utf-8"))
    record("a second run merges rather than clobbers — the earlier run's entry "
           "survives, which is the difference between a record and a log of the "
           "last 25 loops",
           second.returncode == 0 and set(data["loops"]) == {
               "/tracking/loops/closed-one.md", "/tracking/loops/left-open.md"},
           json.dumps(data, indent=2))
    record("…in the schema close-loops.py documents: schema, generated, and one "
           "{examined, outcome} entry per loop",
           data.get("schema") == 1 and isinstance(data.get("generated"), str)
           and data["loops"]["/tracking/loops/closed-one.md"]["outcome"] == "done"
           and data["loops"]["/tracking/loops/left-open.md"]["outcome"] == "open",
           json.dumps(data, indent=2))

    today = datetime.date.today().isoformat()
    record("the examination is dated today, which is what the settled rule and "
           "decay's per-loop gate both compare against",
           {e["examined"] for e in data["loops"].values()} == {today},
           json.dumps(data, indent=2))

    # The validation the prose promises, executed. `pair.partition("=")` cannot
    # fail, so before this every one of these recorded junk under a key naming a
    # loop that does not exist — and the count printed len(argv)-1, so the step
    # reported success. The record is the only thing standing between `decay`
    # and a lane it may not touch, and junk in it is indistinguishable from an
    # examination that happened.
    state_file = bundle / "state" / "closure-sweep.json"
    intact = state_file.read_text(encoding="utf-8")
    for label, bad in (
        ("an empty link (`=done`, a pair typed with the path missing)", "=done"),
        ("a relative path", "tracking/loops/closed-one.md=done"),
        ("a path outside the loops directory", "/facts/closed-one.md=done"),
        ("a link that is not a markdown file", "/tracking/loops/closed-one=done"),
        ("an outcome outside the vocabulary close-loops.py reads",
         "/tracking/loops/closed-one.md=closed"),
    ):
        got = sweep(bad)
        record(f"the recipe refuses {label} — loudly, and writes nothing",
               got.returncode != 0
               and "closure-sweep" in ((got.stdout or "") + (got.stderr or ""))
               and state_file.read_text(encoding="utf-8") == intact,
               f"exit={got.returncode}\n{got.stdout}\n{got.stderr}")

    mixed = sweep("/tracking/loops/untouched.md=open", "/tracking/loops/x.md=nope")
    record("one bad pair rejects the whole command rather than half-recording "
           "the run — a half-written record is not a state this file can be in",
           mixed.returncode != 0
           and state_file.read_text(encoding="utf-8") == intact,
           f"exit={mixed.returncode}\n{mixed.stdout}\n{mixed.stderr}")

    repeated = sweep("/tracking/loops/left-open.md=open",
                     "/tracking/loops/left-open.md=done")
    record("the count is the entries actually recorded, not the arguments "
           "passed — otherwise a run that recorded one loop reports two",
           repeated.returncode == 0 and "1 loop(s) recorded" in repeated.stdout,
           (repeated.stdout or "") + (repeated.stderr or ""))

    # The recipe is the one command in this bundle a human types by hand, and
    # `python3 -` reads stdin: it has no `__file__`, so it cannot resolve its
    # bundle the way every shipped script does. Run from anywhere else it used to
    # create a `state/` there, print a count and exit 0 while the real record
    # stayed untouched, and `decay` then held every loop back as never examined.
    elsewhere = Path(root) / "not-a-bundle"
    elsewhere.mkdir()
    stray = subprocess.run(
        [sys.executable, str(recipe), "/tracking/loops/closed-one.md=done"],
        cwd=str(elsewhere), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    record("the recipe refuses to run outside a bundle root instead of writing a "
           "state/ nobody reads and reporting success",
           stray.returncode == 1
           and "run this from the bundle root" in (stray.stdout + stray.stderr)
           and not (elsewhere / "state").exists(),
           f"exit={stray.returncode}\n{stray.stdout}\n{stray.stderr}")

    # write_text() truncates the target before the replacement lands, so an
    # interruption discards every earlier entry or leaves half a JSON document
    # behind. The write goes through a temporary file renamed onto the target.
    record("the replacement goes to a temporary file renamed onto the target, "
           "never straight through `path.write_text()`, which truncates the "
           "record before the new bytes land",
           "os.replace(" in body and "path.write_text(" not in body,
           body)
    rewritten = sweep("/tracking/loops/untouched.md=open")
    after = json.loads(state_file.read_text(encoding="utf-8"))
    record("a rewrite replaces the record whole: it still parses afterwards, the "
           "earlier runs' entries are all in it, and no temporary file is left "
           "beside it",
           rewritten.returncode == 0
           and set(after["loops"]) == {"/tracking/loops/closed-one.md",
                                       "/tracking/loops/left-open.md",
                                       "/tracking/loops/untouched.md"}
           and not list((bundle / "state").glob("*.tmp")),
           f"exit={rewritten.returncode}\n{json.dumps(after, indent=2)}")

    # Undo those last writes so the queue assertions below read the two-entry
    # record the earlier calls built.
    state_file.write_text(intact, encoding="utf-8")

    payload, result = proposal(bundle)
    if payload is None:
        record("close-loops.py reads the record the procedure wrote", False,
               f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")
        return
    record("close-loops.py reads the record the procedure wrote: both examined "
           "loops are settled and only the untouched one is still queued",
           queued_paths(payload) == ["/tracking/loops/untouched.md"],
           queued_paths(payload))

    # And the record is not a wall: new material returns an examined loop to
    # band 1, so "left open" is a state the routine revisits by itself (E14).
    # Dated the day after the examination, because material has to be strictly
    # newer to count — a fact filed the same day is what the examination read.
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    write_fact(bundle, "beta-shipped", description="beta shipped the migration",
               entities=("beta",), occurred=tomorrow)
    payload, _ = proposal(bundle)
    band1 = [lp for lp in payload["loops"] if lp["band"] == 1]
    record("…and a loop left open returns to band 1 the moment its entities "
           "gain material, which is why nothing is queued for a human",
           [lp["path"] for lp in band1] == ["/tracking/loops/left-open.md"],
           json.dumps([{"path": lp["path"], "band": lp["band"]}
                       for lp in payload["loops"]], indent=2))


# --- (f) (g) the guard, the shipping surface ------------------------------


def test_checkout_guard(root):
    """E22: the guard 9 of the 11 shipped scripts carried before this one."""
    fake = Path(root) / "fake-plugin"
    (fake / ".claude-plugin").mkdir(parents=True)
    (fake / "assets" / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, fake / "assets" / "scripts" / "close-loops.py")
    result = subprocess.run(
        [sys.executable, str(fake / "assets" / "scripts" / "close-loops.py")],
        cwd=str(fake), capture_output=True, text=True, encoding="utf-8",
    )
    record("close-loops.py refuses to run inside the plugin checkout",
           result.returncode != 0
           and "refusing to run inside" in (result.stdout + result.stderr),
           f"exit={result.returncode}\n{result.stdout}\n{result.stderr}")

    plain = Path(root) / "plain" / "assets" / "scripts"
    plain.mkdir(parents=True)
    shutil.copy2(SCRIPT, plain / "close-loops.py")
    result = subprocess.run(
        [sys.executable, str(plain / "close-loops.py"), "--help"],
        cwd=str(plain.parent.parent), capture_output=True, text=True, encoding="utf-8",
    )
    record("…and does not trip on a directory merely named assets/",
           "refusing to run inside" not in (result.stdout + result.stderr),
           result.stdout + result.stderr)


def test_shipping_surface():
    """E24: the script reaches installed bundles, and CI runs this suite."""
    record("the script lives where update's `scripts/` re-sync finds it",
           SCRIPT.parent == REPO_ROOT / "plugin" / "assets" / "scripts")
    ci = CI_WORKFLOW.read_text(encoding="utf-8") if CI_WORKFLOW.exists() else ""
    record("this suite has its own `- run:` line in ci.yml, which has no glob",
           "- run: python tests/test_close_loops.py" in ci)


def main():
    print("elephant-mem test_close_loops — the queue, the evidence proposal, "
          "and the routine that writes the verdict")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print()

    root = Path(tempfile.mkdtemp(prefix="elephant-mem-test-close-loops-"))
    print(f"scratch root: {root}\n")
    try:
        for test in (test_queue_order_and_bound, test_undated_loop_sorts_last,
                     test_bands, test_settled_boundary_is_on_or_after,
                     test_unreadable_examination_date,
                     test_band_two_quota_at_every_reachable_cap,
                     test_band_one_does_not_starve_band_two,
                     test_evidence_ranking, test_evidence_score_composes_not_nests,
                     test_evidence_cap, test_no_evidence,
                     test_criterion_fallback, test_closure_signal_shapes,
                     test_degraded_inputs,
                     test_named_loop_bypasses_the_queue,
                     test_max_is_refused_at_the_boundary,
                     test_owner_is_what_the_file_declares,
                     test_sweep_recipe_writes_what_the_script_reads,
                     test_checkout_guard):
            try:
                test(root)
            except Exception as exc:  # noqa: BLE001 - one broken case must not hide the rest
                import traceback
                record(f"{test.__name__} raised {exc.__class__.__name__}", False,
                       traceback.format_exc())
        test_skill_shape()
        test_procedure_contract()
        test_shipping_surface()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
