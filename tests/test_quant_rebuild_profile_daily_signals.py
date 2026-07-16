# -*- coding: utf-8 -*-
"""Profile daily rebuild helper tests."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pandas as pd

import scripts.quant_rebuild_profile_daily_signals as rebuild


def test_run_daily_select_inprocess_preserves_profile_args_and_restores_state(monkeypatch):
    rebuild._DAILY_MODULE_CACHE = None
    old_argv = sys.argv[:]
    old_env = os.environ.copy()
    old_cwd = os.getcwd()
    seen: dict[str, object] = {}

    def _main():
        seen["argv"] = sys.argv[:]
        seen["profile"] = os.environ.get("MFTS_ACTIVE_PROFILE")
        print("daily-ok")
        return 0

    monkeypatch.setattr(rebuild.importlib, "import_module", lambda _name: SimpleNamespace(main=_main))

    cmd = [
        sys.executable,
        str(rebuild.DAILY_SCRIPT),
        "--date",
        "20260401",
        "--output-profile",
        "quality_regime_candidate_v16_holiday_gap_guard",
    ]
    env = old_env.copy()
    env["MFTS_ACTIVE_PROFILE"] = "quality_regime_candidate_v16_holiday_gap_guard"

    proc = rebuild._run_daily_select(cmd, env=env, execution_mode="inprocess", verbose=False)

    assert proc.returncode == 0
    assert "daily-ok" in str(proc.stdout)
    assert seen["profile"] == "quality_regime_candidate_v16_holiday_gap_guard"
    assert seen["argv"] == [str(rebuild.DAILY_SCRIPT), *cmd[2:]]
    assert sys.argv == old_argv
    assert os.getcwd() == old_cwd
    assert os.environ.get("MFTS_ACTIVE_PROFILE") == old_env.get("MFTS_ACTIVE_PROFILE")


def test_run_daily_select_inprocess_converts_system_exit_to_return_code(monkeypatch):
    rebuild._DAILY_MODULE_CACHE = None

    def _main():
        raise SystemExit(2)

    monkeypatch.setattr(rebuild.importlib, "import_module", lambda _name: SimpleNamespace(main=_main))

    proc = rebuild._run_daily_select(
        [sys.executable, str(rebuild.DAILY_SCRIPT), "--date", "20260401"],
        env=os.environ.copy(),
        execution_mode="inprocess",
        verbose=False,
    )

    assert proc.returncode == 2


def test_load_trade_dates_reads_ods_sessions(monkeypatch):
    class FakeGateway:
        def available_trade_dates(self):
            return ["2026-04-01", "2026-04-02"]

    monkeypatch.setattr(rebuild, "AShareMarketDataGateway", lambda: FakeGateway(), raising=False)

    assert rebuild._load_trade_dates() == ["20260401", "20260402"]


def test_select_dates_can_use_existing_daily_files(monkeypatch, tmp_path):
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    (daily_dir / "daily_20260402.csv").write_text("x", encoding="utf-8")
    (daily_dir / "daily_20260401.csv").write_text("x", encoding="utf-8")
    (daily_dir / "notes.txt").write_text("ignore", encoding="utf-8")
    monkeypatch.setattr(rebuild, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(rebuild, "_load_trade_dates", lambda: ["19990101"])

    args = SimpleNamespace(date_source="daily-files", start="20260402", end="20260410", days=0, replayable_only=False)

    assert rebuild._select_dates(args) == ["20260402"]


def test_select_dates_replayable_only_excludes_endpoint_before_days(monkeypatch, tmp_path):
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    for day in ["20260401", "20260402", "20260403"]:
        (daily_dir / f"daily_{day}.csv").write_text("x", encoding="utf-8")
    monkeypatch.setattr(rebuild, "DAILY_DIR", daily_dir)
    monkeypatch.setattr(rebuild, "_load_trade_dates", lambda: ["20260401", "20260402", "20260403"])

    args = SimpleNamespace(date_source="daily-files", start="", end="", days=2, replayable_only=True)

    assert rebuild._select_dates(args) == ["20260401", "20260402"]


def test_select_dates_end_plus_days_selects_recent_window(monkeypatch):
    monkeypatch.setattr(
        rebuild,
        "_load_trade_dates",
        lambda: ["20260401", "20260402", "20260403", "20260407", "20260408"],
    )
    args = SimpleNamespace(date_source="data", start="", end="20260407", days=2, replayable_only=True)

    assert rebuild._select_dates(args) == ["20260403", "20260407"]


def test_select_dates_normalizes_hyphenated_end_with_days(monkeypatch):
    monkeypatch.setattr(
        rebuild,
        "_load_trade_dates",
        lambda: ["20251204", "20251205", "20260409", "20260410", "20260413", "20260414"],
    )
    args = SimpleNamespace(date_source="data", start="", end="2026-04-14", days=3, replayable_only=True)

    assert rebuild._select_dates(args) == ["20260409", "20260410", "20260413"]


def test_remove_output_file_deletes_stale_daily(tmp_path):
    stale = tmp_path / "daily_20260126.csv"
    stale.write_text("old", encoding="utf-8")

    assert rebuild._remove_output_file(stale) is True
    assert not stale.exists()
    assert rebuild._remove_output_file(stale) is False


def test_main_forwards_metadata_staleness_days(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    daily_script = tmp_path / "daily_ml_select.py"
    daily_script.write_text("placeholder", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_daily_select(cmd, *, env, execution_mode, verbose):
        captured["cmd"] = list(cmd)
        out_file = output_dir / "daily_profiles" / "quality_regime_candidate" / "daily_20260401.csv"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text("code,target_weight\n000001,0.1\n", encoding="utf-8")
        return rebuild.subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(rebuild, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(rebuild, "DAILY_SCRIPT", daily_script)
    monkeypatch.setattr(rebuild, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(rebuild, "_select_dates", lambda _args: ["20260401"])
    monkeypatch.setattr(rebuild, "_run_daily_select", fake_run_daily_select)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_rebuild_profile_daily_signals.py",
            "--profiles",
            "quality_regime_candidate",
            "--max-metadata-staleness-days",
            "999",
        ],
    )

    assert rebuild.main() == 0
    cmd = captured["cmd"]
    assert cmd[cmd.index("--max-metadata-staleness-days") + 1] == "999.0"
