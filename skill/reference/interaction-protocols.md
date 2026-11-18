# Interaction protocols

How I talk to the human, to other sessions, and to the orch-manager: the invocation grammar, the human mode, the session-mode response and record formats, decision authority, and the orch-manager handshake and brief. `<kb>` is the KB directory (default `mighty-ops`).

## Contents
1. Invocation grammar
2. Human mode (bare invocation)
3. Session mode (ask / decide / review / brief-next-manager)
4. orch-manager handshake and brief
5. Inbox lines between briefs

## 1. Invocation grammar
The runtime puts a line `Base directory for this skill: PATH` before the skill text, and a final line `ARGUMENTS: RAW` after it. There is no templating. These rules apply:
1. Find the last line that starts with `ARGUMENTS:`. If there is none, or the rest is blank, the mode is **human session**.
2. Strip it and match the first token case-insensitively, with or without a trailing colon: `ask`, `decide`, `review`, `catchup`, `init`, `brief-next-manager`. The rest is the payload.
3. Optional trailing caller tag ` | from: WHO` (for example `| from: orch-manager my-session`): strip it from the payload and record it as the requester. Without it, the requester is `session` for ask/decide/review and `human` otherwise.
4. Any other first token: the whole string is treated as `ask:`. The first line of the answer says "(interpreted as ask:)".
5. Script paths are relative to the base directory (`BASE/scripts/catchup.py`). If that line is missing, use `~/.claude/skills/mighty-ops-system-manager/`, then `PROJECT/.claude/skills/mighty-ops-system-manager/`.

| Mode | Payload | Sync rule | Writes | Output |
|---|---|---|---|---|
| human (bare) | none | full catch-up if stale (chunked) | anything in the KB the discussion produces | greeting status ≤12 lines, then conversation |
| `ask:` | question | stale rule | exchange record; findings if new facts were verified | ≤30 lines, session format |
| `decide:` | question + options + constraints | stale rule | exchange record + DR + per-system `decisions.md` index lines | ≤30 lines, includes `Decision:` and `DR:` |
| `review:` | target: path(s), an `A..B` range, a worker `result.md`, `plan.md`, or `phase N` | stale rule | exchange record; regression and limitation entries it found | ≤30 lines; `Verdict: PASS / CONCERNS / BLOCK` + ≤10 findings |
| `catchup` | none | full catch-up, chunked | per-system pages, state, digest | ≤20-line summary |
| `init` | optional `--kb-dir NAME` | n/a | creates or extends the KB | ≤40-line report |
| `brief-next-manager` | optional focus text | stale rule | `inbox/orch-manager.md` (previous brief archived to `outbox/`) | `Brief:` path + ≤5-bullet summary (§3.1) |

The stale rule is in `catchup-protocol.md` §3. **No KB yet:** ask/decide/review answer from a bounded look (`project_digest.py` output only, ≤60 lines read). The answer is marked `PROVISIONAL: no KB` and recommends `init`. `brief-next-manager` with no KB says so and stops.

## 2. Human mode (bare invocation)
1. Locate the KB and sync (the state machine in SKILL.md). Print a greeting status (≤12 lines):
   - the last sync (sha7, date) and how many commits I just caught up on;
   - health per system, one line each (the worst 8 if there are more);
   - what is new since last time;
   - anything in `inbox/human.md`;
   - the top 3 open todos by roadmap order.

   Then ask what they want to work on.
2. What each kind of discussion must write:
   - **Idea** ("we should …"): append `IDEA-n` to `roadmap/ideas.md` verbatim with the date. Triage aloud: which systems it touches, where it compounds (`quality-bar.md` §1), what it conflicts with (vision, limitations, harmony edges), and the smallest first step. Record the outcome as roadmap item(s) plus todo(s) with acceptance criteria, and a DR if it changes a system's vision or contract. Write the triage outcome under the idea.
   - **Strategy / "how should X be built":** answer against `vision.md` and `harmony.md`. Record agreed vision text in `vision.md`, quoted with "(human, DATE)".
   - **"What is weak":** rank by limitation severity × fan-in from `harmony.md`, citing entries.
   - **Review:** the same as `review:` but unbounded in length.
3. Before ending (or when the human goes quiet), say in ≤5 lines what was written to the KB, then write back: `check_kb.py --record`, then commit per policy.
4. **Disagreement:** if the human chooses against my advice, record the DR with `Decided by: human` and my objection under "Alternatives considered", then comply. The human's decision binds.
5. Human-owned matters (secrets, real data, external accounts, spending, irreversible actions) are never decided by me. I lay out the options and record the human's choice.

## 3. Session mode (ask / decide / review / brief-next-manager)
The answer runs inside the caller's context, so every line costs the caller. Never paste a file or dump a KB page into it; cite it.

### 3.1 Response printed to the caller (≤30 lines, plain text, in this order)
```
mighty-ops MODE EX-20261024-003
KB: synced SHA7 = HEAD            (or)  PROVISIONAL: KB at SHA7, HEAD SHA7, 41 commits behind
Answer: 1–10 lines                (decide: "Decision: one line" first, then "Confidence: high|medium|low")
Why: ≤4 bullets, each citing a KB or repo path
Risks/limits touched: ≤4 bullets with ids
Conditions: what would change this answer          (decide only, optional)
DR: <kb>/decisions/DR-0007-SLUG.md (accepted|proposed)   (decide only)
Record: <kb>/exchanges/EX-20261024-003-decide-SLUG.md
```
- Citations look like `<kb>/systems/api/limitations.md#L-3` or `src/api/routes.py:42`.
- `review:` replaces `Answer:` with `Verdict: PASS|CONCERNS|BLOCK` and up to 10 lines of the form `- [high|medium|low] finding (cite)`. BLOCK is reserved for a regression flag, a contract change with no DR, or a broken harmony edge (`quality-bar.md` §2–3).
- `brief-next-manager` keeps the first two lines (with the brief id `B-…` in place of the EX id) and then prints the `Brief:` line and a ≤5-bullet summary instead of `Answer:`. It prints no `Why:`, `Risks/limits touched:` or `Record:` line, because the brief file is the record. The template and a worked example:
  ```
  mighty-ops brief-next-manager B-YYYYMMDD-N
  KB: synced SHA7 = HEAD          (or the PROVISIONAL line)
  Brief: <kb>/inbox/orch-manager.md (B-YYYYMMDD-N; supersedes B-… | first brief)
  - ≤5 bullets: systems and health, top open item, binding DRs, suggested units, pending decide: calls
  ```
  ```
  mighty-ops brief-next-manager B-20261024-1
  KB: synced fad0b22 = HEAD
  Brief: mighty-ops/inbox/orch-manager.md (B-20261024-1; first brief)
  - 6 systems, all amber (no tests anywhere); new system `plugins` this cycle (DR-0002).
  - Top open item: runtime L-1 high (the build allowlist grants a forbidden git command).
  - DR-0003 binds: keep the two env vars separate; the real fix is one directory variable (T-1).
  - 4 suggested next units; 2 `decide:` calls pending before planning.
  ```
- If the grammar fell back to ask (rule 4), the first line is "(interpreted as ask:)".

### 3.2 Exchange record file
The path is `<kb>/exchanges/EX-YYYYMMDD-NNN-MODE-SLUG.md`. YYYYMMDD is the UTC date. SLUG is the first 5 words of the payload, kebab-case, ≤40 chars. NNN comes from `state.json` `counters.exchange_seq[YYYYMMDD]` (increment it, zero-pad to 3). Never reword a slug to dodge a `check_kb.py` finding. The E10 key check ignores `sk-` inside kebab words (`ask-which-…`), so a real E10 on a record is real content to remove.
```
# EX-20261024-003 — decide — SLUG
- Date: 2026-10-24T10:12:00Z
- From: orch-manager my-session        (the `| from:` tag, else session|human)
- Mode: decide
- KB at: SHA40 (provisional: no)
- Systems: api, storage
## Request
payload verbatim, ≤40 lines; longer payloads truncated with "[truncated N lines]"
## Response
exactly what was printed
## Follow-ups
- DR-0007 (accepted) · T-4 in systems/api/todo.md · inbox line for orch-manager
```
Exchange records are never deleted or edited after the fact. A correction is a new exchange that cites the old one.

### 3.3 Decision authority (`decide:`)
- **accepted:** the question is within the existing visions and DRs (a technical choice consistent with them). Write the DR as `accepted`, `Decided by: mighty-ops-system-manager`.
- **proposed:** the answer would change a system's vision, the roadmap, anything irreversible, or anything the human owns (secrets, real data, external accounts, spending). Write the DR as `proposed`, add a line to `<kb>/inbox/human.md`, and begin the printed `Decision:` with "PROPOSED (needs human):".
- **provisional:** with the KB stale beyond the bounded update, the DR is always `proposed`, and the printed `Decision:` begins "PROPOSED (provisional KB):". The next full catch-up re-checks it (`catchup-protocol.md` §2e). With no KB at all, no DR is written: the answer says so and recommends `init`.
- Every DR gets an index line in each affected `systems/ID/decisions.md` (`decision-record.md`).

## 4. orch-manager handshake and brief
- **Inbox file:** `<kb>/inbox/orch-manager.md`.
- **Writer:** only me (on `brief-next-manager`, or regression-flag lines during catch-up).
- **Reader:** orch-manager, at orientation (§0 step 2a of claude-orch's orch-manager skill), before planning, on every orientation (fresh and `resume`). orch-manager never edits or deletes it.

**Brief format** (≤80 lines). The brief id is `B-YYYYMMDD-N`, with N taken from `counters.brief_seq[YYYYMMDD]`.
```
# Brief for the next orch-manager — B-20261024-1
- Written: ISO by mighty-ops-system-manager (MODE)   - KB synced at: SHA7
- Supersedes: B-20261020-2 (now in outbox/)
## Read first (≤5 bullets)
## System health (table: system | health | reason | cite; ≤15 rows)
## Suggested next units (≤6; each: goal · system · files it will own · acceptance tests · model hint · DR)
## Decisions that bind planning (DR id — one line each)
## Limitations every worker prompt in these systems must repeat (≤8, cite)
## Call `decide:` before (pending decision points)
Ack: write `B-20261024-1` in plan.md (Decisions or Re-plans) when you act on this brief.
```
- **Writing a new brief:** if `inbox/orch-manager.md` exists, first move it to `outbox/DATE-orch-manager-OLDID.md` (`git mv <kb>/inbox/orch-manager.md <kb>/outbox/DATE-orch-manager-OLDID.md` if it is tracked, otherwise `mv` with the same paths). This is a move, not a delete: the outbox copy is the archive. Put its id in `Supersedes:`.
- **Archiving:** on my next run, I move the brief to `outbox/DATE-orch-manager-BRIEFID.md` when (a) catch-up sees the brief id in an `orchestration/plan.md` diff (`catchup-protocol.md` §2d), or (b) a new brief supersedes it. **Who archives:** always me, never orch-manager.
- **How orch-manager asks:**
  `/mighty-ops-system-manager decide: QUESTION; options: A) … B) …; constraints: … | from: orch-manager SESSION-NAME`
  The answer is ≤30 lines, but an inline call also loads this skill's body and its reference reads into the manager's context (several thousand tokens per call). The recommended path is an explore worker on the strongest model available (opus; the worker does the reasoning, so its model is the decision's quality) whose prompt is that one line plus "put the answer verbatim in result.md": workers can call Skill when the skill is installed, and the worker's context is discarded on exit. Inline is for a single urgent decision while the manager's context is small. `ask:` and `review:` use the same `| from:` tag.
- **Recording on both sides:**
  - orch-manager appends to `plan.md` under `## Decisions`: `- DATE QUESTION → DECISION (DR-0007, <kb>/decisions/DR-0007-SLUG.md)`. If it overrides me: `→ OVERRIDE: what instead — reason`.
  - I record the DR plus the exchange. During catch-up (`catchup-protocol.md` §2d) I fill the DR's `Acknowledged by:` line with the plan.md line. On an OVERRIDE I set `Status: superseded by manager override (DATE: reason)` and open a limitation or todo if the override carries risk.
  - A `decide:` answer is advisory to orch-manager, but it is the default. An override must state its reason in plan.md.
- **Phase boundaries:** orch-manager *may* call `brief-next-manager` at its §7 step 4. This is recommended when the next phase touches ≥2 systems.
- **KB freshness at a boundary (orch-manager §7):** orch-manager runs `catchup.py --dry-run` and, only when the `Status:` is `provisional-candidate` (drift past the bounded-update limit), spawns one explore worker to invoke `catchup`. `behind` is healed inside the next `decide:`; `up_to_date` needs nothing. This keeps `decide:` answers from going PROVISIONAL mid-run without a chunked catch-up ever running in the manager's context.
- I never write under `orchestration/`. The plan is the manager's file, and the inbox is mine.

## 5. Inbox lines between briefs
Regression flags found during catch-up, and "run `/mighty-ops-system-manager catchup`" notes, are appended to `inbox/orch-manager.md` under a `## Since this brief` section, one line each: `- DATE [system] what (cite)`. If no brief exists yet, create the file with the header `# Notes for the orch-manager (no brief yet)` and that section. `inbox/human.md` uses the same line format, for proposed DRs and human-owned questions. Lines are archived with their file, never deleted one by one.
