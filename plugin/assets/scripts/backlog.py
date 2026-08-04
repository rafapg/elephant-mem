#!/usr/bin/env python3
"""Deferred-work ledger for the elephant `catch-up` routine.

`catch-up` runs unattended under a written **autonomy envelope** (see the
`catch-up` skill's `procedure.md`). Findings it is *not* authorized to fix on
its own — the envelope's yellow zone — land here instead of being re-narrated
in `knowledge/log.md` every run.

The point is that a deferred item is filed **once**. A run that re-observes a
known item bumps its counter; it does not write another paragraph. Without this
the routine re-reported the same seven findings hourly for nine consecutive
runs — the ledger grew, nothing moved, and one item stayed on the list months
after it had actually been fixed.

Canonical machine state is `state/backlog.json`. `state/backlog.md` is a
human-readable rendering, regenerated on every mutation (like `watermarks.md`
and the OKF derived files — do NOT hand-edit it). `state/` is NOT part of the
OKF bundle (not under `knowledge/`), so `validate-okf.py` never touches it.

Both files are created on first use, so a bundle that predates this script (or
a freshly `init`-ed one) needs no seeding step.

The `seen` counter is load-bearing, not decoration: the envelope lets the
routine self-tune a closed list of `elephant.json` fields only once the
matching backlog item reports `seen >= 3` (the same finding measured on three
consecutive runs).

Subcommands:
  add <id> --summary <text> [--unblocks <text>] [--evidence <text>] [--zone <z>]
                            file a new item, or bump it if already open.
                            Idempotent by design: the routine calls `add`
                            unconditionally for every yellow finding and lets
                            the script decide new-vs-bump. Prints `new` or
                            `bumped`. Re-filing a *closed* id reopens it.
  bump <id> [--evidence <text>]
                            re-observe a known open item (seen +1, last_seen
                            restamped). Errors on an unknown id — use `add`
                            when you can't be sure the item exists.
  close <id> [--note <text>]
                            mark an item done/decided. Closed items stay in
                            the ledger as history.
  reopen <id> [--evidence <text>]
                            move a closed item back to open (counter kept).
  list [--status open|closed|all] [--json]
                            print the ledger. Default `open`.
  count [--status open|closed|all]
                            print a single number — for the one-line log entry.
  get <id>                  print one item as JSON; exit 1 if unknown.
  show                      dump the whole canonical JSON.
  render                    rewrite backlog.md from backlog.json.

Every mutating subcommand accepts `--at <iso>` to override "now" (tests, and
replaying a run). Timestamps are generated in Python, never shelled out to
`date` — BSD `date` on macOS has no `%:z` and silently emits a literal `:z`,
which is not parseable ISO 8601.
"""
import argparse
import json
import re
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

STATE = Path(__file__).resolve().parent.parent / "state"
BACKLOG = STATE / "backlog.json"
BACKLOG_MD = STATE / "backlog.md"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
ZONES = ("yellow", "red")
EVIDENCE_KEPT = 5

COMMENT = (
    "Deferred findings from the catch-up routine's yellow zone. Canonical state "
    "— backlog.md is a rendering of this file. Managed by scripts/backlog.py; "
    "do not hand-edit."
)


def now_iso(at=None):
    """Local time with a real UTC offset, as ISO 8601."""
    if at:
        return datetime.fromisoformat(at).isoformat()
    return datetime.now().astimezone().isoformat()


def as_date(iso):
    """The date half of an ISO timestamp, for compact rendering."""
    return (iso or "")[:10] or "—"


def load():
    if not BACKLOG.exists():
        return {"comment": COMMENT, "items": []}
    data = json.loads(BACKLOG.read_text(encoding="utf-8"))
    data.setdefault("comment", COMMENT)
    data.setdefault("items", [])
    return data


def save(data):
    STATE.mkdir(parents=True, exist_ok=True)
    BACKLOG.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def find(data, item_id):
    for item in data["items"]:
        if item["id"] == item_id:
            return item
    return None


def require(data, item_id):
    item = find(data, item_id)
    if item is None:
        print(
            f"error: no backlog item '{item_id}' — `list --status all` to see the "
            "ids, or `add` to file it",
            file=sys.stderr,
        )
        sys.exit(1)
    return item


def validate_id(item_id):
    if not ID_RE.match(item_id):
        print(
            f"error: '{item_id}' is not a valid id — use a kebab-case slug, 3-64 "
            "chars, e.g. 'slack-sweep-under-returns'",
            file=sys.stderr,
        )
        sys.exit(2)


def add_evidence(item, evidence):
    """Append one evidence line, keeping only the most recent few.

    An item re-observed for months would otherwise accumulate an unbounded list
    of near-identical notes; the recent ones are the ones that matter.
    """
    if not evidence:
        return
    kept = [e for e in item.get("evidence", []) if e != evidence]
    kept.append(evidence)
    item["evidence"] = kept[-EVIDENCE_KEPT:]


def render(data):
    items = data["items"]
    open_items = [i for i in items if i["status"] == "open"]
    closed_items = [i for i in items if i["status"] != "open"]
    # Most-repeated first: the item nagging every run is the one to fix next.
    open_items.sort(key=lambda i: (-i.get("seen", 0), i.get("first_seen") or ""))
    closed_items.sort(key=lambda i: i.get("closed") or "", reverse=True)

    out = [
        "# Backlog",
        "",
        "Findings the `catch-up` routine surfaced but is **not authorized to fix on",
        "its own** — the yellow zone of its autonomy envelope (see the `catch-up`",
        "skill's `procedure.md`). Each item is filed once; a later run that sees it",
        "again bumps `seen` instead of re-narrating it in `log.md`.",
        "",
        "**Regenerated by `scripts/backlog.py` — do not hand-edit** (canonical state",
        "is `backlog.json`). Not part of the OKF bundle (not under `knowledge/`).",
        "",
        f"## Open ({len(open_items)})",
        "",
    ]
    if not open_items:
        out += ["_Nothing deferred._", ""]
    for item in open_items:
        out += [
            f"### `{item['id']}` — {item['summary']}",
            "",
            f"- **Unblocks:** {item.get('unblocks') or '—'}",
            f"- **Seen:** {item.get('seen', 1)}× · first {as_date(item.get('first_seen'))}"
            f" · last {as_date(item.get('last_seen'))}",
        ]
        for line in item.get("evidence", []):
            out.append(f"- **Evidence:** {line}")
        out += [
            "- Close with: "
            f"`python3 scripts/backlog.py close {item['id']} --note \"<what changed>\"`",
            "",
        ]

    out += [f"## Closed ({len(closed_items)})", ""]
    if not closed_items:
        out += ["_Nothing closed yet._", ""]
    else:
        out += [
            "| id | summary | closed | note |",
            "|---|---|---|---|",
        ]
        for item in closed_items:
            note = (item.get("closed_note") or "—").replace("|", "\\|")
            summary = item["summary"].replace("|", "\\|")
            out.append(
                f"| `{item['id']}` | {summary} | {as_date(item.get('closed'))} | {note} |"
            )
        out.append("")

    STATE.mkdir(parents=True, exist_ok=True)
    BACKLOG_MD.write_text("\n".join(out), encoding="utf-8")


def cmd_add(args):
    validate_id(args.id)
    data = load()
    stamp = now_iso(args.at)
    item = find(data, args.id)
    if item is None:
        item = {
            "id": args.id,
            "summary": args.summary,
            "unblocks": args.unblocks or "",
            "zone": args.zone,
            "status": "open",
            "seen": 1,
            "first_seen": stamp,
            "last_seen": stamp,
            "evidence": [],
            "closed": None,
            "closed_note": "",
        }
        add_evidence(item, args.evidence)
        data["items"].append(item)
        outcome = "new"
    else:
        was_closed = item["status"] != "open"
        item["status"] = "open"
        item["closed"] = None
        item["seen"] = item.get("seen", 0) + 1
        item["last_seen"] = stamp
        # A re-file may carry a sharper summary than the original sighting.
        if args.summary:
            item["summary"] = args.summary
        if args.unblocks:
            item["unblocks"] = args.unblocks
        add_evidence(item, args.evidence)
        outcome = "reopened" if was_closed else "bumped"
    save(data)
    render(data)
    print(f"{outcome} {args.id} (seen={item['seen']})")
    return 0


def cmd_bump(args):
    data = load()
    item = require(data, args.id)
    if item["status"] != "open":
        print(
            f"error: '{args.id}' is closed — use `add` or `reopen` to bring it back",
            file=sys.stderr,
        )
        return 1
    item["seen"] = item.get("seen", 0) + 1
    item["last_seen"] = now_iso(args.at)
    add_evidence(item, args.evidence)
    save(data)
    render(data)
    print(f"bumped {args.id} (seen={item['seen']})")
    return 0


def cmd_close(args):
    data = load()
    item = require(data, args.id)
    item["status"] = "closed"
    item["closed"] = now_iso(args.at)
    item["closed_note"] = args.note or ""
    save(data)
    render(data)
    print(f"closed {args.id}")
    return 0


def cmd_reopen(args):
    data = load()
    item = require(data, args.id)
    item["status"] = "open"
    item["closed"] = None
    item["closed_note"] = ""
    item["last_seen"] = now_iso(args.at)
    add_evidence(item, args.evidence)
    save(data)
    render(data)
    print(f"reopened {args.id} (seen={item.get('seen', 1)})")
    return 0


def select(data, status):
    if status == "all":
        return list(data["items"])
    return [i for i in data["items"] if i["status"] == status]


def cmd_list(args):
    data = load()
    items = select(data, args.status)
    items.sort(key=lambda i: (-i.get("seen", 0), i.get("first_seen") or ""))
    if args.json:
        print(json.dumps(items, indent=2, ensure_ascii=False))
        return 0
    if not items:
        print(f"no {args.status} backlog items")
        return 0
    for item in items:
        flag = "" if item["status"] == "open" else " [closed]"
        print(f"{item['seen']:>3}×  {item['id']}{flag} — {item['summary']}")
        if item.get("unblocks"):
            print(f"      unblocks: {item['unblocks']}")
    return 0


def cmd_count(args):
    print(len(select(load(), args.status)))
    return 0


def cmd_get(args):
    item = find(load(), args.id)
    if item is None:
        print(f"error: no backlog item '{args.id}'", file=sys.stderr)
        return 1
    print(json.dumps(item, indent=2, ensure_ascii=False))
    return 0


def cmd_show(args):
    print(json.dumps(load(), indent=2, ensure_ascii=False))
    return 0


def cmd_render(args):
    data = load()
    save(data)  # materialize backlog.json on a first-ever run
    render(data)
    print("backlog.md regenerated")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="backlog.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    def with_at(sp):
        sp.add_argument("--at", help="override 'now' with an ISO timestamp")
        return sp

    sp = with_at(sub.add_parser("add", help="file a new item, or bump it if known"))
    sp.add_argument("id")
    sp.add_argument("--summary", required=True, help="one line, what the finding is")
    sp.add_argument("--unblocks", help="what a human must decide or do")
    sp.add_argument("--evidence", help="one line of measurement from this run")
    sp.add_argument("--zone", default="yellow", choices=ZONES)
    sp.set_defaults(func=cmd_add)

    sp = with_at(sub.add_parser("bump", help="re-observe a known open item"))
    sp.add_argument("id")
    sp.add_argument("--evidence")
    sp.set_defaults(func=cmd_bump)

    sp = with_at(sub.add_parser("close", help="mark an item done or decided"))
    sp.add_argument("id")
    sp.add_argument("--note", help="what changed")
    sp.set_defaults(func=cmd_close)

    sp = with_at(sub.add_parser("reopen", help="move a closed item back to open"))
    sp.add_argument("id")
    sp.add_argument("--evidence")
    sp.set_defaults(func=cmd_reopen)

    sp = sub.add_parser("list", help="print the ledger")
    sp.add_argument("--status", default="open", choices=("open", "closed", "all"))
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("count", help="print a single number")
    sp.add_argument("--status", default="open", choices=("open", "closed", "all"))
    sp.set_defaults(func=cmd_count)

    sp = sub.add_parser("get", help="print one item as JSON")
    sp.add_argument("id")
    sp.set_defaults(func=cmd_get)

    sub.add_parser("show", help="dump the canonical JSON").set_defaults(func=cmd_show)
    sub.add_parser("render", help="rewrite backlog.md").set_defaults(func=cmd_render)
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
