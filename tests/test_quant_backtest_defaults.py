# -*- coding: utf-8 -*-
"""量化回测默认参数与 CLI 覆盖行为测试。"""

from __future__ import annotations

import json
import sys

import pandas as pd

import scripts.quant_portfolio_backtest as qpb


def _stub_metrics() -> dict[str, float]:
    return {
        "trade_count": 0,
        "total_return_pct": 0.0,
        "annual_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe": 0.0,
        "win_rate_pct": 0.0,
        "avg_trade_return_pct": 0.0,
        "benchmark_total_return_pct": 0.0,
        "benchmark_annual_return_pct": 0.0,
        "excess_total_return_pct": 0.0,
        "excess_annual_return_pct": 0.0,
        "beat_rate_pct": 0.0,
        "info_ratio": 0.0,
        "avg_exposure_pct": 0.0,
        "annual_turnover_pct": 0.0,
        "trades_per_year": 0.0,
    }


def _allow_metadata_gate(monkeypatch):
    monkeypatch.setattr(
        qpb,
        "load_metadata_health",
        lambda _data_dir: {"ok": True, "coverage_pct": 100.0, "age_days": 0.0, "file": "mock.csv"},
    )
    monkeypatch.setattr(
        qpb,
        "evaluate_metadata_guard",
        lambda info, **_kwargs: {
            **info,
            "passed": True,
            "reason": "ok",
            "min_coverage_pct": 80.0,
            "max_age_days": 3.0,
        },
    )


def test_backtest_config_defaults_follow_profile():
    cfg = qpb.BacktestConfig(start="2025-01-01", end="2025-01-31")
    assert cfg.top_n == int(qpb.DEFAULTS["top_n"])
    assert cfg.holding_days == int(qpb.DEFAULTS["holding_days"])
    assert cfg.max_single_pos == float(qpb.DEFAULTS["max_single_pos"])
    assert cfg.use_regime_position == bool(qpb.DEFAULTS["use_regime_position"])
    assert cfg.min_signal_quality == float(qpb.DEFAULTS["min_signal_quality"])
    assert cfg.ml_quality_blend == float(qpb.DEFAULTS["ml_quality_blend"])
    assert cfg.stability_blend == float(qpb.DEFAULTS["stability_blend"])
    assert cfg.min_refactor_score == float(qpb.DEFAULTS["min_refactor_score"])


def test_load_default_backtest_defaults_reads_quality_profile(tmp_path, monkeypatch):
    profile_file = tmp_path / "quant_live_profiles.json"
    profile_file.write_text(
        json.dumps(
            {
                "default_profile": "quality",
                "profiles": {
                    "quality": {
                        "top_n": 12,
                        "holding_days": 8,
                        "max_single_pos": 0.04,
                        "use_regime_position": True,
                        "min_signal_quality": 0.42,
                        "ml_quality_blend": 0.78,
                        "stability_blend": 0.34,
                        "min_refactor_score": 0.53,
                        "risk_window": 8,
                        "risk_cut_factor": 0.72,
                        "min_price": 3.0,
                        "min_amount_ma20": 100000000.0,
                        "liquidity_blend": 0.16,
                        "adv_penalty_blend": 0.14,
                        "industry_crowding_blend": 0.18,
                        "optimizer_mode": "capacity_crowding_aware",
                        "target_capital_base": 1000000.0,
                        "target_max_industry_weight": 0.30,
                        "target_max_adv_participation": 0.04,
                        "impact_model": "sqrt",
                        "impact_participation_bps": 6.0,
                        "promotion_loss_clamp_enabled": False,
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(qpb, "PROFILE_FILE", str(profile_file))

    defaults = qpb._load_default_backtest_defaults()

    assert defaults["top_n"] == 12
    assert defaults["holding_days"] == 8
    assert defaults["use_regime_position"] is True
    assert defaults["min_signal_quality"] == 0.42
    assert defaults["ml_quality_blend"] == 0.78
    assert defaults["stability_blend"] == 0.34
    assert defaults["min_refactor_score"] == 0.53
    assert defaults["risk_window"] == 8
    assert defaults["risk_cut_factor"] == 0.72
    assert defaults["min_price"] == 3.0
    assert defaults["min_amount_ma20"] == 100000000.0
    assert defaults["liquidity_blend"] == 0.16
    assert defaults["adv_penalty_blend"] == 0.14
    assert defaults["industry_crowding_blend"] == 0.18
    assert defaults["optimizer_mode"] == "capacity_crowding_aware"
    assert defaults["target_capital_base"] == 1000000.0
    assert defaults["target_max_industry_weight"] == 0.30
    assert defaults["target_max_adv_participation"] == 0.04
    assert defaults["impact_model"] == "sqrt"
    assert defaults["impact_participation_bps"] == 6.0
    assert defaults["promotion_loss_clamp_enabled"] is False


def test_calc_metrics_keeps_raw_unclamped_metrics_visible():
    trades_df = pd.DataFrame(
        {
            "entry_date": ["2025-01-01", "2025-01-10"],
            "exit_date": ["2025-01-09", "2025-01-20"],
            "portfolio_ret": [0.02, -0.03],
            "portfolio_ret_raw": [0.02, -0.10],
            "loss_clamp_used": [False, True],
            "benchmark_ret_raw": [0.0, 0.0],
            "benchmark_ret": [0.0, 0.0],
            "total_exposure": [0.6, 0.6],
            "equity": [1.02, 1.02 * 0.97],
        }
    )

    metrics = qpb._calc_metrics(trades_df, holding_days=8)

    assert metrics["loss_clamp_used_count"] == 1
    assert metrics["raw_total_return_pct"] < metrics["total_return_pct"]
    assert metrics["raw_max_drawdown_pct"] < metrics["max_drawdown_pct"]
    assert metrics["portfolio_ret_raw_min_pct"] == -10.0
    assert metrics["portfolio_ret_min_pct"] == -3.0


def test_compute_risk_switch_factor_scales_smoothly():
    cfg = qpb.BacktestConfig(
        start="2025-01-01",
        end="2025-01-31",
        risk_window=4,
        risk_cut_win_rate=0.50,
        risk_cut_avg_ret=-0.002,
        risk_cut_factor=0.75,
    )
    trades = [
        {"portfolio_ret": 0.010},
        {"portfolio_ret": -0.004},
        {"portfolio_ret": -0.003},
        {"portfolio_ret": -0.001},
    ]

    risk_factor = qpb._compute_risk_switch_factor(cfg, trades)

    assert 0.75 < risk_factor < 1.0


def test_main_uses_profile_default_regime(monkeypatch):
    captured = {}
    _allow_metadata_gate(monkeypatch)

    def fake_backtest(cfg):
        captured["cfg"] = cfg
        return pd.DataFrame(), _stub_metrics()

    monkeypatch.setattr(qpb, "backtest_portfolio", fake_backtest)
    monkeypatch.setattr(qpb, "_print_summary", lambda metrics, cfg: None)
    monkeypatch.setattr(qpb, "_save_outputs", lambda trades_df, metrics, cfg: ("detail.csv", "summary.csv", "summary.json"))
    monkeypatch.setattr(sys, "argv", ["quant_portfolio_backtest.py"])

    rc = qpb.main()
    assert rc == 0
    assert captured["cfg"].use_regime_position == bool(qpb.DEFAULTS["use_regime_position"])


def test_main_regime_flag_can_override_default(monkeypatch):
    captured = {}
    _allow_metadata_gate(monkeypatch)

    def fake_backtest(cfg):
        captured["cfg"] = cfg
        return pd.DataFrame(), _stub_metrics()

    monkeypatch.setattr(qpb, "backtest_portfolio", fake_backtest)
    monkeypatch.setattr(qpb, "_print_summary", lambda metrics, cfg: None)
    monkeypatch.setattr(qpb, "_save_outputs", lambda trades_df, metrics, cfg: ("detail.csv", "summary.csv", "summary.json"))

    monkeypatch.setattr(sys, "argv", ["quant_portfolio_backtest.py", "--use-regime-position"])
    rc = qpb.main()
    assert rc == 0
    assert captured["cfg"].use_regime_position is True

    monkeypatch.setattr(sys, "argv", ["quant_portfolio_backtest.py", "--no-regime-position"])
    rc = qpb.main()
    assert rc == 0
    assert captured["cfg"].use_regime_position is False


def test_main_feature_refactor_flags_pass_to_config(monkeypatch):
    captured = {}
    _allow_metadata_gate(monkeypatch)

    def fake_backtest(cfg):
        captured["cfg"] = cfg
        return pd.DataFrame(), _stub_metrics()

    monkeypatch.setattr(qpb, "backtest_portfolio", fake_backtest)
    monkeypatch.setattr(qpb, "_print_summary", lambda metrics, cfg: None)
    monkeypatch.setattr(qpb, "_save_outputs", lambda trades_df, metrics, cfg: ("detail.csv", "summary.csv", "summary.json"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_portfolio_backtest.py",
            "--disable-feature-refactor",
            "--stability-blend",
            "0.35",
            "--disable-feature-refactor-gate",
            "--min-refactor-score",
            "0.58",
        ],
    )

    rc = qpb.main()
    assert rc == 0
    cfg = captured["cfg"]
    assert cfg.enable_feature_refactor is False
    assert cfg.stability_blend == 0.35
    assert cfg.enable_feature_refactor_gate is False
    assert cfg.min_refactor_score == 0.58


def test_main_liquidity_flags_pass_to_config(monkeypatch):
    captured = {}
    _allow_metadata_gate(monkeypatch)

    def fake_backtest(cfg):
        captured["cfg"] = cfg
        return pd.DataFrame(), _stub_metrics()

    monkeypatch.setattr(qpb, "backtest_portfolio", fake_backtest)
    monkeypatch.setattr(qpb, "_print_summary", lambda metrics, cfg: None)
    monkeypatch.setattr(qpb, "_save_outputs", lambda trades_df, metrics, cfg: ("detail.csv", "summary.csv", "summary.json"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_portfolio_backtest.py",
            "--min-price",
            "3.0",
            "--min-amount-ma20",
            "100000000",
            "--liquidity-blend",
            "0.16",
            "--adv-penalty-blend",
            "0.14",
            "--industry-crowding-blend",
            "0.18",
        ],
    )

    rc = qpb.main()
    assert rc == 0
    cfg = captured["cfg"]
    assert cfg.min_price == 3.0
    assert cfg.min_amount_ma20 == 100000000.0
    assert cfg.liquidity_blend == 0.16
    assert cfg.adv_penalty_blend == 0.14
    assert cfg.industry_crowding_blend == 0.18


def test_diversification_caps_missing_industry_as_unknown_bucket():
    cfg = qpb.BacktestConfig(
        start="2025-01-01",
        end="2025-01-31",
        top_n=2,
        enable_diversification=True,
        max_industry_positions=1,
        max_pair_corr=0.999,
    )
    picks = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "名称": ["A", "B", "C"],
            "hybrid_score": [0.90, 0.80, 0.70],
            "ml": [0.90, 0.80, 0.70],
        }
    )

    out = qpb._apply_diversification_filters(
        picks=picks,
        market_df=pd.DataFrame(columns=["trade_date", "code", "open"]),
        trading_days=[],
        entry_idx=0,
        cfg=cfg,
        industry_map={"000003": "医药"},
        max_pair_corr=0.999,
    )

    assert list(out["代码"].astype(str)) == ["000001", "000003"]
    assert list(out["industry"].astype(str)) == [qpb.UNKNOWN_INDUSTRY_LABEL, "医药"]
    assert list(pd.to_numeric(out["industry_missing"], errors="coerce").astype(int)) == [1, 0]


def test_main_blocks_when_metadata_gate_fails(monkeypatch):
    monkeypatch.setattr(
        qpb,
        "load_metadata_health",
        lambda _data_dir: {"ok": True, "coverage_pct": 10.0, "age_days": 0.2, "file": "mock.csv"},
    )
    monkeypatch.setattr(
        qpb,
        "evaluate_metadata_guard",
        lambda info, **_kwargs: {
            **info,
            "passed": False,
            "reason": "industry_coverage_low",
            "min_coverage_pct": 80.0,
            "max_age_days": 3.0,
        },
    )
    called = {"backtest": False}

    def fake_backtest(_cfg):
        called["backtest"] = True
        return pd.DataFrame(), _stub_metrics()

    monkeypatch.setattr(qpb, "backtest_portfolio", fake_backtest)
    monkeypatch.setattr(sys, "argv", ["quant_portfolio_backtest.py"])

    rc = qpb.main()
    assert rc == 1
    assert called["backtest"] is False


def test_build_backtest_manifest_writes_platform_run(tmp_path, monkeypatch):
    monkeypatch.setattr(qpb, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(qpb, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(qpb, "PARQUET_FILE", str(tmp_path / "data" / "daily_all_5y.parquet"))
    monkeypatch.setattr(qpb, "PROFILE_FILE", str(tmp_path / "config" / "quant_live_profiles.json"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "daily_all_5y.parquet").write_text("stub", encoding="utf-8")
    (tmp_path / "data" / "stock_info.csv").write_text("ts_code,industry\n000001.SZ,银行\n", encoding="utf-8")
    (tmp_path / "config" / "quant_live_profiles.json").write_text("{}", encoding="utf-8")

    cfg = qpb.BacktestConfig(start="2025-01-01", end="2025-01-31")
    manifest_path = qpb._build_backtest_manifest(cfg, ["quant_portfolio_backtest.py"])

    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["run_type"] == "quant_portfolio_backtest"
    assert payload["params"]["top_n"] == cfg.top_n
    assert "daily_data" in payload["versions"]
