# Design

This document describes how `mighty-ops-system-manager` works: its principles, lifecycle, knowledge-base format, protocols, and the contracts of its helper scripts. The skill's own operating instructions live in [`skill/SKILL.md`](../skill/SKILL.md) and the six files in [`skill/reference/`](../skill/reference/), which the model loads on demand. This page is the overview for humans.

## Contents

1. [Principles](#1-principles)
2. [Components](#2-components)
3. [Invocation](#3-invocation)
4. [Lifecycle](#4-lifecycle)
5. [Knowledge base](#5-knowledge-base)
6. [First run](#6-first-run)
7. [Catch-up](#7-catch-up)
8. [Session mode and the claude-orch handshake](#8-session-mode-and-the-claude-orch-handshake)
9. [Quality bar](#9-quality-bar)
10. [Budget awareness](#10-budget-awareness)
11. [Script reference](#11-script-reference)
12. [Testing](#12-testing)

## 1. Principles

- **Memory is files.** Every conclusion worth keeping goes into the KB in the same turn. A conversation that leaves the KB unchanged produced nothing durable.
- **Evidence or it is a guess.** Findings cite `path:line`, a commit, or a command. Anything inferred is labelled "(inferred)".
- **Compounds, never regresses.** A change is good only if the next change in the same area becomes cheaper and safer (§9).
- **Harmony.** Before endorsing a change to one system, check who relies on it and which tests pin that reliance.
- **Supersede, never delete.** KB history is append-only in meaning.
- **Short when called, broad when asked.** Session modes answer in 30 lines or fewer, with citations; human mode can range wide.
- **One writer per file.** The skill writes only its KB (plus one pointer line in `CLAUDE.md`). `orchestration/` belongs to claude-orch's manager.
- **Bounded reading.** Every protocol has byte and file budgets, and the skill says what it did not read.
- **Generic.** No language, framework or layout is assumed; they are detected.

## 2. Components

| Part | Role |
|---|---|
| `skill/SKILL.md` | The prompt: persona, argument grammar, state machine, mode rules, KB summary, the "never" list. Kept under 200 lines so it is cheap to load on every invocation. |
| `skill/reference/*.md` | Detailed protocols, each read only when its mode starts: `kb-layout`, `first-run-protocol`, `catchup-protocol`, `interaction-protocols`, `decision-record`, `quality-bar`. |
| `skill/scripts/*.py` | Mechanical work the model should not do by hand: scaffolding, digests, git range analysis, linting, scorecards. Python 3.9+ standard library only. |

Judgement (naming systems, writing findings, deciding) stays with the model. Anything that must be exact and repeatable (path-to-system mapping, test-function counts, state transitions, lint rules) is a script.

## 3. Invocation

Claude Code places `Base directory for this skill: <path>` before the skill text and `ARGUMENTS: <raw>` after it. The skill parses that line:

1. No `ARGUMENTS:` line, or a blank one → **human mode**.
2. Otherwise the first token, case-insensitive and with or without a trailing colon, selects the mode: `ask`, `decide`, `review`, `catchup`, `init`, `brief-next-manager`. The rest is the payload.
3. An optional trailing ` | from: <who>` identifies the caller and is recorded.
4. Any other first token is treated as `ask:`, and the answer says so on its first line.

| Mode | Sync rule | Writes | Output |
|---|---|---|---|
| human | full catch-up if stale (chunked) | anything the discussion produces | ≤12-line status, then conversation |
| `ask:` | stale rule | exchange record; verified findings | ≤30 lines |
| `decide:` | stale rule | exchange record, DR, per-system DR index lines | ≤30 lines incl. `Decision:` and `DR:` |
| `review:` | stale rule | exchange record; regression and limitation entries | ≤30 lines: `PASS` / `CONCERNS` / `BLOCK` + ≤10 findings |
| `catchup` | full, chunked | per-system pages, state, digest | ≤20-line summary |
| `init` | n/a | creates or extends the KB | ≤40-line report |
| `brief-next-manager` | stale rule | `inbox/orch-manager.md` (previous brief archived) | path + ≤8-line summary |

**Stale rule.** Session modes run `catchup.py` first. Up to date → answer. At most 30 non-noise commits and 40 non-noise files behind → do a bounded update of the systems the question touches plus every flagged system, then answer. Further behind → answer from the KB with `PROVISIONAL: KB at <sha>, HEAD <sha>, N commits behind`, file any decision only as `proposed`, and leave a "run `catchup`" note in the inbox. The heavy work never runs inside another session's turn.

## 4. Lifecycle

```
invoke ─► parse ARGUMENTS ─► locate KB
   │
   ├─ no KB ── init or human ─► FIRST RUN (heavy on an existing project, light on a new one)
   │        └─ other modes ───► provisional answer from a bounded look; recommend init
   │
   └─ KB found ─► state.json ─► check_kb.py --quick (fix the KB first if it reports errors)
                  ├─ first_run not done ─► resume FIRST RUN at the next pass
                  ├─ pending_sync set ───► resume CATCH-UP
                  └─ catchup.py ─► up_to_date ──────────────────► ACT
                                 └─ behind ─► CATCH-UP or PROVISIONAL ─► ACT
ACT ─► WRITE BACK: KB pages → exchange record → check_kb.py --record
       → catchup.py --mark-synced (only after a completed sync) → commit the KB by pathspec
```

Every step that writes leaves the KB valid on its own. A session that dies mid-way (turn cap, usage limit) resumes from `state.json`: `first_run.passes_done` for the first run, `pending_sync.systems_done` for a catch-up.

## 5. Knowledge base

### Location and discovery

The default directory is `mighty-ops/` at the project root (`init --kb-dir <name>` overrides it; if a non-KB `mighty-ops/` already exists, `mighty-ops-kb/` is used). Discovery order: a `CLAUDE.md` line matching ``Systems knowledge base: `<dir>` ``, then `mighty-ops/state.json`, then any depth-1 `*/state.json` with `"schema": "mighty-ops-kb/1"`.

### Tree

```
README.md            entry point: system map, health, last sync (≤80 lines)
state.json           machine state; only the scripts and the skill write it
harmony.md           | from | to | relies on (contract) | pinned by tests | DR |
glossary.md          term → meaning → owning system
roadmap/roadmap.md   now / next / later, each item → systems, DR, status
roadmap/ideas.md     human ideas as received (IDEA-n), with triage outcome
decisions/           DR-nnnn-<slug>.md
systems/<id>/        findings.md (F-n) · vision.md · limitations.md (L-n, severity)
                     todo.md (T-n, acceptance criteria) · done.md (D-n, commits, pinning tests)
                     decisions.md (DR index)
inbox/<recipient>.md live messages for orch-manager, human, or a named session
outbox/              archived inbox messages
exchanges/           EX-<yyyymmdd>-<nnn>-<mode>-<slug>.md, one per session-mode request
digests/             project digests and catch-up reports (newest 20 kept)
```

### Entries

Each system file starts with `# <id> — <kind>` and `Updated: YYYY-MM-DD`. An entry is a `### <ID> — <title>` heading followed by `- Since: YYYY-MM-DD (<sha7>)`, `- Status: open | resolved (<date>, <sha7>) | superseded by <ID> (<date>: <reason>)`, `- Evidence: …`, and free text. Ids are never reused.

Entries, decision records, systems, briefs and exchanges are never deleted. Superseding keeps the old text and adds a dated `Status: superseded by …` line. The only permitted deletion is pruning digests beyond the newest 20. `check_kb.py --record` stores per-file entry counts, so a deletion surfaces later as error E07.

### Adapting the layout

Each change below is recorded as a decision record.

- **New system:** `kb_init.py --add-system <id> --paths p1,p2 [--kind feature]`.
- **Split:** `kb_init.py --split OLD --into A,B --paths-A … --paths-B …`. OLD is marked `split`, keeps its folder, and each of its files gets a `Superseded:` line; open entries are copied to the new systems and the originals superseded.
- **Merge / rename:** `kb_init.py --merge A,B --into C`. A rename is a merge of one.
- **Retire:** `status: retired`; the folder stays.
- Extra files in a system folder (`contracts.md`, `runbook.md`) are allowed.

### `state.json` (`mighty-ops-kb/1`)

```json
{
  "schema": "mighty-ops-kb/1",
  "kb_dir": "mighty-ops",
  "commit_policy": "auto",
  "last_synced_commit": "<sha40> | null",
  "pending_sync": null,
  "first_run": {"status": "pending|in_progress|partial|done", "head": "<sha40>", "passes_done": []},
  "noise_paths": ["orchestration/"],
  "systems": [
    {"id": "api", "name": "HTTP API", "kind": "feature|cross-cutting|infra|data",
     "paths": ["src/app/api/"], "tests": ["tests/api/"],
     "status": "active|split|merged|retired", "superseded_by": [], "derived_from": [],
     "health": "green|amber|red|unknown", "health_reason": "…",
     "counts": {"findings": 0, "limitations": 0, "todo": 0, "done": 0, "decisions": 0}}
  ],
  "health": {"overall": "…", "kb_check": "clean|warnings|errors|unknown"},
  "counters": {"dr": 0, "exchange_seq": {}, "brief_seq": {}}
}
```

`paths` are POSIX prefixes relative to the project root (a trailing `/` is a directory; `*` patterns use fnmatch), and a file belongs to the system with the longest matching prefix. Writes are atomic (`state.json.tmp` then `os.replace`). Timestamps are UTC ISO-8601.

### Commit policy

`auto` (the default in a git repo): `git add <kb>` then `git commit -m "kb(<mode>): …" -- <kb>`, by pathspec only and never amending. `never`: changes stay uncommitted. Catch-up ignores commits that touch only the KB.

## 6. First run

**Light** when the project has fewer than 15 tracked files or at most 3 commits: write the skeleton, then ask the human what the systems are meant to be. Vision comes first.

**Heavy** otherwise, in resumable passes with a target of about 400 KB read:

| Pass | Work |
|---|---|
| 0 preflight | check the usage budget; `kb_init.py` creates the skeleton |
| 1 digest | `project_digest.py` writes a ≤300-line map plus JSON |
| 2 docs | READMEs, `CLAUDE.md`, `docs/**`, project skills (bounded) |
| 3 orchestration | `orchestration/` plan, handoff and friction in full; worker and archive **names and grep lines only** |
| 4 systems | pick 5–15 systems from the digest's candidates; `kb_init.py --systems-json` |
| 5 per system | entry file, top 3 files by inbound imports, test names, TODO/FIXME (≈25 KB each); write all six files |
| 6 history | recent log, date span, contributor count (never names or emails) → `done.md` |
| 7 cross-cutting | `harmony.md`, `glossary.md`, roadmap, KB README |
| 8 close | `check_kb.py --record`, `catchup.py --mark-synced`, report |

**System detection** (rules 1–4 and 7–8 are applied by `project_digest.py`; the model applies 5–6 and the final merge):

1. Package roots: `__init__.py` packages, `package.json` / `go.mod` / `Cargo.toml` / `pyproject.toml` workspaces.
2. Collection directories: each child of `bin/ skills/ packages/ apps/ services/ plugins/ cmd/ libs/ crates/`.
3. Vertical slices: a code-file stem present in two or more sibling layers (for example `orders` under `cli/`, `pipeline/` and `report/`).
4. Test mirrors: confirm only; never carve a system from tests alone.
5. README headings and CLI subcommands supply human names.
6. Orchestration phase titles and worker names, promoted only if they map to two or more code files.
7. Import clusters: used only to merge small candidates and to find hubs.
8. Infra directories: `config/ scripts/ migrations/ deploy/ infra/ docker/ .github/ ci/`.

Each heavy-run system gets at least three findings with `path:line` evidence, a labelled inferred vision with open questions for the human, at least one limitation (or an explicit "none found in a bounded read"), and a health value with a reason.

## 7. Catch-up

1. `catchup.py` computes `last_synced_commit..HEAD`, maps every changed path to a system, and writes a report plus `pending_sync`. It never advances the baseline on its own (except when nothing outside the KB and noise paths changed).
2. The model updates the KB **most important first**, so a cut-short run has still fixed the dangerous things:
   1. **Regression flags:** test functions dropped (checked at every commit in the range that touched the file, not just at the endpoints), test files deleted, hub or cross-cutting modules changed, files named in a `harmony.md` contract changed.
   2. **Changed systems**, most-changed first (at most 8 per run): read the diffs on the report's read list; update findings, limitations, done and todo; then `catchup.py --done <id>`.
   3. **Unmapped paths and new-system candidates:** map them, or create a system.
   4. **Orchestration (kept separate as noise):** `plan.md` and `handoff.md` diffs, falsified facts from new worker results, decision acknowledgements, and brief acknowledgements.
   5. Changed rows of `harmony.md`, the roadmap, and the README health table.
3. `check_kb.py --record`, then `catchup.py --mark-synced`, which refuses (exit 7) until every changed system is done unless `--force` is given.

**Caps:** a read list of at most 10 files per system and 40 in total (non-test source first); at most 30 commit subjects; at most 10 new worker results. Ranges over 200 commits show counts only and recommend a chunked catch-up, processed four systems at a time with a commit after each batch.

**Rewritten history:** if the baseline is no longer an ancestor of `HEAD`, the merge-base is used. If the baseline commit is gone, `catchup.py` exits 5 ("baseline lost"), and the skill re-detects systems and re-baselines, with a decision record.

## 8. Session mode and the claude-orch handshake

### Response format

```
mighty-ops <mode> EX-yyyymmdd-nnn
KB: synced <sha7> = HEAD            (or)  PROVISIONAL: KB at <sha7>, HEAD <sha7>, N commits behind
Answer: 1–10 lines                  (decide: "Decision: …" then "Confidence: high|medium|low")
Why: ≤4 bullets, each citing a KB or repo path
Risks/limits touched: ≤4 bullets with ids
Conditions: what would change this answer          (decide, optional)
DR: <kb>/decisions/DR-nnnn-<slug>.md (accepted|proposed)
Record: <kb>/exchanges/EX-…md
```

Every request and its exact response are recorded in `exchanges/`.

### Decision authority

`decide:` makes the decision record `accepted` when the choice sits within existing visions and decisions. It makes it `proposed` (printed as `PROPOSED (needs human):`) with a note in `inbox/human.md` when the answer would change a vision or the roadmap, would be irreversible, or touches anything the human owns: secrets, real data, external accounts, spending. In human mode the human's decision binds; the skill records its objection under "Alternatives considered" and complies.

### Handshake with claude-orch's orch-manager

- **Brief.** `brief-next-manager` writes `inbox/orch-manager.md` (id `B-yyyymmdd-n`, ≤80 lines): system health, suggested units with the files each will own and its acceptance tests, binding decisions, limitations every worker prompt must repeat, and pending decision points. The orch-manager reads it before planning and never edits it. The brief is archived to `outbox/` once its id appears in a `plan.md` diff or a newer brief supersedes it.
- **Decisions.** The orch-manager asks `decide: <question>; options: …; constraints: … | from: orch-manager <session>`, preferably through an explore worker so the skill's reads stay out of the manager's context. It records the outcome under `## Decisions` in `plan.md`, or writes `→ OVERRIDE: <what> — <reason>`. On catch-up the skill fills the record's `Acknowledged by:` line, or supersedes it on an override and opens a limitation if the override carries risk.
- **Phase boundaries.** The orch-manager runs `catchup.py --dry-run`. Only `Status: provisional-candidate` triggers a catch-up, and it runs in a worker, never inline.

## 9. Quality bar

**A change compounds when it is:**

1. **Pinned** by a test that `done.md` names.
2. **Placed** in the system whose vision owns it, extending an existing mechanism rather than adding a parallel one.
3. **Contract stated**, with a row in `harmony.md`, if other systems rely on it.
4. **Knowledge kept**: whatever surprised the builder becomes a finding.
5. **Limits honest**: what it does not handle is a limitation with evidence.
6. **A reversible step**: big ideas are cut into steps that each leave the project working.

**Regression guards** (`review:` BLOCKs on the first four): test functions dropped without a decision record; a limitation or decision entry deleted; a harmony contract changed without a decision record or consumer tests; a done item reopened; health worsening or a system drifting while its dependents change.

**Health:** **green** has tests pinning its contract, no open high limitation, a recorded vision, and was synced in the last catch-up. **amber** has an open high limitation, no vision, a drifting flag, or depends on a changed hub. **red** has an open regression flag or a broken harmony edge. **unknown** has not been read yet.

**Decision records** (`decisions/DR-nnnn-<slug>.md`) carry Date, Status (`proposed | accepted | rejected | superseded by …`), Decided by, Asked by, Systems, Acknowledged by, and the sections Context, Decision, Reason, Alternatives considered, and Consequences. The full template is in [`skill/reference/decision-record.md`](../skill/reference/decision-record.md).

## 10. Budget awareness

The skill reads claude-orch's usage snapshot (`~/.claude/orch/limits.json`, or `orch limits` when available); `catchup.py` prints it as a `Budget:` line. With the 5-hour window below 70% it works normally. From 70% to 85% it answers sessions and runs bounded catch-ups only, and limits a first run to passes 0–4 (`partial`). At 85% or more, or with the 7-day window at 90% or more, it answers from the KB only and says when the window resets. With no data it proceeds, checkpointing the first run pass by pass.

## 11. Script reference

All scripts take `--project DIR` (default `.`) and `--kb DIR` where relevant, run git with `cwd=` (never `git -C`, never a shell), print UTF-8 markdown to stdout (JSON with `--json`), and print errors as one `error: <msg>` line on stderr. Shared exit codes: **0** ok, **2** usage error or KB not found, **3** not a git repo or git missing.

### `kb_init.py`

```
kb_init.py [--kb-dir mighty-ops] [--systems-json FILE | --systems id1,id2]
           [--claude-md append|skip|create] [--commit-policy auto|never] [--dry-run] [--json]
kb_init.py --add-system ID --paths p1,p2 [--kind KIND] [--name NAME]
kb_init.py --add-paths ID p1,p2
kb_init.py --split OLD --into A,B --paths-A … --paths-B …
kb_init.py --merge A,B --into C [--paths p1,p2]
```

Creates only missing files and never overwrites one, so a second run changes nothing. `--systems-json` accepts `project_digest.py --json` output or a bare list. Ids must match `^[a-z0-9][a-z0-9-]{0,39}$`. Exit **6**: KB directory mismatch, schema mismatch, or a non-empty, non-KB directory at the target.

### `project_digest.py`

```
project_digest.py [--max-lines 300] [--json] [--out FILE] [--exclude PREFIX ...]
```

Sections: Shape, Tree, Entry points, Tests, Docs, Orchestration & skills, Candidate systems, Vertical slices, Hubs & cross-cutting, Top system edges, Signals, Reading plan, Recent activity. When over `--max-lines`, the lowest-priority sections are trimmed first. It excludes `.git`, `.claude/`, the KB and vendored or generated directories, reads only directory names under `orchestration/workers/`, skips files over 1 MB, and works without git.

### `catchup.py`

```
catchup.py [--to REV] [--max-files 40] [--max-files-per-system 10] [--max-subjects 30] [--dry-run] [--json]
catchup.py --done ID[,ID...]
catchup.py --mark-synced [--force]
```

Report headings: `Regression flags`, `Changed systems`, `Project skills`, `Orchestration (separated)`, `Unmapped paths / new-system candidates`, `Read list`, `Commits`, `Next`. A `Status:` line reads `up_to_date`, `behind`, or `provisional-candidate`. Extra exits: **4** no baseline yet, **5** baseline lost, **7** `--mark-synced` with systems not done.

### `check_kb.py`

```
check_kb.py [--strict] [--quick] [--record] [--json]
```

Exit **0** clean (warnings allowed unless `--strict`), **1** errors, **2** no KB. `--quick` runs E01–E04 only. `--record` (with zero errors) stores entry counts and the check result in `state.json`.

| Code | Rule |
|---|---|
| E01 | `state.json` missing or invalid JSON |
| E02 | wrong `schema`, or a required key missing or of the wrong type |
| E03 | active system has no `systems/<id>/` folder |
| E04 | system folder lacks a required file |
| E05 | decision record lacks a Date, a valid Status, or a non-empty `## Reason` |
| E06 | `last_synced_commit` unknown to git |
| E07 | entry count below the recorded count (an entry was deleted) |
| E08 | duplicate entry id within a file |
| E09 | `decisions.md` links to a missing decision record |
| E10 | secret-like content (private keys, cloud or API keys, tokens, Luhn-valid card numbers) |
| E11 | health, kind or status outside its allowed values |
| E12 | `pending_sync.systems_done` is not a subset of `pending_sync.systems` |
| W01 | system folder not listed in state |
| W02 | KB behind `HEAD` by non-KB commits |
| W03 | inbox message older than 14 days |
| W04 | KB file over 400 lines |
| W06 | git checks skipped (not a git repo) |
| W07 | entry missing a `Since:` or `Status:` line |

### `scorecard.py`

```
scorecard.py [--kb DIR] [--json] [--out PATH]
```

Eight metrics from a claude-orch run (units, cost and explore share; resumed units; stalled units; permission denials; human questions; re-plans; `decide:` calls and the provisional share; test functions at `HEAD`), each with its source. With a KB it appends one row to `<kb>/scorecard.md` and writes the full report to `digests/`. Exit **2** when there is no `orchestration/` directory.

## 12. Testing

`tests/` holds a stdlib `unittest` suite (also runnable with pytest). The tests build real, throwaway git repositories in temporary directories with `make_repo()` from `tests/_fixtures.py`, using `git -c user.name=… -c user.email=…` so no global git configuration is read or written. They cover idempotent scaffolding, split and merge, digest detection rules, path grouping, regression probes, read-list caps, baseline handling under rewritten history, every `check_kb` rule, and the scorecard. Git-dependent cases are skipped when git is not installed.
