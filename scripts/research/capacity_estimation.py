#!/usr/bin/env python3
"""
策略容量评估 - 估算策略可承载的最大资金规模。

原理:
  基于历史推荐标的的成交额，按参与率上限反推单票/总体可容纳资金。
  如果策略选出的标的流动性不足，增大资金会导致滑点急剧上升，Alpha 被吃掉。

使用方法:
    python scripts/research/capacity_estimation.py
    python scripts/research/capacity_estimation.py --participation-rate 0.03 --top-n 10
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from utils.code_utils import normalize_ts_code_series
from utils.output_paths import ensure_output_dirs, list_dual

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")


def _load_historical_picks(output_dir: str, n_days: int = 60) -> pd.DataFrame:
    """加载最近 N 天的 daily_YYYYMMDD.csv 推荐记录。"""
    dirs = ensure_output_dirs(output_dir)
    files = list_dual(["daily_*.csv"], dirs["daily"], Path(output_dir))
    if not files:
        raise FileNotFoundError("未找到 daily_YYYYMMDD.csv 推荐文件")

    files = sorted(files)[-n_days:]
    all_picks = []
    for f in files:
        try:
            df = pd.read_csv(f, dtype={"代码": str})
            if "代码" not in df.columns:
                continue
            df["代码"] = normalize_ts_code_series(df["代码"])
            df["source_file"] = f.name
            all_picks.append(df)
        except Exception:
            continue

    if not all_picks:
        raise RuntimeError("无有效的推荐记录")

    return pd.concat(all_picks, ignore_index=True)


def _load_amount_data(parquet_file: str, lookback_days: int = 60) -> pd.DataFrame:
    """加载成交额数据。"""
    df = pd.read_parquet(parquet_file, columns=["ts_code", "trade_date", "amount"])
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
    df["ts_code"] = normalize_ts_code_series(df["ts_code"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    # 取最近 N 个交易日
    dates = sorted(df["trade_date"].dropna().unique())
    if len(dates) > lookback_days:
        cutoff = dates[-lookback_days]
        df = df[df["trade_date"] >= cutoff]

    return df


def estimate_capacity(
    picks_df: pd.DataFrame,
    amount_df: pd.DataFrame,
    participation_rate: float = 0.05,
    top_n: int = 10,
) -> dict:
    """
    容量估算。

    Args:
        picks_df: 历史推荐记录（含 '代码' 列）
        amount_df: 成交额数据
        participation_rate: 占日均成交额比例上限
        top_n: 每次持仓数量

    Returns:
        容量评估结果字典
    """
    # 取频繁推荐的标的
    pick_codes = picks_df["代码"].dropna().unique()

    # 计算每个标的的 20 日均成交额
    amount_df = amount_df[amount_df["ts_code"].isin(pick_codes)].copy()
    adv20 = (
        amount_df.groupby("ts_code")["amount"]
        .apply(lambda x: x.tail(20).mean())
        .dropna()
    )

    if adv20.empty:
        return {
            "status": "no_data",
            "capacity_per_stock_median": 0,
            "capacity_total": 0,
        }

    # 单票最大可投金额 = ADV20 × 参与率
    max_per_stock = adv20 * participation_rate

    # 被推荐次数（频率权重）
    pick_freq = picks_df["代码"].value_counts()
    common_codes = [c for c in pick_freq.head(top_n * 3).index if c in max_per_stock.index]

    if not common_codes:
        common_codes = list(max_per_stock.index[:top_n])

    selected_capacity = max_per_stock.loc[common_codes].sort_values()

    # 瓶颈：Top-N 中最小的那个决定策略容量
    if len(selected_capacity) >= top_n:
        bottleneck_n = selected_capacity.head(top_n)
    else:
        bottleneck_n = selected_capacity

    capacity_per_stock_min = float(bottleneck_n.min()) if not bottleneck_n.empty else 0
    capacity_per_stock_median = float(bottleneck_n.median()) if not bottleneck_n.empty else 0
    capacity_per_stock_p25 = float(bottleneck_n.quantile(0.25)) if len(bottleneck_n) >= 4 else capacity_per_stock_min

    # 总策略容量 ≈ 瓶颈标的容量 × N
    capacity_total_conservative = capacity_per_stock_min * top_n
    capacity_total_moderate = capacity_per_stock_p25 * top_n
    capacity_total_aggressive = capacity_per_stock_median * top_n

    # 瓶颈标的
    bottleneck_stocks = []
    for code in bottleneck_n.head(5).index:
        bottleneck_stocks.append({
            "code": code,
            "adv20": float(adv20.get(code, 0)),
            "max_capacity": float(max_per_stock.get(code, 0)),
            "pick_count": int(pick_freq.get(code, 0)),
        })

    result = {
        "status": "ok",
        "participation_rate": participation_rate,
        "top_n": top_n,
        "analyzed_stocks": len(common_codes),
        "capacity_per_stock_min": capacity_per_stock_min,
        "capacity_per_stock_p25": capacity_per_stock_p25,
        "capacity_per_stock_median": capacity_per_stock_median,
        "capacity_total_conservative": capacity_total_conservative,
        "capacity_total_moderate": capacity_total_moderate,
        "capacity_total_aggressive": capacity_total_aggressive,
        "bottleneck_stocks": bottleneck_stocks,
        "adv20_median_all": float(adv20.median()),
        "adv20_min_selected": float(adv20.loc[common_codes].min()) if common_codes else 0,
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="策略容量评估")
    parser.add_argument("--participation-rate", type=float, default=0.05, help="参与率上限 (0~1, 默认 0.05)")
    parser.add_argument("--top-n", type=int, default=10, help="每次持仓数")
    parser.add_argument("--lookback-days", type=int, default=60, help="回看天数")
    args = parser.parse_args()

    print("=" * 72)
    print("策略容量评估")
    print("=" * 72)

    print("\n加载推荐历史...")
    picks_df = _load_historical_picks(OUTPUT_DIR, n_days=args.lookback_days)
    print(f"  推荐记录: {len(picks_df)} 条，涉及 {picks_df['代码'].nunique()} 只标的")

    print("加载成交额数据...")
    amount_df = _load_amount_data(PARQUET_FILE, lookback_days=args.lookback_days)

    result = estimate_capacity(
        picks_df,
        amount_df,
        participation_rate=args.participation_rate,
        top_n=args.top_n,
    )

    if result["status"] != "ok":
        print("❌ 数据不足，无法评估容量")
        return

    print(f"\n参与率上限: {result['participation_rate']:.1%}")
    print(f"持仓数量: {result['top_n']}")
    print(f"分析标的: {result['analyzed_stocks']}")

    print(f"\n{'=' * 72}")
    print(f"容量评估结果")
    print(f"{'=' * 72}")
    print(f"  保守估计（瓶颈最小值）: ¥{result['capacity_total_conservative']:>12,.0f}")
    print(f"  中性估计（25分位数）  : ¥{result['capacity_total_moderate']:>12,.0f}")
    print(f"  激进估计（中位数）    : ¥{result['capacity_total_aggressive']:>12,.0f}")

    print(f"\n单票容量:")
    print(f"  最小: ¥{result['capacity_per_stock_min']:>12,.0f}")
    print(f"  P25:  ¥{result['capacity_per_stock_p25']:>12,.0f}")
    print(f"  中位: ¥{result['capacity_per_stock_median']:>12,.0f}")

    if result["bottleneck_stocks"]:
        print(f"\n瓶颈标的（容量最小的前 5 只）:")
        for s in result["bottleneck_stocks"]:
            print(
                f"  {s['code']} | ADV20=¥{s['adv20']:>12,.0f} | "
                f"最大可投=¥{s['max_capacity']:>10,.0f} | 推荐次数={s['pick_count']}"
            )

    print(f"\n✅ 容量评估完成")


if __name__ == "__main__":
    main()
