#!/usr/bin/env python3
"""Targeted regression tests for the derived-surfaces pipeline in
plugin/assets/scripts/ — complements tests/smoke.py (end-to-end happy path)
by covering the specific bug fixes and new behavior below:

  1. Block-style YAML sequences (`entities:\n  - /a.md`) in frontmatter list
     fields, not just inline `entities: [/a.md]`.
  2. Auto-facts marker injection: an entity/source file created without the
     `<!-- BEGIN auto-facts -->` marker gets one appended instead of silently
     never receiving backlinks.
  3. Hub sharding: an entity/source referenced by more than `hub_max_facts`
     active facts keeps only the N most recent inline and moves the rest
     (older actives + all history) to a sibling `<slug>.facts-archive.md`.
  4. vocab.json: validate-okf.py WARNs (never fails) on out-of-vocab values;
     an `expired` loop reads as history with AND without vocab.json (the
     hardcoded loop_status default is what runs in the field, since no bundle
     had ever received the file), and `init` is the procedure that copies it.
  4c. tracking/resolved-loops.md: the archive of done/dropped/expired loops —
     newest first, date + outcome + the first sentence of the resolution, the
     loops gone from the entity hubs and from briefing.py's `## Open loops`,
     and the overflow past `index.resolved_max` in a sibling archive shard.
  4d. One loop-status rule: the open partition (board, manifest, entity hubs)
     and the resolved page are complements of a single normalized comparison,
     so `status: Open` or a padded `open ` cannot fall out of both at once.
  4e. …and the rule's two implementations agree: build-index.py's loop_status()
     and briefing.py's is_resolved() are hand-copied twins across scripts that
     share no module, so one bundle is rendered through both and the partitions
     compared.
  4f. The same one-rule property for FACTS: active(), the entity hub's
     is_history() and briefing.py's is_history() read one normalized value, so
     `status: Superseded` cannot be current in the manifest and history on the
     hub in the same build, and a padded `superseded ` is not published as
     current.
  5. entities/roster.tsv: the resolution surface — one four-column row per
     ACTIVE entity, sorted by kind then title, with the trailing tab of an
     empty `aliases` column surviving, grid-breaking characters sanitized,
     the catalog left untouched and validate-okf.py still clean.

Pure stdlib, Python 3.10+, same scaffolding style as tests/smoke.py: every
check builds its own throwaway bundle under a tempdir and drives the shipped
scripts via subprocess (sys.executable) — no shell-outs, no third-party deps.

Exit code 0 only if every check below passes.
"""
import datetime
import importlib.util
import json
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
MONTH = datetime.date.today().strftime("%Y-%m")

checks = []


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    return passed


def run_script(bundle, script_name, args=None):
    script = bundle / "scripts" / script_name
    return subprocess.run(
        [sys.executable, str(script)] + (args or []),
        cwd=str(bundle), capture_output=True, text=True, encoding="utf-8",
    )


def new_bundle(root, name, with_vocab=False, hub_max_facts=None, resolved_max=None):
    """Minimal throwaway bundle: shipped scripts + a reserved log.md, nothing
    else — each test seeds only the knowledge/ files it needs."""
    bundle = root / name
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    for f in ("build-index.py", "briefing.py", "validate-okf.py"):
        shutil.copy2(ASSETS / "scripts" / f, bundle / "scripts" / f)
    if with_vocab:
        shutil.copy2(ASSETS / "vocab.json", bundle / "vocab.json")
    if hub_max_facts is not None or resolved_max is not None:
        write_index_config(bundle, hub_max_facts=hub_max_facts, resolved_max=resolved_max)
    (bundle / "knowledge").mkdir(parents=True, exist_ok=True)
    (bundle / "knowledge" / "log.md").write_text("# Log\n", encoding="utf-8")
    return bundle


def write_index_config(bundle, hub_max_facts=None, resolved_max=None):
    """(Re)write elephant.json's `index` section. Its own function because the
    overflow test rebuilds the SAME bundle under a larger `resolved_max`, to
    prove a shard that is no longer needed is deleted rather than left behind."""
    index = {}
    if hub_max_facts is not None:
        index["hub_max_facts"] = hub_max_facts
    if resolved_max is not None:
        index["resolved_max"] = resolved_max
    (bundle / "elephant.json").write_text(
        json.dumps({"index": index}) + "\n", encoding="utf-8"
    )


MARKER = (
    "\n<!-- BEGIN auto-facts -->\n"
    "<!-- Regenerated by scripts/build-index.py — do not edit by hand. -->\n"
    "<!-- END auto-facts -->\n"
)


# A bare-token alias: safe both as an inline-list item (which both frontmatter
# parsers split on the comma) and as a plain YAML scalar.
SIMPLE_ALIAS = re.compile(r"^[A-Za-z0-9 ._-]+$")


def _yaml_quote(s):
    """Double-quote a scalar, escaping `\\` and `"` and nothing else — the two
    escapes build-index.py's BOTH frontmatter paths agree on (PyYAML's, and the
    naive fallback's unquote()). A `\\t` escape would not: PyYAML reads it as a
    tab, the fallback leaves it literal."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _yaml_scalar(s):
    """A frontmatter value: plain when that is safe, quoted when it is not. Only
    a literal tab or an inner quote forces quoting (PyYAML rejects a plain scalar
    holding a tab outright), so every file the other tests write stays
    byte-identical to what they wrote before these parameters existed."""
    s = str(s)
    return _yaml_quote(s) if ("\t" in s or '"' in s) else s


def _aliases_lines(aliases):
    """The `aliases:` frontmatter line(s). Inline (`aliases: [a, b]`) while every
    alias is a bare token — the shape a real bundle carries, and the only inline
    shape validate-okf.py's collision check reads — and a quoted block sequence
    once one alias holds a comma or a tab, since an inline list is comma-split by
    both parsers and so could never carry a comma INSIDE an alias."""
    if not aliases:
        return "aliases: []\n"
    if all(SIMPLE_ALIAS.match(a) for a in aliases):
        return "aliases: [" + ", ".join(aliases) + "]\n"
    return "aliases:\n" + "".join(f"  - {_yaml_quote(a)}\n" for a in aliases)


def write_entity(bundle, rel, title, kind="person", with_marker=True,
                 aliases=None, status=None):
    text = (
        "---\n"
        "type: entity\n"
        f"kind: {kind}\n"
        f"title: {_yaml_scalar(title)}\n"
        f"description: {_yaml_scalar(str(title) + '.')}\n"
        + _aliases_lines(aliases)
        + (f"status: {status}\n" if status else "")
        + "tags: []\n"
        f"created: {TODAY}\n"
        f"updated: {TODAY}\n"
        f"timestamp: {TODAY}\n"
        "---\n\n"
        f"{title} — test entity.\n"
        f"{MARKER if with_marker else ''}"
    )
    path = bundle / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_fact(bundle, rel, desc, entities_yaml, status="active", confidence="high", occurred=None):
    text = (
        "---\n"
        "type: fact\n"
        f"description: {desc}\n"
        f"{entities_yaml}"
        f"confidence: {confidence}\n"
        f"status: {status}\n"
        "tags: []\n"
        f"created: {TODAY}\n"
        f"updated: {TODAY}\n"
        f"timestamp: {TODAY}\n"
        f"occurred: {occurred or TODAY}\n"
        "---\n\n"
        f"{desc}\n"
    )
    path = bundle / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_open_loop(bundle, rel, desc, entities_yaml, status="open",
                    closed=None, expired=None, updated=None, resolution=None):
    """A loop file. `closed` / `expired` are the frontmatter dates the two
    writers stamp; `resolution` is the `**Resolution:**` body paragraph they
    append after it — prose, never a frontmatter field (see the loop template's
    three lines of warning about `: ` and ` #`)."""
    text = (
        "---\n"
        "type: open-loop\n"
        f"description: {desc}\n"
        f"{entities_yaml}"
        f"status: {status}\n"
        f"opened: {TODAY}\n"
        + (f"closed: {closed}\n" if closed else "")
        + (f"expired: {expired}\n" if expired else "")
        + "tags: []\n"
        f"created: {TODAY}\n"
        f"updated: {updated or TODAY}\n"
        f"timestamp: {TODAY}\n"
        "---\n\n"
        f"{desc}\n"
        + (f"\n**Resolution:** {resolution}\n" if resolution else "")
    )
    path = bundle / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_source(bundle, rel, desc, source_kind="note"):
    text = (
        "---\n"
        "type: source\n"
        f"description: {desc}\n"
        "resource: https://example.com/test\n"
        f"source-kind: {source_kind}\n"
        "channel: manual\n"
        f"occurred: {TODAY}\n"
        f"ingested: {TODAY}\n"
        "tags: []\n"
        f"created: {TODAY}\n"
        f"updated: {TODAY}\n"
        f"timestamp: {TODAY}\n"
        "---\n\n"
        f"{desc}\n"
        f"{MARKER}"
    )
    path = bundle / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def load_script_module(script_name):
    """Import a hyphenated script (build-index.py, briefing.py) as a module, so
    its helpers can be unit-tested directly rather than only through a build."""
    path = ASSETS / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name.replace(".", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_module_forcing_no_yaml(script_name):
    """Import a hyphenated script (build-index.py, briefing.py) as a module
    with its `yaml` global forced to None, so parse_fm() exercises the
    hand-rolled fallback regardless of whether PyYAML happens to be installed
    in the environment running these tests (it is on this dev machine, but
    NOT in CI — see .github/workflows/ci.yml — and presumably not in most
    bundle environments either, which is how the reported bug went unnoticed)."""
    mod = load_script_module(script_name)
    mod.yaml = None
    return mod


# ---------------------------------------------------------------------------
# 1a. block-style YAML sequences — direct unit test of the fallback parser
#     (forces yaml=None so it can't be masked by PyYAML being installed)
# ---------------------------------------------------------------------------

def test_parse_fm_fallback_block_lists(root):
    for script_name in ("build-index.py", "briefing.py"):
        mod = load_module_forcing_no_yaml(script_name)

        block = (
            "type: fact\n"
            "description: block-style entities\n"
            "entities:\n"
            "  - /entities/person/alice.md\n"
            "  - /entities/org/acme.md\n"
            "tags: []\n"
        )
        fm = mod.parse_fm(block)
        record(
            f"{script_name}: fallback parser reads a block-sequence list (entities:)",
            fm.get("entities") == ["/entities/person/alice.md", "/entities/org/acme.md"],
            fm,
        )

        inline_block = "entities: [/a.md, /b.md]\ntags: []\n"
        fm_inline = mod.parse_fm(inline_block)
        record(
            f"{script_name}: fallback parser still reads inline lists (regression guard)",
            fm_inline.get("entities") == ["/a.md", "/b.md"],
            fm_inline,
        )

        empty_block = "owner:\ntags: []\n"
        fm_empty = mod.parse_fm(empty_block)
        record(
            f"{script_name}: fallback parser leaves a genuinely empty list field as \"\" (not a crash)",
            fm_empty.get("owner") == "" and fm_empty.get("tags") == [],
            fm_empty,
        )

        nested_block = (
            "relations:\n"
            "  supersedes: []\n"
            "  superseded-by: []\n"
            "confidence: high\n"
        )
        fm_nested = mod.parse_fm(nested_block)
        record(
            f"{script_name}: fallback parser leaves a nested mapping (relations:) as \"\" "
            "(unsupported, unchanged from before this fix)",
            fm_nested.get("relations") == "" and fm_nested.get("confidence") == "high",
            fm_nested,
        )


# ---------------------------------------------------------------------------
# 1b. block-style YAML sequences — end-to-end via build-index.py
# ---------------------------------------------------------------------------

def test_block_style_entities(root):
    bundle = new_bundle(root, "block-style")
    write_entity(bundle, "entities/person/alice.md", "Alice")
    write_fact(
        bundle, "facts/f1.md", "Alice said hi",
        entities_yaml="entities:\n  - /entities/person/alice.md\n",
    )
    result = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 (block-style entities)", result.returncode == 0,
                   result.stdout + result.stderr):
        return

    alice = (bundle / "knowledge" / "entities" / "person" / "alice.md").read_text(encoding="utf-8")
    record(
        "block-style `entities:` list produces a backlink into the entity file",
        "Alice said hi" in alice and "/facts/f1.md" in alice,
        alice,
    )

    manifest = (bundle / "knowledge" / "manifest.jsonl").read_text(encoding="utf-8")
    record(
        "fact with block-style entities still lands in manifest.jsonl with entities populated",
        '"entities":["/entities/person/alice.md"]' in manifest,
        manifest,
    )


# ---------------------------------------------------------------------------
# 2. auto-facts marker injection
# ---------------------------------------------------------------------------

def test_marker_injection(root):
    bundle = new_bundle(root, "marker-injection")
    write_entity(bundle, "entities/team/contexters.md", "Contexters", kind="team", with_marker=False)
    write_fact(
        bundle, "facts/f1.md", "Contexters shipped v1",
        entities_yaml="entities: [/entities/team/contexters.md]\n",
    )

    result = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 (markerless entity)", result.returncode == 0,
                   result.stdout + result.stderr):
        return

    record(
        "logs one line for the markerless entity it injected a marker into",
        "Injected auto-facts marker: /entities/team/contexters.md" in result.stdout,
        result.stdout,
    )

    path = bundle / "knowledge" / "entities" / "team" / "contexters.md"
    text = path.read_text(encoding="utf-8")
    record(
        "marker appended + backlink filled on first run",
        text.count("<!-- BEGIN auto-facts -->") == 1 and "Contexters shipped v1" in text,
        text,
    )

    result2 = run_script(bundle, "build-index.py")
    text2 = path.read_text(encoding="utf-8")
    record(
        "rerun is idempotent: marker not duplicated, no re-injection log line",
        text2.count("<!-- BEGIN auto-facts -->") == 1
        and "Injected auto-facts marker" not in result2.stdout,
        result2.stdout + "\n---\n" + text2,
    )


# ---------------------------------------------------------------------------
# 3. hub sharding
# ---------------------------------------------------------------------------

def test_hub_sharding(root):
    bundle = new_bundle(root, "hub-sharding", hub_max_facts=3)
    write_entity(bundle, "entities/org/acme.md", "Acme")

    dates = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
    for i, d in enumerate(dates, start=1):
        write_fact(
            bundle, f"facts/active-{i}.md", f"Acme active fact {i}",
            entities_yaml="entities: [/entities/org/acme.md]\n", occurred=d,
        )
    for i in (1, 2):
        write_fact(
            bundle, f"facts/history-{i}.md", f"Acme history fact {i}",
            entities_yaml="entities: [/entities/org/acme.md]\n",
            status="superseded", occurred=f"2025-12-0{i}",
        )

    result = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 (7 refs on a hub_max_facts=3 hub)", result.returncode == 0,
                   result.stdout + result.stderr):
        return

    acme_path = bundle / "knowledge" / "entities" / "org" / "acme.md"
    acme = acme_path.read_text(encoding="utf-8")
    inline_kept = sum(f"Acme active fact {i}" in acme for i in range(1, 6))
    record("inline block keeps only hub_max_facts (3) active facts", inline_kept == 3, acme)
    record(
        "inline block keeps the 3 MOST RECENT active facts by `occurred` (3, 4, 5)",
        all(f"Acme active fact {i}" in acme for i in (3, 4, 5))
        and not any(f"Acme active fact {i}" in acme for i in (1, 2)),
        acme,
    )
    record("inline block drops its history section entirely once sharded",
           "Superseded / deprecated (history)" not in acme, acme)
    record("inline block ends with an archive link line",
           "facts-archive.md" in acme and "older/superseded facts" in acme, acme)

    archive_path = bundle / "knowledge" / "entities" / "org" / "acme.facts-archive.md"
    record("sibling archive file was created", archive_path.exists())
    if archive_path.exists():
        archive = archive_path.read_text(encoding="utf-8")
        record(
            "archive holds the 2 overflow actives + both history facts, none of the inline 3",
            all(f"Acme active fact {i}" in archive for i in (1, 2))
            and all(f"Acme history fact {i}" in archive for i in (1, 2))
            and not any(f"Acme active fact {i}" in archive for i in (3, 4, 5)),
            archive,
        )

    val = run_script(bundle, "validate-okf.py")
    record("validate-okf.py passes despite the frontmatter-less archive file",
           val.returncode == 0, val.stdout + val.stderr)

    before = archive_path.read_text(encoding="utf-8") if archive_path.exists() else None
    result2 = run_script(bundle, "build-index.py")
    after = archive_path.read_text(encoding="utf-8") if archive_path.exists() else None
    record("rebuild is idempotent: archive content unchanged across reruns",
           result2.returncode == 0 and before is not None and before == after,
           f"before={before!r}\nafter={after!r}")

    # shrink the hub back under the threshold -> stale archive must be removed
    for i in (1, 2):
        (bundle / "knowledge" / "facts" / f"active-{i}.md").unlink()
        (bundle / "knowledge" / "facts" / f"history-{i}.md").unlink()
    result3 = run_script(bundle, "build-index.py")
    record(
        "shrinking the hub below hub_max_facts removes the now-stale archive file",
        result3.returncode == 0 and not archive_path.exists(),
        result3.stdout + result3.stderr,
    )


# ---------------------------------------------------------------------------
# 4a. vocab.json — validate-okf.py WARNINGS (never errors)
# ---------------------------------------------------------------------------

def test_vocab_warnings(root):
    bundle = new_bundle(root, "vocab-warnings", with_vocab=True)
    write_entity(bundle, "entities/person/bob.md", "Bob", kind="alien")
    write_source(bundle, f"sources/{MONTH}/s1.md", "weird source", source_kind="rumor")

    val = run_script(bundle, "validate-okf.py")
    record("validate-okf.py still exits 0 — vocab issues are WARNINGS, never errors",
           val.returncode == 0, val.stdout + val.stderr)
    record("warns about out-of-vocab kind='alien' with a count",
           "out-of-vocab kind='alien' (1 file(s))" in val.stdout, val.stdout)
    record("warns about out-of-vocab source-kind='rumor' with a count",
           "out-of-vocab source-kind='rumor' (1 file(s))" in val.stdout, val.stdout)

    # The templates document each vocabulary in a trailing YAML comment, and a
    # model that keeps it writes the comment into the file. Reading the raw line
    # made every such value out-of-vocab — the templates warned about themselves.
    bundle_c = new_bundle(root, "vocab-comment", with_vocab=True)
    write_entity(bundle_c, "entities/concept/okf.md", "OKF",
                 kind="concept         # person | org | project | tool | concept")
    val_c = run_script(bundle_c, "validate-okf.py")
    record(
        "a vocabulary value trailed by a YAML comment is read as the token alone, not warned",
        val_c.returncode == 0 and "out-of-vocab" not in val_c.stdout,
        val_c.stdout + val_c.stderr,
    )

    bundle2 = new_bundle(root, "vocab-absent", with_vocab=False)
    write_entity(bundle2, "entities/person/bob.md", "Bob", kind="alien")
    write_source(bundle2, f"sources/{MONTH}/s1.md", "weird source", source_kind="rumor")
    val2 = run_script(bundle2, "validate-okf.py")
    record(
        "without vocab.json, the same weird values are NOT flagged (vocab checks skipped entirely)",
        val2.returncode == 0 and "out-of-vocab" not in val2.stdout,
        val2.stdout,
    )


# ---------------------------------------------------------------------------
# 4b. an `expired` loop reads as history with AND without vocab.json (E21):
#     off the entity hub, onto tracking/resolved-loops.md, out of the briefing
# ---------------------------------------------------------------------------

def _expired_loop_bundle(root, name, with_vocab):
    bundle = new_bundle(root, name, with_vocab=with_vocab)
    write_entity(bundle, "entities/person/carol.md", "Carol")
    write_open_loop(
        bundle, "tracking/loops/l1.md", "Carol's old commitment",
        entities_yaml="entities: [/entities/person/carol.md]\n",
        status="expired", expired=TODAY,
        resolution="Expired on {} after 100 days of silence.".format(TODAY),
    )
    return bundle


def test_expired_loop_is_history(root):
    """No bundle has ever received vocab.json — `init` copied scripts,
    templates, config.md, README.md and cursors.json and nothing else — so the
    hardcoded loop_status default is what runs in the field. Until this build it
    was {open, done, dropped}, which put an expired loop in NEITHER bucket:
    is_history() said false and decay's own output rendered on the hub as a
    current item, eating a slot of hub_max_facts. Both bundles must now agree."""
    for label, with_vocab in (("no vocab.json", False), ("vocab.json present", True)):
        bundle = _expired_loop_bundle(root, "expired-" + ("vocab" if with_vocab else "novocab"),
                                      with_vocab=with_vocab)
        result = run_script(bundle, "build-index.py")
        carol = (bundle / "knowledge" / "entities" / "person" / "carol.md").read_text(encoding="utf-8")
        resolved = (bundle / "knowledge" / "tracking" / "resolved-loops.md").read_text(encoding="utf-8")
        record(f"({label}) build-index.py exits 0", result.returncode == 0,
               result.stdout + result.stderr)
        record(
            f"({label}) the expired loop is OFF Carol's hub — not as a current item, "
            "and not re-filed into its history section either",
            "Carol's old commitment" not in carol,
            carol,
        )
        record(
            f"({label}) …and ON tracking/resolved-loops.md, with its date and its outcome",
            "Carol's old commitment" in resolved and TODAY in resolved and "expired" in resolved,
            resolved,
        )

    # E25: the loop keeps its `opened` date, so every window that date falls in
    # used to list it under `## Open loops` — with its status in brackets — for
    # the rest of the bundle's life.
    bundle = _expired_loop_bundle(root, "expired-briefing", with_vocab=False)
    run_script(bundle, "build-index.py")
    brief = run_script(bundle, "briefing.py", ["--days", "3650"])
    record(
        "briefing.py drops the resolved loop from `## Open loops` and says how many it hid",
        brief.returncode == 0
        and "Carol's old commitment" not in brief.stdout
        and "## Open loops (0)" in brief.stdout
        and "1 resolved loop(s) hidden" in brief.stdout,
        brief.stdout + brief.stderr,
    )
    brief_all = run_script(bundle, "briefing.py", ["--days", "3650", "--include-resolved"])
    record(
        "…and --include-resolved brings it back, so the filter hides rather than forgets",
        brief_all.returncode == 0 and "Carol's old commitment" in brief_all.stdout,
        brief_all.stdout + brief_all.stderr,
    )


def test_init_copies_vocab(root):
    """`vocab.json` reached no bundle for the life of the plugin: `init` copied
    scripts, templates, config.md, README.md and cursors.json, and nothing
    copied the vocabulary. `update` must still leave it alone — a bundle may
    have extended its own."""
    init = (REPO_ROOT / "plugin" / "skills" / "init" / "procedure.md").read_text(encoding="utf-8")
    update = (REPO_ROOT / "plugin" / "skills" / "update" / "SKILL.md").read_text(encoding="utf-8")
    record(
        "init/procedure.md copies assets/vocab.json into the new bundle",
        "assets/vocab.json" in init and "<bundle>/vocab.json" in init,
        init[:0],
    )
    record(
        "update/SKILL.md still names vocab.json among the files it never re-syncs",
        "vocab.json" in update and "cp ${CLAUDE_PLUGIN_ROOT}/assets/vocab.json" not in update,
        update[:0],
    )


# ---------------------------------------------------------------------------
# 4c. tracking/resolved-loops.md — the resolved surface (H9, E20)
# ---------------------------------------------------------------------------

FIRST = "Alice shipped the export and the ticket was closed."
SECOND = "The evidence is /facts/export-shipped.md, cited by decay.loop_expiry_days in elephant.json."


def test_resolution_sentence_unit(root):
    """The first sentence is split on `. ` only: a bundle path and a dotted
    config key are not sentence ends, and both appear in every resolution the
    two writers produce."""
    mod = load_script_module("build-index.py")
    body = f"\nSome body text.\n\n**Closure signal:** something.\n\n**Resolution:** {FIRST} {SECOND}\n"
    record(
        "resolution_sentence() returns the first sentence alone, keeping its period",
        mod.resolution_sentence(body) == FIRST,
        repr(mod.resolution_sentence(body)),
    )
    wrapped = "**Resolution:** Expired on 2026-09-03 after 100\ndays of silence. And more.\n"
    record(
        "…collapsing a paragraph wrapped across lines first",
        mod.resolution_sentence("\n\n" + wrapped) == "Expired on 2026-09-03 after 100 days of silence.",
        repr(mod.resolution_sentence("\n\n" + wrapped)),
    )
    record(
        "…and returns \"\" for a loop resolved before the paragraph existed",
        mod.resolution_sentence("\nJust a body.\n") == "",
        repr(mod.resolution_sentence("\nJust a body.\n")),
    )
    record(
        "resolved_on() prefers `closed`, then `expired`, then the file's own dates",
        mod.resolved_on({"fm": {"closed": "2026-01-02", "expired": "2026-03-04"}}) == "2026-01-02"
        and mod.resolved_on({"fm": {"expired": "2026-03-04"}}) == "2026-03-04"
        and mod.resolved_on({"fm": {"updated": "2026-05-06"}}) == "2026-05-06",
        "",
    )


def _resolved_bundle(root, name, resolved_max=None):
    bundle = new_bundle(root, name, resolved_max=resolved_max)
    write_entity(bundle, "entities/person/alice.md", "Alice")
    ents = "entities: [/entities/person/alice.md]\n"
    write_open_loop(bundle, "tracking/loops/done.md", "Ship the export", ents,
                    status="done", closed="2026-03-04", resolution=f"{FIRST} {SECOND}")
    write_open_loop(bundle, "tracking/loops/expired.md", "Chase the invoice", ents,
                    status="expired", expired="2026-01-02",
                    resolution="Expired on 2026-01-02 after 100 days of silence. Nothing cited it.")
    write_open_loop(bundle, "tracking/loops/dropped.md", "Abandoned idea", ents,
                    status="dropped", updated="2026-02-03")
    write_open_loop(bundle, "tracking/loops/open.md", "Still open", ents)
    return bundle


def test_resolved_surface(root):
    bundle = _resolved_bundle(root, "resolved-surface")
    result = run_script(bundle, "build-index.py")
    record("build-index.py exits 0 with resolved loops in the bundle",
           result.returncode == 0, result.stdout + result.stderr)
    record("…and reports the resolved count next to the open one",
           "1 open loops, 3 resolved loops" in result.stdout, result.stdout)

    page = (bundle / "knowledge" / "tracking" / "resolved-loops.md").read_text(encoding="utf-8")
    lines = [ln for ln in page.splitlines() if ln.startswith("- ")]
    record(
        "the page lists every resolved loop, newest first by the date it was resolved",
        [ln.split(" · ")[0] for ln in lines] == ["- 2026-03-04", "- 2026-02-03", "- 2026-01-02"],
        page,
    )
    record(
        "each line carries the date, the outcome and a link to the loop, which never moved",
        lines[0] == f"- 2026-03-04 · done · [Ship the export](/tracking/loops/done.md) — {FIRST}",
        lines[0],
    )
    record(
        "only the FIRST sentence of the resolution reaches the page",
        SECOND not in page,
        page,
    )
    record(
        "a loop resolved before the resolution paragraph existed ends at its link",
        lines[1] == "- 2026-02-03 · dropped · [Abandoned idea](/tracking/loops/dropped.md)",
        lines[1],
    )
    record("the open loop is not on the resolved page",
           "Still open" not in page, page)

    board = (bundle / "knowledge" / "tracking" / "open-loops.md").read_text(encoding="utf-8")
    record("…and is still the only one on the board",
           "Still open" in board and "Ship the export" not in board, board)

    alice = (bundle / "knowledge" / "entities" / "person" / "alice.md").read_text(encoding="utf-8")
    record(
        "resolved loops leave the entity hub; the open one stays",
        "Still open" in alice and "Ship the export" not in alice
        and "Chase the invoice" not in alice and "Abandoned idea" not in alice,
        alice,
    )

    router = (bundle / "knowledge" / "index.md").read_text(encoding="utf-8")
    record(
        "the router points at the resolved archive with its count, next to the board",
        "[archive](/tracking/resolved-loops.md) (3 resolved)" in router,
        router,
    )

    val = run_script(bundle, "validate-okf.py")
    record(
        "validate-okf.py exits 0 — resolved-loops.md is a RESERVED name, so it is not "
        "read as a file missing its frontmatter",
        val.returncode == 0 and "resolved-loops.md" not in val.stdout,
        val.stdout + val.stderr,
    )

    before = page
    run_script(bundle, "build-index.py")
    record("a second build writes the same page byte for byte (idempotent)",
           (bundle / "knowledge" / "tracking" / "resolved-loops.md").read_text(encoding="utf-8") == before,
           "")


def test_resolved_overflow(root):
    """E20: past `index.resolved_max` the older resolutions move to the sibling
    archive shard — the same ARCHIVE_SUFFIX mechanism hub sharding uses, so the
    shard needs no name of its own in the four RESERVED copies and validate-okf
    already exempts it from the frontmatter rule."""
    bundle = _resolved_bundle(root, "resolved-overflow", resolved_max=2)
    run_script(bundle, "build-index.py")
    page = (bundle / "knowledge" / "tracking" / "resolved-loops.md").read_text(encoding="utf-8")
    shard = bundle / "knowledge" / "tracking" / "resolved-loops.facts-archive.md"
    record("the two newest resolutions stay inline",
           "Ship the export" in page and "Abandoned idea" in page
           and "Chase the invoice" not in page, page)
    record("…and the page points at the shard by count",
           "→ 1 older resolved loop(s): [archive](/tracking/resolved-loops.facts-archive.md)" in page,
           page)
    record("the shard exists and carries the overflow",
           shard.is_file() and "Chase the invoice" in shard.read_text(encoding="utf-8"),
           shard.read_text(encoding="utf-8") if shard.is_file() else "<missing>")

    val = run_script(bundle, "validate-okf.py")
    record("validate-okf.py exits 0 over the shard — it carries no frontmatter, by design",
           val.returncode == 0, val.stdout + val.stderr)

    # The archive cleanup in section 4 deletes every ARCHIVE_SUFFIX file this run
    # did not write. The resolved shard is written BEFORE that sweep, so it has
    # to be registered as written or the same build that creates it removes it.
    write_index_config(bundle, resolved_max=10)
    run_script(bundle, "build-index.py")
    page2 = (bundle / "knowledge" / "tracking" / "resolved-loops.md").read_text(encoding="utf-8")
    record("raising the cap folds the shard back inline and deletes it",
           not shard.exists() and "Chase the invoice" in page2 and "archive]" not in page2,
           page2)


def test_loop_status_one_rule(root):
    """The open partition and the resolved page are complements of ONE
    normalized rule, not two literal comparisons of the raw field.

    `close-loops/procedure.md` has the model editing a loop's status by hand, so
    `status: Open` is reachable. Under an exact `== "open"` / `!= "open"` pair
    that loop changed sides: absent from tracking/open-loops.md, from
    manifest.jsonl and from the entity hub, while being published on
    tracking/resolved-loops.md under a header reading "reached done, dropped or
    expired". A live commitment, invisible to every retrieval surface a reader
    starts from and announced as settled on the one page that did list it."""
    mod = load_script_module("build-index.py")
    record(
        "loop_status() strips, lowercases, and defaults to `open`",
        mod.loop_status({"fm": {"status": "Open"}}) == "open"
        and mod.loop_status({"fm": {"status": "  open\t"}}) == "open"
        and mod.loop_status({"fm": {}}) == "open"
        and mod.loop_status({"fm": {"status": "Done"}}) == "done",
        "",
    )

    bundle = new_bundle(root, "loop-status-one-rule")
    write_entity(bundle, "entities/person/alice.md", "Alice")
    ents = "entities: [/entities/person/alice.md]\n"
    write_open_loop(bundle, "tracking/loops/capital.md", "Capitalized status", ents,
                    status="Open")
    # Quoted, so the value survives as `open ` through BOTH frontmatter paths:
    # a plain YAML scalar would have its trailing space eaten before either
    # parser is even asked.
    write_open_loop(bundle, "tracking/loops/padded.md", "Padded status", ents,
                    status='"open "')
    write_open_loop(bundle, "tracking/loops/plain.md", "Plain status", ents)
    write_open_loop(bundle, "tracking/loops/settled.md", "Really settled", ents,
                    status="Done", closed="2026-03-04",
                    resolution="Shipped in the March release. And more.")

    result = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 over off-case loop statuses",
                  result.returncode == 0, result.stdout + result.stderr):
        return
    record("…and counts the three as open, the `Done` one as resolved",
           "3 open loops, 1 resolved loops" in result.stdout, result.stdout)

    live = ("Capitalized status", "Padded status")
    board = (bundle / "knowledge" / "tracking" / "open-loops.md").read_text(encoding="utf-8")
    record(
        "`status: Open` and a padded `open ` reach the board, next to the plain one",
        all(d in board for d in live) and "Plain status" in board
        and "Really settled" not in board,
        board,
    )

    manifest = (bundle / "knowledge" / "manifest.jsonl").read_text(encoding="utf-8")
    descs = {json.loads(ln)["desc"] for ln in manifest.splitlines() if ln.strip()}
    record(
        "…and manifest.jsonl, the surface every triage read starts from",
        all(d in descs for d in live) and "Plain status" in descs
        and "Really settled" not in descs,
        sorted(descs),
    )

    alice = (bundle / "knowledge" / "entities" / "person" / "alice.md").read_text(encoding="utf-8")
    record(
        "…and the entity hub, as current items rather than history",
        all(d in alice for d in live) and "Really settled" not in alice,
        alice,
    )

    page = (bundle / "knowledge" / "tracking" / "resolved-loops.md").read_text(encoding="utf-8")
    record(
        "neither is published on the resolved page as something that got settled",
        not any(d in page for d in live) and "Plain status" not in page,
        page,
    )
    record(
        "the genuinely resolved `Done` loop is there, and only it",
        "- 2026-03-04 · Done · [Really settled](/tracking/loops/settled.md) — "
        "Shipped in the March release." in page,
        page,
    )


# ---------------------------------------------------------------------------
# 4e. the two copies of the rule agree — build-index.py's loop_status() and
#     briefing.py's is_resolved()
# ---------------------------------------------------------------------------

LOOP_LINK = re.compile(r"(/tracking/loops/[a-z0-9-]+\.md)")


def test_loop_status_two_scripts_agree(root):
    """`briefing.py`'s is_resolved() is a hand-copied twin of `build-index.py`'s
    loop_status(): the two scripts share no module, and the briefing docstring
    says outright "change one and change the other". Nothing held them to it.
    Deleting the `.strip().lower()` from the briefing side left all eleven
    suites green, which is precisely the drift the docstring warns about: a
    `status: Open` loop on the board and off the briefing, or the reverse.

    So this check renders ONE bundle through both scripts and compares the
    partitions they draw. The fixture is statuses that only agree once
    normalized (`Open`, a padded `open `, `DONE`) — over plain lowercase values
    the two implementations cannot disagree, and the check would be vacuous."""
    bundle = new_bundle(root, "loop-status-two-scripts")
    write_entity(bundle, "entities/person/alice.md", "Alice")
    ents = "entities: [/entities/person/alice.md]\n"
    write_open_loop(bundle, "tracking/loops/capital.md", "Capitalized status", ents,
                    status="Open")
    # Quoted so the trailing space survives both frontmatter paths (see 4d).
    write_open_loop(bundle, "tracking/loops/padded.md", "Padded status", ents,
                    status='"open "')
    write_open_loop(bundle, "tracking/loops/plain.md", "Plain status", ents)
    write_open_loop(bundle, "tracking/loops/shouted.md", "Shouted done", ents,
                    status="DONE", closed=TODAY,
                    resolution="It landed. And then some.")

    built = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 over the mixed-case loop bundle",
                  built.returncode == 0, built.stdout + built.stderr):
        return
    brief = run_script(bundle, "briefing.py", ["--kind", "open-loop", "--days", "3650"])
    if not record("briefing.py --kind open-loop exits 0 over the same bundle",
                  brief.returncode == 0, brief.stdout + brief.stderr):
        return

    board = (bundle / "knowledge" / "tracking" / "open-loops.md").read_text(encoding="utf-8")
    resolved = (bundle / "knowledge" / "tracking" / "resolved-loops.md").read_text(encoding="utf-8")
    index_open = set(LOOP_LINK.findall(board))
    index_resolved = set(LOOP_LINK.findall(resolved))

    # Everything after the `## Open loops` heading is the briefing's open lane;
    # its resolved lane is only ever a hidden count, so it is read as one.
    _, _, loops_block = brief.stdout.partition("## Open loops")
    briefing_open = set(LOOP_LINK.findall(loops_block))
    hidden = re.search(r"\((\d+) resolved loop\(s\) hidden", loops_block)
    briefing_resolved = int(hidden.group(1)) if hidden else 0

    record(
        "the fixture is actually adversarial: three loops whose status only "
        "reads as `open` after strip+lower, and one whose `DONE` only reads as "
        "resolved after it",
        len(index_open) == 3 and len(index_resolved) == 1,
        f"open={sorted(index_open)} resolved={sorted(index_resolved)}",
    )
    record(
        "build-index.py's open partition and briefing.py's are the same set of "
        "loops — the twin normalizations agree on every off-case status",
        index_open == briefing_open,
        f"build-index={sorted(index_open)}\nbriefing={sorted(briefing_open)}\n"
        f"--- board ---\n{board}\n--- briefing ---\n{brief.stdout}",
    )
    record(
        "…and the loops each one leaves out of that lane are the same count, so "
        "neither script drops a loop off both surfaces at once",
        len(index_resolved) == briefing_resolved,
        f"resolved page={sorted(index_resolved)} briefing hid={briefing_resolved}\n"
        f"--- resolved ---\n{resolved}\n--- briefing ---\n{brief.stdout}",
    )
    record(
        "…and --include-resolved brings exactly the resolved-page loops back "
        "into the briefing, so the two partitions cover the same four loops",
        set(LOOP_LINK.findall(
            run_script(bundle, "briefing.py",
                       ["--kind", "open-loop", "--days", "3650",
                        "--include-resolved"]).stdout.partition("## Open loops")[2]
        )) == index_open | index_resolved,
        f"build-index open+resolved={sorted(index_open | index_resolved)}",
    )


# ---------------------------------------------------------------------------
# 4f. the same one-rule property for FACTS: build-index.py's fact_status(),
#     read by active() and by the hub's is_history(), and briefing.py's twin
# ---------------------------------------------------------------------------

FACT_LINK = re.compile(r"(/facts/[a-z0-9-]+\.md)")


def test_fact_status_one_rule_two_scripts(root):
    """The fact lane is partitioned by ONE normalized rule, in three places.

    The loop lane got that property; the fact lane one screen away did not, and
    its three sites read the raw field three different ways: active() compared
    it with no normalization at all, build-index.py's hub is_history() lowercased
    without stripping, briefing.py's is_history() did the same. Measured on the
    fixture below, that produced two failures in a single build. A fact written
    `status: Superseded` landed on BOTH sides at once: published in
    manifest.jsonl as a current fact while the entity hub filed it under
    "Superseded / deprecated (history)". And a fact written `status: "superseded "`
    read as active on every surface, i.e. a superseded fact published as current,
    because the loop rule strips and the fact rule did not.

    So this check renders one bundle through both scripts and compares every
    surface: the hub's two sections, the manifest, and the briefing with and
    without --include-superseded. The fixture is statuses that only agree once
    normalized (`Superseded`, a padded `superseded `) next to the plain value
    and an active decoy. Over plain lowercase values the implementations
    cannot disagree and the check would be vacuous."""
    mod = load_script_module("build-index.py")
    brief_mod = load_script_module("briefing.py")
    record(
        "build-index.py's fact_status() strips and lowercases, and keeps each "
        "call site's own default for a missing status",
        mod.fact_status({"fm": {"status": "Superseded"}}) == "superseded"
        and mod.fact_status({"fm": {"status": "  superseded \t"}}) == "superseded"
        and mod.fact_status({"fm": {"status": "superseded"}}) == "superseded"
        and mod.fact_status({"fm": {}}) == "active"
        and mod.fact_status({"fm": {}}, "") == "",
        "",
    )
    record(
        "briefing.py's twin normalizes the same field the same way",
        brief_mod.fact_status({"status": "Superseded"}) == "superseded"
        and brief_mod.fact_status({"status": "  superseded \t"}) == "superseded"
        and brief_mod.fact_status({"status": "superseded"}) == "superseded"
        and brief_mod.fact_status({}) == "active"
        and brief_mod.fact_status({}, "") == "",
        "",
    )

    bundle = new_bundle(root, "fact-status-one-rule")
    write_entity(bundle, "entities/person/alice.md", "Alice")
    ents = "entities: [/entities/person/alice.md]\n"
    write_fact(bundle, "facts/shouted-superseded.md", "Shouted superseded", ents,
               status="Superseded")
    # Quoted, so the value survives as `superseded ` through BOTH frontmatter
    # paths: a plain YAML scalar would have its trailing space eaten before
    # either parser is even asked (see 4d).
    write_fact(bundle, "facts/padded-superseded.md", "Padded superseded", ents,
               status='"superseded "')
    write_fact(bundle, "facts/plain-superseded.md", "Plain superseded", ents,
               status="superseded")
    write_fact(bundle, "facts/current.md", "Current fact", ents, status="active")

    built = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 over off-case fact statuses",
                  built.returncode == 0, built.stdout + built.stderr):
        return
    record("…and counts the active decoy as the only current fact",
           "1 entities, 1 facts" in built.stdout, built.stdout)

    superseded = {"/facts/shouted-superseded.md",
                  "/facts/padded-superseded.md",
                  "/facts/plain-superseded.md"}
    decoy = {"/facts/current.md"}

    alice = (bundle / "knowledge" / "entities" / "person" / "alice.md").read_text(encoding="utf-8")
    current_block, sep, history_block = alice.partition("### Superseded / deprecated (history)")
    hub_current = set(FACT_LINK.findall(current_block))
    hub_history = set(FACT_LINK.findall(history_block)) if sep else set()
    record(
        "the entity hub files all three superseded facts as history, and only "
        "the active one as current",
        hub_current == decoy and hub_history == superseded,
        f"current={sorted(hub_current)} history={sorted(hub_history)}\n{alice}",
    )
    record(
        "…and no fact is on both sides of the hub's partition, nor off both",
        not (hub_current & hub_history) and (hub_current | hub_history) == superseded | decoy,
        f"current={sorted(hub_current)} history={sorted(hub_history)}",
    )

    manifest = (bundle / "knowledge" / "manifest.jsonl").read_text(encoding="utf-8")
    manifest_facts = {json.loads(ln)["path"] for ln in manifest.splitlines()
                      if ln.strip() and json.loads(ln)["type"] == "fact"}
    record(
        "manifest.jsonl carries the hub's current facts and nothing the hub "
        "filed as history, so active() and is_history() read one rule",
        manifest_facts == hub_current,
        f"manifest={sorted(manifest_facts)} hub current={sorted(hub_current)}\n{manifest}",
    )

    brief = run_script(bundle, "briefing.py", ["--kind", "fact", "--days", "3650"])
    if not record("briefing.py --kind fact exits 0 over the same bundle",
                  brief.returncode == 0, brief.stdout + brief.stderr):
        return
    brief_visible = set(FACT_LINK.findall(brief.stdout))
    hidden = re.search(r"\((\d+) superseded/deprecated fact\(s\) hidden", brief.stdout)
    brief_hidden = int(hidden.group(1)) if hidden else 0
    record(
        "briefing.py hides exactly the facts the manifest left out, so the two "
        "scripts draw the same partition over the same bundle",
        brief_visible == manifest_facts and brief_hidden == len(superseded),
        f"visible={sorted(brief_visible)} hidden={brief_hidden}\n{brief.stdout}",
    )

    shown = run_script(bundle, "briefing.py",
                       ["--kind", "fact", "--days", "3650", "--include-superseded"])
    marked_history = {ln.rsplit(" ", 1)[-1] for ln in shown.stdout.splitlines()
                      if ln.startswith("- ") and "[history]" in ln}
    record(
        "…and --include-superseded brings them back marked [history], the "
        "active decoy left unmarked",
        set(FACT_LINK.findall(shown.stdout)) == superseded | decoy
        and marked_history == superseded,
        f"marked={sorted(marked_history)}\n{shown.stdout}",
    )


# ---------------------------------------------------------------------------
# 5. entities/roster.tsv — the resolution surface
# ---------------------------------------------------------------------------

TAB = "\t"

# The whole file build-index.py must emit for the bundle below, byte for byte.
# Written out rather than recomputed so the expectation is readable as a grid:
#   - header first, then kind ("org" < "person") then title, case-INSENSITIVELY
#     ("acme" sorts before "Zeta, Ltda");
#   - `Zeta, Ltda` keeps its comma (the column is tab-delimited), `Al,Ali` loses
#     its own to a space (the alias column is itself comma-joined);
#   - the tab inside `Bob<TAB>Builder` and inside the alias `B<TAB>B` is a space;
#   - deprecated `dave` has no row at all;
#   - the last row (`zoe`) has no aliases and still ends on its fourth column,
#     i.e. on a trailing tab — the reason the roster does not go through write().
EXPECTED_ROSTER = (
    f"# slug{TAB}kind{TAB}title{TAB}aliases\n"
    f"acme{TAB}org{TAB}acme{TAB}ACME,Acme Inc\n"
    f"zeta{TAB}org{TAB}Zeta, Ltda{TAB}\n"
    f"alice{TAB}person{TAB}Alice{TAB}Al Ali\n"
    f"bob{TAB}person{TAB}Bob Builder{TAB}B B,Bobby\n"
    f"zoe{TAB}person{TAB}Zoe{TAB}\n"
)

# What entities/index.md held before the roster existed, for the same bundle:
# the roster is emitted from the same active() list and must not perturb it.
EXPECTED_CATALOG = (
    "# Entities\n"
    "\n"
    "Catalog (the navigation spine). Derived — do not edit by hand.\n"
    "\n"
    "## org\n"
    "\n"
    "- [acme](/entities/org/acme.md) — acme.\n"
    "- [Zeta, Ltda](/entities/org/zeta.md) — Zeta, Ltda.\n"
    "\n"
    "## person\n"
    "\n"
    "- [Alice](/entities/person/alice.md) — Alice.\n"
    f"- [Bob{TAB}Builder](/entities/person/bob.md) — Bob{TAB}Builder.\n"
    "- [Zoe](/entities/person/zoe.md) — Zoe.\n"
)


def _roster_bundle(root, name):
    bundle = new_bundle(root, name)
    # lowercase title on purpose: with a case-SENSITIVE sort "Zeta, Ltda" would
    # come first, so this row is what pins the .lower() in the sort key.
    write_entity(bundle, "entities/org/acme.md", "acme", kind="org",
                 aliases=["ACME", "Acme Inc"])
    write_entity(bundle, "entities/org/zeta.md", "Zeta, Ltda", kind="org")
    write_entity(bundle, "entities/person/alice.md", "Alice", aliases=["Al,Ali"])
    write_entity(bundle, "entities/person/bob.md", f"Bob{TAB}Builder",
                 aliases=[f"B{TAB}B", "Bobby"])
    write_entity(bundle, "entities/person/zoe.md", "Zoe")
    write_entity(bundle, "entities/person/dave.md", "Dave", status="deprecated",
                 aliases=["Davey"])
    return bundle


def test_roster(root):
    mod = load_script_module("build-index.py")
    record(
        "tsv_field() collapses tab, CR and LF to a space and KEEPS a comma "
        "(a title's comma is content; the column is tab-delimited)",
        mod.tsv_field("a\tb\rc\nd,e") == "a b c d,e",
        repr(mod.tsv_field("a\tb\rc\nd,e")),
    )
    record(
        "tsv_alias() collapses the comma too (the alias column is comma-joined, "
        "so an inner comma would split one alias into two names)",
        mod.tsv_alias("a\tb\rc\nd,e") == "a b c d e",
        repr(mod.tsv_alias("a\tb\rc\nd,e")),
    )

    bundle = _roster_bundle(root, "roster")
    result = run_script(bundle, "build-index.py")
    if not record("build-index.py exits 0 (bundle with a roster)", result.returncode == 0,
                   result.stdout + result.stderr):
        return

    roster_path = bundle / "knowledge" / "entities" / "roster.tsv"
    if not record("entities/roster.tsv was written", roster_path.exists()):
        return
    raw = roster_path.read_bytes()
    text = raw.decode("utf-8")

    record(
        "roster is byte-identical to the expected grid: header, one row per "
        "ACTIVE entity, sorted by kind then title case-insensitively, "
        "sanitized, deprecated excluded",
        text == EXPECTED_ROSTER,
        f"got:\n{text!r}\nwant:\n{EXPECTED_ROSTER!r}",
    )

    lines = text.splitlines()
    record("header line comes first and names the four columns",
           lines[:1] == [f"# slug{TAB}kind{TAB}title{TAB}aliases"], lines[:1])
    record("every row carries exactly four tab-separated columns",
           all(len(ln.split(TAB)) == 4 for ln in lines), lines)
    record(
        "the last row has empty aliases and still ends on its 4th column — the "
        "trailing tab write()'s rstrip() would have eaten",
        lines[-1] == f"zoe{TAB}person{TAB}Zoe{TAB}" and text.endswith(f"Zoe{TAB}\n"),
        repr(lines[-1]),
    )
    record("no deprecated entity reaches the roster",
           "dave" not in text and "Davey" not in text, text)

    by_slug = {ln.split(TAB)[0]: ln.split(TAB) for ln in lines[1:]}
    record("a comma inside ONE alias becomes a space, keeping it a single alias",
           by_slug["alice"][3] == "Al Ali", by_slug.get("alice"))
    record("a comma inside a TITLE survives untouched",
           by_slug["zeta"][2] == "Zeta, Ltda", by_slug.get("zeta"))
    record("a tab in a title and in an alias each become a space",
           by_slug["bob"][2] == "Bob Builder" and by_slug["bob"][3] == "B B,Bobby",
           by_slug.get("bob"))

    record(
        "summary line reports the roster's row count and byte size",
        f"roster.tsv: 5 rows, {len(raw)} bytes." in result.stdout,
        result.stdout,
    )

    catalog_path = bundle / "knowledge" / "entities" / "index.md"
    catalog = catalog_path.read_text(encoding="utf-8")
    record(
        "entities/index.md is byte-identical to what it emitted before the "
        "roster existed — the catalog is untouched by this change",
        catalog == EXPECTED_CATALOG,
        f"got:\n{catalog!r}\nwant:\n{EXPECTED_CATALOG!r}",
    )

    val = run_script(bundle, "validate-okf.py")
    record(
        "validate-okf.py exits clean over a bundle holding the roster: "
        "no error, no warning (the .tsv is invisible to its .md walk)",
        val.returncode == 0
        and "WARNING" not in (val.stdout + val.stderr)
        and "FAILED" not in val.stdout,
        val.stdout + val.stderr,
    )

    result2 = run_script(bundle, "build-index.py")
    record(
        "rebuild is idempotent: roster and catalog unchanged across reruns",
        result2.returncode == 0
        and roster_path.read_bytes() == raw
        and catalog_path.read_text(encoding="utf-8") == catalog,
        result2.stdout + result2.stderr,
    )

    # fresh `init`: no entities at all
    empty = new_bundle(root, "roster-empty")
    result3 = run_script(empty, "build-index.py")
    empty_roster = empty / "knowledge" / "entities" / "roster.tsv"
    record("build-index.py exits 0 on a bundle with no entities",
           result3.returncode == 0, result3.stdout + result3.stderr)
    record(
        "an empty bundle gets the header line alone — the file exists, nothing errors",
        empty_roster.exists()
        and empty_roster.read_text(encoding="utf-8") == f"# slug{TAB}kind{TAB}title{TAB}aliases\n",
        empty_roster.read_text(encoding="utf-8") if empty_roster.exists() else "<missing>",
    )
    record(
        "summary line reports 0 rows for the empty roster",
        "roster.tsv: 0 rows, " in result3.stdout,
        result3.stdout,
    )


def guarded(fn, root):
    try:
        fn(root)
    except Exception:  # noqa: BLE001 - report and continue to the next check group
        record(f"{fn.__name__} raised an unexpected exception", False, traceback.format_exc())


def main():
    print("elephant-mem test_index — targeted regression tests")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print()

    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-mem-test-index-"))
    print(f"scratch root: {scratch_root}\n")

    for fn in (
        test_parse_fm_fallback_block_lists,
        test_block_style_entities,
        test_marker_injection,
        test_hub_sharding,
        test_vocab_warnings,
        test_expired_loop_is_history,
        test_init_copies_vocab,
        test_resolution_sentence_unit,
        test_resolved_surface,
        test_resolved_overflow,
        test_loop_status_one_rule,
        test_loop_status_two_scripts_agree,
        test_fact_status_one_rule_two_scripts,
        test_roster,
    ):
        guarded(fn, scratch_root)

    print()
    print("Summary")
    print("-------")
    n_pass = 0
    for label, passed in checks:
        status = "PASS" if passed else "FAIL"
        if passed:
            n_pass += 1
        print(f"  {status:4s}  {label}")
    total = len(checks)
    print(f"\n{n_pass}/{total} checks passed.")
    shutil.rmtree(scratch_root, ignore_errors=True)
    return 0 if n_pass == total and total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
