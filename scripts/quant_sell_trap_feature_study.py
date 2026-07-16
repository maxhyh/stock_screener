#!/usr/bin/env python3
"""Full-universe sell-trap feature study using signal-date-known fields."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.code_utils import limit_ratio_vectorized, normalize_ts_code_series
from utils.market_data_units import normalize_amount_volume_units
from core.data import AShareMarketDataGateway


BACKTEST_DIR = BASE_DIR / "output" / "backtest"

DEFAULT_FEATURES = [
    "near_down_limit_risk",
    "sell_pressure_pct",
    "low_touch_risk",
    "low_liquidity_risk",
    "vol_ratio_low_risk",
    "vol_ratio_high_risk",
    "down_momentum_3d",
    "down_momentum_5d",
    "drawdown_10d_pct",
    "volatility_10d",
    "pct_chg",
    "downside_headroom_pct",
    "amount_date_pct_rank",
]


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _parse_date(raw: str | None) -> pd.Timestamp | None:
    if not str(raw or "").strip():
        return None
    dt = pd.to_datetime(str(raw), errors="coerce")
    return pd.Timestamp(dt).normalize() if pd.notna(dt) else None


def _locked_limit_down(df: pd.DataFrame) -> pd.Series:
    prev_close = pd.to_numeric(df["prev_close"], errors="coerce")
    op = pd.to_numeric(df["open"], errors="coerce")
    hi = pd.to_numeric(df["high"], errors="coerce")
    lo = pd.to_numeric(df["low"], errors="coerce")
    vol = pd.to_numeric(df["vol"], errors="coerce")
    amount = pd.to_numeric(df["amount"], errors="coerce")
    limit_ratio = pd.to_numeric(df["limit_ratio"], errors="coerce").fillna(0.10).abs()
    traded_value_seen = amount.gt(0) | vol.gt(0)
    suspended = op.le(0) | op.isna() | (~traded_value_seen.fillna(False))
    limit_down = prev_close * (1.0 - limit_ratio)
    locked_down = (
        prev_close.gt(0)
        & limit_down.gt(0)
        & op.le(limit_down * 1.001)
        & hi.le(limit_down * 1.001)
        & lo.le(limit_down * 1.001)
    )
    return (suspended | locked_down).fillna(False)


def load_market_frame(
    data_file: Path | None = None,
    *,
    start: object | None = None,
    end: object | None = None,
    days: int = 520,
    horizon: int = 5,
    include_bj9: bool = False,
) -> pd.DataFrame:
    """Load an explicit inspection file or a bounded shared-ODS study window."""
    cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"]
    if data_file is not None:
        df = pd.read_parquet(data_file, columns=cols)
    else:
        gateway = AShareMarketDataGateway()
        sessions = gateway.available_trade_dates()
        if not sessions:
            return pd.DataFrame(columns=cols)
        end_date = pd.Timestamp(end).strftime("%Y-%m-%d") if end is not None else sessions[-1]
        eligible = [date for date in sessions if date <= end_date]
        if not eligible:
            return pd.DataFrame(columns=cols)
        end_date = eligible[-1]
        if start is not None:
            start_date = pd.Timestamp(start).strftime("%Y-%m-%d")
        else:
            required = max(30, int(days) + int(horizon) + 25)
            start_date = eligible[max(0, len(eligible) - required)]
        df = gateway.load_bars(start_date, end_date, include_bj9=bool(include_bj9), forward_sessions=max(0, int(horizon)))
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="coerce").dt.normalize()
    df["code"] = normalize_ts_code_series(df["ts_code"])
    for col in ["open", "high", "low", "close", "vol", "amount", "pct_chg"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = normalize_amount_volume_units(df)
    df = df[df["trade_date"].notna() & df["code"].astype(str).ne("")].copy()
    return df.sort_values(["code", "trade_date"]).reset_index(drop=True)


def prepare_feature_frame(
    df: pd.DataFrame,
    *,
    horizon: int = 5,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    days: int = 520,
    exclude_bj9: bool = True,
    require_full_horizon: bool = True,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    horizon = max(1, int(horizon))
    work = df.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work["code"] = normalize_ts_code_series(work.get("code", work.get("ts_code", pd.Series("", index=work.index))))
    work = work[work["trade_date"].notna() & work["code"].astype(str).ne("")].copy()
    if exclude_bj9:
        work = work[~work["code"].astype(str).str.startswith(("4", "8", "9"))].copy()
    work = work.sort_values(["code", "trade_date"]).reset_index(drop=True)
    if work.empty:
        return work

    for col in ["open", "high", "low", "close", "vol", "amount", "pct_chg"]:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work["limit_ratio"] = pd.Series(limit_ratio_vectorized(work["code"], None), index=work.index, dtype=float)

    g = work.groupby("code", group_keys=False)
    work["prev_close"] = g["close"].shift(1)
    work["ret_3d_pct"] = (work["close"] / g["close"].shift(3) - 1.0) * 100.0
    work["ret_5d_pct"] = (work["close"] / g["close"].shift(5) - 1.0) * 100.0
    work["amount_ma20"] = g["amount"].transform(lambda s: s.rolling(20, min_periods=5).mean())
    work["vol_ma20"] = g["vol"].transform(lambda s: s.rolling(20, min_periods=5).mean())
    work["vol_ratio"] = work["vol"] / work["vol_ma20"].replace(0, np.nan)
    work["rolling_max_10"] = g["close"].transform(lambda s: s.rolling(10, min_periods=3).max())
    work["drawdown_10d_pct"] = (1.0 - work["close"] / work["rolling_max_10"].replace(0, np.nan)).clip(lower=0.0) * 100.0
    work["volatility_10d"] = g["pct_chg"].transform(lambda s: s.rolling(10, min_periods=5).std()).fillna(0.0)

    limit_down = work["prev_close"] * (1.0 - work["limit_ratio"])
    valid_down = work["close"].gt(0) & work["prev_close"].gt(0) & limit_down.gt(0)
    work["downside_headroom_pct"] = 0.0
    work.loc[valid_down, "downside_headroom_pct"] = (
        (work.loc[valid_down, "close"] - limit_down.loc[valid_down]) / work.loc[valid_down, "close"] * 100.0
    )
    work["downside_headroom_pct"] = work["downside_headroom_pct"].replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    work["near_down_limit_risk"] = (1.0 - (work["downside_headroom_pct"] / 3.5).clip(0.0, 1.0)).clip(0.0, 1.0)
    work["sell_pressure_pct"] = (-work["pct_chg"].clip(upper=0.0)).clip(lower=0.0)
    work["low_touch_risk"] = (valid_down & work["low"].le(limit_down * 1.015)).astype(float)
    work["down_momentum_3d"] = (-work["ret_3d_pct"].clip(upper=0.0)).fillna(0.0)
    work["down_momentum_5d"] = (-work["ret_5d_pct"].clip(upper=0.0)).fillna(0.0)
    work["vol_ratio_low_risk"] = (1.0 - (work["vol_ratio"] / 0.30).clip(0.0, 1.0)).fillna(0.0)
    work["vol_ratio_high_risk"] = ((work["vol_ratio"] / 3.0) - 1.0).clip(0.0, 1.0).fillna(0.0)
    work["amount_date_pct_rank"] = work.groupby("trade_date")["amount_ma20"].rank(pct=True).fillna(0.0)
    work["low_liquidity_risk"] = (1.0 - work["amount_date_pct_rank"]).clip(0.0, 1.0)

    work["exit_blocked_open"] = _locked_limit_down(work).astype(int)
    valid_future_cols: list[str] = []
    block_future_cols: list[str] = []
    for lag in range(1, horizon + 1):
        future_date = g["trade_date"].shift(-lag)
        future_block = g["exit_blocked_open"].shift(-lag)
        vcol = f"future_valid_lag{lag}"
        bcol = f"future_exit_blocked_lag{lag}"
        work[vcol] = future_date.notna().astype(int)
        work[bcol] = pd.to_numeric(future_block, errors="coerce").fillna(0).astype(int)
        valid_future_cols.append(vcol)
        block_future_cols.append(bcol)
    work["future_available_days"] = work[valid_future_cols].sum(axis=1)
    label_col = f"future_any_exit_block_h{horizon}"
    work[label_col] = work[block_future_cols].max(axis=1).astype(int)

    if days and int(days) > 0 and end is None:
        date_list = sorted(work["trade_date"].dropna().unique())
        if date_list:
            keep_dates = set(date_list[-int(days) :])
            work = work[work["trade_date"].isin(keep_dates)].copy()
    if start is not None:
        work = work[work["trade_date"] >= pd.Timestamp(start)].copy()
    if end is not None:
        work = work[work["trade_date"] <= pd.Timestamp(end)].copy()
    if require_full_horizon:
        work = work[work["future_available_days"] >= horizon].copy()

    needed = ["prev_close", "amount_ma20", "vol_ma20"]
    for col in needed:
        work = work[pd.to_numeric(work[col], errors="coerce").notna()].copy()
    return work.reset_index(drop=True)


def summarize_features(frame: pd.DataFrame, *, label_col: str, features: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    label = pd.to_numeric(frame[label_col], errors="coerce").fillna(0).astype(int)
    for feature in features:
        if feature not in frame.columns:
            continue
        values = pd.to_numeric(frame[feature], errors="coerce")
        valid = values.notna() & label.notna()
        if int(valid.sum()) <= 10:
            continue
        blocked_vals = values[valid & label.eq(1)]
        normal_vals = values[valid & label.eq(0)]
        corr = values[valid].corr(label[valid], method="spearman")
        rows.append(
            {
                "feature": feature,
                "coverage_pct": float(valid.mean() * 100.0),
                "blocked_mean": float(blocked_vals.mean()) if len(blocked_vals) else np.nan,
                "normal_mean": float(normal_vals.mean()) if len(normal_vals) else np.nan,
                "blocked_median": float(blocked_vals.median()) if len(blocked_vals) else np.nan,
                "normal_median": float(normal_vals.median()) if len(normal_vals) else np.nan,
                "mean_delta_blocked_minus_normal": float(blocked_vals.mean() - normal_vals.mean())
                if len(blocked_vals) and len(normal_vals)
                else np.nan,
                "spearman_label_corr": float(corr) if pd.notna(corr) else 0.0,
                "abs_spearman_label_corr": float(abs(corr)) if pd.notna(corr) else 0.0,
            }
        )
    out = pd.DataFrame(rows)
    return out.sort_values("abs_spearman_label_corr", ascending=False).reset_index(drop=True) if not out.empty else out


def build_decile_table(frame: pd.DataFrame, *, label_col: str, features: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    label = pd.to_numeric(frame[label_col], errors="coerce").fillna(0).astype(int)
    for feature in features:
        if feature not in frame.columns:
            continue
        values = pd.to_numeric(frame[feature], errors="coerce")
        valid = values.notna()
        if int(valid.sum()) < 100:
            continue
        try:
            decile = pd.qcut(values[valid].rank(method="first"), 10, labels=False, duplicates="drop") + 1
        except Exception:
            continue
        tmp = pd.DataFrame({"decile": decile.astype(int), "label": label.loc[valid].astype(int), "value": values.loc[valid]})
        for d, g in tmp.groupby("decile"):
            rows.append(
                {
                    "feature": feature,
                    "decile": int(d),
                    "rows": int(len(g)),
                    "label_rate_pct": float(g["label"].mean() * 100.0),
                    "value_min": float(g["value"].min()),
                    "value_max": float(g["value"].max()),
                    "value_mean": float(g["value"].mean()),
                }
            )
    return pd.DataFrame(rows)


def main() -> int:
    p = argparse.ArgumentParser(description="Full-universe sell-trap feature study")
    p.add_argument("--data-file", type=str, default="", help="optional explicit market parquet; default is shared ODS")
    p.add_argument("--start", type=str, default="")
    p.add_argument("--end", type=str, default="")
    p.add_argument("--days", type=int, default=520)
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--include-bj9", action="store_true")
    p.add_argument("--features", type=str, default=",".join(DEFAULT_FEATURES))
    p.add_argument("--write-latest", action="store_true")
    args = p.parse_args()

    horizon = max(1, int(args.horizon))
    df = load_market_frame(
        Path(args.data_file).resolve() if args.data_file else None,
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        days=int(args.days),
        horizon=horizon,
        include_bj9=bool(args.include_bj9),
    )
    frame = prepare_feature_frame(
        df,
        horizon=horizon,
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        days=int(args.days),
        exclude_bj9=not bool(args.include_bj9),
    )
    label_col = f"future_any_exit_block_h{horizon}"
    features = [x.strip() for x in str(args.features or "").split(",") if x.strip()]
    summary = summarize_features(frame, label_col=label_col, features=features)
    deciles = build_decile_table(frame, label_col=label_col, features=features)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    feature_path = BACKTEST_DIR / f"quant_sell_trap_feature_summary_{ts}.csv"
    decile_path = BACKTEST_DIR / f"quant_sell_trap_feature_deciles_{ts}.csv"
    meta_path = BACKTEST_DIR / f"quant_sell_trap_feature_meta_{ts}.json"
    summary.to_csv(feature_path, index=False)
    deciles.to_csv(decile_path, index=False)
    meta = {
        "rows": int(len(frame)),
        "codes": int(frame["code"].nunique()) if "code" in frame.columns else 0,
        "start": str(frame["trade_date"].min().date()) if not frame.empty else "",
        "end": str(frame["trade_date"].max().date()) if not frame.empty else "",
        "horizon": int(horizon),
        "label_col": label_col,
        "label_rate_pct": float(pd.to_numeric(frame.get(label_col, pd.Series(dtype=float)), errors="coerce").mean() * 100.0)
        if not frame.empty
        else 0.0,
        "exclude_bj9": not bool(args.include_bj9),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        summary.to_csv(BACKTEST_DIR / "quant_sell_trap_feature_summary_latest.csv", index=False)
        deciles.to_csv(BACKTEST_DIR / "quant_sell_trap_feature_deciles_latest.csv", index=False)
        (BACKTEST_DIR / "quant_sell_trap_feature_meta_latest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"sell-trap feature summary: {feature_path}")
    print(f"sell-trap feature deciles: {decile_path}")
    print(f"sell-trap feature meta: {meta_path}")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if not summary.empty:
        print(summary.head(12).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
