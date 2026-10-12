"""Fixture cases for `cs serve` (scripts/cs-serve), run by verify-search.

Starts the server for real, on a free port, against the suite's fixture fleet and a
ticket workspace made here, and talks to it over HTTP the way the page does. Three
things are under test, in order of how much a regression would cost:

  1. the lock: no token, a wrong token, a foreign Host, a foreign Origin or a
     non-JSON body is refused -- any web page the user has open can reach
     127.0.0.1, and the answers are the fleet's code;
  2. no drift: the page is offered exactly cs-mcp's tools, and an answer is cs's
     own porcelain envelope, refusals included;
  3. the scope: the page opens on the workspace `cs serve` was started in, and a
     hit carries the absolute path of the layer it came from.

Usage: python3 cases.py CS FLEET_ROOT
Prints one `PASS <name>` or `FAIL <name> ...` line per case; exits 1 if any failed.
"""
import http.client
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

CS, FLEET = os.path.abspath(sys.argv[1]), os.path.realpath(sys.argv[2])
HERE = os.path.dirname(os.path.abspath(CS))
results = []


def case(name, ok, why=""):
    ok = bool(ok)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else ": " + why))


def start(cwd, tickets):
    env = dict(os.environ, FLEET_ROOT=FLEET, TICKETS_ROOT=tickets)
    env.pop("WORKSPACE_ROOTS", None)
    proc = subprocess.Popen([CS, "serve", "--no-open"], cwd=cwd, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True)
    line, deadline = "", time.time() + 20
    while time.time() < deadline:
        line = proc.stderr.readline()
        m = re.search(r"http://127\.0\.0\.1:(\d+)/\?t=(\S+)", line)
        if m:
            return proc, int(m.group(1)), m.group(2)
        if not line and proc.poll() is not None:
            break
    proc.kill()
    raise RuntimeError("cs serve printed no URL: %r" % line)


def req(port, method, path, token=None, body=None, headers=None):
    h = {"Host": "127.0.0.1:%d" % port}
    if token:
        h["X-CS-Token"] = token
    if body is not None:
        h["Content-Type"] = "application/json"
        body = json.dumps(body)
    h.update(headers or {})
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        return r.status, r.getheader("Content-Type", ""), json.loads(data)
    except ValueError:
        return r.status, r.getheader("Content-Type", ""), data.decode("utf-8", "replace")


def call(port, token, tool, arguments):
    return req(port, "POST", "/api/call", token, {"tool": tool, "arguments": arguments})[2]


tmp = tempfile.mkdtemp()
servers = []
try:
    tickets = os.path.join(tmp, "tickets")
    ws = os.path.join(tickets, "SERVE-1")
    os.makedirs(ws)
    subprocess.run(["git", "clone", "-q", os.path.join(FLEET, "pricing-lib-java"),
                    os.path.join(ws, "pricing-lib-java")], check=True)
    # NOT realpath'd: on macOS a temp dir is /var/..., which is /private/var/...
    # -- the page must still open on this workspace when its root is a symlink.
    rws = os.path.realpath(ws)
    same = lambda p: bool(p) and os.path.realpath(p) == rws
    inside = os.path.join(ws, "pricing-lib-java", "src")

    proc, port, token = start(inside, tickets)
    servers.append(proc)

    # ---- 1. the lock -------------------------------------------------------
    s, _, _ = req(port, "GET", "/")
    case("page-needs-token", s == 403, "GET / without the token answered %d" % s)
    s, _, _ = req(port, "GET", "/api/meta", "not-the-token")
    case("api-rejects-wrong-token", s == 403, "a wrong token answered %d" % s)
    s, _, _ = req(port, "GET", "/api/meta", token, headers={"Host": "evil.example:%d" % port})
    case("api-rejects-foreign-host", s == 403,
         "a rebinding-shaped Host header answered %d" % s)
    s, _, _ = req(port, "POST", "/api/call", token, {"tool": "cs_scopes", "arguments": {}},
                  headers={"Origin": "http://evil.example"})
    case("api-rejects-foreign-origin", s == 403, "a foreign Origin answered %d" % s)
    s, _, _ = req(port, "POST", "/api/call", token, {"tool": "cs_scopes", "arguments": {}},
                  headers={"Content-Type": "text/plain"})
    case("api-takes-json-only", s == 415,
         "a text/plain POST (no CORS preflight) answered %d" % s)

    s, ctype, page = req(port, "GET", "/?t=" + token)
    case("page-served-with-token", s == 200 and ctype.startswith("text/html"),
         "GET /?t=<token> answered %d %s" % (s, ctype))
    # Local and offline: nothing on the page may load from the network.
    external = re.findall(r'(?:src|href)\s*=\s*["\']?(?:https?:)?//', page if isinstance(page, str) else "")
    case("page-loads-nothing-remote", not external, "remote references: %r" % external)

    # ---- 2. no drift -------------------------------------------------------
    loader = importlib.machinery.SourceFileLoader("cs_mcp_cases", os.path.join(HERE, "cs-mcp"))
    spec = importlib.util.spec_from_loader("cs_mcp_cases", loader)
    mcp = importlib.util.module_from_spec(spec)
    loader.exec_module(mcp)
    s, _, meta = req(port, "GET", "/api/meta", token)
    names = [t["name"] for t in meta.get("tools", [])] if isinstance(meta, dict) else []
    case("tools-are-cs-mcp-tools", names == [t[0] for t in mcp.TOOLS],
         "page offers %r" % names)
    version = open(os.path.join(HERE, "..", "VERSION")).read().strip()
    case("meta-states-version", meta.get("version") == version,
         "meta says %r, VERSION says %r" % (meta.get("version"), version))

    # ---- 3. the scope ------------------------------------------------------
    case("opens-on-start-workspace", same(meta.get("default_scope")),
         "started in %s, default scope %r" % (inside, meta.get("default_scope")))

    r = call(port, token, "cs_uses", {"query": "DiscountEngine", "scope": ws})
    env = r.get("envelope") or {}
    case("answer-is-the-envelope", env.get("cs") == 1 and env.get("subcommand") == "uses"
         and (env.get("hits") or 0) > 0 and env.get("kind"),
         "got %r" % {k: env.get(k) for k in ("cs", "subcommand", "hits", "kind")} if env else r)
    case("answer-names-the-scope", same(env.get("scope")) and (env.get("scope") or "?") in (env.get("view") or ""),
         "scope %r view %r" % (env.get("scope"), env.get("view")))
    repos = r.get("repos") or {}
    missing = [h for h in env.get("results", []) if h.get("path") and not os.path.isfile(
        os.path.join((repos.get(h["repo"]) or {}).get("path", "/nonexistent"), h["path"]))]
    case("hits-resolve-to-files", env.get("results") and not missing,
         "hits with no file behind them: %r" % missing[:3])
    layer = (repos.get("pricing-lib-java") or {})
    case("ticket-hit-is-from-ticket", layer.get("layer") == "ticket"
         and os.path.realpath(layer.get("path", "/")).startswith(rws + "/"),
         "pricing-lib-java resolved to %r" % layer)

    r = call(port, token, "cs_impls", {"symbol": "IFoo", "repo": "no-such-repo", "scope": "fleet"})
    env = r.get("envelope") or {}
    case("refusal-passes-through", env.get("refused") is True and "no-such-repo" in (env.get("reason") or ""),
         "got %r" % r)
    r = call(port, token, "cs_uses", {"query": "DiscountEngine"})
    case("no-scope-is-refused", "scope is required" in (r.get("error") or ""), "got %r" % r)
    r = call(port, token, "cs_uses", {"query": "--fleet", "scope": "fleet"})
    case("flag-shaped-argument-refused", "spelled like a cs flag" in (r.get("error") or ""),
         "got %r" % r)
    r = call(port, token, "cs_why", {"kind": "textual"})
    case("explainer-returns-text", isinstance(r.get("text"), str) and r["text"].strip(), "got %r" % r)
    s, _, r = req(port, "GET", "/api/repos?scope=" + ws, token)
    case("repo-names-for-scope", isinstance(r, dict) and "pricing-lib-java" in (r.get("repos") or {}),
         "got %r" % r)

    # Started outside every workspace, it opens on the fleet -- and says so.
    proc2, port2, token2 = start(FLEET, tickets)
    servers.append(proc2)
    meta2 = req(port2, "GET", "/api/meta", token2)[2]
    case("opens-on-fleet-outside-workspaces", meta2.get("default_scope") == "fleet",
         "default scope %r" % meta2.get("default_scope"))

    # The query is the proprietary part of a private fleet: not in the server log.
    for p in servers:
        p.terminate()
    log = "".join(p.communicate(timeout=10)[1] or "" for p in servers)
    case("queries-not-logged", "DiscountEngine" not in log, "server stderr: %r" % log[-300:])
except Exception as e:  # a crash is a failure with its reason, not a silent zero
    case("harness", False, repr(e))
finally:
    for p in servers:
        if p.poll() is None:
            p.kill()
    shutil.rmtree(tmp, ignore_errors=True)

n = len(results)
print("%d of %d cases passed" % (sum(results), n))
sys.exit(0 if all(results) else 1)
