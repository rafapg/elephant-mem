#!/usr/bin/env python3
"""Faceted search over `knowledge/manifest.jsonl`, inside a fixed byte budget.

`query` used to pay most of its context to navigate before it read one fact it
would cite: the whole entity catalog (`entities/index.md`, 155 KB on a mature
bundle), then one hub per entity, ~208 KB per query (median) before any fact
body, and five times that once the archives were followed. This script replaces
that navigation. It filters the manifest (active facts and open loops), orders
what matched newest first, prints one page of `desc` lines that fits the
budget, and ends with the facets of the **whole matched set** so the next call
can refine instead of descending further.

    python3 scripts/search.py --entity jane
    python3 scripts/search.py --entity billing-rewrite --entity jane-doe
    python3 scripts/search.py --entity billing-rewrite --entity jane --any
    python3 scripts/search.py --entity acme --text "export fix" --since 2026-06-01
    python3 scripts/search.py --entity acme --page 2

**The budget is the window.** There is no default date cutoff: rows are ordered
newest first and the budget cuts. The footer always says where the cut fell and
how many matches lie behind it, so nothing leaves an answer without the output
saying how many and from when. `--since`/`--until` narrow explicitly.

**Filters.** `--entity` repeated is an intersection; with `--any` it is a union,
interleaved round-robin across the named entities so each gets its share of
the page (each entity's own list ordered by how many of the named entities a
row carries, then newest first). `--tag` repeated is an intersection. `--text`
matches every word, case- and accent-folded, as a substring of `desc`.
`--since`/`--until` bound `occurred`, inclusive. `--status` is `active` (facts)
or `open` (loops); both by default. `--as-of` is "today" for the ordering.

**Names resolve here, and are never guessed between.** `--entity` takes a slug,
an entity path, or a name as written, matched against `entities/roster.tsv`
(slug, title, aliases) case- and accent-folded, in tiers: exact, then a whole
word of a name, then `difflib` similarity. The first tier with any match
decides. Exactly one entity there resolves (a similarity match says so in the
header; an exact match that hides other whole-word matches names them). More
than one prints the candidates and no rows, exit 3. None at all, or no roster,
exit 4. Usage errors keep argparse's 2.

**Read-only, and stdout is the product.** Nothing is written, ever. The last
line is `bytes: <n>`, the exact size of what was printed, which the caller adds
to the `--bytes` it hands `recall.py log`. The functions take their paths as
parameters, so `tests/eval_recall.py` imports this file and replays it against
another bundle. Pure stdlib, Python 3.10+.
"""
import argparse
import difflib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

# Windows consoles default to a legacy codepage (cp1252); force UTF-8 on the
# standard streams so printing non-ASCII content (accented names, em dashes)
# doesn't raise UnicodeEncodeError. No-op on POSIX / when already UTF-8. The
# newline is pinned too: `bytes:` counts "\n" as one byte, and a "\r\n"
# translation would make the count a lie on Windows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BUNDLE = Path(__file__).resolve().parent.parent

# A bundle script lives at <bundle>/scripts/, so it resolves its bundle as the
# parent of its own directory. Run from the plugin checkout that parent is
# `plugin/assets/`. This script writes nothing, but it would read an empty
# assets tree and answer "0 matches" with a straight face. Refuse, like every
# bundle script. Guarded on __main__ so the replay can import it.
if __name__ == "__main__" and BUNDLE.name == "assets" and (
    BUNDLE.parent / ".claude-plugin"
).is_dir():
    sys.exit(
        "refusing to run inside the elephant-mem plugin checkout.\n"
        "This script expects to live at <bundle>/scripts/, so it resolves its\n"
        "bundle as the parent of its own directory. Run from the checkout that\n"
        "is plugin/assets/, and it would search the assets the marketplace\n"
        "publishes instead of a bundle. Run it from an installed bundle instead."
    )

DEFAULT_BUDGET_KB = 32
KB = 1024
FOOTER_CAP = 2 * KB
TOP_ENTITIES = 10
TOP_TAGS = 8
MONTHS = 12
# difflib's ratio at or above which a name counts as a similarity match. Set on
# a real roster of 773 entities: a one-letter typo of an eight-letter name
# scores 0.93, a nickname spelled two ways 0.77 to 0.83, and an unrelated short
# name sharing four letters 0.73.
SIMILARITY_CUTOFF = 0.72
# How far below the best similarity a match still counts as the same tier.
SIMILARITY_MARGIN = 0.15

EXIT_AMBIGUOUS = 3
EXIT_NOT_FOUND = 4
EXIT_NO_MANIFEST = 1

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- reading -----------------------------------------------------------------


def fold(s):
    """Case- and accent-folded text: `Conceição` and `conceicao` compare equal."""
    decomposed = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def words(s):
    """The folded words of a name, split on anything that is not a letter or digit."""
    return [w for w in re.split(r"[^0-9a-z]+", fold(s)) if w]


def slug_of(link):
    """`/entities/person/jane-doe.md` → `jane-doe`."""
    s = str(link or "").strip().replace("\\", "/")
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    if s.endswith(".md"):
        s = s[:-3]
    return s.strip().lower()


def load_manifest(knowledge):
    """`(rows, unparseable)` from `<knowledge>/manifest.jsonl`.

    Raises FileNotFoundError when the manifest is absent: there is nothing to
    search, and the fix (`build-index.py`) belongs in front of the caller. A
    line that is not a JSON object carrying a `path` is skipped and counted, so
    one bad line costs one row rather than the search.
    """
    path = Path(knowledge) / "manifest.jsonl"
    rows, bad = [], 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                bad += 1
                continue
            rows.append(row)
    return rows, bad


def load_roster(knowledge):
    """The roster's rows as dicts, or None when `entities/roster.tsv` is absent."""
    path = Path(knowledge) / "entities" / "roster.tsv"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    out = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        cols += [""] * (4 - len(cols))
        slug = cols[0].strip().lower()
        if not slug:
            continue
        out.append({
            "slug": slug,
            "kind": cols[1].strip(),
            "title": cols[2].strip(),
            "aliases": [a.strip() for a in cols[3].split(",") if a.strip()],
        })
    return out


def owner_slug(bundle):
    """`elephant.json` → `owner.slug`, or None. Never raises."""
    try:
        data = json.loads((Path(bundle) / "elephant.json").read_text(encoding="utf-8"))
        owner = data.get("owner") if isinstance(data, dict) else None
        if isinstance(owner, dict) and isinstance(owner.get("slug"), str):
            return slug_of(owner["slug"]) or None
    except Exception:  # noqa: BLE001 — the owner only trims one facet
        pass
    return None


# --- names -------------------------------------------------------------------


class Resolution:
    """What one `--entity` value became.

    `slug` is set when it resolved. `how` is `exact`, `path`, `word` or
    `similarity`. `others` are the whole-word matches an exact match hid.
    `candidates` is set, with `slug` None, when the deciding tier held several.
    """

    def __init__(self, raw, slug=None, how=None, others=(), candidates=(), tier=None):
        self.raw = raw
        self.slug = slug
        self.how = how
        self.others = list(others)
        self.candidates = list(candidates)
        self.tier = tier

    @property
    def ok(self):
        return self.slug is not None

    def note(self):
        """The header's word on how this name resolved, or None when it is plain."""
        if self.how == "similarity":
            return f"{self.raw} → {self.slug}, by similarity"
        if self.others:
            shown = ", ".join(e["slug"] for e in self.others[:5])
            more = ", …" if len(self.others) > 5 else ""
            return f"{self.raw} → {self.slug}; also matches: {shown}{more}"
        if self.how == "word":
            return f"{self.raw} → {self.slug}"
        return None


def _names(entry):
    """Every spelling an entity answers to, as written."""
    return [entry["slug"].replace("-", " "), entry["title"]] + entry["aliases"]


def resolve(raw, roster):
    """Resolve one `--entity` value. Never guesses between candidates.

    An entity path (`/entities/person/x.md`) is explicit and resolves to its
    slug without the roster. Anything else needs the roster: exact (the folded
    value equals a folded slug, title or alias), then a whole word (the value's
    words appear, contiguous, among a name's words), then difflib similarity
    against each name and each word of it. The first tier with a match decides.
    """
    value = str(raw or "").strip()
    if value.endswith(".md") and "/" in value.replace("\\", "/"):
        return Resolution(raw, slug=slug_of(value), how="path")
    if roster is None:
        return Resolution(raw, tier="no-roster")
    target = " ".join(fold(value).split())
    target_words = words(value)
    target_slugish = "-".join(target_words)
    if not target_words:
        return Resolution(raw, tier="none")

    exact, word_hits, scored = [], [], []
    for entry in roster:
        names = _names(entry)
        if entry["slug"] == target_slugish or any(" ".join(fold(n).split()) == target
                                                  for n in names):
            exact.append(entry)
            continue
        n = len(target_words)
        if any(
            words(name)[i:i + n] == target_words
            for name in names
            for i in range(max(len(words(name)) - n + 1, 0))
        ):
            word_hits.append(entry)
            continue
        best = 0.0
        for name in names:
            folded = " ".join(words(name))
            if not folded:
                continue
            best = max(best, difflib.SequenceMatcher(None, " ".join(target_words), folded).ratio())
            if n == 1:
                for w in words(name):
                    best = max(best, difflib.SequenceMatcher(None, target_words[0], w).ratio())
        if best >= SIMILARITY_CUTOFF:
            scored.append((best, entry))

    if len(exact) == 1:
        return Resolution(raw, slug=exact[0]["slug"], how="exact", others=word_hits)
    if len(exact) > 1:
        return Resolution(raw, candidates=exact, tier="exact")
    if len(word_hits) == 1:
        return Resolution(raw, slug=word_hits[0]["slug"], how="word")
    if len(word_hits) > 1:
        return Resolution(raw, candidates=word_hits, tier="whole word")
    scored.sort(key=lambda t: (-t[0], t[1]["slug"]))
    # The similarity tier is the matches near the best one, not every match
    # over the cutoff: a typo can reach its entity at 0.93 and an unrelated
    # short name at 0.73, and calling that a tie would make a plain typo
    # unresolvable. Within the margin it is a tie, and a tie is never guessed.
    if scored:
        scored = [t for t in scored if t[0] >= scored[0][0] - SIMILARITY_MARGIN]
    if len(scored) == 1:
        return Resolution(raw, slug=scored[0][1]["slug"], how="similarity")
    if len(scored) > 1:
        return Resolution(raw, candidates=[e for _, e in scored], tier="similarity")
    return Resolution(raw, tier="none")


# --- filtering and ordering --------------------------------------------------


def row_slugs(row):
    """The entities a row is about: `entities`, plus a loop's `owner`/`owed_to`.

    An "owed to me" loop can name its counterpart only in `owner`, so on
    `entities` alone it would be invisible to a search for that person.
    """
    out = []
    for key in ("entities", "owner", "owed_to"):
        value = row.get(key)
        for link in value if isinstance(value, list) else ([value] if value else []):
            s = slug_of(link)
            if s and s not in out:
                out.append(s)
    return out


def row_tags(row):
    value = row.get("tags")
    return [str(t) for t in value] if isinstance(value, list) else []


def occurred(row):
    """The row's `occurred` as `YYYY-MM-DD`, or "" when it carries none usable."""
    value = str(row.get("occurred") or "")[:10]
    return value if DAY.match(value) else ""


def effective(row, today):
    """The date the ordering uses: a future `occurred` sorts as today."""
    d = occurred(row)
    return today if d > today else d


class Query:
    def __init__(self, entities=(), any_mode=False, tags=(), text=None,
                 since=None, until=None, status=None, as_of=None):
        self.entities = [e for e in entities if e]
        self.any_mode = bool(any_mode)
        self.tags = [t for t in tags if t]
        self.text = text or None
        self.since = since
        self.until = until
        self.status = status
        self.as_of = as_of or date.today().isoformat()

    def filters(self):
        """Each active filter as `(label, predicate)`, for matching and for E9."""
        out = []
        if self.entities and not self.any_mode:
            for slug in self.entities:
                out.append((f"--entity {slug}", lambda r, s=slug: s in row_slugs(r)))
        elif self.entities:
            wanted = set(self.entities)
            out.append(("--entity … --any", lambda r: bool(wanted & set(row_slugs(r)))))
        for tag in self.tags:
            out.append((f"--tag {tag}", lambda r, t=tag: t in row_tags(r)))
        if self.text:
            needles = [fold(w) for w in self.text.split() if w.strip()]
            out.append((f"--text {self.text}",
                        lambda r: all(n in fold(r.get("desc", "")) for n in needles)))
        if self.since:
            out.append((f"--since {self.since}", lambda r: occurred(r) >= self.since))
        if self.until:
            out.append((f"--until {self.until}",
                        lambda r: occurred(r) != "" and occurred(r) <= self.until))
        if self.status:
            out.append((f"--status {self.status}",
                        lambda r: str(r.get("status", "")) == self.status))
        return out


def match(rows, query):
    preds = [p for _, p in query.filters()]
    return [r for r in rows if all(p(r) for p in preds)]


def emptied_by(rows, query):
    """The one filter that, removed alone, would leave matches. None otherwise."""
    filters = query.filters()
    culprits = []
    for i, (label, _) in enumerate(filters):
        rest = [p for j, (_, p) in enumerate(filters) if j != i]
        if any(all(p(r) for p in rest) for r in rows):
            culprits.append(label)
    return culprits[0] if len(culprits) == 1 else None


def order(matched, query):
    """The one place the ranking lives.

    Newest first by effective date, ties on `path` so pages are deterministic.
    With `--any`, a round-robin across the named entities: each entity's list
    ordered by how many of the named entities a row carries, then newest first,
    and a row already placed is skipped when its turn comes round again.
    """
    today = query.as_of

    def by_newest(rows, first=None):
        # Two stable passes: path ascending, then the real key descending, so
        # rows equal on the key keep their path order. An undated row has ""
        # and lands last.
        rows = sorted(rows, key=lambda r: r["path"])
        return sorted(rows, key=lambda r: ((first(r),) if first else ())
                      + (effective(r, today),), reverse=True)

    if not (query.any_mode and len(query.entities) > 1):
        return by_newest(matched)
    named = set(query.entities)
    lists = [
        by_newest([r for r in matched if slug in row_slugs(r)],
                  first=lambda r: len(named & set(row_slugs(r))))
        for slug in query.entities
    ]
    out, seen, cursors = [], set(), [0] * len(lists)
    while any(c < len(lst) for c, lst in zip(cursors, lists)):
        for i, lst in enumerate(lists):
            while cursors[i] < len(lst) and lst[cursors[i]]["path"] in seen:
                cursors[i] += 1
            if cursors[i] < len(lst):
                row = lst[cursors[i]]
                cursors[i] += 1
                seen.add(row["path"])
                out.append(row)
    return out


# --- rendering ---------------------------------------------------------------


def entry_text(row):
    when = occurred(row) or str(row.get("occurred") or "")[:10] or "----------"
    desc = " ".join(str(row.get("desc", "")).split())
    return f"{when}  {row.get('type', '?')}  {row['path']}\n    {desc}\n"


def size(text):
    return len(text.encode("utf-8"))


def month_buckets(today):
    """The last MONTHS calendar months up to `today`'s, newest first."""
    y, m = int(today[:4]), int(today[5:7])
    out = []
    for _ in range(MONTHS):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def facets(matched, query, owner=None):
    """Facet lines over the whole matched set, trimmed to stay under the cap."""
    skip = set(query.entities) | ({owner} if owner else set())
    ents = Counter(s for r in matched for s in row_slugs(r) if s not in skip)
    tags = Counter(t for r in matched for t in row_tags(r) if t not in set(query.tags))
    recent = month_buckets(query.as_of)
    months = Counter()
    for r in matched:
        d = effective(r, query.as_of)
        months[d[:7] if d[:7] in recent else "older"] += 1

    def top(counter, n):
        return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    lines = []
    if ents:
        lines.append("entities: " + " · ".join(f"{k} {v}" for k, v in top(ents, TOP_ENTITIES)))
    if months:
        shown = [f"{k} {months[k]}" for k in recent if months.get(k)]
        if months.get("older"):
            shown.append(f"older {months['older']}")
        lines.append("months: " + " · ".join(shown))
    if tags:
        lines.append("tags: " + " · ".join(f"{k} {v}" for k, v in top(tags, TOP_TAGS)))
    # Hold the facets under the footer cap, dropping the widest line's tail.
    while lines and size("\n".join(lines)) > FOOTER_CAP - 256:
        widest = max(range(len(lines)), key=lambda i: size(lines[i]))
        parts = lines[widest].split(" · ")
        if len(parts) <= 1:
            lines.pop(widest)
        else:
            lines[widest] = " · ".join(parts[:-1])
    return lines


class Result:
    """A matched, ordered set, cut into pages that fit the budget."""

    def __init__(self, rows, query, budget=DEFAULT_BUDGET_KB * KB, owner=None,
                 notes=(), unparseable=0):
        self.query = query
        self.budget = int(budget)
        self.matched = match(rows, query)
        self.ordered = order(self.matched, query)
        self.future = sum(1 for r in self.matched if occurred(r) > query.as_of)
        self.unparseable = unparseable
        self.emptied = emptied_by(rows, query) if not self.matched else None
        self.facet_lines = facets(self.matched, query, owner)
        self.header = self._header(notes)
        self.entries = [entry_text(r) for r in self.ordered]
        self.pages = self._paginate()

    def _header(self, notes):
        q = self.query
        bits = []
        if q.entities:
            joiner = " | " if q.any_mode else " & "
            bits.append("entity " + joiner.join(q.entities))
        for t in q.tags:
            bits.append(f"tag {t}")
        if q.text:
            bits.append(f'text "{q.text}"')
        if q.since:
            bits.append(f"since {q.since}")
        if q.until:
            bits.append(f"until {q.until}")
        if q.status:
            bits.append(f"status {q.status}")
        n = len(self.matched)
        line = f"search: {', '.join(bits) or 'everything'} · {n} match{'es' if n != 1 else ''}\n"
        for note in notes:
            line += f"resolved: {note}\n"
        return line

    def _footer(self, page, worst=False):
        q = self.query
        total = len(self.ordered)
        last = len(self.pages) if not worst else max(total, 1)
        lines = []
        if worst:
            lines.append(f"page {total} of {total} · showed {total} of {total} · "
                         f"cut at 0000-00-00 · {total} more behind the cut")
            lines.append(f"next: --page {total + 1}")
        elif total == 0:
            lines.append("page 1 of 1 · showed 0 of 0")
            if self.emptied:
                lines.append(f"emptied by: {self.emptied}")
        elif page > last:
            lines.append(f"page {page} of {last} · showed 0 of {total} · "
                         f"past the last page, which is --page {last}")
        else:
            start, end = self.pages[page - 1]
            when = occurred(self.ordered[end - 1]) or "undated"
            remain = total - end
            line = f"page {page} of {last} · showed {end} of {total} · cut at {when}"
            if remain:
                line += f" · {remain} more behind the cut"
            lines.append(line)
            if remain:
                lines.append(f"next: --page {page + 1}")
        lines.extend(self.facet_lines)
        if self.future or worst:
            lines.append(f"future-dated: {self.future} row(s) after {q.as_of}, sorted as {q.as_of}")
        if self.unparseable or worst:
            lines.append(f"skipped: {self.unparseable} unparseable manifest line(s)")
        return "--\n" + "\n".join(lines) + "\n"

    def _paginate(self):
        """Page boundaries over `entries`, as `(start, end)` pairs.

        The room for rows is the budget less the header and the worst footer
        this set can produce, so every page fits whatever its own footer says.
        A row that would cross the room ends the page; the first row of a page
        is always taken, so no page is empty while rows remain (E2).
        """
        self.pages = []
        reserve = size(self.header) + size(self._footer(1, worst=True)) + 32
        room = max(self.budget - reserve, 0)
        pages, start = [], 0
        while start < len(self.entries):
            used, end = 0, start
            while end < len(self.entries):
                cost = size(self.entries[end])
                if end > start and used + cost > room:
                    break
                used += cost
                end += 1
            pages.append((start, end))
            start = end
        return pages

    def page_rows(self, page):
        if 1 <= page <= len(self.pages):
            start, end = self.pages[page - 1]
            return self.ordered[start:end]
        return []

    def render(self, page=1):
        body = ""
        if 1 <= page <= len(self.pages):
            start, end = self.pages[page - 1]
            body = "".join(self.entries[start:end])
        text = self.header + body + self._footer(page)
        return with_bytes(text)


def with_bytes(text):
    """Append `bytes: <n>`, where n is the size of the whole output, that line included."""
    n = size(text) + len("bytes: \n")
    while True:
        out = f"{text}bytes: {n}\n"
        if size(out) == n:
            return out
        n = size(out)


# --- command line ------------------------------------------------------------


def iso_day(value):
    if not DAY.match(value or ""):
        raise argparse.ArgumentTypeError(f"{value!r} is not YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return value


def positive(kind):
    def parse(value):
        try:
            n = kind(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
        if n <= 0:
            raise argparse.ArgumentTypeError(f"{value!r} must be positive")
        return n
    return parse


def build_parser():
    p = argparse.ArgumentParser(
        prog="search.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--entity", action="append", default=[], metavar="SLUG|PATH|NAME",
                   help="an entity as a slug, a path or a name as written; repeat to intersect")
    p.add_argument("--any", action="store_true",
                   help="make repeated --entity a union, interleaved per entity")
    p.add_argument("--tag", action="append", default=[], help="a tag; repeat to intersect")
    p.add_argument("--text", help="words that must all appear in desc, folded")
    p.add_argument("--since", type=iso_day, help="occurred on or after YYYY-MM-DD")
    p.add_argument("--until", type=iso_day, help="occurred on or before YYYY-MM-DD")
    p.add_argument("--status", choices=("active", "open"),
                   help="active facts or open loops; both by default")
    p.add_argument("--page", type=positive(int), default=1, help="the page to print, from 1")
    p.add_argument("--budget", type=positive(float), default=DEFAULT_BUDGET_KB,
                   metavar="KB", help=f"page size in KB, header and footer included "
                                      f"(default {DEFAULT_BUDGET_KB})")
    p.add_argument("--as-of", type=iso_day, help="'today' for the ordering (default: today)")
    return p


def resolution_report(failed):
    """The text printed instead of rows when a name did not resolve."""
    out = []
    for res in failed:
        if res.candidates:
            out.append(f'ambiguous: "{res.raw}" matches {len(res.candidates)} entities '
                       f"by {res.tier}; pass the one the question means, as its slug:")
            for e in res.candidates[:25]:
                out.append(f"  {e['slug']}\t{e['kind']}\t{e['title']}")
            if len(res.candidates) > 25:
                out.append(f"  … {len(res.candidates) - 25} more")
        elif res.tier == "no-roster":
            out.append(f'not found: "{res.raw}": knowledge/entities/roster.tsv is absent, '
                       "so no name can resolve here. Read knowledge/entities/index.md "
                       "for the entity, then pass its slug's path (/entities/<kind>/<slug>.md).")
        else:
            out.append(f'not found: "{res.raw}" matches no entity in '
                       "knowledge/entities/roster.tsv (exact, whole word or similar). "
                       "Read the roster whole, once, to find it.")
    return "\n".join(out) + "\n"


def main(argv, bundle=BUNDLE):
    args = build_parser().parse_args(argv)
    knowledge = Path(bundle) / "knowledge"
    try:
        rows, bad = load_manifest(knowledge)
    except FileNotFoundError:
        print("no manifest: knowledge/manifest.jsonl is missing. Run "
              "`python3 scripts/build-index.py` to rebuild it, then search again.")
        return EXIT_NO_MANIFEST

    roster = load_roster(knowledge) if any(
        not (e.strip().endswith(".md") and "/" in e) for e in args.entity) else None
    resolutions = [resolve(e, roster) for e in args.entity]
    failed = [r for r in resolutions if not r.ok]
    if failed:
        sys.stdout.write(with_bytes(resolution_report(failed)))
        return EXIT_AMBIGUOUS if any(r.candidates for r in failed) else EXIT_NOT_FOUND

    slugs = []
    for r in resolutions:
        if r.slug not in slugs:
            slugs.append(r.slug)
    query = Query(entities=slugs, any_mode=args.any, tags=args.tag, text=args.text,
                  since=args.since, until=args.until, status=args.status, as_of=args.as_of)
    notes = [n for n in (r.note() for r in resolutions) if n]
    result = Result(rows, query, budget=int(args.budget * KB), owner=owner_slug(bundle),
                    notes=notes, unparseable=bad)
    sys.stdout.write(result.render(args.page))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
