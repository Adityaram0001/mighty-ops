# mighty-ops

A Claude Code skill that gives a project a long-lived **operations-and-systems manager** with a persistent memory.

`mighty-ops-system-manager` keeps a knowledge base (KB) inside the project: one folder per system with its findings, vision, limitations, to-dos, completed work and decisions, plus a roadmap, dated decision records, and an inbox for other sessions. Before it answers anything it catches itself up from git history. Its job is to make sure every new idea is built in the place where it compounds, without regressing the systems around it.

It is designed to work alongside [claude-orch](https://github.com/Adityaram0001/claude-orch). claude-orch runs long jobs as many short worker sessions and forgets system-level knowledge between runs. This skill keeps that knowledge, answers the orch-manager's critical design decisions with citations, and briefs each new manager before it plans. It also works on its own in any project.

It is plain files and scripts: a skill prompt, six reference documents, and a handful of Python 3 standard-library scripts. No daemon, no database, no network calls, no third-party packages.

## Why

An agent that starts every session from zero rediscovers the same facts, repeats the same mistakes, and makes local decisions that quietly break other parts of the system. A human architect avoids that by remembering how the pieces fit together and writing down why things are the way they are. This skill does that job for a codebase that is mostly changed by agents:

- **Memory is files.** Every conclusion worth keeping lands in the KB in the same turn, with `path:line` or commit evidence.
- **It catches up before it speaks.** New commits are grouped per system, and dropped tests, deleted test files and changes to shared contracts are flagged as possible regressions.
- **It keeps the systems in harmony.** Cross-system contracts live in one table. Every decision and review checks them.
- **It is honest about limits.** Limitations are recorded with severity and evidence and are never deleted, only superseded with a dated reason.
- **It is cheap to call.** Other sessions get answers of 30 lines or fewer that cite the KB instead of pasting it.

## Requirements

- [Claude Code](https://code.claude.com/docs) with skills support.
- `python3` 3.9 or newer (standard library only) and `git` on `PATH`.
- macOS or Linux.
- Optional: [claude-orch](https://github.com/Adityaram0001/claude-orch) for multi-session runs. Its `orch-manager` skill already includes the handshake described below.

## Install

```bash
git clone https://github.com/Adityaram0001/mighty-ops
cd mighty-ops && ./install.sh
```

`install.sh` symlinks `skill/` to `~/.claude/skills/mighty-ops-system-manager`, so `git pull` updates the installed skill. `./install.sh --uninstall` removes the link.

To install for a single project instead, copy the skill into that project:

```bash
cp -R skill /path/to/project/.claude/skills/mighty-ops-system-manager
```

The directory must be named `mighty-ops-system-manager`, the same as the `name:` in `skill/SKILL.md`. Claude Code discovers skills at session start, so open a new session after installing.

## Quick start

At the root of an existing project, in a Claude Code session:

```
/mighty-ops-system-manager init
```

The first run reads the project in bounded passes (about 400 KB of reading in total, whatever the project's size), carves it into systems, and writes the KB to `mighty-ops/`. It then reports the systems with their health, the most useful findings, and what it did not read. A run that is cut short resumes where it stopped. On a new or very small project the run is light, and the skill asks you what the systems are meant to be.

After that, talk to it:

```
/mighty-ops-system-manager
```

It catches up on any new commits, greets you with a short status (health per system, what changed, the top open to-dos), and then discusses whatever you bring: ideas, strategy, "how should we build X", "what is weak", or a review. Before it stops, it tells you what it wrote to the KB.

## Modes

| Invocation | Used by | What it does | Output |
|---|---|---|---|
| `/mighty-ops-system-manager` | human | catch up, then open discussion | status, then conversation |
| `init` | human | first run on a project | ≤40-line report |
| `catchup` | human, worker | sync the KB with new commits | ≤20-line summary |
| `ask: <question>` | any session | answer from the KB with citations | ≤30 lines |
| `decide: <question>; options: …; constraints: …` | orch-manager, any session | choose, and record a decision record (DR) | ≤30 lines + DR |
| `review: <target>` | any session | `PASS` / `CONCERNS` / `BLOCK` on a path, commit range, `result.md`, `plan.md` or `phase N` | ≤30 lines |
| `brief-next-manager [focus]` | orch-manager | write a planning brief to the KB inbox | path + summary |

Any session-mode request can end with a caller tag, `| from: <who>`, which is recorded in the exchange log.

A `decide:` answer looks like this:

```
mighty-ops decide EX-20261024-003
KB: synced 4f1c2d9 = HEAD
Decision: A) api middleware
Confidence: high
Why:
- mighty-ops/systems/api/vision.md: the api owns cross-request policy
- src/api/middleware.py:12 already holds auth and logging in one chain
Risks/limits touched:
- api L-2 (middleware order is implicit) — add a test pinning order
DR: mighty-ops/decisions/DR-0007-where-should-rate-limiting-live.md (accepted)
Record: mighty-ops/exchanges/EX-20261024-003-decide-where-should-rate-limiting-live.md
```

If the KB is far behind `HEAD`, the second line reads `PROVISIONAL: …` and any decision is filed only as `proposed`. Decisions that would change a system's vision, the roadmap, or anything irreversible or human-owned are always `PROPOSED (needs human)`, with a note left in `mighty-ops/inbox/human.md`.

## The knowledge base

```
mighty-ops/
  README.md            entry point: system map, health, last sync
  state.json           machine state (schema mighty-ops-kb/1), written only by the scripts and the skill
  harmony.md           cross-system contracts: who relies on what, pinned by which tests
  glossary.md          project terms → meaning → owning system
  roadmap/             roadmap.md (now / next / later) and ideas.md (ideas as received, with triage)
  decisions/           DR-nnnn-<slug>.md decision records
  systems/<id>/        findings.md  vision.md  limitations.md  todo.md  done.md  decisions.md
  inbox/ outbox/       live messages for orch-manager or the human, and their archive
  exchanges/           one record per session-mode request
  digests/             project digests and catch-up reports
```

Entries use stable ids (`F-3`, `L-2`, `T-5`, `D-1`) and are superseded, never deleted; `check_kb.py` enforces this from recorded counts. The layout is a default: the skill adapts it to a project (new, split, merged or retired systems) and records each adaptation as a decision. The KB is committed to the project by pathspec (`kb(<mode>): …` commits) unless `commit_policy` is `never`. On first run the skill appends one pointer line to an existing `CLAUDE.md` so other sessions can find the KB.

## Working with claude-orch

claude-orch's `orch-manager` skill already contains the orch-manager side of this handshake:

- **Before planning,** the orch-manager reads `mighty-ops/inbox/orch-manager.md` if it exists. That brief, written by `brief-next-manager`, holds system health, suggested units, binding decisions, and limitations to repeat in worker prompts. The manager cites the brief id (`B-…`) in `plan.md`, and the skill archives the brief on its next run.
- **For critical decisions** (a re-plan, an architecture choice, a contract change), the orch-manager calls `decide:`, preferably through a short-lived explore worker so the skill's own reads stay out of the manager's context. It records `- <date> <question> → <decision> (DR-nnnn, <path>)` under `## Decisions` in `plan.md`, or `→ OVERRIDE: <what> — <reason>`. The skill picks that line up on its next catch-up.
- **At phase boundaries,** the orch-manager checks `catchup.py --dry-run` and runs a catch-up in a worker only when the KB has drifted too far. Before a phase that touches two or more systems, it can ask for a fresh brief.

The skill never writes under `orchestration/` and never spawns workers; the orch-manager owns those. `scripts/scorecard.py` turns a finished run's `orchestration/` artifacts into an eight-metric scorecard row in the KB.

## Scripts

All scripts live in `skill/scripts/`, use only the Python standard library, take `--project DIR` (default `.`), and print markdown (or JSON with `--json`). The skill runs them itself; you rarely need to.

| Script | Purpose |
|---|---|
| `kb_init.py` | create or extend the KB; add, split or merge systems. Idempotent, never overwrites a file |
| `project_digest.py` | bounded digest of any project: shape, entry points, tests, docs, candidate systems, hubs, reading plan |
| `catchup.py` | what changed since the last sync, grouped by system, with regression flags; `--done` and `--mark-synced` advance the baseline |
| `check_kb.py` | lint the KB: structure, entry counts, dangling links, secret-like content |
| `scorecard.py` | per-run scorecard from claude-orch's `orchestration/` directory |
| `kblib.py` | shared library |

Flags, exit codes and report formats are documented in [docs/design.md](docs/design.md).

## Safety

The skill:

- never edits product code, tests, configs or docs. It writes only its own KB, plus one pointer line in `CLAUDE.md`;
- never writes under `orchestration/` or spawns workers;
- never stores secrets, credentials or personal data in the KB (`check_kb.py` rejects secret-like strings);
- never rewrites git history, and commits only its own KB directory, by pathspec;
- never deletes a KB entry, decision record or system: they are superseded with a dated reason;
- never runs the project against real data and never makes network calls.

## Repository layout

```
skill/                 the installable skill
  SKILL.md             the skill prompt (loaded on invocation)
  reference/           protocols loaded on demand: KB layout, first run, catch-up,
                       interaction, decision records, quality bar
  scripts/             stdlib Python helpers
tests/                 unittest suite for the scripts (builds throwaway git repos)
docs/design.md         architecture and script reference
install.sh             symlink installer
```

## Tests

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
# or, with pytest installed:
python3 -m pytest -q tests
```

The tests build temporary git repositories and need `git` on `PATH` (git-dependent cases are skipped without it). CI runs them on Linux and macOS with Python 3.9 and 3.13.

## Limitations

- System detection is heuristic. The first run proposes a system map, and you should correct it early; corrections are recorded as decisions.
- The KB is only as current as its last sync. Callers see `PROVISIONAL` when it is far behind, and a full `catchup` fixes that.
- Budget awareness (5-hour and 7-day usage) relies on claude-orch's `orch limits` data. Without it the skill proceeds and checkpoints the first run in passes.
- Git is required for catch-up. A project without git gets a first run but no history-based sync.

## License

[MIT](LICENSE)
