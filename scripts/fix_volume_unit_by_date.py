#!/usr/bin/env python3
"""
修复指定交易日成交量单位（股 -> 手）。

用法:
    python scripts/fix_volume_unit_by_date.py --date 20260319
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_FILE = BASE_DIR / "data" / "daily_all_5y.parquet"


def detect_ratio_median(df: pd.DataFrame) -> float | None:
    vol = pd.to_numeric(df["vol"], errors="coerce")
    amt = pd.to_numeric(df["amount"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    valid = (vol > 0) & (amt > 0) & (close > 0)
    if valid.sum() < 50:
        return None
    ratio = (amt[valid] / (vol[valid] * close[valid])).replace([np.inf, -np.inf], np.nan).dropna()
    if ratio.empty:
        return None
    return float(ratio.median())


def main() -> int:
    parser = argparse.ArgumentParser(description="修复指定日期成交量单位")
    parser.add_argument("--date", required=True, help="交易日 YYYYMMDD")
    parser.add_argument("--apply", action="store_true", help="执行修复（默认仅预览）")
    args = parser.parse_args()

    if not PARQUET_FILE.exists():
        print(f"❌ 数据文件不存在: {PARQUET_FILE}")
        return 1

    d = args.date
    print(f"读取数据: {PARQUET_FILE}")
    df = pd.read_parquet(PARQUET_FILE)
    date_str = pd.to_datetime(df["trade_date"].astype(str), errors="coerce").dt.strftime("%Y%m%d")
    mask = date_str == d
    day = df.loc[mask, ["vol", "amount", "close"]].copy()
    if day.empty:
        print(f"❌ 指定日期无数据: {d}")
        return 1

    ratio_median = detect_ratio_median(day)
    if ratio_median is None:
        print(f"❌ 样本不足，无法判定: {d}")
        return 1

    print(f"日期 {d} 样本数: {len(day)}")
    print(f"ratio中位数 amount/(vol*close): {ratio_median:.4f}")

    if ratio_median >= 20:
        print("✅ 单位看起来已是“手”，无需修复")
        return 0

    print("⚠️ 检测为“股”单位，建议转换为“手”（vol / 100）")
    if not args.apply:
        print("预览模式结束。加 --apply 执行修复。")
        return 0

    df.loc[mask, "vol"] = pd.to_numeric(df.loc[mask, "vol"], errors="coerce") / 100.0
    if "ts_code" in df.columns:
        df["ts_code"] = df["ts_code"].astype(str).str.split(".").str[0].str.zfill(6).astype("category")
    df.to_parquet(PARQUET_FILE, index=False, compression="snappy")
    print("✅ 修复已写回 parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
