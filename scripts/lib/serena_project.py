#!/usr/bin/env python3
"""Read or create a repo's Serena project file (.serena/project.yml).

Usage: serena_project.py languages <repo-dir>
       serena_project.py ignored <repo-dir>
       serena_project.py create <repo-dir> <language-server>... [--ignore <path>]...

`languages` prints the language servers the file enables, one per line, and
`ignored` its ignored_paths; both exit 1 when there is no project file.
`create` writes one and exits 1, writing nothing, when the file already exists.

Serena creates this file itself on its first run in a repo, and when it is not
interactive it enables only the language with the most files (#95): in a Gradle
repo with more Java than Kotlin, no Kotlin server ever started and every Kotlin
symbol came back "could not locate". cs writes the file instead when the
question is about a language the repo's majority is not. Serena fills in every
field left out here with its default.

No YAML library: the two keys read here are plain lists, written either as a
block (`- java`) or flow (`["java"]`), and cs should not need PyYAML to refuse.
"""
import os
import re
import sys

KEYS = ("language_servers", "languages", "language")


def yml_path(repo):
    return os.path.join(repo, ".serena", "project.yml")


def read_list(text, keys):
    """The values of the first of `keys` present at the top level, or None."""
    lines = text.splitlines()
    for key in keys:
        for i, line in enumerate(lines):
            m = re.match(r"^%s:\s*(.*?)\s*(#.*)?$" % re.escape(key), line)
            if not m:
                continue
            rest = m.group(1)
            if rest.startswith("["):
                return [v.strip().strip("'\"") for v in rest.strip("[]").split(",")
                        if v.strip().strip("'\"")]
            if rest:                       # `language: java`, the oldest form
                return [rest.strip("'\"")]
            out = []
            for item in lines[i + 1:]:
                if not item.strip() or item.lstrip().startswith("#"):
                    continue
                im = re.match(r"^\s*-\s*(.+?)\s*(#.*)?$", item)
                if not im:
                    break
                out.append(im.group(1).strip("'\""))
            return out
    return None


def main(argv):
    if len(argv) < 3 or argv[1] not in ("languages", "ignored", "create"):
        print(__doc__, file=sys.stderr)
        return 2
    cmd, repo = argv[1], argv[2]
    path = yml_path(repo)
    if cmd in ("languages", "ignored"):
        try:
            with open(path, errors="replace") as f:
                text = f.read()
        except OSError:
            return 1
        found = read_list(text, KEYS if cmd == "languages" else ("ignored_paths",))
        for v in found or []:
            print(v)
        return 0

    langs, ignores, rest = [], [], argv[3:]
    while rest:
        if rest[0] == "--ignore" and len(rest) > 1:
            ignores.append(rest[1]); rest = rest[2:]
        else:
            langs.append(rest[0]); rest = rest[1:]
    if not langs:
        print("serena_project.py create: no language server named", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return 1
    q = lambda vs: "[" + ", ".join('"%s"' % v for v in vs) + "]"
    with os.fdopen(fd, "w") as f:
        f.write("# Written by cs (code-search-fleet), not by Serena: Serena enables only\n"
                "# the language with the most files when it writes this itself, and a\n"
                "# question about another language in the repo found nothing. Every field\n"
                "# left out takes Serena's default. Add a language server here to enable it.\n")
        f.write('project_name: "%s"\n' % os.path.basename(os.path.realpath(repo)))
        f.write("language_servers: %s\n" % q(langs))
        f.write("ignored_paths: %s\n" % q(ignores))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
