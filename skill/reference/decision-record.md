# Decision record (DR)

A DR is how a choice about a system becomes durable. It is dated, has a status, and states who decided and why. DRs are never deleted. They are superseded.

## When to write one
- `decide:` always writes one.
- Human mode: an idea or discussion that changes a system's vision, contract or the roadmap.
- KB layout adaptations: a new system, split, merge, retire, rename, or the initial system map (DR-0001 on first run).
- Catch-up: "baseline lost", a manager override with risk, or a test-function drop that is intentional.
- Retroactive: decisions found in `orchestration/plan.md` Re-plans during the first run (`Status: accepted (retroactive from SOURCE)`).

## File name and number
`<kb>/decisions/DR-NNNN-SLUG.md`. NNNN is `state.json` `counters.dr` + 1, zero-padded to 4; write the new value back to `counters.dr`. SLUG is the title, kebab-case, ≤40 chars.

## Template (copy verbatim)
```
# DR-0007 — <title>
- Date: 2026-10-24
- Status: proposed | accepted | rejected | superseded by DR-0012 (2026-11-02: <reason>)
- Decided by: human | mighty-ops-system-manager | orch-manager override
- Asked by: <EX id or "human session">
- Systems: api, storage
- Acknowledged by: <plan.md line, or "-">
## Context
## Decision
## Reason
## Alternatives considered
## Consequences (contracts, tests that pin it, limitations created or resolved, roadmap items)
```
Keep exactly one status value on the `Status:` line. It may be followed by one parenthetical note, such as `accepted (retroactive from orchestration/plan.md:42)` or the dated reason after `superseded by DR-0012`. Never list two statuses. `check_kb.py` requires `- Date: YYYY-MM-DD`, a `- Status:` in {proposed, accepted, rejected, superseded by …}, and a non-empty `## Reason` (E05).

## Index line in each affected system
In `<kb>/systems/ID/decisions.md`, one line per DR:
```
- DR-0007 (2026-10-24, accepted) — <title> → ../../decisions/DR-0007-<slug>.md
```
When the status changes, append a new dated line to the index rather than editing the old one, for example `- DR-0007 (2026-11-02, superseded by DR-0012) — <title> → …`. `check_kb.py` errors on an index link to a DR file that does not exist (E09). `check_kb.py --record` counts the distinct DR ids indexed in each `decisions.md`, so a deleted index line is caught as a deletion (E07). An appended status line for the same DR does not change the count.

"Affected system" means every system the DR's `Systems:` line names. DR-0001 (initial system map) names every system it creates, so it is indexed in every `decisions.md`. A split, merge or new-system DR is indexed in the old systems and in the new ones.

## Filled example (generic)
```
# DR-0007 — Cache layer owns invalidation, not the API handlers
- Date: 2026-10-24
- Status: accepted
- Decided by: mighty-ops-system-manager
- Asked by: EX-20261024-003
- Systems: api, cache
- Acknowledged by: - 2026-10-24 who invalidates cache entries → cache layer (DR-0007, mighty-ops/decisions/DR-0007-cache-layer-owns-invalidation.md)
## Context
Three API handlers each delete cache keys after writes (src/api/orders.py:120, src/api/users.py:88, src/api/items.py:64). Two missed a key in the last month (cache L-2).
## Decision
Invalidation moves into the cache system behind one function keyed on the entity type. Handlers call it; they never delete keys directly.
## Reason
One mechanism instead of three copies (quality bar: placed). The cache vision already says "the cache owns key lifetimes" (cache/vision.md). It closes cache L-2 at its root.
## Alternatives considered
- Keep per-handler deletes and add a lint rule: rejected, the knowledge stays spread across handlers.
- Time-based expiry only: rejected, stale reads for up to the TTL break the orders contract in harmony.md.
## Consequences (contracts, tests that pin it, limitations created or resolved, roadmap items)
- harmony.md row api → cache: "invalidate(entity, id) after every write", pinned by tests/cache/test_invalidate.py.
- Resolves cache L-2 when the move lands. New todo api T-5 (move the three call sites).
```

## Superseding a DR
1. Write the new DR (for example DR-0012). In its Context, cite the old DR and say what changed.
2. In the old DR, change only the `Status:` line to `superseded by DR-0012 (DATE: reason)`. Leave all other text as it was.
3. Append index lines for both DRs in each affected `decisions.md`.
4. Update any `harmony.md` row or `vision.md` text that cited the old DR.

## Special statuses
- **Manager override** (found in plan.md during catch-up): `Status: superseded by manager override (DATE: reason)`. No new DR is needed unless the override changes a contract. If it does, write one with `Decided by: orch-manager override`.
- **Human decision against my advice:** `Decided by: human`. Put my objection under "Alternatives considered". The DR is `accepted`.
- **Proposed** (needs the human): add a line to `<kb>/inbox/human.md`. When the human answers, set the status to `accepted` or `rejected`, add a `(human, DATE)` note under Decision, and append an index line.
