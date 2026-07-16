#!/usr/bin/env python3
"""
MFTS LightGBM模型训练脚本 - 流式处理版
解决OOM问题，采用分批处理策略

使用方法：
    python scripts/train_mfts_lgbm.py
"""

import pandas as pd
import numpy as np
import os
import sys
import pickle
import gc
import argparse
import re
from datetime import datetime
from scipy.stats import spearmanr
from tqdm import tqdm

# 添加路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))

from mfts_screener import calc_indicators
from config.settings import TrainingConfig
from core.data.market_data_gateway import AShareMarketDataGateway
from core.platform.experiment_registry import build_experiment_record, register_experiment
from core.platform.run_manifest import build_file_version

# 配置
IC_RESULT_FILE = os.path.join(BASE_DIR, "output/factor_ic_analysis_T1.csv")
IC_RESULT_FILE_BACKTEST = os.path.join(BASE_DIR, "output/backtest/factor_ic_analysis_T1.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "models")
REPORT_DIR = os.path.join(BASE_DIR, "output")

# 训练参数
TRAIN_START = '2015-01-01'
TRAIN_END = '2022-12-31'
VALID_START = '2023-01-01'
VALID_END = '2023-12-31'
TEST_START = '2024-01-01'
TEST_END = '2025-12-26'

# 分批处理参数（从统一配置读取，按硬件自适应）
BATCH_SIZE = TrainingConfig.BATCH_SIZE
LAST_MARKET_DATA_LINEAGE: dict[str, object] = {}


def select_features_by_ic(ic_file, min_ic=0.01, top_n=None):
    """根据IC分析结果选择特征"""
    print("=" * 70)
    print("特征选择（基于IC分析）")
    print("=" * 70)
    
    ic_df = pd.read_csv(ic_file)
    ic_df = ic_df.sort_values('Mean_IC', key=abs, ascending=False)
    
    if top_n:
        selected = ic_df.head(top_n)
    else:
        selected = ic_df[ic_df['Mean_IC'].abs() >= min_ic]
    
    print(f"\n选中 {len(selected)} 个因子（IC阈值: {min_ic}）:")
    print("-" * 70)
    for i, row in selected.iterrows():
        print(f"  {row['Factor']:<20} IC={row['Mean_IC']:>7.4f}  ICIR={row['ICIR']:>6.3f}")
    
    # 映射因子名称到列名
    factor_mapping = {
        'BIAS-20': 'bias', 'Z-Score': 'z_score', 'BIAS-13': 'bias13',
        'Momentum-5': 'mom_5', 'Momentum-20': 'mom_20', 'Volume Ratio': 'vol_ratio',
        'PV Corr-5': 'pv_corr_5', 'PV Corr-20': 'pv_corr_20', 'RSI-14': 'rsi',
        'MACD Hist': 'macd_hist', 'KDJ-J': 'j_val', 'MFI': 'mfi',
        'BB Position': 'bb_pos', '52W Position': 'pos_52w',
        'ATR %': 'atr_percent', 'ADX': 'adx', 'Volatility Ratio': 'volatility_ratio',
        # [v3.0] 正交因子
        'Smart Money': 'smart_money_ratio',
        'RS-5d': 'rs_5d', 'RS-20d': 'rs_20d',
        'Vol Compression': 'vol_compression',
        'Gap Z-Score': 'gap_zscore',
        'VP Divergence': 'vp_divergence',
    }
    
    feature_cols = [factor_mapping.get(f, f) for f in selected['Factor'].values]
    # 保持顺序去重，避免 IC 文件改名后被静默丢失特征。
    feature_cols = list(dict.fromkeys(feature_cols))
    print(f"\n映射到 {len(feature_cols)} 个特征列")
    return feature_cols, selected


def resolve_ic_result_file():
    """兼容新旧输出目录，定位 IC 结果文件。"""
    candidates = [IC_RESULT_FILE, IC_RESULT_FILE_BACKTEST]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _resolve_open_to_open_horizon(label_mode: str, label_horizon: int) -> int:
    """
    解析 open_to_open 标签持有期（以“入场后持有交易日数”为单位）。
    兼容旧写法 open_to_open_t2（等价于持有1天）。
    """
    if label_mode == "open_to_open_t2":
        return 1
    m = re.match(r"^open_to_open_t(\d+)$", str(label_mode))
    if m:
        t_val = int(m.group(1))
        return max(1, t_val - 1)
    return max(1, int(label_horizon))


def _calc_label_by_mode(batch_df, label_mode: str, label_horizon: int):
    """根据标签模式计算可执行收益标签。"""
    grp = batch_df.groupby('ts_code')
    next_open = grp['open'].shift(-1)
    next_close = grp['close'].shift(-1)
    resolved_h = _resolve_open_to_open_horizon(label_mode, label_horizon)

    if label_mode == 'close_to_close_t1':
        label = grp['pct_chg'].shift(-1)
    elif label_mode in {'open_to_open', 'open_to_open_t2'} or str(label_mode).startswith('open_to_open_t'):
        # 信号在T收盘产生，T+1开盘入场，T+1+H 开盘离场
        exit_open = grp['open'].shift(-(resolved_h + 1))
        label = (exit_open / next_open - 1) * 100
    else:  # 默认 open_to_close_t1
        label = (next_close / next_open - 1) * 100

    return label.replace([np.inf, -np.inf], np.nan)


def _cross_sectional_normalize(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """
    逐日截面 Z-Score 标准化。
    同一天内所有股票的因子值归一化，消除不同市场环境的绝对值差异。
    例如 BIAS=-8 在暴跌日可能是"相对强"，标准化后能体现这一点。
    """
    if df.empty:
        return df
    for col in feature_cols:
        if col not in df.columns:
            continue
        # cs = cross-sectional
        cs_col = f"{col}_cs"
        g = df.groupby('trade_date')[col]
        df[cs_col] = (df[col] - g.transform('mean')) / g.transform('std').replace(0, 1e-8)
    return df


def _make_ranking_labels(df: pd.DataFrame, return_col: str = 'label', n_bins: int = 5) -> pd.DataFrame:
    """
    将连续收益率转为截面排序标签（LambdaRank 所需）。
    每天内按收益率分 n_bins 档：0=最差, n_bins-1=最好。
    """
    def rank_day(group):
        if len(group) < n_bins:
            return pd.Series(np.zeros(len(group), dtype=int), index=group.index)
        return pd.qcut(group, q=n_bins, labels=False, duplicates='drop').fillna(0).astype(int)

    df['rank_label'] = df.groupby('trade_date')[return_col].transform(rank_day)
    return df


def _compute_group_sizes(df: pd.DataFrame, date_col: str = 'trade_date') -> np.ndarray:
    """LambdaRank 的 group 参数：每个 query-group（即每天）的样本数。"""
    return df.groupby(date_col).size().values


def prepare_data_streaming(feature_cols, label_mode='open_to_open', label_horizon=TrainingConfig.LABEL_HORIZON):
    """
    流式数据准备（分批处理，避免OOM）
    """
    print("\n" + "=" * 70)
    print("数据准备（流式处理）")
    print("=" * 70)
    
    # 只加载必需列（parquet中实际存在的列）
    columns_needed = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 
                      'vol', 'amount', 'pct_chg']
    
    print("\n从共享只读 ODS 加载原始数据...")
    gateway = AShareMarketDataGateway()
    sessions = gateway.available_trade_dates(start=TRAIN_START)
    if not sessions:
        raise RuntimeError("共享 ODS 没有可用于训练的日线会话")
    df_raw = gateway.load_bars(TRAIN_START, sessions[-1], include_bj9=False)
    global LAST_MARKET_DATA_LINEAGE
    LAST_MARKET_DATA_LINEAGE = dict(df_raw.attrs.get("market_data_lineage", {}))
    missing_columns = [column for column in columns_needed if column not in df_raw.columns]
    if missing_columns:
        raise RuntimeError(f"共享 ODS 缺少训练所需字段: {missing_columns}")
    df_raw = df_raw[columns_needed].copy()
    df_raw['trade_date'] = pd.to_datetime(df_raw['trade_date'].astype(str))
    df_raw['ts_code'] = df_raw['ts_code'].astype(str)
    
    # 使用2015-2025年数据
    df_raw = df_raw[df_raw['trade_date'] >= TRAIN_START]
    
    all_stocks = sorted(df_raw['ts_code'].unique())
    print(f"数据规模: {len(df_raw):,} 行")
    print(f"股票数量: {len(all_stocks):,} 只")
    print(f"分批大小: {BATCH_SIZE} 只/批")
    
    # 分批处理并收集数据
    train_data = []
    valid_data = []
    test_data = []
    
    total_batches = (len(all_stocks) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for batch_idx in tqdm(range(0, len(all_stocks), BATCH_SIZE), desc="处理批次", total=total_batches):
        batch_stocks = all_stocks[batch_idx:batch_idx + BATCH_SIZE]
        
        # 只取这批股票
        batch_df = df_raw[df_raw['ts_code'].isin(batch_stocks)].copy()
        batch_df = batch_df.sort_values(['ts_code', 'trade_date'])
        
        # 计算指标
        batch_df = calc_indicators(batch_df)
        batch_df = batch_df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
        
        if len(batch_df) == 0:
            continue
        
        # 计算标签和辅助特征
        batch_df['label'] = _calc_label_by_mode(batch_df, label_mode, label_horizon)
        batch_df['vol_ratio'] = batch_df['vol'] / batch_df['vol_ma20']
        
        # 移除缺失值
        valid_features = [f for f in feature_cols if f in batch_df.columns]
        batch_df = batch_df.dropna(subset=valid_features + ['label'])
        
        if len(batch_df) == 0:
            continue
        
        # 分割数据集
        train_mask = (batch_df['trade_date'] >= TRAIN_START) & (batch_df['trade_date'] <= TRAIN_END)
        valid_mask = (batch_df['trade_date'] >= VALID_START) & (batch_df['trade_date'] <= VALID_END)
        test_mask = (batch_df['trade_date'] >= TEST_START) & (batch_df['trade_date'] <= TEST_END)
        
        if train_mask.sum() > 0:
            train_data.append(batch_df.loc[train_mask, valid_features + ['label', 'trade_date', 'ts_code']])
        if valid_mask.sum() > 0:
            valid_data.append(batch_df.loc[valid_mask, valid_features + ['label', 'trade_date', 'ts_code']])
        if test_mask.sum() > 0:
            test_data.append(batch_df.loc[test_mask, valid_features + ['label', 'trade_date', 'ts_code']])
        
        del batch_df
        gc.collect()
    
    # 释放原始数据
    del df_raw
    gc.collect()
    
    # 合并数据
    train_df = pd.concat(train_data, ignore_index=True) if train_data else pd.DataFrame()
    valid_df = pd.concat(valid_data, ignore_index=True) if valid_data else pd.DataFrame()
    test_df = pd.concat(test_data, ignore_index=True) if test_data else pd.DataFrame()
    
    # 获取实际存在的特征列
    actual_features = [f for f in feature_cols if f in train_df.columns]
    
    # ── 截面标准化 ──────────────────────────────────────────
    print("\n截面标准化(Cross-Sectional Z-Score)...")
    for split_name, split_df in [("train", train_df), ("valid", valid_df), ("test", test_df)]:
        if not split_df.empty:
            _cross_sectional_normalize(split_df, actual_features)
    cs_features = [f"{f}_cs" for f in actual_features if f"{f}_cs" in train_df.columns]
    combined_features = actual_features + cs_features
    print(f"  原始特征: {len(actual_features)}, 截面特征: {len(cs_features)}, 总计: {len(combined_features)}")
    # ── 截面标准化结束 ──────────────────────────────────────

    # ── 排序标签 ──────────────────────────────────────────
    print("构建排序标签 (5-bin)...")
    for split_df in [train_df, valid_df, test_df]:
        if not split_df.empty:
            _make_ranking_labels(split_df, 'label', n_bins=5)
    # ── 排序标签结束 ──────────────────────────────────────

    # 按日期排序（LambdaRank group 依赖顺序）
    for split_df in [train_df, valid_df, test_df]:
        if not split_df.empty:
            split_df.sort_values('trade_date', inplace=True)
            split_df.reset_index(drop=True, inplace=True)
    
    print(f"\n训练集: {TRAIN_START} ~ {TRAIN_END}")
    print(f"  样本数: {len(train_df):,}")
    print(f"\n验证集: {VALID_START} ~ {VALID_END}")
    print(f"  样本数: {len(valid_df):,}")
    print(f"\n测试集: {TEST_START} ~ {TEST_END}")
    print(f"  样本数: {len(test_df):,}")
    
    return train_df, valid_df, test_df, combined_features


def train_model(train_df, valid_df, feature_cols):
    """训练LightGBM模型（支持 LambdaRank 排序学习 + 回归回退）"""
    try:
        import lightgbm as lgb
    except Exception as e:
        msg = str(e)
        if "libomp" in msg or "Library not loaded" in msg:
            raise RuntimeError(
                "LightGBM 动态库加载失败（缺少 libomp）。\n"
                "请先安装 OpenMP 运行库后重试：\n"
                "  brew install libomp\n"
                "或在 conda 环境执行：\n"
                "  conda install -c conda-forge libomp lightgbm"
            ) from e
        raise

    use_ranking = os.environ.get('MFTS_TRAIN_OBJECTIVE', 'lambdarank').strip().lower()

    print("\n" + "=" * 70)
    print("LightGBM模型训练")
    print("=" * 70)
    
    X_train = train_df[feature_cols].values
    X_valid = valid_df[feature_cols].values

    if use_ranking == 'lambdarank' and 'rank_label' in train_df.columns:
        print("模式: LambdaRank 排序学习 (NDCG)")
        y_train = train_df['rank_label'].values.astype(float)
        y_valid = valid_df['rank_label'].values.astype(float)
        train_groups = _compute_group_sizes(train_df)
        valid_groups = _compute_group_sizes(valid_df)

        train_data = lgb.Dataset(X_train, label=y_train, group=train_groups, feature_name=feature_cols)
        valid_data = lgb.Dataset(X_valid, label=y_valid, group=valid_groups, reference=train_data)

        params = {
            'objective': 'lambdarank',
            'metric': 'ndcg',
            'ndcg_eval_at': [5, 10, 20],
            'lambdarank_truncation_level': 30,
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'max_depth': 8,
            'min_data_in_leaf': 100,
            'lambda_l1': 0.1,
            'lambda_l2': 0.1,
            'verbose': -1,
        }
    else:
        print("模式: 回归 (RMSE) [fallback]")
        y_train = train_df['label'].values
        y_valid = valid_df['label'].values

        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
        valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

        params = {
            'objective': 'regression',
            'metric': 'rmse',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'max_depth': 8,
            'min_data_in_leaf': 100,
            'lambda_l1': 0.1,
            'lambda_l2': 0.1,
            'verbose': -1,
        }
    
    print(f"参数: objective={params['objective']}, metric={params['metric']}")
    print("\n开始训练...")
    model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[train_data, valid_data],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),
            lgb.log_evaluation(period=50)
        ]
    )
    
    print(f"\n✅ 训练完成! 最佳迭代: {model.best_iteration}")
    return model


def evaluate_model(model, data_df, feature_cols, dataset_name='Test'):
    """评估模型性能"""
    print(f"\n{dataset_name}集评估:")
    
    X = data_df[feature_cols].values
    y_true = data_df['label'].values
    y_pred = model.predict(X)
    
    eval_df = data_df.copy()
    eval_df['pred'] = y_pred
    
    # 计算IC
    ic_by_date = []
    for date in eval_df['trade_date'].unique():
        day_df = eval_df[eval_df['trade_date'] == date]
        if len(day_df) >= 30:
            ic, _ = spearmanr(day_df['pred'], day_df['label'])
            if np.isfinite(ic):
                ic_by_date.append(ic)
    
    mean_ic = np.mean(ic_by_date) if ic_by_date else 0
    ic_std = np.std(ic_by_date) if len(ic_by_date) > 1 else 1e-8
    icir = mean_ic / ic_std if ic_std > 0 else 0.0
    
    # Top 10/30 表现
    top30_by_date = eval_df.groupby('trade_date').apply(lambda x: x.nlargest(30, 'pred'))
    top30_win_rate = (top30_by_date['label'] > 0).mean() * 100
    top30_avg_return = top30_by_date['label'].mean()

    top10_by_date = eval_df.groupby('trade_date').apply(lambda x: x.nlargest(10, 'pred'))
    top10_win_rate = (top10_by_date['label'] > 0).mean() * 100
    top10_avg_return = top10_by_date['label'].mean()
    
    print(f"  均值IC: {mean_ic:.4f}  ICIR: {icir:.3f}")
    print(f"  Top10胜率: {top10_win_rate:.2f}%  Top10平均收益: {top10_avg_return:.3f}%")
    print(f"  Top30胜率: {top30_win_rate:.2f}%  Top30平均收益: {top30_avg_return:.3f}%")
    
    return {
        'mean_ic': mean_ic,
        'icir': icir,
        'ic_std': ic_std,
        'top10_win_rate': top10_win_rate,
        'top10_avg_return': top10_avg_return,
        'top30_win_rate': top30_win_rate,
        'top30_avg_return': top30_avg_return,
    }


def save_model(model, feature_cols, metrics, ic_selected, label_mode, label_horizon):
    """保存模型"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_file = os.path.join(OUTPUT_DIR, f"mfts_lgbm_{timestamp}.pkl")
    
    train_objective = os.environ.get('MFTS_TRAIN_OBJECTIVE', 'lambdarank').strip().lower()

    model_package = {
        'model': model,
        'feature_cols': feature_cols,
        'metrics': metrics,
        'label_mode': label_mode,
        'label_horizon': int(label_horizon),
        'train_objective': train_objective,
        'execution_hint': (
            f"推荐回测/执行持有期: {int(label_horizon)} 交易日"
            if str(label_mode).startswith('open_to_open')
            else "按标签模式匹配执行口径"
        ),
        'timestamp': timestamp,
    }
    
    with open(model_file, 'wb') as f:
        pickle.dump(model_package, f)
    
    print(f"\n✅ 模型已保存: {model_file}")
    print(f"   训练目标: {train_objective}")
    
    # 保存特征重要性
    importance_df = pd.DataFrame({
        'Feature': feature_cols,
        'Importance': model.feature_importance(importance_type='gain')
    }).sort_values('Importance', ascending=False)
    
    importance_file = os.path.join(REPORT_DIR, f"feature_importance_{timestamp}.csv")
    importance_df.to_csv(importance_file, index=False)
    
    print(f"✅ 特征重要性已保存: {importance_file}")
    print("\nTop 10 重要特征:")
    for i, row in importance_df.head(10).iterrows():
        print(f"  {row['Feature']:<20} {row['Importance']:>10.0f}")

    record = build_experiment_record(
        name="mfts_lgbm_train",
        stage="train",
        params={
            "label_mode": label_mode,
            "label_horizon": int(label_horizon),
            "feature_count": len(feature_cols),
            "ic_factor_count": int(len(ic_selected)),
        },
        metrics=metrics,
        artifacts={
            "model_file": model_file,
            "importance_file": importance_file,
        },
        lineage={
            "market_data": LAST_MARKET_DATA_LINEAGE,
            "ic_file": build_file_version(resolve_ic_result_file() or "").__dict__,
        },
    )
    registry_path = register_experiment(BASE_DIR, record)
    print(f"✅ 实验注册已更新: {registry_path}")
    
    return model_file


def main():
    parser = argparse.ArgumentParser(description="MFTS LightGBM 模型训练")
    parser.add_argument(
        "--label-mode",
        type=str,
        default=TrainingConfig.LABEL_MODE,
        choices=["close_to_close_t1", "open_to_close_t1", "open_to_open", "open_to_open_t2"],
        help="标签模式: close_to_close_t1 / open_to_close_t1 / open_to_open / open_to_open_t2(兼容旧)",
    )
    parser.add_argument(
        "--label-horizon",
        type=int,
        default=TrainingConfig.LABEL_HORIZON,
        help=f"仅对 open_to_open 生效：入场后持有交易日数，默认{TrainingConfig.LABEL_HORIZON}",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("MFTS LightGBM模型训练（流式处理版）")
    print("=" * 70)
    print(f"标签模式: {args.label_mode}")
    if args.label_mode.startswith("open_to_open"):
        resolved_h = _resolve_open_to_open_horizon(args.label_mode, args.label_horizon)
        print(f"持有天数: {resolved_h} 交易日")
    
    # 1. 检查IC分析结果（兼容新旧路径）
    ic_file = resolve_ic_result_file()
    if ic_file is None:
        print(f"\n❌ 错误: 未找到IC分析结果文件")
        print(f"已检查路径: {IC_RESULT_FILE} / {IC_RESULT_FILE_BACKTEST}")
        print("请先运行: python scripts/research/analyze_factor_ic.py")
        return None, None
    print(f"使用IC文件: {ic_file}")
    
    # 2. 选择特征
    feature_cols, ic_selected = select_features_by_ic(ic_file, min_ic=0.01, top_n=15)
    
    # 3. 流式数据准备
    train_df, valid_df, test_df, actual_features = prepare_data_streaming(
        feature_cols,
        label_mode=args.label_mode,
        label_horizon=args.label_horizon,
    )
    
    if len(train_df) == 0:
        print("\n❌ 错误: 没有训练数据")
        return None, None
    
    # 4. 训练模型
    try:
        model = train_model(train_df, valid_df, actual_features)
    except Exception as e:
        print(f"\n❌ 训练失败: {e}")
        return None, None
    
    # 5. 评估模型
    print("\n" + "=" * 70)
    print("模型评估")
    print("=" * 70)
    
    train_metrics = evaluate_model(model, train_df, actual_features, 'Train')
    valid_metrics = evaluate_model(model, valid_df, actual_features, 'Valid')
    test_metrics = evaluate_model(model, test_df, actual_features, 'Test')
    
    # 6. 保存模型
    all_metrics = {'train': train_metrics, 'valid': valid_metrics, 'test': test_metrics}
    model_file = save_model(
        model,
        actual_features,
        all_metrics,
        ic_selected,
        label_mode=args.label_mode,
        label_horizon=args.label_horizon,
    )
    
    # 7. 总结
    print("\n" + "=" * 70)
    print("训练完成总结")
    print("=" * 70)
    print(f"模型文件: {model_file}")
    print(f"测试集IC: {test_metrics['mean_ic']:.4f}")
    print(f"Top30胜率: {test_metrics['top30_win_rate']:.2f}%")
    
    print("\n✅ 训练流程全部完成!")
    
    return model, model_file


if __name__ == "__main__":
    main()
