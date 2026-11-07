#!/usr/bin/env python3
"""Bring a workspace clone's tokensave graph up to the files on disk, bounded.

    graph_sync.py <repo-dir> <timeout-seconds>

Prints ONE line, `<status>\t<detail>`, and exits 0 whatever happened, because
the caller answers from the graph either way and only wants to know which of
these it is answering from:

    unchanged  no file tokensave indexes changed since the graph's last sync
    synced     files had changed, and `tokensave sync` brought the graph up
    failed     files had changed (or could not be checked) and the sync did not
               complete; the detail says why

Why cs syncs at all (#127): a graph answers about the code as of its last sync,
and in a workspace the code on disk is exactly what the person asking is
editing. cs printed the age and told them to run the sync themselves; it is the
component that knows which graph a call reads, so it now runs it. Fleet-layer
graphs are not passed here: they describe main by design, and their refresh is
owned elsewhere.

Measured against tokensave 7.16.0 before writing the check below:

  1. `tokensave sync` indexes untracked files that git does not ignore, skips
     ignored ones, and drops deleted ones. So the files to look at are
     `git ls-files --cached --others --exclude-standard`.
  2. It decides what changed by modification time: an edit written back with
     its old mtime (same size) is not re-extracted even by an explicit sync.
     An mtime check therefore misses nothing that the sync itself would see.
  3. A deletion leaves no file to be newer, so the directories holding the
     listed files are checked too: removing or adding an entry moves its
     directory's mtime, and that covers new files copied in with an old mtime.
  4. Two syncs of one graph at once can fail with "sync lock: could not reclaim
     lockfile" -- and an agent asking callers and callees in parallel starts
     exactly that. cs's own syncs of one graph are serialised by a lock here;
     a sync tokensave refuses for its lock is retried until the deadline.

A sync with nothing to do costs ~0.5 s on a 118 MB graph (#127), which is what
the check saves on the common case; a false "changed" costs only that.
"""
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def last_sync_at(repo):
    """Epoch seconds of the graph's last verification against the tree, or None.

    `last_sync_at`, not `last_updated`: a sync that finds nothing advances only
    the first (see tokensave_graph_epoch in cs)."""
    try:
        p = subprocess.run(["tokensave", "status", repo, "--json"],
                           stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=30)
        v = json.loads(p.stdout).get("last_sync_at")
        return int(v) if v is not None else None
    except (OSError, subprocess.SubprocessError, ValueError, TypeError,
            AttributeError):
        return None


def changed_since(repo, epoch):
    """True when a file the graph indexes, or a directory holding one, has an
    mtime at or after the sync. True also when that cannot be told: the cost of
    a needless sync is half a second, of a skipped one a wrong answer."""
    if epoch is None:
        return True
    try:
        p = subprocess.run(["git", "-C", repo, "ls-files", "-z", "--cached",
                            "--others", "--exclude-standard"],
                           stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=60)
    except (OSError, subprocess.SubprocessError):
        return True
    if p.returncode != 0:
        return True
    dirs = {""}
    for raw in p.stdout.split(b"\0"):
        if not raw:
            continue
        rel = os.fsdecode(raw)
        try:
            if os.lstat(os.path.join(repo, rel)).st_mtime >= epoch:
                return True
        except OSError:
            pass   # a tracked file deleted: its directory's mtime says when
        d = os.path.dirname(rel)
        while d not in dirs:
            dirs.add(d)
            d = os.path.dirname(d)
    for d in dirs:
        try:
            if os.stat(os.path.join(repo, d)).st_mtime >= epoch:
                return True
        except OSError:
            pass
    return False


def last_line(text):
    lines = [ANSI.sub("", l).strip() for l in text.replace("\r", "\n").split("\n")]
    lines = [l for l in lines if l]
    return (lines[-1] if lines else "")[:200]


def kill_group(proc, sig):
    try:
        os.killpg(proc.pid, sig)
    except OSError:
        pass


def run_sync(repo, deadline):
    """None on success, else the reason the sync did not complete."""
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return "timed out"
        try:
            # Its own process group, so a timeout reaches whatever it started:
            # a child left holding the pipe would keep communicate() waiting
            # past the deadline the timeout exists to keep.
            proc = subprocess.Popen(["tokensave", "sync", repo],
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    start_new_session=True)
        except OSError as e:
            return f"tokensave sync did not start: {e}"
        try:
            out, _ = proc.communicate(timeout=left)
        except subprocess.TimeoutExpired:
            # TERM first: the graph is SQLite, and a sync given the chance to
            # stop leaves less to recover than one killed mid-write.
            kill_group(proc, signal.SIGTERM)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                kill_group(proc, signal.SIGKILL)
                proc.communicate()
            return "timed out"
        if proc.returncode == 0:
            return None
        why = last_line(out)
        if "lock" in why.lower() and deadline - time.monotonic() > 0.5:
            time.sleep(0.5)   # another sync of this graph, outside cs
            continue
        return f"tokensave sync exited {proc.returncode}" + (f": {why}" if why else "")


def main():
    repo = os.path.realpath(sys.argv[1])
    timeout = float(sys.argv[2])
    deadline = time.monotonic() + timeout

    if not changed_since(repo, last_sync_at(repo)):
        print("unchanged\t")
        return

    key = hashlib.sha1(repo.encode()).hexdigest()[:16]
    lock_path = os.path.join(tempfile.gettempdir(), f"cs-graph-sync-{key}.lock")
    with open(lock_path, "w") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    print(f"failed\ttimed out after {timeout:g}s waiting for "
                          "another cs to finish syncing this graph")
                    return
                time.sleep(0.2)
        # The cs holding the lock before us may have just synced it.
        if not changed_since(repo, last_sync_at(repo)):
            print("synced\tby a concurrent cs")
            return
        started = time.monotonic()
        why = run_sync(repo, deadline)
        if why == "timed out":
            print(f"failed\ttimed out after {timeout:g}s (CS_GRAPH_SYNC_TIMEOUT)")
        elif why:
            print(f"failed\t{why}")
        else:
            print(f"synced\tin {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # never fail the answer on the sync
        print(f"failed\t{type(e).__name__}: {e}")
