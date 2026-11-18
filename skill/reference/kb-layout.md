# KB layout

How the knowledge base (KB) is laid out, how it is found, what `state.json` holds, how the layout adapts, and the supersede and commit rules. `<base>` is this skill's directory and `<kb>` is the KB directory. Run commands from the project root.

## Contents
1. Location and discovery
2. Default tree
3. Per-system files and entry format
4. `state.json` schema
5. How the layout adapts
6. Commit policy
7. Never deleted, only superseded

## 1. Location and discovery
- **Default dir:** `mighty-ops/` at the project root. It is distinctive, visible to humans and unlikely to collide. `init --kb-dir NAME` overrides it (`kb_init.py --kb-dir NAME`).
- **Name collision:** if `mighty-ops/` exists, is non-empty and has no `state.json`, `kb_init.py` exits 6 with "not a KB; rerun with --kb-dir mighty-ops-kb". In that case, rerun with `--kb-dir mighty-ops-kb`.
- **Pointer line.** On first run, `kb_init.py` appends this line to the project's `CLAUDE.md` if that file exists (see the CLAUDE.md policy below for when it does not), exactly:
  "- Systems knowledge base: `mighty-ops/` (owned by the mighty-ops-system-manager skill; start at `mighty-ops/README.md`; never edit by hand)."
  (with the actual dir name if it is not `mighty-ops/`).
- **Discovery order** (the scripts do this; follow the same order when looking by hand):
  1. a CLAUDE.md line matching the regex `Systems knowledge base: \x60([^\x60]+)\x60`;
  2. `<project>/mighty-ops/state.json`;
  3. any `<project>/*/state.json` at depth 1 whose JSON has `"schema": "mighty-ops-kb/1"`;
  4. none, so there is no KB yet.
- **CLAUDE.md policy:** `--claude-md append` (the default) adds the line only if CLAUDE.md exists and lacks it. `--claude-md create` also creates CLAUDE.md. Use it only in human mode after the human agrees. `--claude-md skip` does nothing. Without the line, discovery still works through the default path. When CLAUDE.md is absent, `append` silently writes nothing. Say so in the init report, and leave `CLAUDE.md` out of the commit pathspec (§6).

## 2. Default tree
`kb_init.py` creates this tree. I then adapt it per project (§5).
```
mighty-ops/
  README.md            KB entry point: system map table, how to read, last sync, health (≤80 lines)
  state.json           machine state (§4); only scripts and the skill write it
  harmony.md           cross-system edges and contracts table
  glossary.md          project terms → one-line meaning → owning system
  roadmap/roadmap.md   now / next / later, each item → systems, DR, status
  roadmap/ideas.md     human ideas as received (IDEA-n), with triage outcome
  decisions/DR-0001-slug.md     decision records; never deleted
  systems/ID/          one folder per system, six required files (§3)
  inbox/RECIPIENT.md   live messages FOR a recipient (orch-manager, human, a session name)
  outbox/              archived inbox messages (acknowledged or superseded)
  exchanges/EX-yyyymmdd-nnn-mode-slug.md   session-mode request/response records
  digests/             project digests and catch-up reports (first-run-DATE.md, catchup-DATE-SHA7.md)
```
`inbox/` is named from the recipient's side. `inbox/orch-manager.md` is the orch-manager's inbox, kept in the KB. `outbox/` archives messages that have left the inbox.

`harmony.md` holds one table:
```
| from | to | relies on (contract) | pinned by tests | DR |
```
`README.md` holds: a system map table (`| system | kind | health | reason | paths |`), how to read the KB, the last sync (sha7 and date), a list of any extra cross-cutting folders, and the digest-pruning note (§7).

## 3. Per-system files and entry format
| file | holds | entry id |
|---|---|---|
| `findings.md` | verified facts about how it works today: entry points, contracts, gotchas, test layout | `F-n` |
| `vision.md` | how it *should* be built: goals, boundaries, non-goals, invariants. Human-stated text is quoted with the date; inferred text is labelled "(inferred)" | sections, not ids |
| `limitations.md` | honest known limits, each with evidence and severity (`low/medium/high`) | `L-n` |
| `todo.md` | work that should happen, each with acceptance criteria and the systems it touches | `T-n` |
| `done.md` | completed work: commit(s), tests that pin it, which todo it closed | `D-n` |
| `decisions.md` | index: one line per DR affecting this system → `../../decisions/DR-….md` | DR ids |

Each file starts with `# ID — kind` and `Updated: YYYY-MM-DD`. An entry is a `### ID — title` heading followed by bullets, then free text:
```
### L-3 — Retry loop has no upper bound
- Since: 2026-10-24 (abc1234)
- Status: open
- Evidence: src/net/client.py:88 (`while True:` with no counter)
- Severity: medium
Free text: what breaks, when, who is affected.
```
- `Status:` is one of `open`, `resolved (DATE, SHA7)`, or `superseded by ID (DATE: reason)`.
- Ids are never reused within a file. The next id is the highest existing number plus one.
- `decisions.md` lines: `- DR-0007 (2026-10-24, accepted) — title → ../../decisions/DR-0007-slug.md`.

The stub `kb_init.py` writes for a new file (shown for limitations; the other files change the kind name and the hint line):
```
# ID — limitations
Updated: YYYY-MM-DD
<!-- Entries: ### L-<n> — <title> / - Since: / - Status: / - Evidence: / text. Never delete an entry; supersede it. -->
(none recorded yet)
```
Replace `(none recorded yet)` with the first entry, and keep the comment line. With Edit, replace `(none recorded yet)` (the Edit tool needs one Read of the file first). For a heavy first run with many stubs, write the contents into one bundle file in your scratch dir, then split it into the stubs with a small scratch Python script (`first-run-protocol.md` §4).

## 4. `state.json` schema
`"schema": "mighty-ops-kb/1"`. Only the scripts and the skill write it. Writes are atomic (the scripts write `state.json.tmp`, then rename it). If you edit it by hand, keep the key order and `indent=2`.
```json
{
  "schema": "mighty-ops-kb/1",
  "kb_dir": "mighty-ops",
  "created_at": "2026-10-24T10:00:00Z",
  "updated_at": "2026-10-24T10:00:00Z",
  "commit_policy": "auto",
  "last_synced_commit": "40-hex or null",
  "last_synced_at": "ISO or null",
  "pending_sync": null,
  "first_run": {"status": "pending|in_progress|partial|done", "head": "40-hex or null",
                "started_at": "ISO", "finished_at": "ISO or null", "passes_done": ["digest", "docs", "system:api"]},
  "noise_paths": ["orchestration/"],
  "systems": [
    {"id": "api", "name": "HTTP API", "kind": "feature|cross-cutting|infra|data",
     "paths": ["src/app/api/", "config/api.yaml"], "tests": ["tests/api/"],
     "status": "active|split|merged|retired", "superseded_by": [], "derived_from": [],
     "health": "green|amber|red|unknown", "health_reason": "one line",
     "last_changed_commit": "40-hex or null", "updated_at": "ISO",
     "counts": {"findings": 0, "limitations": 0, "todo": 0, "done": 0, "decisions": 0}}
  ],
  "health": {"overall": "green|amber|red|unknown", "kb_check": "clean|warnings|errors|unknown", "checked_at": "ISO or null"},
  "counters": {"dr": 0, "exchange_seq": {"20261024": 3}, "brief_seq": {"20261024": 1}}
}
```
While a catch-up is in progress, `pending_sync` holds:
```json
{"from": "sha", "to": "sha", "created_at": "ISO", "systems": ["api"], "systems_done": [],
 "digest": "digests/catchup-20261024-abc1234.md", "regression_flags": []}
```
Rules:
- `paths` are POSIX prefixes relative to the project root. A trailing `/` means a directory. A pattern containing `*` is matched with fnmatch. A file belongs to the system with the **longest** matching prefix.
- The KB dir is always noise. It is implicit and never listed in `noise_paths`.
- `health.overall` is the worst health among the active systems (red > unknown > amber > green). `catchup.py --mark-synced` computes it. The health values are defined in `quality-bar.md`.
- `first_run.passes_done`: you append each pass name by hand. `--mark-synced` appends `close` when it closes an `in_progress` first run.
- `counts` are written by `check_kb.py --record`. `decisions` counts the distinct DR ids indexed in `decisions.md`; the other files count `### ID` entries. A later count below the recorded one is an error (E07), because it means an entry was deleted.
- `counters.dr` gives the last DR number. `exchange_seq` and `brief_seq` give the last sequence per day. Increment the counter, then use the new value.
- Timestamps are UTC ISO-8601 with `Z`.

## 5. How the layout adapts
Each adaptation needs a DR (`decision-record.md`).
- **New system** (catch-up flags a new top-level dir or package, or the human or a DR creates one):
  `python3 <base>/scripts/kb_init.py --project . --add-system ID --paths p1,p2 --kind feature --name "Human name"`
  This creates the folder with stubs and appends the system to state.
- **More paths for an existing system:** `python3 <base>/scripts/kb_init.py --project . --add-paths ID p1,p2`
- **Split** OLD into A and B:
  `python3 <base>/scripts/kb_init.py --project . --split OLD --into A,B --paths-A pa1,pa2 --paths-B pb1`
  (one `--paths-ID` flag per new id). OLD gets `status: split, superseded_by: [A, B]` and keeps its folder. Each of its six files gets the line `Superseded: split into A, B on DATE (DR-nnnn).` under the header. The new folders get `derived_from: [OLD]`. The script does not move entries; that is my job. Copy each *open* entry of OLD into the right new file as `### L-1 — title (moved from OLD#L-4)`, and mark the old entry `Status: superseded by A#L-1 (DATE: split)`.
- **Merge** A and B into C: `python3 <base>/scripts/kb_init.py --project . --merge A,B --into C` (`--paths` defaults to the union). Merge mirrors split. A rename is a merge of one system.
- **Retire:** set `status: retired` with a DR. The folder stays.
- **Extra files** in a system folder (for example `contracts.md` or `runbook.md`) are allowed, and `check_kb.py` ignores them. Extra cross-cutting folders are also allowed, and must be listed in `README.md`.
- `kb_init.py` never overwrites an existing file. It only creates missing files and appends missing systems. Use `--dry-run` to preview.

## 6. Commit policy
`commit_policy` is set at init: `auto` when the project is a git repo, otherwise `never` (override it with `--commit-policy`).
- `auto`: at write-back, run
  `git add <kb>` then `git commit -m "kb(MODE): one line" -- <kb>`
  Commit by pathspec only, never other paths, and never amend. On first run, if kb_init added the CLAUDE.md pointer line, commit it too: `git add CLAUDE.md` and add it to the same pathspec. If the project has no CLAUDE.md, leave it out, because a pathspec naming a missing file makes `git add` fail.
- `never`: leave changes uncommitted (for a dry run, or when the human prefers it).
- Catch-up always ignores commits that touch only `<kb>/`.

## 7. Never deleted, only superseded
These are kept forever:
- entries in findings, limitations, todo and done (supersede them with a `Status:` line giving the date and reason);
- DRs (`Status: superseded by DR-nnnn (DATE: reason)`);
- systems (retired, split or merged; the folders are kept);
- inbox messages (moved to `outbox/`);
- exchange records;
- digests. The one allowed delete is pruning digests beyond the newest 20, and that rule is stated in README.md.

Superseding means the old text stays, plus a `Status: superseded by …` line. `check_kb.py` enforces this with the recorded counts (E07). If a file grows past 400 lines (warning W04), summarise resolved entries into a dated "Archive summary" section at its foot. Keep every heading and id, and move the long text into an extra file in the same folder.
