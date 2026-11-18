#!/usr/bin/env python3
"""scorecard.py -- per-run scorecard from orchestration/ artifacts and the KB.

Usage:
  scorecard.py [--project .] [--kb DIR] [--json] [--out PATH]

Prints a markdown `metric | value | source` table (8 metrics; the explore share rides on the units row). With a KB it
also appends ONE row to <kb>/scorecard.md (never rewrites earlier rows) and
writes the full report to <kb>/digests/scorecard-YYYYMMDD-HHMM.md. Without a
KB it only prints. stdlib only. Exit codes: 0 ok, 2 no orchestration/ dir or
--kb given but not a directory.
"""
import argparse
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kblib

MAX_TEST_FILES = 2000
TEST_RX = r"^[[:space:]]*(async[[:space:]]+)?def test_|^[[:space:]]*(it|test)\(|#\[test\]"
HISTORY_HEADER = (
    "# Scorecard history (append-only; one row per run, newest last)\n\n"
    "| date | HEAD | units | cost usd | explore % | resumed | stalled | denials "
    "| questions | re-plans | decide (prov) | tests |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
)


def err(msg):
    print("error: %s" % msg, file=sys.stderr)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def read_json(path):
    t = read_text(path)
    if t is None:
        return None
    try:
        d = json.loads(t)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


# ----------------------------------------------------------------- workers --

def spawn_info(wdir):
    """Role and resume flag from spawns.log (gitignored, so optional)."""
    t = read_text(os.path.join(wdir, "spawns.log"))
    roles, resumes = [], 0
    for m in re.finditer(r"^## spawn .*?role=(\S+).*?resume=(\d+)", t or "", re.M):
        roles.append(m.group(1))
        resumes += int(m.group(2))
    return (roles[0] if roles else None), resumes


def result_status(wdir):
    t = read_text(os.path.join(wdir, "result.md"))
    if not t:
        return None
    m = re.match(r"\s*STATUS:\s*([A-Z_]+)", t)
    return m.group(1) if m else None


def worker_stats(project):
    """One record per worker dir that has run.json. A resume overwrites
    run.json and keeps the earlier run as run.<epoch>.json, so every run of a
    unit is run.json plus run.*.json."""
    units = []
    for wdir in sorted(glob.glob(os.path.join(project, "orchestration", "workers", "*"))):
        cur = os.path.join(wdir, "run.json")
        if not os.path.isfile(cur):
            continue
        runs = [read_json(p) or {} for p in sorted(glob.glob(os.path.join(wdir, "run.*.json")))]
        runs.append(read_json(cur) or {})
        role, spawn_resumes = spawn_info(wdir)
        cost = sum(float(r.get("total_cost_usd") or 0) for r in runs)
        denials = sum(len(r.get("permission_denials") or []) for r in runs)
        max_turns = sum(1 for r in runs if r.get("subtype") == "error_max_turns"
                        or r.get("terminal_reason") == "max_turns")
        units.append({
            "id": os.path.basename(wdir), "role": role, "cost": cost,
            "runs": len(runs), "resumed": len(runs) > 1 or spawn_resumes > 0,
            "denials": denials, "max_turns": max_turns,
            "status": result_status(wdir),
        })
    return units


# ------------------------------------------------------------ text artifacts --

def count_questions(project):
    t = read_text(os.path.join(project, "orchestration", "questions.md"))
    if t is None:
        return None
    opn = ans = 0
    for m in re.finditer(r"^### Q\d+\b.*?[—-]\s*(OPEN|ANSWERED)\b", t, re.M):
        if m.group(1) == "OPEN":
            opn += 1
        else:
            ans += 1
    return opn, ans


def count_replans(project):
    n = 0
    base = os.path.join(project, "orchestration")
    files = [os.path.join(base, "plan.md")] + sorted(glob.glob(os.path.join(base, "archive", "plan_p*.md")))
    for p in files:
        t = read_text(p)
        if not t:
            continue
        m = re.search(r"^## Re-plans[^\n]*\n(.*?)(?=^## |\Z)", t, re.M | re.S)
        if m:
            n += len(re.findall(r"^- 20\d\d-\d\d-\d\d", m.group(1), re.M))
    return n


def decide_stats(kb):
    """(decide calls, provisional ones) from KB exchange records."""
    calls = prov = 0
    for p in sorted(glob.glob(os.path.join(kb, "exchanges", "EX-*.md"))):
        t = read_text(p) or ""
        mode = re.search(r"^- Mode:\s*(\S+)", t, re.M)
        if not mode or mode.group(1) != "decide":
            continue
        calls += 1
        at = re.search(r"^- KB at:.*\(provisional:\s*(yes|no)\)", t, re.M)
        if at and at.group(1) == "yes":
            prov += 1
    return calls, prov


# ---------------------------------------------------------------- test count --

def test_paths_from_state(kb):
    if not kb:
        return []
    try:
        st = kblib.load_state(kb)
    except ValueError:
        return []
    out = []
    for s in st.get("systems", []) or []:
        out += [p for p in (s.get("tests") or []) if isinstance(p, str)]
    return out


def count_tests(project, kb):
    """Test functions at HEAD. Returns (count, scope) or (None, reason)."""
    if not kblib.is_git_repo(project) or not kblib.head(project):
        return None, "no git HEAD"
    paths = test_paths_from_state(kb)
    args = ["grep", "-c", "-E", TEST_RX, "HEAD", "--"] + (paths or ["."])
    rc, out = kblib.git(project, *args)
    if rc not in (0, 1):
        return None, "git grep failed"
    files = []
    for line in out.splitlines():
        name, _, n = line.rpartition(":")
        if name.startswith("HEAD:") and n.isdigit():
            files.append((name[5:], int(n)))
    if not paths:
        files = [(p, n) for p, n in files if kblib.is_test_path(p)]
    files = files[:MAX_TEST_FILES]
    scope = "state.json systems[].tests" if paths else "repo-wide test paths"
    return sum(n for _, n in files), scope


# --------------------------------------------------------------------- build --

def build(project, kb):
    units = worker_stats(project)
    total = sum(u["cost"] for u in units)
    roles_known = [u for u in units if u["role"]]
    explore_cost = sum(u["cost"] for u in roles_known if u["role"] == "explore")
    explore_share = None
    if roles_known and total > 0:
        explore_share = round(100.0 * explore_cost / sum(u["cost"] for u in roles_known), 1)
    stalled = {"MAX_TURNS": sum(u["max_turns"] for u in units),
               "BLOCKED": sum(1 for u in units if u["status"] == "BLOCKED"),
               "FAILED": sum(1 for u in units if u["status"] == "FAILED")}
    q = count_questions(project)
    tests, tscope = count_tests(project, kb)
    dec = decide_stats(kb) if kb else None
    run_src = "orchestration/workers/*/run.json (+ run.*.json)"
    exp_txt = "explore n/a (no spawns.log)" if explore_share is None else "explore %.1f%% of cost" % explore_share
    m = [
        ("units_cost", "units, total cost, explore share",
         "%d units, $%.2f, %s" % (len(units), total, exp_txt),
         run_src + "; role= from workers/*/spawns.log (gitignored)",
         {"units": len(units), "cost_usd": round(total, 4),
          "explore_percent": explore_share, "roles_known": len(roles_known)}),
        ("resumed", "resumed units", str(sum(1 for u in units if u["resumed"])),
         "extra run.*.json beside run.json (resume keeps the old run)",
         {"count": sum(1 for u in units if u["resumed"])}),
        ("stalled", "MAX_TURNS + BLOCKED + FAILED", "%d (%s)" % (
            sum(stalled.values()), ", ".join("%s %d" % kv for kv in stalled.items())),
         "run*.json subtype/terminal_reason; workers/*/result.md line 1",
         dict(stalled, total=sum(stalled.values()))),
        ("denials", "permission denials", str(sum(u["denials"] for u in units)),
         "run*.json permission_denials",
         {"count": sum(u["denials"] for u in units)}),
        ("questions", "human questions",
         "n/a (no questions.md)" if q is None else "%d (OPEN %d, answered %d)" % (q[0] + q[1], q[0], q[1]),
         "orchestration/questions.md",
         {"total": None if q is None else q[0] + q[1], "open": None if q is None else q[0],
          "answered": None if q is None else q[1]}),
        ("replans", "re-plans", str(count_replans(project)),
         "plan.md + archive/plan_p*.md `## Re-plans` dated bullets",
         {"count": count_replans(project)}),
    ]
    if dec is None:
        m.append(("decide", "decide: calls (provisional)", "n/a (no KB)", "<kb>/exchanges/EX-*.md",
                  {"calls": None, "provisional": None}))
    else:
        share = "-" if dec[0] == 0 else "%.0f%%" % (100.0 * dec[1] / dec[0])
        m.append(("decide", "decide: calls (provisional)", "%d (%d provisional, %s)" % (dec[0], dec[1], share),
                  "<kb>/exchanges/EX-*.md `- Mode:` and `- KB at:`",
                  {"calls": dec[0], "provisional": dec[1]}))
    m.append(("tests", "test functions at HEAD",
              "n/a (%s)" % tscope if tests is None else str(tests),
              "git grep at HEAD, %s" % (tscope if tests is not None else "-"),
              {"count": tests}))
    return m


def table(metrics):
    lines = ["| metric | value | source |", "|---|---|---|"]
    for _, name, value, source, _ in metrics:
        lines.append("| %s | %s | %s |" % (name, value, source))
    return "\n".join(lines) + "\n"


def history_row(metrics, head):
    d = {k: data for k, _, _, _, data in metrics}
    exp = d["units_cost"]["explore_percent"]
    dec = d["decide"]
    return "| %s | %s | %d | %.2f | %s | %d | %d | %d | %s | %d | %s | %s |\n" % (
        time.strftime("%Y-%m-%d", time.gmtime()), (head or "-")[:7],
        d["units_cost"]["units"], d["units_cost"]["cost_usd"],
        "-" if exp is None else "%.1f" % exp, d["resumed"]["count"], d["stalled"]["total"],
        d["denials"]["count"], "-" if d["questions"]["total"] is None else d["questions"]["total"],
        d["replans"]["count"],
        "-" if dec["calls"] is None else "%d (%d)" % (dec["calls"], dec["provisional"]),
        "-" if d["tests"]["count"] is None else d["tests"]["count"],
    )


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scorecard.py", description="Per-run scorecard (orchestration/ + KB).")
    ap.add_argument("--project", default=".")
    ap.add_argument("--kb", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    project = os.path.abspath(args.project)

    if not os.path.isdir(os.path.join(project, "orchestration")):
        err("no orchestration/ directory in %s; nothing to score" % project)
        return 2
    kb = None
    if args.kb:
        kb = os.path.join(project, args.kb)
        if not os.path.isdir(kb):
            err("KB not found: %s" % kb)
            return 2
    else:
        kb = kblib.find_kb(project)

    metrics = build(project, kb)
    head = kblib.head(project) if kblib.is_git_repo(project) else None
    stamp = time.strftime("%Y%m%d-%H%M", time.gmtime())
    report = "# Scorecard %s (HEAD %s)\n\n%s" % (stamp, (head or "-")[:7], table(metrics))

    if args.json:
        print(json.dumps({
            "head": head, "kb": bool(kb),
            "metrics": [{"key": k, "metric": n, "value": v, "source": s, "data": d}
                        for k, n, v, s, d in metrics],
        }))
    else:
        print(report, end="")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
    if kb:
        hist = os.path.join(kb, "scorecard.md")
        new = not os.path.isfile(hist)
        with open(hist, "a", encoding="utf-8") as f:
            if new:
                f.write(HISTORY_HEADER)
            f.write(history_row(metrics, head))
        os.makedirs(os.path.join(kb, "digests"), exist_ok=True)
        with open(os.path.join(kb, "digests", "scorecard-%s.md" % stamp), "w", encoding="utf-8") as f:
            f.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
