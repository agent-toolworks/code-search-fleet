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
_env_CS_NO_GRAPH="${CS_NO_GRAPH:-}"
# The disconnect guard's keys (scripts/cs-disconnect-guard).
_env_CS_DISCONNECT_GUARD="${CS_DISCONNECT_GUARD:-}"
_env_CS_DISCONNECT_ACK="${CS_DISCONNECT_ACK:-}"
_env_CS_DISCONNECT_FILES_ARE_READS="${CS_DISCONNECT_FILES_ARE_READS:-}"

# shellcheck disable=SC1091
[[ -f "$FLEET_CONFIG_DIR/fleet.env" ]] && source "$FLEET_CONFIG_DIR/fleet.env"

[[ -n "$_env_FLEET_ROOT" ]]    && FLEET_ROOT="$_env_FLEET_ROOT"
[[ -n "$_env_TICKETS_ROOT" ]]  && TICKETS_ROOT="$_env_TICKETS_ROOT"
[[ -n "$_env_BRANCH_PREFIX" ]] && BRANCH_PREFIX="$_env_BRANCH_PREFIX"
[[ -n "$_env_WORKSPACE_ROOTS" ]] && WORKSPACE_ROOTS="$_env_WORKSPACE_ROOTS"
[[ -n "$_env_CS_NO_GRAPH" ]] && CS_NO_GRAPH="$_env_CS_NO_GRAPH"
[[ -n "$_env_CS_DISCONNECT_GUARD" ]] && CS_DISCONNECT_GUARD="$_env_CS_DISCONNECT_GUARD"
[[ -n "$_env_CS_DISCONNECT_ACK" ]] && CS_DISCONNECT_ACK="$_env_CS_DISCONNECT_ACK"
[[ -n "$_env_CS_DISCONNECT_FILES_ARE_READS" ]] \
  && CS_DISCONNECT_FILES_ARE_READS="$_env_CS_DISCONNECT_FILES_ARE_READS"
unset _env_FLEET_ROOT _env_TICKETS_ROOT _env_BRANCH_PREFIX _env_WORKSPACE_ROOTS _env_CS_NO_GRAPH \
  _env_CS_DISCONNECT_GUARD _env_CS_DISCONNECT_ACK _env_CS_DISCONNECT_FILES_ARE_READS

FLEET_ROOT="${FLEET_ROOT:-${HOME}/code/fleet}"
# Whether TICKETS_ROOT is only the default: cs doctor flags a CONFIGURED root
# that does not exist, not a default nobody asked for.
TICKETS_ROOT_DEFAULTED=0
[[ -z "${TICKETS_ROOT:-}" ]] && TICKETS_ROOT_DEFAULTED=1
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

# ---- engine versions (#100) -------------------------------------------------
# cs names a minimum for each engine (lib/engine-minimums.tsv) and the versions
# each release was tested with (fixtures/verified-versions.tsv). Without them an
# answer depended on whatever the machine had: tokensave 7.15.0 added C# edges
# that 7.13.0 lacked, so the same `cs callers` gave different answers on two
# laptops and neither said why.
_common_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

engine_minimum() {  # <engine> -> its minimum version, if cs names one
  awk -F'\t' -v e="$1" '!/^#/ && $1 == e { print $2; exit }' "$_common_lib_dir/engine-minimums.tsv" 2>/dev/null
}

engine_tested() {  # <engine> -> the version this release was tested with
  awk -F'\t' -v e="$1" '!/^#/ && $1 == e { print $2; exit }' \
    "$_common_lib_dir/../../fixtures/verified-versions.tsv" 2>/dev/null
}

# Numeric, field by field: "v22.23.1", "1.180.0" and "21.0.12.1" all compare.
# Anything after the numbers (a -beta, a +build) is ignored.
version_lt() {  # <a> <b> -> success when a is older than b
  local -a a b
  local i x y
  IFS=. read -ra a <<< "$(printf '%s' "$1" | sed 's/^[^0-9]*//; s/[^0-9.].*//')"
  IFS=. read -ra b <<< "$(printf '%s' "$2" | sed 's/^[^0-9]*//; s/[^0-9.].*//')"
  for ((i = 0; i < ${#a[@]} || i < ${#b[@]}; i++)); do
    x=${a[i]:-0}; y=${b[i]:-0}
    ((10#$x < 10#$y)) && return 0
    ((10#$x > 10#$y)) && return 1
  done
  return 1
}

tokensave_version() { tokensave --version 2>/dev/null | awk '{print $2}'; }

# Sets _ts_old to "<installed> <minimum>" when tokensave is installed but older
# than cs supports, once per process. Not a subshell: the answer is cached.
_ts_checked=""; _ts_old=""
tokensave_check_age() {
  [[ -n "$_ts_checked" ]] && return 0
  _ts_checked=1
  command -v tokensave >/dev/null 2>&1 || return 0
  local v m
  v=$(tokensave_version); m=$(engine_minimum tokensave)
  [[ -n "$v" && -n "$m" ]] && version_lt "$v" "$m" && _ts_old="$v $m"
  return 0
}

# An old tokensave counts as absent: every route that falls back from it falls
# back from an old one too, and a refusal says which of the two it was.
have_tokensave() {
  command -v tokensave >/dev/null 2>&1 || return 1
  tokensave_check_age
  [[ -z "$_ts_old" ]]
}

# "is not installed", or "is 7.13.0, older than 7.15.0 (the oldest cs supports)"
tokensave_absent_why() {
  tokensave_check_age
  if [[ -n "$_ts_old" ]]; then
    printf 'is %s, older than %s (the oldest cs supports)' "${_ts_old% *}" "${_ts_old#* }"
  else
    printf 'is not installed'
  fi
}

tokensave_get_it() {  # the command that installs or upgrades it
  local verb=install
  tokensave_check_age; [[ -n "$_ts_old" ]] && verb=upgrade
  if command -v brew >/dev/null 2>&1; then printf 'brew %s aovestdipaperino/tap/tokensave' "$verb"
  else printf '%s tokensave (github.com/aovestdipaperino/tokensave/releases)' "$verb"; fi
}
