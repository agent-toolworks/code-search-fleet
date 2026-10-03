#!/usr/bin/env python3
"""Normalize Serena's JSON into the `repo/path:line: text` stream cs emits.

Every other cs subcommand emits that one line format -- it is what keeps
results compact, what makes them clickable, and what scripts/score-seams
parses. `cs impls` and `cs refs` used to print Serena's raw JSON instead, so
the two most expensive subcommands were also the two whose output could not be
scored, could not be capped, and did not match what SKILL.md promises. A single
`cs refs` on a widely used interface is a multi-kilobyte blob of
`content_around_reference` snippets, which is precisely the thing the result
cap exists to keep out of an agent's context.

Two shapes are handled, because Serena returns a different one per tool:

  find_implementations     [{name_path, kind, relative_path, body_location}]
  find_referencing_symbols {relative_path: {kind: [{name_path, ...}]}}

Anything that does not parse is passed through untouched: an error message or a
future shape should reach the caller, not be swallowed by the formatter.

Usage: serena_fmt.py <repo-name>
"""
import json
import re
import sys

# Serena marks the referencing line with `>` in its context snippet:
#     ...   6:// meant to exercise.
#     >   7:public class SqlInventoryStore : IInventoryStore
# That line number is the reference; body_location is where the *enclosing*
# symbol starts, which is a different and less useful thing to report.
#
# BOTH are 0-based -- the LSP's convention -- while every other engine's
# `repo/path:line:` is 1-based (an editor's, grep's). Printed as they came,
# every address landed one line short: on the `{` above a class, on a blank
# line above an annotation, and a join with another engine's (file, line)
# never matched (#76). In the snippet above the class is on line 8.
REF_LINE = re.compile(r"^\s*>\s*(\d+):(.*)$", re.MULTILINE)


def one_based(n):
    return n + 1 if isinstance(n, int) else n


def start_line(entry):
    loc = entry.get("body_location") or {}
    return one_based(loc.get("start_line", "?"))


def short_name(name_path):
    """The symbol path without its namespace: Acme.Inventory.Web/Foo/Bar -> Foo/Bar."""
    head, sep, rest = name_path.partition("/")
    return rest if sep and "." in head else name_path


def reference_site(entry):
    """(line, text) of the actual reference, falling back to the symbol start."""
    snippet = entry.get("content_around_reference") or ""
    m = REF_LINE.search(snippet)
    if m:
        return int(m.group(1)) + 1, m.group(2).strip()
    return start_line(entry), entry.get("name_path", "")


def emit(repo, path, line, kind, text):
    prefix = "{}/{}".format(repo, path) if repo else path
    print("{}:{}: [{}] {}".format(prefix, line, kind, text))


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = sys.stdin.read()
    stripped = raw.strip()
    if not stripped:
        return 0
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        sys.stdout.write(raw)      # an error line, or a shape we do not know
        return 0

    if isinstance(data, list):
        # find_implementations
        for entry in data:
            if not isinstance(entry, dict):
                continue
            emit(repo, entry.get("relative_path", "?"), start_line(entry),
                 entry.get("kind", "?"), entry.get("name_path", ""))
        return 0

    if isinstance(data, dict):
        # find_referencing_symbols
        rows = []
        for path, kinds in data.items():
            if not isinstance(kinds, dict):
                continue
            for kind, entries in kinds.items():
                for entry in entries or []:
                    if not isinstance(entry, dict):
                        continue
                    line, text = reference_site(entry)
                    # The kind Serena groups by is the ENCLOSING symbol's, not
                    # the reference's: a call inside a method read `[Class]`.
                    # Naming the enclosing symbol says where the site is (#76).
                    where = short_name(entry.get("name_path", ""))
                    tag = "in {} {}".format(kind, where) if where else kind
                    rows.append((path, int(line) if str(line).isdigit() else 0,
                                 tag, text))
        # By file then line, so a reader scans a file's references in order.
        for path, line, kind, text in sorted(rows, key=lambda r: (r[0], r[1])):
            emit(repo, path, line, kind, text)
        return 0

    sys.stdout.write(raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
