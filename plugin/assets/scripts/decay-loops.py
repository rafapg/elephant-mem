#!/usr/bin/env python3
"""Decay stale `open` loops into `status: expired`.

Philosophy (owner-approved): loops are noise that, when it keeps recurring,
earns the right to stay alive — otherwise it should decay automatically.
Re-mention resets the clock elsewhere, in exactly one place: `catch-up` step 4
bumps a loop's `updated:` field to a source's date when that source re-raises
the loop without showing it done. (`capture` opens loops and never returns to
one; it writes no bump.) This script only reads the signal; it never itself
decides what counts as re-mention.

Candidate = `status: open` AND its last-activity date (the max of
`updated`/`opened`/`created`, whichever are present, and the date
`state/recall.json` last records the loop as cited by an answer) is older than
`elephant.json` -> `decay.loop_expiry_days` (default 45 — same defensive
fallback pattern as build-index.py's `hub_max_facts`: missing file, missing
key, or malformed JSON all fall back to the default instead of crashing).

The citation date is the fourth date and nothing more. `updated` says a source
re-raised the loop; a citation says the owner's own answers still reach for it,
which is the same claim from the other side. It only ever protects: a loop with
no citation decays on its file dates exactly as it did before recall existed, so
an absent, empty or malformed `state/recall.json` collapses this script to its
previous behavior rather than to a crash.

Default mode is DRY-RUN: prints one candidate per line (bundle-relative path +
age in days) plus a trailing count, and changes nothing on disk. `--apply`
flips `status: open` -> `status: expired`, stamps an `expired: YYYY-MM-DD`
field right after the status line, and appends a `**Resolution:**` paragraph
to the body — it never deletes a file and never touches `done` / `dropped` /
already-`expired` loops (they're excluded by the `status: open` filter before
any file is opened for writing).

**The resolution is prose in the body, the same shape `close-loops` writes**
(see `../skills/close-loops/procedure.md` -> step 3): a `**Resolution:**`
paragraph whose first sentence stands alone, because that first sentence is all
`tracking/resolved-loops.md` prints. Never a frontmatter field — a sentence of
judgment carries `: ` and sometimes ` #`, which break or silently truncate an
unquoted YAML value. Decay's says what a closure's cannot: that nothing
happened. It is generated, so it is written in English rather than in the
bundle's `knowledge_language`; the dates and the paths in it are the content,
and its owner can rewrite the sentence.

**`--apply` is gated per loop on `state/closure-sweep.json`** (E15, E18). A
candidate is expirable only if the sweep shows it was examined on or after its
own last activity and that the examination did not close it — the same
"settled" test `close-loops.py` uses to drop a loop from its queue, so what
decay may expire is exactly what left that queue. An unexamined candidate is
refused **by name**, with the `close-loops` command to examine it, and the run
still exits 0: expiry is a verdict of silence, and silence a routine never
looked at is not evidence of anything. Losing the record therefore parks decay
instead of corrupting it: every loop reads as never examined and nothing
expires until `close-loops` records examinations again.

`--skip-sweep` bypasses that gate entirely and restores the behavior this
script had before the gate existed. It is the deliberate way out of a lost or
unwritable record, and the flag the suites use to pin the pre-gate rules.

Exit code is 0 whenever the script completed a run, whether or not it found
candidates — non-zero only on a hard, unexpected error. After `--apply` the
caller is expected to run `build-index.py` (this script does not — it only
touches loop files).
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
# Control state, outside the OKF bundle: `close-loops` writes it (its
# procedure.md -> "The sweep record"), this script only ever reads it.
SWEEP = BUNDLE / "state" / "closure-sweep.json"

DEFAULT_EXPIRY_DAYS = 45

FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def loop_expiry_days():
    """Read `decay.loop_expiry_days` from elephant.json. Defensive by design
    (mirrors ingest-audio.py's config reader / build-index.py's hub_max_facts):
    a missing file, missing key, non-dict `decay`, or malformed JSON all fall
    back to DEFAULT_EXPIRY_DAYS instead of crashing."""
    try:
        with open(BUNDLE / "elephant.json", encoding="utf-8") as fh:
            data = json.load(fh)
        decay_cfg = data.get("decay")
        if isinstance(decay_cfg, dict):
            v = decay_cfg.get("loop_expiry_days")
            if isinstance(v, int) and v > 0:
                return v
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

    open-loop.md ships `status: open          # open | done | dropped`, so with
    the comment glued on `field(block, "status") != "open"` was true for every
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


def load_sweep():
    """`state/closure-sweep.json`, or the empty record. Never raises.

    Read here rather than imported from `close-loops.py`: this is the file
    standing between decay and a lane it may not touch, so the gate must behave
    the same in a bundle whose `update` brought the new decay script and not yet
    its sibling. The tolerance is deliberately identical to `close-loops.py`'s
    reader of the same file, including reading a bare ISO string in place of the
    entry dict, because a hand-repaired record is a likely shape and refusing it
    would park expiry over a formatting opinion.

    Shape (written by the `close-loops` routine, never by a script):

        {"schema": 1, "generated": "<iso>",
         "loops": {"/tracking/loops/x.md": {"examined": "2026-09-01",
                                            "outcome": "open"}}}

    Absent or malformed reads as empty, which is E18: every loop then reads as
    never examined and `--apply` expires nothing until `close-loops` records
    examinations again, or until `--skip-sweep`.
    """
    if not SWEEP.exists():
        return {"loops": {}}
    try:
        data = json.loads(SWEEP.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
    except Exception as exc:  # noqa: BLE001
        print(
            f"warning: state/closure-sweep.json is unreadable ({exc}) — treating "
            "it as empty, so every loop reads as never examined and nothing "
            "expires this run.",
            file=sys.stderr,
        )
        return {"loops": {}}
    loops = data.get("loops")
    return {"loops": loops if isinstance(loops, dict) else {}}


def sweep_verdict(sweep, link):
    """`(examined ISO date, outcome)` for one loop, either half None."""
    entry = (sweep.get("loops") or {}).get(link)
    outcome = None
    if isinstance(entry, str):
        value = entry
    elif isinstance(entry, dict):
        value = entry.get("examined") or entry.get("date") or entry.get("last")
        raw = entry.get("outcome")
        outcome = raw.strip().lower() if isinstance(raw, str) else None
    else:
        return None, None
    m = DATE.search(value) if isinstance(value, str) else None
    return (m.group(0) if m else None), outcome


def gate(sweep, link, activity):
    """`(expirable, reason)` for one candidate under the sweep gate.

    Expirable iff `close-loops` examined the loop on or after its own last
    activity and did not close it. On-or-after, not strictly after, so this is
    exactly `close-loops.py`'s "settled" test: what leaves that queue is what
    decay may consider, and a loop examined the same day it last moved does not
    have to wait a full extra cycle.

    `activity` is decay's own last-activity date, so it includes the citation
    date `close-loops.py` does not read. That only ever makes the gate stricter:
    a loop the owner's answers still reach for is not expirable on an older
    examination.
    """
    examined, outcome = sweep_verdict(sweep, link)
    if examined is None:
        return False, "never examined — state/closure-sweep.json has no entry for it"
    if outcome == "done":
        return False, (
            f"close-loops closed it on {examined}; a `done` loop is not decay's "
            "to expire"
        )
    if activity is not None and examined < activity.isoformat():
        return False, (
            f"examined {examined}, before its last activity {activity} — it "
            "moved after the examination and has not been re-read since"
        )
    return True, f"examined {examined}, on or after its last activity {activity}"


def last_activity(block, cited=None):
    """Max of `updated`/`opened`/`created` and `cited` (whichever parse as a
    date), or None if none of the four are present/parseable — treated as
    "can't tell, not a candidate" rather than an error.

    `cited` is the ISO date `state/recall.json` holds for this loop's
    bundle-absolute path, from `recall.py`'s `last_cited()`. Passing None is
    the whole of the degraded path: no record, no entry for this loop, or no
    `recall.py` at all all arrive here as None and leave the three file dates
    deciding on their own.
    """
    dates = []
    for key in ("updated", "opened", "created"):
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


def expire_block(block, expired_date):
    """Rewrite a frontmatter block's `status: open` line to `status: expired`
    and stamp `expired: <date>` right after it (updating it in place if a
    stray `expired:` line already exists). Returns the new block, or None if
    the block has no `status: open` line (caller should skip the file)."""
    lines = block.splitlines()
    status_idx = next(
        (i for i, ln in enumerate(lines) if re.match(r"^status:\s*open\b", ln)), None
    )
    if status_idx is None:
        return None
    lines[status_idx] = re.sub(r"^(status:\s*)open\b", r"\1expired", lines[status_idx])
    expired_idx = next((i for i, ln in enumerate(lines) if re.match(r"^expired:\s*", ln)), None)
    if expired_idx is not None:
        lines[expired_idx] = f"expired: {expired_date}"
    else:
        lines.insert(status_idx + 1, f"expired: {expired_date}")
    return "\n".join(lines)


def resolution_paragraph(age_days, activity, examined, expiry_days, today):
    """The `**Resolution:**` paragraph decay appends when it expires a loop.

    Same shape as the one `close-loops` writes by hand (E17): a body paragraph,
    two to four sentences, whose **first sentence stands alone** — that
    sentence, and nothing else from here, is what `tracking/resolved-loops.md`
    prints next to the date and the outcome. So it names the silence in full
    rather than opening with "this one went quiet".

    `examined` is the sweep's date when there is one; a `--skip-sweep` run over
    a loop no examination ever reached says so instead of claiming one.
    """
    if examined:
        opening = (
            f"**Resolution:** Expired on {today} after {age_days} days of "
            "silence: no later source re-raised it, no answer cited it, and the "
            f"`close-loops` examination on {examined} found no evidence it was "
            "delivered."
        )
        middle = (
            f"Its last activity was {activity}, older than the {expiry_days}-day "
            "window `decay.loop_expiry_days` sets in `elephant.json`, and the "
            "examination that cleared it for expiry is recorded in "
            "state/closure-sweep.json."
        )
    else:
        opening = (
            f"**Resolution:** Expired on {today} after {age_days} days of "
            "silence: no later source re-raised it, no answer cited it, and no "
            "`close-loops` examination is on record for it."
        )
        middle = (
            f"Its last activity was {activity}, older than the {expiry_days}-day "
            "window `decay.loop_expiry_days` sets in `elephant.json`; this run "
            "passed `--skip-sweep`, so the sweep gate did not stand between the "
            "loop and expiry."
        )
    closing = (
        "Expiry states silence, not a verdict on the commitment: a later source "
        "that re-raises this loop reopens it, and closure by evidence would have "
        "been written here by `close-loops` instead."
    )
    return f"{opening} {middle} {closing}"


def append_resolution(text, paragraph):
    """`text` with `paragraph` as its last body paragraph, one blank line after
    what was there and a single trailing newline.

    End of body is where the template puts `**Closure signal:**`, so appending
    here lands the resolution after it — the placement `close-loops`'s procedure
    specifies for the paragraph it writes by hand.
    """
    return text.rstrip("\n") + "\n\n" + paragraph + "\n"


def find_candidates(expiry_days):
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=expiry_days)
    cited_on = recall_lookup()
    candidates = []
    for path in loop_files():
        text = path.read_text(encoding="utf-8")
        m = FM.match(text)
        if not m:
            continue
        block = m.group(1)
        if field(block, "status") != "open":
            continue
        activity = last_activity(block, cited_on(bundle_link(path)))
        if activity is None or activity > cutoff:
            continue
        candidates.append((path, text, m, (today - activity).days, activity))
    candidates.sort(key=lambda c: -c[3])
    return candidates


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                     help="expire the candidates found (default: dry-run, changes nothing)")
    ap.add_argument("--skip-sweep", action="store_true",
                     help="bypass the state/closure-sweep.json gate: expire every "
                          "candidate whether or not close-loops examined it")
    args = ap.parse_args()

    expiry_days = loop_expiry_days()
    candidates = find_candidates(expiry_days)
    sweep = None if args.skip_sweep else load_sweep()

    def verdict(path, activity):
        """(expirable, reason) — always expirable when the gate is off."""
        if sweep is None:
            return True, "--skip-sweep: the sweep gate was not consulted"
        return gate(sweep, bundle_link(path), activity)

    if not args.apply:
        n_cleared = 0
        for path, _text, _m, age_days, activity in candidates:
            ok, reason = verdict(path, activity)
            n_cleared += ok
            note = "" if sweep is None else f" — {'cleared' if ok else 'held back'}: {reason}"
            print(f"{bundle_link(path)}  ({age_days}d stale){note}")
        print(f"\n{len(candidates)} candidate(s) for decay "
              f"(status: open, stale > {expiry_days}d — dry-run, pass --apply to expire)")
        if sweep is not None and candidates:
            print(f"Of those, {n_cleared} cleared by state/closure-sweep.json and "
                  f"{len(candidates) - n_cleared} held back until close-loops has "
                  f"examined them: python3 scripts/close-loops.py")
        return 0

    today = datetime.date.today()
    today_str = today.isoformat()
    n_expired, held = 0, []
    for path, text, m, age_days, activity in candidates:
        ok, reason = verdict(path, activity)
        if not ok:
            held.append((bundle_link(path), age_days, reason))
            print(f"held back: {bundle_link(path)}  ({age_days}d stale) — {reason}")
            continue
        new_block = expire_block(m.group(1), today_str)
        if new_block is None:
            print(f"warning: {bundle_link(path)} — could not locate `status: open` line, skipped",
                  file=sys.stderr)
            continue
        examined = None if sweep is None else sweep_verdict(sweep, bundle_link(path))[0]
        new_text = text[:m.start(1)] + new_block + text[m.end(1):]
        new_text = append_resolution(
            new_text,
            resolution_paragraph(age_days, activity, examined, expiry_days, today_str),
        )
        path.write_text(new_text, encoding="utf-8")
        n_expired += 1
        print(f"expired: {bundle_link(path)}  ({age_days}d stale)")

    print(f"\n{n_expired} loop(s) expired (status: open -> expired, stale > {expiry_days}d). "
          f"Run build-index.py next.")
    if held:
        print(f"{len(held)} candidate(s) held back: state/closure-sweep.json does not show "
              f"them examined after their own last activity, so their silence is a lane "
              f"nothing has read. Run the close-loops routine — python3 "
              f"scripts/close-loops.py — and they expire on a later run. "
              f"--skip-sweep expires them without the gate.")
        if not n_expired:
            print("Nothing was written this run: no rebuild and no commit are needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
