#!/usr/bin/env python3
"""Attribute P2 no-entry / blocked-order clusters by execution failure mode."""

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


DEFAULT_FOCUS_DATES = "20260319,20260320,20260324,20260325,20260326,20260403,20260407"


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


def _summarize_risk_file(fp: Path | None) -> dict[str, int]:
    out = {
        "risk_gate_rows": 0,
        "risk_adv_hit": 0,
        "risk_style_hit": 0,
        "risk_industry_hit": 0,
        "risk_entry_not_tradable_hit": 0,
    }
    if fp is None or not fp.exists():
        return out
    try:
        df = pd.read_csv(fp)
    except Exception:
        return out
    if df.empty or "reasons" not in df.columns:
        return out
    reasons = df["reasons"].astype(str)
    out["risk_gate_rows"] = int(len(df))
    out["risk_adv_hit"] = int(reasons.str.contains("adv_participation", na=False).sum())
    out["risk_style_hit"] = int(reasons.str.contains("style_", na=False).sum())
    out["risk_industry_hit"] = int(reasons.str.contains("industry_weight|post_trade_industry", na=False).sum())
    out["risk_entry_not_tradable_hit"] = int(reasons.str.contains("entry_not_tradable", na=False).sum())
    return out


def classify_attribution(row: dict[str, Any]) -> str:
    state = str(row.get("execution_state", "") or "")
    if state == "empty_after_universe_filter":
        return "universe_filter_empty"
    if state == "empty_signal_raw":
        return "empty_signal_raw"
    if _safe_int(row.get("broker_exit_not_tradable_orders", row.get("exit_not_tradable_orders", 0))) > 0:
        return "sell_trap"
    if _safe_float(row.get("blocked_sell_current_weight", 0.0)) > 0:
        return "sell_trap"

    adv = _safe_int(row.get("risk_adv_hit", row.get("risk_adv_limits_hit", 0)))
    style = _safe_int(row.get("risk_style_hit", row.get("risk_style_limits_hit", 0)))
    entry = _safe_int(row.get("risk_entry_not_tradable_hit", 0))
    if state == "executable_pool_halt":
        if adv > 0 and adv >= style and adv >= entry:
            return "adv_capacity_collapse"
        if style > 0 and style >= adv and style >= entry:
            return "style_gate_collapse"
        if entry > 0:
            return "tradability_collapse"
    if _safe_int(row.get("broker_entry_not_tradable_orders", row.get("entry_not_tradable_orders", 0))) > 0 or entry > 0:
        return "tradability_collapse"
    if _safe_int(row.get("empty_signal_filtered_bj9_rows", 0)) > 0 and _safe_int(row.get("empty_signal_post_filter_rows", 1)) == 0:
        return "universe_filter_empty"
    return "mixed_or_other"


def _row_from_ledger(profile: str, window: int, channel: str, row: pd.Series) -> dict[str, Any]:
    risk = _summarize_risk_file(_risk_file_for(row, channel=channel))
    out: dict[str, Any] = {
        "profile": profile,
        "window": int(window),
        "channel": channel,
        "signal_date": str(row.get("signal_date", "")),
        "trade_date": str(row.get("trade_date", "")),
        "run_id": str(row.get("run_id", "")),
        "execution_state": str(row.get("execution_state", "")),
        "raw_candidate_count": _safe_int(row.get("empty_signal_raw_rows", 0)),
        "post_universe_count": _safe_int(row.get("empty_signal_post_filter_rows", row.get("risk_input_count", 0))),
        "post_pretrade_count": _safe_int(row.get("risk_kept_count", 0)),
        "filtered_bj9_rows": _safe_int(row.get("empty_signal_filtered_bj9_rows", 0)),
        "filtered_st_rows": _safe_int(row.get("empty_signal_filtered_st_rows", 0)),
        "risk_input_count": _safe_int(row.get("risk_input_count", 0)),
        "risk_blocked_count": _safe_int(row.get("risk_blocked_count", 0)),
        "risk_adv_limits_hit": _safe_int(row.get("risk_adv_limits_hit", 0)),
        "risk_style_limits_hit": _safe_int(row.get("risk_style_limits_hit", 0)),
        "risk_industry_limits_hit": _safe_int(row.get("risk_industry_limits_hit", 0)),
        "risk_entry_not_tradable_hit": _safe_int(row.get("risk_entry_not_tradable_hit", 0)),
        "broker_entry_not_tradable_orders": _safe_int(
            row.get("broker_entry_not_tradable_orders", row.get("entry_not_tradable_orders", 0))
        ),
        "broker_exit_not_tradable_orders": _safe_int(
            row.get("broker_exit_not_tradable_orders", row.get("exit_not_tradable_orders", 0))
        ),
        "blocked_target_weight": _safe_float(row.get("blocked_target_weight", 0.0)),
        "entry_not_tradable_target_weight": _safe_float(row.get("entry_not_tradable_target_weight", 0.0)),
        "exit_not_tradable_target_weight": _safe_float(row.get("exit_not_tradable_target_weight", 0.0)),
        "blocked_sell_current_weight": _safe_float(row.get("blocked_sell_current_weight", 0.0)),
        "blocked_sell_notional": _safe_float(row.get("blocked_sell_notional", 0.0)),
        "blocked_sell_entry_risk_score_weighted_mean": _safe_float(
            row.get("blocked_sell_entry_risk_score_weighted_mean", 0.0)
        ),
        "blocked_sell_entry_tradability_safe_score_weighted_mean": _safe_float(
            row.get("blocked_sell_entry_tradability_safe_score_weighted_mean", 0.0)
        ),
        "blocked_sell_entry_exit_trap_risk_score_weighted_mean": _safe_float(
            row.get("blocked_sell_entry_exit_trap_risk_score_weighted_mean", 0.0)
        ),
        "blocked_sell_entry_exit_trap_volume_drought_risk_weighted_mean": _safe_float(
            row.get("blocked_sell_entry_exit_trap_volume_drought_risk_weighted_mean", 0.0)
        ),
        "blocked_sell_high_entry_risk_orders": _safe_int(row.get("blocked_sell_high_entry_risk_orders", 0)),
        "blocked_sell_high_entry_exit_trap_risk_orders": _safe_int(
            row.get("blocked_sell_high_entry_exit_trap_risk_orders", 0)
        ),
        "blocked_sell_high_entry_exit_trap_volume_drought_orders": _safe_int(
            row.get("blocked_sell_high_entry_exit_trap_volume_drought_orders", 0)
        ),
        "blocked_sell_low_entry_safety_orders": _safe_int(row.get("blocked_sell_low_entry_safety_orders", 0)),
        "blocked_sell_reserve_entry_orders": _safe_int(row.get("blocked_sell_reserve_entry_orders", 0)),
    }
    out.update(risk)
    out["attribution_label"] = classify_attribution(out)
    return out


def build_attribution(summary_df: pd.DataFrame, focus_dates: set[str], windows: set[int] | None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
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
            if focus_dates and sig not in focus_dates and trade not in focus_dates:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="P2 halt / blocked cluster attribution")
    parser.add_argument("--p2-summary", type=str, default="", help="P2 rolling summary 文件，支持逗号分隔；默认 latest")
    parser.add_argument("--profiles", type=str, default="", help="profile 列表，逗号分隔")
    parser.add_argument("--windows", type=str, default="60,90,120", help="窗口列表，逗号分隔")
    parser.add_argument("--focus-dates", type=str, default=DEFAULT_FOCUS_DATES, help="关注日期 YYYYMMDD，逗号分隔；空=全部")
    parser.add_argument("--write-latest", action="store_true", help="写入 latest 快捷文件")
    args = parser.parse_args()

    profiles = _parse_list(args.profiles)
    windows = {int(x) for x in _parse_list(args.windows)} if str(args.windows or "").strip() else set()
    focus_dates = {_yyyymmdd(x) for x in _parse_list(args.focus_dates)}
    focus_dates = {x for x in focus_dates if x}
    summary_df, used_paths = _load_summary(args.p2_summary, profiles)
    out_df = build_attribution(summary_df, focus_dates, windows or None)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = BACKTEST_DIR / f"quant_p2_halt_cluster_attribution_{ts}.csv"
    json_path = BACKTEST_DIR / f"quant_p2_halt_cluster_attribution_{ts}.json"
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "p2_summary_files": used_paths,
        "profiles": profiles,
        "windows": sorted(windows),
        "focus_dates": sorted(focus_dates),
        "rows": out_df.to_dict(orient="records"),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        out_df.to_csv(BACKTEST_DIR / "quant_p2_halt_cluster_attribution_latest.csv", index=False, encoding="utf-8-sig")
        (BACKTEST_DIR / "quant_p2_halt_cluster_attribution_latest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"halt cluster attribution: {csv_path}")
    if not out_df.empty:
        print(out_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
