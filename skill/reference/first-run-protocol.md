# First-run protocol

Use this for `init`, or for a bare invocation when no KB exists. It explains how to understand a whole project in bounded passes and what to write for each system. `<base>` is this skill's directory and `<kb>` is the KB directory (default `mighty-ops`). Run every command from the project root, without `cd` chains. Never run the heavy first run inside another session's turn (ask/decide/review). Those modes answer provisionally and recommend `init`.

## Contents
1. Light vs heavy
2. Heavy passes 0–8 (bounded)
3. System detection heuristics
4. What gets written per system (minimums)
5. Report template
6. Resuming a cut-short run

## 1. Light vs heavy
To choose, print the digest to the terminal first, writing no file: `python3 <base>/scripts/project_digest.py --project .`. (Pass 1 writes it into the KB later, after pass 0 has created `<kb>/digests/`.) The run is **light** only when the title and Shape lines show all three: <15 tracked files, **and** ≤3 commits, **and** <50 KB of source+docs bytes. Otherwise it is **heavy**. A squashed import can have 2 commits and 70 KB of real code, so commit count alone never makes a run light.

**Light run** (one pass):
1. `python3 <base>/scripts/kb_init.py --project .` (add `--systems a,b` once the planned components are known).
2. Write `README.md` and confirm `state.json` exists.
3. In human mode, ask what the systems are meant to be. Vision comes first: record the human's words in each `vision.md`, quoted with "(human, DATE)".
4. Each planned component becomes a system with an empty findings file.
5. `python3 <base>/scripts/check_kb.py --project . --record`, then `python3 <base>/scripts/catchup.py --project . --mark-synced`, then commit per policy.

**Heavy run:** passes 0–8 below. The target is **≤400 KB read (~100K tokens)**. Keep a running byte count and report it. Each pass ends by appending its name to `state.json` `first_run.passes_done`: `preflight`, `digest`, `docs`, `orchestration`, `systems`, `system:ID` (one per system), `history`, `cross-cutting`, `close`. A dead session then resumes at the next pass. A pass that has nothing to do (pass 3 with no `orchestration/`) is still appended, so resume does not stop on it. Passes 0–7 are recorded by hand: edit `state.json` with the Edit tool, append the name to the array, and keep the JSON valid. `check_kb.py --quick` catches a broken file (E01). `catchup.py --mark-synced` appends `close` itself (pass 8).

**Dates.** Every date the KB writes is UTC: `Updated:` lines, DR `Date:`, digest file names (`first-run-YYYYMMDD`), exchange ids. The scripts already use UTC. Take YYYYMMDD from `python3 -c "import time; print(time.strftime('%Y%m%d', time.gmtime()))"`, not from the local clock, or the dates will mix near midnight.

## 2. Heavy passes (in order)

**Pass 0 — preflight** (pass name `preflight`).
1. `python3 <base>/scripts/kb_init.py --project .` creates the skeleton and sets `first_run.head = HEAD` and status `in_progress`. If it exits 6 with "not a KB", rerun with `--kb-dir mighty-ops-kb`. With the default `--claude-md append` it adds the pointer line only to an existing `CLAUDE.md`. If the project has no `CLAUDE.md`, nothing is written: say so in the report, and do not create one unless the human asks (`--claude-md create`).
2. Check the budget: `orch limits` if `orch` is on PATH and allowed. Otherwise run `python3 <base>/scripts/catchup.py --project .`. Before the first sync it exits 4 ("no baseline"), which is expected here, but it still prints a `Budget:` line from the orch limits file. If both fail, the budget is unknown.
3. If five_hour ≥85% or seven_day ≥90%: stop, and tell the human when to come back (the reset time).
4. If five_hour is 70–85%: run passes 1–4 only, then set `first_run.status` to `partial`.
5. If the budget is unknown: continue, but commit (or save) after every pass.

**Pass 1 — digest.**
```
python3 <base>/scripts/project_digest.py --project . --out <kb>/digests/first-run-YYYYMMDD.md
python3 <base>/scripts/project_digest.py --project . --json --out <kb>/digests/first-run-YYYYMMDD.json
```
`--out` is relative to the current directory, not to `--project`. Run from the project root as shown. If you must point `--project` elsewhere, give `--out` the same prefix (`--project ../app --out ../app/<kb>/digests/…`).
Read the markdown digest (≤300 lines). Do not read the JSON. It feeds pass 4.

**Pass 2 — docs.**
- Read root `README*`, `CONTRIBUTING*`, `CLAUDE.md` and `docs/**/*.md`. Read the full text of files ≤20 KB. For a larger file, read its headings (`Grep "^#" -n`), the first 150 lines, and the sections whose headings name a candidate system from the digest (read by line range). A 75 KB README often keeps its feature sections far past line 300.
- Read `.claude/skills/*/SKILL.md` in full (cap 200 lines each). They are the project's procedures.

**Pass 3 — orchestration** (only if `orchestration/` exists. If it does not, append `orchestration` to `passes_done` and move on. Passes 6 and 7 then have no plan or handoff to draw on, so see the roadmap rule in pass 7).
- Read `plan.md`, `handoff.md`, `friction.md` and `progress.md` in full.
- `questions.md`: headings only.
- `archive/` and `workers/`: **file names only** (Glob).
- `Grep "FALSIFIED"` over `orchestration/workers/*/result.md` (head_limit 60).
- `Grep "^#"` over `orchestration/archive/*.md` (head_limit 80).
- Never read worker or archive bodies.

**Pass 4 — systems.**
- Decide the system list from the digest's "Candidate systems" table using §3. Target 5–15 systems (≤6 if the project has <30 files).
- Write `<kb>/digests/systems.json`: the digest JSON's `systems` array, edited (rename, merge, drop, add). Each item needs `id` (`^[a-z0-9][a-z0-9-]{0,39}$`), plus `name`, `kind`, `paths` and `tests`. `--systems-json` also accepts the whole digest object and reads its `systems` key, but pass the edited array: the raw list is a candidate list, not a map.
- Things the digest leaves to you: the `core` candidate (loose root modules) has `paths: []`, so list its root files by hand (one path per file) or attach them to the system that uses them. Slice candidates list their stem files as `paths`. Keep those; never widen a slice to the whole layer dirs, or longest-prefix ownership gives every layer file to several systems. `tests` holds the test-mirror patterns (rule 4) when the digest found any. Check them, and write fnmatch patterns (`tests/unit/test_loans*`) for the systems it missed.
- `python3 <base>/scripts/kb_init.py --project . --systems-json <kb>/digests/systems.json`
- Record the carving choices (which layers vs slices, merges, where root files went) in DR-0001 "Initial system map". Index DR-0001 in the `decisions.md` of **every** system it creates, because it is each system's birth record.

**Pass 5 — per system** (largest first; one pass entry `system:ID` each).
- Budget per system = (400 KB − bytes already read) ÷ systems left, at least 10 KB. On a 15-system project that is about 15 KB, not 25 KB.
- Signatures first: `Grep "^(def |class |[A-Z_]+ =|export )" -n` over its paths. Then read targeted line ranges. Read whole files only while the system's budget lasts, starting with its init or index file and the digest's "Reading plan" files (cap 600 lines each).
- Test **names** only: `Grep "def test_|it\(|test\("` over its test paths (head_limit 80).
- `Grep "TODO|FIXME|XXX"` over its paths (head_limit 20).
- Write all six files to the minimums in §4. Set `health` and `health_reason` in `state.json`.

**Pass 6 — history.**
- From the project root: `git log --oneline -50`, and `git log --format=%ad --date=short --reverse` keeping only the first and last date.
- When the project is not your current directory, do not use `git -C` or `cd … &&`. Run git through Python with `cwd` instead:
  `python3 -c "import subprocess,sys; print(subprocess.run(['git','log','--oneline','-50'], cwd=sys.argv[1], capture_output=True, text=True).stdout)" <project>`
  For anything longer (per-system subjects, date ranges), write a small script in your scratch dir and run that script.
- The number of contributors only (`git shortlog -sn HEAD | wc -l`). Never record their names or emails.
- Per-system commit counts must use longest-prefix ownership, as `catchup.py` does. `git log -- pkg/` also counts every commit under the sub-systems inside `pkg/`.
- Map completed phases and large commits to `done.md` entries (cap 15 per system).

**Pass 7 — cross-cutting.**
- `harmony.md`: from the digest's "Top system edges" and "Hubs & cross-cutting" sections plus what pass 5 found. One row per relied-on contract, with the tests that pin it, or "none" (which is a limitation).
- `glossary.md`: ≤40 terms, each with its owning system.
- `roadmap/roadmap.md`: from handoff "next" items, open todos and the plan's objective. With no `orchestration/` (no plan, no handoff) the roadmap is only your ordering of the open todos: head it "(inferred)" and add one open question for the human about direction.
- `README.md`: system map and health.
- Map every `friction.md` line that is about code (not process) to a finding or limitation of a system, citing `orchestration/friction.md:LINE`.

**Pass 8 — close.**
1. `python3 <base>/scripts/check_kb.py --project . --record` must exit 0. Fix every ERROR it prints first.
2. `python3 <base>/scripts/catchup.py --project . --mark-synced` sets `last_synced_commit = first_run.head`, sets `first_run.status` from `in_progress` to `done` with `finished_at`, appends `close` to `passes_done`, and sets `health.overall` to the worst health among the active systems (`quality-bar.md`).
3. Check `state.json`. If the run was `partial` and has now finished, set `first_run.status` to `done` yourself and append `close`, because mark-synced only closes an `in_progress` run.
4. Commit per policy. Name `CLAUDE.md` in the pathspec only if kb_init changed it (pass 0), because a pathspec naming a missing file makes `git add` fail: `git add <kb> [CLAUDE.md]`, then `git commit -m "kb(init): first run" -- <kb> [CLAUDE.md]`.
5. Report to the human (§5).

## 3. System detection heuristics
`project_digest.py` applies rules 1–4 and 7–8 mechanically. Apply rules 5–6 and the final merge yourself. The rules are in priority order:
1. **Package roots** (confidence 0.9): dirs with `__init__.py` at depth 1 or under `src/X`; `package.json`, `go.mod`, `Cargo.toml` and `pyproject.toml` workspace members. Each immediate sub-package is a candidate. Loose root modules form one `core` candidate.
2. **Collection dirs** (0.85): each child of `bin/ skills/ packages/ apps/ services/ plugins/ cmd/ libs/ crates/` is a candidate.
3. **Vertical slices** (0.75): a module stem present as a **code** file in ≥2 sibling sub-packages is a feature candidate spanning those layers. Its `paths` are those stem files, and the layer dirs are then flagged `layer`. Data files with the same stem (a YAML in `config/` and `pkg/data/`) do not make a slice. Stoplist: `base, common, utils, util, helpers, types, models, core, main, index, init, report, extract, config, test`.
4. **Test mirror** (0.7, confirm-only): `test_NAME*`, `NAME.test.*`, `NAME_test.*`, or a `NAME/` dir under a test dir raises confidence, and the digest writes them into the candidate's `tests` (for example `tests/unit/test_NAME*`). Never carve a system from tests alone.
5. **Docs and CLI headings** (0.6, naming): README `##`/`###` headings and CLI subcommands supply human names.
6. **Orchestration signals** (0.5): plan phase titles and worker-name tokens (strip `pN-NN-`). Promote a concept to a system only if it maps to ≥2 code files.
7. **Import clusters** (0.4): use only to MERGE small co-clustering candidates and to flag hubs. Never use them to split.
8. **Infra dirs** (0.8): `config/ scripts/ migrations/ deploy/ infra/ docker/ .github/ ci/` become infra systems. A config subdir named after a system attaches to that system.

**Classification:**
- `cross-cutting`: root modules; shared names (`config|settings|utils?|common|shared|core|db|models|paths|ids|types|constants|errors|log(ging)?|helpers|lib`); or code with inbound edges from ≥⅓ of systems and in ≥2×out.
- `data`: no code.
- `infra`: in the infra list.
- Otherwise `feature`.

Always exclude `orchestration/`, `.claude/`, the KB dir, and vendored and generated dirs (`node_modules .venv venv dist build target __pycache__ .git …`).

**Layers vs slices.** When a project is layered (for example `cli/ pipeline/ report/`) and the same feature stems recur across the layers, give the slices their own folders. A layer-only map hides where a feature's logic lives.
**Example:** in a project layered as `cli/ pipeline/ report/`, the slices `orders`, `invoices` and `refunds` cut across the layers. The KB needed folders for the slices, not only for the layers.

## 4. What gets written per system (minimums for a heavy first run)
| file | minimum |
|---|---|
| `findings.md` | ≥3 entries with `path:line` evidence: entry points, contract, test layout |
| `vision.md` | an "Inferred vision" section (labelled "(inferred)"), plus "Open vision questions for the human" (≤3) |
| `limitations.md` | ≥1 entry, or the explicit line "none found in a bounded read; not proven absent" |
| `todo.md` | from TODO/FIXME, friction and handoff (cap 10), each with acceptance criteria |
| `done.md` | cap 15, each with commit(s) and the tests that pin it |
| `decisions.md` | the DR-0001 index line, plus index lines for retroactive DRs taken from plan.md Re-plans (`Status: accepted (retroactive from SOURCE)`, one status word plus a note, see `decision-record.md`) |
| `state.json` | `health` plus a one-line `health_reason` (`quality-bar.md` health table) |

**Filling many stubs.** kb_init writes six stubs per system, and the Write tool refuses to overwrite a file you have not Read. For a heavy KB (10+ systems), do not Read 90 stubs one by one. Write the content into one bundle file in your scratch dir, then run a small scratch Python script that splits it into the stub files. Then read back one or two files to spot-check the result. `check_kb.py` validates the rest.

## 5. Report template (≤40 lines, to the human)
```
mighty-ops init — KB at <kb>/ (HEAD sha7), first run done|partial
Systems (N):
| system | kind | health | reason |
Most useful findings (3–5, each with path:line)
Top limitations (≤5, each with id and severity)
Not read: <what was skipped and why: worker bodies, large files, systems past budget>
Bytes read: ~N KB of 400 KB budget · passes: <passes_done>
CLAUDE.md: pointer added | already present | absent, not created
Open vision questions for you: <≤3>
Next: <what I suggest we discuss first>
```

## 6. Resuming a cut-short run
- `first_run.status` other than `done`: read `first_run.passes_done` and resume at the first pass not in it. Do not redo passes that are done. Reread only the digest (pass 1 output) to restore context.
- `partial` (the budget stopped it at pass 4): resume at pass 5 when the budget allows.
- A `system:ID` pass is done only when all six files meet §4. Otherwise redo that one system.
- If HEAD has moved since `first_run.head`, finish the first run against `first_run.head` and close it (pass 8). The next invocation's catch-up picks up the newer commits.
