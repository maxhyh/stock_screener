# -*- coding: utf-8 -*-
"""统一组合决策引擎测试。"""

from __future__ import annotations

import pandas as pd

from core.platform.portfolio_engine import PortfolioConstraints, build_portfolio_decision


def test_build_portfolio_decision_respects_industry_cap():
    candidates = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "ML评分": [0.9, 0.8, 0.7],
            "industry": ["银行", "银行", "电子"],
        }
    )
    decision = build_portfolio_decision(
        candidates,
        PortfolioConstraints(total_target=0.6, single_cap=0.35, industry_cap=0.35),
    )

    assert set(decision.selected["代码"]) == {"000001", "000003"}
    assert decision.exposures["max_industry_weight"] <= 0.35 + 1e-9


def test_build_portfolio_decision_blocks_when_min_names_not_met():
    candidates = pd.DataFrame({"代码": ["000001"], "ML评分": [0.9], "industry": ["银行"]})
    decision = build_portfolio_decision(
        candidates,
        PortfolioConstraints(total_target=0.5, single_cap=0.5, min_names=2),
    )
    assert decision.selected.empty
    assert decision.diagnostics["blocked_by_min_names"] is True


def test_build_portfolio_decision_clips_adv_and_reports_impact():
    candidates = pd.DataFrame(
        {
            "代码": ["000001", "000002"],
            "ML评分": [0.9, 0.8],
            "industry": ["银行", "电子"],
            "amount_ma20": [1_000_000.0, 100_000_000.0],
        }
    )

    decision = build_portfolio_decision(
        candidates,
        PortfolioConstraints(
            total_target=0.6,
            single_cap=0.5,
            adv_participation_cap=0.04,
            capital_base=1_000_000.0,
            amount_col="amount_ma20",
            impact_participation_bps=6.0,
        ),
    )

    first = decision.selected[decision.selected["代码"] == "000001"].iloc[0]
    assert first["target_weight"] <= 0.04 + 1e-12
    assert "adv_participation_clip" in first["constraint_reason"]
    assert "participation_pct" in decision.selected.columns
    assert "impact_cost_bps" in decision.selected.columns
    assert decision.exposures["max_adv_participation_pct"] <= 4.0 + 1e-9


def test_build_portfolio_decision_applies_capacity_amount_buffer():
    candidates = pd.DataFrame(
        {
            "代码": ["000001"],
            "ML评分": [0.9],
            "industry": ["银行"],
            "amount_capacity_conservative": [10_000_000.0],
        }
    )

    decision = build_portfolio_decision(
        candidates,
        PortfolioConstraints(
            total_target=0.5,
            single_cap=0.5,
            adv_participation_cap=0.05,
            capital_base=1_000_000.0,
            amount_col="amount_capacity_conservative",
            amount_buffer=0.5,
        ),
    )

    row = decision.selected.iloc[0]
    assert row["target_weight"] <= 0.25 + 1e-12
    assert "adv_participation_clip" in row["constraint_reason"]
    assert decision.diagnostics["constraints"]["amount_col"] == "amount_capacity_conservative"
    assert decision.diagnostics["constraints"]["amount_buffer"] == 0.5


def test_build_portfolio_decision_redistributes_clipped_capacity():
    candidates = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "ML评分": [0.95, 0.90, 0.85],
            "industry": ["银行", "电子", "医药"],
            "amount_ma20": [1_000_000.0, 100_000_000.0, 100_000_000.0],
        }
    )

    no_redistribution = build_portfolio_decision(
        candidates,
        PortfolioConstraints(
            total_target=0.60,
            single_cap=0.40,
            adv_participation_cap=0.04,
            capital_base=1_000_000.0,
            amount_col="amount_ma20",
            redistribute_clipped=False,
        ),
    )
    redistributed = build_portfolio_decision(
        candidates,
        PortfolioConstraints(
            total_target=0.60,
            single_cap=0.40,
            adv_participation_cap=0.04,
            capital_base=1_000_000.0,
            amount_col="amount_ma20",
            redistribute_clipped=True,
        ),
    )

    assert redistributed.exposures["total_weight"] > no_redistribution.exposures["total_weight"]
    assert redistributed.exposures["total_weight"] <= 0.60 + 1e-12
    assert redistributed.exposures["max_adv_participation_pct"] <= 4.0 + 1e-9
    assert redistributed.diagnostics["capacity_shortfall_weight"] < no_redistribution.diagnostics["capacity_shortfall_weight"]
    assert redistributed.selected["constraint_reason"].astype(str).str.contains("redistributed_in").any()


def test_build_portfolio_decision_uses_reserve_rows_after_primary_capacity_clip():
    candidates = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "ML评分": [0.95, 0.90, 0.85],
            "industry": ["银行", "电子", "医药"],
            "amount_ma20": [1_000_000.0, 100_000_000.0, 100_000_000.0],
        }
    )

    decision = build_portfolio_decision(
        candidates,
        PortfolioConstraints(
            total_target=0.60,
            single_cap=0.30,
            max_names=2,
            adv_participation_cap=0.04,
            capital_base=1_000_000.0,
            amount_col="amount_ma20",
            redistribute_clipped=True,
        ),
    )

    selected = decision.selected.set_index("代码")
    assert "000003" in selected.index
    assert float(selected.loc["000003", "target_weight_raw"]) == 0.0
    assert float(selected.loc["000003", "target_weight"]) > 0.0
    assert "redistributed_in" in str(selected.loc["000003", "constraint_reason"])
    assert decision.diagnostics["constraints"]["max_names"] == 2


def test_build_portfolio_decision_redistribution_respects_industry_cap():
    candidates = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003", "000004"],
            "ML评分": [0.95, 0.90, 0.85, 0.80],
            "industry": ["银行", "银行", "电子", "医药"],
            "amount_ma20": [100_000_000.0] * 4,
        }
    )

    decision = build_portfolio_decision(
        candidates,
        PortfolioConstraints(
            total_target=0.60,
            single_cap=0.30,
            industry_cap=0.30,
            adv_participation_cap=0.10,
            capital_base=1_000_000.0,
            amount_col="amount_ma20",
            redistribute_clipped=True,
        ),
    )

    assert decision.exposures["total_weight"] <= 0.60 + 1e-12
    assert decision.exposures["max_industry_weight"] <= 0.30 + 1e-12
    assert float(decision.selected.groupby("industry")["target_weight"].sum().max()) <= 0.30 + 1e-12
