#!/usr/bin/env python3
"""
修复历史数据中缺失/无效成交量(vol)：
使用 amount/(close*100) 估算 vol（单位：手）。

用法:
    python scripts/repair_missing_volume.py
"""

import os
import sys
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARQUET_FILE = os.path.join(BASE_DIR, "data", "daily_all_5y.parquet")


def main():
    if not os.path.exists(PARQUET_FILE):
        print(f"❌ 文件不存在: {PARQUET_FILE}")
        return 1

    print(f"读取: {PARQUET_FILE}")
    df = pd.read_parquet(PARQUET_FILE)

    for col in ["close", "amount", "vol"]:
        if col not in df.columns:
            print(f"❌ 缺少列: {col}")
            return 1
        df[col] = pd.to_numeric(df[col], errors="coerce")

    miss_vol = df["vol"].isna() | (df["vol"] <= 0)
    fillable = miss_vol & df["amount"].notna() & (df["amount"] > 0) & df["close"].notna() & (df["close"] > 0)
    fill_count = int(fillable.sum())
    total_miss = int(miss_vol.sum())

    print(f"缺失/无效 vol 行数: {total_miss}")
    print(f"可回填行数: {fill_count}")

    if fill_count == 0:
        print("✅ 无需修复")
        return 0

    df.loc[fillable, "vol"] = df.loc[fillable, "amount"] / (df.loc[fillable, "close"] * 100.0)

    print("写回 parquet...")
    df.to_parquet(PARQUET_FILE, index=False, compression="snappy")
    print("✅ 修复完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())

