# code-search-fleet

`cs` (in `scripts/`) searches a fleet of repositories and labels every answer with the
evidence behind it; the Claude Code plugin is this repository (`.claude-plugin/`,
`skills/`, `.mcp.json`). The README is the reference.

- Versions: `VERSION` and `CHANGELOG.md`. Add a line under **Unreleased** for every
  change; cut a release with `scripts/set-version X.Y.Z` (minor for a new verb, flag or
  behaviour, patch for a fix alone), commit, and tag `vX.Y.Z`. `scripts/check-version-bump`
  (run in CI) fails when shipped files change without the version moving, or when
  `VERSION`, the two manifests and the changelog disagree.
- Tests: `scripts/verify-search` (end to end, on a throwaway fixture fleet) and
  `scripts/verify-engines` (each engine probed on the capability cs relies on). An engine
  that is not installed is skipped, and a skip is not a pass: say which checks did not run.
- tokensave behaviour differs between versions: check a change to `scripts/lib/tokensave_call.py`
  against more than one (the upstream release binaries can be put first on `PATH`), and
  record what was verified in `fixtures/verified-versions.tsv` (`verify-engines --update`).
