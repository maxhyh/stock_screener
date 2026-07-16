# -*- coding: utf-8 -*-
"""daily_all 编排关键路径测试。"""

from __future__ import annotations

import sys
from datetime import datetime as _dt

import scripts.daily_all as daily_all


def test_get_auto_target_date_uses_prev_trading_day_before_cutoff(monkeypatch):
    class _FakeDateTime:
        @classmethod
        def now(cls):
            return _dt(2026, 4, 14, 7, 30, 0)

    monkeypatch.setattr(daily_all, "datetime", _FakeDateTime)
    monkeypatch.setenv("MFTS_AUTO_TARGET_CUTOFF_HOUR", "18")
    assert daily_all.get_auto_target_date() == "20260413"


def test_get_auto_target_date_uses_friday_for_monday_morning(monkeypatch):
    class _FakeDateTime:
        @classmethod
        def now(cls):
            return _dt(2026, 4, 13, 9, 0, 0)  # Monday

    monkeypatch.setattr(daily_all, "datetime", _FakeDateTime)
    monkeypatch.setenv("MFTS_AUTO_TARGET_CUTOFF_HOUR", "18")
    assert daily_all.get_auto_target_date() == "20260410"


def test_get_auto_target_date_uses_today_after_cutoff(monkeypatch):
    class _FakeDateTime:
        @classmethod
        def now(cls):
            return _dt(2026, 4, 14, 19, 0, 0)

    monkeypatch.setattr(daily_all, "datetime", _FakeDateTime)
    monkeypatch.setenv("MFTS_AUTO_TARGET_CUTOFF_HOUR", "18")
    assert daily_all.get_auto_target_date() == "20260414"


def test_load_trade_calendar_info_normalizes_ods_coverage_keys(monkeypatch):
    class _Gateway:
        def available_trade_dates(self):
            return ["2026-04-13", "2026-04-14"]

        def daily_bar_counts(self, sessions):
            assert sessions == ["2026-04-13", "2026-04-14"]
            return {"2026-04-13": 3601, "2026-04-14": 3602}

    monkeypatch.setattr(daily_all, "AShareMarketDataGateway", _Gateway)
    monkeypatch.setenv("MFTS_PIPELINE_CALENDAR_DAYS", "30")

    dates, counts = daily_all.load_trade_calendar_info()
    assert dates == ["20260413", "20260414"]
    assert counts == {"20260413": 3601, "20260414": 3602}


def test_calc_verify_targets_respects_label_horizon():
    trade_dates = ["20260407", "20260408", "20260409", "20260410", "20260411"]
    trade_counts = {d: 3600 for d in trade_dates}
    ml_dates = set(trade_dates)
    verify_dates = set()

    # open_to_open + h=3 需要 pred 后至少 4 个交易日，仅 20260407 可验证
    o2o_targets = daily_all.calc_verify_targets(
        trade_dates=trade_dates,
        trade_counts=trade_counts,
        ml_dates=ml_dates,
        verify_dates=verify_dates,
        mode="latest",
        catchup_days=10,
        min_verify_stocks=3000,
        label_mode="open_to_open",
        label_horizon=3,
    )
    assert o2o_targets == ["20260407"]

    # close_to_close_t1 仅需 T+1，latest 应取最近可验证日
    c2c_targets = daily_all.calc_verify_targets(
        trade_dates=trade_dates,
        trade_counts=trade_counts,
        ml_dates=ml_dates,
        verify_dates=verify_dates,
        mode="latest",
        catchup_days=10,
        min_verify_stocks=3000,
        label_mode="close_to_close_t1",
        label_horizon=1,
    )
    assert c2c_targets == ["20260410"]


def test_latest_mode_stops_when_ods_does_not_cover_target(monkeypatch):
    saved = {}

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260320")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: None)
    monkeypatch.setattr(daily_all, "save_state", lambda record: saved.setdefault("record", record))
    monkeypatch.setattr(sys, "argv", ["daily_all.py", "--mode", "latest", "--skip-profile-gate"])

    ok = daily_all.main()
    assert ok is False
    assert saved["record"]["steps"]["data_availability"] is False
    assert saved["record"]["steps"]["mfts_scan"] is False
    assert saved["record"]["steps"]["ml_select"] is False
    assert saved["record"]["steps"]["verify"] is False


def test_latest_mode_uses_covered_ods_then_runs_scan_ml(monkeypatch):
    calls = []

    def fake_run_script(script_path, description="", script_args=None, extra_env=None):
        calls.append(
            {
                "script_path": script_path,
                "description": description,
                "script_args": script_args or [],
                "extra_env": extra_env or {},
            }
        )
        return True

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260320")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: "20260320")
    monkeypatch.setattr(
        daily_all,
        "load_trade_calendar_info",
        lambda: (["20260318", "20260319", "20260320"], {"20260318": 3600, "20260319": 3600, "20260320": 3600}),
    )
    monkeypatch.setattr(daily_all, "list_stage_dates", lambda prefix, subdir_key: set())
    monkeypatch.setattr(daily_all, "run_script", fake_run_script)
    monkeypatch.setattr(daily_all, "save_state", lambda record: None)
    monkeypatch.setattr(sys, "argv", ["daily_all.py", "--mode", "latest", "--skip-profile-gate"])

    ok = daily_all.main()
    assert ok is True
    assert len(calls) == 2

    scan_call = calls[0]
    ml_call = calls[1]

    assert scan_call["script_path"].endswith("core/mfts_screener.py")
    assert scan_call["script_args"] == ["--date", "20260320"]

    assert ml_call["script_path"].endswith("scripts/daily_ml_select.py")
    assert ml_call["script_args"] == ["--date", "20260320"]


def test_latest_mode_does_not_invoke_data_update_when_ods_covers_target(monkeypatch):
    calls = []

    def fake_run_script(script_path, description="", script_args=None, extra_env=None):
        calls.append(
            {
                "script_path": script_path,
                "description": description,
                "script_args": script_args or [],
                "extra_env": extra_env or {},
            }
        )
        return True

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260413")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: "20260413")
    monkeypatch.setattr(
        daily_all,
        "load_trade_calendar_info",
        lambda: (["20260411", "20260412", "20260413"], {"20260411": 3600, "20260412": 3600, "20260413": 3600}),
    )
    monkeypatch.setattr(daily_all, "list_stage_dates", lambda prefix, subdir_key: set())
    monkeypatch.setattr(daily_all, "run_script", fake_run_script)
    monkeypatch.setattr(daily_all, "save_state", lambda record: None)
    monkeypatch.setattr(sys, "argv", ["daily_all.py", "--mode", "latest", "--skip-profile-gate"])

    ok = daily_all.main()
    assert ok is True
    assert len(calls) == 2
    assert calls[0]["script_path"].endswith("core/mfts_screener.py")
    assert calls[1]["script_path"].endswith("scripts/daily_ml_select.py")


def test_latest_mode_runs_profile_gate_by_default(monkeypatch):
    calls = []

    def fake_run_script(script_path, description="", script_args=None, extra_env=None):
        calls.append(
            {
                "script_path": script_path,
                "description": description,
                "script_args": script_args or [],
                "extra_env": extra_env or {},
            }
        )
        return True

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260413")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: "20260413")
    monkeypatch.setattr(
        daily_all,
        "load_trade_calendar_info",
        lambda: (["20260411", "20260412", "20260413"], {"20260411": 3600, "20260412": 3600, "20260413": 3600}),
    )
    monkeypatch.setattr(daily_all, "list_stage_dates", lambda prefix, subdir_key: set())
    monkeypatch.setattr(daily_all, "run_script", fake_run_script)
    monkeypatch.setattr(daily_all, "save_state", lambda record: None)
    monkeypatch.setattr(sys, "argv", ["daily_all.py", "--mode", "latest"])

    ok = daily_all.main()
    assert ok is True
    assert any(c["script_path"].endswith("scripts/quant_refresh_promotion_gate.py") for c in calls)


def test_catchup_stops_when_ods_is_behind_target_without_downloading(monkeypatch):
    saved = {}

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260408")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: "20260403")
    monkeypatch.setattr(daily_all, "save_state", lambda record: saved.setdefault("record", record))
    monkeypatch.setattr(sys, "argv", ["daily_all.py", "--mode", "catchup", "--skip-profile-gate"])

    ok = daily_all.main()
    assert ok is False
    assert saved["record"]["steps"]["data_availability"] is False


def test_latest_mode_with_p1_p2_runs_optional_steps(monkeypatch):
    calls = []

    def fake_run_script(script_path, description="", script_args=None, extra_env=None):
        calls.append(
            {
                "script_path": script_path,
                "description": description,
                "script_args": script_args or [],
                "extra_env": extra_env or {},
            }
        )
        return True

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260320")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: "20260320")
    monkeypatch.setattr(
        daily_all,
        "load_trade_calendar_info",
        lambda: (["20260318", "20260319", "20260320"], {"20260318": 3600, "20260319": 3600, "20260320": 3600}),
    )
    monkeypatch.setattr(daily_all, "list_stage_dates", lambda prefix, subdir_key: set())
    monkeypatch.setattr(daily_all, "run_script", fake_run_script)
    monkeypatch.setattr(daily_all, "save_state", lambda record: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_all.py",
            "--mode",
            "latest",
            "--with-p1",
            "--with-p2",
            "--p2-broker",
            "paper",
            "--p2-dry-run",
            "--disable-industry-coverage-gate",
            "--skip-profile-gate",
        ],
    )

    ok = daily_all.main()
    assert ok is True
    assert len(calls) == 4
    assert calls[2]["script_path"].endswith("scripts/quant_p1_analytics.py")
    assert calls[3]["script_path"].endswith("scripts/quant_p2_paper_trade.py")
    assert "--date" in calls[3]["script_args"]
    assert "20260320" in calls[3]["script_args"]
    assert "--broker" in calls[3]["script_args"]
    assert "paper" in calls[3]["script_args"]


def test_latest_mode_with_p3_runs_consistency_step(monkeypatch):
    calls = []

    def fake_run_script(script_path, description="", script_args=None, extra_env=None):
        calls.append(
            {
                "script_path": script_path,
                "description": description,
                "script_args": script_args or [],
                "extra_env": extra_env or {},
            }
        )
        return True

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260320")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: "20260408")
    monkeypatch.setattr(
        daily_all,
        "load_trade_calendar_info",
        lambda: (["20260318", "20260319", "20260320"], {"20260318": 3600, "20260319": 3600, "20260320": 3600}),
    )
    monkeypatch.setattr(daily_all, "list_stage_dates", lambda prefix, subdir_key: set())
    monkeypatch.setattr(daily_all, "run_script", fake_run_script)
    monkeypatch.setattr(daily_all, "save_state", lambda record: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_all.py",
            "--mode",
            "latest",
            "--with-p3-consistency",
            "--p3-broker",
            "paper",
            "--disable-industry-coverage-gate",
            "--skip-profile-gate",
        ],
    )

    ok = daily_all.main()
    assert ok is True
    assert len(calls) == 3
    assert calls[-1]["script_path"].endswith("scripts/quant_exec_consistency_report.py")
    assert "--broker" in calls[-1]["script_args"]
    assert "paper" in calls[-1]["script_args"]


def test_latest_mode_with_p2_recommendation_flags(monkeypatch):
    calls = []

    def fake_run_script(script_path, description="", script_args=None, extra_env=None):
        calls.append(
            {
                "script_path": script_path,
                "description": description,
                "script_args": script_args or [],
                "extra_env": extra_env or {},
            }
        )
        return True

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260408")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: "20260408")
    monkeypatch.setattr(
        daily_all,
        "load_trade_calendar_info",
        lambda: (["20260407", "20260408"], {"20260407": 3600, "20260408": 3600}),
    )
    monkeypatch.setattr(daily_all, "list_stage_dates", lambda prefix, subdir_key: set())
    monkeypatch.setattr(daily_all, "run_script", fake_run_script)
    monkeypatch.setattr(daily_all, "save_state", lambda record: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_all.py",
            "--mode",
            "latest",
            "--with-p2",
            "--p2-broker",
            "paper",
            "--p2-dry-run",
            "--p2-use-recommendation",
            "--p2-recommend-rank",
            "2",
            "--p2-recommend-file",
            "output/backtest/quant_strategy_paper_recommendations.csv",
            "--p2-recommend-keep-signal-position",
            "--disable-industry-coverage-gate",
            "--skip-profile-gate",
        ],
    )

    ok = daily_all.main()
    assert ok is True
    p2_call = calls[-1]
    assert p2_call["script_path"].endswith("scripts/quant_p2_paper_trade.py")
    assert "--use-recommendation" in p2_call["script_args"]
    assert "--recommend-rank" in p2_call["script_args"]
    assert "2" in p2_call["script_args"]
    assert "--recommend-file" in p2_call["script_args"]
    assert "output/backtest/quant_strategy_paper_recommendations.csv" in p2_call["script_args"]
    assert "--recommend-keep-signal-position" in p2_call["script_args"]


def test_latest_mode_with_p2_risk_tuning_flags(monkeypatch):
    calls = []

    def fake_run_script(script_path, description="", script_args=None, extra_env=None):
        calls.append(
            {
                "script_path": script_path,
                "description": description,
                "script_args": script_args or [],
                "extra_env": extra_env or {},
            }
        )
        return True

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260408")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: "20260408")
    monkeypatch.setattr(
        daily_all,
        "load_trade_calendar_info",
        lambda: (["20260407", "20260408"], {"20260407": 3600, "20260408": 3600}),
    )
    monkeypatch.setattr(daily_all, "list_stage_dates", lambda prefix, subdir_key: set())
    monkeypatch.setattr(daily_all, "run_script", fake_run_script)
    monkeypatch.setattr(daily_all, "save_state", lambda record: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_all.py",
            "--mode",
            "latest",
            "--with-p2",
            "--p2-broker",
            "paper",
            "--p2-dry-run",
            "--p2-risk-max-industry-weight",
            "0.35",
            "--p2-risk-max-adv-participation",
            "0.06",
            "--p2-risk-min-price",
            "2.0",
            "--p2-risk-max-style-size-exposure-abs",
            "0.20",
            "--p2-risk-max-style-beta-exposure-abs",
            "0.25",
            "--p2-risk-max-style-momentum-exposure-abs",
            "0.30",
            "--p2-risk-max-style-vol-exposure-abs",
            "0.35",
            "--p2-risk-style-lb-short",
            "30",
            "--p2-risk-style-lb-beta",
            "90",
            "--disable-industry-coverage-gate",
            "--skip-profile-gate",
        ],
    )

    ok = daily_all.main()
    assert ok is True
    ml_call = next(c for c in calls if c["script_path"].endswith("scripts/daily_ml_select.py"))
    assert ml_call["extra_env"]["MFTS_SIGNAL_PRETRADE_GATE"] == "true"
    assert ml_call["extra_env"]["MFTS_RISK_MAX_INDUSTRY_WEIGHT"] == "0.35"
    assert ml_call["extra_env"]["MFTS_RISK_MAX_ADV_PARTICIPATION"] == "0.06"
    assert ml_call["extra_env"]["MFTS_RISK_MIN_PRICE"] == "2.0"
    assert ml_call["extra_env"]["MFTS_RISK_MAX_STYLE_SIZE_EXPOSURE_ABS"] == "0.2"
    assert ml_call["extra_env"]["MFTS_RISK_MAX_STYLE_BETA_EXPOSURE_ABS"] == "0.25"
    assert ml_call["extra_env"]["MFTS_RISK_MAX_STYLE_MOMENTUM_EXPOSURE_ABS"] == "0.3"
    assert ml_call["extra_env"]["MFTS_RISK_MAX_STYLE_VOL_EXPOSURE_ABS"] == "0.35"
    assert ml_call["extra_env"]["MFTS_RISK_STYLE_LB_SHORT"] == "30"
    assert ml_call["extra_env"]["MFTS_RISK_STYLE_LB_BETA"] == "90"
    p2_call = calls[-1]
    assert p2_call["script_path"].endswith("scripts/quant_p2_paper_trade.py")
    assert "--risk-max-industry-weight" in p2_call["script_args"]
    assert "0.35" in p2_call["script_args"]
    assert "--risk-max-adv-participation" in p2_call["script_args"]
    assert "0.06" in p2_call["script_args"]
    assert "--risk-min-price" in p2_call["script_args"]
    assert "2.0" in p2_call["script_args"]
    assert "--risk-max-style-size-exposure-abs" in p2_call["script_args"]
    assert "0.2" in p2_call["script_args"]
    assert "--risk-max-style-beta-exposure-abs" in p2_call["script_args"]
    assert "0.25" in p2_call["script_args"]
    assert "--risk-max-style-momentum-exposure-abs" in p2_call["script_args"]
    assert "0.3" in p2_call["script_args"]
    assert "--risk-max-style-vol-exposure-abs" in p2_call["script_args"]
    assert "0.35" in p2_call["script_args"]
    assert "--risk-style-lb-short" in p2_call["script_args"]
    assert "30" in p2_call["script_args"]
    assert "--risk-style-lb-beta" in p2_call["script_args"]
    assert "90" in p2_call["script_args"]


def test_latest_mode_blocks_p2_when_industry_coverage_gate_fails(monkeypatch):
    calls = []

    def fake_run_script(script_path, description="", script_args=None, extra_env=None):
        calls.append(
            {
                "script_path": script_path,
                "description": description,
                "script_args": script_args or [],
                "extra_env": extra_env or {},
            }
        )
        return True

    monkeypatch.setattr(daily_all, "get_auto_target_date", lambda: "20260408")
    monkeypatch.setattr(daily_all, "load_latest_data_date", lambda: "20260408")
    monkeypatch.setattr(
        daily_all,
        "load_trade_calendar_info",
        lambda: (["20260407", "20260408"], {"20260407": 3600, "20260408": 3600}),
    )
    monkeypatch.setattr(
        daily_all,
        "load_industry_coverage",
        lambda: {
            "file": "/tmp/stock_info.csv",
            "rows": 100,
            "industry_nonempty": 10,
            "coverage_pct": 10.0,
            "ok": True,
        },
    )
    monkeypatch.setattr(daily_all, "list_stage_dates", lambda prefix, subdir_key: set())
    monkeypatch.setattr(daily_all, "run_script", fake_run_script)
    monkeypatch.setattr(daily_all, "save_state", lambda record: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_all.py",
            "--mode",
            "latest",
            "--with-p2",
            "--p2-broker",
            "paper",
            "--p2-dry-run",
            "--min-industry-coverage-pct",
            "80",
        ],
    )

    ok = daily_all.main()
    assert ok is False
    assert not any(c["script_path"].endswith("scripts/quant_p2_paper_trade.py") for c in calls)
