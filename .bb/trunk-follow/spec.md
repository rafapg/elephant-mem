---
status: in-progress
created: 2026-11-09
slug: trunk-follow
---

# The trunk follows its work past the pull request

Today a trunk run ends when the pull request opens. The orq team closes, nothing
wakes the trunk again, and the owner becomes the watcher: they notice the
approval, decide the merge, run or watch the deploy, and check that it went
live. This spec makes a run keep going until the work is live and healthy, or
until it hands the work back with a reason. A dispatched run waits on what comes
next. A scheduled routine looks at every waiting run, puts what changed on a
local queue, and hands each change to an orq session that decides the next step
the way the owner would: merge now, hold until business hours, deploy, confirm
the deploy, or give the work back.

It builds on the trunk as specced in `.bb/elephant-trunk/spec.md` and on the
merge condition PR #26 added (SKILL.md §3a). Success is a run whose pull request
gets approved by the right person, merges under GitHub's gate at a sensible
hour, and is confirmed live, without the owner typing anything, with a Slack
note at each step saying what happened and why.

## The pieces

```
scheduled routine (Claude Desktop, hourly)
  └─ trunk.py follow poll ── sources (scripts, no model) ──▶ queue (state/trunk/)
  └─ for each new event: route ──▶ orq session ──▶ trunk "continue from event"
                                                     └─ decides by the owner's facts
                                                     └─ note in the run + Slack
```

- **A waiting run.** At dispatch, the run records what it waits on and what it
  will do then. First it waits on its team: the orq team key, the repo and the
  branch. When the team finishes, the wait gains the pull request (or, in a repo
  with no remote, the branch to merge locally) and the commit the run's
  reviewer approved. Then it waits on the approval, the hour, the deploy and the
  health check, in that order, with since when and the last state it saw.
- **Sources.** A source is a script that reads one kind of thing and prints
  typed events. This version ships four: the run's orq team (its `approved`
  message, read from orq's store, with the SHA and the pull request link; a
  team that finished with no approval); the state of the waiting runs' pull
  requests on GitHub; the deploy signal GitHub records for a merge commit
  (workflow runs and deployments); and time (a held run's hour arrives, a health
  window ends, a wait goes stale). Later sources plug into the same queue.
- **The queue.** A local file under `<bundle>/state/trunk/`, which the trunk
  already keeps out of git. An event carries structured fields only (numbers,
  states, logins, SHAs, conclusions, timestamps), never text someone else wrote.
- **The routine.** A Claude Desktop scheduled task, like the catch-up. Each tick
  runs the sources, then routes each new event to an orq session. With nothing
  new, it ends at once.
- **The decision.** The orq session that gets the event continues the run and
  decides the next step from the owner's `como-trabalhar` facts in the area
  `trunk-follow`, writing its reasoning before acting.

## How the merge is decided now

The `manual`/`automatic` preference goes away. The trunk decides each merge from
the owner's facts, the way a senior person would: whether the approvals that
arrived are enough for this change, given who the trunk asked to review and how
critical the change is; whether this is the hour for it; and whether the owner
said anything for this run. The floor under that judgment stays:

1. The run's own reviewer approved exactly the commit that merges, and it is
   still the pull request's head.
2. GitHub gates the base: required checks and auto-merge allowed. The trunk
   never reads CI itself. A repo without that gate gets a note and no merge.
3. No hold on the run. "Don't merge before I approve" said for a run is a hold,
   and only the owner lifts it.

## What deploying means, repo by repo

The trunk discerns, per repo, what the deploy is and what "live and healthy"
means, from the repo itself (its `CLAUDE.md`, workflows, release docs) and the
owner's facts, and records both in the run before the merge. The owner's own
examples set the range:

- **A web service** deploys on its own after the merge. Live is the deploy
  GitHub records for the merge commit finishing well; healthy is the new
  version running with no unexpected errors over a window after it.
- **elephant-mem** deploys by the merge plus the release: the tag on the merge
  commit and the GitHub release, as its `CLAUDE.md` describes, under the tag
  prefix of the plugin whose version the change bumped. The trunk cuts them. A
  merge that bumped no version has no release: the merge is the deploy.
- **A LexFlow app** deploys with `lexflow deploy`, which the trunk runs after
  the merge, preceded by its `--dry-run`. A deploy that would ask for a secret
  value stops and goes to the owner; the trunk never supplies or records one.
- **A local tool** (a repo with no remote) deploys by the local merge, under
  the light guards of SKILL.md §3a for local repos.

A repo where the trunk cannot tell what the deploy is gets a note and stops at
the merge.

## Decisions

- A dispatched run whose work ends in a pull request does not end there: it
  waits, with a structured record of what it waits on and what comes next.
- The merge is the trunk's judgment from the owner's facts, replacing the
  `manual`/`automatic` preference; the three floor conditions above always hold.
- The owner's explicit hold for a run blocks its merge until the owner lifts it
  in a session.
- A change the trunk judges critical, in a repo where the merge deploys, waits
  for business hours: the owner's timezone from `elephant.json`, weekday working
  hours from the configuration, Monday to Friday 9:00 to 18:00 when none are
  configured.
- A scheduled auto-merge on a critical change that is still pending when the
  hours close, or on a run that gets a hold, is cancelled, and the run holds.
- Every run that ends its work in a pull request or a branch waits the same
  way, whether it was dispatched on orq or worked on plain Claude Code; on plain
  Claude Code the session itself records the wait when it opens the pull
  request.
- After the merge the trunk follows the deploy as the repo defines it, runs the
  deploy step itself where the repo's deploy is a command (a release, `lexflow
  deploy`), and checks health where the repo has a service to check.
- Health checks only read: logs, endpoints and error reports, never a change to
  the environment.
- Before any merge or deploy step, the trunk writes its reasoning as a note in
  the run, and the Slack note carries it.
- On orq, the trunk dispatches `impl_review` without a merge parameter (the
  recipe stops at the pull request); merging and deploying are the follow's job.
- The routine is a Claude Desktop scheduled task, hourly.
- Routing: the session that owns the run when it is alive and can take a
  message; otherwise the `/orq master` reading picks a live session that fits;
  otherwise a new orq session in the run's repo.
- Events carry structured fields only. No comment, review body, log line or
  message text enters an event or the line that wakes a session.
- The same state never enqueues twice: an event enters only when the state
  differs from what the run last saw.
- In this version the trunk acts on an approval, on the hour arriving, on the
  deploy signal and on the health window. A change request, failing checks or a
  broken deploy only notify, and the run waits for the owner.
- A run with no change for 3 days gets a Slack reminder; at 7 days it leaves
  the wait and the work is the owner's.
- Notifications go to the owner's Slack self-DM and show on the orq board
  through the session the follow opens. The woken session sends the note of
  each decision it makes; the routine sends the notes that need no decision
  (reminder, give-back, merged or closed by someone else, a delivery failure).
- Routing never lands in a session the owner is using: a live session is a
  candidate only when the follow or the trunk opened it for this run.
- The owner's facts on merging, deploying, the hour, breaking and notifying
  live under the area tag `trunk-follow`.

## Behavior

### Happy path

1. The trunk dispatches a run on orq; the team opens the pull request with
   reviewers requested and posts its `approved` message.
2. The run records the wait on its team at dispatch; on the next tick the team
   source reads the `approved` message, and the wait gains the pull request and
   the approved SHA.
3. An hour later the routine polls; a reviewer approved; the source emits a
   `pr-approved` event with the reviewer's login and the head SHA.
4. The routine routes the event: the owning session is gone, so it opens a new
   orq session in the repo and tells it to continue the run from the event.
5. That session reads the run and the owner's facts, finds the approval enough,
   no hold, and the hour right; it records what the deploy is for this repo,
   checks the floor, writes its reasoning as a note, and schedules the merge
   with GitHub.
6. A later tick sees the pull request merged; the run now waits on the deploy,
   and the owner gets a Slack note: merged, and why.
7. The deploy source sees GitHub's deploy for the merge commit finish well; the
   run waits for the health window.
8. When the window ends, the woken session reads the service's errors since the
   deploy, finds nothing unexpected, ends the run, and Slack says it is live.

### Edge cases

| WHEN | THEN |
| --- | --- |
| the team finishes with no approval | Slack note; the run waits for the owner |
| a repo with no remote, the team approved | the woken session decides the local merge under §3a's local guards |
| the work was done on plain Claude Code | the session records the wait at the pull request; the follow takes it from there |
| a hold or the closing hour arrives after the auto-merge was scheduled | the auto-merge is cancelled and the run holds |
| no business hours are configured | Monday to Friday, 9:00 to 18:00, in the owner's timezone |
| an elephant-mem merge bumped no version | no release; the merge is the deploy |
| `lexflow deploy` would ask for a secret value | the deploy stops; Slack hands it to the owner; no value is recorded |
| the approval is not enough for this change | the run keeps waiting; the note says whose approval it waits for |
| the run has a hold | no merge; Slack says it is ready and waits for the owner |
| the change is critical and it is outside business hours | the run holds until the hour opens; Slack says so |
| the hour opens for a held run | the routine wakes it and the merge decision runs again |
| the approved SHA is no longer the head | no merge; note and Slack say the head moved |
| the base has no required checks or auto-merge | no merge; note and Slack name what to turn on |
| a reviewer requests changes | Slack note; the run waits for the owner |
| checks fail on the head | Slack note; the run waits for the owner |
| someone else merges the pull request | the run moves on to the deploy as if it had merged |
| someone else closes the pull request | the run ends; Slack says who |
| the repo's deploy is a release | the trunk tags the merge commit and creates the release as the repo describes |
| the repo's deploy is `lexflow deploy` | the trunk runs the dry run, then the deploy, and records the result |
| the trunk cannot tell what the deploy is | it stops at the merge; Slack says the deploy is the owner's |
| the deploy fails | Slack note with what failed; the run waits for the owner |
| the health window shows unexpected errors | Slack note with what was seen; the run waits for the owner |
| the repo has no service to check | the run ends when the deploy finishes |
| 3 days with no change | one Slack reminder naming what it waits for |
| 7 days with no change | the run leaves the wait; Slack hands the work back |
| the same state is seen on the next tick | nothing is enqueued |
| two ticks overlap | one event is delivered once |
| the routine finds no waiting run | it ends without opening any session |
| GitHub or `gh` cannot be read | no event; the tick's log says why; the next tick retries |
| routing fails (orq down, no repo checkout) | the event stays queued; Slack says it could not be delivered |
| an event's run no longer exists | the event is dropped with a log line |
| the owner continues the run by hand meanwhile | the hand-made step counts; the next event sees the new state |
| a run dispatched before this version | it is not waiting; the follow ignores it |

## Metric

skipped: a personal tool with a handful of runs a week; the owner reads the outcome in the Slack notes rather than a measure.

## Attention points

- The orq session that receives an event runs Claude Code from orq; whether
  the claude.ai Slack connector is available there is unverified.
- `orq tell` refuses recipe agents and sessions outside herdr
  (`orq/tell.py`); an `impl_review` team is finished by the time an approval
  arrives.
- The run record has no structured field for the owning orq session or the
  pull request today; `claim.where` and `dispatch.where` are free text
  (`trunk.py` around 933-979).
- The `approved` message lives in orq's SQLite store (`~/.agent_bus/agent_bus.sqlite`,
  read through `orq.bus`), now that the agent-bus itself is deprecated.
- A woken session that reads the pull request, logs or error reports to decide
  reads text written by others; the event's structured fields do not cover that
  read.
- The trunk's "Continue a run" path offers steps and waits for the owner
  (SKILL.md around 1030-1086); a session woken by an event has no owner present.
- Reading a service's errors needs credentials and tools per environment; the
  read-only guard `/bb:debug` uses lives in the bb plugin, outside this repo.
- A release or `lexflow deploy` run by the trunk is outward and hard to undo;
  `lexflow` needs a logged-in session on the machine.
- Which GitHub signal marks a deploy differs per repo (deployments, a workflow
  on push, none at all).
- `lexflow deploy` prompts at deploy time for each `$secret` value in
  `lexflow.toml`; an unattended session has no one to answer it.
- `elephant.json`'s `timezone` is a fixed offset with no daylight saving.
- `orq tell` refuses only `working` or `blocked` sessions, so an idle session
  the owner is typing in accepts it; `orq new` may take the focus when it opens
  a workspace.
- Claude Desktop scheduled tasks run only while the app is open; ticks missed
  while it was closed are not replayed, and a held hour can pass unseen.
- Two duplicate-looking scheduled tasks already exist for elephant-mem
  (`~/.claude/scheduled-tasks/`); a new task can be installed twice the same
  way.
- Removing the merge preference touches decisions already recorded as
  `merge-level:` in existing runs and the `run claim` check that reads them.

## Tasks

### Phase 1: the waiting run

- [ ] **1. The run waits**: `trunk.py` gains a `waiting` status and a structured
      wait (what it waits on, repo, pull request, approved SHA, owning orq
      session, deploy kind and health rule, hold-until, since, last state,
      reminded), a `hold` decision, and `run` subcommands to set and read them;
      the `merge-level` preference is retired. · verify: `tests/test_trunk.py`

### Phase 2 (tasks run together)

- [ ] **2. The queue and the sources**: `trunk.py follow poll` runs the sources,
      enqueues typed events with dedupe, and ships the orq team source, the pull
      request source, the deploy source and the time source (hold-until, health window, 3-day
      reminder, 7-day give-back). · verify: `tests/test_trunk.py` with a fake `gh`
- [ ] **3. The trunk decides from events**: SKILL.md replaces the merge
      preference with the judgment from the owner's facts, adds business hours,
      the per-repo deploy and health discernment, records the wait at dispatch,
      dispatches `impl_review` without a merge parameter, and adds "continue
      from an event" with the note-before-acting rule. · verify: reading against
      `## Behavior`

### Phase 3: the routine

- [ ] **4. The follow routine**: a `follow` skill for the scheduled task polls,
      routes each event (owning session, `/orq master` reading, `orq new`),
      marks it delivered, and sends the Slack notes; the README says how to
      schedule it once and where business hours are configured. · verify: a dry
      run against a real waiting run

### Phase 4: the release

- [ ] **5. Docs and version**: the trunk's spec, README and CHANGELOG
      describe the follow; `elephant-trunk` bumps to 0.1.0-beta.3. · verify:
      `for t in tests/*.py; do python3 "$t" || echo "FAIL $t"; done`

## Out of scope

- Acting on a change request or failing checks (pushing fixes to the pull
  request): _revisit_ when the notify-only path has run for a few weeks.
- Opening a fix pull request after a broken deploy or unexpected errors:
  _revisit_ when the deploy follow has caught a real break.
- Reverting a deploy: _discarded_, the owner prefers a fix pull request over a
  revert.
- A row for waiting runs on the orq board itself: _revisit_ when the Slack
  notes prove not enough to see what is waiting.
- Other sources (Slack, calendar, Wave): _revisit_ when a second kind of source
  is asked for.
- The agent-bus as transport: _discarded_, deprecated; orq is the only way.

## Open

Nothing.
