#!/usr/bin/env python3
"""Regenerate the derived surfaces of the elephant bundle from frontmatter.

At scale the bundle must NOT keep one flat global list of facts — that index
would grow without bound. Instead retrieval is entity-centric: facts are reached
through the entity pages that link them. So this script regenerates:

  1. knowledge/entities/index.md   — the entity CATALOG (the navigation spine),
                                      grouped by kind. Bounded by # of entities.
  2. knowledge/tracking/open-loops.md — board of `status: open` loops by owner.
  3. knowledge/index.md            — a thin ROUTER: pointers + recent activity.
                                      Does NOT list every fact.
  4. entity/source backlinks       — the auto-facts block in each entity/source
                                      file, listing facts that reference it.
  5. knowledge/manifest.jsonl      — ultra-slim triage surface: one compact JSON
                                      line per active fact / open loop, carrying
                                      only the fields needed to DECIDE what to
                                      read in full (path, type, desc, entities,
                                      tags, occurred, confidence, status). A
                                      subagent loads the whole
                                      manifest cheaply, triages, then deep-reads
                                      only the chosen files.

Never hand-edit those — this script is the single source of truth so they can't
drift. Pure stdlib (PyYAML optional, with a minimal fallback).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, "knowledge")
RESERVED = {"index.md", "log.md", "open-loops.md"}
RECENT_N = 12

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
INLINE_LIST = re.compile(r"^\[(.*)\]$")
AUTO = re.compile(r"<!-- BEGIN auto-facts -->.*?<!-- END auto-facts -->", re.DOTALL)

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


def parse_fm(block):
    if yaml is not None:
        try:
            data = yaml.safe_load(block) or {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    data = {}
    for line in block.splitlines():
        if not line or line[0] in " \t#" or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        m = INLINE_LIST.match(val)
        if m:
            inner = m.group(1).strip()
            data[key] = [x.strip() for x in inner.split(",") if x.strip()] if inner else []
        else:
            data[key] = val
    return data


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v).strip()] if str(v).strip() else []


def md_files(base):
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".md"):
                yield os.path.join(dirpath, f)


def bundle_link(path):
    return "/" + os.path.relpath(path, BUNDLE).replace(os.sep, "/")


def line(c):
    """`- [title](link) — description`, without repeating the description."""
    title = c["title"]
    desc = f" — {c['description']}" if c["description"] and c["description"] != title else ""
    return f"- [{title}]({c['link']}){desc}"


def write(rel, lines):
    path = os.path.join(BUNDLE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")


def main():
    concepts = []
    for path in md_files(BUNDLE):
        if os.path.basename(path) in RESERVED:
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        m = FM.match(text)
        if not m:
            continue
        fm = parse_fm(m.group(1))
        title = fm.get("title") or fm.get("description") or os.path.basename(path)[:-3]
        concepts.append({
            "type": str(fm.get("type", "untyped")),
            "kind": str(fm.get("kind", "other")),
            "title": str(title),
            "description": str(fm.get("description", "")),
            "status": str(fm.get("status", "active")),
            "updated": str(fm.get("updated", "")),
            "link": bundle_link(path),
            "fm": fm,
            "path": path,
        })

    def active(items):
        return [c for c in items if c["status"] not in ("deprecated", "superseded")]

    entities = [c for c in concepts if c["type"] == "entity"]
    facts = [c for c in concepts if c["type"] == "fact"]
    sources = [c for c in concepts if c["type"] == "source"]
    loops = [c for c in concepts if c["type"] == "open-loop"]

    # 1. entities/index.md — catalog by kind
    cat = ["# Entities", "", "Catalog (the navigation spine). Derived — do not edit by hand.", ""]
    by_kind = {}
    for c in active(entities):
        by_kind.setdefault(c["kind"], []).append(c)
    for k in sorted(by_kind):
        cat.append(f"## {k}")
        cat.append("")
        for c in sorted(by_kind[k], key=lambda x: x["title"].lower()):
            cat.append(line(c))
        cat.append("")
    write("entities/index.md", cat)

    # 2. tracking/open-loops.md — board of open loops by owner
    board = ["# Open loops", "", "Action items / commitments still open. Derived — do not edit by hand.", ""]
    open_loops = [c for c in loops if str(c["fm"].get("status", "open")) == "open"]
    if not open_loops:
        board.append("_No open loops._")
    else:
        by_owner = {}
        for c in open_loops:
            owners = as_list(c["fm"].get("owner")) or ["(unassigned)"]
            for o in owners:
                by_owner.setdefault(o, []).append(c)
        for o in sorted(by_owner):
            board.append(f"## {o}")
            board.append("")
            for c in sorted(by_owner[o], key=lambda x: x["fm"].get("opened", "")):
                opened = c["fm"].get("opened", "")
                board.append(f"- [{c['description'] or c['title']}]({c['link']}) — opened {opened}")
            board.append("")
    write("tracking/open-loops.md", board)

    # 3. knowledge/index.md — thin router
    n_kind = {k: len(v) for k, v in by_kind.items()}
    kinds_str = ", ".join(f"{n} {k}" for k, n in sorted(n_kind.items())) or "none yet"
    recent = sorted(active(facts), key=lambda x: x["updated"], reverse=True)[:RECENT_N]
    router = [
        "# elephant — index",
        "",
        "Router. Derived by `scripts/build-index.py` — do not edit by hand.",
        "Facts are reached through the entity pages that link them, not listed here.",
        "",
        f"- **Entities** → [catalog](/entities/index.md) ({kinds_str})",
        f"- **Open loops** → [board](/tracking/open-loops.md) ({len(open_loops)} open)",
        "- **Log** → [log.md](/log.md)",
        f"- **Counts**: {len(active(facts))} active facts · {len(sources)} sources",
        "",
        "## Recent activity",
        "",
    ]
    if recent:
        for c in recent:
            router.append(f"- {c['updated']} · [{c['description'] or c['title']}]({c['link']})")
    else:
        router.append("_Nothing yet._")
    write("index.md", router)

    # 4. backlinks into entity & source files — trust-aware (see SKILL "Retrieval trust")
    fact_by_link = {c["link"]: c for c in facts}
    HISTORY_STATUS = {"deprecated", "superseded", "done", "dropped"}

    def is_history(r):
        st = str(r["fm"].get("status", "")).lower()
        return st in HISTORY_STATUS

    def marked(r):
        """Prefix ⚠️ for low-confidence or needs-review active items; leave others clean."""
        low = str(r["fm"].get("confidence", "")).lower() == "low"
        review = "needs-review" in as_list(r["fm"].get("tags"))
        label = r["description"] or r["title"]
        item = f"- [{label}]({r['link']})"
        return ("- ⚠️ " + item[2:]) if (low or review) else item

    def history_line(r):
        label = r["description"] or r["title"]
        item = f"- [{label}]({r['link']})"
        # For a superseded fact, point at its successor so the reader sees the current truth.
        for tgt in as_list((r["fm"].get("relations") or {}).get("superseded-by")
                           if isinstance(r["fm"].get("relations"), dict) else None):
            succ = fact_by_link.get(tgt)
            succ_label = (succ["description"] or succ["title"]) if succ else tgt
            item += f" → superseded by [{succ_label}]({tgt})"
            break
        return item

    backlinks = {}
    for c in facts + loops:
        for tgt in as_list(c["fm"].get("entities")) + as_list(c["fm"].get("sources")) + as_list(c["fm"].get("owner")):
            backlinks.setdefault(tgt, []).append(c)
    for c in entities + sources:
        refs = sorted(backlinks.get(c["link"], []), key=lambda x: x["link"])
        active_refs = [r for r in refs if not is_history(r)]
        history_refs = [r for r in refs if is_history(r)]
        block = ["<!-- BEGIN auto-facts -->",
                 "<!-- Regenerated by scripts/build-index.py — do not edit by hand. -->"]
        if active_refs:
            block += ["", "## Related facts", ""]
            block += [marked(r) for r in active_refs]
            block += [""]
        if history_refs:
            block += ["", "### Superseded / deprecated (history)", ""]
            block += [history_line(r) for r in history_refs]
            block += [""]
        block.append("<!-- END auto-facts -->")
        with open(c["path"], encoding="utf-8") as fh:
            text = fh.read()
        if AUTO.search(text):
            with open(c["path"], "w", encoding="utf-8") as fh:
                fh.write(AUTO.sub("\n".join(block), text))

    # 5. manifest.jsonl — ultra-slim triage surface (active facts + open loops)
    def occ(c):
        return str(c["fm"].get("occurred") or c["fm"].get("opened") or c["updated"] or "")

    manifest = []
    for c in sorted(active(facts) + open_loops, key=occ, reverse=True):
        manifest.append(json.dumps({
            "path": c["link"],
            "type": c["type"],
            "desc": c["description"] or c["title"],
            "entities": as_list(c["fm"].get("entities")),
            "tags": as_list(c["fm"].get("tags")),
            "occurred": occ(c),
            "confidence": str(c["fm"].get("confidence", "")),
            "status": c["status"],
        }, ensure_ascii=False, separators=(",", ":")))
    write("manifest.jsonl", manifest)

    print(f"Rebuilt: {len(active(entities))} entities, {len(active(facts))} facts, "
          f"{len(open_loops)} open loops, {len(sources)} sources. "
          f"manifest.jsonl: {len(manifest)} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
