# Changelog

One version for the plugin, and a new one for every release. Add a line under
**Unreleased** with each change. `scripts/set-version` moves **Unreleased** under a new
version, and sets the number in `VERSION` and both manifests (minor for a new verb, flag
or behaviour, patch for a fix alone). Then tag the commit `vX.Y.Z`.
`scripts/check-version-bump` holds the four in agreement in CI.

## Unreleased

## 1.27.0 — 2026-10-10

- **`cs callers` / `callees` / `impact` mark an edge tokensave guessed**
  (#111). tokensave records how it bound each call (`edges.resolved_by`).
  Some codes are guesses by name, not by type: a trailing name as the only
  candidate (4), or the best of several by score (2, 5, 13), and a few more.
  A library's `Broker.Execute` bound to the repo's only public `Execute` was
  listed as a plain caller. On a real C# repo, 669 of one method's 675
  callers were such edges.
  - **What you see now:** these rows are listed but marked `(calls,
    guessed: simple-name-match-scored, resolved_by=5 — …)`, with one warning,
    and counted apart from the hits (`N guessed by name, listed apart from
    the hits`).
  - **`cs impact`:** a node reached only through a guessed edge is marked
    `only through a guessed edge`.
  - **What stays plain:** edges with no code (written by the extractor) and
    the codes tokensave's own `is_exact()` accepts.
  - **Hit counts can drop:** a C# call inside a property getter is bound by
    name (code 4) in tokensave 7.15.0. So such callers now appear marked
    instead of counted.

## 1.26.0 — 2026-10-10

- **`cs callers`, `callees` and `impact` answer for a method with many callers**
  (#108). `tokensave tool` cuts every reply at 15,000 characters, about 50
  caller rows. So a method with more callers than that, or a name with more
  than about 70 nodes, was refused with *tokensave callers returned no
  parseable JSON*. Those were the methods most worth asking about.
  - **The fix:** the symbol lookup and the three questions now read the
    graph's database directly. They follow tokensave 7.15.0's own logic, and
    were checked against its CLI on every node of the fixture fleet and on a
    400-node sample of a 21,000-node Rust graph: every reply that fit agrees.
    `cs def`'s graph fallback uses the same lookup.
  - **Callers are listed one row per call site:** a method that calls yours on
    three lines is three rows. tokensave's tool listed only the first, so a
    count can go up after upgrading. The answer line says *a row per call site*.
  - **`cs impls`' graph fallback still reads through the CLI.** It refuses
    when the reply was cut, and says the CLI cut it at 15,000 characters. It
    used to parse the cut text as a shorter list of implementations.
    `cs fields` already handled a cut reply and is unchanged.
  - **Long lists of nodes are shortened:** *'X' is N nodes … ALL were asked*
    names the first 10 and says how many more.

## 1.25.1 — 2026-10-10

- **Without uv, `cs refs` and `cs impls` say what to do** (found by #105).
  They refused with one line, *serena needs uv installed*, with no fix and no
  graph to turn to. `cs refs` now names `brew install uv`, `cs doctor`, and
  an *answer now* command from the tokensave graph (`cs callers` for a
  method, `cs impls --engine=tokensave` for a type), the same as when a
  toolchain is missing. `cs impls` answers from the graph when the repo has
  one, and its answer line says uv is missing.
- **CI installs tokensave** (#105), at exactly the version
  `fixtures/verified-versions.tsv` records, and checks it against the
  release's SHA256SUMS. Before, CI had no tokensave, so a green check
  covered none of the graph paths (`cs callers` / `callees` / `impact` /
  `fields`, the tokensave refusals and caveats). Nothing changes for users.

## 1.25.0 — 2026-10-10

- **`cs callers` lists the calls tokensave saw but did not bind** (#107). A
  call tokensave cannot pin to one node is no edge, so `cs callers` dropped
  it and answered as if complete. Three measured cases:
  - a C# getter calling a method name two classes share (since 1.24.0
    removed the C# accessor caveat, that miss carried no caveat at all);
  - a TypeScript function imported from another package;
  - a Python call through an injected object.
  Those call sites are now read from the graph's `unresolved_refs` and
  listed after the edges, marked `(unbound call: <the call as written> …)`.
  The answer line counts them apart (`N unbound call site(s) listed apart
  from the hits`), and the hit count is still the number of edges. An
  unbound row may call another method of that name: read the call before
  relying on it. `cs impact` cannot walk from those calls. Its answer line
  says how many there are, and an impact zero with any is `degraded`.
- **`cs refs` finds a namespace-qualified member** (#102).
  `cs refs Acme.Inventory.Domain.IInventoryStore.ReserveAsync <repo> <file>`,
  which is how a member reads in a stack trace, was split at every dot,
  matched nothing and was refused. `IInventoryStore.ReserveAsync` worked. A
  dotted name of three or more parts is now asked as its last two
  (`IInventoryStore/ReserveAsync`), and cs says so. The file you pass already
  names the namespace, and Serena matches the shorter name in C# and Java.
  Pass names as you see them; you no longer need to strip the namespace.
- **A session opened inside a clone of this repo lists one `cs` server, not
  two** (#99). The clone's `.mcp.json` was also loaded as a project config,
  where `${CLAUDE_PLUGIN_ROOT}` is unset, so a second `cs` failed with ENOENT
  on every start beside the working `plugin:code-search:cs`. The clone's
  `.claude/settings.json` now turns that copy off. The client's "Missing
  environment variables: CLAUDE_PLUGIN_ROOT" diagnostic still prints and is
  harmless; see `docs/mcp.md`.
- **`scripts/build-fixtures --no-toolchain`** (#103) builds the fixture fleet
  with its two JDK 21 toolchain requests replaced by a JVM-target pin,
  committed on `main`. Use it to reproduce a Kotlin or Java language-server
  question on a machine without JDK 21. `verify-engines`' Kotlin probe uses it.
- **`verify-search` checks the `[in Property …]` label against a live
  language server** (#104). The fixture's C# repo gains `StockLevel.cs`, with
  a block getter, an expression-bodied property and a method all calling one
  method. A Serena pin bump that changes the server's reply shapes now fails
  the suite instead of relabelling getter calls as their class.

## 1.24.0 — 2026-10-10

- **cs states the engine versions it was tested with, and the oldest it
  supports** (#100). Until now cs checked no engine version (only
  python ≥ 3.11), and nothing published what a release had been verified on,
  so the same query could answer differently on two machines and neither
  said why. Now:
  - **Every GitHub release has a "Tested with" table:** the exact ripgrep,
    ctags, ast-grep, semgrep, tokensave, uv, Serena, dotnet, java and node
    versions `verify-engines` and `verify-search` passed on, and the minimum
    for each engine. This release: tokensave 7.15.0, ast-grep 0.50.0,
    semgrep 1.180.0, uv 0.13.0, ripgrep 15.2.0, ctags 6.2.1.
  - **`cs doctor` has a `versions` section.** It shows each installed engine
    beside the tested version: `✓ … as tested`, `! … newer than tested` (or
    older) as a note, which leaves the exit status alone (Homebrew upgrades
    whenever it likes; an untested version is not known broken), and `✗`
    below the minimum. Paste the doctor output when you report a wrong answer.
  - **The minimum tokensave is 7.15.0.** Older releases lack C# edges cs
    relies on: calls inside property accessors, interfaces filed as
    `implements`, calls resolved through the receiver's type. Below it,
    `cs callers` / `callees` / `impact` / `fields` refuse and name both
    versions (*tokensave is 7.13.0, older than 7.15.0*), and `cs impls` has
    no graph fallback. Fix: `brew upgrade aovestdipaperino/tap/tokensave`,
    **then `tokensave sync --force` in each repo with a graph.** The new
    edges are in the graph, not the binary, and 7.15.0 does not re-index
    every older graph by itself: one built by 7.13.0 is re-indexed when it is
    first opened, one built by 7.14.x is not (measured with the release
    binaries). `cs doctor` lists the graphs that hold C# and were last fully
    indexed before 7.15.0.
  - **Serena is pinned to a commit** (1de556f). It used to run whatever
    Serena's `main` branch held that day, and every build reports 2.0.0.dev0,
    so no one could say which code had answered. A newer Serena now reaches
    you only in a cs release, after it has been verified.
  - **C# graph answers no longer say "calls inside C# property accessors are
    not in the graph"** when the graph was last fully indexed by 7.15.0 or
    later (tokensave records those calls since then), and a C# zero from
    `cs callers` there is no longer `degraded` for that reason. On an older
    graph the caveat stays, and the answer also says to run
    `tokensave sync --force`. Kotlin answers keep the caveat: Kotlin accessors
    still have no edges.

## 1.23.0 — 2026-10-09

- **A Kotlin symbol in a Java-majority repo is looked up, and a build-output
  copy is never the answer** (#95). Serena writes `<repo>/.serena/project.yml`
  on its first run in a repo and enables one language server, the language
  with the most files. In a Gradle repo with more `.java` than `.kt`/`.kts`
  the Kotlin server never started, and `cs impls` / `cs refs` on a Kotlin
  symbol refused with *could not locate symbol* and advice on spelling it.
  Now, when that file does not exist yet and the question is in a language
  that is not the repo's majority, cs writes it with both servers (and
  `**/bin/**` ignored when Java is on; see below). A question in the majority
  language still leaves the file to Serena, and cs never edits an existing
  file. When an existing file leaves out the symbol's language, the refusal
  says so: *'X' is Kotlin, and repo's Serena project enables only: java*, with
  the fix (add `kotlin` to `language_servers:`). `cs refs` gives this refusal
  before starting a server. Separately, JDTLS imports a Gradle build into
  `bin/` and copies every `.kt` file there. `cs impls` looked up the first match,
  the copy, which no server owns, and reported its empty answer as
  `resolved · 0 hit(s)` for an interface with three implementations. It now
  skips matches that git does not track under `bin/`, `build/`, `out/`,
  `target/` or `obj/`, and refuses when those are the only matches. When
  `cs impls` falls back to a tokensave graph for either cause, the answer line
  names that cause (*no Kotlin language server is enabled in the repo's Serena
  project*, *found the symbol only in build-output copies*). It used to say
  *the language server did not resolve the symbol*, which is not what
  happened. `cs def` listed the same `bin/` copy as a second definition,
  because the ctags index ignored the exclusion list text search uses (`bin`,
  `build`, `out`, `target`, `obj` and the rest). The index now applies that
  list, so `cs def` and `cs uses` agree about which files exist, and
  `CS_EXCLUDE_REMOVE=bin` brings a `bin/` of real sources back to both. `cs doctor`
  has a `project.yml` row that flags a project file leaving out a language
  its repo is written in (3 tracked files and 5% of the source files cs
  recognises, `.kts` not counted), and visible `bin/` copies. Where that language's toolchain is missing, the row names it
  as the first step: Serena starts a repo's servers all or none, so adding a
  server that cannot start would break the repo's other answers. If you were told to add `- kotlin` by hand, cs now does it
  for repos it sets up. For repos already set up, run `cs doctor` to find them.

- **A Kotlin graph answer no longer says cs refs "needs java"** (#97). When
  `cs impls` answered from a tokensave graph on a Kotlin repo, its closing
  warning said `cs refs` needs `java`, which has not been true since 1.18.0
  and sent readers to install a JDK they did not need. It now names what
  Kotlin needs: a Kotlin language server that starts (docs/install.md,
  "Kotlin language server"), and a JDK only when the build requests
  `jvmToolchain(N)`, then exactly N, naming the version when the build asks
  for one that is not findable. The answer line's reason for a Kotlin repo with no
  usable JDK says the same, where it said *no java here*.
- **`verify-search` skips the Gradle-catalog check on a Python without
  `tomllib`** (#96). With Apple's Python 3.9 first on `PATH`,
  `versions-gradle-catalog` could only fail, which looked like a regression
  in the catalog reader on a clean tree. It is now reported as SKIPPED with
  the reason, the same setup gap `cs doctor` names on its `python3` row. A
  skip is not a pass: put a Python 3.11+ first on `PATH` to run it.

## 1.22.1 — 2026-10-09

- **A language server that did not start is named as such** (#90). The Kotlin
  server Serena downloaded (kotlin-server 263.4702.0) is a JetBrains
  pre-release build that has expired: it exits at start-up, so every
  `cs refs` / `cs impls` on a Kotlin repo fails. Serena cannot fetch a newer
  one either, because JetBrains' CDN answers 404 to the URL it builds. cs
  refused with Serena's *"language server manager is not initialized"* and
  advice on how to name the symbol, which pointed at the wrong problem. It now
  refuses with *the language server did not start*, the reason read from
  Serena's log (an expired Kotlin build, a refused download) with the fix, and
  the log's path. `cs impls` used to warn *could not locate* the symbol in this
  case; when it falls back to a tokensave graph, its answer line now gives
  *the language server did not start* as the reason. The expired build's
  version is named whether Serena installed it or `ls_path` points at it. If you see this on Kotlin, install a current kotlin-server and set
  `ls_path` as in docs/install.md, "Kotlin language server". `verify-engines`
  now names the cause on its `serena-kt` line.

## 1.22.0 — 2026-10-09

- **An agent that loses the MCP server is told to tell the user** (#92). When
  the server dropped mid-session, the harness removed every `cs_*` tool and
  said so once; an agent could carry on answering cross-repo questions with
  `grep`, giving textual answers where cs gives resolved ones, without the user
  knowing. The MCP instructions now say: if the `cs_*` tools disappear, the
  server has disconnected; tell the user, ask them to reconnect (`/mcp`), and
  label any grep answer textual. The plugin also ships an optional
  `PreToolUse` hook (`hooks/hooks.json`), off unless `CS_DISCONNECT_GUARD=1`,
  that reads the drop from the session transcript, blocks the first tool call
  after it once per agent, and blocks grep spanning two or more clones under
  `FLEET_ROOT` until the server is back or the command carries
  `# cs-down-ack`. `CS_DISCONNECT_ACK` changes the marker, and
  `CS_DISCONNECT_FILES_ARE_READS=0` counts named files toward their clone. See
  docs/mcp.md § "When the tools disappear mid-session".

## 1.21.0 — 2026-10-09

- **The MCP server says why it stopped** (#88). Every way out of the server
  was silent: the client closing stdin, a SIGTERM / SIGHUP / SIGINT (SIGINT
  even exited 0), a broken pipe. A client that lost the server saw only its
  tools vanish. Each ending now writes one line to stderr, which Claude Code
  keeps in its MCP log, with uptime, calls answered, the last call, and the
  tool still running if there was one. New `CS_MCP_LOG` (`1` for
  `~/.cache/cs-mcp.log`, or a path) also appends start, every call (name,
  duration, outcome, never the arguments) and the exit to a file. A run with no
  exit line there was SIGKILLed or crashed. If the server drops again, set
  `CS_MCP_LOG=1` before starting `claude` and attach the file. A message that
  is not a JSON object, or has non-object `params`, used to crash the server;
  it now gets a `-32600` error and the server carries on. `cs` runs with stdin
  on `/dev/null`, so nothing it starts can read the protocol stream. See
  docs/mcp.md § "When the server stops".

## 1.20.1 — 2026-10-04

- **A language-server refusal states the server's error once** (#86). Since
  1.20.0, `cs refs` / `cs impls` printed Serena's message as a raw `serena: …`
  line before the `✗` refusal and again inside it, with a trailing space, so an
  agent reading stderr saw one failure twice. It is now only in the refusal.
  The server's notes on an answer (a re-ask after import, an import with
  warnings) still print. The refusal's naming advice now lists `Type.Member`,
  which `cs refs` accepts since 1.20.0.

## 1.20.0 — 2026-10-03

- **A language-server error is a refusal, not a hit** (#83). When Serena's tool
  failed, for instance on a name it matches no symbol for, its message
  (`Error executing tool find_referencing_symbols: ValueError: No symbol
  matching 'Patient.GetAccessionList' found`) was printed as the one result
  line of `resolved · 1 hit(s)`, exit 0: a failed lookup read as a positive
  answer, and a real zero could not be told apart from it. `cs refs` and
  `cs impls` now refuse (exit 1, `"refused":true` in the envelope) with the
  server's message, "nothing was ruled out", and how to name the symbol. If
  you kept a `cs refs` answer whose only hit was an `Error executing tool`
  line, it was not an answer: ask again.
- **`cs refs Type.Member` works** (#83). That is how a C# or Java call reads,
  and how an agent writes it, but Serena separates a type and its member with
  `/` and matched nothing. `cs refs` now asks for `Patient.GetAccessionList` as
  `Patient/GetAccessionList`, and says so on stderr. `Type/Member` and the bare
  member name work as before. A namespace-qualified name
  (`Acme.Domain.Patient.Get`) is not one Serena matches either way, and is now
  refused with that advice.

## 1.19.2 — 2026-10-03

- **The `cs refs` hint after a graph zero runs as printed** (#81). `cs callers`
  ending in nothing advised `cs refs <sym> <repo> <file>` with a literal
  `<file>`, so an agent needed a `cs def` round trip before it could follow the
  advice. The hint, and the `cs callers --engine=serena` refusal, now name the
  declaring file (`cs refs GetAccessionList lims Data/Patient.cs`). When
  several files declare the name, `<file>` stays, with a pointer to `cs def`.
- **A `cs refs` hit inside a property is labelled with the property** (#81).
  The language server names the method around a reference, but for a call
  inside a C# getter or an expression-bodied property it named the class:
  `[in Class PatientRelative]`, just where a reader is checking whether the
  caller is a getter. cs now asks the server for that type's members and
  labels the hit `[in Property PatientRelative/AccessionList]` (a field
  initializer, `[in Field …]`). `[in Class …]` now means the reference is in
  no member at all, such as an attribute or a base-type list.

## 1.19.1 — 2026-10-03

- **A C# or Kotlin graph answer names the graph's property-accessor hole** (#79).
  tokensave emits no edges out of property accessors (get/set/init, a Kotlin
  `get() =`) and none into properties: on tokensave 7.9.0, 7.13.0 and 7.14.1, a
  method called only from a getter has no callers in the graph. TypeScript
  getters are fine. `cs callers` therefore answered a clean structural zero,
  exit 2, for a method with a caller, and the 1.18.1 refusal for `cs refs`
  pointed at exactly that command. Now:
  - `cs callers` / `cs callees` / `cs impact` on C# or Kotlin say
    `calls inside C# property accessors are not in the graph` in the
    provenance line;
  - a zero is marked `degraded` in the envelope, with
    `cs uses '<name>' --word` as the first hint;
  - the `cs refs` "answer now" for a method adds that text search as a second
    line, saying only the two together approximate references.

  **If you are an agent:** a C# or Kotlin "no callers" from the graph is not
  "unused" until `cs uses --word` agrees. `cs why structural` says the same.
  `verify-engines` has a `ts-getters` known-limitation probe, which reports
  `IMPROVED` when a tokensave release fixes this.

## 1.19.0 — 2026-10-03

- **`cs changes [version]`** (`cs_changes` over MCP): what changed in cs,
  from this changelog. With no argument it shows the three latest releases;
  with a version, everything after it. Small fixes that never had a ticket are
  included, because every change gets a line here. **If you are an agent whose
  notes describe an older cs, call it with the version you knew.**
- The MCP server's instructions name the running version (`This is cs X.Y.Z`),
  and say to call `cs_changes` when cs behaves differently from what you
  remember.
- `scripts/release-notes X.Y.Z` prints a version's notes from its changelog
  section, so a GitHub release cannot leave out a change the changelog
  records. `CLAUDE.md` makes that the rule for every release.
- The skill's "If you learned cs earlier" list and `docs/install.md`'s "what
  changed" cover 1.18.1: 1-based line numbers, the enclosing symbol on
  `cs refs` lines, and an answer given before the import finished. The skill no
  longer says a wrong-version Kotlin JDK cannot be refused; it has been
  refused since 1.18.0.

## 1.18.1 — 2026-10-03

- **A language server that answered before its project import finished is
  re-asked, or refused** (#76). Serena's Java wrapper stops waiting for the
  import after 20 seconds, and only accepts the status `OK`. Past that it
  answers anyway, and on a cold multi-module build that was
  `resolved · 0 hit(s)` for an interface with two implementations.
  `serena_call.py` now reads the server's own log for this. If the import
  reported a status later, it asks again and returns that answer. If it never
  reported one within the time left before `CS_TIMEOUT`, it exits 3, and `cs`
  refuses: nothing was ruled out. If the import had already ended with a
  warning, the answer stands, with a note. Reproduced by interrupting a first
  import; the decision is tested on synthetic logs.
- **Language-server line numbers are 1-based** (#76). Serena's are 0-based (the
  LSP's), and were printed as they came, so every `cs impls` / `cs refs` address
  landed one line short. `verify-search` now opens each reported file at the
  reported line.
- `cs refs` names the enclosing symbol of each reference
  (`[in Method ReservationController/ReservationController]`); it printed only
  that symbol's kind, so a call inside a method read `[Class]` (#76).
- **A refusal's "answer now" is a command that runs** (#75). It was shared by
  `cs impls` and `cs refs` ("rerun with `--engine=tokensave`"), and `cs refs`
  refuses that flag. For `cs refs` it now asks the graph whether the symbol is
  a type or a method, offers `cs impls … --engine=tokensave` or `cs callers …`
  accordingly, and says either is narrower than a reference search.
  `verify-search` follows each one.
- `docs/install.md` / `docs/updating.md`: `CS_ROOT` no longer names a catalog,
  so it is found whichever catalog installed the plugin. It is chosen by
  version alone: sorting whole paths picked the alphabetically last catalog. A
  folder named after a pinned commit is used only when it is the only one, and
  a missing install is said rather than running `/scripts/cs` (#75).
- `cs doctor`'s Kotlin row: singular and plural fixed, and a doubled
  `findable (JAVA_HOME)JAVA_HOME` from 1.18.0 removed.

## 1.18.0 — 2026-10-03

- **Kotlin is gated by what its build requests, not by `java` running** (#72).
  A `jvmToolchain(N)` request, the repo's own or one in a build it pulls in
  with `includeBuild`, needs a JDK of exactly N that Gradle can find, and `cs`
  now refuses when there is none. Before, a JDK of another version passed the
  check and the server answered `[]`. A build pinned only by
  `sourceCompatibility` / `jvmTarget` needs no JDK: the Kotlin server builds it
  on its own runtime (Java 25). Verified under JDK 17, 21, 26 and none. `cs`
  refused those builds before when `java` did not run. JDK discovery adds
  Gradle-provisioned JDKs, SDKMAN, `org.gradle.java.installations.paths`, and
  builds that apply the foojay resolver.
- **Legacy .NET Framework C# loads with the .NET SDK on macOS and Linux** (#72).
  A two-project v4.x solution resolved implementations and references across a
  `ProjectReference`, minus the framework's reference assemblies. The refusal
  text, the README and the skill had called that impossible. `cs doctor` and
  the C# refusal now say what a Framework repo gets. When the repo has a
  tokensave graph, the refusal leads with `--engine=tokensave`.
- **`CS_NO_GRAPH`** (`fleet.env`): repos kept without a tokensave graph on
  purpose. `cs doctor` names them and does not count them, and a graph refusal
  in one says why instead of prescribing `tokensave init` (#72).
- `cs doctor` has a **workspaces** row: each configured root, its workspace
  count, any `mixed` folder, and a root that does not exist. The default
  `TICKETS_ROOT` is not flagged when absent (#72).
- `verify-engines`: `serena-kt` (Kotlin with no toolchain request, no
  `JAVA_HOME`) and `serena-netfx` (a legacy .NET Framework solution) probes.
- Toolchain probes give `--version` an empty stdin. `dotnet` otherwise writes a
  keypad-mode escape (`ESC[?1h ESC=`) straight to the terminal, even with its
  output captured, which leaves the terminal's keypad mode switched.
- Docs (#73). `docs/install.md` covers workspaces and path scopes, gives a
  ticket-scoped first query, and "If you already use cs: what changed" (under a
  stable heading; the old link still works) now opens with path scopes (#59)
  and `WORKSPACE_ROOTS`. The MCP "scope is required" error leads with the
  absolute path. Check counts are no longer quoted, so they cannot go stale.

## 1.17.2 — 2026-10-03

- **`docs/install.md`: installing on a new machine, step by step** (#70). It is
  written so a person or an agent can follow it top to bottom: install the
  plugins, find the installed copy, `bootstrap`, `fleet.env`, fix what
  `cs doctor` flags, restart, and check `cs_doctor` over MCP. It adds a
  troubleshooting table (doctor line → fix), the rule that an agent hands
  profile edits to the user rather than working around a permission, and
  "If you already use cs: what changed in 1.16–1.17". The README's install
  section is now that list in short. Its fleet step writes `fleet.env`, where
  it had shown a shell `export` the MCP server never sees.
- Refusals point at `cs doctor`, not `cs engines` (#70). The Kotlin refusal
  names the JDK version the Gradle build declares and, when that JDK is
  installed but keg-only, gives the `JAVA_HOME` line rather than
  `brew install openjdk@21`, which reinstalled a JDK that was already there.
- `cs doctor` prints fixes ready to paste for the user's shell (`~/.zprofile`
  for `PATH`, `~/.zshrc` / `~/.bashrc` for `JAVA_HOME`), and Homebrew's
  `brew shellenv` line when a newer Python is Homebrew's. Its first row names
  cs's version and the path it runs from, which is how a plugin install finds
  `cs`. The tokensave row shows graph age, and a footer says which environment
  the report describes.
- Skill: install and new-machine triggers, the install procedure, and a note on
  what changed for agents that learned cs before 1.16.

## 1.17.1 — 2026-10-03

- The MCP server's standing instructions tell the agent to call `cs_doctor`
  when a tool refuses for a missing engine or toolchain, or `cs_impls` /
  `cs_refs` come back empty. Agents on other machines learn it from the tool
  list without loading the skill. The skill also triggers on setup questions
  ("is cs working", "why did cs refuse").
- `docs/updating.md`: an "After updating: run `cs doctor`" section listing the
  one-time machine fixes (Python 3.11+ first on `PATH`, `JAVA_HOME` for a
  keg-only Homebrew JDK, the .NET SDK, tokensave graphs), and why Claude Code
  must be restarted after changing `PATH` or `JAVA_HOME`.
- `fixtures/verified-versions.tsv` re-recorded with a JDK 21 present: every
  probe passes, `java` included.

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
