# -*- coding: utf-8 -*-
"""daily_ml_select 数据窗口读取测试。"""

from __future__ import annotations

import sys

import pandas as pd
import pytest

import scripts.daily_ml_select as daily_ml_select


def test_load_default_profile_config_reads_default_profile(tmp_path):
    cfg = tmp_path / "quant_live_profiles.json"
    cfg.write_text(
        """
        {
          "default_profile": "quality_regime",
          "profiles": {
            "quality_regime": {
              "top_n": 13,
              "ml_quality_blend": 0.78,
              "min_refactor_score": 0.56
            }
          }
        }
        """,
        encoding="utf-8",
    )

    out = daily_ml_select.load_default_profile_config(cfg)

    assert int(out["top_n"]) == 13
    assert float(out["ml_quality_blend"]) == 0.78
    assert float(out["min_refactor_score"]) == 0.56


def test_load_latest_data_respects_columns_and_date_window(monkeypatch):
    source = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260407", "open": 10.0, "close": 10.1, "vol": 100.0, "amount": 101000.0, "pct_chg": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260408", "open": 10.2, "close": 10.3, "vol": 110.0, "amount": 113300.0, "pct_chg": 2.0},
            {"ts_code": "000001.SZ", "trade_date": "20260409", "open": 10.4, "close": 10.5, "vol": 120.0, "amount": 126000.0, "pct_chg": 1.5},
        ]
    )

    class FakeGateway:
        def load_bars(self, *_args, **_kwargs):
            out = source.copy()
            out.attrs["market_data_lineage"] = {"data_source": "ashare_ods"}
            return out

    monkeypatch.setattr(daily_ml_select, "AShareMarketDataGateway", lambda: FakeGateway())

    out = daily_ml_select.load_latest_data(
        columns=["open", "close"],
        start_date=pd.Timestamp("2026-04-08"),
        end_date=pd.Timestamp("2026-04-08"),
    )

    assert set(out.columns) == {"ts_code", "trade_date", "open", "close"}
    assert out["trade_date"].dt.strftime("%Y%m%d").tolist() == ["20260408"]
    assert out["ts_code"].tolist() == ["000001"]


def test_load_latest_data_reads_shared_ods_gateway_and_preserves_lineage(monkeypatch):
    source = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "2026-04-07", "open": 10.0, "close": 10.1, "vol": 100.0, "amount": 101000.0},
            {"ts_code": "000001.SZ", "trade_date": "2026-04-08", "open": 10.2, "close": 10.3, "vol": 110.0, "amount": 113300.0},
        ]
    )
    calls: list[dict[str, object]] = []

    class FakeGateway:
        def available_trade_dates(self):
            return ["2026-04-07", "2026-04-08"]

        def load_bars(self, start, end, *, include_bj9, lookback_sessions=0, forward_sessions=0):
            calls.append({"start": str(start), "end": str(end), "include_bj9": include_bj9})
            out = source.copy()
            out.attrs["market_data_lineage"] = {"data_source": "ashare_ods", "snapshot_digest": "test"}
            return out

    monkeypatch.setattr(daily_ml_select, "AShareMarketDataGateway", lambda: FakeGateway(), raising=False)

    out = daily_ml_select.load_latest_data(
        columns=["open", "close"],
        start_date=pd.Timestamp("2026-04-08"),
        end_date=pd.Timestamp("2026-04-08"),
    )

    assert calls == [{"start": "2026-04-08 00:00:00", "end": "2026-04-08 00:00:00", "include_bj9": False}]
    assert set(out.columns) == {"ts_code", "trade_date", "open", "close"}
    assert out["ts_code"].tolist() == ["000001"]
    assert out.attrs["market_data_lineage"]["data_source"] == "ashare_ods"


def test_load_latest_data_cache_reuses_identical_ods_requests(monkeypatch):
    source = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260407", "open": 10.0, "amount": 101000.0},
            {"ts_code": "000002.SZ", "trade_date": "20260408", "open": 11.0, "amount": 111000.0},
        ]
    )
    calls: list[dict[str, object]] = []

    class FakeGateway:
        def load_bars(self, start, end, *, include_bj9, lookback_sessions=0, forward_sessions=0):
            calls.append({"start": str(start), "end": str(end), "include_bj9": include_bj9})
            out = source.copy()
            out.attrs["market_data_lineage"] = {"data_source": "ashare_ods", "snapshot_digest": "cache-test"}
            return out

    daily_ml_select._DATA_CACHE.clear()
    monkeypatch.setenv("MFTS_DAILY_SELECT_CACHE_DATA", "true")
    monkeypatch.setattr(daily_ml_select, "AShareMarketDataGateway", lambda: FakeGateway())

    first = daily_ml_select.load_latest_data(
        columns=["open", "amount"],
        start_date=pd.Timestamp("2026-04-07"),
        end_date=pd.Timestamp("2026-04-07"),
    )
    second = daily_ml_select.load_latest_data(
        columns=["open", "amount"],
        start_date=pd.Timestamp("2026-04-07"),
        end_date=pd.Timestamp("2026-04-07"),
    )

    assert len(calls) == 1
    assert calls[0]["include_bj9"] is False
    assert first["ts_code"].tolist() == ["000001"]
    assert second["ts_code"].tolist() == ["000001"]
    daily_ml_select._DATA_CACHE.clear()


def test_cached_indicator_window_reuses_indicator_frame(monkeypatch):
    source = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260401",
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.0,
                "vol": 100.0,
                "amount": 100000.0,
                "pct_chg": 0.0,
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260402",
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
                "vol": 120.0,
                "amount": 122000.0,
                "pct_chg": 2.0,
            },
        ]
    )
    calls = {"load": 0, "calc": 0}

    def fake_load_latest_data(**_kwargs):
        calls["load"] += 1
        out = source.copy()
        out["trade_date"] = pd.to_datetime(out["trade_date"])
        return out

    def fake_calc_indicators(df):
        calls["calc"] += 1
        out = df.copy()
        out["ma120"] = 1.0
        out["vol_ma20"] = 100.0
        out["z_score"] = 0.0
        out["close_5"] = 10.0
        return out

    daily_ml_select._INDICATOR_DATA_CACHE.clear()
    monkeypatch.setenv("MFTS_DAILY_SELECT_CACHE_START", "20260401")
    monkeypatch.setenv("MFTS_DAILY_SELECT_CACHE_END", "20260402")
    monkeypatch.setattr(daily_ml_select, "load_latest_data", fake_load_latest_data)
    monkeypatch.setattr(daily_ml_select, "calc_indicators", fake_calc_indicators)

    first = daily_ml_select._load_cached_indicator_window(
        columns=["open", "high", "low", "close", "vol", "amount", "pct_chg"],
        start_date=pd.Timestamp("2026-04-01"),
        end_date=pd.Timestamp("2026-04-01"),
    )
    second = daily_ml_select._load_cached_indicator_window(
        columns=["open", "high", "low", "close", "vol", "amount", "pct_chg"],
        start_date=pd.Timestamp("2026-04-02"),
        end_date=pd.Timestamp("2026-04-02"),
    )

    assert calls == {"load": 1, "calc": 1}
    assert first["trade_date"].dt.strftime("%Y%m%d").tolist() == ["20260401"]
    assert second["trade_date"].dt.strftime("%Y%m%d").tolist() == ["20260402"]
    assert "vol_ratio" in second.columns
    daily_ml_select._INDICATOR_DATA_CACHE.clear()


def test_signal_pretrade_cfg_uses_profile_style_defaults(monkeypatch):
    for key in (
        "MFTS_RISK_MAX_STYLE_SIZE_EXPOSURE_ABS",
        "MFTS_RISK_MAX_STYLE_BETA_EXPOSURE_ABS",
        "MFTS_RISK_MAX_STYLE_MOMENTUM_EXPOSURE_ABS",
        "MFTS_RISK_MAX_STYLE_VOL_EXPOSURE_ABS",
        "MFTS_RISK_STYLE_EXPOSURE_BASIS",
        "MFTS_RISK_STYLE_LB_SHORT",
        "MFTS_RISK_STYLE_LB_BETA",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = daily_ml_select._build_signal_pretrade_cfg_from_env(
        {
            "risk_max_style_size_exposure_abs": 0.9,
            "risk_max_style_beta_exposure_abs": 0.8,
            "risk_max_style_momentum_exposure_abs": 1.2,
            "risk_max_style_vol_exposure_abs": 1.1,
            "risk_style_exposure_basis": "nav_weighted",
            "risk_style_lb_short": 30,
            "risk_style_lb_beta": 80,
        }
    )

    assert cfg.max_style_size_exposure_abs == pytest.approx(0.9)
    assert cfg.max_style_beta_exposure_abs == pytest.approx(0.8)
    assert cfg.max_style_momentum_exposure_abs == pytest.approx(1.2)
    assert cfg.max_style_vol_exposure_abs == pytest.approx(1.1)
    assert cfg.style_exposure_basis == "nav_weighted"
    assert cfg.style_lb_short == 30
    assert cfg.style_lb_beta == 80


def test_resolve_score_quantile_preserves_defaults_and_profile_overrides():
    assert daily_ml_select._resolve_score_quantile({}, "正常") == (0.60, "default_regime_map")
    assert daily_ml_select._resolve_score_quantile({}, "震荡") == (0.75, "default_regime_map")
    assert daily_ml_select._resolve_score_quantile({}, "恐慌") == (0.85, "default_regime_map")
    assert daily_ml_select._resolve_score_quantile({}, "unknown") == (0.50, "default_regime_map")

    q, source = daily_ml_select._resolve_score_quantile({"score_quantile_normal": 0.35}, "正常")
    assert q == pytest.approx(0.35)
    assert source == "score_quantile_normal"

    q, source = daily_ml_select._resolve_score_quantile({"score_quantile_q": 1.25}, "正常")
    assert q == pytest.approx(1.0)
    assert source == "score_quantile_q"

    q, source = daily_ml_select._resolve_score_quantile({"score_quantile_map": {"恐慌": 0.40}}, "恐慌")
    assert q == pytest.approx(0.40)
    assert source == "profile_score_quantile_map:恐慌"


def test_main_blocks_when_metadata_gate_fails(monkeypatch):
    monkeypatch.setattr(
        daily_ml_select,
        "load_ods_metadata_health",
        lambda _asof_date: {"ok": True, "coverage_pct": 10.0, "age_days": 0.0, "file": "ashare_ods:instrument_master"},
    )
    monkeypatch.setattr(
        daily_ml_select,
        "evaluate_metadata_guard",
        lambda info, **_kwargs: {
            **info,
            "passed": False,
            "reason": "industry_coverage_low",
            "min_coverage_pct": 80.0,
            "max_age_days": 3.0,
        },
    )
    monkeypatch.setattr(sys, "argv", ["daily_ml_select.py", "--date", "20260408"])

    with pytest.raises(SystemExit) as exc:
        daily_ml_select.main()
    assert exc.value.code == 1


def test_main_skips_guard_when_disabled(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        daily_ml_select,
        "select_stocks",
        lambda target_date=None, top_n=None, profile_cfg=None: (
            seen.update({"top_n": top_n, "profile_cfg": profile_cfg}) or pd.DataFrame([{"ts_code": "000001", "name": "A"}])
        ),
    )
    monkeypatch.setattr(daily_ml_select, "load_default_profile_config", lambda *_args, **_kwargs: {"top_n": 13})
    monkeypatch.setattr(sys, "argv", ["daily_ml_select.py", "--disable-industry-coverage-gate"])

    daily_ml_select.main()
    assert seen["top_n"] is None
    assert int(seen["profile_cfg"]["top_n"]) == 13


def test_build_signal_pretrade_cfg_prefers_profile_defaults_when_env_missing(monkeypatch):
    monkeypatch.delenv("MFTS_RISK_MAX_ADV_PARTICIPATION", raising=False)
    monkeypatch.delenv("MFTS_RISK_MIN_PRICE", raising=False)
    monkeypatch.delenv("MFTS_RISK_MAX_INDUSTRY_WEIGHT", raising=False)

    cfg = daily_ml_select._build_signal_pretrade_cfg_from_env(
        {
            "risk_max_adv_participation": 0.04,
            "risk_max_industry_weight": 0.30,
            "min_price": 3.0,
        }
    )

    assert abs(float(cfg.max_adv_participation) - 0.04) < 1e-9
    assert abs(float(cfg.max_industry_weight) - 0.30) < 1e-9
    assert abs(float(cfg.min_price) - 3.0) < 1e-9


def test_capacity_optimizer_empty_does_not_use_unconstrained_fallback():
    pool = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ"],
            "portfolio_rank_score": [2.0, 1.5],
            "industry": ["bank", "tech"],
            "amount_capacity_conservative": [0.0, 0.0],
            "reserve_candidate": [0, 0],
        }
    )

    out, info = daily_ml_select._assign_target_weights(
        top_stocks=pool,
        ranking_col="portfolio_rank_score",
        total_target_pos=0.4,
        max_single_pos=0.1,
        primary_top_n=2,
        profile_cfg={
            "optimizer_mode": "capacity_crowding_aware",
            "target_score_col": "portfolio_rank_score",
            "target_max_adv_participation": 0.02,
            "target_capacity_amount_col": "amount_capacity_conservative",
            "target_capital_base": 1_000_000.0,
            "min_valid_positions": 1,
            "redistribute_clipped_weight": True,
        },
    )

    assert out.empty
    assert info["fallback"] is False
    assert info["optimizer_empty"] is True


def test_main_allows_empty_profile_output(monkeypatch):
    monkeypatch.setattr(daily_ml_select, "load_default_profile_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(daily_ml_select, "select_stocks", lambda **_kwargs: pd.DataFrame())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_ml_select.py",
            "--date",
            "20260410",
            "--output-profile",
            "empty_profile",
            "--disable-industry-coverage-gate",
        ],
    )

    daily_ml_select.main()


def test_resolve_profile_total_position_respects_non_regime_profiles():
    assert abs(
        daily_ml_select._resolve_profile_total_position(
            "60%-80%",
            {"use_regime_position": False, "fallback_total_position": 0.40},
        )
        - 0.40
    ) < 1e-9
    assert abs(
        daily_ml_select._resolve_profile_total_position(
            "60%-80%",
            {"use_regime_position": True, "fallback_total_position": 0.40},
        )
        - 0.70
    ) < 1e-9


def test_holiday_gap_guard_caps_pre_holiday_target_exposure():
    info = daily_ml_select._build_holiday_gap_guard_info(
        pd.Series(["20260401", "20260402", "20260403", "20260407"]),
        pd.Timestamp("2026-04-02"),
        {
            "holiday_gap_guard_enabled": True,
            "holiday_gap_min_calendar_days": 4,
            "holiday_gap_total_position_cap": 0.18,
            "holiday_gap_single_pos_cap": 0.012,
        },
        total_target=0.40,
        single_cap=0.026,
    )

    assert info["guard"] is True
    assert info["reason"] == "post_trade_gap"
    assert int(info["signal_trade_gap_days"]) == 1
    assert int(info["post_trade_gap_days"]) == 4
    assert float(info["adjusted_total_target"]) == pytest.approx(0.18)
    assert float(info["adjusted_single_cap"]) == pytest.approx(0.012)
    assert float(info["target_scale"]) == pytest.approx(0.45)


def test_holiday_gap_guard_stays_off_without_long_gap():
    info = daily_ml_select._build_holiday_gap_guard_info(
        pd.Series(["20260401", "20260402", "20260403", "20260407"]),
        pd.Timestamp("2026-04-01"),
        {
            "holiday_gap_guard_enabled": True,
            "holiday_gap_min_calendar_days": 4,
            "holiday_gap_total_position_cap": 0.18,
        },
        total_target=0.40,
        single_cap=0.026,
    )

    assert info["guard"] is False
    assert info["reason"] == "none"
    assert float(info["adjusted_total_target"]) == pytest.approx(0.40)
    assert float(info["target_scale"]) == pytest.approx(1.0)


def test_holiday_gap_guard_reason_override_caps_combined_gap():
    info = daily_ml_select._build_holiday_gap_guard_info(
        pd.Series(["20260101", "20260110", "20260120"]),
        pd.Timestamp("2026-01-01"),
        {
            "holiday_gap_guard_enabled": True,
            "holiday_gap_min_calendar_days": 4,
            "holiday_gap_total_position_cap": 0.12,
            "holiday_gap_single_pos_cap": 0.008,
            "holiday_gap_reason_overrides": {
                "signal_to_trade_gap+post_trade_gap": {
                    "total_position_cap": 0.20,
                    "single_pos_cap": 0.015,
                }
            },
        },
        total_target=0.40,
        single_cap=0.026,
    )

    assert info["guard"] is True
    assert info["reason"] == "signal_to_trade_gap+post_trade_gap"
    assert info["reason_override_applied"] is True
    assert int(info["signal_trade_gap_days"]) == 9
    assert int(info["post_trade_gap_days"]) == 10
    assert float(info["adjusted_total_target"]) == pytest.approx(0.20)
    assert float(info["adjusted_single_cap"]) == pytest.approx(0.015)
    assert float(info["target_scale"]) == pytest.approx(0.50)


def test_holiday_gap_guard_reason_override_does_not_affect_other_reasons():
    info = daily_ml_select._build_holiday_gap_guard_info(
        pd.Series(["20260401", "20260402", "20260403", "20260407"]),
        pd.Timestamp("2026-04-02"),
        {
            "holiday_gap_guard_enabled": True,
            "holiday_gap_min_calendar_days": 4,
            "holiday_gap_total_position_cap": 0.12,
            "holiday_gap_single_pos_cap": 0.008,
            "holiday_gap_reason_overrides": {
                "signal_to_trade_gap+post_trade_gap": {
                    "total_position_cap": 0.20,
                    "single_pos_cap": 0.015,
                }
            },
        },
        total_target=0.40,
        single_cap=0.026,
    )

    assert info["guard"] is True
    assert info["reason"] == "post_trade_gap"
    assert info["reason_override_applied"] is False
    assert float(info["adjusted_total_target"]) == pytest.approx(0.12)
    assert float(info["adjusted_single_cap"]) == pytest.approx(0.008)


def test_capacity_safe_reserve_pool_keeps_primary_and_reranks_reserves():
    pool = pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003", "000004"],
            "refactor_score": [0.99, 0.98, 0.97, 0.50],
            "amount_ma20": [500_000_000, 400_000_000, 5_000_000, 650_000_000],
            "amount_last": [500_000_000, 400_000_000, 5_000_000, 650_000_000],
            "amount_min5": [480_000_000, 380_000_000, 4_000_000, 640_000_000],
            "amount_min10": [470_000_000, 370_000_000, 4_500_000, 630_000_000],
            "adv_capacity_score": [0.90, 0.80, 0.05, 1.00],
            "liquidity_score": [0.90, 0.80, 0.05, 1.00],
            "industry_balance_score": [0.50, 0.50, 0.50, 0.50],
            "signal_quality": [0.90, 0.85, 0.80, 0.80],
            "pct_chg": [1.0, 1.0, 1.0, 1.0],
        }
    )

    out, score_col, info = daily_ml_select._prepare_capacity_safe_reserve_pool(
        pool,
        ranking_col="refactor_score",
        primary_top_n=2,
        profile_cfg={
            "capacity_safe_reserve_enabled": True,
            "capacity_safe_reserve_amount_col": "amount_capacity_conservative",
            "reserve_capacity_blend": 0.70,
            "reserve_rank_blend": 0.20,
            "reserve_liquidity_blend": 0.10,
        },
    )

    assert score_col == "portfolio_rank_score"
    assert info["enabled"] is True
    assert out.iloc[0]["ts_code"] == "000001"
    assert out.iloc[1]["ts_code"] == "000002"
    reserves = out[out["reserve_candidate"] == 1].reset_index(drop=True)
    assert reserves.iloc[0]["ts_code"] == "000004"
    assert reserves.iloc[1]["ts_code"] == "000003"
    assert float(out.iloc[1]["portfolio_rank_score"]) > float(reserves.iloc[0]["portfolio_rank_score"])


def test_capacity_safe_reserve_pool_can_promote_safe_reserve_to_primary_rank():
    pool = pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003", "000004"],
            "refactor_score": [0.99, 0.98, 0.97, 0.50],
            "amount_ma20": [100_000_000, 100_000_000, 100_000_000, 900_000_000],
            "amount_last": [100_000_000, 100_000_000, 100_000_000, 900_000_000],
            "amount_min5": [90_000_000, 90_000_000, 90_000_000, 880_000_000],
            "amount_min10": [95_000_000, 95_000_000, 95_000_000, 870_000_000],
            "adv_capacity_score": [0.10, 0.10, 0.10, 1.00],
            "liquidity_score": [0.10, 0.10, 0.10, 1.00],
            "industry_balance_score": [0.50, 0.50, 0.50, 0.50],
            "signal_quality": [0.70, 0.70, 0.70, 0.80],
            "pct_chg": [1.0, 1.0, 1.0, 1.0],
        }
    )

    out, score_col, info = daily_ml_select._prepare_capacity_safe_reserve_pool(
        pool,
        ranking_col="refactor_score",
        primary_top_n=2,
        profile_cfg={
            "capacity_safe_reserve_enabled": True,
            "capacity_safe_reserve_amount_col": "amount_capacity_conservative",
            "reserve_capacity_blend": 0.90,
            "reserve_rank_blend": 0.10,
            "reserve_liquidity_blend": 0.0,
            "capacity_safe_primary_rank_mode": "blend_full_pool",
            "capacity_safe_primary_rank_blend": 1.0,
        },
    )

    assert score_col == "portfolio_rank_score"
    assert info["primary_rank_mode"] == "blend_full_pool"
    assert info["primary_rank_blend"] == 1.0
    assert out.iloc[0]["ts_code"] == "000004"
    assert int(out.iloc[0]["reserve_candidate"]) == 1


def test_capacity_safe_reserve_pool_can_label_primary_by_target_score():
    pool = pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003", "000004"],
            "refactor_score": [0.99, 0.98, 0.40, 0.30],
            "liquidity_score": [0.10, 0.20, 0.90, 1.00],
            "exit_trap_safe_score": [0.10, 0.20, 0.90, 1.00],
            "amount_ma20": [100_000_000, 100_000_000, 900_000_000, 900_000_000],
            "amount_last": [100_000_000, 100_000_000, 900_000_000, 900_000_000],
            "amount_min5": [90_000_000, 90_000_000, 880_000_000, 880_000_000],
            "amount_min10": [95_000_000, 95_000_000, 870_000_000, 870_000_000],
            "adv_capacity_score": [0.10, 0.10, 1.00, 1.00],
            "industry_balance_score": [0.50, 0.50, 0.50, 0.50],
            "signal_quality": [0.70, 0.70, 0.80, 0.80],
            "pct_chg": [1.0, 1.0, 1.0, 1.0],
        }
    )

    out, score_col, info = daily_ml_select._prepare_capacity_safe_reserve_pool(
        pool,
        ranking_col="refactor_score",
        primary_top_n=2,
        profile_cfg={
            "capacity_safe_reserve_enabled": True,
            "target_score_blend": {"liquidity_score": 0.55, "exit_trap_safe_score": 0.45},
            "capacity_safe_primary_rank_mode": "target_score_topn",
        },
    )

    primary = out[out["reserve_candidate"].astype(int).eq(0)]["ts_code"].tolist()
    assert score_col == "portfolio_rank_score"
    assert info["primary_rank_mode"] == "target_score_topn"
    assert info["primary_label_score_col"] == "target_blend_score"
    assert primary == ["000004", "000003"]


def test_research_stage_snapshot_writes_stage_file(tmp_path):
    frames = []
    daily_ml_select._append_research_stage_snapshot(
        frames,
        pd.DataFrame(
            {
                "ts_code": ["000001", "000002"],
                "ml_score": [0.2, 0.8],
                "signal_quality": [0.4, 0.7],
                "close": [10.0, 12.0],
            }
        ),
        stage="raw_scored_post_indicator",
        target_date=pd.Timestamp("2026-01-05"),
        ranking_col="ml_score",
        extra={"stage_pool_n": 2},
    )

    dated, latest = daily_ml_select._write_research_stage_snapshots(
        frames,
        base_dir=tmp_path,
        output_profile="test_profile",
        date_str="20260105",
    )

    out = pd.read_csv(dated)
    assert latest
    assert out["research_stage"].iloc[0] == "raw_scored_post_indicator"
    assert out["代码"].tolist() == [2, 1]
    assert out["ML评分"].tolist() == [0.8, 0.2]


def test_assign_target_weights_honors_profile_target_score_col():
    picks = pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003"],
            "portfolio_rank_score": [3.0, 2.0, 1.0],
            "hybrid_score": [0.1, 0.9, 0.2],
            "amount_ma20": [1_000_000_000, 1_000_000_000, 1_000_000_000],
            "industry": ["A", "B", "C"],
        }
    )

    out, info = daily_ml_select._assign_target_weights(
        top_stocks=picks,
        ranking_col="portfolio_rank_score",
        total_target_pos=0.30,
        max_single_pos=0.20,
        profile_cfg={"target_score_col": "hybrid_score"},
        primary_top_n=3,
    )

    weights = out.set_index("ts_code")["target_weight"]
    assert info["target_score_col"] == "hybrid_score"
    assert weights["000002"] > weights["000001"]


def test_assign_target_weights_can_use_profile_target_score_blend():
    picks = pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003"],
            "portfolio_rank_score": [3.0, 2.0, 1.0],
            "liquidity_score": [0.1, 0.9, 0.2],
            "exit_trap_safe_score": [0.1, 0.8, 0.3],
            "amount_ma20": [1_000_000_000, 1_000_000_000, 1_000_000_000],
            "industry": ["A", "B", "C"],
        }
    )

    out, info = daily_ml_select._assign_target_weights(
        top_stocks=picks,
        ranking_col="portfolio_rank_score",
        total_target_pos=0.30,
        max_single_pos=0.20,
        profile_cfg={"target_score_blend": {"liquidity_score": 0.6, "exit_trap_safe_score": 0.4}},
        primary_top_n=3,
    )

    weights = out.set_index("ts_code")["target_weight"]
    assert info["target_score_col"] == "target_blend_score"
    assert info["target_score_blend"]["enabled"] is True
    assert weights["000002"] > weights["000001"]


def test_tradability_safe_ranking_penalizes_near_limit_hot_candidate():
    pool = pd.DataFrame(
        {
            "ts_code": ["000001", "000002"],
            "name": ["平安银行", "万科A"],
            "refactor_score": [0.99, 0.60],
            "close_1": [10.0, 10.0],
            "close": [10.88, 10.20],
            "high": [10.95, 10.30],
            "pct_chg": [8.8, 2.0],
            "vol_ratio": [5.0, 1.0],
            "amount_ma20": [100_000_000, 600_000_000],
            "amount_last": [100_000_000, 600_000_000],
            "amount_min5": [90_000_000, 580_000_000],
            "amount_min10": [95_000_000, 590_000_000],
        }
    )

    out, score_col, info = daily_ml_select._apply_tradability_safe_ranking(
        pool,
        ranking_col="refactor_score",
        profile_cfg={
            "tradability_safe_ranking_enabled": True,
            "tradability_rank_blend": 0.80,
            "tradability_limit_headroom_pct": 3.5,
            "tradability_hot_pct_of_limit": 0.70,
        },
    )

    assert score_col == "tradability_adjusted_score"
    assert info["ranking_enabled"] is True
    risky = out.set_index("ts_code").loc["000001"]
    safer = out.set_index("ts_code").loc["000002"]
    assert float(risky["tradability_safe_score"]) < float(safer["tradability_safe_score"])
    assert float(safer["tradability_adjusted_score"]) > float(risky["tradability_adjusted_score"])


def test_exit_trap_score_penalizes_near_limit_down_candidate():
    pool = pd.DataFrame(
        {
            "ts_code": ["000001", "000002"],
            "name": ["平安银行", "万科A"],
            "refactor_score": [0.99, 0.60],
            "close_1": [10.0, 10.0],
            "close": [9.12, 10.10],
            "low": [9.02, 10.00],
            "high": [9.30, 10.20],
            "pct_chg": [-8.8, 1.0],
            "vol_ratio": [0.20, 1.0],
            "amount_ma20": [100_000_000, 600_000_000],
            "amount_last": [100_000_000, 600_000_000],
            "amount_min5": [90_000_000, 580_000_000],
            "amount_min10": [95_000_000, 590_000_000],
        }
    )

    out, score_col, info = daily_ml_select._apply_tradability_safe_ranking(
        pool,
        ranking_col="refactor_score",
        profile_cfg={
            "tradability_safe_ranking_enabled": True,
            "tradability_rank_blend": 0.80,
            "exit_trap_ranking_enabled": True,
            "exit_trap_rank_blend": 0.80,
            "exit_trap_downside_headroom_pct": 3.5,
            "exit_trap_hot_pct_of_limit": 0.55,
            "exit_trap_low_touch_buffer": 1.015,
        },
    )

    risky = out.set_index("ts_code").loc["000001"]
    safer = out.set_index("ts_code").loc["000002"]
    assert score_col == "tradability_adjusted_score"
    assert info["exit_trap_rank_blend"] == 0.80
    assert float(risky["exit_trap_risk_score"]) > float(safer["exit_trap_risk_score"])
    assert float(risky["exit_trap_downside_headroom_pct"]) < float(safer["exit_trap_downside_headroom_pct"])
    assert float(safer["tradability_adjusted_score"]) > float(risky["tradability_adjusted_score"])


def test_capacity_safe_reserve_pool_uses_tradability_for_reserve_order():
    pool = pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003", "000004"],
            "refactor_score": [0.99, 0.98, 0.97, 0.50],
            "amount_ma20": [500_000_000, 400_000_000, 500_000_000, 500_000_000],
            "amount_last": [500_000_000, 400_000_000, 500_000_000, 500_000_000],
            "amount_min5": [480_000_000, 380_000_000, 500_000_000, 500_000_000],
            "amount_min10": [470_000_000, 370_000_000, 500_000_000, 500_000_000],
            "adv_capacity_score": [0.90, 0.80, 0.80, 0.80],
            "liquidity_score": [0.90, 0.80, 0.80, 0.80],
            "industry_balance_score": [0.50, 0.50, 0.50, 0.50],
            "signal_quality": [0.90, 0.85, 0.80, 0.80],
            "pct_chg": [1.0, 1.0, 1.0, 1.0],
            "tradability_safe_score": [0.9, 0.9, 0.05, 1.00],
            "exit_trap_safe_score": [0.9, 0.9, 1.00, 0.05],
        }
    )

    out, _, info = daily_ml_select._prepare_capacity_safe_reserve_pool(
        pool,
        ranking_col="refactor_score",
        primary_top_n=2,
        profile_cfg={
            "capacity_safe_reserve_enabled": True,
            "capacity_safe_reserve_amount_col": "amount_capacity_conservative",
            "reserve_capacity_blend": 0.0,
            "reserve_rank_blend": 0.0,
            "reserve_liquidity_blend": 0.0,
            "reserve_industry_blend": 0.0,
            "reserve_calm_blend": 0.0,
            "reserve_tradability_blend": 1.0,
            "reserve_exit_trap_blend": 0.0,
        },
    )

    reserves = out[out["reserve_candidate"] == 1].reset_index(drop=True)
    assert info["reserve_tradability_blend"] == 1.0
    assert reserves.iloc[0]["ts_code"] == "000004"
    assert reserves.iloc[1]["ts_code"] == "000003"


def test_capacity_safe_reserve_pool_can_use_exit_trap_for_reserve_order():
    pool = pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003", "000004"],
            "refactor_score": [0.99, 0.98, 0.97, 0.50],
            "amount_ma20": [500_000_000, 400_000_000, 500_000_000, 500_000_000],
            "amount_last": [500_000_000, 400_000_000, 500_000_000, 500_000_000],
            "amount_min5": [480_000_000, 380_000_000, 500_000_000, 500_000_000],
            "amount_min10": [470_000_000, 370_000_000, 500_000_000, 500_000_000],
            "adv_capacity_score": [0.90, 0.80, 0.80, 0.80],
            "liquidity_score": [0.90, 0.80, 0.80, 0.80],
            "industry_balance_score": [0.50, 0.50, 0.50, 0.50],
            "signal_quality": [0.90, 0.85, 0.80, 0.80],
            "pct_chg": [1.0, 1.0, 1.0, 1.0],
            "tradability_safe_score": [0.9, 0.9, 0.9, 0.9],
            "exit_trap_safe_score": [0.9, 0.9, 0.05, 1.00],
        }
    )

    out, _, info = daily_ml_select._prepare_capacity_safe_reserve_pool(
        pool,
        ranking_col="refactor_score",
        primary_top_n=2,
        profile_cfg={
            "capacity_safe_reserve_enabled": True,
            "capacity_safe_reserve_amount_col": "amount_capacity_conservative",
            "reserve_capacity_blend": 0.0,
            "reserve_rank_blend": 0.0,
            "reserve_liquidity_blend": 0.0,
            "reserve_industry_blend": 0.0,
            "reserve_calm_blend": 0.0,
            "reserve_tradability_blend": 0.0,
            "reserve_exit_trap_blend": 1.0,
        },
    )

    reserves = out[out["reserve_candidate"] == 1].reset_index(drop=True)
    assert info["reserve_exit_trap_blend"] == 1.0
    assert reserves.iloc[0]["ts_code"] == "000004"
    assert reserves.iloc[1]["ts_code"] == "000003"
