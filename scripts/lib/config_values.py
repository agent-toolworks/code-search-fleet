#!/usr/bin/env python3
"""Split a config key's sites into SET-sites and READ-sites, and compare them.

`cs fields` split a field's sites into writes and reads, and that split turned
out to be the whole value: writes observe a changed default, reads break on a
rename. A config key has exactly the same two sides -- except that they sit on
opposite sides of a REPO BOUNDARY, and nothing separated them.

`cs uses <KEY>` returns both sides in one undifferentiated list, which is the
shape that hides the defect. The interesting failure is not a missing
reference; it is a VALUE MISMATCH across the seam. The motivating finding: a
cross-repo pair, both halves unusually well verified in isolation -- the
producer proved its chart rendered identically, the consumer proved its values
parsed identically -- and the defect sat exactly between them, because the
producer gated on specific tokens and the consumer passed a group-level name
that was never one of them. Neither side's tests could see it, and nothing in
either diff could.

The asymmetry is the argument for splitting by file kind: measured across a
43-repo fleet, a Spring profile selector was in 10 manifest files and 4 code
files, a feature-flag prefix in 1 and 26, a log-level key in 15 and 58. The two
sides live in different file types, so one text sweep mixes deployment
manifests with branching code and the counts alone say nothing about whether
they agree.

WHAT THIS DELIBERATELY WILL NOT DO
----------------------------------
* "Accepts" is only sometimes derivable. A switch/when over string literals is
  readable; a value passed to a framework, split on a comma, or compared after
  normalisation is not. Undeterminable is reported as undeterminable, and the
  mismatch line fires ONLY when the read side is genuinely enumerable -- a
  guessed enumeration would turn this into a generator of false findings about
  values that are perfectly fine.
* A set-site's literal is often templated (`{{ .Values.x }}`, `${VAR}`). It is
  reported as templated rather than resolved, because naming WHICH sites are
  opaque is itself the useful part: those are the ones a human must check.
* The sides are told apart by FILE KIND, not by dataflow. A code file that sets
  the key at runtime reads as a read-site here, and that is said in the answer
  rather than papered over.

Usage:  config_values.py <fleet-root> <KEY>   < hits on stdin (repo/path:line:text)
Exit:   0 something was classified, 1 nothing was.
"""
import os
import re
import sys

# The set side: files whose job is to STATE a value. A match in one of these is
# a value being supplied, not a value being consumed.
SET_EXTS = {
    ".yaml", ".yml", ".env", ".properties", ".ini", ".cfg", ".conf", ".toml",
    ".tfvars", ".tf", ".hcl", ".plist",
}
SET_NAMES = {"dockerfile", "procfile", "makefile", ".env", ".envrc"}

# The read side: files that BRANCH on a value.
READ_EXTS = {
    ".py", ".java", ".kt", ".kts", ".scala", ".groovy", ".go", ".rb", ".rs",
    ".cs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".php", ".swift",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".m", ".ex", ".exs", ".erl", ".sh",
    ".bash", ".zsh", ".sql", ".xml",
}

# Neither side. Reported so the count is honest -- a README naming a key is not
# a set-site and not a consumer -- and kept out of both tallies.
DOC_EXTS = {".md", ".markdown", ".rst", ".txt", ".adoc"}

# A value that cannot be known statically. Naming these is the point: they are
# exactly the sites a human has to open.
TEMPLATE_RE = re.compile(r"\{\{|\$\{|\$\(|%\(|<%")

# `KEY: value`, `KEY = value`, `KEY=value`, `"KEY": "value"`, `ENV KEY value`.
def assigned_value(key, text):
    """The literal this line supplies for `key`, or None if it supplies none."""
    k = re.escape(key)
    for pat in (
        r'["\']?' + k + r'["\']?\s*[:=]\s*(.+)$',       # yaml / json / env / toml
        r'\bENV\s+' + k + r'\s+(.+)$',                  # Dockerfile ENV K V
        r'\b(?:export|set)\s+' + k + r'\s*=\s*(.+)$',   # shell
    ):
        m = re.search(pat, text)
        if not m:
            continue
        v = m.group(1).strip()
        # Trailing comment, but only when it is not inside the quotes.
        if v[:1] not in "\"'":
            v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
        v = v.rstrip(",")
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        return v if v else None
    return None


# Tokens a read site compares against, taken ONLY from shapes where the literal
# is unambiguously being tested against something. `"x"` appearing anywhere near
# the key is not evidence; `== "x"` is.
COMPARE_RES = [
    re.compile(r'[=!]==?\s*["\']([^"\']+)["\']'),
    re.compile(r'["\']([^"\']+)["\']\s*[=!]==?'),
    re.compile(r'\.equals(?:IgnoreCase)?\(\s*["\']([^"\']+)["\']'),
    re.compile(r'\bin\s*[\(\[\{]([^\)\]\}]*)[\)\]\}]'),
]
CASE_RES = [
    re.compile(r'^\s*(?:case|when)\s+["\']([^"\']+)["\']'),
    re.compile(r'^\s*["\']([^"\']+)["\']\s*(?:->|=>|:)'),
]
SWITCH_RE = re.compile(r'\b(?:switch|when|match)\b')


# `in (...)` is a membership test only where its result is USED as a boolean.
# `for name in ("KEY", "KEY_USERNAME"):` is a loop, and reading it as a test
# made three key NAMES the accepted VALUES of a URL key -- so every real URL in
# dev, stg and prd was reported as accepted by no read site. A comprehension
# (`[x for x in (...)]`) is the same loop in another spelling.
_LOOP_BEFORE_IN = re.compile(r'\bfor\b')
_BOOLEAN_BEFORE_IN = re.compile(
    r'\b(?:if|elif|while|and|or|not|assert|return|unless)\b'
    r'|[^=!<>]=(?!=)|\?|&&|\|\||!\s*$|^\s*$'   # `!in`; a Kotlin `in setOf(..) ->` label
)


def compare_tokens(text):
    out = []
    for rx in COMPARE_RES[:3]:
        out += rx.findall(text)
    for m in COMPARE_RES[3].finditer(text):
        before = text[:m.start()]
        if _LOOP_BEFORE_IN.search(before) or not _BOOLEAN_BEFORE_IN.search(before):
            continue
        out += re.findall(r'["\']([^"\']+)["\']', m.group(1))
    return out


# A test file's literal is evidence of what a TEST expects -- usually a fixture
# value -- not of what the production reader accepts. Counting
# `assert settings.URL == "https://fake-host/release"` as accepted turned every
# deployed URL into a "SET but not accepted" finding, the kind of false alarm
# someone acts on. They are listed apart, never mixed into the accepted set.
_TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testing", "testdata",
              "fixtures", "e2e", "it"}
_TEST_FILE_RE = re.compile(
    r'(?:^test_.*\.py$|_test\.(?:py|go|rb|exs?)$|^conftest\.py$'
    r'|(?:Test|Tests|Spec|IT)\.(?:java|kt|kts|scala|groovy|cs|swift)$'
    r'|\.(?:test|spec)\.[cm]?[jt]sx?$|_spec\.rb$)'
)


def is_test_path(path):
    parts = path.split("/")
    # parts[0] is the repo; a repo NAMED "tests" is not a test directory.
    if any(p.lower() in _TEST_DIRS for p in parts[1:-1]):
        return True
    return bool(_TEST_FILE_RE.search(parts[-1]))


def names_the_key(key, tok):
    """A token that is the key's own NAME, or a sibling key's (`KEY_USERNAME`),
    is an identifier, not a value the key can hold."""
    if tok == key:
        return True
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*', tok):
        return False
    return tok.startswith(key + "_") or tok.endswith("_" + key)


def switch_tokens(lines, idx):
    """Labels of a switch/when/match whose SUBJECT line mentions the key.

    Attribution is the whole risk here, so the subject line must be the one the
    key was found on: a switch elsewhere in the file is over something else, and
    borrowing its labels is how this would start inventing accepted values.
    """
    if not SWITCH_RE.search(lines[idx]):
        return []
    toks, base = [], len(lines[idx]) - len(lines[idx].lstrip())
    for line in lines[idx + 1: idx + 41]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        hit = False
        for rx in CASE_RES:
            m = rx.match(line)
            if m:
                toks.append(m.group(1)); hit = True; break
        if hit:
            continue
        # Out of the block: back to the subject's own indentation on a line that
        # is not a label.
        if indent <= base and line.strip() not in ("{", "}", "):", ")"):
            break
    return toks


def kind_of(path):
    base = os.path.basename(path).lower()
    stem = base.rsplit(".", 1)[0]
    ext = "." + base.rsplit(".", 1)[-1] if "." in base else ""
    if base in SET_NAMES or stem in SET_NAMES:
        return "set"
    if ext in SET_EXTS:
        return "set"
    if ext in READ_EXTS:
        return "read"
    if ext in DOC_EXTS:
        return "doc"
    return "other"


def split_hit(line):
    """`repo/path:line:text` -> (path, lineno, text), splitting at the FIRST
    `:digits:` -- a matched line's TEXT can carry `:NN:` and a path almost
    never does. The same rule cs's json_results learned the hard way."""
    m = re.match(r"^(.*?):(\d+):(.*)$", line)
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3)


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 1
    root, key = sys.argv[1], sys.argv[2]

    sets, reads, docs, others = [], [], [], []
    accepted, accept_sites = [], []
    test_tokens, test_sites, key_names = set(), [], set()
    file_cache = {}

    for raw in sys.stdin.read().splitlines():
        if not raw.strip():
            continue
        parsed = split_hit(raw)
        if not parsed:
            continue
        path, lineno, text = parsed
        kind = kind_of(path)

        if kind == "set":
            val = assigned_value(key, text)
            if val is None:
                label = "(names the key, supplies no literal here)"
            elif TEMPLATE_RE.search(val):
                label = "(templated) " + val
            else:
                label = '"%s"' % val
            sets.append((path, lineno, label, val, text.strip()))
        elif kind == "read":
            toks = compare_tokens(text)
            if not toks:
                if path not in file_cache:
                    try:
                        with open(os.path.join(root, path), "r",
                                  encoding="utf-8", errors="replace") as fh:
                            file_cache[path] = fh.read().splitlines()
                    except OSError:
                        file_cache[path] = []
                lines = file_cache[path]
                if 0 <= lineno - 1 < len(lines):
                    toks = switch_tokens(lines, lineno - 1)
            note = ""
            names = sorted({t for t in toks if names_the_key(key, t)})
            toks = [t for t in toks if t not in names]
            if names:
                key_names.update(names)
            if toks and is_test_path(path):
                test_tokens.update(toks)
                test_sites.append("%s:%d" % (path, lineno))
                note = "test compares against (not counted as accepted): " \
                    + " | ".join(sorted(set(toks)))
            elif toks:
                accepted += toks
                accept_sites.append("%s:%d" % (path, lineno))
                note = "compares against: " + " | ".join(sorted(set(toks)))
            reads.append((path, lineno, note, text.strip()))
        elif kind == "doc":
            docs.append((path, lineno, text.strip()))
        else:
            others.append((path, lineno, text.strip()))

    if not (sets or reads or docs or others):
        return 1

    # The accepted set has to be known before the set-sites are printed, because
    # the finding belongs ON the offending line. Over a machine interface the
    # narrative below goes to stderr and is not in the result stream at all, so
    # a mismatch that lived only there would be invisible to exactly the caller
    # least able to notice it.
    acc_pre = set(accepted)
    for path, lineno, label, v, text in sets:
        mark = ""
        if acc_pre and v and not TEMPLATE_RE.search(v):
            parts = [t.strip() for t in re.split(r"[,\s]+", v) if t.strip()]
            if not all(t in acc_pre for t in parts):
                mark = "  <- NOT accepted by any read site"
        print("%s:%d: [set] %s   %s%s" % (path, lineno, label, text, mark))
    for path, lineno, note, text in reads:
        print("%s:%d: [read] %s%s" % (path, lineno, (note + "   ") if note else "", text))
    for path, lineno, text in docs:
        print("%s:%d: [doc] %s" % (path, lineno, text))
    for path, lineno, text in others:
        print("%s:%d: [other] %s" % (path, lineno, text))

    # ---- the summary, on stderr like every other cs diagnostic -------------
    literals = sorted({v for _p, _l, _lab, v, _t in sets
                       if v and not TEMPLATE_RE.search(v)})
    templated = [( p, l) for p, l, _lab, v, _t in sets
                 if v and TEMPLATE_RE.search(v)]
    e = sys.stderr
    print("set sites: %d in %d repo(s), %d distinct literal value(s)%s"
          % (len(sets), len({p.split("/")[0] for p, _l, _a, _v, _t in sets}),
             len(literals),
             (", %d templated" % len(templated)) if templated else ""), file=e)
    if literals:
        print("  values SET: " + "  ".join('"%s"' % v for v in literals), file=e)
    if templated:
        print("  templated, so not resolvable here — open these by hand: "
              + " ".join("%s:%d" % (p, l) for p, l in templated[:10]), file=e)

    acc = sorted(set(accepted))
    print("read sites: %d in %d repo(s), %s"
          % (len(reads), len({p.split("/")[0] for p, _l, _n, _t in reads}),
             ("accepts %d token(s): %s" % (len(acc), " | ".join(acc))) if acc
             else "accepts: UNDETERMINABLE"), file=e)
    if not acc and reads:
        print("  no read site compares the value against string literals this "
              "can enumerate — a value passed to a framework, split on a "
              "separator, or normalised first is not readable here, and "
              "guessing an enumeration would invent findings", file=e)
    if test_tokens:
        print("  test files compare against %d token(s), NOT counted as accepted "
              "(a fixture value is what a test expects, not what production "
              "accepts): %s   at %s"
              % (len(test_tokens), " | ".join(sorted(test_tokens)),
                 " ".join(test_sites[:5])), file=e)
    if key_names:
        print("  dropped %d token(s) that name a key rather than a value: %s"
              % (len(key_names), " | ".join(sorted(key_names))), file=e)

    # THE finding. Everything above it is context. Fires only when the read side
    # is genuinely enumerable, and never on a templated set-site.
    rc = 0
    if acc and literals:
        unmatched = []
        for p, l, _lab, v, _t in sets:
            if not v or TEMPLATE_RE.search(v):
                continue
            # A comma or space list is checked token by token: a consumer that
            # passes "alpha,beta" satisfies a producer accepting both.
            parts = [t.strip() for t in re.split(r"[,\s]+", v) if t.strip()]
            if all(t in acc for t in parts):
                continue
            unmatched.append((p, l, v))
        if unmatched:
            print("! %d value(s) are SET but not accepted by any read site "
                  "this could enumerate:" % len(unmatched), file=e)
            for p, l, v in unmatched[:10]:
                print('    %s:%d   "%s"' % (p, l, v), file=e)
            print("  the read side accepts: " + " | ".join(acc), file=e)
            rc = 0
    if docs or others:
        print("not counted on either side: %d doc mention(s), %d file(s) of a "
              "kind this does not classify — a README naming a key neither "
              "supplies it nor consumes it" % (len(docs), len(others)), file=e)
    return rc


if __name__ == "__main__":
    sys.exit(main())
