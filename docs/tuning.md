# Tuning, scopes and the query log

[← README](../README.md)

## Tuning it for your repos

| Variable | Does |
|---|---|
| `FLEET_ROOT` | the directory holding your repos — **required**, no useful default |
| `TICKETS_ROOT` | where per-ticket workspaces live |
| `WORKSPACE_ROOTS` | further workspace roots, colon-separated (`_reviews/` beside `_tickets/`); `TICKETS_ROOT` is always one of them |
| `CS_MAX_LINE` | bytes of text kept per hit line, cut around the match, default 400 (`0` or `--full-lines` for whole lines) |
| `CS_MAX_RESULTS` | result cap, default 200 (`0` or `--all` for none) |
| `CS_TIMEOUT` | per-engine wall-clock limit in seconds, default 120 |
| `CS_TAGS_TTL` | how long `cs def` reuses its symbol index; default 60s with a ticket workspace layered, and unbounded for a fleet-only view, where the fingerprint is already a complete key |
| `CS_TEXT_ENGINE` | force `rg` or `grep`, so the two can be compared rather than trusted |
| `CS_EXCLUDE_EXTRA` | directories to skip, added to the built-in list |
| `CS_EXCLUDE_REMOVE` | directories to **stop** skipping |
| `CS_JSON` | `1` for one JSON object on stdout instead of result lines (same as `--porcelain`) |
| `CS_CTAGS_BIN` | use exactly this universal-ctags; if it does not validate, ctags counts as absent |

`CS_TAGS_TTL` is scoped, because the two scopes `cs def` answers for have
different keys rather than different tastes in staleness. The symbol index is
cached under a fingerprint of every repo in view and the commit each sits on, so
the key already invalidates precisely when any repo's HEAD moves. On top of it
sat a flat 60s TTL whose documented purpose is *uncommitted edits* — the one
thing a commit hash cannot see.

In a ticket workspace that is the normal state, and the TTL earns its keep. In a
fleet-only view it does not: a read-only mirror reset to `origin/HEAD` on every
refresh has no uncommitted edits, and the fingerprint is a complete key for
tracked content. The flat TTL made it decorative. Measured on a 43-repo fleet:

| call | time | answer line |
|---|---|---|
| cold `cs def <Symbol>` | **42.1s** | `ctags (fleet-wide symbol index, rebuilt now)` |
| same call 6s later | **5.85s** | `ctags (…, cached 6s ago …)` |

Any interactive use is more than 60 seconds apart, so nearly every `cs def` paid
the 42s to rebuild an index the key had already proved current. So a fleet-only
view now trusts the fingerprint, and a layered ticket keeps the 60s. The answer
line names the gap that actually applies to each — under the fingerprint there
is no time window to distrust, only files added by hand and never committed,
which is what `--refresh` is for. Setting `CS_TAGS_TTL` overrides both, for a
fleet root people edit in place rather than mirror.

`CS_EXCLUDE_REMOVE` matters more than it looks. The built-in exclusion list is a
guess about other people's repos, and some entries are wrong for some of them:
`bin` and `build` are generated in most layouts and hand-written source in
others, and a Go fleet keeps real dependencies in `vendor`. An excluded
directory produces a silent false negative — the hit simply is not there — so
removing an entry has to be as easy as adding one:

```sh
CS_EXCLUDE_REMOVE="bin vendor" cs uses "/api/v1/orders"
```

`cs engines` prints the effective list, because a directory excluded by mistake
looks exactly like a directory with no hits. And because that only helps if you
think to run it, any query with a non-default exclusion list now says so on the
answer:

```
! searching with a NON-DEFAULT exclusion list: +app (CS_EXCLUDE_EXTRA) — files
  under those directories were not searched, so this result may be narrower…
```

`EXTRA` gets the louder wording because it is the direction that manufactures
false negatives, and because these are environment variables: set one for a
single investigation and every later session is narrowed with no expiry.

## Two levels

Built for a **fleet** directory of repos on main plus per-ticket **workspaces**
containing worktrees of only the repos being changed. Run `cs` inside a ticket
workspace and it layers that ticket's branch state over the rest of the fleet:

```
searching: /home/me/tickets/on-call/PROJ-123 (2 repo(s), your branch) + fleet (8 repo(s), main)
```

Searching only the ticket would miss callers in repos the ticket does not
contain — the failure that makes renaming a shared route look safe.

A workspace is any directory under a **workspace root** (`TICKETS_ROOT`, plus
any in `WORKSPACE_ROOTS`) whose immediate children are git repos, at any depth:
`tickets/PROJ-123/`, `tickets/on-call/PROJ-123/` and `reviews/PR-88/` all work,
and a grouping folder such as `on-call/` is not one. A grouping folder that also
holds a repo directly (a stray clone in `_old/`) is a workspace of its own, and
the workspaces inside it are still found; `cs scopes` marks it `mixed`. From anywhere inside a
repo, the workspace is that repo's parent (worktrees included), so `cs` finds it
from any depth. Run from a repo **outside** every root (and outside the fleet),
`cs` answers from the fleet and says so, rather than silently answering from
main while you edit something it cannot see. A workspace repo cloned under
another folder name (`lims-v2` from the fleet's `lims`, matched by `origin`)
stands in for the fleet repo, and the answer says so, instead of both being
searched and counted as two repos.

`--ticket=<path>` searches a named workspace instead of the one you are standing
in: the absolute path of the workspace or of any directory inside one. It is
refused if the path is outside every workspace root, inside the fleet root, or
holds no repos. `--ticket=<id>` still works, looked up by folder name under
every root, and is refused if two workspaces share the name. Either form
**fails** if that workspace does not exist. Falling back to the fleet
would be the same mistake inverted: you asked for your branch state and would
have been handed main, with no `searching:` line to reveal the substitution.
`--fleet` is how you ask for the fleet on purpose, and `cs scopes` lists what
there is to choose between, by path — which is what anything calling `cs` without a
working directory to stand in has to do first.

## Measuring what it actually did — opt-in, off by default

Two of this tool's claims are, in principle, falsifiable: that every answer is
labelled with **how** it was obtained, and that it **fails closed** rather than
reporting a broken engine's empty output as a clean negative. Neither is
measurable from the outside, and the second has a failure mode in the other
direction — a tool that refuses too often teaches its callers to route around
it. Two committed broken symlinks in one repo once made *every* zero-hit query
refuse, so for a stretch no negative result was obtainable at all; that was
caught only because someone happened to be evaluating at the time. As a refusal
rate it would have been a step change on a graph.

`CS_LOG` appends one JSON line per query recording the **outcome**:

```sh
export CS_LOG=1          # -> ~/.cache/cs-queries.jsonl; any other value is a path
```
```json
{"ts":"2026-08-17T12:00:00Z","v":"1.10.0","sub":"seam","query":"h:fa2c3cc2058d",
 "layer":"ticket+fleet","kind":"textual","engine":"ripgrep","outcome":"hits",
 "refusal":"none","hits":7,"repos":2,"ms":3512,"ms_res":"ms","partial":false,
 "warnings":["truncated"]}
```

`outcome` is `hits` / `zero` / `refused`, and a refusal carries a coarse
`refusal` class (`no-fleet-root`, `empty-fleet`, `no-python3`, `no-workspace`,
`engine-failed`, `bad-args`, `other`) — the refusal *messages* carry paths and
query strings and are deliberately not written down. Only the subcommands that
ask the code something are logged; `cs which`, `why`, `engines`, `scopes` and
`repos` cannot hit, miss or refuse, and counting them would dilute every rate
in the file.

**The query string is controlled separately from everything else.** Outcome,
kind, engine, hit count and latency are the analytically valuable fields and
none of them are sensitive; the query is the part that is proprietary in a
private fleet — internal route names, queue names, config keys, symbol names.

| `CS_LOG_QUERY` | writes | for |
|---|---|---|
| `hash` (default) | `"h:fa2c3cc2058d"` | repeat queries stay countable, the identifier is never on disk |
| `omit` | `null` | no query column at all |
| `plain` | the literal string | a fleet that wants it |

The hash is not a security boundary — a short internal identifier does not
survive a dictionary attack by anyone who already has the fleet. It exists so
that "this search ran 40 times this week" stays answerable without writing the
search down.

`ms_res` is `ms` or `s`, because the resolution is not the same everywhere:
`EPOCHREALTIME` needs bash 5 (macOS ships 3.2) and `date +%s%N` is GNU-only, so
the floor is the shell's whole-second counter. A latency graph built on
second-granularity data *without knowing that* is worse than no graph, so the
resolution is recorded next to the number rather than left to be inferred.

**JSONL rather than SQLite, deliberately.** The callers here are agent sessions
and several run at once, so the concurrent case is the normal one. One
`O_APPEND` write of one short line needs no locking, no schema migration, and
cannot be locked out under a fan-out of parallel queries; every field is
bounded so the line cannot grow to a size at which a single write may be split.
`verify-search` runs 16 real queries in parallel and requires 16 intact lines.
It also stays greppable, and anyone who wants SQL can load the JSONL.

The log is instrumentation, so it never costs the query anything: an unwritable
path warns on stderr and the search still answers. `cs engines` reports whether
the log is on and where — in both directions, since a log nobody knows is
running is the problem the opt-in default exists to avoid, and a log somebody
believes is running when it is not is how a measurement window turns out empty.
Rotation is left to you; it is an ordinary append-only file.
