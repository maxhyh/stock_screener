#!/usr/bin/env python3
"""
量化组合参数优化（网格搜索）

示例：
    python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20
"""

from __future__ import annotations

import argparse
import os
import sys
import json
from datetime import datetime
from pathlib import Path
from itertools import product

import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from quant_portfolio_backtest import BacktestConfig, backtest_portfolio
from utils.output_paths import ensure_output_dirs, write_dual_csv

OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def _parse_int_grid(text: str) -> list[int]:
    vals = []
    for x in text.split(","):
        x = x.strip()
        if not x:
            continue
        vals.append(int(x))
    return sorted(set(vals))


def _constraint_fail_reasons(
    metrics: dict[str, float],
    robust: dict[str, float] | None,
    *,
    robust_on: bool,
    min_windows: int,
    min_annual_return_pct: float,
    min_excess_annual_pct: float,
    min_sharpe: float,
    min_sortino: float,
    min_win_rate_pct: float,
    min_profit_factor: float,
    min_tail_ratio: float,
    min_capital_efficiency: float,
    max_drawdown_limit_pct: float,
    max_ulcer_index_pct: float | None,
    turnover_cap_pct: float | None,
    min_oos_excess_total_median: float,
    min_oos_mdd_worst: float,
    min_oos_pass_rate: float,
    min_oos_valid_window_ratio: float,
) -> list[str]:
    """返回组合未通过硬门槛的原因标签列表。"""
    robust = robust or {}
    reasons: list[str] = []
    annual = float(metrics.get("annual_return_pct", 0.0))
    excess_annual = float(metrics.get("excess_annual_return_pct", 0.0))
    sharpe = float(metrics.get("sharpe", 0.0))
    sortino = float(metrics.get("sortino", 0.0))
    win_rate = float(metrics.get("win_rate_pct", 0.0))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    tail_ratio = float(metrics.get("tail_ratio", 0.0))
    capital_efficiency = float(metrics.get("capital_efficiency", 0.0))
    mdd = float(metrics.get("max_drawdown_pct", 0.0))
    ulcer_index = float(metrics.get("ulcer_index_pct", 0.0))
    turnover = float(metrics.get("annual_turnover_pct", 0.0))

    if annual < float(min_annual_return_pct):
        reasons.append("annual_return")
    if excess_annual < float(min_excess_annual_pct):
        reasons.append("excess_annual")
    if sharpe < float(min_sharpe):
        reasons.append("sharpe")
    if sortino < float(min_sortino):
        reasons.append("sortino")
    if win_rate < float(min_win_rate_pct):
        reasons.append("win_rate")
    if profit_factor < float(min_profit_factor):
        reasons.append("profit_factor")
    if tail_ratio < float(min_tail_ratio):
        reasons.append("tail_ratio")
    if capital_efficiency < float(min_capital_efficiency):
        reasons.append("capital_efficiency")
    if mdd < float(max_drawdown_limit_pct):
        reasons.append("max_drawdown")
    if max_ulcer_index_pct is not None and max_ulcer_index_pct > 0:
        if ulcer_index > float(max_ulcer_index_pct):
            reasons.append("ulcer_index")
    if turnover_cap_pct is not None and turnover_cap_pct > 0:
        if turnover > float(turnover_cap_pct):
            reasons.append("turnover")

    if robust_on:
        if int(robust.get("oos_valid_windows", 0)) < int(min_windows):
            reasons.append("oos_valid_windows")
        if float(robust.get("oos_excess_total_median", 0.0)) < float(min_oos_excess_total_median):
            reasons.append("oos_excess_total_median")
        if float(robust.get("oos_mdd_worst", 0.0)) < float(min_oos_mdd_worst):
            reasons.append("oos_mdd_worst")
        if float(robust.get("oos_pass_rate", 0.0)) < float(min_oos_pass_rate):
            reasons.append("oos_pass_rate")
        if float(robust.get("oos_valid_window_ratio", 0.0)) < float(min_oos_valid_window_ratio):
            reasons.append("oos_valid_window_ratio")
    return reasons


def _passes_hard_filters(
    metrics: dict[str, float],
    *,
    min_annual_return_pct: float,
    min_excess_annual_pct: float,
    min_sharpe: float,
    min_sortino: float,
    min_win_rate_pct: float,
    min_profit_factor: float,
    min_tail_ratio: float,
    min_capital_efficiency: float,
    max_drawdown_limit_pct: float,
    max_ulcer_index_pct: float | None,
    turnover_cap_pct: float | None = None,
) -> bool:
    """普通模式硬门槛。"""
    reasons = _constraint_fail_reasons(
        metrics,
        {},
        robust_on=False,
        min_windows=0,
        min_annual_return_pct=min_annual_return_pct,
        min_excess_annual_pct=min_excess_annual_pct,
        min_sharpe=min_sharpe,
        min_sortino=min_sortino,
        min_win_rate_pct=min_win_rate_pct,
        min_profit_factor=min_profit_factor,
        min_tail_ratio=min_tail_ratio,
        min_capital_efficiency=min_capital_efficiency,
        max_drawdown_limit_pct=max_drawdown_limit_pct,
        max_ulcer_index_pct=max_ulcer_index_pct,
        turnover_cap_pct=turnover_cap_pct,
        min_oos_excess_total_median=0.0,
        min_oos_mdd_worst=-999.0,
        min_oos_pass_rate=0.0,
        min_oos_valid_window_ratio=0.0,
    )
    return len(reasons) == 0


def _score(metrics: dict[str, float]) -> float:
    # 越大越好：收益/夏普/胜率加分，回撤/换手扣分
    # 注意：换手是百分比口径（如3000%），先做尺度归一，避免惩罚过重挤压收益维度
    turnover_norm = float(metrics.get("annual_turnover_pct", 0.0)) / 100.0
    sortino = min(max(float(metrics.get("sortino", 0.0)), -3.0), 4.0)
    calmar = min(max(float(metrics.get("calmar", 0.0)), -2.0), 4.0)
    profit_factor = min(max(float(metrics.get("profit_factor", 0.0)), 0.0), 5.0)
    tail_ratio = min(max(float(metrics.get("tail_ratio", 0.0)), 0.0), 5.0)
    capital_efficiency = min(max(float(metrics.get("capital_efficiency", 0.0)), -1.0), 2.0)
    ulcer_index = float(metrics.get("ulcer_index_pct", 0.0))
    return (
        0.24 * float(metrics.get("annual_return_pct", 0.0))
        + 0.20 * float(metrics.get("excess_annual_return_pct", 0.0))
        + 0.16 * float(metrics.get("sharpe", 0.0)) * 10.0
        + 0.10 * sortino * 8.0
        + 0.08 * calmar * 8.0
        + 0.08 * float(metrics.get("win_rate_pct", 0.0))
        + 0.05 * float(metrics.get("beat_rate_pct", 0.0))
        + 0.05 * float(metrics.get("total_return_pct", 0.0))
        + 0.05 * profit_factor * 10.0
        + 0.03 * tail_ratio * 10.0
        + 0.04 * capital_efficiency * 10.0
        - 0.26 * abs(float(metrics.get("max_drawdown_pct", 0.0)))
        - 0.08 * ulcer_index
        - 0.03 * turnover_norm
    )


def _add_months(ts: pd.Timestamp, months: int) -> pd.Timestamp:
    return ts + pd.DateOffset(months=months)


def _build_oos_windows(start: pd.Timestamp, end: pd.Timestamp, warmup_months: int, test_months: int, step_months: int) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    cur = _add_months(start, warmup_months)
    while cur <= end:
        test_start = cur
        test_end = _add_months(test_start, test_months) - pd.Timedelta(days=1)
        if test_end > end:
            break
        windows.append((test_start.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d")))
        cur = _add_months(cur, step_months)
    return windows


def _robust_oos_metrics(base_cfg_kwargs: dict, windows: list[tuple[str, str]], min_trades_per_window: int = 1) -> dict[str, float]:
    if not windows:
        return {
            "oos_windows": 0,
            "oos_excess_annual_mean": 0.0,
            "oos_excess_annual_median": 0.0,
            "oos_excess_annual_p25": 0.0,
            "oos_excess_total_mean": 0.0,
            "oos_excess_total_median": 0.0,
            "oos_excess_total_p25": 0.0,
            "oos_total_mean": 0.0,
            "oos_total_median": 0.0,
            "oos_total_p25": 0.0,
            "oos_annual_mean": 0.0,
            "oos_mdd_worst": 0.0,
            "oos_mdd_std": 0.0,
            "oos_sharpe_mean": 0.0,
            "oos_beat_rate_mean": 0.0,
            "oos_pass_rate": 0.0,
            "oos_valid_window_ratio": 0.0,
        }

    excess_totals = []
    totals = []
    annuals = []
    excess_annuals = []
    mdds = []
    sharpes = []
    beats = []
    used = 0

    for ws, we in windows:
        cfg = BacktestConfig(start=ws, end=we, **base_cfg_kwargs)
        try:
            _, m = backtest_portfolio(cfg)
        except Exception:
            continue
        if int(m.get("trade_count", 0)) < int(min_trades_per_window):
            continue
        used += 1
        totals.append(float(m.get("total_return_pct", 0.0)))
        excess_totals.append(float(m.get("excess_total_return_pct", 0.0)))
        annuals.append(float(m.get("annual_return_pct", 0.0)))
        excess_annuals.append(float(m.get("excess_annual_return_pct", 0.0)))
        mdds.append(float(m.get("max_drawdown_pct", 0.0)))
        sharpes.append(float(m.get("sharpe", 0.0)))
        beats.append(float(m.get("beat_rate_pct", 0.0)))

    if not excess_annuals:
        return {
            "oos_windows": 0,
            "oos_excess_annual_mean": 0.0,
            "oos_excess_annual_median": 0.0,
            "oos_excess_annual_p25": 0.0,
            "oos_excess_total_mean": 0.0,
            "oos_excess_total_median": 0.0,
            "oos_excess_total_p25": 0.0,
            "oos_total_mean": 0.0,
            "oos_total_median": 0.0,
            "oos_total_p25": 0.0,
            "oos_annual_mean": 0.0,
            "oos_mdd_worst": 0.0,
            "oos_mdd_std": 0.0,
            "oos_sharpe_mean": 0.0,
            "oos_beat_rate_mean": 0.0,
            "oos_pass_rate": 0.0,
            "oos_valid_window_ratio": 0.0,
        }

    excess_arr = np.asarray(excess_annuals, dtype=float)
    excess_total_arr = np.asarray(excess_totals, dtype=float)
    total_arr = np.asarray(totals, dtype=float)
    mdd_arr = np.asarray(mdds, dtype=float)
    sharpe_arr = np.asarray(sharpes, dtype=float)
    beat_arr = np.asarray(beats, dtype=float)
    pass_mask = (excess_total_arr > 0.0) & (mdd_arr > -15.0) & (sharpe_arr > 0.0)

    return {
        "oos_windows": int(len(windows)),
        "oos_valid_windows": int(used),
        "oos_valid_window_ratio": float(used / max(len(windows), 1)),
        "oos_excess_annual_mean": float(np.mean(excess_arr)),
        "oos_excess_annual_median": float(np.median(excess_arr)),
        "oos_excess_annual_p25": float(np.percentile(excess_arr, 25)),
        "oos_excess_total_mean": float(np.mean(excess_total_arr)),
        "oos_excess_total_median": float(np.median(excess_total_arr)),
        "oos_excess_total_p25": float(np.percentile(excess_total_arr, 25)),
        "oos_total_mean": float(np.mean(total_arr)),
        "oos_total_median": float(np.median(total_arr)),
        "oos_total_p25": float(np.percentile(total_arr, 25)),
        "oos_annual_mean": float(np.mean(np.asarray(annuals, dtype=float))),
        "oos_mdd_worst": float(np.min(mdd_arr)),
        "oos_mdd_std": float(np.std(mdd_arr)),
        "oos_sharpe_mean": float(np.mean(sharpe_arr)),
        "oos_beat_rate_mean": float(np.mean(beat_arr)),
        "oos_pass_rate": float(np.mean(pass_mask)),
    }


def _passes_robust_hard_filters(
    metrics: dict[str, float],
    robust: dict[str, float],
    min_windows: int,
    *,
    min_annual_return_pct: float,
    min_excess_annual_pct: float,
    min_sharpe: float,
    min_sortino: float,
    min_win_rate_pct: float,
    min_profit_factor: float,
    min_tail_ratio: float,
    min_capital_efficiency: float,
    max_drawdown_limit_pct: float,
    max_ulcer_index_pct: float | None,
    min_oos_excess_total_median: float,
    min_oos_mdd_worst: float,
    min_oos_pass_rate: float,
    min_oos_valid_window_ratio: float,
    turnover_cap_pct: float | None = None,
) -> bool:
    reasons = _constraint_fail_reasons(
        metrics,
        robust,
        robust_on=True,
        min_windows=min_windows,
        min_annual_return_pct=min_annual_return_pct,
        min_excess_annual_pct=min_excess_annual_pct,
        min_sharpe=min_sharpe,
        min_sortino=min_sortino,
        min_win_rate_pct=min_win_rate_pct,
        min_profit_factor=min_profit_factor,
        min_tail_ratio=min_tail_ratio,
        min_capital_efficiency=min_capital_efficiency,
        max_drawdown_limit_pct=max_drawdown_limit_pct,
        max_ulcer_index_pct=max_ulcer_index_pct,
        turnover_cap_pct=turnover_cap_pct,
        min_oos_excess_total_median=min_oos_excess_total_median,
        min_oos_mdd_worst=min_oos_mdd_worst,
        min_oos_pass_rate=min_oos_pass_rate,
        min_oos_valid_window_ratio=min_oos_valid_window_ratio,
    )
    return len(reasons) == 0


def _minmax_norm(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().sum() == 0:
        return pd.Series([0.0] * len(s), index=s.index, dtype=float)
    lo = float(x.min())
    hi = float(x.max())
    if not np.isfinite(lo) or not np.isfinite(hi) or abs(hi - lo) < 1e-12:
        return pd.Series([0.5] * len(s), index=s.index, dtype=float)
    return (x - lo) / (hi - lo)


def _compute_multi_objective_score(
    df: pd.DataFrame,
    *,
    robust_on: bool,
    w_annual: float,
    w_excess_annual: float,
    w_sharpe: float,
    w_sortino: float,
    w_calmar: float,
    w_win_rate: float,
    w_info: float,
    w_profit_factor: float,
    w_tail_ratio: float,
    w_capital_efficiency: float,
    w_mdd: float,
    w_ulcer: float,
    w_turnover: float,
    w_oos_excess: float,
    w_oos_pass: float,
    w_oos_mdd: float,
) -> pd.Series:
    """
    多目标评分（0~100附近浮动）：
    - 收益/质量类指标加分
    - 回撤/换手类指标扣分
    - robust_on 时引入 OOS 稳健项
    """
    if df.empty:
        return pd.Series([], dtype=float)

    score = pd.Series([0.0] * len(df), index=df.index, dtype=float)
    total_w = 0.0

    def add_plus(col: str, w: float):
        nonlocal score, total_w
        if w <= 0 or col not in df.columns:
            return
        score += _minmax_norm(df[col]) * float(w)
        total_w += float(w)

    def add_minus(col: str, w: float, abs_value: bool = False):
        nonlocal score, total_w
        if w <= 0 or col not in df.columns:
            return
        s = df[col].abs() if abs_value else df[col]
        score -= _minmax_norm(s) * float(w)
        total_w += float(w)

    add_plus("annual_return_pct", w_annual)
    add_plus("excess_annual_return_pct", w_excess_annual)
    add_plus("sharpe", w_sharpe)
    add_plus("sortino", w_sortino)
    add_plus("calmar", w_calmar)
    add_plus("win_rate_pct", w_win_rate)
    add_plus("info_ratio", w_info)
    add_plus("profit_factor", w_profit_factor)
    add_plus("tail_ratio", w_tail_ratio)
    add_plus("capital_efficiency", w_capital_efficiency)
    add_minus("max_drawdown_pct", w_mdd, abs_value=True)
    add_minus("ulcer_index_pct", w_ulcer, abs_value=False)
    add_minus("annual_turnover_pct", w_turnover, abs_value=False)

    if robust_on:
        add_plus("oos_excess_total_median", w_oos_excess)
        add_plus("oos_pass_rate", w_oos_pass)
        add_minus("oos_mdd_worst", w_oos_mdd, abs_value=True)

    if total_w <= 0:
        return pd.Series([0.0] * len(df), index=df.index, dtype=float)
    return score / total_w * 100.0


def _risk_tier(max_drawdown_pct: float, annual_turnover_pct: float, sharpe: float) -> str:
    if max_drawdown_pct >= -10.0 and annual_turnover_pct <= 2500 and sharpe >= 1.0:
        return "conservative"
    if max_drawdown_pct >= -15.0 and annual_turnover_pct <= 4500 and sharpe >= 0.6:
        return "balanced"
    return "aggressive"


def _build_paper_recommendations(
    res: pd.DataFrame,
    *,
    robust_on: bool,
    top_k: int,
) -> pd.DataFrame:
    if res.empty:
        return pd.DataFrame()
    pool = res[res["pass_hard_filters"] == 1].copy()
    mode = "hard_filter_pass"
    if pool.empty:
        pool = res.copy()
        mode = "fallback_by_objective_score"
    pool = pool.head(max(1, int(top_k))).copy()
    pool.insert(0, "recommend_rank", range(1, len(pool) + 1))
    pool["selection_mode"] = mode
    pool["risk_tier"] = pool.apply(
        lambda r: _risk_tier(
            max_drawdown_pct=float(r.get("max_drawdown_pct", 0.0)),
            annual_turnover_pct=float(r.get("annual_turnover_pct", 0.0)),
            sharpe=float(r.get("sharpe", 0.0)),
        ),
        axis=1,
    )
    pool["backtest_cmd"] = pool.apply(
        lambda r: (
            "python scripts/quant_portfolio_backtest.py "
            f"--top-n {int(r['top_n'])} --holding-days {int(r['holding_days'])} "
            f"--max-single-pos {float(r['max_single_pos']):.2f} "
            + ("--use-regime-position" if int(r["use_regime_position"]) == 1 else "--no-regime-position")
            + ("" if int(r.get("enable_signal_quality_gate", 1)) == 1 else " --disable-signal-quality-gate")
            + f" --min-signal-quality {float(r.get('min_signal_quality', 0.35)):.2f}"
            + f" --ml-quality-blend {float(r.get('ml_quality_blend', 0.85)):.2f}"
            + f" --max-abs-pct-chg {float(r.get('max_abs_pct_chg', 9.0)):.2f}"
            + ("" if int(r.get("enable_feature_refactor", 1)) == 1 else " --disable-feature-refactor")
            + f" --stability-blend {float(r.get('stability_blend', 0.20)):.2f}"
            + ("" if int(r.get("enable_feature_refactor_gate", 1)) == 1 else " --disable-feature-refactor-gate")
            + f" --min-refactor-score {float(r.get('min_refactor_score', 0.45)):.2f}"
        ),
        axis=1,
    )
    pool["paper_cmd"] = pool.apply(
        lambda r: (
            "python scripts/quant_p2_paper_trade.py --broker paper "
            f"--top-n {int(r['top_n'])} --max-single-pos {float(r['max_single_pos']):.2f}"
        ),
        axis=1,
    )

    cols = [
        "recommend_rank",
        "selection_mode",
        "risk_tier",
        "top_n",
        "holding_days",
        "max_single_pos",
        "use_regime_position",
        "enable_signal_quality_gate",
        "min_signal_quality",
        "ml_quality_blend",
        "max_abs_pct_chg",
        "enable_feature_refactor",
        "stability_blend",
        "enable_feature_refactor_gate",
        "min_refactor_score",
        "objective_score",
        "rank_score",
        "annual_return_pct",
        "excess_annual_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "sortino",
        "calmar",
        "profit_factor",
        "tail_ratio",
        "capital_efficiency",
        "ulcer_index_pct",
        "win_rate_pct",
        "annual_turnover_pct",
        "constraint_fail_reasons",
        "backtest_cmd",
        "paper_cmd",
    ]
    if robust_on:
        cols.extend(["oos_excess_total_median", "oos_mdd_worst", "oos_pass_rate"])
    cols = [c for c in cols if c in pool.columns]
    return pool[cols].copy()


def _score_robust(metrics: dict[str, float], robust: dict[str, float]) -> float:
    turnover_norm = float(metrics.get("annual_turnover_pct", 0.0)) / 100.0
    sortino = min(max(float(metrics.get("sortino", 0.0)), -3.0), 4.0)
    profit_factor = min(max(float(metrics.get("profit_factor", 0.0)), 0.0), 5.0)
    ulcer_index = float(metrics.get("ulcer_index_pct", 0.0))
    return (
        0.34 * float(robust.get("oos_excess_total_median", 0.0))
        + 0.18 * float(robust.get("oos_excess_total_p25", 0.0))
        + 0.10 * float(robust.get("oos_total_median", 0.0))
        + 0.06 * float(robust.get("oos_total_p25", 0.0))
        + 0.16 * float(robust.get("oos_sharpe_mean", 0.0)) * 10.0
        + 0.12 * float(robust.get("oos_pass_rate", 0.0)) * 100.0
        + 0.05 * float(metrics.get("excess_total_return_pct", 0.0))
        + 0.04 * float(metrics.get("excess_annual_return_pct", 0.0))
        + 0.03 * float(metrics.get("annual_return_pct", 0.0))
        + 0.04 * sortino * 8.0
        + 0.03 * profit_factor * 10.0
        - 0.34 * abs(float(robust.get("oos_mdd_worst", 0.0)))
        - 0.08 * float(robust.get("oos_mdd_std", 0.0))
        - 0.04 * ulcer_index
        - 0.03 * turnover_norm
    )


def _eval_param_set(
    start: str | None,
    end: str | None,
    base_cfg_kwargs: dict,
    robust_on: bool,
    oos_windows: list[tuple[str, str]],
    oos_min_trades_per_window: int,
) -> tuple[dict[str, float], dict[str, float], float]:
    cfg = BacktestConfig(start=start, end=end, **base_cfg_kwargs)
    _, metrics = backtest_portfolio(cfg)
    robust = (
        _robust_oos_metrics(
            base_cfg_kwargs,
            oos_windows,
            min_trades_per_window=max(1, oos_min_trades_per_window),
        )
        if robust_on
        else {}
    )
    score = _score_robust(metrics, robust) if robust_on else _score(metrics)
    return metrics, robust, score


def _auto_tune_regime_params(
    args: argparse.Namespace,
    best_row: pd.Series,
    robust_on: bool,
    oos_windows: list[tuple[str, str]],
) -> dict[str, float]:
    """
    自动分市场调参（坐标下降）：
    固定最佳 TopN/Hold/MaxPos/仓位模式，仅优化三挡风险参数。
    """
    base_cfg_kwargs = dict(
        top_n=int(best_row["top_n"]),
        holding_days=int(best_row["holding_days"]),
        fee_bps=max(0.0, args.fee_bps),
        slippage_bps=max(0.0, args.slippage_bps),
        max_single_pos=min(max(float(best_row["max_single_pos"]), 0.0), 1.0),
        use_regime_position=bool(int(best_row["use_regime_position"])),
        fallback_total_position=0.60,
        exclude_st=not args.include_st,
        min_valid_positions=3,
        max_loss_per_trade=(None if args.max_loss_per_trade is None else min(max(args.max_loss_per_trade, 0.0), 1.0)),
        engine_mode=args.engine_mode,
        benchmark_mode=args.benchmark_mode,
        benchmark_file=args.benchmark_file,
        exclude_bj9=not args.include_bj9,
        enable_diversification=not args.disable_diversification,
        max_industry_positions=max(1, args.max_industry_positions),
        corr_lookback_days=max(10, args.corr_lookback_days),
        max_pair_corr=min(max(args.max_pair_corr, 0.10), 0.999),
        corr_min_obs=max(5, args.corr_min_obs),
        enable_dynamic_exit=not args.disable_dynamic_exit,
        take_profit=min(max(args.take_profit, 0.01), 0.80),
        stop_loss=min(max(args.stop_loss, 0.01), 0.50),
        trail_drawdown=min(max(args.trail_drawdown, 0.01), 0.80),
        enable_regime_risk_params=not args.disable_regime_risk_params,
        tp_normal=min(max(args.tp_normal, 0.01), 0.80),
        tp_choppy=min(max(args.tp_choppy, 0.01), 0.80),
        tp_panic=min(max(args.tp_panic, 0.01), 0.80),
        sl_normal=min(max(args.sl_normal, 0.01), 0.50),
        sl_choppy=min(max(args.sl_choppy, 0.01), 0.50),
        sl_panic=min(max(args.sl_panic, 0.01), 0.50),
        trail_normal=min(max(args.trail_normal, 0.01), 0.80),
        trail_choppy=min(max(args.trail_choppy, 0.01), 0.80),
        trail_panic=min(max(args.trail_panic, 0.01), 0.80),
        corr_normal=min(max(args.corr_normal, 0.10), 0.999),
        corr_choppy=min(max(args.corr_choppy, 0.10), 0.999),
        corr_panic=min(max(args.corr_panic, 0.10), 0.999),
        enable_risk_switch=not args.disable_risk_switch,
        risk_window=max(1, args.risk_window),
        risk_cut_win_rate=min(max(args.risk_cut_win_rate, 0.0), 1.0),
        risk_cut_avg_ret=args.risk_cut_avg_ret,
        risk_cut_factor=min(max(args.risk_cut_factor, 0.0), 1.0),
        enable_signal_quality_gate=not args.disable_signal_quality_gate,
        min_signal_quality=min(max(float(args.min_signal_quality), 0.0), 1.0),
        ml_quality_blend=min(max(float(args.ml_quality_blend), 0.0), 1.0),
        max_abs_pct_chg=max(1.0, float(args.max_abs_pct_chg)),
        enable_feature_refactor=not args.disable_feature_refactor,
        stability_blend=min(max(float(args.stability_blend), 0.0), 1.0),
        enable_feature_refactor_gate=not args.disable_feature_refactor_gate,
        min_refactor_score=min(max(float(args.min_refactor_score), 0.0), 1.0),
        verbose=False,
    )

    regime_profiles = {
        "normal": [
            {"tp": 0.14, "sl": 0.07, "trail": 0.08, "corr": 0.80},
            {"tp": 0.18, "sl": 0.08, "trail": 0.10, "corr": 0.85},
            {"tp": 0.22, "sl": 0.10, "trail": 0.12, "corr": 0.90},
        ],
        "choppy": [
            {"tp": 0.12, "sl": 0.05, "trail": 0.07, "corr": 0.70},
            {"tp": 0.14, "sl": 0.06, "trail": 0.08, "corr": 0.75},
            {"tp": 0.16, "sl": 0.07, "trail": 0.09, "corr": 0.80},
        ],
        "panic": [
            {"tp": 0.08, "sl": 0.04, "trail": 0.05, "corr": 0.60},
            {"tp": 0.10, "sl": 0.05, "trail": 0.06, "corr": 0.65},
            {"tp": 0.12, "sl": 0.06, "trail": 0.07, "corr": 0.70},
        ],
    }

    # 基线得分
    _, _, cur_score = _eval_param_set(
        start=args.start,
        end=args.end,
        base_cfg_kwargs=base_cfg_kwargs,
        robust_on=robust_on,
        oos_windows=oos_windows,
        oos_min_trades_per_window=max(1, args.oos_min_trades_per_window),
    )

    print("\n" + "=" * 72)
    print("自动分市场调参建议器")
    print("=" * 72)
    print(f"基线评分: {cur_score:.3f}")

    def _apply_regime(cfg_kwargs: dict, reg: str, cand: dict[str, float]) -> None:
        if reg == "normal":
            cfg_kwargs["tp_normal"] = cand["tp"]
            cfg_kwargs["sl_normal"] = cand["sl"]
            cfg_kwargs["trail_normal"] = cand["trail"]
            cfg_kwargs["corr_normal"] = cand["corr"]
        elif reg == "choppy":
            cfg_kwargs["tp_choppy"] = cand["tp"]
            cfg_kwargs["sl_choppy"] = cand["sl"]
            cfg_kwargs["trail_choppy"] = cand["trail"]
            cfg_kwargs["corr_choppy"] = cand["corr"]
        else:
            cfg_kwargs["tp_panic"] = cand["tp"]
            cfg_kwargs["sl_panic"] = cand["sl"]
            cfg_kwargs["trail_panic"] = cand["trail"]
            cfg_kwargs["corr_panic"] = cand["corr"]

    # 坐标下降：按 normal -> choppy -> panic 顺序逐段优化
    for reg in ["normal", "choppy", "panic"]:
        best_local = None
        best_local_score = cur_score
        for cand in regime_profiles[reg]:
            trial = dict(base_cfg_kwargs)
            _apply_regime(trial, reg, cand)
            metrics, robust, score = _eval_param_set(
                start=args.start,
                end=args.end,
                base_cfg_kwargs=trial,
                robust_on=robust_on,
                oos_windows=oos_windows,
                oos_min_trades_per_window=max(1, args.oos_min_trades_per_window),
            )
            key_metric = robust.get("oos_excess_total_median", metrics.get("excess_total_return_pct", 0.0)) if robust_on else metrics.get("excess_total_return_pct", 0.0)
            print(
                f"[{reg}] tp={cand['tp']:.2f} sl={cand['sl']:.2f} trail={cand['trail']:.2f} corr={cand['corr']:.2f} "
                f"| score={score:.3f} key={key_metric:.2f}"
            )
            if score > best_local_score:
                best_local_score = score
                best_local = cand
        if best_local is not None:
            _apply_regime(base_cfg_kwargs, reg, best_local)
            cur_score = best_local_score
            print(f"✅ 采用 {reg} 建议: {best_local} | new_score={cur_score:.3f}")
        else:
            print(f"ℹ️ {reg} 保持基线参数")

    suggestion = {
        "top_n": int(best_row["top_n"]),
        "holding_days": int(best_row["holding_days"]),
        "max_single_pos": float(best_row["max_single_pos"]),
        "use_regime_position": bool(int(best_row["use_regime_position"])),
        "tp_normal": float(base_cfg_kwargs["tp_normal"]),
        "tp_choppy": float(base_cfg_kwargs["tp_choppy"]),
        "tp_panic": float(base_cfg_kwargs["tp_panic"]),
        "sl_normal": float(base_cfg_kwargs["sl_normal"]),
        "sl_choppy": float(base_cfg_kwargs["sl_choppy"]),
        "sl_panic": float(base_cfg_kwargs["sl_panic"]),
        "trail_normal": float(base_cfg_kwargs["trail_normal"]),
        "trail_choppy": float(base_cfg_kwargs["trail_choppy"]),
        "trail_panic": float(base_cfg_kwargs["trail_panic"]),
        "corr_normal": float(base_cfg_kwargs["corr_normal"]),
        "corr_choppy": float(base_cfg_kwargs["corr_choppy"]),
        "corr_panic": float(base_cfg_kwargs["corr_panic"]),
        "score_after_tune": float(cur_score),
    }
    return suggestion


def main() -> int:
    p = argparse.ArgumentParser(description="量化组合参数优化")
    p.add_argument("--start", type=str, default=None, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, default=None, help="结束日期 YYYY-MM-DD")
    p.add_argument("--topn-grid", type=str, default="10,12,15,20", help="TopN 搜索网格")
    p.add_argument("--hold-grid", type=str, default="3,5,8,10", help="持有天数搜索网格")
    p.add_argument("--maxpos-grid", type=str, default="0.04,0.06,0.08", help="单票上限搜索网格")
    p.add_argument("--fee-bps", type=float, default=8.0, help="单边手续费(bps)")
    p.add_argument("--slippage-bps", type=float, default=5.0, help="单边滑点(bps)")
    p.add_argument("--max-loss-per-trade", type=float, default=None, help="单笔组合最大亏损(0~1)")
    p.add_argument("--engine-mode", type=str, default="hybrid", choices=["left", "right", "hybrid"], help="交易引擎模式")
    p.add_argument("--benchmark-mode", type=str, default="hs300", choices=["hs300", "synthetic", "none"], help="基准模式")
    p.add_argument("--benchmark-file", type=str, default=None, help="基准CSV文件（包含 date/trade_date 与 open/close）")
    p.add_argument("--include-bj9", action="store_true", help="包含北交所9开头代码（默认排除）")
    p.add_argument("--disable-diversification", action="store_true", help="关闭行业分散+相关性去重")
    p.add_argument("--max-industry-positions", type=int, default=3, help="单行业最多持仓数")
    p.add_argument("--corr-lookback-days", type=int, default=60, help="相关性去重回看交易日")
    p.add_argument("--max-pair-corr", type=float, default=0.85, help="任意两票最大允许相关系数")
    p.add_argument("--corr-min-obs", type=int, default=15, help="计算相关性最少样本数")
    p.add_argument("--disable-dynamic-exit", action="store_true", help="关闭动态止盈止损")
    p.add_argument("--take-profit", type=float, default=0.18, help="动态止盈阈值(0~1)")
    p.add_argument("--stop-loss", type=float, default=0.08, help="动态止损阈值(0~1)")
    p.add_argument("--trail-drawdown", type=float, default=0.10, help="浮盈回撤止盈阈值(0~1)")
    p.add_argument("--disable-regime-risk-params", action="store_true", help="关闭分市场风险参数")
    p.add_argument("--tp-normal", type=float, default=0.18, help="正常市止盈阈值")
    p.add_argument("--tp-choppy", type=float, default=0.14, help="震荡市止盈阈值")
    p.add_argument("--tp-panic", type=float, default=0.10, help="恐慌市止盈阈值")
    p.add_argument("--sl-normal", type=float, default=0.08, help="正常市止损阈值")
    p.add_argument("--sl-choppy", type=float, default=0.06, help="震荡市止损阈值")
    p.add_argument("--sl-panic", type=float, default=0.05, help="恐慌市止损阈值")
    p.add_argument("--trail-normal", type=float, default=0.10, help="正常市浮盈回撤阈值")
    p.add_argument("--trail-choppy", type=float, default=0.08, help="震荡市浮盈回撤阈值")
    p.add_argument("--trail-panic", type=float, default=0.06, help="恐慌市浮盈回撤阈值")
    p.add_argument("--corr-normal", type=float, default=0.85, help="正常市相关性上限")
    p.add_argument("--corr-choppy", type=float, default=0.75, help="震荡市相关性上限")
    p.add_argument("--corr-panic", type=float, default=0.65, help="恐慌市相关性上限")
    p.add_argument("--disable-risk-switch", action="store_true", help="关闭风险开关（近期劣化降仓）")
    p.add_argument("--risk-window", type=int, default=8, help="风险开关回看最近N笔交易")
    p.add_argument("--risk-cut-win-rate", type=float, default=0.35, help="近期胜率低于阈值则降仓")
    p.add_argument("--risk-cut-avg-ret", type=float, default=-0.005, help="近期平均收益低于阈值则降仓")
    p.add_argument("--risk-cut-factor", type=float, default=0.75, help="触发风险开关后的总仓缩放系数")
    p.add_argument("--disable-signal-quality-gate", action="store_true", help="关闭信号质量门禁（默认开启）")
    p.add_argument("--min-signal-quality", type=float, default=0.40, help="信号质量最低阈值(0~1)")
    p.add_argument("--ml-quality-blend", type=float, default=0.80, help="综合分中ML排序权重(0~1)")
    p.add_argument("--max-abs-pct-chg", type=float, default=8.5, help="信号质量中日涨跌幅惩罚阈值(%%)")
    p.add_argument("--disable-feature-refactor", action="store_true", help="关闭特征重构评分（默认开启）")
    p.add_argument("--stability-blend", type=float, default=0.30, help="重构分中稳定性权重(0~1)")
    p.add_argument("--disable-feature-refactor-gate", action="store_true", help="关闭重构分门禁（默认开启）")
    p.add_argument("--min-refactor-score", type=float, default=0.50, help="重构分最低阈值(0~1)")
    p.add_argument("--robust-mode", type=str, default="on", choices=["on", "off"], help="稳健评分模式：on=优先OOS超额与回撤稳定")
    p.add_argument("--oos-warmup-months", type=int, default=6, help="稳健模式OOS起始预热月数")
    p.add_argument("--oos-test-months", type=int, default=2, help="稳健模式单窗测试月数")
    p.add_argument("--oos-step-months", type=int, default=2, help="稳健模式窗口步长月数")
    p.add_argument("--oos-min-windows", type=int, default=3, help="稳健硬门槛最少OOS窗口数")
    p.add_argument("--oos-min-trades-per-window", type=int, default=3, help="稳健评估每窗口最少交易笔数")
    p.add_argument("--min-annual-return-pct", type=float, default=0.0, help="硬门槛：最小年化收益(%%)")
    p.add_argument("--min-excess-annual-pct", type=float, default=0.0, help="硬门槛：最小超额年化(%%)")
    p.add_argument("--min-sharpe", type=float, default=0.0, help="硬门槛：最小 Sharpe")
    p.add_argument("--min-sortino", type=float, default=0.70, help="硬门槛：最小 Sortino")
    p.add_argument("--min-win-rate-pct", type=float, default=0.0, help="硬门槛：最小胜率(%%)")
    p.add_argument("--min-profit-factor", type=float, default=1.05, help="硬门槛：最小 Profit Factor")
    p.add_argument("--min-tail-ratio", type=float, default=1.00, help="硬门槛：最小 Tail Ratio")
    p.add_argument("--min-capital-efficiency", type=float, default=0.0, help="硬门槛：最小资本效率")
    p.add_argument("--max-drawdown-limit-pct", type=float, default=-15.0, help="硬门槛：最大回撤下限(%%, 通常为负)")
    p.add_argument("--max-ulcer-index-pct", type=float, default=7.5, help="硬门槛：最大 Ulcer Index(%%)，<=0 表示不限制")
    p.add_argument("--min-oos-excess-total-median", type=float, default=0.0, help="稳健硬门槛：OOS超额收益中位数下限(%%)")
    p.add_argument("--min-oos-mdd-worst", type=float, default=-15.0, help="稳健硬门槛：OOS最差回撤下限(%%)")
    p.add_argument("--min-oos-pass-rate", type=float, default=0.45, help="稳健硬门槛：OOS通过率下限(0~1)")
    p.add_argument("--min-oos-valid-window-ratio", type=float, default=0.60, help="稳健硬门槛：OOS有效窗口占比下限(0~1)")
    p.add_argument("--turnover-cap-pct", type=float, default=4500.0, help="换手硬门槛(年化%%)，<=0 表示不限制")
    p.add_argument("--w-annual", type=float, default=0.18, help="多目标评分权重：年化收益")
    p.add_argument("--w-excess-annual", type=float, default=0.28, help="多目标评分权重：超额年化")
    p.add_argument("--w-sharpe", type=float, default=0.18, help="多目标评分权重：Sharpe")
    p.add_argument("--w-sortino", type=float, default=0.12, help="多目标评分权重：Sortino")
    p.add_argument("--w-calmar", type=float, default=0.10, help="多目标评分权重：Calmar")
    p.add_argument("--w-win-rate", type=float, default=0.08, help="多目标评分权重：胜率")
    p.add_argument("--w-info", type=float, default=0.06, help="多目标评分权重：Info Ratio")
    p.add_argument("--w-profit-factor", type=float, default=0.08, help="多目标评分权重：Profit Factor")
    p.add_argument("--w-tail-ratio", type=float, default=0.05, help="多目标评分权重：Tail Ratio")
    p.add_argument("--w-capital-efficiency", type=float, default=0.06, help="多目标评分权重：资本效率")
    p.add_argument("--w-mdd", type=float, default=0.18, help="多目标评分权重：最大回撤惩罚")
    p.add_argument("--w-ulcer", type=float, default=0.10, help="多目标评分权重：Ulcer Index 惩罚")
    p.add_argument("--w-turnover", type=float, default=0.12, help="多目标评分权重：换手惩罚")
    p.add_argument("--w-oos-excess", type=float, default=0.20, help="稳健评分权重：OOS超额收益中位数")
    p.add_argument("--w-oos-pass", type=float, default=0.10, help="稳健评分权重：OOS通过率")
    p.add_argument("--w-oos-mdd", type=float, default=0.12, help="稳健评分权重：OOS最差回撤惩罚")
    p.add_argument("--recommend-top-k", type=int, default=5, help="输出可用于模拟盘的推荐参数条数")
    p.add_argument("--auto-regime-tune", type=str, default="off", choices=["on", "off"], help="优化后自动给出分市场参数建议")
    p.add_argument("--include-st", action="store_true", help="包含 ST 股票")
    args = p.parse_args()

    topn_grid = _parse_int_grid(args.topn_grid)
    hold_grid = _parse_int_grid(args.hold_grid)
    maxpos_grid = sorted(set(float(x.strip()) for x in args.maxpos_grid.split(",") if x.strip()))
    regime_grid = [True, False]

    combos = list(product(topn_grid, hold_grid, maxpos_grid, regime_grid))
    if not combos:
        raise RuntimeError("参数网格为空")

    print("=" * 72)
    print("量化交易系统 - 参数优化")
    print("=" * 72)
    print(f"参数组合数: {len(combos)}")
    turnover_cap = None if args.turnover_cap_pct is None or args.turnover_cap_pct <= 0 else float(args.turnover_cap_pct)
    robust_on = args.robust_mode == "on"
    oos_windows: list[tuple[str, str]] = []
    if robust_on and args.start and args.end:
        start_dt = pd.to_datetime(args.start).normalize()
        end_dt = pd.to_datetime(args.end).normalize()
        oos_windows = _build_oos_windows(
            start=start_dt,
            end=end_dt,
            warmup_months=max(1, args.oos_warmup_months),
            test_months=max(1, args.oos_test_months),
            step_months=max(1, args.oos_step_months),
        )
        print(
            f"稳健模式: ON | OOS窗口={len(oos_windows)} "
            f"(warmup={args.oos_warmup_months}m, test={args.oos_test_months}m, step={args.oos_step_months}m)"
        )
    elif robust_on:
        print("稳健模式: ON，但未提供 start/end，退化为普通评分。")
        robust_on = False
    else:
        print("稳健模式: OFF（使用普通评分）")

    rows = []
    for i, (top_n, hold_days, max_pos, use_regime) in enumerate(combos, start=1):
        base_cfg_kwargs = dict(
            top_n=top_n,
            holding_days=hold_days,
            fee_bps=max(0.0, args.fee_bps),
            slippage_bps=max(0.0, args.slippage_bps),
            max_single_pos=min(max(max_pos, 0.0), 1.0),
            use_regime_position=use_regime,
            fallback_total_position=0.60,
            exclude_st=not args.include_st,
            min_valid_positions=3,
            max_loss_per_trade=(None if args.max_loss_per_trade is None else min(max(args.max_loss_per_trade, 0.0), 1.0)),
            engine_mode=args.engine_mode,
            benchmark_mode=args.benchmark_mode,
            benchmark_file=args.benchmark_file,
            exclude_bj9=not args.include_bj9,
            enable_diversification=not args.disable_diversification,
            max_industry_positions=max(1, args.max_industry_positions),
            corr_lookback_days=max(10, args.corr_lookback_days),
            max_pair_corr=min(max(args.max_pair_corr, 0.10), 0.999),
            corr_min_obs=max(5, args.corr_min_obs),
            enable_dynamic_exit=not args.disable_dynamic_exit,
            take_profit=min(max(args.take_profit, 0.01), 0.80),
            stop_loss=min(max(args.stop_loss, 0.01), 0.50),
            trail_drawdown=min(max(args.trail_drawdown, 0.01), 0.80),
            enable_regime_risk_params=not args.disable_regime_risk_params,
            tp_normal=min(max(args.tp_normal, 0.01), 0.80),
            tp_choppy=min(max(args.tp_choppy, 0.01), 0.80),
            tp_panic=min(max(args.tp_panic, 0.01), 0.80),
            sl_normal=min(max(args.sl_normal, 0.01), 0.50),
            sl_choppy=min(max(args.sl_choppy, 0.01), 0.50),
            sl_panic=min(max(args.sl_panic, 0.01), 0.50),
            trail_normal=min(max(args.trail_normal, 0.01), 0.80),
            trail_choppy=min(max(args.trail_choppy, 0.01), 0.80),
            trail_panic=min(max(args.trail_panic, 0.01), 0.80),
            corr_normal=min(max(args.corr_normal, 0.10), 0.999),
            corr_choppy=min(max(args.corr_choppy, 0.10), 0.999),
            corr_panic=min(max(args.corr_panic, 0.10), 0.999),
            enable_risk_switch=not args.disable_risk_switch,
            risk_window=max(1, args.risk_window),
            risk_cut_win_rate=min(max(args.risk_cut_win_rate, 0.0), 1.0),
            risk_cut_avg_ret=args.risk_cut_avg_ret,
            risk_cut_factor=min(max(args.risk_cut_factor, 0.0), 1.0),
            enable_signal_quality_gate=not args.disable_signal_quality_gate,
            min_signal_quality=min(max(float(args.min_signal_quality), 0.0), 1.0),
            ml_quality_blend=min(max(float(args.ml_quality_blend), 0.0), 1.0),
            max_abs_pct_chg=max(1.0, float(args.max_abs_pct_chg)),
            enable_feature_refactor=not args.disable_feature_refactor,
            stability_blend=min(max(float(args.stability_blend), 0.0), 1.0),
            enable_feature_refactor_gate=not args.disable_feature_refactor_gate,
            min_refactor_score=min(max(float(args.min_refactor_score), 0.0), 1.0),
            verbose=False,
        )
        cfg = BacktestConfig(
            start=args.start,
            end=args.end,
            **base_cfg_kwargs,
        )
        trades_df, metrics = backtest_portfolio(cfg)
        robust = _robust_oos_metrics(base_cfg_kwargs, oos_windows, min_trades_per_window=max(1, args.oos_min_trades_per_window)) if robust_on else {}
        score = _score_robust(metrics, robust) if robust_on else _score(metrics)
        pass_hard = (
            _passes_robust_hard_filters(
                metrics,
                robust,
                args.oos_min_windows,
                min_annual_return_pct=args.min_annual_return_pct,
                min_excess_annual_pct=args.min_excess_annual_pct,
                min_sharpe=args.min_sharpe,
                min_sortino=args.min_sortino,
                min_win_rate_pct=args.min_win_rate_pct,
                min_profit_factor=args.min_profit_factor,
                min_tail_ratio=args.min_tail_ratio,
                min_capital_efficiency=args.min_capital_efficiency,
                max_drawdown_limit_pct=args.max_drawdown_limit_pct,
                max_ulcer_index_pct=(None if args.max_ulcer_index_pct <= 0 else float(args.max_ulcer_index_pct)),
                min_oos_excess_total_median=args.min_oos_excess_total_median,
                min_oos_mdd_worst=args.min_oos_mdd_worst,
                min_oos_pass_rate=args.min_oos_pass_rate,
                min_oos_valid_window_ratio=args.min_oos_valid_window_ratio,
                turnover_cap_pct=turnover_cap,
            )
            if robust_on
            else _passes_hard_filters(
                metrics,
                min_annual_return_pct=args.min_annual_return_pct,
                min_excess_annual_pct=args.min_excess_annual_pct,
                min_sharpe=args.min_sharpe,
                min_sortino=args.min_sortino,
                min_win_rate_pct=args.min_win_rate_pct,
                min_profit_factor=args.min_profit_factor,
                min_tail_ratio=args.min_tail_ratio,
                min_capital_efficiency=args.min_capital_efficiency,
                max_drawdown_limit_pct=args.max_drawdown_limit_pct,
                max_ulcer_index_pct=(None if args.max_ulcer_index_pct <= 0 else float(args.max_ulcer_index_pct)),
                turnover_cap_pct=turnover_cap,
            )
        )
        fail_reasons = _constraint_fail_reasons(
            metrics=metrics,
            robust=robust,
            robust_on=robust_on,
            min_windows=args.oos_min_windows,
            min_annual_return_pct=args.min_annual_return_pct,
            min_excess_annual_pct=args.min_excess_annual_pct,
            min_sharpe=args.min_sharpe,
            min_sortino=args.min_sortino,
            min_win_rate_pct=args.min_win_rate_pct,
            min_profit_factor=args.min_profit_factor,
            min_tail_ratio=args.min_tail_ratio,
            min_capital_efficiency=args.min_capital_efficiency,
            max_drawdown_limit_pct=args.max_drawdown_limit_pct,
            max_ulcer_index_pct=(None if args.max_ulcer_index_pct <= 0 else float(args.max_ulcer_index_pct)),
            turnover_cap_pct=turnover_cap,
            min_oos_excess_total_median=args.min_oos_excess_total_median,
            min_oos_mdd_worst=args.min_oos_mdd_worst,
            min_oos_pass_rate=args.min_oos_pass_rate,
            min_oos_valid_window_ratio=args.min_oos_valid_window_ratio,
        )
        row = {
            "pass_hard_filters": int(pass_hard),
            "rank_score": score,
            "constraint_fail_count": int(len(fail_reasons)),
            "constraint_fail_reasons": ",".join(fail_reasons),
            "top_n": top_n,
            "holding_days": hold_days,
            "max_single_pos": max_pos,
            "use_regime_position": int(use_regime),
            "enable_signal_quality_gate": int(not args.disable_signal_quality_gate),
            "min_signal_quality": min(max(float(args.min_signal_quality), 0.0), 1.0),
            "ml_quality_blend": min(max(float(args.ml_quality_blend), 0.0), 1.0),
            "max_abs_pct_chg": max(1.0, float(args.max_abs_pct_chg)),
            "enable_feature_refactor": int(not args.disable_feature_refactor),
            "stability_blend": min(max(float(args.stability_blend), 0.0), 1.0),
            "enable_feature_refactor_gate": int(not args.disable_feature_refactor_gate),
            "min_refactor_score": min(max(float(args.min_refactor_score), 0.0), 1.0),
            "trade_count": metrics.get("trade_count", 0),
            "total_return_pct": metrics.get("total_return_pct", 0.0),
            "annual_return_pct": metrics.get("annual_return_pct", 0.0),
            "max_drawdown_pct": metrics.get("max_drawdown_pct", 0.0),
            "sharpe": metrics.get("sharpe", 0.0),
            "sortino": metrics.get("sortino", 0.0),
            "calmar": metrics.get("calmar", 0.0),
            "profit_factor": metrics.get("profit_factor", 0.0),
            "tail_ratio": metrics.get("tail_ratio", 0.0),
            "capital_efficiency": metrics.get("capital_efficiency", 0.0),
            "ulcer_index_pct": metrics.get("ulcer_index_pct", 0.0),
            "win_rate_pct": metrics.get("win_rate_pct", 0.0),
            "benchmark_annual_return_pct": metrics.get("benchmark_annual_return_pct", 0.0),
            "excess_annual_return_pct": metrics.get("excess_annual_return_pct", 0.0),
            "beat_rate_pct": metrics.get("beat_rate_pct", 0.0),
            "info_ratio": metrics.get("info_ratio", 0.0),
            "avg_exposure_pct": metrics.get("avg_exposure_pct", 0.0),
            "annual_turnover_pct": metrics.get("annual_turnover_pct", 0.0),
            "trades_per_year": metrics.get("trades_per_year", 0.0),
            "trades_file_rows": len(trades_df),
        }
        if robust_on:
            row.update(
                {
                    "oos_windows": robust.get("oos_windows", 0),
                    "oos_valid_windows": robust.get("oos_valid_windows", 0),
                    "oos_valid_window_ratio": robust.get("oos_valid_window_ratio", 0.0),
                    "oos_excess_annual_mean": robust.get("oos_excess_annual_mean", 0.0),
                    "oos_excess_annual_median": robust.get("oos_excess_annual_median", 0.0),
                    "oos_excess_annual_p25": robust.get("oos_excess_annual_p25", 0.0),
                    "oos_excess_total_mean": robust.get("oos_excess_total_mean", 0.0),
                    "oos_excess_total_median": robust.get("oos_excess_total_median", 0.0),
                    "oos_excess_total_p25": robust.get("oos_excess_total_p25", 0.0),
                    "oos_total_mean": robust.get("oos_total_mean", 0.0),
                    "oos_total_median": robust.get("oos_total_median", 0.0),
                    "oos_total_p25": robust.get("oos_total_p25", 0.0),
                    "oos_mdd_worst": robust.get("oos_mdd_worst", 0.0),
                    "oos_mdd_std": robust.get("oos_mdd_std", 0.0),
                    "oos_sharpe_mean": robust.get("oos_sharpe_mean", 0.0),
                    "oos_pass_rate": robust.get("oos_pass_rate", 0.0),
                }
            )
        rows.append(row)
        if robust_on:
            print(
                f"[{i:>3}/{len(combos)}] TopN={top_n} Hold={hold_days} MaxPos={max_pos:.2f} "
                f"Regime={use_regime} | OOS超额收益中位={row['oos_excess_total_median']:.2f}% "
                f"OOS最差回撤={row['oos_mdd_worst']:.2f}% OOS通过率={row['oos_pass_rate']*100:.1f}% "
                f"换手={row['annual_turnover_pct']:.1f}% 年化={row['annual_return_pct']:.2f}%"
            )
        else:
            print(
                f"[{i:>3}/{len(combos)}] TopN={top_n} Hold={hold_days} MaxPos={max_pos:.2f} "
                f"Regime={use_regime} | 年化={row['annual_return_pct']:.2f}% "
                f"超额年化={row['excess_annual_return_pct']:.2f}% "
                f"MDD={row['max_drawdown_pct']:.2f}% Sharpe={row['sharpe']:.3f} "
                f"Turnover={row['annual_turnover_pct']:.1f}%"
            )

    res = pd.DataFrame(rows)
    if res.empty:
        raise RuntimeError("优化结果为空")

    res["objective_score"] = _compute_multi_objective_score(
        res,
        robust_on=robust_on,
        w_annual=max(0.0, args.w_annual),
        w_excess_annual=max(0.0, args.w_excess_annual),
        w_sharpe=max(0.0, args.w_sharpe),
        w_sortino=max(0.0, args.w_sortino),
        w_calmar=max(0.0, args.w_calmar),
        w_win_rate=max(0.0, args.w_win_rate),
        w_info=max(0.0, args.w_info),
        w_profit_factor=max(0.0, args.w_profit_factor),
        w_tail_ratio=max(0.0, args.w_tail_ratio),
        w_capital_efficiency=max(0.0, args.w_capital_efficiency),
        w_mdd=max(0.0, args.w_mdd),
        w_ulcer=max(0.0, args.w_ulcer),
        w_turnover=max(0.0, args.w_turnover),
        w_oos_excess=max(0.0, args.w_oos_excess),
        w_oos_pass=max(0.0, args.w_oos_pass),
        w_oos_mdd=max(0.0, args.w_oos_mdd),
    )

    res = res.sort_values(
        ["pass_hard_filters", "objective_score", "rank_score"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    res.insert(0, "rank", range(1, len(res) + 1))

    dirs = ensure_output_dirs(OUTPUT_DIR)
    base_dir = Path(OUTPUT_DIR)
    out_new = dirs["backtest"] / "quant_optimization_results.csv"
    out_legacy = base_dir / "quant_optimization_results.csv"
    write_dual_csv(res, out_new, out_legacy, index=False, encoding="utf-8-sig")

    rec_df = _build_paper_recommendations(
        res=res,
        robust_on=robust_on,
        top_k=max(1, int(args.recommend_top_k)),
    )
    rec_new = dirs["backtest"] / "quant_strategy_paper_recommendations.csv"
    rec_legacy = base_dir / "quant_strategy_paper_recommendations.csv"
    write_dual_csv(rec_df, rec_new, rec_legacy, index=False, encoding="utf-8-sig")

    rec_json = dirs["backtest"] / "quant_strategy_paper_recommendations.json"
    rec_payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "robust_mode": bool(robust_on),
        "rows_total": int(len(res)),
        "rows_pass_hard_filters": int(res["pass_hard_filters"].sum()),
        "recommend_top_k": int(len(rec_df)),
        "recommendations": rec_df.to_dict(orient="records"),
    }
    rec_json.write_text(json.dumps(rec_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print("优化结果 Top 10")
    print("=" * 72)
    print(res.head(10).to_string(index=False))
    print(f"\n完整结果已保存: {out_new}")
    print(f"模拟盘推荐参数已保存: {rec_new}")

    pass_cnt = int(res["pass_hard_filters"].sum()) if not res.empty else 0
    print(f"\n硬门槛通过组合数: {pass_cnt}/{len(res)}")
    if pass_cnt == 0:
        print("⚠️ 当前网格下无组合通过硬门槛，以下推荐将回退为“综合分最高”组合。")

    fail_counter = (
        res.loc[res["pass_hard_filters"] == 0, "constraint_fail_reasons"]
        .astype(str)
        .str.split(",")
        .explode()
        .str.strip()
    )
    fail_counter = fail_counter[fail_counter != ""]
    if len(fail_counter) > 0:
        print("\n失效配置原因 Top:")
        print(fail_counter.value_counts().head(10).to_string())

    if not res.empty:
        eligible = res[res["pass_hard_filters"] == 1]
        best = eligible.iloc[0] if not eligible.empty else res.iloc[0]
        print("\n推荐实盘参数:")
        print(
            f"top_n={int(best['top_n'])}, holding_days={int(best['holding_days'])}, "
            f"max_single_pos={best['max_single_pos']:.2f}, use_regime_position={bool(best['use_regime_position'])}"
        )

        if args.auto_regime_tune == "on":
            suggestion = _auto_tune_regime_params(args, best, robust_on=robust_on, oos_windows=oos_windows)
            sug_file = dirs["backtest"] / "quant_regime_suggestion.json"
            sug_file.write_text(json.dumps(suggestion, ensure_ascii=False, indent=2), encoding="utf-8")
            print("\n分市场参数建议:")
            print(
                f"tp(normal/choppy/panic)=({suggestion['tp_normal']:.2f}/{suggestion['tp_choppy']:.2f}/{suggestion['tp_panic']:.2f}), "
                f"sl=({suggestion['sl_normal']:.2f}/{suggestion['sl_choppy']:.2f}/{suggestion['sl_panic']:.2f}), "
                f"trail=({suggestion['trail_normal']:.2f}/{suggestion['trail_choppy']:.2f}/{suggestion['trail_panic']:.2f}), "
                f"corr=({suggestion['corr_normal']:.2f}/{suggestion['corr_choppy']:.2f}/{suggestion['corr_panic']:.2f})"
            )
            print(f"建议文件已保存: {sug_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
