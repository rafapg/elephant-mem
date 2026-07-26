#!/usr/bin/env python3
"""Validate the elephant knowledge bundle against OKF v0.1 + elephant rules.

Rules:
  1. Every non-reserved `.md` under knowledge/ has frontmatter (--- ... ---)
     with a non-empty `type`.
  2. Reserved files (index.md, log.md) have NO frontmatter.
  3. Bundle-absolute links `](/path.md)` resolve to an existing file.
  4. No [[wikilinks]] anywhere.

Non-fatal WARNINGS (do not affect the exit code):
  - alias/title collision: a name (case-insensitive) shared by the title or
    aliases of MORE THAN ONE entity file — surfaces entity conflation.
  - out-of-vocab value: a `type`/`kind`/`confidence`/`status`/`source-kind`
    value not listed in vocab.json's controlled vocabulary (skipped entirely
    when vocab.json is absent — see load_vocab()).

Exit code 0 if clean, 1 if any hard violation. Pure stdlib (PyYAML optional).
"""
import json
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
# Regenerated hub-sharding shard (see build-index.py) — has no frontmatter by
# design, so it's exempt from rule 1 (frontmatter + `type`) but still subject
# to the wikilink / broken-link checks below.
ARCHIVE_SUFFIX = ".facts-archive.md"

WIKILINK = re.compile(r"\[\[[^\]]+\]\]")
ABS_LINK = re.compile(r"\]\((/[^)\s#]+)")
FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TYPE_KEY = re.compile(r"^type:\s*(\S.*?)\s*$", re.MULTILINE)
TITLE_KEY = re.compile(r"^title:\s*(\S.*?)\s*$", re.MULTILINE)
ALIASES_KEY = re.compile(r"^aliases:\s*\[(.*)\]\s*$", re.MULTILINE)
KIND_KEY = re.compile(r"^kind:\s*(\S.*?)\s*$", re.MULTILINE)
CONFIDENCE_KEY = re.compile(r"^confidence:\s*(\S.*?)\s*$", re.MULTILINE)
STATUS_KEY = re.compile(r"^status:\s*(\S.*?)\s*$", re.MULTILINE)
SOURCE_KIND_KEY = re.compile(r"^source-kind:\s*(\S.*?)\s*$", re.MULTILINE)


def md_files(base):
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".md"):
                yield os.path.join(dirpath, f)


def read_block_list(block, key):
    """Return items of a block-sequence list field (`key:` then `  - item`
    lines), or [] if the field is absent or uses inline `[...]` syntax
    (handled separately by the caller's own regex)."""
    lines = block.splitlines()
    for idx, ln in enumerate(lines):
        if ln.strip() == f"{key}:":
            items = []
            for nxt in lines[idx + 1:]:
                stripped = nxt.strip()
                if not stripped:
                    continue
                if nxt[0] in " \t" and stripped.startswith("- "):
                    items.append(stripped[2:].strip())
                    continue
                break
            return items
    return []


def load_vocab():
    """Read vocab.json from the bundle root. None if absent or malformed —
    callers must treat that as "skip vocab checks", never as an error."""
    path = os.path.join(ROOT, "vocab.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def vocab_warnings(vocab):
    """WARN (never fail) on frontmatter values outside vocab.json's controlled
    vocabularies, grouped by (field, value) with an occurrence count. Which
    field applies depends on the file's `type`: kind/entity, confidence+status
    (fact_status)/fact, status (loop_status)/open-loop, source-kind/source."""
    if not vocab:
        return []
    counts = {}
    for path in md_files(BUNDLE):
        name = os.path.basename(path)
        if name in RESERVED or name.endswith(ARCHIVE_SUFFIX):
            continue
        with open(path, encoding="utf-8") as fh:
            m = FM.match(fh.read())
        if not m:
            continue
        block = m.group(1)
        tm = TYPE_KEY.search(block)
        type_val = tm.group(1).strip() if tm else ""

        checks = [("type", TYPE_KEY, vocab.get("type"))]
        if type_val == "entity":
            checks.append(("kind", KIND_KEY, vocab.get("kind")))
        elif type_val == "fact":
            checks.append(("confidence", CONFIDENCE_KEY, vocab.get("confidence")))
            checks.append(("status", STATUS_KEY, vocab.get("fact_status")))
        elif type_val == "open-loop":
            checks.append(("status", STATUS_KEY, vocab.get("loop_status")))
        elif type_val == "source":
            checks.append(("source-kind", SOURCE_KIND_KEY, vocab.get("source-kind")))

        for field, pattern, allowed in checks:
            if not isinstance(allowed, list):
                continue
            fm_match = pattern.search(block)
            if not fm_match:
                continue
            val = fm_match.group(1).strip()
            if val and val not in allowed:
                counts[(field, val)] = counts.get((field, val), 0) + 1

    return [f"out-of-vocab {field}='{value}' ({n} file(s))"
            for (field, value), n in sorted(counts.items())]


def alias_title_collisions():
    """Scan entities/**; collect each entity's title + aliases and detect any
    name (case-insensitive) mapping to more than one entity file. Returns a list
    of warning strings."""
    entities_dir = os.path.join(BUNDLE, "entities")
    name_to_files = {}  # lowercased name -> {display_name, files:set}
    for path in md_files(entities_dir):
        if os.path.basename(path) in RESERVED:
            continue
        with open(path, encoding="utf-8") as fh:
            m = FM.match(fh.read())
        if not m:
            continue
        block = m.group(1)
        names = []
        tm = TITLE_KEY.search(block)
        if tm and tm.group(1).strip():
            names.append(tm.group(1).strip())
        am = ALIASES_KEY.search(block)
        if am:
            names += [x.strip() for x in am.group(1).split(",") if x.strip()]
        am_block = read_block_list(block, "aliases")
        names += [x for x in am_block if x not in names]
        rel = os.path.relpath(path, BUNDLE)
        for n in names:
            key = n.lower()
            entry = name_to_files.setdefault(key, {"display": n, "files": set()})
            entry["files"].add(rel)

    warnings = []
    for entry in name_to_files.values():
        if len(entry["files"]) > 1:
            files = ", ".join(sorted(entry["files"]))
            warnings.append(f"alias/title collision: '{entry['display']}' on [{files}]")
    return sorted(warnings)


def main():
    if not os.path.isdir(BUNDLE):
        print(f"FAIL: bundle not found: {BUNDLE}")
        return 1

    errors = []
    for path in md_files(BUNDLE):
        rel = os.path.relpath(path, BUNDLE)
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()

        m = FM.match(text)
        if name in RESERVED:
            if m:
                errors.append(f"{rel}: reserved file must NOT have frontmatter")
        elif name.endswith(ARCHIVE_SUFFIX):
            pass  # generated hub-sharding shard: no frontmatter/type requirement
        else:
            if not m:
                errors.append(f"{rel}: missing frontmatter")
            else:
                t = TYPE_KEY.search(m.group(1))
                if not t or not t.group(1).strip():
                    errors.append(f"{rel}: frontmatter missing non-empty `type`")

        for w in WIKILINK.findall(text):
            errors.append(f"{rel}: forbidden wikilink {w}")

        for link in ABS_LINK.findall(text):
            target = os.path.join(BUNDLE, link.lstrip("/"))
            if not os.path.exists(target):
                errors.append(f"{rel}: broken bundle link -> {link}")

    warnings = alias_title_collisions() + vocab_warnings(load_vocab())

    if errors:
        print(f"OKF validation FAILED ({len(errors)} issue(s)):")
        for e in errors:
            print(f"  - {e}")
    else:
        print("OKF validation passed.")

    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
