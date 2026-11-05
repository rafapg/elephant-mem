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

## [0.1.0-beta.1] - Unreleased

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
  stops with the wiki's own guidance, word for word.
- **`trunk.tag` in `elephant.json`** names the how-I-work tag the trunk reads,
  so a bundle whose facts already carry another tag (`como-trabalhar`, say) is
  read as it is. With no `trunk.tag` the trunk reads `how-i-work` and says how
  to set another; a value that is not a non-empty string falls back to the same
  default and says why. `trunk.py config` prints what it resolved, and
  `--json` prints it as one object for the skill.
- **`trunk.py facts` reads the owner's how**: the active facts carrying the
  how-I-work tag plus one of `trunk-study`, `trunk-dispatch` or `trunk-recipe`,
  straight from `knowledge/manifest.jsonl` and never through `query`, with the
  same matching rules as the `como-trabalhar` reader `post-produto-slack`
  already uses, so the two cannot disagree about one fact. `--area` narrows it to
  one step. A bundle with no such fact gets an empty list and a note, and one
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
  the write instead of leaving raw content for the next commit. A failed
  dispatch is kept with its error and the run stays open; a run that was
  dispatched refuses a second dispatch and says what ran and where. A missing or
  unreadable record says so and offers to start over from the topic.
