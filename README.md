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

Install from the agent-toolworks catalog. It lists this plugin next to
`fleet-workspace`, which builds and maintains the fleet (see
[Setting up a fleet](#setting-up-a-fleet)):

```sh
claude plugin marketplace add agent-toolworks/plugins
claude plugin install code-search@agent-toolworks
claude plugin install fleet-workspace@agent-toolworks   # optional: fleet-init, ticket workspaces
```

This repo is also its own marketplace, if you want only this plugin:

```sh
claude plugin marketplace add agent-toolworks/code-search-fleet
claude plugin install code-search@code-search-fleet
```

**`repo-fleet` is the legacy catalog.** Installs made as `code-search@repo-fleet`
keep working. The catalog calls itself deprecated, so do not use it for a new
install. To move an existing install, run
`claude plugin uninstall code-search@repo-fleet` and then use the commands above.

Then tell it where the fleet is. `~/.config/repo-fleet/fleet.env` is the one
place both the CLI and the MCP server read (see
[Setting up a fleet](#setting-up-a-fleet)):

```sh
export FLEET_ROOT=~/code/fleet     # the directory holding your repos
```

Updating, the plugin cache, and running the installed scripts from a terminal:
[docs/updating.md](docs/updating.md).

### From a clone

```sh
scripts/bootstrap                  # install engines (--check to only report)
export FLEET_ROOT=~/code/fleet     # a directory holding your repos (see below)
scripts/verify-search              # 200+ checks against a throwaway fixture fleet
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

Every *engine* is optional; `cs engines` reports what is present and `cs` routes
around what is missing rather than failing silently.

**`python3` is the one hard requirement** — `uses`, `provides`, `deps`,
`publishes`, `versions`, `owns`, `impls`, `refs`, `fields` and symbol mode all
run through it. It is separate from the engines because it does not degrade:
those commands refuse rather than answer without it. Nothing installs it for you
(a system python is the OS's business), but `bootstrap` and `cs engines` both
report it.

`timeout(1)` is worth having too. Without it a hung language server hangs `cs`
with no upper bound, and a search that never returns is the one outcome worse
than a wrong one, because nothing reports it. `brew install coreutils` on macOS.

## Setting up a fleet

A fleet is a directory with one clone per repository, kept on `main`. `cs`
searches whatever is there. It does not clone anything itself.

Put the location in `~/.config/repo-fleet/fleet.env`:

```sh
export FLEET_ROOT="$HOME/code/fleet"     # one clone per repo
export TICKETS_ROOT="$HOME/tickets"      # per-ticket worktree workspaces (optional)
export WORKSPACE_ROOTS="$HOME/reviews"   # more workspace roots, colon-separated (optional)
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
