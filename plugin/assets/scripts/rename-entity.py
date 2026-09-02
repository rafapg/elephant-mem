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
     (if the existing `aliases:` line can't be read as an inline list, step 4
     is refused rather than overwritten — see merge_aliases)

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

# A bundle script lives at <bundle>/scripts/, so it resolves its bundle as the
# parent of its own directory. Run from the plugin checkout that parent is
# `plugin/assets/`, and the script would create knowledge/ or state/ inside the
# assets the marketplace publishes. That is not hypothetical: `plugin/assets/
# knowledge/` once carried four derived files, committed by accident and shipped.
# Refuse rather than create. Guarded on __main__ so the suites can still
# import the module to exercise its pure functions.
if __name__ == "__main__" and os.path.basename(ROOT) == "assets" and os.path.isdir(
    os.path.join(os.path.dirname(ROOT), ".claude-plugin")
):
    sys.exit(
        "refusing to run inside the elephant-mem plugin checkout.\n"
        "This script expects to live at <bundle>/scripts/, so it resolves its\n"
        "bundle as the parent of its own directory. Run from the checkout that\n"
        "is plugin/assets/, and it would write into the assets the marketplace\n"
        "publishes. Run it from an installed bundle instead."
    )
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


def _closing_quote(v):
    """Index of the quote that closes the quoted scalar `v` (v[0] is the opening
    quote), or -1 if it is never closed. Honors the escaping rules of each YAML
    quoting style: `\\"` inside double quotes, `''` inside single quotes.
    Mirrors build-index.py's function of the same name."""
    q, i, n = v[0], 1, len(v)
    while i < n:
        c = v[i]
        if q == '"' and c == "\\":
            i += 2
            continue
        if c == q:
            if q == "'" and i + 1 < n and v[i + 1] == "'":
                i += 2
                continue
            return i
        i += 1
    return -1


def _closing_bracket(v):
    """Index of the `]` closing the inline list `v` (v[0] is `[`), or -1 if it
    is never closed. A quoted item is skipped whole, so a `]` or a `#` inside
    one is content. Mirrors build-index.py's function of the same name."""
    depth, i, n = 0, 0, len(v)
    while i < n:
        c = v[i]
        if c in "\"'":
            end = _closing_quote(v[i:])
            if end < 0:
                return -1
            i += end + 1
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_comment(v):
    """Split a raw frontmatter value into (value, trailing comment).

    The comment keeps the whitespace that separated it, so `value + comment`
    reconstructs the line verbatim. A `#` opens a comment only after a space,
    and only outside quotes and inline lists: `(#9-channel)` is content, and so
    are `description: "vale #123"` and `aliases: ["a #b"]`. Same rule and same
    scanning as build-index.py's / validate-okf.py's strip_comment(), which is
    this function's `[0]` — split rather than strip because this script also
    WRITES the line back, and a comment silently dropped on rewrite is the same
    class of loss as one silently read as content.
    """
    v = v.rstrip()
    stripped = v.lstrip()
    if not stripped or stripped[0] == "#":
        return "", v
    if stripped[0] in "\"'":
        end = _closing_quote(stripped)
    elif stripped[0] == "[":
        end = _closing_bracket(stripped)
    else:
        head, sep, _tail = v.partition(" #")
        value = head.rstrip()
        return value, (v[len(value):] if sep else "")
    if end < 0:
        return v, ""  # never closed — no outside for a comment to live in
    lead = len(v) - len(stripped)
    cut = lead + end + 1
    head, sep, _tail = v[cut:].partition(" #")
    if not sep:
        return v, ""
    keep = cut + len(head.rstrip())
    return v[:keep], v[keep:]


class AliasMergeError(Exception):
    """The `aliases:` line exists but is not an inline list we can read."""


def set_line(block, key, value):
    """Set `key` to `value`, preserving any trailing YAML comment on the line."""
    pat = re.compile(rf"^{re.escape(key)}:(?P<rest>.*)$", re.MULTILINE)
    m = pat.search(block)
    if m:
        comment = split_comment(m.group("rest"))[1]
        return block[: m.start()] + f"{key}: {value}{comment}" + block[m.end():]
    return block.rstrip() + f"\n{key}: {value}"


def merge_aliases(block, new_aliases):
    """Merge `new_aliases` into the entity's inline `aliases:` list.

    Fails closed. The old reader anchored on `\\]\\s*$`, which does not match
    when the line keeps the trailing comment entity.md ships — so `existing`
    fell to `[]` and the set_line() below REPLACED the line instead of
    extending it. Silently: exit 0, no warning, every accumulated alias gone.
    That column is the roster's resolution surface, and a resolution that fails
    is what makes an ingestion invent an entity.

    So a line that is present but unreadable (an unterminated `[`, a block
    sequence) now raises rather than being overwritten. A regex that misses
    again must stop, not erase.
    """
    m = re.search(r"^aliases:(?P<rest>.*)$", block, re.MULTILINE)
    if m is None:
        existing = []
    else:
        raw = split_comment(m.group("rest"))[0].strip()
        if not (raw.startswith("[") and raw.endswith("]")):
            raise AliasMergeError(
                f"cannot read the existing aliases as an inline list: {m.group(0).strip()!r}"
            )
        existing = [x.strip() for x in raw[1:-1].split(",") if x.strip()]
    merged = existing + [a for a in new_aliases if a not in existing]
    return set_line(block, "aliases", "[" + ", ".join(merged) + "]")


def update_entity_fields(path, title=None, desc=None, aliases=None):
    """Set canonical title/description and MERGE aliases on an entity file's
    frontmatter (aliases applied LAST, so they survive any prose --text).

    Nothing is written unless every edit succeeded: an unreadable `aliases:`
    line aborts the whole update rather than half-applying it."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = FM.match(text)
    block = m.group(1)
    if title:
        block = set_line(block, "title", title)
    if desc:
        block = set_line(block, "description", desc)
    if aliases:
        block = merge_aliases(block, aliases)  # may raise AliasMergeError
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


def refuse(path, exc, kept=None, landed=None):
    """Report an aborted alias merge and exit non-zero. The `aliases:` line is
    left exactly as it was — the whole point is that we do not overwrite a line
    we could not read. But the steps BEFORE the merge have already landed, so
    `landed` has to say which: a bare "nothing was written" reads as "the command
    did nothing", and what follows is a re-run with a slug that no longer
    resolves, over a bundle whose links were in fact already rewritten."""
    print(f"refusing to rewrite aliases on {path}: {exc}", file=sys.stderr)
    print("The `aliases:` line was left exactly as it was. Fix it by hand "
          "(an inline list, e.g. `aliases: [A, B]`) and re-run.", file=sys.stderr)
    if landed:
        print(landed, file=sys.stderr)
    if kept:
        print(f"The source entity was NOT deleted: {kept}", file=sys.stderr)
    return 1


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
        # (b) merge aliases (and optional title/desc) into the EXISTING target.
        # If the aliases can't be read, refuse — and in particular do NOT reach
        # (c) below, which would delete the source entity in exchange for a
        # merge that never happened.
        try:
            update_entity_fields(dst, title=args.title, desc=args.desc, aliases=args.alias)
        except AliasMergeError as exc:
            return refuse(
                dst, exc, kept=src,
                landed=f"Already landed before this step: {touched} file(s) had their "
                       f"links rewritten from {old_link} to {new_link}.")
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
    try:
        update_entity_fields(dst, title=args.title, desc=args.desc, aliases=args.alias)
    except AliasMergeError as exc:
        return refuse(
            dst, exc,
            landed=f"Already landed before this step: the rename {old_link} -> {new_link}, "
                   f"and {touched} file(s) had their links rewritten. Only the alias merge "
                   f"was skipped: add it to {new_link} by hand. Do not re-run with the old "
                   f"slug, which no longer resolves.")

    print(f"renamed {old_link} -> {new_link}; {touched} file(s) updated.")
    print("now run: python3 scripts/build-index.py && python3 scripts/validate-okf.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
