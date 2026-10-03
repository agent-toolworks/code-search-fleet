# Updating and running from the plugin cache

[← README](../README.md)

## Updating

Use the marketplace you installed from. `claude plugin list` shows the full id:

```sh
claude plugin marketplace update agent-toolworks      # installed as code-search@agent-toolworks
claude plugin update code-search@agent-toolworks

claude plugin marketplace update code-search-fleet    # installed as code-search@code-search-fleet
claude plugin update code-search@code-search-fleet

claude plugin marketplace update repo-fleet           # legacy: code-search@repo-fleet
claude plugin update code-search@repo-fleet
```

Both lines of each pair are needed. The first refreshes the catalog so it knows
a newer version exists. Running only the second updates against a stale catalog
and reports nothing to do. The plugin also **must** be given with its
marketplace, as in `code-search@agent-toolworks`. The bare `code-search` fails
with `Plugin "code-search" not found`, which reads like the plugin is not
installed, not like the id is incomplete.

Restart Claude Code afterwards; the CLI says so, and the previously loaded skill
stays in the session until you do.

### After updating: run `cs doctor`

Since 1.17.0, `cs doctor` checks this machine against *your* fleet and names
what will not work here, what it costs, and the fix. Run it after every update
and on every new machine: ask Claude to run `cs_doctor`, or run it from a
terminal (`"$CS_ROOT/scripts/cs" doctor`, see
[below](#running-the-scripts-from-a-terminal)). It exits 0 when nothing is
flagged and 3 when something is.

Each flagged line prints its fix, ready to paste. The common ones, with what to
do, are in [install.md](install.md#what-cs-doctor-says-and-what-to-do), and
[what changed in 1.16–1.17](install.md#if-you-already-use-cs-what-changed-in-116117)
is there too.

Java needs nothing; its language server ships its own runtime (since 1.16.2;
before that, cs refused Java without a JDK).

**After changing `PATH` or `JAVA_HOME`, restart Claude Code.** The MCP server
inherits the environment Claude Code was started with, so it keeps using the
old Python and no JDK until then, and `cs_doctor` reports from that old
environment.

**Verify by effect, not by the version string** — and the reason that advice
exists is worth stating, because it was once not enough. The plugin cache keeps
every version side by side and `claude plugin update` compares version strings,
so a tree that ships new work under an unchanged version does not look broken
from anywhere:

```
$ claude plugin update code-search@code-search-fleet
✔ code-search is already at the latest version (1.11.0).
$ grep -c 'cmd_gaps' <cache>/code-search/1.11.0/scripts/cs
0
```

The update command is behaving correctly; the published `1.11.0` and the tree's
`1.11.0` were different artifacts sharing a version string. A subcommand then
works from a clone and errors from the plugin, *both reporting the same
version*, which makes the usual debugging move actively misleading.

So the version is now a CI gate rather than a habit: `scripts/check-version-bump`
fails when anything under `scripts/` or `skills/` changes without
`.claude-plugin/plugin.json` moving with it, and fails when the two manifests
disagree with each other (they had drifted to 1.11.0 and 1.10.0 unnoticed —
each is read by a different consumer, and neither reads the other). Run it by
hand the same way CI does:

```sh
./scripts/check-version-bump          # against origin/main, or the previous commit
```

**Cutting a release.** Every change adds a line under **Unreleased** in
`CHANGELOG.md`. To release, run `scripts/set-version X.Y.Z`: minor for a new
verb, flag or behaviour, patch for a fix alone. It moves Unreleased under the
new version with today's date, and writes the number to `VERSION` and both
manifests. Then commit and tag `vX.Y.Z`. `check-version-bump` also fails when
`VERSION` disagrees with `plugin.json`, or the changelog has no entry for it.

**The catalogs that republish this plugin carry no `version`.**
`agent-toolworks/plugins` and the legacy `repo-fleet` list it through a `url`
source. For a plugin fetched that way, `plugin.json` wins over an entry's
`version` at install and update time. The entry's copy only affects what
`/plugin` shows before install, because nothing else can be read then. That
copy had drifted to `1.13.0` while `plugin.json` said `1.14.1`, and no check here
could see it. So those entries now leave `version` out, and `plugin.json` is the
only place it is stated. This repo's own `marketplace.json` still carries one,
because its entry is a relative path in the same tree, and
`check-version-bump` holds it equal to `plugin.json`.

## Running the scripts from a terminal

The whole repo ships with the plugin — the `cs` CLI, all five engines' glue, the
fixture fleet, and the verification suite — so `verify-search` runs from the
installed copy and answers "is this working *here*" rather than "did it work
where it was built".

`CLAUDE_PLUGIN_ROOT` is set **only inside a Claude Code session**, so the
`"$CLAUDE_PLUGIN_ROOT/scripts/…"` form used throughout `SKILL.md` expands to
`/scripts/…` in an ordinary shell and fails. Resolve the installed copy instead:

```sh
MARKETPLACE=agent-toolworks   # or code-search-fleet, or repo-fleet: the part after @ in `claude plugin list`
CS_ROOT=$(ls -d ~/.claude/plugins/cache/"$MARKETPLACE"/code-search/*/ \
          | grep -E '/[0-9]+(\.[0-9]+)*/$' | sort -V | tail -1)

"$CS_ROOT/scripts/bootstrap"        # install the engines (--check to only report)
"$CS_ROOT/scripts/verify-search"    # the full suite, against a throwaway fixture fleet
"$CS_ROOT/scripts/cs" which         # the decision table
```

The filter and `sort -V` pick the highest *version*, which matters because an
update leaves the previous version's directory in place. A plain `tail -1` is
not enough. A catalog entry pinned by `sha` can also leave a directory named
after the short commit (`code-search/c7607743042c/` next to
`code-search/1.14.1/`), and a hex name sorts after a version string. `tail -1`
would then pick that directory, not the one the running `cs-mcp` serves from. If
the result looks wrong, `claude plugin details code-search` names the installed
version.

`verify-search` builds its own fixture repos, so it neither touches your code nor
needs `FLEET_ROOT` set — which makes it the right first thing to run, before the
fleet exists. It **ignores** an exported `FLEET_ROOT` rather than honouring it:
every check asserts fixture content, and the suite seeds probe files into the
fleet it runs against, so aiming it at a real one could only produce failures
that are not real while writing into repos it does not own. `--fleet <dir>`
overrides deliberately, and refuses a tree that is not a fixture fleet. The same
applies to `verify-engines`. Simply asking the agent to "verify code-search" also works, and
avoids the path entirely: the skill resolves it from `CLAUDE_PLUGIN_ROOT`.

**Cost: ~200 tokens always-on**, and the ~8.2k skill body only loads when a
search question actually comes up. `claude plugin details code-search` reports
both numbers for the version you actually have installed — prefer it to this
line, which is a snapshot: the always-on figure was ~150 before `cs owns` and
`cs versions` needed announcing in the description.

That split is the argument against exposing this over MCP *instead*: MCP tool
schemas sit in context for the whole session whether or not you search, so the
8.2k would be permanent rather than on demand.

It is not the argument against exposing it over MCP *as well* — see [mcp.md](mcp.md).

From a plain clone instead, symlink the skill:

```sh
ln -s "$PWD/skills/code-search" ~/.claude/skills/code-search
```

Either way the skill resolves the CLI through `${CLAUDE_PLUGIN_ROOT}`, falling
back to the checkout — the working directory is the user's project, so `cs` is
never on a relative path.
