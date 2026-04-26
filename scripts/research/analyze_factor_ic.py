#!/usr/bin/env python3
"""
MFTS因子IC分析 - 真正的流式处理版本

关键改进：
1. 逐只股票处理，而非一次性全部加载
2. 每处理100只股票输出一次IC
3. 及时释放内存
4. 只保留最终IC统计，不保留全量数据
"""

import pandas as pd
import numpy as np
import os
import sys
import gc
from scipy.stats import spearmanr
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))

from mfts_screener import calc_indicators

DATA_FILE = os.path.join(BASE_DIR, "data/daily_all_5y.parquet")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# 因子定义
FACTORS = {
    'BIAS-20': 'bias',
    'Z-Score': 'z_score',
    'BIAS-13': 'bias13',
    'Momentum-5': 'mom_5',
    'Momentum-20': 'mom_20',
    'Volume Ratio': 'vol_ratio',
    'PV Corr-5': 'pv_corr_5',
    'PV Corr-20': 'pv_corr_20',
    'RSI-14': 'rsi',
    'MACD Hist': 'macd_hist',
    'KDJ-J': 'j_val',
    'MFI': 'mfi',
    'BB Position': 'bb_pos',
    '52W Position': 'pos_52w',
    'ATR %': 'atr_percent',
    'ADX': 'adx',
    'Volatility Ratio': 'volatility_ratio',
    # [v3.0] 正交因子
    'Smart Money': 'smart_money_ratio',
    'RS-5d': 'rs_5d',
    'RS-20d': 'rs_20d',
    'Vol Compression': 'vol_compression',
    'Gap Z-Score': 'gap_zscore',
    'VP Divergence': 'vp_divergence',
}

BATCH_SIZE = 100  # 每批处理100只股票
START_DATE = '20150101'
END_DATE = '20221231' # [Fix] Limit to training data end (Anti-Leakage)


def calculate_ic(factor_series, return_series):
    """计算IC"""
    valid = ~(factor_series.isna() | return_series.isna())
    if valid.sum() < 10:
        return np.nan
    try:
        corr, _ = spearmanr(factor_series[valid], return_series[valid])
        return corr
    except Exception:
        return np.nan


def process_stock_batch(stock_codes, all_data):
    """处理一批股票"""
    # 只取这批股票的数据
    batch_df = all_data[all_data['ts_code'].isin(stock_codes)].copy()
    
    if len(batch_df) == 0:
        return None
    
    # 计算指标（只对这批股票）
    batch_df = batch_df.sort_values(['ts_code', 'trade_date'])
    batch_df = calc_indicators(batch_df)
    batch_df = batch_df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
    
    # 计算未来收益
    batch_df['return_t1'] = batch_df.groupby('ts_code')['pct_chg'].shift(-1)
    batch_df['vol_ratio'] = batch_df['vol'] / batch_df['vol_ma20']
    
    # 按日期计算IC
    ic_results = []
    for date in batch_df['trade_date'].unique():
        day_df = batch_df[batch_df['trade_date'] == date]
        if len(day_df) < 5:  # 至少5只股票
            continue
        
        date_ic = {'date': date, 'stock_count': len(day_df)}
        for factor_name, factor_col in FACTORS.items():
            if factor_col in day_df.columns:
                ic = calculate_ic(day_df[factor_col], day_df['return_t1'])
                date_ic[factor_name] = ic
        
        ic_results.append(date_ic)
    
    return pd.DataFrame(ic_results) if ic_results else None


def main():
    print("=" * 70)
    print("MFTS因子IC分析 - 流式处理版")
    print("=" * 70)
    
    # 【关键】只加载原始数据，不计算指标
    print("\n加载原始数据...")
    columns_needed = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    df = pd.read_parquet(DATA_FILE, columns=columns_needed)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = df['ts_code'].astype(str)
    
    # 使用2015-2025年数据（10年完整数据）
    # [Fix] Date Filtering for Anti-Leakage
    # Only use data up to END_DATE for Feature Selection Analysis
    print(f"Applying Date Filter: {START_DATE} ~ {END_DATE}")
    df = df[(df['trade_date'] >= pd.to_datetime(START_DATE)) & 
            (df['trade_date'] <= pd.to_datetime(END_DATE))]
    print(f"数据规模: {len(df):,} 行 ({START_DATE}-{END_DATE})")
    
    # 获取所有股票列表
    all_stocks = sorted(df['ts_code'].unique())
    print(f"股票数量: {len(all_stocks):,}")
    
    # 【关键】分批处理股票
    print(f"\n开始分批处理（每批{BATCH_SIZE}只股票）...")
    all_ic_results = []
    
    for i in range(0, len(all_stocks), BATCH_SIZE):
        batch_stocks = all_stocks[i:i+BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(all_stocks) + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"  批次 {batch_num}/{total_batches}: 处理股票 {len(batch_stocks)} 只...")
        
        try:
            ic_batch = process_stock_batch(batch_stocks, df)
            if ic_batch is not None:
                all_ic_results.append(ic_batch)
        except Exception as e:
            print(f"    警告: 批次{batch_num}处理失败: {e}")
            continue
        
        # 强制释放内存
        gc.collect()
        
        if batch_num % 10 == 0:
            print(f"    已处理 {batch_num * BATCH_SIZE} 只股票...")
    
    if not all_ic_results:
        print("\n❌ 错误: 没有成功处理任何数据")
        return
    
    # 合并所有IC结果（按日期聚合）
    print("\n合并IC结果...")
    all_ic_df = pd.concat(all_ic_results, ignore_index=True)
    
    # 按日期聚合IC（取平均值）
    ic_df = all_ic_df.groupby('date').agg({
        col: 'mean' for col in FACTORS.keys() if col in all_ic_df.columns
    }).reset_index()
    
    print(f"有效日期数: {len(ic_df)}")
    
    # 计算统计
    print("\n" + "=" * 70)
    print("因子IC统计（10年数据，2015-2025）")
    print("=" * 70)
    print(f"{'因子名称':<20} {'均值IC':>10} {'IC标准差':>10} {'ICIR':>10} {'胜率%':>10}")
    print("-" * 70)
    
    results = []
    for factor_name in FACTORS.keys():
        if factor_name in ic_df.columns:
            ic_series = ic_df[factor_name].dropna()
            if len(ic_series) > 0:
                mean_ic = ic_series.mean()
                std_ic = ic_series.std()
                icir = mean_ic / std_ic if std_ic > 0 else 0
                win_rate = (ic_series > 0).mean() * 100
                
                results.append({
                    'Factor': factor_name,
                    'Mean_IC': mean_ic,
                    'Std_IC': std_ic,
                    'ICIR': icir,
                    'Win_Rate': win_rate
                })
                
                print(f"{factor_name:<20} {mean_ic:>10.4f} {std_ic:>10.4f} {icir:>10.3f} {win_rate:>10.1f}")
    
    # 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results_df = pd.DataFrame(results).sort_values('Mean_IC', key=abs, ascending=False)
    
    output_file = os.path.join(OUTPUT_DIR, "factor_ic_analysis_T1.csv")
    results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    
    ic_file = os.path.join(OUTPUT_DIR, "ic_timeseries_T1.csv")
    ic_df.to_csv(ic_file, index=False, encoding='utf-8-sig')
    
    print("\n" + "=" * 70)
    print("Top 5 最强因子:")
    print("=" * 70)
    for i, row in results_df.head(5).iterrows():
        print(f"{i+1}. {row['Factor']}: IC={row['Mean_IC']:.4f}, ICIR={row['ICIR']:.3f}")
    
    print(f"\n✅ IC分析完成!")
    print(f"结果已保存:")
    print(f"  - {output_file}")
    print(f"  - {ic_file}")
    
    return results_df


if __name__ == "__main__":
    main()
