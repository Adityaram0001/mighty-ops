#!/usr/bin/env python3
"""catchup.py -- bring the mighty-ops KB's view of the project up to date
with the commits that landed since `last_synced_commit`.

Usage:
  catchup.py [--project .] [--kb DIR] [--to REV] [--max-files 40]
             [--max-files-per-system 10] [--max-subjects 30] [--dry-run]
             [--json] [--limits-file PATH]
  catchup.py --done ID[,ID...]
  catchup.py --mark-synced [--force]

See reference/catchup-protocol.md. stdlib only. Exit codes: 0 ok, 2 usage
error / KB not found / unknown --done id, 3 not a git repo, 4 no baseline,
5 baseline lost, 7 --mark-synced with systems not done.
"""
import argparse
import fnmatch
import json
import os
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kblib

DEFAULT_NOISE = ["orchestration/"]


def err(msg):
    print("error: %s" % msg, file=sys.stderr)


def norm(p):
    return p.replace(os.sep, "/")


def resolve_kb_dir(project, kb_arg):
    """Find the KB dir even if its state.json is missing or broken, so a
    broken KB is diagnosable rather than reported as simply absent."""
    if kb_arg:
        return os.path.join(project, kb_arg)
    kb = kblib.find_kb(project)
    if kb:
        return kb
    claude_md = os.path.join(project, "CLAUDE.md")
    if os.path.isfile(claude_md):
        try:
            with open(claude_md, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            text = ""
        m = kblib._POINTER_RX.search(text)
        if m:
            candidate = os.path.join(project, m.group(1).rstrip("/"))
            if os.path.isdir(candidate):
                return candidate
    default = os.path.join(project, "mighty-ops")
    if os.path.isdir(default):
        return default
    return None


def load_state_or_none(kb):
    try:
        return kblib.load_state(kb), None
    except ValueError as e:
        return None, str(e)


# ------------------------------------------------------------- git parsing --

def parse_numstat_log(out):
    commits = []
    cur = None
    for line in out.splitlines():
        if line.startswith("@@"):
            if cur is not None:
                commits.append(cur)
            parts = line[2:].split("\t", 2)
            cur = {
                "sha": parts[0] if len(parts) > 0 else "",
                "date": parts[1] if len(parts) > 1 else "",
                "subject": parts[2] if len(parts) > 2 else "",
                "files": [],
            }
        elif line.strip() and cur is not None:
            bits = line.split("\t")
            if len(bits) == 3:
                added_s, deleted_s, path = bits
                added = 0 if added_s == "-" else int(added_s)
                deleted = 0 if deleted_s == "-" else int(deleted_s)
                cur["files"].append({"path": norm(path), "added": added, "deleted": deleted})
    if cur is not None:
        commits.append(cur)
    return commits


def log_range(project, frm, to):
    rc, out = kblib.git(
        project, "log", "--no-renames", "--numstat",
        "--format=@@%H\t%ad\t%s", "--date=short", "%s..%s" % (frm, to),
    )
    if rc != 0:
        return []
    return parse_numstat_log(out)


def git_show_text(project, rev, path):
    rc, out = kblib.git(project, "show", "%s:%s" % (rev, path))
    if rc != 0:
        return None
    return out


# ------------------------------------------------------------ classification --

def classify_path(path, systems, kb_dir, noise, is_test_file):
    kb_dir_norm = (kb_dir or "").rstrip("/")
    if kb_dir_norm and (path == kb_dir_norm or path.startswith(kb_dir_norm + "/")):
        return "(kb)"
    for n in noise or []:
        nn = n.rstrip("/")
        if path == nn or path.startswith(nn + "/"):
            return "(noise:%s)" % n
    if path.startswith(".claude/skills/"):
        return "(skills)"
    if is_test_file:
        best_id, best_len = None, -1
        for s in systems:
            for p in s.get("tests", []) or []:
                if "*" in p:
                    if fnmatch.fnmatch(path, p):
                        matched = len(p)
                    else:
                        continue
                else:
                    pn = p.rstrip("/")
                    if path == pn or path.startswith(pn + "/"):
                        matched = len(pn)
                    else:
                        continue
                if matched > best_len:
                    best_len, best_id = matched, s["id"]
        if best_id:
            return best_id
        base = os.path.basename(path)
        for s in systems:
            if re.search(r"test_%s(_|[.\-])" % re.escape(s["id"]), base):
                return s["id"]
        return "(tests-unmapped)"
    return kblib.system_for_path(path, systems, kb_dir, noise)


def is_noise_or_kb(bucket):
    return bucket == "(kb)" or bucket.startswith("(noise:")


def display_bucket(bucket):
    if bucket.startswith("(noise:"):
        return "orchestration"
    if bucket == "(skills)":
        return "skills"
    if bucket in ("(unmapped)", "(tests-unmapped)"):
        return "unmapped"
    return bucket


# ----------------------------------------------------------- regression probes --

MAX_COMMITS_PER_TEST_FILE = 20


def test_fn_drops(project, frm, path, shas):
    """Walk `path` through frm and each in-window commit that touched it
    (oldest first) and return every step where test functions dropped or the
    file vanished. Comparing only the window's endpoints misses a file added
    then trimmed inside one window."""
    drops = []
    prev = git_show_text(project, frm, path)
    for sha in shas:
        cur = git_show_text(project, sha, path)
        n_prev = kblib.count_test_fns(prev) if prev else 0
        n_cur = kblib.count_test_fns(cur) if cur else 0
        if prev is not None and cur is None:
            drops.append("deleted in %s (had %d)" % (sha[:7], n_prev))
        elif n_cur < n_prev:
            drops.append("test functions %d → %d (−%d) in %s" % (n_prev, n_cur, n_prev - n_cur, sha[:7]))
        prev = cur
    return drops


def regression_flags(project, frm, to, by_bucket, kb, max_files, commits=None):
    flags = []
    test_paths = []
    for bucket, rec in by_bucket.items():
        if is_noise_or_kb(bucket):
            continue
        for path in rec["files"]:
            if kblib.is_test_path(path):
                test_paths.append((bucket, path))
    touched_by = defaultdict(list)
    for c in reversed(commits or []):
        for fobj in c["files"]:
            touched_by[fobj["path"]].append(c["sha"])
    for bucket, path in test_paths[:max_files]:
        before = git_show_text(project, frm, path)
        after = git_show_text(project, to, path)
        n_before = kblib.count_test_fns(before) if before else 0
        if before is not None and after is None:
            flags.append({
                "kind": "tests-deleted", "path": path, "system": bucket,
                "detail": "test file deleted (had %d test fns)" % n_before,
            })
            continue
        shas = touched_by.get(path, [])[-MAX_COMMITS_PER_TEST_FILE:]
        if not shas or shas[-1] != to:
            shas = shas + [to]
        drops = test_fn_drops(project, frm, path, shas)
        if drops:
            flags.append({
                "kind": "tests", "path": path, "system": bucket,
                "detail": "; ".join(drops),
            })

    harmony_path = os.path.join(kb, "harmony.md")
    harmony_cited_paths = {}
    if os.path.isfile(harmony_path):
        try:
            with open(harmony_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.startswith("|"):
                        continue
                    for m in re.finditer(r"`([^`]+)`", line):
                        harmony_cited_paths[m.group(1).strip()] = line.strip()
        except OSError:
            pass
    for bucket, rec in by_bucket.items():
        if is_noise_or_kb(bucket):
            continue
        for path in rec["files"]:
            for cited, row in harmony_cited_paths.items():
                cited_norm = cited.rstrip("/")
                if path == cited_norm or path.startswith(cited_norm + "/"):
                    flags.append({
                        "kind": "harmony", "path": path, "system": bucket,
                        "detail": "touches a harmony.md contract row: %s" % row[:100],
                    })

    return flags


def cross_cutting_flags(by_bucket, systems):
    flags = []
    by_id = {s["id"]: s for s in systems}
    for bucket in by_bucket:
        if is_noise_or_kb(bucket):
            continue
        s = by_id.get(bucket)
        if s and s.get("kind") == "cross-cutting":
            flags.append({
                "kind": "cross-cutting", "path": "", "system": bucket,
                "detail": "cross-cutting system changed; consumers go amber until re-verified",
            })
    return flags


# -------------------------------------------------------------------- budget --

def fmt_budget(limits):
    if not limits.get("available"):
        return "Budget: unknown (no orch limits data)"

    def pct(d):
        u = d.get("used")
        return "%.1f%%" % u if isinstance(u, (int, float)) else "unknown"

    def reset(ts, fmt):
        if not ts:
            return ""
        try:
            return " (resets %s)" % time.strftime(fmt, time.localtime(ts))
        except (OSError, ValueError, OverflowError):
            return ""

    five = limits.get("five_hour", {})
    seven = limits.get("seven_day", {})
    return "Budget: five_hour %s%s, seven_day %s%s" % (
        pct(five), reset(five.get("resets_at"), "%H:%M"),
        pct(seven), reset(seven.get("resets_at"), "%a %H:%M"),
    )


# -------------------------------------------------------------- orchestration --

def orchestration_section(project, frm, to, by_bucket):
    out = {"files": 0, "plan_changed": False, "handoff_changed": False, "new_results": []}
    for bucket, rec in by_bucket.items():
        if bucket.startswith("(noise:"):
            out["files"] += len(rec["files"])
            if any(p.endswith("plan.md") for p in rec["files"]):
                out["plan_changed"] = True
            if any(p.endswith("handoff.md") for p in rec["files"]):
                out["handoff_changed"] = True
    rc, log_out = kblib.git(
        project, "log", "--diff-filter=A", "--name-only", "--format=",
        "%s..%s" % (frm, to), "--", "orchestration/workers",
    )
    if rc == 0:
        names = sorted({norm(l.strip()) for l in log_out.splitlines() if l.strip().endswith("/result.md")})
        ids = []
        for n in names:
            parts = n.split("/")
            if len(parts) >= 3:
                ids.append(parts[2])
        out["new_results"] = sorted(set(ids))[:10]
    return out


# -------------------------------------------------------------------- report --

def build_report(data):
    lines = []
    lines.append(
        "# Catch-up %s..%s — %d commits (%d incl. noise), %s..%s"
        % (data["from"][:7], data["to"][:7], data["commits"], data["commits_total"], data["date1"], data["date2"])
    )
    lines.append(data["budget_line"])
    lines.append("Status: %s" % data["status"])

    lines.append("## Regression flags")
    if data["regression_flags"]:
        for fl in data["regression_flags"]:
            if fl["kind"] in ("tests", "tests-deleted"):
                lines.append("- tests: %s %s [%s]" % (fl["path"], fl["detail"], fl["system"]))
            elif fl["kind"] == "harmony":
                lines.append("- harmony: %s %s [%s]" % (fl["path"], fl["detail"], fl["system"]))
            else:
                lines.append("- cross-cutting: %s %s" % (fl["system"], fl["detail"]))
    else:
        lines.append("(none)")

    lines.append("## Changed systems")
    lines.append("| system | commits | files | +/- | top files |")
    lines.append("|---|---|---|---|---|")
    for row in data["systems"]:
        lines.append("| %s | %d | %d | +%d/-%d | %s |" % (
            row["id"], row["commits"], len(row["files"]), row["added"], row["deleted"],
            ", ".join(row["top_files"]),
        ))

    lines.append("## Project skills")
    if data["skills"]:
        for p in data["skills"]:
            lines.append("- %s" % p)
    else:
        lines.append("(none)")

    lines.append("## Orchestration (separated)")
    orch = data["orchestration"]
    lines.append(
        "- files: %d · plan.md: %s · handoff.md: %s · new worker results: %s"
        % (
            orch["files"],
            "changed" if orch["plan_changed"] else "unchanged",
            "changed" if orch["handoff_changed"] else "unchanged",
            ", ".join(orch["new_results"]) if orch["new_results"] else "(none)",
        )
    )

    lines.append("## Unmapped paths / new-system candidates")
    if data["unmapped"] or data["new_system_candidates"]:
        for p in data["unmapped"][:20]:
            lines.append("- (unmapped) %s" % p)
        for c in data["new_system_candidates"]:
            lines.append("- candidate: %s" % c)
    else:
        lines.append("(none)")

    lines.append("## Read list")
    if data["read_list"]:
        for r in data["read_list"]:
            lines.append("- [%s] %s" % (r["system"], r["path"]))
    else:
        lines.append("(none)")

    lines.append("## Commits")
    if data["commits_total"] > 200:
        lines.append("(>200 commits in range; subjects suppressed. Use a chunked catch-up.)")
    elif data["subjects"]:
        for c in data["subjects"]:
            lines.append("- %s %s [%s] %s" % (c["sha"][:7], c["date"], ", ".join(c["systems"]), c["subject"]))
    else:
        lines.append("(none)")

    lines.append("## Next")
    if data["status"] == "up_to_date":
        lines.append("- nothing to do; the KB is up to date")
    else:
        ids = ", ".join(data["pending_systems"]) if data["pending_systems"] else "<ids>"
        lines.append(
            "- run the update order of catchup-protocol.md §3; "
            "then `catchup.py --done %s`; then `--mark-synced`" % ids
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main run --

def do_default(args, project):
    kb = resolve_kb_dir(project, args.kb)
    if not kb or not os.path.isdir(kb):
        err("KB not found")
        return 2
    st, load_err = load_state_or_none(kb)
    if st is None:
        err("KB at %s: %s" % (kb, load_err))
        return 2

    if not kblib.is_git_repo(project):
        err("not a git repo")
        return 3

    pending = st.get("pending_sync")
    old_to = pending["to"] if pending else None
    old_systems_done = set(pending.get("systems_done", []) or []) if pending else set()
    frm = pending["from"] if pending else st.get("last_synced_commit")
    if not frm:
        # Still print the budget: during a first run (no baseline yet) this
        # is the budget source when `orch limits` is unavailable.
        line = fmt_budget(kblib.read_limits(args.limits_file))
        print(json.dumps({"budget_line": line}) if args.json else line)
        err("no baseline: finish init (first_run) or run --mark-synced")
        return 4

    if args.to:
        rc, out = kblib.git(project, "rev-parse", args.to)
        if rc != 0:
            err("cannot resolve --to %s" % args.to)
            return 2
        to = out.strip()
    else:
        to = kblib.head(project)
        if not to:
            err("cannot resolve HEAD")
            return 3

    rc, _ = kblib.git(project, "cat-file", "-e", "%s^{commit}" % frm)
    if rc != 0:
        err("baseline lost: %s not found in history" % frm)
        return 5
    rc, _ = kblib.git(project, "merge-base", "--is-ancestor", frm, to)
    if rc != 0:
        rc2, mb_out = kblib.git(project, "merge-base", frm, to)
        if rc2 == 0 and mb_out.strip():
            frm = mb_out.strip()
        else:
            err("baseline lost: no merge-base between %s and %s" % (frm, to))
            return 5

    systems = st.get("systems", []) or []
    kb_dir_name = st.get("kb_dir") or os.path.basename(kb.rstrip("/"))
    noise = st.get("noise_paths") or list(DEFAULT_NOISE)
    known_ids = {s["id"] for s in systems}

    commits = log_range(project, frm, to)
    commits_total = len(commits)

    by_bucket = defaultdict(lambda: {"commits": set(), "files": defaultdict(lambda: {"added": 0, "deleted": 0})})
    commit_systems = {}
    commit_nonnoise = {}
    for c in commits:
        touched = set()
        nonnoise = False
        for fobj in c["files"]:
            path = fobj["path"]
            is_t = kblib.is_test_path(path)
            bucket = classify_path(path, systems, kb_dir_name, noise, is_t)
            if bucket == "(kb)":
                continue
            touched.add(bucket)
            rec = by_bucket[bucket]
            rec["commits"].add(c["sha"])
            frec = rec["files"][path]
            frec["added"] += fobj["added"]
            frec["deleted"] += fobj["deleted"]
            if not is_noise_or_kb(bucket):
                nonnoise = True
        commit_systems[c["sha"]] = touched
        commit_nonnoise[c["sha"]] = nonnoise

    commits_nonnoise = [c for c in commits if commit_nonnoise.get(c["sha"])]
    commits_count = len(commits_nonnoise)

    flags = []
    if commits_count:
        flags += regression_flags(project, frm, to, by_bucket, kb, 40, commits)
        flags += cross_cutting_flags(by_bucket, systems)

    nonnoise_files = set()
    for bucket, rec in by_bucket.items():
        if not is_noise_or_kb(bucket):
            nonnoise_files |= set(rec["files"])

    limits = kblib.read_limits(args.limits_file)
    if commits_count == 0 and not flags:
        status = "up_to_date"
        if not args.dry_run:
            st["last_synced_commit"] = to
            st["last_synced_at"] = kblib.now_iso()
            st["pending_sync"] = None
            st["updated_at"] = kblib.now_iso()
            kblib.save_state(kb, st)
        data = {
            "from": frm, "to": to, "commits": 0, "commits_total": commits_total,
            "status": status, "date1": "-", "date2": "-",
            "budget": limits, "budget_line": fmt_budget(limits),
            "regression_flags": [], "systems": [], "skills": [],
            "orchestration": {"files": 0, "plan_changed": False, "handoff_changed": False, "new_results": []},
            "unmapped": [], "new_system_candidates": [], "read_list": [],
            "subjects": [], "pending_systems": [],
        }
        emit(args, data, None)
        return 0

    if commits_count > 30 or len(nonnoise_files) > 40:
        status = "provisional-candidate"
    else:
        status = "behind"

    changed_system_ids = sorted(b for b in by_bucket if b in known_ids)
    changed_systems_rows = []
    read_list = []
    for sid in sorted(changed_system_ids, key=lambda s: -sum(
        v["added"] + v["deleted"] for v in by_bucket[s]["files"].values()
    )):
        rec = by_bucket[sid]
        added = sum(v["added"] for v in rec["files"].values())
        deleted = sum(v["deleted"] for v in rec["files"].values())
        ranked = sorted(
            rec["files"].items(),
            key=lambda kv: (kblib.is_test_path(kv[0]), -(kv[1]["added"] + kv[1]["deleted"])),
        )
        top_files = [p for p, _ in ranked[:3]]
        files_detail = [{"path": p, "added": v["added"], "deleted": v["deleted"]} for p, v in rec["files"].items()]
        changed_systems_rows.append({
            "id": sid, "commits": len(rec["commits"]), "files": files_detail,
            "added": added, "deleted": deleted, "top_files": top_files,
        })
        for p, _ in ranked[: args.max_files_per_system]:
            read_list.append({"system": sid, "path": p})
    read_list = read_list[: args.max_files]

    skills_files = sorted(by_bucket.get("(skills)", {}).get("files", {}).keys())
    unmapped_paths = sorted(by_bucket.get("(unmapped)", {}).get("files", {}).keys())
    tests_unmapped_paths = sorted(by_bucket.get("(tests-unmapped)", {}).get("files", {}).keys())
    all_unmapped = unmapped_paths + tests_unmapped_paths

    new_candidates = set()
    for p in all_unmapped:
        top = p.split("/")[0]
        new_candidates.add(top)
        base = os.path.basename(p)
        if base in ("__init__.py", "package.json"):
            d = os.path.dirname(p)
            new_candidates.add(d if d else top)

    orch = orchestration_section(project, frm, to, by_bucket)

    subjects = []
    for c in commits_nonnoise[: args.max_subjects]:
        systems_touched = sorted(display_bucket(b) for b in commit_systems[c["sha"]])
        subjects.append({"sha": c["sha"], "date": c["date"], "subject": c["subject"], "systems": systems_touched})

    dates = [c["date"] for c in commits if c["date"]]
    date1 = dates[-1] if dates else "-"
    date2 = dates[0] if dates else "-"

    date_str = time.strftime("%Y%m%d", time.gmtime())
    digest_rel = os.path.join("digests", "catchup-%s-%s.md" % (date_str, to[:7]))

    data = {
        "from": frm, "to": to, "commits": commits_count, "commits_total": commits_total,
        "status": status, "date1": date1, "date2": date2,
        "budget": limits, "budget_line": fmt_budget(limits),
        "regression_flags": flags, "systems": changed_systems_rows,
        "skills": skills_files, "orchestration": orch,
        "unmapped": all_unmapped, "new_system_candidates": sorted(new_candidates),
        "read_list": read_list, "subjects": subjects,
        "pending_systems": changed_system_ids,
    }

    if not args.dry_run:
        reopened = set()
        if pending and old_to:
            extra = log_range(project, old_to, to)
            for c in extra:
                for fobj in c["files"]:
                    is_t = kblib.is_test_path(fobj["path"])
                    bucket = classify_path(fobj["path"], systems, kb_dir_name, noise, is_t)
                    if bucket in old_systems_done:
                        reopened.add(bucket)
        systems_done = sorted((old_systems_done - reopened) & set(changed_system_ids))

        digest_path = os.path.join(kb, digest_rel)
        os.makedirs(os.path.dirname(digest_path), exist_ok=True)
        with open(digest_path, "w", encoding="utf-8") as f:
            f.write(build_report(data))

        st["pending_sync"] = {
            "from": frm, "to": to, "created_at": kblib.now_iso(),
            "systems": changed_system_ids, "systems_done": systems_done,
            "digest": norm(digest_rel), "regression_flags": flags,
        }
        st["updated_at"] = kblib.now_iso()
        kblib.save_state(kb, st)
        emit(args, data, digest_path)
    else:
        emit(args, data, None)
    return 0


def emit(args, data, digest_path):
    if args.json:
        print(json.dumps(data))
    else:
        print(build_report(data), end="")


def cmd_done(args, project):
    kb = resolve_kb_dir(project, args.kb)
    if not kb or not os.path.isdir(kb):
        err("KB not found")
        return 2
    st, load_err = load_state_or_none(kb)
    if st is None:
        err("KB at %s: %s" % (kb, load_err))
        return 2
    pending = st.get("pending_sync")
    if not pending:
        err("no pending_sync in progress")
        return 2
    ids = [x.strip() for x in args.done.split(",") if x.strip()]
    for i in ids:
        if i not in pending["systems"]:
            err("unknown id in pending_sync.systems: %s" % i)
            return 2
    done_set = set(pending.get("systems_done", []) or [])
    for i in ids:
        done_set.add(i)
        for s in st["systems"]:
            if s["id"] == i:
                s["last_changed_commit"] = pending["to"]
                s["updated_at"] = kblib.now_iso()
    pending["systems_done"] = sorted(done_set)
    st["updated_at"] = kblib.now_iso()
    kblib.save_state(kb, st)
    if args.json:
        print(json.dumps({"done": ids, "systems_done": pending["systems_done"]}))
    else:
        print("done: %s" % ", ".join(ids))
    return 0


HEALTH_RANK = {"green": 0, "amber": 1, "unknown": 2, "red": 3}


def overall_health(systems):
    """Worst health among active systems (kb-layout.md). `unknown` ranks
    below red but above amber: an unread system cannot make the KB green."""
    active = [s.get("health") or "unknown" for s in systems if s.get("status", "active") == "active"]
    if not active:
        return "unknown"
    return max(active, key=lambda h: HEALTH_RANK.get(h, 2))


def cmd_mark_synced(args, project):
    kb = resolve_kb_dir(project, args.kb)
    if not kb or not os.path.isdir(kb):
        err("KB not found")
        return 2
    st, load_err = load_state_or_none(kb)
    if st is None:
        err("KB at %s: %s" % (kb, load_err))
        return 2
    pending = st.get("pending_sync")
    skipped = []
    if pending:
        missing = [i for i in pending["systems"] if i not in (pending.get("systems_done") or [])]
        if missing and not args.force:
            err("systems not done: %s" % ", ".join(missing))
            return 7
        skipped = missing
        st["last_synced_commit"] = pending["to"]
        st["last_synced_at"] = kblib.now_iso()
        digest_rel = pending.get("digest")
        if digest_rel:
            digest_path = os.path.join(kb, digest_rel)
            if os.path.isfile(digest_path):
                line = "\nMarked synced at %s (last_synced_commit=%s)" % (kblib.now_iso(), pending["to"])
                if skipped:
                    line += "; skipped (--force): %s" % ", ".join(skipped)
                try:
                    with open(digest_path, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except OSError:
                    pass
        st["pending_sync"] = None
    else:
        if not st.get("last_synced_commit"):
            head_ = (st.get("first_run") or {}).get("head") or kblib.head(project)
            st["last_synced_commit"] = head_
            st["last_synced_at"] = kblib.now_iso()
            if (st.get("first_run") or {}).get("status") == "in_progress":
                st["first_run"]["status"] = "done"
                st["first_run"]["finished_at"] = kblib.now_iso()
                passes = st["first_run"].setdefault("passes_done", [])
                if "close" not in passes:
                    passes.append("close")
    st.setdefault("health", {})
    st["health"]["overall"] = overall_health(st.get("systems") or [])
    st["updated_at"] = kblib.now_iso()
    kblib.save_state(kb, st)
    if args.json:
        print(json.dumps({"last_synced_commit": st["last_synced_commit"], "skipped": skipped}))
    else:
        print("mark-synced: last_synced_commit=%s" % st["last_synced_commit"])
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="catchup.py",
        description="Bring the KB up to date with new commits (see reference/catchup-protocol.md).",
    )
    p.add_argument("--project", default=".")
    p.add_argument("--kb", default=None)
    p.add_argument("--to", default=None)
    p.add_argument("--max-files", type=int, default=40)
    p.add_argument("--max-files-per-system", type=int, default=10)
    p.add_argument("--max-subjects", type=int, default=30)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limits-file", default=None)
    p.add_argument("--done", default=None, metavar="ID[,ID...]")
    p.add_argument("--mark-synced", action="store_true")
    p.add_argument("--force", action="store_true")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    project = os.path.abspath(args.project)

    if args.done:
        return cmd_done(args, project)
    if args.mark_synced:
        return cmd_mark_synced(args, project)
    return do_default(args, project)


if __name__ == "__main__":
    sys.exit(main())
