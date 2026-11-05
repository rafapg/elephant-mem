#!/usr/bin/env python3
"""Standalone test suite for elephant-trunk's `assets/scripts/trunk.py`.

Covers the plugin's shape (its plugin.json, its CHANGELOG, its marketplace
entry), how it finds the bundle (`--bundle`, then ELEPHANT_BUNDLE, then the
machine pointer, with elephant-wiki's guidance when none resolves), and how it
reads `trunk.tag` from elephant.json (the bundle's value, or `how-i-work` with a
hint on how to set another), how `facts` lists the owner's how from
knowledge/manifest.jsonl alone, and how `run` writes a run record under
state/trunk/ (git-ignored, so a `git add -A` never stages it), reads it back,
continues it, never dispatches a dispatched run again, and records the ingest
of a dispatched run only when its commit left the raw record out. A recipe
written for a run is kept as a draft beside the record, checked against its
hash, saved without ever replacing one, and never started unless it passed.
A learning the owner steers or forgets leaves the facts the trunk reads: its
fact becomes `superseded` or `deprecated` in its own file, the bundle's real
build-index.py rebuilds the manifest, and only the trunk's own how is touched.
Past sessions read on first use are estimated without a bundle, and their
extract keeps the owner's own messages and the names of what ran, never tool
output, the assistant's text, a command's arguments or a credential.

Pure stdlib, Python 3.10+, mirroring tests/test_wiki.py's conventions: a
throwaway bundle in a tempdir, subprocess calls into the real script, PASS/FAIL
per check, exit 0 only if every check passes. The machine pointer is faked by
pointing HOME (and USERPROFILE, for Windows) at the tempdir, so the real
~/.config/elephant-mem/config.json is never read.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN = REPO_ROOT / "elephant-trunk"
TRUNK = PLUGIN / "assets" / "scripts" / "trunk.py"
WIKI = REPO_ROOT / "elephant-wiki" / "assets" / "scripts" / "wiki.py"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
BUILD_INDEX = REPO_ROOT / "plugin" / "assets" / "scripts" / "build-index.py"

checks = []


def record(label, passed, detail=""):
    checks.append((label, passed))
    print(f"[{len(checks):2d}] {'PASS' if passed else 'FAIL'} — {label}")
    if detail and not passed:
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    return passed


def make_bundle(root, name="bundle", cfg=None):
    b = root / name
    (b / "knowledge").mkdir(parents=True)
    (b / "state").mkdir()
    if cfg is not None:
        text = cfg if isinstance(cfg, str) else json.dumps(cfg)
        (b / "elephant.json").write_text(text, encoding="utf-8")
    return b


def env_for(home, bundle_env=None):
    """A child environment whose HOME is the tempdir, so the pointer the script
    reads is the one this suite writes. ELEPHANT_BUNDLE is set only when asked:
    a developer's own value must never leak into a check."""
    env = {k: v for k, v in os.environ.items() if k != "ELEPHANT_BUNDLE"}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    if bundle_env is not None:
        env["ELEPHANT_BUNDLE"] = str(bundle_env)
    return env


def run(script, *args, env):
    return subprocess.run([sys.executable, str(script), *[str(a) for a in args]],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def config_json(*args, env):
    r = run(TRUNK, "config", "--json", *args, env=env)
    try:
        return r, json.loads(r.stdout)
    except ValueError:
        return r, None


def write_pointer(home, bundle):
    p = home / ".config" / "elephant-mem" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"bundle_path": str(bundle)}), encoding="utf-8")
    return p


def fact_row(link, tags, status="active", type_="fact", desc=None):
    row = {"path": link, "type": type_, "desc": desc or link, "entities": [],
           "tags": tags, "occurred": "2026-11-05", "confidence": "high"}
    if status is not None:
        row["status"] = status
    return row


def write_manifest(bundle, rows):
    """knowledge/manifest.jsonl as build-index writes it: one compact JSON
    object per line. A str row is written verbatim, to plant a broken line."""
    lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, separators=(",", ":"))
             for r in rows]
    (bundle / "knowledge" / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def facts_json(*args, env):
    r = run(TRUNK, "facts", "--json", *args, env=env)
    try:
        return r, json.loads(r.stdout)
    except ValueError:
        return r, None


def links(out):
    return [f["link"] for f in out["facts"]] if out else None


def guidance(stderr, prog):
    """A die() message with its `<prog>: ` prefix stripped, so trunk's and the
    wiki's guidance compare on what they say rather than on who says it."""
    line = stderr.strip().splitlines()[-1] if stderr.strip() else ""
    return line[len(prog) + 2:] if line.startswith(prog + ": ") else line


def main():
    root = Path(tempfile.mkdtemp(prefix="elephant-trunk-"))
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
    # ── the plugin's shape ────────────────────────────────────────────────────
    pj_path = PLUGIN / ".claude-plugin" / "plugin.json"
    try:
        pj = json.loads(pj_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        pj = {}
        record("plugin.json exists and parses", False, exc)
    else:
        record("plugin.json exists and parses", True)
    version = pj.get("version", "")
    record("plugin.json names the plugin elephant-trunk", pj.get("name") == "elephant-trunk", pj.get("name"))
    record("plugin.json carries a semver version",
           bool(re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", version)), version)

    mk = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    entries = [p for p in mk.get("plugins", []) if p.get("name") == "elephant-trunk"]
    record("the marketplace lists elephant-trunk once", len(entries) == 1, entries)
    src = entries[0].get("source", "") if entries else ""
    record("its marketplace source is the plugin's directory",
           src == "./elephant-trunk" and (REPO_ROOT / src / ".claude-plugin" / "plugin.json").is_file(), src)
    record("the marketplace still lists elephant-mem and elephant-wiki",
           {"elephant-mem", "elephant-wiki"} <= {p.get("name") for p in mk.get("plugins", [])})

    cl_path = PLUGIN / "CHANGELOG.md"
    cl = cl_path.read_text(encoding="utf-8") if cl_path.is_file() else ""
    record("the plugin has its own CHANGELOG", bool(cl))
    record("the CHANGELOG has a section for plugin.json's version",
           bool(version) and f"## [{version}]" in cl, version)

    # tests/test_skill_invocation.py checks the 1024-character limit on
    # plugin/skills/ only; its own parser reads the trunk's, so the two agree.
    spec = importlib.util.spec_from_file_location(
        "skill_invocation", REPO_ROOT / "tests" / "test_skill_invocation.py")
    invocation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(invocation)
    skill_files = sorted((PLUGIN / "skills").glob("*/SKILL.md"))
    record("the plugin ships its skills", bool(skill_files), PLUGIN / "skills")
    for path in skill_files:
        desc = invocation.description(invocation.frontmatter(path))
        record(f"{path.parent.name}: description is present and fits 1024 characters ({len(desc)})",
               0 < len(desc) <= 1024, desc[:80])

    # ── bundle resolution ─────────────────────────────────────────────────────
    home = root / "home"
    home.mkdir()
    flagged = make_bundle(root, "flagged", {"trunk": {"tag": "flag-tag"}})
    via_env = make_bundle(root, "via-env", {"trunk": {"tag": "env-tag"}})
    pointed = make_bundle(root, "pointed", {"trunk": {"tag": "pointer-tag"}})

    r, cfg = config_json("--bundle", flagged, env=env_for(home))
    record("--bundle resolves the bundle",
           r.returncode == 0 and cfg is not None and
           Path(cfg["bundle"]).resolve() == flagged.resolve() and cfg["tag"] == "flag-tag",
           r.stderr or r.stdout)

    r, cfg = config_json(env=env_for(home, via_env))
    record("ELEPHANT_BUNDLE resolves the bundle when no --bundle is given",
           r.returncode == 0 and cfg is not None and cfg["tag"] == "env-tag", r.stderr or r.stdout)

    r, cfg = config_json("--bundle", flagged, env=env_for(home, via_env))
    record("--bundle wins over ELEPHANT_BUNDLE",
           r.returncode == 0 and cfg is not None and cfg["tag"] == "flag-tag", r.stderr or r.stdout)

    r, cfg = config_json(env=env_for(home))
    record("with no flag, no env and no pointer, it stops",
           r.returncode != 0 and cfg is None, r.stdout)
    rw = run(WIKI, env=env_for(home))
    record("its guidance for a missing pointer is elephant-wiki's, word for word",
           guidance(r.stderr, "trunk.py") != "" and
           guidance(r.stderr, "trunk.py") == guidance(rw.stderr, "wiki.py"),
           f"trunk: {r.stderr.strip()}\nwiki:  {rw.stderr.strip()}")
    record("the guidance names the pointer and --bundle",
           ".config" in r.stderr and "--bundle" in r.stderr, r.stderr)

    write_pointer(home, pointed)
    r, cfg = config_json(env=env_for(home, via_env))
    record("ELEPHANT_BUNDLE wins over the pointer",
           r.returncode == 0 and cfg is not None and cfg["tag"] == "env-tag", r.stderr or r.stdout)
    r, cfg = config_json(env=env_for(home, ""))
    record("the machine pointer resolves the bundle when nothing overrides it (an empty ELEPHANT_BUNDLE counts as unset)",
           r.returncode == 0 and cfg is not None and cfg["tag"] == "pointer-tag", r.stderr or r.stdout)

    not_bundle = root / "not-a-bundle"
    not_bundle.mkdir()
    r = run(TRUNK, "config", "--bundle", not_bundle, env=env_for(home))
    rw = run(WIKI, "--bundle", not_bundle, env=env_for(home))
    record("a directory with no knowledge/ is refused with the wiki's guidance",
           r.returncode != 0 and "does not look like a bundle" in r.stderr and
           guidance(r.stderr, "trunk.py") == guidance(rw.stderr, "wiki.py"),
           f"trunk: {r.stderr.strip()}\nwiki:  {rw.stderr.strip()}")

    (home / ".config" / "elephant-mem" / "config.json").write_text("not json", encoding="utf-8")
    r = run(TRUNK, "config", env=env_for(home))
    record("an unreadable pointer stops with the same guidance",
           r.returncode != 0 and "no bundle pointer" in r.stderr and "--bundle" in r.stderr, r.stderr)

    # ── trunk.tag ─────────────────────────────────────────────────────────────
    custom = make_bundle(root, "custom", {"owner": {"slug": "t"}, "trunk": {"tag": "como-trabalhar"}})
    r, cfg = config_json("--bundle", custom, env=env_for(home))
    record("trunk.tag in elephant.json is the tag read",
           cfg is not None and cfg["tag"] == "como-trabalhar" and cfg["tag_source"] == "elephant.json",
           r.stderr or r.stdout)
    record("a set trunk.tag prints no hint about setting one",
           "trunk.tag" not in r.stderr, r.stderr)
    record("the area tags are the fixed three",
           cfg is not None and cfg["area_tags"] == ["trunk-study", "trunk-dispatch", "trunk-recipe"],
           cfg)

    absent = make_bundle(root, "absent", {"owner": {"slug": "t"}, "hooks": {}})
    r, cfg = config_json("--bundle", absent, env=env_for(home))
    record("with no trunk.tag it reads how-i-work",
           r.returncode == 0 and cfg is not None and cfg["tag"] == "how-i-work" and cfg["tag_source"] == "default",
           r.stderr or r.stdout)
    record("with no trunk.tag it says how to set another tag",
           '"trunk": {"tag":' in r.stderr and "elephant.json" in r.stderr, r.stderr)
    r = run(TRUNK, "config", "--bundle", absent, env=env_for(home))
    record("the human output names the bundle and the tag",
           r.returncode == 0 and str(absent) in r.stdout and "how-i-work" in r.stdout, r.stdout)

    no_cfg = make_bundle(root, "no-config")
    r, cfg = config_json("--bundle", no_cfg, env=env_for(home))
    record("a bundle with no elephant.json reads how-i-work",
           r.returncode == 0 and cfg is not None and cfg["tag"] == "how-i-work", r.stderr or r.stdout)

    for label, value in (("an empty", ""), ("a whitespace-only", "   "),
                         ("a non-string", ["a"]), ("a null", None)):
        b = make_bundle(root, f"bad-{len(checks)}", {"trunk": {"tag": value}})
        r, cfg = config_json("--bundle", b, env=env_for(home))
        record(f"{label} trunk.tag falls back to how-i-work and says why",
               r.returncode == 0 and cfg is not None and cfg["tag"] == "how-i-work"
               and cfg["problem"] and "trunk.tag" in r.stderr, r.stderr or r.stdout)

    b = make_bundle(root, "trunk-not-object", {"trunk": "como-trabalhar"})
    r, cfg = config_json("--bundle", b, env=env_for(home))
    record("a trunk key that is not an object falls back and says why",
           r.returncode == 0 and cfg is not None and cfg["tag"] == "how-i-work" and cfg["problem"],
           r.stderr or r.stdout)

    b = make_bundle(root, "broken-json", "{not json")
    r, cfg = config_json("--bundle", b, env=env_for(home))
    record("a malformed elephant.json falls back to how-i-work and says so",
           r.returncode == 0 and cfg is not None and cfg["tag"] == "how-i-work"
           and "cannot parse" in r.stderr, r.stderr or r.stdout)

    b = make_bundle(root, "padded", {"trunk": {"tag": "  como-trabalhar  "}})
    r, cfg = config_json("--bundle", b, env=env_for(home))
    record("surrounding whitespace in trunk.tag is trimmed",
           cfg is not None and cfg["tag"] == "como-trabalhar", r.stderr or r.stdout)

    # ── the plugin stays out of the bundle ────────────────────────────────────
    record("reading the config writes nothing into the bundle",
           sorted(p.name for p in custom.iterdir()) == ["elephant.json", "knowledge", "state"],
           sorted(p.name for p in custom.iterdir()))

    # ── the owner's how: `facts` ─────────────────────────────────────────────
    how = make_bundle(root, "how", {"trunk": {"tag": "como-trabalhar"}})
    write_manifest(how, [
        fact_row("/facts/study.md", ["como-trabalhar", "trunk-study"], desc="study with the repos"),
        fact_row("/facts/dispatch-recipe.md", ["trunk-recipe", "como-trabalhar", "trunk-dispatch"]),
        fact_row("/facts/slack-rule.md", ["como-trabalhar", "slack-produto"]),
        fact_row("/facts/untagged-study.md", ["trunk-study", "strategy"]),
        fact_row("/facts/other-how.md", ["how-i-work", "trunk-study"]),
        fact_row("/facts/superseded.md", ["como-trabalhar", "trunk-study"], status="superseded"),
        fact_row("/facts/deprecated.md", ["como-trabalhar", "trunk-dispatch"], status="deprecated"),
        fact_row("/facts/no-status.md", ["como-trabalhar", "trunk-recipe"], status=None),
        fact_row("/facts/loud-status.md", ["como-trabalhar", "trunk-study"], status=" Active "),
        fact_row("/tracking/loops/loop.md", ["como-trabalhar", "trunk-study"], status="open",
                 type_="open-loop"),
        fact_row("/entities/project/x.md", ["como-trabalhar", "trunk-study"], type_="entity"),
        "{not a json line",
        fact_row("/facts/one-string-tag.md", "como-trabalhar"),
    ])
    # A fact file on disk the manifest does not list: reading the manifest only
    # means it is never seen, whatever its frontmatter says.
    (how / "knowledge" / "facts").mkdir()
    (how / "knowledge" / "facts" / "off-manifest.md").write_text(
        "---\ntype: fact\nstatus: active\ntags: [como-trabalhar, trunk-study]\n---\nbody\n",
        encoding="utf-8")
    before = sorted(str(p.relative_to(how)) for p in how.rglob("*"))

    r, out = facts_json("--bundle", how, env=env_for(home))
    got = links(out)
    record("facts lists the active facts with the how-I-work tag plus a trunk area tag",
           r.returncode == 0 and got is not None and
           set(got) == {"/facts/study.md", "/facts/dispatch-recipe.md",
                        "/facts/no-status.md", "/facts/loud-status.md"},
           r.stderr or r.stdout)
    record("it keeps the manifest's order",
           got == ["/facts/study.md", "/facts/dispatch-recipe.md",
                   "/facts/no-status.md", "/facts/loud-status.md"], got)
    record("the how-I-work tag alone, with no trunk area tag, is not enough",
           got is not None and "/facts/slack-rule.md" not in got and
           "/facts/one-string-tag.md" not in got, got)
    record("a trunk area tag alone, without the bundle's how-I-work tag, is not enough",
           got is not None and "/facts/untagged-study.md" not in got and "/facts/other-how.md" not in got,
           got)
    record("superseded and deprecated facts are not read",
           got is not None and "/facts/superseded.md" not in got and "/facts/deprecated.md" not in got, got)
    record("only facts are read: an open loop or an entity with the tags is not",
           got is not None and not any(g.startswith(("/tracking/", "/entities/")) for g in got), got)
    record("it reads the manifest only: a fact file absent from it is never listed",
           got is not None and "/facts/off-manifest.md" not in got, got)
    record("an unreadable manifest line is skipped and said, the rest still read",
           got is not None and len(got) == 4 and "skipped 1" in r.stderr, r.stderr)
    by_link = {f["link"]: f for f in out["facts"]} if out else {}
    dr = by_link.get("/facts/dispatch-recipe.md", {})
    record("each fact names the area tags it carries, in the fixed order",
           dr.get("areas") == ["trunk-dispatch", "trunk-recipe"] and
           by_link.get("/facts/study.md", {}).get("areas") == ["trunk-study"], dr)
    st = by_link.get("/facts/study.md", {})
    record("each fact's path is absolute, under the bundle's knowledge/, with its description",
           Path(st.get("path", "")).is_absolute() and
           Path(st.get("path", "")) == how / "knowledge" / "facts" / "study.md" and
           st.get("desc") == "study with the repos", st)
    record("the JSON names the tag read and the areas asked for",
           out is not None and out["tag"] == "como-trabalhar" and out["tag_source"] == "elephant.json"
           and out["areas"] == ["trunk-study", "trunk-dispatch", "trunk-recipe"], out)

    r, out = facts_json("--bundle", how, "--area", "trunk-recipe", env=env_for(home))
    record("--area narrows the list to that area",
           r.returncode == 0 and links(out) == ["/facts/dispatch-recipe.md", "/facts/no-status.md"],
           r.stderr or r.stdout)
    record("--area narrows each fact's areas too",
           out is not None and out["facts"] and out["facts"][0]["areas"] == ["trunk-recipe"]
           and out["areas"] == ["trunk-recipe"], out)
    r, out = facts_json("--bundle", how, "--area", "trunk-recipe", "--area", "trunk-study", env=env_for(home))
    record("--area repeats",
           r.returncode == 0 and out is not None and len(out["facts"]) == 4, r.stderr or r.stdout)
    r = run(TRUNK, "facts", "--bundle", how, "--area", "trunk-other", env=env_for(home))
    record("an --area outside the three is refused", r.returncode != 0, r.stdout)

    r = run(TRUNK, "facts", "--bundle", how, env=env_for(home))
    lines = r.stdout.splitlines()
    first = lines[0].split("\t") if lines else []
    record("the plain output is one tab-separated line per fact: areas, path, description",
           r.returncode == 0 and len(lines) == 4 and first[:1] == ["trunk-study"]
           and first[1:2] and first[1].endswith("study.md") and first[2:] == ["study with the repos"],
           r.stdout)
    record("listing the facts writes nothing into the bundle",
           sorted(str(p.relative_to(how)) for p in how.rglob("*")) == before)

    default = make_bundle(root, "default-how")
    write_manifest(default, [
        fact_row("/facts/a.md", ["how-i-work", "trunk-dispatch"]),
        fact_row("/facts/b.md", ["como-trabalhar", "trunk-dispatch"]),
    ])
    r, out = facts_json("--bundle", default, env=env_for(home))
    record("with no trunk.tag, facts reads how-i-work",
           r.returncode == 0 and links(out) == ["/facts/a.md"], r.stderr or r.stdout)
    record("with no trunk.tag, facts says how to set another tag",
           '"trunk": {"tag":' in r.stderr, r.stderr)

    empty = make_bundle(root, "no-how", {"trunk": {"tag": "como-trabalhar"}})
    write_manifest(empty, [fact_row("/facts/c.md", ["como-trabalhar", "slack-produto"])])
    r, out = facts_json("--bundle", empty, env=env_for(home))
    record("with no how-I-work fact for the trunk, it lists none and still exits 0",
           r.returncode == 0 and out is not None and out["facts"] == [], r.stderr or r.stdout)
    record("and says so on stderr, naming the tag",
           "no active fact" in r.stderr and "como-trabalhar" in r.stderr, r.stderr)
    r = run(TRUNK, "facts", "--bundle", empty, env=env_for(home))
    record("its plain output is empty: the data stream carries facts only",
           r.returncode == 0 and r.stdout == "", r.stdout)

    unbuilt = make_bundle(root, "unbuilt")
    r = run(TRUNK, "facts", "--bundle", unbuilt, env=env_for(home))
    record("a bundle with no manifest stops and says to rebuild it, rather than report no how",
           r.returncode != 0 and "manifest.jsonl" in r.stderr and "build-index" in r.stderr,
           r.stderr)

    r = run(TRUNK, "facts", env=env_for(root / "nohome"))
    record("facts resolves the bundle like config: no bundle stops with the same guidance",
           r.returncode != 0 and "no bundle pointer" in r.stderr, r.stderr)

    _run_record(root, home)
    _recipe_written(root, home)
    _steer_and_forget(root, home)
    _past_sessions(root, home)


def git(bundle, *args):
    return subprocess.run(["git", "-C", str(bundle), *args], capture_output=True, text=True,
                          encoding="utf-8")


def git_bundle(root, name, gitignore=None):
    """A bundle that is a git work tree, as `init` leaves it, with the seed's
    .gitignore unless another is given."""
    b = make_bundle(root, name, {"trunk": {"tag": "como-trabalhar"}})
    seed = (REPO_ROOT / "plugin" / "assets" / "seed" / ".gitignore").read_text(encoding="utf-8")
    (b / ".gitignore").write_text(seed if gitignore is None else gitignore, encoding="utf-8")
    git(b, "init", "-q")
    return b


def run_json(*args, env):
    r = run(TRUNK, "run", *args, "--json", env=env)
    try:
        return r, json.loads(r.stdout)
    except ValueError:
        return r, None


def _run_record(root, home):
    env = env_for(home)
    has_git = shutil.which("git") is not None
    record("git is on PATH (the ignore checks below need it)", has_git)

    # ── a run is written to state/trunk/, git-ignored ─────────────────────────
    b = git_bundle(root, "runs")
    r, out = run_json("new", "--bundle", b, "--topic", "Migrar o catálogo de entidades!", env=env)
    name = out["name"] if out else ""
    record("run new starts a record and names it after the date and the topic",
           r.returncode == 0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}-migrar-o-catalogo-de-entidades", name or ""),
           r.stderr or r.stdout)
    path = b / "state" / "trunk" / "runs" / f"{name}.json"
    record("the record is one JSON file under state/trunk/runs/",
           out is not None and path.is_file() and Path(out["path"]) == path, out)
    rec = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    record("a new record is open, carries its topic and nothing decided yet",
           rec.get("status") == "open" and rec.get("topic") == "Migrar o catálogo de entidades!"
           and rec.get("dispatch") is None and rec.get("approaches") == [] and rec.get("decisions") == [],
           rec)
    gi_lines = (b / ".gitignore").read_text(encoding="utf-8").splitlines()
    record("writing a run git-ignores state/trunk/ in the bundle",
           "state/trunk/" in gi_lines and "git-ignored state/trunk/" in r.stderr, gi_lines)
    record("the seed's ignore rules are kept", "state/recall.json" in gi_lines, gi_lines)
    if os.name == "posix":
        mode = path.stat().st_mode & 0o777
        record("the raw record is readable by its owner only", mode == 0o600, oct(mode))
    trunk = load_trunk()
    broken = {"name": "2026-11-05-a-write-that-fails", "topic": {1, 2}}   # a set: json cannot write it
    try:
        trunk.write_record(str(b), broken, create=True)
        raised = False
    except TypeError:
        raised = True
    left = sorted(p.name for p in (b / "state" / "trunk" / "runs").iterdir() if p.name != f"{name}.json")
    record("a new record whose write fails leaves no placeholder or temp file, so its name stays free",
           raised and left == [], left)

    r2, out2 = run_json("new", "--bundle", b, "--topic", "Migrar o catálogo de entidades!", env=env)
    record("the same topic twice gets a second name, never overwriting the first",
           r2.returncode == 0 and out2 is not None and out2["name"] == f"{name}-2", r2.stderr or r2.stdout)
    gi_lines = (b / ".gitignore").read_text(encoding="utf-8").splitlines()
    record("the ignore entry is written once, however many runs",
           gi_lines.count("state/trunk/") == 1 and "git-ignored" not in r2.stderr, gi_lines)
    r = run(TRUNK, "run", "new", "--bundle", b, "--topic", "x", "--name", name, env=env)
    record("an explicit --name that exists is refused", r.returncode != 0 and "already exists" in r.stderr,
           r.stderr)
    r = run(TRUNK, "run", "new", "--bundle", b, "--topic", "x", "--name", "../escape", env=env)
    record("a run name cannot leave state/trunk/runs/",
           r.returncode != 0 and not (b / "state" / "trunk" / "escape.json").exists(), r.stderr)

    if has_git:
        git(b, "add", "-A")
        staged = git(b, "diff", "--cached", "--name-only").stdout.splitlines()
        record("an `ingest`-style `git add -A` stages no run record",
               staged and not any(s.startswith("state/trunk") for s in staged), staged)

    # ── read back and continued ───────────────────────────────────────────────
    S = ("run", "set", "--bundle", b, name)
    steps = [run(TRUNK, *S, "study", "--value", "## what the memory says\nthree facts", env=env),
             run(TRUNK, *S, "approaches", "--value", json.dumps(["split by area", "one big PR"]), env=env),
             run(TRUNK, *S, "decision", "--value", "split by area", env=env),
             run(TRUNK, *S, "decision", "--value", "orq, two sessions", env=env),
             run(TRUNK, *S, "note", "--value", "owner left before dispatching", env=env)]
    record("run set continues a run, one field at a time", all(s.returncode == 0 for s in steps),
           "\n".join(s.stderr for s in steps))
    brief = root / "brief.md"
    brief.write_text("# brief\nbuild it in two sessions\n", encoding="utf-8")
    r = run(TRUNK, *S, "brief", "--file", brief, env=env)
    record("a long value is read from --file", r.returncode == 0, r.stderr)

    r, rec = run_json("show", "--bundle", b, name, env=env)
    record("run show --json reads the record back as written",
           r.returncode == 0 and rec is not None and rec["study"].startswith("## what the memory says")
           and rec["approaches"] == ["split by area", "one big PR"]
           and [d["text"] for d in rec["decisions"]] == ["split by area", "orq, two sessions"]
           and rec["brief"] == "# brief\nbuild it in two sessions\n"
           and [n["text"] for n in rec["log"]] == ["owner left before dispatching"], r.stderr or rec)
    record("continuing a run moves its updated time and keeps its created time",
           rec is not None and rec["updated"] > rec["created"], rec and (rec["created"], rec["updated"]))
    r = run(TRUNK, "run", "show", "--bundle", b, name, env=env)
    record("the plain show names the topic, the approaches, the decisions and the brief",
           r.returncode == 0 and "Migrar o catálogo" in r.stdout and "split by area" in r.stdout
           and "orq, two sessions" in r.stdout and "build it in two sessions" in r.stdout, r.stdout)

    r = run(TRUNK, *S, "approaches", "--value", '{"not": "a list"}', env=env)
    record("approaches must be a JSON array", r.returncode != 0, r.stderr)
    r = run(TRUNK, *S, "recipe", "--value", "not json", env=env)
    record("a recipe must be JSON", r.returncode != 0 and "JSON" in r.stderr, r.stderr)
    r = run(TRUNK, *S, "recipe", "--value", json.dumps({"name": "two-sessions", "check": {"ok": False, "error": "bad"}}),
            env=env)
    _, rec = run_json("show", "--bundle", b, name, env=env)
    record("a recipe and its failed check are kept in the record",
           r.returncode == 0 and rec and rec["recipe"]["check"]["error"] == "bad", r.stderr)
    r = run(TRUNK, *S, "study", env=env)
    record("set with no value is refused", r.returncode != 0, r.stderr)

    # ── list: most recent first, open runs ────────────────────────────────────
    r, out = run_json("list", "--bundle", b, env=env)
    names = [x["name"] for x in out["runs"]] if out else None
    record("run list puts the most recently continued run first",
           r.returncode == 0 and names == [name, f"{name}-2"], names)

    # ── dispatch: failure keeps it open, success closes it to re-dispatch ─────
    D = ("run", "dispatch", "--bundle", b, name, "--via", "orq", "--command", "orq start two-sessions")
    r = run(TRUNK, *D, "--error", "orq: no such recipe", env=env)
    _, rec = run_json("show", "--bundle", b, name, env=env)
    record("a failed dispatch is recorded with its error and the run stays open",
           r.returncode == 0 and rec and rec["status"] == "open" and rec["dispatch"] is None
           and rec["attempts"][-1]["error"] == "orq: no such recipe" and not rec["attempts"][-1]["ok"],
           r.stderr or rec)
    r = run(TRUNK, "run", "show", "--bundle", b, name, env=env)
    record("show says a run was not dispatched, with the error", "not dispatched" in r.stdout
           and "orq: no such recipe" in r.stdout, r.stdout)
    r = run(TRUNK, *D, "--where", "orq team trunk-7", env=env)
    _, rec = run_json("show", "--bundle", b, name, env=env)
    record("a dispatch that ran makes the run dispatched, with the command and where",
           r.returncode == 0 and rec and rec["status"] == "dispatched"
           and rec["dispatch"]["command"] == "orq start two-sessions"
           and rec["dispatch"]["where"] == "orq team trunk-7" and len(rec["attempts"]) == 2,
           r.stderr or rec)
    r = run(TRUNK, *D, env=env)
    _, after = run_json("show", "--bundle", b, name, env=env)
    record("a dispatched run is never dispatched again: refused, saying what and where",
           r.returncode != 0 and "never dispatched again" in r.stderr and "trunk-7" in r.stderr
           and after == rec, r.stderr)
    r = run(TRUNK, *S, "brief", "--value", "another brief", env=env)
    record("what was dispatched stays as dispatched", r.returncode != 0, r.stderr)
    r = run(TRUNK, *S, "decision", "--value", "follow up next week", env=env)
    record("the conversation continues after the dispatch", r.returncode == 0, r.stderr)
    r = run(TRUNK, *S, "learning", "--value", "/facts/2026-11/orq-for-two-areas.md: orq when the work splits by area",
            env=env)
    _, rec = run_json("show", "--bundle", b, name, env=env)
    record("a learning is appended to the record after the dispatch",
           r.returncode == 0 and rec and [x["text"] for x in rec["learnings"]]
           == ["/facts/2026-11/orq-for-two-areas.md: orq when the work splits by area"], r.stderr or rec)

    # ── the ingest of a dispatched run ────────────────────────────────────────
    r = run(TRUNK, "run", "ingested", "--bundle", b, f"{name}-2", env=env)
    record("a run not dispatched yet is not marked ingested",
           r.returncode != 0 and "not dispatched" in r.stderr, r.stderr)
    if has_git:
        G = ("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false")
        git(b, "add", "-A")
        git(b, *G, "commit", "-q", "-m", "ingest: the run")
        head = git(b, "rev-parse", "HEAD").stdout.strip()
        r, out = run_json("ingested", "--bundle", b, name, env=env)
        _, rec = run_json("show", "--bundle", b, name, env=env)
        record("run ingested records the ingest commit, the bundle's HEAD by default",
               r.returncode == 0 and rec and head and rec["ingests"][-1]["commit"] == head
               and rec["status"] == "dispatched", r.stderr or rec)
        r = run(TRUNK, "run", "show", "--bundle", b, name, env=env)
        record("the plain show names the ingest and what was learned",
               "## ingested" in r.stdout and head[:12] in r.stdout and "orq when the work splits" in r.stdout,
               r.stdout)

        leak = git_bundle(root, "leaked")
        _, lo = run_json("new", "--bundle", leak, "--topic", "t", env=env)
        lname = lo["name"] if lo else "x"
        run(TRUNK, "run", "dispatch", "--bundle", leak, lname, "--via", "claude-code",
            "--command", "this session", env=env)
        git(leak, "add", "-A")
        git(leak, "add", "-f", f"state/trunk/runs/{lname}.json")
        git(leak, *G, "commit", "-q", "-m", "ingest: leaked")
        leaked_sha = git(leak, "rev-parse", "HEAD").stdout.strip()
        r = run(TRUNK, "run", "ingested", "--bundle", leak, lname, env=env)
        record("an ingest that committed the raw record is refused, saying how to untrack it",
               r.returncode != 0 and "entered the bundle's history" in r.stderr and "rm -r --cached" in r.stderr,
               r.stderr)
        git(leak, "rm", "-r", "-q", "--cached", "state/trunk")
        git(leak, *G, "commit", "-q", "-m", "untrack")
        r = run(TRUNK, "run", "ingested", "--bundle", leak, lname, "--commit", leaked_sha, env=env)
        _, lrec = run_json("show", "--bundle", leak, lname, env=env)
        record("an ingest commit that carried the raw record is refused even once untracked",
               r.returncode != 0 and "entered" in r.stderr and lrec and lrec["ingests"] == [], r.stderr)
        (leak / "raw").mkdir()
        shutil.copy2(leak / "state" / "trunk" / "runs" / f"{lname}.json", leak / "raw" / "run.json")
        git(leak, "add", "-A")
        git(leak, *G, "commit", "-q", "-m", "ingest: copied to raw")
        r = run(TRUNK, "run", "ingested", "--bundle", leak, lname, env=env)
        record("an ingest that copied the raw record elsewhere is refused, naming the copy",
               r.returncode != 0 and "raw/run.json" in r.stderr and "entered" in r.stderr, r.stderr)

    r, out = run_json("list", "--bundle", b, "--open", env=env)
    record("run list --open leaves out the dispatched run",
           r.returncode == 0 and out is not None and [x["name"] for x in out["runs"]] == [f"{name}-2"], out)

    # ── missing or unreadable on resume ───────────────────────────────────────
    r = run(TRUNK, "run", "show", "--bundle", b, "no-such-run", env=env)
    record("a missing record says so and offers to start over from the topic",
           r.returncode != 0 and "no run record" in r.stderr and "start over" in r.stderr, r.stderr)
    (b / "state" / "trunk" / "runs" / "broken.json").write_text("{half a rec", encoding="utf-8")
    r = run(TRUNK, "run", "show", "--bundle", b, "broken", env=env)
    record("an unreadable record says so and offers to start over",
           r.returncode != 0 and "unreadable" in r.stderr and "start over" in r.stderr, r.stderr)
    r, out = run_json("list", "--bundle", b, env=env)
    record("list skips an unreadable record and says so",
           r.returncode == 0 and out is not None and len(out["runs"]) == 2 and "broken" in r.stderr, r.stderr)
    record("list --json names the unreadable record by path, for the resume picker to say",
           out is not None and [os.path.basename(p) for p in out.get("unreadable", [])] == ["broken.json"], out)
    empty = git_bundle(root, "no-runs")
    r, out = run_json("list", "--bundle", empty, env=env)
    record("a bundle with no runs lists none and writes nothing",
           r.returncode == 0 and out is not None and out["runs"] == []
           and not (empty / "state" / "trunk").exists(), r.stderr or out)

    # ── the ignore rule, when it cannot be trusted ────────────────────────────
    covered = git_bundle(root, "covered", "state/\n")
    r = run(TRUNK, "run", "new", "--bundle", covered, "--topic", "t", env=env)
    record("a bundle that already ignores state/ gets no extra entry",
           r.returncode == 0 and (covered / ".gitignore").read_text(encoding="utf-8") == "state/\n",
           r.stderr)
    plain = make_bundle(root, "not-git")
    r = run(TRUNK, "run", "new", "--bundle", plain, "--topic", "t", env=env)
    record("a bundle that is not a git repo still records, and still gets the ignore entry",
           r.returncode == 0 and "state/trunk/" in (plain / ".gitignore").read_text(encoding="utf-8"),
           r.stderr)
    if has_git:
        reinc = git_bundle(root, "reincluded")
        (reinc / "state" / ".gitignore").write_text("!trunk/\n", encoding="utf-8")
        r = run(TRUNK, "run", "new", "--bundle", reinc, "--topic", "t", env=env)
        record("a rule that re-includes state/trunk/ refuses the write, and nothing is written",
               r.returncode != 0 and "not git-ignored" in r.stderr
               and not (reinc / "state" / "trunk" / "runs").exists(), r.stderr)
        tracked = git_bundle(root, "tracked", "")
        (tracked / "state" / "trunk").mkdir(parents=True)
        (tracked / "state" / "trunk" / "old.json").write_text("{}", encoding="utf-8")
        git(tracked, "add", "-A")
        r = run(TRUNK, "run", "new", "--bundle", tracked, "--topic", "t", env=env)
        record("a bundle that already tracks state/trunk/ refuses the write",
               r.returncode != 0 and "already tracks" in r.stderr
               and not (tracked / "state" / "trunk" / "runs").exists(), r.stderr)


def _recipe_written(root, home):
    env = env_for(home)
    b = git_bundle(root, "recipes")
    _, out = run_json("new", "--bundle", b, "--topic", "Split the export by area", env=env)
    name = out["name"] if out else "x"
    rdir = root / "orq-recipes"
    rdir.mkdir()
    src = root / "split_by_area.py"
    src.write_text("def run(t):\n    return 'done'\n", encoding="utf-8")
    test = root / "test_split_by_area.py"
    test.write_text("def test_it():\n    pass\n", encoding="utf-8")
    R = ("recipe",)
    show = lambda: run_json("show", "--bundle", b, name, env=env)[1] or {}

    # ── draft: kept beside the record, git-ignored, hashed ───────────────────
    r = run(TRUNK, *R, "draft", "--bundle", b, name, "--name", "Split-Area", "--roles", "build",
            "--file", src, env=env)
    record("a recipe name that is not lowercase letters, digits and _ is refused",
           r.returncode != 0 and "not a recipe name" in r.stderr, r.stderr)
    r = run(TRUNK, *R, "draft", "--bundle", b, name, "--name", "split_by_area",
            "--roles", "build: one session per area\nreview: reads the diff", "--file", src,
            "--test", test, "--command", "orq start split_by_area k1 --repo /r --brief b.md", "--json",
            env=env)
    try:
        dr = json.loads(r.stdout)
    except ValueError:
        dr = {}
    draft = b / "state" / "trunk" / "recipes" / name / "split_by_area.py"
    record("recipe draft keeps the recipe and its check file under state/trunk/recipes/<run>/",
           r.returncode == 0 and Path(dr.get("draft", "")) == draft and draft.is_file()
           and (draft.parent / "test_split_by_area.py").is_file(), r.stderr or dr)
    rec = show()
    rc = rec.get("recipe") or {}
    record("the draft becomes the run's recipe: name, roles, command, unchecked, unsaved, no fact",
           rc.get("name") == "split_by_area" and rc.get("roles", "").startswith("build:")
           and rc.get("command", "").startswith("orq start split_by_area") and rc.get("check") is None
           and rc.get("fact") is None and (rc.get("written") or {}).get("saved") is None
           and (rc.get("written") or {}).get("sha256") == dr.get("sha256"), rc)
    git(b, "add", "-A")
    staged = git(b, "diff", "--cached", "--name-only").stdout.splitlines()
    record("an `ingest`-style `git add -A` stages no recipe draft",
           not any(x.startswith("state/trunk") for x in staged), staged)
    r = run(TRUNK, "run", "set", "--bundle", b, name, "recipe", "--value",
            json.dumps({"name": "x", "written": {"saved": "/tmp/x.py"}, "check": {"ok": True}}), env=env)
    record("run set cannot forge a written recipe or its check",
           r.returncode != 0 and "recipe draft" in r.stderr and show().get("recipe", {}).get("name") == "split_by_area",
           r.stderr)

    # ── nothing starts before a passed check ─────────────────────────────────
    D = ("run", "dispatch", "--bundle", b, name, "--via", "orq", "--command", "orq start split_by_area k1")
    r = run(TRUNK, *D, env=env)
    record("an unchecked written recipe is never started: nothing is dispatched",
           r.returncode != 0 and "never checked" in r.stderr and show().get("status") == "open"
           and show().get("attempts") == [], r.stderr)
    r = run(TRUNK, *R, "save", "--bundle", b, name, "--dir", rdir, env=env)
    record("an unchecked recipe is not saved", r.returncode != 0 and not any(rdir.iterdir()), r.stderr)
    r = run(TRUNK, *R, "checked", "--bundle", b, name, "--command", "pytest test_split_by_area.py",
            "--error", "AssertionError: review never asked\nline 2", env=env)
    rec = show()
    record("a failed check keeps the recipe, the failure and a note; the run stays open",
           r.returncode == 0 and rec.get("status") == "open" and rec["recipe"]["check"]["ok"] is False
           and "review never asked" in rec["recipe"]["check"]["error"] and draft.is_file()
           and any("failed its check" in n["text"] for n in rec.get("log", [])), r.stderr or rec)
    r = run(TRUNK, *D, env=env)
    record("a recipe that failed its check is never started",
           r.returncode != 0 and "failed its check" in r.stderr and show().get("attempts") == [], r.stderr)
    r = run(TRUNK, "run", "show", "--bundle", b, name, env=env)
    record("the plain show names the recipe and its failed check",
           "split_by_area" in r.stdout and "review never asked" in r.stdout, r.stdout)

    # ── the check is held against what was drafted ───────────────────────────
    r = run(TRUNK, *R, "draft", "--bundle", b, name, "--name", "split_by_area", "--roles", "build",
            "--file", src, "--test", test, env=env)
    r = run(TRUNK, *R, "checked", "--bundle", b, name, "--command", "pytest", env=env)
    draft.write_text("def run(t):\n    return 'edited'\n", encoding="utf-8")
    r = run(TRUNK, *R, "save", "--bundle", b, name, "--dir", rdir, env=env)
    record("a draft edited after its check is not saved",
           r.returncode != 0 and "changed after its check" in r.stderr and not any(rdir.iterdir()), r.stderr)
    r = run(TRUNK, *R, "checked", "--bundle", b, name, "--command", "pytest", env=env)
    record("a check is not recorded over a draft edited behind the record's back",
           r.returncode != 0 and "changed since" in r.stderr, r.stderr)
    run(TRUNK, *R, "draft", "--bundle", b, name, "--name", "split_by_area", "--roles", "build",
        "--file", src, "--test", test, env=env)
    run(TRUNK, *R, "checked", "--bundle", b, name, "--command", "pytest", env=env)
    r = run(TRUNK, *D, env=env)
    record("a checked recipe is started only once it is saved",
           r.returncode != 0 and "not saved" in r.stderr, r.stderr)

    # ── save: never replacing a recipe already there ─────────────────────────
    (rdir / "split_by_area.py").write_text("# an older team's recipe\n", encoding="utf-8")
    r = run(TRUNK, *R, "save", "--bundle", b, name, "--dir", rdir, env=env)
    record("a recipe already in the directory is never replaced",
           r.returncode != 0 and "never replaced" in r.stderr
           and (rdir / "split_by_area.py").read_text(encoding="utf-8") == "# an older team's recipe\n"
           and not (rdir / "test_split_by_area.py").exists(), r.stderr)
    (rdir / "split_by_area.py").unlink()
    r = run(TRUNK, *R, "save", "--bundle", b, name, "--dir", root / "no-such-dir", env=env)
    record("a recipe directory that does not exist is refused", r.returncode != 0, r.stderr)
    r = run(TRUNK, *R, "save", "--bundle", b, name, "--dir", rdir, "--json", env=env)
    try:
        sv = json.loads(r.stdout)
    except ValueError:
        sv = {}
    record("the checked recipe is saved byte for byte, with its check file",
           r.returncode == 0 and Path(sv.get("saved", "")) == rdir / "split_by_area.py"
           and (rdir / "split_by_area.py").read_bytes() == src.read_bytes()
           and (rdir / "test_split_by_area.py").read_bytes() == test.read_bytes(), r.stderr or sv)
    r = run(TRUNK, *R, "save", "--bundle", b, name, "--dir", rdir, env=env)
    record("saving again changes nothing and says it was saved already",
           r.returncode == 0 and "already saved" in r.stderr, r.stderr)
    r = run(TRUNK, *R, "fact", "--bundle", b, name, "--link", "split_by_area", env=env)
    record("a recipe's fact is a /facts/ link", r.returncode != 0, r.stderr)

    # ── started, then its fact ───────────────────────────────────────────────
    r = run(TRUNK, *D, "--where", "orq team k1", env=env)
    record("a saved recipe that passed its check is started", r.returncode == 0
           and show().get("status") == "dispatched", r.stderr)
    r = run(TRUNK, *R, "fact", "--bundle", b, name, "--link", "/facts/2026-11/recipe-split-by-area.md", env=env)
    rec = show()
    record("the recipe's trunk-recipe fact is linked after the start",
           r.returncode == 0 and rec["recipe"]["fact"] == "/facts/2026-11/recipe-split-by-area.md", r.stderr)
    r = run(TRUNK, *R, "draft", "--bundle", b, name, "--name", "other", "--roles", "x", "--file", src, env=env)
    record("a dispatched run's recipe is not drafted again",
           r.returncode != 0 and "already dispatched" in r.stderr, r.stderr)

    # ── a picked saved recipe is not held to a check it never needed ─────────
    _, o2 = run_json("new", "--bundle", b, "--topic", "picked", env=env)
    n2 = o2["name"] if o2 else "y"
    run(TRUNK, "run", "set", "--bundle", b, n2, "recipe", "--value",
        json.dumps({"name": "impl_review", "fact": "/facts/r.md", "command": "orq start impl_review", "roles": "x"}),
        env=env)
    r = run(TRUNK, "run", "dispatch", "--bundle", b, n2, "--via", "orq", "--command", "orq start impl_review", env=env)
    record("a saved recipe picked from the facts starts with no check of its own", r.returncode == 0, r.stderr)


def write_fact(bundle, name, tags, status="active", relations=None, desc=None):
    """A fact file as capture writes it from templates/fact.md, the template's
    own comment on `status:` included. Returns its /facts/ link."""
    rel = relations if relations is not None else "  supersedes: []\n  superseded-by: []\n"
    (bundle / "knowledge" / "facts" / f"{name}.md").write_text(
        "---\ntype: fact\n"
        f"description: \"{desc or 'How the owner works: ' + name}\"\n"
        "entities: []\n"
        f"relations:\n{rel}"
        "sources: []\nconfidence: high\n"
        f"status: {status}        # active | deprecated | superseded\n"
        f"tags: [{', '.join(tags)}]\n"
        "created: 2026-11-01\nupdated: 2026-11-01\noccurred: 2026-11-01\n---\n\n"
        f"The owner works this way: {name}.\n\n**Why it matters / context:** a test.\n",
        encoding="utf-8")
    return f"/facts/{name}.md"


def build_index(bundle):
    return subprocess.run([sys.executable, str(bundle / "scripts" / "build-index.py")], cwd=str(bundle),
                          capture_output=True, text=True, encoding="utf-8")


def load_trunk():
    """trunk.py as a module, to reach a helper no subcommand isolates."""
    spec = importlib.util.spec_from_file_location("trunk_under_test", TRUNK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def learning(*args, env):
    r = run(TRUNK, "learning", *args, "--json", env=env)
    try:
        return r, json.loads(r.stdout)
    except ValueError:
        return r, None


def _steer_and_forget(root, home):
    env = env_for(home)
    b = git_bundle(root, "learnings")
    (b / "scripts").mkdir()
    (b / "knowledge" / "facts").mkdir()
    shutil.copy2(BUILD_INDEX, b / "scripts" / "build-index.py")
    T = "como-trabalhar"
    study = write_fact(b, "study-open-prs", [T, "trunk-study"])
    dispatch = write_fact(b, "dispatch-orq", [T, "trunk-dispatch"])
    other = write_fact(b, "slack-voice", [T])
    plain = write_fact(b, "plain-fact", ["decision", "trunk-study"])
    block = write_fact(b, "recipe-split", [T, "trunk-recipe"],
                       relations="  supersedes: []\n  superseded-by:\n    - /facts/older.md\n")
    r = build_index(b)
    record("the learnings bundle builds its index", r.returncode == 0, r.stderr)
    _, out = facts_json("--bundle", b, env=env)
    record("before anything is forgotten the trunk reads its three learnings",
           set(links(out) or []) == {study, dispatch, block}, out)

    _, o = run_json("new", "--bundle", b, "--topic", "learnings", env=env)
    name = o["name"] if o else "x"
    run(TRUNK, "run", "set", "--bundle", b, name, "learning", "--value", f"{study}: read the open PRs first",
        env=env)
    run(TRUNK, "run", "dispatch", "--bundle", b, name, "--via", "claude-code", "--command", "plan", env=env)

    # ── forget ───────────────────────────────────────────────────────────────
    study_file = b / "knowledge" / "facts" / "study-open-prs.md"
    before = study_file.read_text(encoding="utf-8")
    r, out = learning("forget", "--bundle", b, study, "--run", name, env=env)
    record("forget exits 0 and says it changed the fact", r.returncode == 0 and out and out["changed"]
           and out["status"] == "deprecated", r.stderr)
    _, f = facts_json("--bundle", b, env=env)
    record("a forgotten learning is no longer read", study not in (links(f) or [study])
           and set(links(f) or []) == {dispatch, block}, f)
    after = study_file.read_text(encoding="utf-8")
    record("the forgotten fact's file says deprecated, with the rest of it as it was",
           re.search(r"^status: deprecated$", after, re.M) is not None
           and re.search(r"^updated: \d{4}-\d\d-\d\d$", after, re.M) is not None
           and after.split("\n---\n", 1)[1] == before.split("\n---\n", 1)[1]
           and 'description: "How the owner works: study-open-prs"' in after, after)
    _, f = facts_json("--bundle", b, "--forgotten", env=env)
    record("facts --forgotten lists it, so the trunk does not learn it again",
           links(f) == [study] and f["facts"][0]["status"] == "deprecated", f)
    r, out = learning("forget", "--bundle", b, study, env=env)
    record("forgetting it again changes nothing and says so",
           r.returncode == 0 and out and out["changed"] is False and "already" in r.stderr
           and study_file.read_text(encoding="utf-8") == after, r.stderr)
    for label, link in (("a how-I-work fact with no trunk area tag", other),
                        ("a fact with an area tag but not the how-I-work tag", plain)):
        path = b / "knowledge" / link.lstrip("/")
        was = path.read_text(encoding="utf-8")
        r = run(TRUNK, "learning", "forget", "--bundle", b, link, env=env)
        record(f"{label} is not the trunk's to forget", r.returncode != 0 and "maintain" in r.stderr
               and path.read_text(encoding="utf-8") == was, r.stderr)
    r = run(TRUNK, "learning", "forget", "--bundle", b, "/facts/nope.md", env=env)
    record("a link to no fact is refused", r.returncode != 0 and "no fact at" in r.stderr, r.stderr)
    (b / "knowledge" / "outside.md").write_text("---\ntags: [x]\n---\n", encoding="utf-8")
    for label, link in (("a link that leaves facts/ is refused", "/facts/../outside.md"),
                        ("a link that leaves facts/ through a backslash is refused",
                         "/facts/..\\outside.md")):
        r = run(TRUNK, "learning", "forget", "--bundle", b, link, env=env)
        record(label, r.returncode != 0 and "not a fact link" in r.stderr, r.stderr)
    (b / "knowledge" / "outside.md").unlink()

    # ── steer ────────────────────────────────────────────────────────────────
    new = write_fact(b, "dispatch-cc", [T, "trunk-dispatch"])
    build_index(b)
    r, out = learning("steer", "--bundle", b, dispatch, "--to", new, "--run", name, env=env)
    record("steer exits 0", r.returncode == 0 and out and out["status"] == "superseded", r.stderr)
    _, f = facts_json("--bundle", b, env=env)
    record("a steered learning is no longer read, and the one it was steered to is",
           set(links(f) or []) == {new, block}, f)
    old_text = (b / "knowledge" / "facts" / "dispatch-orq.md").read_text(encoding="utf-8")
    new_text = (b / "knowledge" / "facts" / "dispatch-cc.md").read_text(encoding="utf-8")
    record("the steered fact is superseded by the new one, and the new one supersedes it",
           re.search(r"^status: superseded$", old_text, re.M) is not None
           and f"  superseded-by: [{new}]" in old_text and f"  supersedes: [{dispatch}]" in new_text
           and re.search(r"^status: active", new_text, re.M) is not None, old_text + new_text)
    r = run(TRUNK, "learning", "steer", "--bundle", b, block, "--to", other, env=env)
    record("a learning is not steered to a fact the trunk does not read",
           r.returncode != 0 and "status: superseded" not in
           (b / "knowledge" / "facts" / "recipe-split.md").read_text(encoding="utf-8"), r.stderr)
    r = run(TRUNK, "learning", "steer", "--bundle", b, study, "--to", new, env=env)
    record("a forgotten learning is not steered", r.returncode != 0 and "deprecated" in r.stderr, r.stderr)
    newer = write_fact(b, "recipe-split-v2", [T, "trunk-recipe"])
    build_index(b)
    r, out = learning("steer", "--bundle", b, block, "--to", newer, env=env)
    block_text = (b / "knowledge" / "facts" / "recipe-split.md").read_text(encoding="utf-8")
    record("a block-list superseded-by gains the new link as one more item",
           r.returncode == 0 and f"    - /facts/older.md\n    - {newer}\n" in block_text, r.stderr + block_text)
    r = build_index(b)
    record("the edited facts still build", r.returncode == 0, r.stderr)
    trunk = load_trunk()
    flush = ["relations:", "  superseded-by:", "  - /facts/older.md", "  supersedes: []"]
    lines = list(flush)
    added = trunk._add_relation(lines, "superseded-by", "/facts/b.md")
    record("a block list written at the key's own indent (PyYAML's style) gains one more item",
           added is True and lines == ["relations:", "  superseded-by:", "  - /facts/older.md",
                                       "  - /facts/b.md", "  supersedes: []"], lines)
    lines = list(flush)
    added = trunk._add_relation(lines, "superseded-by", "/facts/older.md")
    record("a link already in that block list is not added again", added is False and lines == flush, lines)

    # ── the run record ───────────────────────────────────────────────────────
    _, rec = run_json("show", "--bundle", b, name, env=env)
    steers = (rec or {}).get("steers", [])
    record("a dispatched run records what was forgotten and steered in it",
           [(s["link"], s["action"], s["to"]) for s in steers]
           == [(study, "forgotten", None), (dispatch, "steered", new)], steers)
    r = run(TRUNK, "run", "show", "--bundle", b, name, env=env)
    record("run show marks the learning that was forgotten",
           f"{study}: read the open PRs first (forgotten)" in r.stdout
           and f"{dispatch}: steered to {new}" in r.stdout, r.stdout)
    r = git(b, "status", "--porcelain", "--untracked-files=all")
    record("nothing the steer or the forget wrote is staged from state/trunk/",
           "state/trunk" not in r.stdout, r.stdout)

    # ── no build-index, nothing changed ──────────────────────────────────────
    (b / "scripts" / "build-index.py").unlink()
    was = (b / "knowledge" / "facts" / "dispatch-cc.md").read_text(encoding="utf-8")
    r = run(TRUNK, "learning", "forget", "--bundle", b, new, env=env)
    record("with no build-index.py nothing is forgotten, since the index would keep it read",
           r.returncode != 0 and "build-index.py" in r.stderr
           and (b / "knowledge" / "facts" / "dispatch-cc.md").read_text(encoding="utf-8") == was, r.stderr)



def transcript(path, records, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def owner(text, **extra):
    return {"type": "user", "cwd": "/work/repo", "timestamp": "2026-11-01T10:00:00Z",
            "origin": {"kind": "human"}, "message": {"role": "user", "content": text}, **extra}


def assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def tool_use(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


def _past_sessions(root, home):
    # ── past sessions: the estimate ──────────────────────────────────────────
    env = env_for(root / "nohome")          # no bundle anywhere: sessions need none
    projects = root / "claude" / "projects"
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    rich = transcript(projects / "-work-repo" / "rich.jsonl", [
        owner("read the open PRs before proposing, always"),
        owner("<system-reminder>injected rules</system-reminder>"),
        owner("<command-name>/bb:spec</command-name><command-message>bb:spec</command-message>"
              "<command-args>then dispatch</command-args>"),
        owner("<command-name>/compact</command-name><command-message>compact</command-message>"),
        {**owner("a skill body"), "isMeta": True},
        {**owner("a subagent prompt"), "isSidechain": True},
        {**owner("a peer message"), "origin": {"kind": "peer"}},
        owner("Another Claude session sent a message: hi"),
        owner([{"type": "tool_result", "tool_use_id": "t1", "content": "FILE CONTENT customer Acme"}]),
        assistant({"type": "text", "text": "ASSISTANT PROSE about the topic"},
                  tool_use("Skill", skill="orq"),
                  tool_use("Bash", command="TOKEN=abc orq start split --brief 'Acme; rm -rf'"
                                           " && cat x | grep y\nsecond line words"),
                  tool_use("Bash", command="python3 - <<'EOF'\nimport os; customer()\nEOF"),
                  tool_use("Agent", subagent_type="general-purpose", prompt="PROMPT TEXT")),
        owner(f"use this key {secret} and password: hunter2hunter2 please"),
        owner("\n\n<pasted_content id=\"ab\">\nmy long dictated rule\n</pasted_content id=\"ab\">\n"),
        owner("x" * 5000),
        owner("y" * 1980 + " " + secret + " and more"),
    ], 3000)
    transcript(projects / "-work-repo" / "older.jsonl", [owner("older session")], 1000)
    transcript(projects / "-work-other" / "auto.jsonl",
               [{**owner("<scheduled-task name=\"x\">run</scheduled-task>"),
                 "origin": {"kind": "task-notification"}}], 4000)
    transcript(projects / "-work-repo" / "rich" / "subagents" / "agent-1.jsonl",
               [owner("subagent transcript")], 5000)
    (projects / "-work-repo" / "memory").mkdir(parents=True, exist_ok=True)

    r = run(TRUNK, "sessions", "list", "--root", projects, "--json", env=env)
    try:
        est = json.loads(r.stdout)
    except ValueError:
        est = None
    record("sessions list runs with no bundle and prints one JSON object",
           r.returncode == 0 and est is not None, r.stdout + r.stderr)
    est = est or {}
    record("only top-level transcripts are found, a subagent's is not",
           est.get("found") == 3, est)
    record("sessions with no message of the owner's are passed over and counted",
           est.get("read") == 2 and est.get("skipped_no_owner") == 1
           and [Path(s["path"]).name for s in est.get("sessions", [])] == ["rich.jsonl", "older.jsonl"], est)
    record("the estimate carries raw size, extracted tokens and readers",
           est.get("raw_bytes", 0) > est.get("tokens", 0) * 4 > 0 and est.get("readers") == 1
           and est.get("raw_tokens") == -(-est.get("raw_bytes", 0) // 4), est)
    r = run(TRUNK, "sessions", "list", "--root", projects, "--limit", "1", "--json", env=env)
    one = json.loads(r.stdout) if r.returncode == 0 else {}
    record("--limit reads fewer, the most recent first", one.get("read") == 1
           and Path(one["sessions"][0]["path"]).name == "rich.jsonl", r.stdout + r.stderr)
    r = run(TRUNK, "sessions", "list", "--root", projects, "--batch-tokens", "100", "--json", env=env)
    small = json.loads(r.stdout) if r.returncode == 0 else {}
    record("a smaller reader budget splits the sessions into more readers, none over it",
           small.get("readers") == 2 and all(s["tokens"] <= 100 for s in small.get("sessions", []))
           and small["sessions"][0]["cut"] is True, small)
    r = run(TRUNK, "sessions", "list", "--root", projects, env=env)
    record("the plain estimate names sessions, size, tokens and readers",
           r.returncode == 0 and "3 sessions found" in r.stdout and "small-model readers" in r.stdout
           and "1 more recent sessions hold no message" in r.stdout, r.stdout + r.stderr)
    r = run(TRUNK, "sessions", "list", "--root", root / "nowhere", env=env)
    record("no transcripts directory exits 1 and names it",
           r.returncode == 1 and "no Claude Code sessions" in r.stderr, r.stderr)
    r = run(TRUNK, "sessions", "list", "--root", projects, "--limit", "0", env=env)
    record("a limit under 1 is refused", r.returncode == 1 and "--limit" in r.stderr, r.stderr)
    cfg_env = dict(env, CLAUDE_CONFIG_DIR=str(root / "claude"))
    r = run(TRUNK, "sessions", "list", "--json", env=cfg_env)
    record("with no --root, CLAUDE_CONFIG_DIR/projects is read",
           r.returncode == 0 and json.loads(r.stdout).get("root") == str(projects), r.stdout + r.stderr)

    # ── past sessions: the extract ───────────────────────────────────────────
    r = run(TRUNK, "sessions", "extract", rich, env=env)
    out = r.stdout
    record("extract runs with no bundle", r.returncode == 0, r.stderr)
    record("the owner's own messages are kept, a skill command with its arguments",
           "owner: read the open PRs before proposing, always" in out
           and "owner: /bb:spec then dispatch" in out
           and "owner: [pasted]" in out, out[:2000])
    record("a pasted block is marked, its body and the session's directory never handed over",
           "my long dictated rule" not in out and "/work/repo" not in out, out[:2000])
    leaked = [w for w in ("injected rules", "a skill body", "a subagent prompt", "a peer message",
                          "Another Claude session", "FILE CONTENT", "Acme", "ASSISTANT PROSE",
                          "PROMPT TEXT", "/compact", "customer", "second line", "TOKEN=", "abc")
              if w in out]
    record("tool output, the assistant's text, injected turns and arguments are left out",
           not leaked, leaked)
    record("what ran is named by program, skill and subagent, plumbing passed over",
           "[then: skill orq, ran orq, ran python3, subagent general-purpose]" in out, out[:2000])
    record("credential-shaped strings never reach a reader",
           secret not in out and "hunter2hunter2" not in out
           and out.count("[secret left out]") >= 2, out[:2000])
    record("a long message is cut", "x" * 2001 not in out and "[… cut]" in out, "")
    record("a token the cut would split is left out whole, not cut to a prefix",
           secret[:8] not in out, [ln[-60:] for ln in out.splitlines() if "yyy" in ln])
    redact = load_trunk()._redact
    shapes = {
        '{"password": "hunter2pass"}': "hunter2pass",
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY": "wJalrXUtnFEMI",
        "the key is wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY": "wJalrXUtnFEMI",
        "senha: Xy9!kq2pz": "Xy9!kq2pz",
        "a senha do banco é Xy9kq2pz77": "Xy9kq2pz77",
        "the password for prod is hunter2pass": "hunter2pass",
        "post to https://hooks.slack.com/services/T0000AAAA/B0000BBBB/" + "X" * 24: "T0000AAAA",
        "post to https://example.com/webhook/abc123def456ghi now": "abc123def456ghi",
        "access_tokens = abcdef1234567890xyzXYZ": "abcdef1234567890xyzXYZ",
        '"auth_tokens": "Zx81kq92LmP0aa"': "Zx81kq92LmP0aa",
        "my password is /Xy9kq2pz77!": "Xy9kq2pz77",
    }
    missed = [text for text, value in shapes.items() if value in redact(text)]
    record("a quoted key, a compound key, a bare slashed token, senha, a password in prose, "
           "a webhook URL and a key holding tokens are left out", not missed, missed)
    whole = {"senha=abc": "senha=[secret left out]",
             "export GITHUB_TOKEN=ghp_" + "a1" * 18: "export GITHUB_TOKEN=[secret left out]",
             "OPENAI_API_KEY=sk-proj-" + "b2" * 12: "OPENAI_API_KEY=[secret left out]"}
    record("a value two passes match is marked once, the marker never cut by a later pass",
           {t: redact(t) for t in whole} == whole, {t: redact(t) for t in whole})
    kept = ["read the open PRs before proposing, always", "/bb:spec then dispatch",
            "the password policy is strict, rotate every 90 days",
            "open /Users/someone/development/projects/elephant-mem/x.py",
            "see https://github.com/Inspira-Legal/stillare/pull/1234 please",
            "open docs/2026/Q3/RoadmapPlanningNotesFinal",
            "the password reset flow goes through /bb:spec and auth0",
            "the password file is ~/.config/app/creds.json, keep it there",
            "read https://docs.github.com/en/webhooks/about-webhooks first",
            "set max_tokens=4096", '"max_tokens": 4096,']
    record("ordinary words, a skill command, a path, a mixed-case link or path, a page "
           "about webhooks and a token count survive the redaction",
           [redact(t) for t in kept] == kept, [redact(t) for t in kept])
    r = run(TRUNK, "sessions", "extract", rich, "--max-tokens", "50", env=env)
    record("--max-tokens cuts a session and says how much was left",
           r.returncode == 0 and "[cut: about" in r.stdout and len(r.stdout) < 400, r.stdout)
    r = run(TRUNK, "sessions", "extract", rich, root / "missing.jsonl", env=env)
    record("an unreadable transcript exits 1, the others still extracted",
           r.returncode == 1 and "could not read" in r.stderr and "owner: read the open PRs" in r.stdout,
           r.stderr)


if __name__ == "__main__":
    sys.exit(main())
