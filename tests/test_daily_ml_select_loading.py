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


def test_load_latest_data_respects_columns_and_date_window(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    parquet_path = data_dir / "daily_all_5y.parquet"
    pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260407", "open": 10.0, "close": 10.1, "vol": 100.0, "amount": 101000.0, "pct_chg": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260408", "open": 10.2, "close": 10.3, "vol": 110.0, "amount": 113300.0, "pct_chg": 2.0},
            {"ts_code": "000001.SZ", "trade_date": "20260409", "open": 10.4, "close": 10.5, "vol": 120.0, "amount": 126000.0, "pct_chg": 1.5},
        ]
    ).to_parquet(parquet_path, index=False)

    monkeypatch.setattr(daily_ml_select, "DATA_DIR", str(data_dir))

    out = daily_ml_select.load_latest_data(
        columns=["open", "close"],
        start_date=pd.Timestamp("2026-04-08"),
        end_date=pd.Timestamp("2026-04-08"),
    )

    assert set(out.columns) == {"ts_code", "trade_date", "open", "close"}
    assert out["trade_date"].dt.strftime("%Y%m%d").tolist() == ["20260408"]
    assert out["ts_code"].tolist() == ["000001"]


def test_main_blocks_when_metadata_gate_fails(monkeypatch):
    monkeypatch.setattr(
        daily_ml_select,
        "load_metadata_health",
        lambda _data_dir: {"ok": True, "coverage_pct": 10.0, "age_days": 0.2, "file": "mock.csv"},
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
    monkeypatch.setattr(sys, "argv", ["daily_ml_select.py"])

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
