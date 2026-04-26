#!/usr/bin/env python3
"""
MFTS 回测系统（已归档）
- 验证选股信号的历史表现
- 计算胜率、收益等指标

说明:
- 本脚本已退出主维护面，仅保留历史参考
- 当前建议使用 `scripts/quant_portfolio_backtest.py`

使用方法:
    python archive/scripts/backtest.py --days 30
"""

import pandas as pd
import numpy as np
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import argparse

# 添加项目路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))
sys.path.insert(0, BASE_DIR)

from mfts_screener import (
    load_data, load_metadata, calc_indicators, scan, format_output, PARAMS
)
from utils.output_paths import ensure_output_dirs, write_dual_csv

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")


def run_backtest(days=30, holding_period=1):
    """
    运行回测
    
    Args:
        days: 回测天数
        holding_period: 持有周期 (T+N)
    """
    print("=" * 60)
    print(f"MFTS 回测系统")
    print(f"回测天数: {days} | 持有周期: T+{holding_period}")
    print("=" * 60)
    
    # 加载数据
    print("\n加载数据...")
    df = pd.read_parquet(PARQUET_FILE)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = df['ts_code'].astype(str)
    df = df.sort_values(['ts_code', 'trade_date'])
    
    # 加载元数据
    meta_dict = load_metadata()
    
    # 计算指标
    print("计算指标...")
    df = calc_indicators(df)
    df = df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
    df = df.fillna(method='ffill').fillna(0)
    
    # 获取所有交易日
    all_dates = sorted(df['trade_date'].unique())
    
    # 选择回测日期范围
    end_idx = len(all_dates) - holding_period - 1  # 留出持有期
    start_idx = max(0, end_idx - days)
    test_dates = all_dates[start_idx:end_idx]
    
    print(f"回测区间: {test_dates[0].date()} ~ {test_dates[-1].date()}")
    print(f"共 {len(test_dates)} 个交易日\n")
    
    # 存储回测结果
    all_results = []
    
    for i, scan_date in enumerate(test_dates):
        # 运行选股
        signals_df = scan(df, target_date=scan_date, meta_dict=meta_dict)
        
        if signals_df.empty:
            continue
        
        # 获取 T+N 日的收益
        date_idx = list(all_dates).index(scan_date)
        future_date = all_dates[date_idx + holding_period]
        
        future_df = df[df['trade_date'] == future_date][['ts_code', 'open', 'close', 'pct_chg']]
        future_df = future_df.rename(columns={
            'open': 'next_open',
            'close': 'next_close', 
            'pct_chg': 'next_pct_chg'
        })
        
        # 合并
        signals_df = signals_df.merge(future_df, left_on='代码', right_on='ts_code', how='left')
        signals_df['scan_date'] = scan_date
        
        all_results.append(signals_df)
        
        if (i + 1) % 10 == 0:
            print(f"  已处理 {i+1}/{len(test_dates)} 天...")
    
    if not all_results:
        print("回测期间无信号!")
        return
    
    # 合并所有结果
    results_df = pd.concat(all_results, ignore_index=True)
    
    # 计算统计
    print("\n" + "=" * 60)
    print("回测结果统计")
    print("=" * 60)
    
    total_signals = len(results_df)
    valid_signals = results_df['next_pct_chg'].notna().sum()
    
    # 胜率 (T+N 收益 > 0)
    win_count = (results_df['next_pct_chg'] > 0).sum()
    win_rate = win_count / valid_signals * 100 if valid_signals > 0 else 0
    
    # 平均收益
    avg_return = results_df['next_pct_chg'].mean()
    
    # 最大收益/亏损
    max_return = results_df['next_pct_chg'].max()
    min_return = results_df['next_pct_chg'].min()
    
    print(f"\n总信号数: {total_signals}")
    print(f"有效信号: {valid_signals}")
    print(f"胜率 (T+{holding_period}): {win_rate:.1f}%")
    print(f"平均收益: {avg_return:.2f}%")
    print(f"最大收益: {max_return:.2f}%")
    print(f"最大亏损: {min_return:.2f}%")
    
    # 按信号类型统计
    print("\n--- 按信号类型统计 ---")
    for signal_type in ['L1', 'L2', 'L3', '趋势']:
        subset = results_df[results_df['信号'].str.contains(signal_type, na=False)]
        if len(subset) > 0:
            sub_win = (subset['next_pct_chg'] > 0).sum()
            sub_rate = sub_win / len(subset) * 100
            sub_avg = subset['next_pct_chg'].mean()
            print(f"  {signal_type}: {len(subset)}个 | 胜率 {sub_rate:.1f}% | 平均 {sub_avg:.2f}%")
    
    # 按超跌等级统计
    print("\n--- 按超跌等级统计 ---")
    for level in ['极度', '深度', '普通']:
        subset = results_df[results_df['超跌等级'] == level]
        if len(subset) > 0:
            sub_win = (subset['next_pct_chg'] > 0).sum()
            sub_rate = sub_win / len(subset) * 100
            sub_avg = subset['next_pct_chg'].mean()
            print(f"  {level}: {len(subset)}个 | 胜率 {sub_rate:.1f}% | 平均 {sub_avg:.2f}%")
    
    # 保存详细结果
    dirs = ensure_output_dirs(OUTPUT_DIR)
    base_dir = Path(OUTPUT_DIR)
    output_file = dirs["backtest"] / f"backtest_T{holding_period}_{days}days.csv"
    legacy_file = base_dir / f"backtest_T{holding_period}_{days}days.csv"
    write_dual_csv(results_df, output_file, legacy_file, index=False, encoding='utf-8-sig')
    print(f"\n详细结果已保存: {output_file}")
    
    return results_df


def main():
    parser = argparse.ArgumentParser(description='MFTS 回测系统')
    parser.add_argument('--days', type=int, default=30, help='回测天数')
    parser.add_argument('--holding', type=int, default=1, help='持有周期 (T+N)')
    args = parser.parse_args()
    
    run_backtest(days=args.days, holding_period=args.holding)


if __name__ == "__main__":
    main()
