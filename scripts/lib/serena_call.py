#!/usr/bin/env python3
"""Call one Serena MCP tool over stdio and print its JSON result.

Serena has no query CLI -- it is an MCP server -- so the facade speaks the
protocol directly rather than shelling out to an agent.

Usage: serena_call.py <project-dir> <tool-name> [json-args]

Exit 3 when the language server never finished importing the project in the
time allowed: whatever it said is not an answer (see wait_until_imported).
"""
import glob
import json
import os
import subprocess
import sys
import threading
import time

SERENA = ["uvx", "--from", "git+https://github.com/oraios/serena", "serena",
          "start-mcp-server", "--transport", "stdio", "--enable-web-dashboard", "false"]


# Serena's Java wrapper waits for the server to report the project imported, but
# only for 20 seconds -- a "hotfix" in its source -- and only for the status
# `OK`. Past that, or on any other status, it logs this and answers anyway, from
# a project that is still importing. A cold multi-module Gradle build takes
# longer than that, and the answer was `resolved · 0 hit(s)` for an interface
# with two implementations; the same command minutes later found both (#76).
# Reproduced by killing a first import part-way, as cs's own find_symbol call
# can: the next server started, reported `ProjectStatus: WARNING`, waited its
# 20s and queried a project with nothing imported.
NOT_READY = "proceeding anyway"
IMPORT_DONE = "'type': 'ProjectStatus'"
LOG_ROOT = os.path.expanduser("~/.serena/logs")


def descendants(pid):
    """pid and every process below it: uvx starts Serena as a child, and the
    log file is named after Serena's pid, not ours."""
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        try:
            kids = subprocess.run(["pgrep", "-P", str(p)], capture_output=True,
                                  text=True, timeout=5).stdout.split()
        except (OSError, subprocess.SubprocessError):
            kids = []
        todo.extend(int(k) for k in kids if k.isdigit())
    return out


def own_log(pid):
    for p in descendants(pid):
        hits = glob.glob(os.path.join(LOG_ROOT, "*", "mcp_*_{}.txt".format(p)))
        if hits:
            return max(hits, key=os.path.getmtime)
    return None


def read(path):
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def import_state(log, budget, alive=lambda: True, poll=2):
    """What the server's log says about its project import, for one answer.

    ("confirmed", 0)  it never gave up waiting: the answer stands
    ("warned", 0)     it gave up, but a status had already come (not `OK`, which
                      Serena alone accepts -- `WARNING` on a build with problems):
                      the import is over, the answer stands, with a note
    ("late", secs)    it gave up and the status came later: ask again
    ("never", secs)   no status within the budget: the answer is not one
    """
    text = read(log) if log else ""
    gave_up = text.find(NOT_READY)
    if gave_up < 0:
        return ("confirmed", 0)
    if text.rfind(IMPORT_DONE, 0, gave_up) >= 0:
        return ("warned", 0)
    t0 = time.time()
    while time.time() - t0 < budget and alive():
        if read(log).find(IMPORT_DONE, gave_up) >= 0:
            return ("late", int(time.time() - t0))
        time.sleep(poll)
    return ("never", int(time.time() - t0))


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2

    project, tool = sys.argv[1], sys.argv[2]
    args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}

    proc = subprocess.Popen(
        SERENA + ["--project", project],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )

    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def read_until(match_id, timeout=300):
        box = {}

        def reader():
            for line in proc.stdout:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == match_id:
                    box["msg"] = msg
                    return

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout)
        return box.get("msg")

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "cs-facade", "version": "1"}}})
    if not read_until(1):
        print("serena: initialize timed out", file=sys.stderr)
        proc.terminate()
        return 1
    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": tool, "arguments": args}})
    res = read_until(2)

    # Asked before the import finished: wait for it, then ask again. The
    # budget stays inside cs's own engine timeout, so a slow import ends in
    # this script's refusal rather than in a kill that reads as a timeout.
    budget = max(10, int(os.environ.get("CS_TIMEOUT", "120") or 120) - 30)
    state, secs = (import_state(own_log(proc.pid), budget, lambda: proc.poll() is None)
                   if res else ("confirmed", 0))
    if state == "never":
        proc.terminate()
        print("serena: the language server answered before it had imported the "
              "project (Serena stops waiting after 20s), and the import reported "
              "nothing in {}s more, so its answer is not one. Re-run once the "
              "first import has completed, or raise CS_TIMEOUT.".format(secs),
              file=sys.stderr)
        return 3
    if state == "late":
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": tool, "arguments": args}})
        res = read_until(3)
        print("serena: the language server first answered before it had imported "
              "the project; re-asked once the import finished ({}s later), and "
              "this is that answer.".format(secs), file=sys.stderr)
    if state == "warned":
        print("serena: the project import finished with warnings (not OK), so "
              "part of it may not have loaded; an empty answer is weaker than "
              "usual.", file=sys.stderr)
    proc.terminate()

    if not res:
        print("serena: call timed out", file=sys.stderr)
        return 1
    if "error" in res:
        print("serena: " + json.dumps(res["error"])[:300], file=sys.stderr)
        return 1

    for item in res.get("result", {}).get("content", []):
        print(item.get("text", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
