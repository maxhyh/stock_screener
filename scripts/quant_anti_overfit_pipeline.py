#!/usr/bin/env python3
"""
反过拟合优化流水线（A股）：
1) Walk-Forward 粗网格，寻找跨窗口稳定参数区
2) 基于稳定参数区收窄网格
3) 运行 robust-mode 参数优化
4) 输出结构化报告与下一步执行命令
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_BACKTEST_DIR = Path(BASE_DIR) / "output" / "backtest"


def _parse_int_grid(text: str) -> list[int]:
    vals = [int(x.strip()) for x in str(text).split(",") if x.strip()]
    return sorted(set(vals))


def _parse_float_grid(text: str) -> list[float]:
    vals = [float(x.strip()) for x in str(text).split(",") if x.strip()]
    return sorted(set(vals))


def _format_int_grid(vals: list[int]) -> str:
    return ",".join(str(int(x)) for x in sorted(set(vals)))


def _format_float_grid(vals: list[float]) -> str:
    return ",".join(f"{float(x):.2f}" for x in sorted(set(vals)))


def _latest_file(pattern: str) -> Path | None:
    files = sorted(glob.glob(pattern))
    return Path(files[-1]) if files else None


def _run_cmd(cmd: list[str]) -> None:
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=BASE_DIR, check=True)


def _append_signal_refactor_flags(cmd: list[str], args: argparse.Namespace) -> list[str]:
    out = list(cmd)
    if bool(args.disable_signal_quality_gate):
        out.append("--disable-signal-quality-gate")
    out.extend(
        [
            "--min-signal-quality",
            f"{min(max(float(args.min_signal_quality), 0.0), 1.0):.4f}",
            "--ml-quality-blend",
            f"{min(max(float(args.ml_quality_blend), 0.0), 1.0):.4f}",
            "--max-abs-pct-chg",
            f"{max(1.0, float(args.max_abs_pct_chg)):.4f}",
        ]
    )
    if bool(args.disable_feature_refactor):
        out.append("--disable-feature-refactor")
    out.extend(
        [
            "--stability-blend",
            f"{min(max(float(args.stability_blend), 0.0), 1.0):.4f}",
        ]
    )
    if bool(args.disable_feature_refactor_gate):
        out.append("--disable-feature-refactor-gate")
    out.extend(
        [
            "--min-refactor-score",
            f"{min(max(float(args.min_refactor_score), 0.0), 1.0):.4f}",
        ]
    )
    return out


def _build_stable_table(
    wf_df: pd.DataFrame,
    *,
    min_windows: int,
    min_good_ratio: float,
    min_test_excess_annual: float,
    max_test_mdd: float,
) -> pd.DataFrame:
    if wf_df.empty:
        return pd.DataFrame()

    work = wf_df.copy()
    work["good"] = (
        (pd.to_numeric(work["test_excess_annual_return_pct"], errors="coerce") >= float(min_test_excess_annual))
        & (pd.to_numeric(work["test_mdd_pct"], errors="coerce") >= float(max_test_mdd))
    ).astype(int)

    group_cols = ["top_n", "holding_days", "max_single_pos", "use_regime_position"]
    agg = (
        work.groupby(group_cols, as_index=False)
        .agg(
            windows=("window_id", "count"),
            good_windows=("good", "sum"),
            med_test_excess_annual=("test_excess_annual_return_pct", "median"),
            med_test_annual=("test_annual_return_pct", "median"),
            med_test_mdd=("test_mdd_pct", "median"),
            mean_test_sharpe=("test_sharpe", "mean"),
            mean_test_beat_rate=("test_beat_rate_pct", "mean"),
        )
    )
    agg["good_ratio"] = agg["good_windows"] / agg["windows"].clip(lower=1)
    stable = agg[
        (agg["windows"] >= int(min_windows))
        & (agg["good_ratio"] >= float(min_good_ratio))
    ].copy()
    if stable.empty:
        return stable
    stable = stable.sort_values(
        ["good_ratio", "med_test_excess_annual", "mean_test_sharpe", "med_test_mdd"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    return stable


def _derive_narrow_grid(
    stable_df: pd.DataFrame,
    *,
    fallback_topn: list[int],
    fallback_hold: list[int],
    fallback_maxpos: list[float],
    top_k: int,
) -> dict[str, list]:
    if stable_df.empty:
        return {
            "topn_grid": sorted(set(fallback_topn)),
            "hold_grid": sorted(set(fallback_hold)),
            "maxpos_grid": sorted(set(fallback_maxpos)),
            "regime_grid": [True, False],
            "used_fallback": True,
        }

    top = stable_df.head(max(1, int(top_k))).copy()
    topn_grid = sorted(set(int(x) for x in top["top_n"].tolist()))
    hold_grid = sorted(set(int(x) for x in top["holding_days"].tolist()))
    maxpos_grid = sorted(set(float(x) for x in top["max_single_pos"].tolist()))
    regime_grid = sorted(set(bool(int(x)) for x in top["use_regime_position"].tolist()))
    if not regime_grid:
        regime_grid = [True, False]
    return {
        "topn_grid": topn_grid,
        "hold_grid": hold_grid,
        "maxpos_grid": maxpos_grid,
        "regime_grid": regime_grid,
        "used_fallback": False,
    }


def _latest_daily_date_str() -> str | None:
    files = sorted(glob.glob(str(Path(BASE_DIR) / "output" / "daily" / "daily_*.csv")))
    if not files:
        return None
    name = Path(files[-1]).name
    return name.replace("daily_", "").replace(".csv", "")


def _write_report(
    report: dict[str, object],
    *,
    report_json: Path,
    report_md: Path,
) -> None:
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 反过拟合优化报告",
        "",
        f"- 时间: {report.get('created_at', '')}",
        f"- Walk-Forward 文件: {report.get('walk_forward_file', '')}",
        f"- 推荐参数文件: {report.get('recommendation_file', '')}",
        "",
        "## 稳定参数区（Top）",
    ]
    stable_top = report.get("stable_top", [])
    if stable_top:
        lines.append("")
        lines.append("|top_n|holding_days|max_single_pos|use_regime_position|windows|good_ratio|med_test_excess_annual|med_test_mdd|")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in stable_top:
            lines.append(
                "|{top_n}|{holding_days}|{max_single_pos:.2f}|{use_regime_position}|{windows}|{good_ratio:.2f}|{med_test_excess_annual:.2f}|{med_test_mdd:.2f}|".format(
                    **r
                )
            )
    else:
        lines.append("")
        lines.append("- 未找到满足稳定条件的参数组，已回退到预设网格。")

    lines.extend(
        [
            "",
            "## 收窄后优化网格",
            "",
            f"- top_n: {report.get('narrow_topn_grid', '')}",
            f"- holding_days: {report.get('narrow_hold_grid', '')}",
            f"- max_single_pos: {report.get('narrow_maxpos_grid', '')}",
            "",
            "## 信号稳健参数",
            "",
            f"- signal_quality_gate: {report.get('signal_quality_gate', True)}",
            f"- min_signal_quality: {report.get('min_signal_quality', 0.35)}",
            f"- ml_quality_blend: {report.get('ml_quality_blend', 0.85)}",
            f"- max_abs_pct_chg: {report.get('max_abs_pct_chg', 9.0)}",
            f"- feature_refactor: {report.get('feature_refactor', True)}",
            f"- stability_blend: {report.get('stability_blend', 0.20)}",
            f"- feature_refactor_gate: {report.get('feature_refactor_gate', True)}",
            f"- min_refactor_score: {report.get('min_refactor_score', 0.45)}",
            "",
            "## 下一步命令",
            "",
            f"- 优化命令: `{report.get('optimize_command', '')}`",
            f"- 模拟命令: `{report.get('paper_command', '')}`",
        ]
    )
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="反过拟合优化流水线")
    p.add_argument("--start", type=str, required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, required=True, help="结束日期 YYYY-MM-DD")
    p.add_argument("--wf-train-months", type=int, default=6, help="Walk-Forward 训练窗（月）")
    p.add_argument("--wf-test-months", type=int, default=2, help="Walk-Forward 测试窗（月）")
    p.add_argument("--wf-step-months", type=int, default=2, help="Walk-Forward 步长（月）")
    p.add_argument("--wf-topn-grid", type=str, default="8,10,12,15,18", help="Walk-Forward TopN 网格")
    p.add_argument("--wf-hold-grid", type=str, default="4,5,6,8", help="Walk-Forward 持有天数网格")
    p.add_argument("--wf-maxpos-grid", type=str, default="0.04,0.05,0.06", help="Walk-Forward 单票上限网格")
    p.add_argument("--stable-min-windows", type=int, default=2, help="稳定组合最少窗口数")
    p.add_argument("--stable-min-good-ratio", type=float, default=0.50, help="稳定组合最小通过率")
    p.add_argument("--stable-min-test-excess-annual", type=float, default=0.0, help="稳定组合最小窗口超额年化")
    p.add_argument("--stable-max-test-mdd", type=float, default=-18.0, help="稳定组合窗口回撤下限(%%)")
    p.add_argument("--stable-top-k", type=int, default=6, help="用于收窄网格的稳定组合数")
    p.add_argument("--engine-mode", type=str, default="hybrid", choices=["left", "right", "hybrid"], help="交易引擎模式")
    p.add_argument("--benchmark-mode", type=str, default="hs300", choices=["hs300", "synthetic", "none"], help="基准模式")
    p.add_argument("--disable-signal-quality-gate", action="store_true", help="关闭信号质量门禁（默认开启）")
    p.add_argument("--min-signal-quality", type=float, default=0.35, help="信号质量最低阈值(0~1)")
    p.add_argument("--ml-quality-blend", type=float, default=0.85, help="综合分中ML排序权重(0~1)")
    p.add_argument("--max-abs-pct-chg", type=float, default=9.0, help="信号质量中日涨跌幅惩罚阈值(%%)")
    p.add_argument("--disable-feature-refactor", action="store_true", help="关闭特征重构评分（默认开启）")
    p.add_argument("--stability-blend", type=float, default=0.20, help="重构分中稳定性权重(0~1)")
    p.add_argument("--disable-feature-refactor-gate", action="store_true", help="关闭重构分门禁（默认开启）")
    p.add_argument("--min-refactor-score", type=float, default=0.45, help="重构分最低阈值(0~1)")
    p.add_argument("--skip-wf", action="store_true", help="跳过 Walk-Forward，直接读取最近窗口文件")
    p.add_argument("--skip-opt", action="store_true", help="跳过收窄网格优化")
    args = p.parse_args()

    wf_topn_grid = _parse_int_grid(args.wf_topn_grid)
    wf_hold_grid = _parse_int_grid(args.wf_hold_grid)
    wf_maxpos_grid = _parse_float_grid(args.wf_maxpos_grid)
    if not wf_topn_grid or not wf_hold_grid or not wf_maxpos_grid:
        raise RuntimeError("Walk-Forward 网格不能为空")

    if not args.skip_wf:
        wf_cmd = [
            sys.executable,
            "scripts/quant_walk_forward.py",
            "--start",
            args.start,
            "--end",
            args.end,
            "--train-months",
            str(max(1, int(args.wf_train_months))),
            "--test-months",
            str(max(1, int(args.wf_test_months))),
            "--step-months",
            str(max(1, int(args.wf_step_months))),
            "--topn-grid",
            _format_int_grid(wf_topn_grid),
            "--hold-grid",
            _format_int_grid(wf_hold_grid),
            "--maxpos-grid",
            _format_float_grid(wf_maxpos_grid),
            "--engine-mode",
            str(args.engine_mode),
            "--benchmark-mode",
            str(args.benchmark_mode),
        ]
        wf_cmd = _append_signal_refactor_flags(wf_cmd, args)
        _run_cmd(wf_cmd)

    wf_file = _latest_file(str(OUTPUT_BACKTEST_DIR / "quant_walk_forward_windows_*.csv"))
    if wf_file is None or not wf_file.exists():
        raise RuntimeError("未找到 Walk-Forward 窗口结果文件")
    wf_df = pd.read_csv(wf_file)
    stable_df = _build_stable_table(
        wf_df,
        min_windows=max(1, int(args.stable_min_windows)),
        min_good_ratio=min(max(float(args.stable_min_good_ratio), 0.0), 1.0),
        min_test_excess_annual=float(args.stable_min_test_excess_annual),
        max_test_mdd=float(args.stable_max_test_mdd),
    )
    narrow = _derive_narrow_grid(
        stable_df,
        fallback_topn=wf_topn_grid,
        fallback_hold=wf_hold_grid,
        fallback_maxpos=wf_maxpos_grid,
        top_k=max(1, int(args.stable_top_k)),
    )

    opt_cmd: list[str] = []
    if not args.skip_opt:
        opt_cmd = [
            sys.executable,
            "scripts/quant_optimize.py",
            "--start",
            args.start,
            "--end",
            args.end,
            "--topn-grid",
            _format_int_grid(narrow["topn_grid"]),
            "--hold-grid",
            _format_int_grid(narrow["hold_grid"]),
            "--maxpos-grid",
            _format_float_grid(narrow["maxpos_grid"]),
            "--engine-mode",
            str(args.engine_mode),
            "--benchmark-mode",
            str(args.benchmark_mode),
            "--robust-mode",
            "on",
            "--min-annual-return-pct",
            "0",
            "--min-excess-annual-pct",
            "0",
            "--min-sharpe",
            "0",
            "--max-drawdown-limit-pct",
            "-15",
            "--turnover-cap-pct",
            "4500",
            "--recommend-top-k",
            "10",
        ]
        opt_cmd = _append_signal_refactor_flags(opt_cmd, args)
        _run_cmd(opt_cmd)

    rec_file = OUTPUT_BACKTEST_DIR / "quant_strategy_paper_recommendations.csv"
    rec_row = {}
    if rec_file.exists():
        try:
            rec_df = pd.read_csv(rec_file)
            if not rec_df.empty:
                rec_row = rec_df.iloc[0].to_dict()
        except Exception:
            rec_row = {}

    latest_daily = _latest_daily_date_str() or ""
    paper_cmd = ""
    if latest_daily:
        paper_cmd = (
            f"python scripts/quant_p2_paper_trade.py --date {latest_daily} "
            f"--broker paper --use-recommendation --recommend-rank 1 --dry-run --write-latest"
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_json = OUTPUT_BACKTEST_DIR / f"quant_anti_overfit_report_{ts}.json"
    report_md = OUTPUT_BACKTEST_DIR / f"quant_anti_overfit_report_{ts}.md"
    stable_top = stable_df.head(10).to_dict(orient="records") if not stable_df.empty else []
    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start": args.start,
        "end": args.end,
        "walk_forward_file": str(wf_file),
        "stable_count": int(len(stable_df)),
        "stable_top": stable_top,
        "narrow_topn_grid": _format_int_grid(narrow["topn_grid"]),
        "narrow_hold_grid": _format_int_grid(narrow["hold_grid"]),
        "narrow_maxpos_grid": _format_float_grid(narrow["maxpos_grid"]),
        "narrow_regime_grid": ",".join("1" if x else "0" for x in narrow["regime_grid"]),
        "used_fallback_grid": bool(narrow["used_fallback"]),
        "signal_quality_gate": bool(not args.disable_signal_quality_gate),
        "min_signal_quality": min(max(float(args.min_signal_quality), 0.0), 1.0),
        "ml_quality_blend": min(max(float(args.ml_quality_blend), 0.0), 1.0),
        "max_abs_pct_chg": max(1.0, float(args.max_abs_pct_chg)),
        "feature_refactor": bool(not args.disable_feature_refactor),
        "stability_blend": min(max(float(args.stability_blend), 0.0), 1.0),
        "feature_refactor_gate": bool(not args.disable_feature_refactor_gate),
        "min_refactor_score": min(max(float(args.min_refactor_score), 0.0), 1.0),
        "optimize_command": " ".join(opt_cmd),
        "recommendation_file": str(rec_file) if rec_file.exists() else "",
        "recommendation_top1": rec_row,
        "paper_command": paper_cmd,
    }
    _write_report(report, report_json=report_json, report_md=report_md)

    print("\n" + "=" * 72)
    print("反过拟合流水线完成")
    print("=" * 72)
    print(f"WF窗口文件: {wf_file}")
    print(f"稳定参数组数: {len(stable_df)} (fallback={narrow['used_fallback']})")
    print(f"收窄网格: top_n={report['narrow_topn_grid']} hold={report['narrow_hold_grid']} maxpos={report['narrow_maxpos_grid']}")
    print(f"报告JSON: {report_json}")
    print(f"报告Markdown: {report_md}")
    if paper_cmd:
        print(f"模拟命令: {paper_cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
