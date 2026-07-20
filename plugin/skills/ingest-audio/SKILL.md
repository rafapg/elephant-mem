---
name: ingest-audio
disable-model-invocation: true
description: >
  Bring an audio recording into elephant-mem. Acquires a recording from
  wherever it lands (e.g. a phone recording sent over Tailscale/Taildrop —
  one example acquisition route, not the only one), transcribes it locally
  with WhisperX (speaker-diarized), resolves who-said-what to entities, then
  ingests it as a meeting source. A deliberate operation with large side
  effects (transcribes, writes facts, rebuilds the index, commits). Invoke
  only when the user explicitly asks (elephant-mem:ingest-audio).
---

# elephant-mem:ingest-audio

Acquire + transcribe an audio recording and ingest it as a meeting source.

**Load `../_shared/core.md` first** (the shared contract). It touches
entities and does who-said-what resolution — also load
`../_shared/entity-resolution.md`.

The core of this mode is a three-step pipeline — **audio → diarized
transcript → ingest** — regardless of how the recording reached this
machine. A phone recording transferred via Taildrop is the example workflow
below because it needs no cloud account, but any transfer mechanism that
lands a file on disk works identically. Everything downstream of the
transcript is the normal ingest flow — this mode reuses
[`../ingest/procedure.md`](../ingest/procedure.md) for fact extraction.

This is an **advanced, optional** mode: it requires WhisperX installed
locally and a Hugging Face token for diarization (see `procedure.md` for
prerequisites). Core modes never depend on it.

The full procedure is in [`procedure.md`](procedure.md) — open it and follow
it.
