#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
围绕 quality_regime 候选参数做交易成本压力测试。

目标：
1) 固定一组主推荐参数
2) 细扫 fee_bps / slippage_bps
3) 输出收益/质量退化幅度，衡量策略对交易成本的敏感性
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from itertools import product
from pathlib import Path

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from quant_portfolio_backtest import BacktestConfig, backtest_portfolio
from utils.output_paths import ensure_output_dirs, write_dual_csv

OUTPUT_DIR = Path(BASE_DIR) / "output"
PROFILE_FILE = Path(BASE_DIR) / "config" / "quant_live_profiles.json"


def _parse_int_grid(text: str) -> list[int]:
    vals = [int(x.strip()) for x in str(text).split(",") if x.strip()]
    return sorted(set(vals))


def _parse_float_grid(text: str) -> list[float]:
    vals = [float(x.strip()) for x in str(text).split(",") if x.strip()]
    return sorted(set(vals))


def _load_profile(profile_name: str, config_file: Path) -> dict[str, object]:
    root = json.loads(config_file.read_text(encoding="utf-8"))
    profiles = root.get("profiles", {})
    if not isinstance(profiles, dict) or profile_name not in profiles:
        raise RuntimeError(f"未知 profile: {profile_name}")
    cfg = profiles.get(profile_name, {})
    return dict(cfg) if isinstance(cfg, dict) else {}


def _build_cfg(
    *,
    start: str,
    end: str,
    profile_cfg: dict[str, object],
    benchmark_file: str | None,
    fee_bps: float,
    slippage_bps: float,
    top_n: int | None,
    min_signal_quality: float | None,
    ml_quality_blend: float | None,
    min_refactor_score: float | None,
    risk_window: int | None,
    risk_cut_factor: float | None,
) -> BacktestConfig:
    return BacktestConfig(
        start=start,
        end=end,
        top_n=int(top_n if top_n is not None else profile_cfg.get("top_n", 13)),
        holding_days=int(profile_cfg.get("holding_days", 8)),
        fee_bps=float(fee_bps),
        slippage_bps=float(slippage_bps),
        max_single_pos=float(profile_cfg.get("max_single_pos", 0.04)),
        use_regime_position=bool(profile_cfg.get("use_regime_position", True)),
        fallback_total_position=float(profile_cfg.get("fallback_total_position", 0.60)),
        exclude_st=bool(profile_cfg.get("exclude_st", True)),
        min_valid_positions=int(profile_cfg.get("min_valid_positions", 4)),
        max_loss_per_trade=(
            None
            if profile_cfg.get("max_loss_per_trade", None) is None
            else float(profile_cfg.get("max_loss_per_trade"))
        ),
        engine_mode=str(profile_cfg.get("engine_mode", "hybrid")),
        benchmark_mode=str(profile_cfg.get("benchmark_mode", "hs300")),
        benchmark_file=benchmark_file,
        exclude_bj9=bool(profile_cfg.get("exclude_bj9", True)),
        enable_diversification=True,
        max_industry_positions=int(profile_cfg.get("max_industry_positions", 3)),
        corr_lookback_days=int(profile_cfg.get("corr_lookback_days", 60)),
        max_pair_corr=float(profile_cfg.get("max_pair_corr", 0.85)),
        corr_min_obs=int(profile_cfg.get("corr_min_obs", 15)),
        enable_dynamic_exit=True,
        take_profit=float(profile_cfg.get("take_profit", 0.18)),
        stop_loss=float(profile_cfg.get("stop_loss", 0.08)),
        trail_drawdown=float(profile_cfg.get("trail_drawdown", 0.10)),
        enable_regime_risk_params=True,
        tp_normal=float(profile_cfg.get("tp_normal", 0.18)),
        tp_choppy=float(profile_cfg.get("tp_choppy", 0.14)),
        tp_panic=float(profile_cfg.get("tp_panic", 0.08)),
        sl_normal=float(profile_cfg.get("sl_normal", 0.08)),
        sl_choppy=float(profile_cfg.get("sl_choppy", 0.06)),
        sl_panic=float(profile_cfg.get("sl_panic", 0.04)),
        trail_normal=float(profile_cfg.get("trail_normal", 0.10)),
        trail_choppy=float(profile_cfg.get("trail_choppy", 0.08)),
        trail_panic=float(profile_cfg.get("trail_panic", 0.05)),
        corr_normal=float(profile_cfg.get("corr_normal", 0.85)),
        corr_choppy=float(profile_cfg.get("corr_choppy", 0.75)),
        corr_panic=float(profile_cfg.get("corr_panic", 0.60)),
        enable_risk_switch=True,
        risk_window=int(risk_window if risk_window is not None else profile_cfg.get("risk_window", 8)),
        risk_cut_win_rate=float(profile_cfg.get("risk_cut_win_rate", 0.35)),
        risk_cut_avg_ret=float(profile_cfg.get("risk_cut_avg_ret", -0.005)),
        risk_cut_factor=float(risk_cut_factor if risk_cut_factor is not None else profile_cfg.get("risk_cut_factor", 0.75)),
        enable_signal_quality_gate=True,
        min_signal_quality=float(
            min_signal_quality if min_signal_quality is not None else profile_cfg.get("min_signal_quality", 0.48)
        ),
        ml_quality_blend=float(
            ml_quality_blend if ml_quality_blend is not None else profile_cfg.get("ml_quality_blend", 0.78)
        ),
        max_abs_pct_chg=float(profile_cfg.get("max_abs_pct_chg", 8.5)),
        enable_feature_refactor=True,
        stability_blend=float(profile_cfg.get("stability_blend", 0.30)),
        enable_feature_refactor_gate=True,
        min_refactor_score=float(
            min_refactor_score if min_refactor_score is not None else profile_cfg.get("min_refactor_score", 0.56)
        ),
        verbose=False,
    )


def _calc_decay(df: pd.DataFrame, baseline_row: dict[str, float]) -> pd.DataFrame:
    out = df.copy()
    out["delta_annual_return_pct"] = pd.to_numeric(out["annual_return_pct"], errors="coerce") - float(
        baseline_row.get("annual_return_pct", 0.0)
    )
    out["delta_excess_annual_return_pct"] = pd.to_numeric(out["excess_annual_return_pct"], errors="coerce") - float(
        baseline_row.get("excess_annual_return_pct", 0.0)
    )
    out["delta_sharpe"] = pd.to_numeric(out["sharpe"], errors="coerce") - float(baseline_row.get("sharpe", 0.0))
    out["delta_sortino"] = pd.to_numeric(out["sortino"], errors="coerce") - float(baseline_row.get("sortino", 0.0))
    out["delta_profit_factor"] = pd.to_numeric(out["profit_factor"], errors="coerce") - float(
        baseline_row.get("profit_factor", 0.0)
    )
    out["delta_tail_ratio"] = pd.to_numeric(out["tail_ratio"], errors="coerce") - float(
        baseline_row.get("tail_ratio", 0.0)
    )
    out["improvement_max_drawdown_pct"] = float(baseline_row.get("max_drawdown_pct", 0.0)) - pd.to_numeric(
        out["max_drawdown_pct"], errors="coerce"
    )
    out["improvement_ulcer_index_pct"] = float(baseline_row.get("ulcer_index_pct", 0.0)) - pd.to_numeric(
        out["ulcer_index_pct"], errors="coerce"
    )
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="quality_regime 交易成本压力测试")
    p.add_argument("--start", type=str, required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, required=True, help="结束日期 YYYY-MM-DD")
    p.add_argument("--profile", type=str, default="quality_regime", help="基准 profile")
    p.add_argument("--config", type=str, default=str(PROFILE_FILE), help="profile 配置文件")
    p.add_argument("--benchmark-file", type=str, default=None)
    p.add_argument("--top-n", type=int, default=None)
    p.add_argument("--min-signal-quality", type=float, default=None)
    p.add_argument("--ml-quality-blend", type=float, default=None)
    p.add_argument("--min-refactor-score", type=float, default=None)
    p.add_argument("--risk-window", type=int, default=None)
    p.add_argument("--risk-cut-factor", type=float, default=None)
    p.add_argument("--fee-grid", type=str, default="8,10,12,15", help="手续费 bps 网格")
    p.add_argument("--slippage-grid", type=str, default="5,7,10,12", help="滑点 bps 网格")
    args = p.parse_args()

    config_file = Path(args.config)
    if not config_file.exists():
        raise FileNotFoundError(f"未找到配置文件: {config_file}")

    profile_cfg = _load_profile(str(args.profile), config_file)
    fee_grid = _parse_float_grid(args.fee_grid)
    slippage_grid = _parse_float_grid(args.slippage_grid)
    if not fee_grid or not slippage_grid:
        raise RuntimeError("fee/slippage 网格不能为空")

    baseline_cfg = _build_cfg(
        start=args.start,
        end=args.end,
        profile_cfg=profile_cfg,
        benchmark_file=args.benchmark_file,
        fee_bps=float(profile_cfg.get("fee_bps", 8.0)),
        slippage_bps=float(profile_cfg.get("slippage_bps", 5.0)),
        top_n=args.top_n,
        min_signal_quality=args.min_signal_quality,
        ml_quality_blend=args.ml_quality_blend,
        min_refactor_score=args.min_refactor_score,
        risk_window=args.risk_window,
        risk_cut_factor=args.risk_cut_factor,
    )
    _, baseline_metrics = backtest_portfolio(baseline_cfg)

    rows: list[dict[str, object]] = []
    for fee_bps, slippage_bps in product(fee_grid, slippage_grid):
        cfg = _build_cfg(
            start=args.start,
            end=args.end,
            profile_cfg=profile_cfg,
            benchmark_file=args.benchmark_file,
            fee_bps=float(fee_bps),
            slippage_bps=float(slippage_bps),
            top_n=args.top_n,
            min_signal_quality=args.min_signal_quality,
            ml_quality_blend=args.ml_quality_blend,
            min_refactor_score=args.min_refactor_score,
            risk_window=args.risk_window,
            risk_cut_factor=args.risk_cut_factor,
        )
        _, metrics = backtest_portfolio(cfg)
        row = {
            "profile": args.profile,
            "top_n": int(cfg.top_n),
            "holding_days": int(cfg.holding_days),
            "min_signal_quality": float(cfg.min_signal_quality),
            "ml_quality_blend": float(cfg.ml_quality_blend),
            "min_refactor_score": float(cfg.min_refactor_score),
            "risk_window": int(cfg.risk_window),
            "risk_cut_factor": float(cfg.risk_cut_factor),
            "fee_bps": float(fee_bps),
            "slippage_bps": float(slippage_bps),
            "total_cost_bps": float(fee_bps + slippage_bps),
        }
        row.update(metrics)
        rows.append(row)

    stress_df = pd.DataFrame(rows)
    if stress_df.empty:
        raise RuntimeError("压力测试结果为空")
    stress_df = _calc_decay(stress_df, baseline_metrics)
    stress_df = stress_df.sort_values(
        ["annual_return_pct", "sortino", "sharpe", "profit_factor"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    dirs = ensure_output_dirs(str(OUTPUT_DIR))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_new = dirs["backtest"] / f"quality_regime_cost_stress_{ts}.csv"
    csv_legacy = OUTPUT_DIR / f"quality_regime_cost_stress_{ts}.csv"
    write_dual_csv(stress_df, csv_new, csv_legacy, index=False, encoding="utf-8-sig")

    summary = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profile": args.profile,
        "start": args.start,
        "end": args.end,
        "baseline": {
            "fee_bps": baseline_cfg.fee_bps,
            "slippage_bps": baseline_cfg.slippage_bps,
            "top_n": baseline_cfg.top_n,
            "min_signal_quality": baseline_cfg.min_signal_quality,
            "ml_quality_blend": baseline_cfg.ml_quality_blend,
            "min_refactor_score": baseline_cfg.min_refactor_score,
            "risk_window": baseline_cfg.risk_window,
            "risk_cut_factor": baseline_cfg.risk_cut_factor,
            "metrics": baseline_metrics,
        },
        "best_row": stress_df.iloc[0].to_dict(),
        "worst_row": stress_df.sort_values(
            ["annual_return_pct", "sortino", "sharpe"],
            ascending=[True, True, True],
        ).iloc[0].to_dict(),
        "csv_file": str(csv_new),
    }
    json_path = dirs["backtest"] / f"quality_regime_cost_stress_{ts}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("quality_regime 成本压力测试")
    print("=" * 72)
    print(
        f"profile={args.profile} | period={args.start}~{args.end} | "
        f"TopN={baseline_cfg.top_n} | Q={baseline_cfg.min_signal_quality:.2f} "
        f"| ML={baseline_cfg.ml_quality_blend:.2f} | Ref={baseline_cfg.min_refactor_score:.2f}"
    )
    print(
        f"baseline cost={baseline_cfg.fee_bps + baseline_cfg.slippage_bps:.1f}bps | "
        f"年化={float(baseline_metrics.get('annual_return_pct', 0.0)):.2f}% "
        f"超额={float(baseline_metrics.get('excess_annual_return_pct', 0.0)):.2f}% "
        f"Sharpe={float(baseline_metrics.get('sharpe', 0.0)):.3f} "
        f"Sortino={float(baseline_metrics.get('sortino', 0.0)):.3f}"
    )
    print("\nTop Stress Rows")
    print(
        stress_df[
            [
                "fee_bps",
                "slippage_bps",
                "total_cost_bps",
                "annual_return_pct",
                "excess_annual_return_pct",
                "sharpe",
                "sortino",
                "profit_factor",
                "tail_ratio",
                "delta_annual_return_pct",
                "delta_sharpe",
            ]
        ].head(8).to_string(index=False)
    )
    print("\nWorst Stress Rows")
    print(
        stress_df.sort_values(
            ["annual_return_pct", "sortino", "sharpe"],
            ascending=[True, True, True],
        )[
            [
                "fee_bps",
                "slippage_bps",
                "total_cost_bps",
                "annual_return_pct",
                "excess_annual_return_pct",
                "sharpe",
                "sortino",
                "profit_factor",
                "tail_ratio",
                "delta_annual_return_pct",
                "delta_sharpe",
            ]
        ].head(5).to_string(index=False)
    )
    print(f"\nCSV: {csv_new}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
