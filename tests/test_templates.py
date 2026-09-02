#!/usr/bin/env python3
"""Regression tests for the four templates under plugin/assets/templates/.

`init` copies them into every new bundle and `update` re-syncs them, so they are
the shape every hand-written knowledge file starts from — and until this suite
nothing validated them. The CI step that was supposed to (`validate-okf.py` run
straight from the checkout, dropped in 0.1.0-beta.11) never reached them: it
walked an accidental `plugin/assets/knowledge/` of four empty files instead.

What is checked, in the order the templates are used:

  1. All four exist, carry a `---`-delimited frontmatter block, and declare the
     `type:` their filename promises. A suite that only ran the validator would
     go green on a deleted or renamed template — the same vacuous pass that
     motivated dropping that CI step.
  2. Mounted into a throwaway bundle, `validate-okf.py` exits 0 AND prints no
     WARNINGS. Both, separately: warnings never affect the exit code, so an
     exit-code-only check would sleep through an out-of-vocab value in a
     template — which is exactly what a bundle owner would then see on their
     own first file.
  3. `build-index.py` consumes the same bundle and emits every derived surface.
     That proves the templates carry the fields the *code* reads, not merely the
     ones the validator tolerates.

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
# 2 + 3. the templates as a bundle: validator clean, index buildable
# ---------------------------------------------------------------------------

def mount_bundle(root):
    """A bundle whose entire knowledge/ is the four templates, filed where each
    type belongs."""
    bundle = root / "templates-bundle"
    (bundle / "scripts").mkdir(parents=True, exist_ok=True)
    for f in (ASSETS / "scripts").glob("*.py"):
        shutil.copy2(f, bundle / "scripts" / f.name)
    # Without vocab.json the vocabulary checks are skipped entirely, so an
    # out-of-vocab value in a template would pass unnoticed. Copy the shipped
    # one — it is what init puts in a real bundle.
    shutil.copy2(ASSETS / "vocab.json", bundle / "vocab.json")
    for name, (_, dest) in TEMPLATE_SPEC.items():
        target = bundle / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATES / name, target)
    return bundle


def test_bundle_of_templates(root):
    bundle = mount_bundle(root)

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

    idx = run_script(bundle, "build-index.py")
    record(
        "build-index.py consumes the same bundle",
        idx.returncode == 0,
        f"exit={idx.returncode}\n{idx.stdout}\n{idx.stderr}",
    )
    # The counts are the non-vacuity proof: they say the builder recognized each
    # template as the type it declares, rather than skipping files it could not
    # parse and reporting success over an empty walk.
    record(
        "…and counts one document of each type, so no template was silently skipped",
        "1 entities, 1 facts, 1 open loops, 1 sources" in idx.stdout,
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


def main():
    print("elephant-mem test_templates — the shipped templates as a bundle")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print()

    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-mem-test-templates-"))
    print(f"scratch root: {scratch_root}\n")

    try:
        test_templates_wellformed()
        test_bundle_of_templates(scratch_root)
    except Exception:  # noqa: BLE001 - report as a failed check, not a traceback
        record("test_templates raised an unexpected exception", False,
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
