#!/usr/bin/env python3
"""
批量生成 ML 预测数据
用于补全缺失的历史预测
"""
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from scripts.daily_ml_select import select_stocks, load_latest_data

def get_trading_dates(start_date, end_date):
    """获取日期范围内的交易日"""
    try:
        df = load_latest_data()
        all_dates = pd.to_datetime(df['trade_date'].unique())
        # Fix for DatetimeArray sort
        if hasattr(all_dates, 'sort_values'):
            dates = all_dates.sort_values()
        else:
            dates = pd.Series(all_dates).sort_values()
        
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        
        mask = (dates >= start) & (dates <= end)
        return dates[mask].dt.strftime('%Y%m%d').tolist()
    except Exception as e:
        print(f"Error loading dates: {e}")
        return []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, required=True, help='Start date YYYYMMDD')
    parser.add_argument('--end', type=str, required=True, help='End date YYYYMMDD')
    args = parser.parse_args()
    
    dates = get_trading_dates(args.start, args.end)
    print(f"Found {len(dates)} trading dates between {args.start} and {args.end}")
    
    for date_str in dates:
        print(f"\nProcessing {date_str}...")
        try:
            select_stocks(target_date=date_str, top_n=50) 
        except Exception as e:
            print(f"Failed to process {date_str}: {e}")

if __name__ == "__main__":
    main()
