# Changelog: elephant-trunk

Notable changes to the **`elephant-trunk`** plugin. `elephant-mem` has its own
[CHANGELOG](../CHANGELOG.md), and so does [`elephant-wiki`](../elephant-wiki/CHANGELOG.md);
the three plugins version independently, so a gap between their numbers is
expected and is not a sign any one of them is behind.

`elephant-trunk` has its own tag namespace, `trunk-v0.1.0-beta.N`, disjoint from
`elephant-mem`'s plain `v0.1.0-beta.N` and the wiki's `wiki-v0.1.0-beta.N`. As
with the wiki, nothing machine-reads a trunk tag: the marketplace serves `main`,
so a tag is a record rather than a delivery mechanism. A section is dated by the
day its tag is cut, which is the day it lands on `main`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-beta.3] - 2026-11-09

A trunk run ended where the pull request opened. The orq team closed, nothing
woke the trunk again, and the owner became the watcher: they noticed the
approval, decided the merge, ran or watched the deploy and checked that it went
live. The 0.1.0-beta.2 preference made this worse rather than better: a
two-valued `manual`/`automatic` setting decided every merge the same way for
every change, when the real decision is a judgment about this change (who
approved it, how critical it is, whether this is the hour, whether the owner
said anything for this run). This release makes a run keep going until the work
is live and healthy, or until it hands the work back with a reason, and the
trunk decides each merge from the owner's facts.

### Added

- **A waiting run.** A run has a `waiting` status and a structured wait: what it
  waits on (its team, the approval, the hour, the merge, the deploy, the health
  check, the owner), the repository, the branch, the orq team, the pull request,
  the approved SHA, the owning session, the deploy kind, the health rule and
  window, the hold-until, since when, the last state a source saw and whether a
  reminder went out. `trunk.py run wait set|show|list|end` writes and reads it
  and `run hold [--lift]` records the owner's hold; a wait that ended moves to
  `past_waits`. Every run that ends in a pull request or a branch waits the same
  way, on orq or on plain Claude Code. A run dispatched before this version does
  not wait, and the follow ignores it.
- **The follow.** `trunk.py follow poll` runs the sources and puts typed events
  on a local queue under `<bundle>/state/trunk/follow/`: the run's orq team (its
  `approved` message, read from orq's store with the SHA and the pull request;
  a team that finished with no approval), the state of the pull request on
  GitHub, the deploy GitHub records for the merge commit, and time (a held hour
  arrives, a scheduled merge's open window closes, a health window ends, a wait
  goes stale). An event carries structured fields only and enters the queue only
  when the state differs from what the run last saw, so the same state never
  enqueues twice and two overlapping ticks deliver one event once. `follow
  queue|take|mark|wake|checkout|unsent|relayed` are what the routine calls.
- **`/elephant-trunk:follow`**, the routine, fired hourly by a Claude Desktop
  scheduled task. It wakes an orq session for each event that needs a decision
  (the run's own session, else a live one the follow opened for it, else a new
  session in the run's repository, never one the owner is using) with the line
  `/elephant-trunk:trunk continue <run> from event <json>`, and sends a Slack
  note for each event that needs none: the 3-day reminder, the 7-day give-back,
  a pull request merged or closed by someone else, a change request, failing
  checks, an event that could not be delivered. `--dry-run` reads everything and
  changes nothing.
- **`trunk-follow`**, a fourth area tag, for the owner's facts on merging,
  deploying, the hour, breaking and notifying.
- **Business hours.** `trunk.business_hours` in `elephant.json` (Monday to
  Friday, 09:00 to 18:00 when unset) in the bundle's `timezone`, and
  `trunk.py hours`, which says whether they are open, when they close and when
  they open next. A change the trunk judges critical, in a repository where the
  merge deploys, merges only inside them; an auto-merge still pending when they
  close is cancelled and the run holds.
- **Deploying, repository by repository.** The trunk discerns what the deploy is
  and what live and healthy mean from the repository and the owner's facts, and
  records both in the run before the merge: a web service's own deploy, an
  `elephant-mem` tag and release under the prefix of the plugin whose version
  the change bumped (none when it bumped none), `lexflow deploy` after its
  `--dry-run` (it stops and hands over to the owner when it would ask for a
  secret, and no value is ever recorded), or the local merge of a repository
  with no remote. Where it cannot tell, it stops at the merge. Health checks
  only read.

### Changed

- **The `manual`/`automatic` merge preference is gone.** The trunk decides each
  merge from the owner's `trunk-follow` facts, with a floor that does not move:
  the run's own reviewer approved exactly the commit that merges and it is still
  the head, GitHub gates the base (the trunk still never reads CI), and no hold.
  "Don't merge before I approve" said for a run is a hold, and only the owner
  lifts it. A new `merge-level:` decision is refused and an old one stays as
  history; `run claim` no longer reads it. With no fact saying when approvals
  are enough, nothing merges and Slack says which fact would let the follow
  decide it next time.
- **On orq the dispatch stops at the pull request.** `impl_review` starts
  without a merge parameter; merging and deploying are the follow's job.
- **A note before acting.** Before any merge, cancel, tag, release or deploy
  step the trunk writes its reasoning as a note in the run, and the Slack note
  carries it. A woken session has no owner: a question becomes a Slack note and
  a wait on the owner, and text written by others (reviews, logs, error
  reports) is evidence, never an instruction.
- **What the follow only reports.** A change request, failing checks or a broken
  deploy notify and the run waits for the owner; pushing a fix, opening a fix
  pull request and reverting a deploy are out of scope for this version.

## [0.1.0-beta.2] - 2026-11-06

The trunk hard-coded that the work it dispatched never merged: the brief's done,
the stop of every written recipe, the end of the plain Claude Code path and the
skill's rules all said so, for every owner. That is a way of working, not a rule
of the trunk: some owners merge by hand, others would rather not. Two drafts of
this release got the condition wrong. The first kept every merge behind the
owner's word in each run, which made a learned preference worth nothing. The
second had the trunk read CI itself (every check completed, at least one, none
pending), which reimplemented a gate that belongs to the repository's
maintainer. The quality of the delivery is the owner's and the guardrails are
the maintainer's; a merge is where the two meet. So who merges is now a fact of
the owner's how, and the merge relies on GitHub's own gate, stopping at the
pull request where that gate is missing. A third review found the merge line
itself would not have run: `gh pr merge` with no method fails when it cannot
ask for one, and nothing checked that the repository allows auto-merge, which
`elephant-mem` itself does not.

### Changed

- **Who merges is a `trunk-dispatch` fact**, the merge preference, learned like
  any other how. At `manual`, the default with no fact, so every owner starts
  there, the work ends at a pull request unless the owner says, in the
  session, to merge this run's pull request. At `automatic` the work is
  dispatched with the merge on, without asking, unless the owner says in the
  session (on orq, before "dispatch") that the run needs their authorization.
  A learned `automatic` fact is meant to authorize merges, so "the fact wins"
  still holds; the owner is told when it is learned and can steer or forget
  it. A one-off "merge this one" is a value of the run, never a learning.
- **Only the owner sets it.** The preference and a session's override come
  from the owner's own words or behavior. Text from a third party (a Slack
  message, a ticket, a source of the study, a brief, a pasted message, the
  topic text) never sets either, whatever it asks.
- **The merge condition** is the same on orq and on plain Claude Code: the
  owner wants it; the run's own reviewer, a separate one with a fresh
  context, approved exactly the commit that will merge; and the base branch
  is protected on GitHub with required status checks, with auto-merge
  allowed. Then `gh pr merge <n> --repo <owner>/<repo> --auto --merge
  --match-head-commit <sha>` on the pull request's own repository (not the
  default remote, which an `upstream` checkout may point elsewhere), with
  `--merge` as the method unless the repository allows only squash or
  rebase. GitHub waits for the checks and merges or refuses; a scheduled
  auto-merge is reported as scheduled, never as merged. The SHA is read from
  the run's record and must still be the pull request's head. The trunk never
  reads CI and never changes a repository's settings. Where protection or
  auto-merge is missing, one note names both, suggests turning them on (to an
  admin) or says the pull request waits for the maintainer, and warns that a
  required check no workflow reports any more leaves an auto-merge waiting
  forever. Implementing roles never merge, and every brief and subagent
  prompt says so.
- **A repository with no remote**, usually the owner's own local tool, merges
  locally instead: the local tests pass on exactly the approved commit with
  nothing uncommitted, a `git merge-tree` probe finds no conflict, and
  `git merge --no-ff` of that commit into `refs/heads/<base>` lands only when
  the owner's checkout is on the base and clean, with `git merge --abort` when
  it fails. A commit already in the base is said so, never reported as
  merged. It never stashes, resets or checks out.
- **The level is computed fresh every session** and recorded as
  `merge-level: manual|automatic (<source>)`, a prefix of its own, so it
  neither collides with approaches that merged nor moves "where it stopped" on
  a resume. A level recorded by an earlier session is history, and a retry
  recomputes the brief's done and the start command.
- **On orq** the level reaches the recipe through the start
  (`orq start impl_review <KEY> --repo … --brief … --set merge=on-approve`).
  Once 3c picks the recipe, `automatic` needs one with a review role that
  takes the level, else the run falls back to `manual`, recorded with why; at
  `manual` a saved recipe must be shown not to merge without the parameter,
  else the owner is asked. A written recipe's check asserts that nothing
  merges without the parameter, that a merge is only `gh pr merge --auto
  --match-head-commit <the reviewed sha>` after a protection check, and that
  no merge call carries `--admin`, force or a skip flag. At `manual`, a
  "merge it" after the team opened the pull request goes through the same
  three conditions: the recipe now pins the builder's commit and asks the
  reviewer for its SHA at every level, and the trunk merges only when the
  run's record holds an approved SHA that is still the head. A run started
  before that change has none, so it is handed to the owner, with why.
- **A merge in a repository that deploys on push is said to be a deploy**, at
  3d, at the confirmation and in the interview about who merges.
- **Deploying stays out.** The trunk and the work it dispatches never deploy,
  and the trunk never pushes the bundle.

### Added

- **`trunk.py facts --json` says where each fact came from**: an `origin` of
  `owner`, `other` or `unknown`, and the `channels` it read. A fact cites its
  sources, and `capture` files the owner's own Claude Code conversation with
  `channel: claude-code:<workspace>`; the catch-up and ingest stamp the feed
  (`slack:...`, `meeting`). Only an `owner` fact is read for the merge
  preference, so a `trunk-dispatch` fact the catch-up filed from a Slack
  thread can never turn merges on.
- **`trunk.py` refuses a stored merge parameter**: `recipe draft --command`
  and `run set recipe` refuse a command carrying one in any spelling
  (`--set merge=…`, `--set=merge=…`, `--merge`, `MERGE:…`); `run claim` via
  orq refuses a command whose merge parameter disagrees with the run's last
  `merge-level:` decision, and any merge parameter when none is recorded;
  `run set decision` refuses a `merge-level:` decision in another form. A
  level recorded before the run's last start or its last `dispatch:` decision
  is another session's and no longer passes a claim, and the refusals say the
  owner states the level in this session rather than how to add the
  parameter. A bare `merge` that is another option's value (`--branch merge`)
  is not read as one, and a pending learning or a learning carrying a merge
  parameter is refused too.
- **The interview asks who merges**: "do you want to merge dispatched work
  yourself, or should it merge on its own once the review approves and CI is
  green?", captured as the merge preference. The readers of past sessions may
  surface it too, from the owner's own messages only.

## [0.1.0-beta.1] - 2026-11-05

The owner already took topics to dispatched work by hand, and the middle of it
worked: studying a topic with their memory and converging on an approach in a
conversation. Both ends hurt. At the start they had to spell out how a topic
should be studied, every time; at the end, on orq, they had to configure the
recipe and spawn the sessions themselves. elephant-trunk is a new plugin beside
`elephant-mem` and `elephant-wiki`, outside the core, that takes a one-line
topic to dispatched work and reads every *how* from the owner's own memory.

### Added

- **The plugin itself**, listed in the marketplace as `elephant-trunk`, with its
  own version and this CHANGELOG. Its mechanics live in
  `assets/scripts/trunk.py`, pure stdlib, run from the plugin and never copied
  into the bundle, so `elephant-update` has no stale copy to miss.
- **The bundle is found the way `elephant-wiki` finds it**: `--bundle`, then
  `ELEPHANT_BUNDLE`, then the machine pointer. A bundle that cannot be found
  stops with the wiki's own guidance, word for word, and so does a machine
  pointer whose `bundle_path` is not a non-empty string.
- **`trunk.tag` in `elephant.json`** names the how-I-work tag the trunk reads,
  so a bundle whose facts already carry another tag (`como-trabalhar`, say) is
  read as it is. With no `trunk.tag` the trunk reads `how-i-work` and says how
  to set another. An `elephant.json` that is present but unusable (it does not
  parse, is not an object, or carries a `trunk.tag` that is not a non-empty
  string) stops `trunk.py facts`, `--forgotten` included, with exit 1 and the
  problem on stderr and in `--json`, and nothing is read: the default tag would
  list none of the owner's facts, send the skill into first use and capture the
  answers under a tag that goes unread once the file is fixed. `learning
  forget` and `learning steer` stop the same way, naming the problem, and
  change nothing. The skill stops there and never goes to first use from it. `trunk.py config` stays lenient,
  printing the default it falls back to and why, and `--json` prints what it
  resolved as one object for the skill.
- **`trunk.py facts` reads the owner's how**: the active facts carrying the
  how-I-work tag plus one of `trunk-study`, `trunk-dispatch` or `trunk-recipe`,
  straight from `knowledge/manifest.jsonl` and never through `query`, matching a
  fact on the manifest's own fields alone: its `type` is `fact`, its status is
  `active` (a missing one counts as active), and its tags match exactly. `--area`
  narrows it to one step. Matching stays exact, but `--json` also carries
  `near_misses`: the active facts that would match under another case
  (`Como-Trabalhar`) or once a comma-joined tag string (`tags: a, b` written
  without brackets, one string in the manifest) is split, narrowed by `--area`
  like the facts and counted on stderr. A near miss is never read as the
  owner's how; the skill says how many facts nearly carry the tag and asks
  whether to fix their tags before it starts a first use, so a mistyped tag
  does not send the owner through the interview again. A bundle with no such fact gets an empty list and a note, and one
  whose manifest was never built stops and says to rebuild it rather than
  report that the owner has no how.
- **`trunk.py run` keeps the run record** in `<bundle>/state/trunk/runs/<name>.json`,
  one JSON file per run: the topic, the study, the approaches, the decisions,
  the brief, the recipe and every dispatch attempt. `run new` starts one,
  `run set` continues it one field at a time, `run show` reads it back and
  `run list` puts the most recently continued first (`--open` for the runs not
  dispatched yet). A record can hold whatever the conversation touched and
  `ingest` commits with `git add -A`, so before every write the script makes
  sure `state/trunk/` is git-ignored in the bundle, and in a git bundle asks git
  itself: a rule that re-includes the path, or a record already tracked, refuses
  the write instead of leaving raw content for the next commit. `run claim`
  takes a run from `open` to `starting` before its dispatch command runs,
  under the record's lock (an empty file beside it, created exclusively), and
  refuses a run that is `starting` or `dispatched`: of six concurrent claims on
  one run, exactly one won in every round. Every write of a record takes the
  same lock, and a lock left by a killed process stops the write after ten
  seconds, naming the file. `run dispatch` ends the claim and records only a
  run that is `starting`, so a session that skipped the claim cannot race one
  that made it; a `--command` that is not the claimed one is refused via orq,
  whose command runs exactly as claimed, and recorded with a warning on stderr
  via claude-code. A start that ran makes the run `dispatched`, and one
  recorded with `--error` is kept with its error and reopens the run for a
  retry to claim. A run that was dispatched
  refuses a second claim or dispatch and says what ran and where. A missing or
  unreadable record says so and offers to start over from the topic.
- **The `trunk` skill, study and converse** (`/elephant-trunk:trunk <topic>`).
  It loads the owner's how with `trunk.py facts`, reads each fact whole and
  says which ones apply to the topic, studies it through elephant-mem's own
  skills and the repositories involved, presents approaches in the form the
  `trunk-study` facts give, and converges with the owner until they say to
  dispatch, writing the study, the approaches and each decision to the run
  record as they happen, so an owner who leaves mid-conversation leaves a
  record to continue from. The skill holds no owner's way of working: a step
  with no fact asks the owner instead of falling back on a habit, two facts
  that contradict each other are both shown and the owner picks, and a how the
  owner states is captured with its tags spelled out and then looked up with
  `trunk.py facts`, because `capture` checks no tag.
- **The `trunk` skill, dispatch and follow.** Once the owner says to dispatch,
  the trunk writes the brief from the run record in the form the owner's
  `trunk-dispatch` facts give (an approved bb spec, for an orq recipe that runs
  `/bb:implement`), filters it for content not meant to travel before the owner
  sees it, and dispatches nothing when the brief lacks that form, saying what
  is missing. It picks a saved recipe from the `trunk-recipe` facts, shows the
  brief, the recipe and the exact command, claims the run, and only once the
  claim succeeded starts the work, never more than once: on orq or, on plain
  Claude Code, in the same session as a maestro with subagents. When orq is
  the way but its tooling is not on the machine, it says so and offers plain
  Claude Code. A failed start is recorded with its error and the run is open
  again. It then confirms the work is running, runs `ingest` over the record,
  and captures what it learned about how the owner works without asking,
  reporting each learning with its link. Right after ingest's commit,
  `trunk.py run ingested` records the ingest, and refuses it when that commit
  touched `state/trunk/`, added a byte-for-byte copy of a file from there, or
  added lines carrying the record's `"created": "<timestamp>"` key, as JSON
  writes it, together with its name to any other file, which finds a copy with
  its final newline dropped, reserialized as compact JSON or changed since by
  `run set`; a fact that only names the run, or a source note that names it
  and copies the timestamp as its `occurred`, is not taken for a copy. The commit's diff is read as UTF-8
  with undecodable bytes replaced, so a CSV in Latin-1 or cp1252 that
  `git add -A` carried along does not stop the check. Only that one commit is
  read, and a partial copy (the study pasted into a source) is not found. `run set <name>
  learning` keeps what was learned in the record. A learning is kept as
  `pending` in the record the moment it surfaces (`run set <name> pending`),
  and `run set ... learning --pending <n>` (or a `note`, when it is set aside)
  settles it, refusing an entry already settled or never recorded, while
  `run show` lists what is still pending; so a run that stops before its last step, on a failed start or
  an owner who leaves, loses nothing it learned: the next session that
  continues the run captures what is still pending. What is kept is only the
  how, with the run's own values (a client, a ticket, a repository) as
  placeholders, and an entry that still carries anything of the topic, of a
  client or of a session is settled with a note and never captured, since the
  session that captures it may never have seen the conversation it came from.
- **The `trunk` skill, a recipe when none fits.** When no saved recipe fits
  work bound for orq, the trunk writes one from the closest saved recipe and
  the tooling's own documentation, carrying the roles and stop conditions of
  that kind of work and nothing of the topic, with a check that drives every
  role to its end. `trunk.py recipe draft` keeps it beside the run record,
  git-ignored, and records its hash; `recipe checked` records the check against
  that hash, so a draft edited afterwards is refused, and a failed check keeps
  the recipe and the failure while nothing is dispatched. The recipe is shown
  whole with the dispatch, and `recipe save` copies it into the tooling's
  recipe directory only once it passed, never replacing a recipe already
  there: `orq resume` reloads a team's recipe from the path it started with,
  so an edited one would break the resume of every team started from it. After
  the start it is saved with a `trunk-recipe` fact (`recipe fact` links it),
  and `run dispatch` refuses a written recipe that was not checked and saved.
- **The `trunk` skill, continuing a run.** A new session saw nothing of the
  one that left a run, so it continues from the record alone
  (`/elephant-trunk:trunk continue <name>`). A run named, even in part or by
  its topic, is read back; with none named, the open runs are listed most
  recent first and the owner picks, and `run list --json` names the
  records it could not read so the list can say which were left out. The trunk
  says where the run stopped, reading one timeline across decisions, notes,
  attempts and the recipe's check, and picks up there: the study, the
  approaches, the conversation, or the start that failed. A `dispatch`
  recorded by an earlier session starts nothing; a retry waits for the owner's
  word in this one. A run left `starting`, claimed and never recorded, never
  has its command run again to find out whether it ran: the trunk checks with
  what the `trunk-dispatch` facts name for it, or asks the owner, records the
  dispatch or the failed start accordingly, and leaves the run `starting`,
  starting nothing, when it cannot tell. A run
  already dispatched is shown, with what was dispatched, where and what
  followed, and is never dispatched again; an ingest that never ran is offered.
  A missing or unreadable record is said so, and the trunk offers to start over
  from the topic without deleting the file.
- **The `trunk` skill, steering and forgetting a learning.** Learning is
  autonomous, so the owner needed a way to correct what the trunk took from
  them. `trunk.py learning forget <link>` sets the fact `deprecated` and
  `learning steer <link> --to <link>` sets it `superseded`, linked both ways to
  the fact the owner captured in its place: elephant-mem's own statuses, so
  `query` and `briefing` stop presenting it as current too, and nothing is
  deleted. The script then rebuilds the bundle's index and checks that the
  trunk no longer reads it, since the manifest is all the trunk reads and a
  stale one would keep it read; with no `build-index.py` it changes nothing.
  It touches only the trunk's own how: an active fact is a learning exactly
  when `facts` lists it, read from the same manifest by the same code, and a
  fact already forgotten or steered, which the manifest no longer carries, is
  judged by the tags in its frontmatter, read in the shapes `build-index`
  accepts (a flow list wrapped over lines, a block list with a comment between
  its items), so `facts --forgotten` and a second `forget` agree. Any other
  fact is refused. `facts --forgotten` lists what was forgotten
  or steered, read from the fact files because the manifest keeps active facts
  only, so the next run does not learn it again, and `--run` records each
  steer in the run, where `run show` marks the learning.
- **The `trunk` skill, the interview.** A bundle with no how-I-work fact for
  the trunk left it nothing to follow, and guessing would have put a habit of
  the skill's own in the owner's place. The trunk now offers an interview:
  seven questions, the same for every owner, on how a topic is studied, how
  work is dispatched and how it is split into sessions, asked one area at a
  time and never with a suggested answer. A skipped question captures nothing,
  so its step asks when it comes; an answer that holds only for this topic is
  used and not kept; a credential in an answer is left out and the fact says
  where it lives. Nothing is captured until the owner confirms a read-back of
  one fact per how, each with its area tag, so any one can be steered or
  forgotten alone later; each is checked with `facts --area`, kept in the run
  as a learning and reported with its link. What the owner forgot earlier is
  never offered back as an answer.
- **The `trunk` skill, reading past sessions.** The interview asked the owner
  to describe a way of working their own sessions already showed. On first use
  the trunk now offers to read them instead, and estimates first:
  `trunk.py sessions list` finds every session's transcript, picks the most
  recent ones holding a message of the owner's (30 by default; sessions run by
  a script or a schedule are passed over), and reports their raw size, the
  tokens left after extraction and the small-model readers it takes. On this
  machine the 30 most recent were 96 MB raw, about 24M tokens, and about 67k
  tokens after extraction, two readers. Nothing is read before the owner says
  so; a skip goes to the interview. `sessions extract` hands a reader the
  owner's own messages and the names of what each session ran (a skill, a
  subagent, a program, never its arguments), with tool output, the assistant's
  text, system-injected turns and credential-shaped strings left out, so the
  raw transcripts never enter the conversation. A `!cmd` the owner ran in a
  session's bash mode is reduced to `ran <program>`, or to nothing when it ran
  only plumbing, and its output is dropped, so a `!cat .env` hands the reader
  none of the file; a program name carries much less than its arguments,
  though not nothing (`acme-bank-migrate.sh`). The redaction cuts a value keyed
  by a credential word (`token`, `secret`, `password`, `pwd`, `senha`, `chave`,
  `pass`, `passcode`, `passkey` and `auth`, in a key of any case, camel-cased
  or glued after a prefix, as in `DB_PASS`, `PGPASS`, `passwordConfirm`,
  `BasicAuth` and `Authorization`, but never before a lowercase letter or
  inside another word, so "próximo passo:", `passwordless:`, `bypass:` and
  `OAuth:` keep their text while `ProtoAuth:` does not, and a `_key` suffix other than a table's, as
  `primary_key`) together with its HTTP scheme (`Authorization: Token x`), an
  unquoted password to the end of its line (`password: correct horse battery
  staple`), the value glued to the `-p` of `mysql`, its tools (`mysqldump`,
  `mysqladmin`, `mysqlsh` and the rest), `mariadb` or `mariadb-dump`, in any
  case, a secret named in prose ("the token is x",
  "a chave da API é x"), URL credentials with or without a user (`redis://:pw@host`), and vendor shapes
  such as PEM and PGP private keys, AWS, GitHub, GitLab and Slack tokens, JWTs
  and Bearer values. CPF, CNPJ, e-mail and phone are left to the reader's
  instruction. Readers on the small model
  return statements of how the owner works only, per area; the trunk filters
  them again, sets aside what the owner forgot, shows a panorama with how many
  sessions each how showed in, offers the interview's questions for an area
  with nothing, and captures only what the owner confirms, as the interview
  does.
- **Docs.** The README presents the trunk beside the memory and the wiki (a
  badge, a section, its own tag namespace), and `docs/configuration.md` gains a
  `trunk` section for `trunk.tag`, its default and its fallbacks. The trunk
  needs no CI line of its own beyond `tests/test_trunk.py`, listed as its own
  step; `trunk.py sessions` is documented as needing no bundle.
