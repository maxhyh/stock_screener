#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
围绕 quality_regime 的局部实验矩阵：
1) 固定持有期/单票上限/分市场仓位等核心骨架
2) 细扫 TopN / signal quality / ML blend / refactor floor / risk switch
3) 对首轮前排组合补做 OOS 稳健评估
4) 输出完整矩阵、稳健 shortlist 与摘要
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
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

from quant_optimize import (
    _build_oos_windows,
    _constraint_fail_reasons,
    _passes_robust_hard_filters,
    _robust_oos_metrics,
    _score,
    _score_robust,
)
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
    pcfg = dict(profiles[profile_name])
    pcfg["_default_profile"] = str(root.get("default_profile", ""))
    return pcfg


def _base_cfg_kwargs(pcfg: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    return {
        "fee_bps": float(pcfg.get("fee_bps", 8.0)),
        "slippage_bps": float(pcfg.get("slippage_bps", 5.0)),
        "max_single_pos": float(pcfg.get("max_single_pos", 0.04)),
        "use_regime_position": bool(pcfg.get("use_regime_position", True)),
        "fallback_total_position": float(pcfg.get("fallback_total_position", 0.60)),
        "exclude_st": bool(pcfg.get("exclude_st", True)),
        "min_valid_positions": int(pcfg.get("min_valid_positions", 3)),
        "max_loss_per_trade": (
            None if pcfg.get("max_loss_per_trade", None) is None else float(pcfg.get("max_loss_per_trade"))
        ),
        "engine_mode": str(pcfg.get("engine_mode", "hybrid")),
        "benchmark_mode": str(pcfg.get("benchmark_mode", "hs300")),
        "benchmark_file": args.benchmark_file,
        "exclude_bj9": bool(pcfg.get("exclude_bj9", True)),
        "enable_diversification": not bool(args.disable_diversification),
        "max_industry_positions": int(pcfg.get("max_industry_positions", 3)),
        "corr_lookback_days": int(pcfg.get("corr_lookback_days", 60)),
        "max_pair_corr": float(pcfg.get("max_pair_corr", 0.85)),
        "corr_min_obs": int(pcfg.get("corr_min_obs", 15)),
        "enable_dynamic_exit": not bool(args.disable_dynamic_exit),
        "take_profit": float(pcfg.get("take_profit", 0.18)),
        "stop_loss": float(pcfg.get("stop_loss", 0.08)),
        "trail_drawdown": float(pcfg.get("trail_drawdown", 0.10)),
        "enable_regime_risk_params": not bool(args.disable_regime_risk_params),
        "tp_normal": float(pcfg.get("tp_normal", 0.18)),
        "tp_choppy": float(pcfg.get("tp_choppy", 0.14)),
        "tp_panic": float(pcfg.get("tp_panic", 0.10)),
        "sl_normal": float(pcfg.get("sl_normal", 0.08)),
        "sl_choppy": float(pcfg.get("sl_choppy", 0.06)),
        "sl_panic": float(pcfg.get("sl_panic", 0.05)),
        "trail_normal": float(pcfg.get("trail_normal", 0.10)),
        "trail_choppy": float(pcfg.get("trail_choppy", 0.08)),
        "trail_panic": float(pcfg.get("trail_panic", 0.06)),
        "corr_normal": float(pcfg.get("corr_normal", 0.85)),
        "corr_choppy": float(pcfg.get("corr_choppy", 0.75)),
        "corr_panic": float(pcfg.get("corr_panic", 0.65)),
        "enable_risk_switch": not bool(args.disable_risk_switch),
        "risk_cut_win_rate": float(pcfg.get("risk_cut_win_rate", 0.35)),
        "risk_cut_avg_ret": float(pcfg.get("risk_cut_avg_ret", -0.005)),
        "enable_exec_constraints": not bool(args.disable_exec_constraints),
        "max_exit_delay_days": int(args.max_exit_delay_days),
        "enable_signal_quality_gate": not bool(args.disable_signal_quality_gate),
        "max_abs_pct_chg": float(pcfg.get("max_abs_pct_chg", 8.5)),
        "enable_feature_refactor": not bool(args.disable_feature_refactor),
        "stability_blend": float(pcfg.get("stability_blend", 0.30)),
        "enable_feature_refactor_gate": not bool(args.disable_feature_refactor_gate),
        "verbose": False,
    }


def _combo_to_cfg(
    *,
    start: str,
    end: str,
    top_n: int,
    holding_days: int,
    base_cfg_kwargs: dict[str, object],
    min_signal_quality: float,
    ml_quality_blend: float,
    min_refactor_score: float,
    risk_window: int,
    risk_cut_factor: float,
) -> BacktestConfig:
    return BacktestConfig(
        start=start,
        end=end,
        top_n=max(1, int(top_n)),
        holding_days=max(1, int(holding_days)),
        min_signal_quality=min(max(float(min_signal_quality), 0.0), 1.0),
        ml_quality_blend=min(max(float(ml_quality_blend), 0.0), 1.0),
        min_refactor_score=min(max(float(min_refactor_score), 0.0), 1.0),
        risk_window=max(1, int(risk_window)),
        risk_cut_factor=min(max(float(risk_cut_factor), 0.0), 1.0),
        **base_cfg_kwargs,
    )


def _run_matrix_row(
    *,
    cfg: BacktestConfig,
    hard_filter_kwargs: dict[str, object],
) -> dict[str, object]:
    _, metrics = backtest_portfolio(cfg)
    fail_reasons = _constraint_fail_reasons(
        metrics,
        {},
        robust_on=False,
        min_windows=0,
        min_annual_return_pct=float(hard_filter_kwargs["min_annual_return_pct"]),
        min_excess_annual_pct=float(hard_filter_kwargs["min_excess_annual_pct"]),
        min_sharpe=float(hard_filter_kwargs["min_sharpe"]),
        min_sortino=float(hard_filter_kwargs["min_sortino"]),
        min_win_rate_pct=float(hard_filter_kwargs["min_win_rate_pct"]),
        min_profit_factor=float(hard_filter_kwargs["min_profit_factor"]),
        min_tail_ratio=float(hard_filter_kwargs["min_tail_ratio"]),
        min_capital_efficiency=float(hard_filter_kwargs["min_capital_efficiency"]),
        max_drawdown_limit_pct=float(hard_filter_kwargs["max_drawdown_limit_pct"]),
        max_ulcer_index_pct=hard_filter_kwargs["max_ulcer_index_pct"],
        turnover_cap_pct=hard_filter_kwargs["turnover_cap_pct"],
        min_oos_excess_total_median=0.0,
        min_oos_mdd_worst=-999.0,
        min_oos_pass_rate=0.0,
        min_oos_valid_window_ratio=0.0,
    )
    row: dict[str, object] = {
        "top_n": int(cfg.top_n),
        "holding_days": int(cfg.holding_days),
        "max_single_pos": float(cfg.max_single_pos),
        "use_regime_position": int(bool(cfg.use_regime_position)),
        "min_signal_quality": float(cfg.min_signal_quality),
        "ml_quality_blend": float(cfg.ml_quality_blend),
        "min_refactor_score": float(cfg.min_refactor_score),
        "stability_blend": float(cfg.stability_blend),
        "risk_window": int(cfg.risk_window),
        "risk_cut_factor": float(cfg.risk_cut_factor),
        "pass_hard_filters": int(len(fail_reasons) == 0),
        "constraint_fail_count": int(len(fail_reasons)),
        "constraint_fail_reasons": ",".join(fail_reasons),
        "rank_score": float(_score(metrics)),
    }
    row.update(metrics)
    return row


def _matrix_combo_worker(payload: dict[str, object]) -> dict[str, object]:
    try:
        cfg = _combo_to_cfg(
            start=str(payload["start"]),
            end=str(payload["end"]),
            top_n=int(payload["top_n"]),
            holding_days=int(payload["holding_days"]),
            base_cfg_kwargs=dict(payload["base_cfg_kwargs"]),
            min_signal_quality=float(payload["min_signal_quality"]),
            ml_quality_blend=float(payload["ml_quality_blend"]),
            min_refactor_score=float(payload["min_refactor_score"]),
            risk_window=int(payload["risk_window"]),
            risk_cut_factor=float(payload["risk_cut_factor"]),
        )
        row = _run_matrix_row(cfg=cfg, hard_filter_kwargs=dict(payload["hard_filter_kwargs"]))
        row["worker_error"] = ""
        return row
    except Exception as exc:
        return {
            "top_n": int(payload["top_n"]),
            "holding_days": int(payload["holding_days"]),
            "max_single_pos": float(dict(payload["base_cfg_kwargs"]).get("max_single_pos", 0.0)),
            "use_regime_position": int(bool(dict(payload["base_cfg_kwargs"]).get("use_regime_position", False))),
            "min_signal_quality": float(payload["min_signal_quality"]),
            "ml_quality_blend": float(payload["ml_quality_blend"]),
            "min_refactor_score": float(payload["min_refactor_score"]),
            "stability_blend": float(dict(payload["base_cfg_kwargs"]).get("stability_blend", 0.0)),
            "risk_window": int(payload["risk_window"]),
            "risk_cut_factor": float(payload["risk_cut_factor"]),
            "pass_hard_filters": 0,
            "constraint_fail_count": 1,
            "constraint_fail_reasons": "worker_exception",
            "rank_score": float("-inf"),
            "annual_return_pct": float("nan"),
            "excess_annual_return_pct": float("nan"),
            "max_drawdown_pct": float("nan"),
            "sharpe": float("nan"),
            "sortino": float("nan"),
            "profit_factor": float("nan"),
            "tail_ratio": float("nan"),
            "ulcer_index_pct": float("nan"),
            "capital_efficiency": float("nan"),
            "worker_error": f"{type(exc).__name__}: {exc}",
        }


def _run_robust_shortlist(
    base_rows: pd.DataFrame,
    *,
    start: str,
    end: str,
    holding_days: int,
    base_cfg_kwargs: dict[str, object],
    top_k: int,
    oos_kwargs: dict[str, int],
    hard_filter_kwargs: dict[str, object],
) -> pd.DataFrame:
    if base_rows.empty:
        return pd.DataFrame()

    start_dt = pd.to_datetime(start).normalize()
    end_dt = pd.to_datetime(end).normalize()
    oos_windows = _build_oos_windows(
        start=start_dt,
        end=end_dt,
        warmup_months=max(1, int(oos_kwargs["warmup_months"])),
        test_months=max(1, int(oos_kwargs["test_months"])),
        step_months=max(1, int(oos_kwargs["step_months"])),
    )
    shortlist = base_rows.sort_values(
        ["pass_hard_filters", "rank_score", "sortino", "profit_factor", "tail_ratio"],
        ascending=[False, False, False, False, False],
    ).head(max(1, int(top_k)))
    rows: list[dict[str, object]] = []
    for row in shortlist.to_dict(orient="records"):
        cfg = _combo_to_cfg(
            start=start,
            end=end,
            top_n=int(row["top_n"]),
            holding_days=holding_days,
            base_cfg_kwargs=base_cfg_kwargs,
            min_signal_quality=float(row["min_signal_quality"]),
            ml_quality_blend=float(row["ml_quality_blend"]),
            min_refactor_score=float(row["min_refactor_score"]),
            risk_window=int(row["risk_window"]),
            risk_cut_factor=float(row["risk_cut_factor"]),
        )
        robust = _robust_oos_metrics(
            asdict_for_robust(cfg),
            oos_windows,
            min_trades_per_window=max(1, int(oos_kwargs["min_trades_per_window"])),
        )
        row.update(robust)
        row["robust_score"] = float(_score_robust(row, robust))
        row["pass_robust_hard_filters"] = int(
            _passes_robust_hard_filters(
                row,
                robust,
                int(oos_kwargs["min_windows"]),
                min_annual_return_pct=float(hard_filter_kwargs["min_annual_return_pct"]),
                min_excess_annual_pct=float(hard_filter_kwargs["min_excess_annual_pct"]),
                min_sharpe=float(hard_filter_kwargs["min_sharpe"]),
                min_sortino=float(hard_filter_kwargs["min_sortino"]),
                min_win_rate_pct=float(hard_filter_kwargs["min_win_rate_pct"]),
                min_profit_factor=float(hard_filter_kwargs["min_profit_factor"]),
                min_tail_ratio=float(hard_filter_kwargs["min_tail_ratio"]),
                min_capital_efficiency=float(hard_filter_kwargs["min_capital_efficiency"]),
                max_drawdown_limit_pct=float(hard_filter_kwargs["max_drawdown_limit_pct"]),
                max_ulcer_index_pct=hard_filter_kwargs["max_ulcer_index_pct"],
                min_oos_excess_total_median=float(hard_filter_kwargs["min_oos_excess_total_median"]),
                min_oos_mdd_worst=float(hard_filter_kwargs["min_oos_mdd_worst"]),
                min_oos_pass_rate=float(hard_filter_kwargs["min_oos_pass_rate"]),
                min_oos_valid_window_ratio=float(hard_filter_kwargs["min_oos_valid_window_ratio"]),
                turnover_cap_pct=hard_filter_kwargs["turnover_cap_pct"],
            )
        )
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(
        ["pass_robust_hard_filters", "robust_score", "rank_score"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def _add_baseline_deltas(df: pd.DataFrame, baseline: dict[str, float]) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    plus_cols = [
        "annual_return_pct",
        "excess_annual_return_pct",
        "sharpe",
        "sortino",
        "profit_factor",
        "tail_ratio",
        "capital_efficiency",
    ]
    minus_cols = ["max_drawdown_pct", "ulcer_index_pct"]
    for col in plus_cols:
        out[f"delta_{col}"] = pd.to_numeric(out[col], errors="coerce") - float(baseline.get(col, 0.0))
    for col in minus_cols:
        out[f"improvement_{col}"] = float(baseline.get(col, 0.0)) - pd.to_numeric(out[col], errors="coerce")
    return out


def _build_recommended_table(
    matrix_df: pd.DataFrame,
    robust_df: pd.DataFrame,
    baseline: dict[str, float],
    *,
    top_k: int = 8,
) -> pd.DataFrame:
    selection_source = "in_sample_fallback"
    source = matrix_df.copy()
    if not robust_df.empty and "pass_robust_hard_filters" in robust_df.columns:
        robust_pass = robust_df.loc[pd.to_numeric(robust_df["pass_robust_hard_filters"], errors="coerce") == 1].copy()
        if not robust_pass.empty:
            source = robust_pass
            selection_source = "robust_pass"
    if source.empty:
        return pd.DataFrame()
    out = _add_baseline_deltas(source, baseline)
    out["selection_source"] = selection_source
    if "pass_robust_hard_filters" in out.columns:
        out = out.sort_values(
            ["pass_robust_hard_filters", "robust_score", "rank_score"],
            ascending=[False, False, False],
        )
    else:
        out = out.sort_values(
            ["pass_hard_filters", "rank_score", "sortino", "profit_factor"],
            ascending=[False, False, False, False],
        )
    out = out.head(max(1, int(top_k))).copy()
    out.insert(0, "upgrade_rank", range(1, len(out) + 1))
    keep_cols = [
        "upgrade_rank",
        "selection_source",
        "top_n",
        "holding_days",
        "min_signal_quality",
        "ml_quality_blend",
        "min_refactor_score",
        "risk_window",
        "risk_cut_factor",
        "annual_return_pct",
        "excess_annual_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "sortino",
        "profit_factor",
        "tail_ratio",
        "ulcer_index_pct",
        "capital_efficiency",
        "delta_annual_return_pct",
        "delta_excess_annual_return_pct",
        "delta_sharpe",
        "delta_sortino",
        "delta_profit_factor",
        "delta_tail_ratio",
        "improvement_max_drawdown_pct",
        "improvement_ulcer_index_pct",
    ]
    if "robust_score" in out.columns:
        keep_cols.extend(["robust_score", "oos_excess_total_median", "oos_mdd_worst", "oos_pass_rate"])
    if "pass_robust_hard_filters" in out.columns:
        keep_cols.append("pass_robust_hard_filters")
    return out[[c for c in keep_cols if c in out.columns]].reset_index(drop=True)


def _build_elimination_table(
    matrix_df: pd.DataFrame,
    robust_df: pd.DataFrame,
    baseline: dict[str, float],
) -> pd.DataFrame:
    output_cols = [
        "dimension",
        "value",
        "combo_count",
        "hard_pass_rate",
        "top_quartile_share",
        "robust_evaluated_share",
        "robust_pass_share_of_evaluated",
        "mean_rank_score",
        "mean_excess_annual_return_pct",
        "mean_sortino",
        "mean_profit_factor",
        "mean_tail_ratio",
        "mean_ulcer_index_pct",
        "reasons",
    ]
    if matrix_df.empty:
        return pd.DataFrame(columns=output_cols)
    signature_cols = [
        "top_n",
        "min_signal_quality",
        "ml_quality_blend",
        "min_refactor_score",
        "risk_window",
        "risk_cut_factor",
    ]
    robust_evaluated_keys: set[tuple[object, ...]] = set()
    robust_pass_keys: set[tuple[object, ...]] = set()
    if not robust_df.empty:
        robust_evaluated_keys = {
            tuple(r[c] for c in signature_cols if c in robust_df.columns)
            for _, r in robust_df[signature_cols].drop_duplicates().iterrows()
        }
        if "pass_robust_hard_filters" in robust_df.columns:
            robust_pass_keys = {
                tuple(r[c] for c in signature_cols if c in robust_df.columns)
                for _, r in robust_df.loc[
                    pd.to_numeric(robust_df["pass_robust_hard_filters"], errors="coerce") == 1, signature_cols
                ].drop_duplicates().iterrows()
            }
    top_quartile_cut = float(pd.to_numeric(matrix_df["rank_score"], errors="coerce").quantile(0.75))
    rows: list[dict[str, object]] = []
    dims = [
        ("top_n", "TopN"),
        ("min_signal_quality", "QualityFloor"),
        ("ml_quality_blend", "MLBlend"),
        ("min_refactor_score", "RefactorFloor"),
        ("risk_window", "RiskWindow"),
        ("risk_cut_factor", "RiskCutFactor"),
    ]
    for col, label in dims:
        for value, g in matrix_df.groupby(col):
            robust_eval_share = 0.0
            robust_pass_share = float("nan")
            sig_df = g[signature_cols].drop_duplicates()
            if robust_evaluated_keys:
                eval_hits = [tuple(r[c] for c in signature_cols) in robust_evaluated_keys for _, r in sig_df.iterrows()]
                eval_count = int(sum(eval_hits))
                robust_eval_share = float(eval_count / max(len(sig_df), 1))
                if eval_count > 0:
                    pass_count = sum(1 for _, r in sig_df.iterrows() if tuple(r[c] for c in signature_cols) in robust_pass_keys)
                    robust_pass_share = float(pass_count / eval_count)
            hard_pass_rate = float(pd.to_numeric(g["pass_hard_filters"], errors="coerce").fillna(0.0).mean())
            top_quartile_share = float((pd.to_numeric(g["rank_score"], errors="coerce") >= top_quartile_cut).mean())
            mean_excess = float(pd.to_numeric(g["excess_annual_return_pct"], errors="coerce").mean())
            mean_sortino = float(pd.to_numeric(g["sortino"], errors="coerce").mean())
            mean_profit = float(pd.to_numeric(g["profit_factor"], errors="coerce").mean())
            mean_tail = float(pd.to_numeric(g["tail_ratio"], errors="coerce").mean())
            mean_ulcer = float(pd.to_numeric(g["ulcer_index_pct"], errors="coerce").mean())
            reasons: list[str] = []
            if hard_pass_rate < 0.5:
                reasons.append("high_fail_rate")
            if top_quartile_share <= 0.10:
                reasons.append("rarely_top_quartile")
            if robust_eval_share > 0.0 and robust_pass_share == 0.0:
                reasons.append("no_robust_pass_in_evaluated")
            if mean_excess < float(baseline.get("excess_annual_return_pct", 0.0)):
                reasons.append("weak_excess")
            if mean_sortino < float(baseline.get("sortino", 0.0)):
                reasons.append("weak_sortino")
            if mean_profit < float(baseline.get("profit_factor", 0.0)):
                reasons.append("weak_profit_factor")
            if mean_tail < float(baseline.get("tail_ratio", 0.0)):
                reasons.append("weak_tail_ratio")
            if mean_ulcer > float(baseline.get("ulcer_index_pct", 0.0)):
                reasons.append("worse_ulcer")
            if not reasons:
                continue
            if len(reasons) < 3:
                continue
            rows.append(
                {
                    "dimension": label,
                    "value": value,
                    "combo_count": int(len(g)),
                    "hard_pass_rate": hard_pass_rate,
                    "top_quartile_share": top_quartile_share,
                    "robust_evaluated_share": robust_eval_share,
                    "robust_pass_share_of_evaluated": robust_pass_share,
                    "mean_rank_score": float(pd.to_numeric(g["rank_score"], errors="coerce").mean()),
                    "mean_excess_annual_return_pct": mean_excess,
                    "mean_sortino": mean_sortino,
                    "mean_profit_factor": mean_profit,
                    "mean_tail_ratio": mean_tail,
                    "mean_ulcer_index_pct": mean_ulcer,
                    "reasons": ",".join(reasons),
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=output_cols)
    return out.sort_values(
        ["hard_pass_rate", "top_quartile_share", "mean_rank_score"],
        ascending=[True, True, True],
    ).reset_index(drop=True)[output_cols]


def asdict_for_robust(cfg: BacktestConfig) -> dict[str, object]:
    return {
        "top_n": int(cfg.top_n),
        "holding_days": int(cfg.holding_days),
        "fee_bps": float(cfg.fee_bps),
        "slippage_bps": float(cfg.slippage_bps),
        "max_single_pos": float(cfg.max_single_pos),
        "use_regime_position": bool(cfg.use_regime_position),
        "fallback_total_position": float(cfg.fallback_total_position),
        "exclude_st": bool(cfg.exclude_st),
        "min_valid_positions": int(cfg.min_valid_positions),
        "max_loss_per_trade": cfg.max_loss_per_trade,
        "engine_mode": str(cfg.engine_mode),
        "benchmark_mode": str(cfg.benchmark_mode),
        "benchmark_file": cfg.benchmark_file,
        "exclude_bj9": bool(cfg.exclude_bj9),
        "enable_diversification": bool(cfg.enable_diversification),
        "max_industry_positions": int(cfg.max_industry_positions),
        "corr_lookback_days": int(cfg.corr_lookback_days),
        "max_pair_corr": float(cfg.max_pair_corr),
        "corr_min_obs": int(cfg.corr_min_obs),
        "enable_dynamic_exit": bool(cfg.enable_dynamic_exit),
        "take_profit": float(cfg.take_profit),
        "stop_loss": float(cfg.stop_loss),
        "trail_drawdown": float(cfg.trail_drawdown),
        "enable_regime_risk_params": bool(cfg.enable_regime_risk_params),
        "tp_normal": float(cfg.tp_normal),
        "tp_choppy": float(cfg.tp_choppy),
        "tp_panic": float(cfg.tp_panic),
        "sl_normal": float(cfg.sl_normal),
        "sl_choppy": float(cfg.sl_choppy),
        "sl_panic": float(cfg.sl_panic),
        "trail_normal": float(cfg.trail_normal),
        "trail_choppy": float(cfg.trail_choppy),
        "trail_panic": float(cfg.trail_panic),
        "corr_normal": float(cfg.corr_normal),
        "corr_choppy": float(cfg.corr_choppy),
        "corr_panic": float(cfg.corr_panic),
        "enable_risk_switch": bool(cfg.enable_risk_switch),
        "risk_window": int(cfg.risk_window),
        "risk_cut_win_rate": float(cfg.risk_cut_win_rate),
        "risk_cut_avg_ret": float(cfg.risk_cut_avg_ret),
        "risk_cut_factor": float(cfg.risk_cut_factor),
        "enable_signal_quality_gate": bool(cfg.enable_signal_quality_gate),
        "min_signal_quality": float(cfg.min_signal_quality),
        "ml_quality_blend": float(cfg.ml_quality_blend),
        "max_abs_pct_chg": float(cfg.max_abs_pct_chg),
        "enable_feature_refactor": bool(cfg.enable_feature_refactor),
        "stability_blend": float(cfg.stability_blend),
        "enable_feature_refactor_gate": bool(cfg.enable_feature_refactor_gate),
        "min_refactor_score": float(cfg.min_refactor_score),
        "verbose": False,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="quality_regime 局部实验矩阵")
    p.add_argument("--start", type=str, required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, required=True, help="结束日期 YYYY-MM-DD")
    p.add_argument("--profile", type=str, default="quality_regime", help="基准 profile")
    p.add_argument("--config", type=str, default=str(PROFILE_FILE), help="profile 配置文件")
    p.add_argument("--topn-grid", type=str, default="11,12,13", help="TopN 邻域")
    p.add_argument("--quality-grid", type=str, default="0.40,0.42,0.45", help="质量门槛邻域")
    p.add_argument("--ml-blend-grid", type=str, default="0.76,0.80", help="ML blend 邻域")
    p.add_argument("--refactor-floor-grid", type=str, default="0.50,0.53", help="重构门槛邻域")
    p.add_argument("--risk-window-grid", type=str, default="8,10", help="风险开关窗口邻域")
    p.add_argument("--risk-cut-factor-grid", type=str, default="0.75,0.85", help="风险开关降仓系数邻域")
    p.add_argument("--top-k-robust", type=int, default=12, help="进入 OOS 稳健复评的组合数")
    p.add_argument("--top-k-recommended", type=int, default=8, help="推荐升级参数表行数")
    p.add_argument("--jobs", type=int, default=max(1, min(os.cpu_count() or 1, 4)), help="并行进程数")
    p.add_argument("--oos-warmup-months", type=int, default=6)
    p.add_argument("--oos-test-months", type=int, default=2)
    p.add_argument("--oos-step-months", type=int, default=2)
    p.add_argument("--oos-min-windows", type=int, default=3)
    p.add_argument("--oos-min-trades-per-window", type=int, default=3)
    p.add_argument("--benchmark-file", type=str, default=None)
    p.add_argument("--disable-diversification", action="store_true")
    p.add_argument("--disable-dynamic-exit", action="store_true")
    p.add_argument("--disable-regime-risk-params", action="store_true")
    p.add_argument("--disable-risk-switch", action="store_true")
    p.add_argument("--disable-exec-constraints", action="store_true")
    p.add_argument("--max-exit-delay-days", type=int, default=5)
    p.add_argument("--disable-signal-quality-gate", action="store_true")
    p.add_argument("--disable-feature-refactor", action="store_true")
    p.add_argument("--disable-feature-refactor-gate", action="store_true")
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
    p.add_argument("--min-oos-excess-total-median", type=float, default=0.0)
    p.add_argument("--min-oos-mdd-worst", type=float, default=-15.0)
    p.add_argument("--min-oos-pass-rate", type=float, default=0.45)
    p.add_argument("--min-oos-valid-window-ratio", type=float, default=0.60)
    return p


def main() -> int:
    args = _build_parser().parse_args()
    config_file = Path(args.config)
    if not config_file.exists():
        raise FileNotFoundError(f"未找到配置文件: {config_file}")

    pcfg = _load_profile(str(args.profile), config_file)
    topn_grid = _parse_int_grid(args.topn_grid)
    quality_grid = _parse_float_grid(args.quality_grid)
    ml_blend_grid = _parse_float_grid(args.ml_blend_grid)
    refactor_floor_grid = _parse_float_grid(args.refactor_floor_grid)
    risk_window_grid = _parse_int_grid(args.risk_window_grid)
    risk_cut_factor_grid = _parse_float_grid(args.risk_cut_factor_grid)
    if not all([topn_grid, quality_grid, ml_blend_grid, refactor_floor_grid, risk_window_grid, risk_cut_factor_grid]):
        raise RuntimeError("实验矩阵网格不能为空")

    base_cfg_kwargs = _base_cfg_kwargs(pcfg, args)
    holding_days = int(pcfg.get("holding_days", 8))
    combos = list(product(topn_grid, quality_grid, ml_blend_grid, refactor_floor_grid, risk_window_grid, risk_cut_factor_grid))
    hard_filter_kwargs = {
        "min_annual_return_pct": float(args.min_annual_return_pct),
        "min_excess_annual_pct": float(args.min_excess_annual_pct),
        "min_sharpe": float(args.min_sharpe),
        "min_sortino": float(args.min_sortino),
        "min_win_rate_pct": float(args.min_win_rate_pct),
        "min_profit_factor": float(args.min_profit_factor),
        "min_tail_ratio": float(args.min_tail_ratio),
        "min_capital_efficiency": float(args.min_capital_efficiency),
        "max_drawdown_limit_pct": float(args.max_drawdown_limit_pct),
        "max_ulcer_index_pct": (None if float(args.max_ulcer_index_pct) <= 0 else float(args.max_ulcer_index_pct)),
        "turnover_cap_pct": (None if float(args.turnover_cap_pct) <= 0 else float(args.turnover_cap_pct)),
        "min_oos_excess_total_median": float(args.min_oos_excess_total_median),
        "min_oos_mdd_worst": float(args.min_oos_mdd_worst),
        "min_oos_pass_rate": float(args.min_oos_pass_rate),
        "min_oos_valid_window_ratio": float(args.min_oos_valid_window_ratio),
    }

    print("=" * 72)
    print("quality_regime 局部实验矩阵")
    print("=" * 72)
    print(f"profile={args.profile} | period={args.start}~{args.end}")
    print(f"fixed: hold={holding_days} max_pos={float(pcfg.get('max_single_pos', 0.04)):.2f} regime={bool(pcfg.get('use_regime_position', True))}")
    print(f"combos={len(combos)}")

    baseline_cfg = _combo_to_cfg(
        start=args.start,
        end=args.end,
        top_n=int(pcfg.get("top_n", 12)),
        holding_days=holding_days,
        base_cfg_kwargs=base_cfg_kwargs,
        min_signal_quality=float(pcfg.get("min_signal_quality", 0.40)),
        ml_quality_blend=float(pcfg.get("ml_quality_blend", 0.80)),
        min_refactor_score=float(pcfg.get("min_refactor_score", 0.50)),
        risk_window=int(pcfg.get("risk_window", 8)),
        risk_cut_factor=float(pcfg.get("risk_cut_factor", 0.75)),
    )
    baseline_metrics = backtest_portfolio(baseline_cfg)[1]

    payloads = [
        {
            "start": args.start,
            "end": args.end,
            "holding_days": holding_days,
            "base_cfg_kwargs": base_cfg_kwargs,
            "hard_filter_kwargs": hard_filter_kwargs,
            "top_n": int(top_n),
            "min_signal_quality": float(q_floor),
            "ml_quality_blend": float(ml_blend),
            "min_refactor_score": float(ref_floor),
            "risk_window": int(risk_window),
            "risk_cut_factor": float(risk_cut_factor),
        }
        for (top_n, q_floor, ml_blend, ref_floor, risk_window, risk_cut_factor) in combos
    ]

    rows: list[dict[str, object]] = []
    jobs = max(1, int(args.jobs))
    if jobs == 1:
        for idx, payload in enumerate(payloads, start=1):
            row = _matrix_combo_worker(payload)
            rows.append(row)
            print(
                f"[{idx:>3}/{len(payloads)}] TopN={payload['top_n']} Q={payload['min_signal_quality']:.2f} "
                f"ML={payload['ml_quality_blend']:.2f} Ref={payload['min_refactor_score']:.2f} "
                f"RiskW={payload['risk_window']} RiskCut={payload['risk_cut_factor']:.2f} | "
                f"年化={float(row.get('annual_return_pct', 0.0)):.2f}% "
                f"超额={float(row.get('excess_annual_return_pct', 0.0)):.2f}% "
                f"Sharpe={float(row.get('sharpe', 0.0)):.3f} "
                f"Sortino={float(row.get('sortino', 0.0)):.3f}"
            )
    else:
        print(f"parallel jobs={jobs}")
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            for idx, row in enumerate(ex.map(_matrix_combo_worker, payloads), start=1):
                rows.append(row)
                print(
                    f"[{idx:>3}/{len(payloads)}] TopN={int(row.get('top_n', 0))} "
                    f"Q={float(row.get('min_signal_quality', 0.0)):.2f} "
                    f"ML={float(row.get('ml_quality_blend', 0.0)):.2f} "
                    f"Ref={float(row.get('min_refactor_score', 0.0)):.2f} "
                    f"RiskW={int(row.get('risk_window', 0))} "
                    f"RiskCut={float(row.get('risk_cut_factor', 0.0)):.2f} | "
                    f"年化={float(row.get('annual_return_pct', 0.0)):.2f}% "
                    f"超额={float(row.get('excess_annual_return_pct', 0.0)):.2f}% "
                    f"Sharpe={float(row.get('sharpe', 0.0)):.3f} "
                    f"Sortino={float(row.get('sortino', 0.0)):.3f}"
                )

    matrix_df = pd.DataFrame(rows)
    if matrix_df.empty:
        raise RuntimeError("矩阵结果为空")
    matrix_df = matrix_df.sort_values(
        ["pass_hard_filters", "rank_score", "sortino", "profit_factor", "tail_ratio"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)
    matrix_df.insert(0, "rank", range(1, len(matrix_df) + 1))

    robust_df = _run_robust_shortlist(
        matrix_df,
        start=args.start,
        end=args.end,
        holding_days=holding_days,
        base_cfg_kwargs=base_cfg_kwargs,
        top_k=max(1, int(args.top_k_robust)),
        oos_kwargs={
            "warmup_months": int(args.oos_warmup_months),
            "test_months": int(args.oos_test_months),
            "step_months": int(args.oos_step_months),
            "min_windows": int(args.oos_min_windows),
            "min_trades_per_window": int(args.oos_min_trades_per_window),
        },
        hard_filter_kwargs=hard_filter_kwargs,
    )

    dirs = ensure_output_dirs(str(OUTPUT_DIR))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    matrix_new = dirs["backtest"] / f"quality_regime_matrix_{ts}.csv"
    matrix_legacy = OUTPUT_DIR / f"quality_regime_matrix_{ts}.csv"
    write_dual_csv(matrix_df, matrix_new, matrix_legacy, index=False, encoding="utf-8-sig")

    robust_new = dirs["backtest"] / f"quality_regime_matrix_shortlist_{ts}.csv"
    robust_legacy = OUTPUT_DIR / f"quality_regime_matrix_shortlist_{ts}.csv"
    write_dual_csv(robust_df, robust_new, robust_legacy, index=False, encoding="utf-8-sig")

    recommended_df = _build_recommended_table(
        matrix_df,
        robust_df,
        baseline_metrics,
        top_k=max(1, int(args.top_k_recommended)),
    )
    recommended_new = dirs["backtest"] / f"quality_regime_upgrade_recommended_{ts}.csv"
    recommended_legacy = OUTPUT_DIR / f"quality_regime_upgrade_recommended_{ts}.csv"
    write_dual_csv(recommended_df, recommended_new, recommended_legacy, index=False, encoding="utf-8-sig")

    eliminated_df = _build_elimination_table(matrix_df, robust_df, baseline_metrics)
    eliminated_new = dirs["backtest"] / f"quality_regime_eliminated_bands_{ts}.csv"
    eliminated_legacy = OUTPUT_DIR / f"quality_regime_eliminated_bands_{ts}.csv"
    write_dual_csv(eliminated_df, eliminated_new, eliminated_legacy, index=False, encoding="utf-8-sig")

    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profile": str(args.profile),
        "start": args.start,
        "end": args.end,
        "combos": int(len(combos)),
        "matrix_file": str(matrix_new),
        "shortlist_file": str(robust_new),
        "recommended_file": str(recommended_new),
        "eliminated_file": str(eliminated_new),
        "baseline_metrics": baseline_metrics,
        "best_in_sample": (matrix_df.iloc[0].to_dict() if not matrix_df.empty else {}),
        "best_robust": (robust_df.iloc[0].to_dict() if not robust_df.empty else {}),
    }
    json_path = dirs["backtest"] / f"quality_regime_matrix_{ts}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "-" * 72)
    print("Baseline")
    print(
        f"TopN={baseline_cfg.top_n} Hold={baseline_cfg.holding_days} "
        f"Q={baseline_cfg.min_signal_quality:.2f} ML={baseline_cfg.ml_quality_blend:.2f} "
        f"Ref={baseline_cfg.min_refactor_score:.2f} RiskW={baseline_cfg.risk_window} "
        f"RiskCut={baseline_cfg.risk_cut_factor:.2f} | "
        f"年化={float(baseline_metrics.get('annual_return_pct', 0.0)):.2f}% "
        f"超额={float(baseline_metrics.get('excess_annual_return_pct', 0.0)):.2f}% "
        f"Sharpe={float(baseline_metrics.get('sharpe', 0.0)):.3f} "
        f"Sortino={float(baseline_metrics.get('sortino', 0.0)):.3f}"
    )
    print("Top In-Sample")
    print(matrix_df.head(5)[[
        "rank", "top_n", "min_signal_quality", "ml_quality_blend", "min_refactor_score",
        "risk_window", "risk_cut_factor", "annual_return_pct", "excess_annual_return_pct",
        "max_drawdown_pct", "sharpe", "sortino", "profit_factor", "tail_ratio"
    ]].to_string(index=False))
    if not robust_df.empty:
        print("\nTop Robust")
        print(robust_df.head(5)[[
            "top_n", "min_signal_quality", "ml_quality_blend", "min_refactor_score",
            "risk_window", "risk_cut_factor", "robust_score", "oos_excess_total_median",
            "oos_mdd_worst", "oos_pass_rate", "sortino", "profit_factor", "tail_ratio"
        ]].to_string(index=False))
    if not recommended_df.empty:
        print("\nRecommended Upgrades")
        print(recommended_df.head(5).to_string(index=False))
    if not eliminated_df.empty:
        print("\nEliminated Bands")
        print(eliminated_df.head(10).to_string(index=False))
    print("-" * 72)
    print(f"矩阵文件: {matrix_new}")
    print(f"Shortlist 文件: {robust_new}")
    print(f"推荐升级表: {recommended_new}")
    print(f"淘汰参数带表: {eliminated_new}")
    print(f"摘要 JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
