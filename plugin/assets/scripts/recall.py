#!/usr/bin/env python3
"""Recall record for elephant-mem — what the owner's answers actually cite.

Two files, one purpose. `state/consumption-log.jsonl` is the raw, append-only
trace: one JSON line per answered read, holding the bundle-absolute paths that
answer cited and the entity slugs it was about. `state/recall.json` is the
rolled-up pyramid over that trace, the fixed-size lookup a consumer reads
instead of rescanning the log per item.

**Why the line is written by this script and not typed by the model.** The
log shipped as prose in `_shared/core.md`: every adopting procedure re-typed
the JSON object, and every one of them carried its own chance of a malformed
line or a missing field. One writer kills that class, and puts the
swallow-and-continue in one place instead of in every procedure. It is called
after the answer is decided, so it can never change or delay an answer:

    python3 scripts/recall.py log --mode query \\
        --item /entities/person/angelo.md --item /facts/2026-08/export-fix.md \\
        --entity angelo --entity acme

**Failure is silent by contract.** A missing or unwritable `state/` makes `log`
exit 0 and write nothing. A read must never fail, and must never emit anything
of its own into the transcript, because of telemetry. `show` is how you check
whether the record is being written.

**`state/recall.json` is disposable.** It is derived from a git-ignored log and
rebuildable only forward, so every consumer must behave correctly when it is
absent, empty or malformed — `load()` returns the empty record for all three,
warning once on stderr for the malformed case rather than raising.

**The record is sensitive.** It holds which entities were consulted and when,
which exposes query patterns over named people. Nothing here prints a path or a
slug except `show`, which is the operator deliberately asking to see it, and
`roll` guarantees the two files are git-ignored before it writes either of them
— see `ensure_gitignore()`. The seed `.gitignore` carries the rules, but `init`
copies that file once and `update` re-syncs only `scripts/` and `templates/`, so
every bundle created before the rules existed would otherwise commit the roll-up
on the next `decay` or `catch-up` run, both of which end in `git add -A`.

**The pyramid is bought for read cost, not for disk.** 26 lines over 33 days is
26.8 KB; even twenty times that coverage is half a megabyte a year. What does
not scale is the question decay asks: "was this item cited lately?", asked once
per open loop — 1784 of them — against a log that only grows. `roll` folds the
log into fixed-size per-item buckets so that question is a dict lookup:
day-by-day for the last 14 days, week-by-week out to 90, month-by-month out to
365, and one `older` aggregate beyond. Buckets coarsen as they age and never
refine, so an item's record converges to at most 14 + 12 + 12 + 1 keys however
long the bundle lives.

**It is item-agnostic on purpose.** The log records facts, loops and sources in
one `facts_cited` array, so the roll-up covers all of them at no extra cost.
What differs is the consumer: a loop is a claim about the future that can die,
so recall feeds its expiry; a fact is a claim about the past that silence
cannot falsify, so recall may only ever feed its ranking.

Subcommands:
  log --mode <mode> [--item <bundle path>]... [--entity <slug>]...
                            append one line to the consumption log. Silent,
                            always exits 0. `--item` and `--entity` repeat;
                            both are normalized and de-duplicated here so the
                            caller never has to.
  roll                      fold the consumption log into `state/recall.json`'s
                            pyramid, coarsen the aged buckets, and drop items
                            whose file is gone. Idempotent: `rolled_through`
                            watermarks the last line folded, so re-running over
                            the same log adds nothing. The only writer of
                            `state/recall.json`, and the one place that keeps
                            the bundle's `.gitignore` covering `state/`'s
                            machine-local files.
  score [--item <path>]... [--entity <slug>]... [--json]
                            the lookup decay reads: per key, the date it was
                            last cited and how often. Absent, empty or
                            malformed record — all three report no citation.
  show                      dump the canonical `state/recall.json`.

Every mutating subcommand accepts `--at <iso>` to override "now" (tests, and
replaying a run). Timestamps are generated in Python, never shelled out to
`date` — BSD `date` on macOS has no `%:z` and silently emits a literal `:z`,
which is not parseable ISO 8601.
"""
import argparse
import calendar
import json
import posixpath
import re
import sys
from datetime import date, datetime
from pathlib import Path

# Windows consoles default to a legacy codepage (cp1252); force UTF-8 on the
# standard streams so printing non-ASCII content (accented names, em dashes)
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
KNOWLEDGE = BUNDLE / "knowledge"
LOG = STATE / "consumption-log.jsonl"
RECALL = STATE / "recall.json"

SCHEMA = 1

# The pyramid's three steps, in days of age. Inside DAY_SPAN a citation keeps
# its own date; past it the day folds into its ISO week, past WEEK_SPAN the week
# folds into its calendar month, past MONTH_SPAN the month folds into one
# aggregate. Bounds an item at 14 + 12 + 12 + 1 keys, forever.
DAY_SPAN = 14
WEEK_SPAN = 90
MONTH_SPAN = 365
AGGREGATE = "older"

DAY_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEEK_KEY = re.compile(r"^(\d{4})-W(\d{2})$")
MONTH_KEY = re.compile(r"^(\d{4})-(\d{2})$")

# Coarseness order. Re-bucketing may only ever move a key rightwards along it:
# a week bucket holds days as new as its Sunday, so classifying it by that
# Sunday alone would "refine" it back into a single day and lie about the other
# six. GRAIN is what forbids that.
GRAIN = {"day": 0, "week": 1, "month": 2, AGGREGATE: 3}

COMMENT = (
    "Rolled-up recall record — which bundle items and entities the owner's "
    "answers actually cited, and when. Derived from the git-ignored "
    "state/consumption-log.jsonl and rebuildable only forward, so it is "
    "disposable: every consumer treats it as empty when it is missing. "
    "Managed by scripts/recall.py; do not hand-edit."
)


def now_iso(at=None):
    """Local time with a real UTC offset, as ISO 8601."""
    if at:
        return datetime.fromisoformat(at).isoformat()
    return datetime.now().astimezone().isoformat()


def _strip_bundle_prefix(s):
    """Reduce a real filesystem path inside this bundle to a bundle-relative one.

    Tried against the path as given *and* against its resolved form: on macOS a
    bundle under a tempdir resolves through `/var` → `/private/var`, so an
    honest absolute path from a caller does not textually match the script's own
    resolved root. Leaves anything outside the bundle untouched.
    """
    candidates = [s]
    if s.startswith("/") or (len(s) > 2 and s[1] == ":"):
        try:
            candidates.append(Path(s).resolve().as_posix())
        except (OSError, ValueError):
            pass
    for candidate in candidates:
        for prefix in (KNOWLEDGE.as_posix(), BUNDLE.as_posix()):
            if candidate.startswith(prefix + "/"):
                return candidate[len(prefix):]
    return s


def normalize_item(raw):
    """Coerce one cited path to the bundle-absolute form `/facts/….md`.

    Callers hand over whatever they had in the answer: a bundle-absolute link
    exactly as written in the markdown, a `knowledge/`-relative path, or the
    real filesystem path a tool printed. All three name the same file, and a
    consumer that has to guess which convention a line used cannot prune a
    path that no longer exists. Normalize once, at the only writer.

    Returns None for anything that is not a path (empty, or bare `/`).
    """
    s = (raw or "").strip().replace("\\", "/")
    if not s:
        return None
    # An absolute filesystem path inside this bundle, POSIX or Windows shaped.
    # Stripping the bundle prefix leaves `/knowledge/…`, which the tail of this
    # function reduces the same way it reduces a hand-written `knowledge/…`.
    s = _strip_bundle_prefix(s)
    if s.startswith("./"):
        s = s[2:]
    if not s.startswith("/"):
        s = "/" + s
    # normpath collapses `//`, `.` and `..`; it cannot escape the leading `/`,
    # so a hostile `../../etc/passwd` lands harmlessly at `/etc/passwd`.
    s = posixpath.normpath(s)
    if s.startswith("/knowledge/"):
        s = s[len("/knowledge"):]
    return s if s not in ("/", ".", "") else None


def normalize_entity(raw):
    """Coerce one entity reference to a bare slug.

    A mode holding `/entities/person/angelo.md` and a mode holding `angelo`
    are naming the same entity; keyed apart they would each count half.
    """
    s = (raw or "").strip().replace("\\", "/")
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    if s.endswith(".md"):
        s = s[:-3]
    return s.strip().lower() or None


def dedupe(values, normalizer):
    """Normalize, drop the empties, keep the first occurrence's order."""
    out = []
    for value in values or []:
        norm = normalizer(value)
        if norm and norm not in out:
            out.append(norm)
    return out


def append(record):
    """Append one line to the consumption log. Never raises.

    Returns True when the line landed, False when it did not. Nothing prints
    either way: this runs after an answer is decided and must not add a word
    to it, nor leak a cited path into a transcript.

    A failed write is not always a clean no-op: a mid-flush disk-full leaves a
    fragment with no trailing newline, and the next append would be
    concatenated onto it, costing two citations instead of one. So the last
    byte on disk is read first and a newline prefixed when it is missing. The
    fragment stays unparseable and is skipped by `log_rows()` — one line lost,
    which is what the suite claims — instead of taking the next good line down
    with it.
    """
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        prefix = ""
        if LOG.is_file() and LOG.stat().st_size:
            with LOG.open("rb") as fh:
                fh.seek(-1, 2)
                if fh.read(1) != b"\n":
                    prefix = "\n"
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(prefix + json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001 — best-effort by contract, see the docstring
        return False


def empty():
    """The canonical record for a bundle that has never rolled."""
    return {
        "comment": COMMENT,
        "schema": SCHEMA,
        # ISO timestamp of the last consumption line folded in. `roll` reads it
        # to stay idempotent over a log it re-reads whole every time.
        "rolled_through": None,
        "generated": None,
        # path -> bucketed citation counts; slug -> the same. Item-agnostic on
        # purpose: the log carries facts, loops and sources in one array, so
        # the roll-up covers all of them at no extra cost.
        "items": {},
        "entities": {},
    }


def load():
    """The canonical record, or the empty one. Never raises, never exits."""
    if not RECALL.exists():
        return empty()
    try:
        data = json.loads(RECALL.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
    except Exception as exc:  # noqa: BLE001
        print(
            f"warning: state/recall.json is unreadable ({exc}) — treating it as "
            "empty. It is derived state; `recall.py roll` rebuilds it forward.",
            file=sys.stderr,
        )
        return empty()
    base = empty()
    for key, default in base.items():
        value = data.get(key, default)
        if default is not None and not isinstance(value, type(default)):
            value = default
        data[key] = value
    # The version is written into every record, so it is read back out of one.
    # A record from a newer writer cannot be interpreted with v1 semantics, and
    # this file is disposable and rebuildable forward, so the honest answer is
    # the empty record and a warning — never a silent misreading of buckets
    # whose meaning changed.
    if isinstance(data["schema"], int) and data["schema"] > SCHEMA:
        print(
            f"warning: state/recall.json is schema {data['schema']}, newer than "
            f"the {SCHEMA} this script reads — treating it as empty. It is "
            "derived state; `recall.py roll` rebuilds it forward.",
            file=sys.stderr,
        )
        return empty()
    # Read as v1, so it says v1: whatever older integer was on disk, the record
    # this returns (and the one `save()` writes back) carries this writer's.
    data["schema"] = SCHEMA
    data["comment"] = COMMENT
    return data


def save(data):
    """Write the canonical record. Only `roll` should call this."""
    STATE.mkdir(parents=True, exist_ok=True)
    RECALL.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# The machine-local files under `state/` that must never be committed, in the
# spelling the seed `.gitignore` uses. `state/` itself is not ignored as a
# block, and deliberately: `cursors.json` is committed on purpose.
IGNORE_RULES = (
    "state/consumption-log.jsonl",
    "state/recall.json",
    "state/last-update-check.json",
)

# A bundle that already ignores the whole directory needs none of them.
IGNORE_BLANKET = {"state", "state/", "state/*", "/state", "/state/", "/state/*"}

IGNORE_HEADER = "# elephant-mem: machine-local state, never committed"


def ensure_gitignore():
    """Make sure the bundle's `.gitignore` covers `state/`'s local files.

    The seed carries these rules, but `init` copies the seed `.gitignore` once
    and `update` re-syncs **only** `scripts/` and `templates/`. So a bundle
    created before a rule existed never receives it, while `decay`, `catch-up`
    and `close-loops` all end in `git add -A && git commit`: the roll-up
    recording which people were looked up and when would be committed, and on
    a bundle with a remote, pushed. `roll` is where this belongs because it is
    the writer of the file that leaks.

    Appends, never rewrites. Only the rules that are actually missing are
    written, so a second roll adds nothing, and no line this function did not
    write is touched. Returns the rules it added. Never raises: an unwritable
    bundle root must not cost the roll.
    """
    path = BUNDLE / ".gitignore"
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return []
    present = {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    if present & IGNORE_BLANKET:
        return []
    missing = [
        rule for rule in IGNORE_RULES
        if rule not in present and "/" + rule not in present
    ]
    if not missing:
        return []
    addition = ""
    if text and not text.endswith("\n"):
        addition += "\n"
    if text.strip():
        addition += "\n"
    addition += IGNORE_HEADER + "\n" + "\n".join(missing) + "\n"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(addition)
    except OSError:
        return []
    print(
        f"added {len(missing)} ignore rule(s) to .gitignore: " + ", ".join(missing)
    )
    return missing


# --- the pyramid -----------------------------------------------------------


def bucket_key(day, ref):
    """The bucket a citation on `day` belongs in, seen from `ref`.

    A future-dated line (a clock skew, a hand-written `--at`) is clamped to
    age 0 rather than dropped: it is still a citation, and inventing a negative
    age would sort it ahead of everything real.
    """
    age = max((ref - day).days, 0)
    if age < DAY_SPAN:
        return day.isoformat()
    if age < WEEK_SPAN:
        iso_year, iso_week, _ = day.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if age < MONTH_SPAN:
        return f"{day.year}-{day.month:02d}"
    return AGGREGATE


def key_grain(key):
    """Which step of the pyramid a bucket key is on, or None if it is garbage."""
    if key == AGGREGATE:
        return AGGREGATE
    if DAY_KEY.match(key):
        return "day"
    if WEEK_KEY.match(key):
        return "week"
    if MONTH_KEY.match(key):
        return "month"
    return None


def key_span_end(key):
    """The newest date a bucket key can hold, or None if it is garbage.

    The newest rather than the oldest, so a bucket coarsens only once every
    citation inside it has aged out of the finer step.
    """
    grain = key_grain(key)
    try:
        if grain == "day":
            return date.fromisoformat(key)
        if grain == "week":
            iso_year, iso_week = (int(g) for g in WEEK_KEY.match(key).groups())
            return date.fromisocalendar(iso_year, iso_week, 7)
        if grain == "month":
            year, month = (int(g) for g in MONTH_KEY.match(key).groups())
            return date(year, month, calendar.monthrange(year, month)[1])
    except ValueError:
        return None
    return None


def rebucket(buckets, ref):
    """Coarsen aged buckets, merging any that now land on the same key.

    Monotone by construction: a key never moves to a finer step, so a roll is
    lossy exactly once per boundary crossed and never re-splits what it merged.
    An unparseable key is folded into the aggregate rather than dropped — the
    count is real even when the label is not.
    """
    out = {}
    for key, count in buckets.items():
        span_end = key_span_end(key)
        if span_end is None:
            target = AGGREGATE
        else:
            target = bucket_key(span_end, ref)
            if GRAIN[key_grain(target)] < GRAIN[key_grain(key)]:
                target = key
        out[target] = out.get(target, 0) + count
    return out


def entry(raw=None):
    """One item's or entity's record, coerced into shape.

    `state/recall.json` is disposable and hand-editable-by-accident, so every
    field is rebuilt from what is actually there: `total` falls back to the sum
    of the buckets, a `last` that is not a date falls back to None.
    """
    raw = raw if isinstance(raw, dict) else {}
    buckets = raw.get("buckets")
    buckets = buckets if isinstance(buckets, dict) else {}
    clean = {}
    for key, count in buckets.items():
        if isinstance(count, bool) or not isinstance(count, (int, float)):
            continue
        key = str(key).strip()
        if key:
            clean[key] = clean.get(key, 0) + int(count)
    total = raw.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        total = sum(clean.values())
    last = raw.get("last")
    if not (isinstance(last, str) and DAY_KEY.match(last)):
        last = None
    return {"total": int(total), "last": last, "buckets": clean}


def bump(table, key, day):
    """Record one citation of `key` on `day`, in its own day bucket.

    Always the day bucket, never the aged one: `rebucket` runs over the whole
    table afterwards and coarsens it in one place, so a backdated line and a
    bucket that aged out of the finer step take the same code path.
    """
    item = entry(table.get(key))
    iso = day.isoformat()
    item["buckets"][iso] = item["buckets"].get(iso, 0) + 1
    item["total"] += 1
    if item["last"] is None or iso > item["last"]:
        item["last"] = iso
    table[key] = item


def parse_ts(value):
    """An ISO timestamp as an aware datetime, or None.

    A naive timestamp gets the local zone, so a hand-written `--at` without an
    offset still compares against a watermark that has one.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def log_rows():
    """`(rows, unparseable)` — every parseable line, oldest first as written.

    Never raises. A line that is not JSON, is not an object, or carries no
    parseable `ts` is skipped: the log is appended by a best-effort writer and
    one bad line must not cost a roll the other 25. The count comes back with
    the rows because `roll` is otherwise mute about it — a log of nothing but
    junk and a log of nothing at all printed the same "0 line(s) folded", and
    the pyramid could disagree with the log with no diagnostic saying so.
    """
    rows = []
    unparseable = 0
    try:
        raw = LOG.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return rows, unparseable
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            unparseable += 1
            continue
        if not isinstance(row, dict):
            unparseable += 1
            continue
        ts = parse_ts(row.get("ts"))
        if ts is None:
            unparseable += 1
            continue
        rows.append((ts, row))
    return rows, unparseable


def prune_missing(items):
    """Drop items whose file is gone. Returns (kept, dropped count).

    Skipped entirely when `knowledge/` is not a directory: that is a bundle
    mid-move or a partial checkout, and reading it as "every cited file was
    deleted" would empty the record over an accident of timing.
    """
    if not KNOWLEDGE.is_dir():
        return items, 0
    kept = {}
    for key, item in items.items():
        norm = normalize_item(key)
        if norm and (KNOWLEDGE / norm.lstrip("/")).exists():
            kept[key] = item
    return kept, len(items) - len(kept)


def cmd_roll(args):
    ensure_gitignore()
    rows, unparseable = log_rows()
    if not rows:
        # E5. Nothing to derive from, so nothing is written — not even the
        # empty record. `roll` is the only writer of state/recall.json, and a
        # bundle that has never been read should not carry a derived file
        # saying so. A log of nothing but junk is not that case, and says so.
        print(
            "0 line(s) folded — "
            + (
                f"{unparseable} unparseable line(s), none readable"
                if unparseable
                else "the consumption log is empty or absent"
            )
        )
        return 0

    data = load()
    ref = datetime.fromisoformat(now_iso(args.at)).date()
    watermark = parse_ts(data.get("rolled_through"))
    newest = watermark
    folded = 0
    skipped = 0

    for ts, row in rows:
        # Strictly greater: the watermark is the last line already folded, and
        # re-reading the log whole every run is what makes E4 hold. The cost is
        # that a line backdated to at-or-before the watermark is skipped, which
        # is the same trade every watermark makes — counted, not swallowed, so
        # "nothing new" and "a line landed behind the watermark" read apart.
        if watermark is not None and ts <= watermark:
            skipped += 1
            continue
        day = ts.date()
        for item in dedupe(row.get("facts_cited"), normalize_item):
            bump(data["items"], item, day)
        for slug in dedupe(row.get("entities"), normalize_entity):
            bump(data["entities"], slug, day)
        folded += 1
        if newest is None or ts > newest:
            newest = ts

    data["items"], pruned = prune_missing(data["items"])
    for table in (data["items"], data["entities"]):
        for key, item in list(table.items()):
            item = entry(item)
            item["buckets"] = rebucket(item["buckets"], ref)
            table[key] = item

    data["rolled_through"] = newest.isoformat() if newest else None
    data["generated"] = now_iso(args.at)
    save(data)
    print(
        f"{folded} line(s) folded, {len(data['items'])} item(s) and "
        f"{len(data['entities'])} entity(ies) in the pyramid"
        + (f", {pruned} pruned" if pruned else "")
    )
    if skipped or unparseable:
        print(
            f"{skipped} skipped (older than watermark), {unparseable} unparseable"
        )
    return 0


def scores(data, items=None, entities=None):
    """The recall lookup, as `{"items": {...}, "entities": {...}}`.

    A key that was asked for and never cited comes back as a zeroed entry
    rather than missing, so a consumer never branches on absence — which is
    what makes an absent, empty or malformed `recall.json` degrade to "nothing
    was ever cited" instead of to a crash (E2, E3).
    """
    out = {}
    for field_name, asked in (("items", items), ("entities", entities)):
        table = data.get(field_name)
        table = table if isinstance(table, dict) else {}
        if asked is None:
            out[field_name] = {k: entry(v) for k, v in table.items()}
        else:
            out[field_name] = {k: entry(table.get(k)) for k in asked}
    return out


def last_cited(data, key, kind="items"):
    """The ISO date `key` was last cited, or None. The one call decay makes.

    Read the record once with `load()` and call this per loop: that is the
    fixed-size lookup the pyramid was built to be. Calling the `score`
    subcommand per loop would re-read the file 1784 times.
    """
    table = data.get(kind)
    table = table if isinstance(table, dict) else {}
    return entry(table.get(key))["last"]


def cmd_score(args):
    asked_items = dedupe(args.item, normalize_item) if args.item else None
    asked_entities = dedupe(args.entity, normalize_entity) if args.entity else None
    if asked_items is None and asked_entities is None:
        result = scores(load())
    else:
        result = scores(load(), asked_items or [], asked_entities or [])
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    for kind, label in (("items", "item"), ("entities", "entity")):
        rows = sorted(
            result[kind].items(), key=lambda kv: (-kv[1]["total"], kv[0])
        )
        for key, item in rows:
            print(f"{label}\t{key}\t{item['last'] or '—'}\t{item['total']}")
    return 0


def cmd_log(args):
    mode = (args.mode or "").strip()
    if not mode:
        # Not a usage error worth failing a read over: a line with no mode is
        # simply not worth writing.
        return 0
    append(
        {
            "ts": now_iso(args.at),
            "mode": mode,
            "entities": dedupe(args.entity, normalize_entity),
            "facts_cited": dedupe(args.item, normalize_item),
        }
    )
    return 0


def cmd_show(args):
    print(json.dumps(load(), indent=2, ensure_ascii=False))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="recall.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("log", help="append one consumption line (silent, always 0)")
    sp.add_argument("--mode", required=True, help="the read mode's name")
    sp.add_argument(
        "--item",
        action="append",
        default=[],
        metavar="PATH",
        help="a bundle-absolute path the answer cited; repeat per item",
    )
    sp.add_argument(
        "--entity",
        action="append",
        default=[],
        metavar="SLUG",
        help="an entity slug the answer was about; repeat per entity",
    )
    sp.add_argument("--at", help="override 'now' with an ISO timestamp")
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser(
        "roll", help="fold the consumption log into recall.json's pyramid"
    )
    sp.add_argument("--at", help="override 'now' with an ISO timestamp")
    sp.set_defaults(func=cmd_roll)

    sp = sub.add_parser("score", help="what a key was last cited, and how often")
    sp.add_argument(
        "--item",
        action="append",
        default=[],
        metavar="PATH",
        help="score this path; repeat per item. Default: every key on record",
    )
    sp.add_argument(
        "--entity",
        action="append",
        default=[],
        metavar="SLUG",
        help="score this entity slug; repeat per entity",
    )
    sp.add_argument("--json", action="store_true", help="emit JSON instead of rows")
    sp.set_defaults(func=cmd_score)

    sub.add_parser("show", help="dump the canonical recall.json").set_defaults(
        func=cmd_show
    )
    return p


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
