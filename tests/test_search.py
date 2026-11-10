#!/usr/bin/env python3
"""Standalone test suite for `scripts/search.py` and `tests/eval_recall.py`.

`search.py` replaces `query`'s navigation (the whole entity catalog, then a hub
per entity, ~208 KB a query on a mature bundle) with a faceted search over
`knowledge/manifest.jsonl` that prints one page inside a fixed budget. What is
checked:

  (a) **the page** — rows newest first with ties on `path`, one page inside the
      budget, header and footer included; a row that would cross it ends the
      page, a single row larger than the budget still prints; pages tile the
      ordered set with no gap and no overlap; a page past the last says which
      page is last; the footer gives the cut date, what lies behind it and the
      next command; the closing `bytes:` is the exact size printed (H1, H3,
      E1-E3);
  (b) **the filters** — repeated `--entity` intersects, `--any` interleaves,
      `--tag`, folded `--text`, inclusive `--since`/`--until`, `--status`; a
      loop's `owner` counts as an entity it is about (H2);
  (c) **the facets** describe the whole matched set, not the page, and leave
      out the owner and the filtered entities;
  (d) **the edges** — a future `occurred` sorts as today and is counted, an
      empty result names the filter that emptied it, an unparseable manifest
      line is skipped and counted, a missing manifest names `build-index.py`
      (E8-E11);
  (e) **names** — exact, whole word, similarity, in that order; one entity in
      the deciding tier resolves, several print candidates and exit 3, none
      (or no roster) exit 4; a similarity match says so, an exact match names
      the whole-word matches it hid (E4-E7);
  (f) **read-only** — neither script writes a byte into the bundle, and
      `search.py` refuses to run from the plugin checkout (E19);
  (g) **the replay** measures what it claims — on a throwaway bundle whose log
      has a known answer, the recall per page, the current path's recall and
      bytes, the oracle stop, and the excluded lines and citations come out
      exactly (H6, E20, E21);
  (h) the suite has its own `- run:` line in CI, which has no glob.

Pure stdlib, Python 3.10+: throwaway bundles in a tempdir, subprocess calls
into a copy of the real `plugin/assets/scripts/search.py`, PASS/FAIL per check,
exit 0 only if every check passes.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_SCRIPT = REPO_ROOT / "plugin" / "assets" / "scripts" / "search.py"
EVAL_SCRIPT = REPO_ROOT / "tests" / "eval_recall.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

checks = []


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in str(detail).splitlines()[:40]:
            print(f"       {ln}")
    return passed


def run(bundle, args):
    return subprocess.run(
        [sys.executable, str(bundle / "scripts" / "search.py")] + [str(a) for a in args],
        cwd=str(bundle), capture_output=True, text=True, encoding="utf-8",
    )


def out_bytes(result):
    return len(result.stdout.encode("utf-8"))


def entries(stdout):
    """The `(date, type, path)` of each row printed, in order."""
    rows = []
    for line in stdout.splitlines():
        parts = line.split("  ")
        if len(parts) == 3 and len(parts[0]) == 10 and parts[0][4] == "-":
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def footer(stdout):
    return stdout.split("\n--\n", 1)[1] if "\n--\n" in stdout else ""


def link(slug, kind="person"):
    return f"/entities/{kind}/{slug}.md"


ROSTER = [
    ("dayane-ferraz", "person", "Dayane Ferraz", "Daiane"),
    ("diane-souza", "person", "Diane Souza", "Di"),
    ("nebulare", "project", "Nebulare", ""),
    ("nebu", "project", "Nebu", ""),
    ("bruno-alves", "person", "Bruno Alves", "Balves,brunoa"),
    ("bruno-teixeira", "person", "Bruno Teixeira", "Bt"),
    ("lucas-prado", "person", "Lucas Prado", "Lucas,Luca"),
    ("lucas-moreno", "person", "Lucas Moreno", "Lm"),
    ("joao-conceicao", "person", "João Conceição", ""),
    ("acme", "org", "Acme", ""),
]


def make_bundle(root, name, rows, roster=ROSTER, owner="bruno-alves",
                extra_lines=()):
    bundle = Path(root) / name
    (bundle / "scripts").mkdir(parents=True)
    (bundle / "knowledge" / "entities").mkdir(parents=True)
    shutil.copy(SEARCH_SCRIPT, bundle / "scripts" / "search.py")
    lines = [json.dumps(r, ensure_ascii=False) for r in rows] + list(extra_lines)
    (bundle / "knowledge" / "manifest.jsonl").write_text(
        "".join(ln + "\n" for ln in lines), encoding="utf-8")
    if roster is not None:
        (bundle / "knowledge" / "entities" / "roster.tsv").write_text(
            "# slug\tkind\ttitle\taliases\n"
            + "".join("\t".join(r) + "\n" for r in roster), encoding="utf-8")
    if owner:
        (bundle / "elephant.json").write_text(
            json.dumps({"owner": {"name": "Owner", "slug": owner}}), encoding="utf-8")
    return bundle


def fact(path, when, ents, desc="", tags=(), kind="fact", status="active", **extra):
    row = {"path": path, "type": kind, "desc": desc or f"fact {path}",
           "entities": [link(e, k) for e, k in ents], "tags": list(tags),
           "occurred": when, "confidence": "high", "status": status}
    row.update(extra)
    return row


def snapshot(root):
    """Every file under root, with its content hash: a write shows up as a diff."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# --- (a)-(d): one bundle with a busy entity -----------------------------------

TODAY = "2026-11-10"
DESC = "Dayane Ferraz said the self-checkout covers offices of up to twenty lawyers " * 3


def busy_rows():
    base = date(2026, 11, 1)
    rows = []
    for i in range(300):
        d = (base - timedelta(days=i // 2)).isoformat()
        ents = [("dayane-ferraz", "person")]
        if i % 3 == 0:
            ents.append(("nebulare", "project"))
        if i % 5 == 0:
            ents.append(("bruno-alves", "person"))
        if i % 7 == 0:
            ents.append(("acme", "org"))
        rows.append(fact(f"/facts/t-{i:03d}.md", d, ents, desc=f"{DESC} #{i}",
                         tags=["pricing"] + (["decision"] if i % 4 == 0 else [])))
    for i in range(40):
        d = (base - timedelta(days=i)).isoformat()
        rows.append(fact(f"/facts/s-{i:03d}.md", d, [("nebulare", "project")],
                         desc=f"Nebulare only fact number {i}", tags=["nebulare"]))
    rows.append(fact("/tracking/loops/owed.md", "2026-10-20", [], kind="open-loop",
                     status="open", desc="Bruno to send the deck to Acme",
                     owner=[link("acme", "org")], owed_to=[link("bruno-alves")]))
    rows.append(fact("/facts/accent.md", "2025-06-15", [("joao-conceicao", "person")],
                     desc="A reunião com João Conceição foi remarcada", tags=["meeting"]))
    rows.append(fact("/facts/future.md", "2030-01-01", [("nebulare", "project")],
                     desc="Vision for 2030", tags=["strategy"]))
    return rows


def page_and_order(tmp):
    bundle = make_bundle(tmp, "busy", busy_rows(), extra_lines=["{ not json", "[1, 2]"])
    before = snapshot(bundle)

    r1 = run(bundle, ["--entity", "dayane", "--as-of", TODAY])
    rows1 = entries(r1.stdout)
    record("H1 a name as written resolves and prints page 1, exit 0",
           r1.returncode == 0 and r1.stdout.startswith("search: entity dayane-ferraz")
           and len(rows1) > 10, r1.stdout[:400] + r1.stderr)
    record("H1 the page fits the 32 KB budget, header and footer included",
           out_bytes(r1) <= 32 * 1024, out_bytes(r1))
    last_line = r1.stdout.rstrip("\n").splitlines()[-1]
    record("the last line is `bytes: <n>`, the exact size printed",
           last_line == f"bytes: {out_bytes(r1)}", last_line)
    dates = [d for d, _, _ in rows1]
    record("rows are newest first", dates == sorted(dates, reverse=True), dates[:6])
    same_day = [p for d, _, p in rows1 if d == "2026-11-01"]
    record("rows on the same date break the tie on path, ascending",
           same_day == sorted(same_day) and len(same_day) == 2, same_day)
    foot = footer(r1.stdout)
    record("E1 the footer gives the page, the count shown, the cut date and what is behind",
           f"page 1 of " in foot and f"showed {len(rows1)} of 300" in foot
           and f"cut at {dates[-1]}" in foot and f"{300 - len(rows1)} more behind the cut" in foot,
           foot)
    record("E1 …and the exact next command", "next: --page 2" in foot, foot)

    # H3: the pages tile the ordered set, no gap and no overlap.
    seen, page, last_out = [], 1, None
    while True:
        r = run(bundle, ["--entity", "dayane-ferraz", "--as-of", TODAY, "--page", page])
        got = entries(r.stdout)
        if not got:
            last_out = r
            break
        seen.extend(p for _, _, p in got)
        page += 1
        if page > 30:
            break
    record("H3 pages tile the matched set: every row once, in order",
           len(seen) == 300 and len(set(seen)) == 300, f"{len(seen)} rows, {len(set(seen))} unique")
    record("E3 a page past the last prints no rows, names the last page, exit 0",
           last_out is not None and last_out.returncode == 0
           and f"which is --page {page - 1}" in footer(last_out.stdout),
           last_out.stdout if last_out else "")

    r = run(bundle, ["--entity", "dayane-ferraz", "--as-of", TODAY, "--budget", "8"])
    record("--budget sets the page size", out_bytes(r) <= 8 * 1024
           and len(entries(r.stdout)) < len(rows1), out_bytes(r))

    # (c) facets of the whole matched set, owner and filtered entities left out.
    record("facets count the whole matched set, not the page",
           "nebulare 100" in foot and "acme 43" in foot, foot)
    record("the owner and the filtered entity are left out of the entity facet",
           "bruno-alves" not in foot.split("entities:", 1)[-1].split("\n", 1)[0]
           and "dayane-ferraz " not in foot, foot)
    record("months facet: the months of the matched set, newest first",
           "months: 2026-11 2 · 2026-10 62 · 2026-09 60" in foot and "older" not in foot, foot)
    r = run(bundle, ["--as-of", TODAY])
    record("months facet: past the last 12 months, one `older` bucket",
           "· older 1" in footer(r.stdout), footer(r.stdout))
    record("tags facet ranks by count", "tags: pricing 300 · decision 75" in foot, foot)
    record("E10 an unparseable manifest line is skipped and counted",
           "skipped: 2 unparseable manifest line(s)" in foot, foot)

    # (b) filters.
    r = run(bundle, ["--entity", "dayane", "--entity", "nebulare", "--as-of", TODAY])
    record("H2 repeated --entity intersects",
           "100 matches" in r.stdout.splitlines()[0], r.stdout.splitlines()[0])
    r = run(bundle, ["--entity", "nebulare", "--entity", "dayane", "--any", "--as-of", TODAY])
    got = [p for _, _, p in entries(r.stdout)]
    record("H2 --any is the union", "341 matches" in r.stdout.splitlines()[0],
           r.stdout.splitlines()[0])
    record("H2 --any round-robins, rows carrying both entities first in each list",
           got[0].startswith("/facts/t-") and got[1].startswith("/facts/t-")
           and int(got[0][9:12]) % 3 == 0 and int(got[1][9:12]) % 3 == 0, got[:6])
    nebulare_only = [p for p in got if p.startswith("/facts/s-")]
    record("H2 --any still reaches the rows only the second entity carries on page 1",
           len(nebulare_only) >= 1, len(nebulare_only))
    r = run(bundle, ["--tag", "decision", "--tag", "pricing", "--as-of", TODAY])
    record("--tag repeated intersects", "75 matches" in r.stdout.splitlines()[0],
           r.stdout.splitlines()[0])
    r = run(bundle, ["--text", "reuniao conceicao", "--as-of", TODAY])
    record("--text matches every word, case- and accent-folded",
           r.stdout.splitlines()[0].endswith("· 1 match")
           and "/facts/accent.md" in r.stdout, r.stdout[:300])
    r = run(bundle, ["--entity", "dayane", "--since", "2026-10-30",
                     "--until", "2026-10-31", "--as-of", TODAY])
    got = entries(r.stdout)
    record("--since and --until are inclusive",
           {d for d, _, _ in got} == {"2026-10-30", "2026-10-31"} and len(got) == 4, got)
    r = run(bundle, ["--status", "open", "--as-of", TODAY])
    record("--status open keeps the loops only",
           [t for _, t, _ in entries(r.stdout)] == ["open-loop"], r.stdout[:300])
    r = run(bundle, ["--entity", "acme", "--status", "open", "--as-of", TODAY])
    record("a loop's owner counts as an entity it is about",
           "/tracking/loops/owed.md" in r.stdout, r.stdout[:300])

    # (d) the edges.
    r = run(bundle, ["--entity", "nebulare", "--as-of", TODAY])
    got = entries(r.stdout)
    record("E8 a future occurred sorts as today and shows its real date",
           got and got[0] == ("2030-01-01", "fact", "/facts/future.md"), got[:2])
    record("E8 …and the footer counts it",
           f"future-dated: 1 row(s) after {TODAY}" in footer(r.stdout), footer(r.stdout))
    r = run(bundle, ["--entity", "dayane", "--tag", "nope", "--as-of", TODAY])
    record("E9 no match: `0 matches`, exit 0",
           r.returncode == 0 and "· 0 matches" in r.stdout.splitlines()[0]
           and not entries(r.stdout), r.stdout)
    record("E9 …and the footer names the one filter that emptied the set",
           "emptied by: --tag nope" in r.stdout, r.stdout)
    r = run(bundle, ["--entity", "joao", "--tag", "nope", "--text", "zzz", "--as-of", TODAY])
    record("E9 …and names none when no single filter did",
           r.returncode == 0 and "emptied by" not in r.stdout, r.stdout)

    record("E19 a dozen searches wrote nothing into the bundle",
           snapshot(bundle) == before, set(snapshot(bundle)) ^ set(before))

    # E2: a single row larger than the budget still prints, alone.
    big = make_bundle(tmp, "big", [
        fact("/facts/huge.md", "2026-11-01", [("acme", "org")], desc="x" * 40000),
        fact("/facts/small.md", "2026-10-01", [("acme", "org")]),
    ])
    r = run(big, ["--entity", "acme"])
    got = entries(r.stdout)
    record("E2 a row larger than the budget prints anyway, alone on its page",
           [p for _, _, p in got] == ["/facts/huge.md"] and out_bytes(r) > 32 * 1024
           and "next: --page 2" in r.stdout, [p for _, _, p in got])

    # E11: no manifest.
    (big / "knowledge" / "manifest.jsonl").unlink()
    r = run(big, ["--entity", "acme"])
    record("E11 a missing manifest exits non-zero, naming build-index.py",
           r.returncode not in (0, 3, 4) and "build-index.py" in r.stdout + r.stderr,
           f"exit={r.returncode}\n{r.stdout}{r.stderr}")
    r = run(big, ["--since", "yesterday"])
    record("a malformed date is a usage error, exit 2", r.returncode == 2, r.returncode)


# --- (e) names ----------------------------------------------------------------


def names(tmp):
    rows = [fact(f"/facts/n-{slug}.md", "2026-10-01", [(slug, kind)])
            for slug, kind, _, _ in ROSTER]
    bundle = make_bundle(tmp, "names", rows)

    def header(r):
        return r.stdout.split("\n--\n", 1)[0]

    r = run(bundle, ["--entity", "Dayane Ferraz"])
    record("an exact title resolves", r.returncode == 0
           and "entity dayane-ferraz" in r.stdout and "/facts/n-dayane-ferraz.md" in r.stdout,
           r.stdout)
    r = run(bundle, ["--entity", "joao conceicao"])
    record("exact matching is case- and accent-folded",
           r.returncode == 0 and "entity joao-conceicao" in r.stdout, r.stdout)
    r = run(bundle, ["--entity", "balves"])
    record("an alias resolves exactly", r.returncode == 0
           and "entity bruno-alves" in r.stdout, r.stdout)
    r = run(bundle, ["--entity", "/entities/person/dayane-ferraz.md"])
    record("an entity path resolves to its slug",
           r.returncode == 0 and "entity dayane-ferraz" in r.stdout, r.stdout)
    r = run(bundle, ["--entity", "ferraz"])
    record("a whole word of one name resolves",
           r.returncode == 0 and "entity dayane-ferraz" in r.stdout, r.stdout)

    r = run(bundle, ["--entity", "bruno"])
    record("E4 a whole word shared by several entities exits 3",
           r.returncode == 3, f"exit={r.returncode}\n{r.stdout}")
    record("E4 …printing the candidates and no rows",
           "bruno-alves\tperson\tBruno Alves" in r.stdout
           and "bruno-teixeira" in r.stdout and not entries(r.stdout), r.stdout)
    r = run(bundle, ["--entity", "daine"])
    record("E4 a similarity tie is never guessed (daine: dayane via the alias daiane, or diane)",
           r.returncode == 3 and "dayane-ferraz" in r.stdout and "diane-souza" in r.stdout
           and "by similarity" in r.stdout, f"exit={r.returncode}\n{r.stdout}")

    r = run(bundle, ["--entity", "xyzzy"])
    record("E5 a name that matches nothing exits 4 and tells the agent to read the roster",
           r.returncode == 4 and "roster" in r.stdout and not entries(r.stdout),
           f"exit={r.returncode}\n{r.stdout}")

    r = run(bundle, ["--entity", "nebulre"])
    record("E6 a unique similarity match resolves",
           r.returncode == 0 and "entity nebulare" in r.stdout, f"exit={r.returncode}\n{r.stdout}")
    record("E6 …and the header says it was by similarity",
           "nebulre → nebulare, by similarity" in header(r), header(r))

    r = run(bundle, ["--entity", "lucas"])
    record("E7 an exact match resolves even when whole-word matches exist",
           r.returncode == 0 and "entity lucas-prado" in r.stdout, r.stdout)
    record("E7 …and the header names the matches it hid",
           "lucas → lucas-prado; also matches: lucas-moreno" in header(r), header(r))

    r = run(bundle, ["--entity", "bruno", "--entity", "xyzzy"])
    record("an ambiguous and a missing name together exit 3 and report both",
           r.returncode == 3 and "ambiguous" in r.stdout and "not found" in r.stdout,
           f"exit={r.returncode}\n{r.stdout}")

    rosterless = make_bundle(tmp, "rosterless", rows, roster=None)
    r = run(rosterless, ["--entity", "dayane"])
    record("E5 with no roster.tsv a name exits 4, pointing at entities/index.md",
           r.returncode == 4 and "entities/index.md" in r.stdout, f"exit={r.returncode}\n{r.stdout}")
    r = run(rosterless, ["--entity", "/entities/person/dayane-ferraz.md"])
    record("…while an entity path still needs no roster",
           r.returncode == 0 and "/facts/n-dayane-ferraz.md" in r.stdout, r.stdout)


# --- (f) the checkout guard ----------------------------------------------------


def guard(tmp):
    fake = Path(tmp) / "fake-plugin"
    (fake / ".claude-plugin").mkdir(parents=True)
    (fake / "assets" / "scripts").mkdir(parents=True)
    shutil.copy(SEARCH_SCRIPT, fake / "assets" / "scripts" / "search.py")
    r = subprocess.run([sys.executable, str(fake / "assets" / "scripts" / "search.py")],
                       cwd=str(fake), capture_output=True, text=True, encoding="utf-8")
    record("E19 search.py refuses to run inside the plugin checkout",
           r.returncode != 0 and "refusing to run inside" in r.stdout + r.stderr,
           f"exit={r.returncode}\n{r.stdout}{r.stderr}")
    record("the script lives where update's `cp scripts/*.py` re-sync finds it",
           SEARCH_SCRIPT.parent == REPO_ROOT / "plugin" / "assets" / "scripts")


# --- (g) the replay -----------------------------------------------------------

ALPHA_DESC = "A" * 260


def replay_bundle(tmp):
    """A bundle whose log has a known answer.

    `alpha` has 500 facts, one a day; `beta` has 20. Entries are ~305 bytes,
    so a 32 KB page holds ~100 rows: alpha's ranks 10 and 60 land on page 1,
    150 on page 2 and 450 on page 5, beyond the 4-page ceiling. A hub inlines
    50 rows, so the current path sees rank 10 and not rank 60.
    """
    base = date(2026, 10, 31)
    rows = []
    for i in range(500):
        rows.append(fact(f"/facts/alpha-{i:03d}.md", (base - timedelta(days=i)).isoformat(),
                         [("alpha", "person")], desc=f"{ALPHA_DESC} {i}"))
    for i in range(20):
        rows.append(fact(f"/facts/beta-{i:03d}.md", (base - timedelta(days=i)).isoformat(),
                         [("beta", "project")], desc=f"beta {i}"))
    rows.append(fact("/facts/alpha-late.md", "2026-11-20", [("alpha", "person")]))
    roster = [("alpha", "person", "Alpha", ""), ("beta", "project", "Beta", "")]
    bundle = make_bundle(tmp, "replayed", rows, roster=roster, owner=None)
    ents = bundle / "knowledge" / "entities"
    (ents / "index.md").write_text("c" * 10000, encoding="utf-8")
    (ents / "person").mkdir()
    (ents / "project").mkdir()
    (ents / "person" / "alpha.md").write_text("h" * 5000, encoding="utf-8")
    (ents / "person" / "alpha.facts-archive.md").write_text("a" * 20000, encoding="utf-8")
    (ents / "project" / "beta.md").write_text("h" * 3000, encoding="utf-8")
    (bundle / "state").mkdir()
    ts = "2026-11-05T10:00:00-03:00"
    log = [
        {"ts": ts, "mode": "query", "entities": ["alpha"],
         "facts_cited": ["/facts/alpha-009.md", "/facts/alpha-059.md",
                         "knowledge/facts/alpha-149.md", "/facts/alpha-449.md",
                         "/sources/x.md"],
         "question": "never printed", "caller": "human", "caller_basis": "x"},
        {"ts": ts, "mode": "query", "entities": ["/entities/project/beta.md"],
         "facts_cited": ["/facts/beta-000.md", "/facts/beta-004.md",
                         "/facts/alpha-late.md"]},
        {"ts": ts, "mode": "briefing", "entities": ["alpha"],
         "facts_cited": ["/facts/alpha-000.md"]},
        {"ts": ts, "mode": "query", "entities": ["alpha"],
         "facts_cited": ["/facts/gone.md"]},
        {"ts": ts, "mode": "query", "entities": [],
         "facts_cited": ["/facts/alpha-000.md"]},
    ]
    (bundle / "state" / "consumption-log.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in log) + "garbage\n", encoding="utf-8")
    return bundle


def replay(tmp):
    bundle = replay_bundle(tmp)
    before = snapshot(bundle)
    r = subprocess.run([sys.executable, str(EVAL_SCRIPT), "--bundle", str(bundle), "--json"],
                       capture_output=True, text=True, encoding="utf-8")
    record("H6 eval_recall.py --json runs on a throwaway bundle, exit 0",
           r.returncode == 0, f"exit={r.returncode}\n{r.stdout[-800:]}{r.stderr[-800:]}")
    rep = json.loads(r.stdout)
    c = rep["counts"]
    record("E21 only query lines are replayed; briefing lines are excluded",
           c["lines_replayed"] == 2 and c["excluded_not_query"] == 1, c)
    record("E20 citations no longer in the manifest leave the denominator, counted apart",
           c["citations"] == 7 and c["citations_not_in_manifest"] == 2
           and c["excluded_no_citation_in_manifest"] == 1, c)
    record("a query line with no entity is excluded and counted",
           c["excluded_no_entity"] == 1 and c["log_unparseable"] == 1, c)
    record("a citation dated after its own line is counted",
           c["citations_dated_after_line"] == 1, c)
    s32 = rep["search"]["32"]
    record("H6 recall at 1 to 4 pages of 32 KB is exactly 4/7, 5/7, 5/7, 5/7",
           [round(x, 6) for x in s32["recall_at_pages"]]
           == [round(x, 6) for x in (4 / 7, 5 / 7, 5 / 7, 5 / 7)],
           s32["recall_at_pages"])
    record("H6 the current path sees the hub's 50 newest: recall 3/7",
           abs(rep["current"]["recall"] - 3 / 7) < 1e-9, rep["current"])
    record("H6 the current path's bytes are the catalog plus the logged entities' hubs",
           rep["current"]["bytes_mean"] == 14000
           and rep["current_archives"]["bytes_mean"] == 24000
           and abs(rep["current_archives"]["recall"] - 6 / 7) < 1e-9,
           (rep["current"], rep["current_archives"]))
    record("H6 the oracle stops at page 1 when every citation is seen, at 4 otherwise",
           s32["oracle_stop_at_page"] == {"1": 1, "2": 0, "3": 0, "4": 1},
           s32["oracle_stop_at_page"])
    record("H6 the oracle's bytes are the pages it read, each within the budget",
           3 * 32 * 1024 < s32["oracle_bytes_mean"] * 2 <= 5 * 32 * 1024
           and s32["oracle_bytes_median"] == s32["oracle_bytes_mean"],
           s32)
    record("H6 the curve covers 16, 32, 48 and 64 KB pages",
           sorted(rep["search"], key=int) == ["16", "32", "48", "64"]
           and rep["search"]["16"]["recall_at_pages"][0] < s32["recall_at_pages"][0],
           list(rep["search"]))
    record("the acceptance verdicts follow from the numbers",
           rep["acceptance"] == {"recall_at_least_current": True,
                                 "oracle_bytes_at_most_half": False}, rep["acceptance"])

    r = subprocess.run([sys.executable, str(EVAL_SCRIPT), "--bundle", str(bundle)],
                       capture_output=True, text=True, encoding="utf-8")
    record("the text report prints the before/after table and the acceptance line",
           r.returncode == 0 and "| current: catalog + inline hubs" in r.stdout
           and "Acceptance:" in r.stdout and "tokens" in r.stdout, r.stdout + r.stderr)
    record("the report prints aggregates only: no question, path or slug",
           "never printed" not in r.stdout and "/facts/" not in r.stdout
           and "alpha" not in r.stdout and "beta" not in r.stdout, r.stdout)
    record("E19 the replay wrote nothing into the bundle", snapshot(bundle) == before,
           set(snapshot(bundle)) ^ set(before))
    r = subprocess.run([sys.executable, str(EVAL_SCRIPT)],
                       capture_output=True, text=True, encoding="utf-8")
    record("run bare (as the suite loop does), the replay says so and exits 0",
           r.returncode == 0 and "nothing replayed" in r.stdout, r.stdout + r.stderr)


def guarded(fn, tmp):
    try:
        fn(tmp)
    except Exception:  # noqa: BLE001 — report it and go on to the next group
        record(f"{fn.__name__} raised an unexpected exception", False, traceback.format_exc())


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for group in (page_and_order, names, guard, replay):
            guarded(group, tmp)
    ci = CI_WORKFLOW.read_text(encoding="utf-8") if CI_WORKFLOW.exists() else ""
    record("this suite has its own `- run:` line in ci.yml, which has no glob",
           "- run: python tests/test_search.py" in ci)
    passed = sum(1 for _, ok in checks if ok)
    print(f"\n{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
