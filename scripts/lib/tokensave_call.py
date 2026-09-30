#!/usr/bin/env python3
"""Ask a tokensave graph a symbol question, in cs's line format.

Why this exists: the `resolved` tier needs a language server, and a language
server needs its language's toolchain. For .NET Framework C# that toolchain is
Windows-only to build, so on macOS or Linux `resolved` is unavailable BY
CONSTRUCTION -- not for want of installing something. Without a fallback, cs has
no answer at all for "what implements this interface" in those repos.

A prebuilt graph is the profile the facade is otherwise missing: offline,
cross-repo, and needing no per-language toolchain.

Four traps, all reproduced against tokensave 7.9.0 rather than taken on trust:

  1. The graph tools take a NODE ID, not a name, and they DISAGREE about what to
     do with a name. `type_hierarchy`, `callers` and `callees` reject a bare name
     loudly ("node not found", exit 1). `callers_for` and `impact` accept one and
     succeed while having looked nothing up:

         tokensave tool callers_for <Name>  -> {"callers": {"<Name>": []}}, exit 0
         tokensave tool impact      <Name>  -> {"node_count": 0, ...},      exit 0

     That is a manufactured negative -- "nothing calls this" is exactly the
     answer someone deletes code on. So every lookup here is two-step
     (name -> node id -> the real question), and a symbol that does not resolve
     to a node exits 3 rather than printing nothing. A well-formed id with
     genuinely no edges also returns empty, and nothing at the call site can
     tell that apart from the bug; only the two-step makes the empty trustworthy.
  2. `tokensave tool ...` accepts `--project <dir>`; `tokensave status` takes its
     path POSITIONALLY and rejects `--project`. Both spellings are used below,
     each where it works.
  3. A graph answers about the code as of its last sync, so it is the one engine
     here that can be confidently WRONG rather than merely blind. Staleness is
     surfaced by the caller; see `cs engines`.
  4. One name is often several nodes -- an interface method and its
     implementation both answer to `ReserveAsync`. Asking only the top-ranked one
     reported "nothing calls ReserveAsync" when the implementation had a caller
     and the interface method did not. Every exact-name node is asked, and the
     set is named on stderr so the reader can see what was actually queried.

Usage: tokensave_call.py <impls|def|callers|callees|impact|fields|field-counts>
                         <repo-dir>
                         <repo-name> <symbol>
Exit:  0 found, 1 nothing found (an honest negative), 3 the symbol does not
       resolve to a node this question can be asked of, 4 the tool itself failed.
"""
import json
import re
import subprocess
import sys

# `Name (kind) -- path:line`, with the edge kind on the indented rows.
ROW = re.compile(r"^\|-\s+(\w+)\s+(.+?)\s+\((\w+)\)\s+--\s+(.+):(\d+)\s*$")

TYPE_KINDS = ("interface", "class", "trait", "struct", "enum", "record", "type")

# `search` is a RANKED, fuzzy match, so `Reserve` also returns ReserveAsync,
# ReservationController and ReserveRequest. cs def answers "where is this symbol
# defined", so only an exact name counts -- and these kinds are references or
# containers rather than definitions, which ctags would not report either.
NOT_A_DEFINITION = ("use", "annotation_usage", "file")

# What can appear at either end of a `calls` edge, across the languages the
# fixture fleet covers (C#, Java, Kotlin, TypeScript, Python).
CALLABLE_KINDS = ("function", "method", "constructor", "abstract_method")

# Containers: a class HAS callers in no sense the call graph records, so asking
# for them would produce an empty result that reads as "nothing calls this".
# That is the one answer this file exists to never manufacture, so a name that
# resolves ONLY to these is refused with the question it should have been.
# A kind in neither list is asked anyway -- a TypeScript `const` can hold an
# arrow function -- because the two-step has already happened by then and the
# node's kind is printed next to every row.
CONTAINER_KINDS = ("class", "interface", "trait", "struct", "enum", "record",
                   "data_class", "kotlin_object", "namespace", "package",
                   "module", "kotlin_package", "type")

# How far `impact` walks. Pinned rather than left to the tool's default, because
# cs states the depth in its provenance line and a claim that tracks a default
# is a claim that changes when someone else changes theirs.
IMPACT_DEPTH = "3"


def _run(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"tokensave could not be run: {e}"
    if p.returncode != 0:
        return None, (p.stderr or p.stdout or "").strip()[:300]
    return p.stdout, None


def _search(project, symbol, limit):
    # Both asked for explicitly: from tokensave 7.13 `search` defaults to a
    # text format ("count: N", one line per hit) and leaves node ids out, and
    # every caller here parses JSON and follows the ids. Earlier versions
    # (7.9, 7.11 measured) accept both flags and already behave that way.
    # `--json` is NOT the same thing -- it wraps the reply in an MCP envelope.
    out, err = _run(["tokensave", "tool", "search", symbol,
                     "--project", project, "--limit", str(limit),
                     "--format", "json", "--ids", "true"])
    if out is None:
        print(f"tokensave search failed: {err}", file=sys.stderr)
        return None
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        print("tokensave search returned no parseable JSON", file=sys.stderr)
        return None
    if not isinstance(rows, list):
        rows = rows.get("results", []) if isinstance(rows, dict) else []
    return [r for r in rows if isinstance(r, dict)]


def _exact_nodes(project, symbol):
    """Every node whose name is EXACTLY the symbol, or None if nothing ran.

    `find_exact_symbol` is an index probe with no ranking and a 200-row cap;
    `search` is BM25 with a default limit of TEN, so on a real repo the node you
    asked about can rank below ten near-misses and simply not be in the list --
    which would arrive here as "this symbol is not in the graph". The ranked
    search is kept only as the fallback for a tokensave without the exact tool.
    """
    out, _ = _run(["tokensave", "tool", "find_exact_symbol", "--name", symbol,
                   "--project", project, "--limit", "200"])
    if out is not None:
        try:
            doc = json.loads(out)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict) and isinstance(doc.get("matches"), list):
            return [m for m in doc["matches"]
                    if isinstance(m, dict) and m.get("id")]
    rows = _search(project, symbol, 200)
    if rows is None:
        return None
    return [r for r in rows if r.get("name") == symbol and r.get("id")]


def _seeds(project, symbol, mode):
    """The nodes to ask `mode` about: (nodes, exit-code). nodes is None on 3/4."""
    nodes = _exact_nodes(project, symbol)
    if nodes is None:
        return None, 4
    nodes = [n for n in nodes if n.get("kind") not in NOT_A_DEFINITION]
    if not nodes:
        # NOT an empty answer. The graph was never asked the question.
        print(f"tokensave: '{symbol}' is not a node in this graph — nothing was "
              f"looked up, so nothing was ruled out", file=sys.stderr)
        return None, 3

    if mode != "impact":
        callable_nodes = [n for n in nodes if n.get("kind") in CALLABLE_KINDS]
        if callable_nodes:
            nodes = callable_nodes
        elif all(n.get("kind") in CONTAINER_KINDS for n in nodes):
            kinds = ", ".join(sorted({n.get("kind", "?") for n in nodes}))
            print(f"tokensave: '{symbol}' resolves only to {kinds} node(s), and "
                  f"a call graph records no calls to or from those — so this is "
                  f"a question the graph cannot be asked, not 'nothing calls it'",
                  file=sys.stderr)
            return None, 3

    if len(nodes) > 1:
        where = ", ".join(f"{n.get('file', '?')}:{n.get('line', '?')}"
                          for n in nodes)
        print(f"tokensave: '{symbol}' is {len(nodes)} nodes in this graph and "
              f"ALL were asked ({where}) — the rows below are their union",
              file=sys.stderr)
    return nodes, 0


def _rows(project, node, mode):
    """The answer rows for one seed node, or None if the tool itself failed."""
    args = ["tokensave", "tool", mode, "--node-id", node["id"],
            "--project", project]
    if mode == "impact":
        args += ["--max-depth", IMPACT_DEPTH]
    else:
        # Depth 1, deliberately. `callees` defaults to 3 and its rows carry no
        # depth field, so the default answer mixes "this function calls it" with
        # "something three hops down does" and gives the reader no way to tell.
        args += ["--max-depth", "1"]
    out, err = _run(args)
    if out is None:
        print(f"tokensave {mode} failed: {err}", file=sys.stderr)
        return None
    try:
        doc = json.loads(out)
    except json.JSONDecodeError:
        print(f"tokensave {mode} returned no parseable JSON", file=sys.stderr)
        return None
    if mode == "impact":
        return doc.get("nodes", []) if isinstance(doc, dict) else []
    return doc if isinstance(doc, list) else []


def graph_edges(project, repo, symbol, mode):
    """cs callers / cs callees / cs impact, as `repo/path:line: text` lines."""
    nodes, rc = _seeds(project, symbol, mode)
    if nodes is None:
        return rc

    seen, no_location = set(), 0
    seed_ids = {n["id"] for n in nodes}
    for node in nodes:
        rows = _rows(project, node, mode)
        if rows is None:
            return 4
        for r in rows:
            if not isinstance(r, dict):
                continue
            # impact reports the radius INCLUDING the node you asked about, and
            # "X depends on X" is not an answer to "what breaks if I change it".
            if mode == "impact" and r.get("id") in seed_ids:
                continue
            if not r.get("file"):
                no_location += 1
                continue
            if mode == "impact":
                edge = f"depends on {symbol}"
            else:
                edge = r.get("edge_kind") or "calls"
                # The graph resolved this through an interface rather than
                # seeing the call site name the concrete method. Worth printing:
                # it is the one place a graph edge is an inference.
                if r.get("dispatch_via_trait"):
                    edge += ", via the interface"
            line = (f"{repo}/{r['file']}:{r.get('line', '?')}: "
                    f"[{r.get('kind', '?')}] {r.get('name', '?')} ({edge})")
            if line not in seen:
                seen.add(line)
                print(line)

    if no_location:
        # Named rather than dropped: a row cs cannot place is a row cs cannot
        # show, and a quietly shorter answer is a quietly wrong one.
        print(f"tokensave: {no_location} matching node(s) had no file location "
              f"in the graph and are not listed below", file=sys.stderr)
    return 0 if seen else 1


def defs(project, repo, symbol):
    """Where a symbol is DEFINED, as a cross-repo alternative to the ctags index."""
    rows = _search(project, symbol, 100)
    if rows is None:
        return 4
    found = 0
    for r in rows:
        if r.get("name") != symbol:
            continue
        kind = r.get("kind", "?")
        if kind in NOT_A_DEFINITION:
            continue
        if not r.get("file"):
            continue
        print(f"{repo}/{r['file']}:{r.get('line', '?')}: [{kind}] {symbol}")
        found += 1
    return 0 if found else 1



# `tokensave tool` truncates its own stdout at 15000 characters -- it is built
# for MCP token budgets, and the cut lands mid-token, leaving INVALID JSON
# rather than a short answer. Measured: ~200 bytes per site, so this trips at
# roughly 75 sites and the reported 160-site case would hit it every time.
#
# Reads can be sacrificed to get an answer, writes cannot, and if the writes
# alone overflow there is nothing trustworthy to return. So on a cut the two
# halves are fetched SEPARATELY:
#
#   - the writes with `--writes-only true`, and checked complete against the
#     engine's own write total -- never assumed;
#   - a sample of the reads with `--limit N`, smaller until it fits.
#
# Separately, because what `--limit` does to the WRITES changed under us: it
# bounded read_sites only before tokensave 7.11, and caps both kinds from 7.11
# (write_returned/read_returned and `truncated` disclose it). Leaning on the
# old asymmetry is what printed 30 of 41 writes under "the write list is
# complete" (#44). Taking writes from their own query makes the answer the same
# on both sides of that change.
#
# The read TOTAL is not lost to the sampling: the counts precede the arrays, so
# the head of the first, cut, output still carries the graph's true totals
# (before 7.11 a --limit reply reports the capped number instead, so the head is
# the only place to read it). They are references, not sites -- the listing
# dedupes to file:line -- and are stated as such.
TRUNCATION_MARK = "[... truncated at"
READ_LIMITS = (30, 10, 1)


def _writes_complete(doc):
    """False when the engine SAYS it listed fewer writes than exist."""
    returned = doc.get("write_returned")
    total = doc.get("write_count")
    return not (isinstance(returned, int) and isinstance(total, int)
                and returned < total)


def _field_json(args):
    """(doc, None) | (None, "truncated") | (None, reason)."""
    out, err = _run(args)
    if out is None:
        return None, err
    try:
        doc = json.loads(out)
    except json.JSONDecodeError:
        # Only the engine's own truncation is worth retrying smaller. Any
        # other unparseable output is a different fault and is reported as
        # one rather than retried.
        return None, ("truncated" if TRUNCATION_MARK in out
                      else "returned no parseable JSON")
    if not isinstance(doc, dict):
        return None, "returned JSON that is not an object"
    return doc, None


def _field_doc(project, field):
    """(doc, applied_read_limit, head) -- or (None, reason, head).

    applied_read_limit is None when the full answer came back, and an int when
    reads are a sample. head holds the graph's true write_count/read_count
    whenever they were read, so a sample or a refusal can state them.
    """
    base = ["tokensave", "tool", "field_sites", "--field", field,
            "--project", project]
    out, err = _run(base)
    if out is None:
        return None, err, {}
    head = {}
    for key, pat in _NUM.items():
        m = pat.search(out)
        if m:
            head[key] = int(m.group(1))
    try:
        doc = json.loads(out)
    except json.JSONDecodeError:
        if TRUNCATION_MARK not in out:
            return None, "returned no parseable JSON", head
        doc = None
    if doc is not None:
        if not isinstance(doc, dict):
            return None, "returned JSON that is not an object", head
        # Uncut -- unless the engine's default per-kind limit (200) applied,
        # which 7.11+ says in write_returned/read_returned.
        if _writes_complete(doc):
            rr, rc = doc.get("read_returned"), doc.get("read_count")
            sampled = isinstance(rr, int) and isinstance(rc, int) and rr < rc
            return doc, (rr if sampled else None), head

    wdoc, why = _field_json(base + ["--writes-only", "true"])
    if wdoc is None:
        return None, why, head
    if not _writes_complete(wdoc):
        return None, "truncated", head
    for limit in READ_LIMITS:
        rdoc, why = _field_json(base + ["--limit", str(limit)])
        if rdoc is None:
            if why == "truncated":
                continue
            return None, why, head
        rdoc["write_sites"] = wdoc.get("write_sites") or []
        return rdoc, limit, head
    return None, "truncated", head


def _totals(head):
    if "write_count" in head and "read_count" in head:
        return (f" The graph's own totals: {head['write_count']} write and "
                f"{head['read_count']} read references.")
    return ""


def _qualifier_unmatched(doc):
    """The engine APPLIED a Type::field qualifier and it matched nothing.

    From 7.11 the qualifier narrows to sites whose receiver resolves to the
    type -- and a zero from that says nothing about who uses the field. Two
    measured ways to get it for a field that is plainly used: a Python
    attribute that is only assigned (`self._x = ...`) has no declaration for
    the type to own (DiscountEngine::_threshold in the fixture), and a C#
    field used without `this.` is not a `.field` reference the scan matches.
    """
    return (doc.get("qualifier") and doc.get("qualifier_applied")
            and not doc.get("write_count") and not doc.get("read_count"))


def _unattributed(doc):
    """How many sites a narrowed answer dropped because their receiver could
    not be typed (a call's return value, a container read). 7.11+ counts them
    and does not list them, so any above zero makes the answer a lower bound."""
    n = doc.get("unattributed_count") if doc.get("qualifier_applied") else 0
    return n if isinstance(n, int) and n > 0 else 0


def _say_lower_bound(doc, repo, n):
    bare = (doc.get("field") or "").split("::")[-1]
    print(f"tokensave: narrowed to '{doc.get('qualifier')}' in {repo}, {n} "
          f"site(s) whose receiver could not be typed are NOT included, so "
          f"these are a LOWER BOUND; the bare name '{bare}' gives the "
          f"unnarrowed answer", file=sys.stderr)


def field_sites(project, repo, field):
    """cs fields: read and write sites of a named field, as cs result lines.

    Emitted as `repo/path:line: [write] snippet` / `[read] snippet` -- the cs
    line shape, with the access kind where the node kind goes for the other
    modes. Nothing is capped here: the caller caps the two kinds SEPARATELY,
    which it can only do if it is handed both in full.

    Exit: 0 sites found, 1 no sites at all, 3 a qualifier that was not applied,
    4 the tool failed, 5 sites found but the engine truncated its own output so
    the reads are a sample, 6 too many sites to list at all (use the count
    mode -- the counts survive the truncation that destroys the arrays), 7 a
    qualifier the engine applied that matched no site, 8 sites found under an
    applied qualifier that dropped some it could not type (a lower bound). `1`
    is deliberately NOT treated as an answer by the caller -- see below.
    """
    doc, read_limit, head = _field_doc(project, field)
    if doc is None:
        # read_limit carries the reason when doc is None.
        if read_limit == "truncated":
            print("tokensave truncated its own output at 15000 CHARACTERS even "
                  "for the write list alone, so no complete list can be read "
                  "from this graph. The limit is bytes, not a number of sites: "
                  "a few dozen long lines are enough." + _totals(head),
                  file=sys.stderr)
            # 6, not 4: the graph answered fine and the SITE LIST is what does
            # not fit. Counting still works, because the counts precede the
            # arrays in the JSON and survive the cut -- so the caller has an
            # answer to offer rather than only a refusal.
            return 6
        print(f"tokensave field_sites failed: {read_limit}", file=sys.stderr)
        return 4

    # A `Type::field` query is PARSED into a qualifier and then, on tokensave
    # 7.9.0, not applied -- `qualifier_applied` came back false for every real
    # type probed, in C# and in Python. The results returned are the bare-name
    # results, so a caller who qualified because the bare name was ambiguous
    # gets the ambiguous answer back while believing it was narrowed.
    #
    # Measured, not assumed: `DiscountEngine::_threshold` (a real class) and
    # `NoSuchClass::_threshold` (a fabricated one) returned identical sites and
    # identical counts. A wrong type name is not an error here, so the
    # qualifier cannot even be used as a spell-check.
    #
    # So a qualified query whose qualifier was dropped is refused rather than
    # answered. Answering would return the broader question's result under the
    # narrower question's heading, and the caller asked to narrow precisely
    # because they did not want that. From 7.11 tokensave applies it, and this
    # path simply stops triggering.
    if doc.get("qualifier") and not doc.get("qualifier_applied"):
        print(f"tokensave: the qualifier '{doc['qualifier']}' was parsed but "
              f"NOT applied, so these would be the results for the bare field "
              f"name '{doc.get('field', field).split('::')[-1]}' — the broad "
              f"answer under a narrow heading", file=sys.stderr)
        return 3
    # Not printed here: this runs once per repo, and every repo without the
    # type answers the same way. The caller says it once, if no repo matched.
    if _qualifier_unmatched(doc):
        return 7

    found = 0
    # write before read: the two have different blast radii and the writes are
    # the smaller, more surprising set. Within a kind, source order.
    for kind in ("write", "read"):
        seen = set()
        for r in doc.get(f"{kind}_sites") or []:
            if not isinstance(r, dict) or not r.get("file"):
                continue
            # tokensave lists one entry per REFERENCE, so two mentions of the
            # field on one line arrive as two identical entries (measured:
            # read_count 3 over 2 distinct lines). In cs's line format those
            # would print as duplicate rows, which reads as a display bug --
            # and would inflate the hit count the caller weighs the answer by.
            key = (r["file"], r.get("line"), kind)
            if key in seen:
                continue
            seen.add(key)
            snippet = " ".join((r.get("snippet") or "").split())
            # The graph's `enclosing` is `file::file::Class::Member`; only the
            # last two carry information the path does not already give.
            enclosing = "::".join(
                [x for x in (r.get("enclosing") or "").split("::") if x][-2:])
            where = f" in {enclosing}" if enclosing else ""
            print(f"{repo}/{r['file']}:{r.get('line', '?')}: "
                  f"[{kind}]{where} {snippet}")
            found += 1
    if not found:
        return 1
    lost = _unattributed(doc)
    if lost:
        _say_lower_bound(doc, repo, lost)
    if read_limit is not None:
        # Exit 5, not 0: the caller has to mark this PARTIAL, and a warning on
        # stderr alone would be a fact the porcelain envelope does not carry.
        # "Complete" is said of the writes only because _field_doc checked it.
        total = head.get("read_count", doc.get("read_count"))
        print(f"tokensave: output was truncated by the engine, so the reads "
              f"were re-requested with --limit {read_limit}. The read sites "
              f"below are a SAMPLE of {total} read references (the graph's "
              f"true total); the write list is complete, checked against the "
              f"graph's write total.", file=sys.stderr)
        return 5
    return 8 if lost else 0



# The counts live in the JSON HEAD, before the site arrays -- `write_count` and
# `read_count` are emitted ahead of `write_sites`/`read_sites`. The 15000-char
# truncation therefore cuts the arrays and leaves the counts intact, which is
# what makes a summary mode possible at fleet scale where the full listing
# cannot be read at all.
#
# Read with a regex rather than json.loads precisely BECAUSE the document may be
# truncated: waiting for valid JSON is what made the fleet-wide question
# unanswerable. The scalars are matched individually so a cut anywhere after
# them costs nothing.
#
# Critically, this is called with NO --limit. Before 7.11, --limit rewrites
# read_count to the capped number, so counting through it would report the
# limit back as if it were a total -- the same silent cap the union graph has,
# and the reason the per-repo fan-out is used here instead. (7.11 reports true
# totals under --limit, but the arrays the site count is derived from are then
# capped, so the unlimited call is still the right one.)
_NUM = {k: re.compile(r'"%s"\s*:\s*(\d+)' % k) for k in ("write_count", "read_count")}
_QUAL = re.compile(r'"qualifier"\s*:\s*(?:"([^"]*)"|null)')
_QUAL_OK = re.compile(r'"qualifier_applied"\s*:\s*(true|false)')


def field_counts(project, repo, field):
    """cs fields --count: one summary line per repo.

    The headline numbers are SITES -- distinct file:line -- because that is what
    the listing mode reports and what a reviewer means by blast radius. Three
    references on one line are one place a human edits, not three.

    tokensave emits one entry per OCCURRENCE, so the raw write_count/read_count
    are reference counts and overstate the sites. Deduping needs the arrays, so
    it is possible only when the document actually parses; when the engine
    truncated its own output the arrays are incomplete and site counts are not
    derivable at all. That case reports references, says so in the line, and
    exits 5 so the caller can mark it.

    Exit: 0 counted as sites, 1 no sites at all, 3 a qualifier that was not
    applied, 4 the tool failed, 5 counted as REFERENCES because the output was
    truncated and sites could not be derived, 7 a qualifier the engine applied
    that matched no site, 8 counted under an applied qualifier that dropped
    sites it could not type (a lower bound).
    """
    out, err = _run(["tokensave", "tool", "field_sites", "--field", field,
                     "--project", project])
    if out is None:
        print(f"tokensave field_sites failed: {err}", file=sys.stderr)
        return 4

    qual = _QUAL.search(out)
    qual_ok = _QUAL_OK.search(out)
    if qual and qual.group(1) and qual_ok and qual_ok.group(1) == "false":
        print(f"tokensave: the qualifier '{qual.group(1)}' was parsed but NOT "
              f"applied, so these counts would be the bare field name's",
              file=sys.stderr)
        return 3

    # The reference counts, read from the JSON HEAD. They precede the site
    # arrays, so they survive the truncation that destroys them -- which is the
    # whole reason a count mode can answer where a listing cannot.
    refs = {}
    for key, pat in _NUM.items():
        m = pat.search(out)
        if not m:
            print(f"tokensave field_sites returned no {key}", file=sys.stderr)
            return 4
        refs[key] = int(m.group(1))

    if refs["write_count"] == 0 and refs["read_count"] == 0:
        # Zero output is short, so it parses; the applied-qualifier case has
        # its own refusal, for the reason _qualifier_unmatched gives.
        try:
            doc = json.loads(out)
        except json.JSONDecodeError:
            return 1
        if isinstance(doc, dict) and _qualifier_unmatched(doc):
            return 7
        return 1

    # Sites, when the arrays are all there. Same dedupe key as the listing path,
    # so the two modes report the same quantity -- they disagreed before, and
    # both claimed to be complete.
    try:
        doc = json.loads(out)
    except json.JSONDecodeError:
        print(f"{repo}: writes {refs['write_count']}, reads {refs['read_count']}"
              f" (references, not sites — output truncated)")
        return 5
    if not isinstance(doc, dict):
        return 4

    sites = {}
    for kind in ("write", "read"):
        seen = set()
        for r in doc.get(f"{kind}_sites") or []:
            if isinstance(r, dict) and r.get("file"):
                seen.add((r["file"], r.get("line")))
        sites[kind] = len(seen)

    line = f"{repo}: writes {sites['write']}, reads {sites['read']}"
    # The reference counts are kept alongside rather than dropped: they are
    # strictly more information, and printing them ONLY when they differ makes
    # the difference self-evident instead of visible only to someone who runs
    # both modes.
    if (sites["write"] != refs["write_count"]
            or sites["read"] != refs["read_count"]):
        line += (f" (refs: {refs['write_count']} write, "
                 f"{refs['read_count']} read)")
    print(line)
    lost = _unattributed(doc)
    if lost:
        _say_lower_bound(doc, repo, lost)
        return 8
    return 0


def main():
    if len(sys.argv) < 5:
        print(__doc__, file=sys.stderr)
        return 4
    mode, project, repo, symbol = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

    if mode == "def":
        return defs(project, repo, symbol)
    if mode == "fields":
        return field_sites(project, repo, symbol)
    if mode == "field-counts":
        return field_counts(project, repo, symbol)
    if mode in ("callers", "callees", "impact"):
        return graph_edges(project, repo, symbol, mode)
    if mode != "impls":
        print(f"unknown mode: {mode}", file=sys.stderr)
        return 4

    # Step 1: resolve the name to a graph node id. Through the exact-name probe
    # rather than the ranked search this used to call with its default limit of
    # ten -- on a repo where ten near-misses outrank the interface, that reported
    # "not a type node in this graph" about a type that is right there.
    rows = _exact_nodes(project, symbol)
    if rows is None:
        return 4

    node = next(
        (r for r in rows if r.get("kind") in TYPE_KINDS),
        None,
    )
    if not node or not node.get("id"):
        # NOT an empty answer. The graph was never asked the question, so
        # printing nothing here would be a negative nobody established.
        print(f"tokensave: '{symbol}' is not a type node in this graph",
              file=sys.stderr)
        return 3

    # Step 2: the hierarchy, by id.
    out, err = _run(["tokensave", "tool", "type_hierarchy",
                     "--node-id", node["id"], "--project", project])
    if out is None:
        print(f"tokensave type_hierarchy failed: {err}", file=sys.stderr)
        return 4

    found = 0
    for line in out.splitlines():
        m = ROW.match(line.strip())
        if not m:
            continue
        edge, name, kind, path, lineno = m.groups()
        # `implements` and `extends` both, which is the whole point: C# has one
        # syntax for both relations, so an extractor that resolves some names
        # and defaults the rest files interface implementations under either.
        # The edge kind is printed so the reader can see which it was.
        print(f"{repo}/{path}:{lineno}: [{kind}] {name} ({edge})")
        found += 1

    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
