"""Guard the completed retirement boundary for local market-data caches."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RETIRED_SOURCE_FILES = {
    "core/mfts_screener_v62.py",
    "data/data_adapter.py",
    "data/download_5y_data.py",
    "scripts/daily_incremental_update.py",
    "scripts/fix_missing_data.py",
    "scripts/fix_volume_unit_by_date.py",
    "scripts/repair_missing_ohlc.py",
    "scripts/repair_missing_volume.py",
    "scripts/research/daily_hybrid_select.py",
    "scripts/verify_historical.py",
    "utils/metadata_guard.py",
}


def test_local_legacy_market_data_has_been_removed():
    for relative_path in (
        "data/daily_all_5y.parquet",
        "data/stock_info.csv",
        "data/industry_map_cache.csv",
        "data/benchmarks/hs300_daily.csv",
    ):
        assert not (ROOT / relative_path).exists(), relative_path


def test_active_code_has_no_unclassified_legacy_market_path():
    hits = set()
    for base in ("config", "core", "scripts", "utils", "web", "data"):
        for path in (ROOT / base).rglob("*.py"):
            if "daily_all_5y.parquet" in path.read_text(encoding="utf-8") or "stock_info.csv" in path.read_text(encoding="utf-8"):
                hits.add(str(path.relative_to(ROOT)))

    expected = RETIRED_SOURCE_FILES | {
        "scripts/history/backtest_5y.py",
        "scripts/history/backtest_comparison.py",
        "scripts/history/backtest_mfts_6m.py",
        "scripts/history/backtest_v62_compare.py",
        "scripts/history/generate_historical_scans_6m.py",
    }
    assert hits == expected
