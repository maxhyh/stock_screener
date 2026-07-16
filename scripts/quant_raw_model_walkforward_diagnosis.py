#!/usr/bin/env python3
"""Raw model label, drift, and walk-forward alpha diagnosis.

This script is a model-layer gate. It does not create profiles, does not write
daily signals, and does not save a model for production loading. It answers one
question before capacity/P2 work resumes: does a raw-universe model trained for
the execution horizon still produce positive top-bucket open-to-open alpha?
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "core"))

from core.mfts_screener import calc_indicators  # noqa: E402
from core.data.ashare_ods_loader import AShareOdsLoader  # noqa: E402
from utils.code_utils import normalize_ts_code_series  # noqa: E402
from utils.market_data_units import normalize_amount_volume_units  # noqa: E402

BACKTEST_DIR = BASE_DIR / "output" / "backtest"
# Compatibility marker for downstream diagnostic imports. It is not a market
# data path: raw-model evidence is ODS-only.
DATA_FILE = Path("")
MODEL_DIR = BASE_DIR / "models"
RAW_MODEL_FRAME_CACHE_DIR = BASE_DIR / "output" / "cache" / "raw_model_frames"
RAW_MODEL_FRAME_CACHE_VERSION = 5
RAW_PANEL_COLUMNS = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"]
RAW_MODEL_FEATURE_WARMUP_TRADING_DAYS = 252

DEFAULT_HORIZONS = [8, 10]
DEFAULT_FEATURES = [
    "atr_percent",
    "rsi",
    "bias13",
    "pos_52w",
    "rs_5d",
    "bias",
    "mom_5",
    "vol_ratio",
    "pv_corr_5",
    "pv_corr_20",
    "rs_20d",
    "z_score",
    "bb_pos",
    "mom_20",
    "volatility_ratio",
]


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _safe_int(value: object, default: int = 0) -> int:
    return int(round(_safe_float(value, float(default))))


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(value).lower()).strip("_")


def _parse_int_list(raw: str | list[int] | tuple[int, ...] | None, default: list[int]) -> list[int]:
    if raw is None:
        return list(default)
    parts = raw.split(",") if isinstance(raw, str) else [str(x) for x in raw]
    out: list[int] = []
    for part in parts:
        try:
            x = int(str(part).strip())
        except Exception:
            continue
        if x > 0 and x not in out:
            out.append(x)
    return out or list(default)


def _parse_feature_list(raw: str | None, model_file: str = "") -> list[str]:
    if raw:
        vals = [x.strip() for x in str(raw).split(",") if x.strip()]
        if vals:
            return list(dict.fromkeys(vals))
    fp = Path(model_file).expanduser().resolve() if model_file else _latest_model_file()
    if fp and fp.exists():
        try:
            payload = pickle.load(open(fp, "rb"))
            cols = payload.get("feature_cols", []) if isinstance(payload, dict) else []
            cols = [str(x) for x in cols if str(x).strip()]
            if cols:
                return list(dict.fromkeys(cols))
        except Exception:
            pass
    base = []
    for f in DEFAULT_FEATURES:
        base.append(f)
        base.append(f"{f}_cs")
    return list(dict.fromkeys(base))


def _latest_model_file() -> Path:
    files = sorted(MODEL_DIR.glob("mfts_lgbm_*.pkl"))
    return files[-1] if files else Path("")


def _feature_bases(features: list[str]) -> list[str]:
    bases = []
    for col in features:
        base = str(col)
        if base.endswith("_cs"):
            base = base[:-3]
        if base and base not in bases:
            bases.append(base)
    return bases


def _add_cross_sectional_features(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in _feature_bases(features):
        cs_col = f"{col}_cs"
        if cs_col not in features or col not in out.columns:
            continue
        vals = pd.to_numeric(out[col], errors="coerce")
        g = vals.groupby(out["trade_date"], sort=False)
        mean = g.transform("mean")
        std = g.transform("std").replace(0, np.nan)
        out[cs_col] = ((vals - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def _calc_open_to_open_labels(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    out = df.sort_values(["ts_code", "trade_date"]).copy()
    grouped = out.groupby("ts_code", observed=True, sort=False)
    next_open = grouped["open"].shift(-1)
    for h in sorted(set(int(x) for x in horizons if int(x) > 0)):
        exit_open = grouped["open"].shift(-(int(h) + 1))
        label = (pd.to_numeric(exit_open, errors="coerce") / pd.to_numeric(next_open, errors="coerce") - 1.0) * 100.0
        out[f"label_h{h}"] = label.replace([np.inf, -np.inf], np.nan)
    return out


def _iter_windows(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    train_months: int,
    test_months: int,
    step_months: int,
    allow_partial_final_test: bool = True,
):
    anchor = pd.Timestamp(start).normalize()
    idx = 0
    while True:
        train_start = anchor
        train_end = train_start + pd.DateOffset(months=int(train_months)) - pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(months=int(test_months)) - pd.Timedelta(days=1)
        if test_start > end:
            break
        partial = False
        if test_end > end:
            if not allow_partial_final_test:
                break
            test_end = pd.Timestamp(end).normalize()
            partial = True
        idx += 1
        yield {
            "fold": idx,
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "partial_final_test": bool(partial),
        }
        if partial:
            break
        anchor = anchor + pd.DateOffset(months=int(step_months))


def load_model_metadata(model_file: str = "") -> dict[str, object]:
    fp = Path(model_file).expanduser().resolve() if model_file else _latest_model_file()
    if not fp or not fp.exists():
        return {"model_file": "", "label_mode": "", "label_horizon": 0, "train_objective": ""}
    try:
        payload = pickle.load(open(fp, "rb"))
    except Exception as exc:
        return {"model_file": str(fp), "label_mode": "", "label_horizon": 0, "train_objective": "", "error": str(exc)}
    if not isinstance(payload, dict):
        return {"model_file": str(fp), "label_mode": "", "label_horizon": 0, "train_objective": ""}
    return {
        "model_file": str(fp),
        "model_timestamp": str(payload.get("timestamp", "")),
        "label_mode": str(payload.get("label_mode", "")),
        "label_horizon": _safe_int(payload.get("label_horizon", 0)),
        "train_objective": str(payload.get("train_objective", "")),
        "feature_count": len(payload.get("feature_cols", []) or []),
    }


def load_raw_market_panel(
    *,
    data_file: Path,
    start: str,
    end: str,
    include_bj9: bool,
    data_source: str = "ashare_ods",
    ashare_data_root: str = "",
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Read the ODS source into the raw market-panel schema."""
    source = str(data_source or "ashare_ods").strip().lower()
    if source != "ashare_ods":
        raise ValueError("Raw-model market data must use data_source='ashare_ods'")

    loader = AShareOdsLoader(ashare_data_root or None)
    raw = loader.load_daily_panel(start, end, include_bj9=bool(include_bj9))
    missing = [col for col in RAW_PANEL_COLUMNS if col not in raw.columns]
    if missing:
        raise RuntimeError(f"ODS daily panel is missing required columns: {','.join(missing)}")
    if raw.empty:
        raise RuntimeError(f"ODS daily_bars has no rows for {start}..{end}")
    return raw.loc[:, RAW_PANEL_COLUMNS].copy(), {
        "data_source": "ashare_ods",
        "ashare_data_root": str(loader.data_root),
        "snapshot_policy": "latest_snapshot_per_trade_date",
    }


def summarize_raw_panel(frame: pd.DataFrame) -> dict[str, object]:
    """Summarize raw-panel coverage without implying cross-source parity."""
    missing = [col for col in RAW_PANEL_COLUMNS if col not in frame.columns]
    dates = pd.to_datetime(frame.get("trade_date", pd.Series(dtype=object)), errors="coerce")
    codes = frame.get("ts_code", pd.Series(dtype=object)).astype(str).str.strip()
    null_rows = int(frame[RAW_PANEL_COLUMNS].isna().any(axis=1).sum()) if not missing else int(len(frame))
    return {
        "rows": int(len(frame)),
        "trade_dates": int(dates.dt.normalize().nunique()),
        "unique_codes": int(codes.replace("", np.nan).nunique()),
        "date_min": str(dates.min().date()) if dates.notna().any() else "",
        "date_max": str(dates.max().date()) if dates.notna().any() else "",
        "missing_required_columns": missing,
        "required_column_null_rows": null_rows,
    }


def resolve_ods_market_window(
    loader: AShareOdsLoader,
    *,
    start: str,
    end: str,
    horizons: list[int],
) -> tuple[str, str]:
    """Expand an ODS request for indicator history and open-to-open labels."""
    dates = sorted(set(loader.available_trade_dates("daily_bars")))
    if not dates:
        raise RuntimeError("ODS daily_bars has no available trade dates")
    start_date = pd.Timestamp(start).strftime("%Y-%m-%d")
    end_date = pd.Timestamp(end).strftime("%Y-%m-%d")
    if not any(start_date <= date <= end_date for date in dates):
        raise RuntimeError(f"ODS daily_bars has no trade dates for {start}..{end}")

    prior = [date for date in dates if date < start_date]
    future = [date for date in dates if date > end_date]
    source_start = prior[-RAW_MODEL_FEATURE_WARMUP_TRADING_DAYS] if len(prior) >= RAW_MODEL_FEATURE_WARMUP_TRADING_DAYS else dates[0]
    label_buffer = max([int(h) for h in horizons if int(h) > 0], default=0) + 1
    source_end = future[label_buffer - 1] if len(future) >= label_buffer else dates[-1]
    return source_start, source_end


def _ods_daily_bars_snapshot_lineage(
    loader: AShareOdsLoader,
    *,
    start: str,
    end: str,
    horizons: list[int],
) -> dict[str, object]:
    """Fingerprint the exact latest daily-bar snapshots used by an ODS frame."""
    source_start, source_end = resolve_ods_market_window(loader, start=start, end=end, horizons=horizons)
    snapshots: list[dict[str, str]] = []
    for trade_date in loader.available_trade_dates("daily_bars"):
        if trade_date < source_start or trade_date > source_end:
            continue
        part = loader.latest_partition("daily_bars", trade_date)
        if part is not None:
            snapshots.append({"trade_date": trade_date, "snapshot": part.snapshot})
    digest = hashlib.sha256(json.dumps(snapshots, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "ods_source_start": source_start,
        "ods_source_end": source_end,
        "ods_daily_bars_snapshot_count": len(snapshots),
        "ods_daily_bars_snapshot_digest": digest,
    }


def load_raw_model_frame(
    *,
    data_file: Path,
    features: list[str],
    horizons: list[int],
    start: str,
    end: str,
    exclude_bj9: bool = True,
    data_source: str = "ashare_ods",
    ashare_data_root: str = "",
) -> pd.DataFrame:
    source = str(data_source or "ashare_ods").strip().lower()
    source_start = start
    source_end = end
    if source == "ashare_ods":
        source_start, source_end = resolve_ods_market_window(
            AShareOdsLoader(ashare_data_root or None),
            start=start,
            end=end,
            horizons=horizons,
        )
    raw, _ = load_raw_market_panel(
        data_file=data_file,
        data_source=source,
        start=source_start,
        end=source_end,
        include_bj9=not bool(exclude_bj9),
        ashare_data_root=ashare_data_root,
    )
    raw["trade_date"] = pd.to_datetime(raw["trade_date"].astype(str), errors="coerce").dt.normalize()
    raw["ts_code"] = normalize_ts_code_series(raw["ts_code"])
    raw = raw[raw["trade_date"].notna() & raw["ts_code"].ne("")].copy()
    if exclude_bj9:
        raw = raw[~raw["ts_code"].astype(str).str.startswith("9")].copy()
    raw = normalize_amount_volume_units(raw, date_col="trade_date", amount_col="amount", vol_col="vol")
    raw = raw.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    ind = calc_indicators(raw)
    ind["vol_ratio"] = pd.to_numeric(ind.get("vol", 0.0), errors="coerce") / pd.to_numeric(
        ind.get("vol_ma20", np.nan),
        errors="coerce",
    ).replace(0, np.nan)
    ind = _add_cross_sectional_features(ind, features)
    ind = _calc_open_to_open_labels(ind, horizons)

    s = pd.to_datetime(start, errors="coerce")
    e = pd.to_datetime(end, errors="coerce")
    if pd.notna(s):
        ind = ind[ind["trade_date"].ge(pd.Timestamp(s).normalize())].copy()
    if pd.notna(e):
        ind = ind[ind["trade_date"].le(pd.Timestamp(e).normalize())].copy()
    return ind.reset_index(drop=True)


def _raw_model_frame_cache_request(
    *,
    data_file: Path,
    data_source: str = "ashare_ods",
    ashare_data_root: str = "",
    features: list[str],
    horizons: list[int],
    start: str,
    end: str,
    exclude_bj9: bool,
) -> dict[str, object]:
    source = str(data_source or "ashare_ods").strip().lower()
    ods_root = ""
    ods_lineage: dict[str, object] = {}
    if source == "ashare_ods":
        loader = AShareOdsLoader(ashare_data_root or None)
        ods_root = str(loader.data_root.resolve())
        ods_lineage = _ods_daily_bars_snapshot_lineage(loader, start=start, end=end, horizons=horizons)
    return {
        "cache_version": RAW_MODEL_FRAME_CACHE_VERSION,
        "data_source": source,
        "market_data_input": "ashare_ods",
        "ashare_data_root": ods_root,
        "ods_snapshot_policy": "latest_snapshot_per_trade_date" if source == "ashare_ods" else "",
        "ods_feature_warmup_trading_days": RAW_MODEL_FEATURE_WARMUP_TRADING_DAYS if source == "ashare_ods" else 0,
        "ods_label_buffer_trading_days": max([int(h) for h in horizons if int(h) > 0], default=0) + 1 if source == "ashare_ods" else 0,
        **ods_lineage,
        "features": list(dict.fromkeys(str(x) for x in features)),
        "horizons": sorted(set(int(x) for x in horizons if int(x) > 0)),
        "start": str(pd.Timestamp(pd.to_datetime(start, errors="coerce")).normalize().date()) if pd.notna(pd.to_datetime(start, errors="coerce")) else "",
        "end": str(pd.Timestamp(pd.to_datetime(end, errors="coerce")).normalize().date()) if pd.notna(pd.to_datetime(end, errors="coerce")) else "",
        "exclude_bj9": bool(exclude_bj9),
    }


def _raw_model_frame_cache_path(cache_file: str, request: dict[str, object]) -> Path | None:
    raw = str(cache_file or "").strip()
    if not raw or raw.lower() in {"none", "off", "false"}:
        return None
    if raw.lower() == "auto":
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        return RAW_MODEL_FRAME_CACHE_DIR / f"raw_model_frame_{digest}.parquet"
    return Path(raw).expanduser().resolve()


def _raw_model_frame_cache_meta_path(cache_path: Path) -> Path:
    return cache_path.with_suffix(cache_path.suffix + ".json")


def _raw_model_frame_cache_matches(cache_path: Path, request: dict[str, object]) -> bool:
    meta_path = _raw_model_frame_cache_meta_path(cache_path)
    if not cache_path.exists() or not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return dict(meta.get("request", {})) == dict(request)


def load_raw_model_frame_cached(
    *,
    data_file: Path,
    data_source: str = "ashare_ods",
    ashare_data_root: str = "",
    features: list[str],
    horizons: list[int],
    start: str,
    end: str,
    exclude_bj9: bool = True,
    cache_file: str = "auto",
    builder: Any | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Load raw model frame through a metadata-validated parquet cache.

    The cache is diagnosis-only. Its metadata binds the market data file size
    and mtime, feature list, horizons, date range, BJ/9-code filter, and cache
    version so stale experiments cannot silently reuse incompatible frames.
    """

    request = _raw_model_frame_cache_request(
        data_file=Path(data_file),
        data_source=data_source,
        ashare_data_root=ashare_data_root,
        features=features,
        horizons=horizons,
        start=start,
        end=end,
        exclude_bj9=bool(exclude_bj9),
    )
    cache_path = _raw_model_frame_cache_path(cache_file, request)
    if cache_path is not None and _raw_model_frame_cache_matches(cache_path, request):
        frame = pd.read_parquet(cache_path)
        if "trade_date" in frame.columns:
            frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.normalize()
        return frame.reset_index(drop=True), {
            "cache_enabled": True,
            "cache_hit": True,
            "cache_file": str(cache_path),
            "cache_request": request,
        }

    build = builder or load_raw_model_frame
    frame = build(
        data_file=Path(data_file),
        data_source=data_source,
        ashare_data_root=ashare_data_root,
        features=features,
        horizons=horizons,
        start=start,
        end=end,
        exclude_bj9=bool(exclude_bj9),
    )
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(cache_path, index=False)
        _raw_model_frame_cache_meta_path(cache_path).write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "request": request,
                    "rows": int(len(frame)),
                    "columns": list(frame.columns),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return frame.reset_index(drop=True), {
        "cache_enabled": cache_path is not None,
        "cache_hit": False,
        "cache_file": str(cache_path) if cache_path is not None else "",
        "cache_request": request,
    }


def _sample_rows(df: pd.DataFrame, max_rows: int, seed: int) -> pd.DataFrame:
    if max_rows <= 0 or len(df) <= max_rows:
        return df
    return df.sample(n=int(max_rows), random_state=int(seed)).sort_values(["trade_date", "ts_code"]).reset_index(drop=True)


def _clean_feature_label_frame(df: pd.DataFrame, features: list[str], label_col: str) -> pd.DataFrame:
    cols = ["trade_date", "ts_code", *features, label_col]
    work = df.loc[:, [c for c in cols if c in df.columns]].copy()
    for col in features + [label_col]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    need = [c for c in features + [label_col] if c in work.columns]
    return work.dropna(subset=need).reset_index(drop=True)


def _train_lgb_regression(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    *,
    features: list[str],
    label_col: str,
    num_boost_round: int,
    early_stopping_rounds: int,
    seed: int,
    num_threads: int,
) -> Any:
    import lightgbm as lgb

    params = {
        "objective": "regression",
        "metric": "rmse",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "max_depth": 8,
        "min_data_in_leaf": 100,
        "lambda_l1": 0.1,
        "lambda_l2": 0.1,
        "seed": int(seed),
        "feature_fraction_seed": int(seed),
        "bagging_seed": int(seed),
        "verbose": -1,
        "num_threads": int(num_threads),
    }
    train_data = lgb.Dataset(train_df[features].to_numpy(dtype=float), label=train_df[label_col].to_numpy(dtype=float), feature_name=features)
    callbacks = [lgb.log_evaluation(period=0)]
    valid_sets = [train_data]
    valid_names = ["train"]
    if not valid_df.empty:
        valid_data = lgb.Dataset(
            valid_df[features].to_numpy(dtype=float),
            label=valid_df[label_col].to_numpy(dtype=float),
            feature_name=features,
            reference=train_data,
        )
        valid_sets.append(valid_data)
        valid_names.append("valid")
        if early_stopping_rounds > 0:
            callbacks.append(lgb.early_stopping(stopping_rounds=int(early_stopping_rounds), verbose=False))
    return lgb.train(
        params,
        train_data,
        num_boost_round=int(num_boost_round),
        valid_sets=valid_sets,
        valid_names=valid_names,
        callbacks=callbacks,
    )


def _daily_ic(g: pd.DataFrame, score_col: str, label_col: str, direction: str) -> float | None:
    work = g[[score_col, label_col]].dropna()
    if len(work) < 20 or work[score_col].nunique(dropna=True) < 2 or work[label_col].nunique(dropna=True) < 2:
        return None
    score = work[score_col] if direction == "desc" else -work[score_col]
    ic = score.rank().corr(work[label_col].rank())
    return float(ic) if pd.notna(ic) and np.isfinite(ic) else None


def summarize_predictions(
    pred_df: pd.DataFrame,
    *,
    score_col: str = "pred",
    label_col: str = "label",
    top_n: int = 30,
    direction: str = "desc",
) -> dict[str, object]:
    if pred_df.empty:
        return {
            "rows": 0,
            "days": 0,
            "all_mean_return_pct": 0.0,
            "top_mean_return_pct": 0.0,
            "bottom_mean_return_pct": 0.0,
            "top_minus_all_pct": 0.0,
            "top_minus_bottom_pct": 0.0,
            "rank_ic_mean": 0.0,
            "icir": 0.0,
            "rank_ic_positive_day_rate_pct": 0.0,
            "top_hit_rate_pct": 0.0,
            "alpha_gate_pass": False,
        }
    work = pred_df.copy()
    work[score_col] = pd.to_numeric(work[score_col], errors="coerce")
    work[label_col] = pd.to_numeric(work[label_col], errors="coerce")
    work = work.dropna(subset=[score_col, label_col])
    if work.empty:
        return summarize_predictions(pd.DataFrame(), score_col=score_col, label_col=label_col, top_n=top_n, direction=direction)
    work["_score_eff"] = work[score_col] if direction == "desc" else -work[score_col]
    selected = (
        work.sort_values(["trade_date", "_score_eff"], ascending=[True, False])
        .groupby("trade_date", group_keys=False)
        .head(max(1, int(top_n)))
        .copy()
    )
    bottom = (
        work.sort_values(["trade_date", "_score_eff"], ascending=[True, True])
        .groupby("trade_date", group_keys=False)
        .head(max(1, int(top_n)))
        .copy()
    )
    ic_values = []
    for _, g in work.groupby("trade_date", sort=True):
        ic = _daily_ic(g, score_col, label_col, direction)
        if ic is not None:
            ic_values.append(ic)
    all_mean = _safe_float(work[label_col].mean(), 0.0)
    top_mean = _safe_float(selected[label_col].mean(), 0.0)
    bottom_mean = _safe_float(bottom[label_col].mean(), 0.0)
    ic_mean = float(np.mean(ic_values)) if ic_values else 0.0
    ic_std = float(np.std(ic_values, ddof=1)) if len(ic_values) > 1 else 0.0
    gate = top_mean > 0.0 and top_mean > all_mean and top_mean > bottom_mean and ic_mean > 0.0
    return {
        "rows": int(len(work)),
        "days": int(work["trade_date"].nunique()),
        "all_mean_return_pct": float(all_mean),
        "top_mean_return_pct": float(top_mean),
        "bottom_mean_return_pct": float(bottom_mean),
        "top_minus_all_pct": float(top_mean - all_mean),
        "top_minus_bottom_pct": float(top_mean - bottom_mean),
        "rank_ic_mean": float(ic_mean),
        "icir": float(ic_mean / ic_std) if ic_std > 1e-12 else 0.0,
        "rank_ic_positive_day_rate_pct": float(np.mean(np.array(ic_values) > 0.0) * 100.0) if ic_values else 0.0,
        "top_hit_rate_pct": float((selected[label_col] > 0.0).mean() * 100.0) if not selected.empty else 0.0,
        "alpha_gate_pass": bool(gate),
    }


def label_sample_summary(df: pd.DataFrame, *, horizons: list[int], split_name: str) -> pd.DataFrame:
    rows = []
    for h in horizons:
        col = f"label_h{int(h)}"
        vals = pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        rows.append(
            {
                "split": str(split_name),
                "horizon": int(h),
                "rows": int(len(df)),
                "valid_label_rows": int(len(vals)),
                "valid_label_rate_pct": float(len(vals) / max(len(df), 1) * 100.0),
                "label_mean_pct": _safe_float(vals.mean(), 0.0),
                "label_median_pct": _safe_float(vals.median(), 0.0),
                "label_std_pct": _safe_float(vals.std(ddof=1), 0.0),
                "label_p10_pct": _safe_float(vals.quantile(0.10), 0.0) if len(vals) else 0.0,
                "label_p90_pct": _safe_float(vals.quantile(0.90), 0.0) if len(vals) else 0.0,
                "label_positive_rate_pct": float((vals > 0.0).mean() * 100.0) if len(vals) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _psi(train_vals: pd.Series, test_vals: pd.Series, bins: int = 10) -> float:
    train = pd.to_numeric(train_vals, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    test = pd.to_numeric(test_vals, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(train) < bins * 5 or len(test) < bins * 5:
        return 0.0
    edges = np.unique(np.nanquantile(train.to_numpy(dtype=float), np.linspace(0, 1, bins + 1)))
    if len(edges) <= 2:
        return 0.0
    train_counts, _ = np.histogram(train, bins=edges)
    test_counts, _ = np.histogram(test, bins=edges)
    train_pct = np.clip(train_counts / max(train_counts.sum(), 1), 1e-6, None)
    test_pct = np.clip(test_counts / max(test_counts.sum(), 1), 1e-6, None)
    return float(np.sum((test_pct - train_pct) * np.log(test_pct / train_pct)))


def feature_drift_rows(train_df: pd.DataFrame, test_df: pd.DataFrame, *, features: list[str], max_features: int = 30) -> list[dict[str, object]]:
    rows = []
    for col in features[: max(1, int(max_features))]:
        tr = pd.to_numeric(train_df.get(col, pd.Series(dtype=float)), errors="coerce").replace([np.inf, -np.inf], np.nan)
        te = pd.to_numeric(test_df.get(col, pd.Series(dtype=float)), errors="coerce").replace([np.inf, -np.inf], np.nan)
        tr_valid = tr.dropna()
        te_valid = te.dropna()
        tr_std = _safe_float(tr_valid.std(ddof=1), 0.0)
        rows.append(
            {
                "feature": str(col),
                "train_missing_rate_pct": float(tr.isna().mean() * 100.0) if len(tr) else 0.0,
                "test_missing_rate_pct": float(te.isna().mean() * 100.0) if len(te) else 0.0,
                "train_mean": _safe_float(tr_valid.mean(), 0.0),
                "test_mean": _safe_float(te_valid.mean(), 0.0),
                "train_std": tr_std,
                "test_std": _safe_float(te_valid.std(ddof=1), 0.0),
                "std_mean_diff": float(abs(_safe_float(te_valid.mean(), 0.0) - _safe_float(tr_valid.mean(), 0.0)) / max(tr_std, 1e-12)),
                "psi": _psi(tr_valid, te_valid),
            }
        )
    return rows


def build_overall_verdict(horizon_summary: pd.DataFrame, *, min_fold_pass_rate_pct: float = 50.0) -> dict[str, object]:
    desc = horizon_summary[horizon_summary["score_direction"].astype(str).eq("desc")].copy() if not horizon_summary.empty else pd.DataFrame()
    asc = horizon_summary[horizon_summary["score_direction"].astype(str).eq("asc")].copy() if not horizon_summary.empty else pd.DataFrame()
    desc_pass = desc[
        desc.get("alpha_gate_pass", pd.Series(dtype=bool)).astype(bool)
        & (pd.to_numeric(desc.get("fold_pass_rate_pct", pd.Series(dtype=float)), errors="coerce").fillna(0.0) >= float(min_fold_pass_rate_pct))
    ].copy()
    asc_pass = asc[
        asc.get("alpha_gate_pass", pd.Series(dtype=bool)).astype(bool)
        & (pd.to_numeric(asc.get("fold_pass_rate_pct", pd.Series(dtype=float)), errors="coerce").fillna(0.0) >= float(min_fold_pass_rate_pct))
    ].copy()
    if not desc_pass.empty:
        best = desc_pass.sort_values(["rank_ic_mean", "top_minus_bottom_pct"], ascending=[False, False]).iloc[0].to_dict()
        verdict = "raw_walkforward_alpha_pass"
        action = "raw universe model passes walk-forward alpha gate; only then consider capacity-aware profile hypothesis"
    elif not asc_pass.empty:
        best = asc_pass.sort_values(["rank_ic_mean", "top_minus_bottom_pct"], ascending=[False, False]).iloc[0].to_dict()
        verdict = "score_sign_or_objective_issue"
        action = "inverted predictions pass while normal direction fails; audit label sign/objective before using model"
    else:
        pool = desc if not desc.empty else horizon_summary
        best = pool.sort_values(["rank_ic_mean", "top_minus_bottom_pct"], ascending=[False, False]).head(1)
        best = best.iloc[0].to_dict() if not best.empty else {}
        verdict = "raw_walkforward_alpha_failed"
        action = "do not create profile; inspect labels, feature drift, split stability, and model family"
    return {
        "overall_verdict": verdict,
        "recommended_next_action": action,
        "best_horizon": _safe_int(best.get("horizon", 0)),
        "best_score_direction": str(best.get("score_direction", "")),
        "best_top_mean_return_pct": _safe_float(best.get("top_mean_return_pct", 0.0)),
        "best_top_minus_all_pct": _safe_float(best.get("top_minus_all_pct", 0.0)),
        "best_top_minus_bottom_pct": _safe_float(best.get("top_minus_bottom_pct", 0.0)),
        "best_rank_ic_mean": _safe_float(best.get("rank_ic_mean", 0.0)),
        "best_fold_pass_rate_pct": _safe_float(best.get("fold_pass_rate_pct", 0.0)),
        "passed_horizons_desc": ",".join(str(int(x)) for x in desc_pass.get("horizon", pd.Series(dtype=int)).tolist()),
        "passed_horizons_asc": ",".join(str(int(x)) for x in asc_pass.get("horizon", pd.Series(dtype=int)).tolist()),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Raw model H=8/H=10 walk-forward diagnosis")
    p.add_argument("--data-source", choices=["ashare_ods"], default="ashare_ods")
    p.add_argument("--ashare-data-root", default="", help="optional shared ODS root; otherwise uses ASHARE_DATA_ROOT")
    p.add_argument("--model-file", default="", help="model package used only for feature list and metadata")
    p.add_argument("--features", default="", help="comma-separated feature override; default uses latest model feature_cols")
    p.add_argument("--horizons", default="8,10")
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2026-04-14")
    p.add_argument("--train-months", type=int, default=24)
    p.add_argument("--test-months", type=int, default=4)
    p.add_argument("--step-months", type=int, default=4)
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--max-train-rows", type=int, default=180000)
    p.add_argument("--max-test-rows", type=int, default=0, help="0 means evaluate full OOS test window")
    p.add_argument("--num-boost-round", type=int, default=160)
    p.add_argument("--early-stopping-rounds", type=int, default=25)
    p.add_argument("--valid-months", type=int, default=3)
    p.add_argument("--seed", type=int, default=20260507)
    p.add_argument("--num-threads", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    p.add_argument("--min-fold-pass-rate-pct", type=float, default=50.0)
    p.add_argument("--min-test-days", type=int, default=20)
    p.add_argument("--include-bj9", action="store_true")
    p.add_argument(
        "--feature-cache-file",
        default="auto",
        help="raw feature-frame cache path; use 'auto' for metadata-keyed cache or 'none' to disable",
    )
    p.add_argument("--no-feature-cache", action="store_true", help="disable raw feature-frame cache")
    p.add_argument("--label", default="raw_model_h8_h10_walkforward")
    p.add_argument("--write-predictions", action="store_true", help="write full OOS row-level predictions; can be very large")
    p.add_argument("--write-latest", action="store_true")
    args = p.parse_args()

    horizons = _parse_int_list(args.horizons, DEFAULT_HORIZONS)
    features = _parse_feature_list(args.features or None, args.model_file)
    model_meta = load_model_metadata(args.model_file)
    print(f"features={len(features)} horizons={horizons} latest_model_h={model_meta.get('label_horizon')}")
    print("loading and preparing raw universe frame...")
    frame, frame_cache = load_raw_model_frame_cached(
        data_file=DATA_FILE,
        data_source=str(args.data_source),
        ashare_data_root=str(args.ashare_data_root),
        features=features,
        horizons=horizons,
        start=str(args.start),
        end=str(args.end),
        exclude_bj9=not args.include_bj9,
        cache_file="none" if args.no_feature_cache else str(args.feature_cache_file),
    )
    source_panel_summary = summarize_raw_panel(frame)
    cache_msg = "hit" if frame_cache.get("cache_hit") else "miss"
    print(f"data_source={args.data_source} source_panel={json.dumps(source_panel_summary, ensure_ascii=False)}")
    print(
        f"prepared_rows={len(frame)} dates={frame['trade_date'].min()}..{frame['trade_date'].max()} "
        f"feature_cache={cache_msg}:{frame_cache.get('cache_file', '')}"
    )

    start_dt = pd.to_datetime(args.start).normalize()
    end_dt = pd.to_datetime(args.end).normalize()
    windows = list(
        _iter_windows(
            start_dt,
            end_dt,
            train_months=max(1, int(args.train_months)),
            test_months=max(1, int(args.test_months)),
            step_months=max(1, int(args.step_months)),
            allow_partial_final_test=True,
        )
    )
    if not windows:
        raise RuntimeError("No walk-forward windows generated")

    label_rows = [label_sample_summary(frame, horizons=horizons, split_name="all")]
    fold_rows: list[dict[str, object]] = []
    pred_frames: list[pd.DataFrame] = []
    drift_rows: list[dict[str, object]] = []
    usable_features = [f for f in features if f in frame.columns]
    if not usable_features:
        raise RuntimeError("No usable feature columns after indicator calculation")

    for win in windows:
        fold = int(win["fold"])
        train_mask = frame["trade_date"].between(win["train_start"], win["train_end"], inclusive="both")
        test_mask = frame["trade_date"].between(win["test_start"], win["test_end"], inclusive="both")
        train_raw = frame.loc[train_mask].copy()
        test_raw = frame.loc[test_mask].copy()
        if test_raw["trade_date"].nunique() < int(args.min_test_days):
            continue
        label_rows.append(label_sample_summary(train_raw, horizons=horizons, split_name=f"fold{fold}_train"))
        label_rows.append(label_sample_summary(test_raw, horizons=horizons, split_name=f"fold{fold}_test"))
        for h in horizons:
            label_col = f"label_h{int(h)}"
            train_work = _clean_feature_label_frame(train_raw, usable_features, label_col)
            test_work = _clean_feature_label_frame(test_raw, usable_features, label_col)
            if len(train_work) < 5000 or len(test_work) < 1000:
                continue
            valid_cut = pd.Timestamp(win["train_end"]) - pd.DateOffset(months=max(1, int(args.valid_months))) + pd.Timedelta(days=1)
            valid_work = train_work[train_work["trade_date"].ge(valid_cut)].copy()
            train_fit = train_work[train_work["trade_date"].lt(valid_cut)].copy()
            if train_fit.empty or valid_work.empty:
                train_fit = train_work.copy()
                valid_work = pd.DataFrame(columns=train_work.columns)
            train_fit = _sample_rows(train_fit, int(args.max_train_rows), int(args.seed) + fold * 100 + int(h))
            valid_work = _sample_rows(valid_work, max(0, int(args.max_train_rows // 4)), int(args.seed) + fold * 1000 + int(h))
            test_eval = _sample_rows(test_work, int(args.max_test_rows), int(args.seed) + fold * 10000 + int(h))
            print(
                f"fold={fold} h={h} train={win['train_start'].date()}..{win['train_end'].date()} "
                f"test={win['test_start'].date()}..{win['test_end'].date()} rows={len(train_fit)}/{len(valid_work)}/{len(test_eval)}"
            )
            model = _train_lgb_regression(
                train_fit,
                valid_work,
                features=usable_features,
                label_col=label_col,
                num_boost_round=max(20, int(args.num_boost_round)),
                early_stopping_rounds=max(0, int(args.early_stopping_rounds)),
                seed=int(args.seed) + fold + int(h),
                num_threads=max(1, int(args.num_threads)),
            )
            pred = test_eval[["trade_date", "ts_code", label_col]].copy()
            pred = pred.rename(columns={label_col: "label"})
            pred["pred"] = model.predict(test_eval[usable_features].to_numpy(dtype=float))
            pred["horizon"] = int(h)
            pred["fold"] = int(fold)
            pred["train_start"] = pd.Timestamp(win["train_start"]).strftime("%Y-%m-%d")
            pred["train_end"] = pd.Timestamp(win["train_end"]).strftime("%Y-%m-%d")
            pred["test_start"] = pd.Timestamp(win["test_start"]).strftime("%Y-%m-%d")
            pred["test_end"] = pd.Timestamp(win["test_end"]).strftime("%Y-%m-%d")
            pred_frames.append(pred)
            for direction in ["desc", "asc"]:
                row = summarize_predictions(pred, score_col="pred", label_col="label", top_n=int(args.top_n), direction=direction)
                fold_rows.append(
                    {
                        "fold": int(fold),
                        "horizon": int(h),
                        "score_direction": direction,
                        "train_start": pd.Timestamp(win["train_start"]).strftime("%Y-%m-%d"),
                        "train_end": pd.Timestamp(win["train_end"]).strftime("%Y-%m-%d"),
                        "test_start": pd.Timestamp(win["test_start"]).strftime("%Y-%m-%d"),
                        "test_end": pd.Timestamp(win["test_end"]).strftime("%Y-%m-%d"),
                        "partial_final_test": bool(win["partial_final_test"]),
                        "train_rows_fit": int(len(train_fit)),
                        "valid_rows": int(len(valid_work)),
                        "test_rows": int(len(test_eval)),
                        **row,
                    }
                )
            for dr in feature_drift_rows(train_fit, test_eval, features=usable_features, max_features=30):
                drift_rows.append({"fold": int(fold), "horizon": int(h), **dr})

    if not pred_frames:
        raise RuntimeError("No prediction frames generated")
    preds = pd.concat(pred_frames, ignore_index=True)
    fold_summary = pd.DataFrame(fold_rows)
    label_summary = pd.concat(label_rows, ignore_index=True) if label_rows else pd.DataFrame()
    feature_drift = pd.DataFrame(drift_rows)

    horizon_rows: list[dict[str, object]] = []
    for h in horizons:
        hp = preds[preds["horizon"].eq(int(h))].copy()
        for direction in ["desc", "asc"]:
            row = summarize_predictions(hp, score_col="pred", label_col="label", top_n=int(args.top_n), direction=direction)
            fold_side = fold_summary[
                fold_summary["horizon"].eq(int(h)) & fold_summary["score_direction"].astype(str).eq(direction)
            ]
            fold_pass_rate = float(fold_side["alpha_gate_pass"].astype(bool).mean() * 100.0) if not fold_side.empty else 0.0
            horizon_rows.append(
                {
                    "horizon": int(h),
                    "score_direction": direction,
                    "folds": int(fold_side["fold"].nunique()) if not fold_side.empty else 0,
                    "fold_pass_rate_pct": fold_pass_rate,
                    **row,
                }
            )
    horizon_summary = pd.DataFrame(horizon_rows)
    verdict = build_overall_verdict(horizon_summary, min_fold_pass_rate_pct=float(args.min_fold_pass_rate_pct))
    drift_summary = (
        feature_drift.groupby(["horizon", "feature"], as_index=False)
        .agg(
            folds=("fold", "nunique"),
            mean_std_mean_diff=("std_mean_diff", "mean"),
            max_std_mean_diff=("std_mean_diff", "max"),
            mean_psi=("psi", "mean"),
            max_psi=("psi", "max"),
            mean_test_missing_rate_pct=("test_missing_rate_pct", "mean"),
        )
        .sort_values(["horizon", "max_psi", "max_std_mean_diff"], ascending=[True, False, False])
        if not feature_drift.empty
        else pd.DataFrame()
    )

    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(str(args.label))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = BACKTEST_DIR / f"quant_raw_model_walkforward_diagnosis_{slug}_{ts}"
    files = {
        "horizon_summary": str(base.with_name(base.name + "_horizon_summary.csv")),
        "fold_summary": str(base.with_name(base.name + "_fold_summary.csv")),
        "label_summary": str(base.with_name(base.name + "_label_summary.csv")),
        "feature_drift": str(base.with_name(base.name + "_feature_drift.csv")),
        "feature_drift_summary": str(base.with_name(base.name + "_feature_drift_summary.csv")),
        "verdict": str(base.with_name(base.name + "_verdict.csv")),
        "json": str(base.with_suffix(".json")),
    }
    if args.write_predictions:
        files["predictions"] = str(base.with_name(base.name + "_predictions.csv"))
    horizon_summary.to_csv(files["horizon_summary"], index=False, encoding="utf-8-sig")
    fold_summary.to_csv(files["fold_summary"], index=False, encoding="utf-8-sig")
    label_summary.to_csv(files["label_summary"], index=False, encoding="utf-8-sig")
    feature_drift.to_csv(files["feature_drift"], index=False, encoding="utf-8-sig")
    drift_summary.to_csv(files["feature_drift_summary"], index=False, encoding="utf-8-sig")
    if args.write_predictions:
        preds.to_csv(files["predictions"], index=False, encoding="utf-8-sig")
    verdict_df = pd.DataFrame([{**verdict, **{f"source_model_{k}": v for k, v in model_meta.items()}}])
    verdict_df.to_csv(files["verdict"], index=False, encoding="utf-8-sig")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "label": str(args.label),
        "horizons": horizons,
        "features": usable_features,
        "feature_count": len(usable_features),
        "source_model": model_meta,
        "data_source": str(args.data_source),
        "ashare_data_root": str(args.ashare_data_root),
        "source_panel_summary": source_panel_summary,
        "frame_cache": frame_cache,
        "windows": [
            {k: (pd.Timestamp(v).strftime("%Y-%m-%d") if isinstance(v, pd.Timestamp) else v) for k, v in win.items()}
            for win in windows
        ],
        "args": vars(args),
        "files": files,
        "verdict": verdict,
    }
    Path(files["json"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        latest = BACKTEST_DIR / f"quant_raw_model_walkforward_diagnosis_latest_{slug}"
        mapping = {
            "horizon_summary": "_horizon_summary.csv",
            "fold_summary": "_fold_summary.csv",
            "label_summary": "_label_summary.csv",
            "feature_drift": "_feature_drift.csv",
            "feature_drift_summary": "_feature_drift_summary.csv",
            "verdict": "_verdict.csv",
        }
        if args.write_predictions:
            mapping["predictions"] = "_predictions.csv"
        for key, suffix in mapping.items():
            src = pd.read_csv(files[key]) if key in files and files[key].endswith(".csv") else None
            if src is not None:
                src.to_csv(latest.with_name(latest.name + suffix), index=False, encoding="utf-8-sig")
        latest.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        horizon_summary.to_csv(BACKTEST_DIR / "quant_raw_model_walkforward_diagnosis_latest_horizon_summary.csv", index=False, encoding="utf-8-sig")
        fold_summary.to_csv(BACKTEST_DIR / "quant_raw_model_walkforward_diagnosis_latest_fold_summary.csv", index=False, encoding="utf-8-sig")
        verdict_df.to_csv(BACKTEST_DIR / "quant_raw_model_walkforward_diagnosis_latest_verdict.csv", index=False, encoding="utf-8-sig")

    print(verdict_df.to_string(index=False))
    print(horizon_summary.to_string(index=False))
    print(f"raw_model_walkforward_verdict={files['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
