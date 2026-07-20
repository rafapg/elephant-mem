#!/usr/bin/env python3
"""Rename/correct an entity and fix every reference to it across the bundle.

Transcription noise (e.g. the team "DevOps Circle" mis-heard as "DVOPS") leaves an
entity with the wrong name and slug. Because retrieval is entity-centric, the
canonical name lives in one file — but its slug (the link path) and prose
mentions are referenced across many files. This script, in order:

  1. moves entities/<kind>/<old>.md -> entities/<kind>/<new>.md
  2. (optional) replaces prose text via --text OLD=NEW across all bundle files
  3. rewrites every bundle link /entities/<kind>/<old>.md -> .../<new>.md
  4. sets the new `title`/`description` and MERGES --alias values, so future
     ingestion of the OLD spelling resolves back to this entity automatically

With --merge, the target slug is expected to ALREADY exist (the old entity is a
duplicate/phantom of the target). Instead of renaming, the script applies the
same --text replacements and link rewrite across the bundle, merges --alias (and
optional --title/--desc) into the EXISTING target entity, and deletes the source
entity file — collapsing the two entities into one.

Afterwards run: python3 scripts/build-index.py && python3 scripts/validate-okf.py

Example:
  python3 scripts/rename-entity.py dvops devops-circle --title "DevOps Circle" \\
      --alias DVOPS --desc "Engineering team managing platform infrastructure." \\
      --text DVOPS="DevOps Circle"

  # merge a phantom duplicate into an existing entity:
  python3 scripts/rename-entity.py john-doe jane-doe --merge \\
      --alias jonny --alias Jon
"""
import argparse
import os
import re
import sys

# Windows consoles default to a legacy codepage (cp1252); force UTF-8 on the
# standard streams so printing non-ASCII content (emoji, accented names)
# doesn't raise UnicodeEncodeError. No-op on POSIX / when already UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, "knowledge")
RESERVED = {"index.md", "log.md", "open-loops.md"}
FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def bundle_files(skip_reserved=True):
    for dp, _d, files in os.walk(BUNDLE):
        for f in files:
            if f.endswith(".md") and not (skip_reserved and f in RESERVED):
                yield os.path.join(dp, f)


def find_entity(slug):
    for dp, _d, files in os.walk(os.path.join(BUNDLE, "entities")):
        if f"{slug}.md" in files:
            return os.path.join(dp, f"{slug}.md")
    return None


def set_line(block, key, value):
    pat = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    if pat.search(block):
        return pat.sub(f"{key}: {value}", block, count=1)
    return block.rstrip() + f"\n{key}: {value}"


def merge_aliases(block, new_aliases):
    m = re.search(r"^aliases:\s*\[(.*)\]\s*$", block, re.MULTILINE)
    existing = [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []
    merged = existing + [a for a in new_aliases if a not in existing]
    return set_line(block, "aliases", "[" + ", ".join(merged) + "]")


def update_entity_fields(path, title=None, desc=None, aliases=None):
    """Set canonical title/description and MERGE aliases on an entity file's
    frontmatter (aliases applied LAST, so they survive any prose --text)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = FM.match(text)
    block = m.group(1)
    if title:
        block = set_line(block, "title", title)
    if desc:
        block = set_line(block, "description", desc)
    if aliases:
        block = merge_aliases(block, aliases)
    text = text[: m.start(1)] + block + text[m.end(1):]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def rewrite_bundle(pairs, old_link, new_link):
    """Apply --text prose replacements and the entity-link rewrite across every
    non-reserved bundle file. Returns the count of files touched."""
    touched = 0
    for path in bundle_files():
        with open(path, encoding="utf-8") as fh:
            text = orig = fh.read()
        for o, n in pairs:
            text = text.replace(o, n)
        text = text.replace(old_link, new_link)
        if text != orig:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            touched += 1
    return touched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old_slug")
    ap.add_argument("new_slug")
    ap.add_argument("--title")
    ap.add_argument("--desc")
    ap.add_argument("--alias", action="append", default=[])
    ap.add_argument("--text", action="append", default=[], help='literal prose replace "OLD=NEW"')
    ap.add_argument("--merge", action="store_true",
                    help="merge into an EXISTING target entity (collapse duplicate): "
                         "rewrite links, merge aliases into the target, delete the source file")
    args = ap.parse_args()

    src = find_entity(args.old_slug)
    if not src:
        print(f"entity not found: {args.old_slug}")
        return 1
    kind_dir = os.path.dirname(src)
    dst = os.path.join(kind_dir, f"{args.new_slug}.md")

    kind = os.path.basename(kind_dir)
    old_link = f"/entities/{kind}/{args.old_slug}.md"
    new_link = f"/entities/{kind}/{args.new_slug}.md"

    # parse --text pairs
    pairs = []
    for t in args.text:
        if "=" not in t:
            print(f"--text must be OLD=NEW, got: {t}")
            return 1
        o, n = t.split("=", 1)
        pairs.append((o, n))

    if args.merge and os.path.exists(dst):
        # MERGE: target already exists — collapse the source into it.
        # (a) prose --text + link rewrite across the bundle
        touched = rewrite_bundle(pairs, old_link, new_link)
        # (b) merge aliases (and optional title/desc) into the EXISTING target
        update_entity_fields(dst, title=args.title, desc=args.desc, aliases=args.alias)
        # (c) delete the source entity file
        os.remove(src)
        # (d) summarize
        print(f"merged {args.old_slug} -> {args.new_slug}; {touched} file(s) updated; "
              f"removed {old_link}.")
        print("now run: python3 scripts/build-index.py && python3 scripts/validate-okf.py")
        return 0

    if os.path.exists(dst):
        print(f"target already exists: {dst}")
        return 1

    # 1. move
    os.rename(src, dst)

    # 2 + 3: text replace and link rewrite across the bundle
    touched = rewrite_bundle(pairs, old_link, new_link)

    # 4: set canonical fields on the entity (LAST, so --alias survives any --text)
    update_entity_fields(dst, title=args.title, desc=args.desc, aliases=args.alias)

    print(f"renamed {old_link} -> {new_link}; {touched} file(s) updated.")
    print("now run: python3 scripts/build-index.py && python3 scripts/validate-okf.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
