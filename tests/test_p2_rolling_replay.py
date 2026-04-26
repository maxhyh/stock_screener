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
                "risk_input_count": [10, 8],
                "risk_blocked_count": [2, 1],
                "risk_style_limits_hit": [3, 1],
                "risk_style_size_limits_hit": [2, 0],
                "risk_style_beta_limits_hit": [1, 1],
                "risk_style_momentum_limits_hit": [1, 1],
                "risk_style_vol_limits_hit": [0, 1],
                "target_weight_source": ["external_target_weight", "external_target_weight"],
                "target_weight_checksum": ["abc", "def"],
                "entry_not_tradable_orders": [1, 3],
                "exit_not_tradable_orders": [0, 2],
                "blocked_target_weight": [0.03, 0.07],
            "entry_not_tradable_target_weight": [0.03, 0.05],
            "exit_not_tradable_target_weight": [0.0, 0.02],
            "blocked_sell_current_weight": [0.04, 0.08],
            "blocked_sell_notional": [40_000.0, 80_000.0],
            "blocked_sell_orders": [1, 2],
            "blocked_exit_buy_freeze": [1, 0],
            "blocked_exit_freeze_orders": [3, 0],
            "blocked_exit_freeze_target_weight": [0.12, 0.0],
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
    assert float(s["entry_not_tradable_orders"]) == 4.0
    assert float(s["exit_not_tradable_orders"]) == 2.0
    assert round(float(s["blocked_target_weight_sum"]), 2) == 0.10
    assert float(s["max_daily_tradability_blocked_orders"]) == 5.0
    assert round(float(s["blocked_sell_current_weight_sum"]), 2) == 0.12
    assert round(float(s["blocked_sell_current_weight_max"]), 2) == 0.08
    assert float(s["blocked_sell_notional_sum"]) == 120_000.0
    assert float(s["blocked_sell_orders_sum"]) == 3.0
    assert float(s["blocked_exit_buy_freeze_days"]) == 1.0
    assert float(s["blocked_exit_freeze_orders_sum"]) == 3.0
    assert round(float(s["blocked_exit_freeze_target_weight_sum"]), 2) == 0.12
    assert float(s["blocked_state_count_max"]) == 4.0
    assert float(s["blocked_state_max_consecutive_days_max"]) == 2.0
    assert float(s["blocked_state_sell_notional_max"]) == 90_000.0
    assert round(float(s["blocked_state_buy_target_weight_sum"]), 2) == 0.16
    assert round(float(s["blocked_state_sell_target_weight_sum"]), 2) == 0.12
    assert float(s["blocked_state_resolved_count_sum"]) == 2.0


def test_main_passes_metadata_gate_overrides(monkeypatch, tmp_path: Path):
    signal_dir = tmp_path / "daily"
    signal_dir.mkdir(parents=True, exist_ok=True)
    (signal_dir / "daily_20260401.csv").write_text("代码,名称\n000001,平安银行\n", encoding="utf-8-sig")

    monkeypatch.setattr(
        replay,
        "get_output_dirs",
        lambda _output_dir: {"daily": signal_dir, "base": signal_dir},
    )
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
