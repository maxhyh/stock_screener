#!/usr/bin/env python3
"""
批量生成历史选股结果

使用方法:
    python scripts/history/generate_historical_scans.py
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))

from mfts_screener import load_data, load_metadata, calc_indicators, scan, format_output
import pandas as pd

# 要生成的日期列表
dates_to_generate = [
    '20260105', '20260106', '20260107', '20260108', '20260109', '20260112'
]

print("=" * 70)
print("批量生成历史选股结果")
print("=" * 70)

# 加载数据
print("\n加载数据...")
df = load_data()
meta_dict = load_metadata()

print("计算指标...")
df = calc_indicators(df)

# 批量生成
output_dir = os.path.join(BASE_DIR, 'output')
os.makedirs(output_dir, exist_ok=True)

for date_str in dates_to_generate:
    try:
        target_date = pd.Timestamp(date_str)
        print(f"\n处理 {date_str}...")
        
        res = scan(df, target_date=target_date, meta_dict=meta_dict)
        
        if not res.empty:
            final_res = format_output(res, meta_dict)
            output_file = os.path.join(output_dir, f"mfts_scan_{date_str}.csv")
            final_res.to_csv(output_file, index=False, encoding='utf-8-sig')
            print(f"  ✅ 生成成功: {len(final_res)}只股票 -> {output_file}")
        else:
            print(f"  ⚠️ 无符合条件的股票")
    except Exception as e:
        print(f"  ❌ 错误: {e}")

print("\n" + "=" * 70)
print("完成!")
print("=" * 70)
