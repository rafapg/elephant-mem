# `ingest-audio`

Load `../_shared/core.md` first (always). This file is the `ingest-audio`
procedure. It resolves who-said-what and touches entities — also load
`../_shared/entity-resolution.md`.

**What this mode is:** a three-step pipeline — **audio → diarized transcript
→ ingest**. Acquire a recording (from a phone, a standalone recorder —
anything that produces an audio file), transcribe it locally with speaker
diarization, then hand the transcript to the normal ingest flow. The
deterministic parts (drain the landing dir, run WhisperX) are in
`scripts/ingest-audio.py`; the judgment parts (which recording, who is each
speaker, what's a durable fact) are here.

**Acquisition route is your choice — the pipeline doesn't care how the file
got here.** The steps below illustrate one option — a phone recording sent
via Tailscale's file-sharing feature, Taildrop — because it needs no cloud
account and works offline on a private network. It is not a requirement:
AirDrop into a watched folder, a synced drive, or a USB copy all work
identically from step 2 onward. Point `scripts/ingest-audio.py pull` at
wherever your files land — resolved in this order: the `ELEPHANT_TAILDROP_DIR`
environment variable (highest priority) → the `audio.inbox_dir` key in
`elephant.json` (see `docs/configuration.md`) → `~/Downloads` (default). The
env var name is a nod to the example acquisition route, not a hard dependency
on Tailscale.

**This mode is optional; nothing else in the plugin depends on it.** It also
has the heaviest install of anything here — plan for it before reaching for
this mode:
- WhisperX pulls in **PyTorch and ctranslate2**, a multi-gigabyte download on
  first install.
- Diarization needs a **Hugging Face token** and accepting the
  **pyannote license** (see Prereqs below) — it will not run without both.
- **CPU `int8` inference works on both x86 and ARM (including Apple
  Silicon)**, but it is **slow** — expect roughly 0.5–1× realtime, i.e. a
  30-minute recording takes 15–30+ minutes to transcribe.

**Prereqs** (fail fast with a clear message, in the bundle's
`conversation_language`, if missing):
- `whisperx` on PATH (`uv tool install whisperx`) and `ffmpeg` installed.
- A Hugging Face token exported as `HF_TOKEN` (or `HUGGINGFACE_TOKEN`) —
  needed for the gated pyannote diarization model. Create a read token at
  huggingface.co and accept the
  `pyannote/speaker-diarization-community-1` model license first. Keep the
  token wherever you keep other secrets (a sourced `.env`/`.secrets` file, your
  shell profile, a password manager's env-inject) — the only requirement is
  that it's an environment variable by the time the transcribe step runs.
- A way for the recording to reach this machine (see acquisition route,
  above) and, for the Taildrop example, Tailscale running on both ends.

## Procedure

1. **Pull.** Tell the user (in `conversation_language`) how to send the
   recording — e.g., for the Taildrop example: *Voice Memos → Share →
   Tailscale → `<this machine's device name>`*. Then drain the landing dir:
   ```bash
   python3 scripts/ingest-audio.py pull            # add --wait to block for an arrival
   ```
   This lists candidate audio (from the resolved landing dir — see the
   `ELEPHANT_TAILDROP_DIR` / `audio.inbox_dir` / `~/Downloads` precedence
   above — plus the CLI's own inbox). Note: some Taildrop clients (e.g. the
   macOS App Store Tailscale app) save straight to a folder like
   `~/Downloads` rather than into the CLI's queue — `pull` scans the landing
   dir for that reason, so it works whichever client saved the file.

2. **Pick.** Present the candidates (name, duration, size, when it arrived),
   newest first, in a batch. Let the user choose one (or several). If nothing
   recent shows up, the file probably went to a different destination or is
   still in transit — say so.

3. **Transcribe.** For each chosen file:
   ```bash
   python3 scripts/ingest-audio.py transcribe "<path>" --language <lang> [--speakers N]
   ```
   Set `--language` to the recording's actual spoken language (an ISO code
   WhisperX accepts, e.g. `en`, `pt`, `es`) — it does not need to match the
   bundle's `knowledge_language`; normalization into `knowledge_language`
   happens later, during fact extraction, same as any other source. Pass
   `--speakers N` when the user knows how many people were in the room — it
   sharpens diarization. This step is **slow** (large-v3 + pyannote on CPU;
   roughly 0.5–1× realtime) and the **first run downloads several GB of
   models**. Run it in the background and tell the user the estimate. Output
   lands in `state/phone/work/<stem>.{txt,srt,json,…}` — read the `.txt`
   (speaker-tagged) and keep the `.json` for word-level timing if needed.

4. **Resolve speakers → people.** The transcript labels turns `SPEAKER_00`,
   `SPEAKER_01`, … (anonymous voice clusters, **not** names). For each label,
   show the user its first 2–3 utterances and ask who it is. Map each to a
   real person, applying `entity-resolution.md` — e.g. a mangled nickname
   turning out to resolve to an existing person entity (say, a transcript
   rendering "Jon" when the speaker is actually **Jon Smyth**,
   `entities/person/jon-smith.md`). If a voice is ambiguous, or a cluster is
   clearly two people the model merged into one, flag it `low`/needs-review
   rather than guessing. Rewrite the transcript replacing `SPEAKER_xx` with
   the resolved names. Save the named transcript to
   `state/phone/transcripts/<YYYY-MM-DD>-<slug>.txt` (kept for
   re-extraction; git-ignored).

5. **Meeting metadata.** Ask (or infer) the meeting's real **date/time**
   (`occurred` = when it happened, NOT today), a short **title/slug**, and the
   **participant list** (the resolved names from step 4). The recording
   file's mtime is a hint for the date, not authoritative — confirm with the
   user.

6. **Ingest.** Hand the named transcript to the ingest flow — **follow
   `../ingest/procedure.md` from step 1**, with these bindings:
   - The **source** is the named transcript file. Create
     `knowledge/sources/<YYYY-MM>/<YYYY-MM-DD>-<slug>.md` from
     `templates/source.md` with:
     - `source-kind: meeting-transcript`
     - `channel: meeting`
     - `resource:` the transcript's provenance, e.g.
       `taildrop://<original-audio-filename>` (or the URI shape matching
       whichever acquisition route was actually used — the audio itself is
       deleted, see retention), plus a note that it was a recording
       transcribed locally by WhisperX (diarized).
     - `occurred:` the confirmed meeting date.
     - a concise summary written in `knowledge_language` — a pointer, not a
       copy.
   - Then run ingest steps 2–8: extract atomic facts / open-loops, resolve &
     dedup entities (**merge**, don't duplicate, against same-day chat
     echoes of the same meeting — this is a **primary** transcript and wins
     wording conflicts over secondary chat reports), assign confidence,
     persist, then `build-index.py` + `validate-okf.py` + append to
     `log.md` + local commit (`ingest: <slug> meeting transcript (+N facts,
     ~M updated)`).

7. **Retention.** After a successful ingest+commit: **delete the audio** (the
   inbox copy and the landing-dir original) and the WhisperX scratch in
   `state/phone/work/`. **Keep** the named text transcript in
   `state/phone/transcripts/` so facts can be re-extracted later without
   re-transcribing. Confirm the deletion in the recap.

8. **Recap** (in `conversation_language`). Close with a short recap: the
   meeting + headline, the speaker map you used (and anything flagged
   low-confidence), key facts/decisions and open-loops, notable
   dedup/correlation with existing knowledge, new entities, and that the
   audio was deleted / transcript kept.

**Multiple recordings:** process them one at a time through steps 3–7 (each
is its own source + commit), then give one combined recap.
