#!/usr/bin/env python3
"""Capacity-feasible alpha diagnostics for profile daily/stage artifacts.

This report asks a narrower question than raw alpha attribution: does any
candidate score still select positive forward-return names after the existing
profile capacity, industry, reserve, and exit-trap constraints are applied?
It is a pre-profile diagnostic, not promotion evidence.
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

from core.platform.portfolio_engine import PortfolioConstraints, build_portfolio_decision  # noqa: E402
from quant_alpha_execution_attribution import (  # noqa: E402
    _attach_forward_returns,
    _discover_daily_paths,
    _load_daily_recommendations,
    _load_industry_map,
    _load_market_bars,
    _load_ods_market_bars,
    _parse_date,
)
from quant_stage_transition_diagnosis import (  # noqa: E402
    _attach_returns_and_industry,
    _discover_paths,
    _load_stage_snapshots,
)
from utils.code_utils import normalize_ts_code_series  # noqa: E402

PROFILE_FILE = BASE_DIR / "config" / "quant_live_profiles.json"
BACKTEST_DIR = BASE_DIR / "output" / "backtest"

DEFAULT_SCORE_COLS = [
    "target_weight",
    "portfolio_rank_score",
    "target_blend_score",
    "liquidity_score",
    "exit_trap_safe_score",
    "tradability_safe_score",
    "reserve_safe_score",
    "adv_capacity_score",
    "hybrid_score",
    "ml_score",
    "重构分",
    "综合分",
    "流动性分",
    "ML评分",
]

DEFAULT_STAGE_PRIORITY = [
    "optimizer_ranked_pool",
    "ranking_pool_post_pretrade",
    "filtered_signal_pool",
    "final_target_weight",
]

DEFAULT_PRIMARY_PROMOTION_MODES = ["keep"]


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _parse_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return bool(value)
    raw = str(value).strip().lower()
    if not raw:
        return bool(default)
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _parse_list(raw: str | list[str] | tuple[str, ...] | None, default: list[str]) -> list[str]:
    if raw is None:
        return list(default)
    if isinstance(raw, str):
        out = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        out = [str(x).strip() for x in raw if str(x).strip()]
    return out or list(default)


def _parse_primary_promotion_modes(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    allowed = {"keep", "score_topn"}
    modes = [m.lower() for m in _parse_list(raw, DEFAULT_PRIMARY_PROMOTION_MODES)]
    out: list[str] = []
    for mode in modes:
        if mode in allowed and mode not in out:
            out.append(mode)
    return out or list(DEFAULT_PRIMARY_PROMOTION_MODES)


def _sanitize_suffix(label: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(label or ""))


def _load_profile_config(profile: str, profile_file: Path = PROFILE_FILE) -> dict[str, Any]:
    payload = json.loads(profile_file.read_text(encoding="utf-8"))
    profiles = payload.get("profiles", payload)
    cfg = profiles.get(profile)
    if not isinstance(cfg, dict):
        raise KeyError(f"profile not found: {profile}")
    return dict(cfg)


def _infer_total_target(profile_cfg: dict[str, Any]) -> float:
    return min(max(_safe_float(profile_cfg.get("fallback_total_position", 0.60), 0.60), 0.0), 1.0)


def _infer_single_cap(profile_cfg: dict[str, Any]) -> float:
    for key in ("max_single_pos", "single_stock_max", "target_max_single_weight"):
        if key not in profile_cfg:
            continue
        raw = profile_cfg.get(key)
        if isinstance(raw, str) and raw.strip().endswith("%"):
            return min(max(_safe_float(raw.strip().rstrip("%"), 10.0) / 100.0, 0.0), 1.0)
        return min(max(_safe_float(raw, 0.10), 0.0), 1.0)
    return 0.10


def _ensure_capacity_amount(df: pd.DataFrame, amount_col: str) -> pd.DataFrame:
    out = df.copy()
    if amount_col == "amount_capacity_conservative" and amount_col not in out.columns:
        if "amount_last" not in out.columns:
            out["amount_last"] = pd.to_numeric(out.get("amount", 0.0), errors="coerce").fillna(0.0)
        for col in ("amount_ma20", "amount_last", "amount_min5", "amount_min10"):
            if col not in out.columns:
                out[col] = 0.0
        vals = out[["amount_ma20", "amount_last", "amount_min5", "amount_min10"]].apply(
            lambda row: min([float(x) for x in row if pd.notna(x) and float(x) > 0.0], default=0.0),
            axis=1,
        )
        out[amount_col] = vals
    if amount_col not in out.columns:
        fallback = "amount_ma20" if "amount_ma20" in out.columns else ("成交额MA20" if "成交额MA20" in out.columns else "")
        if fallback:
            out[amount_col] = pd.to_numeric(out[fallback], errors="coerce").fillna(0.0)
        else:
            out[amount_col] = 0.0
    return out


def _norm01_series(raw: pd.Series) -> pd.Series:
    s = pd.to_numeric(raw, errors="coerce").replace([np.inf, -np.inf], np.nan)
    finite = s.dropna()
    if finite.empty:
        return pd.Series(0.0, index=raw.index, dtype=float)
    lo = float(finite.min())
    hi = float(finite.max())
    if hi - lo <= 1e-12:
        return pd.Series(0.5, index=raw.index, dtype=float)
    return ((s.fillna(lo) - lo) / (hi - lo)).clip(0.0, 1.0)


def _apply_profile_target_blend(df: pd.DataFrame, profile_cfg: dict[str, Any]) -> pd.DataFrame:
    raw = profile_cfg.get("target_score_blend", {})
    if not isinstance(raw, dict) or not raw:
        return df
    out = df.copy()
    pieces: list[tuple[str, float]] = []
    for col, weight in raw.items():
        col_name = str(col).strip()
        w = _safe_float(weight, 0.0)
        if w > 0.0 and col_name in out.columns:
            pieces.append((col_name, w))
    if not pieces:
        return out

    def _blend_day(g: pd.DataFrame) -> pd.DataFrame:
        total = sum(w for _, w in pieces)
        blended = pd.Series(0.0, index=g.index, dtype=float)
        for col_name, weight in pieces:
            blended = blended + float(weight / max(total, 1e-12)) * _norm01_series(g[col_name])
        day = g.copy()
        day["target_blend_score"] = blended.clip(0.0, 1.0)
        return day

    frames = [_blend_day(g) for _, g in out.groupby("signal_date", dropna=False)]
    return pd.concat(frames, ignore_index=True) if frames else out


def _normalize_input_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "signal_date" not in out.columns:
        if "日期" in out.columns:
            out["signal_date"] = pd.to_datetime(out["日期"], errors="coerce").dt.normalize()
        else:
            out["signal_date"] = pd.NaT
    else:
        out["signal_date"] = pd.to_datetime(out["signal_date"], errors="coerce").dt.normalize()
    code_source = "ts_code" if "ts_code" in out.columns else ("code" if "code" in out.columns else "代码")
    if code_source not in out.columns:
        raise KeyError("missing code column: expected ts_code/code/代码")
    out["ts_code"] = normalize_ts_code_series(out[code_source])
    if "代码" not in out.columns:
        out["代码"] = out["ts_code"]
    if "industry" not in out.columns:
        if "行业" in out.columns:
            out["industry"] = out["行业"]
        else:
            out["industry"] = "未知"
    out["industry"] = out["industry"].fillna("未知").astype(str).str.strip().replace({"": "未知"})
    return out[(out["ts_code"] != "") & out["signal_date"].notna()].copy()


def _load_daily_source(
    *,
    daily_glob: str,
    market_file: Path | None,
    start: str,
    end: str,
    forward_days: int,
) -> pd.DataFrame:
    paths = _discover_daily_paths(daily_glob)
    if not paths:
        return pd.DataFrame()
    daily = _load_daily_recommendations(paths, start=start, end=end)
    if daily.empty:
        return pd.DataFrame()
    if "建议持有天数" not in daily.columns:
        daily["建议持有天数"] = int(max(1, int(forward_days)))
    if market_file is None:
        bars, _ = _load_ods_market_bars(daily, max(1, int(forward_days)))
    else:
        bars = _load_market_bars(market_file)
    daily = _attach_forward_returns(daily, bars, default_horizon=max(1, int(forward_days)))
    industry_map = _load_industry_map(daily["signal_date"].max())
    daily["industry"] = daily["code"].map(industry_map).fillna("未知").astype(str).str.strip().replace({"": "未知"})
    return _normalize_input_frame(daily)


def _load_source_frame(
    *,
    profile: str,
    source: str,
    stage_glob: str,
    daily_glob: str,
    stage: str,
    market_file: Path | None,
    start: str,
    end: str,
    forward_days: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = str(source or "stage").strip().lower()
    meta: dict[str, Any] = {"source": source, "requested_stage": stage}
    if source == "daily":
        glob_value = daily_glob or str(BASE_DIR / "output" / "daily_profiles" / profile / "daily_*.csv")
        df = _load_daily_source(
            daily_glob=glob_value,
            market_file=market_file,
            start=start,
            end=end,
            forward_days=forward_days,
        )
        meta.update({"daily_glob": glob_value, "source_rows": int(len(df)), "selected_stage": "daily_profile"})
        return df, meta

    glob_value = stage_glob or str(BASE_DIR / "output" / "research_stage_profiles" / profile / "research_stages_*.csv")
    paths = _discover_paths(glob_value)
    if not paths:
        if daily_glob:
            return _load_source_frame(
                profile=profile,
                source="daily",
                stage_glob="",
                daily_glob=daily_glob,
                stage=stage,
                market_file=market_file,
                start=start,
                end=end,
                forward_days=forward_days,
            )
        return pd.DataFrame(), {"source": "stage", "stage_glob": glob_value, "stage_file_count": 0}
    raw = _load_stage_snapshots(paths, start=start, end=end)
    if raw.empty:
        return pd.DataFrame(), {"source": "stage", "stage_glob": glob_value, "stage_file_count": int(len(paths))}
    present = set(raw.get("research_stage", pd.Series(dtype=str)).astype(str).unique())
    selected_stage = stage
    if stage == "auto":
        selected_stage = next((s for s in DEFAULT_STAGE_PRIORITY if s in present), "")
    if selected_stage:
        raw = raw[raw["research_stage"].astype(str).eq(selected_stage)].copy()
    df = _attach_returns_and_industry(raw, market_file=market_file, forward_days=max(1, int(forward_days)))
    df = _normalize_input_frame(df)
    meta.update(
        {
            "stage_glob": glob_value,
            "stage_file_count": int(len(paths)),
            "selected_stage": selected_stage,
            "source_rows": int(len(df)),
        }
    )
    return df, meta


def _score_rank_ic(day: pd.DataFrame, score_col: str) -> float | None:
    if score_col not in day.columns or "forward_return" not in day.columns:
        return None
    work = day[[score_col, "forward_return"]].copy()
    work[score_col] = pd.to_numeric(work[score_col], errors="coerce")
    work["forward_return"] = pd.to_numeric(work["forward_return"], errors="coerce")
    work = work.dropna()
    if len(work) < 3:
        return None
    if work[score_col].nunique(dropna=True) < 2 or work["forward_return"].nunique(dropna=True) < 2:
        return None
    ic = work[score_col].corr(work["forward_return"], method="spearman")
    if pd.notna(ic) and np.isfinite(float(ic)):
        return float(ic)
    return None


def _unconstrained_top(day: pd.DataFrame, score_col: str, top_n: int) -> pd.DataFrame:
    work = day.copy()
    work["_score"] = pd.to_numeric(work[score_col], errors="coerce")
    work = work.dropna(subset=["_score"])
    if work.empty:
        return work
    return work.sort_values("_score", ascending=False).head(max(1, int(top_n))).drop(columns=["_score"], errors="ignore")


def _mean_forward_return(df: pd.DataFrame) -> float:
    if df.empty or "forward_return" not in df.columns:
        return np.nan
    vals = pd.to_numeric(df["forward_return"], errors="coerce").dropna()
    return float(vals.mean()) if not vals.empty else np.nan


def _weighted_forward_return(df: pd.DataFrame) -> float:
    if df.empty or "forward_return" not in df.columns or "target_weight" not in df.columns:
        return np.nan
    ret = pd.to_numeric(df["forward_return"], errors="coerce")
    weight = pd.to_numeric(df["target_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    mask = ret.notna() & weight.gt(1e-12)
    if not bool(mask.any()):
        return np.nan
    w = weight.loc[mask]
    return float((ret.loc[mask] * w).sum() / max(float(w.sum()), 1e-12))


def _reason_counts(decision_selected: pd.DataFrame, blocked_records: list[dict[str, Any]]) -> dict[str, int]:
    blocked = pd.DataFrame(blocked_records)
    frames = [x for x in (decision_selected, blocked) if x is not None and not x.empty]
    if not frames:
        reasons = pd.Series(dtype=str)
    else:
        all_rows = pd.concat(frames, ignore_index=True)
        reasons = all_rows.get("constraint_reason", pd.Series("", index=all_rows.index)).astype(str)
    return {
        "adv_clip_rows": int(reasons.str.contains("adv_participation_clip", na=False).sum()),
        "industry_clip_rows": int(reasons.str.contains("industry_weight_clip", na=False).sum()),
        "reserve_clip_rows": int(reasons.str.contains("reserve_weight_clip", na=False).sum()),
        "exit_trap_clip_rows": int(
            (
                reasons.str.contains("exit_trap_weight_clip", na=False)
                | reasons.str.contains("exit_trap_single_clip", na=False)
            ).sum()
        ),
        "min_weight_rows": int(reasons.str.contains("min_weight", na=False).sum()),
        "invalid_amount_rows": int(reasons.str.contains("invalid_amount", na=False).sum()),
    }


def _rows_for_codes(df: pd.DataFrame, codes: set[str]) -> pd.DataFrame:
    if df.empty or not codes or "ts_code" not in df.columns:
        return df.iloc[0:0].copy()
    return df[df["ts_code"].astype(str).isin(codes)].copy()


def _decision_records(selected: pd.DataFrame, blocked_records: list[dict[str, Any]]) -> pd.DataFrame:
    blocked = pd.DataFrame(blocked_records)
    frames = [x for x in (selected, blocked) if x is not None and not x.empty]
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if "ts_code" not in out.columns:
        if "代码" in out.columns:
            out["ts_code"] = normalize_ts_code_series(out["代码"])
        elif "code" in out.columns:
            out["ts_code"] = normalize_ts_code_series(out["code"])
    return out


def _reason_counts_for_rows(rows: pd.DataFrame, prefix: str) -> dict[str, int]:
    if rows.empty:
        reasons = pd.Series(dtype=str)
    else:
        reasons = rows.get("constraint_reason", pd.Series("", index=rows.index)).astype(str)
    return {
        f"{prefix}_adv_clip_rows": int(reasons.str.contains("adv_participation_clip", na=False).sum()),
        f"{prefix}_industry_clip_rows": int(reasons.str.contains("industry_weight_clip", na=False).sum()),
        f"{prefix}_reserve_clip_rows": int(reasons.str.contains("reserve_weight_clip", na=False).sum()),
        f"{prefix}_exit_trap_clip_rows": int(
            (
                reasons.str.contains("exit_trap_weight_clip", na=False)
                | reasons.str.contains("exit_trap_single_clip", na=False)
            ).sum()
        ),
        f"{prefix}_invalid_amount_rows": int(reasons.str.contains("invalid_amount", na=False).sum()),
        f"{prefix}_min_weight_rows": int(reasons.str.contains("min_weight", na=False).sum()),
    }


def _selection_loss_label(row: dict[str, Any]) -> str:
    if _safe_float(row.get("selection_loss_pct", 0.0), 0.0) >= 0.0:
        return "no_selection_loss"
    if _safe_int(row.get("top_dropped_rows", 0), 0) <= 0:
        return "selected_reweight_loss"
    reason_counts = {
        "invalid_amount_capacity_loss": _safe_int(row.get("top_dropped_invalid_amount_rows", 0), 0),
        "reserve_cap_replaced_alpha": _safe_int(row.get("top_dropped_reserve_clip_rows", 0), 0),
        "exit_trap_cap_replaced_alpha": _safe_int(row.get("top_dropped_exit_trap_clip_rows", 0), 0),
        "adv_capacity_replaced_alpha": _safe_int(row.get("top_dropped_adv_clip_rows", 0), 0),
        "industry_cap_replaced_alpha": _safe_int(row.get("top_dropped_industry_clip_rows", 0), 0),
        "min_weight_replaced_alpha": _safe_int(row.get("top_dropped_min_weight_rows", 0), 0),
    }
    best_label, best_count = max(reason_counts.items(), key=lambda kv: kv[1])
    if best_count > 0:
        return best_label
    if _safe_int(row.get("selected_replacement_rows", 0), 0) > 0:
        return "replacement_quality_loss"
    return "constraint_selected_loss"


def _loss_label_from_summary(row: dict[str, Any]) -> str:
    if _safe_float(row.get("selection_loss_pct", 0.0), 0.0) >= 0.0:
        return "no_selection_loss"
    reason_counts = {
        "invalid_amount_capacity_loss": _safe_int(row.get("top_dropped_invalid_amount_rows", 0), 0),
        "reserve_cap_replaced_alpha": _safe_int(row.get("top_dropped_reserve_clip_rows", 0), 0),
        "exit_trap_cap_replaced_alpha": _safe_int(row.get("top_dropped_exit_trap_clip_rows", 0), 0),
        "adv_capacity_replaced_alpha": _safe_int(row.get("top_dropped_adv_clip_rows", 0), 0),
        "industry_cap_replaced_alpha": _safe_int(row.get("top_dropped_industry_clip_rows", 0), 0),
        "min_weight_replaced_alpha": _safe_int(row.get("top_dropped_min_weight_rows", 0), 0),
    }
    best_label, best_count = max(reason_counts.items(), key=lambda kv: kv[1])
    if best_count > 0:
        return best_label
    if _safe_int(row.get("selected_replacement_rows", 0), 0) > 0:
        return "replacement_quality_loss"
    return "constraint_selected_loss"


def _apply_primary_promotion_mode(day: pd.DataFrame, score_col: str, top_n: int, mode: str) -> pd.DataFrame:
    mode = str(mode or "keep").strip().lower()
    out = day.copy()
    if mode != "score_topn":
        if "reserve_candidate" not in out.columns:
            out["reserve_candidate"] = 0
        return out
    if score_col not in out.columns:
        out["reserve_candidate"] = 0
        return out
    score = pd.to_numeric(out[score_col], errors="coerce")
    ranked_idx = score.sort_values(ascending=False, na_position="last").index.tolist()
    primary = set(ranked_idx[: max(1, int(top_n))])
    out["reserve_candidate"] = [0 if idx in primary else 1 for idx in out.index]
    return out


def _constraints_for_day(
    *,
    profile_cfg: dict[str, Any],
    score_col: str,
    total_target: float,
    single_cap: float,
    top_n: int,
) -> PortfolioConstraints:
    optimizer_mode = str(profile_cfg.get("optimizer_mode", "score_weight") or "score_weight").strip().lower()
    capacity_on = optimizer_mode in {"capacity_aware", "capacity_crowding", "capacity_crowding_aware"}
    industry_cap = _safe_float(profile_cfg.get("target_max_industry_weight", 0.0), 0.0)
    adv_cap = _safe_float(profile_cfg.get("target_max_adv_participation", 0.0), 0.0)
    if capacity_on:
        if industry_cap <= 0.0:
            industry_cap = _safe_float(profile_cfg.get("risk_max_industry_weight", 0.0), 0.0)
        if adv_cap <= 0.0:
            adv_cap = _safe_float(profile_cfg.get("risk_max_adv_participation", 0.0), 0.0)
    else:
        industry_cap = 0.0
        adv_cap = 0.0
    return PortfolioConstraints(
        total_target=min(max(float(total_target), 0.0), 1.0),
        single_cap=min(max(float(single_cap), 0.0), 1.0),
        industry_cap=min(max(float(industry_cap), 0.0), 1.0),
        adv_participation_cap=min(max(float(adv_cap), 0.0), 1.0),
        capital_base=max(100000.0, _safe_float(profile_cfg.get("target_capital_base", 1_000_000.0), 1_000_000.0)),
        max_names=max(0, int(top_n)),
        min_names=max(0, _safe_int(profile_cfg.get("min_valid_positions", 0), 0)),
        score_col=score_col,
        code_col="ts_code",
        industry_col="industry",
        amount_col=str(profile_cfg.get("target_capacity_amount_col", "amount_ma20") or "amount_ma20"),
        amount_buffer=max(0.0, _safe_float(profile_cfg.get("target_capacity_amount_buffer", 1.0), 1.0)),
        redistribute_clipped=_parse_bool(profile_cfg.get("redistribute_clipped_weight", False), default=False),
        reserve_cap=min(max(_safe_float(profile_cfg.get("target_max_reserve_weight", 0.0), 0.0), 0.0), 1.0),
        reserve_col="reserve_candidate",
        exit_trap_risk_col="exit_trap_risk_score",
        exit_trap_risk_threshold=min(
            max(_safe_float(profile_cfg.get("target_exit_trap_risk_threshold", 0.0), 0.0), 0.0),
            1.0,
        ),
        exit_trap_weight_cap=min(max(_safe_float(profile_cfg.get("target_max_exit_trap_weight", 0.0), 0.0), 0.0), 1.0),
        exit_trap_single_cap=min(
            max(_safe_float(profile_cfg.get("target_max_exit_trap_single_weight", 0.0), 0.0), 0.0),
            1.0,
        ),
        impact_model=str(profile_cfg.get("impact_model", "sqrt") or "sqrt"),
        impact_base_bps=max(0.0, _safe_float(profile_cfg.get("impact_base_bps", 0.0), 0.0)),
        impact_participation_bps=max(0.0, _safe_float(profile_cfg.get("impact_participation_bps", 0.0), 0.0)),
        impact_power=max(0.10, _safe_float(profile_cfg.get("impact_power", 0.5), 0.5)),
    )


def _day_caps(day: pd.DataFrame, *, base_total: float, base_single: float) -> tuple[float, float]:
    total = base_total
    single = base_single
    if "holiday_gap_total_position_cap" in day.columns:
        vals = pd.to_numeric(day["holiday_gap_total_position_cap"], errors="coerce").dropna()
        vals = vals[vals > 0]
        if not vals.empty:
            total = min(total, float(vals.median()))
    if "holiday_gap_single_pos_cap" in day.columns:
        vals = pd.to_numeric(day["holiday_gap_single_pos_cap"], errors="coerce").dropna()
        vals = vals[vals > 0]
        if not vals.empty:
            single = min(single, float(vals.median()))
    return min(max(float(total), 0.0), 1.0), min(max(float(single), 0.0), 1.0)


def build_capacity_feasible_summary(
    df: pd.DataFrame,
    *,
    profile_cfg: dict[str, Any],
    score_cols: list[str],
    top_n: int | None = None,
    total_target: float | None = None,
    single_cap: float | None = None,
    min_days: int = 60,
    min_target_weight_sum_mean: float = 0.30,
    max_zero_target_rate_pct: float = 5.0,
    max_capacity_shortfall_weight: float = 0.10,
    min_selected_forward_return_pct: float = 0.0,
    min_selected_minus_pool_pct: float = 0.0,
    min_rank_ic: float = 0.0,
    min_alt_spread_pct: float = 0.25,
    primary_promotion_modes: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    source = _normalize_input_frame(df)
    source = _apply_profile_target_blend(source, profile_cfg)
    score_cols = [col for col in score_cols if col in source.columns]
    top_n = int(top_n or _safe_int(profile_cfg.get("top_n", 20), 20))
    base_total = _infer_total_target(profile_cfg) if total_target is None else min(max(float(total_target), 0.0), 1.0)
    base_single = _infer_single_cap(profile_cfg) if single_cap is None else min(max(float(single_cap), 0.0), 1.0)
    promotion_modes = _parse_primary_promotion_modes(primary_promotion_modes)
    daily_rows: list[dict[str, Any]] = []

    for score_col in score_cols:
        work = source.copy()
        work[score_col] = pd.to_numeric(work[score_col], errors="coerce")
        work = work.dropna(subset=[score_col])
        amount_col = str(profile_cfg.get("target_capacity_amount_col", "amount_ma20") or "amount_ma20")
        work = _ensure_capacity_amount(work, amount_col)
        for date, day in work.groupby("signal_date", dropna=False):
            base_day = day.copy()
            day = base_day.copy()
            pool_ret = _mean_forward_return(day)
            top = _unconstrained_top(day, score_col, top_n=top_n)
            top_ret = _mean_forward_return(top)
            rank_ic = _score_rank_ic(day, score_col)
            day_total, day_single = _day_caps(day, base_total=base_total, base_single=base_single)
            for promotion_mode in promotion_modes:
                day = _apply_primary_promotion_mode(base_day, score_col, top_n, promotion_mode)
                constraints = _constraints_for_day(
                    profile_cfg=profile_cfg,
                    score_col=score_col,
                    total_target=day_total,
                    single_cap=day_single,
                    top_n=top_n,
                )
                decision = build_portfolio_decision(day, constraints)
                selected = decision.selected.copy()
                selected_positive = selected[
                    pd.to_numeric(selected.get("target_weight", pd.Series(0.0, index=selected.index)), errors="coerce")
                    .fillna(0.0)
                    .gt(1e-12)
                ].copy()
                target_sum = float(decision.exposures.get("total_weight", 0.0))
                selected_ret = _weighted_forward_return(selected_positive)
                selected_equal_ret = _mean_forward_return(selected_positive)
                blocked_records = list(decision.diagnostics.get("blocked", []))
                decision_rows = _decision_records(selected, blocked_records)
                counts = _reason_counts(selected, blocked_records)
                top_codes = set(top.get("ts_code", pd.Series(dtype=str)).astype(str))
                selected_codes = set(selected_positive.get("ts_code", pd.Series(dtype=str)).astype(str))
                overlap_codes = top_codes & selected_codes
                top_dropped_codes = top_codes - selected_codes
                replacement_codes = selected_codes - top_codes
                top_dropped = _rows_for_codes(top, top_dropped_codes)
                selected_replacement = _rows_for_codes(selected_positive, replacement_codes)
                decision_top_dropped = _rows_for_codes(decision_rows, top_dropped_codes)
                top_dropped_ret = _mean_forward_return(top_dropped)
                replacement_ret = _mean_forward_return(selected_replacement)
                top_overlap_weight_sum = float(
                    pd.to_numeric(
                        _rows_for_codes(selected_positive, overlap_codes).get("target_weight", pd.Series(dtype=float)),
                        errors="coerce",
                    )
                    .fillna(0.0)
                    .sum()
                )
                replacement_weight_sum = float(
                    pd.to_numeric(selected_replacement.get("target_weight", pd.Series(dtype=float)), errors="coerce")
                    .fillna(0.0)
                    .sum()
                )
                dropped_unfilled_weight_sum = float(
                    pd.to_numeric(decision_top_dropped.get("unfilled_target_weight", pd.Series(dtype=float)), errors="coerce")
                    .fillna(0.0)
                    .sum()
                )
                dropped_raw_weight_sum = float(
                    pd.to_numeric(decision_top_dropped.get("target_weight_raw", pd.Series(dtype=float)), errors="coerce")
                    .fillna(0.0)
                    .sum()
                )
                loss_row = {
                    "selection_loss_pct": float((selected_ret - top_ret) * 100.0)
                    if np.isfinite(selected_ret) and np.isfinite(top_ret)
                    else 0.0,
                    "top_selected_overlap_rows": int(len(overlap_codes)),
                    "top_selected_overlap_rate_pct": float(len(overlap_codes) / max(len(top_codes), 1) * 100.0),
                    "top_dropped_rows": int(len(top_dropped)),
                    "top_dropped_mean_forward_return_pct": float(top_dropped_ret * 100.0)
                    if np.isfinite(top_dropped_ret)
                    else 0.0,
                    "top_dropped_target_weight_raw_sum": float(dropped_raw_weight_sum),
                    "top_dropped_unfilled_weight_sum": float(dropped_unfilled_weight_sum),
                    "selected_replacement_rows": int(len(selected_replacement)),
                    "selected_replacement_mean_forward_return_pct": float(replacement_ret * 100.0)
                    if np.isfinite(replacement_ret)
                    else 0.0,
                    "selected_replacement_target_weight_sum": float(replacement_weight_sum),
                    "selected_from_top_target_weight_sum": float(top_overlap_weight_sum),
                    "replacement_minus_dropped_forward_return_pct": float((replacement_ret - top_dropped_ret) * 100.0)
                    if np.isfinite(replacement_ret) and np.isfinite(top_dropped_ret)
                    else 0.0,
                }
                loss_row.update(_reason_counts_for_rows(decision_top_dropped, "top_dropped"))
                loss_row["selection_loss_label"] = _selection_loss_label(loss_row)
                daily_rows.append(
                    {
                        "signal_date": pd.Timestamp(date).strftime("%Y-%m-%d") if pd.notna(date) else "",
                        "score_col": score_col,
                        "primary_promotion_mode": str(promotion_mode),
                        "input_rows": int(len(day)),
                        "top_n": int(top_n),
                        "pool_mean_forward_return_pct": float(pool_ret * 100.0) if np.isfinite(pool_ret) else 0.0,
                        "unconstrained_top_mean_forward_return_pct": float(top_ret * 100.0)
                        if np.isfinite(top_ret)
                        else 0.0,
                        "unconstrained_top_minus_pool_pct": float((top_ret - pool_ret) * 100.0)
                        if np.isfinite(top_ret) and np.isfinite(pool_ret)
                        else 0.0,
                        "selected_weighted_forward_return_pct": float(selected_ret * 100.0)
                        if np.isfinite(selected_ret)
                        else 0.0,
                        "selected_equal_forward_return_pct": float(selected_equal_ret * 100.0)
                        if np.isfinite(selected_equal_ret)
                        else 0.0,
                        "selected_minus_pool_pct": float((selected_ret - pool_ret) * 100.0)
                        if np.isfinite(selected_ret) and np.isfinite(pool_ret)
                        else 0.0,
                        "rank_ic": float(rank_ic) if rank_ic is not None else 0.0,
                        "target_weight_sum": float(target_sum),
                        "zero_target": int(target_sum <= 1e-12),
                        "selected_count": int(decision.diagnostics.get("selected_count", len(selected))),
                        "blocked_count": int(decision.diagnostics.get("blocked_count", 0)),
                        "capacity_shortfall_weight": float(decision.exposures.get("capacity_shortfall_weight", 0.0)),
                        "max_industry_weight": float(decision.exposures.get("max_industry_weight", 0.0)),
                        "max_adv_participation_pct": float(decision.exposures.get("max_adv_participation_pct", 0.0)),
                        **counts,
                        **loss_row,
                    }
                )

    daily = pd.DataFrame(daily_rows)
    summary_rows: list[dict[str, Any]] = []
    group_cols = ["score_col", "primary_promotion_mode"] if "primary_promotion_mode" in daily.columns else ["score_col"]
    for group_key, g in daily.groupby(group_cols, dropna=False):
        if isinstance(group_key, tuple):
            score_col = str(group_key[0])
            promotion_mode = str(group_key[1])
        else:
            score_col = str(group_key)
            promotion_mode = "keep"
        target = pd.to_numeric(g["target_weight_sum"], errors="coerce").fillna(0.0)
        selected_ret = pd.to_numeric(g["selected_weighted_forward_return_pct"], errors="coerce")
        pool_ret = pd.to_numeric(g["pool_mean_forward_return_pct"], errors="coerce")
        selected_minus_pool = pd.to_numeric(g["selected_minus_pool_pct"], errors="coerce")
        unconstrained_top = pd.to_numeric(g["unconstrained_top_mean_forward_return_pct"], errors="coerce")
        unconstrained_spread = pd.to_numeric(g["unconstrained_top_minus_pool_pct"], errors="coerce")
        rank_ic = pd.to_numeric(g["rank_ic"], errors="coerce")
        selection_loss = pd.to_numeric(g["selection_loss_pct"], errors="coerce")
        top_dropped_ret = pd.to_numeric(g["top_dropped_mean_forward_return_pct"], errors="coerce")
        replacement_ret = pd.to_numeric(g["selected_replacement_mean_forward_return_pct"], errors="coerce")
        days = int(g["signal_date"].nunique())
        row = {
            "score_col": str(score_col),
            "primary_promotion_mode": str(promotion_mode),
            "days": days,
            "input_rows": int(pd.to_numeric(g["input_rows"], errors="coerce").fillna(0).sum()),
            "target_weight_sum_mean": float(target.mean()) if len(target) else 0.0,
            "target_weight_sum_p10": float(target.quantile(0.10)) if len(target) else 0.0,
            "zero_target_days": int(pd.to_numeric(g["zero_target"], errors="coerce").fillna(0).sum()),
            "zero_target_rate_pct": float(pd.to_numeric(g["zero_target"], errors="coerce").fillna(0).mean() * 100.0)
            if len(g)
            else 0.0,
            "capacity_shortfall_weight_mean": float(
                pd.to_numeric(g["capacity_shortfall_weight"], errors="coerce").fillna(0.0).mean()
            )
            if len(g)
            else 0.0,
            "pool_mean_forward_return_pct": float(pool_ret.mean()) if len(pool_ret) else 0.0,
            "unconstrained_top_mean_forward_return_pct": float(unconstrained_top.mean()) if len(unconstrained_top) else 0.0,
            "unconstrained_top_minus_pool_pct": float(unconstrained_spread.mean()) if len(unconstrained_spread) else 0.0,
            "selected_weighted_forward_return_pct": float(selected_ret.mean()) if selected_ret.notna().any() else 0.0,
            "selected_minus_pool_pct": float(selected_minus_pool.mean()) if selected_minus_pool.notna().any() else 0.0,
            "selected_hit_rate_pct": float(
                (pd.to_numeric(g["selected_weighted_forward_return_pct"], errors="coerce") > 0.0).mean() * 100.0
            )
            if len(g)
            else 0.0,
            "rank_ic_mean": float(rank_ic.mean()) if len(rank_ic) else 0.0,
            "selection_loss_pct": float(selection_loss.mean()) if len(selection_loss) else 0.0,
            "top_selected_overlap_rate_pct": float(
                pd.to_numeric(g["top_selected_overlap_rate_pct"], errors="coerce").fillna(0.0).mean()
            )
            if len(g)
            else 0.0,
            "top_dropped_rows": int(pd.to_numeric(g["top_dropped_rows"], errors="coerce").fillna(0).sum()),
            "top_dropped_mean_forward_return_pct": float(top_dropped_ret.mean()) if len(top_dropped_ret) else 0.0,
            "top_dropped_target_weight_raw_sum": float(
                pd.to_numeric(g["top_dropped_target_weight_raw_sum"], errors="coerce").fillna(0.0).sum()
            ),
            "top_dropped_unfilled_weight_sum": float(
                pd.to_numeric(g["top_dropped_unfilled_weight_sum"], errors="coerce").fillna(0.0).sum()
            ),
            "selected_replacement_rows": int(
                pd.to_numeric(g["selected_replacement_rows"], errors="coerce").fillna(0).sum()
            ),
            "selected_replacement_mean_forward_return_pct": float(replacement_ret.mean()) if len(replacement_ret) else 0.0,
            "selected_replacement_target_weight_sum": float(
                pd.to_numeric(g["selected_replacement_target_weight_sum"], errors="coerce").fillna(0.0).sum()
            ),
            "selected_from_top_target_weight_sum": float(
                pd.to_numeric(g["selected_from_top_target_weight_sum"], errors="coerce").fillna(0.0).sum()
            ),
            "adv_clip_rows": int(pd.to_numeric(g["adv_clip_rows"], errors="coerce").fillna(0).sum()),
            "industry_clip_rows": int(pd.to_numeric(g["industry_clip_rows"], errors="coerce").fillna(0).sum()),
            "reserve_clip_rows": int(pd.to_numeric(g["reserve_clip_rows"], errors="coerce").fillna(0).sum()),
            "exit_trap_clip_rows": int(pd.to_numeric(g["exit_trap_clip_rows"], errors="coerce").fillna(0).sum()),
            "invalid_amount_rows": int(pd.to_numeric(g["invalid_amount_rows"], errors="coerce").fillna(0).sum()),
            "top_dropped_adv_clip_rows": int(pd.to_numeric(g["top_dropped_adv_clip_rows"], errors="coerce").fillna(0).sum()),
            "top_dropped_industry_clip_rows": int(
                pd.to_numeric(g["top_dropped_industry_clip_rows"], errors="coerce").fillna(0).sum()
            ),
            "top_dropped_reserve_clip_rows": int(
                pd.to_numeric(g["top_dropped_reserve_clip_rows"], errors="coerce").fillna(0).sum()
            ),
            "top_dropped_exit_trap_clip_rows": int(
                pd.to_numeric(g["top_dropped_exit_trap_clip_rows"], errors="coerce").fillna(0).sum()
            ),
            "top_dropped_invalid_amount_rows": int(
                pd.to_numeric(g["top_dropped_invalid_amount_rows"], errors="coerce").fillna(0).sum()
            ),
            "top_dropped_min_weight_rows": int(
                pd.to_numeric(g["top_dropped_min_weight_rows"], errors="coerce").fillna(0).sum()
            ),
        }
        row["selection_loss_label"] = _loss_label_from_summary(row)
        row.update(
            evaluate_capacity_feasible_row(
                row,
                min_days=min_days,
                min_target_weight_sum_mean=min_target_weight_sum_mean,
                max_zero_target_rate_pct=max_zero_target_rate_pct,
                max_capacity_shortfall_weight=max_capacity_shortfall_weight,
                min_selected_forward_return_pct=min_selected_forward_return_pct,
                min_selected_minus_pool_pct=min_selected_minus_pool_pct,
                min_rank_ic=min_rank_ic,
                min_alt_spread_pct=min_alt_spread_pct,
            )
        )
        summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary = summary.sort_values(
            [
                "gate_pass",
                "verdict",
                "selected_weighted_forward_return_pct",
                "target_weight_sum_mean",
                "primary_promotion_mode",
            ],
            ascending=[False, True, False, False, True],
        ).reset_index(drop=True)
    gate = {
        "pass": bool(not summary.empty and summary["gate_pass"].astype(bool).any()),
        "passing_score_cols": (
            summary.loc[summary["gate_pass"].astype(bool), "score_col"].astype(str).tolist()
            if not summary.empty
            else []
        ),
        "passing_score_modes": (
            (
                summary.loc[summary["gate_pass"].astype(bool), "score_col"].astype(str)
                + ":"
                + summary.loc[summary["gate_pass"].astype(bool), "primary_promotion_mode"].astype(str)
            ).tolist()
            if not summary.empty and "primary_promotion_mode" in summary.columns
            else []
        ),
        "reasons": [] if (not summary.empty and summary["gate_pass"].astype(bool).any()) else ["no_capacity_feasible_alpha_score_passed"],
        "thresholds": {
            "min_days": int(min_days),
            "min_target_weight_sum_mean": float(min_target_weight_sum_mean),
            "max_zero_target_rate_pct": float(max_zero_target_rate_pct),
            "max_capacity_shortfall_weight": float(max_capacity_shortfall_weight),
            "min_selected_forward_return_pct": float(min_selected_forward_return_pct),
            "min_selected_minus_pool_pct": float(min_selected_minus_pool_pct),
            "min_rank_ic": float(min_rank_ic),
            "min_alt_spread_pct": float(min_alt_spread_pct),
            "primary_promotion_modes": list(promotion_modes),
        },
        "limitation": (
            "This is a capacity-feasible pre-profile diagnostic. Passing it only allows a shadow profile "
            "hypothesis; it is not promotion evidence."
        ),
    }
    return summary, daily, gate


def evaluate_capacity_feasible_row(
    row: dict[str, Any] | pd.Series,
    *,
    min_days: int = 60,
    min_target_weight_sum_mean: float = 0.30,
    max_zero_target_rate_pct: float = 5.0,
    max_capacity_shortfall_weight: float = 0.10,
    min_selected_forward_return_pct: float = 0.0,
    min_selected_minus_pool_pct: float = 0.0,
    min_rank_ic: float = 0.0,
    min_alt_spread_pct: float = 0.25,
) -> dict[str, Any]:
    days = _safe_int(row.get("days", 0), 0)
    target_mean = _safe_float(row.get("target_weight_sum_mean", 0.0), 0.0)
    zero_rate = _safe_float(row.get("zero_target_rate_pct", 0.0), 0.0)
    shortfall = _safe_float(row.get("capacity_shortfall_weight_mean", 0.0), 0.0)
    selected_ret = _safe_float(row.get("selected_weighted_forward_return_pct", 0.0), 0.0)
    selected_spread = _safe_float(row.get("selected_minus_pool_pct", 0.0), 0.0)
    rank_ic = _safe_float(row.get("rank_ic_mean", 0.0), 0.0)
    raw_top = _safe_float(row.get("unconstrained_top_mean_forward_return_pct", 0.0), 0.0)
    raw_spread = _safe_float(row.get("unconstrained_top_minus_pool_pct", 0.0), 0.0)

    if days < int(min_days):
        return {"gate_pass": False, "verdict": "insufficient_sample", "reasons": ["days_too_low"]}

    capacity_reasons: list[str] = []
    if target_mean < float(min_target_weight_sum_mean):
        capacity_reasons.append("target_weight_sum_mean_too_low")
    if zero_rate > float(max_zero_target_rate_pct):
        capacity_reasons.append("zero_target_rate_too_high")
    if shortfall > float(max_capacity_shortfall_weight):
        capacity_reasons.append("capacity_shortfall_too_high")
    capacity_ok = not capacity_reasons

    feasible_alpha_reasons: list[str] = []
    if selected_ret <= float(min_selected_forward_return_pct):
        feasible_alpha_reasons.append("selected_forward_return_not_positive")
    if selected_spread <= float(min_selected_minus_pool_pct):
        feasible_alpha_reasons.append("selected_not_above_pool")
    if rank_ic <= float(min_rank_ic) and selected_spread < float(min_alt_spread_pct):
        feasible_alpha_reasons.append("rank_ic_not_positive_and_spread_not_large")
    feasible_alpha_ok = not feasible_alpha_reasons

    raw_alpha_positive = raw_top > float(min_selected_forward_return_pct) and raw_spread > float(min_selected_minus_pool_pct)
    if capacity_ok and feasible_alpha_ok:
        return {"gate_pass": True, "verdict": "capacity_feasible_alpha_pass", "reasons": []}
    if raw_alpha_positive and not capacity_ok:
        return {
            "gate_pass": False,
            "verdict": "alpha_positive_but_capacity_failed",
            "reasons": capacity_reasons,
        }
    if capacity_ok and not feasible_alpha_ok:
        return {
            "gate_pass": False,
            "verdict": "capacity_ok_alpha_failed",
            "reasons": feasible_alpha_reasons,
        }
    return {
        "gate_pass": False,
        "verdict": "alpha_and_capacity_failed",
        "reasons": feasible_alpha_reasons + capacity_reasons,
    }


def build_report(
    *,
    profile: str,
    source: str = "stage",
    stage_glob: str = "",
    daily_glob: str = "",
    stage: str = "optimizer_ranked_pool",
    market_file: Path | None = None,
    profile_file: Path = PROFILE_FILE,
    start: str = "",
    end: str = "",
    forward_days: int = 8,
    score_cols: list[str] | None = None,
    top_n: int | None = None,
    min_days: int = 60,
    min_target_weight_sum_mean: float = 0.30,
    max_zero_target_rate_pct: float = 5.0,
    max_capacity_shortfall_weight: float = 0.10,
    primary_promotion_modes: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cfg = _load_profile_config(profile, profile_file=profile_file)
    if forward_days <= 0:
        forward_days = max(1, _safe_int(cfg.get("holding_days", 8), 8))
    df, source_meta = _load_source_frame(
        profile=profile,
        source=source,
        stage_glob=stage_glob,
        daily_glob=daily_glob,
        stage=stage,
        market_file=market_file,
        start=start,
        end=end,
        forward_days=forward_days,
    )
    if df.empty:
        raise RuntimeError("capacity-feasible alpha source is empty")
    summary, daily, gate = build_capacity_feasible_summary(
        df,
        profile_cfg=cfg,
        score_cols=score_cols or DEFAULT_SCORE_COLS,
        top_n=top_n or _safe_int(cfg.get("top_n", 20), 20),
        min_days=min_days,
        min_target_weight_sum_mean=min_target_weight_sum_mean,
        max_zero_target_rate_pct=max_zero_target_rate_pct,
        max_capacity_shortfall_weight=max_capacity_shortfall_weight,
        primary_promotion_modes=primary_promotion_modes,
    )
    meta: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profile": profile,
        "profile_file": str(profile_file),
        "market_data_source": "ashare_ods" if market_file is None else "explicit_market_file",
        "market_file": str(market_file or ""),
        "signal_start": str(df["signal_date"].min().date()),
        "signal_end": str(df["signal_date"].max().date()),
        "forward_days_default": int(forward_days),
        "top_n": int(top_n or _safe_int(cfg.get("top_n", 20), 20)),
        "score_cols_requested": list(score_cols or DEFAULT_SCORE_COLS),
        "source_meta": source_meta,
        "capacity_feasible_alpha_gate": gate,
        "summary": summary.to_dict(orient="records"),
        "daily": daily.to_dict(orient="records"),
    }
    return summary, daily, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Capacity-feasible alpha diagnosis for profile artifacts")
    parser.add_argument("--profile", required=True, help="profile name")
    parser.add_argument("--source", choices=["stage", "daily"], default="stage", help="artifact source")
    parser.add_argument("--stage-glob", default="", help="research stage CSV glob(s)")
    parser.add_argument("--daily-glob", default="", help="profile daily CSV glob(s)")
    parser.add_argument("--stage", default="optimizer_ranked_pool", help="research stage to simulate, or auto")
    parser.add_argument("--market-file", default="", help="optional explicit market parquet; default is shared ODS")
    parser.add_argument("--profile-file", default=str(PROFILE_FILE), help="profile JSON file")
    parser.add_argument("--start", default="", help="signal start date")
    parser.add_argument("--end", default="", help="signal end date")
    parser.add_argument("--forward-days", type=int, default=0, help="default forward horizon; 0 uses profile holding_days")
    parser.add_argument("--score-cols", default=",".join(DEFAULT_SCORE_COLS), help="comma-separated score columns")
    parser.add_argument("--top-n", type=int, default=0, help="top-N/max primary names; 0 uses profile top_n")
    parser.add_argument("--min-days", type=int, default=60, help="minimum signal days for a usable pre-profile gate")
    parser.add_argument("--min-target-weight-sum-mean", type=float, default=0.30)
    parser.add_argument("--max-zero-target-rate-pct", type=float, default=5.0)
    parser.add_argument("--max-capacity-shortfall-weight", type=float, default=0.10)
    parser.add_argument(
        "--primary-promotion-modes",
        default=",".join(DEFAULT_PRIMARY_PROMOTION_MODES),
        help="comma-separated diagnostic reserve-label modes: keep,score_topn",
    )
    parser.add_argument("--label", default="", help="artifact label suffix")
    parser.add_argument("--write-latest", action="store_true", help="write latest shortcut files")
    parser.add_argument("--enforce-gate", action="store_true", help="return non-zero when no score passes")
    args = parser.parse_args()

    score_cols = _parse_list(args.score_cols, DEFAULT_SCORE_COLS)
    label = str(args.label or args.profile)
    summary, daily, payload = build_report(
        profile=str(args.profile),
        source=str(args.source),
        stage_glob=str(args.stage_glob or ""),
        daily_glob=str(args.daily_glob or ""),
        stage=str(args.stage or "optimizer_ranked_pool"),
        market_file=Path(args.market_file).resolve() if args.market_file else None,
        profile_file=Path(args.profile_file).resolve(),
        start=str(args.start or ""),
        end=str(args.end or ""),
        forward_days=int(args.forward_days),
        score_cols=score_cols,
        top_n=int(args.top_n) if int(args.top_n) > 0 else None,
        min_days=max(0, int(args.min_days)),
        min_target_weight_sum_mean=float(args.min_target_weight_sum_mean),
        max_zero_target_rate_pct=float(args.max_zero_target_rate_pct),
        max_capacity_shortfall_weight=float(args.max_capacity_shortfall_weight),
        primary_promotion_modes=_parse_primary_promotion_modes(args.primary_promotion_modes),
    )

    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = _sanitize_suffix(f"_{label}" if label else "")
    base = BACKTEST_DIR / f"quant_capacity_feasible_alpha_diagnosis{suffix}_{ts}"
    summary_csv = base.with_name(base.name + "_score_summary.csv")
    daily_csv = base.with_name(base.name + "_daily.csv")
    json_path = base.with_suffix(".json")
    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    daily.to_csv(daily_csv, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        latest = BACKTEST_DIR / f"quant_capacity_feasible_alpha_diagnosis_latest{suffix}"
        summary.to_csv(latest.with_name(latest.name + "_score_summary.csv"), index=False, encoding="utf-8-sig")
        daily.to_csv(latest.with_name(latest.name + "_daily.csv"), index=False, encoding="utf-8-sig")
        latest.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(summary.to_string(index=False))
    gate = payload.get("capacity_feasible_alpha_gate", {})
    print(f"capacity_feasible_alpha_gate_pass={bool(gate.get('pass', False))}")
    if gate.get("reasons"):
        print(f"capacity_feasible_alpha_gate_reasons={','.join(str(x) for x in gate.get('reasons', []))}")
    print(f"capacity_feasible_score_summary_csv={summary_csv}")
    print(f"capacity_feasible_daily_csv={daily_csv}")
    print(f"capacity_feasible_json={json_path}")
    if args.enforce_gate and not bool(gate.get("pass", False)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
