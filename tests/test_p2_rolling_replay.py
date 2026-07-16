# -*- coding: utf-8 -*-
"""P2 滚动回放脚本单测。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

import scripts.quant_p2_rolling_replay as replay


def test_parse_windows_dedup_and_fallback():
    assert replay._parse_windows("120,60,90,60") == [60, 90, 120]
    assert replay._parse_windows("bad,0,-1") == [60, 90, 120]


def test_parse_style_grids():
    assert replay._parse_float_grid("0.9,1.2,0.9,bad", [0.8]) == [0.9, 1.2]
    assert replay._parse_float_grid("-1,bad", [0.8, 1.0]) == [0.8, 1.0]
    assert replay._parse_int_grid("20,60,20,bad", [30], min_value=5) == [20, 60]
    assert replay._parse_int_grid("0,-1,bad", [30], min_value=5) == [30]


def test_single_profile_slug():
    assert replay._single_profile_slug(["quality_regime_candidate_v2"]) == "quality_regime_candidate_v2"
    assert replay._single_profile_slug(["a", "b"]) == ""


def test_filter_signal_dates_excludes_endpoint_without_next_trade_day():
    out, meta = replay._filter_signal_dates_with_next_trade_day(
        ["20260410", "20260413", "20260414"],
        ["20260410", "20260413", "20260414"],
    )
    assert out == ["20260410", "20260413"]
    assert meta["next_trade_day_filter_applied"] is True
    assert meta["market_last_trade_date"] == "20260414"
    assert meta["excluded_no_next_trade_dates"] == ["20260414"]


def test_replay_market_calendar_uses_ods_gateway(monkeypatch):
    class FakeGateway:
        def available_trade_dates(self):
            return ["2026-04-10", "2026-04-13", "2026-04-14"]

    monkeypatch.setattr(replay, "AShareMarketDataGateway", lambda: FakeGateway(), raising=False)

    assert replay._load_market_trade_dates() == ["20260410", "20260413", "20260414"]


def test_filter_signal_dates_excludes_stale_daily_without_market_bar():
    out, meta = replay._filter_signal_dates_with_next_trade_day(
        ["20260409", "20260410", "20260413"],
        ["20260410", "20260413", "20260414"],
    )
    assert out == ["20260410", "20260413"]
    assert meta["excluded_missing_market_dates"] == ["20260409"]


def test_filter_signal_dates_keeps_old_behavior_without_market_calendar():
    out, meta = replay._filter_signal_dates_with_next_trade_day(["20260414"], [])
    assert out == ["20260414"]
    assert meta["next_trade_day_filter_applied"] is False


def test_window_calendar_coverage_reports_shortfall():
    coverage = replay._window_calendar_coverage(["20260401", "20260402"], requested_window=5, available_dates=2)
    assert coverage["requested_window_days"] == 5.0
    assert coverage["profile_signal_days_available"] == 2.0
    assert coverage["signal_calendar_shortfall_days"] == 3.0
    assert coverage["signal_calendar_coverage_pct"] == 40.0


def test_resolve_profile_calendar_aligns_to_shared_reference():
    dates, source, meta = replay._resolve_profile_calendar_dates(
        shared_signal_dates=["20260401", "20260402", "20260403"],
        profile_signal_dates=["20260402", "20260403", "20260404"],
        has_profile_calendar=True,
        align_to_shared=True,
    )

    assert dates == ["20260402", "20260403"]
    assert source == "profile_aligned_shared"
    assert meta["profile_calendar_aligned_to_shared"] is True
    assert meta["profile_calendar_missing_shared_dates"] == ["20260401"]
    assert meta["profile_calendar_extra_profile_dates"] == ["20260404"]


def test_resolve_profile_calendar_keeps_profile_dates_when_not_aligned():
    dates, source, meta = replay._resolve_profile_calendar_dates(
        shared_signal_dates=["20260401"],
        profile_signal_dates=["20260402"],
        has_profile_calendar=True,
        align_to_shared=False,
    )

    assert dates == ["20260402"]
    assert source == "profile"
    assert meta["profile_calendar_aligned_to_shared"] is False
    assert meta["profile_calendar_extra_profile_dates"] == ["20260402"]


def test_max_drawdown_pct():
    nav = [100.0, 110.0, 105.0, 90.0, 95.0]
    mdd = replay._max_drawdown_pct(nav)
    assert round(mdd, 2) == -18.18


def test_summarize_ledger_basic_metrics(tmp_path: Path):
    ledger = pd.DataFrame(
        {
            "nav_pre": [1_000_000.0, 1_010_000.0],
            "nav_post": [1_010_000.0, 1_005_000.0],
            "turnover": [300_000.0, 200_000.0],
            "filled_orders": [8, 6],
            "partial_orders": [1, 1],
            "blocked_orders": [1, 2],
            "rejected_orders": [0, 1],
            "execution_state": ["empty_after_universe_filter", "normal"],
                "risk_input_count": [10, 8],
                "risk_blocked_count": [2, 1],
                "risk_style_limits_hit": [3, 1],
                "risk_style_size_limits_hit": [2, 0],
                "risk_style_beta_limits_hit": [1, 1],
                "risk_style_momentum_limits_hit": [1, 1],
                "risk_style_vol_limits_hit": [0, 1],
                "risk_adv_limits_hit": [5, 7],
                "risk_entry_not_tradable_hit": [2, 0],
                "target_weight_source": ["external_target_weight", "external_target_weight"],
                "target_weight_checksum": ["abc", "def"],
                "holiday_gap_guard": [1, 0],
                "holiday_gap_signal_trade_gap_days": [1, 4],
                "holiday_gap_post_trade_gap_days": [4, 1],
                "holiday_gap_target_scale": [0.45, 1.0],
                "upstream_target_weight_present": [1, 1],
                "upstream_target_weight_sum": [0.18, 0.40],
                "upstream_target_weight_positive_count": [15, 18],
                "upstream_target_weight_max": [0.012, 0.026],
                "entry_not_tradable_orders": [1, 3],
                "exit_not_tradable_orders": [0, 2],
                "broker_entry_not_tradable_orders": [1, 3],
                "broker_exit_not_tradable_orders": [0, 2],
                "blocked_target_weight": [0.03, 0.07],
            "empty_signal": [1, 0],
            "empty_signal_raw_rows": [10, 0],
            "empty_signal_post_filter_rows": [0, 0],
            "empty_signal_filtered_bj9_rows": [10, 0],
            "empty_signal_filtered_st_rows": [0, 0],
            "executable_pool_halt": [1, 0],
            "executable_pool_input_count": [10, 0],
            "executable_pool_blocked_count": [8, 0],
            "entry_not_tradable_target_weight": [0.03, 0.05],
            "exit_not_tradable_target_weight": [0.0, 0.02],
            "blocked_sell_current_weight": [0.04, 0.08],
            "blocked_sell_notional": [40_000.0, 80_000.0],
            "blocked_sell_orders": [1, 2],
            "blocked_sell_entry_risk_score_weighted_mean": [0.70, 0.40],
            "blocked_sell_entry_tradability_safe_score_weighted_mean": [0.30, 0.60],
            "blocked_sell_entry_limit_headroom_min": [0.80, 1.20],
            "blocked_sell_high_entry_risk_orders": [1, 0],
            "blocked_sell_low_entry_safety_orders": [1, 0],
            "blocked_sell_reserve_entry_orders": [1, 2],
            "blocked_exit_buy_freeze": [1, 0],
            "blocked_exit_freeze_sell_weight": [0.04, 0.0],
            "blocked_exit_freeze_sell_notional": [40_000.0, 0.0],
            "blocked_exit_freeze_orders": [3, 0],
            "blocked_exit_freeze_target_weight": [0.12, 0.0],
            "active_blocked_sell_state_count": [0, 1],
            "active_blocked_sell_state_weight": [0.0, 0.08],
            "active_blocked_sell_state_notional": [0.0, 80_000.0],
            "active_blocked_sell_state_max_consecutive_days": [0, 2],
            "blocked_state_count": [4, 2],
            "blocked_state_buy_count": [3, 1],
            "blocked_state_sell_count": [1, 1],
            "blocked_state_max_consecutive_days": [1, 2],
            "blocked_state_sell_notional": [40_000.0, 90_000.0],
            "blocked_state_buy_target_weight": [0.12, 0.04],
            "blocked_state_sell_target_weight": [0.04, 0.08],
            "blocked_state_resolved_count": [0, 2],
        }
    )
    ledger_file = tmp_path / "ledger.csv"
    ledger.to_csv(ledger_file, index=False, encoding="utf-8-sig")

    s = replay._summarize_ledger(ledger_file)
    assert s["executed_days"] == 2
    assert round(float(s["nav_return_pct"]), 2) == 0.5
    assert float(s["turnover_sum"]) == 500_000.0
    assert round(float(s["exec_block_rate_pct"]), 2) == 20.0
    assert round(float(s["risk_block_rate_pct"]), 2) == 16.67
    assert float(s["style_hit_total"]) == 4.0
    assert round(float(s["style_hit_rate_pct"]), 2) == 22.22
    assert float(s["target_weight_source_external_rate_pct"]) == 100.0
    assert float(s["target_weight_checksum_coverage_pct"]) == 100.0
    assert float(s["upstream_target_weight_present_days"]) == 2.0
    assert float(s["upstream_target_weight_present_rate_pct"]) == 100.0
    assert round(float(s["upstream_target_weight_sum_mean"]), 2) == 0.29
    assert round(float(s["upstream_target_weight_positive_count_mean"]), 2) == 16.50
    assert round(float(s["upstream_target_weight_max_mean"]), 3) == 0.019
    assert round(float(s["upstream_target_weight_gap_abs_max"]), 2) == 0.40
    assert round(float(s["upstream_target_weight_overrun_max"]), 2) == 0.0
    assert round(float(s["upstream_target_weight_underuse_max"]), 2) == 0.40
    assert float(s["holiday_gap_guard_days"]) == 1.0
    assert round(float(s["holiday_gap_guard_rate_pct"]), 2) == 50.0
    assert float(s["holiday_gap_signal_trade_gap_days_max"]) == 4.0
    assert float(s["holiday_gap_post_trade_gap_days_max"]) == 4.0
    assert round(float(s["holiday_gap_target_scale_min"]), 2) == 0.45
    assert float(s["entry_not_tradable_orders"]) == 4.0
    assert float(s["exit_not_tradable_orders"]) == 2.0
    assert float(s["broker_entry_not_tradable_orders"]) == 4.0
    assert float(s["broker_exit_not_tradable_orders"]) == 2.0
    assert float(s["broker_tradability_block_orders"]) == 6.0
    assert round(float(s["blocked_target_weight_sum"]), 2) == 0.10
    assert float(s["max_daily_tradability_blocked_orders"]) == 5.0
    assert round(float(s["blocked_sell_current_weight_sum"]), 2) == 0.12
    assert round(float(s["blocked_sell_current_weight_max"]), 2) == 0.08
    assert float(s["blocked_sell_notional_sum"]) == 120_000.0
    assert float(s["blocked_sell_orders_sum"]) == 3.0
    assert round(float(s["blocked_sell_entry_risk_score_weighted_mean_max"]), 2) == 0.70
    assert round(float(s["blocked_sell_entry_tradability_safe_score_weighted_mean_min"]), 2) == 0.30
    assert round(float(s["blocked_sell_entry_limit_headroom_min"]), 2) == 0.80
    assert float(s["blocked_sell_high_entry_risk_orders_sum"]) == 1.0
    assert float(s["blocked_sell_low_entry_safety_orders_sum"]) == 1.0
    assert float(s["blocked_sell_reserve_entry_orders_sum"]) == 3.0
    assert float(s["blocked_exit_buy_freeze_days"]) == 1.0
    assert round(float(s["blocked_exit_freeze_sell_weight_max"]), 2) == 0.04
    assert float(s["blocked_exit_freeze_sell_notional_max"]) == 40_000.0
    assert float(s["blocked_exit_freeze_orders_sum"]) == 3.0
    assert round(float(s["blocked_exit_freeze_target_weight_sum"]), 2) == 0.12
    assert float(s["active_blocked_sell_state_count_max"]) == 1.0
    assert round(float(s["active_blocked_sell_state_weight_max"]), 2) == 0.08
    assert float(s["active_blocked_sell_state_notional_max"]) == 80_000.0
    assert float(s["active_blocked_sell_state_max_consecutive_days_max"]) == 2.0
    assert float(s["blocked_state_count_max"]) == 4.0
    assert float(s["blocked_state_max_consecutive_days_max"]) == 2.0
    assert float(s["blocked_state_sell_notional_max"]) == 90_000.0
    assert round(float(s["blocked_state_buy_target_weight_sum"]), 2) == 0.16
    assert round(float(s["blocked_state_sell_target_weight_sum"]), 2) == 0.12
    assert float(s["blocked_state_resolved_count_sum"]) == 2.0
    assert float(s["empty_signal_days"]) == 1.0
    assert round(float(s["empty_signal_rate_pct"]), 2) == 50.0
    assert float(s["empty_after_universe_filter_days"]) == 1.0
    assert float(s["empty_signal_filtered_bj9_rows_sum"]) == 10.0
    assert float(s["executable_pool_halt_days"]) == 1.0
    assert round(float(s["executable_pool_halt_rate_pct"]), 2) == 50.0
    assert float(s["executable_pool_halt_input_sum"]) == 10.0
    assert float(s["executable_pool_halt_blocked_sum"]) == 8.0
    assert float(s["executable_pool_halt_adv_hit_sum"]) == 5.0
    assert float(s["executable_pool_halt_entry_not_tradable_hit_sum"]) == 2.0
    assert float(s["executable_pool_halt_style_hit_sum"]) == 3.0


def test_main_passes_metadata_gate_overrides(monkeypatch, tmp_path: Path):
    signal_dir = tmp_path / "daily"
    signal_dir.mkdir(parents=True, exist_ok=True)
    (signal_dir / "daily_20260401.csv").write_text("代码,名称\n000001,平安银行\n", encoding="utf-8-sig")

    monkeypatch.setattr(
        replay,
        "get_output_dirs",
        lambda _output_dir: {"daily": signal_dir, "base": signal_dir},
    )
    monkeypatch.setattr(replay, "_load_market_trade_dates", lambda: [])
    monkeypatch.setattr(replay, "EXEC_DIR", tmp_path / "execution")
    monkeypatch.setattr(replay, "BACKTEST_DIR", tmp_path / "backtest")
    mock_p2_script = tmp_path / "quant_p2_paper_trade.py"
    mock_p2_script.write_text("# mock\n", encoding="utf-8")
    monkeypatch.setattr(replay, "P2_SCRIPT", mock_p2_script)

    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, cwd=None, env=None, **_kwargs):
        calls.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(replay.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        replay,
        "_summarize_ledger",
        lambda _ledger_file: {
            "executed_days": 1,
            "nav_return_pct": 1.0,
            "max_drawdown_pct": -0.5,
            "turnover_sum": 1000.0,
            "turnover_mean": 1000.0,
            "exec_block_rate_pct": 0.0,
            "risk_block_rate_pct": 0.0,
            "style_hit_total": 0.0,
            "style_hit_mean": 0.0,
            "style_hit_rate_pct": 0.0,
            "style_hit_size_total": 0.0,
            "style_hit_beta_total": 0.0,
            "style_hit_momentum_total": 0.0,
            "style_hit_vol_total": 0.0,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_p2_rolling_replay.py",
            "--profiles",
            "quality_regime",
            "--windows",
            "1",
            "--style-size-grid",
            "0.9",
            "--style-beta-grid",
            "0.9",
            "--style-momentum-grid",
            "1.2",
            "--style-vol-grid",
            "1.1",
            "--style-lb-short-grid",
            "20",
            "--style-lb-beta-grid",
            "60",
            "--write-latest",
            "--max-metadata-staleness-days",
            "999",
            "--min-industry-coverage-pct",
            "85",
        ],
    )

    rc = replay.main()
    assert rc == 0
    assert calls
    backtest_files = {p.name for p in (tmp_path / "backtest").iterdir()}
    assert any(name.startswith("p2_rolling_replay_summary_") and name.endswith("_quality_regime.csv") for name in backtest_files)
    assert "p2_rolling_replay_summary_latest_quality_regime.csv" in backtest_files
    assert "p2_rolling_replay_runs_latest_quality_regime.csv" in backtest_files
    assert "p2_rolling_replay_meta_latest_quality_regime.json" in backtest_files
    first = calls[0]
    assert "--max-metadata-staleness-days" in first
    assert first[first.index("--max-metadata-staleness-days") + 1] == "999.0"
    assert "--min-industry-coverage-pct" in first
    assert first[first.index("--min-industry-coverage-pct") + 1] == "85.0"


def test_main_uses_profile_signal_calendar_when_available(monkeypatch, tmp_path: Path):
    shared_dir = tmp_path / "daily"
    profile_root = tmp_path / "daily_profiles"
    profile_dir = profile_root / "quality_regime_candidate_v8_reserve_pool"
    shared_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    (shared_dir / "daily_20260401.csv").write_text("代码,名称\n000001,平安银行\n", encoding="utf-8-sig")
    profile_file = profile_dir / "daily_20260402.csv"
    profile_file.write_text("代码,名称,target_weight\n000002,万科A,0.10\n", encoding="utf-8-sig")

    monkeypatch.setattr(
        replay,
        "get_output_dirs",
        lambda _output_dir: {"daily": shared_dir, "base": shared_dir},
    )
    monkeypatch.setattr(replay, "_load_market_trade_dates", lambda: [])
    monkeypatch.setattr(replay, "EXEC_DIR", tmp_path / "execution")
    monkeypatch.setattr(replay, "BACKTEST_DIR", tmp_path / "backtest")
    mock_p2_script = tmp_path / "quant_p2_paper_trade.py"
    mock_p2_script.write_text("# mock\n", encoding="utf-8")
    monkeypatch.setattr(replay, "P2_SCRIPT", mock_p2_script)

    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, cwd=None, env=None, **_kwargs):
        calls.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(replay.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        replay,
        "_summarize_ledger",
        lambda _ledger_file: {
            "executed_days": 1,
            "nav_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "turnover_mean": 0.0,
            "exec_block_rate_pct": 0.0,
            "risk_block_rate_pct": 0.0,
            "style_hit_rate_pct": 0.0,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_p2_rolling_replay.py",
            "--profiles",
            "quality_regime_candidate_v8_reserve_pool",
            "--windows",
            "3",
            "--style-size-grid",
            "0.9",
            "--style-beta-grid",
            "0.9",
            "--style-momentum-grid",
            "1.2",
            "--style-vol-grid",
            "1.1",
            "--style-lb-short-grid",
            "20",
            "--style-lb-beta-grid",
            "60",
            "--profile-signal-root",
            str(profile_root),
            "--write-latest",
        ],
    )

    assert replay.main() == 0
    assert calls
    first = calls[0]
    assert "--signal-file" in first
    assert first[first.index("--signal-file") + 1] == str(profile_file)
    assert "--date" not in first
    runs = pd.read_csv(
        tmp_path / "backtest" / "p2_rolling_replay_runs_latest_quality_regime_candidate_v8_reserve_pool.csv"
    )
    assert runs["signal_date_source"].iloc[0] == "profile"
    summary = pd.read_csv(
        tmp_path / "backtest" / "p2_rolling_replay_summary_latest_quality_regime_candidate_v8_reserve_pool.csv"
    )
    assert int(summary["requested_window_days"].iloc[0]) == 3
    assert int(summary["signal_calendar_shortfall_days"].iloc[0]) == 2
    assert round(float(summary["signal_calendar_coverage_pct"].iloc[0]), 2) == 33.33
