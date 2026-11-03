#!/usr/bin/env python3
"""Drop matches that sit inside a comment or docstring.

Reads `path:line: text` on stdin and writes back only the lines whose match is
in executable code. This is the one thing no single engine did well: ripgrep
counts a docstring mentioning an endpoint as a caller, and a symbol graph
cannot see the string literal that is the real call site.

Line-leading markers are not enough -- a docstring's middle line carries no
marker at all -- so this tracks block state by scanning each file once.

A file whose language is not in the tables below cannot be filtered, and the
honest thing to do with it is say so: `--report-unsupported` writes the
extensions it had to pass through unfiltered to stderr, so `cs uses` can
qualify its "prose filtered" claim instead of overstating it.

Usage: filter_code.py [--invert] [--root DIR] [--report-unsupported]
"""
import sys
import pathlib
import argparse
from functools import lru_cache

# Three families cover almost everything in use: `//`, `#`, and `/* */`. An
# extension absent from these tables gets an EMPTY comment set, which means
# every one of its lines counts as code -- `cs uses` silently degrades to
# `cs seam` for that language while still reporting "prose filtered". That is a
# provenance claim the filter did not honour, and it is invisible to anyone
# whose fleet is written in the languages already covered. So the tables are
# deliberately broad, and whatever is still missing is reported rather than
# quietly passed through.
_SLASH = ("//",)
_HASH = ("#",)
_C_BLOCK = [("/*", "*/")]
_XML_BLOCK = [("<!--", "-->")]

LINE_COMMENT = {
    # hash family
    ".py": _HASH, ".rb": _HASH, ".sh": _HASH, ".bash": _HASH, ".zsh": _HASH,
    ".fish": _HASH, ".yml": _HASH, ".yaml": _HASH, ".toml": _HASH,
    ".tf": _HASH, ".tfvars": _HASH, ".hcl": _HASH, ".nix": _HASH,
    ".pl": _HASH, ".pm": _HASH, ".r": _HASH, ".jl": _HASH, ".cr": _HASH,
    ".ex": _HASH, ".exs": _HASH, ".cmake": _HASH, ".mk": _HASH,
    ".rake": _HASH, ".gemspec": _HASH, ".ps1": _HASH, ".psm1": _HASH,
    ".properties": _HASH, ".env": _HASH, ".ini": _HASH + (";",),
    # slash family
    ".cs": _SLASH, ".kt": _SLASH, ".kts": _SLASH, ".java": _SLASH,
    ".ts": _SLASH, ".tsx": _SLASH, ".js": _SLASH, ".jsx": _SLASH,
    ".mjs": _SLASH, ".cjs": _SLASH, ".mts": _SLASH, ".cts": _SLASH,
    ".go": _SLASH, ".rs": _SLASH, ".swift": _SLASH, ".scala": _SLASH,
    ".sc": _SLASH, ".groovy": _SLASH, ".gradle": _SLASH, ".dart": _SLASH,
    ".c": _SLASH, ".h": _SLASH, ".cc": _SLASH, ".cpp": _SLASH, ".cxx": _SLASH,
    ".hpp": _SLASH, ".hh": _SLASH, ".hxx": _SLASH, ".ino": _SLASH,
    ".m": _SLASH, ".mm": _SLASH, ".proto": _SLASH, ".thrift": _SLASH,
    ".vue": _SLASH, ".svelte": _SLASH, ".zig": _SLASH, ".sol": _SLASH,
    ".php": _SLASH + _HASH, ".fs": _SLASH, ".fsx": _SLASH,
    # everything else
    ".sql": ("--",), ".lua": ("--",), ".hs": ("--",), ".elm": ("--",),
    ".ada": ("--",), ".clj": (";",), ".cljs": (";",), ".cljc": (";",),
    ".edn": (";",), ".el": (";",), ".lisp": (";",), ".scm": (";",),
    ".vb": ("'",), ".bas": ("'",), ".erl": ("%",), ".hrl": ("%",),
    ".tex": ("%",), ".f90": ("!",), ".f95": ("!",),
}
BLOCK = {
    ".cs": _C_BLOCK, ".kt": _C_BLOCK, ".kts": _C_BLOCK, ".java": _C_BLOCK,
    ".ts": _C_BLOCK, ".tsx": _C_BLOCK, ".js": _C_BLOCK, ".jsx": _C_BLOCK,
    ".mjs": _C_BLOCK, ".cjs": _C_BLOCK, ".mts": _C_BLOCK, ".cts": _C_BLOCK,
    ".go": _C_BLOCK, ".rs": _C_BLOCK, ".swift": _C_BLOCK, ".scala": _C_BLOCK,
    ".sc": _C_BLOCK, ".groovy": _C_BLOCK, ".gradle": _C_BLOCK, ".dart": _C_BLOCK,
    ".c": _C_BLOCK, ".h": _C_BLOCK, ".cc": _C_BLOCK, ".cpp": _C_BLOCK,
    ".cxx": _C_BLOCK, ".hpp": _C_BLOCK, ".hh": _C_BLOCK, ".hxx": _C_BLOCK,
    ".ino": _C_BLOCK, ".m": _C_BLOCK, ".mm": _C_BLOCK, ".php": _C_BLOCK,
    ".proto": _C_BLOCK, ".thrift": _C_BLOCK, ".vue": _C_BLOCK,
    ".svelte": _C_BLOCK, ".zig": _C_BLOCK, ".sol": _C_BLOCK,
    ".css": _C_BLOCK, ".scss": _C_BLOCK, ".less": _C_BLOCK,
    ".sql": _C_BLOCK, ".lua": [("--[[", "]]")],
    ".hs": [("{-", "-}")], ".elm": [("{-", "-}")],
    ".fs": [("(*", "*)")], ".fsx": [("(*", "*)")],
    ".py": [('"""', '"""'), ("'''", "'''")],
    ".html": _XML_BLOCK, ".htm": _XML_BLOCK, ".xml": _XML_BLOCK,
    ".xhtml": _XML_BLOCK, ".xsd": _XML_BLOCK, ".md": _XML_BLOCK,
    ".cshtml": _XML_BLOCK, ".razor": _XML_BLOCK,
}

# Files with no extension whose *name* identifies the language. Common enough
# in a fleet (a Dockerfile mentioning a config key, a Makefile calling a route)
# that treating them as unsupported would be a needless gap.
BY_NAME = {
    "Dockerfile": (_HASH, []), "Containerfile": (_HASH, []),
    "Makefile": (_HASH, []), "GNUmakefile": (_HASH, []),
    "Rakefile": (_HASH, []), "Gemfile": (_HASH, []), "Brewfile": (_HASH, []),
    "Vagrantfile": (_HASH, []), "Procfile": (_HASH, []),
    "BUILD": (_HASH, []), "WORKSPACE": (_HASH, []), "Justfile": (_HASH, []),
    "Jenkinsfile": (_SLASH, _C_BLOCK),
}

# Extensions that are data, not code, and have no comment syntax at all. They
# are "supported" in the sense that nothing needs filtering -- distinguishing
# them from genuinely unknown ones keeps the unsupported report meaningful.
NO_COMMENT_SYNTAX = {".json", ".txt", ".csv", ".tsv", ".lock", ".log", ".rst"}


def markers_for(path):
    """(line_markers, block_pairs) for a path, or None when unsupported."""
    ext = path.suffix.lower()
    if ext in LINE_COMMENT or ext in BLOCK:
        return LINE_COMMENT.get(ext, ()), BLOCK.get(ext, [])
    if path.name in BY_NAME:
        return BY_NAME[path.name]
    if ext in NO_COMMENT_SYNTAX:
        return (), []
    return None


def _block_opener(raw, start, line_markers):
    """Where a block comment opens on this line, or -1.

    Only an opener in code counts: not one inside a string ("/api/*", `/x/*`),
    and not one after a line-comment marker (`// routes under /api/*`). Matching
    the opener anywhere on the line made such a line open a block comment that
    ran to the next `*/` in the file, so every call site in between was counted
    as a comment and `cs uses` answered "no code uses it".

    A quote that never closes on the line (a Rust lifetime, an apostrophe in a
    string the scan misreads) hides any opener after it, so the line counts as
    code: the safe direction, since a call site missed is worse than a comment
    counted. Block markers made of quotes (Python's triple quotes) are matched
    without string tracking, as before.
    """
    quotes = "" if start[0] in "\"'" else "\"'`"
    i, n, q = 0, len(raw), None
    while i < n:
        ch = raw[i]
        if q:
            if ch == "\\":
                i += 2
                continue
            if ch == q:
                q = None
            i += 1
            continue
        if ch in quotes:
            q = ch
            i += 1
            continue
        if raw.startswith(start, i):
            return i
        if any(m and raw.startswith(m, i) for m in line_markers):
            return -1
        i += 1
    return -1


@lru_cache(maxsize=512)
def comment_lines(path_str):
    """1-based line numbers that are comment or docstring.

    Returns None -- distinct from an empty set -- when the language is unknown,
    so the caller can tell "nothing to filter here" from "could not filter".
    """
    path = pathlib.Path(path_str)
    markers = markers_for(path)
    if markers is None:
        return None
    line_markers, blocks = markers
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None

    out = set()
    open_marker = None
    for idx, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()

        if open_marker is not None:
            out.add(idx)
            if open_marker[1] in raw:
                open_marker = None
            continue

        for start, end in blocks:
            pos = _block_opener(raw, start, line_markers)
            if pos == -1:
                continue
            out.add(idx)
            rest = raw[pos + len(start):]
            if end not in rest:
                open_marker = (start, end)
            break
        else:
            for marker in line_markers:
                if line.startswith(marker):
                    out.add(idx)
                    break
    return frozenset(out)


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--invert", action="store_true",
                    help="keep only the comment matches instead")
    ap.add_argument("--root", default=".")
    ap.add_argument("--report-unsupported", action="store_true",
                    help="write unfilterable extensions to stderr, one per line")
    ap.add_argument("-h", "--help", action="store_true")
    args = ap.parse_args()
    if args.help:
        print(__doc__)
        return 0

    root = pathlib.Path(args.root)
    unsupported = {}
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        parts = line.split(":", 2)
        if len(parts) < 3 or not parts[1].isdigit():
            print(line)          # not a match line; pass through untouched
            continue
        rel, num = parts[0], int(parts[1])
        marked = comment_lines(str(root / rel))
        if marked is None:
            # Unfilterable. Kept on the code side rather than dropped: a real
            # call site missed is worse than a comment counted, and the caller
            # is told the claim is qualified.
            p = pathlib.Path(rel)
            key = p.suffix.lower() or p.name
            unsupported[key] = unsupported.get(key, 0) + 1
            if not args.invert:
                print(line)
            continue
        if (num in marked) == args.invert:
            print(line)

    if args.report_unsupported and unsupported:
        for ext, n in sorted(unsupported.items(), key=lambda kv: -kv[1]):
            print("{}\t{}".format(ext, n), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
