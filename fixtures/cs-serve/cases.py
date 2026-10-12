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
import socket
import sqlite3
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
    tk_repo = os.path.join(ws, "pricing-lib-java")
    # The Fleet tab's commit link is built from the remote, and its symbol count
    # from the repo's tokensave graph: a GitHub-shaped remote, and a minimal
    # graph whose nodes are 2 definitions and 2 non-definitions (file, import).
    subprocess.run(["git", "-C", tk_repo, "remote", "set-url", "origin",
                    "git@github.com:acme/pricing-lib-java.git"], check=True)
    os.makedirs(os.path.join(tk_repo, ".tokensave"))
    con = sqlite3.connect(os.path.join(tk_repo, ".tokensave", "tokensave.db"))
    con.execute("CREATE TABLE nodes (id INTEGER PRIMARY KEY, kind TEXT, name TEXT)")
    con.executemany("INSERT INTO nodes (kind, name) VALUES (?, ?)",
                    [("class", "DiscountEngine"), ("method", "apply"),
                     ("file", "DiscountEngine.java"), ("use", "java.util.List")])
    con.commit()
    con.close()
    same = lambda p: bool(p) and os.path.realpath(p) == rws
    inside = os.path.join(ws, "pricing-lib-java", "src")

    # A grouping folder holding a stray clone beside a workspace: `cs scopes`
    # lists it with a "(mixed: …)" suffix, which the page must strip, not keep.
    grp = os.path.join(tickets, "grp")
    os.makedirs(os.path.join(grp, "W-2"))
    for dest in (os.path.join(grp, "stray"), os.path.join(grp, "W-2", "kit-service-python")):
        subprocess.run(["git", "clone", "-q", os.path.join(FLEET, "kit-service-python"), dest], check=True)

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

    # The scope menu is parsed from `cs scopes`' table: every value must be a
    # real directory, the mixed one included, or the parse has drifted.
    values = [x["value"] for x in meta.get("scopes", []) if x["value"] != "fleet"]
    real = set(os.path.realpath(v) for v in values)
    case("scope-menu-paths-exist", values and all(os.path.isdir(v) for v in values)
         and {os.path.realpath(grp), rws, os.path.realpath(os.path.join(grp, "W-2"))} <= real,
         "parsed scopes %r" % values)

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

    for path in ("/api/fleet?scope=fleet", "/api/repos?scope=fleet"):
        s, _, _ = req(port, "GET", path)
        case("needs-token " + path.split("?")[0], s == 403, "answered %d without the token" % s)

    # ---- the Search tab: one box, literal, narrowed to a repo ----------------
    r = call(port, token, "cs_text", {"pattern": "DiscountEngine(", "literal": True,
                                      "in_repo": "pricing-lib-java", "scope": ws})
    env = r.get("envelope") or {}
    hits = env.get("results") or []
    case("search-box-literal-in-repo", hits and all(h["repo"] == "pricing-lib-java" for h in hits)
         and "narrowed by --repo=" in (env.get("view") or "") and env.get("note") == "literal",
         "got %r" % {k: env.get(k) for k in ("view", "note", "hits", "refused", "reason")})

    # ---- the Fleet tab -----------------------------------------------------
    s, _, fl = req(port, "GET", "/api/fleet?scope=" + ws, token)
    rows = {r["name"]: r for r in (fl.get("repos") or [])} if isinstance(fl, dict) else {}
    want = set(req(port, "GET", "/api/repos?scope=" + ws, token)[2].get("repos") or {})
    case("fleet-lists-every-repo", set(rows) == want and want, "fleet %r vs repos %r" % (sorted(rows), sorted(want)))
    pl = rows.get("pricing-lib-java", {})
    git_sha = subprocess.run(["git", "-C", tk_repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    git_files = len(subprocess.run(["git", "-C", tk_repo, "ls-files"], capture_output=True, text=True).stdout.split())
    case("fleet-row-facts", pl.get("layer") == "ticket" and pl.get("commit") == git_sha
         and pl.get("files") == git_files and pl.get("branch") and pl.get("synced"),
         "got %r (sha %s, %d files)" % (pl, git_sha, git_files))
    case("fleet-commit-link", pl.get("commit_url") == "https://github.com/acme/pricing-lib-java/commit/" + git_sha,
         "got %r" % pl.get("commit_url"))
    case("fleet-symbols-are-definitions", pl.get("symbols") == 2 and pl.get("graph_built"),
         "symbols %r (want 2: file and import nodes are not symbols)" % pl.get("symbols"))
    others = [r for n, r in rows.items() if n != "pricing-lib-java"]
    case("fleet-no-graph-is-none", others and all(r.get("symbols") is None or r.get("graph_built") for r in others),
         "a repo without a graph reported symbols: %r" % [r for r in others if r.get("symbols") is not None and not r.get("graph_built")])

    # A negative Content-Length is refused at once, not read until the client
    # hangs up (rfile.read(-1) reads to EOF).
    sk = socket.create_connection(("127.0.0.1", port), timeout=10)
    sk.sendall(("POST /api/call HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-CS-Token: %s\r\n"
                "Content-Type: application/json\r\nContent-Length: -1\r\n\r\n" % (port, token)).encode())
    try:
        status = sk.recv(64).decode("latin-1").split(" ")[1]
    except (socket.timeout, IndexError):
        status = "no answer within 10s"
    sk.close()
    case("negative-content-length-refused", status == "400", "answered %s" % status)

    # Commit links only for forge remotes, each with its own commit path; a
    # local mirror or a Windows path is never turned into https://file//… .
    sloader = importlib.machinery.SourceFileLoader("cs_serve_cases", os.path.join(HERE, "cs-serve"))
    srv = importlib.util.module_from_spec(importlib.util.spec_from_loader("cs_serve_cases", sloader))
    sloader.exec_module(srv)
    expect = {
        "git@github.com:acme/a.git": ("https://github.com/acme/a", "/commit/"),
        "https://user@github.acme.io/o/r.git": ("https://github.acme.io/o/r", "/commit/"),
        "ssh://git@gitlab.example.com:2222/g/s/z.git": ("https://gitlab.example.com/g/s/z", "/-/commit/"),
        "git@bitbucket.org:t/r.git": ("https://bitbucket.org/t/r", "/commits/"),
        "file:///Users/x/fleet/repo.git": None, "C:/x/repo": None, "/srv/mirror/repo": None,
        "https://git.internal.example/acme/a": None, "git@host:2222/x": None,
    }
    wrong = {u: srv.web_url(u) for u, w in expect.items() if srv.web_url(u) != w}
    case("commit-links-forges-only", not wrong, "got %r" % wrong)

    # A ticket repo made with `git worktree add` has its own FETCH_HEAD, which a
    # fetch in the main clone never writes: the shared one must count.
    main_clone = os.path.join(tmp, "mirror", "kit-service-python")
    subprocess.run(["git", "clone", "-q", os.path.join(FLEET, "kit-service-python"), main_clone], check=True)
    subprocess.run(["git", "-C", main_clone, "fetch", "-q"], check=True)
    wt = os.path.join(tmp, "wt", "WT-1", "kit-service-python")
    subprocess.run(["git", "-C", main_clone, "worktree", "add", "-q", "-b", "wt1", wt],
                   check=True, capture_output=True)
    shared = int(os.path.getmtime(os.path.join(main_clone, ".git", "FETCH_HEAD")))
    facts = srv.repo_facts("kit-service-python", {"path": wt, "layer": "ticket"})
    case("worktree-synced-from-shared-fetch", facts.get("synced") == shared and facts.get("synced_how") == "fetched",
         "synced %r (%r), shared FETCH_HEAD %r" % (facts.get("synced"), facts.get("synced_how"), shared))

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
