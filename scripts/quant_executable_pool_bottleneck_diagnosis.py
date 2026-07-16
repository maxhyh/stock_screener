#!/usr/bin/env python3
"""Diagnose executable-pool halt bottlenecks from P2 replay artifacts."""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

BACKTEST_DIR = BASE_DIR / "output" / "backtest"
EXEC_DIR = BASE_DIR / "output" / "execution"
DAILY_PROFILE_DIR = BASE_DIR / "output" / "daily_profiles"

DEFAULT_FOCUS_DATES = "20260324,20260325,20260326,20260330,20260403,20260407"
REASON_CATEGORIES = ("adv", "style", "tradability", "industry")


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if pd.isna(x):
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _safe_int(value: object, default: int = 0) -> int:
    return int(_safe_float(value, float(default)))


def _yyyymmdd(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raw = str(value or "").strip()
        return raw.replace("-", "")[:8] if raw else ""
    return ts.strftime("%Y%m%d")


def _parse_list(raw: str) -> list[str]:
    out: list[str] = []
    for part in str(raw or "").split(","):
        s = part.strip()
        if s:
            out.append(s)
    return list(dict.fromkeys(out))


def _latest_summary_paths(profiles: list[str]) -> list[Path]:
    paths: list[Path] = []
    common = BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"
    if common.exists():
        paths.append(common)
    for profile in profiles:
        slug = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in profile.lower()).strip("_")
        fp = BACKTEST_DIR / f"p2_rolling_replay_summary_latest_{slug}.csv"
        if fp.exists():
            paths.append(fp)
    if paths:
        return list(dict.fromkeys(paths))
    matches = sorted(glob.glob(str(BACKTEST_DIR / "p2_rolling_replay_summary_*.csv")))
    return [Path(matches[-1])] if matches else []


def _load_summary(raw: str, profiles: list[str]) -> tuple[pd.DataFrame, list[str]]:
    paths = [Path(x).expanduser().resolve() for x in _parse_list(raw)] if str(raw or "").strip() else _latest_summary_paths(profiles)
    frames: list[pd.DataFrame] = []
    used: list[str] = []
    for fp in paths:
        if not fp.exists():
            continue
        df = pd.read_csv(fp)
        if df.empty:
            continue
        frames.append(df)
        used.append(str(fp))
    if not frames:
        raise FileNotFoundError("未找到可用 P2 rolling summary")
    out = pd.concat(frames, ignore_index=True)
    if profiles and "profile" in out.columns:
        out = out[out["profile"].astype(str).isin(profiles)].copy()
    return out.reset_index(drop=True), used


def _select_best_summary_rows(summary_df: pd.DataFrame, windows: set[int] | None) -> pd.DataFrame:
    df = summary_df.copy()
    if "window" in df.columns:
        df["window"] = pd.to_numeric(df["window"], errors="coerce").fillna(0).astype(int)
        if windows:
            df = df[df["window"].isin(windows)].copy()
    sort_cols = [c for c in ["profile", "window", "objective_score", "nav_return_pct", "executed_days"] if c in df.columns]
    ascending = [True, True, False, False, False][: len(sort_cols)]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=ascending)
    group_cols = [c for c in ["profile", "window"] if c in df.columns]
    return df.groupby(group_cols, as_index=False).head(1).reset_index(drop=True) if group_cols else df


def _risk_file_for(row: pd.Series, channel: str = "") -> Path | None:
    channel = str(channel or row.get("channel", "") or "").strip()
    run_id = str(row.get("run_id", "") or "").strip()
    trade_date = _yyyymmdd(row.get("trade_date", ""))
    if not channel or not run_id or not trade_date:
        return None
    fp = EXEC_DIR / f"{channel}_risk_gates_{trade_date}_{run_id}.csv"
    return fp if fp.exists() else None


def _daily_file_for(profile: str, signal_date: str) -> Path | None:
    date = _yyyymmdd(signal_date)
    if not profile or not date:
        return None
    fp = DAILY_PROFILE_DIR / str(profile) / f"daily_{date}.csv"
    return fp if fp.exists() else None


def _reason_categories(reason: object) -> set[str]:
    s = str(reason or "").strip().lower()
    cats: set[str] = set()
    if "adv_participation" in s:
        cats.add("adv")
    if "style_" in s:
        cats.add("style")
    if "entry_not_tradable" in s or "not_tradable" in s:
        cats.add("tradability")
    if "industry_weight" in s or "post_trade_industry" in s:
        cats.add("industry")
    return cats


def _has_style_dim(reason: object, dim: str) -> bool:
    return f"style_{dim}_exposure" in str(reason or "").strip().lower()


def _weight_col(df: pd.DataFrame) -> pd.Series:
    if "target_weight" in df.columns:
        return pd.to_numeric(df["target_weight"], errors="coerce").fillna(0.0)
    if "risk_weight" in df.columns:
        return pd.to_numeric(df["risk_weight"], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=df.index, dtype=float)


def summarize_risk_rows(risk_df: pd.DataFrame | None) -> dict[str, object]:
    out: dict[str, object] = {
        "risk_file_rows": 0,
        "risk_unique_codes": 0,
        "risk_blocked_weight_sum": 0.0,
        "risk_multi_reason_rows": 0,
        "risk_no_category_rows": 0,
        "risk_adv_hit_rows": 0,
        "risk_style_hit_rows": 0,
        "risk_tradability_hit_rows": 0,
        "risk_industry_hit_rows": 0,
        "risk_style_size_hit_rows": 0,
        "risk_style_beta_hit_rows": 0,
        "risk_style_momentum_hit_rows": 0,
        "risk_style_vol_hit_rows": 0,
        "risk_adv_only_rows": 0,
        "risk_style_only_rows": 0,
        "risk_tradability_only_rows": 0,
        "risk_industry_only_rows": 0,
        "risk_recoverable_without_adv_rows": 0,
        "risk_recoverable_without_style_rows": 0,
        "risk_recoverable_without_tradability_rows": 0,
        "risk_recoverable_without_industry_rows": 0,
        "risk_recoverable_without_adv_style_rows": 0,
        "risk_adv_hit_weight_sum": 0.0,
        "risk_style_hit_weight_sum": 0.0,
        "risk_tradability_hit_weight_sum": 0.0,
        "risk_industry_hit_weight_sum": 0.0,
    }
    if risk_df is None or risk_df.empty:
        return out
    df = risk_df.copy()
    reasons = df["reasons"].astype(str) if "reasons" in df.columns else pd.Series("", index=df.index)
    cats = reasons.map(_reason_categories)
    weights = _weight_col(df)
    out["risk_file_rows"] = int(len(df))
    code_col = "code" if "code" in df.columns else ("代码" if "代码" in df.columns else "")
    out["risk_unique_codes"] = int(df[code_col].astype(str).nunique()) if code_col else int(len(df))
    out["risk_blocked_weight_sum"] = float(weights.sum())
    out["risk_multi_reason_rows"] = int(cats.map(lambda x: len(x) > 1).sum())
    out["risk_no_category_rows"] = int(cats.map(lambda x: len(x) == 0).sum())

    for cat in REASON_CATEGORIES:
        hit = cats.map(lambda x, c=cat: c in x)
        only = cats.map(lambda x, c=cat: x == {c})
        out[f"risk_{cat}_hit_rows"] = int(hit.sum())
        out[f"risk_{cat}_only_rows"] = int(only.sum())
        out[f"risk_{cat}_hit_weight_sum"] = float(weights.loc[hit].sum())
        out[f"risk_recoverable_without_{cat}_rows"] = int(only.sum())

    out["risk_recoverable_without_adv_style_rows"] = int(cats.map(lambda x: bool(x) and x.issubset({"adv", "style"})).sum())
    for dim in ["size", "beta", "momentum", "vol"]:
        out[f"risk_style_{dim}_hit_rows"] = int(reasons.map(lambda x, d=dim: _has_style_dim(x, d)).sum())
    sole_counts = {
        "adv": _safe_int(out["risk_adv_only_rows"]),
        "style": _safe_int(out["risk_style_only_rows"]),
        "tradability": _safe_int(out["risk_tradability_only_rows"]),
        "industry": _safe_int(out["risk_industry_only_rows"]),
    }
    best_cat, best_rows = max(sole_counts.items(), key=lambda kv: kv[1]) if sole_counts else ("none", 0)
    out["single_gate_relief_best"] = best_cat if best_rows > 0 else "none"
    out["single_gate_relief_rows"] = int(best_rows)
    return out


def summarize_daily_file(profile: str, signal_date: object) -> dict[str, object]:
    out: dict[str, object] = {
        "daily_file_exists": 0,
        "daily_rows": 0,
        "daily_primary_rows": 0,
        "daily_reserve_rows": 0,
        "daily_nonzero_target_rows": 0,
        "daily_target_weight_sum": 0.0,
        "daily_primary_target_weight_sum": 0.0,
        "daily_reserve_target_weight_sum": 0.0,
        "daily_zero_weight_reserve_rows": 0,
        "daily_reserve_weight_clip_rows": 0,
        "daily_max_participation_pct": 0.0,
    }
    fp = _daily_file_for(profile, _yyyymmdd(signal_date))
    if fp is None:
        return out
    try:
        df = pd.read_csv(fp)
    except Exception:
        return out
    out["daily_file_exists"] = 1
    if df.empty:
        return out
    reserve = (
        pd.to_numeric(df.get("reserve_candidate", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0).gt(0)
    )
    target = pd.to_numeric(df.get("target_weight", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0).clip(lower=0.0)
    out["daily_rows"] = int(len(df))
    out["daily_primary_rows"] = int((~reserve).sum())
    out["daily_reserve_rows"] = int(reserve.sum())
    out["daily_nonzero_target_rows"] = int(target.gt(1e-12).sum())
    out["daily_target_weight_sum"] = float(target.sum())
    out["daily_primary_target_weight_sum"] = float(target.loc[~reserve].sum())
    out["daily_reserve_target_weight_sum"] = float(target.loc[reserve].sum())
    out["daily_zero_weight_reserve_rows"] = int((reserve & target.le(1e-12)).sum())
    reasons = df.get("constraint_reason", pd.Series("", index=df.index)).astype(str)
    out["daily_reserve_weight_clip_rows"] = int(reasons.str.contains("reserve_weight_clip", na=False).sum())
    out["daily_max_participation_pct"] = float(
        pd.to_numeric(df.get("participation_pct", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0).max()
    )
    return out


def pool_bottleneck_label(row: dict[str, object]) -> str:
    state = str(row.get("execution_state", "") or "")
    if state == "empty_after_universe_filter":
        return "universe_filter_empty"
    if state == "empty_signal_raw":
        return "empty_signal_raw"
    if _safe_int(row.get("executable_pool_halt", 0)) <= 0:
        return "not_halt"
    rows = max(_safe_int(row.get("risk_file_rows", 0)), 1)
    adv = _safe_int(row.get("risk_adv_hit_rows", 0))
    style = _safe_int(row.get("risk_style_hit_rows", 0))
    tradability = _safe_int(row.get("risk_tradability_hit_rows", 0))
    industry = _safe_int(row.get("risk_industry_hit_rows", 0))
    best_single = str(row.get("single_gate_relief_best", "none"))
    best_rows = _safe_int(row.get("single_gate_relief_rows", 0))
    if best_rows / rows >= 0.50:
        return f"{best_single}_single_gate_collapse"
    if adv > 0 and style > 0 and _safe_int(row.get("risk_recoverable_without_adv_style_rows", 0)) / rows >= 0.50:
        return "adv_style_overlap_collapse"
    dominant = max(
        [("adv", adv), ("style", style), ("tradability", tradability), ("industry", industry)],
        key=lambda kv: kv[1],
    )
    if dominant[1] <= 0:
        return "unknown_gate_collapse"
    return f"{dominant[0]}_dominant_mixed"


def bottleneck_label(row: dict[str, object]) -> str:
    pool_label = str(row.get("pool_bottleneck_label", "") or pool_bottleneck_label(row))
    sell_trap = _safe_int(row.get("broker_exit_not_tradable_orders", 0)) > 0 or _safe_float(
        row.get("blocked_sell_current_weight", 0.0)
    ) > 0
    if sell_trap and pool_label not in {"not_halt", "empty_signal_raw", "universe_filter_empty"}:
        return f"sell_trap+{pool_label}"
    if sell_trap:
        return "sell_trap"
    return pool_label


def _row_from_ledger(profile: str, window: int, channel: str, row: pd.Series) -> dict[str, object]:
    risk_df: pd.DataFrame | None = None
    risk_fp = _risk_file_for(row, channel=channel)
    if risk_fp is not None:
        try:
            risk_df = pd.read_csv(risk_fp)
        except Exception:
            risk_df = None
    out: dict[str, object] = {
        "profile": profile,
        "window": int(window),
        "channel": channel,
        "signal_date": str(row.get("signal_date", "")),
        "trade_date": str(row.get("trade_date", "")),
        "run_id": str(row.get("run_id", "")),
        "execution_state": str(row.get("execution_state", "")),
        "executable_pool_halt": _safe_int(row.get("executable_pool_halt", 0)),
        "executable_pool_input_count": _safe_int(row.get("executable_pool_input_count", 0)),
        "executable_pool_kept_count": _safe_int(row.get("executable_pool_kept_count", 0)),
        "executable_pool_blocked_count": _safe_int(row.get("executable_pool_blocked_count", 0)),
        "target_weight_sum": _safe_float(row.get("target_weight_sum", 0.0)),
        "broker_entry_not_tradable_orders": _safe_int(
            row.get("broker_entry_not_tradable_orders", row.get("entry_not_tradable_orders", 0))
        ),
        "broker_exit_not_tradable_orders": _safe_int(
            row.get("broker_exit_not_tradable_orders", row.get("exit_not_tradable_orders", 0))
        ),
        "blocked_sell_current_weight": _safe_float(row.get("blocked_sell_current_weight", 0.0)),
        "blocked_sell_reserve_entry_orders": _safe_int(row.get("blocked_sell_reserve_entry_orders", 0)),
        "risk_file": str(risk_fp or ""),
    }
    out.update(summarize_daily_file(profile, row.get("signal_date", "")))
    out.update(summarize_risk_rows(risk_df))
    out["sell_trap_flag"] = int(
        _safe_int(out.get("broker_exit_not_tradable_orders", 0)) > 0
        or _safe_float(out.get("blocked_sell_current_weight", 0.0)) > 0
    )
    out["pool_bottleneck_label"] = pool_bottleneck_label(out)
    out["bottleneck_label"] = bottleneck_label(out)
    return out


def build_diagnosis(summary_df: pd.DataFrame, focus_dates: set[str], windows: set[int] | None) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    selected = _select_best_summary_rows(summary_df, windows)
    for _, srow in selected.iterrows():
        channel = str(srow.get("channel", "") or "").strip()
        if not channel:
            continue
        ledger = EXEC_DIR / f"{channel}_ledger.csv"
        if not ledger.exists():
            continue
        try:
            ldf = pd.read_csv(ledger)
        except Exception:
            continue
        if ldf.empty:
            continue
        for _, lrow in ldf.iterrows():
            sig = _yyyymmdd(lrow.get("signal_date", ""))
            trade = _yyyymmdd(lrow.get("trade_date", ""))
            is_halt = _safe_int(lrow.get("executable_pool_halt", 0)) > 0
            has_broker_block = (
                _safe_int(lrow.get("broker_entry_not_tradable_orders", lrow.get("entry_not_tradable_orders", 0))) > 0
                or _safe_int(lrow.get("broker_exit_not_tradable_orders", lrow.get("exit_not_tradable_orders", 0))) > 0
            )
            if focus_dates and sig not in focus_dates and trade not in focus_dates and not is_halt and not has_broker_block:
                continue
            rows.append(
                _row_from_ledger(
                    profile=str(srow.get("profile", "")),
                    window=_safe_int(srow.get("window", 0)),
                    channel=channel,
                    row=lrow,
                )
            )
    return pd.DataFrame(rows)


def build_summary(detail_df: pd.DataFrame) -> pd.DataFrame:
    if detail_df.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for (profile, window), g in detail_df.groupby(["profile", "window"], dropna=False):
        halt = g[pd.to_numeric(g["executable_pool_halt"], errors="coerce").fillna(0).gt(0)]
        label_base = halt if not halt.empty else g
        rows.append(
            {
                "profile": str(profile),
                "window": int(window),
                "diagnosed_days": int(len(g)),
                "halt_days": int(len(halt)),
                "sell_trap_days": int(pd.to_numeric(g["sell_trap_flag"], errors="coerce").fillna(0).gt(0).sum()),
                "daily_target_weight_sum_mean": float(pd.to_numeric(g["daily_target_weight_sum"], errors="coerce").fillna(0.0).mean()),
                "target_weight_sum_mean": float(pd.to_numeric(g["target_weight_sum"], errors="coerce").fillna(0.0).mean()),
                "risk_file_rows_sum": int(pd.to_numeric(g["risk_file_rows"], errors="coerce").fillna(0).sum()),
                "risk_adv_hit_rows_sum": int(pd.to_numeric(g["risk_adv_hit_rows"], errors="coerce").fillna(0).sum()),
                "risk_style_hit_rows_sum": int(pd.to_numeric(g["risk_style_hit_rows"], errors="coerce").fillna(0).sum()),
                "risk_tradability_hit_rows_sum": int(pd.to_numeric(g["risk_tradability_hit_rows"], errors="coerce").fillna(0).sum()),
                "risk_industry_hit_rows_sum": int(pd.to_numeric(g["risk_industry_hit_rows"], errors="coerce").fillna(0).sum()),
                "risk_adv_only_rows_sum": int(pd.to_numeric(g["risk_adv_only_rows"], errors="coerce").fillna(0).sum()),
                "risk_style_only_rows_sum": int(pd.to_numeric(g["risk_style_only_rows"], errors="coerce").fillna(0).sum()),
                "risk_recoverable_without_adv_style_rows_sum": int(
                    pd.to_numeric(g["risk_recoverable_without_adv_style_rows"], errors="coerce").fillna(0).sum()
                ),
                "dominant_pool_bottleneck": str(label_base["pool_bottleneck_label"].astype(str).mode().iloc[0])
                if not label_base.empty
                else "",
                "dominant_bottleneck": str(label_base["bottleneck_label"].astype(str).mode().iloc[0]) if not label_base.empty else "",
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Executable-pool bottleneck diagnosis")
    parser.add_argument("--p2-summary", type=str, default="", help="P2 rolling summary 文件，支持逗号分隔；默认 latest")
    parser.add_argument("--profiles", type=str, default="", help="profile 列表，逗号分隔")
    parser.add_argument("--windows", type=str, default="60,90,120", help="窗口列表，逗号分隔")
    parser.add_argument("--focus-dates", type=str, default=DEFAULT_FOCUS_DATES, help="关注日期 YYYYMMDD，逗号分隔；空=全部")
    parser.add_argument("--write-latest", action="store_true", help="写入 latest 快捷文件")
    args = parser.parse_args()

    profiles = _parse_list(args.profiles)
    windows = {int(x) for x in _parse_list(args.windows)} if str(args.windows or "").strip() else set()
    focus_dates = {_yyyymmdd(x) for x in _parse_list(args.focus_dates)}
    summary_df, used = _load_summary(args.p2_summary, profiles)
    detail = build_diagnosis(summary_df, focus_dates, windows or None)
    if detail.empty:
        print("未找到可诊断的 executable-pool / blocked 记录")
        return 2
    summary = build_summary(detail)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_fp = BACKTEST_DIR / f"quant_executable_pool_bottleneck_diagnosis_{ts}.csv"
    summary_fp = BACKTEST_DIR / f"quant_executable_pool_bottleneck_summary_{ts}.csv"
    detail.to_csv(detail_fp, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_fp, index=False, encoding="utf-8-sig")
    meta = {"created_at": ts, "used_summary_files": used, "detail": str(detail_fp), "summary": str(summary_fp)}
    meta_fp = BACKTEST_DIR / f"quant_executable_pool_bottleneck_diagnosis_{ts}.json"
    meta_fp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        detail.to_csv(BACKTEST_DIR / "quant_executable_pool_bottleneck_diagnosis_latest.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(BACKTEST_DIR / "quant_executable_pool_bottleneck_summary_latest.csv", index=False, encoding="utf-8-sig")
        (BACKTEST_DIR / "quant_executable_pool_bottleneck_diagnosis_latest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"executable-pool bottleneck detail: {detail_fp}")
    if not summary.empty:
        print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
