# Changelog

One version for the plugin, and a new one for every release. Add a line under
**Unreleased** with each change. `scripts/set-version` moves **Unreleased** under a new
version, and sets the number in `VERSION` and both manifests (minor for a new verb, flag
or behaviour, patch for a fix alone). Then tag the commit `vX.Y.Z`.
`scripts/check-version-bump` holds the four in agreement in CI.

## Unreleased

## 1.17.0 — 2026-10-03

- `cs doctor` (`cs_doctor` over MCP): checks this machine against this fleet
  and says what will not work, what it costs, and the fix (#67). It covers
  python3 (and 3.11+ for `tomllib`, naming a newer one already on PATH), the
  fleet root, each engine, tokensave graph coverage, and a row for each
  language the fleet contains. For Kotlin it reads the JDK version the Gradle
  build asks for and checks that one is findable. A Homebrew `openjdk@N` that
  is installed but keg-only is named with the `JAVA_HOME` line that fixes it.
  A JDK of the wrong version is named too: there `cs` cannot refuse, because
  `java` runs, and the server answers `[]`. Exits 3 when anything is flagged.
  `bootstrap` now ends with it.
- README: a "What needs what" section with two tables: each command's
  requirement and what happens without it, and the toolchain each language
  needs (Java: none; Kotlin: a JDK at the build's toolchain version).

## 1.16.2 — 2026-10-03

- `cs impls` / `cs refs` no longer refuse Java for want of a JDK (#65). Java
  shared Kotlin's toolchain entry, so on a machine whose only `java` is the
  macOS stub a query Serena would have answered was turned away. Serena's
  Eclipse JDTLS ships a JRE and imports Gradle with it. Kotlin keeps the gate:
  without a JDK at the project's toolchain version its Gradle import fails and
  the server answers `[]`. `verify-engines` gains a `serena-java` probe so a
  Serena release that stops bundling the runtime shows as a regression.
- `verify-engines` probes tokensave's C# interface edges as a capability, not
  a known limitation (#65). The limitation was corrected at 7.9.0 and
  `cs impls` falls back to the graph, so every run printed `IMPROVED — revisit
  the routing`, and losing the edges would have read `CONFIRMED` in green. It
  now passes, or fails as a regression, and a rank output it cannot parse is a
  FAIL rather than a missing row. Verified on tokensave 7.9.0, 7.13.0 and 7.14.1.

## 1.16.1 — 2026-10-03

- `verify-search` and `verify-engines` no longer hang when run from a terminal.
  `tokensave init` asks whether to install git hooks when stdin is a TTY, and
  the suites ran it with its output discarded but stdin attached, so it waited
  on a question nobody could see. Every `tokensave init`/`sync` in them now
  reads from `/dev/null`.
- A grouping folder that holds a stray repo no longer hides the workspaces
  inside it (#61). Discovery stopped at the first directory holding a repo, so
  `_old/` with one scratch clone was taken to be the workspace: the 26
  workspaces inside it were missing from `cs scopes`, and their bare ids were
  refused, although their paths resolved. Both levels are now listed, and
  `cs scopes` marks the outer one `mixed: N repo(s) and M workspace(s) below`.
- The hit-line cap keeps the annotation a verb writes after the address (#62).
  `cs values` cuts each line's raw text itself, so `[set] "<literal>"`, the
  `[read]` note and the `NOT accepted` mark survive a long line. Before, they
  were the first bytes cut. The cuts are still counted in the warning and the
  envelope. Any `[tag]` right after the address is protected, `cs fields`
  included.
- `cs uses` names only the unfiltered extensions that still have hits (#62).
  With `--source-only`, `.svg` was named as `NOT filtered` (and on the
  `answer:` line) after every `.svg` hit had been dropped.
- `verify-search`: the fleet-index substitution check expects the scope as a
  path, as it has been since #59 (#63). Its summary no longer sends a failed
  check to `score-seams`, which knows only the scored queries: a scored query's
  re-run line is the whole `cs … | score-seams <id> -` command, and other
  failures are listed as checks of the suite.

## 1.16.0 — 2026-10-01

- A scope can be a path (#59). `--ticket=` and the MCP `scope` take the absolute
  path of a workspace or of any directory inside one, so an agent can pass its own
  working directory. The path must lie under a workspace root, which is
  `TICKETS_ROOT` plus the new colon-separated `WORKSPACE_ROOTS`, and outside the
  fleet root. Otherwise it is refused, with the roots named. Inside a repo, the
  workspace is that repo's parent, worktrees included, so nested layouts such as
  `_tickets/on-call/<id>/` and a second root such as `_reviews/` resolve. A bare id
  still works: it is looked up under every root, nested workspaces included, and
  refused if it is ambiguous. `cs scopes` lists workspaces by path and no longer
  lists grouping folders. The `searching:` line, `scope` and `view` name the path.
  Three layouts that answered from main without saying so are fixed. Running from
  a repo outside every root now warns. A nested workspace now resolves. A
  workspace repo cloned under another folder name (matched by `origin`) now stands
  in for its fleet repo, with a warning, instead of being searched beside it and
  counted as a second repo. An explicit scope that holds no repos is refused.
- Hit lines are capped (#58). Each hit's text is cut to `CS_MAX_LINE` bytes
  (default 400) around the match, and the bytes removed are named in the line.
  The `repo/path:line:` address is never cut, and a cut never splits a UTF-8
  character. A warning names the lines that were cut. The porcelain envelope
  gains `bytes` and `elided`, and the MCP result says when lines were cut.
  `--full-lines` (or `CS_MAX_LINE=0`) prints lines whole. Once an answer is over
  20 KB, the `answer:` line gives its size. `--source-only` now also drops `.svg`,
  `.map`, `.min.js` and `.min.css`.
- `cs values` no longer reads a `for … in (…)` loop or a comprehension as a
  membership test, and drops tokens that name a key rather than a value (#56).
  Comparisons in test files are listed apart and never counted as accepted values.
  A free-form key whose only "accepted" tokens came from those shapes now reports
  `accepts: UNDETERMINABLE` instead of flagging every real value as "SET but not
  accepted".
- `cs values` no longer prints a Python 3.13+ `DeprecationWarning` into its output
  (#57). `verify-search` now reads the source for `re.split`/`sub`/`subn` with a
  positional `maxsplit` or `count`, so the next one fails a check on any
  interpreter. It also runs `cs values` with warnings as errors.
- `pyproject.toml` is parsed as TOML, and each requirement is split as PEP 508
  says (#55). A requirement with `[extras]` keeps its version instead of reading
  UNPINNED, and a quoted word in a `#` comment inside the array is no longer a
  package. `[project.optional-dependencies]`, `[dependency-groups]` and Poetry's
  dependency tables are read too. Without `tomllib` (Python < 3.11), a
  comment-aware scanner feeds the same split.
- `cs versions`, `cs deps` and `cs provides` read Gradle version catalogs
  (`gradle/*.versions.toml`, including `version.ref` and bundles) and NuGet
  `packages.config` (#54). A catalog row names the build files that reference it.
  A `PackageReference` with no version takes it from `Directory.Packages.props`.
  A manifest the readers find but do not parse (`go.mod`, `requirements.txt`,
  `setup.py`, …) is named on the answer as **not read**, and so is one that failed
  to parse. The same notices reach the porcelain envelope as `notes`, which the
  MCP result shows. `cs versions` now names the publisher of a coordinate declared
  in another spelling (`kit-service`), as `cs provides` already did, instead of
  calling it `external`.

## 1.15.1 — 2026-09-29

- The README is short and ordered for use (#53): install (plugin first), fleet setup,
  first queries, commands, how far to trust an answer, honest limits. It has a table of
  contents. The reference and rationale moved, unchanged, into `docs/`: `answer-kinds.md`,
  `mcp.md`, `updating.md`, `tuning.md` and `verifying.md`. Links into the README still
  resolve.

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
