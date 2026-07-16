# -*- coding: utf-8 -*-
"""Raw model walk-forward diagnosis helper tests."""

from __future__ import annotations

import pandas as pd
import pytest

import scripts.quant_raw_model_walkforward_diagnosis as diag


def _make_ods_snapshot_dir(root, trade_date, snapshot):
    (root / "ods" / "daily_bars" / f"trade_date={trade_date}" / f"snapshot={snapshot}").mkdir(
        parents=True,
        exist_ok=True,
    )


def test_calc_open_to_open_labels_uses_next_open_entry_and_horizon_exit():
    raw = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "ts_code": ["000001.SZ"] * 4,
            "open": [10.0, 11.0, 12.1, 13.31],
        }
    )

    out = diag._calc_open_to_open_labels(raw, [1, 2])

    assert out.loc[0, "label_h1"] == (12.1 / 11.0 - 1.0) * 100.0
    assert out.loc[0, "label_h2"] == (13.31 / 11.0 - 1.0) * 100.0
    assert pd.isna(out.loc[2, "label_h1"])


def test_iter_windows_allows_partial_final_test():
    windows = list(
        diag._iter_windows(
            pd.Timestamp("2022-01-01"),
            pd.Timestamp("2022-08-15"),
            train_months=4,
            test_months=3,
            step_months=3,
            allow_partial_final_test=True,
        )
    )

    assert len(windows) == 2
    assert windows[-1]["partial_final_test"] is True
    assert windows[-1]["test_end"] == pd.Timestamp("2022-08-15")


def test_summarize_predictions_detects_alpha_gate_pass():
    rows = []
    for d in pd.date_range("2026-01-01", periods=3):
        for i in range(40):
            rows.append(
                {
                    "trade_date": d,
                    "ts_code": f"{i:06d}.SZ",
                    "pred": float(i),
                    "label": float(i - 20) / 100.0,
                }
            )
    df = pd.DataFrame(rows)

    out = diag.summarize_predictions(df, top_n=5, direction="desc")

    assert out["alpha_gate_pass"] is True
    assert out["top_mean_return_pct"] > out["all_mean_return_pct"]
    assert out["rank_ic_mean"] > 0


def test_build_overall_verdict_rejects_desc_fail_and_accepts_asc_issue():
    summary = pd.DataFrame(
        [
            {
                "horizon": 8,
                "score_direction": "desc",
                "alpha_gate_pass": False,
                "fold_pass_rate_pct": 0.0,
                "rank_ic_mean": -0.1,
                "top_minus_bottom_pct": -1.0,
                "top_mean_return_pct": -0.5,
                "top_minus_all_pct": -0.5,
            },
            {
                "horizon": 8,
                "score_direction": "asc",
                "alpha_gate_pass": True,
                "fold_pass_rate_pct": 60.0,
                "rank_ic_mean": 0.1,
                "top_minus_bottom_pct": 1.0,
                "top_mean_return_pct": 0.5,
                "top_minus_all_pct": 0.4,
            },
        ]
    )

    out = diag.build_overall_verdict(summary, min_fold_pass_rate_pct=50.0)

    assert out["overall_verdict"] == "score_sign_or_objective_issue"
    assert out["passed_horizons_asc"] == "8"


def test_load_raw_market_panel_rejects_legacy_market_file_mode(tmp_path):
    with pytest.raises(ValueError, match="ashare_ods"):
        diag.load_raw_market_panel(
            data_file=tmp_path / "obsolete.parquet",
            start="2026-01-02",
            end="2026-01-02",
            include_bj9=False,
            data_source="legacy",
        )


def test_load_raw_market_panel_routes_ods_through_loader(monkeypatch, tmp_path):
    expected = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": [pd.Timestamp("2026-01-02")],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "vol": [100.0],
            "amount": [1000.0],
            "pct_chg": [1.0],
        }
    )
    calls = {}

    class FakeLoader:
        def __init__(self, root=None):
            calls["root"] = root
            self.data_root = root

        def load_daily_panel(self, start, end, include_bj9):
            calls.update(start=start, end=end, include_bj9=include_bj9)
            return expected.copy()

    monkeypatch.setattr(diag, "AShareOdsLoader", FakeLoader)

    out, meta = diag.load_raw_market_panel(
        data_file=tmp_path / "unused.parquet",
        data_source="ashare_ods",
        start="2026-01-02",
        end="2026-01-03",
        include_bj9=True,
        ashare_data_root="/shared/ods",
    )

    pd.testing.assert_frame_equal(out, expected)
    assert calls == {
        "root": "/shared/ods",
        "start": "2026-01-02",
        "end": "2026-01-03",
        "include_bj9": True,
    }
    assert meta["data_source"] == "ashare_ods"
    assert meta["snapshot_policy"] == "latest_snapshot_per_trade_date"


def test_raw_model_frame_cache_request_is_bound_to_ods_snapshots(tmp_path):
    data_file = tmp_path / "daily.parquet"
    data_file.write_bytes(b"legacy")
    ods_root = tmp_path / "ods-root"
    for date in ["2026-01-01", "2026-01-02", "2026-01-05"]:
        _make_ods_snapshot_dir(ods_root, date, "snapshot-a")

    ods = diag._raw_model_frame_cache_request(
        data_file=data_file,
        data_source="ashare_ods",
        ashare_data_root=str(ods_root),
        features=["x"],
        horizons=[8],
        start="2026-01-01",
        end="2026-01-31",
        exclude_bj9=True,
    )

    assert ods["data_source"] == "ashare_ods"
    assert ods["market_data_input"] == "ashare_ods"
    assert ods["ashare_data_root"] == str(ods_root.resolve())
    assert ods["ods_daily_bars_snapshot_count"] == 3


def test_ods_cache_request_changes_when_latest_daily_bars_snapshot_changes(tmp_path):
    data_file = tmp_path / "daily.parquet"
    data_file.write_bytes(b"legacy")
    ods_root = tmp_path / "ods-root"
    for date in ["2026-01-01", "2026-01-02", "2026-01-05"]:
        _make_ods_snapshot_dir(ods_root, date, "snapshot-a")

    one = diag._raw_model_frame_cache_request(
        data_file=data_file,
        data_source="ashare_ods",
        ashare_data_root=str(ods_root),
        features=["x"],
        horizons=[8],
        start="2026-01-01",
        end="2026-01-02",
        exclude_bj9=True,
    )
    _make_ods_snapshot_dir(ods_root, "2026-01-02", "snapshot-z")
    two = diag._raw_model_frame_cache_request(
        data_file=data_file,
        data_source="ashare_ods",
        ashare_data_root=str(ods_root),
        features=["x"],
        horizons=[8],
        start="2026-01-01",
        end="2026-01-02",
        exclude_bj9=True,
    )

    assert one["ods_daily_bars_snapshot_digest"] != two["ods_daily_bars_snapshot_digest"]


def test_summarize_raw_panel_reports_date_code_and_required_column_coverage():
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ"],
            "trade_date": pd.to_datetime(["2026-01-02", "2026-01-02"]),
            "open": [10.0, 20.0],
            "high": [11.0, 21.0],
            "low": [9.0, 19.0],
            "close": [10.5, 20.5],
            "vol": [100.0, 200.0],
            "amount": [1000.0, 2000.0],
            "pct_chg": [1.0, 2.0],
        }
    )

    out = diag.summarize_raw_panel(frame)

    assert out["rows"] == 2
    assert out["trade_dates"] == 1
    assert out["unique_codes"] == 2
    assert out["required_column_null_rows"] == 0
    assert out["missing_required_columns"] == []


def test_resolve_ods_market_window_keeps_feature_warmup_and_label_buffer():
    dates = pd.bdate_range("2025-01-01", periods=280).strftime("%Y-%m-%d").tolist()

    class FakeLoader:
        def available_trade_dates(self, dataset):
            assert dataset == "daily_bars"
            return dates

    start, end = diag.resolve_ods_market_window(
        FakeLoader(),
        start=dates[252],
        end=dates[254],
        horizons=[8, 10],
    )

    assert start == dates[0]
    assert end == dates[265]


def test_load_raw_model_frame_cached_reuses_valid_metadata(tmp_path):
    data_file = tmp_path / "daily.parquet"
    data_file.write_bytes(b"market-data-placeholder")
    cache_file = tmp_path / "raw_frame.parquet"
    calls = {"n": 0}

    def builder(**kwargs):
        calls["n"] += 1
        return pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2026-01-02"]),
                "ts_code": ["000001.SZ"],
                "x": [1.25],
                "label_h10": [0.50],
            }
        )

    one, meta_one = diag.load_raw_model_frame_cached(
        data_file=data_file,
        features=["x"],
        horizons=[10],
        start="2026-01-01",
        end="2026-01-31",
        exclude_bj9=True,
        cache_file=str(cache_file),
        builder=builder,
    )
    two, meta_two = diag.load_raw_model_frame_cached(
        data_file=data_file,
        features=["x"],
        horizons=[10],
        start="2026-01-01",
        end="2026-01-31",
        exclude_bj9=True,
        cache_file=str(cache_file),
        builder=builder,
    )

    assert calls["n"] == 1
    assert meta_one["cache_hit"] is False
    assert meta_two["cache_hit"] is True
    pd.testing.assert_frame_equal(one, two)


def test_load_raw_model_frame_cached_invalidates_when_request_changes(tmp_path):
    data_file = tmp_path / "daily.parquet"
    data_file.write_bytes(b"market-data-placeholder")
    cache_file = tmp_path / "raw_frame.parquet"
    calls = {"n": 0}

    def builder(**kwargs):
        calls["n"] += 1
        return pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2026-01-02"]),
                "ts_code": ["000001.SZ"],
                "x": [float(calls["n"])],
                "label_h10": [0.50],
            }
        )

    diag.load_raw_model_frame_cached(
        data_file=data_file,
        features=["x"],
        horizons=[10],
        start="2026-01-01",
        end="2026-01-31",
        exclude_bj9=True,
        cache_file=str(cache_file),
        builder=builder,
    )
    _, meta_two = diag.load_raw_model_frame_cached(
        data_file=data_file,
        features=["x", "y"],
        horizons=[10],
        start="2026-01-01",
        end="2026-01-31",
        exclude_bj9=True,
        cache_file=str(cache_file),
        builder=builder,
    )

    assert calls["n"] == 2
    assert meta_two["cache_hit"] is False
