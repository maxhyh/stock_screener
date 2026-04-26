# -*- coding: utf-8 -*-
"""quant_profile_ab_compare 配置传递测试。"""

from __future__ import annotations

import argparse

import scripts.quant_profile_ab_compare as qpab


def test_build_cfg_passes_liquidity_fields():
    args = argparse.Namespace(
        start="2025-01-01",
        end="2025-01-31",
        benchmark_file=None,
        verbose=False,
    )
    cfg = qpab._build_cfg(
        {
            "top_n": 14,
            "corr_lookback_days": 75,
            "corr_min_obs": 18,
            "min_price": 3.0,
            "min_amount_ma20": 100000000.0,
            "liquidity_blend": 0.16,
            "adv_penalty_blend": 0.14,
            "industry_crowding_blend": 0.18,
            "promotion_loss_clamp_enabled": False,
            "optimizer_mode": "capacity_crowding_aware",
            "target_capital_base": 1000000.0,
            "target_max_industry_weight": 0.30,
            "target_max_adv_participation": 0.04,
            "impact_model": "sqrt",
            "impact_participation_bps": 6.0,
        },
        args,
    )

    assert cfg.top_n == 14
    assert cfg.corr_lookback_days == 75
    assert cfg.corr_min_obs == 18
    assert cfg.min_price == 3.0
    assert cfg.min_amount_ma20 == 100000000.0
    assert cfg.liquidity_blend == 0.16
    assert cfg.adv_penalty_blend == 0.14
    assert cfg.industry_crowding_blend == 0.18
    assert cfg.loss_clamp_enabled is False
    assert cfg.optimizer_mode == "capacity_crowding_aware"
    assert cfg.target_capital_base == 1000000.0
    assert cfg.target_max_industry_weight == 0.30
    assert cfg.target_max_adv_participation == 0.04
    assert cfg.impact_model == "sqrt"
    assert cfg.impact_participation_bps == 6.0
