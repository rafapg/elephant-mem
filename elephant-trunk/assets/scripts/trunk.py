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
    --json              the same, as one JSON object on stdout
  facts                 list the active facts carrying the how-I-work tag plus a
                        trunk area tag, read from knowledge/manifest.jsonl only;
                        exits 1, with `problem` in --json, when elephant.json is
                        present but its trunk.tag cannot be used; --json
                        also names the near misses, facts that would match
                        under another case or split on commas
    --area <tag>        only this area tag (repeatable; default: all three)
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
                        a decision starting merge-level: must read
                        merge-level: manual|automatic (<source>), and a
                        recipe's command, a pending learning or a learning
                        never carries a merge parameter
    [--pending <n>]     with learning or note: settles pending learning n
                        (1-based, in the record's `pending`), as captured
                        (learning) or set aside (note); refuses one settled
  run claim <name> --via <orq|claude-code> --command <c> [--where <w>]
                        before the dispatch command runs: flips an open run to
                        starting under the record's lock, so of two sessions
                        claiming it exactly one wins; refuses a run that is
                        not open (starting or dispatched); via orq, refuses a
                        command whose merge parameter disagrees with the run's
                        last merge-level: decision recorded after its last
                        start and dispatch: decision (any merge parameter
                        when there is none; on-approve only at automatic)
  run dispatch <name> --via <orq|claude-code> --command <c> [--where <w>]
                        [--error <e>]
                        record how the start went, ending the claim: without
                        --error the run becomes dispatched, with it the run is
                        open again for a retry; refuses a run that is not
                        starting (claim it first); when --command is not the
                        claimed one, refuses it via orq and warns via
                        claude-code; a dispatched run refuses another
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

Run records live in <bundle>/state/trunk/runs/<name>.json. Before any write the
script makes sure `state/trunk/` is git-ignored in the bundle (appending it to
the bundle's .gitignore when needed) and, in a git bundle, asks git whether it
is: a record git would commit is never written.

The bundle is resolved exactly as elephant-wiki resolves it, and a bundle that
cannot be found stops with the same guidance.

Pure stdlib, Python 3.10+. Cross-platform (explicit UTF-8 I/O).
"""
import argparse
import atexit
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

POINTER = os.path.expanduser("~/.config/elephant-mem/config.json")

# The how-I-work tag when elephant.json sets none. The area tags are fixed: the
# skill reads the owner's how for each step through one of them.
DEFAULT_TAG = "how-i-work"
AREA_TAGS = ("trunk-study", "trunk-dispatch", "trunk-recipe")
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


def config(bundle):
    tag, source, problem = read_tag(bundle)
    return {"bundle": bundle, "tag": tag, "tag_source": source,
            "area_tags": list(AREA_TAGS), "problem": problem}


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
STATUSES = (STATUS_OPEN, STATUS_STARTING, STATUS_DISPATCHED)
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

# The merge level of a run. The owner's merge preference is computed fresh in
# every session and recorded as a decision of its own prefix; a stored command
# (a recipe's, a fact's) never carries the merge parameter, which the skill
# adds to the start command from this run's level only. A merge parameter in
# any spelling: `merge=on-approve` (after `--set` or `-s`), `--set=merge=pr`,
# `--merge`, `MERGE:pr`. A bare value-less flag is one too, read as unknown. A
# bare `merge` word is one only after `--set`/`-s` or before an `=`: as the
# value of another option (`--branch merge`) it is not.
MERGE_LEVEL_PREFIX = "merge-level:"
MERGE_LEVEL_RE = re.compile(r"^merge-level:[ \t]*(manual|automatic)[ \t]*\((.+)\)[ \t]*$", re.I | re.S)
MERGE_TOKEN_RE = re.compile(r"^(?:-{1,2}set[=:])?-{0,2}merge(?:[ \t]*[=:][ \t]*(.*))?$", re.I | re.S)
MERGE_VALUES = {"manual": "pr", "automatic": "on-approve"}
SET_FLAGS = ("--set", "-set", "-s")
DISPATCH_PREFIX = "dispatch:"


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
        die(f"{what} carries a merge parameter ({command!r}): a stored command never does. "
            f"The merge level is set per run, from the owner's preference and this session; "
            f"the start command gets it at 3c, and `run claim` checks it against the run's "
            f"merge-level: decision")


def _at(item):
    return str(item.get("at") or "") if isinstance(item, dict) else ""


def last_merge_level(rec):
    """`manual` or `automatic` from the run's last merge-level: decision, or
    None. Only a decision recorded after the run's last start (an attempt or
    a claim) and after its last `dispatch:` decision counts: the level is
    stated in the session that starts the run, at 3c, after the owner's word
    to dispatch, so one recorded before a failed start or before a newer
    dispatch word is history from another session."""
    decisions = rec.get("decisions") or []
    cutoff = max([_at(a) for a in rec.get("attempts") or []] + [_at(rec.get("claim"))]
                 + [_at(d) for d in decisions
                    if isinstance(d, dict) and str(d.get("text") or "").strip().lower()
                    .startswith(DISPATCH_PREFIX)] + [""])
    for d in reversed(decisions):
        text = (d.get("text") if isinstance(d, dict) else str(d)) or ""
        if text.strip().lower().startswith(MERGE_LEVEL_PREFIX):
            if _at(d) <= cutoff:
                return None
            m = MERGE_LEVEL_RE.match(text.strip())
            return m.group(1).lower() if m else None
    return None


def merge_param_problem(command, level):
    """Why a dispatch command's merge parameter disagrees with the run's
    merge level, or None when it agrees."""
    values = merge_params(command)
    if not values:
        if level == "automatic":
            return ("the run's merge level in this session is automatic and the command "
                    "carries no merge parameter, so it does not match the level; build the start "
                    "command again from the level, or record the fallback to manual with why")
        return None
    if level is None:
        return ("the command carries a merge parameter and the run records no merge-level: "
                "decision of this session (after its last start and its last dispatch: "
                "decision); the owner states the level in this session, and it is recorded "
                "before the start (merge-level: manual|automatic (<source>))")
    if any(v not in MERGE_VALUES.values() for v in values) or len(set(values)) > 1:
        return (f"the command's merge parameter cannot be read as one of "
                f"{', '.join(sorted(MERGE_VALUES.values()))} ({', '.join(str(v) for v in values)})")
    if values[0] != MERGE_VALUES[level]:
        return (f"the command's merge parameter is {values[0]} and the run's last merge-level: "
                f"decision is {level}, which takes {MERGE_VALUES[level]}")
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
    deadline = time.monotonic() + wait
    while True:
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                die(f"run {name} is being changed by another trunk.py (lock {path}); "
                    f"try again, and remove that file only if no trunk.py is running")
            time.sleep(0.02)

    def release():
        try:
            os.unlink(path)
        except OSError:
            pass
    atexit.register(release)


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
        recs = [r for r in recs if r["status"] != STATUS_DISPATCHED]
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
    if rec["status"] == STATUS_DISPATCHED and field in FROZEN_AFTER_DISPATCH:
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
        if field == "decision" and raw.strip().lower().startswith(MERGE_LEVEL_PREFIX) \
                and not MERGE_LEVEL_RE.match(raw.strip()):
            die("a merge-level: decision reads merge-level: manual|automatic (<source>), "
                "the source being fact, owner in this session, session override or a "
                "fallback with why; nothing was recorded")
        entry = {"at": t, "text": raw.strip()}
        if settles is not None:
            entry["settles"] = settles
        rec.setdefault(APPEND_FIELDS[field], []).append(entry)
    rec["updated"] = t
    write_record(bundle, rec)
    return 0


def _refuse_dispatched(rec):
    if rec["status"] == STATUS_DISPATCHED:
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
            or merge_param_problem(args.dispatch_command, last_merge_level(rec))
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
    if rec["status"] != STATUS_DISPATCHED:
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
    if rec["status"] == STATUS_DISPATCHED and not after_dispatch:
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
    p = sub.add_parser("facts", parents=[common],
                       help="list the owner's how: facts with the how-I-work tag plus a trunk area tag")
    p.add_argument("--area", action="append", choices=AREA_TAGS,
                   help="only this area tag (repeatable; default: all three)")
    p.add_argument("--forgotten", action="store_true",
                   help="the learnings forgotten or steered instead, never read as the owner's how")
    p.add_argument("--json", action="store_true",
                   help="print one JSON object; each fact carries its origin (owner, other, unknown)")
    p.set_defaults(func=cmd_facts)

    run = sub.add_parser("run", help="the run record: new, show, list, set, claim, dispatch, ingested")
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
                   help="the command about to start the work; via orq, its merge parameter must "
                        "agree with the run's last merge-level: decision")
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
