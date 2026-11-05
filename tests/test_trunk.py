#!/usr/bin/env python3
"""Standalone test suite for elephant-trunk's `assets/scripts/trunk.py`.

Covers the plugin's shape (its plugin.json, its CHANGELOG, its marketplace
entry), how it finds the bundle (`--bundle`, then ELEPHANT_BUNDLE, then the
machine pointer, with elephant-wiki's guidance when none resolves), and how it
reads `trunk.tag` from elephant.json (the bundle's value, or `how-i-work` with a
hint on how to set another), and how `facts` lists the owner's how from
knowledge/manifest.jsonl alone.

Pure stdlib, Python 3.10+, mirroring tests/test_wiki.py's conventions: a
throwaway bundle in a tempdir, subprocess calls into the real script, PASS/FAIL
per check, exit 0 only if every check passes. The machine pointer is faked by
pointing HOME (and USERPROFILE, for Windows) at the tempdir, so the real
~/.config/elephant-mem/config.json is never read.
"""
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


if __name__ == "__main__":
    sys.exit(main())
