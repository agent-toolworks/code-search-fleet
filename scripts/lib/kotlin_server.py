#!/usr/bin/env python3
"""The Kotlin language server Serena runs: which build, whether it starts, and
how to replace it (#130).

    kotlin_server.py which              <source> TAB <launcher> TAB <build> TAB <built> TAB <note>
    kotlin_server.py start <launcher> [timeout]
                                        starts | expired | exits TAB <rc> TAB <line>
                                        | silent TAB <seconds>
    kotlin_server.py newest             the newest release's build number, or nothing
    kotlin_server.py install [--version V] [--dir D]

Why: JetBrains ships kotlin-server as pre-release builds that stop starting
about a month after they are built -- 263.4702.0 (built 2026-09-08) had stopped
by 2026-10-09 (#90), 263.6379.0 (built 2026-09-30) passed verify-engines on
2026-10-27 and had stopped by 2026-11-07 (#130). An expired build prints "This
build of kotlin-server has expired" and exits 7 within about two seconds. cs
doctor checked the Kotlin runtime and never started the server, so a green
Kotlin row and a refused query coexisted; and the docs pinned a build number,
which rots on the same schedule. So the doctor starts the server the way an LSP
client does, and the install takes the newest release rather than a number.

Which build Serena runs: `ls_specific_settings.kotlin.ls_path` in
~/.serena/serena_config.yml when set, otherwise its own copy under
~/.serena/language_servers/static/KotlinLanguageServer/. Serena can download a
build itself (`kotlin_lsp_version`), but from download-cdn.jetbrains.com, which
answered 404 for every kotlin-server build tried, old and newest, on
2026-11-07; download.jetbrains.com serves them. So the fix is `ls_path`.
"""
import json
import os
import platform
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

SERENA_CONFIG = os.path.expanduser("~/.serena/serena_config.yml")
STATIC = os.path.expanduser("~/.serena/language_servers/static/KotlinLanguageServer")
INSTALL_ROOT = os.path.expanduser("~/.local/share/kotlin-server")
RELEASES = "https://github.com/Kotlin/kotlin-lsp/releases/latest"
DOWNLOAD = "https://download.jetbrains.com/language-server/kotlin-server/{v}/{a}"
EXPIRED = re.compile(r"(kotlin-server|EAP build) has expired")
# Asset suffixes, as Serena's own Kotlin installer names them (solidlsp).
SUFFIX = {("Darwin", "arm64"): "-aarch64.sit", ("Darwin", "x86_64"): ".sit",
          ("Linux", "aarch64"): "-aarch64.tar.gz", ("Linux", "x86_64"): ".tar.gz"}


def kotlin_settings(text):
    """ls_path and kotlin_lsp_version under ls_specific_settings.kotlin, read
    without a YAML library: cs cannot assume one is installed. A value may sit
    on the line after its key (`ls_path:` then the path, indented), which is how
    a long path gets wrapped and is valid YAML."""
    out, lines = {}, text.splitlines()
    in_ls = in_kt = False
    kt_indent = -1
    for i, raw in enumerate(lines):
        line = raw.split(" #")[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        key = line.strip()
        if indent == 0:
            in_ls = key.startswith("ls_specific_settings:")
            in_kt = False
            continue
        if in_ls and key.startswith("kotlin:"):
            in_kt, kt_indent = True, indent
            continue
        if in_kt and indent <= kt_indent:
            in_kt = False
        if not in_kt:
            continue
        # `ls_path:/x`, with no space, is one plain string to YAML, not a key
        # and a value: Serena ignores it without a word (docs/install.md).
        m = re.match(r"ls_path:(\S.*)$", key)
        if m:
            out["unspaced"] = m.group(1)
            continue
        m = re.match(r"(ls_path|kotlin_lsp_version):(\s.*)?$", key)
        if not m:
            continue
        val = (m.group(2) or "").strip()
        if not val:
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    if len(nxt) - len(nxt.lstrip()) > indent:
                        val = nxt.strip()
                    break
        out[m.group(1)] = val.strip("'\"")
    return out


def build_of(launcher):
    """(build number, build date YYYY-MM-DD) from the build's product-info.json
    -- two levels above bin/intellij-server -- or ("", "")."""
    home = os.path.dirname(os.path.dirname(os.path.realpath(launcher)))
    try:
        with open(os.path.join(home, "product-info.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return "", ""
    date = d.get("majorVersionReleaseDate") or ""
    if re.fullmatch(r"\d{8}", date):
        date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return d.get("buildNumber") or "", date


def which():
    try:
        with open(SERENA_CONFIG) as f:
            settings = kotlin_settings(f.read())
    except OSError:
        settings = {}
    if settings.get("ls_path"):
        p = os.path.expanduser(settings["ls_path"])
        return "ls_path", p, ""
    note = f"ls_path:{settings['unspaced']} has no space after the colon, so Serena ignores it" \
        if settings.get("unspaced") else ""
    # Serena's own copy: the version it is told to use, else the newest it has.
    # A leftover from an older pin has the lower number; the newest present is
    # the one the pinned Serena installed.
    want = settings.get("kotlin_lsp_version")
    best, best_v = "", ()
    for d in sorted(os.listdir(STATIC)) if os.path.isdir(STATIC) else []:
        m = re.fullmatch(r"kotlin_language_server-(\d[\d.]*)", d)
        if not m:
            continue
        p = os.path.join(STATIC, d, f"kotlin-server-{m.group(1)}", "bin", "intellij-server")
        if not os.path.exists(p):
            continue
        v = tuple(int(x) for x in m.group(1).split("."))
        if want and m.group(1) == want:
            return "serena", p, note
        if v > best_v:
            best, best_v = p, v
    return ("serena", best, note) if best else ("none", "", note)


def frame(obj):
    body = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def start(launcher, timeout=60.0):
    """Start the server as an LSP client does and ask it `initialize`.

    An answer is the proof it starts. The expiry message, or an exit before
    answering, is the proof it does not. Neither within the timeout is said as
    such, not guessed at. Measured on macOS arm64: 263.7084.0 answered in about
    5 s; the expired 263.6379.0 and 263.4702.0 exited in under 2 s."""
    tmp = tempfile.mkdtemp(prefix="cs-kotlin-probe.")
    # The server makes an idea-system<N> directory in java.io.tmpdir for each
    # start, and a server stopped by a signal leaves it there: five in $TMPDIR
    # after one suite run. Pointed into this probe's own directory, which goes.
    # (On macOS the JVM takes its temp dir from the OS, not from $TMPDIR, so the
    # property is the lever; the launcher appends IJ_JAVA_OPTIONS to its own.)
    env = dict(os.environ, TMPDIR=tmp)
    env["IJ_JAVA_OPTIONS"] = (env.get("IJ_JAVA_OPTIONS", "") + f" -Djava.io.tmpdir={tmp}").strip()
    try:
        proc = subprocess.Popen([launcher, "--stdio"], cwd=tmp, env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return f"exits\t-\t{e}"
    try:
        proc.stdin.write(frame({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"processId": os.getpid(), "rootUri": None,
                                           "capabilities": {}}}))
        proc.stdin.flush()
    except OSError:
        pass   # it exited already; the output says why
    out, err = b"", b""
    deadline = time.monotonic() + timeout
    streams = {proc.stdout.fileno(): "out", proc.stderr.fileno(): "err"}
    try:
        while streams:
            left = deadline - time.monotonic()
            if left <= 0:
                return f"silent\t{timeout:g}"
            ready, _, _ = select.select(list(streams), [], [], min(left, 1.0))
            for fd in ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    del streams[fd]
                elif streams[fd] == "out":
                    out += chunk
                else:
                    err += chunk
            text = (out + err).decode(errors="replace")
            if EXPIRED.search(text):
                return "expired"
            if re.search(rb'"id"\s*:\s*1\b', out) and b'"result"' in out:
                return "starts"
        proc.wait(timeout=max(deadline - time.monotonic(), 1))
        text = (out + err).decode(errors="replace")
        if EXPIRED.search(text):
            return "expired"
        last = [l.strip() for l in text.splitlines() if l.strip()]
        return f"exits\t{proc.returncode}\t{(last[-1] if last else '')[:200]}"
    except subprocess.TimeoutExpired:
        return f"silent\t{timeout:g}"
    finally:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if proc.poll() is not None:
                break
            try:
                os.killpg(proc.pid, sig)
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        shutil.rmtree(tmp, ignore_errors=True)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def newest(timeout=3.0):
    """The newest release's build number, or "" when it cannot be told -- offline,
    or a tag in another shape. Never a guess.

    From where the web page's /releases/latest redirects to, not from the API:
    the anonymous API allows 60 calls an hour per address, and answered 403
    "rate limit exceeded" on the maintainer's network (2026-11-07), where the
    redirect answered at once. One HEAD request, no body."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(RELEASES, method="HEAD", headers={"User-Agent": "cs-doctor"})
    try:
        opener.open(req, timeout=timeout)
        return ""
    except urllib.error.HTTPError as e:
        where = e.headers.get("Location") or ""
    except Exception:
        return ""
    m = re.search(r"/v?(\d+\.\d+\.\d+)$", where)
    return m.group(1) if m else ""


def install(version, root):
    """Download a build, check its SHA-256, unpack it, and print its launcher.

    The checksum comes from the same host as the archive, so it proves the
    download is intact, not who made it. JetBrains publishes no other."""
    key = (platform.system(), platform.machine())
    if key not in SUFFIX:
        sys.exit(f"kotlin-server is not published for {key[0]} {key[1]}")
    v = version or newest(timeout=15)
    if not v:
        sys.exit("could not read the newest release from " + RELEASES +
                 " -- pass --version <build> (see https://github.com/Kotlin/kotlin-lsp/releases)")
    asset = f"kotlin-server-{v}{SUFFIX[key]}"
    launcher = os.path.join(root, f"kotlin-server-{v}", "bin", "intellij-server")
    if os.path.exists(launcher):
        print(f"kotlin-server {v} is already unpacked", file=sys.stderr)
    else:
        os.makedirs(root, exist_ok=True)
        work = tempfile.mkdtemp(prefix="cs-kotlin-dl.", dir=root)
        try:
            archive = os.path.join(work, asset)
            print(f"downloading {DOWNLOAD.format(v=v, a=asset)}", file=sys.stderr)
            subprocess.run(["curl", "-fsSL", "-o", archive, DOWNLOAD.format(v=v, a=asset)], check=True)
            want = subprocess.run(["curl", "-fsSL", DOWNLOAD.format(v=v, a=asset) + ".sha256"],
                                  check=True, capture_output=True, text=True).stdout.split()[0]
            import hashlib
            h = hashlib.sha256()
            with open(archive, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            if h.hexdigest() != want.lower():
                sys.exit(f"SHA-256 mismatch for {asset}: got {h.hexdigest()}, published {want}")
            print(f"SHA-256 OK ({want})", file=sys.stderr)
            # ditto and tar keep the exec bits and symlinks the bundled runtime
            # needs; Python's zipfile drops both.
            if asset.endswith(".sit"):
                subprocess.run(["ditto", "-x", "-k", archive, work], check=True)
            else:
                subprocess.run(["tar", "xzf", archive, "-C", work], check=True)
            os.rename(os.path.join(work, f"kotlin-server-{v}"), os.path.join(root, f"kotlin-server-{v}"))
        except subprocess.CalledProcessError as e:
            sys.exit(f"{e.cmd[0]} failed (exit {e.returncode}): {e.cmd[-1]}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    if not os.path.exists(launcher):
        sys.exit(f"unpacked, but {launcher} is not there")
    print(launcher)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "which":
        source, launcher, note = which()
        build, built = build_of(launcher) if launcher else ("", "")
        print(f"{source}\t{launcher}\t{build}\t{built}\t{note}")
    elif cmd == "start" and len(argv) >= 3:
        print(start(argv[2], float(argv[3]) if len(argv) > 3 else 60.0))
    elif cmd == "newest":
        print(newest())
    elif cmd == "install":
        version, root, rest = "", INSTALL_ROOT, argv[2:]
        while rest:
            a = rest.pop(0)
            if a == "--version" and rest:
                version = rest.pop(0)
            elif a == "--dir" and rest:
                root = os.path.expanduser(rest.pop(0))
            else:
                sys.exit("usage: kotlin_server.py install [--version <build>] [--dir <dir>]")
        install(version, root)
    else:
        sys.exit(__doc__.split("\n\n")[1])


if __name__ == "__main__":
    main(sys.argv)
