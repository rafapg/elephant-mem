#!/usr/bin/env python3
"""Generate a human-navigable static wiki from an elephant-mem bundle.

Reads the bundle's knowledge/ (entities, facts, sources) and emits a local,
zero-server single-page app under <bundle>/wiki-out/. You open
`wiki-out/wiki.html` directly (file://) — no process, no port, nothing running.

Why it works off `file://` with no server: browsers block `fetch()` of local
files (CORS), so NOTHING is fetched. All data is loaded via `<script src>` tags
(which file:// allows), each defining a `window.__…__` global. The heavy fact and
source bodies are sharded by month and injected lazily on navigation, so opening
the page stays fast even on a large bundle — only the slim search/catalog spine
loads eagerly.

The wiki is a DERIVED artifact, like the bundle's own manifest.jsonl: rebuild it
any time from the markdown, which stays the single source of truth. This script
is READ-ONLY over knowledge/ — it never mutates a fact. (`--register` /
`--unregister` do touch elephant.json and .gitignore, and only those.)

It reuses the bundle's own `scripts/build-index.py` frontmatter parser, so a
file parses here exactly as it does when the index is built.

Commands:
  build                 (default) regenerate wiki-out/ from the bundle
  --register            subscribe this wiki to the bundle's post_ingest event
                        (writes elephant.json hooks + gitignores wiki-out/)
  --unregister          remove that subscription
  --bundle <path>       override bundle location (default: the machine pointer
                        ~/.config/elephant-mem/config.json)
  --out <dir>           override output dir (default: <bundle>/wiki-out)

Pure stdlib, Python 3.10+. Cross-platform (explicit UTF-8 I/O).
"""
import argparse
import html
import importlib.util
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

POINTER = os.path.expanduser("~/.config/elephant-mem/config.json")
FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
AUTO_RE = re.compile(r"<!-- BEGIN auto-facts -->.*?<!-- END auto-facts -->", re.DOTALL)


def die(msg):
    print(f"wiki.py: {msg}", file=sys.stderr)
    sys.exit(1)


# Sibling JS assets that ship next to this script and get installed alongside
# it (see install_into_bundle). Both are inlined into WIKI_HTML at build time:
# wiki.js is the SPA, graph.js the local knowledge-graph panel it calls into.
ASSETS = ("graph.js", "wiki.js")


def read_assets(*names):
    """Read sibling asset file(s) from the directory holding this script
    itself (not the CWD) and return their concatenated text. A missing asset
    means an in-bundle copy of wiki.py is stale — re-running the elephant-wiki
    build/register from the plugin recopies the current siblings."""
    here = os.path.dirname(os.path.abspath(__file__))
    parts = []
    for name in names:
        path = os.path.join(here, name)
        if not os.path.exists(path):
            die(f"missing asset {path} — this wiki.py copy is stale (its sibling "
                f"JS assets didn't come along); re-run the elephant-wiki build/"
                f"register from the plugin to refresh the in-bundle copy")
        parts.append(open(path, encoding="utf-8").read())
    return "".join(parts)


# ── bundle resolution ────────────────────────────────────────────────────────

def resolve_bundle(override):
    if not override:
        override = os.environ.get("ELEPHANT_BUNDLE", "")  # set when run as a hook
    if override:
        root = os.path.abspath(os.path.expanduser(override))
    else:
        try:
            with open(POINTER, encoding="utf-8") as fh:
                root = json.load(fh)["bundle_path"]
        except (OSError, ValueError, KeyError):
            die(f"no bundle pointer at {POINTER} — pass --bundle <path>")
        root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(os.path.join(root, "knowledge")):
        die(f"{root} does not look like a bundle (no knowledge/)")
    return root


def load_parser(bundle):
    """Import the bundle's own build-index.py to reuse its frontmatter parser."""
    path = os.path.join(bundle, "scripts", "build-index.py")
    if not os.path.exists(path):
        die(f"bundle has no scripts/build-index.py (needed for parsing): {path}")
    spec = importlib.util.spec_from_file_location("_elephant_build_index", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── markdown → html (minimal, link-rewriting) ────────────────────────────────

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![\*\w])\*([^*\n]+)\*(?![\*\w])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def route_for(target):
    """Rewrite a bundle-absolute link (/entities/x.md) to a hash route (#/entities/x)."""
    t = target.strip()
    if t.startswith("/") and t.endswith(".md"):
        return "#" + t[:-3]
    return t


_SAFE_SCHEMES = ("http:", "https:", "mailto:")


def safe_href(href):
    """A bundle body is third-party text — Slack messages, transcripts, forwarded
    documents — so a link written into one must not be able to carry a script.
    `[x](javascript:…)` rendered straight into an href executes in a page that
    holds the whole knowledge base. Returns None for anything but an http(s)/
    mailto URL, a rewritten hash route, or a scheme-less relative path.

    Browsers ignore whitespace and control characters when reading a scheme, so
    `java\\tscript:` is live where a naive startswith check is not: probe with
    those stripped, and keep the original for the href itself."""
    probe = re.sub(r"[\s\x00-\x1f\x7f]", "", href).lower()
    if not re.match(r"^[a-z][a-z0-9+.\-]*:", probe):
        return href                       # "#/entities/x", "/facts/y.md", "./z"
    return href if probe.startswith(_SAFE_SCHEMES) else None


def _inline(text):
    """Inline markdown on an already HTML-escaped string."""
    def link(m):
        label, target = m.group(1), m.group(2)
        href = safe_href(route_for(target))
        if href is None:
            return label                  # unsafe scheme: keep the words, drop the link
        ext = href.startswith("http://") or href.startswith("https://")
        attr = ' target="_blank" rel="noopener"' if ext else ""
        return f'<a href="{html.escape(href, quote=True)}"{attr}>{label}</a>'

    text = _INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _LINK.sub(link, text)
    text = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", text)
    text = _ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", text)
    # Bare bundle-absolute links not written as markdown, e.g. "[1] /sources/x.md".
    text = re.sub(
        r"(?<![\"\w])(/(?:entities|facts|sources|tracking)/[^\s)]+?\.md)",
        lambda m: f'<a href="{route_for(m.group(1))}">{m.group(1)}</a>',
        text,
    )
    return text


_UL = r"^\s*[-*]\s+"
_OL = r"^\s*\d+\.\s+"


def _soft(line):
    """One line of a paragraph or blockquote, rendered with markdown's soft-break
    rule: a single newline inside a block reflows, it is not a line break.

    Bundle bodies are hard-wrapped prose — a transcript or a summary written at
    72 columns — and joining their lines with <br> baked the source's wrap into
    the page, so a paragraph broke at ~490px inside a 1130px column no matter
    how wide the reader's window was. Only markdown's explicit hard break (two
    trailing spaces) still forces one, which is why the check runs before the
    strip that would erase it."""
    hard = line.rstrip("\r\n").endswith("  ")
    return _inline(html.escape(line.strip())) + ("<br>" if hard else "")


def md_to_html(text):
    """A small, dependency-free markdown renderer for bundle bodies.

    Handles: fenced code, ATX headings, unordered/ordered lists, blockquotes,
    paragraphs, and inline code/bold/italic/links. Not CommonMark-complete —
    just enough for the bundle's own prose, which is simple by construction."""
    text = AUTO_RE.sub("", text).strip()
    if not text:
        return ""
    lines = text.split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        # fenced code
        if ln.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            i += 1  # closing fence
            out.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            continue
        # heading
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(html.escape(m.group(2).strip()))}</h{lvl}>")
            i += 1
            continue
        # blockquote
        if ln.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(_soft(lines[i].lstrip(">")))
                i += 1
            out.append("<blockquote>" + " ".join(buf) + "</blockquote>")
            continue
        # lists — unordered and ordered differ only in the marker and the tag
        kind = next(((p, t) for p, t in ((_UL, "ul"), (_OL, "ol")) if re.match(p, ln)), None)
        if kind:
            pat, tag = kind
            buf = []
            while i < n and re.match(pat, lines[i]):
                item = [re.sub(pat, "", lines[i])]
                i += 1
                # Lazy continuation. A wrapped list item's later lines carry no
                # marker, and without this they fell out of the loop and were
                # emitted as their own paragraph *after* the closing </ul> — so a
                # hard-wrapped list rendered as alternating bullets and orphaned
                # half-sentences. CommonMark reads them as part of the item.
                while (i < n and lines[i].strip()
                       and not re.match(r"^(\s*[-*]\s|\s*\d+\.\s|#{1,6}\s|>|```)", lines[i])):
                    item.append(lines[i])
                    i += 1
                buf.append("<li>" + " ".join(_soft(x) for x in item) + "</li>")
            out.append(f"<{tag}>" + "".join(buf) + f"</{tag}>")
            continue
        # blank
        if not ln.strip():
            i += 1
            continue
        # paragraph (gather until blank / block start)
        buf = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|\s*[-*]\s|\s*\d+\.\s|>|```)", lines[i]):
            buf.append(_soft(lines[i]))
            i += 1
        out.append("<p>" + " ".join(buf) + "</p>")
    return "".join(out)


# ── model building ───────────────────────────────────────────────────────────

def read_fm_and_body(path, parse_fm):
    txt = open(path, encoding="utf-8").read()
    m = FM_RE.match(txt)
    if not m:
        return {}, txt
    # Pass `path` so build-index.py's parse_fm can name the file when a block is
    # unparseable, instead of warning about an anonymous "<frontmatter>".
    return parse_fm(m.group(1), path) or {}, txt[m.end():]


def bundle_id(kroot, path):
    """Bundle-absolute id, matching frontmatter cross-refs: relative to
    knowledge/, leading slash (e.g. /entities/person/foo.md) — NOT relative to
    the bundle root, so it joins against the `entities:`/`sources:` links."""
    return "/" + os.path.relpath(path, kroot).replace(os.sep, "/")


def walk_md(base):
    for dp, _dirs, files in os.walk(base):
        for f in sorted(files):
            if f.endswith(".md") and f != "index.md":
                yield os.path.join(dp, f)


def as_list(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if v in (None, ""):
        return []
    return [str(v).strip()]


def build_model(bundle, bi):
    """Walk knowledge/ and return (entities, facts, sources) dicts keyed by id."""
    K = os.path.join(bundle, "knowledge")
    parse_fm = bi.parse_fm
    entities, facts, sources = {}, {}, {}

    # entities
    ent_base = os.path.join(K, "entities")
    if os.path.isdir(ent_base):
        for p in walk_md(ent_base):
            fm, body = read_fm_and_body(p, parse_fm)
            if fm.get("type") != "entity":
                continue
            eid = bundle_id(K, p)
            kind = os.path.basename(os.path.dirname(p))
            entities[eid] = {
                "id": eid, "kind": kind,
                "title": str(fm.get("title") or os.path.basename(p)[:-3]),
                "desc": str(fm.get("description") or ""),
                "aliases": as_list(fm.get("aliases")),
                "tags": as_list(fm.get("tags")),
                "prose": md_to_html(body),
                "updated": str(fm.get("updated") or ""),
                "factIds": [],
            }

    # facts
    fact_base = os.path.join(K, "facts")
    if os.path.isdir(fact_base):
        for p in walk_md(fact_base):
            fm, body = read_fm_and_body(p, parse_fm)
            if fm.get("type") != "fact":
                continue
            fid = bundle_id(K, p)
            rel = fm.get("relations") if isinstance(fm.get("relations"), dict) else {}
            occurred = str(fm.get("occurred") or fm.get("created") or "")
            facts[fid] = {
                "id": fid,
                "desc": str(fm.get("description") or ""),
                "body": md_to_html(body),
                "entities": as_list(fm.get("entities")),
                "sources": as_list(fm.get("sources")),
                "relations": {k: as_list(v) for k, v in rel.items() if as_list(v)},
                "confidence": str(fm.get("confidence") or ""),
                "status": str(fm.get("status") or "active"),
                "tags": as_list(fm.get("tags")),
                "occurred": occurred,
                "times": fm.get("times_referenced") or 0,
                "sh": occurred[:7] if len(occurred) >= 7 else "undated",
            }

    # sources
    src_base = os.path.join(K, "sources")
    if os.path.isdir(src_base):
        for p in walk_md(src_base):
            fm, body = read_fm_and_body(p, parse_fm)
            if fm.get("type") != "source":
                continue
            sid = bundle_id(K, p)
            occurred = str(fm.get("occurred") or fm.get("ingested") or "")
            sources[sid] = {
                "id": sid,
                "desc": str(fm.get("description") or ""),
                "body": md_to_html(body),
                "kind": str(fm.get("source-kind") or ""),
                "channel": str(fm.get("channel") or ""),
                "resource": str(fm.get("resource") or ""),
                "tags": as_list(fm.get("tags")),
                "occurred": occurred,
                "sh": occurred[:7] if len(occurred) >= 7 else "undated",
                "factIds": [],
            }

    # cross-links: entity/source backlinks from fact references
    for fid, f in facts.items():
        for eid in f["entities"]:
            if eid in entities:
                entities[eid]["factIds"].append(fid)
        for sid in f["sources"]:
            if sid in sources:
                sources[sid]["factIds"].append(fid)

    return entities, facts, sources


# ── emit ─────────────────────────────────────────────────────────────────────

def js_global(varname, value):
    return f"window.{varname} = " + json.dumps(value, ensure_ascii=False, separators=(",", ":")) + ";\n"


def emit(bundle, out, entities, facts, sources):
    # Read the sibling JS assets FIRST, before anything else is written: a
    # stale install (a missing asset) must fail the build before it churns
    # the output directory, not after every data file has already landed.
    graph_js = read_assets("graph.js")
    wiki_js = read_assets("wiki.js")

    data_dir = os.path.join(out, "data")
    os.makedirs(data_dir, exist_ok=True)

    # slim index over facts + sources (entities carry their own slim fields in CORE)
    index = []
    for f in facts.values():
        index.append({"id": f["id"], "t": "f", "desc": f["desc"], "tags": f["tags"],
                      "date": f["occurred"], "sh": f["sh"], "conf": f["confidence"],
                      "status": f["status"], "ents": f["entities"]})
    for s in sources.values():
        index.append({"id": s["id"], "t": "s", "desc": s["desc"], "tags": s["tags"],
                      "date": s["occurred"], "sh": s["sh"], "kind": s["kind"], "channel": s["channel"]})

    # eager CORE: entities (full) + slim index + shard registries
    ent_slim = [{"id": e["id"], "kind": e["kind"], "title": e["title"], "desc": e["desc"],
                 "aliases": e["aliases"], "tags": e["tags"], "prose": e["prose"],
                 "factIds": e["factIds"]} for e in entities.values()]
    fact_shards = sorted({f["sh"] for f in facts.values()})
    src_shards = sorted({s["sh"] for s in sources.values()})
    core = {
        "meta": {
            "generated": datetime.now().isoformat(timespec="seconds"),
            "bundle": os.path.basename(bundle),
            "counts": {"entities": len(entities), "facts": len(facts), "sources": len(sources)},
            "factShards": fact_shards, "sourceShards": src_shards,
        },
        "entities": ent_slim,
        "index": index,
    }
    with open(os.path.join(data_dir, "core.js"), "w", encoding="utf-8") as fh:
        fh.write(js_global("__CORE__", core))

    # lazy shards: full fact/source bodies keyed by id, grouped by month
    fact_by_sh = defaultdict(dict)
    for f in facts.values():
        fact_by_sh[f["sh"]][f["id"]] = {"body": f["body"], "relations": f["relations"],
                                        "sources": f["sources"], "entities": f["entities"],
                                        "times": f["times"]}
    for sh, obj in fact_by_sh.items():
        with open(os.path.join(data_dir, f"facts-{sh}.js"), "w", encoding="utf-8") as fh:
            fh.write(f"window.__SHARD__('f',{json.dumps(sh)}," +
                     json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + ");\n")

    src_by_sh = defaultdict(dict)
    for s in sources.values():
        src_by_sh[s["sh"]][s["id"]] = {"body": s["body"], "resource": s["resource"],
                                       "factIds": s["factIds"]}
    for sh, obj in src_by_sh.items():
        with open(os.path.join(data_dir, f"sources-{sh}.js"), "w", encoding="utf-8") as fh:
            fh.write(f"window.__SHARD__('s',{json.dumps(sh)}," +
                     json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + ");\n")

    # Two separate <script> blocks, graph.js first: it defines window.localGraph,
    # which wiki.js's own initial render() may already need on the very first
    # paint. Keeping them separate means a broken/absent graph.js only costs
    # the local-graph panel — wiki.js still parses and runs on its own, which
    # is the whole point of its `window.localGraph &&` guard.
    page = WIKI_HTML.replace("@@GRAPH_JS@@", graph_js).replace("@@WIKI_JS@@", wiki_js)
    with open(os.path.join(out, "wiki.html"), "w", encoding="utf-8") as fh:
        fh.write(page)

    return len(fact_by_sh) + len(src_by_sh) + 2


# ── register / unregister as a post_ingest subscriber ────────────────────────

def config_path(bundle):
    return os.path.join(bundle, "elephant.json")


def install_into_bundle(bundle):
    """Copy this script AND its sibling JS assets (ASSETS) into
    <bundle>/scripts/ so the hook is self-contained — it keeps working if the
    plugin is moved, updated, or uninstalled (the same way elephant-mem's
    bundle owns its own scripts). Returns the in-bundle path to register."""
    here = os.path.dirname(os.path.abspath(__file__))
    dest = os.path.join(bundle, "scripts", "wiki.py")
    src = os.path.abspath(__file__)
    if os.path.abspath(dest) != src:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        print(f"wiki: installed generator at {dest}")
        for name in ASSETS:
            asset_dest = os.path.join(bundle, "scripts", name)
            shutil.copy2(os.path.join(here, name), asset_dest)
            print(f"wiki: installed asset at {asset_dest}")
    return dest


def refresh_stale_install(bundle):
    """A plain `build` against a bundle that already has a `wiki` post_ingest
    hook refreshes the in-bundle copy of this script and its sibling JS
    assets, running here from the plugin's own (current) copy. Without this,
    an already-registered bundle keeps its pre-fix in-bundle wiki.py forever:
    the NEXT ingestion runs that stale copy, regenerates wiki-out/ without
    whatever changed here, exits 0, and says nothing.

    Reads elephant.json defensively — a missing or unparseable config just
    skips the refresh; it must never fail a plain build."""
    cfgp = config_path(bundle)
    try:
        cfg = json.load(open(cfgp, encoding="utf-8"))
    except (OSError, ValueError):
        return
    arr = (cfg.get("hooks") or {}).get("post_ingest")
    if not isinstance(arr, list):
        return
    if not any(isinstance(h, dict) and h.get("name") == "wiki" for h in arr):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.abspath(here) == os.path.abspath(os.path.join(bundle, "scripts")):
        return  # already running the in-bundle copy itself; nothing stale to refresh
    print("wiki: bundle has a registered post_ingest hook — refreshing its in-bundle copy")
    install_into_bundle(bundle)


def register(bundle, out):
    cfgp = config_path(bundle)
    try:
        cfg = json.load(open(cfgp, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        die(f"cannot read {cfgp}: {exc}")
    script = install_into_bundle(bundle)
    hooks = cfg.setdefault("hooks", {})
    arr = hooks.setdefault("post_ingest", [])
    run = [sys.executable, script, "build", "--bundle", bundle]
    existing = next((h for h in arr if isinstance(h, dict) and h.get("name") == "wiki"), None)
    if existing:
        existing["run"] = run
        action = "updated"
    else:
        arr.append({"name": "wiki", "run": run})
        action = "added"
    with open(cfgp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    _gitignore(bundle, out)
    print(f"wiki: {action} post_ingest subscriber in {cfgp}")
    print(f"      -> {' '.join(run)}")


def unregister(bundle):
    cfgp = config_path(bundle)
    try:
        cfg = json.load(open(cfgp, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        die(f"cannot read {cfgp}: {exc}")
    arr = (cfg.get("hooks") or {}).get("post_ingest") or []
    kept = [h for h in arr if not (isinstance(h, dict) and h.get("name") == "wiki")]
    if len(kept) == len(arr):
        print("wiki: no subscriber to remove")
        return
    cfg["hooks"]["post_ingest"] = kept
    with open(cfgp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"wiki: removed post_ingest subscriber from {cfgp}")


def _gitignore(bundle, out):
    """Ensure wiki-out/ is git-ignored — it's a derived artifact."""
    rel = os.path.relpath(out, bundle).replace(os.sep, "/")
    if rel.startswith(".."):
        return  # output lives outside the bundle; nothing to ignore
    gi = os.path.join(bundle, ".gitignore")
    entry = rel.rstrip("/") + "/"
    lines = []
    if os.path.exists(gi):
        lines = open(gi, encoding="utf-8").read().splitlines()
    if entry not in lines:
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write(("" if not lines or lines[-1] == "" else "\n") + entry + "\n")
        print(f"wiki: gitignored {entry}")


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv):
    ap = argparse.ArgumentParser(prog="wiki.py", description="Generate a static wiki from an elephant-mem bundle.")
    ap.add_argument("command", nargs="?", default="build", choices=["build"], help="what to do (default: build)")
    ap.add_argument("--bundle", default="", help="bundle root (default: machine pointer)")
    ap.add_argument("--out", default="", help="output dir (default: <bundle>/wiki-out)")
    ap.add_argument("--register", action="store_true", help="subscribe to post_ingest and gitignore wiki-out/")
    ap.add_argument("--unregister", action="store_true", help="remove the post_ingest subscription")
    args = ap.parse_args(argv)

    bundle = resolve_bundle(args.bundle)
    out = os.path.abspath(os.path.expanduser(args.out)) if args.out else os.path.join(bundle, "wiki-out")

    if not args.register and not args.unregister:
        refresh_stale_install(bundle)

    if args.unregister:
        unregister(bundle)
        return 0
    if args.register:
        register(bundle, out)
        # fall through: also build so the wiki exists immediately

    bi = load_parser(bundle)
    entities, facts, sources = build_model(bundle, bi)
    nfiles = emit(bundle, out, entities, facts, sources)
    print(f"wiki: {len(entities)} entities · {len(facts)} facts · {len(sources)} sources "
          f"→ {nfiles} data files")
    print(f"wiki: open {os.path.join(out, 'wiki.html')}")
    return 0


# ── the single-page app (constant; all data arrives via data/*.js) ───────────

WIKI_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>elephant · wiki</title>
<script>
  /* Resolve the theme before first paint. Deferring this to the app script
     means a dark-mode reader gets a full white flash on every load. */
  (function(){try{
    var s=localStorage.getItem("elephant-theme");
    if(!s) s=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";
    document.documentElement.setAttribute("data-theme",s);
  }catch(e){document.documentElement.setAttribute("data-theme","light")}})();
</script>
<style>
/* ══════════════════════════════════════════════════════════════════════════
   TOKENS — paste as the FIRST block inside <style>.

   Authored in OKLCH, SHIPPED AS HEX. The oklch() triples in the comments are
   the source of truth; regenerate from those, never nudge a hex by eye.

   WHY HEX AND NOT oklch(): the "hex first, oklch() second" cascade does NOT
   work for a custom property. A custom property accepts almost any token
   stream at parse time, so the oklch() declaration always wins — even on an
   engine that cannot parse it — and the *consuming* declaration then becomes
   invalid-at-computed-value-time and falls back to inherited/initial, not to
   the hex. Worse, getComputedStyle() on an unregistered custom property
   returns the specified token stream verbatim, so graph.js would hand
   ctx.strokeStyle the literal string "oklch(...)"; per the HTML spec an
   unparseable canvas colour is IGNORED and the previous value silently
   persists. Hex always parses, everywhere, as both CSS and canvas colour.

   TWO TEMPERATURES IN ONE LIGHT RAMP:
     b00-b40   SURFACES + BORDERS   hue 78-85, C .0025->.0070, R-B +3..+7
     b45-b100  INK                  hue 262,   C .0070->.0100, R-B -6..-8
   Warm stock, cold ink. The old ramp ran warm text on warm paper at a +13..+15
   split, which is what reads as newsprint. The chroma cut alone kills the cast
   and survives any panel calibration; the temperature split is a refinement
   and is deliberately NOT load-bearing (see `verification`).                */

:root{
  color-scheme:light;

  /* ── surfaces & borders — warm ─────────────────────────────────────── */
  --b00:#fdfcfa;   /* oklch(.992 .0025 85)  rgb(253,252,250)  R-B +3  content pane */
  --b05:#f9f8f6;   /* oklch(.980 .0035 85)  rgb(249,248,246)  R-B +3  raised       */
  --b10:#f4f3ef;   /* oklch(.963 .0045 85)  rgb(244,243,239)  R-B +5  THE RAILS    */
  --b20:#edebe7;   /* oklch(.940 .0050 85)  rgb(237,235,231)  R-B +6  hover, chip  */
  --b25:#e4e3df;   /* oklch(.915 .0050 85)  rgb(228,227,223)  R-B +5  active, soft */
  --b30:#dad8d4;   /* oklch(.882 .0055 82)  rgb(218,216,212)  R-B +6  hairline     */
  --b35:#cbc8c5;   /* oklch(.835 .0060 80)  rgb(203,200,197)  R-B +6  quote bar    */
  --b40:#adaaa6;   /* oklch(.740 .0065 78)  rgb(173,170,166)  R-B +7  GRAPH EDGE
                      2.26:1 pane / 2.08:1 rail. Non-text. Read by graph.js.      */

  /* ── ink — cool ────────────────────────────────────────────────────── */
  --b45:#87898d;   /* oklch(.630 .0070 262) 3.42:1 pane / 3.16:1 rail — --ghost:
                      clears 1.4.11's 3:1 graphical floor, deliberately BELOW the
                      4.5:1 text floor so it can never be reused for a label.     */
  --b50:#717377;   /* oklch(.555 .0075 262) 4.63 / 4.28 — input border, icons      */
  --b60:#5c5f64;   /* oklch(.485 .0085 262) 6.25 / 5.77 — MUTED (all metadata)     */
  --b70:#484a4f;   /* oklch(.410 .0090 262) 8.65 / 7.99 — TEXT-2, graph fact node  */
  --b100:#1b1e23;  /* oklch(.235 .0100 262) 16.30 / 15.05 — INK                    */

  /* ── the one signal ───────────────────────────────────────────────────
     oklch(.465 .122 50). Chroma .122 against the ramp's peak of .0070 = 18x.
     Hue 50 satisfies the accent hue floor h>=46 that keeps it clear of the
     graph's tool(32) and event(8) node hues.                                */
  --accent:#8d4002;        /* 7.14:1 pane · 6.60 rail · 6.15 on b20 · 5.70 on b25 */
  --accent-hover:#6d2c00;  /* oklch(.380 .108 50) 10.19:1 — DARKER on light ground */
  --accent-fill:#fee8db;   /* oklch(.945 .030 50) 1.152:1 vs pane; accent on it 6.20 */
  --accent-ring:rgb(141 64 2 / .18);

  /* ── status. HIGH is the majority case across 4156 facts, so it ships as a
     quiet neutral rather than a green pill or no pill at all. ───────────── */
  --ok-bg:#edebe7;   --ok-fg:#5c5f64;   /* HIGH        5.38:1 */
  --warn-bg:#f4e8cb; --warn-fg:#663f05; /* MEDIUM      7.57:1 */
  --bad-bg:#fee1df;  --bad-fg:#74312e;  /* LOW         7.68:1 */
  --dead-bg:#e8e5fc; --dead-fg:#4a3f73; /* SUPERSEDED  7.58:1 */

  /* ── planes, scrim, elevation ────────────────────────────────────────
     ONE elevation model: hairlines carry every resting surface; --shadow has
     exactly two consumers, .pop and .ov .sheet. The old value was heavy AND
     warm-tinted next to flat hairlined siblings — two models in one screen. */
  --bg-pane:var(--b00);
  --bg-rail:var(--b10);
  --bg-raise:var(--b05);
  --scrim:rgb(27 30 35 / .58);   /* was hsl(var(--accent-h) 8% 8%/.55) — the modal
                                    scrim was tinted with the accent hue.        */
  --shadow:0 1px 2px rgb(27 30 35 / .06),
           0 10px 28px -6px rgb(27 30 35 / .13);
}

/* ══════════════════════════════════════════════════════════════════════════
   DARK — the owner likes this theme. All twelve original ramp values are
   BYTE-FOR-BYTE what ships today. Exactly four things are added or changed,
   each with a reason. The warm/cool split does NOT apply here and that is not
   an inconsistency: in light the paper is the large field and the ink the
   small mark, so a cool mark on a warm field reads crisp; in dark the
   near-black IS the large field, and cooling it makes the warm near-white
   text read as yellow-stained — the exact complaint this redesign exists to
   kill. Dark stays one temperature: warm, amber-lit, untouched.            */
:root[data-theme=dark]{
  color-scheme:dark;

  /* ── unchanged. Do not touch. ─────────────────────────────────────── */
  --b00:#1a1917;  --b05:#201f1c;  --b10:#252420;  --b20:#2b2925;
  --b25:#33302a;  --b30:#3b3831;  --b35:#46423a;  --b40:#5a544a;
  --b50:#837b6d;  --b60:#9e9687;  --b70:#b9b1a3;  --b100:#eae6dd;

  /* CHANGE 1 — the one new ramp step, so --ghost exists in both themes.
     Sits between b40 and b50, in dark's own warm family.                    */
  --b45:#726b5f;  /* 3.13:1 pane / 3.33:1 rail — non-text marks only          */

  /* CHANGE 2 — accent chroma trimmed ~13% and hue stepped away from the
     `tool` node hue (32), so an active nav row and a tool node no longer read
     as the same colour on a page that shows both. Luminance essentially
     unmoved (7.75 -> 7.61), so the theme looks identical.                    */
  --accent:#d2a979;        /* oklch(.760 .080 70)  7.61:1 pane · 8.11 rail · 6.07 b25 */
  --accent-hover:#e7c499;  /* oklch(.840 .070 72) 10.01:1 — LIGHTER on a dark ground  */
  --accent-fill:#432c1a;   /* accent on it 6.01:1                                     */
  --accent-ring:rgb(210 169 121 / .22);

  /* CHANGE 3 — HIGH quieted to match light. The other three keep the fills
     the owner already likes. No cyan anywhere: a confidence scale keeps its
     green/amber/red read.                                                   */
  --ok-bg:#2b2925;   --ok-fg:#9e9687;   /* HIGH        4.95:1 */
  --warn-bg:#35291a; --warn-fg:#d8ab63; /* MEDIUM      6.69:1 */
  --bad-bg:#352220;  --bad-fg:#d99590;  /* LOW         6.18:1 */
  --dead-bg:#272338; --dead-fg:#aa9ce0; /* SUPERSEDED  6.17:1 */

  /* CHANGE 4 — neutral scrim and a pure-black shadow, replacing the
     accent-tinted scrim and the warm-tinted resting shadow.                 */
  --bg-pane:var(--b05); --bg-rail:var(--b00); --bg-raise:var(--b10);
  --scrim:rgb(10 9 8 / .70);
  --shadow:0 1px 2px rgb(0 0 0 / .50),
           0 12px 32px -8px rgb(0 0 0 / .62);
}

/* ══════════════════════════════════════════════════════════════════════════
   SEMANTIC LAYER — theme-independent. A theme stays a swap of the ramp plus
   ~14 literals; there is no second stylesheet.

   THE SIX TOKENS graph.js READS ARE UNCHANGED IN NAME AND MEANING:
     --b70  fact-centre node   --line  hover-label box stroke
     --muted standing labels   --line-soft  de-emphasised edges
     --accent hovered ring     --text  hovered label ink
   --b40 is ADDED to that set as the normal edge colour. It is a ramp token
   already declared in both theme blocks, so tests/test_wiki.py's existing
   regex picks it up with no change to the assertion machinery.

   --faint IS DELETED. Its 15 uses are re-homed: everything that carries
   INFORMATION (dates, counts, placeholders) goes to --muted at 5.77:1 on the
   rail; everything that is a MARK goes to --ghost. The name is the constraint. */
:root{
  --text:var(--b100);    /* body, titles, fact sentences   16.30/15.05 · 13.23/14.11 */
  --text-2:var(--b70);   /* .sub .row, .rel b, blockquote   8.65/ 7.99 ·  7.75/ 8.27 */
  --muted:var(--b60);    /* ALL metadata, dates, counts     6.25/ 5.77 ·  5.62/ 6.00 */
  --ghost:var(--b45);    /* NEVER TEXT. Twisties, tree guides, search glyph, the
                            empty-state mark, disabled icons. 3.16:1 rail (light) /
                            3.33:1 rail (dark) — over 1.4.11's 3:1, under 4.5:1.     */
  --edge:var(--b50);     /* #q border. 4.28:1 rail — well over 1.4.11's 3:1.         */

  --line:var(--b30);        /* structural hairline, graph hover-label stroke */
  --line-soft:var(--b25);   /* pane/rail seams, de-emphasised graph edges    */
  --spine:var(--b30);       /* THE LEDGER SPINE. One token, one job.         */
  --hover:var(--b20);
  --active:var(--b25);

  /* ── space: 4px base ───────────────────────────────────────────────── */
  --sp-1:4px;  --sp-2:8px;  --sp-3:12px; --sp-4:16px;
  --sp-5:24px; --sp-6:32px; --sp-7:40px; --sp-8:64px;

  /* ── radius: a real 3-step scale, replacing the lone unscaled 5px ──── */
  --r-1:4px;   /* chip, badge, kbd, twistie, toggle */
  --r-2:8px;   /* fact row, explorer row, input, pre, canvas */
  --r-3:12px;  /* popover, expanded sheet */

  /* ── type stack. "Inter" is DELETED: dead code after -apple-system on
     macOS, and the FIRST live candidate on Windows/Linux, where two people
     opening the identical offline file saw different type designs depending
     on what else they had installed. system-ui is added so Linux gets its
     real system font rather than a Roboto-if-installed lottery.          */
  --ui:-apple-system,BlinkMacSystemFont,system-ui,"Segoe UI",Roboto,
       "Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}

/* ── CONTRAST LEDGER — every pair measured, pane / rail, light · dark ──────
   role                      target   light          dark
   --text        15px        4.5      16.30 / 15.05  13.23 / 14.11   PASS
   --text-2      13.5px      4.5       8.65 /  7.99   7.75 /  8.27   PASS
   --muted       12px        4.5       6.25 /  5.77   5.62 /  6.00   PASS
   --muted on --active       4.5       4.99           4.49  <- see note
   --ghost       non-text    3.0       3.42 /  3.16   3.13 /  3.33   PASS
   --edge (#q border)        3.0       4.63 /  4.28   3.94 /  4.20   PASS
   --accent      text        4.5       7.14 /  6.60   7.61 /  8.11   PASS
   --accent on --active      4.5       5.70           6.07           PASS
   --accent on --accent-fill 4.5       6.20           6.01           PASS
   badge fg/bg (all four)    4.5       5.38 - 7.68    4.95 - 6.69    PASS
   --b40 graph edge          n/a       2.26 /  2.08   2.20 /  2.34
   NOTE: --muted on --active measures 4.49:1 in dark — one hundredth short.
   That pair occurs only at `.row.on .n`, which is therefore set to --text-2
   (6.19:1 dark, 6.91:1 light) in `css_components`. There is no other place
   in the sheet where --muted sits on --active.                             */

/* ══════════════════════════════════════════════════════════════════════════
   TYPE — paste immediately after the token block.

   SEVEN STEPS across a 19.5px band: 30 / 21 / 16.5 / 15 / 13.5 / 12 / 10.5.
   Gaps 9 / 4.5 / 1.5 / 1.5 / 1.5 / 1.5 — every gap >= 1.5px, the threshold at
   which the eye reads "smaller role" without reading colour. Today: seven
   sizes inside a 4.5px band with four of them doing two unrelated jobs each.
   That, not the typeface, is the weak typography.

   WEIGHTS ARE 400 / 500 / 600 / 700 ONLY. This is not taste. Where the system
   font is not variable or the engine does not expose the axis (Windows Segoe
   UI, most Linux, older engines), CSS font matching resolves a desired weight
   above 500 to the nearest available weight at or above it — so 650 resolves
   to 700 and 550 to 600. Today .sect, .badge, .brand, .pop .t, .prose h1/h2/h3
   AND h1 all render at the IDENTICAL Bold: there is no weight hierarchy above
   400 anywhere in the sheet, and which weights you get differs by OS from the
   same offline file. Six instances of 650 and one of 550 are removed below.

   TRACKING is size-gated, per Inter's own published rule:
     >= 21px  ->  negative, -.008em to -.018em
     <  18px  ->  EXACTLY ZERO. Negative tracking under 18px is the commonest
                  way to make small text look cramped and call it designed.
     caps     ->  +.07em, and caps exist at exactly one size, on one role.
   Today .sect and .badge carry positive tracking at 10.5px while nothing
   above 20px has enough negative — backwards on both ends.

   NUMERALS: font-variant-numeric:tabular-nums is set globally on body (~96%
   support). It is the entire reason the monospace was there. Every date and
   count leaves --mono, which survives only for .prose code / .prose pre /
   .kbd — nothing here is a terminal, a diff, or code.                       */

*{box-sizing:border-box}
body{
  margin:0;background:var(--bg-rail);color:var(--text);
  font:400 15px/1.5 var(--ui);
  font-variant-numeric:tabular-nums;
  font-feature-settings:"kern" 1,"liga" 1,"calt" 1;
  -webkit-font-smoothing:antialiased;   /* macOS-only; safe because the floor is
                                           10.5px at 600 and 12px at 400-500 —
                                           there is no thin small text anywhere */
  text-rendering:optimizeLegibility;
}
a{color:inherit;text-decoration:none}
::selection{background:var(--accent-fill);color:var(--text)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;
               border-radius:var(--r-1)}

/* ── STEP 1 — 30px — the entity title ─────────────────────────────────── */
h1{font-size:30px;line-height:34px;font-weight:700;letter-spacing:-.018em;
   margin:0 0 var(--sp-2);color:var(--text);max-width:var(--measure)}

/* ── STEP 2 — 21px — long titles, prose heads ─────────────────────────── */
h1.long{font-size:21px;line-height:28px;letter-spacing:-.008em}
.prose h1,.prose h2{font-size:21px;line-height:28px;font-weight:600;
   letter-spacing:-.008em;margin:var(--sp-6) 0 var(--sp-2)}

/* ── STEP 3 — 16.5px — the deck, and section heads ─────────────────────
   .desc is a standfirst: it summarises the entity and is read once, so it is
   LARGER than body and set in muted. Today it is 14.5px — smaller than body
   and the same size as a fact sentence, which is exactly why the top of every
   entity page reads as undifferentiated grey.
   .sect shares the size at a different weight AND a different colour tier:
   step 3 means "above body", and 400/muted vs 600/ink are two axes apart.  */
.desc{font-size:16.5px;line-height:26px;font-weight:400;letter-spacing:0;
   color:var(--muted);margin:0 0 var(--sp-5);max-width:var(--measure)}
.prose h3{font-size:16.5px;line-height:24px;font-weight:600;letter-spacing:0;
   margin:var(--sp-5) 0 var(--sp-1)}
/* THE SINGLE BIGGEST CHANGE IN THE SHEET. Was 10.5px/650/uppercase/+.075em/
   --faint. Uppercase+tracking was the ONLY hierarchy device in play, applied
   to five structurally unrelated roles with no other axis varying between
   them — it reads as a crutch because it is one. Now four things separate a
   section head from body: it is bigger, heavier, in full ink, and it has a
   rule and an asymmetric 32-above / 8-below gap.                           */
.sect{display:flex;align-items:center;gap:var(--sp-3);
   font-size:16.5px;line-height:24px;font-weight:600;
   text-transform:none;letter-spacing:0;color:var(--text);
   margin:var(--sp-6) 0 var(--sp-2)}
.sect::after{content:"";flex:1;height:1px;background:var(--line)}

/* ── STEP 4 — 15px — reading text. The fact sentence lives here. ───────
   UP from 14.5px, line-height DOWN from 1.62 to 1.5. 1.62 was borrowed from
   long-form prose conventions this list does not need: a fact is one clause,
   not a paragraph. The fact sentence is now the largest body-weight object in
   the column, which is correct — it is the content.                        */
.item .t{display:block;font-size:15px;line-height:22px;font-weight:400;
   letter-spacing:0;color:var(--text)}
.item .t b{font-weight:600}
.prose{margin:var(--sp-4) 0;font-size:15px;line-height:24px;
   max-width:var(--measure)}
.prose>:first-child{margin-top:0}
.prose p{margin:var(--sp-3) 0}
.prose ul,.prose ol{padding-left:var(--sp-5);margin:var(--sp-2) 0}
.prose li{margin:var(--sp-1) 0}
#q{font:400 15px/1.4 var(--ui)}
.brand{font-size:15px;font-weight:600;letter-spacing:-.006em}
.brand .n{color:var(--text)}
.brand .s{color:var(--muted);font-weight:400}

/* ── STEP 5 — 13.5px — structure and navigation ────────────────────────
   Two roles, split by weight AND colour: rail HEADS are 600/muted, rail ROWS
   are 400/ink. Nothing else lives here.                                     */
.rail{font-size:13.5px;line-height:19px}
.row{font-size:13.5px;line-height:19px;font-weight:400}
.sub .row{font-size:13.5px;color:var(--text-2)}
.kindcard div,.rel,.empty{font-size:13.5px;line-height:19px}
.pop .t{font-size:13.5px;line-height:19px;font-weight:600;display:block;
   margin-bottom:var(--sp-1)}
nav h4,.rblock h4,.kindcard h3,.ov .bar h4{
   margin:var(--sp-5) var(--sp-1) var(--sp-1);
   font-size:13.5px;line-height:19px;font-weight:600;
   text-transform:none;letter-spacing:0;color:var(--muted)}
nav h4:first-child{margin-top:var(--sp-1)}

/* ── STEP 6 — 12px — the apparatus. Every metadatum, and nothing else. ── */
.meta,.chip,.crumb,.more,.lg .cnt{font-size:12px;line-height:17px;
   font-weight:400;letter-spacing:0;color:var(--muted)}
.rel b{font-size:12px;font-weight:600;color:var(--text-2);
   text-transform:capitalize}
/* Every one of these was ui-monospace at 11-11.5px in --faint (2.92:1).
   tabular-nums gives the identical alignment guarantee with no font swap, no
   texture clash, and it lifts them to --muted at 5.77:1 on the rail.        */
.meta .dt,.row .n,.sect .n,.lg .cnt,.kindcard h3 .n,nav h4 .n,.rblock h4 .n{
   font-family:inherit;font-size:12px;font-weight:500;letter-spacing:0;
   font-variant-numeric:tabular-nums;color:var(--muted)}

/* ── STEP 7 — 10.5px — CAPS. One size, one role, one rule in the sheet. ─
   +.07em sits mid-range of the 5-12% convention three independent
   typographers converge on. Today .badge declares NO letter-spacing at
   10.5px all-caps — capital letterforms are drawn to sit beside lowercase
   and are too tight against each other in an all-caps run. Making .badge the
   ONLY uppercase thing on the page is what makes uppercase mean something. */
.badge{font-size:10.5px;line-height:14px;font-weight:600;
   text-transform:uppercase;letter-spacing:.07em}

/* ── the two survivors of --mono ──────────────────────────────────────── */
.prose code{font:400 12.5px/1.4 var(--mono)}
.prose pre{font:400 12.5px/1.55 var(--mono)}
.prose pre code{background:none;padding:0;font-size:inherit}
.kbd{font:500 11px/1 var(--mono)}

/* ── ROLE -> STEP, one-to-one ─────────────────────────────────────────────
   1  30/34/700/-.018  h1
   2  21/28/600/-.008  h1.long, .prose h1, .prose h2
   3  16.5             .desc @400 muted (deck) · .sect @600 ink · .prose h3 @600
   4  15/22-24/400     .item .t, .prose p/li, #q, .brand @600
   5  13.5/19          .rail/.row/.sub .row/.kindcard div/.rel/.empty @400 ink
                       nav h4/.rblock h4/.kindcard h3/.ov .bar h4 @600 muted
                       .pop .t @600
   6  12/17            .meta, .chip, .crumb, .more, .lg .cnt, all counts and
                       dates @500 tabular
   7  10.5/14/600/+.07 .badge, and nothing else, ever                        */

/* ══════════════════════════════════════════════════════════════════════════
   LAYOUT — PART A: base rules. Paste after the type block, BEFORE the
   component block. PART B (all @media) is at the bottom of this field and
   MUST be pasted LAST in the whole sheet — after css_components.

   THE 3200px PROBLEM, root cause: fixed-px rails plus a fixed centred measure
   means the surplus has exactly one destination, the gutter, and it grows
   without limit. Three moves fix it, and none of them is a shell cap:
     1. Rails become fluid clamp() tracks — the graph's share stops falling.
     2. The surplus buys CONTENT: above 1400px each fact's apparatus leaves
        the flow and hangs in a right-hand margin column, so the article block
        goes from 624px to 954px WITHOUT widening the sentence past 72ch.
     3. Above 2400px the ARTICLE track stops being the flexible one and the
        GRAPH becomes it. The article is fixed at --article; the graph column
        takes every remaining pixel, and the canvas is centred inside it with
        a --canvas-max ceiling. Residual width therefore lives INSIDE the
        graph column as canvas margin — the one place emptiness reads as
        canvas rather than as a pane that failed to fill.
   There is no capped shell and no "desk". At no viewport does the article
   sit in a hole.

   Lengths, not percentages, in every grid track: a clamp() with a percentage
   delivered through a custom property resolves against the grid container and
   is lightly travelled; vw resolves against the viewport and, with no shell
   cap, the two are identical here. One less untested mechanism.             */

:root{
  --rail-l:clamp(240px,15vw,320px);
  --rail-r:clamp(300px,26vw,460px);
  --pane-pad:clamp(20px,2.2vw,40px);
  --row-pad:14px;              /* .item horizontal padding; the spine reads it */

  --measure:49ch;              /* 463px == ~66 RUNNING characters. `ch` is the
                                  advance of "0" (9.45px here), not the average
                                  character (7.08px); 66ch measured 88 running
                                  characters on the real corpus, well past 75.  */
  --apparatus:0px;             /* the margin column; opens at 1400px           */
  --appgap:0px;
  --block:calc(var(--measure) + var(--appgap) + var(--apparatus));
  --article:calc(var(--block) + var(--pane-pad)*2);

  --canvas-max:clamp(1100px,46vw,1700px);
}

/* ── the workspace: three independently scrolling panes, as in the app ──── */
.app{display:grid;grid-template-columns:var(--rail-l) minmax(0,1fr) var(--rail-r);
     height:100vh;height:100dvh;overflow:hidden;background:var(--bg-pane)}
/* .app.norail is (0,2,0) and .app is (0,1,0), so this wins at every tier
   regardless of source order — a media query adds no specificity, but a
   compound selector does. */
.app.norail{grid-template-columns:var(--rail-l) minmax(0,1fr)}
.app.norail .rail-r{display:none}
/* On rail-less views (home, browse, kind lists) the content is card grids and
   lists, which genuinely want width. Letting them keep --article would put a
   963px gutter back on a 3200px home page — the original bug, on the one page
   that does not have a graph to absorb it. */
.app.norail .pane-in{width:min(100%,1560px)}

.rail{overflow-y:auto;overscroll-behavior:contain;background:var(--bg-rail);
      padding:var(--sp-3) var(--sp-2) var(--sp-8)}
.rail-l{border-right:1px solid var(--line-soft)}
.rail-r{border-left:1px solid var(--line-soft)}
.pane{overflow-y:auto;overscroll-behavior:contain;background:var(--bg-pane);
      scroll-behavior:smooth}
.pane-in{width:min(100%,var(--article));margin:0 auto;
         padding:var(--sp-6) var(--pane-pad) 30vh}

/* Left rail keeps its structure exactly as shipped: only the tree scrolls, so
   the brand and the search box never leave, and the sticky group rows have a
   scrollport to stick to. DO NOT COLLAPSE THIS INTO .rail. */
.rail-l{display:flex;flex-direction:column;overflow:hidden;padding-bottom:0}
.rail-l .rail-top{flex:none}
.rail-l nav{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;
            padding-bottom:var(--sp-7);margin-right:-4px;padding-right:4px}

/* Blocks that are prose keep the measure; card grids take the full block. */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
      gap:var(--sp-1) var(--sp-5);align-items:start;margin-top:var(--sp-2)}
.crumb{display:flex;align-items:center;gap:var(--sp-1);flex-wrap:wrap;
       margin-bottom:var(--sp-3);max-width:var(--measure)}

/* ── right rail: graph + mentions ──────────────────────────────────────── */
.rblock{margin-bottom:var(--sp-5)}
.rblock:empty{display:none}
.lg:empty{display:none}
.lg .hd{display:flex;align-items:center;gap:var(--sp-1);
        margin:var(--sp-5) var(--sp-1) var(--sp-1)}
.lg h4{margin:0;flex:1;min-width:0}
/* The canvas paints straight onto the rail — no fill, no frame, no padding.
   behind() then resolves to --bg-rail and the graph is EMBEDDED rather than a
   widget floating in a panel. The expanded sheet already does this; the rail
   now matches the thing the owner already likes. */
.lg .box{background:none;border:0;padding:0;
         width:min(100%,var(--canvas-max));margin-inline:auto}
.lg canvas{display:block;width:100%;border-radius:var(--r-2)}
.lg .cnt{margin:var(--sp-2) var(--sp-1) 0}
#mentions{width:min(100%,var(--canvas-max));margin-inline:auto}
/* A list is not a canvas: without this the count sits a full canvas-width
   from the name it belongs to. */
#mentions .row,#mentions .kick{max-width:440px}

/* ══════════════════════════════════════════════════════════════════════════
   COMPONENTS — paste after css_layout PART A and BEFORE css_layout PART B
   (the media queries). Complete replacements for every rule they touch.

   ACCENT BUDGET — seven uses, and this is the whole list. Nothing may join it.
     1 :focus-visible outline            (in css_typography)
     2 .row.on inset 2px bar
     3 #q:focus border + ring
     4 ::selection fill                  (in css_typography)
     5 .chip.k fill and text
     6 .prose a underline, and its hover
     7 the graph's hovered-node ring     (graph.js, with a bg-coloured gap)
   REMOVED FROM: every `a` at rest, .item:hover .t, a.chip:hover, .crumb
   a:hover, .kindcard a:hover, .lg .exp:hover, .sub .row.on, .row.on .n,
   .toggle:hover. Eleven rules moving off the accent. Today it appears in ~14
   rules, which is what made it read as a default theme colour.              */

/* ── THE FACT ROW — the spreadsheet tell ──────────────────────────────────
   Every one of 492 rows draws its own full-width bottom border today. Drop it
   entirely: separation comes from padding plus a hover fill, and above 1400px
   the only hairline left in the region is the vertical ledger spine.        */
.item{display:block;padding:var(--sp-3) var(--row-pad);
      margin:0 calc(var(--row-pad) * -1);
      border-radius:var(--r-2);border-bottom:0;cursor:pointer;color:var(--text)}
.item:hover{background:var(--bg-raise);text-decoration:none;color:var(--text)}
.item:last-child{border-bottom:0}
/* Was `.item:hover .t{color:var(--accent)}` plus `.item .t:hover{...}`. The
   row fill IS the affordance; 492 rows recolouring to accent on hover is how
   the accent stopped meaning anything. The underline is --ghost, not accent. */
.item .t:hover{color:var(--text);text-decoration:underline;
      text-decoration-color:var(--ghost);text-decoration-thickness:1px;
      text-underline-offset:3px}
.meta{display:flex;flex-wrap:wrap;gap:var(--sp-1) var(--sp-2);align-items:center;
      margin-top:var(--sp-1)}
/* Superseded and deprecated facts dim the SENTENCE, not just the badge —
   "don't trust this" should be visible without reading the pill. :has() is
   safe in every engine that ships aspect-ratio, and degrades to no change. */
.item:has(.b-superseded) .t,.item:has(.b-deprecated) .t{color:var(--muted)}

/* ── THE EXPLORER ROW, x543 ───────────────────────────────────────────────
   The active row is now a fill, a weight, and a 2px accent bar. Accent as a
   MARK, not as text colour. Today it recolours the label, the count and the
   nested label — the accent on a surface, a border and a glyph at once.     */
.row{display:flex;align-items:center;gap:var(--sp-1);
     padding:var(--sp-1) var(--sp-2);border-radius:var(--r-1);
     color:var(--text);cursor:pointer;user-select:none}
.row:hover{background:var(--hover);text-decoration:none;color:var(--text)}
.row .n{margin-left:auto;color:var(--muted)}
.row.on{background:var(--active);color:var(--text);font-weight:600;
        box-shadow:inset 2px 0 0 var(--accent)}
.row.on .n{color:var(--text-2)}     /* NOT --muted: 4.49:1 on --active in dark */
.sub .row.on{color:var(--text)}
/* Sticky group headers — keep exactly as shipped, plus a hairline so a stuck
   header separates from the rows sliding under it. */
.grp .row[data-kind]{position:sticky;top:0;z-index:1;background:var(--bg-rail);
        box-shadow:0 1px 0 var(--line-soft)}
.row .tw{width:11px;flex:none;color:var(--ghost);font-size:9px;
         transition:transform .12s}
.row.open .tw{transform:rotate(90deg)}
.sub{margin:0 0 2px var(--sp-2);border-left:1px solid var(--line-soft);
     padding-left:var(--sp-1)}

/* ── CHIP — the tag pill. Neutral, and it STAYS neutral on hover. ───────── */
.chip{display:inline-block;background:var(--hover);border:1px solid transparent;
      border-radius:var(--r-1);padding:1px 7px;color:var(--muted)}
a.chip:hover{background:var(--active);color:var(--text);text-decoration:none}
.chip.k{background:var(--accent-fill);color:var(--accent);font-weight:500}

/* ── BADGE — unmistakably a status object ────────────────────────────────
   Today it shares font-size, weight and uppercase with .sect: two unrelated
   roles, one rule set. Now a filled pill, at the one size where caps exist.
   HIGH ships as a QUIET NEUTRAL: it is the majority case across 4156 facts,
   so a green pill on every default row is stacked saturation, and deleting it
   outright removes confidence triage the owner may rely on. */
.badge{display:inline-block;border-radius:999px;padding:2px 8px}
.b-high{background:var(--ok-bg);color:var(--ok-fg)}
.b-medium{background:var(--warn-bg);color:var(--warn-fg)}
.b-low{background:var(--bad-bg);color:var(--bad-fg)}
.b-superseded,.b-deprecated{background:var(--dead-bg);color:var(--dead-fg)}

/* ── SEARCH — a true plane change: a pane-white field on the b10 rail ───── */
.srch{position:relative;margin:0 2px var(--sp-3)}
.srch svg{position:absolute;left:var(--sp-2);top:50%;transform:translateY(-50%);
          width:16px;height:16px;stroke-width:1.5;color:var(--ghost);
          pointer-events:none}
#q{width:100%;padding:7px 10px 7px 32px;border:1px solid var(--edge);
   border-radius:var(--r-2);background:var(--bg-pane);color:var(--text)}
#q::placeholder{color:var(--muted)}      /* was --faint at 2.92:1 */
#q:focus{outline:none;border-color:var(--accent);
         box-shadow:0 0 0 3px var(--accent-ring)}
.kbd{color:var(--muted);border:1px solid var(--line);border-radius:var(--r-1);
     padding:0 4px;position:absolute;right:var(--sp-1);top:50%;
     transform:translateY(-50%);pointer-events:none}

/* ── LINKS — the biggest change to how the page reads ─────────────────────
   543 explorer rows, every crumb, every kindcard entry and every mention stop
   being coloured. Only real hyperlinks inside user-authored prose keep an
   accent, and only as an underline until hover. */
.crumb{color:var(--muted)}
.crumb a{color:var(--muted)}
.crumb a:hover{color:var(--text)}
.kindcard a{color:var(--text)}
.kindcard a:hover{color:var(--text);text-decoration:underline;
      text-decoration-color:var(--ghost);text-underline-offset:2px}
.prose a{color:var(--text);text-decoration:underline;
      text-decoration-thickness:1px;text-decoration-color:var(--accent);
      text-underline-offset:2px}
.prose a:hover{color:var(--accent-hover);text-decoration-color:currentColor}
.prose code{background:var(--hover);padding:1px 5px;border-radius:var(--r-1)}
.prose pre{background:var(--bg-raise);border:1px solid var(--line);
      border-radius:var(--r-2);padding:var(--sp-3) var(--sp-4);overflow:auto}
.prose blockquote{border-left:2px solid var(--b35);margin:var(--sp-3) 0;
      padding:2px var(--sp-4);color:var(--text-2)}

/* ── EMPTY STATE — unstyled default text today ────────────────────────────
   An oversized em-dash in --ghost: the typographic mark for "nothing here",
   no icon asset, no bytes, and in register with the rest of the sheet. */
.empty{color:var(--muted);padding:var(--sp-8) 0;text-align:center}
.empty::before{content:"—";display:block;font-size:30px;line-height:1;
      color:var(--ghost);margin-bottom:var(--sp-3);letter-spacing:-.02em}

/* ── MISC CHROME ─────────────────────────────────────────────────────────── */
.brand{display:flex;align-items:center;gap:var(--sp-1);cursor:pointer;
       padding:2px var(--sp-1) var(--sp-2)}
.toggle{margin-left:auto;border:0;background:none;color:var(--muted);
        cursor:pointer;padding:3px 5px;border-radius:var(--r-1);
        font-size:14px;line-height:1}
.toggle:hover{background:var(--hover);color:var(--text)}
.lg .exp{border:0;background:none;color:var(--ghost);cursor:pointer;
        padding:2px 5px;border-radius:var(--r-1);font-size:12px;line-height:1}
.lg .exp:hover{background:var(--hover);color:var(--text)}
.rblock .row .n{font-variant-numeric:tabular-nums}
.rblock .kick{border-bottom:1px solid var(--line-soft);margin-bottom:var(--sp-1);
        padding-bottom:var(--sp-1);color:var(--muted)}
.kindcard h3{margin:var(--sp-3) 0 var(--sp-1)}
.kindcard div{padding:1px 0;overflow:hidden;text-overflow:ellipsis;
        white-space:nowrap}
.rel{margin:var(--sp-1) 0}
.more{margin-top:var(--sp-3)}
[hidden]{display:none!important}

/* ── OVERLAYS — the ONLY two places --shadow may appear ─────────────────── */
.pop{position:fixed;z-index:40;width:310px;max-width:calc(100vw - 24px);
     background:var(--bg-raise);border:1px solid var(--line);
     border-radius:var(--r-3);box-shadow:var(--shadow);
     padding:var(--sp-2) var(--sp-3);pointer-events:none;opacity:0;
     transition:opacity .09s}
.pop[data-on]{opacity:1}
.pop .d{color:var(--muted);margin:2px 0 var(--sp-1);
        display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;
        overflow:hidden}
.ov{position:fixed;inset:0;z-index:50;background:var(--scrim);
    display:flex;align-items:center;justify-content:center;padding:2.5vh 2.5vw}
.ov .sheet{background:var(--bg-pane);border:1px solid var(--line);
    border-radius:var(--r-3);box-shadow:var(--shadow);
    /* Must stay LARGER than the rail canvas, which is now 1472x1104 at 3200px:
       a fixed 1400x920 sheet made the expand button shrink the graph on the
       screen that needed it most. Viewport-relative, with the px ceiling only
       binding on displays wider than ~2600px. */
    width:min(2400px,92vw);height:min(1500px,90vh);
    display:flex;flex-direction:column;overflow:hidden}
.ov .bar{display:flex;align-items:center;gap:var(--sp-2);
    padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--line-soft)}
.ov .x{border:0;background:none;color:var(--muted);cursor:pointer;font-size:15px;
    line-height:1;padding:2px var(--sp-1);border-radius:var(--r-1)}
.ov .x:hover{background:var(--hover);color:var(--text)}
.ov .lg{flex:1;min-height:0;display:flex;flex-direction:column;margin:0}
.ov .lg .hd,.ov .lg .cnt{display:none}
.ov .lg .box{flex:1;min-height:0;border:0;background:none;padding:0;
    width:100%;aspect-ratio:auto;max-height:none}
.ov .lg canvas{height:100%!important;border-radius:0}

/* ══════════════════════════════════════════════════════════════════════════
   LAYOUT — PART B: ALL MEDIA QUERIES.

   *** THIS BLOCK MUST BE THE LAST THING IN THE <style> STRING. ***

   A media query adds NO specificity, so a responsive block placed above the
   base rules it means to override simply loses to them. This codebase has
   already shipped that bug once — the phone layout went out with the rail
   still a centred column. Two assertions in tests/test_wiki.py enforce the
   ordering from both ends: "every component rule is declared before the first
   @media block" and "nothing but media queries follows the first @media
   block". They are named rather than cited by line, because a line number in
   a comment is stale the moment anything above it moves.

   Emitted ascending, then the two descending legacy tiers, so no two blocks
   that can both match ever contradict each other.

   SIX NAMED QA CHECKPOINTS: 860 · 1180 · 1400 · 1700 · 2000 · 2400.        */

/* ══ WHAT THE USER ACTUALLY SEES — measured, 1ch = 0.55em @15px = 8.25px ══
 W      railL  graphCol  article  gutter  measure      canvas      area   share
 1181    240      307      596      19   544px 66.0ch   275x300    1.0x   23.3%
 1440    240      374      826       0   538px 65.2ch   342x306    1.3x   23.8%
 1700    255      544      843      29   544px 66.0ch   512x384    2.4x   30.1%
 1920    288      614      848      85   544px 66.0ch   582x437    3.1x   30.3%
 2000    300      640      954      53   594px 72.0ch   608x456    3.4x   30.4%
 2400    320     1126      954       0   594px 72.0ch  1094x820   11.1x   45.6%
 3200    320     1926      954       0   594px 72.0ch  1472x1104  20.0x   46.0%  <- owner
 3840    320     2566      954       0   594px 72.0ch  1700x1275  26.7x   44.3%

 "area" is canvas area against today's 278x292 = 81,176px². "share" is canvas
 width as a fraction of viewport width; today it is 19.9% at 1440 and 8.9% at
 3200. "gutter" is the empty pane margin each side of the article block;
 today it is 62px at 1440, 302px at 1920, 942px at 3200 and 1262px at 3840.

 TWO INVARIANTS, and they are the deliverable:
   · Pane gutter never exceeds 85px at any viewport, and is exactly 0 at every
     viewport >= 2400px. (Today: 942px at 3200.)
   · The canvas never falls below 23% of viewport width. (Today: 8.9%.)
 At 3200px the distance from the article's right edge to the canvas's left
 edge is 227px, of which 211px is canvas margin inside the graph column.
 Today it is ~950px of empty pane. At 3840px the canvas margin rises to 417px
 per side — that is this design's honest ceiling, and it is inside the graph
 column, which is the least harmful place for it.                            */


/* ── 1400px — the apparatus column and the ledger spine appear ────────────
   Gated at 1400, NOT 1480: with fluid rails the centre track is 826px at
   1440px against an 831px article block, so the device is available on the
   commonest desktop width and in every screenshot. Below this the fact row
   reverts to a stacked block with a soft hairline. */
@media(min-width:1400px){
  :root{--apparatus:200px;--appgap:24px}
  .item{display:grid;
        grid-template-columns:var(--measure) var(--apparatus);
        column-gap:var(--appgap);align-items:start;
        position:relative;border-bottom:0}
  .item>.t{grid-column:1;min-width:0;overflow-wrap:break-word}
  /* Wrapping rows, NOT a strict column: with up to eight tags a column ran
     nine lines deep beside a three-line sentence, and the row height came
     from the apparatus instead of the content. */
  .item>.meta{grid-column:2;margin-top:2px;flex-flow:row wrap;
              align-items:flex-start;gap:var(--sp-1)}
  .item.flat{display:block}
  /* THE LEDGER SPINE. One continuous 1px hairline in the gutter between the
     sentence column and the apparatus column, replacing 492 full-width
     horizontal rules with one vertical one.
     It is a positioned ::after, NOT a background-position gradient: it is
     anchored LEFT off the same two tokens that size the grid tracks, so the
     line and the columns cannot desync independently, and anchoring left
     rather than right means it tracks the columns even where .item is much
     wider than measure+gap+apparatus (the .norail views).
     Adjacent .item elements carry ZERO vertical margin, so consecutive
     padding boxes abut exactly and the line is genuinely unbroken. If you
     ever add margin to .item, the spine breaks visibly — that is the guard. */
  .item::after{content:"";position:absolute;top:0;bottom:0;width:1px;
        left:calc(var(--measure) + var(--appgap)/2 + var(--row-pad));
        background:var(--spine)}
  .item.flat::after{content:none}
}

/* ── 1700px — the graph is promoted from a strip to a panel ───────────────
   The rail roughly doubles and the canvas becomes aspect-driven. Below this
   the canvas height comes from graph.js's node-count formula; above it the
   box has a definite height from aspect-ratio and `height:100%!important`
   overrides the inline value — the same mechanism the 1180px tier already
   uses today. A tall thin canvas would be wasted: graph.js derives the star
   radius from min(H,W)/2, so the box has to stay roughly square. */
@media(min-width:1700px){
  :root{--rail-r:clamp(460px,32vw,860px)}
  .lg .box{aspect-ratio:4/3;max-height:calc(100dvh - 220px)}
  .lg canvas{height:100%!important}
}

/* ── 2000px — the measure earns its last six characters ─────────────────── */
@media(min-width:2000px){
  :root{--measure:54ch;--apparatus:248px;--appgap:32px}   /* ~72 running chars */
}

/* ── 2400px — THE TRACK INVERSION. This is the 3200px fix. ────────────────
   The article stops being the flexible track and becomes a fixed one; the
   graph column becomes the 1fr. Everything above 2400px is spent on canvas,
   and what the canvas does not take becomes canvas margin inside the graph
   column, never pane gutter. */
@media(min-width:2400px){
  .app{grid-template-columns:var(--rail-l) var(--article) minmax(480px,1fr)}
}

/* ── 1180px and below — unchanged in behaviour, updated in numbers ────────
   The rail is too narrow for a graph, so it becomes a bounded band beneath
   the reading pane. The explicit grid rows matter: with the default 1fr each,
   the band took half the viewport and left the article four visible lines. */
@media(max-width:1180px){
  :root{--rail-r:0px;--apparatus:0px;--appgap:0px}
  .app{grid-template-columns:var(--rail-l) minmax(0,1fr);
       grid-template-rows:minmax(0,1fr) auto}
  .app.norail{grid-template-rows:minmax(0,1fr)}
  .app.norail .pane-in{width:min(100%,var(--article))}
  .rail-l{grid-row:1/span 2}
  .rail-r{grid-column:2;grid-row:2;max-height:40vh;border-left:0;
          border-top:1px solid var(--line-soft);
          padding:var(--sp-1) var(--pane-pad) var(--sp-4);
          display:flex;gap:var(--sp-5);flex-wrap:wrap;align-items:flex-start}
  .rail-r>*{flex:1 1 240px;min-width:0;margin-bottom:0}
  .lg .box{aspect-ratio:auto;max-height:none}
  .rail-r .lg canvas{max-height:min(34vh,320px);height:auto!important}
  .item{display:block}
  .item+.item{border-top:1px solid var(--line-soft)}
  .item::after{content:none}
}

/* ── 860px and below — the panes stop being panes and the document scrolls
   as one page. The explorer keeps its own bounded scroll: at full height an
   open group of 184 orgs pushed the article three screens down. */
@media(max-width:860px){
  :root{--pane-pad:16px}
  .app,.app.norail{display:block;height:auto;overflow:visible}
  .pane{overflow:visible;height:auto}
  .rail{height:auto}
  .rail-l{flex-direction:row;flex-wrap:wrap;align-items:center;gap:var(--sp-2);
          overflow:visible;border-right:0;
          border-bottom:1px solid var(--line-soft);padding-bottom:var(--sp-3)}
  .rail-l .rail-top{flex:1 1 100%;display:flex;gap:var(--sp-3);align-items:center}
  .rail-l .rail-top .brand{padding-bottom:0}
  .rail-l .rail-top .srch{flex:1;margin:0}
  .rail-l nav{flex:1 1 100%;max-height:34vh;overflow-y:auto;
              padding-bottom:var(--sp-1);margin-right:0;padding-right:0}
  .pane-in{padding:var(--sp-5) var(--pane-pad) var(--sp-8)}
  .app.norail .pane-in{width:100%}
  .rail-r{max-height:none;display:block;padding:var(--sp-1) var(--pane-pad) var(--sp-6)}
  .rail-r>*{margin-bottom:var(--sp-4)}
  .rail-r .lg canvas{max-height:none}
}
</style>
</head>
<body>
<div class="app">
  <aside class="rail rail-l">
    <div class="rail-top">
      <div class="brand" id="brand">🐘 <span class="n">elephant</span> <span class="s">wiki</span>
        <button class="toggle" id="theme" title="Toggle light / dark" aria-label="Toggle light / dark"></button>
      </div>
      <div class="srch">
        <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" fill="none"
             stroke="currentColor" stroke-width="1.7"
             stroke-linecap="round"><circle cx="6.6" cy="6.6" r="4.4"/><path d="M10 10l3.6 3.6"/></svg>
        <!-- A placeholder is not an accessible name, and it disappears the moment
             the user types: a screen reader announced this as an unnamed text
             input. The magnifier beside it is aria-hidden decoration. -->
        <input id="q" aria-label="Search the wiki"
               placeholder="Search…" autocomplete="off" spellcheck="false">
        <span class="kbd" id="kbd">/</span>
      </div>
    </div>
    <nav id="nav"></nav>
  </aside>
  <main class="pane" id="pane"><div class="pane-in" id="app"><div class="empty">loading…</div></div></main>
  <aside class="rail rail-r" id="railr">
    <div class="lg rblock" id="lg"></div>
    <div class="rblock" id="mentions"></div>
  </aside>
</div>
<div class="pop" id="pop" hidden></div>
<div id="ovhost"></div>

<script src="data/core.js"></script>
<script>
@@GRAPH_JS@@
</script>
<script>
@@WIKI_JS@@
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
