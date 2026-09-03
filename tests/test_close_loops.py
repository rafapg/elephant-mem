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
      reason a run reaches the stale end of the lane first, and the settling
      rule is the whole reason run N+1 reaches loops run N did not;
  (b) **the evidence is ranked and capped** — shared non-owner entities, then
      content-word overlap, then recency, capped at 10, with the noise dropped
      rather than padded in (H3). The owner is on nearly every fact in a real
      bundle, which is why sharing only the owner ranks as nothing;
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

    The comments are not decoration: `status: open  # open | done | dropped` is
    what every loop written from the template carries, and it is what a naive
    reader glues onto the value.
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


def test_band_one_fills_the_cap_first(root):
    """E9: when band 1 alone overflows the cap, band 2 gets nothing this run."""
    bundle = make_bundle(root, "band1-overflow")
    for i in range(4):
        write_loop(bundle, f"revisit-{i}", opened="2026-05-01", entities=("acme",))
    write_loop(bundle, "ancient", opened="2020-01-01", entities=("nobody",))
    write_fact(bundle, "new-acme", entities=("acme",), occurred="2026-08-20")
    write_sweep(bundle, {f"/tracking/loops/revisit-{i}.md": "2026-08-01"
                         for i in range(4)})

    payload, _ = proposal(bundle, ["--max", "2"])
    paths = queued_paths(payload)
    record("band 1 fills the cap before band 2 is reached — the oldest loop in "
           "the bundle waits behind the loops with new evidence",
           len(paths) == 2 and all(p.startswith("/tracking/loops/revisit-")
                                   for p in paths),
           paths)
    record("…and the counts still report the whole of both bands, not just what fit",
           payload["counts"]["band1"] == 4 and payload["counts"]["band2"] == 1,
           json.dumps(payload["counts"]))


# --- (b) the evidence -----------------------------------------------------


def test_evidence_ranking(root):
    """H3: shared non-owner entities, then word overlap, then recency, cap 10."""
    bundle = make_bundle(root, "ranking")
    write_loop(bundle, "export", description="Ship the export pipeline fix to Acme",
               entities=("acme", "angelo"),
               signal="a source showing the export pipeline released to Acme")

    write_fact(bundle, "two-shared", description="unrelated wording entirely",
               entities=("acme", "angelo"), occurred="2026-01-01")
    write_fact(bundle, "one-shared-overlap",
               description="the export pipeline shipped to production",
               entities=("acme",), occurred="2026-02-01")
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
    record("the fact sharing two non-owner entities ranks first, however old it is",
           order and order[0] == "/facts/two-shared.md", order)
    record("…then word overlap decides between facts sharing one entity, ahead "
           "of the more recent one that shares no wording",
           order[1:3] == ["/facts/one-shared-overlap.md",
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


# --- (h) the routine --------------------------------------------------------


def read_skill(name):
    path = SKILL_DIR / name
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
                              encoding="utf-8")

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
                     test_bands, test_band_one_fills_the_cap_first,
                     test_evidence_ranking, test_evidence_cap, test_no_evidence,
                     test_criterion_fallback, test_degraded_inputs,
                     test_named_loop_bypasses_the_queue,
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
