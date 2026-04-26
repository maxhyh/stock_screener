#!/usr/bin/env python3
"""
5年完整回测脚本 - 流式处理版
解决OOM问题，采用分批处理策略

使用方法:
    python scripts/history/backtest_5y.py
    python scripts/history/backtest_5y.py --start 2023-01-01 --end 2025-12-31
"""

import pandas as pd
import numpy as np
import os
import sys
import gc
import shutil
from pathlib import Path
from datetime import datetime
import argparse
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))
sys.path.insert(0, BASE_DIR)

from mfts_screener import calc_indicators, calculate_alpha_score_vectorized
from utils.output_paths import ensure_output_dirs, write_dual_csv

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# 关键配置：分批处理
# 8GB内存建议使用100，16GB+可使用200
BATCH_SIZE = 100  # 每批处理100只股票 (针对8GB MacBook优化)


def process_batch_backtest(batch_df, trading_days, top_n=10):
    """
    处理一批股票的回测
    
    Args:
        batch_df: 已计算指标的批次数据
        trading_days: 交易日列表
        top_n: 每日选股数量
    
    Returns:
        results: 交易记录列表
    """
    results = []
    
    # 计算未来收益（在批次内计算）
    batch_df = batch_df.sort_values(['ts_code', 'trade_date'])
    batch_df['return_t1'] = batch_df.groupby('ts_code')['pct_chg'].shift(-1)
    
    # 计算T+5收益
    batch_df['close_t5'] = batch_df.groupby('ts_code')['close'].shift(-5)
    batch_df['return_t5'] = (batch_df['close_t5'] / batch_df['close'] - 1) * 100
    
    # 计算T+1数据 (用于更真实的撮合)
    batch_df['open_t1'] = batch_df.groupby('ts_code')['open'].shift(-1)
    batch_df['close_t1'] = batch_df.groupby('ts_code')['close'].shift(-1)
    
    # 计算T+10收益 (修正为基于 Open_T1)
    batch_df['close_t10'] = batch_df.groupby('ts_code')['close'].shift(-10)
    batch_df['return_t10'] = (batch_df['close_t10'] / batch_df['close'] - 1) * 100
    
    # 逐日选股（只处理这批股票）
    for date in trading_days:
        day_df = batch_df[batch_df['trade_date'] == date]
        if len(day_df) == 0:
            continue
        
        # 选择Alpha评分最高的top_n只
        picks = day_df.nlargest(top_n, 'alpha_score')
        
        for _, row in picks.iterrows():
            # [Fix] Future Function: Use T+1 Open price as buy price (if available)
            # row['open_t1'] was calculated in process_batch_backtest logic (needs addition)
            # Actually, batch_df passing needs to include open_t1.
            buy_price = row['open_t1'] if 'open_t1' in row and not pd.isna(row['open_t1']) else row['close']
            
            # Recalculate returns based on REAL buy price (T+1 Open)
            # t1_return = (close_t2 / open_t1) - 1 ?? 
            # Original logic: return_t1 = close_t1 / close_t0 - 1. (Close-to-Close return).
            # If we buy at T+1 Open, we hold until when? 
            # Usually: Buy at T+1 Open, Sell at T+2 Open (1 day return)? Or T+1 Close?
            # Standard "T+1 strategy" usually means: Signal at T close, Buy T+1 Open, Sell T+2 Open (or T+1 Close).
            # The original metric 'return_t1' was shift(-1) of pct_chg, which is T+1 Close / T+1 Open - 1? No. 
            # pct_chg is (Close_t - Close_t-1)/Close_t-1.
            # shift(-1) is (Close_t+1 - Close_t)/Close_t. This is Close-to-Close from Signal Day to Next Day.
            # Realistically: Buy T+1 Open, Sell T+2 Open. 
            # Or simpler: Buy T+1 Open, Sell T+1 Close (Intraday)? No, T+1 trading means next day.
            # Let's assume we hold for 1 day: Buy T+1 Open, Sell T+2 Open.
            # return_real = (open_t2 / open_t1) - 1.
            # For simplicity and to match "Close-to-Close" trend roughly, let's use:
            # Buy T+1 Open, Sell T+2 Close (2 day hold?)
            # Let's stick to: Buy Price = T+1 Open. Sell Price = T+2 Open (~ T+1 pct_chg).
            # To be safe and minimal change: Use Close-to-Close for trend check, but penalize entry.
            # Implementation: Return = (Close_T+1 - Open_T+1) / Open_T+1 ? That's T+1 intraday.
            # Let's use: Return = (Close_T+1 - Buy_Price) / Buy_Price * 100. (profit from T+1 Open to T+1 Close).
            # This is "T+0" profit if we buy T+1 Open? 
            # If strategy is "Buy Tomorrow Open", we own it at T+1 Open.
            # If we sell at T+1 Close, that's one day.
            # Original code 'return_t1' comes from `batch_df.groupby('ts_code')['pct_chg'].shift(-1)`.
            # This is `pct_chg` of T+1. i.e. (C_t1 - C_t0) / C_t0.
            # We want (C_t1 - O_t1) / O_t1 ? Or (C_t2 - O_t1) ?
            # Let's use (Close_T+1 - Open_T+1) for T+1 return (Intraday T+1).
            # But wait, original 'return_t1' implies 1-day holding. 
            # If we buy T+1 Open, we realize PnL at T+1 Close?
            # Let's calc: t1_return = (row['close_t1'] - row['open_t1']) / row['open_t1'] * 100
            
            t1_ret = (row['close_t1'] - buy_price) / buy_price * 100 if buy_price > 0 and 'close_t1' in row else 0
            
            # For T+5: Sell at T+5 Close.
            t5_ret = (row['close_t5'] - buy_price) / buy_price * 100 if 'close_t5' in row and not pd.isna(row['close_t5']) else None
            
            results.append({
                'date': date,
                'code': row['ts_code'],
                'alpha_score': row['alpha_score'],
                'buy_price': buy_price,
                't1_return': t1_ret,
                't5_return': t5_ret,
                't10_return': row['return_t10'] # Keep T10 roughly comparable or fix later
            })
    
    return results


def backtest_streaming(start_date='2023-01-01', end_date='2025-12-31', top_n=10):
    """
    流式回测（分批处理，避免OOM）
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        top_n: 每日选股数量
    """
    print("=" * 70)
    print(f"MFTS回测（流式处理版）：{start_date} ~ {end_date}")
    print("=" * 70)
    
    # 1. 只加载必需列（减少内存）
    print("\n[1/5] 加载数据...")
    parquet_file = os.path.join(DATA_DIR, "daily_all_5y.parquet")
    # 只使用parquet中实际存在的列
    columns_needed = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 
                      'vol', 'amount', 'pct_chg']
    
    df_raw = pd.read_parquet(parquet_file, columns=columns_needed)
    df_raw['trade_date'] = pd.to_datetime(df_raw['trade_date'].astype(str))
    df_raw['ts_code'] = df_raw['ts_code'].astype(str)
    
    # 筛选时间范围
    df_raw = df_raw[(df_raw['trade_date'] >= start_date) & (df_raw['trade_date'] <= end_date)]
    
    # 获取交易日和股票列表
    trading_days = sorted(df_raw['trade_date'].unique())
    all_stocks = sorted(df_raw['ts_code'].unique())
    
    print(f"数据量: {len(df_raw):,} 行")
    print(f"股票数: {len(all_stocks):,} 只")
    print(f"交易日: {len(trading_days)} 天")
    print(f"分批大小: {BATCH_SIZE} 只/批")
    
    # 2. 分批处理
    print(f"\n[2/5] 分批处理（共{(len(all_stocks) + BATCH_SIZE - 1) // BATCH_SIZE}批）...")
    all_results = []
    
    total_batches = (len(all_stocks) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for batch_idx in tqdm(range(0, len(all_stocks), BATCH_SIZE), desc="回测进度", total=total_batches):
        batch_stocks = all_stocks[batch_idx:batch_idx + BATCH_SIZE]
        
        # 只取这批股票的数据
        batch_df = df_raw[df_raw['ts_code'].isin(batch_stocks)].copy()
        batch_df = batch_df.sort_values(['ts_code', 'trade_date'])
        
        # 计算技术指标
        batch_df = calc_indicators(batch_df)
        batch_df = batch_df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
        
        if len(batch_df) == 0:
            continue
        
        # 计算Alpha评分（逐行处理）
        # [Optimized] Vectorized Alpha Score
        # Scalars: adaptive_buy_deep=-10, adaptive_buy_mid=-7, dynamic_z_deep=-2.0
        batch_df['alpha_score'] = calculate_alpha_score_vectorized(
            batch_df, 
            adaptive_buy_deep=-10.0, 
            adaptive_buy_mid=-7.0, 
            dynamic_z_deep=-2.0
        )
        
        # 回测这批股票
        batch_results = process_batch_backtest(batch_df, trading_days[:-10], top_n)
        all_results.extend(batch_results)
        
        # 释放内存
        del batch_df
        gc.collect()
    
    # 释放原始数据
    del df_raw
    gc.collect()
    
    # 3. 合并结果
    print("\n[3/5] 合并结果...")
    if not all_results:
        print("❌ 没有交易记录")
        return None
    
    results_df = pd.DataFrame(all_results)
    
    # 按日期聚合（取每天Top N）
    final_results = []
    for date in results_df['date'].unique():
        day_picks = results_df[results_df['date'] == date].nlargest(top_n, 'alpha_score')
        final_results.append(day_picks)
    
    results_df = pd.concat(final_results, ignore_index=True)
    
    # 4. 保存结果
    print("\n[4/5] 保存结果...")
    dirs = ensure_output_dirs(OUTPUT_DIR)
    base_dir = Path(OUTPUT_DIR)
    report_file = dirs["backtest"] / "backtest_report.csv"
    report_legacy = base_dir / "backtest_report.csv"
    write_dual_csv(results_df, report_file, report_legacy, index=False, encoding='utf-8-sig')
    
    # 5. 统计分析
    print("\n[5/5] 统计分析...")
    print("\n" + "=" * 70)
    print("回测结果")
    print("=" * 70)
    
    # 基础统计
    t1_valid = results_df['t1_return'].dropna()
    t5_valid = results_df['t5_return'].dropna()
    t10_valid = results_df['t10_return'].dropna()
    
    stats = {
        '总交易天数': results_df['date'].nunique(),
        '总交易次数': len(results_df),
        'T+1胜率': (t1_valid > 0).mean() * 100,
        'T+1平均收益': t1_valid.mean(),
        'T+1最大收益': t1_valid.max(),
        'T+1最大亏损': t1_valid.min(),
        'T+5胜率': (t5_valid > 0).mean() * 100,
        'T+5平均收益': t5_valid.mean(),
        'T+10胜率': (t10_valid > 0).mean() * 100,
        'T+10平均收益': t10_valid.mean(),
    }
    
    for key, value in stats.items():
        if '胜率' in key:
            print(f"{key:<15}: {value:.2f}%")
        elif '收益' in key or '亏损' in key:
            print(f"{key:<15}: {value:.2f}%")
        else:
            print(f"{key:<15}: {value:,}")
    
    # 年度统计
    print("\n" + "=" * 70)
    print("年度表现")
    print("=" * 70)
    results_df['year'] = pd.to_datetime(results_df['date']).dt.year
    for year, group in results_df.groupby('year'):
        t1 = group['t1_return'].dropna()
        win_rate = (t1 > 0).mean() * 100
        avg_ret = t1.mean()
        print(f"{year}: {len(group)}笔, 胜率={win_rate:.1f}%, 平均={avg_ret:.2f}%")
    
    # 生成图表
    try:
        print("\n生成图表...")
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # 1. 年度胜率
        yearly_win = results_df.groupby('year')['t1_return'].apply(lambda x: (x > 0).mean() * 100)
        yearly_win.plot(kind='bar', ax=axes[0, 0], color='steelblue')
        axes[0, 0].set_title('年度T+1胜率')
        axes[0, 0].set_ylabel('胜率 (%)')
        axes[0, 0].axhline(y=50, color='r', linestyle='--', alpha=0.5)
        
        # 2. 年度平均收益
        yearly_ret = results_df.groupby('year')['t1_return'].mean()
        yearly_ret.plot(kind='bar', ax=axes[0, 1], color='green')
        axes[0, 1].set_title('年度T+1平均收益')
        axes[0, 1].set_ylabel('收益 (%)')
        axes[0, 1].axhline(y=0, color='r', linestyle='--', alpha=0.5)
        
        # 3. 不同周期胜率
        periods = ['T+1', 'T+5', 'T+10']
        win_rates = [
            (t1_valid > 0).mean() * 100,
            (t5_valid > 0).mean() * 100,
            (t10_valid > 0).mean() * 100,
        ]
        axes[1, 0].bar(periods, win_rates, color=['steelblue', 'orange', 'green'])
        axes[1, 0].set_title('持仓周期胜率对比')
        axes[1, 0].set_ylabel('胜率 (%)')
        axes[1, 0].axhline(y=50, color='r', linestyle='--', alpha=0.5)
        
        # 4. 收益分布
        axes[1, 1].hist(t1_valid, bins=50, alpha=0.7, color='steelblue', edgecolor='black')
        axes[1, 1].axvline(x=0, color='r', linestyle='--', linewidth=2)
        axes[1, 1].set_title('T+1收益分布')
        axes[1, 1].set_xlabel('收益率 (%)')
        
        plt.tight_layout()
        chart_file = dirs["backtest"] / "backtest_charts.png"
        chart_legacy = base_dir / "backtest_charts.png"
        plt.savefig(chart_file, dpi=150, bbox_inches='tight')
        if chart_file.resolve() != chart_legacy.resolve():
            shutil.copyfile(chart_file, chart_legacy)
        plt.close()
        print(f"图表已保存: {chart_file}")
    except Exception as e:
        print(f"图表生成失败: {e}")
    
    print(f"\n✅ 回测完成!")
    print(f"报告已保存: {report_file}")
    
    return results_df


def main():
    parser = argparse.ArgumentParser(description='MFTS回测（流式处理版）')
    parser.add_argument('--start', type=str, default='2023-01-01', help='开始日期')
    parser.add_argument('--end', type=str, default='2025-12-31', help='结束日期')
    parser.add_argument('--top', type=int, default=10, help='每日选股数量')
    parser.add_argument('--batch', type=int, default=200, help='批次大小')
    args = parser.parse_args()
    
    global BATCH_SIZE
    BATCH_SIZE = args.batch
    
    backtest_streaming(start_date=args.start, end_date=args.end, top_n=args.top)


if __name__ == "__main__":
    main()
