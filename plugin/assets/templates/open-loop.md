---
type: open-loop
# QUOTED free-text scalar — keep the quotes and escape every inner `"` as `\"`
# (or wrap in single quotes instead). Unquoted, a `: ` breaks the whole block and
# a ` #` silently truncates the value.
description: "<the action / commitment, one sentence>"
owner: []             # bundle-absolute entity links of who owns it
status: open          # open | done | dropped
entities: []          # other entities this loop concerns
sources: []           # source(s) where it was raised
opened: 2026-06-24
closed:               # date it was completed/dropped (set by close-loops)
closed_by:            # bundle-absolute source link that evidenced closure
# A loop can also end as `status: expired`: `decay` flips it there when the loop
# has gone quiet and `close-loops` already examined it, and inserts its own
# `expired: YYYY-MM-DD` line right under `status:`. Written by the routine only,
# so this template declares no field for it — never set it by hand.
tags: []
created: 2026-06-24
updated: 2026-06-24
timestamp: 2026-06-24
---

<Details of the commitment.>

**Closure signal:** <what a future source would have to show for this to count
as done — this is the section `close-loops` reads to close the loop
automatically, and the only one it reads.>
