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
CS_ROOT=$(ls -d ~/.claude/plugins/cache/agent-toolworks/code-search/*/ \
          | grep -E '/[0-9]+(\.[0-9]+)*/$' | sort -V | tail -1)
"$CS_ROOT/scripts/cs" doctor | head -3
```

**Check:** the `cs` row names the version and the path it runs from. Every
later step uses `$CS_ROOT`. For why the `grep` and `sort -V` are needed, see
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

**Check:** the `fleet` row of `"$CS_ROOT/scripts/cs" doctor` reads `✓ … N
repo(s)`. A folder there that is not a git clone is listed as not searched.

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

**Check:** `cs doctor` exits 0, or flags only what the user chose to leave. For
example, tokensave graphs are optional.

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

Optionally, to prove the tool itself on this machine:

```sh
"$CS_ROOT/scripts/verify-search"      # 260+ checks on a throwaway fixture fleet, a few minutes
```

## What `cs doctor` says, and what to do

| It says | Do |
|---|---|
| `✗ fleet  root does not exist` / `no repositories in …` | step 4 |
| `fleet … not git repos, so not searched: x` | `x` is not a clone. Clone it properly, or move it out |
| `! python3 … older than 3.11` | put a newer Python first on `PATH`. On macOS with Homebrew the printed fix is `echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile`. `/usr/bin` otherwise wins with Apple's 3.9, which cannot read Gradle version catalogs |
| `! Kotlin … the builds ask for JDK N … installed but keg-only` | paste the printed `export JAVA_HOME=…` line. Homebrew's JDKs are invisible until `JAVA_HOME` points at them |
| `! Kotlin … the builds ask for JDK N, and none is findable` | `brew install openjdk@N`, then the printed `JAVA_HOME` line. It must be **that** version: with another JDK the Kotlin server answers *empty*, not an error |
| `! C# … no runnable dotnet` | `brew install --cask dotnet-sdk`. .NET Framework repos cannot load on macOS or Linux; there `cs impls` falls back to a tokensave graph |
| `! TypeScript` / `JavaScript … no runnable node` | `brew install node` |
| `? Python` / `Go` / `Rust` | not checked by `cs`. An empty `cs impls` / `cs refs` there is not proof of absence |
| `! tokensave  MISSING` / `graphs in N of M repo(s)` | `brew install aovestdipaperino/tap/tokensave`, then `cd <repo> && tokensave init` in each repo. fleet-workspace's refresh keeps graphs synced |
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

## If you already use cs: what changed in 1.16–1.17

For people, and for agents whose notes, `CLAUDE.md` or memory describe cs from
before 1.16. Update anything that says otherwise:

- **`cs doctor` / `cs_doctor` is the setup check** (1.17.0). Refusals now end
  with `check: cs doctor`; until 1.17.1 they said `cs engines`. `cs engines`
  still exists, as the shorter "what is installed" view. When a tool refuses,
  or `cs impls` / `cs refs` come back empty, run `cs_doctor` before concluding
  anything.
- **Java needs no JDK** (1.16.2). cs used to refuse Java queries without one.
  `java MISSING` in `cs engines` now concerns Kotlin only.
- **Kotlin needs the JDK version its Gradle build declares**
  (`jvmToolchain(21)`). With a JDK of another version, `cs` cannot refuse,
  because `java` runs, and the server answers empty. Only `cs doctor` catches
  this. The Kotlin refusal now names the version, and gives the `JAVA_HOME`
  line when that JDK is installed but keg-only (1.17.2).
- **`cs doctor` exits 3** when it flags something. That code is its own: it
  is not a refusal (1) and not a zero-hit answer (2).
- **`verify-engines`**: tokensave's C# interface edges are a capability, so
  losing them reports a regression. There is a new `serena-java` probe (1.16.2).
