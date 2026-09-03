#!/usr/bin/env python3
"""Regression tests for the four templates under plugin/assets/templates/.

A template is a **contract with every script that reads a bundle**, not just
with the validator. `init` copies the four into every new bundle and `update`
re-syncs them, so every hand-written knowledge file starts as one of them —
comments and all, since a bundle owner fills in the placeholders and leaves the
`# open | done | dropped | expired` documentation where it sits. Any script that
reads a field a template ships is therefore bound by the way the template writes
that field. "The fields the *code* reads" means every one of those scripts.

That is not a hypothetical contract. The branch that added this suite also
shipped six frontmatter readers that glued a template's trailing `#` comment
onto the value — in `decay-loops.py`, `snapshot-drift.py`, `rename-entity.py`
and `validate-okf.py`. One of them wiped a `rename-entity.py` target's
accumulated aliases silently, at exit 0. Every one of those scripts was already
sitting in this suite's mounted bundle, over exactly these files, and none was
ever invoked: the suite drove two of them. A bundle-of-templates suite is the
only place that can hold all of them at once, so it drives all of them.

Which scripts those are is **derived, not hand-listed** (same shape as
tests/smoke.py's GUARDED_SCRIPTS): a glob over `assets/scripts/*.py` minus a
named exempt set, each exemption carrying its reason. A hand-written tuple
proves "these six run", never "every reader runs", so the twelfth script would
be born without a sensor — which is the exact shape of the defect this suite
exists to close.

What is checked, in the order the templates are used:

  1. All four exist, carry a `---`-delimited frontmatter block, and declare the
     `type:` their filename promises. A suite that only ran the validator would
     go green on a deleted or renamed template — the same vacuous pass that
     motivated dropping the CI step that ran `validate-okf.py` straight from the
     checkout (0.1.0-beta.11): it walked an accidental `plugin/assets/knowledge/`
     of four empty files instead of the templates.
  2. Every bundle reader has a driver below, so a new script under
     `assets/scripts/` fails this suite until someone writes one or exempts it.
  3. One check per reader, mounting the templates as a real bundle and asserting
     something **substantive** about the output. Not `returncode == 0`: a script
     can exit 0 while saying nothing, and silence is precisely what all six of
     those defects looked like.

Each driver gets its **own freshly mounted bundle**. Three of the readers write
(`build-index.py` emits the derived surfaces, `decay-loops.py --apply` rewrites
a loop, `rename-entity.py` moves a file), and a shared bundle would make every
later check depend on an ordering no one states. Mounting is a dozen file
copies; the isolation is worth more than the milliseconds.

Pure stdlib, Python 3.10+, same scaffolding style as tests/smoke.py: the bundle
is a tempdir with the shipped scripts copied in, driven via subprocess
(sys.executable). The copy is not convenience — since 0.1.0-beta.11 every
bundle script refuses to run from inside the plugin checkout, where it would
resolve `plugin/assets/` as its bundle.

Exit code 0 only if every check below passes.
"""
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "plugin" / "assets"
TEMPLATES = ASSETS / "templates"

# filename -> (declared type, where init/ingest files a document of that type)
TEMPLATE_SPEC = {
    "entity.md": ("entity", "knowledge/entities/concept/t.md"),
    "fact.md": ("fact", "knowledge/facts/t.md"),
    "open-loop.md": ("open-loop", "knowledge/tracking/loops/t.md"),
    "source.md": ("source", "knowledge/sources/t.md"),
}

# Scripts under assets/scripts/ that do NOT read `knowledge/` — the templates
# are no contract of theirs, so they are out of scope here. Verified by reading
# each one's bundle-relative constants, not by reputation:
#   backlog.py     — BUNDLE/state only (`state/backlog.json` + its rendering);
#                    its own docstring says state/ is not part of the OKF bundle.
#   ingest-audio.py — BUNDLE/state/phone only (Taildrop inbox, WhisperX output).
#   recall.py      — BUNDLE/state only (the consumption log and its roll-up). It
#                    does define KNOWLEDGE, but only as a string prefix: it
#                    rewrites a cited link to its bundle-absolute spelling and
#                    opens no document, so it parses no frontmatter and no
#                    template field is a contract of its.
#   run-hooks.py   — reads `hooks` out of elephant.json and spawns subscribers;
#                    resolves no knowledge/ path at all. (smoke.py exempts it
#                    from the checkout guard for the neighbouring reason: it
#                    takes --bundle and creates nothing.)
#   send-email.py  — resolves no bundle whatsoever; its config comes from the
#                    machine-local pointer file.
#   state.py       — BUNDLE/state only (cursors, processed events, watermarks).
READER_EXEMPT = {
    "backlog.py",
    "ingest-audio.py",
    "recall.py",
    "run-hooks.py",
    "send-email.py",
    "state.py",
}
BUNDLE_READERS = tuple(
    p.name for p in sorted((ASSETS / "scripts").glob("*.py"))
    if p.name not in READER_EXEMPT
)

DRIVERS = {}  # script name -> the function that drives it over a template bundle

checks = []


def drives(script_name):
    """Register a driver for one bundle reader. The registry is what check 2
    measures against the derived list, so a new reader cannot slip in unsensed."""
    def deco(fn):
        DRIVERS[script_name] = fn
        return fn
    return deco


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


def frontmatter_type(text):
    """The `type:` value of a `---`-delimited frontmatter block, or None if the
    block is missing or unterminated. Deliberately not the scripts' own parser:
    this asserts what the file looks like, independently of the code under test.
    The templates document each vocabulary in a trailing `#` comment, so the
    value is taken as the first whitespace-delimited token."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            break
    else:
        return None
    for line in lines[1:i]:
        if line.startswith("type:"):
            return line[len("type:"):].split("#", 1)[0].strip().strip("\"'")
    return None


def seed_field(path, key, value):
    """Fill in one template placeholder, KEEPING the line's trailing comment.

    A bundle owner fills the value and leaves the documentation comment where it
    is, so a fixture that dropped the comment would be testing a file no bundle
    ever contains — and the comment is the whole hazard: it is what the six
    broken readers glued onto the value. Raises rather than no-op'ing, so a
    renamed template field fails loudly instead of quietly disarming a check."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if not stripped.startswith(f"{key}:"):
            continue
        indent = ln[: len(ln) - len(stripped)]
        _head, sep, tail = stripped[len(key) + 1:].partition(" #")
        comment = f" #{tail}" if sep else ""
        lines[i] = f"{indent}{key}: {value}{comment}"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    raise AssertionError(f"{path.name} has no `{key}:` line to seed")


# ---------------------------------------------------------------------------
# 1. the templates themselves
# ---------------------------------------------------------------------------

def test_templates_wellformed():
    on_disk = sorted(p.name for p in TEMPLATES.glob("*.md"))
    record(
        "plugin/assets/templates/ holds exactly the four templates init copies "
        "into a bundle",
        on_disk == sorted(TEMPLATE_SPEC),
        f"on disk: {on_disk}\nexpected: {sorted(TEMPLATE_SPEC)}",
    )

    for name, (expected_type, _) in sorted(TEMPLATE_SPEC.items()):
        path = TEMPLATES / name
        if not path.exists():
            record(f"{name} declares type: {expected_type}", False, f"missing: {path}")
            continue
        found = frontmatter_type(path.read_text(encoding="utf-8"))
        record(
            f"{name} opens on a terminated frontmatter block declaring "
            f"type: {expected_type}",
            found == expected_type,
            f"parsed type: {found!r}",
        )


# ---------------------------------------------------------------------------
# 2. every bundle reader is driven
# ---------------------------------------------------------------------------

def test_reader_coverage():
    undriven = [s for s in BUNDLE_READERS if s not in DRIVERS]
    stale = [s for s in sorted(DRIVERS) if s not in BUNDLE_READERS]
    record(
        "every script that reads a bundle is driven over the templates below "
        "(add a driver or an exemption with its reason)",
        not undriven and not stale,
        f"undriven readers: {undriven}\ndrivers for non-readers: {stale}",
    )


# ---------------------------------------------------------------------------
# 3. the templates as a real bundle, one reader at a time
# ---------------------------------------------------------------------------

def mount_bundle(root, name):
    """A bundle whose entire knowledge/ is the four templates, filed where each
    type belongs. One per driver — see the module docstring on why they are not
    shared."""
    bundle = root / name
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    for f in (ASSETS / "scripts").glob("*.py"):
        shutil.copy2(f, bundle / "scripts" / f.name)
    # Without vocab.json the vocabulary checks are skipped entirely, so an
    # out-of-vocab value in a template would pass unnoticed. Copy the shipped
    # one — it is what init puts in a real bundle.
    shutil.copy2(ASSETS / "vocab.json", bundle / "vocab.json")
    for tname, (_, dest) in TEMPLATE_SPEC.items():
        target = bundle / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATES / tname, target)
    return bundle


@drives("validate-okf.py")
def drive_validate(root):
    bundle = mount_bundle(root, "validate")

    val = run_script(bundle, "validate-okf.py")
    record(
        "a bundle whose knowledge/ is the four templates passes validate-okf.py",
        val.returncode == 0,
        f"exit={val.returncode}\n{val.stdout}\n{val.stderr}",
    )
    record(
        "…and does so with no WARNINGS (warnings leave the exit code at 0, so "
        "the exit check above cannot see them)",
        "WARNINGS" not in (val.stdout + val.stderr),
        val.stdout + val.stderr,
    )


@drives("build-index.py")
def drive_build_index(root):
    bundle = mount_bundle(root, "build-index")

    idx = run_script(bundle, "build-index.py")
    record(
        "build-index.py consumes a bundle of the four templates",
        idx.returncode == 0,
        f"exit={idx.returncode}\n{idx.stdout}\n{idx.stderr}",
    )
    # The counts are the non-vacuity proof: they say the builder recognized each
    # template as the type it declares, rather than skipping files it could not
    # parse and reporting success over an empty walk.
    record(
        "…and counts one document of each type, so no template was silently skipped",
        "1 entities, 1 facts, 1 open loops, 0 resolved loops, 1 sources" in idx.stdout,
        idx.stdout + idx.stderr,
    )

    surfaces = [
        "knowledge/index.md",
        "knowledge/entities/index.md",
        "knowledge/entities/roster.tsv",
        "knowledge/manifest.jsonl",
    ]
    missing = [s for s in surfaces if not (bundle / s).exists()]
    record(
        "every derived surface is emitted (index, entity catalog, roster, manifest)",
        not missing,
        f"missing: {missing}",
    )

    roster_path = bundle / "knowledge" / "entities" / "roster.tsv"
    roster = roster_path.read_text(encoding="utf-8") if roster_path.exists() else ""
    rows = roster.splitlines()
    record(
        "the roster carries its header and a row for the template entity — the "
        "template's fields are the ones the resolution surface reads",
        len(rows) == 2
        and rows[0] == "# slug\tkind\ttitle\taliases"
        and rows[1].split("\t")[:2] == ["t", "concept"],
        repr(roster),
    )


@drives("briefing.py")
def drive_briefing(root):
    bundle = mount_bundle(root, "briefing")

    # A window wide enough to hold whatever placeholder date the templates carry
    # this release: the assertion is about the digest finding both documents,
    # not about arithmetic on a date that moves when the templates are refreshed.
    window = ["--since", "2000-01-01", "--until", "2100-01-01"]
    br = run_script(bundle, "briefing.py", window)
    record(
        "briefing.py finds the template fact and the template open loop — the "
        "digest reads the same fields the templates ship",
        br.returncode == 0 and "1 fact(s), 1 open-loop(s)" in br.stdout,
        f"exit={br.returncode}\n{br.stdout}\n{br.stderr}",
    )

    # `confidence: medium    # low | medium | high` is a filter input, and a
    # comment glued to it ranks as the unknown value (0), which silently drops
    # the fact from every --min-confidence run above `low` and prints it as
    # `[?]` in the rows that do survive.
    conf = run_script(bundle, "briefing.py", window + ["--min-confidence", "medium"])
    record(
        "…and --min-confidence medium keeps it, so `confidence:` was read "
        "without its trailing comment",
        conf.returncode == 0
        and "1 fact(s), 1 open-loop(s)" in conf.stdout
        and "[med]" in conf.stdout,
        f"exit={conf.returncode}\n{conf.stdout}\n{conf.stderr}",
    )


@drives("decay-loops.py")
def drive_decay_loops(root):
    bundle = mount_bundle(root, "decay-loops")
    loop = bundle / "knowledge" / "tracking" / "loops" / "t.md"
    # The template's dates are a placeholder that ages with each release, and
    # the default expiry is 45 days — pin them well past it so this check is
    # about `status:` being read as `open`, not about the calendar.
    for key in ("opened", "created", "updated"):
        seed_field(loop, key, "2000-01-01")

    dry = run_script(bundle, "decay-loops.py")
    record(
        "decay-loops.py sees the template loop as a decay candidate, so "
        "`status: open  # open | done | dropped | expired` was read as `open`",
        dry.returncode == 0 and "1 candidate(s)" in dry.stdout,
        f"exit={dry.returncode}\n{dry.stdout}\n{dry.stderr}",
    )
    record(
        "…and the dry run left the loop file untouched",
        "status: open" in loop.read_text(encoding="utf-8"),
        loop.read_text(encoding="utf-8"),
    )

    # --apply writes, so it runs last in this driver's bundle and nothing else
    # reads it afterwards. --skip-sweep because this check is about the template
    # being read, not about the closure sweep: without it the gate would hold
    # the loop back (no `close-loops` run ever examined it) and the check would
    # fail for a reason that has nothing to do with the templates.
    applied = run_script(bundle, "decay-loops.py", ["--apply", "--skip-sweep"])
    text = loop.read_text(encoding="utf-8")
    record(
        "decay-loops.py --apply flips the template loop to `status: expired`",
        applied.returncode == 0
        and "1 loop(s) expired" in applied.stdout
        and "status: expired" in text
        and "status: open" not in text,
        f"exit={applied.returncode}\n{applied.stdout}\n{applied.stderr}\n---\n{text}",
    )
    # The template documents `expired:` in prose (it declares no field for it,
    # since only the routine may write one) and the status flip above passes
    # without it ever being stamped. So the field gets its own two checks: that
    # it is there, and that it sits where the template says it does.
    fm_lines = text.split("---")[1].splitlines() if text.startswith("---") else []
    expired = [ln for ln in fm_lines if ln.startswith("expired:")]
    record(
        "…and stamps the `expired:` field the template documents, with a date",
        len(expired) == 1 and expired[0][len("expired:"):].strip() != "",
        f"frontmatter:\n" + "\n".join(fm_lines),
    )
    status_at = [i for i, ln in enumerate(fm_lines) if ln.startswith("status:")]
    record(
        "…on the line directly under `status:`, where the template says the "
        "routine inserts it",
        len(status_at) == 1
        and len(expired) == 1
        and fm_lines[status_at[0] + 1:status_at[0] + 2] == expired,
        f"frontmatter:\n" + "\n".join(fm_lines),
    )


@drives("close-loops.py")
def drive_close_loops(root):
    bundle = mount_bundle(root, "close-loops")
    loop = bundle / "knowledge" / "tracking" / "loops" / "t.md"

    out = run_script(bundle, "close-loops.py")
    text = out.stdout
    record(
        "close-loops.py queues the template loop, so `status: open  # open | "
        "done | dropped | expired` was read as `open` — a reader that keeps the comment "
        "queues nothing at all and says so at exit 0",
        out.returncode == 0
        and "1 loop(s) queued of 1 open" in text
        and "/tracking/loops/t.md" in text,
        f"exit={out.returncode}\n{text}\n{out.stderr}",
    )
    record(
        "…and reads the criterion out of the template's `**Closure signal:**` "
        "section, the field no code opened before this build",
        "criterion (**Closure signal:**): <what a future source would have to "
        "show" in text,
        text,
    )
    # The fact template ships `entities: []  # bundle-absolute links, e.g.
    # [/entities/person/foo.md]` — a reader that swallows that comment files the
    # placeholder as an entity BOTH documents share, and the template fact then
    # ranks as evidence for the template loop.
    record(
        "…and proposes no evidence: the template fact's `entities: []` is read "
        "as empty, comment and its bracketed example both",
        "evidence: none" in text,
        text,
    )


@drives("snapshot-drift.py")
def drive_snapshot_drift(root):
    bundle = mount_bundle(root, "snapshot-drift")
    facts = bundle / "knowledge" / "facts"
    # A drift report needs a `snapshot`-tagged fact and at least one other fact
    # to compare it against, so the second one is the fact template again —
    # every field, and every comment, exactly as a bundle receives it.
    snap = facts / "t-snapshot.md"
    shutil.copy2(TEMPLATES / "fact.md", snap)
    seed_field(snap, "tags", "[snapshot]")

    drift = run_script(bundle, "snapshot-drift.py")
    out = drift.stdout + drift.stderr
    # Both template facts ship `entities: []  # bundle-absolute links, e.g.
    # [/entities/person/foo.md]`. A reader that takes the comment as list items
    # has them "sharing" two entities, and a glued `occurred:` sorts above a
    # bare `updated:` — so two untouched templates reported drift against each
    # other. Empty lists share nothing, and nothing is what must be reported.
    record(
        "snapshot-drift.py reports no drift between two untouched fact "
        "templates — their empty `entities: []` is read as empty, comment and all",
        drift.returncode == 0 and "0 of 1 snapshot(s) may have drifted." in out,
        f"exit={drift.returncode}\n{out}",
    )
    # The report prints the dates and paths it read back, so a `#` anywhere in
    # it is a comment that survived the parser — the pre-fix run tailed each row
    # with `# when the content actually happened / was said (ISO; ≠ created)`.
    record(
        "…and no comment text leaks into the report",
        "#" not in out,
        out,
    )


@drives("rename-entity.py")
def drive_rename_entity(root):
    bundle = mount_bundle(root, "rename-entity")
    entity = bundle / "knowledge" / "entities" / "concept" / "t.md"
    # The template ships `aliases: []`, and an empty list cannot tell a merge
    # from a replacement — both produce `[Zed]`. Seed one alias first (keeping
    # the trailing comment, which is what broke the reader) so the two outcomes
    # are distinguishable.
    seed_field(entity, "aliases", '["Tee"]')

    ren = run_script(bundle, "rename-entity.py", ["t", "t2", "--alias", "Zed"])
    renamed = bundle / "knowledge" / "entities" / "concept" / "t2.md"
    record(
        "rename-entity.py renames the template entity",
        ren.returncode == 0 and renamed.exists() and not entity.exists(),
        f"exit={ren.returncode}\n{ren.stdout}\n{ren.stderr}",
    )

    text = renamed.read_text(encoding="utf-8") if renamed.exists() else ""
    record(
        "…and MERGES the new alias into the existing ones rather than replacing "
        "them — the silent loss was exit 0 with no warning",
        'aliases: ["Tee", Zed]' in text,
        text,
    )
    record(
        "…keeping the field's documentation comment, which the rewrite must not "
        "swallow either",
        "other names/spellings used for this entity" in text,
        text,
    )


def main():
    print("elephant-mem test_templates — the shipped templates as a bundle")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print()

    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-mem-test-templates-"))
    print(f"scratch root: {scratch_root}")
    print(f"bundle readers: {', '.join(BUNDLE_READERS)}\n")

    try:
        test_templates_wellformed()
        test_reader_coverage()
    except Exception:  # noqa: BLE001 - report as a failed check, not a traceback
        record("test_templates raised an unexpected exception", False,
               traceback.format_exc())

    for script_name in BUNDLE_READERS:
        driver = DRIVERS.get(script_name)
        if driver is None:
            continue  # already reported by test_reader_coverage
        try:
            driver(scratch_root)
        except Exception:  # noqa: BLE001 - one broken driver must not hide the rest
            record(f"driving {script_name} raised an unexpected exception", False,
                   traceback.format_exc())

    print()
    print("Summary")
    print("-------")
    n_pass = sum(1 for _, passed in checks if passed)
    for label, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL':4s}  {label}")
    total = len(checks)
    print(f"\n{n_pass}/{total} checks passed.")
    shutil.rmtree(scratch_root, ignore_errors=True)

    return 0 if n_pass == total and total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
