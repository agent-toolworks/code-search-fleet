#!/usr/bin/env python3
"""Read CHANGELOG.md by version, for `cs changes` and `scripts/release-notes`.

The changelog is the one record of EVERY change -- the ticketed ones and the
small fixes nobody filed -- and it ships with the plugin. But an agent never
opens it, and a release page used to be written by hand, so whatever was left
out of either did not reach the people and agents using cs. Both now read it
from here.

Usage:
  changelog.py <CHANGELOG.md> since <X.Y.Z>    sections newer than X.Y.Z
  changelog.py <CHANGELOG.md> last <N>         the N newest released sections
  changelog.py <CHANGELOG.md> body <X.Y.Z>     one version's entries, no heading

Exit 1 when the version asked for is not in the changelog.
"""
import re
import sys

HEAD = re.compile(r"^## (\d+(?:\.\d+)*)\b.*$")


def sections(text):
    """[(version, heading, body)] in file order, newest first; Unreleased skipped."""
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            if cur:
                out.append(cur)
            m = HEAD.match(line)
            cur = (m.group(1), line, []) if m else None
            continue
        if cur:
            cur[2].append(line)
    if cur:
        out.append(cur)
    return [(v, h, "\n".join(b).strip("\n")) for v, h, b in out]


def key(v):
    return tuple(int(p) for p in v.split("."))


def main():
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    path, mode, arg = sys.argv[1:]
    try:
        secs = sections(open(path, encoding="utf-8").read())
    except OSError as exc:
        print("changelog: cannot read {}: {}".format(path, exc), file=sys.stderr)
        return 1
    if mode == "body":
        for v, _, body in secs:
            if v == arg:
                print(body)
                return 0
        print("changelog: no entry for {}".format(arg), file=sys.stderr)
        return 1
    if mode == "since":
        if not re.fullmatch(r"\d+(\.\d+)*", arg):
            print("changelog: not a version: {}".format(arg), file=sys.stderr)
            return 1
        pick = [s for s in secs if key(s[0]) > key(arg)]
    elif mode == "last":
        pick = secs[:max(1, int(arg))]
    else:
        print(__doc__, file=sys.stderr)
        return 2
    for _, heading, body in pick:
        print(heading)
        print()
        print(body)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
