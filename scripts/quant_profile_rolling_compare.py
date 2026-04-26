#!/usr/bin/env python3
"""
按固定滚动窗口比较多个 quant profile 的 OOS 表现。

用途：
1) 不再只看单段回测，而是把 profile 放到多段时间窗里比较
2) 输出每个窗口的细项结果，以及按 profile 聚合后的风险收益摘要
3) 为 default_profile 升档/降档提供更稳定的依据
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

from quant_optimize import _passes_hard_filters, _score
from quant_profile_ab_compare import _build_cfg, _load_profiles
from quant_portfolio_backtest import backtest_portfolio
from quant_walk_forward import _iter_windows
from utils.output_paths import ensure_output_dirs, write_dual_csv

OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def _parse_profiles(raw: str) -> list[str]:
    out: list[str] = []
    for tok in str(raw or "").split(","):
        name = tok.strip()
        if name:
            out.append(name)
    seen: set[str] = set()
    dedup: list[str] = []
    for name in out:
        if name in seen:
            continue
        seen.add(name)
        dedup.append(name)
    return dedup


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _summarize_profile_windows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "profile",
                "window_count",
                "hard_pass_rate",
                "annual_return_mean",
                "annual_return_median",
                "excess_annual_mean",
                "excess_annual_median",
                "max_drawdown_worst",
                "sharpe_mean",
                "sortino_mean",
                "profit_factor_mean",
                "tail_ratio_mean",
                "win_rate_mean",
                "beat_rate_mean",
                "rank_score_mean",
                "objective_score",
            ]
        )

    rows: list[dict[str, object]] = []
    for profile, g in df.groupby("profile"):
        g = g.copy()
        rows.append(
            {
                "profile": str(profile),
                "window_count": int(len(g)),
                "hard_pass_rate": float(pd.to_numeric(g["pass_hard_filters"], errors="coerce").fillna(0.0).mean()),
                "annual_return_mean": float(pd.to_numeric(g["annual_return_pct"], errors="coerce").mean()),
                "annual_return_median": float(pd.to_numeric(g["annual_return_pct"], errors="coerce").median()),
                "excess_annual_mean": float(pd.to_numeric(g["excess_annual_return_pct"], errors="coerce").mean()),
                "excess_annual_median": float(pd.to_numeric(g["excess_annual_return_pct"], errors="coerce").median()),
                "max_drawdown_worst": float(pd.to_numeric(g["max_drawdown_pct"], errors="coerce").min()),
                "sharpe_mean": float(pd.to_numeric(g["sharpe"], errors="coerce").mean()),
                "sortino_mean": float(pd.to_numeric(g["sortino"], errors="coerce").mean()),
                "profit_factor_mean": float(pd.to_numeric(g["profit_factor"], errors="coerce").mean()),
                "tail_ratio_mean": float(pd.to_numeric(g["tail_ratio"], errors="coerce").mean()),
                "win_rate_mean": float(pd.to_numeric(g["win_rate_pct"], errors="coerce").mean()),
                "beat_rate_mean": float(pd.to_numeric(g["beat_rate_pct"], errors="coerce").mean()),
                "rank_score_mean": float(pd.to_numeric(g["rank_score"], errors="coerce").mean()),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["objective_score"] = (
        0.35 * pd.to_numeric(out["excess_annual_median"], errors="coerce")
        + 0.20 * pd.to_numeric(out["annual_return_median"], errors="coerce")
        + 8.0 * pd.to_numeric(out["hard_pass_rate"], errors="coerce")
        + 2.0 * pd.to_numeric(out["sortino_mean"], errors="coerce")
        + 1.0 * pd.to_numeric(out["tail_ratio_mean"], errors="coerce")
        - 0.35 * pd.to_numeric(out["max_drawdown_worst"], errors="coerce").abs()
    )
    return out.sort_values(
        ["objective_score", "excess_annual_median", "sortino_mean"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def main() -> int:
    p = argparse.ArgumentParser(description="按滚动窗口比较多个 quant profile")
    p.add_argument("--config", type=str, default=os.path.join(BASE_DIR, "config", "quant_live_profiles.json"), help="配置文件路径")
    p.add_argument("--profiles", type=str, default="", help="档位列表，逗号分隔；默认读取 default_profile 和 candidate")
    p.add_argument("--start", type=str, required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, required=True, help="结束日期 YYYY-MM-DD")
    p.add_argument("--train-months", type=int, default=4, help="滚动 warmup 窗口（月）")
    p.add_argument("--test-months", type=int, default=2, help="每个 OOS 窗口（月）")
    p.add_argument("--step-months", type=int, default=1, help="滚动步长（月）")
    p.add_argument("--benchmark-file", type=str, default=None, help="可选覆盖基准文件")
    p.add_argument("--min-annual-return-pct", type=float, default=0.0)
    p.add_argument("--min-excess-annual-pct", type=float, default=0.0)
    p.add_argument("--min-sharpe", type=float, default=0.0)
    p.add_argument("--min-sortino", type=float, default=0.70)
    p.add_argument("--min-win-rate-pct", type=float, default=0.0)
    p.add_argument("--min-profit-factor", type=float, default=1.05)
    p.add_argument("--min-tail-ratio", type=float, default=1.00)
    p.add_argument("--min-capital-efficiency", type=float, default=0.0)
    p.add_argument("--max-drawdown-limit-pct", type=float, default=-15.0)
    p.add_argument("--max-ulcer-index-pct", type=float, default=7.5)
    p.add_argument("--turnover-cap-pct", type=float, default=4500.0)
    p.add_argument("--write-latest", action="store_true", help="写入 latest 快捷文件")
    args = p.parse_args()

    cfg_file = os.path.abspath(args.config)
    if not os.path.exists(cfg_file):
        raise FileNotFoundError(f"未找到配置文件: {cfg_file}")

    root = _load_profiles(cfg_file)
    profiles = root.get("profiles", {})
    if not isinstance(profiles, dict) or not profiles:
        raise RuntimeError("配置文件中未找到 profiles")

    requested_profiles = _parse_profiles(args.profiles)
    if not requested_profiles:
        default_profile = str(root.get("default_profile", "quality_regime"))
        candidate = "quality_regime_candidate" if "quality_regime_candidate" in profiles else None
        requested_profiles = [default_profile]
        if candidate and candidate != default_profile:
            requested_profiles.append(candidate)

    missing = [name for name in requested_profiles if name not in profiles]
    if missing:
        raise RuntimeError(f"未知 profile: {', '.join(missing)}; 可选: {', '.join(sorted(profiles.keys()))}")

    start_dt = pd.to_datetime(args.start).normalize()
    end_dt = pd.to_datetime(args.end).normalize()
    if start_dt >= end_dt:
        raise ValueError("start 必须早于 end")

    windows = list(
        _iter_windows(
            start_dt,
            end_dt,
            train_months=max(1, int(args.train_months)),
            test_months=max(1, int(args.test_months)),
            step_months=max(1, int(args.step_months)),
        )
    )
    if not windows:
        raise RuntimeError("滚动窗口为空，请调整 train/test/step 参数")

    print("=" * 72)
    print("量化档位滚动比较")
    print("=" * 72)
    print(f"profiles={requested_profiles}")
    print(f"period={args.start}~{args.end} | train={args.train_months}m | test={args.test_months}m | step={args.step_months}m")
    print(f"windows={len(windows)}")

    rows: list[dict[str, object]] = []
    for profile in requested_profiles:
        profile_cfg = dict(profiles[profile])
        for window_idx, _train_start, _train_end, test_start, test_end in windows:
            window_args = argparse.Namespace(
                start=test_start.strftime("%Y-%m-%d"),
                end=test_end.strftime("%Y-%m-%d"),
                benchmark_file=args.benchmark_file,
                verbose=False,
            )
            cfg = _build_cfg(profile_cfg, window_args)
            _, metrics = backtest_portfolio(cfg)
            pass_hard = int(
                _passes_hard_filters(
                    metrics,
                    min_annual_return_pct=float(args.min_annual_return_pct),
                    min_excess_annual_pct=float(args.min_excess_annual_pct),
                    min_sharpe=float(args.min_sharpe),
                    min_sortino=float(args.min_sortino),
                    min_win_rate_pct=float(args.min_win_rate_pct),
                    min_profit_factor=float(args.min_profit_factor),
                    min_tail_ratio=float(args.min_tail_ratio),
                    min_capital_efficiency=float(args.min_capital_efficiency),
                    max_drawdown_limit_pct=float(args.max_drawdown_limit_pct),
                    max_ulcer_index_pct=(None if float(args.max_ulcer_index_pct) <= 0 else float(args.max_ulcer_index_pct)),
                    turnover_cap_pct=(None if float(args.turnover_cap_pct) <= 0 else float(args.turnover_cap_pct)),
                )
            )
            row = {
                "profile": profile,
                "window_idx": int(window_idx),
                "test_start": test_start.strftime("%Y-%m-%d"),
                "test_end": test_end.strftime("%Y-%m-%d"),
                "top_n": int(cfg.top_n),
                "holding_days": int(cfg.holding_days),
                "use_regime_position": int(bool(cfg.use_regime_position)),
                "fee_bps": float(cfg.fee_bps),
                "slippage_bps": float(cfg.slippage_bps),
                "min_signal_quality": float(cfg.min_signal_quality),
                "ml_quality_blend": float(cfg.ml_quality_blend),
                "min_refactor_score": float(cfg.min_refactor_score),
                "risk_window": int(cfg.risk_window),
                "risk_cut_factor": float(cfg.risk_cut_factor),
                "pass_hard_filters": pass_hard,
                "rank_score": float(_score(metrics)),
            }
            row.update(metrics)
            rows.append(row)
            print(
                f"[{profile}] win#{window_idx} {row['test_start']}~{row['test_end']} | "
                f"年化={_safe_float(row.get('annual_return_pct')):.2f}% "
                f"超额={_safe_float(row.get('excess_annual_return_pct')):.2f}% "
                f"MDD={_safe_float(row.get('max_drawdown_pct')):.2f}% "
                f"Sharpe={_safe_float(row.get('sharpe')):.3f} "
                f"pass={pass_hard}"
            )

    detail_df = pd.DataFrame(rows)
    summary_df = _summarize_profile_windows(detail_df)

    if not summary_df.empty:
        base_profile = requested_profiles[0]
        base_row = summary_df.loc[summary_df["profile"] == base_profile].head(1)
        if not base_row.empty:
            base = base_row.iloc[0]
            for col in [
                "annual_return_mean",
                "annual_return_median",
                "excess_annual_mean",
                "excess_annual_median",
                "max_drawdown_worst",
                "sharpe_mean",
                "sortino_mean",
                "profit_factor_mean",
                "tail_ratio_mean",
                "hard_pass_rate",
                "objective_score",
            ]:
                summary_df[f"delta_{col}"] = pd.to_numeric(summary_df[col], errors="coerce") - float(base[col])

    dirs = ensure_output_dirs(OUTPUT_DIR)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_new = dirs["backtest"] / f"quant_profile_rolling_compare_detail_{ts}.csv"
    detail_legacy = Path(OUTPUT_DIR) / f"quant_profile_rolling_compare_detail_{ts}.csv"
    write_dual_csv(detail_df, detail_new, detail_legacy, index=False, encoding="utf-8-sig")

    summary_new = dirs["backtest"] / f"quant_profile_rolling_compare_summary_{ts}.csv"
    summary_legacy = Path(OUTPUT_DIR) / f"quant_profile_rolling_compare_summary_{ts}.csv"
    write_dual_csv(summary_df, summary_new, summary_legacy, index=False, encoding="utf-8-sig")

    json_path = dirs["backtest"] / f"quant_profile_rolling_compare_{ts}.json"
    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profiles": requested_profiles,
        "start": args.start,
        "end": args.end,
        "train_months": int(args.train_months),
        "test_months": int(args.test_months),
        "step_months": int(args.step_months),
        "window_count": int(len(windows)),
        "best_profile": (summary_df.iloc[0].to_dict() if not summary_df.empty else {}),
        "detail_file": str(detail_new),
        "summary_file": str(summary_new),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if bool(args.write_latest):
        write_dual_csv(
            detail_df,
            dirs["backtest"] / "quant_profile_rolling_compare_detail_latest.csv",
            Path(OUTPUT_DIR) / "quant_profile_rolling_compare_detail_latest.csv",
            index=False,
            encoding="utf-8-sig",
        )
        write_dual_csv(
            summary_df,
            dirs["backtest"] / "quant_profile_rolling_compare_summary_latest.csv",
            Path(OUTPUT_DIR) / "quant_profile_rolling_compare_summary_latest.csv",
            index=False,
            encoding="utf-8-sig",
        )
        (dirs["backtest"] / "quant_profile_rolling_compare_latest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print("\n" + "-" * 72)
    if not summary_df.empty:
        print(summary_df.to_string(index=False))
    print("-" * 72)
    print(f"detail: {detail_new}")
    print(f"summary: {summary_new}")
    print(f"json: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
