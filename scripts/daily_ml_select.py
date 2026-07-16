#!/usr/bin/env python3
"""
每日ML选股脚本 (内存优化版)
使用训练好的LightGBM模型进行选股
按目标日期裁剪窗口计算指标，兼顾内存与历史回算

使用方法:
    python scripts/daily_ml_select.py
    python scripts/daily_ml_select.py --date 20260109
"""

import pandas as pd
import numpy as np
import os
import sys
import pickle
import json
import re
from datetime import datetime
import argparse
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))

from mfts_screener import calc_indicators, load_metadata
from core.data.market_data_gateway import AShareMarketDataGateway
from core.risk import PreTradeRiskConfig, apply_pretrade_risk_gates, load_industry_map
from core.risk.pretrade import _load_blacklist
from core.platform.portfolio_engine import PortfolioConstraints, build_portfolio_decision
from config.settings import resolve_default_label_horizon
from utils.code_utils import limit_ratio_vectorized, normalize_ts_code, normalize_ts_code_series
from utils.market_data_units import normalize_amount_volume_units
from utils.market_regime import detect_market_regime
from utils.metadata_guard import evaluate_metadata_guard, load_ods_metadata_health
from utils.execution_overlay import add_execution_overlay_scores
from utils.output_paths import ensure_output_dirs, write_dual_csv
from utils.portfolio_weights import build_score_weights, build_target_weight_checksum
from utils.signal_refactor import add_feature_refactor_columns
from utils.signal_quality import add_signal_quality_columns

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
MODEL_DIR = os.path.join(BASE_DIR, "models")
PROFILE_FILE = Path(BASE_DIR) / "config" / "quant_live_profiles.json"
_MODEL_CACHE: dict[str, object] = {}
_DATA_CACHE: dict[tuple[object, ...], pd.DataFrame] = {}
_INDICATOR_DATA_CACHE: dict[tuple[tuple[str, ...], str, str], pd.DataFrame] = {}


def load_default_profile_config(profile_file: Path | None = None) -> dict[str, object]:
    """读取 default_profile 对应的量化档位配置。"""
    try:
        path = Path(profile_file) if profile_file else PROFILE_FILE
        with path.open("r", encoding="utf-8") as f:
            root = json.load(f)
        if not isinstance(root, dict):
            return {}
        profiles = root.get("profiles", {})
        if not isinstance(profiles, dict):
            return {}
        profile_name = str(
            os.environ.get("MFTS_ACTIVE_PROFILE")
            or os.environ.get("MFTS_P2_PROFILE")
            or root.get("default_profile", "")
        )
        cfg = profiles.get(profile_name, {})
        return dict(cfg) if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _profile_float(profile_cfg: dict[str, object], key: str, default: float = 0.0) -> float:
    try:
        return float(profile_cfg.get(key, default))
    except Exception:
        return float(default)


def _profile_int(profile_cfg: dict[str, object] | None, key: str, default: int = 0) -> int:
    try:
        return int(float((profile_cfg or {}).get(key, default)))
    except Exception:
        return int(default)


def _profile_bool(profile_cfg: dict[str, object] | None, key: str, default: bool = False) -> bool:
    raw = (profile_cfg or {}).get(key, default)
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_score_quantile(profile_cfg: dict[str, object] | None, regime_state: object) -> tuple[float, str]:
    """Resolve the pre-pretrade ranking-pool quantile while preserving defaults."""
    defaults = {"正常": 0.60, "震荡": 0.75, "恐慌": 0.85}
    state = str(regime_state or "").strip()
    cfg = profile_cfg or {}
    source = "default_regime_map"
    q = float(defaults.get(state, 0.50))

    raw_map = cfg.get("score_quantile_map", {})
    if isinstance(raw_map, dict) and state in raw_map:
        q = _profile_float(raw_map, state, q)
        source = f"profile_score_quantile_map:{state}"

    state_key_map = {
        "正常": "score_quantile_normal",
        "震荡": "score_quantile_choppy",
        "恐慌": "score_quantile_panic",
    }
    state_key = state_key_map.get(state, "")
    if state_key and state_key in cfg:
        q = _profile_float(cfg, state_key, q)
        source = state_key

    if "score_quantile_q" in cfg:
        q = _profile_float(cfg, "score_quantile_q", q)
        source = "score_quantile_q"

    return min(max(float(q), 0.0), 1.0), source


def _apply_target_score_blend(
    work: pd.DataFrame,
    *,
    ranking_col: str,
    profile_cfg: dict[str, object],
) -> tuple[pd.DataFrame, str, dict[str, object]]:
    raw = profile_cfg.get("target_score_blend", {})
    if not isinstance(raw, dict) or not raw:
        target_score_col = str(profile_cfg.get("target_score_col", ranking_col) or ranking_col).strip()
        if target_score_col and target_score_col in work.columns:
            return work, target_score_col, {"enabled": False, "target_score_col": str(target_score_col)}
        return work, ranking_col, {"enabled": False, "target_score_col": str(ranking_col)}

    weighted: list[tuple[str, float, pd.Series]] = []
    for col, raw_weight in raw.items():
        col_name = str(col).strip()
        weight = _profile_float(raw, col_name, 0.0)
        if weight <= 0.0 or col_name not in work.columns:
            continue
        weighted.append((col_name, float(weight), _norm01_series(work[col_name])))
    if not weighted:
        return work, ranking_col, {
            "enabled": False,
            "target_score_col": str(ranking_col),
            "reason": "no_valid_target_score_blend_cols",
        }

    total = sum(w for _, w, _ in weighted)
    out = work.copy()
    blended = pd.Series(0.0, index=out.index, dtype=float)
    blend_cols: dict[str, float] = {}
    for col_name, weight, score in weighted:
        normalized_weight = float(weight / max(total, 1e-12))
        blended = blended + normalized_weight * score
        blend_cols[col_name] = normalized_weight
    out["target_blend_score"] = blended.clip(0.0, 1.0)
    return out, "target_blend_score", {
        "enabled": True,
        "target_score_col": "target_blend_score",
        "target_score_blend": blend_cols,
    }


def _holiday_gap_reason_override(profile_cfg: dict[str, object] | None, reason: str) -> dict[str, object]:
    raw = (profile_cfg or {}).get("holiday_gap_reason_overrides", {})
    if not isinstance(raw, dict):
        return {}
    value = raw.get(str(reason), {})
    return dict(value) if isinstance(value, dict) else {}


def _resolve_candidate_pool_n(top_n: int, available_n: int, profile_cfg: dict[str, object] | None) -> int:
    """Return the optimizer/pretrade candidate pool size for reserve replacement."""
    top_n = max(1, int(top_n))
    available_n = max(0, int(available_n))
    if available_n <= 0:
        return 0
    cfg = profile_cfg or {}
    multiplier = max(1.0, _profile_float(cfg, "optimizer_candidate_pool_multiplier", 1.0))
    reserve_count = max(0, _profile_int(cfg, "reserve_candidate_count", 0))
    pool_n = max(top_n, int(np.ceil(float(top_n) * multiplier)), top_n + reserve_count)
    max_n = max(0, _profile_int(cfg, "optimizer_candidate_pool_max_n", 0))
    if max_n > 0:
        pool_n = min(pool_n, max(top_n, max_n))
    return max(1, min(int(pool_n), available_n))


def _build_holiday_gap_guard_info(
    trade_dates: pd.Series | list[object],
    signal_date: pd.Timestamp,
    profile_cfg: dict[str, object] | None,
    *,
    total_target: float,
    single_cap: float,
) -> dict[str, object]:
    """Build signal-date-known holiday/long-gap target caps.

    The guard uses only the exchange calendar implied by available trade dates,
    not future prices or tradability outcomes. It is designed for A-share
    T+1 risk around long non-trading gaps, where a position entered before a
    holiday can become an exit trap on the next trading day.
    """
    cfg = profile_cfg or {}
    enabled = _profile_bool(cfg, "holiday_gap_guard_enabled", False)
    min_gap = max(2, _profile_int(cfg, "holiday_gap_min_calendar_days", 4))
    total_target = min(max(float(total_target), 0.0), 1.0)
    single_cap = min(max(float(single_cap), 0.0), 1.0)
    dates = (
        pd.Series(trade_dates)
        .pipe(pd.to_datetime, errors="coerce")
        .dropna()
        .dt.normalize()
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    signal_ts = pd.Timestamp(signal_date).normalize()
    next_trade = next((d for d in dates if d > signal_ts), None)
    post_trade_next = next((d for d in dates if next_trade is not None and d > next_trade), None)
    signal_trade_gap_days = int((next_trade - signal_ts).days) if next_trade is not None else 0
    post_trade_gap_days = int((post_trade_next - next_trade).days) if post_trade_next is not None and next_trade is not None else 0
    max_gap = max(signal_trade_gap_days, post_trade_gap_days)
    guard = bool(enabled and max_gap >= min_gap)
    if guard and signal_trade_gap_days >= min_gap and post_trade_gap_days >= min_gap:
        reason = "signal_to_trade_gap+post_trade_gap"
    elif guard and signal_trade_gap_days >= min_gap:
        reason = "signal_to_trade_gap"
    elif guard and post_trade_gap_days >= min_gap:
        reason = "post_trade_gap"
    else:
        reason = "none"
    total_cap = min(max(_profile_float(cfg, "holiday_gap_total_position_cap", total_target), 0.0), 1.0)
    single_cap_limit = min(max(_profile_float(cfg, "holiday_gap_single_pos_cap", single_cap), 0.0), 1.0)
    reason_override = _holiday_gap_reason_override(cfg, reason) if guard else {}
    if reason_override:
        total_cap = min(
            max(
                _profile_float(
                    reason_override,
                    "total_position_cap",
                    _profile_float(reason_override, "holiday_gap_total_position_cap", total_cap),
                ),
                0.0,
            ),
            1.0,
        )
        single_cap_limit = min(
            max(
                _profile_float(
                    reason_override,
                    "single_pos_cap",
                    _profile_float(reason_override, "holiday_gap_single_pos_cap", single_cap_limit),
                ),
                0.0,
            ),
            1.0,
        )
    adjusted_total = min(total_target, total_cap) if guard else total_target
    adjusted_single = min(single_cap, single_cap_limit) if guard else single_cap
    scale = float(adjusted_total / max(total_target, 1e-12)) if total_target > 0 else 0.0
    if not guard:
        scale = 1.0
    return {
        "enabled": bool(enabled),
        "guard": bool(guard),
        "reason": reason,
        "reason_override_applied": bool(reason_override),
        "min_calendar_gap_days": int(min_gap),
        "signal_trade_gap_days": int(signal_trade_gap_days),
        "post_trade_gap_days": int(post_trade_gap_days),
        "next_trade_date": next_trade.strftime("%Y-%m-%d") if next_trade is not None else "",
        "post_trade_next_date": post_trade_next.strftime("%Y-%m-%d") if post_trade_next is not None else "",
        "original_total_target": float(total_target),
        "adjusted_total_target": float(adjusted_total),
        "original_single_cap": float(single_cap),
        "adjusted_single_cap": float(adjusted_single),
        "target_scale": float(scale),
    }


def _sanitize_profile_slug(raw: object) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", str(raw or "").strip()).strip("_")
    return s


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


def _ensure_capacity_amount_columns(work: pd.DataFrame) -> pd.DataFrame:
    out = work.copy()
    if "amount_last" not in out.columns:
        out["amount_last"] = pd.to_numeric(out.get("amount", 0.0), errors="coerce").fillna(0.0)
    for col in ("amount_ma20", "amount_last", "amount_min5", "amount_min10"):
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if "amount_capacity_conservative" not in out.columns:
        out["amount_capacity_conservative"] = [
            _positive_min([ma20, last, min5, min10])
            for ma20, last, min5, min10 in out[
                ["amount_ma20", "amount_last", "amount_min5", "amount_min10"]
            ].itertuples(index=False, name=None)
        ]
    return out


def _vol_ratio_safety(raw: pd.Series, *, low: float, high: float) -> pd.Series:
    s = pd.to_numeric(raw, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(1.0)
    low = max(float(low), 1e-6)
    high = max(float(high), low + 1e-6)
    score = pd.Series(1.0, index=s.index, dtype=float)
    score.loc[s < low] = (s.loc[s < low] / low).clip(0.0, 1.0)
    score.loc[s > high] = (high / s.loc[s > high]).clip(0.0, 1.0)
    return score.clip(0.0, 1.0)


def _add_tradability_safe_scores(
    pool: pd.DataFrame,
    *,
    profile_cfg: dict[str, object],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Add signal-date-only tradability safety scores for A-share candidate generation."""
    if pool is None or pool.empty:
        return pool, {"enabled": False, "reason": "empty"}
    out = _ensure_capacity_amount_columns(pool)
    code_col = "ts_code" if "ts_code" in out.columns else "代码"
    name_col = "name" if "name" in out.columns else ("名称" if "名称" in out.columns else "")
    codes = out.get(code_col, pd.Series("", index=out.index)).astype(str)
    names = out.get(name_col, pd.Series("", index=out.index)).astype(str) if name_col else pd.Series("", index=out.index)
    limit_ratio = pd.Series(limit_ratio_vectorized(codes, names), index=out.index, dtype=float).clip(lower=0.01)
    close = pd.to_numeric(out.get("close", out.get("收盘价", np.nan)), errors="coerce")
    prev_close = pd.to_numeric(out.get("close_1", out.get("prev_close", np.nan)), errors="coerce")
    high = pd.to_numeric(out.get("high", close), errors="coerce")
    pct_chg = pd.to_numeric(out.get("pct_chg", out.get("涨跌幅%", 0.0)), errors="coerce").fillna(0.0)

    limit_up = prev_close * (1.0 + limit_ratio)
    limit_down = prev_close * (1.0 - limit_ratio)
    valid_limit = close.gt(0) & prev_close.gt(0) & limit_up.gt(0)
    headroom_pct = pd.Series(0.0, index=out.index, dtype=float)
    headroom_pct.loc[valid_limit] = ((limit_up.loc[valid_limit] - close.loc[valid_limit]) / close.loc[valid_limit] * 100.0)
    headroom_pct = headroom_pct.replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(lower=0.0)
    headroom_floor_pct = max(0.1, _profile_float(profile_cfg, "tradability_limit_headroom_pct", 3.5))
    limit_headroom_score = (headroom_pct / headroom_floor_pct).clip(0.0, 1.0)

    hot_pct_of_limit = min(max(_profile_float(profile_cfg, "tradability_hot_pct_of_limit", 0.75), 0.1), 1.0)
    hot_threshold = (limit_ratio * 100.0 * hot_pct_of_limit).clip(lower=0.1)
    hot_move_score = (1.0 - (pct_chg.clip(lower=0.0) / hot_threshold).clip(0.0, 1.0)).clip(0.0, 1.0)

    max_abs_pct = max(0.1, _profile_float(profile_cfg, "max_abs_pct_chg", 8.0))
    calm_abs_move_score = (1.0 - (pct_chg.abs() / max_abs_pct).clip(0.0, 1.0)).clip(0.0, 1.0)

    high_touch_buffer = min(max(_profile_float(profile_cfg, "tradability_high_touch_buffer", 0.985), 0.90), 1.01)
    high_touch_risk = pd.Series(0.0, index=out.index, dtype=float)
    high_touch_risk.loc[valid_limit] = (high.loc[valid_limit] >= limit_up.loc[valid_limit] * high_touch_buffer).astype(float)
    high_touch_score = (1.0 - high_touch_risk).clip(0.0, 1.0)

    low = pd.to_numeric(out.get("low", close), errors="coerce")
    downside_headroom_pct = pd.Series(0.0, index=out.index, dtype=float)
    valid_down_limit = close.gt(0) & prev_close.gt(0) & limit_down.gt(0)
    downside_headroom_pct.loc[valid_down_limit] = (
        (close.loc[valid_down_limit] - limit_down.loc[valid_down_limit])
        / close.loc[valid_down_limit]
        * 100.0
    )
    downside_headroom_pct = downside_headroom_pct.replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(lower=0.0)
    exit_headroom_floor_pct = max(0.1, _profile_float(profile_cfg, "exit_trap_downside_headroom_pct", 3.5))
    exit_headroom_score = (downside_headroom_pct / exit_headroom_floor_pct).clip(0.0, 1.0)
    exit_hot_pct_of_limit = min(max(_profile_float(profile_cfg, "exit_trap_hot_pct_of_limit", 0.55), 0.1), 1.0)
    sell_pressure_threshold = (limit_ratio * 100.0 * exit_hot_pct_of_limit).clip(lower=0.1)
    sell_pressure = (-pct_chg.clip(upper=0.0)).clip(lower=0.0)
    sell_pressure_score = (1.0 - (sell_pressure / sell_pressure_threshold).clip(0.0, 1.0)).clip(0.0, 1.0)
    low_touch_buffer = min(max(_profile_float(profile_cfg, "exit_trap_low_touch_buffer", 1.015), 1.0), 1.10)
    low_touch_risk = pd.Series(0.0, index=out.index, dtype=float)
    low_touch_risk.loc[valid_down_limit] = (low.loc[valid_down_limit] <= limit_down.loc[valid_down_limit] * low_touch_buffer).astype(float)
    low_touch_score = (1.0 - low_touch_risk).clip(0.0, 1.0)

    vol_score = _vol_ratio_safety(
        out.get("vol_ratio", pd.Series(1.0, index=out.index)),
        low=_profile_float(profile_cfg, "tradability_vol_ratio_low", 0.30),
        high=_profile_float(profile_cfg, "tradability_vol_ratio_high", 3.0),
    )
    vol_ratio_raw = (
        pd.to_numeric(out.get("vol_ratio", pd.Series(1.0, index=out.index)), errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(1.0)
    )
    vol_ratio_low_floor = max(_profile_float(profile_cfg, "tradability_vol_ratio_low", 0.30), 1e-6)
    vol_ratio_high_floor = max(_profile_float(profile_cfg, "tradability_vol_ratio_high", 3.0), vol_ratio_low_floor + 1e-6)
    exit_trap_volume_drought_risk = (1.0 - (vol_ratio_raw / vol_ratio_low_floor).clip(0.0, 1.0)).clip(0.0, 1.0)
    exit_trap_volume_drought_score = (1.0 - exit_trap_volume_drought_risk).clip(0.0, 1.0)
    exit_trap_volume_surge_risk = ((vol_ratio_raw / vol_ratio_high_floor) - 1.0).clip(0.0, 1.0)
    exit_trap_volume_surge_score = (1.0 - exit_trap_volume_surge_risk).clip(0.0, 1.0)
    drawdown_10d_pct = pd.to_numeric(out.get("drawdown_10d_pct", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0).clip(lower=0.0)
    drawdown_floor_pct = max(0.1, _profile_float(profile_cfg, "exit_trap_drawdown_floor_pct", 12.0))
    exit_trap_drawdown_risk = (drawdown_10d_pct / drawdown_floor_pct).clip(0.0, 1.0)
    exit_trap_drawdown_score = (1.0 - exit_trap_drawdown_risk).clip(0.0, 1.0)
    down_momentum_5d = pd.to_numeric(out.get("down_momentum_5d", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0).clip(lower=0.0)
    momentum_floor_pct = max(0.1, _profile_float(profile_cfg, "exit_trap_down_momentum_floor_pct", 8.0))
    exit_trap_momentum_risk = (down_momentum_5d / momentum_floor_pct).clip(0.0, 1.0)
    exit_trap_momentum_score = (1.0 - exit_trap_momentum_risk).clip(0.0, 1.0)
    volatility_10d = pd.to_numeric(out.get("volatility_10d", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0).clip(lower=0.0)
    volatility_floor_pct = max(0.1, _profile_float(profile_cfg, "exit_trap_volatility_floor_pct", 4.0))
    exit_trap_volatility_risk = (volatility_10d / volatility_floor_pct).clip(0.0, 1.0)
    exit_trap_volatility_score = (1.0 - exit_trap_volatility_risk).clip(0.0, 1.0)
    amount_score = _norm01_series(
        np.log1p(pd.to_numeric(out.get("amount_capacity_conservative", out.get("amount_ma20", 0.0)), errors="coerce").fillna(0.0).clip(lower=0.0))
    )

    w_headroom = max(0.0, _profile_float(profile_cfg, "tradability_headroom_blend", 0.30))
    w_hot = max(0.0, _profile_float(profile_cfg, "tradability_hot_blend", 0.25))
    w_vol = max(0.0, _profile_float(profile_cfg, "tradability_volume_blend", 0.20))
    w_calm = max(0.0, _profile_float(profile_cfg, "tradability_calm_blend", 0.15))
    w_amount = max(0.0, _profile_float(profile_cfg, "tradability_amount_blend", 0.10))
    w_touch = max(0.0, _profile_float(profile_cfg, "tradability_high_touch_blend", 0.20))
    total = w_headroom + w_hot + w_vol + w_calm + w_amount + w_touch
    if total <= 1e-12:
        total = 1.0
        w_headroom = 1.0
    tradability_score = (
        w_headroom * limit_headroom_score
        + w_hot * hot_move_score
        + w_vol * vol_score
        + w_calm * calm_abs_move_score
        + w_amount * amount_score
        + w_touch * high_touch_score
    ) / total
    out["tradability_safe_score"] = tradability_score.clip(0.0, 1.0)
    out["tradability_limit_headroom_pct"] = headroom_pct
    out["tradability_hot_move_score"] = hot_move_score
    out["tradability_volume_score"] = vol_score
    out["tradability_high_touch_score"] = high_touch_score
    out["tradability_entry_risk_score"] = (1.0 - out["tradability_safe_score"]).clip(0.0, 1.0)

    w_exit_headroom = max(0.0, _profile_float(profile_cfg, "exit_trap_headroom_blend", 0.35))
    w_exit_pressure = max(0.0, _profile_float(profile_cfg, "exit_trap_pressure_blend", 0.25))
    w_exit_vol = max(0.0, _profile_float(profile_cfg, "exit_trap_volume_blend", 0.15))
    w_exit_amount = max(0.0, _profile_float(profile_cfg, "exit_trap_amount_blend", 0.10))
    w_exit_touch = max(0.0, _profile_float(profile_cfg, "exit_trap_low_touch_blend", 0.15))
    w_exit_calm = max(0.0, _profile_float(profile_cfg, "exit_trap_calm_blend", 0.10))
    w_exit_vol_drought = max(0.0, _profile_float(profile_cfg, "exit_trap_volume_drought_blend", 0.0))
    w_exit_vol_surge = max(0.0, _profile_float(profile_cfg, "exit_trap_volume_surge_blend", 0.0))
    w_exit_drawdown = max(0.0, _profile_float(profile_cfg, "exit_trap_drawdown_blend", 0.0))
    w_exit_momentum = max(0.0, _profile_float(profile_cfg, "exit_trap_down_momentum_blend", 0.0))
    w_exit_volatility = max(0.0, _profile_float(profile_cfg, "exit_trap_volatility_blend", 0.0))
    exit_total = (
        w_exit_headroom
        + w_exit_pressure
        + w_exit_vol
        + w_exit_amount
        + w_exit_touch
        + w_exit_calm
        + w_exit_vol_drought
        + w_exit_vol_surge
        + w_exit_drawdown
        + w_exit_momentum
        + w_exit_volatility
    )
    if exit_total <= 1e-12:
        exit_total = 1.0
        w_exit_headroom = 1.0
    exit_safe_score = (
        w_exit_headroom * exit_headroom_score
        + w_exit_pressure * sell_pressure_score
        + w_exit_vol * vol_score
        + w_exit_amount * amount_score
        + w_exit_touch * low_touch_score
        + w_exit_calm * calm_abs_move_score
        + w_exit_vol_drought * exit_trap_volume_drought_score
        + w_exit_vol_surge * exit_trap_volume_surge_score
        + w_exit_drawdown * exit_trap_drawdown_score
        + w_exit_momentum * exit_trap_momentum_score
        + w_exit_volatility * exit_trap_volatility_score
    ) / exit_total
    out["exit_trap_safe_score"] = exit_safe_score.clip(0.0, 1.0)
    out["exit_trap_risk_score"] = (1.0 - out["exit_trap_safe_score"]).clip(0.0, 1.0)
    out["exit_trap_downside_headroom_pct"] = downside_headroom_pct
    out["exit_trap_low_touch_score"] = low_touch_score
    out["exit_trap_volume_drought_risk"] = exit_trap_volume_drought_risk
    out["exit_trap_volume_surge_risk"] = exit_trap_volume_surge_risk
    out["exit_trap_drawdown_10d_pct"] = drawdown_10d_pct
    out["exit_trap_down_momentum_5d"] = down_momentum_5d
    out["exit_trap_volatility_10d"] = volatility_10d
    return out, {
        "enabled": True,
        "mean_score": float(pd.to_numeric(out["tradability_safe_score"], errors="coerce").mean()),
        "low_score_count": int((pd.to_numeric(out["tradability_safe_score"], errors="coerce").fillna(0.0) < 0.35).sum()),
        "near_limit_count": int((headroom_pct < headroom_floor_pct).sum()),
        "high_touch_count": int(high_touch_risk.sum()),
        "headroom_floor_pct": float(headroom_floor_pct),
        "exit_trap_risk_mean": float(pd.to_numeric(out["exit_trap_risk_score"], errors="coerce").mean()),
        "exit_trap_high_risk_count": int((pd.to_numeric(out["exit_trap_risk_score"], errors="coerce").fillna(0.0) >= 0.65).sum()),
        "exit_trap_low_touch_count": int(low_touch_risk.sum()),
        "exit_trap_headroom_floor_pct": float(exit_headroom_floor_pct),
        "exit_trap_volume_drought_risk_mean": float(pd.to_numeric(out["exit_trap_volume_drought_risk"], errors="coerce").mean()),
        "exit_trap_drawdown_10d_mean": float(pd.to_numeric(out["exit_trap_drawdown_10d_pct"], errors="coerce").mean()),
    }


def _apply_tradability_safe_ranking(
    pool: pd.DataFrame,
    *,
    ranking_col: str,
    profile_cfg: dict[str, object],
) -> tuple[pd.DataFrame, str, dict[str, object]]:
    work, info = _add_tradability_safe_scores(pool, profile_cfg=profile_cfg)
    if work is None or work.empty:
        return work, ranking_col, info
    enabled = _profile_bool(profile_cfg, "tradability_safe_ranking_enabled", False)
    blend = min(max(_profile_float(profile_cfg, "tradability_rank_blend", 0.0), 0.0), 0.8)
    if not enabled or blend <= 1e-12:
        work["tradability_adjusted_score"] = pd.to_numeric(work.get(ranking_col, 0.0), errors="coerce").fillna(0.0)
        info.update({"ranking_enabled": False, "ranking_col": str(ranking_col), "rank_blend": 0.0})
        return work, ranking_col, info
    rank_score = _norm01_series(work.get(ranking_col, pd.Series(0.0, index=work.index)))
    safe_score = pd.to_numeric(work["tradability_safe_score"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    exit_blend = (
        min(max(_profile_float(profile_cfg, "exit_trap_rank_blend", 0.0), 0.0), 0.8)
        if _profile_bool(profile_cfg, "exit_trap_ranking_enabled", False)
        else 0.0
    )
    exit_safe = pd.to_numeric(work.get("exit_trap_safe_score", 0.5), errors="coerce").fillna(0.5).clip(0.0, 1.0)
    combined_safe = ((1.0 - exit_blend) * safe_score + exit_blend * exit_safe).clip(0.0, 1.0)
    work["tradability_adjusted_score"] = ((1.0 - blend) * rank_score + blend * combined_safe).clip(0.0, 1.0)
    info.update(
        {
            "ranking_enabled": True,
            "ranking_col": "tradability_adjusted_score",
            "rank_blend": float(blend),
            "exit_trap_rank_blend": float(exit_blend),
        }
    )
    return work, "tradability_adjusted_score", info


def _prepare_capacity_safe_reserve_pool(
    pool: pd.DataFrame,
    *,
    ranking_col: str,
    primary_top_n: int,
    profile_cfg: dict[str, object],
) -> tuple[pd.DataFrame, str, dict[str, object]]:
    """Keep primary ranking intact, but rank reserve rows by capacity safety."""
    if pool is None or pool.empty:
        return pool, ranking_col, {"enabled": False, "reason": "empty"}
    if not _profile_bool(profile_cfg, "capacity_safe_reserve_enabled", False):
        out = pool.copy()
        out["portfolio_rank_score"] = pd.to_numeric(out.get(ranking_col, 0.0), errors="coerce").fillna(0.0)
        out["reserve_safe_score"] = 0.0
        out["reserve_capacity_score"] = 0.0
        return out, ranking_col, {"enabled": False, "reason": "disabled"}

    work = pool.copy()
    if ranking_col not in work.columns:
        work[ranking_col] = 0.0
    work[ranking_col] = pd.to_numeric(work[ranking_col], errors="coerce").fillna(0.0)
    work = _ensure_capacity_amount_columns(work)

    primary_n = max(1, min(int(primary_top_n), len(work)))
    amount_col = str(profile_cfg.get("capacity_safe_reserve_amount_col", "") or "").strip()
    if not amount_col:
        amount_col = str(profile_cfg.get("target_capacity_amount_col", "amount_capacity_conservative") or "amount_capacity_conservative")
    if amount_col not in work.columns:
        amount_col = "amount_capacity_conservative" if "amount_capacity_conservative" in work.columns else "amount_ma20"

    rank_score = _norm01_series(work[ranking_col])
    amount_score = _norm01_series(np.log1p(pd.to_numeric(work.get(amount_col, 0.0), errors="coerce").fillna(0.0).clip(lower=0.0)))
    adv_score = _norm01_series(work.get("adv_capacity_score", amount_score))
    liquidity_score = _norm01_series(work.get("liquidity_score", amount_score))
    industry_score = _norm01_series(work.get("industry_balance_score", 0.5))
    tradability_score = _norm01_series(
        work["tradability_safe_score"]
        if "tradability_safe_score" in work.columns
        else pd.Series(0.5, index=work.index, dtype=float)
    )
    exit_trap_score = _norm01_series(
        work["exit_trap_safe_score"]
        if "exit_trap_safe_score" in work.columns
        else pd.Series(0.5, index=work.index, dtype=float)
    )
    quality_score = _norm01_series(work.get("signal_quality", rank_score))
    abs_pct = pd.to_numeric(work.get("pct_chg", 0.0), errors="coerce").fillna(0.0).abs()
    calm_score = 1.0 - _norm01_series(abs_pct)

    capacity_blend = min(max(_profile_float(profile_cfg, "reserve_capacity_blend", 0.45), 0.0), 1.0)
    rank_blend = min(max(_profile_float(profile_cfg, "reserve_rank_blend", 0.30), 0.0), 1.0)
    liquidity_blend = min(max(_profile_float(profile_cfg, "reserve_liquidity_blend", 0.10), 0.0), 1.0)
    industry_blend = min(max(_profile_float(profile_cfg, "reserve_industry_blend", 0.10), 0.0), 1.0)
    calm_blend = min(max(_profile_float(profile_cfg, "reserve_calm_blend", 0.05), 0.0), 1.0)
    quality_blend = min(max(_profile_float(profile_cfg, "reserve_quality_blend", 0.0), 0.0), 1.0)
    tradability_blend = min(max(_profile_float(profile_cfg, "reserve_tradability_blend", 0.0), 0.0), 1.0)
    exit_trap_blend = min(max(_profile_float(profile_cfg, "reserve_exit_trap_blend", 0.0), 0.0), 1.0)
    if _profile_bool(profile_cfg, "tradability_safe_reserve_enabled", False) and tradability_blend <= 1e-12:
        tradability_blend = 0.15
    if _profile_bool(profile_cfg, "exit_trap_safe_reserve_enabled", False) and exit_trap_blend <= 1e-12:
        exit_trap_blend = 0.15
    raw_total = (
        capacity_blend
        + rank_blend
        + liquidity_blend
        + industry_blend
        + calm_blend
        + quality_blend
        + tradability_blend
        + exit_trap_blend
    )
    if raw_total <= 1e-12:
        raw_total = 1.0
        capacity_blend = 1.0

    capacity_score = (0.65 * amount_score + 0.35 * adv_score).clip(0.0, 1.0)
    safe_score = (
        capacity_blend * capacity_score
        + rank_blend * rank_score
        + liquidity_blend * liquidity_score
        + industry_blend * industry_score
        + calm_blend * calm_score
        + quality_blend * quality_score
        + tradability_blend * tradability_score
        + exit_trap_blend * exit_trap_score
    ) / raw_total
    safe_score = safe_score.clip(0.0, 1.0)

    work["_original_rank_score"] = rank_score
    work["reserve_capacity_score"] = capacity_score
    work["reserve_safe_score"] = safe_score
    primary_rank_mode = str(
        profile_cfg.get("capacity_safe_primary_rank_mode", "reserve_only") or "reserve_only"
    ).strip().lower()
    primary_rank_blend = min(max(_profile_float(profile_cfg, "capacity_safe_primary_rank_blend", 0.0), 0.0), 1.0)
    if primary_rank_mode in {"target_score_topn", "score_topn"}:
        work, label_score_col, label_score_info = _apply_target_score_blend(
            work,
            ranking_col=ranking_col,
            profile_cfg=profile_cfg,
        )
        explicit_label_col = str(profile_cfg.get("capacity_safe_primary_label_score_col", "") or "").strip()
        if explicit_label_col and explicit_label_col in work.columns:
            label_score_col = explicit_label_col
        if label_score_col not in work.columns:
            label_score_col = ranking_col
        work[label_score_col] = pd.to_numeric(work[label_score_col], errors="coerce").fillna(0.0)
        out = work.sort_values(label_score_col, ascending=False).reset_index(drop=True)
        out["reserve_candidate"] = (np.arange(len(out)) >= primary_n).astype(int)
        out["portfolio_rank_score"] = 1.0 + _norm01_series(out[label_score_col])
        reserves = out[out["reserve_candidate"].astype(int).eq(1)]
        return out, "portfolio_rank_score", {
            "enabled": True,
            "primary_top_n": int(primary_n),
            "amount_col": str(amount_col),
            "reserve_rows": int(len(reserves)),
            "reserve_safe_score_mean": float(
                pd.to_numeric(reserves.get("reserve_safe_score", pd.Series(dtype=float)), errors="coerce").mean()
            )
            if not reserves.empty
            else 0.0,
            "reserve_tradability_blend": float(tradability_blend),
            "reserve_exit_trap_blend": float(exit_trap_blend),
            "reserve_tradability_score_mean": float(
                pd.to_numeric(reserves.get("tradability_safe_score", pd.Series(dtype=float)), errors="coerce").mean()
            )
            if (not reserves.empty and "tradability_safe_score" in reserves.columns)
            else 0.0,
            "reserve_exit_trap_safe_score_mean": float(
                pd.to_numeric(reserves.get("exit_trap_safe_score", pd.Series(dtype=float)), errors="coerce").mean()
            )
            if (not reserves.empty and "exit_trap_safe_score" in reserves.columns)
            else 0.0,
            "primary_rank_mode": primary_rank_mode,
            "primary_rank_blend": float(primary_rank_blend),
            "primary_label_score_col": str(label_score_col),
            "primary_label_score_info": label_score_info,
        }
    if primary_rank_mode in {"blend_full_pool", "full_pool_blend", "safe_full_pool"} and primary_rank_blend > 0.0:
        work["capacity_safe_primary_score"] = (
            (1.0 - primary_rank_blend) * rank_score + primary_rank_blend * safe_score
        ).clip(0.0, 1.0)
        work = work.sort_values(ranking_col, ascending=False).reset_index(drop=True)
        work["reserve_candidate"] = (np.arange(len(work)) >= primary_n).astype(int)
        out = work.sort_values("capacity_safe_primary_score", ascending=False).reset_index(drop=True)
        out["portfolio_rank_score"] = 1.0 + pd.to_numeric(
            out["capacity_safe_primary_score"], errors="coerce"
        ).fillna(0.0)
        return out, "portfolio_rank_score", {
            "enabled": True,
            "primary_top_n": int(primary_n),
            "amount_col": str(amount_col),
            "reserve_rows": int(len(out[out["reserve_candidate"].astype(int).eq(1)])),
            "reserve_safe_score_mean": float(
                pd.to_numeric(
                    out.loc[out["reserve_candidate"].astype(int).eq(1), "reserve_safe_score"],
                    errors="coerce",
                ).mean()
            ),
            "reserve_tradability_blend": float(tradability_blend),
            "reserve_exit_trap_blend": float(exit_trap_blend),
            "reserve_tradability_score_mean": float(
                pd.to_numeric(
                    out.loc[out["reserve_candidate"].astype(int).eq(1), "tradability_safe_score"],
                    errors="coerce",
                ).mean()
            )
            if "tradability_safe_score" in out.columns
            else 0.0,
            "reserve_exit_trap_safe_score_mean": float(
                pd.to_numeric(
                    out.loc[out["reserve_candidate"].astype(int).eq(1), "exit_trap_safe_score"],
                    errors="coerce",
                ).mean()
            )
            if "exit_trap_safe_score" in out.columns
            else 0.0,
            "primary_rank_mode": primary_rank_mode,
            "primary_rank_blend": float(primary_rank_blend),
        }
    work = work.sort_values(ranking_col, ascending=False).reset_index(drop=True)
    work["reserve_candidate"] = (np.arange(len(work)) >= primary_n).astype(int)
    primary = work.iloc[:primary_n].copy()
    reserve = work.iloc[primary_n:].copy()
    primary["portfolio_rank_score"] = 2.0 + _norm01_series(primary[ranking_col])
    reserve["portfolio_rank_score"] = 1.0 + pd.to_numeric(reserve["reserve_safe_score"], errors="coerce").fillna(0.0)
    out = pd.concat([primary, reserve], ignore_index=True)
    out = out.sort_values("portfolio_rank_score", ascending=False).reset_index(drop=True)
    return out, "portfolio_rank_score", {
        "enabled": True,
        "primary_top_n": int(primary_n),
        "amount_col": str(amount_col),
        "reserve_rows": int(len(reserve)),
        "reserve_safe_score_mean": float(pd.to_numeric(reserve.get("reserve_safe_score", pd.Series(dtype=float)), errors="coerce").mean()) if not reserve.empty else 0.0,
        "reserve_tradability_blend": float(tradability_blend),
        "reserve_exit_trap_blend": float(exit_trap_blend),
        "reserve_tradability_score_mean": float(pd.to_numeric(reserve.get("tradability_safe_score", pd.Series(dtype=float)), errors="coerce").mean()) if not reserve.empty else 0.0,
        "reserve_exit_trap_safe_score_mean": float(pd.to_numeric(reserve.get("exit_trap_safe_score", pd.Series(dtype=float)), errors="coerce").mean()) if not reserve.empty else 0.0,
        "primary_rank_mode": primary_rank_mode,
        "primary_rank_blend": float(primary_rank_blend),
    }


def load_latest_model():
    """加载最新的训练模型"""
    if not os.path.exists(MODEL_DIR):
        raise FileNotFoundError(f"模型目录不存在: {MODEL_DIR}")
        
    model_files = sorted([f for f in os.listdir(MODEL_DIR) if f.startswith('mfts_lgbm_') and f.endswith('.pkl')])
    
    if not model_files:
        raise FileNotFoundError("未找到训练好的模型！请先运行 train_mfts_lgbm.py")
    
    latest_model = os.path.join(MODEL_DIR, model_files[-1])
    print(f"加载模型: {latest_model}")

    cache_enabled = _parse_bool_like(os.environ.get("MFTS_DAILY_SELECT_CACHE_MODEL", "true"), default=True)
    cache_key = os.path.abspath(latest_model)
    if cache_enabled and cache_key in _MODEL_CACHE:
        model_pkg = _MODEL_CACHE[cache_key]
        model_info = {
            'label_mode': model_pkg.get('label_mode', 'unknown'),
            'label_horizon': model_pkg.get('label_horizon', None),
            'execution_hint': model_pkg.get('execution_hint', ''),
            'timestamp': model_pkg.get('timestamp', ''),
        }
        return model_pkg['model'], model_pkg['feature_cols'], model_info
    
    with open(latest_model, 'rb') as f:
        model_pkg = pickle.load(f)
    if cache_enabled:
        _MODEL_CACHE.clear()
        _MODEL_CACHE[cache_key] = model_pkg
    
    model_info = {
        'label_mode': model_pkg.get('label_mode', 'unknown'),
        'label_horizon': model_pkg.get('label_horizon', None),
        'execution_hint': model_pkg.get('execution_hint', ''),
        'timestamp': model_pkg.get('timestamp', ''),
    }
    return model_pkg['model'], model_pkg['feature_cols'], model_info


def load_latest_data(
    *,
    columns: list[str] | None = None,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
):
    """Load a column/date slice from the canonical read-only ODS gateway."""
    read_cols = None
    if columns:
        read_cols = sorted(set(["ts_code", "trade_date"]) | set(columns))
    gateway = AShareMarketDataGateway()
    if start_date is None or end_date is None:
        available_dates = gateway.available_trade_dates()
        if not available_dates:
            raise RuntimeError("共享 ODS daily_bars 没有可用交易日")
    else:
        available_dates = []
    start_ts = pd.Timestamp(start_date).normalize() if start_date is not None else pd.Timestamp(available_dates[0])
    end_ts = pd.Timestamp(end_date).normalize() if end_date is not None else pd.Timestamp(available_dates[-1])
    if end_ts < start_ts:
        raise ValueError(f"end_date {end_ts.date()} is before start_date {start_ts.date()}")
    cache_enabled = _parse_bool_like(os.environ.get("MFTS_DAILY_SELECT_CACHE_DATA", "false"), default=False)
    cache_key = (
        tuple(read_cols or ["__all__"]),
        start_ts.strftime("%Y%m%d"),
        end_ts.strftime("%Y%m%d"),
    )
    if cache_enabled:
        if cache_key not in _DATA_CACHE:
            _DATA_CACHE[cache_key] = gateway.load_bars(start_ts, end_ts, include_bj9=False)
        df = _DATA_CACHE[cache_key].copy()
    else:
        df = gateway.load_bars(start_ts, end_ts, include_bj9=False)
    lineage = dict(df.attrs.get("market_data_lineage", {}))

    df['trade_date'] = pd.to_datetime(df['trade_date'], errors="coerce")
    df['ts_code'] = normalize_ts_code_series(df['ts_code'])
    df = df[df['ts_code'] != ''].copy()
    df = df[(df['trade_date'] >= start_ts) & (df['trade_date'] <= end_ts)].copy()
    if read_cols:
        missing = [column for column in read_cols if column not in df.columns]
        if missing:
            raise RuntimeError(f"共享 ODS 行情缺少请求列: {','.join(missing)}")
        df = df.loc[:, read_cols].copy()
    df.attrs["market_data_lineage"] = lineage
    return df


def _add_selection_window_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['vol_ratio'] = out['vol'] / out['vol_ma20']
    out['rolling_high_10'] = out.groupby('ts_code', observed=True, sort=False)['close'].transform(
        lambda s: s.rolling(10, min_periods=3).max()
    )
    out['drawdown_10d_pct'] = (
        (1.0 - out['close'] / out['rolling_high_10'].replace(0, np.nan)).clip(lower=0.0) * 100.0
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out['volatility_10d'] = out.groupby('ts_code', observed=True, sort=False)['pct_chg'].transform(
        lambda s: pd.to_numeric(s, errors='coerce').rolling(10, min_periods=5).std()
    ).fillna(0.0)
    out['down_momentum_5d'] = (
        -(out['close'] / out['close_5'].replace(0, np.nan) - 1.0).clip(upper=0.0) * 100.0
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    return out


def _load_cached_indicator_window(
    *,
    columns: list[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    cache_start = pd.to_datetime(
        os.environ.get("MFTS_DAILY_SELECT_CACHE_START") or start_date,
        errors="coerce",
    )
    cache_end = pd.to_datetime(
        os.environ.get("MFTS_DAILY_SELECT_CACHE_END") or end_date,
        errors="coerce",
    )
    if pd.isna(cache_start):
        cache_start = pd.Timestamp(start_date)
    if pd.isna(cache_end):
        cache_end = pd.Timestamp(end_date)
    cache_start = pd.Timestamp(cache_start).normalize()
    cache_end = pd.Timestamp(cache_end).normalize()
    cache_key = (tuple(sorted(set(["open", "high", "low", "close", "vol", "amount", "pct_chg", *columns]))), cache_start.strftime("%Y%m%d"), cache_end.strftime("%Y%m%d"))
    if cache_key not in _INDICATOR_DATA_CACHE:
        raw = load_latest_data(columns=list(cache_key[0]), start_date=cache_start, end_date=cache_end)
        raw = raw.sort_values(['ts_code', 'trade_date'])
        enriched = calc_indicators(raw)
        enriched = _add_selection_window_columns(enriched)
        _INDICATOR_DATA_CACHE.clear()
        _INDICATOR_DATA_CACHE[cache_key] = enriched
    cached = _INDICATOR_DATA_CACHE[cache_key]
    mask = (cached["trade_date"] >= pd.Timestamp(start_date).normalize()) & (
        cached["trade_date"] <= pd.Timestamp(end_date).normalize()
    )
    return cached.loc[mask].copy()


def _parse_bool_like(v: object, default: bool = False) -> bool:
    if isinstance(v, bool):
        return bool(v)
    s = str(v or "").strip().lower()
    if not s:
        return bool(default)
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _research_stage_snapshots_enabled(profile_cfg: dict[str, object] | None) -> bool:
    raw = os.environ.get("MFTS_WRITE_RESEARCH_STAGE_SNAPSHOTS", "")
    if raw.strip():
        return _parse_bool_like(raw, default=False)
    return _profile_bool(profile_cfg, "write_research_stage_snapshots", False)


def _append_research_stage_snapshot(
    frames: list[pd.DataFrame],
    df: pd.DataFrame | None,
    *,
    stage: str,
    target_date: pd.Timestamp,
    ranking_col: str,
    extra: dict[str, object] | None = None,
) -> None:
    if df is None or df.empty:
        return
    out = df.copy()
    out["research_stage"] = str(stage)
    out["stage_ranking_col"] = str(ranking_col)
    out["日期"] = pd.Timestamp(target_date).strftime("%Y-%m-%d")
    out["代码"] = normalize_ts_code_series(out.get("ts_code", out.get("代码", "")))
    out = out[out["代码"] != ""].copy()
    if out.empty:
        return
    if ranking_col in out.columns:
        score = pd.to_numeric(out[ranking_col], errors="coerce")
        out["stage_rank"] = score.rank(method="first", ascending=False, na_option="bottom").astype(int)
    else:
        out["stage_rank"] = np.arange(1, len(out) + 1)
    out["排名"] = out["stage_rank"]
    alias_map = {
        "ML评分": "ml_score",
        "质量分": "signal_quality",
        "综合分": "hybrid_score",
        "稳定分": "stability_score",
        "重构分": "refactor_score",
        "流动性分": "liquidity_score",
        "ADV容量分": "adv_capacity_score",
        "行业均衡分": "industry_balance_score",
        "成交额MA20": "amount_ma20",
        "收盘价": "close",
        "涨跌幅%": "pct_chg",
    }
    for alias, source in alias_map.items():
        if alias not in out.columns and source in out.columns:
            out[alias] = out[source]
    if "名称" not in out.columns and "name" in out.columns:
        out["名称"] = out["name"]
    if "行业" not in out.columns and "industry" in out.columns:
        out["行业"] = out["industry"]
    for key, value in (extra or {}).items():
        out[str(key)] = value
    preferred = [
        "日期",
        "research_stage",
        "stage_rank",
        "stage_ranking_col",
        "排名",
        "代码",
        "名称",
        "行业",
        "收盘价",
        "涨跌幅%",
        "ML评分",
        "质量分",
        "综合分",
        "稳定分",
        "重构分",
        "流动性分",
        "ADV容量分",
        "行业均衡分",
        "成交额MA20",
        "portfolio_rank_score",
        "target_blend_score",
        "reserve_safe_score",
        "reserve_capacity_score",
        "tradability_safe_score",
        "exit_trap_safe_score",
        "exit_trap_risk_score",
        "hard_limit_flag",
        "overheat_flag",
        "vol_anomaly_flag",
        "vol_anomaly_low_flag",
        "vol_anomaly_high_flag",
        "target_weight",
        "target_weight_raw",
        "participation_pct",
        "impact_cost_bps",
        "unfilled_target_weight",
        "constraint_reason",
        "reserve_candidate",
        "signal_risk_blocked",
        "signal_risk_reason",
        "stage_pool_n",
        "stage_note",
    ]
    cols = [c for c in preferred if c in out.columns]
    cols += [c for c in out.columns if c not in cols and not str(c).startswith("_")]
    frames.append(out.loc[:, cols].sort_values("stage_rank").reset_index(drop=True))


def _write_research_stage_snapshots(
    frames: list[pd.DataFrame],
    *,
    base_dir: Path,
    output_profile: str,
    date_str: str,
) -> tuple[str, str]:
    if not frames:
        return "", ""
    out = pd.concat(frames, ignore_index=True)
    if out.empty:
        return "", ""
    if output_profile:
        stage_dir = base_dir / "research_stage_profiles" / output_profile
    else:
        stage_dir = base_dir / "research_stage"
    stage_dir.mkdir(parents=True, exist_ok=True)
    dated = stage_dir / f"research_stages_{date_str}.csv"
    latest = stage_dir / "research_stages_latest.csv"
    out.to_csv(dated, index=False, encoding="utf-8-sig")
    out.to_csv(latest, index=False, encoding="utf-8-sig")
    return str(dated), str(latest)


def _parse_percent_text(text: object, fallback: float) -> float:
    s = str(text or "").strip()
    if not s:
        return float(fallback)
    vals = []
    for m in s.replace("~", "-").split("-"):
        m = m.strip()
        if m.endswith("%"):
            m = m[:-1].strip()
        try:
            vals.append(float(m))
        except Exception:
            continue
    if vals:
        return float(np.mean(vals)) / 100.0
    try:
        v = float(s)
        return v / 100.0 if v > 1 else v
    except Exception:
        return float(fallback)


def _resolve_profile_total_position(
    regime_position_range: object,
    profile_cfg: dict[str, object] | None,
    fallback: float = 0.60,
) -> float:
    cfg = profile_cfg or {}
    profile_fallback = min(max(_profile_float(cfg, "fallback_total_position", fallback), 0.0), 1.0)
    if "use_regime_position" in cfg and not _profile_bool(cfg, "use_regime_position", True):
        return float(profile_fallback)
    return min(max(_parse_percent_text(regime_position_range, profile_fallback), 0.0), 1.0)


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _positive_min(values: list[float]) -> float:
    vals = []
    for x in values:
        v = _safe_float(x, 0.0)
        if np.isfinite(v) and v > 0:
            vals.append(float(v))
    return float(min(vals)) if vals else 0.0


def _to_jsonable(obj: object) -> object:
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        x = float(obj)
        return x if np.isfinite(x) else None
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, np.ndarray):
        return [_to_jsonable(x) for x in obj.tolist()]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        if isinstance(obj, float) and (not np.isfinite(obj)):
            return None
        return obj
    try:
        x = float(obj)
        if np.isfinite(x):
            return x
    except Exception:
        pass
    return str(obj)


def _build_bars_idx(df: pd.DataFrame) -> pd.DataFrame:
    def _empty_bars_idx() -> pd.DataFrame:
        out = pd.DataFrame(columns=["open", "high", "low", "close", "vol", "amount"])
        out.index = pd.MultiIndex.from_arrays([[], []], names=["trade_date", "code"])
        return out

    if df is None or df.empty:
        return _empty_bars_idx()
    need_cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
    cols = [c for c in need_cols if c in df.columns]
    if "ts_code" not in cols or "trade_date" not in cols:
        return _empty_bars_idx()
    bars = df[cols].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="coerce").dt.normalize()
    bars["code"] = normalize_ts_code_series(bars["ts_code"])
    bars = bars.dropna(subset=["trade_date"])
    bars = bars[bars["code"] != ""].copy()
    for c in ("open", "high", "low", "close", "vol", "amount"):
        if c in bars.columns:
            bars[c] = pd.to_numeric(bars[c], errors="coerce")
        else:
            bars[c] = np.nan
    bars = bars.sort_values(["trade_date", "code"]).reset_index(drop=True)
    if bars.empty:
        return _empty_bars_idx()
    return bars.set_index(["trade_date", "code"]).sort_index()


def _resolve_next_trade_day(trading_days: list[pd.Timestamp], signal_date: pd.Timestamp) -> pd.Timestamp | None:
    for d in trading_days:
        if d > signal_date:
            return d
    return None


def _top_blocked_reason(blocked_df: pd.DataFrame) -> tuple[str, int]:
    if blocked_df is None or blocked_df.empty or "reasons" not in blocked_df.columns:
        return "none", 0
    counts: dict[str, int] = {}
    for txt in blocked_df["reasons"].astype(str).tolist():
        for r in [x.strip() for x in txt.split(",") if x.strip()]:
            counts[r] = counts.get(r, 0) + 1
    if not counts:
        return "none", 0
    top = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[0]
    return str(top[0]), int(top[1])


def _build_signal_pretrade_cfg_from_env(profile_cfg: dict[str, object] | None = None) -> PreTradeRiskConfig:
    profile_cfg = dict(profile_cfg or {})
    default_adv = _profile_float(profile_cfg, "risk_max_adv_participation", 0.05)
    default_industry_weight = min(max(_profile_float(profile_cfg, "risk_max_industry_weight", 0.35), 0.05), 1.0)
    default_style_size = max(0.0, _profile_float(profile_cfg, "risk_max_style_size_exposure_abs", 0.0))
    default_style_beta = max(0.0, _profile_float(profile_cfg, "risk_max_style_beta_exposure_abs", 0.0))
    default_style_momentum = max(0.0, _profile_float(profile_cfg, "risk_max_style_momentum_exposure_abs", 0.0))
    default_style_vol = max(0.0, _profile_float(profile_cfg, "risk_max_style_vol_exposure_abs", 0.0))
    default_style_basis = str(profile_cfg.get("risk_style_exposure_basis", "invested_weighted") or "invested_weighted")
    default_style_lb_short = max(5, _profile_int(profile_cfg, "risk_style_lb_short", 20))
    default_style_lb_beta = max(10, _profile_int(profile_cfg, "risk_style_lb_beta", 60))
    default_min_price = max(
        0.0,
        _profile_float(
            profile_cfg,
            "risk_min_price",
            _profile_float(profile_cfg, "min_price", 2.0),
        ),
    )
    return PreTradeRiskConfig(
        enabled=True,
        capital_base=max(100000.0, _safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_CAPITAL_BASE", "1000000"), 1000000.0)),
        max_industry_weight=min(
            max(_safe_float(os.environ.get("MFTS_RISK_MAX_INDUSTRY_WEIGHT", str(default_industry_weight)), default_industry_weight), 0.05),
            1.0,
        ),
        max_adv_participation=min(
            max(_safe_float(os.environ.get("MFTS_RISK_MAX_ADV_PARTICIPATION", str(default_adv)), default_adv), 0.001),
            0.50,
        ),
        min_price=max(
            0.0,
            _safe_float(os.environ.get("MFTS_RISK_MIN_PRICE", str(default_min_price)), default_min_price),
        ),
        max_style_size_exposure_abs=max(
            0.0,
            _safe_float(os.environ.get("MFTS_RISK_MAX_STYLE_SIZE_EXPOSURE_ABS", str(default_style_size)), default_style_size),
        ),
        max_style_beta_exposure_abs=max(
            0.0,
            _safe_float(os.environ.get("MFTS_RISK_MAX_STYLE_BETA_EXPOSURE_ABS", str(default_style_beta)), default_style_beta),
        ),
        max_style_momentum_exposure_abs=max(
            0.0,
            _safe_float(
                os.environ.get("MFTS_RISK_MAX_STYLE_MOMENTUM_EXPOSURE_ABS", str(default_style_momentum)),
                default_style_momentum,
            ),
        ),
        max_style_vol_exposure_abs=max(
            0.0,
            _safe_float(os.environ.get("MFTS_RISK_MAX_STYLE_VOL_EXPOSURE_ABS", str(default_style_vol)), default_style_vol),
        ),
        style_exposure_basis=str(os.environ.get("MFTS_RISK_STYLE_EXPOSURE_BASIS", default_style_basis) or default_style_basis),
        style_lb_short=max(
            5,
            int(_safe_float(os.environ.get("MFTS_RISK_STYLE_LB_SHORT", str(default_style_lb_short)), default_style_lb_short)),
        ),
        style_lb_beta=max(
            10,
            int(_safe_float(os.environ.get("MFTS_RISK_STYLE_LB_BETA", str(default_style_lb_beta)), default_style_lb_beta)),
        ),
        blacklist_codes=_load_blacklist(os.environ.get("MFTS_RISK_BLACKLIST_FILE", "")),
    )


def _apply_signal_pretrade_gate(
    *,
    ranking_pool: pd.DataFrame,
    ranking_col: str,
    bars_window_df: pd.DataFrame,
    signal_date: pd.Timestamp,
    top_n: int,
    regime_position_range: object,
    regime_single_stock_max: object,
    profile_cfg: dict[str, object] | None = None,
    industry_map: dict[str, str] | None = None,
    data_dir: str | Path = DATA_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    info: dict[str, object] = {
        "enabled": False,
        "stage": "pretrade_off",
        "trade_date": pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
        "pool_n": 0,
        "kept_count": int(len(ranking_pool)),
        "blocked_count": 0,
        "blocked_rate_pct": 0.0,
        "top_reason": "none",
        "top_reason_count": 0,
    }
    if ranking_pool.empty:
        return ranking_pool, pd.DataFrame(), info

    enabled = _parse_bool_like(os.environ.get("MFTS_SIGNAL_PRETRADE_GATE", "true"), default=True)
    if not enabled:
        return ranking_pool, pd.DataFrame(), info
    info["enabled"] = True

    total_target = _resolve_profile_total_position(regime_position_range, profile_cfg, 0.60)
    max_single_pos = min(max(_parse_percent_text(regime_single_stock_max, 0.10), 0.0), 1.0)
    if total_target <= 0:
        total_target = 0.60
    if max_single_pos <= 0:
        max_single_pos = 0.10

    profile_pool_n = _resolve_candidate_pool_n(int(top_n), int(len(ranking_pool)), profile_cfg)
    default_pool_mult = max(
        1.0,
        _profile_float(
            profile_cfg or {},
            "pretrade_candidate_pool_multiplier",
            _profile_float(profile_cfg or {}, "optimizer_candidate_pool_multiplier", 1.0),
        ),
    )
    default_pool_max_n = max(
        int(top_n),
        _profile_int(
            profile_cfg,
            "pretrade_candidate_pool_max_n",
            _profile_int(profile_cfg, "optimizer_candidate_pool_max_n", profile_pool_n),
        ),
    )
    default_allow_expand = _profile_bool(profile_cfg, "pretrade_allow_pool_expand", False) or _profile_bool(
        profile_cfg,
        "reserve_pool_enabled",
        False,
    )
    pool_fixed = int(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_N", "0"), 0.0))
    pool_mult = min(max(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_MULT", str(default_pool_mult)), default_pool_mult), 1.0), 8.0)
    pool_min_default = int(top_n) + max(0, _profile_int(profile_cfg, "reserve_candidate_count", 0))
    pool_min_n = max(0, int(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_MIN_N", str(pool_min_default)), pool_min_default)))
    pool_step_n = max(1, int(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_STEP_N", "10"), 10.0)))
    pool_max_n_default = max(int(top_n) * 3, int(top_n), pool_min_n, default_pool_max_n)
    pool_max_n = max(1, int(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_MAX_N", str(pool_max_n_default)), pool_max_n_default)))
    pool_max_n = min(pool_max_n, int(len(ranking_pool)))
    allow_expand = _parse_bool_like(
        os.environ.get("MFTS_SIGNAL_PRETRADE_ALLOW_EXPAND", str(default_allow_expand).lower()),
        default=bool(default_allow_expand),
    )
    stress_block_rate_pct = max(
        0.0,
        min(100.0, _safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_STRESS_BLOCK_RATE_PCT", "30"), 30.0)),
    )
    stress_pool_mult = min(
        max(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_STRESS_POOL_MULT", "1.5"), 1.5), pool_mult),
        8.0,
    )

    bars_idx = _build_bars_idx(bars_window_df)
    trading_days = sorted(bars_idx.index.get_level_values(0).unique()) if not bars_idx.empty else []
    gate_date = pd.Timestamp(signal_date).normalize()
    use_next_day = _parse_bool_like(os.environ.get("MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY", "false"), default=False)
    if use_next_day:
        next_day = _resolve_next_trade_day(trading_days, gate_date)
        if next_day is not None:
            gate_date = pd.Timestamp(next_day).normalize()
    info["trade_date"] = gate_date.strftime("%Y-%m-%d")
    info["research_safe_mode"] = int(not bool(use_next_day))
    info["pretrade_uses_next_trade_day"] = int(bool(use_next_day))

    cfg = _build_signal_pretrade_cfg_from_env(profile_cfg)
    cfg.max_names = int(top_n)
    eff_industry_map = industry_map if industry_map is not None else load_industry_map(data_dir)

    dynamic_pool_mult = float(pool_mult)
    precheck_block_rate = 0.0
    if pool_fixed > 0:
        pool_n_plan = [max(1, min(int(pool_fixed), int(len(ranking_pool))))]
    else:
        # 先用 TopN 快速预检；高阻塞日放大扩池倍率，低阻塞日保持紧池，减少 pool 层虚高拦截。
        pre_n = max(1, min(int(top_n), int(len(ranking_pool))))
        pre_pool = ranking_pool.sort_values(ranking_col, ascending=False).head(pre_n).copy()
        pre_pool["代码"] = normalize_ts_code_series(pre_pool["ts_code"])
        pre_pool["名称"] = pre_pool["name"].astype(str).fillna("")
        pre_score_src = "ml_score" if "ml_score" in pre_pool.columns else ranking_col
        pre_pool["ML评分"] = pd.to_numeric(pre_pool[pre_score_src], errors="coerce").fillna(0.0).round(2)
        pre_pool["排名_num"] = np.arange(1, len(pre_pool) + 1)
        _, _, pre_stats = apply_pretrade_risk_gates(
            signal_df=pre_pool[["代码", "名称", "ML评分", "排名_num"]].copy(),
            bars_idx=bars_idx,
            trade_date=gate_date,
            total_target_pos=total_target,
            max_single_pos=max_single_pos,
            cfg=cfg,
            industry_map=eff_industry_map,
        )
        precheck_block_rate = float(_safe_float(pre_stats.get("blocked_rate_pct", 0.0), 0.0))
        if precheck_block_rate >= float(stress_block_rate_pct):
            dynamic_pool_mult = float(stress_pool_mult)

        start_n = max(int(top_n), int(round(float(top_n) * dynamic_pool_mult)), int(pool_min_n))
        start_n = max(1, min(start_n, int(len(ranking_pool))))
        pool_n_plan = [start_n]
        if allow_expand:
            while pool_n_plan[-1] < pool_max_n:
                nxt = min(pool_max_n, pool_n_plan[-1] + pool_step_n)
                if nxt <= pool_n_plan[-1]:
                    break
                pool_n_plan.append(nxt)

    info["precheck_blocked_rate_pct"] = float(precheck_block_rate)
    info["pool_mult_base"] = float(pool_mult)
    info["pool_mult_used"] = float(dynamic_pool_mult)
    info["pool_expand_enabled"] = bool(allow_expand)
    info["pool_n_plan"] = list(pool_n_plan)
    info["pool_expand_rounds"] = int(max(len(pool_n_plan) - 1, 0))

    gated_pool = pd.DataFrame()
    blocked_df = pd.DataFrame()
    stats: dict[str, object] = {}
    for idx, pool_n in enumerate(pool_n_plan):
        pool = ranking_pool.sort_values(ranking_col, ascending=False).head(int(pool_n)).copy()
        pool["代码"] = normalize_ts_code_series(pool["ts_code"])
        pool["名称"] = pool["name"].astype(str).fillna("")
        score_src = "ml_score" if "ml_score" in pool.columns else ranking_col
        pool["ML评分"] = pd.to_numeric(pool[score_src], errors="coerce").fillna(0.0).round(2)
        pool["排名_num"] = np.arange(1, len(pool) + 1)
        gated_pool, blocked_df, stats = apply_pretrade_risk_gates(
            signal_df=pool[["代码", "名称", "ML评分", "排名_num"]].copy(),
            bars_idx=bars_idx,
            trade_date=gate_date,
            total_target_pos=total_target,
            max_single_pos=max_single_pos,
            cfg=cfg,
            industry_map=eff_industry_map,
        )
        info["pool_n"] = int(len(pool))
        info["pool_expand_rounds_used"] = int(idx)
        if int(len(gated_pool)) >= int(top_n):
            break

    top_reason, top_reason_count = _top_blocked_reason(blocked_df)
    info.update(stats)
    info["top_reason"] = str(top_reason)
    info["top_reason_count"] = int(top_reason_count)

    strict = _parse_bool_like(os.environ.get("MFTS_SIGNAL_PRETRADE_STRICT", "false"), default=False)
    if int(len(gated_pool)) < int(top_n):
        info["stage"] = "pretrade_gate_fallback"
        if strict:
            raise RuntimeError(
                f"{signal_date.date()} 前置风控后候选仅 {len(gated_pool)} 只 < TopN {top_n}（strict=true）"
            )
        return ranking_pool, blocked_df, info

    keep_codes = set(normalize_ts_code_series(gated_pool["代码"]).tolist())
    gated_ranking_pool = ranking_pool[ranking_pool["ts_code"].astype(str).isin(keep_codes)].copy()
    info["stage"] = "pretrade_gate_on"
    info["kept_count"] = int(len(gated_ranking_pool))
    return gated_ranking_pool, blocked_df, info


def _eval_topn_pretrade(
    *,
    top_stocks: pd.DataFrame,
    ranking_col: str,
    bars_window_df: pd.DataFrame,
    trade_date: pd.Timestamp,
    total_target_pos: float,
    max_single_pos: float,
    profile_cfg: dict[str, object] | None,
    industry_map: dict[str, str] | None,
) -> dict[str, object]:
    out: dict[str, object] = {
        "enabled": False,
        "input_count": int(len(top_stocks)),
        "blocked_count": 0,
        "blocked_rate_pct": 0.0,
        "top_reason": "none",
        "top_reason_count": 0,
    }
    if top_stocks is None or top_stocks.empty:
        return out
    enabled = _parse_bool_like(os.environ.get("MFTS_SIGNAL_PRETRADE_GATE", "true"), default=True)
    if not enabled:
        return out
    out["enabled"] = True
    bars_idx = _build_bars_idx(bars_window_df)
    signal_df = pd.DataFrame(
        {
            "代码": normalize_ts_code_series(top_stocks["ts_code"]),
            "名称": top_stocks["name"].astype(str).fillna(""),
            "ML评分": pd.to_numeric(
                top_stocks["ml_score"] if "ml_score" in top_stocks.columns else top_stocks[ranking_col],
                errors="coerce",
            ).fillna(0.0).round(2),
            "排名_num": np.arange(1, len(top_stocks) + 1),
        }
    )
    signal_df = signal_df[signal_df["代码"] != ""].copy()
    cfg = _build_signal_pretrade_cfg_from_env(profile_cfg)
    cfg.max_names = int(len(signal_df))
    _, blocked_df, stats = apply_pretrade_risk_gates(
        signal_df=signal_df,
        bars_idx=bars_idx,
        trade_date=pd.Timestamp(trade_date).normalize(),
        total_target_pos=float(total_target_pos),
        max_single_pos=float(max_single_pos),
        cfg=cfg,
        industry_map=(industry_map or load_industry_map(DATA_DIR)),
    )
    reason, reason_n = _top_blocked_reason(blocked_df)
    out.update(
        {
            "input_count": int(stats.get("input_count", len(signal_df))),
            "blocked_count": int(stats.get("blocked_count", 0)),
            "blocked_rate_pct": float(stats.get("blocked_rate_pct", 0.0)),
            "top_reason": str(reason),
            "top_reason_count": int(reason_n),
        }
    )
    return out


def _assign_target_weights(
    *,
    top_stocks: pd.DataFrame,
    ranking_col: str,
    total_target_pos: float,
    max_single_pos: float,
    profile_cfg: dict[str, object],
    primary_top_n: int | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if top_stocks is None or top_stocks.empty:
        return top_stocks, {"mode": "empty", "selected_count": 0}
    work = top_stocks.copy()
    work, ranking_col, target_score_info = _apply_target_score_blend(
        work,
        ranking_col=ranking_col,
        profile_cfg=profile_cfg,
    )
    optimizer_mode = str(profile_cfg.get("optimizer_mode", "score_weight") or "score_weight").strip().lower()
    capacity_on = optimizer_mode in {"capacity_aware", "capacity_crowding", "capacity_crowding_aware"}
    industry_cap = _profile_float(profile_cfg, "target_max_industry_weight", 0.0)
    adv_cap = _profile_float(profile_cfg, "target_max_adv_participation", 0.0)
    if capacity_on:
        if industry_cap <= 0.0:
            industry_cap = _profile_float(profile_cfg, "risk_max_industry_weight", 0.0)
        if adv_cap <= 0.0:
            adv_cap = _profile_float(profile_cfg, "risk_max_adv_participation", 0.0)
    else:
        industry_cap = 0.0
        adv_cap = 0.0

    amount_col = str(profile_cfg.get("target_capacity_amount_col", "amount_ma20") or "amount_ma20")
    if amount_col == "amount_capacity_conservative" and amount_col not in work.columns:
        if "amount_last" not in work.columns:
            if "amount" in work.columns:
                work["amount_last"] = pd.to_numeric(work["amount"], errors="coerce").fillna(0.0)
            else:
                work["amount_last"] = 0.0
        for col in ("amount_ma20", "amount_last", "amount_min5", "amount_min10"):
            if col not in work.columns:
                work[col] = 0.0
        work["amount_capacity_conservative"] = [
            _positive_min([ma20, last, min5, min10])
            for ma20, last, min5, min10 in work[
                ["amount_ma20", "amount_last", "amount_min5", "amount_min10"]
            ].itertuples(index=False, name=None)
        ]
    if amount_col not in work.columns:
        amount_col = "amount_ma20"
    amount_buffer = max(0.0, _profile_float(profile_cfg, "target_capacity_amount_buffer", 1.0))

    decision = build_portfolio_decision(
        work,
        PortfolioConstraints(
            total_target=min(max(float(total_target_pos), 0.0), 1.0),
            single_cap=min(max(float(max_single_pos), 0.0), 1.0),
            industry_cap=min(max(float(industry_cap), 0.0), 1.0),
            adv_participation_cap=min(max(float(adv_cap), 0.0), 1.0),
            capital_base=max(100000.0, _profile_float(profile_cfg, "target_capital_base", 1_000_000.0)),
            max_names=max(0, int(primary_top_n or 0)),
            min_names=max(0, _profile_int(profile_cfg, "min_valid_positions", 0)),
            score_col=ranking_col,
            code_col="ts_code",
            industry_col="industry",
            amount_col=amount_col,
            amount_buffer=amount_buffer,
            redistribute_clipped=str(profile_cfg.get("redistribute_clipped_weight", False)).strip().lower()
            in {"1", "true", "yes", "y", "on"},
            reserve_cap=min(max(_profile_float(profile_cfg, "target_max_reserve_weight", 0.0), 0.0), 1.0),
            reserve_col="reserve_candidate",
            exit_trap_risk_col="exit_trap_risk_score",
            exit_trap_risk_threshold=min(max(_profile_float(profile_cfg, "target_exit_trap_risk_threshold", 0.0), 0.0), 1.0),
            exit_trap_weight_cap=min(max(_profile_float(profile_cfg, "target_max_exit_trap_weight", 0.0), 0.0), 1.0),
            exit_trap_single_cap=min(max(_profile_float(profile_cfg, "target_max_exit_trap_single_weight", 0.0), 0.0), 1.0),
            impact_model=str(profile_cfg.get("impact_model", "sqrt") or "sqrt"),
            impact_base_bps=max(0.0, _profile_float(profile_cfg, "impact_base_bps", 0.0)),
            impact_participation_bps=max(0.0, _profile_float(profile_cfg, "impact_participation_bps", 0.0)),
            impact_power=max(0.1, _profile_float(profile_cfg, "impact_power", 0.5)),
        ),
    )
    selected = decision.selected.copy()
    if selected.empty:
        if capacity_on:
            empty = work.iloc[0:0].copy()
            for col, default in {
                "target_weight": 0.0,
                "target_weight_raw": 0.0,
                "participation_pct": 0.0,
                "impact_cost_bps": 0.0,
                "unfilled_target_weight": 0.0,
                "industry_weight_post": 0.0,
                "constraint_reason": "optimizer_empty",
                "reserve_candidate": 0,
                "exit_trap_flag": 0,
            }.items():
                if col not in empty.columns:
                    empty[col] = default
            return empty, {
                "mode": optimizer_mode,
                "target_score_col": str(ranking_col),
                "target_score_blend": target_score_info,
                "selected_count": 0,
                "primary_top_n": int(primary_top_n or len(work)),
                "candidate_pool_n": int(len(work)),
                "fallback": False,
                "optimizer_empty": True,
                "exposures": decision.exposures,
                "diagnostics": decision.diagnostics,
            }
        fallback = work.copy()
        weights = np.asarray(
            build_score_weights(
                pd.to_numeric(fallback[ranking_col], errors="coerce").fillna(0.0).to_numpy(dtype=float),
                min(max(float(total_target_pos), 0.0), 1.0),
                min(max(float(max_single_pos), 0.0), 1.0),
            ),
            dtype=float,
        )
        fallback["target_weight"] = weights if len(weights) == len(fallback) else 0.0
        fallback["target_weight_raw"] = fallback["target_weight"]
        fallback["participation_pct"] = 0.0
        fallback["impact_cost_bps"] = 0.0
        fallback["unfilled_target_weight"] = 0.0
        fallback["industry_weight_post"] = 0.0
        fallback["constraint_reason"] = "optimizer_fallback"
        fallback["reserve_candidate"] = 0
        return fallback, {
            "mode": optimizer_mode,
            "target_score_col": str(ranking_col),
            "target_score_blend": target_score_info,
            "selected_count": int(len(fallback)),
            "primary_top_n": int(primary_top_n or len(work)),
            "candidate_pool_n": int(len(work)),
            "fallback": True,
        }
    if _profile_bool(profile_cfg, "reserve_pool_enabled", False):
        reserve_rows = pd.DataFrame(decision.diagnostics.get("blocked", []))
        if not reserve_rows.empty and "constraint_reason" in reserve_rows.columns:
            reserve_rows = reserve_rows[reserve_rows["constraint_reason"].astype(str).eq("zero_weight")].copy()
            reserve_limit = max(0, _profile_int(profile_cfg, "reserve_candidate_count", 0))
            if reserve_limit > 0:
                reserve_rows = reserve_rows.head(reserve_limit).copy()
        if not reserve_rows.empty:
            selected["reserve_candidate"] = 0
            reserve_rows["reserve_candidate"] = 1
            selected = pd.concat([selected, reserve_rows.reindex(columns=selected.columns)], ignore_index=True)
    if "reserve_candidate" not in selected.columns:
        selected["reserve_candidate"] = 0
    return selected, {
        "mode": optimizer_mode,
        "target_score_col": str(ranking_col),
        "target_score_blend": target_score_info,
        "selected_count": int(len(selected)),
        "primary_top_n": int(primary_top_n or len(work)),
        "candidate_pool_n": int(len(work)),
        "fallback": False,
        "exposures": decision.exposures,
        "diagnostics": decision.diagnostics,
    }


def select_stocks(target_date=None, top_n=None, profile_cfg: dict[str, object] | None = None):
    """
    ML选股主函数
    """
    profile_cfg = dict(profile_cfg or load_default_profile_config())
    if top_n is None:
        top_n = int(profile_cfg.get("top_n", 30))
    research_stage_frames: list[pd.DataFrame] = []
    write_research_stages = _research_stage_snapshots_enabled(profile_cfg)

    print("=" * 70)
    print("MFTS ML每日选股 (内存优化版)")
    print("=" * 70)
    
    # 1. 加载数据
    print("\n[1/5] 加载市场数据...")
    trade_dates_df = load_latest_data(columns=["trade_date"])
    print(f"原始数据行数: {len(trade_dates_df)}")

    latest_date = trade_dates_df['trade_date'].max()
    earliest_date = trade_dates_df['trade_date'].min()

    # 确定目标日期
    if target_date:
        target_date = pd.to_datetime(target_date)
    else:
        target_date = latest_date

    if target_date < earliest_date or target_date > latest_date:
        raise RuntimeError(
            f"目标日期 {target_date.date()} 超出数据范围 "
            f"({earliest_date.date()} ~ {latest_date.date()})"
        )

    # 内存优化: 围绕目标日期切片，而不是固定按最新日期切片。
    # 这样在 catchup/rebuild 回算历史日期时，不会因为固定窗口导致目标日被裁掉。
    # 可通过环境变量调节窗口宽度：
    #   MFTS_ML_LOOKBACK_DAYS（默认450）
    #   MFTS_ML_FORWARD_BUFFER_DAYS（默认2）
    lookback_days = int(os.environ.get("MFTS_ML_LOOKBACK_DAYS", "450"))
    forward_buffer_days = int(os.environ.get("MFTS_ML_FORWARD_BUFFER_DAYS", "2"))
    pretrade_gate_on = _parse_bool_like(os.environ.get("MFTS_SIGNAL_PRETRADE_GATE", "true"), default=True)
    pretrade_uses_next_day = _parse_bool_like(
        os.environ.get("MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY", "false"),
        default=False,
    )
    if pretrade_gate_on and pretrade_uses_next_day:
        pretrade_forward_floor = max(
            0,
            int(os.environ.get("MFTS_SIGNAL_PRETRADE_FORWARD_BUFFER_DAYS", "10")),
        )
        if forward_buffer_days < pretrade_forward_floor:
            print(
                "ℹ️ 前置风控已开启，自动扩展前瞻窗口: "
                f"MFTS_ML_FORWARD_BUFFER_DAYS {forward_buffer_days} -> {pretrade_forward_floor}"
            )
        forward_buffer_days = max(forward_buffer_days, pretrade_forward_floor)
    start_date = target_date - pd.Timedelta(days=lookback_days)
    end_date = min(latest_date, target_date + pd.Timedelta(days=forward_buffer_days))
    print(
        f">>> 内存优化: 按目标日期切片 {lookback_days} 天回看 "
        f"(窗口: {start_date.date()} ~ {end_date.date()})..."
    )
    data_columns = ["open", "high", "low", "close", "vol", "amount", "pct_chg"]
    use_indicator_cache = _parse_bool_like(
        os.environ.get("MFTS_DAILY_SELECT_PRECOMPUTE_INDICATORS", "false"),
        default=False,
    )
    if use_indicator_cache:
        df = _load_cached_indicator_window(columns=data_columns, start_date=start_date, end_date=end_date)
    else:
        df = load_latest_data(
            columns=data_columns,
            start_date=start_date,
            end_date=end_date,
        )
    print(f"截取后行数: {len(df)}")
    bars_window_df = df[
        [c for c in ("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount") if c in df.columns]
    ].copy()

    print(f"目标日期: {target_date.date()}")
    
    # 2. 计算指标
    print("\n[2/5] 计算技术指标...")
    if not use_indicator_cache:
        df = df.sort_values(['ts_code', 'trade_date'])
        df = calc_indicators(df)
        df = _add_selection_window_columns(df)

    # 再次清理NaN (指标计算产生的前段NaN)
    df = df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
    
    # 4. 筛选目标日期数据
    today_df = df[df['trade_date'] == target_date].copy()
    # 实盘约束：不参与北交所 9 开头标的
    today_df = today_df[~today_df['ts_code'].astype(str).str.startswith('9')].copy()
    
    if len(today_df) == 0:
        raise RuntimeError(f"{target_date.date()} 无数据（指标清洗后为空）")
    
    print(f"当日候选股票: {len(today_df)}")
    min_stocks = int(os.environ.get("MFTS_STAGE_MIN_STOCKS", "3000"))
    if min_stocks > 0 and len(today_df) < min_stocks:
        raise RuntimeError(
            f"{target_date.date()} 覆盖仅 {len(today_df)} 只 < 阈值 {min_stocks}，拒绝生成推荐。"
            "请先补齐数据或降低 MFTS_STAGE_MIN_STOCKS。"
        )

    # 3. 市场状态与仓位建议
    regime = detect_market_regime(today_df)
    regime_top_n = {
        '正常': top_n,
        '震荡': min(top_n, 20),
        '恐慌': min(top_n, 10),
    }.get(regime['state'], top_n)
    
    # 4. 加载模型并预测（放在覆盖校验后，避免无效模型加载）
    print("\n[3/5] 加载模型...")
    model, feature_cols, model_info = load_latest_model()
    print(f"特征数量: {len(feature_cols)}")
    if model_info.get('label_mode'):
        print(
            f"模型标签: {model_info.get('label_mode')} | "
            f"H={model_info.get('label_horizon')} | {model_info.get('execution_hint', '')}"
        )
    print("\n[4/5] ML模型预测...")
    
    # 检查特征是否存在
    missing_features = [f for f in feature_cols if f not in today_df.columns]
    if missing_features:
        print(f"警告: 缺失特征 {missing_features}，将填充为0")
        for f in missing_features:
            today_df[f] = 0
    
    X = today_df[feature_cols].values
    predictions = model.predict(X)
    today_df['ml_score'] = predictions
    default_ml_weight = float(profile_cfg.get("ml_quality_blend", 0.80))
    ml_weight = float(os.environ.get("MFTS_ML_QUALITY_BLEND", str(default_ml_weight)))
    max_abs_pct_chg = float(os.environ.get("MFTS_SIGNAL_MAX_ABS_PCT_CHG", "8.5"))
    today_df = add_signal_quality_columns(
        today_df,
        bias_col="bias",
        z_col="z_score",
        rsi_col="rsi",
        vol_ratio_col="vol_ratio",
        pct_chg_col="pct_chg",
        max_abs_pct_chg=max_abs_pct_chg,
        quality_col="signal_quality",
        score_col="hybrid_score",
        ml_col="ml_score",
        ml_weight=ml_weight,
    )
    feature_refactor_on = os.environ.get("MFTS_FEATURE_REFACTOR_ON", "true").strip().lower() not in {"0", "false", "off", "no"}
    stability_blend = float(os.environ.get("MFTS_STABILITY_BLEND", "0.30"))
    if feature_refactor_on:
        today_df = add_feature_refactor_columns(
            today_df,
            bias_col="bias",
            z_col="z_score",
            rsi_col="rsi",
            vol_ratio_col="vol_ratio",
            pct_chg_col="pct_chg",
            base_score_col="hybrid_score",
            stability_col="stability_score",
            refactor_col="refactor_score",
            redundancy_col="feature_redundancy",
            blend=stability_blend,
            max_abs_pct_chg=max_abs_pct_chg,
        )
        ranking_col = "refactor_score"
    else:
        today_df["stability_score"] = today_df.get("signal_quality", 0.0)
        today_df["refactor_score"] = today_df.get("hybrid_score", 0.0)
        today_df["feature_redundancy"] = 0.0
        ranking_col = "hybrid_score"

    industry_map = load_industry_map(asof_date=target_date)
    today_df["ts_code"] = normalize_ts_code_series(today_df["ts_code"])
    today_df["industry"] = today_df["ts_code"].map(industry_map).fillna("").astype(str).str.strip()
    today_df["industry"] = today_df["industry"].replace({"nan": "", "None": ""})
    liquidity_blend = min(max(_profile_float(profile_cfg, "liquidity_blend", 0.0), 0.0), 0.5)
    adv_penalty_blend = min(max(_profile_float(profile_cfg, "adv_penalty_blend", 0.0), 0.0), 0.5)
    industry_crowding_blend = min(max(_profile_float(profile_cfg, "industry_crowding_blend", 0.0), 0.0), 0.5)
    today_df = add_execution_overlay_scores(
        today_df,
        base_score_col=ranking_col,
        price_col="close",
        amount_col="amount_ma20",
        industry_col="industry",
        liquidity_blend=liquidity_blend,
        adv_penalty_blend=adv_penalty_blend,
        industry_crowding_blend=industry_crowding_blend,
    )
    if liquidity_blend > 0 or adv_penalty_blend > 0 or industry_crowding_blend > 0:
        ranking_col = "execution_score"
    # 5.1 可交易性过滤（实盘增强）
    meta_dict = load_metadata(target_date)
    name_map = {normalize_ts_code(k): v.get('name', '') for k, v in meta_dict.items()}
    today_df['name'] = today_df['ts_code'].astype(str).map(name_map).fillna('')
    is_st = today_df['name'].astype(str).str.contains('ST', case=False, na=False)
    is_kc_cy = today_df['ts_code'].astype(str).str.startswith('688') | today_df['ts_code'].astype(str).str.startswith('30')
    is_bj = (
        today_df['ts_code'].astype(str).str.startswith('8')
        | today_df['ts_code'].astype(str).str.startswith('4')
        | today_df['ts_code'].astype(str).str.startswith('9')
    )
    limit_ratio = np.select([is_st, is_bj, is_kc_cy], [0.05, 0.30, 0.20], default=0.10)
    limit_up_price = today_df['close_1'] * (1 + limit_ratio)

    # 强过滤：涨停触及、过热、量能异常
    hard_limit = (today_df['high'] >= limit_up_price * 0.995) | (today_df['pct_chg'] >= (limit_ratio * 100 * 0.95))
    overheat = (today_df['rsi'] > 85) | (today_df['bias'] > 30)
    vol_ratio_for_filter = (
        pd.to_numeric(today_df.get("vol_ratio", pd.Series(1.0, index=today_df.index)), errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(1.0)
    )
    vol_anomaly_low = vol_ratio_for_filter < _profile_float(profile_cfg, "hard_filter_vol_ratio_low", 0.15)
    vol_anomaly_high = vol_ratio_for_filter > _profile_float(profile_cfg, "hard_filter_vol_ratio_high", 5.0)
    vol_anomaly = vol_anomaly_low | vol_anomaly_high
    today_df["hard_limit_flag"] = hard_limit.astype(int)
    today_df["overheat_flag"] = overheat.astype(int)
    today_df["vol_anomaly_flag"] = vol_anomaly.astype(int)
    today_df["vol_anomaly_low_flag"] = vol_anomaly_low.astype(int)
    today_df["vol_anomaly_high_flag"] = vol_anomaly_high.astype(int)
    if write_research_stages:
        _append_research_stage_snapshot(
            research_stage_frames,
            today_df,
            stage="raw_scored_post_indicator",
            target_date=pd.Timestamp(target_date),
            ranking_col=ranking_col,
            extra={"stage_note": "post_indicator_scored_before_tradability_filters", "stage_pool_n": int(len(today_df))},
        )

    tradable_mask = (~hard_limit) & (~overheat) & (~vol_anomaly)
    filtered_df = today_df[tradable_mask].copy()
    liquidity_stage = "liquidity_gate_off"

    # 兜底：过滤过严时逐步放宽（保留硬涨停过滤）
    fallback_stage = "strict"
    if len(filtered_df) < regime_top_n:
        relaxed_mask = (~hard_limit) & (~overheat)
        filtered_df = today_df[relaxed_mask].copy()
        fallback_stage = "relax_no_vol_anomaly"
    if len(filtered_df) < regime_top_n:
        filtered_df = today_df[~hard_limit].copy()
        fallback_stage = "relax_hard_limit_only"
    if len(filtered_df) < regime_top_n:
        raise RuntimeError(
            f"{target_date.date()} 可交易候选仅 {len(filtered_df)} 只，低于目标 {regime_top_n}，拒绝出榜。"
            "请检查当日覆盖、涨跌停触发和量能过滤条件。"
        )
    if write_research_stages:
        _append_research_stage_snapshot(
            research_stage_frames,
            filtered_df,
            stage="tradability_filter_pool",
            target_date=pd.Timestamp(target_date),
            ranking_col=ranking_col,
            extra={"stage_note": fallback_stage, "stage_pool_n": int(len(filtered_df))},
        )

    profile_min_price = max(0.0, _profile_float(profile_cfg, "min_price", 0.0))
    profile_min_amount_ma20 = max(0.0, _profile_float(profile_cfg, "min_amount_ma20", 0.0))
    if profile_min_price > 0.0 or profile_min_amount_ma20 > 0.0:
        liq_mask = pd.Series(True, index=filtered_df.index)
        if profile_min_price > 0.0:
            liq_mask &= pd.to_numeric(filtered_df.get("close", np.nan), errors="coerce").fillna(0.0) >= profile_min_price
        if profile_min_amount_ma20 > 0.0:
            liq_mask &= pd.to_numeric(filtered_df.get("amount_ma20", np.nan), errors="coerce").fillna(0.0) >= profile_min_amount_ma20
        liquidity_pool = filtered_df[liq_mask].copy()
        if len(liquidity_pool) >= regime_top_n:
            filtered_df = liquidity_pool
            liquidity_stage = "liquidity_gate_on"
        else:
            liquidity_stage = "liquidity_gate_fallback"
    if write_research_stages:
        _append_research_stage_snapshot(
            research_stage_frames,
            filtered_df,
            stage="liquidity_filter_pool",
            target_date=pd.Timestamp(target_date),
            ranking_col=ranking_col,
            extra={"stage_note": liquidity_stage, "stage_pool_n": int(len(filtered_df))},
        )

    quality_floor_env = os.environ.get("MFTS_SIGNAL_QUALITY_FLOOR", "")
    profile_quality_floor = float(profile_cfg.get("min_signal_quality", 0.40))
    if quality_floor_env.strip():
        quality_floor = float(quality_floor_env)
    else:
        regime_floor = {"正常": 0.40, "震荡": 0.45, "恐慌": 0.50}.get(regime["state"], 0.40)
        quality_floor = max(profile_quality_floor, regime_floor)
    quality_floor = min(max(quality_floor, 0.0), 1.0)
    quality_pool = filtered_df[filtered_df["signal_quality"] >= quality_floor].copy()
    quality_stage = "quality_gate_on"
    if len(quality_pool) >= regime_top_n:
        filtered_df = quality_pool
    else:
        quality_stage = "quality_gate_fallback"

    refactor_floor_env = os.environ.get("MFTS_REFACTOR_SCORE_FLOOR", "")
    profile_refactor_floor = float(profile_cfg.get("min_refactor_score", 0.0))
    if feature_refactor_on and ranking_col == "refactor_score":
        if refactor_floor_env.strip():
            refactor_floor = float(refactor_floor_env)
        else:
            refactor_floor = profile_refactor_floor
        refactor_floor = min(max(refactor_floor, 0.0), 1.0)
        refactor_pool = filtered_df[filtered_df["refactor_score"] >= refactor_floor].copy()
        if len(refactor_pool) >= regime_top_n:
            filtered_df = refactor_pool
            quality_stage = f"{quality_stage}+refactor_gate_on"
        else:
            quality_stage = f"{quality_stage}+refactor_gate_fallback"
    if write_research_stages:
        _append_research_stage_snapshot(
            research_stage_frames,
            filtered_df,
            stage="quality_filter_pool",
            target_date=pd.Timestamp(target_date),
            ranking_col=ranking_col,
            extra={"stage_note": quality_stage, "stage_pool_n": int(len(filtered_df))},
        )
    if write_research_stages:
        _append_research_stage_snapshot(
            research_stage_frames,
            filtered_df,
            stage="filtered_signal_pool",
            target_date=pd.Timestamp(target_date),
            ranking_col=ranking_col,
            extra={"stage_note": f"{fallback_stage}+{liquidity_stage}+{quality_stage}", "stage_pool_n": int(len(filtered_df))},
        )

    # 市场状态下的分位数门槛（先收缩，再兜底回原过滤池）
    q, q_source = _resolve_score_quantile(profile_cfg, regime.get("state", ""))
    score_floor = float(filtered_df[ranking_col].quantile(q))
    gated_df = filtered_df[filtered_df[ranking_col] >= score_floor].copy()
    ranking_pool = gated_df if len(gated_df) >= regime_top_n else filtered_df
    if write_research_stages:
        _append_research_stage_snapshot(
            research_stage_frames,
            ranking_pool,
            stage="ranking_pool_pre_pretrade",
            target_date=pd.Timestamp(target_date),
            ranking_col=ranking_col,
            extra={
                "stage_note": f"score_quantile_q={q:.2f};source={q_source}",
                "stage_pool_n": int(len(ranking_pool)),
            },
        )

    # 5.2 前置风控联动（与 P2 同口径参数）
    ranking_pool, signal_risk_block_df, signal_risk_info = _apply_signal_pretrade_gate(
        ranking_pool=ranking_pool,
        ranking_col=ranking_col,
        bars_window_df=bars_window_df,
        signal_date=pd.Timestamp(target_date).normalize(),
        top_n=int(regime_top_n),
        regime_position_range=regime.get("position_range", "60%-80%"),
        regime_single_stock_max=regime.get("single_stock_max", "10%"),
        profile_cfg=profile_cfg,
        industry_map=industry_map,
        data_dir=DATA_DIR,
    )
    ranking_pool, ranking_col, tradability_rank_info = _apply_tradability_safe_ranking(
        ranking_pool,
        ranking_col=ranking_col,
        profile_cfg=profile_cfg,
    )
    if write_research_stages:
        _append_research_stage_snapshot(
            research_stage_frames,
            ranking_pool,
            stage="ranking_pool_post_pretrade",
            target_date=pd.Timestamp(target_date),
            ranking_col=ranking_col,
            extra={
                "stage_note": str(signal_risk_info.get("stage", "pretrade_unknown")),
                "stage_pool_n": int(len(ranking_pool)),
            },
        )

    # 6. 排序并选择Top N；v8 reserve pool 会把扩展候选交给组合层，由组合层在 clip 后递补。
    optimizer_pool_n = _resolve_candidate_pool_n(int(regime_top_n), int(len(ranking_pool)), profile_cfg)
    print(f"\n[5/5] 选择Top {regime_top_n}目标股票 (optimizer_pool={optimizer_pool_n})...")
    top_stocks = ranking_pool.nlargest(optimizer_pool_n, ranking_col).copy()
    top_stocks, weight_ranking_col, reserve_rank_info = _prepare_capacity_safe_reserve_pool(
        top_stocks,
        ranking_col=ranking_col,
        primary_top_n=int(regime_top_n),
        profile_cfg=profile_cfg,
    )
    if write_research_stages:
        _append_research_stage_snapshot(
            research_stage_frames,
            top_stocks,
            stage="optimizer_ranked_pool",
            target_date=pd.Timestamp(target_date),
            ranking_col=weight_ranking_col,
            extra={
                "stage_note": str(reserve_rank_info.get("primary_rank_mode", "reserve_only")),
                "stage_pool_n": int(len(top_stocks)),
            },
        )
    target_total_for_weights = _resolve_profile_total_position(regime.get("position_range", "60%-80%"), profile_cfg, 0.60)
    target_single_for_weights = min(max(_parse_percent_text(regime.get("single_stock_max", "10%"), 0.10), 0.0), 1.0)
    holiday_gap_info = _build_holiday_gap_guard_info(
        trade_dates_df["trade_date"],
        pd.Timestamp(target_date).normalize(),
        profile_cfg,
        total_target=target_total_for_weights,
        single_cap=target_single_for_weights,
    )
    target_total_for_weights = float(holiday_gap_info.get("adjusted_total_target", target_total_for_weights))
    target_single_for_weights = float(holiday_gap_info.get("adjusted_single_cap", target_single_for_weights))
    top_stocks, optimizer_info = _assign_target_weights(
        top_stocks=top_stocks,
        ranking_col=weight_ranking_col,
        total_target_pos=target_total_for_weights,
        max_single_pos=target_single_for_weights,
        profile_cfg=profile_cfg,
        primary_top_n=int(regime_top_n),
    )
    if write_research_stages:
        _append_research_stage_snapshot(
            research_stage_frames,
            top_stocks,
            stage="final_target_weight",
            target_date=pd.Timestamp(target_date),
            ranking_col="target_weight" if "target_weight" in top_stocks.columns else weight_ranking_col,
            extra={"stage_note": str(optimizer_info.get("mode", "")), "stage_pool_n": int(len(top_stocks))},
        )
    eval_trade_date = pd.to_datetime(signal_risk_info.get("trade_date", target_date), errors="coerce")
    if pd.isna(eval_trade_date):
        eval_trade_date = pd.Timestamp(target_date).normalize()
    topn_pretrade_eval = _eval_topn_pretrade(
        top_stocks=top_stocks,
        ranking_col=ranking_col,
        bars_window_df=bars_window_df,
        trade_date=pd.Timestamp(eval_trade_date).normalize(),
        total_target_pos=target_total_for_weights,
        max_single_pos=target_single_for_weights,
        profile_cfg=profile_cfg,
        industry_map=industry_map,
    )
    
    # meta_dict结构: {'code': {'name': '...', 'industry': '...'}}
    # 我们只想要名称
    top_stocks['ts_code'] = normalize_ts_code_series(top_stocks['ts_code'])
    top_stocks['name'] = top_stocks['ts_code'].apply(
        lambda x: meta_dict.get(normalize_ts_code(x), {}).get('name', x)
    )
    
    # 整理输出
    result_cols = [
        'ts_code', 'name', 'close', 'pct_chg', 'ml_score', 'signal_quality', 'hybrid_score', 'stability_score', 'refactor_score',
        'liquidity_score', 'adv_capacity_score', 'industry_balance_score', 'amount_ma20', 'bias', 'z_score', 'rsi', 'vol_ratio',
        'portfolio_rank_score', 'target_blend_score', 'reserve_safe_score', 'reserve_capacity_score', 'tradability_safe_score',
        'tradability_entry_risk_score', 'tradability_limit_headroom_pct',
        'exit_trap_safe_score', 'exit_trap_risk_score', 'exit_trap_downside_headroom_pct',
        'exit_trap_volume_drought_risk', 'exit_trap_drawdown_10d_pct', 'exit_trap_down_momentum_5d',
        'exit_trap_volatility_10d',
        'target_weight', 'target_weight_raw', 'participation_pct', 'impact_cost_bps', 'unfilled_target_weight',
        'industry_weight_post', 'constraint_reason', 'reserve_candidate', 'exit_trap_flag'
    ]
    text_defaults = {"ts_code": "", "name": "", "constraint_reason": ""}
    for col in result_cols:
        if col not in top_stocks.columns:
            top_stocks[col] = text_defaults.get(col, 0.0)
    result = top_stocks[result_cols].copy()
    result["holiday_gap_guard"] = int(bool(holiday_gap_info.get("guard", False)))
    result["holiday_gap_reason"] = str(holiday_gap_info.get("reason", "none"))
    result["holiday_gap_signal_trade_gap_days"] = int(holiday_gap_info.get("signal_trade_gap_days", 0))
    result["holiday_gap_post_trade_gap_days"] = int(holiday_gap_info.get("post_trade_gap_days", 0))
    result["holiday_gap_target_scale"] = float(holiday_gap_info.get("target_scale", 1.0))
    result["holiday_gap_total_position_cap"] = float(holiday_gap_info.get("adjusted_total_target", target_total_for_weights))
    result["holiday_gap_single_pos_cap"] = float(holiday_gap_info.get("adjusted_single_cap", target_single_for_weights))
    result["holiday_gap_reason_override_applied"] = int(bool(holiday_gap_info.get("reason_override_applied", False)))
    
    result.columns = ['代码', '名称', '收盘价', '涨跌幅%', 'ML评分', '质量分', '综合分', '稳定分', '重构分',
                      '流动性分', 'ADV容量分', '行业均衡分', '成交额MA20', 'BIAS-20', 'Z-Score', 'RSI', '量比',
                      'portfolio_rank_score', 'target_blend_score', 'reserve_safe_score', 'reserve_capacity_score', 'tradability_safe_score',
                      'tradability_entry_risk_score', 'tradability_limit_headroom_pct',
                      'exit_trap_safe_score', 'exit_trap_risk_score', 'exit_trap_downside_headroom_pct',
                      'exit_trap_volume_drought_risk', 'exit_trap_drawdown_10d_pct', 'exit_trap_down_momentum_5d',
                      'exit_trap_volatility_10d',
                      'target_weight', 'target_weight_raw', 'participation_pct', 'impact_cost_bps', 'unfilled_target_weight',
                      'industry_weight_post', 'constraint_reason', 'reserve_candidate', 'exit_trap_flag',
                      'holiday_gap_guard', 'holiday_gap_reason', 'holiday_gap_signal_trade_gap_days',
                      'holiday_gap_post_trade_gap_days', 'holiday_gap_target_scale',
                      'holiday_gap_total_position_cap', 'holiday_gap_single_pos_cap',
                      'holiday_gap_reason_override_applied']
    result['代码'] = result['代码'].astype(str).str.zfill(6)
    
    result['日期'] = target_date.strftime('%Y-%m-%d')
    result['排名'] = range(1, len(result) + 1)
    result['市场状态'] = regime['state']
    result['建议仓位'] = (
        regime['position_range']
        if _profile_bool(profile_cfg, "use_regime_position", True)
        else f"{target_total_for_weights:.0%}"
    )
    result['单票上限'] = regime['single_stock_max']
    profile_h = int(resolve_default_label_horizon(fallback=8))
    model_h = None
    if model_info.get('label_mode', '').startswith('open_to_open') and model_info.get('label_horizon'):
        model_h = int(model_info['label_horizon'])
    use_model_h = os.environ.get("MFTS_SUGGEST_HOLD_FROM_MODEL", "false").lower() == "true"
    suggest_h = model_h if (use_model_h and model_h) else profile_h
    if model_h and model_h != profile_h and not use_model_h:
        print(f"⚠️ 模型标签持有期={model_h} 与 default_profile={profile_h} 不一致，已按平台口径输出 {profile_h}")
    result['建议持有天数'] = int(max(1, suggest_h))
    result["target_weight_source"] = "portfolio_optimizer"
    result["target_weight_checksum"] = ""
    
    # 重新排列列
    result = result[['日期', '市场状态', '建议仓位', '单票上限', '建议持有天数', '排名', '代码', '名称', '收盘价', 'ML评分', '质量分', '综合分', '稳定分', '重构分',
                     '流动性分', 'ADV容量分', '行业均衡分', '成交额MA20', 'target_weight', 'target_weight_raw',
                     'participation_pct', 'impact_cost_bps', 'unfilled_target_weight', 'industry_weight_post',
                     'constraint_reason', 'reserve_candidate', 'portfolio_rank_score', 'reserve_safe_score',
                     'reserve_capacity_score', 'tradability_safe_score', 'tradability_entry_risk_score',
                     'tradability_limit_headroom_pct', 'exit_trap_safe_score', 'exit_trap_risk_score',
                     'exit_trap_downside_headroom_pct', 'exit_trap_volume_drought_risk',
                     'exit_trap_drawdown_10d_pct', 'exit_trap_down_momentum_5d', 'exit_trap_volatility_10d',
                     'holiday_gap_guard', 'holiday_gap_reason', 'holiday_gap_signal_trade_gap_days',
                     'holiday_gap_post_trade_gap_days', 'holiday_gap_target_scale',
                     'holiday_gap_total_position_cap', 'holiday_gap_single_pos_cap',
                     'holiday_gap_reason_override_applied',
                     'exit_trap_flag', 'target_weight_source', 'target_weight_checksum',
                     'BIAS-20', 'Z-Score', 'RSI', '量比', '涨跌幅%']]
    
    # Display metrics can be rounded for readability, but execution weights need
    # enough precision for P2 checksum and replay consistency.
    float_cols = ['收盘价', 'ML评分', '质量分', '综合分', '稳定分', '重构分', '流动性分', 'ADV容量分', '行业均衡分', '成交额MA20',
                  'target_weight', 'target_weight_raw', 'participation_pct', 'impact_cost_bps', 'unfilled_target_weight',
                  'industry_weight_post', 'portfolio_rank_score', 'reserve_safe_score', 'reserve_capacity_score',
                  'tradability_safe_score', 'tradability_entry_risk_score', 'tradability_limit_headroom_pct',
                  'exit_trap_safe_score', 'exit_trap_risk_score', 'exit_trap_downside_headroom_pct',
                  'exit_trap_volume_drought_risk', 'exit_trap_drawdown_10d_pct', 'exit_trap_down_momentum_5d',
                  'exit_trap_volatility_10d', 'holiday_gap_guard', 'holiday_gap_signal_trade_gap_days',
                  'holiday_gap_post_trade_gap_days', 'holiday_gap_target_scale', 'holiday_gap_total_position_cap',
                  'holiday_gap_single_pos_cap', 'holiday_gap_reason_override_applied', 'exit_trap_flag',
                  'BIAS-20', 'Z-Score', 'RSI', '量比', '涨跌幅%']
    weight_cols = {"target_weight", "target_weight_raw", "participation_pct", "unfilled_target_weight", "industry_weight_post"}
    score_cols = {
        "质量分",
        "综合分",
        "稳定分",
        "重构分",
        "流动性分",
        "ADV容量分",
        "行业均衡分",
        "portfolio_rank_score",
        "reserve_safe_score",
        "reserve_capacity_score",
        "tradability_safe_score",
        "tradability_entry_risk_score",
        "exit_trap_safe_score",
        "exit_trap_risk_score",
        "exit_trap_volume_drought_risk",
    }
    for col in float_cols:
        decimals = 6 if col in weight_cols else (4 if col in score_cols else 2)
        result[col] = result[col].round(decimals)
    target_weight_checksum = build_target_weight_checksum(zip(result["代码"], result["target_weight"]))
    result["target_weight_checksum"] = target_weight_checksum

    # 7. 保存结果（daily 子目录 + 兼容旧路径双写）
    base_dir = Path(OUTPUT_DIR)
    dirs = ensure_output_dirs(base_dir)
    output_profile = _sanitize_profile_slug(os.environ.get("MFTS_DAILY_OUTPUT_PROFILE", ""))
    date_str = target_date.strftime('%Y%m%d')
    if output_profile:
        daily_dir = base_dir / "daily_profiles" / output_profile
        risk_dir = base_dir / "risk_profiles" / output_profile
        legacy_file = daily_dir / f"daily_{date_str}.csv"
    else:
        daily_dir = dirs['daily']
        risk_dir = base_dir / "risk"
        legacy_file = base_dir / f"daily_{date_str}.csv"
    output_file = daily_dir / f"daily_{date_str}.csv"
    research_stage_file, research_stage_latest_file = _write_research_stage_snapshots(
        research_stage_frames,
        base_dir=base_dir,
        output_profile=str(output_profile),
        date_str=date_str,
    )
    write_dual_csv(result, output_file, legacy_file, index=False, encoding='utf-8-sig')
    risk_dir.mkdir(parents=True, exist_ok=True)
    risk_file = risk_dir / f"signal_pretrade_gates_{date_str}.csv"
    risk_latest_file = risk_dir / "signal_pretrade_gates_latest.csv"
    signal_risk_block_df.to_csv(risk_file, index=False, encoding="utf-8-sig")
    signal_risk_block_df.to_csv(risk_latest_file, index=False, encoding="utf-8-sig")
    summary_obj = {
        "date": target_date.strftime("%Y-%m-%d"),
        "output_profile": str(output_profile),
        "market_state": regime.get("state", ""),
        "regime_top_n": int(regime_top_n),
        "ranking_col": str(ranking_col),
        "score_quantile_q": float(q),
        "score_quantile_source": str(q_source),
        "score_floor": float(score_floor),
        "raw_candidates": int(len(today_df)),
        "tradable_filtered": int(len(filtered_df)),
        "score_gated": int(len(gated_df)),
        "optimizer_candidate_pool_n": int(optimizer_pool_n),
        "optimizer_primary_top_n": int(regime_top_n),
        "reserve_candidate_count": int(max(0, _profile_int(profile_cfg, "reserve_candidate_count", 0))),
        "capacity_safe_reserve": dict(reserve_rank_info),
        "tradability_safe_ranking": dict(tradability_rank_info),
        "liquidity_stage": str(liquidity_stage),
        "liquidity_blend": float(liquidity_blend),
        "adv_penalty_blend": float(adv_penalty_blend),
        "industry_crowding_blend": float(industry_crowding_blend),
        "min_price": float(profile_min_price),
        "min_amount_ma20": float(profile_min_amount_ma20),
        "pretrade": dict(signal_risk_info),
        "topn_pretrade_eval": dict(topn_pretrade_eval),
        "optimizer": dict(optimizer_info),
        "holiday_gap_guard": dict(holiday_gap_info),
        "target_weight_checksum": str(target_weight_checksum),
        "research_stage_snapshot": {
            "enabled": bool(write_research_stages),
            "file": str(research_stage_file),
            "latest_file": str(research_stage_latest_file),
            "stage_count": int(len(research_stage_frames)),
        },
    }
    summary_file = risk_dir / f"signal_pretrade_summary_{date_str}.json"
    summary_latest_file = risk_dir / "signal_pretrade_summary_latest.json"
    summary_txt = json.dumps(_to_jsonable(summary_obj), ensure_ascii=False, indent=2)
    summary_file.write_text(summary_txt, encoding="utf-8")
    summary_latest_file.write_text(summary_txt, encoding="utf-8")
    
    # 8. 打印结果
    print("\n" + "=" * 70)
    print("市场状态与仓位建议")
    print("=" * 70)
    print(
        f"状态: {regime['state']} | 建议总仓: {regime['position_range']} | 单票上限: {regime['single_stock_max']} "
        f"| 下跌占比: {regime['down_ratio']:.2%} | 中位涨跌幅: {regime['median_chg']:.2f}% | 深超跌占比: {regime['deep_oversold_ratio']:.2%}"
    )
    print(
        f"候选数: {len(today_df)} | 过滤后: {len(filtered_df)} | 评分门槛后: {len(gated_df)} "
        f"(涨停触发过滤: {int(hard_limit.sum())}, 过热过滤: {int(overheat.sum())}, 量能异常过滤: {int(vol_anomaly.sum())})"
    )
    print(
        f"出榜模式: {fallback_stage} + {liquidity_stage} + {quality_stage} | 市场限额TopN: {regime_top_n} "
        f"| 质量门槛: {quality_floor:.2f} | 打分列: {ranking_col} | 分位门槛(q={q:.2f}): {score_floor:.4f}"
    )
    print(
        f"前置风控: {signal_risk_info.get('stage', 'pretrade_off')} "
        f"| gate_trade_date: {signal_risk_info.get('trade_date', target_date.strftime('%Y-%m-%d'))} "
        f"| pool={int(signal_risk_info.get('pool_n', 0))} kept={int(signal_risk_info.get('kept_count', 0))} "
        f"blocked={int(signal_risk_info.get('blocked_count', 0))} ({float(signal_risk_info.get('blocked_rate_pct', 0.0)):.2f}%) "
        f"| missing_industry={int(signal_risk_info.get('missing_industry_count', 0))} "
        f"| unknown_industry_hit={int(signal_risk_info.get('unknown_industry_limits_hit', 0))} "
        f"| top_reason={signal_risk_info.get('top_reason', 'none')}:{int(signal_risk_info.get('top_reason_count', 0))}"
    )
    print(
        f"TopN复核: input={int(topn_pretrade_eval.get('input_count', 0))} "
        f"blocked={int(topn_pretrade_eval.get('blocked_count', 0))} "
        f"({float(topn_pretrade_eval.get('blocked_rate_pct', 0.0)):.2f}%) "
        f"| missing_industry={int(topn_pretrade_eval.get('missing_industry_count', 0))} "
        f"| unknown_industry_hit={int(topn_pretrade_eval.get('unknown_industry_limits_hit', 0))} "
        f"| top_reason={topn_pretrade_eval.get('top_reason', 'none')}:{int(topn_pretrade_eval.get('top_reason_count', 0))}"
    )
    print(
        f"节假日/长间隔保护: guard={int(bool(holiday_gap_info.get('guard', False)))} "
        f"| reason={holiday_gap_info.get('reason', 'none')} "
        f"| signal_gap={int(holiday_gap_info.get('signal_trade_gap_days', 0))}d "
        f"| post_trade_gap={int(holiday_gap_info.get('post_trade_gap_days', 0))}d "
        f"| target_scale={float(holiday_gap_info.get('target_scale', 1.0)):.2f}"
    )

    print("\n" + "=" * 70)
    print(f"Top {regime_top_n} 目标股票 / reserve 后实际 {len(result)} 只")
    print("=" * 70)
    print(result.to_string(index=False))
    
    print(f"\n✅ 结果已保存: {output_file} (兼容写入: {legacy_file})")
    print(f"✅ 前置风控拦截明细: {risk_file} (latest: {risk_latest_file})")
    print(f"✅ 前置风控汇总: {summary_file} (latest: {summary_latest_file})")
    if research_stage_file:
        print(f"✅ 研究阶段候选池快照: {research_stage_file} (latest: {research_stage_latest_file})")
    
    return result


def main():
    parser = argparse.ArgumentParser(description='MFTS ML每日选股')
    parser.add_argument('--date', type=str, help='目标日期(YYYYMMDD)，默认最新交易日')
    parser.add_argument('--top', type=int, default=None, help='选择Top N股票，默认读取 default_profile.top_n')
    parser.add_argument("--disable-industry-coverage-gate", action="store_true", help="关闭元数据行业覆盖率/新鲜度硬门禁")
    parser.add_argument(
        "--min-industry-coverage-pct",
        type=float,
        default=float(os.environ.get("MFTS_MIN_INDUSTRY_COVERAGE_PCT", "80.0")),
        help="元数据行业覆盖率最低阈值(%%)",
    )
    parser.add_argument(
        "--max-metadata-staleness-days",
        type=float,
        default=float(os.environ.get("MFTS_MAX_METADATA_STALENESS_DAYS", "3.0")),
        help="元数据允许的最大陈旧天数",
    )
    parser.add_argument(
        "--output-profile",
        type=str,
        default=os.environ.get("MFTS_DAILY_OUTPUT_PROFILE", ""),
        help="将 daily/risk 输出写入 profile 隔离目录 output/daily_profiles/<profile>/",
    )
    args = parser.parse_args()
    if str(args.output_profile or "").strip():
        os.environ["MFTS_DAILY_OUTPUT_PROFILE"] = str(args.output_profile).strip()
    profile_cfg = load_default_profile_config()
    
    if not bool(args.disable_industry_coverage_gate):
        metadata_asof = args.date
        if not metadata_asof:
            sessions = AShareMarketDataGateway().available_trade_dates()
            metadata_asof = sessions[-1] if sessions else ""
        metadata_health = load_ods_metadata_health(metadata_asof)
        metadata_gate = evaluate_metadata_guard(
            metadata_health,
            min_coverage_pct=float(args.min_industry_coverage_pct),
            max_age_days=float(args.max_metadata_staleness_days),
        )
        if not bool(metadata_gate.get("passed", False)):
            print(
                "⛔ ODS 元数据门禁未通过: "
                f"reason={metadata_gate.get('reason', '')} "
                f"| coverage={float(metadata_gate.get('coverage_pct', 0.0)):.2f}% "
                f"| min={float(metadata_gate.get('min_coverage_pct', 0.0)):.2f}% "
                f"| file={metadata_gate.get('file', '')}"
            )
            sys.exit(1)
        print(
            "✅ ODS 元数据门禁通过: "
            f"coverage={float(metadata_gate.get('coverage_pct', 0.0)):.2f}% "
            f"| file={metadata_gate.get('file', '')}"
        )

    try:
        result = select_stocks(target_date=args.date, top_n=args.top, profile_cfg=profile_cfg)
        if result is None or len(result) == 0:
            raw_allow_empty = os.environ.get("MFTS_ALLOW_EMPTY_DAILY_OUTPUT")
            allow_empty_output = _parse_bool_like(
                raw_allow_empty,
                default=bool(str(args.output_profile or "").strip()),
            )
            if allow_empty_output:
                print("\n⚠️ 选股为空：已保留空 daily 输出作为 no-entry / optimizer_empty evidence")
                return
            print("\n❌ 选股失败：无有效结果")
            sys.exit(2)
        print("\n✅ 选股完成!")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
