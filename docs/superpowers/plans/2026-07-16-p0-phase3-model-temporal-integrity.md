# P0 Phase 3 Model Temporal Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make labels, splits, feature selection, model artifacts, and inference temporally valid and fail-closed.

**Architecture:** Shared modeling contracts build labels and purged folds before training. A sidecar model contract binds the model to one ODS/price/universe/feature/label/split generation. Inference validates the contract before loading features or writing signals.

**Tech Stack:** Python, pandas, LightGBM, JSON Schema, pytest.

---

## File Structure

- Create `core/modeling/label_contract.py`, `split_contract.py`, `model_contract.py`.
- Create `schemas/model_contract.schema.json`.
- Modify training, raw walk-forward, and daily inference scripts.
- Add focused model/split tests.

### Task 1: Purge Outcome Windows

- [ ] Add a failing fold test asserting every train label exits before validation and every validation label exits before test.

```python
assert folds.train["label_exit_date"].max() < folds.valid_start
assert folds.valid["label_exit_date"].max() < folds.test_start
```

- [ ] Implement fixed folds, horizon-aware purge, preregistered embargo, and no partial final fold.
- [ ] Replace date-only masks in training and raw walk-forward.
- [ ] Run split and walk-forward tests; commit.

### Task 2: Make Feature Selection Train-Only

- [ ] Add a test that modifying validation/test labels cannot change selected features.
- [ ] Bind IC/feature-selection artifacts to train dates, generation, price, universe, and label IDs.
- [ ] Reject stale or cross-fold IC files.
- [ ] Run feature-selection tests; commit.

### Task 3: Create A Self-Describing Model Contract

- [ ] Add schema tests for required IDs, exact ordered feature dtypes, objective, horizon, direction, seed, commit, environment, and model hash.
- [ ] Implement canonical contract hashing and save the sidecar atomically with the model.
- [ ] Include model contract ID in the pickle metadata and training manifest.
- [ ] Run training package tests; commit.

### Task 4: Fail Closed At Inference

- [ ] Add parameterized tests that alter one feature name/order/dtype, horizon, generation ID, or price contract and expect no signal file.

```python
with pytest.raises(ModelContractError, match="feature_schema_mismatch"):
    validate_inference_contract(model_contract, inference_contract)
```

- [ ] Remove missing-feature zero fill and warning-only horizon behavior.
- [ ] Make `daily_ml_select.py` write model/generation/contract IDs on every row and run manifest.
- [ ] Run daily inference tests; commit.

### Task 5: Harden The Raw-Universe Gate

- [ ] Add preregistered threshold config and experiment-family ID.
- [ ] Require seven complete purged folds, normal score direction, at least 6/7 directional stability, no catastrophic worst fold, residual exposure metrics, serial-dependence confidence intervals, and multiple-experiment tracking.
- [ ] Add tests proving pooled metrics cannot hide a catastrophic fold and that one ordinary noisy fold does not mechanically require 7/7 absolute profit.
- [ ] Run raw-model tests; commit.

### Phase 3 Gate

- [ ] Prove zero split overlap and zero incompatible inference output.
- [ ] Run the full suite and update docs/Skill/memory.
- [ ] Enter `RAW_MODEL_ELIGIBLE` only after one compatible H=8/H=10 model family passes the registered gate; otherwise remain at model diagnosis and stop.
