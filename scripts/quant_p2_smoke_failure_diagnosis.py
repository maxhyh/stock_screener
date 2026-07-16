#!/usr/bin/env python3
"""Explain why a profile passed cheap alpha gates but failed P2 smoke.

This report is intentionally narrow: it compares same-window P2 smoke ledgers
for the main profile and one or more candidates, then joins the cheap
score-alpha precheck so a failed candidate is labeled before spending 90/120
day replay time.
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

BACKTEST_DIR = BASE_DIR / "output" / "backtest"
EXEC_DIR = BASE_DIR / "output" / "execution"


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


def _parse_list(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = [str(x) for x in raw]
    out: list[str] = []
    for part in parts:
        s = str(part or "").strip()
        if s:
            out.append(s)
    return list(dict.fromkeys(out))


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(value).lower()).strip("_")


def _yyyymmdd(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.notna(ts):
        return ts.strftime("%Y%m%d")
    raw = str(value or "").strip()
    return raw.replace("-", "")[:8] if raw else ""


def _date_display(value: object) -> str:
    d = _yyyymmdd(value)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""


def _latest_file(pattern: str) -> Path | None:
    matches = sorted(glob.glob(str(BACKTEST_DIR / pattern)))
    return Path(matches[-1]) if matches else None


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return pd.read_csv(path)


def _load_summary(path: str, profiles: list[str]) -> tuple[pd.DataFrame, str]:
    fp = Path(path).expanduser().resolve() if str(path or "").strip() else BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"
    df = _load_csv(fp)
    if profiles and "profile" in df.columns:
        df = df[df["profile"].astype(str).isin(profiles)].copy()
    if df.empty:
        raise RuntimeError("P2 rolling summary is empty after profile filtering")
    return df.reset_index(drop=True), str(fp)


def _best_summary_rows(summary_df: pd.DataFrame, window: int | None) -> pd.DataFrame:
    df = summary_df.copy()
    if "window" in df.columns:
        df["window"] = pd.to_numeric(df["window"], errors="coerce").fillna(0).astype(int)
        if window:
            df = df[df["window"].eq(int(window))].copy()
    if df.empty:
        return df
    sort_cols = [c for c in ["profile", "window", "objective_score", "nav_return_pct", "executed_days"] if c in df.columns]
    ascending = [True, True, False, False, False][: len(sort_cols)]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=ascending)
    return df.groupby(["profile", "window"], as_index=False).head(1).reset_index(drop=True)


def _row_for_profile(best_rows: pd.DataFrame, profile: str, window: int | None) -> pd.Series | None:
    if best_rows.empty:
        return None
    df = best_rows[best_rows["profile"].astype(str).eq(profile)].copy()
    if window and "window" in df.columns:
        df = df[pd.to_numeric(df["window"], errors="coerce").fillna(0).astype(int).eq(int(window))]
    if df.empty:
        return None
    return df.iloc[0]


def _ledger_path(channel: str) -> Path:
    return EXEC_DIR / f"{channel}_ledger.csv"


def _load_ledger(channel: str) -> pd.DataFrame:
    fp = _ledger_path(channel)
    if not fp.exists():
        raise FileNotFoundError(str(fp))
    df = pd.read_csv(fp)
    if df.empty:
        return df
    out = df.copy()
    out["signal_key"] = out["signal_date"].map(_yyyymmdd) if "signal_date" in out.columns else ""
    out["trade_key"] = out["trade_date"].map(_yyyymmdd) if "trade_date" in out.columns else ""
    nav_pre = pd.to_numeric(out.get("nav_pre", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0)
    nav_post = pd.to_numeric(out.get("nav_post", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0)
    out["execution_return"] = np.where(nav_pre.gt(0.0), nav_post / nav_pre - 1.0, 0.0)
    # P2 nav_pre/nav_post can exclude the mark-to-market gap between replay
    # rows. Use the continuous nav_post path for profile-vs-main attribution.
    path_base = nav_post.shift(1)
    if len(path_base) > 0:
        path_base.iloc[0] = nav_pre.iloc[0]
    path_base = path_base.where(path_base.gt(0.0), nav_pre)
    out["daily_return"] = np.where(path_base.gt(0.0), nav_post / path_base - 1.0, 0.0)
    return out


def _num(row: pd.Series, col: str, default: float = 0.0) -> float:
    return _safe_float(row.get(col, default), default)


def _intnum(row: pd.Series, col: str, default: int = 0) -> int:
    return _safe_int(row.get(col, default), default)


def build_relative_detail(
    summary_df: pd.DataFrame,
    *,
    main_profile: str,
    candidate_profile: str,
    window: int | None = None,
) -> pd.DataFrame:
    """Build daily same-calendar return/block comparison from two ledgers."""

    best = _best_summary_rows(summary_df, window)
    main_row = _row_for_profile(best, main_profile, window)
    cand_row = _row_for_profile(best, candidate_profile, window)
    if main_row is None or cand_row is None:
        return pd.DataFrame()
    main_ledger = _load_ledger(str(main_row.get("channel", "")))
    cand_ledger = _load_ledger(str(cand_row.get("channel", "")))
    if main_ledger.empty or cand_ledger.empty:
        return pd.DataFrame()
    main_map = {str(r.get("signal_key", "")): r for _, r in main_ledger.iterrows() if str(r.get("signal_key", ""))}
    cand_map = {str(r.get("signal_key", "")): r for _, r in cand_ledger.iterrows() if str(r.get("signal_key", ""))}
    keys = sorted(set(main_map) & set(cand_map))
    rows: list[dict[str, object]] = []
    for key in keys:
        m = main_map[key]
        c = cand_map[key]
        main_ret = _num(m, "daily_return")
        cand_ret = _num(c, "daily_return")
        rows.append(
            {
                "candidate_profile": candidate_profile,
                "main_profile": main_profile,
                "window": int(_safe_int(cand_row.get("window", window or 0), window or 0)),
                "signal_date": _date_display(key),
                "main_trade_date": _date_display(m.get("trade_date", "")),
                "candidate_trade_date": _date_display(c.get("trade_date", "")),
                "main_daily_return_pct": float(main_ret * 100.0),
                "candidate_daily_return_pct": float(cand_ret * 100.0),
                "relative_return_gap_pct": float((cand_ret - main_ret) * 100.0),
                "main_target_weight_sum": _num(m, "target_weight_sum"),
                "candidate_target_weight_sum": _num(c, "target_weight_sum"),
                "target_weight_gap": _num(c, "target_weight_sum") - _num(m, "target_weight_sum"),
                "main_broker_entry_blocks": _intnum(m, "broker_entry_not_tradable_orders"),
                "candidate_broker_entry_blocks": _intnum(c, "broker_entry_not_tradable_orders"),
                "main_broker_exit_blocks": _intnum(m, "broker_exit_not_tradable_orders"),
                "candidate_broker_exit_blocks": _intnum(c, "broker_exit_not_tradable_orders"),
                "exit_block_delta": _intnum(c, "broker_exit_not_tradable_orders")
                - _intnum(m, "broker_exit_not_tradable_orders"),
                "main_blocked_sell_current_weight": _num(m, "blocked_sell_current_weight"),
                "candidate_blocked_sell_current_weight": _num(c, "blocked_sell_current_weight"),
                "blocked_sell_weight_gap": _num(c, "blocked_sell_current_weight")
                - _num(m, "blocked_sell_current_weight"),
                "main_risk_blocked_rate_pct": _num(m, "risk_blocked_rate_pct"),
                "candidate_risk_blocked_rate_pct": _num(c, "risk_blocked_rate_pct"),
                "main_execution_state": str(m.get("execution_state", "")),
                "candidate_execution_state": str(c.get("execution_state", "")),
            }
        )
    return pd.DataFrame(rows)


def _load_precheck(path: str) -> pd.DataFrame:
    fp = Path(path).expanduser().resolve() if str(path or "").strip() else BACKTEST_DIR / "quant_p2_smoke_precheck_latest.csv"
    if not fp.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(fp)
    except Exception:
        return pd.DataFrame()


def _load_score_alpha_json(profile: str, override_paths: dict[str, str] | None = None) -> dict[str, Any]:
    if override_paths and profile in override_paths:
        fp = Path(override_paths[profile]).expanduser().resolve()
    else:
        fp = BACKTEST_DIR / f"quant_score_alpha_diagnosis_latest_{_slug(profile)}.json"
        if not fp.exists():
            fp = _latest_file(f"quant_score_alpha_diagnosis_{_slug(profile)}_*.json") or fp
    if not fp.exists():
        return {"score_alpha_file": "", "score_alpha_gate_pass": None}
    try:
        payload = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return {"score_alpha_file": str(fp), "score_alpha_gate_pass": None}
    gate = payload.get("alpha_quality_gate", {}) if isinstance(payload, dict) else {}
    evaluated = gate.get("evaluated", []) if isinstance(gate, dict) else []
    best: dict[str, Any] = {}
    if isinstance(evaluated, list) and evaluated:
        pass_rows = [x for x in evaluated if isinstance(x, dict) and bool(x.get("pass"))]
        best = dict(pass_rows[0] if pass_rows else evaluated[0])
    return {
        "score_alpha_file": str(fp),
        "score_alpha_gate_pass": bool(gate.get("pass", False)) if isinstance(gate, dict) else None,
        "score_alpha_gate_reasons": ",".join(str(x) for x in gate.get("reasons", [])) if isinstance(gate, dict) else "",
        "score_alpha_best_col": str(best.get("score_col", "")),
        "score_alpha_best_top_days": _safe_int(best.get("top_days", 0)),
        "score_alpha_best_top_mean_forward_return_pct": _safe_float(best.get("top_mean_forward_return_pct", 0.0)),
        "score_alpha_best_all_mean_forward_return_pct": _safe_float(best.get("all_mean_forward_return_pct", 0.0)),
        "score_alpha_best_top_minus_all_pct": _safe_float(best.get("top_minus_all_pct", 0.0)),
        "score_alpha_best_top_minus_bottom_pct": _safe_float(best.get("top_minus_bottom_pct", 0.0)),
        "score_alpha_best_rank_ic_mean": _safe_float(best.get("rank_ic_mean", 0.0)),
    }


def _score_path_overrides(raw: str) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in _parse_list(raw):
        if "=" in item:
            k, v = item.split("=", 1)
            profile = k.strip()
            path = v.strip()
            if profile and path:
                overrides[profile] = path
    return overrides


def _precheck_row(precheck_df: pd.DataFrame, profile: str) -> dict[str, object]:
    if precheck_df.empty or "profile" not in precheck_df.columns:
        return {"p2_smoke_precheck_decision": "", "p2_smoke_precheck_reason": ""}
    rows = precheck_df[precheck_df["profile"].astype(str).eq(profile)]
    if rows.empty:
        return {"p2_smoke_precheck_decision": "", "p2_smoke_precheck_reason": ""}
    row = rows.iloc[0]
    return {
        "p2_smoke_precheck_decision": str(row.get("decision", "")),
        "p2_smoke_precheck_reason": str(row.get("reason", "")),
    }


def _failure_label(row: dict[str, object]) -> str:
    score_pass = row.get("score_alpha_gate_pass")
    nav_worse = _safe_float(row.get("candidate_nav_return_pct", 0.0)) < _safe_float(row.get("main_nav_return_pct", 0.0))
    mdd_worse = _safe_float(row.get("candidate_max_drawdown_pct", 0.0)) < _safe_float(row.get("main_max_drawdown_pct", 0.0))
    target_gap = _safe_float(row.get("candidate_target_weight_sum_mean", 0.0)) - _safe_float(
        row.get("main_target_weight_sum_mean", 0.0)
    )
    exit_worse = _safe_int(row.get("candidate_broker_exit_not_tradable_orders", 0)) > _safe_int(
        row.get("main_broker_exit_not_tradable_orders", 0)
    )
    entry_worse = _safe_int(row.get("candidate_broker_entry_not_tradable_orders", 0)) > _safe_int(
        row.get("main_broker_entry_not_tradable_orders", 0)
    )
    overlap = _safe_float(row.get("calendar_overlap_pct", 100.0), 100.0)
    if score_pass is False:
        return "score_alpha_failed"
    if overlap < 95.0:
        return "calendar_mismatch"
    if exit_worse and (nav_worse or mdd_worse):
        return "sell_trap_or_exit_block"
    if entry_worse and nav_worse:
        return "entry_tradability_block"
    if target_gap < -0.05 and nav_worse:
        return "cash_drag_or_underdeployment"
    if score_pass is True and nav_worse:
        return "score_alpha_not_executed"
    if mdd_worse:
        return "risk_quality_worse"
    return "mixed_or_not_failed"


def _summary_metrics(row: pd.Series, prefix: str) -> dict[str, object]:
    cols = [
        "nav_return_pct",
        "max_drawdown_pct",
        "target_weight_sum_mean",
        "signal_start",
        "signal_end",
        "signal_days",
        "executed_days",
        "run_failed_days",
        "broker_entry_not_tradable_orders",
        "broker_exit_not_tradable_orders",
        "blocked_sell_current_weight_max",
        "empty_signal_days",
        "executable_pool_halt_days",
    ]
    out: dict[str, object] = {}
    for col in cols:
        out[f"{prefix}_{col}"] = row.get(col, "")
    return out


def build_failure_summary(
    summary_df: pd.DataFrame,
    *,
    main_profile: str,
    candidate_profiles: list[str],
    window: int | None = None,
    precheck_df: pd.DataFrame | None = None,
    score_alpha_paths: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    best = _best_summary_rows(summary_df, window)
    main_row = _row_for_profile(best, main_profile, window)
    if main_row is None:
        raise RuntimeError(f"Missing main profile in P2 summary: {main_profile}")
    precheck_df = precheck_df if precheck_df is not None else pd.DataFrame()
    summary_rows: list[dict[str, object]] = []
    detail_frames: list[pd.DataFrame] = []
    main_ledger = _load_ledger(str(main_row.get("channel", "")))
    main_signal_days = set(main_ledger["signal_key"].astype(str)) if not main_ledger.empty else set()
    for profile in candidate_profiles:
        if profile == main_profile:
            continue
        cand_row = _row_for_profile(best, profile, window)
        if cand_row is None:
            summary_rows.append(
                {
                    "candidate_profile": profile,
                    "main_profile": main_profile,
                    "window": int(window or 0),
                    "failure_label": "missing_p2_summary",
                }
            )
            continue
        cand_ledger = _load_ledger(str(cand_row.get("channel", "")))
        cand_signal_days = set(cand_ledger["signal_key"].astype(str)) if not cand_ledger.empty else set()
        overlap = len(main_signal_days & cand_signal_days)
        union = len(main_signal_days | cand_signal_days)
        detail = build_relative_detail(summary_df, main_profile=main_profile, candidate_profile=profile, window=window)
        if not detail.empty:
            detail_frames.append(detail)
        worst = detail.sort_values("relative_return_gap_pct").head(1) if not detail.empty else pd.DataFrame()
        row: dict[str, object] = {
            "candidate_profile": profile,
            "main_profile": main_profile,
            "window": int(_safe_int(cand_row.get("window", window or 0), window or 0)),
            "calendar_overlap_days": int(overlap),
            "calendar_union_days": int(union),
            "calendar_overlap_pct": float(overlap / union * 100.0) if union else 0.0,
            "aligned_days": int(len(detail)),
            "candidate_underperform_days": int((pd.to_numeric(detail.get("relative_return_gap_pct", pd.Series(dtype=float)), errors="coerce") < 0).sum())
            if not detail.empty
            else 0,
            "relative_return_gap_sum_pct": float(pd.to_numeric(detail.get("relative_return_gap_pct", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
            if not detail.empty
            else 0.0,
            "relative_return_gap_mean_pct": float(pd.to_numeric(detail.get("relative_return_gap_pct", pd.Series(dtype=float)), errors="coerce").fillna(0.0).mean())
            if not detail.empty
            else 0.0,
            "worst_relative_signal_date": str(worst.iloc[0].get("signal_date", "")) if not worst.empty else "",
            "worst_relative_return_gap_pct": _safe_float(worst.iloc[0].get("relative_return_gap_pct", 0.0)) if not worst.empty else 0.0,
        }
        row.update(_summary_metrics(main_row, "main"))
        row.update(_summary_metrics(cand_row, "candidate"))
        row.update(_precheck_row(precheck_df, profile))
        row.update(_load_score_alpha_json(profile, score_alpha_paths))
        row["nav_gap_vs_main_pct"] = _safe_float(row.get("candidate_nav_return_pct", 0.0)) - _safe_float(
            row.get("main_nav_return_pct", 0.0)
        )
        row["mdd_gap_vs_main_pct"] = _safe_float(row.get("candidate_max_drawdown_pct", 0.0)) - _safe_float(
            row.get("main_max_drawdown_pct", 0.0)
        )
        row["target_weight_sum_gap_vs_main"] = _safe_float(row.get("candidate_target_weight_sum_mean", 0.0)) - _safe_float(
            row.get("main_target_weight_sum_mean", 0.0)
        )
        row["broker_exit_block_delta_vs_main"] = _safe_int(row.get("candidate_broker_exit_not_tradable_orders", 0)) - _safe_int(
            row.get("main_broker_exit_not_tradable_orders", 0)
        )
        row["broker_entry_block_delta_vs_main"] = _safe_int(row.get("candidate_broker_entry_not_tradable_orders", 0)) - _safe_int(
            row.get("main_broker_entry_not_tradable_orders", 0)
        )
        row["failure_label"] = _failure_label(row)
        summary_rows.append(row)
    detail_out = pd.concat(detail_frames, ignore_index=True) if detail_frames else pd.DataFrame()
    summary_out = pd.DataFrame(summary_rows)
    if not summary_out.empty:
        lead_cols = [
            "candidate_profile",
            "window",
            "failure_label",
            "p2_smoke_precheck_decision",
            "p2_smoke_precheck_reason",
            "score_alpha_gate_pass",
            "score_alpha_best_col",
            "main_nav_return_pct",
            "candidate_nav_return_pct",
            "nav_gap_vs_main_pct",
            "main_max_drawdown_pct",
            "candidate_max_drawdown_pct",
            "mdd_gap_vs_main_pct",
            "main_target_weight_sum_mean",
            "candidate_target_weight_sum_mean",
            "target_weight_sum_gap_vs_main",
            "main_broker_exit_not_tradable_orders",
            "candidate_broker_exit_not_tradable_orders",
            "broker_exit_block_delta_vs_main",
            "calendar_overlap_pct",
            "aligned_days",
            "candidate_underperform_days",
            "relative_return_gap_sum_pct",
            "worst_relative_signal_date",
            "worst_relative_return_gap_pct",
        ]
        cols = [c for c in lead_cols if c in summary_out.columns] + [c for c in summary_out.columns if c not in lead_cols]
        summary_out = summary_out[cols]
    return summary_out, detail_out


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose P2 smoke failures against the main profile")
    parser.add_argument("--p2-summary", default="", help="P2 rolling summary CSV; default latest")
    parser.add_argument("--p2-smoke-precheck", default="", help="P2 smoke precheck CSV; default latest")
    parser.add_argument("--main-profile", default="quality_regime", help="Main/default profile")
    parser.add_argument("--profiles", default="", help="Comma-separated profiles. Defaults to profiles in P2 summary")
    parser.add_argument("--window", type=int, default=60, help="P2 smoke window to diagnose")
    parser.add_argument(
        "--score-alpha-diagnosis",
        default="",
        help="Optional profile=path overrides for score-alpha JSON, comma-separated",
    )
    parser.add_argument("--write-latest", action="store_true", help="Write latest shortcut files")
    args = parser.parse_args()

    requested_profiles = _parse_list(args.profiles)
    summary_df, summary_path = _load_summary(args.p2_summary, requested_profiles)
    best = _best_summary_rows(summary_df, int(args.window) if args.window else None)
    profiles = requested_profiles or [str(x) for x in best.get("profile", pd.Series(dtype=str)).dropna().astype(str).unique()]
    if args.main_profile not in profiles:
        profiles.insert(0, args.main_profile)
    candidates = [p for p in profiles if p != args.main_profile]
    precheck_df = _load_precheck(args.p2_smoke_precheck)
    score_overrides = _score_path_overrides(args.score_alpha_diagnosis)
    summary, detail = build_failure_summary(
        summary_df,
        main_profile=str(args.main_profile),
        candidate_profiles=candidates,
        window=int(args.window) if args.window else None,
        precheck_df=precheck_df,
        score_alpha_paths=score_overrides,
    )
    if summary.empty:
        print("未生成 P2 smoke failure diagnosis；请检查 profiles/window/summary")
        return 2
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_fp = BACKTEST_DIR / f"quant_p2_smoke_failure_diagnosis_{ts}.csv"
    detail_fp = BACKTEST_DIR / f"quant_p2_smoke_failure_detail_{ts}.csv"
    meta_fp = BACKTEST_DIR / f"quant_p2_smoke_failure_diagnosis_{ts}.json"
    summary.to_csv(summary_fp, index=False, encoding="utf-8-sig")
    detail.to_csv(detail_fp, index=False, encoding="utf-8-sig")
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "p2_summary": summary_path,
        "p2_smoke_precheck": str(Path(args.p2_smoke_precheck).resolve()) if str(args.p2_smoke_precheck or "").strip() else str(BACKTEST_DIR / "quant_p2_smoke_precheck_latest.csv"),
        "main_profile": str(args.main_profile),
        "profiles": profiles,
        "window": int(args.window),
        "summary": str(summary_fp),
        "detail": str(detail_fp),
        "rows": summary.to_dict(orient="records"),
    }
    meta_fp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        summary.to_csv(BACKTEST_DIR / "quant_p2_smoke_failure_diagnosis_latest.csv", index=False, encoding="utf-8-sig")
        detail.to_csv(BACKTEST_DIR / "quant_p2_smoke_failure_detail_latest.csv", index=False, encoding="utf-8-sig")
        (BACKTEST_DIR / "quant_p2_smoke_failure_diagnosis_latest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(summary.to_string(index=False))
    print(f"p2_smoke_failure_summary={summary_fp}")
    print(f"p2_smoke_failure_detail={detail_fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
