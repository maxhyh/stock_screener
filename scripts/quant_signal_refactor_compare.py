#!/usr/bin/env python3
"""
信号特征重构 A/B 对比回测：
1) Baseline：关闭特征重构
2) Refactor：开启特征重构与门禁
可选 3) Refactor(no_gate)：开启重构但关闭重构门禁
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

from quant_portfolio_backtest import BacktestConfig, DEFAULTS, backtest_portfolio
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
    "win_rate_pct",
    "beat_rate_pct",
    "annual_turnover_pct",
    "avg_exposure_pct",
]


def _build_cfg(args: argparse.Namespace, *, enable_refactor: bool, enable_refactor_gate: bool) -> BacktestConfig:
    return BacktestConfig(
        start=args.start,
        end=args.end,
        top_n=max(1, int(args.top_n)),
        holding_days=max(1, int(args.holding_days)),
        fee_bps=max(0.0, float(args.fee_bps)),
        slippage_bps=max(0.0, float(args.slippage_bps)),
        max_single_pos=min(max(float(args.max_single_pos), 0.0), 1.0),
        use_regime_position=bool(args.use_regime_position),
        fallback_total_position=min(max(float(args.fallback_total_pos), 0.0), 1.0),
        engine_mode=str(args.engine_mode),
        benchmark_mode=str(args.benchmark_mode),
        benchmark_file=args.benchmark_file,
        enable_signal_quality_gate=not args.disable_signal_quality_gate,
        min_signal_quality=min(max(float(args.min_signal_quality), 0.0), 1.0),
        ml_quality_blend=min(max(float(args.ml_quality_blend), 0.0), 1.0),
        max_abs_pct_chg=max(1.0, float(args.max_abs_pct_chg)),
        enable_feature_refactor=bool(enable_refactor),
        stability_blend=min(max(float(args.stability_blend), 0.0), 1.0),
        enable_feature_refactor_gate=bool(enable_refactor_gate),
        min_refactor_score=min(max(float(args.min_refactor_score), 0.0), 1.0),
        verbose=bool(args.verbose),
    )


def _run_variant(name: str, cfg: BacktestConfig) -> dict[str, float]:
    _, metrics = backtest_portfolio(cfg)
    row: dict[str, float] = {
        "variant": name,
        "start": cfg.start or "",
        "end": cfg.end or "",
        "top_n": cfg.top_n,
        "holding_days": cfg.holding_days,
        "engine_mode": cfg.engine_mode,
        "benchmark_mode": cfg.benchmark_mode,
        "enable_feature_refactor": int(cfg.enable_feature_refactor),
        "enable_feature_refactor_gate": int(cfg.enable_feature_refactor_gate),
        "stability_blend": float(cfg.stability_blend),
        "min_refactor_score": float(cfg.min_refactor_score),
    }
    for k in DISPLAY_METRICS:
        row[k] = float(metrics.get(k, 0.0))
    return row


def _add_delta_vs_base(df: pd.DataFrame, base_variant: str) -> pd.DataFrame:
    out = df.copy()
    if out.empty or base_variant not in set(out["variant"].astype(str)):
        return out
    base = out[out["variant"] == base_variant].iloc[0]
    for col in DISPLAY_METRICS:
        out[f"delta_{col}"] = pd.to_numeric(out[col], errors="coerce") - float(base[col])
    return out


def _pick_best_variant(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    rank_df = df.copy()
    rank_df["key_excess"] = pd.to_numeric(rank_df["excess_annual_return_pct"], errors="coerce").fillna(-1e9)
    rank_df["key_sharpe"] = pd.to_numeric(rank_df["sharpe"], errors="coerce").fillna(-1e9)
    rank_df["key_mdd"] = pd.to_numeric(rank_df["max_drawdown_pct"], errors="coerce").fillna(-1e9)
    rank_df = rank_df.sort_values(["key_excess", "key_sharpe", "key_mdd"], ascending=[False, False, False])
    return str(rank_df.iloc[0]["variant"])


def _write_markdown(md_path: Path, result_df: pd.DataFrame, base_variant: str, args: argparse.Namespace) -> None:
    best = _pick_best_variant(result_df)
    lines = [
        "# Signal Refactor A/B 对比报告",
        "",
        f"- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 区间: {args.start} ~ {args.end}",
        f"- 基准组: {base_variant}",
        f"- 引擎: {args.engine_mode} | 基准: {args.benchmark_mode}",
        f"- 最优组(按超额年化->夏普->回撤): {best or 'N/A'}",
        "",
        "## 参数",
        "",
        f"- top_n={int(args.top_n)}, holding_days={int(args.holding_days)}, max_single_pos={float(args.max_single_pos):.2f}",
        f"- signal_gate={not args.disable_signal_quality_gate}, min_signal_quality={float(args.min_signal_quality):.2f}",
        f"- refactor: blend={float(args.stability_blend):.2f}, floor={float(args.min_refactor_score):.2f}",
        "",
        "## 指标对比",
        "",
    ]
    show_cols = [
        "variant",
        "annual_return_pct",
        "excess_annual_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "win_rate_pct",
        "beat_rate_pct",
    ]
    if not result_df.empty:
        lines.append(result_df[show_cols].to_markdown(index=False))
    else:
        lines.append("无结果。")
    lines.extend(
        [
            "",
            "## 结论建议",
            "",
            f"- 建议优先使用 `{best or base_variant}` 作为下一轮优化起点，并在Walk-Forward中验证稳定性。",
            "- 若 refactor 组提升收益但回撤明显放大，应先降低 `stability_blend` 或提高 `min_refactor_score`。",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="信号特征重构 A/B 对比回测")
    p.add_argument("--start", type=str, required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, required=True, help="结束日期 YYYY-MM-DD")
    p.add_argument("--top-n", type=int, default=int(DEFAULTS["top_n"]), help="每日持仓数")
    p.add_argument("--holding-days", type=int, default=int(DEFAULTS["holding_days"]), help="持有天数")
    p.add_argument("--fee-bps", type=float, default=8.0, help="双边手续费(bps)")
    p.add_argument("--slippage-bps", type=float, default=5.0, help="双边滑点(bps)")
    p.add_argument("--max-single-pos", type=float, default=float(DEFAULTS["max_single_pos"]), help="单票上限(0~1)")
    p.add_argument("--use-regime-position", action="store_true", help="使用市场状态建议仓位")
    p.add_argument("--fallback-total-pos", type=float, default=float(DEFAULTS["fallback_total_position"]), help="固定总仓(0~1)")
    p.add_argument("--engine-mode", type=str, default=str(DEFAULTS["engine_mode"]), choices=["left", "right", "hybrid"], help="交易引擎模式")
    p.add_argument("--benchmark-mode", type=str, default=str(DEFAULTS["benchmark_mode"]), choices=["hs300", "synthetic", "none"], help="基准模式")
    p.add_argument("--benchmark-file", type=str, default=None, help="基准CSV文件（包含 date/trade_date 与 open/close）")
    p.add_argument("--disable-signal-quality-gate", action="store_true", help="关闭信号质量门禁")
    p.add_argument("--min-signal-quality", type=float, default=0.35, help="信号质量最低阈值(0~1)")
    p.add_argument("--ml-quality-blend", type=float, default=0.85, help="综合分中ML排序权重(0~1)")
    p.add_argument("--max-abs-pct-chg", type=float, default=9.0, help="信号质量中涨跌幅惩罚阈值(%%)")
    p.add_argument("--stability-blend", type=float, default=0.20, help="重构分中稳定性权重(0~1)")
    p.add_argument("--min-refactor-score", type=float, default=0.45, help="重构分最低阈值(0~1)")
    p.add_argument("--include-no-gate", action="store_true", help="额外输出 refactor 但不启用重构门禁组")
    p.add_argument("--verbose", action="store_true", help="打印回测过程明细")
    args = p.parse_args()

    variants = [
        (
            "baseline",
            _build_cfg(args, enable_refactor=False, enable_refactor_gate=False),
        ),
        (
            "refactor",
            _build_cfg(args, enable_refactor=True, enable_refactor_gate=True),
        ),
    ]
    if args.include_no_gate:
        variants.append(
            (
                "refactor_no_gate",
                _build_cfg(args, enable_refactor=True, enable_refactor_gate=False),
            )
        )

    print("=" * 72)
    print("Signal Refactor A/B 回测")
    print("=" * 72)
    print(f"区间: {args.start} ~ {args.end}")
    print(f"组合: {', '.join(name for name, _ in variants)}")

    rows: list[dict[str, float]] = []
    for name, cfg in variants:
        print(f"\n[RUN] {name}")
        rows.append(_run_variant(name, cfg))
    result_df = _add_delta_vs_base(pd.DataFrame(rows), base_variant="baseline")

    dirs = ensure_output_dirs(OUTPUT_DIR)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_new = dirs["backtest"] / f"quant_signal_refactor_compare_{ts}.csv"
    csv_legacy = Path(OUTPUT_DIR) / f"quant_signal_refactor_compare_{ts}.csv"
    write_dual_csv(result_df, csv_new, csv_legacy, index=False, encoding="utf-8-sig")

    json_path = dirs["backtest"] / f"quant_signal_refactor_compare_{ts}.json"
    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start": args.start,
        "end": args.end,
        "variants": [name for name, _ in variants],
        "rows": result_df.to_dict(orient="records"),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = dirs["backtest"] / f"quant_signal_refactor_compare_{ts}.md"
    _write_markdown(md_path, result_df, base_variant="baseline", args=args)

    view_cols = [
        "variant",
        "annual_return_pct",
        "excess_annual_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "win_rate_pct",
    ]
    print("\n" + "-" * 72)
    print(result_df[view_cols].to_string(index=False))
    print("-" * 72)
    print(f"对比CSV已保存: {csv_new}")
    print(f"对比JSON已保存: {json_path}")
    print(f"对比Markdown已保存: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
