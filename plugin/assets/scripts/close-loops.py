#!/usr/bin/env python3
"""Propose evidence for the open loops it is this run's turn to examine.

The open-loop lane is close to write-only: 2036 loop files on the owner's
bundle, 1794 of them `open`, a 12% closure rate. The criterion for closing each
one is already written on 2025 of those files, in a `**Closure signal:**`
section no code has ever opened. This script opens it, and hands the daily
`close-loops` routine a bounded, ranked proposal instead of a 1794-file lane.

It reads and prints. It never writes a knowledge file, never writes
`state/closure-sweep.json`, and never decides that a loop is done — the routine
judges the evidence set as a whole and writes the verdict, because "did this get
delivered" is a judgment and not a string match.

**The queue is bounded and two-banded** (H2, E9, E10). Each run takes, in order:

  band 1 — loops examined before whose entities have gained a fact or a source
           since that examination. A verdict is never permanent: new material
           returns a loop to the front. Ordered oldest examination first.
  band 2 — everything else still unsettled, oldest last activity first, which
           puts the stale end of the lane at the front and gives a
           never-examined loop a defined position that a last-examination date
           cannot.

capped at `close_loops_max` (default 25), with a fifth of every run reserved for
band 2. While band 1 stays under the four fifths it may take, a run of 25
examines the stale backlog in about a month and the whole open lane in about two
and a half. Once band 1 saturates, the cold end advances at the reserved fifth
and no faster: 5 loops a run, so the owner's 735 stale loops take about 147 runs,
roughly five months. Either figure only holds if a run reaches loops the last one
did not, so "everything else" is read here as everything **not settled**: a loop
is settled once it was examined on or after its own last activity and has gained
nothing since. That is deliberately the same shape as the gate `decay-loops.py --apply`
applies before expiring a loop, one band earlier: what leaves this queue is
exactly what decay is then allowed to consider.

**The evidence is ranked and capped** (H3). Candidates are facts that share an
entity with the loop — the bundle's retrieval is entity-centric, so that is
where a loop's evidence actually lives — scored **additively**: two points per
shared **non-owner** entity plus one per content word shared with the loop's
`description` and its closure signal, ties broken by recency and then by path.
Capped at 10. The two signals live on incomparable scales, a loop names one to
three entities and a description carries fifteen-odd content words, so nesting
them made the entity count absolute: the one fact that literally satisfies the
closure criterion, sharing a single entity, lost all ten slots to facts that
shared two entities and not a word. Additive lets a criterion match outrank a
filing coincidence, which is the whole point of reading the closure signal.
Ranking on the owner's entity alone is why the median candidate count is 684:
the owner is on nearly every fact in the bundle, so as a signal it says
nothing. A candidate that shares no non-owner entity and no content word is
dropped rather than padded in, which is what makes "no evidence" (E11) a real
answer instead of ten unrelated facts.

A loop with no `**Closure signal:**` section is not skipped: its `description`
becomes the criterion and the proposal says so, in words, so the routine judges
against a criterion it can see the provenance of (E12).

Output is text by default (the routine reads it) and `--json` for a consumer
that parses. `--loop <path>` proposes for named loops and bypasses the queue,
warning on stderr about any name that matches no open loop rather than exiting
0 over a typo.

Exit code is 0 whenever the run completed, whether or not anything was queued.
Pure stdlib, regex frontmatter reader — same rule and same scanning as
`decay-loops.py`'s, comments and quotes included, because the templates
document every field with a trailing `#` comment and a reader that keeps it
reads `status: open  # open | done | dropped` as not-open and goes silently
blind.
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
# `plugin/assets/`, and the script would read (and a sibling would write) inside
# the assets the marketplace publishes. That is not hypothetical: `plugin/assets/
# knowledge/` once carried four derived files, committed by accident and shipped.
# Refuse rather than proceed. Guarded on __main__ so the suites can still
# import the module to exercise its pure functions.
if __name__ == "__main__" and BUNDLE.name == "assets" and (
    BUNDLE.parent / ".claude-plugin"
).is_dir():
    sys.exit(
        "refusing to run inside the elephant-mem plugin checkout.\n"
        "This script expects to live at <bundle>/scripts/, so it resolves its\n"
        "bundle as the parent of its own directory. Run from the checkout that\n"
        "is plugin/assets/, and it would read the assets the marketplace\n"
        "publishes as if they were a bundle. Run it from an installed bundle instead."
    )
KNOWLEDGE = BUNDLE / "knowledge"
LOOPS_DIR = KNOWLEDGE / "tracking" / "loops"
FACTS_DIR = KNOWLEDGE / "facts"
SOURCES_DIR = KNOWLEDGE / "sources"
STATE = BUNDLE / "state"
SWEEP = STATE / "closure-sweep.json"

DEFAULT_MAX = 25
EVIDENCE_CAP = 10

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# The closure criterion as the template writes it: a bolded lead-in, then a
# paragraph. It ends at a blank line, at the next bolded lead-in, or at EOF.
#
# The `\s*` between the lead-in and the criterion is deliberate, and so are the
# two things that make it safe. Markdown writes the criterion on the same line
# as the lead-in, on the line directly below it, or in the paragraph below it
# after a blank line; only `\s*` reaches all three. A separator that crosses at
# most one newline misses the third shape, the most idiomatic of them, and the
# loop then falls back to its `description` while the proposal states it carries
# no `**Closure signal:**` section at all. Worse, `terms` is built from the
# description plus the criterion, so the words that identify the right fact go
# with it.
#
# What `\s*` alone would do is run past an *empty* `**Closure signal:**` heading
# and return the next section labelled as the closure criterion, the one thing
# this script exists to read, silently wrong. Two guards refuse that:
# `(?!\*\*[^*\n]+:\*\*)` refuses a bolded lead-in as the criterion, and the `(\S`
# anchor refuses whitespace as its first character. With the
# `(?=\n\s*\n|\n\*\*…:\*\*|\Z)` terminator, an empty section then matches
# nothing and falls back to the `description` (E12), a criterion whose
# provenance the proposal can name. An empty section and a criterion in the
# paragraph below are byte-identical up to those guards, which is exactly why
# they carry the whole distinction. Case-insensitive because 2025 loop bodies
# were written by hand and nothing has ever checked the capital C.
CLOSURE_SIGNAL = re.compile(
    r"\*\*Closure signal:\*\*\s*(?!\*\*[^*\n]+:\*\*)(\S.*?)"
    r"(?=\n\s*\n|\n\*\*[^*\n]+:\*\*|\Z)",
    re.DOTALL | re.IGNORECASE,
)
WORD = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ][0-9A-Za-zÀ-ÖØ-öø-ÿ'’_-]*")

# Closed-class words in the two languages a bundle is written in (a bundle's
# `knowledge_language` is usually English, its conversation Portuguese), plus
# the loop lane's own vocabulary — "loop", "closure", "signal" and friends match
# between every loop and every fact and so rank nothing. Deliberately short: a
# stopword list that grows into a stemmer is a search engine, and the ranking
# only has to order 684 candidates well enough to keep the best 10.
STOPWORDS = {
    # English
    "about", "after", "again", "against", "already", "also", "and", "any",
    "are", "because", "been", "before", "being", "both", "but", "can", "cannot",
    "could", "did", "does", "done", "each", "either", "else", "even", "ever",
    "every", "for", "from", "had", "has", "have", "her", "here", "him", "his",
    "how", "into", "its", "just", "like", "made", "make", "many", "may",
    "might", "more", "most", "much", "must", "need", "needs", "not", "now",
    "off", "once", "only", "other", "our", "out", "over", "own", "per", "same",
    "several", "shall", "she", "should", "since", "some", "still", "such",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "through", "too", "under", "until", "upon", "use", "used",
    "using", "very", "was", "were", "what", "when", "where", "whether", "which",
    "while", "who", "whom", "why", "will", "with", "within", "without", "would",
    "yet", "you", "your",
    # Portuguese
    "aos", "após", "aquele", "aquela", "até", "cada", "com", "como", "das",
    "dela", "dele", "deles", "depois", "dos", "ela", "elas", "ele", "eles",
    "em", "entre", "essa", "esse", "esta", "estar", "este", "eu", "foi",
    "for", "isso", "já", "mais", "mas", "mesmo", "muito", "nao", "não", "nas",
    "nos", "num", "numa", "onde", "ou", "para", "pela", "pelo", "por", "porque",
    "qual", "quando", "que", "quem", "sao", "são", "se", "sem", "ser", "seu",
    "sua", "sobre", "também", "tem", "ter", "todo", "toda", "uma", "uns",
    # the lane's own vocabulary
    "closure", "loop", "loops", "open", "signal", "status", "tracking",
}
MIN_WORD = 3


def close_loops_max():
    """`close_loops_max` from elephant.json, or 25.

    Read from `close_loops.max` (section named for its consumer, the shape
    `index.hub_max_facts` and `decay.loop_expiry_days` already use) and, for a
    bundle that filed it with the other loop knob, from
    `decay.close_loops_max`. Defensive by design, like every other config
    reader here: a missing file, a missing key, a non-dict section or malformed
    JSON all fall back to the default rather than crashing an unattended run.
    """
    try:
        with open(BUNDLE / "elephant.json", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 — see the docstring
        return DEFAULT_MAX
    for section, key in (("close_loops", "max"), ("decay", "close_loops_max")):
        cfg = data.get(section) if isinstance(data, dict) else None
        if isinstance(cfg, dict):
            v = cfg.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                return v
    return DEFAULT_MAX


# --- the frontmatter reader ------------------------------------------------


def _closing_quote(v):
    """Index of the quote that closes the quoted scalar `v` (v[0] is the opening
    quote), or -1 if it is never closed. Honors the escaping rules of each YAML
    quoting style: `\\"` inside double quotes, `''` inside single quotes.
    Mirrors decay-loops.py's function of the same name."""
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
    one is content. Mirrors decay-loops.py's function of the same name."""
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
    build-index.py's / decay-loops.py's strip_comment(). The fact template
    documents `entities:` with a comment that carries a bracketed link of its
    own (`# bundle-absolute links, e.g. [/entities/person/foo.md]`), so a reader
    that cut naively would file that placeholder as an entity every fact shares.
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


def unquote(s):
    """Unwrap a quoted scalar, undoing the two escapes quoting actually
    produces: `\\"` and `\\\\` inside double quotes, `''` inside single quotes.
    Minimal on purpose, exactly like build-index.py's — a link left wrapped in
    literal quotes matches no entity, which is how one unsafe scalar empties a
    whole ranking."""
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


def field(block, key):
    """First `key: value` scalar in a frontmatter block, unquoted and without
    its trailing YAML comment, or None."""
    m = re.search(rf"^{re.escape(key)}:\s*(\S.*?)\s*$", block, re.MULTILINE)
    if not m:
        return None
    return unquote(strip_comment(m.group(1))) or None


def list_field(block, key):
    """Values of a list-valued frontmatter field: `key: [a, b]`, or the block
    sequence spelling, or a bare scalar read as a one-item list.

    The comma split is naive, matching build-index.py's fallback parser: every
    value this is used for is a bundle-absolute link or a slug, neither of which
    can carry a comma.
    """
    lines = block.splitlines()
    for i, ln in enumerate(lines):
        if not ln.startswith(key + ":"):
            continue
        val = strip_comment(ln[len(key) + 1:])
        if val.startswith("["):
            end = _closing_bracket(val)
            inner = (val[1:end] if end > 0 else val[1:]).strip()
            return [unquote(x.strip()) for x in inner.split(",") if x.strip()]
        if val:
            return [unquote(val)]
        items = []
        for nxt in lines[i + 1:]:
            stripped = nxt.strip()
            if not stripped:
                continue
            if nxt[:1] in " \t" and stripped.startswith("- "):
                items.append(unquote(strip_comment(stripped[2:])))
                continue
            break
        return items
    return []


def slug(link):
    """The entity slug a bundle-absolute link names. Compared by slug rather
    than by path so `/entities/person/x.md` and a hand-written `x` are the same
    entity — the kind directory is a filing decision, not identity."""
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


def newest_date(block, keys):
    """The newest of `keys` that parses as a date, as an ISO string, or None.
    Same tolerance as decay-loops.py's last_activity(): an unparseable or
    missing field is simply not a date, never an error."""
    dates = []
    for key in keys:
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
    return max(dates).isoformat() if dates else None


def body_of(text, match):
    return text[match.end():]


def criterion_of(text, match, description):
    """(criterion, where it came from) for one loop.

    The `**Closure signal:**` paragraph when the loop carries one; otherwise the
    `description`, flagged as such so the proposal can say so in words (E12).
    2025 of the owner's 2036 loops carry the section — the 11 that do not are
    exactly the case this fallback exists for.
    """
    m = CLOSURE_SIGNAL.search(body_of(text, match))
    if m:
        signal = " ".join(m.group(1).split())
        if signal:
            return signal, "closure-signal"
    return description or "", "description"


def tokens(text):
    """Content words of `text`: lowercased, at least MIN_WORD long, stopwords
    dropped. Order-free and duplicate-free — the overlap is a set intersection,
    so a fact does not rank higher for repeating a word."""
    out = set()
    for m in WORD.finditer(text or ""):
        w = m.group(0).lower().strip("-_'’")
        if len(w) >= MIN_WORD and w not in STOPWORDS:
            out.add(w)
    return out


# --- the bundle ------------------------------------------------------------


def bundle_link(path):
    return "/" + str(path.relative_to(KNOWLEDGE)).replace("\\", "/")


def md_files(base):
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.md") if p.is_file())


def parsed(path):
    """(frontmatter block, whole text, the FM match) for a document, or None
    when the file has no terminated frontmatter block — a derived surface, a
    shard, or a file mid-write. Never raises on an unreadable file: an
    unattended run must not die on one bad byte."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = FM.match(text)
    if not m:
        return None
    return m.group(1), text, m


def owner_slug():
    """The bundle owner's entity slug from elephant.json, or None.

    The owner is on nearly every fact and on most loops, so as a shared-entity
    signal it is noise — it is what makes the median candidate count 684. It is
    excluded from the ranking's first key together with the loop's own `owner:`
    links, and kept for pool membership so a loop that names nobody else still
    gets a ranked proposal instead of silence.
    """
    try:
        with open(BUNDLE / "elephant.json", encoding="utf-8") as fh:
            data = json.load(fh)
        owner = data.get("owner") if isinstance(data, dict) else None
        if isinstance(owner, dict):
            return slug(owner.get("slug") or owner.get("name"))
    except Exception:  # noqa: BLE001 — a missing config only costs one filter
        pass
    return None


def read_loops():
    """Every `status: open` loop, as a dict of what the proposal needs."""
    loops = []
    for path in md_files(LOOPS_DIR):
        got = parsed(path)
        if not got:
            continue
        block, text, m = got
        if field(block, "status") != "open":
            continue
        description = field(block, "description") or ""
        criterion, source = criterion_of(text, m, description)
        owners = slugs(list_field(block, "owner"))
        entities = slugs(list_field(block, "entities"))
        loops.append({
            "path": bundle_link(path),
            "description": description,
            "criterion": criterion,
            "criterion_source": source,
            # `owner` is what the file declares, and stays that way: it is
            # printed and emitted, and a loop declaring `owner: []` reported as
            # owned by whoever runs the script is a fact the bundle never
            # recorded. The bundle owner is folded into `effective_owner`
            # instead, which only the ranking reads.
            "owner": owners,
            "effective_owner": list(owners),
            "entities": entities,
            "last_activity": newest_date(block, ("updated", "opened", "created")),
            "terms": tokens(f"{description} {criterion}"),
        })
    return loops


def read_sources():
    """Bundle-absolute source link -> the newest date on that source."""
    dates = {}
    for path in md_files(SOURCES_DIR):
        got = parsed(path)
        if not got:
            continue
        block, _text, _m = got
        if field(block, "type") != "source":
            continue
        dates[bundle_link(path)] = newest_date(
            block, ("occurred", "ingested", "updated", "created", "timestamp")
        )
    return dates


def read_facts(source_dates):
    """Every active fact, with the date its evidence is worth.

    A fact's date is the newest of its own dates and of the sources it cites:
    an old conversation ingested last week is new material to a loop, and the
    file dates of the fact alone would say the opposite.
    """
    facts = []
    for path in md_files(FACTS_DIR):
        got = parsed(path)
        if not got:
            continue
        block, _text, _m = got
        if field(block, "type") != "fact":
            continue
        status = field(block, "status")
        if status and status != "active":
            continue
        description = field(block, "description") or ""
        sources = [str(s).strip() for s in list_field(block, "sources") if str(s).strip()]
        dates = [newest_date(block, ("occurred", "updated", "created", "timestamp"))]
        dates += [source_dates.get(s) for s in sources]
        dates = [d for d in dates if d]
        facts.append({
            "path": bundle_link(path),
            "description": description,
            "entities": slugs(list_field(block, "entities")),
            "sources": sources,
            "date": max(dates) if dates else None,
            "terms": tokens(description),
        })
    return facts


def entity_material(facts):
    """Entity slug -> the newest date of any material touching it.

    A source reaches an entity only through the facts that cite it — the source
    template carries no `entities:` field at all — so one walk over the facts
    covers both halves of "gained a fact or a source" (E10).
    """
    material = {}
    for fact in facts:
        if not fact["date"]:
            continue
        for s in fact["entities"]:
            if fact["date"] > material.get(s, ""):
                material[s] = fact["date"]
    return material


def index_by_entity(facts):
    """Entity slug -> the facts that name it. The candidate pool is drawn from
    here rather than from every fact: retrieval in this bundle is
    entity-centric, so a loop's evidence lives on the entities it names."""
    index = {}
    for fact in facts:
        for s in fact["entities"]:
            index.setdefault(s, []).append(fact)
    return index


# --- the sweep record ------------------------------------------------------


def load_sweep():
    """`state/closure-sweep.json`, or the empty record. Never raises.

    Control state, not audit: it records which loops were examined and when, so
    this queue knows what to revisit and `decay-loops.py --apply` knows what was
    looked at. Losing it parks decay rather than corrupting it — every loop then
    reads as never examined and returns to band 2, which at 25 a run takes weeks
    to work through (E18).

    Shape (written by the `close-loops` routine, never by this script):

        {"schema": 1, "generated": "<iso>",
         "loops": {"/tracking/loops/x.md": {"examined": "2026-09-01",
                                            "outcome": "open"}}}

    A bare ISO string in place of the entry dict is read as the examination
    date, because a hand-repaired record is a likely shape and refusing it would
    park decay over a formatting opinion.
    """
    if not SWEEP.exists():
        return {"schema": 1, "generated": None, "loops": {}}
    try:
        data = json.loads(SWEEP.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
    except Exception as exc:  # noqa: BLE001
        print(
            f"warning: state/closure-sweep.json is unreadable ({exc}) — treating "
            "it as empty, so every loop reads as never examined this run.",
            file=sys.stderr,
        )
        return {"schema": 1, "generated": None, "loops": {}}
    loops = data.get("loops")
    data["loops"] = loops if isinstance(loops, dict) else {}
    return data


def examined_on(sweep, link):
    """The ISO date `link` was last examined, or None if there is none readable.

    The value is validated exactly as decay-loops.py's `examination_date()`
    validates it, and the two have to stay mirrors. `DATE.search` alone finds ten
    digits in the right shape and nothing else, so `2026-99-99` and `2099-01-01`
    both read as an examination here while decay refuses them and parks the loop
    as never examined. That disagreement is a deadlock: decay holds the loop
    forever waiting for an examination, this queue calls it settled and never
    proposes one, and neither lane touches it again.

    Validating the **matched group** rather than the whole value, again like
    decay: `datetime.date.fromisoformat()` over the whole thing would reject the
    `2026-09-01T09:00:00-03:00` shape `load_sweep()` tolerates on purpose. An
    unreadable value reads as "never examined", which returns that one loop to
    band 2 rather than dropping it.
    """
    entry = (sweep.get("loops") or {}).get(link)
    if isinstance(entry, str):
        value = entry
    elif isinstance(entry, dict):
        value = entry.get("examined") or entry.get("date") or entry.get("last")
    else:
        return None
    m = DATE.search(value) if isinstance(value, str) else None
    if not m:
        return None
    try:
        parsed = datetime.date.fromisoformat(m.group(0))
    except ValueError:
        return None  # ten digits in the right shape, not a date
    if parsed > datetime.date.today():
        return None  # an examination cannot be in the future
    return m.group(0)


# --- the queue -------------------------------------------------------------


def new_material(loop, material, examined):
    """(slug, date) of the newest material a loop's non-owner entities gained
    strictly after `examined`, or None.

    Strictly after, by date: a fact filed the same day the loop was examined was
    almost certainly what the examination read, and counting it would return the
    loop to band 1 on every run forever.
    """
    best = None
    owners = loop.get("effective_owner", loop["owner"])
    for s in loop["entities"]:
        if s in owners:
            continue
        when = material.get(s)
        if when and when > examined and (best is None or when > best[1]):
            best = (s, when)
    return best


def build_queue(loops, sweep, material, cap):
    """The run's queue: band 1 first, band 2 guaranteed a slice, capped at `cap`.

    Band 1 takes at most four fifths of the run so band 2 always advances; the
    slots band 2 cannot fill go back to band 1, so the run is never short.

    Band 2 is "everything else still unsettled" — never examined, or examined
    before its own last activity. A loop examined on or after its last activity
    and with nothing new is settled and waits for material rather than being
    re-read every run, which is what makes the lane finite: 25 a run only clears
    a 1794-loop backlog if a run reaches loops the last one did not.
    """
    band1, band2 = [], []
    for loop in loops:
        examined = examined_on(sweep, loop["path"])
        loop["examined"] = examined
        if examined:
            gained = new_material(loop, material, examined)
            if gained:
                loop["band"] = 1
                loop["reason"] = (
                    f"{gained[0]} gained material on {gained[1]}, "
                    f"examined {examined}"
                )
                band1.append(loop)
                continue
            if loop["last_activity"] and loop["last_activity"] > examined:
                loop["band"] = 2
                loop["reason"] = (
                    f"active since it was examined ({loop['last_activity']} > "
                    f"{examined})"
                )
                band2.append(loop)
            continue
        loop["band"] = 2
        loop["reason"] = "never examined"
        band2.append(loop)

    band1.sort(key=lambda lp: (lp["examined"], lp["path"]))
    # None last: a loop whose file carries no parseable date is not evidence of
    # age, so it does not get to claim the front of the stale end.
    band2.sort(key=lambda lp: (lp["last_activity"] is None,
                               lp["last_activity"] or "", lp["path"]))
    # Band 1 is served first but is not absolute: a fifth of the run is reserved
    # for the cold end of the lane. Absolute precedence starves band 2 for as
    # long as band 1 keeps overflowing, and band 2 is where the loops decay is
    # waiting on live: measured on the owner's bundle, 0 of 40 cold loops were
    # examined over 30 simulated runs.
    #
    # The reservation is at least one slot, because `cap // 5` is 0 for every cap
    # below 5 and a plain fifth hands those runs entirely to band 1, which is the
    # starvation this exists to stop. `close_loops_max` takes any int above 0
    # from elephant.json and `--max 3` is a legal run, so those caps are reached.
    # The one exception is a cap of 1: a single slot cannot serve both bands, and
    # band 1 is the priority lane.
    reserve = 0 if cap == 1 else max(1, cap // 5)
    take1 = min(len(band1), cap - reserve)
    # The reservation is only ever as large as band 2 can fill, so an empty
    # cold end gives its slots back rather than shortening the run.
    take2 = min(len(band2), cap - take1)
    take1 = min(len(band1), cap - take2)
    return band1[:take1] + band2[:take2], band1, band2


# --- the evidence ----------------------------------------------------------


def score_of(shared, overlap):
    """The evidence score: two per shared non-owner entity, one per shared word.

    Additive, not nested. The two counts have incomparable ranges — a loop names
    one to three non-owner entities, its description and closure signal carry
    fifteen-odd content words — so comparing the entity count first made it
    absolute: every fact sharing two entities and not one word outranked the
    fact that quoted the closure criterion back, and with the cap at 10 the real
    match was not merely demoted, it was cut. Two points an entity keeps the
    filing signal worth more than any single word without letting it win alone.
    """
    return 2 * len(shared) + len(overlap)


def rank_evidence(loop, by_entity, cap=EVIDENCE_CAP):
    """(the top `cap` candidates, how many there were).

    Ordered by `score_of()` descending, then recency, then path so a run is
    reproducible. A candidate scoring zero is dropped: it shares only the owner,
    who is on nearly every fact, and would pad the proposal with exactly the
    noise the cap exists to keep out.
    """
    owners = loop.get("effective_owner", loop["owner"])
    signal_entities = [s for s in loop["entities"] if s not in owners]
    pool = {}
    for s in loop["entities"] + owners:
        for fact in by_entity.get(s, []):
            pool[fact["path"]] = fact

    scored = []
    for fact in pool.values():
        shared = [s for s in signal_entities if s in fact["entities"]]
        overlap = sorted(loop["terms"] & fact["terms"])
        if not score_of(shared, overlap):
            continue
        scored.append({
            "path": fact["path"],
            "description": fact["description"],
            "shared_entities": shared,
            "overlap": overlap,
            "score": score_of(shared, overlap),
            "date": fact["date"],
            "sources": fact["sources"],
        })
    scored.sort(key=lambda c: (-c["score"], c["date"] is None,
                               _desc(c["date"]), c["path"]))
    return scored[:cap], len(scored)


def _desc(iso):
    """A sort key that orders ISO dates newest first inside an otherwise
    ascending tuple. `None` is handled by the flag ahead of it."""
    return tuple(-int(part) for part in (iso or "0-0-0").split("-"))


# --- rendering -------------------------------------------------------------


def render_text(queue, counts, cap):
    out = [
        f"# close-loops proposal — {counts['queued']} loop(s) queued of "
        f"{counts['open']} open ({counts['band1']} in band 1, "
        f"{counts['band2']} unsettled in band 2, max {cap})",
    ]
    for loop in queue:
        out.append("")
        out.append(f"## {loop['path']}")
        out.append(f"band: {loop['band']} — {loop['reason']}")
        out.append(f"description: {loop['description'] or '—'}")
        if loop["criterion_source"] == "closure-signal":
            out.append(f"criterion (**Closure signal:**): {loop['criterion']}")
        else:
            out.append(
                "criterion (its `description` — this loop carries no "
                f"**Closure signal:** section): {loop['criterion'] or '—'}"
            )
        entities = ", ".join(loop["entities"]) or "—"
        owners = ", ".join(loop["owner"]) or "—"
        out.append(f"entities: {entities}  |  owner: {owners}")
        out.append(f"last activity: {loop['last_activity'] or 'unknown'}")
        if not loop["evidence"]:
            out.append(
                "evidence: none — no fact shares a non-owner entity or a content "
                "word with this loop. Examine it, record it, leave it open."
            )
            continue
        out.append(
            f"evidence: {len(loop['evidence'])} of {loop['candidates_total']} "
            f"candidate(s), ranked, capped at {EVIDENCE_CAP}"
        )
        for i, cand in enumerate(loop["evidence"], 1):
            shared = ", ".join(cand["shared_entities"]) or "—"
            overlap = ", ".join(cand["overlap"][:8]) or "—"
            out.append(
                f"  {i}. {cand['path']}  [score: {cand['score']} | shared: "
                f"{shared} | overlap: {overlap} | {cand['date'] or 'undated'}]"
            )
            if cand["description"]:
                out.append(f"     {cand['description']}")
            if cand["sources"]:
                out.append(f"     sources: {', '.join(cand['sources'])}")
    out.append("")
    out.append(
        f"{counts['queued']} loop(s) proposed. Nothing was written: this script "
        "reads. The routine judges each evidence set as a whole, writes the "
        "verdict into the loop file, and records the examination."
    )
    return "\n".join(out)


def warn_unmatched(requested, queue):
    """One stderr warning per `--loop` that matched no open loop.

    Exiting 0 with an empty proposal reads to the routine exactly like a loop
    with no evidence: it cannot tell "nothing to say about this one" from "you
    named a path that does not exist" or "that loop closed last week". The
    script already warns when the loops directory is missing; this is the same
    courtesy one level down. It stays a warning, not a failure — an unattended
    run that named three loops and mistyped one still proposes for the other two.
    """
    matched = set()
    for lp in queue:
        matched.add(lp["path"])
        matched.add(slug(lp["path"]))
    on_disk = {}
    for path in md_files(LOOPS_DIR):
        link = bundle_link(path)
        on_disk.setdefault(link, path)
        on_disk.setdefault(slug(link), path)
    for req in requested:
        if req in matched or (slug(req) or req) in matched:
            continue
        path = on_disk.get(req) or on_disk.get(slug(req) or req)
        if path is None:
            print(f"warning: --loop {req}: no loop by that name under "
                  "/tracking/loops/ — nothing was proposed for it",
                  file=sys.stderr)
            continue
        got = parsed(path)
        status = (field(got[0], "status") if got else None) or "unreadable"
        print(f"warning: --loop {req}: {bundle_link(path)} is `status: "
              f"{status}`, not open — only open loops are examined, so nothing "
              "was proposed for it", file=sys.stderr)


def positive_int(value):
    """`--max N` with N at least 1, refused at the boundary rather than
    silently rewritten. `--max 0` used to fall through to the configured
    default and examine 25 loops — a run that asked for none and got a full
    one, with nothing in the output saying so."""
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


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="close-loops.py",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--max", type=positive_int, default=None, metavar="N",
                    help="how many loops this run examines, at least 1 "
                         f"(default: elephant.json close_loops.max, else {DEFAULT_MAX})")
    ap.add_argument("--loop", action="append", default=[], metavar="PATH",
                    help="propose for this loop, bypassing the queue; repeat per loop")
    ap.add_argument("--json", action="store_true",
                    help="emit the proposal as JSON instead of text")
    args = ap.parse_args(argv)

    if not LOOPS_DIR.is_dir():
        print(f"note: {LOOPS_DIR} doesn't exist — no loops to examine",
              file=sys.stderr)

    cap = args.max or close_loops_max()
    loops = read_loops()
    owner = owner_slug()
    if owner:
        for loop in loops:
            # Into the ranking's owner set only. `owner:` keeps saying what the
            # file says, so `--json` and the printed proposal never report a
            # loop nobody claimed as the bundle owner's.
            if owner not in loop["effective_owner"]:
                loop["effective_owner"] = loop["effective_owner"] + [owner]

    facts = read_facts(read_sources())
    by_entity = index_by_entity(facts)

    if args.loop:
        wanted = {slug(p) or p for p in args.loop}
        queue = [lp for lp in loops if lp["path"] in set(args.loop)
                 or slug(lp["path"]) in wanted]
        for loop in queue:
            loop.setdefault("band", 0)
            loop.setdefault("reason", "named on the command line")
            loop.setdefault("examined", None)
        warn_unmatched(args.loop, queue)
        band1, band2 = [], []
    else:
        queue, band1, band2 = build_queue(
            loops, load_sweep(), entity_material(facts), cap
        )

    for loop in queue:
        loop["evidence"], loop["candidates_total"] = rank_evidence(loop, by_entity)

    counts = {
        "open": len(loops),
        "queued": len(queue),
        "band1": len(band1),
        "band2": len(band2),
        "facts": len(facts),
    }
    if args.json:
        payload = {
            "generated": datetime.datetime.now().astimezone().isoformat(),
            "max": cap,
            "evidence_cap": EVIDENCE_CAP,
            "counts": counts,
            "loops": [{k: v for k, v in loop.items() if k != "terms"} for loop in queue],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_text(queue, counts, cap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
