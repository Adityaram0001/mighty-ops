#!/usr/bin/env python3
"""kblib.py -- shared library for the mighty-ops-system-manager scripts.

Not a CLI. Import only: `import kblib` after
`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`.

Provides: find_kb, load_state, save_state, system_for_path, git,
is_git_repo, head, count_test_fns, is_test_path, read_limits, now_iso,
slugify, REQUIRED_FILES, ENTRY_RX. See reference/kb-layout.md.
"""
import fnmatch
import json
import os
import re
import subprocess
import time

SCHEMA = "mighty-ops-kb/1"

REQUIRED_FILES = [
    "findings.md",
    "vision.md",
    "limitations.md",
    "todo.md",
    "done.md",
    "decisions.md",
]

ENTRY_RX = r"^### ([A-Z]+-\d+) — "

_POINTER_RX = re.compile(r"Systems knowledge base: `([^`]+)`")
_TEST_FN_RX = re.compile(r"^\s*(async\s+)?def test_|^\s*(it|test)\(", re.M)


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slugify(text, max=40):
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:max].rstrip("-") or "x"


def find_kb(project):
    """Locate the KB dir for `project`, in discovery order (CLAUDE.md pointer line,
    <project>/mighty-ops/state.json, then a depth-1 schema scan). Returns an
    absolute path, or None if no KB is found."""
    project = os.path.abspath(project)

    claude_md = os.path.join(project, "CLAUDE.md")
    if os.path.isfile(claude_md):
        try:
            with open(claude_md, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            text = ""
        m = _POINTER_RX.search(text)
        if m:
            kb_dir = m.group(1).rstrip("/")
            candidate = os.path.join(project, kb_dir)
            if os.path.isdir(candidate):
                return candidate

    default = os.path.join(project, "mighty-ops")
    if os.path.isfile(os.path.join(default, "state.json")):
        return default

    try:
        names = sorted(os.listdir(project))
    except OSError:
        names = []
    for name in names:
        candidate = os.path.join(project, name)
        state_path = os.path.join(candidate, "state.json")
        if not os.path.isdir(candidate) or not os.path.isfile(state_path):
            continue
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("schema") == SCHEMA:
            return candidate
    return None


def load_state(kb):
    """Read and validate <kb>/state.json. Raises ValueError if missing,
    malformed, or schema-mismatched."""
    path = os.path.join(kb, "state.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise ValueError("state.json missing or unreadable: %s" % e)
    except ValueError as e:
        raise ValueError("state.json invalid JSON: %s" % e)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("state.json schema mismatch")
    return data


def save_state(kb, st):
    """Atomically write <kb>/state.json, key order preserved."""
    path = os.path.join(kb, "state.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _norm(path):
    p = path.replace(os.sep, "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def system_for_path(path, systems, kb_dir, noise):
    """Classify a project-relative path. Returns a system id, "(kb)",
    "(noise:<prefix>)", "(skills)", or "(unmapped)". See SS D.3 and SS F.2."""
    path = _norm(path)
    kb_dir_norm = _norm(kb_dir).rstrip("/") if kb_dir else None
    if kb_dir_norm and (path == kb_dir_norm or path.startswith(kb_dir_norm + "/")):
        return "(kb)"

    best_id = None
    best_len = -1
    for sysdef in systems or []:
        for p in sysdef.get("paths", []) or []:
            p_norm = _norm(p)
            if "*" in p_norm:
                if fnmatch.fnmatch(path, p_norm):
                    matched_len = len(p_norm)
                else:
                    continue
            else:
                p2 = p_norm.rstrip("/")
                if path == p2 or path.startswith(p2 + "/"):
                    matched_len = len(p2)
                else:
                    continue
            if matched_len > best_len:
                best_len = matched_len
                best_id = sysdef.get("id")
    if best_id is not None:
        return best_id

    for n in noise or []:
        n_norm = _norm(n).rstrip("/")
        if path == n_norm or path.startswith(n_norm + "/"):
            return "(noise:%s)" % n
    default_noise = "orchestration"
    if not noise and (path == default_noise or path.startswith(default_noise + "/")):
        return "(noise:orchestration/)"

    if path.startswith(".claude/skills/"):
        return "(skills)"

    return "(unmapped)"


def git(project, *args):
    """Run git with cwd=project. Returns (returncode, combined stdout+stderr
    text). Never uses `git -C`, never shell=True, no env changes."""
    try:
        proc = subprocess.run(
            ["git"] + list(args),
            cwd=project,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        return 127, "git not found"
    return proc.returncode, proc.stdout


def is_git_repo(project):
    rc, _ = git(project, "rev-parse", "--is-inside-work-tree")
    return rc == 0


def head(project):
    rc, out = git(project, "rev-parse", "HEAD")
    if rc != 0:
        return None
    return out.strip()


def count_test_fns(text):
    """Count test function/case definitions: `def test_*` (py) and
    `it(` / `test(` (js-like)."""
    return len(_TEST_FN_RX.findall(text))


def is_test_path(p):
    """Test-path heuristic: a tests/ dir ancestor, or a
    test_*/_test filename, or a .test./.spec. filename."""
    p = _norm(p)
    parts = p.split("/")
    b = parts[-1]
    if any(part in ("tests", "test", "__tests__", "spec") for part in parts[:-1]):
        return True
    if b.startswith("test_") or b.endswith("_test.py"):
        return True
    if re.search(r"\.(test|spec)\.[jt]sx?$", b):
        return True
    return False


def read_limits(path=None):
    """Read ~/.claude/orch/limits.json (or ORCH_LIMITS_FILE, or `path` for
    tests). Never raises; degrades to available:false. See SS J."""
    empty = {
        "available": False,
        "five_hour": {"used": None, "resets_at": None},
        "seven_day": {"used": None, "resets_at": None},
        "age_s": 0,
        "stale": False,
    }
    if path is None:
        path = os.environ.get("ORCH_LIMITS_FILE") or os.path.expanduser(
            "~/.claude/orch/limits.json"
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    rl = data.get("rate_limits")
    written_at = data.get("_written_at")
    if not isinstance(rl, dict) or not isinstance(written_at, (int, float)):
        return empty
    try:
        five = rl["five_hour"]
        seven = rl["seven_day"]
        result = {
            "available": True,
            "five_hour": {
                "used": five.get("used_percentage"),
                "resets_at": five.get("resets_at"),
            },
            "seven_day": {
                "used": seven.get("used_percentage"),
                "resets_at": seven.get("resets_at"),
            },
        }
    except (KeyError, AttributeError, TypeError):
        return empty
    age_s = int(time.time() - written_at)
    result["age_s"] = age_s
    result["stale"] = age_s > 1800
    return result
