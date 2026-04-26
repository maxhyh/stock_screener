#!/usr/bin/env python3
"""生成平台 profiling 基线。"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "core"))

from core.platform.profiling import profile_call
from mfts_screener import calc_indicators


def main() -> int:
    parser = argparse.ArgumentParser(description="MFTS profiling baseline")
    parser.add_argument("--stocks", type=int, default=200, help="抽样股票数量")
    parser.add_argument("--iterations", type=int, default=1, help="重复次数")
    args = parser.parse_args()

    parquet_file = os.path.join(BASE_DIR, "data", "daily_all_5y.parquet")
    if not os.path.exists(parquet_file):
        print(f"❌ 数据文件不存在: {parquet_file}")
        return 1

    cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"]
    df = pd.read_parquet(parquet_file, columns=cols)
    codes = sorted(df["ts_code"].astype(str).unique().tolist())[: max(int(args.stocks), 1)]
    sample = df[df["ts_code"].astype(str).isin(codes)].copy().sort_values(["ts_code", "trade_date"])
    result = profile_call("calc_indicators", calc_indicators, sample, iterations=max(int(args.iterations), 1))
    print(
        f"label={result.label} | iterations={result.iterations} | elapsed={result.elapsed_seconds:.4f}s "
        f"| avg={result.avg_seconds:.4f}s | peak_memory_kb={result.peak_memory_kb:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
