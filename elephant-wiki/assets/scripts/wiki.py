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
                buf.append(_inline(html.escape(lines[i].lstrip(">").strip())))
                i += 1
            out.append("<blockquote>" + "<br>".join(buf) + "</blockquote>")
            continue
        # lists
        if re.match(r"^\s*[-*]\s+", ln):
            buf = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                item = re.sub(r"^\s*[-*]\s+", "", lines[i])
                buf.append(f"<li>{_inline(html.escape(item))}</li>")
                i += 1
            out.append("<ul>" + "".join(buf) + "</ul>")
            continue
        if re.match(r"^\s*\d+\.\s+", ln):
            buf = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                item = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                buf.append(f"<li>{_inline(html.escape(item))}</li>")
                i += 1
            out.append("<ol>" + "".join(buf) + "</ol>")
            continue
        # blank
        if not ln.strip():
            i += 1
            continue
        # paragraph (gather until blank / block start)
        buf = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|\s*[-*]\s|\s*\d+\.\s|>|```)", lines[i]):
            buf.append(_inline(html.escape(lines[i].strip())))
            i += 1
        out.append("<p>" + "<br>".join(buf) + "</p>")
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
<style>
  :root{--bg:#faf9f7;--panel:#fff;--ink:#1c1a17;--muted:#6b665e;--line:#e6e2da;
        --accent:#7a5b34;--accent-soft:#f0e9de;--chip:#efece6;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
  header{position:sticky;top:0;z-index:5;background:rgba(250,249,247,.92);backdrop-filter:blur(6px);
         border-bottom:1px solid var(--line);padding:.6rem 1rem;display:flex;gap:1rem;align-items:center}
  header .brand{font-weight:700;letter-spacing:.02em;cursor:pointer}
  header .brand span{color:var(--accent)}
  #q{flex:1;max-width:520px;padding:.5rem .7rem;border:1px solid var(--line);border-radius:8px;
     background:#fff;font-size:14px}
  .counts{color:var(--muted);font-size:12.5px;white-space:nowrap}
  main{max-width:960px;margin:0 auto;padding:1.4rem 1rem 4rem}
  .layout{display:grid;grid-template-columns:220px 1fr;gap:1.6rem}
  @media(max-width:720px){.layout{grid-template-columns:1fr}.side{position:static}}
  .side{position:sticky;top:64px;align-self:start;font-size:14px}
  .side h4{margin:.2rem 0 .4rem;text-transform:uppercase;letter-spacing:.06em;font-size:11px;color:var(--muted)}
  .side a{display:flex;justify-content:space-between;padding:.2rem .4rem;border-radius:6px;color:var(--ink)}
  .side a:hover{background:var(--accent-soft);text-decoration:none}
  .side a .n{color:var(--muted);font-size:12px}
  .side a.active{background:var(--accent-soft);color:var(--accent);font-weight:600}
  h1{font-size:1.5rem;margin:.2rem 0 .3rem} h2{font-size:1.05rem;margin:1.4rem 0 .5rem}
  .desc{color:var(--muted);margin:.1rem 0 .8rem}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.7rem .85rem;margin:.5rem 0}
  .card .d{margin:0}
  .meta{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin-top:.4rem;font-size:12px;color:var(--muted)}
  .chip{background:var(--chip);border-radius:999px;padding:.05rem .5rem;font-size:11.5px;color:#524d45}
  .chip.k{background:var(--accent-soft);color:var(--accent)}
  .badge{border-radius:999px;padding:.05rem .5rem;font-size:11px;font-weight:600}
  .b-high{background:#e4f0e4;color:#2f6b34}.b-medium{background:#fdf1dc;color:#93641b}
  .b-low{background:#f6e4e4;color:#8f3d3d}
  .b-superseded,.b-deprecated{background:#eceaf3;color:#5c4b8a}
  .prose{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.2rem 1rem;margin:.6rem 0}
  .prose h1,.prose h2,.prose h3{font-size:1rem;margin:.9rem 0 .4rem}
  .prose code{background:#f2efe9;padding:.05rem .3rem;border-radius:4px;font-size:13px}
  .prose pre{background:#f2efe9;padding:.7rem;border-radius:8px;overflow:auto}
  .prose blockquote{border-left:3px solid var(--line);margin:.5rem 0;padding:.1rem .8rem;color:var(--muted)}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:.5rem}
  .kindcard{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.6rem .8rem}
  .kindcard h3{margin:0 0 .3rem;font-size:.95rem;text-transform:capitalize}
  .back{color:var(--muted);font-size:13px;cursor:pointer;display:inline-block;margin-bottom:.6rem}
  .rel{font-size:13px;margin:.15rem 0}.rel b{color:var(--muted);font-weight:600;text-transform:capitalize}
  .empty{color:var(--muted);padding:2rem 0;text-align:center}
  .filters{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0 1rem}
  .filters button{border:1px solid var(--line);background:#fff;border-radius:999px;padding:.2rem .7rem;
                  font-size:12.5px;cursor:pointer;color:#524d45}
  .filters button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
  .lg{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:.8rem 0;padding:.4rem .5rem}
  .lg:empty{display:none}
  .lg h4{margin:.1rem .3rem .25rem;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
         color:var(--muted);font-weight:600}
  .lg canvas{display:block;width:100%;height:320px}  /* graph.js overrides per node count */
</style>
</head>
<body>
<header>
  <div class="brand" onclick="location.hash='#/'">🐘 <span>elephant</span> wiki</div>
  <input id="q" placeholder="search facts, people, projects, sources…" autocomplete="off">
  <div class="counts" id="counts"></div>
</header>
<main id="app"><div class="empty">loading…</div></main>

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
