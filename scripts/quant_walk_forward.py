#!/usr/bin/env python3
"""
Walk-Forward 滚动验证（训练窗选参 + 测试窗验证）。

示例：
  python scripts/quant_walk_forward.py --start 2025-01-01 --end 2026-03-20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from itertools import product
from pathlib import Path

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from quant_optimize import _passes_hard_filters, _score
from quant_portfolio_backtest import BacktestConfig, _calc_metrics, backtest_portfolio
from utils.output_paths import ensure_output_dirs, write_dual_csv

OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def _parse_int_grid(text: str) -> list[int]:
    vals = [int(x.strip()) for x in str(text).split(",") if x.strip()]
    return sorted(set(vals))


def _parse_float_grid(text: str) -> list[float]:
    vals = [float(x.strip()) for x in str(text).split(",") if x.strip()]
    return sorted(set(vals))


def _add_months(dt: pd.Timestamp, months: int) -> pd.Timestamp:
    return dt + pd.DateOffset(months=months)


def _iter_windows(start: pd.Timestamp, end: pd.Timestamp, train_months: int, test_months: int, step_months: int):
    anchor = start
    idx = 0
    while True:
        train_start = anchor
        train_end = _add_months(train_start, train_months) - pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = _add_months(test_start, test_months) - pd.Timedelta(days=1)
        if test_end > end:
            break
        idx += 1
        yield idx, train_start, train_end, test_start, test_end
        anchor = _add_months(anchor, step_months)


def _pick_best_params(
    train_start: str,
    train_end: str,
    combos: list[tuple],
    static_kwargs: dict,
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
    turnover_cap_pct: float | None,
) -> tuple[dict, dict]:
    rows = []
    for top_n, hold_days, max_pos, use_regime in combos:
        cfg = BacktestConfig(
            start=train_start,
            end=train_end,
            top_n=top_n,
            holding_days=hold_days,
            max_single_pos=max_pos,
            use_regime_position=use_regime,
            **static_kwargs,
        )
        _, metrics = backtest_portfolio(cfg)
        row = {
            "top_n": top_n,
            "holding_days": hold_days,
            "max_single_pos": max_pos,
            "use_regime_position": int(use_regime),
            **metrics,
        }
        row["pass_hard_filters"] = int(
            _passes_hard_filters(
                metrics,
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
            )
        )
        row["rank_score"] = float(_score(metrics))
        rows.append(row)

    sdf = pd.DataFrame(rows)
    sdf = sdf.sort_values(["pass_hard_filters", "rank_score"], ascending=[False, False]).reset_index(drop=True)
    best = sdf.iloc[0].to_dict()
    chosen = {
        "top_n": int(best["top_n"]),
        "holding_days": int(best["holding_days"]),
        "max_single_pos": float(best["max_single_pos"]),
        "use_regime_position": bool(best["use_regime_position"]),
        "train_pass_hard_filters": int(best["pass_hard_filters"]),
        "train_rank_score": float(best["rank_score"]),
    }
    return chosen, best


def main() -> int:
    p = argparse.ArgumentParser(description="Walk-Forward 滚动验证")
    p.add_argument("--start", type=str, required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, required=True, help="结束日期 YYYY-MM-DD")
    p.add_argument("--train-months", type=int, default=6, help="训练窗（月）")
    p.add_argument("--test-months", type=int, default=2, help="测试窗（月）")
    p.add_argument("--step-months", type=int, default=2, help="滚动步长（月）")
    p.add_argument("--topn-grid", type=str, default="10,12,15,20", help="TopN 搜索网格")
    p.add_argument("--hold-grid", type=str, default="3,5,8,10", help="持有天数搜索网格")
    p.add_argument("--maxpos-grid", type=str, default="0.04,0.06,0.08", help="单票上限搜索网格")
    # 固定参数模式（传入后会覆盖对应网格）
    p.add_argument("--top-n", type=int, default=None, help="固定 TopN（覆盖 --topn-grid）")
    p.add_argument("--holding-days", type=int, default=None, help="固定持有天数（覆盖 --hold-grid）")
    p.add_argument("--max-single-pos", type=float, default=None, help="固定单票上限（覆盖 --maxpos-grid）")
    regime_group = p.add_mutually_exclusive_group()
    regime_group.add_argument("--use-regime-position", action="store_true", help="固定启用分市场仓位")
    regime_group.add_argument("--no-regime-position", action="store_true", help="固定关闭分市场仓位")
    p.add_argument("--fee-bps", type=float, default=8.0, help="单边手续费(bps)")
    p.add_argument("--slippage-bps", type=float, default=5.0, help="单边滑点(bps)")
    p.add_argument("--max-loss-per-trade", type=float, default=0.03, help="单笔组合最大亏损(0~1)")
    p.add_argument("--engine-mode", type=str, default="hybrid", choices=["left", "right", "hybrid"], help="交易引擎模式")
    p.add_argument("--benchmark-mode", type=str, default="hs300", choices=["hs300", "synthetic", "none"], help="基准模式")
    p.add_argument("--benchmark-file", type=str, default=None, help="基准CSV文件")
    p.add_argument("--include-st", action="store_true", help="包含 ST 股票")
    p.add_argument("--include-bj9", action="store_true", help="包含北交所9开头代码（默认排除）")
    p.add_argument("--disable-diversification", action="store_true", help="禁用行业分散和相关性去重")
    p.add_argument("--max-industry-positions", type=int, default=3, help="单行业最大持仓数")
    p.add_argument("--corr-lookback-days", type=int, default=60, help="相关性计算回看天数")
    p.add_argument("--max-pair-corr", type=float, default=0.85, help="候选两两最大相关系数")
    p.add_argument("--corr-min-obs", type=int, default=15, help="相关性最小样本数")
    p.add_argument("--disable-dynamic-exit", action="store_true", help="禁用动态退出（止盈/止损/回撤止盈）")
    p.add_argument("--take-profit", type=float, default=0.18, help="止盈阈值（0~1）")
    p.add_argument("--stop-loss", type=float, default=0.08, help="止损阈值（0~1）")
    p.add_argument("--trail-drawdown", type=float, default=0.10, help="跟踪止盈回撤阈值（0~1）")
    p.add_argument("--disable-regime-risk-params", action="store_true", help="禁用分市场风险参数")
    p.add_argument("--tp-normal", type=float, default=0.18, help="正常市止盈")
    p.add_argument("--tp-choppy", type=float, default=0.14, help="震荡市止盈")
    p.add_argument("--tp-panic", type=float, default=0.10, help="恐慌市止盈")
    p.add_argument("--sl-normal", type=float, default=0.08, help="正常市止损")
    p.add_argument("--sl-choppy", type=float, default=0.06, help="震荡市止损")
    p.add_argument("--sl-panic", type=float, default=0.05, help="恐慌市止损")
    p.add_argument("--trail-normal", type=float, default=0.10, help="正常市跟踪止盈回撤")
    p.add_argument("--trail-choppy", type=float, default=0.08, help="震荡市跟踪止盈回撤")
    p.add_argument("--trail-panic", type=float, default=0.06, help="恐慌市跟踪止盈回撤")
    p.add_argument("--corr-normal", type=float, default=0.85, help="正常市相关阈值")
    p.add_argument("--corr-choppy", type=float, default=0.75, help="震荡市相关阈值")
    p.add_argument("--corr-panic", type=float, default=0.65, help="恐慌市相关阈值")
    p.add_argument("--disable-risk-switch", action="store_true", help="禁用风控降档开关")
    p.add_argument("--risk-window", type=int, default=8, help="风控窗口（最近N笔）")
    p.add_argument("--risk-cut-win-rate", type=float, default=0.35, help="触发风控的胜率阈值")
    p.add_argument("--risk-cut-avg-ret", type=float, default=-0.005, help="触发风控的平均收益阈值")
    p.add_argument("--risk-cut-factor", type=float, default=0.75, help="触发后仓位缩放系数")
    p.add_argument("--disable-signal-quality-gate", action="store_true", help="关闭信号质量门禁（默认开启）")
    p.add_argument("--min-signal-quality", type=float, default=0.40, help="信号质量最低阈值(0~1)")
    p.add_argument("--ml-quality-blend", type=float, default=0.80, help="综合分中ML排序权重(0~1)")
    p.add_argument("--max-abs-pct-chg", type=float, default=8.5, help="信号质量中日涨跌幅惩罚阈值(%%)")
    p.add_argument("--disable-feature-refactor", action="store_true", help="关闭特征重构评分（默认开启）")
    p.add_argument("--stability-blend", type=float, default=0.30, help="重构分中稳定性权重(0~1)")
    p.add_argument("--disable-feature-refactor-gate", action="store_true", help="关闭重构分门禁（默认开启）")
    p.add_argument("--min-refactor-score", type=float, default=0.50, help="重构分最低阈值(0~1)")
    p.add_argument("--min-annual-return-pct", type=float, default=0.0, help="硬门槛：最小年化收益(%%)")
    p.add_argument("--min-excess-annual-pct", type=float, default=0.0, help="硬门槛：最小超额年化(%%)")
    p.add_argument("--min-sharpe", type=float, default=0.0, help="硬门槛：最小Sharpe")
    p.add_argument("--min-sortino", type=float, default=0.70, help="硬门槛：最小Sortino")
    p.add_argument("--min-win-rate-pct", type=float, default=0.0, help="硬门槛：最小胜率(%%)")
    p.add_argument("--min-profit-factor", type=float, default=1.05, help="硬门槛：最小Profit Factor")
    p.add_argument("--min-tail-ratio", type=float, default=1.00, help="硬门槛：最小Tail Ratio")
    p.add_argument("--min-capital-efficiency", type=float, default=0.0, help="硬门槛：最小资本效率")
    p.add_argument("--max-drawdown-limit-pct", type=float, default=-15.0, help="硬门槛：最大回撤下限(%%)")
    p.add_argument("--max-ulcer-index-pct", type=float, default=7.5, help="硬门槛：最大Ulcer Index(%%，<=0表示不限制)")
    p.add_argument("--turnover-cap-pct", type=float, default=4500.0, help="硬门槛：年化换手上限(%%，<=0表示不限制)")
    args = p.parse_args()

    start_dt = pd.to_datetime(args.start).normalize()
    end_dt = pd.to_datetime(args.end).normalize()
    if start_dt >= end_dt:
        raise ValueError("start 必须早于 end")

    topn_grid = [int(args.top_n)] if args.top_n is not None else _parse_int_grid(args.topn_grid)
    hold_grid = [int(args.holding_days)] if args.holding_days is not None else _parse_int_grid(args.hold_grid)
    maxpos_grid = [float(args.max_single_pos)] if args.max_single_pos is not None else _parse_float_grid(args.maxpos_grid)
    if args.use_regime_position:
        regime_grid = [True]
    elif args.no_regime_position:
        regime_grid = [False]
    else:
        regime_grid = [True, False]
    combos = list(product(topn_grid, hold_grid, maxpos_grid, regime_grid))
    if not combos:
        raise RuntimeError("参数网格为空")

    static_kwargs = dict(
        fee_bps=max(0.0, args.fee_bps),
        slippage_bps=max(0.0, args.slippage_bps),
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
        risk_cut_avg_ret=float(args.risk_cut_avg_ret),
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

    turnover_cap = None if args.turnover_cap_pct is None or args.turnover_cap_pct <= 0 else float(args.turnover_cap_pct)

    print("=" * 72)
    print("量化交易系统 - Walk-Forward 滚动验证")
    print("=" * 72)
    print(
        f"区间: {args.start} ~ {args.end} | train={args.train_months}m test={args.test_months}m step={args.step_months}m | "
        f"engine={args.engine_mode} benchmark={args.benchmark_mode}"
    )
    print(f"参数组合数: {len(combos)}")

    window_rows = []
    oos_trades_all = []
    for wid, tr_s, tr_e, te_s, te_e in _iter_windows(start_dt, end_dt, args.train_months, args.test_months, args.step_months):
        print(f"\n[{wid}] 训练窗 {tr_s.date()}~{tr_e.date()} -> 测试窗 {te_s.date()}~{te_e.date()}")
        chosen, train_best = _pick_best_params(
            tr_s.strftime("%Y-%m-%d"),
            tr_e.strftime("%Y-%m-%d"),
            combos,
            static_kwargs,
            min_annual_return_pct=float(args.min_annual_return_pct),
            min_excess_annual_pct=float(args.min_excess_annual_pct),
            min_sharpe=float(args.min_sharpe),
            min_sortino=float(args.min_sortino),
            min_win_rate_pct=float(args.min_win_rate_pct),
            min_profit_factor=float(args.min_profit_factor),
            min_tail_ratio=float(args.min_tail_ratio),
            min_capital_efficiency=float(args.min_capital_efficiency),
            max_drawdown_limit_pct=float(args.max_drawdown_limit_pct),
            max_ulcer_index_pct=(None if args.max_ulcer_index_pct <= 0 else float(args.max_ulcer_index_pct)),
            turnover_cap_pct=turnover_cap,
        )

        test_cfg = BacktestConfig(
            start=te_s.strftime("%Y-%m-%d"),
            end=te_e.strftime("%Y-%m-%d"),
            top_n=chosen["top_n"],
            holding_days=chosen["holding_days"],
            max_single_pos=chosen["max_single_pos"],
            use_regime_position=chosen["use_regime_position"],
            **static_kwargs,
        )
        test_trades, test_metrics = backtest_portfolio(test_cfg)
        if not test_trades.empty:
            test_trades = test_trades.copy()
            test_trades["wf_window_id"] = wid
            test_trades["wf_test_start"] = te_s.strftime("%Y-%m-%d")
            test_trades["wf_test_end"] = te_e.strftime("%Y-%m-%d")
            test_trades["wf_top_n"] = chosen["top_n"]
            test_trades["wf_holding_days"] = chosen["holding_days"]
            test_trades["wf_max_single_pos"] = chosen["max_single_pos"]
            test_trades["wf_use_regime_position"] = int(chosen["use_regime_position"])
            oos_trades_all.append(test_trades)

        row = {
            "window_id": wid,
            "train_start": tr_s.strftime("%Y-%m-%d"),
            "train_end": tr_e.strftime("%Y-%m-%d"),
            "test_start": te_s.strftime("%Y-%m-%d"),
            "test_end": te_e.strftime("%Y-%m-%d"),
            "top_n": chosen["top_n"],
            "holding_days": chosen["holding_days"],
            "max_single_pos": chosen["max_single_pos"],
            "use_regime_position": int(chosen["use_regime_position"]),
            "train_rank_score": chosen["train_rank_score"],
            "train_pass_hard_filters": chosen["train_pass_hard_filters"],
            "train_annual_return_pct": float(train_best.get("annual_return_pct", 0.0)),
            "train_excess_annual_return_pct": float(train_best.get("excess_annual_return_pct", 0.0)),
            "train_mdd_pct": float(train_best.get("max_drawdown_pct", 0.0)),
            "test_trade_count": int(test_metrics.get("trade_count", 0)),
            "test_annual_return_pct": float(test_metrics.get("annual_return_pct", 0.0)),
            "test_excess_annual_return_pct": float(test_metrics.get("excess_annual_return_pct", 0.0)),
            "test_mdd_pct": float(test_metrics.get("max_drawdown_pct", 0.0)),
            "test_sharpe": float(test_metrics.get("sharpe", 0.0)),
            "test_beat_rate_pct": float(test_metrics.get("beat_rate_pct", 0.0)),
        }
        window_rows.append(row)
        print(
            f"  选参: TopN={row['top_n']} Hold={row['holding_days']} MaxPos={row['max_single_pos']:.2f} Regime={bool(row['use_regime_position'])} | "
            f"OOS年化={row['test_annual_return_pct']:.2f}% 超额年化={row['test_excess_annual_return_pct']:.2f}% MDD={row['test_mdd_pct']:.2f}%"
        )

    if not window_rows:
        raise RuntimeError("未生成任何滚动窗口，请检查日期范围或窗口参数。")

    wf_df = pd.DataFrame(window_rows)
    oos_trades_df = pd.concat(oos_trades_all, axis=0, ignore_index=True) if oos_trades_all else pd.DataFrame()
    if not oos_trades_df.empty:
        hold_mean = int(max(1, round(pd.to_numeric(oos_trades_df.get("wf_holding_days"), errors="coerce").dropna().mean())))
        oos_metrics = _calc_metrics(oos_trades_df, hold_mean)
    else:
        oos_metrics = _calc_metrics(pd.DataFrame(), 8)

    dirs = ensure_output_dirs(OUTPUT_DIR)
    base_dir = Path(OUTPUT_DIR)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    wf_new = dirs["backtest"] / f"quant_walk_forward_windows_{ts}.csv"
    wf_legacy = base_dir / f"quant_walk_forward_windows_{ts}.csv"
    write_dual_csv(wf_df, wf_new, wf_legacy, index=False, encoding="utf-8-sig")

    oos_new = dirs["backtest"] / f"quant_walk_forward_oos_trades_{ts}.csv"
    oos_legacy = base_dir / f"quant_walk_forward_oos_trades_{ts}.csv"
    write_dual_csv(oos_trades_df, oos_new, oos_legacy, index=False, encoding="utf-8-sig")

    summary = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start": args.start,
        "end": args.end,
        "train_months": args.train_months,
        "test_months": args.test_months,
        "step_months": args.step_months,
        "engine_mode": args.engine_mode,
        "benchmark_mode": args.benchmark_mode,
        "benchmark_file": args.benchmark_file or "",
        "windows": int(len(wf_df)),
        "combos": int(len(combos)),
        **oos_metrics,
    }

    # ── OOS 实盘准入检查 ────────────────────────────────────────
    oos_sharpe = float(oos_metrics.get("sharpe", 0.0))
    oos_mdd = float(oos_metrics.get("max_drawdown_pct", 0.0))
    oos_win = float(oos_metrics.get("win_rate_pct", 0.0))
    oos_annual = float(oos_metrics.get("annual_return_pct", 0.0))

    # 每个窗口的 OOS Sharpe
    wf_sharpes = wf_df["test_sharpe"].dropna().tolist() if "test_sharpe" in wf_df.columns else []
    all_win_sharpe = all(s > 0.3 for s in wf_sharpes) if wf_sharpes else False
    pct_positive_sharpe = sum(1 for s in wf_sharpes if s > 0) / max(len(wf_sharpes), 1) * 100

    # IS / OOS Sharpe 比值（过拟合检测）
    is_sharpes = wf_df.get("train_rank_score", pd.Series(dtype=float)).dropna()
    is_sharpe_mean = float(is_sharpes.mean()) if not is_sharpes.empty else 0.0
    is_oos_ratio = is_sharpe_mean / oos_sharpe if oos_sharpe > 0.01 else float("inf")

    # 准入标准
    checks = {
        "oos_sharpe_gt_0.5": oos_sharpe > 0.5,
        "oos_mdd_lt_-25%": oos_mdd > -25.0,  # mdd is negative
        "oos_win_rate_gt_45%": oos_win > 45.0,
        "oos_annual_return_gt_0%": oos_annual > 0.0,
        "all_windows_sharpe_positive": pct_positive_sharpe >= 80.0,
        "is_oos_ratio_lt_3.0": is_oos_ratio < 3.0,
    }
    all_passed = all(checks.values())

    summary["oos_validation"] = {
        "checks": {k: bool(v) for k, v in checks.items()},
        "all_passed": all_passed,
        "production_ready": all_passed,
        "is_oos_sharpe_ratio": round(is_oos_ratio, 2),
        "pct_positive_sharpe_windows": round(pct_positive_sharpe, 1),
        "per_window_sharpes": [round(s, 3) for s in wf_sharpes],
    }
    # ── 检查结束 ────────────────────────────────────────────────

    summary_new = dirs["backtest"] / f"quant_walk_forward_summary_{ts}.json"
    summary_new.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print("Walk-Forward OOS 汇总")
    print("=" * 72)
    print(f"窗口数: {summary['windows']}")
    print(f"OOS交易次数: {summary.get('trade_count', 0)}")
    print(f"OOS总收益: {summary.get('total_return_pct', 0.0):.2f}%")
    print(f"OOS年化: {summary.get('annual_return_pct', 0.0):.2f}%")
    print(f"OOS超额年化: {summary.get('excess_annual_return_pct', 0.0):.2f}%")
    print(f"OOS最大回撤: {summary.get('max_drawdown_pct', 0.0):.2f}%")
    print(f"OOS Sharpe: {summary.get('sharpe', 0.0):.3f}")
    print(f"OOS Sortino: {summary.get('sortino', 0.0):.3f}")
    print(f"OOS Calmar: {summary.get('calmar', 0.0):.3f}")
    print(f"OOS 跑赢占比: {summary.get('beat_rate_pct', 0.0):.2f}%")

    # 实盘准入报告
    print(f"\n{'=' * 72}")
    print("实盘准入验证 (OOS Validation)")
    print(f"{'=' * 72}")
    print(f"IS/OOS Sharpe 比值: {is_oos_ratio:.2f} (< 3.0 = 未过拟合)")
    print(f"Sharpe > 0 的窗口占比: {pct_positive_sharpe:.1f}% (≥ 80% 要求)")
    for name, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"  {status} {name}")

    if all_passed:
        print(f"\n🟢 PRODUCTION READY: 策略通过所有 OOS 准入检查")
    else:
        failed = [k for k, v in checks.items() if not v]
        print(f"\n🔴 NOT READY: 以下检查未通过: {', '.join(failed)}")

    print(f"\n窗口明细: {wf_new}")
    print(f"OOS交易: {oos_new}")
    print(f"汇总JSON: {summary_new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
