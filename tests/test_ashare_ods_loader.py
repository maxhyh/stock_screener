# -*- coding: utf-8 -*-
"""Read-only ODS data source adapter tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core.data.ashare_ods_loader import (
    AShareOdsLoader,
    get_ashare_data_root,
    normalize_ods_trade_date,
)


def _write_partition(
    root: Path,
    dataset: str,
    trade_date: str,
    snapshot: str,
    rows: list[dict],
) -> None:
    part_dir = root / "ods" / dataset / f"trade_date={trade_date}" / f"snapshot={snapshot}"
    part_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(part_dir / "part-0000.parquet", index=False)
    (part_dir / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_name": dataset,
                "truth_source_layer": "ods",
                "trade_date": trade_date,
                "snapshot_id": snapshot,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_get_ashare_data_root_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ASHARE_DATA_ROOT", str(tmp_path))

    assert get_ashare_data_root() == tmp_path


def test_normalize_ods_trade_date_accepts_project_formats():
    assert normalize_ods_trade_date("20260715") == "2026-07-15"
    assert normalize_ods_trade_date("2026-07-15") == "2026-07-15"
    assert normalize_ods_trade_date(pd.Timestamp("2026-07-15")) == "2026-07-15"


def test_loader_uses_latest_snapshot_and_maps_to_legacy_panel(tmp_path):
    root = tmp_path / "ashare-source-data"
    _write_partition(
        root,
        "daily_bars",
        "2026-07-15",
        "20260715T010000Z",
        [
            {
                "instrument_id": "000001.SZ",
                "trade_date": "2026-07-15",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "pre_close": 10.0,
                "price_change": 0.2,
                "pct_chg": 2.0,
                "volume": 100.0,
                "amount": 1000.0,
                "price_adjustment_type": "none",
            }
        ],
    )
    _write_partition(
        root,
        "daily_bars",
        "2026-07-15",
        "20260715T020000Z",
        [
            {
                "instrument_id": "000001.SZ",
                "trade_date": "2026-07-15",
                "open": 11.0,
                "high": 11.5,
                "low": 10.8,
                "close": 11.2,
                "pre_close": 11.0,
                "price_change": 0.2,
                "pct_chg": 1.818,
                "volume": 200.0,
                "amount": 2200.0,
                "price_adjustment_type": "none",
            },
            {
                "instrument_id": "920001.BJ",
                "trade_date": "2026-07-15",
                "open": 5.0,
                "high": 5.5,
                "low": 4.8,
                "close": 5.2,
                "pre_close": 5.0,
                "price_change": 0.2,
                "pct_chg": 4.0,
                "volume": 50.0,
                "amount": 260.0,
                "price_adjustment_type": "none",
            },
        ],
    )
    _write_partition(
        root,
        "daily_basic",
        "2026-07-15",
        "20260715T020001Z",
        [
            {
                "instrument_id": "000001.SZ",
                "trade_date": "2026-07-15",
                "turnover_rate": 1.2,
                "total_mv": 100000.0,
                "circ_mv": 90000.0,
            },
            {
                "instrument_id": "920001.BJ",
                "trade_date": "2026-07-15",
                "turnover_rate": 3.4,
                "total_mv": 5000.0,
                "circ_mv": 4500.0,
            },
        ],
    )
    _write_partition(
        root,
        "daily_adj_factor",
        "2026-07-15",
        "20260715T020002Z",
        [
            {"instrument_id": "000001.SZ", "trade_date": "2026-07-15", "adj_factor": 1.1},
            {"instrument_id": "920001.BJ", "trade_date": "2026-07-15", "adj_factor": 1.0},
        ],
    )
    _write_partition(
        root,
        "daily_limits",
        "2026-07-15",
        "20260715T020003Z",
        [
            {"instrument_id": "000001.SZ", "trade_date": "2026-07-15", "up_limit": 12.1, "down_limit": 9.9},
            {"instrument_id": "920001.BJ", "trade_date": "2026-07-15", "up_limit": 6.5, "down_limit": 3.5},
        ],
    )
    _write_partition(
        root,
        "instrument_master",
        "2026-07-14",
        "20260715T020004Z",
        [
            {
                "instrument_id": "000001.SZ",
                "ticker": "000001",
                "exchange": "SZ",
                "display_name": "平安银行",
                "board": "主板",
                "industry": "银行",
                "list_status": "L",
            },
            {
                "instrument_id": "920001.BJ",
                "ticker": "920001",
                "exchange": "BJ",
                "display_name": "北交测试",
                "board": "北交所",
                "industry": "测试",
                "list_status": "L",
            },
        ],
    )

    loader = AShareOdsLoader(root)
    panel = loader.load_daily_panel("20260715", "20260715", include_bj9=False)

    assert panel["ts_code"].tolist() == ["000001.SZ"]
    row = panel.iloc[0]
    assert row["trade_date"] == pd.Timestamp("2026-07-15")
    assert float(row["open"]) == 11.0
    assert float(row["vol"]) == 200.0
    assert float(row["amount"]) == 2200.0
    assert float(row["turnover_rate"]) == 1.2
    assert float(row["adj_factor"]) == 1.1
    assert float(row["up_limit"]) == 12.1
    assert row["name"] == "平安银行"
    assert row["industry"] == "银行"


def test_loader_can_include_bj9_when_explicitly_requested(tmp_path):
    root = tmp_path / "ashare-source-data"
    _write_partition(
        root,
        "daily_bars",
        "2026-07-15",
        "snapshot-a",
        [
            {
                "instrument_id": "920001.BJ",
                "trade_date": "2026-07-15",
                "open": 5.0,
                "high": 5.5,
                "low": 4.8,
                "close": 5.2,
                "pct_chg": 4.0,
                "volume": 50.0,
                "amount": 260.0,
            }
        ],
    )

    panel = AShareOdsLoader(root).load_daily_panel("2026-07-15", "2026-07-15", include_bj9=True)

    assert panel["ts_code"].tolist() == ["920001.BJ"]
    assert float(panel.loc[0, "vol"]) == 50.0
