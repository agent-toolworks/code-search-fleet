#!/usr/bin/env bash
# Shared config and helpers for the fleet/ticket scripts.
# The setup this assumes is under "Setting up a fleet" in README.md, and in
# repo-fleet's GETTING-STARTED.md for fleet-init.

# Config precedence: environment > config file > defaults.
#
# The directory is `repo-fleet`, matching what `fleet-init --config` writes.
# This read `~/.config/ai-toolbox/fleet.env` until 2026-08-16 -- the path the
# tooling used before it moved out of ai-toolbox into the repo-fleet plugin.
# Nothing failed when it diverged: cs simply never saw the config, fell back to
# ~/code/fleet, and answered "nothing found" against a directory that did not
# exist. A configured fleet and a search tool that cannot see it is the worst
# combination available, because every answer is a confident negative.
#
# The config file uses `export`, so sourcing it OVERWRITES whatever the caller
# set in the environment -- the opposite of the precedence documented here and
# in the file's own header. The environment is captured first and reinstated
# afterwards, which is what makes `FLEET_ROOT=… cs …` and verify-search's own
# fixture root work. (repo-fleet's copy of this file was fixed months ago; this
# one was not, and the bug was masked by the wrong directory name above.)
FLEET_CONFIG_DIR="${FLEET_CONFIG_DIR:-${HOME}/.config/repo-fleet}"
_env_FLEET_ROOT="${FLEET_ROOT:-}"
_env_TICKETS_ROOT="${TICKETS_ROOT:-}"
_env_BRANCH_PREFIX="${BRANCH_PREFIX:-}"
_env_WORKSPACE_ROOTS="${WORKSPACE_ROOTS:-}"

# shellcheck disable=SC1091
[[ -f "$FLEET_CONFIG_DIR/fleet.env" ]] && source "$FLEET_CONFIG_DIR/fleet.env"

[[ -n "$_env_FLEET_ROOT" ]]    && FLEET_ROOT="$_env_FLEET_ROOT"
[[ -n "$_env_TICKETS_ROOT" ]]  && TICKETS_ROOT="$_env_TICKETS_ROOT"
[[ -n "$_env_BRANCH_PREFIX" ]] && BRANCH_PREFIX="$_env_BRANCH_PREFIX"
[[ -n "$_env_WORKSPACE_ROOTS" ]] && WORKSPACE_ROOTS="$_env_WORKSPACE_ROOTS"
unset _env_FLEET_ROOT _env_TICKETS_ROOT _env_BRANCH_PREFIX _env_WORKSPACE_ROOTS

FLEET_ROOT="${FLEET_ROOT:-${HOME}/code/fleet}"
TICKETS_ROOT="${TICKETS_ROOT:-${HOME}/tickets}"
# Further workspace roots, colon-separated (_reviews/ beside _tickets/, say).
# TICKETS_ROOT is always one of them; a scope must lie under one.
WORKSPACE_ROOTS="${WORKSPACE_ROOTS:-}"
BRANCH_PREFIX="${BRANCH_PREFIX:-feature/}"

if [[ -t 2 ]]; then
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_RED=''; C_GREEN=''; C_YELLOW=''; C_BOLD=''; C_OFF=''
fi

info()  { printf '%s\n' "$*" >&2; }
ok()    { printf '%s✓%s %s\n' "$C_GREEN" "$C_OFF" "$*" >&2; }
warn()  { printf '%s!%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; }
err()   { printf '%s✗%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
# Exit 1 is `cs`'s REFUSAL code, and every refusal path in cs routes through
# here. It is deliberately distinct from 2, which cs returns for a query that
# ran honestly and found nothing -- see the exit-code table in scripts/cs. Both
# used to be 1, which made the difference between "this search did not happen"
# and "this search happened and the answer is no" undetectable to a caller.
die()   { err "$*"; exit 1; }

# List fleet repos (directory name only), one per line.
fleet_repos() {
  [[ -d "$FLEET_ROOT" ]] || die "fleet root not found: $FLEET_ROOT"
  local d
  for d in "$FLEET_ROOT"/*/; do
    [[ -d "${d}.git" ]] || continue
    basename "$d"
  done
}

# Default branch for a repo, from origin/HEAD, falling back to main then master.
default_branch() {
  local repo_dir="$1" ref
  if ref=$(git -C "$repo_dir" symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null); then
    printf '%s\n' "${ref#refs/remotes/origin/}"
    return 0
  fi
  local b
  for b in main master; do
    if git -C "$repo_dir" show-ref --verify --quiet "refs/remotes/origin/$b"; then
      printf '%s\n' "$b"
      return 0
    fi
  done
  return 1
}

have_tokensave() { command -v tokensave >/dev/null 2>&1; }
