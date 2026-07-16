#!/usr/bin/env python3
"""
P1 平台化分析：风险暴露 / 收益归因 / 容量与成本诊断。

输入：
1) 组合回测交易明细（quant_trades_*.csv）
2) 共享只读 A 股 ODS（用于流动性容量）
3) 股票元数据（行业映射）

输出（output/risk/）：
- risk_exposure_summary_*.csv
- risk_exposure_industry_*.csv
- return_attribution_*.csv
- capacity_cost_*.csv
- p1_analytics_summary_*.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from utils.code_utils import normalize_ts_code, normalize_ts_code_series
from utils.output_paths import get_output_dirs, list_dual
from core.data.market_data_gateway import load_execution_bars
from core.risk.pretrade import load_industry_map as load_ods_industry_map

OUTPUT_DIR = Path(BASE_DIR) / "output"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def _resolve_latest_trade_file(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    dirs = get_output_dirs(OUTPUT_DIR)
    files = list_dual(["quant_trades_*.csv"], dirs["backtest"], dirs["base"])
    if not files:
        return None
    return sorted(files)[-1]


def _resolve_summary_file(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    candidates = [
        OUTPUT_DIR / "backtest" / "quant_backtest_summary.csv",
        OUTPUT_DIR / "quant_backtest_summary.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_summary_row(summary_file: Path | None) -> dict[str, float]:
    if not summary_file or not summary_file.exists():
        return {}
    try:
        df = pd.read_csv(summary_file)
        if df.empty:
            return {}
        row = df.iloc[-1].to_dict()
    except Exception:
        return {}
    out: dict[str, float] = {}
    for k, v in row.items():
        try:
            out[str(k)] = float(v)
        except Exception:
            continue
    return out


def _load_trades(trade_file: Path) -> pd.DataFrame:
    df = pd.read_csv(trade_file)
    if df.empty:
        return df
    for col in ("signal_date", "entry_date", "exit_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.normalize()
    for col in ("portfolio_ret", "excess_ret", "total_exposure"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["entry_date", "portfolio_ret", "total_exposure"])
    return df.sort_values(["entry_date", "signal_date"]).reset_index(drop=True)


def _load_industry_map(asof_date: object) -> dict[str, str]:
    """Load industry metadata from the shared ODS as of the analysis window."""
    return load_ods_industry_map(asof_date=asof_date)


def _load_bars_index(start: object, end: object) -> pd.DataFrame:
    """Load only the ODS sessions needed by the realized trade window."""
    _, bars_idx, _ = load_execution_bars(start, end, lookback_sessions=20, forward_sessions=0)
    return bars_idx


def _get_bar_row(bars_idx: pd.DataFrame, trade_date: pd.Timestamp, code: str) -> pd.Series | None:
    if bars_idx.empty:
        return None
    try:
        row = bars_idx.loc[(trade_date, code)]
    except KeyError:
        return None
    if isinstance(row, pd.DataFrame):
        if row.empty:
            return None
        return row.iloc[-1]
    return row


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _parse_codes_and_weights(row: pd.Series) -> tuple[list[str], np.ndarray]:
    codes_raw = str(row.get("codes", "") or "")
    codes = [normalize_ts_code(x) for x in codes_raw.split(",")]
    codes = [c for c in codes if c]
    if not codes:
        return [], np.array([], dtype=float)

    weights_raw = str(row.get("weights", "") or "")
    weights = []
    for x in weights_raw.split(","):
        x = x.strip()
        if not x:
            continue
        try:
            weights.append(float(x))
        except Exception:
            continue

    if len(weights) != len(codes):
        w = np.ones(len(codes), dtype=float)
    else:
        w = np.asarray(weights, dtype=float)
        w = np.where(np.isfinite(w), w, 0.0)
        if np.sum(w) <= 0:
            w = np.ones(len(codes), dtype=float)
    total_exposure = max(_safe_float(row.get("total_exposure", 0.0), 0.0), 0.0)
    if total_exposure > 0:
        w = w / np.sum(w) * total_exposure
    else:
        w = w / np.sum(w)
    return codes, w


def _build_trade_and_position_frames(
    trades_df: pd.DataFrame,
    bars_idx: pd.DataFrame,
    industry_map: dict[str, str],
    capital_base: float,
    adv_participation: float,
    fee_bps: float,
    slippage_bps: float,
    stamp_tax_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    trade_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []

    roundtrip_cost_rate = (2.0 * (fee_bps + slippage_bps) + stamp_tax_bps) / 10000.0

    for _, row in trades_df.iterrows():
        entry_date = pd.to_datetime(row.get("entry_date"), errors="coerce")
        signal_date = pd.to_datetime(row.get("signal_date"), errors="coerce")
        if pd.isna(entry_date):
            continue
        entry_date = entry_date.normalize()
        signal_date = signal_date.normalize() if pd.notna(signal_date) else pd.NaT

        codes, weights = _parse_codes_and_weights(row)
        if len(codes) == 0:
            continue
        total_exposure = max(_safe_float(row.get("total_exposure", 0.0)), 0.0)
        if total_exposure <= 0:
            total_exposure = float(np.sum(weights))
        if total_exposure <= 0:
            continue

        norm_w = np.asarray(weights, dtype=float) / max(float(np.sum(weights)), 1e-12)
        hhi = float(np.sum(np.square(norm_w)))
        industry_weight_share: dict[str, float] = {}
        adv_amounts: list[float] = []
        participation_list: list[float] = []

        for code, w_abs, w_share in zip(codes, weights, norm_w):
            ind = industry_map.get(code, "")
            industry = ind if ind else "未知"
            industry_weight_share[industry] = industry_weight_share.get(industry, 0.0) + float(w_share)

            bar = _get_bar_row(bars_idx, entry_date, code)
            adv_amount = np.nan
            participation = np.nan
            if bar is not None:
                adv_amount = _safe_float(bar.get("amount", np.nan), np.nan)
                if np.isfinite(adv_amount) and adv_amount > 0:
                    participation = float(capital_base * w_abs / adv_amount)
                    adv_amounts.append(float(adv_amount))
                    participation_list.append(float(participation))

            position_rows.append(
                {
                    "signal_date": signal_date.strftime("%Y-%m-%d") if pd.notna(signal_date) else "",
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "state": str(row.get("state", "") or ""),
                    "code": code,
                    "industry": industry,
                    "weight_abs": float(w_abs),
                    "weight_pct": float(w_abs * 100.0),
                    "weight_share": float(w_share),
                    "adv_amount": float(adv_amount) if np.isfinite(adv_amount) else np.nan,
                    "participation_pct": float(participation * 100.0) if np.isfinite(participation) else np.nan,
                    "portfolio_ret_pct": _safe_float(row.get("portfolio_ret", 0.0), 0.0) * 100.0,
                    "excess_ret_pct": _safe_float(row.get("excess_ret", 0.0), 0.0) * 100.0,
                }
            )

        top_industry = ""
        max_industry_weight = 0.0
        if industry_weight_share:
            top_industry, max_industry_weight = max(industry_weight_share.items(), key=lambda kv: kv[1])

        trade_capacity_capital = np.nan
        if adv_amounts and total_exposure > 0:
            trade_capacity_capital = float(adv_participation * np.sum(adv_amounts) / total_exposure)

        trade_rows.append(
            {
                "signal_date": signal_date.strftime("%Y-%m-%d") if pd.notna(signal_date) else "",
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "state": str(row.get("state", "") or ""),
                "exit_reason": str(row.get("exit_reason", "") or ""),
                "position_count": int(len(codes)),
                "total_exposure": float(total_exposure),
                "total_exposure_pct": float(total_exposure * 100.0),
                "portfolio_ret_pct": _safe_float(row.get("portfolio_ret", 0.0), 0.0) * 100.0,
                "excess_ret_pct": _safe_float(row.get("excess_ret", 0.0), 0.0) * 100.0,
                "weight_hhi": hhi,
                "top_industry": top_industry,
                "top_industry_weight_pct": float(max_industry_weight * 100.0),
                "avg_adv_amount": float(np.mean(adv_amounts)) if adv_amounts else np.nan,
                "min_adv_amount": float(np.min(adv_amounts)) if adv_amounts else np.nan,
                "max_participation_pct": float(np.max(participation_list) * 100.0) if participation_list else np.nan,
                "median_participation_pct": float(np.median(participation_list) * 100.0) if participation_list else np.nan,
                "trade_capacity_capital": float(trade_capacity_capital) if np.isfinite(trade_capacity_capital) else np.nan,
                "estimated_roundtrip_cost": float(capital_base * total_exposure * roundtrip_cost_rate),
                "estimated_roundtrip_cost_bps": float(roundtrip_cost_rate * 10000.0),
                "estimated_pnl_amount": float(capital_base * _safe_float(row.get("portfolio_ret", 0.0), 0.0)),
            }
        )

    return pd.DataFrame(trade_rows), pd.DataFrame(position_rows)


def _build_exposure_summary(diag_df: pd.DataFrame) -> pd.DataFrame:
    if diag_df.empty:
        return pd.DataFrame()

    grp = (
        diag_df.groupby("state", dropna=False)
        .agg(
            trades=("entry_date", "count"),
            avg_exposure_pct=("total_exposure_pct", "mean"),
            avg_positions=("position_count", "mean"),
            win_rate_pct=("portfolio_ret_pct", lambda s: float(np.mean(s > 0) * 100.0)),
            avg_portfolio_ret_pct=("portfolio_ret_pct", "mean"),
            avg_excess_ret_pct=("excess_ret_pct", "mean"),
            cum_portfolio_ret_pct=("portfolio_ret_pct", "sum"),
            avg_hhi=("weight_hhi", "mean"),
            avg_top_industry_weight_pct=("top_industry_weight_pct", "mean"),
            p95_max_participation_pct=("max_participation_pct", lambda s: float(np.nanpercentile(s, 95))),
        )
        .reset_index()
    )
    grp["state"] = grp["state"].replace({"": "未知"})

    total_row = {
        "state": "__TOTAL__",
        "trades": int(len(diag_df)),
        "avg_exposure_pct": float(diag_df["total_exposure_pct"].mean()),
        "avg_positions": float(diag_df["position_count"].mean()),
        "win_rate_pct": float(np.mean(diag_df["portfolio_ret_pct"] > 0) * 100.0),
        "avg_portfolio_ret_pct": float(diag_df["portfolio_ret_pct"].mean()),
        "avg_excess_ret_pct": float(diag_df["excess_ret_pct"].mean()),
        "cum_portfolio_ret_pct": float(diag_df["portfolio_ret_pct"].sum()),
        "avg_hhi": float(diag_df["weight_hhi"].mean()),
        "avg_top_industry_weight_pct": float(diag_df["top_industry_weight_pct"].mean()),
        "p95_max_participation_pct": float(np.nanpercentile(diag_df["max_participation_pct"], 95)),
    }
    return pd.concat([grp, pd.DataFrame([total_row])], ignore_index=True)


def _build_industry_exposure(position_df: pd.DataFrame) -> pd.DataFrame:
    if position_df.empty:
        return pd.DataFrame()
    g = (
        position_df.groupby("industry", dropna=False)
        .agg(
            position_obs=("code", "count"),
            traded_days=("entry_date", "nunique"),
            avg_weight_pct=("weight_pct", "mean"),
            median_weight_pct=("weight_pct", "median"),
            max_weight_pct=("weight_pct", "max"),
            avg_participation_pct=("participation_pct", "mean"),
            approx_return_contrib_pct=("portfolio_ret_pct", lambda s: float(np.sum(s))),
        )
        .reset_index()
        .sort_values(["avg_weight_pct", "position_obs"], ascending=[False, False])
    )
    g["industry"] = g["industry"].replace({"": "未知"})
    return g


def _build_attribution(diag_df: pd.DataFrame) -> pd.DataFrame:
    if diag_df.empty:
        return pd.DataFrame()
    work = diag_df.copy()
    work["entry_month"] = pd.to_datetime(work["entry_date"], errors="coerce").dt.strftime("%Y-%m")
    dims = [
        ("state", "state"),
        ("exit_reason", "exit_reason"),
        ("entry_month", "entry_month"),
    ]
    rows = []
    for dim_name, col in dims:
        part = (
            work.groupby(col, dropna=False)
            .agg(
                trades=("entry_date", "count"),
                win_rate_pct=("portfolio_ret_pct", lambda s: float(np.mean(s > 0) * 100.0)),
                avg_portfolio_ret_pct=("portfolio_ret_pct", "mean"),
                avg_excess_ret_pct=("excess_ret_pct", "mean"),
                cum_portfolio_ret_pct=("portfolio_ret_pct", "sum"),
                avg_exposure_pct=("total_exposure_pct", "mean"),
            )
            .reset_index()
        )
        part["group_type"] = dim_name
        part["group_value"] = part[col].astype(str).replace({"": "未知", "nan": "未知"})
        rows.append(part[["group_type", "group_value", "trades", "win_rate_pct", "avg_portfolio_ret_pct", "avg_excess_ret_pct", "cum_portfolio_ret_pct", "avg_exposure_pct"]])
    return pd.concat(rows, ignore_index=True)


def _build_capacity_cost(diag_df: pd.DataFrame, capital_base: float) -> pd.DataFrame:
    if diag_df.empty:
        return pd.DataFrame()
    out = diag_df[
        [
            "signal_date",
            "entry_date",
            "state",
            "total_exposure_pct",
            "position_count",
            "max_participation_pct",
            "median_participation_pct",
            "trade_capacity_capital",
            "estimated_roundtrip_cost",
            "estimated_roundtrip_cost_bps",
            "estimated_pnl_amount",
            "portfolio_ret_pct",
        ]
    ].copy()
    out["capacity_multiple"] = out["trade_capacity_capital"] / max(capital_base, 1e-9)
    return out


def _json_summary(
    trade_file: Path,
    diag_df: pd.DataFrame,
    capital_df: pd.DataFrame,
    capital_base: float,
    adv_participation: float,
) -> dict[str, object]:
    if diag_df.empty:
        return {
            "trade_file": str(trade_file),
            "trade_count": 0,
            "capital_base": capital_base,
            "adv_participation_limit": adv_participation,
        }
    out = {
        "trade_file": str(trade_file),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trade_count": int(len(diag_df)),
        "capital_base": float(capital_base),
        "adv_participation_limit": float(adv_participation),
        "avg_exposure_pct": float(diag_df["total_exposure_pct"].mean()),
        "avg_position_count": float(diag_df["position_count"].mean()),
        "avg_hhi": float(diag_df["weight_hhi"].mean()),
        "avg_top_industry_weight_pct": float(diag_df["top_industry_weight_pct"].mean()),
        "avg_trade_ret_pct": float(diag_df["portfolio_ret_pct"].mean()),
        "cum_trade_ret_pct": float(diag_df["portfolio_ret_pct"].sum()),
        "win_rate_pct": float(np.mean(diag_df["portfolio_ret_pct"] > 0) * 100.0),
        "median_trade_capacity_capital": float(np.nanmedian(diag_df["trade_capacity_capital"])),
        "p25_trade_capacity_capital": float(np.nanpercentile(diag_df["trade_capacity_capital"], 25)),
        "avg_max_participation_pct": float(np.nanmean(diag_df["max_participation_pct"])),
        "p95_max_participation_pct": float(np.nanpercentile(diag_df["max_participation_pct"], 95)),
        "avg_roundtrip_cost_amount": float(diag_df["estimated_roundtrip_cost"].mean()),
    }
    if not capital_df.empty:
        finite_cap = capital_df["trade_capacity_capital"].dropna()
        if len(finite_cap) > 0:
            min_idx = finite_cap.idxmin()
            out["binding_capacity_trade"] = {
                "entry_date": str(capital_df.loc[min_idx, "entry_date"]),
                "state": str(capital_df.loc[min_idx, "state"]),
                "trade_capacity_capital": float(capital_df.loc[min_idx, "trade_capacity_capital"]),
                "max_participation_pct": float(capital_df.loc[min_idx, "max_participation_pct"]),
            }
    return out


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _write_outputs(
    exposure_df: pd.DataFrame,
    industry_df: pd.DataFrame,
    attrib_df: pd.DataFrame,
    capacity_df: pd.DataFrame,
    summary: dict[str, object],
    write_latest: bool,
) -> list[Path]:
    out_dir = OUTPUT_DIR / "risk"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")

    files = {
        "exposure": out_dir / f"risk_exposure_summary_{tag}.csv",
        "industry": out_dir / f"risk_exposure_industry_{tag}.csv",
        "attrib": out_dir / f"return_attribution_{tag}.csv",
        "capacity": out_dir / f"capacity_cost_{tag}.csv",
        "summary": out_dir / f"p1_analytics_summary_{tag}.json",
    }
    _write_csv(exposure_df, files["exposure"])
    _write_csv(industry_df, files["industry"])
    _write_csv(attrib_df, files["attrib"])
    _write_csv(capacity_df, files["capacity"])
    files["summary"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if write_latest:
        latest_map = {
            "risk_exposure_summary_latest.csv": exposure_df,
            "risk_exposure_industry_latest.csv": industry_df,
            "return_attribution_latest.csv": attrib_df,
            "capacity_cost_latest.csv": capacity_df,
        }
        for name, df in latest_map.items():
            _write_csv(df, out_dir / name)
        (out_dir / "p1_analytics_summary_latest.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return list(files.values())


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="P1 风险暴露/归因/容量诊断")
    p.add_argument("--trades-file", type=str, default=None, help="指定回测交易明细 CSV")
    p.add_argument("--summary-file", type=str, default=None, help="指定回测汇总 CSV")
    p.add_argument("--capital-base", type=float, default=float(os.environ.get("MFTS_CAPITAL_BASE", "5000000")), help="容量评估资金规模（元）")
    p.add_argument("--adv-participation", type=float, default=float(os.environ.get("MFTS_ADV_PARTICIPATION", "0.05")), help="单票成交额参与率上限(0~1)")
    p.add_argument("--fee-bps", type=float, default=None, help="单边手续费 bps；不传则读取回测汇总")
    p.add_argument("--slippage-bps", type=float, default=None, help="单边滑点 bps；不传则读取回测汇总")
    p.add_argument("--stamp-tax-bps", type=float, default=float(os.environ.get("MFTS_STAMP_TAX_BPS", "10")), help="卖出印花税 bps")
    p.add_argument("--write-latest", action="store_true", help="额外写入 *_latest 便捷文件")
    p.add_argument("--strict", action="store_true", help="无交易文件时返回失败码")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    trade_file = _resolve_latest_trade_file(args.trades_file)
    if trade_file is None:
        _log("未找到 quant_trades_*.csv，跳过 P1 报告生成。")
        return 1 if args.strict else 0

    summary_file = _resolve_summary_file(args.summary_file)
    summary_row = _load_summary_row(summary_file)

    fee_bps = float(args.fee_bps if args.fee_bps is not None else summary_row.get("fee_bps", 8.0))
    slippage_bps = float(args.slippage_bps if args.slippage_bps is not None else summary_row.get("slippage_bps", 5.0))
    stamp_tax_bps = max(0.0, float(args.stamp_tax_bps))
    capital_base = max(100000.0, float(args.capital_base))
    adv_participation = min(max(float(args.adv_participation), 0.005), 0.50)

    _log(f"读取交易明细: {trade_file}")
    trades_df = _load_trades(trade_file)
    if trades_df.empty:
        _log("交易明细为空，跳过 P1 报告生成。")
        return 1 if args.strict else 0

    _log("加载行业映射与成交额数据...")
    analysis_start = trades_df["entry_date"].min()
    analysis_end = trades_df["exit_date"].max() if "exit_date" in trades_df.columns else trades_df["entry_date"].max()
    if pd.isna(analysis_end):
        analysis_end = trades_df["entry_date"].max()
    industry_map = _load_industry_map(analysis_end)
    bars_idx = _load_bars_index(analysis_start, analysis_end)

    diag_df, position_df = _build_trade_and_position_frames(
        trades_df=trades_df,
        bars_idx=bars_idx,
        industry_map=industry_map,
        capital_base=capital_base,
        adv_participation=adv_participation,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        stamp_tax_bps=stamp_tax_bps,
    )
    if diag_df.empty:
        _log("交易解析后无有效样本，跳过 P1 报告生成。")
        return 1 if args.strict else 0

    exposure_df = _build_exposure_summary(diag_df)
    industry_df = _build_industry_exposure(position_df)
    attrib_df = _build_attribution(diag_df)
    capacity_df = _build_capacity_cost(diag_df, capital_base=capital_base)
    summary = _json_summary(
        trade_file=trade_file,
        diag_df=diag_df,
        capital_df=capacity_df,
        capital_base=capital_base,
        adv_participation=adv_participation,
    )
    files = _write_outputs(
        exposure_df=exposure_df,
        industry_df=industry_df,
        attrib_df=attrib_df,
        capacity_df=capacity_df,
        summary=summary,
        write_latest=bool(args.write_latest),
    )

    _log("P1 报告生成完成:")
    for p in files:
        _log(f"  - {p}")
    _log(
        "关键指标: "
        f"trades={summary.get('trade_count', 0)}, "
        f"avg_exposure={summary.get('avg_exposure_pct', 0.0):.2f}%, "
        f"win_rate={summary.get('win_rate_pct', 0.0):.2f}%, "
        f"median_capacity={summary.get('median_trade_capacity_capital', 0.0):.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
