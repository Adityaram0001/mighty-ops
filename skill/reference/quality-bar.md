# Quality bar

What I hold every change to: what "compounds" means, the regression guards, the harmony checks between systems, how `review:` reaches its verdict, the health values, and the budget thresholds.

## Contents
1. What "compounds" means
2. Regression guards
3. Harmony checks
4. Review verdict rules
5. Health definitions
6. Budget thresholds

## 1. What "compounds" means
A change compounds when, after it, the *next* change in the same area is cheaper and safer. Concretely:
1. **Pinned.** New behaviour has a test that would fail if it regressed, and `done.md` names that test.
2. **Placed.** It lives in the system whose vision owns it. It extends an existing mechanism rather than adding a parallel one. Two ways of doing one thing is a limitation entry.
3. **Contract stated.** If other systems rely on it, `harmony.md` has the row: what is relied on, and which tests pin it.
4. **Knowledge kept.** Whatever surprised the builder is a finding, so nobody rediscovers it.
5. **Limits honest.** Anything it does not handle is a limitation with evidence, not a silent gap.
6. **Reversible step.** Big ideas are cut into steps that each leave the project working.

When triaging an idea, say which of the six it would satisfy as proposed, and what the smallest first step is that satisfies all six.

## 2. Regression guards
Each guard produces a flag. `review:` BLOCKs on guards 1–4.
1. Test functions in a system dropped (the catch-up probe) without a DR explaining it. The probe walks every commit in the window that touched a test file, so a file that gains tests and then loses some within one window is still flagged, with the commit that dropped them.
2. A limitation or decision entry deleted (`check_kb.py` E07).
3. A `harmony.md` contract changed without a DR, or without updating the consumers' tests.
4. A done item reopened (the same bug fixed twice). The limitation is upgraded to `high`.
5. Health worsened, or a system stayed untouched across 3 or more catch-ups while its dependents changed (amber, "drifting").

A flag becomes an entry: a limitation or todo in the affected system, a health change with a reason, and (if `orchestration/` exists) a line in `inbox/orch-manager.md` under `## Since this brief`.

## 3. Harmony checks
Run these on every `decide:`, `review:` and catch-up, for the systems that changed.

`harmony.md` holds one table:
```
| from | to | relies on (contract) | pinned by tests | DR |
```
For each changed system:
1. List its consumers (rows whose `to` is this system).
2. Check the contract column against the diff. A changed signature, file format, path, env var, CLI flag or output heading counts as a contract change.
3. Check that the "pinned by tests" tests still exist (`Grep` the test names). A missing pin is a limitation.
4. Flag duplicated concepts: two glossary terms with the same meaning, or one term owned by two systems.
5. Flag mirrored copies that must change together, for example two config dirs kept byte-identical by hand. A change to one without the other is a broken edge.
6. Hubs (fan-in ≥⅓ of systems): when a hub changes, every consumer goes amber until a test run is cited.

A row with "none" under "pinned by tests" is itself a limitation (severity medium) of the `to` system.

## 4. Review verdict rules (`review:`)
Targets: path(s), an `A..B` commit range, a worker `result.md`, `orchestration/plan.md`, or `phase N` (that phase's units in plan.md).
- **BLOCK:** a regression flag (guards 1–4), a contract change with no DR, or a broken harmony edge.
- **CONCERNS:** any compounding criterion of §1 not met (no pinning test named, a parallel mechanism, a missing harmony row, a new limitation not recorded); a plan unit that builds on an UNVERIFIED claim; a change that contradicts a `vision.md` or an accepted DR without a new DR.
- **PASS:** none of the above. Still list up to 3 low findings if they are useful.

Findings are written `- [high|medium|low] finding (cite)`, ≤10 in session mode. Every finding cites a KB entry or a `path:line`. The review records what it found: new limitations, todos and flags go into the KB in the same turn.

Reviewing a worker `result.md`: check its "Claims verified / falsified" against the KB. Each FALSIFIED claim becomes a finding of the owning system. A claim that contradicts a KB finding means one of the two is wrong: verify it, then supersede the wrong one.

## 5. Health definitions
Decide top-down. The first row that matches wins, so every system that has been read gets exactly one value.
| health | meaning |
|---|---|
| **red** | has a regression flag or a broken harmony edge open |
| **amber** | anything read that is not red and misses one or more green conditions. Examples: an open high limitation, no tests pinning its contract, no vision at all, a drifting flag, or being a consumer of a changed hub |
| **green** | has tests pinning its contract, no open high limitation, a recorded vision, and was synced in the last catch-up |
| **unknown** | has not been read yet |

- **Recorded vision:** an "Inferred vision (inferred)" section counts as recorded. Only a `vision.md` that is still a stub counts as "no vision". Open vision questions do not stop a system being green.
- **Synced:** on a first run, the close (pass 8, `--mark-synced`) counts as the last catch-up. A system read in pass 5 is synced.
- A system with no tests at all is amber, with `health_reason` "no tests pin its contract", even if it has no limitation.

`health_reason` is one line naming the deciding entry (for example "L-4 high open: retry loop unbounded"). `health.overall` is the worst health among the active systems, in the order red > unknown > amber > green, and `catchup.py --mark-synced` computes it. An unknown system keeps the KB from being green, but an amber one never hides a red. A system leaves red only when the flag's entry is resolved or a DR explains it.

## 6. Budget thresholds
Read the budget with `orch limits` if `orch` is on PATH and allowed. Otherwise use the `Budget:` line of `catchup.py`'s report, which reads the orch limits file (`~/.claude/orch/limits.json`). The line is printed even when catchup exits 4 because no baseline exists yet, which is the normal state during a first run. A `Budget: unknown` line means no data.
| five_hour used | seven_day used | what I do |
|---|---|---|
| <70% | <90% | normal |
| 70–85% | <90% | session answers plus bounded catch-up only. The first run is limited to passes 0–4 (`first_run.status=partial`) |
| ≥85% | any | answer from the KB only (provisional if stale): no first run, no chunked catch-up. Say when it resets |
| any | ≥90% | the same as the row above |
| unknown | unknown | continue, but run the heavy first run in passes with checkpoints (commit or save after each) |
