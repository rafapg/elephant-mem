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
FACTS = os.path.join(BUNDLE, "facts")

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SHARE_THRESHOLD = 2


def field_list(fm, key):
    """Extract a `key: [a, b, c]` inline list from a frontmatter block."""
    m = re.search(rf"^\s*{re.escape(key)}:\s*\[(.*?)\]\s*$", fm, re.MULTILINE)
    if not m:
        return []
    return [x.strip() for x in m.group(1).split(",") if x.strip()]


def field_scalar(fm, key):
    m = re.search(rf"^{re.escape(key)}:\s*(\S.*?)\s*$", fm, re.MULTILINE)
    return m.group(1).strip() if m else None


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
