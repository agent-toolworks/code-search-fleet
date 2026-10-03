# Over MCP

[← README](../README.md)

The cost argument in [updating.md](updating.md#running-the-scripts-from-a-terminal) — schemas are permanent, the skill body is on demand —
assumed a client that inlines every tool schema at session start. That is still
true of some, and there the objection stands unchanged. It is no longer true of
clients that **defer** tool schemas: tools arrive as names only, and a schema is
fetched when a tool is actually called. The standing cost there is a list of 27
identifiers — smaller than the always-on skill description it partly duplicates.

So `scripts/cs-mcp` exposes the same subcommands over MCP, and **installing the
plugin now registers it** — the plugin ships a `.mcp.json` at its root that
Claude Code resolves against `${CLAUDE_PLUGIN_ROOT}`:

```json
{
  "mcpServers": {
    "cs": {
      "command": "${CLAUDE_PLUGIN_ROOT}/scripts/cs-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

`env` is `{}` on purpose, not an empty slot to fill: the server inherits no
shell, so the fleet root is resolved by `~/.config/repo-fleet/fleet.env` under
the same environment > config-file > default precedence the CLI uses — see
`scripts/lib/common.sh`. Leave it empty and the plugin-shipped server resolves
the fleet exactly as an existing manual registration does; put a `FLEET_ROOT`
here and you would pin every install to one machine's layout.

The server this registers runs from the **versioned plugin cache**, not from
your clone. A manual registration that points at a clone picks up changes with
`git pull`. The plugin's server only changes when you run `claude plugin update`
(see [Updating](updating.md#updating)), so a clone's `cs` and the MCP surface can end up on
different versions. If they behave differently, compare their versions first.

This closes the reachability gap `cs-mcp` was built for: the surface `cs` is
primarily reached through no longer depends on a human remembering a second,
undocumented `claude mcp add` after install. A client that inlines schemas and
does not want to pay the standing cost can still remove it with
`claude mcp remove cs` (or disable the plugin's MCP server in that client).

## The tool names are plugin-scoped

A plugin-provided server is namespaced by Claude Code, so its tools arrive under
a **plugin-scoped prefix** rather than the bare `mcp__cs__*` a manual
user-scope registration produces. Any doctrine, rules file, or workspace
template that hard-codes `mcp__cs__…` needs a rename pass to match what the
installed plugin actually exposes. The pattern is
`mcp__plugin_<plugin>_<server>__<tool>`, which for this plugin is:

```
mcp__plugin_code-search_cs__cs_text
mcp__plugin_code-search_cs__cs_uses
mcp__plugin_code-search_cs__cs_engines
…                                        (all of `cs-mcp --tools`)
```

So the rename is mechanical: `sed 's/mcp__cs__/mcp__plugin_code-search_cs__/g'`.
Confirm it once in a **new** session after installing. The tool list is fixed
when a session starts, so the session that ran the install cannot see the new
tools, and `claude plugin details` does not list tool names either.

The manual registration is still available, and is the way to keep the bare
`mcp__cs__*` names (or to wire the server from a plain clone, with no plugin):

```sh
# $CS_ROOT as resolved in docs/updating.md, "Running the scripts from a terminal"
"$CS_ROOT/scripts/cs-mcp" --install     # prints the exact `claude mcp add` command, path resolved
"$CS_ROOT/scripts/cs-mcp" --self-check  # can it reach cs and your fleet from here?
"$CS_ROOT/scripts/cs-mcp" --tools       # the surface, without speaking the protocol
```

`--install` exists because the path is the whole difficulty: `CLAUDE_PLUGIN_ROOT`
is unset in the shell where you actually run `claude mcp add`, and an installed
plugin lives under a versioned cache directory nobody types from memory. The
`.mcp.json` above is what removes the need for it on the install path.

What it buys over the CLI is **reachability**, not capability. A tool an agent
must be told about is reached only when something remembers to tell it; a tool
in the tool list is reached because it is there. Prose that has to be loaded
first is the layer that fails. Measurement comes with it: usage rollups key on
the `mcp__<server>__` tool-name prefix, so calls are counted by name rather than
by matching the shape of a shell command — which undercounts precisely when
someone invokes it in a way the matcher does not recognise, and an uncounted
call is indistinguishable from non-use.

## Calling the tools

The main argument has a **different name on different tools**. Copying the
argument name from a sibling tool is the most common wrong call. One example per
shape, with the names as the plugin exposes them:

```jsonc
// pattern: cs_text, cs_calls
mcp__plugin_code-search_cs__cs_text   {"scope": "fleet", "pattern": "orders\\.reserved"}
// query: cs_uses, cs_seam, cs_gaps, cs_history
mcp__plugin_code-search_cs__cs_uses   {"scope": "PROJ-123", "query": "/api/v1/orders"}
// symbol: cs_def (repo optional)
mcp__plugin_code-search_cs__cs_def    {"scope": "fleet", "symbol": "PriceCalculator"}
// symbol + repo: cs_impls, cs_callers, cs_callees, cs_impact
mcp__plugin_code-search_cs__cs_impls  {"scope": "fleet", "symbol": "IInventory", "repo": "inventory-api"}
// symbol + repo + file: cs_refs
mcp__plugin_code-search_cs__cs_refs   {"scope": "fleet", "symbol": "Reserve", "repo": "inventory-api",
                                       "file": "src/Inventory/ReserveHandler.cs"}
// one named key: cs_fields (field), cs_values (key), cs_constructs (type), cs_provides (coordinate)
mcp__plugin_code-search_cs__cs_fields {"scope": "fleet", "field": "Order::status", "count": true}
// scope only: cs_deps, cs_versions, cs_owns, cs_repos, …; nothing at all: cs_scopes, cs_which, cs_why, cs_engines, cs_doctor, cs_changes
mcp__plugin_code-search_cs__cs_scopes {}
```

For every tool's required and optional arguments, use `cs-mcp --tools`:

```
$ "$CS_ROOT/scripts/cs-mcp" --tools
cs_uses        cs uses       (query, scope; optional: word, source_only, count)
cs_text        cs text       (pattern, scope; optional: word, source_only, count)
cs_impls       cs impls      (symbol, repo, scope)
…
```

An argument the tool does not take is rejected by name, and the error lists what
the tool does take. The call does not run:

```
cs_text {"scope": "fleet", "query": "probe"}
→ unknown argument 'query' — cs_text takes: pattern, scope, word, source_only, count
```

## Every tool requires an explicit scope

This is the part that would otherwise break silently, so it is worth stating
plainly. `cs` resolves the ticket workspace from `$PWD`. That is right for a
CLI — you are standing in the workspace — and **meaningless for a server**,
which is a long-lived process whose working directory is wherever the client
launched it and which does not move when you do.

A server that inherited that cwd would make every MCP query a silent fleet-only
search: stale copies of the files you are editing, answered from `main`, with
none of the `searching:` provenance that makes the substitution visible. That
is the worst failure available here — a confident wrong answer arriving through
a new door.

So `scope` is a **required** argument on every tool that reads the fleet, with
no default and no detection. It is the **absolute path** of a workspace or of
any directory inside one (an agent can pass its own working directory, from any
depth), a workspace folder name when that is unique, or `"fleet"`. A path must
lie under a configured workspace root (`TICKETS_ROOT`, `WORKSPACE_ROOTS`) and
outside the fleet root, or the call is refused with the roots named; a relative
path is refused, because the server's working directory is not yours.
`cs_scopes` lists the workspaces by path, nested ones included, `"fleet"` is
spelled out as one of them so that searching `main` alone is a choice rather
than a fallback, and every result carries the same provenance line the CLI
prints:

```
searching: /home/me/tickets/PROJ-123 (2 repo(s), your branch) + fleet (8 repo(s), main)
answer: heuristic via ripgrep (literal, prose filtered) · 2 hit(s) · 2 repo(s)
```

The refusal/zero-hit distinction survives the crossing too: a query that ran
and found nothing comes back as a normal result saying so, and a query that did
not run comes back with `isError` — the same two facts the exit codes carry,
which would otherwise collapse into one at the boundary.

`verify-search` covers all of this, including a differential that issues the
same request from two working directories and requires the answers to match.
