# Fixture repos

Five tiny repos — one per stack in use (C#, Kotlin, Python, TypeScript, Java) —
with deliberately planted cross-repo seams.

**What these are for:** testing that the *mechanics* work. Does `new-ticket`
create usable worktrees? Does `tokensave branch add` inherit the fleet index
instead of building one cold? Does `refresh-fleet` leave worktrees intact? Does
cross-repo graph querying resolve? Being tiny is correct for those questions.

**What these are not for:** judging whether a search tool is good. This code is
clean, small, and its seams were planted on purpose — every tool will score well
on it. That question needs real queries against a real repo, drawn from your
own tickets; see "Honest limits" in the top-level `README.md`, and
`fixtures/BASELINE.md` for how the scored queries here were measured.

The exception is accuracy. The fixture carries **decoys** — a prose-only
mention of an endpoint, a consumer of a topic version nobody produces, a
same-named but unrelated class, a dead endpoint, a retired flag key that is a
superstring of a live one — so a tool cannot score well by being over-eager.
Those cases transfer to real repos even though the code around them does not,
because they are about how a tool decides two things are related, not about
scale.

Seam 6 is the other honest case: a DI indirection no static tool can resolve,
there to catch a tool overselling call-graph completeness.

## Ownership

Four of the five repos declare CODEOWNERS, deliberately across two conventional
locations (`.github/CODEOWNERS` and a root `CODEOWNERS`), with overlapping rules
so that **last-match-wins** is actually exercised: a catch-all `*` at the top of
`inventory-api-dotnet` is overridden by `/src/Infrastructure/`, and getting the
precedence backwards names the wrong team rather than failing.

`pricing-lib-java` declares none, on purpose. A repo with no CODEOWNERS is a
finding — `cs owns` reports it as a gap on stderr rather than answering "nobody
owns it" on stdout — and a fixture where every repo is owned could not test that.

## The blind spot these five repos share

They are written in C#, Kotlin, Python, TypeScript and Java — every one of which
`cs`'s comment filter supported from the day it was written. So a filter that
did nothing at all for C++, Go, Ruby or PHP still passed all nine queries, while
`cs uses` quietly returned comment matches as call sites for anyone whose fleet
was not this fleet.

`prose-probes/` closes that gap, and is deliberately *not* a modelled system:
one file per language, each carrying one token that appears only in comments and
one that appears only in code. `verify-search` copies them into a throwaway repo
at test time, so this fleet stays the five repos it has always been. See
`prose-probes/README.md`.

The general point is worth keeping in mind when adding fixtures here: a set
built to model one organisation's stack cannot detect a per-language failure,
and a facade that degrades per language looks perfect on it.

## Scoring

`expectations.json` holds machine-readable expected/forbidden file sets.

```sh
scripts/score-seams --list                              # the nine queries
rg -n "orders\.reserved" | scripts/score-seams orders-reserved-v1 -
```

`BASELINE.md` records how naive grep scores, as the floor an indexed tool must
beat. Note its stated limitation: the scorer checks which files an answer
names, not whether the reasoning was sound, so some passes are hollow. Failures
are the trustworthy signal.

## Usage

```sh
scripts/build-fixtures /tmp/fixture-fleet
export FLEET_ROOT=/tmp/fixture-fleet
export TICKETS_ROOT=/tmp/fixture-tickets
```

Each fixture is built as a bare origin plus a working clone, so fetch, reset,
worktree, and branch operations behave like real repos.

The Kotlin service and the Java library request a JDK 21 Gradle toolchain, so
on a machine without JDK 21 cs refuses their language-server questions. To
reproduce one there, build with `--no-toolchain`. It replaces both requests with
a JVM-target pin and commits that on `main`, because cs reads a fleet repo's
committed `main`, not its working tree.

`GROUND-TRUTH.md` lists every planted relation and what a correct answer looks
like. Read it *after* running a search, not before.

## Running one of them

`docker-compose.yml` brings up **inventory-api** so the HTTP boundary between it
and checkout can be exercised instead of read:

```sh
docker compose -f fixtures/docker-compose.yml up -d --build
curl -X POST http://localhost:18080/api/v1/inventory/reserve \
  -H 'content-type: application/json' -d '{"sku":"SKU-1","quantity":1}'
```

The response comes back **indented**, which is the whole point — that is the
serializer setting the PROJ-388 incident turns on, and the shape a hand-written
test payload in another repo will not have. ai-toolbox's `scripts/verify-contract`
drives checkout's real `InventoryClient` against this and checks that the
PROJ-388 introducing commit fails against it.

The `events` profile adds a single-node Kafka for the other seam
(`orders.reserved.v1`), so fulfillment-worker's `ReservationConsumer` can be run
against a real broker — its own suite never touches it:

```sh
docker compose -f fixtures/docker-compose.yml --profile events up -d kafka
```

Ports are 18080 and 19092 rather than 8080 and 9092, so they do not fight with
whatever is already running; override with `INVENTORY_PORT` and `KAFKA_PORT`.

One thing worth knowing before debugging a stuck consumer: a client killed
rather than closed leaves a member in the group, and that holds the group in
`PreparingRebalance` for the rebalance timeout — five minutes by default — so
the *next* consumer gets no partition assigned and looks broken when it is not.
`verify-contract` recreates the broker between scenarios rather than trying to
hand one back clean.
