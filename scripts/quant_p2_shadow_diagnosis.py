#!/usr/bin/env python3
"""
P2 shadow 对比诊断。

用途：
1) 基于 p2_rolling_replay_summary 汇总多个 profile 的执行路径
2) 聚焦 NAV 路径、adv_participation 阻塞、行业集中三个维度
3) 为 shadow 挑战主档提供更可读的执行证据
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from utils.code_utils import normalize_ts_code, normalize_ts_code_series

DATA_DIR = BASE_DIR / "data"
BACKTEST_DIR = BASE_DIR / "output" / "backtest"
EXEC_DIR = BASE_DIR / "output" / "execution"
PARQUET_FILE = DATA_DIR / "daily_all_5y.parquet"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _parse_profiles(raw: str) -> list[str]:
    out: list[str] = []
    for tok in str(raw or "").split(","):
        s = tok.strip()
        if s:
            out.append(s)
    seen: set[str] = set()
    dedup: list[str] = []
    for name in out:
        if name in seen:
            continue
        seen.add(name)
        dedup.append(name)
    return dedup


def _profile_latest_summary_paths(profiles: list[str]) -> list[Path]:
    paths: list[Path] = []
    for profile in profiles:
        slug = str(profile or "").strip().lower()
        slug = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in slug).strip("_")
        if not slug:
            continue
        fp = BACKTEST_DIR / f"p2_rolling_replay_summary_latest_{slug}.csv"
        if fp.exists():
            paths.append(fp)
    return paths


def _find_latest_file(patterns: list[str]) -> Path:
    for pat in patterns:
        matches = sorted(glob.glob(str(BASE_DIR / pat)))
        if matches:
            return Path(matches[-1])
    raise FileNotFoundError(f"未找到匹配文件: {patterns}")


def _load_summary_frames(raw: str, profiles: list[str]) -> tuple[pd.DataFrame, list[str]]:
    paths: list[Path] = []
    if str(raw or "").strip():
        for part in str(raw).split(","):
            s = part.strip()
            if not s:
                continue
            paths.append(Path(s).expanduser().resolve())
    else:
        common_latest = BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"
        if common_latest.exists():
            paths.append(common_latest)
        else:
            profile_paths = _profile_latest_summary_paths(profiles)
            if profile_paths:
                paths.extend(profile_paths)
            else:
                paths.append(
                    _find_latest_file(
                        [
                            "output/backtest/p2_rolling_replay_summary_*.csv",
                        ]
                    )
            )

    frames: list[pd.DataFrame] = []
    used_paths: list[str] = []
    for fp in paths:
        if not fp.exists():
            raise FileNotFoundError(f"未找到 P2 summary: {fp}")
        df = pd.read_csv(fp)
        if df.empty:
            continue
        frames.append(df)
        used_paths.append(str(fp))
    if not frames:
        raise RuntimeError("没有可用的 P2 summary 数据")
    return pd.concat(frames, ignore_index=True), used_paths


def _load_industry_map() -> dict[str, str]:
    candidates = [DATA_DIR / "stock_info.csv", DATA_DIR / "stock_metadata.csv", DATA_DIR / "stock_basic.csv"]
    for fp in candidates:
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp, dtype={"ts_code": str})
        except Exception:
            continue
        if df.empty:
            continue
        code_col = "ts_code" if "ts_code" in df.columns else ("代码" if "代码" in df.columns else None)
        ind_col = "industry" if "industry" in df.columns else ("行业" if "行业" in df.columns else None)
        if not code_col or not ind_col:
            continue
        work = df[[code_col, ind_col]].copy()
        work["code"] = normalize_ts_code_series(work[code_col])
        work = work[work["code"] != ""].copy()
        work["industry"] = work[ind_col].astype(str).fillna("").str.strip().replace({"nan": "", "None": ""})
        return dict(zip(work["code"], work["industry"]))
    return {}


def _select_shadow_rows(summary_df: pd.DataFrame, profiles: list[str], windows: set[int] | None) -> pd.DataFrame:
    df = summary_df.copy()
    df["profile"] = df["profile"].astype(str)
    df["window"] = pd.to_numeric(df.get("window"), errors="coerce").fillna(0).astype(int)
    if profiles:
        df = df[df["profile"].isin(profiles)].copy()
    if windows:
        df = df[df["window"].isin(windows)].copy()
    if df.empty:
        raise RuntimeError("P2 summary 中没有匹配的 profile/window")
    sort_cols = ["profile", "window", "objective_score", "nav_return_pct", "executed_days"]
    asc = [True, True, False, False, False]
    df = df.sort_values(sort_cols, ascending=asc)
    return df.groupby(["profile", "window"], as_index=False).head(1).reset_index(drop=True)


def _collect_price_map(run_records: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    all_dates: set[str] = set()
    all_codes: set[str] = set()
    for rec in run_records:
        trade_date = str(rec.get("trade_date", "")).strip()
        if not trade_date:
            continue
        for code in rec.get("codes", []):
            all_dates.add(trade_date)
            all_codes.add(code)
    if (not all_dates) or (not all_codes) or (not PARQUET_FILE.exists()):
        return {}

    start = min(all_dates)
    end = max(all_dates)
    try:
        bars = pd.read_parquet(PARQUET_FILE, columns=["ts_code", "trade_date", "close"])
    except Exception:
        return {}
    if bars.empty:
        return {}
    bars["code"] = normalize_ts_code_series(bars["ts_code"])
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bars = bars[
        bars["code"].isin(all_codes)
        & bars["trade_date"].between(start, end)
        & bars["close"].notna()
    ].copy()
    if bars.empty:
        return {}
    return {
        (str(td), str(code)): float(px)
        for td, code, px in zip(bars["trade_date"], bars["code"], bars["close"])
    }


def _load_run_records(channel: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fp in sorted(EXEC_DIR.glob(f"{channel}_run_*.json")):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        positions = payload.get("positions", {})
        if not isinstance(positions, dict):
            positions = {}
        trade_date = str(payload.get("last_trade_date") or payload.get("trade_date") or "").strip()
        codes = [normalize_ts_code(x) for x in positions.keys()]
        codes = [c for c in codes if c]
        out.append(
            {
                "trade_date": trade_date,
                "positions": positions,
                "codes": codes,
                "nav": _safe_float(payload.get("nav", payload.get("nav_pre", 0.0)), 0.0),
            }
        )
    return out


def _empty_industry_summary() -> dict[str, float | str]:
    return {
        "industry_days": 0.0,
        # Backward-compatible aliases: invested-weight concentration.
        "mean_top_industry_weight_pct": 0.0,
        "worst_top_industry_weight_pct": 0.0,
        "mean_industry_hhi": 0.0,
        "worst_industry_hhi": 0.0,
        # Explicit invested-weight metrics.
        "mean_top_industry_invested_weight_pct": 0.0,
        "worst_top_industry_invested_weight_pct": 0.0,
        "mean_industry_invested_hhi": 0.0,
        "worst_industry_invested_hhi": 0.0,
        # NAV-weight metrics include cash drag, so they show whether a profile
        # is only "less concentrated" because it is under-invested.
        "mean_top_industry_nav_weight_pct": 0.0,
        "worst_top_industry_nav_weight_pct": 0.0,
        "mean_industry_nav_hhi": 0.0,
        "worst_industry_nav_hhi": 0.0,
        "dominant_industry": "",
    }


def _summarize_industry_concentration(channel: str, industry_map: dict[str, str]) -> dict[str, float]:
    records = _load_run_records(channel)
    if not records:
        return _empty_industry_summary()

    price_map = _collect_price_map(records)
    top_invested_weights: list[float] = []
    invested_hhis: list[float] = []
    top_nav_weights: list[float] = []
    nav_hhis: list[float] = []
    dominant_names: list[str] = []

    for rec in records:
        trade_date = str(rec.get("trade_date", "")).strip()
        positions = rec.get("positions", {})
        if not isinstance(positions, dict) or not positions:
            continue
        industry_values: dict[str, float] = {}
        total_value = 0.0
        for raw_code, raw_pos in positions.items():
            code = normalize_ts_code(raw_code)
            if not code:
                continue
            pos = dict(raw_pos or {})
            qty = max(0, int(_safe_float(pos.get("qty", 0), 0.0)))
            if qty <= 0:
                continue
            px = price_map.get((trade_date, code))
            if px is None or px <= 0:
                px = _safe_float(pos.get("avg_cost", 0.0), 0.0)
            if px <= 0:
                continue
            value = float(qty) * float(px)
            total_value += value
            industry = str(industry_map.get(code, "") or "未知")
            industry_values[industry] = industry_values.get(industry, 0.0) + value
        if total_value <= 0 or not industry_values:
            continue
        nav = _safe_float(rec.get("nav", 0.0), 0.0)
        nav_denom = nav if nav > 0 else total_value
        invested_shares = np.asarray([v / total_value for v in industry_values.values()], dtype=float)
        nav_shares = np.asarray([v / nav_denom for v in industry_values.values()], dtype=float)
        top_industry, top_value = max(industry_values.items(), key=lambda kv: kv[1])
        top_invested_weights.append(float(top_value / total_value * 100.0))
        invested_hhis.append(float(np.sum(np.square(invested_shares))))
        top_nav_weights.append(float(top_value / nav_denom * 100.0))
        nav_hhis.append(float(np.sum(np.square(nav_shares))))
        dominant_names.append(str(top_industry))

    if not top_invested_weights:
        return _empty_industry_summary()

    dominant = ""
    if dominant_names:
        dominant = Counter(dominant_names).most_common(1)[0][0]
    return {
        "industry_days": float(len(top_invested_weights)),
        "mean_top_industry_weight_pct": float(np.mean(top_invested_weights)),
        "worst_top_industry_weight_pct": float(np.max(top_invested_weights)),
        "mean_industry_hhi": float(np.mean(invested_hhis)),
        "worst_industry_hhi": float(np.max(invested_hhis)),
        "mean_top_industry_invested_weight_pct": float(np.mean(top_invested_weights)),
        "worst_top_industry_invested_weight_pct": float(np.max(top_invested_weights)),
        "mean_industry_invested_hhi": float(np.mean(invested_hhis)),
        "worst_industry_invested_hhi": float(np.max(invested_hhis)),
        "mean_top_industry_nav_weight_pct": float(np.mean(top_nav_weights)),
        "worst_top_industry_nav_weight_pct": float(np.max(top_nav_weights)),
        "mean_industry_nav_hhi": float(np.mean(nav_hhis)),
        "worst_industry_nav_hhi": float(np.max(nav_hhis)),
        "dominant_industry": dominant,
    }


def _summarize_adv_risk(channel: str) -> dict[str, float]:
    gate_files = sorted(EXEC_DIR.glob(f"{channel}_risk_gates_*.csv"))
    total_rows = 0
    adv_rows = 0
    adv_days = 0
    participation_vals: list[float] = []
    for fp in gate_files:
        try:
            df = pd.read_csv(fp)
        except Exception:
            continue
        if df.empty or "reasons" not in df.columns:
            continue
        total_rows += int(len(df))
        adv = df[df["reasons"].astype(str).str.contains("adv_participation", na=False)].copy()
        if not adv.empty:
            adv_days += 1
            adv_rows += int(len(adv))
            if "participation_pct" in adv.columns:
                vals = pd.to_numeric(adv["participation_pct"], errors="coerce").dropna().tolist()
                participation_vals.extend([float(x) for x in vals if np.isfinite(x)])
    return {
        "risk_gate_files": float(len(gate_files)),
        "blocked_rows_total": float(total_rows),
        "adv_blocked_rows": float(adv_rows),
        "adv_block_days": float(adv_days),
        "adv_row_share_pct": float(100.0 * adv_rows / total_rows) if total_rows > 0 else 0.0,
        "adv_participation_mean_pct": float(np.mean(participation_vals)) if participation_vals else 0.0,
        "adv_participation_max_pct": float(np.max(participation_vals)) if participation_vals else 0.0,
    }


def _profile_row(profile: str, rows: pd.DataFrame, industry_map: dict[str, str]) -> dict[str, Any]:
    nav = pd.to_numeric(rows.get("nav_return_pct", 0.0), errors="coerce").fillna(0.0)
    mdd = pd.to_numeric(rows.get("max_drawdown_pct", 0.0), errors="coerce").fillna(0.0)
    obj = pd.to_numeric(rows.get("objective_score", 0.0), errors="coerce").fillna(0.0)
    exec_days = pd.to_numeric(rows.get("executed_days", 0.0), errors="coerce").fillna(0.0)

    adv_parts: list[dict[str, float]] = []
    ind_parts: list[dict[str, float]] = []
    for channel in rows["channel"].astype(str).tolist():
        adv_parts.append(_summarize_adv_risk(channel))
        ind_parts.append(_summarize_industry_concentration(channel, industry_map))

    adv_df = pd.DataFrame(adv_parts)
    ind_df = pd.DataFrame(ind_parts)
    dominant = ""
    if not ind_df.empty and "dominant_industry" in ind_df.columns:
        names = [str(x) for x in ind_df["dominant_industry"].tolist() if str(x)]
        if names:
            dominant = Counter(names).most_common(1)[0][0]

    return {
        "profile": profile,
        "window_count": int(len(rows)),
        "windows": ",".join(str(int(x)) for x in sorted(rows["window"].astype(int).tolist())),
        "signal_start": str(rows["signal_start"].min()) if "signal_start" in rows.columns else "",
        "signal_end": str(rows["signal_end"].max()) if "signal_end" in rows.columns else "",
        "nav_return_mean_pct": float(nav.mean()),
        "nav_return_worst_pct": float(nav.min()),
        "max_drawdown_mean_pct": float(mdd.mean()),
        "max_drawdown_worst_pct": float(mdd.min()),
        "objective_score_mean": float(obj.mean()),
        "executed_days_total": float(exec_days.sum()),
        "adv_blocked_rows_total": float(pd.to_numeric(adv_df.get("adv_blocked_rows", 0.0), errors="coerce").sum()) if not adv_df.empty else 0.0,
        "adv_block_days_total": float(pd.to_numeric(adv_df.get("adv_block_days", 0.0), errors="coerce").sum()) if not adv_df.empty else 0.0,
        "adv_participation_mean_pct": float(pd.to_numeric(adv_df.get("adv_participation_mean_pct", 0.0), errors="coerce").mean()) if not adv_df.empty else 0.0,
        "adv_participation_max_pct": float(pd.to_numeric(adv_df.get("adv_participation_max_pct", 0.0), errors="coerce").max()) if not adv_df.empty else 0.0,
        "mean_top_industry_weight_pct": float(pd.to_numeric(ind_df.get("mean_top_industry_weight_pct", 0.0), errors="coerce").mean()) if not ind_df.empty else 0.0,
        "worst_top_industry_weight_pct": float(pd.to_numeric(ind_df.get("worst_top_industry_weight_pct", 0.0), errors="coerce").max()) if not ind_df.empty else 0.0,
        "mean_industry_hhi": float(pd.to_numeric(ind_df.get("mean_industry_hhi", 0.0), errors="coerce").mean()) if not ind_df.empty else 0.0,
        "worst_industry_hhi": float(pd.to_numeric(ind_df.get("worst_industry_hhi", 0.0), errors="coerce").max()) if not ind_df.empty else 0.0,
        "mean_top_industry_invested_weight_pct": float(pd.to_numeric(ind_df.get("mean_top_industry_invested_weight_pct", 0.0), errors="coerce").mean()) if not ind_df.empty else 0.0,
        "worst_top_industry_invested_weight_pct": float(pd.to_numeric(ind_df.get("worst_top_industry_invested_weight_pct", 0.0), errors="coerce").max()) if not ind_df.empty else 0.0,
        "mean_industry_invested_hhi": float(pd.to_numeric(ind_df.get("mean_industry_invested_hhi", 0.0), errors="coerce").mean()) if not ind_df.empty else 0.0,
        "worst_industry_invested_hhi": float(pd.to_numeric(ind_df.get("worst_industry_invested_hhi", 0.0), errors="coerce").max()) if not ind_df.empty else 0.0,
        "mean_top_industry_nav_weight_pct": float(pd.to_numeric(ind_df.get("mean_top_industry_nav_weight_pct", 0.0), errors="coerce").mean()) if not ind_df.empty else 0.0,
        "worst_top_industry_nav_weight_pct": float(pd.to_numeric(ind_df.get("worst_top_industry_nav_weight_pct", 0.0), errors="coerce").max()) if not ind_df.empty else 0.0,
        "mean_industry_nav_hhi": float(pd.to_numeric(ind_df.get("mean_industry_nav_hhi", 0.0), errors="coerce").mean()) if not ind_df.empty else 0.0,
        "worst_industry_nav_hhi": float(pd.to_numeric(ind_df.get("worst_industry_nav_hhi", 0.0), errors="coerce").max()) if not ind_df.empty else 0.0,
        "dominant_industry": dominant,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="P2 shadow 对比诊断")
    p.add_argument("--p2-summary", type=str, default="", help="P2 rolling replay summary 文件，支持逗号分隔多文件；默认 latest")
    p.add_argument(
        "--profiles",
        type=str,
        default=(
            "quality_regime,quality_regime_candidate,quality_regime_candidate_v2,"
            "quality_regime_candidate_v3,quality_regime_candidate_v4_exec,"
            "quality_regime_candidate_v5_capacity_guard,quality_regime_candidate_v6_liquidity_guard,"
            "quality_regime_candidate_v7_industry_balance,quality_regime_candidate_v8_reserve_pool"
        ),
        help="档位列表，逗号分隔",
    )
    p.add_argument("--windows", type=str, default="20,60,90,120", help="窗口列表，逗号分隔")
    p.add_argument("--write-latest", action="store_true", help="写入 latest 快捷文件")
    args = p.parse_args()

    profiles = _parse_profiles(args.profiles)
    windows = {int(x) for x in _parse_profiles(args.windows)} if args.windows.strip() else set()
    summary_df, summary_files = _load_summary_frames(args.p2_summary, profiles)
    selected = _select_shadow_rows(summary_df, profiles, windows)
    industry_map = _load_industry_map()

    rows: list[dict[str, Any]] = []
    for profile, g in selected.groupby("profile"):
        rows.append(_profile_row(str(profile), g.copy(), industry_map))

    out_df = pd.DataFrame(rows).sort_values(["objective_score_mean", "nav_return_mean_pct"], ascending=[False, False]).reset_index(drop=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = BACKTEST_DIR / f"quant_p2_shadow_diagnosis_{ts}.csv"
    json_path = BACKTEST_DIR / f"quant_p2_shadow_diagnosis_{ts}.json"
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "p2_summary_files": summary_files,
        "profiles": profiles,
        "windows": sorted(windows),
        "selected_rows": selected.to_dict(orient="records"),
        "rows": out_df.to_dict(orient="records"),
    }
    out_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.write_latest:
        out_df.to_csv(BACKTEST_DIR / "quant_p2_shadow_diagnosis_latest.csv", index=False, encoding="utf-8-sig")
        (BACKTEST_DIR / "quant_p2_shadow_diagnosis_latest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    _log(f"shadow 诊断表: {csv_path}")
    _log(f"shadow 诊断 JSON: {json_path}")
    if not out_df.empty:
        print(out_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
