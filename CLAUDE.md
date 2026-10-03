# code-search-fleet

`cs` (in `scripts/`) searches a fleet of repositories and labels every answer with the
evidence behind it; the Claude Code plugin is this repository (`.claude-plugin/`,
`skills/`, `.mcp.json`). The README and `docs/` are the reference.

- Versions: `VERSION` and `CHANGELOG.md`. Add a line under **Unreleased** for every
  change; cut a release with `scripts/set-version X.Y.Z` (minor for a new verb, flag or
  behaviour, patch for a fix alone), commit, and tag `vX.Y.Z`. `scripts/check-version-bump`
  (run in CI) fails when shipped files change without the version moving, or when
  `VERSION`, the two manifests and the changelog disagree.
- Telling users and agents what changed. Every user-visible change gets its changelog
  line, including the small fixes nobody files a ticket for. Each line says what was
  wrong, or what is new, and what a user or agent should now do differently. The
  changelog is what reaches people and agents: `cs changes` / `cs_changes` reads it, and
  the MCP instructions state the running version so an agent notices a version it does
  not know. For every release, publish a GitHub release built from
  `scripts/release-notes X.Y.Z`: add to it, never replace it. A change to how an agent
  should call cs or read its answers (a new refusal, a changed meaning, a moved line
  number) also goes in `docs/install.md` § "If you already use cs: what changed" and in
  the skill's "If you learned cs earlier" list.
- Tests: `scripts/verify-search` (end to end, on a throwaway fixture fleet) and
  `scripts/verify-engines` (each engine probed on the capability cs relies on). An engine
  that is not installed is skipped, and a skip is not a pass: say which checks did not run.
- tokensave behaviour differs between versions: check a change to `scripts/lib/tokensave_call.py`
  against more than one (the upstream release binaries can be put first on `PATH`), and
  record what was verified in `fixtures/verified-versions.tsv` (`verify-engines --update`).
