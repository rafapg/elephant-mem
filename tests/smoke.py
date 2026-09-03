#!/usr/bin/env python3
"""Cross-platform smoke test for the elephant-mem deterministic layer.

Scaffolds a throwaway bundle from the shipped plugin assets (mirroring
`plugin/skills/init/procedure.md` Stage 4/7/8: reserved files with no
frontmatter, `type:` frontmatter on every other bundle markdown file,
bundle-absolute links, no wikilinks) and then exercises every entry point
under `plugin/assets/scripts/` end to end, including a UTF-8 regression test
(non-ASCII fact content + an accented entity alias) and the SMTP dry-run path.

Pure stdlib, Python 3.10+. The only external processes launched are `git`
(bundle init) and `sys.executable` (the bundle scripts) — no shell-outs, no
third-party dependencies. Uses pathlib throughout so it runs unmodified on
ubuntu-latest, macos-latest, and windows-latest GitHub runners.

Exit code 0 only if every check below passes.
"""
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "plugin" / "assets"

TODAY = datetime.date.today().isoformat()
MONTH = datetime.date.today().strftime("%Y-%m")

checks = []  # list of (label, passed)


def record(label, passed, detail=""):
    checks.append((label, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{len(checks):2d}] {status} — {label}")
    if detail and not passed:
        for ln in detail.splitlines():
            print(f"       {ln}")
    return passed


def run(args, cwd, env=None, input_text=None):
    return subprocess.run(
        [str(a) for a in args],
        cwd=str(cwd),
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def run_script(bundle, script_name, extra_args=None, env=None, input_text=None):
    script = bundle / "scripts" / script_name
    return run([sys.executable, script] + (extra_args or []), cwd=bundle, env=env, input_text=input_text)


def run_and_check(bundle, script_name, args, label, env=None, input_text=None, expect_zero=True):
    result = run_script(bundle, script_name, args, env=env, input_text=input_text)
    ok = (result.returncode == 0) if expect_zero else (result.returncode != 0)
    detail = ""
    if not ok:
        detail = (
            f"exit={result.returncode} (expected {'0' if expect_zero else 'non-zero'})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    record(label, ok, detail)
    return result


# ---------------------------------------------------------------------------
# a. scaffold a minimal bundle from the shipped assets
# ---------------------------------------------------------------------------

def scaffold_bundle(bundle):
    dirs = [
        "knowledge/facts",
        "knowledge/entities/person",
        "knowledge/entities/org",
        "knowledge/tracking/loops",
        "knowledge/sources",
        "state",
        "scripts",
        "templates",
        "raw",
    ]
    for d in dirs:
        (bundle / d).mkdir(parents=True, exist_ok=True)

    for f in (ASSETS / "scripts").glob("*.py"):
        shutil.copy2(f, bundle / "scripts" / f.name)
    for f in (ASSETS / "templates").glob("*.md"):
        shutil.copy2(f, bundle / "templates" / f.name)

    seed = ASSETS / "seed"
    shutil.copy2(seed / "config.md", bundle / "config.md")
    shutil.copy2(seed / "README.md", bundle / "README.md")
    shutil.copy2(seed / ".gitignore", bundle / ".gitignore")
    shutil.copy2(seed / "state" / "cursors.json", bundle / "state" / "cursors.json")

    # init Stage 4: patch the copied cursors.json's config.timezone to match elephant.json
    cursors_path = bundle / "state" / "cursors.json"
    cursors = json.loads(cursors_path.read_text(encoding="utf-8"))
    cursors["config"]["timezone"] = "-05:00"
    cursors_path.write_text(json.dumps(cursors, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    elephant_json = {
        "owner": {"name": "Jane Doe", "slug": "jane-doe"},
        "knowledge_language": "en",
        "conversation_language": "en",
        "timezone": "-05:00",
    }
    (bundle / "elephant.json").write_text(
        json.dumps(elephant_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # reserved file: no frontmatter
    (bundle / "knowledge" / "log.md").write_text("# Log\n", encoding="utf-8")


def init_git(bundle):
    git = shutil.which("git")
    if not git:
        record(
            "git init + user.email/user.name config",
            False,
            "git not found on PATH — skipping (git is expected on all GitHub-hosted runners)",
        )
        return False
    r_init = run([git, "init"], cwd=bundle)
    r_email = run([git, "config", "user.email", "ci@example.com"], cwd=bundle)
    r_name = run([git, "config", "user.name", "Elephant CI"], cwd=bundle)
    ok = r_init.returncode == 0 and r_email.returncode == 0 and r_name.returncode == 0
    detail = "" if ok else (
        f"init: {r_init.returncode} {r_init.stderr}\n"
        f"email: {r_email.returncode} {r_email.stderr}\n"
        f"name: {r_name.returncode} {r_name.stderr}"
    )
    record("git init + user.email/user.name config", ok, detail)
    return ok


# ---------------------------------------------------------------------------
# c. seed owner/org entities + source + fact — WITH non-ASCII content
# ---------------------------------------------------------------------------

def seed_knowledge(bundle):
    (bundle / "knowledge" / "entities" / "person" / "jane-doe.md").write_text(
        f"""---
type: entity
kind: person
title: Jane Doe
description: Owner of this elephant-mem smoke-test bundle.
aliases: []
tags: []
created: {TODAY}
updated: {TODAY}
timestamp: {TODAY}
---

Jane Doe is the fictional owner of this smoke-test bundle.

<!-- BEGIN auto-facts -->
<!-- Regenerated by scripts/build-index.py — do not edit by hand. -->
<!-- END auto-facts -->
""",
        encoding="utf-8",
    )

    # accented alias — part of the UTF-8 regression test
    (bundle / "knowledge" / "entities" / "org" / "acme-corp.md").write_text(
        f"""---
type: entity
kind: org
title: Acme Corp
description: A fictional example org used by the elephant-mem smoke test.
aliases: [Companhia Exemplária]
tags: [example-seed]
created: {TODAY}
updated: {TODAY}
timestamp: {TODAY}
---

Acme Corp is a fictional org used to exercise the entity/fact/source shapes.

<!-- BEGIN auto-facts -->
<!-- Regenerated by scripts/build-index.py — do not edit by hand. -->
<!-- END auto-facts -->
""",
        encoding="utf-8",
    )

    sources_dir = bundle / "knowledge" / "sources" / MONTH
    sources_dir.mkdir(parents=True, exist_ok=True)
    source_rel = f"/sources/{MONTH}/{TODAY}-example.md"
    (sources_dir / f"{TODAY}-example.md").write_text(
        f"""---
type: source
description: A fictional example source used by the elephant-mem smoke test.
resource: https://example.com/smoke-test-notes
source-kind: note
channel: manual
occurred: {TODAY}
ingested: {TODAY}
tags: [example-seed]
created: {TODAY}
updated: {TODAY}
timestamp: {TODAY}
---

Fictional smoke-test note about Acme Corp's monthly budget meeting.

<!-- BEGIN auto-facts -->
<!-- Regenerated by scripts/build-index.py — do not edit by hand. -->
<!-- END auto-facts -->

# Citations

[1] https://example.com/smoke-test-notes
""",
        encoding="utf-8",
    )

    # non-ASCII title/description/body + emoji — the UTF-8 regression test
    (bundle / "knowledge" / "facts" / "reuniao-segunda-decisao-orcamento.md").write_text(
        f"""---
type: fact
description: Reunião de segunda-feira 🐘 — decisão de orçamento
entities: [/entities/person/jane-doe.md, /entities/org/acme-corp.md]
relations:
  supersedes: []
  superseded-by: []
  contradicts: []
  derived-from: []
  relates-to: []
sources: [{source_rel}]
confidence: high
status: active
tags: [example-seed]
created: {TODAY}
updated: {TODAY}
timestamp: {TODAY}
occurred: {TODAY}
times_referenced: 0
---

Reunião de segunda-feira 🐘 — decisão de orçamento: Jane Doe e a Acme Corp
aprovaram o orçamento fictício do trimestre.

**Why it matters / context:** Fabricado para testar suporte UTF-8 (acentos e
emoji) nos scripts do elephant-mem.

**Provenance note:** Fabricado para demonstração; não é uma observação real.
""",
        encoding="utf-8",
    )

    return source_rel


def add_second_fact(bundle, source_rel):
    (bundle / "knowledge" / "facts" / "acme-corp-second-fact.md").write_text(
        f"""---
type: fact
description: Acme Corp confirmed the fictional smoke-test contract renewal.
entities: [/entities/org/acme-corp.md]
relations:
  supersedes: []
  superseded-by: []
  contradicts: []
  derived-from: []
  relates-to: []
sources: [{source_rel}]
confidence: medium
status: active
tags: [example-seed]
created: {TODAY}
updated: {TODAY}
timestamp: {TODAY}
occurred: {TODAY}
times_referenced: 0
---

Acme Corp confirmed the fictional smoke-test contract renewal.

**Why it matters / context:** Exercises re-running `build-index.py` after the
bundle grows by one fact.

**Provenance note:** Fabricated for the smoke test; not a real observation.
""",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# e. send-email.py --dry-run (positive + negative)
# ---------------------------------------------------------------------------

def send_email_checks(bundle, scratch_root):
    import os

    pointer_path = scratch_root / "fake-pointer.json"
    pointer_path.write_text(
        json.dumps(
            {
                "bundle_path": str(bundle),
                "smtp": {
                    "host": "smtp.example.com",
                    "port": 587,
                    "username": "jane@example.com",
                    "from": "jane@example.com",
                    "password_env": "CI_FAKE_SMTP_PW",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    body = "This is a fictional smoke-test email body.\n"
    send_args = [
        "--config", str(pointer_path),
        "--to", "jane@example.com",
        "--subject", "smoke",
        "--body-stdin",
        "--dry-run",
    ]

    env_with_pw = dict(os.environ)
    env_with_pw["CI_FAKE_SMTP_PW"] = "fake-password-not-real"
    run_and_check(
        bundle, "send-email.py", send_args,
        "send-email.py --dry-run (CI_FAKE_SMTP_PW set)",
        env=env_with_pw, input_text=body, expect_zero=True,
    )

    env_without_pw = dict(os.environ)
    env_without_pw.pop("CI_FAKE_SMTP_PW", None)
    run_and_check(
        bundle, "send-email.py", send_args,
        "send-email.py --dry-run (CI_FAKE_SMTP_PW unset — expect failure)",
        env=env_without_pw, input_text=body, expect_zero=False,
    )


# ---------------------------------------------------------------------------
# f. regeneration check — adding a fact and rebuilding must change index.md
# ---------------------------------------------------------------------------

def regen_check(bundle, source_rel):
    index_path = bundle / "knowledge" / "index.md"
    before = index_path.read_text(encoding="utf-8") if index_path.exists() else None

    add_second_fact(bundle, source_rel)
    result = run_and_check(bundle, "build-index.py", [], "build-index.py (after adding second fact)")
    if not result or result.returncode != 0:
        return

    after = index_path.read_text(encoding="utf-8") if index_path.exists() else None
    changed = before is not None and after is not None and before != after
    detail = "" if changed else f"index.md before:\n{before}\nindex.md after:\n{after}"
    record("index.md content changed after regeneration", changed, detail)


def finish(scratch_root):
    print()
    print("Summary")
    print("-------")
    width = max((len(label) for label, _ in checks), default=0)
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


# Derived, not hand-listed: a hardcoded tuple proves "these nine refuse", never
# "every script refuses", so the tenth script is unguarded by construction —
# the same shape as the accident this guard exists to close. Globbing forces a
# decision on anything new under assets/scripts/. Exempt, with the reason:
#   run-hooks.py  — falls back to the same parent-of-__file__ root, but takes
#                   --bundle and creates nothing: append_log() returns early
#                   when <bundle>/state/ is absent.
#   send-email.py — resolves no bundle at all; its config comes from a pointer.
GUARD_EXEMPT = {"run-hooks.py", "send-email.py"}
GUARDED_SCRIPTS = tuple(
    p.name for p in sorted((ASSETS / "scripts").glob("*.py"))
    if p.name not in GUARD_EXEMPT
)


def checkout_guard_checks(scratch_root):
    """Every bundle script resolves its bundle as the parent of its own
    directory, which is correct at <bundle>/scripts/ and wrong in the plugin
    checkout, where it lands on plugin/assets/. It used to create knowledge/ or
    state/ there, inside the assets the marketplace publishes; four such files
    were once committed by accident. Assert the refusal, and assert it does NOT
    fire on a directory that merely happens to be named `assets`."""
    fake = scratch_root / "fake-plugin"
    (fake / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (fake / "assets" / "scripts").mkdir(parents=True, exist_ok=True)

    # No .claude-plugin sibling: the same `assets` basename must not trip it.
    plain = scratch_root / "plain" / "assets" / "scripts"
    plain.mkdir(parents=True, exist_ok=True)

    for name in GUARDED_SCRIPTS:
        src = ASSETS / "scripts" / name
        shutil.copy2(src, fake / "assets" / "scripts" / name)
        shutil.copy2(src, plain / name)

        r = run([sys.executable, fake / "assets" / "scripts" / name], cwd=fake)
        refused = r.returncode != 0 and "refusing to run inside" in (r.stdout + r.stderr)
        record(f"{name} refuses to run in the plugin checkout", refused,
               f"rc={r.returncode}\n{r.stdout}\n{r.stderr}")

        r2 = run([sys.executable, plain / name, "--help"], cwd=plain.parent.parent)
        tripped = "refusing to run inside" in (r2.stdout + r2.stderr)
        record(f"{name} does not trip on a bare assets/ dir", not tripped,
               f"rc={r2.returncode}\n{r2.stdout}\n{r2.stderr}")


def published_numbers_checks():
    """The numbers the repo publishes about itself, against what it is.

    Two of them, and both went stale by hand inside a single pull request. The
    check counts in the CHANGELOG's newest section are the ones that become
    `gh release create --notes`, so a wrong number there is a wrong number in
    the published release; four of the five were wrong for a day. The README's
    version badge is the number a reader compares against `claude plugin
    update`, and it is written in a second place from `plugin.json`.

    Both are read out of the files rather than restated here, so this check has
    nothing of its own to keep current. A suite the CHANGELOG does not mention
    is not an error: only the numbers actually claimed are compared.
    """
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = changelog.split("\n## [", 2)
    section = newest[1] if len(newest) > 1 else changelog

    claimed = dict(re.findall(
        r"`tests/(\w+\.py)`[^`\n]{0,40}?\((\d+)(?: checks?)?\)", section))
    claimed.update(dict(re.findall(
        r"`tests/(\w+\.py)`[^`\n]{0,40}?\bgrew to (\d+)", section)))
    claimed.update(dict(re.findall(
        r"`tests/(\w+\.py)`[^`\n]{0,40}?\bto (\d+)\b", section)))
    record("the newest CHANGELOG section claims a check count for at least one "
           "suite, so this check is not passing vacuously", bool(claimed),
           sorted(claimed))

    for name, want in sorted(claimed.items()):
        suite = REPO_ROOT / "tests" / name
        if not suite.is_file():
            record(f"CHANGELOG names tests/{name}, which exists", False,
                   str(suite))
            continue
        r = run([sys.executable, str(suite)], cwd=REPO_ROOT)
        got = re.findall(r"(\d+)/(\d+) checks passed", r.stdout + r.stderr)
        actual = got[-1][1] if got else None
        record(f"CHANGELOG says tests/{name} has {want} checks, and it does",
               actual == want, f"actual={actual} rc={r.returncode}")

    version = json.loads(
        (REPO_ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"))["version"]
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    badge = version.replace("-", "--").replace(".", ".")
    record("the README badge carries the version plugin.json declares",
           f"elephant--mem-v{badge}-" in readme, f"version={version}")


def main():
    print("elephant-mem cross-platform smoke test")
    print(f"python:   {sys.version.splitlines()[0]}")
    print(f"platform: {sys.platform}")
    print()

    scratch_root = Path(tempfile.mkdtemp(prefix="elephant-mem-smoke-"))
    bundle = scratch_root / "bundle"
    print(f"scratch bundle: {bundle}\n")

    try:
        scaffold_bundle(bundle)
        record("scaffold bundle directory tree + copy assets", True)
    except Exception as e:  # noqa: BLE001 - report and stop, this is a smoke test
        record("scaffold bundle directory tree + copy assets", False, str(e))
        return finish(scratch_root)

    init_git(bundle)

    try:
        source_rel = seed_knowledge(bundle)
        record("seed owner/org entities + source + fact (non-ASCII content)", True)
    except Exception as e:  # noqa: BLE001
        record("seed owner/org entities + source + fact (non-ASCII content)", False, str(e))
        return finish(scratch_root)

    run_and_check(bundle, "build-index.py", [], "build-index.py (initial)")
    run_and_check(bundle, "validate-okf.py", [], "validate-okf.py")
    run_and_check(bundle, "briefing.py", ["--days", "7"], "briefing.py --days 7")
    run_and_check(
        bundle, "briefing.py", ["--days", "7", "--entity", "jane-doe"],
        "briefing.py --days 7 --entity jane-doe",
    )
    run_and_check(bundle, "rename-entity.py", ["--help"], "rename-entity.py --help")
    run_and_check(bundle, "snapshot-drift.py", [], "snapshot-drift.py")

    send_email_checks(bundle, scratch_root)

    regen_check(bundle, source_rel)

    checkout_guard_checks(scratch_root)

    published_numbers_checks()

    return finish(scratch_root)


if __name__ == "__main__":
    sys.exit(main())
