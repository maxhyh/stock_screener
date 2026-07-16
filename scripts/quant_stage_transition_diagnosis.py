#!/usr/bin/env python3
"""Diagnose alpha attrition across persisted research-stage snapshots.

The input is produced by `daily_ml_select.py` when
`MFTS_WRITE_RESEARCH_STAGE_SNAPSHOTS=true`. This report compares each stage
and each adjacent transition so we can see whether a gate removes weak names
or accidentally drops the names that later outperform.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

from quant_alpha_execution_attribution import (  # noqa: E402
    _attach_forward_returns,
    _load_industry_map,
    _load_market_bars,
    _load_ods_market_bars,
    _parse_date,
)
from utils.code_utils import normalize_ts_code_series  # noqa: E402

BACKTEST_DIR = BASE_DIR / "output" / "backtest"

DEFAULT_STAGE_ORDER = [
    "raw_scored_post_indicator",
    "tradability_filter_pool",
    "liquidity_filter_pool",
    "quality_filter_pool",
    "filtered_signal_pool",
    "ranking_pool_pre_pretrade",
    "ranking_pool_post_pretrade",
    "optimizer_ranked_pool",
    "final_target_weight",
]

DEFAULT_SCORE_COLS = [
    "ml_score",
    "hybrid_score",
    "refactor_score",
    "execution_score",
    "liquidity_score",
    "tradability_safe_score",
    "exit_trap_safe_score",
    "tradability_adjusted_score",
    "portfolio_rank_score",
    "target_weight",
]

DEFAULT_GATE_SCORE_COLS = ["target_weight", "portfolio_rank_score"]


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _discover_paths(raw_glob: str) -> list[Path]:
    paths: list[Path] = []
    for part in str(raw_glob or "").split(","):
        part = part.strip()
        if not part:
            continue
        paths.extend(Path(p) for p in glob.glob(part))
    return sorted(set(paths))


def _top_industry_label(df: pd.DataFrame) -> str:
    if df.empty or "industry" not in df.columns:
        return ""
    s = df["industry"].fillna("未知").astype(str).str.strip().replace({"": "未知"})
    if s.empty:
        return ""
    return str(s.value_counts().index[0])


def _top_industry_pct(df: pd.DataFrame) -> float:
    if df.empty or "industry" not in df.columns:
        return 0.0
    s = df["industry"].fillna("未知").astype(str).str.strip().replace({"": "未知"})
    if s.empty:
        return 0.0
    return float(s.value_counts(normalize=True).iloc[0] * 100.0)


def _top_filter_flag(df: pd.DataFrame) -> tuple[str, int, float]:
    if df.empty:
        return "", 0, 0.0
    preferred = [
        "hard_limit_flag",
        "overheat_flag",
        "vol_anomaly_low_flag",
        "vol_anomaly_high_flag",
        "signal_risk_blocked",
    ]
    candidates = [col for col in preferred if col in df.columns]
    if not any(col.startswith("vol_anomaly_") for col in candidates) and "vol_anomaly_flag" in df.columns:
        candidates.append("vol_anomaly_flag")
    if not candidates:
        return "", 0, 0.0
    counts: dict[str, int] = {}
    for col in candidates:
        vals = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        counts[col] = int(vals.gt(0).sum())
    reason, count = max(counts.items(), key=lambda kv: kv[1])
    if count <= 0:
        return "", 0, 0.0
    return str(reason), int(count), float(count / max(len(df), 1) * 100.0)


def _load_stage_snapshots(paths: list[Path], *, start: str = "", end: str = "") -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            df = pd.read_csv(path, low_memory=False).copy()
        except Exception:
            continue
        if df.empty or "research_stage" not in df.columns:
            continue
        if "日期" in df.columns:
            dates = pd.to_datetime(df["日期"], errors="coerce")
        else:
            dates = pd.Series(pd.NaT, index=df.index)
        if dates.notna().any():
            df["signal_date"] = dates.dt.normalize()
        else:
            raw = path.stem.replace("research_stages_", "", 1)
            dt = pd.to_datetime(raw, errors="coerce")
            if pd.isna(dt):
                continue
            df["signal_date"] = pd.Timestamp(dt).normalize()
        if "代码" not in df.columns:
            continue
        df["code"] = normalize_ts_code_series(df["代码"])
        df = df[df["code"] != ""].copy()
        if df.empty:
            continue
        df["_source_file"] = str(path)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if start:
        s = _parse_date(start)
        if s is not None:
            out = out[out["signal_date"] >= s].copy()
    if end:
        e = _parse_date(end)
        if e is not None:
            out = out[out["signal_date"] <= e].copy()
    if "建议持有天数" not in out.columns:
        out["建议持有天数"] = np.nan
    return out.reset_index(drop=True)


def _attach_returns_and_industry(df: pd.DataFrame, *, market_file: Path | None, forward_days: int) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["建议持有天数"] = pd.to_numeric(out.get("建议持有天数", np.nan), errors="coerce").fillna(
        max(1, int(forward_days))
    )
    if market_file is None:
        bars, _ = _load_ods_market_bars(out, max(1, int(forward_days)))
    else:
        bars = _load_market_bars(market_file)
    out = _attach_forward_returns(out, bars, default_horizon=max(1, int(forward_days)))
    industry_map = _load_industry_map(out["signal_date"].max())
    mapped = out["code"].map(industry_map)
    if "行业" in out.columns:
        fallback = out["行业"].fillna("").astype(str).str.strip()
        mapped = mapped.where(mapped.notna() & mapped.astype(str).str.strip().ne(""), fallback)
    out["industry"] = mapped.fillna("未知").astype(str).str.strip().replace({"": "未知"})
    return out


def _subset_by_keys(df: pd.DataFrame, keys: set[tuple[pd.Timestamp, str]]) -> pd.DataFrame:
    if df.empty or not keys:
        return df.iloc[0:0].copy()
    idx = list(zip(pd.to_datetime(df["signal_date"]).dt.normalize(), df["code"].astype(str)))
    mask = pd.Series([k in keys for k in idx], index=df.index)
    return df[mask].copy()


def _keys(df: pd.DataFrame) -> set[tuple[pd.Timestamp, str]]:
    if df.empty:
        return set()
    return set(zip(pd.to_datetime(df["signal_date"]).dt.normalize(), df["code"].astype(str)))


def _mean_return_pct(df: pd.DataFrame) -> float:
    valid = df.dropna(subset=["forward_return"]) if "forward_return" in df.columns else df.iloc[0:0]
    return float(valid["forward_return"].mean() * 100.0) if not valid.empty else 0.0


def _hit_rate_pct(df: pd.DataFrame) -> float:
    valid = df.dropna(subset=["forward_return"]) if "forward_return" in df.columns else df.iloc[0:0]
    return float((valid["forward_return"] > 0).mean() * 100.0) if not valid.empty else 0.0


def _top_by_stage_rank(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if df.empty:
        return df.iloc[0:0].copy()
    if "stage_rank" in df.columns:
        rank = pd.to_numeric(df["stage_rank"], errors="coerce")
        work = df.assign(_stage_rank=rank).dropna(subset=["_stage_rank"]).copy()
        if not work.empty:
            return work.sort_values(["signal_date", "_stage_rank"], ascending=[True, True]).groupby(
                "signal_date", group_keys=False
            ).head(max(1, int(top_n)))
    return df.groupby("signal_date", group_keys=False).head(max(1, int(top_n))).copy()


def _top_by_score(df: pd.DataFrame, score_col: str, top_n: int, *, ascending: bool = False) -> pd.DataFrame:
    if df.empty or score_col not in df.columns:
        return df.iloc[0:0].copy()
    work = df.copy()
    work["_score"] = pd.to_numeric(work[score_col], errors="coerce")
    work = work.dropna(subset=["_score"])
    if work.empty:
        return work
    return (
        work.sort_values(["signal_date", "_score"], ascending=[True, ascending])
        .groupby("signal_date", group_keys=False)
        .head(max(1, int(top_n)))
        .drop(columns=["_score"], errors="ignore")
    )


def _rank_ic_mean(df: pd.DataFrame, score_col: str) -> float:
    if df.empty or score_col not in df.columns or "forward_return" not in df.columns:
        return 0.0
    vals: list[float] = []
    for _, g in df.groupby("signal_date"):
        work = g[[score_col, "forward_return"]].copy()
        work[score_col] = pd.to_numeric(work[score_col], errors="coerce")
        work["forward_return"] = pd.to_numeric(work["forward_return"], errors="coerce")
        work = work.dropna()
        if len(work) < 3:
            continue
        if work[score_col].nunique(dropna=True) < 2 or work["forward_return"].nunique(dropna=True) < 2:
            continue
        ic = work[score_col].corr(work["forward_return"], method="spearman")
        if pd.notna(ic) and np.isfinite(float(ic)):
            vals.append(float(ic))
    return float(np.mean(vals)) if vals else 0.0


def build_stage_summary(df: pd.DataFrame, *, top_n: int, stage_order: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    order = {stage: i for i, stage in enumerate(stage_order)}
    for stage, g in df.groupby("research_stage", dropna=False):
        valid = g.dropna(subset=["forward_return"]).copy()
        top = _top_by_stage_rank(g, top_n=top_n)
        rows.append(
            {
                "research_stage": str(stage),
                "stage_order": int(order.get(str(stage), 999)),
                "rows": int(len(g)),
                "valid_forward_rows": int(len(valid)),
                "days": int(g["signal_date"].nunique()),
                "rows_per_day_mean": float(g.groupby("signal_date")["code"].count().mean()) if len(g) else 0.0,
                "mean_forward_return_pct": _mean_return_pct(g),
                "median_forward_return_pct": float(valid["forward_return"].median() * 100.0) if not valid.empty else 0.0,
                "hit_rate_pct": _hit_rate_pct(g),
                "stage_rank_top_n": int(top_n),
                "stage_rank_top_mean_forward_return_pct": _mean_return_pct(top),
                "stage_rank_top_hit_rate_pct": _hit_rate_pct(top),
                "top_industry_label": _top_industry_label(g),
                "top_industry_count_weight_pct": _top_industry_pct(g),
                "stage_rank_top_industry_label": _top_industry_label(top),
                "stage_rank_top_industry_count_weight_pct": _top_industry_pct(top),
                "target_weight_sum_mean": float(
                    pd.to_numeric(g.get("target_weight", pd.Series(0.0, index=g.index)), errors="coerce")
                    .fillna(0.0)
                    .groupby(g["signal_date"])
                    .sum()
                    .mean()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["stage_order", "research_stage"]).reset_index(drop=True)


def build_score_stage_summary(
    df: pd.DataFrame,
    *,
    score_cols: list[str],
    top_n: int,
    stage_order: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if df.empty:
        return pd.DataFrame(rows)
    order = {stage: i for i, stage in enumerate(stage_order)}
    for stage, g in df.groupby("research_stage", dropna=False):
        stage_name = str(stage)
        valid = g.dropna(subset=["forward_return"]) if "forward_return" in g.columns else g.iloc[0:0]
        for score_col in score_cols:
            if score_col not in g.columns:
                continue
            score = pd.to_numeric(g[score_col], errors="coerce")
            if score.notna().sum() <= 0:
                continue
            top = _top_by_score(g, score_col, top_n=top_n, ascending=False)
            bottom = _top_by_score(g, score_col, top_n=top_n, ascending=True)
            rows.append(
                {
                    "research_stage": stage_name,
                    "stage_order": int(order.get(stage_name, 999)),
                    "score_col": str(score_col),
                    "rows": int(len(g)),
                    "valid_forward_rows": int(len(valid)),
                    "score_valid_rows": int(score.notna().sum()),
                    "days": int(g["signal_date"].nunique()),
                    "top_n": int(top_n),
                    "all_mean_forward_return_pct": _mean_return_pct(g),
                    "top_mean_forward_return_pct": _mean_return_pct(top),
                    "bottom_mean_forward_return_pct": _mean_return_pct(bottom),
                    "top_minus_all_pct": float(_mean_return_pct(top) - _mean_return_pct(g)),
                    "top_minus_bottom_pct": float(_mean_return_pct(top) - _mean_return_pct(bottom)),
                    "rank_ic_mean": _rank_ic_mean(g, score_col),
                    "top_hit_rate_pct": _hit_rate_pct(top),
                    "bottom_hit_rate_pct": _hit_rate_pct(bottom),
                    "top_industry_label": _top_industry_label(top),
                    "top_industry_count_weight_pct": _top_industry_pct(top),
                }
            )
    if not rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(rows).sort_values(["stage_order", "research_stage", "score_col"]).reset_index(drop=True)


def build_transition_diagnosis(
    df: pd.DataFrame,
    *,
    stage_order: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    present = set(df["research_stage"].astype(str).dropna().unique()) if "research_stage" in df.columns else set()
    stage_order = [stage for stage in stage_order if stage in present]
    for from_stage, to_stage in zip(stage_order, stage_order[1:]):
        source = df[df["research_stage"].astype(str).eq(from_stage)].copy()
        dest = df[df["research_stage"].astype(str).eq(to_stage)].copy()
        if source.empty and dest.empty:
            continue
        source_keys = _keys(source)
        dest_keys = _keys(dest)
        kept_keys = source_keys & dest_keys
        dropped_keys = source_keys - dest_keys
        gained_keys = dest_keys - source_keys
        kept = _subset_by_keys(source, kept_keys)
        dropped = _subset_by_keys(source, dropped_keys)
        gained = _subset_by_keys(dest, gained_keys)
        dropped_flag, dropped_flag_count, dropped_flag_rate = _top_filter_flag(dropped)
        for date in sorted(set(source["signal_date"].dropna().unique()).union(dest["signal_date"].dropna().unique())):
            sd = source[source["signal_date"].eq(date)].copy()
            dd = dest[dest["signal_date"].eq(date)].copy()
            day_source_keys = _keys(sd)
            day_dest_keys = _keys(dd)
            day_kept = _subset_by_keys(sd, day_source_keys & day_dest_keys)
            day_dropped = _subset_by_keys(sd, day_source_keys - day_dest_keys)
            day_gained = _subset_by_keys(dd, day_dest_keys - day_source_keys)
            day_flag, day_flag_count, day_flag_rate = _top_filter_flag(day_dropped)
            daily_rows.append(
                {
                    "signal_date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                    "from_stage": from_stage,
                    "to_stage": to_stage,
                    "from_rows": int(len(sd)),
                    "to_rows": int(len(dd)),
                    "kept_rows": int(len(day_kept)),
                    "dropped_rows": int(len(day_dropped)),
                    "gained_rows": int(len(day_gained)),
                    "keep_rate_pct": float(len(day_kept) / max(len(sd), 1) * 100.0),
                    "from_mean_forward_return_pct": _mean_return_pct(sd),
                    "to_mean_forward_return_pct": _mean_return_pct(dd),
                    "kept_mean_forward_return_pct": _mean_return_pct(day_kept),
                    "dropped_mean_forward_return_pct": _mean_return_pct(day_dropped),
                    "gained_mean_forward_return_pct": _mean_return_pct(day_gained),
                    "dropped_minus_kept_pct": float(_mean_return_pct(day_dropped) - _mean_return_pct(day_kept)),
                    "dropped_top_industry_label": _top_industry_label(day_dropped),
                    "dropped_top_industry_count_weight_pct": _top_industry_pct(day_dropped),
                    "kept_top_industry_label": _top_industry_label(day_kept),
                    "kept_top_industry_count_weight_pct": _top_industry_pct(day_kept),
                    "dropped_top_filter_flag": day_flag,
                    "dropped_top_filter_flag_count": int(day_flag_count),
                    "dropped_top_filter_flag_rate_pct": float(day_flag_rate),
                }
            )
        summary_rows.append(
            {
                "from_stage": from_stage,
                "to_stage": to_stage,
                "days": int(max(source["signal_date"].nunique(), dest["signal_date"].nunique())),
                "from_rows": int(len(source)),
                "to_rows": int(len(dest)),
                "kept_rows": int(len(kept)),
                "dropped_rows": int(len(dropped)),
                "gained_rows": int(len(gained)),
                "keep_rate_pct": float(len(kept) / max(len(source), 1) * 100.0),
                "from_mean_forward_return_pct": _mean_return_pct(source),
                "to_mean_forward_return_pct": _mean_return_pct(dest),
                "kept_mean_forward_return_pct": _mean_return_pct(kept),
                "dropped_mean_forward_return_pct": _mean_return_pct(dropped),
                "gained_mean_forward_return_pct": _mean_return_pct(gained),
                "dropped_minus_kept_pct": float(_mean_return_pct(dropped) - _mean_return_pct(kept)),
                "dropped_top_industry_label": _top_industry_label(dropped),
                "dropped_top_industry_count_weight_pct": _top_industry_pct(dropped),
                "kept_top_industry_label": _top_industry_label(kept),
                "kept_top_industry_count_weight_pct": _top_industry_pct(kept),
                "dropped_top_filter_flag": dropped_flag,
                "dropped_top_filter_flag_count": int(dropped_flag_count),
                "dropped_top_filter_flag_rate_pct": float(dropped_flag_rate),
            }
        )
    return pd.DataFrame(summary_rows), pd.DataFrame(daily_rows)


def _score_gate_reasons(row: pd.Series) -> list[str]:
    reasons: list[str] = []
    if _safe_float(row.get("top_mean_forward_return_pct", 0.0)) <= 0.0:
        reasons.append("top_mean_not_positive")
    if _safe_float(row.get("top_minus_all_pct", 0.0)) <= 0.0:
        reasons.append("top_not_above_stage_average")
    if _safe_float(row.get("top_minus_bottom_pct", 0.0)) <= 0.0:
        reasons.append("top_not_above_bottom_bucket")
    if _safe_float(row.get("rank_ic_mean", 0.0)) <= 0.0:
        reasons.append("rank_ic_not_positive")
    return reasons


def build_alpha_decay_summary(
    stage_summary: pd.DataFrame,
    transition_summary: pd.DataFrame,
    score_stage_summary: pd.DataFrame,
    *,
    gate_score_cols: list[str] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    gate_cols = {str(c) for c in (gate_score_cols or DEFAULT_GATE_SCORE_COLS)}

    if not transition_summary.empty:
        work = transition_summary.copy()
        work["_dropped_minus_kept"] = pd.to_numeric(work.get("dropped_minus_kept_pct", 0.0), errors="coerce").fillna(0.0)
        work["_from_mean"] = pd.to_numeric(work.get("from_mean_forward_return_pct", 0.0), errors="coerce").fillna(0.0)
        work["_to_mean"] = pd.to_numeric(work.get("to_mean_forward_return_pct", 0.0), errors="coerce").fillna(0.0)
        harmful = work[(work["_dropped_minus_kept"] > 0.0) & (work["_to_mean"] < work["_from_mean"])].copy()
        if not harmful.empty:
            worst = harmful.sort_values("_dropped_minus_kept", ascending=False).iloc[0]
            rows.append(
                {
                    "summary_type": "transition_alpha_loss",
                    "verdict": "alpha_damaging_transition",
                    "research_stage": "",
                    "from_stage": str(worst.get("from_stage", "")),
                    "to_stage": str(worst.get("to_stage", "")),
                    "score_col": "",
                    "mean_forward_return_pct": _safe_float(worst.get("to_mean_forward_return_pct", 0.0)),
                    "top_mean_forward_return_pct": 0.0,
                    "top_minus_all_pct": 0.0,
                    "top_minus_bottom_pct": 0.0,
                    "rank_ic_mean": 0.0,
                    "dropped_minus_kept_pct": _safe_float(worst.get("dropped_minus_kept_pct", 0.0)),
                    "keep_rate_pct": _safe_float(worst.get("keep_rate_pct", 0.0)),
                    "reason": (
                        f"dropped names beat kept names by "
                        f"{_safe_float(worst.get('dropped_minus_kept_pct', 0.0)):.4f} pct while stage mean fell "
                        f"from {_safe_float(worst.get('from_mean_forward_return_pct', 0.0)):.4f}% to "
                        f"{_safe_float(worst.get('to_mean_forward_return_pct', 0.0)):.4f}%"
                    ),
                }
            )

    if not score_stage_summary.empty:
        score_work = score_stage_summary.copy()
        score_work["_top"] = pd.to_numeric(
            score_work.get("top_mean_forward_return_pct", 0.0), errors="coerce"
        ).fillna(0.0)
        score_work["_top_all"] = pd.to_numeric(score_work.get("top_minus_all_pct", 0.0), errors="coerce").fillna(0.0)
        score_work["_top_bottom"] = pd.to_numeric(
            score_work.get("top_minus_bottom_pct", 0.0), errors="coerce"
        ).fillna(0.0)
        score_work["_ic"] = pd.to_numeric(score_work.get("rank_ic_mean", 0.0), errors="coerce").fillna(0.0)
        later_stages = {"ranking_pool_post_pretrade", "optimizer_ranked_pool", "final_target_weight"}
        component = score_work[
            score_work["research_stage"].astype(str).isin(later_stages)
            & ~score_work["score_col"].astype(str).isin(gate_cols)
            & (score_work["_top"] > 0.0)
            & (score_work["_top_all"] > 0.0)
            & (score_work["_top_bottom"] > 0.0)
            & (score_work["_ic"] > 0.0)
        ].copy()
        if not component.empty:
            component["_score_strength"] = component["_top"] + component["_top_all"] + component["_top_bottom"] + 10.0 * component["_ic"]
            for _, best in component.sort_values("_score_strength", ascending=False).head(5).iterrows():
                rows.append(
                    {
                        "summary_type": "component_score_survives",
                        "verdict": "hypothesis_only_not_profile_gate",
                        "research_stage": str(best.get("research_stage", "")),
                        "from_stage": "",
                        "to_stage": "",
                        "score_col": str(best.get("score_col", "")),
                        "mean_forward_return_pct": _safe_float(best.get("all_mean_forward_return_pct", 0.0)),
                        "top_mean_forward_return_pct": _safe_float(best.get("top_mean_forward_return_pct", 0.0)),
                        "top_minus_all_pct": _safe_float(best.get("top_minus_all_pct", 0.0)),
                        "top_minus_bottom_pct": _safe_float(best.get("top_minus_bottom_pct", 0.0)),
                        "rank_ic_mean": _safe_float(best.get("rank_ic_mean", 0.0)),
                        "dropped_minus_kept_pct": 0.0,
                        "keep_rate_pct": 0.0,
                        "reason": "component score has positive top bucket, spread, and RankIC inside a late-stage pool",
                    }
                )

        gate = score_work[
            score_work["research_stage"].astype(str).eq("final_target_weight")
            & score_work["score_col"].astype(str).isin(gate_cols)
        ].copy()
        for _, row in gate.sort_values("score_col").iterrows():
            reasons = _score_gate_reasons(row)
            rows.append(
                {
                    "summary_type": "profile_gate_score",
                    "verdict": "gate_score_passed" if not reasons else "gate_score_failed",
                    "research_stage": str(row.get("research_stage", "")),
                    "from_stage": "",
                    "to_stage": "",
                    "score_col": str(row.get("score_col", "")),
                    "mean_forward_return_pct": _safe_float(row.get("all_mean_forward_return_pct", 0.0)),
                    "top_mean_forward_return_pct": _safe_float(row.get("top_mean_forward_return_pct", 0.0)),
                    "top_minus_all_pct": _safe_float(row.get("top_minus_all_pct", 0.0)),
                    "top_minus_bottom_pct": _safe_float(row.get("top_minus_bottom_pct", 0.0)),
                    "rank_ic_mean": _safe_float(row.get("rank_ic_mean", 0.0)),
                    "dropped_minus_kept_pct": 0.0,
                    "keep_rate_pct": 0.0,
                    "reason": ",".join(reasons) if reasons else "final profile gate score passed late-stage smoke thresholds",
                }
            )

    if rows:
        has_gate_pass = any(r.get("summary_type") == "profile_gate_score" and r.get("verdict") == "gate_score_passed" for r in rows)
        has_alpha_loss = any(r.get("summary_type") == "transition_alpha_loss" for r in rows)
        if has_alpha_loss and not has_gate_pass:
            verdict = "ranking_alpha_decay_before_p2"
            reason = "a damaging transition exists and final profile gate scores do not pass"
        elif has_gate_pass:
            verdict = "profile_gate_scores_need_p2_smoke"
            reason = "at least one final profile gate score passed; execution smoke is the next gate"
        else:
            verdict = "no_late_stage_component_edge_found"
            reason = "no obvious late-stage component score or transition alpha-loss summary was detected"
        rows.insert(
            0,
            {
                "summary_type": "overall",
                "verdict": verdict,
                "research_stage": "",
                "from_stage": "",
                "to_stage": "",
                "score_col": "",
                "mean_forward_return_pct": 0.0,
                "top_mean_forward_return_pct": 0.0,
                "top_minus_all_pct": 0.0,
                "top_minus_bottom_pct": 0.0,
                "rank_ic_mean": 0.0,
                "dropped_minus_kept_pct": 0.0,
                "keep_rate_pct": 0.0,
                "reason": reason,
            },
        )

    return pd.DataFrame(rows)


def build_report(
    *,
    stage_glob: str,
    market_file: Path | None = None,
    start: str = "",
    end: str = "",
    forward_days: int = 8,
    top_n: int = 20,
    stage_order: list[str] | None = None,
    score_cols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    paths = _discover_paths(stage_glob)
    if not paths:
        raise RuntimeError("未找到 research stage snapshot 文件")
    stages = stage_order or DEFAULT_STAGE_ORDER
    df = _load_stage_snapshots(paths, start=start, end=end)
    if df.empty:
        raise RuntimeError("research stage snapshot 为空")
    df = _attach_returns_and_industry(df, market_file=market_file, forward_days=max(1, int(forward_days)))
    stage_summary = build_stage_summary(df, top_n=max(1, int(top_n)), stage_order=stages)
    score_stage_summary = build_score_stage_summary(
        df,
        score_cols=score_cols or DEFAULT_SCORE_COLS,
        top_n=max(1, int(top_n)),
        stage_order=stages,
    )
    transition_summary, transition_daily = build_transition_diagnosis(df, stage_order=stages)
    alpha_decay_summary = build_alpha_decay_summary(
        stage_summary,
        transition_summary,
        score_stage_summary,
        gate_score_cols=DEFAULT_GATE_SCORE_COLS,
    )
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stage_glob": stage_glob,
        "stage_file_count": int(len(paths)),
        "rows": int(len(df)),
        "signal_start": str(df["signal_date"].min().date()),
        "signal_end": str(df["signal_date"].max().date()),
        "forward_days_default": int(forward_days),
        "top_n": int(top_n),
        "stage_order": stages,
    }
    return stage_summary, transition_summary, transition_daily, score_stage_summary, alpha_decay_summary, meta


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnose alpha attrition between research-stage snapshots")
    p.add_argument("--stage-glob", required=True, help="research_stages CSV glob(s), comma separated")
    p.add_argument("--market-file", default="", help="optional explicit market parquet; default is shared ODS")
    p.add_argument("--start", default="", help="signal start date")
    p.add_argument("--end", default="", help="signal end date")
    p.add_argument("--forward-days", type=int, default=8, help="default forward open-to-open horizon")
    p.add_argument("--top-n", type=int, default=20, help="stage-rank top-N per date")
    p.add_argument("--label", default="", help="artifact/profile label")
    p.add_argument(
        "--stage-order",
        default=",".join(DEFAULT_STAGE_ORDER),
        help="comma-separated ordered stage names",
    )
    p.add_argument(
        "--score-cols",
        default=",".join(DEFAULT_SCORE_COLS),
        help="comma-separated score columns to evaluate inside each stage",
    )
    p.add_argument("--write-latest", action="store_true", help="write latest shortcut files")
    args = p.parse_args()

    stage_order = [s.strip() for s in str(args.stage_order or "").split(",") if s.strip()]
    score_cols = [s.strip() for s in str(args.score_cols or "").split(",") if s.strip()]
    stage_summary, transition_summary, transition_daily, score_stage_summary, alpha_decay_summary, meta = build_report(
        stage_glob=str(args.stage_glob),
        market_file=Path(args.market_file).resolve() if args.market_file else None,
        start=str(args.start or ""),
        end=str(args.end or ""),
        forward_days=max(1, int(args.forward_days)),
        top_n=max(1, int(args.top_n)),
        stage_order=stage_order or DEFAULT_STAGE_ORDER,
        score_cols=score_cols or DEFAULT_SCORE_COLS,
    )

    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{args.label}" if args.label else ""
    safe_suffix = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in suffix)
    base = BACKTEST_DIR / f"quant_stage_transition_diagnosis{safe_suffix}_{ts}"
    stage_csv = base.with_name(base.name + "_stage_summary.csv")
    transition_csv = base.with_name(base.name + "_transition_summary.csv")
    daily_csv = base.with_name(base.name + "_transition_daily.csv")
    score_csv = base.with_name(base.name + "_score_stage_summary.csv")
    alpha_decay_csv = base.with_name(base.name + "_alpha_decay_summary.csv")
    json_path = base.with_suffix(".json")
    stage_summary.to_csv(stage_csv, index=False, encoding="utf-8-sig")
    transition_summary.to_csv(transition_csv, index=False, encoding="utf-8-sig")
    transition_daily.to_csv(daily_csv, index=False, encoding="utf-8-sig")
    score_stage_summary.to_csv(score_csv, index=False, encoding="utf-8-sig")
    alpha_decay_summary.to_csv(alpha_decay_csv, index=False, encoding="utf-8-sig")
    payload = {
        **meta,
        "stage_summary": stage_summary.to_dict(orient="records"),
        "score_stage_summary": score_stage_summary.to_dict(orient="records"),
        "alpha_decay_summary": alpha_decay_summary.to_dict(orient="records"),
        "transition_summary": transition_summary.to_dict(orient="records"),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        latest_base = BACKTEST_DIR / f"quant_stage_transition_diagnosis_latest{safe_suffix}"
        stage_summary.to_csv(latest_base.with_name(latest_base.name + "_stage_summary.csv"), index=False, encoding="utf-8-sig")
        transition_summary.to_csv(
            latest_base.with_name(latest_base.name + "_transition_summary.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        transition_daily.to_csv(
            latest_base.with_name(latest_base.name + "_transition_daily.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        score_stage_summary.to_csv(
            latest_base.with_name(latest_base.name + "_score_stage_summary.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        alpha_decay_summary.to_csv(
            latest_base.with_name(latest_base.name + "_alpha_decay_summary.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        latest_base.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[stage_summary]")
    print(stage_summary.to_string(index=False))
    print("\n[transition_summary]")
    print(transition_summary.to_string(index=False))
    if not score_stage_summary.empty:
        print("\n[score_stage_summary]")
        print(score_stage_summary.to_string(index=False))
    if not alpha_decay_summary.empty:
        print("\n[alpha_decay_summary]")
        print(alpha_decay_summary.to_string(index=False))
    print(f"stage_summary_csv={stage_csv}")
    print(f"transition_summary_csv={transition_csv}")
    print(f"transition_daily_csv={daily_csv}")
    print(f"score_stage_summary_csv={score_csv}")
    print(f"alpha_decay_summary_csv={alpha_decay_csv}")
    print(f"stage_transition_json={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
