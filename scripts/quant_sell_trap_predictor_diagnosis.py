#!/usr/bin/env python3
"""Validate whether entry-time risk scores explain later blocked sells."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
BACKTEST_DIR = BASE_DIR / "output" / "backtest"
EXECUTION_DIR = BASE_DIR / "output" / "execution"


def _parse_list(raw: str | None) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if pd.notna(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _latest_summary_paths(profiles: list[str]) -> list[Path]:
    matches = sorted(BACKTEST_DIR.glob("p2_rolling_replay_summary_*.csv"))
    if not matches:
        return []
    if not profiles:
        return [matches[-1]]
    out: list[Path] = []
    for p in profiles:
        profile_matches = [x for x in matches if str(p) in x.name]
        if profile_matches:
            out.append(profile_matches[-1])
    return out or [matches[-1]]


def load_summary(raw: str | None, profiles: list[str]) -> pd.DataFrame:
    paths = [Path(x).expanduser().resolve() for x in _parse_list(raw)] if str(raw or "").strip() else _latest_summary_paths(profiles)
    frames: list[pd.DataFrame] = []
    for fp in paths:
        if fp.exists():
            frames.append(pd.read_csv(fp))
    if not frames:
        raise FileNotFoundError("未找到 P2 rolling summary")
    df = pd.concat(frames, ignore_index=True)
    if profiles and "profile" in df.columns:
        df = df[df["profile"].astype(str).isin(profiles)].copy()
    return df.reset_index(drop=True)


def select_best_summary_rows(summary_df: pd.DataFrame, windows: set[int] | None) -> pd.DataFrame:
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


def load_sell_orders_for_channel(channel: str) -> pd.DataFrame:
    channel = str(channel or "").strip()
    if not channel:
        return pd.DataFrame()
    frames: list[pd.DataFrame] = []
    for fp in sorted(EXECUTION_DIR.glob(f"{channel}_orders_*.csv")):
        try:
            df = pd.read_csv(fp)
        except Exception:
            continue
        if df.empty or "side" not in df.columns:
            continue
        sell = df[df["side"].astype(str).str.upper().eq("SELL")].copy()
        if sell.empty:
            continue
        sell["orders_file"] = str(fp)
        frames.append(sell)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_predictor_detail(summary_rows: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for rec in summary_rows.to_dict(orient="records"):
        orders = load_sell_orders_for_channel(str(rec.get("channel", "")))
        if orders.empty:
            continue
        orders["profile"] = str(rec.get("profile", ""))
        orders["window"] = int(_safe_float(rec.get("window", 0), 0))
        orders["channel"] = str(rec.get("channel", ""))
        orders["blocked_sell_label"] = (
            orders.get("status", "").astype(str).eq("blocked")
            & orders.get("reason", "").astype(str).eq("exit_not_tradable")
        ).astype(int)
        for col in [
            "position_entry_exit_trap_risk_score",
            "position_entry_exit_trap_safe_score",
            "position_entry_exit_trap_volume_drought_risk",
            "position_entry_exit_trap_drawdown_10d_pct",
            "position_entry_exit_trap_down_momentum_5d",
            "position_entry_exit_trap_volatility_10d",
            "position_entry_risk_score",
            "position_entry_tradability_safe_score",
            "position_entry_reserve_candidate",
            "blocked_current_weight",
        ]:
            if col not in orders.columns:
                orders[col] = pd.NA
            orders[col] = pd.to_numeric(orders[col], errors="coerce")
        orders["entry_exit_trap_risk_score_available"] = orders["position_entry_exit_trap_risk_score"].notna().astype(int)
        rows.append(orders)
    if not rows:
        return pd.DataFrame()
    detail = pd.concat(rows, ignore_index=True)
    keep_cols = [
        "profile",
        "window",
        "channel",
        "signal_date",
        "trade_date",
        "code",
        "name",
        "status",
        "reason",
        "blocked_sell_label",
        "position_entry_exit_trap_risk_score",
        "position_entry_exit_trap_safe_score",
        "position_entry_exit_trap_volume_drought_risk",
        "position_entry_exit_trap_drawdown_10d_pct",
        "position_entry_exit_trap_down_momentum_5d",
        "position_entry_exit_trap_volatility_10d",
        "position_entry_risk_score",
        "position_entry_tradability_safe_score",
        "position_entry_reserve_candidate",
        "blocked_current_weight",
        "entry_exit_trap_risk_score_available",
        "orders_file",
    ]
    return detail[[c for c in keep_cols if c in detail.columns]].copy()


def _mean_for(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").mean()) if len(df) else 0.0


def summarize_predictor(detail: pd.DataFrame, risk_threshold: float) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for (profile, window), g in detail.groupby(["profile", "window"], dropna=False):
        blocked = g[g["blocked_sell_label"].astype(int).eq(1)].copy()
        filled = g[g["blocked_sell_label"].astype(int).eq(0)].copy()
        risk = pd.to_numeric(g["position_entry_exit_trap_risk_score"], errors="coerce").fillna(0.0)
        volume_drought = pd.to_numeric(
            g.get("position_entry_exit_trap_volume_drought_risk", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0)
        risk_available = pd.to_numeric(
            g.get("entry_exit_trap_risk_score_available", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0)
        high = risk.ge(float(risk_threshold))
        high_volume_drought = volume_drought.ge(float(risk_threshold))
        high_blocked = int((high & g["blocked_sell_label"].astype(int).eq(1)).sum())
        high_volume_drought_blocked = int((high_volume_drought & g["blocked_sell_label"].astype(int).eq(1)).sum())
        rows.append(
            {
                "profile": profile,
                "window": int(window),
                "sell_orders": int(len(g)),
                "blocked_sell_orders": int(len(blocked)),
                "filled_sell_orders": int(len(filled)),
                "blocked_rate_pct": float(len(blocked) / max(len(g), 1) * 100.0),
                "entry_exit_trap_risk_score_coverage_pct": float(risk_available.gt(0).sum() / max(len(g), 1) * 100.0),
                "entry_exit_trap_risk_blocked_mean": _mean_for(blocked, "position_entry_exit_trap_risk_score"),
                "entry_exit_trap_risk_filled_mean": _mean_for(filled, "position_entry_exit_trap_risk_score"),
                "entry_exit_trap_volume_drought_blocked_mean": _mean_for(
                    blocked, "position_entry_exit_trap_volume_drought_risk"
                ),
                "entry_exit_trap_volume_drought_filled_mean": _mean_for(
                    filled, "position_entry_exit_trap_volume_drought_risk"
                ),
                "entry_exit_trap_drawdown_10d_blocked_mean": _mean_for(
                    blocked, "position_entry_exit_trap_drawdown_10d_pct"
                ),
                "entry_exit_trap_drawdown_10d_filled_mean": _mean_for(
                    filled, "position_entry_exit_trap_drawdown_10d_pct"
                ),
                "entry_risk_blocked_mean": _mean_for(blocked, "position_entry_risk_score"),
                "entry_risk_filled_mean": _mean_for(filled, "position_entry_risk_score"),
                "blocked_sell_reserve_orders": int(
                    pd.to_numeric(blocked.get("position_entry_reserve_candidate", pd.Series(dtype=float)), errors="coerce")
                    .fillna(0.0)
                    .gt(0)
                    .sum()
                ),
                "high_exit_trap_risk_orders": int(high.sum()),
                "high_exit_trap_risk_blocked_orders": int(high_blocked),
                "high_exit_trap_risk_blocked_recall_pct": float(
                    high_blocked / max(int(len(blocked)), 1) * 100.0
                ),
                "high_exit_trap_volume_drought_orders": int(high_volume_drought.sum()),
                "high_exit_trap_volume_drought_blocked_orders": int(high_volume_drought_blocked),
                "high_exit_trap_volume_drought_blocked_recall_pct": float(
                    high_volume_drought_blocked / max(int(len(blocked)), 1) * 100.0
                ),
                "blocked_sell_weight_sum": float(
                    pd.to_numeric(blocked.get("blocked_current_weight", pd.Series(dtype=float)), errors="coerce")
                    .fillna(0.0)
                    .sum()
                ),
                "predictor_direction_ok": bool(
                    _mean_for(blocked, "position_entry_exit_trap_risk_score")
                    > _mean_for(filled, "position_entry_exit_trap_risk_score")
                ),
                "volume_drought_direction_ok": bool(
                    _mean_for(blocked, "position_entry_exit_trap_volume_drought_risk")
                    > _mean_for(filled, "position_entry_exit_trap_volume_drought_risk")
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    p = argparse.ArgumentParser(description="Sell-trap predictor diagnosis")
    p.add_argument("--p2-summary", type=str, default="", help="P2 rolling summary 文件，支持逗号分隔；默认 latest")
    p.add_argument("--profiles", type=str, default="", help="profile 列表，逗号分隔")
    p.add_argument("--windows", type=str, default="", help="窗口列表，逗号分隔")
    p.add_argument("--risk-threshold", type=float, default=0.65)
    p.add_argument("--write-latest", action="store_true")
    args = p.parse_args()

    profiles = _parse_list(args.profiles)
    windows = {int(x) for x in _parse_list(args.windows)} if str(args.windows or "").strip() else None
    summary = select_best_summary_rows(load_summary(args.p2_summary, profiles), windows)
    detail = build_predictor_detail(summary)
    summary_out = summarize_predictor(detail, float(args.risk_threshold))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_path = BACKTEST_DIR / f"quant_sell_trap_predictor_detail_{ts}.csv"
    summary_path = BACKTEST_DIR / f"quant_sell_trap_predictor_summary_{ts}.csv"
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    detail.to_csv(detail_path, index=False)
    summary_out.to_csv(summary_path, index=False)
    if args.write_latest:
        detail.to_csv(BACKTEST_DIR / "quant_sell_trap_predictor_detail_latest.csv", index=False)
        summary_out.to_csv(BACKTEST_DIR / "quant_sell_trap_predictor_summary_latest.csv", index=False)

    print(f"sell-trap predictor detail: {detail_path}")
    print(f"sell-trap predictor summary: {summary_path}")
    if not summary_out.empty:
        print(summary_out.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
