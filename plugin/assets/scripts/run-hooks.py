#!/usr/bin/env python3
"""Fire elephant-mem lifecycle hooks after an ingestion cycle completes.

elephant-mem is a platform, not just a plugin. After a `capture`, `ingest`, or
`catch-up` finishes (markdown written, index rebuilt, committed), the mode emits
a `post_ingest` event by calling this runner. Any plugin can subscribe by adding
a command to the `hooks.post_ingest` array in the bundle's `elephant.json` — the
wiki generator is the first such subscriber. This decouples reactors (wiki,
export, notify) from the ingestion modes: they never import each other, they meet
at the event contract.

Why a lifecycle event and not a git hook: the event names *what happened*
("an ingestion landed"), not *how* ("git committed"). A subscriber depends on
the contract below, never on the bundle's VCS plumbing. And why fire it from the
modes (not from build-index.py): `build-index.py` runs many times inside a single
`maintain`; emitting an event per rebuild would be noise. The event fires ONCE,
at the end of an ingestion cycle.

Contract a hook may rely on:
  - It runs AFTER the derived surfaces (manifest.jsonl, backlinks) are current
    and the ingestion commit has landed — it sees final, committed state.
  - These environment variables are set:
      ELEPHANT_BUNDLE   absolute path to the bundle root
      ELEPHANT_EVENT    the event name (e.g. "post_ingest")
      ELEPHANT_TRIGGER  the mode that fired it ("capture" | "ingest" |
                        "catch-up"); empty string if not supplied
  - A hook that fails (non-zero exit, timeout, crash, bad command) is logged and
    skipped. It NEVER breaks the ingestion that triggered it. Hooks are
    best-effort reactors: this runner exits 0 whenever the event was processed,
    so the caller can never mistake a hook failure for an ingestion failure.

Config shape in elephant.json:
  "hooks": {
    "post_ingest": [
      { "name": "wiki", "run": ["/usr/bin/python3", "/path/to/wiki.py", "build"] }
    ]
  }
`hooks` is a MAP of event name -> list of entries, so new events
(post_maintain, ...) can be added without breaking the schema. Each entry:
  run      required. The command as a list argv (["python3", "x.py", "build"] —
           preferred, no quoting pitfalls) OR a string ("python3 x.py build",
           split with shell-like rules). NOT a shell pipeline; wrap in
           `bash -c "..."` yourself if you need one.
  name     optional label used in logs (default "(unnamed)").
  timeout  optional per-hook timeout in seconds (default 120).
  enabled  optional bool; set false to keep an entry registered but dormant.

Usage:
  run-hooks.py <event> [--trigger <mode>] [--bundle <path>]
               [--timeout <sec>] [--dry-run]

Pure stdlib, Python 3.10+. Cross-platform (explicit UTF-8 I/O).
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime

# Windows consoles default to a legacy codepage (cp1252); force UTF-8 on the
# standard streams so printing non-ASCII hook output doesn't raise. No-op on
# POSIX / when already UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_TIMEOUT = 120


def warn(msg):
    print(f"run-hooks: {msg}", file=sys.stderr)


def bundle_root(override):
    if override:
        return os.path.abspath(override)
    # This script is copied to <bundle>/scripts/, so the bundle is one level up.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_hooks(bundle, event):
    """Return the list of hook entries for `event` (or [] if none/unreadable).

    A missing elephant.json, a missing `hooks` block, or a missing event key are
    all the common no-subscribers case — silent. Only a malformed file or a
    wrong-typed value warns, and even then we return [] rather than raise."""
    path = os.path.join(bundle, "elephant.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        warn(f"could not read {path}: {exc}")
        return []
    hooks = cfg.get("hooks")
    if not isinstance(hooks, dict):
        if hooks is not None:
            warn("`hooks` in elephant.json is not an object — ignoring")
        return []
    entries = hooks.get(event)
    if entries is None:
        return []
    if not isinstance(entries, list):
        warn(f"hooks.{event} is not a list — ignoring")
        return []
    return entries


def append_log(bundle, fields):
    """Append one tab-separated line to <bundle>/state/hooks.log (best-effort).

    Useful for debugging unattended catch-up runs whose stderr is otherwise
    lost. Skipped silently if state/ doesn't exist or the write fails."""
    state_dir = os.path.join(bundle, "state")
    if not os.path.isdir(state_dir):
        return
    stamp = datetime.now().isoformat(timespec="seconds")
    try:
        with open(os.path.join(state_dir, "hooks.log"), "a", encoding="utf-8") as fh:
            fh.write("\t".join([stamp, *(str(f) for f in fields)]) + "\n")
    except OSError:
        pass


def resolve_argv(cmd):
    """Turn a hook `run` value into an argv list, or None if unusable."""
    if isinstance(cmd, list):
        argv = [str(x) for x in cmd]
        return argv or None
    if isinstance(cmd, str):
        try:
            # posix=False on Windows keeps backslash paths intact.
            argv = shlex.split(cmd, posix=(os.name != "nt"))
        except ValueError:
            return None
        return argv or None
    return None


def run_hook(entry, event, trigger, bundle, default_timeout, dry_run):
    """Run one hook entry. Return True on success (or dormant), False on failure."""
    if not isinstance(entry, dict) or not entry.get("run"):
        warn(f"skipping malformed hook entry: {entry!r}")
        return False
    if entry.get("enabled") is False:
        return True  # explicitly dormant — not a failure

    name = entry.get("name") or "(unnamed)"
    argv = resolve_argv(entry["run"])
    if argv is None:
        warn(f"hook '{name}': unusable command {entry['run']!r}")
        append_log(bundle, [event, name, "bad-command"])
        return False

    timeout = entry.get("timeout", default_timeout)
    display = argv if isinstance(entry["run"], list) else entry["run"]

    if dry_run:
        print(f"[dry-run] {event} -> {name}: {display}")
        return True

    env = dict(os.environ)
    env["ELEPHANT_BUNDLE"] = bundle
    env["ELEPHANT_EVENT"] = event
    env["ELEPHANT_TRIGGER"] = trigger or ""

    try:
        proc = subprocess.run(
            argv,
            env=env,
            cwd=bundle,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        warn(f"hook '{name}' timed out after {timeout}s — skipped")
        append_log(bundle, [event, name, f"timeout={timeout}s"])
        return False
    except OSError as exc:
        warn(f"hook '{name}' could not start: {exc}")
        append_log(bundle, [event, name, f"error={exc}"])
        return False

    if proc.returncode != 0:
        warn(f"hook '{name}' exited {proc.returncode} — skipped")
        for ln in (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]:
            warn(f"  {name}: {ln}")
        append_log(bundle, [event, name, f"exit={proc.returncode}"])
        return False

    append_log(bundle, [event, name, "ok"])
    return True


def main(argv):
    ap = argparse.ArgumentParser(
        prog="run-hooks.py",
        description="Fire elephant-mem lifecycle hooks (best-effort).",
    )
    ap.add_argument("event", help="event name, e.g. post_ingest")
    ap.add_argument("--trigger", default="", help="mode that fired the event (capture|ingest|catch-up)")
    ap.add_argument("--bundle", default="", help="bundle root (default: parent of this script's dir)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="default per-hook timeout (seconds)")
    ap.add_argument("--dry-run", action="store_true", help="show what would run; run nothing")
    args = ap.parse_args(argv)

    bundle = bundle_root(args.bundle)
    entries = [e for e in load_hooks(bundle, args.event) if not (isinstance(e, dict) and e.get("enabled") is False)]
    if not entries:
        return 0  # no subscribers — the common case, stays silent

    ran = ok = 0
    for entry in entries:
        ran += 1
        if run_hook(entry, args.event, args.trigger, bundle, args.timeout, args.dry_run):
            ok += 1

    failed = ran - ok
    if failed:
        warn(f"{args.event}: {ok}/{ran} hooks ok, {failed} failed (ingestion unaffected)")
    # Best-effort by contract: a hook failure is never an ingestion failure.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
