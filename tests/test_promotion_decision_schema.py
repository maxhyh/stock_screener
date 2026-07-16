# -*- coding: utf-8 -*-
"""promotion_decision schema / validator tests."""

from __future__ import annotations

import json

import pytest

from utils.promotion_decision import load_json_strict, load_promotion_decision_schema, validate_promotion_decision_payload


def _sample_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-04-24T06:13:32+08:00",
        "review_id": "quant_profile_promotion_review_20260424_061332",
        "expected_current_default_profile": "quality_regime",
        "final_default_profile": "quality_regime",
        "candidate_profile": "quality_regime_candidate",
        "decision": "keep",
        "change_required": False,
        "reason_code": "candidate_execution_underperformed",
        "rationale": "Candidate research score is stronger, but complete P2 replay underperformed the incumbent.",
        "evidence": {
            "main_score": -1.2,
            "candidate_score": 6.3,
            "score_margin": 7.5,
            "candidate_p2_executed_days_total": 261,
            "min_p2_executed_days": 20,
            "candidate_p2_gate_passed": True,
            "candidate_promotion_hard_gate_passed": False,
            "candidate_execution_parity_passed": False,
        },
        "artifacts": {
            "review_csv": "/tmp/review.csv",
            "review_meta_json": "/tmp/review.json",
        },
    }


def test_load_promotion_decision_schema_exists():
    schema = load_promotion_decision_schema()
    assert schema["properties"]["decision"]["enum"] == ["keep", "promote"]


def test_validate_promotion_decision_payload_accepts_valid_keep():
    validate_promotion_decision_payload(_sample_payload())


def test_load_json_strict_rejects_duplicate_keys(tmp_path):
    fp = tmp_path / "promotion_decision.json"
    fp.write_text(
        '{"schema_version":1,"decision":"keep","decision":"promote"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_json_strict(fp)


def test_validate_promotion_decision_payload_rejects_inconsistent_change_required():
    payload = _sample_payload()
    payload["final_default_profile"] = "quality_regime_candidate"
    payload["change_required"] = False
    with pytest.raises(ValueError):
        validate_promotion_decision_payload(payload)
