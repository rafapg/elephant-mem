#!/usr/bin/env python3
"""Regression tests for YAML-safe frontmatter (validate-okf.py rule 5).

Ingestion is model-driven: the ingest skill mirrors the shape of
templates/*.md, so an unsafe free-text scalar is a matter of when, not if.
Three distinct failure modes follow, and before rule 5 existed
validate-okf.py caught none of them — it checked `type:` with a regex and
never parsed YAML, so a syntactically destroyed block passed:

  1. unquoted value containing `: `  — safe_load raises; build-index.py falls
     back to its naive parser and the entity hub's auto-facts block empties.
  2. unquoted value containing ` #`  — parses FINE, value silently truncated
     at the hash. No exception, nothing in the manifest to grep for.
  3. quoted value with unescaped inner quotes — same as (1), but the value IS
     quoted. This is what a model writes once told to quote but not to escape,
     which is why quoting the templates is necessary but not sufficient.

What these tests pin down, in order of what actually protects the bundle:

  a. all three modes FAIL validate-okf.py, each localized to its line and kind
  b. safe shapes are NOT flagged — including trailing comments on enum/date
     fields, which our own templates use. A check that cries wolf on nearly
     every file gets ignored, so this is as load-bearing as (a).
  c. the four shipped templates scan clean (entity.md once shipped a
     placeholder whose own text contained `: `)
  d. `--fix` repairs all three preserving inner quotes, and revalidates clean
  e. end-to-end: a broken fact no longer silently empties the hub, and after
     `--fix` + rebuild the description in the manifest is intact
  f. missing PyYAML warns on stderr instead of switching parsers in silence
  g. the fallback parser reads a trailing YAML comment the way PyYAML does —
     stripped outside quotes, kept inside them — and agrees with PyYAML field
     by field on a block carrying every shape. It used to keep the comment, so
     the templates' own `kind: concept  # person | org | …` documentation was
     read as the value on every machine without PyYAML.
  h. the same rule in the scripts that read frontmatter by REGEX rather than
     through parse_fm — rename-entity.py, snapshot-drift.py, validate-okf.py
     (decay-loops.py's is in tests/test_decay.py, next to the rest of decay).
     None of them knew about the comment either, and there PyYAML never helped:
     they have no parser to fall back to, so the damage was on every machine.

Pure stdlib, Python 3.10+, same scaffolding style as tests/test_index.py:
throwaway bundles under a tempdir, shipped scripts driven via subprocess.

Exit code 0 only if every check passes.
"""
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "plugin" / "assets"
TODAY = datetime.date.today().isoformat()
FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# A few assertions describe what PyYAML does with a given block (raising on
# mode 1/3, truncating on mode 2). Those are meaningless where PyYAML is absent,
# because then every file takes the naive parser instead — so they are skipped
# rather than asserted, and the skip is printed rather than swallowed.
try:
    import yaml  # noqa: F401
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

checks = []
skipped = []


def record(label, passed, detail=""):
    checks.append((label, passed))
    print(f"[{len(checks):2d}] {'PASS' if passed else 'FAIL'} — {label}")
    if detail and not passed:
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    return passed


def skip(label, why):
    skipped.append((label, why))
    print(f"[--] SKIP — {label} ({why})")


def guarded(fn, *a):
    try:
        fn(*a)
    except Exception:
        record(f"{fn.__name__} raised", False, traceback.format_exc())


def run_script(bundle, script_name, args=None, block_yaml=False):
    """Drive a shipped script in `bundle`. With block_yaml, PYTHONPATH gains a
    `yaml.py` that raises ImportError on execution, which is indistinguishable
    from PyYAML being absent — the state that makes every file take the naive
    parser and turns a per-file bug into a bundle-wide one."""
    env = dict(os.environ)
    if block_yaml:
        shim = bundle / "_noyaml"
        shim.mkdir(exist_ok=True)
        (shim / "yaml.py").write_text(
            'raise ImportError("simulated: PyYAML absent")\n', encoding="utf-8")
        env["PYTHONPATH"] = str(shim)
    return subprocess.run(
        [sys.executable, str(bundle / "scripts" / script_name)] + (args or []),
        cwd=str(bundle), capture_output=True, text=True, encoding="utf-8", env=env,
    )


def new_bundle(root, name):
    bundle = root / name
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    for f in ("build-index.py", "briefing.py", "validate-okf.py",
              "snapshot-drift.py", "rename-entity.py"):
        shutil.copy2(ASSETS / "scripts" / f, bundle / "scripts" / f)
    (bundle / "knowledge").mkdir(parents=True, exist_ok=True)
    (bundle / "knowledge" / "log.md").write_text("# Log\n", encoding="utf-8")
    return bundle


MARKER = (
    "\n<!-- BEGIN auto-facts -->\n"
    "<!-- Regenerated by scripts/build-index.py — do not edit by hand. -->\n"
    "<!-- END auto-facts -->\n"
)

ENTITY_LINK = "/entities/person/angelo.md"


def write_entity(bundle, rel=ENTITY_LINK.lstrip("/")):
    (bundle / "knowledge" / rel).parent.mkdir(parents=True, exist_ok=True)
    (bundle / "knowledge" / rel).write_text(
        "---\n"
        "type: entity\n"
        "kind: person         # person | org | project | tool | concept\n"
        'title: "Angelo Spinardi"\n'
        'description: "engineer on the export team"\n'
        "aliases: []\n"
        f"created: {TODAY}\nupdated: {TODAY}\n"
        "---\n\nAngelo.\n" + MARKER,
        encoding="utf-8")


def write_fact(bundle, rel, description_line, occurred=TODAY):
    """`description_line` is injected verbatim so a test can plant a raw,
    deliberately unsafe line — quoting it here would defeat the point."""
    path = bundle / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "type: fact\n"
        f"{description_line}\n"
        f"entities: ['{ENTITY_LINK}']\n"
        "status: active       # active | deprecated | superseded\n"
        f"occurred: {occurred}\nupdated: {occurred}\n"
        "---\n\nBody.\n",
        encoding="utf-8")
    return path


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "okf_validator", ASSETS / "scripts" / "validate-okf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def manifest_rows(bundle):
    p = bundle / "knowledge" / "manifest.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def auto_facts_block(bundle, rel=ENTITY_LINK.lstrip("/")):
    text = (bundle / "knowledge" / rel).read_text(encoding="utf-8")
    m = re.search(r"<!-- BEGIN auto-facts -->(.*?)<!-- END auto-facts -->", text, re.DOTALL)
    return m.group(1) if m else ""


def slashed(text):
    """Normalize path separators in captured output before matching.

    validate-okf.py reports file positions via os.path.relpath, so a finding
    reads `facts/m1.md:3` on POSIX and `facts\\m1.md:3` on Windows — as rules
    1-4 have always done. The assertion is about *which line* is reported, not
    about the separator, so normalize rather than hardcode either form."""
    return text.replace("\\", "/")


# The three modes, exactly as a model writes them.
MODE1 = "description: Angelo asked for help: the export was failing"
MODE2 = "description: Angelo asked for help in #suporte-produto about the export"
MODE3 = 'description: "Thayane took the informal role of "Chief Legal Officer", automating"'


# ---------------------------------------------------------------------------
# a. all three modes fail validation, localized
# ---------------------------------------------------------------------------

def test_three_modes_fail_validation(root):
    bundle = new_bundle(root, "three-modes")
    write_entity(bundle)
    for rel, line in (("facts/m1.md", MODE1), ("facts/m2.md", MODE2), ("facts/m3.md", MODE3)):
        write_fact(bundle, rel, line)

    r = run_script(bundle, "validate-okf.py")
    record("validate-okf.py exits nonzero when frontmatter is unsafe (it passed before rule 5)",
           r.returncode == 1, r.stdout + r.stderr)

    out = slashed(r.stdout)
    for rel, kind in (("m1", "`: `"), ("m2", "` #`"), ("m3", "unescaped inner quotes")):
        record(f"{rel}: reported on line 3 with the right diagnosis ({kind})",
               f"facts/{rel}.md:3: unsafe frontmatter `description`" in out
               and kind in out,
               r.stdout)

    record("the failure output points at --fix",
           "--fix" in r.stdout, r.stdout)


# ---------------------------------------------------------------------------
# b. safe shapes are not flagged — the check must not cry wolf
# ---------------------------------------------------------------------------

def test_safe_shapes_not_flagged(root):
    v = load_validator()
    safe = [
        ('quoted value containing `: `', 'description: "Angelo asked for help: the export failed"'),
        ('quoted value containing ` #`', 'description: "help in #suporte-produto about the export"'),
        ('single-quoted value containing "', "description: 'she said \"ship it\" on Friday'"),
        ('double-quoted value with escaped \\"', 'description: "she said \\"ship it\\" on Friday"'),
        ('`#` with no space before it', 'description: see ticket (#9-channel) for details'),
        ('trailing comment on an enum field', 'kind: concept        # person | org | project'),
        ('trailing comment containing `: `', 'channel: slack       # origin: slack:#channel'),
        ('a URL', 'resource: https://example.com/a/b'),
        ('an inline flow list', "entities: ['/entities/person/x.md', '/b.md']"),
        ('a block-sequence list', "entities:\n  - /entities/person/x.md"),
        # Regression: comment-stripping used to run BEFORE the quote analysis, so
        # a properly quoted non-free-text value containing ` #` was cut mid-string
        # and misreported as an unterminated quote — with no repair possible.
        # Found on a real bundle, not by the suite. Both lines are valid YAML.
        ('quoted non-free-text value containing ` #`',
         'resource: "Slack #team-a, #team-b, #support-bugs"'),
        ('quoted channel list with ` #`', 'channel: "slack:#a, #b"'),
        ('quoted value with ` #` AND a trailing comment',
         'resource: "Slack #team-a"   # where it came from'),
        # Leading characters that are NOT indicators when followed by non-space.
        # Over-flagging these would fire on ordinary prose and numbers.
        ('leading `-` (a negative number)', 'description: -5% growth in Q3'),
        ('leading `~`', 'description: ~2000 documents migrated'),
        ('leading `?`', 'description: ?unclear whether this shipped'),
        ('leading `:`', 'description: :shrug was the only reply'),
        ('a backtick NOT in first position', 'description: the `lexflow init` command'),
        # `-`/`?` open a token only when alone or followed by a space, so these
        # stay legitimate plain scalars. All verified accepted by PyYAML.
        ('leading `->`', 'description: -> handed off to the platform team'),
        ('leading `---`', 'description: --- separator in the pasted log'),
        ('leading `??`', 'description: ?? nobody knows who owns this'),
        ('leading `--` (a CLI flag)', 'description: --force was required'),
        # A lone `~` is the idiomatic YAML null: `confidence: ~` meaning "unset"
        # is intent, not damage. Flagging it would be a false positive.
        ('a lone `~` (explicit null)', 'confidence: ~'),
    ]
    for label, line in safe:
        found = v.unsafe_frontmatter(line + "\n")
        record(f"not flagged: {label}", not found, found)

    unsafe = [("unterminated quote", 'description: "never closed', "unterminated-quote"),
              ("`: ` on a non-free-text field", "owner: Jane: the lead", "unquoted-colon")]
    # A plain scalar may not start with a YAML indicator. Verified against
    # PyYAML: ` @ % * ! , > | all raise; `&` does NOT — it parses as an anchor
    # and silently drops the first word, so it belongs with ` #` in the
    # invisible-damage group. Found on a real bundle via a backticked command
    # name in a description, and the lexical scan has to model it because the
    # PyYAML backstop doesn't run where PyYAML is absent — including CI.
    unsafe += [(f"leading {c!r} on a plain scalar",
                f"description: {c}lexflow init generates a CLAUDE.md", "reserved-lead")
               for c in "`@%&*!,>|"]
    # `-` and `?` are indicators only when they open a token: alone, or followed
    # by a space. Both forms raise ScannerError and take the whole block with
    # them, and the lexical scan missed both — a gap CodeRabbit caught on #5.
    # `:` is the same shape, already covered by the `: `/trailing-`:` rule.
    unsafe += [("`- ` opening the value", "description: - handed off to Ana", "reserved-lead"),
               ("`? ` opening the value", "description: ? unclear who owns it", "reserved-lead"),
               ("a lone `-`", "description: -", "reserved-lead"),
               ("a lone `?`", "description: ?", "reserved-lead"),
               ("a lone `:`", "description: :", "unquoted-colon")]
    for label, line, kind in unsafe:
        found = v.unsafe_frontmatter(line + "\n")
        record(f"flagged: {label}", len(found) == 1 and found[0][2] == kind, found)

    # Every finding must carry a repairable value, or --fix leaves the bundle
    # permanently red. On a real bundle this was 34 of 445 findings.
    inferable = [
        ('outer quotes ARE the quoting (strip them)',
         'description: "she said "ship it" now"', 'she said "ship it" now'),
        ('leading quote is CONTENT — a quoted title opening a sentence',
         'description: "Search API - Nova Onda" meeting on 2026-05-26 with Angelo',
         '"Search API - Nova Onda" meeting on 2026-05-26 with Angelo'),
        ('never-closed quote is kept verbatim, not guessed away',
         'description: "never closed', '"never closed'),
        ('leading YAML indicator — quote the whole value, indicator included',
         'description: `lexflow init` generates a CLAUDE.md',
         '`lexflow init` generates a CLAUDE.md'),
        ('leading `&` — the silent one; the dropped first word is preserved',
         'description: &lexflow init generates a CLAUDE.md',
         '&lexflow init generates a CLAUDE.md'),
        ('`- ` opening the value — the dash is content, keep it',
         'description: - handed off to Ana', '- handed off to Ana'),
    ]
    for label, line, want in inferable:
        found = v.unsafe_frontmatter(line + "\n")
        got = found[0][3] if found else None
        record(f"--fix can infer: {label}", got == want, f"want={want!r}\ngot ={got!r}")


# ---------------------------------------------------------------------------
# c. the shipped templates are themselves safe
# ---------------------------------------------------------------------------

def test_shipped_templates_are_safe(root):
    v = load_validator()
    for path in sorted((ASSETS / "templates").glob("*.md")):
        m = FM_RE.match(path.read_text(encoding="utf-8"))
        if not m:
            continue
        found = v.unsafe_frontmatter(m.group(1))
        record(f"template {path.name} has no unsafe frontmatter scalar", not found, found)
        record(f"template {path.name} quotes its free-text `description`",
               re.search(r'^description: ["\']', m.group(1), re.MULTILINE) is not None,
               m.group(1))


# ---------------------------------------------------------------------------
# d. --fix repairs all three, preserving the author's text
# ---------------------------------------------------------------------------

def test_fix_repairs_and_preserves(root):
    bundle = new_bundle(root, "fix-repairs")
    write_entity(bundle)
    for rel, line in (("facts/m1.md", MODE1), ("facts/m2.md", MODE2), ("facts/m3.md", MODE3)):
        write_fact(bundle, rel, line)

    r = run_script(bundle, "validate-okf.py", ["--fix"])
    record("--fix repairs all three and exits 0",
           r.returncode == 0 and "Repaired 3 unsafe scalar(s) in 3 file(s)" in r.stdout,
           r.stdout + r.stderr)

    # The point of JSON-encoding the value: inner quotes survive instead of
    # being stripped, and the `#channel` is kept as the content it always was.
    expected = {
        "facts/m1.md": "Angelo asked for help: the export was failing",
        "facts/m2.md": "Angelo asked for help in #suporte-produto about the export",
        "facts/m3.md": 'Thayane took the informal role of "Chief Legal Officer", automating',
    }
    for rel, want in expected.items():
        block = FM_RE.match((bundle / "knowledge" / rel).read_text(encoding="utf-8")).group(1)
        got = None
        for ln in block.splitlines():
            if ln.startswith("description:"):
                got = json.loads(ln.split(":", 1)[1].strip())
        record(f"{rel}: repaired value is byte-identical to what the author wrote",
               got == want, f"want={want!r}\ngot ={got!r}")

    r2 = run_script(bundle, "validate-okf.py")
    record("the repaired bundle revalidates clean", r2.returncode == 0, r2.stdout + r2.stderr)


# ---------------------------------------------------------------------------
# e. end-to-end impact: hub backlinks and manifest descriptions
# ---------------------------------------------------------------------------

def test_end_to_end_hub_and_manifest(root):
    bundle = new_bundle(root, "end-to-end")
    write_entity(bundle)
    write_fact(bundle, "facts/m1.md", MODE1, occurred="2026-07-28")
    write_fact(bundle, "facts/m2.md", MODE2, occurred="2026-07-27")
    write_fact(bundle, "facts/m3.md", MODE3, occurred="2026-07-26")

    r = run_script(bundle, "build-index.py")
    if HAS_YAML:
        record("build-index.py names the unparseable files on stderr instead of falling back silently",
               "/facts/m1.md" in r.stderr and "/facts/m3.md" in r.stderr and "WARNING" in r.stderr,
               r.stderr)
    else:
        skip("build-index.py names the unparseable files on stderr",
             "needs PyYAML — without it nothing raises, so there is no per-file warning to emit")

    rows = manifest_rows(bundle)
    record("no literal-quote artifacts in manifest.jsonl (the reported grep signal)",
           all(not any(e.startswith("'") or e.startswith('"') for e in row["entities"])
               for row in rows),
           [row["entities"] for row in rows])

    block = auto_facts_block(bundle)
    linked = set(re.findall(r"\]\((/facts/[^)]+)\)", block))
    record("all three facts reach the entity hub's auto-facts block "
           "(52 of 53 hubs regenerated empty before this fix)",
           linked == {"/facts/m1.md", "/facts/m2.md", "/facts/m3.md"}, sorted(linked))

    # Asserted on BOTH parsers since 0.1.0-beta.12: this used to be skipped
    # without PyYAML, because the naive parser kept the comment and so never
    # truncated. That divergence was the bug — the fallback now strips trailing
    # comments the same way, so both paths damage mode 2 identically and the
    # repair below is what fixes it on both.
    truncated = [r_["desc"] for r_ in rows if r_["path"] == "/facts/m2.md"][0]
    record("mode 2 is still truncated before repair (the silent one — motivates the check), "
           "with either parser", truncated == "Angelo asked for help in", truncated)

    run_script(bundle, "validate-okf.py", ["--fix"])
    run_script(bundle, "build-index.py")
    after = {r_["path"]: r_["desc"] for r_ in manifest_rows(bundle)}
    record("after --fix + rebuild, mode 2's description is whole again",
           after["/facts/m2.md"] == "Angelo asked for help in #suporte-produto about the export",
           after.get("/facts/m2.md"))
    record("after --fix + rebuild, mode 3 keeps its inner quotes",
           after["/facts/m3.md"] ==
           'Thayane took the informal role of "Chief Legal Officer", automating',
           after.get("/facts/m3.md"))
    record("after --fix + rebuild, build-index.py emits no YAML warning",
           "not valid YAML" not in run_script(bundle, "build-index.py").stderr)


# ---------------------------------------------------------------------------
# f2. unquote(): what the naive parser makes of a properly quoted value
# ---------------------------------------------------------------------------

def test_unquote_round_trips_fix_output(root):
    """The fallback parser must read back exactly what `--fix` writes. --fix
    emits JSON-escaped values (`"she said \\"ship it\\""`), so without
    unescaping, every description on a machine lacking PyYAML would render with
    visible backslashes — a regression introduced BY the repair path."""
    for script in ("build-index.py", "briefing.py"):
        spec = importlib.util.spec_from_file_location(
            "uq_" + script.replace(".", "_"), ASSETS / "scripts" / script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cases = [
            ('"/entities/person/x.md"', "/entities/person/x.md", "double-quoted link"),
            ("'/entities/person/x.md'", "/entities/person/x.md", "single-quoted link"),
            ('"Angelo asked for help: the export failed"',
             "Angelo asked for help: the export failed", "quoted value with a colon"),
            ('"she said \\"ship it\\" on Friday"', 'she said "ship it" on Friday',
             "escaped inner quotes (exactly what --fix writes)"),
            ("'she said \"ship it\"'", 'she said "ship it"', "single-quoted with inner quotes"),
            ("'it''s shipped'", "it's shipped", "single-quoted with doubled apostrophe"),
            ('"a back\\\\slash"', "a back\\slash", "escaped backslash"),
            ('"literal \\n stays literal"', "literal \\n stays literal",
             "non-quote escape passed through, not guessed at"),
            ("unquoted stays as-is", "unquoted stays as-is", "unquoted value untouched"),
            ('"mismatched\'', '"mismatched\'', "mismatched quotes left alone"),
        ]
        for raw, want, label in cases:
            got = mod.unquote(raw)
            record(f"{script}: unquote — {label}", got == want, f"want={want!r}\ngot ={got!r}")


# ---------------------------------------------------------------------------
# f. missing PyYAML warns instead of degrading quietly
# ---------------------------------------------------------------------------

def test_missing_pyyaml_warns(root):
    bundle = new_bundle(root, "no-pyyaml")
    write_entity(bundle)
    write_fact(bundle, "facts/m1.md", MODE1)

    for script in ("build-index.py", "briefing.py"):
        r = run_script(bundle, script, ["--days", "7"] if script == "briefing.py" else None,
                       block_yaml=True)
        record(f"{script}: warns on stderr when PyYAML is missing",
               "PyYAML is not installed" in r.stderr, r.stderr)
        record(f"{script}: still succeeds — the fallback stays a supported path",
               r.returncode == 0, r.stdout + r.stderr)

    # Bundle-wide variant: with no PyYAML every file takes the naive parser, so
    # unquote() is what keeps quoted links resolving at all.
    rows = manifest_rows(bundle)
    record("no-PyYAML rebuild leaves no literal-quote artifacts in manifest.jsonl",
           rows and all(e == ENTITY_LINK for row in rows for e in row["entities"]),
           [row["entities"] for row in rows])
    record("no-PyYAML rebuild reaches the hub's auto-facts block",
           "/facts/m1.md" in auto_facts_block(bundle), auto_facts_block(bundle))


# ---------------------------------------------------------------------------
# g. the fallback parser strips trailing YAML comments, exactly where PyYAML does
# ---------------------------------------------------------------------------

def fallback_parsers():
    """Both shipped copies of the fallback parser, loaded in-process with `yaml`
    forced to None so parse_fm() takes the naive path. The copies are deliberate
    — bundle scripts are standalone and stdlib-only, and are copied into every
    bundle — so each is exercised on its own rather than assumed identical."""
    mods = []
    for script in ("build-index.py", "briefing.py"):
        spec = importlib.util.spec_from_file_location(
            "fb_" + script.replace(".", "_"), ASSETS / "scripts" / script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.yaml = None
        mods.append((script, mod))
    return mods


def test_fallback_strips_trailing_comments(root):
    """The fallback parser kept the trailing comment our own templates carry, so
    on any machine without PyYAML — the ordinary local case — `kind`, `aliases`
    and `status` were all read wrong. The cases below are the three damages plus
    every shape a greedy cut would break."""
    stripped = [
        # The three damages, verbatim from plugin/assets/templates/.
        ("kind", "kind: concept         # person | org | project | tool | concept | event | place",
         "concept", "enum reached the roster with its whole vocabulary glued on"),
        ("aliases", "aliases: []           # other names/spellings used for this entity",
         [], "inline list stopped matching INLINE_LIST and became one long string"),
        ("status", "status: open          # open | done | dropped",
         "open", "the open loop was invisible to the open-loop surface"),
        # The same rule on every other shape a frontmatter block holds.
        ("occurred", "occurred: 2026-06-24  # when it happened", "2026-06-24", "date"),
        ("tags", "tags: [a, b]          # a couple of tags", ["a", "b"], "populated inline list"),
        ("title", 'title: "Jane Doe"     # the display name', "Jane Doe", "double-quoted scalar"),
        ("title", "title: 'Jane Doe'     # the display name", "Jane Doe", "single-quoted scalar"),
        ("entities", "entities: ['/a.md']   # bundle-absolute links", ["/a.md"],
         "inline list of quoted links"),
        ("description", "description: -5% growth in Q3  # measured", "-5% growth in Q3",
         "plain scalar that opens on a `-`"),
        ("sources", "sources:\n  - /sources/a.md     # first\n  - /sources/b.md",
         ["/sources/a.md", "/sources/b.md"], "block-sequence items, per item"),
    ]
    kept = [
        ("resource", 'resource: "slack:#canal"', "slack:#canal",
         "a `#` inside quotes is content, never a comment"),
        ("description", 'description: "vale #123"', "vale #123", "issue number inside quotes"),
        ("channel", 'channel: "slack:#a, #b"   # where it came from', "slack:#a, #b",
         "content hashes kept, the real trailing comment cut"),
        ("issue", "issue: see ticket (#9-channel) for details",
         "see ticket (#9-channel) for details", "a `#` with no space before it is content"),
        ("description", 'description: "a # b"', "a # b",
         "even ` #` survives inside quotes — the greedy-cut regression"),
        ("aliases", 'aliases: ["a #b", "c"]', ["a #b", "c"],
         "a `#` inside a quoted inline-list item"),
        ("sources", 'sources:\n  - "/sources/b #2.md"', ["/sources/b #2.md"],
         "a `#` inside a quoted block-sequence item"),
        ("description", 'description: "never closed # x', '"never closed # x',
         "an unterminated quote is kept verbatim, not guessed away"),
    ]
    for script, mod in fallback_parsers():
        for key, line, want, why in stripped:
            got = mod.parse_fm(line + "\n").get(key)
            record(f"{script}: comment stripped — {why}", got == want,
                   f"line={line!r}\nwant={want!r}\ngot ={got!r}")
        for key, line, want, why in kept:
            got = mod.parse_fm(line + "\n").get(key)
            record(f"{script}: NOT cut — {why}", got == want,
                   f"line={line!r}\nwant={want!r}\ngot ={got!r}")


# The oracle for the fallback: one block carrying every shape at once. PyYAML is
# the reference implementation, so for a block PyYAML accepts, the two parsers
# must agree on every scalar and list.
ORACLE_BLOCK = """type: entity
kind: concept         # person | org | project | tool | concept | event | place
title: "<display name, e.g. Jane Doe>"
description: "Angelo asked for help in #suporte about the export"
aliases: []           # other names/spellings used for this entity
tags: [alpha, beta]   # a couple of tags
status: open          # open | done | dropped
resource: "slack:#canal"
channel: "slack:#a, #b"   # where it came from
issue: see ticket (#9-channel) for details
entities: ['/entities/person/x.md', "/entities/org/y.md"]
sources:
  - /sources/a.md     # first
  - "/sources/b #2.md"
occurred: 2026-06-24  # when it happened
"""


def norm(v):
    """A parsed value as the scripts consume it. PyYAML types `2026-06-24` as a
    datetime.date and the fallback keeps the string; every reader runs both
    through str() (as_list, to_date, the manifest writer), so that difference is
    not one of theirs and is normalized away here."""
    return [str(x) for x in v] if isinstance(v, list) else str(v)


def test_fallback_agrees_with_pyyaml(root):
    if not HAS_YAML:
        skip("the fallback parser agrees with PyYAML field by field",
             "needs PyYAML — it is the oracle; this leg has only the parser under test")
        return
    for script in ("build-index.py", "briefing.py"):
        spec = importlib.util.spec_from_file_location(
            "or_" + script.replace(".", "_"), ASSETS / "scripts" / script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        reference = mod.parse_fm(ORACLE_BLOCK)
        mod.yaml = None
        fallback = mod.parse_fm(ORACLE_BLOCK)
        diffs = [f"{k}: pyyaml={reference.get(k)!r} fallback={fallback.get(k)!r}"
                 for k in sorted(set(reference) | set(fallback))
                 if norm(reference.get(k, "<absent>")) != norm(fallback.get(k, "<absent>"))]
        record(f"{script}: the fallback parser agrees with PyYAML on every field "
               f"of a block carrying all of them ({len(reference)} keys)",
               not diffs, "\n".join(diffs))


# The four templates, filed where init/ingest puts a document of each type —
# the same mount tests/test_templates.py builds.
TEMPLATE_DEST = {
    "entity.md": "knowledge/entities/concept/t.md",
    "fact.md": "knowledge/facts/t.md",
    "open-loop.md": "knowledge/tracking/loops/t.md",
    "source.md": "knowledge/sources/t.md",
}


def test_templates_bundle_without_pyyaml(root):
    """The CI scenario, pinned on every leg.

    tests/test_templates.py mounts this same bundle but takes whichever parser
    the machine has, so it only ever saw this on the `pyyaml=false` legs — where
    the entity's kind, the entity's aliases and the open loop's status were all
    misread. Forcing the fallback keeps the check honest where PyYAML is
    installed, which is CI's other three legs and most development machines
    after `pip install pyyaml`."""
    bundle = root / "templates-no-pyyaml"
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    for f in (ASSETS / "scripts").glob("*.py"):
        shutil.copy2(f, bundle / "scripts" / f.name)
    shutil.copy2(ASSETS / "vocab.json", bundle / "vocab.json")
    for name, dest in TEMPLATE_DEST.items():
        target = bundle / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ASSETS / "templates" / name, target)

    r = run_script(bundle, "build-index.py", block_yaml=True)
    record("templates bundle, PyYAML forced absent: one document of each type — "
           "the open loop counted 0 while `status: open  # open | done | dropped` "
           "did not equal `open`",
           "1 entities, 1 facts, 1 open loops, 1 sources" in r.stdout, r.stdout + r.stderr)

    rows = (bundle / "knowledge" / "entities" / "roster.tsv").read_text(
        encoding="utf-8").splitlines()
    record("…and the roster row carries the bare kind, the title, and an empty "
           "aliases column — not the vocabulary comment and the `[]` explainer",
           len(rows) == 2
           and rows[1].split("\t") == ["t", "concept", "<display name, e.g. Jane Doe>", ""],
           repr(rows))

    loops = [row for row in manifest_rows(bundle) if row["type"] == "open-loop"]
    record("…and the open loop reaches manifest.jsonl with status `open` "
           "(it was absent entirely before)",
           len(loops) == 1 and loops[0]["status"] == "open" and
           loops[0]["path"] == "/tracking/loops/t.md",
           loops)


# ---------------------------------------------------------------------------
# h. the same rule, in the scripts that read frontmatter by regex
# ---------------------------------------------------------------------------
# parse_fm() is not the only reader. rename-entity.py, decay-loops.py,
# snapshot-drift.py and validate-okf.py each pick fields straight out of the
# block with their own regex, and none of them knew about the comment. The
# damage ranged from an advisory going quiet to rename-entity.py replacing an
# entity's whole alias list instead of extending it.

# Verbatim from plugin/assets/templates/ — the comment a bundle file ordinarily
# keeps, since it is the documentation the model reads while filling the file in.
C_KIND = "         # person | org | project | tool | concept | event | place"
C_ALIASES = "           # other names/spellings used for this entity (entity resolution)"
C_ENTITIES = "          # bundle-absolute links, e.g. [/entities/person/foo.md]"
C_STATUS = "        # active | deprecated | superseded"
C_OCCURRED = "     # when the content actually happened / was said (ISO; ≠ created)"


def load_script(script_name):
    """One shipped script, loaded in-process to reach its pure functions."""
    spec = importlib.util.spec_from_file_location(
        "rx_" + re.sub(r"\W", "_", script_name), ASSETS / "scripts" / script_name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# (raw value after `key: `, what the reader must see). Half of these are the
# damages; the rest are the greedy cut that is this change's obvious regression.
STRIP_CASES = [
    ("concept" + C_KIND, "concept", "the enum, not its whole vocabulary"),
    ("[]" + C_ALIASES, "[]", "an empty inline list stays empty"),
    ('["Tee", "T."]' + C_ALIASES, '["Tee", "T."]',
     "a populated inline list ends at its own `]`"),
    ("[/entities/person/a.md]" + C_ENTITIES, "[/entities/person/a.md]",
     "…even when the comment itself carries a `[`…`]`"),
    ("active" + C_STATUS, "active", "the status, not the status vocabulary"),
    ("2026-06-24" + C_OCCURRED, "2026-06-24",
     "a date that must still compare as a date"),
    ('"Acme"  # canonical spelling', '"Acme"', "a quoted scalar, comment after the quote"),
    # Must NOT be cut. A `#` is content unless a space opens it, and always
    # inside quotes — cutting greedily is how this fix would regress.
    ('"slack:#canal"', '"slack:#canal"', "a `#` inside quotes is content"),
    ('"vale #123"', '"vale #123"', "an issue number inside quotes"),
    ('"a # b"', '"a # b"', "even ` #` survives inside quotes"),
    ("see ticket (#9-channel) for details", "see ticket (#9-channel) for details",
     "a `#` with no space before it is content"),
    ('["a #b", "c"]', '["a #b", "c"]', "a `#` inside a quoted inline-list item"),
    ('["a]b", "c"]  # two names', '["a]b", "c"]', "a `]` inside a quoted item is content"),
    ('"never closed # x', '"never closed # x',
     "an unterminated quote is kept verbatim, not guessed away"),
]


def test_regex_readers_share_the_rule(root):
    """Every copy of the rule agrees with build-index.py's, case for case.

    The copies are deliberate — bundle scripts are standalone, stdlib-only, and
    are copied into every user's bundle — so each is exercised on its own rather
    than assumed identical. rename-entity.py's is split_comment(), which returns
    the comment too because that script also writes the line back."""
    copies = [(name, load_script(name).strip_comment) for name in
              ("build-index.py", "briefing.py", "validate-okf.py",
               "snapshot-drift.py", "decay-loops.py", "close-loops.py")]
    renamer = load_script("rename-entity.py")
    copies.append(("rename-entity.py", lambda v: renamer.split_comment(v)[0].strip()))

    for name, fn in copies:
        for raw, want, why in STRIP_CASES:
            got = fn(raw)
            record(f"{name}: {why}", got == want, f"raw={raw!r}\nwant={want!r}\ngot ={got!r}")

    # split_comment() is a split, not a strip: the two halves must rebuild the
    # line, or rename-entity.py would drop the comment every time it rewrites.
    bad = [raw for raw, _w, _y in STRIP_CASES
           if "".join(renamer.split_comment(raw)) != raw.rstrip()]
    record("rename-entity.py: value + comment reconstructs the line verbatim, "
           "so a rewrite keeps the documentation the template put there",
           not bad, bad)


def write_drift_fact(bundle, rel, desc, entities=(), relates_to=(),
                     status="active", updated=TODAY, occurred=None):
    """A fact in the shape fact.md ships — trailing comments and all."""
    path = bundle / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tags = "[snapshot]" if "snapshot" in rel else "[]"
    path.write_text(
        "---\n"
        "type: fact\n"
        f'description: "{desc}"\n'
        f"entities: [{', '.join(entities)}]{C_ENTITIES}\n"
        "relations:\n"
        "  supersedes: []\n"
        f"  relates-to: [{', '.join(relates_to)}]\n"
        f"confidence: medium    # low | medium | high\n"
        f"status: {status}{C_STATUS}\n"
        f"tags: {tags}\n"
        f"created: {updated}\nupdated: {updated}\n"
        f"occurred: {occurred or updated}{C_OCCURRED}\n"
        "---\n\nBody.\n",
        encoding="utf-8")
    return path


def test_snapshot_drift_reads_the_template_shape(root):
    """snapshot-drift.py's two readers, on facts that kept their comments.

    Each case is paired with the opposite verdict on the same wiring, so the
    suite cannot be satisfied by a script that has simply gone silent."""
    A, B, C = ("/entities/person/a.md", "/entities/person/b.md", "/entities/person/c.md")

    # 1. shared-entities: the comment carries a `[`…`]` of its own, so the old
    #    reader swallowed it into the list and two facts sharing ONE entity
    #    "shared" the comment's words as well — over the threshold, false drift.
    b1 = new_bundle(root, "drift-share")
    write_drift_fact(b1, "facts/snapshot.md", "who owns what", entities=(A, B),
                     updated="2026-06-01")
    write_drift_fact(b1, "facts/f.md", "one entity in common", entities=(A, C),
                     updated="2026-07-01")
    out = run_script(b1, "snapshot-drift.py").stdout
    record("snapshot-drift: one shared entity is below the threshold — the "
           "`# bundle-absolute links, e.g. [...]` comment is not a shared entity",
           "0 of 1 snapshot(s) may have drifted." in out, out)

    b2 = new_bundle(root, "drift-share-true")
    write_drift_fact(b2, "facts/snapshot.md", "who owns what", entities=(A, B),
                     updated="2026-06-01")
    write_drift_fact(b2, "facts/f.md", "two entities in common", entities=(A, B),
                     updated="2026-07-01")
    out = run_script(b2, "snapshot-drift.py").stdout
    record("…and two genuinely shared entities still raise the signal, which "
           "the old reader could only reach through the comment",
           "1 shared-entities" in out and "1 of 1 snapshot(s) may have drifted." in out,
           out)

    # 2. `occurred` glued to its comment sorts ABOVE a bare date, so a fact from
    #    the very day the snapshot was tended reported it as drifted.
    b3 = new_bundle(root, "drift-sameday")
    write_drift_fact(b3, "facts/snapshot.md", "who owns what", updated="2026-06-24")
    write_drift_fact(b3, "facts/f.md", "same day", relates_to=("/facts/snapshot.md",),
                     updated="2026-06-24")
    out = run_script(b3, "snapshot-drift.py").stdout
    record("snapshot-drift: a same-day fact is not newer than the snapshot — "
           "`2026-06-24  # when the content…` no longer sorts above `2026-06-24`",
           "0 of 1 snapshot(s) may have drifted." in out, out)

    b4 = new_bundle(root, "drift-newer")
    write_drift_fact(b4, "facts/snapshot.md", "who owns what", updated="2026-06-24")
    write_drift_fact(b4, "facts/f.md", "genuinely newer",
                     relates_to=("/facts/snapshot.md",), updated="2026-07-01")
    out = run_script(b4, "snapshot-drift.py").stdout
    record("…and a genuinely newer one still drifts, reported with a clean date",
           "1 of 1 snapshot(s) may have drifted." in out and "2026-07-01  /facts/f.md" in out,
           out)

    # 3. `status` glued to its comment never equalled `deprecated`, so a retired
    #    fact was still counted as a live drift signal.
    b5 = new_bundle(root, "drift-deprecated")
    write_drift_fact(b5, "facts/snapshot.md", "who owns what", updated="2026-06-01")
    write_drift_fact(b5, "facts/d.md", "a retired claim", status="deprecated",
                     relates_to=("/facts/snapshot.md",), updated="2026-07-01")
    out = run_script(b5, "snapshot-drift.py").stdout
    record("snapshot-drift: a `deprecated` fact is skipped even when it kept "
           "`# active | deprecated | superseded` on the line",
           "0 of 1 snapshot(s) may have drifted." in out, out)


def write_template_entity(bundle, rel, title, aliases='[]' + C_ALIASES):
    """An entity in the shape entity.md ships. `aliases` is injected verbatim so
    a test can plant a block sequence or a broken line."""
    path = bundle / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "type: entity\n"
        f"kind: concept{C_KIND}\n"
        f'title: {title}\n'
        'description: "a thing"\n'
        f"aliases: {aliases}\n"
        "tags: []\n"
        f"created: {TODAY}\nupdated: {TODAY}\n"
        "---\n\nBody.\n",
        encoding="utf-8")
    return path


def aliases_line(path):
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("aliases:"):
            return ln
    return "<no aliases line>"


def test_rename_entity_merges_through_the_comment(root):
    """The destructive one: merge_aliases() read `^aliases:…\\]\\s*$`, which does
    not match a line that kept its comment. `existing` fell to [], and the write
    that follows REPLACED the line — exit 0, no warning, every accumulated alias
    gone. Aliases are the roster's resolution surface, and a resolution that
    fails is what makes an ingestion invent a duplicate entity."""
    bundle = new_bundle(root, "rename-merge")
    write_template_entity(bundle, "entities/concept/t.md", '"Tee"',
                          aliases='["Tee", "T."]' + C_ALIASES)
    r = run_script(bundle, "rename-entity.py", ["t", "t2", "--alias", "Newname"])
    line = aliases_line(bundle / "knowledge" / "entities" / "concept" / "t2.md")
    record("rename-entity: --alias EXTENDS the existing aliases on an entity "
           "that kept its template comment (it used to replace them)",
           r.returncode == 0 and line.startswith('aliases: ["Tee", "T.", Newname]'),
           f"exit={r.returncode}\nline={line!r}\n{r.stdout}{r.stderr}")
    record("…and the trailing comment survives the rewrite, so the file keeps "
           "the documentation its template put there",
           line.endswith(C_ALIASES.strip()) or C_ALIASES.strip() in line, repr(line))

    # Fail closed. A regex that misses again must stop, not erase — so an
    # `aliases:` line that is present but not an inline list is refused.
    bundle = new_bundle(root, "rename-blockseq")
    ent = write_template_entity(bundle, "entities/concept/t.md", '"Tee"',
                                aliases="\n  - Tee\n  - T.")
    before = ent.read_text(encoding="utf-8")
    r = run_script(bundle, "rename-entity.py", ["t", "t2", "--alias", "Newname"])
    after = (bundle / "knowledge" / "entities" / "concept" / "t2.md").read_text(
        encoding="utf-8")
    record("rename-entity: an `aliases:` line it cannot read is refused, not "
           "overwritten — non-zero exit and the frontmatter untouched",
           r.returncode != 0 and "refusing" in r.stderr and after == before,
           f"exit={r.returncode}\nstderr={r.stderr}\n{after}")

    # …and on the --merge path the refusal must come BEFORE the source entity is
    # deleted, or the collapse would cost a file and gain nothing.
    bundle = new_bundle(root, "rename-merge-refuse")
    src = write_template_entity(bundle, "entities/concept/x.md", '"Ex"')
    write_template_entity(bundle, "entities/concept/y.md", '"Why"',
                          aliases="\n  - Why\n  - Y.")
    r = run_script(bundle, "rename-entity.py", ["x", "y", "--merge", "--alias", "Ex"])
    record("rename-entity --merge: a refused alias merge does not delete the "
           "source entity it was collapsing",
           r.returncode != 0 and src.exists(),
           f"exit={r.returncode}\nsrc exists={src.exists()}\n{r.stderr}")


def collisions(bundle):
    out = run_script(bundle, "validate-okf.py").stdout
    return [ln.strip() for ln in out.splitlines() if "collision" in ln]


def test_validator_sees_collisions_through_the_comment(root):
    """alias/title collision is the warning that exposes entity conflation, and
    it went blind on exactly the files most likely to be conflated: the ones a
    model wrote from the template and left the comment on."""
    bundle = new_bundle(root, "collide-alias")
    write_template_entity(bundle, "entities/concept/x.md", '"Ex"',
                          aliases='["Shared Name"]' + C_ALIASES)
    write_template_entity(bundle, "entities/concept/y.md", '"Why"',
                          aliases='["Shared Name"]' + C_ALIASES)
    hits = collisions(bundle)
    record("validate-okf: two entities sharing an alias collide even though "
           "both kept `# other names/spellings…` after the `]`",
           any("Shared Name" in h for h in hits), hits)

    bundle = new_bundle(root, "collide-title")
    write_template_entity(bundle, "entities/concept/x.md", '"Acme"  # canonical spelling')
    write_template_entity(bundle, "entities/concept/y.md", '"Acme"')
    hits = collisions(bundle)
    record("validate-okf: a title carrying a trailing comment still collides "
           "with the same title without one — the comment is not part of the key",
           any("Acme" in h for h in hits), hits)

    # The greedy-cut regression, at the surface that would suffer it: an alias
    # whose `#` is content must still be compared whole.
    bundle = new_bundle(root, "collide-hash")
    write_template_entity(bundle, "entities/concept/x.md", '"Ex"',
                          aliases='["canal #growth"]' + C_ALIASES)
    write_template_entity(bundle, "entities/concept/y.md", '"Why"',
                          aliases='["canal #growth"]' + C_ALIASES)
    hits = collisions(bundle)
    record("validate-okf: an alias whose ` #` is content collides on the whole "
           "alias — a greedy cut would compare `canal` and miss nothing else",
           any("canal #growth" in h for h in hits), hits)

    bundle = new_bundle(root, "collide-none")
    write_template_entity(bundle, "entities/concept/x.md", '"Ex"',
                          aliases='["Exeter"]' + C_ALIASES)
    write_template_entity(bundle, "entities/concept/y.md", '"Why"',
                          aliases='["Wyoming"]' + C_ALIASES)
    record("…and distinct names still collide with nothing — the warning did "
           "not simply learn to fire",
           collisions(bundle) == [], collisions(bundle))


def main():
    print("elephant-mem test_frontmatter — YAML-safe frontmatter (validate-okf rule 5)")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print(f"PyYAML:   {'present' if HAS_YAML else 'ABSENT — a few PyYAML-specific checks will skip'}")
    print()

    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-mem-test-frontmatter-"))
    print(f"scratch root: {scratch_root}\n")

    for fn in (
        test_three_modes_fail_validation,
        test_safe_shapes_not_flagged,
        test_shipped_templates_are_safe,
        test_fix_repairs_and_preserves,
        test_end_to_end_hub_and_manifest,
        test_unquote_round_trips_fix_output,
        test_missing_pyyaml_warns,
        test_fallback_strips_trailing_comments,
        test_fallback_agrees_with_pyyaml,
        test_templates_bundle_without_pyyaml,
        test_regex_readers_share_the_rule,
        test_snapshot_drift_reads_the_template_shape,
        test_rename_entity_merges_through_the_comment,
        test_validator_sees_collisions_through_the_comment,
    ):
        guarded(fn, scratch_root)

    print()
    print("Summary")
    print("-------")
    n_pass = 0
    for label, passed in checks:
        if passed:
            n_pass += 1
        print(f"  {'PASS' if passed else 'FAIL':4s}  {label}")
    for label, why in skipped:
        print(f"  SKIP  {label} — {why}")
    total = len(checks)
    print(f"\n{n_pass}/{total} checks passed"
          + (f", {len(skipped)} skipped." if skipped else "."))
    shutil.rmtree(scratch_root, ignore_errors=True)
    return 0 if n_pass == total and total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
