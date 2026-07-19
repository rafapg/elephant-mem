---
name: from-phone-tts
disable-model-invocation: true
description: >
  Bring an offline voice recording into elephant-mem. Pulls audio transferred
  from a recording device (e.g. a phone, over Tailscale/Taildrop or any other
  transfer mechanism), transcribes it locally with WhisperX (speaker-diarized),
  resolves who-said-what to entities, then ingests it as a meeting source. A
  deliberate operation with large side effects (transcribes, writes facts,
  rebuilds the index, commits). Invoke only when the user explicitly asks
  (elephant-mem:from-phone-tts).
---

# elephant-mem:from-phone-tts

Acquire + transcribe an offline recording and ingest it as a meeting source.

**Load `../_shared/core.md` first** (the shared contract). It touches
entities and does who-said-what resolution — also load
`../_shared/entity-resolution.md`.

Everything downstream of the transcript is the normal ingest flow — this mode
reuses [`../ingest/procedure.md`](../ingest/procedure.md) for fact extraction.

This is an **advanced, optional** mode: it requires WhisperX installed
locally and a Hugging Face token for diarization (see `procedure.md` for
prerequisites). Core modes never depend on it.

The full procedure is in [`procedure.md`](procedure.md) — open it and follow
it.
