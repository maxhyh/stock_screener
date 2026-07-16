#!/usr/bin/env python3
"""Alpha-to-execution attribution for daily A-share recommendation artifacts.

This script intentionally works from the artifacts this project actually
persists today: daily recommendation CSVs, market bars, optional risk-gate
files, and optional P2 order files. It does not pretend to reconstruct the
full raw prediction universe when only the final daily candidate list exists.
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

from utils.code_utils import normalize_ts_code, normalize_ts_code_series
from core.data import AShareMarketDataGateway
from core.risk.pretrade import load_industry_map as load_ods_industry_map

OUTPUT_DIR = BASE_DIR / "output"
BACKTEST_DIR = OUTPUT_DIR / "backtest"
EXEC_DIR = OUTPUT_DIR / "execution"
# Transitional compatibility export for downstream diagnostics. It deliberately
# has no legacy-file default; callers must pass a file explicitly or migrate to
# the ODS-loading helper in this module.
PARQUET_FILE: Path | None = None


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _parse_date(value: object) -> pd.Timestamp | None:
    s = str(value or "").strip()
    if not s:
        return None
    dt = pd.to_datetime(s, errors="coerce")
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt).normalize()


def _date_from_daily_path(path: Path) -> pd.Timestamp | None:
    stem = path.stem
    for token in stem.replace("-", "_").split("_"):
        if len(token) == 8 and token.isdigit():
            return _parse_date(token)
    return None


def _discover_daily_paths(raw_glob: str) -> list[Path]:
    patterns = [p.strip() for p in str(raw_glob or "").split(",") if p.strip()]
    if not patterns:
        patterns = ["output/daily_*.csv", "output/daily/daily_*.csv"]
    paths: list[Path] = []
    for pat in patterns:
        p = Path(pat)
        matches = glob.glob(str(p if p.is_absolute() else BASE_DIR / pat))
        paths.extend(Path(x).resolve() for x in matches)
    by_date: dict[str, Path] = {}
    for fp in sorted(set(paths)):
        d = _date_from_daily_path(fp)
        if d is None:
            continue
        key = d.strftime("%Y-%m-%d")
        old = by_date.get(key)
        if old is None or fp.stat().st_mtime >= old.stat().st_mtime:
            by_date[key] = fp
    return [by_date[k] for k in sorted(by_date)]


def _load_industry_map(asof_date: object) -> dict[str, str]:
    return load_ods_industry_map(asof_date=asof_date)


def _normalize_daily_frame(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp)
    if df.empty:
        return pd.DataFrame()
    trade_date = None
    if "日期" in df.columns:
        vals = pd.to_datetime(df["日期"], errors="coerce").dropna()
        if not vals.empty:
            trade_date = pd.Timestamp(vals.iloc[0]).normalize()
    if trade_date is None:
        trade_date = _date_from_daily_path(fp)
    if trade_date is None:
        return pd.DataFrame()

    if "代码" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["signal_date"] = trade_date
    out["code"] = normalize_ts_code_series(out["代码"])
    out = out[out["code"] != ""].copy()
    if out.empty:
        return out
    for c in ["ML评分", "质量分", "信号质量分", "重构分", "稳定性分", "流动性分", "排名", "target_weight", "建议持有天数"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    if "排名" not in out.columns:
        out["排名"] = np.arange(1, len(out) + 1)
    if "ML评分" not in out.columns:
        out["ML评分"] = 0.0
    if "市场状态" not in out.columns:
        out["市场状态"] = "unknown"
    out["_source_file"] = str(fp)
    return out.reset_index(drop=True)


def _load_daily_recommendations(paths: list[Path], start: str = "", end: str = "") -> pd.DataFrame:
    frames = [_normalize_daily_frame(fp) for fp in paths]
    frames = [df for df in frames if not df.empty]
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
    return out.reset_index(drop=True)


def _load_market_bars(path: Path) -> pd.DataFrame:
    cols = ["ts_code", "trade_date", "open", "close", "amount"]
    df = pd.read_parquet(path, columns=cols)
    df["code"] = normalize_ts_code_series(df["ts_code"])
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.normalize()
    for c in ["open", "close", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["trade_date", "code", "open"]).sort_values(["code", "trade_date"]).reset_index(drop=True)
    return df


def _load_ods_market_bars(daily: pd.DataFrame, forward_days: int) -> tuple[pd.DataFrame, dict[str, object]]:
    """Load a bounded ODS window covering signal dates and forward labels."""
    start = pd.Timestamp(daily["signal_date"].min()).normalize()
    end = pd.Timestamp(daily["signal_date"].max()).normalize()
    bars = AShareMarketDataGateway().load_bars(
        start,
        end,
        forward_sessions=max(1, int(forward_days) + 1),
    )
    if bars.empty:
        return pd.DataFrame(), dict(bars.attrs.get("market_data_lineage", {}))
    bars["code"] = normalize_ts_code_series(bars["ts_code"])
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="coerce").dt.normalize()
    for c in ["open", "close", "amount"]:
        bars[c] = pd.to_numeric(bars[c], errors="coerce")
    bars = bars.dropna(subset=["trade_date", "code", "open"]).sort_values(["code", "trade_date"]).reset_index(drop=True)
    return bars, dict(bars.attrs.get("market_data_lineage", {}))


def _attach_forward_returns(daily: pd.DataFrame, bars: pd.DataFrame, default_horizon: int) -> pd.DataFrame:
    if daily.empty:
        return daily.copy()
    out = daily.copy()
    horizons = pd.to_numeric(out.get("建议持有天数", default_horizon), errors="coerce").fillna(default_horizon)
    out["_forward_horizon"] = horizons.clip(lower=1, upper=60).astype(int)
    bar_map: dict[str, pd.DataFrame] = {str(code): g.reset_index(drop=True) for code, g in bars.groupby("code", sort=False)}

    entry_open: list[float] = []
    exit_open: list[float] = []
    amount_signal: list[float] = []
    for _, row in out.iterrows():
        code = str(row.get("code", ""))
        d = pd.Timestamp(row.get("signal_date")).normalize()
        h = int(row.get("_forward_horizon", default_horizon))
        g = bar_map.get(code)
        if g is None or g.empty:
            entry_open.append(np.nan)
            exit_open.append(np.nan)
            amount_signal.append(np.nan)
            continue
        dates = g["trade_date"].to_numpy(dtype="datetime64[ns]")
        idx = int(np.searchsorted(dates, np.datetime64(d), side="left"))
        if idx >= len(g) or pd.Timestamp(g.loc[idx, "trade_date"]).normalize() != d:
            idx = int(np.searchsorted(dates, np.datetime64(d), side="right") - 1)
        if idx < 0:
            entry_open.append(np.nan)
            exit_open.append(np.nan)
            amount_signal.append(np.nan)
            continue
        entry_idx = idx + 1
        exit_idx = entry_idx + h
        amount_signal.append(_safe_float(g.loc[idx, "amount"], np.nan))
        if exit_idx >= len(g):
            entry_open.append(np.nan)
            exit_open.append(np.nan)
            continue
        entry_open.append(_safe_float(g.loc[entry_idx, "open"], np.nan))
        exit_open.append(_safe_float(g.loc[exit_idx, "open"], np.nan))
    out["entry_open"] = entry_open
    out["exit_open"] = exit_open
    out["amount_signal"] = amount_signal
    out["forward_return"] = out["exit_open"] / out["entry_open"] - 1.0
    out.loc[(out["entry_open"] <= 0) | (~np.isfinite(out["forward_return"])), "forward_return"] = np.nan
    return out


def _stage_frame(daily: pd.DataFrame, stage: str, top_n: int) -> tuple[pd.DataFrame, str, str, int]:
    if daily.empty:
        return daily.copy(), "ML评分", "empty", 0
    work = daily.copy()
    score_col = "ML评分"
    source = "daily_recommendation_proxy"
    available = 1
    ascending = False

    if stage == "raw_ml_top":
        score_col = "ML评分"
    elif stage == "quality_gate":
        score_col = "质量分" if "质量分" in work.columns else ("信号质量分" if "信号质量分" in work.columns else "ML评分")
        available = int(score_col != "ML评分")
    elif stage == "refactor":
        score_col = "重构分" if "重构分" in work.columns else ("稳定性分" if "稳定性分" in work.columns else "ML评分")
        available = int(score_col != "ML评分")
    elif stage == "execution_overlay":
        candidates = ["execution_overlay_score", "执行层排序覆盖分", "流动性分"]
        score_col = next((c for c in candidates if c in work.columns), "排名")
        ascending = score_col == "排名"
        available = int(score_col != "排名")
    elif stage == "optimizer":
        if "target_weight" in work.columns and pd.to_numeric(work["target_weight"], errors="coerce").fillna(0.0).gt(0).any():
            work = work[pd.to_numeric(work["target_weight"], errors="coerce").fillna(0.0) > 0].copy()
            score_col = "target_weight"
            source = "target_weight"
        else:
            score_col = "排名"
            ascending = True
            available = 0
    elif stage == "pretrade":
        score_col = "排名"
        ascending = True
        available = 0
    elif stage == "p2_fill":
        score_col = "排名"
        ascending = True
        source = "p2_orders"
    if score_col not in work.columns:
        work[score_col] = 0.0
    work[score_col] = pd.to_numeric(work[score_col], errors="coerce").fillna(0.0)
    selected = (
        work.sort_values(["signal_date", score_col], ascending=[True, ascending])
        .groupby("signal_date", group_keys=False)
        .head(max(1, int(top_n)))
        .copy()
    )
    return selected.reset_index(drop=True), score_col, source, available


def _load_blocked_codes_by_signal_date(raw_glob: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    patterns = [raw_glob] if raw_glob else [str(EXEC_DIR / "*risk_gates_*.csv")]
    for pat in patterns:
        for fp in glob.glob(str(pat)):
            try:
                df = pd.read_csv(fp)
            except Exception:
                continue
            if df.empty:
                continue
            date_col = "signal_date" if "signal_date" in df.columns else ""
            df["code_norm"] = normalize_ts_code_series(df.get("code", df.get("代码", "")))
            if not date_col:
                fallback_dt = _date_from_daily_path(Path(fp))
                if fallback_dt is None:
                    continue
                out.setdefault(fallback_dt.strftime("%Y-%m-%d"), set()).update(df["code_norm"].astype(str).tolist())
                continue
            for d, g in df.groupby(date_col):
                dt = _parse_date(d)
                if dt is None:
                    continue
                out.setdefault(dt.strftime("%Y-%m-%d"), set()).update(g["code_norm"].astype(str).tolist())
    return out


def _load_filled_codes_by_signal_date(raw_glob: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    patterns = [raw_glob] if raw_glob else [str(EXEC_DIR / "*orders_*.csv")]
    for pat in patterns:
        for fp in glob.glob(str(pat)):
            try:
                df = pd.read_csv(fp)
            except Exception:
                continue
            if df.empty or "signal_date" not in df.columns:
                continue
            status = df.get("status", "").astype(str).str.lower()
            side = df.get("side", "").astype(str).str.upper()
            work = df[status.isin(["filled", "partial"]) & side.eq("BUY")].copy()
            if work.empty:
                continue
            work["code_norm"] = normalize_ts_code_series(work.get("code", work.get("代码", "")))
            for d, g in work.groupby("signal_date"):
                dt = _parse_date(d)
                if dt is None:
                    continue
                out.setdefault(dt.strftime("%Y-%m-%d"), set()).update(g["code_norm"].astype(str).tolist())
    return out


def _apply_pretrade_stage(daily: pd.DataFrame, blocked_by_date: dict[str, set[str]], top_n: int) -> pd.DataFrame:
    if not blocked_by_date:
        return _stage_frame(daily, "optimizer", top_n)[0]
    work = daily.copy()
    keep = []
    for _, row in work.iterrows():
        d = pd.Timestamp(row["signal_date"]).strftime("%Y-%m-%d")
        keep.append(str(row["code"]) not in blocked_by_date.get(d, set()))
    work = work[keep].copy()
    return _stage_frame(work, "optimizer", top_n)[0]


def _apply_p2_fill_stage(daily: pd.DataFrame, filled_by_date: dict[str, set[str]], top_n: int) -> pd.DataFrame:
    if not filled_by_date:
        return daily.iloc[0:0].copy()
    keep = []
    for _, row in daily.iterrows():
        d = pd.Timestamp(row["signal_date"]).strftime("%Y-%m-%d")
        keep.append(str(row["code"]) in filled_by_date.get(d, set()))
    work = daily[keep].copy()
    return _stage_frame(work, "optimizer", top_n)[0]


def _rank_ic_by_day(df: pd.DataFrame, score_col: str) -> tuple[float, float]:
    vals: list[float] = []
    for _, g in df.dropna(subset=["forward_return"]).groupby("signal_date"):
        if len(g) < 3 or g[score_col].nunique(dropna=True) < 2 or g["forward_return"].nunique(dropna=True) < 2:
            continue
        ic = g[score_col].rank().corr(g["forward_return"].rank())
        if pd.notna(ic) and np.isfinite(ic):
            vals.append(float(ic))
    if not vals:
        return 0.0, 0.0
    mean = float(np.mean(vals))
    std = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
    return mean, float(mean / std) if std > 1e-12 else 0.0


def _quantile_spread_by_day(df: pd.DataFrame, score_col: str) -> float:
    spreads: list[float] = []
    for _, g in df.dropna(subset=["forward_return"]).groupby("signal_date"):
        if len(g) < 3:
            continue
        g = g.sort_values(score_col, ascending=False)
        n = max(1, int(np.ceil(len(g) / 3)))
        top = float(g.head(n)["forward_return"].mean())
        bottom = float(g.tail(n)["forward_return"].mean())
        if np.isfinite(top) and np.isfinite(bottom):
            spreads.append(top - bottom)
    return float(np.mean(spreads)) if spreads else 0.0


def _turnover_by_day(df: pd.DataFrame) -> float:
    sets: list[set[str]] = []
    for _, g in df.sort_values("signal_date").groupby("signal_date"):
        sets.append(set(g["code"].astype(str).tolist()))
    if len(sets) < 2:
        return 0.0
    vals: list[float] = []
    for prev, cur in zip(sets[:-1], sets[1:]):
        denom = max(len(prev | cur), 1)
        vals.append(1.0 - len(prev & cur) / denom)
    return float(np.mean(vals)) if vals else 0.0


def _top_industry_pct(df: pd.DataFrame) -> float:
    if df.empty or "industry" not in df.columns:
        return 0.0
    vals: list[float] = []
    for _, g in df.groupby("signal_date"):
        share = g["industry"].astype(str).value_counts(normalize=True)
        if not share.empty:
            vals.append(float(share.iloc[0] * 100.0))
    return float(np.mean(vals)) if vals else 0.0


def _summarize_subset(
    df: pd.DataFrame,
    *,
    stage: str,
    score_col: str,
    stage_source: str,
    data_available: int,
    segment: str,
    segment_value: str,
) -> dict[str, object]:
    valid = df.dropna(subset=["forward_return"]).copy()
    ic_mean, icir = _rank_ic_by_day(valid, score_col) if score_col in valid.columns else (0.0, 0.0)
    return {
        "stage": stage,
        "segment": segment,
        "segment_value": segment_value,
        "stage_source": stage_source,
        "data_available": int(data_available),
        "rows": int(len(df)),
        "valid_forward_rows": int(len(valid)),
        "days": int(valid["signal_date"].nunique()) if not valid.empty else 0,
        "mean_forward_return_pct": float(valid["forward_return"].mean() * 100.0) if not valid.empty else 0.0,
        "median_forward_return_pct": float(valid["forward_return"].median() * 100.0) if not valid.empty else 0.0,
        "hit_rate_pct": float((valid["forward_return"] > 0).mean() * 100.0) if not valid.empty else 0.0,
        "rank_ic_mean": float(ic_mean),
        "icir": float(icir),
        "quantile_spread_pct": float(_quantile_spread_by_day(valid, score_col) * 100.0) if score_col in valid.columns else 0.0,
        "turnover_proxy": float(_turnover_by_day(df)),
        "adv_loss_proxy_pct": float((df.get("unfilled_target_weight", pd.Series(dtype=float)).pipe(pd.to_numeric, errors="coerce").fillna(0.0).sum()) * 100.0)
        if "unfilled_target_weight" in df.columns
        else 0.0,
        "mean_amount_signal": float(pd.to_numeric(valid.get("amount_signal", 0.0), errors="coerce").mean()) if not valid.empty else 0.0,
        "mean_top_industry_count_weight_pct": float(_top_industry_pct(df)),
        "mean_target_weight": float(pd.to_numeric(df.get("target_weight", 0.0), errors="coerce").mean()) if "target_weight" in df.columns and not df.empty else 0.0,
    }


def _segment_rows(
    df: pd.DataFrame,
    *,
    stage: str,
    score_col: str,
    stage_source: str,
    data_available: int,
) -> list[dict[str, object]]:
    rows = [
        _summarize_subset(
            df,
            stage=stage,
            score_col=score_col,
            stage_source=stage_source,
            data_available=data_available,
            segment="overall",
            segment_value="all",
        )
    ]
    for seg_col, seg_name in [("市场状态", "market_regime"), ("industry", "industry"), ("amount_bucket", "amount_bucket")]:
        if seg_col not in df.columns:
            continue
        for value, g in df.groupby(seg_col, dropna=False):
            rows.append(
                _summarize_subset(
                    g.copy(),
                    stage=stage,
                    score_col=score_col,
                    stage_source=stage_source,
                    data_available=data_available,
                    segment=seg_name,
                    segment_value=str(value),
                )
            )
    return rows


def build_attribution(
    *,
    daily_glob: str = "",
    market_file: Path | None = None,
    start: str = "",
    end: str = "",
    forward_days: int = 8,
    top_n: int = 20,
    risk_glob: str = "",
    orders_glob: str = "",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    daily_paths = _discover_daily_paths(daily_glob)
    daily = _load_daily_recommendations(daily_paths, start=start, end=end)
    if daily.empty:
        raise RuntimeError("未找到可用 daily recommendation 文件")
    if market_file is not None:
        bars = _load_market_bars(market_file)
        market_lineage: dict[str, object] = {"data_source": "explicit_market_file", "path": str(market_file)}
    else:
        bars, market_lineage = _load_ods_market_bars(daily, forward_days)
    daily = _attach_forward_returns(daily, bars, default_horizon=forward_days)
    industry_map = _load_industry_map(daily["signal_date"].max())
    daily["industry"] = daily["code"].map(industry_map).fillna("未知")
    daily["amount_bucket"] = "unknown"
    amount = pd.to_numeric(daily["amount_signal"], errors="coerce")
    if amount.notna().sum() >= 4:
        daily.loc[amount.notna(), "amount_bucket"] = pd.qcut(
            amount[amount.notna()].rank(method="first"),
            q=min(4, int(amount.notna().sum())),
            labels=["amount_q1_low", "amount_q2", "amount_q3", "amount_q4_high"][: min(4, int(amount.notna().sum()))],
            duplicates="drop",
        ).astype(str)

    blocked_by_date = _load_blocked_codes_by_signal_date(risk_glob)
    filled_by_date = _load_filled_codes_by_signal_date(orders_glob)

    stage_defs = ["raw_ml_top", "quality_gate", "refactor", "execution_overlay", "optimizer"]
    rows: list[dict[str, object]] = []
    for stage in stage_defs:
        frame, score_col, source, available = _stage_frame(daily, stage, top_n)
        rows.extend(_segment_rows(frame, stage=stage, score_col=score_col, stage_source=source, data_available=available))

    pretrade = _apply_pretrade_stage(daily, blocked_by_date, top_n)
    rows.extend(
        _segment_rows(
            pretrade,
            stage="pretrade",
            score_col="target_weight" if "target_weight" in pretrade.columns else "排名",
            stage_source="risk_gate_exclusion" if blocked_by_date else "optimizer_proxy_no_risk_artifact",
            data_available=int(bool(blocked_by_date)),
        )
    )
    p2_fill = _apply_p2_fill_stage(daily, filled_by_date, top_n)
    rows.extend(
        _segment_rows(
            p2_fill,
            stage="p2_fill",
            score_col="target_weight" if "target_weight" in p2_fill.columns else "排名",
            stage_source="p2_orders" if filled_by_date else "missing_p2_order_artifact",
            data_available=int(bool(filled_by_date)),
        )
    )

    out = pd.DataFrame(rows)
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "daily_files": [str(x) for x in daily_paths],
        "daily_rows": int(len(daily)),
        "signal_start": str(daily["signal_date"].min().date()),
        "signal_end": str(daily["signal_date"].max().date()),
        "forward_days_default": int(forward_days),
        "top_n": int(top_n),
        "risk_artifact_dates": int(len(blocked_by_date)),
        "p2_fill_artifact_dates": int(len(filled_by_date)),
        "market_data": market_lineage,
        "limitation": (
            "raw_ml_top/quality_gate/refactor are computed from persisted daily recommendation rows; "
            "they are not a full-universe raw prediction reconstruction unless upstream artifacts contain those rows."
        ),
    }
    return out, meta


def main() -> int:
    p = argparse.ArgumentParser(description="Alpha-to-execution attribution diagnostics")
    p.add_argument("--daily-glob", type=str, default="", help="daily recommendation CSV glob(s), comma separated")
    p.add_argument("--market-file", type=str, default="", help="optional explicit market parquet; default is shared ODS")
    p.add_argument("--start", type=str, default="", help="signal start date")
    p.add_argument("--end", type=str, default="", help="signal end date")
    p.add_argument("--forward-days", type=int, default=8, help="default forward open-to-open horizon")
    p.add_argument("--top-n", type=int, default=20, help="stage top-N")
    p.add_argument("--risk-glob", type=str, default="", help="optional risk gate CSV glob")
    p.add_argument("--orders-glob", type=str, default="", help="optional P2 order CSV glob")
    p.add_argument("--write-latest", action="store_true", help="write latest shortcut files")
    args = p.parse_args()

    out, meta = build_attribution(
        daily_glob=args.daily_glob,
        market_file=Path(args.market_file).resolve() if args.market_file else None,
        start=args.start,
        end=args.end,
        forward_days=max(1, int(args.forward_days)),
        top_n=max(1, int(args.top_n)),
        risk_glob=args.risk_glob,
        orders_glob=args.orders_glob,
    )
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = BACKTEST_DIR / f"quant_alpha_execution_attribution_{ts}.csv"
    json_path = BACKTEST_DIR / f"quant_alpha_execution_attribution_{ts}.json"
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    payload = dict(meta)
    payload["rows"] = out.to_dict(orient="records")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        out.to_csv(BACKTEST_DIR / "quant_alpha_execution_attribution_latest.csv", index=False, encoding="utf-8-sig")
        (BACKTEST_DIR / "quant_alpha_execution_attribution_latest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(out[out["segment"] == "overall"].to_string(index=False))
    print(f"alpha_attribution_csv={csv_path}")
    print(f"alpha_attribution_json={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
