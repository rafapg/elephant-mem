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
  (i) nothing assumes `python3` is on PATH;
  (j) `--check` resolves the bundle the way `wiki.py` does (`--bundle`, then
      `ELEPHANT_BUNDLE`, then the machine pointer), emits one of exactly four
      codes, says what it found on stderr for three of them and nothing at all
      for the fourth, and writes nothing anywhere.

Pure stdlib, Python 3.10+, mirroring `tests/test_backlog.py`'s conventions: a
throwaway bundle in a tempdir, fake plugin directories in the cache layout
Claude Code really uses, PASS/FAIL per check, exit code 0 only if every check
passes.
"""
import datetime
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


def write_pointer(path, bundle):
    """The machine pointer, in the shape every script in this family reads:
    one JSON object carrying `bundle_path`."""
    return write(path, json.dumps({"bundle_path": str(bundle)}, indent=2) + "\n")


def run_cli(args, *, plugins_dir, pointer, bundle_env=None, home=None,
            claude=None, stdin=""):
    """The executable as a real subprocess, which is the only way to observe
    what a mode observes: an exit code and stderr.

    `plugins_dir` and `pointer` are required rather than defaulted, so no call
    here can quietly read the developer's real install or their real
    `~/.config/elephant-mem/config.json`. `claude` is the same guarantee for the
    other side: unset, it names a program that does not exist, because the
    fallback is the real `claude` on PATH and a full run refreshes a marketplace
    clone and installs plugins with it. Invoked through `sys.executable` rather
    than by its shebang, because a Windows runner honours no shebang.

    `stdin` defaults to closed, so a run that would ask for confirmation reads
    EOF and declines rather than hanging a suite forever.
    """
    env = dict(os.environ)
    for key in ("ELEPHANT_PLUGINS_DIR", "ELEPHANT_POINTER", "ELEPHANT_BUNDLE",
                "CLAUDE_CONFIG_DIR", "ELEPHANT_CLAUDE_CLI"):
        env.pop(key, None)
    env["ELEPHANT_PLUGINS_DIR"] = str(plugins_dir)
    env["ELEPHANT_POINTER"] = str(pointer)
    env["ELEPHANT_CLAUDE_CLI"] = str(claude) if claude else "no-such-claude-cli"
    if bundle_env is not None:
        env["ELEPHANT_BUNDLE"] = str(bundle_env)
    if home is not None:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    return subprocess.run(
        [sys.executable, str(EXECUTABLE)] + [str(a) for a in args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, input=stdin,
        text=True, encoding="utf-8", errors="replace", env=env)


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


# ── a throwaway machine for the full run ─────────────────────────────────────
# The run refreshes a marketplace clone, installs plugins through Claude Code's
# CLI, copies into a bundle, runs the bundle's own pipeline and commits. Every
# one of those has to happen somewhere that is not the developer's machine, so
# the whole world is built under a tempdir: a plugin cache, a registry, a
# marketplace clone, a git bundle, and a stand-in for the CLI.

FAKE_CLAUDE = '''\
"""A stand-in for Claude Code's CLI, so no check in this suite can invoke the
real one — a full run refreshes a marketplace clone and installs plugins, and
neither belongs in a test.

It does to the two files the executable reads what the real CLI does. A
marketplace update rewrites the version the clone declares. A plugin update
copies the clone's source directory into the plugin cache under that version and
repoints the registry at it — which is why the directory the run copies from
does not exist when the run starts, and re-resolution is the only way to find it.
"""
import json
import pathlib
import shutil
import sys

PLAN = json.loads(pathlib.Path(__file__).with_name("plan.json").read_text(encoding="utf-8"))
ARGV = sys.argv[1:]
CLONE = pathlib.Path(PLAN["clone"])

with open(PLAN["log"], "a", encoding="utf-8") as handle:
    handle.write(" ".join(ARGV) + "\\n")


def manifest_of(source):
    return CLONE / source / ".claude-plugin" / "plugin.json"


if ARGV[:3] == ["plugin", "marketplace", "update"]:
    if PLAN.get("refresh_fails"):
        print("fatal: could not reach the marketplace remote", file=sys.stderr)
        sys.exit(1)
    for source, version in PLAN.get("declare", {}).items():
        path = manifest_of(source)
        declared = json.loads(path.read_text(encoding="utf-8"))
        declared["version"] = version
        path.write_text(json.dumps(declared, indent=2) + "\\n", encoding="utf-8")
    print("marketplace " + ARGV[3] + " updated")
    sys.exit(0)

if ARGV[:2] == ["plugin", "update"]:
    if PLAN.get("install_fails"):
        print("error: the download for " + ARGV[2] + " did not complete", file=sys.stderr)
        sys.exit(1)
    key = ARGV[2]
    plugin = key.split("@")[0]
    catalogue = json.loads((CLONE / ".claude-plugin" / "marketplace.json")
                           .read_text(encoding="utf-8"))
    source = {entry["name"]: entry["source"] for entry in catalogue["plugins"]}[plugin]
    version = json.loads(manifest_of(source).read_text(encoding="utf-8"))["version"]
    target = pathlib.Path(PLAN["cache"]) / PLAN["marketplace"] / plugin / version
    shutil.copytree(CLONE / source, target, dirs_exist_ok=True)
    registry = pathlib.Path(PLAN["registry"])
    installed = json.loads(registry.read_text(encoding="utf-8"))
    installed["plugins"][key] = [{"installPath": str(target), "version": version}]
    registry.write_text(json.dumps(installed, indent=2) + "\\n", encoding="utf-8")
    print("updated " + key + " to " + version)
    sys.exit(0)

print("unrecognised command: " + " ".join(ARGV), file=sys.stderr)
sys.exit(2)
'''

# Stand-ins for the two scripts the run executes out of the bundle AFTER the
# copy. build-index.py rewrites a derived file under `knowledge/`, which is what
# makes the commit cover `knowledge` and not only the two copied directories;
# validate-okf.py is the gate that decides whether there is a commit at all.
STUB_BUILD_INDEX = """\
#!/usr/bin/env python3
import pathlib
bundle = pathlib.Path(__file__).resolve().parent.parent
out = bundle / "knowledge" / "entities" / "index.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("# Entity index\\n\\n- rebuilt by build-index\\n", encoding="utf-8")
print("index rebuilt")
"""

STUB_VALIDATE_OK = """\
#!/usr/bin/env python3
print("bundle validates: 0 problems")
"""

STUB_VALIDATE_FAIL = """\
#!/usr/bin/env python3
import sys
print("knowledge/facts/2026-01-02-a-fact.md: frontmatter is missing `entities`")
sys.exit(1)
"""

# What the bundle holds that no update may ever touch: E29's list.
HAND_WRITTEN = {
    "knowledge/facts/2026-01-02-a-fact.md": "---\nid: a-fact\n---\n\nA fact.\n",
    "knowledge/sources/2026-01-02-a-source.md": "---\nid: a-source\n---\n\nA source.\n",
    "knowledge/tracking/loops/a-loop.md": "---\nid: a-loop\n---\n\nAn open loop.\n",
    "elephant.json": '{"owner": "someone"}\n',
    "config.md": "# config\n\nThe owner's file.\n",
    "vocab.json": '{"terms": ["the owner extended this"]}\n',
}


def make_fake_claude(root, plan):
    """The stand-in CLI on disk, plus the plan that drives it.

    Two files on Windows because Git Bash's `chmod` grants no NTFS execute
    permission and CreateProcess resolves a `.cmd` where it would not resolve a
    bare script; one executable file everywhere else.
    """
    home = Path(root) / "cli"
    home.mkdir(parents=True, exist_ok=True)
    write(home / "plan.json", json.dumps(plan, indent=2) + "\n")
    if os.name == "nt":
        script = write(home / "claude-fake.py", FAKE_CLAUDE)
        return write(home / "claude.cmd",
                     f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n')
    launcher = write(home / "claude", f"#!{sys.executable}\n" + FAKE_CLAUDE)
    launcher.chmod(0o755)
    return launcher


def make_clone(root, sources, marketplace="elephant-mem"):
    """The local marketplace checkout: `marketplace.json` naming each plugin and
    the directory it ships from, and each of those directories carrying the
    `plugin.json` whose `version` the CLI reads and the `assets/` an install
    places. `marketplace.json` declares no version of its own, which is why a
    clone that stopped at an older commit can report a user current."""
    clone = Path(root) / "marketplaces" / marketplace
    write(clone / ".claude-plugin" / "marketplace.json", json.dumps({
        "name": marketplace,
        "plugins": [{"name": "elephant-mem", "source": "./plugin"},
                    {"name": "elephant-wiki", "source": "./elephant-wiki"}],
    }, indent=2) + "\n")
    for source, (name, version, assets_from) in sources.items():
        write(clone / source / ".claude-plugin" / "plugin.json",
              json.dumps({"name": name, "version": version}, indent=2) + "\n")
        if assets_from:
            shutil.copytree(Path(assets_from) / "assets", clone / source / "assets",
                            dirs_exist_ok=True)
    return clone


def git_available():
    return shutil.which("git") is not None


def git(bundle, *args):
    return subprocess.run([shutil.which("git"), "-C", str(bundle), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace")


def init_git(bundle):
    """A bundle is a git repository, and the run commits into it. Local identity
    and no signing, so a runner's global config cannot decide the outcome."""
    git(bundle, "init", "-q")
    git(bundle, "config", "user.email", "ci@example.com")
    git(bundle, "config", "user.name", "Elephant CI")
    git(bundle, "config", "commit.gpgsign", "false")
    git(bundle, "add", "-A")
    git(bundle, "commit", "-q", "-m", "the bundle as it stood")
    return git(bundle, "rev-parse", "HEAD").stdout.strip()


def make_world(root, *, validator=STUB_VALIDATE_OK, declares="0.1.0-beta.14",
               refresh_fails=False, install_fails=False):
    """A machine with `elephant-mem` 0.1.0-beta.13 installed, a clone carrying
    the release that follows it, and a bundle in sync with what is installed.

    The clone holds the NEW files while still declaring the old version, which is
    the state a stale clone is really in: the refresh moves the declared version,
    and only then is the delta true. The cache holds no 0.1.0-beta.14 at all —
    the stand-in CLI creates it, so a run that copied from the directory it
    resolved at startup would copy the old files and this world would catch it.
    """
    mem13 = make_plugin(root, "elephant-mem", version="0.1.0-beta.13",
                        scripts={"recall.py": "print('recall 13')\n",
                                 "build-index.py": STUB_BUILD_INDEX,
                                 "validate-okf.py": STUB_VALIDATE_OK},
                        templates={"open-loop.md": "# loop 13\n"})
    # The next release, staged under a marketplace nothing resolves, so it
    # reaches the run only through the clone and the install — never as a
    # directory the cache fallback could have found lying around.
    incoming = make_plugin(root, "elephant-mem", version="0.1.0-beta.14",
                           marketplace="staging",
                           scripts={"recall.py": "print('recall 14')\n",
                                    "close-loops.py": "print('close 14')\n",
                                    "build-index.py": STUB_BUILD_INDEX,
                                    "validate-okf.py": validator},
                           templates={"open-loop.md": "# loop 14\n"})
    wiki4 = make_plugin(root, "elephant-wiki", version="0.1.0-beta.4",
                        scripts={"wiki.py": "print('wiki 4')\n",
                                 "wiki.js": "// spa 4\n", "graph.js": "// graph 4\n"})
    registry = make_registry(root, {
        "elephant-mem@elephant-mem": {"installPath": str(mem13),
                                      "version": "0.1.0-beta.13"},
        "elephant-wiki@elephant-mem": {"installPath": str(wiki4),
                                       "version": "0.1.0-beta.4"},
    })
    clone = make_clone(root, {
        "plugin": ("elephant-mem", "0.1.0-beta.13", incoming),
        "elephant-wiki": ("elephant-wiki", "0.1.0-beta.4", wiki4),
    })
    bundle = make_bundle(
        root, "bundle",
        scripts={"recall.py": "print('recall 13')\n",
                 "build-index.py": STUB_BUILD_INDEX,
                 "validate-okf.py": STUB_VALIDATE_OK,
                 # one wiki file frozen at an older build, and the other two
                 # never installed — the scoped copy has to tell them apart
                 "wiki.py": "print('wiki 3')\n"},
        templates={"open-loop.md": "# loop 13\n"},
        extra={**HAND_WRITTEN,
               ".gitignore": (REAL_MEM_PLUGIN / "assets" / "seed" / ".gitignore")
               .read_text(encoding="utf-8"),
               "knowledge/entities/index.md": "# Entity index\n\n- stale\n"})
    home = Path(root) / "home"
    home.mkdir(parents=True, exist_ok=True)
    log = Path(root) / "claude-calls.log"
    write(log, "")
    world = {
        "root": Path(root), "bundle": bundle, "registry": registry,
        "clone": clone, "log": log, "home": home,
        "pointer": write_pointer(Path(root) / "pointer.json", bundle),
        "plan": {"log": str(log), "clone": str(clone),
                 "cache": str(Path(root) / "cache"), "registry": str(registry),
                 "marketplace": "elephant-mem",
                 "declare": {"plugin": declares},
                 "refresh_fails": refresh_fails, "install_fails": install_fails},
    }
    world["claude"] = make_fake_claude(root, world["plan"])
    world["head"] = init_git(bundle)
    return world


def repoint(world, **changes):
    """Rewrite the stand-in CLI's plan between phases — the way a second refresh
    would find the marketplace further along than the first one did."""
    world["plan"].update(changes)
    write(Path(world["claude"]).parent / "plan.json",
          json.dumps(world["plan"], indent=2) + "\n")


def calls(world, clear=False):
    """Every command the stand-in CLI was asked to run, in order."""
    lines = [ln for ln in world["log"].read_text(encoding="utf-8").splitlines() if ln]
    if clear:
        write(world["log"], "")
    return lines


def in_world(world, *args, **kwargs):
    kwargs.setdefault("plugins_dir", world["root"])
    kwargs.setdefault("pointer", world["pointer"])
    kwargs.setdefault("home", world["home"])
    kwargs.setdefault("claude", world["claude"])
    return run_cli(args, **kwargs)


def committed_paths(bundle):
    return sorted(p for p in git(bundle, "show", "--pretty=format:", "--name-only",
                                 "HEAD").stdout.splitlines() if p)


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
        bundle_checks(eu, tmp)
        check_cli_checks(eu, tmp)
        run_checks(eu, tmp)
        failure_checks(eu, tmp)
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


# ── the bundle side of the check ─────────────────────────────────────────────

def bundle_checks(eu, tmp):
    """E9 and E12 at the function level: which bundle a run checks, and what it
    says when there is none. The order is `wiki.py:85-97`'s, so the two scripts
    in this family cannot disagree about which bundle they are looking at."""
    root = tmp / "bundleres"
    pointed = make_bundle(root, "pointed")
    other = make_bundle(root, "other")
    pointer = write_pointer(root / "pointer.json", pointed)

    resolved, why = eu.resolve_bundle(pointer=pointer)
    record("the machine pointer's bundle_path is what a bare run checks",
           resolved == pointed and why == "", f"{resolved} {why!r}")
    record("the path comes back absolute but not symlink-resolved, so the "
           "messages name the path the caller gave",
           resolved == Path(os.path.abspath(str(pointed))), str(resolved))
    record("E12 --bundle overrides the pointer, which is how a mode checks the "
           "bundle it actually resolved",
           eu.resolve_bundle(str(other), pointer=pointer)[0] == other,
           str(eu.resolve_bundle(str(other), pointer=pointer)[0]))
    record("a --bundle path is normalised rather than passed through",
           eu.resolve_bundle(str(other / ".." / "other"), pointer=pointer)[0] == other,
           str(eu.resolve_bundle(str(other / ".." / "other"), pointer=pointer)[0]))

    saved = os.environ.get(eu.BUNDLE_ENV)
    try:
        os.environ[eu.BUNDLE_ENV] = str(other)
        record("ELEPHANT_BUNDLE is honoured, since run-hooks.py sets it for "
               "every hook subprocess and a routine driving another bundle is "
               "already carrying the answer",
               eu.resolve_bundle(pointer=pointer)[0] == other,
               str(eu.resolve_bundle(pointer=pointer)[0]))
        record("--bundle still wins over the environment",
               eu.resolve_bundle(str(pointed), pointer=pointer)[0] == pointed,
               str(eu.resolve_bundle(str(pointed), pointer=pointer)[0]))
    finally:
        if saved is None:
            os.environ.pop(eu.BUNDLE_ENV, None)
        else:
            os.environ[eu.BUNDLE_ENV] = saved

    # A directory that is not a bundle must not be compared at all. Compared, it
    # would answer with a confident required-drift about the wrong directory:
    # every published file reads as missing.
    notabundle = root / "notabundle"
    (notabundle / "scripts").mkdir(parents=True)
    resolved, why = eu.resolve_bundle(str(notabundle), pointer=pointer)
    record("a directory with no knowledge/ is refused rather than compared",
           resolved is None and "knowledge/" in why, f"{resolved} {why!r}")
    resolved, why = eu.resolve_bundle(str(root / "nothing-here"), pointer=pointer)
    record("a --bundle path that does not exist is refused, and the note says "
           "it came from --bundle",
           resolved is None and "--bundle" in why, f"{resolved} {why!r}")

    # E9 — no pointer and no override, and the three ways a pointer can be there
    # and still name nothing.
    for n, (label, content, wanted) in enumerate((
        ("there is no pointer file", None, "no bundle pointer"),
        ("the pointer is not JSON", "{not json", "no usable bundle_path"),
        ("the pointer carries no bundle_path", '{"smtp": {}}', "no usable bundle_path"),
        ("bundle_path is empty", '{"bundle_path": "  "}', "empty bundle_path"),
        ("bundle_path is not a string", '{"bundle_path": 7}', "bundle_path"),
    )):
        spot = root / "pointers" / ("absent.json" if content is None else f"p{n}.json")
        if content is not None:
            write(spot, content)
        resolved, why = eu.resolve_bundle(pointer=spot)
        record(f"E9 {label} — could not verify, and the note says so",
               resolved is None and wanted in why, f"{resolved} {why!r}")
    record("E9 the note names the pointer it looked at and the flag that would "
           "have answered, since a mode's user has to act on one line",
           all(part in eu.resolve_bundle(pointer=root / "pointers" / "absent.json")[1]
               for part in ("absent.json", "--bundle")),
           eu.resolve_bundle(pointer=root / "pointers" / "absent.json")[1])

    before = snapshot(root)
    for override in ("", str(other), str(root / "nothing-here")):
        eu.resolve_bundle(override, pointer=pointer)
    record("resolving a bundle reads and never writes",
           snapshot(root) == before)


# ── `--check` as a mode really runs it ───────────────────────────────────────

def check_cli_checks(eu, tmp):
    """The four codes, their stderr notes, and writing nothing — observed
    through a real subprocess, because an exit code and stderr are the whole of
    what a mode gets. Every call routes the registry, the pointer and HOME into
    the throwaway tree, so nothing here can read or repair a real install."""
    root = tmp / "cli"
    mem = make_plugin(root, "elephant-mem", version="0.1.0-beta.13",
                      scripts={"recall.py": "print('recall 13')\n",
                               "close-loops.py": "print('close 13')\n"},
                      templates={"open-loop.md": "# loop 13\n"})
    wiki = make_plugin(root, "elephant-wiki", version="0.1.0-beta.4",
                       scripts={"wiki.py": "print('wiki 4')\n",
                                "wiki.js": "// spa 4\n", "graph.js": "// graph 4\n"})
    make_registry(root, {
        "elephant-mem@elephant-mem": {"installPath": str(mem),
                                      "version": "0.1.0-beta.13"},
        "elephant-wiki@elephant-mem": {"installPath": str(wiki),
                                       "version": "0.1.0-beta.4"},
    })
    current = make_bundle(root, "current",
                          scripts={"recall.py": "print('recall 13')\n",
                                   "close-loops.py": "print('close 13')\n"},
                          templates={"open-loop.md": "# loop 13\n"})
    stale = make_bundle(root, "stale",
                        scripts={"recall.py": "print('recall 9')\n"},
                        templates={"open-loop.md": "# loop 13\n"})
    wikistale = make_bundle(root, "wikistale",
                            scripts={"recall.py": "print('recall 13')\n",
                                     "close-loops.py": "print('close 13')\n",
                                     "wiki.py": "print('wiki 3')\n",
                                     "wiki.js": "// spa 4\n",
                                     "graph.js": "// graph 4\n"},
                            templates={"open-loop.md": "# loop 13\n"})
    pointer = write_pointer(root / "pointer.json", current)
    # Written up here with the rest of the fixtures: the E11 snapshot below
    # brackets every run, so anything the SUITE writes after it would read as
    # something the executable wrote.
    other_pointer = write_pointer(root / "stale-pointer.json", stale)
    home = root / "home"
    home.mkdir()

    def check(*args, **kwargs):
        kwargs.setdefault("plugins_dir", root)
        kwargs.setdefault("pointer", pointer)
        kwargs.setdefault("home", home)
        return run_cli(["--check", *args], **kwargs)

    before = snapshot(root)

    # code 0 — in sync, and silent. A mode runs this before every piece of work
    # it does, so a line printed on the quiet path is printed on every run.
    done = check()
    record("in sync exits 0 through the CLI",
           done.returncode == eu.CHECK_IN_SYNC,
           f"{done.returncode} {done.stderr!r}")
    record("in sync says nothing at all, on either stream",
           done.stdout == "" and done.stderr == "",
           f"out={done.stdout!r} err={done.stderr!r}")

    # code 1 — required drift, the one outcome that stops a mode
    done = check("--bundle", stale)
    record("required drift exits 1",
           done.returncode == eu.CHECK_REQUIRED_DRIFT,
           f"{done.returncode} {done.stderr!r}")
    record("required drift names the file that differs and the one that is "
           "missing, which is the whole of the motivating failure",
           "scripts/recall.py" in done.stderr
           and "scripts/close-loops.py" in done.stderr, done.stderr)
    record("the blocking message names both routes out, because a blocked user "
           "may be one whose shell has no launcher yet",
           "elephant-update" in done.stderr
           and "elephant-mem:update" in done.stderr, done.stderr)
    record("the notice goes to stderr and stdout stays clean",
           done.stdout == "", done.stdout)

    # code 2 — drift confined to the wiki's optional files
    done = check("--bundle", wikistale)
    record("optional drift exits 2",
           done.returncode == eu.CHECK_OPTIONAL_DRIFT,
           f"{done.returncode} {done.stderr!r}")
    record("optional drift names the outdated wiki file and says it is not a stop",
           "scripts/wiki.py" in done.stderr and "Not a stop." in done.stderr,
           done.stderr)
    record("an up-to-date wiki file is not reported as drift",
           "graph.js" not in done.stderr, done.stderr)

    # code 3 — E9, no pointer and no override
    done = check(pointer=root / "no-such-pointer.json")
    record("E9 no pointer and no --bundle exits 3",
           done.returncode == eu.CHECK_CANNOT_VERIFY,
           f"{done.returncode} {done.stderr!r}")
    record("E9 and the note on stderr names the pointer and --bundle",
           "no-such-pointer.json" in done.stderr and "--bundle" in done.stderr,
           done.stderr)

    done = check("--bundle", root / "cache")
    record("a path that is not a bundle is could-not-verify, not a confident "
           "required-drift about the wrong directory",
           done.returncode == eu.CHECK_CANNOT_VERIFY
           and "knowledge/" in done.stderr,
           f"{done.returncode} {done.stderr!r}")

    # E12 — the bundle a mode passes is the bundle that gets checked, whichever
    # one this machine happens to point at.
    record("E12 a mode on a non-pointer bundle checks the one it passed, even "
           "when the pointer's own bundle is in sync",
           check("--bundle", stale).returncode == eu.CHECK_REQUIRED_DRIFT
           and check("--bundle", current,
                     pointer=other_pointer).returncode == eu.CHECK_IN_SYNC)
    record("E12 ELEPHANT_BUNDLE reaches the same place, which is what a hook "
           "subprocess carries",
           check(pointer=other_pointer,
                 bundle_env=current).returncode == eu.CHECK_IN_SYNC)
    record("E12 --bundle still wins over the environment",
           check("--bundle", stale, bundle_env=current).returncode
           == eu.CHECK_REQUIRED_DRIFT)

    # E11 — `--check` writes nothing, launcher repair included. Four outcomes
    # have now run against this tree; repair belongs to the full run, which the
    # user invoked on purpose.
    record("E11 nothing under the bundles, the plugins or the pointer changed "
           "across every outcome",
           snapshot(root) == before,
           sorted(set(snapshot(root)) ^ set(before)))
    record("E11 no launcher was written, and the home directory the run saw is "
           "still empty",
           not (home / ".local" / "bin" / "elephant-update").exists()
           and snapshot(home) == {}, sorted(snapshot(home)))

    # The codes are a contract a caller matches on, so the ones this executable
    # can emit have to stay inside the four.
    done = run_cli(["--check", "--nonsense"], plugins_dir=root, pointer=pointer)
    record("a usage error exits could-not-verify and not 2, which is taken and "
           "would arrive as the reassuring 'proceed, mention the wiki'",
           done.returncode == eu.CHECK_CANNOT_VERIFY,
           f"{done.returncode} {done.stderr!r}")
    done = run_cli([], plugins_dir=root, pointer=pointer)
    record("a run without --check never answers with one of the check's codes",
           done.returncode not in (eu.CHECK_IN_SYNC, eu.CHECK_REQUIRED_DRIFT,
                                   eu.CHECK_OPTIONAL_DRIFT, eu.CHECK_CANNOT_VERIFY),
           f"{done.returncode} {done.stderr!r}")

    # A resolution note has to reach the reader: compare() sees only that a
    # plugin did not resolve and cannot say why.
    gaps = tmp / "cli-gaps"
    gone = gaps / "cache" / "elephant-mem" / "elephant-mem" / "0.1.0-beta.12"
    make_bundle(gaps, "bundle")
    make_registry(gaps, {"elephant-mem@elephant-mem":
                         {"installPath": str(gone), "version": "0.1.0-beta.12"}})
    done = run_cli(["--check", "--bundle", gaps / "bundle"],
                   plugins_dir=gaps, pointer=gaps / "no-pointer.json")
    record("a registry naming a directory that is gone exits 3",
           done.returncode == eu.CHECK_CANNOT_VERIFY,
           f"{done.returncode} {done.stderr!r}")
    record("and the resolution's note reaches stderr, since could-not-verify "
           "otherwise says nothing about which side failed to read",
           "not on disk" in done.stderr and "0.1.0-beta.12" in done.stderr,
           done.stderr)

    # The usage text carries the rule a caller implements, since the caller is
    # what turns three codes into two decisions.
    done = run_cli(["--help"], plugins_dir=root, pointer=pointer)
    record("the usage text states all four outcomes and the everything-else rule",
           all(part in done.stdout for part in
               ("in sync", "required drift", "could-not-verify", "EVERYTHING else")),
           done.stdout)


# ── the full run ─────────────────────────────────────────────────────────────

def run_checks(eu, tmp):
    """E18, E19, E28, E29, E30 and E39 in the order a user meets them: a plan,
    the run that follows it, and the run after that with nothing left to do."""
    if not git_available():
        record("git on PATH (every GitHub-hosted runner has it)", False,
               "git not found — the full run commits, so these checks cannot run")
        return
    world = make_world(tmp / "run")
    bundle, registry = world["bundle"], world["registry"]

    # ── `--plan` ─────────────────────────────────────────────────────────────
    before = snapshot(bundle)
    declared_before = registry.read_text(encoding="utf-8")
    done = in_world(world, "--plan")
    record("E18 --plan exits 0", done.returncode == eu.RUN_OK,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E18 the delta is printed, installed against what the clone now offers",
           "0.1.0-beta.13 → 0.1.0-beta.14" in done.stdout, done.stdout)
    record("E18 the refresh ran first, and exactly once — a delta read before it "
           "can report 'current' off a clone that stopped at an older commit",
           calls(world) == ["plugin marketplace update elephant-mem"], calls(world))
    record("E18 the plan names the file the new release adds and the two it moves",
           all(part in done.stdout for part in
               ("scripts/close-loops.py", "scripts/recall.py",
                "templates/open-loop.md")), done.stdout)
    record("E18 the plan names the outdated wiki file the bundle has",
           "scripts/wiki.py" in done.stdout, done.stdout)
    record("E18 and leaves out the wiki files the bundle never had, which a copy "
           "would not install either",
           "scripts/graph.js" not in done.stdout
           and "scripts/wiki.js" not in done.stdout, done.stdout)
    record("E18 --plan installed nothing: the registry still names beta.13",
           registry.read_text(encoding="utf-8") == declared_before)
    record("E18 --plan wrote nothing into the bundle — no copy, no index rewrite, "
           "no commit, no stamp",
           snapshot(bundle) == before,
           sorted(set(snapshot(bundle)) ^ set(before)))

    # ── the run that follows it ──────────────────────────────────────────────
    # A second refresh would find the marketplace further along. `--no-refresh`
    # is what keeps the delta the user approved from moving under them.
    repoint(world, declare={"plugin": "0.1.0-beta.15"})
    calls(world, clear=True)
    done = in_world(world, "--yes", "--no-refresh")
    record("the run exits 0", done.returncode == eu.RUN_OK,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E19 --no-refresh runs no second marketplace update",
           not any("marketplace" in line for line in calls(world)), calls(world))
    record("E19 the version installed is the one the plan showed, not the one a "
           "second refresh would have moved to",
           "0.1.0-beta.14" in registry.read_text(encoding="utf-8")
           and "0.1.0-beta.15" not in registry.read_text(encoding="utf-8"),
           registry.read_text(encoding="utf-8"))
    record("one `claude plugin update` per installed plugin of the family, each "
           "carrying -y, which the CLI requires off a TTY",
           calls(world) == ["plugin update elephant-mem@elephant-mem -y",
                            "plugin update elephant-wiki@elephant-mem -y"],
           calls(world))
    record("the copy came from the directory the install had just written — one "
           "that did not exist when the run started, so only re-resolution finds it",
           (bundle / "scripts" / "recall.py").read_text(encoding="utf-8")
           == "print('recall 14')\n",
           (bundle / "scripts" / "recall.py").read_text(encoding="utf-8"))
    record("a required script the bundle lacked is installed — the motivating "
           "failure, repaired",
           (bundle / "scripts" / "close-loops.py").is_file())
    record("templates move with the scripts",
           (bundle / "templates" / "open-loop.md").read_text(encoding="utf-8")
           == "# loop 14\n")
    record("the outdated wiki file the bundle had is refreshed",
           (bundle / "scripts" / "wiki.py").read_text(encoding="utf-8")
           == "print('wiki 4')\n")
    record("and the wiki files it never had are still not there: a bundle that "
           "never built a wiki does not get one from an update",
           not (bundle / "scripts" / "graph.js").exists()
           and not (bundle / "scripts" / "wiki.js").exists())
    record("E29 no hand-written fact, loop or source changed, and elephant.json, "
           "config.md and vocab.json are untouched",
           all((bundle / rel).read_text(encoding="utf-8") == content
               for rel, content in HAND_WRITTEN.items()),
           [rel for rel, content in HAND_WRITTEN.items()
            if (bundle / rel).read_text(encoding="utf-8") != content])
    record("the index was rebuilt, by the freshly copied build-index.py",
           "rebuilt by build-index" in
           (bundle / "knowledge" / "entities" / "index.md").read_text(encoding="utf-8"))
    committed = committed_paths(bundle)
    record("E28 the commit covers knowledge as well as scripts and templates — "
           "today's update leaves the index rewrite for the next `git add -A`",
           {"knowledge/entities/index.md", "scripts/close-loops.py",
            "scripts/recall.py", "templates/open-loop.md"} <= set(committed),
           committed)
    record("E28 the gitignored stamp is not in the commit",
           not any("last-update-check" in path for path in committed), committed)
    record("E28 the commit is local: no remote was configured and none was added",
           git(bundle, "remote").stdout.strip() == "",
           git(bundle, "remote").stdout)
    stamp = json.loads((bundle / "state" / "last-update-check.json")
                       .read_text(encoding="utf-8"))
    record("E39 the run stamps last-update-check.json with the version it saw",
           stamp.get("latest_seen") == "0.1.0-beta.14", stamp)
    record("E39 and a fresh last_checked, which is what holds the weekly nudge",
           abs((datetime.datetime.now().astimezone()
                - datetime.datetime.fromisoformat(stamp["last_checked"]))
               .total_seconds()) < 300, stamp)
    record("the run says a restart is needed to load the plugin just installed",
           "restart" in done.stdout and "0.1.0-beta.14" in done.stdout, done.stdout)

    # ── E30: the same run again, with nothing left to do ─────────────────────
    head = git(bundle, "rev-parse", "HEAD").stdout.strip()
    stamped = (bundle / "state" / "last-update-check.json").read_text(encoding="utf-8")
    calls(world, clear=True)
    done = in_world(world, "--yes", "--no-refresh")
    record("E30 a run with nothing to copy exits 0 and says the bundle is in sync",
           done.returncode == eu.RUN_OK and "already in sync" in done.stdout,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E30 nothing was staged, so no commit was attempted rather than an "
           "empty one failing the run",
           git(bundle, "rev-parse", "HEAD").stdout.strip() == head
           and "no commit was made" in done.stdout, done.stdout)
    record("E30 and it stamps anyway, so the nudge is still throttled",
           (bundle / "state" / "last-update-check.json").read_text(encoding="utf-8")
           != stamped)
    record("a run that moved no version says nothing about restarting",
           "restart" not in done.stdout, done.stdout)

    # The flags belong to the run, and `--check` is the one path that promises it
    # wrote nothing. Accepting them there would have it answering for a run it
    # never performs.
    for flags in (["--check", "--yes"], ["--check", "--no-refresh"],
                  ["--check", "--plan"]):
        done = in_world(world, *flags)
        record(f"`{' '.join(flags)}` is a usage error, and exits could-not-verify",
               done.returncode == eu.CHECK_CANNOT_VERIFY,
               f"{done.returncode} {done.stderr!r}")


def failure_checks(eu, tmp):
    """E20, E21, E22, E26 and E27 — the three ways a run stops, and what it
    leaves behind when it stops after the copy."""
    if not git_available():
        return

    # E20 — the one confirmation, declined.
    world = make_world(tmp / "declined")
    bundle = world["bundle"]
    before = snapshot(bundle)
    done = in_world(world, stdin="n\n")
    record("E20 declining exits the declined code, which is neither success nor "
           "failure and neither of the check's",
           done.returncode == eu.RUN_DECLINED,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E20 nothing was installed: the refresh ran and no plugin update did",
           calls(world) == ["plugin marketplace update elephant-mem"], calls(world))
    record("E20 and nothing was copied, indexed, committed or stamped",
           snapshot(bundle) == before,
           sorted(set(snapshot(bundle)) ^ set(before)))
    record("E20 the refreshed clone is left as it is — deliberate, and harmless",
           "0.1.0-beta.14" in (world["clone"] / "plugin" / ".claude-plugin"
                               / "plugin.json").read_text(encoding="utf-8"))
    calls(world, clear=True)
    done = in_world(world)
    record("E20 a closed stdin is a decline too, rather than a run installing on "
           "a question nobody answered",
           done.returncode == eu.RUN_DECLINED, done.stderr)
    calls(world, clear=True)
    done = in_world(world, stdin="y\n")
    record("and answering yes is what proceeds — the decline above is not the "
           "prompt refusing every answer",
           done.returncode == eu.RUN_OK
           and (bundle / "scripts" / "close-loops.py").is_file(),
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")

    # E21 — the marketplace refresh fails.
    world = make_world(tmp / "norefresh", refresh_fails=True)
    bundle = world["bundle"]
    before = snapshot(bundle)
    done = in_world(world, "--yes")
    record("E21 a failed marketplace refresh exits failed-before-copy",
           done.returncode == eu.RUN_FAILED_BEFORE_COPY,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E21 it is reported, with the CLI's own words rather than a summary",
           "could not be refreshed" in done.stderr
           and "could not reach the marketplace remote" in done.stderr, done.stderr)
    record("E21 no plugin was updated after it",
           calls(world) == ["plugin marketplace update elephant-mem"], calls(world))
    record("E21 and the bundle is untouched", snapshot(bundle) == before)

    # E22 — `claude plugin update` fails.
    world = make_world(tmp / "noinstall", install_fails=True)
    bundle = world["bundle"]
    before = snapshot(bundle)
    done = in_world(world, "--yes")
    record("E22 a failed plugin update exits failed-before-copy",
           done.returncode == eu.RUN_FAILED_BEFORE_COPY,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E22 the failing command and its output are both named",
           "plugin update elephant-mem@elephant-mem" in done.stderr
           and "did not complete" in done.stderr, done.stderr)
    record("E22 it stops at the first failure rather than trying the rest",
           calls(world) == ["plugin marketplace update elephant-mem",
                            "plugin update elephant-mem@elephant-mem -y"],
           calls(world))
    record("E22 and nothing was copied", snapshot(bundle) == before)

    # E26, E27 — the validator fails after the copy.
    world = make_world(tmp / "invalid", validator=STUB_VALIDATE_FAIL)
    bundle = world["bundle"]
    head = world["head"]
    done = in_world(world, "--yes")
    record("E26 a failed validation after the copy exits failed-after-copy",
           done.returncode == eu.RUN_FAILED_AFTER_COPY,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E26 the validator's own output is printed, not a summary of it",
           "frontmatter is missing `entities`" in done.stderr, done.stderr)
    record("E26 the validator that ran is the freshly copied one — the old copy "
           "in the bundle would have passed",
           "sys.exit(1)" in (bundle / "scripts" / "validate-okf.py")
           .read_text(encoding="utf-8"))
    record("E26 nothing was committed",
           git(bundle, "rev-parse", "HEAD").stdout.strip() == head)
    record("E26 nothing was stamped: holding the weekly nudge over a bundle that "
           "has just failed is the one thing the stamp must not do",
           not (bundle / "state" / "last-update-check.json").exists())
    record("E26 and the copy is still on disk — there is no rollback, on purpose",
           (bundle / "scripts" / "close-loops.py").is_file())
    record("E27 the restore commands are printed, covering knowledge as well as "
           "scripts and templates, since the index rewrite is in there too",
           all(f"{verb} {' '.join(('knowledge', 'scripts', 'templates'))}"
               in done.stderr for verb in ("checkout --", "clean -fd")),
           done.stderr)
    record("E27 the index rewrite the restore has to undo really happened",
           "rebuilt by build-index" in
           (bundle / "knowledge" / "entities" / "index.md").read_text(encoding="utf-8"))
    record("E26 the failure names both routes out, as every blocking message does",
           "elephant-update" in done.stderr and "elephant-mem:update" in done.stderr,
           done.stderr)


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
