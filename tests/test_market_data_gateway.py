# -*- coding: utf-8 -*-
"""Contract tests for the canonical read-only A-share market-data gateway."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core.data.market_data_gateway import AShareMarketDataGateway


def _write_partition(
    root: Path,
    dataset: str,
    trade_date: str,
    rows: list[dict[str, object]],
    *,
    snapshot: str = "20260101T000000Z",
) -> None:
    part = root / "ods" / dataset / f"trade_date={trade_date}" / f"snapshot={snapshot}"
    part.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(part / "part-0000.parquet", index=False)
    (part / "manifest.json").write_text(json.dumps({"snapshot_id": snapshot}), encoding="utf-8")


def _bar_rows(trade_date: str, *, close: float = 10.0) -> list[dict[str, object]]:
    return [
        {
            "instrument_id": "000001.SZ",
            "trade_date": trade_date,
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.3,
            "close": close,
            "pre_close": close - 0.2,
            "pct_chg": 2.0,
            "volume": 100.0,
            "amount": 1000.0,
            "price_adjustment_type": "unadjusted",
        }
    ]


def test_available_market_sessions_intersects_calendar_and_daily_bars(tmp_path):
    _write_partition(
        tmp_path,
        "trading_calendar",
        "2026-01-01",
        [{"exchange": "SH", "trade_date": "2026-01-01", "is_trading_day": False}],
    )
    _write_partition(
        tmp_path,
        "trading_calendar",
        "2026-01-02",
        [{"exchange": "SH", "trade_date": "2026-01-02", "is_trading_day": True}],
    )
    _write_partition(
        tmp_path,
        "trading_calendar",
        "2026-01-05",
        [{"exchange": "SH", "trade_date": "2026-01-05", "is_trading_day": True}],
    )
    _write_partition(tmp_path, "daily_bars", "2026-01-05", _bar_rows("2026-01-05"))

    gateway = AShareMarketDataGateway(tmp_path)

    assert gateway.available_trade_dates("2026-01-01", "2026-01-05") == ["2026-01-05"]


def test_available_market_sessions_falls_back_to_complete_bar_partitions_when_calendar_is_sparse(tmp_path):
    _write_partition(
        tmp_path,
        "trading_calendar",
        "2026-01-02",
        [{"exchange": "SH", "trade_date": "2026-01-02", "is_trading_day": True}],
    )
    _write_partition(tmp_path, "daily_bars", "2026-01-02", _bar_rows("2026-01-02"))
    _write_partition(tmp_path, "daily_bars", "2026-01-05", _bar_rows("2026-01-05"))

    gateway = AShareMarketDataGateway(tmp_path)

    assert gateway.available_trade_dates("2026-01-02", "2026-01-05") == ["2026-01-02", "2026-01-05"]


def test_daily_bars_lineage_records_selected_snapshot(tmp_path):
    _write_partition(
        tmp_path,
        "daily_bars",
        "2026-01-05",
        _bar_rows("2026-01-05", close=10.0),
        snapshot="20260105T010000Z",
    )
    _write_partition(
        tmp_path,
        "daily_bars",
        "2026-01-05",
        _bar_rows("2026-01-05", close=11.0),
        snapshot="20260105T020000Z",
    )

    frame = AShareMarketDataGateway(tmp_path).load_bars("2026-01-05", "2026-01-05")

    assert frame.loc[0, "close"] == 11.0
    lineage = frame.attrs["market_data_lineage"]
    assert lineage["data_source"] == "ashare_ods"
    assert lineage["price_mode"] == "unadjusted"
    assert lineage["snapshot_count"] == 1
