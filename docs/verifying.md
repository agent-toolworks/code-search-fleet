# Verifying

[← README](../README.md)

```sh
scripts/verify-search      # end-to-end: does the facade still answer everything?
scripts/verify-engines     # per-engine: is each engine still doing its job?
scripts/bench-scale        # what it costs on a generated 456k-line fleet
```

Both matter. `verify-search` alone is not enough because **the facade hides
engine regressions**: `cs calls` falls back from ast-grep to semgrep, so
ast-grep could break entirely and the end-to-end run would still pass. (The
fallback now announces itself, but a passing score still would not.)

`verify-search` also asserts that **the two text backends agree**. Ripgrep
defaults to skipping dotted paths and honouring `.gitignore` while POSIX grep
does neither, so before those flags were pinned a config key in `.github/` was
found on a machine without ripgrep and missed on one with it. An answer that
depends on which engine happens to be installed is worse than a slow one,
because nothing tells you which answer you got.

`verify-engines` also probes **known limitations**, not just capabilities, and
reports `IMPROVED` when one disappears — an upgrade can remove the reason a
tool was rejected, and nothing else would notice.

And `verify-search` tests that `cs` **refuses**, not only that it answers. Those
are different properties, and only the second protects the claim the tool makes.
Every check in that section reproduces a defect that passed all nine scored
queries: a missing `python3` reporting zero hits, six concurrent `cs def` runs
racing on one index file and half returning nothing, a typo'd `--ticket`
answering from main, a language the prose filter could not parse being reported
as filtered anyway.

Two of those are worth naming as a lesson about the tests themselves. A check
that quietly downgrades is worse than no check: piping a long-running producer
into `grep -q` under `set -o pipefail` reports failure by SIGPIPE, so merely
*appending a line* to `cs engines` output turned the timeout-visibility check
into a `SKIP` while the run still said `0 failed`. And a check with no positive
control passes for the wrong reason — asserting only that a comment token is
absent succeeds just as well when the command is broken and finds nothing at
all, which is why every language probe now asserts both halves.

## The fixture

`fixtures/` holds five small repos (C#, Kotlin, Python, TypeScript, Java) with
deliberately planted cross-repo seams **and decoys**: a prose-only mention of an
endpoint, a consumer subscribed to a topic version nobody produces, a
same-named class in an unrelated repo, a dead endpoint, a retired config key
that is a superstring of a live one.

The decoys are the point. Positive cases alone measure recall and are trivially
gamed — a tool answering "everything is related to everything" scores perfectly.
`fixtures/GROUND-TRUTH.md` explains each; `fixtures/BASELINE.md` records how
every engine scores alone.

`fixtures/prose-probes/` is a second, deliberately unglamorous fixture: one file
per language, each carrying one token that appears only in comments and one that
appears only in code. It exists because the five repos above share a blind spot —
they are written in languages the prose filter supported from the start, so a
filter that silently did nothing for C++, Go, Ruby or PHP passed every query.
Twelve languages are covered; adding one is dropping in a `probe.<ext>`.

They also **build and test for real**, each with a GitHub Actions workflow:
`dotnet test`, `gradle test`, `pytest`, and a TypeScript typecheck. That makes
the declared dependency edge executable rather than decorative — Gradle
substitutes `com.acme:pricing-lib` for the sibling `pricing-lib-java` checkout,
so the edge `cs deps` reports is the edge the build actually resolves. It also
gives anything layering incidents on top a real defense layer to inspect.

## Layering in your own incidents

The fixture repos here exist to test search. If you are testing a *workflow* on
top of them — a postmortem process, a review checklist — seed the defects in
your own repo and layer them in:

```sh
scripts/build-fixtures /tmp/fleet --incidents-dir ~/my-toolbox/fixtures/incidents
```

Each incident directory supplies `incident.env`, `before/`, and commit messages;
`build-fixtures` regresses the touched files, commits that as the introducing
change, adds unrelated commits, then restores them as the fix — and asserts the
replayed tip matches the canonical tree, so history cannot drift from source.
