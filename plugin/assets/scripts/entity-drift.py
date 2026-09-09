#!/usr/bin/env python3
"""Flag entity hubs whose hand-written `description` may have fallen behind.

Three of the bundle's four knowledge surfaces already age: facts through
`maintain`'s decay and promotion, open loops through `decay` and
`close-loops`, snapshots through `snapshot-drift.py`. The fourth,
`description:` on an entity hub, has no aging mechanism at all —
`build-index.py` keeps a hub's `<!-- BEGIN auto-facts -->` block current on
every run, but the hand-written prose above it is only ever touched by
whoever wrote it.

This is the deterministic half of that gap: for each active entity hub
(`type: entity`, not `status: deprecated`), compare its own `updated` date
against every active fact (`type: fact`, `status` not
`deprecated`/`superseded`) whose `entities:` list names the hub by its
bundle-absolute path. A fact's date for this comparison is
`max(occurred, updated)`, same as snapshot-drift.py's `newest()`. A hub is a
candidate when at least one qualifying fact's date is newer than the hub's
own `updated`; `n_newer` is the count of such facts, and the newest
qualifying date is carried alongside it.

Candidates are ranked `n_newer` descending (real accumulation first), ties
broken by the gap in days between the hub's `updated` and the newest
qualifying date (descending), then by path — printed in full to stdout and
capped at `entity_drift_max` (`elephant.json` -> `maintain.entity_drift_max`,
default 25, same defensive-default shape as build-index.py's
`hub_max_facts()`), overridable per-run with `--max`. The trailing line
states the true total and how many are shown, matching snapshot-drift.py's
`"N of M snapshot(s) may have drifted."` line.

This is an ADVISORY (always exits 0 on a normal run, zero candidates
included). It never edits a hub — the owner re-tends the description by
hand and bumps `updated`, which is what makes the hub stop appearing.

Pure stdlib, no PyYAML dependency — same regex-based frontmatter reading
snapshot-drift.py uses, so there is no fallback-parser divergence to test
for here.
"""
import argparse
import datetime
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

# A bundle script lives at <bundle>/scripts/, so it resolves its bundle as the
# parent of its own directory. Run from the plugin checkout that parent is
# `plugin/assets/`, and the script would read (and a sibling would write) inside
# the assets the marketplace publishes. That is not hypothetical: `plugin/assets/
# knowledge/` once carried four derived files, committed by accident and shipped.
# Refuse rather than proceed. Guarded on __main__ so the suites can still
# import the module to exercise its pure functions.
if __name__ == "__main__" and os.path.basename(ROOT) == "assets" and os.path.isdir(
    os.path.join(os.path.dirname(ROOT), ".claude-plugin")
):
    sys.exit(
        "refusing to run inside the elephant-mem plugin checkout.\n"
        "This script expects to live at <bundle>/scripts/, so it resolves its\n"
        "bundle as the parent of its own directory. Run from the checkout that\n"
        "is plugin/assets/, and it would read the assets the marketplace\n"
        "publishes as if they were a bundle. Run it from an installed bundle instead."
    )
ENTITIES = os.path.join(BUNDLE, "entities")
FACTS = os.path.join(BUNDLE, "facts")

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DEFAULT_MAX = 25


# --- the frontmatter reader (mirrors snapshot-drift.py's, byte-for-byte) ---


def _closing_quote(v):
    """Index of the quote that closes the quoted scalar `v` (v[0] is the opening
    quote), or -1 if it is never closed. Honors the escaping rules of each YAML
    quoting style: `\\"` inside double quotes, `''` inside single quotes.
    Mirrors snapshot-drift.py's function of the same name."""
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
    one is content. Mirrors snapshot-drift.py's function of the same name."""
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


def unquote(s):
    """Unwrap a quoted scalar (list item or bare value) read by the regex
    parsers below, undoing the two escapes that quoting a free-text value
    actually produces. Mirrors snapshot-drift.py's function of the same name.

    Without it, `entities: ["/entities/person/foo.md"]` returns the item as
    `'"/entities/person/foo.md"'`, not `'/entities/person/foo.md'`, and every
    backlink match downstream fails silently: not a single quoted `entities:`
    list is ever recognized as naming its hub, and the drift report reads as
    "nothing drifted" no matter what did.
    """
    if not (len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'"):
        return s
    inner, quote = s[1:-1], s[0]
    if quote == "'":
        return inner.replace("''", "'")
    out, i, n = [], 0, len(inner)
    while i < n:
        if inner[i] == "\\" and i + 1 < n and inner[i + 1] in '"\\':
            out.append(inner[i + 1])
            i += 2
            continue
        out.append(inner[i])
        i += 1
    return "".join(out)


def strip_comment(v):
    """The scalar `v` with its trailing YAML comment removed.

    A `#` opens a comment only after a space, and only outside quotes and
    inline lists: `(#9-channel)` is content, and so are `resource:
    "slack:#channel"` and `entities: ["a #b"]`. Same rule and same scanning as
    build-index.py's / snapshot-drift.py's strip_comment().
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
    line outright (no signal — no hub could ever be named) or, when the
    comment itself carried a `]`, swallowed the comment into the list and
    made two unrelated facts "share" its words. Mirrors snapshot-drift.py's
    function of the same name.
    """
    m = re.search(rf"^\s*{re.escape(key)}:\s*(\[.*)$", fm, re.MULTILINE)
    if not m:
        return []
    v = strip_comment(m.group(1))
    if not (v.startswith("[") and v.endswith("]")):
        return []
    return [unquote(x.strip()) for x in v[1:-1].split(",") if x.strip()]


def field_scalar(fm, key):
    """A `key: value` scalar, without its trailing YAML comment.

    Kept glued, the comment poisoned readers of this shape elsewhere: dates
    compared as strings sort the comment in, and a `status: deprecated  #
    active | …` no longer equals `deprecated`. Mirrors snapshot-drift.py's
    function of the same name.
    """
    m = re.search(rf"^{re.escape(key)}:\s*(\S.*?)\s*$", fm, re.MULTILINE)
    if not m:
        return None
    return strip_comment(m.group(1)) or None


def bundle_path(abspath):
    rel = os.path.relpath(abspath, BUNDLE)
    return "/" + rel.replace(os.sep, "/")


# --- config ------------------------------------------------------------


def entity_drift_max():
    """`entity_drift_max` from elephant.json, or 25.

    Read from `maintain.entity_drift_max`. Defensive by design, like
    close-loops.py's `close_loops_max()` and build-index.py's
    `hub_max_facts()`: a missing file, a missing key, a non-dict section, a
    non-int value or malformed JSON all fall back to the default rather than
    crashing an unattended run.
    """
    try:
        with open(os.path.join(ROOT, "elephant.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 — see the docstring
        return DEFAULT_MAX
    cfg = data.get("maintain") if isinstance(data, dict) else None
    if isinstance(cfg, dict):
        v = cfg.get("entity_drift_max")
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            return v
    return DEFAULT_MAX


def positive_int(value):
    """`--max N` with N at least 1, refused at the boundary rather than
    silently rewritten. Copied from close-loops.py's `positive_int`: `--max 0`
    used to fall through to the configured default there and run the full
    default size, with nothing in the output saying so."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if n < 1:
        raise argparse.ArgumentTypeError(
            f"{value} is not a run size — pass 1 or more, or omit --max for the "
            "configured default"
        )
    return n


# --- loaders -------------------------------------------------------------


def load_hubs():
    """Every active entity hub: `type: entity`, `status` not `deprecated`.

    Keyed by bundle-absolute path (the same identity a fact's `entities:`
    list names it by), carrying its own `updated` date.
    """
    hubs = {}
    if not os.path.isdir(ENTITIES):
        return hubs
    for dirpath, _dirs, files in os.walk(ENTITIES):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            m = FM.match(text)
            if not m:
                continue
            fm = m.group(1)
            if field_scalar(fm, "type") != "entity":
                continue
            status = (field_scalar(fm, "status") or "").strip().lower()
            if status == "deprecated":
                continue
            hubs[bundle_path(path)] = {
                "updated": field_scalar(fm, "updated"),
            }
    return hubs


def load_facts():
    """Every active fact: `type: fact`, `status` not
    `deprecated`/`superseded`. Carries its `entities:` backlinks and the
    date this check compares (`max(occurred, updated)`, or None)."""
    facts = []
    if not os.path.isdir(FACTS):
        return facts
    for name in sorted(os.listdir(FACTS)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(FACTS, name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        m = FM.match(text)
        if not m:
            continue
        fm = m.group(1)
        if field_scalar(fm, "type") != "fact":
            continue
        status = (field_scalar(fm, "status") or "active").strip().lower()
        if status in ("deprecated", "superseded"):
            continue
        facts.append({
            "entities": set(field_list(fm, "entities")),
            "date": newest(field_scalar(fm, "occurred"), field_scalar(fm, "updated")),
        })
    return facts


def _iso_or_none(v):
    """`v` when it parses as an ISO date, else None — "missing" and
    "unparseable" collapse to the same outcome, so a hand-typo'd
    `occurred: 2026-99-99` cannot masquerade as a real date and outrank a
    genuinely newer fact by string comparison."""
    if not v:
        return None
    try:
        datetime.date.fromisoformat(v)
    except ValueError:
        return None
    return v


def newest(occurred, updated):
    """`max(occurred, updated)`, or None when neither parses as an ISO date —
    a fact with no usable date can never be "newer" than anything (E13).
    Mirrors snapshot-drift.py's `newest()`, extended to reject a value that
    isn't actually a parseable date rather than just an empty one."""
    dates = [d for d in (_iso_or_none(occurred), _iso_or_none(updated)) if d]
    return max(dates) if dates else None


# --- the check -------------------------------------------------------------


def day_gap(tended, fdate):
    """Days between a hub's `updated` and a qualifying fact's date, or 0 when
    either isn't a real ISO date (or is missing entirely — `fromisoformat`
    raises `TypeError` on `None`, not `ValueError`) — the tie-break degrades
    to "no gap" rather than raising on a value that merely looked like a
    date. Both call sites (`compute_candidates`) only ever pass dates
    already validated by `newest()`/`_iso_or_none()`, so this guard is
    currently untriggered defense-in-depth, not a live path."""
    try:
        t = datetime.date.fromisoformat(tended)
        f = datetime.date.fromisoformat(fdate)
    except (ValueError, TypeError):
        return 0
    return (f - t).days


def compute_candidates(hubs, facts):
    """Every hub with `n_newer >= 1`, as (path, updated, n_newer, newest_date),
    ranked `n_newer` desc, then day-gap desc, then path. A hub whose own
    `updated` doesn't parse as an ISO date is skipped entirely (E3): it never
    appears, flagged or not — the same defensive posture as
    snapshot-drift.py's own guard (`if tended and fdate and fdate > tended`).
    """
    by_hub = {}
    for hub, info in hubs.items():
        tended = info["updated"]
        if not tended:
            continue
        try:
            datetime.date.fromisoformat(tended)
        except ValueError:
            continue
        by_hub[hub] = tended

    candidates = []
    for hub, tended in by_hub.items():
        newer = [f["date"] for f in facts if hub in f["entities"] and f["date"] and f["date"] > tended]
        if not newer:
            continue
        n_newer = len(newer)
        newest_date = max(newer)
        candidates.append((hub, tended, n_newer, newest_date))

    candidates.sort(key=lambda c: (-c[2], -day_gap(c[1], c[3]), c[0]))
    return candidates


# --- rendering -------------------------------------------------------------


def render(candidates, cap):
    total = len(candidates)
    shown = candidates[:cap]
    out = []
    for hub, tended, n_newer, newest_date in shown:
        out.append(f"{hub}  updated {tended}  n_newer {n_newer}  newest {newest_date}")
    out.append(f"{min(total, cap)} of {total} entity hub(s) may be stale.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="entity-drift.py",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--max", type=positive_int, default=None, metavar="N",
                    help="how many hubs this run prints, at least 1 (default: "
                         f"elephant.json maintain.entity_drift_max, else {DEFAULT_MAX})")
    args = ap.parse_args(argv)

    hubs = load_hubs()
    if not hubs:
        print("No entity hubs found.")
        return 0

    facts = load_facts()
    cap = args.max or entity_drift_max()
    candidates = compute_candidates(hubs, facts)
    print(render(candidates, cap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
