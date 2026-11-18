# Catch-up protocol

Use this on every invocation where a KB exists. It brings the KB up to date with the commits that landed since `last_synced_commit`, before I answer or act. `<base>` is this skill's directory and `<kb>` is the KB directory. Run every command from the project root, with `--project .`. Never use `cd` chains or `git -C`.

## Contents
1. The sequence (exact commands)
2. Update order (step 3 in detail)
3. Stale-KB rule for session modes
4. Grouping and noise
5. Caps and bounded reading of big diffs
6. Rewritten history
7. Chunked catch-up for big ranges
8. Exit codes

## 1. The sequence
```
python3 <base>/scripts/catchup.py --project .                 # 1. report; writes pending_sync + digest
                                                               # 2. if Status: up_to_date, stop
                                                               # 3. update the KB (section 2), and per system:
python3 <base>/scripts/catchup.py --project . --done ID[,ID...]
python3 <base>/scripts/check_kb.py --project . --record       # 4. must exit 0
python3 <base>/scripts/catchup.py --project . --mark-synced   # 5. advance the baseline
git add <kb>                                                   # 6. commit per policy (auto)
git commit -m "kb(catchup): sha7..sha7, N commits" -- <kb>
```
1. **Run** `catchup.py` and read its report (≤150 lines). It does **not** advance the baseline. It writes `state.pending_sync` and `<kb>/digests/catchup-YYYYMMDD-SHA7.md`. The report's headings are: `# Catch-up …`, `Budget:`, `Status:`, `## Regression flags`, `## Changed systems`, `## Project skills`, `## Orchestration (separated)`, `## Unmapped paths / new-system candidates`, `## Read list`, `## Commits`, `## Next`.
2. **Up to date:** if `Status: up_to_date`, stop. There is nothing to update. If there were 0 non-noise commits and no flags, the script has already advanced `last_synced_commit` itself.
3. **Update the KB** in the order of section 2. After finishing each system, run `catchup.py --done ID` (several ids can be given, comma-separated). The ids must be in `pending_sync.systems`, else it exits 2.
4. **Check:** `check_kb.py --record` must exit 0. Fix every ERROR line first; they are mine.
5. **Mark synced:** `catchup.py --mark-synced`. It refuses with exit 7, listing what is missing, unless every system in `pending_sync.systems` is in `systems_done`. `--force` overrides and records the skipped ids in the digest. Use `--force` only when a skipped system has a todo explaining why (for example "binary assets only").
6. **Commit** per `commit_policy` (`kb-layout.md` §6). With `never`, skip it.

`catchup.py --json` prints the same data as JSON (keys: `from`, `to`, `commits`, `commits_total`, `status`, `budget`, `systems`, `orchestration`, `skills`, `unmapped`, `new_system_candidates`, `regression_flags`, `read_list`, `subjects`). Use it only when a script needs the data. Read the markdown yourself.

## 2. Update order (step 3)
The most important work comes first, so a run that is cut short has still fixed the dangerous things.

**a. Regression flags** (removed test functions, checked commit by commit, so the flag names the commit that dropped them even when the file was added in the same window; deleted test files; a changed hub or cross-cutting module, files in a `harmony.md` contract changed). For each flag:
- add a limitation or todo entry to the system, citing the flag line and the commits;
- set the system's `health` to amber or red with a `health_reason` (the definitions are in `quality-bar.md`);
- if `orchestration/` exists, append a line under `## Since this brief` in `<kb>/inbox/orch-manager.md` (create the section if it is missing).

A test-function drop that a DR explains is not a regression. Cite the DR and stay green.

**b. Changed systems**, most-changed first, cap 8 per run. For each file on the report's Read list for that system:
```
git diff FROM..TO -- PATH
```
If that diff is >400 lines, use instead:
```
git diff --stat FROM..TO -- PATH
git diff -U0 FROM..TO -- PATH          # read only the first 200 lines
```
Then update the system's files:
- `findings.md`: new facts, each with `path:line` or the commit;
- `limitations.md`: mark what is fixed `Status: resolved (DATE, SHA7)`, and add new limitations;
- `done.md`: the commits plus the tests that pin them;
- `todo.md`: close the matching `T-n` (`Status: resolved …`).

Then run `catchup.py --done ID`.

**c. New-system candidates and unmapped paths.** Map each one to an existing system:
```
python3 <base>/scripts/kb_init.py --project . --add-paths ID p1,p2
```
Or create a new system (`kb_init.py --add-system ID --paths p1,p2 --kind feature`, plus a DR; see `kb-layout.md` §5). Never leave a path unmapped twice in a row without a todo in README.md.
Mapping into an existing system needs no DR when the owner is obvious: the path sits under the system's own dir, or it is a test named after the system. Write a DR (`accepted`, `Systems:` naming every system you considered) when the choice is not obvious. Examples: the report also lists the path's top dir as a `candidate:` and you decline it, two systems could own it, or you attach a new top-level dir to an existing system. The next catch-up then knows why the path went where it did.

**d. Orchestration** (kept separate from noise; only if the report lists it).
- `git diff FROM..TO -- orchestration/plan.md orchestration/handoff.md` (read ≤300 lines).
- For each worker result added in the range (listed by the report, cap 10): `Grep "FALSIFIED"` in that `result.md`. Record each falsified fact as a finding of the owning system. Never read the bodies.
- Lines added to plan.md under `## Decisions` that cite a DR id: fill that DR's `- Acknowledged by:` line with the plan.md line. If the line says `→ OVERRIDE:`, set the DR to `Status: superseded by manager override (DATE: reason)`, and open a limitation or todo if the override carries risk.
- A brief id (`B-…`) cited in the plan.md diff: move `inbox/orch-manager.md` to `outbox/DATE-orch-manager-BRIEFID.md` (see `interaction-protocols.md` §4).

**e. Cross-cutting pages.** Update only the rows that changed: `harmony.md`, `roadmap/roadmap.md`, and the `README.md` health table and last-sync line. Then re-check each DR filed `proposed` only because the KB was provisional (its exchange record says `provisional: yes`): if the caught-up KB still supports it and it needs no human, set it `accepted (after catch-up DATE)` and append an index line; otherwise leave it proposed with a line in `inbox/human.md`, or supersede it.

**f. Scorecard** (full catch-up only, when `orchestration/` exists). After `--mark-synced` run `python3 <base>/scripts/scorecard.py --project .`.
It prints a `metric | value | source` table, appends one row to `<kb>/scorecard.md` (earlier rows are never rewritten) and writes `<kb>/digests/scorecard-YYYYMMDD-HHMM.md`.
Commit both with the KB. Exit 2 = no `orchestration/`: skip. Do not interpret the numbers;
the human reads `<kb>/scorecard.md` every few runs to judge changes to the dev system.

**Project skills.** Changed `.claude/skills/*/SKILL.md` files are listed under `## Project skills`. Read them in full (cap 200 lines each), because they are procedures. Record changed procedures as findings of the owning system.

## 3. Stale-KB rule (session modes: ask, decide, review, brief-next-manager)
Run step 1. Then:
- `Status: up_to_date`: answer.
- ≤30 non-noise commits **and** ≤40 non-noise changed files: do a **bounded update** first. That means step 3a, then step 3b only for the systems the question touches plus every system with a regression flag, then `--done` for those. Run `--mark-synced` only if every system in `pending_sync.systems` was processed. Otherwise leave `pending_sync` in place for the next run. Then answer.
- More than that (the report says `Status: provisional-candidate`): do **not** catch up inside the caller's turn. Answer from the KB with the second line `PROVISIONAL: KB at SHA7, HEAD SHA7, N commits behind`. File any DR as `proposed`, never `accepted`, with `Decision:` beginning "PROPOSED (provisional KB):" and `provisional: yes` in the exchange record (§2e re-checks it later). Append the line "run `/mighty-ops-system-manager catchup`" to `<kb>/inbox/orch-manager.md`, or to `<kb>/inbox/human.md` if there is no `orchestration/`.

## 4. Grouping and noise
`catchup.py` maps every changed path to a system by longest prefix. These buckets are kept separate, in this order:
1. the KB dir: dropped (catch-up never learns from its own commits);
2. `noise_paths` (default `orchestration/`): the `## Orchestration (separated)` section;
3. `.claude/skills/`: the `## Project skills` section;
4. unmatched paths: `(unmapped)`.

Test files count toward the system whose `tests` prefixes match. Failing that, they count toward the system whose id appears in the file name (`test_ID`), and otherwise toward `(tests-unmapped)`. Commits that touch only KB or noise paths count in `commits_total` but not in `commits`.

## 5. Caps and bounded reading of big diffs
- Read list: ≤10 files per system and ≤40 in total, non-test source first, then by lines changed.
- Commit subjects: ≤30 (the most recent), grouped by system.
- Orchestration: ≤10 new worker results listed.
- More than 200 commits in the range: the report shows per-system counts but no subjects, and recommends a chunked catch-up (section 7).
- A single file's diff over 400 lines: `--stat` plus the first 200 lines of `-U0` (section 2b).
- Up to 8 systems per run in step 3b. The rest wait in `pending_sync` for the next run.
- Binary files count as files with 0/0 lines. Do not diff them.
- Say in the summary what was not read.

## 6. Rewritten history
If `last_synced_commit` no longer exists, or is not an ancestor of HEAD:
- if it still exists, `catchup.py` uses `git merge-base LAST HEAD` as `from` and says so;
- otherwise it exits 5 ("baseline lost"). Then run only first-run passes 1, 4 and 8 (`first-run-protocol.md`): re-digest, add the missing systems, and re-baseline with `--mark-synced`. Record a DR "baseline lost on DATE".

## 7. Chunked catch-up (human or `catchup` mode, big ranges)
Process `pending_sync.systems` in batches of 4. After each batch:
```
python3 <base>/scripts/catchup.py --project . --done a,b,c,d
git add <kb>
git commit -m "kb(catchup): batch a,b,c,d" -- <kb>
```
A later invocation resumes from `pending_sync`. If new commits landed meanwhile, rerunning `catchup.py` keeps the original `from`, moves `to` to the new HEAD, and keeps `systems_done` only for systems with no further changes. Finish with steps 4–6 of section 1. The `catchup` mode summary to the human is ≤20 lines: the range, the systems updated, the flags, health changes, what was not read, and what is still pending.

## 8. Exit codes (`catchup.py`)
| code | meaning | what I do |
|---|---|---|
| 0 | up to date, or report produced | continue |
| 2 | usage error, KB not found, or `--done` id not in pending | check the args; with no KB, follow `first-run-protocol.md` |
| 3 | not a git repo, or git missing | catch-up is impossible; say so, answer from the KB |
| 4 | no baseline (`last_synced_commit` null) | finish the first run, or run `--mark-synced` if the first run is done. The `Budget:` line is still printed (first-run pass 0 uses it) |
| 5 | baseline lost | section 6 |
| 7 | `--mark-synced` with systems not done | finish them, or `--force` with a todo per skipped id |
