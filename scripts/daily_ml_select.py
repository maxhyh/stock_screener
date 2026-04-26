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
from datetime import datetime
import argparse
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))

from mfts_screener import calc_indicators, load_metadata
from core.risk import PreTradeRiskConfig, apply_pretrade_risk_gates, load_industry_map
from core.risk.pretrade import _load_blacklist
from core.platform.portfolio_engine import PortfolioConstraints, build_portfolio_decision
from config.settings import resolve_default_label_horizon
from utils.code_utils import normalize_ts_code, normalize_ts_code_series
from utils.market_regime import detect_market_regime
from utils.metadata_guard import evaluate_metadata_guard, load_metadata_health
from utils.execution_overlay import add_execution_overlay_scores
from utils.output_paths import ensure_output_dirs, write_dual_csv
from utils.portfolio_weights import build_score_weights, build_target_weight_checksum
from utils.signal_refactor import add_feature_refactor_columns
from utils.signal_quality import add_signal_quality_columns

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
MODEL_DIR = os.path.join(BASE_DIR, "models")
PROFILE_FILE = Path(BASE_DIR) / "config" / "quant_live_profiles.json"


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


def load_latest_model():
    """加载最新的训练模型"""
    if not os.path.exists(MODEL_DIR):
        raise FileNotFoundError(f"模型目录不存在: {MODEL_DIR}")
        
    model_files = sorted([f for f in os.listdir(MODEL_DIR) if f.startswith('mfts_lgbm_') and f.endswith('.pkl')])
    
    if not model_files:
        raise FileNotFoundError("未找到训练好的模型！请先运行 train_mfts_lgbm.py")
    
    latest_model = os.path.join(MODEL_DIR, model_files[-1])
    print(f"加载模型: {latest_model}")
    
    with open(latest_model, 'rb') as f:
        model_pkg = pickle.load(f)
    
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
    """加载市场数据，支持列裁剪与日期窗口过滤。"""
    parquet_file = os.path.join(DATA_DIR, "daily_all_5y.parquet")
    
    if not os.path.exists(parquet_file):
        raise FileNotFoundError(f"数据文件不存在: {parquet_file}")
    
    print(f"读取数据文件: {parquet_file}")
    read_cols = None
    if columns:
        read_cols = sorted(set(["ts_code", "trade_date"]) | set(columns))

    df = None
    filters_to_try: list[list[tuple[str, str, object]]] = [[]]
    if start_date is not None or end_date is not None:
        start_ts = pd.Timestamp(start_date).normalize() if start_date is not None else None
        end_ts = pd.Timestamp(end_date).normalize() if end_date is not None else None
        next_day = end_ts + pd.Timedelta(days=1) if end_ts is not None else None

        int_filters: list[tuple[str, str, object]] = []
        str_filters: list[tuple[str, str, object]] = []
        if start_ts is not None:
            int_filters.append(("trade_date", ">=", int(start_ts.strftime("%Y%m%d"))))
            str_filters.append(("trade_date", ">=", start_ts.strftime("%Y%m%d")))
        if next_day is not None:
            int_filters.append(("trade_date", "<", int(next_day.strftime("%Y%m%d"))))
            str_filters.append(("trade_date", "<", next_day.strftime("%Y%m%d")))
        filters_to_try = [int_filters, str_filters]

    for filters in filters_to_try:
        try:
            kwargs = {"columns": read_cols}
            if filters:
                kwargs["filters"] = filters
            df = pd.read_parquet(parquet_file, **kwargs)
            break
        except Exception:
            df = None

    if df is None:
        df = pd.read_parquet(parquet_file, columns=read_cols)

    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = normalize_ts_code_series(df['ts_code'])
    df = df[df['ts_code'] != ''].copy()
    if start_date is not None:
        df = df[df['trade_date'] >= pd.Timestamp(start_date).normalize()].copy()
    if end_date is not None:
        df = df[df['trade_date'] <= pd.Timestamp(end_date).normalize()].copy()
    
    return df


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
        max_style_size_exposure_abs=max(0.0, _safe_float(os.environ.get("MFTS_RISK_MAX_STYLE_SIZE_EXPOSURE_ABS", "0.0"), 0.0)),
        max_style_beta_exposure_abs=max(0.0, _safe_float(os.environ.get("MFTS_RISK_MAX_STYLE_BETA_EXPOSURE_ABS", "0.0"), 0.0)),
        max_style_momentum_exposure_abs=max(0.0, _safe_float(os.environ.get("MFTS_RISK_MAX_STYLE_MOMENTUM_EXPOSURE_ABS", "0.0"), 0.0)),
        max_style_vol_exposure_abs=max(0.0, _safe_float(os.environ.get("MFTS_RISK_MAX_STYLE_VOL_EXPOSURE_ABS", "0.0"), 0.0)),
        style_lb_short=max(5, int(_safe_float(os.environ.get("MFTS_RISK_STYLE_LB_SHORT", "20"), 20.0))),
        style_lb_beta=max(10, int(_safe_float(os.environ.get("MFTS_RISK_STYLE_LB_BETA", "60"), 60.0))),
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

    total_target = min(max(_parse_percent_text(regime_position_range, 0.60), 0.0), 1.0)
    max_single_pos = min(max(_parse_percent_text(regime_single_stock_max, 0.10), 0.0), 1.0)
    if total_target <= 0:
        total_target = 0.60
    if max_single_pos <= 0:
        max_single_pos = 0.10

    pool_fixed = int(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_N", "0"), 0.0))
    pool_mult = min(max(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_MULT", "1.0"), 1.0), 1.0), 8.0)
    pool_min_n = max(0, int(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_MIN_N", "0"), 0.0)))
    pool_step_n = max(1, int(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_STEP_N", "10"), 10.0)))
    pool_max_n_default = max(int(top_n) * 3, int(top_n), pool_min_n)
    pool_max_n = max(1, int(_safe_float(os.environ.get("MFTS_SIGNAL_PRETRADE_POOL_MAX_N", str(pool_max_n_default)), pool_max_n_default)))
    pool_max_n = min(pool_max_n, int(len(ranking_pool)))
    allow_expand = _parse_bool_like(
        os.environ.get("MFTS_SIGNAL_PRETRADE_ALLOW_EXPAND", "false"),
        default=False,
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
) -> tuple[pd.DataFrame, dict[str, object]]:
    if top_stocks is None or top_stocks.empty:
        return top_stocks, {"mode": "empty", "selected_count": 0}
    work = top_stocks.copy()
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
            score_col=ranking_col,
            code_col="ts_code",
            industry_col="industry",
            amount_col=amount_col,
            amount_buffer=amount_buffer,
            redistribute_clipped=str(profile_cfg.get("redistribute_clipped_weight", False)).strip().lower()
            in {"1", "true", "yes", "y", "on"},
            impact_model=str(profile_cfg.get("impact_model", "sqrt") or "sqrt"),
            impact_base_bps=max(0.0, _profile_float(profile_cfg, "impact_base_bps", 0.0)),
            impact_participation_bps=max(0.0, _profile_float(profile_cfg, "impact_participation_bps", 0.0)),
            impact_power=max(0.1, _profile_float(profile_cfg, "impact_power", 0.5)),
        ),
    )
    selected = decision.selected.copy()
    if selected.empty:
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
        return fallback, {"mode": optimizer_mode, "selected_count": int(len(fallback)), "fallback": True}
    return selected, {
        "mode": optimizer_mode,
        "selected_count": int(len(selected)),
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
    df = load_latest_data(
        columns=["open", "high", "low", "close", "vol", "amount", "pct_chg"],
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
    df = df.sort_values(['ts_code', 'trade_date'])
    df = calc_indicators(df)
    
    # 再次清理NaN (指标计算产生的前段NaN)
    df = df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
    
    # 添加辅助列
    df['vol_ratio'] = df['vol'] / df['vol_ma20']
    
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

    industry_map = load_industry_map(DATA_DIR)
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
    meta_dict = load_metadata()
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
    vol_anomaly = (today_df['vol_ratio'] < 0.15) | (today_df['vol_ratio'] > 5.0)

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

    # 市场状态下的分位数门槛（先收缩，再兜底回原过滤池）
    score_quantile_map = {'正常': 0.60, '震荡': 0.75, '恐慌': 0.85}
    q = score_quantile_map.get(regime['state'], 0.50)
    score_floor = float(filtered_df[ranking_col].quantile(q))
    gated_df = filtered_df[filtered_df[ranking_col] >= score_floor].copy()
    ranking_pool = gated_df if len(gated_df) >= regime_top_n else filtered_df

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
    
    # 6. 排序并选择Top N
    print(f"\n[5/5] 选择Top {regime_top_n}股票...")
    top_stocks = ranking_pool.nlargest(regime_top_n, ranking_col).copy()
    target_total_for_weights = min(max(_parse_percent_text(regime.get("position_range", "60%-80%"), 0.60), 0.0), 1.0)
    target_single_for_weights = min(max(_parse_percent_text(regime.get("single_stock_max", "10%"), 0.10), 0.0), 1.0)
    top_stocks, optimizer_info = _assign_target_weights(
        top_stocks=top_stocks,
        ranking_col=ranking_col,
        total_target_pos=target_total_for_weights,
        max_single_pos=target_single_for_weights,
        profile_cfg=profile_cfg,
    )
    eval_trade_date = pd.to_datetime(signal_risk_info.get("trade_date", target_date), errors="coerce")
    if pd.isna(eval_trade_date):
        eval_trade_date = pd.Timestamp(target_date).normalize()
    topn_pretrade_eval = _eval_topn_pretrade(
        top_stocks=top_stocks,
        ranking_col=ranking_col,
        bars_window_df=bars_window_df,
        trade_date=pd.Timestamp(eval_trade_date).normalize(),
        total_target_pos=min(max(_parse_percent_text(regime.get("position_range", "60%-80%"), 0.60), 0.0), 1.0),
        max_single_pos=min(max(_parse_percent_text(regime.get("single_stock_max", "10%"), 0.10), 0.0), 1.0),
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
    result = top_stocks[[
        'ts_code', 'name', 'close', 'pct_chg', 'ml_score', 'signal_quality', 'hybrid_score', 'stability_score', 'refactor_score',
        'liquidity_score', 'adv_capacity_score', 'industry_balance_score', 'amount_ma20', 'bias', 'z_score', 'rsi', 'vol_ratio',
        'target_weight', 'target_weight_raw', 'participation_pct', 'impact_cost_bps', 'unfilled_target_weight',
        'industry_weight_post', 'constraint_reason'
    ]].copy()
    
    result.columns = ['代码', '名称', '收盘价', '涨跌幅%', 'ML评分', '质量分', '综合分', '稳定分', '重构分',
                      '流动性分', 'ADV容量分', '行业均衡分', '成交额MA20', 'BIAS-20', 'Z-Score', 'RSI', '量比',
                      'target_weight', 'target_weight_raw', 'participation_pct', 'impact_cost_bps', 'unfilled_target_weight',
                      'industry_weight_post', 'constraint_reason']
    result['代码'] = result['代码'].astype(str).str.zfill(6)
    
    result['日期'] = target_date.strftime('%Y-%m-%d')
    result['排名'] = range(1, len(result) + 1)
    result['市场状态'] = regime['state']
    result['建议仓位'] = regime['position_range']
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
    target_weight_checksum = build_target_weight_checksum(zip(result["代码"], result["target_weight"]))
    result["target_weight_source"] = "portfolio_optimizer"
    result["target_weight_checksum"] = target_weight_checksum
    
    # 重新排列列
    result = result[['日期', '市场状态', '建议仓位', '单票上限', '建议持有天数', '排名', '代码', '名称', '收盘价', 'ML评分', '质量分', '综合分', '稳定分', '重构分',
                     '流动性分', 'ADV容量分', '行业均衡分', '成交额MA20', 'target_weight', 'target_weight_raw',
                     'participation_pct', 'impact_cost_bps', 'unfilled_target_weight', 'industry_weight_post',
                     'constraint_reason', 'target_weight_source', 'target_weight_checksum',
                     'BIAS-20', 'Z-Score', 'RSI', '量比', '涨跌幅%']]
    
    # 保留两位小数
    float_cols = ['收盘价', 'ML评分', '质量分', '综合分', '稳定分', '重构分', '流动性分', 'ADV容量分', '行业均衡分', '成交额MA20',
                  'target_weight', 'target_weight_raw', 'participation_pct', 'impact_cost_bps', 'unfilled_target_weight',
                  'industry_weight_post', 'BIAS-20', 'Z-Score', 'RSI', '量比', '涨跌幅%']
    for col in float_cols:
        decimals = 4 if col in ("质量分", "综合分", "稳定分", "重构分", "流动性分") else 2
        result[col] = result[col].round(decimals)

    # 7. 保存结果（daily 子目录 + 兼容旧路径双写）
    dirs = ensure_output_dirs(OUTPUT_DIR)
    daily_dir = dirs['daily']
    base_dir = Path(OUTPUT_DIR)
    date_str = target_date.strftime('%Y%m%d')
    output_file = daily_dir / f"daily_{date_str}.csv"
    legacy_file = base_dir / f"daily_{date_str}.csv"
    write_dual_csv(result, output_file, legacy_file, index=False, encoding='utf-8-sig')
    risk_dir = base_dir / "risk"
    risk_dir.mkdir(parents=True, exist_ok=True)
    risk_file = risk_dir / f"signal_pretrade_gates_{date_str}.csv"
    risk_latest_file = risk_dir / "signal_pretrade_gates_latest.csv"
    signal_risk_block_df.to_csv(risk_file, index=False, encoding="utf-8-sig")
    signal_risk_block_df.to_csv(risk_latest_file, index=False, encoding="utf-8-sig")
    summary_obj = {
        "date": target_date.strftime("%Y-%m-%d"),
        "market_state": regime.get("state", ""),
        "regime_top_n": int(regime_top_n),
        "ranking_col": str(ranking_col),
        "score_quantile_q": float(q),
        "score_floor": float(score_floor),
        "raw_candidates": int(len(today_df)),
        "tradable_filtered": int(len(filtered_df)),
        "score_gated": int(len(gated_df)),
        "liquidity_stage": str(liquidity_stage),
        "liquidity_blend": float(liquidity_blend),
        "adv_penalty_blend": float(adv_penalty_blend),
        "industry_crowding_blend": float(industry_crowding_blend),
        "min_price": float(profile_min_price),
        "min_amount_ma20": float(profile_min_amount_ma20),
        "pretrade": dict(signal_risk_info),
        "topn_pretrade_eval": dict(topn_pretrade_eval),
        "optimizer": dict(optimizer_info),
        "target_weight_checksum": str(target_weight_checksum),
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

    print("\n" + "=" * 70)
    print(f"Top {regime_top_n} 推荐股票")
    print("=" * 70)
    print(result.to_string(index=False))
    
    print(f"\n✅ 结果已保存: {output_file} (兼容写入: {legacy_file})")
    print(f"✅ 前置风控拦截明细: {risk_file} (latest: {risk_latest_file})")
    print(f"✅ 前置风控汇总: {summary_file} (latest: {summary_latest_file})")
    
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
    args = parser.parse_args()
    profile_cfg = load_default_profile_config()
    
    if not bool(args.disable_industry_coverage_gate):
        metadata_health = load_metadata_health(DATA_DIR)
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
            sys.exit(1)
        print(
            "✅ 元数据门禁通过: "
            f"coverage={float(metadata_gate.get('coverage_pct', 0.0)):.2f}% "
            f"| age_days={float(metadata_gate.get('age_days', 0.0)):.2f} "
            f"| file={metadata_gate.get('file', '')}"
        )

    try:
        result = select_stocks(target_date=args.date, top_n=args.top, profile_cfg=profile_cfg)
        if result is None or len(result) == 0:
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
