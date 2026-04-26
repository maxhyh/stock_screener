#!/usr/bin/env python3
"""
MFTS 参数优化器（已归档）
- 自动寻找最优参数组合
- 基于历史数据验证

说明:
- 本脚本已退出主维护面，仅保留历史参考
- 当前建议使用 `scripts/quant_optimize.py`

使用方法:
    python archive/scripts/optimize.py
"""

import pandas as pd
import numpy as np
import os
import sys
from itertools import product
from datetime import datetime

# 添加项目路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")


def load_and_prepare_data():
    """加载并准备数据"""
    from mfts_screener import calc_indicators, load_metadata
    
    print("加载数据...")
    df = pd.read_parquet(PARQUET_FILE)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = df['ts_code'].astype(str)
    df = df.sort_values(['ts_code', 'trade_date'])
    
    print("计算指标...")
    df = calc_indicators(df)
    df = df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
    df = df.fillna(method='ffill').fillna(0)
    
    meta_dict = load_metadata()
    
    return df, meta_dict


def evaluate_params(df, meta_dict, params, test_days=30):
    """
    评估一组参数的表现
    
    Returns:
        dict: 包含胜率、平均收益等指标
    """
    from mfts_screener import scan, PARAMS
    
    # 临时修改参数
    original_params = PARAMS.copy()
    PARAMS.update(params)
    
    try:
        all_dates = sorted(df['trade_date'].unique())
        end_idx = len(all_dates) - 2
        start_idx = max(0, end_idx - test_days)
        test_dates = all_dates[start_idx:end_idx]
        
        results = []
        for scan_date in test_dates:
            signals_df = scan(df, target_date=scan_date, meta_dict=meta_dict)
            
            if signals_df.empty:
                continue
            
            # 获取 T+1 收益
            date_idx = list(all_dates).index(scan_date)
            future_date = all_dates[date_idx + 1]
            future_df = df[df['trade_date'] == future_date][['ts_code', 'pct_chg']]
            
            merged = signals_df.merge(future_df, left_on='代码', right_on='ts_code', how='left')
            merged = merged.rename(columns={'pct_chg_y': 'next_return'})
            results.append(merged)
        
        if not results:
            return {'win_rate': 0, 'avg_return': 0, 'signal_count': 0}
        
        all_results = pd.concat(results, ignore_index=True)
        valid = all_results['next_return'].notna()
        
        win_rate = (all_results.loc[valid, 'next_return'] > 0).mean() * 100
        avg_return = all_results.loc[valid, 'next_return'].mean()
        signal_count = valid.sum()
        
        return {
            'win_rate': win_rate,
            'avg_return': avg_return,
            'signal_count': signal_count
        }
        
    finally:
        # 恢复原参数
        PARAMS.clear()
        PARAMS.update(original_params)


def run_optimization():
    """运行参数优化"""
    print("=" * 60)
    print("MFTS 参数优化器")
    print("=" * 60)
    
    df, meta_dict = load_and_prepare_data()
    
    # 定义参数搜索空间
    param_grid = {
        'z_buy_deep': [-2.2, -1.96, -1.7],
        'z_buy_mid': [-1.7, -1.5, -1.3],
        'pass_score_threshold': [3.0, 4.0, 5.0],
        'buy_deep': [-12.0, -10.0, -8.0],
        'buy_mid': [-8.0, -7.0, -6.0],
    }
    
    # 生成所有组合
    keys = list(param_grid.keys())
    combinations = list(product(*[param_grid[k] for k in keys]))
    
    print(f"\n参数组合数: {len(combinations)}")
    print("开始评估...\n")
    
    results = []
    for i, values in enumerate(combinations):
        params = dict(zip(keys, values))
        
        try:
            metrics = evaluate_params(df, meta_dict, params, test_days=20)
            
            result = {**params, **metrics}
            results.append(result)
            
            if (i + 1) % 10 == 0:
                print(f"  已评估 {i+1}/{len(combinations)} 组合...")
                
        except Exception as e:
            print(f"  组合 {i+1} 失败: {e}")
            continue
    
    # 转换为 DataFrame 并排序
    results_df = pd.DataFrame(results)
    
    # 按综合评分排序 (胜率 * 0.6 + 归一化收益 * 0.4)
    if len(results_df) > 0:
        results_df['score'] = (
            results_df['win_rate'] / 100 * 0.6 + 
            (results_df['avg_return'] / results_df['avg_return'].abs().max()) * 0.4
        )
        results_df = results_df.sort_values('score', ascending=False)
    
    print("\n" + "=" * 60)
    print("优化结果 (Top 10)")
    print("=" * 60)
    
    if len(results_df) > 0:
        top10 = results_df.head(10)
        for i, row in top10.iterrows():
            print(f"\n#{results_df.index.get_loc(i)+1}:")
            print(f"  z_buy_deep={row['z_buy_deep']}, z_buy_mid={row['z_buy_mid']}")
            print(f"  buy_deep={row['buy_deep']}, buy_mid={row['buy_mid']}")
            print(f"  pass_score={row['pass_score_threshold']}")
            print(f"  胜率: {row['win_rate']:.1f}% | 平均收益: {row['avg_return']:.2f}% | 信号数: {row['signal_count']}")
    
    # 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = os.path.join(OUTPUT_DIR, "optimization_results.csv")
    results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n完整结果已保存: {output_file}")
    
    # 输出最优参数建议
    if len(results_df) > 0:
        best = results_df.iloc[0]
        print("\n" + "=" * 60)
        print("推荐参数配置:")
        print("=" * 60)
        print(f"""
PARAMS = {{
    'z_buy_deep': {best['z_buy_deep']},
    'z_buy_mid': {best['z_buy_mid']},
    'buy_deep': {best['buy_deep']},
    'buy_mid': {best['buy_mid']},
    'pass_score_threshold': {best['pass_score_threshold']},
}}
""")


if __name__ == "__main__":
    run_optimization()
