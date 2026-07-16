#!/usr/bin/env python3
"""生成平台 profiling 基线。"""

from __future__ import annotations

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "core"))

from core.platform.profiling import profile_call
from core.data.market_data_gateway import AShareMarketDataGateway
from mfts_screener import calc_indicators


def main() -> int:
    parser = argparse.ArgumentParser(description="MFTS profiling baseline")
    parser.add_argument("--stocks", type=int, default=200, help="抽样股票数量")
    parser.add_argument("--iterations", type=int, default=1, help="重复次数")
    args = parser.parse_args()

    gateway = AShareMarketDataGateway()
    sessions = gateway.available_trade_dates()
    if not sessions:
        print("❌ 共享 ODS 没有可用日线会话")
        return 1
    start = sessions[max(0, len(sessions) - 300)]
    df = gateway.load_bars(start, sessions[-1], include_bj9=False)
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
