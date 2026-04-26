#!/usr/bin/env python3
"""
生成过去半年的历史扫描数据 - 优化版
一次性计算指标，然后对每个日期进行快速扫描

使用方法:
    python scripts/history/generate_historical_scans_6m.py
"""

import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime, timedelta
from tqdm import tqdm
import warnings

warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")

# 导入核心扫描函数
from core.mfts_screener import calc_indicators, load_metadata, PARAMS


def get_trading_dates(df, start_date, end_date):
    """获取指定范围内的交易日列表"""
    dates = df['trade_date'].unique()
    dates = sorted([d for d in dates if start_date <= d <= end_date])
    return dates


def fast_scan_for_date(df_with_indicators, target_date, meta_dict):
    """对指定日期进行快速扫描（使用预计算的指标）"""
    # 获取目标日期的数据
    df_target = df_with_indicators[df_with_indicators['trade_date'] == target_date].copy()
    
    if df_target.empty:
        return None
    
    # 简化的信号检测逻辑
    results = []
    
    for _, row in df_target.iterrows():
        signals = []
        level = '普通'
        
        # 检查 NaN
        if pd.isna(row.get('bias', np.nan)) or pd.isna(row.get('z_score', np.nan)):
            continue
        
        bias = row.get('bias', 0)
        z_score = row.get('z_score', 0)
        rsi = row.get('rsi', 50)
        vol_ratio = row.get('vol_ratio', 1)
        alpha = row.get('alpha_score', 0) if 'alpha_score' in row else 0
        
        # 超跌等级判断
        if bias < -15 or z_score < -2.5:
            level = '极度'
        elif bias < -10 or z_score < -1.96:
            level = '深度'
        
        # L1 抢筹信号
        if bias < PARAMS['buy_deep'] and z_score < PARAMS['z_buy_deep']:
            signals.append('抢筹 (L1)')
        
        # L2 建仓信号
        if bias < PARAMS['buy_mid'] and z_score < PARAMS['z_buy_mid'] and rsi < 40:
            if '抢筹 (L1)' not in signals:
                signals.append('建仓 (L2)')
        
        # 趋势信号 (简化版)
        pct_chg = row.get('pct_chg', 0)
        if pct_chg > 3 and vol_ratio > 1.5:
            signals.append('趋势:突破')
        elif pct_chg > 2 and 0 < pct_chg < 5:
            signals.append('趋势:动量')
        
        if signals:
            code = str(row.get('ts_code', '')).replace('.SZ', '').replace('.SH', '')
            name = meta_dict.get(code, {}).get('name', row.get('name', ''))
            
            results.append({
                '代码': code,
                '名称': name,
                '信号': ' | '.join(signals),
                '涨幅%': round(pct_chg, 2) if not pd.isna(pct_chg) else 0,
                '行业': meta_dict.get(code, {}).get('industry', ''),
                'Alpha评分': round(alpha, 1) if not pd.isna(alpha) else 0,
                'Z-Score': round(z_score, 2) if not pd.isna(z_score) else 0,
                'BIAS': round(bias, 2) if not pd.isna(bias) else 0,
                'Vol比': round(vol_ratio, 0) if not pd.isna(vol_ratio) else 1,
                '高位': '否',
                '超跌等级': level,
                '收盘': round(row.get('close', 0), 2)
            })
    
    if results:
        return pd.DataFrame(results)
    return None


def main():
    print("=" * 60)
    print("生成半年历史扫描数据 (优化版)")
    print("=" * 60)
    print()
    
    # 加载数据
    print("📊 加载市场数据...")
    df = pd.read_parquet(PARQUET_FILE)
    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')
    print(f"✅ 加载 {len(df)} 条数据")
    
    # 加载元数据
    meta_dict = load_metadata()
    
    # 确定日期范围（最近 6 个月）
    end_date = df['trade_date'].max()
    end_dt = datetime.strptime(end_date, '%Y%m%d')
    start_dt = end_dt - timedelta(days=180)
    start_date = start_dt.strftime('%Y%m%d')
    
    print(f"📅 扫描日期范围: {start_date} - {end_date}")
    
    # 获取交易日列表
    trading_dates = get_trading_dates(df, start_date, end_date)
    print(f"📆 共 {len(trading_dates)} 个交易日")
    
    # 检查已存在的扫描文件
    existing_files = set()
    for f in os.listdir(OUTPUT_DIR):
        if f.startswith('mfts_scan_') and f.endswith('.csv'):
            date_str = f.replace('mfts_scan_', '').replace('.csv', '')
            existing_files.add(date_str)
    
    # 只处理缺失的日期
    missing_dates = [d for d in trading_dates if d not in existing_files]
    print(f"📝 需要生成 {len(missing_dates)} 个日期的扫描结果")
    
    if not missing_dates:
        print("✅ 所有日期已有扫描结果，无需重新生成")
        return
    
    # 只保留需要的日期范围数据
    df = df[df['trade_date'] >= start_date].copy()
    
    # 一次性计算所有指标
    print("🔧 预计算指标 (这可能需要几分钟)...")
    df = calc_indicators(df)
    print("✅ 指标计算完成")
    
    # 计算 vol_ratio
    if 'vol_ma5' in df.columns and 'vol' in df.columns:
        df['vol_ratio'] = df['vol'] / df['vol_ma5']
        df['vol_ratio'] = df['vol_ratio'].fillna(1).clip(0, 10)
    else:
        df['vol_ratio'] = 1
    
    # 逐日快速扫描
    success_count = 0
    for date in tqdm(missing_dates, desc="生成扫描结果"):
        results = fast_scan_for_date(df, date, meta_dict)
        
        if results is not None and not results.empty:
            output_file = os.path.join(OUTPUT_DIR, f"mfts_scan_{date}.csv")
            results.to_csv(output_file, index=False, encoding='utf-8-sig')
            success_count += 1
    
    print()
    print("=" * 60)
    print(f"✅ 生成完成！成功 {success_count}/{len(missing_dates)} 个日期")
    print("=" * 60)


if __name__ == '__main__':
    main()
