"""Shared test fixtures for the skill script tests.

make_repo(tmp, files, commits) -> path: build a real git repo under tmp.
run_script(name, *args, cwd) -> CompletedProcess: run a skill script via sys.executable.
"""
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skill", "scripts")


def _git(cwd, *args):
    return subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def write_files(root, files):
    for relpath, content in files.items():
        full = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)


def make_repo(tmp, files=None, commits=None):
    """Create a git repo at `tmp`. `files` is written before any commit, if
    `commits` is empty. `commits` is a list of {"files": {...}, "message": str}
    dicts, applied in order, each producing one commit. Returns `tmp`."""
    os.makedirs(tmp, exist_ok=True)
    _git(tmp, "init", "-q")
    if files:
        write_files(tmp, files)
    if commits:
        for i, c in enumerate(commits):
            if c.get("files"):
                write_files(tmp, c["files"])
            _git(tmp, "add", "-A")
            msg = c.get("message", "commit %d" % i)
            _git(tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", msg)
    elif files:
        _git(tmp, "add", "-A")
        _git(tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init")
    return tmp


def run_script(name, *args, cwd=None):
    script = os.path.join(SCRIPTS_DIR, name)
    return subprocess.run(
        [sys.executable, script] + list(args),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
