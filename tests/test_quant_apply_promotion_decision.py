# -*- coding: utf-8 -*-
"""promotion_decision 应用测试。"""

from __future__ import annotations

import json
import sys

import pytest

import scripts.quant_apply_promotion_decision as apply_decision


def _decision_payload(decision: str, expected_current: str, final_default: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-04-24T06:13:32+08:00",
        "review_id": "quant_profile_promotion_review_test",
        "expected_current_default_profile": expected_current,
        "final_default_profile": final_default,
        "candidate_profile": "" if decision == "keep" else final_default,
        "decision": decision,
        "change_required": final_default != expected_current,
        "reason_code": "current_main_profile_remains_best" if decision == "keep" else "candidate_outperformed_with_sufficient_p2_support",
        "rationale": "test payload",
        "evidence": {
            "main_score": 1.0,
            "candidate_score": 2.0,
            "score_margin": 1.0,
            "candidate_p2_executed_days_total": 30,
            "min_p2_executed_days": 20,
            "candidate_p2_gate_passed": True,
            "candidate_promotion_hard_gate_passed": decision == "promote",
            "candidate_execution_parity_passed": decision == "promote",
        },
        "artifacts": {
            "review_csv": "/tmp/review.csv",
            "review_meta_json": "/tmp/review.json",
        },
    }


def test_apply_promotion_decision_rejects_hold(tmp_path, monkeypatch):
    decision_file = tmp_path / "promotion_decision.json"
    config_file = tmp_path / "quant_live_profiles.json"
    decision_file.write_text(
        json.dumps(
            _decision_payload("keep", "quality_regime", "quality_regime"),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_file.write_text(
        json.dumps({"default_profile": "quality_regime", "profiles": {"quality_regime": {}, "quality_regime_candidate": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["quant_apply_promotion_decision.py", "--decision-file", str(decision_file), "--config", str(config_file)],
    )

    with pytest.raises(RuntimeError):
        apply_decision.main()


def test_apply_promotion_decision_updates_default_profile(tmp_path, monkeypatch):
    decision_file = tmp_path / "promotion_decision.json"
    config_file = tmp_path / "quant_live_profiles.json"
    decision_file.write_text(
        json.dumps(
            _decision_payload("promote", "quality_regime", "quality_regime_candidate"),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_file.write_text(
        json.dumps({"default_profile": "quality_regime", "profiles": {"quality_regime": {}, "quality_regime_candidate": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["quant_apply_promotion_decision.py", "--decision-file", str(decision_file), "--config", str(config_file)],
    )

    rc = apply_decision.main()
    root = json.loads(config_file.read_text(encoding="utf-8"))
    assert rc == 0
    assert root["default_profile"] == "quality_regime_candidate"


def test_apply_promotion_decision_rejects_compare_and_swap_mismatch(tmp_path, monkeypatch):
    decision_file = tmp_path / "promotion_decision.json"
    config_file = tmp_path / "quant_live_profiles.json"
    decision_file.write_text(
        json.dumps(
            _decision_payload("promote", "quality_regime", "quality_regime_candidate"),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_file.write_text(
        json.dumps({"default_profile": "balanced", "profiles": {"quality_regime": {}, "quality_regime_candidate": {}, "balanced": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["quant_apply_promotion_decision.py", "--decision-file", str(decision_file), "--config", str(config_file)],
    )

    with pytest.raises(RuntimeError):
        apply_decision.main()
