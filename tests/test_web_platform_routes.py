# -*- coding: utf-8 -*-
"""平台路由测试。"""

from __future__ import annotations

import json

from web.app import create_app


def test_platform_routes_expose_health_and_latest_run(tmp_path):
    app = create_app()
    app.config.update(TESTING=True, BASE_DIR=str(tmp_path))
    platform_dir = tmp_path / "output" / "platform" / "runs"
    platform_dir.mkdir(parents=True, exist_ok=True)
    (platform_dir / "run_1.json").write_text(
        json.dumps({"run_id": "run_1", "status": "success"}),
        encoding="utf-8",
    )
    experiments_dir = tmp_path / "output" / "platform" / "experiments"
    experiments_dir.mkdir(parents=True, exist_ok=True)
    (experiments_dir / "registry.json").write_text(
        json.dumps([{"experiment_id": "exp_1", "name": "demo"}]),
        encoding="utf-8",
    )

    with app.test_client() as client:
        health = client.get("/api/platform/health")
        assert health.status_code == 200
        payload = health.get_json()
        assert payload["success"] is True
        assert payload["latest_run_id"] == "run_1"
        assert payload["experiment_count"] == 1

        latest = client.get("/api/platform/latest_run")
        assert latest.status_code == 200
        assert latest.get_json()["run"]["status"] == "success"


def test_platform_ops_overview_and_page(tmp_path):
    app = create_app()
    app.config.update(TESTING=True, BASE_DIR=str(tmp_path))

    output_dir = tmp_path / "output"
    platform_runs = output_dir / "platform" / "runs"
    platform_runs.mkdir(parents=True, exist_ok=True)
    (platform_runs / "run_2.json").write_text(
        json.dumps({"run_id": "run_2", "status": "success", "started_at": "2026-04-23 20:00:00"}),
        encoding="utf-8",
    )
    experiments_dir = output_dir / "platform" / "experiments"
    experiments_dir.mkdir(parents=True, exist_ok=True)
    (experiments_dir / "registry.json").write_text(
        json.dumps([{"experiment_id": "exp_2", "name": "alpha-demo", "created_at": "2026-04-23 20:10:00"}]),
        encoding="utf-8",
    )
    backtest_dir = output_dir / "backtest"
    backtest_dir.mkdir(parents=True, exist_ok=True)
    (backtest_dir / "promotion_decision_20260423_235900.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-04-23T23:59:00+08:00",
                "review_id": "quant_profile_promotion_review_20260423_235900",
                "expected_current_default_profile": "quality_regime",
                "final_default_profile": "quality_regime",
                "candidate_profile": "quality_regime_candidate",
                "decision": "keep",
                "change_required": False,
                "reason_code": "candidate_p2_gate_failed",
                "rationale": "Candidate does not have enough execution support yet.",
                "evidence": {
                    "score_margin": 4.5,
                    "candidate_p2_executed_days_total": 120,
                    "candidate_p2_gate_passed": False,
                },
                "artifacts": {
                    "review_csv": "/tmp/review_old.csv",
                    "review_meta_json": "/tmp/review_old.json",
                },
            }
        ),
        encoding="utf-8",
    )
    (backtest_dir / "promotion_decision_latest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-04-24T06:13:32+08:00",
                "review_id": "quant_profile_promotion_review_20260424_061332",
                "expected_current_default_profile": "quality_regime",
                "final_default_profile": "quality_regime",
                "candidate_profile": "quality_regime_candidate",
                "decision": "keep",
                "change_required": False,
                "reason_code": "candidate_execution_underperformed",
                "rationale": "Candidate research is stronger but execution underperformed.",
                "evidence": {
                    "winner_research_score": 15.49,
                    "winner_ops_score": -10.73,
                    "score_margin": 7.51,
                    "candidate_p2_executed_days_total": 261,
                    "min_p2_executed_days": 20,
                },
                "artifacts": {
                    "review_csv": "/tmp/review.csv",
                    "review_meta_json": "/tmp/review.json",
                },
            }
        ),
        encoding="utf-8",
    )

    risk_dir = output_dir / "risk"
    risk_dir.mkdir(parents=True, exist_ok=True)
    (risk_dir / "risk_exposure_summary_latest.csv").write_text(
        "state,trades,avg_exposure_pct,avg_positions,win_rate_pct,avg_portfolio_ret_pct,avg_hhi\n正常,10,60.0,5.0,55.0,1.2,0.18\n",
        encoding="utf-8",
    )
    (risk_dir / "risk_exposure_industry_latest.csv").write_text(
        "industry,avg_weight_pct,max_weight_pct\n电子,22.0,35.0\n医药,18.0,24.0\n",
        encoding="utf-8",
    )
    (risk_dir / "exec_consistency_summary_paper_latest.json").write_text(
        json.dumps(
            {
                "coverage_pct": 90.0,
                "matched_rows": 9,
                "rows": 10,
                "ret_gap_mean_pct": -0.2,
                "ret_gap_mae_pct": 0.5,
                "order_block_rate_mean_pct": 3.0,
                "risk_block_rate_mean_pct": 12.0,
                "primary_driver_top": "risk_gates",
                "consistency_pass": True,
            }
        ),
        encoding="utf-8",
    )
    (risk_dir / "pretrade_alignment_summary_paper_pretrade_diag_latest.json").write_text(
        json.dumps(
            {
                "channel": "paper_pretrade_diag",
                "rows": 7,
                "window_start": "2026-04-01",
                "window_end": "2026-04-10",
                "metrics": {
                    "match_rate_pct": 85.0,
                    "mean_p2_risk_blocked_rate_pct": 11.5,
                    "signal_rows": 7,
                    "top_p2_risk_block_reason": "industry_weight_unknown",
                },
            }
        ),
        encoding="utf-8",
    )
    (risk_dir / "capacity_cost_latest.csv").write_text(
        "signal_date,state,total_exposure_pct,position_count,max_participation_pct,estimated_roundtrip_cost_bps,capacity_multiple,portfolio_ret_pct\n2026-04-10,正常,60.0,5,18.0,36.0,2.4,1.2\n",
        encoding="utf-8",
    )

    with app.test_client() as client:
        page = client.get("/platform/ops")
        assert page.status_code == 200
        assert "平台运维与风险暴露" in page.get_data(as_text=True)

        overview = client.get("/api/platform/ops_overview")
        assert overview.status_code == 200
        payload = overview.get_json()
        assert payload["success"] is True
        assert payload["platform"]["latest_run_id"] == "run_2"
        assert payload["platform"]["experiment_count"] == 1
        assert payload["alert_summary"]["total"] >= 1
        assert any(item["id"] == "pretrade_match_rate_low" for item in payload["alerts"])
        assert len(payload["alert_history"]) == 1
        assert payload["alert_trends"]["total_alerts"]["latest"] == payload["alert_summary"]["total"]
        assert payload["governance"]["promotion_decision"]["decision"] == "keep"
        assert payload["governance"]["promotion_decision"]["candidate_profile"] == "quality_regime_candidate"
        assert len(payload["governance"]["promotion_history"]) == 1
        assert payload["governance"]["promotion_history"][0]["review_id"] == "quant_profile_promotion_review_20260423_235900"
        assert payload["governance"]["promotion_trends"]["series"][0]["decision"] == "keep"
        assert payload["risk"]["exec_consistency"]["consistency_pass"] is True
        assert payload["risk"]["industry_top"][0]["industry"] == "电子"

        (backtest_dir / "promotion_decision_20260424_071500.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": "2026-04-24T07:15:00+08:00",
                    "review_id": "quant_profile_promotion_review_20260424_071500",
                    "expected_current_default_profile": "quality_regime",
                    "final_default_profile": "quality_regime_candidate",
                    "candidate_profile": "quality_regime_candidate",
                    "decision": "promote",
                    "change_required": True,
                    "reason_code": "candidate_outperformed_with_sufficient_p2_support",
                    "rationale": "Candidate now passes both research and execution gates.",
                    "evidence": {
                        "score_margin": 8.1,
                        "candidate_p2_executed_days_total": 300,
                        "candidate_p2_gate_passed": True,
                    },
                    "artifacts": {
                        "review_csv": "/tmp/review_new.csv",
                        "review_meta_json": "/tmp/review_new.json",
                    },
                }
            ),
            encoding="utf-8",
        )

        (risk_dir / "exec_consistency_summary_paper_latest.json").write_text(
            json.dumps(
                {
                    "coverage_pct": 86.0,
                    "matched_rows": 8,
                    "rows": 10,
                    "ret_gap_mean_pct": -0.5,
                    "ret_gap_mae_pct": 1.8,
                    "order_block_rate_mean_pct": 12.0,
                    "risk_block_rate_mean_pct": 28.0,
                    "primary_driver_top": "capacity",
                    "consistency_pass": False,
                }
            ),
            encoding="utf-8",
        )

        overview_2 = client.get("/api/platform/ops_overview")
        assert overview_2.status_code == 200
        payload_2 = overview_2.get_json()
        assert payload_2["alert_summary"]["critical"] >= payload["alert_summary"]["critical"]
        assert len(payload_2["alert_history"]) == 2
        assert payload_2["alert_trends"]["total_alerts"]["delta"] is not None
        assert len(payload_2["governance"]["promotion_history"]) == 2
        assert payload_2["governance"]["promotion_history"][-1]["decision"] == "promote"
        assert payload_2["governance"]["promotion_trends"]["promote_count"] >= 1
        assert payload_2["governance"]["promotion_trends"]["change_required_count"] >= 1
        assert any(item["id"] == "exec_consistency_failed" for item in payload_2["alerts"])
