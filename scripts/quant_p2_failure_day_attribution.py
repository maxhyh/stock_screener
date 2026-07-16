#!/usr/bin/env python3
"""Drill P2 smoke failure days down to ledger/order/risk artifacts."""

from __future__ import annotations

import argparse
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


def _yyyymmdd(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.notna(ts):
        return ts.strftime("%Y%m%d")
    raw = str(value or "").strip()
    return raw.replace("-", "")[:8] if raw else ""


def _date_display(value: object) -> str:
    d = _yyyymmdd(value)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""


def _parse_list(raw: str | None) -> list[str]:
    out: list[str] = []
    for part in str(raw or "").split(","):
        s = part.strip()
        if s:
            out.append(s)
    return list(dict.fromkeys(out))


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


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


def _summary_row(best_rows: pd.DataFrame, profile: str, window: int | None) -> pd.Series | None:
    rows = best_rows[best_rows["profile"].astype(str).eq(str(profile))].copy()
    if window and "window" in rows.columns:
        rows = rows[pd.to_numeric(rows["window"], errors="coerce").fillna(0).astype(int).eq(int(window))]
    return None if rows.empty else rows.iloc[0]


def _load_ledger(channel: str) -> pd.DataFrame:
    df = _load_csv(EXEC_DIR / f"{channel}_ledger.csv")
    if df.empty:
        return df
    out = df.copy()
    out["signal_key"] = out["signal_date"].map(_yyyymmdd) if "signal_date" in out.columns else ""
    out["trade_key"] = out["trade_date"].map(_yyyymmdd) if "trade_date" in out.columns else ""
    nav_pre = pd.to_numeric(out.get("nav_pre", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0)
    nav_post = pd.to_numeric(out.get("nav_post", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0)
    base = nav_post.shift(1)
    if len(base) > 0:
        base.iloc[0] = nav_pre.iloc[0]
    base = base.where(base.gt(0.0), nav_pre)
    out["daily_return_pct"] = np.where(base.gt(0.0), (nav_post / base - 1.0) * 100.0, 0.0)
    return out


def _artifact_path(channel: str, kind: str, trade_date: str, run_id: str) -> Path:
    return EXEC_DIR / f"{channel}_{kind}_{_yyyymmdd(trade_date)}_{run_id}.csv"


def _num(s: pd.Series, col: str, default: float = 0.0) -> float:
    return _safe_float(s.get(col, default), default)


def _intnum(s: pd.Series, col: str, default: int = 0) -> int:
    return _safe_int(s.get(col, default), default)


def _risk_summary(risk_df: pd.DataFrame) -> dict[str, object]:
    out = {
        "risk_gate_rows": 0,
        "risk_adv_hit_rows": 0,
        "risk_style_hit_rows": 0,
        "risk_industry_hit_rows": 0,
        "risk_entry_not_tradable_rows": 0,
        "risk_missing_bar_rows": 0,
        "risk_target_weight_sum": 0.0,
    }
    if risk_df.empty:
        return out
    reasons = risk_df.get("reasons", pd.Series("", index=risk_df.index)).astype(str).str.lower()
    target = pd.to_numeric(risk_df.get("target_weight", pd.Series(0.0, index=risk_df.index)), errors="coerce").fillna(0.0)
    out["risk_gate_rows"] = int(len(risk_df))
    out["risk_adv_hit_rows"] = int(reasons.str.contains("adv_participation", na=False).sum())
    out["risk_style_hit_rows"] = int(reasons.str.contains("style_", na=False).sum())
    out["risk_industry_hit_rows"] = int(reasons.str.contains("industry_weight|post_trade_industry", na=False).sum())
    out["risk_entry_not_tradable_rows"] = int(reasons.str.contains("entry_not_tradable", na=False).sum())
    out["risk_missing_bar_rows"] = int(reasons.str.contains("missing_bar", na=False).sum())
    out["risk_target_weight_sum"] = float(target.sum())
    return out


def _orders_summary(orders_df: pd.DataFrame) -> dict[str, object]:
    out = {
        "order_rows": 0,
        "filled_orders": 0,
        "blocked_orders": 0,
        "blocked_buy_orders": 0,
        "blocked_sell_orders": 0,
        "filled_buy_orders": 0,
        "filled_sell_orders": 0,
        "filled_buy_target_weight_sum": 0.0,
        "filled_sell_target_weight_sum": 0.0,
        "blocked_sell_current_weight_sum": 0.0,
        "blocked_sell_notional_sum": 0.0,
        "blocked_sell_codes": "",
        "blocked_sell_reasons": "",
    }
    if orders_df.empty:
        return out
    status = orders_df.get("status", pd.Series("", index=orders_df.index)).astype(str).str.lower()
    side = orders_df.get("side", pd.Series("", index=orders_df.index)).astype(str).str.upper()
    target = pd.to_numeric(orders_df.get("target_weight", pd.Series(0.0, index=orders_df.index)), errors="coerce").fillna(0.0)
    blocked_weight = pd.to_numeric(
        orders_df.get("blocked_current_weight", pd.Series(0.0, index=orders_df.index)),
        errors="coerce",
    ).fillna(0.0)
    blocked_notional = pd.to_numeric(
        orders_df.get("blocked_notional", pd.Series(0.0, index=orders_df.index)),
        errors="coerce",
    ).fillna(0.0)
    blocked = status.eq("blocked")
    sell = side.eq("SELL")
    buy = side.eq("BUY")
    blocked_sell = blocked & sell
    out["order_rows"] = int(len(orders_df))
    out["filled_orders"] = int(status.eq("filled").sum())
    out["blocked_orders"] = int(blocked.sum())
    out["blocked_buy_orders"] = int((blocked & buy).sum())
    out["blocked_sell_orders"] = int(blocked_sell.sum())
    out["filled_buy_orders"] = int((status.eq("filled") & buy).sum())
    out["filled_sell_orders"] = int((status.eq("filled") & sell).sum())
    out["filled_buy_target_weight_sum"] = float(target.loc[status.eq("filled") & buy].sum())
    out["filled_sell_target_weight_sum"] = float(target.loc[status.eq("filled") & sell].sum())
    out["blocked_sell_current_weight_sum"] = float(blocked_weight.loc[blocked_sell].sum())
    out["blocked_sell_notional_sum"] = float(blocked_notional.loc[blocked_sell].sum())
    if blocked_sell.any():
        out["blocked_sell_codes"] = ",".join(orders_df.loc[blocked_sell, "code"].astype(str).tolist())
        out["blocked_sell_reasons"] = ",".join(orders_df.loc[blocked_sell, "reason"].astype(str).tolist())
    return out


def _day_label(row: dict[str, object]) -> str:
    holiday = _safe_int(row.get("candidate_holiday_gap_guard", 0)) > 0
    target_gap = _safe_float(row.get("target_weight_gap", 0.0))
    exit_worse = _safe_int(row.get("candidate_blocked_sell_orders", 0)) > _safe_int(row.get("main_blocked_sell_orders", 0))
    entry_hits = _safe_int(row.get("candidate_risk_entry_not_tradable_rows", 0)) > _safe_int(
        row.get("main_risk_entry_not_tradable_rows", 0)
    )
    if holiday and target_gap < -0.05 and exit_worse:
        return "holiday_gap_cash_drag+sell_trap"
    if holiday and target_gap < -0.05:
        return "holiday_gap_cash_drag"
    if exit_worse:
        return "sell_trap"
    if entry_hits:
        return "entry_tradability_gate"
    if target_gap < -0.05:
        return "cash_drag_or_underdeployment"
    return "relative_alpha_or_mark_to_market"


def _role_day(
    *,
    profile: str,
    role: str,
    channel: str,
    ledger_row: pd.Series,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    trade_date = _yyyymmdd(ledger_row.get("trade_date", ""))
    run_id = str(ledger_row.get("run_id", ""))
    orders_fp = _artifact_path(channel, "orders", trade_date, run_id)
    risk_fp = _artifact_path(channel, "risk_gates", trade_date, run_id)
    orders = _load_csv(orders_fp)
    risk = _load_csv(risk_fp)
    summary: dict[str, object] = {
        "profile": profile,
        "role": role,
        "channel": channel,
        "run_id": run_id,
        "signal_date": _date_display(ledger_row.get("signal_date", "")),
        "trade_date": _date_display(ledger_row.get("trade_date", "")),
        "nav_pre": _num(ledger_row, "nav_pre"),
        "nav_post": _num(ledger_row, "nav_post"),
        "daily_return_pct": _num(ledger_row, "daily_return_pct"),
        "target_weight_sum": _num(ledger_row, "target_weight_sum"),
        "holiday_gap_guard": _intnum(ledger_row, "holiday_gap_guard"),
        "holiday_gap_reason": str(ledger_row.get("holiday_gap_reason", "") or ""),
        "holiday_gap_target_scale": _num(ledger_row, "holiday_gap_target_scale", 1.0),
        "broker_entry_not_tradable_orders": _intnum(ledger_row, "broker_entry_not_tradable_orders"),
        "broker_exit_not_tradable_orders": _intnum(ledger_row, "broker_exit_not_tradable_orders"),
        "blocked_sell_current_weight": _num(ledger_row, "blocked_sell_current_weight"),
        "blocked_sell_notional": _num(ledger_row, "blocked_sell_notional"),
        "risk_blocked_count": _intnum(ledger_row, "risk_blocked_count"),
        "risk_blocked_rate_pct": _num(ledger_row, "risk_blocked_rate_pct"),
        "orders_file": str(orders_fp if orders_fp.exists() else ""),
        "risk_file": str(risk_fp if risk_fp.exists() else ""),
    }
    summary.update(_orders_summary(orders))
    summary.update(_risk_summary(risk))
    if not orders.empty:
        orders = orders.copy()
        orders.insert(0, "profile", profile)
        orders.insert(1, "role", role)
    if not risk.empty:
        risk = risk.copy()
        risk.insert(0, "profile", profile)
        risk.insert(1, "role", role)
    return summary, orders, risk


def build_day_attribution(
    *,
    failure_detail: pd.DataFrame,
    p2_summary: pd.DataFrame,
    main_profile: str,
    candidate_profiles: list[str],
    window: int | None,
    focus_dates: list[str],
    worst_n: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    best = _best_summary_rows(p2_summary, window)
    main_row = _summary_row(best, main_profile, window)
    if main_row is None:
        raise RuntimeError(f"Missing main profile in P2 summary: {main_profile}")
    main_channel = str(main_row.get("channel", ""))
    main_ledger = _load_ledger(main_channel)
    all_summaries: list[dict[str, object]] = []
    order_frames: list[pd.DataFrame] = []
    risk_frames: list[pd.DataFrame] = []
    for candidate in candidate_profiles:
        cand_row = _summary_row(best, candidate, window)
        if cand_row is None:
            continue
        cand_channel = str(cand_row.get("channel", ""))
        cand_ledger = _load_ledger(cand_channel)
        if cand_ledger.empty or main_ledger.empty:
            continue
        cand_days = failure_detail[failure_detail.get("candidate_profile", "").astype(str).eq(candidate)].copy()
        if window and "window" in cand_days.columns:
            cand_days = cand_days[pd.to_numeric(cand_days["window"], errors="coerce").fillna(0).astype(int).eq(int(window))]
        focus_keys = {_yyyymmdd(x) for x in focus_dates}
        if focus_keys:
            selected_days = cand_days[cand_days["signal_date"].map(_yyyymmdd).isin(focus_keys)].copy()
        else:
            selected_days = cand_days.sort_values("relative_return_gap_pct", ascending=True).head(max(1, int(worst_n))).copy()
        for _, frow in selected_days.iterrows():
            sig = _yyyymmdd(frow.get("signal_date", ""))
            mrows = main_ledger[main_ledger["signal_key"].astype(str).eq(sig)]
            crows = cand_ledger[cand_ledger["signal_key"].astype(str).eq(sig)]
            if mrows.empty or crows.empty:
                continue
            msummary, morders, mrisk = _role_day(
                profile=main_profile,
                role="main",
                channel=main_channel,
                ledger_row=mrows.iloc[0],
            )
            csummary, corders, crisk = _role_day(
                profile=candidate,
                role="candidate",
                channel=cand_channel,
                ledger_row=crows.iloc[0],
            )
            merged: dict[str, object] = {
                "candidate_profile": candidate,
                "main_profile": main_profile,
                "window": int(window or _safe_int(frow.get("window", 0))),
                "signal_date": _date_display(sig),
                "main_trade_date": msummary["trade_date"],
                "candidate_trade_date": csummary["trade_date"],
                "relative_return_gap_pct": _safe_float(frow.get("relative_return_gap_pct", 0.0)),
                "main_daily_return_pct": msummary["daily_return_pct"],
                "candidate_daily_return_pct": csummary["daily_return_pct"],
                "target_weight_gap": _safe_float(csummary["target_weight_sum"]) - _safe_float(msummary["target_weight_sum"]),
            }
            for prefix, src in [("main", msummary), ("candidate", csummary)]:
                for key, value in src.items():
                    if key in {"profile", "role", "channel", "run_id", "signal_date", "trade_date"}:
                        merged[f"{prefix}_{key}"] = value
                    elif key not in {"nav_pre", "nav_post"}:
                        merged[f"{prefix}_{key}"] = value
            merged["day_failure_label"] = _day_label(merged)
            all_summaries.append(merged)
            if not morders.empty:
                morders.insert(2, "focus_signal_date", _date_display(sig))
                order_frames.append(morders)
            if not corders.empty:
                corders.insert(2, "focus_signal_date", _date_display(sig))
                order_frames.append(corders)
            if not mrisk.empty:
                mrisk.insert(2, "focus_signal_date", _date_display(sig))
                risk_frames.append(mrisk)
            if not crisk.empty:
                crisk.insert(2, "focus_signal_date", _date_display(sig))
                risk_frames.append(crisk)
    summary = pd.DataFrame(all_summaries)
    orders = pd.concat(order_frames, ignore_index=True) if order_frames else pd.DataFrame()
    risks = pd.concat(risk_frames, ignore_index=True) if risk_frames else pd.DataFrame()
    return summary, orders, risks


def main() -> int:
    parser = argparse.ArgumentParser(description="Drill worst P2 failure days into order/risk artifacts")
    parser.add_argument("--failure-detail", default=str(BACKTEST_DIR / "quant_p2_smoke_failure_detail_latest.csv"))
    parser.add_argument("--p2-summary", default=str(BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"))
    parser.add_argument("--main-profile", default="quality_regime")
    parser.add_argument("--profiles", default="", help="Candidate profiles; default from failure detail")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--focus-dates", default="", help="Signal dates to inspect, comma-separated; default worst days")
    parser.add_argument("--worst-n", type=int, default=3)
    parser.add_argument("--write-latest", action="store_true")
    args = parser.parse_args()

    failure_detail = _load_csv(Path(args.failure_detail).expanduser().resolve())
    p2_summary = _load_csv(Path(args.p2_summary).expanduser().resolve())
    if failure_detail.empty or p2_summary.empty:
        print("缺少 failure detail 或 P2 summary")
        return 2
    candidates = _parse_list(args.profiles)
    if not candidates and "candidate_profile" in failure_detail.columns:
        candidates = [str(x) for x in failure_detail["candidate_profile"].dropna().astype(str).unique()]
    summary, orders, risks = build_day_attribution(
        failure_detail=failure_detail,
        p2_summary=p2_summary,
        main_profile=str(args.main_profile),
        candidate_profiles=candidates,
        window=int(args.window) if args.window else None,
        focus_dates=_parse_list(args.focus_dates),
        worst_n=max(1, int(args.worst_n)),
    )
    if summary.empty:
        print("未生成 day attribution；请检查候选、窗口或 failure detail")
        return 2
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_fp = BACKTEST_DIR / f"quant_p2_failure_day_attribution_{ts}.csv"
    orders_fp = BACKTEST_DIR / f"quant_p2_failure_day_orders_{ts}.csv"
    risks_fp = BACKTEST_DIR / f"quant_p2_failure_day_risks_{ts}.csv"
    meta_fp = BACKTEST_DIR / f"quant_p2_failure_day_attribution_{ts}.json"
    summary.to_csv(summary_fp, index=False, encoding="utf-8-sig")
    orders.to_csv(orders_fp, index=False, encoding="utf-8-sig")
    risks.to_csv(risks_fp, index=False, encoding="utf-8-sig")
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "failure_detail": str(Path(args.failure_detail).expanduser().resolve()),
        "p2_summary": str(Path(args.p2_summary).expanduser().resolve()),
        "main_profile": str(args.main_profile),
        "candidate_profiles": candidates,
        "window": int(args.window),
        "summary": str(summary_fp),
        "orders": str(orders_fp),
        "risks": str(risks_fp),
        "rows": summary.to_dict(orient="records"),
    }
    meta_fp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        summary.to_csv(BACKTEST_DIR / "quant_p2_failure_day_attribution_latest.csv", index=False, encoding="utf-8-sig")
        orders.to_csv(BACKTEST_DIR / "quant_p2_failure_day_orders_latest.csv", index=False, encoding="utf-8-sig")
        risks.to_csv(BACKTEST_DIR / "quant_p2_failure_day_risks_latest.csv", index=False, encoding="utf-8-sig")
        (BACKTEST_DIR / "quant_p2_failure_day_attribution_latest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    lead_cols = [
        "candidate_profile",
        "signal_date",
        "day_failure_label",
        "relative_return_gap_pct",
        "target_weight_gap",
        "candidate_holiday_gap_reason",
        "candidate_holiday_gap_target_scale",
        "candidate_blocked_sell_orders",
        "candidate_blocked_sell_codes",
        "candidate_risk_entry_not_tradable_rows",
    ]
    print(summary[[c for c in lead_cols if c in summary.columns]].to_string(index=False))
    print(f"p2_failure_day_summary={summary_fp}")
    print(f"p2_failure_day_orders={orders_fp}")
    print(f"p2_failure_day_risks={risks_fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
