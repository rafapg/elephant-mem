#!/usr/bin/env python3
"""The mechanics of elephant-trunk: what the skill reads from the bundle.

elephant-trunk takes a loose topic to dispatched work. The skill is a skeleton;
every *how* comes from the owner's elephant-mem facts carrying the bundle's
how-I-work tag plus a trunk area tag. This script is the deterministic part the
skill calls into: it finds the bundle and reads the trunk's config from it.

It runs from the plugin (`${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py`) and is
never copied into the bundle: `elephant-update` re-syncs only the plugins it
knows by name, so an in-bundle copy would go stale with no one to refresh it.

Commands:
  config                print the bundle and the how-I-work tag the trunk reads
    --json              the same, as one JSON object on stdout
  --bundle <path>       override bundle location (default: ELEPHANT_BUNDLE, then
                        the machine pointer ~/.config/elephant-mem/config.json)

The bundle is resolved exactly as elephant-wiki resolves it, and a bundle that
cannot be found stops with the same guidance.

Pure stdlib, Python 3.10+. Cross-platform (explicit UTF-8 I/O).
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

POINTER = os.path.expanduser("~/.config/elephant-mem/config.json")

# The how-I-work tag when elephant.json sets none. The area tags are fixed: the
# skill reads the owner's how for each step through one of them.
DEFAULT_TAG = "how-i-work"
AREA_TAGS = ("trunk-study", "trunk-dispatch", "trunk-recipe")

SET_TAG_HINT = ('to read another tag, set it in elephant.json: '
                '"trunk": {"tag": "<your-tag>"}')


def die(msg):
    print(f"trunk.py: {msg}", file=sys.stderr)
    sys.exit(1)


def note(msg):
    print(f"trunk.py: {msg}", file=sys.stderr)


# ── bundle resolution ────────────────────────────────────────────────────────

def resolve_bundle(override=""):
    """`--bundle`, then ELEPHANT_BUNDLE, then the machine pointer: the order
    and the messages elephant-wiki's wiki.py uses, so a user who has seen one
    plugin's guidance knows the other's."""
    if not override:
        override = os.environ.get("ELEPHANT_BUNDLE", "")
    if override:
        root = os.path.abspath(os.path.expanduser(override))
    else:
        try:
            with open(POINTER, encoding="utf-8") as fh:
                root = json.load(fh)["bundle_path"]
        except (OSError, ValueError, KeyError, TypeError):
            die(f"no bundle pointer at {POINTER} — pass --bundle <path>")
        root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(os.path.join(root, "knowledge")):
        die(f"{root} does not look like a bundle (no knowledge/)")
    return root


# ── config ───────────────────────────────────────────────────────────────────

def read_tag(bundle):
    """The how-I-work tag this bundle's trunk reads, and where it came from.

    Returns (tag, source, problem). `source` is "elephant.json" when the
    bundle sets `trunk.tag`, else "default". `problem` is None, or a sentence
    saying why a value present in elephant.json was not used. A missing or
    malformed config never stops the trunk: it falls back to the default and
    says so, the same leniency elephant-wiki shows when it reads hooks."""
    path = os.path.join(bundle, "elephant.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except OSError:
        return DEFAULT_TAG, "default", None
    except ValueError as exc:
        return DEFAULT_TAG, "default", f"cannot parse {path} ({exc})"
    if not isinstance(cfg, dict):
        return DEFAULT_TAG, "default", f"{path} is not a JSON object"
    trunk = cfg.get("trunk")
    if trunk is None:
        return DEFAULT_TAG, "default", None
    if not isinstance(trunk, dict):
        return DEFAULT_TAG, "default", '"trunk" in elephant.json is not an object'
    if "tag" not in trunk:
        return DEFAULT_TAG, "default", None
    tag = trunk["tag"]
    if not isinstance(tag, str) or not tag.strip():
        return DEFAULT_TAG, "default", '"trunk.tag" in elephant.json is not a non-empty string'
    return tag.strip(), "elephant.json", None


def config(bundle):
    tag, source, problem = read_tag(bundle)
    return {"bundle": bundle, "tag": tag, "tag_source": source,
            "area_tags": list(AREA_TAGS), "problem": problem}


def cmd_config(args):
    cfg = config(resolve_bundle(args.bundle))
    if cfg["problem"]:
        note(f"{cfg['problem']}; reading the default tag")
    if cfg["tag_source"] == "default":
        note(f'no trunk.tag in elephant.json, reading "{DEFAULT_TAG}"; {SET_TAG_HINT}')
    if args.json:
        print(json.dumps(cfg, ensure_ascii=False))
        return 0
    print(f"trunk: bundle {cfg['bundle']}")
    print(f"trunk: how-I-work tag {cfg['tag']} (from {cfg['tag_source']})")
    print(f"trunk: area tags {', '.join(cfg['area_tags'])}")
    return 0


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bundle", default="", help="bundle root (default: ELEPHANT_BUNDLE, then the machine pointer)")
    ap = argparse.ArgumentParser(prog="trunk.py", description="The mechanics of elephant-trunk.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("config", parents=[common], help="print the bundle and the how-I-work tag")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_config)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
