#!/usr/bin/env python3
"""Standalone test suite for `plugin/bin/elephant-update`.

The executable exists because a bundle carries its own copy of the plugin's
`scripts/` and `templates/`, and `claude plugin update` never touches it. The
measured failure: the plugin sat on `0.1.0-beta.13` while a bundle's `scripts/`
still held `0.1.0-beta.9`, two scripts the skills call were absent there
entirely, and the hourly routine that noticed re-filed the wrong fix five times
in one day because no signal available to it could say the bundle was stale.

What this file covers so far is the comparison layer — the part every mode's
preflight depends on and the part that must not be able to lie:

  (a) both sides are read off disk, every time. Nothing is stored in the bundle
      (a record would be absent from exactly the stale bundles it exists to
      catch) and nothing is published;
  (b) the published set is a PATTERN matched against the resolved plugin, so
      `assets/scripts/__pycache__/` and the `init`-only assets are outside it
      by construction rather than by a filter someone has to remember;
  (c) comparison normalises line endings, or a Git-for-Windows checkout reads as
      fully drifted and blocks every mode on Windows;
  (d) `elephant-mem`'s set is required and blocks; `elephant-wiki`'s is optional,
      is drift only where the bundle already has the file, and never blocks;
  (e) an uninstalled `elephant-wiki` is not could-not-verify — with no plugin
      publishing them, wiki files in a bundle are files no plugin ships;
  (f) `--check` writes nothing at all.

Pure stdlib, Python 3.10+, mirroring `tests/test_backlog.py`'s conventions: a
throwaway bundle in a tempdir, fake plugin directories in the cache layout
Claude Code really uses, PASS/FAIL per check, exit code 0 only if every check
passes.
"""
import importlib.machinery
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXECUTABLE = REPO_ROOT / "plugin" / "bin" / "elephant-update"
REAL_MEM_PLUGIN = REPO_ROOT / "plugin"
REAL_WIKI_PLUGIN = REPO_ROOT / "elephant-wiki"

checks = []  # list of (label, passed)


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    return passed


def load_executable():
    """Import the extensionless executable as a module, so its comparison can
    be exercised directly rather than only through a CLI. `spec_from_file_location`
    cannot infer a loader without a `.py` suffix, hence the explicit one."""
    loader = importlib.machinery.SourceFileLoader("elephant_update", str(EXECUTABLE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# ── helpers tasks 2-5 extend ─────────────────────────────────────────────────

def make_bundle(root, name="bundle", scripts=None, templates=None, extra=None):
    """A throwaway bundle: the directories a real one has, plus whatever copies
    of the published files this case wants. `scripts`/`templates` map a filename
    to its content; `extra` maps a bundle-relative path to content, for files no
    plugin ships."""
    bundle = Path(root) / name
    for d in ("knowledge/facts", "knowledge/entities", "knowledge/sources",
              "state", "scripts", "templates"):
        (bundle / d).mkdir(parents=True, exist_ok=True)
    for filename, content in (scripts or {}).items():
        write(bundle / "scripts" / filename, content)
    for filename, content in (templates or {}).items():
        write(bundle / "templates" / filename, content)
    for rel, content in (extra or {}).items():
        write(bundle / rel, content)
    return bundle


def make_plugin(root, plugin, version="0.1.0-beta.1", scripts=None, templates=None,
                other_assets=None, marketplace="elephant-mem"):
    """A fake installed plugin directory in the layout Claude Code uses:
    `<root>/cache/<marketplace>/<plugin>/<version>/`, so the same helper serves
    the resolution tests. `other_assets` are assets outside the published set."""
    plugin_root = Path(root) / "cache" / marketplace / plugin / version
    (plugin_root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    write(plugin_root / ".claude-plugin" / "plugin.json",
          json.dumps({"name": plugin, "version": version}, indent=2) + "\n")
    for filename, content in (scripts or {}).items():
        write(plugin_root / "assets" / "scripts" / filename, content)
    for filename, content in (templates or {}).items():
        write(plugin_root / "assets" / "templates" / filename, content)
    for rel, content in (other_assets or {}).items():
        write(plugin_root / "assets" / rel, content)
    return plugin_root


def write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def snapshot(root):
    """Every file under `root` with its bytes and mtime — enough to prove a
    read-only pass wrote nothing, including a rewrite of identical content."""
    out = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = (path.read_bytes(), path.stat().st_mtime_ns)
    return out


def rels(entries):
    return sorted(e.rel for e in entries)


def main():
    eu = load_executable()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        comparison_checks(eu, tmp)
        wiki_checks(eu, tmp)
        real_tree_checks(eu, tmp)

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


# ── the required set ─────────────────────────────────────────────────────────

def comparison_checks(eu, tmp):
    root = tmp / "required"
    plugin = make_plugin(
        root, "elephant-mem",
        scripts={"recall.py": "print('recall')\n",
                 "close-loops.py": "print('close')\n",
                 "build-index.py": "print('index')\n"},
        templates={"open-loop.md": "# loop\n", "fact.md": "# fact\n"},
    )

    # E1 — everything matches
    synced = make_bundle(
        root, "synced",
        scripts={"recall.py": "print('recall')\n",
                 "close-loops.py": "print('close')\n",
                 "build-index.py": "print('index')\n"},
        templates={"open-loop.md": "# loop\n", "fact.md": "# fact\n"},
    )
    before = snapshot(synced)
    result = eu.compare({"elephant-mem": plugin}, synced)
    record("E1 every compared file matches — in-sync code",
           result.code == eu.CHECK_IN_SYNC,
           f"code={result.code} drift={rels(result.required_drift)}")
    record("E1 in sync is silent — no stderr notice",
           eu.check_notice(result) == "", repr(eu.check_notice(result)))
    record("E1 the comparison wrote nothing to the bundle",
           snapshot(synced) == before)
    record("E1 all five published files were compared, none skipped",
           len(result.entries) == 5 and all(e.state == "same" for e in result.entries),
           [(e.rel, e.state) for e in result.entries])

    # E2 — a required file present on both sides differs
    stale = make_bundle(
        root, "stale",
        scripts={"recall.py": "print('OLD recall')\n",
                 "close-loops.py": "print('close')\n",
                 "build-index.py": "print('index')\n"},
        templates={"open-loop.md": "# loop\n", "fact.md": "# fact\n"},
    )
    result = eu.compare({"elephant-mem": plugin}, stale)
    record("E2 a differing required file is required-drift",
           result.code == eu.CHECK_REQUIRED_DRIFT, f"code={result.code}")
    record("E2 the drift names the file that differs",
           rels(result.required_drift) == ["scripts/recall.py"],
           rels(result.required_drift))
    notice = eu.check_notice(result)
    record("E2 the notice names the file", "scripts/recall.py" in notice, notice)
    record("E2 the notice names both routes out",
           "elephant-update" in notice and "elephant-mem:update" in notice, notice)
    record("E2 a copy would overwrite it",
           "scripts/recall.py" in rels(result.copy_plan))

    # E3 — a required file the bundle lacks entirely (the motivating failure)
    missing = make_bundle(
        root, "missing",
        scripts={"build-index.py": "print('index')\n"},
        templates={"open-loop.md": "# loop\n", "fact.md": "# fact\n"},
    )
    result = eu.compare({"elephant-mem": plugin}, missing)
    record("E3 a missing required file is required-drift",
           result.code == eu.CHECK_REQUIRED_DRIFT, f"code={result.code}")
    record("E3 both absent scripts are named",
           rels(result.required_drift) == ["scripts/close-loops.py", "scripts/recall.py"],
           rels(result.required_drift))
    record("E3 a copy installs them",
           {"scripts/close-loops.py", "scripts/recall.py"} <= set(rels(result.copy_plan)),
           rels(result.copy_plan))
    record("E3 the copy plan is the required set in full, matches included",
           len(result.copy_plan) == 5, rels(result.copy_plan))
    record("E3 the notice says missing, not merely different",
           "missing from the bundle" in eu.check_notice(result),
           eu.check_notice(result))

    # E6 — files differing only by line ending
    crlf = make_bundle(
        root, "crlf",
        scripts={"recall.py": b"print('recall')\r\n",
                 "close-loops.py": b"print('close')\r\n",
                 "build-index.py": b"print('index')\r\n"},
        templates={"open-loop.md": b"# loop\r\n", "fact.md": b"# fact\r\n"},
    )
    result = eu.compare({"elephant-mem": plugin}, crlf)
    record("E6 a CRLF checkout is not drift",
           result.code == eu.CHECK_IN_SYNC,
           f"code={result.code} drift={rels(result.required_drift)}")
    record("E6 normalisation is line endings only, not whitespace at large",
           eu.normalise_newlines(b"a\r\nb\rc\n") == b"a\nb\nc\n"
           and eu.normalise_newlines(b"a \n") != b"a\n")
    trailing = make_bundle(root, "trailing", scripts={"recall.py": "print('recall')"},
                           templates={})
    shutil.copy2(plugin / "assets" / "scripts" / "close-loops.py", trailing / "scripts")
    shutil.copy2(plugin / "assets" / "scripts" / "build-index.py", trailing / "scripts")
    for name in ("open-loop.md", "fact.md"):
        shutil.copy2(plugin / "assets" / "templates" / name, trailing / "templates")
    record("E6 a missing final newline is still drift",
           eu.compare({"elephant-mem": plugin}, trailing).code == eu.CHECK_REQUIRED_DRIFT)

    # E7 — files the bundle holds that neither plugin ships
    ownfiles = make_bundle(
        root, "ownfiles",
        scripts={"recall.py": "print('recall')\n",
                 "close-loops.py": "print('close')\n",
                 "build-index.py": "print('index')\n",
                 "my-own-tool.py": "print('mine')\n"},
        templates={"open-loop.md": "# loop\n", "fact.md": "# fact\n",
                   "my-template.md": "# mine\n"},
        extra={"notes.md": "# notes\n", "knowledge/facts/2026-01-a-fact.md": "x\n"},
    )
    result = eu.compare({"elephant-mem": plugin}, ownfiles)
    record("E7 bundle-only files are not drift",
           result.code == eu.CHECK_IN_SYNC, f"code={result.code}")
    record("E7 bundle-only files are never in the compared set",
           "scripts/my-own-tool.py" not in [e.rel for e in result.entries],
           [e.rel for e in result.entries])
    record("E7 bundle-only files are never in the copy plan",
           "templates/my-template.md" not in rels(result.copy_plan))

    # E8 — unpublished files under the plugin's own assets
    noisy = make_plugin(
        root, "elephant-mem", version="0.1.0-beta.2",
        scripts={"recall.py": "print('recall')\n"},
        templates={"open-loop.md": "# loop\n"},
        other_assets={
            "scripts/__pycache__/recall.cpython-311.pyc": b"\x00\x01",
            "scripts/notes.txt": "scratch\n",
            "vocab.json": "{}\n",
            "elephant-plugin.md": "# plugin\n",
            "seed/config.md": "# seed config\n",
            "seed/state/cursors.json": "{}\n",
        },
    )
    plain = make_bundle(root, "plain",
                        scripts={"recall.py": "print('recall')\n"},
                        templates={"open-loop.md": "# loop\n"})
    result = eu.compare({"elephant-mem": noisy}, plain)
    compared = [e.rel for e in result.entries]
    record("E8 only the published patterns are compared",
           sorted(compared) == ["scripts/recall.py", "templates/open-loop.md"], compared)
    record("E8 __pycache__ is outside the set", not any("__pycache__" in r for r in compared))
    record("E8 an init-only asset is outside the set",
           not any(r in ("vocab.json", "elephant-plugin.md") for r in compared))
    record("E8 the seed tree is outside the set", not any(r.startswith("seed/") for r in compared))
    record("E8 a non-matching extension under scripts/ is outside the set",
           "scripts/notes.txt" not in compared)
    record("E8 a noisy plugin with a matching bundle is still in sync",
           result.code == eu.CHECK_IN_SYNC, f"code={result.code}")


# ── the optional set ─────────────────────────────────────────────────────────

def wiki_checks(eu, tmp):
    root = tmp / "wiki"
    mem = make_plugin(root, "elephant-mem",
                      scripts={"recall.py": "print('recall')\n"},
                      templates={"open-loop.md": "# loop\n"})
    wiki = make_plugin(root, "elephant-wiki", version="0.1.0-beta.4",
                       scripts={"wiki.py": "print('wiki 2')\n",
                                "wiki.js": "// spa 2\n",
                                "graph.js": "// graph 2\n"})
    in_sync_mem = {"recall.py": "print('recall')\n"}
    in_sync_templates = {"open-loop.md": "# loop\n"}

    # E4 — a bundle that never built a wiki
    never = make_bundle(root, "never", scripts=dict(in_sync_mem),
                        templates=dict(in_sync_templates))
    result = eu.compare({"elephant-mem": mem, "elephant-wiki": wiki}, never)
    record("E4 an absent optional file is not drift",
           result.code == eu.CHECK_IN_SYNC, f"code={result.code}")
    record("E4 a copy installs nothing of the optional set",
           not any(e.plugin == "elephant-wiki" for e in result.copy_plan),
           rels(result.copy_plan))
    record("E4 the absent optional files are still accounted for as compared",
           sorted(e.rel for e in result.entries if e.plugin == "elephant-wiki")
           == ["scripts/graph.js", "scripts/wiki.js", "scripts/wiki.py"],
           [(e.rel, e.state) for e in result.entries if e.plugin == "elephant-wiki"])

    # E5 — a bundle that has them, frozen at an older build
    frozen = make_bundle(root, "frozen",
                         scripts={**in_sync_mem,
                                  "wiki.py": "print('wiki 1')\n",
                                  "wiki.js": "// spa 2\n",
                                  "graph.js": "// graph 1\n"},
                         templates=dict(in_sync_templates))
    result = eu.compare({"elephant-mem": mem, "elephant-wiki": wiki}, frozen)
    record("E5 an outdated optional file is optional-drift",
           result.code == eu.CHECK_OPTIONAL_DRIFT, f"code={result.code}")
    record("E5 optional drift never counts as required drift",
           result.required_drift == [], rels(result.required_drift))
    record("E5 the outdated optional files are named",
           rels(result.optional_drift) == ["scripts/graph.js", "scripts/wiki.py"],
           rels(result.optional_drift))
    notice = eu.check_notice(result)
    record("E5 the notice names them", "scripts/graph.js" in notice and
           "scripts/wiki.py" in notice, notice)
    record("E5 the notice says it does not stop the run",
           "Not a stop." in notice, notice)
    record("E5 a copy updates the files the bundle already has",
           sorted(e.rel for e in result.copy_plan if e.plugin == "elephant-wiki")
           == ["scripts/graph.js", "scripts/wiki.js", "scripts/wiki.py"],
           rels(result.copy_plan))

    # required drift outranks optional drift when both are present
    both = make_bundle(root, "both",
                       scripts={"recall.py": "print('OLD')\n",
                                "wiki.py": "print('wiki 1')\n"},
                       templates=dict(in_sync_templates))
    result = eu.compare({"elephant-mem": mem, "elephant-wiki": wiki}, both)
    record("required drift outranks optional drift in the code",
           result.code == eu.CHECK_REQUIRED_DRIFT, f"code={result.code}")
    record("the blocking notice is the one printed when both drifted",
           "elephant-mem:update" in eu.check_notice(result), eu.check_notice(result))

    # E40 — elephant-wiki is not installed
    for label, dirs in (("absent from the mapping", {"elephant-mem": mem}),
                        ("mapped to None", {"elephant-mem": mem, "elephant-wiki": None}),
                        ("mapped to a path that is gone",
                         {"elephant-mem": mem, "elephant-wiki": root / "cache" / "nope"})):
        result = eu.compare(dirs, frozen)
        record(f"E40 wiki {label} — not could-not-verify, and not drift",
               result.code == eu.CHECK_IN_SYNC, f"code={result.code}")
        record(f"E40 wiki {label} — its files in the bundle are simply ignored",
               not any(e.plugin == "elephant-wiki" for e in result.entries)
               and not any("wiki" in e.rel for e in result.copy_plan),
               [e.rel for e in result.entries])

    # only elephant-mem failing to resolve is could-not-verify
    result = eu.compare({"elephant-wiki": wiki}, frozen)
    record("only elephant-mem failing to resolve is could-not-verify",
           result.code == eu.CHECK_CANNOT_VERIFY, f"code={result.code}")
    record("the could-not-verify notice says which side it could not read",
           "elephant-mem" in eu.check_notice(result), eu.check_notice(result))
    record("a bundle that is not there is could-not-verify too",
           eu.compare({"elephant-mem": mem}, root / "no-such-bundle").code
           == eu.CHECK_CANNOT_VERIFY)

    # A half-installed plugin must never read as agreement. In sync is the one
    # outcome that lets every mode run, so an empty required set has to be
    # could-not-verify rather than the silent pass this command exists to close.
    hollow = make_plugin(root, "elephant-mem", version="0.1.0-beta.99")
    result = eu.compare({"elephant-mem": hollow}, never)
    record("a resolved plugin publishing no files is could-not-verify, not in sync",
           result.code == eu.CHECK_CANNOT_VERIFY, f"code={result.code}")
    record("the notice says the install looks incomplete",
           "publishes no files" in eu.check_notice(result), eu.check_notice(result))


# ── against the real published assets ────────────────────────────────────────

def real_tree_checks(eu, tmp):
    """The patterns have to line up with what this repo actually publishes and
    with where a bundle actually keeps those files. A fake plugin tree can agree
    with a wrong pattern; the real one cannot."""
    mem_set = eu.published_files(REAL_MEM_PLUGIN, ("scripts/*.py", "templates/*.md"))
    record("the real required set includes the two scripts the failure was about",
           {"scripts/close-loops.py", "scripts/recall.py"} <= set(mem_set), sorted(mem_set))
    record("the real required set includes the templates",
           "templates/open-loop.md" in mem_set, sorted(mem_set))
    record("the real required set excludes the init-only assets",
           not any(r in ("vocab.json", "elephant-plugin.md") or r.startswith("seed/")
                   for r in mem_set), sorted(mem_set))
    record("every file in the real required set is a script or a template",
           all(r.startswith("scripts/") and r.endswith(".py")
               or r.startswith("templates/") and r.endswith(".md") for r in mem_set),
           sorted(mem_set))

    wiki_spec = next(s for s in eu.PUBLISHED if s.plugin == "elephant-wiki")
    wiki_set = eu.published_files(REAL_WIKI_PLUGIN, wiki_spec.patterns)
    record("the real optional set is exactly the wiki's three files",
           sorted(wiki_set) == ["scripts/graph.js", "scripts/wiki.js", "scripts/wiki.py"],
           sorted(wiki_set))

    # A bundle built the way `init` builds one, from the real assets, is in sync
    # against the real plugin directories — pattern, relative paths and bundle
    # layout all agreeing at once.
    bundle = make_bundle(tmp, "real")
    for rel, src in mem_set.items():
        shutil.copy2(src, bundle / rel)
    for rel, src in wiki_set.items():
        shutil.copy2(src, bundle / rel)
    result = eu.compare({"elephant-mem": REAL_MEM_PLUGIN, "elephant-wiki": REAL_WIKI_PLUGIN},
                        bundle)
    record("a bundle holding the real published files reads as in sync",
           result.code == eu.CHECK_IN_SYNC,
           f"code={result.code} required={rels(result.required_drift)} "
           f"optional={rels(result.optional_drift)}")
    record("that comparison covered every real published file",
           len(result.entries) == len(mem_set) + len(wiki_set),
           f"{len(result.entries)} vs {len(mem_set) + len(wiki_set)}")

    # Deleting one real script reproduces the motivating failure exactly.
    (bundle / "scripts" / "close-loops.py").unlink()
    result = eu.compare({"elephant-mem": REAL_MEM_PLUGIN, "elephant-wiki": REAL_WIKI_PLUGIN},
                        bundle)
    record("removing a real required script reads as required drift",
           result.code == eu.CHECK_REQUIRED_DRIFT
           and rels(result.required_drift) == ["scripts/close-loops.py"],
           f"code={result.code} {rels(result.required_drift)}")

    record("the executable sits outside plugin/assets/scripts/, which a re-sync "
           "copies and three suites glob",
           EXECUTABLE.is_file()
           and not (REAL_MEM_PLUGIN / "assets" / "scripts" / "elephant-update").exists(),
           str(EXECUTABLE))


if __name__ == "__main__":
    sys.exit(main())
