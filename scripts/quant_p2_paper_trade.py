#!/usr/bin/env python3
"""
P2 平台化执行：A 股纸面 OMS + 审计日志。

功能：
1) 读取 daily_YYYYMMDD 推荐并生成目标仓位
2) 按下一交易日开盘价模拟撮合（含滑点/手续费/印花税）
3) 持久化组合状态、订单/成交、资金曲线
4) 输出审计日志（可追溯每次再平衡决策）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.platform import (
    OrderEvent,
    OrderEventType,
    OrderLifecycleState,
    PortfolioConstraints,
    apply_order_event,
    build_config_fingerprint,
    build_portfolio_decision,
    build_run_manifest,
    finalize_run_manifest,
    load_security_config,
    write_run_manifest,
)
from core.execution import create_broker
from core.execution.paper_broker import PaperBroker
from core.risk import PreTradeRiskConfig, apply_pretrade_risk_gates, load_industry_map
from core.risk.pretrade import _load_blacklist
from utils.code_utils import limit_ratio_for_stock, normalize_ts_code, normalize_ts_code_series
from utils.metadata_guard import evaluate_metadata_guard, load_metadata_health
from utils.output_paths import get_output_dirs, list_dual

OUTPUT_DIR = Path(BASE_DIR) / "output"
DATA_DIR = Path(BASE_DIR) / "data"
PARQUET_FILE = DATA_DIR / "daily_all_5y.parquet"
PROFILE_FILE = Path(BASE_DIR) / "config" / "quant_live_profiles.json"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def _load_default_profile_values() -> dict[str, float]:
    defaults = {
        "top_n": 10,
        "max_single_pos": 0.06,
        "use_regime_position": True,
        "fallback_total_position": 0.60,
        "fee_bps": 8.0,
        "slippage_bps": 5.0,
        "risk_max_industry_weight": 0.35,
        "risk_max_adv_participation": 0.05,
        "risk_min_price": 2.0,
        "risk_max_style_size_exposure_abs": 0.0,
        "risk_max_style_beta_exposure_abs": 0.0,
        "risk_max_style_momentum_exposure_abs": 0.0,
        "risk_max_style_vol_exposure_abs": 0.0,
        "risk_style_lb_short": 20,
        "risk_style_lb_beta": 60,
        "optimizer_mode": "score_weight",
        "target_capital_base": 1_000_000.0,
        "target_max_industry_weight": 0.0,
        "target_max_adv_participation": 0.0,
        "target_capacity_amount_col": "amount_ma20",
        "target_capacity_amount_buffer": 1.0,
        "redistribute_clipped_weight": False,
        "reserve_pool_enabled": False,
        "optimizer_candidate_pool_multiplier": 1.0,
        "optimizer_candidate_pool_max_n": 0,
        "reserve_candidate_count": 0,
        "reserve_reoptimize_rounds": 2,
        "target_score_col": "",
        "capacity_safe_reserve_enabled": False,
        "blocked_state_enabled": True,
        "block_buy_on_exit_blocked": False,
        "blocked_exit_freeze_min_weight": 0.0,
        "impact_model": "sqrt",
        "impact_base_bps": 0.0,
        "impact_participation_bps": 0.0,
        "impact_power": 0.5,
        "exclude_st": True,
    }
    try:
        if not PROFILE_FILE.exists():
            return defaults
        root = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        profile_name = str(os.environ.get("MFTS_P2_PROFILE") or root.get("default_profile", "balanced"))
        p = root.get("profiles", {}).get(profile_name, {})
        if not isinstance(p, dict):
            return defaults
        defaults["top_n"] = int(p.get("top_n", defaults["top_n"]))
        defaults["max_single_pos"] = float(p.get("max_single_pos", defaults["max_single_pos"]))
        raw_use_regime = p.get("use_regime_position", defaults["use_regime_position"])
        if isinstance(raw_use_regime, bool):
            defaults["use_regime_position"] = raw_use_regime
        else:
            defaults["use_regime_position"] = str(raw_use_regime).strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        defaults["fallback_total_position"] = float(p.get("fallback_total_position", defaults["fallback_total_position"]))
        defaults["fee_bps"] = float(p.get("fee_bps", defaults["fee_bps"]))
        defaults["slippage_bps"] = float(p.get("slippage_bps", defaults["slippage_bps"]))
        defaults["risk_max_industry_weight"] = float(p.get("risk_max_industry_weight", defaults["risk_max_industry_weight"]))
        defaults["risk_max_adv_participation"] = float(p.get("risk_max_adv_participation", defaults["risk_max_adv_participation"]))
        defaults["risk_min_price"] = float(p.get("risk_min_price", defaults["risk_min_price"]))
        defaults["risk_max_style_size_exposure_abs"] = float(
            p.get("risk_max_style_size_exposure_abs", defaults["risk_max_style_size_exposure_abs"])
        )
        defaults["risk_max_style_beta_exposure_abs"] = float(
            p.get("risk_max_style_beta_exposure_abs", defaults["risk_max_style_beta_exposure_abs"])
        )
        defaults["risk_max_style_momentum_exposure_abs"] = float(
            p.get("risk_max_style_momentum_exposure_abs", defaults["risk_max_style_momentum_exposure_abs"])
        )
        defaults["risk_max_style_vol_exposure_abs"] = float(
            p.get("risk_max_style_vol_exposure_abs", defaults["risk_max_style_vol_exposure_abs"])
        )
        defaults["risk_style_lb_short"] = int(p.get("risk_style_lb_short", defaults["risk_style_lb_short"]))
        defaults["risk_style_lb_beta"] = int(p.get("risk_style_lb_beta", defaults["risk_style_lb_beta"]))
        defaults["optimizer_mode"] = str(p.get("optimizer_mode", defaults["optimizer_mode"]))
        defaults["target_capital_base"] = float(p.get("target_capital_base", defaults["target_capital_base"]))
        defaults["target_max_industry_weight"] = float(
            p.get("target_max_industry_weight", p.get("risk_max_industry_weight", defaults["target_max_industry_weight"]))
        )
        defaults["target_max_adv_participation"] = float(
            p.get("target_max_adv_participation", p.get("risk_max_adv_participation", defaults["target_max_adv_participation"]))
        )
        defaults["target_capacity_amount_col"] = str(
            p.get("target_capacity_amount_col", defaults["target_capacity_amount_col"]) or defaults["target_capacity_amount_col"]
        )
        defaults["target_capacity_amount_buffer"] = float(
            p.get("target_capacity_amount_buffer", defaults["target_capacity_amount_buffer"])
        )
        raw_redistribute = p.get("redistribute_clipped_weight", defaults["redistribute_clipped_weight"])
        if isinstance(raw_redistribute, bool):
            defaults["redistribute_clipped_weight"] = raw_redistribute
        else:
            defaults["redistribute_clipped_weight"] = str(raw_redistribute).strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            }
        raw_reserve = p.get("reserve_pool_enabled", defaults["reserve_pool_enabled"])
        if isinstance(raw_reserve, bool):
            defaults["reserve_pool_enabled"] = raw_reserve
        else:
            defaults["reserve_pool_enabled"] = str(raw_reserve).strip().lower() in {"1", "true", "yes", "y", "on"}
        defaults["optimizer_candidate_pool_multiplier"] = float(
            p.get("optimizer_candidate_pool_multiplier", defaults["optimizer_candidate_pool_multiplier"])
        )
        defaults["optimizer_candidate_pool_max_n"] = int(
            float(p.get("optimizer_candidate_pool_max_n", defaults["optimizer_candidate_pool_max_n"]))
        )
        defaults["reserve_candidate_count"] = int(float(p.get("reserve_candidate_count", defaults["reserve_candidate_count"])))
        defaults["reserve_reoptimize_rounds"] = int(
            float(p.get("reserve_reoptimize_rounds", defaults["reserve_reoptimize_rounds"]))
        )
        defaults["target_score_col"] = str(p.get("target_score_col", defaults["target_score_col"]) or "")
        raw_capacity_safe = p.get("capacity_safe_reserve_enabled", defaults["capacity_safe_reserve_enabled"])
        if isinstance(raw_capacity_safe, bool):
            defaults["capacity_safe_reserve_enabled"] = raw_capacity_safe
        else:
            defaults["capacity_safe_reserve_enabled"] = str(raw_capacity_safe).strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            }
        raw_block_state = p.get("blocked_state_enabled", defaults["blocked_state_enabled"])
        if isinstance(raw_block_state, bool):
            defaults["blocked_state_enabled"] = raw_block_state
        else:
            defaults["blocked_state_enabled"] = str(raw_block_state).strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        raw_block_buy = p.get("block_buy_on_exit_blocked", defaults["block_buy_on_exit_blocked"])
        if isinstance(raw_block_buy, bool):
            defaults["block_buy_on_exit_blocked"] = raw_block_buy
        else:
            defaults["block_buy_on_exit_blocked"] = str(raw_block_buy).strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
                "on",
            }
        defaults["blocked_exit_freeze_min_weight"] = float(
            p.get("blocked_exit_freeze_min_weight", defaults["blocked_exit_freeze_min_weight"])
        )
        defaults["impact_model"] = str(p.get("impact_model", defaults["impact_model"]))
        defaults["impact_base_bps"] = float(p.get("impact_base_bps", defaults["impact_base_bps"]))
        defaults["impact_participation_bps"] = float(p.get("impact_participation_bps", defaults["impact_participation_bps"]))
        defaults["impact_power"] = float(p.get("impact_power", defaults["impact_power"]))
        raw_exclude_st = p.get("exclude_st", defaults["exclude_st"])
        if isinstance(raw_exclude_st, bool):
            defaults["exclude_st"] = raw_exclude_st
        else:
            defaults["exclude_st"] = str(raw_exclude_st).strip().lower() not in {"0", "false", "no", "off"}
    except Exception:
        return defaults
    return defaults


DEFAULTS = _load_default_profile_values()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return float(default)


def _parse_percent_text(text: object, fallback: float) -> float:
    s = str(text or "").strip()
    if not s:
        return fallback
    m = re.findall(r"(\d+(?:\.\d+)?)\s*%", s)
    if m:
        vals = [float(x) for x in m]
        return float(np.mean(vals)) / 100.0
    try:
        v = float(s)
        return v / 100.0 if v > 1 else v
    except Exception:
        return fallback


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _parse_bool_like(v: object, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    if not s:
        return default
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _profile_int(profile_cfg: dict[str, object], key: str, default: int = 0) -> int:
    try:
        return int(float(profile_cfg.get(key, default)))
    except Exception:
        return int(default)


def _resolve_candidate_pool_n(top_n: int, profile_cfg: dict[str, object], available_n: int | None = None) -> int:
    top_n = max(1, int(top_n))
    multiplier = max(1.0, _safe_float(profile_cfg.get("optimizer_candidate_pool_multiplier", 1.0), 1.0))
    reserve_count = max(0, _profile_int(profile_cfg, "reserve_candidate_count", 0))
    pool_n = max(top_n, int(np.ceil(float(top_n) * multiplier)), top_n + reserve_count)
    max_n = max(0, _profile_int(profile_cfg, "optimizer_candidate_pool_max_n", 0))
    if max_n > 0:
        pool_n = min(pool_n, max(top_n, max_n))
    if available_n is not None:
        pool_n = min(pool_n, max(1, int(available_n)))
    return max(1, int(pool_n))


def _sanitize_channel(name: object, fallback: str) -> str:
    s = str(name or "").strip().lower()
    if not s:
        return fallback
    s = re.sub(r"[^a-z0-9_]+", "_", s).strip("_")
    return s or fallback


def _resolve_signal_file(explicit_file: str | None, explicit_date: str | None) -> Path | None:
    if explicit_file:
        p = Path(explicit_file)
        return p if p.exists() else None

    dirs = get_output_dirs(OUTPUT_DIR)
    if explicit_date:
        cands = [
            dirs["daily"] / f"daily_{explicit_date}.csv",
            dirs["base"] / f"daily_{explicit_date}.csv",
        ]
        for p in cands:
            if p.exists():
                return p
        return None

    files = list_dual(["daily_*.csv"], dirs["daily"], dirs["base"])
    if not files:
        return None
    return sorted(files)[-1]


def _resolve_recommendation_file(explicit_file: str | None) -> Path | None:
    if explicit_file:
        p = Path(explicit_file)
        return p if p.exists() else None
    candidates = [
        OUTPUT_DIR / "backtest" / "quant_strategy_paper_recommendations.csv",
        OUTPUT_DIR / "quant_strategy_paper_recommendations.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_recommendation_row(path: Path, rank: int) -> dict[str, object]:
    df = pd.read_csv(path)
    if df.empty:
        raise RuntimeError(f"推荐参数文件为空: {path}")
    target_rank = max(1, int(rank))

    chosen = None
    if "recommend_rank" in df.columns:
        rr = pd.to_numeric(df["recommend_rank"], errors="coerce")
        sub = df[rr == target_rank]
        if not sub.empty:
            chosen = sub.iloc[0]
    if chosen is None:
        idx = target_rank - 1
        if idx < 0 or idx >= len(df):
            raise RuntimeError(f"推荐参数 rank={target_rank} 超出范围，文件仅 {len(df)} 行")
        chosen = df.iloc[idx]

    top_n = int(_safe_float(chosen.get("top_n", DEFAULTS["top_n"]), DEFAULTS["top_n"]))
    max_single_pos = float(_safe_float(chosen.get("max_single_pos", DEFAULTS["max_single_pos"]), DEFAULTS["max_single_pos"]))
    use_regime_position = _parse_bool_like(chosen.get("use_regime_position", False), default=False)
    holding_days = int(_safe_float(chosen.get("holding_days", 0), 0))
    return {
        "top_n": max(1, top_n),
        "max_single_pos": min(max(max_single_pos, 0.0), 1.0),
        "use_regime_position": bool(use_regime_position),
        "holding_days": max(0, holding_days),
        "recommend_rank": int(_safe_float(chosen.get("recommend_rank", target_rank), target_rank)),
        "risk_tier": str(chosen.get("risk_tier", "") or ""),
        "selection_mode": str(chosen.get("selection_mode", "") or ""),
        "objective_score": float(_safe_float(chosen.get("objective_score", np.nan), np.nan)),
        "raw": chosen.to_dict(),
    }


def _extract_signal_date(signal_file: Path) -> pd.Timestamp:
    m = re.search(r"daily_(\d{8})\.csv$", signal_file.name)
    if m:
        dt = pd.to_datetime(m.group(1), format="%Y%m%d", errors="coerce")
        if pd.notna(dt):
            return dt.normalize()
    df = pd.read_csv(signal_file, nrows=3)
    if "日期" in df.columns and not df.empty:
        dt = pd.to_datetime(df["日期"].iloc[0], errors="coerce")
        if pd.notna(dt):
            return dt.normalize()
    raise RuntimeError(f"无法从推荐文件识别日期: {signal_file}")


def _load_signal_df(signal_file: Path, top_n: int, include_bj9: bool, exclude_st: bool) -> pd.DataFrame:
    df = pd.read_csv(signal_file, dtype={"代码": str})
    if df.empty or "代码" not in df.columns:
        raise RuntimeError(f"推荐文件缺少有效数据: {signal_file}")
    work = df.copy()
    work["代码"] = normalize_ts_code_series(work["代码"])
    work = work[work["代码"] != ""].copy()
    if not include_bj9:
        work = work[~work["代码"].astype(str).str.startswith("9")].copy()
    if "排名" in work.columns:
        work["排名_num"] = pd.to_numeric(work["排名"], errors="coerce")
        work = work.sort_values("排名_num")
    else:
        work["排名_num"] = np.arange(1, len(work) + 1)
    if "ML评分" not in work.columns:
        work["ML评分"] = np.linspace(1.0, 0.5, num=len(work))
    work["ML评分"] = pd.to_numeric(work["ML评分"], errors="coerce").fillna(0.0)
    if "名称" not in work.columns:
        work["名称"] = work["代码"]
    if exclude_st:
        work = work[~work["名称"].astype(str).str.contains("ST", case=False, na=False)].copy()
    return work.head(max(1, top_n)).reset_index(drop=True)


def _positive_min(values: list[float]) -> float:
    vals = []
    for x in values:
        v = _safe_float(x, 0.0)
        if np.isfinite(v) and v > 0:
            vals.append(float(v))
    return float(min(vals)) if vals else 0.0


def _enrich_signal_amount_ma20(
    signal_df: pd.DataFrame,
    bars_idx: pd.DataFrame,
    signal_date: pd.Timestamp,
    trade_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    work = signal_df.copy()
    amount_ma20: list[float] = []
    amount_last: list[float] = []
    amount_min5: list[float] = []
    amount_min10: list[float] = []
    amount_trade_day: list[float] = []
    amount_capacity_conservative: list[float] = []
    amount_execution_capacity: list[float] = []

    existing_ma20 = (
        pd.to_numeric(work["amount_ma20"], errors="coerce").fillna(0.0).tolist()
        if "amount_ma20" in work.columns
        else [0.0] * len(work)
    )
    for i, code in enumerate(work["代码"].astype(str).map(normalize_ts_code)):
        signal_row = _get_bar_row(bars_idx, signal_date, code)
        trade_row = _get_bar_row(bars_idx, trade_date, code) if trade_date is not None else None
        ma20 = _safe_float(signal_row.get("amount_ma20", 0.0), 0.0) if signal_row is not None else 0.0
        if ma20 <= 0:
            ma20 = _safe_float(existing_ma20[i], 0.0)
        last = _safe_float(signal_row.get("amount", 0.0), 0.0) if signal_row is not None else 0.0
        min5 = _safe_float(signal_row.get("amount_min5", 0.0), 0.0) if signal_row is not None else 0.0
        min10 = _safe_float(signal_row.get("amount_min10", 0.0), 0.0) if signal_row is not None else 0.0
        traded = _safe_float(trade_row.get("amount", 0.0), 0.0) if trade_row is not None else 0.0
        conservative = _positive_min([ma20, last, min5, min10])
        execution = _positive_min([conservative, traded]) if traded > 0 else conservative
        amount_ma20.append(float(ma20))
        amount_last.append(float(last))
        amount_min5.append(float(min5))
        amount_min10.append(float(min10))
        amount_trade_day.append(float(traded))
        amount_capacity_conservative.append(float(conservative))
        amount_execution_capacity.append(float(execution))

    work["amount_ma20"] = amount_ma20
    work["amount_last"] = amount_last
    work["amount_min5"] = amount_min5
    work["amount_min10"] = amount_min10
    work["amount_trade_day"] = amount_trade_day
    work["amount_capacity_conservative"] = amount_capacity_conservative
    work["amount_execution_capacity"] = amount_execution_capacity
    if "成交额MA20" not in work.columns:
        work["成交额MA20"] = work["amount_ma20"]
    return work


def _assign_profile_target_weights(
    *,
    signal_df: pd.DataFrame,
    profile_cfg: dict[str, object],
    total_target_pos: float,
    max_single_pos: float,
    industry_map: dict[str, str],
    primary_top_n: int | None = None,
) -> pd.DataFrame:
    work = signal_df.copy()
    if "target_weight" in work.columns:
        existing = pd.to_numeric(work["target_weight"], errors="coerce").fillna(0.0)
    else:
        existing = pd.Series([0.0] * len(work), index=work.index)
    if len(existing) == len(work) and float(existing.clip(lower=0.0).sum()) > 0:
        return work

    optimizer_mode = str(profile_cfg.get("optimizer_mode", "score_weight") or "score_weight").strip().lower()
    capacity_on = optimizer_mode in {"capacity_aware", "capacity_crowding", "capacity_crowding_aware"}
    configured_score_col = str(profile_cfg.get("target_score_col", "") or "").strip()
    if configured_score_col and configured_score_col in work.columns:
        score_col = configured_score_col
    elif _parse_bool_like(profile_cfg.get("capacity_safe_reserve_enabled", False), default=False) and "portfolio_rank_score" in work.columns:
        score_col = "portfolio_rank_score"
    else:
        score_col = "重构分" if "重构分" in work.columns else ("综合分" if "综合分" in work.columns else "ML评分")
    if score_col not in work.columns:
        work[score_col] = np.linspace(1.0, 0.5, num=len(work))
    work["industry"] = work["代码"].astype(str).map(lambda x: industry_map.get(normalize_ts_code(x), "")).fillna("").astype(str)
    industry_cap = 0.0
    adv_cap = 0.0
    if capacity_on:
        industry_raw = _safe_float(
            profile_cfg.get("target_max_industry_weight", profile_cfg.get("risk_max_industry_weight", 0.0)),
            0.0,
        )
        adv_raw = _safe_float(
            profile_cfg.get("target_max_adv_participation", profile_cfg.get("risk_max_adv_participation", 0.0)),
            0.0,
        )
        industry_cap = min(max(industry_raw, 0.0), 1.0)
        adv_cap = min(max(adv_raw, 0.0), 1.0)
    amount_col = str(profile_cfg.get("target_capacity_amount_col", "amount_ma20") or "amount_ma20")
    if amount_col not in work.columns:
        amount_col = "amount_ma20"
    amount_buffer = max(0.0, _safe_float(profile_cfg.get("target_capacity_amount_buffer", 1.0), 1.0))
    decision = build_portfolio_decision(
        work,
        PortfolioConstraints(
            total_target=min(max(float(total_target_pos), 0.0), 1.0),
            single_cap=min(max(float(max_single_pos), 0.0), 1.0),
            industry_cap=industry_cap,
            adv_participation_cap=adv_cap,
            capital_base=max(100000.0, _safe_float(profile_cfg.get("target_capital_base", 1_000_000.0), 1_000_000.0)),
            max_names=max(0, int(primary_top_n or 0)),
            min_names=max(0, _profile_int(profile_cfg, "min_valid_positions", 0)),
            score_col=score_col,
            code_col="代码",
            industry_col="industry",
            amount_col=amount_col,
            amount_buffer=amount_buffer,
            redistribute_clipped=_parse_bool_like(profile_cfg.get("redistribute_clipped_weight", False), default=False),
            impact_model=str(profile_cfg.get("impact_model", "sqrt") or "sqrt"),
            impact_base_bps=max(0.0, _safe_float(profile_cfg.get("impact_base_bps", 0.0), 0.0)),
            impact_participation_bps=max(0.0, _safe_float(profile_cfg.get("impact_participation_bps", 0.0), 0.0)),
            impact_power=max(0.10, _safe_float(profile_cfg.get("impact_power", 0.5), 0.5)),
        ),
    )
    selected = decision.selected.copy()
    if selected.empty:
        work["target_weight"] = 0.0
        work["target_weight_raw"] = 0.0
        work["participation_pct"] = 0.0
        work["impact_cost_bps"] = 0.0
        work["unfilled_target_weight"] = 0.0
        work["industry_weight_post"] = 0.0
        work["constraint_reason"] = "optimizer_empty"
        return work
    return selected.reset_index(drop=True)


def _load_bars() -> pd.DataFrame:
    if not PARQUET_FILE.exists():
        raise FileNotFoundError(f"未找到行情数据: {PARQUET_FILE}")
    cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
    df = pd.read_parquet(PARQUET_FILE, columns=cols)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="coerce").dt.normalize()
    df["code"] = normalize_ts_code_series(df["ts_code"])
    for c in ("open", "high", "low", "close", "vol", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["trade_date", "code"])
    df = df[df["code"] != ""].copy()
    df = df.sort_values(["code", "trade_date"]).reset_index(drop=True)
    df["prev_close"] = df.groupby("code", observed=True)["close"].shift(1)
    df["amount_ma20"] = (
        df.groupby("code", observed=True)["amount"]
        .transform(lambda s: s.rolling(20, min_periods=5).mean())
        .fillna(0.0)
    )
    df["amount_min5"] = (
        df.groupby("code", observed=True)["amount"]
        .transform(lambda s: s.rolling(5, min_periods=1).min())
        .fillna(0.0)
    )
    df["amount_min10"] = (
        df.groupby("code", observed=True)["amount"]
        .transform(lambda s: s.rolling(10, min_periods=3).min())
        .fillna(df["amount_min5"])
    )
    return df


def _get_next_trade_day(trading_days: list[pd.Timestamp], signal_date: pd.Timestamp) -> pd.Timestamp | None:
    for d in trading_days:
        if d > signal_date:
            return d
    return None


def _get_bar_row(bars_idx: pd.DataFrame, trade_date: pd.Timestamp, code: str) -> pd.Series | None:
    try:
        row = bars_idx.loc[(trade_date, code)]
    except KeyError:
        return None
    if isinstance(row, pd.DataFrame):
        if row.empty:
            return None
        return row.iloc[-1]
    return row


def _is_suspended(row: pd.Series | None) -> bool:
    if row is None:
        return True
    op = _safe_float(row.get("open", np.nan), np.nan)
    vol = _safe_float(row.get("vol", np.nan), np.nan)
    amt = _safe_float(row.get("amount", np.nan), np.nan)
    return (not np.isfinite(op)) or op <= 0 or (not np.isfinite(vol)) or vol <= 0 or (not np.isfinite(amt)) or amt <= 0


def _is_locked_limit_up(row: pd.Series | None, limit_ratio: float) -> bool:
    if row is None:
        return False
    prev_close = _safe_float(row.get("prev_close", np.nan), np.nan)
    op = _safe_float(row.get("open", np.nan), np.nan)
    hi = _safe_float(row.get("high", np.nan), np.nan)
    lo = _safe_float(row.get("low", np.nan), np.nan)
    if (not np.isfinite(prev_close)) or prev_close <= 0:
        return False
    limit_up = prev_close * (1.0 + abs(limit_ratio))
    return (op >= limit_up * 0.999) and (hi >= limit_up * 0.999) and (lo >= limit_up * 0.999)


def _is_locked_limit_down(row: pd.Series | None, limit_ratio: float) -> bool:
    if row is None:
        return False
    prev_close = _safe_float(row.get("prev_close", np.nan), np.nan)
    op = _safe_float(row.get("open", np.nan), np.nan)
    hi = _safe_float(row.get("high", np.nan), np.nan)
    lo = _safe_float(row.get("low", np.nan), np.nan)
    if (not np.isfinite(prev_close)) or prev_close <= 0:
        return False
    limit_down = prev_close * (1.0 - abs(limit_ratio))
    return (op <= limit_down * 1.001) and (hi <= limit_down * 1.001) and (lo <= limit_down * 1.001)


def _can_enter(row: pd.Series | None, code: str, name: str) -> bool:
    if _is_suspended(row):
        return False
    ratio = limit_ratio_for_stock(code, name)
    return not _is_locked_limit_up(row, ratio)


def _can_exit(row: pd.Series | None, code: str, name: str) -> bool:
    if _is_suspended(row):
        return False
    ratio = limit_ratio_for_stock(code, name)
    return not _is_locked_limit_down(row, ratio)


def _load_state(state_file: Path, initial_capital: float, reset_state: bool) -> dict[str, object]:
    if reset_state or not state_file.exists():
        return {
            "version": 1,
            "cash": float(initial_capital),
            "positions": {},
            "nav": float(initial_capital),
            "last_trade_date": "",
            "last_signal_date": "",
        }
    try:
        st = json.loads(state_file.read_text(encoding="utf-8"))
        if not isinstance(st, dict):
            raise ValueError("bad state format")
        st.setdefault("positions", {})
        st.setdefault("cash", float(initial_capital))
        return st
    except Exception:
        return {
            "version": 1,
            "cash": float(initial_capital),
            "positions": {},
            "nav": float(initial_capital),
            "last_trade_date": "",
            "last_signal_date": "",
        }


def _save_state(state_file: Path, state: dict[str, object], dry_run: bool) -> None:
    if dry_run:
        return
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _mark_to_market(positions: dict[str, dict[str, object]], bars_idx: pd.DataFrame, trade_date: pd.Timestamp) -> tuple[float, dict[str, float]]:
    market_value = 0.0
    px_map: dict[str, float] = {}
    for code, pos in positions.items():
        qty = int(pos.get("qty", 0))
        if qty <= 0:
            continue
        bar = _get_bar_row(bars_idx, trade_date, code)
        if bar is None:
            px = _safe_float(pos.get("avg_cost", 0.0), 0.0)
        else:
            px = _safe_float(bar.get("open", np.nan), np.nan)
            if not np.isfinite(px) or px <= 0:
                px = _safe_float(pos.get("avg_cost", 0.0), 0.0)
        px_map[code] = float(px)
        market_value += float(qty * px)
    return market_value, px_map


def _append_audit_event(audit_file: Path, event: dict[str, object]) -> None:
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False)
    with open(audit_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _attach_order_lifecycle(orders_df: pd.DataFrame) -> pd.DataFrame:
    if orders_df is None or orders_df.empty:
        return orders_df.copy() if orders_df is not None else pd.DataFrame()

    enriched_rows: list[dict[str, object]] = []
    for row in orders_df.to_dict(orient="records"):
        requested_qty = int(_safe_float(row.get("requested_qty", 0), 0))
        filled_qty = int(_safe_float(row.get("filled_qty", 0), 0))
        state = OrderLifecycleState(
            order_id=f"{row.get('run_id', '')}:{row.get('code', '')}:{row.get('side', '')}:{row.get('rank', '')}",
            requested_qty=max(requested_qty, 0),
        )
        state = apply_order_event(state, OrderEvent(OrderEventType.CREATE))
        raw_status = str(row.get("status", "") or "").strip().lower()
        reason = str(row.get("reason", "") or "")

        if raw_status == "blocked":
            state = apply_order_event(state, OrderEvent(OrderEventType.BLOCK, reason=reason))
        elif raw_status == "rejected":
            state = apply_order_event(state, OrderEvent(OrderEventType.REJECT, reason=reason))
        else:
            state = apply_order_event(state, OrderEvent(OrderEventType.SUBMIT, reason="paper_submit"))
            state = apply_order_event(state, OrderEvent(OrderEventType.ACK, reason="paper_ack"))
            if raw_status == "partial":
                state = apply_order_event(state, OrderEvent(OrderEventType.PARTIAL_FILL, qty=filled_qty, reason=reason))
            elif raw_status == "filled":
                state = apply_order_event(state, OrderEvent(OrderEventType.FILL, qty=filled_qty, reason=reason))

        row["lifecycle_status"] = str(state.status.value)
        row["lifecycle_terminal"] = int(bool(state.is_terminal))
        row["lifecycle_retry_count"] = int(state.retry_count)
        row["lifecycle_remaining_qty"] = int(state.remaining_qty)
        enriched_rows.append(row)
    return pd.DataFrame(enriched_rows)


def _build_p2_manifest(
    *,
    argv: list[str],
    signal_file: Path,
    state_file: str,
    recommendation_file: Path | None,
    broker_name: str,
    live_mode: str,
) -> Path:
    security_cfg = load_security_config()
    tracked_files: dict[str, str | Path] = {
        "daily_data": PARQUET_FILE,
        "stock_meta": DATA_DIR / "stock_info.csv",
        "profile_config": PROFILE_FILE,
        "signal_file": signal_file,
        "state_file": state_file,
    }
    if recommendation_file is not None:
        tracked_files["recommendation_file"] = recommendation_file
    manifest = build_run_manifest(
        run_type="quant_p2_paper_trade",
        argv=argv,
        params={
            "broker": str(broker_name),
            "live_mode": str(live_mode),
            "state_file": str(state_file),
        },
        tracked_files=tracked_files,
        config_fingerprint=build_config_fingerprint(security_cfg),
    )
    return write_run_manifest(BASE_DIR, manifest)


def _rebalance(
    signal_df: pd.DataFrame,
    state: dict[str, object],
    bars_idx: pd.DataFrame,
    signal_date: pd.Timestamp,
    trade_date: pd.Timestamp,
    top_n: int,
    total_target_pos: float,
    max_single_pos: float,
    lot_size: int,
    fee_bps: float,
    slippage_bps: float,
    stamp_tax_bps: float,
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    broker = PaperBroker(
        state_file=Path("__legacy_in_memory_paper_state.json"),
        initial_capital=max(100000.0, _safe_float(state.get("cash", 0.0), 0.0)),
        lot_size=max(1, int(lot_size)),
        fee_bps=max(0.0, float(fee_bps)),
        slippage_bps=max(0.0, float(slippage_bps)),
        stamp_tax_bps=max(0.0, float(stamp_tax_bps)),
        blocked_state_enabled=bool(DEFAULTS.get("blocked_state_enabled", True)),
        block_buy_on_exit_blocked=bool(DEFAULTS.get("block_buy_on_exit_blocked", False)),
        blocked_exit_freeze_min_weight=max(0.0, float(DEFAULTS.get("blocked_exit_freeze_min_weight", 0.0))),
    )
    result = broker.rebalance_on_state(
        state=state,
        signal_df=signal_df,
        signal_date=signal_date,
        trade_date=trade_date,
        bars_idx=bars_idx,
        run_id=run_id,
        top_n=top_n,
        target_total_pos=total_target_pos,
        max_single_pos=max_single_pos,
    )
    new_state = dict(result.state)
    new_state["run_info"] = dict(result.ledger_row)
    return result.orders_df, result.fills_df, new_state


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="P2 执行引擎（BrokerAdapter）")
    p.add_argument("--date", type=str, default=None, help="推荐日期 YYYYMMDD（不传则取最新 daily 文件）")
    p.add_argument("--signal-file", type=str, default=None, help="指定推荐文件路径")
    p.add_argument("--use-recommendation", action="store_true", help="从优化推荐表自动加载参数")
    p.add_argument("--recommend-file", type=str, default=os.environ.get("MFTS_RECOMMEND_FILE", ""), help="推荐参数表路径（默认 output/backtest/quant_strategy_paper_recommendations.csv）")
    p.add_argument("--recommend-rank", type=int, default=int(os.environ.get("MFTS_RECOMMEND_RANK", "1")), help="推荐参数序号（默认第1名）")
    p.add_argument("--recommend-keep-signal-position", action="store_true", help="即使推荐参数 use_regime_position=0，也保留信号里的建议仓位")
    p.add_argument("--broker", type=str, default=os.environ.get("MFTS_EXEC_BROKER", "paper"), help="执行通道（当前支持: paper/live）")
    p.add_argument("--channel", type=str, default=os.environ.get("MFTS_EXEC_CHANNEL", ""), help="输出通道名（默认跟随 broker，可用于隔离回放账本）")
    p.add_argument("--live-mode", type=str, default=os.environ.get("MFTS_LIVE_MODE", "shadow"), help="live 通道模式（shadow/gateway）")
    p.add_argument("--state-file", type=str, default=str(OUTPUT_DIR / "execution" / "paper_portfolio_state.json"), help="持仓状态文件")
    p.add_argument("--initial-capital", type=float, default=float(os.environ.get("MFTS_PAPER_CAPITAL", "1000000")), help="初始资金")
    p.add_argument("--top-n", type=int, default=int(DEFAULTS["top_n"]), help="目标持仓数")
    p.add_argument("--default-total-pos", type=float, default=float(DEFAULTS["fallback_total_position"]), help="默认总仓（推荐文件缺失仓位时）")
    p.add_argument("--target-total-pos", type=float, default=None, help="强制指定总仓（覆盖推荐文件）")
    p.add_argument("--max-single-pos", type=float, default=float(DEFAULTS["max_single_pos"]), help="单票上限")
    p.add_argument("--fee-bps", type=float, default=_env_float("MFTS_FEE_BPS", float(DEFAULTS["fee_bps"])), help="单边手续费 bps")
    p.add_argument("--slippage-bps", type=float, default=_env_float("MFTS_SLIPPAGE_BPS", float(DEFAULTS["slippage_bps"])), help="单边滑点 bps")
    p.add_argument("--stamp-tax-bps", type=float, default=10.0, help="卖出印花税 bps")
    p.add_argument("--lot-size", type=int, default=100, help="最小交易手（A股=100）")
    p.add_argument("--exclude-st", dest="exclude_st", action="store_true", default=bool(DEFAULTS.get("exclude_st", True)), help="过滤 ST/*ST")
    p.add_argument("--include-st", dest="exclude_st", action="store_false", help="包含 ST/*ST")
    p.add_argument("--include-bj9", action="store_true", help="包含北交所 9 开头")
    p.add_argument("--disable-pretrade-risk", action="store_true", help="关闭下单前风控硬门禁")
    p.add_argument("--risk-capital-base", type=float, default=0.0, help="风控容量测算资金（<=0 使用 initial-capital）")
    p.add_argument(
        "--risk-max-industry-weight",
        type=float,
        default=_env_float("MFTS_RISK_MAX_INDUSTRY_WEIGHT", float(DEFAULTS.get("risk_max_industry_weight", 0.35))),
        help="单行业目标权重上限(0~1)",
    )
    p.add_argument(
        "--risk-max-adv-participation",
        type=float,
        default=_env_float("MFTS_RISK_MAX_ADV_PARTICIPATION", float(DEFAULTS.get("risk_max_adv_participation", 0.05))),
        help="单票成交额参与率上限(0~1)",
    )
    p.add_argument(
        "--risk-min-price",
        type=float,
        default=_env_float("MFTS_RISK_MIN_PRICE", float(DEFAULTS.get("risk_min_price", 2.0))),
        help="最低开盘价过滤",
    )
    p.add_argument(
        "--risk-max-style-size-exposure-abs",
        type=float,
        default=_env_float(
            "MFTS_RISK_MAX_STYLE_SIZE_EXPOSURE_ABS",
            float(DEFAULTS.get("risk_max_style_size_exposure_abs", 0.0)),
        ),
        help="风格门禁：Size 暴露绝对值上限（<=0 关闭）",
    )
    p.add_argument(
        "--risk-max-style-beta-exposure-abs",
        type=float,
        default=_env_float(
            "MFTS_RISK_MAX_STYLE_BETA_EXPOSURE_ABS",
            float(DEFAULTS.get("risk_max_style_beta_exposure_abs", 0.0)),
        ),
        help="风格门禁：Beta 暴露绝对值上限（<=0 关闭）",
    )
    p.add_argument(
        "--risk-max-style-momentum-exposure-abs",
        type=float,
        default=_env_float(
            "MFTS_RISK_MAX_STYLE_MOMENTUM_EXPOSURE_ABS",
            float(DEFAULTS.get("risk_max_style_momentum_exposure_abs", 0.0)),
        ),
        help="风格门禁：Momentum 暴露绝对值上限（<=0 关闭）",
    )
    p.add_argument(
        "--risk-max-style-vol-exposure-abs",
        type=float,
        default=_env_float(
            "MFTS_RISK_MAX_STYLE_VOL_EXPOSURE_ABS",
            float(DEFAULTS.get("risk_max_style_vol_exposure_abs", 0.0)),
        ),
        help="风格门禁：Vol 暴露绝对值上限（<=0 关闭）",
    )
    p.add_argument(
        "--risk-style-lb-short",
        type=int,
        default=int(os.environ.get("MFTS_RISK_STYLE_LB_SHORT", str(int(DEFAULTS.get("risk_style_lb_short", 20))))),
        help="风格门禁：短窗回看（Momentum/Vol）",
    )
    p.add_argument(
        "--risk-style-lb-beta",
        type=int,
        default=int(os.environ.get("MFTS_RISK_STYLE_LB_BETA", str(int(DEFAULTS.get("risk_style_lb_beta", 60))))),
        help="风格门禁：Beta 回看窗口",
    )
    p.add_argument("--risk-blacklist-file", type=str, default=os.environ.get("MFTS_RISK_BLACKLIST_FILE", str(Path(BASE_DIR) / "config" / "pretrade_blacklist.txt")), help="黑名单文件（每行一个代码）")
    p.add_argument("--dry-run", action="store_true", help="只模拟，不写入持仓状态")
    p.add_argument("--reset-state", action="store_true", help="重置状态（从初始资金开始）")
    p.add_argument("--write-latest", action="store_true", help="写入 latest 快捷文件")
    p.add_argument("--disable-industry-coverage-gate", action="store_true", help="关闭元数据行业覆盖率/新鲜度硬门禁")
    p.add_argument(
        "--min-industry-coverage-pct",
        type=float,
        default=float(os.environ.get("MFTS_MIN_INDUSTRY_COVERAGE_PCT", "80.0")),
        help="元数据行业覆盖率最低阈值(%%)",
    )
    p.add_argument(
        "--max-metadata-staleness-days",
        type=float,
        default=float(os.environ.get("MFTS_MAX_METADATA_STALENESS_DAYS", "3.0")),
        help="元数据允许的最大陈旧天数",
    )
    p.add_argument("--strict", action="store_true", help="无推荐文件/无下一交易日时返回失败码")
    return p


def main() -> int:
    args = _build_parser().parse_args()

    rec_info: dict[str, object] | None = None
    recommendation_file: Path | None = None
    effective_top_n = max(1, int(args.top_n))
    effective_max_single = float(args.max_single_pos)
    if args.use_recommendation:
        recommendation_file = _resolve_recommendation_file(args.recommend_file)
        if recommendation_file is None:
            _log("未找到推荐参数文件，请先运行 quant_optimize.py 生成推荐表。")
            return 1 if args.strict else 0
        try:
            rec_info = _load_recommendation_row(recommendation_file, rank=max(1, int(args.recommend_rank)))
        except RuntimeError as e:
            _log(f"读取推荐参数失败: {e}")
            return 1 if args.strict else 0
        effective_top_n = int(rec_info["top_n"])
        effective_max_single = float(rec_info["max_single_pos"])
        _log(
            "已加载推荐参数: "
            f"rank={rec_info['recommend_rank']} top_n={effective_top_n} "
            f"max_single_pos={effective_max_single:.2f} "
            f"use_regime_position={rec_info['use_regime_position']}"
        )

    if not bool(args.disable_industry_coverage_gate):
        metadata_health = load_metadata_health(DATA_DIR)
        metadata_gate = evaluate_metadata_guard(
            metadata_health,
            min_coverage_pct=float(args.min_industry_coverage_pct),
            max_age_days=float(args.max_metadata_staleness_days),
        )
        if not bool(metadata_gate.get("passed", False)):
            _log(
                "⛔ 元数据门禁未通过: "
                f"reason={metadata_gate.get('reason', '')} "
                f"| coverage={float(metadata_gate.get('coverage_pct', 0.0)):.2f}% "
                f"| min={float(metadata_gate.get('min_coverage_pct', 0.0)):.2f}% "
                f"| age_days={float(metadata_gate.get('age_days', 0.0)):.2f} "
                f"| max_age_days={float(metadata_gate.get('max_age_days', 0.0)):.2f} "
                f"| file={metadata_gate.get('file', '')}"
            )
            return 1
        _log(
            "✅ 元数据门禁通过: "
            f"coverage={float(metadata_gate.get('coverage_pct', 0.0)):.2f}% "
            f"| age_days={float(metadata_gate.get('age_days', 0.0)):.2f} "
            f"| file={metadata_gate.get('file', '')}"
        )

    signal_file = _resolve_signal_file(args.signal_file, args.date)
    if signal_file is None:
        _log("未找到 daily 推荐文件，跳过 P2 OMS。")
        return 1 if args.strict else 0

    signal_date = _extract_signal_date(signal_file)
    _log(f"读取推荐文件: {signal_file} (signal_date={signal_date.date()})")
    candidate_pool_n = _resolve_candidate_pool_n(effective_top_n, DEFAULTS)
    signal_df = _load_signal_df(
        signal_file,
        top_n=candidate_pool_n,
        include_bj9=bool(args.include_bj9),
        exclude_st=bool(args.exclude_st),
    )
    if signal_df.empty:
        _log("推荐文件为空，跳过 P2 OMS。")
        return 1 if args.strict else 0

    bars = _load_bars()
    trading_days = sorted(bars["trade_date"].dropna().unique())
    trade_date = _get_next_trade_day(trading_days, signal_date)
    if trade_date is None:
        _log(f"signal_date={signal_date.date()} 后无下一交易日，跳过。")
        return 1 if args.strict else 0
    bars_idx = bars.set_index(["trade_date", "code"]).sort_index()

    use_signal_position = bool(DEFAULTS.get("use_regime_position", True))
    if rec_info and (not bool(rec_info.get("use_regime_position", True))) and (not args.recommend_keep_signal_position):
        use_signal_position = False

    total_target = float(args.default_total_pos)
    if args.target_total_pos is not None:
        total_target = float(args.target_total_pos)
    elif use_signal_position and "建议仓位" in signal_df.columns and not signal_df.empty:
        total_target = _parse_percent_text(signal_df["建议仓位"].iloc[0], total_target)

    max_single = float(effective_max_single)
    if "单票上限" in signal_df.columns and not signal_df.empty:
        max_single = min(max_single, _parse_percent_text(signal_df["单票上限"].iloc[0], max_single))

    total_target = min(max(total_target, 0.0), 1.0)
    max_single = min(max(max_single, 0.0), 1.0)

    risk_capital_base = float(args.risk_capital_base) if float(args.risk_capital_base) > 0 else max(100000.0, float(args.initial_capital))
    risk_cfg = PreTradeRiskConfig(
        enabled=not bool(args.disable_pretrade_risk),
        capital_base=risk_capital_base,
        max_industry_weight=min(max(float(args.risk_max_industry_weight), 0.05), 1.0),
        max_adv_participation=min(max(float(args.risk_max_adv_participation), 0.001), 0.50),
        min_price=max(0.0, float(args.risk_min_price)),
        max_style_size_exposure_abs=max(0.0, float(args.risk_max_style_size_exposure_abs)),
        max_style_beta_exposure_abs=max(0.0, float(args.risk_max_style_beta_exposure_abs)),
        max_style_momentum_exposure_abs=max(0.0, float(args.risk_max_style_momentum_exposure_abs)),
        max_style_vol_exposure_abs=max(0.0, float(args.risk_max_style_vol_exposure_abs)),
        style_lb_short=max(5, int(args.risk_style_lb_short)),
        style_lb_beta=max(10, int(args.risk_style_lb_beta)),
        max_names=int(effective_top_n),
        block_entry_not_tradable=True,
        blacklist_codes=_load_blacklist(args.risk_blacklist_file),
    )
    industry_map = load_industry_map(DATA_DIR)
    signal_df = _enrich_signal_amount_ma20(signal_df, bars_idx, signal_date, trade_date=trade_date)
    pretrade_state = _load_state(
        Path(args.state_file),
        initial_capital=max(100000.0, float(args.initial_capital)),
        reset_state=bool(args.reset_state),
    )
    pretrade_input = signal_df.drop(
        columns=[
            "target_weight",
            "target_weight_raw",
            "target_weight_source",
            "target_weight_checksum",
            "participation_pct",
            "impact_cost_bps",
            "unfilled_target_weight",
            "industry_weight_post",
            "constraint_reason",
        ],
        errors="ignore",
    )
    reserve_rounds = max(
        1,
        int(DEFAULTS.get("reserve_reoptimize_rounds", 2)) if bool(DEFAULTS.get("reserve_pool_enabled", False)) else 1,
    )
    risk_block_frames: list[pd.DataFrame] = []
    risk_stats: dict[str, object] = {}
    gated_signal_df = pd.DataFrame()
    working_pool = pretrade_input.copy()
    for round_idx in range(reserve_rounds):
        pre_kept_df, pre_block_df, pre_stats = apply_pretrade_risk_gates(
            signal_df=working_pool,
            bars_idx=bars_idx,
            trade_date=trade_date,
            total_target_pos=total_target,
            max_single_pos=max_single,
            cfg=risk_cfg,
            industry_map=industry_map,
            current_positions=pretrade_state.get("positions", {}) if isinstance(pretrade_state, dict) else {},
        )
        if not pre_block_df.empty:
            pre_block_df = pre_block_df.copy()
            pre_block_df["reserve_phase"] = "pre_optimizer"
            pre_block_df["reserve_round"] = int(round_idx + 1)
            risk_block_frames.append(pre_block_df)
        if pre_kept_df.empty:
            risk_stats = dict(pre_stats)
            gated_signal_df = pre_kept_df
            break

        optimized_df = _assign_profile_target_weights(
            signal_df=pre_kept_df,
            profile_cfg=DEFAULTS,
            total_target_pos=total_target,
            max_single_pos=max_single,
            industry_map=industry_map,
            primary_top_n=effective_top_n,
        )
        final_kept_df, final_block_df, final_stats = apply_pretrade_risk_gates(
            signal_df=optimized_df,
            bars_idx=bars_idx,
            trade_date=trade_date,
            total_target_pos=total_target,
            max_single_pos=max_single,
            cfg=risk_cfg,
            industry_map=industry_map,
            current_positions=pretrade_state.get("positions", {}) if isinstance(pretrade_state, dict) else {},
        )
        if not final_block_df.empty:
            final_block_df = final_block_df.copy()
            final_block_df["reserve_phase"] = "post_optimizer"
            final_block_df["reserve_round"] = int(round_idx + 1)
            risk_block_frames.append(final_block_df)
        gated_signal_df = final_kept_df
        risk_stats = dict(final_stats)
        risk_stats["pre_optimizer_blocked_count"] = int(pre_stats.get("blocked_count", 0))
        risk_stats["post_optimizer_blocked_count"] = int(final_stats.get("blocked_count", 0))
        risk_stats["reserve_rounds_used"] = int(round_idx + 1)
        risk_stats["reserve_candidate_pool_n"] = int(len(pretrade_input))
        risk_stats["reserve_enabled"] = int(bool(DEFAULTS.get("reserve_pool_enabled", False)))
        if final_block_df.empty:
            break
        blocked_codes = set(final_block_df.get("code", pd.Series(dtype=str)).astype(str).map(normalize_ts_code).tolist())
        working_pool = pre_kept_df[~pre_kept_df["代码"].astype(str).map(normalize_ts_code).isin(blocked_codes)].copy()
        if working_pool.empty:
            break

    risk_block_df = pd.concat(risk_block_frames, ignore_index=True) if risk_block_frames else pd.DataFrame()
    risk_stats.setdefault("reserve_candidate_pool_n", int(len(pretrade_input)))
    risk_stats.setdefault("reserve_enabled", int(bool(DEFAULTS.get("reserve_pool_enabled", False))))
    risk_stats.setdefault("reserve_rounds_used", 0)
    if not risk_block_df.empty and "reasons" in risk_block_df.columns:
        reason_s = risk_block_df["reasons"].astype(str)
        risk_stats["blocked_count"] = int(len(risk_block_df))
        risk_stats["blocked_rate_pct"] = float(len(risk_block_df) / max(len(pretrade_input), 1) * 100.0)
        risk_stats["industry_limits_hit"] = int(reason_s.str.contains("industry_weight").sum())
        risk_stats["post_trade_industry_limits_hit"] = int(reason_s.str.contains("post_trade_industry_clip").sum())
        risk_stats["unknown_industry_limits_hit"] = int(reason_s.str.contains("industry_weight_unknown").sum())
        risk_stats["adv_limits_hit"] = int(reason_s.str.contains("adv_participation").sum())
        risk_stats["entry_not_tradable_hit"] = int(reason_s.str.contains("entry_not_tradable").sum())
    _log(
        "风控门禁统计: "
        f"input={int(risk_stats.get('input_count', 0))}, "
        f"kept={int(risk_stats.get('kept_count', 0))}, "
        f"blocked={int(risk_stats.get('blocked_count', 0))}, "
        f"reserve_pool={int(risk_stats.get('reserve_candidate_pool_n', len(pretrade_input)))}, "
        f"reserve_rounds={int(risk_stats.get('reserve_rounds_used', 0))}, "
        f"industry_hit={int(risk_stats.get('industry_limits_hit', 0))}, "
        f"post_trade_industry_hit={int(risk_stats.get('post_trade_industry_limits_hit', 0))}, "
        f"missing_industry={int(risk_stats.get('missing_industry_count', 0))}, "
        f"unknown_industry_hit={int(risk_stats.get('unknown_industry_limits_hit', 0))}, "
        f"adv_hit={int(risk_stats.get('adv_limits_hit', 0))}, "
        f"entry_not_tradable_hit={int(risk_stats.get('entry_not_tradable_hit', 0))}, "
        f"style_hit={int(risk_stats.get('style_limits_hit', 0))}"
    )
    if gated_signal_df.empty:
        _log("风控硬门禁后无可交易标的，终止执行。")
        if not risk_block_df.empty:
            _log(f"被拦截标的数: {len(risk_block_df)}")
        return 1 if args.strict else 0

    broker_name = str(args.broker or "paper").strip().lower()
    channel = _sanitize_channel(args.channel, fallback=broker_name)
    try:
        broker = create_broker(
            broker_name,
            state_file=Path(args.state_file),
            initial_capital=max(100000.0, float(args.initial_capital)),
            lot_size=max(1, int(args.lot_size)),
            fee_bps=max(0.0, float(args.fee_bps)),
            slippage_bps=max(0.0, float(args.slippage_bps)),
            stamp_tax_bps=max(0.0, float(args.stamp_tax_bps)),
            blocked_state_enabled=bool(DEFAULTS.get("blocked_state_enabled", True)),
            block_buy_on_exit_blocked=bool(DEFAULTS.get("block_buy_on_exit_blocked", False)),
            blocked_exit_freeze_min_weight=max(0.0, float(DEFAULTS.get("blocked_exit_freeze_min_weight", 0.0))),
            live_mode=str(args.live_mode),
        )
    except ValueError as e:
        _log(str(e))
        return 1 if args.strict else 0

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    manifest_path = _build_p2_manifest(
        argv=sys.argv,
        signal_file=signal_file,
        state_file=str(args.state_file),
        recommendation_file=recommendation_file,
        broker_name=broker_name,
        live_mode=str(args.live_mode),
    )

    try:
        result = broker.rebalance(
            signal_df=gated_signal_df,
            signal_date=signal_date,
            trade_date=trade_date,
            bars_idx=bars_idx,
            run_id=run_id,
            top_n=effective_top_n,
            target_total_pos=total_target,
            max_single_pos=max_single,
            reset_state=bool(args.reset_state),
            dry_run=bool(args.dry_run),
        )
        orders_df = _attach_order_lifecycle(result.orders_df)
        fills_df = result.fills_df
        new_state = result.state
    except Exception:
        finalize_run_manifest(
            manifest_path,
            status="failed",
            step_results={"p2_rebalance": False},
            notes=["p2_rebalance_exception"],
        )
        raise

    exec_dir = OUTPUT_DIR / "execution"
    audit_dir = OUTPUT_DIR / "audit"
    exec_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    trade_date_str = pd.to_datetime(trade_date).strftime("%Y%m%d")
    orders_file = exec_dir / f"{channel}_orders_{trade_date_str}_{run_id}.csv"
    fills_file = exec_dir / f"{channel}_fills_{trade_date_str}_{run_id}.csv"
    run_file = exec_dir / f"{channel}_run_{trade_date_str}_{run_id}.json"
    risk_file = exec_dir / f"{channel}_risk_gates_{trade_date_str}_{run_id}.csv"
    ledger_file = exec_dir / f"{channel}_ledger.csv"
    audit_file = audit_dir / f"{channel}_audit_log.jsonl"

    _write_csv(orders_file, orders_df)
    _write_csv(fills_file, fills_df)
    run_file.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(risk_file, risk_block_df)

    ledger_row = dict(result.ledger_row)
    blocked_or_rejected = orders_df["status"].isin(["blocked", "rejected"]) if "status" in orders_df.columns else pd.Series(dtype=bool)
    reasons = orders_df.get("reason", pd.Series(dtype=object)).astype(str) if not orders_df.empty else pd.Series(dtype=str)
    sides = orders_df.get("side", pd.Series(dtype=object)).astype(str) if not orders_df.empty else pd.Series(dtype=str)
    weights = (
        pd.to_numeric(orders_df.get("target_weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        if not orders_df.empty
        else pd.Series(dtype=float)
    )
    entry_block = blocked_or_rejected & sides.eq("BUY") & reasons.eq("entry_not_tradable")
    exit_block = blocked_or_rejected & sides.eq("SELL") & reasons.eq("exit_not_tradable")
    ledger_row["dry_run"] = int(bool(args.dry_run))
    ledger_row["broker"] = broker_name
    ledger_row["channel"] = channel
    ledger_row["risk_input_count"] = int(risk_stats.get("input_count", 0))
    ledger_row["risk_kept_count"] = int(risk_stats.get("kept_count", 0))
    ledger_row["risk_blocked_count"] = int(risk_stats.get("blocked_count", 0))
    ledger_row["risk_blocked_rate_pct"] = float(risk_stats.get("blocked_rate_pct", 0.0))
    ledger_row["reserve_enabled"] = int(risk_stats.get("reserve_enabled", int(bool(DEFAULTS.get("reserve_pool_enabled", False)))))
    ledger_row["reserve_candidate_pool_n"] = int(risk_stats.get("reserve_candidate_pool_n", candidate_pool_n))
    ledger_row["reserve_rounds_used"] = int(risk_stats.get("reserve_rounds_used", 0))
    ledger_row["pre_optimizer_blocked_count"] = int(risk_stats.get("pre_optimizer_blocked_count", 0))
    ledger_row["post_optimizer_blocked_count"] = int(risk_stats.get("post_optimizer_blocked_count", 0))
    ledger_row["risk_industry_limits_hit"] = int(risk_stats.get("industry_limits_hit", 0))
    ledger_row["risk_post_trade_industry_limits_hit"] = int(risk_stats.get("post_trade_industry_limits_hit", 0))
    ledger_row["risk_missing_industry_count"] = int(risk_stats.get("missing_industry_count", 0))
    ledger_row["risk_unknown_industry_limits_hit"] = int(risk_stats.get("unknown_industry_limits_hit", 0))
    ledger_row["risk_adv_limits_hit"] = int(risk_stats.get("adv_limits_hit", 0))
    ledger_row["risk_style_limits_hit"] = int(risk_stats.get("style_limits_hit", 0))
    ledger_row["risk_style_size_limits_hit"] = int(risk_stats.get("style_size_limits_hit", 0))
    ledger_row["risk_style_beta_limits_hit"] = int(risk_stats.get("style_beta_limits_hit", 0))
    ledger_row["risk_style_momentum_limits_hit"] = int(risk_stats.get("style_momentum_limits_hit", 0))
    ledger_row["risk_style_vol_limits_hit"] = int(risk_stats.get("style_vol_limits_hit", 0))
    ledger_row["risk_entry_not_tradable_hit"] = int(risk_stats.get("entry_not_tradable_hit", 0))
    ledger_row["used_recommendation"] = int(bool(rec_info))
    ledger_row["recommend_rank"] = int(rec_info.get("recommend_rank", 0)) if rec_info else 0
    ledger_row["recommend_risk_tier"] = str(rec_info.get("risk_tier", "")) if rec_info else ""
    ledger_row["entry_not_tradable_orders"] = int(entry_block.sum()) if len(entry_block) else 0
    ledger_row["exit_not_tradable_orders"] = int(exit_block.sum()) if len(exit_block) else 0
    ledger_row["blocked_target_weight"] = float(weights.loc[blocked_or_rejected].sum()) if len(weights) else 0.0
    ledger_row["entry_not_tradable_target_weight"] = float(weights.loc[entry_block].sum()) if len(weights) else 0.0
    ledger_row["exit_not_tradable_target_weight"] = float(weights.loc[exit_block].sum()) if len(weights) else 0.0
    if ledger_file.exists():
        old = pd.read_csv(ledger_file)
        ledger_df = pd.concat([old, pd.DataFrame([ledger_row])], ignore_index=True)
    else:
        ledger_df = pd.DataFrame([ledger_row])
    _write_csv(ledger_file, ledger_df)

    if args.write_latest:
        _write_csv(exec_dir / f"{channel}_orders_latest.csv", orders_df)
        _write_csv(exec_dir / f"{channel}_fills_latest.csv", fills_df)
        _write_csv(exec_dir / f"{channel}_risk_gates_latest.csv", risk_block_df)
        (exec_dir / f"{channel}_run_latest.json").write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")

    event = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": f"{channel}_rebalance",
        "run_id": run_id,
        "broker": broker_name,
        "channel": channel,
        "live_mode": str(args.live_mode),
        "signal_file": str(signal_file),
        "signal_date": signal_date.strftime("%Y-%m-%d"),
        "trade_date": pd.to_datetime(trade_date).strftime("%Y-%m-%d"),
        "target_total_pos": float(total_target),
        "max_single_pos": float(max_single),
        "top_n": int(effective_top_n),
        "filled_orders": int(ledger_row["filled_orders"]),
        "partial_orders": int(ledger_row["partial_orders"]),
        "blocked_orders": int(ledger_row["blocked_orders"]),
        "rejected_orders": int(ledger_row["rejected_orders"]),
        "nav_post": float(ledger_row["nav_post"]),
        "risk_stats": risk_stats,
        "recommendation": None
        if not rec_info
        else {
            "rank": int(rec_info.get("recommend_rank", 0)),
            "risk_tier": str(rec_info.get("risk_tier", "")),
            "selection_mode": str(rec_info.get("selection_mode", "")),
            "objective_score": float(_safe_float(rec_info.get("objective_score", np.nan), np.nan)),
            "use_regime_position": bool(rec_info.get("use_regime_position", False)),
        },
        "dry_run": bool(args.dry_run),
        "orders_file": str(orders_file),
        "fills_file": str(fills_file),
        "run_file": str(run_file),
        "risk_file": str(risk_file),
        "platform_manifest": str(manifest_path),
    }
    _append_audit_event(audit_file, event)

    finalize_run_manifest(
        manifest_path,
        status="success",
        step_results={
            "p2_rebalance": True,
            "filled_orders": int(ledger_row["filled_orders"]),
            "blocked_orders": int(ledger_row["blocked_orders"]),
            "rejected_orders": int(ledger_row["rejected_orders"]),
            "nav_post": float(ledger_row["nav_post"]),
        },
        notes=[
            f"orders_file={orders_file}",
            f"fills_file={fills_file}",
            f"run_file={run_file}",
            f"ledger_file={ledger_file}",
        ],
    )

    _log("P2 OMS 执行完成:")
    _log(f"  - orders: {orders_file}")
    _log(f"  - fills:  {fills_file}")
    _log(f"  - risk:   {risk_file}")
    _log(f"  - run:    {run_file}")
    _log(f"  - ledger: {ledger_file}")
    _log(f"  - audit:  {audit_file}")
    _log(f"  - manifest: {manifest_path}")
    _log(
        "关键指标: "
        f"filled={ledger_row['filled_orders']}, "
        f"blocked={ledger_row['blocked_orders']}, "
        f"risk_blocked={ledger_row['risk_blocked_count']}, "
        f"nav={ledger_row['nav_post']:.2f}, "
        f"cash={ledger_row['cash_post']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
