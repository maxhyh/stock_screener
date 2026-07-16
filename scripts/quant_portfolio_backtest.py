#!/usr/bin/env python3
"""
量化组合交易回测（基于 daily_YYYYMMDD 推荐文件）

目标：
1. 把“每日选股”转成“可执行的组合交易”
2. 支持交易成本、仓位约束、市场状态仓位建议
3. 产出组合层面的净值曲线与关键绩效指标

示例：
    python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20
    python scripts/quant_portfolio_backtest.py --top-n 10 --holding-days 3 --exclude-st
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.platform import (
    PortfolioConstraints,
    build_config_fingerprint,
    build_portfolio_decision,
    build_run_manifest,
    finalize_run_manifest,
    load_security_config,
    write_run_manifest,
)
from core.data.market_data_gateway import AShareMarketDataGateway, load_execution_bars
from core.risk.pretrade import load_industry_map as load_ods_industry_map
from utils.code_utils import normalize_ts_code, normalize_ts_code_series, limit_ratio_for_stock
from utils.market_data_units import normalize_amount_volume_units
from utils.metadata_guard import evaluate_metadata_guard, load_ods_metadata_health
from utils.output_paths import ensure_output_dirs, write_dual_csv
from utils.execution_overlay import add_execution_overlay_scores
from utils.signal_refactor import add_feature_refactor_columns
from utils.signal_quality import add_signal_quality_columns

OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PROFILE_FILE = os.path.join(BASE_DIR, "config", "quant_live_profiles.json")
UNKNOWN_INDUSTRY_LABEL = "未知"


def _load_default_backtest_defaults() -> dict[str, object]:
    """从量化档位配置加载 CLI 默认参数，避免文档/代码漂移。"""
    defaults: dict[str, object] = {
        "top_n": 10,
        "holding_days": 3,
        "max_single_pos": 0.06,
        "use_regime_position": False,
        "fallback_total_position": 0.60,
        "exclude_st": True,
        "exclude_bj9": True,
        "min_valid_positions": 3,
        "engine_mode": "hybrid",
        "benchmark_mode": "hs300",
        "max_industry_positions": 3,
        "corr_lookback_days": 60,
        "max_pair_corr": 0.85,
        "corr_min_obs": 15,
        "take_profit": 0.18,
        "stop_loss": 0.08,
        "trail_drawdown": 0.10,
        "tp_normal": 0.18,
        "tp_choppy": 0.14,
        "tp_panic": 0.10,
        "sl_normal": 0.08,
        "sl_choppy": 0.06,
        "sl_panic": 0.05,
        "trail_normal": 0.10,
        "trail_choppy": 0.08,
        "trail_panic": 0.06,
        "corr_normal": 0.85,
        "corr_choppy": 0.75,
        "corr_panic": 0.65,
        "risk_window": 5,
        "risk_cut_win_rate": 0.35,
        "risk_cut_avg_ret": -0.005,
        "risk_cut_factor": 0.60,
        "min_signal_quality": 0.40,
        "ml_quality_blend": 0.80,
        "max_abs_pct_chg": 8.5,
        "stability_blend": 0.30,
        "min_refactor_score": 0.50,
        "min_price": 0.0,
        "min_amount_ma20": 0.0,
        "liquidity_blend": 0.0,
        "adv_penalty_blend": 0.0,
        "industry_crowding_blend": 0.0,
        "optimizer_mode": "score_weight",
        "target_capital_base": 1_000_000.0,
        "target_max_industry_weight": 0.0,
        "target_max_adv_participation": 0.0,
        "target_capacity_amount_col": "amount_ma20",
        "target_capacity_amount_buffer": 1.0,
        "redistribute_clipped_weight": False,
        "impact_model": "sqrt",
        "impact_base_bps": 0.0,
        "impact_participation_bps": 0.0,
        "impact_power": 0.5,
        "promotion_loss_clamp_enabled": False,
    }
    try:
        if not os.path.exists(PROFILE_FILE):
            return defaults
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        profile_name = str(cfg.get("default_profile", "balanced"))
        profiles = cfg.get("profiles", {})
        p = profiles.get(profile_name, {})
        if not isinstance(p, dict):
            return defaults
        defaults.update(
            {
                "top_n": int(p.get("top_n", defaults["top_n"])),
                "holding_days": int(p.get("holding_days", defaults["holding_days"])),
                "max_single_pos": float(p.get("max_single_pos", defaults["max_single_pos"])),
                "use_regime_position": bool(p.get("use_regime_position", defaults["use_regime_position"])),
                "fallback_total_position": float(p.get("fallback_total_position", defaults["fallback_total_position"])),
                "exclude_st": bool(p.get("exclude_st", defaults["exclude_st"])),
                "exclude_bj9": bool(p.get("exclude_bj9", defaults["exclude_bj9"])),
                "min_valid_positions": int(p.get("min_valid_positions", defaults["min_valid_positions"])),
                "engine_mode": str(p.get("engine_mode", defaults["engine_mode"])),
                "benchmark_mode": str(p.get("benchmark_mode", defaults["benchmark_mode"])),
                "max_industry_positions": int(p.get("max_industry_positions", defaults["max_industry_positions"])),
                "corr_lookback_days": int(p.get("corr_lookback_days", defaults["corr_lookback_days"])),
                "max_pair_corr": float(p.get("max_pair_corr", defaults["max_pair_corr"])),
                "corr_min_obs": int(p.get("corr_min_obs", defaults["corr_min_obs"])),
                "take_profit": float(p.get("take_profit", defaults["take_profit"])),
                "stop_loss": float(p.get("stop_loss", defaults["stop_loss"])),
                "trail_drawdown": float(p.get("trail_drawdown", defaults["trail_drawdown"])),
                "tp_normal": float(p.get("tp_normal", defaults["tp_normal"])),
                "tp_choppy": float(p.get("tp_choppy", defaults["tp_choppy"])),
                "tp_panic": float(p.get("tp_panic", defaults["tp_panic"])),
                "sl_normal": float(p.get("sl_normal", defaults["sl_normal"])),
                "sl_choppy": float(p.get("sl_choppy", defaults["sl_choppy"])),
                "sl_panic": float(p.get("sl_panic", defaults["sl_panic"])),
                "trail_normal": float(p.get("trail_normal", defaults["trail_normal"])),
                "trail_choppy": float(p.get("trail_choppy", defaults["trail_choppy"])),
                "trail_panic": float(p.get("trail_panic", defaults["trail_panic"])),
                "corr_normal": float(p.get("corr_normal", defaults["corr_normal"])),
                "corr_choppy": float(p.get("corr_choppy", defaults["corr_choppy"])),
                "corr_panic": float(p.get("corr_panic", defaults["corr_panic"])),
                "risk_window": int(p.get("risk_window", defaults["risk_window"])),
                "risk_cut_win_rate": float(p.get("risk_cut_win_rate", defaults["risk_cut_win_rate"])),
                "risk_cut_avg_ret": float(p.get("risk_cut_avg_ret", defaults["risk_cut_avg_ret"])),
                "risk_cut_factor": float(p.get("risk_cut_factor", defaults["risk_cut_factor"])),
                "min_signal_quality": float(p.get("min_signal_quality", defaults["min_signal_quality"])),
                "ml_quality_blend": float(p.get("ml_quality_blend", defaults["ml_quality_blend"])),
                "max_abs_pct_chg": float(p.get("max_abs_pct_chg", defaults["max_abs_pct_chg"])),
                "stability_blend": float(p.get("stability_blend", defaults["stability_blend"])),
                "min_refactor_score": float(p.get("min_refactor_score", defaults["min_refactor_score"])),
                "min_price": float(p.get("min_price", defaults["min_price"])),
                "min_amount_ma20": float(p.get("min_amount_ma20", defaults["min_amount_ma20"])),
                "liquidity_blend": float(p.get("liquidity_blend", defaults["liquidity_blend"])),
                "adv_penalty_blend": float(p.get("adv_penalty_blend", defaults["adv_penalty_blend"])),
                "industry_crowding_blend": float(p.get("industry_crowding_blend", defaults["industry_crowding_blend"])),
                "optimizer_mode": str(p.get("optimizer_mode", defaults["optimizer_mode"])),
                "target_capital_base": float(p.get("target_capital_base", defaults["target_capital_base"])),
                "target_max_industry_weight": float(
                    p.get("target_max_industry_weight", p.get("risk_max_industry_weight", defaults["target_max_industry_weight"]))
                ),
                "target_max_adv_participation": float(
                    p.get("target_max_adv_participation", p.get("risk_max_adv_participation", defaults["target_max_adv_participation"]))
                ),
                "target_capacity_amount_col": str(
                    p.get("target_capacity_amount_col", defaults["target_capacity_amount_col"]) or defaults["target_capacity_amount_col"]
                ),
                "target_capacity_amount_buffer": float(
                    p.get("target_capacity_amount_buffer", defaults["target_capacity_amount_buffer"])
                ),
                "redistribute_clipped_weight": bool(
                    p.get("redistribute_clipped_weight", defaults["redistribute_clipped_weight"])
                ),
                "impact_model": str(p.get("impact_model", defaults["impact_model"])),
                "impact_base_bps": float(p.get("impact_base_bps", defaults["impact_base_bps"])),
                "impact_participation_bps": float(p.get("impact_participation_bps", defaults["impact_participation_bps"])),
                "impact_power": float(p.get("impact_power", defaults["impact_power"])),
                "promotion_loss_clamp_enabled": bool(
                    p.get("promotion_loss_clamp_enabled", defaults["promotion_loss_clamp_enabled"])
                ),
            }
        )
    except Exception:
        return defaults
    return defaults


DEFAULTS = _load_default_backtest_defaults()


@dataclass
class BacktestConfig:
    start: str | None
    end: str | None
    top_n: int = int(DEFAULTS["top_n"])
    holding_days: int = int(DEFAULTS["holding_days"])
    fee_bps: float = 8.0
    slippage_bps: float = 5.0
    stamp_duty_bps: float = 5.0  # [Audit Fix P0-2] A股印花税 0.05% 卖出单边
    max_single_pos: float = float(DEFAULTS["max_single_pos"])
    use_regime_position: bool = bool(DEFAULTS["use_regime_position"])
    fallback_total_position: float = float(DEFAULTS["fallback_total_position"])
    exclude_st: bool = bool(DEFAULTS["exclude_st"])
    min_valid_positions: int = int(DEFAULTS["min_valid_positions"])
    max_loss_per_trade: float | None = None
    loss_clamp_enabled: bool = bool(DEFAULTS["promotion_loss_clamp_enabled"])
    engine_mode: str = str(DEFAULTS["engine_mode"])  # left/right/hybrid
    benchmark_mode: str = str(DEFAULTS["benchmark_mode"])  # hs300/synthetic/none
    benchmark_file: str | None = None
    exclude_bj9: bool = bool(DEFAULTS["exclude_bj9"])
    enable_diversification: bool = True
    max_industry_positions: int = int(DEFAULTS["max_industry_positions"])
    corr_lookback_days: int = int(DEFAULTS["corr_lookback_days"])
    max_pair_corr: float = float(DEFAULTS["max_pair_corr"])
    corr_min_obs: int = int(DEFAULTS["corr_min_obs"])
    enable_dynamic_exit: bool = True
    take_profit: float = float(DEFAULTS["take_profit"])
    stop_loss: float = float(DEFAULTS["stop_loss"])
    trail_drawdown: float = float(DEFAULTS["trail_drawdown"])
    enable_regime_risk_params: bool = True
    tp_normal: float = float(DEFAULTS["tp_normal"])
    tp_choppy: float = float(DEFAULTS["tp_choppy"])
    tp_panic: float = float(DEFAULTS["tp_panic"])
    sl_normal: float = float(DEFAULTS["sl_normal"])
    sl_choppy: float = float(DEFAULTS["sl_choppy"])
    sl_panic: float = float(DEFAULTS["sl_panic"])
    trail_normal: float = float(DEFAULTS["trail_normal"])
    trail_choppy: float = float(DEFAULTS["trail_choppy"])
    trail_panic: float = float(DEFAULTS["trail_panic"])
    corr_normal: float = float(DEFAULTS["corr_normal"])
    corr_choppy: float = float(DEFAULTS["corr_choppy"])
    corr_panic: float = float(DEFAULTS["corr_panic"])
    enable_risk_switch: bool = True
    risk_window: int = int(DEFAULTS["risk_window"])
    risk_cut_win_rate: float = float(DEFAULTS["risk_cut_win_rate"])
    risk_cut_avg_ret: float = float(DEFAULTS["risk_cut_avg_ret"])
    risk_cut_factor: float = float(DEFAULTS["risk_cut_factor"])
    enable_exec_constraints: bool = True
    max_exit_delay_days: int = 5
    enable_signal_quality_gate: bool = True
    min_signal_quality: float = float(DEFAULTS["min_signal_quality"])
    ml_quality_blend: float = float(DEFAULTS["ml_quality_blend"])
    max_abs_pct_chg: float = float(DEFAULTS["max_abs_pct_chg"])
    enable_feature_refactor: bool = True
    stability_blend: float = float(DEFAULTS["stability_blend"])
    enable_feature_refactor_gate: bool = True
    min_refactor_score: float = float(DEFAULTS["min_refactor_score"])
    min_price: float = float(DEFAULTS["min_price"])
    min_amount_ma20: float = float(DEFAULTS["min_amount_ma20"])
    liquidity_blend: float = float(DEFAULTS["liquidity_blend"])
    adv_penalty_blend: float = float(DEFAULTS["adv_penalty_blend"])
    industry_crowding_blend: float = float(DEFAULTS["industry_crowding_blend"])
    optimizer_mode: str = str(DEFAULTS["optimizer_mode"])
    target_capital_base: float = float(DEFAULTS["target_capital_base"])
    target_max_industry_weight: float = float(DEFAULTS["target_max_industry_weight"])
    target_max_adv_participation: float = float(DEFAULTS["target_max_adv_participation"])
    target_capacity_amount_col: str = str(DEFAULTS["target_capacity_amount_col"])
    target_capacity_amount_buffer: float = float(DEFAULTS["target_capacity_amount_buffer"])
    redistribute_clipped_weight: bool = bool(DEFAULTS["redistribute_clipped_weight"])
    impact_model: str = str(DEFAULTS["impact_model"])
    impact_base_bps: float = float(DEFAULTS["impact_base_bps"])
    impact_participation_bps: float = float(DEFAULTS["impact_participation_bps"])
    impact_power: float = float(DEFAULTS["impact_power"])
    verbose: bool = True


def _norm_code(code: object) -> str:
    return normalize_ts_code(code)


def _is_excluded_code(code: object) -> bool:
    """统一实盘排除规则。当前：排除北交所 9 开头代码。"""
    c = _norm_code(code)
    return c.startswith("9")


def _regime_key(state: str) -> str:
    s = str(state or "").strip()
    if s == "恐慌":
        return "panic"
    if s == "震荡":
        return "choppy"
    return "normal"


def _regime_risk_params(cfg: BacktestConfig, market_state: str) -> tuple[float, float, float, float]:
    if not cfg.enable_regime_risk_params:
        return cfg.take_profit, cfg.stop_loss, cfg.trail_drawdown, cfg.max_pair_corr
    key = _regime_key(market_state)
    if key == "panic":
        return cfg.tp_panic, cfg.sl_panic, cfg.trail_panic, cfg.corr_panic
    if key == "choppy":
        return cfg.tp_choppy, cfg.sl_choppy, cfg.trail_choppy, cfg.corr_choppy
    return cfg.tp_normal, cfg.sl_normal, cfg.trail_normal, cfg.corr_normal


def _compute_risk_switch_factor(cfg: BacktestConfig, trades: list[dict[str, object]]) -> float:
    """基于近期组合表现做平滑降仓，避免短窗口噪声触发二元急刹车。"""
    window = max(1, int(cfg.risk_window))
    if (not cfg.enable_risk_switch) or len(trades) < window:
        return 1.0

    recent = np.asarray([float(x.get("portfolio_ret", 0.0)) for x in trades[-window:]], dtype=float)
    if recent.size == 0:
        return 1.0

    recent_win = float(np.mean(recent > 0))
    recent_avg = float(np.mean(recent))
    win_gap = 0.0
    avg_gap = 0.0
    if recent_win < float(cfg.risk_cut_win_rate):
        win_gap = min(1.0, (float(cfg.risk_cut_win_rate) - recent_win) / max(float(cfg.risk_cut_win_rate), 1e-6))
    if recent_avg < float(cfg.risk_cut_avg_ret):
        avg_gap = min(1.0, (float(cfg.risk_cut_avg_ret) - recent_avg) / max(abs(float(cfg.risk_cut_avg_ret)), 1e-4))

    stress = max(win_gap, avg_gap)
    floor = min(max(float(cfg.risk_cut_factor), 0.0), 1.0)
    return float(1.0 - stress * (1.0 - floor))


def _load_industry_map(asof_date: object | None = None) -> dict[str, str]:
    """Load the backtest industry map from ODS metadata as of each evidence window."""
    return load_ods_industry_map(asof_date=asof_date)


def _parse_percent_text(text: str | float | int | None, fallback: float) -> float:
    if text is None:
        return fallback
    s = str(text).strip()
    if not s:
        return fallback
    m = re.findall(r"(\d+(?:\.\d+)?)\s*%", s)
    if not m:
        try:
            v = float(s)
            if v > 1:
                return v / 100.0
            return v
        except Exception:
            return fallback
    vals = [float(x) for x in m]
    if len(vals) >= 2:
        return float(np.mean(vals)) / 100.0
    return vals[0] / 100.0


def _load_daily_recommendations(output_dir: str, exclude_bj9: bool = True) -> dict[pd.Timestamp, pd.DataFrame]:
    daily_files = []
    daily_files.extend(glob.glob(os.path.join(output_dir, "daily", "daily_*.csv")))
    daily_files.extend(glob.glob(os.path.join(output_dir, "daily_*.csv")))
    daily_files = sorted(set(daily_files))

    rec_map: dict[pd.Timestamp, pd.DataFrame] = {}
    for path in daily_files:
        m = re.search(r"daily_(\d{8})\.csv$", os.path.basename(path))
        if not m:
            continue
        date_str = m.group(1)
        dt = pd.to_datetime(date_str, format="%Y%m%d", errors="coerce")
        if pd.isna(dt):
            continue
        try:
            df = pd.read_csv(path, dtype={"代码": str})
        except Exception:
            continue
        if df.empty or "代码" not in df.columns:
            continue
        df = df.copy()
        df["代码"] = normalize_ts_code_series(df["代码"])
        df = df[df["代码"] != ""].copy()
        if exclude_bj9:
            df = df[~df["代码"].apply(_is_excluded_code)].copy()
        if "排名" in df.columns:
            df = df.sort_values("排名")
        if df.empty:
            continue
        rec_map[dt.normalize()] = df
    return rec_map


def _load_market_open_prices(
    start: object,
    end: object,
    *,
    holding_days: int,
    include_bj9: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    加载回测需要的市场 bar，并构建 MultiIndex 快速查询视图。

    返回:
    - market_df: 明细 DataFrame（供相关性/基准使用）
    - bars_idx: 以 (trade_date, code) 为索引的 DataFrame（供执行可达性判断）
    """
    market, bars_idx, lineage = load_execution_bars(
        start,
        end,
        lookback_sessions=60,
        forward_sessions=max(1, int(holding_days)),
        include_bj9=bool(include_bj9),
    )
    market.attrs["market_data_lineage"] = lineage
    return market, bars_idx


def _safe_num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series([default] * len(df), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def _positive_min(values: list[float]) -> float:
    vals = []
    for x in values:
        try:
            v = float(x)
            if pd.notna(v) and np.isfinite(v) and v > 0:
                vals.append(float(v))
        except Exception:
            continue
    return float(min(vals)) if vals else 0.0


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


def _is_suspended_bar(row: pd.Series | None) -> bool:
    if row is None:
        return True
    op = float(row.get("open", np.nan))
    vol = float(row.get("vol", np.nan))
    amt = float(row.get("amount", np.nan))
    if (not np.isfinite(op)) or (op <= 0):
        return True
    return not ((np.isfinite(amt) and amt > 0) or (np.isfinite(vol) and vol > 0))


def _is_locked_limit_up(row: pd.Series | None, limit_ratio: float) -> bool:
    if row is None:
        return False
    prev_close = float(row.get("prev_close", np.nan))
    op = float(row.get("open", np.nan))
    hi = float(row.get("high", np.nan))
    lo = float(row.get("low", np.nan))
    if (not np.isfinite(prev_close)) or prev_close <= 0:
        return False
    if not (np.isfinite(op) and np.isfinite(hi) and np.isfinite(lo)):
        return False
    limit_up = prev_close * (1.0 + abs(limit_ratio))
    return (op >= limit_up * 0.999) and (lo >= limit_up * 0.999) and (hi >= limit_up * 0.999)


def _is_locked_limit_down(row: pd.Series | None, limit_ratio: float) -> bool:
    if row is None:
        return False
    prev_close = float(row.get("prev_close", np.nan))
    op = float(row.get("open", np.nan))
    hi = float(row.get("high", np.nan))
    lo = float(row.get("low", np.nan))
    if (not np.isfinite(prev_close)) or prev_close <= 0:
        return False
    if not (np.isfinite(op) and np.isfinite(hi) and np.isfinite(lo)):
        return False
    limit_down = prev_close * (1.0 - abs(limit_ratio))
    return (op <= limit_down * 1.001) and (hi <= limit_down * 1.001) and (lo <= limit_down * 1.001)


def _can_enter_long(row: pd.Series | None, code: str, name: str) -> bool:
    if _is_suspended_bar(row):
        return False
    ratio = limit_ratio_for_stock(code, name)
    if _is_locked_limit_up(row, ratio):
        return False
    return True


def _can_exit_long(row: pd.Series | None, code: str, name: str) -> bool:
    if _is_suspended_bar(row):
        return False
    ratio = limit_ratio_for_stock(code, name)
    if _is_locked_limit_down(row, ratio):
        return False
    return True


def _align_exit_idx_with_exec_constraints(
    bars_idx: pd.DataFrame,
    trading_days: list[pd.Timestamp],
    base_exit_idx: int,
    held: list[tuple[str, str]],
    cfg: BacktestConfig,
) -> int | None:
    if not held:
        return None
    idx = base_exit_idx
    max_idx = min(len(trading_days) - 1, base_exit_idx + max(0, int(cfg.max_exit_delay_days)))
    while idx <= max_idx:
        dt = trading_days[idx]
        blocked = False
        for code, name in held:
            row = _get_bar_row(bars_idx, dt, code)
            if not _can_exit_long(row, code, name):
                blocked = True
                break
        if not blocked:
            return idx
        idx += 1
    return None


def _resolve_benchmark_file(explicit_file: str | None) -> str | None:
    candidates = []
    if explicit_file:
        candidates.append(explicit_file)
    candidates.extend(
        [
            os.path.join(OUTPUT_DIR, "backtest", "hs300_daily.csv"),
        ]
    )
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


def _build_synthetic_benchmark(market_df: pd.DataFrame) -> pd.DataFrame:
    """基于全市场开盘价构建“广谱市场”基准（中位数日收益）。"""
    mdf = market_df[["trade_date", "code", "open"]].copy()
    mdf = mdf.sort_values(["code", "trade_date"])
    mdf["ret"] = mdf.groupby("code")["open"].pct_change()
    daily = (
        mdf.dropna(subset=["ret"])
        .groupby("trade_date", as_index=False)["ret"]
        .median()
        .sort_values("trade_date")
    )
    if daily.empty:
        return pd.DataFrame(columns=["trade_date", "level"])
    daily["level"] = (1.0 + daily["ret"]).cumprod()
    return daily[["trade_date", "level"]]


def _load_benchmark_levels(cfg: BacktestConfig, market_df: pd.DataFrame) -> tuple[dict[pd.Timestamp, float], str]:
    """返回 benchmark 开盘级别映射（date->level）。"""
    if cfg.benchmark_mode == "none":
        return {}, "none"

    if cfg.benchmark_mode == "hs300":
        bench_file = _resolve_benchmark_file(cfg.benchmark_file)
        if bench_file:
            bdf = pd.read_csv(bench_file)
            col_map = {str(c).strip().lower(): c for c in bdf.columns}
            date_col = col_map.get("date") or col_map.get("trade_date") or col_map.get("日期")
            level_col = col_map.get("open") or col_map.get("close") or col_map.get("收盘") or col_map.get("level")
            if date_col and level_col:
                bdf["trade_date"] = pd.to_datetime(bdf[date_col], errors="coerce").dt.normalize()
                bdf["level"] = pd.to_numeric(bdf[level_col], errors="coerce")
                bdf = bdf.dropna(subset=["trade_date", "level"]).sort_values("trade_date")
                if not bdf.empty:
                    return {(d): float(v) for d, v in bdf[["trade_date", "level"]].itertuples(index=False, name=None)}, "hs300_file"

    syn = _build_synthetic_benchmark(market_df)
    return {(d): float(v) for d, v in syn[["trade_date", "level"]].itertuples(index=False, name=None)}, "synthetic"


def _pick_by_engine(
    day_df: pd.DataFrame,
    top_n: int,
    engine_mode: str,
    market_state: str,
    cfg: BacktestConfig,
    industry_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    df = day_df.copy()
    df["ml"] = _safe_num(df, "ML评分", 0.0)
    df["close_px"] = _safe_num(df, "收盘价", _safe_num(df, "close", 0.0))
    df["bias"] = _safe_num(df, "BIAS-20", 0.0)
    if "Z-Score" in df.columns:
        df["z_score"] = _safe_num(df, "Z-Score", 0.0)
    else:
        df["z_score"] = _safe_num(df, "z_score", 0.0)
    df["rsi"] = _safe_num(df, "RSI", 50.0)
    df["chg"] = _safe_num(df, "涨跌幅%", 0.0)
    if "量比" in df.columns:
        df["vol_ratio"] = _safe_num(df, "量比", 1.0)
    else:
        df["vol_ratio"] = _safe_num(df, "vol_ratio", 1.0)
    if "排名" in df.columns:
        df["rank_num"] = pd.to_numeric(df["排名"], errors="coerce")
    else:
        df["rank_num"] = np.nan
    if "成交额MA20" in df.columns:
        df["amount_ma20"] = _safe_num(df, "成交额MA20", 0.0)
    else:
        df["amount_ma20"] = _safe_num(df, "amount_ma20", 0.0)
    if "流动性分" in df.columns:
        df["liquidity_score"] = _safe_num(df, "流动性分", 0.0)
    else:
        amt_rank = np.log1p(df["amount_ma20"].clip(lower=0.0)).rank(method="average", pct=True)
        px_rank = df["close_px"].clip(lower=0.0).rank(method="average", pct=True)
        df["liquidity_score"] = (0.80 * amt_rank + 0.20 * px_rank).fillna(0.0)

    df = add_signal_quality_columns(
        df,
        bias_col="bias",
        z_col="z_score",
        rsi_col="rsi",
        vol_ratio_col="vol_ratio",
        pct_chg_col="chg",
        max_abs_pct_chg=max(1.0, float(cfg.max_abs_pct_chg)),
        quality_col="signal_quality",
        score_col="hybrid_score",
        ml_col="ml",
        ml_weight=float(cfg.ml_quality_blend),
    )
    if cfg.enable_feature_refactor:
        df = add_feature_refactor_columns(
            df,
            bias_col="bias",
            z_col="z_score",
            rsi_col="rsi",
            vol_ratio_col="vol_ratio",
            pct_chg_col="chg",
            base_score_col="hybrid_score",
            stability_col="stability_score",
            refactor_col="refactor_score",
            redundancy_col="feature_redundancy",
            blend=float(cfg.stability_blend),
            max_abs_pct_chg=max(1.0, float(cfg.max_abs_pct_chg)),
        )
        ranking_col = "refactor_score"
    else:
        df["stability_score"] = df["signal_quality"]
        df["refactor_score"] = df["hybrid_score"]
        df["feature_redundancy"] = 0.0
        ranking_col = "hybrid_score"

    eff_industry_map = dict(industry_map or {})
    df["industry"] = df["代码"].map(eff_industry_map).fillna("").astype(str).str.strip()
    df["industry"] = df["industry"].replace({"nan": "", "None": ""})
    liquidity_blend = min(max(float(cfg.liquidity_blend), 0.0), 0.5)
    adv_penalty_blend = min(max(float(cfg.adv_penalty_blend), 0.0), 0.5)
    industry_crowding_blend = min(max(float(cfg.industry_crowding_blend), 0.0), 0.5)
    df = add_execution_overlay_scores(
        df,
        base_score_col=ranking_col,
        price_col="close_px",
        amount_col="amount_ma20",
        industry_col="industry",
        liquidity_blend=liquidity_blend,
        adv_penalty_blend=adv_penalty_blend,
        industry_crowding_blend=industry_crowding_blend,
    )
    if liquidity_blend > 0 or adv_penalty_blend > 0 or industry_crowding_blend > 0:
        ranking_col = "execution_score"

    if cfg.enable_signal_quality_gate:
        gate_floor = float(cfg.min_signal_quality)
        if str(market_state) == "恐慌":
            gate_floor = min(0.80, gate_floor + 0.10)
        elif str(market_state) == "震荡":
            gate_floor = min(0.80, gate_floor + 0.05)
        gated = df[df["signal_quality"] >= gate_floor].copy()
        if len(gated) >= max(3, min(top_n, 5)):
            df = gated
    if cfg.enable_feature_refactor and cfg.enable_feature_refactor_gate:
        ref_gate = float(cfg.min_refactor_score)
        if str(market_state) == "恐慌":
            ref_gate = min(0.90, ref_gate + 0.05)
        gated_ref = df[df["refactor_score"] >= ref_gate].copy()
        if len(gated_ref) >= max(3, min(top_n, 5)):
            df = gated_ref
    if float(cfg.min_price) > 0.0 or float(cfg.min_amount_ma20) > 0.0:
        liq_mask = pd.Series(True, index=df.index)
        if float(cfg.min_price) > 0.0:
            liq_mask &= df["close_px"] >= float(cfg.min_price)
        if float(cfg.min_amount_ma20) > 0.0:
            liq_mask &= df["amount_ma20"] >= float(cfg.min_amount_ma20)
        liquid_df = df[liq_mask].copy()
        if len(liquid_df) >= max(3, min(top_n, 5)):
            df = liquid_df

    left_pool = df[(df["bias"] <= 5) & (df["rsi"] <= 65) & (df["chg"] <= 7)].copy()
    left_pool = left_pool.sort_values([ranking_col, "hybrid_score", "ml", "bias", "rsi"], ascending=[False, False, False, True, True])

    right_pool = df[(df["bias"] >= -2) & (df["rsi"].between(50, 88)) & (df["chg"] > -6) & (df["chg"] < 9.8)].copy()
    right_pool = right_pool.sort_values([ranking_col, "hybrid_score", "ml", "bias", "rsi"], ascending=[False, False, False, False, False])

    mode = engine_mode
    if engine_mode == "hybrid":
        mode = "left" if market_state == "恐慌" else ("right" if market_state == "正常" else "hybrid_mid")

    if mode == "left":
        picks = left_pool.head(top_n)
        return picks if not picks.empty else df.sort_values([ranking_col, "hybrid_score", "ml"], ascending=[False, False, False]).head(top_n)
    if mode == "right":
        picks = right_pool.head(top_n)
        return picks if not picks.empty else df.sort_values([ranking_col, "hybrid_score", "ml"], ascending=[False, False, False]).head(top_n)

    # hybrid_mid: 震荡市左右结合
    left_n = max(1, int(round(top_n * 0.4)))
    right_n = max(1, top_n - left_n)
    a = left_pool.head(left_n)
    b = right_pool.head(right_n)
    picks = pd.concat([a, b], axis=0).drop_duplicates(subset=["代码"], keep="first")
    if len(picks) < top_n:
        fill = df[~df["代码"].isin(picks["代码"])].sort_values([ranking_col, "hybrid_score", "ml"], ascending=[False, False, False]).head(top_n - len(picks))
        picks = pd.concat([picks, fill], axis=0)
    return picks.head(top_n)


def _apply_diversification_filters(
    picks: pd.DataFrame,
    market_df: pd.DataFrame,
    trading_days: list[pd.Timestamp],
    entry_idx: int,
    cfg: BacktestConfig,
    industry_map: dict[str, str],
    max_pair_corr: float | None = None,
) -> pd.DataFrame:
    if picks.empty or not cfg.enable_diversification:
        return picks.head(cfg.top_n)

    work = picks.copy()
    work["代码"] = work["代码"].astype(str).apply(_norm_code)
    work["industry"] = work["代码"].map(industry_map).fillna("").astype(str).str.strip()
    work["industry"] = work["industry"].replace({"nan": "", "None": ""})
    work["industry_missing"] = (work["industry"] == "").astype(int)
    work.loc[work["industry_missing"] == 1, "industry"] = UNKNOWN_INDUSTRY_LABEL
    score_col = "refactor_score" if "refactor_score" in work.columns else ("hybrid_score" if "hybrid_score" in work.columns else "ml")
    work = work.sort_values([score_col, "hybrid_score", "ml"], ascending=[False, False, False]).reset_index(drop=True)

    # 准备相关性窗口
    pivot = None
    corr_cap = float(max_pair_corr if max_pair_corr is not None else cfg.max_pair_corr)
    if corr_cap < 0.999 and cfg.corr_lookback_days > 1 and entry_idx > 2:
        sidx = max(0, entry_idx - cfg.corr_lookback_days)
        window_dates = trading_days[sidx:entry_idx]
        if len(window_dates) >= 5:
            sub = market_df[
                market_df["trade_date"].isin(window_dates)
                & market_df["code"].isin(work["代码"].tolist())
            ][["trade_date", "code", "open"]].copy()
            if not sub.empty:
                pivot = (
                    sub.pivot(index="trade_date", columns="code", values="open")
                    .sort_index()
                    .pct_change(fill_method=None)
                )

    kept_rows = []
    kept_codes: list[str] = []
    ind_cnt: dict[str, int] = {}

    for _, row in work.iterrows():
        code = row["代码"]
        ind = str(row.get("industry", "") or "")

        # 行业集中度限制
        if cfg.max_industry_positions > 0:
            if ind_cnt.get(ind, 0) >= cfg.max_industry_positions:
                continue

        # 与已选持仓相关性去重
        if pivot is not None and kept_codes and code in pivot.columns:
            too_correlated = False
            for kc in kept_codes:
                if kc not in pivot.columns:
                    continue
                pair = pivot[[code, kc]].dropna()
                if len(pair) < max(2, cfg.corr_min_obs):
                    continue
                corr = float(pair[code].corr(pair[kc]))
                if np.isfinite(corr) and corr > corr_cap:
                    too_correlated = True
                    break
            if too_correlated:
                continue

        kept_rows.append(row)
        kept_codes.append(code)
        ind_cnt[ind] = ind_cnt.get(ind, 0) + 1
        if len(kept_rows) >= cfg.top_n:
            break

    if not kept_rows:
        return work.head(cfg.top_n)
    return pd.DataFrame(kept_rows).head(cfg.top_n)


def _calc_metrics(trades_df: pd.DataFrame, holding_days: int) -> dict[str, float]:
    if trades_df.empty:
        return {
            "trade_count": 0,
            "total_return_pct": 0.0,
            "annual_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
            "win_rate_pct": 0.0,
            "avg_trade_return_pct": 0.0,
            "avg_win_return_pct": 0.0,
            "avg_loss_return_pct": 0.0,
            "profit_factor": 0.0,
            "payoff_ratio": 0.0,
            "tail_ratio": 0.0,
            "ulcer_index_pct": 0.0,
            "recovery_factor": 0.0,
            "capital_efficiency": 0.0,
            "avg_exposure_pct": 0.0,
            "annual_turnover_pct": 0.0,
            "trades_per_year": 0.0,
            "raw_total_return_pct": 0.0,
            "raw_annual_return_pct": 0.0,
            "raw_max_drawdown_pct": 0.0,
            "raw_sharpe": 0.0,
            "raw_sortino": 0.0,
            "raw_calmar": 0.0,
            "raw_ulcer_index_pct": 0.0,
            "loss_clamp_used_count": 0,
            "loss_clamp_used_rate_pct": 0.0,
            "portfolio_ret_raw_min_pct": 0.0,
            "portfolio_ret_min_pct": 0.0,
        }

    eq = trades_df["equity"].to_numpy(dtype=float)
    eq_path = np.concatenate(([1.0], eq))
    rets = trades_df["portfolio_ret"].to_numpy(dtype=float)
    raw_rets = (
        trades_df["portfolio_ret_raw"].to_numpy(dtype=float)
        if "portfolio_ret_raw" in trades_df.columns
        else rets.copy()
    )
    raw_rets = np.nan_to_num(raw_rets, nan=0.0, posinf=0.0, neginf=0.0)
    bench_rets_raw = (
        trades_df["benchmark_ret_raw"].to_numpy(dtype=float)
        if "benchmark_ret_raw" in trades_df.columns
        else (
            trades_df["benchmark_ret"].to_numpy(dtype=float)
            if "benchmark_ret" in trades_df.columns
            else np.zeros_like(rets)
        )
    )
    bench_rets = (
        trades_df["benchmark_ret"].to_numpy(dtype=float)
        if "benchmark_ret" in trades_df.columns
        else bench_rets_raw
    )
    excess_rets = rets - bench_rets

    total_ret = eq[-1] - 1.0
    peak = np.maximum.accumulate(eq_path)
    mdd = float(np.min(eq_path / peak - 1.0))
    win_rate = float((rets > 0).mean())
    avg_ret = float(np.mean(rets))
    avg_bench_ret = float(np.mean(bench_rets_raw)) if len(bench_rets_raw) else 0.0
    avg_excess_ret = float(np.mean(excess_rets)) if len(excess_rets) else 0.0
    avg_exposure = float(trades_df["total_exposure"].mean())
    win_rets = rets[rets > 0]
    loss_rets = rets[rets < 0]
    avg_win_ret = float(np.mean(win_rets)) if len(win_rets) else 0.0
    avg_loss_ret = float(np.mean(loss_rets)) if len(loss_rets) else 0.0
    gross_profit = float(np.sum(win_rets)) if len(win_rets) else 0.0
    gross_loss = float(abs(np.sum(loss_rets))) if len(loss_rets) else 0.0

    vol = float(np.std(rets, ddof=1)) if len(rets) >= 2 else 0.0
    ann_factor = np.sqrt(252.0 / max(holding_days, 1))
    sharpe = float((avg_ret / vol) * ann_factor) if vol > 1e-12 else 0.0
    excess_vol = float(np.std(excess_rets, ddof=1)) if len(excess_rets) >= 2 else 0.0
    info_ratio = float((avg_excess_ret / excess_vol) * ann_factor) if excess_vol > 1e-12 else 0.0
    beat_rate = float((excess_rets > 0).mean()) if len(excess_rets) else 0.0

    # [Audit Fix] Sortino Ratio（仅考虑下行波动）
    downside_rets = np.minimum(rets, 0.0)
    downside_vol = float(np.sqrt(np.mean(downside_rets ** 2))) if len(downside_rets) >= 2 else 0.0
    sortino = float((avg_ret / downside_vol) * ann_factor) if downside_vol > 1e-12 else 0.0

    first = pd.to_datetime(trades_df["entry_date"].iloc[0])
    last = pd.to_datetime(trades_df["exit_date"].iloc[-1])
    span_days = max((last - first).days, 1)
    annual_ret = (1.0 + total_ret) ** (365.0 / span_days) - 1.0
    raw_eq_path = np.concatenate(([1.0], np.cumprod(1.0 + raw_rets)))
    raw_total_ret = float(raw_eq_path[-1] - 1.0)
    raw_peak = np.maximum.accumulate(raw_eq_path)
    raw_dd_path = raw_eq_path / raw_peak - 1.0
    raw_mdd = float(np.min(raw_dd_path)) if len(raw_dd_path) else 0.0
    raw_annual_ret = (1.0 + raw_total_ret) ** (365.0 / span_days) - 1.0 if raw_total_ret > -0.999999 else -1.0
    raw_avg_ret = float(np.mean(raw_rets)) if len(raw_rets) else 0.0
    raw_vol = float(np.std(raw_rets, ddof=1)) if len(raw_rets) >= 2 else 0.0
    raw_sharpe = float((raw_avg_ret / raw_vol) * ann_factor) if raw_vol > 1e-12 else 0.0
    raw_downside_rets = np.minimum(raw_rets, 0.0)
    raw_downside_vol = float(np.sqrt(np.mean(raw_downside_rets ** 2))) if len(raw_downside_rets) >= 2 else 0.0
    raw_sortino = float((raw_avg_ret / raw_downside_vol) * ann_factor) if raw_downside_vol > 1e-12 else 0.0
    raw_calmar = float(raw_annual_ret / abs(raw_mdd)) if abs(raw_mdd) > 1e-6 else 0.0
    raw_ulcer_index = float(np.sqrt(np.mean((raw_dd_path * 100.0) ** 2))) if len(raw_dd_path) else 0.0
    loss_clamp_used_count = (
        int(pd.Series(trades_df["loss_clamp_used"]).astype(bool).sum())
        if "loss_clamp_used" in trades_df.columns
        else 0
    )
    loss_clamp_used_rate = float(loss_clamp_used_count / max(len(trades_df), 1))
    bench_total_ret = float(np.prod(1.0 + bench_rets_raw) - 1.0) if len(bench_rets_raw) else 0.0
    bench_annual_ret = (1.0 + bench_total_ret) ** (365.0 / span_days) - 1.0 if span_days > 0 else 0.0
    bench_exposure_adj_total_ret = float(np.prod(1.0 + bench_rets) - 1.0) if len(bench_rets) else 0.0
    bench_exposure_adj_annual_ret = (
        (1.0 + bench_exposure_adj_total_ret) ** (365.0 / span_days) - 1.0
        if span_days > 0
        else 0.0
    )
    excess_total_ret = float(np.prod(1.0 + excess_rets) - 1.0) if len(excess_rets) else 0.0
    excess_annual_ret = (1.0 + excess_total_ret) ** (365.0 / span_days) - 1.0 if span_days > 0 else 0.0
    years = span_days / 365.0
    # 简化年化换手：每笔换手约为 2 * 当期总暴露（买入+卖出）
    annual_turnover = float((trades_df["total_exposure"].sum() * 2.0) / years) if years > 0 else 0.0
    trades_per_year = float(len(trades_df) / years) if years > 0 else 0.0

    # [Audit Fix] Calmar Ratio（年化收益 / 最大回撤）
    calmar = float(annual_ret / abs(mdd)) if abs(mdd) > 1e-6 else 0.0
    recovery_factor = float(total_ret / abs(mdd)) if abs(mdd) > 1e-6 else 0.0
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 1e-12 else (10.0 if gross_profit > 0 else 0.0)
    payoff_ratio = float(avg_win_ret / abs(avg_loss_ret)) if abs(avg_loss_ret) > 1e-12 else (10.0 if avg_win_ret > 0 else 0.0)
    tail_dn = float(abs(np.percentile(rets, 5))) if len(rets) else 0.0
    tail_up = float(abs(np.percentile(rets, 95))) if len(rets) else 0.0
    tail_ratio = float(tail_up / tail_dn) if tail_dn > 1e-12 else (10.0 if tail_up > 0 else 0.0)

    # [Audit Fix] 最大回撤持续期（交易笔数）
    dd_path = eq_path / peak - 1.0
    ulcer_index = float(np.sqrt(np.mean((dd_path * 100.0) ** 2))) if len(dd_path) else 0.0
    capital_efficiency = float((annual_ret * 100.0) / max(avg_exposure * 100.0, 1e-9)) if avg_exposure > 1e-12 else 0.0
    in_drawdown = dd_path < -1e-8
    max_dd_duration = 0
    cur_dd_dur = 0
    for is_dd in in_drawdown:
        if is_dd:
            cur_dd_dur += 1
            max_dd_duration = max(max_dd_duration, cur_dd_dur)
        else:
            cur_dd_dur = 0

    return {
        "trade_count": int(len(trades_df)),
        "total_return_pct": float(total_ret * 100),
        "annual_return_pct": float(annual_ret * 100),
        "max_drawdown_pct": float(mdd * 100),
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "recovery_factor": float(recovery_factor),
        "max_dd_duration_trades": int(max_dd_duration),
        "win_rate_pct": float(win_rate * 100),
        "avg_trade_return_pct": float(avg_ret * 100),
        "avg_win_return_pct": float(avg_win_ret * 100),
        "avg_loss_return_pct": float(avg_loss_ret * 100),
        "profit_factor": float(min(max(profit_factor, 0.0), 10.0)),
        "payoff_ratio": float(min(max(payoff_ratio, 0.0), 10.0)),
        "tail_ratio": float(min(max(tail_ratio, 0.0), 10.0)),
        "ulcer_index_pct": float(max(ulcer_index, 0.0)),
        "benchmark_total_return_pct": float(bench_total_ret * 100),
        "benchmark_annual_return_pct": float(bench_annual_ret * 100),
        "benchmark_exposure_adj_total_return_pct": float(bench_exposure_adj_total_ret * 100),
        "benchmark_exposure_adj_annual_return_pct": float(bench_exposure_adj_annual_ret * 100),
        "excess_total_return_pct": float(excess_total_ret * 100),
        "excess_annual_return_pct": float(excess_annual_ret * 100),
        "beat_rate_pct": float(beat_rate * 100),
        "info_ratio": float(info_ratio),
        "capital_efficiency": float(capital_efficiency),
        "avg_exposure_pct": float(avg_exposure * 100),
        "annual_turnover_pct": float(annual_turnover * 100),
        "trades_per_year": trades_per_year,
        "raw_total_return_pct": float(raw_total_ret * 100),
        "raw_annual_return_pct": float(raw_annual_ret * 100),
        "raw_max_drawdown_pct": float(raw_mdd * 100),
        "raw_sharpe": float(raw_sharpe),
        "raw_sortino": float(raw_sortino),
        "raw_calmar": float(raw_calmar),
        "raw_ulcer_index_pct": float(max(raw_ulcer_index, 0.0)),
        "loss_clamp_used_count": int(loss_clamp_used_count),
        "loss_clamp_used_rate_pct": float(loss_clamp_used_rate * 100),
        "portfolio_ret_raw_min_pct": float(np.min(raw_rets) * 100) if len(raw_rets) else 0.0,
        "portfolio_ret_min_pct": float(np.min(rets) * 100) if len(rets) else 0.0,
    }


def backtest_portfolio(cfg: BacktestConfig) -> tuple[pd.DataFrame, dict[str, float]]:
    rec_map = _load_daily_recommendations(OUTPUT_DIR, exclude_bj9=cfg.exclude_bj9)
    if not rec_map:
        raise RuntimeError("未找到 daily_YYYYMMDD.csv 推荐文件，请先生成历史 ML 推荐。")

    recommendation_dates = sorted(rec_map)
    market_start = pd.to_datetime(cfg.start).normalize() if cfg.start else recommendation_dates[0]
    market_end = pd.to_datetime(cfg.end).normalize() if cfg.end else recommendation_dates[-1]
    market_df, bars_idx = _load_market_open_prices(
        market_start,
        market_end,
        holding_days=cfg.holding_days,
        include_bj9=not cfg.exclude_bj9,
    )
    industry_map = _load_industry_map(asof_date=market_end)
    bench_level_map, bench_used = _load_benchmark_levels(cfg, market_df)
    amount_lookup = {
        (d, c): {
            "amount_last": float(amount),
            "amount_ma20": float(ma20),
            "amount_min5": float(min5),
            "amount_min10": float(min10),
        }
        for d, c, amount, ma20, min5, min10 in market_df[
            ["trade_date", "code", "amount", "amount_ma20", "amount_min5", "amount_min10"]
        ].itertuples(index=False, name=None)
    }
    trading_days = sorted(market_df["trade_date"].dropna().unique())
    if len(trading_days) < 10:
        raise RuntimeError("交易日不足，无法回测。")

    td_to_idx = {d: i for i, d in enumerate(trading_days)}

    start_dt = pd.to_datetime(cfg.start).normalize() if cfg.start else trading_days[0]
    end_dt = pd.to_datetime(cfg.end).normalize() if cfg.end else trading_days[-1]
    if start_dt > end_dt:
        raise ValueError("start 不能晚于 end")

    signal_dates = sorted([d for d in rec_map.keys() if start_dt <= d <= end_dt and d in td_to_idx])
    if not signal_dates:
        raise RuntimeError("指定区间内没有可用推荐日期。")

    # [Audit Fix P0-2] 佣金+滑点双边 + 印花税卖出单边
    roundtrip_cost = (cfg.fee_bps + cfg.slippage_bps) * 2.0 / 10000.0 + cfg.stamp_duty_bps / 10000.0
    equity = 1.0
    next_free_entry_idx = 0
    trades: list[dict[str, object]] = []

    for sig_dt in signal_dates:
        sig_idx = td_to_idx[sig_dt]
        entry_idx = sig_idx + 1
        exit_idx = entry_idx + cfg.holding_days

        if entry_idx < next_free_entry_idx:
            continue
        if exit_idx >= len(trading_days):
            continue

        entry_dt = trading_days[entry_idx]
        exit_dt = trading_days[exit_idx]

        day_df = rec_map[sig_dt].copy()
        if day_df.empty:
            continue
        day_df["代码"] = day_df["代码"].astype(str).apply(_norm_code)
        code_list = [_norm_code(code) for code in day_df["代码"].tolist()]
        if "amount_ma20" not in day_df.columns:
            if "成交额MA20" in day_df.columns:
                day_df["amount_ma20"] = pd.to_numeric(day_df["成交额MA20"], errors="coerce").fillna(0.0)
            else:
                day_df["amount_ma20"] = [
                    float(amount_lookup.get((sig_dt, code), {}).get("amount_ma20", 0.0))
                    for code in code_list
                ]
        if "amount_last" not in day_df.columns:
            day_df["amount_last"] = [
                float(amount_lookup.get((sig_dt, code), {}).get("amount_last", 0.0))
                for code in code_list
            ]
        if "amount_min5" not in day_df.columns:
            day_df["amount_min5"] = [
                float(amount_lookup.get((sig_dt, code), {}).get("amount_min5", 0.0))
                for code in code_list
            ]
        if "amount_min10" not in day_df.columns:
            day_df["amount_min10"] = [
                float(amount_lookup.get((sig_dt, code), {}).get("amount_min10", 0.0))
                for code in code_list
            ]
        if "amount_capacity_conservative" not in day_df.columns:
            day_df["amount_capacity_conservative"] = [
                _positive_min([ma20, last, min5, min10])
                for ma20, last, min5, min10 in day_df[
                    ["amount_ma20", "amount_last", "amount_min5", "amount_min10"]
                ].itertuples(index=False, name=None)
            ]
        if "成交额MA20" not in day_df.columns:
            day_df["成交额MA20"] = day_df["amount_ma20"]
        if cfg.exclude_st and "名称" in day_df.columns:
            day_df = day_df[~day_df["名称"].astype(str).str.upper().str.contains("ST", na=False)]
        if cfg.exclude_bj9:
            day_df = day_df[~day_df["代码"].apply(_is_excluded_code)].copy()
        if day_df.empty:
            continue

        if "排名" in day_df.columns:
            day_df = day_df.sort_values("排名")
        market_state = str(day_df["市场状态"].iloc[0]) if ("市场状态" in day_df.columns and not day_df.empty) else ""
        tp_used, sl_used, trail_used, corr_used = _regime_risk_params(cfg, market_state)
        picks = _pick_by_engine(day_df, cfg.top_n, cfg.engine_mode, market_state, cfg, industry_map=industry_map).copy()
        picks = _apply_diversification_filters(
            picks,
            market_df=market_df,
            trading_days=trading_days,
            entry_idx=entry_idx,
            cfg=cfg,
            industry_map=industry_map,
            max_pair_corr=corr_used,
        )
        if picks.empty:
            continue
        picks = picks.copy()
        picks["代码"] = picks["代码"].astype(str).apply(_norm_code)
        if "industry" not in picks.columns:
            picks["industry"] = picks["代码"].map(industry_map).fillna("").astype(str).str.strip()
            picks["industry"] = picks["industry"].replace({"nan": "", "None": ""})
            picks["industry_missing"] = (picks["industry"] == "").astype(int)
            picks.loc[picks["industry_missing"] == 1, "industry"] = UNKNOWN_INDUSTRY_LABEL
        elif "industry_missing" not in picks.columns:
            picks["industry_missing"] = (picks["industry"].astype(str).fillna("").str.strip() == UNKNOWN_INDUSTRY_LABEL).astype(int)
        if "名称" not in picks.columns:
            picks["名称"] = ""
        else:
            picks["名称"] = picks["名称"].astype(str).fillna("")

        # A股可执行性约束：停牌/一字涨停无法买入的标的不参与本笔组合
        if cfg.enable_exec_constraints:
            tradable_rows = []
            for _, row in picks.iterrows():
                code = _norm_code(row.get("代码", ""))
                name = str(row.get("名称", "") or "")
                bar = _get_bar_row(bars_idx, entry_dt, code)
                if _can_enter_long(bar, code, name):
                    tradable_rows.append(row)
            picks = pd.DataFrame(tradable_rows) if tradable_rows else pd.DataFrame(columns=picks.columns)
            if len(picks) > cfg.top_n:
                picks = picks.head(cfg.top_n)
        if picks.empty:
            continue

        position_text = picks["建议仓位"].iloc[0] if "建议仓位" in picks.columns else ""
        single_text = picks["单票上限"].iloc[0] if "单票上限" in picks.columns else ""

        total_target = cfg.fallback_total_position
        if cfg.use_regime_position:
            total_target = _parse_percent_text(position_text, cfg.fallback_total_position)

        single_cap = cfg.max_single_pos
        if cfg.use_regime_position:
            single_cap = min(cfg.max_single_pos, _parse_percent_text(single_text, cfg.max_single_pos))
        else:
            single_cap = cfg.max_single_pos

        # 风险开关：近期表现恶化时自动降仓
        risk_factor = _compute_risk_switch_factor(cfg, trades)
        total_target *= risk_factor

        if total_target <= 0 or single_cap <= 0:
            continue

        score_col = "refactor_score" if "refactor_score" in picks.columns else ("hybrid_score" if "hybrid_score" in picks.columns else "ml")
        optimizer_mode = str(cfg.optimizer_mode or "score_weight").strip().lower()
        capacity_on = optimizer_mode in {"capacity_aware", "capacity_crowding", "capacity_crowding_aware"}
        target_amount_col = str(cfg.target_capacity_amount_col or "amount_ma20")
        if target_amount_col not in picks.columns:
            target_amount_col = "amount_ma20"
        decision = build_portfolio_decision(
            picks,
            PortfolioConstraints(
                total_target=float(total_target),
                single_cap=float(single_cap),
                industry_cap=float(cfg.target_max_industry_weight) if capacity_on else 0.0,
                adv_participation_cap=float(cfg.target_max_adv_participation) if capacity_on else 0.0,
                capital_base=max(float(cfg.target_capital_base), 1.0),
                score_col=score_col,
                code_col="代码",
                industry_col="industry",
                amount_col=target_amount_col,
                amount_buffer=max(0.0, float(cfg.target_capacity_amount_buffer)),
                redistribute_clipped=bool(cfg.redistribute_clipped_weight),
                impact_model=str(cfg.impact_model or "sqrt"),
                impact_base_bps=max(0.0, float(cfg.impact_base_bps)),
                impact_participation_bps=max(0.0, float(cfg.impact_participation_bps)),
                impact_power=max(0.05, float(cfg.impact_power)),
            ),
        )
        picks = decision.selected.copy()
        portfolio_diag = dict(decision.diagnostics)
        portfolio_exposures = dict(decision.exposures)
        if picks.empty:
            continue

        entry_candidates: list[tuple[str, str, float, float, float, float, float, float]] = []
        for _, row in picks.iterrows():
            code = _norm_code(row.get("代码", ""))
            name = str(row.get("名称", "") or "")
            score_val = row.get(score_col, 0.0)
            target_weight = float(pd.to_numeric(pd.Series([row.get("target_weight", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
            if target_weight <= 0:
                continue
            code = _norm_code(code)
            entry_bar = _get_bar_row(bars_idx, entry_dt, code)
            if entry_bar is None:
                continue
            ep = float(entry_bar.get("open", np.nan))
            if (not np.isfinite(ep)) or ep <= 0:
                continue
            impact_bps = float(pd.to_numeric(pd.Series([row.get("impact_cost_bps", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
            participation_pct = float(pd.to_numeric(pd.Series([row.get("participation_pct", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
            unfilled_weight = float(pd.to_numeric(pd.Series([row.get("unfilled_target_weight", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
            industry_weight = float(pd.to_numeric(pd.Series([row.get("industry_weight_post", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
            entry_candidates.append(
                (
                    code,
                    name,
                    float(score_val) if pd.notna(score_val) else 0.0,
                    target_weight,
                    impact_bps,
                    participation_pct,
                    unfilled_weight,
                    industry_weight,
                )
            )

        if len(entry_candidates) < cfg.min_valid_positions:
            continue

        # 动态退出：在持有窗口内触发止盈/止损/回撤保护可提前离场
        # [Audit Fix P0-3] 使用收盘价判断触发条件，次日开盘执行卖出（符合 T+1 制度）
        actual_exit_idx = exit_idx
        exit_reason = "time_exit"
        if cfg.enable_dynamic_exit:
            candidate_codes = [c for c, *_ in entry_candidates]
            impact_by_code = {c: impact_bps for c, _, _, _, impact_bps, *_ in entry_candidates}
            peak_ret = -1e9
            for j in range(entry_idx, min(entry_idx + cfg.holding_days, len(trading_days) - 1)):
                dt_j = trading_days[j]
                rets_j = []
                for code in candidate_codes:
                    entry_bar = _get_bar_row(bars_idx, entry_dt, code)
                    check_bar = _get_bar_row(bars_idx, dt_j, code)
                    if entry_bar is None or check_bar is None:
                        continue
                    ep = float(entry_bar.get("open", np.nan))
                    # 用收盘价判断触发（实盘可观测）
                    cp = float(check_bar.get("close", np.nan))
                    if (not np.isfinite(ep)) or (not np.isfinite(cp)) or ep <= 0 or cp <= 0:
                        continue
                    impact_roundtrip = 2.0 * max(0.0, float(impact_by_code.get(code, 0.0))) / 10000.0
                    rets_j.append(float(cp / ep - 1.0 - roundtrip_cost - impact_roundtrip))
                if len(rets_j) < cfg.min_valid_positions:
                    continue
                pr = float(np.mean(rets_j))
                peak_ret = max(peak_ret, pr)
                # 触发后在次日(j+1)开盘执行卖出
                exec_idx = j + 1
                if exec_idx >= len(trading_days):
                    continue
                if pr <= -abs(sl_used):
                    actual_exit_idx = exec_idx
                    exit_reason = "stop_loss"
                    break
                if pr >= abs(tp_used):
                    actual_exit_idx = exec_idx
                    exit_reason = "take_profit"
                    break
                if peak_ret > 0 and (peak_ret - pr) >= abs(trail_used):
                    actual_exit_idx = exec_idx
                    exit_reason = "trail_stop"
                    break

        if cfg.enable_exec_constraints:
            aligned_exit_idx = _align_exit_idx_with_exec_constraints(
                bars_idx=bars_idx,
                trading_days=trading_days,
                base_exit_idx=actual_exit_idx,
                held=[(c, n) for c, n, *_ in entry_candidates],
                cfg=cfg,
            )
            if aligned_exit_idx is None:
                continue
            if aligned_exit_idx != actual_exit_idx and exit_reason == "time_exit":
                exit_reason = "exit_delayed_exec"
            actual_exit_idx = aligned_exit_idx

        exit_dt = trading_days[actual_exit_idx]

        valid_returns: list[float] = []
        valid_codes: list[str] = []
        valid_weights: list[float] = []
        valid_impact_bps: list[float] = []
        valid_participation_pct: list[float] = []
        valid_unfilled_weight: list[float] = []
        valid_industry_weight: list[float] = []
        for code, name, score_val, target_weight, impact_bps, participation_pct, unfilled_weight, industry_weight in entry_candidates:
            entry_bar = _get_bar_row(bars_idx, entry_dt, code)
            exit_bar = _get_bar_row(bars_idx, exit_dt, code)
            if entry_bar is None or exit_bar is None:
                continue
            ep = float(entry_bar.get("open", np.nan))
            xp = float(exit_bar.get("open", np.nan))
            if (not np.isfinite(ep)) or (not np.isfinite(xp)) or ep <= 0 or xp <= 0:
                continue
            gross_ret = xp / ep - 1.0
            impact_roundtrip = 2.0 * max(0.0, float(impact_bps)) / 10000.0
            net_ret = gross_ret - roundtrip_cost - impact_roundtrip
            valid_returns.append(float(net_ret))
            valid_codes.append(code)
            valid_weights.append(float(target_weight))
            valid_impact_bps.append(float(impact_bps))
            valid_participation_pct.append(float(participation_pct))
            valid_unfilled_weight.append(float(unfilled_weight))
            valid_industry_weight.append(float(industry_weight))

        if len(valid_returns) < cfg.min_valid_positions:
            continue

        weights = np.asarray(valid_weights, dtype=float)
        if len(weights) != len(valid_returns) or float(np.sum(weights)) <= 0:
            continue

        total_exposure = float(np.sum(weights))
        portfolio_ret_raw = float(np.sum(weights * np.array(valid_returns, dtype=float)))
        # 组合层风险开关：单笔最大亏损限制（近似，按本周期收益截断）
        loss_clamp_used = False
        portfolio_ret = portfolio_ret_raw
        if cfg.loss_clamp_enabled and cfg.max_loss_per_trade is not None:
            clamp_floor = -abs(float(cfg.max_loss_per_trade))
            loss_clamp_used = bool(portfolio_ret_raw < clamp_floor)
            portfolio_ret = max(portfolio_ret_raw, clamp_floor)
        bench_ret_raw = 0.0
        if bench_level_map:
            be = bench_level_map.get(entry_dt)
            bx = bench_level_map.get(exit_dt)
            if be and bx and be > 0:
                bench_ret_raw = float(bx / be - 1.0)
        bench_ret = float(bench_ret_raw * total_exposure)
        excess_ret = float(portfolio_ret - bench_ret)
        equity *= (1.0 + portfolio_ret)

        trades.append(
            {
                "signal_date": sig_dt.strftime("%Y-%m-%d"),
                "entry_date": entry_dt.strftime("%Y-%m-%d"),
                "exit_date": exit_dt.strftime("%Y-%m-%d"),
                "state": picks["市场状态"].iloc[0] if "市场状态" in picks.columns else "",
                "selected_count": int(len(picks)),
                "valid_count": int(len(valid_returns)),
                "missing_industry_count": int(pd.to_numeric(picks.get("industry_missing", 0), errors="coerce").fillna(0).sum()),
                "unknown_industry_selected_count": int((picks.get("industry", "").astype(str) == UNKNOWN_INDUSTRY_LABEL).sum()) if "industry" in picks.columns else 0,
                "signal_quality_mean": float(pd.to_numeric(picks.get("signal_quality", np.nan), errors="coerce").mean())
                if "signal_quality" in picks.columns
                else np.nan,
                "stability_score_mean": float(pd.to_numeric(picks.get("stability_score", np.nan), errors="coerce").mean())
                if "stability_score" in picks.columns
                else np.nan,
                "refactor_score_mean": float(pd.to_numeric(picks.get("refactor_score", np.nan), errors="coerce").mean())
                if "refactor_score" in picks.columns
                else np.nan,
                "feature_redundancy_mean": float(pd.to_numeric(picks.get("feature_redundancy", np.nan), errors="coerce").mean())
                if "feature_redundancy" in picks.columns
                else np.nan,
                "per_position_weight": float(total_exposure / max(len(valid_returns), 1)),
                "total_exposure": float(total_exposure),
                "avg_stock_ret": float(np.mean(valid_returns)),
                "portfolio_ret_raw": float(portfolio_ret_raw),
                "portfolio_ret": float(portfolio_ret),
                "loss_clamp_used": bool(loss_clamp_used),
                "loss_clamp_enabled": bool(cfg.loss_clamp_enabled),
                "avg_impact_cost_bps": float(np.mean(valid_impact_bps)) if valid_impact_bps else 0.0,
                "max_participation_pct": float(np.max(valid_participation_pct)) if valid_participation_pct else 0.0,
                "unfilled_target_weight": float(np.sum(valid_unfilled_weight)) if valid_unfilled_weight else 0.0,
                "max_industry_weight_post": float(np.max(valid_industry_weight)) if valid_industry_weight else 0.0,
                "optimizer_mode": optimizer_mode,
                "optimizer_blocked_count": int(portfolio_diag.get("blocked_count", 0)),
                "optimizer_clipped_count": int(portfolio_diag.get("clipped_count", 0)),
                "optimizer_estimated_impact_cost_bps": float(portfolio_exposures.get("estimated_impact_cost_bps", 0.0)),
                "optimizer_max_adv_participation_pct": float(portfolio_exposures.get("max_adv_participation_pct", 0.0)),
                "benchmark_ret_raw": float(bench_ret_raw),
                "benchmark_ret": float(bench_ret),
                "excess_ret": float(excess_ret),
                "equity": float(equity),
                "risk_factor": float(risk_factor),
                "exit_reason": exit_reason,
                "tp_used": float(tp_used),
                "sl_used": float(sl_used),
                "trail_used": float(trail_used),
                "corr_used": float(corr_used),
                "codes": ",".join(valid_codes),
                "weights": ",".join([f"{w:.6f}" for w in weights]),
                "engine_mode": cfg.engine_mode,
                "benchmark_mode": bench_used,
            }
        )
        next_free_entry_idx = actual_exit_idx

    trades_df = pd.DataFrame(trades)
    metrics = _calc_metrics(trades_df, cfg.holding_days)
    return trades_df, metrics


def _print_summary(metrics: dict[str, float], cfg: BacktestConfig) -> None:
    print("\n" + "=" * 72)
    print("量化组合回测结果")
    print("=" * 72)
    print(
        f"TopN: {cfg.top_n} | 持有: {cfg.holding_days}天 | 排除ST: {cfg.exclude_st} | "
        f"排除北交所9开头: {cfg.exclude_bj9}"
    )
    print(f"交易成本: fee {cfg.fee_bps:.1f}bps + slippage {cfg.slippage_bps:.1f}bps (单边) + stamp_duty {cfg.stamp_duty_bps:.1f}bps (卖出)")
    print(f"交易次数: {metrics['trade_count']}")
    print(f"总收益: {metrics['total_return_pct']:.2f}%")
    print(f"年化收益: {metrics['annual_return_pct']:.2f}%")
    print(f"最大回撤: {metrics['max_drawdown_pct']:.2f}%")
    if int(metrics.get("loss_clamp_used_count", 0)) > 0 or cfg.loss_clamp_enabled:
        print(
            f"Raw口径: total={metrics.get('raw_total_return_pct', 0.0):.2f}% | "
            f"annual={metrics.get('raw_annual_return_pct', 0.0):.2f}% | "
            f"mdd={metrics.get('raw_max_drawdown_pct', 0.0):.2f}% | "
            f"clamp_used={int(metrics.get('loss_clamp_used_count', 0))}"
        )
    print(f"Sharpe: {metrics['sharpe']:.3f} | Sortino: {metrics.get('sortino', 0.0):.3f} | Calmar: {metrics.get('calmar', 0.0):.3f}")
    print(
        f"收益质量: ProfitFactor={metrics.get('profit_factor', 0.0):.3f} | "
        f"TailRatio={metrics.get('tail_ratio', 0.0):.3f} | "
        f"Ulcer={metrics.get('ulcer_index_pct', 0.0):.2f} | "
        f"CapitalEff={metrics.get('capital_efficiency', 0.0):.3f}"
    )
    print(f"最大回撤持续期: {metrics.get('max_dd_duration_trades', 0)} 笔交易")
    print(f"胜率: {metrics['win_rate_pct']:.2f}%")
    print(
        f"单笔平均收益: {metrics['avg_trade_return_pct']:.2f}% | "
        f"平均盈利/亏损: {metrics.get('avg_win_return_pct', 0.0):.2f}% / {metrics.get('avg_loss_return_pct', 0.0):.2f}%"
    )
    print(
        f"基准总收益/年化: {metrics.get('benchmark_total_return_pct', 0.0):.2f}% / "
        f"{metrics.get('benchmark_annual_return_pct', 0.0):.2f}%"
    )
    print(
        f"超额总收益/年化: {metrics.get('excess_total_return_pct', 0.0):.2f}% / "
        f"{metrics.get('excess_annual_return_pct', 0.0):.2f}%"
    )
    print(
        f"跑赢占比: {metrics.get('beat_rate_pct', 0.0):.2f}% | "
        f"Info Ratio: {metrics.get('info_ratio', 0.0):.3f}"
    )
    print(f"平均暴露仓位: {metrics['avg_exposure_pct']:.2f}%")
    print(f"年化换手: {metrics['annual_turnover_pct']:.2f}% | 年化交易笔数: {metrics['trades_per_year']:.2f}")
    print(
        f"风控: 分散={cfg.enable_diversification} 行业上限={cfg.max_industry_positions} "
        f"相关阈值={cfg.max_pair_corr:.2f} 动态退出={cfg.enable_dynamic_exit} "
        f"分市场参数={cfg.enable_regime_risk_params} 风险开关={cfg.enable_risk_switch} "
        f"执行约束={cfg.enable_exec_constraints}(max_exit_delay={cfg.max_exit_delay_days}) "
        f"质量门禁={cfg.enable_signal_quality_gate}(floor={cfg.min_signal_quality:.2f},ml_w={cfg.ml_quality_blend:.2f}) "
        f"特征重构={cfg.enable_feature_refactor}(blend={cfg.stability_blend:.2f},gate={cfg.enable_feature_refactor_gate},floor={cfg.min_refactor_score:.2f})"
        f" 优化器={cfg.optimizer_mode}(ind_cap={cfg.target_max_industry_weight:.2f},adv_cap={cfg.target_max_adv_participation:.2f})"
    )


def _save_outputs(trades_df: pd.DataFrame, metrics: dict[str, float], cfg: BacktestConfig) -> tuple[Path, Path, Path]:
    dirs = ensure_output_dirs(OUTPUT_DIR)
    base_dir = Path(OUTPUT_DIR)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    detail_new = dirs["backtest"] / f"quant_trades_{timestamp}.csv"
    detail_legacy = base_dir / f"quant_trades_{timestamp}.csv"
    write_dual_csv(trades_df, detail_new, detail_legacy, index=False, encoding="utf-8-sig")

    summary_row = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start": cfg.start or "",
        "end": cfg.end or "",
        "top_n": cfg.top_n,
        "holding_days": cfg.holding_days,
        "fee_bps": cfg.fee_bps,
        "slippage_bps": cfg.slippage_bps,
        "max_single_pos": cfg.max_single_pos,
        "use_regime_position": int(cfg.use_regime_position),
        "exclude_st": int(cfg.exclude_st),
        "exclude_bj9": int(cfg.exclude_bj9),
        "max_loss_per_trade": "" if cfg.max_loss_per_trade is None else cfg.max_loss_per_trade,
        "loss_clamp_enabled": int(cfg.loss_clamp_enabled),
        "engine_mode": cfg.engine_mode,
        "benchmark_mode": cfg.benchmark_mode,
        "benchmark_file": cfg.benchmark_file or "",
        "enable_diversification": int(cfg.enable_diversification),
        "max_industry_positions": cfg.max_industry_positions,
        "corr_lookback_days": cfg.corr_lookback_days,
        "max_pair_corr": cfg.max_pair_corr,
        "corr_min_obs": cfg.corr_min_obs,
        "enable_dynamic_exit": int(cfg.enable_dynamic_exit),
        "take_profit": cfg.take_profit,
        "stop_loss": cfg.stop_loss,
        "trail_drawdown": cfg.trail_drawdown,
        "enable_regime_risk_params": int(cfg.enable_regime_risk_params),
        "tp_normal": cfg.tp_normal,
        "tp_choppy": cfg.tp_choppy,
        "tp_panic": cfg.tp_panic,
        "sl_normal": cfg.sl_normal,
        "sl_choppy": cfg.sl_choppy,
        "sl_panic": cfg.sl_panic,
        "trail_normal": cfg.trail_normal,
        "trail_choppy": cfg.trail_choppy,
        "trail_panic": cfg.trail_panic,
        "corr_normal": cfg.corr_normal,
        "corr_choppy": cfg.corr_choppy,
        "corr_panic": cfg.corr_panic,
        "enable_risk_switch": int(cfg.enable_risk_switch),
        "risk_window": cfg.risk_window,
        "risk_cut_win_rate": cfg.risk_cut_win_rate,
        "risk_cut_avg_ret": cfg.risk_cut_avg_ret,
        "risk_cut_factor": cfg.risk_cut_factor,
        "enable_exec_constraints": int(cfg.enable_exec_constraints),
        "max_exit_delay_days": cfg.max_exit_delay_days,
        "enable_signal_quality_gate": int(cfg.enable_signal_quality_gate),
        "min_signal_quality": cfg.min_signal_quality,
        "ml_quality_blend": cfg.ml_quality_blend,
        "max_abs_pct_chg": cfg.max_abs_pct_chg,
        "enable_feature_refactor": int(cfg.enable_feature_refactor),
        "stability_blend": cfg.stability_blend,
        "enable_feature_refactor_gate": int(cfg.enable_feature_refactor_gate),
        "min_refactor_score": cfg.min_refactor_score,
        "min_price": cfg.min_price,
        "min_amount_ma20": cfg.min_amount_ma20,
        "liquidity_blend": cfg.liquidity_blend,
        "adv_penalty_blend": cfg.adv_penalty_blend,
        "industry_crowding_blend": cfg.industry_crowding_blend,
        "optimizer_mode": cfg.optimizer_mode,
        "target_capital_base": cfg.target_capital_base,
        "target_max_industry_weight": cfg.target_max_industry_weight,
        "target_max_adv_participation": cfg.target_max_adv_participation,
        "target_capacity_amount_col": cfg.target_capacity_amount_col,
        "target_capacity_amount_buffer": cfg.target_capacity_amount_buffer,
        "redistribute_clipped_weight": int(cfg.redistribute_clipped_weight),
        "impact_model": cfg.impact_model,
        "impact_base_bps": cfg.impact_base_bps,
        "impact_participation_bps": cfg.impact_participation_bps,
        "impact_power": cfg.impact_power,
        **metrics,
    }
    summary_df = pd.DataFrame([summary_row])
    summary_new = dirs["backtest"] / "quant_backtest_summary.csv"
    summary_legacy = base_dir / "quant_backtest_summary.csv"
    write_dual_csv(summary_df, summary_new, summary_legacy, index=False, encoding="utf-8-sig")

    json_new = dirs["backtest"] / "quant_backtest_summary.json"
    json_new.write_text(json.dumps(summary_row, ensure_ascii=False, indent=2), encoding="utf-8")
    return detail_new, summary_new, json_new


def _build_backtest_manifest(cfg: BacktestConfig, argv: list[str]) -> Path:
    security_cfg = load_security_config()
    tracked_files: dict[str, str | Path] = {
        "profile_config": PROFILE_FILE,
    }
    if cfg.benchmark_file:
        tracked_files["benchmark_file"] = cfg.benchmark_file
    manifest = build_run_manifest(
        run_type="quant_portfolio_backtest",
        argv=argv,
        params={
            "start": cfg.start or "",
            "end": cfg.end or "",
            "top_n": int(cfg.top_n),
            "holding_days": int(cfg.holding_days),
            "engine_mode": str(cfg.engine_mode),
            "benchmark_mode": str(cfg.benchmark_mode),
            "use_regime_position": bool(cfg.use_regime_position),
            "market_data": {
                "data_source": "ashare_ods",
                "data_root": str(AShareMarketDataGateway().data_root),
                "snapshot_policy": "latest_snapshot_per_trade_date",
                "price_mode": "unadjusted",
            },
        },
        tracked_files=tracked_files,
        config_fingerprint=build_config_fingerprint(security_cfg),
    )
    return write_run_manifest(BASE_DIR, manifest)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="量化组合交易回测（基于 daily 推荐）")
    p.add_argument("--start", type=str, default=None, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", type=str, default=None, help="结束日期 YYYY-MM-DD")
    p.add_argument(
        "--top-n",
        type=int,
        default=int(DEFAULTS["top_n"]),
        help=f"每次交易最多持仓股票数（默认{int(DEFAULTS['top_n'])}）",
    )
    p.add_argument(
        "--holding-days",
        type=int,
        default=int(DEFAULTS["holding_days"]),
        help=f"持有天数（按交易日，默认{int(DEFAULTS['holding_days'])}）",
    )
    p.add_argument("--fee-bps", type=float, default=8.0, help="单边手续费(bps)")
    p.add_argument("--slippage-bps", type=float, default=5.0, help="单边滑点(bps)")
    p.add_argument("--stamp-duty-bps", type=float, default=5.0, help="印花税(bps)，卖出单边，默认 5.0 (0.05%%)")
    p.add_argument(
        "--max-single-pos",
        type=float,
        default=float(DEFAULTS["max_single_pos"]),
        help=f"单票最大仓位(0~1，默认{float(DEFAULTS['max_single_pos']):.2f})",
    )
    p.add_argument(
        "--fallback-total-pos",
        type=float,
        default=float(DEFAULTS["fallback_total_position"]),
        help=f"无仓位建议时默认总仓(0~1，默认{float(DEFAULTS['fallback_total_position']):.2f})",
    )
    p.add_argument("--min-valid-positions", type=int, default=int(DEFAULTS["min_valid_positions"]), help="最少可成交持仓数")
    p.add_argument("--max-loss-per-trade", type=float, default=None, help="单笔组合最大亏损(0~1)，例如 0.03 表示 -3%%")
    p.add_argument("--enable-loss-clamp", action="store_true", help="启用最终组合收益截断；默认关闭，promotion/rolling 使用 raw 口径")
    p.add_argument(
        "--engine-mode",
        type=str,
        default=str(DEFAULTS["engine_mode"]),
        choices=["left", "right", "hybrid"],
        help=f"交易引擎模式（默认 {str(DEFAULTS['engine_mode'])}）",
    )
    p.add_argument(
        "--benchmark-mode",
        type=str,
        default=str(DEFAULTS["benchmark_mode"]),
        choices=["hs300", "synthetic", "none"],
        help=f"基准模式（默认 {str(DEFAULTS['benchmark_mode'])}）",
    )
    p.add_argument("--benchmark-file", type=str, default=None, help="基准CSV文件（包含 date/trade_date 与 open/close）")
    p.add_argument("--include-bj9", action="store_true", help="包含北交所9开头代码（默认排除）")
    p.add_argument("--disable-diversification", action="store_true", help="关闭行业分散+相关性去重")
    p.add_argument("--max-industry-positions", type=int, default=int(DEFAULTS["max_industry_positions"]), help="单行业最多持仓数")
    p.add_argument("--corr-lookback-days", type=int, default=int(DEFAULTS["corr_lookback_days"]), help="相关性去重回看交易日")
    p.add_argument("--max-pair-corr", type=float, default=float(DEFAULTS["max_pair_corr"]), help="任意两票最大允许相关系数")
    p.add_argument("--corr-min-obs", type=int, default=int(DEFAULTS["corr_min_obs"]), help="计算相关性最少样本数")
    p.add_argument("--disable-dynamic-exit", action="store_true", help="关闭动态止盈止损")
    p.add_argument("--take-profit", type=float, default=float(DEFAULTS["take_profit"]), help="动态止盈阈值(0~1)")
    p.add_argument("--stop-loss", type=float, default=float(DEFAULTS["stop_loss"]), help="动态止损阈值(0~1)")
    p.add_argument("--trail-drawdown", type=float, default=float(DEFAULTS["trail_drawdown"]), help="浮盈回撤止盈阈值(0~1)")
    p.add_argument("--disable-regime-risk-params", action="store_true", help="关闭分市场风险参数")
    p.add_argument("--tp-normal", type=float, default=float(DEFAULTS["tp_normal"]), help="正常市止盈阈值")
    p.add_argument("--tp-choppy", type=float, default=float(DEFAULTS["tp_choppy"]), help="震荡市止盈阈值")
    p.add_argument("--tp-panic", type=float, default=float(DEFAULTS["tp_panic"]), help="恐慌市止盈阈值")
    p.add_argument("--sl-normal", type=float, default=float(DEFAULTS["sl_normal"]), help="正常市止损阈值")
    p.add_argument("--sl-choppy", type=float, default=float(DEFAULTS["sl_choppy"]), help="震荡市止损阈值")
    p.add_argument("--sl-panic", type=float, default=float(DEFAULTS["sl_panic"]), help="恐慌市止损阈值")
    p.add_argument("--trail-normal", type=float, default=float(DEFAULTS["trail_normal"]), help="正常市浮盈回撤阈值")
    p.add_argument("--trail-choppy", type=float, default=float(DEFAULTS["trail_choppy"]), help="震荡市浮盈回撤阈值")
    p.add_argument("--trail-panic", type=float, default=float(DEFAULTS["trail_panic"]), help="恐慌市浮盈回撤阈值")
    p.add_argument("--corr-normal", type=float, default=float(DEFAULTS["corr_normal"]), help="正常市相关性上限")
    p.add_argument("--corr-choppy", type=float, default=float(DEFAULTS["corr_choppy"]), help="震荡市相关性上限")
    p.add_argument("--corr-panic", type=float, default=float(DEFAULTS["corr_panic"]), help="恐慌市相关性上限")
    p.add_argument("--disable-risk-switch", action="store_true", help="关闭风险开关（近期劣化降仓）")
    p.add_argument("--risk-window", type=int, default=int(DEFAULTS["risk_window"]), help="风险开关回看最近N笔交易")
    p.add_argument("--risk-cut-win-rate", type=float, default=float(DEFAULTS["risk_cut_win_rate"]), help="近期胜率低于阈值则降仓")
    p.add_argument("--risk-cut-avg-ret", type=float, default=float(DEFAULTS["risk_cut_avg_ret"]), help="近期平均收益低于阈值则降仓")
    p.add_argument("--risk-cut-factor", type=float, default=float(DEFAULTS["risk_cut_factor"]), help="触发风险开关后的总仓缩放系数")
    p.add_argument("--disable-exec-constraints", action="store_true", help="关闭A股执行约束（停牌/涨跌停不可成交）")
    p.add_argument("--max-exit-delay-days", type=int, default=5, help="卖出受阻时最多顺延交易日")
    p.add_argument("--disable-signal-quality-gate", action="store_true", help="关闭信号质量门禁（默认开启）")
    p.add_argument("--min-signal-quality", type=float, default=float(DEFAULTS["min_signal_quality"]), help="信号质量最低阈值(0~1)")
    p.add_argument("--ml-quality-blend", type=float, default=float(DEFAULTS["ml_quality_blend"]), help="综合分中ML排序权重(0~1)")
    p.add_argument("--max-abs-pct-chg", type=float, default=float(DEFAULTS["max_abs_pct_chg"]), help="信号质量中日涨跌幅惩罚阈值(%%)")
    p.add_argument("--disable-feature-refactor", action="store_true", help="关闭特征重构评分（默认开启）")
    p.add_argument("--stability-blend", type=float, default=float(DEFAULTS["stability_blend"]), help="重构分中稳定性权重(0~1)")
    p.add_argument("--disable-feature-refactor-gate", action="store_true", help="关闭重构分门禁（默认开启）")
    p.add_argument("--min-refactor-score", type=float, default=float(DEFAULTS["min_refactor_score"]), help="重构分最低阈值(0~1)")
    p.add_argument("--min-price", type=float, default=float(DEFAULTS["min_price"]), help="流动性过滤最低股价")
    p.add_argument("--min-amount-ma20", type=float, default=float(DEFAULTS["min_amount_ma20"]), help="流动性过滤最低20日均成交额")
    p.add_argument("--liquidity-blend", type=float, default=float(DEFAULTS["liquidity_blend"]), help="执行友好分与研究排序的混合权重(0~0.5)")
    p.add_argument("--adv-penalty-blend", type=float, default=float(DEFAULTS["adv_penalty_blend"]), help="连续ADV容量分混合权重(0~0.5)")
    p.add_argument("--industry-crowding-blend", type=float, default=float(DEFAULTS["industry_crowding_blend"]), help="行业拥挤惩罚混合权重(0~0.5)")
    p.add_argument(
        "--optimizer-mode",
        type=str,
        default=str(DEFAULTS["optimizer_mode"]),
        choices=["score_weight", "capacity_aware", "capacity_crowding", "capacity_crowding_aware"],
        help="组合权重优化模式",
    )
    p.add_argument("--target-capital-base", type=float, default=float(DEFAULTS["target_capital_base"]), help="容量验收资金规模")
    p.add_argument("--target-max-industry-weight", type=float, default=float(DEFAULTS["target_max_industry_weight"]), help="组合层行业权重上限")
    p.add_argument("--target-max-adv-participation", type=float, default=float(DEFAULTS["target_max_adv_participation"]), help="组合层ADV参与率上限")
    p.add_argument("--target-capacity-amount-col", type=str, default=str(DEFAULTS["target_capacity_amount_col"]), help="组合层容量测算成交额列")
    p.add_argument("--target-capacity-amount-buffer", type=float, default=float(DEFAULTS["target_capacity_amount_buffer"]), help="组合层容量成交额折扣系数")
    p.add_argument("--redistribute-clipped-weight", action="store_true", default=bool(DEFAULTS["redistribute_clipped_weight"]), help="将 ADV/行业剪裁后的剩余权重再分配给合格候选")
    p.add_argument("--impact-model", type=str, default=str(DEFAULTS["impact_model"]), choices=["none", "linear", "sqrt"], help="冲击成本模型")
    p.add_argument("--impact-base-bps", type=float, default=float(DEFAULTS["impact_base_bps"]), help="冲击成本基础bps")
    p.add_argument("--impact-participation-bps", type=float, default=float(DEFAULTS["impact_participation_bps"]), help="参与率冲击成本系数bps")
    p.add_argument("--impact-power", type=float, default=float(DEFAULTS["impact_power"]), help="参与率冲击成本幂指数")
    regime_group = p.add_mutually_exclusive_group()
    regime_group.add_argument("--use-regime-position", action="store_true", help="使用建议仓位（覆盖默认配置）")
    regime_group.add_argument("--no-regime-position", action="store_true", help="不使用建议仓位，固定总仓（覆盖默认配置）")
    p.add_argument("--include-st", action="store_true", help="包含 ST 股票")
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
    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not bool(args.disable_industry_coverage_gate):
        asof_date = args.end or AShareMarketDataGateway().available_trade_dates()[-1]
        metadata_health = load_ods_metadata_health(asof_date)
        metadata_gate = evaluate_metadata_guard(
            metadata_health,
            min_coverage_pct=float(args.min_industry_coverage_pct),
            max_age_days=float(args.max_metadata_staleness_days),
        )
        if not bool(metadata_gate.get("passed", False)):
            print(
                "⛔ 元数据门禁未通过: "
                f"reason={metadata_gate.get('reason', '')} "
                f"| coverage={float(metadata_gate.get('coverage_pct', 0.0)):.2f}% "
                f"| min={float(metadata_gate.get('min_coverage_pct', 0.0)):.2f}% "
                f"| age_days={float(metadata_gate.get('age_days', 0.0)):.2f} "
                f"| max_age_days={float(metadata_gate.get('max_age_days', 0.0)):.2f} "
                f"| file={metadata_gate.get('file', '')}"
            )
            return 1
        print(
            "✅ 元数据门禁通过: "
            f"coverage={float(metadata_gate.get('coverage_pct', 0.0)):.2f}% "
            f"| age_days={float(metadata_gate.get('age_days', 0.0)):.2f} "
            f"| file={metadata_gate.get('file', '')}"
        )
    if args.use_regime_position:
        use_regime_position = True
    elif args.no_regime_position:
        use_regime_position = False
    else:
        use_regime_position = bool(DEFAULTS["use_regime_position"])

    cfg = BacktestConfig(
        start=args.start,
        end=args.end,
        top_n=max(1, args.top_n),
        holding_days=max(1, args.holding_days),
        fee_bps=max(0.0, args.fee_bps),
        slippage_bps=max(0.0, args.slippage_bps),
        stamp_duty_bps=max(0.0, args.stamp_duty_bps),
        max_single_pos=min(max(args.max_single_pos, 0.0), 1.0),
        use_regime_position=use_regime_position,
        fallback_total_position=min(max(args.fallback_total_pos, 0.0), 1.0),
        exclude_st=not args.include_st,
        min_valid_positions=max(1, args.min_valid_positions),
        max_loss_per_trade=(None if args.max_loss_per_trade is None else min(max(args.max_loss_per_trade, 0.0), 1.0)),
        loss_clamp_enabled=bool(args.enable_loss_clamp),
        engine_mode=args.engine_mode,
        benchmark_mode=args.benchmark_mode,
        benchmark_file=args.benchmark_file,
        exclude_bj9=not args.include_bj9,
        enable_diversification=not args.disable_diversification,
        max_industry_positions=max(1, args.max_industry_positions),
        corr_lookback_days=max(10, args.corr_lookback_days),
        max_pair_corr=min(max(args.max_pair_corr, 0.10), 0.999),
        corr_min_obs=max(5, args.corr_min_obs),
        enable_dynamic_exit=not args.disable_dynamic_exit,
        take_profit=min(max(args.take_profit, 0.01), 0.80),
        stop_loss=min(max(args.stop_loss, 0.01), 0.50),
        trail_drawdown=min(max(args.trail_drawdown, 0.01), 0.80),
        enable_regime_risk_params=not args.disable_regime_risk_params,
        tp_normal=min(max(args.tp_normal, 0.01), 0.80),
        tp_choppy=min(max(args.tp_choppy, 0.01), 0.80),
        tp_panic=min(max(args.tp_panic, 0.01), 0.80),
        sl_normal=min(max(args.sl_normal, 0.01), 0.50),
        sl_choppy=min(max(args.sl_choppy, 0.01), 0.50),
        sl_panic=min(max(args.sl_panic, 0.01), 0.50),
        trail_normal=min(max(args.trail_normal, 0.01), 0.80),
        trail_choppy=min(max(args.trail_choppy, 0.01), 0.80),
        trail_panic=min(max(args.trail_panic, 0.01), 0.80),
        corr_normal=min(max(args.corr_normal, 0.10), 0.999),
        corr_choppy=min(max(args.corr_choppy, 0.10), 0.999),
        corr_panic=min(max(args.corr_panic, 0.10), 0.999),
        enable_risk_switch=not args.disable_risk_switch,
        risk_window=max(1, args.risk_window),
        risk_cut_win_rate=min(max(args.risk_cut_win_rate, 0.0), 1.0),
        risk_cut_avg_ret=args.risk_cut_avg_ret,
        risk_cut_factor=min(max(args.risk_cut_factor, 0.0), 1.0),
        enable_exec_constraints=not args.disable_exec_constraints,
        max_exit_delay_days=max(0, int(args.max_exit_delay_days)),
        enable_signal_quality_gate=not args.disable_signal_quality_gate,
        min_signal_quality=min(max(float(args.min_signal_quality), 0.0), 1.0),
        ml_quality_blend=min(max(float(args.ml_quality_blend), 0.0), 1.0),
        max_abs_pct_chg=max(1.0, float(args.max_abs_pct_chg)),
        enable_feature_refactor=not args.disable_feature_refactor,
        stability_blend=min(max(float(args.stability_blend), 0.0), 1.0),
        enable_feature_refactor_gate=not args.disable_feature_refactor_gate,
        min_refactor_score=min(max(float(args.min_refactor_score), 0.0), 1.0),
        min_price=max(0.0, float(args.min_price)),
        min_amount_ma20=max(0.0, float(args.min_amount_ma20)),
        liquidity_blend=min(max(float(args.liquidity_blend), 0.0), 0.5),
        adv_penalty_blend=min(max(float(args.adv_penalty_blend), 0.0), 0.5),
        industry_crowding_blend=min(max(float(args.industry_crowding_blend), 0.0), 0.5),
        optimizer_mode=str(args.optimizer_mode),
        target_capital_base=max(1.0, float(args.target_capital_base)),
        target_max_industry_weight=min(max(float(args.target_max_industry_weight), 0.0), 1.0),
        target_max_adv_participation=min(max(float(args.target_max_adv_participation), 0.0), 1.0),
        target_capacity_amount_col=str(args.target_capacity_amount_col or "amount_ma20"),
        target_capacity_amount_buffer=max(0.0, float(args.target_capacity_amount_buffer)),
        redistribute_clipped_weight=bool(args.redistribute_clipped_weight),
        impact_model=str(args.impact_model),
        impact_base_bps=max(0.0, float(args.impact_base_bps)),
        impact_participation_bps=max(0.0, float(args.impact_participation_bps)),
        impact_power=max(0.05, float(args.impact_power)),
    )
    manifest_path = _build_backtest_manifest(cfg, sys.argv)

    print("=" * 72)
    print("量化交易系统 - 组合回测")
    print("=" * 72)
    print(
        f"区间: {cfg.start or 'auto'} ~ {cfg.end or 'auto'} | TopN={cfg.top_n} | "
        f"Hold={cfg.holding_days} | RegimePos={cfg.use_regime_position} | "
        f"Engine={cfg.engine_mode} | Benchmark={cfg.benchmark_mode}"
    )

    try:
        trades_df, metrics = backtest_portfolio(cfg)
        _print_summary(metrics, cfg)
        detail_file, summary_file, json_file = _save_outputs(trades_df, metrics, cfg)
    except Exception:
        finalize_run_manifest(
            manifest_path,
            status="failed",
            step_results={"backtest": False},
            notes=["backtest_exception"],
        )
        raise

    finalize_run_manifest(
        manifest_path,
        status="success",
        step_results={
            "backtest": True,
            "trade_count": int(metrics.get("trade_count", 0.0)),
            "total_return_pct": float(metrics.get("total_return_pct", 0.0)),
        },
        notes=[
            f"detail_file={detail_file}",
            f"summary_file={summary_file}",
            f"summary_json={json_file}",
        ],
    )

    print(f"\n交易明细已保存: {detail_file}")
    print(f"汇总表已保存: {summary_file}")
    print(f"汇总JSON已保存: {json_file}")
    print(f"运行清单已保存: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
