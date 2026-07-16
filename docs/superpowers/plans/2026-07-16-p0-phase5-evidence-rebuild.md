# P0 Phase 5 Evidence Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild raw-model, capacity, daily, P2, shadow, and promotion evidence in causal order on one compatible generation.

**Architecture:** A single orchestration manifest pins generation/model/profile/execution IDs. Each stage consumes the prior gate artifact and writes append-only outputs. Any lineage or method failure invalidates downstream artifacts; a performance failure remains valid negative evidence.

**Tech Stack:** Existing training/raw-model/capacity/P2/promotion scripts, JSON/Parquet artifacts, pytest.

---

## File Structure

- Create `core/platform/evidence_bundle.py` and `schemas/evidence_bundle.schema.json`.
- Create `scripts/quant_rebuild_evidence_generation.py`.
- Modify promotion refresh/review and schema for global evidence-health checks.
- Extend evidence-bundle and promotion tests.

### Task 1: Pin One Evidence Bundle

- [ ] Add schema/tests requiring generation, calendar, PIT, price, universe, feature, label, split, model, profile, target, execution, code, and environment IDs.
- [ ] Implement append-only bundle manifests; reject `latest` as an identity.
- [ ] Reject mixed IDs before any performance aggregation.
- [ ] Run schema tests; commit.

### Task 2: Rebuild H=8/H=10 Raw Evidence

- [ ] Register fold boundaries, thresholds, experiment family, direction, and cost hurdle before running.
- [ ] Train compatible H=8/H=10 candidates and persist row-level OOS predictions plus residual exposure metrics.
- [ ] Run the full purged raw-universe gate.
- [ ] Stop all downstream work if the gate fails; write the negative result to memory without changing thresholds.
- [ ] Commit only code/config/docs, not large model/output artifacts.

### Task 3: Run Capacity And Daily Generation

- [ ] Only after raw pass, run RMB 1,000,000 capacity diagnosis under existing risk limits.
- [ ] Require target utilization, capacity shortfall, ADV/industry/style/impact, and target-instruction lineage.
- [ ] Rebuild profile-isolated daily signals using the passing model and bundle IDs.
- [ ] Stop if daily target checksums or coverage are incomplete.

### Task 4: Run Execution Evidence In Order

- [ ] Run 20-day P2 as engineering smoke only.
- [ ] If software/data/lineage fails, fix and rebuild from the affected parent stage.
- [ ] If smoke is valid, run 60, then 90, then 120 days on identical IDs.
- [ ] Produce shadow, funnel, blocked-cluster, holiday-gap, cost, and cash-drag attribution.
- [ ] Preserve performance failures as negative evidence; do not relax risk gates.

### Task 5: Make Promotion Evidence Health Global

- [ ] Require main and candidate to pass the same bundle-health checks.
- [ ] Missing score-alpha, raw-model, formal generation, checksum equality, unclamped metrics, or required P2 window fails closed.
- [ ] Extend `promotion_decision.schema.json` with exact bundle IDs and evidence state.
- [ ] Add tests that delete one artifact or mix one ID and expect rejection.
- [ ] Run promotion tests; commit.

### Final Gate

- [ ] Run `conda run -n stock python -m pytest -q`.
- [ ] Confirm no shared-root writes and no pre-remediation artifact enters the bundle.
- [ ] Set `PROMOTION_ELIGIBLE` only if method, lineage, execution, capacity, risk, and performance gates all pass.
- [ ] If no candidate passes, keep `quality_regime` configured as default but explicitly mark it not evidence-certified for real capital.
