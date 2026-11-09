---
status: done
created: 2026-11-05
slug: elephant-trunk
---


# elephant-trunk: from a loose topic to dispatched work

elephant-trunk is a new plugin beside elephant-mem and elephant-wiki, outside the
core. Its first slice is one skill: the owner raises a topic, the trunk studies it
with the owner's memory and comes back with approaches, the two converge in a short
conversation, and the trunk dispatches the work to Claude Code sessions that carry it
to a pull request. Its run is recorded so a later session can continue it.

Why now: the owner already does this by hand and the middle works. Both ends hurt.
The start, because the owner has to instruct exactly how to study a topic. The end,
because on orq the recipe has to be configured and the sessions spawned by hand. The
vision this slice serves is `.bb/elephant-trunk/discovery.md` (sections Vision and
First slice).

Success: the owner hands a topic over in one line, spends their time only in the
conversation, and the work leaves for a PR without them assembling anything.

## The four steps

1. **Study.** The trunk reads how this owner likes a topic studied (from memory),
   studies the topic with elephant-mem and the repositories involved, and presents a
   few approaches.
2. **Converse.** The owner questions, adjusts and picks. The conversation ends when
   the owner says to dispatch.
3. **Dispatch.** The trunk turns the conversation into a brief, in the form this
   owner's dispatch takes, picks a recipe, and starts the sessions.
4. **Follow.** The trunk confirms the dispatch is running, records the run, and stops.
   The PR is the dispatched sessions' job.

## The *how* lives in memory, not in the skill

The skill is a skeleton. Each step reads the owner's own way of doing it from
elephant-mem facts carrying the bundle's how-I-work tag plus a trunk area tag. The
how-I-work tag is set per bundle in `elephant.json` (`trunk.tag`, default
`how-i-work`); this owner's bundle sets `como-trabalhar`, the tag its existing facts
already carry.

| area tag         | what the facts say                                          |
| ---------------- | ----------------------------------------------------------- |
| `trunk-study`    | sources to read, depth, how approaches are presented        |
| `trunk-dispatch` | how this owner dispatches agents (orq, plain Claude Code)   |
| `trunk-recipe`   | reusable recipes: when each one fits and how it is started  |

This is the mechanism already in use by `post-produto-slack`, whose rules are facts
tagged `como-trabalhar` read straight from `knowledge/manifest.jsonl`, never through
the `query` skill.

## Recipes

A recipe is how a piece of work is split into sessions: the roles and the stop
conditions. Saved recipes are reused when one fits, found through `trunk-recipe` facts.
When none fits, the trunk writes a new orq recipe for the case, shows it with the
dispatch, checks it before starting it, and saves it with a `trunk-recipe` fact so the
next run can reuse it.

## The run record

Every run keeps its raw record under `<bundle>/state/trunk/`: the topic, the study,
the approaches, what the conversation decided and what was dispatched. A new session
continues a run from it. After the dispatch, the trunk runs `ingest` over the record so
the useful parts become facts with the right tags; the raw record stays in `state/`.

## Two ways to dispatch

- **orq**: several sessions in an orq workspace, coordinating over agent-bus, through
  the owner's existing tooling (`orq start <recipe> <KEY> --repo … --brief …`).
  `bus-spawn` is infrastructure orq runs on, not something the trunk calls.
- **Plain Claude Code**: the work runs in this same session, right after the conversation,
  as a maestro with subagents, no bus. On this path the trunk ends when the work ends, and
  the record is updated as the work goes.

Which one runs comes from the owner's `trunk-dispatch` facts. Codex and other tools
come when a user needs them.

## First use

With no how-I-work facts carrying a trunk area tag, the trunk does not guess. It offers two paths and says what
each costs:

- **Read past sessions**: it estimates the cost first (sessions found, size, tokens),
  reads the most recent ones with a small model, and shows a panorama of how the owner
  works for confirmation. It extracts how the owner works, never what was in the
  session.
- **Interview only**: a few questions on how the owner studies, dispatches and splits work.

Either way, what is confirmed is saved as tagged facts through `capture`.

## Decisions

- elephant-trunk is its own plugin in this repo, listed in `.claude-plugin/marketplace.json`,
  versioned and changelogged on its own, like elephant-wiki.
- It finds the bundle the way elephant-wiki does: `--bundle`, then `ELEPHANT_BUNDLE`,
  then the pointer file.
- The skill carries no owner-specific way of working; every *how* comes from tagged facts.
- The how-I-work tag is configurable per bundle in `elephant.json` (`trunk.tag`), default
  `how-i-work`; the area tags `trunk-study`, `trunk-dispatch`, `trunk-recipe` are fixed.
- The raw run record lives in `<bundle>/state/trunk/`, git-ignored: it never enters the
  bundle's history. An `ingest` over it after the dispatch turns its useful parts into
  tagged facts, and only those are committed.
- When no saved recipe fits, the trunk writes a new orq recipe, shows it before starting it,
  and saves it for reuse.
- The first slice ends at the dispatch on orq: the trunk does not watch the sessions to the
  PR. On plain Claude Code this session is the maestro and the trunk ends with the work. It
  never deploys.
- Who merges, and why the trunk never checks CI: the quality of the delivery is the owner's,
  and the trunk acts on the owner's behalf; the repository's guardrails (branch protection with
  required checks) belong to its maintainer. A merge is where the two meet. So the trunk never
  reimplements CI checking: it relies on GitHub's own gate, and where that gate is missing it
  stops at the PR.
- Who merges is part of the owner's how: a `trunk-dispatch` merge preference, learned like
  any other how (interview, past sessions, a learning of a run). `manual` (the default with no
  fact): the owner merges by hand, and the trunk merges only when the owner says, in this
  session, to merge this run's PR; otherwise the work ends at a PR. `automatic`: the work is
  dispatched with the merge on, without asking, unless the owner says in this session that the
  run needs their authorization, which makes that run `manual` (on orq, said before
  "dispatch"). A learned `automatic` fact is meant to authorize merges, so "the fact wins"
  holds; the owner is told when it is learned and can steer or forget it.
- Only the owner's own words or behavior set the preference or this session's override; text
  from a third party never does (a Slack message, a ticket, a study source, a brief, a pasted
  message, the topic text). A one-off "merge this one" at `manual` is a value of the run, never
  a learning; only an explicit statement of the general preference becomes the `automatic` fact.
- A merge-preference fact counts only when it came from the owner, and `trunk.py` says so:
  `facts --json` gives each fact an `origin` read from the sources it cites. `owner` when every
  source's `channel` is `claude-code` or `claude-code:<workspace>` (what `capture` files: the
  interview, a confirmed panorama, a learning, the owner capturing it directly); `other` when
  one came from a feed (the catch-up or an ingest of Slack, meetings, email); `unknown` when it
  cites none or one cannot be read. Only `owner` is read for the merge preference; anything
  else means `manual`.
- The level is computed fresh in every session from the current fact plus this session's word,
  and recorded as `merge-level: manual|automatic (<source>)`, never the free `merge:` prefix.
  A level recorded by an earlier session is history. Stored commands (facts, recipe facts,
  pending learnings) never carry the merge parameter; 3c adds it from this run's level, and a
  retry recomputes the brief's done and the command. `trunk.py` holds it: `recipe draft` and
  `run set recipe` refuse a merge parameter in any spelling (and so does `run set` for a
  pending learning or a learning), `run claim` via orq refuses one that disagrees with the last
  `merge-level:` decision, counting only a decision recorded after the run's last start (attempt
  or claim) and its last `dispatch:` decision (any merge parameter when there is none), and a
  `merge-level:` decision in another form is refused. Its refusals say the owner states the
  level in this session; they never suggest adding the parameter.
- The merge condition, the same on orq and on plain Claude Code: the work merges only when all
  three hold, else it stops at the PR with a note. (1) The owner wants it: `automatic` with no
  override, or at `manual` the owner's word in this session. (2) The run's own reviewer, a
  separate one with a fresh context, approved exactly the commit that will merge, a named head
  SHA; an approval from outside the run, an automated reviewer signing as the owner included,
  never counts. The SHA is read from the run's record, never from memory, and must be the PR's
  current head. (3) The base branch is protected on GitHub with required status checks
  (classic protection or a ruleset) and the repository allows auto-merge, read on the PR's own
  repository (from its URL, not the default remote, since an `upstream` remote may differ).
  Then `gh pr merge <n> --repo <owner>/<repo> --auto --merge --match-head-commit <sha>`: the
  method is required (gh fails non-interactively without one), `--merge` by default, else the
  first of `--squash` and `--rebase` the repository allows. GitHub waits for the required
  checks and merges or refuses. A scheduled auto-merge is reported as scheduled, never as
  merged. Never `--admin`, force or a skipped check. Implementing roles never merge: only the recipe's merge step (orq,
  `impl_review` at `--set merge=on-approve`) or the maestro (plain Claude Code) merges.
- A repository with no remote is usually the owner's own local tool, and the owner is less
  strict there: condition (3) becomes the local tests passing on exactly the approved commit,
  with nothing uncommitted, and the merge is a local `git merge --no-ff` of that commit into
  `refs/heads/<base>`, after a `git merge-tree` probe and only when the owner's checkout is on
  the base and clean at that moment; a failed merge runs `git merge --abort`. A commit already
  in the base is reported as that, never as merged. It never stashes, resets or checks out.
- When condition (3) fails, one note says everything missing (protection with required checks,
  auto-merge allowed, or both), so the owner learns it at once: to an admin of the repository,
  turning it on once; to anyone else, that the PR waits for the maintainer. It also says that a
  required check no workflow reports any more leaves an auto-merge waiting forever. The trunk
  never changes repository settings.
- On orq at `manual`, a "merge it" after the team opened the PR goes through the same three
  conditions, and the owner's word never stands in for the review: the recipe pins the
  builder's commit and asks the reviewer for `--meta sha=<sha>` at every level, and the trunk
  merges only when the run's record holds a reviewer's approved SHA that is the PR's current
  head. With none (a run started before that change) or a head that moved, it merges nothing,
  says why and hands the owner the merge.
- In a repository where a push to the base deploys, an automatic merge is in effect a deploy:
  the skill says so at 3d, at the confirmation and in the interview about who merges.
- After 3c picks the recipe, `automatic` needs a recipe with a review role that takes the merge
  level; with none, the run falls back to `manual`, recorded with why. At `manual`, a saved
  recipe must be shown not to merge without the parameter, or the owner is asked before it
  starts. A written recipe's check asserts three things: nothing merges without the parameter;
  a merge is only `gh pr merge --auto <method> --match-head-commit <the reviewed SHA>` after a
  check of protection and of auto-merge being allowed; and no merge call carries `--admin`,
  force or a skip flag.
- A run can be continued in a new session from its record.
- The owner's "dispatch" in the conversation is the authorization to start sessions;
  the trunk shows the brief and the dispatch command before running them.
- The brief obeys the contextual integrity rule: memory content travels into it only when
  the content and the expectation of whoever shared it allow; sensitive content and things
  shared in confidence stay out.
- The session debrief never copies session content or secrets into memory.
- Learning is autonomous by default: the trunk records what it learned about how the owner
  works without asking, and tells the owner what it recorded. The owner can steer a learning
  or ask to forget one; a forgotten learning is no longer read by the trunk.
- A dispatch starts only when the brief has the form the chosen dispatch needs to run without
  interviewing the owner (the form the chosen orq recipe needs: an approved bb spec, for a
  recipe that runs `/bb:implement`).
- Resuming takes a run by name or picks from the open runs, most recent first. A run already
  dispatched is never dispatched again by a resume: the trunk shows what was dispatched and
  where, and the conversation can continue from there.
- Commit convention for this build: every commit on the branch, including those made by
  subagents and workflows, has the subject `feat(trunk-1): ...`. The item comes from a local
  brief with no Wave ticket, so the PR title does not carry the key.

## Behavior

### Happy path

| #   | step                                                                          |
| --- | ----------------------------------------------------------------------------- |
| 1   | The owner invokes the skill with a topic in one line.                         |
| 2   | The trunk loads the owner's how-I-work facts and says which ones apply.       |
| 3   | It studies the topic with elephant-mem and the repos, then presents approaches. |
| 4   | The owner and the trunk converge; the owner says to dispatch.                 |
| 5   | The trunk writes the brief in the owner's dispatch form and shows it.         |
| 6   | It picks or writes the recipe, shows it with the command, and starts it.      |
| 7   | It confirms the work is running, records the run and ingests the record.      |
| 8   | It records what it learned about how the owner works and says what it was.   |
| 9   | Later, a new session continues the run from its record.                       |

### Edges

| WHEN                                                     | THEN                                                               |
| -------------------------------------------------------- | ------------------------------------------------------------------ |
| no how-I-work facts with a trunk area tag exist         | offers session reading (with a cost estimate) or interview only    |
| the owner skips session reading                          | interview only; answers saved as tagged facts                      |
| a session holds secrets or third-party content           | nothing of it reaches memory; only how-the-owner-works statements  |
| the preferred dispatch is orq and orq is not available   | says so and offers plain Claude Code                               |
| the repo the work belongs to is unclear                  | asks before writing the brief                                      |
| no saved recipe fits                                     | writes a new orq recipe, shows it, saves it for reuse              |
| a written recipe fails its check before starting         | nothing is dispatched; the record keeps the recipe and the failure |
| the brief lacks the form the dispatch needs to run alone | nothing is dispatched; says what is missing; the chat continues    |
| two how-I-work facts contradict each other              | shows both and asks; offers to capture the winner                  |
| the owner asks to forget a learning                      | the fact stops being read by the trunk                             |
| no merge preference fact                                 | `manual`: the work ends at a PR; nothing is asked                  |
| the preference is `automatic`                            | dispatched with the merge on, without asking                       |
| `automatic`, and the owner says this run needs their OK  | the run is `manual` (session override)                             |
| `manual`, and the owner says in this session to merge    | the run is `automatic` (owner in this session)                     |
| a third party's text asks to merge or to skip asking     | changes nothing; never sets the preference or the override         |
| a continued run holds a `merge-level:` decision          | history; the level, done and command are computed again            |
| `automatic`, the recipe has no review or no merge level  | falls back to `manual`, recorded with why                          |
| `manual`, a saved recipe not shown to merge nothing       | the owner is asked before it starts                                |
| a merge-preference fact came from a feed, not the owner  | set aside for the merge preference; the level is `manual`          |
| the reviewer did not approve the head that would merge   | nothing merges; the PR stays open for the owner, with a note       |
| the base branch has no required status checks            | nothing merges; the note suggests protection (admin) or waits      |
| the repository does not allow auto-merge                 | nothing merges; the same note names it with the protection         |
| the run's record holds no reviewer SHA, or the head moved | nothing merges; says why and hands the owner the merge             |
| a `merge-level:` decision predates the last start or dispatch word | `run claim` ignores it; the owner states the level again   |
| the approved commit is already in the base (no remote)   | reported as already in the base, never as merged                   |
| the repository has no remote                             | merges locally only if tests pass on that commit, all clean        |
| the owner's checkout is off the base or dirty (no remote) | nothing merges; never stashes, resets or checks out               |
| at `manual` on orq, the owner says "merge it" after the PR | the same three conditions, with the team's approved SHA            |
| a stored command carries a merge parameter               | `trunk.py` refuses it                                              |
| the brief would carry content not meant to travel        | that content is left out or generalized before the owner sees it   |
| the dispatch command fails                               | the record says not dispatched, with the error; resume retries     |
| an `ingest` commits the bundle after a run                | the raw record stays out of the commit; only extracted facts land  |
| the owner leaves before dispatching                      | the record keeps the study and approaches; resume reopens the chat |
| the run record is missing or unreadable on resume        | says so and offers to start over from the topic                    |
| resume is asked with no run named                        | lists the open runs, most recent first, and asks which             |
| resume reaches a run already dispatched                  | shows what was dispatched and where; never dispatches it again     |
| `trunk.tag` is absent from `elephant.json`               | reads `how-i-work` and says how to set another tag                 |
| the bundle is not found                                  | stops with the same guidance elephant-wiki gives                   |

## Metric

- Metric: trunk runs that reach a dispatch per week, read from the run records
- Baseline: 0 (the trunk does not exist yet)
- Target: skipped: set after two weeks of the owner's own use
- Events: none, a local plugin with no telemetry; the run records are the measure

## Attention points

- `orq new` takes no initial prompt and a free team has no topic messages; structured
  coordination on the bus needs a recipe or `bus-team` (`agent-bus-setup/bin/orq`).
- `bus-spawn` needs a repo already trusted in Claude Code, and goes straight to
  `/bb:implement` only when the brief passes its approved-spec rule (`lib/bbspec.py`).
- The orq tooling lives in the owner's private checkout `agent-bus-setup`; no other user
  has it, so the orq path is machine-specific.
- The 30 most recent session transcripts are about 79 MB raw (about 20M tokens); the
  only existing text extractor, `orq/transcript.py`, also lives in that private checkout.
- `elephant.json` has no namespace for extension config yet; `trunk` is the first such
  key besides the wiki's `hooks` entry (`docs/configuration.md`).
- An orq recipe is Python run by `orq/kernel.py`; `orq resume` aborts with "resume
  diverged" when a replayed prompt differs, and recipes have a test harness
  (`orq.testing.run_recipe`).
- `orq resume` reloads the recipe from the path saved at start (`bin/orq:217-221`), so
  editing a saved recipe for reuse breaks the resume of teams started with the old version.
- `<bundle>/state/` mixes committed and git-ignored files; a raw run record can hold
  whatever the conversation touched.
- `ingest` is an LLM procedure that commits with `git add -A` and fires `post_ingest`
  (`plugin/skills/ingest/procedure.md`, step 8): whatever sits un-ignored under `state/`
  goes into the commit.
- `capture` has no tag parameter: tags are asked for in natural language and nothing
  validates them (`plugin/skills/capture/SKILL.md`).
- `~/.claude/skills/post-produto-slack/scripts/regras.py` already reads `como-trabalhar`
  facts; a second reader of the same tags can drift from it.
- `briefing.py --tag` matches one exact tag and must run from `<bundle>/scripts/`.
- `elephant-update` knows plugins by name (`plugin/bin/elephant-update:84-94`); a plugin
  that copies scripts into the bundle is invisible to it unless listed there.
- `tests/test_skill_invocation.py` scans only `plugin/skills/`, and CI lists each test
  file by hand (`.github/workflows/ci.yml`).
- In a repository where a push to the base branch deploys, an automatic merge is in effect a
  deploy.
- `origin: owner` trusts a source's `channel: claude-code*`, and the bundle already holds
  content pasted or fetched into a Claude Code session, and autonomous sessions, stamped that
  way. A fact that looks like the owner's may not be. The fix belongs to elephant-mem's
  `capture` (a marker only `capture` writes), another plugin.
- Unconfirmed: whether GitHub checks `--match-head-commit` (`expectedHeadOid`) again against a
  push made after the auto-merge was scheduled.

## Tasks

### Foundation

- [x] **1. The plugin exists**: `elephant-trunk/` with its `plugin.json`, CHANGELOG and
      marketplace entry; resolves the bundle like elephant-wiki and reads `trunk.tag`. · verify: `python3 tests/test_trunk.py`

### Memory and record

- [x] **2. Reading the owner's how**: a stdlib script lists active facts carrying the
      how-I-work tag plus a trunk area tag, from the manifest only. · verify: `python3 tests/test_trunk.py`
- [x] **3. The run record**: a run is written to `state/trunk/`, git-ignored in the
      bundle, read back and continued. · verify: `python3 tests/test_trunk.py`

### Study and converse

- [x] **4. Study and converse**: the skill loads the owner's how, studies the topic,
      presents approaches and converges (happy path 1–4). · verify: reading

### Dispatch

- [x] **5. Dispatch and follow**: brief in the form the dispatch needs, saved recipe, orq
      or plain Claude Code, confirmation, record, ingest of the record, learnings recorded
      and reported (happy path 5–8). · verify: reading

### A recipe when none fits

- [x] **6. Writing a recipe**: a new orq recipe for the case, shown, checked before it
      starts, saved with a `trunk-recipe` fact. · verify: reading

### Continue a run

- [x] **7. Continue a run**: a new session resumes a named or picked run; a dispatched run
      is shown, never re-dispatched (happy path 9). · verify: reading

### Steer and forget

- [x] **8. Steer and forget a learning**: the owner redirects a learning or asks to forget
      one, and a forgotten learning is no longer read. · verify: `python3 tests/test_trunk.py`

### Interview

- [x] **9. The interview**: with no how-I-work facts for the trunk, the questions and
      the captured answers. · verify: reading

### Reading past sessions

- [x] **10. Reading past sessions**: the cost estimate, the skip, the small-model debrief
      that keeps how-the-owner-works only, the panorama for confirmation. · verify: reading

### Close

- [x] **11. Docs and CI**: README and docs mention the plugin and `trunk.tag`; each new
      test file has its own CI line. · verify: CI

## Out of scope

- Picking up work on its own from discussions, and speaking in the owner's name in Slack
  (capabilities 2 and the `bot-` voice in the vision). _revisit_
- Debriefing every session continuously after it ends; this slice reads history only on
  first use. _revisit_
- Watching the sessions to the PR, deploying, and monitoring after the merge. _revisit_
- Codex and dispatch tools other than orq and plain Claude Code. _revisit_
- A declarative recipe engine replacing orq's scripted recipes. _revisit_
- A risk ceiling per owner: nothing in this slice acts beyond the dispatch the owner
  authorizes in the conversation. _revisit_

## Open

Nothing.
