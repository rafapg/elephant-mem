#!/usr/bin/env python3
"""Time-first digest over the bundle — the "am I missing anything?" engine.

Unlike `query` (entity-first), this filters facts and open-loops by a TIME
WINDOW plus optional channel / tag / entity, reading only frontmatter (cheap —
no bodies, no embeddings). It answers things like:

  "everything relevant to me in Slack in the last 2 days"
  python3 scripts/briefing.py --days 2 --channel slack --entity jane-doe

  "what was decided in the team's meetings last week"
  python3 scripts/briefing.py --since 2026-06-16 --until 2026-06-22 \\
      --channel meeting --tag decision

Time is filtered on `occurred` (when it happened), falling back to `created`
(ingestion date) when a file has no `occurred`. Channel is resolved by joining a
fact to its `sources` and reading each source's `channel`.
"""
import argparse
import datetime
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
ARCHIVE_SUFFIX = ".facts-archive.md"  # regenerated hub shard — no frontmatter, not a fact/open-loop
FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
INLINE_LIST = re.compile(r"^\[(.*)\]$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None
    YAML_MISSING = True  # see build-index.py: distinct from a caller forcing None
else:
    YAML_MISSING = False


def load_vocab():
    path = os.path.join(ROOT, "vocab.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


VOCAB = load_vocab()


def vocab_set(key, default):
    if VOCAB and isinstance(VOCAB.get(key), list):
        return set(str(x) for x in VOCAB[key])
    return set(default)


# Kept byte-identical to the hardcoded values this replaced when vocab.json is
# absent, so bundles without it behave exactly as before.
TRACKED_TYPES = vocab_set("type", ["entity", "fact", "open-loop", "source"]) - {"entity", "source"}
FACT_HISTORY_STATUS = vocab_set("fact_status", ["active", "superseded", "deprecated"]) - {"active"}


def unquote(s):
    """Strip matching outer quotes from a fallback-parsed value — see the fuller
    rationale on build-index.py's unquote(). Not a YAML unescaper."""
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" else s


def parse_fm(block, path=None):
    if yaml is not None:
        try:
            d = yaml.safe_load(block) or {}
            if isinstance(d, dict):
                return d
        except Exception as exc:
            print(f"WARNING: {path or '<frontmatter>'}: frontmatter is not valid YAML "
                  f"({exc.__class__.__name__}); falling back to the naive parser. "
                  "Run `validate-okf.py` to localize it.", file=sys.stderr)
    # Minimal fallback parser (no PyYAML installed): handles scalars, inline
    # lists (`key: [a, b]`) and block-sequence lists (`key:` then `  - item`).
    # Nested mappings (e.g. `relations:`) are NOT supported and resolve to "".
    d = {}
    lines = block.splitlines()
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        i += 1
        if not ln or ln[0] in " \t#" or ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        k, v = k.strip(), v.strip()
        if not v:
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
            d[k] = items if items else ""
            continue
        m = INLINE_LIST.match(v)
        d[k] = ([unquote(x.strip()) for x in m.group(1).split(",") if x.strip()]
                if m.group(1).strip() else []) if m else unquote(v)
    return d


def as_list(v):
    if v is None:
        return []
    return [str(x).strip() for x in v] if isinstance(v, list) else ([str(v).strip()] if str(v).strip() else [])


def to_date(v):
    if not v:
        return None
    m = DATE.search(str(v))
    return datetime.date.fromisoformat(m.group(0)) if m else None


def load():
    if YAML_MISSING:
        print("WARNING: PyYAML is not installed — parsing frontmatter with the naive "
              "fallback parser for every file. Install it (`pip install pyyaml`) for "
              "exact parsing.", file=sys.stderr)
    items = []
    for dp, _d, files in os.walk(BUNDLE):
        for f in files:
            if not f.endswith(".md") or f in RESERVED or f.endswith(ARCHIVE_SUFFIX):
                continue
            p = os.path.join(dp, f)
            with open(p, encoding="utf-8") as fh:
                m = FM.match(fh.read())
            if not m:
                continue
            link = "/" + os.path.relpath(p, BUNDLE).replace(os.sep, "/")
            fm = parse_fm(m.group(1), link)
            fm["_link"] = link
            items.append(fm)
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--days", type=int, help="window = last N days (occurred >= today-N)")
    ap.add_argument("--channel", help="substring match against the source channel")
    ap.add_argument("--tag")
    ap.add_argument("--entity", help="entity slug, e.g. jane-doe")
    ap.add_argument("--kind", choices=["fact", "open-loop", "all"], default="all")
    ap.add_argument("--include-superseded", action="store_true",
                    help="include deprecated/superseded facts (marked as history); hidden by default")
    ap.add_argument("--min-confidence", choices=["low", "medium", "high"], default="low",
                    help="drop rows below this confidence (default low = show all)")
    args = ap.parse_args()

    CONF_RANK = {"low": 0, "medium": 1, "high": 2}
    min_rank = CONF_RANK[args.min_confidence]

    today = datetime.date.today()
    until = to_date(args.until) or today
    if args.days is not None:
        since = today - datetime.timedelta(days=args.days)
    else:
        since = to_date(args.since) or datetime.date.min

    items = load()
    sources = {i["_link"]: i for i in items if i.get("type") == "source"}

    def channel_of(fm):
        chans = [sources.get(s, {}).get("channel", "") for s in as_list(fm.get("sources"))]
        return [c for c in chans if c]

    def event_date(fm):
        return to_date(fm.get("occurred")) or to_date(fm.get("opened")) or to_date(fm.get("created"))

    def is_history(fm):
        return str(fm.get("status", "")).lower() in FACT_HISTORY_STATUS

    facts, loops = [], []
    hidden_superseded = 0
    for fm in items:
        t = fm.get("type")
        if t not in TRACKED_TYPES:
            continue
        if args.kind != "all" and t != args.kind:
            continue
        ed = event_date(fm)
        if ed is None or not (since <= ed <= until):
            continue
        if args.tag and args.tag not in as_list(fm.get("tags")):
            continue
        if args.entity:
            ents = as_list(fm.get("entities")) + as_list(fm.get("owner"))
            if not any(e.endswith(f"/{args.entity}.md") for e in ents):
                continue
        if args.channel:
            if not any(args.channel.lower() in c.lower() for c in channel_of(fm)):
                continue
        if t == "fact":
            if is_history(fm) and not args.include_superseded:
                hidden_superseded += 1
                continue
            conf = str(fm.get("confidence", "")).lower()
            if CONF_RANK.get(conf, 0) < min_rank:
                continue
            facts.append((ed, fm))
        else:
            loops.append((ed, fm))

    flt = []
    if args.channel: flt.append(f"channel~{args.channel}")
    if args.tag: flt.append(f"tag={args.tag}")
    if args.entity: flt.append(f"entity={args.entity}")
    print(f"# Briefing {since}..{until}" + (f"  [{', '.join(flt)}]" if flt else ""))
    print(f"# {len(facts)} fact(s), {len(loops)} open-loop(s)\n")

    CONF_SHORT = {"low": "low", "medium": "med", "high": "high"}

    if args.kind != "open-loop":
        print(f"## Facts ({len(facts)})")
        for ed, fm in sorted(facts, key=lambda x: x[0], reverse=True):
            ch = ",".join(channel_of(fm)) or "?"
            conf = str(fm.get("confidence", "")).lower()
            review = "needs-review" in as_list(fm.get("tags"))
            hist = " [history]" if is_history(fm) else ""
            mark = "⚠️ " if (conf == "low" or review) else ""
            clabel = CONF_SHORT.get(conf, "?")
            print(f"- {mark}{ed} [{clabel}]{hist} ({ch}) {fm.get('description','')}  {fm['_link']}")
        if hidden_superseded and not args.include_superseded:
            print(f"\n_({hidden_superseded} superseded/deprecated fact(s) hidden "
                  f"— pass --include-superseded to show)_")
        print()
    if args.kind != "fact":
        print(f"## Open loops ({len(loops)})")
        for ed, fm in sorted(loops, key=lambda x: x[0], reverse=True):
            print(f"- {ed} [{fm.get('status','open')}] {fm.get('description','')}  {fm['_link']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
