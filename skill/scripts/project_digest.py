#!/usr/bin/env python3
"""project_digest.py -- a generic map of a project: shape, tree, entry points,
tests, docs, orchestration/skills presence, candidate systems (detected with
the heuristics of reference/first-run-protocol.md; rules 1-4 and 7-8 are
applied here), vertical slices, hubs, edges, signals and a reading plan.

Usage: project_digest.py [--project .] [--max-lines 300] [--json] [--out FILE]
                          [--exclude PREFIX ...]

stdlib only. Exit codes: 0 ok, 2 project path is not a directory.
"""
import argparse
import ast
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kblib

SKIP = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".tox", "target",
    "coverage", ".cache", ".claude",
}
CODE_EXT = {
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".sh", ".go", ".rs",
    ".rb", ".java", ".c", ".cc", ".cpp", ".h", ".hpp",
}
DOC_EXT = {".md", ".rst", ".txt"}
LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".mjs": "JavaScript", ".cjs": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".sh": "Shell", ".go": "Go", ".rs": "Rust",
    ".rb": "Ruby", ".java": "Java", ".c": "C", ".cc": "C++", ".cpp": "C++",
    ".h": "C", ".hpp": "C++", ".md": "Markdown", ".rst": "reST",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
}
COLLECTION = {"bin", "skills", "packages", "apps", "services", "plugins", "cmd", "libs", "crates"}
INFRA_DIRS = {"config", "scripts", "migrations", "deploy", "infra", "docker", ".github", "ci"}
SHARED_NAMES = re.compile(
    r"^(config|settings|utils?|common|shared|core|db|models|paths|ids|types|"
    r"constants|errors|log(ging)?|helpers|lib)$"
)
SLICE_STOPLIST = {
    "base", "common", "utils", "util", "helpers", "types", "models", "core",
    "main", "index", "init", "report", "extract", "config", "test",
}
ENTRY_NAMES = {"__main__.py", "main.py", "cli.py", "server.py", "app.py", "index.js", "main.go"}
MAX_FILE_BYTES = 1024 * 1024

MARKDOWN_CAPS = {
    "Shape": 8,
    "Tree (depth 2)": 40,
    "Entry points": 15,
    "Tests": 10,
    "Docs": 25,
    "Orchestration & skills": 20,
    "Candidate systems": 60,
    "Vertical slices": 10,
    "Hubs & cross-cutting": 10,
    "Top system edges": 10,
    "Signals": 20,
    "Reading plan": 40,
    "Recent activity": 20,
}
SECTION_ORDER = list(MARKDOWN_CAPS.keys())
TRIM_ORDER = ["Signals", "Recent activity", "Top system edges", "Tree (depth 2)"]


def err(msg):
    print("error: %s" % msg, file=sys.stderr)


def norm(p):
    return p.replace(os.sep, "/")


def read_text_capped(path, cap=MAX_FILE_BYTES):
    try:
        if os.path.getsize(path) > cap:
            return ""
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def is_test(rel):
    return kblib.is_test_path(rel)


def ext_of(rel):
    return os.path.splitext(rel)[1].lower()


def is_code_file(root, rel):
    ext = ext_of(rel)
    if ext in CODE_EXT:
        return True
    if "." not in os.path.basename(rel):
        try:
            with open(os.path.join(root, rel), "rb") as f:
                return f.read(2) == b"#!"
        except OSError:
            return False
    return False


SHEBANG_LANGS = [
    (re.compile(r"\b(ba|z|k|da)?sh\b"), "Shell"),
    (re.compile(r"\bpython[0-9.]*\b"), "Python"),
    (re.compile(r"\b(node|deno|bun)\b"), "JavaScript"),
    (re.compile(r"\bruby\b"), "Ruby"),
    (re.compile(r"\bperl\b"), "Perl"),
]


def lang_of(root, rel):
    """Language by extension, else by the shebang of an extensionless file
    (e.g. a bash script in bin/ with no extension)."""
    lang = LANG_BY_EXT.get(ext_of(rel))
    if lang or "." in os.path.basename(rel):
        return lang
    try:
        with open(os.path.join(root, rel), "rb") as f:
            first = f.readline(200).decode("utf-8", "ignore")
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    for rx, name in SHEBANG_LANGS:
        if rx.search(first):
            return name
    return None


def is_doc(rel):
    if ext_of(rel) in DOC_EXT:
        return True
    return rel == "docs" or rel.startswith("docs/")


def category(root, rel):
    if is_test(rel):
        return "tests"
    if is_doc(rel):
        return "docs"
    if is_code_file(root, rel):
        return "source"
    return "meta"


# ---------------------------------------------------------------- walking --

def walk_files(root, exclude_prefixes):
    """Walk `root`, pruning SKIP dirs and `exclude_prefixes` (project-relative,
    posix, no trailing slash). Returns (files, large) where files is a list
    of (relpath, size) and large is a list of relpaths >1MB (never opened)."""
    files = []
    large = []
    for d, dirs, fnames in os.walk(root):
        reld = os.path.relpath(d, root)
        reld = "" if reld == "." else norm(reld)
        kept = []
        for x in sorted(dirs):
            if x in SKIP or x.endswith(".egg-info"):
                continue
            full_rel = (reld + "/" + x) if reld else x
            if any(full_rel == p or full_rel.startswith(p + "/") for p in exclude_prefixes):
                continue
            kept.append(x)
        dirs[:] = kept
        for f in sorted(fnames):
            rel = (reld + "/" + f) if reld else f
            if any(rel == p or rel.startswith(p + "/") for p in exclude_prefixes):
                continue
            full = os.path.join(d, f)
            try:
                sz = os.path.getsize(full)
            except OSError:
                continue
            if sz > MAX_FILE_BYTES:
                large.append(rel)
                continue
            files.append((rel, sz))
    return files, large


# ------------------------------------------------------- system detection --

def find_package_roots(files):
    roots = []
    for rel, _ in files:
        parts = rel.split("/")
        if parts[-1] == "__init__.py" and (len(parts) == 2 or (len(parts) == 3 and parts[0] == "src")):
            roots.append("/".join(parts[:-1]))
        if parts[-1] == "package.json" and 1 < len(parts) <= 3 and "node_modules" not in parts:
            roots.append("/".join(parts[:-1]))
    return sorted(set(roots))


def system_of(rel, pkg_roots):
    parts = rel.split("/")
    for pr in pkg_roots:
        prp = pr.split("/")
        if parts[: len(prp)] == prp:
            rest = parts[len(prp):]
            if len(rest) >= 2:
                return pr + "/" + rest[0]
            return pr + "/(root)"
    if is_test(rel):
        return None
    if len(parts) == 1:
        return "(repo-root)"
    if parts[0] in COLLECTION:
        if len(parts) == 2:
            return parts[0] + "/" + os.path.splitext(parts[1])[0]
        return parts[0] + "/" + parts[1]
    return parts[0]


def evidence_for(raw, pkg_roots):
    parts = raw.split("/")
    if raw == "(repo-root)":
        return "repo-root"
    if any(raw == pr or raw.startswith(pr + "/") for pr in pkg_roots):
        return "package-root"
    if parts[0] in COLLECTION:
        return "collection-dir"
    if parts[0] in INFRA_DIRS:
        return "infra-dir"
    return "top-level-dir"


def build_candidates(files, pkg_roots):
    sysfiles = defaultdict(list)
    evidence = {}
    for rel, _ in files:
        raw = system_of(rel, pkg_roots)
        if raw is None:
            continue
        sysfiles[raw].append(rel)
        evidence.setdefault(raw, evidence_for(raw, pkg_roots))
    return sysfiles, evidence


def detect_slices(root, files, pkg_roots):
    """Rule 3: a module stem present as a code file in >=2 sibling layers
    (top-level dirs, or sibling sub-packages of a package root) is a feature
    candidate. Only code files count, so a YAML file mirrored in two config
    dirs is not a slice. `files` lists the stem files themselves: a
    slice owns those, not the whole layer dirs."""
    stem_dirs = defaultdict(set)
    stem_files = defaultdict(list)
    for rel, _ in files:
        if is_test(rel) or not is_code_file(root, rel):
            continue
        parts = rel.split("/")
        handled = False
        for pr in pkg_roots:
            prp = pr.split("/")
            if parts[: len(prp)] == prp and len(parts) == len(prp) + 2:
                layer = parts[len(prp)]
                stem = os.path.splitext(parts[-1])[0]
                if stem.lower() not in SLICE_STOPLIST and not stem.startswith("_"):
                    stem_dirs[stem].add(pr + "/" + layer)
                    stem_files[stem].append(rel)
                handled = True
                break
        if handled:
            continue
        if len(parts) == 2:
            stem = os.path.splitext(parts[1])[0]
            if stem.lower() not in SLICE_STOPLIST and not stem.startswith("_"):
                stem_dirs[stem].add(parts[0])
                stem_files[stem].append(rel)
    out = [{"stem": s, "dirs": sorted(d), "files": sorted(stem_files[s])}
           for s, d in stem_dirs.items() if len(d) >= 2]
    out.sort(key=lambda x: (-len(x["dirs"]), x["stem"]))
    return out


def mirror_tests(sid, files):
    """Rule 4 (test mirror): test paths for system `sid` -- a `<id>/` dir
    under a test dir, or flat `test_<id>*` files (as fnmatch patterns, one
    per containing dir). Returns (patterns, matching test files)."""
    stems = {sid, sid.replace("-", "_")}
    patterns, matched = set(), []
    for rel, _ in files:
        if not is_test(rel):
            continue
        parts = rel.split("/")
        dirs = parts[:-1]
        hit = None
        for i, d in enumerate(dirs):
            if d in stems and any(x in ("tests", "test", "__tests__", "spec") for x in dirs[:i]):
                hit = "/".join(dirs[: i + 1]) + "/"
                break
        if hit is None:
            base = parts[-1]
            for st in stems:
                if re.match(r"test_%s(_|\.|$)" % re.escape(st), base) or \
                        re.match(r"%s(_test|\.test|\.spec)\." % re.escape(st), base):
                    prefix = "/".join(dirs) + "/" if dirs else ""
                    hit = prefix + ("test_%s*" % st if base.startswith("test_") else "%s*" % st)
                    break
        if hit:
            patterns.add(hit)
            matched.append(rel)
    return sorted(patterns), matched


def compute_ids(raw_keys):
    def base_id(raw):
        if raw == "(repo-root)":
            return "core"
        if raw.endswith("/(root)"):
            return raw[: -len("/(root)")].split("/")[-1]
        return raw.split("/")[-1]

    bases = {raw: kblib.slugify(base_id(raw)) for raw in raw_keys}
    counts = Counter(bases.values())
    id_map = {}
    used = set()
    for raw in raw_keys:
        base = bases[raw]
        if counts[base] > 1 and "/" in raw and not raw.endswith("/(root)"):
            sid = kblib.slugify(raw.split("/")[0] + "-" + base)
        else:
            sid = base
        orig, n = sid, 1
        while sid in used:
            n += 1
            sid = "%s-%d" % (orig, n)
        used.add(sid)
        id_map[raw] = sid
    return id_map


def classify_kind(raw, evidence, code_count, n_in, n_out, nsys):
    short = raw.split("/")[-1].strip("()")
    if raw == "(repo-root)" or raw.endswith("/(root)") or SHARED_NAMES.match(short):
        return "cross-cutting"
    if evidence == "infra-dir":
        return "infra"
    if code_count == 0:
        return "data"
    if n_in >= max(3, nsys // 3) and n_in >= 2 * n_out:
        return "cross-cutting"
    return "feature"


# ----------------------------------------------------------------- import graph --

def py_modname(rel):
    m = rel[:-3].replace("/", ".")
    if m.endswith(".__init__"):
        m = m[: -len(".__init__")]
    if m.startswith("src."):
        m = m[4:]
    return m


def py_imports(root, rel, mod):
    text = read_text_capped(os.path.join(root, rel))
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    out = []
    pkg = mod.rsplit(".", 1)[0] if not rel.endswith("__init__.py") else mod
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                parts = pkg.split(".")
                parts = parts[: len(parts) - (n.level - 1)] if n.level > 1 else parts
                base = ".".join(parts + ([base] if base else []))
            out.append(base)
            out += [base + "." + a.name for a in n.names]
    return out


def js_imports(root, rel):
    text = read_text_capped(os.path.join(root, rel))
    specs = re.findall(r"""(?:import\s[^'"]*?from\s*|import\s*\(|require\s*\()\s*['"]([^'"]+)['"]""", text)
    out = []
    for s in specs:
        if s.startswith("."):
            out.append(norm(os.path.normpath(os.path.join(os.path.dirname(rel), s))))
    return out


def mention_edges(root, sysfiles, max_files=400):
    total_files = sum(len(fs) for fs in sysfiles.values())
    if total_files > max_files:
        return Counter()
    keys = {}
    for s, fs in sysfiles.items():
        for f in fs:
            b = os.path.basename(f)
            if len(b) >= 6 and b.lower() not in ("readme.md", "skill.md", "license", "__init__.py", ".gitignore"):
                keys.setdefault(b, s)
    out = Counter()
    for s, fs in sysfiles.items():
        txt = "".join(read_text_capped(os.path.join(root, f)) for f in fs)
        for b, t in keys.items():
            if t != s and b in txt:
                out[(s, t)] += 1
    return out


def analyze_edges(root, files, pkg_roots):
    """Returns (sedge Counter[(a,b)]->n, inb dict, outb dict, test_fns dict,
    test_files dict, mention_fallback bool)."""
    mod2sys, mod2file = {}, {}
    for rel, _ in files:
        if rel.endswith(".py"):
            m = py_modname(rel)
            mod2file[m] = rel
            s = system_of(rel, pkg_roots)
            if s:
                mod2sys[m] = s
    raw = {}
    for m, rel in mod2file.items():
        raw[m] = py_imports(root, rel, m)
    for rel, _ in files:
        if ext_of(rel) in (".js", ".jsx", ".mjs", ".ts", ".tsx"):
            key = os.path.splitext(rel)[0]
            mod2file[key] = rel
            s = system_of(rel, pkg_roots)
            if s:
                mod2sys[key] = s
            raw[key] = [os.path.splitext(x)[0] for x in js_imports(root, rel)]

    edges = defaultdict(set)
    for m, imps in raw.items():
        for i in imps:
            cand = i
            while cand and cand not in mod2file:
                cand = cand.rsplit(".", 1)[0] if "." in cand else ""
            if cand and cand != m:
                edges[m].add(cand)

    sedge = Counter()
    inb, outb = defaultdict(set), defaultdict(set)
    test_fns, test_files = Counter(), Counter()
    inbound_file_hits = Counter()
    for m, tgts in edges.items():
        rel = mod2file[m]
        if is_test(rel):
            text = read_text_capped(os.path.join(root, rel))
            n = kblib.count_test_fns(text)
            hit = {mod2sys.get(t) for t in tgts} - {None}
            if len(hit) > 1:
                hit = {h for h in hit if not h.endswith("/(root)")} or hit
            for s in hit:
                test_fns[s] += n
                test_files[s] += 1
            continue
        a = mod2sys.get(m)
        for t in tgts:
            b = mod2sys.get(t)
            inbound_file_hits[mod2file[t]] += 1
            if a and b and a != b and not is_test(mod2file[t]):
                sedge[(a, b)] += 1
                outb[a].add(b)
                inb[b].add(a)

    sysfiles = defaultdict(list)
    for rel, _ in files:
        s = system_of(rel, pkg_roots)
        if s:
            sysfiles[s].append(rel)

    mention_fallback = False
    if not sedge:
        me = mention_edges(root, sysfiles)
        if me:
            mention_fallback = True
            sedge = me
            for (a, b) in sedge:
                outb[a].add(b)
                inb[b].add(a)

    return sedge, inb, outb, test_fns, test_files, inbound_file_hits, mention_fallback


# ------------------------------------------------------------- aggregates --

def tests_config_line(root, files):
    names = {rel.split("/")[-1] for rel, _ in files if "/" not in rel}
    if "pytest.ini" in names or "conftest.py" in names:
        return "pytest (pytest.ini/conftest.py found)"
    if "pyproject.toml" in names:
        text = read_text_capped(os.path.join(root, "pyproject.toml"))
        if "[tool.pytest" in text:
            return "pytest (pyproject.toml [tool.pytest...])"
    if "jest.config.js" in names or "jest.config.ts" in names:
        return "jest (jest.config.*)"
    if "package.json" in names:
        text = read_text_capped(os.path.join(root, "package.json"))
        if '"test"' in text:
            return "npm test (package.json scripts.test)"
    if "Makefile" in names:
        text = read_text_capped(os.path.join(root, "Makefile"))
        if re.search(r"^test:", text, re.M):
            return "make test (Makefile target)"
    return "unknown"


def doc_headings(root, rel, cap=8):
    text = read_text_capped(os.path.join(root, rel))
    heads = [l.strip() for l in text.splitlines() if l.startswith("#")]
    return heads[:cap]


def entry_points(root, files):
    out = []
    for rel, _ in files:
        base = rel.split("/")[-1]
        if base in ENTRY_NAMES:
            out.append(rel)
        elif rel.split("/")[0] == "bin" and "/" in rel and rel.count("/") == 1:
            out.append(rel)
    names = {rel.split("/")[-1] for rel, _ in files if "/" not in rel}
    if "package.json" in names:
        text = read_text_capped(os.path.join(root, "package.json"))
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            data = {}
        for k, v in (data.get("scripts") or {}).items():
            out.append("npm run %s -> %s" % (k, v))
    if "Makefile" in names:
        text = read_text_capped(os.path.join(root, "Makefile"))
        for m in re.finditer(r"^([a-zA-Z0-9_-]+):", text, re.M):
            if m.group(1) != ".PHONY":
                out.append("make %s" % m.group(1))
    seen, uniq = set(), []
    for o in out:
        if o not in seen:
            seen.add(o)
            uniq.append(o)
    return uniq


def orchestration_info(root):
    orch = os.path.join(root, "orchestration")
    info = {"present": False, "dirs": {}, "phases": []}
    if not os.path.isdir(orch):
        return info
    info["present"] = True
    for name in sorted(os.listdir(orch)):
        full = os.path.join(orch, name)
        if name in SKIP:
            continue
        if os.path.isdir(full):
            if name == "workers":
                try:
                    worker_names = sorted(x for x in os.listdir(full) if os.path.isdir(os.path.join(full, x)))
                except OSError:
                    worker_names = []
                info["dirs"]["workers"] = {"count": len(worker_names), "bytes": 0, "names": worker_names}
                continue
            nfiles, nbytes = 0, 0
            for dd, _, fs in os.walk(full):
                for f in fs:
                    fp = os.path.join(dd, f)
                    try:
                        nbytes += os.path.getsize(fp)
                    except OSError:
                        continue
                    nfiles += 1
            info["dirs"][name] = {"count": nfiles, "bytes": nbytes}
        else:
            d = info["dirs"].setdefault("(root files)", {"count": 0, "bytes": 0})
            try:
                d["bytes"] += os.path.getsize(full)
            except OSError:
                pass
            d["count"] += 1
    plan_path = os.path.join(orch, "plan.md")
    if os.path.isfile(plan_path):
        text = read_text_capped(plan_path)
        for line in text.splitlines():
            if line.startswith("#"):
                info["phases"].append(line.strip())
            if len(info["phases"]) >= 15:
                break
    return info


def skills_info(root):
    d = os.path.join(root, ".claude", "skills")
    if not os.path.isdir(d):
        return []
    try:
        return sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x)))
    except OSError:
        return []


def signals_info(root, sysfiles, id_map):
    out = {"worker_tokens": [], "ci_jobs": [], "unmapped": []}
    wdir = os.path.join(root, "orchestration", "workers")
    if os.path.isdir(wdir):
        try:
            names = [x for x in os.listdir(wdir) if os.path.isdir(os.path.join(wdir, x))]
        except OSError:
            names = []
        toks = Counter()
        for n in names:
            stripped = re.sub(r"^p\d+-\d+-", "", n)
            for tok in re.split(r"[-_]", stripped):
                if tok:
                    toks[tok] += 1
        out["worker_tokens"] = [t for t, _ in toks.most_common(20)]
    ci_dir = os.path.join(root, ".github", "workflows")
    if os.path.isdir(ci_dir):
        jobs = []
        try:
            wf_files = sorted(os.listdir(ci_dir))
        except OSError:
            wf_files = []
        for f in wf_files:
            text = read_text_capped(os.path.join(ci_dir, f))
            jobs += re.findall(r"^\s{2}([a-zA-Z0-9_-]+):\s*$", text, re.M)
        out["ci_jobs"] = jobs[:20]
    return out


def reading_plan(root, sysfiles, id_map, inbound_file_hits):
    out = {}
    for raw, fs in sysfiles.items():
        sid = id_map[raw]
        ranked = sorted(fs, key=lambda f: (-inbound_file_hits.get(f, 0), -_size_of(root, f)))
        out[sid] = ranked[:3]
    return out


def _size_of(root, rel):
    try:
        return os.path.getsize(os.path.join(root, rel))
    except OSError:
        return 0


# ------------------------------------------------------------------- git --

def git_history(project):
    if not kblib.is_git_repo(project):
        return None
    head_full = kblib.head(project)
    rc, out = kblib.git(project, "rev-list", "--count", "HEAD")
    commits = int(out.strip()) if rc == 0 and out.strip().isdigit() else 0
    rc, out = kblib.git(project, "log", "--format=%ad", "--date=short", "--reverse")
    dates = [l for l in out.splitlines() if l.strip()] if rc == 0 else []
    first_date = dates[0] if dates else None
    last_date = dates[-1] if dates else None
    rc, out = kblib.git(project, "log", "-n", "20", "--name-only", "--format=@@%H\t%ad\t%s", "--date=short")
    commits_detail = []
    if rc == 0:
        cur = None
        for line in out.splitlines():
            if line.startswith("@@"):
                if cur:
                    commits_detail.append(cur)
                parts = line[2:].split("\t", 2)
                sha = parts[0] if len(parts) > 0 else ""
                date = parts[1] if len(parts) > 1 else ""
                subj = parts[2] if len(parts) > 2 else ""
                cur = {"sha": sha, "date": date, "subject": subj, "files": []}
            elif line.strip() and cur is not None:
                cur["files"].append(norm(line.strip()))
        if cur:
            commits_detail.append(cur)
    return {
        "head": head_full,
        "commits": commits,
        "first_date": first_date,
        "last_date": last_date,
        "recent": commits_detail,
    }


# -------------------------------------------------------------- markdown --

def fmt_kb(n):
    return "%.1fKB" % (n / 1024.0)


def build_sections(project, args, exclude_prefixes):
    files, large = walk_files(project, exclude_prefixes)
    pkg_roots = find_package_roots(files)
    sysfiles, evidence = build_candidates(files, pkg_roots)
    id_map = compute_ids(sorted(sysfiles))
    sedge, inb, outb, test_fns, test_files, inbound_hits, mention_fallback = analyze_edges(project, files, pkg_roots)
    slices = detect_slices(project, files, pkg_roots)
    orch = orchestration_info(project)
    skills = skills_info(project)
    hist = git_history(project)
    nsys = len(sysfiles) or 1

    systems = []
    for raw in sorted(sysfiles, key=lambda r: -len(sysfiles[r])):
        fs = sysfiles[raw]
        sid = id_map[raw]
        code_count = sum(1 for f in fs if is_code_file(project, f))
        kind = classify_kind(raw, evidence[raw], code_count, len(inb[raw]), len(outb[raw]), nsys)
        ev = [evidence[raw]]
        if mention_fallback:
            ev.append("mention-edge")
        if raw == "(repo-root)":
            paths = []
        elif raw.endswith("/(root)"):
            paths = [raw[: -len("/(root)")] + "/"]
        elif os.path.isdir(os.path.join(project, raw)):
            paths = [raw + "/"]
        else:
            # a collapsed single file (e.g. bin/x.py -> raw "bin/x"): find its
            # real on-disk file path among this system's own files.
            match = next((f for f in fs if os.path.splitext(f)[0] == raw), None)
            paths = [match] if match else [raw + "/"]
        systems.append({
            "id": sid,
            "name": sid,
            "kind": kind,
            "paths": paths,
            "tests": [],
            "files": len(fs),
            "code_files": code_count,
            "test_fns": test_fns.get(raw, 0),
            "in": len(inb[raw]),
            "out": len(outb[raw]),
            "evidence": ev,
            "_raw": raw,
        })

    for sl in slices:
        sid = kblib.slugify(sl["stem"])
        if sid in [s["id"] for s in systems]:
            sid = sid + "-slice"
        systems.append({
            "id": sid, "name": sl["stem"], "kind": "feature",
            "paths": list(sl["files"]), "tests": [],
            "files": len(sl["files"]), "code_files": len(sl["files"]),
            "test_fns": 0, "in": 0, "out": 0,
            "evidence": ["vertical-slice"], "_raw": "(slice:%s)" % sl["stem"],
        })

    for s in systems:
        patterns, matched = mirror_tests(s["id"], files)
        if not patterns and s["name"] != s["id"]:
            patterns, matched = mirror_tests(kblib.slugify(s["name"]), files)
        s["tests"] = patterns
        if patterns and not s["test_fns"]:
            s["test_fns"] = sum(kblib.count_test_fns(read_text_capped(os.path.join(project, f))) for f in matched)
        if patterns:
            s["evidence"].append("test-mirror")

    raw_to_sid = {s["_raw"]: s["id"] for s in systems if "_raw" in s}
    rplan = reading_plan(project, sysfiles, id_map, inbound_hits)
    for s in systems:
        s["read_first"] = rplan.get(s["id"], [])

    edges_out = [{"from": raw_to_sid.get(a, a), "to": raw_to_sid.get(b, b), "n": n}
                 for (a, b), n in sedge.most_common(30)]

    signals = signals_info(project, sysfiles, id_map)

    # Shape
    cats = Counter()
    cat_bytes = Counter()
    lang_files = Counter()
    lang_bytes = Counter()
    for rel, sz in files:
        c = category(project, rel)
        cats[c] += 1
        cat_bytes[c] += sz
        lang = lang_of(project, rel)
        if lang:
            lang_files[lang] += 1
            lang_bytes[lang] += sz
    cat_bytes["orchestration"] = sum(v.get("bytes", 0) for v in orch["dirs"].values())
    shape_lines = [
        "- files: %d tracked (+%d large skipped)" % (len(files), len(large)),
        "- languages: " + ", ".join(
            "%s %d files / %s" % (l, lang_files[l], fmt_kb(lang_bytes[l]))
            for l, _ in lang_files.most_common(6)
        ) if lang_files else "- languages: (none detected)",
        "- bytes by category: source %s, tests %s, docs %s, meta %s, orchestration %s" % (
            fmt_kb(cat_bytes["source"]), fmt_kb(cat_bytes["tests"]), fmt_kb(cat_bytes["docs"]),
            fmt_kb(cat_bytes["meta"]), fmt_kb(cat_bytes["orchestration"]),
        ),
    ]

    # Tree (depth 2)
    tree_children = defaultdict(lambda: defaultdict(int))
    tree_lang = defaultdict(Counter)
    top_level = set()
    for rel, sz in files:
        parts = rel.split("/")
        top_level.add(parts[0] if len(parts) > 1 else "(root)")
        if len(parts) == 1:
            continue
        depth2 = "/".join(parts[:2]) if len(parts) > 2 else rel
        key = parts[0]
        tree_children[key][depth2] += 1
        lang = lang_of(project, rel)
        if lang:
            tree_lang[depth2][lang] += 1
    tree_lines = []
    for top in sorted(top_level):
        if top == "(root)":
            continue
        entries = sorted(tree_children.get(top, {}).items())
        shown, folded = [], 0
        for name, n in entries:
            if n < 3 and name != top:
                folded += 1
            else:
                dom = tree_lang[name].most_common(1)
                dom_lang = dom[0][0] if dom else "-"
                shown.append("  %s — %d files — %s" % (name, n, dom_lang))
        total_top = sum(n for _, n in entries) or sum(1 for rel, _ in files if rel.split("/")[0] == top)
        tree_lines.append("- %s — %d files" % (top, total_top))
        tree_lines.extend(shown)
        if folded:
            tree_lines.append("  (+%d small)" % folded)

    # Entry points
    entries = entry_points(project, files)

    # Tests
    runner_line = tests_config_line(project, files)
    test_dirs = sorted({rel.split("/")[0] + "/" for rel, _ in files if is_test(rel) and "/" in rel})
    total_test_fns = 0
    parametrize_n = 0
    for rel, _ in files:
        if is_test(rel):
            text = read_text_capped(os.path.join(project, rel))
            total_test_fns += kblib.count_test_fns(text)
            parametrize_n += len(re.findall(r"parametrize", text))
    tests_lines = [
        "- runner: %s" % runner_line,
        "- test dirs: %s" % (", ".join(test_dirs) if test_dirs else "(none found)"),
        "- test functions: %d" % total_test_fns,
        "- parametrize: %d" % parametrize_n,
    ]

    # Docs
    doc_entries = []
    for rel, sz in files:
        if ext_of(rel) == ".md" and ("/" not in rel or rel.startswith("docs/")):
            heads = doc_headings(project, rel)
            doc_entries.append("- %s (%s): %s" % (rel, fmt_kb(sz), "; ".join(heads) if heads else "(no headings)"))
    docs_lines = doc_entries

    # Orchestration & skills
    orch_lines = ["- present: %s" % orch["present"]]
    for name, d in sorted(orch["dirs"].items()):
        if "names" in d:
            orch_lines.append("- workers/: %d worker dirs" % d["count"])
        else:
            orch_lines.append("- %s/: %d files, %s" % (name, d["count"], fmt_kb(d["bytes"])))
    for ph in orch["phases"]:
        orch_lines.append("  phase: %s" % ph)
    if skills:
        orch_lines.append("- .claude/skills: " + ", ".join(skills))

    # Candidate systems table
    sys_lines = ["| system | kind | files | code | test fns | in/out | evidence |", "|---|---|---|---|---|---|---|"]
    for s in systems:
        sys_lines.append("| %s | %s | %d | %d | %d | %d/%d | %s |" % (
            s["id"], s["kind"], s["files"], s["code_files"], s["test_fns"],
            s["in"], s["out"], ", ".join(s["evidence"]),
        ))

    # Vertical slices
    slice_lines = ["- %s — %s" % (sl["stem"], ", ".join(sl["dirs"])) for sl in slices]

    # Hubs & cross-cutting
    hub_lines = []
    for s in systems:
        if s["kind"] == "cross-cutting":
            hub_lines.append("- %s (in=%d, out=%d)" % (s["id"], s["in"], s["out"]))

    # Top system edges
    edge_lines = ["- %s -> %s (%d)" % (e["from"], e["to"], e["n"]) for e in edges_out]

    # Signals
    signal_lines = []
    if signals["worker_tokens"]:
        signal_lines.append("- worker-name tokens: " + ", ".join(signals["worker_tokens"]))
    if signals["ci_jobs"]:
        signal_lines.append("- CI job names: " + ", ".join(signals["ci_jobs"]))
    unmapped_concepts = [s["id"] for s in systems if s["files"] <= 1]
    if unmapped_concepts:
        signal_lines.append("- small/unmapped concepts: " + ", ".join(unmapped_concepts[:10]))

    # Reading plan
    read_lines = []
    for s in systems:
        if s["read_first"]:
            read_lines.append("- [%s] %s" % (s["id"], ", ".join(s["read_first"])))
    read_lines.append("KB totals: %d systems, %d files tracked" % (len(systems), len(files)))

    # Recent activity
    recent_lines = []
    if hist is None:
        recent_lines.append("(not a git repo)")
    else:
        for c in hist["recent"]:
            touched = set()
            orch_only = True
            for f in c["files"]:
                if f.startswith("orchestration/"):
                    touched.add("(orchestration)")
                    continue
                orch_only = False
                raw = system_of(f, pkg_roots)
                if raw and raw in raw_to_sid:
                    touched.add(raw_to_sid[raw])
                else:
                    touched.add("(unmapped)")
            recent_lines.append("- %s %s [%s] %s" % (
                c["sha"][:7], c["date"], ", ".join(sorted(touched)) or "-", c["subject"],
            ))

    content = {
        "Shape": shape_lines,
        "Tree (depth 2)": tree_lines,
        "Entry points": ["- %s" % e for e in entries],
        "Tests": tests_lines,
        "Docs": docs_lines,
        "Orchestration & skills": orch_lines,
        "Candidate systems": sys_lines,
        "Vertical slices": slice_lines,
        "Hubs & cross-cutting": hub_lines,
        "Top system edges": edge_lines,
        "Signals": signal_lines,
        "Reading plan": read_lines,
        "Recent activity": recent_lines,
    }
    for name, cap in MARKDOWN_CAPS.items():
        if len(content[name]) > cap:
            content[name] = content[name][:cap]

    title_name = os.path.basename(os.path.abspath(project).rstrip("/")) or "/"
    if hist is None:
        title = "# Project digest: %s  (not a git repo)" % title_name
    else:
        title = "# Project digest: %s  (HEAD %s, %d commits, %s..%s)" % (
            title_name, (hist["head"] or "")[:12], hist["commits"],
            hist["first_date"] or "?", hist["last_date"] or "?",
        )

    data = {
        "project": title_name,
        "head": hist["head"] if hist else None,
        "commits": hist["commits"] if hist else 0,
        "first_date": hist["first_date"] if hist else None,
        "last_date": hist["last_date"] if hist else None,
        "shape": {
            "files": len(files), "large": len(large),
            "languages": {l: {"files": lang_files[l], "bytes": lang_bytes[l]} for l in lang_files},
            "bytes_by_category": dict(cat_bytes),
        },
        "entry_points": entries,
        "tests": {"runner": runner_line, "dirs": test_dirs, "functions": total_test_fns, "parametrize": parametrize_n},
        "docs": [
            {"path": rel, "bytes": sz, "headings": doc_headings(project, rel)}
            for rel, sz in files if ext_of(rel) == ".md" and ("/" not in rel or rel.startswith("docs/"))
        ],
        "orchestration": orch,
        "skills": skills,
        "systems": [{k: v for k, v in s.items() if k != "_raw"} for s in systems],
        "slices": slices,
        "hubs": [s["id"] for s in systems if s["kind"] == "cross-cutting"],
        "edges": edges_out,
        "signals": signals,
        "recent": [
            {"sha": c["sha"], "date": c["date"], "subject": c["subject"]}
            for c in (hist["recent"] if hist else [])
        ],
    }

    return title, content, data


def render_markdown(title, content, max_lines):
    def total_lines():
        n = 1
        for name in SECTION_ORDER:
            n += 1 + len(content[name])
        return n

    while total_lines() > max_lines:
        progressed = False
        for name in TRIM_ORDER:
            if content.get(name):
                content[name] = content[name][:-1]
                progressed = True
                break
        if not progressed:
            break

    lines = [title]
    for name in SECTION_ORDER:
        lines.append("## " + name)
        lines.extend(content[name] if content[name] else ["(none)"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="project_digest.py",
        description="Generic project map: shape, tree, candidate systems, edges, reading plan (see reference/first-run-protocol.md).",
    )
    parser.add_argument("--project", default=".")
    parser.add_argument("--max-lines", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--exclude", action="append", default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    project = os.path.abspath(args.project)
    if not os.path.isdir(project):
        err("not a directory: %s" % args.project)
        return 2

    exclude_prefixes = {"orchestration"}
    kb = kblib.find_kb(project)
    if kb:
        exclude_prefixes.add(norm(os.path.relpath(kb, project)))
    for p in args.exclude or []:
        exclude_prefixes.add(norm(p.strip("/")))

    title, content, data = build_sections(project, args, exclude_prefixes)

    if args.json:
        out_text = json.dumps(data, indent=2) + "\n"
    else:
        out_text = render_markdown(title, content, args.max_lines)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out_text)
    else:
        sys.stdout.write(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
