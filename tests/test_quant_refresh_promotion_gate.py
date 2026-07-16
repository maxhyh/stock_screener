# -*- coding: utf-8 -*-
"""promotion gate refresh script tests."""

from __future__ import annotations

import json
import sys

import pytest

import scripts.quant_refresh_promotion_gate as refresh


def test_derive_period_from_explicit_end():
    start, end = refresh._derive_period("2026-04-14", 10)
    assert end == "2026-04-14"
    assert start.startswith("2025-")


def test_derive_period_without_end_uses_ods_last_session(monkeypatch, tmp_path):
    monkeypatch.setattr(refresh, "_load_market_last_trade_date", lambda: "20260414")

    start, end = refresh._derive_period("", 10)

    assert start.startswith("2025-")
    assert end == "2026-04-14"


def test_refresh_market_calendar_uses_ods_gateway(monkeypatch):
    class FakeGateway:
        def available_trade_dates(self):
            return ["2026-04-10", "2026-04-13", "2026-04-14"]

    monkeypatch.setattr(refresh, "AShareMarketDataGateway", lambda: FakeGateway(), raising=False)

    assert refresh._load_market_trade_dates() == ["20260410", "20260413", "20260414"]
    assert refresh._load_market_last_trade_date() == "20260414"


def test_main_builds_expected_commands(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    backtest_dir.mkdir()
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--lookback-months",
            "10",
            "--p2-windows",
            "60,90,120",
        ],
    )

    rc = refresh.main()
    assert rc == 0
    assert len(calls) == 5
    assert any("quant_profile_rolling_compare.py" in part for part in calls[0][0])
    assert "--write-latest" in calls[0][0]
    assert any("quant_p2_rolling_replay.py" in part for part in calls[1][0])
    assert any("quant_p2_shadow_diagnosis.py" in part for part in calls[2][0])
    assert any("quant_research_execution_funnel.py" in part for part in calls[3][0])
    assert any("quant_profile_promotion_review.py" in part for part in calls[4][0])
    assert "--score-alpha-diagnosis" not in calls[4][0]


def test_main_adds_existing_score_alpha_latest_files(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    backtest_dir.mkdir()
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    score_file = backtest_dir / "quant_score_alpha_diagnosis_latest_quality_regime_candidate.json"
    score_file.write_text("{}", encoding="utf-8")

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
        ],
    )

    rc = refresh.main()
    assert rc == 0
    review_cmd = calls[-1][0]
    flag_idx = review_cmd.index("--score-alpha-diagnosis")
    assert review_cmd[flag_idx + 1] == str(score_file)


def test_main_prefers_explicit_score_alpha_files_over_discovered(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    backtest_dir.mkdir()
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    discovered = backtest_dir / "quant_score_alpha_diagnosis_latest_quality_regime_candidate.json"
    explicit = tmp_path / "explicit_score_alpha.json"
    discovered.write_text("{}", encoding="utf-8")
    explicit.write_text("{}", encoding="utf-8")

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--score-alpha-diagnosis",
            str(explicit),
        ],
    )

    rc = refresh.main()
    assert rc == 0
    review_cmd = calls[-1][0]
    flag_idx = review_cmd.index("--score-alpha-diagnosis")
    assert review_cmd[flag_idx + 1] == str(explicit.resolve())


def test_discover_score_alpha_daily_globs_uses_profile_isolated_files(tmp_path):
    root = tmp_path / "daily_profiles"
    profile_dir = root / "quality_regime_candidate"
    profile_dir.mkdir(parents=True)
    (profile_dir / "daily_20260414.csv").write_text("code,target_weight\n000001,0.1\n", encoding="utf-8")
    (root / "quality_regime_candidate_v2").mkdir()

    out = refresh._discover_score_alpha_daily_globs(
        ["quality_regime_candidate", "quality_regime_candidate_v2"],
        root,
    )

    assert out == {"quality_regime_candidate": str(profile_dir / "daily_*.csv")}


def test_signal_coverage_precheck_skips_sparse_profile_daily(tmp_path):
    root = tmp_path / "daily_profiles"
    sparse_dir = root / "quality_regime_candidate_sparse"
    full_dir = root / "quality_regime_candidate_full"
    sparse_dir.mkdir(parents=True)
    full_dir.mkdir(parents=True)
    for day in ["20260401", "20260402"]:
        (sparse_dir / f"daily_{day}.csv").write_text("code,target_weight\n000001,0.1\n", encoding="utf-8")
    for i in range(1, 6):
        (full_dir / f"daily_2026040{i}.csv").write_text("code,target_weight\n000001,0.1\n", encoding="utf-8")

    keep, rows = refresh._build_signal_coverage_precheck(
        profiles=["quality_regime", "quality_regime_candidate_sparse", "quality_regime_candidate_full"],
        main_profile="quality_regime",
        min_required_days=5,
        end="2026-04-05",
        market_last_trade_date="20260406",
        daily_profile_dir=root,
    )

    assert keep == ["quality_regime", "quality_regime_candidate_full"]
    by_profile = {str(row["profile"]): row for row in rows}
    assert by_profile["quality_regime"]["reason"] == "main_profile_always_kept"
    assert by_profile["quality_regime_candidate_sparse"]["decision"] == "skip"
    assert by_profile["quality_regime_candidate_sparse"]["reason"] == "profile_signal_days_insufficient"
    assert by_profile["quality_regime_candidate_sparse"]["replayable_profile_signal_days"] == 2
    assert by_profile["quality_regime_candidate_full"]["decision"] == "keep"


def test_signal_coverage_precheck_filters_no_next_trade_endpoint(tmp_path):
    root = tmp_path / "daily_profiles"
    profile_dir = root / "quality_regime_candidate"
    profile_dir.mkdir(parents=True)
    for day in ["20260403", "20260406"]:
        (profile_dir / f"daily_{day}.csv").write_text("code,target_weight\n000001,0.1\n", encoding="utf-8")

    keep, rows = refresh._build_signal_coverage_precheck(
        profiles=["quality_regime", "quality_regime_candidate"],
        main_profile="quality_regime",
        min_required_days=2,
        end="2026-04-06",
        market_last_trade_date="20260406",
        daily_profile_dir=root,
    )

    assert keep == ["quality_regime"]
    candidate = {str(row["profile"]): row for row in rows}["quality_regime_candidate"]
    assert candidate["raw_profile_signal_days"] == 2
    assert candidate["replayable_profile_signal_days"] == 1
    assert candidate["excluded_no_next_trade_days"] == 1


def test_build_reference_signal_dates_excludes_shared_daily_missing_market_bar(tmp_path):
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir(parents=True)
    for day in ["20260408", "20260409", "20260410", "20260413", "20260414"]:
        (daily_dir / f"daily_{day}.csv").write_text("code,target_weight\n000001,0.1\n", encoding="utf-8")

    out = refresh._build_reference_signal_dates(
        end="2026-04-14",
        market_trade_dates=["20260408", "20260410", "20260413", "20260414"],
        required_signal_days=3,
        output_dir=tmp_path,
    )

    assert out == ["20260408", "20260410", "20260413"]


def test_signal_coverage_precheck_rejects_calendar_mismatch_even_when_count_passes(tmp_path):
    root = tmp_path / "daily_profiles"
    profile_dir = root / "quality_regime_candidate"
    profile_dir.mkdir(parents=True)
    for day in ["20260401", "20260403", "20260404"]:
        (profile_dir / f"daily_{day}.csv").write_text("code,target_weight\n000001,0.1\n", encoding="utf-8")

    keep, rows = refresh._build_signal_coverage_precheck(
        profiles=["quality_regime", "quality_regime_candidate"],
        main_profile="quality_regime",
        min_required_days=3,
        end="2026-04-04",
        market_last_trade_date="20260405",
        daily_profile_dir=root,
        reference_dates=["20260401", "20260402", "20260403"],
    )

    assert keep == ["quality_regime"]
    candidate = {str(row["profile"]): row for row in rows}["quality_regime_candidate"]
    assert candidate["raw_profile_signal_days"] == 3
    assert candidate["replayable_profile_signal_days"] == 3
    assert candidate["decision"] == "skip"
    assert candidate["reason"] == "profile_signal_calendar_mismatch"
    assert candidate["missing_reference_signal_days"] == 1
    assert candidate["missing_reference_signal_dates"] == "20260402"
    assert candidate["reference_signal_coverage_pct"] == pytest.approx(100.0 * 2 / 3)


def test_write_signal_coverage_precheck_report_writes_latest_json_and_csv(tmp_path):
    json_path, csv_path = refresh._write_signal_coverage_precheck_report(
        rows=[
            {
                "profile": "quality_regime_candidate",
                "decision": "skip",
                "reason": "profile_signal_days_insufficient",
            }
        ],
        requested_profiles=["quality_regime", "quality_regime_candidate"],
        effective_profiles=["quality_regime"],
        main_profile="quality_regime",
        min_required_days=60,
        backtest_dir=tmp_path,
    )

    assert json_path.exists()
    assert csv_path.exists()
    latest = json.loads((tmp_path / "quant_signal_coverage_precheck_latest.json").read_text(encoding="utf-8"))
    assert latest["min_required_signal_days"] == 60
    assert latest["effective_profiles"] == ["quality_regime"]
    assert latest["skipped_profiles"] == ["quality_regime_candidate"]
    assert (tmp_path / "quant_signal_coverage_precheck_latest.csv").exists()


def _write_daily_with_target(path, target_sum: float, rows: int = 2):
    per_row = float(target_sum) / max(int(rows), 1)
    path.write_text(
        "code,target_weight\n" + "\n".join(f"00000{i + 1},{per_row}" for i in range(max(int(rows), 1))) + "\n",
        encoding="utf-8",
    )


def test_target_utilization_precheck_rejects_low_mean_and_zero_days(tmp_path):
    root = tmp_path / "daily_profiles"
    main_dir = root / "quality_regime"
    cand_dir = root / "quality_regime_candidate"
    main_dir.mkdir(parents=True)
    cand_dir.mkdir(parents=True)
    days = [f"2026040{i}" for i in range(1, 6)]
    for day in days:
        _write_daily_with_target(main_dir / f"daily_{day}.csv", 0.40)
    for day, target_sum in zip(days, [0.0, 0.10, 0.20, 0.30, 0.40]):
        _write_daily_with_target(cand_dir / f"daily_{day}.csv", target_sum)

    keep, rows = refresh._build_target_utilization_precheck(
        profiles=["quality_regime", "quality_regime_candidate"],
        main_profile="quality_regime",
        required_signal_days=5,
        end="2026-04-05",
        market_last_trade_date="20260406",
        daily_profile_dir=root,
        reference_dates=days,
        min_target_weight_sum_mean=0.30,
        max_zero_target_rate_pct=5.0,
    )

    assert keep == ["quality_regime"]
    candidate = {str(row["profile"]): row for row in rows}["quality_regime_candidate"]
    assert candidate["decision"] == "skip"
    assert "target_weight_sum_mean_below_floor" in str(candidate["reason"])
    assert "zero_target_rate_above_floor" in str(candidate["reason"])
    assert candidate["target_weight_sum_mean_5"] == pytest.approx(0.20)
    assert candidate["zero_target_days_5"] == 1
    assert candidate["zero_target_rate_pct_5"] == pytest.approx(20.0)


def test_target_utilization_precheck_allows_candidate_when_main_same_or_worse(tmp_path):
    root = tmp_path / "daily_profiles"
    main_dir = root / "quality_regime"
    cand_dir = root / "quality_regime_candidate"
    main_dir.mkdir(parents=True)
    cand_dir.mkdir(parents=True)
    days = [f"2026040{i}" for i in range(1, 6)]
    for day, target_sum in zip(days, [0.0, 0.10, 0.10, 0.10, 0.10]):
        _write_daily_with_target(main_dir / f"daily_{day}.csv", target_sum)
    for day in days:
        _write_daily_with_target(cand_dir / f"daily_{day}.csv", 0.20)

    keep, rows = refresh._build_target_utilization_precheck(
        profiles=["quality_regime", "quality_regime_candidate"],
        main_profile="quality_regime",
        required_signal_days=5,
        end="2026-04-05",
        market_last_trade_date="20260406",
        daily_profile_dir=root,
        reference_dates=days,
        min_target_weight_sum_mean=0.30,
        max_zero_target_rate_pct=5.0,
    )

    assert keep == ["quality_regime", "quality_regime_candidate"]
    candidate = {str(row["profile"]): row for row in rows}["quality_regime_candidate"]
    assert candidate["decision"] == "keep"
    assert candidate["reason"] == "target_utilization_passed"


def test_write_target_utilization_precheck_report_writes_latest_json_and_csv(tmp_path):
    json_path, csv_path = refresh._write_target_utilization_precheck_report(
        rows=[
            {
                "profile": "quality_regime_candidate",
                "decision": "skip",
                "reason": "target_weight_sum_mean_below_floor",
            }
        ],
        requested_profiles=["quality_regime", "quality_regime_candidate"],
        effective_profiles=["quality_regime"],
        main_profile="quality_regime",
        required_signal_days=60,
        backtest_dir=tmp_path,
    )

    assert json_path.exists()
    assert csv_path.exists()
    latest = json.loads((tmp_path / "quant_target_utilization_precheck_latest.json").read_text(encoding="utf-8"))
    assert latest["required_signal_days"] == 60
    assert latest["effective_profiles"] == ["quality_regime"]
    assert latest["skipped_profiles"] == ["quality_regime_candidate"]
    assert (tmp_path / "quant_target_utilization_precheck_latest.csv").exists()


def test_p2_smoke_precheck_prunes_candidate_below_main(tmp_path):
    summary = tmp_path / "p2_rolling_replay_summary_latest.csv"
    summary.write_text(
        "profile,window,nav_return_pct,max_drawdown_pct,target_weight_sum_mean,run_failed_days,"
        "broker_entry_not_tradable_orders,broker_exit_not_tradable_orders\n"
        "quality_regime,60,1.2,-5.0,0.41,0,0,3\n"
        "quality_regime_candidate,60,-1.9,-7.7,0.34,0,0,7\n",
        encoding="utf-8",
    )

    keep, rows = refresh._build_p2_smoke_precheck(
        profiles=["quality_regime", "quality_regime_candidate"],
        main_profile="quality_regime",
        summary_path=summary,
        smoke_window=60,
        min_target_weight_sum=0.30,
    )

    assert keep == ["quality_regime"]
    by_profile = {str(row["profile"]): row for row in rows}
    candidate = by_profile["quality_regime_candidate"]
    assert candidate["decision"] == "skip"
    assert "p2_smoke_nav_below_main" in str(candidate["reason"])
    assert "p2_smoke_mdd_worse_than_main" in str(candidate["reason"])
    assert "p2_smoke_exit_blocks_worse_than_main" in str(candidate["reason"])


def test_write_p2_smoke_precheck_report_writes_latest_json_and_csv(tmp_path):
    json_path, csv_path = refresh._write_p2_smoke_precheck_report(
        rows=[
            {
                "profile": "quality_regime_candidate",
                "decision": "skip",
                "reason": "p2_smoke_nav_below_main",
            }
        ],
        requested_profiles=["quality_regime", "quality_regime_candidate"],
        effective_profiles=["quality_regime"],
        main_profile="quality_regime",
        smoke_window=60,
        backtest_dir=tmp_path,
    )

    assert json_path.exists()
    assert csv_path.exists()
    latest = json.loads((tmp_path / "quant_p2_smoke_precheck_latest.json").read_text(encoding="utf-8"))
    assert latest["smoke_window"] == 60
    assert latest["effective_profiles"] == ["quality_regime"]
    assert latest["skipped_profiles"] == ["quality_regime_candidate"]
    assert (tmp_path / "quant_p2_smoke_precheck_latest.csv").exists()


def test_score_alpha_gate_passes_reads_latest_json(tmp_path):
    passed = tmp_path / "passed.json"
    failed = tmp_path / "failed.json"
    passed.write_text(json.dumps({"alpha_quality_gate": {"pass": True}}), encoding="utf-8")
    failed.write_text(json.dumps({"alpha_quality_gate": {"pass": False}}), encoding="utf-8")

    assert refresh._score_alpha_gate_passes(passed) is True
    assert refresh._score_alpha_gate_passes(failed) is False


def test_filter_profiles_by_score_alpha_gate_keeps_main_and_passed_candidates(tmp_path):
    passed = tmp_path / "quant_score_alpha_diagnosis_latest_quality_regime_candidate.json"
    failed = tmp_path / "quant_score_alpha_diagnosis_latest_quality_regime_candidate_v2.json"
    passed.write_text(json.dumps({"alpha_quality_gate": {"pass": True}}), encoding="utf-8")
    failed.write_text(json.dumps({"alpha_quality_gate": {"pass": False}}), encoding="utf-8")

    out = refresh._filter_profiles_by_score_alpha_gate(
        profiles=["quality_regime", "quality_regime_candidate", "quality_regime_candidate_v2"],
        main_profile="quality_regime",
        score_alpha_files=[passed, failed],
    )

    assert out == ["quality_regime", "quality_regime_candidate"]


def test_filter_profiles_by_score_alpha_gate_accepts_explicit_artifact_label(tmp_path):
    explicit = tmp_path / "explicit_score_alpha.json"
    explicit.write_text(
        json.dumps(
            {
                "artifact_label": "quality_regime_candidate",
                "alpha_quality_gate": {"pass": True},
            }
        ),
        encoding="utf-8",
    )

    out = refresh._filter_profiles_by_score_alpha_gate(
        profiles=["quality_regime", "quality_regime_candidate"],
        main_profile="quality_regime",
        score_alpha_files=[explicit],
    )

    assert out == ["quality_regime", "quality_regime_candidate"]


def test_build_score_alpha_precheck_records_skip_reasons(tmp_path):
    failed = tmp_path / "quant_score_alpha_diagnosis_latest_quality_regime_candidate.json"
    failed.write_text(
        json.dumps({"alpha_quality_gate": {"pass": False, "reasons": ["no_gate_score_passed"]}}),
        encoding="utf-8",
    )

    keep, rows = refresh._build_score_alpha_precheck(
        profiles=["quality_regime", "quality_regime_candidate", "quality_regime_candidate_v2"],
        main_profile="quality_regime",
        score_alpha_files=[failed],
    )

    assert keep == ["quality_regime"]
    by_profile = {str(row["profile"]): row for row in rows}
    assert by_profile["quality_regime"]["decision"] == "keep"
    assert by_profile["quality_regime_candidate"]["decision"] == "skip"
    assert by_profile["quality_regime_candidate"]["reason"] == "score_alpha_gate_failed"
    assert by_profile["quality_regime_candidate"]["gate_reasons"] == "no_gate_score_passed"
    assert by_profile["quality_regime_candidate_v2"]["reason"] == "score_alpha_missing"


def test_main_refreshes_score_alpha_before_promotion_review(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    daily_profile_dir = tmp_path / "daily_profiles"
    candidate_dir = daily_profile_dir / "quality_regime_candidate"
    backtest_dir.mkdir()
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "daily_20260414.csv").write_text("code,target_weight\n000001,0.1\n", encoding="utf-8")
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))
        if any("quant_score_alpha_diagnosis.py" in part for part in cmd):
            (backtest_dir / "quant_score_alpha_diagnosis_latest_quality_regime_candidate.json").write_text(
                "{}",
                encoding="utf-8",
            )

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(refresh, "DAILY_PROFILE_DIR", daily_profile_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--refresh-score-alpha",
        ],
    )

    rc = refresh.main()
    assert rc == 0
    assert len(calls) == 6
    score_cmd = calls[0][0]
    assert any("quant_score_alpha_diagnosis.py" in part for part in score_cmd)
    assert "--daily-glob" in score_cmd
    assert score_cmd[score_cmd.index("--label") + 1] == "quality_regime_candidate"
    assert any("quant_profile_rolling_compare.py" in part for part in calls[1][0])
    review_cmd = calls[-1][0]
    flag_idx = review_cmd.index("--score-alpha-diagnosis")
    assert review_cmd[flag_idx + 1] == str(backtest_dir / "quant_score_alpha_diagnosis_latest_quality_regime_candidate.json")


def test_precheck_score_alpha_prunes_failed_candidate_before_p2(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    backtest_dir.mkdir()
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                    "quality_regime_candidate_v2": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (backtest_dir / "quant_score_alpha_diagnosis_latest_quality_regime_candidate.json").write_text(
        json.dumps({"alpha_quality_gate": {"pass": True}}),
        encoding="utf-8",
    )
    (backtest_dir / "quant_score_alpha_diagnosis_latest_quality_regime_candidate_v2.json").write_text(
        json.dumps({"alpha_quality_gate": {"pass": False}}),
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--precheck-score-alpha",
        ],
    )

    rc = refresh.main()
    assert rc == 0
    expected_profiles = "quality_regime,quality_regime_candidate"
    for call_idx in [0, 1, 2, 3, 4]:
        cmd = calls[call_idx][0]
        if "--profiles" in cmd:
            assert cmd[cmd.index("--profiles") + 1] == expected_profiles
    report = json.loads((backtest_dir / "quant_score_alpha_precheck_latest.json").read_text(encoding="utf-8"))
    assert report["effective_profiles"] == ["quality_regime", "quality_regime_candidate"]
    assert report["skipped_profiles"] == ["quality_regime_candidate_v2"]
    report_rows = {str(row["profile"]): row for row in report["rows"]}
    assert report_rows["quality_regime_candidate_v2"]["reason"] == "score_alpha_gate_failed"
    assert (backtest_dir / "quant_score_alpha_precheck_latest.csv").exists()


def test_precheck_only_writes_report_and_skips_downstream(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    backtest_dir.mkdir()
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (backtest_dir / "quant_score_alpha_diagnosis_latest_quality_regime_candidate.json").write_text(
        json.dumps({"alpha_quality_gate": {"pass": False, "reasons": ["no_gate_score_passed"]}}),
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--precheck-only",
        ],
    )

    rc = refresh.main()
    assert rc == 0
    assert calls == []
    report = json.loads((backtest_dir / "quant_score_alpha_precheck_latest.json").read_text(encoding="utf-8"))
    assert report["effective_profiles"] == ["quality_regime"]
    assert report["skipped_profiles"] == ["quality_regime_candidate"]


def test_precheck_signal_coverage_prunes_sparse_candidate_before_p2(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    daily_profile_dir = tmp_path / "daily_profiles"
    sparse_dir = daily_profile_dir / "quality_regime_candidate_sparse"
    full_dir = daily_profile_dir / "quality_regime_candidate_full"
    backtest_dir.mkdir()
    sparse_dir.mkdir(parents=True)
    full_dir.mkdir(parents=True)
    (sparse_dir / "daily_20260401.csv").write_text("code,target_weight\n000001,0.1\n", encoding="utf-8")
    for i in range(1, 4):
        (full_dir / f"daily_2026040{i}.csv").write_text("code,target_weight\n000001,0.4\n", encoding="utf-8")
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate_sparse": {},
                    "quality_regime_candidate_full": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(refresh, "_load_market_trade_dates", lambda: ["20260401", "20260402", "20260403", "20260404"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-03",
            "--p2-windows",
            "60",
            "--precheck-signal-coverage",
            "--min-profile-signal-days",
            "3",
            "--profile-signal-root",
            str(daily_profile_dir),
        ],
    )

    rc = refresh.main()
    assert rc == 0
    expected_profiles = "quality_regime,quality_regime_candidate_full"
    for call_idx in [0, 1, 2, 3, 4]:
        cmd = calls[call_idx][0]
        if "--profiles" in cmd:
            assert cmd[cmd.index("--profiles") + 1] == expected_profiles
    report = json.loads((backtest_dir / "quant_signal_coverage_precheck_latest.json").read_text(encoding="utf-8"))
    assert report["effective_profiles"] == ["quality_regime", "quality_regime_candidate_full"]
    assert report["skipped_profiles"] == ["quality_regime_candidate_sparse"]


def test_fail_fast_p2_smoke_stops_after_failed_candidate(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    backtest_dir.mkdir()
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))
        if any("quant_p2_rolling_replay.py" in part for part in cmd):
            (backtest_dir / "p2_rolling_replay_summary_latest.csv").write_text(
                "profile,window,nav_return_pct,max_drawdown_pct,target_weight_sum_mean,run_failed_days,"
                "broker_entry_not_tradable_orders,broker_exit_not_tradable_orders\n"
                "quality_regime,60,1.2,-5.0,0.41,0,0,3\n"
                "quality_regime_candidate,60,-1.9,-7.7,0.34,0,0,7\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--p2-windows",
            "60,90,120",
            "--fail-fast-p2-smoke-window",
            "60",
            "--p2-execution-mode",
            "inprocess",
        ],
    )

    rc = refresh.main()
    assert rc == 0
    assert len(calls) == 4
    smoke_cmd = calls[0][0]
    assert any("quant_p2_rolling_replay.py" in part for part in smoke_cmd)
    assert smoke_cmd[smoke_cmd.index("--windows") + 1] == "60"
    assert smoke_cmd[smoke_cmd.index("--execution-mode") + 1] == "inprocess"
    diagnosis_cmd = calls[1][0]
    assert any("quant_p2_smoke_failure_diagnosis.py" in part for part in diagnosis_cmd)
    assert diagnosis_cmd[diagnosis_cmd.index("--profiles") + 1] == "quality_regime,quality_regime_candidate"
    assert diagnosis_cmd[diagnosis_cmd.index("--window") + 1] == "60"
    assert "--write-latest" in diagnosis_cmd
    day_cmd = calls[2][0]
    assert any("quant_p2_failure_day_attribution.py" in part for part in day_cmd)
    assert day_cmd[day_cmd.index("--profiles") + 1] == "quality_regime_candidate"
    assert day_cmd[day_cmd.index("--window") + 1] == "60"
    assert day_cmd[day_cmd.index("--worst-n") + 1] == "3"
    assert "--write-latest" in day_cmd
    holiday_cmd = calls[3][0]
    assert any("quant_p2_holiday_gap_guard_attribution.py" in part for part in holiday_cmd)
    assert holiday_cmd[holiday_cmd.index("--profiles") + 1] == "quality_regime_candidate"
    assert holiday_cmd[holiday_cmd.index("--windows") + 1] == "60"
    assert "--write-latest" in holiday_cmd
    report = json.loads((backtest_dir / "quant_p2_smoke_precheck_latest.json").read_text(encoding="utf-8"))
    assert report["effective_profiles"] == ["quality_regime"]
    assert report["skipped_profiles"] == ["quality_regime_candidate"]


def test_fail_fast_p2_smoke_runs_static_to_p2_when_capacity_daily_exists(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    backtest_dir.mkdir()
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {
                        "target_score_col": "portfolio_rank_score",
                        "capacity_safe_primary_label_score_col": "target_blend_score",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (backtest_dir / "quant_capacity_feasible_alpha_diagnosis_latest_quality_regime_candidate_daily.csv").write_text(
        "signal_date,score_col,primary_promotion_mode,selected_weighted_forward_return_pct\n"
        "2026-01-01,target_blend_score,keep,1.0\n",
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))
        if any("quant_p2_rolling_replay.py" in part for part in cmd):
            (backtest_dir / "p2_rolling_replay_summary_latest.csv").write_text(
                "profile,window,nav_return_pct,max_drawdown_pct,target_weight_sum_mean,run_failed_days,"
                "broker_entry_not_tradable_orders,broker_exit_not_tradable_orders\n"
                "quality_regime,60,1.2,-5.0,0.41,0,0,3\n"
                "quality_regime_candidate,60,-1.9,-7.7,0.34,0,0,7\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--p2-windows",
            "60,90,120",
            "--fail-fast-p2-smoke-window",
            "60",
        ],
    )

    rc = refresh.main()

    assert rc == 0
    static_cmd = calls[-1][0]
    assert any("quant_static_to_p2_pass_through_diagnosis.py" in part for part in static_cmd)
    assert static_cmd[static_cmd.index("--profile") + 1] == "quality_regime_candidate"
    assert static_cmd[static_cmd.index("--score-col") + 1] == "target_blend_score"
    assert static_cmd[static_cmd.index("--capacity-daily") + 1].endswith(
        "quant_capacity_feasible_alpha_diagnosis_latest_quality_regime_candidate_daily.csv"
    )


def test_reuse_rolling_latest_skips_rolling_compare_when_profiles_present(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    backtest_dir.mkdir()
    rolling_summary = backtest_dir / "quant_profile_rolling_compare_summary_latest.csv"
    rolling_summary.write_text(
        "profile,annual_return,sharpe,max_drawdown\n"
        "quality_regime,0.01,1.0,-0.02\n"
        "quality_regime_candidate,0.02,1.1,-0.03\n",
        encoding="utf-8",
    )
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--reuse-rolling-latest",
            "--rolling-summary",
            str(rolling_summary),
        ],
    )

    rc = refresh.main()
    assert rc == 0
    assert len(calls) == 4
    assert not any("quant_profile_rolling_compare.py" in part for cmd, _ in calls for part in cmd)
    assert any("quant_p2_rolling_replay.py" in part for part in calls[0][0])
    review_cmd = calls[-1][0]
    assert review_cmd[review_cmd.index("--rolling-summary") + 1] == str(rolling_summary.resolve())


def test_reuse_rolling_latest_fails_when_profile_missing(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    backtest_dir.mkdir()
    rolling_summary = backtest_dir / "quant_profile_rolling_compare_summary_latest.csv"
    rolling_summary.write_text(
        "profile,annual_return,sharpe,max_drawdown\nquality_regime,0.01,1.0,-0.02\n",
        encoding="utf-8",
    )
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--reuse-rolling-latest",
            "--rolling-summary",
            str(rolling_summary),
        ],
    )

    try:
        refresh.main()
    except RuntimeError as exc:
        assert "缺少 profile=quality_regime_candidate" in str(exc)
    else:
        raise AssertionError("expected missing profile RuntimeError")


def test_write_score_alpha_precheck_report_writes_latest_json_and_csv(tmp_path):
    json_path, csv_path = refresh._write_score_alpha_precheck_report(
        rows=[
            {
                "profile": "quality_regime",
                "decision": "keep",
                "is_main_profile": True,
                "score_alpha_file": "",
                "score_alpha_gate_pass": True,
                "reason": "main_profile_always_kept",
                "gate_reasons": "",
            }
        ],
        requested_profiles=["quality_regime"],
        effective_profiles=["quality_regime"],
        main_profile="quality_regime",
        backtest_dir=tmp_path,
    )

    assert json_path.exists()
    assert csv_path.exists()
    latest = json.loads((tmp_path / "quant_score_alpha_precheck_latest.json").read_text(encoding="utf-8"))
    assert latest["main_profile"] == "quality_regime"
    assert latest["effective_profiles"] == ["quality_regime"]
    assert (tmp_path / "quant_score_alpha_precheck_latest.csv").exists()


def test_refresh_score_alpha_does_not_attach_stale_file_without_profile_daily(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    backtest_dir = tmp_path / "backtest"
    daily_profile_dir = tmp_path / "daily_profiles"
    backtest_dir.mkdir()
    daily_profile_dir.mkdir()
    stale = backtest_dir / "quant_score_alpha_diagnosis_latest_quality_regime_candidate.json"
    stale.write_text("{}", encoding="utf-8")
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(refresh, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(refresh, "DAILY_PROFILE_DIR", daily_profile_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--refresh-score-alpha",
        ],
    )

    rc = refresh.main()
    assert rc == 0
    assert len(calls) == 5
    assert "--score-alpha-diagnosis" not in calls[-1][0]
