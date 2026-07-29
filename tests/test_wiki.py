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
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

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

    # 1. build
    r = run(WIKI, "build", "--bundle", b, "--out", out)
    record("build exits 0", r.returncode == 0, r.stdout + r.stderr)
    record("wiki.html written", (out / "wiki.html").exists())
    record("data/core.js written", (out / "data" / "core.js").exists())

    core = load_core(out) if (out / "data" / "core.js").exists() else {"entities": [], "index": []}

    # 2. ids follow the bundle-absolute convention (/entities/…, NOT /knowledge/…)
    alice = next((e for e in core["entities"] if e["title"] == "Alice"), None)
    record("entity id is bundle-absolute (/entities/…)",
           bool(alice) and alice["id"] == "/entities/person/alice.md",
           alice["id"] if alice else "no Alice")

    # 3. fact→entity cross-link resolved (the bug the browser test caught)
    record("fact backlinks onto its entity",
           bool(alice) and "/facts/f1.md" in alice["factIds"],
           alice["factIds"] if alice else "")

    # 4. index carries the fact and the source
    types = {r_["t"] for r_ in core["index"]}
    record("index has a fact row", "f" in types)
    record("index has a source row", "s" in types)

    # 5. a fact shard exists with the SHARD contract
    shard = out / "data" / "facts-2026-07.js"
    record("month shard written with __SHARD__ contract",
           shard.exists() and shard.read_text(encoding="utf-8").startswith("window.__SHARD__('f',"),
           "missing/!SHARD")

    # 6. --register: subscribe + self-copy + gitignore
    r = run(WIKI, "build", "--bundle", b, "--out", out, "--register")
    record("--register exits 0", r.returncode == 0, r.stdout + r.stderr)
    cfg = json.loads((b / "elephant.json").read_text(encoding="utf-8"))
    entry = next((h for h in cfg.get("hooks", {}).get("post_ingest", [])
                  if h.get("name") == "wiki"), None)
    record("post_ingest has a wiki subscriber", bool(entry), json.dumps(cfg.get("hooks", {})))
    record("generator copied into <bundle>/scripts/wiki.py", (b / "scripts" / "wiki.py").exists())
    record("registered run points at the in-bundle copy",
           bool(entry) and str(b / "scripts" / "wiki.py") in entry["run"],
           entry["run"] if entry else "")
    gi = b / ".gitignore"
    record("wiki-out/ is gitignored", gi.exists() and "wiki-out/" in gi.read_text(encoding="utf-8"))

    # 7. INTEGRATION: firing post_ingest regenerates the wiki (Part A ⟶ Part B)
    shutil.rmtree(out, ignore_errors=True)
    r = run(b / "scripts" / "run-hooks.py", "post_ingest", "--trigger", "ingest", "--bundle", b)
    record("run-hooks post_ingest exits 0", r.returncode == 0, r.stderr)
    record("firing post_ingest regenerated wiki-out/wiki.html", (out / "wiki.html").exists(),
           "wiki did not regenerate from the hook")

    # 8. --unregister removes the subscriber
    r = run(WIKI, "build", "--bundle", b, "--out", out, "--unregister")
    cfg = json.loads((b / "elephant.json").read_text(encoding="utf-8"))
    still = any(h.get("name") == "wiki" for h in cfg.get("hooks", {}).get("post_ingest", []))
    record("--unregister removes the subscriber", r.returncode == 0 and not still, r.stdout + r.stderr)


if __name__ == "__main__":
    sys.exit(main())
