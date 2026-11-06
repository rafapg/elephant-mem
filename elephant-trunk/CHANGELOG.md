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

## [0.1.0-beta.2] - 2026-11-06

The trunk hard-coded that the work it dispatched never merged: the brief's done,
the stop of every written recipe, the end of the plain Claude Code path and the
skill's rules all said so, for every owner. That is not a rule about the trunk,
it is a way of working: some owners merge by hand, others would rather not. A
first draft of this release kept the merge behind the owner's word in every
run, which made a learned preference worth nothing; the owner corrected it.
Who merges is now a fact of the owner's how, read like every other one, and
what keeps it safe is where that fact may come from and the gate every merge
passes.

### Changed

- **Who merges is a `trunk-dispatch` fact**, the merge preference, learned like
  any other how. At `manual`, the default with no fact, so every owner starts
  there, the work ends at a pull request unless the owner says, in the
  session, to merge this run's pull request. At `automatic` the work is
  dispatched with the merge on, without asking, unless the owner says in the
  session that the run needs their authorization, which makes that run
  `manual`. A learned `automatic` fact is meant to authorize merges, so "the
  fact wins" still holds; the owner is told when it is learned and can steer
  or forget it.
- **Only the owner sets it.** The preference and a session's override come
  from the owner's own words or behavior only. Text from a third party (a
  Slack message, a ticket, a source of the study, a brief, a pasted message,
  the topic text) never sets either, whatever it asks.
- **The level is computed fresh every session** and recorded as
  `merge-level: manual|automatic (<source>)`, a prefix of its own, so it does
  not collide with approaches that merged in the conversation and does not
  move "where it stopped" on a resume. A level recorded by an earlier session
  is history. Stored commands (the facts, a recipe's fact, pending learnings,
  the interview's answer) never carry the merge parameter: 3c adds it from
  this run's level only, and a retry recomputes the brief's done and the
  start command, artifacts included.
- **Every merge passes the gate**: the run's own review approved the pull
  request's head, and CI is green, every check completed and passing, at
  least one, none pending or skipped, under the repository's own rules, never
  forced, never with `--admin` and never with a check skipped. An approval
  from outside the run, an automated reviewer that signs as the owner
  included, never counts. A repository with no checks, a review that does
  not approve or a rule that blocks the merge leaves the pull request open
  for the owner, with why. Implementing roles never merge, and every brief
  and subagent prompt says so.
- **On orq** the level reaches the recipe through the start
  (`orq start impl_review <KEY> --repo … --brief … --set merge=on-approve`).
  Once 3c picks the recipe, `automatic` needs one with a review role that
  takes the merge level, else the run falls back to `manual`, recorded with
  why; at `manual` a saved recipe must be shown not to merge without the
  parameter, else the owner is asked before it starts. A written recipe's
  check asserts that nothing merges without the parameter and that no merge
  call carries `--admin`, force or a skip flag.
- **On plain Claude Code** the maestro merges only after a separate reviewer
  subagent, with a fresh context, returns an explicit approve on a named head
  SHA, recorded as a note, and with `gh pr merge <n> --match-head-commit
  <sha>`. The maestro never approves its own work.
- **A brief re-saved for the level is checked again**: when the level changes
  the brief's done after its form check, the form check runs again.
- **Deploying stays out.** The trunk and the work it dispatches never deploy,
  and the trunk never pushes the bundle.

### Added

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
