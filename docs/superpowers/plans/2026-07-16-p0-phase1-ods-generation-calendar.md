# P0 Phase 1 ODS Generation And Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only ODS validator and evidence modes that distinguish diagnostic data access from formal, frozen, replay-visible evidence.

**Architecture:** Keep `AShareOdsLoader` as filesystem I/O. Add immutable evidence contracts and a validator that checks every selected parquet part and manifest. The gateway consumes a validated generation and exposes authoritative versus diagnostic calendar modes.

**Tech Stack:** Python dataclasses/enums, pandas, pyarrow, hashlib, pytest, existing ODS Parquet layout.

---

## File Structure

- Create `core/data/evidence_contract.py`: evidence states, modes, immutable generation records.
- Create `core/data/ods_evidence_validator.py`: manifest/partition/generation validation.
- Modify `core/data/ashare_ods_loader.py`: enumerate and read every parquet part.
- Modify `core/data/market_data_gateway.py`: require evidence mode and calendar contract.
- Create `scripts/quant_validate_ods_generation.py`: read-only validation CLI and gate artifact.
- Create `tests/test_ods_evidence_validator.py` and extend gateway/loader tests.

### Task 1: Define Evidence Contracts

**Files:** Create `core/data/evidence_contract.py`; create `tests/test_evidence_contract.py`.

- [ ] Write a failing round-trip test for `EvidenceMode`, `EvidenceState`, and `OdsGenerationContract`.

```python
def test_generation_contract_id_is_order_invariant():
    left = OdsGenerationContract.build(mode="diagnostic", partitions=[PART_B, PART_A])
    right = OdsGenerationContract.build(mode="diagnostic", partitions=[PART_A, PART_B])
    assert left.generation_id == right.generation_id
    assert left.to_dict()["evidence_state"] == "DIAGNOSTIC_ONLY"
```

- [ ] Run `conda run -n stock python -m pytest -q tests/test_evidence_contract.py`; expect import failure.
- [ ] Implement frozen dataclasses with canonical JSON hashing; reject unknown modes/states.
- [ ] Re-run the test; expect pass.
- [ ] Commit `Add immutable ODS evidence contracts`.

### Task 2: Validate Manifests And All Parts

**Files:** Create `core/data/ods_evidence_validator.py`; modify `core/data/ashare_ods_loader.py`; create `tests/test_ods_evidence_validator.py`.

- [ ] Add failing tests for missing manifest, invisible snapshot, `freeze_pending` in formal mode, multipart row count, duplicate primary keys, declared-column mismatch, and path/date mismatch.

```python
def test_formal_generation_rejects_freeze_pending(tmp_path):
    _write_partition(tmp_path, freeze_status="freeze_pending", visible_at="2026-01-06T08:45:00+08:00")
    result = OdsEvidenceValidator(tmp_path).validate(
        datasets=["daily_bars"], start="2026-01-05", end="2026-01-05",
        replay_cutoff="2026-01-06T09:00:00+08:00", mode="formal")
    assert not result.passed
    assert "snapshot_not_frozen" in result.blocking_reasons
```

- [ ] Run the focused tests; expect failures against current latest-snapshot behavior.
- [ ] Implement `validate_partition()` and `validate_generation()` without writing shared data.
- [ ] Change `read_dataset()` to concatenate all sorted parquet parts and preserve stable ordering.
- [ ] Re-run loader/validator tests; expect pass.
- [ ] Commit `Enforce read-only ODS generation validation`.

### Task 3: Separate Diagnostic And Formal Calendars

**Files:** Modify `core/data/market_data_gateway.py`; modify `tests/test_market_data_gateway.py`.

- [ ] Add tests proving diagnostic mode labels bars fallback, while formal mode rejects incomplete authoritative calendar coverage.

```python
def test_formal_calendar_rejects_sparse_calendar(tmp_path):
    gateway = AShareMarketDataGateway(tmp_path, evidence_mode="formal")
    with pytest.raises(EvidenceContractError, match="authoritative_calendar_incomplete"):
        gateway.available_trade_dates("2026-01-01", "2026-01-31")
```

- [ ] Implement explicit `calendar_source` and `calendar_contract_id`; remove implicit promotion use of bars fallback.
- [ ] Run gateway, replay-calendar, and refresh-gate tests.
- [ ] Commit `Separate diagnostic and formal trading calendars`.

### Task 4: Emit A Generation Gate Artifact

**Files:** Create `scripts/quant_validate_ods_generation.py`; modify `core/platform/run_manifest.py`; create `tests/test_quant_validate_ods_generation.py`.

- [ ] Add CLI tests for JSON output, nonzero formal failure, and no shared-root writes.
- [ ] Implement CLI options `--mode`, `--datasets`, `--start`, `--end`, `--replay-cutoff`, `--output`.
- [ ] Persist only under project `output/data_quality/`; include code commit and `conda list --explicit` digest.
- [ ] Run a real diagnostic read-only smoke against `/Users/max/Data/ashare-source-data`.
- [ ] Expected current result: `DIAGNOSTIC_ONLY` if required manifests remain `freeze_pending`; do not force pass.
- [ ] Commit `Add ODS generation validation gate`.

### Phase 1 Gate

- [ ] Run `conda run -n stock python -m pytest -q`.
- [ ] Update docs, Skill, and memory with the actual gate result.
- [ ] Stop before Phase 2 if required datasets cannot even produce a valid diagnostic generation.
