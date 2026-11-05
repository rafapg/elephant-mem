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

The owner said to dispatch, and the record holds it. This step turns the
conversation into work: the dispatch way, the brief, the recipe, then the
start. Nothing starts before 3e, and 3e runs only what 3d showed. Read the run
back first, so the brief is written from the record and not from memory of the
chat:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run show <name> --json
```

### 3a. The dispatch way

The `trunk-dispatch` facts read in 1a say how this owner dispatches: on
**orq** (several sessions in an orq workspace, coordinating over agent-bus,
started with the owner's own tooling) or on **plain Claude Code** (the work
runs in this session, right after the conversation, as a maestro with
subagents, no bus). They also say the form the brief takes for that way and
the command that starts it. Use the way they give; when two apply, the one
whose condition matches this work.

- **No `trunk-dispatch` fact**: ask the owner the one question this step
  needs (orq or this session, and for orq the command that starts the work),
  and use the answer for this run. It is captured as a learning in 4c.
- **orq is the way and orq is not available here**: the orq tooling is
  machine-specific, so check before writing anything for it. The command the
  facts name to start the work must resolve on this machine
  (`command -v <its first word>`), and so must any other tool they name for
  the dispatch. When one does not, say so in one line, naming what is missing,
  and offer plain Claude Code. Nothing is attempted on orq. If the owner takes
  plain Claude Code, record it:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> decision --value "dispatch via claude-code: orq not available (<what was missing>)"
  ```

  If they decline, the run stays open with nothing dispatched; stop here and
  say a later session can continue it.

### 3b. The brief

**The repository first.** The repository the work lands in must be settled
before a word of the brief is written. If the conversation left it open, ask
now, naming the candidates and what points to each.

**What every brief carries**, whatever its form: the repository (and the base
branch, when the study found one), the goal in the owner's terms, the approach
as converged (the `dispatch:` decision), the decisions that shape the work with
their why, what is out of scope, and when the work is done. Done is a pull
request opened for the owner to review: the dispatched work never merges and
never deploys.

**The form** is the one the `trunk-dispatch` facts give for the chosen way.
Some ways run alone only on a given form: `bus-spawn`, for one, goes straight
to `/bb:implement` only on an approved bb spec, and anything less makes it
interview the owner. Write the brief in that form. When the form is an
artifact (a spec file in the repository, a ticket), write it where the facts
say, from the same brief.

**Contextual integrity, before the owner sees it.** Go through the brief piece
by piece against where each piece came from. Memory content travels into it
only when the content and the expectation of whoever shared it allow it to
reach the sessions that will read the brief and the repository and pull
request where it lands. Sensitive content (personal data, health, pay, a
customer's own words) and anything shared in confidence is left out, or
generalized ("a customer reported the export times out" rather than who and
what they wrote). A secret never travels: when the work needs a credential,
the brief says where it lives (an environment variable, a secret manager, a
connection the owner manages), never its value. When something was left out or
generalized, tell the owner in one line what kind of content it was, without
repeating it.

**The form check.** The brief must have the form the dispatch needs to run
without interviewing the owner. Run the check the facts name for it (a lint, a
dry run, the dispatch tool's own rule); with none named, check the brief
yourself against the form they describe. When anything is missing, **nothing
is dispatched**: say what is missing, item by item, record it, and go back to
the conversation (step 2). The owner's next "dispatch" starts step 3 again.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> note --value "not dispatched: the brief lacks <what is missing>"
```

When the brief passes, save it (the filtered text, as the dispatch will read
it; an artifact's location goes in a note):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> brief --file - <<'EOF'
<the brief>
EOF
```

### 3c. The recipe

A recipe is how the work is split into sessions: the roles and the stop
conditions. Saved recipes are the `trunk-recipe` facts read in 1a, each saying
when it fits and how it is started. Pick the one whose "when it fits" matches
this work (its split, its roles, the kind of repository), and say in one line
which one and why, citing its `link`.

- On **orq**, the recipe's start command, filled in for this run, is the
  dispatch command.
- On **plain Claude Code**, the same roles and stop conditions are played by
  subagents of this session. With no recipe that fits, the split is this
  session's own, stated in one line per role with the dispatch in 3d.
- **No saved recipe fits the work on orq**: writing a new one is not built in
  this version. Say that none fits, name the closest one and what it lacks,
  and offer to dispatch with it as it is or on plain Claude Code. Write no
  recipe of your own.

Save the choice:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> recipe --value '{"name": "<recipe>", "fact": "<its link, or null>", "command": "<the start command, or null on claude-code>", "roles": "<one line per role>"}'
```

### 3d. Show it

Show the owner, in one message: the brief (or the artifact's location and a
summary of it), the recipe and the fact it came from, the exact command or
commands that will run, where the work will run, and what follows the start:
the confirmation, the record, an `ingest` of the record into the bundle (a
local commit of the facts it yields, never the raw record), and the learnings
of this run. The owner's "dispatch" is the authorization: show this, then go
straight to 3e. If what 3a to 3c produced changed the work the owner agreed to
(a different repository, a part left out), ask before starting instead.

### 3e. Start it

**On orq**, run the command or commands exactly as shown.

- **It ran** (exit 0): record the dispatch, with where it runs (the orq
  team, the workspace):

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run dispatch <name> --via orq --command "<the command, as run>" --where "<team or workspace>"
  ```

- **It failed**: record the attempt with its error (its first lines, with any
  token or secret it printed cut out), so the record says not dispatched:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run dispatch <name> --via orq --command "<the command, as run>" --error "<the error>"
  ```

  Tell the owner it was not dispatched, with the error. The run stays open; a
  retry, now or from a later session, is a new dispatch the owner asks for.
  Never retry on your own, and do not go on to step 4.

**On plain Claude Code**, there is no command to fail: record the dispatch as
the work starting in this session, then go to step 4, where the work runs.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run dispatch <name> --via claude-code --command "<one line: the plan this session runs>" --where "this session (<working directory>)"
```

A run the script says was already dispatched is never started again: show
what was dispatched and where (`run show <name>`), and continue the
conversation from there.

## 4. Follow

### 4a. Confirm the work

**On orq**, confirm the sessions are running with what the `trunk-dispatch`
facts name for it (a status or board command). With nothing named, the start
command's own output is the evidence: the team, workspace or sessions it
reports. Say in one line what is running and where. When the check shows
nothing running, say so and record it; the run stays dispatched and is never
started again by the trunk:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> note --value "started, not confirmed: <what the check showed>"
```

The trunk does not watch the sessions to the pull request: that is their job.
Go to 4b.

**On plain Claude Code**, this session is the maestro: run the work on the
brief, one subagent (the Agent tool) per role of the recipe, and update the
record as the work goes, one note per milestone (a role done, a check green,
the pull request opened, with its link):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> note --value "<the milestone>"
```

The trunk ends when the work ends: a pull request opened for the owner, or the
work stopped, with why in a note. It never merges and never deploys. Then 4b.

### 4b. Ingest the record

The raw record stays in `state/`; its useful parts become facts. Run
`elephant-mem:ingest` (the Skill tool) over the record file,
`<bundle>/state/trunk/runs/<name>.json`, once: right after 4a on orq, when the
work has ended on plain Claude Code. The owner saw it announced in 3d and
their "dispatch" covers it, which is ingest's scope confirmation. Pass these
terms with the source:

- **No raw capture.** Nothing is copied to `raw/`; the source record's summary
  is a recall aid (the topic, the approach chosen, where the work went), never
  a copy of the study or the conversation.
- **What becomes facts**: the decisions, with their why (tagged `decision`),
  and what was dispatched, how and where, so a later `query` on the topic
  finds it. Nothing that restates what the memory already held, and nothing
  about how the owner works: 4c captures that, with its tags.
- **Contextual integrity**, as for the brief: what was shared in confidence,
  sensitive content and secrets stay out of the facts.

`ingest` commits with `git add -A`; the script keeps `state/trunk/` ignored, so
the record cannot go in. Check that it did not, and record the ingest:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run ingested <name> --json
```

**Exit 1** means the raw record entered the bundle's history: relay the stderr
as it is, tell the owner, and do nothing else with the bundle. The bundle is
never pushed by the trunk. An ingest that failed is said so, and the run is
left with no ingest recorded, for a later session to run again.

### 4c. What the trunk learned

During the run the trunk may have learned something about how the owner works:
an answer to a question asked because an area had no fact, the winner between
two facts that contradicted each other, a correction to how a step was done (a
source to add, approaches shown another way, another dispatch way), a recipe
that fit or did not. Only that: never something about the topic, never content
of a session, a secret or third-party content.

Learning is autonomous. Capture each one without asking, with **Capturing a
how**, and check it with `facts --area`. Two exceptions: a how the owner
already captured in this run is not captured again, and one the owner declined
to capture in this run stays uncaptured. Record each learning that landed:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> learning --value "<its link>: <the how, in one line>"
```

A capture that did not land is recorded as a note, and reported as not
recorded.

### 4d. Report and stop

Close with one short message: the run's name, what is running and where (or
the pull request, on plain Claude Code), the ingest's commit, and the
learnings, one line each with its area and its `link`, saying the owner can
steer one or ask to forget it. With nothing learned, say so in one line. The
trunk stops here; a later session continues the run from its record.

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

During the conversation a capture is offered once. What the owner neither
captured nor declined by the end of the run is captured in 4c without asking,
and reported.

## Rules

- **The how comes from facts.** Nothing in this file is a preference of this
  owner; a step with no fact asks instead of guessing.
- **Contextual integrity.** The study and the record may hold anything the
  memory and the repos hold. What later travels out of the record (a brief, a
  fact) is filtered by the content and the expectation of whoever shared it;
  sensitive content and things shared in confidence stay out.
- **Nothing starts without the owner's word.** The owner's "dispatch" is the
  only authorization to start sessions. The trunk never deploys, never
  merges and never pushes the bundle.
