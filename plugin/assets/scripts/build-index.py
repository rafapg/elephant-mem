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

# Windows consoles default to a legacy codepage (cp1252); force UTF-8 on the
# standard streams so printing non-ASCII content (emoji, accented names)
# doesn't raise UnicodeEncodeError. No-op on POSIX / when already UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, "knowledge")
RESERVED = {"index.md", "log.md", "open-loops.md"}
RECENT_N = 12
# Regenerated hub-sharding shard: never a first-class OKF type, so it carries
# no frontmatter and is excluded from concept-scanning / validate-okf.py's
# frontmatter rule (mirrors RESERVED, but by suffix since the basename varies
# per entity/source).
ARCHIVE_SUFFIX = ".facts-archive.md"
HUB_MAX_FACTS_DEFAULT = 50

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
INLINE_LIST = re.compile(r"^\[(.*)\]$")
AUTO = re.compile(r"<!-- BEGIN auto-facts -->.*?<!-- END auto-facts -->", re.DOTALL)

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None
    # Distinct from `yaml = None` set by a caller (tests force it to exercise the
    # fallback on purpose): only a genuinely missing install warrants the warning.
    YAML_MISSING = True
else:
    YAML_MISSING = False


def load_json_config(name):
    """Defensively read a JSON config file at the bundle root. Missing file,
    missing keys, or malformed JSON all fall through to None — callers apply
    their own default (mirrors ingest-audio.py's elephant.json reader)."""
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


VOCAB = load_json_config("vocab.json")


def vocab_set(key, default):
    """Controlled-vocabulary values for `key`, from vocab.json when present
    and well-formed, else `default` — kept byte-identical to the hardcoded
    behavior this replaced so bundles without vocab.json are unaffected."""
    if VOCAB and isinstance(VOCAB.get(key), list):
        return set(str(x) for x in VOCAB[key])
    return set(default)


def hub_max_facts():
    cfg = load_json_config("elephant.json") or {}
    v = cfg.get("index", {}).get("hub_max_facts") if isinstance(cfg.get("index"), dict) else None
    return v if isinstance(v, int) and v > 0 else HUB_MAX_FACTS_DEFAULT


# fact_status / loop_status default lists mirror the exact values the old
# hardcoded HISTORY_STATUS / active() sets covered — see vocab.json for the
# full controlled vocabulary (adds "expired" for loops, used by decay).
FACT_STATUS = vocab_set("fact_status", ["active", "superseded", "deprecated"])
LOOP_STATUS = vocab_set("loop_status", ["open", "done", "dropped"])
FACT_HISTORY_STATUS = FACT_STATUS - {"active"}
LOOP_HISTORY_STATUS = LOOP_STATUS - {"open"}


def unquote(s):
    """Strip matching outer quotes from a value the fallback parser read.

    That parser is lexical, so without this a quoted bundle link stays wrapped in
    literal quotes (`"'/entities/person/x.md'"`) and never matches its target —
    which is how a single unsafe scalar empties an entity hub's auto-facts block.
    Not a YAML unescaper: inner `''` / `\\"` escapes are left alone. Degrading
    less badly is the point; validate-okf.py rule 5 is what actually prevents it.
    """
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" else s


def parse_fm(block, path=None):
    if yaml is not None:
        try:
            data = yaml.safe_load(block) or {}
            if isinstance(data, dict):
                return data
        except Exception as exc:
            # Never silent: a raising block means this file's links and
            # description are about to be misread by the fallback parser.
            where = path or "<frontmatter>"
            print(f"WARNING: {where}: frontmatter is not valid YAML ({exc.__class__.__name__}); "
                  "falling back to the naive parser. Run `validate-okf.py` to localize it.",
                  file=sys.stderr)
    # Minimal fallback parser (no PyYAML installed): handles scalars, inline
    # lists (`key: [a, b]`) and block-sequence lists:
    #   key:
    #     - a
    #     - b
    # Nested mappings (e.g. `relations:`) are NOT supported here and resolve to
    # "" — same as before this fallback grew block-sequence support.
    data = {}
    lines = block.splitlines()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        i += 1
        if not line or line[0] in " \t#" or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if not val:
            items = []
            while i < n:
                nxt = lines[i]
                stripped = nxt.strip()
                if not stripped:
                    i += 1
                    continue
                if nxt[0] in " \t" and stripped.startswith("- "):
                    items.append(unquote(stripped[2:].strip()))
                    i += 1
                    continue
                break
            data[key] = items if items else ""
            continue
        m = INLINE_LIST.match(val)
        if m:
            inner = m.group(1).strip()
            data[key] = [unquote(x.strip()) for x in inner.split(",") if x.strip()] if inner else []
        else:
            data[key] = unquote(val)
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
    if YAML_MISSING:
        # Without PyYAML EVERY file goes through the naive parser, so the damage
        # from an unsafe scalar is bundle-wide rather than per-file. Warn instead
        # of hard-failing: the fallback is a supported path (see tests/test_index.py).
        print("WARNING: PyYAML is not installed — parsing frontmatter with the naive "
              "fallback parser for every file, which cannot read nested mappings and "
              "is quote-lenient. Install it (`pip install pyyaml`) for exact parsing.",
              file=sys.stderr)
    concepts = []
    for path in md_files(BUNDLE):
        if os.path.basename(path) in RESERVED or path.endswith(ARCHIVE_SUFFIX):
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        m = FM.match(text)
        if not m:
            continue
        fm = parse_fm(m.group(1), bundle_link(path))
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
        return [c for c in items if c["status"] not in FACT_HISTORY_STATUS]

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
    HISTORY_STATUS = FACT_HISTORY_STATUS | LOOP_HISTORY_STATUS
    HUB_MAX_FACTS = hub_max_facts()

    def occ(c):
        return str(c["fm"].get("occurred") or c["fm"].get("opened") or c["updated"] or "")

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

    def archive_path_for(entity_path):
        d = os.path.dirname(entity_path)
        base = os.path.basename(entity_path)[:-len(".md")]
        return os.path.join(d, base + ARCHIVE_SUFFIX)

    def write_archive(path, hub_title, hub_link, overflow_active, hist_refs):
        """Sibling shard for a hub past HUB_MAX_FACTS: no frontmatter (see
        ARCHIVE_SUFFIX) — plain markdown, regenerated wholesale every build."""
        lines = [
            f"# Archived facts — {hub_title}",
            "",
            f"Older / superseded facts referencing [{hub_title}]({hub_link}), sharded out of its "
            "inline auto-facts block by `scripts/build-index.py` (hub too large). "
            "Regenerated every build — do not edit by hand.",
            "",
        ]
        if overflow_active:
            lines += ["## Related facts (older)", ""]
            lines += [marked(r) for r in overflow_active]
            lines += [""]
        if hist_refs:
            lines += ["## Superseded / deprecated (history)", ""]
            lines += [history_line(r) for r in hist_refs]
            lines += [""]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).rstrip() + "\n")

    backlinks = {}
    for c in facts + loops:
        for tgt in as_list(c["fm"].get("entities")) + as_list(c["fm"].get("sources")) + as_list(c["fm"].get("owner")):
            backlinks.setdefault(tgt, []).append(c)

    injected = []
    archives_written = set()
    for c in entities + sources:
        refs = sorted(backlinks.get(c["link"], []), key=lambda x: x["link"])
        active_refs = [r for r in refs if not is_history(r)]
        history_refs = [r for r in refs if is_history(r)]

        sharded = len(active_refs) > HUB_MAX_FACTS
        if sharded:
            active_sorted = sorted(active_refs, key=occ, reverse=True)
            inline_active = active_sorted[:HUB_MAX_FACTS]
            overflow_active = active_sorted[HUB_MAX_FACTS:]
        else:
            inline_active = active_refs
            overflow_active = []

        block = ["<!-- BEGIN auto-facts -->",
                 "<!-- Regenerated by scripts/build-index.py — do not edit by hand. -->"]
        if inline_active:
            block += ["", "## Related facts", ""]
            block += [marked(r) for r in inline_active]
            block += [""]
        if not sharded and history_refs:
            block += ["", "### Superseded / deprecated (history)", ""]
            block += [history_line(r) for r in history_refs]
            block += [""]
        if sharded:
            archive_path = archive_path_for(c["path"])
            archive_link = bundle_link(archive_path)
            moved = len(overflow_active) + len(history_refs)
            block += ["", f"→ {moved} older/superseded facts: [archive]({archive_link})", ""]
            write_archive(archive_path, c["title"], c["link"], overflow_active, history_refs)
            archives_written.add(archive_path)
        block.append("<!-- END auto-facts -->")

        with open(c["path"], encoding="utf-8") as fh:
            text = fh.read()
        if AUTO.search(text):
            new_text = AUTO.sub("\n".join(block), text)
        else:
            # No auto-facts marker yet (file created outside the template) —
            # append it so backlinks stop being silently dropped.
            sep = "" if text.endswith("\n") else "\n"
            new_text = text + sep + "\n" + "\n".join(block) + "\n"
            injected.append(c["link"])
        if new_text != text:
            with open(c["path"], "w", encoding="utf-8") as fh:
                fh.write(new_text)

    for label in injected:
        print(f"Injected auto-facts marker: {label}")

    # Idempotent archive cleanup: remove shards from a prior build that this
    # run didn't (re)write (hub shrank below HUB_MAX_FACTS, or was renamed/removed).
    for path in md_files(BUNDLE):
        if path.endswith(ARCHIVE_SUFFIX) and path not in archives_written:
            os.remove(path)

    # 5. manifest.jsonl — ultra-slim triage surface (active facts + open loops)
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
