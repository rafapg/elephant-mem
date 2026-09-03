#!/usr/bin/env python3
"""Validate the elephant knowledge bundle against OKF v0.1 + elephant rules.

Rules:
  1. Every non-reserved `.md` under knowledge/ has frontmatter (--- ... ---)
     with a non-empty `type`.
  2. Reserved files (index.md, log.md) have NO frontmatter.
  3. Bundle-absolute links `](/path.md)` resolve to an existing file.
  4. No [[wikilinks]] anywhere.
  5. Every frontmatter scalar is YAML-safe (see unsafe_frontmatter()).

Rule 5 exists because ingestion is model-driven: a language model writes the
frontmatter, so an unsafe free-text scalar is a matter of when, not if. The three
ways it breaks in practice — all silent before this check existed:

  a. unquoted value containing `: `  — yaml.safe_load RAISES; build-index.py
     falls back to its naive parser, which doesn't strip quotes, so
     `entities: ['/x.md']` becomes the literal string "'/x.md'" and the entity
     hub's auto-facts block regenerates EMPTY.
  b. unquoted value containing ` #`  — parses FINE, but YAML treats the rest of
     the line as a comment, so the value is silently TRUNCATED. No exception, no
     artifact to grep for. (`(#9-channel)` — no leading space — is safe.)
  c. quoted value with unescaped inner quotes — same outcome as (a), but the
     value IS quoted. This is what a model produces once it's been told to quote
     but not how to escape, so quoting the templates is necessary, not sufficient.

Detection is purely lexical (no PyYAML needed — CI runs without it) so the
offending line can be reported for all three, including already-quoted ones.
`--fix` rewrites flagged values as JSON-encoded double-quoted scalars, which
preserves inner quotes instead of stripping them.

Non-fatal WARNINGS (do not affect the exit code):
  - alias/title collision: a name (case-insensitive) shared by the title or
    aliases of MORE THAN ONE entity file — surfaces entity conflation.
  - out-of-vocab value: a `type`/`kind`/`confidence`/`status`/`source-kind`
    value not listed in vocab.json's controlled vocabulary (skipped entirely
    when vocab.json is absent — see load_vocab()).

Usage:
  validate-okf.py          # report only; exit 1 on any hard violation
  validate-okf.py --fix     # additionally repair rule-5 violations in place

Exit code 0 if clean, 1 if any hard violation. Pure stdlib (PyYAML optional).
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
# Regenerated hub-sharding shard (see build-index.py) — has no frontmatter by
# design, so it's exempt from rule 1 (frontmatter + `type`) but still subject
# to the wikilink / broken-link checks below.
ARCHIVE_SUFFIX = ".facts-archive.md"

WIKILINK = re.compile(r"\[\[[^\]]+\]\]")
ABS_LINK = re.compile(r"\]\((/[^)\s#]+)")
FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TYPE_KEY = re.compile(r"^type:\s*(\S.*?)\s*$", re.MULTILINE)
TITLE_KEY = re.compile(r"^title:\s*(\S.*?)\s*$", re.MULTILINE)
# The whole inline list AND whatever follows it: the `]` is not the end of the
# line whenever the entity kept the trailing comment entity.md ships. Where the
# list actually closes is decided by inline_list(), which honors quoting.
ALIASES_KEY = re.compile(r"^aliases:\s*(\[.*)$", re.MULTILINE)
KIND_KEY = re.compile(r"^kind:\s*(\S.*?)\s*$", re.MULTILINE)
CONFIDENCE_KEY = re.compile(r"^confidence:\s*(\S.*?)\s*$", re.MULTILINE)
STATUS_KEY = re.compile(r"^status:\s*(\S.*?)\s*$", re.MULTILINE)
SOURCE_KIND_KEY = re.compile(r"^source-kind:\s*(\S.*?)\s*$", re.MULTILINE)

# A frontmatter mapping-key line: `key:` or `key: value`, at any indent. The
# strict key charset keeps prose lines inside a block scalar from matching (the
# block-scalar skip in unsafe_frontmatter() is the primary guard; this is belt
# and braces), and stops the key at the FIRST colon so a `: ` further along the
# line lands in the value where rule 5a can see it.
KEY_LINE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_.-]*):(?:\s(.*))?$")
BLOCK_SCALAR = re.compile(r"^[|>][+-]?\d*$")

# Free-text scalars: prose written by the model, where a `#` is CONTENT (a Slack
# channel, an issue number) and a trailing YAML comment is never intended. Every
# other field holds a bare token (enum, date, link) that our own templates
# document with a trailing comment — `kind: concept  # person | org | ...` — so
# for those the comment is stripped before checking, or the rules below would
# flag every template-derived file and the check would be worthless noise.
FREETEXT_KEYS = {"description", "title"}

# A plain scalar may not START with these, in ANY position-0 context. Most raise;
# `&` is the dangerous one because it does NOT — `description: &foo bar` parses as
# an anchor named `foo` with the value `bar`, silently dropping the first word (the
# same class of invisible damage as ` #`). Backticks around an identifier are
# extremely natural in technical prose (`description: `lexflow init` generates …`),
# which is how this turned up. Not included: `[`/`{` (flow, out of scope), `'`/`"`
# (handled by the quote analysis), and bare `|`/`>` (block scalars).
RESERVED_LEAD = "`@%&*!,>|"

# `-` and `?` are indicators ONLY when they open a token — i.e. when the value is
# just the indicator, or the indicator is followed by a space. Both forms raise and
# take the whole block with them. Everything else is a legitimate plain scalar, so
# this has to be narrower than RESERVED_LEAD: `-foo`, `-1.5`, `--force`,
# `-> arrow`, `--- three` and `?? what` are all fine and must not be flagged.
# `:` is the same shape but already covered by the `: `/trailing-`:` rule below.
# `~` is deliberately absent: a lone `~` is the idiomatic YAML null, so
# `confidence: ~` meaning "unset" is intent, not damage.
SPACED_LEAD = ("-", "?")

UNSAFE_HINT = {
    "unquoted-colon": "unquoted value contains `: ` — breaks the whole frontmatter block",
    "unquoted-hash": "unquoted value contains ` #` — silently truncated as a YAML comment",
    "unescaped-quote": "quoted value has unescaped inner quotes — breaks the whole block",
    "unterminated-quote": "quoted value is never closed — breaks the whole block",
    "reserved-lead": "unquoted value starts with a YAML indicator — breaks the block, "
                     "or (with `&`) is silently read as an anchor and loses its first word",
}


try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


def yaml_error(block):
    """One-line description of why PyYAML rejects `block`, or None if it accepts
    it (or isn't installed). Only a backstop — the lexical scan above is what
    localizes the three known failure modes and what runs everywhere."""
    if yaml is None:
        return None
    try:
        yaml.safe_load(block)
        return None
    except Exception as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 2}: " if mark is not None else ""
        return where + (getattr(exc, "problem", None) or type(exc).__name__)


def _closing_quote(v):
    """Index of the quote that closes the quoted scalar `v` (v[0] is the opening
    quote), or -1 if it is never closed. Honors the escaping rules of each YAML
    quoting style: `\\"` inside double quotes, `''` inside single quotes."""
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

    It used to cut on ` #` and nothing else, which is right for the plain
    bare-token scalar classify_value() hands it (the quotes are peeled there
    first) but wrong for every caller that reads a raw frontmatter line:
    `title: "vale #123"` came back as `"vale`, and `aliases: ["a", "b"]  # other
    names…` never matched its regex at all, so alias_title_collisions() went
    blind on any entity that kept the comment our own templates ship.

    A `#` opens a comment only after a space, and only outside quotes and
    inline lists: `(#9-channel)` is content, and so are `resource:
    "slack:#channel"` and `aliases: ["a #b"]`. Same rule and same scanning as
    build-index.py's / briefing.py's strip_comment().
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


def inline_list(raw):
    """Items of an inline `[a, b]` list read from a raw frontmatter line, or
    None when `raw` is not one — a block sequence (`aliases:` then `  - a`),
    an unterminated `[`, or any other shape. None means "not read", so the
    caller can fall back instead of mistaking it for an empty list."""
    v = strip_comment(raw)
    if not (v.startswith("[") and v.endswith("]")):
        return None
    return [x.strip() for x in v[1:-1].split(",") if x.strip()]


def classify_value(raw, freetext):
    """Classify the text after `key:`. Returns one of:
      None                  — safe, or out of scope (flow collection, empty)
      "block-scalar"        — `|`/`>` header; caller must skip the indented body
      (kind, fixable_value) — an unsafe scalar; fixable_value is the text the
                              author meant, or None when it can't be inferred.

    `freetext` selects how ` #` is read on an UNQUOTED value: as content on a
    prose field (so it must be quoted), or as a documenting comment on a
    bare-token field (so it is stripped before checking). See FREETEXT_KEYS.
    Quoting is analyzed FIRST and that stripping never applies inside quotes —
    `resource: "Slack #a, #b"` is valid YAML, and cutting at ` #` before looking
    at the quotes turned it into a bogus "unterminated quote".
    """
    v = raw.strip()
    if not v:
        return None
    if BLOCK_SCALAR.match(v):
        return "block-scalar"
    if v[0] in "[{":
        return None  # flow collection — PyYAML handles these; out of scope here
    if v[0] in "\"'":
        end = _closing_quote(v)
        # A quoted scalar that never closes, or closes before the end of the
        # line, is broken the same way — and in both cases the author's text is
        # recoverable, just not always the same span:
        #
        #   "she said "ship it" now"   → outer quotes ARE the YAML quoting;
        #                                the value is what's between them.
        #   "Search API" meeting …     → the leading quote is CONTENT (a quoted
        #                                title opening a sentence); the value is
        #                                the whole line. Same for a value whose
        #                                quote is simply never closed.
        #
        # The line ending in its own opening quote is what separates the two.
        if end < 0:
            return ("unterminated-quote", v)
        rest = v[end + 1:].strip()
        if not rest or rest.startswith("#"):
            return None  # properly closed, optionally trailing a comment
        wraps = v.endswith(v[0]) and len(v) > 1
        return ("unescaped-quote", v[1:-1] if wraps else v)
    # Plain (unquoted) scalar. Only here can a ` #` be a YAML comment.
    if not freetext:
        v = strip_comment(v)
        if not v:
            return None
    if v[0] in RESERVED_LEAD or v in SPACED_LEAD or v[:2] in ("- ", "? "):
        return ("reserved-lead", v)
    if ": " in v or v.endswith(":"):
        return ("unquoted-colon", v)
    if " #" in v:
        return ("unquoted-hash", v)
    return None


def unsafe_frontmatter(block):
    """Findings for rule 5 over one frontmatter block, as a list of
    (line_index_within_block, key, kind, fixable_value)."""
    findings = []
    lines = block.splitlines()
    i, n = 0, len(lines)
    while i < n:
        m = KEY_LINE.match(lines[i])
        i += 1
        if not m:
            continue
        indent, key, raw = m.group(1), m.group(2), m.group(3) or ""
        verdict = classify_value(raw, key in FREETEXT_KEYS)
        if verdict is None:
            continue
        if verdict == "block-scalar":
            # Literal/folded body: more-indented lines are content, not mappings.
            while i < n and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > len(indent)):
                i += 1
            continue
        kind, fixable = verdict
        findings.append((i - 1, key, kind, fixable))
    return findings


def fix_block(block, findings):
    """Rewrite the flagged lines of `block` as JSON-encoded double-quoted
    scalars. JSON string syntax is a valid YAML double-quoted scalar, so this
    escapes inner quotes rather than dropping them. Returns (new_block, n_fixed);
    findings whose intended value couldn't be inferred are left untouched."""
    lines = block.splitlines()
    fixed = 0
    for idx, key, _kind, fixable in findings:
        if fixable is None:
            continue
        indent = KEY_LINE.match(lines[idx]).group(1)
        lines[idx] = f"{indent}{key}: {json.dumps(fixable, ensure_ascii=False)}"
        fixed += 1
    return "\n".join(lines), fixed


def md_files(base):
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".md"):
                yield os.path.join(dirpath, f)


def read_block_list(block, key):
    """Return items of a block-sequence list field (`key:` then `  - item`
    lines), or [] if the field is absent or uses inline `[...]` syntax
    (handled separately by the caller's own regex)."""
    lines = block.splitlines()
    for idx, ln in enumerate(lines):
        if ln.strip() == f"{key}:":
            items = []
            for nxt in lines[idx + 1:]:
                stripped = nxt.strip()
                if not stripped:
                    continue
                if nxt[0] in " \t" and stripped.startswith("- "):
                    items.append(stripped[2:].strip())
                    continue
                break
            return items
    return []


def load_vocab():
    """Read vocab.json from the bundle root. None if absent or malformed —
    callers must treat that as "skip vocab checks", never as an error."""
    path = os.path.join(ROOT, "vocab.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def vocab_warnings(vocab):
    """WARN (never fail) on frontmatter values outside vocab.json's controlled
    vocabularies, grouped by (field, value) with an occurrence count. Which
    field applies depends on the file's `type`: kind/entity, confidence+status
    (fact_status)/fact, status (loop_status)/open-loop, source-kind/source."""
    if not vocab:
        return []
    counts = {}
    for path in md_files(BUNDLE):
        name = os.path.basename(path)
        if name in RESERVED or name.endswith(ARCHIVE_SUFFIX):
            continue
        with open(path, encoding="utf-8") as fh:
            m = FM.match(fh.read())
        if not m:
            continue
        block = m.group(1)
        # Every field checked here is a bare vocabulary token, never free text,
        # so a trailing ` #` is always a comment. Reading the raw line instead
        # made each of the four templates warn about itself — the whole
        # `concept         # person | org | …` line was compared to the
        # vocabulary — and so did every file a model wrote keeping that comment.
        tm = TYPE_KEY.search(block)
        type_val = strip_comment(tm.group(1).strip()) if tm else ""

        checks = [("type", TYPE_KEY, vocab.get("type"))]
        if type_val == "entity":
            checks.append(("kind", KIND_KEY, vocab.get("kind")))
        elif type_val == "fact":
            checks.append(("confidence", CONFIDENCE_KEY, vocab.get("confidence")))
            checks.append(("status", STATUS_KEY, vocab.get("fact_status")))
        elif type_val == "open-loop":
            checks.append(("status", STATUS_KEY, vocab.get("loop_status")))
        elif type_val == "source":
            checks.append(("source-kind", SOURCE_KIND_KEY, vocab.get("source-kind")))

        for field, pattern, allowed in checks:
            if not isinstance(allowed, list):
                continue
            fm_match = pattern.search(block)
            if not fm_match:
                continue
            val = strip_comment(fm_match.group(1).strip())
            if val and val not in allowed:
                counts[(field, val)] = counts.get((field, val), 0) + 1

    return [f"out-of-vocab {field}='{value}' ({n} file(s))"
            for (field, value), n in sorted(counts.items())]


def alias_title_collisions():
    """Scan entities/**; collect each entity's title + aliases and detect any
    name (case-insensitive) mapping to more than one entity file. Returns a list
    of warning strings."""
    entities_dir = os.path.join(BUNDLE, "entities")
    name_to_files = {}  # lowercased name -> {display_name, files:set}
    for path in md_files(entities_dir):
        if os.path.basename(path) in RESERVED:
            continue
        with open(path, encoding="utf-8") as fh:
            m = FM.match(fh.read())
        if not m:
            continue
        block = m.group(1)
        # Both reads go through strip_comment: an entity that kept the trailing
        # comment its template ships used to collide with nothing at all — the
        # aliases line stopped matching, and the title carried the comment into
        # the collision key. This warning exists to expose entity conflation,
        # so reading it wrong is exactly the failure it is meant to catch.
        names = []
        tm = TITLE_KEY.search(block)
        if tm and strip_comment(tm.group(1)):
            names.append(strip_comment(tm.group(1)))
        am = ALIASES_KEY.search(block)
        if am:
            names += inline_list(am.group(1)) or []
        am_block = read_block_list(block, "aliases")
        names += [x for x in am_block if x not in names]
        rel = os.path.relpath(path, BUNDLE)
        for n in names:
            key = n.lower()
            entry = name_to_files.setdefault(key, {"display": n, "files": set()})
            entry["files"].add(rel)

    warnings = []
    for entry in name_to_files.values():
        if len(entry["files"]) > 1:
            files = ", ".join(sorted(entry["files"]))
            warnings.append(f"alias/title collision: '{entry['display']}' on [{files}]")
    return sorted(warnings)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    apply_fixes = "--fix" in argv
    if not os.path.isdir(BUNDLE):
        print(f"FAIL: bundle not found: {BUNDLE}")
        return 1

    errors = []
    repaired = []
    for path in md_files(BUNDLE):
        rel = os.path.relpath(path, BUNDLE)
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()

        m = FM.match(text)
        if name in RESERVED:
            if m:
                errors.append(f"{rel}: reserved file must NOT have frontmatter")
        elif name.endswith(ARCHIVE_SUFFIX):
            pass  # generated hub-sharding shard: no frontmatter/type requirement
        else:
            if not m:
                errors.append(f"{rel}: missing frontmatter")
            else:
                t = TYPE_KEY.search(m.group(1))
                if not t or not t.group(1).strip():
                    errors.append(f"{rel}: frontmatter missing non-empty `type`")

        # Rule 5 — YAML-safe frontmatter scalars. The block starts on file line 2
        # (line 1 is the opening `---`), so +2 turns a block index into a file line.
        if m:
            block = m.group(1)
            findings = unsafe_frontmatter(block)
            if not findings:
                # Backstop for anything the lexical scan doesn't model: if PyYAML
                # is here and still refuses the block, say so rather than let
                # build-index.py fall back to the naive parser in silence. Only
                # reachable when the scan found nothing, so `block` is never stale.
                err = yaml_error(block)
                if err:
                    errors.append(f"{rel}: frontmatter is not valid YAML ({err})")
            else:
                if apply_fixes:
                    new_block, n_fixed = fix_block(block, findings)
                    if n_fixed:
                        text = text[:m.start(1)] + new_block + text[m.end(1):]
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(text)
                        repaired.append((rel, n_fixed))
                    # Only what --fix could NOT infer counts against the exit code.
                    findings = [f for f in findings if f[3] is None]
                for idx, key, kind, _fixable in findings:
                    errors.append(f"{rel}:{idx + 2}: unsafe frontmatter `{key}`: {UNSAFE_HINT[kind]}")

    warnings = alias_title_collisions() + vocab_warnings(load_vocab())

    if repaired:
        total = sum(n for _, n in repaired)
        print(f"Repaired {total} unsafe scalar(s) in {len(repaired)} file(s):")
        for rel, n in sorted(repaired):
            print(f"  - {rel} ({n})")
        print("Re-run `build-index.py` to regenerate the derived surfaces.")

    if errors:
        print(f"OKF validation FAILED ({len(errors)} issue(s)):")
        for e in errors:
            print(f"  - {e}")
        if not apply_fixes and any("unsafe frontmatter" in e for e in errors):
            print("Hint: `validate-okf.py --fix` repairs unsafe scalars in place "
                  "(quotes the value, preserving inner quotes).")
    else:
        print("OKF validation passed.")

    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
