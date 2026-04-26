# -*- coding: utf-8 -*-
"""执行层排序覆盖逻辑测试。"""

from __future__ import annotations

import pandas as pd

from utils.execution_overlay import add_execution_overlay_scores


def test_execution_overlay_adds_capacity_and_industry_balance_scores():
    df = pd.DataFrame(
        [
            {"score": 0.80, "close": 12.0, "amount_ma20": 1.2e8, "industry": "软件"},
            {"score": 0.78, "close": 15.0, "amount_ma20": 4.5e8, "industry": "软件"},
            {"score": 0.77, "close": 16.0, "amount_ma20": 3.8e8, "industry": "医药"},
        ]
    )

    out = add_execution_overlay_scores(
        df,
        base_score_col="score",
        price_col="close",
        amount_col="amount_ma20",
        industry_col="industry",
        liquidity_blend=0.10,
        adv_penalty_blend=0.14,
        industry_crowding_blend=0.18,
    )

    assert {"liquidity_score", "adv_capacity_score", "industry_balance_score", "execution_score"} <= set(out.columns)
    assert out["adv_capacity_score"].between(0.0, 1.0).all()
    assert out["industry_balance_score"].between(0.0, 1.0).all()


def test_execution_overlay_penalizes_more_crowded_industry():
    df = pd.DataFrame(
        [
            {"score": 0.82, "close": 20.0, "amount_ma20": 6.0e8, "industry": "软件"},
            {"score": 0.81, "close": 18.0, "amount_ma20": 5.0e8, "industry": "软件"},
            {"score": 0.80, "close": 17.0, "amount_ma20": 4.5e8, "industry": "软件"},
            {"score": 0.79, "close": 19.0, "amount_ma20": 4.8e8, "industry": "医药"},
        ]
    )

    out = add_execution_overlay_scores(
        df,
        base_score_col="score",
        price_col="close",
        amount_col="amount_ma20",
        industry_col="industry",
        industry_crowding_blend=0.20,
    )

    software_mean = out.loc[out["industry"] == "软件", "industry_balance_score"].mean()
    pharma_mean = out.loc[out["industry"] == "医药", "industry_balance_score"].mean()
    assert pharma_mean > software_mean
