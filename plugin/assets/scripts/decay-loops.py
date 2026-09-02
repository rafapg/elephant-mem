#!/usr/bin/env python3
"""Decay stale `open` loops into `status: expired`.

Philosophy (owner-approved): loops are noise that, when it keeps recurring,
earns the right to stay alive — otherwise it should decay automatically.
Re-mention already resets the clock elsewhere: `catch-up`/`capture` bump a
loop's `updated:` field whenever a later source corroborates it. This script
only reads that signal; it never itself decides what counts as re-mention.

Candidate = `status: open` AND its last-activity date (the max of
`updated`/`opened`/`created`, whichever are present) is older than
`elephant.json` -> `decay.loop_expiry_days` (default 45 — same defensive
fallback pattern as build-index.py's `hub_max_facts`: missing file, missing
key, or malformed JSON all fall back to the default instead of crashing).

Default mode is DRY-RUN: prints one candidate per line (bundle-relative path +
age in days) plus a trailing count, and changes nothing on disk. `--apply`
flips `status: open` -> `status: expired` and stamps an `expired: YYYY-MM-DD`
field right after the status line — it never deletes a file and never touches
`done` / `dropped` / already-`expired` loops (they're excluded by the
`status: open` filter before any file is opened for writing).

Exit code is 0 whenever the script completed a run, whether or not it found
candidates — non-zero only on a hard, unexpected error. After `--apply` the
caller is expected to run `build-index.py` (this script does not — it only
touches loop files).
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

# Windows consoles default to a legacy codepage (cp1252); force UTF-8 on the
# standard streams so printing non-ASCII content (emoji, accented names)
# doesn't raise UnicodeEncodeError. No-op on POSIX / when already UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BUNDLE = Path(__file__).resolve().parent.parent

# A bundle script lives at <bundle>/scripts/, so it resolves its bundle as the
# parent of its own directory. Run from the plugin checkout that parent is
# `plugin/assets/`, and the script would create knowledge/ or state/ inside the
# assets the marketplace publishes. That is not hypothetical: `plugin/assets/
# knowledge/` once carried four derived files, committed by accident and shipped.
# Refuse rather than create. Guarded on __main__ so the suites can still
# import the module to exercise its pure functions.
if __name__ == "__main__" and BUNDLE.name == "assets" and (
    BUNDLE.parent / ".claude-plugin"
).is_dir():
    sys.exit(
        "refusing to run inside the elephant-mem plugin checkout.\n"
        "This script expects to live at <bundle>/scripts/, so it resolves its\n"
        "bundle as the parent of its own directory. Run from the checkout that\n"
        "is plugin/assets/, and it would write into the assets the marketplace\n"
        "publishes. Run it from an installed bundle instead."
    )
KNOWLEDGE = BUNDLE / "knowledge"
LOOPS_DIR = KNOWLEDGE / "tracking" / "loops"

DEFAULT_EXPIRY_DAYS = 45

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def loop_expiry_days():
    """Read `decay.loop_expiry_days` from elephant.json. Defensive by design
    (mirrors ingest-audio.py's config reader / build-index.py's hub_max_facts):
    a missing file, missing key, non-dict `decay`, or malformed JSON all fall
    back to DEFAULT_EXPIRY_DAYS instead of crashing."""
    try:
        with open(BUNDLE / "elephant.json", encoding="utf-8") as fh:
            data = json.load(fh)
        decay_cfg = data.get("decay")
        if isinstance(decay_cfg, dict):
            v = decay_cfg.get("loop_expiry_days")
            if isinstance(v, int) and v > 0:
                return v
    except Exception:
        pass
    return DEFAULT_EXPIRY_DAYS


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
    "slack:#channel"` and `owner: ["a #b"]`. Same rule and same scanning as
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


def field(block, key):
    """First `key: value` scalar match in a frontmatter block, without its
    trailing YAML comment, or None.

    open-loop.md ships `status: open          # open | done | dropped`, so with
    the comment glued on `field(block, "status") != "open"` was true for every
    loop written from the template and the whole script was a no-op — on every
    machine, since it has no PyYAML path to fall back to. Note the asymmetry
    with the writer below, which matches `^status:\\s*open\\b` and so already
    tolerated the comment (and keeps it when it rewrites the line to
    `expired`). It is the reader that was wrong.
    """
    m = re.search(rf"^{re.escape(key)}:\s*(\S.*?)\s*$", block, re.MULTILINE)
    if not m:
        return None
    return strip_comment(m.group(1)) or None


def last_activity(block):
    """Max of `updated`/`opened`/`created` (whichever parse as a date), or
    None if none of the three are present/parseable — treated as "can't tell,
    not a candidate" rather than an error."""
    dates = []
    for key in ("updated", "opened", "created"):
        v = field(block, key)
        if not v:
            continue
        m = DATE.search(v)
        if not m:
            continue
        try:
            dates.append(datetime.date.fromisoformat(m.group(0)))
        except ValueError:
            continue
    return max(dates) if dates else None


def bundle_link(path):
    return "/" + str(path.relative_to(KNOWLEDGE)).replace("\\", "/")


def loop_files():
    if not LOOPS_DIR.is_dir():
        print(f"note: {LOOPS_DIR} doesn't exist — nothing to decay", file=sys.stderr)
        return []
    return sorted(p for p in LOOPS_DIR.iterdir() if p.suffix == ".md")


def expire_block(block, expired_date):
    """Rewrite a frontmatter block's `status: open` line to `status: expired`
    and stamp `expired: <date>` right after it (updating it in place if a
    stray `expired:` line already exists). Returns the new block, or None if
    the block has no `status: open` line (caller should skip the file)."""
    lines = block.splitlines()
    status_idx = next(
        (i for i, ln in enumerate(lines) if re.match(r"^status:\s*open\b", ln)), None
    )
    if status_idx is None:
        return None
    lines[status_idx] = re.sub(r"^(status:\s*)open\b", r"\1expired", lines[status_idx])
    expired_idx = next((i for i, ln in enumerate(lines) if re.match(r"^expired:\s*", ln)), None)
    if expired_idx is not None:
        lines[expired_idx] = f"expired: {expired_date}"
    else:
        lines.insert(status_idx + 1, f"expired: {expired_date}")
    return "\n".join(lines)


def find_candidates(expiry_days):
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=expiry_days)
    candidates = []
    for path in loop_files():
        text = path.read_text(encoding="utf-8")
        m = FM.match(text)
        if not m:
            continue
        block = m.group(1)
        if field(block, "status") != "open":
            continue
        activity = last_activity(block)
        if activity is None or activity > cutoff:
            continue
        candidates.append((path, text, m, (today - activity).days))
    candidates.sort(key=lambda c: -c[3])
    return candidates


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                     help="expire the candidates found (default: dry-run, changes nothing)")
    args = ap.parse_args()

    expiry_days = loop_expiry_days()
    candidates = find_candidates(expiry_days)

    if not args.apply:
        for path, _text, _m, age_days in candidates:
            print(f"{bundle_link(path)}  ({age_days}d stale)")
        print(f"\n{len(candidates)} candidate(s) for decay "
              f"(status: open, stale > {expiry_days}d — dry-run, pass --apply to expire)")
        return 0

    today_str = datetime.date.today().isoformat()
    n_expired = 0
    for path, text, m, age_days in candidates:
        new_block = expire_block(m.group(1), today_str)
        if new_block is None:
            print(f"warning: {bundle_link(path)} — could not locate `status: open` line, skipped",
                  file=sys.stderr)
            continue
        new_text = text[:m.start(1)] + new_block + text[m.end(1):]
        path.write_text(new_text, encoding="utf-8")
        n_expired += 1
        print(f"expired: {bundle_link(path)}  ({age_days}d stale)")

    print(f"\n{n_expired} loop(s) expired (status: open -> expired, stale > {expiry_days}d). "
          f"Run build-index.py next.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
