# -*- coding: utf-8 -*-
"""daily_ml_select 前置风控联动测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.daily_ml_select import _apply_signal_pretrade_gate


def _ranking_pool() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003"],
            "name": ["A", "B", "C"],
            "refactor_score": [0.90, 0.80, 0.70],
        }
    )


def _bars_window() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003"],
            "trade_date": [pd.Timestamp("2026-04-09")] * 3,
            "open": [10.0, 1.5, 5.0],
            "high": [10.2, 1.6, 5.1],
            "low": [9.8, 1.4, 4.9],
            "close": [10.0, 1.5, 5.0],
            "vol": [1_000_000.0, 800_000.0, 900_000.0],
            "amount": [10_000_000.0, 8_000_000.0, 9_000_000.0],
        }
    )


def _bars_window_with_next_day() -> pd.DataFrame:
    base = _bars_window()
    next_day = base.copy()
    next_day["trade_date"] = pd.Timestamp("2026-04-10")
    next_day.loc[next_day["ts_code"] == "000001", "open"] = 1.0
    next_day.loc[next_day["ts_code"] == "000001", "close"] = 1.0
    next_day.loc[next_day["ts_code"] == "000002", ["open", "high", "low", "close"]] = [3.0, 3.1, 2.9, 3.0]
    return pd.concat([base, next_day], ignore_index=True)


def _set_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_GATE", "true")
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY", "false")
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_POOL_N", "3")
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_CAPITAL_BASE", "1000000")
    monkeypatch.setenv("MFTS_RISK_MAX_INDUSTRY_WEIGHT", "1.0")
    monkeypatch.setenv("MFTS_RISK_MAX_ADV_PARTICIPATION", "0.50")
    monkeypatch.setenv("MFTS_RISK_MAX_STYLE_SIZE_EXPOSURE_ABS", "0.0")
    monkeypatch.setenv("MFTS_RISK_MAX_STYLE_BETA_EXPOSURE_ABS", "0.0")
    monkeypatch.setenv("MFTS_RISK_MAX_STYLE_MOMENTUM_EXPOSURE_ABS", "0.0")
    monkeypatch.setenv("MFTS_RISK_MAX_STYLE_VOL_EXPOSURE_ABS", "0.0")
    monkeypatch.setenv("MFTS_RISK_STYLE_LB_SHORT", "20")
    monkeypatch.setenv("MFTS_RISK_STYLE_LB_BETA", "60")
    monkeypatch.delenv("MFTS_RISK_BLACKLIST_FILE", raising=False)


def test_signal_pretrade_gate_blocks_min_price(monkeypatch: pytest.MonkeyPatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_STRICT", "false")
    monkeypatch.setenv("MFTS_RISK_MIN_PRICE", "2.0")

    gated, blocked, info = _apply_signal_pretrade_gate(
        ranking_pool=_ranking_pool(),
        ranking_col="refactor_score",
        bars_window_df=_bars_window(),
        signal_date=pd.Timestamp("2026-04-09"),
        top_n=2,
        regime_position_range="60%-80%",
        regime_single_stock_max="10%",
        industry_map={"000001": "银行", "000002": "银行", "000003": "医药"},
    )

    assert info["stage"] == "pretrade_gate_on"
    assert int(info["blocked_count"]) == 1
    assert str(info["top_reason"]) == "min_price"
    assert set(gated["ts_code"].astype(str)) == {"000001", "000003"}
    assert set(blocked["code"].astype(str)) == {"000002"}


def test_signal_pretrade_gate_defaults_to_research_safe_signal_day(monkeypatch: pytest.MonkeyPatch):
    _set_base_env(monkeypatch)
    monkeypatch.delenv("MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY", raising=False)
    monkeypatch.setenv("MFTS_RISK_MIN_PRICE", "2.0")

    gated, _blocked, info = _apply_signal_pretrade_gate(
        ranking_pool=_ranking_pool(),
        ranking_col="refactor_score",
        bars_window_df=_bars_window_with_next_day(),
        signal_date=pd.Timestamp("2026-04-09"),
        top_n=2,
        regime_position_range="60%-80%",
        regime_single_stock_max="10%",
        industry_map={"000001": "银行", "000002": "银行", "000003": "医药"},
    )

    assert info["trade_date"] == "2026-04-09"
    assert int(info["research_safe_mode"]) == 1
    assert int(info["pretrade_uses_next_trade_day"]) == 0
    assert "000001" in set(gated["ts_code"].astype(str))


def test_signal_pretrade_gate_next_day_mode_is_explicit_expost(monkeypatch: pytest.MonkeyPatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY", "true")
    monkeypatch.setenv("MFTS_RISK_MIN_PRICE", "2.0")

    gated, blocked, info = _apply_signal_pretrade_gate(
        ranking_pool=_ranking_pool(),
        ranking_col="refactor_score",
        bars_window_df=_bars_window_with_next_day(),
        signal_date=pd.Timestamp("2026-04-09"),
        top_n=2,
        regime_position_range="60%-80%",
        regime_single_stock_max="10%",
        industry_map={"000001": "银行", "000002": "银行", "000003": "医药"},
    )

    assert info["trade_date"] == "2026-04-10"
    assert int(info["research_safe_mode"]) == 0
    assert int(info["pretrade_uses_next_trade_day"]) == 1
    assert "000001" not in set(gated["ts_code"].astype(str))
    assert "000001" in set(blocked["code"].astype(str))


def test_signal_pretrade_gate_fallback_when_kept_insufficient(monkeypatch: pytest.MonkeyPatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_STRICT", "false")
    monkeypatch.setenv("MFTS_RISK_MIN_PRICE", "20.0")

    ranking_pool = _ranking_pool()
    gated, blocked, info = _apply_signal_pretrade_gate(
        ranking_pool=ranking_pool,
        ranking_col="refactor_score",
        bars_window_df=_bars_window(),
        signal_date=pd.Timestamp("2026-04-09"),
        top_n=2,
        regime_position_range="60%-80%",
        regime_single_stock_max="10%",
        industry_map={"000001": "银行", "000002": "银行", "000003": "医药"},
    )

    assert info["stage"] == "pretrade_gate_fallback"
    assert int(info["blocked_count"]) == 3
    assert len(gated) == len(ranking_pool)
    assert set(gated["ts_code"].astype(str)) == set(ranking_pool["ts_code"].astype(str))
    assert not blocked.empty


def test_signal_pretrade_gate_strict_raises_when_kept_insufficient(monkeypatch: pytest.MonkeyPatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_STRICT", "true")
    monkeypatch.setenv("MFTS_RISK_MIN_PRICE", "20.0")

    with pytest.raises(RuntimeError):
        _apply_signal_pretrade_gate(
            ranking_pool=_ranking_pool(),
            ranking_col="refactor_score",
            bars_window_df=_bars_window(),
            signal_date=pd.Timestamp("2026-04-09"),
            top_n=2,
            regime_position_range="60%-80%",
            regime_single_stock_max="10%",
            industry_map={"000001": "银行", "000002": "银行", "000003": "医药"},
        )


def test_signal_pretrade_gate_adaptive_pool_expands_to_meet_topn(monkeypatch: pytest.MonkeyPatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_STRICT", "false")
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_ALLOW_EXPAND", "true")
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_POOL_MULT", "1.0")
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_POOL_MIN_N", "2")
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_POOL_STEP_N", "1")
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_POOL_MAX_N", "3")
    monkeypatch.delenv("MFTS_SIGNAL_PRETRADE_POOL_N", raising=False)
    monkeypatch.setenv("MFTS_SIGNAL_PRETRADE_STRESS_BLOCK_RATE_PCT", "100")
    monkeypatch.setenv("MFTS_RISK_MIN_PRICE", "2.0")

    gated, blocked, info = _apply_signal_pretrade_gate(
        ranking_pool=_ranking_pool(),
        ranking_col="refactor_score",
        bars_window_df=_bars_window(),
        signal_date=pd.Timestamp("2026-04-09"),
        top_n=2,
        regime_position_range="60%-80%",
        regime_single_stock_max="10%",
        industry_map={"000001": "银行", "000002": "银行", "000003": "医药"},
    )

    assert info["stage"] == "pretrade_gate_on"
    assert int(info["pool_n"]) == 3
    assert int(info["pool_expand_rounds_used"]) == 1
    assert list(info["pool_n_plan"]) == [2, 3]
    assert set(gated["ts_code"].astype(str)) == {"000001", "000003"}
    assert not blocked.empty
