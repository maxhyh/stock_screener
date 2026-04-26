#!/usr/bin/env python3
"""
按配置档位运行量化组合回测。

示例：
  python scripts/run_quant_profile.py --profile conservative --start 2025-01-01 --end 2026-03-20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from quant_portfolio_backtest import BacktestConfig, backtest_portfolio, _print_summary, _save_outputs


def _load_profiles(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    p = argparse.ArgumentParser(description="按档位配置运行量化组合回测")
    p.add_argument("--config", type=str, default=os.path.join(BASE_DIR, "config", "quant_live_profiles.json"), help="配置文件路径")
    p.add_argument(
        "--profile",
        type=str,
        default=None,
        help="档位名称（如 conservative/balanced/balanced_regime/balanced_h8/aggressive）",
    )
    p.add_argument("--start", type=str, default=None, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, default=None, help="结束日期 YYYY-MM-DD")
    p.add_argument("--benchmark-file", type=str, default=None, help="可选覆盖基准文件")
    args = p.parse_args()

    cfg_file = os.path.abspath(args.config)
    if not os.path.exists(cfg_file):
        raise FileNotFoundError(f"未找到配置文件: {cfg_file}")

    root = _load_profiles(cfg_file)
    profiles = root.get("profiles", {})
    if not profiles:
        raise RuntimeError("配置文件中未找到 profiles")

    profile_name = args.profile or root.get("default_profile")
    if profile_name not in profiles:
        raise RuntimeError(f"未知 profile: {profile_name}; 可选: {', '.join(sorted(profiles.keys()))}")

    pcfg = dict(profiles[profile_name])

    cfg = BacktestConfig(
        start=args.start,
        end=args.end,
        top_n=int(pcfg.get("top_n", 10)),
        holding_days=int(pcfg.get("holding_days", 8)),
        fee_bps=float(pcfg.get("fee_bps", 8.0)),
        slippage_bps=float(pcfg.get("slippage_bps", 5.0)),
        max_single_pos=float(pcfg.get("max_single_pos", 0.06)),
        use_regime_position=bool(pcfg.get("use_regime_position", True)),
        fallback_total_position=float(pcfg.get("fallback_total_position", 0.60)),
        exclude_st=bool(pcfg.get("exclude_st", True)),
        min_valid_positions=int(pcfg.get("min_valid_positions", 3)),
        max_loss_per_trade=(None if pcfg.get("max_loss_per_trade", None) is None else float(pcfg.get("max_loss_per_trade"))),
        loss_clamp_enabled=bool(pcfg.get("promotion_loss_clamp_enabled", False)),
        engine_mode=str(pcfg.get("engine_mode", "hybrid")),
        benchmark_mode=str(pcfg.get("benchmark_mode", "hs300")),
        benchmark_file=args.benchmark_file,
        exclude_bj9=bool(pcfg.get("exclude_bj9", True)),
        max_industry_positions=int(pcfg.get("max_industry_positions", 3)),
        corr_lookback_days=int(pcfg.get("corr_lookback_days", 60)),
        max_pair_corr=float(pcfg.get("max_pair_corr", 0.85)),
        corr_min_obs=int(pcfg.get("corr_min_obs", 15)),
        take_profit=float(pcfg.get("take_profit", 0.18)),
        stop_loss=float(pcfg.get("stop_loss", 0.08)),
        trail_drawdown=float(pcfg.get("trail_drawdown", 0.10)),
        tp_normal=float(pcfg.get("tp_normal", 0.18)),
        tp_choppy=float(pcfg.get("tp_choppy", 0.14)),
        tp_panic=float(pcfg.get("tp_panic", 0.10)),
        sl_normal=float(pcfg.get("sl_normal", 0.08)),
        sl_choppy=float(pcfg.get("sl_choppy", 0.06)),
        sl_panic=float(pcfg.get("sl_panic", 0.05)),
        trail_normal=float(pcfg.get("trail_normal", 0.10)),
        trail_choppy=float(pcfg.get("trail_choppy", 0.08)),
        trail_panic=float(pcfg.get("trail_panic", 0.06)),
        corr_normal=float(pcfg.get("corr_normal", 0.85)),
        corr_choppy=float(pcfg.get("corr_choppy", 0.75)),
        corr_panic=float(pcfg.get("corr_panic", 0.65)),
        risk_window=int(pcfg.get("risk_window", 5)),
        risk_cut_win_rate=float(pcfg.get("risk_cut_win_rate", 0.35)),
        risk_cut_avg_ret=float(pcfg.get("risk_cut_avg_ret", -0.005)),
        risk_cut_factor=float(pcfg.get("risk_cut_factor", 0.60)),
        min_signal_quality=float(pcfg.get("min_signal_quality", 0.40)),
        ml_quality_blend=float(pcfg.get("ml_quality_blend", 0.80)),
        max_abs_pct_chg=float(pcfg.get("max_abs_pct_chg", 8.5)),
        stability_blend=float(pcfg.get("stability_blend", 0.30)),
        min_refactor_score=float(pcfg.get("min_refactor_score", 0.50)),
        min_price=float(pcfg.get("min_price", 0.0)),
        min_amount_ma20=float(pcfg.get("min_amount_ma20", 0.0)),
        liquidity_blend=float(pcfg.get("liquidity_blend", 0.0)),
        adv_penalty_blend=float(pcfg.get("adv_penalty_blend", 0.0)),
        industry_crowding_blend=float(pcfg.get("industry_crowding_blend", 0.0)),
        optimizer_mode=str(pcfg.get("optimizer_mode", "score_weight")),
        target_capital_base=float(pcfg.get("target_capital_base", 1_000_000.0)),
        target_max_industry_weight=float(pcfg.get("target_max_industry_weight", pcfg.get("risk_max_industry_weight", 0.0))),
        target_max_adv_participation=float(pcfg.get("target_max_adv_participation", pcfg.get("risk_max_adv_participation", 0.0))),
        target_capacity_amount_col=str(pcfg.get("target_capacity_amount_col", "amount_ma20")),
        target_capacity_amount_buffer=float(pcfg.get("target_capacity_amount_buffer", 1.0)),
        redistribute_clipped_weight=bool(pcfg.get("redistribute_clipped_weight", False)),
        impact_model=str(pcfg.get("impact_model", "sqrt")),
        impact_base_bps=float(pcfg.get("impact_base_bps", 0.0)),
        impact_participation_bps=float(pcfg.get("impact_participation_bps", 0.0)),
        impact_power=float(pcfg.get("impact_power", 0.5)),
    )

    print("=" * 72)
    print("量化交易系统 - 档位运行")
    print("=" * 72)
    print(f"profile: {profile_name}")
    print(
        f"区间: {cfg.start or 'auto'} ~ {cfg.end or 'auto'} | TopN={cfg.top_n} | "
        f"Hold={cfg.holding_days} | RegimePos={cfg.use_regime_position} | "
        f"Engine={cfg.engine_mode} | Benchmark={cfg.benchmark_mode}"
    )

    trades_df, metrics = backtest_portfolio(cfg)
    _print_summary(metrics, cfg)
    detail_file, summary_file, json_file = _save_outputs(trades_df, metrics, cfg)

    print(f"\n交易明细已保存: {detail_file}")
    print(f"汇总表已保存: {summary_file}")
    print(f"汇总JSON已保存: {json_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
