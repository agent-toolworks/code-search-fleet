# Baseline: naive grep vs tokensave

Run 2026-08-15 against the fixture fleet, scoring one query per tool per
question with `scripts/score-seams`. tokensave 7.9.0, installed via Homebrew;
all five fixture repos indexed with `tokensave init` (4–5 files each, 12–29ms).

**Headline: grep 5/9, tokensave 4/9 — and they fail on different questions.**
Neither is close to sufficient alone. Three of grep's passes are hollow (right
file, wrong or absent reasoning), so the honest read is that tokensave wins two
questions cleanly, grep wins one cleanly, and both fail three.

| # | Query | grep | tokensave | Notes |
|---|---|---|---|---|
| 1 | `reserve-consumers` | FAIL | FAIL | Both find the two real callers and both add the Python docstring as a third. Different mechanisms: grep matched prose text, tokensave matched symbol names in the same file. |
| 2 | `reserve-definition` | FAIL | **PASS** | tokensave's win. It surfaces the `Reserve` method with signature `[HttpPost("reserve")]`; grep can't, because the full path is assembled from two attributes and exists nowhere as a literal. |
| 3 | `release-consumers` | PASS | PASS | Both correctly report the dead endpoint has no consumers. |
| 4 | `orders-reserved-v1` | FAIL | **PASS** | tokensave's win. Matching the symbol `ORDERS_RESERVED_TOPIC` naturally excludes the v2 analytics consumer; grep's string match drags it in. |
| 5 | `orphaned-consumer` | PASS\* | PASS\* | Both name the file; neither actually compares produced against consumed topic sets. |
| 6 | `reservation-event-shape` | PASS\* | FAIL | tokensave misses the inline JSON literal in Kotlin — it isn't a symbol. grep's "pass" came from a *comment* containing the word, not the literal either. |
| 7 | `discount-engine` | FAIL | FAIL | Both conflate the unrelated Python `DiscountEngine` with the Java one. Name-based matching fails identically in both. |
| 8 | `reserve-flag` | **PASS** | FAIL | grep's win. tokensave misses `_flags.IsEnabled("inventory.reserve.enabled")` in C# entirely, because the key is a bare string literal, not a symbol. |
| 9 | `reserve-implementation` | PASS\* | FAIL | tokensave finds `SqlInventoryStore` but not the controller or the DI registration. grep's "pass" was naming three files by symbol match without bridging DI at all. |

\* Hollow pass: `score-seams` checks which files an answer names, not whether
the reasoning was sound. A FAIL is trustworthy; a PASS still needs reading.

## The two findings that should drive the decision

**1. String literals are not symbols.** tokensave indexes a symbol graph, so
route paths, topic names, and config keys are invisible to it unless they
happen to be bound to a named constant. Query 8 is the clean demonstration:
the .NET side passes the flag key as a bare argument and tokensave cannot see
it. This matters because cross-repo seams *are* strings — which is precisely
the "global relations across repos" use case. A symbol graph does not replace
grep for that; it cannot.

**2. `implements` edges exist only for Java.** Ranking the graph by that edge
kind across the fleet:

| repo | language | `implements` edges |
|---|---|---|
| pricing-lib-java | Java | 1 (correct) |
| inventory-api-dotnet | C# | **0** |
| checkout-service-kotlin | Kotlin | **0** |
| fulfillment-worker-python | Python | **0** |
| web-monorepo-node | TypeScript | **0** |

`implementations --trait IInventoryStore` returns zero matches. Interface to
implementation is the single most valuable relation in a DI-heavy .NET
codebase. All five are in tokensave's "lite" tier, its best-supported one. Note
also that the installed binary reports 34 languages, not the 50+ the README
advertises.

> **Correction (tokensave 7.9.0).** The table above is a true count and the
> conclusion drawn from it was wrong. This section originally read
> "`SqlInventoryStore : IInventoryStore` is not in the C# graph". It is — as an
> **`extends`** edge. C# has one syntax for both relations,
> `class Foo : BaseFoo, IFoo`, so an extractor cannot separate them without
> resolving each name in the base list; tokensave resolves some and defaults the
> rest. Querying the fixture's graph directly:
>
> | edge kind | C# edges | targeting an interface |
> |---|---|---|
> | `implements` | 1 | 1 |
> | `extends` | 4 | 3 |
>
> So all four interface implementations are captured; only one is filed under
> the kind we asked for. The same shape appears at scale — on a tree with
> ~40,650 C# nodes, 33 `implements` against 399 `extends`, 45 of the latter
> targeting an interface.
>
> That changes what a consumer should do. "Zero implements edges" means route
> elsewhere; "split across two kinds" means the graph *can* answer interface
> questions in C#, by querying both kinds and filtering targets. The target id
> carries its own kind (`interface:<hash>` / `class:<hash>`), which is a more
> reliable filter than the `I[A-Z]*` naming convention.
>
> **Why this went unnoticed** is the part worth keeping. The fixture's C# repo
> declared only interfaces and no base class, so *every* relation in it was an
> interface implementation. A graph that emitted zero `implements` edges and one
> that filed all of them under `extends` produce the identical count, and this
> file drew the stronger conclusion from evidence that could not distinguish
> them — a clean-looking negative from a sensor never proven able to fire, which
> is the exact hazard documented elsewhere in this project.
> `src/Infrastructure/AuditedStockLedger.cs` now gives the fixture a real base
> class and a type that does both, so the two kinds are separable here rather
> than only on real code, and `verify-engines` probes both.
>
> This does not change the routing. `cs refs` still uniquely bridges the DI
> registration (`AddScoped<IInventoryStore, SqlInventoryStore>()`), which no
> edge kind captures. But the narrower "what implements this interface" is
> answerable from the graph without a .NET SDK — the expensive prerequisite the
> LSP path carries.

## Token cost

Bytes of raw tool output for the same question:

| Query | ripgrep | tokensave |
|---|---|---|
| Q2 (find definition) | 389 | 2,858 |
| Q9 (trace implementation) | 936 | 1,311 |

tokensave's own savings counter read `0` after this run. **On this fixture it
costs more tokens than grep, not fewer** — its JSON carries signatures and
method bodies.

Read that with care in both directions: the fixture is five files per repo,
where grep output is trivially small anyway. The savings argument is about
avoiding *file reads* while an agent explores a large codebase, and that cannot
be validated or refuted at this scale. What this does show is that the raw
output is verbose, and verbosity does not shrink on bigger repos.

## Round 2: Serena and ast-grep (2026-08-15)

Both installed and measured. **Scope note:** for these two I ran the decisive
subset, not all nine — the queries where round 1 exposed a real gap.

### Serena (LSP-backed) — wins the structural questions outright

| Test | Result |
|---|---|
| `find_implementations` on the C# `IInventoryStore` | **Returns `SqlInventoryStore`.** tokensave returns nothing; its C# graph has zero `implements` edges. |
| Q9 `reserve-implementation` | **PASS, 3/3, non-hollow.** `find_referencing_symbols` returns the controller field, the constructor, *and* the DI registration line `AddScoped<IInventoryStore, SqlInventoryStore>()`, each with surrounding source. This is the query grep and tokensave both effectively failed. |
| Q7 `discount-engine` | Same false positive as the others — returns both `DiscountEngine`s. But it labels each with repo, language, and kind, so a reader can disambiguate; the others give an undifferentiated list. |

**Multi-repo works.** Pointing Serena at the fleet root and listing all five
language servers in `.serena/project.yml` indexed every repo in one project:
`typescript=5, python=4, java=4, csharp=7, kotlin=9`. Cross-repo `find_symbol`
then returns hits from every repo with correct per-repo attribution. So "search
many repos, several sharing a language" is supported — the fleet root *is* the
project.

**Setup cost is the real tradeoff, and it is substantial:**

- Requires a working toolchain per language. This machine had **no .NET SDK and
  no JVM**; both had to be installed before C#, Java, or Kotlin could be
  analyzed at all. tokensave and ast-grep need nothing.
  *Correction (#65):* Java did not need the JVM. Serena's Eclipse JDTLS ships a
  JRE and imports Gradle with it, so `find_implementations` resolves Java on a
  machine with no JDK. Kotlin does need one: its server bundles a runtime to
  run, but its Gradle import needs a JDK at the project's toolchain version,
  and without it the server answers `[]`.
- Fleet-root auto-configuration is **interactive** (it prompts per language) and
  fails outright in a non-interactive shell with `EOF when reading a line`. The
  `project.yml` has to be written by hand for automation — which `new-ticket`
  would have to do.
- The C# server warned `has unresolved dependencies` without a package restore.
  Results were still correct here, but on a real repo expect to need a
  successful build first.
- Serena's own docs cite ~5 minutes to index a 500K-LOC repo. Ten large repos in
  one fleet project is a materially different proposition from this fixture.

### ast-grep (structural, index-free) — covers the string-literal gap

| Test | Result |
|---|---|
| Q8 `IsEnabled("inventory.reserve.enabled")` in C# | **Found**, via `$X.IsEnabled($KEY)`. This is the exact query tokensave cannot answer, because the key is a literal rather than a symbol. |
| C# route attributes | **Found** all three (`[Route(...)]`, both `[HttpPost(...)]`) via a `kind: attribute` rule — the split-attribute construction grep cannot reassemble. |

Its structural advantage is that it matches *syntax*, so a string literal in
argument position is reachable. Two caveats: patterns need per-language
fiddling (the C# attribute case failed as a plain pattern and needed a YAML
rule, because a bare attribute is not a parseable compilation unit), and it has
no notion of types or references — it cannot answer "who implements this".

Because it holds no index, one invocation spans every repo in the fleet at
once. For fleet-wide questions that is a structural advantage over both
Serena and tokensave, which are project-scoped.

## Recommendation after both rounds

Layer them; no single tool covers the space.

| Question | Tool |
|---|---|
| Cross-repo seams: routes, topics, config keys, versions | ripgrep, fleet-wide |
| Same, but needing syntax awareness (literal in argument position, attributes, call shapes) | ast-grep, fleet-wide, no index |
| Symbol truth within a repo: implementations, references, rename safety | Serena |
| Everything else | agentic exploration |

**tokensave is the weakest of the three for this stack.** Its one clean win
(finding the endpoint definition by signature metadata) is matched by
ast-grep's attribute rule, while its `implements` gap in C#, Kotlin, Python,
and TypeScript removes the main reason to run a graph at all here.

## On Docker

Docker helps exactly one of these three, and at a cost:

- **Serena** — genuine benefit. A container bundles the language servers and
  the .NET/JVM toolchains, which is the bulk of the setup pain above, and keeps
  five language servers off the host. Serena supports containerized use.
- **tokensave and ast-grep** — no benefit. Both are single static binaries with
  no runtime dependencies; a container adds indirection and nothing else.

The catch is that on macOS, bind-mounted source is significantly slower than
native filesystem access, and LSP indexing is I/O-heavy — so Docker's cost
lands hardest on exactly the largest repos, which is where Serena is slowest
already. Worth benchmarking on one real repo both ways before committing.
Containers also complicate the worktree model, since each ticket workspace
would need mounting too.

## Round 3: the `cs` facade — 8 of 9

Two more engines added (`semgrep`, `universal-ctags`), then `scripts/cs` put
one question-shaped interface over all of them. Scored on the same nine
queries:

| Approach | Score | Note |
|---|---|---|
| ripgrep alone | 5/9 | three hollow passes → honestly ~2/9 |
| tokensave alone | 4/9 | wins 2 cleanly |
| Serena alone | (subset) | wins the structural questions outright |
| **`cs` facade** | **8/9** | only the cross-repo name collision fails |

The facade beats every individual engine because it routes each question to the
engine that can answer it, and because it can do things **no engine does
alone**:

- **`cs uses`** — the seam question with prose excluded. Text search counts a
  docstring mentioning an endpoint as a caller; a symbol graph cannot see the
  string literal that is the real call site. `scripts/lib/filter_code.py`
  tracks block-comment and docstring state per file, so the middle line of a
  Python docstring is correctly excluded even though it carries no marker.
  This alone turned Q1 from a universal failure into a pass.
- **`cs def`** — universal-ctags indexes the **whole fleet, all five
  languages, in 0.07s**, so the index is rebuilt per query and can never be
  stale. It answers Q2, which ripgrep cannot see at all.
- **`cs seam`** — groups hits by repo and warns when only one repo mentions a
  string, which is the shape of a dead endpoint or an orphaned consumer.
- **`cs refs` / `cs impls`** — escalate to Serena's language servers, the only
  engine that bridges DI. Reserved for that, because it is also the slowest and
  the only one needing a per-language toolchain.

## Round 4: 9 of 9 — and why that number now means less

Adding dependency resolution (`cs provides` / `cs deps`, reading build
manifests rather than code) closed the last query. `scripts/verify-search`
reproduces the full run in one command.

| Approach | Score |
|---|---|
| ripgrep alone | 5/9 (three hollow) |
| tokensave alone | 4/9 |
| `cs` facade | 8/9 |
| **`cs` + dependency graph** | **9/9** |

**Read this number with suspicion.** These nine queries were written here, and
a tool scoring full marks on its author's own test set has exhausted the test
set, not solved search. What 9/9 legitimately says is that the *architecture*
covers the known question types: text, structure, symbols, and dependencies.
What it cannot say is anything about entropy at scale — 400 call sites of a
generic name, reflection, ORM indirection, a decade of drift.

Getting to 100% on real repos is not achievable in the way this table suggests,
because some questions are undecidable statically at any budget: a container
resolving an implementation from a config string, an identifier assembled at
runtime, a route built by concatenation. The honest target is not a perfect
score but a tool that **says which kind of answer it is giving** — a resolved
reference, a textual match, or a guess.

The real measure remains the query set drawn from actual tickets, run against a
real repo. That is still outstanding and nothing here substitutes for it.

### How the last one was closed

`discount-engine` (Q7) failed for every search engine tried, because it is not
a search question. "Which `DiscountEngine` does checkout use" is answered by
resolving the Gradle coordinate `com.acme:pricing-lib` to the repo that
publishes it — information that lives in build manifests, which no code search
engine reads.

`scripts/lib/deps.py` parses publish and dependency declarations across Gradle,
Maven, npm, PyPI, and NuGet manifests, giving a fleet dependency graph. The
query then composes:

```sh
cs def DiscountEngine "$(cs provides com.acme:pricing-lib)"
```

This is a general capability, not a special case for the fixture: `cs deps`
answers "which repos depend on this one", which is the first question of any
impact analysis.

### Engines are optional, and absence is loud

`cs engines` reports what is present. `cs` degrades rather than silently
returning nothing — the failure mode that hid the worktree indexing bug
earlier. Notably, **`rg` on this machine is a Claude Code shell function, not a
binary**, so a script cannot call it; `cs` detects that and falls back to POSIX
grep, which matters for any machine where ripgrep was never installed.

## Still unmeasured

The question this baseline was built to inform — does indexing pay for itself
on a 100K+ LOC repo with real queries — needs a real repo and a query set from
real tickets. Nothing here substitutes for that.

## Round 5: what happens at 456k lines (2026-08-15)

Everything above was measured on five repos of five files each, where every
engine looks instant and the index-versus-grep question cannot even be asked.
`scripts/bench-scale` generates a synthetic fleet — 10 repos, 20,150 files,
456,000 lines, 161MB — and times the facade against it.

| Query | Cost | Hits |
|---|---|---|
| `cs uses` (literal, fleet-wide, prose filtered) | 299 ms | 242 |
| `cs seam` (literal, fleet-wide) | 283 ms | 242 |
| `cs text` (regex, fleet-wide) | 267 ms | — |
| **`cs def` (ctags index built cold)** | **5,901 ms** | — |
| **`cs def` (ctags index reused)** | **744 ms** | — |
| `cs history` (git pickaxe, every repo) | 1,591 ms | 10 |
| `cs deps` (build manifests) | 470 ms | — |
| ripgrep vs POSIX grep, same query | 286 ms vs 885 ms | 242 |

**This is a floor, not an estimate.** Synthetic files have no vendored trees,
no generated code, no minified assets, and none of the drift that makes real
repos expensive.

### Three things it settled

**1. Rebuilding the symbol index per query does not survive scale.** That design
was justified by "0.07s, so it can never be stale" — true at five files, false
at 456k lines, where it costs 5.9s. A real ten-repo fleet is several times
larger again. `cs def` now caches the index keyed on the repos in view and the
commit each is on, with a 60s TTL as the backstop for uncommitted edits, which
refs cannot see. 5.9s → 0.74s. The staleness window is stated in the answer line
rather than hidden, and `--refresh` forces a rebuild.

**2. Fleet-wide grep is fast enough that indexed search is not the bottleneck.**
280-300ms across 161MB. That is the measurement Zoekt was going to be evaluated
against, and it argues against adopting it: an indexed engine would buy perhaps
250ms per query in exchange for an index to build, host, and keep fresh. Revisit
if the real fleet is an order of magnitude larger than this corpus — the
`bench-scale` numbers are how to decide, rather than intuition.

**3. The result cap earns its place.** `cs text '\bid\b'` returns **24,000
lines** uncapped. Capped at 200 with the per-repo distribution printed, the same
query stays readable and still says where the other 23,800 are. Before the cap
existed, that query would have put roughly 1.5MB into an agent's context.

### Two bugs it exposed

Both were invisible on the small fixture, and both are the failure mode this
project cares most about — a wrong answer that looks like a clean one.

**`cs text` was broken for every regex whenever ripgrep was installed.** `-E`
means `--extended-regexp` to grep and `--encoding` to ripgrep, so the query died
with `unknown encoding` and `cs` reported *"nothing found"*. It survived because
the machine it was written on had no ripgrep binary and silently used the grep
fallback — the same shell-function trap recorded at the top of this file, in a
new costume. The backends no longer share a flag vocabulary; the mode is named
and translated per engine, and `verify-search` now diffs regex queries across
both backends, not just literal ones.

**ripgrep and grep were searching different file sets.** ripgrep skips dotted
paths and honours `.gitignore`; grep does neither. A feature-flag key in
`.github/workflows/` was therefore found on a machine without ripgrep and missed
on one with it. Both backends now share one exclusion list, and `verify-search`
asserts they agree.
