# Every answer says what kind of answer it is

[← README](../README.md)

A perfect score on a fixture is not the goal; some questions are undecidable
statically at any budget. So each result is labelled with the evidence behind
it — `resolved`, `declared`, `historical`, `structural`, `heuristic`, or
`textual`:

```
answer: heuristic via ripgrep (literal, prose filtered) · 2 hit(s) · 2 repo(s)
  --why for what a heuristic answer cannot see
```

This matters most for **negative** results, which is where a search tool does
real damage: "nothing uses this" from a `textual` match is close to worthless
evidence, while the same answer from `cs refs` is strong. `cs why <kind>` prints
what that kind cannot see.

`cs` is also loud about the four ways a result can be less than it looks: an
engine that hit its timeout says `PARTIAL` rather than returning empty, a capped
result says `showing N of M` and prints the per-repo distribution, a fallback to
a different engine says `degraded:`, and a `cs uses` that met a language its
prose filter does not know names it rather than claiming a filter that did not
run:

```
answer: heuristic via ripgrep (literal, prose filtered except: .erl) · 6 hit(s)
```

## And it refuses rather than answering empty

The worst thing this tool can produce is not a wrong answer but a confident
*negative* — a well-formatted, correctly-labelled, entirely empty result caused
by a malfunction rather than by an absence. "No code uses this" is what makes
deleting a live endpoint look safe.

So the conditions that would manufacture one are fatal, not silent: a fleet root
that does not exist or holds no repos, a missing `python3`, a `--ticket=<id>`
naming a workspace that is not there, or — for `cs impls` / `cs refs` — a repo
whose **language toolchain** is not installed. That last one was the tool's own
worst failure mode reproduced inside it: the preflight checked `uvx` and
`python3`, the *driver*, and said nothing about whether the language could be
analysed, so on a machine with no .NET SDK a C# repo produced

```
answer: resolved via serena (LSP) · 0 hit(s)
```

— the strongest negative in the taxonomy, asserted about a repo where nothing
had been read. `cs` now refuses, and never labels `resolved` an empty result the
language server did not affirmatively produce: an error, a timeout, or an empty
response refuse rather than answer.

`verify-search` has a whole section asserting each of these refuses, because none
of them failed a scored query — they were found by probing the failure paths,
not by reading the code.

## And a refusal is detectable, not merely explained

| Exit | Meaning |
|---|---|
| `0` | the query ran and found at least one hit |
| `1` | **refusal** — the query did not run, so nothing was ruled out |
| `2` | the query ran honestly and found nothing |

`1` and `2` are opposite facts and both used to be `1`, which left the tool's
central promise available only as prose on stderr. The obvious thing for a
caller to write —

```sh
if cs uses "$route" >/dev/null 2>&1; then echo "in use"; else echo "unused"; fi
```

— reported `unused` for a typo'd `FLEET_ROOT`. Asking the caller to read *which*
failure they got is a reasonable instruction for a human and a useless one for a
script.

A **broken** engine refuses as well, which is what makes `2` worth trusting.
`cs engines` can report what is on `PATH`; it cannot report that ripgrep is on
`PATH` and exiting 2 on every query, that the regex you typed does not compile,
or that `deps.py` is crashing. Each produced no output and was reported as
`0 hit(s)` — and splitting the exit codes made that *worse*, because a caller
correctly branching on `2` now gets "the answer is no" from a search that
crashed. Every engine's status is checked (`ripgrep`, `grep` and `ast-grep`
share the `0`/`1`/`≥2` convention; `semgrep` and `git` report `0` either way),
and an empty result from a failed engine refuses.

A file that could not be **read** is deliberately not in that category. ripgrep
uses exit 2 for "could not open one file out of 84,000" as well as for a broken
regex, and treating those alike meant a single committed symlink pointing at a
former colleague's home directory made *every zero-hit query on the fleet
refuse* — while queries with hits answered normally. `cs` parses the engine's
stderr, so a per-file error becomes `PARTIAL` with the skipped paths named, and
only a systemic failure refuses. Recursive `grep` skips such a file silently, so
`cs` finds it separately on that backend: a negative has to mean the same thing
whichever engine is installed.

**And a dangling symlink is not a read failure either.** A symlink *committed to
a repo* whose target is not in it is unreadable on every checkout but its
author's, permanently — it is a property of the corpus, like an excluded
directory or a repo that was never cloned. Measured on a 43-repo fleet, two of
them put `PARTIAL` on 100% of answers, on every verb, naming the same two paths
whether or not the query touched their repo. A warning that fires always is a
warning nobody reads, and then the day it means an engine *timed out* is the day
it is skipped. So the deterministic case is separated from the retryable one:

| condition | deterministic? | would a rerun change it? | `PARTIAL`? |
|---|---|---|---|
| engine timeout | no | maybe | yes |
| file unreadable (permissions, I/O) | no | maybe | yes |
| dangling symlink committed to the repo | **yes** | **no** | **no** |

Each answer carries a one-line count (`skipped: 2 dangling symlink(s) — a corpus
property, not a read failure`); `cs engines` names them once, under `corpus:`,
which is where fleet health belongs; and `--porcelain` reports them as
`corpus_skipped`, separate from `skipped` and not folded into `partial`. The
disclosure survives — silently narrowing the corpus is the opposite failure —
and only its severity changes.

## And the metadata is available as data

Everything that decides how much an answer is worth was prose on stderr — the
answer kind and the four warnings that must not be swallowed. `--porcelain` (or
`CS_JSON=1`) puts one JSON object on stdout instead of the result lines:

```json
{"cs":1,"subcommand":"uses","query":"…","scope":"/home/me/tickets/PROJ-123",
 "view":"/home/me/tickets/PROJ-123 (2 repo(s), your branch) + fleet (8 repo(s), main)",
 "exit":0,"refused":false,"kind":"heuristic","engine":"ripgrep","hits":2,
 "repos":2,"degraded":null,"partial":false,"truncated":false,"returned":2,
 "bytes":214,"elided":null,"notes":[],
 "engine_errors":[],"results":[{"repo":"…","path":"…","line":7,"text":"…"}]}
```

`bytes` is the size of the results, and `elided` says how many hit lines were
cut to `CS_MAX_LINE` and how many bytes that removed (`null` when none were).
`notes` carries answer-level notices that would otherwise exist only on stderr —
a manifest `cs versions` found but could not read, for one.

Refusals carry the envelope too, with `refused: true` and the reason — the case
with no result stream to attach anything to. `hits` is how many exist and
`returned` how many came back, so a cap is visible without reading a warning.
stderr is untouched, so `--porcelain` composes with `--quiet`.

`scope` and `view` are the `searching:` line as data. A human running `cs` knows
which directory they are standing in; a caller reading the envelope chose
neither the directory nor the layering and could not otherwise tell which of
the two levels answered — so the provenance goes on stdout with everything else
that decides what the result is worth, and a caller that asked for a named
workspace can assert it got that workspace rather than `main`.

## And `cs engines` reports answer kinds, not just binaries

The contract is expressed in answer kinds; the install is a list of binaries;
nothing connected the two, so `ast-grep MISSING` / `semgrep MISSING` next to
five rows saying `ok` read as a healthy setup rather than as *the entire
`structural` tier is gone and `cs calls` will refuse*. `cs engines` now derives a
per-kind view from the same probes:

```
ANSWER KIND  STATUS
structural   UNAVAILABLE — needs ast-grep or semgrep, neither installed → cs calls and cs def both refuse
               backs: cs calls, cs def
resolved     DEGRADED — dotnet ok, java MISSING (Kotlin), node ok → cs impls / cs refs refuse for the missing languages
               backs: cs impls, cs refs
textual      ok — ripgrep
               backs: cs text, cs seam
```

`degraded` is deliberately a third state: no ripgrep still yields `textual`
through the POSIX grep fallback, which is a slower route to the same kind, not a
missing kind. `cs why <kind>` reports the same availability alongside that
kind's blind spots.

## And where no language server can run, a graph answers instead

`cs impls` needs a language server, which needs its language's toolchain. Where
that toolchain is missing, or cannot be installed on the machine, refusing was
`cs`'s only answer. (This once said .NET Framework C# was such a case by
construction on macOS and Linux. It is not: the .NET SDK loads Framework
projects there too, minus their reference assemblies, as `verify-engines`'
`serena-netfx` probe checks.) When a repo has a tokensave graph, `cs impls` now falls back
to it:

```
! answered from a tokensave graph last synced 12m ago — it cannot see changes made since
! this is a GRAPH answer, not a language server: it cannot see reflection, DI
  registration, or generated code…
answer: structural via tokensave (graph) · 2 hit(s) · 1 repo(s)
```

Never labelled `resolved` — a graph is not a language server, and `cs refs`
remains the only thing here that bridges a DI registration. The query is
`implements` ∪ `extends`, because C# has one syntax for both relations (see
`fixtures/BASELINE.md`). `cs engines` reports graph age alongside the binaries,
since a graph is the one engine that can be confidently *wrong* rather than
merely blind.

That age is read from the graph's `last_sync_at` — when it was last **verified**
against the tree — and deliberately not from `last_updated`, which records when
its **content last changed**. They are different questions, and a sync that
finds nothing to change advances the first and not the second. On a fleet synced
two minutes earlier:

```
last_sync_at        ->  0h  2m ago
last_updated        -> 87h 46m ago
```

Reading the second made every graph answer tell the reader their graph was days
stale and prescribe `tokensave sync` — minutes after a scheduled job had run it.
It never self-corrected either: a repo whose commits touch only file types with
no extractor keeps a stale `last_updated` indefinitely while being perfectly
current, so the warning fired hardest on the repos that least needed it. Where
the field is missing the age is reported as *unknown* rather than substituting
the other one, for the same reason `cs strictness` keeps `UNKNOWN` distinct.

`cs def` gets the same fallback: with no universal-ctags installed it reads the
graphs instead, and `--engine=tokensave` asks for them deliberately. The
trade-off is coverage — the ctags index spans the whole view in one pass, while
graphs are **per-repo** — so `cs` names the repos it could not cover:

```
! no tokensave graph, so NOT searched: pricing-lib-java web-monorepo-node …
  — a definition in those repos cannot be found this way
```

Without that line a definition living in an unindexed repo would look exactly
like a symbol that does not exist, which is the failure this whole project is
organised against.

## The field-level impact question, split by access kind

`cs uses` answers *"who is affected if I change field X"* textually, which is
the one shape text cannot express: it has no read/write distinction. That
matters because a field change has **two different blast radii**, and which one
you care about depends on the change:

- an **additive** change, or a changed **default**, can only be observed where
  the field is **written** — it is invisible anywhere the object is merely read
- a **removal, rename or retype** breaks where the field is **read**

A grep collapses both into one list, so reviewing a default-value change with a
text sweep returns precisely the sites where the change is *not* observable.

```
$ cs fields _threshold --fleet
fulfillment-worker-python/fulfillment/discounts.py:14: [write] in DiscountEngine::__init__ self._threshold = waiver_threshold_cents
fulfillment-worker-python/fulfillment/discounts.py:17: [read] in DiscountEngine::handling_fee_cents if subtotal_cents >= self._threshold:

write sites: 1 (shown 1) — these observe an added field or a changed default
read sites:  1 (shown 1) — these break on a removal, rename or retype
answer: structural via tokensave (graph) (2 repo graph(s), read/write split) · 2 hit(s) · 1 repo(s)
```

Unlike `cs callers` / `cs callees` / `cs impact`, this one is **fleet-wide**:
"who is affected" stops making sense at a repo boundary. Graphs are still
per-repo, so the union is assembled across them and the repos with no graph are
named — a field read in an unindexed repo looks exactly like a field nobody
reads.

Three things it refuses or discloses rather than guessing, measured against
tokensave 7.9.0 and re-measured on 7.11.0 and 7.13.0:

- **An empty answer refuses.** `field_sites` returns zero counts with exit 0 for
  a field that does not exist, in the identical shape it returns for a field
  that exists and is never touched — and `find_exact_symbol` reports count 0 for
  a *real* field too, because field nodes are not in that index. Nothing can
  separate the two, and *"nothing reads this field"* is the answer someone
  deletes a field on.
- **A `Type::field` qualifier is trusted only as far as the engine applies it.**
  Before 7.11 it is parsed and then dropped, and the *bare-name* results come
  back regardless: `DiscountEngine::_threshold` and a fabricated
  `NoSuchClass::_threshold` return identical sites. Answering would put the
  broad question's result under the narrow question's heading, so it refuses.
  From 7.11 it is applied, by typing each site's receiver. That brings two
  more cases. A narrowed zero refuses, because a Python attribute that is only
  assigned has no declaration to match, so a real type can answer zero. And
  sites whose receiver cannot be typed (`make()._x`) are counted, not listed,
  so a narrowed answer that dropped any is marked PARTIAL, a lower bound.
- **At fleet scale, ask for counts instead.** A common field name overflows
  tokensave's 15000-character output on its *write* list alone, so the listing
  refuses — correctly, since a partial site list would understate the blast
  radius. `cs fields <field> --count` answers anyway, because the counts are
  emitted *before* the site arrays and survive the cut that destroys them:

  ```
  $ cs fields chargeAmount --fleet --count
  repo-a: writes 9, reads 41 (refs: 9 write, 63 read)
  repo-b: writes 3, reads 12

  total: writes 12, reads 53 site(s) across 2 repo(s) with a graph
  ```

  The headline numbers are **sites** — distinct `file:line`, the same quantity
  the listing reports, so the two modes agree. tokensave counts *occurrences*,
  which overstates a blast radius: three references on one line are one place a
  human edits, not three. The occurrence counts are kept alongside, and printed
  only where they differ. Where the output was truncated the arrays are
  incomplete, sites cannot be derived at all, and the row says it is counting
  references instead.

  These are the graph's own totals, not a returned-row count. That distinction
  is why this fans out per repo rather than querying the fleet-wide union graph:
  the union graph answers promptly but silently *caps* — its `write_count` came
  back as 20 with limit 20 and 21 with limit 21, so nothing separates "21 sites
  exist" from "21 of many were returned". An honest refusal beats a total nobody
  established.
- **The cap is per access kind, and engine truncation is `PARTIAL`.** Reads
  outnumber writes heavily, so one cap over the combined stream would spend the
  budget on reads and truncate the writes away. Separately, `tokensave tool`
  cuts its own stdout at 15000 characters — mid-token, leaving invalid JSON — so
  above roughly 75 sites the reads are re-requested with a limit and become a
  sample of an unknown total. That is reported as `PARTIAL` with the read count
  spelled `≥N`, never as a complete answer.

## Who can even OBSERVE an error contract

`cs strictness` answers *"who rejects an added field"*. There is a second
question with the same shape, the same declared evidence, and a different class
of review behind it: **will this consumer even read the response body?**

Two findings it exists for. A producer shipped a partial-failure contract — a
*"here is what already succeeded"* field, designed for a caller that reads it on
error — and the consumer discarded the body and auto-retried. The field was
worthless, and that half was never in the diff. And a producer changed an
**error** shape, where the impact question is *"who parses error responses"* —
which the additive/strictness framing does not fire on at all.

The evidence is plentiful and declared. Across a 43-repo fleet: `raise_for_status`
in 323 files, `tenacity` in 219, `@Retryable` in 10, `Retryer` in 1. Those 323
raise on a non-2xx **without reading the body**, and none of them looks any
different from an attentive consumer in a `cs uses` answer.

```
$ cs resilience --fleet
fulfillment-worker-python: RETRIES, BODY DISCARDED — 1 raise-and-discard, 1 retry configuration(s)
kit-service-python:        READS ERROR BODY — 1 site(s) read the error body
pricing-lib-java:          UNKNOWN — no recognised error handling found
```

`RETRIES, BODY DISCARDED` is its own verdict rather than a shade of `DISCARDS`,
because it is the one that turns a producer-side contract into a no-op. And
`UNKNOWN` is **not** "reads it", for the same reason `UNKNOWN` is not `LENIENT`
in `cs strictness`: undetermined is not safe. A retry configured at the
*infrastructure* layer — a mesh, an ingress, a client-side load balancer —
produces the same observable behaviour with nothing in the repo to find, and is
named in every answer rather than silently missing.

A wrong answer here is **quieter** than a wrong strictness answer, which is the
argument for having it: a rejected field crashes the consumer loudly, while a
discarded field simply never arrives and nobody gets paged.

## The same split for a config key, across a repo boundary

`cs fields` splits a field into writes and reads. A config key has the same two
sides — except they sit on opposite sides of a **repo boundary**, and
`cs uses <KEY>` returns them in one undifferentiated list. That shape hides the
defect, because the interesting failure is not a missing reference. It is a
**value mismatch across the seam**.

The finding behind it: a cross-repo pair, both halves unusually well verified in
isolation — the producer proved its chart rendered identically, the consumer
proved its values parsed identically — with the defect sitting exactly between
them, because the producer gated on specific tokens and the consumer passed a
group-level name that was never one of them. Neither side's tests could see it.
Nothing in either diff could.

The two sides live in **different file kinds**, which is what makes the split
cheap and a single sweep useless. Measured on a 43-repo fleet: a Spring profile
selector in 10 manifests and 4 code files, a feature-flag prefix in 1 and 26, a
log-level key in 15 and 58.

```
$ cs values ACME_TIER_SELECTOR --fleet
web-monorepo-node/charts/x/values.yaml:1: [set] "group-name"   ...  <- NOT accepted by any read site
web-monorepo-node/charts/x/templated.yaml:1: [set] (templated) {{ .Values.tier }}   ...
inventory-api-dotnet/deploy/values-prod.yaml:2: [set] "alpha,beta"   ...
checkout-service-kotlin/.../Tier.kt:5: [read] compares against: alpha | beta | gamma   ...
set sites: 4 in 2 repo(s), 3 distinct literal value(s), 1 templated
read sites: 1 in 1 repo(s), accepts 3 token(s): alpha | beta | gamma
! 1 value(s) are SET but not accepted by any read site this could enumerate
```

The last line is the finding; everything above it is context. Three restraints
keep it worth trusting:

- **"Accepts" is only sometimes derivable.** A `switch`/`when` over string
  literals is readable; a value passed to a framework, split on a separator, or
  normalised first is not. Undeterminable is reported as `UNDETERMINABLE` and
  the mismatch line does not fire at all — a guessed enumeration would turn this
  into a generator of false findings about values that are fine. Only a real
  test counts: `for name in ("KEY", "KEY_USERNAME"):` is a loop, not a
  membership test, and a token that names a key is dropped. A comparison in a
  **test file** (`assert settings.URL == "https://fake-host"`) is listed apart
  and never counted as accepted, because a fixture value shows what a test
  expects, not what production accepts.
- **A templated set-site is named, not resolved.** `{{ .Values.x }}` is reported
  as templated and never compared. Naming *which* sites are opaque is the useful
  part: those are the ones a human has to open.
- **A list value is checked token by token.** `"alpha,beta"` satisfies a reader
  that accepts both, rather than being flagged because the whole string is not a
  token.

The sides are told apart by **file kind, not dataflow**, and the answer says so:
a code file that sets the key at runtime is counted as a read site here.

## The corpus bounds a negative, not just the search

Everything else here is about whether the *search* was sound — a zero is
distinguished from a refusal, a timeout rules nothing out, `PARTIAL` is
disclosed. None of it says anything about whether the *corpus* was. A fleet
holding 43 of an org's 365 repos makes `cs uses <route>` returning nothing mean
"not in these 43", and reading it as "nothing at this company calls it" is wrong
in a way no provenance on the search can catch. The proof is set-theoretic: no
query shape can find a repo that was never cloned.

So every fleet-scoped zero now says so:

```
! this negative is bounded by the CORPUS, not just the search: 43 repo(s) are in
  view, and a repo that was never cloned cannot be searched by any query.
  Escalate before reporting absence: cs gaps '<route>'
```

`cs gaps` runs the query against the forge's org-wide code search, subtracts the
repos the fleet already holds, and reports the remainder split by whether the
match is application code or config only — of ~20 non-fleet repos found
referencing a service this way, only about half did so from application code;
the rest were deployment manifests and READMEs, and cloning on a raw match would
grow the fleet with the wrong half.

It is the one engine here that needs **network**, so it is opt-in, reported by
`cs engines` like any other, and it **refuses** rather than degrading to a
fleet-only answer wearing an org-wide label. Three refusals are load-bearing,
because each was a measured false zero: a rate-limited call (org-wide search is
limited, and a suppressed stderr turned a 403 into "this repo has no hits for
anything"), an unauthenticated CLI, and a fleet whose remotes are local paths —
which an earlier version read as an org named `.origins`, searched, and would
have reported as "nothing beyond the fleet".

## A text answer says how much of itself is data

The size of a text answer is the first thing a reader takes from it, and a large
hit count reads as thorough coverage. Measured on a 43-repo fleet, `cs uses` on a
CamelCase type returned **1,295 hits** — of which 1,271 were data files and 1,192
came from a single test-resources CSV. The 24 source hits were the answer, and
under the 200-line cap almost none of them were shown.

Nothing was filtering wrongly: a CSV has no comment syntax, so there is nothing
to strip and every line legitimately passes. The defect was that the composition
was invisible — the answer did not distinguish 24-code-plus-1271-fixture from
1295-code, and `cs uses`'s own "in CODE" reads as a promise about file *kind*
when what it means is "with comments stripped where we know how".

Every text answer now reports its own composition, and warns when the data half
dominates:

```
$ cs uses OrderLineItem --fleet
...
! most of this answer is NOT source: composition: 24 in source, 1271 in
  data/doc files (.csv 1208, .json 19, .md 3) — --source-only excludes the data half
```

`--source-only` is the opt-in narrowing, and it is **not** the default: a route
in an `appsettings.json` is a real seam, and dropping it silently would be the
same class of error in the other direction. When used, it is declared in the
porcelain envelope's `exclusions`, not only on stderr. Generated assets count
as data too: `.svg`, `.map`, `.min.js` and `.min.css`. A match inside a
committed SVG diagram is a label, not a seam.

### One hit line is not the whole answer

A 27-hit answer once came to 110 KB, and 96% of that was six lines of a
generated SVG. The longest line was 62 KB. The count gave no warning, because
the cost was in line *length*. So each hit's text is now cut to `CS_MAX_LINE`
bytes (default 400) **around the match**, with the bytes removed written where
they were:

```
docs/arch.svg:1:…(49828 bytes elided)…<text>/api/orders</text>…(29824 bytes elided)
! 1 line(s) longer than 400 bytes were cut around the match (79652 bytes elided) — --full-lines prints them whole
```

The `repo/path:line:` address is never cut, and neither is what a verb writes
after it: the `[set]`/`[read]` tag and the literal from `cs values`, or the
`[write]`/`[read]` tag from `cs fields`. Only the raw source line is cut. Once an answer is over 20 KB, the
`answer:` line also gives its size, so the cost shows before you re-run.
`--full-lines` (or `CS_MAX_LINE=0`) prints lines whole.

The line is **data vs source, never test vs production**. A test file is often
the single most informative hit for an impact question — a test constructing a
request object *without* a field is exactly where a changed default becomes
observable — so test code always stays in scope. `.sql`, `.yaml` and `.xml` count
as source too: they have comment syntax, and a column named in a query is a real
use.

## Counts first, when hits cost something

`--count` started on `cs fields`, where a fleet-wide listing overflows the
graph's own output and the tallies are the only thing that survives. It now
also answers on `cs text`, `cs seam` and `cs uses`, for a different reason: an
**MCP caller pays per hit**.

One exploratory `cs_text` over a 43-repo fleet returned:

```
answer: textual via ripgrep (regex) · 642 hit(s) · 12 repo(s)
TRUNCATED: 200 of 642 hits shown. Narrow the query to see the rest.
```

Roughly 15,000 tokens, for a query whose only purpose was to find out *where to
look*. The cap behaved correctly — it disclosed the denominator, which is what
makes the cost visible — but the caller still paid 200 hit bodies to learn a
distribution:

```
$ cs text 'reservationId' --fleet --count
inventory-api-dotnet: 412
checkout-service-kotlin: 187
web-monorepo-node: 43

total: 642 hit(s) across 12 repo(s)
  counts only — no hit bodies were read into this answer
```

Two properties make the number worth reading. It comes from the **same search**
the listing runs, so `--word`, `--source-only` and the prose filter all still
apply and the totals agree with the listing's — a tally taken by a shortcut
would be a wider question wearing this one's heading. And the findings survive:
`cs seam --count` still reports the orphan warning, and every answer still
discloses its composition, because those are computed from the hits rather than
from what was printed.

It is refused, not ignored, on the subcommands that return neither hits nor
tallies. A dropped flag looks exactly like a flag that was honoured and changed
nothing.

## Saved queries are consumers, and they fail silently

One class of hit is neither source nor data: a **dashboard panel, alert rule or
recording rule**. When a workload is renamed or split, the emitted
`service.name` is a contract with every saved query that names it — and nothing
in a code diff, a chart diff or a symbol graph can see that seam, because on one
side it is a deployment identifier and on the other it is a string inside a
query expression. A workload split once changed a job name, the dashboards and
alerts kept querying the old one, and nothing broke loudly: the panel went flat
and the alert never fired again.

So `cs` labels them where they already turn up, rather than adding a verb for a
corpus of a dozen files:

```
$ cs uses 'checkout-service' --fleet
checkout-service-kotlin/alerts/rules.yaml:8: [alert rule] expr: up{job="checkout-service"} == 0
web-monorepo-node/dashboards/service.json:8: [dashboard] { "expr": "sum(rate(http_requests_total{job=\"checkout-service\"}[5m]))" }
! 2 of these file(s) are SAVED QUERIES, not code — a dashboard panel, alert or
  recording rule naming this string will not error when it stops matching: the
  panel goes flat and the alert never fires again
```

Classified by **content**, not by path — a dashboard lives wherever someone put
it — with one grep per candidate file, memoised, and only for the extensions a
saved query can live in.

And `--source-only` no longer hides them. A Grafana dashboard is a `.json`,
which the data/doc list drops, while an impact question is exactly the question
a caller reaches for `--source-only` to ask: the flag is meant to remove
fixtures and logs, not consumers. It says how many it kept for this reason.

## And the same graph answers the symbol half of a question

`cs uses`, `cs seam` and `cs history` ask about **names**. `cs callers`,
`cs callees`, `cs impact`, `cs impls` and `cs fields` ask about **symbols**. Both are here
because a real question crosses between them — *"I am renaming this route, what
breaks"* starts as a seam question and ends as a symbol one — and the handoff to
a second tool with a second scoping model is the cost worth removing.

```
$ cs callers ReserveAsync inventory-api-dotnet
tokensave: 'ReserveAsync' is 2 nodes in this graph and ALL were asked
  (src/Infrastructure/SqlInventoryStore.cs:14, src/Domain/IInventoryStore.cs:5)
inventory-api-dotnet/src/Controllers/ReservationController.cs:27: [method] Reserve (calls)
answer: structural via tokensave (graph) (scoped to inventory-api-dotnet; fleet layer, synced 0d ago; direct callers) · 1 hit(s)
```

Three subcommands, not ninety. The tool behind this fronts dead code, coupling,
complexity, blame, test mapping, call chains and inheritance depth; wrapping all
of that would make `cs` a second, worse interface for something already good at
it and would cost the property that makes it legible — subcommands shaped like
questions, few enough to hold in your head. `cs which` points at the graph tool
directly for anything deeper, because a facade that quietly answers *less* than
the thing it fronts is worse than no facade.

What `cs` adds over calling the graph is the part the graph does not carry:

- **The answer kind.** `structural`, never `resolved`. A graph cannot see
  reflection, DI registration or generated code, and raw graph output says so
  nowhere.
- **Refusal discipline.** Two of the graph CLI's own tools take a node id and
  answer a bare *name* with an empty result and **exit 0**: `callers_for` returns
  `{"callers": {"<Name>": []}}` and `impact` returns `node_count: 0`, both having
  looked nothing up. "Nothing calls this" is the answer someone deletes code on,
  so every lookup is two-step — name → node id → question — and a name that does
  not resolve refuses instead of printing nothing. (`callers` and `callees`
  reject a bare name loudly, so only two of the four needed the guard; a name
  that is several nodes, like an interface method and its implementation, has
  all of them asked rather than the top-ranked one.)
- **The scope it actually had.** Below.

### The layered view does not survive into symbol mode, and `cs` says so

`cs`'s best property is the layered view: ticket repos at branch state, every
other repo at main, one root. Graph indexes cannot do that. They are
per-project — the workspace copy of a repo has its own index, the fleet copy has
its own, and **there is no union**. So `cs callers <symbol>` cannot deliver what
`cs uses <string>` delivers, and left unsaid the gap is invisible in the output:
ask for callers of something you just renamed on your branch, get the fleet
index's answer, and it describes the world before your edit.

There is no clean fix, so the gap is made loud instead. Every symbol answer
names **which** index answered and how old it is, and an index from the wrong
layer is reported as `degraded` — which puts it in the porcelain envelope too,
where a non-human caller sees it without reading stderr:

```
$ cs callers ReserveAsync inventory-api-dotnet --ticket=PROJ-9
! the PROJ-9 workspace copy of inventory-api-dotnet has no graph, so its FLEET
  copy answered — this describes main, not your branch
answer: structural via tokensave (graph) (scoped to …; fleet layer, synced 0d ago; direct callers) · 1 hit(s)
! degraded: answered from inventory-api-dotnet's FLEET index (main) although the
  scope is PROJ-9 — graph indexes are per-project and there is no union of the
  two, so your branch's edits to inventory-api-dotnet are invisible in this answer
```

A caller who knows the answer excludes their branch can act on it; one who does
not, cannot. Build a graph in the workspace copy and the same query is answered
from it, with no warning to ignore — which is what keeps the warning worth
reading.
