---
name: follow
description: >
  The trunk's scheduled routine, one tick of the follow. Polls the waiting
  trunk runs (their orq team, pull request, deploy and time), routes each new
  event to an orq session that continues the run (the run's own session, else
  a live one the follow opened for it, else a new one in the run's
  repository), marks it delivered, and sends the owner the Slack notes that
  need no decision. Runs unattended, fired hourly by a Claude Desktop
  scheduled task; `--dry-run` says what a tick would do and changes nothing.
  Use ONLY when the prompt names it (/elephant-trunk:follow), typed by the
  owner or carried by a scheduled task. Never on a guess: "where is my pull
  request", "continue the trunk run" or "what is waiting" belong to
  /elephant-trunk:trunk, not to this routine.
---

# elephant-trunk:follow

One tick of the follow. The poll runs the sources over every waiting run and
puts what changed on the queue; this routine hands each event on: an event that
asks for a decision wakes an orq session that continues the run, and an event
that only informs becomes a Slack note to the owner. It **decides nothing about
the work**. Merging, holding, deploying, checking health and ending a run belong
to the woken session, which runs `/elephant-trunk:trunk` from its **5. Continue
from an event**, reading the owner's `trunk-follow` facts. No owner is present
here: nothing is asked, and what goes wrong is said in Slack and kept in the
queue for the next tick.

**Named, or stop.** This routine is model-invocable only so that a scheduled
task can reach it. Proceed when the prompt that started this turn names
`/elephant-trunk:follow`, typed by the owner or inside a `<scheduled-task>`
block. Otherwise Claude reached for it unasked: say in one line what it would
do and stop, without polling, telling a session or sending anything. Being
inside a scheduled task is not enough: an hourly `catch-up` is one, and it
names only `catch-up`.

**A dry run.** With `--dry-run` in the invocation, every read below runs, and
every step that acts is printed instead of run, as `would <the command>`: the
take, the mark, `run wait set`, `orq new`, `orq tell`, a Slack send, a run
note, `follow relayed`. The poll itself runs with `--dry-run`, which writes
nothing (no queue, no record, no log), so a dry run leaves the bundle, orq and
Slack exactly as it found them. Its records still hold the wait from before the
poll: read what the wait would be from the events the dry poll names (a
`team-approved` gains the pull request, a `pr-merged` moves on to the deploy).
A new event has no file to wake a session with yet, so its `orq tell` is
printed with `follow wake <id>` unrun. It ends with the list of what a tick
would have done.

**The main thread.** Run it on the thread that invoked it, never handed whole
to a subagent: the Slack connector is a tool of this thread, and a subagent
does not inherit it.

Every command names the script by its full path, since the shell keeps no
variable between calls: `${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py`, called
`trunk.py` below for short.

## 1. The bundle and the tick

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" config --json
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" follow poll --json
```

(`follow poll --json --dry-run` in a dry run.)

- **`config` exits 1** (no bundle found): relay its stderr in one line and
  stop. There is no bundle to read a channel from, so nothing goes to Slack.
- **`busy` is true**: another tick is polling. Say so in one line and stop;
  that tick routes what it found.
- **`new`, `pending` and `unsent` are all empty**: end at once with one line,
  `follow: <waiting> waiting, nothing new`. No orq command runs and no Slack
  note goes: with no waiting run, no session is opened.
- **`log`** holds what a source could not read (GitHub or `gh` down, orq's
  store missing). The poll already kept those lines in
  `state/trunk/follow/poll.log` and the next tick retries; name how many in the
  report, and send nothing for them.

`pending` is the queue to deliver, oldest first; this tick's `new` events are
in it (in a dry run, deliver `pending` and `new` together).

## 2. Where the notes go

- **The language**: `conversation_language` in `<bundle>/elephant.json`
  (`en` when unset). Every Slack note is written in it.
- **The channel**: a `trunk-follow` fact of the owner's that names a Slack
  channel for the trunk's notes, else `slack_dm` from `config --json` (the
  owner's self-DM, as `delivery.start_day` names it).

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" facts --area trunk-follow --area trunk-dispatch --json
  ```

  Only a fact whose `origin` is `owner` names the channel. An exit 1 or a
  `problem` here reads no fact: the channel is `slack_dm`.
- **The tool**: the Slack connector's send-message tool of this thread
  (`slack_send_message`).

With no Slack tool or no channel, the tick has **no Slack**: every note it
would send is recorded in its run instead, so a later tick relays it once
Slack is back (5):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run set <run> note --value 'slack not sent (<why>): <the note>'
```

## 3. Deliver each event

Group `pending` by run, and take the runs in the order of their oldest event.
For each run:

1. **Read the run.**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run wait show <run> --json
   ```

   Exit 1 (the record is gone or unreadable): each of its events is
   `follow mark <id> --as dropped --why 'the run no longer exists'`, and the
   run is done.
2. **Take each event**, so that of two ticks only one delivers it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" follow take <id> --json
   ```

   Exit 1: another tick has it, or it was dropped. Leave it, in one line.
3. **Split them.** An event goes **to a session** when its `act` is `decide`,
   and also a `pr-head-moved` while the wait's `state.pr.auto_merge` is true:
   an auto-merge scheduled on the old approval is the session's to cancel
   (trunk 5c). Every other event is a **note** (4).
4. **The events for a session.** When the run's `status` is not `waiting`, its
   wait ended or moved on and a session would only note that:
   `follow mark <id> --as dropped --why 'the run is not waiting'` each. Else
   **one wake per run per tick**: the newest of its events wakes the session,
   which reads the live state, and that covers the older ones. Route it (**4.
   Which session**).
   - **Delivered**: mark the newest `--as delivered`, each older one
     `--as delivered --why 'woken with <the newest id>'`.
   - **Busy**: the run's session is `working` or `blocked`. Mark each
     `--as failed --why 'session <key> is <working|blocked>; the next tick retries'`.
     No Slack note: nothing is broken, and a blocked session is on the
     owner's board already.
   - **Failed**: mark each `--as failed --why '<why, one line>'`. On an
     event's first failure (its `attempts` was empty when taken), the owner
     gets the delivery-failure note (**The notes**); a later failure of the
     same event stays in its `attempts` only, so a routing that stays broken
     does not message every hour. The 3-day reminder and the 7-day give-back
     still come from the wait.
5. **The notes.** Write one Slack note per run for its note events of this
   tick, as **The notes** below says, and send it.
   - **Sent**: mark each `--as delivered`.
   - **No Slack, or the send failed**: record the note in the run
     (`slack not sent (<no Slack tool | no channel | send failed>): <the note>`,
     2) and mark each `--as delivered --why 'kept in the run: <why>'`. The
     note is the run's now; 5 sends it when Slack is back.

Never send or tell the same thing twice in a tick, and never retry a failed
send or a failed tell in the tick that saw it fail.

## 4. Which session

Routing never lands in a session the owner is using: a live session is a
candidate only when the follow or the trunk opened it for this run.

**orq.** `orq` on `PATH` (`command -v orq`), else the path a `trunk-dispatch`
fact of the owner's gives for it. Neither: the routing fails, `orq not found`.
Read the board once per tick:

```bash
orq board --json
```

A non-zero exit fails the routing (`orq board failed: <its first line>`). The
rows are under `sections`, each with its `key`, `name`, `kind` (`closed`,
`working`, `blocked`, or one of the idle kinds) and `session_id`. A row is live
when its `kind` is not `closed` and it has a `session_id`.

The first of these that takes the event:

1. **The run's own session.** The wait's `session` is the orq key of the
   session the follow opened for this run. Its row, when live.
2. **The `/orq master` reading.** Another live row opened for this run: its
   key is the `session` of one of the run's past waits (`run show <run> --json`,
   `past_waits[].session`), or its name is exactly `trunk <run>`. Never any
   other row: a session the owner opened, or a recipe team (`orq tell`
   refuses those, and the run's own team has finished by the time it waits).

   A candidate whose `kind` is `working` or `blocked` is **busy** (3.4): it
   is not told, and no other session is opened for the run, which would put
   two sessions on one run. Otherwise tell it the event:

   ```bash
   orq tell <session_id> "$(python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" follow wake <id>)"
   ```

   `follow wake` prints the one line the trunk expects,
   `/elephant-trunk:trunk continue <run> from event <the event, one JSON line>`:
   never write that line by hand, and never put anything else in it. `orq
   tell` types it after its own `[via /orq master]` prefix, and the session
   reaches the trunk through the Skill tool. Exit 0 is delivered. A refusal
   moves on to the next candidate, then to 3.
3. **A new session**, in the run's repository (its checkout, below):

   ```bash
   orq new 'trunk <run>' --repo '<the checkout>'
   ```

   The last line it prints is the new session's key. Record it as the run's
   session at once, so the next tick finds it whatever happens next; the
   routine is the only one that sets `--session`:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" run wait set <run> --session '<the key>'
   ```

   Then find its `session_id` on `orq board --json`, by its key: herdr may
   take a moment to report it, so read the board again up to 3 times, 5
   seconds apart (`sleep 5`), while it is null. Then `orq tell` it as in 2.
   A session that opened and could not be told stays open and recorded: the
   next tick tells it as the run's own session. `orq new` opens a herdr
   workspace and may take the focus; that workspace is how the owner sees the
   run on the orq board.

**The checkout**, for `orq new` only:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" follow checkout <run> --json
```

It is the wait's `repo` when that is an absolute path (a repository with no
remote); else the folder orq's store records for the run's team (the `repo`
of its `start` message, kept after the team closed), taken to its main
checkout, since a team's worktree holds the team's branch and may be gone,
and whose `origin` must be the wait's `repo`. With no `checkout` (exit 1, its
`problem` says why), a `trunk-dispatch` or `trunk-follow` fact of the owner's
that says where their repositories live may name it: the folder there whose
`git remote get-url origin` is the wait's `repo`. None found: the routing
fails, `no checkout of <repo> found: <the problem>`.

## 5. Notes a session could not send

A woken session that had no Slack tool, no channel, or a send that failed left
its note in its run (trunk 5b), and the poll lists those in `unsent`. With
Slack this tick, send each one, oldest first, as it is (the session wrote it
for the owner, in the owner's language), then record it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/assets/scripts/trunk.py" follow relayed <run> <the note's id>
```

A send that fails leaves the note in `unsent` for the next tick. With no Slack
this tick, say how many wait in the report and send nothing.

## 6. Report

A few lines for the scheduled task's own log: how many runs wait, each event
delivered and where (the session's key, told or opened), each note sent, each
failure with its why, and how many lines the poll logged. Nothing else is
written: the queue, the run records and `poll.log` are the record, all under
`state/trunk/`, git-ignored, so the routine commits nothing.

## The notes

One Slack message per run per tick, mobile-short, in the bundle's
`conversation_language`. Its first line is `trunk · <run>`; then what happened,
why when the run knows it, and what the run waits on now, from `run wait show
<run> --json` read after the poll (`wait.on`, or how the wait ended); then the
pull request's link, `https://github.com/<repo>/pull/<pr>`, when the wait has
both.

What goes in comes from the event's fields, the wait, and the trunk's own
`decide:` notes in the run. Never text someone else wrote: no pull request
title, comment, review body, check output, log line or orq message. A login, a
SHA (its first 7 characters), a count, a state, a time and a link are fine.

| event                  | the note says                                                                                                         |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `team-approved`        | the team's reviewer approved `<sha>` (round `<round>`) and the pull request is open; it waits on the approval of `<reviewers>` |
| `team-finished`        | the team finished with no approval; the run waits for the owner                                                       |
| `team-error`           | the team stopped on an error; `orq resume <team>` takes it on; the run still waits on it                              |
| `pr-changes-requested` | `<reviewer>` requested changes; the trunk pushes no fix; the run waits for the owner                                  |
| `pr-checks-failed`     | checks failed on `<head>`; the run waits for the owner                                                                |
| `pr-head-moved`        | the head moved to `<head>`, past the approved `<approved_sha>`: nothing merges on the old approval; it waits for the owner |
| `pr-merged`            | merged by `<by>`; why, when the run's last `decide:` note before it is about this merge (the trunk scheduled it); now it waits on the deploy, or it is live (the merge is the deploy), or the deploy is the owner's (`unknown`) |
| `pr-closed`            | closed with no merge by `<by>`; the run ended                                                                         |
| `deploy-succeeded`     | the deploy of `<sha>` finished well (`<signal>`); it waits out the health window, or it is live                        |
| `deploy-failed`        | the deploy of `<sha>` failed (`<signal>`), with the commit's checks, `https://github.com/<repo>/commit/<sha>/checks`; the run waits for the owner |
| `reminder`             | no change for 3 days; it waits on `<on>` since `<since>`, and what would move it                                     |
| `given-back`           | no change for 7 days; the run left the wait and the work is the owner's, with what it waited on                      |

**The delivery-failure note** (3.4): `trunk · <run>`, the event it could not
deliver (its type), why, and that it stays queued and the next tick retries.

## Rules

- The routine decides nothing: it never merges, cancels an auto-merge,
  deploys, holds or lifts a hold, ends a wait, or sets anything in a wait but
  `--session`. Each of those is the woken session's.
- A session is told only through `follow wake`, and only one opened for this
  run.
- Nothing of what a source read beyond the event's fields reaches a session or
  a note.
- Nothing is retried in the tick that saw it fail; the queue keeps it for the
  next one.
