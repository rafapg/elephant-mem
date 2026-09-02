#!/usr/bin/env python3
"""Flag `snapshot` facts that may have drifted.

A `snapshot` fact is a hand-written editorial rollup (e.g. an ownership map) that
encodes a judgment no query can derive — so it is NOT regenerated and NOT decayed
as an orphan. Instead it is monitored for *drift*: when a finer atomic fact that
it summarizes (or that shares its subject) becomes newer than the snapshot's
`updated` (its last-tended date), the snapshot may no longer reflect reality.

A fact F is considered a drift signal for snapshot S when:
  - F and S are linked by `relates-to` in EITHER direction (S lists F, or the
    newer F lists S — the forward link a new fact can declare that S, written in
    the past, could not), OR
  - F shares >= 2 entities with S (specific enough to avoid hub-level noise),
and max(F.updated, F.occurred) > S.updated, and F is not itself deprecated.

Signals are bucketed by strength: `relates-to` (either direction — an explicit,
high-signal link) is reported first; `shared-entities` (structural co-occurrence,
noisier) follows. The shared-entities tail is NOT suppressed — genuine drift often
arrives as a new unlinked fact, so hiding it would trade away recall.

This is an ADVISORY (always exits 0). `maintain` runs it and queues drifted
snapshots to state/needs-review.md ("re-tend or archive"). It never edits files.

Pure stdlib.
"""
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
FACTS = os.path.join(BUNDLE, "facts")

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SHARE_THRESHOLD = 2


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


def strip_comment(v):
    """The scalar `v` with its trailing YAML comment removed.

    A `#` opens a comment only after a space, and only outside quotes and
    inline lists: `(#9-channel)` is content, and so are `resource:
    "slack:#channel"` and `entities: ["a #b"]`. Same rule and same scanning as
    build-index.py's / validate-okf.py's strip_comment().
    """
    v = v.strip()
    if not v or v[0] == "#":
        return ""
    if v[0] in "\"'":
        end = _closing_quote(v)
    elif v[0] == "[":
        end = _closing_bracket(v)
    else:
        return v.split(" #", 1)[0].rstrip()
    if end < 0:
        return v  # never closed — no outside for a comment to live in
    rest = v[end + 1:]
    if not rest.strip() or rest.lstrip().startswith("#"):
        return v[:end + 1]
    return (v[:end + 1] + rest.split(" #", 1)[0]).rstrip()


def field_list(fm, key):
    """Extract a `key: [a, b, c]` inline list from a frontmatter block.

    The pattern matches to end of line, not to a `]` that ends it: fact.md
    ships `entities: []          # bundle-absolute links, e.g. [/entities/…]`,
    so on any fact that kept the comment the old `\\]\\s*$` either missed the
    line outright (no signal — `len(shared) >= SHARE_THRESHOLD` could never
    fire) or, when the comment itself carried a `]`, swallowed the comment into
    the list and made two unrelated facts "share" its words.
    """
    m = re.search(rf"^\s*{re.escape(key)}:\s*(\[.*)$", fm, re.MULTILINE)
    if not m:
        return []
    v = strip_comment(m.group(1))
    if not (v.startswith("[") and v.endswith("]")):
        return []
    return [x.strip() for x in v[1:-1].split(",") if x.strip()]


def field_scalar(fm, key):
    """A `key: value` scalar, without its trailing YAML comment.

    Kept glued, the comment poisoned both readers of this function: newest()
    compares these as strings, so `occurred: 2026-06-24  # when the content…`
    sorted ABOVE a bare `2026-06-24` and a same-day fact reported the snapshot
    as drifted; and a `status: deprecated  # active | …` no longer equalled
    `deprecated`, so a retired fact was still counted as a live drift signal.
    """
    m = re.search(rf"^{re.escape(key)}:\s*(\S.*?)\s*$", fm, re.MULTILINE)
    if not m:
        return None
    return strip_comment(m.group(1)) or None


def bundle_path(abspath):
    rel = os.path.relpath(abspath, BUNDLE)
    return "/" + rel.replace(os.sep, "/")


def load_facts():
    facts = {}
    if not os.path.isdir(FACTS):
        return facts
    for name in os.listdir(FACTS):
        if not name.endswith(".md"):
            continue
        path = os.path.join(FACTS, name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        m = FM.match(text)
        if not m:
            continue
        fm = m.group(1)
        facts[bundle_path(path)] = {
            "tags": field_list(fm, "tags"),
            "entities": set(field_list(fm, "entities")),
            "relates_to": set(field_list(fm, "relates-to")),
            "updated": field_scalar(fm, "updated"),
            "occurred": field_scalar(fm, "occurred"),
            "status": field_scalar(fm, "status"),
        }
    return facts


def newest(fact):
    return max(d for d in (fact["updated"], fact["occurred"]) if d) if (
        fact["updated"] or fact["occurred"]
    ) else None


def main():
    facts = load_facts()
    snapshots = {p: f for p, f in facts.items() if "snapshot" in f["tags"]}
    if not snapshots:
        print("No `snapshot` facts found.")
        return 0

    drifted = 0
    for spath, snap in sorted(snapshots.items()):
        tended = snap["updated"]
        signals = []
        for fpath, f in facts.items():
            if fpath == spath:
                continue
            if (f["status"] or "active") in ("deprecated", "superseded"):
                continue
            related = fpath in snap["relates_to"] or spath in f["relates_to"]
            shares = len(f["entities"] & snap["entities"]) >= SHARE_THRESHOLD
            if not (related or shares):
                continue
            fdate = newest(f)
            if tended and fdate and fdate > tended:
                signals.append((fpath, fdate, "relates-to" if related else "shared-entities"))
        if signals:
            drifted += 1
            n_rel = sum(1 for s in signals if s[2] == "relates-to")
            n_shared = len(signals) - n_rel
            print(f"\nDRIFTED: {spath} (last-tended {tended})")
            print(f"  {n_rel} relates-to (high-signal), {n_shared} shared-entities (review)")
            # relates-to bucket first, date-descending within each bucket (stable sort)
            by_date = sorted(signals, key=lambda s: s[1], reverse=True)
            ordered = sorted(by_date, key=lambda s: 0 if s[2] == "relates-to" else 1)
            for fpath, fdate, why in ordered:
                print(f"  ← {fdate}  {fpath}  [{why}]")

    print(f"\n{drifted} of {len(snapshots)} snapshot(s) may have drifted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
