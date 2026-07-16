# -*- coding: utf-8 -*-
"""P2 推荐参数读取测试。"""

from __future__ import annotations

import sys

import pandas as pd

import scripts.quant_p2_paper_trade as p2


def test_load_recommendation_row_prefers_recommend_rank_column(tmp_path):
    path = tmp_path / "recs.csv"
    df = pd.DataFrame(
        [
            {
                "recommend_rank": 2,
                "top_n": 12,
                "max_single_pos": 0.05,
                "use_regime_position": 0,
                "holding_days": 5,
                "risk_tier": "aggressive",
                "selection_mode": "top_hard_pass",
                "objective_score": 88.1,
            },
            {
                "recommend_rank": 1,
                "top_n": 8,
                "max_single_pos": 0.04,
                "use_regime_position": 1,
                "holding_days": 3,
                "risk_tier": "balanced",
                "selection_mode": "top_hard_pass",
                "objective_score": 90.2,
            },
        ]
    )
    df.to_csv(path, index=False, encoding="utf-8-sig")

    rec = p2._load_recommendation_row(path, rank=1)
    assert rec["recommend_rank"] == 1
    assert rec["top_n"] == 8
    assert abs(float(rec["max_single_pos"]) - 0.04) < 1e-9
    assert rec["use_regime_position"] is True
    assert rec["holding_days"] == 3
    assert rec["risk_tier"] == "balanced"


def test_load_recommendation_row_falls_back_to_row_index(tmp_path):
    path = tmp_path / "recs_no_rank.csv"
    df = pd.DataFrame(
        [
            {"top_n": 9, "max_single_pos": 0.07, "use_regime_position": "false", "holding_days": 2},
            {"top_n": 11, "max_single_pos": 0.06, "use_regime_position": "true", "holding_days": 4},
        ]
    )
    df.to_csv(path, index=False, encoding="utf-8-sig")

    rec = p2._load_recommendation_row(path, rank=2)
    assert rec["top_n"] == 11
    assert abs(float(rec["max_single_pos"]) - 0.06) < 1e-9
    assert rec["use_regime_position"] is True
    assert rec["holding_days"] == 4


def test_build_parser_uses_profile_risk_defaults(monkeypatch):
    monkeypatch.setattr(
        p2,
        "DEFAULTS",
        {
            "top_n": 10,
            "max_single_pos": 0.04,
            "fallback_total_position": 0.60,
            "fee_bps": 7.5,
            "slippage_bps": 4.5,
            "risk_max_industry_weight": 0.35,
            "risk_max_adv_participation": 0.06,
            "risk_min_price": 2.0,
            "risk_max_style_size_exposure_abs": 0.20,
            "risk_max_style_beta_exposure_abs": 0.25,
            "risk_max_style_momentum_exposure_abs": 0.30,
            "risk_max_style_vol_exposure_abs": 0.35,
            "risk_style_lb_short": 30,
            "risk_style_lb_beta": 90,
        },
    )
    parser = p2._build_parser()
    args = parser.parse_args([])

    assert abs(float(args.fee_bps) - 7.5) < 1e-9
    assert abs(float(args.slippage_bps) - 4.5) < 1e-9
    assert abs(float(args.risk_max_industry_weight) - 0.35) < 1e-9
    assert abs(float(args.risk_max_adv_participation) - 0.06) < 1e-9
    assert abs(float(args.risk_min_price) - 2.0) < 1e-9
    assert abs(float(args.risk_max_style_size_exposure_abs) - 0.20) < 1e-9
    assert abs(float(args.risk_max_style_beta_exposure_abs) - 0.25) < 1e-9
    assert abs(float(args.risk_max_style_momentum_exposure_abs) - 0.30) < 1e-9
    assert abs(float(args.risk_max_style_vol_exposure_abs) - 0.35) < 1e-9
    assert int(args.risk_style_lb_short) == 30
    assert int(args.risk_style_lb_beta) == 90


def test_load_signal_df_excludes_st_when_enabled(tmp_path):
    path = tmp_path / "daily_test.csv"
    df = pd.DataFrame(
        [
            {"代码": "600581", "名称": "*ST八钢", "排名": 1, "ML评分": 0.9},
            {"代码": "300154", "名称": "瑞凌股份", "排名": 2, "ML评分": 0.8},
        ]
    )
    df.to_csv(path, index=False, encoding="utf-8-sig")

    out_ex = p2._load_signal_df(path, top_n=10, include_bj9=False, exclude_st=True)
    out_in = p2._load_signal_df(path, top_n=10, include_bj9=False, exclude_st=False)

    assert len(out_ex) == 1
    assert out_ex.iloc[0]["名称"] == "瑞凌股份"
    assert len(out_in) == 2


def test_enrich_signal_amount_adds_conservative_and_execution_capacity():
    signal_df = pd.DataFrame({"代码": ["000001"], "名称": ["平安银行"], "ML评分": [0.9]})
    bars = pd.DataFrame(
        [
            {
                "trade_date": pd.Timestamp("2026-03-20"),
                "code": "000001",
                "amount": 80_000_000.0,
                "amount_ma20": 100_000_000.0,
                "amount_min5": 70_000_000.0,
                "amount_min10": 60_000_000.0,
            },
            {
                "trade_date": pd.Timestamp("2026-03-23"),
                "code": "000001",
                "amount": 50_000_000.0,
                "amount_ma20": 95_000_000.0,
                "amount_min5": 50_000_000.0,
                "amount_min10": 50_000_000.0,
            },
        ]
    ).set_index(["trade_date", "code"]).sort_index()

    out = p2._enrich_signal_amount_ma20(
        signal_df,
        bars,
        pd.Timestamp("2026-03-20"),
        trade_date=pd.Timestamp("2026-03-23"),
    )

    assert float(out.loc[0, "amount_ma20"]) == 100_000_000.0
    assert float(out.loc[0, "amount_capacity_conservative"]) == 60_000_000.0
    assert float(out.loc[0, "amount_execution_capacity"]) == 50_000_000.0


def test_assign_profile_target_weights_uses_configured_capacity_column():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001"],
            "名称": ["平安银行"],
            "ML评分": [0.9],
            "amount_ma20": [100_000_000.0],
            "amount_capacity_conservative": [10_000_000.0],
        }
    )

    out = p2._assign_profile_target_weights(
        signal_df=signal_df,
        profile_cfg={
            "optimizer_mode": "capacity_crowding_aware",
            "target_capital_base": 1_000_000.0,
            "target_max_adv_participation": 0.05,
            "target_capacity_amount_col": "amount_capacity_conservative",
            "target_capacity_amount_buffer": 0.5,
        },
        total_target_pos=0.60,
        max_single_pos=0.60,
        industry_map={"000001": "银行"},
    )

    assert float(out.loc[0, "target_weight"]) <= 0.25 + 1e-12
    assert "adv_participation_clip" in str(out.loc[0, "constraint_reason"])


def test_p2_main_blocks_when_metadata_gate_fails(monkeypatch):
    monkeypatch.setattr(
        p2,
        "load_ods_metadata_health",
        lambda _asof_date: {"ok": True, "coverage_pct": 10.0, "age_days": 0.2, "file": "mock.csv"},
    )
    monkeypatch.setattr(
        p2,
        "evaluate_metadata_guard",
        lambda info, **_kwargs: {
            **info,
            "passed": False,
            "reason": "industry_coverage_low",
            "min_coverage_pct": 80.0,
            "max_age_days": 3.0,
        },
    )
    monkeypatch.setattr(sys, "argv", ["quant_p2_paper_trade.py"])

    rc = p2.main()
    assert rc == 1


def test_attach_order_lifecycle_adds_platform_fields():
    orders = pd.DataFrame(
        [
            {"run_id": "r1", "code": "000001", "side": "BUY", "rank": 1, "requested_qty": 1000, "filled_qty": 1000, "status": "filled", "reason": "ok"},
            {"run_id": "r1", "code": "000002", "side": "BUY", "rank": 2, "requested_qty": 800, "filled_qty": 300, "status": "partial", "reason": "cash_limited"},
            {"run_id": "r1", "code": "000003", "side": "SELL", "rank": 3, "requested_qty": 500, "filled_qty": 0, "status": "blocked", "reason": "exit_not_tradable"},
            {"run_id": "r1", "code": "000004", "side": "BUY", "rank": 4, "requested_qty": 600, "filled_qty": 0, "status": "rejected", "reason": "insufficient_cash"},
        ]
    )

    enriched = p2._attach_order_lifecycle(orders)

    assert list(enriched["lifecycle_status"]) == ["filled", "partially_filled", "blocked", "rejected"]
    assert list(enriched["lifecycle_terminal"].astype(int)) == [1, 0, 1, 1]
    assert list(enriched["lifecycle_remaining_qty"].astype(int)) == [0, 500, 500, 600]
