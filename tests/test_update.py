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
  (f) `--check` writes nothing at all;
  (g) resolution reads Claude Code's registry FIRST and only falls back to
      semver over the plugin cache, because a version sitting in the cache is
      not evidence it is installed — and because sorted as text `0.1.0-beta.9`
      follows `0.1.0-beta.13`, which is the older plugin and the original bug;
  (h) the family comes from the `@elephant-mem` key suffix, never a prefix
      heuristic over names;
  (i) nothing assumes `python3` is on PATH.

Pure stdlib, Python 3.10+, mirroring `tests/test_backlog.py`'s conventions: a
throwaway bundle in a tempdir, fake plugin directories in the cache layout
Claude Code really uses, PASS/FAIL per check, exit code 0 only if every check
passes.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
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


def make_registry(root, entries, schema=2):
    """`<root>/installed_plugins.json` in the shape Claude Code really writes:
    schema version 2, `plugins` keyed `<plugin>@<marketplace>`, each key holding
    a LIST of install records carrying `installPath` and `version`. `entries`
    maps a key to one record or to a list of them, so a suite can exercise the
    several-scopes case as well as the ordinary one."""
    plugins = {key: (value if isinstance(value, list) else [value])
               for key, value in entries.items()}
    return write(Path(root) / "installed_plugins.json",
                 json.dumps({"version": schema, "plugins": plugins}, indent=2) + "\n")


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
        version_checks(eu)
        registry_checks(eu, tmp)
        family_checks(eu, tmp)
        registry_gap_checks(eu, tmp)
        fallback_checks(eu, tmp)
        plugins_dir_checks(eu, tmp)
        interpreter_checks(eu)
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


# ── resolution: the registry first, semver over the cache as the fallback ────

def version_checks(eu):
    """E25 — and the reason resolution is Python at all. Sorted as text
    `0.1.0-beta.9` follows `0.1.0-beta.13`, so a shell `sort` picks the older
    plugin and reproduces the failure this command exists to fix. A Windows
    batch file cannot sort at all."""
    key = eu.parse_version
    record("E25 beta.13 outranks beta.9 as semver",
           key("0.1.0-beta.13") > key("0.1.0-beta.9"))
    record("E25 and a text sort of that pair picks the wrong one, so the check "
           "above is not passing vacuously",
           sorted(["0.1.0-beta.13", "0.1.0-beta.9"])[-1] == "0.1.0-beta.9")
    real_cache = ["0.1.0-beta.10", "0.1.0-beta.11", "0.1.0-beta.12",
                  "0.1.0-beta.13", "0.1.0-beta.7", "0.1.0-beta.9"]
    record("E25 the six versions really in the owner's cache order correctly",
           sorted(real_cache, key=key) ==
           ["0.1.0-beta.7", "0.1.0-beta.9", "0.1.0-beta.10", "0.1.0-beta.11",
            "0.1.0-beta.12", "0.1.0-beta.13"],
           sorted(real_cache, key=key))
    record("a release outranks any prerelease of the same core",
           key("0.1.0") > key("0.1.0-beta.13"))
    record("the numeric core is compared before anything else",
           key("0.2.0") > key("0.1.9") and key("1.0.0") > key("0.99.99"))
    record("more prerelease identifiers outrank a prefix of themselves",
           key("0.1.0-beta.1") > key("0.1.0-beta"))
    record("alphanumeric prerelease identifiers compare as text",
           key("0.1.0-beta.1") > key("0.1.0-alpha.99"))
    record("a numeric prerelease identifier sits below an alphanumeric one",
           key("0.1.0-1") < key("0.1.0-beta"))
    record("build metadata is ignored and a leading v is tolerated",
           key("0.1.0+build.5") == key("0.1.0") == key("v0.1.0"))
    record("a string that is not a version sorts below one that is, and does "
           "not raise — the cache is a directory listing and can hold anything",
           key("main") < key("0.0.1") and key("") < key("0.0.1"))


def registry_checks(eu, tmp):
    """E23 — the registry names an installed version, and that directory is the
    one used. A version sitting in the cache is not evidence it is installed."""
    root = tmp / "registry"
    mem9 = make_plugin(root, "elephant-mem", version="0.1.0-beta.9",
                       scripts={"recall.py": "print('recall 9')\n"},
                       templates={"open-loop.md": "# loop 9\n"})
    mem13 = make_plugin(root, "elephant-mem", version="0.1.0-beta.13",
                        scripts={"recall.py": "print('recall 13')\n",
                                 "close-loops.py": "print('close 13')\n"},
                        templates={"open-loop.md": "# loop 13\n"})
    wiki4 = make_plugin(root, "elephant-wiki", version="0.1.0-beta.4",
                        scripts={"wiki.py": "print('wiki 4')\n",
                                 "wiki.js": "// spa 4\n", "graph.js": "// graph 4\n"})

    # The registry names beta.9 — deliberately NOT the cache's highest, so
    # "the registry wins" is something these checks can actually observe.
    make_registry(root, {
        "elephant-mem@elephant-mem": {"installPath": str(mem9),
                                      "version": "0.1.0-beta.9"},
        "elephant-wiki@elephant-mem": {"installPath": str(wiki4),
                                       "version": "0.1.0-beta.4"},
    })
    before = snapshot(root)
    resolution = eu.resolve_plugins(plugins_dir=root)
    record("E23 the registry is the source, not the cache",
           resolution.source == "registry", resolution.source)
    record("E23 the declared directory is used, not the cache's highest",
           resolution.path_of("elephant-mem") == mem9,
           f"{resolution.path_of('elephant-mem')} (cache high: {mem13})")
    record("E23 the version reported is the one the registry declares",
           resolution.version_of("elephant-mem") == "0.1.0-beta.9",
           resolution.version_of("elephant-mem"))
    record("E23 the optional plugin resolves from the registry too",
           resolution.path_of("elephant-wiki") == wiki4,
           str(resolution.path_of("elephant-wiki")))
    record("E23 a clean resolution has nothing to say out loud",
           resolution.notes == [], resolution.notes)
    record("E23 resolution reads and never writes",
           snapshot(root) == before)
    record("E23 plugin_dirs is exactly what compare() takes",
           resolution.plugin_dirs ==
           {"elephant-mem": mem9, "elephant-wiki": wiki4},
           resolution.plugin_dirs)

    # The integration that gives E23 its teeth: one bundle, one cache, two
    # registries. Resolving the wrong version is precisely what would let a
    # stale bundle read as fine — or a current one read as broken.
    bundle = make_bundle(root, "at-beta-9",
                         scripts={"recall.py": "print('recall 9')\n"},
                         templates={"open-loop.md": "# loop 9\n"})
    record("E23 a bundle at the version the registry declares reads as in sync",
           eu.compare(resolution.plugin_dirs, bundle).code == eu.CHECK_IN_SYNC)
    make_registry(root, {
        "elephant-mem@elephant-mem": {"installPath": str(mem13),
                                      "version": "0.1.0-beta.13"},
    })
    upgraded = eu.resolve_plugins(plugins_dir=root)
    result = eu.compare(upgraded.plugin_dirs, bundle)
    record("E23 the same bundle against the newly declared version is required "
           "drift — the motivating failure, reproduced through resolution",
           result.code == eu.CHECK_REQUIRED_DRIFT
           and rels(result.required_drift) ==
           ["scripts/close-loops.py", "scripts/recall.py",
            "templates/open-loop.md"],
           f"code={result.code} {rels(result.required_drift)}")
    record("E23 an uninstalled elephant-wiki drops out of the mapping entirely",
           "elephant-wiki" not in upgraded.plugin_dirs, upgraded.plugin_dirs)


def family_checks(eu, tmp):
    """The family comes from the `@elephant-mem` key suffix. A prefix heuristic
    over plugin or directory names would claim a stranger's `elephant-notes`
    from another marketplace, and would miss a plugin of ours not named
    `elephant-*`."""
    record("the plugin name comes out of the key",
           eu.plugin_of_key("elephant-mem@elephant-mem") == "elephant-mem")
    record("the optional plugin's key resolves the same way",
           eu.plugin_of_key("elephant-wiki@elephant-mem") == "elephant-wiki")
    record("a key from another marketplace is not ours — the real registry on "
           "the owner's machine carries exactly this one",
           eu.plugin_of_key("bb@inspira-legal") is None)
    record("a same-named plugin published by another marketplace is not ours",
           eu.plugin_of_key("elephant-mem@someone-elses-market") is None)
    record("an elephant-ish name from another marketplace is not ours either",
           eu.plugin_of_key("elephant-notes@other-market") is None)
    record("a malformed key is not ours, and does not raise",
           eu.plugin_of_key("@elephant-mem") is None
           and eu.plugin_of_key("elephant-mem") is None
           and eu.plugin_of_key(None) is None)
    record("family_key builds what `claude plugin update` takes",
           eu.family_key("elephant-wiki") == "elephant-wiki@elephant-mem")

    root = tmp / "family"
    mine = make_plugin(root, "elephant-mem", version="0.1.0-beta.13",
                       scripts={"recall.py": "print('mine')\n"})
    theirs = make_plugin(root, "elephant-mem", version="9.9.9",
                         scripts={"recall.py": "print('theirs')\n"},
                         marketplace="someone-elses-market")
    make_registry(root, {
        "elephant-mem@elephant-mem": {"installPath": str(mine),
                                      "version": "0.1.0-beta.13"},
        "elephant-mem@someone-elses-market": {"installPath": str(theirs),
                                              "version": "9.9.9"},
        "bb@inspira-legal": {"installPath": str(root), "version": "3.6.0"},
    })
    resolution = eu.resolve_plugins(plugins_dir=root)
    record("a foreign plugin sharing our name never wins on its higher version",
           resolution.path_of("elephant-mem") == mine,
           str(resolution.path_of("elephant-mem")))
    record("a foreign plugin is not in the resolution at all",
           sorted(resolution.installs) == ["elephant-mem"],
           sorted(resolution.installs))
    record("the cache fallback takes the family from the marketplace directory, "
           "not from what a plugin is called",
           eu.resolve_from_cache(plugins_dir=root).path_of("elephant-mem") == mine,
           str(eu.resolve_from_cache(plugins_dir=root).path_of("elephant-mem")))


def registry_gap_checks(eu, tmp):
    """A readable registry that names no plugin of the family, and one naming a
    directory that is gone. Neither may be answered by resolving the cache: a
    version in the cache is not evidence it is installed, and running a version
    the registry does not declare is the silent wrong-version run this command
    exists to close."""
    root = tmp / "gaps"
    mem13 = make_plugin(root, "elephant-mem", version="0.1.0-beta.13",
                        scripts={"recall.py": "print('recall 13')\n"})
    bundle = make_bundle(root, "bundle", scripts={"recall.py": "print('recall 13')\n"})

    make_registry(root, {"bb@inspira-legal": {"installPath": str(root),
                                              "version": "3.6.0"}})
    resolution = eu.resolve_plugins(plugins_dir=root)
    record("a registry naming no plugin of the family resolves nothing",
           resolution.installs == {}, resolution.installs)
    record("and it does NOT fall back to the cache, which holds beta.13",
           resolution.source == "registry", resolution.source)
    record("compare() then reports could-not-verify rather than reading the "
           "bundle against a version nobody installed",
           eu.compare(resolution.plugin_dirs, bundle).code
           == eu.CHECK_CANNOT_VERIFY)

    gone = root / "cache" / "elephant-mem" / "elephant-mem" / "0.1.0-beta.12"
    make_registry(root, {
        "elephant-mem@elephant-mem": {"installPath": str(gone),
                                      "version": "0.1.0-beta.12"}})
    resolution = eu.resolve_plugins(plugins_dir=root)
    record("a declared directory that is not on disk resolves to no path",
           resolution.path_of("elephant-mem") is None,
           str(resolution.path_of("elephant-mem")))
    record("the version it declared is still reported, so a caller can say what "
           "the registry claimed",
           resolution.version_of("elephant-mem") == "0.1.0-beta.12",
           resolution.version_of("elephant-mem"))
    record("a note names the directory that is missing, since compare() sees "
           "only the absence and cannot know the reason",
           len(resolution.notes) == 1 and "0.1.0-beta.12" in resolution.notes[0]
           and "not on disk" in resolution.notes[0], resolution.notes)
    record("the cache's beta.13 does not stand in for it",
           mem13 not in resolution.plugin_dirs.values(), resolution.plugin_dirs)
    record("that is could-not-verify, which lets the mode proceed",
           eu.compare(resolution.plugin_dirs, bundle).code
           == eu.CHECK_CANNOT_VERIFY)

    # One key can hold several records, one per install scope.
    make_registry(root, {"elephant-mem@elephant-mem": [
        {"scope": "project", "installPath": str(gone), "version": "0.1.0-beta.12"},
        {"scope": "user", "installPath": str(mem13), "version": "0.1.0-beta.13"},
    ]})
    record("among several scope records the highest live one wins",
           eu.resolve_plugins(plugins_dir=root).path_of("elephant-mem") == mem13)
    mem7 = make_plugin(root, "elephant-mem", version="0.1.0-beta.7",
                       scripts={"recall.py": "print('recall 7')\n"})
    make_registry(root, {"elephant-mem@elephant-mem": [
        {"scope": "user", "installPath": str(gone), "version": "0.1.0-beta.13"},
        {"scope": "project", "installPath": str(mem7), "version": "0.1.0-beta.7"},
    ]})
    record("a higher record whose directory is gone yields to the live lower one",
           eu.resolve_plugins(plugins_dir=root).path_of("elephant-mem") == mem7,
           str(eu.resolve_plugins(plugins_dir=root).path_of("elephant-mem")))
    make_registry(root, {"elephant-mem@elephant-mem":
                         {"installPath": str(mem13), "version": "0.1.0-beta.13"}})
    record("a key holding one record rather than a list still resolves",
           eu.resolve_plugins(plugins_dir=root).path_of("elephant-mem") == mem13)


def fallback_checks(eu, tmp):
    """E24 — a missing registry, or one whose schema has moved, falls back to
    semver over the cache. E25 again, on that route."""
    root = tmp / "fallback"
    make_plugin(root, "elephant-mem", version="0.1.0-beta.9",
                scripts={"recall.py": "print('recall 9')\n"})
    mem13 = make_plugin(root, "elephant-mem", version="0.1.0-beta.13",
                        scripts={"recall.py": "print('recall 13')\n"})
    wiki4 = make_plugin(root, "elephant-wiki", version="0.1.0-beta.4",
                        scripts={"wiki.py": "print('wiki 4')\n"})
    registry = root / "installed_plugins.json"

    record("E24 no registry at all falls back to the cache",
           eu.resolve_plugins(plugins_dir=root).source == "cache")
    resolution = eu.resolve_plugins(plugins_dir=root)
    record("E25 the fallback picks beta.13 over beta.9, under semver",
           resolution.path_of("elephant-mem") == mem13,
           str(resolution.path_of("elephant-mem")))
    record("E24 a note says the registry could not be read and what happened next",
           any("no plugin registry" in n and "falling back" in n
               for n in resolution.notes), resolution.notes)
    record("E24 the optional plugin resolves from the cache too",
           resolution.path_of("elephant-wiki") == wiki4,
           str(resolution.path_of("elephant-wiki")))

    for label, content in (
        ("its schema version moved", json.dumps({"version": 3, "plugins": {}})),
        ("it is not readable JSON", "{not json at all"),
        ("it is not an object", json.dumps(["elephant-mem"])),
        ("it carries no plugins object", json.dumps({"version": 2})),
        ("its plugins key is the wrong type",
         json.dumps({"version": 2, "plugins": ["elephant-mem@elephant-mem"]})),
    ):
        write(registry, content)
        resolution = eu.resolve_plugins(plugins_dir=root)
        record(f"E24 the registry is unusable because {label} — cache fallback",
               resolution.source == "cache", resolution.source)
        record(f"E24 and beta.13 still wins when {label}",
               resolution.path_of("elephant-mem") == mem13,
               str(resolution.path_of("elephant-mem")))
    registry.unlink()

    # A cache is a directory listing: it holds half-removed installs, git-style
    # checkout names, and empty shells. None of them may take the resolver down
    # or beat a complete install.
    hollow = root / "cache" / "elephant-mem" / "elephant-mem" / "0.1.0-beta.20"
    hollow.mkdir(parents=True, exist_ok=True)
    record("a version directory with no plugin manifest never outranks a "
           "complete lower one, however much higher its number",
           eu.resolve_from_cache(plugins_dir=root).path_of("elephant-mem") == mem13,
           str(eu.resolve_from_cache(plugins_dir=root).path_of("elephant-mem")))
    (root / "cache" / "elephant-mem" / "elephant-mem" / "main").mkdir(exist_ok=True)
    record("a directory whose name is not a version does not win either",
           eu.resolve_from_cache(plugins_dir=root).path_of("elephant-mem") == mem13)

    lone = tmp / "lone"
    (lone / "cache" / "elephant-mem" / "elephant-mem" / "main").mkdir(parents=True)
    record("a cache holding only a non-version directory still resolves it "
           "rather than crashing",
           eu.resolve_from_cache(plugins_dir=lone).version_of("elephant-mem")
           == "main",
           eu.resolve_from_cache(plugins_dir=lone).version_of("elephant-mem"))

    empty = tmp / "empty-cache"
    empty.mkdir()
    resolution = eu.resolve_plugins(plugins_dir=empty)
    record("no cache and no registry resolves nothing and says so",
           resolution.installs == {} and any("cache" in n for n in resolution.notes),
           resolution.notes)
    record("which compare() turns into could-not-verify",
           eu.compare(resolution.plugin_dirs, make_bundle(empty, "b")).code
           == eu.CHECK_CANNOT_VERIFY)
    (empty / "cache" / "elephant-mem" / "elephant-mem").mkdir(parents=True)
    record("a plugin directory holding no version directories is skipped",
           eu.resolve_from_cache(plugins_dir=empty).installs == {},
           eu.resolve_from_cache(plugins_dir=empty).installs)


def plugins_dir_checks(eu, tmp):
    """The resolver's own default, and the override that keeps every suite off
    the developer's real install."""
    saved = {k: os.environ.get(k) for k in ("ELEPHANT_PLUGINS_DIR", "CLAUDE_CONFIG_DIR")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        record("with nothing set the registry and cache live under "
               "~/.claude/plugins, the path this design was verified against",
               eu.default_plugins_dir() == Path.home() / ".claude" / "plugins",
               str(eu.default_plugins_dir()))
        os.environ["CLAUDE_CONFIG_DIR"] = str(tmp / "elsewhere")
        record("a relocated config dir takes the registry with it",
               eu.default_plugins_dir() == tmp / "elsewhere" / "plugins",
               str(eu.default_plugins_dir()))
        os.environ["ELEPHANT_PLUGINS_DIR"] = str(tmp / "throwaway")
        record("ELEPHANT_PLUGINS_DIR wins, which is how a suite resolves against "
               "a throwaway tree instead of a real install",
               eu.default_plugins_dir() == tmp / "throwaway",
               str(eu.default_plugins_dir()))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def interpreter_checks(eu):
    """E36 — `python3` is frequently absent from a Windows PATH, which
    `init/procedure.md:25-28` records and answers by trying `python3`, then
    `python`, then `py -3`. Nothing here assumes the name."""
    record("E36 the candidates and their order are init's, so the two agree",
           eu.INTERPRETER_CANDIDATES == (("python3",), ("python",), ("py", "-3")),
           eu.INTERPRETER_CANDIDATES)
    record("E36 the floor is the 3.10 the scripts and CI require",
           eu.MIN_PYTHON == (3, 10), eu.MIN_PYTHON)

    def probe_for(available):
        return lambda argv: available.get(tuple(argv))

    absent = probe_for({("python",): (3, 12), ("py", "-3"): (3, 11)})
    record("E36 python3 missing from PATH resolves python instead of assuming",
           eu.resolve_interpreter(running="", probe=absent) == ["python"],
           eu.resolve_interpreter(running="", probe=absent))
    only_py = probe_for({("py", "-3"): (3, 11)})
    record("E36 with only the Windows launcher answering, it is used whole",
           eu.resolve_interpreter(running="", probe=only_py) == ["py", "-3"],
           eu.resolve_interpreter(running="", probe=only_py))
    record("E36 a machine with no usable interpreter resolves None rather than "
           "handing back a name that will not run",
           eu.resolve_interpreter(running="", probe=probe_for({})) is None)
    too_old = probe_for({("python3",): (2, 7), ("python",): (3, 9),
                         ("py", "-3"): (3, 10)})
    record("E36 an interpreter below the floor is skipped, not accepted",
           eu.resolve_interpreter(running="", probe=too_old) == ["py", "-3"],
           eu.resolve_interpreter(running="", probe=too_old))
    record("E36 python3 is preferred when it does answer",
           eu.resolve_interpreter(
               running="", probe=probe_for({("python3",): (3, 10),
                                            ("python",): (3, 13)})) == ["python3"])
    record("the interpreter already running this file is preferred, being the "
           "one candidate whose version needs no probe",
           eu.resolve_interpreter(probe=probe_for({})) == [sys.executable],
           eu.resolve_interpreter(probe=probe_for({})))

    # Not a mock: whatever this machine resolves has to actually run.
    resolved = eu.resolve_interpreter()
    ok = False
    if resolved:
        done = subprocess.run(
            resolved + ["-c", "import sys; print(sys.version_info[:2] >= (3, 10))"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        ok = done.returncode == 0 and (done.stdout or "").strip() == "True"
    record("E36 the interpreter this machine resolves really runs and really "
           "reports 3.10 or newer",
           ok, f"{resolved}")
    record("a candidate that is not there probes as None instead of raising",
           eu._probe_interpreter(("definitely-not-an-interpreter-42",)) is None)


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
