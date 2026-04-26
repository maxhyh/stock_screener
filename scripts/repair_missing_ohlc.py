#!/usr/bin/env python3
"""
修复主数据中指定交易日的 OHLC 缺失（重点修复 open 缺失）。

用法：
    python scripts/repair_missing_ohlc.py --dates 20260320 --apply
    python scripts/repair_missing_ohlc.py --dates 20260319,20260320 --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARQUET_FILE = os.path.join(BASE_DIR, "data", "daily_all_5y.parquet")


def normalize_trade_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str), errors="coerce").dt.strftime("%Y%m%d")


def normalize_ts_code(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.split(".").str[0]
    s = s.str.replace(r"[^0-9]", "", regex=True).str[-6:]
    return s.str.zfill(6)


def parse_dates_arg(text: str) -> list[str]:
    vals = [x.strip() for x in text.split(",") if x.strip()]
    out = []
    for v in vals:
        if len(v) != 8 or (not v.isdigit()):
            raise ValueError(f"无效日期: {v}，应为 YYYYMMDD")
        out.append(v)
    return sorted(set(out))


def summarize_missing(df: pd.DataFrame, dates: Iterable[str]) -> pd.DataFrame:
    sub = df[df["trade_date"].isin(list(dates))]
    if sub.empty:
        return pd.DataFrame(columns=["date", "rows", "open_na", "high_na", "low_na", "close_na"])
    g = sub.groupby("trade_date").agg(
        rows=("ts_code", "size"),
        open_na=("open", lambda s: s.isna().sum() + (s <= 0).sum()),
        high_na=("high", lambda s: s.isna().sum() + (s <= 0).sum()),
        low_na=("low", lambda s: s.isna().sum() + (s <= 0).sum()),
        close_na=("close", lambda s: s.isna().sum() + (s <= 0).sum()),
    )
    g = g.reset_index().rename(columns={"trade_date": "date"})
    return g


def repair_ohlc(df: pd.DataFrame, dates: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    work = df.copy()
    work = work.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    work["prev_close"] = work.groupby("ts_code")["close"].shift(1)

    mask = work["trade_date"].isin(dates)
    d = work[mask].copy()

    open_bad = d["open"].isna() | (d["open"] <= 0)
    fill_open_prev = open_bad & d["prev_close"].notna() & (d["prev_close"] > 0)
    fill_open_close = open_bad & (~fill_open_prev) & d["close"].notna() & (d["close"] > 0)
    d.loc[fill_open_prev, "open"] = d.loc[fill_open_prev, "prev_close"]
    d.loc[fill_open_close, "open"] = d.loc[fill_open_close, "close"]

    oc_max = d[["open", "close"]].max(axis=1)
    oc_min = d[["open", "close"]].min(axis=1)

    high_bad = d["high"].isna() | (d["high"] <= 0)
    low_bad = d["low"].isna() | (d["low"] <= 0)
    d.loc[high_bad & oc_max.notna(), "high"] = oc_max[high_bad & oc_max.notna()]
    d.loc[low_bad & oc_min.notna(), "low"] = oc_min[low_bad & oc_min.notna()]

    d["high"] = np.nanmax(np.vstack([d["high"].values, oc_max.values]), axis=0)
    d["low"] = np.nanmin(np.vstack([d["low"].values, oc_min.values]), axis=0)

    work.loc[mask, ["open", "high", "low"]] = d[["open", "high", "low"]].values
    work = work.drop(columns=["prev_close"], errors="ignore")

    stats = {
        "patched_open": int((fill_open_prev | fill_open_close).sum()),
        "patched_high": int(high_bad.sum()),
        "patched_low": int(low_bad.sum()),
    }
    return work, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="修复指定交易日OHLC缺失")
    parser.add_argument("--dates", type=str, required=True, help="日期列表，逗号分隔，格式 YYYYMMDD")
    parser.add_argument("--apply", action="store_true", help="执行写回；不加仅预览")
    args = parser.parse_args()

    dates = parse_dates_arg(args.dates)
    if not os.path.exists(PARQUET_FILE):
        print(f"❌ 数据文件不存在: {PARQUET_FILE}")
        return 1

    print(f"读取: {PARQUET_FILE}")
    df = pd.read_parquet(PARQUET_FILE, columns=["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"])
    df["trade_date"] = normalize_trade_date(df["trade_date"])
    df["ts_code"] = normalize_ts_code(df["ts_code"])
    for c in ["open", "high", "low", "close", "vol", "amount", "pct_chg"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    print("\n修复前:")
    before = summarize_missing(df, dates)
    print(before.to_string(index=False) if not before.empty else "  无目标日期数据")

    repaired, stats = repair_ohlc(df, dates)

    print("\n修复后:")
    after = summarize_missing(repaired, dates)
    print(after.to_string(index=False) if not after.empty else "  无目标日期数据")
    print(f"\n回填统计: open={stats['patched_open']}, high={stats['patched_high']}, low={stats['patched_low']}")

    if not args.apply:
        print("\n(预览模式) 未写回文件。加 --apply 执行落盘。")
        return 0

    repaired = repaired.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    repaired["ts_code"] = repaired["ts_code"].astype("category")
    repaired.to_parquet(PARQUET_FILE, index=False, compression="snappy")
    print(f"\n✅ 已写回: {PARQUET_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

