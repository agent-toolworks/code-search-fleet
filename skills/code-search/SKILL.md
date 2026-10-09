---
name: code-search
description: Search across many repositories at once — find who calls an endpoint, where a symbol is defined, what implements an interface, which repo publishes a package, who owns the code (CODEOWNERS), and whether every repo pins the same version of a shared package. Use whenever a question spans more than one repo, or when grep alone gives noisy or incomplete answers. Trigger phrases: "who calls", "where is X defined", "what implements", "across the repos", "which repo", "find usages", "is this endpoint dead", "impact of changing", "who owns", "which team owns", "what version of", "version drift", "set up code search", "install code search", "new machine", "is cs working", "why did cs refuse".
---

# Searching a fleet of repositories

Use the `cs` command. It is one interface over five engines, because **no single
engine answers every question** — measured, not assumed: across nine scored
queries the best individual engine got 5/9, and `cs` gets 9/9.

Do not reach for raw `grep` first. It cannot see a route assembled from two C#
attributes, it counts a docstring mentioning an endpoint as a caller, and it
cannot resolve an interface to its implementation.

## Finding the command

The working directory is the user's project, not this tool, so `cs` is never on
a relative path. Resolve it once at the start of the session and reuse it:

```sh
CS="${CLAUDE_PLUGIN_ROOT:-$PWD}/scripts/cs"    # installed as a plugin, or a clone
"$CS" engines
```

`CLAUDE_PLUGIN_ROOT` is set when this is installed as a plugin. From a plain
clone, use the checkout's own path. Every example below writes `cs` for
readability; run `"$CS"`.

## Setup

```sh
"$CS" doctor                         # what will not work on THESE repos, and the fix
"$CS" engines                        # the shorter view: what is installed here
"${CLAUDE_PLUGIN_ROOT:-.}/scripts/bootstrap"   # install missing engines, then run cs doctor
```

**Installing on a new machine, or asked to "set up code search": follow
`"${CLAUDE_PLUGIN_ROOT:-.}/docs/install.md"` step by step.** Each step has a check, and the
last one is `cs_doctor` over MCP agreeing with `cs doctor` in a terminal. Fixes
that need a shell profile (`~/.zprofile`, `~/.zshrc`) or `~/.config` are often
outside what you may edit. Do not work around that: give the user the exact line
`cs doctor` printed, prefixed with `!` so they can run it here. Then tell them
to restart Claude Code from a new terminal, because the MCP server keeps the
environment it started with.

**`FLEET_ROOT` is required** and there is no useful default — without it `cs`
searches the current directory, which is not a fleet. It belongs in
`~/.config/repo-fleet/fleet.env` (`export FLEET_ROOT="$HOME/code/fleet"`), the
one file both the CLI and the MCP server read. An `export` in a shell reaches
only that shell. If it is unset, ask the user for the directory holding their
repos rather than guessing.

**If you learned cs earlier**, these changed. `cs changes <the version you knew>`
(`cs_changes` over MCP) lists everything since, small fixes included, and the
MCP instructions name the running version. Details are in `docs/install.md`,
"If you already use cs":
- A scope is the **absolute path** of the workspace you are in, or of any
  directory inside it (since 1.16.0). A bare folder name still works when it is
  unique. `cs_scopes` lists workspaces by path, across `TICKETS_ROOT` and
  `WORKSPACE_ROOTS`.
- `cs doctor` is the setup check. Refusals now say `check: cs doctor`.
- Java needs no JDK. Kotlin needs one only when its build (or a build it
  includes) requests a Gradle toolchain, and then exactly that version; `cs`
  refuses when it is not findable. A build pinned by `sourceCompatibility` /
  `jvmTarget` alone needs none.
- Legacy .NET Framework C# loads with the .NET SDK, minus its reference
  assemblies.
- `CS_NO_GRAPH` in `fleet.env` marks repos kept without a graph on purpose.
- Language-server line numbers are 1-based since 1.18.1. Before, every
  `cs impls` / `cs refs` address was one line short, so an older answer
  you kept points one line above the symbol.
- A `cs refs` line names its enclosing symbol (`[in Method Foo/Bar]`). Since
  1.19.2 a hit inside a C# property is `[in Property Foo/Bar]`, not
  `[in Class Foo]`, and the `cs refs` hint after a `cs callers` zero names the
  declaring file, so run it as printed.
- A C# or Kotlin `cs callers` / `cs callees` / `cs impact` answer says the graph
  has no edges through property accessors (since 1.19.1), and a zero there is
  `degraded`, not "unused".
- A `cs refs` / `cs impls` refusal that says *the language server did not
  start* is about setup, not the symbol (since 1.21.1): do not rename and
  retry. An expired Kotlin build is fixed by the steps in `docs/install.md`,
  "Kotlin language server"; tell the user. Meanwhile use `cs def` / `cs uses`.
- `cs refs` takes a member as `Type.Member` (asked as `Type/Member`) since
  1.20.0. Before, it hit a Serena error that was counted as one `resolved`
  hit, exit 0. A language-server error is now a refusal, so a `resolved` hit
  is always a real reference.
- An answer a language server gave before its project import finished is
  asked again, or refused. It is never reported as it came, so a
  `resolved · 0 hit(s)` is a real zero.

**When a command refuses for a missing engine or toolchain, or `cs impls` /
`cs refs` comes back empty, run `cs doctor` (`cs_doctor` over MCP) before
concluding anything.** It checks this machine against the languages the fleet
actually contains, and hands the user the fix.

Every *engine* is optional. `cs engines` reports what is present, and `cs` routes
around whatever is missing rather than failing silently. **Two exceptions.**
`python3` — `uses`, `provides`, `deps`, `publishes`, `versions`, `owns`, `impls`,
`refs` and symbol mode run through it, and refuse without it rather than
returning zero hits that would read exactly like a real "nothing uses this". If
`cs` reports python3 missing, tell the user; `cs seam` still works without it,
but counts comments as hits. And **`tokensave`** — nothing else here answers a
call graph, so `cs callers`, `cs callees` and `cs impact` refuse without it (and
without a graph built in the repo being asked about: `cd <repo> && tokensave
init`) rather than degrading to something weaker.

**Read the `ANSWER KIND` table in `cs engines`, not just the binary list.** The
binaries are not the decision-relevant fact — which *kinds* of answer this
machine can produce is, because that is what the negative results are worth:

```
ANSWER KIND  STATUS
structural   UNAVAILABLE — needs ast-grep or semgrep, and universal-ctags — none installed → cs calls and cs def both refuse; no tokensave → cs callers / cs callees / cs impact refuse
               backs: cs calls, cs def, cs impls (graph fallback), cs callers, cs callees, cs impact
resolved     DEGRADED — dotnet ok, java MISSING (Kotlin), node ok → cs impls / cs refs refuse for the missing languages
               backs: cs impls, cs refs
```

There is a realistic install where both *strong* code-derived kinds are gone —
no ast-grep and no semgrep removes `structural`, and a missing language
toolchain removes `resolved` for that language — while five of the seven binary
rows still say `ok`. If a kind you were about to rely on is `UNAVAILABLE`, say
so rather than falling back to a weaker kind silently. `cs why <kind>` also
reports whether that kind is reachable here.

## Which subcommand

Run `cs which` for this table at any time.

| What you want to know | Use |
|---|---|
| Who calls/uses this endpoint, topic, config key | `cs uses <string>` |
| Which repos share this string | `cs seam <string>` |
| Any text or regex, comments included | `cs text <pattern>` |
| Where a symbol is defined | `cs def <symbol> [repo]` |
| Calls shaped like X, or taking literal Y | `cs calls '<pattern>' [lang]` |
| What implements this interface | `cs impls <symbol> <repo>` |
| What calls this symbol | `cs callers <symbol> <repo>` |
| What this symbol calls | `cs callees <symbol> <repo>` |
| What breaks if I change this symbol | `cs impact <symbol> <repo>` |
| Who reads/writes this FIELD, fleet-wide | `cs fields <field> [repo]` |
| Where a type is CONSTRUCTED, across every idiom | `cs constructs <Type> [repo]` |
| Who CRASHES if I add a field to a response | `cs strictness [repo]` |
| Who even READS an error body, and who retries | `cs resilience [repo]` |
| Who SETS this config key, and who READS it | `cs values <KEY> [repo]` |
| What matches ORG-WIDE that the fleet does not hold | `cs gaps <query>` |
| What references this symbol (bridges DI) | `cs refs <symbol> <repo> <file>` |
| Which repo publishes this package | `cs provides <coordinate>` |
| Which repos depend on which | `cs deps [repo]` |
| Which version each repo pins, and where they disagree | `cs versions [coordinate]` |
| Who to ask about this repo or file | `cs owns [repo\|repo/path]` |
| When a seam appeared, or last changed | `cs history <string> [repo]` |
| What is actually being searched right now | `cs repos` |
| Which workspaces there are to search at all | `cs scopes` |

**An API-impact review is four of these, not one.** `cs fields` finds who reads
and writes it; `cs constructs` finds where a changed default is observable;
`cs strictness` finds who *rejects* an added field; `cs resilience` finds who
can even *observe* one added to an **error** body — a caller that raises on the
status and retries never reads the payload, so the contract is a no-op for it
and nothing errors. For a config key rather than a field, `cs values` is the
same split across a repo boundary, and it reports which set values no read site
accepts. Before reporting that nothing is affected, run `cs gaps`: a repo that
was never cloned cannot be searched by any query.

**Start cheap.** `cs uses`, `cs def`, and `cs seam` answer in well under a
second. `cs impls` and `cs refs` start language servers and take minutes on a
large repo — reach for them when you need symbol-level truth, not for a first
look.

Every subcommand emits the same line format, including the two LSP-backed ones:

```
$ cs refs IInventoryStore inventory-api-dotnet src/Domain/IInventoryStore.cs
inventory-api-dotnet/src/Controllers/ReservationController.cs:9: [Class] private readonly IInventoryStore _store;
inventory-api-dotnet/src/Program.cs:11: [File] builder.Services.AddScoped<IInventoryStore, SqlInventoryStore>();
```

That second hit is the DI registration — the step neither grep nor a call graph
bridges, and the reason `cs refs` is worth its cost.

When a subcommand finds nothing it prints what to try instead, so a wrong first
choice self-corrects.

**Two kinds of question, one interface.** `cs uses` / `cs seam` / `cs history`
ask about **names**; `cs callers` / `cs callees` / `cs impact` / `cs impls` ask
about **symbols**. A real question crosses between them — *"I am renaming this
route, what breaks"* starts as a seam question and ends as a symbol one — which
is why both live here instead of in two tools with two scoping models. Run the
seam half first: it spans every repo, and it is what tells you which repo to
then ask the symbol half about.

Symbol mode reads a **tokensave graph**, which is per-repo — see *Symbol mode
answers about one repo at one layer* under **Known blind spots** before
reporting the result. `cs impact` is the one to reach for when the user is
deciding whether a change is safe; `cs callers` returning nothing for a resolved
symbol is the strongest "this looks dead" signal available inside one repo, and
still says nothing about the other repos.

## Read the answer kind before you trust the answer

Every result ends with a line naming the kind of evidence behind it:

```
answer: heuristic via ripgrep (literal, prose filtered) · 2 hit(s) · 2 repo(s)
```

The kind matters most for **negative** results, which is where a search tool
does real damage — concluding "nothing uses this" is what makes a breaking
change look safe.

| Kind | From | A negative result means |
|---|---|---|
| `resolved` | serena (LSP) | strong: no reference — within that one repo |
| `declared` | build manifests | strong: not declared |
| `historical` | `git log -S`/`-G` | strong, for tracked files |
| `structural` | ast-grep / semgrep / ctags | medium: no such syntax shape |
| `heuristic` | text match, prose filtered | **weak** |
| `textual` | ripgrep / grep | **weakest** — an occurrence is not a use |

`cs why <kind>` prints exactly what that kind cannot see; `--why` on any query
gives it inline.

Five warnings `cs` emits that you must pass on rather than swallow:

- **`PARTIAL`** — the result is a subset, not an answer. Two causes: an engine
  hit its timeout (raise `CS_TIMEOUT` and rerun), or files could not be read and
  were skipped. The skipped paths are always named — read them. Two unreadable
  files cannot hide a symbol, so a negative is still worth something; a skipped
  directory of 400 files is a different matter.
- **`skipped: N dangling symlink(s)`** — *not* `PARTIAL`, and not a warning to
  pass on as one. These are symlinks committed to a repo whose targets are not
  in it, so they are unreadable on every checkout, permanently: rerunning
  changes nothing and they say nothing about whether this search finished.
  `cs engines` names them. Report them to the owning repo, not in the answer.
- **`showing N of M`** — capped at 200 results. The per-repo distribution of all
  M is printed; use it to narrow, or pass `--all`. If you did not already know
  roughly where the hits were, ask the *next* exploratory question with
  `--count` instead: `cs text|seam|uses <query> --count` returns the per-repo
  tally and no hit bodies, from the same search, so the totals agree with the
  listing's and every narrowing (`--word`, `--source-only`, the prose filter)
  still applies. It is the difference between reading 200 hits to learn a
  distribution and reading one line per repo.
- **`degraded:`** — an engine was missing and `cs` fell back to another with a
  different pattern dialect. The results are not equivalent.
- **`prose filtered except: <extensions>`** — `cs uses` met files in a language
  its comment filter does not know, and passed them through unfiltered. Hits in
  those files may be comments. Treat them as `cs seam` hits, not `cs uses` hits.
- **`N of these file(s) are SAVED QUERIES, not code`** — some hits are dashboard
  panels, alert rules or recording rules, tagged `[dashboard]`, `[alert rule]`,
  `[recording rule]` or `[saved query]` in the output. They are consumers of the
  identifier, and they fail *silently*: renaming it does not error anywhere, the
  panel just goes flat and the alert never fires again. Report them by name in a
  rename's blast radius. `--source-only` keeps them even though a Grafana
  dashboard is a `.json`. Much of an observability estate lives in the platform
  rather than in git, so this is a floor on the exposure, never a ceiling.
- **`non-default exclusion list`** — `CS_EXCLUDE_EXTRA` or `CS_EXCLUDE_REMOVE`
  is set, so the search was narrowed or widened relative to the default. `EXTRA`
  is the dangerous direction: it can hide the very declaration you are looking
  for while leaving incidental mentions, so the result is not merely smaller but
  can be inverted in character. These are environment variables, so one set in a
  shell profile silently narrows every later session — if you see this warning
  and did not expect it, say so before trusting a negative.

## When cs refuses, it is protecting you from a false negative

`cs` exits `1` with an explanation rather than returning an empty result when it
cannot answer honestly: no such fleet root, no repos in it, python3 missing,
`--ticket=<id>` naming a workspace that does not exist, or — for `cs impls` and
`cs refs` — a repo whose **language toolchain** is not installed. **Do not work
around a refusal by falling back to raw `grep`** — the refusal means the
conditions for a trustworthy negative are not met, and grep's negative is
weaker still. Fix the cause, or tell the user what is missing.

Symbol mode refuses for two more reasons, both of the same shape. A repo with no
tokensave graph is a place results cannot come from (`cd <repo> && tokensave
init`), and a symbol that does not resolve to a graph node means the graph was
never asked at all. That second one matters because the raw graph CLI does *not*
refuse there: `tokensave tool impact <bare-name>` and `tokensave tool
callers_for <bare-name>` both **exit 0 with an empty result**, having looked
nothing up. "Nothing calls this" is the answer people delete code on, so `cs`
resolves the name to a node id first and refuses when it cannot.

That last one is worth naming, because it is the strongest label on the weakest
evidence: Serena is a *driver* for a language server, and a language server
needs a .NET SDK to load a C# project, a JDK for Kotlin, node for TypeScript
(the Java server ships its own runtime, so Java needs nothing installed). Without it the server loads nothing and returns nothing, which used
to print as `answer: resolved via serena (LSP) · 0 hit(s)` — "no reference,
within that repo", asserted about a repo where nothing had been read. `cs` now
refuses, and never labels `resolved` a result the server did not affirmatively
produce (an error, a timeout, or an empty response all refuse instead).

**Branch on the exit code, not on the message.** The three outcomes have three
codes:

| Exit | Meaning | What to do |
|---|---|---|
| `0` | the query ran and found ≥1 hit | report the hits, with the answer kind |
| `1` | **refusal** — the query did not run | fix the cause, or tell the user what is missing. Never report a negative. |
| `2` | the query ran honestly and found nothing | weigh it by the answer kind before saying "nothing uses this" |

`1` and `2` are opposite facts: one means *this search did not happen*, the
other means *this search happened and the answer is no*. Both used to be `1`,
which made the distinction available only as prose on stderr — so the obvious
thing to write,

```sh
if cs uses "$route" >/dev/null 2>&1; then echo "in use"; else echo "unused"; fi
```

reported `unused` for a typo'd `FLEET_ROOT`. That is the false negative this
whole design exists to prevent, so read the code, not the sentence.

**A broken engine refuses too**, which is what makes `2` worth trusting. An
engine that is installed and *failing* — ripgrep exiting 2, a regex that does
not compile, `ast-grep` rejecting its own pattern, a crashing helper — produces
empty output that is byte-identical to an honest negative. `cs` checks every
engine's exit status, so `2` means the search actually ran to completion. If you
see a refusal naming an engine, report the engine; do not retry with `grep`.

A file that could not be **read** is a different thing and does not refuse —
ripgrep reports a dangling symlink with the same exit 2 it uses for a broken
regex, and one such file on a real fleet would otherwise block every negative
result on it. Those come back as a normal answer carrying `PARTIAL` and the
skipped paths.

A **dangling symlink committed to a repo** is a third thing again, and is not
`PARTIAL`. It is deterministic: it is unreadable on every checkout that is not
its author's, so it fails identically on every rerun and cannot distinguish a
search that finished from one that did not. Two of them once put `PARTIAL` on
100% of a 43-repo fleet's answers, on every verb, which is how readers learn to
skip the line that matters. They are counted on each answer, named once by
`cs engines`, and reported in `--porcelain` under `corpus_skipped` rather than
`skipped`.

### `--porcelain` when you want the metadata as data

`--porcelain` (or `CS_JSON=1`) replaces the result lines on stdout with one JSON
object. Everything you would otherwise have to scrape off stderr is a field:

```sh
cs uses '/api/v1/inventory/reserve' --porcelain
```
```json
{"cs":1,"subcommand":"uses","query":"…","scope":"/home/me/tickets/PROJ-123",
 "view":"/home/me/tickets/PROJ-123 (2 repo(s), your branch) + fleet (8 repo(s), main)",
 "exit":0,"refused":false,"reason":null,"kind":"heuristic",
 "engine":"ripgrep","note":"literal, prose filtered","hits":2,"repos":2,
 "degraded":null,"partial":false,"truncated":false,"returned":2,
 "bytes":214,"elided":null,"notes":[],"engine_errors":[],"hints":[],
 "results":[{"repo":"…","path":"…","line":7,"text":"…"}]}
```

`view` is the `searching:` line as a field, and `scope` the workspace it
resolved to (or `"fleet"`) — so a caller that asked for a named workspace can
check it got that one rather than main.

### `CS_LOG` if the user wants outcomes measured over time

Off by default. `export CS_LOG=1` appends one JSON line per query to
`~/.cache/cs-queries.jsonl` recording `outcome` (`hits`/`zero`/`refused`),
answer kind, engine, hit count and latency — which is how a refusal rate or an
answer-kind mix becomes answerable over a window longer than this session.

Only enable it if asked. In a private fleet the query string is the proprietary
part, so it is hashed by default; `CS_LOG_QUERY=omit` drops it entirely and
`plain` keeps it. Tell the user which of those they are getting rather than
turning it on quietly.

Refusals emit the envelope too, with `refused: true` and the reason — that is
the case with no result stream to attach anything to, and the one you most need
to detect. `hits` is how many exist and `returned` how many are in `results`;
if they differ the answer was capped. stderr is unchanged, so `--porcelain`
composes with `--quiet` rather than replacing it.

## Finding a cause in another repo

When something breaks and nothing in its own repo changed, the trigger is in a
repo whose history is not reachable from where you are standing. `cs history`
spans the fleet and sorts by date, which puts the two changes side by side:

```sh
cs history 'reservationId'
# 2026-02-17  checkout-service-kotlin   7041e2d  PROJ-388: return the reservation id
# 2026-03-30  inventory-api-dotnet      a41c9e2  Bump serialization settings
```

It uses git's pickaxe (`-S`), which reports commits that changed the *number* of
occurrences — that is what separates the commit which introduced a seam from the
hundreds that merely touched the file. A change made **in place** leaves the
count identical and is invisible to `-S`, which is exactly the shape of a
formatting or serializer change; `cs` escalates to `-G` automatically and says
that it did. `--touched` forces `-G` from the start.

## Two levels: fleet and ticket workspace

The setup is a **fleet** directory holding every repo on main, plus a
**ticket workspace** holding worktrees of just the repos a ticket changes.
Search must span both, and `cs` does this automatically: run it from inside a
ticket workspace and it layers the ticket's repos (your branch state) over the
rest of the fleet (main).

```sh
export FLEET_ROOT=~/code/fleet TICKETS_ROOT=~/tickets
cd ~/tickets/PROJ-123 && cs uses "/api/v1/inventory/reserve"
# searching: PROJ-123 (2 repo(s), your branch) + fleet (8 repo(s), main)
```

This matters more than it sounds. Searching **only** the ticket makes renaming a
shared route look safe, because the caller that breaks lives in a repo the
ticket does not contain. Searching **only** the fleet shows stale copies of the
files you are editing. Both answers are wrong in ways that do not announce
themselves.

- `--fleet` ignores the ticket workspace entirely.
- `--ticket=<path>` layers a named workspace instead of the one you are standing
  in. Pass the absolute path of the workspace or of any directory inside it
  (your own working directory works); a bare folder name also works when it is
  unique. It **fails** if the path is outside every workspace root
  (`TICKETS_ROOT`, `WORKSPACE_ROOTS`), inside the fleet, or holds no repos,
  rather than falling back to the fleet. That fallback would be the same mistake
  inverted — you asked for branch state and would have been handed main. If you
  get that error, run `cs scopes` instead of dropping the flag.
- Run from a repo outside every workspace root, `cs` answers from the fleet and
  warns that the repo you are in is not searched. Take that warning at its word.

Always read the `searching:` line before trusting a layered answer. If it is
absent, no ticket was layered and every hit came from the fleet.

`cs scopes` lists the fleet and every workspace, by path, with its repo count. Use
it when you are **not** standing in a workspace — the layering is resolved from
the working directory, so anything invoking `cs` from somewhere else has to
choose a scope explicitly rather than let it be inferred.

## The distinctions that matter

**Substring matches, and the warning they used to delete.** All three text
subcommands match substrings by default, so `AccessionUpdateIn` also matches
`AccessionUpdateInput` in an unrelated repo. That is usually harmless noise —
except for `cs seam`'s orphan warning ("only one repo mentions this — a producer
with no consumer, or dead"), where an extra hit does not add noise, it *deletes
the warning*, flipping the reading from "this looks dead" to "two repos use it".
`cs` now computes that warning on whole-identifier matches and tells you when
hits matched inside a longer name:

```
! only one repo mentions this as a whole identifier (lims) -- a producer with no consumer, or dead
! 1 repo(s) matched only INSIDE a longer identifier: cx-graph — not whole-word
```

Pass `--word` to search whole identifiers only. It is **not** the default,
because it would drop `reserve` inside `reserveItem` — a real use — and a silent
false negative is the failure this tool is organised against. Report the
distinction rather than assuming either reading.

**`cs uses` vs `cs seam` vs `cs text`.** All three search strings, but:
`cs text` returns everything including comments; `cs seam` groups by repo and
warns when only one repo mentions a string (the shape of a dead endpoint or an
orphaned consumer); `cs uses` excludes comments and docstrings, so it answers
"who actually calls this" rather than "who mentions this". For "is this
endpoint still used", `cs uses` is the right one and the other two will mislead
you.

**Two same-named symbols in different repos.** Code search cannot tell them
apart — the answer is in build manifests, not code. Resolve the dependency
first, then filter:

```sh
cs def DiscountEngine "$(cs provides com.acme:pricing-lib)"
```

## The two questions that follow a search result

Both read manifests and CODEOWNERS rather than code, so both are `declared` —
the strongest kind for a negative, and the one most likely to be repeated to a
person as fact. Reach for them when a result raises "so who do I tell" or "is
everyone on the same version".

**`cs owns <repo>/<path>`** — who CODEOWNERS names, applying **last-match-wins**
as git does, and printing the rule that matched so you can judge whether it was
meant to cover that file:

```
inventory-api-dotnet/src/Infrastructure/SqlInventoryStore.cs	@acme/storage-team	.github/CODEOWNERS:4 [/src/Infrastructure/]
```

`cs owns` with no argument audits the fleet. A repo with **no** CODEOWNERS is
reported on stderr as a gap, not on stdout as an answer — "nobody owns it" is
not a conclusion this can reach. Never relay an owner as "the person who knows
this code": it is who is required to review, which is a different claim, and the
team named may no longer exist.

**`cs versions [coordinate]`** — which version each repo pins, flagged `AGREED`,
`DRIFT`, or `UNPINNED`. It reads Gradle (inline and `gradle/libs.versions.toml`),
Maven, npm, `pyproject.toml` (parsed as TOML, PEP 508 extras and all), and NuGet
(`PackageReference`, `Directory.Packages.props`, `packages.config`). A manifest
it finds but does not parse (`go.mod`, `requirements.txt`, …) is named on the
answer as **not read**. That repo's absence is not a finding. A shared contract library at two versions across a seam
is a real bug shape, and it is invisible to every search engine here because the
evidence is in manifests rather than in code:

```
acme-schemas	DRIFT	2 version(s)	external
  fulfillment-worker-python	==2.4.0	pyproject.toml
  web-monorepo-node	2.5.1	package.json
```

Versions are compared on the number, not the spelling, so `==2.4.0` and `2.4.0`
report as `AGREED` rather than as a false drift. Package **names** are compared
per ecosystem too — PEP 503 for PyPI (`Kit Service`, `kit_service` and
`kit-service` are one package), case-insensitively for npm and NuGet, and
**exactly** for Maven, whose coordinates are case-sensitive. When a match needs
normalizing, `cs` says what the manifest actually declares, because a name that
needs it is usually a small bug in that repo too. It reads **manifests, not
lockfiles** — two repos agreeing here can still resolve differently at build
time, so report drift as a declaration mismatch, never as proof of what is
installed.

## Known blind spots — do not oversell an answer

- **Cross-repo, cross-language relations are strings.** A Kotlin service calling
  a .NET endpoint is connected only by the route literal. `cs uses` finds those
  seams; nothing resolves them symbolically. Say so rather than implying a
  verified call graph.
- **Runtime indirection defeats static analysis.** DI registration, reflection,
  and dynamically built identifiers are invisible. `cs refs` bridges DI
  *registration* because a language server sees the type arguments, but a
  container resolving by string name is beyond every tool here. The honest
  answer names the interface and says the implementation is resolved at runtime.
- **`cs def` uses ctags**, which indexes declarations, not semantics. It will
  not find a symbol assembled at runtime, and it does not distinguish
  overloads. `cs refs` is the precise-but-slow alternative. Where universal-ctags
  is not installed, `cs def` falls back to any tokensave graphs in the view, and
  `--engine=tokensave` asks for them deliberately. Read the coverage warning
  when it does: ctags indexes the whole view in one pass, while graphs are
  **per-repo**, so a definition living in a repo with no graph is reported as
  absent. `cs` names those repos — treat that list as the boundary of the
  answer. The two engines agree on the defining file but can differ by a line,
  since a graph includes a decorator or attribute in the symbol's range.
- **`cs def` reuses its index for 60 seconds.** The key is the commit each repo
  is on, so a fleet refresh or a branch change invalidates it — but *uncommitted*
  edits do not. The answer line says how old the index is; pass `--refresh` after
  editing a file you are about to look up. Measured 5.9s cold and 0.74s reused
  on a 456k-line fleet, which is why it is cached at all.
- **`grep` may not be the `grep` you tested with.** In an agent shell, `grep`
  and `rg` can be shell functions proxying a bundled ripgrep; a *script* gets
  the real system binary instead. BSD `grep -R` follows a symlink named on the
  command line but not one met while recursing, so a naive recursive search
  over a symlinked view silently finds nothing. `cs` passes repo directories
  explicitly to avoid depending on that behaviour at all — but the lesson
  generalises: verify search changes by running the script, not by running the
  command interactively.
- **A clean result is not proof of absence.** For "is this dead", check with
  `cs uses` *and* `cs seam` before concluding, since a caller may construct the
  string rather than write it literally. The answer kind tells you how much the
  empty result is worth; a `textual` or `heuristic` negative is close to nothing.
- **A structural engine returns nothing for a language it cannot parse**, which
  looks identical to "no matches". Name the language (`cs calls '<pat>' csharp`)
  to turn that silence into an error.
- **`resolved` needs a language toolchain, not just Serena.** `cs impls` and
  `cs refs` preflight the repo's dominant language against the runtime its
  server needs (C# → `dotnet`, Kotlin → `java`, TS/JS → `node`; Java needs
  none, its server bundles a JRE) and refuse when it is absent — **unless** a tokensave graph exists for that repo, in
  which case `cs impls` falls back to it and labels the answer `structural`.
  The toolchain question is asked about the **symbol's** language (found via the
  ctags index), not the repo's most-common one, so a mostly-JavaScript repo with
  a C# component still routes correctly. `--engine=tokensave` forces the graph;
  an `--engine` a subcommand cannot serve is refused rather than ignored.
  That matters where the toolchain is missing or cannot be installed. (Legacy
  .NET Framework C# is not such a case: the .NET SDK loads it on macOS and
  Linux too, minus its reference assemblies, so framework and package types do
  not resolve while the repo's own do.) A graph answer is weaker in a specific
  way — it cannot see reflection, DI registration, or generated code, and
  `cs refs` remains the only thing that bridges a DI registration. It also
  answers about the code as of its last sync, so `cs` states the graph's age on
  every such answer; treat a stale graph as a source of confidently *wrong*
  answers rather than merely blind ones. A language *outside* that mapping — Python, Go, Rust — is
  not preflighted: `cs` warns that it did not check, and an empty result there
  may still mean the project failed to load. Check `cs doctor` before treating
  such a negative as strong.
- **Symbol mode answers about one repo at one layer.** `cs callers`, `cs callees` and
  `cs impact` read a tokensave graph, and a graph index is **per-project**: the
  workspace copy of a repo has its own, the fleet copy has its own, and *there is
  no union*. So these cannot deliver what `cs uses` delivers — a caller in
  another repo of the fleet is a string, not an edge, and is invisible here.
  Always pair a symbol answer with `cs uses '<symbol>'` before telling anyone
  something is unused. **In C# and Kotlin this is not optional:** tokensave's
  graph has no edges out of property accessors, so a method called only from a
  getter shows no callers. `cs` names that on every such answer and marks a zero
  `degraded`; `cs uses '<symbol>' --word` finds those calls. The answer line names **which** index answered and how
  old it is (`scoped to <repo>; ticket layer, synced 2d ago`); when the scope was
  a ticket workspace and the fleet index answered instead, `cs` reports that as
  `degraded` — the answer then describes `main`, not the branch being edited, and
  must be passed on with that caveat rather than as the state of the code.
  A stale graph is a source of confidently *wrong* answers, not merely blind
  ones. `cs callers` and `cs callees` return **direct** edges only; `cs impact`
  walks transitively to depth 3 and says so.
- **Symbol mode fronts three graph questions, not ninety.** The tool behind it
  also answers dead code, coupling, complexity, blame, test mapping, call chains
  and inheritance depth. `cs` deliberately does not wrap those: for anything
  deeper than the three, say so and use the graph tool directly
  (`tokensave tool <name>`) rather than reporting that `cs` could not answer.
- **`cs uses` filters comments by file extension**, so its coverage is a table
  rather than a parser: 106 extensions plus 13 well-known filenames. A file in
  a language outside the table is passed through unfiltered and *named* in the
  answer line (`prose filtered except: .erl`). When you see that, the hits in
  those files are `cs seam` quality, not `cs uses` quality.
- **Some directories are never searched.** `node_modules`, `target`, `dist`,
  `vendor`, `bin`, `obj` and similar are excluded fleet-wide, and an excluded
  directory looks exactly like one with no hits. `cs engines` prints the
  effective list. Some layouts keep hand-written source in `bin` or real
  dependencies in `vendor` — if a file you know exists is not being found, check
  the list and rerun with `CS_EXCLUDE_REMOVE="bin vendor"`.

## Verifying it works

It ships a fixture fleet with known-correct answers, including decoys designed
to catch over-eager tools. `ROOT` below is `${CLAUDE_PLUGIN_ROOT:-.}`:

```sh
ROOT="${CLAUDE_PLUGIN_ROOT:-.}"
"$ROOT/scripts/build-fixtures" /tmp/fixture-fleet
export FLEET_ROOT=/tmp/fixture-fleet
"$CS" uses "/api/v1/inventory/reserve" | "$ROOT/scripts/score-seams" reserve-consumers -
```

`score-seams --list` shows all nine queries. `fixtures/BASELINE.md` records how
each engine scores alone, and `fixtures/GROUND-TRUTH.md` explains what each
query is testing.

**Three layers:**

```sh
"$ROOT/scripts/verify-search"    # end-to-end: does the facade still answer all nine?
"$ROOT/scripts/verify-engines"   # per-engine: is each engine still doing its job?
"$ROOT/scripts/bench-scale"      # what it costs on a generated 456k-line fleet
```

`verify-engines` exists because **the facade hides engine regressions**:
`cs calls` falls back from ast-grep to semgrep, so ast-grep could break
entirely and the end-to-end run would still score 9/9. Each engine is therefore
probed directly on the one capability the routing depends on it for.

`verify-search` also has a **refusals** section, which tests that `cs` refuses
rather than that it answers. Those are different properties, and only the second
protects what this tool claims: a missing python3, a typo'd `--ticket`, or two
`cs def` calls issued in parallel all used to yield a confident empty answer
while every scored query still passed. If you are diagnosing a suspicious
negative result, run `verify-search` — it reproduces each of those directly.

Run both after upgrading any tool. `verify-engines` compares against
`fixtures/verified-versions.tsv` and flags version changes as a prompt to look,
not as a failure. `--update` records a new baseline once you have reviewed the
results.

It can also probe **known limitations**, not just capabilities: a probe that
starts passing reports `IMPROVED`, because upgrades can remove the reason a tool
was rejected and nothing else would notice. There are none at present. tokensave's
C# interface edges were one until the routing was revisited and `cs impls` began
falling back to the graph; they are now a capability, and losing them is a
regression. The same goes for Serena's Java server running without a JDK.

## Reporting results

Give file paths as `repo/path:line`, which is the format `cs` already emits and
which stays clickable.

**Carry the answer kind into what you tell the user.** `cs` prints it precisely
so it does not have to be guessed at: an answer that rests on a string match
across a repo boundary is a textual link, not a resolved reference, and saying
"the only caller is X" on `textual` evidence overstates what was actually
checked. Say which it was, and say when a result was `PARTIAL`, capped,
`degraded`, or `prose filtered except:` — a confident summary of an incomplete
search is the failure this whole setup exists to prevent.

**Read stdout and stderr as different things.** stdout is the result stream and
nothing else — every hit, one per line, and never a diagnostic. Provenance,
warnings, the `searching:` line, the per-repo distribution of a capped result,
and the comment-only mentions excluded from a zero-hit `cs uses` all go to
stderr. If you pipe `cs` anywhere, you get results only; if you are judging how
much an answer is worth, you need the stderr side too.
