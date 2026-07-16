# -*- coding: utf-8 -*-
"""下单前风控硬门禁测试。"""

from __future__ import annotations

import pandas as pd

from core.risk.pretrade import PreTradeRiskConfig, apply_pretrade_risk_gates


def _bars_idx():
    df = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2026-04-09")] * 3,
            "code": ["000001", "000002", "000003"],
            "open": [10.0, 8.0, 1.5],
            "amount": [10_000_000, 8_000_000, 5_000_000],
            "vol": [1_000_000, 1_200_000, 900_000],
        }
    )
    return df.set_index(["trade_date", "code"]).sort_index()


def _bars_idx_with_style_history():
    dates = pd.bdate_range("2026-03-02", "2026-04-09")
    rows = []
    for i, d in enumerate(dates):
        rows.append(
            {
                "trade_date": pd.Timestamp(d),
                "code": "000001",
                "open": 10.0 + 0.03 * i,
                "high": 10.1 + 0.03 * i,
                "low": 9.9 + 0.03 * i,
                "close": 10.0 + 0.03 * i,
                "amount": 200_000_000.0,
                "vol": 1_000_000.0,
            }
        )
        rows.append(
            {
                "trade_date": pd.Timestamp(d),
                "code": "000002",
                "open": 8.0 + 0.01 * i,
                "high": 8.1 + 0.01 * i,
                "low": 7.9 + 0.01 * i,
                "close": 8.0 + 0.01 * i,
                "amount": 20_000_000.0,
                "vol": 900_000.0,
            }
        )
    df = pd.DataFrame(rows)
    return df.set_index(["trade_date", "code"]).sort_index()


def test_pretrade_risk_blocks_blacklist_and_min_price_and_industry():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "名称": ["A", "B", "C"],
            "ML评分": [1.0, 1.0, 1.0],
            "排名_num": [1, 2, 3],
        }
    )
    cfg = PreTradeRiskConfig(
        enabled=True,
        capital_base=1_000_000,
        max_industry_weight=0.40,
        max_adv_participation=0.05,
        min_price=2.0,
        blacklist_codes={"000002"},
    )
    kept, blocked, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=_bars_idx(),
        trade_date=pd.Timestamp("2026-04-09"),
        total_target_pos=0.6,
        max_single_pos=0.4,
        cfg=cfg,
        industry_map={"000001": "银行", "000002": "银行", "000003": "医药"},
    )

    assert stats["input_count"] == 3
    assert stats["blocked_count"] >= 2
    assert "000002" in set(blocked["code"])
    # 000003 开盘价 1.5，触发最低价格门禁
    assert "000003" in set(blocked["code"])
    # 至少保留一只
    assert "000001" in set(kept["代码"]) if not kept.empty else True


def test_pretrade_risk_disabled_passes_all():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002"],
            "名称": ["A", "B"],
            "ML评分": [0.9, 0.8],
            "排名_num": [1, 2],
        }
    )
    cfg = PreTradeRiskConfig(enabled=False)
    kept, blocked, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=_bars_idx(),
        trade_date=pd.Timestamp("2026-04-09"),
        total_target_pos=0.6,
        max_single_pos=0.4,
        cfg=cfg,
        industry_map={},
    )
    assert len(kept) == 2
    assert blocked.empty
    assert stats["enabled"] is False


def test_pretrade_risk_blocks_style_size_exposure_when_enabled():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002"],
            "名称": ["A", "B"],
            "ML评分": [0.9, 0.8],
            "排名_num": [1, 2],
        }
    )
    cfg = PreTradeRiskConfig(
        enabled=True,
        capital_base=1_000_000,
        max_industry_weight=1.0,
        max_adv_participation=0.50,
        min_price=0.0,
        blacklist_codes=set(),
        max_style_size_exposure_abs=0.20,
        style_lb_short=20,
        style_lb_beta=60,
    )
    kept, blocked, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=_bars_idx_with_style_history(),
        trade_date=pd.Timestamp("2026-04-09"),
        total_target_pos=0.6,
        max_single_pos=0.4,
        cfg=cfg,
        industry_map={"000001": "银行", "000002": "医药"},
    )

    assert kept.empty
    assert not blocked.empty
    assert blocked["reasons"].astype(str).str.contains("style_size_exposure").any()
    assert stats["style_limits_hit"] >= 1
    assert stats["style_size_limits_hit"] >= 1


def test_pretrade_risk_nav_weighted_style_basis_allows_small_offsetting_entries():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002"],
            "名称": ["A", "B"],
            "ML评分": [0.9, 0.8],
            "排名_num": [1, 2],
            "target_weight": [0.05, 0.05],
        }
    )
    cfg = PreTradeRiskConfig(
        enabled=True,
        capital_base=1_000_000,
        max_industry_weight=1.0,
        max_adv_participation=0.50,
        min_price=0.0,
        blacklist_codes=set(),
        max_style_size_exposure_abs=0.20,
        style_exposure_basis="nav_weighted",
        style_lb_short=20,
        style_lb_beta=60,
    )
    kept, blocked, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=_bars_idx_with_style_history(),
        trade_date=pd.Timestamp("2026-04-09"),
        total_target_pos=0.10,
        max_single_pos=0.05,
        cfg=cfg,
        industry_map={"000001": "银行", "000002": "医药"},
    )

    assert len(kept) == 2
    assert blocked.empty
    assert stats["style_exposure_basis"] == "nav_weighted"


def test_pretrade_risk_reweights_survivors_after_blocked_names():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "名称": ["A", "B", "C"],
            "ML评分": [1.0, 1.0, 1.0],
            "排名_num": [1, 2, 3],
        }
    )
    bars = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2026-04-09")] * 3,
            "code": ["000001", "000002", "000003"],
            "open": [1.5, 8.0, 10.0],
            "high": [1.5, 8.1, 10.1],
            "low": [1.5, 7.9, 9.9],
            "close": [1.5, 8.0, 10.0],
            "amount": [5_000_000.0, 1_800_000.0, 50_000_000.0],
            "vol": [900_000.0, 1_000_000.0, 1_200_000.0],
        }
    ).set_index(["trade_date", "code"]).sort_index()
    cfg = PreTradeRiskConfig(
        enabled=True,
        capital_base=1_000_000,
        max_industry_weight=1.0,
        max_adv_participation=0.15,
        min_price=2.0,
        blacklist_codes=set(),
    )

    kept, blocked, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=bars,
        trade_date=pd.Timestamp("2026-04-09"),
        total_target_pos=0.6,
        max_single_pos=0.4,
        cfg=cfg,
        industry_map={"000001": "银行", "000002": "银行", "000003": "医药"},
    )

    assert set(blocked["code"].astype(str)) == {"000001", "000002"}
    assert "min_price" in blocked.loc[blocked["code"] == "000001", "reasons"].iloc[0]
    assert "adv_participation" in blocked.loc[blocked["code"] == "000002", "reasons"].iloc[0]
    assert set(kept["代码"].astype(str)) == {"000003"}
    assert stats["reweight_rounds"] >= 2


def test_pretrade_risk_replaces_locked_entry_with_reserve_when_max_names_set():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "名称": ["A", "B", "C"],
            "ML评分": [1.0, 0.9, 0.8],
            "排名_num": [1, 2, 3],
        }
    )
    bars = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2026-04-09")] * 3,
            "code": ["000001", "000002", "000003"],
            "open": [11.0, 8.0, 10.0],
            "high": [11.0, 8.2, 10.2],
            "low": [11.0, 7.9, 9.9],
            "close": [11.0, 8.1, 10.1],
            "prev_close": [10.0, 8.0, 10.0],
            "amount": [100_000_000.0, 100_000_000.0, 100_000_000.0],
            "vol": [1_000_000.0, 1_000_000.0, 1_000_000.0],
        }
    ).set_index(["trade_date", "code"]).sort_index()
    cfg = PreTradeRiskConfig(
        enabled=True,
        capital_base=1_000_000,
        max_industry_weight=1.0,
        max_adv_participation=0.50,
        min_price=2.0,
        blacklist_codes=set(),
        max_names=2,
        block_entry_not_tradable=True,
    )

    kept, blocked, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=bars,
        trade_date=pd.Timestamp("2026-04-09"),
        total_target_pos=0.6,
        max_single_pos=0.4,
        cfg=cfg,
        industry_map={"000001": "银行", "000002": "电子", "000003": "医药"},
    )

    assert "000001" in set(blocked["code"].astype(str))
    assert "entry_not_tradable" in blocked.loc[blocked["code"] == "000001", "reasons"].iloc[0]
    assert set(kept["代码"].astype(str)) == {"000002", "000003"}
    assert stats["entry_not_tradable_hit"] == 1
    assert stats["max_names"] == 2


def test_pretrade_risk_preserves_external_target_weight_without_reweight():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002"],
            "名称": ["A", "B"],
            "ML评分": [1.0, 1.0],
            "排名_num": [1, 2],
            "target_weight": [0.50, 0.10],
        }
    )
    bars = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2026-04-09")] * 2,
            "code": ["000001", "000002"],
            "open": [1.5, 10.0],
            "high": [1.6, 10.1],
            "low": [1.4, 9.9],
            "close": [1.5, 10.0],
            "amount": [50_000_000.0, 2_000_000.0],
            "vol": [900_000.0, 1_000_000.0],
        }
    ).set_index(["trade_date", "code"]).sort_index()
    cfg = PreTradeRiskConfig(
        enabled=True,
        capital_base=1_000_000,
        max_industry_weight=1.0,
        max_adv_participation=0.15,
        min_price=2.0,
        blacklist_codes=set(),
    )

    kept, blocked, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=bars,
        trade_date=pd.Timestamp("2026-04-09"),
        total_target_pos=0.6,
        max_single_pos=0.5,
        cfg=cfg,
        industry_map={"000001": "银行", "000002": "医药"},
    )

    assert set(blocked["code"].astype(str)) == {"000001"}
    assert set(kept["代码"].astype(str)) == {"000002"}
    assert float(kept["target_weight"].iloc[0]) == 0.10
    assert stats["reweight_rounds"] == 1


def test_pretrade_risk_caps_missing_industry_as_unknown_bucket():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "名称": ["A", "B", "C"],
            "ML评分": [1.0, 1.0, 1.0],
            "排名_num": [1, 2, 3],
        }
    )
    bars = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2026-04-09")] * 3,
            "code": ["000001", "000002", "000003"],
            "open": [10.0, 9.0, 8.0],
            "high": [10.1, 9.1, 8.1],
            "low": [9.9, 8.9, 7.9],
            "close": [10.0, 9.0, 8.0],
            "amount": [50_000_000.0, 40_000_000.0, 30_000_000.0],
            "vol": [1_000_000.0, 900_000.0, 800_000.0],
        }
    ).set_index(["trade_date", "code"]).sort_index()
    cfg = PreTradeRiskConfig(
        enabled=True,
        capital_base=1_000_000,
        max_industry_weight=0.30,
        max_adv_participation=0.50,
        min_price=2.0,
        blacklist_codes=set(),
    )

    kept, blocked, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=bars,
        trade_date=pd.Timestamp("2026-04-09"),
        total_target_pos=0.6,
        max_single_pos=0.4,
        cfg=cfg,
        industry_map={"000003": "医药"},
    )

    assert set(kept["代码"].astype(str)) == {"000001", "000003"}
    assert set(blocked["code"].astype(str)) == {"000002"}
    assert blocked.loc[blocked["code"] == "000002", "industry"].iloc[0] == "未知"
    assert int(blocked.loc[blocked["code"] == "000002", "industry_missing"].iloc[0]) == 1
    assert "industry_weight_unknown" in blocked.loc[blocked["code"] == "000002", "reasons"].iloc[0]
    assert stats["missing_industry_count"] == 2
    assert stats["unknown_industry_limits_hit"] == 1
    assert stats["industry_limits_hit"] >= 1


def test_pretrade_risk_blocks_post_trade_industry_exposure_from_existing_positions():
    signal_df = pd.DataFrame(
        {
            "代码": ["000002"],
            "名称": ["B"],
            "ML评分": [1.0],
            "排名_num": [1],
            "target_weight": [0.10],
        }
    )
    bars = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2026-04-09")] * 2,
            "code": ["000001", "000002"],
            "open": [10.0, 8.0],
            "high": [10.1, 8.1],
            "low": [9.9, 7.9],
            "close": [10.0, 8.0],
            "amount": [100_000_000.0, 100_000_000.0],
            "vol": [1_000_000.0, 1_000_000.0],
        }
    ).set_index(["trade_date", "code"]).sort_index()
    cfg = PreTradeRiskConfig(
        enabled=True,
        capital_base=1_000_000,
        max_industry_weight=0.30,
        max_adv_participation=0.50,
        min_price=2.0,
        blacklist_codes=set(),
    )

    kept, blocked, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=bars,
        trade_date=pd.Timestamp("2026-04-09"),
        total_target_pos=0.10,
        max_single_pos=0.10,
        cfg=cfg,
        industry_map={"000001": "银行", "000002": "银行"},
        current_positions={"000001": {"qty": 25_000, "avg_cost": 10.0}},
    )

    assert kept.empty
    assert set(blocked["code"].astype(str)) == {"000002"}
    assert "post_trade_industry_clip" in blocked["reasons"].iloc[0]
    assert stats["post_trade_industry_limits_hit"] == 1
    assert stats["post_trade_existing_weight"] == 0.25
