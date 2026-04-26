#!/usr/bin/env python3
"""
汇总研究侧与执行侧证据，给出 quant profile 升档/保留建议。

用途：
1) 读取 rolling OOS 比较结果，衡量研究侧稳健性
2) 汇总 P2 replay ledger / summary，衡量纸面执行与风控可实现性
3) 输出统一 promotion review，减少“凭感觉升档”
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

from quant_p2_rolling_replay import _objective_score as _p2_objective_score
from quant_p2_rolling_replay import _summarize_ledger
from utils.promotion_decision import validate_promotion_decision_payload

OUTPUT_DIR = BASE_DIR / "output"
BACKTEST_DIR = OUTPUT_DIR / "backtest"
EXEC_DIR = OUTPUT_DIR / "execution"
PROFILE_FILE = BASE_DIR / "config" / "quant_live_profiles.json"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if pd.isna(x):
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _safe_int(value: object, default: int = 0) -> int:
    v = _safe_float(value, float(default))
    if pd.isna(v):
        return int(default)
    return int(v)


def _row_first_finite(row: pd.Series, cols: list[str], default: float = float("nan")) -> float:
    for c in cols:
        if c not in row.index:
            continue
        val = _safe_float(row.get(c, float("nan")), float("nan"))
        if pd.notna(val):
            return float(val)
    return float(default)


def _load_root_config(config_file: Path) -> dict[str, object]:
    with config_file.open("r", encoding="utf-8") as f:
        root = json.load(f)
    if not isinstance(root, dict):
        raise RuntimeError("profile 配置文件格式错误")
    return root


def _parse_profiles(raw: str, root: dict[str, object]) -> list[str]:
    out: list[str] = []
    for tok in str(raw or "").split(","):
        name = tok.strip()
        if name:
            out.append(name)
    if out:
        return list(dict.fromkeys(out))
    profiles = root.get("profiles", {})
    if not isinstance(profiles, dict):
        return []
    default_profile = str(root.get("default_profile", "quality_regime"))
    names = [default_profile]
    for name in sorted(profiles):
        if str(name).startswith("quality_regime_candidate") and str(name) != default_profile:
            names.append(str(name))
    return list(dict.fromkeys([x for x in names if x]))


def _detect_profile_from_name(name: str, profiles: list[str]) -> str:
    stem = Path(name).name
    for profile in sorted(profiles, key=len, reverse=True):
        marker = f"paper_replay_{profile}_"
        if marker in stem:
            return profile
    return ""


def _load_research_summary(path: Path, profiles: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"未找到 rolling summary: {path}")
    df = pd.read_csv(path)
    if df.empty:
        raise RuntimeError(f"rolling summary 为空: {path}")
    df = df[df["profile"].astype(str).isin(profiles)].copy()
    if df.empty:
        raise RuntimeError("rolling summary 中未找到目标 profile")
    keep_cols = [
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
        "rank_score_mean",
        "objective_score",
    ]
    for c in keep_cols:
        if c not in df.columns:
            df[c] = 0.0
    return df[keep_cols].reset_index(drop=True)


def _summarize_p2_ledgers(profiles: list[str], ledgers: list[Path], min_days: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for fp in ledgers:
        profile = _detect_profile_from_name(fp.name, profiles)
        if not profile:
            continue
        metrics = _summarize_ledger(fp)
        rows.append(
            {
                "profile": profile,
                "ledger_file": str(fp),
                "executed_days": int(metrics.get("executed_days", 0)),
                "nav_return_pct": float(metrics.get("nav_return_pct", 0.0)),
                "max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0.0)),
                "turnover_mean": float(metrics.get("turnover_mean", 0.0)),
                "exec_block_rate_pct": float(metrics.get("exec_block_rate_pct", 0.0)),
                "risk_block_rate_pct": float(metrics.get("risk_block_rate_pct", 0.0)),
                "style_hit_rate_pct": float(metrics.get("style_hit_rate_pct", 0.0)),
                "target_weight_sum_mean": float(metrics.get("target_weight_sum_mean", 0.0)),
                "objective_score": float(
                    _p2_objective_score(
                        nav_return_pct=float(metrics.get("nav_return_pct", 0.0)),
                        max_drawdown_pct=float(metrics.get("max_drawdown_pct", 0.0)),
                        turnover_mean=float(metrics.get("turnover_mean", 0.0)),
                        exec_block_rate_pct=float(metrics.get("exec_block_rate_pct", 0.0)),
                        risk_block_rate_pct=float(metrics.get("risk_block_rate_pct", 0.0)),
                        style_hit_rate_pct=float(metrics.get("style_hit_rate_pct", 0.0)),
                    )
                ),
            }
        )
    detail_df = pd.DataFrame(rows)
    if detail_df.empty:
        return pd.DataFrame(
            columns=[
                "profile",
                "p2_replay_count",
                "p2_executed_days_total",
                "p2_executed_days_mean",
                "p2_nav_return_mean",
                "p2_max_drawdown_worst",
                "p2_exec_block_rate_mean",
                "p2_risk_block_rate_mean",
                "p2_style_hit_rate_mean",
                "p2_target_weight_sum_mean",
                "p2_objective_mean",
                "p2_min_days_gate",
            ]
        )

    out_rows: list[dict[str, object]] = []
    for profile, g in detail_df.groupby("profile"):
        out_rows.append(
            {
                "profile": str(profile),
                "p2_replay_count": int(len(g)),
                "p2_executed_days_total": int(pd.to_numeric(g["executed_days"], errors="coerce").fillna(0).sum()),
                "p2_executed_days_mean": float(pd.to_numeric(g["executed_days"], errors="coerce").mean()),
                "p2_nav_return_mean": float(pd.to_numeric(g["nav_return_pct"], errors="coerce").mean()),
                "p2_max_drawdown_worst": float(pd.to_numeric(g["max_drawdown_pct"], errors="coerce").min()),
                "p2_exec_block_rate_mean": float(pd.to_numeric(g["exec_block_rate_pct"], errors="coerce").mean()),
                "p2_risk_block_rate_mean": float(pd.to_numeric(g["risk_block_rate_pct"], errors="coerce").mean()),
                "p2_style_hit_rate_mean": float(pd.to_numeric(g["style_hit_rate_pct"], errors="coerce").mean()),
                "p2_target_weight_sum_mean": float(pd.to_numeric(g["target_weight_sum_mean"], errors="coerce").mean()),
                "p2_objective_mean": float(pd.to_numeric(g["objective_score"], errors="coerce").mean()),
            }
        )
    out = pd.DataFrame(out_rows)
    out["p2_min_days_gate"] = (pd.to_numeric(out["p2_executed_days_total"], errors="coerce") >= int(min_days)).astype(int)
    return out.sort_values(["p2_objective_mean", "p2_nav_return_mean"], ascending=[False, False]).reset_index(drop=True)


def _add_p2_window_evidence(agg: pd.DataFrame, detail_df: pd.DataFrame, *, main_profile: str) -> pd.DataFrame:
    out = agg.copy()
    defaults = {
        "p2_window_count": 0,
        "p2_nav_not_below_main_windows": 0,
        "p2_mdd_not_worse_than_main_windows": 0,
        "p2_target_weight_sum_mean": float("nan"),
        "p2_target_weight_sum_60": float("nan"),
        "p2_target_weight_sum_90": float("nan"),
        "p2_target_weight_sum_120": float("nan"),
    }
    if detail_df.empty or "profile" not in detail_df.columns or "window" not in detail_df.columns:
        for c, v in defaults.items():
            if c not in out.columns:
                out[c] = v
        return out

    df = detail_df.copy()
    df["profile"] = df["profile"].astype(str)
    df["window"] = pd.to_numeric(df["window"], errors="coerce").fillna(0).astype(int)
    for c in ["objective_score", "nav_return_pct", "max_drawdown_pct", "executed_days", "target_weight_sum_mean"]:
        if c not in df.columns:
            df[c] = 0.0
        df[c] = pd.to_numeric(df[c], errors="coerce")
    sort_cols = ["profile", "window", "objective_score", "nav_return_pct", "executed_days"]
    selected = (
        df.sort_values(sort_cols, ascending=[True, True, False, False, False])
        .groupby(["profile", "window"], as_index=False)
        .head(1)
        .reset_index(drop=True)
    )
    main = selected[selected["profile"] == str(main_profile)][
        ["window", "nav_return_pct", "max_drawdown_pct"]
    ].rename(
        columns={
            "nav_return_pct": "_main_nav_return_pct",
            "max_drawdown_pct": "_main_max_drawdown_pct",
        }
    )
    merged = selected.merge(main, on="window", how="left")

    rows: list[dict[str, object]] = []
    for profile, g in merged.groupby("profile", dropna=False):
        has_main = g["_main_nav_return_pct"].notna()
        nav_pass = (
            g.loc[has_main, "nav_return_pct"].astype(float)
            >= g.loc[has_main, "_main_nav_return_pct"].astype(float) - 1e-12
        )
        mdd_pass = (
            g.loc[has_main, "max_drawdown_pct"].astype(float)
            >= g.loc[has_main, "_main_max_drawdown_pct"].astype(float) - 1e-12
        )
        row = {
            "profile": str(profile),
            "p2_window_count": int(has_main.sum()),
            "p2_nav_not_below_main_windows": int(nav_pass.sum()),
            "p2_mdd_not_worse_than_main_windows": int(mdd_pass.sum()),
            "p2_target_weight_sum_mean": float(pd.to_numeric(g["target_weight_sum_mean"], errors="coerce").mean()),
        }
        for window in [60, 90, 120]:
            w = g[g["window"] == int(window)]
            row[f"p2_target_weight_sum_{window}"] = (
                float(pd.to_numeric(w["target_weight_sum_mean"], errors="coerce").iloc[0])
                if not w.empty
                else float("nan")
            )
        rows.append(row)
    evidence = pd.DataFrame(rows)
    overlap = [c for c in evidence.columns if c != "profile" and c in out.columns]
    if overlap:
        out = out.drop(columns=overlap)
    out = out.merge(evidence, on="profile", how="left")
    for c, v in defaults.items():
        if c not in out.columns:
            out[c] = v
        out[c] = out[c].fillna(v)
    return out


def _load_or_build_p2_summary(
    *,
    p2_summary_file: Path | list[Path] | None,
    profiles: list[str],
    ledger_glob: str,
    min_days: int,
    main_profile: str,
) -> tuple[pd.DataFrame, list[Path]]:
    summary_files: list[Path] = []
    if isinstance(p2_summary_file, list):
        summary_files = [fp for fp in p2_summary_file if fp.exists()]
    elif p2_summary_file and p2_summary_file.exists():
        summary_files = [p2_summary_file]
    if summary_files:
        frames: list[pd.DataFrame] = []
        for fp in summary_files:
            part = pd.read_csv(fp)
            if not part.empty:
                frames.append(part)
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if not df.empty and "profile" in df.columns:
            df = df[df["profile"].astype(str).isin(profiles)].copy()
            if not df.empty:
                if "target_weight_sum_mean" not in df.columns:
                    df["target_weight_sum_mean"] = float("nan")
                agg = (
                    df.groupby("profile", dropna=False)
                    .agg(
                        p2_replay_count=("profile", "size"),
                        p2_executed_days_total=("executed_days", "sum"),
                        p2_executed_days_mean=("executed_days", "mean"),
                        p2_nav_return_mean=("nav_return_pct", "mean"),
                        p2_max_drawdown_worst=("max_drawdown_pct", "min"),
                        p2_exec_block_rate_mean=("exec_block_rate_pct", "mean"),
                        p2_risk_block_rate_mean=("risk_block_rate_pct", "mean"),
                        p2_style_hit_rate_mean=("style_hit_rate_pct", "mean"),
                        p2_target_weight_sum_mean=("target_weight_sum_mean", "mean"),
                        p2_objective_mean=("objective_score", "mean"),
                    )
                    .reset_index()
                )
                agg["p2_min_days_gate"] = (
                    pd.to_numeric(agg["p2_executed_days_total"], errors="coerce") >= int(min_days)
                ).astype(int)
                agg = _add_p2_window_evidence(agg, df, main_profile=main_profile)
                return agg, []

    ledgers = sorted(EXEC_DIR.glob(ledger_glob))
    agg = _summarize_p2_ledgers(profiles, ledgers, min_days=min_days)
    agg = _add_p2_window_evidence(agg, pd.DataFrame(), main_profile=main_profile)
    return agg, ledgers


def _load_shadow_diagnosis(path: Path | None, profiles: list[str]) -> pd.DataFrame:
    if not path or not path.exists():
        return pd.DataFrame(columns=["profile"])
    df = pd.read_csv(path)
    if df.empty or "profile" not in df.columns:
        return pd.DataFrame(columns=["profile"])
    df = df[df["profile"].astype(str).isin(profiles)].copy()
    if df.empty:
        return pd.DataFrame(columns=["profile"])
    rename_map = {
        "window_count": "shadow_window_count",
        "executed_days_total": "shadow_executed_days_total",
        "adv_blocked_rows_total": "shadow_adv_blocked_rows_total",
        "adv_block_days_total": "shadow_adv_block_days_total",
        "adv_participation_mean_pct": "shadow_adv_participation_mean_pct",
        "adv_participation_max_pct": "shadow_adv_participation_max_pct",
        "mean_top_industry_weight_pct": "shadow_mean_top_industry_weight_pct",
        "worst_top_industry_weight_pct": "shadow_worst_top_industry_weight_pct",
        "mean_industry_hhi": "shadow_mean_industry_hhi",
        "worst_industry_hhi": "shadow_worst_industry_hhi",
        "mean_top_industry_invested_weight_pct": "shadow_mean_top_industry_invested_weight_pct",
        "worst_top_industry_invested_weight_pct": "shadow_worst_top_industry_invested_weight_pct",
        "mean_industry_invested_hhi": "shadow_mean_industry_invested_hhi",
        "worst_industry_invested_hhi": "shadow_worst_industry_invested_hhi",
        "mean_top_industry_nav_weight_pct": "shadow_mean_top_industry_nav_weight_pct",
        "worst_top_industry_nav_weight_pct": "shadow_worst_top_industry_nav_weight_pct",
        "mean_industry_nav_hhi": "shadow_mean_industry_nav_hhi",
        "worst_industry_nav_hhi": "shadow_worst_industry_nav_hhi",
        "dominant_industry": "shadow_dominant_industry",
    }
    keep = ["profile"] + [c for c in rename_map if c in df.columns]
    out = df[keep].rename(columns=rename_map).copy()
    for c in out.columns:
        if c not in {"profile", "shadow_dominant_industry"}:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.reset_index(drop=True)


def _build_promotion_review(
    research_df: pd.DataFrame,
    p2_df: pd.DataFrame,
    *,
    main_profile: str,
) -> pd.DataFrame:
    df = research_df.merge(p2_df, on="profile", how="left")
    for c in [
        "p2_replay_count",
        "p2_executed_days_total",
        "p2_executed_days_mean",
        "p2_nav_return_mean",
        "p2_max_drawdown_worst",
        "p2_exec_block_rate_mean",
        "p2_risk_block_rate_mean",
        "p2_style_hit_rate_mean",
        "p2_objective_mean",
        "p2_min_days_gate",
        "p2_window_count",
        "p2_nav_not_below_main_windows",
        "p2_mdd_not_worse_than_main_windows",
        "p2_target_weight_sum_mean",
        "p2_target_weight_sum_60",
        "p2_target_weight_sum_90",
        "p2_target_weight_sum_120",
    ]:
        if c not in df.columns:
            df[c] = float("nan") if c.startswith("p2_target_weight_sum") else 0.0
    shadow_numeric_cols = [
        "shadow_window_count",
        "shadow_executed_days_total",
        "shadow_adv_blocked_rows_total",
        "shadow_adv_block_days_total",
        "shadow_adv_participation_mean_pct",
        "shadow_adv_participation_max_pct",
        "shadow_mean_top_industry_weight_pct",
        "shadow_worst_top_industry_weight_pct",
        "shadow_mean_industry_hhi",
        "shadow_worst_industry_hhi",
        "shadow_mean_top_industry_invested_weight_pct",
        "shadow_worst_top_industry_invested_weight_pct",
        "shadow_mean_industry_invested_hhi",
        "shadow_worst_industry_invested_hhi",
        "shadow_mean_top_industry_nav_weight_pct",
        "shadow_worst_top_industry_nav_weight_pct",
        "shadow_mean_industry_nav_hhi",
        "shadow_worst_industry_nav_hhi",
    ]
    for c in shadow_numeric_cols:
        if c not in df.columns:
            df[c] = float("nan")
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "shadow_dominant_industry" not in df.columns:
        df["shadow_dominant_industry"] = ""
    df["shadow_evidence_available"] = (
        df[
            [
                "shadow_executed_days_total",
                "shadow_adv_blocked_rows_total",
                "shadow_mean_top_industry_weight_pct",
                "shadow_worst_top_industry_weight_pct",
                "shadow_mean_top_industry_invested_weight_pct",
                "shadow_mean_top_industry_nav_weight_pct",
            ]
        ]
        .notna()
        .any(axis=1)
        .astype(int)
    )

    df["research_score"] = (
        1.00 * pd.to_numeric(df["objective_score"], errors="coerce").fillna(0.0)
        + 2.0 * pd.to_numeric(df["hard_pass_rate"], errors="coerce").fillna(0.0)
    )
    df["ops_score"] = (
        0.60 * pd.to_numeric(df["p2_objective_mean"], errors="coerce").fillna(0.0)
        + 0.20 * pd.to_numeric(df["p2_nav_return_mean"], errors="coerce").fillna(0.0)
        + 2.0 * pd.to_numeric(df["p2_min_days_gate"], errors="coerce").fillna(0.0)
        - 0.10 * pd.to_numeric(df["p2_exec_block_rate_mean"], errors="coerce").fillna(0.0)
        - 0.10 * pd.to_numeric(df["p2_risk_block_rate_mean"], errors="coerce").fillna(0.0)
        - 0.05 * pd.to_numeric(df["p2_style_hit_rate_mean"], errors="coerce").fillna(0.0)
    )
    df["promotion_score"] = 0.65 * df["research_score"] + 0.35 * df["ops_score"]
    df["is_main_profile"] = (df["profile"].astype(str) == str(main_profile)).astype(int)

    main_row = df[df["profile"].astype(str) == str(main_profile)].head(1)
    main_score = _safe_float(main_row["promotion_score"].iloc[0]) if not main_row.empty else 0.0
    main_ops_score = _safe_float(main_row["ops_score"].iloc[0]) if not main_row.empty else 0.0
    main_p2_objective = _safe_float(main_row["p2_objective_mean"].iloc[0]) if not main_row.empty else 0.0
    main_p2_mdd = _safe_float(main_row["p2_max_drawdown_worst"].iloc[0], float("nan")) if not main_row.empty else float("nan")
    main_shadow_adv_rows = _safe_float(main_row["shadow_adv_blocked_rows_total"].iloc[0], float("nan")) if not main_row.empty else float("nan")
    main_shadow_mean_ind = (
        _row_first_finite(
            main_row.iloc[0],
            ["shadow_mean_top_industry_invested_weight_pct", "shadow_mean_top_industry_weight_pct"],
        )
        if not main_row.empty
        else float("nan")
    )
    main_shadow_days = _safe_float(main_row["shadow_executed_days_total"].iloc[0], float("nan")) if not main_row.empty else float("nan")

    hard_gate_pass: list[int] = []
    hard_gate_reasons: list[str] = []
    for _, row in df.iterrows():
        if str(row.get("profile", "")) == str(main_profile):
            hard_gate_pass.append(1)
            hard_gate_reasons.append("main_profile")
            continue
        reasons: list[str] = []
        if int(_safe_float(row.get("p2_min_days_gate", 0.0))) <= 0:
            reasons.append("p2_executed_days_insufficient")
        if _safe_float(row.get("ops_score", 0.0)) < main_ops_score:
            reasons.append("ops_score_below_main")
        if _safe_float(row.get("p2_objective_mean", 0.0)) < main_p2_objective:
            reasons.append("p2_objective_below_main")
        window_count = _safe_int(row.get("p2_window_count", 0), 0)
        if window_count > 0:
            if _safe_int(row.get("p2_nav_not_below_main_windows", 0), 0) < 2:
                reasons.append("p2_long_window_nav_parity_failed")
            if _safe_int(row.get("p2_mdd_not_worse_than_main_windows", 0), 0) < 2:
                reasons.append("p2_long_window_mdd_parity_failed")
        p2_mdd = _safe_float(row.get("p2_max_drawdown_worst", float("nan")), float("nan"))
        if pd.notna(p2_mdd) and pd.notna(main_p2_mdd) and p2_mdd < main_p2_mdd - 1e-12:
            reasons.append("p2_mdd_worse_than_main")
        target_w_mean = _safe_float(row.get("p2_target_weight_sum_mean", float("nan")), float("nan"))
        if pd.notna(target_w_mean) and target_w_mean < 0.30 - 1e-12:
            reasons.append("target_weight_sum_mean_too_low")
        target_w_60 = _safe_float(row.get("p2_target_weight_sum_60", float("nan")), float("nan"))
        if pd.notna(target_w_60) and target_w_60 < 0.24 - 1e-12:
            reasons.append("target_weight_sum_60_too_low")
        if int(_safe_float(row.get("shadow_evidence_available", 0.0))) > 0:
            shadow_days = _safe_float(row.get("shadow_executed_days_total", float("nan")), float("nan"))
            if pd.notna(shadow_days) and pd.notna(main_shadow_days) and shadow_days < min(20.0, main_shadow_days):
                reasons.append("shadow_execution_coverage_insufficient")
            adv_rows = _safe_float(row.get("shadow_adv_blocked_rows_total", float("nan")), float("nan"))
            if pd.notna(adv_rows) and pd.notna(main_shadow_adv_rows) and adv_rows > main_shadow_adv_rows:
                reasons.append("adv_blocked_rows_worse_than_main")
            if pd.notna(adv_rows) and adv_rows > 100.0:
                reasons.append("adv_blocked_rows_hard_cap_failed")
            mean_ind = _row_first_finite(
                row,
                ["shadow_mean_top_industry_invested_weight_pct", "shadow_mean_top_industry_weight_pct"],
            )
            if pd.notna(mean_ind):
                rel_cap = main_shadow_mean_ind + 2.0 if pd.notna(main_shadow_mean_ind) else float("nan")
                if not (mean_ind <= 32.0 or (pd.notna(rel_cap) and mean_ind <= rel_cap)):
                    reasons.append("industry_concentration_hard_cap_failed")
                    reasons.append("industry_invested_concentration_hard_cap_failed")
            mean_nav_ind = _safe_float(row.get("shadow_mean_top_industry_nav_weight_pct", float("nan")), float("nan"))
            if pd.notna(mean_nav_ind) and mean_nav_ind > 24.0 + 1e-12:
                reasons.append("industry_nav_concentration_hard_cap_failed")
        hard_gate_pass.append(0 if reasons else 1)
        hard_gate_reasons.append(",".join(reasons) if reasons else "passed")

    df["promotion_hard_gate_pass"] = hard_gate_pass
    df["promotion_hard_gate_reasons"] = hard_gate_reasons

    df = df.sort_values(
        ["promotion_score", "research_score", "ops_score", "p2_executed_days_total"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    decisions: list[str] = []
    rationales: list[str] = []
    for _, row in df.iterrows():
        profile = str(row["profile"])
        score = _safe_float(row["promotion_score"])
        ops_score = _safe_float(row.get("ops_score"))
        p2_gate = int(_safe_float(row.get("p2_min_days_gate", 0.0)))
        hard_gate = int(_safe_float(row.get("promotion_hard_gate_pass", 1.0)))
        if profile == str(main_profile):
            decisions.append("keep_main")
            rationales.append("当前主档，作为基准保留")
            continue
        if p2_gate <= 0:
            decisions.append("shadow_only")
            rationales.append("研究侧更强，但 P2 执行样本不足，先保留影子跟踪")
            continue
        if hard_gate <= 0:
            decisions.append("shadow_only")
            rationales.append(f"硬门槛未通过：{row.get('promotion_hard_gate_reasons', '')}")
            continue
        if ops_score < main_ops_score:
            decisions.append("shadow_preferred")
            rationales.append("研究侧更强，但执行侧弱于当前主档，继续 shadow 观察")
            continue
        if score > main_score + 1.0:
            decisions.append("promote_candidate")
            rationales.append("研究与执行综合评分显著领先，满足升档条件")
        elif score > main_score:
            decisions.append("shadow_preferred")
            rationales.append("综合评分略优，但优势不够大，建议继续 shadow")
        else:
            decisions.append("keep_shadow")
            rationales.append("执行侧或综合评分未超过主档，继续候选跟踪")
    df["decision"] = decisions
    df["decision_rationale"] = rationales
    return df


def _build_promotion_decision(
    review_df: pd.DataFrame,
    *,
    main_profile: str,
    min_promote_margin: float,
    review_id: str,
    min_p2_executed_days: int,
    review_csv: str,
    review_meta_json: str,
) -> dict[str, object]:
    if review_df.empty:
        return {
            "schema_version": 1,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "review_id": str(review_id),
            "expected_current_default_profile": str(main_profile),
            "final_default_profile": str(main_profile),
            "candidate_profile": "",
            "decision": "keep",
            "change_required": False,
            "reason_code": "review_empty",
            "rationale": "Promotion review 为空，维持当前主档。",
            "evidence": {
                "main_score": 0.0,
                "candidate_score": 0.0,
                "score_margin": 0.0,
                "candidate_p2_executed_days_total": 0,
                "min_p2_executed_days": int(min_p2_executed_days),
                "candidate_p2_gate_passed": False,
                "candidate_promotion_hard_gate_passed": False,
                "candidate_execution_parity_passed": False,
            },
            "artifacts": {
                "review_csv": str(review_csv),
                "review_meta_json": str(review_meta_json),
            },
        }

    ordered = review_df.sort_values(
        ["promotion_score", "research_score", "ops_score", "p2_executed_days_total"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    top = ordered.iloc[0]
    main_row = ordered[ordered["profile"].astype(str) == str(main_profile)].head(1)
    main_score = _safe_float(main_row["promotion_score"].iloc[0]) if not main_row.empty and "promotion_score" in main_row.columns else 0.0
    main_ops_score = _safe_float(main_row["ops_score"].iloc[0]) if not main_row.empty and "ops_score" in main_row.columns else 0.0
    main_p2_objective = _safe_float(main_row["p2_objective_mean"].iloc[0]) if not main_row.empty and "p2_objective_mean" in main_row.columns else 0.0
    top_score = _safe_float(top["promotion_score"])
    top_ops_score = _safe_float(top.get("ops_score"))
    top_p2_objective = _safe_float(top.get("p2_objective_mean"))
    delta = float(top_score - main_score)
    top_profile = str(top["profile"])
    top_decision = str(top.get("decision", ""))
    hard_gate_passed = bool(_safe_int(top.get("promotion_hard_gate_pass", 1), 1)) if top_profile != str(main_profile) else True
    execution_parity = bool(top_ops_score >= main_ops_score and top_p2_objective >= main_p2_objective)
    promote = (
        top_profile != str(main_profile)
        and top_decision == "promote_candidate"
        and delta >= float(min_promote_margin)
        and execution_parity
        and hard_gate_passed
    )
    candidate_p2_days = _safe_int(top.get("p2_executed_days_total")) if top_profile != str(main_profile) else 0
    candidate_p2_gate = bool(_safe_int(top.get("p2_min_days_gate"))) if top_profile != str(main_profile) else False

    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_id": str(review_id),
        "expected_current_default_profile": str(main_profile),
        "final_default_profile": str(top_profile if promote else main_profile),
        "candidate_profile": str("" if top_profile == str(main_profile) else top_profile),
        "decision": "promote" if promote else "keep",
        "change_required": bool(promote and top_profile != str(main_profile)),
        "reason_code": (
            "candidate_outperformed_with_sufficient_p2_support"
            if promote
            else (
                "candidate_p2_gate_failed"
                if top_profile != str(main_profile) and not candidate_p2_gate
                else "candidate_hard_gate_failed"
                if top_profile != str(main_profile) and candidate_p2_gate and not hard_gate_passed
                else "candidate_execution_underperformed"
                if top_profile != str(main_profile) and candidate_p2_gate and not execution_parity
                else "insufficient_edge_or_execution_evidence"
                if top_profile != str(main_profile)
                else "current_main_profile_remains_best"
            )
        ),
        "rationale": (
            "Candidate research and execution evidence both passed the promotion gate."
            if promote
            else (
                "Candidate research score is stronger, but P2 executed-days gate did not pass."
                if top_profile != str(main_profile) and not candidate_p2_gate
                else (
                    "Candidate research score is stronger, but one or more hard execution gates failed."
                    if top_profile != str(main_profile) and candidate_p2_gate and not hard_gate_passed
                    else (
                    "Candidate research score is stronger, but complete P2 replay underperformed the incumbent."
                    if top_profile != str(main_profile) and candidate_p2_gate and not execution_parity
                    else (
                        "Candidate edge over the incumbent is not large enough or execution evidence is not strong enough."
                        if top_profile != str(main_profile)
                        else "Current main profile remains the best supported default profile."
                    )
                    )
                )
            )
        ),
        "evidence": {
            "winner_profile": str(top_profile),
            "winner_promotion_score": float(top_score),
            "winner_research_score": _safe_float(top.get("research_score")),
            "winner_ops_score": _safe_float(top.get("ops_score")),
            "winner_p2_executed_days_total": _safe_int(top.get("p2_executed_days_total")),
            "winner_p2_min_days_gate": _safe_int(top.get("p2_min_days_gate")),
            "winner_decision_hint": top_decision,
            "winner_promotion_hard_gate_pass": bool(hard_gate_passed),
            "winner_promotion_hard_gate_reasons": str(top.get("promotion_hard_gate_reasons", "")),
            "winner_shadow_executed_days_total": _safe_int(top.get("shadow_executed_days_total", 0.0)),
            "winner_shadow_adv_blocked_rows_total": _safe_int(top.get("shadow_adv_blocked_rows_total", 0.0)),
            "winner_shadow_mean_top_industry_weight_pct": _safe_float(top.get("shadow_mean_top_industry_weight_pct", 0.0)),
            "winner_shadow_worst_top_industry_weight_pct": _safe_float(top.get("shadow_worst_top_industry_weight_pct", 0.0)),
            "winner_shadow_mean_top_industry_invested_weight_pct": _safe_float(
                top.get("shadow_mean_top_industry_invested_weight_pct", top.get("shadow_mean_top_industry_weight_pct", 0.0))
            ),
            "winner_shadow_mean_top_industry_nav_weight_pct": _safe_float(top.get("shadow_mean_top_industry_nav_weight_pct", 0.0)),
            "winner_p2_target_weight_sum_mean": _safe_float(top.get("p2_target_weight_sum_mean", 0.0)),
            "winner_p2_nav_not_below_main_windows": _safe_int(top.get("p2_nav_not_below_main_windows", 0)),
            "winner_p2_mdd_not_worse_than_main_windows": _safe_int(top.get("p2_mdd_not_worse_than_main_windows", 0)),
            "winner_shadow_mean_industry_hhi": _safe_float(top.get("shadow_mean_industry_hhi", 0.0)),
            "main_profile_score": float(main_score),
            "main_ops_score": float(main_ops_score),
            "main_p2_objective_mean": float(main_p2_objective),
            "winner_p2_objective_mean": float(top_p2_objective),
            "candidate_execution_parity_passed": bool(execution_parity),
            "candidate_promotion_hard_gate_passed": bool(hard_gate_passed),
            "main_score": float(main_score),
            "candidate_score": float(top_score if top_profile != str(main_profile) else main_score),
            "score_margin": float(delta),
            "candidate_p2_executed_days_total": int(candidate_p2_days),
            "min_p2_executed_days": int(min_p2_executed_days),
            "candidate_p2_gate_passed": bool(candidate_p2_gate),
        },
        "artifacts": {
            "review_csv": str(review_csv),
            "review_meta_json": str(review_meta_json),
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description="量化 profile 升档评审")
    p.add_argument("--config", type=str, default=str(PROFILE_FILE), help="profile 配置文件")
    p.add_argument("--profiles", type=str, default="", help="要评审的 profile，逗号分隔")
    p.add_argument("--main-profile", type=str, default="", help="当前主档；默认读取 config.default_profile")
    p.add_argument(
        "--rolling-summary",
        type=str,
        default=str(BACKTEST_DIR / "quant_profile_rolling_compare_summary_latest.csv"),
        help="rolling compare summary 文件",
    )
    p.add_argument("--p2-summary", type=str, default="", help="可选 P2 replay summary；为空时回落到 ledger 汇总")
    p.add_argument(
        "--shadow-diagnosis",
        type=str,
        default=str(BACKTEST_DIR / "quant_p2_shadow_diagnosis_latest.csv"),
        help="可选 P2 shadow diagnosis 文件，用于 ADV/行业集中硬门槛",
    )
    p.add_argument(
        "--ledger-glob",
        type=str,
        default="*paper_replay_*ledger.csv",
        help="当未提供 p2-summary 时，用于搜集 ledger 的 glob；建议配合 profiles 使用",
    )
    p.add_argument("--min-p2-executed-days", type=int, default=20, help="升档前要求的最少 P2 执行天数")
    p.add_argument("--min-promote-margin", type=float, default=1.0, help="候选档超过当前主档所需的最小 promotion_score 差值")
    p.add_argument("--write-latest", action="store_true", help="写入 latest review/decision 快捷文件")
    args = p.parse_args()

    config_file = Path(args.config).resolve()
    if not config_file.exists():
        raise FileNotFoundError(f"未找到 config: {config_file}")
    root = _load_root_config(config_file)
    profiles = _parse_profiles(args.profiles, root)
    if not profiles:
        raise RuntimeError("未解析到任何 profile")
    main_profile = str(args.main_profile or root.get("default_profile", profiles[0]))

    research_df = _load_research_summary(Path(args.rolling_summary).resolve(), profiles)
    p2_summary_file = [Path(x.strip()).resolve() for x in str(args.p2_summary).split(",") if x.strip()] if args.p2_summary else None
    p2_df, ledgers = _load_or_build_p2_summary(
        p2_summary_file=p2_summary_file,
        profiles=profiles,
        ledger_glob=args.ledger_glob,
        min_days=max(1, int(args.min_p2_executed_days)),
        main_profile=main_profile,
    )
    shadow_df = _load_shadow_diagnosis(Path(args.shadow_diagnosis).resolve() if args.shadow_diagnosis else None, profiles)
    if not shadow_df.empty and len(shadow_df.columns) > 1:
        p2_df = p2_df.merge(shadow_df, on="profile", how="left")
    review_df = _build_promotion_review(research_df, p2_df, main_profile=main_profile)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_id = f"quant_profile_promotion_review_{ts}"
    review_file = BACKTEST_DIR / f"quant_profile_promotion_review_{ts}.csv"
    meta_file = BACKTEST_DIR / f"quant_profile_promotion_review_{ts}.json"
    decision_file = BACKTEST_DIR / f"promotion_decision_{ts}.json"
    review_df.to_csv(review_file, index=False, encoding="utf-8-sig")
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profiles": profiles,
        "main_profile": main_profile,
        "rolling_summary": str(Path(args.rolling_summary).resolve()),
        "p2_summary": [str(x) for x in p2_summary_file] if isinstance(p2_summary_file, list) else (str(p2_summary_file) if p2_summary_file else ""),
        "shadow_diagnosis": str(Path(args.shadow_diagnosis).resolve()) if args.shadow_diagnosis else "",
        "ledger_glob": str(args.ledger_glob),
        "matched_ledgers": [str(x) for x in ledgers],
        "min_p2_executed_days": int(args.min_p2_executed_days),
        "min_promote_margin": float(args.min_promote_margin),
    }
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    decision = _build_promotion_decision(
        review_df,
        main_profile=main_profile,
        min_promote_margin=float(args.min_promote_margin),
        review_id=review_id,
        min_p2_executed_days=int(args.min_p2_executed_days),
        review_csv=str(review_file),
        review_meta_json=str(meta_file),
    )
    validate_promotion_decision_payload(decision)
    decision_file.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    if bool(args.write_latest):
        review_df.to_csv(BACKTEST_DIR / "quant_profile_promotion_review_latest.csv", index=False, encoding="utf-8-sig")
        meta_file_latest = BACKTEST_DIR / "quant_profile_promotion_review_latest.json"
        meta_file_latest.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        decision_latest = BACKTEST_DIR / "promotion_decision_latest.json"
        decision_latest.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("Quant Profile Promotion Review")
    print("=" * 72)
    print(review_df.to_string(index=False))
    print(f"\nreview_file={review_file}")
    print(f"meta_file={meta_file}")
    print(f"decision_file={decision_file}")
    print(f"decision={decision['decision']} final_default={decision['final_default_profile']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
