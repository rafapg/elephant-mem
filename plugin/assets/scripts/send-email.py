#!/usr/bin/env python3
"""Send an email via SMTP for the elephant `push-start-day` email transport.

Stdlib only (smtplib, ssl, email.message) — no extra dependencies to install
on a bare machine. Credentials live in the **pointer** file
(`~/.config/elephant-mem/config.json`, machine-local, never travels with the
bundle) under an `smtp` block:

  {
    "bundle_path": "/Users/jane/notes/my-memory",
    "smtp": {
      "host": "smtp.gmail.com",
      "port": 587,
      "username": "jane@example.com",
      "from": "jane@example.com",
      "password_env": "ELEPHANT_SMTP_PASSWORD"
    }
  }

Password resolution: `password_env` (read that environment variable) wins if
present; otherwise `password` (inline, plaintext — chmod 600 the pointer file);
otherwise a clear error. Port 465 connects over implicit TLS (SMTP_SSL); any
other port uses plain SMTP + STARTTLS with `ssl.create_default_context()`.

Usage:
  send-email.py --to <addr> --subject <s> (--body-file <path> | --body-stdin)
                [--config <pointer-path>] [--dry-run]

`--dry-run` validates the config, builds the message, and prints a summary
(host, port, from, to, subject, body length, password source) without
connecting — never prints the password itself. Exits 0 on success (or a
successful dry-run), non-zero with a clear message on any failure.
"""
import argparse
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

# Windows consoles default to a legacy codepage (cp1252); force UTF-8 on the
# standard streams so printing non-ASCII content (emoji, accented names)
# doesn't raise UnicodeEncodeError. No-op on POSIX / when already UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_CONFIG = "~/.config/elephant-mem/config.json"


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def load_pointer(path):
    p = Path(path).expanduser()
    if not p.exists():
        fail(f"pointer file not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"pointer file is not valid JSON ({p}): {e}")


def resolve_password(smtp_cfg):
    password_env = smtp_cfg.get("password_env")
    if password_env:
        val = os.environ.get(password_env)
        if val is None or val == "":
            fail(
                f"smtp.password_env names '{password_env}' but that environment "
                f"variable is not set. Export it (e.g. in your shell profile) and "
                f"retry."
            )
        return val, f"env:{password_env}"
    if "password" in smtp_cfg and smtp_cfg["password"]:
        return smtp_cfg["password"], "inline (plaintext in pointer file)"
    fail(
        "smtp block has neither 'password_env' nor 'password' — nothing to "
        "authenticate with. See docs/configuration.md."
    )


def load_smtp_config(pointer):
    smtp_cfg = pointer.get("smtp")
    if not smtp_cfg:
        fail(
            "no 'smtp' block in the pointer file. Add one under "
            "~/.config/elephant-mem/config.json — see docs/configuration.md."
        )
    missing = [k for k in ("host", "port", "username", "from") if k not in smtp_cfg]
    if missing:
        fail(f"smtp block is missing required field(s): {', '.join(missing)}")
    return smtp_cfg


def build_message(sender, to, subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body, charset="utf-8")
    return msg


def send(smtp_cfg, password, msg):
    host = smtp_cfg["host"]
    port = int(smtp_cfg["port"])
    username = smtp_cfg["username"]
    try:
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
                server.login(username, password)
                server.send_message(msg)
        else:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls(context=context)
                server.login(username, password)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        fail(f"SMTP authentication failed ({host}:{port}, user={username}): {e}")
    except (smtplib.SMTPException, OSError) as e:
        fail(f"failed to send via {host}:{port}: {e}")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True)
    parser.add_argument("--subject", required=True)
    body_group = parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body-file", help="path to a file with the message body")
    body_group.add_argument(
        "--body-stdin", action="store_true", help="read the message body from stdin"
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"pointer file path (default {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate + build the message but don't connect or send",
    )
    args = parser.parse_args(argv)

    if args.body_stdin:
        body = sys.stdin.read()
    else:
        body_path = Path(args.body_file)
        if not body_path.exists():
            fail(f"body file not found: {body_path}")
        body = body_path.read_text(encoding="utf-8")

    pointer = load_pointer(args.config)
    smtp_cfg = load_smtp_config(pointer)
    password, password_source = resolve_password(smtp_cfg)

    msg = build_message(smtp_cfg["from"], args.to, args.subject, body)

    if args.dry_run:
        print("dry-run: message built, not sent")
        print(f"  host:           {smtp_cfg['host']}")
        print(f"  port:           {smtp_cfg['port']}")
        print(f"  from:           {smtp_cfg['from']}")
        print(f"  to:             {args.to}")
        print(f"  subject:        {args.subject}")
        print(f"  body length:    {len(body)} chars")
        print(f"  password source: {password_source}")
        return 0

    send(smtp_cfg, password, msg)
    print(f"sent to {args.to} via {smtp_cfg['host']}:{smtp_cfg['port']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
