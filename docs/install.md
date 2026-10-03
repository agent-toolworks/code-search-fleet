# Installing on a new machine

[← README](../README.md)

Follow these steps in order, as a person or as an agent asked to "install code
search". Every step ends with a check, and the last check is `cs doctor`
reporting nothing to fix. About 15 minutes, most of it package installs.

What you end up with:

- the `code-search` plugin: the skill, and the `cs_*` MCP tools;
- the search engines `cs` routes between;
- a **fleet**: one directory holding a clone of each repository, named in
  `~/.config/repo-fleet/fleet.env`;
- a clean `cs doctor`, checked once from a terminal and once over MCP.

## 1. Install the plugins

```sh
claude plugin marketplace add agent-toolworks/plugins
claude plugin install code-search@agent-toolworks
claude plugin install fleet-workspace@agent-toolworks   # fleet-init: builds and refreshes the fleet
```

**Check:** `claude plugin list` shows both.

The skill and the `cs_*` tools load only when Claude Code restarts (step 6).
Until then, run the installed scripts directly, as below.

## 2. Find the installed copy

A plugin install does not put `cs` on `PATH`:

```sh
CS_ROOT=$(ls -d ~/.claude/plugins/cache/*/code-search/*/ 2>/dev/null \
  | awk -F/ '{v=$(NF-1); print (v ~ /^[0-9]+(\.[0-9]+)*$/ ? v : "0"), $0}' \
  | sort -V -k1,1 | tail -1 | cut -d' ' -f2-)
[ -n "$CS_ROOT" ] || echo 'code-search is not installed: see claude plugin list'
"$CS_ROOT/scripts/cs" doctor | head -3
```

**Check:** the `cs` row names the version and the path it runs from. Every
later step uses `$CS_ROOT`. It works whichever catalog installed the plugin
(`agent-toolworks`, this repo's own, a team catalog). It picks the highest
version across them, and a folder named after a pinned commit only when there is
nothing else. Why that matters: see
[updating.md](updating.md#running-the-scripts-from-a-terminal).

## 3. Install the engines

```sh
"$CS_ROOT/scripts/bootstrap"          # --check to only report
```

It installs ripgrep, universal-ctags, ast-grep and semgrep with `brew`,
`apt-get` or `dnf`, and reports python3, uv and the language toolchains. It
ends by running `cs doctor`. Expect that report to flag the fleet until step 4
is done.

tokensave, uv and `gh` are not installed by `bootstrap`. `cs doctor` gives the
command for each one that is missing.

## 4. Set up the fleet

The fleet's location goes in **`~/.config/repo-fleet/fleet.env`**, not in a
shell `export`. The MCP server is started by Claude Code, not by your shell, and
this file is the one setting that both it and the CLI always read.

**With fleet-workspace** (recommended), restart Claude Code and say: *"Set up the
repo fleet in ~/code/fleet, tickets in ~/tickets, and clone acme/a, acme/b"*.
It runs:

```sh
fleet-init --config --fleet-root ~/code/fleet --tickets-root ~/tickets
fleet-init --clone acme/a acme/b      # uses gh, so private repos work; re-run to add repos
fleet-init --cron                     # prints the daily refresh line for crontab
```

**By hand:**

```sh
mkdir -p ~/.config/repo-fleet ~/code/fleet
echo 'export FLEET_ROOT="$HOME/code/fleet"' >> ~/.config/repo-fleet/fleet.env
git clone git@github.com:acme/a.git ~/code/fleet/a
```

**Ticket workspaces** (optional) are a second level: a folder per ticket under
`TICKETS_ROOT`, holding worktrees of only the repos that ticket changes, which
`cs` layers over the fleet. Further roots, such as a `_reviews/` beside
`_tickets/`, go in `WORKSPACE_ROOTS`, colon-separated. All three settings, and
`CS_NO_GRAPH` for repos kept without a tokensave graph on purpose, are in
[Setting up a fleet](../README.md#setting-up-a-fleet).

**Check:** in `"$CS_ROOT/scripts/cs" doctor`, the `fleet` row reads `✓ … N
repo(s)`, and the `workspaces` row lists each root with its workspace count. A
folder in the fleet that is not a git clone is listed as not searched. A
configured workspace root that does not exist is flagged.

## 5. Fix what `cs doctor` flags

```sh
"$CS_ROOT/scripts/cs" doctor          # exit 0: nothing to fix; exit 3: something flagged
```

Every `!` or `✗` line says what it costs and gives a fix. Where the fix is a
line for your shell profile, it is printed ready to paste, for the shell you use.
The [table below](#what-cs-doctor-says-and-what-to-do) lists the common ones.
It checks only the languages your fleet actually contains, so a machine with no
Kotlin repos is never asked for a JDK.

**If you are an agent:** shell profiles (`~/.zprofile`, `~/.zshrc`) and
`~/.config` are often outside what you are permitted to edit. Do not look for a
way around that. Give the user the exact line, prefixed with `!`, so they can
run it in this session, then re-run `cs doctor`.

**Check:** `cs doctor` exits 0, or flags only what the user chose to leave. A
repo kept without a tokensave graph on purpose belongs in `CS_NO_GRAPH`, and
then it is not flagged.

## 6. Restart Claude Code, and check again over MCP

Restart Claude Code from a **new terminal**, so it starts with the profile
changes from step 5. Then ask it to *"run cs_doctor"*.

**Check:** the result matches the terminal's. The MCP server keeps the
environment Claude Code started with. So if the terminal is clean and
`cs_doctor` is not, Claude Code started without the fix. The desktop app,
launched from the Dock, does not read shell profiles at all. Start Claude Code
from a terminal, or put the variable where GUI apps see it
(`launchctl setenv JAVA_HOME …` on macOS).

## 7. First query

Ask Claude a cross-repo question: *"where is `<a class you know>` defined across
the repos?"*, or *"who calls the `/orders` endpoint?"*. The answer ends with a
provenance line saying which kind of evidence it rests on. See
[How far to trust an answer](../README.md#how-far-to-trust-an-answer).

From inside a ticket workspace, the same question answers from your branch
layered over the fleet. Over MCP, the `scope` is the workspace's absolute path,
and your own working directory at any depth works:

```sh
"$CS_ROOT/scripts/cs" --ticket="$PWD" uses '/orders'    # or: cs_uses {"scope": "<that path>", ...}
"$CS_ROOT/scripts/cs" scopes                              # every workspace, by path
```

Optionally, to prove the tool itself on this machine:

```sh
"$CS_ROOT/scripts/verify-search"      # the full suite, on a throwaway fixture fleet, a few minutes
```

## What `cs doctor` says, and what to do

| It says | Do |
|---|---|
| `✗ fleet  root does not exist` / `no repositories in …` | step 4 |
| `fleet … not git repos, so not searched: x` | `x` is not a clone. Clone it properly, or move it out |
| `! python3 … older than 3.11` | put a newer Python first on `PATH`. On macOS with Homebrew the printed fix is `echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile`. `/usr/bin` otherwise wins with Apple's 3.9, which cannot read Gradle version catalogs |
| `! Kotlin … request a JDK N toolchain … installed but keg-only` | paste the printed `export JAVA_HOME=…` line. Homebrew's JDKs are invisible until `JAVA_HOME` points at them |
| `! Kotlin … request a JDK N toolchain, and none is findable` | `brew install openjdk@N`, then the printed `JAVA_HOME` line. It must be **that** version: with another, the Kotlin server answers *empty*, so `cs` refuses. The request can come from a build the repo includes (`includeBuild`) |
| `✓ Kotlin … request no Gradle toolchain` | nothing to do: a build pinned only by `sourceCompatibility` / `jvmTarget` is built on the Kotlin server's own runtime, with no JDK |
| `! C# … no runnable dotnet` | `brew install --cask dotnet-sdk`. It loads legacy .NET Framework projects too, on macOS and Linux, without their reference assemblies: framework and package types do not resolve, the repo's own do. Meanwhile `cs impls --engine=tokensave` answers where a graph exists |
| `! TypeScript` / `JavaScript … no runnable node` | `brew install node` |
| `? Python` / `Go` / `Rust` | not checked by `cs`. An empty `cs impls` / `cs refs` there is not proof of absence |
| `! tokensave  MISSING` / `graphs in N of M repo(s)` | `brew install aovestdipaperino/tap/tokensave`, then `cd <repo> && tokensave init` in each repo. fleet-workspace's refresh keeps graphs synced. A repo left unindexed **on purpose** goes in `CS_NO_GRAPH="…"` in `fleet.env`, and stops being flagged |
| `! workspaces  configured but missing` | create the directory, or correct `TICKETS_ROOT` / `WORKSPACE_ROOTS` in `fleet.env`. `--ticket=` and an MCP `scope` under it refuse otherwise |
| `! serena  uv MISSING` | `brew install uv` |
| `! forge  … not authenticated` | `gh auth login` |
| `! ripgrep` / `structural` / `ctags` / `timeout` | re-run `bootstrap`, or the printed `brew install` |

Java needs nothing: Serena's Java server ships its own runtime.

## Updating later

```sh
claude plugin marketplace update agent-toolworks
claude plugin update code-search@agent-toolworks
```

Then restart Claude Code and run `cs_doctor` again. A new version can need
something new. See [updating.md](updating.md).

<a id="if-you-already-use-cs-what-changed-in-116117"></a>

## If you already use cs: what changed

For people, and for agents whose notes, `CLAUDE.md` or memory describe cs from
before 1.16. Update anything that says otherwise:

- **A scope is a path** (1.16.0, #59). Over MCP, and with `--ticket=`, the scope
  is the absolute path of the workspace you are working in, or of any directory
  inside it. A bare folder name still works when it is unique. Workspaces can
  live under several roots: `TICKETS_ROOT`, plus `WORKSPACE_ROOTS` (colon-
  separated), nested at any depth. `cs scopes` / `cs_scopes` lists them by
  path, and those paths are the values to pass. Notes that say "a scope is a
  folder name under `TICKETS_ROOT`" are out of date.
- **`cs doctor` / `cs_doctor` is the setup check** (1.17.0). Refusals now end
  with `check: cs doctor`; until 1.17.1 they said `cs engines`. `cs engines`
  still exists, as the shorter "what is installed" view. When a tool refuses,
  or `cs impls` / `cs refs` come back empty, run `cs_doctor` before concluding
  anything. It exits 3 when it flags something, a code of its own: not a
  refusal (1) and not a zero-hit answer (2).
- **Java needs no JDK** (1.16.2). cs used to refuse Java queries without one.
- **Kotlin needs a JDK only when its build requests a Gradle toolchain**
  (1.18.0). A `jvmToolchain(N)` request, the repo's own or one in a build it
  pulls in with `includeBuild`, needs a JDK of exactly N that Gradle can find,
  and `cs` refuses when there is none, because the server would answer empty.
  A build pinned only by `sourceCompatibility` / `jvmTarget` needs no JDK; cs
  refused those before 1.18 if `java` did not run. The refusal names the
  version, and gives the `JAVA_HOME` line when that JDK is installed but
  keg-only.
- **Legacy .NET Framework C# loads with the .NET SDK** (1.18.0), on macOS and
  Linux too, minus its reference assemblies. cs used to call that impossible.
- **`CS_NO_GRAPH`** in `fleet.env` (1.18.0) names repos kept without a tokensave
  graph on purpose, so `cs doctor` can come clean on a fleet that has them.
- **Language-server line numbers are 1-based** (1.18.1, #76). Every `cs impls`
  / `cs refs` address used to be one line short, the LSP's 0-based number.
  A `cs refs` line names its enclosing symbol (`[in Method Foo/Bar]`), where it
  printed only that symbol's kind.
- **An answer given before the project import finished is re-asked, or
  refused** (1.18.1, #76). Serena's Java wrapper stops waiting after 20s. `cs`
  now waits for the import and asks again, or refuses, so
  `resolved · 0 hit(s)` from a cold server is no longer possible.
- **A refusal's "answer now" is a command that runs** (1.18.1, #75): for
  `cs refs` it is `cs callers` (a method) or `cs impls --engine=tokensave` (a
  type), not a flag `cs refs` refuses.
- **C# and Kotlin graph answers name a hole in the graph** (1.19.1, #79).
  tokensave emits no edges out of property accessors, so a method called only
  from a getter has no callers in the graph. `cs callers` / `callees` /
  `impact` say so in the provenance line, a zero is marked `degraded`, and the
  `cs refs` refusal pairs `cs callers` with `cs uses '<name>' --word`, the text
  search that finds those calls. Until 1.19.1, such a zero looked like "unused".
- **`cs changes` / `cs_changes`** (1.19.0) lists what changed since a version,
  small fixes included, and the MCP instructions name the running version.
  This section is the summary; that command is the complete list.
- **`verify-engines`** probes tokensave's C# interface edges as a capability
  (1.16.2), and Serena on Java without a JDK, Kotlin without a toolchain
  request, and .NET Framework projects (1.18.0).
