#!/usr/bin/env python3
"""
MFTS v6.2 + ML 融合选股脚本
结合规则信号(v6.2)和机器学习预测

使用方法:
    python scripts/research/daily_hybrid_select.py
    python scripts/research/daily_hybrid_select.py --date 20260109 --top 30
"""

import pandas as pd
import numpy as np
import os
import sys
import pickle
import gc
from datetime import datetime
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))

from mfts_screener import calc_indicators, load_metadata
from mfts_screener_v62 import (
    calculate_alpha_score_v62, get_dynamic_thresholds,
    PARAMS_V62, WEIGHTS_V62
)

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
MODEL_DIR = os.path.join(BASE_DIR, "models")

PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")


def load_latest_model():
    """加载最新训练的ML模型"""
    if not os.path.exists(MODEL_DIR):
        print("⚠️ 未找到模型目录")
        return None, None
    
    # 找到最新的pkl文件
    pkl_files = [f for f in os.listdir(MODEL_DIR) if f.endswith('.pkl')]
    if not pkl_files:
        print("⚠️ 未找到模型文件")
        return None, None
    
    latest_file = sorted(pkl_files)[-1]
    model_path = os.path.join(MODEL_DIR, latest_file)
    
    print(f"加载模型: {latest_file}")
    
    with open(model_path, 'rb') as f:
        model_data = pickle.load(f)
    
    return model_data.get('model'), model_data.get('feature_cols')


def hybrid_select(target_date=None, top_n=30, ml_weight=0.6, rule_weight=0.4):
    """
    MFTS v6.2 + ML 融合选股
    
    Args:
        target_date: 目标日期(YYYYMMDD)
        top_n: 选取数量
        ml_weight: ML预测权重 (默认0.6)
        rule_weight: 规则信号权重 (默认0.4)
    """
    print("=" * 70)
    print("MFTS v6.2 + ML 融合选股系统")
    print(f"ML权重: {ml_weight:.0%} | 规则权重: {rule_weight:.0%}")
    print("=" * 70)
    
    # 1. 加载数据
    print("\n[1/5] 加载数据...")
    df = pd.read_parquet(PARQUET_FILE)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = df['ts_code'].astype(str)
    df = df.sort_values(['ts_code', 'trade_date'])
    
    # 2. 确定日期
    if target_date:
        target_date = pd.to_datetime(target_date)
    else:
        target_date = df['trade_date'].max()
    
    print(f"目标日期: {target_date.date()}")
    
    # 3. 加载ML模型
    print("\n[2/5] 加载ML模型...")
    model, feature_cols = load_latest_model()
    use_ml = model is not None
    
    if use_ml:
        print(f"  使用 {len(feature_cols)} 个特征")
    else:
        print("  ⚠️ 无ML模型，仅使用规则信号")
        ml_weight = 0
        rule_weight = 1.0
    
    # 4. 计算技术指标
    print("\n[3/5] 计算技术指标...")
    df = calc_indicators(df)
    df = df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
    
    # 获取目标日期数据
    today_df = df[df['trade_date'] == target_date].copy()
    # 实盘约束：不参与北交所 9 开头标的
    today_df = today_df[~today_df['ts_code'].astype(str).str.startswith('9')].copy()
    print(f"  今日股票数: {len(today_df)}")
    
    if len(today_df) == 0:
        print("❌ 无今日数据")
        return None
    
    # 5. 计算v6.2规则评分
    print("\n[4/5] 计算信号评分...")
    
    # 计算量比
    today_df['vol_ratio'] = today_df['vol'] / today_df['vol_ma20']
    
    # 动态阈值
    thresholds = get_dynamic_thresholds(1.0)  # 默认市场波动
    
    # v6.2 Alpha评分
    today_df['rule_score'] = today_df.apply(
        lambda row: calculate_alpha_score_v62(row, thresholds),
        axis=1
    )
    
    # 标准化规则评分 (0-100)
    max_rule = today_df['rule_score'].max()
    if max_rule > 0:
        today_df['rule_score_norm'] = today_df['rule_score'] / max_rule * 100
    else:
        today_df['rule_score_norm'] = 0
    
    # 6. 计算ML预测（如果可用）
    if use_ml:
        print("  计算ML预测...")
        
        # 准备特征
        valid_features = [f for f in feature_cols if f in today_df.columns]
        
        if len(valid_features) < len(feature_cols):
            missing = set(feature_cols) - set(valid_features)
            print(f"  ⚠️ 缺少特征: {missing}")
        
        if valid_features:
            X = today_df[valid_features].fillna(0)
            today_df['ml_pred'] = model.predict(X)
            
            # 标准化ML预测 (0-100)
            ml_min = today_df['ml_pred'].min()
            ml_max = today_df['ml_pred'].max()
            if ml_max > ml_min:
                today_df['ml_score_norm'] = (today_df['ml_pred'] - ml_min) / (ml_max - ml_min) * 100
            else:
                today_df['ml_score_norm'] = 50
        else:
            today_df['ml_score_norm'] = 50
    else:
        today_df['ml_score_norm'] = 50
    
    # 7. 融合评分
    today_df['hybrid_score'] = (
        today_df['rule_score_norm'] * rule_weight +
        today_df['ml_score_norm'] * ml_weight
    )
    
    # 8. 过滤和排序
    print("\n[5/5] 筛选Top股票...")
    
    # 基础过滤
    valid_df = today_df[
        (today_df['rule_score'] >= PARAMS_V62['min_alpha_score']) &  # 最低规则评分
        (today_df['vol_ratio'] >= PARAMS_V62['min_volume_ratio'])     # 最低量比
    ].copy()
    
    print(f"  符合条件: {len(valid_df)}")
    
    if len(valid_df) == 0:
        print("❌ 无符合条件的股票")
        return None
    
    # 选取Top N
    result = valid_df.nlargest(top_n, 'hybrid_score').copy()
    
    # 添加股票名称
    meta_dict = load_metadata()
    result['name'] = result['ts_code'].apply(
        lambda x: meta_dict.get(x, {}).get('name', x)
    )
    
    # 信号类型
    def get_signal_type(row):
        if row['rule_score'] >= 15:
            return 'L1_极度超跌'
        elif row['rule_score'] >= 10:
            return 'L2_深度超跌'
        elif row['rule_score'] >= 7:
            return 'L3_中度超跌'
        else:
            return 'L4_轻度超跌'
    
    result['signal'] = result.apply(get_signal_type, axis=1)
    result['rank'] = range(1, len(result) + 1)
    
    # 9. 输出结果
    print("\n" + "=" * 70)
    print(f"TOP {top_n} 融合选股结果")
    print("=" * 70)
    
    output_cols = ['rank', 'ts_code', 'name', 'signal', 'hybrid_score', 
                   'rule_score', 'ml_score_norm', 'close', 'pct_chg', 'vol_ratio']
    
    for col in output_cols:
        if col not in result.columns:
            result[col] = np.nan
    
    display_df = result[output_cols].copy()
    display_df.columns = ['排名', '代码', '名称', '信号', '融合分', 
                          '规则分', 'ML分', '收盘价', '涨跌%', '量比']
    
    print(display_df.to_string(index=False))
    
    # 10. 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    date_str = target_date.strftime('%Y%m%d')
    output_file = os.path.join(OUTPUT_DIR, f"hybrid_{date_str}.csv")
    result.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 结果已保存: {output_file}")
    
    # 同时更新latest
    latest_file = os.path.join(OUTPUT_DIR, "hybrid_latest.csv")
    result.to_csv(latest_file, index=False, encoding='utf-8-sig')
    
    # 统计
    print("\n" + "=" * 70)
    print("统计摘要")
    print("=" * 70)
    print(f"信号分布:")
    print(f"  L1极度超跌: {(result['signal'] == 'L1_极度超跌').sum()}")
    print(f"  L2深度超跌: {(result['signal'] == 'L2_深度超跌').sum()}")
    print(f"  L3中度超跌: {(result['signal'] == 'L3_中度超跌').sum()}")
    print(f"  L4轻度超跌: {(result['signal'] == 'L4_轻度超跌').sum()}")
    print(f"\n平均融合分: {result['hybrid_score'].mean():.2f}")
    print(f"平均规则分: {result['rule_score'].mean():.2f}")
    if use_ml:
        print(f"平均ML分: {result['ml_score_norm'].mean():.2f}")
    
    return result


def main():
    parser = argparse.ArgumentParser(description='MFTS v6.2 + ML 融合选股')
    parser.add_argument('--date', type=str, help='目标日期(YYYYMMDD)')
    parser.add_argument('--top', type=int, default=30, help='选取数量')
    parser.add_argument('--ml-weight', type=float, default=0.6, help='ML权重')
    args = parser.parse_args()
    
    rule_weight = 1.0 - args.ml_weight
    
    try:
        hybrid_select(
            target_date=args.date,
            top_n=args.top,
            ml_weight=args.ml_weight,
            rule_weight=rule_weight
        )
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
