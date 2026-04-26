#!/usr/bin/env python3
"""
MFTS v6.1 vs v6.2 对比回测
验证优化效果

使用方法:
    python scripts/history/backtest_v62_compare.py
"""

import pandas as pd
import numpy as np
import os
import sys
import gc
import shutil
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))
sys.path.insert(0, BASE_DIR)

from mfts_screener import calc_indicators, calculate_alpha_score as calculate_alpha_v61
from mfts_screener_v62 import calculate_alpha_score_v62, get_dynamic_thresholds, PARAMS_V62
from utils.output_paths import ensure_output_dirs, write_dual_csv

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

BATCH_SIZE = 200


def backtest_version(df_raw, version='v61', start_date='2023-01-01', end_date='2025-12-31', top_n=10):
    """
    单版本回测
    """
    print(f"\n{'='*60}")
    print(f"回测 {version.upper()}: {start_date} ~ {end_date}")
    print(f"{'='*60}")
    
    all_stocks = sorted(df_raw['ts_code'].unique())
    trading_days = sorted(df_raw['trade_date'].unique())
    
    print(f"股票数: {len(all_stocks)}, 交易日: {len(trading_days)}")
    
    all_results = []
    total_batches = (len(all_stocks) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for batch_idx in tqdm(range(0, len(all_stocks), BATCH_SIZE), desc=f"{version}回测", total=total_batches):
        batch_stocks = all_stocks[batch_idx:batch_idx + BATCH_SIZE]
        
        # 获取批次数据
        batch_df = df_raw[df_raw['ts_code'].isin(batch_stocks)].copy()
        batch_df = batch_df.sort_values(['ts_code', 'trade_date'])
        
        # 计算技术指标
        batch_df = calc_indicators(batch_df)
        batch_df = batch_df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
        
        if len(batch_df) == 0:
            continue
        
        # 添加量比
        batch_df['vol_ratio'] = batch_df['vol'] / batch_df['vol_ma20']
        
        # 计算Alpha评分
        if version == 'v61':
            batch_df['alpha_score'] = batch_df.apply(
                lambda row: calculate_alpha_v61(row, -10, -7, -2.0),
                axis=1
            )
        else:  # v62
            thresholds = {'buy_deep': -10, 'buy_mid': -7, 'z_deep': -2.0}
            batch_df['alpha_score'] = batch_df.apply(
                lambda row: calculate_alpha_score_v62(row, thresholds),
                axis=1
            )
        
        # 计算未来收益
        batch_df['return_t1'] = batch_df.groupby('ts_code')['pct_chg'].shift(-1)
        batch_df['close_t5'] = batch_df.groupby('ts_code')['close'].shift(-5)
        batch_df['return_t5'] = (batch_df['close_t5'] / batch_df['close'] - 1) * 100
        
        # 逐日选股
        for date in trading_days[:-10]:
            day_df = batch_df[batch_df['trade_date'] == date]
            if len(day_df) == 0:
                continue
            
            # v6.2额外过滤
            if version == 'v62':
                day_df = day_df[day_df['alpha_score'] >= PARAMS_V62['min_alpha_score']]
                if 'vol_ratio' in day_df.columns:
                    day_df = day_df[day_df['vol_ratio'] >= PARAMS_V62['min_volume_ratio']]
            
            if len(day_df) == 0:
                continue
            
            picks = day_df.nlargest(top_n, 'alpha_score')
            
            for _, row in picks.iterrows():
                all_results.append({
                    'date': date,
                    'code': row['ts_code'],
                    'alpha_score': row['alpha_score'],
                    't1_return': row['return_t1'],
                    't5_return': row['return_t5'],
                })
        
        del batch_df
        gc.collect()
    
    # 合并去重
    results_df = pd.DataFrame(all_results)
    
    if len(results_df) == 0:
        return None
    
    # 每日只保留Top N
    final_results = []
    for date in results_df['date'].unique():
        day_picks = results_df[results_df['date'] == date].nlargest(top_n, 'alpha_score')
        final_results.append(day_picks)
    
    results_df = pd.concat(final_results, ignore_index=True)
    
    return results_df


def compare_versions(start_date='2023-01-01', end_date='2025-12-31', top_n=10):
    """
    对比v6.1和v6.2
    """
    print("=" * 70)
    print("MFTS v6.1 vs v6.2 对比回测")
    print("=" * 70)
    
    # 加载数据
    print("\n加载数据...")
    parquet_file = os.path.join(DATA_DIR, "daily_all_5y.parquet")
    columns = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    
    df_raw = pd.read_parquet(parquet_file, columns=columns)
    df_raw['trade_date'] = pd.to_datetime(df_raw['trade_date'].astype(str))
    df_raw['ts_code'] = df_raw['ts_code'].astype(str)
    df_raw = df_raw[(df_raw['trade_date'] >= start_date) & (df_raw['trade_date'] <= end_date)]
    
    print(f"数据量: {len(df_raw):,} 行")
    
    # 回测两个版本
    results_v61 = backtest_version(df_raw.copy(), 'v61', start_date, end_date, top_n)
    results_v62 = backtest_version(df_raw.copy(), 'v62', start_date, end_date, top_n)
    
    # 对比结果
    print("\n" + "=" * 70)
    print("对比结果")
    print("=" * 70)
    
    stats = {}
    for name, results in [('v6.1', results_v61), ('v6.2', results_v62)]:
        if results is None or len(results) == 0:
            continue
        
        t1 = results['t1_return'].dropna()
        t5 = results['t5_return'].dropna()
        
        stats[name] = {
            '交易次数': len(results),
            'T+1胜率': (t1 > 0).mean() * 100,
            'T+1平均收益': t1.mean(),
            'T+5胜率': (t5 > 0).mean() * 100,
            'T+5平均收益': t5.mean(),
        }
    
    print(f"\n{'指标':<15} {'v6.1':>12} {'v6.2':>12} {'改善':>12}")
    print("-" * 55)
    
    for metric in ['交易次数', 'T+1胜率', 'T+1平均收益', 'T+5胜率', 'T+5平均收益']:
        v61_val = stats.get('v6.1', {}).get(metric, 0)
        v62_val = stats.get('v6.2', {}).get(metric, 0)
        diff = v62_val - v61_val
        
        if '胜率' in metric:
            print(f"{metric:<15} {v61_val:>11.2f}% {v62_val:>11.2f}% {diff:>+11.2f}%")
        elif '收益' in metric:
            print(f"{metric:<15} {v61_val:>11.2f}% {v62_val:>11.2f}% {diff:>+11.2f}%")
        else:
            print(f"{metric:<15} {v61_val:>12,.0f} {v62_val:>12,.0f} {diff:>+12,.0f}")
    
    # 保存结果
    dirs = ensure_output_dirs(OUTPUT_DIR)
    base_dir = Path(OUTPUT_DIR)
    
    if results_v61 is not None:
        write_dual_csv(results_v61, dirs["backtest"] / "backtest_v61.csv", base_dir / "backtest_v61.csv", index=False)
    if results_v62 is not None:
        write_dual_csv(results_v62, dirs["backtest"] / "backtest_v62.csv", base_dir / "backtest_v62.csv", index=False)
    
    # 生成对比图表
    try:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        
        # 胜率对比
        metrics = ['T+1胜率', 'T+5胜率']
        v61_rates = [stats.get('v6.1', {}).get(m, 0) for m in metrics]
        v62_rates = [stats.get('v6.2', {}).get(m, 0) for m in metrics]
        
        x = np.arange(len(metrics))
        width = 0.35
        
        axes[0].bar(x - width/2, v61_rates, width, label='v6.1', color='steelblue')
        axes[0].bar(x + width/2, v62_rates, width, label='v6.2', color='green')
        axes[0].set_ylabel('胜率 (%)')
        axes[0].set_title('胜率对比')
        axes[0].set_xticks(x)
        axes[0].set_xticklabels(metrics)
        axes[0].legend()
        axes[0].axhline(y=50, color='r', linestyle='--', alpha=0.5)
        
        # 收益对比
        metrics = ['T+1平均收益', 'T+5平均收益']
        v61_rets = [stats.get('v6.1', {}).get(m, 0) for m in metrics]
        v62_rets = [stats.get('v6.2', {}).get(m, 0) for m in metrics]
        
        axes[1].bar(x - width/2, v61_rets, width, label='v6.1', color='steelblue')
        axes[1].bar(x + width/2, v62_rets, width, label='v6.2', color='green')
        axes[1].set_ylabel('收益 (%)')
        axes[1].set_title('平均收益对比')
        axes[1].set_xticks(x)
        axes[1].set_xticklabels(metrics)
        axes[1].legend()
        axes[1].axhline(y=0, color='r', linestyle='--', alpha=0.5)
        
        plt.tight_layout()
        chart_file = dirs["backtest"] / "version_comparison.png"
        chart_legacy = base_dir / "version_comparison.png"
        plt.savefig(chart_file, dpi=150)
        if chart_file.resolve() != chart_legacy.resolve():
            shutil.copyfile(chart_file, chart_legacy)
        print(f"\n✅ 对比图表已保存: {chart_file}")
    except Exception as e:
        print(f"图表生成失败: {e}")
    
    print("\n✅ 对比回测完成!")
    
    return stats


if __name__ == "__main__":
    compare_versions()
