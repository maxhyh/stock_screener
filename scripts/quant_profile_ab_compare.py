#!/usr/bin/env python3
"""
按量化 profile 执行 A/B 回测并导出对比指标表。

示例：
  python scripts/quant_profile_ab_compare.py \
    --base-profile balanced \
    --compare-profile balanced_regime \
    --start 2025-01-01 --end 2026-03-20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from quant_portfolio_backtest import BacktestConfig, backtest_portfolio
from utils.output_paths import ensure_output_dirs, write_dual_csv

OUTPUT_DIR = os.path.join(BASE_DIR, "output")

DISPLAY_METRICS = [
    "trade_count",
    "total_return_pct",
    "annual_return_pct",
    "excess_total_return_pct",
    "excess_annual_return_pct",
    "max_drawdown_pct",
    "sharpe",
    "sortino",
    "calmar",
    "profit_factor",
    "tail_ratio",
    "ulcer_index_pct",
    "raw_total_return_pct",
    "raw_annual_return_pct",
    "raw_max_drawdown_pct",
    "raw_sharpe",
    "raw_sortino",
    "raw_calmar",
    "loss_clamp_used_count",
    "capital_efficiency",
    "win_rate_pct",
    "beat_rate_pct",
    "annual_turnover_pct",
    "avg_exposure_pct",
]


def _load_profiles(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        root = json.load(f)
    if not isinstance(root, dict):
        raise RuntimeError("配置文件格式错误：根节点必须是对象")
    profiles = root.get("profiles", {})
    if not isinstance(profiles, dict) or not profiles:
        raise RuntimeError("配置文件中未找到 profiles")
    return root


def _build_cfg(profile_cfg: dict, args: argparse.Namespace) -> BacktestConfig:
    return BacktestConfig(
        start=args.start,
        end=args.end,
        top_n=int(profile_cfg.get("top_n", 10)),
        holding_days=int(profile_cfg.get("holding_days", 8)),
        fee_bps=float(profile_cfg.get("fee_bps", 8.0)),
        slippage_bps=float(profile_cfg.get("slippage_bps", 5.0)),
        max_single_pos=float(profile_cfg.get("max_single_pos", 0.06)),
        use_regime_position=bool(profile_cfg.get("use_regime_position", False)),
        fallback_total_position=float(profile_cfg.get("fallback_total_position", 0.60)),
        exclude_st=bool(profile_cfg.get("exclude_st", True)),
        min_valid_positions=int(profile_cfg.get("min_valid_positions", 3)),
        max_loss_per_trade=(
            None if profile_cfg.get("max_loss_per_trade", None) is None else float(profile_cfg.get("max_loss_per_trade"))
        ),
        loss_clamp_enabled=bool(profile_cfg.get("promotion_loss_clamp_enabled", False)),
        engine_mode=str(profile_cfg.get("engine_mode", "hybrid")),
        benchmark_mode=str(profile_cfg.get("benchmark_mode", "hs300")),
        benchmark_file=args.benchmark_file,
        exclude_bj9=bool(profile_cfg.get("exclude_bj9", True)),
        max_industry_positions=int(profile_cfg.get("max_industry_positions", 3)),
        corr_lookback_days=int(profile_cfg.get("corr_lookback_days", 60)),
        max_pair_corr=float(profile_cfg.get("max_pair_corr", 0.85)),
        corr_min_obs=int(profile_cfg.get("corr_min_obs", 15)),
        take_profit=float(profile_cfg.get("take_profit", 0.18)),
        stop_loss=float(profile_cfg.get("stop_loss", 0.08)),
        trail_drawdown=float(profile_cfg.get("trail_drawdown", 0.10)),
        tp_normal=float(profile_cfg.get("tp_normal", 0.18)),
        tp_choppy=float(profile_cfg.get("tp_choppy", 0.14)),
        tp_panic=float(profile_cfg.get("tp_panic", 0.10)),
        sl_normal=float(profile_cfg.get("sl_normal", 0.08)),
        sl_choppy=float(profile_cfg.get("sl_choppy", 0.06)),
        sl_panic=float(profile_cfg.get("sl_panic", 0.05)),
        trail_normal=float(profile_cfg.get("trail_normal", 0.10)),
        trail_choppy=float(profile_cfg.get("trail_choppy", 0.08)),
        trail_panic=float(profile_cfg.get("trail_panic", 0.06)),
        corr_normal=float(profile_cfg.get("corr_normal", 0.85)),
        corr_choppy=float(profile_cfg.get("corr_choppy", 0.75)),
        corr_panic=float(profile_cfg.get("corr_panic", 0.65)),
        risk_window=int(profile_cfg.get("risk_window", 5)),
        risk_cut_win_rate=float(profile_cfg.get("risk_cut_win_rate", 0.35)),
        risk_cut_avg_ret=float(profile_cfg.get("risk_cut_avg_ret", -0.005)),
        risk_cut_factor=float(profile_cfg.get("risk_cut_factor", 0.60)),
        min_signal_quality=float(profile_cfg.get("min_signal_quality", 0.40)),
        ml_quality_blend=float(profile_cfg.get("ml_quality_blend", 0.80)),
        max_abs_pct_chg=float(profile_cfg.get("max_abs_pct_chg", 8.5)),
        stability_blend=float(profile_cfg.get("stability_blend", 0.30)),
        min_refactor_score=float(profile_cfg.get("min_refactor_score", 0.50)),
        min_price=float(profile_cfg.get("min_price", 0.0)),
        min_amount_ma20=float(profile_cfg.get("min_amount_ma20", 0.0)),
        liquidity_blend=float(profile_cfg.get("liquidity_blend", 0.0)),
        adv_penalty_blend=float(profile_cfg.get("adv_penalty_blend", 0.0)),
        industry_crowding_blend=float(profile_cfg.get("industry_crowding_blend", 0.0)),
        optimizer_mode=str(profile_cfg.get("optimizer_mode", "score_weight")),
        target_capital_base=float(profile_cfg.get("target_capital_base", 1_000_000.0)),
        target_max_industry_weight=float(
            profile_cfg.get("target_max_industry_weight", profile_cfg.get("risk_max_industry_weight", 0.0))
        ),
        target_max_adv_participation=float(
            profile_cfg.get("target_max_adv_participation", profile_cfg.get("risk_max_adv_participation", 0.0))
        ),
        target_capacity_amount_col=str(profile_cfg.get("target_capacity_amount_col", "amount_ma20")),
        target_capacity_amount_buffer=float(profile_cfg.get("target_capacity_amount_buffer", 1.0)),
        redistribute_clipped_weight=bool(profile_cfg.get("redistribute_clipped_weight", False)),
        impact_model=str(profile_cfg.get("impact_model", "sqrt")),
        impact_base_bps=float(profile_cfg.get("impact_base_bps", 0.0)),
        impact_participation_bps=float(profile_cfg.get("impact_participation_bps", 0.0)),
        impact_power=float(profile_cfg.get("impact_power", 0.5)),
        verbose=bool(args.verbose),
    )


def _run_one_profile(profile_name: str, profile_cfg: dict, args: argparse.Namespace) -> dict[str, float]:
    cfg = _build_cfg(profile_cfg, args)
    _, metrics = backtest_portfolio(cfg)
    row = {
        "profile": profile_name,
        "start": cfg.start or "",
        "end": cfg.end or "",
        "top_n": cfg.top_n,
        "holding_days": cfg.holding_days,
        "use_regime_position": int(cfg.use_regime_position),
        "max_single_pos": cfg.max_single_pos,
        "engine_mode": cfg.engine_mode,
        "benchmark_mode": cfg.benchmark_mode,
    }
    for k in DISPLAY_METRICS:
        row[k] = float(metrics.get(k, 0.0))
    return row


def _add_delta_vs_base(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    base = out.iloc[0]
    for col in DISPLAY_METRICS:
        out[f"delta_{col}"] = pd.to_numeric(out[col], errors="coerce") - float(base[col])
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="按 profile 执行 A/B 回测并导出对比指标")
    p.add_argument("--config", type=str, default=os.path.join(BASE_DIR, "config", "quant_live_profiles.json"), help="配置文件路径")
    p.add_argument("--base-profile", type=str, default=None, help="基准档位，默认读取配置中的 default_profile")
    p.add_argument("--compare-profile", type=str, default=None, help="对照档位，默认自动选择一个非基准档位")
    p.add_argument("--extra-profiles", type=str, default="", help="可选：额外对照档位，逗号分隔")
    p.add_argument("--start", type=str, default=None, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, default=None, help="结束日期 YYYY-MM-DD")
    p.add_argument("--benchmark-file", type=str, default=None, help="可选覆盖基准文件")
    p.add_argument("--verbose", action="store_true", help="打印回测过程明细")
    args = p.parse_args()

    cfg_file = os.path.abspath(args.config)
    if not os.path.exists(cfg_file):
        raise FileNotFoundError(f"未找到配置文件: {cfg_file}")

    root = _load_profiles(cfg_file)
    profiles = root.get("profiles", {})

    base_profile = args.base_profile or str(root.get("default_profile", "balanced"))
    compare_profile = args.compare_profile
    if compare_profile is None:
        compare_profile = "balanced" if base_profile != "balanced" and "balanced" in profiles else next(
            (name for name in profiles.keys() if name != base_profile),
            base_profile,
        )

    names = [base_profile, compare_profile]
    if args.extra_profiles.strip():
        names.extend([x.strip() for x in args.extra_profiles.split(",") if x.strip()])

    ordered_names: list[str] = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        ordered_names.append(name)

    missing = [n for n in ordered_names if n not in profiles]
    if missing:
        raise RuntimeError(f"未知 profile: {', '.join(missing)}; 可选: {', '.join(sorted(profiles.keys()))}")

    print("=" * 72)
    print("量化档位 A/B 对比")
    print("=" * 72)
    print(f"配置文件: {cfg_file}")
    print(f"区间: {args.start or 'auto'} ~ {args.end or 'auto'}")
    print(f"档位: {', '.join(ordered_names)}")

    rows: list[dict[str, float]] = []
    for name in ordered_names:
        print(f"\n[RUN] {name}")
        rows.append(_run_one_profile(name, dict(profiles[name]), args))

    summary_df = pd.DataFrame(rows)
    result_df = _add_delta_vs_base(summary_df)

    dirs = ensure_output_dirs(OUTPUT_DIR)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_new = dirs["backtest"] / f"quant_profile_ab_{timestamp}.csv"
    csv_legacy = Path(OUTPUT_DIR) / f"quant_profile_ab_{timestamp}.csv"
    write_dual_csv(result_df, csv_new, csv_legacy, index=False, encoding="utf-8-sig")

    json_path = dirs["backtest"] / f"quant_profile_ab_{timestamp}.json"
    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": cfg_file,
        "profiles": ordered_names,
        "start": args.start,
        "end": args.end,
        "rows": result_df.to_dict(orient="records"),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "-" * 72)
    display_cols = [
        "profile",
        "holding_days",
        "use_regime_position",
        "annual_return_pct",
        "excess_annual_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "sortino",
        "profit_factor",
        "tail_ratio",
        "ulcer_index_pct",
        "win_rate_pct",
        "beat_rate_pct",
    ]
    print(result_df[display_cols].to_string(index=False))
    print("-" * 72)
    print(f"对比表已保存: {csv_new}")
    print(f"对比JSON已保存: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
