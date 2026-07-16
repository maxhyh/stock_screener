from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_active_training_and_daily_entrypoints_do_not_default_to_legacy_market_file():
    """Active production entrypoints must default to the read-only shared ODS."""
    for relative_path in (
        "config/settings.py",
        "core/mfts_screener.py",
        "scripts/project_doctor.py",
        "scripts/platform_profile_baseline.py",
        "scripts/backtest_mfts_lite.py",
        "scripts/train_mfts_lgbm.py",
        "scripts/auto_retrain.py",
        "scripts/daily_mfts_select.py",
        "scripts/analyze_signal_performance.py",
        "scripts/research/analyze_factor_ic.py",
        "scripts/research/capacity_estimation.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "daily_all_5y.parquet" not in source
