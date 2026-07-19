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

Exit code 0 if clean, 1 if any hard violation. Pure stdlib (PyYAML optional).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, "knowledge")
RESERVED = {"index.md", "log.md", "open-loops.md"}

WIKILINK = re.compile(r"\[\[[^\]]+\]\]")
ABS_LINK = re.compile(r"\]\((/[^)\s#]+)")
FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TYPE_KEY = re.compile(r"^type:\s*(\S.*?)\s*$", re.MULTILINE)
TITLE_KEY = re.compile(r"^title:\s*(\S.*?)\s*$", re.MULTILINE)
ALIASES_KEY = re.compile(r"^aliases:\s*\[(.*)\]\s*$", re.MULTILINE)


def md_files(base):
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".md"):
                yield os.path.join(dirpath, f)


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

    warnings = alias_title_collisions()

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
