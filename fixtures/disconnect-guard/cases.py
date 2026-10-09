"""Fixture cases for scripts/cs-disconnect-guard, run by verify-search.

Each case runs the hook as a subprocess with HOME pointed at a temp directory: the
fleet, fleet.env and the guard's state all live there, and nothing under the real
home is touched. The hook is run through its shell wrapper, so the configuration is
resolved exactly as it is for a user (environment, then fleet.env, then default).

Payloads live in this file rather than on a Bash command line on purpose: the guard
reads Bash commands, so a shell harness holding these strings could be judged by an
enabled guard on the machine running it.

Usage: python3 cases.py HOOK
Prints one `PASS <name>` or `FAIL <name> ...` line per case; exits 1 if any failed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = sys.argv[1]

BLOCK, ALLOW = 2, 0
CS_NAMES = ["mcp__plugin_code-search_cs__cs_text", "mcp__plugin_code-search_cs__cs_refs"]
SERVER = "plugin:code-search:cs"

# Everything that would let the caller's own configuration reach the hook.
SCRUB = ("FLEET_ROOT", "FLEET_CONFIG_DIR", "TICKETS_ROOT", "WORKSPACE_ROOTS",
         "XDG_STATE_HOME", "CS_DISCONNECT_GUARD", "CS_DISCONNECT_ACK",
         "CS_DISCONNECT_FILES_ARE_READS")


def delta(ts, added=(), removed=(), readded=(), failed=(), pending=()):
    return json.dumps({
        "type": "attachment", "timestamp": ts,
        "attachment": {
            "type": "deferred_tools_delta",
            "addedNames": list(added), "removedNames": list(removed),
            "readdedNames": list(readded),
            "failedMcpServers": [{"name": n} for n in failed],
            "pendingMcpServers": [{"name": n} for n in pending],
        },
    })


def user(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


START = delta("2025-01-01T09:00:00Z", added=CS_NAMES + ["Read"])
DOWN = delta("2025-01-01T10:15:30Z", removed=CS_NAMES, failed=[SERVER])
UP = delta("2025-01-01T10:30:00Z", added=CS_NAMES, readded=CS_NAMES)
DOWN2 = delta("2025-01-01T11:00:00Z", removed=CS_NAMES, failed=[SERVER])


class Env:
    def __init__(self):
        self.home = tempfile.mkdtemp(prefix="cs-guard-test-")
        self.fleet = os.path.join(self.home, "fleet")
        for r in ("inventory-api", "pricing-lib", "web-app"):
            os.makedirs(os.path.join(self.fleet, r, "src"))
            with open(os.path.join(self.fleet, r, "src", "a.py"), "w") as fh:
                fh.write("x = 1\n")
        self.config(FLEET_ROOT=self.fleet, CS_DISCONNECT_GUARD="1")
        self.n = 0

    def config(self, **values):
        """Write fleet.env the way fleet-init does: one `export` per key."""
        d = os.path.join(self.home, ".config", "repo-fleet")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "fleet.env"), "w") as fh:
            for k, v in values.items():
                fh.write('export %s="%s"\n' % (k, v))

    def transcript(self, lines, newline=True):
        self.n += 1
        p = os.path.join(self.home, "t%d.jsonl" % self.n)
        with open(p, "w") as fh:
            fh.write("\n".join(lines) + ("\n" if newline else ""))
        return p

    def run(self, transcript, session, tool="Read", tool_input=None, cwd=None, raw=None,
            agent=None, env=None):
        body = {
            "session_id": session, "transcript_path": transcript, "tool_name": tool,
            "tool_input": tool_input or {"file_path": "/x"},
            "cwd": cwd or os.path.join(self.fleet, "inventory-api"),
        }
        if agent:  # a subagent's hook payload: same session_id and transcript, plus agent_id
            body["agent_id"] = agent
            body["agent_type"] = "general-purpose"
        payload = raw if raw is not None else json.dumps(body)
        e = {k: v for k, v in os.environ.items() if k not in SCRUB}
        e["HOME"] = self.home
        e.update(env or {})
        p = subprocess.run([HOOK], input=payload, env=e, capture_output=True, text=True)
        return p.returncode, p.stderr


RESULTS = []


def check(name, got, want, stderr=""):
    ok = got == want
    RESULTS.append(ok)
    if ok:
        print("PASS %s" % name)
    else:
        first = (stderr.strip().splitlines() or [""])[0]
        print("FAIL %s (exit=%s, want %s)%s" % (name, got, want,
                                                 " -- " + first if first else ""))


def bash(cmd):
    return {"command": cmd}


def main():
    e = Env()
    R = e.fleet
    H = e.home

    # --- transcript states -------------------------------------------------------
    t = e.transcript([START, user("hi")])
    check("connected: Read passes", e.run(t, "s-conn")[0], ALLOW)
    check("connected: cross-repo grep passes",
          e.run(t, "s-conn", "Bash", bash("grep -rn foo %s" % R))[0], ALLOW)

    t = e.transcript([START, DOWN])
    rc, err = e.run(t, "s-down")
    check("disconnected: first call of any tool blocks once", rc, BLOCK, err)
    check("  ...message names the time, the server, the tool prefix and /mcp",
          int("10:15:30" in err and SERVER in err and "mcp__plugin_code-search_cs__*" in err
              and "/mcp" in err), 1)
    check("disconnected: second Read passes (one-shot)", e.run(t, "s-down")[0], ALLOW)

    # --- cross-repo battery while down (session already flagged) -----------------
    cases = [
        ("grep -r over the root", BLOCK, "grep -rn foo %s" % R),
        ("commit message mentioning it", ALLOW, 'git commit -m "grep -rn foo %s"' % R),
        ("heredoc body mentioning it", ALLOW,
         "git commit -F - <<EOF\ngrep -rn foo %s\nEOF" % R),
        ("same invocation chained", BLOCK, "echo hi; grep -rn foo %s" % R),
        ("after a mid-word # expansion", BLOCK, "tag=${s##*:}; grep -rn foo %s" % R),
        ("tilde root", BLOCK, "rg foo ~/fleet"),
        ("$HOME root", BLOCK, "rg foo $HOME/fleet/"),
        ("glob over clones", BLOCK, "grep -rn foo ~/fleet/*/src"),
        ("two named clones", BLOCK, "grep -rn foo %s/inventory-api %s/web-app" % (R, R)),
        ("find over the root", BLOCK, "find %s -name '*.py'" % R),
        ("ack marker allows", ALLOW, "grep -rn foo %s  # cs-down-ack" % R),
        ("a marker that only starts with the ack word does not", BLOCK,
         "grep -rn foo %s  # cs-down-acknowledged" % R),
        ("one clone is fine", ALLOW, "grep -rn foo %s/inventory-api/src" % R),
        ("not a search command", ALLOW, "ls %s" % R),
        ("git grep is one repo", ALLOW, "git -C %s/inventory-api grep foo" % R),
        ("two exact files in two clones = a read", ALLOW,
         "grep -n foo %s/inventory-api/src/a.py %s/web-app/src/a.py" % (R, R)),
        ("exact file + one clone dir = one repo", ALLOW,
         "grep -rn foo %s/inventory-api/src/a.py %s/web-app/src" % (R, R)),
        ("exact file + a second clone dir = two repos", BLOCK,
         "grep -rn foo %s/inventory-api/src/a.py %s/web-app/src %s/pricing-lib"
         % (R, R, R)),
        ("two nonexistent paths in two clones search nothing", ALLOW,
         "grep -n foo %s/inventory-api/src/missing.py %s/web-app/src/missing.py" % (R, R)),
        ("pattern from inside clone A + clone B dir = one repo", ALLOW,
         "grep -rn foo %s/web-app/src" % R),
        ("exact file + glob over clones", BLOCK,
         "grep -n foo %s/inventory-api/src/a.py %s/*/src/a.py" % (R, R)),
    ]
    for name, want, cmd in cases:
        rc, err = e.run(t, "s-down", "Bash", bash(cmd))
        check("down/Bash " + name, rc, want, err)

    rc, err = e.run(t, "s-down", "Bash", bash("rg foo %s" % R))
    check("down/Bash block names the fleet root and the ack marker",
          int(R in err and "# cs-down-ack" in err), 1)

    cwd_cases = [
        ("rg with no path, cwd = root", BLOCK, "rg foo", R),
        ("grep -r with no path, cwd = root", BLOCK, "grep -rn foo", R),
        ("relative two clones, cwd = root", BLOCK, "grep -rn foo inventory-api pricing-lib", R),
        ("relative one clone, cwd = root", ALLOW, "grep -rn foo inventory-api", R),
        ("regex pattern + one clone, cwd = root", ALLOW, "grep -rn 'foo.*bar' inventory-api", R),
        ("rg -g filter in one clone", ALLOW, "rg -g '*.py' foo", os.path.join(R, "inventory-api")),
        ("rg . inside one clone", ALLOW, "rg foo .", os.path.join(R, "inventory-api")),
        ("rg .. from one clone = root", BLOCK, "rg foo ..", os.path.join(R, "inventory-api")),
        ("non-recursive grep, cwd = root", ALLOW, "grep foo notes.txt", R),
        ("relative exact files in two clones, cwd = root", ALLOW,
         "grep -n foo inventory-api/src/a.py web-app/src/a.py", R),
    ]
    for name, want, cmd, cwd in cwd_cases:
        rc, err = e.run(t, "s-down", "Bash", bash(cmd), cwd=cwd)
        check("down/Bash " + name, rc, want, err)

    check("down/Grep path = root blocks",
          e.run(t, "s-down", "Grep", {"pattern": "x", "path": R})[0], BLOCK)
    check("down/Grep path = one clone passes",
          e.run(t, "s-down", "Grep", {"pattern": "x", "path": R + "/web-app"})[0], ALLOW)
    check("down/Grep no path, cwd = root blocks",
          e.run(t, "s-down", "Grep", {"pattern": "x"}, cwd=R)[0], BLOCK)
    check("down/Read anywhere passes",
          e.run(t, "s-down", "Read", {"file_path": R + "/inventory-api/x"})[0], ALLOW)

    # --- configuration -------------------------------------------------------------
    # The two configurable behaviours, each from the environment and from fleet.env,
    # and the precedence between them. The session is already flagged, so each run
    # reaches the cross-repo guard.
    two_files = "grep -n foo %s/inventory-api/src/a.py %s/web-app/src/a.py" % (R, R)
    check("config: files-are-reads=0 (env) makes two exact files two repos",
          e.run(t, "s-down", "Bash", bash(two_files),
                env={"CS_DISCONNECT_FILES_ARE_READS": "0"})[0], BLOCK)
    check("config: a custom ack marker (env) allows",
          e.run(t, "s-down", "Bash", bash("rg foo %s  # grep-ok" % R),
                env={"CS_DISCONNECT_ACK": "grep-ok"})[0], ALLOW)
    rc, err = e.run(t, "s-down", "Bash", bash("rg foo %s  # cs-down-ack" % R),
                    env={"CS_DISCONNECT_ACK": "grep-ok"})
    check("config: ...and the default marker no longer does", rc, BLOCK, err)
    check("  ...the message names the custom marker", int("# grep-ok" in err), 1)

    e.config(FLEET_ROOT=R, CS_DISCONNECT_GUARD="1", CS_DISCONNECT_FILES_ARE_READS="0",
             CS_DISCONNECT_ACK="grep-ok")
    check("config: files-are-reads=0 from fleet.env",
          e.run(t, "s-down", "Bash", bash(two_files))[0], BLOCK)
    check("config: ack marker from fleet.env",
          e.run(t, "s-down", "Bash", bash("rg foo %s  # grep-ok" % R))[0], ALLOW)
    check("config: the environment beats fleet.env",
          e.run(t, "s-down", "Bash", bash(two_files),
                env={"CS_DISCONNECT_FILES_ARE_READS": "1"})[0], ALLOW)

    e.config(FLEET_ROOT=R)
    t_off = e.transcript([START, DOWN])
    check("config: guard not enabled -> nothing fires", e.run(t_off, "s-off")[0], ALLOW)
    check("config: ...and it leaves no state behind",
          int(os.path.exists(os.path.join(H, ".local", "state", "code-search",
                                          "disconnect-guard", "s-off.json"))), 0)
    check("config: CS_DISCONNECT_GUARD=1 in the environment enables it",
          e.run(t_off, "s-off", env={"CS_DISCONNECT_GUARD": "1"})[0], BLOCK)
    e.config(FLEET_ROOT=R, CS_DISCONNECT_GUARD="1")
    check("config: CS_DISCONNECT_GUARD=0 in the environment beats fleet.env",
          e.run(e.transcript([START, DOWN]), "s-off2", env={"CS_DISCONNECT_GUARD": "0"})[0],
          ALLOW)

    # The fleet root comes from the configuration, not from a fixed path: the same
    # command is cross-repo under one root and a one-repo search under another.
    e.config(FLEET_ROOT=R, CS_DISCONNECT_GUARD="1")
    check("config: FLEET_ROOT from fleet.env",
          e.run(t, "s-down", "Bash", bash("rg foo %s/inventory-api %s/web-app" % (R, R)))[0],
          BLOCK)
    other = os.path.join(H, "other-fleet")
    os.makedirs(os.path.join(other, "a"))
    os.makedirs(os.path.join(other, "b"))
    check("config: FLEET_ROOT from the environment beats fleet.env",
          e.run(t, "s-down", "Bash", bash("rg foo %s/inventory-api %s/web-app" % (R, R)),
                env={"FLEET_ROOT": other})[0], ALLOW)
    check("config: ...and a search across the configured root blocks",
          e.run(t, "s-down", "Bash", bash("rg foo %s/a %s/b" % (other, other)),
                env={"FLEET_ROOT": other})[0], BLOCK)
    e.config(CS_DISCONNECT_GUARD="1")
    os.makedirs(os.path.join(H, "code", "fleet", "x"))
    os.makedirs(os.path.join(H, "code", "fleet", "y"))
    check("config: unset FLEET_ROOT falls back to ~/code/fleet, as cs does",
          e.run(t, "s-down", "Bash", bash("rg foo ~/code/fleet/x ~/code/fleet/y"))[0], BLOCK)
    e.config(FLEET_ROOT=R, CS_DISCONNECT_GUARD="1")

    # --- reconnect, incremental replay, second disconnect -------------------------
    t = e.transcript([START, DOWN, UP])
    check("reconnected: nothing fires", e.run(t, "s-re")[0], ALLOW)
    check("reconnected: cross-repo grep passes",
          e.run(t, "s-re", "Bash", bash("grep -rn foo %s" % R))[0], ALLOW)

    t = e.transcript([START])
    check("incremental: connected", e.run(t, "s-inc")[0], ALLOW)
    with open(t, "a") as fh:
        fh.write(DOWN + "\n")
    check("incremental: disconnect appended -> flag", e.run(t, "s-inc")[0], BLOCK)
    check("incremental: still down -> cross-repo blocked",
          e.run(t, "s-inc", "Bash", bash("rg x %s" % R))[0], BLOCK)
    with open(t, "a") as fh:
        fh.write(UP + "\n")
    check("incremental: reconnect appended -> clear",
          e.run(t, "s-inc", "Bash", bash("rg x %s" % R))[0], ALLOW)
    with open(t, "a") as fh:
        fh.write(DOWN2 + "\n")
    check("incremental: second disconnect flags again", e.run(t, "s-inc")[0], BLOCK)

    # --- start-up shapes ---------------------------------------------------------
    t = e.transcript([delta("2025-01-01T08:00:00Z", pending=[SERVER]),
                      delta("2025-01-01T08:00:20Z", failed=[SERVER])])
    rc, err = e.run(t, "s-failstart")
    check("failed at start (pending -> failed) flags", rc, BLOCK, err)

    t = e.transcript([delta("2025-01-01T08:00:00Z", pending=[SERVER]),
                      delta("2025-01-01T08:00:20Z", added=CS_NAMES)])
    check("pending at start then added: nothing fires", e.run(t, "s-pend")[0], ALLOW)

    t = e.transcript([delta("2025-01-01T08:00:00Z", added=["Read"]), user("hi")])
    check("cs never present: nothing fires", e.run(t, "s-never")[0], ALLOW)
    check("cs never present: cross-repo grep passes",
          e.run(t, "s-never", "Bash", bash("grep -rn x %s" % R))[0], ALLOW)

    # A manual registration's tools (`mcp__cs__*`) are not this plugin's server.
    t = e.transcript([delta("2025-01-01T08:00:00Z", added=["mcp__cs__cs_text"]),
                      delta("2025-01-01T08:10:00Z", removed=["mcp__cs__cs_text"],
                            failed=["cs"])])
    check("another server's cs tools dropping: nothing fires", e.run(t, "s-other")[0], ALLOW)

    # --- content that merely quotes the event -------------------------------------
    quote = user('see the record: {"type": "deferred_tools_delta", "removedNames": %s, '
                 '"failedMcpServers": [{"name": "%s"}]} -- cs disconnected'
                 % (json.dumps(CS_NAMES), SERVER))
    tool_result = json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "content": DOWN}]}})
    t = e.transcript([START, quote, tool_result])
    check("quoted event in a message / tool_result: no fire", e.run(t, "s-quote")[0], ALLOW)

    # --- partial line, shrink ----------------------------------------------------
    t = e.transcript([START, DOWN], newline=False)
    check("partial trailing record not consumed yet", e.run(t, "s-part")[0], ALLOW)
    with open(t, "a") as fh:
        fh.write("\n")
    check("...consumed once its newline lands", e.run(t, "s-part")[0], BLOCK)

    t = e.transcript([START, DOWN, user("x" * 5000)])
    check("shrink: down before rewrite", e.run(t, "s-shrink")[0], BLOCK)
    with open(t, "w") as fh:
        fh.write(START + "\n")
    check("shrink: transcript rewritten smaller -> replay from 0",
          e.run(t, "s-shrink", "Bash", bash("rg x %s" % R))[0], ALLOW)

    # --- two sessions interleaving through the same state directory ---------------
    ta = e.transcript([START, DOWN])
    tb = e.transcript([START])
    seq = [("A", ta, BLOCK), ("B", tb, ALLOW), ("A", ta, ALLOW), ("B", tb, ALLOW),
           ("A", ta, ALLOW)]
    for i, (s, tp, want) in enumerate(seq):
        check("interleave #%d session %s" % (i + 1, s), e.run(tp, "s-il-" + s)[0], want)
    check("interleave: B cross-repo passes",
          e.run(tb, "s-il-B", "Bash", bash("rg x %s" % R))[0], ALLOW)
    check("interleave: A cross-repo blocked",
          e.run(ta, "s-il-A", "Bash", bash("rg x %s" % R))[0], BLOCK)

    # --- per-agent one-shot: a subagent's first call must not consume the main agent's ---
    t = e.transcript([START, DOWN])
    check("agent: subagent first call blocks", e.run(t, "s-ag", agent="ag1")[0], BLOCK)
    check("agent: same subagent second call passes", e.run(t, "s-ag", agent="ag1")[0], ALLOW)
    check("agent: main agent still gets its own block", e.run(t, "s-ag")[0], BLOCK)
    check("agent: main agent second call passes", e.run(t, "s-ag")[0], ALLOW)
    check("agent: a second subagent gets its own block", e.run(t, "s-ag", agent="ag2")[0], BLOCK)
    check("agent: cross-repo still blocked for a flagged subagent",
          e.run(t, "s-ag", "Bash", bash("rg x %s" % R), agent="ag1")[0], BLOCK)
    t = e.transcript([START, DOWN])
    check("agent: main first, then subagent still blocks once", e.run(t, "s-ag2")[0], BLOCK)
    check("agent: ...subagent after main", e.run(t, "s-ag2", agent="ag9")[0], BLOCK)
    check("agent: ...and not twice", e.run(t, "s-ag2", agent="ag9")[0], ALLOW)

    # --- fail open ---------------------------------------------------------------
    check("bad JSON payload fails open", e.run(None, None, raw="{not json")[0], ALLOW)
    check("missing transcript fails open",
          e.run(os.path.join(H, "nope.jsonl"), "s-missing")[0], ALLOW)
    t = e.transcript([START, DOWN])
    check("a session id with a path in it cannot escape the state directory",
          e.run(t, "../../escape")[0], BLOCK)
    check("  ...nothing was written outside it",
          int(any(n.startswith("escape") for n in os.listdir(os.path.join(H, ".local")))), 0)

    shutil.rmtree(H, ignore_errors=True)
    passed = sum(RESULTS)
    print("%d of %d cases passed" % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
