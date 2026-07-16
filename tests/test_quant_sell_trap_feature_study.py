import pandas as pd

import scripts.quant_sell_trap_feature_study as study


def _sample_market() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2026-01-01", periods=28, freq="B")
    closes_a = [
        10.0,
        10.1,
        10.0,
        9.9,
        9.8,
        9.7,
        9.5,
        9.3,
        9.1,
        8.9,
        8.7,
        8.4,
        7.56,
        7.45,
        7.4,
        7.5,
        7.6,
        7.7,
        7.8,
        7.9,
        8.0,
        8.1,
        8.2,
        8.3,
        8.4,
        8.5,
        8.6,
        8.7,
    ]
    closes_b = [10.0 + i * 0.05 for i in range(len(dates))]
    for code, closes in [("000001", closes_a), ("000002", closes_b)]:
        prev = None
        for d, close in zip(dates, closes):
            prev_close = prev if prev is not None else close
            limit_down = prev_close * 0.90
            is_lock_down = code == "000001" and d == dates[12]
            op = limit_down if is_lock_down else close
            high = limit_down if is_lock_down else close * 1.01
            low = limit_down if is_lock_down else close * 0.99
            rows.append(
                {
                    "ts_code": f"{code}.SZ",
                    "trade_date": d.strftime("%Y%m%d"),
                    "open": op,
                    "high": high,
                    "low": low,
                    "close": close,
                    "vol": 100000.0,
                    "amount": 100000000.0,
                    "pct_chg": 0.0 if prev is None else (close / prev - 1.0) * 100.0,
                }
            )
            prev = close
    return pd.DataFrame(rows)


def test_prepare_feature_frame_labels_future_exit_block():
    frame = study.prepare_feature_frame(
        _sample_market(),
        horizon=2,
        days=0,
        exclude_bj9=True,
        require_full_horizon=True,
    )

    a = frame[frame["code"].eq("000001")].sort_values("trade_date")
    dates = pd.date_range("2026-01-01", periods=28, freq="B")
    assert "future_any_exit_block_h2" in frame.columns
    pre_block = a[a["trade_date"].eq(dates[10])]
    post_block = a[a["trade_date"].eq(dates[15])]
    assert int(pre_block.iloc[0]["future_any_exit_block_h2"]) == 1
    assert int(post_block.iloc[0]["future_any_exit_block_h2"]) == 0
    assert float(pre_block.iloc[0]["sell_pressure_pct"]) > 0


def test_locked_limit_down_does_not_treat_missing_vol_with_amount_as_suspended():
    rows = pd.DataFrame(
        [
            {
                "prev_close": 10.0,
                "open": 10.2,
                "high": 10.5,
                "low": 10.1,
                "vol": float("nan"),
                "amount": 100000.0,
                "limit_ratio": 0.10,
            }
        ]
    )

    assert bool(study._locked_limit_down(rows).iloc[0]) is False


def test_summarize_features_and_deciles():
    frame = study.prepare_feature_frame(
        _sample_market(),
        horizon=2,
        days=0,
        exclude_bj9=True,
        require_full_horizon=True,
    )
    summary = study.summarize_features(
        frame,
        label_col="future_any_exit_block_h2",
        features=["sell_pressure_pct", "near_down_limit_risk"],
    )
    deciles = study.build_decile_table(
        frame,
        label_col="future_any_exit_block_h2",
        features=["sell_pressure_pct"],
    )

    assert set(summary["feature"]) == {"sell_pressure_pct", "near_down_limit_risk"}
    assert "spearman_label_corr" in summary.columns
    # Small synthetic sample is below the production decile minimum.
    assert deciles.empty
