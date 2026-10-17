"""Fixture cases for hub-source/run, the code-search source toolworks-hub runs.

Run by verify-search against its fixture fleet. Three things are under test, in
order of how much a regression would cost:

  1. a refusal is an error, never an empty result -- the hub would show "no
     results" for a search that did not happen;
  2. every result keeps its evidence kind, and the `searching:` line reaches
     the notice above the hits;
  3. detect tells an empty or missing fleet apart from a working one, and
     names the fix.

When a toolworks-hub checkout sits beside this repo, or HUB_ROOT names one, its
check-source runs against the source as well; otherwise that case is skipped.

Usage: python3 cases.py CS FLEET_ROOT
Prints one `PASS <name>`, `FAIL <name> ...` or `SKIP <name> ...` line per case;
exits 1 if any failed.
"""
import json
import os
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


def run(*args, fleet=FLEET):
    env = dict(os.environ, FLEET_ROOT=fleet)
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

rc, d, raw = run("fetch", "find", "--query", "PriceCalculator")
res = (d or {}).get("data", {}).get("results", [])
case("find: the fixture's three PriceCalculator hits, as repo/path:line",
     rc == 0 and len(res) == 3
     and "checkout-service-kotlin/src/main/kotlin/com/acme/checkout/PriceCalculator.kt:7" in [r["title"] for r in res],
     raw[:400])
case("find: every result carries cs's evidence kind",
     res and all(r.get("evidence") == "textual" for r in res), raw[:400])
case("find: the searching: line is in the notice", "fleet only (6 repo(s), main)" in (d or {}).get("notice", ""),
     raw[:400])

rc, d, raw = run("fetch", "find", "--query", "no-such-string-anywhere-q7x")
case("find: zero hits is an empty result, with the scope it searched",
     rc == 0 and d and d["data"]["results"] == [] and "6 repo(s)" in d.get("notice", ""), raw[:400])

rc, d, raw = run("fetch", "find", "--query", "--porcelain")
case("find: a refused query is an error, never an empty result",
     rc == 1 and d is None and "flag" in raw, raw[:400])

rc, d, raw = run("fetch", "fleet")
repos = [r["repo"] for r in (d or {}).get("data", {}).get("rows", [])]
case("fleet: every fixture repo, with its branch",
     rc == 0 and {"inventory-api-dotnet", "pricing-lib-java"} <= set(repos) and len(repos) == 6
     and all(r["branch"] == "main" for r in d["data"]["rows"]), raw[:400])

rc, d, raw = run("fetch", "doctor")
items = (d or {}).get("data", {}).get("items", [])
case("doctor: cs doctor's checks, one item each",
     rc == 0 and any(i["text"] == "✓ cs" for i in items) and any(i["text"].endswith(" fleet") for i in items), raw[:400])

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
