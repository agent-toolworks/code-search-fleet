#!/usr/bin/env python3
"""The two sides of a seam: who publishes and who consumes an event, who defines
and who calls an HTTP route.

`cs uses` answers "where does this string appear, outside comments". For a
seam that is half the question. The publisher and the consumer of an event both
name it; the definition of a route and its callers both spell its path; a
`GET /charges` and a `POST /charges` share every character a text search sees.
Scored against a fleet with known answers, 12 of 14 remaining failures were
exactly this (#122): a correct list of files, with the two sides mixed.

This classifies each hit by the CODE AROUND IT, not by its text:

  event   the call the name sits in, walking outward through enclosing calls
          and across lines: publish/send/emit/outbox -> publishes;
          consume/subscribe/listen/bind/handler map/queue -> consumes;
          a schema or constant -> declares. Every spelling of the name is
          searched (stock.reserved, STOCK_RESERVED, StockReserved,
          stockReserved), and a constant holding it is followed to its uses
          in the same file.
  route   the DEFINITION, with its path assembled from the pieces frameworks
          split it into (Spring class @RequestMapping + method mapping, .NET
          MapGroup or [Route] + [HttpX], FastAPI APIRouter(prefix=) + decorator,
          Express app/router, route tables with method/path keys); and the
          CALLERS: string literals whose path matches segment by segment, a
          parameter matching any one segment, with the HTTP method read near
          the call. Same path, other method; a path matching only the route's
          tail; and a call whose method is not visible are listed apart.
          A literal matching only the tail, passed to a function defined in
          the same repo that joins a fixed base path in front of that argument
          ("/api/admin" + path, `/api${path}`, f"/api{path}"), is read with
          that base: a caller when the two make the route, named as another
          route when they do not. Two definitions that disagree: nothing is
          assumed.

WHAT THIS DELIBERATELY WILL NOT DO
----------------------------------
* Resolve a base URL. A caller of `/orders/{id}/refund` may be calling the
  gateway or the service; a path match says which ROUTE SHAPE is called, not
  which deployment. The answer says so. Only a fixed base PATH joined inside a
  helper of the same repo is followed, never a host or a value set at runtime.
* Follow a constant into another file, or a name built at runtime. Both are
  named as limits, not papered over.
* Guess. A hit whose surroundings decide nothing is a `mention`, counted on
  neither side.

Usage:  seams.py <view-root> event <name>              < hits (repo/path:line:text)
        seams.py <view-root> route <METHOD> <path>     < hits
Prints `repo/path:line: [side] text` lines on stdout and the summary on stderr.
Exit: 0 something was classified on a side, 1 nothing was, 2 bad arguments.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filter_code import comment_lines  # noqa: E402

CODE_EXTS = {
    ".py", ".java", ".kt", ".kts", ".scala", ".groovy", ".go", ".rb", ".rs", ".cs",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".php", ".swift", ".c", ".h",
    ".cc", ".cpp", ".hpp", ".ex", ".exs", ".sh", ".bash",
}
DOC_EXTS = {".md", ".markdown", ".rst", ".txt", ".adoc"}
DATA_EXTS = {".json", ".yaml", ".yml", ".toml", ".xml", ".properties", ".env", ".ini"}
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

_cache = {}


def lines_of(root, path):
    if path not in _cache:
        try:
            with open(os.path.join(root, path), encoding="utf-8", errors="replace") as fh:
                _cache[path] = fh.read().splitlines()
        except OSError:
            _cache[path] = []
    return _cache[path]


def ext_of(path):
    base = os.path.basename(path).lower()
    return "." + base.rsplit(".", 1)[-1] if "." in base else ""


def file_kind(path):
    e = ext_of(path)
    if e in CODE_EXTS or os.path.basename(path) in ("smoke",):
        return "code"
    if e in DOC_EXTS:
        return "doc"
    if e in DATA_EXTS:
        return "data"
    return "other"


def is_comment(root, path, lineno):
    marked = comment_lines(os.path.join(root, path))
    return bool(marked) and lineno in marked


def split_hit(line):
    m = re.match(r"^(.*?):(\d+):(.*)$", line)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else None


# ---------------------------------------------------------------- enclosing calls

_IDENT_BEFORE = re.compile(r"([@A-Za-z_$][\w$.@?!]*)\s*(?:<[^<>()]*>)?\s*$")
_ASSIGNED = re.compile(r"(?:\b(?:val|var|let|const|final|static|private|public|readonly)\s+)*"
                       r"([A-Za-z_$][\w$]*)\s*(?::[^=]{0,60})?=(?!=)\s*$")


def enclosing(lines, idx, col, back=8):
    """Callee names of the calls (and names of the containers) a position is inside,
    innermost first. Scans back across lines; skips string contents roughly."""
    start = max(0, idx - back)
    chunk = "\n".join(lines[start:idx] + [lines[idx][:col]])
    out, depth = [], {"(": 0, "[": 0, "{": 0}
    close = {")": "(", "]": "[", "}": "{"}
    i, quote = len(chunk) - 1, None
    while i >= 0:
        ch = chunk[i]
        if quote:
            if ch == quote and (i == 0 or chunk[i - 1] != "\\"):
                quote = None
            i -= 1
            continue
        if ch in "\"'`":
            # walking backwards: a quote opens a string we are now inside of
            quote = ch
            i -= 1
            continue
        if ch in close:
            depth[close[ch]] += 1
        elif ch in depth:
            if depth[ch] > 0:
                depth[ch] -= 1
            else:
                before = chunk[:i]
                if ch == "(":
                    m = _IDENT_BEFORE.search(before)
                    out.append(("call", m.group(1) if m else ""))
                else:
                    m = _ASSIGNED.search(before)
                    if m:
                        out.append(("container", m.group(1)))
                    else:
                        m = _IDENT_BEFORE.search(before)
                        out.append(("container", m.group(1) if m else ""))
        i -= 1
    return out


PUB_RE = re.compile(r"(publish|emit|\bsend|produce|outbox|enqueue|dispatch|fire|convertandsend|basic_publish|basicpublish)", re.I)
CON_RE = re.compile(r"(consum|subscrib|listen|handler|bind|queue|on_?message|@?\w*listener)", re.I)


def last_part(name):
    return re.split(r"[.@?!]", name)[-1] if name else ""


def decide(name):
    """'publishes' / 'consumes' / None for one callee or container name."""
    if not name:
        return None
    tail = last_part(name)
    for cand in (tail, name):
        if PUB_RE.search(cand) and not CON_RE.search(cand):
            return "publishes"
        if CON_RE.search(cand):
            return "consumes"
    return None


# ---------------------------------------------------------------- events

def spellings(name):
    words = [w for w in re.split(r"[._\-\s]+", name) if w]
    out = [name]
    if len(words) > 1:
        out += ["_".join(w.upper() for w in words),
                "".join(w[:1].upper() + w[1:] for w in words),
                words[0].lower() + "".join(w[:1].upper() + w[1:] for w in words[1:])]
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


_CONST_DEF = re.compile(r"""(?:\b(?:const|val|var|let|final|static|readonly|public|private|internal|export)\s+)*"""
                        r"""(?:string\s+|String\s+)?([A-Za-z_$][\w$]*)\s*(?::\s*\w+\s*)?=\s*["'`]([^"'`]+)["'`]""")


def classify_event(root, name, hits):
    spell = spellings(name)
    rx = re.compile(r"(?<![\w$])(" + "|".join(re.escape(s) for s in sorted(spell, key=len, reverse=True)) + r")(?![\w$])")
    rows, aliases = [], {}
    seen = set()

    def classify_at(path, lineno, text, how="", at=None):
        key = (path, lineno)
        if key in seen:
            return
        seen.add(key)
        kind = file_kind(path)
        if kind == "doc" or (kind == "code" and is_comment(root, path, lineno)):
            rows.append((path, lineno, "doc", "", text))
            return
        if kind == "data":
            low = text.lower()
            if '"const"' in low or '"title"' in low or "$id" in low:
                rows.append((path, lineno, "declares", "schema", text))
            elif re.search(r"queue|bind|route|topic", text, re.I) or re.search(r'":\s*"', text):
                rows.append((path, lineno, "wiring", "config", text))
            else:
                rows.append((path, lineno, "mention", "", text))
            return
        if kind != "code":
            rows.append((path, lineno, "mention", "", text))
            return
        stripped = text.strip()
        if re.match(r"^(import|from\s+\S+\s+import|using|#include|require\()", stripped):
            rows.append((path, lineno, "import", "", text))
            return
        lines = lines_of(root, path)
        idx = lineno - 1
        if not (0 <= idx < len(lines)):
            rows.append((path, lineno, "mention", "", text))
            return
        # A spelling followed by `(` is a function or constructor with the event's
        # name (`t.subscriptionPaymentFailed(...)`, `new OrderPaid(...)`), not the
        # event itself; the first spelling that is not a call is the one that counts.
        m = None
        for cand in rx.finditer(lines[idx]):
            if not re.match(r"\s*\(", lines[idx][cand.end():]):
                m = cand
                break
        if m is None and at is None:
            rows.append((path, lineno, "mention", "a function or constructor of that name", text))
            return
        col = at if at is not None else m.start()
        cd = _CONST_DEF.search(lines[idx])
        if cd and name in cd.group(2) and cd.group(1) not in spell:
            aliases.setdefault(path, set()).add(cd.group(1))
            rows.append((path, lineno, "declares", "constant %s" % cd.group(1), text))
            return
        side, via = None, ""
        for what, callee in enclosing(lines, idx, col):
            side = decide(callee)
            if side:
                via = "%s %s" % ("in" if what == "call" else "in", callee + ("(" if what == "call" else ""))
                break
        if not side:
            am = re.match(r"\s*(?:(?:val|var|let|const|final)\s+)?([A-Za-z_$][\w$]*)\s*=", lines[idx])
            if am and decide(am.group(1)):
                side, via = decide(am.group(1)), "assigned to %s" % am.group(1)
        if not side and re.search(r"\[\s*[\w.$]*" + re.escape(m.group(1) if m else name) + r"\s*\]\s*:", lines[idx]):
            side, via = "consumes", "a handler map key"
        rows.append((path, lineno, side or "mention", via + how, text))

    for raw in hits:
        parsed = split_hit(raw)
        if parsed:
            classify_at(*parsed)
    # One hop: a constant holding the name, followed to its uses in the same file.
    for path, names in aliases.items():
        lines = lines_of(root, path)
        # `$NAME` / `${NAME}` inside a string template is a use too, so only a word
        # character may not precede the name.
        arx = re.compile(r"(?<![\w])(" + "|".join(re.escape(n) for n in names) + r")(?![\w$])")
        for i, line in enumerate(lines):
            m = arx.search(line)
            if not m or _CONST_DEF.search(line) and _CONST_DEF.search(line).group(1) in names:
                continue
            before = len(rows)
            classify_at(path, i + 1, line, how=" (via %s)" % m.group(1), at=m.start())
            if len(rows) > before and rows[-1][2] == "mention":
                rows.pop()   # an alias use that decides nothing is noise, not a mention of the event
    return rows, spell, sorted({a for v in aliases.values() for a in v})


# ---------------------------------------------------------------- routes

PARAM_SEG = re.compile(r"^(\{[^}]*\}|:[A-Za-z_]\w*(\([^)]*\))?|<[^>]*>|\*|%[sd]|\$\{[^}]*\}|\$[A-Za-z_]\w*|\{\})$")


def norm_segments(path):
    """'/a/{id}/b?x=1' -> ['a', '*', 'b'], or None for something that is not a path."""
    path = re.sub(r"^[a-z][a-z0-9+.-]*://[^/]*", "", path.strip())
    path = re.sub(r"\$\{[^}]*\}|\$[A-Za-z_]\w*", "{}", path)          # interpolations
    path = re.sub(r'"\s*\+\s*[\w.()]+\s*\+\s*"', "{}", path)            # "a/" + x + "/b"
    path = path.split("?")[0].split("#")[0]
    if not path.startswith("/") and "/" not in path:
        return [path] if path and re.fullmatch(r"[\w.\-{}:<>*%$]+", path) else ([] if path == "" else None)
    segs = [s for s in path.strip("/").split("/")]
    out = []
    for s in segs:
        if s == "":
            continue
        out.append("*" if PARAM_SEG.match(s) or "{" in s or s.startswith(":") else s)
    return out


def seg_match(want, got):
    """A route's parameter matches any one segment; a caller's parameter matches only
    a route parameter (a call to `/lots/{x}` is not evidence of `/lots/allocate`)."""
    if len(want) != len(got):
        return False
    return all(w == g or w == "*" for w, g in zip(want, got))


def tail_match(want, got):
    """got matches the END of want, shorter, and agrees on at least one literal segment."""
    if not got or len(got) >= len(want):
        return False
    tail = want[-len(got):]
    if not any(w != "*" and w == g for w, g in zip(tail, got)):
        return False
    return seg_match(tail, got)


def join_path(*parts):
    out = "/".join(p.strip("/") for p in parts if p and p.strip("/"))
    return "/" + out


def class_prefix_spring(lines, idx):
    """The @RequestMapping("...") on the class this line belongs to, or ''."""
    for j in range(idx, -1, -1):
        if re.search(r"\bclass\b", lines[j]) and not lines[j].strip().startswith(("//", "*")):
            for k in range(j, max(-1, j - 6), -1):
                m = re.search(r'@RequestMapping\(\s*(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']*)["\']', lines[k])
                if m:
                    return m.group(1)
            return ""
    return ""


def class_prefix_aspnet(lines, idx):
    for j in range(idx, -1, -1):
        m = re.search(r"\bclass\s+(\w+)", lines[j])
        if m:
            stem = re.sub(r"Controller$", "", m.group(1)).lower()
            for k in range(j, max(-1, j - 8), -1):
                r = re.search(r'\[Route\(\s*"([^"]*)"\s*\)\]', lines[k])
                if r:
                    return r.group(1).replace("[controller]", stem)
            return ""
    return ""


def group_prefix(lines, var, depth=0):
    """A .NET MapGroup / FastAPI APIRouter prefix for a variable, nested groups included."""
    if depth > 5:
        return ""
    for line in lines:
        m = re.search(r"(?:var|let|const)?\s*\b%s\s*=\s*(\w+)\.MapGroup\(\s*\"([^\"]*)\"" % re.escape(var), line)
        if m:
            return join_path(group_prefix(lines, m.group(1), depth + 1), m.group(2))
        m = re.search(r"\b%s\s*=\s*APIRouter\([^)]*prefix\s*=\s*[\"']([^\"']*)[\"']" % re.escape(var), line)
        if m:
            return m.group(1)
    return ""


def definitions_in_line(lines, idx):
    """[(METHOD, full path, how)] that this line DEFINES."""
    line = lines[idx]
    out = []
    for m in re.finditer(r'@(Get|Post|Put|Delete|Patch)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']*)["\']', line):
        pre = class_prefix_spring(lines, idx)
        out.append((m.group(1).upper(), join_path(pre, m.group(2)), "Spring" + (" + class @RequestMapping(\"%s\")" % pre if pre else "")))
    m = re.search(r'@RequestMapping\(([^)]*)\)', line)
    if m and "method" in m.group(1):
        p = re.search(r'["\']([^"\']*)["\']', m.group(1))
        meth = re.search(r"RequestMethod\.(\w+)", m.group(1))
        if p and meth:
            pre = class_prefix_spring(lines, idx)
            out.append((meth.group(1).upper(), join_path(pre, p.group(1)), "Spring"))
    for m in re.finditer(r'(\w+)\.Map(Get|Post|Put|Delete|Patch)\(\s*"([^"]*)"', line):
        pre = group_prefix(lines, m.group(1)) if m.group(1) not in ("app", "builder") else ""
        out.append((m.group(2).upper(), join_path(pre, m.group(3)), ".NET minimal API" + (" + MapGroup(\"%s\")" % pre if pre else "")))
    for m in re.finditer(r'\[Http(Get|Post|Put|Delete|Patch)(?:\(\s*"([^"]*)"\s*\))?\]', line):
        pre = class_prefix_aspnet(lines, idx)
        out.append((m.group(1).upper(), join_path(pre, m.group(2) or ""), "ASP.NET [Http%s]" % m.group(1) + (" + [Route(\"%s\")]" % pre if pre else "")))
    for m in re.finditer(r'@(\w+)\.(get|post|put|delete|patch)\(\s*["\']([^"\']*)["\']', line):
        pre = group_prefix(lines, m.group(1))
        out.append((m.group(2).upper(), join_path(pre, m.group(3)), "decorator @%s.%s" % (m.group(1), m.group(2))))
    m = re.search(r'@(\w+)\.route\(\s*["\']([^"\']*)["\'](.*)', line)
    if m:
        meths = re.findall(r'["\'](GET|POST|PUT|PATCH|DELETE)["\']', m.group(3)) or ["GET"]
        for meth in meths:
            out.append((meth, m.group(2), "Flask @route"))
    m = re.search(r'\bmethod\s*:\s*["\'](GET|POST|PUT|PATCH|DELETE)["\']\s*,\s*path\s*:\s*["\'`]([^"\'`]*)["\'`]', line)
    if m:
        out.append((m.group(1), m.group(2), "route table (method/path)"))
    for m in re.finditer(r'(?:url\.path|self\.path|req\.url|request\.path)\s*===?\s*["\']([^"\']*)["\']', line):
        out.append(("GET", m.group(1), "path comparison"))
    return out


def express_definition(lines, idx, path_text):
    """app.get('/x', handler) in an Express-style file is a definition, not a call."""
    line = lines[idx]
    m = re.search(r'\b(app|router|api|server)\.(get|post|put|delete|patch)\(\s*["\'`]', line)
    if not m:
        return None
    text = "\n".join(lines)
    if re.search(r"express|fastify|koa|hono", text):
        return m.group(2).upper()
    return None


_METHOD_NEAR = [
    re.compile(r'\bmethod\s*[:=]\s*["\'](GET|POST|PUT|PATCH|DELETE)["\']', re.I),
    re.compile(r'\.(get|post|put|patch|delete)\(\)'),                              # RestClient http.post()
    re.compile(r'\.(GET|POST|PUT|PATCH|DELETE)\('),                                # HttpRequest.newBuilder().POST(
    re.compile(r'\b(?:requests|httpx|axios|client|session|http|api)\.(get|post|put|patch|delete)\(', re.I),
    re.compile(r'\b(Get|Post|Put|Patch|Delete)(?:Async|FromJsonAsync|AsJsonAsync)\('),
    re.compile(r'["\'](GET|POST|PUT|PATCH|DELETE)["\']'),
]


def method_near(lines, idx, span=(2, 3)):
    lo, hi = max(0, idx - span[0]), min(len(lines), idx + span[1] + 1)
    # nearest first: the hit line, then outward
    order = [idx] + [j for d in range(1, max(span) + 1) for j in (idx - d, idx + d) if lo <= j < hi]
    for j in order:
        for rx in _METHOD_NEAR:
            m = rx.search(lines[j])
            if m:
                return m.group(1).upper()
        if re.search(r"\bfetch\w*\s*\(", lines[j]) and j == idx:
            fetch_default = True
            # fetch with no method in its options is a GET; look at the next lines first
            for k in range(idx, min(len(lines), idx + 4)):
                mm = _METHOD_NEAR[0].search(lines[k])
                if mm:
                    return mm.group(1).upper()
            if fetch_default:
                return "GET"
    return None


_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|`([^`]*)`')


def path_literals(line):
    """Path-like string literals on a line, joined across `"a" + x + "b"`."""
    joined = re.sub(r'"\s*\+\s*[\w.()]+\s*\+\s*"', "{}", line)
    joined = re.sub(r'(\w+_URL|baseUrl|base_url|BASE)\s*\+\s*"', '"', joined)
    out = []
    for m in _STRING.finditer(joined):
        s = next(g for g in m.groups() if g is not None)
        s = re.sub(r"\$\{[^}]*\}", "{}", s)
        if "/" in s and not re.search(r"\s", s.strip()) and len(s) < 300:
            out.append((s, m.start()))
    return out


# ---------------------------------------------------------------- base paths added by a helper

_SKIP_DIRS = {"node_modules", "vendor", "dist", "build", "target", "bin", "obj", ".git", "__pycache__", ".venv"}
_repo_files = {}
_helpers = {}


def call_position(line, pos):
    """(callee, argument index) of the call whose arguments hold position `pos` on this
    line, or None. Strings and nested brackets are skipped."""
    depth, quote, commas = 0, None, 0
    i = pos - 1
    while i >= 0:
        ch = line[i]
        if quote:
            if ch == quote and (i == 0 or line[i - 1] != "\\"):
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch in ")]}":
            depth += 1
        elif ch in "([{":
            if depth:
                depth -= 1
            elif ch == "(":
                m = re.search(r"([A-Za-z_$][\w$]*)\s*(?:<[^<>()]*>)?\s*$", line[:i])
                return (m.group(1), commas) if m else None
            else:
                return None
        elif ch == "," and not depth:
            commas += 1
        i -= 1
    return None


def _code_files(root, repo):
    if repo not in _repo_files:
        out = []
        for dirpath, dirs, files in os.walk(os.path.join(root, repo)):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), root)
                if file_kind(rel) == "code":
                    out.append(rel)
        _repo_files[repo] = sorted(out)
    return _repo_files[repo]


def _params(text):
    """Parameter names of the first parenthesised list in text."""
    start = text.find("(")
    if start < 0:
        return []
    depth, end = 0, None
    for i in range(start, len(text)):
        if text[i] in "([{<":
            depth += 1
        elif text[i] in ")]}>":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return []
    inner, parts, cur, d = text[start + 1:end], [], "", 0
    for ch in inner:
        if ch in "([{<":
            d += 1
        elif ch in ")]}>":
            d -= 1
        if ch == "," and d == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    names = []
    for part in parts:
        m = re.match(r"\s*(?:\.\.\.|\*{1,2}|val\s+|var\s+)?([A-Za-z_$][\w$]*)", part)
        if m:
            names.append(m.group(1))
    if names and names[0] in ("self", "cls"):
        names = names[1:]
    return names


def _base_in_body(body, param):
    """The string a function joins in front of its parameter: "/api" + path,
    `/api${path}`, f"/api{path}", "/api$path"."""
    p = re.escape(param)
    for rx in (r'["\']([^"\'\n]*)["\']\s*\+\s*%s\b' % p,
               r'`([^`]*?)\$\{\s*%s\s*\}' % p,
               r'\bf["\']([^"\'\n]*?)\{\s*%s\s*\}' % p,
               r'"([^"\n]*?)\$\{?%s\b' % p):
        m = re.search(rx, body)
        if m:
            base = re.sub(r"^(?:\$\{[^}]*\}|\{[^}]*\}|\$[A-Za-z_]\w*)+", "", m.group(1))
            base = re.sub(r"^[a-z][a-z0-9+.-]*://[^/]*", "", base)
            if base.startswith("/") and not re.search(r"\s", base):
                return base.rstrip("/")
    return None


def helper_base(root, path, name, arg):
    """(base path, where) when the function `name`, defined in this repo, joins a
    fixed base path in front of the argument at index `arg`; else None. Its
    definition in the same file wins; otherwise every definition in the repo
    must agree, or nothing is assumed."""
    key = (path.split("/", 1)[0], path, name, arg)
    if key in _helpers:
        return _helpers[key]
    rx = re.compile(r"(?:\bfunction\s*\*?\s*%(n)s\s*(?:<[^>]*>)?\s*\(|\b(?:const|let|var)\s+%(n)s\s*(?::[^=]+)?=\s*"
                    r"(?:async\s*)?(?:function\b[^(]*)?(?=\()|\bdef\s+%(n)s\s*\(|\bfun\s+%(n)s\s*\()" % {"n": re.escape(name)})
    found = {}
    files = [path] + [f for f in _code_files(root, key[0]) if f != path]
    for f in files:
        lines = lines_of(root, f)
        for i, line in enumerate(lines):
            m = rx.search(line)
            if not m:
                continue
            head = "\n".join(lines[i:i + 4])[m.start():]
            params = _params(head)
            if arg >= len(params):
                continue
            base = _base_in_body("\n".join(lines[i:i + 15]), params[arg])
            if base is not None:
                found.setdefault(f, []).append((base, "%s:%d" % (f, i + 1)))
        if f == path and found:
            break
    answer = None
    if path in found:
        answer = found[path][0]
    elif found:
        bases = {b for entries in found.values() for b, _ in entries}
        if len(bases) == 1:
            answer = next(iter(found.values()))[0]
    _helpers[key] = answer
    return answer


def classify_route(root, method, path, hits):
    want = norm_segments(path)
    rows, aliases, seen = [], {}, set()
    for raw in hits:
        parsed = split_hit(raw)
        if not parsed:
            continue
        p, lineno, text = parsed
        if (p, lineno) in seen:
            continue
        seen.add((p, lineno))
        kind = file_kind(p)
        if kind == "doc" or (kind == "code" and is_comment(root, p, lineno)):
            for s, _ in path_literals(text) or [(text, 0)]:
                pass
            if any(seg_match(want, norm_segments(t) or []) for t in re.findall(r"/[\w/{}:.\-<>]+", text)):
                rows.append((p, lineno, "doc", "", text))
            continue
        lines = lines_of(root, p)
        idx = lineno - 1
        if kind != "code" or not (0 <= idx < len(lines)):
            continue
        defs = definitions_in_line(lines, idx)
        hit_def = False
        for meth, full, how in defs:
            segs = norm_segments(full) or []
            if seg_match(want, segs):
                hit_def = True
                side = "defines" if meth == method else "defines-other-method"
                rows.append((p, lineno, side, "%s %s via %s" % (meth, full, how), text))
        em = express_definition(lines, idx, path)
        if em and not hit_def:
            for s, _ in path_literals(lines[idx]):
                if seg_match(want, norm_segments(s) or []):
                    hit_def = True
                    rows.append((p, lineno, "defines" if em == method else "defines-other-method",
                                 "%s %s via Express" % (em, s), text))
        # a line that defines a route is not a caller -- except a route table, which
        # both defines its own path and CALLS its target
        if (defs or em) and not re.search(r"\btarget\s*:", lines[idx]):
            continue
        for s, pos in path_literals(lines[idx]):
            segs = norm_segments(s)
            if segs is None:
                continue
            exact, tail = seg_match(want, segs), tail_match(want, segs)
            if hit_def:
                tail = False   # this line defines the asked route; its target is another route
            if not (exact or tail):
                continue
            if hit_def and re.search(r'\bpath\s*:\s*["\'`]' + re.escape(s), lines[idx]):
                continue   # the table's own path, already a definition
            cd = _CONST_DEF.search(lines[idx])
            if cd and cd.group(2) == s:
                aliases.setdefault(p, {})[cd.group(1)] = (lineno, exact)
                continue
            via = ""
            if tail and not exact:
                # A helper may add the base: admin("/orders/1/refund") -> "/api/admin" + path.
                cp = call_position(lines[idx], pos)
                hb = helper_base(root, p, cp[0], cp[1]) if cp else None
                if hb:
                    base, where = hb
                    if seg_match(want, norm_segments(join_path(base, s)) or []):
                        exact = True
                        via = " via %s(), which adds %s (%s)" % (cp[0], base, where)
                    else:
                        via = " (%s() adds %s, so this is %s, not the route asked for)" % (
                            cp[0], base, join_path(base, s))
            meth = method_near(lines, idx)
            side = ("calls" if meth == method else "calls-other-method" if meth else "calls-method-unseen") \
                if exact else "calls-tail"
            rows.append((p, lineno, side, "%s %s%s" % (meth or "?", s, via), text))
            break
    # A definition whose own line holds no searched segment -- `@GetMapping("/{sku}")`
    # under `@RequestMapping("/coffees")` -- is found by reading every code file
    # that had a hit, not just the hit lines.
    for p in sorted({r.split(":", 1)[0] for r in hits if split_hit(r)}):
        if file_kind(p) != "code":
            continue
        lines = lines_of(root, p)
        for i in range(len(lines)):
            if (p, i + 1) in seen or is_comment(root, p, i + 1):
                continue
            for meth, full, how in definitions_in_line(lines, i):
                if seg_match(want, norm_segments(full) or []):
                    seen.add((p, i + 1))
                    rows.append((p, i + 1, "defines" if meth == method else "defines-other-method",
                                 "%s %s via %s" % (meth, full, how), lines[i]))
    # a constant holding the path: its uses in the same file carry the method
    for p, names in aliases.items():
        lines = lines_of(root, p)
        for const, (decl_line, exact) in names.items():
            used = False
            for i, line in enumerate(lines):
                if i + 1 == decl_line or not re.search(r"(?<![\w])%s(?![\w$])" % re.escape(const), line):
                    continue
                used = True
                meth = method_near(lines, i)
                side = ("calls" if meth == method else "calls-other-method" if meth else "calls-method-unseen") \
                    if exact else "calls-tail"
                rows.append((p, i + 1, side, "%s via %s (line %d)" % (meth or "?", const, decl_line), line))
            if not used:
                rows.append((p, decl_line, "calls-method-unseen", "constant %s, used nowhere in this file" % const,
                             lines[decl_line - 1] if decl_line - 1 < len(lines) else ""))
    return rows, want


# ---------------------------------------------------------------- output

ORDER = {
    "event": ["publishes", "consumes", "declares", "wiring", "import", "mention", "doc"],
    "route": ["defines", "calls", "calls-method-unseen", "calls-tail", "calls-other-method",
              "defines-other-method", "doc"],
}


def main():
    a = sys.argv[1:]
    if len(a) < 3 or a[1] not in ("event", "route") or (a[1] == "route" and len(a) < 4):
        print(__doc__, file=sys.stderr)
        return 2
    root, mode = a[0], a[1]
    hits = [h for h in sys.stdin.read().splitlines() if h.strip()]
    e = sys.stderr
    if mode == "event":
        name = a[2]
        rows, spell, aliases = classify_event(root, name, hits)
    else:
        method, path = a[2].upper(), a[3]
        if method not in METHODS:
            print("route: the method is one of %s" % " ".join(METHODS), file=e)
            return 2
        rows, want = classify_route(root, method, path, hits)
    rows.sort(key=lambda r: (ORDER[mode].index(r[2]) if r[2] in ORDER[mode] else 99, r[0], r[1]))
    for p, l, side, via, text in rows:
        print("%s:%d: [%s] %s%s" % (p, l, side, (via + "   ") if via else "", text.strip()))

    def repos(side):
        return sorted({r[0].split("/")[0] for r in rows if r[2] == side})

    def n(side):
        return sum(1 for r in rows if r[2] == side)

    if mode == "event":
        print("spellings searched: %s%s" % (", ".join(spell),
              ("; constants followed in their file: " + ", ".join(aliases)) if aliases else ""), file=e)
        print("publishes: %d site(s) in %s" % (n("publishes"), ", ".join(repos("publishes")) or "no repo"), file=e)
        print("consumes:  %d site(s) in %s" % (n("consumes"), ", ".join(repos("consumes")) or "no repo"), file=e)
        if n("consumes") and not n("publishes"):
            print("! nothing in view publishes %s: %d consumer site(s) wait for an event no code here sends. "
                  "Check cs gaps before calling it dead: the publisher may live in a repo that is not cloned."
                  % (name, n("consumes")), file=e)
        if n("publishes") and not n("consumes"):
            print("! %s is published and nothing in view consumes it" % name, file=e)
        if n("mention"):
            print("  %d mention(s) whose surroundings decide neither side are listed as [mention], not guessed"
                  % n("mention"), file=e)
        found = n("publishes") + n("consumes") + n("declares") + n("wiring")
    else:
        print("defines: %d site(s) in %s" % (n("defines"), ", ".join(repos("defines")) or "no repo"), file=e)
        print("calls:   %d site(s) in %s%s" % (n("calls"), ", ".join(repos("calls")) or "no repo",
              ("; %d more whose method is not visible at the call" % n("calls-method-unseen")) if n("calls-method-unseen") else ""), file=e)
        if n("calls-other-method"):
            print("  %d call(s) to the same path with ANOTHER method, not counted: %s"
                  % (n("calls-other-method"), ", ".join(repos("calls-other-method"))), file=e)
        helped = sorted({re.search(r" via (\w+)\(\), which adds", r[3]).group(1) for r in rows
                         if r[2] == "calls" and ", which adds " in r[3]})
        if helped:
            print("  %d call(s) found through a helper that adds the base path: %s"
                  % (sum(1 for r in rows if r[2] == "calls" and ", which adds " in r[3]),
                     ", ".join(h + "()" for h in helped)), file=e)
        if n("calls-tail"):
            print("  %d literal(s) match only the END of the path (a base URL may add the rest): listed as [calls-tail]"
                  % n("calls-tail"), file=e)
        if not n("defines"):
            print("! no definition of %s %s found in view: frameworks read are Spring, .NET minimal API "
                  "and [Route]/[HttpX], FastAPI/Flask, Express, route tables, path comparisons" % (method, path), file=e)
        elif not n("calls") and not n("calls-method-unseen") and not n("calls-tail"):
            print("! defined, and no caller found in view. Check cs gaps before calling it dead: a caller may "
                  "build the path at runtime, or live in a repo that is not cloned.", file=e)
        print("  a call matches a route SHAPE; its base URL is not resolved, so it may reach another service "
              "with the same path", file=e)
        found = n("defines") + n("calls") + n("calls-method-unseen") + n("calls-tail")
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
