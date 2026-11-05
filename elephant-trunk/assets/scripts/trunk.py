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
                        trunk area tag, read from knowledge/manifest.jsonl only
    --area <tag>        only this area tag (repeatable; default: all three)
    --json              one JSON object on stdout
  run new --topic <t>   start a run record; prints its name
    [--name <n>]        the run's name (default: <date>-<slug of the topic>)
  run show <name>       read a run record back (--json: the record itself)
  run list              the runs, most recent first (--open: not dispatched yet)
  run set <name> <field> (--value <v> | --file <path|->)
                        continue a run: study, brief (text, replaced);
                        approaches (JSON array), recipe (JSON object), replaced;
                        decision, note, learning (text, appended)
  run dispatch <name> --via <orq|claude-code> --command <c> [--where <w>]
                        [--error <e>]
                        record a dispatch attempt; without --error the run
                        becomes dispatched, and a dispatched run refuses another
  run ingested <name> [--commit <sha>]
                        after `ingest` ran over a dispatched run's record:
                        checks no run record entered the bundle's history and
                        records the ingest commit (default: the bundle's HEAD)
  recipe draft <run> --name <n> --roles <r> --file <path|->
                        [--test <path>] [--command <c>]
                        a new recipe written for this run: kept as a draft under
                        state/trunk/recipes/<run>/ and recorded as the run's recipe
  recipe checked <run> --command <c> [--error <e>]
                        record the check the draft went through; a failure keeps
                        the draft and the error, and nothing is dispatched
  recipe save <run> --dir <d>
                        copy the checked draft into the recipe directory, never
                        replacing a recipe already there
  recipe fact <run> --link <l>
                        the trunk-recipe fact the saved recipe was captured with
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
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
    saying why a value present in elephant.json was not used. A missing or
    malformed config never stops the trunk: it falls back to the default and
    says so, the same leniency elephant-wiki shows when it reads hooks."""
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
    if cfg["tag_source"] == "default":
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


def how_facts(bundle, tag, areas=AREA_TAGS):
    """The owner's how: every active fact in knowledge/manifest.jsonl carrying
    `tag` plus at least one of `areas`, in manifest order (most recent first).

    Reads the manifest and nothing else, the way post-produto-slack's
    regras.py reads its `como-trabalhar` rules, and with its rules, so the two
    readers cannot disagree about one fact: `type` is `fact`, the status
    (missing counts as `active`) is `active` once stripped and lowercased, and
    tags match exactly. Returns (facts, skipped): each fact a dict with `path`
    (absolute), `link` (the manifest's `/facts/...`), `areas` (the area tags it
    carries, among `areas`), `desc`, `tags`, `occurred` and `confidence`;
    `skipped` counts manifest lines that are not a usable JSON object. A
    missing manifest raises OSError: build-index writes one on every bundle, so
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
            if str(row.get("status", "active")).strip().lower() != "active":
                continue
            tags = _tags(row.get("tags"))
            hit = [a for a in wanted if a in tags]
            if tag not in tags or not hit:
                continue
            link = str(row.get("path") or "")
            if not link:
                skipped += 1
                continue
            facts.append({
                "path": os.path.join(bundle, "knowledge", *link.lstrip("/").split("/")),
                "link": link,
                "areas": hit,
                "desc": str(row.get("desc", "")),
                "tags": tags,
                "occurred": str(row.get("occurred", "")),
                "confidence": str(row.get("confidence", "")),
            })
    return facts, skipped


def cmd_facts(args):
    bundle = resolve_bundle(args.bundle)
    cfg = config(bundle)
    announce_tag(cfg)
    areas = [a for a in AREA_TAGS if not args.area or a in args.area]
    try:
        facts, skipped = how_facts(bundle, cfg["tag"], areas)
    except OSError:
        manifest = os.path.join(bundle, "knowledge", "manifest.jsonl")
        die(f"cannot read {manifest} — rebuild it with "
            f"python3 {os.path.join(bundle, 'scripts', 'build-index.py')}")
    if skipped:
        note(f"skipped {skipped} unreadable line(s) in knowledge/manifest.jsonl")
    if not facts:
        note(f'no active fact carries "{cfg["tag"]}" plus a trunk area tag ({", ".join(areas)})')
    if args.json:
        print(json.dumps({"bundle": bundle, "tag": cfg["tag"], "tag_source": cfg["tag_source"],
                          "areas": areas, "facts": facts}, ensure_ascii=False))
        return 0
    for f in facts:
        print(f"{','.join(f['areas'])}\t{f['path']}\t{f['desc']}")
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
DISPATCH_VIAS = ("orq", "claude-code")
# What `run set` may change: text replaced, JSON replaced, text appended.
TEXT_FIELDS = ("study", "brief")
JSON_FIELDS = {"approaches": list, "recipe": dict}
APPEND_FIELDS = {"decision": "decisions", "note": "log", "learning": "learnings"}
# After the dispatch the conversation can go on, but what was dispatched stays
# as it was dispatched.
FROZEN_AFTER_DISPATCH = ("study", "approaches", "brief", "recipe")


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
    fd, tmp = tempfile.mkstemp(prefix=".run-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
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
            or rec.get("status") not in (STATUS_OPEN, STATUS_DISPATCHED):
        raise RecordError(f"the run record {path} is not a run record")
    return rec


def load_or_die(bundle, name):
    try:
        return read_record(bundle, name)
    except RecordError as exc:
        die(f"{exc} — start over from the topic with `trunk.py run new --topic ...`")


def new_record(name, topic):
    t = now()
    return {"version": RECORD_VERSION, "name": name, "topic": topic,
            "status": STATUS_OPEN, "created": t, "updated": t,
            "study": None, "approaches": [], "decisions": [], "brief": None,
            "recipe": None, "dispatch": None, "attempts": [], "log": [],
            "ingests": [], "learnings": []}


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
    failed = [a for a in rec.get("attempts", []) if not a.get("ok")]
    if failed and rec["status"] == STATUS_OPEN:
        last = failed[-1]
        print(f"\n## not dispatched\nlast attempt via {last.get('via')} at {last.get('at')} "
              f"failed: {last.get('error')}")
    if rec.get("ingests"):
        print("\n## ingested")
        for i in rec["ingests"]:
            print(f"- {i.get('at')}{', commit ' + i['commit'] if i.get('commit') else ''}")
    if rec.get("learnings"):
        print("\n## learned")
        for item in rec["learnings"]:
            print(f"- {item.get('text') if isinstance(item, dict) else item}")
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
        recs = [r for r in recs if r["status"] == STATUS_OPEN]
    if args.json:
        print(json.dumps({"bundle": bundle, "runs": [summary(r) for r in recs]}, ensure_ascii=False))
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
    rec = load_or_die(bundle, check_name(args.name))
    field, raw = args.field, _value(args)
    if rec["status"] == STATUS_DISPATCHED and field in FROZEN_AFTER_DISPATCH:
        die(f"run {rec['name']} was already dispatched; its {field} stays as dispatched "
            f"(add a decision or a note instead)")
    t = now()
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
        rec[field] = value
    else:
        if not raw.strip():
            die(f"an empty {field} adds nothing")
        rec.setdefault(APPEND_FIELDS[field], []).append({"at": t, "text": raw.strip()})
    rec["updated"] = t
    write_record(bundle, rec)
    return 0


def cmd_run_dispatch(args):
    bundle = resolve_bundle(args.bundle)
    rec = load_or_die(bundle, check_name(args.name))
    if rec["status"] == STATUS_DISPATCHED:
        d = rec.get("dispatch") or {}
        die(f"run {rec['name']} was already dispatched via {d.get('via')} at {d.get('at')}"
            f"{' (' + d['where'] + ')' if d.get('where') else ''}; it is never dispatched again")
    if args.via == "orq":
        problem = written_recipe_problem(rec.get("recipe"))
        if problem:
            die(f"nothing is dispatched: {problem}")
    t = now()
    attempt = {"at": t, "via": args.via, "command": args.dispatch_command, "where": args.where or None,
               "ok": args.error is None, "error": args.error}
    rec.setdefault("attempts", []).append(attempt)
    if attempt["ok"]:
        rec["status"] = STATUS_DISPATCHED
        rec["dispatch"] = {k: attempt[k] for k in ("at", "via", "command", "where")}
    rec["updated"] = t
    write_record(bundle, rec)
    if args.json:
        print(json.dumps(summary(rec), ensure_ascii=False))
    else:
        print(f"run {rec['name']}: {'dispatched' if attempt['ok'] else 'not dispatched'}")
    return 0


def _git(bundle, *args):
    """A git command in the bundle: (returncode, stdout), or None when git is
    missing or cannot run."""
    git = shutil.which("git")
    if not git:
        return None
    try:
        r = subprocess.run([git, "-C", bundle, *args], capture_output=True, text=True)
    except OSError:
        return None
    return r.returncode, r.stdout.strip()


def cmd_run_ingested(args):
    """Record that `ingest` ran over a dispatched run's record, after checking
    the raw record stayed out of the bundle's history: nothing under
    state/trunk/ is tracked, and the ingest commit touched nothing there."""
    bundle = resolve_bundle(args.bundle)
    rec = load_or_die(bundle, check_name(args.name))
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
    rec = load_or_die(bundle, check_name(args.run))
    if rec["status"] == STATUS_DISPATCHED and not after_dispatch:
        die(f"run {rec['name']} was already dispatched; its recipe stays as dispatched")
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
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_facts)

    run = sub.add_parser("run", help="the run record: new, show, list, set, dispatch, ingested")
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
    p.add_argument("--open", action="store_true", help="only runs not dispatched yet")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.set_defaults(func=cmd_run_list)
    p = rsub.add_parser("set", parents=[common], help="continue a run: set or add one field")
    p.add_argument("name")
    p.add_argument("field", choices=[*TEXT_FIELDS, *JSON_FIELDS, *APPEND_FIELDS])
    p.add_argument("--value", default=None, help="the value")
    p.add_argument("--file", default=None, help="read the value from this file (- for stdin)")
    p.set_defaults(func=cmd_run_set)
    p = rsub.add_parser("dispatch", parents=[common], help="record a dispatch attempt")
    p.add_argument("name")
    p.add_argument("--via", required=True, choices=DISPATCH_VIAS)
    p.add_argument("--command", dest="dispatch_command", required=True,
                   help="the command that started the work")
    p.add_argument("--where", default="", help="where the work runs (orq team, workspace, session)")
    p.add_argument("--error", default=None, help="the attempt failed with this error")
    p.add_argument("--json", action="store_true", help="print the run's summary as JSON")
    p.set_defaults(func=cmd_run_dispatch)
    p = rsub.add_parser("ingested", parents=[common],
                        help="record that ingest ran over a dispatched run's record")
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
                   help="the command that will start it, filled in for this run")
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
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
