---
name: trunk
description: >
  Take a loose topic to dispatched work, the way the owner works. Studies the
  topic with the owner's elephant-mem memory and the repositories involved,
  presents a few approaches, converges with the owner in the conversation, and
  dispatches the work to Claude Code sessions when the owner says to. Every
  how (what to read, how deep, how approaches are shown, how work is
  dispatched) comes from the owner's own tagged facts, never from this file.
  Use when the owner names it (/elephant-trunk:trunk <topic>) or hands a topic
  over to be studied and taken to dispatched work ("trunk this", "study this
  and dispatch it", "take this to a PR"). Not for a plain recall question
  about a topic (that is elephant-mem:query) or for work the owner is already
  doing in this session.
---

# elephant-trunk:trunk

The owner hands over a topic in one line. The trunk studies it, comes back with
approaches, converges with the owner, and dispatches the work. Its four steps:
**study, converse, dispatch, follow**.

This file is a skeleton. It says what each step is and in what order; it never
says how this owner likes it done. That lives in elephant-mem, as facts carrying
the bundle's how-I-work tag plus one area tag:

| area tag         | what the facts say                                        |
| ---------------- | --------------------------------------------------------- |
| `trunk-study`    | sources to read, depth, how approaches are presented      |
| `trunk-dispatch` | how this owner dispatches agents (orq, plain Claude Code) |
| `trunk-recipe`   | reusable recipes: when each one fits and how it starts    |

When a fact and this file disagree, the fact wins.

Every bundle read and write goes through the plugin's own script,
`${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py`, run from the plugin and never
from the bundle. Each command below spells the full path: shell variables do
not survive from one Bash call to the next. `--help` on any command lists its
options. Speak to the owner in the
language they use in the conversation.

## 0. The topic and the bundle

1. **The topic.** Take it from the invocation, in the owner's words. With no
   topic, ask for it in one line and wait. A topic is not a spec: do not ask
   clarifying questions yet, the study is where they come from.
2. **The bundle and the tag.**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" config --json
   ```

   - **Exit 1** (the bundle is not found): stop. Relay the script's stderr as it
     is, it carries the same guidance elephant-wiki gives, and do nothing else.
   - **`tag_source` is `default`**: the stderr says the trunk reads
     `how-i-work` and how to set another tag in `elephant.json`. Relay that one
     line, once, and go on. When `problem` is set, relay it too: a value in
     `elephant.json` was present but not usable.

## 1. Study

### 1a. Load the owner's how

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" facts --json
```

It reads `knowledge/manifest.jsonl` only, never `query`: recalling the owner's
own way of working through `query` costs a whole retrieval for a handful of
short facts.

- **Exit 1** (the manifest cannot be read): relay the stderr, which names the
  `build-index.py` to run, and stop. An unbuilt index does not mean the owner
  has no how, so never continue as if it did.
- **`facts` is empty**: this is the first use. The trunk does not guess. Go to
  **First use** below and come back here once facts exist.
- **Otherwise**, open and read every listed fact file whole (`path` is
  absolute; they are few and short). Then tell the owner, one line per fact,
  which ones apply to this topic and to which step, citing each by its `link`.
  A fact that does not apply to this topic is named as set aside, in the same
  line count, so the owner sees what was read and what was used.

**Two facts that contradict each other.** When two facts give opposite
instructions for the same step (one says read the repo's open PRs first, the
other says never), do not pick one. Show both, with their `link` and
`occurred`, and ask the owner which holds. Then offer once to capture the
winner (see **Capturing a how** below), and use the winner for this run
either way.

**An area with no fact.** Facts exist, but none for the step at hand (no
`trunk-study` fact when the study starts): do not fall back on a habit of your
own. Ask the owner the one question that step needs (for the study: which
sources, how deep, how the approaches should come), use the answer for this
run, and offer to capture it.

### 1b. Open the run record

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run new --topic "<the topic, verbatim>" --json
```

It prints the run's `name`. Tell the owner the name in one line: it is how a
later session continues this run. The record lives in
`<bundle>/state/trunk/runs/<name>.json`, git-ignored by the script before every
write; it never enters the bundle's history. A write the script refuses (exit
1, "not git-ignored" or "already tracks") is relayed as it is, and the run goes
on without a record only if the owner says so.

### 1c. Study the topic

Follow the `trunk-study` facts: they say which sources, in what order, and how
deep. The two sources the trunk always has are:

- **elephant-mem**, through its own skills: `elephant-mem:query` for what the
  memory knows about the topic and the people, projects and decisions it
  touches; `elephant-mem:briefing` when the facts say recent activity matters.
  Never read the bundle's `knowledge/` directly for the study.
- **The repositories involved**: the ones the topic, the memory or the
  current working directory point to. Read what the facts say to read there
  (the code, its docs, open PRs, recent history).

Run the study in subagents (the Agent tool), one per source or per repository,
so the raw reading stays out of this conversation. Each one returns findings
with where they came from (a fact's `link`, a file and line, a PR number).

**Which repository** the work belongs to can be unclear from the topic. When
the study cannot settle it, ask the owner before going deeper, naming the
candidates and what points to each.

When the study is done, save it to the record:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> study --file - <<'EOF'
<the study: what was read, what was found, each finding with its provenance>
EOF
```

### 1d. Present the approaches

Present a few approaches in the form the `trunk-study` facts give (how many,
what each one carries, whether one comes recommended). Each approach is backed
by what the study found; an approach the study cannot support is not shown.
Then save them, replacing any earlier set:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> approaches --file - <<'EOF'
[{"title": "...", "summary": "...", "tradeoffs": "...", "recommended": false}]
EOF
```

`title` and `summary` are required; `tradeoffs` and `recommended` are there
when the presentation had them. One object per approach, in the order shown.

## 2. Converse

The owner questions, adjusts and picks. This is the part the owner is here
for: answer from the study, go back to a source when a question needs it, and
say plainly when something was not studied.

- **Record each decision as it is made**, one sentence each, not at the end:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> decision --value "<what was decided, and why>"
  ```

  An owner who leaves mid-conversation leaves a record with the study, the
  approaches and every decision so far, and a later session reopens the chat
  from it.
- **An approach that changes** in the conversation (merged, cut, reshaped) is
  saved again with `run set <name> approaches`, the whole set as it now stands.
- **The repository** the work lands in must be settled before the dispatch. If
  the conversation reaches the dispatch with it still open, ask.
- **The conversation ends only when the owner says to dispatch.** Agreement on
  an approach is not that; the trunk does not propose to dispatch on its own
  initiative more than once. When the owner says it, record it:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> decision --value "dispatch: <the approach as converged>"
  ```

  and go to step 3.

## 3. Dispatch

Not built yet in this version. Stop after recording the dispatch decision: tell
the owner the run `<name>` holds the study, the approaches and the decisions,
and that nothing was dispatched. Start nothing.

## 4. Follow

Not built yet in this version.

## First use

With no fact carrying the how-I-work tag plus a trunk area tag, the trunk does
not guess how this owner works. Say so, and offer the two ways to learn it,
each with what it costs:

- **Read past sessions**: an estimate first (sessions found, their size, the
  tokens it would take), then a small model reads the most recent ones and
  extracts how the owner works, never what was in the session. The owner
  confirms a panorama before anything is saved.
- **Interview only**: a few questions on how the owner studies a topic,
  dispatches work and splits it into sessions.

Either way, what the owner confirms is saved with **Capturing a how**, and the
run continues at 1a.

## Capturing a how

`elephant-mem:capture` takes no tag parameter: the tags are asked for in plain
words and nothing checks them. So every capture the trunk asks for names its
tags explicitly, the bundle's how-I-work tag (from `config`) and exactly one
area tag, and says the fact is how the owner works, not something about the
topic:

> Capture as a fact, tags `<tag>` and `trunk-study`: <the how, in one or two
> sentences, with the why>.

Then check it landed where the trunk will read it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" facts --area <the area tag> --json
```

A capture that does not show up there carries the wrong tags; say so to the
owner rather than assume it took.

## Rules

- **The how comes from facts.** Nothing in this file is a preference of this
  owner; a step with no fact asks instead of guessing.
- **Contextual integrity.** The study and the record may hold anything the
  memory and the repos hold. What later travels out of the record (a brief, a
  fact) is filtered by the content and the expectation of whoever shared it;
  sensitive content and things shared in confidence stay out.
- **Nothing starts without the owner's word.** The owner's "dispatch" is the
  only authorization to start sessions. The trunk never deploys and never
  merges.
