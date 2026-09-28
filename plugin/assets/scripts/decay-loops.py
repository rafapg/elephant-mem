#!/usr/bin/env python3
"""Decay stale or out-of-scope `open` loops into `status: expired`.

Philosophy (owner-approved): loops are noise that, when it keeps recurring,
earns the right to stay alive — otherwise it should decay automatically.
Re-mention resets the clock through `updated:`, written by the ingest core (the
plugin's `skills/ingest/procedure.md`, steps 2 and 4, written at step 7) on
every ingest path, and by the review-gate snooze and claim of this script's own
procedure. This script only reads the signal; it never itself decides what
counts as re-mention.

Candidate = `status: open` AND its last-activity date (the max of
`updated`/`opened`/`created`, whichever are present, and the date
`state/recall.json` last records the loop as cited by an answer) is
`elephant.json` -> `decay.loop_expiry_days` days back or more (default 30; the
comparison is `>=`, so a loop exactly that old expires — same defensive
fallback pattern as build-index.py's `hub_max_facts`: missing file, missing
key, or malformed JSON all fall back to the default instead of crashing, and a
value that is not a positive whole number does too, with a note on stderr). A
loop whose `updated:` is present but reads as no date is not a candidate, with
a note naming it: read past, it would age from `opened`.

The citation date is the fourth date and nothing more. `updated` says a source
re-raised the loop; a citation says the owner's own answers still reach for it,
which is the same claim from the other side. It only ever protects: a loop with
no citation decays on its file dates exactly as it did before recall existed, so
an absent, empty or malformed `state/recall.json` collapses this script to its
previous behavior rather than to a crash.

**Out of scope is the other kind of candidate.** A `status: open` loop whose
`owner`, `owed_to` and `entities` all leave out the bundle owner
(`elephant.json` -> `owner.slug`) is a commitment between other people, which
the loop lane does not track. It is a candidate at any age, listed ahead of the
stale ones. The test reads no date, the citation included: a recent `updated:`
or a recent answer citing it does not keep a third-party loop in the lane.
Links are compared by slug (last path segment, `.md` stripped, lowercased,
quotes removed), with the same `slug()` `close-loops.py` uses, so a hand-written
bare slug still counts as naming the owner. Expiry is the irreversible side, and
the permissive comparison is the safe one. Only `owner.slug` is read, never
`owner.name`, since a name is not an entity link. The rule is skipped with one
note on stderr, rather than expiring every loop as naming nobody, in three
cases: there is no `owner.slug`; it names no entity file under
`knowledge/entities/` (`rename-entity.py` rewrites the loops' links and never
`elephant.json`, so a renamed or merged owner leaves a stale slug behind); or no
open loop names the owner's own entity at all. And a loop is only out of scope
on a positive reading: an entity link to the owner anywhere in its frontmatter,
the owner's slug as a token anywhere in those three fields, or a link to another
entity carrying one of the owner's names (a duplicate of the owner) keeps it in.

Default mode is DRY-RUN: prints one candidate per line (bundle-absolute path
and its label: out of scope, or the age in days) plus a trailing count split by
kind, and changes nothing on disk. `--apply` flips `status: open` ->
`status: expired`, stamps an `expired: YYYY-MM-DD` field right after the status
line, and appends a `**Resolution:**` paragraph to the body — it never deletes
a file and never touches `done` / `dropped` / already-`expired` loops (they're
excluded by the `status: open` filter before any file is opened for writing).

**The resolution is prose in the body, the same shape `close-loops` writes**
(see `../skills/close-loops/procedure.md` -> step 3): a `**Resolution:**`
paragraph whose first sentence stands alone, because that first sentence is all
`tracking/resolved-loops.md` prints. Never a frontmatter field — a sentence of
judgment carries `: ` and sometimes ` #`, which break or silently truncate an
unquoted YAML value. Decay's says what a closure's cannot: that nothing
happened, or that the loop was never the owner's. It is generated, so it is
written in English rather than in the bundle's `knowledge_language`; the dates
and the paths in it are the content, and its owner can rewrite the sentence.

`--except <link>` (repeatable, a bundle-absolute loop path) keeps the named
loops out of this run, in the dry run and on `--apply`: it is how the
interactive review gate keeps every candidate the owner rejected out of the
`--apply` re-scan, which would otherwise list an unclaimed out-of-scope loop
again, and a snoozed stale one again if its `updated:` bump went wrong. A
link that names no loop file, or a loop that is not open, ends the run with
exit 2 before anything is written; a link to an open loop that is no longer a
candidate prints a note.

`--skip-sweep` is a deprecated no-op. This script no longer reads
`state/closure-sweep.json`; the flag is still accepted so a schedule or a habit
that passes it does not make argparse exit 2 and quietly stop expiry.

Exit code is 0 whenever the script completed a run, whether or not it found
candidates — non-zero only on a hard, unexpected error, or 2 when an
`--except` link names no loop file or a loop that is not open, checked
before anything is scanned or written: a typo there would otherwise let the
loop it meant to keep expire.
After `--apply` the caller is expected to run `build-index.py` (this script
does not — it only touches loop files).
"""
import argparse
import datetime
import importlib.util
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

DEFAULT_EXPIRY_DAYS = 30

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# The three link lists the scope test reads. `owed_to` is absent from every
# loop written before the field existed, and list_field() reads a missing line
# as the empty list, so such a loop is decided on `owner` and `entities` alone.
SCOPE_FIELDS = ("owner", "owed_to", "entities")


def loop_expiry_days():
    """Read `decay.loop_expiry_days` from elephant.json. Defensive by design
    (mirrors ingest-audio.py's config reader / build-index.py's hub_max_facts):
    a missing file, missing key, non-dict `decay`, or malformed JSON all fall
    back to DEFAULT_EXPIRY_DAYS instead of crashing.

    A key that is present but not a positive whole number falls back too, and
    says so on stderr, since its owner meant some window and is not getting it.
    `true` is the case that needed a rule of its own: JSON's boolean is a
    Python `int`, so it passed as a 1-day window and every loop quiet since
    yesterday was a candidate. `"60"` and `60.0` are not whole numbers either;
    they take the default rather than a guess at what was meant."""
    try:
        with open(BUNDLE / "elephant.json", encoding="utf-8") as fh:
            data = json.load(fh)
        decay_cfg = data.get("decay")
        if isinstance(decay_cfg, dict) and "loop_expiry_days" in decay_cfg:
            v = decay_cfg["loop_expiry_days"]
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                return v
            print(f"note: elephant.json -> decay.loop_expiry_days is {json.dumps(v)}, "
                  f"not a positive whole number of days, so the default "
                  f"{DEFAULT_EXPIRY_DAYS} is used this run.", file=sys.stderr)
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
        # A quote opens a quoted item only where an item starts, after the `[`
        # or a `,`; inside a plain item it is content, so the apostrophe of
        # `[O'Brien, me]` does not swallow the `]`. An approximation of YAML's
        # flow rule: a node may also start after a tag or anchor (`!!str 'a'`,
        # `&x 'a'`) or after a flow mapping's `:`, and those are not handled.
        if c in "\"'" and v[:i].rstrip()[-1:] in ("[", ","):
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


def _split_items(inner):
    """The items of an inline list, given the text between its `[` and `]`,
    split at the commas that sit outside a quoted item and stripped, empty ones
    dropped. As in _closing_bracket(), a quote opens a quoted item only where
    an item starts, so `"Doe, Jane"` is one item while the apostrophe of
    `O'Neil, Kit` is content; a quote that never closes is content too, so
    the rest of the list still splits. The items keep their quotes, for the
    caller to unquote. Same function in decay-loops.py, close-loops.py,
    build-index.py and validate-okf.py."""
    items, start, i, n = [], 0, 0, len(inner)
    while i < n:
        c = inner[i]
        if c in "\"'" and not inner[start:i].strip():
            end = _closing_quote(inner[i:])
            if end >= 0:
                i += end + 1
                continue
        if c == ",":
            items.append(inner[start:i])
            start = i + 1
        i += 1
    items.append(inner[start:])
    return [x.strip() for x in items if x.strip()]


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

    open-loop.md ships the status field with its vocabulary glued on as a
    comment, `status: open          # open | done | dropped | expired`, and with
    it there `field(block, "status") != "open"` was true for every
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


def loop_status(block):
    """A loop's status, normalized: unquoted, stripped and lowercased,
    defaulting to `open`.

    THE single rule that decides what decay may look at, and deliberately the
    same one build-index.py's loop_status() applies to the same field, so the
    board and this script can never disagree about one loop. A loop carrying
    `status: Open` (close-loops/procedure.md has the model editing that field by
    hand) read as open on the board and as not-open here: it sat on the board as
    a live commitment forever, and decay never so much as considered it.

    The unquoting is this reader's own business. field() here returns the raw
    scalar, quotes and all, where close-loops.py's namesake unquotes for its
    caller; `status: "open"` is a legal spelling of the same value and must not
    survive a decay run for the sake of two characters.
    """
    raw = field(block, "status") or "open"
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1]
    return raw.strip().lower()


def unquote(s):
    """Unwrap a quoted scalar, undoing the two escapes quoting actually
    produces: `\\"` and `\\\\` inside double quotes, `''` inside single quotes.
    Mirrors close-loops.py's function of the same name. A link left wrapped in
    literal quotes would name no slug, and here that reads as a loop naming
    nobody, which the scope test expires."""
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


def _cut_line_comment(v):
    """One physical line of an inline list that wraps, without its YAML comment.

    strip_comment() leaves a comment on a line whose `[` has not closed yet,
    because it looks for the comment outside the list and that line has no
    outside. A comment still ends at the end of its own line, list or not, so
    this cuts at the first `#` that starts the line or follows a space, skipping
    quoted items (`"a #b"` is content). Brackets are not tracked: on a wrapped
    line they no longer delimit where a comment may sit. Mirrors close-loops.py's
    function of the same name."""
    v = v.strip()
    i, n = 0, len(v)
    while i < n:
        c = v[i]
        # As in _closing_bracket(), a quote opens a quoted item only where an
        # item starts: the start of the line, a block item's `-`, or after a
        # `[` or a `,`. `O'Neil,  # x` is a plain item and then a comment.
        prev = v[:i].rstrip()
        if c in "\"'" and (prev in ("", "-") or prev[-1] in "[,"):
            end = _closing_quote(v[i:])
            if end < 0:
                return v
            i += end + 1
            continue
        if c == "#" and (i == 0 or v[i - 1] in " \t"):
            return v[:i].rstrip()
        i += 1
    return v


# A top-level `key:` line, which is where a wrapped inline list that never
# closed has certainly ended.
TOP_KEY = re.compile(r"^[A-Za-z_][\w-]*[ \t]*:(?:\s|$)")


def list_field(block, key):
    """Values of a list-valued frontmatter field: `key: [a, b]`, or the block
    sequence spelling, or a bare scalar read as a one-item list. A missing line
    is the empty list. Mirrors close-loops.py's function of the same name.

    Every shape valid YAML allows for these lists is read, because here a
    misread is not a lost signal: it reads the owner out of the loop, and the
    scope test then expires it. So `owner :` (space before the colon) is the
    same key; a block sequence may sit at column 0 (`owner:` then `- /x.md`,
    PyYAML's own `safe_dump` style) and may carry comment lines between its
    items; and an inline list may wrap across lines, read until its `]`.

    The items are split by _split_items(), which honors quoting, as
    build-index.py's fallback parser does. A naive comma split was once safe
    here, when every value read was a bundle-absolute link or a slug, neither
    of which can carry a comma. decay-loops.py's _names() also reads `aliases`
    through this, and an alias can: `aliases: ["Doe, Jane"]` came back as
    `"Doe` and `Jane"`, the duplicate titled `Doe, Jane` went undetected, and
    the loop linking it expired as out of scope.
    """
    lines = block.splitlines()
    head = re.compile(rf"^{re.escape(key)}[ \t]*:(.*)$")
    for i, ln in enumerate(lines):
        m = head.match(ln)
        if not m:
            continue
        val = strip_comment(m.group(1))
        if val.startswith("["):
            if _closing_bracket(val) < 0:
                val = _cut_line_comment(m.group(1))
            j = i + 1
            while _closing_bracket(val) < 0 and j < len(lines) and not TOP_KEY.match(lines[j]):
                val = val + " " + _cut_line_comment(lines[j])
                j += 1
            end = _closing_bracket(val)
            inner = (val[1:end] if end > 0 else val[1:]).strip()
            return [unquote(x) for x in _split_items(inner)]
        if val:
            return [unquote(val)]
        items = []
        for nxt in lines[i + 1:]:
            stripped = nxt.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- "):
                items.append(unquote(strip_comment(stripped[2:])))
                continue
            break
        return items
    return []


def slug(link):
    """The entity slug a bundle-absolute link names. Compared by slug rather
    than by path so `/entities/person/x.md` and a hand-written `x` are the same
    entity — the kind directory is a filing decision, not identity. Mirrors
    close-loops.py's function of the same name."""
    s = str(link or "").strip().replace("\\", "/").strip("\"'")
    if not s:
        return None
    s = s.rsplit("/", 1)[-1]
    if s.endswith(".md"):
        s = s[:-3]
    return s.strip().lower() or None


def slugs(links):
    out = []
    for link in links:
        s = slug(link)
        if s and s not in out:
            out.append(s)
    return out


def owner_slug():
    """The bundle owner's entity slug, from `elephant.json` -> `owner.slug`
    through slug(), or None. Never raises.

    Only `owner.slug` is read. close-loops.py's namesake falls back to
    `owner.name`, which costs it at worst one ranking filter; here the value
    decides an irreversible expiry, and a name is not an entity link. None (a
    missing file, malformed JSON, a non-dict `owner`, an absent, empty or
    non-string `slug`) switches the scope rule off for the run instead of
    reading every loop as naming nobody.
    """
    try:
        with open(BUNDLE / "elephant.json", encoding="utf-8") as fh:
            data = json.load(fh)
        owner = data.get("owner") if isinstance(data, dict) else None
        if isinstance(owner, dict):
            value = owner.get("slug")
            if isinstance(value, str):
                return slug(value)
    except Exception:  # noqa: BLE001, a missing config only skips one rule
        pass
    return None


def owner_entity_exists(owner):
    """True iff some `knowledge/entities/<kind>/<owner>.md` exists, compared
    case-insensitively on the file's stem.

    `owner.slug` present is not `owner.slug` right. `rename-entity.py` rewrites
    every link to a renamed or merged entity across `knowledge/` and never
    touches `elephant.json`, so after the owner's own entity is renamed every
    loop names the new slug while the config still names the old one. Read as
    is, that config makes every open loop out of scope and the next unattended
    run expires the whole lane. A slug naming no entity is treated as no slug.
    """
    root = KNOWLEDGE / "entities"
    if not root.is_dir():
        return False
    return any(p.stem.lower() == owner for p in root.rglob("*.md"))


BLOCK_SCALAR = re.compile(r"^[|>][-+0-9]*$")


def _title(block):
    """The entity's `title`, with a block scalar (`title: >-` then indented
    lines) read as its lines joined by one space rather than as the bare
    indicator: two unrelated entities whose titles are both folded would
    otherwise share the "name" `>-` and read as duplicates of each other."""
    value = field(block, "title")
    if value is None or not BLOCK_SCALAR.match(value):
        return value
    lines = block.splitlines()
    head = re.compile(r"^title[ \t]*:")
    for i, ln in enumerate(lines):
        if head.match(ln):
            body = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt[:1].isspace():
                    break
                body.append(nxt.strip())
            return " ".join(x for x in body if x) or None
    return None


def _norm_name(name):
    """A name as the duplicate test compares it: unquoted, lowercased, with
    `-`, `_` and runs of whitespace read as one space."""
    return " ".join(re.sub(r"[-_]", " ", unquote(name.strip())).lower().split())


def _names(block):
    """The names an entity's frontmatter gives it, normalized (_norm_name()):
    its `title` and every `aliases` item."""
    raw = [_title(block) or ""] + list_field(block, "aliases")
    return {n for n in (_norm_name(x) for x in raw) if n}


def owner_duplicates(owner):
    """Slugs of the other entity files that carry one of the owner entity's
    names (its slug, title or an alias) as their own slug, title or alias.

    The "no open loop names the owner" guard is all or nothing. A lane where
    only *some* loops link a duplicate of the owner's entity (an ingest that
    resolved a nickname to a new entity file instead of the owner) passes it, and the
    loops linking the duplicate would expire as out of scope. A loop linking
    one of these is read as naming the owner instead, which only ever keeps a
    loop in the lane, on the 30-day clock. `*.facts-archive.md` and the other
    dotted stems are not entities and are skipped, and so is a directory
    whose name ends in `.md`.

    Never raises, and never loses the whole scan to one file: an entity file
    that cannot be read is skipped on its own, with one stderr note counting
    them, since a duplicate among them goes undetected and a loop linking it
    can then expire as out of scope."""
    root = KNOWLEDGE / "entities"
    try:
        files = sorted(p for p in root.rglob("*.md") if "." not in p.stem)
    except Exception as exc:  # noqa: BLE001
        print(f"note: knowledge/entities/ could not be listed ({exc}), so no "
              "duplicate of the owner's entity is detected this run.", file=sys.stderr)
        return []
    own, others, skipped = set(), [], []
    for p in files:
        if p.is_dir():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001, one unreadable file skips only itself
            skipped.append(p)
            continue
        m = FM.match(text)
        names = _names(m.group(1)) if m else set()
        names.add(_norm_name(p.stem))
        if p.stem.lower() == owner:
            own |= names
        else:
            others.append((p.stem.lower(), names))
    if skipped:
        print(f"note: {len(skipped)} entity file(s) could not be read (first: "
              f"/{skipped[0].relative_to(KNOWLEDGE).as_posix()}), so a duplicate of "
              "the owner's entity among them is not detected this run.", file=sys.stderr)
    own.add(_norm_name(owner))
    return sorted({stem for stem, names in others if names & own})


def owner_link_pattern(owner):
    """An entity link to the owner, `.../entities/<kind>/<owner>[.md]`, as it
    may appear anywhere in raw frontmatter text, a markdown link's `(...)`
    included: `[Me](/entities/person/me.md)` ends the link on a `)`."""
    return re.compile(
        rf"entities/[^/\s\"'\[\],]+/{re.escape(owner)}(?:\.md)?(?=[\s\]\"',#)]|$)",
        re.IGNORECASE | re.MULTILINE,
    )


def scope_text(block):
    """The raw text of the `owner`, `owed_to` and `entities` values, each from
    the text after its key's colon up to the next top-level key, joined, with
    each line's comment removed (the template glues a sentence of prose to
    each of these lines)."""
    keys = re.compile(rf"^(?:{'|'.join(SCOPE_FIELDS)})[ \t]*:(.*)$")
    out, on = [], False
    for ln in block.splitlines():
        m = keys.match(ln)
        if m:
            on = True
            out.append(_cut_line_comment(m.group(1)))
        elif TOP_KEY.match(ln):
            on = False
        elif on:
            out.append(_cut_line_comment(ln))
    return "\n".join(out)


def in_scope(block, owner, also=()):
    """True iff the owner's slug is among the slugs of any of `owner`,
    `owed_to`, `entities`, or an entity link to the owner appears anywhere in
    the frontmatter, or the owner's slug appears as a whole token anywhere in
    the raw text of those three fields. `also` holds more slugs read as the
    owner's (owner_duplicates()). `owner` must not be None: the caller skips
    the scope rule entirely when there is no owner to test for.

    The second and third tests are a floor under the parser. Out of scope is
    only ever declared on a positive reading that the owner is absent, since
    the expiry it leads to is final: a spelling list_field() does not know (a
    YAML tag, an anchor, a markdown link, a wrapped list whose first line
    carries a comment, a shape nobody has written yet) keeps the loop in the
    lane, where the 30-day clock still reaches it, instead of expiring it the
    day it was opened. The token test reads only the three fields, never the
    description, where a short slug like `me` is an ordinary word."""
    raw = scope_text(block)
    for name in (owner, *also):
        if any(name in slugs(list_field(block, key)) for key in SCOPE_FIELDS):
            return True
        if owner_link_pattern(name).search(block):
            return True
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", raw, re.IGNORECASE):
            return True
    return False


def recall_lookup():
    """A `bundle-absolute path -> ISO date last cited` callable over
    `state/recall.json`, or one that answers None for every path.

    The sibling `recall.py` is imported by its path rather than by name: this
    script is also loaded in-process by the suites, where `scripts/` is not on
    `sys.path`. The record is read once here and the per-loop question is then
    a dict lookup — the whole reason `roll` builds a fixed-size pyramid instead
    of leaving decay to rescan the log 1784 times.

    The import is deliberately soft. `recall.py` reaches an installed bundle
    through `update`'s `scripts/` re-sync, so a bundle that has the decay script
    but not yet its sibling must still decay; it simply decays on file dates
    alone, which is what it did before recall existed. `recall.load()` already
    absorbs the absent, empty and malformed record the same way.
    """
    script = Path(__file__).resolve().parent / "recall.py"
    if not script.is_file():
        return lambda link: None
    try:
        spec = importlib.util.spec_from_file_location("_decay_recall", script)
        if spec is None or spec.loader is None:
            raise ImportError("no loader for scripts/recall.py")
        recall = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recall)
        data = recall.load()
    except Exception as exc:  # noqa: BLE001
        print(
            f"warning: scripts/recall.py did not load ({exc}) — scanning on the "
            "loop files' own dates only. Citations cannot protect a loop this run.",
            file=sys.stderr,
        )
        return lambda link: None
    return lambda link: recall.last_cited(data, link)


def field_values(block, key):
    """Every `key: value` scalar in a frontmatter block, in file order, each
    without its trailing comment and its quotes. A blank value, `""`, `null`
    and `~` are no value and are left out."""
    out = []
    for m in re.finditer(rf"^{re.escape(key)}[ \t]*:[ \t]*(.*)$", block, re.MULTILINE):
        v = unquote(strip_comment(m.group(1))).strip()
        if v and v.lower() not in ("null", "~"):
            out.append(v)
    return out


def parse_date(v):
    m = DATE.search(v or "")
    if not m:
        return None
    try:
        return datetime.date.fromisoformat(m.group(0))
    except ValueError:
        return None


def unreadable_updated(block):
    """The first `updated:` value that is present but reads as no date
    (`2026-9-25`, `25/09/2026`, `2026-13-01`), or None when every one parses.

    `updated:` is the one date a model rewrites over a loop's life (every
    ingest bump, the gate's snooze and claim), so it is the one a slip lands
    in. Skipped as if absent, the loop fell back to `opened`/`created` and
    expired on the next run as silent since the day it was opened, the loop
    that had just been re-raised or snoozed."""
    for v in field_values(block, "updated"):
        if parse_date(v) is None:
            return v
    return None


def last_activity(block, cited=None):
    """Max of `updated`/`opened`/`created` and `cited` (whichever parse as a
    date), or None if none of the four are present/parseable — treated as
    "can't tell, not a candidate" rather than an error.

    Also None when an `updated:` line is present but unreadable
    (unreadable_updated()): a re-mention nobody can date is still a re-mention,
    and reading past it is the destructive side. Every line of each key is
    read, so a bump appended as a second `updated:` rather than edited in place
    counts; the max is the same whichever line is newer.

    `cited` is the ISO date `state/recall.json` holds for this loop's
    bundle-absolute path, from `recall.py`'s `last_cited()`. Passing None is
    the whole of the degraded path: no record, no entry for this loop, or no
    `recall.py` at all all arrive here as None and leave the three file dates
    deciding on their own.
    """
    if unreadable_updated(block) is not None:
        return None
    dates = []
    for key in ("updated", "opened", "created"):
        for v in field_values(block, key):
            d = parse_date(v)
            if d is not None:
                dates.append(d)
    if cited:
        m = DATE.search(cited)
        if m:
            try:
                dates.append(datetime.date.fromisoformat(m.group(0)))
            except ValueError:
                pass
    return max(dates) if dates else None


def bundle_link(path):
    return "/" + str(path.relative_to(KNOWLEDGE)).replace("\\", "/")


def loop_files():
    if not LOOPS_DIR.is_dir():
        print(f"note: {LOOPS_DIR} doesn't exist — nothing to decay", file=sys.stderr)
        return []
    return sorted(p for p in LOOPS_DIR.iterdir() if p.suffix == ".md")


# The `status: open` line as the writer must match it: exactly the spellings
# loop_status() reads as open, because a loop this script accepts as a candidate
# has to be one it can also rewrite. Group 1 keeps the key, the spacing and an
# opening quote; everything after `open` (a closing quote, the template's
# `# open | done | dropped | expired` comment) is left where it is.
OPEN_LINE = re.compile(r"^(status:\s*[\"']?)open\b", re.IGNORECASE)


def expire_block(block, expired_date):
    """Rewrite a frontmatter block's `status: open` line to `status: expired`
    and stamp `expired: <date>` right after it (updating it in place if a
    stray `expired:` line already exists). Returns the new block, or None if
    the block has no `status: open` line (caller should skip the file).

    Matched through OPEN_LINE, so `status: Open` and `status: "open"` are
    rewritten too. Reading a spelling the writer then refuses would be worse
    than not reading it at all: the loop would be named as a candidate on every
    dry run and skipped with a warning on every `--apply`.
    """
    lines = block.splitlines()
    status_idx = next(
        (i for i, ln in enumerate(lines) if OPEN_LINE.match(ln)), None
    )
    if status_idx is None:
        return None
    lines[status_idx] = OPEN_LINE.sub(r"\1expired", lines[status_idx], count=1)
    expired_idx = next((i for i, ln in enumerate(lines) if re.match(r"^expired:\s*", ln)), None)
    if expired_idx is not None:
        lines[expired_idx] = f"expired: {expired_date}"
    else:
        lines.insert(status_idx + 1, f"expired: {expired_date}")
    return "\n".join(lines)


def resolution_paragraph(kind, age_days, activity, expiry_days, today, owner=None):
    """The `**Resolution:**` paragraph decay appends when it expires a loop,
    in one of two shapes: `kind` is `"stale"` or `"out-of-scope"`.

    Same shape as the one `close-loops` writes by hand: a body paragraph, two
    to four sentences, whose **first sentence stands alone**. That sentence,
    and nothing else from here, is what `tracking/resolved-loops.md` prints
    next to the date and the outcome, so it names the silence or the scope
    verdict in full rather than opening with "this one went quiet".

    **Every claim here is window-relative, because decay checks nothing wider.**
    The stale sentence used to assert absolutes it had no standing for: "no
    answer cited it" is false whenever recall holds a citation older than the
    window, and "no later source re-raised it" likewise whenever a source
    bumped `updated:` longer ago than the window. What decay can actually stand
    behind is that nothing has touched the loop since `activity`, which is
    exactly what the stale shape says, and it says the expiry is no verdict on
    the commitment.

    The out-of-scope shape names no age and no activity date, because the scope
    test reads no date (a loop with no parseable date at all is still such a
    candidate). What it names is the owner link the loop left out, `owner`
    being the slug read from `elephant.json`.
    """
    if kind == "out-of-scope":
        return (
            f"**Resolution:** Expired on {today} as out of scope: a third-party "
            f"commitment, with the bundle owner (`/entities/person/{owner}.md`) "
            "in none of its owner, owed_to or entities. The loop lane tracks "
            "only what the owner owes or is owed; a commitment between other "
            "people belongs in the fact lane, where briefing and query still "
            "reach it. Expiry here is a scope verdict, not a verdict on the "
            "commitment."
        )
    return (
        f"**Resolution:** Expired on {today} after {age_days} days of silence: "
        f"nothing re-raised or cited it after {activity}. Its last activity was "
        f"{activity}, at or past the {expiry_days}-day window "
        "`decay.loop_expiry_days` sets in `elephant.json`. Expiry states "
        "silence, not a verdict on the commitment: closure by evidence would "
        "have been written here by an ingest or by `close-loops` instead."
    )


def append_resolution(text, paragraph):
    """`text` with `paragraph` as its last body paragraph, one blank line after
    what was there and a single trailing newline.

    End of body is where the template puts `**Closure signal:**` (and where a
    refined loop keeps its `**Closure signal history:**` right after it), so
    appending here lands the resolution after both, the placement
    `close-loops`'s procedure specifies for the paragraph it writes by hand.
    """
    return text.rstrip("\n") + "\n\n" + paragraph + "\n"


def find_candidates(expiry_days, owner):
    """Every `status: open` loop decay may expire, each labelled with its
    `kind`: `"out-of-scope"` or `"stale"`.

    Out of scope is tested first, and only when `owner` is not None: the
    owner's slug in none of `owner`, `owed_to`, `entities`. It reads no date
    and no citation, so such a loop is a candidate at any age, and a loop that
    is both out of scope and stale is listed once, as out of scope.

    The stale test is unchanged from before the scope rule: `activity > cutoff`
    skips, so a loop whose last activity is *exactly* `expiry_days` days old is
    a candidate (the boundary is `>=`, which every message in this script says
    out loud), and a loop with no parseable date at all is not one. `activity`
    is citation-inclusive, and the age, the report lines and the resolution are
    all measured from it.

    Sorted out of scope first, by path, then stale oldest first, so the dry run
    and the review batches group the two kinds.

    **When no open loop names the owner at all, the rule is skipped** for the
    run, with one note on stderr. A lane where every open loop is someone
    else's says far more often that `owner.slug` names the wrong entity (a
    duplicate the loops link instead, a typo that happens to name another
    file) than that the owner has no commitment left, and expiring all of it
    on that reading cannot be undone. Skipped, those loops still decay on the
    stale test.

    **A partial duplicate is covered loop by loop** (owner_duplicates()): a
    loop linking another entity that carries one of the owner's names is read
    as naming the owner, with one note on stderr naming those entities. A
    duplicate never counts toward the guard above: it can only keep a loop in
    the lane, never switch the rule on.

    A loop whose `updated:` is present but no date is not a stale candidate,
    with one note on stderr naming it (unreadable_updated()).
    """
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=expiry_days)
    cited_on = recall_lookup()
    opened = []
    for path in loop_files():
        text = path.read_text(encoding="utf-8")
        m = FM.match(text)
        if not m:
            continue
        if loop_status(m.group(1)) != "open":
            continue
        opened.append((path, text, m))
    also = owner_duplicates(owner) if owner is not None and opened else []
    if also:
        print("note: " + ", ".join(f"/entities/*/{s}.md" for s in also)
              + f" carry one of the owner's names (title or alias of "
              f"/entities/person/{owner}.md) without being that entity, so a loop "
              f"linking them is read as naming the owner and does not expire as out "
              f"of scope. If they are duplicates of the owner, merge them with "
              f"rename-entity.py --merge.", file=sys.stderr)
    # The guard reads the owner's own slug only, never `also`: a duplicate
    # can keep its own loop in the lane, but it must not be what switches the
    # rule on. An `owner.slug` naming the wrong entity, whose title a third
    # party carries as an alias, would otherwise arm the rule on that third
    # party's loop and expire every loop the owner really owes.
    if owner is not None and opened and not any(
            in_scope(m.group(1), owner) for _p, _t, m in opened):
        print(f"note: no open loop names the owner (/entities/person/{owner}.md) in "
              f"owner, owed_to or entities, so the out-of-scope rule is skipped this "
              f"run rather than expiring all {len(opened)}; check elephant.json -> "
              f"owner.slug. Only loops stale for {expiry_days}+ days are candidates.",
              file=sys.stderr)
        owner = None
    out_of_scope, stale = [], []
    for path, text, m in opened:
        block = m.group(1)
        if owner is not None and not in_scope(block, owner, also):
            out_of_scope.append({"path": path, "text": text, "match": m,
                                 "kind": "out-of-scope", "age": None,
                                 "activity": None})
            continue
        activity = last_activity(block, cited_on(bundle_link(path)))
        if activity is None:
            bad = unreadable_updated(block)
            if bad is not None:
                print(f"note: {bundle_link(path)} has `updated: {bad}`, which is no "
                      "YYYY-MM-DD date, so it is not a stale candidate until that "
                      "line is fixed.", file=sys.stderr)
            continue
        if activity > cutoff:
            continue
        stale.append({"path": path, "text": text, "match": m, "kind": "stale",
                      "age": (today - activity).days, "activity": activity})
    out_of_scope.sort(key=lambda c: bundle_link(c["path"]))
    stale.sort(key=lambda c: -c["age"])
    return out_of_scope + stale


def normalize_link(link):
    """A `--except` value as the bundle-absolute loop path bundle_link()
    prints. Tolerant of a missing leading slash, a `knowledge/` prefix and
    backslashes: the value only ever keeps a loop open, so reading it
    generously is the safe direction."""
    s = str(link).strip().replace("\\", "/")
    if s.startswith("/knowledge/"):
        s = s[len("/knowledge"):]
    elif s.startswith("knowledge/"):
        s = s[len("knowledge"):]
    if not s.startswith("/"):
        s = "/" + s
    return s


def label(candidate):
    if candidate["kind"] == "out-of-scope":
        return "out of scope: the owner is in none of owner, owed_to, entities"
    return f"{candidate['age']}d stale"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                     help="expire the candidates found (default: dry-run, changes nothing)")
    ap.add_argument("--except", dest="except_links", action="append", default=[],
                     metavar="LINK",
                     help="bundle-absolute path of a loop to leave out of this run "
                          "(repeatable), in the dry run and on --apply")
    ap.add_argument("--skip-sweep", action="store_true",
                     help="deprecated, no effect: decay no longer reads "
                          "state/closure-sweep.json")
    args = ap.parse_args()

    if args.skip_sweep:
        print("note: --skip-sweep is deprecated and does nothing: decay no longer "
              "reads state/closure-sweep.json.", file=sys.stderr)

    expiry_days = loop_expiry_days()
    owner = owner_slug()
    if owner is None:
        print(f"note: elephant.json has no owner.slug, so the out-of-scope rule is "
              f"skipped this run; only loops stale for {expiry_days}+ days are "
              f"candidates.", file=sys.stderr)
    elif not owner_entity_exists(owner):
        print(f"note: elephant.json -> owner.slug `{owner}` names no entity file "
              f"(knowledge/entities/*/{owner}.md), so the out-of-scope rule is "
              f"skipped this run; was the owner's entity renamed or merged? Fix "
              f"owner.slug to match. Only loops stale for {expiry_days}+ days are "
              f"candidates.", file=sys.stderr)
        owner = None

    # --except: a link that names no loop file at all is a typo, not a loop
    # that stopped being a candidate, and the loop it meant to keep open would
    # expire in this very run. So is a link to a loop that is not open (done,
    # dropped, expired): it can never have been a candidate, and letting it
    # through would print the `matches no candidate` note the procedure reads
    # as a snooze or claim having taken. Refuse before anything is scanned or
    # written.
    excepted = []
    for raw in args.except_links:
        link = normalize_link(raw)
        if link not in excepted:
            excepted.append(link)
    if excepted:
        status_of = {}
        for p in loop_files():
            m = FM.match(p.read_text(encoding="utf-8"))
            status_of[bundle_link(p)] = loop_status(m.group(1)) if m else None
        refused = [link for link in excepted if status_of.get(link) != "open"]
        if refused:
            for link in refused:
                if link not in status_of:
                    why = f"names no loop file (no knowledge{link} under tracking/loops/)"
                elif status_of[link] is None:
                    why = "names a loop file with no frontmatter, which is no candidate"
                else:
                    why = (f"names a loop whose status is `{status_of[link]}`, not "
                           "open, so it is no candidate")
                print(f"error: --except {link} {why}. Nothing was scanned or "
                      "written; fix the link and run again.", file=sys.stderr)
            return 2

    candidates = find_candidates(expiry_days, owner)

    # --except: drop the named loops from this run before anything is printed
    # or written, so they are counted in neither split.
    if excepted:
        found = {bundle_link(c["path"]) for c in candidates}
        for link in excepted:
            if link not in found:
                print(f"note: --except {link} matches no candidate this run; "
                      "ignored.", file=sys.stderr)
        candidates = [c for c in candidates if bundle_link(c["path"]) not in excepted]

    if not args.apply:
        for c in candidates:
            print(f"{bundle_link(c['path'])}  ({label(c)})")
        n_scope = sum(1 for c in candidates if c["kind"] == "out-of-scope")
        print(f"\n{len(candidates)} candidate(s) for decay ({n_scope} out of scope, "
              f"{len(candidates) - n_scope} stale >= {expiry_days}d, dry-run, "
              f"pass --apply to expire)")
        return 0

    today_str = datetime.date.today().isoformat()
    n_scope = n_stale = 0
    for c in candidates:
        path, text, m = c["path"], c["text"], c["match"]
        new_block = expire_block(m.group(1), today_str)
        if new_block is None:
            print(f"warning: {bundle_link(path)} — could not locate `status: open` line, skipped",
                  file=sys.stderr)
            continue
        new_text = text[:m.start(1)] + new_block + text[m.end(1):]
        new_text = append_resolution(
            new_text,
            resolution_paragraph(c["kind"], c["age"], c["activity"], expiry_days,
                                 today_str, owner=owner),
        )
        path.write_text(new_text, encoding="utf-8")
        if c["kind"] == "out-of-scope":
            n_scope += 1
            print(f"expired: {bundle_link(path)}  (out of scope)")
        else:
            n_stale += 1
            print(f"expired: {bundle_link(path)}  ({c['age']}d stale)")

    print(f"\n{n_scope + n_stale} loop(s) expired ({n_scope} out of scope, "
          f"{n_stale} stale >= {expiry_days}d). Run build-index.py next.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
