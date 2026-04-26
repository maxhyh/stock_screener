#!/usr/bin/env python3
"""
每日验证脚本
验证昨日推荐的实际表现

使用方法:
    python scripts/daily_verify.py
    python scripts/daily_verify.py --date 20260108
"""

import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime, timedelta
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import resolve_default_label_horizon
from utils.code_utils import normalize_ts_code_series
from utils.output_paths import ensure_output_dirs, resolve_file, write_dual_csv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DEFAULT_VERIFY_LABEL_MODE = os.environ.get('MFTS_VERIFY_LABEL_MODE', 'open_to_open')
DEFAULT_VERIFY_LABEL_HORIZON = int(os.environ.get('MFTS_VERIFY_LABEL_HORIZON', str(resolve_default_label_horizon(fallback=8))))


def load_market_day_data():
    """加载市场日线数据（仅验证所需列）。"""
    parquet_file = os.path.join(DATA_DIR, "daily_all_5y.parquet")
    df = pd.read_parquet(parquet_file, columns=['ts_code', 'trade_date', 'open', 'close'])
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = normalize_ts_code_series(df['ts_code'])
    df = df[df['ts_code'] != ''].copy()
    df['open'] = pd.to_numeric(df['open'], errors='coerce')
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    # 对缺失/无效开盘价做一次全局回填，避免 open_to_open 验证频繁回退
    df['open_filled'] = df['open']
    bad_open = df['open_filled'].isna() | (df['open_filled'] <= 0)
    prev_close = df.groupby('ts_code')['close'].shift(1)
    fill_prev = bad_open & prev_close.notna() & (prev_close > 0)
    fill_close = bad_open & (~fill_prev) & df['close'].notna() & (df['close'] > 0)
    df.loc[fill_prev, 'open_filled'] = prev_close[fill_prev]
    df.loc[fill_close, 'open_filled'] = df.loc[fill_close, 'close']
    return df


def get_next_trade_date(market_df, pred_date):
    """返回 pred_date 之后的下一个交易日。"""
    trade_days = sorted(market_df['trade_date'].dropna().unique())
    future_days = [d for d in trade_days if d > pred_date]
    return future_days[0] if future_days else None


def get_trade_date_after_n_days(market_df, pred_date, n_days):
    """返回 pred_date 之后第 n_days 个交易日（n_days>=1）。"""
    trade_days = sorted(market_df['trade_date'].dropna().unique())
    future_days = [d for d in trade_days if d > pred_date]
    if n_days <= 0 or len(future_days) < n_days:
        return None
    return future_days[n_days - 1]


def get_close_prices_on_date(market_df, stock_codes, trade_date):
    """获取指定交易日收盘价映射。"""
    day_df = market_df[market_df['trade_date'] == trade_date].copy()
    day_df = day_df[day_df['ts_code'].isin(stock_codes)]
    return dict(zip(day_df['ts_code'], day_df['close']))


def get_open_prices_on_date(market_df, stock_codes, trade_date):
    """获取指定交易日开盘价映射。"""
    day_df = market_df[market_df['trade_date'] == trade_date].copy()
    day_df = day_df[day_df['ts_code'].isin(stock_codes)]
    return dict(zip(day_df['ts_code'], day_df['open_filled']))


def verify_predictions(pred_date=None, label_mode='open_to_close_t1', label_horizon=1):
    """
    验证指定日期的推荐表现
    
    Args:
        pred_date: 推荐日期(YYYYMMDD)，None表示昨日
    """
    print("=" * 70)
    print("MFTS ML验证系统")
    print("=" * 70)
    
    # 1. 确定验证日期
    if pred_date:
        pred_date = pd.to_datetime(pred_date)
    else:
        # 默认验证昨日
        pred_date = datetime.now() - timedelta(days=1)
    
    pred_date_str = pred_date.strftime('%Y%m%d')
    print(f"\n推荐日期: {pred_date.strftime('%Y-%m-%d')}")
    print(f"验证口径: {label_mode}")
    
    # 2. 加载推荐记录
    dirs = ensure_output_dirs(OUTPUT_DIR)
    daily_dir = dirs['daily']
    verify_dir = dirs['verify']
    base_dir = Path(OUTPUT_DIR)

    picks_new = daily_dir / f"daily_{pred_date_str}.csv"
    picks_legacy = base_dir / f"daily_{pred_date_str}.csv"
    picks_path = resolve_file(picks_new, picks_legacy)

    if picks_path is None:
        print(f"\n❌ 错误: 未找到推荐记录 {picks_new} 或 {picks_legacy}")
        return None
    
    # 强制读取所有代码为字符串
    picks = pd.read_csv(picks_path, dtype={'代码': str, 'ts_code': str})
    
    # 标准化代码
    if '代码' in picks.columns:
        picks['代码'] = normalize_ts_code_series(picks['代码'])
    elif 'ts_code' in picks.columns:
        picks['代码'] = normalize_ts_code_series(picks['ts_code'])
    picks = picks[picks['代码'] != ''].copy()
        
    print(f"推荐股票数: {len(picks)}")
    
    # 3. 获取 T+1 交易日收盘价
    print("\n加载市场数据并定位 T+1 交易日...")
    market_df = load_market_day_data()
    entry_date = get_next_trade_date(market_df, pred_date)
    if entry_date is None:
        print("\n❌ 无法验证：推荐日之后暂无交易日数据")
        return None

    if label_mode == 'open_to_open_t2':
        # 兼容旧命名：T+1开盘买入，T+2开盘卖出（持有1日）
        label_mode = 'open_to_open'
        label_horizon = 1

    if label_mode == 'open_to_open':
        verify_date = get_trade_date_after_n_days(market_df, pred_date, label_horizon + 1)
        if verify_date is None:
            print(f"\n❌ 无法验证：推荐日后不足 {label_horizon + 1} 个交易日")
            return None
        print(f"入场交易日(T+1): {entry_date.date()}")
        print(f"验证交易日(T+{label_horizon + 1}): {verify_date.date()}")
    else:
        verify_date = entry_date
        print(f"验证交易日(T+1): {verify_date.date()}")

    verify_entry_opens = get_open_prices_on_date(market_df, picks['代码'].tolist(), entry_date)
    verify_opens = get_open_prices_on_date(market_df, picks['代码'].tolist(), verify_date)
    verify_prices = get_close_prices_on_date(market_df, picks['代码'].tolist(), verify_date)
    
    # 4. 计算实际收益
    picks['入场日开盘'] = picks['代码'].map(verify_entry_opens)
    picks['验证日开盘'] = picks['代码'].map(verify_opens)
    picks['验证日收盘'] = picks['代码'].map(verify_prices)
    used_mode = label_mode
    if label_mode == 'close_to_close_t1':
        picks['实际收益%'] = ((picks['验证日收盘'] / picks['收盘价']) - 1) * 100
        valid_mask = picks['验证日收盘'].notna() & picks['收盘价'].notna()
    elif label_mode == 'open_to_open':
        picks['实际收益%'] = ((picks['验证日开盘'] / picks['入场日开盘']) - 1) * 100
        valid_mask = picks['验证日开盘'].notna() & picks['入场日开盘'].notna()
        if valid_mask.sum() == 0:
            print("\n⚠️ open_to_open 缺少有效开盘价，自动回退到 close_to_close_t1 口径")
            picks['实际收益%'] = ((picks['验证日收盘'] / picks['收盘价']) - 1) * 100
            valid_mask = picks['验证日收盘'].notna() & picks['收盘价'].notna()
            used_mode = 'close_to_close_t1(fallback)'
        else:
            used_mode = f'open_to_open_h{label_horizon}'
    else:
        picks['实际收益%'] = ((picks['验证日收盘'] / picks['验证日开盘']) - 1) * 100
        valid_mask = picks['验证日收盘'].notna() & picks['验证日开盘'].notna()
        # 兼容数据源仅有收盘价、缺少开盘价的场景（如批量补数日）
        if valid_mask.sum() == 0:
            print("\n⚠️ open_to_close_t1 缺少有效开盘价，自动回退到 close_to_close_t1 口径")
            picks['实际收益%'] = ((picks['验证日收盘'] / picks['收盘价']) - 1) * 100
            valid_mask = picks['验证日收盘'].notna() & picks['收盘价'].notna()
            used_mode = 'close_to_close_t1(fallback)'
    picks['盈利'] = picks['实际收益%'] > 0
    
    # 处理停牌等情况
    valid_count = valid_mask.sum()
    print(f"有效验证: {valid_count}/{len(picks)}")
    
    # 5. 统计分析
    valid_picks = picks[valid_mask].copy()
    
    if len(valid_picks) == 0:
        print("\n❌ 无有效数据可验证")
        return None
    
    stats = {
        '验证日期': pred_date.strftime('%Y-%m-%d'),
        '验证交易日': verify_date.strftime('%Y-%m-%d'),
        '验证口径': used_mode,
        '推荐总数': len(picks),
        '有效验证': len(valid_picks),
        '盈利数量': valid_picks['盈利'].sum(),
        '整体胜率%': valid_picks['盈利'].mean() * 100,
        '平均收益%': valid_picks['实际收益%'].mean(),
        '最大收益%': valid_picks['实际收益%'].max(),
        '最大亏损%': valid_picks['实际收益%'].min(),
        'Top10胜率%': valid_picks.head(10)['盈利'].mean() * 100,
        'Top10平均收益%': valid_picks.head(10)['实际收益%'].mean(),
    }
    
    # 6. 打印结果
    print("\n" + "=" * 70)
    print("验证结果")
    print("=" * 70)
    for key, value in stats.items():
        if isinstance(value, (int, float, np.integer, np.floating)):
            if '%' in key:
                print(f"{key:<15}: {float(value):>8.2f}%")
            else:
                print(f"{key:<15}: {float(value):>8.0f}")
        else:
            print(f"{key:<15}: {value}")
    
    # 7. Top10详情
    print("\n" + "=" * 70)
    print("Top 10 实际表现")
    print("=" * 70)
    top10 = valid_picks.head(10)[['排名', '代码', '名称', 'ML评分', '收盘价', '验证日收盘', '实际收益%', '盈利']]
    print(top10.to_string(index=False))
    
    # 8. 保存验证结果
    # 保存详细数据（verify 子目录 + 兼容旧路径双写）
    verify_new = verify_dir / f"verification_{pred_date_str}.csv"
    verify_legacy = base_dir / f"verification_{pred_date_str}.csv"
    write_dual_csv(valid_picks, verify_new, verify_legacy, index=False, encoding='utf-8-sig')
    print(f"\n详细结果已保存: {verify_new} (兼容写入: {verify_legacy})")
    
    # 9. 追加到历史统计
    history_new = verify_dir / "history_stats.csv"
    history_legacy = base_dir / "history_stats.csv"
    stats_df = pd.DataFrame([stats])
    
    history_file = resolve_file(history_new, history_legacy)
    if history_file is not None:
        history = pd.read_csv(history_file)
        history.columns = [str(c).lstrip('\ufeff').strip() for c in history.columns]
        history = pd.concat([history, stats_df], ignore_index=True)
        # 按“验证日期”去重，保留最新记录，避免重复统计污染均值
        if '验证日期' in history.columns:
            history = history.drop_duplicates(subset=['验证日期'], keep='last')
    else:
        history = stats_df
    
    write_dual_csv(history, history_new, history_legacy, index=False, encoding='utf-8-sig')
    print(f"历史统计已更新: {history_new} (兼容写入: {history_legacy})")
    
    # 10. 显示历史趋势（最近10次）
    if len(history) >= 2:
        print("\n" + "=" * 70)
        print("最近历史表现")
        print("=" * 70)
        recent = history.tail(10)[['验证日期', '整体胜率%', '平均收益%', 'Top10胜率%']]
        print(recent.to_string(index=False))
        
        print(f"\n近{len(history)}天平均:")
        print(f"  整体胜率: {history['整体胜率%'].mean():.2f}%")
        print(f"  平均收益: {history['平均收益%'].mean():.2f}%")
        print(f"  Top10胜率: {history['Top10胜率%'].mean():.2f}%")
    
    print("\n✅ 验证完成!")
    
    return stats


def main():
    parser = argparse.ArgumentParser(description='MFTS ML每日验证')
    parser.add_argument('--date', type=str, help='推荐日期(YYYYMMDD)，默认昨日')
    parser.add_argument(
        '--label-mode',
        type=str,
        default=DEFAULT_VERIFY_LABEL_MODE,
        choices=['close_to_close_t1', 'open_to_close_t1', 'open_to_open', 'open_to_open_t2'],
        help=f'验证口径: close_to_close_t1 / open_to_close_t1 / open_to_open / open_to_open_t2(兼容旧)，默认 {DEFAULT_VERIFY_LABEL_MODE}',
    )
    parser.add_argument(
        '--label-horizon',
        type=int,
        default=DEFAULT_VERIFY_LABEL_HORIZON,
        help=f'仅对 open_to_open 生效：入场后持有交易日数，默认{DEFAULT_VERIFY_LABEL_HORIZON}',
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        default=os.environ.get('MFTS_VERIFY_STRICT', 'false').lower() in {'1', 'true', 'yes', 'on'},
        help='严格模式：无可验证样本时返回非零退出码',
    )
    args = parser.parse_args()
    
    try:
        stats = verify_predictions(
            pred_date=args.date,
            label_mode=args.label_mode,
            label_horizon=max(1, int(args.label_horizon)),
        )
        if stats is None:
            msg = "\n⚠️ 无可验证样本（缺少推荐文件或未来交易日不足）"
            if args.strict:
                print(msg + "，严格模式返回失败")
                sys.exit(2)
            print(msg + "，按跳过处理")
            sys.exit(0)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
