"""Fixture cases for hub-source/run, the code-search source toolworks-hub runs.

Run by verify-search against its fixture fleet. Three things are under test, in
order of how much a regression would cost:

  1. no drift: the hub's code-search page is offered exactly cs-mcp's tools,
     and an answer is cs's own porcelain envelope, refusals included -- a
     refusal is never an empty result;
  2. the scope: a hit carries the absolute path of the layer (ticket
     workspace or fleet) it came from, and the scope menu lists real
     workspaces;
  3. the Fleet facts (commit, forge link, last fetch, files, symbols), and
     detect telling an empty or missing fleet apart from a working one.

When a toolworks-hub checkout sits beside this repo, or HUB_ROOT names one, its
check-source runs against the source as well; otherwise that case is skipped.

Usage: python3 cases.py CS FLEET_ROOT
Prints one `PASS <name>`, `FAIL <name> ...` or `SKIP <name> ...` line per case;
exits 1 if any failed.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

CS, FLEET = os.path.abspath(sys.argv[1]), os.path.realpath(sys.argv[2])
ROOT = os.path.dirname(os.path.dirname(CS))
RUN = os.path.join(ROOT, "hub-source", "run")
results = []


def case(name, ok, why=""):
    ok = bool(ok)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else ": " + why))


def run(*args, fleet=FLEET, tickets=None):
    env = dict(os.environ, FLEET_ROOT=fleet)
    env.pop("WORKSPACE_ROOTS", None)
    if tickets:
        env["TICKETS_ROOT"] = tickets
    p = subprocess.run([RUN, *args], env=env, capture_output=True, text=True, timeout=120,
                       stdin=subprocess.DEVNULL)
    try:
        value = json.loads(p.stdout) if p.stdout.strip() else None
    except ValueError:
        value = None
    return p.returncode, value, p.stdout + p.stderr


with open(os.path.join(ROOT, "VERSION")) as f:
    version = f.read().strip()
with open(os.path.join(ROOT, "hub-source", "source.json")) as f:
    manifest = json.load(f)
case("hub-source/source.json carries the plugin's version", manifest["version"] == version,
     "%s vs VERSION %s" % (manifest["version"], version))
case("hub-source/source.json has no widgets: the hub's page is the whole view",
     "widgets" not in manifest, "widgets: %r" % manifest.get("widgets"))

rc, d, raw = run("detect")
case("detect: the fixture fleet is working, with cs's version",
     rc == 0 and d == {"state": "working", "tool_version": version}, raw)

with tempfile.TemporaryDirectory() as empty:
    rc, d, raw = run("detect", fleet=empty)
    case("detect: an empty fleet is not set up, and says to clone",
         rc == 0 and d and d["state"] == "not_set_up" and "fleet-init --clone" in d.get("fix", ""), raw)
    rc, d, raw = run("detect", fleet=os.path.join(empty, "missing"))
    case("detect: a missing fleet root is not set up, and names fleet.env",
         rc == 0 and d and d["state"] == "not_set_up" and "fleet.env" in d.get("fix", ""), raw)


def call(op, args, **kw):
    return run("call", op, json.dumps(args), **kw)


def ask(tool, arguments, **kw):
    return call("ask", {"tool": tool, "arguments": arguments}, **kw)[1] or {}


loader = importlib.machinery.SourceFileLoader("cs_mcp_cases", os.path.join(ROOT, "scripts", "cs-mcp"))
mcp = importlib.util.module_from_spec(importlib.util.spec_from_loader("cs_mcp_cases", loader))
loader.exec_module(mcp)
rloader = importlib.machinery.SourceFileLoader("hub_run_cases", RUN)
hubrun = importlib.util.module_from_spec(importlib.util.spec_from_loader("hub_run_cases", rloader))
rloader.exec_module(hubrun)

tmp = tempfile.mkdtemp()
try:
    tickets = os.path.join(tmp, "tickets")
    ws = os.path.join(tickets, "HUB-1")
    os.makedirs(ws)
    subprocess.run(["git", "clone", "-q", os.path.join(FLEET, "pricing-lib-java"),
                    os.path.join(ws, "pricing-lib-java")], check=True)
    # NOT realpath'd: on macOS a temp dir is /var/..., which is /private/var/...
    rws = os.path.realpath(ws)
    tk_repo = os.path.join(ws, "pricing-lib-java")
    # The Fleet facts' commit link comes from the remote, and the symbol count
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

    # A grouping folder holding a stray clone beside a workspace: `cs scopes`
    # lists it with a "(mixed: ...)" suffix, which must be stripped, not kept.
    grp = os.path.join(tickets, "grp")
    os.makedirs(os.path.join(grp, "W-2"))
    for dest in (os.path.join(grp, "stray"), os.path.join(grp, "W-2", "kit-service-python")):
        subprocess.run(["git", "clone", "-q", os.path.join(FLEET, "kit-service-python"), dest], check=True)
    T = {"tickets": tickets}

    # ---- 1. no drift ---------------------------------------------------------
    rc, meta, raw = call("meta", {}, **T)
    meta = meta or {}
    names = [t["name"] for t in meta.get("tools", [])]
    case("meta: the page is offered exactly cs-mcp's tools", rc == 0 and names == [t[0] for t in mcp.TOOLS],
         "offered %r" % names or raw[:400])
    case("meta: states cs's version", meta.get("version") == version,
         "meta says %r, VERSION says %r" % (meta.get("version"), version))
    values = [x["value"] for x in meta.get("scopes", []) if x["value"] != "fleet"]
    real = set(os.path.realpath(v) for v in values)
    case("meta: every scope is a real folder, the mixed one included",
         values and all(os.path.isdir(v) for v in values)
         and {os.path.realpath(grp), rws, os.path.realpath(os.path.join(grp, "W-2"))} <= real,
         "parsed scopes %r" % values)

    r = ask("cs_uses", {"query": "DiscountEngine", "scope": ws}, **T)
    env = r.get("envelope") or {}
    case("ask: the answer is cs's envelope", env.get("cs") == 1 and env.get("subcommand") == "uses"
         and (env.get("hits") or 0) > 0 and env.get("kind"),
         "got %r" % ({k: env.get(k) for k in ("cs", "subcommand", "hits", "kind")} if env else r))
    case("ask: the answer names the scope", same(env.get("scope")) and (env.get("scope") or "?") in (env.get("view") or ""),
         "scope %r view %r" % (env.get("scope"), env.get("view")))

    # ---- 2. the scope --------------------------------------------------------
    repos = r.get("repos") or {}
    missing = [h for h in env.get("results", []) if h.get("path") and not os.path.isfile(
        os.path.join((repos.get(h["repo"]) or {}).get("path", "/nonexistent"), h["path"]))]
    case("ask: every hit resolves to a file", env.get("results") and not missing,
         "hits with no file behind them: %r" % missing[:3])
    layer = repos.get("pricing-lib-java") or {}
    case("ask: a ticket repo's hits come from the ticket workspace", layer.get("layer") == "ticket"
         and os.path.realpath(layer.get("path", "/")).startswith(rws + "/"),
         "pricing-lib-java resolved to %r" % layer)

    r = ask("cs_impls", {"symbol": "IFoo", "repo": "no-such-repo", "scope": "fleet"}, **T)
    env = r.get("envelope") or {}
    case("ask: a refusal passes through as a refusal", env.get("refused") is True
         and "no-such-repo" in (env.get("reason") or ""), "got %r" % r)
    r = ask("cs_uses", {"query": "DiscountEngine"}, **T)
    case("ask: no scope is refused", "scope is required" in (r.get("error") or ""), "got %r" % r)
    r = ask("cs_uses", {"query": "--fleet", "scope": "fleet"}, **T)
    case("ask: a flag-shaped argument is refused", "spelled like a cs flag" in (r.get("error") or ""), "got %r" % r)
    r = ask("cs_why", {"kind": "textual"}, **T)
    case("ask: an explainer returns text", isinstance(r.get("text"), str) and r["text"].strip(), "got %r" % r)
    rc, d, raw = call("repos", {"scope": ws}, **T)
    case("repos: the repo names in a scope", "pricing-lib-java" in ((d or {}).get("repos") or {}), raw[:400])

    r = ask("cs_text", {"pattern": "DiscountEngine(", "literal": True, "in_repo": "pricing-lib-java", "scope": ws}, **T)
    env = r.get("envelope") or {}
    hits = env.get("results") or []
    case("ask: the search box is literal and narrowed to a repo",
         hits and all(h["repo"] == "pricing-lib-java" for h in hits)
         and "narrowed by --repo=" in (env.get("view") or "") and env.get("note") == "literal",
         "got %r" % {k: env.get(k) for k in ("view", "note", "hits", "refused", "reason")})

    rc, d, raw = run("call", "ask", "not json", **T)
    case("call: arguments that are not a JSON object are a usage error", rc == 2 and "JSON object" in raw, raw[:400])
    rc, d, raw = run("call", "nope", "{}", **T)
    case("call: an unknown call is a usage error", rc == 2 and "unknown command" in raw, raw[:400])

    # ---- 3. the Fleet facts ----------------------------------------------------
    rc, fl, raw = call("fleet", {"scope": ws}, **T)
    rows = {r["name"]: r for r in ((fl or {}).get("repos") or [])}
    want = set((call("repos", {"scope": ws}, **T)[1] or {}).get("repos") or {})
    case("fleet: every repo in the scope", set(rows) == want and want, "fleet %r vs repos %r" % (sorted(rows), sorted(want)))
    pl = rows.get("pricing-lib-java", {})
    git_sha = subprocess.run(["git", "-C", tk_repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    git_files = len(subprocess.run(["git", "-C", tk_repo, "ls-files"], capture_output=True, text=True).stdout.split())
    case("fleet: a row's facts come from git", pl.get("layer") == "ticket" and pl.get("commit") == git_sha
         and pl.get("files") == git_files and pl.get("branch") and pl.get("synced"),
         "got %r (sha %s, %d files)" % (pl, git_sha, git_files))
    case("fleet: the commit links to the forge", pl.get("commit_url") == "https://github.com/acme/pricing-lib-java/commit/" + git_sha,
         "got %r" % pl.get("commit_url"))
    case("fleet: symbols count definitions only", pl.get("symbols") == 2 and pl.get("graph_built"),
         "symbols %r (want 2: file and import nodes are not symbols)" % pl.get("symbols"))
    others = [r for n, r in rows.items() if n != "pricing-lib-java"]
    case("fleet: a repo without a graph has no symbol count",
         others and all(r.get("symbols") is None or r.get("graph_built") for r in others),
         "%r" % [r for r in others if r.get("symbols") is not None and not r.get("graph_built")])

    # Commit links only for forge remotes, each with its own commit path; a
    # local mirror or a Windows path is never turned into https://file//... .
    expect = {
        "git@github.com:acme/a.git": ("https://github.com/acme/a", "/commit/"),
        "https://user@github.acme.io/o/r.git": ("https://github.acme.io/o/r", "/commit/"),
        "ssh://git@gitlab.example.com:2222/g/s/z.git": ("https://gitlab.example.com/g/s/z", "/-/commit/"),
        "git@bitbucket.org:t/r.git": ("https://bitbucket.org/t/r", "/commits/"),
        "file:///Users/x/fleet/repo.git": None, "C:/x/repo": None, "/srv/mirror/repo": None,
        "https://git.internal.example/acme/a": None, "git@host:2222/x": None,
    }
    wrong = {u: hubrun.web_url(u) for u, w in expect.items() if hubrun.web_url(u) != w}
    case("fleet: commit links for forges only", not wrong, "got %r" % wrong)

    # A ticket repo made with `git worktree add` has its own FETCH_HEAD, which a
    # fetch in the main clone never writes: the shared one must count.
    main_clone = os.path.join(tmp, "mirror", "kit-service-python")
    subprocess.run(["git", "clone", "-q", os.path.join(FLEET, "kit-service-python"), main_clone], check=True)
    subprocess.run(["git", "-C", main_clone, "fetch", "-q"], check=True)
    wt = os.path.join(tmp, "wt", "WT-1", "kit-service-python")
    subprocess.run(["git", "-C", main_clone, "worktree", "add", "-q", "-b", "wt1", wt],
                   check=True, capture_output=True)
    shared = int(os.path.getmtime(os.path.join(main_clone, ".git", "FETCH_HEAD")))
    facts = hubrun.repo_facts("kit-service-python", {"path": wt, "layer": "ticket"})
    case("fleet: a worktree's last fetch is the shared clone's", facts.get("synced") == shared
         and facts.get("synced_how") == "fetched",
         "synced %r (%r), shared FETCH_HEAD %r" % (facts.get("synced"), facts.get("synced_how"), shared))
except Exception as e:  # a crash is a failure with its reason, not a silent zero
    case("harness", False, repr(e))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

hub = os.environ.get("HUB_ROOT") or os.path.join(os.path.dirname(ROOT), "toolworks-hub")
check = os.path.join(hub, "scripts", "hub")
if os.access(check, os.X_OK):
    p = subprocess.run([check, "check-source", os.path.join(ROOT, "hub-source")],
                       env=dict(os.environ, FLEET_ROOT=FLEET), capture_output=True, text=True, timeout=300)
    case("toolworks-hub's check-source passes", p.returncode == 0, p.stdout[-800:] + p.stderr[-400:])
else:
    print("SKIP toolworks-hub's check-source: no checkout at %s (set HUB_ROOT)" % hub)

passed = sum(results)
print("%d of %d cases passed" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
