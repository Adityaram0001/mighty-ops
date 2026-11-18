#!/usr/bin/env python3
"""kb_init.py -- create or extend the mighty-ops knowledge base tree.

Usage:
  kb_init.py [--project .] [--kb-dir mighty-ops] [--systems-json FILE | --systems id1,id2]
             [--claude-md append|skip|create] [--commit-policy auto|never] [--dry-run] [--json]
  kb_init.py --add-system ID --paths p1,p2 [--kind feature] [--name "Human name"]
  kb_init.py --add-paths ID p1,p2
  kb_init.py --split OLD --into A,B --paths-A p.. --paths-B p..
  kb_init.py --merge A,B --into C [--paths p1,p2]

See reference/kb-layout.md. Exit codes: 0 ok, 2 usage/KB-not-found, 6 KB-dir
or schema mismatch.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kblib

ID_RX_SRC = r"^[a-z0-9][a-z0-9-]{0,39}$"


def err(msg):
    print("error: %s" % msg, file=sys.stderr)


def id_ok(id_):
    import re

    return re.match(ID_RX_SRC, id_ or "") is not None


def _stub(id_, kind, hint, body="(none recorded yet)"):
    date = kblib.now_iso()[:10]
    return "# %s — %s\nUpdated: %s\n%s\n%s\n" % (id_, kind, date, hint, body)


def system_stub_files(id_):
    """Return {filename: content} for the six required per-system files."""
    entry_hint = (
        "<!-- Entries: ### %s-<n> — <title> / - Since: / - Status: / "
        "- Evidence: / text. Never delete an entry; supersede it. -->"
    )
    return {
        "findings.md": _stub(id_, "findings", entry_hint % "F"),
        "vision.md": _stub(
            id_,
            "vision",
            '<!-- Sections, not entries. Human-stated text quoted with date; '
            'inferred text labelled "(inferred)". Never delete; supersede '
            "with a dated note. -->",
        ),
        "limitations.md": _stub(id_, "limitations", entry_hint % "L"),
        "todo.md": _stub(id_, "todo", entry_hint % "T"),
        "done.md": _stub(id_, "done", entry_hint % "D"),
        "decisions.md": _stub(
            id_,
            "decisions",
            "<!-- Index: one line per DR affecting this system -> "
            "../../decisions/DR-....md -->",
        ),
    }


def toplevel_stub_files():
    date = kblib.now_iso()[:10]
    return {
        "README.md": (
            "# mighty-ops knowledge base\n"
            "Updated: %s\n"
            "<!-- Entry point. System map table, how to read, last sync, health. -->\n"
            "## System map\n"
            "| system | kind | health | reason |\n"
            "|---|---|---|---|\n"
            "(none recorded yet)\n"
        )
        % date,
        "harmony.md": (
            "# harmony — cross-system edges and contracts\n"
            "Updated: %s\n"
            "| from | to | relies on (contract) | pinned by tests | DR |\n"
            "|---|---|---|---|---|\n"
            "(none recorded yet)\n"
        )
        % date,
        "glossary.md": (
            "# glossary\n"
            "Updated: %s\n"
            "<!-- term -> one-line meaning -> owning system -->\n"
            "(none recorded yet)\n"
        )
        % date,
        os.path.join("roadmap", "roadmap.md"): (
            "# roadmap\n"
            "Updated: %s\n"
            "## Now\n(none recorded yet)\n## Next\n(none recorded yet)\n## Later\n(none recorded yet)\n"
        )
        % date,
        os.path.join("roadmap", "ideas.md"): (
            "# ideas\n"
            "Updated: %s\n"
            "<!-- IDEA-n, verbatim with date, plus triage outcome. -->\n"
            "(none recorded yet)\n"
        )
        % date,
    }


EXTRA_DIRS = ["decisions", "inbox", "outbox", "exchanges", "digests", "systems"]


def write_if_missing(path, content, dry_run):
    """Returns True if created (or would be created), False if kept."""
    if os.path.isfile(path):
        return False
    if not dry_run:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return True


def parse_systems(args):
    """Returns a validated list of {id, name, kind, paths, tests} dicts, or
    calls sys.exit(2) on a bad id."""
    raw = []
    if args.systems_json:
        try:
            with open(args.systems_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            err("cannot read --systems-json: %s" % e)
            sys.exit(2)
        if isinstance(data, dict) and "systems" in data:
            raw = data["systems"]
        elif isinstance(data, list):
            raw = data
        else:
            err("--systems-json: expected a list or an object with 'systems'")
            sys.exit(2)
    elif args.systems:
        raw = [{"id": s.strip()} for s in args.systems.split(",") if s.strip()]

    out = []
    for item in raw:
        if isinstance(item, str):
            item = {"id": item}
        id_ = item.get("id")
        if not id_ok(id_):
            err("bad system id: %r" % (id_,))
            sys.exit(2)
        out.append(
            {
                "id": id_,
                "name": item.get("name", id_),
                "kind": item.get("kind", "feature"),
                "paths": item.get("paths", []) or [],
                "tests": item.get("tests", []) or [],
            }
        )
    return out


def make_system_entry(sysdef, kind_override=None, derived_from=None):
    return {
        "id": sysdef["id"],
        "name": sysdef.get("name", sysdef["id"]),
        "kind": kind_override or sysdef.get("kind", "feature"),
        "paths": sysdef.get("paths", []) or [],
        "tests": sysdef.get("tests", []) or [],
        "status": "active",
        "superseded_by": [],
        "derived_from": derived_from or [],
        "health": "unknown",
        "health_reason": "",
        "last_changed_commit": None,
        "updated_at": kblib.now_iso(),
        "counts": {"findings": 0, "limitations": 0, "todo": 0, "done": 0, "decisions": 0},
    }


def resolve_kb(project, kb_dir_arg):
    """Returns (kb_path, is_new, error_exit_code_or_None)."""
    existing = kblib.find_kb(project)
    if existing:
        if kb_dir_arg and os.path.basename(existing.rstrip("/")) != kb_dir_arg:
            return existing, False, 6
        return existing, False, None
    name = kb_dir_arg or "mighty-ops"
    kb = os.path.join(project, name)
    if os.path.isdir(kb) and os.listdir(kb) and not os.path.isfile(
        os.path.join(kb, "state.json")
    ):
        return kb, True, 6
    return kb, True, None


def insert_superseded_line(path, line):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)
    out = []
    inserted = False
    for ln in lines:
        out.append(ln)
        if not inserted and ln.startswith("Updated:"):
            if not ln.endswith("\n"):
                out[-1] = ln + "\n"
            out.append(line + "\n")
            inserted = True
    if not inserted:
        out.append(line + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)


def handle_claude_md(project, kb_dir_name, mode, dry_run):
    path = os.path.join(project, "CLAUDE.md")
    pointer = (
        "- Systems knowledge base: `%s/` (owned by the mighty-ops-system-manager "
        "skill; start at `%s/README.md`; never edit by hand)."
        % (kb_dir_name.rstrip("/"), kb_dir_name.rstrip("/"))
    )
    if mode == "skip":
        return False
    exists = os.path.isfile(path)
    if not exists and mode == "append":
        return False
    if dry_run:
        return True
    if not exists:
        with open(path, "w", encoding="utf-8") as f:
            f.write(pointer + "\n")
        return True
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if "Systems knowledge base:" in text:
        return False
    if not text.endswith("\n"):
        text += "\n"
    text += pointer + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def cmd_default(args, project):
    kb, is_new, code = resolve_kb(project, args.kb_dir)
    if code == 6:
        if is_new:
            err("not a KB; rerun with --kb-dir mighty-ops-kb")
        else:
            err("--kb-dir does not match existing state.kb_dir")
        return 6
    kb_dir_name = os.path.basename(kb.rstrip("/"))

    if is_new:
        st = {
            "schema": kblib.SCHEMA,
            "kb_dir": kb_dir_name,
            "created_at": kblib.now_iso(),
            "updated_at": kblib.now_iso(),
            "commit_policy": args.commit_policy
            or ("auto" if kblib.is_git_repo(project) else "never"),
            "last_synced_commit": None,
            "last_synced_at": None,
            "pending_sync": None,
            "first_run": {
                "status": "in_progress",
                "head": kblib.head(project) if kblib.is_git_repo(project) else None,
                "started_at": kblib.now_iso(),
                "finished_at": None,
                "passes_done": [],
            },
            "noise_paths": ["orchestration/"],
            "systems": [],
            "health": {"overall": "unknown", "kb_check": "unknown", "checked_at": None},
            "counters": {"dr": 0, "exchange_seq": {}, "brief_seq": {}},
        }
    else:
        try:
            st = kblib.load_state(kb)
        except ValueError as e:
            err(str(e))
            return 6

    new_systems = parse_systems(args)
    existing_ids = {s["id"] for s in st["systems"]}
    systems_added = []
    for sysdef in new_systems:
        if sysdef["id"] not in existing_ids:
            st["systems"].append(make_system_entry(sysdef))
            existing_ids.add(sysdef["id"])
            systems_added.append(sysdef["id"])

    created = []
    kept = []

    for rel, content in toplevel_stub_files().items():
        full = os.path.join(kb, rel)
        if write_if_missing(full, content, args.dry_run):
            created.append(os.path.join(kb_dir_name, rel))
        else:
            kept.append(os.path.join(kb_dir_name, rel))

    for d in EXTRA_DIRS:
        full = os.path.join(kb, d)
        if not os.path.isdir(full) and not args.dry_run:
            os.makedirs(full, exist_ok=True)

    for sysdef in st["systems"]:
        sid = sysdef["id"]
        for fname, content in system_stub_files(sid).items():
            full = os.path.join(kb, "systems", sid, fname)
            rel_out = os.path.join(kb_dir_name, "systems", sid, fname)
            if write_if_missing(full, content, args.dry_run):
                created.append(rel_out)
            else:
                kept.append(rel_out)

    handle_claude_md(project, kb_dir_name, args.claude_md, args.dry_run)

    state_path = os.path.join(kb, "state.json")
    rel_state = os.path.join(kb_dir_name, "state.json")
    state_is_new = not os.path.isfile(state_path)
    if state_is_new:
        created.insert(0, rel_state)
    else:
        kept.insert(0, rel_state)
    # A rerun that adds nothing leaves state.json byte-identical (idempotent).
    if not args.dry_run and (state_is_new or systems_added):
        st["updated_at"] = kblib.now_iso()
        kblib.save_state(kb, st)

    report(args, created, kept, systems_added, kb_dir_name)
    return 0


def report(args, created, kept, systems_added, kb_dir_name):
    if args.json:
        print(
            json.dumps(
                {
                    "created": created,
                    "kept": kept,
                    "systems_added": systems_added,
                    "kb": kb_dir_name,
                }
            )
        )
        return
    print(
        "created: %d files, kept: %d, systems added: %s"
        % (len(created), len(kept), ", ".join(systems_added))
    )
    for c in created:
        print(c)


def cmd_add_system(args, project):
    kb = kblib.find_kb(project)
    if not kb:
        err("KB not found")
        return 2
    try:
        st = kblib.load_state(kb)
    except ValueError as e:
        err(str(e))
        return 6
    id_ = args.add_system
    if not id_ok(id_):
        err("bad system id: %r" % (id_,))
        return 2
    paths = [p.strip() for p in (args.paths or "").split(",") if p.strip()]
    existing = {s["id"]: s for s in st["systems"]}
    if id_ in existing:
        for p in paths:
            if p not in existing[id_]["paths"]:
                existing[id_]["paths"].append(p)
        if args.kind:
            existing[id_]["kind"] = args.kind
        if args.name:
            existing[id_]["name"] = args.name
        existing[id_]["updated_at"] = kblib.now_iso()
        systems_added = []
    else:
        sysdef = {"id": id_, "name": args.name or id_, "kind": args.kind or "feature", "paths": paths, "tests": []}
        st["systems"].append(make_system_entry(sysdef))
        systems_added = [id_]

    created, kept = [], []
    for fname, content in system_stub_files(id_).items():
        full = os.path.join(kb, "systems", id_, fname)
        rel_out = os.path.join(os.path.basename(kb.rstrip("/")), "systems", id_, fname)
        if write_if_missing(full, content, args.dry_run):
            created.append(rel_out)
        else:
            kept.append(rel_out)

    if not args.dry_run:
        st["updated_at"] = kblib.now_iso()
        kblib.save_state(kb, st)

    report(args, created, kept, systems_added, os.path.basename(kb.rstrip("/")))
    return 0


def cmd_add_paths(args, project):
    kb = kblib.find_kb(project)
    if not kb:
        err("KB not found")
        return 2
    try:
        st = kblib.load_state(kb)
    except ValueError as e:
        err(str(e))
        return 6
    id_, paths_csv = args.add_paths
    sysdef = next((s for s in st["systems"] if s["id"] == id_), None)
    if sysdef is None:
        err("unknown system id: %s" % id_)
        return 2
    paths = [p.strip() for p in paths_csv.split(",") if p.strip()]
    for p in paths:
        if p not in sysdef["paths"]:
            sysdef["paths"].append(p)
    sysdef["updated_at"] = kblib.now_iso()
    if not args.dry_run:
        st["updated_at"] = kblib.now_iso()
        kblib.save_state(kb, st)
    report(args, [], [], [], os.path.basename(kb.rstrip("/")))
    return 0


def cmd_split(args, project, extra_paths_flags):
    kb = kblib.find_kb(project)
    if not kb:
        err("KB not found")
        return 2
    try:
        st = kblib.load_state(kb)
    except ValueError as e:
        err(str(e))
        return 6
    old_id = args.split
    into_ids = [s.strip() for s in args.into.split(",") if s.strip()]
    systems_by_id = {s["id"]: s for s in st["systems"]}
    if old_id not in systems_by_id:
        err("unknown system id: %s" % old_id)
        return 2
    for nid in into_ids:
        if not id_ok(nid):
            err("bad system id: %r" % (nid,))
            return 2
        if nid in systems_by_id:
            err("system already exists: %s" % nid)
            return 2

    paths_for = {}
    for nid in into_ids:
        flag = "paths_%s" % nid
        if flag not in extra_paths_flags or extra_paths_flags[flag] is None:
            err("missing --paths-%s" % nid)
            return 2
        paths_for[nid] = [p.strip() for p in extra_paths_flags[flag].split(",") if p.strip()]

    old = systems_by_id[old_id]
    date = kblib.now_iso()[:10]
    old["status"] = "split"
    old["superseded_by"] = into_ids
    old["updated_at"] = kblib.now_iso()
    created, kept = [], []
    if not args.dry_run:
        line = "Superseded: split into %s on %s (DR-nnnn)." % (", ".join(into_ids), date)
        for fname in kblib.REQUIRED_FILES:
            full = os.path.join(kb, "systems", old_id, fname)
            if os.path.isfile(full):
                insert_superseded_line(full, line)

    systems_added = []
    for nid in into_ids:
        sysdef = {"id": nid, "name": nid, "kind": old.get("kind", "feature"), "paths": paths_for[nid], "tests": []}
        st["systems"].append(make_system_entry(sysdef, derived_from=[old_id]))
        systems_added.append(nid)
        for fname, content in system_stub_files(nid).items():
            full = os.path.join(kb, "systems", nid, fname)
            rel_out = os.path.join(os.path.basename(kb.rstrip("/")), "systems", nid, fname)
            if write_if_missing(full, content, args.dry_run):
                created.append(rel_out)
            else:
                kept.append(rel_out)

    if not args.dry_run:
        st["updated_at"] = kblib.now_iso()
        kblib.save_state(kb, st)

    report(args, created, kept, systems_added, os.path.basename(kb.rstrip("/")))
    return 0


def cmd_merge(args, project):
    kb = kblib.find_kb(project)
    if not kb:
        err("KB not found")
        return 2
    try:
        st = kblib.load_state(kb)
    except ValueError as e:
        err(str(e))
        return 6
    src_ids = [s.strip() for s in args.merge.split(",") if s.strip()]
    new_id = args.into
    systems_by_id = {s["id"]: s for s in st["systems"]}
    for sid in src_ids:
        if sid not in systems_by_id:
            err("unknown system id: %s" % sid)
            return 2
    if not id_ok(new_id):
        err("bad system id: %r" % (new_id,))
        return 2
    if new_id in systems_by_id:
        err("system already exists: %s" % new_id)
        return 2

    if args.paths:
        paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    else:
        paths = []
        for sid in src_ids:
            for p in systems_by_id[sid]["paths"]:
                if p not in paths:
                    paths.append(p)

    date = kblib.now_iso()[:10]
    line = "Superseded: merged into %s on %s (DR-nnnn)." % (new_id, date)
    for sid in src_ids:
        sysdef = systems_by_id[sid]
        sysdef["status"] = "merged"
        sysdef["superseded_by"] = [new_id]
        sysdef["updated_at"] = kblib.now_iso()
        if not args.dry_run:
            for fname in kblib.REQUIRED_FILES:
                full = os.path.join(kb, "systems", sid, fname)
                if os.path.isfile(full):
                    insert_superseded_line(full, line)

    kind = systems_by_id[src_ids[0]].get("kind", "feature")
    sysdef = {"id": new_id, "name": new_id, "kind": kind, "paths": paths, "tests": []}
    st["systems"].append(make_system_entry(sysdef, derived_from=src_ids))

    created, kept = [], []
    for fname, content in system_stub_files(new_id).items():
        full = os.path.join(kb, "systems", new_id, fname)
        rel_out = os.path.join(os.path.basename(kb.rstrip("/")), "systems", new_id, fname)
        if write_if_missing(full, content, args.dry_run):
            created.append(rel_out)
        else:
            kept.append(rel_out)

    if not args.dry_run:
        st["updated_at"] = kblib.now_iso()
        kblib.save_state(kb, st)

    report(args, created, kept, [new_id], os.path.basename(kb.rstrip("/")))
    return 0


def build_parser(extra_paths_ids):
    p = argparse.ArgumentParser(
        prog="kb_init.py",
        description="Create or extend the mighty-ops knowledge base tree (see reference/kb-layout.md).",
    )
    p.add_argument("--project", default=".")
    p.add_argument("--kb-dir", default=None)
    p.add_argument("--systems-json", default=None)
    p.add_argument("--systems", default=None)
    p.add_argument("--claude-md", choices=["append", "skip", "create"], default="append")
    p.add_argument("--commit-policy", choices=["auto", "never"], default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--add-system", default=None, metavar="ID")
    p.add_argument("--paths", default=None, metavar="p1,p2")
    p.add_argument("--kind", default=None)
    p.add_argument("--name", default=None)
    p.add_argument("--add-paths", nargs=2, default=None, metavar=("ID", "PATHS"))
    p.add_argument("--split", default=None, metavar="OLD")
    p.add_argument("--into", default=None, metavar="A,B")
    p.add_argument("--merge", default=None, metavar="A,B")
    for nid in extra_paths_ids:
        p.add_argument("--paths-%s" % nid, dest="paths_%s" % nid, default=None)
    return p


def prescan_split_ids(argv):
    """--split/--into may need dynamically-named --paths-<id> flags; scan
    argv for them before building the real parser."""
    if "--into" not in argv:
        return []
    i = argv.index("--into")
    if i + 1 >= len(argv):
        return []
    return [s.strip() for s in argv[i + 1].split(",") if s.strip()]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    extra_ids = prescan_split_ids(argv) if "--split" in argv else []
    parser = build_parser(extra_ids)
    args = parser.parse_args(argv)
    project = os.path.abspath(args.project)

    if args.add_system:
        return cmd_add_system(args, project)
    if args.add_paths:
        return cmd_add_paths(args, project)
    if args.split:
        if not args.into:
            err("--split requires --into")
            return 2
        extra_flags = {nid_flag: getattr(args, nid_flag, None) for nid_flag in
                        ("paths_%s" % nid for nid in extra_ids)}
        return cmd_split(args, project, extra_flags)
    if args.merge:
        if not args.into:
            err("--merge requires --into")
            return 2
        return cmd_merge(args, project)
    return cmd_default(args, project)


if __name__ == "__main__":
    sys.exit(main())
