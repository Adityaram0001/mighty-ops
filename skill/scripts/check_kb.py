#!/usr/bin/env python3
"""check_kb.py -- validate the mighty-ops knowledge base's own structure.

Usage: check_kb.py [--project .] [--kb DIR] [--strict] [--quick] [--record] [--json]

Rule codes E01-E12 (errors) and W01-W07 (warnings; W05 unused) are listed in
docs/design.md of the source repository. Exit codes:
0 (clean, warnings allowed unless --strict), 1 (errors, or warnings under
--strict), 2 (no KB found).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kblib

VALID_STATUS_WORDS = ("active", "split", "merged", "retired")
VALID_KINDS = ("feature", "cross-cutting", "infra", "data")
VALID_HEALTH = ("green", "amber", "red", "unknown")
VALID_DR_STATUS_PREFIXES = ("proposed", "accepted", "rejected", "superseded by")

SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    # Not preceded by a slug character (so `ask-which-...` is not a key), and
    # needs one unbroken run of 16+ key characters (a kebab slug has none).
    ("api-key", re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]*[A-Za-z0-9_]{16}")),
    ("github-token", re.compile(r"ghp_[A-Za-z0-9]{30,}")),
    ("slack-token", re.compile(r"xox[bp]-")),
]
DIGIT_RUN_RX = re.compile(r"\b\d{13,19}\b")


def resolve_kb_dir(project, kb_arg):
    """Find the KB dir to check, even if its state.json is missing or
    broken (that is E01's job to report, not a reason to exit 2 here)."""
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


def luhn_ok(digits):
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iter_kb_files(kb):
    for root, dirs, files in os.walk(kb):
        dirs[:] = sorted(dirs)
        for f in sorted(files):
            if f == "state.json":
                continue
            full = os.path.join(root, f)
            if f.endswith(".md"):
                yield full


DR_INDEX_RX = r"^- (DR-\d+) \("


def count_entries(path):
    """Entry ids in a system file. decisions.md has no `### ID` entries; its
    entries are DR index lines (decision-record.md), and a status change
    appends a second line for the same DR, so those ids are deduplicated."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return [], ""
    if os.path.basename(path) == "decisions.md":
        text_nc = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        ids = sorted(set(re.findall(DR_INDEX_RX, text_nc, re.M)))
        return ids, text
    ids = re.findall(kblib.ENTRY_RX, text, re.M)
    return ids, text


class Checker:
    def __init__(self, project, kb, args):
        self.project = project
        self.kb = kb
        self.args = args
        self.errors = []
        self.warnings = []
        self.st = None

    def add_error(self, code, path, msg):
        self.errors.append({"code": code, "path": path, "msg": msg})

    def add_warning(self, code, path, msg):
        self.warnings.append({"code": code, "path": path, "msg": msg})

    def run(self):
        if not self.load_state():
            return
        self.check_e03_e04()
        if self.args.quick:
            self._dr_count = len(self.dr_files())
            return True
        self.check_e11()
        self.check_e05_e09_and_dr_count()
        self.check_e07_e08_w07()
        self.check_e10()
        self.check_e12()
        self.check_e06_w02_w06()
        self.check_w01()
        self.check_w03()
        self.check_w04()
        return True

    def load_state(self):
        state_path = os.path.join(self.kb, "state.json")
        rel = os.path.relpath(state_path, self.project)
        if not os.path.isfile(state_path):
            self.add_error("E01", rel, "state.json missing")
            return False
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError as e:
            self.add_error("E01", rel, "cannot read state.json: %s" % e)
            return False
        try:
            data = json.loads(raw)
        except ValueError as e:
            self.add_error("E01", rel, "invalid JSON: %s" % e)
            return False
        if not isinstance(data, dict):
            self.add_error("E01", rel, "state.json is not an object")
            return False

        required_keys = {
            "schema": str,
            "kb_dir": str,
            "systems": list,
            "counters": dict,
        }
        bad = False
        if data.get("schema") != kblib.SCHEMA:
            self.add_error("E02", rel, "schema != %s" % kblib.SCHEMA)
            bad = True
        for key, typ in required_keys.items():
            if key not in data:
                self.add_error("E02", rel, "missing key: %s" % key)
                bad = True
            elif not isinstance(data[key], typ):
                self.add_error("E02", rel, "wrong type for key: %s" % key)
                bad = True
        self.st = data
        return not bad

    def check_e03_e04(self):
        for sysdef in self.st.get("systems", []):
            sid = sysdef.get("id")
            if sysdef.get("status") not in ("active",):
                continue
            folder = os.path.join(self.kb, "systems", sid)
            if not os.path.isdir(folder):
                self.add_error("E03", "systems/%s" % sid, "no systems/%s/ folder" % sid)
                continue
            for fname in kblib.REQUIRED_FILES:
                if not os.path.isfile(os.path.join(folder, fname)):
                    self.add_error("E04", "systems/%s" % sid, "missing %s" % fname)

    def check_e11(self):
        for sysdef in self.st.get("systems", []):
            sid = sysdef.get("id")
            if sysdef.get("kind") not in VALID_KINDS:
                self.add_error("E11", "systems/%s" % sid, "kind out of enum: %r" % (sysdef.get("kind"),))
            status = sysdef.get("status")
            status_ok = status in VALID_STATUS_WORDS
            if not status_ok:
                self.add_error("E11", "systems/%s" % sid, "status out of enum: %r" % (status,))
            if sysdef.get("health") not in VALID_HEALTH:
                self.add_error("E11", "systems/%s" % sid, "health out of enum: %r" % (sysdef.get("health"),))

    def dr_files(self):
        d = os.path.join(self.kb, "decisions")
        if not os.path.isdir(d):
            return []
        return [f for f in sorted(os.listdir(d)) if f.endswith(".md")]

    def check_e05_e09_and_dr_count(self):
        dr_ids = set()
        for fname in self.dr_files():
            path = os.path.join(self.kb, "decisions", fname)
            rel = os.path.relpath(path, self.project)
            m = re.match(r"(DR-\d+)-", fname)
            if m:
                dr_ids.add(m.group(1))
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            if not re.search(r"^- Date: \d{4}-\d{2}-\d{2}", text, re.M):
                self.add_error("E05", rel, "missing '- Date: YYYY-MM-DD'")
                continue
            status_m = re.search(r"^- Status: (.+)$", text, re.M)
            if not status_m or not any(
                status_m.group(1).strip().startswith(p) for p in VALID_DR_STATUS_PREFIXES
            ):
                self.add_error("E05", rel, "missing or invalid '- Status:'")
                continue
            reason_m = re.search(r"^## Reason\s*\n(.*?)(\n## |\Z)", text, re.M | re.S)
            if not reason_m or not reason_m.group(1).strip():
                self.add_error("E05", rel, "empty or missing '## Reason'")
        self._dr_ids = dr_ids
        self._dr_count = len(self.dr_files())

        for sysdef in self.st.get("systems", []):
            sid = sysdef.get("id")
            path = os.path.join(self.kb, "systems", sid, "decisions.md")
            if not os.path.isfile(path):
                continue
            rel = os.path.relpath(path, self.project)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            text_nc = re.sub(r"<!--.*?-->", "", text, flags=re.S)
            for m in re.finditer(r"\.\./\.\./decisions/(DR-\d+-[^\s)]+)\.md", text_nc):
                link_name = m.group(1)
                target = os.path.join(self.kb, "decisions", link_name + ".md")
                if not os.path.isfile(target):
                    self.add_error("E09", rel, "dangling DR link: %s" % link_name)

    def check_e07_e08_w07(self):
        for sysdef in self.st.get("systems", []):
            sid = sysdef.get("id")
            folder = os.path.join(self.kb, "systems", sid)
            if not os.path.isdir(folder):
                continue
            recorded = sysdef.get("counts", {}) or {}
            for fname in kblib.REQUIRED_FILES:
                if fname == "vision.md":
                    continue
                path = os.path.join(folder, fname)
                if not os.path.isfile(path):
                    continue
                rel = os.path.relpath(path, self.project)
                ids, text = count_entries(path)
                seen = set()
                for eid in ids:
                    if eid in seen:
                        self.add_error("E08", rel, "duplicate entry id: %s" % eid)
                    seen.add(eid)
                key = fname[:-3]
                want = recorded.get(key)
                if isinstance(want, int) and len(seen) < want:
                    self.add_error(
                        "E07",
                        rel,
                        "entry count %d below recorded %d (possible deletion)" % (len(seen), want),
                    )
                for block in re.split(r"(?=^### [A-Z]+-\d+ )", text, flags=re.M)[1:]:
                    if "- Since:" not in block:
                        self.add_warning("W07", rel, "entry missing 'Since:' line")
                    if "- Status:" not in block:
                        self.add_warning("W07", rel, "entry missing 'Status:' line")

    def check_e10(self):
        for path in iter_kb_files(self.kb):
            rel = os.path.relpath(path, self.project)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            for name, rx in SECRET_PATTERNS:
                if rx.search(text):
                    self.add_error("E10", rel, "secret-like content (%s)" % name)
            for m in DIGIT_RUN_RX.finditer(text):
                if luhn_ok(m.group(0)):
                    self.add_error("E10", rel, "secret-like content (card-like number)")

    def check_e12(self):
        pending = self.st.get("pending_sync")
        if not pending:
            return
        rel = os.path.relpath(os.path.join(self.kb, "state.json"), self.project)
        systems = set(pending.get("systems", []) or [])
        done = set(pending.get("systems_done", []) or [])
        if not done <= systems:
            self.add_error("E12", rel, "pending_sync.systems_done not subset of systems")

    def check_e06_w02_w06(self):
        rel = os.path.relpath(os.path.join(self.kb, "state.json"), self.project)
        is_git = kblib.is_git_repo(self.project)
        if not is_git:
            self.add_warning("W06", rel, "git checks skipped (not a git repo)")
            return
        last = self.st.get("last_synced_commit")
        if last:
            rc, _ = kblib.git(self.project, "cat-file", "-e", "%s^{commit}" % last)
            if rc != 0:
                self.add_error("E06", rel, "last_synced_commit unknown to git: %s" % last)
                return
            kb_rel = os.path.relpath(self.kb, self.project)
            rc, out = kblib.git(
                self.project, "rev-list", "--count", "%s..HEAD" % last, "--", ".", ":(exclude)%s" % kb_rel
            )
            if rc == 0:
                try:
                    n = int(out.strip())
                except ValueError:
                    n = 0
                if n > 0:
                    self.add_warning("W02", rel, "KB behind HEAD by %d non-KB commits" % n)

    def check_w01(self):
        systems_dir = os.path.join(self.kb, "systems")
        if not os.path.isdir(systems_dir):
            return
        known = {s.get("id") for s in self.st.get("systems", [])}
        for name in sorted(os.listdir(systems_dir)):
            full = os.path.join(systems_dir, name)
            if os.path.isdir(full) and name not in known:
                self.add_warning("W01", "systems/%s" % name, "folder not listed in state (orphan)")

    def check_w03(self):
        inbox_dir = os.path.join(self.kb, "inbox")
        if not os.path.isdir(inbox_dir):
            return
        import time

        now = time.time()
        for name in sorted(os.listdir(inbox_dir)):
            if not name.endswith(".md"):
                continue
            path = os.path.join(inbox_dir, name)
            rel = os.path.relpath(path, self.project)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            m = re.search(r"Written: (\d{4}-\d{2}-\d{2})", text)
            if not m:
                continue
            try:
                t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d"))
            except ValueError:
                continue
            if (now - t) > 14 * 86400:
                self.add_warning("W03", rel, "inbox message older than 14 days")

    def check_w04(self):
        for path in iter_kb_files(self.kb):
            rel = os.path.relpath(path, self.project)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    n = sum(1 for _ in f)
            except OSError:
                continue
            if n > 400:
                self.add_warning("W04", rel, "file is %d lines (summarise or split)" % n)

    def record(self):
        for sysdef in self.st.get("systems", []):
            sid = sysdef.get("id")
            folder = os.path.join(self.kb, "systems", sid)
            if not os.path.isdir(folder):
                continue
            counts = {}
            for fname in kblib.REQUIRED_FILES:
                if fname == "vision.md":
                    continue
                path = os.path.join(folder, fname)
                if not os.path.isfile(path):
                    counts[fname[:-3]] = 0
                    continue
                ids, _ = count_entries(path)
                counts[fname[:-3]] = len(set(ids))
            sysdef["counts"] = counts
        self.st["health"] = self.st.get("health", {}) or {}
        self.st["health"]["kb_check"] = "clean"
        self.st["health"]["checked_at"] = kblib.now_iso()
        kblib.save_state(self.kb, self.st)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="check_kb.py",
        description="Validate the mighty-ops knowledge base's own structure (see reference/kb-layout.md and decision-record.md).",
    )
    parser.add_argument("--project", default=".")
    parser.add_argument("--kb", default=None)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    project = os.path.abspath(args.project)
    kb = resolve_kb_dir(project, args.kb)
    if not kb or not os.path.isdir(kb):
        print("error: KB not found", file=sys.stderr)
        return 2

    checker = Checker(project, kb, args)
    checker.run()

    n_systems = len(checker.st.get("systems", [])) if checker.st else 0
    n_drs = checker._dr_count if hasattr(checker, "_dr_count") else len(checker.dr_files())

    if args.json:
        print(
            json.dumps(
                {
                    "errors": checker.errors,
                    "warnings": checker.warnings,
                    "systems": n_systems,
                    "drs": n_drs,
                }
            )
        )
    else:
        for e in checker.errors:
            print("ERROR %s %s: %s" % (e["code"], e["path"], e["msg"]))
        for w in checker.warnings:
            print("WARNING %s %s: %s" % (w["code"], w["path"], w["msg"]))
        print(
            "check_kb: %d errors, %d warnings (%d systems, %d DRs)"
            % (len(checker.errors), len(checker.warnings), n_systems, n_drs)
        )

    if checker.errors:
        return 1
    if args.record:
        checker.record()
    if args.strict and checker.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
