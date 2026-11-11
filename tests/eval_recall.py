#!/usr/bin/env python3
"""Replay a bundle's consumption log against `search.py` and the path it replaces.

    python3 tests/eval_recall.py --bundle ~/elephant-mem [--json]

The acceptance tool for recall v0. Each `query` line of
`<bundle>/state/consumption-log.jsonl` is replayed as of its own date: only
manifest rows whose `occurred` is on or before the line's date take part, and
the line's logged entities are the query. Two paths are measured against the
facts that line actually cited:

- **the current path**: the entity catalog (`entities/index.md`) read whole,
  then one hub per logged entity, whose inline block lists that entity's
  `hub_max_facts` newest rows (50 by default). Its bytes are the catalog plus
  today's hub files of those entities. An approximation: the hubs on the line's
  date held different rows, and the replay can only rebuild their membership.
  "+ archives" adds every row of the entity and the size of its archive shard,
  which is the most that following the entities could ever see;
- **the search path**: `search.py --entity … --any --until <date>`, one page
  of 32 KB at a time, 1 to 4 fixed pages (or fewer, when the list ends first),
  plus a curve over 16, 32, 48 and 64 KB pages.

**Acceptance is judged on the rule the agent runs.** `query/procedure.md`
caps a query at 4 search pages, and an agent cannot know which facts its
answer will cite before it reads them. So both gates read 4 fixed pages: their
recall must reach the current path's, and their mean bytes must stay at or
under 60% of the current path's. The oracle stop (read pages until every cited
fact has been shown, capped at 4) uses the answer key, so it is reported as a
lower bound on bytes, for reference, and decides nothing. With no line
replayed (an empty manifest, a missing or unreadable log) the report says
"nothing to judge" rather than pass.

Recall is pooled over citations: the cited facts a path showed, over the cited
facts still in the manifest. A citation no longer in the manifest (superseded,
deleted, or not a fact or loop at all) leaves the denominator and is counted on
its own line (E20). Only `query` lines count (E21): `briefing` and `start-day`
cite from a time window, not from entities. What the numbers do not measure is
listed under the report's Caveats.

**Read-only, and aggregate-only.** This opens the bundle's files for reading
and writes nothing anywhere, not even a `__pycache__/` beside the imported
`search.py`. The report prints counts and fractions, never a
question, a path or a slug, so it can be pasted into a pull request. It imports
`plugin/assets/scripts/search.py` from this checkout, so the code measured is
the code under review. Pure stdlib, Python 3.10+.
"""
import argparse
import importlib.util
import json
import posixpath
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_SCRIPT = REPO_ROOT / "plugin" / "assets" / "scripts" / "search.py"

PAGE_KB = 32
MAX_PAGES = 4
CURVE_KB = (16, 32, 48, 64)
# The bytes gate: MAX_PAGES fixed pages read at most this share of the current
# path's mean. The owner set it at 0.60 once the 4-page ceiling, measured as the
# agent runs it rather than with an oracle stop, came out at about half.
BYTES_GATE = 0.60
HUB_MAX_FACTS_DEFAULT = 50
ARCHIVE_SUFFIX = ".facts-archive.md"


def load_search():
    # Importing would leave a `__pycache__/` next to search.py in the checkout;
    # "writes nothing anywhere" has to hold there too.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("elephant_search", SEARCH_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalize_item(raw):
    """A cited path as the manifest spells it: `/facts/….md`."""
    s = str(raw or "").strip().replace("\\", "/")
    if not s:
        return None
    if s.startswith("./"):
        s = s[2:]
    if not s.startswith("/"):
        s = "/" + s
    s = posixpath.normpath(s)
    if s.startswith("/knowledge/"):
        s = s[len("/knowledge"):]
    return s


def hub_max_facts(bundle):
    try:
        cfg = json.loads((bundle / "elephant.json").read_text(encoding="utf-8"))
        v = cfg.get("index", {}).get("hub_max_facts")
        if isinstance(v, int) and v > 0:
            return v
    except Exception:  # noqa: BLE001 — the default is the documented fallback
        pass
    return HUB_MAX_FACTS_DEFAULT


def file_size(path):
    try:
        return path.stat().st_size
    except OSError:
        return 0


def hub_path(knowledge, slug, kinds):
    kind = kinds.get(slug)
    if kind:
        return knowledge / "entities" / kind / f"{slug}.md"
    for candidate in sorted((knowledge / "entities").glob(f"*/{slug}.md")):
        return candidate
    return None


def hub_slugs(row, search):
    """Who a row is backlinked from on a hub: `entities` and a loop's `owner`."""
    out = set()
    for key in ("entities", "owner"):
        value = row.get(key)
        for link in value if isinstance(value, list) else ([value] if value else []):
            s = search.slug_of(link)
            if s:
                out.add(s)
    return out


def read_log(bundle):
    """`(rows, unparseable, readable)`. A missing or unreadable log is not an
    error here, but it must not read as a log that passed: `readable` says so."""
    path = bundle / "state" / "consumption-log.jsonl"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], 0, False
    rows, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict) and isinstance(row.get("ts"), str) and len(row["ts"]) >= 10:
            rows.append(row)
        else:
            bad += 1
    return rows, bad, True


def mean(values):
    return statistics.fmean(values) if values else 0.0


def median(values):
    return statistics.median(values) if values else 0.0


def replay(bundle, search=None):
    """Every number of the report, as a dict. Reads, never writes."""
    search = search or load_search()
    bundle = Path(bundle)
    knowledge = bundle / "knowledge"
    rows, unparseable = search.load_manifest(knowledge)
    by_path = {r["path"]: r for r in rows}
    roster = search.load_roster(knowledge) or []
    kinds = {e["slug"]: e["kind"] for e in roster}
    catalog_bytes = file_size(knowledge / "entities" / "index.md")
    hub_max = hub_max_facts(bundle)
    log, log_bad, log_readable = read_log(bundle)
    # The same owner `search.py`'s main() hands its Result: it trims the entity
    # facet, so it changes the footer, the page room and every byte measured.
    owner = search.owner_slug(bundle)
    ents_per_line = []

    counts = {
        "log_readable": log_readable,
        "log_lines": len(log),
        "log_unparseable": log_bad,
        "manifest_rows": len(rows),
        "manifest_unparseable": unparseable,
        "excluded_not_query": 0,
        "excluded_no_entity": 0,
        "excluded_no_citation_in_manifest": 0,
        "citations_not_in_manifest": 0,
        "citations_dated_after_line": 0,
        "lines_replayed": 0,
        "lines_with_owner": 0,
        "citations": 0,
    }
    seen = {
        "current": 0,
        "current_archives": 0,
        "search": {kb: [0] * MAX_PAGES for kb in CURVE_KB},
    }
    bytes_ = {
        "current": [],
        "current_archives": [],
        "oracle": {kb: [] for kb in CURVE_KB},
        "pages": {kb: [[] for _ in range(MAX_PAGES)] for kb in CURVE_KB},
    }
    stops = {kb: [] for kb in CURVE_KB}

    for line in log:
        if line.get("mode") != "query":
            counts["excluded_not_query"] += 1
            continue
        day = line["ts"][:10]
        ents = []
        for e in line.get("entities") or []:
            s = search.slug_of(e)
            if s and s not in ents:
                ents.append(s)
        cited = []
        for item in line.get("facts_cited") or []:
            p = normalize_item(item)
            if not p or p in cited:
                continue
            if p in by_path:
                cited.append(p)
            else:
                counts["citations_not_in_manifest"] += 1
        if not ents:
            counts["excluded_no_entity"] += 1
            continue
        if not cited:
            counts["excluded_no_citation_in_manifest"] += 1
            continue
        counts["lines_replayed"] += 1
        counts["citations"] += len(cited)
        ents_per_line.append(len(ents))
        if owner and owner in ents:
            counts["lines_with_owner"] += 1
        counts["citations_dated_after_line"] += sum(
            1 for p in cited if search.occurred(by_path[p]) > day)
        wanted = set(cited)

        # The current path: catalog + one hub per entity, its newest rows inline.
        dated = [r for r in rows if search.occurred(r) and search.occurred(r) <= day]
        inline, everything, hub_bytes, archive_bytes = set(), set(), 0, 0
        for slug in ents:
            own = [r for r in dated if slug in hub_slugs(r, search)]
            own.sort(key=lambda r: r["path"])
            own.sort(key=lambda r: search.occurred(r), reverse=True)
            inline.update(r["path"] for r in own[:hub_max])
            everything.update(r["path"] for r in own)
            hub = hub_path(knowledge, slug, kinds)
            if hub is not None:
                hub_bytes += file_size(hub)
                archive_bytes += file_size(hub.with_name(slug + ARCHIVE_SUFFIX))
        seen["current"] += len(wanted & inline)
        seen["current_archives"] += len(wanted & everything)
        bytes_["current"].append(catalog_bytes + hub_bytes)
        bytes_["current_archives"].append(catalog_bytes + hub_bytes + archive_bytes)

        # The search path, per page size.
        query = search.Query(entities=ents, any_mode=True, until=day, as_of=day)
        for kb in CURVE_KB:
            result = search.Result(rows, query, budget=kb * search.KB, owner=owner)
            last = min(MAX_PAGES, len(result.pages)) or 1
            shown, stop, spent = set(), None, 0
            for page in range(1, MAX_PAGES + 1):
                if page <= last:
                    size = len(result.render(page).encode("utf-8"))
                    shown.update(r["path"] for r in result.page_rows(page))
                    bytes_["pages"][kb][page - 1].append(size)
                    if stop is None:
                        spent += size
                        if wanted <= shown or page == last:
                            stop = page
                seen["search"][kb][page - 1] += len(wanted & shown)
            stops[kb].append(stop)
            bytes_["oracle"][kb].append(spent)

    n = counts["citations"] or 1
    counts["entities_per_line_mean"] = mean(ents_per_line)
    counts["entities_per_line_max"] = max(ents_per_line, default=0)
    report = {
        "counts": counts,
        "hub_max_facts": hub_max,
        "current": {
            "recall": seen["current"] / n,
            "bytes_mean": mean(bytes_["current"]),
            "bytes_median": median(bytes_["current"]),
        },
        "current_archives": {
            "recall": seen["current_archives"] / n,
            "bytes_mean": mean(bytes_["current_archives"]),
            "bytes_median": median(bytes_["current_archives"]),
        },
        "search": {},
    }
    for kb in CURVE_KB:
        cumulative = []
        for k in range(MAX_PAGES):
            cumulative.append(sum(sum(v) for v in (bytes_["pages"][kb][j] for j in range(k + 1)))
                              / (counts["lines_replayed"] or 1))
        report["search"][kb] = {
            "recall_at_pages": [s / n for s in seen["search"][kb]],
            "oracle_bytes_mean": mean(bytes_["oracle"][kb]),
            "oracle_bytes_median": median(bytes_["oracle"][kb]),
            "oracle_stop_at_page": {
                str(p): sum(1 for s in stops[kb] if s == p) for p in range(1, MAX_PAGES + 1)
            },
            "pages_bytes_mean": cumulative,
        }
    # Both gates are measured on the rule the agent can execute: the
    # procedure's ceiling of MAX_PAGES fixed pages. The oracle stop needs the
    # answer's citations before reading, which no agent has, so it is reported
    # as a lower bound and decides nothing. With nothing replayed there is
    # nothing to judge, and the gates say so rather than pass.
    main = report["search"][PAGE_KB]
    judged = counts["lines_replayed"] > 0
    report["acceptance"] = {
        "judged": judged,
        "fixed_pages_recall_at_least_current": (
            main["recall_at_pages"][MAX_PAGES - 1] >= report["current"]["recall"]
            if judged else None),
        "fixed_pages_bytes_at_most_60pct": (
            main["pages_bytes_mean"][MAX_PAGES - 1]
            <= report["current"]["bytes_mean"] * BYTES_GATE
            if judged else None),
    }
    return report


def kb(n):
    return f"{n / 1024:,.0f} KB"


def tokens(n):
    return f"~{n / 4 / 1000:,.1f}k tokens"


def render(report):
    c = report["counts"]
    cur, arc = report["current"], report["current_archives"]
    main = report["search"][PAGE_KB]
    out = []
    out.append("# recall v0 replay")
    out.append("")
    out.append(f"{c['lines_replayed']} query lines replayed, {c['citations']} citations "
               f"still in the manifest ({c['manifest_rows']} manifest rows).")
    out.append(f"Excluded: {c['excluded_not_query']} non-query lines, "
               f"{c['excluded_no_entity']} query lines with no entity, "
               f"{c['excluded_no_citation_in_manifest']} with no citation left in the manifest; "
               f"{c['citations_not_in_manifest']} citations no longer in the manifest; "
               f"{c['citations_dated_after_line']} citations dated after their own line "
               f"(unseeable by either path).")
    if c["log_unparseable"] or c["manifest_unparseable"]:
        out.append(f"Unparseable: {c['log_unparseable']} log lines, "
                   f"{c['manifest_unparseable']} manifest lines.")
    out.append("")
    out.append("| path | read per query (mean / median) | tokens (mean) | cited facts seen |")
    out.append("|---|---|---|---|")
    out.append(f"| current: catalog + inline hubs (≤{report['hub_max_facts']} rows) "
               f"| {kb(cur['bytes_mean'])} / {kb(cur['bytes_median'])} "
               f"| {tokens(cur['bytes_mean'])} | {cur['recall']:.2f} |")
    out.append(f"| current + archives | {kb(arc['bytes_mean'])} / {kb(arc['bytes_median'])} "
               f"| {tokens(arc['bytes_mean'])} | {arc['recall']:.2f} |")
    for k in range(MAX_PAGES):
        gated = " (the procedure's ceiling: gated)" if k == MAX_PAGES - 1 else ""
        out.append(f"| search, `--any`, {k + 1} fixed page(s) of {PAGE_KB} KB{gated} "
                   f"| {kb(main['pages_bytes_mean'][k])} | {tokens(main['pages_bytes_mean'][k])} "
                   f"| {main['recall_at_pages'][k]:.2f} |")
    out.append(f"| search, oracle stop (lower bound, reference only; ≤{MAX_PAGES} pages) "
               f"| {kb(main['oracle_bytes_mean'])} / {kb(main['oracle_bytes_median'])} "
               f"| {tokens(main['oracle_bytes_mean'])} | {main['recall_at_pages'][-1]:.2f} |")
    out.append("")
    stops = main["oracle_stop_at_page"]
    out.append("Oracle stop, lines per page: "
               + ", ".join(f"page {p}: {n}" for p, n in stops.items()) + ". The oracle "
               "stops once every fact the answer cited has been shown, which an agent "
               "cannot know before it reads: a lower bound on bytes, not a rule anyone runs.")
    out.append("")
    out.append("Budget curve, recall at 1 to 4 pages and oracle-stop bytes (mean):")
    out.append("")
    out.append("| page size | 1 | 2 | 3 | 4 | oracle bytes |")
    out.append("|---|---|---|---|---|---|")
    for size, row in report["search"].items():
        r = row["recall_at_pages"]
        out.append(f"| {size} KB | {r[0]:.2f} | {r[1]:.2f} | {r[2]:.2f} | {r[3]:.2f} "
                   f"| {kb(row['oracle_bytes_mean'])} |")
    out.append("")
    acc = report["acceptance"]
    if not acc["judged"]:
        why = ("the consumption log is missing or unreadable" if not c["log_readable"]
               else "no query line had both an entity and a citation still in the manifest")
        out.append(f"Acceptance: nothing to judge — 0 query lines replayed ({why}).")
    else:
        fixed = main["pages_bytes_mean"][MAX_PAGES - 1]
        ratio = fixed / cur["bytes_mean"] if cur["bytes_mean"] else 0
        oracle = main["oracle_bytes_mean"] / cur["bytes_mean"] if cur["bytes_mean"] else 0
        out.append(f"Acceptance, at the procedure's ceiling of {MAX_PAGES} fixed pages "
                   f"(the rule the agent runs): recall {main['recall_at_pages'][MAX_PAGES - 1]:.2f} "
                   f"vs current {cur['recall']:.2f} — "
                   f"{'PASS' if acc['fixed_pages_recall_at_least_current'] else 'FAIL'}; "
                   f"bytes {ratio:.0%} of current, gate ≤ {BYTES_GATE:.0%} — "
                   f"{'PASS' if acc['fixed_pages_bytes_at_most_60pct'] else 'FAIL'}. "
                   f"The oracle stop ({oracle:.0%} of current) is a lower bound, for "
                   f"reference; it decides nothing.")
    out.append("")
    logged = c["citations"] + c["citations_not_in_manifest"]
    share = c["citations_not_in_manifest"] / logged if logged else 0
    out.append("Caveats:")
    out.append("")
    out.append("- The current path is costed at today's catalog and hub sizes, not at "
               "their size on each line's date. Both grow with the bundle, so those bytes "
               "overstate what the path read then, and the search's share of them "
               "flatters the search.")
    out.append("- The current path's hubs are rebuilt from today's manifest as of each "
               "line's date, so they approximate the hubs of that day.")
    out.append(f"- The query's entities are the `--entity` values the answer logged, not "
               f"the names in the question (the procedure's first look uses those): "
               f"{c['entities_per_line_mean']:.2f} per line on average, at most "
               f"{c['entities_per_line_max']}, and the owner in {c['lines_with_owner']} "
               f"of {c['lines_replayed']} lines.")
    out.append(f"- {c['citations_not_in_manifest']} of {logged} logged citations "
               f"({share:.0%}) are no longer in the manifest and sit outside every "
               f"recall's denominator.")
    out.append("- The replay cannot refine by `--text` or an entity pair (it has no "
               "question text), which understates the search; today's manifest replayed "
               "against past dates crowds the past with rows ingested later, which "
               "understates it too; and the cited facts were chosen from what the "
               "current path showed, which favours that path.")
    return "\n".join(out) + "\n"


def main(argv):
    p = argparse.ArgumentParser(prog="eval_recall.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bundle", help="the bundle to replay, read only")
    p.add_argument("--json", action="store_true", help="print the numbers as JSON")
    args = p.parse_args(argv)
    if not args.bundle:
        # Not a suite: `for t in tests/*.py` runs it bare, and a bare run has
        # nothing to replay. Say how to use it and leave the loop green.
        print("eval_recall.py: nothing replayed; pass --bundle <path> "
              "(tests/test_search.py exercises it on a throwaway bundle).")
        return 0
    bundle = Path(args.bundle).expanduser()
    if not (bundle / "knowledge" / "manifest.jsonl").is_file():
        print(f"no manifest at {bundle}/knowledge/manifest.jsonl", file=sys.stderr)
        return 1
    report = replay(bundle)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        sys.stdout.write(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
