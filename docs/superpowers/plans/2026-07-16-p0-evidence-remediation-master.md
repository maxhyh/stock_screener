# P0 Evidence Remediation Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the data, model, target, execution, and promotion evidence chain so only compatible, point-in-time, adjusted, purged, and lineage-complete artifacts can support A-share strategy decisions.

**Architecture:** Five dependency-ordered phase plans each produce a machine-readable gate artifact. A failed phase leaves the repository in `P0_BLOCKED` or `DIAGNOSTIC_ONLY` and prevents downstream plans from executing. The shared ODS root remains read-only.

**Tech Stack:** Python 3 in Conda `stock`, pandas, pyarrow/parquet, LightGBM, pytest, JSON Schema, existing ODS gateway and paper execution stack.

---

## Phase Plans

1. `2026-07-16-p0-phase1-ods-generation-calendar.md`
2. `2026-07-16-p0-phase2-pit-price-contracts.md`
3. `2026-07-16-p0-phase3-model-temporal-integrity.md`
4. `2026-07-16-p0-phase4-target-execution-integrity.md`
5. `2026-07-16-p0-phase5-evidence-rebuild.md`

## Global Sequencing Rules

- [ ] Run all commands with `conda run -n stock` or the exact `stock` interpreter.
- [ ] Never modify `/Users/max/Data/ashare-source-data`.
- [ ] Do not execute a later phase until the prior phase's gate artifact reports pass.
- [ ] Do not create a profile, refresh P2 performance, or run promotion before Phase 5 permits it.
- [ ] Treat pre-ODS and pre-remediation artifacts as historical diagnostics only.
- [ ] Commit each completed task separately; never mix strategy parameter changes into P0 repairs.

## Cross-Phase Evidence State

All gates emit this shared shape:

```json
{
  "evidence_state": "P0_BLOCKED|DIAGNOSTIC_ONLY|RAW_MODEL_ELIGIBLE|EXECUTION_ELIGIBLE|PROMOTION_ELIGIBLE",
  "gate_name": "string",
  "passed": false,
  "generation_id": "sha256-or-empty",
  "blocking_reasons": ["stable_machine_reason"],
  "artifact_ids": {},
  "created_at": "ISO-8601",
  "code_commit": "git-sha",
  "environment_lock_id": "sha256"
}
```

## Master Acceptance

- [ ] Phase 1 proves whether formal ODS evidence is possible; `freeze_pending` cannot be silently promoted to frozen.
- [ ] Phase 2 prevents unadjusted research labels, window-end master joins, and inferred official limits.
- [ ] Phase 3 proves no label crosses a split and no incompatible model can write signals.
- [ ] Phase 4 proves every target change has parent/child checksum lineage and trapped holdings consume risk budgets.
- [ ] Phase 5 rebuilds evidence in causal order and stops on the first failed gate.
- [ ] `conda run -n stock python -m pytest -q` passes after every phase.

## Execution Stop

If a required supplier field or frozen snapshot is unavailable, record the
blocker in `memory/errors.md`, refresh memory, and stop. Do not replace missing
PIT or freeze evidence with heuristics merely to complete the plan.
