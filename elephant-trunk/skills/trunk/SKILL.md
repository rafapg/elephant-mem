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
  and dispatch it", "take this to a PR"), and to continue a run an earlier
  session left ("continue the trunk run <name>", "resume the trunk", "where
  did the trunk stop"), and to steer or forget what the trunk learned about
  how the owner works ("forget that learning", "that's not how I dispatch").
  Not for a plain recall question about a topic (that is
  elephant-mem:query) or for work the owner is already doing in this session.
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
options. Free text on a command line (a topic, a decision, a command, an error,
a JSON value) goes inside single quotes, as the templates show, so a backtick,
a `$(`, a `$` or a `"` in it is passed as written and never run; write each
apostrophe in the text as `'\''`. An option with no file input (`--roles`,
`--error`) takes its several lines inside those single quotes, which hold a
line break as written; never route that text into another option's `--file`.
Elsewhere, text over several lines goes through
`--file -` and a quoted heredoc instead (see 1c), whose delimiter,
`TRUNK_END_OF_TEXT`, must be no line of the text: a line that is exactly the
delimiter ends the heredoc there and the lines after it run as shell. Should
the text hold that line, pick another delimiter for that call. Speak to the owner in the
language they use in the conversation.

## 0. The topic and the bundle

1. **The topic, or a run to continue.** Take it from the invocation, in the
   owner's words. When the owner asks to continue a run instead (they say
   continue or resume, or name a run, or the invocation is exactly the name of
   one), find the bundle in item 2 and go to **Continue a run** below; no new
   run is opened. When the owner asks to steer or forget a learning (they say
   forget, or correct how the trunk said they work, or the invocation is
   `forget <link>`), find the bundle and go to **Steer or forget a learning**;
   no run is opened for it. With no topic and no run, ask for the topic in one line and
   wait. A topic is not a spec: do not ask clarifying questions yet, the study
   is where they come from.
2. **The bundle and the tag.**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" config --json
   ```

   - **Exit 1** (the bundle is not found): stop. Relay the script's stderr as it
     is, it carries the same guidance elephant-wiki gives, and do nothing else.
   - **`problem` is set**: `elephant.json` is there but its tag cannot be
     used (it does not parse, it is not an object, or `trunk.tag` is not a
     non-empty string). Relay the problem as it is and stop before step 1:
     the owner's facts carry the tag the broken file meant, so reading
     `how-i-work` instead would find none of them, start a first use and
     capture its answers under a tag that goes unread once the file is fixed.
     `facts` refuses in this case too. Go on only once the owner has fixed
     `elephant.json` and `config --json` shows no `problem`.
   - **`tag_source` is `default`** (and no `problem`): the stderr says the
     trunk reads `how-i-work` and how to set another tag in `elephant.json`.
     Relay that one line, once, and go on.

## 1. Study

### 1a. Load the owner's how

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" facts --json
```

It reads `knowledge/manifest.jsonl` only, never `query`: recalling the owner's
own way of working through `query` costs a whole retrieval for a handful of
short facts.

- **Exit 1** (the manifest cannot be read, or `elephant.json` has a
  `problem`, which the JSON then names): relay the stderr, which names the
  `build-index.py` to run or the problem to fix, and stop. An unbuilt index or
  an unusable tag does not mean the owner has no how, so never continue as if
  it did, and never go to **First use** from here.
- **`near_misses` is not empty**: these facts nearly carry the tag (another
  case, as `Como-Trabalhar`, or one comma-joined tag string, as
  `tags: como-trabalhar, trunk-study` written without brackets) and the trunk
  does not read them: matching is exact. Before anything else, and before
  **First use** above all, say "N facts nearly carry the tag `<tag>`", one
  line per fact with its `link` and its `tags` as written, and ask the owner
  whether to fix their tags (by hand in each file, then the bundle's
  `build-index.py`, then `facts --json` again) or to go on without them.
  Never fix them on your own, and never start a first use while the owner
  has not answered: those facts may be the owner's how, read once a tag is
  fixed.
- **`facts` is empty** (and the owner, asked about any near misses, chose to
  go on without them): this is the first use. The trunk does not guess. Go to
  **First use** below and come back here once facts exist. First use is
  offered once per session: when it ended with nothing captured (the owner
  answered nothing, or stopped it), go on with no facts, and every step asks
  its one question as **An area with no fact** says.
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

**An area with no fact.** No fact for the step at hand (no `trunk-study` fact
when the study starts, or none at all after a first use that captured
nothing): do not fall back on a habit of your
own. Ask the owner the one question that step needs (for the study: which
sources, how deep, how the approaches should come), use the answer for this
run, and offer to capture it.

### 1b. Open the run record

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run new --topic '<the topic, verbatim>' --json
```

It prints the run's `name`. Tell the owner the name in one line: it is how a
later session continues this run. The record lives in
`<bundle>/state/trunk/runs/<name>.json`, git-ignored by the script before every
write; it never enters the bundle's history. A write the script refuses (exit
1, "not git-ignored" or "already tracks") is relayed as it is, and the run goes
on without a record only if the owner says so.

When **First use** captured facts in this session, record each one in the new
run now, as **The interview** says at its end, so 4c does not capture it again
and 4d reports it with the run's learnings.

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
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> study --file - <<'TRUNK_END_OF_TEXT'
<the study: what was read, what was found, each finding with its provenance>
TRUNK_END_OF_TEXT
```

### 1d. Present the approaches

Present a few approaches in the form the `trunk-study` facts give (how many,
what each one carries, whether one comes recommended). Each approach is backed
by what the study found; an approach the study cannot support is not shown.
Then save them, replacing any earlier set:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> approaches --file - <<'TRUNK_END_OF_TEXT'
[{"title": "...", "summary": "...", "tradeoffs": "...", "recommended": false}]
TRUNK_END_OF_TEXT
```

`title` and `summary` are required; `tradeoffs` and `recommended` are there
when the presentation had them. One object per approach, in the order shown.

## 2. Converse

The owner questions, adjusts and picks. This is the part the owner is here
for: answer from the study, go back to a source when a question needs it, and
say plainly when something was not studied.

- **Record each decision as it is made**, one sentence each, not at the end:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> decision --value '<what was decided, and why>'
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
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> decision --value 'dispatch: <the approach as converged>'
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
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> decision --value 'dispatch via claude-code: orq not available (<what was missing>)'
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
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> note --value 'not dispatched: the brief lacks <what is missing>'
```

When the brief passes, save it (the filtered text, as the dispatch will read
it; an artifact's location goes in a note):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> brief --file - <<'TRUNK_END_OF_TEXT'
<the brief>
TRUNK_END_OF_TEXT
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
- **No saved recipe fits the work on orq**: write a new one, with **Writing a
  recipe** below. Say so in one line, naming the closest saved recipe and
  what it lacks for this work.

Save the choice of a saved recipe (a written one is recorded as it is
written):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> recipe --value '{"name": "<recipe>", "fact": "<its link, or null>", "command": "<the start command, or null on claude-code>", "roles": "<one line per role>"}'
```

#### Writing a recipe

Only on orq, and only when no saved recipe fits. The recipe is written in the
form the orq tooling runs (for orq, a Python file with a `run(t)` the tooling
loads): read two things before writing a line, the closest saved recipe (its
file, from its `trunk-recipe` fact, when there is one) and the tooling's own
documentation of recipes (its `--help`, its README). Never write a recipe from memory.

1. **Where it will live.** The directory the tooling reads recipes from by
   name: from the `trunk-recipe` facts (where the saved ones are), else from
   the tooling's own help, which names it. When neither says, ask the owner.
2. **What it carries.** The roles and the stop conditions of this kind of
   work, and nothing of this topic: the work itself reaches the sessions
   through the brief at the start (`--brief` on orq), so the recipe can be
   reused by the next run that fits. No repository path, no person's or
   customer's name, no content from memory, no secret, no credential: a
   value the sessions need comes in at start (a `--set`), or from where it
   lives (an environment variable, a connection the owner manages). Every role ends in a pull request opened for
   the owner or a stop that says why; none merges, none deploys.
3. **Its name** is new: lowercase letters, digits and `_`, saying the split
   (`split_by_area`), not the topic. A name already in the recipe directory
   is never reused, even for a better version: a team started from a saved
   recipe reloads it from that file when it resumes (`orq resume` aborts with
   "resume diverged" when a replayed step differs), so a saved recipe is never
   edited. A changed recipe is a new name and a new fact.
4. **Its check**, written with it: the check the `trunk-recipe` or
   `trunk-dispatch` facts name for a recipe, else the tooling's own way to
   test a recipe without starting sessions (orq's README names a test harness
   that runs a recipe over a fake terminal with scripted replies). The check
   drives the recipe through every role to its end, with one scripted reply
   per request (and, where a role can send the work back, a reply that does),
   so a role that is never reached fails it.

Keep the draft, its check and the start command in the record. The draft lives
beside the record, under `<bundle>/state/trunk/recipes/<name>/`, git-ignored
like it. Write the two files to a temporary path, pass them in, then delete
the temporary copies:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" recipe draft <name> --name <recipe> --roles '<one line per role>' --file <recipe.py> --test <test_recipe.py> --command '<the start command, filled in for this run>' --json
```

It prints the draft's paths. **Check the draft there**, running the check from
where the tooling needs it (for orq's harness, its checkout, which the
tooling's help or README names), and record what happened, whichever way it
went:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" recipe checked <name> --command '<the check, as run>'
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" recipe checked <name> --command '<the check, as run>' --error '<its failure: the first lines, any token it printed cut out>'
```

The script holds the check to the draft's hash: a draft edited after
`recipe draft` is refused, so what is checked is what was recorded.

- **The check failed**: **nothing is dispatched.** The record keeps the
  recipe and the failure. Tell the owner, with the failure, and offer three
  ways on: fix the recipe and check it again (a new `recipe draft`, then
  `recipe checked`), the closest saved recipe as it is, or plain Claude Code.
  Nothing goes on to 3d until the owner picks; a fix that fails again is the
  same choice again, never a retry loop of your own.
- **The check passed**: go on to 3d. The recipe is saved in 3e, with the
  start, not before the owner sees it.

### 3d. Show it

Show the owner, in one message: the brief (or the artifact's location and a
summary of it), the recipe and the fact it came from, the exact command or
commands that will run, where the work will run, and what follows the start:
the confirmation, the record, an `ingest` of the record into the bundle (a
local commit of the facts it yields, never the raw record), and the learnings
of this run. The owner's "dispatch" is the authorization: show this, then go
straight to 3e. If what 3a to 3c produced changed the work the owner agreed to
(a different repository, a part left out), ask before starting instead.

A **written recipe** is shown whole: its roles and stop conditions, the draft's
path, the check it passed (the command), the directory it will be saved in and
the `trunk-recipe` fact it will be saved with. Writing a recipe is part of the
work the owner agreed to only when it says nothing the conversation did not:
a role or a stop condition the owner never heard of is asked about before the
start.

### 3e. Start it

**A written recipe is saved first**, into the directory 3d named, so the
start runs the file the next run will reuse:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" recipe save <name> --dir <the recipe directory>
```

It copies the checked draft, byte for byte, and refuses a draft that was not
checked, failed its check or changed since, and a name already in the
directory: a saved recipe is never replaced. A refusal means nothing is
started; relay it, and on a name already taken draft the recipe again under a
new name, check it again and show it again. The script also refuses the
dispatch of a written recipe that is not checked and saved.

**On orq**, run the command or commands exactly as shown.

- **It ran** (exit 0): record the dispatch, with where it runs (the orq
  team, the workspace):

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run dispatch <name> --via orq --command '<the command, as run>' --where '<team or workspace>'
  ```

- **It failed**: record the attempt with its error (its first lines, with any
  token or secret it printed cut out), so the record says not dispatched:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run dispatch <name> --via orq --command '<the command, as run>' --error '<the error>'
  ```

  Tell the owner it was not dispatched, with the error. The run stays open; a
  retry, now or from a later session, is a new dispatch the owner asks for.
  Never retry on your own, and do not go on to step 4. A written recipe stays
  saved, checked and unedited, with no fact yet: the retry starts that same
  file (`recipe save` says it was saved already) and saves its fact then.

**A written recipe that started** is saved for reuse with a `trunk-recipe`
fact, right after the dispatch is recorded, with **Capturing a how**:

> Capture as a fact, tags `<tag>` and `trunk-recipe`: recipe `<recipe>`, saved
> at `<the saved path>`. It fits <the kind of work: its split, its roles, the
> kind of repository>. Roles: <one line each, with its stop condition>. Started
> with `<the start command, this run's values as placeholders>`; checked with
> `<the check>`.

Like the recipe, the fact says nothing of this topic: it is how this kind of
work is split, for the next run to find. Check it with
`facts --area trunk-recipe`, then link it to the record and keep it as one of
this run's learnings, so 4c does not capture it again and 4d reports it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" recipe fact <name> --link <its link>
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> learning --value '<its link>: recipe <recipe>, for <when it fits>'
```

A capture that did not land is a note, and the recipe stays saved without a
fact: say so in 4d, with the saved path, so the owner can capture it by hand.

**On plain Claude Code**, there is no command to fail: record the dispatch as
the work starting in this session, then go to step 4, where the work runs.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run dispatch <name> --via claude-code --command '<one line: the plan this session runs>' --where 'this session (<working directory>)'
```

A run the script says was already dispatched is never started again: show
what was dispatched and where (`run show <name>`), and continue the
conversation from there, as **A dispatched run** in **Continue a run** says.

## 4. Follow

### 4a. Confirm the work

**On orq**, confirm the sessions are running with what the `trunk-dispatch`
facts name for it (a status or board command). With nothing named, the start
command's own output is the evidence: the team, workspace or sessions it
reports. Say in one line what is running and where. When the check shows
nothing running, say so and record it; the run stays dispatched and is never
started again by the trunk:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> note --value 'started, not confirmed: <what the check showed>'
```

The trunk does not watch the sessions to the pull request: that is their job.
Go to 4b.

**On plain Claude Code**, this session is the maestro: run the work on the
brief, one subagent (the Agent tool) per role of the recipe, and update the
record as the work goes, one note per milestone (a role done, a check green,
the pull request opened, with its link):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> note --value '<the milestone>'
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
the record cannot go in. Check that it did not, and record the ingest, right
after ingest's commit and before anything else commits in the bundle: the
check reads that one commit (the bundle's HEAD), for anything under
`state/trunk/`, a byte copy of the record, or lines carrying its `created`
time together with its name:

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
how**, and check it with `facts --area`. Three exceptions: a how the owner
already captured in this run is not captured again (a recipe written in this
run already has its `trunk-recipe` fact from 3e), one the owner declined
to capture in this run stays uncaptured, and one the owner forgot or steered
away from is never learned again. Before capturing, list those:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" facts --forgotten --json
```

and read the ones in the same area. A learning that says what one of them
said is set aside, and 4d names it as set aside because the owner forgot it.
Only the owner brings a forgotten how back, by stating it again; what they
state is captured as any how they state. Record each learning that landed:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> learning --value '<its link>: <the how, in one line>'
```

A capture that did not land is recorded as a note, and reported as not
recorded.

### 4d. Report and stop

Close with one short message: the run's name, what is running and where (or
the pull request, on plain Claude Code), the ingest's commit, and the
learnings, one line each with its area and its `link`, saying the owner can
steer one or ask to forget it (**Steer or forget a learning**). With nothing
learned, say so in one line. The
trunk stops here; a later session continues the run from its record
(`/elephant-trunk:trunk continue <name>`).

## Continue a run

A run left by an earlier session is continued from its record, never from
memory of that session: this session saw none of it. The bundle was found in
step 0.

### Which run

- **Named.** Read it back:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run show <name> --json
  ```

  When the owner's words are not exactly a run's name (a part of it, or the
  topic in other words), list the runs with `run list --json` and match the
  words against each `name` and `topic`. One match is said in one line and
  read back; several are listed for the owner to pick, as below; none is said
  so, and the open runs are offered instead.
- **Not named.** List the open runs, most recent first:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run list --open --json
  ```

  Show them numbered, in that order, one line each: the name, the topic and
  when it was last continued. Ask which, and wait. Every path in `unreadable`
  is named in one line as a record that could not be read, and not offered.
  With no open run, say so; the dispatched ones (`run list --json`, status
  `dispatched`) are named in one line each, since one of them may be what the
  owner meant, and the owner can also hand over a new topic.

**The record is missing or unreadable** (`run show` exits 1): relay the
stderr as it is and offer to start over from the topic. Ask the owner for the
topic in one line (an unreadable record cannot be trusted to give it), then
go to 1a and open a new run in 1b. The broken file is left where it is: the
trunk deletes no record.

### Where it stopped

Read the record (the `run show --json` above) and tell the owner, in a few
lines, the run's name and topic, when it was started and last continued, what
it holds (the study, how many approaches, the decisions so far, the brief, the
recipe) and where it stopped. Where it stopped is the first row that matches,
top down:

| the record                                                                                  | where it stopped                                     | the run continues at                                    |
| ------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------- |
| `status` is `dispatched`                                                                    | the work was dispatched                              | **A dispatched run**, below                             |
| the last of `attempts` failed                                                               | the start failed, with its `error`                   | the retry, below                                        |
| `recipe.written` with a `check` whose `ok` is false                                         | a written recipe failed its check                    | the three ways on of **Writing a recipe**, in 3c        |
| a `dispatch:` decision, then a `not dispatched: the brief lacks` note                       | the brief lacked the form the dispatch needs         | step 2, with what was missing                           |
| a `dispatch:` decision and nothing after it                                                 | between the owner's word and the start               | the retry, below                                        |
| `approaches`, and no `dispatch:` decision                                                   | in the conversation                                  | step 2                                                  |
| a `study` and no `approaches`                                                               | after the study                                      | 1d                                                      |
| the topic only                                                                              | before the study                                     | 1c                                                      |

"After" is by `at`: decisions and notes both carry one. Before any step runs
again, load the owner's how with 1a, as for a new run: the record keeps what
was decided, not how the owner works, and the facts may have changed since.
Reopening the conversation (step 2) starts from the record: recall the
approaches and every decision so far, and answer from the study, going back to
a source when a question needs it, as step 2 says.

**A word given in an earlier session starts nothing.** The `dispatch:`
decision in the record is history: the owner's "dispatch" authorizes the start
only in the conversation where it was said. **The retry** is a new dispatch,
so it waits for the owner to say to dispatch in this session. Show where it
stopped (the failed attempt's command and error, when there is one) and ask;
on the owner's word, record it with a new `dispatch:` decision and run step 3
whole, from its read back. What the record holds is reused, not rewritten,
unless the owner changes it: the brief still goes through the form check, the
saved recipe is shown again, and a written recipe that was saved before the
failed start is started from that same file (`recipe save` says it was saved
already). 3a runs again in full: this session may be on another machine, and
orq's availability is checked here.

### A dispatched run

A run already dispatched is **never dispatched again**, whatever the owner
asks: `run dispatch` refuses it, and the trunk never starts its command or its
work a second time. Show what was dispatched and where, from the record: the
way (`dispatch.via`), where it runs (`dispatch.where`), when (`dispatch.at`),
the command as run, the recipe, and a short summary of the brief. Then what
followed: the ingests and their commits, the learnings with their links, and
the notes, the last one first (on plain Claude Code they are the work's
milestones).

What is left of step 4 is said and offered, never run silently:

- **On orq**, a status or board command the `trunk-dispatch` facts name can be
  run to say where the sessions stand now. It reads and starts nothing.
- **On plain Claude Code**, when the last note is neither a pull request nor a
  stop, the work stopped short in the session that ran it. The trunk does not
  take it up again: that would be a second dispatch. Say the last milestone,
  and that the owner can carry the rest on as their own work or start a new
  run on what is left.
- **No ingest recorded** (`ingests` is empty): the ingest of 4b never ran or
  failed. Offer to run it now; on the owner's yes, run 4b as written, with
  `run ingested` after it.
- **Learnings**: the record's `learnings`, each with its link, and its
  `steers`, what was forgotten or steered since (`run show` marks each
  learning that was). The owner can steer or forget any of them here, with
  **Steer or forget a learning**, passing this run as `--run`. What this
  session learns about how the owner works goes through 4c, as in any run.

Then the conversation continues from there: answer from the record, and
record each new decision or note with `run set` as in step 2. The study, the
approaches, the brief and the recipe stay as they were dispatched (the script
refuses to change them). Further work the owner wants on the topic is a new
run (`run new`), whose topic can name this one.

## First use

With no fact carrying the how-I-work tag plus a trunk area tag, the trunk does
not guess how this owner works. Say so, and offer the two ways to learn it,
each with what it costs:

- **Read past sessions**: an estimate first (sessions found, their size, the
  tokens it would take), then a small model reads the most recent ones and
  extracts how the owner works, never what was in the session. The owner
  confirms a panorama before anything is saved. It costs the small model's
  reading, shown before anything is read, and a few minutes of the owner's
  confirmation.
- **Interview only**: a few questions on how the owner studies a topic,
  dispatches work and splits it into sessions. It costs a few minutes of the
  owner's answers and no reading of anything else.

When the owner picks the reading, go to **Reading past sessions**; the estimate
there is what they decide on, and nothing is read before they do. When the
owner picks the interview, or declines the reading, go to **The interview**.
Either way, what the owner confirms is saved with **Capturing a how**, and the
run continues at 1a.

## Reading past sessions

The owner's past Claude Code sessions show how they work: what they ask a
topic to be studied with, how they react to approaches, how they start work and
split it. The trunk reads them **once, on first use**, and only on the owner's
word after an estimate; it never debriefs sessions as they end. It keeps how the
owner works, never what was in a session: no topic, no file, no person's or
customer's words, no secret.

The raw transcripts never enter this conversation. The script reads them and
prints counts; small-model readers, in subagents, read the extract the script
makes of them and return statements of how only. Nothing of this is written to
disk; what becomes a fact is what the owner confirms in the panorama.

### The estimate

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" sessions list --json
```

It needs no bundle. It finds every session's transcript (under
`$CLAUDE_CONFIG_DIR/projects`, else `~/.claude/projects`; `--root` when they
live elsewhere) and picks the most recent ones holding at least one message of
the owner's, `limit` of them (30 by default). Sessions run by a script or a
schedule, with no message of the owner's, are passed over and counted in
`skipped_no_owner`. For the ones picked it reports the raw size (`raw_bytes`,
`raw_tokens`), what the readers would read after extraction (`tokens`), and how
that splits into `readers`, one small-model subagent per batch of at most
`batch_tokens`.

- **Exit 1**, or `read` is 0: there is nothing to read. Say so in one line and
  go to **The interview**.
- **Otherwise**, show the owner the estimate in a few lines: the sessions found
  on the machine (`found`), the ones that would be read (`read`, from `since` to
  `until`, across `projects` projects), their raw size and tokens, the tokens
  the readers would read, and how many readers. Say what the extract leaves out
  before any reader sees it: tool output, files read, the assistant's own text,
  system-injected messages, and anything shaped like a credential; only the
  owner's messages and the names of what each session ran (a skill, a subagent,
  a program, never its arguments) are read. Every path in `unreadable` is named
  in one line. Then ask: read these, read fewer or more (a number, run again
  with `--limit <n>` and show the new estimate), or skip. Wait.

### The skip

The owner skips, declines or does not say yes: nothing is read. Go to **The
interview**, whole. Skipping is never asked again in this session: the interview
is the way on.

### The debrief

Before the readers start, list what the owner forgot or steered away from,
with `facts --forgotten --json` as **The interview** does. The readers are not
told of them; the panorama sets aside what matches one.

Start one reader per entry of `batches`, all at once, each a subagent (the
Agent tool) on the small model (`model: "haiku"`). A reader's shell may not
carry `CLAUDE_PLUGIN_ROOT`, so spell the script's absolute path in its prompt.
Its prompt is this, filled in, in English whatever the owner speaks:

> Read how one person works from their past Claude Code sessions. Run
> `python3 "<the script's absolute path>" sessions extract <the batch's paths>
> --max-tokens <batch_tokens>` and read its output: each session's messages
> from the owner, and between them `[then: ...]`, what the session ran next.
> Return only statements of how the owner works, in three areas:
> `trunk-study` (what they have a topic studied with, in what order, how deep,
> how they want approaches shown and how many), `trunk-dispatch` (where work
> runs once they decide: in the same session with subagents, or as separate
> sessions with a tool such as orq or bus-spawn; the form a brief takes; the
> commands that start work and show it running), `trunk-recipe` (how work is
> split into sessions: roles, when each stops, saved recipes and when each
> fits). Only what the owner does or asks for repeatedly or states as a rule;
> one session's one-off is not a way of working. Never write what a session was
> about: no topic, project, repository, file or person's name, no customer, no
> quote of more than five words, no URL, no id, path, version or value of any
> kind, nothing marked `[secret left out]` or `[pasted]`. Generalize what you
> keep ("reads the repository's open pull requests before proposing", not which
> repository); drop what cannot be generalized. Answer with JSON lines only,
> one per statement: `{"area": "<one of the three>", "how": "<one sentence>",
> "sessions": <in how many of these sessions it shows>}`. No statement at all
> is a valid answer: print nothing.

A reader that fails, or answers with anything but those lines, is named in one
line with the number of sessions it held, as not read; the others go on. A line
whose `area` is not one of the three is dropped.

### The panorama

Merge what the readers returned, in this conversation:

1. **The same how** from several readers is one line, its `sessions` summed.
2. **The second gate.** Read each line as the owner's memory would keep it: a
   line that still names a topic, a repository, a person, a customer or a
   value, or carries anything secret, is generalized or dropped here, before
   the owner sees it. When one was, say in one line what kind of content it
   was, without repeating it.
3. **Forgotten.** A line that says what one of the forgotten facts said is set
   aside and named as set aside because the owner forgot it. Only the owner
   brings a forgotten how back, by confirming it below in their own words.
4. **Contradictions.** Two lines that say opposite things for the same step are
   shown side by side, each with its `sessions`, and the owner says which holds,
   as **Two facts that contradict each other** does for facts.

Show the panorama grouped by area, in the order of **The questions**, one line
per how, each with its area tag and in how many of the `read` sessions it
showed ("in 7 of 30 sessions"). An area with no line is said so. Then the
owner confirms, changes or drops lines, as **The read-back** says: one fact per
how, nothing captured before they confirm, nothing they drop captured.

**An area with nothing to show** is offered its questions from **The
questions**, that area's only, with **The answers** applying to what the owner
says; their answers join the read-back. The owner can decline, and the step
asks when it comes (**An area with no fact**).

When the owner has confirmed, capture with **The capture**, exactly as for the
interview: each line with the bundle's how-I-work tag and its one area tag, the
owner's confirmed words, checked with `facts --area`, listed, reported with
their links, and kept as learnings of the run. When nothing was confirmed, say
so in one line and go on as 1a says for a first use that captured nothing.

## The interview

The owner tells the trunk how they work, in their own words, and what they
confirm becomes the facts every later run reads. The questions below are the
same for every owner: they name what each step needs to know, never an answer.
Ask them in the language the owner uses, one area at a time, in this order,
and wait for the answers to each area before the next. Do not suggest an
answer, and do not offer a habit of your own as the default: an example in a
question shows the kind of answer, always with more than one option.

**Before the first question**, list what the owner forgot or steered away
from:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" facts --forgotten --json
```

When it lists any, say in one line how many there are and that the trunk does
not read them. Never read them back as suggestions or pre-fill an answer from
one: a forgotten how comes back only when the owner states it again, and then
it is captured as any answer is.

### The questions

**How a topic is studied** (area `trunk-study`):

1. When you hand over a topic, what should be read, and in what order? For
   example: the memory, the repository's code and docs, its open pull
   requests, its recent history, issues, outside sources.
2. How deep before coming back to you: a first pass that names the open
   questions, or a study that settles them?
3. How should the approaches come: how many, what each one carries
   (trade-offs, cost, risk, what it leaves out), and whether one comes
   recommended?

**How work is dispatched** (area `trunk-dispatch`):

4. Once you say to dispatch, where does the work run: on orq, several
   sessions coordinating over agent-bus, or in this same session, with
   subagents? If both, when each one?
5. What form does the brief take for that way, so the work runs without
   asking you anything (an approved bb spec, a ticket, a plain brief), where
   does it go when it is a file or a ticket, and what checks it is ready?
6. On orq: the command that starts the work, and the one that shows it is
   running. Skip this one when the work only runs in this session.

**How work is split into sessions** (area `trunk-recipe`):

7. How do you split a piece of work into sessions: the roles, and when each
   one stops? If you keep saved orq recipes, which ones, where they live, when
   each one fits, how each is started and how it is checked.

### The answers

- **Nothing invented.** An answer of "I don't know", "skip" or "ask me each
  time" captures nothing for that question: the step asks it when it comes
  (**An area with no fact**). An area whose answers were all skipped has no
  fact, and that is said in the read-back.
- **How the owner works, never the topic.** The topic handed over in step 0
  stays out of the questions. An answer that holds only for this topic ("for
  this one, read the billing repo") is used for this run and not captured,
  unless the owner says it holds in general.
- **Unclear or conflicting.** An answer that does not say enough for its step
  to act on (a source with no name, "the usual command") gets one follow-up
  question. Two answers that contradict each other (read the open pull
  requests first, never read them) are shown side by side and the owner says
  which holds, as **Two facts that contradict each other** does for facts.
- **No secret, no third-party content.** A token, a password, a key or any
  other credential in an answer never goes into a fact: the fact says where it
  lives (an environment variable, a secret manager, a connection the owner
  manages), and the owner is told in one line that the value was left out and
  where to keep it instead. A person's or a customer's words quoted in an
  answer are generalized, as for the brief.
- **A tool named is not checked here.** A command or a recipe the owner names
  is taken as they give it; 3a checks it resolves on the machine when a
  dispatch needs it.

### The read-back

When the three areas are answered, show the owner what would be captured, one
line per fact, each with its area tag. **One fact per how**: a source order, a
depth, a presentation, a dispatch way, a brief form, a start command, a recipe
each stand alone, so the owner can later steer or forget one without the
others. Answers that belong together (a dispatch way and the condition that
picks it) stay one fact. Ask the owner to confirm, change or drop any line,
and wait. Nothing is captured before the owner confirms; what they drop is not
captured.

### The capture

Capture each confirmed line with **Capturing a how**, the bundle's how-I-work
tag (from `config`) and its one area tag, the owner's own words, and the why
when they gave one. Check each with `facts --area <its area>` before the next;
a line that does not show up is said so, with its area, and the rest go on.

Then list them with `facts --json`. When anything landed, tell the owner in
one short message what was captured, one line each with its area and its
`link`, saying they can steer or forget any one later (**Steer or forget a
learning**), and go back to 1a, which reads them as for any run. When nothing
landed, say so in one line and go on as 1a says for a first use that captured
nothing.

Each fact that landed is kept in the run, where 4c finds it already captured
and 4d reports it: in the run this conversation is on, at once, when the
interview came from **Continue a run**; otherwise in the run 1b opens, right
after it opens:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <name> learning --value '<its link>: <the how, in one line>'
```

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

## Steer or forget a learning

What the trunk learned about how the owner works is the owner's to correct, at
any point: right after 4d's report, while continuing a run, or invoked for it
alone. They can **steer** a learning (it is not quite how they work, here is
how) or **forget** one (it should not have been learned). Either way the fact
is never deleted, git keeps its history: it changes status in its own file, the
script rebuilds the bundle's index, and the trunk no longer reads it.

**Which learning.** By its link, as 4d and `run show` print it, or in the
owner's words: match them against the facts `facts --json` lists (`desc`, and
the fact file when the line is not enough). One match is named in one line,
with its link; several are listed for the owner to pick; none is said so. The
trunk steers and forgets only its own how: the script refuses a fact without
the how-I-work tag plus an area tag, which is the owner's to retire with
elephant-mem's `maintain`.

**Forget.** The owner's request is the authorization. Name the fact in one
line, its link and what it says, and run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" learning forget <link> --run <name> --json
```

`--run` is the run this conversation is on, when there is one: the forget is
recorded there. The fact becomes `deprecated`, elephant-mem's own status for
a retired fact, so `query` and `briefing` stop presenting it as current too.
The script rebuilds the index and checks the trunk no longer reads it. Forgetting
undoes nothing already dispatched; from here on this run does not use it.

**Steer.** The owner says how it really is.

1. Capture the corrected how with **Capturing a how**: the same area tag
   unless the owner puts it in another, the owner's own words, and a line
   saying it replaces the learning `<link>`. Check it with `facts --area`.
2. Steer the old learning to it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" learning steer <link> --to <the new link> --run <name> --json
   ```

   The old fact becomes `superseded`, with the new one in its
   `superseded-by` and itself in the new one's `supersedes`; the script
   rebuilds the index and checks the trunk reads the new one in its place.

A capture that did not land (it does not show up in `facts --area`) steers
nothing: say so, and offer to forget the old learning instead.

**Exit 1**: relay the stderr as it is. Not a learning of the trunk's, a link
to no fact, or a missing `build-index.py` change nothing. A `build-index.py`
that failed after the edit leaves the fact file changed and the old index in
place, so the trunk still reads it: say so, stop, and commit nothing.

**Then validate, log and commit**, as elephant-mem's own writes do:

```bash
python3 "<bundle>/scripts/validate-okf.py"
```

It must pass; when it does not, commit nothing and say so. Then append one
dated line to `knowledge/log.md`, newest first, in the form of the lines
already there (`**Trunk**: forgot <link>`, or `**Trunk**: steered <link> to
<the new link>`), and commit locally:
`git -C <bundle> add -A && git -C <bundle> commit -m "trunk: forget <link>"`
(or `"trunk: steer <link> to <the new link>"`). The script keeps
`state/trunk/` git-ignored, so no run record goes in. Never push.

Tell the owner in one line what changed: the link, forgotten or steered to
which fact, and that the trunk no longer reads it.

## Rules

- **The how comes from facts.** Nothing in this file is a preference of this
  owner; a step with no fact asks instead of guessing.
- **Contextual integrity.** The study and the record may hold anything the
  memory and the repos hold. What later travels out of the record (a brief, a
  fact, a recipe) is filtered by the content and the expectation of whoever shared it;
  sensitive content and things shared in confidence stay out.
- **Nothing starts without the owner's word.** The owner's "dispatch" is the
  only authorization to start sessions, and only in the conversation where it
  is said: a word recorded by an earlier session starts nothing. The trunk
  never deploys, never merges and never pushes the bundle.
- **A dispatched run is never dispatched again.** Continuing it shows what was
  dispatched and where; more work is a new run.
- **A forgotten learning is never read.** The trunk reads only active facts,
  and never learns again what the owner forgot or steered away from.
- **A saved recipe is never edited.** A team started from it resumes from
  that file; a better version is a new recipe with a new name and fact.
