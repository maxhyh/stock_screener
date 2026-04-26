"""
MFTS Data Adapter for Server
将服务器的Tushare CSV数据转换为MFTS所需的Parquet格式
"""

import pandas as pd
import os
from datetime import datetime

# 服务器数据路径
TUSHARE_DATA_DIR = "/root/.qlib/tushare_data"
DAILY_CSV = os.path.join(TUSHARE_DATA_DIR, "daily.csv")
OUTPUT_DIR = "/root/qlib_project/mfts/data"

def convert_tushare_to_mfts_format():
    """
    将Tushare CSV转换为MFTS Parquet格式
    """
    print("Loading Tushare data...")
    
    # 读取Tushare数据
    df = pd.read_csv(DAILY_CSV)
    
    # Tushare列名映射
    column_mapping = {
        'ts_code': 'ts_code',
        'trade_date': 'trade_date',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'vol': 'vol',  # 单位：手
        'amount': 'amount',  # 单位：千元
        'pct_chg': 'pct_chg'
    }
    
    # 选择需要的列
    required_cols = list(column_mapping.keys())
    df = df[required_cols]
    
    # 数据类型转换
    df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
    df['ts_code'] = df['ts_code'].astype(str)
    
    # 数值列转换
    numeric_cols = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 单位转换：MFTS 全链路统一使用“vol=手、amount=元”
    # Tushare daily 的 vol 本身就是“手”，这里不再乘 100，避免量能因子被放大 100 倍。
    # amount 单位千元 -> 元
    df['amount'] = df['amount'] * 1000
    
    # 排序
    df = df.sort_values(['ts_code', 'trade_date'])
    
    # 保存为Parquet
    output_file = os.path.join(OUTPUT_DIR, "daily_all_5y.parquet")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print(f"Converting {len(df)} rows...")
    df.to_parquet(output_file, index=False, compression='snappy')
    
    print(f"✅ Conversion complete: {output_file}")
    print(f"   Total rows: {len(df):,}")
    print(f"   Stocks: {df['ts_code'].nunique():,}")
    print(f"   Date range: {df['trade_date'].min()} to {df['trade_date'].max()}")
    
    return output_file

if __name__ == "__main__":
    convert_tushare_to_mfts_format()
