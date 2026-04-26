#!/usr/bin/env python3
"""
MFTS 选股引擎 - 服务器轻量版
针对低内存服务器优化，只加载最近数据

使用方法:
    python3 core/mfts_screener_lite.py
"""

import pandas as pd
import numpy as np
import os
import warnings
import gc
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")
META_FILE = os.path.join(DATA_DIR, "stock_info.csv")

# 只加载最近 N 天数据 (节省内存)
DAYS_TO_LOAD = 180  # 6个月足够计算指标

PARAMS = {
    'bias_len': 20,
    'buy_deep': -10.0,
    'buy_mid': -7.0,
    'buy_light': -5.0,
    'z_buy_deep': -1.96,
    'z_buy_mid': -1.50,
    'pass_score_threshold': 4.0,
    'liquidity_threshold': 50000000,
    'strict_limit_filter': True,
    'enable_vwap_filter': False,
    'new_stock_days': 60,
}


def load_data_lite():
    """轻量级数据加载 - 只加载最近数据"""
    if not os.path.exists(PARQUET_FILE):
        print(f"Error: 数据文件不存在: {PARQUET_FILE}")
        return None
    
    print(f"加载数据 (仅最近 {DAYS_TO_LOAD} 天)...")
    
    # 读取全部数据但只保留最近日期
    df = pd.read_parquet(PARQUET_FILE)
    
    # 转换日期
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    
    # 只保留最近 N 天
    latest_date = df['trade_date'].max()
    cutoff_date = latest_date - timedelta(days=DAYS_TO_LOAD)
    df = df[df['trade_date'] >= cutoff_date].copy()
    
    print(f"日期范围: {df['trade_date'].min().date()} ~ {latest_date.date()}")
    print(f"数据量: {len(df):,} 行, {df['ts_code'].nunique():,} 只股票")
    
    # 内存优化
    df['ts_code'] = df['ts_code'].astype('category')
    
    # 数值类型优化
    float_cols = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    for col in float_cols:
        if col in df.columns:
            df[col] = df[col].astype('float32')
    
    df = df.sort_values(['ts_code', 'trade_date'])
    
    mem_mb = df.memory_usage(deep=True).sum() / 1024**2
    print(f"内存占用: {mem_mb:.1f} MB")
    
    gc.collect()
    return df


def load_metadata():
    if not os.path.exists(META_FILE):
        return {}
    try:
        meta_df = pd.read_csv(META_FILE, dtype={'ts_code': str})
        return meta_df.set_index('ts_code').to_dict('index')
    except:
        return {}


def get_limit_ratio(ts_code, name=''):
    if 'ST' in name.upper():
        return 0.05
    elif ts_code.startswith('688') or ts_code.startswith('30'):
        return 0.20
    elif ts_code.startswith('8') or ts_code.startswith('4'):
        return 0.30
    else:
        return 0.10


def calc_indicators_lite(df):
    """轻量级指标计算"""
    print("计算指标 (轻量模式)...")
    
    grouped = df.groupby('ts_code', observed=True)
    
    # 基础均线
    df['ma5'] = grouped['close'].transform(lambda x: x.rolling(5).mean())
    df['ma20'] = grouped['close'].transform(lambda x: x.rolling(20).mean())
    df['ma120'] = grouped['close'].transform(lambda x: x.rolling(120).mean())
    df['vol_ma5'] = grouped['vol'].transform(lambda x: x.rolling(5).mean())
    df['vol_ma20'] = grouped['vol'].transform(lambda x: x.rolling(20).mean())
    df['amount_ma20'] = grouped['amount'].transform(lambda x: x.rolling(20).mean())
    
    # Shifted values
    df['close_1'] = grouped['close'].shift(1)
    df['close_5'] = grouped['close'].shift(5)
    
    # Z-Score & BIAS
    df['log_close'] = np.log(df['close'])
    df['log_ma'] = grouped['log_close'].transform(lambda x: x.rolling(PARAMS['bias_len']).mean())
    df['log_std'] = grouped['log_close'].transform(lambda x: x.rolling(PARAMS['bias_len']).std())
    df['z_score'] = np.where(df['log_std'] > 0, (df['log_close'] - df['log_ma']) / df['log_std'], 0.0)
    
    df['ma_bias_base'] = np.exp(df['log_ma'])
    df['bias'] = (df['close'] - df['ma_bias_base']) / df['ma_bias_base'] * 100
    
    # 动量
    df['mom_5'] = grouped['close'].transform(lambda x: x.pct_change(5))
    df['mom_20'] = grouped['close'].transform(lambda x: x.pct_change(20))
    
    # RSI (简化版)
    delta = grouped['close'].diff()
    gain = delta.where(delta > 0, 0).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = grouped.apply(lambda x: x['close'].diff().where(x['close'].diff() > 0, 0).rolling(14).mean()).reset_index(level=0, drop=True)
    avg_loss = grouped.apply(lambda x: (-x['close'].diff().where(x['close'].diff() < 0, 0)).rolling(14).mean()).reset_index(level=0, drop=True)
    df['rsi'] = 100 - (100 / (1 + avg_gain / avg_loss.replace(0, np.nan)))
    
    # ADX (简化版)
    df['adx'] = 25  # 使用默认值，节省计算
    df['plus_di'] = 25
    df['minus_di'] = 20
    
    # 高位判断
    df['high_250'] = grouped['high'].transform(lambda x: x.rolling(min(250, len(x)), min_periods=20).max())
    df['distance_from_high_pct'] = (df['high_250'] - df['close']) / df['high_250'] * 100
    df['is_high_position'] = df['distance_from_high_pct'] < 10
    
    # 其他必要字段
    range_hl = df['high'] - df['low']
    df['clv'] = np.where(range_hl > 0, ((df['close'] - df['low']) - (df['high'] - df['close'])) / range_hl, 0.0)
    df['spread'] = range_hl
    df['avg_spread'] = grouped['spread'].transform(lambda x: x.rolling(20).mean())
    df['lower_wick'] = np.minimum(df['close'], df['open']) - df['low']
    df['lower_wick_pct'] = np.where(range_hl > 0, df['lower_wick'] / range_hl, 0.0)
    df['is_high_volume'] = df['vol'] > df['vol_ma20'] * 1.5
    df['is_narrow_spread'] = df['spread'] < df['avg_spread'] * 0.7
    df['close_position'] = np.where(range_hl > 0, (df['close'] - df['low']) / range_hl, 0.5)
    
    # 上市天数
    df['days_listed'] = grouped.cumcount() + 1
    
    # 高20日 (用于突破)
    df['high_20_prev'] = grouped['high'].transform(lambda x: x.shift(1).rolling(20).max())
    
    # MACD (简化)
    df['macd'] = 0
    df['macd_signal'] = 0
    
    gc.collect()
    return df


def calculate_alpha_score_lite(row, adaptive_buy_deep, adaptive_buy_mid):
    """简化版 Alpha 评分"""
    points = 0.0
    
    # 飞刀检测
    is_falling_knife = (row['clv'] < -0.7) and (row['spread'] > row['avg_spread'] * 1.5) and (row['close'] < row['open'])
    if is_falling_knife:
        return -5.0
    
    # 动量因子
    if row['mom_5'] < -0.15:
        points += 2.0
    elif row['mom_5'] < -0.08:
        points += 1.2
    
    if row['mom_20'] < -0.25:
        points += 2.5
    elif row['mom_20'] < -0.15:
        points += 1.5
    
    # BIAS
    if row['bias'] < adaptive_buy_deep * 1.3:
        points += 2.0
    elif row['bias'] < adaptive_buy_deep:
        points += 1.0
    
    # Z-Score
    if row['z_score'] < PARAMS['z_buy_deep']:
        points += 1.0
    
    # RSI
    if not pd.isna(row['rsi']) and row['rsi'] < 30:
        points += 0.6
    
    return points


def scan_lite(df, meta_dict=None):
    """轻量级扫描"""
    target_date = df['trade_date'].max()
    print(f"扫描日期: {target_date.date()}")
    
    if meta_dict is None:
        meta_dict = {}
    
    today_df = df[df['trade_date'] == target_date].copy()
    results = []
    
    for _, row in today_df.iterrows():
        ts_code = str(row['ts_code'])
        stock_name = meta_dict.get(ts_code, {}).get('name', '')
        
        # 基础过滤
        if pd.isna(row['ma20']) or pd.isna(row['vol_ma20']):
            continue
        if row['days_listed'] < PARAMS['new_stock_days']:
            continue
        
        limit_ratio = get_limit_ratio(ts_code, stock_name)
        
        # 跌停过滤
        if row['pct_chg'] < -limit_ratio * 100 * 0.9:
            continue
        
        # 流动性
        vol_ratio = row['vol'] / row['vol_ma20'] if row['vol_ma20'] > 0 else 1.0
        is_extreme_oversold = (row['bias'] < -15) or (row['z_score'] < -2.5)
        is_deep_oversold = (row['bias'] < -10) or (row['z_score'] < -2.0)
        
        if is_extreme_oversold:
            liquidity_ok = True
        elif is_deep_oversold:
            liquidity_ok = row['amount_ma20'] > PARAMS['liquidity_threshold'] and vol_ratio > 0.4
        else:
            liquidity_ok = row['amount_ma20'] > PARAMS['liquidity_threshold'] and vol_ratio > 0.6
        
        if not liquidity_ok:
            continue
        
        # 动态阈值
        adaptive_buy_deep = PARAMS['buy_deep']
        adaptive_buy_mid = PARAMS['buy_mid']
        
        # Alpha 评分
        score = calculate_alpha_score_lite(row, adaptive_buy_deep, adaptive_buy_mid)
        
        # 信号判定
        signals = []
        
        is_deep_os = (row['z_score'] < PARAMS['z_buy_deep']) or (row['bias'] < adaptive_buy_deep)
        cond_red = row['close'] > row['open']
        cond_shrink = row['vol'] < row['vol_ma5'] * 1.2
        
        if is_deep_os and (cond_red or cond_shrink) and score >= 2.0:
            signals.append("抢筹 (L1)")
        
        is_mid_os = (row['z_score'] < PARAMS['z_buy_mid']) or (row['bias'] < adaptive_buy_mid)
        if is_mid_os and not is_deep_os and score >= PARAMS['pass_score_threshold']:
            signals.append("建仓 (L2)")
        
        if signals:
            results.append({
                '代码': ts_code,
                '名称': stock_name,
                '信号': " | ".join(signals),
                '收盘': round(row['close'], 2),
                '涨幅%': round(row['pct_chg'], 2),
                'Alpha评分': round(score, 1),
                'Z-Score': round(row['z_score'], 2),
                'BIAS': round(row['bias'], 2),
                '超跌等级': '极度' if is_extreme_oversold else ('深度' if is_deep_oversold else '普通')
            })
    
    return pd.DataFrame(results)


def main():
    print("=" * 60)
    print("MFTS v6.1 选股引擎 - 服务器轻量版")
    print("=" * 60)
    
    df = load_data_lite()
    if df is None:
        return
    
    meta_dict = load_metadata()
    df = calc_indicators_lite(df)
    
    # 清理
    df = df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
    gc.collect()
    
    # 扫描
    res = scan_lite(df, meta_dict)
    
    if not res.empty:
        scan_date = df['trade_date'].max().strftime('%Y%m%d')
        
        print(f"\n[MFTS Lite] 选股结果 ({len(res)} 只) - {scan_date}:")
        print(res[['代码', '名称', '信号', '涨幅%', 'Alpha评分', '超跌等级']].head(20))
        
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        dated_file = os.path.join(OUTPUT_DIR, f"mfts_scan_{scan_date}.csv")
        res.to_csv(dated_file, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存: {dated_file}")
        
        latest_file = os.path.join(OUTPUT_DIR, "mfts_latest.csv")
        res.to_csv(latest_file, index=False, encoding='utf-8-sig')
    else:
        print("\n今日无符合标准的标的。")


if __name__ == "__main__":
    main()
