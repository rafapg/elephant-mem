#!/usr/bin/env python3
"""Regenerate the derived surfaces of the elephant bundle from frontmatter.

At scale the bundle must NOT keep one flat global list of facts — that index
would grow without bound. Instead retrieval is entity-centric: facts are reached
through the entity pages that link them. So this script regenerates:

  1. knowledge/entities/index.md   — the entity CATALOG (the navigation spine),
                                      grouped by kind. Bounded by # of entities.
  2. knowledge/tracking/open-loops.md — board of `status: open` loops by owner.
  2b. knowledge/tracking/resolved-loops.md — the archive of loops that reached
                                      `done`, `dropped` or `expired`: newest
                                      first, one line each carrying the date,
                                      the outcome and the first sentence of the
                                      resolution written in the loop's body.
                                      Capped at `index.resolved_max` (200) with
                                      the overflow in a sibling archive shard.
                                      The loop FILE never moves — its path is
                                      cited from thousands of source bodies and
                                      facts — so this page, not a new location
                                      on disk, is where a resolved loop goes.
  3. knowledge/index.md            — a thin ROUTER: pointers + recent activity.
                                      Does NOT list every fact.
  4. entity/source backlinks       — the auto-facts block in each entity/source
                                      file, listing facts that reference it.
  5. knowledge/manifest.jsonl      — triage surface: one compact JSON line per
                                      active fact / open loop, carrying only the
                                      fields needed to DECIDE what to read in
                                      full (path, type, desc, entities, tags,
                                      occurred, confidence, status). It is NOT
                                      cheap to load: it grows with every fact and
                                      is already megabytes on a mature bundle, so
                                      a consumer hands it to a subagent and
                                      pre-filters with `rg` rather than reading
                                      it whole — see the delegation rule in
                                      skills/_shared/whole-field-scan.md.
  6. knowledge/entities/roster.tsv  — the RESOLUTION surface: one self-contained
                                      tab-separated row per active entity (slug,
                                      kind, title, aliases), so an extraction run
                                      resolves names in context instead of grepping
                                      and opening entity files. The bundle path is
                                      not stored; it reconstructs as
                                      /entities/{kind}/{slug}.md.

Never hand-edit those — this script is the single source of truth so they can't
drift. Pure stdlib (PyYAML optional, with a minimal fallback).
"""
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
# `plugin/assets/`, and the script would create knowledge/ or state/ inside the
# assets the marketplace publishes. That is not hypothetical: `plugin/assets/
# knowledge/` once carried four derived files, committed by accident and shipped.
# Refuse rather than create. Guarded on __main__ so the suites can still
# import the module to exercise its pure functions.
if __name__ == "__main__" and os.path.basename(ROOT) == "assets" and os.path.isdir(
    os.path.join(os.path.dirname(ROOT), ".claude-plugin")
):
    sys.exit(
        "refusing to run inside the elephant-mem plugin checkout.\n"
        "This script expects to live at <bundle>/scripts/, so it resolves its\n"
        "bundle as the parent of its own directory. Run from the checkout that\n"
        "is plugin/assets/, and it would write into the assets the marketplace\n"
        "publishes. Run it from an installed bundle instead."
    )
RESERVED = {"index.md", "log.md", "open-loops.md", "resolved-loops.md"}
RECENT_N = 12
# Regenerated sharding shard: never a first-class OKF type, so it carries no
# frontmatter and is excluded from concept-scanning / validate-okf.py's
# frontmatter rule (mirrors RESERVED, but by suffix since the basename varies
# per entity/source). Carries the overflow of a hub past HUB_MAX_FACTS and, on
# `tracking/`, the overflow of the resolved page past RESOLVED_MAX — the same
# mechanism, so the resolved shard needs no name of its own in the four
# RESERVED copies.
ARCHIVE_SUFFIX = ".facts-archive.md"
HUB_MAX_FACTS_DEFAULT = 50
RESOLVED_MAX_DEFAULT = 200
RESOLVED_REL = "tracking/resolved-loops.md"
RESOLVED_ARCHIVE_REL = "tracking/resolved-loops" + ARCHIVE_SUFFIX
RESOLUTION_HEAD = "**Resolution:**"

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
INLINE_LIST = re.compile(r"^\[(.*)\]$")
AUTO = re.compile(r"<!-- BEGIN auto-facts -->.*?<!-- END auto-facts -->", re.DOTALL)
TSV_BREAKING = re.compile(r"[\t\r\n]")
TSV_BREAKING_ALIAS = re.compile(r"[\t\r\n,]")
ROSTER_HEADER = "# slug\tkind\ttitle\taliases"

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None
    # Distinct from `yaml = None` set by a caller (tests force it to exercise the
    # fallback on purpose): only a genuinely missing install warrants the warning.
    YAML_MISSING = True
else:
    YAML_MISSING = False


def load_json_config(name):
    """Defensively read a JSON config file at the bundle root. Missing file,
    missing keys, or malformed JSON all fall through to None — callers apply
    their own default (mirrors ingest-audio.py's elephant.json reader)."""
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


VOCAB = load_json_config("vocab.json")


def vocab_set(key, default):
    """Controlled-vocabulary values for `key`, from vocab.json when present
    and well-formed, else `default` — kept byte-identical to the hardcoded
    behavior this replaced so bundles without vocab.json are unaffected."""
    if VOCAB and isinstance(VOCAB.get(key), list):
        return set(str(x) for x in VOCAB[key])
    return set(default)


def hub_max_facts():
    cfg = load_json_config("elephant.json") or {}
    v = cfg.get("index", {}).get("hub_max_facts") if isinstance(cfg.get("index"), dict) else None
    return v if isinstance(v, int) and v > 0 else HUB_MAX_FACTS_DEFAULT


def resolved_max():
    """How many resolved loops `tracking/resolved-loops.md` keeps inline, from
    `index.resolved_max` in elephant.json, else 200. Same section and the same
    defensive read as hub_max_facts(): the resolved page is the surface that
    would otherwise grow with every closure, forever."""
    cfg = load_json_config("elephant.json") or {}
    v = cfg.get("index", {}).get("resolved_max") if isinstance(cfg.get("index"), dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else RESOLVED_MAX_DEFAULT


# fact_status / loop_status default lists mirror vocab.json, which no bundle has
# ever received: `init` copies scripts/, templates/, config.md, README.md and
# cursors.json, and `update` re-syncs scripts/ and templates/ — so until a bundle
# is initialized by a version that copies it, THIS is the vocabulary that runs in
# the field. `expired` is in the loop default for that reason: without it
# `LOOP_HISTORY_STATUS` was `{done, dropped}`, `is_history()` returned false for
# an expired loop, and decay's own output rendered on the entity hub as a current
# item, consuming a slot of hub_max_facts.
FACT_STATUS = vocab_set("fact_status", ["active", "superseded", "deprecated"])
LOOP_STATUS = vocab_set("loop_status", ["open", "done", "dropped", "expired"])
FACT_HISTORY_STATUS = FACT_STATUS - {"active"}
LOOP_HISTORY_STATUS = LOOP_STATUS - {"open"}


def _closing_quote(v):
    """Index of the quote that closes the quoted scalar `v` (v[0] is the opening
    quote), or -1 if it is never closed. Honors the escaping rules of each YAML
    quoting style: `\\"` inside double quotes, `''` inside single quotes.
    Mirrors validate-okf.py's function of the same name."""
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
    one is content."""
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

    The fallback parser used to keep the comment, so every field our own
    templates document inline was read wrong wherever PyYAML is absent:
    `kind: concept  # person | org | ...` reached the roster with the whole
    vocabulary glued to it, `aliases: []  # other names...` stopped matching
    INLINE_LIST and became one long string instead of an empty list, and
    `status: open  # open | done | dropped` no longer equalled `open`, which
    hid every open loop from the open-loop surface.

    A `#` opens a comment only after a space, and only outside quotes and
    inline lists: `(#9-channel)` is content, and so are `resource:
    "slack:#channel"` and `aliases: ["a #b"]`.

    The *rule* is validate-okf.py's strip_comment(); the *quote scanning* is its
    _closing_quote(). They are two functions there, not one, and its own
    strip_comment() is the bare `split(" #")` one-liner with no quote handling at
    all — it does not need any, because classify_value() has already peeled the
    quotes before calling it. The quote-aware composition of the two exists only
    in this copy and briefing.py's. Chasing the pointer to that one-liner and
    concluding the three are interchangeable is how a later "unify these" lands a
    greedy cut that eats `resource: "slack:#channel"`.
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
    """Unwrap a quoted scalar the fallback parser read, undoing the two escapes
    that quoting a free-text value actually produces.

    Without the unwrapping, a quoted bundle link stays wrapped in literal quotes
    (`"'/entities/person/x.md'"`) and never matches its target — which is how a
    single unsafe scalar empties an entity hub's auto-facts block. Without the
    unescaping, a description written the way `validate-okf.py --fix` writes it
    (`"she said \\"ship it\\""`) renders with visible backslashes everywhere
    PyYAML is absent — and --fix is now the main producer of those escapes.

    Deliberately minimal, not a YAML unescaper: `\\"` and `\\\\` inside double
    quotes, `''` inside single quotes. Any other backslash sequence (`\\n`, `\\t`)
    is passed through untouched rather than guessed at.
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


def parse_fm(block, path=None):
    if yaml is not None:
        try:
            data = yaml.safe_load(block) or {}
            if isinstance(data, dict):
                return data
        except Exception as exc:
            # Never silent: a raising block means this file's links and
            # description are about to be misread by the fallback parser.
            where = path or "<frontmatter>"
            print(f"WARNING: {where}: frontmatter is not valid YAML ({exc.__class__.__name__}); "
                  "falling back to the naive parser. Run `validate-okf.py` to localize it.",
                  file=sys.stderr)
    # Minimal fallback parser (no PyYAML installed): handles scalars, inline
    # lists (`key: [a, b]`) and block-sequence lists:
    #   key:
    #     - a
    #     - b
    # A trailing YAML comment is stripped from every value, quotes and inline
    # lists honored (see strip_comment) — the templates document each field with
    # one, so keeping it fed the comment into the roster and the surfaces.
    # Nested mappings (e.g. `relations:`) are NOT supported here and resolve to
    # "" — same as before this fallback grew block-sequence support.
    data = {}
    lines = block.splitlines()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        i += 1
        if not line or line[0] in " \t#" or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), strip_comment(val)
        if not val:
            items = []
            while i < n:
                nxt = lines[i]
                stripped = nxt.strip()
                if not stripped:
                    i += 1
                    continue
                if nxt[0] in " \t" and stripped.startswith("- "):
                    items.append(unquote(strip_comment(stripped[2:])))
                    i += 1
                    continue
                break
            data[key] = items if items else ""
            continue
        m = INLINE_LIST.match(val)
        if m:
            inner = m.group(1).strip()
            data[key] = [unquote(x.strip()) for x in inner.split(",") if x.strip()] if inner else []
        else:
            data[key] = unquote(val)
    return data


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v).strip()] if str(v).strip() else []


def md_files(base):
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".md"):
                yield os.path.join(dirpath, f)


def bundle_link(path):
    return "/" + os.path.relpath(path, BUNDLE).replace(os.sep, "/")


def line(c):
    """`- [title](link) — description`, without repeating the description."""
    title = c["title"]
    desc = f" — {c['description']}" if c["description"] and c["description"] != title else ""
    return f"- [{title}]({c['link']}){desc}"


def resolution_sentence(body):
    """The first sentence of a loop body's `**Resolution:**` paragraph, or "".

    The resolution is prose in the body, never a frontmatter field — a sentence
    of judgment carries `: ` and sometimes ` #`, which the loop template warns
    breaks or silently truncates an unquoted value. Both writers put the
    sentence that stands alone first (`close-loops` by hand, decay-loops.py's
    resolution_paragraph()) precisely because this is where it lands.

    Split on `. ` only, so `elephant.json` and `decay.loop_expiry_days` are not
    sentence ends. A paragraph wrapped across lines is collapsed first.
    """
    for para in body.split("\n\n"):
        para = " ".join(para.split())
        if not para.startswith(RESOLUTION_HEAD):
            continue
        rest = para[len(RESOLUTION_HEAD):].strip()
        head, sep, _ = rest.partition(". ")
        return head + "." if sep else head
    return ""


def resolved_on(c):
    """The date a resolved loop was resolved: `closed` for a closure, `expired`
    for a decay expiry, and the file's own `updated`/`opened` for a loop whose
    status was flipped by hand without either. Sorts the resolved page."""
    for key in ("closed", "expired"):
        v = str(c["fm"].get(key) or "").strip()
        if v:
            return v
    return str(c["fm"].get("updated") or c["fm"].get("opened") or "")


def resolved_line(c):
    """`- <date> · <status> · [description](link) — <first sentence>`. A loop
    resolved before the resolution paragraph existed simply ends at the link."""
    label = c["description"] or c["title"]
    tail = f" — {c['resolution']}" if c["resolution"] else ""
    return f"- {resolved_on(c)} · {c['status']} · [{label}]({c['link']}){tail}"


def write(rel, lines):
    path = os.path.join(BUNDLE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")


def tsv_field(s):
    """Collapse the three characters that would break the TSV grid (tab, CR, LF)
    to a space. A comma survives here: the column is tab-delimited, and law-firm
    and org names carry real commas."""
    return TSV_BREAKING.sub(" ", str(s))


def tsv_alias(s):
    """Same, plus the comma — the alias column is itself comma-joined, so a comma
    inside a single alias would split it into two names."""
    return TSV_BREAKING_ALIAS.sub(" ", str(s))


def write_roster(rel, rows):
    """Write the roster with its own writer, NOT through write(): that helper ends
    with `"\\n".join(lines).rstrip() + "\\n"`, and the rstrip() eats the trailing tab
    of a last row whose aliases are empty — silently emitting three columns instead
    of four. newline="\\n" keeps the row separator out of the sanitized fields on
    Windows. Returns the byte size written."""
    path = os.path.join(BUNDLE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = "".join(r + "\n" for r in rows)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(data)
    return len(data.encode("utf-8"))


def main():
    if YAML_MISSING:
        # Without PyYAML EVERY file goes through the naive parser, so the damage
        # from an unsafe scalar is bundle-wide rather than per-file. Warn instead
        # of hard-failing: the fallback is a supported path (see tests/test_index.py).
        print("WARNING: PyYAML is not installed — parsing frontmatter with the naive "
              "fallback parser for every file, which cannot read nested mappings and "
              "is quote-lenient. Install it (`pip install pyyaml`) for exact parsing.",
              file=sys.stderr)
    concepts = []
    for path in md_files(BUNDLE):
        if os.path.basename(path) in RESERVED or path.endswith(ARCHIVE_SUFFIX):
            continue
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        m = FM.match(text)
        if not m:
            continue
        fm = parse_fm(m.group(1), bundle_link(path))
        title = fm.get("title") or fm.get("description") or os.path.basename(path)[:-3]
        concepts.append({
            "type": str(fm.get("type", "untyped")),
            "kind": str(fm.get("kind", "other")),
            "title": str(title),
            "description": str(fm.get("description", "")),
            "status": str(fm.get("status", "active")),
            "updated": str(fm.get("updated", "")),
            "link": bundle_link(path),
            "fm": fm,
            "path": path,
            # Only a loop's body is kept, and only its resolution sentence out of
            # it: the resolved page needs that one line, and holding every body
            # in memory would cost the whole bundle instead of one field per loop.
            "resolution": (resolution_sentence(text[m.end():])
                           if str(fm.get("type", "")) == "open-loop" else ""),
        })

    def active(items):
        return [c for c in items if c["status"] not in FACT_HISTORY_STATUS]

    entities = [c for c in concepts if c["type"] == "entity"]
    facts = [c for c in concepts if c["type"] == "fact"]
    sources = [c for c in concepts if c["type"] == "source"]
    loops = [c for c in concepts if c["type"] == "open-loop"]

    # 1. entities/index.md — catalog by kind
    cat = ["# Entities", "", "Catalog (the navigation spine). Derived — do not edit by hand.", ""]
    by_kind = {}
    for c in active(entities):
        by_kind.setdefault(c["kind"], []).append(c)
    for k in sorted(by_kind):
        cat.append(f"## {k}")
        cat.append("")
        for c in sorted(by_kind[k], key=lambda x: x["title"].lower()):
            cat.append(line(c))
        cat.append("")
    write("entities/index.md", cat)

    # 1b. entities/roster.tsv — the resolution surface, from the same active()
    # list the catalog is built from. One self-contained row per entity, so a
    # future shard is a matter of dropping lines rather than a reformat.
    roster_rows = []
    for c in sorted(active(entities), key=lambda x: (x["kind"], x["title"].lower(), x["path"])):
        slug = os.path.basename(c["path"])[:-len(".md")]
        aliases = ",".join(tsv_alias(a) for a in as_list(c["fm"].get("aliases")))
        roster_rows.append("\t".join((
            tsv_field(slug), tsv_field(c["kind"]), tsv_field(c["title"]), aliases,
        )))
    roster_bytes = write_roster("entities/roster.tsv", [ROSTER_HEADER] + roster_rows)

    # 2. tracking/open-loops.md — board of open loops by owner
    board = ["# Open loops", "", "Action items / commitments still open. Derived — do not edit by hand.", ""]
    open_loops = [c for c in loops if str(c["fm"].get("status", "open")) == "open"]
    if not open_loops:
        board.append("_No open loops._")
    else:
        by_owner = {}
        for c in open_loops:
            owners = as_list(c["fm"].get("owner")) or ["(unassigned)"]
            for o in owners:
                by_owner.setdefault(o, []).append(c)
        for o in sorted(by_owner):
            board.append(f"## {o}")
            board.append("")
            for c in sorted(by_owner[o], key=lambda x: x["fm"].get("opened", "")):
                opened = c["fm"].get("opened", "")
                board.append(f"- [{c['description'] or c['title']}]({c['link']}) — opened {opened}")
            board.append("")
    write("tracking/open-loops.md", board)

    # 2b. tracking/resolved-loops.md — the one listing of resolved loops.
    # A resolved loop's FILE never moves: its path is cited thousands of times
    # from source bodies, facts and log.md, and validate-okf.py fails the run on
    # a link that no longer resolves. So resolution is a state change plus a
    # written justification, and THIS page is the archive.
    resolved_loops = [c for c in loops if str(c["fm"].get("status", "open")) != "open"]

    def write_resolved(items):
        """Emit the resolved page newest first, capped at resolved_max(), with
        the overflow in a sibling ARCHIVE_SUFFIX shard so the page cannot become
        a second 541 KB board. Returns the shard paths written, so the archive
        cleanup in section 4 does not delete a shard this run created."""
        ordered = sorted(items, key=lambda c: (resolved_on(c), c["link"]), reverse=True)
        cap = resolved_max()
        inline, overflow = ordered[:cap], ordered[cap:]
        shard_path = os.path.join(BUNDLE, RESOLVED_ARCHIVE_REL)
        page = [
            "# Resolved loops",
            "",
            "Loops that reached `done`, `dropped` or `expired`, newest first, each with the "
            "first sentence of its resolution. Derived — do not edit by hand.",
            "",
        ]
        page += [resolved_line(c) for c in inline] or ["_No resolved loops._"]
        if overflow:
            page += ["", f"→ {len(overflow)} older resolved loop(s): "
                         f"[archive]({bundle_link(shard_path)})"]
        write(RESOLVED_REL, page)
        if not overflow:
            return set()
        write(RESOLVED_ARCHIVE_REL, [
            "# Resolved loops — archive",
            "",
            f"Resolved loops past the newest {cap} on "
            f"[the resolved page](/{RESOLVED_REL}), sharded out by "
            "`scripts/build-index.py` (page too large). Regenerated every build — "
            "do not edit by hand.",
            "",
        ] + [resolved_line(c) for c in overflow])
        return {shard_path}

    resolved_shards = write_resolved(resolved_loops)

    # 3. knowledge/index.md — thin router
    n_kind = {k: len(v) for k, v in by_kind.items()}
    kinds_str = ", ".join(f"{n} {k}" for k, n in sorted(n_kind.items())) or "none yet"
    recent = sorted(active(facts), key=lambda x: x["updated"], reverse=True)[:RECENT_N]
    router = [
        "# elephant — index",
        "",
        "Router. Derived by `scripts/build-index.py` — do not edit by hand.",
        "Facts are reached through the entity pages that link them, not listed here.",
        "",
        f"- **Entities** → [catalog](/entities/index.md) ({kinds_str})",
        f"- **Open loops** → [board](/tracking/open-loops.md) ({len(open_loops)} open)",
        f"- **Resolved loops** → [archive](/{RESOLVED_REL}) ({len(resolved_loops)} resolved)",
        "- **Log** → [log.md](/log.md)",
        f"- **Counts**: {len(active(facts))} active facts · {len(sources)} sources",
        "",
        "## Recent activity",
        "",
    ]
    if recent:
        for c in recent:
            router.append(f"- {c['updated']} · [{c['description'] or c['title']}]({c['link']})")
    else:
        router.append("_Nothing yet._")
    write("index.md", router)

    # 4. backlinks into entity & source files — trust-aware (see SKILL "Retrieval trust")
    fact_by_link = {c["link"]: c for c in facts}
    # The union survives the loops leaving: `refs` below is facts + OPEN loops,
    # so LOOP_HISTORY_STATUS matches nothing here any more, and is_history() is
    # in practice the fact test. Kept whole rather than narrowed, so a hub that
    # is ever asked to carry loops again classifies them the same way.
    HISTORY_STATUS = FACT_HISTORY_STATUS | LOOP_HISTORY_STATUS
    HUB_MAX_FACTS = hub_max_facts()

    def occ(c):
        return str(c["fm"].get("occurred") or c["fm"].get("opened") or c["updated"] or "")

    def is_history(r):
        st = str(r["fm"].get("status", "")).lower()
        return st in HISTORY_STATUS

    def marked(r):
        """Prefix ⚠️ for low-confidence or needs-review active items; leave others clean."""
        low = str(r["fm"].get("confidence", "")).lower() == "low"
        review = "needs-review" in as_list(r["fm"].get("tags"))
        label = r["description"] or r["title"]
        item = f"- [{label}]({r['link']})"
        return ("- ⚠️ " + item[2:]) if (low or review) else item

    def history_line(r):
        label = r["description"] or r["title"]
        item = f"- [{label}]({r['link']})"
        # For a superseded fact, point at its successor so the reader sees the current truth.
        for tgt in as_list((r["fm"].get("relations") or {}).get("superseded-by")
                           if isinstance(r["fm"].get("relations"), dict) else None):
            succ = fact_by_link.get(tgt)
            succ_label = (succ["description"] or succ["title"]) if succ else tgt
            item += f" → superseded by [{succ_label}]({tgt})"
            break
        return item

    def archive_path_for(entity_path):
        d = os.path.dirname(entity_path)
        base = os.path.basename(entity_path)[:-len(".md")]
        return os.path.join(d, base + ARCHIVE_SUFFIX)

    def write_archive(path, hub_title, hub_link, overflow_active, hist_refs):
        """Sibling shard for a hub past HUB_MAX_FACTS: no frontmatter (see
        ARCHIVE_SUFFIX) — plain markdown, regenerated wholesale every build."""
        lines = [
            f"# Archived facts — {hub_title}",
            "",
            f"Older / superseded facts referencing [{hub_title}]({hub_link}), sharded out of its "
            "inline auto-facts block by `scripts/build-index.py` (hub too large). "
            "Regenerated every build — do not edit by hand.",
            "",
        ]
        if overflow_active:
            lines += ["## Related facts (older)", ""]
            lines += [marked(r) for r in overflow_active]
            lines += [""]
        if hist_refs:
            lines += ["## Superseded / deprecated (history)", ""]
            lines += [history_line(r) for r in hist_refs]
            lines += [""]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).rstrip() + "\n")

    # Resolved loops leave the entity pages: `tracking/resolved-loops.md` is
    # their one listing, and a hub that kept re-filing them spent a slot of
    # hub_max_facts on each. Open loops only, the same partition the board and
    # the manifest already use.
    backlinks = {}
    for c in facts + open_loops:
        for tgt in as_list(c["fm"].get("entities")) + as_list(c["fm"].get("sources")) + as_list(c["fm"].get("owner")):
            backlinks.setdefault(tgt, []).append(c)

    injected = []
    archives_written = set(resolved_shards)
    for c in entities + sources:
        refs = sorted(backlinks.get(c["link"], []), key=lambda x: x["link"])
        active_refs = [r for r in refs if not is_history(r)]
        history_refs = [r for r in refs if is_history(r)]

        sharded = len(active_refs) > HUB_MAX_FACTS
        if sharded:
            active_sorted = sorted(active_refs, key=occ, reverse=True)
            inline_active = active_sorted[:HUB_MAX_FACTS]
            overflow_active = active_sorted[HUB_MAX_FACTS:]
        else:
            inline_active = active_refs
            overflow_active = []

        block = ["<!-- BEGIN auto-facts -->",
                 "<!-- Regenerated by scripts/build-index.py — do not edit by hand. -->"]
        if inline_active:
            block += ["", "## Related facts", ""]
            block += [marked(r) for r in inline_active]
            block += [""]
        if not sharded and history_refs:
            block += ["", "### Superseded / deprecated (history)", ""]
            block += [history_line(r) for r in history_refs]
            block += [""]
        if sharded:
            archive_path = archive_path_for(c["path"])
            archive_link = bundle_link(archive_path)
            moved = len(overflow_active) + len(history_refs)
            block += ["", f"→ {moved} older/superseded facts: [archive]({archive_link})", ""]
            write_archive(archive_path, c["title"], c["link"], overflow_active, history_refs)
            archives_written.add(archive_path)
        block.append("<!-- END auto-facts -->")

        with open(c["path"], encoding="utf-8") as fh:
            text = fh.read()
        if AUTO.search(text):
            new_text = AUTO.sub("\n".join(block), text)
        else:
            # No auto-facts marker yet (file created outside the template) —
            # append it so backlinks stop being silently dropped.
            sep = "" if text.endswith("\n") else "\n"
            new_text = text + sep + "\n" + "\n".join(block) + "\n"
            injected.append(c["link"])
        if new_text != text:
            with open(c["path"], "w", encoding="utf-8") as fh:
                fh.write(new_text)

    for label in injected:
        print(f"Injected auto-facts marker: {label}")

    # Idempotent archive cleanup: remove shards from a prior build that this
    # run didn't (re)write (hub shrank below HUB_MAX_FACTS, or was renamed/removed).
    for path in md_files(BUNDLE):
        if path.endswith(ARCHIVE_SUFFIX) and path not in archives_written:
            os.remove(path)

    # 5. manifest.jsonl — ultra-slim triage surface (active facts + open loops)
    manifest = []
    for c in sorted(active(facts) + open_loops, key=occ, reverse=True):
        manifest.append(json.dumps({
            "path": c["link"],
            "type": c["type"],
            "desc": c["description"] or c["title"],
            "entities": as_list(c["fm"].get("entities")),
            "tags": as_list(c["fm"].get("tags")),
            "occurred": occ(c),
            "confidence": str(c["fm"].get("confidence", "")),
            "status": c["status"],
        }, ensure_ascii=False, separators=(",", ":")))
    write("manifest.jsonl", manifest)

    print(f"Rebuilt: {len(active(entities))} entities, {len(active(facts))} facts, "
          f"{len(open_loops)} open loops, {len(resolved_loops)} resolved loops, "
          f"{len(sources)} sources. "
          f"manifest.jsonl: {len(manifest)} rows. "
          f"roster.tsv: {len(roster_rows)} rows, {roster_bytes} bytes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
