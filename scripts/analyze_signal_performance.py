#!/usr/bin/env python3
"""
信号绩效分析脚本
分析历史扫描结果中不同信号类型和超跌等级的表现

使用方法:
    python scripts/analyze_signal_performance.py
"""

import pandas as pd
import numpy as np
import os
import glob
import json
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from utils.output_paths import ensure_output_dirs, list_dual
from core.data.market_data_gateway import AShareMarketDataGateway

OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STATS_FILE = os.path.join(OUTPUT_DIR, "backtest", "signal_stats.json")
LEGACY_STATS_FILE = os.path.join(OUTPUT_DIR, "signal_stats.json")


def write_dual_json(data, new_path: Path, legacy_path: Path) -> None:
    new_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    with open(new_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if legacy_path.resolve() != new_path.resolve():
        with open(legacy_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def is_valid_scan_file(file_path):
    """校验扫描结果文件结构，过滤异常导出的全量指标文件。"""
    try:
        cols = pd.read_csv(file_path, nrows=0, encoding='utf-8-sig').columns
    except Exception:
        return False
    required = {'代码', '信号'}
    # 正常扫描结果约 10~20 列；异常原始表通常 100+ 列
    return required.issubset(set(cols)) and len(cols) <= 30


def load_historical_scans(start_date=None, end_date=None):
    """加载历史扫描结果
    
    Args:
        start_date: 开始日期 (YYYYMMDD)，默认 None 表示不限制
        end_date: 结束日期 (YYYYMMDD)，默认 None 表示不限制
    """
    dirs = ensure_output_dirs(OUTPUT_DIR)
    files = list_dual(["mfts_scan_*.csv"], dirs["scan"], dirs["base"])
    
    if not files:
        print("❌ 未找到历史扫描文件")
        return None
    
    # 按日期过滤文件
    if start_date or end_date:
        filtered_files = []
        for f in files:
            date_str = f.name.replace("mfts_scan_", "").replace(".csv", "")
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                continue
            filtered_files.append(f)
        files = filtered_files
    
    print(f"📂 找到 {len(files)} 个历史扫描文件")
    
    all_data = []
    skipped_invalid = 0
    for f in files:
        try:
            # 从文件名提取日期
            date_str = f.name.replace("mfts_scan_", "").replace(".csv", "")
            if not is_valid_scan_file(f):
                skipped_invalid += 1
                print(f"  ⚠️ 跳过结构异常文件: {f.name}")
                continue
            df = pd.read_csv(f, encoding='utf-8-sig')
            df['scan_date'] = date_str
            all_data.append(df)
        except Exception as e:
            print(f"  ⚠️ 跳过 {f}: {e}")
    
    if not all_data:
        return None
    
    combined = pd.concat(all_data, ignore_index=True)
    print(f"✅ 加载 {len(combined)} 条历史记录")
    if skipped_invalid:
        print(f"ℹ️ 已跳过 {skipped_invalid} 个结构异常文件")
    return combined


def load_market_data(start_date: str, end_date: str):
    """从共享只读 ODS 加载计算收益所需的有界市场窗口。"""
    print("📊 从共享只读 ODS 加载市场数据...")
    gateway = AShareMarketDataGateway()
    df = gateway.load_bars(start_date, end_date, include_bj9=True, forward_sessions=10)
    if df.empty:
        print("❌ 共享 ODS 未返回市场数据")
        return None
    
    # 确保日期格式一致
    if 'trade_date' in df.columns:
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')
    
    print(f"✅ 加载 {len(df)} 条市场数据")
    return df


def calculate_returns(scans_df, market_df):
    """计算每个信号的 T+1, T+5, T+10 收益"""
    print("📈 计算收益率...")
    
    results = []
    
    # 优化：预处理市场数据为字典 {code: df}
    print("  ⚡️ 预处理市场数据索引...")
    market_df = market_df.sort_values(['ts_code', 'trade_date'])
    market_dict = dict(tuple(market_df.groupby('ts_code')))
    
    for _, row in scans_df.iterrows():
        code = str(row['代码']).zfill(6)  # 确保是字符串并补齐6位
        scan_date = row['scan_date']
        signal = row.get('信号', '未知')
        level = row.get('超跌等级', '普通')
        
        # 市场数据使用纯数字格式
        code_full = code
        
        # 优化：直接从字典获取，避免全表扫描
        stock_data = market_dict.get(code_full)
        if stock_data is None or stock_data.empty:
            continue
        
        # 找到信号日期之后的交易日
        future_data = stock_data[stock_data['trade_date'] > scan_date].head(11)
        if len(future_data) < 2:
            continue
        
        # 信号日收盘价
        # 优化：使用 searchsorted 可能会更快，但这里数据量小，布尔索引尚可
        signal_day = stock_data[stock_data['trade_date'] == scan_date]
        if signal_day.empty:
            # 尝试找最近的交易日
            before = stock_data[stock_data['trade_date'] <= scan_date].tail(1)
            if before.empty:
                continue
            base_price = before['close'].iloc[0]
        else:
            base_price = signal_day['close'].iloc[0]
        
        result = {
            'code': code,
            'signal': signal,
            'level': level,
            'scan_date': scan_date,
        }
        
        # 计算 T+1, T+5, T+10 收益
        for t, name in [(1, 't1'), (5, 't5'), (10, 't10')]:
            if len(future_data) >= t:
                future_price = future_data['close'].iloc[t-1]
                ret = (future_price - base_price) / base_price * 100
                result[f'{name}_return'] = round(ret, 2)
                result[f'{name}_win'] = 1 if ret > 0 else 0
            else:
                result[f'{name}_return'] = None
                result[f'{name}_win'] = None
        
        results.append(result)
    
    print(f"✅ 计算完成 {len(results)} 条有效记录")
    return pd.DataFrame(results)


def analyze_by_group(returns_df, group_col, group_name):
    """按指定列分组分析"""
    stats = {}
    
    for group_val, group_data in returns_df.groupby(group_col):
        stat = {
            'count': len(group_data),
        }
        
        for t in ['t1', 't5', 't10']:
            ret_col = f'{t}_return'
            win_col = f'{t}_win'
            
            valid = group_data[group_data[ret_col].notna()]
            if len(valid) > 0:
                stat[f'{t}_avg_return'] = round(valid[ret_col].mean(), 2)
                stat[f'{t}_win_rate'] = round(valid[win_col].mean() * 100, 1)
                stat[f'{t}_sample'] = len(valid)
            else:
                stat[f'{t}_avg_return'] = None
                stat[f'{t}_win_rate'] = None
                stat[f'{t}_sample'] = 0
        
        stats[group_val] = stat
    
    return stats


def analyze_by_month(returns_df):
    """按月份分组分析"""
    # 提取月份
    returns_df['month'] = pd.to_datetime(returns_df['scan_date']).dt.strftime('%Y-%m')
    
    stats = {}
    for month, group_data in returns_df.groupby('month'):
        stat = {
            'count': len(group_data),
        }
        
        for t in ['t1', 't5']:
            ret_col = f'{t}_return'
            win_col = f'{t}_win'
            
            valid = group_data[group_data[ret_col].notna()]
            if len(valid) > 0:
                stat[f'{t}_avg_return'] = round(valid[ret_col].mean(), 2)
                stat[f'{t}_win_rate'] = round(valid[win_col].mean() * 100, 1)
            else:
                stat[f'{t}_avg_return'] = 0
                stat[f'{t}_win_rate'] = 0
        
        stats[month] = stat
        
    return stats


def export_daily_summary(returns_df):
    """导出每日汇总数据，兼容回测页面格式"""
    daily_stats = []
    
    for date, group in returns_df.groupby('scan_date'):
        row = {
            'date': date,
            'picks': len(group),
        }
        
        for t in ['t1', 't5', 't10']:
            ret_col = f'{t}_return'
            win_col = f'{t}_win'
            
            valid = group[group[ret_col].notna()]
            if len(valid) > 0:
                row[f'{t}_avg'] = round(valid[ret_col].mean(), 2)
                row[f'{t}_win'] = round(valid[win_col].mean() * 100, 1)
            else:
                row[f'{t}_avg'] = 0
                row[f'{t}_win'] = 0
                
        daily_stats.append(row)
    
    df = pd.DataFrame(daily_stats)
    # 按日期排序
    df = df.sort_values('date')
    
    # 保存文件
    dirs = ensure_output_dirs(OUTPUT_DIR)
    outfile = dirs["backtest"] / "mfts_backtest_auto.csv"
    legacy = dirs["base"] / "mfts_backtest_auto.csv"
    df.to_csv(outfile, index=False)
    if outfile.resolve() != legacy.resolve():
        df.to_csv(legacy, index=False)
    print(f"✅ 每日汇总已保存: {outfile}")


def main(start_date=None, end_date=None):
    print("=" * 60)
    print("信号绩效分析")
    print("=" * 60)
    
    if start_date or end_date:
        print(f"📅 日期范围: {start_date or '最早'} - {end_date or '最新'}")
    print()
    
    # 1. 加载数据
    scans_df = load_historical_scans(start_date, end_date)
    if scans_df is None:
        return
    
    market_df = load_market_data(scans_df['scan_date'].min(), scans_df['scan_date'].max())
    if market_df is None:
        return
    
    # 2. 计算收益
    returns_df = calculate_returns(scans_df, market_df)
    if returns_df.empty:
        print("❌ 无有效收益数据")
        return
    
    # 3. 按信号类型分析
    print("\n📊 按信号类型分析...")
    by_signal = analyze_by_group(returns_df, 'signal', '信号类型')
    
    # 4. 按超跌等级分析
    print("📊 按超跌等级分析...")
    by_level = analyze_by_group(returns_df, 'level', '超跌等级')
    
    # 5. 按月份分析
    print("📊 按月份分析...")
    by_month = analyze_by_month(returns_df)
    
    # 6. 导出每日汇总 (修复旧回测数据)
    export_daily_summary(returns_df)
    
    # 5. 统计时间范围
    date_range = {
        'start_date': returns_df['scan_date'].min(),
        'end_date': returns_df['scan_date'].max(),
        'trading_days': returns_df['scan_date'].nunique(),
    }
    
    # 6. 整体统计
    overall = {
        'total_signals': len(returns_df),
        't1_avg_return': round(returns_df['t1_return'].dropna().mean(), 2),
        't1_win_rate': round(returns_df['t1_win'].dropna().mean() * 100, 1),
        't5_avg_return': round(returns_df['t5_return'].dropna().mean(), 2),
        't5_win_rate': round(returns_df['t5_win'].dropna().mean() * 100, 1),
    }
    
    # 7. 保存结果
    result = {
        'date_range': date_range,
        'overall': overall,
        'by_signal_type': by_signal,
        'by_oversold_level': by_level,
        'by_month': by_month,
        'generated_at': datetime.now().isoformat(),
    }
    
    write_dual_json(result, Path(STATS_FILE), Path(LEGACY_STATS_FILE))
    
    print(f"\n✅ 结果已保存: {STATS_FILE}")
    
    # 7. 打印摘要
    print("\n" + "=" * 60)
    print("📈 分析摘要")
    print("=" * 60)
    print(f"总信号数: {overall['total_signals']}")
    print(f"T+1 平均收益: {overall['t1_avg_return']}%  胜率: {overall['t1_win_rate']}%")
    print(f"T+5 平均收益: {overall['t5_avg_return']}%  胜率: {overall['t5_win_rate']}%")
    
    print("\n按信号类型:")
    for sig, stat in by_signal.items():
        print(f"  {sig}: 样本{stat['count']}, T+1收益{stat.get('t1_avg_return', 'N/A')}%, 胜率{stat.get('t1_win_rate', 'N/A')}%")
    
    print("\n按超跌等级:")
    for level, stat in by_level.items():
        print(f"  {level}: 样本{stat['count']}, T+1收益{stat.get('t1_avg_return', 'N/A')}%, 胜率{stat.get('t1_win_rate', 'N/A')}%")


if __name__ == '__main__':
    import argparse
    from datetime import datetime, timedelta
    
    parser = argparse.ArgumentParser(description='信号绩效分析')
    parser.add_argument('--start', type=str, help='开始日期 (YYYYMMDD)')
    parser.add_argument('--end', type=str, help='结束日期 (YYYYMMDD)')
    parser.add_argument('--month', type=int, default=None, help='最近 N 个月（默认全部）')
    
    args = parser.parse_args()
    
    start_date = args.start
    end_date = args.end
    
    # 如果指定了 --month，计算日期范围
    if args.month:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=args.month * 30)
        start_date = start_dt.strftime('%Y%m%d')
        end_date = end_dt.strftime('%Y%m%d')
    
    main(start_date, end_date)
