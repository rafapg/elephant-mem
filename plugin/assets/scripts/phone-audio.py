#!/usr/bin/env python3
"""phone-audio.py — acquire + transcribe voice recordings for elephant-mem.

Deterministic half of the `elephant-mem:from-phone-tts` mode. Two jobs:

  pull        Drain the Tailscale (Taildrop) inbox into a local staging dir and
              report the audio files that arrived (name, duration, size, mtime).
  transcribe  Run WhisperX locally (large-v3, speaker-diarized, CPU/int8,
              language auto-detected unless --language is given) on one staged
              file and report where the transcript landed.

The interactive parts — picking a file, mapping SPEAKER_xx -> real people,
turning the transcript into facts — live in the SKILL, not here.

All paths resolve under the bundle. Audio + transcripts stay in state/phone/
which is git-ignored (large + sensitive). Never commits anything.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent.parent
INBOX = BUNDLE / "state" / "phone" / "inbox"          # pulled audio (raw m4a)
WORK = BUNDLE / "state" / "phone" / "work"            # whisperx output dir
TRANSCRIPTS = BUNDLE / "state" / "phone" / "transcripts"  # kept transcripts

# Where the Tailscale macOS (App Store) app drops received Taildrop files.
# The GUI variant auto-saves to ~/Downloads instead of the CLI inbox, so we scan
# it directly. Override with ELEPHANT_TAILDROP_DIR (e.g. if you point the app's
# Taildrop directory at a dedicated folder).
LANDING = Path(os.environ.get("ELEPHANT_TAILDROP_DIR", str(Path.home() / "Downloads")))

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".caf", ".flac", ".ogg", ".mp4", ".m4v"}


def err(msg):
    print(msg, file=sys.stderr)


def find_binary(name, extra_paths=()):
    """Locate a CLI, checking PATH then a few well-known spots."""
    found = shutil.which(name)
    if found:
        return found
    for p in extra_paths:
        if Path(p).exists():
            return p
    return None


def tailscale_bin():
    return find_binary(
        "tailscale",
        extra_paths=[
            "/usr/local/bin/tailscale",
            "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
        ],
    )


def whisperx_bin():
    return find_binary(
        "whisperx",
        extra_paths=[str(Path.home() / ".local" / "bin" / "whisperx")],
    )


def ffprobe_duration(path):
    """Return duration in seconds (float) or None if ffprobe is unavailable."""
    ffprobe = find_binary("ffprobe", extra_paths=["/opt/homebrew/bin/ffprobe"])
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout or "{}")
        dur = data.get("format", {}).get("duration")
        return round(float(dur), 1) if dur is not None else None
    except Exception:
        return None


def describe_audio(path):
    st = path.stat()
    dur = ffprobe_duration(path)
    return {
        "path": str(path),
        "name": path.name,
        "size_mb": round(st.st_size / (1024 * 1024), 2),
        "duration_s": dur,
        "duration_hms": (
            f"{int(dur // 3600):02d}:{int((dur % 3600) // 60):02d}:{int(dur % 60):02d}"
            if dur is not None else None
        ),
        "mtime": st.st_mtime,
    }


def scan_dir(directory, since_min=None):
    """Audio files in a dir, newest first; if since_min set, only recent ones."""
    if not directory.exists():
        return []
    import time
    cutoff = (time.time() - since_min * 60) if since_min else None
    files = [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
        and (cutoff is None or p.stat().st_mtime >= cutoff)
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def collect_candidates(since_min):
    """Merge audio from the CLI inbox (all) + the Taildrop landing dir (recent).

    Dedup by name (inbox wins). Landing-dir files are reported in place — the
    transcribe step reads any absolute path, so we don't move them.
    """
    seen, out = set(), []
    for p in scan_dir(INBOX):
        seen.add(p.name)
        d = describe_audio(p); d["origin"] = "inbox"; out.append(d)
    for p in scan_dir(LANDING, since_min=since_min):
        if p.name in seen:
            continue
        d = describe_audio(p); d["origin"] = "taildrop"; out.append(d)
    out.sort(key=lambda d: d["mtime"], reverse=True)
    return out


def cmd_pull(args):
    # Best-effort: drain the CLI inbox too (open-source Tailscale path). The
    # App Store GUI saves to LANDING instead, which collect_candidates() scans.
    ts = tailscale_bin()
    if ts:
        INBOX.mkdir(parents=True, exist_ok=True)
        cmd = [ts, "file", "get", "--conflict=rename"]
        if args.wait:
            cmd.append("--wait")
        cmd.append(str(INBOX))
        err(f"$ {' '.join(cmd)}")
        subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr)
    print(json.dumps({
        "inbox": str(INBOX),
        "landing": str(LANDING),
        "since_min": args.since_min,
        "audio": collect_candidates(args.since_min),
    }, indent=2))
    return 0


def cmd_list(args):
    print(json.dumps({
        "inbox": str(INBOX),
        "landing": str(LANDING),
        "since_min": args.since_min,
        "audio": collect_candidates(args.since_min),
    }, indent=2))
    return 0


def cmd_transcribe(args):
    audio = Path(args.audio)
    if not audio.is_absolute():
        # allow passing just a filename that lives in the inbox
        cand = INBOX / audio
        audio = cand if cand.exists() else audio
    if not audio.exists():
        err(f"audio file not found: {audio}")
        return 2

    wx = whisperx_bin()
    if not wx:
        err("whisperx not found. Install with: uv tool install whisperx")
        return 2

    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if args.diarize and not hf_token:
        err("HF_TOKEN not set — diarization needs it. Export your HuggingFace read "
            "token (and accept the pyannote/speaker-diarization-community-1 license).")
        return 2

    WORK.mkdir(parents=True, exist_ok=True)
    cmd = [
        wx, str(audio),
        "--model", args.model,
        "--compute_type", args.compute_type,
        "--device", args.device,
        "--output_format", "all",
        "--output_dir", str(WORK),
    ]
    if args.language:
        cmd += ["--language", args.language]
    if args.diarize:
        # NB: token goes via env (HF_TOKEN), never as --hf_token — a CLI arg is
        # visible in `ps` and any command echo. huggingface_hub reads it from env.
        cmd += ["--diarize"]
        if args.speakers:
            cmd += ["--min_speakers", str(args.speakers), "--max_speakers", str(args.speakers)]
        else:
            if args.min_speakers:
                cmd += ["--min_speakers", str(args.min_speakers)]
            if args.max_speakers:
                cmd += ["--max_speakers", str(args.max_speakers)]

    err(f"$ {' '.join(cmd)}")
    err("(first run downloads large-v3 + pyannote models — needs internet once)")
    # Pass the token via env only (both names huggingface_hub honors), never CLI.
    env = dict(os.environ)
    if args.diarize and hf_token:
        env["HF_TOKEN"] = hf_token
        env["HUGGING_FACE_HUB_TOKEN"] = hf_token
    # WhisperX chatter -> stderr so stdout stays a clean JSON result line.
    proc = subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr, env=env)
    if proc.returncode != 0:
        err(f"whisperx failed (exit {proc.returncode})")
        return proc.returncode

    stem = audio.stem
    outputs = {}
    for ext in ("txt", "srt", "vtt", "json", "tsv", "aud"):
        p = WORK / f"{stem}.{ext}"
        if p.exists():
            outputs[ext] = str(p)
    print(json.dumps({
        "audio": str(audio),
        "work_dir": str(WORK),
        "transcripts_dir": str(TRANSCRIPTS),
        "outputs": outputs,
    }, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_pull = sub.add_parser("pull", help="drain the Taildrop inbox and list arrived audio")
    p_pull.add_argument("--wait", action="store_true", help="block until at least one file arrives")
    p_pull.add_argument("--since-min", type=int, default=240,
                        help="only list landing-dir audio modified within N minutes (default 240)")
    p_pull.set_defaults(func=cmd_pull)

    p_list = sub.add_parser("list", help="list candidate audio (inbox + Taildrop landing dir)")
    p_list.add_argument("--since-min", type=int, default=240,
                        help="only list landing-dir audio modified within N minutes (default 240)")
    p_list.set_defaults(func=cmd_list)

    p_tr = sub.add_parser("transcribe", help="run WhisperX on one staged audio file")
    p_tr.add_argument("audio", help="path (or inbox filename) of the audio to transcribe")
    p_tr.add_argument("--model", default="large-v3")
    p_tr.add_argument("--language", default=None,
                      help="spoken language of the recording (e.g. en, pt); omit to auto-detect")
    p_tr.add_argument("--device", default="cpu", help="cpu (pyannote breaks on mps)")
    p_tr.add_argument("--compute_type", default="int8", choices=["default", "float16", "float32", "int8"])
    p_tr.add_argument("--diarize", action="store_true", default=True)
    p_tr.add_argument("--no-diarize", dest="diarize", action="store_false")
    p_tr.add_argument("--speakers", type=int, help="exact speaker count (sets min=max)")
    p_tr.add_argument("--min_speakers", type=int)
    p_tr.add_argument("--max_speakers", type=int)
    p_tr.set_defaults(func=cmd_transcribe)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
