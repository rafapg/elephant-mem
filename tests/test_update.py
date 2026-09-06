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

The last four sections are the ones no single part could reach from inside
itself, because each crosses two of the others: the file's place in the tree
against the path the launcher's resolver builds by hand; both resolution routes
against one machine's `--check`; the restore commands a failed run prints
against a git that has to accept them and really put the bundle back; the run's
write footprint measured over the whole tree instead of against a list someone
keeps current; and a launcher that will not run arriving after a commit and a
stamp that already happened, which is the ordering's entire claim.

One of those checks does its real work on a Windows runner only — `cmd.exe` is
the only thing that can say whether the `.cmd` half of the pair runs. It is
still RECORDED on every OS: `smoke.py` compares the total this file prints
against the number the CHANGELOG declares, so a check that appears on one
platform and not another would make that number true on one runner and false on
the next two.

Pure stdlib, Python 3.10+, mirroring `tests/test_backlog.py`'s conventions: a
throwaway bundle in a tempdir, fake plugin directories in the cache layout
Claude Code really uses, PASS/FAIL per check, exit code 0 only if every check
passes, and a closing `N/M checks passed` line, which is what `smoke.py` reads.
"""
import base64
import datetime
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
                other_assets=None, marketplace="elephant-mem", bin_files=None):
    """A fake installed plugin directory in the layout Claude Code uses:
    `<root>/cache/<marketplace>/<plugin>/<version>/`, so the same helper serves
    the resolution tests. `other_assets` are assets outside the published set;
    `bin_files` are files under `bin/`, which is where the executable a launcher
    hands off to lives and which is outside `assets/` entirely."""
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
    for filename, content in (bin_files or {}).items():
        write(plugin_root / "bin" / filename, content).chmod(0o755)
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


SANDBOXED_ENV = ("ELEPHANT_PLUGINS_DIR", "ELEPHANT_POINTER", "ELEPHANT_BUNDLE",
                 "ELEPHANT_BIN_DIR", "CLAUDE_CONFIG_DIR", "ELEPHANT_CLAUDE_CLI")


def clean_env(plugins_dir, *, pointer=None, claude=None, bundle_env=None,
              bin_dir=None, home=None):
    """The environment both subprocess helpers run under, built in one place.

    Every name in `SANDBOXED_ENV` is dropped before anything is set, so a value
    the developer happens to export cannot reach a child and send it at a real
    install, a real pointer, a real `~/.local/bin` or the real `claude`. One
    helper rather than a copy per call site: a seventh name added to that tuple
    has to reach both, and a call site that missed it would not fail loudly, it
    would quietly read or write outside the throwaway tree.
    """
    env = dict(os.environ)
    for key in SANDBOXED_ENV:
        env.pop(key, None)
    env["ELEPHANT_PLUGINS_DIR"] = str(plugins_dir)
    env["ELEPHANT_CLAUDE_CLI"] = str(claude) if claude else "no-such-claude-cli"
    if pointer is not None:
        env["ELEPHANT_POINTER"] = str(pointer)
    if bundle_env is not None:
        env["ELEPHANT_BUNDLE"] = str(bundle_env)
    if bin_dir is not None:
        env["ELEPHANT_BIN_DIR"] = str(bin_dir)
    if home is not None:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    return env


def run_cli(args, *, plugins_dir, pointer, bundle_env=None, home=None,
            claude=None, stdin="", bin_dir=None):
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
    EOF and declines rather than hanging a suite forever. `bin_dir` is the same
    guarantee for the launcher: unset, HOME already points into the throwaway
    tree, and it is named outright where a check wants to look at what landed.
    """
    env = clean_env(plugins_dir, pointer=pointer, claude=claude,
                    bundle_env=bundle_env, bin_dir=bin_dir, home=home)
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
    for source, (name, version, ships_from) in sources.items():
        write(clone / source / ".claude-plugin" / "plugin.json",
              json.dumps({"name": name, "version": version}, indent=2) + "\n")
        # `assets/` is what an install places in a bundle; `bin/` is what the
        # launcher hands off to. The clone carries both because the stand-in CLI
        # copies this directory whole, exactly as an install does.
        for part in ("assets", "bin"):
            if ships_from and (Path(ships_from) / part).is_dir():
                shutil.copytree(Path(ships_from) / part, clone / source / part,
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
               refresh_fails=False, install_fails=False, ships_executable=True):
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
                           templates={"open-loop.md": "# loop 14\n"},
                           # The release that introduces the launcher is the
                           # first to carry the executable it hands off to; the
                           # beta.13 already installed does not, which is the
                           # state every machine is really in.
                           # `ships_executable=False` is the release that moved
                           # or dropped it: the copy, the commit and the stamp
                           # all still happen and only the launcher has nothing
                           # to hand off to, which is E33 on the full run.
                           bin_files={"elephant-update":
                                      EXECUTABLE.read_text(encoding="utf-8")}
                           if ships_executable else None)
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
        dirty_knowledge_checks(eu, tmp)
        failure_checks(eu, tmp)
        launcher_checks(eu, tmp)
        interpreter_checks(eu)
        real_tree_checks(eu, tmp)
        placement_checks(eu)
        both_routes_checks(eu, tmp)
        windows_pair_checks(eu, tmp)
        report_checks(eu, tmp)

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
    # A launcher already on disk, written the day the registry looked different.
    # HOME is the throwaway one, so `~/.local/bin` is here and not the runner's.
    launcher = write(world["home"] / ".local" / "bin" / "elephant-update",
                     "#!/bin/sh\n# an older resolver, frozen\nexit 0\n")

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
    record("E18 and it rewrote no launcher either: a plan is a plan",
           launcher.read_text(encoding="utf-8").endswith("exit 0\n"),
           launcher.read_text(encoding="utf-8")[:120])

    # ── the run that follows it ──────────────────────────────────────────────
    # A second refresh would find the marketplace further along. `--no-refresh`
    # is what keeps the delta the user approved from moving under them.
    repoint(world, declare={"plugin": "0.1.0-beta.15"})
    calls(world, clear=True)
    # Age the clone the install copies from, so "the copy is new" is a claim the
    # check can fail. Left fresh, every source is younger than the run anyway and
    # the assertion below holds whether or not the copy preserves a timestamp.
    aged = time.time() - 90 * 24 * 3600
    for path in Path(world["clone"]).rglob("*"):
        if path.is_file():
            os.utime(path, (aged, aged))
    # A second of slack: a filesystem whose timestamps are coarser than the test
    # is not the thing under test here.
    copy_started = time.time() - 1
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
    record("a copied file is new as of the copy, not as of whenever the plugin's "
           "own file was written: carrying the source mtime over leaves git free "
           "to trust an index entry the copy has just invalidated, and the commit "
           "then skips that file while adding the untracked ones beside it",
           all((bundle / rel).stat().st_mtime >= copy_started
               for rel in ("scripts/recall.py", "templates/open-loop.md")),
           {rel: (bundle / rel).stat().st_mtime
            for rel in ("scripts/recall.py", "templates/open-loop.md")}
           | {"copy_started": copy_started})
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
    record("E31 the run rewrote the launcher that was already there, rather than "
           "leaving a copy of the resolver frozen at the day it was written",
           launcher.read_text(encoding="utf-8") == eu.launcher_text(),
           launcher.read_text(encoding="utf-8")[:200])
    record("E33 and it verified it by running it, which reached the plugin the "
           "run had just installed — the launcher is written last, so this can "
           "only ever be a report",
           "Verified it" in done.stdout, done.stdout)

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
    record("E31 a run with nothing to copy still rewrites the launcher: what "
           "goes stale in it is the resolver, not the bundle",
           launcher.read_text(encoding="utf-8") == eu.launcher_text())
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


def dirty_knowledge_checks(eu, tmp):
    """E29, on the tree state the rest of the suite never produces.

    Everywhere else the bundle is committed whole before a run starts, so the
    commit step never meets a `knowledge/` that was already dirty and E29 is
    only ever read as a content check. The guarantee is wider than that: an
    `ingest` or `capture` interrupted before its own final commit, or a person
    editing a fact by hand, leaves real hand-written content uncommitted, and a
    run that stages the whole directory would carry it into a commit whose
    message mentions only scripts and templates.
    """
    if not git_available():
        record("git on PATH for the dirty-tree checks", False, "git not found")
        return
    world = make_world(tmp / "dirty")
    bundle = world["bundle"]
    edited = bundle / "knowledge" / "facts" / "2026-01-02-a-fact.md"
    original = edited.read_text(encoding="utf-8")
    mid_edit = original.replace("A fact.", "A fact, still being written.")
    write(edited, mid_edit)
    untracked = write(bundle / "knowledge" / "facts" / "2026-01-03-half-done.md",
                      "---\nid: half-done\n---\n\nAn ingest that never finished.\n")

    done = in_world(world, "--yes")
    record("E29 a run over a bundle with uncommitted hand-written work still "
           "succeeds", done.returncode == eu.RUN_OK,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    committed = committed_paths(bundle)
    record("E29 the commit still carries the index rewrite the run itself caused",
           "knowledge/entities/index.md" in committed, committed)
    record("E29 and the scripts it copied",
           "scripts/close-loops.py" in committed, committed)
    record("E29 but not the fact somebody was midway through editing — a run "
           "that swept it in would bury a person's work under a commit message "
           "about scripts and templates",
           "knowledge/facts/2026-01-02-a-fact.md" not in committed, committed)
    record("E29 nor the untracked one an interrupted ingest left behind",
           "knowledge/facts/2026-01-03-half-done.md" not in committed, committed)
    record("E29 both are still on disk with the words their author left there",
           edited.read_text(encoding="utf-8") == mid_edit
           and "never finished" in untracked.read_text(encoding="utf-8"))
    still_dirty = git(bundle, "status", "--porcelain", "--", "knowledge").stdout
    record("E29 and both are still uncommitted, so the next ingest commits them "
           "itself rather than finding its work already gone",
           "2026-01-02-a-fact.md" in still_dirty
           and "2026-01-03-half-done.md" in still_dirty, still_dirty)


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


# ── the launcher ─────────────────────────────────────────────────────────────
# The PATH that carries the command inside Claude Code belongs to Claude Code's
# own processes, so a terminal needs a launcher, and it cannot be a symlink: a
# plugin installs into a new versioned directory on every update and the link
# would dangle exactly when the user updated. So the launcher carries the
# resolver, which is a SECOND copy of logic that already exists in the
# executable — and the whole risk of a second copy is that it drifts. These
# checks execute that copy rather than reading it.

def load_resolver(eu):
    """The launcher's own copy of the resolver, executed the way the launcher
    executes it. `__name__` is anything but `__main__`, so its `sys.exit(main())`
    does not take the suite down with it."""
    namespace = {"__name__": "launcher_resolver"}
    exec(compile(eu.LAUNCHER_RESOLVER, "<the launcher's resolver>", "exec"),
         namespace)
    return namespace


def run_launcher(target, args, *, plugins_dir, pointer=None, home=None):
    """The launcher as a real subprocess, which is the only way to observe what
    a terminal observes. Same `clean_env` as `run_cli`, so nothing here can
    reach a real install, a real pointer or the real `claude`."""
    env = clean_env(plugins_dir, pointer=pointer, home=home)
    return subprocess.run([str(target)] + [str(a) for a in args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          input="", text=True, encoding="utf-8",
                          errors="replace", env=env)


def launcher_machine(root, *, carries_bin=True):
    """A machine with `elephant-mem` 0.1.0-beta.13 installed over an older
    0.1.0-beta.9 still in the cache, and a bundle in sync with it.

    `carries_bin=False` is the plugin that predates this executable: resolution
    succeeds and there is nothing at the end of it to run, which is the state
    every already-installed bundle is in on the release that adds the launcher.
    """
    executable = EXECUTABLE.read_text(encoding="utf-8")
    published = {"scripts": {"recall.py": "print('recall 13')\n"},
                 "templates": {"open-loop.md": "# loop 13\n"}}
    mem13 = make_plugin(root, "elephant-mem", version="0.1.0-beta.13",
                        bin_files={"elephant-update": executable} if carries_bin
                        else None, **published)
    # Older, complete, and carrying the executable too: if anything here ever
    # sorted versions as text, `beta.9` would follow `beta.13` and this is the
    # directory that would answer.
    make_plugin(root, "elephant-mem", version="0.1.0-beta.9",
                bin_files={"elephant-update": executable},
                scripts={"recall.py": "print('recall 9')\n"},
                templates={"open-loop.md": "# loop 9\n"})
    registry = make_registry(root, {
        "elephant-mem@elephant-mem": {"installPath": str(mem13),
                                      "version": "0.1.0-beta.13"}})
    bundle = make_bundle(root, "bundle", **published)
    stale = make_bundle(root, "stale", scripts={"recall.py": "print('recall 9')\n"},
                        templates={"open-loop.md": "# loop 13\n"})
    home = Path(root) / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {"root": Path(root), "plugin": mem13, "registry": registry,
            "bundle": bundle, "stale": stale, "home": home,
            "pointer": write_pointer(Path(root) / "pointer.json", bundle)}


def launcher_checks(eu, tmp):
    """E31, E32, E33, E35 and E36 — what the two generated files say, that they
    are rewritten rather than repaired, and that the pair really runs."""
    resolver = load_resolver(eu)
    posix = eu.launcher_text()
    windows = eu.launcher_cmd_text()

    # ── the resolver the launcher carries ────────────────────────────────────
    record("E36 the launcher's resolver orders versions as semver: sorted as "
           "text 0.1.0-beta.9 follows 0.1.0-beta.13, which is the older plugin "
           "and the failure this command exists to close",
           resolver["version_key"]("0.1.0-beta.13")
           > resolver["version_key"]("0.1.0-beta.9"))
    ladder = ["0.1.0-alpha.99", "0.1.0-beta", "0.1.0-beta.9", "0.1.0-beta.13",
              "0.1.0", "0.2.0"]
    record("and it agrees with the executable's own ordering all the way up the "
           "ladder — the one copy of this logic outside that file must not drift",
           [resolver["version_key"](v) < resolver["version_key"](w)
            for v, w in zip(ladder, ladder[1:])]
           == [eu.parse_version(v) < eu.parse_version(w)
               for v, w in zip(ladder, ladder[1:])])
    record("the resolver reads the registry first and the cache only as a "
           "fallback, the way the executable does",
           callable(resolver.get("from_registry"))
           and callable(resolver.get("from_cache")))

    # ── what the two files say ───────────────────────────────────────────────
    record("the POSIX launcher is a shell script",
           posix.startswith("#!/bin/sh\n"), posix[:40])
    record("E36 it walks init's interpreter candidates, in init's order, and "
           "assumes none of them",
           all(" ".join(argv) in posix for argv in eu.INTERPRETER_CANDIDATES)
           and posix.index("python3") < posix.index("py -3"), posix[:1200])
    record("E36 it probes for the floor rather than trusting a name",
           "sys.version_info[:2] >= (3, 10)" in posix)
    record("it carries the resolver in the clear, not a path to one: a second "
           "file beside it is a file a user can delete",
           eu.LAUNCHER_RESOLVER in posix)
    record("the resolver is embedded quoted, so the shell hands Python the "
           "source rather than interpreting it",
           "-c '" in posix and posix.count("exec $ELEPHANT_PY") == 1, posix[-400:])
    record("not a heredoc, which would be the script's own stdin — and the run "
           "it hands off to asks the user one question",
           "<<" not in posix)
    record("a machine with no interpreter at all exits could-not-verify rather "
           "than pretending it checked",
           f"exit {eu.CHECK_CANNOT_VERIFY}\n" in posix, posix[-200:])
    record("both files are pure ASCII: a batch comment renders in whatever "
           "codepage the console has",
           all(ord(c) < 128 for c in posix) and all(ord(c) < 128 for c in windows))

    # ── E35: the Windows half ────────────────────────────────────────────────
    payload = [ln for ln in windows.split("\r\n") if ln.startswith("set \"ELEPHANT_B64=")]
    decoded = ""
    if payload:
        decoded = base64.b64decode(payload[0].split("=", 1)[1].rstrip('"')).decode("utf-8")
    record("E35 the .cmd carries the same resolver, from the same constant, so "
           "the two halves of the pair cannot disagree",
           decoded == eu.LAUNCHER_RESOLVER, f"{len(decoded)} vs {len(eu.LAUNCHER_RESOLVER)}")
    record("E35 base64 because a batch variable cannot hold a newline, and the "
           "alphabet needs no batch escaping",
           payload and set(payload[0].split("=", 1)[1].rstrip('"'))
           <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="))
    record("E35 CRLF, which is what cmd.exe expects of a batch file",
           windows.endswith("\r\n") and "\n" not in windows.replace("\r\n", ""))
    record("E35 it walks the same candidates as the POSIX half",
           all(f'set "ELEPHANT_PY={" ".join(argv)}"' in windows
               for argv in eu.INTERPRETER_CANDIDATES), windows[:600])
    record("E35 no rem line carries a shell metacharacter — rem is a command "
           "like any other and an unescaped ampersand ends it",
           not any(set(ln) & set("&|<>^%") for ln in windows.split("\r\n")
                   if ln.startswith("rem ")),
           [ln for ln in windows.split("\r\n") if ln.startswith("rem ")])
    longest = max(len(ln) for ln in windows.split("\r\n"))
    record("E35 every line stays clear of cmd.exe's 8191-character limit, which "
           "the base64 payload is the only thing near",
           longest < 7000, longest)

    # ── E31: written, and rewritten ──────────────────────────────────────────
    root = tmp / "launcher"
    root.mkdir(parents=True, exist_ok=True)
    empty = root / "bin-empty"
    written, error = eu.write_launcher(empty)
    record("E31 the launcher is written into a directory that did not exist",
           not error and (empty / "elephant-update").is_file(), error)
    record("E31 and it is executable, since a shell has to run it by name",
           os.name == "nt" or os.access(empty / "elephant-update", os.X_OK))
    record("E35 the .cmd is written on Windows and nowhere else: elsewhere it is "
           "a file nothing can run",
           (empty / "elephant-update.cmd").is_file() == (os.name == "nt"))
    both = root / "bin-both"
    forced, _ = eu.write_launcher(both, windows=True)
    record("E35 the pair, when the machine is the one that needs it",
           [p.name for p in forced] == ["elephant-update", "elephant-update.cmd"],
           [p.name for p in forced])
    stale = write(root / "bin-stale" / "elephant-update",
                  "#!/bin/sh\n# a launcher written the day the registry looked "
                  "different\nexit 0\n")
    eu.write_launcher(stale.parent)
    record("E31 a launcher already there, carrying an older resolver, is "
           "rewritten rather than repaired — repairing only what looks broken "
           "is what would strand every launcher on disk",
           stale.read_text(encoding="utf-8") == posix)

    # ── the pair really runs, and hands off ──────────────────────────────────
    machine = launcher_machine(root / "machine")
    written, _ = eu.write_launcher(root / "machine" / "bin", windows=(os.name == "nt"))
    entry = eu.launcher_entry(written)
    done = run_launcher(entry, ["--check"], plugins_dir=machine["root"],
                        pointer=machine["pointer"], home=machine["home"])
    record("the launcher resolves the installed plugin and hands off: a bundle "
           "in sync exits 0, silently",
           done.returncode == eu.CHECK_IN_SYNC and not done.stdout and not done.stderr,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    done = run_launcher(entry, ["--check", "--bundle", machine["stale"]],
                        plugins_dir=machine["root"], pointer=machine["pointer"],
                        home=machine["home"])
    record("arguments are forwarded whole and the exit code comes back whole: a "
           "stale bundle through the launcher is required drift",
           done.returncode == eu.CHECK_REQUIRED_DRIFT
           and "scripts/recall.py" in done.stderr,
           f"{done.returncode}\n{done.stderr}")
    (machine["registry"]).unlink()
    done = run_launcher(entry, ["--check"], plugins_dir=machine["root"],
                        pointer=machine["pointer"], home=machine["home"])
    record("with the registry gone it falls back to semver over the cache and "
           "still finds beta.13 — beta.9 is sitting right there, complete, and "
           "would answer a text sort",
           done.returncode == eu.CHECK_IN_SYNC, f"{done.returncode}\n{done.stderr}")

    bare = launcher_machine(root / "bare", carries_bin=False)
    done = run_launcher(entry, ["--check"], plugins_dir=bare["root"],
                        pointer=bare["pointer"], home=bare["home"])
    record("E33 a plugin that carries no executable — every bundle installed "
           "before this release — leaves the launcher with nothing to run, and "
           "it says so with both routes out rather than failing silently",
           done.returncode == eu.CHECK_CANNOT_VERIFY
           and "bin/elephant-update" in done.stderr
           and "elephant-mem:update" in done.stderr,
           f"{done.returncode}\n{done.stderr}")

    # ── `--install-launcher`, the route `init` takes ─────────────────────────
    machine = launcher_machine(root / "install")
    bins = root / "install" / "bin"
    done = run_cli(["--install-launcher"], plugins_dir=machine["root"],
                   pointer=machine["pointer"], home=machine["home"],
                   bin_dir=bins)
    record("--install-launcher exits 0 and writes the pair, installing nothing "
           "and reading no bundle: init has just built one against a plugin it "
           "did not install",
           done.returncode == eu.RUN_OK and (bins / "elephant-update").is_file(),
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E33 it verifies the file instead of asserting it runs, by running it",
           "Verified it" in done.stdout, done.stdout)
    record("E32 the install directory is not on PATH, so the line to add is "
           "printed — and no profile is edited",
           "not on your PATH" in done.stdout
           and f'export PATH="{bins}:$PATH"' in done.stdout, done.stdout)
    saved = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = str(bins) + os.pathsep + saved
        record("E32 and when it IS on PATH there is no line to add — the advice "
               "is for the case that needs it, not a line on every run",
               eu.path_advice(bins) == [], eu.path_advice(bins))
    finally:
        os.environ["PATH"] = saved

    # E32 — the Windows line, checked on every OS.
    #
    # `path_advice` only appends it under `os.name == "nt"`, so reading it
    # through that function would leave the assertion running in two of the six
    # CI cells and vacuous in the other four. The advice is worth pinning
    # everywhere: `setx PATH "%PATH%;<dir>"` is the form every tutorial prints,
    # it is what this file used to print, and it truncates the PATH it saves at
    # 1024 characters — on a machine where node, nvm and python have each added
    # themselves, following it drops unrelated entries from the registry with no
    # error. A command this repository tells a user to run unsupervised does not
    # get to do that, so the regression is worth a check rather than a comment.
    windows = "\n".join(eu.windows_path_advice(r"C:\Users\jane\.local\bin"))
    record("E32 the Windows advice sets PATH through .NET, which has no length "
           "limit, and writes only the user scope",
           "[Environment]::SetEnvironmentVariable('PATH'" in windows
           and "GetEnvironmentVariable('PATH','User')" in windows
           and windows.count("'User'") == 2, windows)
    record("E32 and it is never `setx`, except to say not to use it",
           "setx" not in windows.replace("not `setx`", ""), windows)

    # E33 — the verification fails, and the run does not.
    bare = launcher_machine(root / "bare-install", carries_bin=False)
    bins = root / "bare-install" / "bin"
    done = run_cli(["--install-launcher"], plugins_dir=bare["root"],
                   pointer=bare["pointer"], home=bare["home"], bin_dir=bins)
    record("E33 a launcher that will not run still exits 0: it is written after "
           "everything else precisely so it cannot fail an update already done",
           done.returncode == eu.RUN_OK, f"{done.returncode}\n{done.stdout}")
    record("E33 the installer says so, and prints the interpreter and the path "
           "to use instead",
           "does not run here" in done.stdout
           and str(Path(bare["plugin"]) / "bin" / "elephant-update") in done.stdout,
           done.stdout)
    record("E33 and it claims no update behind it: this route installs, copies "
           "and commits nothing, so the failure text says nothing else depends "
           "on the file rather than announcing a finished update",
           "update itself is done" not in done.stdout
           and "nothing else depends on this file" in done.stdout, done.stdout)
    record("E33 with the other route out beside it, as every blocking message "
           "in this design carries",
           "elephant-mem:update" in done.stdout, done.stdout)
    record("E33 and the file is on disk either way — it is the plugin that has "
           "nothing to run, not this that failed to write",
           (bins / "elephant-update").is_file())

    # E11 — `--check` writes nothing, the launcher included.
    machine = launcher_machine(root / "checkonly")
    untouched = root / "checkonly" / "bin"
    untouched.mkdir(parents=True, exist_ok=True)
    done = run_cli(["--check"], plugins_dir=machine["root"],
                   pointer=machine["pointer"], home=machine["home"],
                   bin_dir=untouched)
    record("E11 --check repairs no launcher and writes none: it runs inside read "
           "modes that must not write",
           done.returncode == eu.CHECK_IN_SYNC and not list(untouched.iterdir()),
           sorted(p.name for p in untouched.iterdir()))

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


# ── what a section on its own could not reach ────────────────────────────────
# Every check below crosses two of the sections above, which is why none of them
# could live inside one: where the file sits against the path the launcher's
# resolver builds; both resolution routes against one machine's `--check`; the
# restore commands a failed run prints against a git that has to accept them;
# the run's whole write footprint against a list nobody has to maintain; and a
# launcher that will not run against a commit and a stamp that already happened.


def eol(data):
    """Bytes with CRLF and lone CR folded to LF.

    Content comparisons over a bundle go through this for the same reason the
    executable's own `compare()` normalises: on Windows `Path.write_text` turns
    every `\n` the fixtures hold into `\r\n`, and with `core.autocrlf` on — the
    default there — `git checkout` rewrites the tree it restores. Neither is the
    bundle changing, so neither should read as one. What the suite pins about
    line endings is in the comparison checks, against bytes written on purpose.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def same_tree(left, right):
    """Two `contents()` maps equal once line endings are folded."""
    return ({rel: eol(data) for rel, data in left.items()}
            == {rel: eol(data) for rel, data in right.items()})


def contents(root, skip=(".git",)):
    """Every file under `root` with its bytes, `.git` left out.

    `snapshot()` carries mtimes too, which is what proves a read-only pass wrote
    nothing at all. Here the question is what the tree HOLDS once git has put it
    back, and a checkout moves the mtime of every file it restores.
    """
    out = {}
    for path in sorted(Path(root).rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and rel.parts[0] not in skip:
            out[rel.as_posix()] = path.read_bytes()
    return out


def placement_checks(eu):
    """Where the file sits is load-bearing in two directions at once, and
    neither is visible from inside the section that owns it. The launcher's
    resolver hands off to `<installPath>/bin/elephant-update` as a literal join,
    so the file has to be exactly there; and `plugin/assets/scripts/` is the set
    a re-sync copies into every bundle and three suites glob, so it has to be
    exactly not there."""
    rel = EXECUTABLE.relative_to(REPO_ROOT).as_posix()
    record("the executable is at plugin/bin/elephant-update",
           rel == "plugin/bin/elephant-update", rel)
    record("which is the path the launcher's resolver builds, as a literal join "
           "of the install directory, `bin` and the name — a file anywhere else "
           "leaves every launcher on disk with nothing to hand off to",
           'os.path.join(found, "bin", "elephant-update")' in eu.LAUNCHER_RESOLVER
           and (REAL_MEM_PLUGIN / "bin" / eu.LAUNCHER_NAME) == EXECUTABLE,
           str(REAL_MEM_PLUGIN / "bin" / eu.LAUNCHER_NAME))
    record("and `bin/` is a directory of the plugin, so an install places it "
           "where the resolver will look",
           EXECUTABLE.parent.parent == REAL_MEM_PLUGIN
           and EXECUTABLE.parent.name == "bin", str(EXECUTABLE.parent))
    record("it carries no .py suffix and the tracked mode is 755: Claude Code "
           "puts <plugin>/bin on the PATH of the processes it spawns and a mode "
           "runs `elephant-update --check` by name",
           EXECUTABLE.suffix == ""
           and git_mode(EXECUTABLE) in ("100755", None), git_mode(EXECUTABLE))

    swept = {path.name for path in (REAL_MEM_PLUGIN / "assets" / "scripts").iterdir()}
    record("plugin/assets/scripts/ does not hold it, under the `*.py` glob two "
           "of those suites use or the bare listing the third one copies",
           eu.LAUNCHER_NAME not in swept
           and not any(name.startswith(eu.LAUNCHER_NAME) for name in swept),
           sorted(swept))
    sources = set()
    for spec in eu.PUBLISHED:
        root = REAL_MEM_PLUGIN if spec.plugin == "elephant-mem" else REAL_WIKI_PLUGIN
        sources |= set(eu.published_files(root, spec.patterns).values())
    record("and no published pattern reaches it: it is not a bundle script, it "
           "is copied into no bundle, and a bundle holding a copy of it would be "
           "a file no plugin ships",
           EXECUTABLE not in sources, sorted(str(s) for s in sources))


def git_mode(path):
    """The mode git has tracked for `path`, or None where git cannot say — a
    source tarball, or a checkout this suite is not running inside."""
    if not git_available():
        return None
    done = git(REPO_ROOT, "ls-files", "-s", "--",
               str(path.relative_to(REPO_ROOT).as_posix()))
    parts = done.stdout.split()
    return parts[0] if done.returncode == 0 and parts else None


def both_routes_checks(eu, tmp):
    """E25 on one machine, through the executable rather than through a
    resolver called directly. `beta.9` and `beta.13` sit in the cache together
    and the registry names the second; the answer has to be `beta.13` with the
    registry there and with it gone, and it has to be an answer — a machine
    where both routes agree because neither looks at anything would pass this
    silently, so the same machine is asked again with a bundle that matches
    `beta.9` and has to call it drift both times."""
    root = tmp / "either-route"
    published = {"scripts": {"recall.py": "print('recall 13')\n"},
                 "templates": {"open-loop.md": "# loop 13\n"}}
    mem13 = make_plugin(root, "elephant-mem", version="0.1.0-beta.13", **published)
    mem9 = make_plugin(root, "elephant-mem", version="0.1.0-beta.9",
                       scripts={"recall.py": "print('recall 9')\n"},
                       templates={"open-loop.md": "# loop 9\n"})
    registry = make_registry(root, {
        "elephant-mem@elephant-mem": {"installPath": str(mem13),
                                      "version": "0.1.0-beta.13"}})
    current = make_bundle(root, "current", **published)
    behind = make_bundle(root, "behind",
                         scripts={"recall.py": "print('recall 9')\n"},
                         templates={"open-loop.md": "# loop 9\n"})
    pointer = write_pointer(root / "pointer.json", current)

    for route in ("registry", "cache"):
        if route == "cache":
            registry.unlink()
        resolution = eu.resolve_plugins(plugins_dir=root)
        record(f"E25 resolving by {route}, beta.13 wins over the beta.9 sitting "
               f"beside it in the cache",
               resolution.source == route
               and resolution.path_of("elephant-mem") == mem13,
               f"{resolution.source} {resolution.path_of('elephant-mem')}")
        done = run_cli(["--check"], plugins_dir=root, pointer=pointer,
                       home=root / "home")
        record(f"E25 and `--check` by {route} reads the bundle against beta.13's "
               f"files: in sync, silently",
               done.returncode == eu.CHECK_IN_SYNC and not done.stderr,
               f"{done.returncode}\n{done.stderr}")
        done = run_cli(["--check", "--bundle", behind], plugins_dir=root,
                       pointer=pointer, home=root / "home")
        record(f"E25 by {route}, a bundle holding beta.9's files is required "
               f"drift — which is what makes the two checks above an answer and "
               f"not an empty comparison",
               done.returncode == eu.CHECK_REQUIRED_DRIFT
               and "scripts/recall.py" in done.stderr
               and "templates/open-loop.md" in done.stderr,
               f"{done.returncode}\n{done.stderr}")
    record("E25 and the beta.9 that would have answered a text sort really is "
           "complete: it carries the same published files, so nothing above "
           "passed because the wrong directory was empty",
           (mem9 / "assets" / "scripts" / "recall.py").is_file()
           and (mem9 / "assets" / "templates" / "open-loop.md").is_file(),
           str(mem9))


def windows_pair_checks(eu, tmp):
    """E35 — the half of the pair that only a Windows runner can execute.

    The assertion is gated, the check is not: it is recorded on every OS so the
    count `smoke.py` compares against the CHANGELOG is the same number on all
    three, and it does its real work on the one runner where `cmd.exe` exists.
    `ci.yml` running this suite across the 3-OS matrix is what gets it there.
    """
    record("E35 the .cmd is the half a Windows shell runs, so it is the half "
           "the installer verifies — everywhere else that is the POSIX file",
           eu.launcher_entry([Path("elephant-update"), Path("elephant-update.cmd")])
           == Path("elephant-update.cmd" if os.name == "nt" else "elephant-update"))

    root = tmp / "windows"
    machine = launcher_machine(root)
    written, error = eu.write_launcher(root / "bin", windows=True)
    cmd = next((p for p in written if p.suffix == ".cmd"), None)
    ran, detail = True, "not a Windows runner: cmd.exe is what runs this file"
    if os.name == "nt" and cmd is not None:
        done = run_launcher(cmd, ["--check"], plugins_dir=machine["root"],
                            pointer=machine["pointer"], home=machine["home"])
        ran = done.returncode == eu.CHECK_IN_SYNC
        detail = f"{done.returncode}\n{done.stdout}\n{done.stderr}"
    record("E35 on a Windows runner the .cmd itself resolves the installed "
           "plugin and hands off — the pair is written because Git Bash's chmod "
           "grants no NTFS execute permission, and only cmd.exe can say whether "
           "what was written runs",
           ran and not error and cmd is not None, detail)

    bins = root / "install-bin"
    done = run_cli(["--install-launcher"], plugins_dir=machine["root"],
                   pointer=machine["pointer"], home=machine["home"], bin_dir=bins)
    entry = eu.launcher_entry(list(eu.launcher_paths(bins)))
    record("E35 and the installer's own run is the proof, on the file this OS "
           "would run rather than on whichever one it happened to write first",
           done.returncode == eu.RUN_OK and f"`{entry.name}` ran" in done.stdout,
           f"{done.returncode}\n{done.stdout}")


def report_checks(eu, tmp):
    """E26, E29 and E33 where they cross the full run: the restore commands
    handed to a real git, the write footprint measured over the whole tree, and
    a launcher that will not run arriving after a commit and a stamp that
    already happened."""
    if not git_available():
        record("git on PATH (every GitHub-hosted runner has it)", False,
               "git not found — these checks run the full run, which commits")
        return

    # ── E26/E27: the printed undo is an undo ─────────────────────────────────
    # Task 4 could assert the commands were printed and that they name the three
    # paths. Whether git accepts them and whether they really put the bundle
    # back is a question only a bundle that has actually been half-updated can
    # answer, and answering it is the difference between advice and an undo.
    world = make_world(tmp / "restore", validator=STUB_VALIDATE_FAIL)
    bundle = world["bundle"]
    before = contents(bundle)
    done = in_world(world, "--yes")
    record("E26 the run failed after the copy, so there is something to undo",
           done.returncode == eu.RUN_FAILED_AFTER_COPY and contents(bundle) != before,
           f"{done.returncode}\n{done.stderr}")
    printed = [line.strip() for line in done.stderr.splitlines()
               if line.strip().startswith("git -C ")]
    record("E27 the two commands it printed are the two it builds, against this "
           "bundle and no other",
           printed == eu.restore_commands(bundle), f"{printed}\n{eu.restore_commands(bundle)}")
    # The tail of each printed line, run as it was printed. Not `shlex.split`,
    # which is posix-mode by default and would eat the backslashes out of a
    # Windows path — the one platform this undo most has to survive.
    prefix = f"git -C {eu._quote(bundle)} "
    for command in printed:
        tail = command[len(prefix):] if command.startswith(prefix) else ""
        record(f"E27 `git … {tail.split(' ')[0] or command}` is addressed at the "
               f"bundle, so what runs below is the line as printed rather than a "
               f"reconstruction of it",
               bool(tail), f"{command}\n{prefix}")
        git(bundle, *tail.split())
    record("E27 running them puts the bundle back exactly as it stood: the "
           "copied files, the ones the copy added, and the index rewrite that "
           "an undo naming only the copied files would have left behind",
           same_tree(contents(bundle), before),
           sorted(set(contents(bundle)) ^ set(before))
           or [rel for rel, data in before.items()
               if eol(contents(bundle).get(rel, b"")) != eol(data)])
    record("E27 and git agrees the tree is clean, which is what the next run "
           "starts from",
           git(bundle, "status", "--porcelain").stdout.strip() == "",
           git(bundle, "status", "--porcelain").stdout)
    record("E29 the hand-written files were never in that failure's way either: "
           "a run that stops after the copy still touches no fact, loop, source, "
           "elephant.json, config.md or vocab.json",
           all(eol(before[rel]) == eol(content)
               for rel, content in HAND_WRITTEN.items()),
           [rel for rel, content in HAND_WRITTEN.items()
            if eol(before[rel]) != eol(content)])

    # ── E29: the footprint, over the whole tree ──────────────────────────────
    # The named list is a list someone has to keep current. This is the same
    # promise stated as a boundary: a run writes under the four paths it owns
    # and nowhere else, so a file nobody thought to name is covered too.
    world = make_world(tmp / "footprint")
    bundle = world["bundle"]
    before = contents(bundle)
    done = in_world(world, "--yes")
    after = contents(bundle)
    touched = sorted({rel for rel in set(before) | set(after)
                      if before.get(rel) != after.get(rel)})
    owned = ("scripts/", "templates/", "knowledge/", "state/")
    record("the run succeeded, so there is a footprint to measure",
           done.returncode == eu.RUN_OK and touched,
           f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E29 every path a successful run wrote is one it owns — the copied "
           "directories, the derived index and the gitignored stamp — measured "
           "over the whole tree rather than against a list to keep current",
           all(rel.startswith(owned) for rel in touched), touched)
    record("E29 nothing under knowledge/facts, knowledge/sources or "
           "knowledge/tracking moved: those are the bundle's own writing and no "
           "update has business in them",
           not any(rel.startswith(("knowledge/facts/", "knowledge/sources/",
                                   "knowledge/tracking/")) for rel in touched),
           touched)
    record("E29 and the three files the mode's never-touched list names by hand "
           "are among the ones the boundary already covers",
           not any(rel in ("elephant.json", "config.md", "vocab.json")
                   for rel in touched), touched)

    # ── E33: the launcher fails after the update is really done ──────────────
    # Task 5 reached this on `--install-launcher`, where there is no update
    # behind it. The claim the ordering makes is about the OTHER route: the
    # copy, the commit and the stamp are already on disk, so a launcher that
    # will not run is a report.
    world = make_world(tmp / "no-handoff", ships_executable=False)
    bundle = world["bundle"]
    bins = tmp / "no-handoff" / "bin"
    done = run_cli(["--yes"], plugins_dir=world["root"], pointer=world["pointer"],
                   home=world["home"], claude=world["claude"], bin_dir=bins)
    record("E33 a full run whose launcher will not run still exits 0",
           done.returncode == eu.RUN_OK, f"{done.returncode}\n{done.stdout}\n{done.stderr}")
    record("E33 it says so and prints the interpreter-and-path line, naming the "
           "installed plugin's own copy",
           "does not run here" in done.stdout
           and "bin/elephant-update" in done.stdout.replace(os.sep, "/"),
           done.stdout)
    record("E33 with the other route out beside it, as every message that stops "
           "someone in this design carries",
           "elephant-mem:update" in done.stdout, done.stdout)
    record("E33 and the file is on disk anyway: it is the plugin that has "
           "nothing to hand off to, not this that failed to write",
           (bins / "elephant-update").is_file(), sorted(p.name for p in bins.iterdir()))
    record("E33 the ordering is the whole reason this is a report: the copy "
           "landed, the commit was made and the stamp was written before the "
           "launcher was ever touched",
           (bundle / "scripts" / "close-loops.py").is_file()
           and "scripts/close-loops.py" in committed_paths(bundle)
           and (bundle / "state" / "last-update-check.json").is_file(),
           committed_paths(bundle))
    record("E33 so the failure text claims nothing about an update on the route "
           "where none ran — `--install-launcher` installs, copies and commits "
           "nothing, and the same text serves both routes",
           "update itself is done" not in done.stdout
           and "nothing else depends on this file" in done.stdout, done.stdout)


if __name__ == "__main__":
    sys.exit(main())
