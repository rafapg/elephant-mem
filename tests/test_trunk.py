#!/usr/bin/env python3
"""Standalone test suite for elephant-trunk's `assets/scripts/trunk.py`.

Covers the plugin's shape (its plugin.json, its CHANGELOG, its marketplace
entry), how it finds the bundle (`--bundle`, then ELEPHANT_BUNDLE, then the
machine pointer, with elephant-wiki's guidance when none resolves), and how it
reads `trunk.tag` from elephant.json (the bundle's value, or `how-i-work` with a
hint on how to set another).

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


if __name__ == "__main__":
    sys.exit(main())
