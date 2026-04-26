#!/usr/bin/env python3
"""
MFTS 轻量级历史回测
仅使用最近3个月数据进行回测，避免内存溢出

使用方法:
    python scripts/backtest_mfts_lite.py [--days 90]
"""

import pandas as pd
import numpy as np
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from tqdm import tqdm
import argparse
import gc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from utils.output_paths import ensure_output_dirs, write_dual_csv

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def backtest_lite(days=90):
    """轻量级回测"""
    print("=" * 70)
    print(f"MFTS 历史回测 (最近{days}天)")
    print("=" * 70)
    
    # 1. 加载数据 (只加载需要的列)
    print("\n[1/3] 加载数据...")
    parquet_file = os.path.join(DATA_DIR, "daily_all_5y.parquet")
    
    columns_needed = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 
                      'vol', 'amount', 'pct_chg']
    
    df = pd.read_parquet(parquet_file, columns=columns_needed)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    
    # 只保留最近 days + 30 天的数据 (30天用于技术指标计算)
    cutoff = df['trade_date'].max() - timedelta(days=days + 60)
    df = df[df['trade_date'] >= cutoff].copy()
    
    print(f"   截取数据: {len(df):,} 行")
    print(f"   日期范围: {df['trade_date'].min().strftime('%Y-%m-%d')} ~ {df['trade_date'].max().strftime('%Y-%m-%d')}")
    
    # 2. 计算简化指标
    print("\n[2/3] 计算指标...")
    df = df.sort_values(['ts_code', 'trade_date'])
    
    # 分组计算
    grouped = df.groupby('ts_code')
    
    # MA20 和 BIAS
    df['ma20'] = grouped['close'].transform(lambda x: x.rolling(20, min_periods=10).mean())
    df['bias'] = (df['close'] / df['ma20'] - 1) * 100
    
    # 20日价格标准差 (用于Z-Score)
    df['std20'] = grouped['close'].transform(lambda x: x.rolling(20, min_periods=10).std())
    df['z_score'] = (df['close'] - df['ma20']) / df['std20']
    
    gc.collect()
    
    # 3. 回测
    print("\n[3/3] 执行回测...")
    all_dates = sorted(df['trade_date'].unique())
    
    # 回测日期 (最后10天用于验证)
    backtest_end = all_dates[-11]
    backtest_start = all_dates[0] + timedelta(days=30)  # 预留指标计算窗口
    
    backtest_dates = [d for d in all_dates if backtest_start <= d <= backtest_end]
    print(f"   回测天数: {len(backtest_dates)}")
    
    results = []
    
    for target_date in tqdm(backtest_dates, desc="回测"):
        # 当日数据
        day_df = df[df['trade_date'] == target_date].copy()
        
        if day_df.empty:
            continue
        
        # 超跌条件: BIAS < -10 或 Z-Score < -2
        oversold = (day_df['bias'] < -10) | (day_df['z_score'] < -2)
        # 非涨停
        not_limit = day_df['pct_chg'] < 9.5
        # 流动性
        liquid = day_df['amount'] >= 50000000
        
        selected = day_df[oversold & not_limit & liquid]['ts_code'].tolist()
        
        if not selected:
            continue
        
        # 计算验证
        t1_rets, t5_rets, t10_rets = [], [], []
        date_idx = list(all_dates).index(target_date)
        
        for code in selected:
            code_df = df[df['ts_code'] == code].sort_values('trade_date')
            code_dates = code_df['trade_date'].tolist()
            
            if target_date not in code_dates:
                continue
            
            cidx = code_dates.index(target_date)
            base = code_df.iloc[cidx]['close']
            
            if cidx + 1 < len(code_dates):
                t1_rets.append((code_df.iloc[cidx + 1]['close'] / base - 1) * 100)
            if cidx + 5 < len(code_dates):
                t5_rets.append((code_df.iloc[cidx + 5]['close'] / base - 1) * 100)
            if cidx + 10 < len(code_dates):
                t10_rets.append((code_df.iloc[cidx + 10]['close'] / base - 1) * 100)
        
        result = {'date': target_date.strftime('%Y-%m-%d'), 'picks': len(selected)}
        
        if t1_rets:
            result['t1_win'] = round((np.array(t1_rets) > 0).mean() * 100, 1)
            result['t1_avg'] = round(np.mean(t1_rets), 2)
        if t5_rets:
            result['t5_win'] = round((np.array(t5_rets) > 0).mean() * 100, 1)
            result['t5_avg'] = round(np.mean(t5_rets), 2)
        if t10_rets:
            result['t10_win'] = round((np.array(t10_rets) > 0).mean() * 100, 1)
            result['t10_avg'] = round(np.mean(t10_rets), 2)
        
        results.append(result)
    
    # 汇总
    print("\n" + "=" * 70)
    print("回测结果")
    print("=" * 70)
    
    if not results:
        print("❌ 无结果")
        return
    
    df_res = pd.DataFrame(results)
    
    # 保存
    dirs = ensure_output_dirs(OUTPUT_DIR)
    base_dir = Path(OUTPUT_DIR)
    output_file = dirs["backtest"] / f"mfts_backtest_{days}d.csv"
    legacy_file = base_dir / f"mfts_backtest_{days}d.csv"
    write_dual_csv(df_res, output_file, legacy_file, index=False, encoding='utf-8-sig')
    
    # 统计
    print(f"\n回测天数: {len(df_res)}")
    print(f"平均选股: {df_res['picks'].mean():.1f} 只/天")
    
    if 't1_win' in df_res.columns:
        print(f"\nT+1 胜率: {df_res['t1_win'].mean():.1f}%")
        print(f"T+1 平均收益: {df_res['t1_avg'].mean():.2f}%")
    
    if 't5_win' in df_res.columns:
        print(f"\nT+5 胜率: {df_res['t5_win'].mean():.1f}%")
        print(f"T+5 平均收益: {df_res['t5_avg'].mean():.2f}%")
    
    if 't10_win' in df_res.columns:
        print(f"\nT+10 胜率: {df_res['t10_win'].mean():.1f}%")
        print(f"T+10 平均收益: {df_res['t10_avg'].mean():.2f}%")
    
    print(f"\n✅ 结果已保存: {output_file}")
    
    # 显示最近10天
    print("\n最近10天详情:")
    print(df_res.tail(10).to_string(index=False))
    
    return df_res


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=90, help='回测天数')
    args = parser.parse_args()
    
    backtest_lite(args.days)
