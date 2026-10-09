#!/usr/bin/env python3
"""PreToolUse guard: stop and tell the user when the cs MCP server has disconnected.

Run through scripts/cs-disconnect-guard, which resolves the configuration the way the
CLI does (scripts/lib/common.sh) and starts this only when CS_DISCONNECT_GUARD=1.

WHY
---
The server can drop mid-session. The harness then removes every cs tool, and the
agent sees one line about it in a system reminder. The failure this exists for: the
agent notes the drop in passing, keeps answering cross-repo questions with `grep` over
the fleet root, and says nothing until the user asks. A grep answer to a cross-repo
question is a textual one where cs would have given a resolved one, and the user does
not know the trade was made. Reconnecting takes one `/mcp`, so the user should hear
about it at once.

THE SIGNAL
----------
The session transcript records every change to the tool surface as an attachment
record, `{"attachment": {"type": "deferred_tools_delta", ...}}`:

  disconnect   removedNames  holds the cs tool names, failedMcpServers names the server
  reconnect    addedNames + readdedNames hold them again
  start        addedNames holds them (or pendingMcpServers names the server, and a
               later record adds them)

The guard replays those records and keys on those fields only, never on prose. A note,
a skill or a handover that quotes the tool names or the word "disconnected" is content,
not an event, and must not trip the guard. A session in which cs never appeared is not
a disconnect either: the server may be disabled for that project, or still connecting.
Only an explicit removal or failure counts.

The tool names and the server name are derived from this plugin's own manifest and
.mcp.json, so a rename of either moves the guard with it instead of leaving it blind.

BEHAVIOUR
---------
1. One-shot flag, any tool, per agent. On the first tool call after cs goes absent,
   block once and tell the agent to raise it with the user. A marker file, created
   with O_EXCL per (session, disconnect timestamp, agent), makes it fire once per
   disconnect even when parallel tool calls run their hooks at the same moment. The
   agent is the payload's `agent_id` (present only inside a subagent, whose hooks
   receive the PARENT's session_id and transcript_path), else "main" -- so a subagent
   that makes the first call after the drop consumes its own flag and the main agent
   still gets one.
2. Cross-repo guard, Bash and Grep, while cs stays down. A search spanning several
   clones under FLEET_ROOT (the root itself, a glob over its children, or two or more
   distinct repos) is blocked. Bash can append `# <ack marker>` (CS_DISCONNECT_ACK,
   default `cs-down-ack`) to say the user agreed to a grep fallback. The Grep tool has
   no comment to carry the marker, so the message points it at Bash.
   With CS_DISCONNECT_FILES_ARE_READS=1 (the default), an argument that names an
   EXISTING regular file (no glob) is a read of a known location, not a search -- cs
   cannot scope to two files anyway -- so it counts as a path but spans no repo:
   `grep x <clone-a>/f.py <clone-b>/g.py` passes. Set it to 0 and a file counts toward
   its clone like a directory does.
3. Reconnect clears both, because the replay then reads cs as present.

STATE
-----
$XDG_STATE_HOME/code-search/disconnect-guard/<session_id>.json (XDG_STATE_HOME
defaults to ~/.local/state) holds the byte offset already replayed and the current
verdict, so each call reads only what the transcript gained since the previous call;
transcripts run to tens of megabytes. If the file shrank, the replay starts again from
zero. Only complete lines are consumed, so a record still being written is read on the
next call.

CONTRACT
--------
Blocks by exiting 2 with the message on stderr. Fails open on anything it cannot read
(bad payload, missing transcript, unreadable state): a guard that breaks every tool
call because it could not answer is worse than no guard.

Bash parsing strips heredoc bodies, splits on operators with `punctuation_chars`, and
hides a mid-word `#` from shlex, or `${x##*/}` would truncate the token stream and the
matcher would fail open.
"""

import json
import os
import re
import shlex
import sys

PLUGIN_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "..", ".."))
DEFAULT_ACK = "cs-down-ack"

SEARCH_COMMANDS = {
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "ugrep", "find", "fd", "bfs",
}
# Commands that search their working directory when given no path argument.
DEFAULT_CWD_COMMANDS = {"rg", "ag", "ack", "fd", "find", "bfs"}
GLOB_CHARS = set("*?[{")

HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
MIDWORD_HASH = re.compile(r"(?<=[^\s;&|()<>])#")

FLAG_MESSAGE = """\
STOP: the `cs` MCP server ({server}) disconnected at {ts}.

All `{prefix}*` tools are gone from this session. Before doing anything else, tell the
user that cs is down and ask them to run `/mcp` to reconnect it. If you are a subagent,
report it to your caller as a blocker.

Do not quietly switch to grep for cross-repo questions. A grep over the fleet is a
textual answer where cs would have given a resolved one, and the user should choose
that trade knowingly. This message fires once per disconnect. While cs stays down,
cross-repo Bash/Grep searches are blocked until the user agrees to a grep fallback
(then append `# {ack}` to the Bash command).
"""

CROSS_REPO_MESSAGE = """\
Blocked: a cross-repo search while the `cs` MCP server is disconnected (since {ts}).

  {what}

This searches several clones under {repos}, which is a question for cs. Ask the user
to run `/mcp` to reconnect it. If they have agreed to a grep fallback, rerun this as a
Bash command ending in `# {ack}` and say in your answer that the result is textual,
not resolved. (The Grep tool cannot carry the marker; use Bash for the acknowledged
fallback.) A search inside ONE repo, e.g. {repos}/<repo>/..., is not blocked.
"""


def home():
    return os.path.expanduser("~")


def fleet_root():
    root = os.environ.get("FLEET_ROOT") or os.path.join(home(), "code", "fleet")
    return os.path.normpath(os.path.abspath(os.path.expanduser(root)))


def ack_marker():
    return (os.environ.get("CS_DISCONNECT_ACK") or "").strip() or DEFAULT_ACK


def files_are_reads():
    return os.environ.get("CS_DISCONNECT_FILES_ARE_READS", "1").strip() != "0"


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(home(), ".local", "state")
    return os.path.join(base, "code-search", "disconnect-guard")


def cs_identity():
    """(tool prefix, a tool name, server name) as the harness names this plugin's server.

    A plugin server's tools are `mcp__plugin_<plugin>_<server>__<tool>` and the server is
    `plugin:<plugin>:<server>` (docs/mcp.md). Read from the manifests rather than typed
    in, so a rename cannot leave the guard watching for names that no longer exist.
    """
    plugin, server = "code-search", "cs"
    try:
        with open(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh).get("name") or plugin
        with open(os.path.join(PLUGIN_ROOT, ".mcp.json")) as fh:
            servers = json.load(fh).get("mcpServers") or {}
        if len(servers) == 1:
            server = next(iter(servers))
    except (OSError, ValueError, AttributeError):
        pass
    prefix = "mcp__plugin_%s_%s__" % (plugin, server)
    return prefix, prefix + "cs_text", "plugin:%s:%s" % (plugin, server)


def _names(value):
    """failedMcpServers holds objects with a `name`; tolerate plain strings too."""
    out = []
    for item in value or []:
        if isinstance(item, dict):
            out.append(item.get("name"))
        else:
            out.append(item)
    return out


def apply_record(state, line, tool, server):
    """Update state from one transcript line, if it is a tool-surface delta."""
    if "deferred_tools_delta" not in line:
        return
    try:
        record = json.loads(line)
    except ValueError:
        return
    if not isinstance(record, dict):
        return
    att = record.get("attachment")
    if not isinstance(att, dict) or att.get("type") != "deferred_tools_delta":
        return
    added = tool in (att.get("addedNames") or []) or \
        tool in (att.get("readdedNames") or [])
    gone = tool in (att.get("removedNames") or []) or \
        server in _names(att.get("failedMcpServers"))
    if added:
        state["down_since"] = None
    elif gone and not state.get("down_since"):
        state["down_since"] = record.get("timestamp") or "an unknown time"


def replay(transcript_path, session_id, tool, server):
    """Return the disconnect timestamp if cs is currently absent, else None."""
    path = os.path.join(state_dir(), "%s.json" % session_id)
    state = {"offset": 0, "down_since": None}
    try:
        with open(path) as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            state.update(loaded)
    except (OSError, ValueError):
        pass

    size = os.path.getsize(transcript_path)
    if size < state["offset"]:
        state = {"offset": 0, "down_since": None}
    if size > state["offset"]:
        with open(transcript_path, "rb") as fh:
            fh.seek(state["offset"])
            chunk = fh.read()
        end = chunk.rfind(b"\n")
        if end >= 0:
            for raw in chunk[: end + 1].splitlines():
                apply_record(state, raw.decode("utf-8", "replace"), tool, server)
            state["offset"] += end + 1
            os.makedirs(state_dir(), exist_ok=True)
            tmp = "%s.%d.tmp" % (path, os.getpid())
            with open(tmp, "w") as fh:
                json.dump(state, fh)
            os.replace(tmp, path)
    return state.get("down_since")


def claim_flag(session_id, down_since, agent="main"):
    """True for exactly one caller per (session, disconnect, agent)."""
    key = re.sub(r"[^0-9A-Za-z]", "", down_since)
    agent = re.sub(r"[^0-9A-Za-z_-]", "", str(agent or "main")) or "main"
    marker = os.path.join(state_dir(), "%s.flagged.%s.%s" % (session_id, key, agent))
    os.makedirs(state_dir(), exist_ok=True)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.close(fd)
    return True


def strip_heredocs(command):
    lines = command.split("\n")
    out, k = [], 0
    while k < len(lines):
        match = HEREDOC_RE.search(lines[k])
        out.append(HEREDOC_RE.sub("", lines[k]) if match else lines[k])
        if match:
            terminator = match.group(2)
            k += 1
            while k < len(lines) and lines[k].strip() != terminator:
                k += 1
        k += 1
    return "\n".join(out)


def tokenize(command):
    command = MIDWORD_HASH.sub("\x01", strip_heredocs(command).replace("\n", " ; "))
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return [t.replace("\x01", "#") for t in lex]
    except ValueError:
        return [t.replace("\x01", "#") for t in command.split()]


def segments(command):
    separators = set(";&|<>()")
    out, current = [], []
    for tok in tokenize(command):
        if tok and set(tok) <= separators:
            out.append(current)
            current = []
        else:
            current.append(tok)
    out.append(current)
    return [seg for seg in out if seg]


def expand(token, cwd):
    """Resolve a path-like token the way the shell would, without globbing."""
    h, root = home(), fleet_root()
    # $FLEET_ROOT is how the docs and fleet.env spell the fleet, so an agent may too.
    for prefix, value in (("${HOME}", h), ("$HOME", h),
                          ("${FLEET_ROOT}", root), ("$FLEET_ROOT", root)):
        if token == prefix or token.startswith(prefix + "/"):
            token = value + token[len(prefix):]
    token = os.path.expanduser(token)
    if not os.path.isabs(token):
        token = os.path.join(cwd or "/", token)
    return os.path.normpath(token)


def repos_touched(token, cwd):
    """(is_path, repos) for one argument.

    is_path says the argument names something on disk (or a path-shaped glob), so the
    command will not fall back to searching its working directory. repos is the set of
    clones under FLEET_ROOT it spans; "*" means all of them (the root itself, or a glob
    in the repo component). A positional that is not a real path, such as a grep
    pattern or a flag's value, touches nothing: the repo component must exist as a
    directory, and a glob counts only when it is path-shaped (`*` alone, or holds a
    `/`), so a quoted `-g '*.py'` filter is not read as a glob over repos. An existing
    regular file inside a clone is a path that spans no repo while files count as reads
    (BEHAVIOUR item 2).
    """
    root = fleet_root()
    path = expand(token, cwd)
    is_glob = bool(set(token) & GLOB_CHARS)
    path_shaped_glob = is_glob and (token.strip() == "*" or "/" in token)
    if path == root:
        return True, {"*"}
    if not path.startswith(root + "/"):
        return (path_shaped_glob or (not is_glob and os.path.exists(path))), set()
    repo = path[len(root) + 1:].split("/", 1)[0]
    if set(repo) & GLOB_CHARS:
        return (True, {"*"}) if path_shaped_glob else (False, set())
    if not is_glob:
        # A literal token under the root counts only if it exists: a file is a read
        # (or its clone, with files-are-reads off), a directory spans its clone, and a
        # path that is not there -- a grep pattern resolved against a cwd inside a
        # clone, or a typo -- searches nothing. Otherwise the pattern `foo`, run from
        # inside clone A, would count as A, and naming clone B's directory would read
        # as two repos.
        if os.path.isfile(path):
            return True, (set() if files_are_reads() else {repo})
        return (True, {repo}) if os.path.isdir(path) else (False, set())
    if os.path.isdir(os.path.join(root, repo)):
        return True, {repo}
    return False, set()


def cross_repo_paths(args, cwd, searches_cwd_by_default):
    repos, any_path = set(), False
    for arg in args:
        is_path, touched = repos_touched(arg, cwd)
        any_path = any_path or is_path
        repos |= touched
    if not any_path and searches_cwd_by_default and cwd:
        repos |= repos_touched(cwd, cwd)[1]
    return "*" in repos or len(repos) >= 2


def recursive_grep(words):
    for w in words[1:]:
        if w in ("--recursive", "--dereference-recursive"):
            return True
        if re.match(r"^-[A-Za-z]*[rR]", w) and not w.startswith("--"):
            return True
    return False


def bash_is_cross_repo(command, cwd):
    for seg in segments(command):
        words = list(seg)
        # Skip leading env assignments (`X=1 rg …`) and flagless wrappers (`time rg …`).
        # A wrapper with flag values (`nice -n 5 rg`, `sudo -u x rg`) or `xargs grep`
        # still passes: that needs real argument parsing, and the guard fails open.
        while words and (re.match(r"^\w+=", words[0])
                         or words[0] in ("command", "env", "time", "nice", "sudo")):
            words.pop(0)
        if not words:
            continue
        name = os.path.basename(words[0])
        if name not in SEARCH_COMMANDS:
            continue  # `git grep` included: one repository by construction
        searches_cwd = name in DEFAULT_CWD_COMMANDS or recursive_grep(words)
        args = [w for w in words[1:] if not w.startswith("-")]
        if cross_repo_paths(args, cwd, searches_cwd):
            return True
    return False


def grep_is_cross_repo(tool_input, cwd):
    path = tool_input.get("path")
    if path:
        return cross_repo_paths([path], cwd, False)
    return cross_repo_paths([], cwd, True)


def main():
    try:
        payload = json.load(sys.stdin)
        transcript = payload.get("transcript_path")
        session_id = re.sub(r"[^\w-]", "", str(payload.get("session_id") or ""))
        if not transcript or not session_id or not os.path.isfile(transcript):
            return 0
        prefix, tool_name, server = cs_identity()
        down_since = replay(transcript, session_id, tool_name, server)
        if not down_since:
            return 0

        ack = ack_marker()
        # `agent_id` is present only when the hook fires inside a subagent; the main
        # thread has none, so it keys as "main".
        if claim_flag(session_id, down_since, payload.get("agent_id") or "main"):
            print(FLAG_MESSAGE.format(server=server, ts=down_since, prefix=prefix, ack=ack),
                  file=sys.stderr)
            return 2

        tool = payload.get("tool_name")
        tool_input = payload.get("tool_input") or {}
        cwd = payload.get("cwd") or ""
        if tool == "Bash":
            command = tool_input.get("command") or ""
            ack_re = re.compile(r"#\s*" + re.escape(ack) + r"(?![\w-])")
            if ack_re.search(command) or not bash_is_cross_repo(command, cwd):
                return 0
            what = "command: " + command.strip()
        elif tool == "Grep":
            if not grep_is_cross_repo(tool_input, cwd):
                return 0
            what = "Grep path: %s" % (tool_input.get("path") or cwd)
        else:
            return 0
        print(CROSS_REPO_MESSAGE.format(ts=down_since, what=what, repos=fleet_root(),
                                        ack=ack),
              file=sys.stderr)
        return 2
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
