#!/usr/bin/env python3
"""Regression tests for how each skill under plugin/skills/ may be invoked.

A scheduled task wraps its prompt in a `<scheduled-task>` preamble, so the
`/elephant-mem:<mode>` it carries is not the first token of the message and the
harness does not expand it as a slash command. The run reaches the skill through
the Skill tool, and since Claude Code 2.1.293 the Skill tool refuses any skill
whose frontmatter carries `disable-model-invocation: true`. Every scheduled
`catch-up` failed from the first run on 2.1.293 until the flag came off; the
scheduled `push-start-day` did worse, falling back to `start-day`, which printed
a briefing without the agenda and delivered nothing, and looked like a success.

What is checked:

  1. No skill whose description says it runs from a schedule carries the flag.
     Derived from the descriptions, not hand-listed, so a fifth scheduled
     routine is covered the day it ships.
  2. The four known scheduled routines are among those the derivation found, so
     rewording a description cannot quietly drop one out of check 1.
  3. Each of the four, now visible to the model, says in its description that
     it runs only when named and lists phrasings that are not a trigger. That
     is the first guard against Claude reaching for a writer unasked.
  4. Each of the four also opens its procedure with a **Named, or stop.** step,
     the second guard: a run whose prompt does not name the routine ends before
     any side effect, so a description that misfires still changes nothing. The
     step must name its own routine and come before the first step that acts.
     `decay` needs it as much as the others: its review gate is skipped for any
     run from a scheduled task, and an hourly `catch-up` is one.
  5. Every description fits the 1024-character limit on skill descriptions.

Pure stdlib, Python 3.10+. Reads the shipped SKILL.md and procedure.md files;
runs nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "plugin" / "skills"
SCHEDULED = ("catch-up", "push-start-day", "close-loops", "decay")
FLAG = "disable-model-invocation: true"
# Any spelling a YAML parser reads as the flag set: `True`, quoted, extra
# spaces around the colon, a trailing comment. A literal `in` test missed all
# of those, and each one blocks the Skill tool just the same.
FLAG_RE = re.compile(
    r"^disable-model-invocation[ \t]*:[ \t]*[\"']?true[\"']?[ \t]*(#.*)?$",
    re.M | re.I)
# Where each model-invocable routine keeps its second guard, the step that
# stops a run nobody named. Pinned like the description's "Never on a guess".
GUARD = "**Named, or stop.**"
GUARD_FILES = {
    "catch-up": "procedure.md",
    "close-loops": "procedure.md",
    "decay": "procedure.md",
    "push-start-day": "SKILL.md",
}
# The first heading or paragraph of each file that starts acting. The guard
# must come before it: at the end of the file it would run too late.
FIRST_ACT = re.compile(r"^(?:## Preflight|## Destination|\*\*Preflight)", re.M)

checks: list[tuple[str, bool]] = []


def record(label: str, passed: bool, detail: str = "") -> None:
    checks.append((label, passed))
    print(f"{'PASS' if passed else 'FAIL'}  {label}")
    if not passed and detail:
        print(f"      {detail}")


def frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    return text[4:end + 1] if end != -1 else ""


def description(fm: str) -> str:
    """A block-scalar description (`>`, `|`, any chomping), joined into one
    line. Matching only `>` let a `>-` description fall through to the inline
    branch, read as "-", and drop its skill out of every derived check."""
    m = re.search(r"^description:[ \t]*[>|][-+]?[ \t]*\n((?:[ \t]+.*\n?)+)",
                  fm, re.M)
    if m:
        return " ".join(line.strip() for line in m.group(1).splitlines())
    m = re.search(r"^description: (.*)$", fm, re.M)
    return m.group(1).strip() if m else ""


def load_skills() -> dict[str, tuple[str, str]]:
    skills = {}
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        fm = frontmatter(path)
        skills[path.parent.name] = (fm, description(fm))
    return skills


def main() -> int:
    skills = load_skills()
    record("plugin/skills/ ships at least the four scheduled routines",
           all(name in skills for name in SCHEDULED), str(sorted(skills)))

    scheduled_by_text = sorted(
        name for name, (_, desc) in skills.items()
        if re.search(r"schedul", desc, re.I))
    record("every scheduled routine is found by its own description: "
           + ", ".join(SCHEDULED),
           all(name in scheduled_by_text for name in SCHEDULED),
           f"derived: {scheduled_by_text}")

    for name in scheduled_by_text:
        fm, _ = skills[name]
        record(f"{name}: runs from a schedule, so it does not carry {FLAG!r} "
               "(the Skill tool refuses it since Claude Code 2.1.293)",
               not FLAG_RE.search(fm), fm[:200])

    for name in SCHEDULED:
        _, desc = skills.get(name, ("", ""))
        record(f"{name}: description restricts it to a prompt that names "
               f"/elephant-mem:{name}",
               "Use ONLY when the prompt names it" in desc
               and f"/elephant-mem:{name}" in desc, desc)
        record(f"{name}: description names phrasings that are not a trigger",
               "Never on a guess" in desc, desc)

    for name, filename in GUARD_FILES.items():
        path = SKILLS_DIR / name / filename
        body = path.read_text(encoding="utf-8") if path.is_file() else ""
        # The name is looked for inside the step's own paragraph: both
        # close-loops and push-start-day cite their name elsewhere in the file,
        # so a whole-file search passed a step that named another routine.
        guard = re.search(re.escape(GUARD) + r"(.*?)(?:\n\n|\Z)", body, re.S)
        first = FIRST_ACT.search(body)
        record(f"{name}: {filename} stops a run whose prompt did not name it "
               f"({GUARD}), before its first step",
               bool(guard) and f"/elephant-mem:{name}" in guard.group(1)
               and (first is None or guard.start() < first.start()), str(path))

    for name, (_, desc) in skills.items():
        record(f"{name}: description is present and fits 1024 characters "
               f"({len(desc)})", 0 < len(desc) <= 1024)

    print()
    n_pass = sum(1 for _, passed in checks if passed)
    print(f"{n_pass}/{len(checks)} checks passed.")
    return 0 if n_pass == len(checks) and checks else 1


if __name__ == "__main__":
    sys.exit(main())
