# Changelog

One version for the plugin, and a new one for every release. Add a line under
**Unreleased** with each change. `scripts/set-version` moves **Unreleased** under a new
version, and sets the number in `VERSION` and both manifests (minor for a new verb, flag
or behaviour, patch for a fix alone). Then tag the commit `vX.Y.Z`.
`scripts/check-version-bump` holds the four in agreement in CI.

## Unreleased

## 1.15.0 — 2026-09-29

- `cs fields` keeps its write list complete on tokensave 7.11 and newer (#44). From 7.11,
  `--limit` caps writes as well as reads. When the engine truncated its output, cs had
  been printing 30 of 41 writes under "the write list is complete", and listing 60 of
  320 sites for a field it used to refuse as too large. Writes are now fetched on their
  own (`--writes-only`) and checked against the graph's write total. The reads are a
  `--limit` sample. A field whose writes alone do not fit still refuses and points at
  `--count`. The sample states the graph's true read total, which is available on
  every version.
- `cs fields` with a `Type::field` qualifier on tokensave 7.11 and newer, where the
  qualifier is applied: a narrowed zero refuses with its own explanation. A real type
  can answer zero because a Python attribute that is only assigned has no declaration.
  A narrowed answer that dropped sites with untypable receivers is marked PARTIAL, a
  lower bound. Before 7.11 the qualifier is still refused as not applied (#44).
- Symbol mode (`cs def` and the graph behind callers, callees and impact) works on
  tokensave 7.13, whose `tool search` defaults to text output without node ids (#52).
- MCP: an unknown argument is named, with the list the tool takes, instead of being
  reported as a missing one. `cs-mcp --tools` lists optional arguments too (#49).
- README: install from the `agent-toolworks` catalog (#46), set up a fleet with
  `fleet.env` (#48), MCP example calls (#49), supported platforms (#50), a check count
  that does not go stale (#51), and why the catalogs carry no version (#47).
- The `CS_ROOT` snippet picks the highest version-shaped cache directory (`sort -V`), so
  a sha-named directory no longer wins (#46).
- Versions are managed: `VERSION`, this changelog, `scripts/set-version`, and a
  `vX.Y.Z` tag per release. `check-version-bump` also checks `VERSION` and the
  changelog.
- Verified against tokensave 7.9.0, 7.11.0 and 7.13.0. `fixtures/verified-versions.tsv`
  now records 7.13.0.

## 1.14.1 — 2026-09-19

- The TTL fingerprint check's probe commit, which CI could never make, is fixed.

## 1.14.0 — 2026-09-19

- The plugin ships `.mcp.json`, so installing it registers the MCP server (#43).
- Fleet searches cover repositories only, not loose files at the fleet root (#42).

Versions before 1.14.0 are in the git history; `v1.13.0` is the last tag before this
changelog.
