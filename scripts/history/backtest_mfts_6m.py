#!/usr/bin/env python3
"""
MFTS 半年历史回测
基于实际数据回测过去半年每个交易日的 MFTS 选股表现

使用方法:
    python scripts/history/backtest_mfts_6m.py
"""

import pandas as pd
import numpy as np
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from utils.output_paths import ensure_output_dirs, write_dual_csv

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# 尝试导入 MFTS 核心模块
try:
    from core.mfts_screener import calc_indicators, PARAMS
except ImportError:
    print("❌ 无法导入 mfts_screener 模块")
    sys.exit(1)


def run_mfts_scan_for_date(df, target_date, meta_dict=None):
    """
    对指定日期运行 MFTS 扫描
    
    Args:
        df: 包含所有历史数据的 DataFrame (已计算指标)
        target_date: 目标日期 (datetime)
        meta_dict: 股票元数据
    
    Returns:
        list: 选中的股票代码列表
    """
    # 获取目标日期的数据
    day_df = df[df['trade_date'] == target_date].copy()
    
    if day_df.empty:
        return []
    
    # 简化的 MFTS 信号逻辑 (L1 抢筹)
    selected = []
    
    for _, row in day_df.iterrows():
        # L1 条件: BIAS < -10 或 Z-Score < -1.96
        bias_cond = row.get('bias', 0) < PARAMS.get('buy_deep', -10)
        z_cond = row.get('z_score', 0) < PARAMS.get('z_buy_deep', -1.96)
        
        # Alpha 评分 >= 阈值
        alpha_cond = row.get('alpha_score', 0) >= PARAMS.get('pass_score_threshold', 4.0)
        
        # 非涨停
        pct = row.get('pct_chg', 0)
        not_limit_up = pct < 9.5
        
        # 流动性
        amount = row.get('amount', 0)
        liquidity_ok = amount >= PARAMS.get('liquidity_threshold', 50000000)
        
        if (bias_cond or z_cond) and not_limit_up and liquidity_ok:
            selected.append(row['ts_code'])
    
    return selected


def backtest_6_months():
    """执行半年回测"""
    print("=" * 70)
    print("MFTS v6.1 半年历史回测")
    print("=" * 70)
    
    # 1. 加载数据
    print("\n[1/4] 加载市场数据...")
    parquet_file = os.path.join(DATA_DIR, "daily_all_5y.parquet")
    
    if not os.path.exists(parquet_file):
        print(f"❌ 数据文件不存在: {parquet_file}")
        return None
    
    df = pd.read_parquet(parquet_file)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = df['ts_code'].astype(str)
    df = df.sort_values(['ts_code', 'trade_date'])
    
    print(f"   数据行数: {len(df):,}")
    print(f"   日期范围: {df['trade_date'].min()} ~ {df['trade_date'].max()}")
    
    # 2. 计算指标
    print("\n[2/4] 计算技术指标...")
    df = calc_indicators(df)
    
    # 3. 获取交易日列表 (过去半年)
    print("\n[3/4] 准备回测...")
    all_dates = sorted(df['trade_date'].unique())
    
    # 需要预留 T+10 的验证数据，所以结束日期提前10天
    end_date = all_dates[-11] if len(all_dates) > 10 else all_dates[-1]
    start_date = end_date - timedelta(days=180)
    
    # 筛选回测日期范围
    backtest_dates = [d for d in all_dates if start_date <= d <= end_date]
    
    print(f"   回测期间: {backtest_dates[0].strftime('%Y-%m-%d')} ~ {backtest_dates[-1].strftime('%Y-%m-%d')}")
    print(f"   交易日数: {len(backtest_dates)}")
    
    # 4. 逐日回测
    print("\n[4/4] 执行回测...")
    results = []
    
    for target_date in tqdm(backtest_dates, desc="回测进度"):
        # 使用截止到当日的数据进行选股
        day_data = df[df['trade_date'] <= target_date]
        
        # 简化的选股 (直接取当日满足条件的)
        day_df = df[df['trade_date'] == target_date].copy()
        
        if day_df.empty:
            continue
        
        # L1 超跌条件
        oversold = (day_df['bias'] < -10) | (day_df['z_score'] < -1.96)
        # 非涨停
        not_limit = day_df['pct_chg'] < 9.5
        # 流动性
        liquid = day_df['amount'] >= 50000000
        
        selected_df = day_df[oversold & not_limit & liquid]
        selected_codes = selected_df['ts_code'].tolist()
        
        if not selected_codes:
            continue
        
        # 计算 T+1, T+5, T+10 收益
        t1_returns = []
        t5_returns = []
        t10_returns = []
        
        date_idx = list(all_dates).index(target_date)
        
        for code in selected_codes:
            code_data = df[df['ts_code'] == code].sort_values('trade_date')
            code_dates = code_data['trade_date'].tolist()
            
            if target_date not in code_dates:
                continue
            
            code_idx = code_dates.index(target_date)
            base_price = code_data[code_data['trade_date'] == target_date]['close'].values[0]
            
            # T+1
            if code_idx + 1 < len(code_dates):
                t1_price = code_data.iloc[code_idx + 1]['close']
                t1_returns.append((t1_price / base_price - 1) * 100)
            
            # T+5
            if code_idx + 5 < len(code_dates):
                t5_price = code_data.iloc[code_idx + 5]['close']
                t5_returns.append((t5_price / base_price - 1) * 100)
            
            # T+10
            if code_idx + 10 < len(code_dates):
                t10_price = code_data.iloc[code_idx + 10]['close']
                t10_returns.append((t10_price / base_price - 1) * 100)
        
        # 记录结果
        result = {
            'date': target_date.strftime('%Y-%m-%d'),
            'picks': len(selected_codes),
        }
        
        if t1_returns:
            result['t1_win_rate'] = (np.array(t1_returns) > 0).mean() * 100
            result['t1_avg_return'] = np.mean(t1_returns)
        
        if t5_returns:
            result['t5_win_rate'] = (np.array(t5_returns) > 0).mean() * 100
            result['t5_avg_return'] = np.mean(t5_returns)
        
        if t10_returns:
            result['t10_win_rate'] = (np.array(t10_returns) > 0).mean() * 100
            result['t10_avg_return'] = np.mean(t10_returns)
        
        results.append(result)
    
    # 5. 汇总结果
    print("\n" + "=" * 70)
    print("回测结果汇总")
    print("=" * 70)
    
    if not results:
        print("❌ 未生成任何结果")
        return None
    
    results_df = pd.DataFrame(results)
    
    # 保存详细结果
    dirs = ensure_output_dirs(OUTPUT_DIR)
    base_dir = Path(OUTPUT_DIR)
    detail_file = dirs["backtest"] / "mfts_backtest_6m.csv"
    legacy_file = base_dir / "mfts_backtest_6m.csv"
    write_dual_csv(results_df, detail_file, legacy_file, index=False, encoding='utf-8-sig')
    print(f"\n详细结果已保存: {detail_file}")
    
    # 统计汇总
    print("\n总体表现:")
    print(f"   回测天数: {len(results_df)}")
    print(f"   平均每日选股: {results_df['picks'].mean():.1f} 只")
    
    if 't1_win_rate' in results_df.columns:
        valid_t1 = results_df.dropna(subset=['t1_win_rate'])
        print(f"\n   T+1 胜率: {valid_t1['t1_win_rate'].mean():.1f}%")
        print(f"   T+1 平均收益: {valid_t1['t1_avg_return'].mean():.2f}%")
    
    if 't5_win_rate' in results_df.columns:
        valid_t5 = results_df.dropna(subset=['t5_win_rate'])
        print(f"\n   T+5 胜率: {valid_t5['t5_win_rate'].mean():.1f}%")
        print(f"   T+5 平均收益: {valid_t5['t5_avg_return'].mean():.2f}%")
    
    if 't10_win_rate' in results_df.columns:
        valid_t10 = results_df.dropna(subset=['t10_win_rate'])
        print(f"\n   T+10 胜率: {valid_t10['t10_win_rate'].mean():.1f}%")
        print(f"   T+10 平均收益: {valid_t10['t10_avg_return'].mean():.2f}%")
    
    print("\n" + "=" * 70)
    print("✅ 回测完成!")
    print("=" * 70)
    
    return results_df


if __name__ == "__main__":
    backtest_6_months()
