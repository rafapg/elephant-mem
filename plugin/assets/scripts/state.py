#!/usr/bin/env python3
"""Operational state for the elephant `catch-up` routine.

Canonical machine state lives in `state/cursors.json` + `state/processed-events.json`.
`state/watermarks.md` is a human-readable rendering, regenerated on every
mutation (like the OKF derived files — do NOT hand-edit it). `state/` is NOT part
of the OKF bundle (not under `knowledge/`), so `validate-okf.py` never touches it.

Two cursors per channel:
  live_cursor      newest content ingested; the forward routine reads strictly
                   *after* this. Advance only on a successful run. Either a
                   bare ISO datetime string (legacy, treated as type `date`)
                   or a typed object `{"type": "date"|"commit", "value": ...}`.
                   `date` cursors support window arithmetic (`after`); `commit`
                   cursors only support get/set/equality (e.g. a no-op gate on
                   a repo's HEAD) — arithmetic on a `commit` cursor is a clear
                   error, not a crash.
  backfill_oldest  YYYY-MM-DD — how far back the day-by-day sweep has reached.
                   Pulled only when forward is caught up (forward-first policy).

A channel that has never been touched (missing from `cursors.json`, or present
with `live_cursor`/`backfill_oldest` set to `null` — exactly what a freshly
registered BYO source looks like) is a defined, non-crashing state:
  - `after` prints Unix epoch `0` (read everything) with a warning on stderr.
  - `next-backfill` starts the day-by-day sweep at today, also with a warning.
  - Any subcommand that *writes* a cursor (`advance-live`, `advance-backfill`,
    `set-last-run`) bootstraps a missing channel entry instead of raising
    KeyError.
A missing/`null` `config.backfill_window_start` similarly falls back to a
30-day horizon from today (with a stderr warning) instead of crashing.

Subcommands:
  show                                    print the current state
  after <channel>                         print live_cursor as a Unix ts (Slack `after`);
                                           errors on a `commit`-typed cursor
  advance-live <channel> <value> [--type date|commit]
                                           set live_cursor (forward progress); default
                                           type is `date` (bare ISO string, backward
                                           compatible); bootstraps the channel if new
  advance-backfill <channel> <date>       set backfill_oldest (one older day done);
                                           bootstraps the channel if new
  set-last-run <channel> <iso>            stamp last_run; bootstraps the channel if new
  live-cursor <channel>                   print the raw live_cursor value (any type),
                                           empty string + warning if unset
  cursor-eq <channel> <value>             exit 0 ("same") if live_cursor's value equals
                                           <value>, else exit 1 ("changed") — the no-op
                                           gate for a `commit` cursor
  mark <id> [<id>...]                     record processed calendar/Drive ids
  seen <id>                               exit 0 if id already processed, else 1
  next-backfill <channel>                 print next older day to backfill, or NONE
  render                                  rewrite watermarks.md
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Windows consoles default to a legacy codepage (cp1252); force UTF-8 on the
# standard streams so printing non-ASCII content (emoji, accented names)
# doesn't raise UnicodeEncodeError. No-op on POSIX / when already UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BUNDLE = Path(__file__).resolve().parent.parent
STATE = BUNDLE / "state"

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
CURSORS = STATE / "cursors.json"
PROCESSED = STATE / "processed-events.json"
WATERMARKS = STATE / "watermarks.md"

DEFAULT_BACKFILL_HORIZON_DAYS = 30


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def save(p, data):
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_iso(s):
    return datetime.fromisoformat(s)


def today_midnight():
    return datetime.combine(datetime.now().date(), datetime.min.time())


def cursor_type_and_value(raw):
    """Normalize a live_cursor field into (type, value).

    `raw` may be `None` (never set), a bare string (legacy — always `date`),
    or a typed object `{"type": ..., "value": ...}`.
    """
    if raw is None:
        return None, None
    if isinstance(raw, str):
        return "date", raw
    if isinstance(raw, dict):
        return raw.get("type", "date"), raw.get("value")
    raise ValueError(f"unrecognized live_cursor shape: {raw!r}")


def require_date_cursor(ctype, ch):
    """Exit with a friendly error if `ctype` isn't `date`-compatible (or unset)."""
    if ctype not in (None, "date"):
        print(
            f"error: '{ch}' live_cursor is type '{ctype}', which has no date/window "
            "arithmetic — only 'date' cursors support 'after' and similar time-based "
            "operations",
            file=sys.stderr,
        )
        sys.exit(2)


def ensure_channel(chans, ch):
    """Bootstrap a missing channel entry instead of KeyError'ing on it."""
    if ch not in chans:
        chans[ch] = {"live_cursor": None, "backfill_oldest": None, "last_run": None}
        print(f"note: '{ch}' wasn't in cursors.json yet — bootstrapped a new entry", file=sys.stderr)
    return chans[ch]


def extract_flag(args, flag):
    """Pull `<flag> <value>` out of a positional args list.

    Returns (value_or_None, remaining_args).
    """
    if flag in args:
        i = args.index(flag)
        value = args[i + 1]
        remaining = args[:i] + args[i + 2:]
        return value, remaining
    return None, args


def format_cursor(raw):
    ctype, value = cursor_type_and_value(raw)
    if value is None:
        return "—"
    if ctype == "date":
        return value
    return f"{value} ({ctype})"


def render(cur):
    lines = [
        "# Watermarks",
        "",
        "Operational cursors for the `elephant catch-up` routine. **Regenerated by",
        "`scripts/state.py` — do not hand-edit** (canonical state is `cursors.json`).",
        "Not part of the OKF bundle (not under `knowledge/`).",
        "",
        "- **live_cursor** — newest content already ingested; the forward routine",
        "  reads strictly *after* this and advances it. Timestamp-granular, so empty",
        "  runs are cheap and a partial day is never re-deduped. Either a bare ISO",
        "  string (`date` type) or a typed `commit` cursor (shown as `<value> (commit)`).",
        "- **backfill_oldest** — how far back the day-by-day sweep has reached; pulled",
        "  only once forward is caught up (forward-first).",
        "",
        "| channel | live_cursor | backfill_oldest | last_run |",
        "|---------|-------------|-----------------|----------|",
    ]
    for name, c in cur["channels"].items():
        lines.append(
            f"| {name} | {format_cursor(c.get('live_cursor'))} | "
            f"{c.get('backfill_oldest') or '—'} | {c.get('last_run') or '—'} |"
        )
    cfg = cur.get("config", {})
    lines += [
        "",
        f"Backfill window floor: **{cfg.get('backfill_window_start') or '?'}** "
        f"(30-day horizon). gcal lag={cfg.get('gcal_lag_hours','?')}h, "
        f"lookback={cfg.get('gcal_lookback_hours','?')}h.",
        "",
        "Advance a cursor ONLY after a successful ingest + validate + commit.",
        "",
    ]
    WATERMARKS.write_text("\n".join(lines), encoding="utf-8")


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    cur = load(CURSORS)
    chans = cur["channels"]
    cfg = cur.get("config", {})

    if cmd == "show":
        print(json.dumps(cur, indent=2, ensure_ascii=False))
    elif cmd == "after":
        ch = rest[0]
        ch_state = chans.get(ch, {})
        ctype, value = cursor_type_and_value(ch_state.get("live_cursor"))
        require_date_cursor(ctype, ch)
        if value is None:
            print(
                f"note: '{ch}' has no live_cursor yet (never ingested) — "
                "returning epoch 0 (read everything)",
                file=sys.stderr,
            )
            print(0)
        else:
            print(int(parse_iso(value).timestamp()))
    elif cmd == "advance-live":
        ctype, rest = extract_flag(rest, "--type")
        ctype = ctype or "date"
        ch, value = rest[0], rest[1]
        entry = ensure_channel(chans, ch)
        if ctype == "date":
            parse_iso(value)  # validate
            entry["live_cursor"] = value  # bare string — backward compatible on-disk shape
        elif ctype == "commit":
            entry["live_cursor"] = {"type": "commit", "value": value}
        else:
            print(f"error: unknown cursor type '{ctype}' (expected 'date' or 'commit')", file=sys.stderr)
            return 2
        save(CURSORS, cur)
        render(cur)
        print(f"{ch} live_cursor -> {value} (type={ctype})")
    elif cmd == "advance-backfill":
        ch, date = rest[0], rest[1]
        datetime.strptime(date, "%Y-%m-%d")  # validate
        entry = ensure_channel(chans, ch)
        entry["backfill_oldest"] = date
        save(CURSORS, cur)
        render(cur)
        print(f"{ch} backfill_oldest -> {date}")
    elif cmd == "set-last-run":
        ch, iso = rest[0], rest[1]
        parse_iso(iso)
        entry = ensure_channel(chans, ch)
        entry["last_run"] = iso
        save(CURSORS, cur)
        render(cur)
        print(f"{ch} last_run -> {iso}")
    elif cmd == "live-cursor":
        ch = rest[0]
        ch_state = chans.get(ch, {})
        _, value = cursor_type_and_value(ch_state.get("live_cursor"))
        if value is None:
            print(f"note: '{ch}' has no live_cursor yet (never ingested)", file=sys.stderr)
            print("")
        else:
            print(value)
    elif cmd == "cursor-eq":
        ch, value = rest[0], rest[1]
        ch_state = chans.get(ch, {})
        _, current = cursor_type_and_value(ch_state.get("live_cursor"))
        if current == value:
            print("same")
            return 0
        print("changed")
        return 1
    elif cmd == "mark":
        proc = load(PROCESSED)
        s = set(proc["processed"])
        before = len(s)
        s.update(rest)
        proc["processed"] = sorted(s)
        save(PROCESSED, proc)
        print(f"marked {len(s) - before} new ({len(s)} total)")
    elif cmd == "seen":
        proc = load(PROCESSED)
        return 0 if rest[0] in set(proc["processed"]) else 1
    elif cmd == "next-backfill":
        ch = rest[0]
        ch_state = chans.get(ch, {})
        backfill_oldest = ch_state.get("backfill_oldest")
        if backfill_oldest is None:
            print(
                f"note: '{ch}' has no backfill_oldest yet (never backfilled) — "
                "starting from today",
                file=sys.stderr,
            )
            oldest = today_midnight() + timedelta(days=1)  # so next day = today
        else:
            oldest = datetime.strptime(backfill_oldest, "%Y-%m-%d")

        floor_str = cfg.get("backfill_window_start")
        if floor_str is None:
            floor = today_midnight() - timedelta(days=DEFAULT_BACKFILL_HORIZON_DAYS)
            print(
                f"note: config.backfill_window_start not set — defaulting to a "
                f"{DEFAULT_BACKFILL_HORIZON_DAYS}-day horizon",
                file=sys.stderr,
            )
        else:
            floor = datetime.strptime(floor_str, "%Y-%m-%d")

        nxt = oldest - timedelta(days=1)
        print("NONE" if nxt < floor else nxt.strftime("%Y-%m-%d"))
    elif cmd == "render":
        render(cur)
        print("watermarks.md regenerated")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
