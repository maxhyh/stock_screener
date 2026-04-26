#!/usr/bin/env python3
"""
自动再训练触发 + IC 衰减分析。

功能:
1. 检查模型是否需要再训练（基于时间、IC 衰减、胜率下降）
2. 多持有期 IC 衰减分析
3. 触发再训练（调用 train_mfts_lgbm.py）

使用方法:
    # 仅检查（不触发训练）
    python scripts/auto_retrain.py --check-only

    # 检查 + 触发训练
    python scripts/auto_retrain.py

    # IC 衰减分析
    python scripts/auto_retrain.py --ic-decay-only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from utils.code_utils import normalize_ts_code_series
from utils.output_paths import ensure_output_dirs, resolve_file

MODEL_DIR = os.path.join(BASE_DIR, "models")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")


# ──────────────────────────────────────────────────────────────────
# 再训练触发条件
# ──────────────────────────────────────────────────────────────────

def _get_latest_model_date() -> datetime | None:
    """从模型文件名提取最新训练日期。"""
    if not os.path.exists(MODEL_DIR):
        return None
    files = sorted(f for f in os.listdir(MODEL_DIR) if f.startswith("mfts_lgbm_") and f.endswith(".pkl"))
    if not files:
        return None
    # 文件名格式: mfts_lgbm_YYYYMMDD_HHMMSS.pkl
    latest = files[-1]
    try:
        date_str = latest.replace("mfts_lgbm_", "").replace(".pkl", "").split("_")[0]
        return datetime.strptime(date_str, "%Y%m%d")
    except Exception:
        return None


def _load_recent_verify_stats(n_days: int = 20) -> pd.DataFrame | None:
    """加载最近 N 天的验证统计。"""
    dirs = ensure_output_dirs(OUTPUT_DIR)
    for candidate in [dirs["verify"] / "history_stats.csv", Path(OUTPUT_DIR) / "history_stats.csv"]:
        if candidate.exists():
            df = pd.read_csv(candidate)
            if not df.empty:
                return df.tail(n_days)
    return None


def check_retrain_triggers(
    max_age_days: int = 90,
    min_ic: float = 0.01,
    min_win_rate: float = 40.0,
    max_drawdown_threshold: float = -15.0,
) -> dict:
    """
    检查是否需要再训练。

    触发条件（满足任一）:
    1. 模型年龄 > max_age_days
    2. 近 20 个交易日平均 IC < min_ic
    3. 近 20 个交易日胜率 < min_win_rate
    4. 近 20 天连续亏损天数 >= 10
    """
    triggers = {
        "should_retrain": False,
        "reasons": [],
        "model_age_days": None,
        "recent_win_rate": None,
        "recent_avg_return": None,
        "consecutive_loss_days": 0,
    }

    # 1. 检查模型年龄
    model_date = _get_latest_model_date()
    if model_date is None:
        triggers["should_retrain"] = True
        triggers["reasons"].append("no_model_found")
        return triggers

    age_days = (datetime.now() - model_date).days
    triggers["model_age_days"] = age_days
    if age_days > max_age_days:
        triggers["should_retrain"] = True
        triggers["reasons"].append(f"model_age_{age_days}d_exceeds_{max_age_days}d")

    # 2/3/4. 检查近期表现
    stats = _load_recent_verify_stats(20)
    if stats is not None and not stats.empty:
        if "整体胜率%" in stats.columns:
            recent_wr = float(stats["整体胜率%"].mean())
            triggers["recent_win_rate"] = recent_wr
            if recent_wr < min_win_rate:
                triggers["should_retrain"] = True
                triggers["reasons"].append(f"win_rate_{recent_wr:.1f}%_below_{min_win_rate}%")

        if "平均收益%" in stats.columns:
            recent_ret = float(stats["平均收益%"].mean())
            triggers["recent_avg_return"] = recent_ret
            if recent_ret < -0.3:  # 平均收益持续为负
                triggers["should_retrain"] = True
                triggers["reasons"].append(f"avg_return_{recent_ret:.2f}%_negative")

            # 连续亏损天数
            loss_streak = 0
            for val in reversed(stats["平均收益%"].tolist()):
                if float(val) < 0:
                    loss_streak += 1
                else:
                    break
            triggers["consecutive_loss_days"] = loss_streak
            if loss_streak >= 10:
                triggers["should_retrain"] = True
                triggers["reasons"].append(f"consecutive_loss_{loss_streak}_days")

    return triggers


# ──────────────────────────────────────────────────────────────────
# IC 衰减分析
# ──────────────────────────────────────────────────────────────────

def analyze_ic_decay(
    parquet_file: str | None = None,
    horizons: list[int] | None = None,
    batch_size: int = 200,
) -> pd.DataFrame:
    """
    多持有期 IC 衰减分析。

    对每个因子，计算不同持有期 (T+1, T+3, T+5, ...) 的 IC，
    从而判断 Alpha 的衰减速率。
    """
    from scipy.stats import spearmanr

    sys.path.insert(0, os.path.join(BASE_DIR, "core"))
    from mfts_screener import calc_indicators

    parquet_file = parquet_file or os.path.join(DATA_DIR, "daily_all_5y.parquet")
    horizons = horizons or [1, 3, 5, 8, 10, 15, 20]

    FACTORS = {
        "BIAS-20": "bias", "Z-Score": "z_score", "Momentum-5": "mom_5",
        "Momentum-20": "mom_20", "RSI-14": "rsi", "MACD Hist": "macd_hist",
        "BB Position": "bb_pos", "ADX": "adx",
    }

    print("加载数据...")
    cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"]
    df = pd.read_parquet(parquet_file, columns=cols)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
    df["ts_code"] = normalize_ts_code_series(df["ts_code"])
    df = df[df["trade_date"] >= "2020-01-01"].copy()  # 近几年即可

    all_stocks = sorted(df["ts_code"].unique())
    print(f"股票数: {len(all_stocks)}, 分批处理中...")

    ic_results = {f"{fname}_H{h}": [] for fname in FACTORS for h in horizons}

    for batch_start in range(0, len(all_stocks), batch_size):
        batch_codes = all_stocks[batch_start:batch_start + batch_size]
        batch_df = df[df["ts_code"].isin(batch_codes)].copy()
        batch_df = batch_df.sort_values(["ts_code", "trade_date"])
        batch_df = calc_indicators(batch_df)
        batch_df = batch_df.dropna(subset=["ma120", "vol_ma20", "z_score"])

        grouped = batch_df.groupby("ts_code")
        for h in horizons:
            # open_to_open 收益：T+1开盘→T+1+H开盘
            next_open = grouped["open"].shift(-1)
            exit_open = grouped["open"].shift(-(h + 1))
            batch_df[f"ret_h{h}"] = (exit_open / next_open - 1) * 100

        for date in batch_df["trade_date"].unique():
            day = batch_df[batch_df["trade_date"] == date]
            if len(day) < 30:
                continue
            for fname, fcol in FACTORS.items():
                if fcol not in day.columns:
                    continue
                for h in horizons:
                    ret_col = f"ret_h{h}"
                    if ret_col not in day.columns:
                        continue
                    valid = day[[fcol, ret_col]].dropna()
                    if len(valid) < 20:
                        continue
                    try:
                        ic, _ = spearmanr(valid[fcol], valid[ret_col])
                        ic_results[f"{fname}_H{h}"].append(ic)
                    except Exception:
                        pass

        print(f"  已处理 {min(batch_start + batch_size, len(all_stocks))}/{len(all_stocks)}")

    # 汇总
    rows = []
    for fname in FACTORS:
        row = {"Factor": fname}
        for h in horizons:
            key = f"{fname}_H{h}"
            ics = ic_results.get(key, [])
            row[f"IC_H{h}"] = float(np.mean(ics)) if ics else 0.0
            row[f"ICIR_H{h}"] = float(np.mean(ics) / np.std(ics)) if ics and np.std(ics) > 0 else 0.0
        rows.append(row)

    result_df = pd.DataFrame(rows)

    # 输出
    print(f"\n{'=' * 72}")
    print("IC 衰减分析（按持有期）")
    print(f"{'=' * 72}")
    header = f"{'因子':<15}" + "".join(f"  H{h:>2d}" for h in horizons)
    print(header)
    print("-" * len(header))
    for _, row in result_df.iterrows():
        line = f"{row['Factor']:<15}"
        for h in horizons:
            ic = row.get(f"IC_H{h}", 0.0)
            line += f" {ic:>5.3f}"
        print(line)

    # 保存
    out_file = os.path.join(OUTPUT_DIR, "ic_decay_analysis.csv")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    result_df.to_csv(out_file, index=False, encoding="utf-8-sig")
    print(f"\n✅ IC 衰减分析已保存: {out_file}")

    return result_df


# ──────────────────────────────────────────────────────────────────
# 触发训练
# ──────────────────────────────────────────────────────────────────

def trigger_retrain() -> int:
    """调用训练脚本。"""
    script = os.path.join(BASE_DIR, "scripts", "train_mfts_lgbm.py")
    if not os.path.exists(script):
        print(f"❌ 训练脚本不存在: {script}")
        return 1

    print("\n🔄 触发模型再训练...")
    result = subprocess.run(
        [sys.executable, script],
        cwd=BASE_DIR,
        capture_output=False,
    )
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="自动再训练触发 + IC 衰减分析")
    parser.add_argument("--check-only", action="store_true", help="仅检查，不触发训练")
    parser.add_argument("--ic-decay-only", action="store_true", help="仅运行 IC 衰减分析")
    parser.add_argument("--max-age-days", type=int, default=90, help="模型最大年龄（天）")
    parser.add_argument("--min-win-rate", type=float, default=40.0, help="最低胜率阈值(%%)")
    args = parser.parse_args()

    if args.ic_decay_only:
        analyze_ic_decay()
        return

    print("=" * 72)
    print("自动再训练检查")
    print("=" * 72)

    triggers = check_retrain_triggers(
        max_age_days=args.max_age_days,
        min_win_rate=args.min_win_rate,
    )

    print(f"\n模型年龄: {triggers['model_age_days']} 天")
    print(f"近期胜率: {triggers['recent_win_rate']:.1f}%" if triggers["recent_win_rate"] is not None else "近期胜率: N/A")
    print(f"近期平均收益: {triggers['recent_avg_return']:.2f}%" if triggers["recent_avg_return"] is not None else "近期平均收益: N/A")
    print(f"连续亏损天数: {triggers['consecutive_loss_days']}")

    if triggers["should_retrain"]:
        print(f"\n⚠️ 需要再训练！原因: {', '.join(triggers['reasons'])}")
        if not args.check_only:
            ret = trigger_retrain()
            if ret == 0:
                print("✅ 再训练完成")
            else:
                print(f"❌ 再训练失败 (退出码: {ret})")
        else:
            print("ℹ️ --check-only 模式，跳过训练")
    else:
        print("\n✅ 模型状态正常，不需要再训练")


if __name__ == "__main__":
    main()
