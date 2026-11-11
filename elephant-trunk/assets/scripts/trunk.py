#!/usr/bin/env python3
"""The mechanics of elephant-trunk: what the skill reads from the bundle.

elephant-trunk takes a loose topic to dispatched work. The skill is a skeleton;
every *how* comes from the owner's elephant-mem facts carrying the bundle's
how-I-work tag plus a trunk area tag. This script is the deterministic part the
skill calls into: it finds the bundle, reads the trunk's config from it, and
lists the owner's how from the manifest.

It runs from the plugin (`${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py`) and is
never copied into the bundle: `elephant-update` re-syncs only the plugins it
knows by name, so an in-bundle copy would go stale with no one to refresh it.

Commands:
  config                print the bundle and the how-I-work tag the trunk reads
    --json              the same, as one JSON object on stdout, with
                        `slack_dm`: the channel delivery.start_day posts to
                        when it is via slack (the owner's self-DM), else null
  hours [--at <time>]   the owner's business hours: elephant.json's timezone
                        (IANA name or fixed offset; the machine's when unset)
                        and trunk.business_hours (days, start, end; Monday to
                        Friday 09:00 to 18:00 when unset), whether they are
                        open at --at (default: now), when the open window
                        closes and when the next one opens
    --json              the same, as one JSON object
  facts                 list the active facts carrying the how-I-work tag plus a
                        trunk area tag, read from knowledge/manifest.jsonl only;
                        exits 1, with `problem` in --json, when elephant.json is
                        present but its trunk.tag cannot be used; --json
                        also names the near misses, facts that would match
                        under another case or split on commas
    --area <tag>        only this area tag (repeatable; default: all four)
    --forgotten         the learnings forgotten or steered instead
    --json              one JSON object on stdout; each fact also carries
                        its `origin` (owner, other or unknown) and the
                        `channels` of the sources it cites: only a fact whose
                        every source is the owner's own Claude Code
                        conversation (channel claude-code[:<workspace>], as
                        capture files it) is `owner`
  run new --topic <t>   start a run record; prints its name
    [--name <n>]        the run's name (default: <date>-<slug of the topic>)
  run show <name>       read a run record back (--json: the record itself)
  run list              the runs, most recent first (--open: not dispatched yet,
                        open or starting);
                        --json also names the records that could not be read
  run set <name> <field> (--value <v> | --file <path|->)
                        continue a run: study, brief (text, replaced);
                        approaches (JSON array), recipe (JSON object), replaced;
                        decision, note, learning, pending (text, appended);
                        pending is a learning surfaced mid-run and not
                        captured yet, kept so an exit before step 4 loses none;
                        a merge-level: decision is refused (the merge level
                        is retired, one already recorded stays as history),
                        a hold: or hold lifted: decision says why, and a
                        recipe's command, a pending learning or a learning
                        never carries a merge parameter
    [--pending <n>]     with learning or note: settles pending learning n
                        (1-based, in the record's `pending`), as captured
                        (learning) or set aside (note); refuses one settled
  run claim <name> --via <orq|claude-code> --command <c> [--where <w>]
                        before the dispatch command runs: flips an open run to
                        starting under the record's lock, so of two sessions
                        claiming it exactly one wins; refuses a run that is
                        not open (starting, dispatched or waiting); via orq,
                        refuses a command carrying a merge parameter: the
                        start stops at the pull request, and the merge is
                        decided when the run's wait sees it approved
  run dispatch <name> --via <orq|claude-code> --command <c> [--where <w>]
                        [--error <e>]
                        record how the start went, ending the claim: without
                        --error the run becomes dispatched, with it the run is
                        open again for a retry; refuses a run that is not
                        starting (claim it first); when --command is not the
                        claimed one, refuses it via orq and warns via
                        claude-code; a dispatched run refuses another
  run wait set <name> [--on <what>] [--repo <r>] [--branch <b>] [--team <k>]
                        [--pr <n|url>] [--sha <sha>] [--session <s>]
                        [--deploy <kind>] [--health-rule <r>]
                        [--health-window <min>] [--hold-until <time>]
                        [--state <json>] [--reminded]
                        a dispatched run starts waiting (--on required) or a
                        waiting run's wait changes: what it waits on (team,
                        approval, hour, merge, deploy, health, owner), the
                        repo (owner/name, or a local path), the branch, the
                        orq team, the pull request, the approved SHA, the
                        owning orq session, the deploy kind (service,
                        release, lexflow, local, merge, unknown) and health
                        rule and window (30 minutes when a rule names none),
                        no merge before --hold-until, what the sources
                        last saw (--state, merged key by key, null drops a
                        key), the reminder sent; an empty value clears a
                        field; a change of --on or of the state moves
                        `since` and clears `reminded`
  run wait show <name>  the run's wait and hold (--json: one object)
  run wait list         the waiting runs, most recent first
  run wait end <name> --outcome <live|merged|closed|given-back> --why <w>
                        the wait ends; the run is dispatched again, the wait
                        kept with how it ended
  run hold <name> --why <w> [--lift]
                        the owner's hold: a hold: decision that blocks the
                        run's merge until a hold lifted: decision, recorded
                        only on the owner's word
  run ingested <name> [--commit <sha>]
                        after `ingest` ran over a dispatched run's record:
                        checks that nothing under state/trunk/ is tracked and
                        that the ingest commit (default: the bundle's HEAD)
                        touched nothing there, added no byte-for-byte copy of
                        a file from there, and added no lines carrying this
                        record's "created": "<timestamp>" key, as JSON writes
                        it, together with its name; then records the
                        commit. Only that commit is read: an earlier or later
                        one, or a partial copy (the study pasted into a
                        source), is not checked
  follow poll [--now <time>] [--dry-run]
                        one tick of the follow: for each waiting run, the
                        sources in order (its orq team, read from orq's
                        store; its pull request, its merge commit's deploy
                        and time, read with gh), each compared with what the
                        run last saw; only a difference enqueues a typed event
                        under state/trunk/follow/queue/ and moves the wait.
                        Time is the held hour arriving, the open window of a
                        scheduled merge closing, the health window ending, a
                        reminder after 3 days with no change and the
                        give-back after 7. A source that cannot read
                        enqueues nothing and says why in the tick's log
                        (state/trunk/follow/poll.log); with no waiting run
                        and nothing queued it writes nothing. --dry-run reads
                        the same sources and says what would be enqueued,
                        writing nothing at all. The JSON also lists the Slack
                        notes a session could not send (`unsent`)
  follow queue [--all]  the events not delivered yet, oldest first
  follow take <id>      take a pending event for delivery: of two routines,
                        one does; an event whose run is gone is dropped
  follow wake <id>      the line that wakes a session for the event:
                        /elephant-trunk:trunk continue <run> from event <JSON>,
                        the event's structured part on one line
  follow mark <id> --as <delivered|failed|dropped> [--why <w>]
                        how the delivery went; failed keeps it queued
  follow checkout <run> the run's repository on this machine, where a new
                        session for it opens: the wait's repo when it is a
                        path, else the main checkout of the folder orq's store
                        records for the run's team, whose origin must be the
                        wait's repo
  follow unsent         the `slack not sent (<why>): <note>` notes of every
                        run that the routine has not relayed yet, each with
                        an id
  follow relayed <run> <note-id>
                        record that the routine sent that note to Slack
  recipe draft <run> --name <n> --roles <r> --file <path|->
                        [--test <path>] [--command <c>]
                        a new recipe written for this run: kept as a draft under
                        state/trunk/recipes/<run>/ and recorded as the run's recipe;
                        --command never carries a merge parameter
  recipe checked <run> --command <c> [--error <e>]
                        record the check the draft went through; a failure keeps
                        the draft and the error, and nothing is dispatched
  recipe save <run> --dir <d>
                        copy the checked draft into the recipe directory, never
                        replacing a recipe already there
  recipe fact <run> --link <l>
                        the trunk-recipe fact the saved recipe was captured with
  learning forget <link> [--run <name>]
                        forget a learning: its fact becomes `deprecated`, the
                        index is rebuilt, and the trunk no longer reads it
  learning steer <link> --to <link> [--run <name>]
                        steer a learning to the fact that replaces it: the old
                        one becomes `superseded`, linked both ways, and the
                        trunk reads the new one in its place
  sessions list [--root <dir>] [--limit <n>] [--batch-tokens <n>]
                        past Claude Code sessions first use would read: how
                        many, their size, the tokens after extraction and the
                        small-model readers it takes (no bundle needed)
  sessions extract <path>... [--max-tokens <n>]
                        the owner's own messages in those sessions and the
                        names of what each ran; tool output, the assistant's
                        text and credential-shaped strings left out
  --bundle <path>       override bundle location (default: ELEPHANT_BUNDLE, then
                        the machine pointer ~/.config/elephant-mem/config.json)

Run records live in <bundle>/state/trunk/runs/<name>.json, the follow's queue in
<bundle>/state/trunk/follow/queue/<id>.json. Before any write the
script makes sure `state/trunk/` is git-ignored in the bundle (appending it to
the bundle's .gitignore when needed) and, in a git bundle, asks git whether it
is: a record git would commit is never written.

The bundle is resolved exactly as elephant-wiki resolves it, and a bundle that
cannot be found stops with the same guidance.

Pure stdlib, Python 3.10+. Cross-platform (explicit UTF-8 I/O).
"""
import argparse
import atexit
import contextlib
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

POINTER = os.path.expanduser("~/.config/elephant-mem/config.json")

# The how-I-work tag when elephant.json sets none. The area tags are fixed: the
# skill reads the owner's how for each step through one of them.
DEFAULT_TAG = "how-i-work"
# trunk-follow: how the owner merges, deploys, keeps hours, breaks and is told,
# read by the session an event wakes once the work reached a pull request.
AREA_TAGS = ("trunk-study", "trunk-dispatch", "trunk-recipe", "trunk-follow")
# A learning the owner forgot is `deprecated`, one they steered elsewhere is
# `superseded`: elephant-mem's own fact statuses, so every reader of the
# bundle, not only the trunk, stops presenting it as current.
FORGOTTEN, STEERED = "deprecated", "superseded"
FORGOTTEN_STATUSES = (FORGOTTEN, STEERED)

SET_TAG_HINT = ('to read another tag, set it in elephant.json: '
                '"trunk": {"tag": "<your-tag>"}')


def die(msg):
    print(f"trunk.py: {msg}", file=sys.stderr)
    sys.exit(1)


def note(msg):
    print(f"trunk.py: {msg}", file=sys.stderr)


# ── bundle resolution ────────────────────────────────────────────────────────

def resolve_bundle(override=""):
    """`--bundle`, then ELEPHANT_BUNDLE, then the machine pointer: the order
    and the messages elephant-wiki's wiki.py uses, so a user who has seen one
    plugin's guidance knows the other's."""
    if not override:
        override = os.environ.get("ELEPHANT_BUNDLE", "")
    if override:
        root = os.path.abspath(os.path.expanduser(override))
    else:
        try:
            with open(POINTER, encoding="utf-8") as fh:
                root = json.load(fh)["bundle_path"]
            # A pointer edited by hand can carry a number or null: the same
            # guidance as no pointer at all, never a traceback.
            if not isinstance(root, str) or not root.strip():
                raise TypeError("bundle_path is not a non-empty string")
        except (OSError, ValueError, KeyError, TypeError):
            die(f"no bundle pointer at {POINTER} — pass --bundle <path>")
        root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(os.path.join(root, "knowledge")):
        die(f"{root} does not look like a bundle (no knowledge/)")
    return root


# ── config ───────────────────────────────────────────────────────────────────

def read_tag(bundle):
    """The how-I-work tag this bundle's trunk reads, and where it came from.

    Returns (tag, source, problem). `source` is "elephant.json" when the
    bundle sets `trunk.tag`, else "default". `problem` is None, or a sentence
    saying why a value present in elephant.json was not used. A missing
    elephant.json or `trunk.tag` reads the default. A present one that cannot
    be used (it does not parse, is not an object, or carries a `trunk.tag`
    that is not a non-empty string) returns the default with a problem, and
    the caller decides: `config` names the problem and prints the default,
    while `facts` and `learning forget|steer` stop with exit 1, and the skill
    with them, until the file is fixed, since the default would read none of
    the owner's facts."""
    path = os.path.join(bundle, "elephant.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except OSError:
        return DEFAULT_TAG, "default", None
    except ValueError as exc:
        return DEFAULT_TAG, "default", f"cannot parse {path} ({exc})"
    if not isinstance(cfg, dict):
        return DEFAULT_TAG, "default", f"{path} is not a JSON object"
    trunk = cfg.get("trunk")
    if trunk is None:
        return DEFAULT_TAG, "default", None
    if not isinstance(trunk, dict):
        return DEFAULT_TAG, "default", '"trunk" in elephant.json is not an object'
    if "tag" not in trunk:
        return DEFAULT_TAG, "default", None
    tag = trunk["tag"]
    if not isinstance(tag, str) or not tag.strip():
        return DEFAULT_TAG, "default", '"trunk.tag" in elephant.json is not a non-empty string'
    return tag.strip(), "elephant.json", None


def read_elephant_json(bundle):
    """elephant.json as a dict, or {} when it is missing or not an object."""
    try:
        with open(os.path.join(bundle, "elephant.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def slack_dm(cfg):
    """The owner's Slack self-DM as the bundle already names it: the channel
    `delivery.start_day` posts to when it goes via slack. None otherwise."""
    d = cfg.get("delivery")
    d = d.get("start_day") if isinstance(d, dict) else None
    if isinstance(d, dict) and d.get("via") == "slack":
        ch = d.get("channel_id")
        if isinstance(ch, str) and ch.strip():
            return ch.strip()
    return None


def config(bundle):
    tag, source, problem = read_tag(bundle)
    return {"bundle": bundle, "tag": tag, "tag_source": source,
            "area_tags": list(AREA_TAGS), "problem": problem,
            "slack_dm": slack_dm(read_elephant_json(bundle))}


def announce_tag(cfg):
    """Say on stderr why the default tag is read, when it is."""
    if cfg["problem"]:
        note(f"{cfg['problem']}; reading the default tag")
    elif cfg["tag_source"] == "default":
        # Only when elephant.json sets no tag at all: after a problem it does
        # set one, and "no trunk.tag" would contradict the line above.
        note(f'no trunk.tag in elephant.json, reading "{DEFAULT_TAG}"; {SET_TAG_HINT}')


def cmd_config(args):
    cfg = config(resolve_bundle(args.bundle))
    announce_tag(cfg)
    if args.json:
        print(json.dumps(cfg, ensure_ascii=False))
        return 0
    print(f"trunk: bundle {cfg['bundle']}")
    print(f"trunk: how-I-work tag {cfg['tag']} (from {cfg['tag_source']})")
    print(f"trunk: area tags {', '.join(cfg['area_tags'])}")
    if cfg["slack_dm"]:
        print(f"trunk: Slack self-DM {cfg['slack_dm']}")
    return 0


# ── business hours ───────────────────────────────────────────────────────────
#
# A change the trunk judges critical, in a repo where the merge deploys, merges
# only inside the owner's business hours. The hours are elephant.json's
# `trunk.business_hours`, read in its top-level `timezone`; with none set,
# Monday to Friday, 09:00 to 18:00. A value that cannot be used reads the
# default and says why, so a typo never stops the follow.

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_HOURS = {"days": list(WEEKDAYS[:5]), "start": "09:00", "end": "18:00"}
HHMM_RE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
OFFSET_RE = re.compile(r"([+-])(\d{2}):?(\d{2})")


def _zone(value):
    """(tzinfo, name, problem) for elephant.json's `timezone`: a fixed offset
    (`-03:00`, `Z`, `UTC`) or an IANA name. Unset, or unusable, is the
    machine's own zone, the default elephant-mem documents for it."""
    machine = datetime.datetime.now().astimezone().tzinfo
    if value is None:
        return machine, None, None
    if not isinstance(value, str) or not value.strip():
        return machine, None, f'"timezone" in elephant.json is not a usable zone ({value!r})'
    raw = value.strip()
    if raw.upper() in ("Z", "UTC"):
        return datetime.timezone.utc, raw, None
    m = OFFSET_RE.fullmatch(raw)
    if m:
        minutes = int(m.group(2)) * 60 + int(m.group(3))
        if minutes < 24 * 60:
            sign = -1 if m.group(1) == "-" else 1
            return datetime.timezone(datetime.timedelta(minutes=sign * minutes)), raw, None
        return machine, None, f'"timezone" in elephant.json is not a usable offset ({raw!r})'
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(raw), raw, None
    except Exception:  # an unknown name, or no tz database on this machine
        return machine, None, f'"timezone" in elephant.json names no zone this machine knows ({raw!r})'


def read_hours(cfg):
    """(hours, source, problem): the business hours elephant.json sets under
    `trunk.business_hours`, as {"days": [...], "start": "HH:MM", "end":
    "HH:MM"}, or the default with source "default"."""
    trunk = cfg.get("trunk")
    value = trunk.get("business_hours") if isinstance(trunk, dict) else None
    if value is None:
        return dict(DEFAULT_HOURS), "default", None
    why = None
    if not isinstance(value, dict):
        why = "is not an object"
    else:
        days = value.get("days", DEFAULT_HOURS["days"])
        start, end = value.get("start", DEFAULT_HOURS["start"]), value.get("end", DEFAULT_HOURS["end"])
        if not isinstance(days, list) or not days or \
                any(not isinstance(d, str) or d.strip().lower()[:3] not in WEEKDAYS for d in days):
            why = f"has days that are not weekdays ({days!r}; mon to sun)"
        elif not all(isinstance(v, str) and HHMM_RE.fullmatch(v.strip()) for v in (start, end)):
            why = f"has a start or end that is not HH:MM ({start!r}, {end!r})"
        elif start.strip() >= end.strip():
            why = f"ends before it starts ({start} to {end})"
    if why:
        return dict(DEFAULT_HOURS), "default", f'"trunk.business_hours" in elephant.json {why}'
    days = sorted({d.strip().lower()[:3] for d in value.get("days", DEFAULT_HOURS["days"])},
                  key=WEEKDAYS.index)
    return ({"days": days, "start": value.get("start", DEFAULT_HOURS["start"]).strip(),
             "end": value.get("end", DEFAULT_HOURS["end"]).strip()}, "elephant.json", None)


def hours_at(hours, tz, at):
    """Whether the hours are open at `at` (aware), the end of the open window
    (or None), and the start of the next window after `at`."""
    local = at.astimezone(tz)

    def edge(day, hhmm):
        h, m = (int(x) for x in hhmm.split(":"))
        return datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=tz)

    open_now, closes, opens = False, None, None
    for k in range(0, 9):
        day = local.date() + datetime.timedelta(days=k)
        if WEEKDAYS[day.weekday()] not in hours["days"]:
            continue
        start, end = edge(day, hours["start"]), edge(day, hours["end"])
        if k == 0 and start <= local < end:
            open_now, closes = True, end
        elif start > local:
            opens = start
            break
    return open_now, closes, opens


def cmd_hours(args):
    bundle = resolve_bundle(args.bundle)
    cfg = read_elephant_json(bundle)
    tz, zone, zproblem = _zone(cfg.get("timezone"))
    hours, source, hproblem = read_hours(cfg)
    problems = [p for p in (zproblem, hproblem) if p]
    for p in problems:
        note(f"{p}; reading the default")
    at = parse_when(args.at, "--at") if args.at else None
    at = datetime.datetime.fromisoformat(at) if at else datetime.datetime.now(datetime.timezone.utc)
    open_now, closes, opens = hours_at(hours, tz, at)
    iso = lambda d: d.isoformat() if d else None
    out = {"bundle": bundle, "timezone": zone or "machine", "hours": hours, "hours_source": source,
           "problems": problems, "at": at.astimezone(tz).isoformat(), "open": open_now,
           "closes": iso(closes), "opens": iso(opens)}
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
        return 0
    days = ", ".join(hours["days"])
    print(f"trunk: business hours {days}, {hours['start']} to {hours['end']} "
          f"({out['timezone']}, from {source})")
    if open_now:
        print(f"trunk: open now, closes {out['closes']}")
    else:
        print(f"trunk: closed now, opens {out['opens']}")
    return 0


# ── the owner's how ──────────────────────────────────────────────────────────

def _tags(value):
    """A manifest row's tags as a list of stripped strings. build-index always
    writes a list; a hand-edited row may carry one string or nothing."""
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(t).strip() for t in value if str(t).strip()]


def _loose_tags(tags):
    """A row's tags as a near miss reads them: each tag string split on commas
    (`tags: a, b` in a frontmatter is one string in the manifest) and
    casefolded."""
    return {p.strip().casefold() for t in tags for p in t.split(",") if p.strip()}


def how_facts(bundle, tag, areas=AREA_TAGS, near=None):
    """The owner's how: every active fact in knowledge/manifest.jsonl carrying
    `tag` plus at least one of `areas`, in manifest order (most recent first).

    Reads the manifest and nothing else, on its own fields alone: `type` is
    `fact`, the status (missing counts as `active`) is `active` once stripped
    and lowercased, and tags match exactly. Returns (facts, skipped): each fact a dict with `path`
    (absolute), `link` (the manifest's `/facts/...`), `areas` (the area tags it
    carries, among `areas`), `desc`, `tags`, `occurred` and `confidence`;
    `skipped` counts manifest lines that are not a usable JSON object. With a
    `near` list, every active fact that misses only because of the case of a
    tag or a comma-joined tag string (`Como-Trabalhar`, `tags: a, b`) is
    appended to it, with the same fields: matching stays exact, and a near
    miss is only said, never read as the owner's how. A missing manifest raises OSError: build-index writes one on every bundle, so
    its absence says the index was never built, not that the owner has no how."""
    path = os.path.join(bundle, "knowledge", "manifest.jsonl")
    wanted = [a for a in AREA_TAGS if a in areas]
    facts, skipped = [], 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(row, dict):
                skipped += 1
                continue
            if row.get("type") != "fact":
                continue
            status = str(row.get("status", "active")).strip().lower()
            if status != "active":
                continue
            tags = _tags(row.get("tags"))
            hit = [a for a in wanted if a in tags]
            into = facts
            if tag not in tags or not hit:
                loose = _loose_tags(tags)
                hit = [a for a in wanted if a in loose]
                if near is None or tag.casefold() not in loose or not hit:
                    continue
                into = near
            link = str(row.get("path") or "")
            if not link:
                skipped += 1
                continue
            into.append({
                "path": os.path.join(bundle, "knowledge", *link.lstrip("/").split("/")),
                "link": link,
                "areas": hit,
                "desc": str(row.get("desc", "")),
                "status": status,
                "tags": tags,
                "occurred": str(row.get("occurred", "")),
                "confidence": str(row.get("confidence", "")),
            })
    return facts, skipped


def cmd_facts(args):
    bundle = resolve_bundle(args.bundle)
    cfg = config(bundle)
    areas = [a for a in AREA_TAGS if not args.area or a in args.area]
    if cfg["problem"]:
        # elephant.json is there but its tag cannot be used. Reading the
        # default tag would list none of the owner's facts (they carry the tag
        # the broken file meant), send the skill into first use, and capture
        # the answers under a tag that goes unread once the file is fixed. So
        # nothing is read until it is fixed, and the problem travels in the
        # JSON as well as on stderr.
        note(f"{cfg['problem']}; fix elephant.json first: the trunk reads no fact until its "
             f"tag is usable ({SET_TAG_HINT})")
        if args.json:
            print(json.dumps({"bundle": bundle, "tag": None, "tag_source": cfg["tag_source"],
                              "problem": cfg["problem"], "areas": areas,
                              "forgotten": args.forgotten, "facts": [], "near_misses": []},
                             ensure_ascii=False))
        return 1
    announce_tag(cfg)
    try:
        near = []
        if args.forgotten:
            facts, skipped = forgotten_facts(bundle, cfg["tag"], areas), 0
        else:
            facts, skipped = how_facts(bundle, cfg["tag"], areas, near)
    except OSError:
        manifest = os.path.join(bundle, "knowledge", "manifest.jsonl")
        die(f"cannot read {manifest} — rebuild it with "
            f"python3 {os.path.join(bundle, 'scripts', 'build-index.py')}")
    if skipped:
        note(f"skipped {skipped} unreadable line(s) in knowledge/manifest.jsonl")
    if not args.forgotten:
        for f in facts + near:
            f["origin"], f["channels"] = fact_origin(bundle, f["path"])
    if not facts:
        which = "forgotten or steered" if args.forgotten else "active"
        note(f'no {which} fact carries "{cfg["tag"]}" plus a trunk area tag ({", ".join(areas)})')
    if near:
        note(f'{len(near)} fact(s) nearly carry "{cfg["tag"]}" plus a trunk area tag, under '
             f"another case or in one comma-joined tag, and are not read: "
             f"{', '.join(n['link'] for n in near)}")
    if args.json:
        print(json.dumps({"bundle": bundle, "tag": cfg["tag"], "tag_source": cfg["tag_source"],
                          "problem": None, "areas": areas, "forgotten": args.forgotten,
                          "facts": facts, "near_misses": near}, ensure_ascii=False))
        return 0
    for f in facts:
        extra = f"\t{f['status']}" if args.forgotten else ""
        print(f"{','.join(f['areas'])}\t{f['path']}\t{f['desc']}{extra}")
    return 0


# ── the run record ───────────────────────────────────────────────────────────
#
# A run is one JSON object in <bundle>/state/trunk/runs/<name>.json. Its raw
# content can hold whatever the conversation touched, so it never enters the
# bundle's history: `ingest` commits with `git add -A`, and the only thing that
# keeps a record out of that commit is the ignore rule ensured below.

RECORD_VERSION = 1
IGNORE_ENTRY = "state/trunk/"
# .gitignore lines that already cover state/trunk/ (state/ covers it too).
IGNORE_COVERS = {"state/trunk/", "state/trunk", "/state/trunk/", "/state/trunk",
                 "state/", "state", "/state/", "/state"}
NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
STATUS_OPEN, STATUS_DISPATCHED = "open", "dispatched"
# Between `run claim` and the `run dispatch` that records how the start went:
# the dispatch command may be running, so nothing else may start it.
STATUS_STARTING = "starting"
# A dispatched run whose work ends in a pull request or a branch waits on what
# comes next (the team, the approval, the hour, the merge, the deploy, the
# health window, the owner), with a structured `wait`; when the wait ends the
# run is `dispatched` again, the wait kept with how it ended.
STATUS_WAITING = "waiting"
STATUSES = (STATUS_OPEN, STATUS_STARTING, STATUS_DISPATCHED, STATUS_WAITING)
# Past the start: what was dispatched stays as dispatched, waiting or not.
STARTED = (STATUS_DISPATCHED, STATUS_WAITING)
# How long a write waits for another trunk.py holding the same record.
LOCK_WAIT = 10.0
DISPATCH_VIAS = ("orq", "claude-code")
# What `run set` may change: text replaced, JSON replaced, text appended.
TEXT_FIELDS = ("study", "brief")
JSON_FIELDS = {"approaches": list, "recipe": dict}
APPEND_FIELDS = {"decision": "decisions", "note": "log", "learning": "learnings",
                 "pending": "pending"}
# What may settle a pending learning: the learning its capture recorded, or a
# note saying why it was set aside.
SETTLES_PENDING = ("learning", "note")
# After the dispatch the conversation can go on, but what was dispatched stays
# as it was dispatched.
FROZEN_AFTER_DISPATCH = ("study", "approaches", "brief", "recipe")

# The merge parameter. The merge used to be a per-run level (`merge-level:
# manual|automatic`, recorded as a decision) that the start command carried; it
# is retired. On orq the start stops at the pull request, and the merge is
# decided when the run's wait sees the pull request approved, from the owner's
# trunk-follow facts. So no command the trunk stores or starts carries a merge
# parameter. A `merge-level:` decision already in a record stays as history and
# is never read. A merge parameter in any spelling: `merge=on-approve` (after
# `--set` or `-s`), `--set=merge=pr`, `--merge`, `MERGE:pr`. A bare value-less
# flag is one too. A bare `merge` word is one only after `--set`/`-s` or before
# an `=`: as the value of another option (`--branch merge`) it is not.
RETIRED_MERGE_LEVEL = "merge-level:"
MERGE_TOKEN_RE = re.compile(r"^(?:-{1,2}set[=:])?-{0,2}merge(?:[ \t]*[=:][ \t]*(.*))?$", re.I | re.S)
SET_FLAGS = ("--set", "-set", "-s")
MERGE_IS_THE_FOLLOWS = ("the start stops at the pull request, and the merge is decided when the "
                        "run's wait sees it approved")


def merge_params(command):
    """The merge parameters a command carries, in any spelling: one value per
    parameter (lowercased), or None for one whose value cannot be read."""
    try:
        tokens = shlex.split(command or "")
    except ValueError:
        tokens = (command or "").split()
    out = []
    for i, tok in enumerate(tokens):
        m = MERGE_TOKEN_RE.match(tok.strip())
        if not m:
            continue
        value = m.group(1)
        bare = value is None and not tok.strip().startswith("-")
        if bare and not (i and tokens[i - 1].strip().lower() in SET_FLAGS) \
                and not (i + 1 < len(tokens) and tokens[i + 1].startswith(("=", ":"))):
            continue
        if value is None and i + 1 < len(tokens) and tokens[i + 1].startswith(("=", ":")):
            value = tokens[i + 1][1:] or (tokens[i + 2] if i + 2 < len(tokens) else "")
        value = (value or "").strip().strip("'\"").lower()
        out.append(value or None)
    return out


def _refuse_stored_merge(command, what):
    if merge_params(command):
        die(f"{what} carries a merge parameter ({command!r}): no command the trunk stores or "
            f"starts carries one; {MERGE_IS_THE_FOLLOWS}")


def merge_param_problem(command):
    """Why an orq start command cannot run as it is, or None: it carries a
    merge parameter, and the merge is the follow's."""
    if merge_params(command):
        return (f"the command carries a merge parameter; on orq {MERGE_IS_THE_FOLLOWS}, so start "
                f"it with no merge parameter")
    return None


class RecordError(Exception):
    """A run record that is missing, unreadable or not a run record."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")


def runs_dir(bundle):
    return os.path.join(bundle, "state", "trunk", "runs")


def record_path(bundle, name):
    return os.path.join(runs_dir(bundle), name + ".json")


def check_name(name):
    if not NAME_RE.fullmatch(name or "") or ".." in name:
        die(f'"{name}" is not a run name: lowercase letters, digits, ".", "_" and "-", '
            f"starting with a letter or digit, at most 80 characters")
    return name


def slug(text, limit=48):
    """A run name's slug from the topic: accents dropped (a Portuguese topic
    keeps its words), anything else not alphanumeric collapsed to "-"."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return s[:limit].rstrip("-") or "run"


def ensure_ignored(bundle):
    """Make sure state/trunk/ is git-ignored before a record is written.

    Appends `state/trunk/` to the bundle's .gitignore unless a line there
    already covers it. Then, when the bundle is a git work tree, asks git
    itself: a rule elsewhere can re-include the path (`!state/trunk/` in a
    nested .gitignore), and a record already tracked is committed whatever the
    ignore file says. Either way the write is refused rather than leave raw
    conversation content for the next `git add -A`."""
    gi = os.path.join(bundle, ".gitignore")
    try:
        with open(gi, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        die(f"cannot read {gi} ({exc}); state/trunk/ must be git-ignored before a run is recorded")
    if not IGNORE_COVERS & {ln.strip() for ln in text.splitlines()}:
        sep = "" if not text or text.endswith("\n") else "\n"
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write(f"{sep}# elephant-trunk run records: raw, never committed\n{IGNORE_ENTRY}\n")
        note(f"git-ignored {IGNORE_ENTRY} in {gi}")
    git = shutil.which("git")
    if not git:
        return
    probe = "state/trunk/runs/probe.json"
    try:
        r = subprocess.run([git, "-C", bundle, "check-ignore", "-q", probe],
                           capture_output=True, text=True)
        tracked = subprocess.run([git, "-C", bundle, "ls-files", "--", "state/trunk"],
                                 capture_output=True, text=True)
    except OSError:
        return
    if r.returncode not in (0, 1):
        return  # not a git work tree (or git cannot tell): nothing will commit it
    if r.returncode == 1:
        die(f"{IGNORE_ENTRY} is not git-ignored in {bundle}: a rule re-includes it "
            f"(check `git -C {bundle} check-ignore -v {probe}`); no run record was written")
    if tracked.returncode == 0 and tracked.stdout.strip():
        die(f"{bundle} already tracks files under {IGNORE_ENTRY} "
            f"(`git -C {bundle} rm -r --cached state/trunk`); no run record was written")


def write_record(bundle, rec, create=False):
    """Write a record atomically, owner-only: a temp file in the same
    directory, then a rename, so a crash never leaves half a record. With
    `create`, an existing record of the same name is never replaced."""
    ensure_ignored(bundle)
    d = runs_dir(bundle)
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = record_path(bundle, rec["name"])
    if create:
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            return False
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".run-", suffix=".tmp", dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        # Nothing half-done stays: the temp file, and with `create` the empty
        # placeholder that reserved the name, which would keep it taken.
        for leftover in (tmp, path if create else None):
            if leftover:
                try:
                    os.unlink(leftover)
                except OSError:
                    pass
        raise
    return True


def read_record(bundle, name):
    """A run record read back, or RecordError saying why it cannot be."""
    path = record_path(bundle, name)
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except FileNotFoundError:
        raise RecordError(f"no run record named {name} ({path})")
    except (OSError, ValueError) as exc:
        raise RecordError(f"the run record {path} is unreadable ({exc})")
    if not isinstance(rec, dict) or not isinstance(rec.get("topic"), str) \
            or rec.get("status") not in STATUSES:
        raise RecordError(f"the run record {path} is not a run record")
    return rec


def load_or_die(bundle, name):
    try:
        return read_record(bundle, name)
    except RecordError as exc:
        die(f"{exc} — start over from the topic with `trunk.py run new --topic ...`")


def lock_path(bundle, name):
    return os.path.join(runs_dir(bundle), f".{name}.lock")


def lock_record(bundle, name, wait=LOCK_WAIT):
    """Hold the record's lock until this process exits.

    Every read-modify-write of a record goes through it, so two sessions
    writing the same run never lose each other's write, and of two `run
    claim` racing on one open run exactly one sees it open. The lock is an
    empty file created with O_EXCL beside the record: atomic on every
    platform, and nothing for a `git add -A` to take (state/trunk/ is
    ignored, and an empty file matches no copy check). A trunk.py killed
    while holding it leaves it behind; after `wait` seconds the write stops
    and names the file to remove."""
    path = lock_path(bundle, name)
    if not os.path.isdir(runs_dir(bundle)):
        return  # no record to change: the load that follows says so
    if not _acquire(path, wait):
        die(f"run {name} is being changed by another trunk.py (lock {path}); "
            f"try again, and remove that file only if no trunk.py is running")
    atexit.register(_release, path)


def _acquire(path, wait):
    """Create the empty lock file `path` with O_EXCL, retrying for `wait`
    seconds; False when another process still holds it."""
    deadline = time.monotonic() + wait
    while True:
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            return True
        except FileExistsError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)


def _release(path):
    try:
        os.unlink(path)
    except OSError:
        pass


@contextlib.contextmanager
def held(path, wait=LOCK_WAIT):
    """A lock held for a block only, not until the process exits: yields
    whether it was taken. The follow's poll changes many runs in one process
    and must not keep each locked while it reads GitHub for the next."""
    ok = _acquire(path, wait)
    try:
        yield ok
    finally:
        if ok:
            _release(path)


def load_for_update(bundle, name):
    """The record, read under its lock: what the caller writes back is
    computed from what no other trunk.py is changing."""
    lock_record(bundle, name)
    return load_or_die(bundle, name)


def new_record(name, topic):
    t = now()
    return {"version": RECORD_VERSION, "name": name, "topic": topic,
            "status": STATUS_OPEN, "created": t, "updated": t,
            "study": None, "approaches": [], "decisions": [], "brief": None,
            "recipe": None, "claim": None, "dispatch": None, "attempts": [], "log": [],
            "ingests": [], "learnings": [], "pending": [], "steers": []}


def list_records(bundle):
    """Every readable record, most recently updated first, plus the names of
    the files that could not be read."""
    d = runs_dir(bundle)
    try:
        names = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and not f.startswith("."))
    except FileNotFoundError:
        return [], []
    recs, bad = [], []
    for n in names:
        try:
            recs.append(read_record(bundle, n))
        except RecordError:
            bad.append(n)
    recs.sort(key=lambda r: (str(r.get("updated", "")), r.get("name", "")), reverse=True)
    return recs, bad


def summary(rec):
    return {k: rec.get(k) for k in ("name", "topic", "status", "created", "updated")}


def cmd_run_new(args):
    bundle = resolve_bundle(args.bundle)
    topic = args.topic.strip()
    if not topic:
        die("a run needs a topic")
    if args.name:
        name = check_name(args.name)
        if not write_record(bundle, new_record(name, topic), create=True):
            die(f"a run named {name} already exists — continue it, or pick another --name")
    else:
        base = f"{datetime.date.today().isoformat()}-{slug(topic)}"
        for i in range(1, 1000):
            name = base if i == 1 else f"{base}-{i}"
            if write_record(bundle, new_record(name, topic), create=True):
                break
        else:
            die(f"too many runs named {base}-*; pass --name")
    if args.json:
        print(json.dumps({"name": name, "path": record_path(bundle, name)}, ensure_ascii=False))
    else:
        print(name)
    return 0


def cmd_run_show(args):
    bundle = resolve_bundle(args.bundle)
    rec = load_or_die(bundle, check_name(args.name))
    if args.json:
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    print(f"run {rec['name']} — {rec['status']}")
    print(f"topic: {rec['topic']}")
    print(f"created {rec.get('created')}, updated {rec.get('updated')}")
    if rec.get("study"):
        print(f"\n## study\n{rec['study']}")
    if rec.get("approaches"):
        print("\n## approaches")
        for i, a in enumerate(rec["approaches"], 1):
            print(f"{i}. {a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)}")
    if rec.get("decisions"):
        print("\n## decisions")
        for d in rec["decisions"]:
            print(f"- {d.get('text') if isinstance(d, dict) else d}")
    if rec.get("brief"):
        print(f"\n## brief\n{rec['brief']}")
    if rec.get("recipe"):
        print(f"\n## recipe\n{json.dumps(rec['recipe'], ensure_ascii=False, indent=2)}")
    if rec.get("dispatch"):
        d = rec["dispatch"]
        print(f"\n## dispatched\nvia {d.get('via')} at {d.get('at')}"
              f"{', ' + d['where'] if d.get('where') else ''}\n{d.get('command')}")
    wait_lines = _wait_lines(rec)
    if wait_lines:
        print("\n## " + ("waiting" if rec["status"] == STATUS_WAITING else "wait"))
        print("\n".join(wait_lines))
    if rec["status"] == STATUS_STARTING:
        c = rec.get("claim") or {}
        print(f"\n## starting\nclaimed via {c.get('via')} at {c.get('at')}"
              f"{', ' + c['where'] if c.get('where') else ''}\n{c.get('command')}\n"
              f"how the start went is not recorded yet (`run dispatch`, with --error if it failed)")
    failed = [a for a in rec.get("attempts", []) if not a.get("ok")]
    if failed and rec["status"] == STATUS_OPEN:
        last = failed[-1]
        print(f"\n## not dispatched\nlast attempt via {last.get('via')} at {last.get('at')} "
              f"failed: {last.get('error')}")
    if rec.get("ingests"):
        print("\n## ingested")
        for i in rec["ingests"]:
            print(f"- {i.get('at')}{', commit ' + i['commit'] if i.get('commit') else ''}")
    steers = {s.get("link"): s for s in rec.get("steers", []) if isinstance(s, dict)}
    if rec.get("learnings"):
        print("\n## learned")
        for item in rec["learnings"]:
            text = item.get("text") if isinstance(item, dict) else item
            steer = steers.get(str(text).split(":", 1)[0].strip())
            print(f"- {text}{' (' + _steer_line(steer) + ')' if steer else ''}")
    if steers:
        print("\n## steered and forgotten")
        for s in rec["steers"]:
            print(f"- {s.get('link')}: {_steer_line(s)}, at {s.get('at')}")
    waiting = [(i, item) for i, item in enumerate(rec.get("pending") or [], 1)
               if isinstance(item, dict) and not item.get("settled")]
    if waiting:
        print("\n## pending learnings (not captured yet)")
        for i, item in waiting:
            print(f"{i}. {item.get('text')}")
    if rec.get("log"):
        print("\n## notes")
        for item in rec["log"]:
            print(f"- {item.get('text') if isinstance(item, dict) else item}")
    return 0


def cmd_run_list(args):
    bundle = resolve_bundle(args.bundle)
    recs, bad = list_records(bundle)
    for n in bad:
        note(f"skipped the unreadable run record {record_path(bundle, n)}")
    if args.open:
        recs = [r for r in recs if r["status"] not in STARTED]
    if args.json:
        # The unreadable ones are listed too, by path, so a resume that picks
        # from this list can say which records it could not offer.
        print(json.dumps({"bundle": bundle, "runs": [summary(r) for r in recs],
                          "unreadable": [record_path(bundle, n) for n in bad]}, ensure_ascii=False))
        return 0
    for r in recs:
        print(f"{r['name']}\t{r['status']}\t{r.get('updated', '')}\t{r['topic']}")
    return 0


def _value(args):
    if (args.value is None) == (args.file is None):
        die("give the value with exactly one of --value or --file")
    if args.value is not None:
        return args.value
    try:
        if args.file == "-":
            return sys.stdin.read()
        with open(args.file, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        die(f"cannot read {args.file} ({exc})")


def cmd_run_set(args):
    bundle = resolve_bundle(args.bundle)
    field, raw = args.field, _value(args)
    rec = load_for_update(bundle, check_name(args.name))
    if rec["status"] in STARTED and field in FROZEN_AFTER_DISPATCH:
        die(f"run {rec['name']} was already dispatched; its {field} stays as dispatched "
            f"(add a decision or a note instead)")
    if rec["status"] == STATUS_STARTING and field in FROZEN_AFTER_DISPATCH:
        die(f"run {rec['name']} is being started; its {field} stays as claimed until "
            f"`run dispatch` records how the start went (add a decision or a note instead)")
    settles = getattr(args, "pending", None)
    if settles is not None and field not in SETTLES_PENDING:
        die(f"--pending settles a pending learning with a learning or a note, not a {field}")
    t = now()
    if settles is not None:
        pending = rec.get("pending") if isinstance(rec.get("pending"), list) else []
        if not 1 <= settles <= len(pending) or not isinstance(pending[settles - 1], dict):
            die(f"run {rec['name']} has no pending learning {settles} "
                f"({len(pending)} recorded; `run show --json` lists them in `pending`)")
        item = pending[settles - 1]
        if item.get("settled"):
            s = item["settled"]
            die(f"pending learning {settles} of run {rec['name']} was already settled "
                f"by a {s.get('by')} at {s.get('at')}")
        item["settled"] = {"at": t, "by": field}
    if field in TEXT_FIELDS:
        rec[field] = raw
    elif field in JSON_FIELDS:
        try:
            value = json.loads(raw)
        except ValueError as exc:
            die(f"{field} must be JSON ({exc})")
        kind = JSON_FIELDS[field]
        if not isinstance(value, kind):
            die(f"{field} must be a JSON {'array' if kind is list else 'object'}")
        if field == "recipe" and "written" in value:
            die("a recipe written for this run is recorded with `trunk.py recipe draft`, "
                "which keeps the draft its check is held against")
        if field == "recipe" and isinstance(value.get("command"), str):
            _refuse_stored_merge(value["command"], "the recipe's command")
        rec[field] = value
    else:
        if not raw.strip():
            die(f"an empty {field} adds nothing")
        if field in ("pending", "learning"):
            _refuse_stored_merge(raw, f"the {field}")
        if field == "decision" and raw.strip().lower().startswith(RETIRED_MERGE_LEVEL):
            die(f"the merge level is retired: {MERGE_IS_THE_FOLLOWS}, from the owner's facts; "
                f"to keep this run from merging, `run hold` it; nothing was recorded")
        if field == "decision":
            hold_decision_or_die(raw)
        entry = {"at": t, "text": raw.strip()}
        if settles is not None:
            entry["settles"] = settles
        rec.setdefault(APPEND_FIELDS[field], []).append(entry)
    rec["updated"] = t
    write_record(bundle, rec)
    return 0


def _refuse_dispatched(rec):
    if rec["status"] in STARTED:
        d = rec.get("dispatch") or {}
        die(f"run {rec['name']} was already dispatched via {d.get('via')} at {d.get('at')}"
            f"{' (' + d['where'] + ')' if d.get('where') else ''}; it is never dispatched again")


def cmd_run_claim(args):
    """Flip an open run to `starting`, under the record's lock, before the
    dispatch command runs: of two sessions claiming the same run, exactly one
    sees it open, so the command is started once. The claim is released by
    `run dispatch`, which records how the start went."""
    bundle = resolve_bundle(args.bundle)
    rec = load_for_update(bundle, check_name(args.name))
    _refuse_dispatched(rec)
    if rec["status"] == STATUS_STARTING:
        c = rec.get("claim") or {}
        die(f"run {rec['name']} is already being started: claimed via {c.get('via')} at "
            f"{c.get('at')} ({c.get('command')}); nothing is started again until `run dispatch` "
            f"records how that start went (with --error when it did not start)")
    if args.via == "orq":
        problem = written_recipe_problem(rec.get("recipe")) \
            or merge_param_problem(args.dispatch_command)
        if problem:
            die(f"nothing is dispatched: {problem}")
    t = now()
    rec["status"] = STATUS_STARTING
    rec["claim"] = {"at": t, "via": args.via, "command": args.dispatch_command,
                    "where": args.where or None}
    rec["updated"] = t
    write_record(bundle, rec)
    if args.json:
        print(json.dumps({**summary(rec), "claim": rec["claim"]}, ensure_ascii=False))
    else:
        print(f"run {rec['name']}: claimed, start it now")
    return 0


def cmd_run_dispatch(args):
    """Record how the start of a claimed run went. Only a `starting` run is
    recorded: a dispatch with no claim before it would let a session that
    skipped the claim race one that made it, both commands running."""
    bundle = resolve_bundle(args.bundle)
    rec = load_for_update(bundle, check_name(args.name))
    _refuse_dispatched(rec)
    if args.via == "orq":
        problem = written_recipe_problem(rec.get("recipe"))
        if problem:
            die(f"nothing is dispatched: {problem}")
    if rec["status"] != STATUS_STARTING:
        die(f"run {rec['name']} was not claimed: `run claim` it with the command about to run, "
            f"run the command only once the claim succeeded, then record here how it went; "
            f"nothing was recorded")
    claimed = (rec.get("claim") or {}).get("command")
    # orq runs the command exactly as claimed, so another one is another
    # session's start, not this claim's: recording it would close a claim
    # whose own start never got recorded. Claude Code words it loosely.
    if claimed and claimed != args.dispatch_command and args.via == "orq":
        die(f"run {rec['name']} was claimed for {claimed!r}, and --command is "
            f"{args.dispatch_command!r}: on orq the command recorded is the one claimed, "
            f"as it ran; nothing was recorded")
    if claimed and claimed != args.dispatch_command:
        note(f"run {rec['name']} was claimed for {claimed!r}, and --command records "
             f"{args.dispatch_command!r}; recording the command given here")
    t = now()
    attempt = {"at": t, "via": args.via, "command": args.dispatch_command, "where": args.where or None,
               "ok": args.error is None, "error": args.error}
    rec.setdefault("attempts", []).append(attempt)
    # Whatever the outcome, the claim is over: a run that started is
    # dispatched, one that did not is open again, for a retry to claim.
    rec["claim"] = None
    if attempt["ok"]:
        rec["status"] = STATUS_DISPATCHED
        rec["dispatch"] = {k: attempt[k] for k in ("at", "via", "command", "where")}
    else:
        rec["status"] = STATUS_OPEN
    rec["updated"] = t
    write_record(bundle, rec)
    if args.json:
        print(json.dumps(summary(rec), ensure_ascii=False))
    else:
        print(f"run {rec['name']}: {'dispatched' if attempt['ok'] else 'not dispatched'}")
    return 0


def _git(bundle, *args):
    """A git command in the bundle: (returncode, stdout), or None when git is
    missing or cannot run. The output is read as UTF-8 with undecodable bytes
    replaced: `diff-tree -p` carries the content of whatever the commit
    added, and a CSV in Latin-1 or cp1252 (common in a bundle) must not stop
    the check. What it looks for (paths, the record's created and name) is
    ASCII, so a replaced byte never hides it."""
    git = shutil.which("git")
    if not git:
        return None
    try:
        r = subprocess.run([git, "-C", bundle, *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        return None
    return r.returncode, r.stdout.strip()


def _blob_ids(data):
    """The ids git would give `data` as a blob, sha1 and sha256 repositories
    alike, as written and with CRLF turned to LF (what autocrlf stores)."""
    ids = set()
    for d in {data, data.replace(b"\r\n", b"\n")}:
        head = b"blob %d\0" % len(d)
        ids.add(hashlib.sha1(head + d).hexdigest())
        ids.add(hashlib.sha256(head + d).hexdigest())
    return ids


def _copied_records(bundle, commit):
    """The paths outside state/trunk/ where `commit` added a byte-for-byte copy
    of a file under it: a run record or a recipe draft that ingest copied
    elsewhere (raw/, say) entered the history all the same."""
    ids = set()
    for d, _, files in os.walk(os.path.join(bundle, "state", "trunk")):
        for f in files:
            try:
                with open(os.path.join(d, f), "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            if data.strip():
                ids |= _blob_ids(data)
    if not ids:
        return []
    tree = _git(bundle, "diff-tree", "-r", "--root", "--no-commit-id", "--no-renames", commit)
    if not tree or tree[0] != 0:
        return []
    found = []
    for line in tree[1].splitlines():
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) >= 5 and fields[4] != "D" and fields[3] in ids:
            found.append(path)
    return found


def _fingerprinted(bundle, commit, rec):
    """The paths outside state/trunk/ whose lines added by `commit` carry the
    record's fingerprint: its `created` key with its timestamp (to the
    microsecond) as JSON writes it, `"created": "<timestamp>"`, and its name,
    both in the same file. A copy that is not byte for byte (a newline
    dropped, the JSON reserialized, the record changed since by `run set`)
    still carries both. The timestamp alone is not enough: a source note's
    `occurred:` may copy it, and the same note names the run in its
    `resource:`, so only the JSON key tells a copy of the record."""
    created, name = rec.get("created"), rec.get("name")
    if not isinstance(created, str) or not created or not isinstance(name, str) or not name:
        return []
    key = re.compile(r'"created"\s*:\s*"' + re.escape(created) + '"')
    diff = _git(bundle, "diff-tree", "-p", "-r", "--root", "--no-commit-id", "--no-renames",
                "--no-ext-diff", "--no-textconv", "--no-color", commit)
    if not diff or diff[0] != 0:
        return []
    added, path = {}, None
    for line in diff[1].splitlines():
        if line.startswith("diff --git "):
            path = None
        elif line.startswith("+++ "):
            target = line[4:]
            if target.startswith('"'):
                try:
                    target = json.loads(target)
                except ValueError:
                    target = target.strip('"')
            path = target[2:] if target.startswith("b/") else None
        elif path and line.startswith("+"):
            added.setdefault(path, []).append(line[1:])
    return [p for p, lines in added.items()
            if not (p + "/").startswith(IGNORE_ENTRY)
            and key.search("\n".join(lines)) and name in "\n".join(lines)]


def cmd_run_ingested(args):
    """Record that `ingest` ran over a dispatched run's record, after checking
    the raw record stayed out of the bundle's history: nothing under
    state/trunk/ is tracked, the ingest commit touched nothing there, it
    added no byte-for-byte copy of a file from there anywhere else, and no
    file it added lines to carries the record's fingerprint (its `created`
    key as JSON writes it, and the name). Only that one commit is read: a
    copy in an earlier or a later commit, or a part of the record (the study
    pasted into a source), is not found."""
    bundle = resolve_bundle(args.bundle)
    rec = load_for_update(bundle, check_name(args.name))
    if rec["status"] not in STARTED:
        die(f"run {rec['name']} was not dispatched; its record is ingested after the dispatch")
    commit = args.commit or None
    inside = _git(bundle, "rev-parse", "--is-inside-work-tree")
    if inside and inside[0] == 0 and inside[1] == "true":
        tracked = _git(bundle, "ls-files", "--", "state/trunk")
        if tracked and tracked[0] == 0 and tracked[1]:
            die(f"{bundle} tracks files under {IGNORE_ENTRY}: the raw record entered the bundle's "
                f"history; untrack it with `git -C {bundle} rm -r --cached state/trunk` and commit")
        ref = commit or "HEAD"
        head = _git(bundle, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if not head or head[0] != 0 or not head[1]:
            die(f"{ref} is not a commit in {bundle}")
        commit = head[1]
        touched = _git(bundle, "show", "--name-only", "--format=", commit, "--", "state/trunk")
        if touched and touched[0] == 0 and touched[1]:
            die(f"commit {commit[:12]} carries files under {IGNORE_ENTRY}: the raw record entered "
                f"the bundle's history; it must be rewritten before anything is pushed or shared")
        copied = _copied_records(bundle, commit)
        copied += [p for p in _fingerprinted(bundle, commit, rec) if p not in copied]
        if copied:
            die(f"commit {commit[:12]} carries a copy of a run record or recipe draft at "
                f"{', '.join(copied)}: the raw record entered the bundle's history; it must be "
                f"rewritten before anything is pushed or shared")
    t = now()
    rec.setdefault("ingests", []).append({"at": t, "commit": commit})
    rec["updated"] = t
    write_record(bundle, rec)
    if args.json:
        print(json.dumps({**summary(rec), "ingests": rec["ingests"]}, ensure_ascii=False))
    else:
        print(f"run {rec['name']}: ingested{' in ' + commit[:12] if commit else ''}")
    return 0


# ── the wait: what a dispatched run waits on next ────────────────────────────
#
# A run whose work ends in a pull request or a branch does not end there: it
# waits, with a structured record the follow reads. Every field is structured
# (a name, a number, a SHA, a kind, a timestamp); `state` holds what the
# sources last saw, so the same state never enqueues twice. `since` is when
# what it waits on, or what was last seen, last changed; `reminded` is when the
# reminder for the current stretch went, and resets with `since`. Ending the
# wait makes the run `dispatched` again, the wait kept with how it ended.
#
# The owner's hold is a decision of its own prefix: `hold: <why>` blocks the
# merge until a later `hold lifted: <why>`, recorded only on the owner's word.

WAIT_ON = ("team", "approval", "hour", "merge", "deploy", "health", "owner")
DEPLOY_KINDS = ("service", "release", "lexflow", "local", "merge", "unknown")
WAIT_OUTCOMES = ("live", "merged", "closed", "given-back")
WAIT_TEXT = ("repo", "branch", "team", "session", "deploy", "health_rule")
HOLD_PREFIX, LIFT_PREFIX = "hold:", "hold lifted:"
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
PR_URL_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/(\d+)(?:[/?#].*)?")
SHA_RE = re.compile(r"[0-9a-f]{7,40}")
# An orq team key, a session or agent name: one token, no whitespace.
WAIT_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")
BRANCH_RE = re.compile(r"[^\s~^:?*\[\\]{1,255}")


def new_wait(t):
    return {"on": None, "repo": None, "branch": None, "team": None, "pr": None,
            "approved_sha": None, "session": None, "deploy": None, "health_rule": None,
            "health_window": None, "hold_until": None, "since": t, "state": {},
            "reminded": None, "ended": None}


def hold_of(rec):
    """The owner's hold on the run: its last `hold:` decision when no `hold
    lifted:` decision came after it, else None."""
    for d in reversed(rec.get("decisions") or []):
        text = ((d.get("text") if isinstance(d, dict) else str(d)) or "").strip()
        if text.lower().startswith(LIFT_PREFIX):
            return None
        if text.lower().startswith(HOLD_PREFIX):
            return d if isinstance(d, dict) else {"at": None, "text": text}
    return None


def hold_decision_or_die(raw):
    """A `hold:` or `hold lifted:` decision says why; one with nothing after
    its prefix is refused."""
    text = raw.strip()
    for prefix in (LIFT_PREFIX, HOLD_PREFIX):
        if text.lower().startswith(prefix):
            if not text[len(prefix):].strip():
                die(f"a {prefix} decision says why after the prefix ({prefix} <why>); "
                    f"nothing was recorded")
            return


def parse_when(value, what):
    """An ISO 8601 time carrying its offset (a trailing Z is UTC), as one
    string; a time without an offset is refused, it would be read in no zone."""
    raw = value.strip()
    try:
        when = datetime.datetime.fromisoformat(raw[:-1] + "+00:00" if raw[-1:] in "Zz" and raw else raw)
    except ValueError:
        die(f"{what} must be an ISO 8601 time with its offset, like 2026-11-10T09:00:00-03:00 ({value!r})")
    if when.tzinfo is None:
        die(f"{what} must carry its offset (-03:00, +00:00 or Z), or it is read in no zone ({value!r})")
    return when.isoformat()


def _wait_changes(args, wait):
    """The fields `run wait set` changes, validated, as a dict. An empty value
    clears a field."""
    out = {}
    if args.on is not None:
        out["on"] = args.on
    for field in WAIT_TEXT:
        value = getattr(args, field)
        if value is None:
            continue
        value = value.strip()
        if value and field == "repo" and not (REPO_RE.fullmatch(value) or os.path.isabs(value)):
            die(f"--repo is owner/name on GitHub, or the absolute path of a repo with no remote ({value!r})")
        if value and field in ("team", "session") and not WAIT_KEY_RE.fullmatch(value):
            die(f"--{field} is one name, without spaces ({value!r})")
        if value and field == "branch" and not BRANCH_RE.fullmatch(value):
            die(f"--branch is not a branch name ({value!r})")
        if value and field == "deploy" and value not in DEPLOY_KINDS:
            die(f"--deploy is one of {', '.join(DEPLOY_KINDS)} ({value!r})")
        if field == "health_rule" and "\n" in value:
            die("--health-rule is one line")
        out[field] = value or None
    if args.pr is not None:
        value = args.pr.strip()
        m = PR_URL_RE.fullmatch(value)
        if m:
            repo = out.get("repo") if "repo" in out else wait.get("repo")
            if repo and repo.lower() != m.group(1).lower():
                die(f"--pr {value} is a pull request of {m.group(1)}, and the wait's repo is {repo}")
            if not repo:
                out["repo"] = m.group(1)
            out["pr"] = int(m.group(2))
        elif value.lstrip("#").isdigit() and int(value.lstrip("#")) > 0:
            out["pr"] = int(value.lstrip("#"))
        elif not value:
            out["pr"] = None
        else:
            die(f"--pr is the pull request's number or its GitHub URL ({value!r})")
    if args.sha is not None:
        value = args.sha.strip().lower()
        if value and not SHA_RE.fullmatch(value):
            die(f"--sha is a commit SHA, 7 to 40 hex digits ({args.sha!r})")
        out["approved_sha"] = value or None
    if args.health_window is not None:
        value = args.health_window.strip()
        if value and not (value.isdigit() and int(value) > 0):
            die(f"--health-window is a whole number of minutes ({args.health_window!r})")
        out["health_window"] = int(value) if value else None
    if args.hold_until is not None:
        out["hold_until"] = parse_when(args.hold_until, "--hold-until") if args.hold_until.strip() else None
    if args.state is not None:
        try:
            state = json.loads(args.state)
        except ValueError as exc:
            die(f"--state must be a JSON object ({exc})")
        if not isinstance(state, dict):
            die("--state must be a JSON object, one key per source")
        merged = dict(wait.get("state") or {})
        for k, v in state.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        out["state"] = merged
    return out


def cmd_run_wait_set(args):
    """Start or update the wait of a dispatched run. A run starts waiting with
    --on; a waiting run takes any field alone. A change to what it waits on,
    or to what the sources last saw, moves `since` and clears `reminded`."""
    bundle = resolve_bundle(args.bundle)
    rec = load_for_update(bundle, check_name(args.name))
    if rec["status"] not in STARTED:
        die(f"run {rec['name']} is {rec['status']}: a run waits once it was dispatched "
            f"(`run dispatch` records the start first); nothing was recorded")
    t = now()
    fresh = rec["status"] != STATUS_WAITING or not isinstance(rec.get("wait"), dict)
    if fresh and not args.on:
        die(f"run {rec['name']} is not waiting yet: say what it waits on with --on "
            f"({', '.join(WAIT_ON)}); nothing was recorded")
    if fresh:
        if isinstance(rec.get("wait"), dict):
            rec.setdefault("past_waits", []).append(rec["wait"])
        wait = new_wait(t)
    else:
        wait = rec["wait"]
    changes = _wait_changes(args, wait)
    moved = not fresh and any(k in changes and changes[k] != wait.get(k) for k in ("on", "state"))
    wait.update(changes)
    if moved:
        wait["since"], wait["reminded"] = t, None
    if args.reminded:
        wait["reminded"] = t
    rec["wait"], rec["status"], rec["updated"] = wait, STATUS_WAITING, t
    write_record(bundle, rec)
    if args.json:
        print(json.dumps({**summary(rec), "wait": wait}, ensure_ascii=False))
    else:
        print(f"run {rec['name']}: waiting on {wait['on']}")
    return 0


def cmd_run_wait_end(args):
    """End a run's wait: the run is `dispatched` again, the wait kept with how
    it ended and why."""
    bundle = resolve_bundle(args.bundle)
    rec = load_for_update(bundle, check_name(args.name))
    if rec["status"] != STATUS_WAITING:
        die(f"run {rec['name']} is not waiting ({rec['status']}); nothing was recorded")
    why = (args.why or "").strip()
    if not why:
        die("say why the wait ends with --why")
    t = now()
    wait = rec["wait"] if isinstance(rec.get("wait"), dict) else new_wait(t)
    wait["ended"] = {"at": t, "outcome": args.outcome, "why": why}
    rec["wait"], rec["status"], rec["updated"] = wait, STATUS_DISPATCHED, t
    write_record(bundle, rec)
    if args.json:
        print(json.dumps({**summary(rec), "wait": wait}, ensure_ascii=False))
    else:
        print(f"run {rec['name']}: the wait ended, {args.outcome}")
    return 0


def wait_view(rec):
    """What a reader of the wait needs: the run, its wait and its hold."""
    return {**summary(rec), "wait": rec.get("wait") if isinstance(rec.get("wait"), dict) else None,
            "hold": hold_of(rec)}


def _wait_lines(rec):
    wait = rec.get("wait") if isinstance(rec.get("wait"), dict) else None
    lines = []
    if wait:
        ended = wait.get("ended") or None
        head = (f"ended {ended.get('at')}: {ended.get('outcome')}, {ended.get('why')}" if ended
                else f"waiting on {wait.get('on')} since {wait.get('since')}")
        lines.append(head)
        where = wait.get("repo") or ""
        if wait.get("pr"):
            where += f"#{wait['pr']}"
        if wait.get("branch"):
            where += f" ({wait['branch']})"
        for label, value in (("where", where.strip()), ("team", wait.get("team")),
                             ("session", wait.get("session")), ("approved", wait.get("approved_sha")),
                             ("deploy", wait.get("deploy")), ("health", wait.get("health_rule")),
                             ("health window", f"{wait['health_window']} min" if wait.get("health_window") is not None
                              else f"{HEALTH_WINDOW_DEFAULT} min (default)" if wait.get("health_rule") else None),
                             ("hold until", wait.get("hold_until")), ("reminded", wait.get("reminded")),
                             ("last seen", json.dumps(wait["state"], ensure_ascii=False, sort_keys=True)
                              if wait.get("state") else None)):
            if value:
                lines.append(f"{label}: {value}")
    hold = hold_of(rec)
    if hold:
        lines.append(f"held since {hold.get('at')}: {hold.get('text')}")
    return lines


def cmd_run_wait_show(args):
    bundle = resolve_bundle(args.bundle)
    rec = load_or_die(bundle, check_name(args.name))
    if args.json:
        print(json.dumps(wait_view(rec), ensure_ascii=False))
        return 0
    lines = _wait_lines(rec)
    print(f"run {rec['name']} — {rec['status']}")
    print("\n".join(lines) if lines else "it has never waited")
    return 0


def waiting_runs(bundle):
    """The waiting runs, most recently updated first, plus the names of the
    records that could not be read."""
    recs, bad = list_records(bundle)
    return [r for r in recs if r["status"] == STATUS_WAITING], bad


def cmd_run_wait_list(args):
    bundle = resolve_bundle(args.bundle)
    recs, bad = waiting_runs(bundle)
    for n in bad:
        note(f"skipped the unreadable run record {record_path(bundle, n)}")
    if args.json:
        print(json.dumps({"bundle": bundle, "runs": [wait_view(r) for r in recs],
                          "unreadable": [record_path(bundle, n) for n in bad]}, ensure_ascii=False))
        return 0
    for r in recs:
        w = r.get("wait") if isinstance(r.get("wait"), dict) else {}
        where = (w.get("repo") or "") + (f"#{w['pr']}" if w.get("pr") else "")
        print(f"{r['name']}\t{w.get('on')}\t{w.get('since', '')}\t{where}"
              f"{chr(9) + 'held' if hold_of(r) else ''}")
    return 0


def cmd_run_hold(args):
    """Record the owner's hold on a run, or lift it. A hold blocks the run's
    merge until the owner lifts it in a session."""
    bundle = resolve_bundle(args.bundle)
    rec = load_for_update(bundle, check_name(args.name))
    why = (args.why or "").strip()
    if not why or "\n" in why:
        die("say why in one line with --why")
    held = hold_of(rec)
    if args.lift and not held:
        die(f"run {rec['name']} has no hold to lift; nothing was recorded")
    if not args.lift and held:
        note(f"run {rec['name']} is already held since {held.get('at')} ({held.get('text')}); "
             f"nothing was recorded")
    else:
        t = now()
        prefix = LIFT_PREFIX if args.lift else HOLD_PREFIX
        rec.setdefault("decisions", []).append({"at": t, "text": f"{prefix} {why}"})
        rec["updated"] = t
        write_record(bundle, rec)
    view = wait_view(rec)
    if args.json:
        print(json.dumps(view, ensure_ascii=False))
    else:
        print(f"run {rec['name']}: {'held' if view['hold'] else 'not held'}")
    return 0


# ── the follow: the sources and the queue ────────────────────────────────────
#
# `follow poll` is one tick of the follow. For each waiting run it runs the
# sources in order (the run's orq team, its pull request, the deploy of the
# merge commit, then time), each reading one kind of thing with no model, and
# compares what it sees with what the run last saw (`wait.state[<source>]`).
# Only a difference enqueues. An event is one JSON file under
# state/trunk/follow/queue/, named by a hash of the run, its wait, the source,
# the event and the wait it moved from, created with O_EXCL: the same state
# never enqueues twice, even when a tick dies between the queue and the
# record, and of two ticks only one creates it. An event carries structured
# fields only (numbers, states, logins, SHAs, kinds, timestamps), each checked
# against its shape before it is kept: a review body, a comment, a log line or
# a message's text is never read into one. From orq's store only the
# messages' metadata is read, never their text.
#
# `act` says what an event asks of the routine. `decide` wakes a session that
# continues the run from it: an approval, a local approval, the hour arriving,
# the open window of a scheduled merge closing, the health window ending, a
# merge whose deploy is a step the trunk runs.
# `notify` is a note the routine sends itself: a change request, failing
# checks, a head that moved, a broken deploy, a merge or a close, a team done
# with no approval, the reminder, the give-back. The poll moves the wait only
# where the next step is a fact (the team approved: wait on the approval; the
# pull request merged: wait on the deploy; closed: the wait ends) and leaves
# every judgment to the woken session.

FOLLOW_SOURCES = ("team", "pr", "deploy", "time")
EVENT_ACTS = ("decide", "notify")
EVENT_PENDING, EVENT_TAKEN, EVENT_DELIVERED, EVENT_DROPPED = "pending", "taken", "delivered", "dropped"
EVENT_OPEN = (EVENT_PENDING, EVENT_TAKEN)
MARKS = ("delivered", "failed", "dropped")
EVENT_VERSION = 1
REMIND_DAYS, GIVE_BACK_DAYS = 3, 7
# The health window, in minutes, when a wait names a health rule and no
# window: the same 30 the trunk's skill gives when no fact names one. A window
# of 0 would fire `health-window-ended` on the tick that saw the deploy.
HEALTH_WINDOW_DEFAULT = 30
# A taken event that no mark followed for this long is taken again: the
# routine that took it died. The routine runs hourly.
TAKE_STALE = 3600.0
# A poll lock this old was left by a tick that died.
POLL_STALE = 1800.0
# orq's own override of where its store is, and its default.
BUS_DB_ENV = "AGENT_BUS_DB"
BUS_DB_DEFAULT = os.path.join("~", ".agent_bus", "agent_bus.sqlite")
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?")
EVENT_ID_RE = re.compile(r"[0-9a-f]{16}")
GH_TIMEOUT = 60
# The pull request is read while the run waits on what comes before its merge.
PR_ON = ("approval", "hour", "merge", "owner")
PR_FIELDS = "state,headRefOid,latestReviews,statusCheckRollup,mergeCommit,mergedBy,mergedAt,autoMergeRequest"
CHECK_FAILED = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
CHECK_PENDING = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}
DEPLOY_FAILED, DEPLOY_DONE = {"failure", "error"}, {"success", "inactive"}
RUN_FAILED = {"failure", "timed_out", "cancelled", "startup_failure", "action_required"}
RUN_DONE = {"success", "skipped", "neutral"}
DEPLOYMENTS_READ = 10


class SourceError(Exception):
    """A source that could not read what it reads: no event, a line in the
    tick's log, and the next tick retries."""


class Step:
    """What one source makes of what it saw: the events, the wait's fields that
    change, the sources' last-seen state that changes, the reminder, and the
    end of the wait as (outcome, why)."""

    def __init__(self):
        self.events, self.changes, self.state = [], {}, {}
        self.reminded, self.end = False, None

    def event(self, etype, act, **fields):
        self.events.append((etype, act, fields))


def follow_dir(bundle):
    return os.path.join(bundle, "state", "trunk", "follow")


def queue_dir(bundle):
    return os.path.join(follow_dir(bundle), "queue")


def event_path(bundle, eid):
    return os.path.join(queue_dir(bundle), eid + ".json")


def _when(value):
    """A timestamp from a record or from GitHub as an aware datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw[-1] in "Zz":
        raw = raw[:-1] + "+00:00"
    try:
        when = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return when if when.tzinfo else None


def _stamp(value):
    """A timestamp kept in an event or a state: ISO 8601 in UTC, or None."""
    when = _when(value)
    return when.astimezone(datetime.timezone.utc).isoformat(timespec="seconds") if when else None


def _sha(value):
    value = value.strip().lower() if isinstance(value, str) else ""
    return value if SHA_RE.fullmatch(value) else None


def _login(value):
    value = value.strip() if isinstance(value, str) else ""
    return value if LOGIN_RE.fullmatch(value) else None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _dig(data, *keys):
    for k in keys:
        data = data.get(k) if isinstance(data, dict) else None
    return data


# ── the sources: what each reads ─────────────────────────────────────────────

def bus_db():
    return os.path.abspath(os.path.expanduser(os.environ.get(BUS_DB_ENV) or BUS_DB_DEFAULT))


def observe_team(team):
    """What the run's orq team shows in orq's store: `approved` (the SHA, the
    round, the pull request, the reviewers requested), `finished` (done or
    closed with no approval), `error` (its last word was an error, and `orq
    resume` can still take it on), `running`; None when no team of that key
    ever started."""
    try:
        import sqlite3
    except ImportError:
        raise SourceError("this Python has no sqlite3 to read orq's store")
    path = bus_db()
    if not os.path.isfile(path):
        raise SourceError(f"no orq store at {path}")
    try:
        uri = "file:" + urllib.request.pathname2url(path) + "?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
            topic = db.execute("SELECT topic_id, status FROM topics WHERE name = ? "
                               "ORDER BY created_at DESC LIMIT 1", (f"orq/{team}",)).fetchone()
            if not topic:
                return None
            rows = db.execute("SELECT metadata_json FROM messages WHERE topic_id = ? ORDER BY seq",
                              (topic[0],)).fetchall()
    except sqlite3.Error as exc:
        raise SourceError(f"orq's store at {path} cannot be read ({exc})")
    kinds, approved = [], None
    for (raw,) in rows:
        try:
            meta = json.loads(raw) if raw else {}
        except ValueError:
            continue
        kind = meta.get("kind") if isinstance(meta, dict) else None
        if isinstance(kind, str):
            kinds.append(kind)
            if kind == "approved" and _sha(meta.get("sha")):
                approved = meta
    if approved is not None:
        out = {"status": "approved", "sha": _sha(approved.get("sha")), "round": _count(approved.get("round")),
               "pr": None, "repo": None,
               "reviewers": sorted({x for x in (_login(p) for p in str(approved.get("reviewers") or "").split(","))
                                    if x})}
        m = PR_URL_RE.fullmatch(str(approved.get("pr") or "").strip())
        if m:
            out["repo"], out["pr"] = m.group(1), int(m.group(2))
        return out
    if "done" in kinds or topic[1] == "closed":
        return {"status": "finished"}
    if kinds and kinds[-1] == "error":
        return {"status": "error"}
    return {"status": "running"}


def gh_json(gh, what, *args):
    """`gh <args>` as JSON. A failure is a SourceError naming `what` and the
    first line gh printed; the tick's log keeps it, no event does."""
    try:
        r = subprocess.run([gh, *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=GH_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError(f"gh could not read {what} ({type(exc).__name__})")
    if r.returncode != 0:
        first = (r.stderr or r.stdout or "").strip().splitlines()
        raise SourceError(f"gh could not read {what} (exit {r.returncode}"
                          f"{': ' + first[0][:160] if first else ''})")
    try:
        return json.loads(r.stdout or "null")
    except ValueError:
        raise SourceError(f"gh printed no JSON for {what}")


def _checks(rollup):
    """The head's checks, from the status check rollup: fail, pending, pass, none."""
    seen = set()
    for c in rollup if isinstance(rollup, list) else []:
        if not isinstance(c, dict):
            continue
        status = str(c.get("status") or "").upper()
        conclusion = str(c.get("conclusion") or "").upper()
        state = str(c.get("state") or "").upper()
        if conclusion in CHECK_FAILED or state in CHECK_FAILED:
            seen.add("fail")
        elif (status and status != "COMPLETED") or state in CHECK_PENDING:
            seen.add("pending")
        else:
            seen.add("pass")
    for verdict in ("fail", "pending", "pass"):
        if verdict in seen:
            return verdict
    return "none"


def observe_pr(gh, repo, pr):
    """The pull request as the follow reads it: its state, head, the approvals
    (login and the commit each approved), who requests changes, the head's
    checks, whether an auto-merge is scheduled, the merge commit and who merged
    or closed it."""
    what = f"pull request {repo}#{pr}"
    data = gh_json(gh, what, "pr", "view", str(pr), "--repo", repo, "--json", PR_FIELDS)
    state = data.get("state") if isinstance(data, dict) else None
    if state not in ("OPEN", "MERGED", "CLOSED"):
        raise SourceError(f"gh gave {what} no state it knows")
    approvals, changes = {}, set()
    for review in data.get("latestReviews") or []:
        login = _login(_dig(review, "author", "login"))
        if not login:
            continue
        if _dig(review, "state") == "APPROVED":
            approvals[login] = _sha(_dig(review, "commit", "oid"))
        elif _dig(review, "state") == "CHANGES_REQUESTED":
            changes.add(login)
    out = {"state": state, "head": _sha(data.get("headRefOid")), "approvals": approvals,
           "changes": sorted(changes), "checks": _checks(data.get("statusCheckRollup")),
           "auto_merge": bool(data.get("autoMergeRequest")), "merge": None, "merged_at": None, "by": None}
    if state == "MERGED":
        out["merge"] = _sha(_dig(data, "mergeCommit", "oid"))
        out["merged_at"] = _stamp(data.get("mergedAt"))
        out["by"] = _login(_dig(data, "mergedBy", "login"))
    elif state == "CLOSED":
        out["by"] = _login(_dig(gh_json(gh, f"who closed {what}", "api", f"repos/{repo}/issues/{pr}"),
                                "closed_by", "login"))
    return out


def observe_deploy(gh, repo, sha):
    """The deploy GitHub records for the merge commit: its deployments when it
    has any (each one's latest status), else the workflow runs the push of
    that commit started. `state` is success, failure, pending, or none when
    GitHub records nothing for it yet."""
    what = f"the deploy of {repo}@{sha[:12]}"
    deps = gh_json(gh, what, "api", "-X", "GET", f"repos/{repo}/deployments", "-f", f"sha={sha}")
    deps = [d for d in deps if _count(_dig(d, "id"))] if isinstance(deps, list) else []
    states, stamps = [], []
    if deps:
        signal = "deployment"
        for d in deps[:DEPLOYMENTS_READ]:
            statuses = gh_json(gh, what, "api", f"repos/{repo}/deployments/{d['id']}/statuses")
            last = statuses[0] if isinstance(statuses, list) and statuses and isinstance(statuses[0], dict) else {}
            states.append(str(last.get("state") or "pending").lower())
            stamps.append(_stamp(last.get("created_at")))
        state = ("failure" if any(s in DEPLOY_FAILED for s in states)
                 else "success" if all(s in DEPLOY_DONE for s in states) else "pending")
    else:
        runs = gh_json(gh, what, "api", "-X", "GET", f"repos/{repo}/actions/runs",
                       "-f", f"head_sha={sha}", "-f", "event=push")
        runs = [r for r in (_dig(runs, "workflow_runs") or []) if isinstance(r, dict)]
        if not runs:
            return {"sha": sha, "signal": "none", "state": "none", "finished_at": None}
        signal = "workflow"
        for r in runs:
            conclusion = str(r.get("conclusion") or "").lower()
            states.append("pending" if r.get("status") != "completed" else
                          "failure" if conclusion in RUN_FAILED else
                          "success" if conclusion in RUN_DONE else "pending")
            stamps.append(_stamp(r.get("updated_at")))
        state = ("failure" if "failure" in states
                 else "success" if all(s == "success" for s in states) else "pending")
    finished = max((s for s in stamps if s), default=None) if state == "success" else None
    return {"sha": sha, "signal": signal, "state": state, "finished_at": finished}


# ── the steps: what each source makes of a change ───────────────────────────

def _health(wait):
    return bool(wait.get("health_window") or wait.get("health_rule"))


def step_team(wait, obs):
    seen = (wait.get("state") or {}).get("team") or {}
    if wait.get("on") != "team" or obs == seen:
        return None
    team, step = wait.get("team"), Step()
    step.state["team"] = obs
    if obs["status"] == "approved":
        repo = wait.get("repo") or ""
        on_github = bool(REPO_RE.fullmatch(repo))
        if obs["pr"]:
            if on_github and repo.lower() != obs["repo"].lower():
                raise SourceError(f"team {team} opened {obs['repo']}#{obs['pr']}, and the wait's repo is {repo}")
            step.changes.update(pr=obs["pr"], approved_sha=obs["sha"], on="approval",
                                repo=repo if on_github else obs["repo"])
            # With a pull request, what comes next is its approval: a note.
            step.event("team-approved", "notify", team=team, sha=obs["sha"],
                       round=obs["round"], pr=obs["pr"], reviewers=obs["reviewers"])
        elif os.path.isabs(repo):
            # No pull request in a repo with no remote: the local merge is
            # decided now.
            step.changes.update(approved_sha=obs["sha"], on="merge")
            step.event("team-approved", "decide", team=team, sha=obs["sha"],
                       round=obs["round"], pr=obs["pr"], reviewers=obs["reviewers"])
        else:
            # No pull request anywhere else means the team could not open one
            # (the push or `gh pr create` failed, or the brief was no spec):
            # nothing merges locally on a repo that lives on GitHub, and no
            # source can see the work move on. The owner takes it.
            step.changes.update(approved_sha=obs["sha"], on="owner")
            step.event("team-approved-no-pr", "notify", team=team, sha=obs["sha"],
                       round=obs["round"])
    elif obs["status"] == "finished":
        step.event("team-finished", "notify", team=team)
        step.changes["on"] = "owner"
    elif obs["status"] == "error":
        step.event("team-error", "notify", team=team)
    return step


def _merged(wait, obs, step):
    """The pull request merged, by the trunk or by anyone: the run moves on to
    the deploy as its repo defines it."""
    pr, kind = wait.get("pr"), wait.get("deploy")
    act = "notify"
    if kind == "unknown":
        step.end = ("merged", f"pull request #{pr} merged; what deploying means in this repo is the owner's")
    elif kind in ("merge", "local"):
        if _health(wait):
            step.changes["on"] = "health"
            step.state["deploy"] = {"sha": obs["merge"], "signal": "merge", "state": "success",
                                    "finished_at": obs["merged_at"]}
        else:
            step.end = ("live", f"pull request #{pr} merged, and the merge is the deploy")
    elif kind == "service":
        step.changes["on"] = "deploy"
    else:
        # A release or a `lexflow deploy` is a step the trunk runs; with no
        # deploy recorded, the session discerns it now.
        step.changes["on"], act = "deploy", "decide"
    step.event("pr-merged", act, pr=pr, merge_sha=obs["merge"], by=obs["by"], deploy=kind)


def step_pr(wait, obs):
    seen = (wait.get("state") or {}).get("pr") or {}
    if wait.get("on") not in PR_ON or obs == seen:
        return None
    pr, step = wait.get("pr"), Step()
    step.state["pr"] = obs
    if obs["state"] == "MERGED":
        if seen.get("state") != "MERGED":
            _merged(wait, obs, step)
        return step
    if obs["state"] == "CLOSED":
        if seen.get("state") != "CLOSED":
            step.event("pr-closed", "notify", pr=pr, by=obs["by"])
            step.end = ("closed", f"pull request #{pr} closed with no merge"
                                  + (f" by {obs['by']}" if obs["by"] else ""))
        return step
    head, before = obs["head"], seen.get("approvals") or {}
    for login, commit in sorted(obs["approvals"].items()):
        if login not in before or before[login] != commit:
            step.event("pr-approved", "decide", pr=pr, reviewer=login, head=head, reviewed=commit)
    for login in obs["changes"]:
        if login not in (seen.get("changes") or []):
            step.event("pr-changes-requested", "notify", pr=pr, reviewer=login, head=head)
            step.changes["on"] = "owner"
    if obs["checks"] == "fail" and (seen.get("checks") != "fail" or seen.get("head") != head):
        step.event("pr-checks-failed", "notify", pr=pr, head=head)
        step.changes["on"] = "owner"
    approved = wait.get("approved_sha")
    if approved and head and not head.startswith(approved) and seen.get("head") != head:
        step.event("pr-head-moved", "notify", pr=pr, head=head, approved_sha=approved)
    return step


def step_deploy(wait, obs):
    seen = (wait.get("state") or {}).get("deploy") or {}
    if wait.get("on") != "deploy" or obs == seen:
        return None
    step = Step()
    step.state["deploy"] = obs
    if obs["state"] == "success" and seen.get("state") != "success":
        step.event("deploy-succeeded", "notify", sha=obs["sha"], signal=obs["signal"],
                   finished_at=obs["finished_at"])
        if _health(wait):
            step.changes["on"] = "health"
        else:
            step.end = ("live", "the deploy finished well, and the repo has no service to check")
    elif obs["state"] == "failure" and seen.get("state") != "failure":
        step.event("deploy-failed", "notify", sha=obs["sha"], signal=obs["signal"])
        step.changes["on"] = "owner"
    return step


def step_time(wait, t):
    """The hour a held run waits for arriving, the open window of a scheduled
    merge closing, and the health window ending."""
    seen = (wait.get("state") or {}).get("time") or {}
    new, step = dict(seen), Step()
    until = wait.get("hold_until")
    # The hour holds a merge: once the run is past it, a hold-until left
    # behind wakes no one.
    if wait.get("on") in PR_ON and until and _when(until) and t >= _when(until) and seen.get("hour") != until:
        step.event("hour-open", "decide", hold_until=until)
        new["hour"] = until
    # A critical change's merge was scheduled inside the business hours and
    # recorded when they close (`state.closes`); still waiting on the merge
    # once they closed, the session cancels the auto-merge and holds.
    closes = _stamp((wait.get("state") or {}).get("closes"))
    if wait.get("on") == "merge" and closes and t >= _when(closes) and seen.get("closed") != closes:
        step.event("hour-closed", "decide", closes=closes)
        new["closed"] = closes
    if wait.get("on") == "health":
        # The window counts from the deploy's end when a source saw it, else
        # from when the run started waiting on health, kept so it never slides.
        start = _dig(wait, "state", "deploy", "finished_at") or seen.get("health_from") or wait.get("since")
        new["health_from"] = start
        window = wait.get("health_window")
        if window is None:
            window = HEALTH_WINDOW_DEFAULT
        began = _when(start)
        if began and t >= began + datetime.timedelta(minutes=window) and seen.get("health") != start:
            step.event("health-window-ended", "decide", deployed_at=_stamp(start), window=window)
            new["health"] = start
    if new != seen:
        step.state["time"] = new
    return step if step.events or step.state else None


def step_stale(wait, t):
    """A wait with no change for 3 days gets one reminder; at 7 it ends, and
    the work is the owner's."""
    since = _when(wait.get("since"))
    if not since:
        return None
    age, step = t - since, Step()
    if age >= datetime.timedelta(days=GIVE_BACK_DAYS):
        step.event("given-back", "notify", on=wait.get("on"), since=_stamp(wait.get("since")),
                   days=GIVE_BACK_DAYS)
        step.end = ("given-back", f"no change for {GIVE_BACK_DAYS} days; the work is the owner's")
    elif age >= datetime.timedelta(days=REMIND_DAYS) and not wait.get("reminded"):
        step.event("reminder", "notify", on=wait.get("on"), since=_stamp(wait.get("since")), days=REMIND_DAYS)
        step.reminded = True
    else:
        return None
    return step


# ── the queue ────────────────────────────────────────────────────────────────

def _event_id(run, wait_n, source, etype, fields, wait):
    """The same event from the same wait is the same file: what makes a tick
    that died between the queue and the record enqueue nothing twice."""
    key = json.dumps([run, wait_n, source, etype, fields, wait.get("state") or {}, wait.get("since"),
                      wait.get("on")], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def read_event(bundle, eid):
    path = event_path(bundle, eid)
    try:
        with open(path, encoding="utf-8") as fh:
            ev = json.load(fh)
    except FileNotFoundError:
        raise RecordError(f"no event {eid} in the queue ({path})")
    except (OSError, ValueError) as exc:
        raise RecordError(f"the event {path} is unreadable ({exc})")
    if not isinstance(ev, dict) or ev.get("id") != eid or ev.get("status") not in \
            (EVENT_PENDING, EVENT_TAKEN, EVENT_DELIVERED, EVENT_DROPPED):
        raise RecordError(f"the event {path} is not an event")
    return ev


def _write_event(bundle, ev):
    d = queue_dir(bundle)
    fd, tmp = tempfile.mkstemp(prefix=".event-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(ev, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, event_path(bundle, ev["id"]))
    except BaseException:
        _release(tmp)
        raise


def enqueue(bundle, ev):
    """Create the event's file; False when it is already queued. A file a dead
    tick left empty is written again."""
    os.makedirs(queue_dir(bundle), mode=0o700, exist_ok=True)
    try:
        os.close(os.open(event_path(bundle, ev["id"]), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        try:
            read_event(bundle, ev["id"])
            return False
        except RecordError:
            pass
    _write_event(bundle, ev)
    return True


def list_events(bundle):
    """Every readable event, oldest first, plus the files that could not be read."""
    try:
        ids = sorted(f[:-5] for f in os.listdir(queue_dir(bundle))
                     if f.endswith(".json") and EVENT_ID_RE.fullmatch(f[:-5]))
    except FileNotFoundError:
        return [], []
    events, bad = [], []
    for eid in ids:
        try:
            events.append(read_event(bundle, eid))
        except RecordError:
            bad.append(event_path(bundle, eid))
    events.sort(key=lambda e: (str(e.get("at", "")), e["id"]))
    return events, bad


def _is_open(ev, t=None):
    """Pending, or taken by a routine that never marked it."""
    if ev["status"] == EVENT_PENDING:
        return True
    if ev["status"] != EVENT_TAKEN:
        return False
    taken = _when(ev.get("taken"))
    t = t or datetime.datetime.now(datetime.timezone.utc)
    return not taken or (t - taken).total_seconds() >= TAKE_STALE


def _drop(bundle, ev, why, t_iso):
    ev["status"], ev["done"] = EVENT_DROPPED, {"at": t_iso, "as": "dropped", "why": why}
    _write_event(bundle, ev)


# ── the tick ─────────────────────────────────────────────────────────────────

def _apply(bundle, name, wait_n, source, step_of, t, new, log, dry=None):
    """Under the run's lock, read the record fresh and let `step_of(wait)` say
    what changed; enqueue its events, then write the wait. Returns the record
    as written (or as read, when nothing changed), or None when the run is no
    longer this wait. A dry run hands in the record as the sources before it
    left it, in memory, and nothing is locked, enqueued or written."""
    if dry is not None:
        return _step(bundle, json.loads(json.dumps(dry)), name, wait_n, source, step_of, t, new, log, False)
    with held(lock_path(bundle, name)) as ok:
        if not ok:
            log(f"{name}: its record is being changed by another trunk.py; the next tick retries")
            return None
        try:
            rec = read_record(bundle, name)
        except RecordError as exc:
            log(f"{name}: {exc}")
            return None
        return _step(bundle, rec, name, wait_n, source, step_of, t, new, log, True)


def _step(bundle, rec, name, wait_n, source, step_of, t, new, log, write):
    t_iso = t.isoformat()
    wait = rec.get("wait")
    if rec["status"] != STATUS_WAITING or not isinstance(wait, dict) \
            or len(rec.get("past_waits") or []) != wait_n:
        return None
    try:
        step = step_of(wait)
    except SourceError as exc:
        log(f"{name}: {source}: {exc}")
        return rec
    if not step:
        return rec
    for etype, act, fields in step.events:
        ev = {"version": EVENT_VERSION, "id": _event_id(name, wait_n, source, etype, fields, wait),
              "run": name, "source": source, "type": etype, "act": act, "at": t_iso, "fields": fields,
              "status": EVENT_PENDING, "taken": None, "attempts": [], "done": None}
        if write and enqueue(bundle, ev):
            new.append(ev)
        elif not write and not os.path.isfile(event_path(bundle, ev["id"])):
            new.append(ev)
    state = dict(wait.get("state") or {})
    state.update(step.state)
    moved = state != (wait.get("state") or {}) or step.changes.get("on", wait.get("on")) != wait.get("on")
    wait.update(step.changes)
    wait["state"] = state
    if moved:
        wait["since"], wait["reminded"] = t_iso, None
    if step.reminded:
        wait["reminded"] = t_iso
    if step.end:
        outcome, why = step.end
        wait["ended"] = {"at": t_iso, "outcome": outcome, "why": why}
        rec["status"] = STATUS_DISPATCHED
    rec["wait"], rec["updated"] = wait, t_iso
    if write:
        write_record(bundle, rec)
    return rec


def follow_run(bundle, rec, t, gh, new, log, dry=False):
    """One waiting run through the sources, in order; each sees the wait as
    the one before it left it."""
    name, wait_n = rec["name"], len(rec.get("past_waits") or [])

    def go(source, step_of):
        nonlocal rec
        got = _apply(bundle, name, wait_n, source, step_of, t, new, log, rec if dry else None)
        if got is not None:
            rec = got
        return got is not None and rec["status"] == STATUS_WAITING

    def read(what, observe, *args):
        try:
            return observe(*args)
        except SourceError as exc:
            log(f"{name}: {what}: {exc}")
            return None

    wait = rec["wait"]
    if wait.get("on") == "team":
        if not wait.get("team"):
            log(f"{name}: it waits on its team and names none (`run wait set {name} --team <key>`)")
        else:
            try:
                obs = observe_team(wait["team"])
            except SourceError as exc:
                log(f"{name}: team: {exc}")
                obs = False
            if obs is None:
                log(f"{name}: team: no orq team {wait['team']} in orq's store yet")
            elif obs and not go("team", lambda w: step_team(w, obs)):
                return
    wait = rec["wait"]
    github = bool(REPO_RE.fullmatch(wait.get("repo") or ""))
    if wait.get("on") in PR_ON and wait.get("pr") and github:
        obs = read("pr", observe_pr, gh, wait["repo"], wait["pr"]) if gh else None
        if not gh:
            log(f"{name}: pr: gh is not on PATH, so no pull request is read")
        if obs is not None and not go("pr", lambda w: step_pr(w, obs)):
            return
    wait = rec["wait"]
    merge = _dig(wait, "state", "pr", "merge")
    if wait.get("on") == "deploy" and wait.get("deploy") == "service" and merge and github:
        obs = read("deploy", observe_deploy, gh, wait["repo"], merge) if gh else None
        if not gh:
            log(f"{name}: deploy: gh is not on PATH, so no deploy is read")
        if obs is not None and not go("deploy", lambda w: step_deploy(w, obs)):
            return
    if go("time", lambda w: step_time(w, t)):
        go("time", lambda w: step_stale(w, t))


def _poll_lock(bundle):
    """The tick's own lock: two ticks never run the sources at once. One left
    by a tick that died is taken over once it is old."""
    path = os.path.join(follow_dir(bundle), ".poll.lock")
    os.makedirs(follow_dir(bundle), mode=0o700, exist_ok=True)
    if _acquire(path, 0):
        return path
    try:
        if time.time() - os.path.getmtime(path) >= POLL_STALE:
            _release(path)
            if _acquire(path, 0):
                return path
    except OSError:
        pass
    return None


SLACK_NOT_SENT, SLACK_RELAYED = "slack not sent (", "slack relayed: "


def _note_id(entry):
    return hashlib.sha256(f"{entry.get('at')}\n{entry.get('text')}".encode("utf-8")).hexdigest()[:12]


def unsent_notes(recs):
    """The `slack not sent (<why>): <note>` notes a session left in its run,
    with no `slack relayed: <id>` note of the routine after them, oldest
    first: what the routine still owes the owner's Slack."""
    out = []
    for rec in recs:
        log = [e for e in rec.get("log") or [] if isinstance(e, dict) and isinstance(e.get("text"), str)]
        relayed = {e["text"][len(SLACK_RELAYED):].strip() for e in log if e["text"].startswith(SLACK_RELAYED)}
        for e in log:
            text = e["text"]
            if not text.startswith(SLACK_NOT_SENT) or "): " not in text:
                continue
            nid = _note_id(e)
            if nid in relayed:
                continue
            why, _, body = text[len(SLACK_NOT_SENT):].partition("): ")
            out.append({"run": rec["name"], "id": nid, "at": e.get("at"), "why": why.strip(), "note": body.strip()})
    out.sort(key=lambda n: (str(n["at"]), n["run"]))
    return out


def cmd_follow_poll(args):
    bundle = resolve_bundle(args.bundle)
    dry = bool(args.dry_run)
    t = (datetime.datetime.fromisoformat(parse_when(args.now, "--now")) if args.now
         else datetime.datetime.now(datetime.timezone.utc))
    t_iso = t.isoformat()
    lines, new = [], []

    def log(line):
        if line not in lines:
            lines.append(line)

    recs, bad = waiting_runs(bundle)
    for n in bad:
        log(f"skipped the unreadable run record {record_path(bundle, n)}")
    events, unreadable = list_events(bundle)
    opened = [e for e in events if e["status"] in EVENT_OPEN]
    busy = False
    if dry and (recs or opened):
        for ev in opened:
            if not os.path.isfile(record_path(bundle, ev["run"])):
                log(f"would drop event {ev['id']} ({ev['type']}): run {ev['run']} no longer exists")
        gh = shutil.which("gh")
        for rec in sorted(recs, key=lambda r: r["name"]):
            follow_run(bundle, rec, t, gh, new, log, dry=True)
    elif recs or opened:
        ensure_ignored(bundle)
        lock = _poll_lock(bundle)
        if lock is None:
            busy = True
            log("another poll is running; this tick reads nothing")
        else:
            try:
                for ev in opened:
                    if not os.path.isfile(record_path(bundle, ev["run"])):
                        with held(os.path.join(queue_dir(bundle), f".{ev['id']}.lock")) as ok:
                            if ok:
                                _drop(bundle, ev, "the run no longer exists", t_iso)
                                log(f"dropped event {ev['id']} ({ev['type']}): run {ev['run']} no longer exists")
                gh = shutil.which("gh")
                for rec in sorted(recs, key=lambda r: r["name"]):
                    follow_run(bundle, rec, t, gh, new, log)
            finally:
                _release(lock)
    for path in unreadable:
        log(f"skipped the unreadable event {path}")
    if lines and not dry:
        os.makedirs(follow_dir(bundle), mode=0o700, exist_ok=True)
        with open(os.path.join(follow_dir(bundle), "poll.log"), "a", encoding="utf-8") as fh:
            fh.writelines(f"{t_iso} {ln}\n" for ln in lines)
    pending = [e for e in list_events(bundle)[0] if _is_open(e, t)]
    unsent = unsent_notes(list_records(bundle)[0])
    if args.json:
        print(json.dumps({"bundle": bundle, "at": t_iso, "dry_run": dry, "waiting": len(recs), "busy": busy,
                          "new": new, "pending": pending, "unsent": unsent, "log": lines}, ensure_ascii=False))
        return 0
    for ln in lines:
        note(ln)
    print(f"follow{' (dry run, nothing written)' if dry else ''}: {len(recs)} waiting, "
          f"{len(new)} {'would be new' if dry else 'new'}, {len(pending)} pending, {len(unsent)} Slack notes unsent")
    for e in new:
        print(f"{e['id']}\t{e['run']}\t{e['type']}\t{e['act']}")
    return 0


def cmd_follow_queue(args):
    bundle = resolve_bundle(args.bundle)
    events, bad = list_events(bundle)
    if not args.all:
        events = [e for e in events if _is_open(e)]
    for path in bad:
        note(f"skipped the unreadable event {path}")
    if args.json:
        print(json.dumps({"bundle": bundle, "events": events, "unreadable": bad}, ensure_ascii=False))
        return 0
    for e in events:
        print(f"{e['id']}\t{e['run']}\t{e['type']}\t{e['act']}\t{e['status']}")
    return 0


def _event_for_update(bundle, eid):
    """The event, read under its own lock, held until this process exits."""
    if not EVENT_ID_RE.fullmatch(eid or ""):
        die(f'"{eid}" is not an event id (16 hex digits, as `follow queue` names it)')
    if os.path.isdir(queue_dir(bundle)):
        path = os.path.join(queue_dir(bundle), f".{eid}.lock")
        if not _acquire(path, LOCK_WAIT):
            die(f"event {eid} is being changed by another trunk.py (lock {path}); try again")
        atexit.register(_release, path)
    try:
        return read_event(bundle, eid)
    except RecordError as exc:
        die(str(exc))


def cmd_follow_take(args):
    """Take a pending event for delivery: of two routines taking it, one does."""
    bundle = resolve_bundle(args.bundle)
    ev = _event_for_update(bundle, args.id)
    t_iso = now()
    if not _is_open(ev):
        die(f"event {ev['id']} is {ev['status']}: another routine has it, or it was delivered; "
            f"nothing was taken")
    if not os.path.isfile(record_path(bundle, ev["run"])):
        _drop(bundle, ev, "the run no longer exists", t_iso)
        die(f"event {ev['id']}: run {ev['run']} no longer exists; the event is dropped")
    ev["status"], ev["taken"] = EVENT_TAKEN, t_iso
    _write_event(bundle, ev)
    print(json.dumps(ev, ensure_ascii=False) if args.json else f"event {ev['id']}: taken")
    return 0


def cmd_follow_mark(args):
    """How a delivery went: delivered and dropped close the event; failed
    keeps it queued, with the attempt, for the next tick."""
    bundle = resolve_bundle(args.bundle)
    ev = _event_for_update(bundle, args.id)
    why = (args.why or "").strip()
    if "\n" in why:
        die("--why is one line")
    if ev["status"] not in EVENT_OPEN:
        die(f"event {ev['id']} is already {ev['status']}; nothing was recorded")
    t_iso = now()
    if args.mark == "failed":
        if not why:
            die("say why the delivery failed with --why")
        ev["attempts"].append({"at": t_iso, "why": why})
        ev["status"], ev["taken"] = EVENT_PENDING, None
    else:
        ev["status"] = EVENT_DELIVERED if args.mark == "delivered" else EVENT_DROPPED
        ev["done"] = {"at": t_iso, "as": args.mark, "why": why or None}
    _write_event(bundle, ev)
    print(json.dumps(ev, ensure_ascii=False) if args.json else f"event {ev['id']}: {ev['status']}")
    return 0


WAKE_KEYS = ("version", "id", "run", "source", "type", "act", "at", "fields")
WAKE_SKILL = "/elephant-trunk:trunk"


def wake_line(ev):
    """The one line that wakes a session for an event: the trunk's skill, the
    run and the event's structured part (never its delivery attempts, whose
    reasons the routine wrote), as one line of JSON."""
    part = {k: ev.get(k) for k in WAKE_KEYS}
    return f"{WAKE_SKILL} continue {ev['run']} from event {json.dumps(part, ensure_ascii=True, separators=(',', ':'))}"


def cmd_follow_wake(args):
    bundle = resolve_bundle(args.bundle)
    if not EVENT_ID_RE.fullmatch(args.id or ""):
        die(f'"{args.id}" is not an event id (16 hex digits, as `follow queue` names it)')
    try:
        ev = read_event(bundle, args.id)
    except RecordError as exc:
        die(str(exc))
    print(wake_line(ev))
    return 0


ORIGIN_RE = re.compile(r"(?:^|[@/:])github\.com[:/]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$", re.I)


def team_folder(team):
    """The folder an orq team was started in, from the `repo` of its topic's
    first `start` message in orq's store (metadata only): orq records the
    main checkout there, and keeps it after the team closed. None when the
    store has no such team or no folder for it."""
    try:
        import sqlite3
    except ImportError:
        raise SourceError("this Python has no sqlite3 to read orq's store")
    path = bus_db()
    if not os.path.isfile(path):
        raise SourceError(f"no orq store at {path}")
    try:
        uri = "file:" + urllib.request.pathname2url(path) + "?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
            topic = db.execute("SELECT topic_id FROM topics WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                               (f"orq/{team}",)).fetchone()
            rows = db.execute("SELECT metadata_json FROM messages WHERE topic_id = ? ORDER BY seq",
                              (topic[0],)).fetchall() if topic else []
    except sqlite3.Error as exc:
        raise SourceError(f"orq's store at {path} cannot be read ({exc})")
    for (raw,) in rows:
        try:
            meta = json.loads(raw) if raw else {}
        except ValueError:
            continue
        if isinstance(meta, dict) and meta.get("kind") == "start":
            folder = meta.get("repo")
            return folder if isinstance(folder, str) and os.path.isabs(folder) else None
    return None


def _git_out(folder, *args):
    try:
        r = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def main_checkout(folder):
    """The main checkout of the repository `folder` is in: the first worktree
    git lists (a team's worktree holds the team's branch, and may be gone)."""
    out = _git_out(folder, "worktree", "list", "--porcelain")
    first = next((ln[len("worktree "):] for ln in (out or "").splitlines() if ln.startswith("worktree ")), None)
    return os.path.normpath(first) if first and os.path.isdir(first) else None


def checkout_of(wait):
    """Where a new session for the run opens: (path, how it was found), or
    (None, why not)."""
    repo = wait.get("repo") or ""
    if os.path.isabs(repo):
        return (repo, "the wait's repo") if os.path.isdir(repo) else (None, f"{repo} is not a folder")
    if not wait.get("team"):
        return None, "the wait names no orq team to find its folder by"
    try:
        folder = team_folder(wait["team"])
    except SourceError as exc:
        return None, str(exc)
    if not folder or not os.path.isdir(folder):
        return None, f"orq's store records no folder for team {wait['team']}" + (f" ({folder} is gone)" if folder else "")
    path = main_checkout(folder)
    if not path:
        return None, f"{folder} is not a git checkout"
    origin = (_git_out(path, "remote", "get-url", "origin") or "").strip()
    m = ORIGIN_RE.search(origin)
    if REPO_RE.fullmatch(repo) and not (m and m.group(1).lower() == repo.lower()):
        return None, f"the origin of {path} is not {repo}"
    return path, f"the folder of team {wait['team']}"


def cmd_follow_checkout(args):
    bundle = resolve_bundle(args.bundle)
    rec = load_or_die(bundle, check_name(args.run))
    wait = rec.get("wait") if isinstance(rec.get("wait"), dict) else {}
    path, how = checkout_of(wait)
    if args.json:
        print(json.dumps({"run": rec["name"], "checkout": path, "from": how if path else None,
                          "problem": None if path else how}, ensure_ascii=False))
        return 0 if path else 1
    if not path:
        die(f"run {rec['name']}: no checkout found: {how}")
    print(path)
    return 0


def cmd_follow_unsent(args):
    bundle = resolve_bundle(args.bundle)
    recs, bad = list_records(bundle)
    for n in bad:
        note(f"skipped the unreadable run record {record_path(bundle, n)}")
    notes = unsent_notes(recs)
    if args.json:
        print(json.dumps({"bundle": bundle, "unsent": notes}, ensure_ascii=False))
        return 0
    for n in notes:
        print(f"{n['run']}\t{n['id']}\t{n['at']}\t{n['why']}\t{n['note']}")
    return 0


def cmd_follow_relayed(args):
    """The routine sent a note a session could not: the run says so, and the
    note leaves `follow unsent`."""
    bundle = resolve_bundle(args.bundle)
    rec = load_for_update(bundle, check_name(args.run))
    if not any(n["id"] == args.note for n in unsent_notes([rec])):
        die(f"run {rec['name']} has no unsent Slack note {args.note} (`follow unsent` lists them); "
            f"nothing was recorded")
    t = now()
    rec.setdefault("log", []).append({"at": t, "text": f"{SLACK_RELAYED}{args.note}"})
    rec["updated"] = t
    write_record(bundle, rec)
    print(f"run {rec['name']}: Slack note {args.note} relayed")
    return 0


# ── a recipe written for the run ─────────────────────────────────────────────
#
# When no saved recipe fits, the skill writes one. It is a draft first, under
# state/trunk/recipes/<run>/ (git-ignored, like the record), and becomes the
# run's recipe with a `written` block the script alone fills: where the draft
# is, its sha256, where it was saved. The check is held against that hash, so
# what is saved and started is byte for byte what passed. A saved recipe is
# never replaced: a team the dispatch tool started from it reloads it from that
# path when it resumes (orq does), and an edit would make the resume diverge.

RECIPE_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")


def recipe_drafts(bundle, run):
    return os.path.join(bundle, "state", "trunk", "recipes", run)


def _digest(paths):
    """One sha256 over the files of a written recipe, in order, or None when
    one of them is gone."""
    h = hashlib.sha256()
    for p in paths:
        try:
            with open(p, "rb") as fh:
                data = fh.read()
        except OSError:
            return None
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def _written_files(written):
    return [p for p in (written.get("draft"), written.get("test")) if p]


def written_recipe_problem(recipe):
    """Why a recipe written for the run cannot start, or None when it can (or
    when the run's recipe was not written by the trunk)."""
    if not isinstance(recipe, dict) or not isinstance(recipe.get("written"), dict):
        return None
    name, written, check = recipe.get("name"), recipe["written"], recipe.get("check")
    if not isinstance(check, dict):
        return f"the recipe {name} written for this run was never checked"
    if check.get("ok") is not True:
        return f"the recipe {name} written for this run failed its check ({check.get('error')})"
    if check.get("sha256") != written.get("sha256") or _digest(_written_files(written)) != written.get("sha256"):
        return f"the draft of the recipe {name} changed after its check; draft it again and check it"
    if not written.get("saved"):
        return f"the recipe {name} passed its check but was not saved (`trunk.py recipe save`)"
    return None


def _write_private(path, data):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".recipe-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_bytes(spec, what):
    try:
        if spec == "-":
            return sys.stdin.buffer.read()
        with open(spec, "rb") as fh:
            return fh.read()
    except OSError as exc:
        die(f"cannot read the {what} {spec} ({exc})")


def _open_for_recipe(args, after_dispatch=False):
    bundle = resolve_bundle(args.bundle)
    rec = load_for_update(bundle, check_name(args.run))
    if rec["status"] in STARTED and not after_dispatch:
        die(f"run {rec['name']} was already dispatched; its recipe stays as dispatched")
    if rec["status"] == STATUS_STARTING and not after_dispatch:
        die(f"run {rec['name']} is being started; its recipe stays as claimed until "
            f"`run dispatch` records how the start went")
    return bundle, rec


def _written_or_die(rec):
    recipe = rec.get("recipe")
    if not isinstance(recipe, dict) or not isinstance(recipe.get("written"), dict):
        die(f"run {rec['name']} has no recipe written for it (`trunk.py recipe draft` first)")
    return recipe


def cmd_recipe_draft(args):
    bundle, rec = _open_for_recipe(args)
    name = args.name
    if not RECIPE_NAME_RE.fullmatch(name or ""):
        die(f'"{name}" is not a recipe name: a lowercase letter, then lowercase letters, '
            f"digits and \"_\", at most 64 characters")
    if args.file == "-" and args.test == "-":
        die("only one of --file and --test can be read from stdin")
    source = _read_bytes(args.file, "recipe")
    test = _read_bytes(args.test, "check") if args.test else None
    if not source.strip():
        die("an empty recipe starts nothing")
    if not args.roles.strip():
        die("say the recipe's roles in --roles, one line per role")
    _refuse_stored_merge(args.recipe_command, "--command")
    ensure_ignored(bundle)
    d = recipe_drafts(bundle, rec["name"])
    os.makedirs(d, mode=0o700, exist_ok=True)
    draft = os.path.join(d, name + ".py")
    test_path = os.path.join(d, f"test_{name}.py") if test is not None else None
    _write_private(draft, source)
    if test_path:
        _write_private(test_path, test)
    written = {"draft": draft, "test": test_path, "sha256": None, "saved": None, "saved_test": None}
    written["sha256"] = _digest(_written_files(written))
    rec["recipe"] = {"name": name, "fact": None, "command": args.recipe_command or None,
                     "roles": args.roles.strip(), "written": written, "check": None}
    rec["updated"] = now()
    write_record(bundle, rec)
    if args.json:
        print(json.dumps({"name": name, **written}, ensure_ascii=False))
    else:
        print(draft)
    return 0


def cmd_recipe_checked(args):
    bundle, rec = _open_for_recipe(args)
    recipe = _written_or_die(rec)
    written = recipe["written"]
    current = _digest(_written_files(written))
    if current is None:
        die(f"the draft of the recipe {recipe['name']} is gone ({written.get('draft')}); draft it again")
    if current != written.get("sha256"):
        die(f"the draft of the recipe {recipe['name']} changed since `recipe draft`; "
            f"draft it again, so the record holds what was checked")
    if not args.check_command.strip():
        die("say the check that ran in --command")
    t = now()
    ok = args.error is None
    recipe["check"] = {"at": t, "ok": ok, "command": args.check_command.strip(),
                       "error": None if ok else args.error.strip(), "sha256": current}
    if not ok:
        first = (args.error.strip().splitlines() or [""])[0]
        rec.setdefault("log", []).append(
            {"at": t, "text": f"recipe {recipe['name']} failed its check, nothing dispatched: {first}"})
    rec["updated"] = t
    write_record(bundle, rec)
    if args.json:
        print(json.dumps({"name": recipe["name"], "check": recipe["check"]}, ensure_ascii=False))
    else:
        print(f"recipe {recipe['name']}: {'check passed' if ok else 'check failed, nothing is dispatched'}")
    return 0


def cmd_recipe_save(args):
    bundle, rec = _open_for_recipe(args)
    recipe = _written_or_die(rec)
    written = recipe["written"]
    if written.get("saved"):
        note(f"the recipe {recipe['name']} was already saved; a saved recipe is never saved again")
    else:
        problem = written_recipe_problem({**recipe, "written": {**written, "saved": "pending"}})
        if problem:
            die(f"not saved: {problem}")
        target = os.path.abspath(os.path.expanduser(args.dir))
        if not os.path.isdir(target):
            die(f"{target} is not a directory; the recipe directory is the one the dispatch "
                f"tool reads recipes from")
        dest = os.path.join(target, recipe["name"] + ".py")
        dest_test = os.path.join(target, f"test_{recipe['name']}.py") if written.get("test") else None
        taken = [p for p in (dest, dest_test) if p and os.path.lexists(p)]
        if taken:
            die(f"{taken[0]} already exists and a saved recipe is never replaced: a team started "
                f"from it resumes from that file; draft this one under another --name")
        made = []
        try:
            for src, dst in ((written["draft"], dest), (written.get("test"), dest_test)):
                if not dst:
                    continue
                with open(src, "rb") as fh:
                    data = fh.read()
                fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                made.append(dst)
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
        except OSError as exc:
            for p in made:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            die(f"cannot save the recipe {recipe['name']} in {target} ({exc})")
        written["saved"], written["saved_test"] = dest, dest_test
        rec["updated"] = now()
        write_record(bundle, rec)
    if args.json:
        print(json.dumps({"name": recipe["name"], "saved": written["saved"],
                          "saved_test": written.get("saved_test")}, ensure_ascii=False))
    else:
        print(written["saved"])
    return 0


def cmd_recipe_fact(args):
    """The trunk-recipe fact a saved recipe was captured with. It is filled in
    after the start too: the link says where the recipe is found for reuse, not
    what was dispatched, which stays as it was."""
    bundle, rec = _open_for_recipe(args, after_dispatch=True)
    recipe = _written_or_die(rec)
    if not recipe["written"].get("saved"):
        die(f"the recipe {recipe['name']} was not saved; its fact comes after `recipe save`")
    link = args.link.strip()
    if not link.startswith("/facts/"):
        die(f'"{link}" is not a fact link: it starts with /facts/, as `facts --json` prints it')
    recipe["fact"] = link
    rec["updated"] = now()
    write_record(bundle, rec)
    return 0


# ── steering and forgetting a learning ───────────────────────────────────────
#
# What the trunk learns about how the owner works is a fact like any other, so
# forgetting or steering one is elephant-mem's own move: never a deletion (git
# keeps the history), a status. A forgotten learning becomes `deprecated`; one
# the owner steered becomes `superseded`, linked both ways to the fact that
# replaced it. Either way it leaves the manifest's active facts once the index
# is rebuilt, and the manifest is all the trunk reads. Only the trunk's own how
# is touched here (the how-I-work tag plus an area tag): any other fact is the
# owner's to retire with elephant-mem's `maintain`.

FM_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*(?:\n|\Z)", re.S)
TOP_KEY_RE = r"^{key}:[ \t]*(.*)$"


def _fm_split(text):
    """(frontmatter lines, the text after it), or None with no frontmatter."""
    m = FM_RE.match(text)
    if not m:
        return None
    return m.group(1).splitlines(), text[m.end():]


def _fm_join(lines, body):
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def _scalar(raw):
    """A frontmatter scalar as build-index reads it: a quoted value unquoted
    (its escapes read), else the trailing ` #` comment cut; stripped."""
    v = raw.strip()
    if v[:1] == '"':
        i = 1
        while i < len(v) and v[i] != '"':
            i += 2 if v[i] == "\\" else 1
        try:
            return json.loads(v[:i + 1])
        except ValueError:
            return v[1:i]
    if v[:1] == "'":
        m = re.match(r"'((?:[^']|'')*)'", v)
        return m.group(1).replace("''", "'") if m else v[1:]
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def _top_index(lines, key):
    rx = re.compile(TOP_KEY_RE.format(key=re.escape(key)))
    return next((i for i, ln in enumerate(lines) if rx.match(ln)), None)


def _fm_status(lines):
    i = _top_index(lines, "status")
    if i is None:
        return "active"
    return _scalar(re.match(TOP_KEY_RE.format(key="status"), lines[i]).group(1)).lower() or "active"


def _fm_value(lines, key):
    i = _top_index(lines, key)
    return None if i is None else re.match(TOP_KEY_RE.format(key=re.escape(key)), lines[i]).group(1)


def _fm_tags(lines):
    """A frontmatter's top-level `tags`: a flow list (wrapped over several
    lines too, read to its `]`), a block list (comment and blank lines between
    its items passed over) or one scalar, each tag unquoted and stripped: the
    shapes build-index's own fallback parser reads."""
    return _fm_list(lines, "tags")


def _fm_list(lines, key):
    """A frontmatter's top-level list `key`, read as `_fm_tags` reads tags."""
    i = _top_index(lines, key)
    if i is None:
        return []
    def bare(text):
        return re.split(r"\s+#", text, maxsplit=1)[0].strip()
    value = bare(lines[i].split(":", 1)[1])
    if value.startswith("["):
        j = i + 1
        while not value.endswith("]") and j < len(lines) and not re.match(r"^\S[^:]*:", lines[j]):
            value = f"{value} {bare(lines[j])}".strip()
            j += 1
        if not value.endswith("]"):
            value += "]"
        return [t for t in (_scalar(x).strip() for x in _flow_items(value)) if t]
    if value:
        return [_scalar(value).strip()]
    out = []
    for ln in lines[i + 1:]:
        if not ln.strip() or ln.strip().startswith("#"):
            continue
        m = re.match(r"^[ \t]*-[ \t]+(.*)$", ln)
        if not m:
            break
        if _scalar(m.group(1)).strip():
            out.append(_scalar(m.group(1)).strip())
    return out


def _is_learning(lines, tag, areas=AREA_TAGS):
    """The area tags this frontmatter carries when it is the trunk's how (a
    fact with the how-I-work tag plus an area tag), else []."""
    if _scalar(_fm_value(lines, "type") or "") != "fact":
        return []
    tags = _fm_tags(lines)
    return [a for a in AREA_TAGS if a in areas and a in tags] if tag in tags else []


# Where a fact came from, read from the sources it cites. elephant-mem's
# `capture` files the current Claude Code conversation (the owner's own words)
# as a source whose `channel` is `claude-code` or `claude-code:<workspace>`;
# `ingest` and the scheduled `catch-up` stamp the feed a source came from
# (`slack:...`, `meeting`, `gcal:...`, `email`). The fact's own frontmatter and
# the manifest carry no origin, so the source is the only place it is said.
OWNER_CHANNEL_RE = re.compile(r"^claude-code(?::.*)?$")


def _read_fm(path):
    try:
        with open(path, encoding="utf-8") as fh:
            split = _fm_split(fh.read().replace("\r\n", "\n"))
    except (OSError, UnicodeDecodeError):
        return None
    return split[0] if split else None


def fact_origin(bundle, path):
    """(origin, channels) of a fact file: `owner` when it cites at least one
    source and every source it cites is the owner's own Claude Code
    conversation; `other` when any source came from another channel (a feed
    the catch-up or an ingest read); `unknown` when it cites none, or a source
    cannot be read or names no channel. Only `owner` is the owner's word."""
    lines = _read_fm(path)
    if lines is None:
        return "unknown", []
    links, channels, unknown, other = _fm_list(lines, "sources"), [], False, False
    if not links:
        return "unknown", []
    for link in links:
        if not link.startswith("/sources/") or "\\" in link or ".." in link.split("/"):
            unknown = True
            continue
        src = _read_fm(os.path.join(bundle, "knowledge", *link.lstrip("/").split("/")))
        channel = _scalar(_fm_value(src, "channel") or "").strip().lower() if src else ""
        if not channel:
            unknown = True
            continue
        channels.append(channel)
        if not OWNER_CHANNEL_RE.match(channel):
            other = True
    return ("other" if other else "unknown" if unknown else "owner"), channels


def forgotten_facts(bundle, tag, areas=AREA_TAGS):
    """The learnings the owner forgot or steered: the trunk's facts whose
    status is deprecated or superseded, most recently updated first. They are
    never in the manifest (build-index keeps active facts only), so this reads
    the fact files themselves; it is not how the owner works, only what the
    trunk must not learn again."""
    base = os.path.join(bundle, "knowledge", "facts")
    out = []
    for d, _, files in os.walk(base):
        for f in files:
            if not f.endswith(".md"):
                continue
            path = os.path.join(d, f)
            try:
                with open(path, encoding="utf-8") as fh:
                    split = _fm_split(fh.read())
            except (OSError, UnicodeDecodeError):
                continue
            if split is None:
                continue
            lines = split[0]
            status, hit = _fm_status(lines), _is_learning(lines, tag, areas)
            if status not in FORGOTTEN_STATUSES or not hit:
                continue
            rel = os.path.relpath(path, os.path.join(bundle, "knowledge")).replace(os.sep, "/")
            out.append({"path": path, "link": "/" + rel, "areas": hit,
                        "desc": _scalar(_fm_value(lines, "description") or ""),
                        "status": status, "tags": _fm_tags(lines),
                        "updated": _scalar(_fm_value(lines, "updated") or ""),
                        "occurred": _scalar(_fm_value(lines, "occurred") or ""),
                        "confidence": _scalar(_fm_value(lines, "confidence") or "")})
    out.sort(key=lambda x: x["link"])
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def _set_top(lines, key, value):
    """Set a top-level scalar, replacing its line (and any comment on it), or
    appending it when the frontmatter has none."""
    i = _top_index(lines, key)
    if i is None:
        lines.append(f"{key}: {value}")
    else:
        lines[i] = f"{key}: {value}"


def _flow_items(value):
    inner = value.strip()[1:-1]
    return [x.strip() for x in inner.split(",") if x.strip()]


def _add_relation(lines, rel, link):
    """Add `link` to `relations.<rel>` in a fact's frontmatter, in whatever
    form the list is written: `[]` and `[a, b]` (the template's), a block list,
    a single scalar, or absent. Returns False when it was already there; raises
    ValueError on a shape it cannot edit without guessing."""
    r = _top_index(lines, "relations")
    if r is None:
        lines += ["relations:", f"  {rel}: [{link}]"]
        return True
    head = re.match(TOP_KEY_RE.format(key="relations"), lines[r]).group(1).strip()
    if head and _scalar(head) not in ("{}", ""):
        raise ValueError("relations is written inline; edit it by hand")
    if head:
        lines[r] = "relations:"
    end = r + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][:1] in (" ", "\t")):
        end += 1
    children = [i for i in range(r + 1, end) if lines[i].strip()]
    indent = re.match(r"[ \t]*", lines[children[0]]).group(0) if children else "  "
    rx = re.compile(rf"^({re.escape(indent)}){re.escape(rel)}:[ \t]*(.*)$")
    at = next((i for i in children if rx.match(lines[i])), None)
    if at is None:
        lines.insert(r + 1, f"{indent}{rel}: [{link}]")
        return True
    value = rx.match(lines[at]).group(2)
    bare = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    if bare.startswith("["):
        if not bare.endswith("]"):
            raise ValueError(f"relations.{rel} is a list over several lines; edit it by hand")
        items = _flow_items(bare)
        if link in [_scalar(x) for x in items]:
            return False
        lines[at] = f"{indent}{rel}: [{', '.join(items + [link])}]"
        return True
    if bare:
        if _scalar(bare) == link:
            return False
        lines[at] = f"{indent}{rel}: [{bare}, {link}]"
        return True
    # A block list, or nothing at all under the key. Its items may sit at the
    # key's own indentation, as PyYAML's safe_dump writes them, or deeper.
    item_rx = re.compile(r"^([ \t]+)-[ \t]+(.*)$")
    last, item_indent = at, indent + "  "
    for i in range(at + 1, end):
        m = item_rx.match(lines[i])
        if not m or len(m.group(1)) < len(indent):
            break
        if _scalar(m.group(2)) == link:
            return False
        last, item_indent = i, m.group(1)
    if last == at:
        lines[at] = f"{indent}{rel}: [{link}]"
    else:
        lines.insert(last + 1, f"{item_indent}- {link}")
    return True


def _read_links(bundle, tag):
    """The links the trunk reads now, from the manifest."""
    try:
        facts, _ = how_facts(bundle, tag)
    except OSError:
        die(f"cannot read {os.path.join(bundle, 'knowledge', 'manifest.jsonl')} — rebuild it with "
            f"python3 {os.path.join(bundle, 'scripts', 'build-index.py')}")
    return [f["link"] for f in facts]


def _learning(bundle, tag, link):
    """The fact file of a learning the trunk reads, or read before it was
    forgotten: a `/facts/` link to a fact carrying the how-I-work tag plus an
    area tag. An active fact is a learning when `facts` lists it: the same
    manifest, read by the same code, so a tag shape build-index accepts is
    never refused here. Only a fact already forgotten or steered, which the
    manifest no longer carries, is judged by its own frontmatter. Returns
    (link, path, lines, body)."""
    link = (link or "").strip()
    # A backslash is refused outright: on Windows it separates a path, so
    # `/facts/..\\x.md` would leave facts/ past a `/`-only `..` check.
    if not link.startswith("/facts/") or "\\" in link or ".." in link.split("/") \
            or not link.endswith(".md"):
        die(f'"{link}" is not a fact link: it starts with /facts/ and ends in .md, '
            f"as `facts --json` prints it")
    path = os.path.join(bundle, "knowledge", *link.lstrip("/").split("/"))
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        die(f"no fact at {link} ({path}) — check the link with `facts --json`")
    except (OSError, UnicodeDecodeError) as exc:
        die(f"cannot read {path} ({exc})")
    split = _fm_split(text)
    if split is None:
        die(f"{path} has no frontmatter to edit")
    if _fm_status(split[0]) == "active":
        learning = link in _read_links(bundle, tag)
    else:
        learning = bool(_is_learning(split[0], tag))
    if not learning:
        die(f'{link} is not a learning the trunk reads (a fact `facts --json` lists, with "{tag}" '
            f"plus one of {', '.join(AREA_TAGS)}, after the index is rebuilt); the trunk steers "
            f"and forgets only its own how — another fact is retired with elephant-mem's maintain")
    return link, path, split[0], split[1]


def _write_fact(path, text):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".fact-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _rebuild_index(bundle):
    """Run the bundle's own build-index.py, so the manifest the trunk reads
    says what the fact files now say."""
    script = os.path.join(bundle, "scripts", "build-index.py")
    r = subprocess.run([sys.executable, script], cwd=bundle, capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode != 0:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-5:])
        die(f"the fact file was edited but {script} failed, so the trunk still reads the "
            f"old index; fix it and run it again:\n{tail}")


def _builder_or_die(bundle):
    script = os.path.join(bundle, "scripts", "build-index.py")
    if not os.path.isfile(script):
        die(f"{script} is missing, and without it the index would keep the learning read; "
            f"nothing was changed (restore the bundle's scripts with elephant-mem's update)")


def _steer_line(s):
    if s.get("action") == "steered":
        return f"steered to {s.get('to')}"
    return "forgotten"


def _log_steer(bundle, run_name, entry):
    rec = load_for_update(bundle, run_name)
    entry = {"at": now(), **entry}
    rec.setdefault("steers", []).append(entry)
    rec["updated"] = entry["at"]
    write_record(bundle, rec)


def _verify_read(bundle, tag, changed, gone, kept=None):
    """Rebuild the index when a fact changed (or the manifest still lists
    `gone`, an index left stale), then check the trunk reads what it should."""
    if changed or gone in _read_links(bundle, tag):
        _rebuild_index(bundle)
    read = _read_links(bundle, tag)
    if gone in read:
        die(f"{gone} is still listed as active in knowledge/manifest.jsonl after the rebuild")
    if kept and kept not in read:
        die(f"{kept} is not read by the trunk after the rebuild; check its tags with `facts --json`")


def _learning_tag(bundle, verb):
    """The tag `learning forget` and `steer` read, or a stop naming the
    problem, as `facts` does: under the default tag an owner's learning is
    refused as not one, and the refusal would hide the broken elephant.json."""
    cfg = config(bundle)
    if cfg["problem"]:
        die(f"{cfg['problem']}; fix elephant.json first: the trunk {verb} no learning until "
            f"its tag is usable ({SET_TAG_HINT})")
    return cfg["tag"]


def cmd_learning_forget(args):
    bundle = resolve_bundle(args.bundle)
    tag = _learning_tag(bundle, "forgets")
    run_name = check_name(args.run) if args.run else None
    if run_name:
        load_or_die(bundle, run_name)
    _builder_or_die(bundle)
    link, path, lines, body = _learning(bundle, tag, args.link)
    status = _fm_status(lines)
    if status == "active":
        _set_top(lines, "status", FORGOTTEN)
        _set_top(lines, "updated", datetime.date.today().isoformat())
        ensure_ignored(bundle)
        _write_fact(path, _fm_join(lines, body))
        status, changed = FORGOTTEN, True
    elif status in FORGOTTEN_STATUSES:
        note(f"{link} is already {status}; the trunk does not read it")
        changed = False
    else:
        die(f"{link} has status {status}, which the trunk already does not read; nothing to forget")
    _verify_read(bundle, tag, changed, link)
    if run_name:
        _log_steer(bundle, run_name, {"link": link, "action": "forgotten", "to": None})
    if args.json:
        print(json.dumps({"link": link, "path": path, "status": status, "changed": changed,
                          "run": run_name}, ensure_ascii=False))
    else:
        print(f"forgot {link}: the trunk no longer reads it")
    return 0


def cmd_learning_steer(args):
    bundle = resolve_bundle(args.bundle)
    tag = _learning_tag(bundle, "steers")
    run_name = check_name(args.run) if args.run else None
    if run_name:
        load_or_die(bundle, run_name)
    _builder_or_die(bundle)
    old, old_path, old_lines, old_body = _learning(bundle, tag, args.link)
    new, new_path, new_lines, new_body = _learning(bundle, tag, args.to)
    if old == new:
        die("a learning is steered to another fact, not to itself")
    if _fm_status(new_lines) != "active":
        die(f"{new} is not active; a learning is steered to the how the owner holds now "
            f"(capture it first, then steer)")
    old_status = _fm_status(old_lines)
    if old_status not in ("active", STEERED):
        die(f"{old} has status {old_status}; the trunk no longer reads it, so there is nothing "
            f"to steer (capture the new how on its own)")
    try:
        changed_old = _add_relation(old_lines, "superseded-by", new)
        changed_new = _add_relation(new_lines, "supersedes", old)
    except ValueError as exc:
        die(f"nothing was changed: {exc}")
    if old_status == STEERED and not changed_old:
        note(f"{old} was already steered to {new}")
    changed_old = changed_old or old_status != STEERED
    today = datetime.date.today().isoformat()
    ensure_ignored(bundle)
    if changed_new:
        _set_top(new_lines, "updated", today)
        _write_fact(new_path, _fm_join(new_lines, new_body))
    if changed_old:
        _set_top(old_lines, "status", STEERED)
        _set_top(old_lines, "updated", today)
        _write_fact(old_path, _fm_join(old_lines, old_body))
    _verify_read(bundle, tag, changed_old or changed_new, old, kept=new)
    if run_name:
        _log_steer(bundle, run_name, {"link": old, "action": "steered", "to": new})
    if args.json:
        print(json.dumps({"link": old, "to": new, "status": STEERED,
                          "changed": changed_old or changed_new, "run": run_name}, ensure_ascii=False))
    else:
        print(f"steered {old} to {new}: the trunk reads {new} in its place")
    return 0


# ── past sessions ────────────────────────────────────────────────────────────
#
# First use can read how the owner works from their own past Claude Code
# sessions. The raw transcripts are large (the 30 most recent were about 79 MB)
# and hold everything a session touched: tool output, files read, other
# people's words, secrets. So nothing raw leaves this script. `sessions list`
# prints counts and an estimate only; `sessions extract` prints, for the small
# model that reads it, the owner's own messages and the names of what the
# session ran, with tool output, the assistant's text, system-injected blocks
# and anything shaped like a credential left out.

SESSIONS_LIMIT = 30          # the most recent sessions read by default
BATCH_TOKENS = 60000         # what one small-model reader is handed, at most
TURN_CHARS = 2000            # one owner message, at most, before it is cut
CHARS_PER_TOKEN = 4          # the rough rule the estimate is stated with
USED_MAX = 12                # names of what ran between two owner messages

_DROP_BLOCKS = re.compile(
    r"<(system-reminder|local-command-caveat|local-command-stdout|local-command-stderr|"
    r"bash-stdout|bash-stderr|task-notification|scheduled-task|command-message)\b[^>]*>.*?</\1>",
    re.S)
# The owner's bash mode (`!cmd`) lands as user turns: the command in a
# `<bash-input>` turn, its output in a `<bash-stdout>`/`<bash-stderr>` turn.
# The output is tool output, never the owner's words; the command is reduced
# to the programs it ran, as the assistant's Bash is.
_BASH_INPUT = re.compile(r"<bash-input>(.*?)(?:</bash-input>|\Z)", re.S)
_BASH_OUTPUT = ("<bash-stdout", "<bash-stderr")
_PASTED = re.compile(r"<pasted_content\b[^>]*>(.*?)</pasted_content\b[^>]*>", re.S)
_COMMAND = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_INTERRUPTED = re.compile(r"^\[Request interrupted by user[^\]]*\]\s*$", re.M)
_SECRETS = [
    # PEM and PGP armor: `… PRIVATE KEY-----`, `… PRIVATE KEY BLOCK-----`.
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?"
               r"(-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)", re.S),
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bA[KS]IA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{16,}"),
    # `user:pass@`, and `:pass@` with no user (`redis://:pw@cache`).
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]*:[^\s/@]+@"),
    # Webhook URLs: the URL itself is the credential.
    re.compile(r"(?i)\bhttps?://hooks\.slack\.com/\S+"),
    re.compile(r"(?i)\bhttps?://(?:[\w-]+\.)*discord(?:app)?\.com/api/webhooks/\S+"),
]
# Any other webhook URL is one only when it carries a token: a page about
# webhooks is a link the owner shared, not a credential.
_WEBHOOK = re.compile(r"(?i)\bhttps?://\S*webhook\S*")
# A credential named by its key, in code, config or JSON: `password = x`,
# `"password": "x"`, `aws_secret_access_key=x`, `senha: x`, `DB_PASS=x`,
# `MYSQL_PWD=x`, `STRIPE_KEY=x`. The key and the separator are kept, the value
# is left out. A key word ends where the key does or where a capital opens the
# next word (`passwordConfirm`, `adminPasswordProd`, `BasicAuth`), never before
# a lowercase letter: the words that go on past one (passo, passou, passwordless,
# author, authentication) are not keys. Glued after a prefix (`PGPASS`, `dbpass`,
# `authkey`) a key word still counts, except where the prefix makes another word
# of it (bypass, compass, surpass, trespass, OAuth: an `o` that opens the key or
# follows `_`, so `ProtoAuth` and `DOAUTH` still count). A bare `key` is not one,
# only a `_key` suffix is, and not the key of a table or a map (`primary_key`).
_WORD_END = r"(?-i:(?![a-z]))"
_CRED_WORDS = (rf"pass(?:word|wd|phrase|code|key)s?{_WORD_END}|"
               rf"(?<!by)(?<!com)(?<!sur)(?<!tres)pass{_WORD_END}|pwd|secret|token|"
               r"api[_-]?key|access[_-]?key|private[_-]?key|"
               r"(?<!primary)(?<!foreign)(?<!unique)(?<!sort)(?<!partition)(?<!range)"
               rf"(?<!shard)(?<!cache)(?<!lookup)(?<!join)(?<!group)(?<!row)_key{_WORD_END}|"
               rf"credential|senha|chave|(?<!\bo)(?<!_o)auth(?:orization|key)?{_WORD_END}")
# An HTTP scheme before the value (`Authorization: Token x`) is part of it.
_KEYED_SECRET = re.compile(
    rf"(?i)\b([A-Za-z_]*(?:{_CRED_WORDS})[A-Za-z_]*[\"']?)(\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|(?:(?:bearer|basic|token|digest)\s+)?\S+)")
# A password is often words with spaces (`password: correct horse battery
# staple`): with a password key and an unquoted value, the rest of the line is
# the value. A quoted one is cut by _KEYED_SECRET, up to its closing quote.
_KEYED_PASSWORD = re.compile(
    rf"(?i)\b([A-Za-z_]*(?:password|passwd|passphrase|senha)s?{_WORD_END}[A-Za-z_]*[\"']?)"
    r"([ \t]*[:=][ \t]*)(?![\"'\s])([^\n]+)")
# MySQL takes its password glued to `-p` (`mysql -u root -pHunter2`), and so
# do its tools and MariaDB's (`mariadb-dump` is `mariadb` up to the hyphen).
# Only after one of them, in any case: `ssh -p2222` and `cp -pR` are no password.
_MYSQL_PASSWORD = re.compile(
    r"(?i)\b((?:mysql(?:dump|admin|import|check|show|sh)?|mariadb)\b[^\n]*?\s-p)"
    r"('[^']*'|\"[^\"]*\"|\S+)")
# A secret named in prose: "the password for prod is hunter2pass", "a senha
# do banco é Xy9kq2pz77", "the token is 9f8e7d…", "--api-key 9f8e7d…". Within
# the few words after the keyword, a word that mixes letters with digits or
# symbols is taken for the secret.
_PROSE_SECRET = re.compile(
    r"(?i)\b(?:password|passwd|passphrase|senha|token|api[ _-]?key|chave)\b([^\n]{0,60})")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_+/=-]{32,}")
# Inside one word of a slashed string, the marks of random text no name
# carries: a digit between letters (K7M), letters between digits (3fa9), one
# lowercase letter between capitals (PxR), a word opening lowercase then
# capital (wJalr). A camel-cased name or a numbered folder has none of them.
_NOISE = re.compile(r"[A-Za-z]\d+[A-Za-z]|\d[A-Za-z]+\d|[A-Z][a-z][A-Z]|^[a-z][A-Z]")
_CUT = "\ue000"               # where a secret was, until _redact writes the marker
# Text Claude Code itself puts in a user turn on older transcripts, which carry
# no `origin` to tell it from the owner's: a peer session's message, a resumed
# session's summary, a hook's feedback.
_INJECTED = ("Another Claude session sent", "This session is being continued",
             "Stop hook feedback:", "A session-scoped Stop hook", "Caveat: The messages below")
# Built-in commands say nothing of how the owner works; a skill or a plugin
# command (`/orq`, `/bb:spec`) does, so only these are passed over.
_BUILTIN_COMMANDS = {"/clear", "/compact", "/exit", "/quit", "/resume", "/model", "/cost",
                     "/context", "/status", "/config", "/login", "/logout", "/help",
                     "/doctor", "/usage", "/mcp", "/plugin", "/permissions", "/rewind"}
# Shell plumbing: present in every session, so it tells nothing apart.
_PLUMBING = {"ls", "cat", "head", "tail", "grep", "rg", "sed", "awk", "echo", "printf", "wc",
             "sort", "uniq", "cut", "tr", "find", "xargs", "true", "false", "test", "pwd",
             "mkdir", "rm", "cp", "mv", "touch", "sleep", "date", "which", "command", "export",
             "source", "set", "jq", "tee", "diff", "stat", "basename", "dirname", "realpath",
             "readlink", "for", "done", "if", "fi", "while", "until", "case", "esac", "break",
             "continue", "return", "wait", "exit", "true", "local", "read", "printf"}
# Words that start a segment before its program: skipped, the next word is it.
_PREFIXES = {"sudo", "time", "env", "nohup", "exec", "!", "(", "{", "do", "then", "else", "elif"}


def _redact(text):
    """Credential-shaped strings out, before any reader sees the text. Errs on
    the side of cutting: a hash or an id lost costs nothing to how the owner
    works, while one token let through would be read by a model and could be
    offered back for capture.

    Each pass writes a one-character stand-in, swapped for the marker at the
    end: the marker holds spaces and a bracket, so a later pass would take a
    piece of it for a value and cut the marker itself."""
    text = text.replace(_CUT, "")
    for rx in _SECRETS:
        text = rx.sub(_CUT, text)
    text = _WEBHOOK.sub(lambda m: _CUT if any(
        len(p) >= 12 and re.search(r"\d", p) and re.search(r"[A-Za-z]", p)
        for p in re.split(r"[/?&=#@]", m.group(0))) else m.group(0), text)

    def keyed(m):
        # `max_tokens = 4096` counts tokens, it holds none. Only a count is
        # kept: `access_tokens = abc123…` holds them, and is cut.
        if re.search(r"(?i)tokens", m.group(1)) and re.fullmatch(r"[\"']?\d+[\"']?,?", m.group(3)):
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}{_CUT}"
    text = _KEYED_PASSWORD.sub(lambda m: f"{m.group(1)}{m.group(2)}{_CUT}", text)
    text = _MYSQL_PASSWORD.sub(lambda m: f"{m.group(1)}{_CUT}", text)
    text = _KEYED_SECRET.sub(keyed, text)

    def prose(m):
        words = re.split(r"(\s+)", m.group(1))
        for i, w in enumerate(words[:13]):
            core = w.strip(".,;:!?()[]{}<>\"'`")
            # A skill command (`/bb:spec`), a link, or a path of two or more
            # segments none of which reads as random text: never a password.
            # A lone `/Xy9kq2pz77` is none of these, and is cut.
            if re.fullmatch(r"/[a-z][a-z-]*(?::[a-z][a-z-]*)?", core) or "://" in core:
                continue
            segs = core.lstrip("~").strip("/").split("/")
            if "/" in core and len(segs) >= 2 and all(segs) \
                    and not any(_NOISE.search(p) for seg in segs for p in re.split(r"[_.+=-]", seg)):
                continue
            if len(core) >= 6 and re.search(r"[^\W\d_]", core) and re.search(r"[\d\W_]", core) \
                    and _CUT not in w:
                words[i] = w.replace(core, _CUT)
        return m.group(0)[:m.start(1) - m.start(0)] + "".join(words)
    text = _PROSE_SECRET.sub(prose, text)

    def long_token(m):
        s = m.group(0)
        if not (re.search(r"\d", s) and re.search(r"[A-Za-z]", s)):
            return s
        if "/" in s:
            # A path, a URL's path or a slashed token. A token when two of
            # its words read as random text: a repo path or a PR link, mixed
            # case or not, reads as names. Otherwise only a segment shaped
            # like a token on its own (a commit hash) is cut, so a commit
            # link keeps its repo and a path keeps its folders.
            noisy = sum(1 for w in re.split(r"[/_.+=-]", s) if _NOISE.search(w))
            if noisy >= 2:
                return _CUT
            return "/".join(
                _CUT if len(seg) >= 16 and re.search(r"\d", seg) and re.search(r"[A-Za-z]", seg)
                and _NOISE.search(seg) else seg for seg in s.split("/"))
        return _CUT
    return _LONG_TOKEN.sub(long_token, text).replace(_CUT, "[secret left out]")


def sessions_root(override=""):
    if override:
        return os.path.abspath(os.path.expanduser(override))
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(base, "projects")


def _transcripts(root):
    """The top-level transcript of every session, one directory per project.
    A subagent's transcript sits deeper and holds no word of the owner's."""
    found = []
    try:
        projects = sorted(os.listdir(root))
    except OSError:
        return None
    for proj in projects:
        d = os.path.join(root, proj)
        if not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if n.endswith(".jsonl") and os.path.isfile(p):
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                found.append((st.st_mtime, st.st_size, p))
    found.sort(key=lambda t: (-t[0], t[2]))
    return found


def _owner_text(rec):
    """The owner's own words in one transcript line, or None. A line is the
    owner's when it is a user turn, not injected (meta, compact summary, a
    sidechain, an origin other than a human), and carries text rather than a
    tool result."""
    if rec.get("type") != "user":
        return None
    if rec.get("isMeta") or rec.get("isSidechain") or rec.get("isCompactSummary") \
            or rec.get("isVisibleInTranscriptOnly"):
        return None
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_result":
                return None
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif b.get("type") == "image":
                parts.append("[an image]")
    else:
        return None
    text = "\n".join(parts)
    if text.lstrip().startswith(_INJECTED + _BASH_OUTPUT):
        return None
    text = _BASH_INPUT.sub(
        lambda m: ", ".join(f"ran {w}" for w in _bash_words(m.group(1))), text)
    cmd = _COMMAND.search(text)
    if cmd:
        args = _COMMAND_ARGS.search(text)
        args = args.group(1).strip() if args else ""
        if cmd.group(1) in _BUILTIN_COMMANDS and not args:
            return None
        text = cmd.group(1) + (" " + args if args else "")
    elif text.strip() in _BUILTIN_COMMANDS:
        return None
    text = _DROP_BLOCKS.sub("", text)
    # What the owner pasted is someone's text, not their words: the reader is
    # told never to use it, so only the mark that something was pasted stays.
    text = _PASTED.sub("[pasted]", text)
    text = _INTERRUPTED.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return None
    # Redacted before the cut: a token the cut split would fall under its
    # pattern's minimum length and its prefix would reach the reader.
    text = _redact(text)
    if len(text) > TURN_CHARS:
        text = text[:TURN_CHARS].rstrip() + " [… cut]"
    return text


def _bash_words(command):
    """The programs a shell command ran, never their arguments: an argument
    can carry a path, a customer's name or a secret. A program name carries
    much less, but not nothing: a script named for a client
    (`./scripts/acme-migrate.sh`) comes through as `acme-migrate.sh`, and
    nothing in this script knows a client's name to take it out."""
    words = []
    # The first line only, up to a heredoc: what follows is the command's
    # input (a file's text, a message), and its first words are content.
    line = (command or "").split("\n", 1)[0].split("<<", 1)[0]
    # A quoted argument is an argument (an inline script, a message): out
    # whole, so a `;` inside it does not start a command. An unclosed quote
    # ends the line.
    line = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", line)
    line = re.split(r"[\"'`]|\$\(", line.replace("''", " "), maxsplit=1)[0]
    for seg in re.split(r"&&|\|\||[;|]", line):
        for tok in seg.strip().split():
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok) or tok in _PREFIXES:
                continue
            w = os.path.basename(tok.strip("'\"()"))
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9._+-]{0,39}", w) and w not in _PLUMBING and w != "cd":
                words.append(w)
            break
    return words


def _used(rec):
    """Names of what an assistant turn ran: a skill, a subagent, a program."""
    if rec.get("type") != "assistant" or rec.get("isSidechain"):
        return []
    content = (rec.get("message") or {}).get("content")
    out = []
    for b in content if isinstance(content, list) else []:
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        name, inp = b.get("name") or "", b.get("input") or {}
        if not isinstance(inp, dict):
            inp = {}
        if name == "Skill" and isinstance(inp.get("skill"), str):
            out.append(f"skill {inp['skill'][:60]}")
        elif name in ("Agent", "Task"):
            kind = inp.get("subagent_type")
            out.append(f"subagent {kind[:40]}" if isinstance(kind, str) and kind else "subagent")
        elif name == "Bash":
            out.extend(f"ran {w}" for w in _bash_words(inp.get("command")))
        elif name:
            out.append(name[:60])
    return out


def _session(path):
    """One transcript, reduced to what a reader of how the owner works needs."""
    turns, cwd, first, last = [], None, None, None
    used = []
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"path": path, "error": str(exc)}
    with fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            if cwd is None and isinstance(rec.get("cwd"), str):
                cwd = rec["cwd"]
            ts = rec.get("timestamp")
            if isinstance(ts, str):
                first = first or ts
                last = ts
            text = _owner_text(rec)
            if text is not None:
                if used and turns:
                    turns.append("[then: " + ", ".join(used[:USED_MAX])
                                 + (", …" if len(used) > USED_MAX else "") + "]")
                used = []
                turns.append("owner: " + text)
                continue
            for u in _used(rec):
                if u not in used:
                    used.append(u)
    if used and turns:
        turns.append("[then: " + ", ".join(used[:USED_MAX]) + (", …" if len(used) > USED_MAX else "") + "]")
    body = "\n".join(turns)
    return {"path": path, "cwd": cwd, "first": first, "last": last,
            "owner_turns": sum(1 for t in turns if t.startswith("owner: ")),
            "text": body, "tokens": -(-len(body) // CHARS_PER_TOKEN)}


def _positive(value, flag):
    if value < 1:
        die(f"{flag} must be at least 1")
    return value


def cmd_sessions_list(args):
    limit = _positive(args.limit, "--limit")
    budget = _positive(args.batch_tokens, "--batch-tokens")
    root = sessions_root(args.root)
    found = _transcripts(root)
    if found is None:
        die(f"no Claude Code sessions at {root} (pass --root <dir> when they live elsewhere)")
    chosen, skipped, unreadable = [], 0, []
    for mtime, size, path in found:
        if len(chosen) == limit:
            break
        s = _session(path)
        if "error" in s:
            unreadable.append(path)
            continue
        if not s["owner_turns"]:
            skipped += 1
            continue
        tokens = min(s["tokens"], budget)
        chosen.append({"path": path, "cwd": s["cwd"], "modified":
                       datetime.datetime.fromtimestamp(mtime).isoformat(timespec="minutes"),
                       "bytes": size, "owner_turns": s["owner_turns"], "tokens": tokens,
                       "cut": s["tokens"] > budget})
    batches, cur, cur_tokens = [], [], 0
    for c in chosen:
        if cur and cur_tokens + c["tokens"] > budget:
            batches.append(cur)
            cur, cur_tokens = [], 0
        cur.append(c["path"])
        cur_tokens += c["tokens"]
    if cur:
        batches.append(cur)
    raw = sum(c["bytes"] for c in chosen)
    out = {"root": root, "found": len(found), "found_bytes": sum(f[1] for f in found),
           "limit": limit, "read": len(chosen), "skipped_no_owner": skipped,
           "unreadable": unreadable, "raw_bytes": raw,
           "raw_tokens": -(-raw // CHARS_PER_TOKEN),
           "tokens": sum(c["tokens"] for c in chosen), "batch_tokens": budget,
           "readers": len(batches), "batches": batches, "sessions": chosen,
           "projects": len({c["cwd"] or os.path.dirname(c["path"]) for c in chosen}),
           "since": min((c["modified"] for c in chosen), default=None),
           "until": max((c["modified"] for c in chosen), default=None)}
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
        return 0
    mb = lambda n: f"{n / 1e6:.1f} MB"
    print(f"{out['found']} sessions found under {root} ({mb(out['found_bytes'])})")
    if not chosen:
        print("none has a message of the owner's to read")
        return 0
    print(f"would read the {out['read']} most recent with a message of the owner's, "
          f"{out['since']} to {out['until']}, across {out['projects']} projects")
    print(f"raw: {mb(raw)}, about {out['raw_tokens']:,} tokens; after extraction: "
          f"about {out['tokens']:,} tokens, in {out['readers']} small-model readers")
    if skipped:
        print(f"{skipped} more recent sessions hold no message of the owner's and are passed over")
    for p in unreadable:
        print(f"could not read {p}")
    return 0


def cmd_sessions_extract(args):
    budget = _positive(args.max_tokens, "--max-tokens")
    status = 0
    for path in args.paths:
        s = _session(os.path.abspath(os.path.expanduser(path)))
        if "error" in s:
            note(f"could not read {path}: {s['error']}")
            status = 1
            continue
        # The date only: the session's directory is a path, which the reader
        # is told never to use and which names a project or a customer.
        head = f"## session {os.path.basename(path)}"
        day = (s["first"] or "")[:10]
        print(f"{head} ({day})" if day else head)
        text = s["text"] or "(no message of the owner's)"
        cap = budget * CHARS_PER_TOKEN
        if len(text) > cap:
            text = text[:cap].rstrip() + f"\n[cut: about {s['tokens'] - budget:,} more tokens]"
        print(text)
        print()
    return status


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bundle", default="", help="bundle root (default: ELEPHANT_BUNDLE, then the machine pointer)")
    ap = argparse.ArgumentParser(prog="trunk.py", description="The mechanics of elephant-trunk.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("config", parents=[common], help="print the bundle and the how-I-work tag")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_config)
    p = sub.add_parser("hours", parents=[common],
                       help="the owner's business hours: open now, when they close, when they open next")
    p.add_argument("--at", default="", metavar="TIME",
                   help="read them at this time, ISO 8601 with its offset (default: now)")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_hours)
    p = sub.add_parser("facts", parents=[common],
                       help="list the owner's how: facts with the how-I-work tag plus a trunk area tag")
    p.add_argument("--area", action="append", choices=AREA_TAGS,
                   help="only this area tag (repeatable; default: all four)")
    p.add_argument("--forgotten", action="store_true",
                   help="the learnings forgotten or steered instead, never read as the owner's how")
    p.add_argument("--json", action="store_true",
                   help="print one JSON object; each fact carries its origin (owner, other, unknown)")
    p.set_defaults(func=cmd_facts)

    run = sub.add_parser("run", help="the run record: new, show, list, set, claim, dispatch, ingested, "
                                     "wait, hold")
    rsub = run.add_subparsers(dest="run_command", required=True)
    p = rsub.add_parser("new", parents=[common], help="start a run record")
    p.add_argument("--topic", required=True, help="the topic, in one line")
    p.add_argument("--name", default="", help="the run's name (default: <date>-<slug of the topic>)")
    p.add_argument("--json", action="store_true", help="print the name and path as one JSON object")
    p.set_defaults(func=cmd_run_new)
    p = rsub.add_parser("show", parents=[common], help="read a run record back")
    p.add_argument("name")
    p.add_argument("--json", action="store_true", help="print the record itself")
    p.set_defaults(func=cmd_run_show)
    p = rsub.add_parser("list", parents=[common], help="the runs, most recent first")
    p.add_argument("--open", action="store_true", help="only runs not dispatched yet (open or starting)")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_run_list)
    p = rsub.add_parser("set", parents=[common], help="continue a run: set or add one field")
    p.add_argument("name")
    p.add_argument("field", choices=[*TEXT_FIELDS, *JSON_FIELDS, *APPEND_FIELDS])
    p.add_argument("--value", default=None, help="the value")
    p.add_argument("--file", default=None, help="read the value from this file (- for stdin)")
    p.add_argument("--pending", type=int, default=None, metavar="N",
                   help="with learning or note: this settles pending learning N (1-based)")
    p.set_defaults(func=cmd_run_set)
    p = rsub.add_parser("claim", parents=[common],
                        help="claim an open run before its dispatch command runs: it becomes starting")
    p.add_argument("name")
    p.add_argument("--via", required=True, choices=DISPATCH_VIAS)
    p.add_argument("--command", dest="dispatch_command", required=True,
                   help="the command about to start the work; via orq, it carries no merge parameter")
    p.add_argument("--where", default="", help="where the work will run (orq team, workspace, session)")
    p.add_argument("--json", action="store_true", help="print the run's summary and claim as JSON")
    p.set_defaults(func=cmd_run_claim)
    p = rsub.add_parser("dispatch", parents=[common],
                        help="record how a start went: dispatched, or open again with --error")
    p.add_argument("name")
    p.add_argument("--via", required=True, choices=DISPATCH_VIAS)
    p.add_argument("--command", dest="dispatch_command", required=True,
                   help="the command that started the work")
    p.add_argument("--where", default="", help="where the work runs (orq team, workspace, session)")
    p.add_argument("--error", default=None, help="the attempt failed with this error")
    p.add_argument("--json", action="store_true", help="print the run's summary as JSON")
    p.set_defaults(func=cmd_run_dispatch)
    p = rsub.add_parser("ingested", parents=[common],
                        help="record that ingest ran over a dispatched run's record, after "
                             "checking that one commit carries nothing of state/trunk/, no byte "
                             "copy of it, and no lines with the record's created time and name")
    p.add_argument("name")
    p.add_argument("--commit", default="", help="the ingest commit (default: the bundle's HEAD)")
    p.add_argument("--json", action="store_true", help="print the run's summary and its ingests as JSON")
    p.set_defaults(func=cmd_run_ingested)
    wait = rsub.add_parser("wait", help="what a dispatched run waits on next: set, show, list, end")
    wsub = wait.add_subparsers(dest="wait_command", required=True)
    p = wsub.add_parser("set", parents=[common],
                        help="start or update the wait of a dispatched run (an empty value clears a field)")
    p.add_argument("name")
    p.add_argument("--on", default=None, choices=WAIT_ON, help="what the run waits on now")
    p.add_argument("--repo", default=None, help="owner/name on GitHub, or the absolute path of a local repo")
    p.add_argument("--branch", default=None, help="the branch the work is on")
    p.add_argument("--team", default=None, help="the orq team key the work was dispatched to")
    p.add_argument("--pr", default=None, help="the pull request: its number or its GitHub URL")
    p.add_argument("--sha", default=None, help="the commit the run's reviewer approved")
    p.add_argument("--session", default=None, help="the orq session that owns the run")
    p.add_argument("--deploy", default=None, metavar="KIND",
                   help=f"what deploying means in this repo: {', '.join(DEPLOY_KINDS)}")
    p.add_argument("--health-rule", dest="health_rule", default=None,
                   help="what healthy means after the deploy, in one line")
    p.add_argument("--health-window", dest="health_window", default=None, metavar="MINUTES",
                   help=f"how long after the deploy health is watched ({HEALTH_WINDOW_DEFAULT} when a health rule names none)")
    p.add_argument("--hold-until", dest="hold_until", default=None, metavar="TIME",
                   help="no merge before this time (ISO 8601 with its offset)")
    p.add_argument("--state", default=None, metavar="JSON",
                   help="what the sources last saw, a JSON object merged key by key (null drops a key)")
    p.add_argument("--reminded", action="store_true", help="the reminder for this stretch was sent")
    p.add_argument("--json", action="store_true", help="print the run's summary and its wait as JSON")
    p.set_defaults(func=cmd_run_wait_set)
    p = wsub.add_parser("show", parents=[common], help="read a run's wait and hold back")
    p.add_argument("name")
    p.add_argument("--json", action="store_true", help="print the run's summary, wait and hold as JSON")
    p.set_defaults(func=cmd_run_wait_show)
    p = wsub.add_parser("list", parents=[common], help="the waiting runs, most recent first")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_run_wait_list)
    p = wsub.add_parser("end", parents=[common], help="end a run's wait: it is dispatched again")
    p.add_argument("name")
    p.add_argument("--outcome", required=True, choices=WAIT_OUTCOMES, help="how the wait ended")
    p.add_argument("--why", required=True, help="why, in one line")
    p.add_argument("--json", action="store_true", help="print the run's summary and its wait as JSON")
    p.set_defaults(func=cmd_run_wait_end)
    p = rsub.add_parser("hold", parents=[common],
                        help="the owner's hold on a run: no merge until the owner lifts it")
    p.add_argument("name")
    p.add_argument("--why", required=True, help="why, in one line")
    p.add_argument("--lift", action="store_true", help="lift the hold, on the owner's word")
    p.add_argument("--json", action="store_true", help="print the run's summary, wait and hold as JSON")
    p.set_defaults(func=cmd_run_hold)

    follow = sub.add_parser("follow", help="the waiting runs' sources and the queue: poll, queue, take, wake, "
                                           "mark, checkout, unsent, relayed")
    fsub = follow.add_subparsers(dest="follow_command", required=True)
    p = fsub.add_parser("poll", parents=[common],
                        help="one tick: run the sources over the waiting runs, enqueue what changed")
    p.add_argument("--now", default="", metavar="TIME",
                   help="the time the tick reads (ISO 8601 with its offset; default: now), for a dry run or a test")
    p.add_argument("--dry-run", action="store_true",
                   help="read the sources and say what would be enqueued; write nothing")
    p.add_argument("--json", action="store_true", help="print the tick as one JSON object")
    p.set_defaults(func=cmd_follow_poll)
    p = fsub.add_parser("queue", parents=[common], help="the events not delivered yet, oldest first")
    p.add_argument("--all", action="store_true", help="every event, delivered and dropped too")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_follow_queue)
    p = fsub.add_parser("take", parents=[common], help="take a pending event for delivery")
    p.add_argument("id", help="the event's id, as follow queue names it")
    p.add_argument("--json", action="store_true", help="print the event")
    p.set_defaults(func=cmd_follow_take)
    p = fsub.add_parser("mark", parents=[common], help="how the delivery of an event went")
    p.add_argument("id", help="the event's id, as follow queue names it")
    p.add_argument("--as", dest="mark", required=True, choices=MARKS,
                   help="delivered or dropped close it; failed keeps it queued")
    p.add_argument("--why", default="", help="why, in one line (required with failed)")
    p.add_argument("--json", action="store_true", help="print the event")
    p.set_defaults(func=cmd_follow_mark)
    p = fsub.add_parser("wake", parents=[common], help="the line that wakes a session for an event")
    p.add_argument("id", help="the event's id, as follow queue names it")
    p.set_defaults(func=cmd_follow_wake)
    p = fsub.add_parser("checkout", parents=[common],
                        help="the run's repository on this machine, where a new session for it opens")
    p.add_argument("run", help="the run's name")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_follow_checkout)
    p = fsub.add_parser("unsent", parents=[common],
                        help="the Slack notes sessions could not send, not relayed yet")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_follow_unsent)
    p = fsub.add_parser("relayed", parents=[common], help="record that the routine sent an unsent Slack note")
    p.add_argument("run", help="the run's name")
    p.add_argument("note", help="the note's id, as follow unsent names it")
    p.set_defaults(func=cmd_follow_relayed)

    recipe = sub.add_parser("recipe", help="a recipe written for a run: draft, checked, save, fact")
    csub = recipe.add_subparsers(dest="recipe_command_name", required=True)
    p = csub.add_parser("draft", parents=[common], help="keep a new recipe as the run's draft")
    p.add_argument("run", help="the run's name")
    p.add_argument("--name", required=True, help="the recipe's name (its file is <name>.py)")
    p.add_argument("--roles", required=True, help="the recipe's roles, one line per role")
    p.add_argument("--file", required=True, help="the recipe's source (- for stdin)")
    p.add_argument("--test", default="", help="a check file kept beside it as test_<name>.py")
    p.add_argument("--command", dest="recipe_command", default="", metavar="COMMAND",
                   help="the command that will start it, filled in for this run, never with a merge parameter")
    p.add_argument("--json", action="store_true", help="print the draft's paths and hash as JSON")
    p.set_defaults(func=cmd_recipe_draft)
    p = csub.add_parser("checked", parents=[common], help="record the check the draft went through")
    p.add_argument("run", help="the run's name")
    p.add_argument("--command", dest="check_command", required=True, metavar="COMMAND",
                   help="the check, as run")
    p.add_argument("--error", default=None, help="the check failed with this error")
    p.add_argument("--json", action="store_true", help="print the check as JSON")
    p.set_defaults(func=cmd_recipe_checked)
    p = csub.add_parser("save", parents=[common], help="copy the checked draft into the recipe directory")
    p.add_argument("run", help="the run's name")
    p.add_argument("--dir", required=True, help="the directory the dispatch tool reads recipes from")
    p.add_argument("--json", action="store_true", help="print where it was saved as JSON")
    p.set_defaults(func=cmd_recipe_save)
    p = csub.add_parser("fact", parents=[common], help="the trunk-recipe fact the saved recipe carries")
    p.add_argument("run", help="the run's name")
    p.add_argument("--link", required=True, help="the fact's link, /facts/...")
    p.set_defaults(func=cmd_recipe_fact)

    learning = sub.add_parser("learning", help="steer a learning to another fact, or forget it")
    lsub = learning.add_subparsers(dest="learning_command", required=True)
    p = lsub.add_parser("forget", parents=[common],
                        help="forget a learning: its fact becomes deprecated and is no longer read")
    p.add_argument("link", help="the learning's fact link, /facts/...")
    p.add_argument("--run", default="", help="the run the owner asked in, to record it there")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(func=cmd_learning_forget)
    p = lsub.add_parser("steer", parents=[common],
                        help="steer a learning to the fact that replaces it: the old one is superseded")
    p.add_argument("link", help="the learning's fact link, /facts/...")
    p.add_argument("--to", required=True, help="the fact that replaces it, captured first, /facts/...")
    p.add_argument("--run", default="", help="the run the owner asked in, to record it there")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(func=cmd_learning_steer)

    sessions = sub.add_parser("sessions", help="past Claude Code sessions, read on first use: list, extract")
    ssub = sessions.add_subparsers(dest="sessions_command", required=True)
    p = ssub.add_parser("list", help="the sessions first use would read, and what reading them costs")
    p.add_argument("--root", default="", help="the transcripts' directory "
                   "(default: $CLAUDE_CONFIG_DIR/projects, else ~/.claude/projects)")
    p.add_argument("--limit", type=int, default=SESSIONS_LIMIT,
                   help=f"how many of the most recent sessions to read (default {SESSIONS_LIMIT})")
    p.add_argument("--batch-tokens", type=int, default=BATCH_TOKENS,
                   help=f"what one small-model reader is handed, at most (default {BATCH_TOKENS})")
    p.add_argument("--json", action="store_true", help="print one JSON object, with the batches")
    p.set_defaults(func=cmd_sessions_list)
    p = ssub.add_parser("extract", help="the owner's own messages in these sessions, for a reader")
    p.add_argument("paths", nargs="+", help="transcript files, as `sessions list --json` names them")
    p.add_argument("--max-tokens", type=int, default=BATCH_TOKENS,
                   help=f"cut each session past this many tokens (default {BATCH_TOKENS})")
    p.set_defaults(func=cmd_sessions_extract)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
