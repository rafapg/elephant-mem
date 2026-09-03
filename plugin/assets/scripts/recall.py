#!/usr/bin/env python3
"""Recall record for elephant-mem — what the owner's answers actually cite.

Two files, one purpose. `state/consumption-log.jsonl` is the raw, append-only
trace: one JSON line per answered read, holding the bundle-absolute paths that
answer cited and the entity slugs it was about. `state/recall.json` is the
rolled-up pyramid over that trace, the fixed-size lookup a consumer reads
instead of rescanning the log per item.

**Why the line is written by this script and not typed by the model.** The
log shipped as prose in `_shared/core.md`: every adopting procedure re-typed
the JSON object, and every one of them carried its own chance of a malformed
line or a missing field. One writer kills that class, and puts the
swallow-and-continue in one place instead of in every procedure. It is called
after the answer is decided, so it can never change or delay an answer:

    python3 scripts/recall.py log --mode query \\
        --item /entities/person/angelo.md --item /facts/2026-08/export-fix.md \\
        --entity angelo --entity acme

**Failure is silent by contract.** A missing or unwritable `state/` makes `log`
exit 0 and write nothing. A read must never fail, and must never emit anything
of its own into the transcript, because of telemetry. `show` is how you check
whether the record is being written.

**`state/recall.json` is disposable.** It is derived from a git-ignored log and
rebuildable only forward, so every consumer must behave correctly when it is
absent, empty or malformed — `load()` returns the empty record for all three,
warning once on stderr for the malformed case rather than raising.

**The record is sensitive.** It holds which entities were consulted and when,
which exposes query patterns over named people. Both files are git-ignored in
the bundle's `.gitignore`; nothing here prints a path or a slug except `show`,
which is the operator deliberately asking to see it.

Subcommands:
  log --mode <mode> [--item <bundle path>]... [--entity <slug>]...
                            append one line to the consumption log. Silent,
                            always exits 0. `--item` and `--entity` repeat;
                            both are normalized and de-duplicated here so the
                            caller never has to.
  show                      dump the canonical `state/recall.json`.

Every mutating subcommand accepts `--at <iso>` to override "now" (tests, and
replaying a run). Timestamps are generated in Python, never shelled out to
`date` — BSD `date` on macOS has no `%:z` and silently emits a literal `:z`,
which is not parseable ISO 8601.
"""
import argparse
import json
import posixpath
import sys
from datetime import datetime
from pathlib import Path

# Windows consoles default to a legacy codepage (cp1252); force UTF-8 on the
# standard streams so printing non-ASCII content (accented names, em dashes)
# doesn't raise UnicodeEncodeError. No-op on POSIX / when already UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BUNDLE = Path(__file__).resolve().parent.parent
STATE = BUNDLE / "state"

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
LOG = STATE / "consumption-log.jsonl"
RECALL = STATE / "recall.json"

SCHEMA = 1

COMMENT = (
    "Rolled-up recall record — which bundle items and entities the owner's "
    "answers actually cited, and when. Derived from the git-ignored "
    "state/consumption-log.jsonl and rebuildable only forward, so it is "
    "disposable: every consumer treats it as empty when it is missing. "
    "Managed by scripts/recall.py; do not hand-edit."
)


def now_iso(at=None):
    """Local time with a real UTC offset, as ISO 8601."""
    if at:
        return datetime.fromisoformat(at).isoformat()
    return datetime.now().astimezone().isoformat()


def _strip_bundle_prefix(s):
    """Reduce a real filesystem path inside this bundle to a bundle-relative one.

    Tried against the path as given *and* against its resolved form: on macOS a
    bundle under a tempdir resolves through `/var` → `/private/var`, so an
    honest absolute path from a caller does not textually match the script's own
    resolved root. Leaves anything outside the bundle untouched.
    """
    candidates = [s]
    if s.startswith("/") or (len(s) > 2 and s[1] == ":"):
        try:
            candidates.append(Path(s).resolve().as_posix())
        except (OSError, ValueError):
            pass
    for candidate in candidates:
        for prefix in (KNOWLEDGE.as_posix(), BUNDLE.as_posix()):
            if candidate.startswith(prefix + "/"):
                return candidate[len(prefix):]
    return s


def normalize_item(raw):
    """Coerce one cited path to the bundle-absolute form `/facts/….md`.

    Callers hand over whatever they had in the answer: a bundle-absolute link
    exactly as written in the markdown, a `knowledge/`-relative path, or the
    real filesystem path a tool printed. All three name the same file, and a
    consumer that has to guess which convention a line used cannot prune a
    path that no longer exists. Normalize once, at the only writer.

    Returns None for anything that is not a path (empty, or bare `/`).
    """
    s = (raw or "").strip().replace("\\", "/")
    if not s:
        return None
    # An absolute filesystem path inside this bundle, POSIX or Windows shaped.
    # Stripping the bundle prefix leaves `/knowledge/…`, which the tail of this
    # function reduces the same way it reduces a hand-written `knowledge/…`.
    s = _strip_bundle_prefix(s)
    if s.startswith("./"):
        s = s[2:]
    if not s.startswith("/"):
        s = "/" + s
    # normpath collapses `//`, `.` and `..`; it cannot escape the leading `/`,
    # so a hostile `../../etc/passwd` lands harmlessly at `/etc/passwd`.
    s = posixpath.normpath(s)
    if s.startswith("/knowledge/"):
        s = s[len("/knowledge"):]
    return s if s not in ("/", ".", "") else None


def normalize_entity(raw):
    """Coerce one entity reference to a bare slug.

    A mode holding `/entities/person/angelo.md` and a mode holding `angelo`
    are naming the same entity; keyed apart they would each count half.
    """
    s = (raw or "").strip().replace("\\", "/")
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    if s.endswith(".md"):
        s = s[:-3]
    return s.strip().lower() or None


def dedupe(values, normalizer):
    """Normalize, drop the empties, keep the first occurrence's order."""
    out = []
    for value in values or []:
        norm = normalizer(value)
        if norm and norm not in out:
            out.append(norm)
    return out


def append(record):
    """Append one line to the consumption log. Never raises.

    Returns True when the line landed, False when it did not. Nothing prints
    either way: this runs after an answer is decided and must not add a word
    to it, nor leak a cited path into a transcript.
    """
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001 — best-effort by contract, see the docstring
        return False


def empty():
    """The canonical record for a bundle that has never rolled."""
    return {
        "comment": COMMENT,
        "schema": SCHEMA,
        # ISO timestamp of the last consumption line folded in. `roll` reads it
        # to stay idempotent over a log it re-reads whole every time.
        "rolled_through": None,
        "generated": None,
        # path -> bucketed citation counts; slug -> the same. Item-agnostic on
        # purpose: the log carries facts, loops and sources in one array, so
        # the roll-up covers all of them at no extra cost.
        "items": {},
        "entities": {},
    }


def load():
    """The canonical record, or the empty one. Never raises, never exits."""
    if not RECALL.exists():
        return empty()
    try:
        data = json.loads(RECALL.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
    except Exception as exc:  # noqa: BLE001
        print(
            f"warning: state/recall.json is unreadable ({exc}) — treating it as "
            "empty. It is derived state; `recall.py roll` rebuilds it forward.",
            file=sys.stderr,
        )
        return empty()
    base = empty()
    for key, default in base.items():
        value = data.get(key, default)
        if default is not None and not isinstance(value, type(default)):
            value = default
        data[key] = value
    data["comment"] = COMMENT
    return data


def save(data):
    """Write the canonical record. Only `roll` should call this."""
    STATE.mkdir(parents=True, exist_ok=True)
    RECALL.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def cmd_log(args):
    mode = (args.mode or "").strip()
    if not mode:
        # Not a usage error worth failing a read over: a line with no mode is
        # simply not worth writing.
        return 0
    append(
        {
            "ts": now_iso(args.at),
            "mode": mode,
            "entities": dedupe(args.entity, normalize_entity),
            "facts_cited": dedupe(args.item, normalize_item),
        }
    )
    return 0


def cmd_show(args):
    print(json.dumps(load(), indent=2, ensure_ascii=False))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="recall.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("log", help="append one consumption line (silent, always 0)")
    sp.add_argument("--mode", required=True, help="the read mode's name")
    sp.add_argument(
        "--item",
        action="append",
        default=[],
        metavar="PATH",
        help="a bundle-absolute path the answer cited; repeat per item",
    )
    sp.add_argument(
        "--entity",
        action="append",
        default=[],
        metavar="SLUG",
        help="an entity slug the answer was about; repeat per entity",
    )
    sp.add_argument("--at", help="override 'now' with an ISO timestamp")
    sp.set_defaults(func=cmd_log)

    sub.add_parser("show", help="dump the canonical recall.json").set_defaults(
        func=cmd_show
    )
    return p


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
