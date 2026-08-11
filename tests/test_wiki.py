#!/usr/bin/env python3
"""Standalone test suite for elephant-wiki's `assets/scripts/wiki.py`.

Covers the generator (build produces the SPA from a bundle, ids match the
bundle-absolute convention, fact→entity cross-links resolve), the self-contained
registration (`--register` copies the generator into the bundle, subscribes to
post_ingest, and gitignores wiki-out/), and — the payoff — an INTEGRATION check
that the whole chain works: after registering, firing elephant-mem's
`run-hooks.py post_ingest` regenerates the wiki with no manual step.

Pure stdlib, Python 3.10+, mirroring tests/test_hooks.py's conventions: a
throwaway bundle in a tempdir, subprocess calls into the real scripts, PASS/FAIL
per check, exit 0 only if every check passes. PyYAML may be absent (as in CI):
the fixtures use inline lists the fallback parser handles, and no check depends
on nested-mapping (`relations`) parsing.

Also covers the wiki's split-out JS assets (`wiki.js`/`graph.js`): they inline
into `wiki.html` untouched by any `<script src>` to a local file, a missing one
fails the build loudly (against a COPY of the scripts, never the real repo
files), `--register` copies every asset alongside `wiki.py`, and the eager
entity↔fact adjacency the local-graph panel depends on lands in `core.js`. A
`node --check` syntax pass over each asset runs only when node is on PATH.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Force UTF-8 stdio: Windows consoles default to cp1252, which can't encode the
# non-ASCII characters (→, —, …) used in check labels — printing them would
# raise UnicodeEncodeError and fail the suite. Mirrors the bundle scripts.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI = REPO_ROOT / "elephant-wiki" / "assets" / "scripts" / "wiki.py"
BUILD_INDEX = REPO_ROOT / "plugin" / "assets" / "scripts" / "build-index.py"
RUN_HOOKS = REPO_ROOT / "plugin" / "assets" / "scripts" / "run-hooks.py"

checks = []


def record(label, passed, detail=""):
    checks.append((label, passed))
    print(f"[{len(checks):2d}] {'PASS' if passed else 'FAIL'} — {label}")
    if detail and not passed:
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    return passed


def make_bundle(root):
    """A minimal but valid bundle: scripts + one entity, fact, and source."""
    b = root / "bundle"
    (b / "scripts").mkdir(parents=True)
    (b / "state").mkdir()
    (b / "knowledge" / "entities" / "person").mkdir(parents=True)
    (b / "knowledge" / "facts").mkdir(parents=True)
    (b / "knowledge" / "sources" / "2026-07").mkdir(parents=True)
    shutil.copy2(BUILD_INDEX, b / "scripts" / "build-index.py")
    shutil.copy2(RUN_HOOKS, b / "scripts" / "run-hooks.py")
    (b / "elephant.json").write_text(json.dumps({"owner": {"name": "T", "slug": "t"}}), encoding="utf-8")

    (b / "knowledge" / "entities" / "person" / "alice.md").write_text(
        "---\ntype: entity\nkind: person\ntitle: Alice\n"
        "description: A test person.\naliases: [Ali]\ntags: [team]\n---\n\n"
        "Alice is a person used in tests.\n", encoding="utf-8")
    (b / "knowledge" / "facts" / "f1.md").write_text(
        "---\ntype: fact\ndescription: Alice shipped the widget on 2026-07-10.\n"
        "entities: [/entities/person/alice.md]\n"
        "sources: [/sources/2026-07/s1.md]\n"
        "confidence: high\nstatus: active\ntags: [shipping]\noccurred: 2026-07-10\n---\n\n"
        "Alice shipped the widget.\n\n**Why it matters / context:** it unblocked launch.\n",
        encoding="utf-8")
    (b / "knowledge" / "sources" / "2026-07" / "s1.md").write_text(
        "---\ntype: source\ndescription: Standup notes 2026-07-10.\n"
        "source-kind: note\nchannel: meeting\noccurred: 2026-07-10\ntags: [standup]\n---\n\n"
        "Notes from the standup.\n", encoding="utf-8")
    return b


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *[str(a) for a in args]],
                          capture_output=True, text=True, encoding="utf-8")


def load_core(out):
    txt = (out / "data" / "core.js").read_text(encoding="utf-8")
    return json.loads(txt[txt.index("=") + 1:].rstrip().rstrip(";"))


_SCRIPT_BLOCK_RE = re.compile(r"<script>\n(.*?)\n</script>", re.DOTALL)


def inline_script_blocks(html_txt):
    """The bare (no-attribute) inline <script>…</script> bodies in wiki.html,
    in document order — i.e. the two asset blocks, not the <script src=…>
    tag that loads data/core.js."""
    return _SCRIPT_BLOCK_RE.findall(html_txt)


def main():
    root = Path(tempfile.mkdtemp(prefix="elephant-wiki-"))
    try:
        _run(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nSummary\n-------")
    n_pass = sum(1 for _, p in checks if p)
    for label, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL':4s}  {label}")
    print(f"\n{n_pass}/{len(checks)} checks passed.")
    return 0 if n_pass == len(checks) and checks else 1


def _run(root):
    b = make_bundle(root)
    out = b / "wiki-out"
    assets_dir = WIKI.parent  # elephant-wiki/assets/scripts/: wiki.py + its JS siblings

    # 1. build
    r = run(WIKI, "build", "--bundle", b, "--out", out)
    record("build exits 0", r.returncode == 0, r.stdout + r.stderr)
    record("wiki.html written", (out / "wiki.html").exists())
    record("data/core.js written", (out / "data" / "core.js").exists())

    core = load_core(out) if (out / "data" / "core.js").exists() else {"entities": [], "index": []}
    html_txt = (out / "wiki.html").read_text(encoding="utf-8") if (out / "wiki.html").exists() else ""

    # 2. ids follow the bundle-absolute convention (/entities/…, NOT /knowledge/…)
    alice = next((e for e in core["entities"] if e["title"] == "Alice"), None)
    record("entity id is bundle-absolute (/entities/…)",
           bool(alice) and alice["id"] == "/entities/person/alice.md",
           alice["id"] if alice else "no Alice")

    # 3. fact→entity cross-link resolved (the bug the browser test caught)
    record("fact backlinks onto its entity",
           bool(alice) and "/facts/f1.md" in alice["factIds"],
           alice["factIds"] if alice else "")

    # 4. the reverse edge: the fact's own index row carries ITS entity ids.
    # graph.js's model() walks BOTH directions (entity.factIds and row.ents) —
    # if this half regresses, the local-graph panel silently draws nothing.
    fact_row = next((r_ for r_ in core["index"] if r_["t"] == "f"), None)
    record("fact index row carries its entity ids (fact→entity adjacency)",
           bool(fact_row) and "/entities/person/alice.md" in (fact_row.get("ents") or []),
           fact_row)

    # 5. index carries the fact and the source
    types = {r_["t"] for r_ in core["index"]}
    record("index has a fact row", "f" in types)
    record("index has a source row", "s" in types)

    # 6. a fact shard exists with the SHARD contract
    shard = out / "data" / "facts-2026-07.js"
    record("month shard written with __SHARD__ contract",
           shard.exists() and shard.read_text(encoding="utf-8").startswith("window.__SHARD__('f',"),
           "missing/!SHARD")

    # 7. the split-out JS assets land INSIDE wiki.html, not as a <script src> to
    # a local file — the page must stay self-contained apart from data/.
    src_refs = re.findall(r'<script\s+src="([^"]+)"', html_txt)
    record("localGraph entry point inlined into wiki.html", "window.localGraph = function" in html_txt)
    record("wiki.js app code inlined into wiki.html", "titleOfEnt" in html_txt)
    record("no <script src> to a local .js file (only data/*.js)",
           bool(src_refs) and all(s.startswith("data/") for s in src_refs), src_refs)

    # 7b. the two assets land in SEPARATE <script> blocks (fix: one shared
    # block meant a graph.js typo blanked the whole page) — graph.js first,
    # since it must define window.localGraph before wiki.js's load-time
    # render can hit an entity page.
    blocks = inline_script_blocks(html_txt)
    record("wiki.html carries exactly two inline <script> blocks", len(blocks) == 2, len(blocks))
    if len(blocks) == 2:
        record("first inline block is graph.js (defines window.localGraph)",
               "window.localGraph = function" in blocks[0] and "titleOfEnt" not in blocks[0])
        record("second inline block is wiki.js (defines titleOfEnt)",
               "titleOfEnt" in blocks[1] and "window.localGraph = function" not in blocks[1])
        # Marker strings alone would still pass if the substitution truncated or
        # mangled an asset outside them: compare each block to its source file.
        for i, name in enumerate(("graph.js", "wiki.js")):
            want = (assets_dir / name).read_text(encoding="utf-8")
            record(f"inline block {i} is {name} verbatim",
                   blocks[i].strip() == want.strip(),
                   f"{len(blocks[i])} vs {len(want)} chars")

    # 8. a missing asset fails the build LOUDLY, naming the file — exercised on
    # a COPY of the scripts, never by touching the real repo files.
    copy_dir = root / "wiki-copy"
    shutil.copytree(assets_dir, copy_dir)
    (copy_dir / "graph.js").unlink()
    missing_asset_out = root / "missing-asset-out"
    r = run(copy_dir / "wiki.py", "build", "--bundle", b, "--out", missing_asset_out)
    record("build fails when an asset is missing", r.returncode != 0, r.stdout + r.stderr)
    record("failure names the missing asset", "graph.js" in (r.stdout + r.stderr), r.stdout + r.stderr)

    # 8b. the asset read is hoisted to the top of emit() — before the output
    # dir is created or any data file is written — so a stale install fails
    # BEFORE it churns the output, not after.
    record("no output written before the missing-asset failure",
           not missing_asset_out.exists(),
           list(missing_asset_out.rglob("*")) if missing_asset_out.exists() else "")

    # 8c. no registration → no in-bundle copy: a plain build never installs
    # anything into <bundle>/scripts/, only --register does.
    record("no post_ingest subscriber yet on this bundle",
           not any(h.get("name") == "wiki"
                   for h in json.loads((b / "elephant.json").read_text(encoding="utf-8"))
                   .get("hooks", {}).get("post_ingest", [])))
    record("unregistered build did NOT create <bundle>/scripts/wiki.py", not (b / "scripts" / "wiki.py").exists())

    # 9. --register: subscribe + self-copy of wiki.py AND its JS assets + gitignore
    r = run(WIKI, "build", "--bundle", b, "--out", out, "--register")
    record("--register exits 0", r.returncode == 0, r.stdout + r.stderr)
    cfg = json.loads((b / "elephant.json").read_text(encoding="utf-8"))
    entry = next((h for h in cfg.get("hooks", {}).get("post_ingest", [])
                  if h.get("name") == "wiki"), None)
    record("post_ingest has a wiki subscriber", bool(entry), json.dumps(cfg.get("hooks", {})))
    record("generator copied into <bundle>/scripts/wiki.py", (b / "scripts" / "wiki.py").exists())
    record("graph.js asset copied into <bundle>/scripts/", (b / "scripts" / "graph.js").exists())
    record("wiki.js asset copied into <bundle>/scripts/", (b / "scripts" / "wiki.js").exists())
    record("registered run points at the in-bundle copy",
           bool(entry) and str(b / "scripts" / "wiki.py") in entry["run"],
           entry["run"] if entry else "")
    gi = b / ".gitignore"
    record("wiki-out/ is gitignored", gi.exists() and "wiki-out/" in gi.read_text(encoding="utf-8"))

    # 10. INTEGRATION: firing post_ingest regenerates the wiki (Part A ⟶ Part B)
    shutil.rmtree(out, ignore_errors=True)
    r = run(b / "scripts" / "run-hooks.py", "post_ingest", "--trigger", "ingest", "--bundle", b)
    record("run-hooks post_ingest exits 0", r.returncode == 0, r.stderr)
    record("firing post_ingest regenerated wiki-out/wiki.html", (out / "wiki.html").exists(),
           "wiki did not regenerate from the hook")

    # 11. --unregister removes the subscriber
    r = run(WIKI, "build", "--bundle", b, "--out", out, "--unregister")
    cfg = json.loads((b / "elephant.json").read_text(encoding="utf-8"))
    still = any(h.get("name") == "wiki" for h in cfg.get("hooks", {}).get("post_ingest", []))
    record("--unregister removes the subscriber", r.returncode == 0 and not still, r.stdout + r.stderr)

    # 12. auto-refresh: a plain build (no --register) run from OUTSIDE the
    # bundle, against a bundle whose elephant.json already has a `wiki`
    # post_ingest entry pointing at a deliberately stale in-bundle copy,
    # refreshes <bundle>/scripts/wiki.py AND every sibling asset — otherwise
    # the next ingestion would silently keep running the stale generator.
    stale_bundle = make_bundle(root / "stale-bundle")
    stale_script = stale_bundle / "scripts" / "wiki.py"
    stale_script.write_text("#!/usr/bin/env python3\n# stale placeholder — pre-dates current assets\n",
                             encoding="utf-8")
    (stale_bundle / "scripts" / "graph.js").write_text("// stale graph.js placeholder\n", encoding="utf-8")
    (stale_bundle / "scripts" / "wiki.js").write_text("// stale wiki.js placeholder\n", encoding="utf-8")
    cfg = json.loads((stale_bundle / "elephant.json").read_text(encoding="utf-8"))
    cfg["hooks"] = {"post_ingest": [{"name": "wiki",
                                      "run": [sys.executable, str(stale_script), "build",
                                              "--bundle", str(stale_bundle)]}]}
    (stale_bundle / "elephant.json").write_text(json.dumps(cfg), encoding="utf-8")

    r = run(WIKI, "build", "--bundle", stale_bundle, "--out", stale_bundle / "wiki-out")
    record("auto-refresh: plain build against a stale-registered bundle exits 0",
           r.returncode == 0, r.stdout + r.stderr)
    record("auto-refresh: prints a refresh notice", "refresh" in (r.stdout + r.stderr).lower(),
           r.stdout + r.stderr)
    record("auto-refresh: <bundle>/scripts/wiki.py content now matches the plugin's current generator",
           stale_script.exists() and stale_script.read_text(encoding="utf-8") == WIKI.read_text(encoding="utf-8"))
    for name in ("graph.js", "wiki.js"):
        refreshed = stale_bundle / "scripts" / name
        record(f"auto-refresh: {name} content now matches the plugin's current asset",
               refreshed.exists() and refreshed.read_text(encoding="utf-8")
               == (assets_dir / name).read_text(encoding="utf-8"))

    # 13. a syntax error in graph.js does not prevent wiki.js from parsing —
    # the whole point of splitting the two into separate <script> blocks.
    # Exercised on a COPY of the assets, never the real repo files.
    broken_dir = root / "wiki-broken-graph"
    shutil.copytree(assets_dir, broken_dir)
    (broken_dir / "graph.js").write_text("this is not valid javascript (((\n", encoding="utf-8")
    broken_out = root / "broken-graph-out"
    r = run(broken_dir / "wiki.py", "build", "--bundle", b, "--out", broken_out)
    record("build still succeeds with a syntactically broken graph.js", r.returncode == 0, r.stdout + r.stderr)
    broken_html = (broken_out / "wiki.html").read_text(encoding="utf-8") if (broken_out / "wiki.html").exists() else ""
    broken_blocks = inline_script_blocks(broken_html)
    record("broken-graph build still carries two separate inline script blocks",
           len(broken_blocks) == 2, len(broken_blocks))
    node_bin = shutil.which("node")
    if node_bin and len(broken_blocks) == 2:
        tmp_graph = root / "_broken_graph.js"
        tmp_wiki = root / "_broken_wiki.js"
        tmp_graph.write_text(broken_blocks[0], encoding="utf-8")
        tmp_wiki.write_text(broken_blocks[1], encoding="utf-8")
        rg = subprocess.run([node_bin, "--check", str(tmp_graph)], capture_output=True, text=True, encoding="utf-8")
        rw = subprocess.run([node_bin, "--check", str(tmp_wiki)], capture_output=True, text=True, encoding="utf-8")
        record("broken graph.js block fails node --check, as expected", rg.returncode != 0, rg.stdout + rg.stderr)
        record("wiki.js block still passes node --check despite the broken graph.js",
               rw.returncode == 0, rw.stdout + rw.stderr)
    elif not node_bin:
        print("       (node not on PATH — skipping the broken-graph node --check pass)")

    # 14. optional: a `node --check` syntax pass on each asset. Never required —
    # skipped cleanly, with a printed note, when node isn't on PATH.
    node = shutil.which("node")
    if node:
        for name in ("wiki.js", "graph.js"):
            rn = subprocess.run([node, "--check", str(assets_dir / name)],
                                 capture_output=True, text=True, encoding="utf-8")
            record(f"node --check {name}", rn.returncode == 0, rn.stdout + rn.stderr)
    else:
        print("       (node not on PATH — skipping the node --check syntax pass)")


if __name__ == "__main__":
    sys.exit(main())
