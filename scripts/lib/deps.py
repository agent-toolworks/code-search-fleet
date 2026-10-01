#!/usr/bin/env python3
"""Map package coordinates to the fleet repos that publish and consume them.

The gap this fills: "which of these two same-named classes does checkout
actually use" is not a code-search question at all. The answer lives in build
manifests -- a Gradle coordinate, an npm name, a NuGet id -- and no code search
engine reads those. Without this, the question is unanswerable no matter how
good the search is.

Publishers are read from each repo's own manifest; consumers from their
declared dependencies. A coordinate naming no publisher in the fleet is
external, which is itself worth seeing.

Usage:
  deps.py <fleet-root> publishes            list what each repo publishes
  deps.py <fleet-root> provides <coord>     which repo publishes a coordinate
  deps.py <fleet-root> deps [repo]          fleet dependency edges
  deps.py <fleet-root> versions [coord]     which version each repo pins
"""
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

try:
    import tomllib  # 3.11+
except ImportError:  # pragma: no cover - older interpreters take the scanner
    tomllib = None


def _read(path):
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


# A package name can be spelled several ways and mean one distribution, and only
# the publisher's ECOSYSTEM knows which of those differences are meaningless.
# Comparing literally made `cs provides kit-service` report "no fleet repo
# publishes this (external dependency?)" for a repo whose pyproject.toml says
# `name = "Kit Service"` -- a confident wrong negative in the `declared` tier,
# which the skill documents as the strongest kind for a negative and the one
# most likely to be repeated to a person as fact. The parenthetical then points
# the reader at the wrong conclusion: they stop looking, because it reads as
# third-party.
#
# The rules are NOT symmetrical, and folding them together would trade this bug
# for a worse one:
#
#   pypi   PEP 503 -- [-_.] runs collapse to '-', case-insensitive
#   npm    lowercase only; the @scope/ prefix is significant
#   nuget  case-insensitive
#   maven  groupId:artifactId is CASE-SENSITIVE -- must not be folded, or two
#          genuinely different artifacts merge into one
def normalize_coord(name, eco):
    name = name.strip()
    if eco == "pypi":
        # Whitespace is folded as well as [-_.], which is a superset of PEP 503.
        # Strict PEP 503 leaves a space alone -- so `Kit Service` normalizes to
        # `kit service` and still fails to match `kit-service`, which is the
        # exact case reported. A space is invalid in a name per PEP 508 anyway;
        # the packaging tools collapse it when building the distribution, which
        # is why consumers end up writing the hyphenated form.
        return re.sub(r"[-_.\s]+", "-", name).lower()
    if eco in ("npm", "nuget"):
        return name.lower()
    return name  # maven, and anything unrecognised: compare exactly


# ---- pyproject.toml ----------------------------------------------------------
# One regex over the raw `dependencies = [...]` text gave two wrong answers. The
# name class stopped at `[`, so `"lib[extra]>=0.26.0,<1.0.0"` lost its version
# and a shared library pulled in with extras read UNPINNED in nine repos that
# all pin it -- hiding the very drift `cs versions` exists to show. And any
# quote in a `#` comment inside the array started a "package": `service's`,
# `"unable to` and `"unused in` became three phantom UNPINNED coordinates.
#
# So the file is parsed as TOML, and each requirement string is split as PEP
# 508 says: name, extras, specifier, marker. Only where tomllib is missing (or
# the file is not valid TOML) does a scanner take over -- one that skips
# comments and respects quotes, feeding the same PEP 508 split.
PEP508_RE = re.compile(
    r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"   # name
    r"\s*(?:\[[^\]]*\])?"                                  # [extras], dropped
    r"\s*(@\s*\S+|\(?[^;@]*?\)?)?"                         # specifier or @ url
    r"\s*(?:;.*)?$"                                        # ; marker, dropped
)


def split_requirement(req):
    """PEP 508 requirement -> (name, version-or-placeholder), or None."""
    m = PEP508_RE.match(req or "")
    if not m:
        return None
    spec = (m.group(2) or "").strip()
    if spec.startswith("@"):
        return m.group(1), "(direct reference)"
    spec = re.sub(r"\s+", "", spec.strip("()"))
    return m.group(1), spec or "(unpinned)"


def _toml_arrays_scanned(text, keys):
    """String items of each top-level `key = [ ... ]` array, without TOML.

    Comment-aware and quote-aware, so `[extras]` inside a string does not close
    the array and a quote inside a `#` comment does not open a string.
    """
    out = []
    for m in re.finditer(r"^\s*(%s)\s*=\s*\[" % "|".join(map(re.escape, keys)), text, re.M):
        i, depth, items, buf, quote = m.end(), 1, [], None, None
        while i < len(text) and depth:
            c = text[i]
            if quote:
                if c == "\\" and quote == '"':
                    buf.append(text[i + 1:i + 2]); i += 2; continue
                if c == quote:
                    items.append("".join(buf)); quote = None
                else:
                    buf.append(c)
            elif c in "\"'":
                quote, buf = c, []
            elif c == "#":
                nl = text.find("\n", i)
                i = len(text) if nl < 0 else nl
                continue
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
            i += 1
        out += items
    return out


def pyproject_requirements(path, problems=None):
    """[(name, version)] from [project] dependencies, optional-dependencies,
    [dependency-groups] and Poetry's dependency tables."""
    text = _read(path)
    reqs, poetry = [], {}
    data = None
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            if problems is not None:
                problems.append((path, f"not valid TOML ({exc}); read by a fallback scanner"))
    if data is not None:
        project = data.get("project") or {}
        reqs += [r for r in project.get("dependencies") or [] if isinstance(r, str)]
        for group in (project.get("optional-dependencies") or {}).values():
            reqs += [r for r in group or [] if isinstance(r, str)]
        for group in (data.get("dependency-groups") or {}).values():
            # `{include-group = "x"}` entries name another group, not a package.
            reqs += [r for r in group or [] if isinstance(r, str)]
        tool_poetry = (data.get("tool") or {}).get("poetry") or {}
        tables = [tool_poetry.get("dependencies") or {}, tool_poetry.get("dev-dependencies") or {}]
        tables += [(g or {}).get("dependencies") or {}
                   for g in (tool_poetry.get("group") or {}).values()]
        for table in tables:
            for name, spec in table.items():
                if name.lower() == "python":
                    continue
                if isinstance(spec, dict):
                    spec = spec.get("version") or ("(direct reference)" if (
                        spec.get("git") or spec.get("path") or spec.get("url")) else "")
                poetry[name] = str(spec) if spec and spec != "*" else "(unpinned)"
    else:
        reqs = _toml_arrays_scanned(text, ["dependencies", "dev", "test", "docs"])
    out = [r for r in (split_requirement(q) for q in reqs) if r]
    out += list(poetry.items())
    return out


# ---- Gradle version catalogs -------------------------------------------------
# Gradle's recommended layout keeps every coordinate and version in
# gradle/libs.versions.toml and has build files say `libs.foo.bar`. Reading
# only inline "group:artifact:version" strings in build.gradle(.kts) gave such
# a repo ZERO rows -- silently, so "which version does each repo pin" got a
# confident answer with the repo missing.
_SKIP_DIRS = {".git", "node_modules", "build", ".gradle", "bin", "obj", "target",
              "dist", ".venv", "venv", "__pycache__", ".tokensave"}


def _walk(repo, pattern):
    for path in repo.rglob(pattern):
        try:
            rel = path.relative_to(repo).parts
        except ValueError:
            rel = path.parts
        if not any(part in _SKIP_DIRS for part in rel[:-1]):
            yield path


def _catalog_version(entry, versions):
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        if "ref" in entry:
            return versions.get(entry["ref"])
        for k in ("strictly", "require", "prefer"):
            if entry.get(k):
                return entry[k]
    return None


def catalog_libraries(path, problems=None):
    """([(coordinate, version-or-placeholder, accessor)], {bundle: [accessor]})."""
    text = _read(path)
    if tomllib is None:
        if problems is not None:
            problems.append((path, "a Gradle version catalog, and this Python has no tomllib (3.11+)"))
        return [], {}
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        if problems is not None:
            problems.append((path, f"not valid TOML ({exc})"))
        return [], {}
    versions = {k: _catalog_version(v, {}) for k, v in (data.get("versions") or {}).items()}
    out = []
    for alias, lib in (data.get("libraries") or {}).items():
        coord = ver = None
        if isinstance(lib, str):
            parts = lib.split(":")
            if len(parts) >= 2:
                coord = ":".join(parts[:2])
                ver = parts[2] if len(parts) > 2 else None
        elif isinstance(lib, dict):
            if lib.get("module"):
                coord = lib["module"]
            elif lib.get("group") and lib.get("name"):
                coord = f"{lib['group']}:{lib['name']}"
            if "version.ref" in lib:            # tomllib keeps a dotted key nested,
                ver = versions.get(lib["version.ref"])   # but be safe either way
            elif "version" in lib:
                ver = _catalog_version(lib["version"], versions)
        if not coord:
            continue
        # A missing version is managed elsewhere (a BOM, a platform), the
        # same thing pom.xml's "(inherited)" means.
        out.append((coord, str(ver) if ver else "(inherited)",
                    re.sub(r"[-_.]", ".", alias)))
    bundles = {name: [re.sub(r"[-_.]", ".", a) for a in (members or [])]
               for name, members in (data.get("bundles") or {}).items()}
    return out, bundles


def catalogs(repo):
    return sorted(set(_walk(repo, "gradle/*.versions.toml")))


def catalog_usage(repo, catalog_path, libraries, bundles):
    """{accessor: [build files referencing it]} for a catalog's libraries."""
    prefix = catalog_path.name.split(".")[0]          # libs.versions.toml -> libs
    texts = {}
    for build in list(_walk(repo, "*.gradle.kts")) + list(_walk(repo, "*.gradle")):
        texts[build] = _read(build)
    used = {}
    for _coord, _ver, acc in libraries:
        rx = re.compile(r"\b%s\.%s\b(?!\.[a-z])" % (re.escape(prefix), re.escape(acc)))
        used[acc] = [b for b, t in texts.items() if rx.search(t)]
    for bundle, members in bundles.items():
        rx = re.compile(r"\b%s\.bundles\.%s\b" % (
            re.escape(prefix), re.escape(re.sub(r"[-_.]", ".", bundle))))
        users = [b for b, t in texts.items() if rx.search(t)]
        for acc in members:
            used.setdefault(acc, [])
            used[acc] += [b for b in users if b not in used[acc]]
    return used


# ---- NuGet packages.config ---------------------------------------------------
# The default for every .NET Framework project that was never migrated to
# PackageReference -- so the repos it misses are the older, central ones.
def packages_config(path, problems=None):
    text = _read(path)
    try:
        root = ET.fromstring(text)
        return [(p.get("id"), p.get("version") or "(inherited)")
                for p in root.iter("package") if p.get("id")]
    except ET.ParseError as exc:
        if problems is not None:
            problems.append((path, f"not valid XML ({exc}); read by a fallback pattern"))
        out = []
        for m in re.finditer(r"<package\b([^>]*)>", text):
            attrs = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', m.group(1)))
            if attrs.get("id"):
                out.append((attrs["id"], attrs.get("version") or "(inherited)"))
        return out


def central_package_versions(repo):
    """NuGet central package management: Directory.Packages.props versions."""
    out = {}
    for props in _walk(repo, "Directory.Packages.props"):
        for m in re.finditer(r'<PackageVersion\s+Include="([^"]+)"\s+Version="([^"]+)"',
                             _read(props)):
            out.setdefault(m.group(1), m.group(2))
    return out


# ---- what was NOT read -------------------------------------------------------
# A repo whose manifest cs cannot read used to show zero rows and nothing else:
# indistinguishable from a repo that declares nothing. Naming the file is the
# same fail-closed rule as naming the corpus bound on a zero-hit text answer.
UNREAD_MANIFESTS = (
    "requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg", "Pipfile",
    "go.mod", "Cargo.toml", "Gemfile", "build.sbt", "composer.json", "pubspec.yaml",
    "Package.swift", "mix.exs", "deps.edn", "project.clj", "*.fsproj", "*.vbproj",
)


def unread_manifests(repo):
    out = []
    for pattern in UNREAD_MANIFESTS:
        out += [p for p in repo.glob(pattern) if p.is_file()]
    return sorted(out)


def publishes_tagged(repo):
    """(coordinate, ecosystem, manifest-path) for everything this repo publishes."""
    out = []

    for gradle in list(repo.glob("build.gradle.kts")) + list(repo.glob("build.gradle")):
        text = _read(gradle)
        group = re.search(r'^\s*group\s*=\s*["\']([^"\']+)["\']', text, re.M)
        artifact = re.search(r'artifactId\s*=\s*["\']([^"\']+)["\']', text)
        if group and artifact:
            out.append((f"{group.group(1)}:{artifact.group(1)}", "maven", gradle))

    for pom in repo.glob("pom.xml"):
        text = _read(pom)
        g = re.search(r"<groupId>([^<]+)</groupId>", text)
        a = re.search(r"<artifactId>([^<]+)</artifactId>", text)
        if g and a:
            out.append((f"{g.group(1)}:{a.group(1)}", "maven", pom))

    for pkg in list(repo.glob("package.json")) + list(repo.glob("*/package.json")):
        try:
            data = json.loads(_read(pkg) or "{}")
        except json.JSONDecodeError:
            continue
        if data.get("name") and not data.get("private"):
            out.append((data["name"], "npm", pkg))

    for pyproject in repo.glob("pyproject.toml"):
        name = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', _read(pyproject), re.M)
        if name:
            out.append((name.group(1), "pypi", pyproject))

    for csproj in repo.rglob("*.csproj"):
        pkg_id = re.search(r"<PackageId>([^<]+)</PackageId>", _read(csproj))
        if pkg_id:
            out.append((pkg_id.group(1), "nuget", csproj))

    return out


def publishes(repo):
    """Coordinates this repo publishes, as a list of strings."""
    return sorted({coord for coord, _eco, _path in publishes_tagged(repo)})


def consumes(repo, problems=None):
    """Coordinates this repo declares a dependency on.

    The same reader as consumes_versioned, minus the version: two parsers of one
    manifest drift apart, and the edge graph and the version table then
    disagree about what a repo depends on.
    """
    return sorted({coord for coord, _ver, _manifest in consumes_versioned(repo, problems)})


def consumes_versioned(repo, problems=None):
    """[(coordinate, version, manifest-relative-path)] this repo declares.

    consumes() deliberately drops the version, because "who depends on what" does
    not need it. "Is the fleet agreed on a version" is a different question and
    cannot be answered without it -- and it is the question that catches a repo
    left behind by an upgrade, which is a real bug shape rather than a tidiness
    complaint.
    """
    out = []

    def rel(p):
        try:
            return str(p.relative_to(repo))
        except ValueError:
            return p.name

    for gradle in list(repo.glob("build.gradle.kts")) + list(repo.glob("build.gradle")):
        for m in re.finditer(r'["\']([\w.\-]+:[\w.\-]+):([\w.\-]+)["\']', _read(gradle)):
            out.append((m.group(1), m.group(2), rel(gradle)))

    for pom in repo.glob("pom.xml"):
        for dep in re.finditer(
            r"<dependency>\s*<groupId>([^<]+)</groupId>\s*"
            r"<artifactId>([^<]+)</artifactId>\s*(?:<version>([^<]+)</version>)?",
            _read(pom),
        ):
            out.append((f"{dep.group(1)}:{dep.group(2)}",
                        (dep.group(3) or "(inherited)").strip(), rel(pom)))

    for pkg in list(repo.glob("package.json")) + list(repo.glob("*/package.json")):
        try:
            data = json.loads(_read(pkg) or "{}")
        except json.JSONDecodeError as exc:
            if problems is not None:
                problems.append((pkg, f"not valid JSON ({exc})"))
            continue
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for name, ver in (data.get(section) or {}).items():
                out.append((name, str(ver), rel(pkg)))

    for pyproject in repo.glob("pyproject.toml"):
        for name, ver in pyproject_requirements(pyproject, problems):
            out.append((name, ver, rel(pyproject)))

    for catalog in catalogs(repo):
        libraries, bundles = catalog_libraries(catalog, problems)
        used = catalog_usage(repo, catalog, libraries, bundles)
        for coord, ver, acc in libraries:
            # Every catalog entry is a declaration of this repo, used or not --
            # but which build file pulls it in is the attribution a reader
            # needs, so it is named where it can be found.
            users = used.get(acc) or []
            where = rel(catalog)
            if users:
                where += " <- " + ", ".join(sorted(rel(u) for u in users))
            else:
                where += " (no build file references libs.%s)" % acc
            out.append((coord, ver, where))

    central = central_package_versions(repo)
    for csproj in _walk(repo, "*.csproj"):
        for m in re.finditer(
            r'PackageReference\s+Include="([^"]+)"(?:\s+Version="([^"]+)")?', _read(csproj)
        ):
            out.append((m.group(1), m.group(2) or central.get(m.group(1)) or "(inherited)",
                        rel(csproj)))

    for config in _walk(repo, "packages.config"):
        for pkg_id, ver in packages_config(config, problems):
            out.append((pkg_id, ver, rel(config)))

    return out


def normalize_version(v):
    """Strip a constraint prefix so versions can be compared across ecosystems.

    `==2.4.0` (pip), `^2.4.0` (npm caret), `~2.4.0`, `v2.4.0` and `2.4.0` all
    name the same release; only the dialect differs. This deliberately does NOT
    try to interpret range semantics -- `>=2.0` and `2.0` really are different
    promises -- it only removes the spelling, so that a repo genuinely left
    behind by an upgrade stands out from four repos agreeing in four syntaxes.
    """
    return re.sub(r"^[\s=<>!~^v]+", "", v.strip()).strip()


def repos(root):
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))


def report_unread(root, problems, scanned):
    """On stderr: manifests that were present and not (fully) read.

    Printed whenever there are any, because a repo that is missing from the
    answer for this reason looks exactly like a repo that declares nothing.
    """
    def rel(p):
        try:
            return str(p.relative_to(root))
        except ValueError:
            return str(p)

    unread = [p for repo in scanned for p in unread_manifests(repo)]
    if unread:
        print(f"! not read: {len(unread)} manifest(s) in a format this does not "
              f"parse, so what they declare is NOT in this answer:", file=sys.stderr)
        for p in unread[:20]:
            print(f"    {rel(p)}", file=sys.stderr)
        if len(unread) > 20:
            print(f"    … and {len(unread) - 20} more", file=sys.stderr)
    for path, why in problems:
        print(f"! {rel(path)}: {why}", file=sys.stderr)


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    root = pathlib.Path(sys.argv[1])
    cmd = sys.argv[2]

    if not root.is_dir():
        print(f"no such fleet root: {root}", file=sys.stderr)
        return 2

    publisher = {}
    # Parallel index keyed on the ECOSYSTEM-normalized name, so a coordinate
    # that differs from its manifest spelling only by normalization still
    # resolves. Carries the raw spelling and manifest path so a match found this
    # way can say what the manifest actually declares -- a name that needs
    # normalizing is usually a small bug in that repo too, and surfacing it
    # beats silently papering over it.
    publisher_norm = {}
    for repo in repos(root):
        for coord, eco, path in publishes_tagged(repo):
            publisher[coord] = repo.name
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = path
            publisher_norm.setdefault(
                normalize_coord(coord, eco), (repo.name, coord, eco, str(rel))
            )

    def resolve(want):
        """(repo, note) for whoever publishes `want`, or (None, None)."""
        if want in publisher:
            return publisher[want], None
        # A bare artifact id, so "pricing-lib" resolves as well as the full
        # "com.acme:pricing-lib".
        for coord, owner in publisher.items():
            if coord.split(":")[-1] == want:
                return owner, None
        # Normalized -- but each candidate is compared under ITS OWN ecosystem's
        # rules, never under a rule borrowed from another. Trying the query
        # against every ruleset in turn instead let npm's lowercasing match a
        # Maven key, so `com.acme:Pricing-Lib` resolved to `com.acme:pricing-lib`
        # -- exactly the case-folding that ecosystem forbids, and the merge of
        # two genuinely different artifacts the rules exist to prevent.
        for key, (owner, raw, raw_eco, rel) in publisher_norm.items():
            if normalize_coord(want, raw_eco) == key:
                if raw != want:
                    return owner, f"{want} -> declared as '{raw}' in {rel} ({raw_eco} normalization)"
                return owner, None
        # And a bare artifact id on the normalized side too.
        for key, (owner, raw, raw_eco, rel) in publisher_norm.items():
            if key.split(":")[-1] == normalize_coord(want, raw_eco):
                return owner, f"{want} -> declared as '{raw}' in {rel} ({raw_eco} normalization)"
        return None, None

    if cmd == "publishes":
        for coord, name in sorted(publisher.items()):
            print(f"{name}\tpublishes\t{coord}")
        return 0

    if cmd == "provides":
        if len(sys.argv) < 4:
            print("usage: deps.py <root> provides <coordinate>", file=sys.stderr)
            return 2
        want = sys.argv[3]
        name, note = resolve(want)
        if name:
            if note:
                print(note, file=sys.stderr)
            print(name)
            return 0
        print(f"no fleet repo publishes '{want}' (external dependency?)", file=sys.stderr)
        report_unread(root, [], repos(root))
        return 1

    if cmd == "deps":
        only = sys.argv[3] if len(sys.argv) > 3 else None
        problems = []
        scanned = [r for r in repos(root) if not only or r.name == only]
        for repo in scanned:
            for coord in consumes(repo, problems):
                # Same resolution as `provides`, so an intra-fleet edge is not
                # invisible purely because the two manifests spell the name
                # differently. Without this, any edge involving a
                # non-normalized publish name could never be detected.
                owner, _note = resolve(coord)
                if owner and owner != repo.name:
                    print(f"{repo.name}\t->\t{owner}\t({coord})")
        report_unread(root, problems, scanned)
        return 0

    if cmd == "versions":
        want = sys.argv[3] if len(sys.argv) > 3 else None
        rows, problems = [], []
        for repo in repos(root):
            for coord, ver, manifest in consumes_versioned(repo, problems):
                if want and coord != want and coord.split(":")[-1] != want:
                    continue
                rows.append((repo.name, coord, ver, manifest))
        report_unread(root, problems, repos(root))
        if not rows:
            if want:
                print(f"no repo in the fleet declares a dependency on '{want}'",
                      file=sys.stderr)
            return 1
        # Grouped by coordinate so the comparison is adjacent; the point of the
        # command is the disagreement, and a flat list buries it.
        for coord in sorted({r[1] for r in rows}):
            mine = [r for r in rows if r[1] == coord]
            # Compared on the version NUMBER, not the raw declaration. Each
            # ecosystem spells a pin differently -- `==2.4.0` in pyproject.toml
            # and `2.4.0` in package.json are the same version -- and reporting
            # that as drift is a false positive in the one command whose entire
            # value is that its findings are worth acting on.
            pinned = {normalize_version(r[2]) for r in mine
                      if not r[2].startswith("(")}
            unknown = [r for r in mine if r[2].startswith("(")]
            spellings = {r[2] for r in mine}

            if len(pinned) > 1:
                flag, detail = "DRIFT", f"{len(pinned)} version(s)"
            elif pinned:
                flag, detail = "AGREED", f"{len(pinned)} version(s)"
                if len(spellings) > len(pinned):
                    detail += ", spelled differently per ecosystem"
            else:
                flag, detail = "UNPINNED", "no explicit version"

            # The same resolution as `provides`, so a name declared in another
            # spelling (`Kit Service`) is not labelled external here while
            # `cs provides` names its publisher.
            owner, _note = resolve(coord)
            line = f"{coord}\t{flag}\t{detail}"
            line += f"\tpublished by {owner}" if owner else "\texternal"
            if unknown and flag != "UNPINNED":
                line += f" ({len(unknown)} declaration(s) inherit or float)"
            print(line)
            for name, _c, ver, manifest in sorted(mine):
                print(f"  {name}\t{ver}\t{manifest}")
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
