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
