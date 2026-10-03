# code-search-fleet

One search interface over many repositories, backed by whichever engine can
actually answer the question.

Across nine scored queries with known-correct answers, the best individual
engine gets **5/9**. This gets **9/9** — not by being cleverer, but by routing
each question to the engine suited to it and doing the few things none of them
do alone.

**Contents:** [Why](#why) · [Install](#install) · [Setting up a fleet](#setting-up-a-fleet) ·
[First queries](#first-queries) · [Commands](#commands) ·
[How far to trust an answer](#how-far-to-trust-an-answer) · [Honest limits](#honest-limits) ·
[Documentation](#documentation) · [License](#license)

## Why

No single search engine answers every question about a codebase:

- **ripgrep** cannot see a route assembled from two C# attributes, and counts a
  docstring mentioning an endpoint as a caller.
- **A symbol graph** cannot see a string literal in argument position — which
  is what cross-repo seams are made of.
- **An LSP** resolves an interface to its implementation, but needs a working
  toolchain per language and minutes to index.
- **None of them** read build manifests, so none can tell you which of two
  same-named classes another repo actually depends on.

Committing to one engine means accepting its blind spot permanently.

## Install

### As a Claude Code plugin

**New machine? Follow [docs/install.md](docs/install.md).** It is a numbered
checklist, with a check after each step, that a person or an agent can follow
top to bottom. In short:

1. Install: `claude plugin marketplace add agent-toolworks/plugins`, then
   `claude plugin install code-search@agent-toolworks`, and
   `fleet-workspace@agent-toolworks` for building the fleet.
2. Find the installed copy (`$CS_ROOT`, a one-liner in the guide), and run
   `"$CS_ROOT/scripts/bootstrap"` to install the engines.
3. Put the fleet's location in `~/.config/repo-fleet/fleet.env`, not in a shell
   `export`, because the MCP server reads that file and not your shell:
   `export FLEET_ROOT="$HOME/code/fleet"`. `fleet-init` from fleet-workspace
   writes it and clones the repos.
4. Run `"$CS_ROOT/scripts/cs" doctor` and fix every line it flags. Each one
   prints its fix, ready to paste.
5. Restart Claude Code from a new terminal, ask it to run `cs_doctor`, and check
   that it agrees with the terminal.

This repo is also its own marketplace, if you want only this plugin:
`claude plugin marketplace add agent-toolworks/code-search-fleet`, then
`claude plugin install code-search@code-search-fleet`.

**`repo-fleet` is the legacy catalog.** Installs made as `code-search@repo-fleet`
keep working. The catalog calls itself deprecated, so do not use it for a new
install. To move an existing install, run
`claude plugin uninstall code-search@repo-fleet` and then use the commands above.

Updating, the plugin cache, and running the installed scripts from a terminal:
[docs/updating.md](docs/updating.md). **Already using cs?** See
[what changed](docs/install.md#if-you-already-use-cs-what-changed), or run
`cs changes <the version you knew>` for every change since, small fixes included.

### From a clone

```sh
scripts/bootstrap                  # install engines (--check to only report), then cs doctor
export FLEET_ROOT=~/code/fleet     # a directory holding your repos (see below)
scripts/cs doctor                  # what will not work on YOUR repos, and the fix
scripts/verify-search              # the full suite, against a throwaway fixture fleet
```

Every check should pass. Checks for an engine you have not installed show as
skipped, not failed. The tokensave checks are verified on 7.9.0, 7.11.0 and
7.13.0.

From a clone, the skill is linked by hand:

```sh
ln -s "$PWD/skills/code-search" ~/.claude/skills/code-search
```

### Requirements

**Platforms.** Tested on macOS and Linux, which is also what CI runs on. The
scripts are bash, and `bootstrap` knows `brew`, `apt-get` and `dnf`. Native
Windows is not supported. WSL2 is untested, but it is Linux, so it should work
there. If you try it, keep the fleet on the Linux filesystem (`~/code/fleet`),
not under `/mnt/c`. Every search walks the whole fleet, and crossing into the
Windows filesystem makes that many times slower.

### What needs what

Only `python3` and a fleet root are required. Every engine is optional: without
one, the commands it backs refuse or fall back, and they say so, rather than
answering empty.

| For | You need | Without it |
|---|---|---|
| every search | `FLEET_ROOT`: a directory of git clones | every search refuses (`which`, `why`, `engines`, `doctor` still run) |
| `uses` `provides` `deps` `publishes` `versions` `owns` `impls` `refs` `fields`, symbol mode | `python3` | those commands refuse |
| Gradle version catalogs and `pyproject.toml` as TOML (`versions`, `deps`) | `python3` ≥ 3.11 (`tomllib`) | catalogs are not read (the answer names them); `pyproject.toml` is read by a fallback scanner |
| `text` `seam` `uses` | ripgrep | POSIX grep: the same answers, slower |
| `calls` | ast-grep, or semgrep | refuses |
| `def` | universal-ctags | falls back to tokensave graphs, or refuses |
| `callers` `callees` `impact`, and `impls` where no toolchain can run | tokensave, and a graph in each repo (`tokensave init`) | refuses in repos without a graph |
| `impls` `refs` (a `resolved` answer) | uv, which runs Serena, and the language's toolchain below | refuses |
| `history` | git | unavailable |
| `gaps` | `gh`, authenticated | refuses |
| a time limit on a hung engine | `timeout(1)` (`brew install coreutils`) | a hung language server hangs `cs` |

`impls` and `refs` start a language server, and each language needs its own
toolchain. Only the languages your fleet contains matter:

| Language | Needs | Notes |
|---|---|---|
| C# | the .NET SDK (`dotnet`) | legacy .NET Framework projects load too, on macOS and Linux, without their reference assemblies: types from the framework and its packages do not resolve, the repo's own types and references do. Without the SDK, `impls` falls back to a tokensave graph |
| Java | nothing | Serena's Java server ships its own runtime |
| Kotlin | only for a build that requests a Gradle toolchain (`jvmToolchain(21)`, its own or an `includeBuild`'s): a JDK of exactly that version, findable through `JAVA_HOME` | a build pinned only by `sourceCompatibility` / `jvmTarget` needs no JDK: the Kotlin server builds it on its own runtime. Where a requested JDK is not findable, `cs` refuses, because the server would answer empty. Homebrew's `openjdk@N` is keg-only, so set `JAVA_HOME` to it |
| TypeScript, JavaScript | node | |
| Python, Go, Rust | not checked by `cs` | an empty answer there is not proof of absence |

**`cs doctor` checks all of this against your fleet.** It lists each engine and
each language your repos contain, marks what will not work here, and says what
it costs and how to fix it. It exits 3 when it flags anything. Over MCP it is
`cs_doctor`. The MCP server sees the environment Claude Code started with, so
after changing `PATH` or `JAVA_HOME`, restart Claude Code. `cs engines` is the
shorter view: what is installed, and which answer kinds work.

## Setting up a fleet

A fleet is a directory with one clone per repository, kept on `main`. `cs`
searches whatever is there. It does not clone anything itself.

Put the location in `~/.config/repo-fleet/fleet.env`:

```sh
export FLEET_ROOT="$HOME/code/fleet"     # one clone per repo
export TICKETS_ROOT="$HOME/tickets"      # per-ticket worktree workspaces (optional)
export WORKSPACE_ROOTS="$HOME/reviews"   # more workspace roots, colon-separated (optional)
export CS_NO_GRAPH="big-legacy-repo"     # repos kept without a tokensave graph on purpose (optional)
```

**This file is what the MCP server reads.** The server that the plugin registers
is started by Claude Code, not from your shell. Whether a `FLEET_ROOT` exported in
your shell profile reaches it depends on how Claude Code was launched. `cs` and
`cs-mcp` both source `fleet.env` on every call, so it is the one setting both
always see. The precedence is environment, then `fleet.env`, then the default
`~/code/fleet` (see `scripts/lib/common.sh`). An exported `FLEET_ROOT` still wins
in a shell where it is set.

To build and maintain the fleet itself, use `fleet-init` from the
`fleet-workspace` plugin. `fleet-init --config` writes the file above,
`--clone <org/repo>…` fills the fleet, and `--cron` prints the daily refresh
line. The steps are in repo-fleet's
[GETTING-STARTED.md](https://github.com/agent-toolworks/repo-fleet/blob/main/GETTING-STARTED.md),
which also covers ticket workspaces. If you do not use `fleet-workspace`, any
directory of clones works. Keep it up to date yourself, because `cs` answers from
whatever is checked out.

## First queries

From a terminal, in a clone. For a plugin install, run `"$CS_ROOT/scripts/cs"`,
with `$CS_ROOT` resolved as in
[docs/updating.md](docs/updating.md#running-the-scripts-from-a-terminal):

```sh
scripts/cs which                   # which subcommand answers what
scripts/cs uses "/api/v1/orders"   # who uses this string, in code only
```

From an agent, over MCP. Every tool that reads the fleet takes an explicit `scope`,
and `cs_scopes` lists the values:

```jsonc
mcp__plugin_code-search_cs__cs_uses   {"scope": "fleet", "query": "/api/v1/orders"}
```

Either way the answer says what was searched and what kind of answer it is:

```
searching: PROJ-123 (2 repo(s), your branch) + fleet (8 repo(s), main)
answer: heuristic via ripgrep (literal, prose filtered) · 2 hit(s) · 2 repo(s)
```

Tool names, argument names per tool, and why `scope` is required:
[docs/mcp.md](docs/mcp.md).

## Commands

| Question | Command |
|---|---|
| Who calls/uses this endpoint, topic, config key | `cs uses <string>` |
| Which repos share this string | `cs seam <string>` |
| Any text or regex, comments included | `cs text <pattern>` |
| Where is a symbol defined | `cs def <symbol> [repo]` |
| Calls shaped like X, or taking literal Y | `cs calls '<pattern>' [lang]` |
| Where a type is constructed, all idioms | `cs constructs <Type> [repo]` |
| What implements this interface | `cs impls <symbol> <repo>` |
| What calls this symbol | `cs callers <symbol> <repo>` |
| What this symbol calls | `cs callees <symbol> <repo>` |
| What breaks if I change this symbol | `cs impact <symbol> <repo>` |
| Who reads or writes this field, fleet-wide | `cs fields <field> [repo]` |
| How big is that field's blast radius | `cs fields <field> --count` |
| Which repos even have this, before paying for hits | `cs text\|seam\|uses <q> --count` |
| What references this symbol (bridges DI) | `cs refs <symbol> <repo> <file>` |
| Which repo publishes this package | `cs provides <coordinate>` |
| Which repos depend on which | `cs deps [repo]` |
| Which version each repo pins, and where they disagree | `cs versions [coordinate]` |
| Who to ask about this repo or file | `cs owns [repo\|repo/path]` |
| Who crashes if I add a field to a response | `cs strictness [repo]` |
| Who even reads an error body, and who retries | `cs resilience [repo]` |
| Who sets this config key, and who reads it | `cs values <KEY> [repo]` |
| What the org has that the fleet does not | `cs gaps <query>` |
| When a seam appeared, or last changed | `cs history <string> [repo]` |
| What is actually being searched | `cs repos` |
| Which workspaces there are to search | `cs scopes` |
| How much to trust an answer | `cs why [kind]` |
| What will not work on this machine, and the fix | `cs doctor` |
| What changed since the version I knew | `cs changes [version]` |

## How far to trust an answer

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

The long version, with the incident behind each behaviour, is
[docs/answer-kinds.md](docs/answer-kinds.md):

- [And it refuses rather than answering empty](docs/answer-kinds.md#and-it-refuses-rather-than-answering-empty)
- [And a refusal is detectable, not merely explained](docs/answer-kinds.md#and-a-refusal-is-detectable-not-merely-explained)
- [And the metadata is available as data](docs/answer-kinds.md#and-the-metadata-is-available-as-data)
- [And `cs engines` reports answer kinds, not just binaries](docs/answer-kinds.md#and-cs-engines-reports-answer-kinds-not-just-binaries)
- [And where no language server can run, a graph answers instead](docs/answer-kinds.md#and-where-no-language-server-can-run-a-graph-answers-instead)
- [The field-level impact question, split by access kind](docs/answer-kinds.md#the-field-level-impact-question-split-by-access-kind)
- [Who can even OBSERVE an error contract](docs/answer-kinds.md#who-can-even-observe-an-error-contract)
- [The same split for a config key, across a repo boundary](docs/answer-kinds.md#the-same-split-for-a-config-key-across-a-repo-boundary)
- [The corpus bounds a negative, not just the search](docs/answer-kinds.md#the-corpus-bounds-a-negative-not-just-the-search)
- [A text answer says how much of itself is data](docs/answer-kinds.md#a-text-answer-says-how-much-of-itself-is-data)
- [Counts first, when hits cost something](docs/answer-kinds.md#counts-first-when-hits-cost-something)
- [Saved queries are consumers, and they fail silently](docs/answer-kinds.md#saved-queries-are-consumers-and-they-fail-silently)
- [And the same graph answers the symbol half of a question](docs/answer-kinds.md#and-the-same-graph-answers-the-symbol-half-of-a-question)

## Honest limits

- Cross-repo, **cross-language** relations are strings. `cs uses` finds them;
  nothing resolves them symbolically. Report such links as textual matches.
- Runtime indirection — DI resolved from config, reflection, identifiers built
  at runtime — is undecidable statically at any budget.
- Symbol mode is **per-repo, at one layer**. A graph index spans neither the
  fleet nor your ticket workspace, so `cs callers` finding nothing rules out
  callers in *that repo* and nothing else. Pair it with `cs uses` before calling
  anything dead.
- 9/9 on this fixture means the test set is exhausted, not that search is
  solved. The real measure is a query set drawn from your own tickets.
- Result caps and timeouts mean an answer can be partial. `cs` says so when it
  is, which is the mitigation — not a guarantee that it is not.

## Documentation

| | |
|---|---|
| [docs/install.md](docs/install.md) | **start here on a new machine**: step by step, what `cs doctor` flags and the fix, what changed for existing users |
| [docs/answer-kinds.md](docs/answer-kinds.md) | every answer kind, refusal and disclosure, and why each exists |
| [docs/mcp.md](docs/mcp.md) | the MCP server: tool names, calling the tools, the required scope, manual registration |
| [docs/updating.md](docs/updating.md) | updating the plugin, version mechanics, `CS_ROOT`, the version gate, cutting a release |
| [docs/tuning.md](docs/tuning.md) | environment variables, the two levels (fleet and ticket), the opt-in query log |
| [docs/verifying.md](docs/verifying.md) | `verify-search`, `verify-engines`, the fixture, layering in your own incidents |
| [skills/code-search/SKILL.md](skills/code-search/SKILL.md) | the agent's entry point: setup, routing, blind spots, verification |
| [CHANGELOG.md](CHANGELOG.md) | what changed in each version |
| [fixtures/BASELINE.md](fixtures/BASELINE.md) | how each engine scores alone on the fixture |

## License

[Apache-2.0](LICENSE). Chosen over MIT for the explicit patent grant, which is
what makes a corporate legal review a formality rather than a conversation —
this is tooling meant to be installed on work machines and pointed at a
company's source, so "may we use this" needs an answer that is already written
down. Without a LICENSE file the default is all rights reserved, which blocks
not just use but vendoring, internal mirroring, and redistribution through an
internal plugin marketplace.
