#!/usr/bin/env python3
"""
回测 vs 执行一致性偏差报告。

目标：
1) 对齐 backtest 预期收益与执行账本实际收益
2) 拆解偏差来源（订单阻塞、风控拦截、成本估算）
3) 生成日级明细 + 汇总 JSON
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from utils.output_paths import get_output_dirs, list_dual
from utils.code_utils import normalize_ts_code, normalize_ts_code_series

OUTPUT_DIR = Path(BASE_DIR) / "output"


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


def _safe_trade_date_set(df: pd.DataFrame, col: str) -> set[str]:
    if df is None or df.empty or col not in df.columns:
        return set()
    s = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    s = s.dropna().astype(str).str.strip()
    return {x for x in s.tolist() if x and x.lower() != "nat"}


def _load_ledger_trade_dates(ledger_file: Path) -> set[str]:
    try:
        df = pd.read_csv(ledger_file, usecols=["trade_date"])
    except Exception:
        try:
            df = pd.read_csv(ledger_file)
        except Exception:
            return set()
    return _safe_trade_date_set(df, "trade_date")


def _score_trades_overlap(trades_file: Path, ledger_dates: set[str]) -> dict[str, float]:
    score = {
        "intersect_count": 0.0,
        "ledger_coverage_pct": 0.0,
        "expected_rows": 0.0,
        "expected_date_count": 0.0,
    }
    try:
        expected_df = _load_expected(trades_file)
    except Exception:
        return score
    if expected_df.empty:
        return score
    exp_dates = _safe_trade_date_set(expected_df, "trade_date")
    if not exp_dates:
        return score
    inter = len(exp_dates & ledger_dates) if ledger_dates else 0
    score["intersect_count"] = float(inter)
    score["ledger_coverage_pct"] = float(inter / max(len(ledger_dates), 1) * 100.0) if ledger_dates else 0.0
    score["expected_rows"] = float(len(expected_df))
    score["expected_date_count"] = float(len(exp_dates))
    return score


def _resolve_latest_trades_file(
    explicit: str | None,
    ledger_file: Path | None = None,
    auto_select: bool = True,
) -> tuple[Path | None, dict[str, object]]:
    if explicit:
        p = Path(explicit)
        return (p if p.exists() else None), {"mode": "explicit"}
    dirs = get_output_dirs(OUTPUT_DIR)
    files = list_dual(["quant_trades_*.csv"], dirs["backtest"], dirs["base"])
    if not files:
        return None, {"mode": "empty"}
    files = sorted(files)
    latest = files[-1]
    meta: dict[str, object] = {
        "mode": "latest",
        "selected": str(latest),
        "candidate_count": int(len(files)),
    }
    if (not auto_select) or ledger_file is None or (not ledger_file.exists()):
        return latest, meta

    ledger_dates = _load_ledger_trade_dates(ledger_file)
    if not ledger_dates:
        return latest, meta

    best_file = latest
    best_key = (-1.0, -1.0, -1.0, "")
    best_score: dict[str, float] = {}
    for fp in files:
        s = _score_trades_overlap(fp, ledger_dates)
        key = (
            float(s["intersect_count"]),
            float(s["ledger_coverage_pct"]),
            float(s["expected_rows"]),
            fp.name,
        )
        if key > best_key:
            best_key = key
            best_file = fp
            best_score = s
    # 若所有候选与 ledger 完全无重叠，回退到最新文件，避免被“历史长样本”误选。
    if float(best_score.get("intersect_count", 0.0)) <= 0.0:
        meta.update(
            {
                "mode": "auto_select_no_overlap",
                "selected": str(latest),
                "latest_default": str(latest),
                "intersect_count": 0,
                "ledger_coverage_pct": 0.0,
                "expected_rows": 0,
                "expected_date_count": 0,
            }
        )
        return latest, meta
    meta.update(
        {
            "mode": "auto_select",
            "selected": str(best_file),
            "latest_default": str(latest),
            "intersect_count": int(best_score.get("intersect_count", 0.0)),
            "ledger_coverage_pct": float(best_score.get("ledger_coverage_pct", 0.0)),
            "expected_rows": int(best_score.get("expected_rows", 0.0)),
            "expected_date_count": int(best_score.get("expected_date_count", 0.0)),
        }
    )
    return best_file, meta


def _resolve_ledger_file(explicit: str | None, broker: str) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    cand = OUTPUT_DIR / "execution" / f"{broker}_ledger.csv"
    return cand if cand.exists() else None


def _extract_run_id_from_filename(file_name: str, broker: str, kind: str) -> str:
    pat = re.compile(rf"^{re.escape(broker)}_{re.escape(kind)}_\d{{8}}_(.+)\.csv$")
    m = pat.match(file_name)
    if not m:
        return ""
    return str(m.group(1)).strip()


def _normalize_reason_token(token: object) -> str:
    s = str(token or "").strip()
    if not s:
        return "unknown"
    low = s.lower()
    if low in {"nan", "none", "null"}:
        return "unknown"
    return s


def _counter_to_json(counter: Counter[str]) -> str:
    if not counter:
        return "{}"
    ordered = dict(sorted(counter.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))))
    return json.dumps({str(k): int(v) for k, v in ordered.items()}, ensure_ascii=False)


def _top_reason(counter: Counter[str]) -> tuple[str, int]:
    if not counter:
        return "none", 0
    ordered = sorted(counter.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
    return str(ordered[0][0]), int(ordered[0][1])


def _load_order_reasons_by_run(broker: str, target_run_ids: set[str]) -> pd.DataFrame:
    exec_dir = OUTPUT_DIR / "execution"
    files = sorted(exec_dir.glob(f"{broker}_orders_*.csv"))
    rows: list[dict[str, object]] = []
    for fp in files:
        run_id = _extract_run_id_from_filename(fp.name, broker=broker, kind="orders")
        if not run_id:
            continue
        if target_run_ids and run_id not in target_run_ids:
            continue
        try:
            df = pd.read_csv(fp)
        except Exception:
            continue
        if df.empty:
            rows.append(
                {
                    "run_id": run_id,
                    "order_block_reason_top": "none",
                    "order_block_reason_top_count": 0,
                    "order_block_reason_total": 0,
                    "order_block_reason_breakdown": "{}",
                }
            )
            continue
        if "status" not in df.columns or "reason" not in df.columns:
            rows.append(
                {
                    "run_id": run_id,
                    "order_block_reason_top": "none",
                    "order_block_reason_top_count": 0,
                    "order_block_reason_total": 0,
                    "order_block_reason_breakdown": "{}",
                }
            )
            continue
        status = df["status"].astype(str).str.strip().str.lower()
        reason = df["reason"].apply(_normalize_reason_token)
        blocked_df = df[status.isin({"blocked", "rejected"})].copy()
        if blocked_df.empty:
            rows.append(
                {
                    "run_id": run_id,
                    "order_block_reason_top": "none",
                    "order_block_reason_top_count": 0,
                    "order_block_reason_total": 0,
                    "order_block_reason_breakdown": "{}",
                }
            )
            continue
        reason_counter: Counter[str] = Counter(reason.loc[blocked_df.index].tolist())
        top_reason, top_count = _top_reason(reason_counter)
        rows.append(
            {
                "run_id": run_id,
                "order_block_reason_top": top_reason,
                "order_block_reason_top_count": int(top_count),
                "order_block_reason_total": int(sum(reason_counter.values())),
                "order_block_reason_breakdown": _counter_to_json(reason_counter),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "run_id",
                "order_block_reason_top",
                "order_block_reason_top_count",
                "order_block_reason_total",
                "order_block_reason_breakdown",
            ]
        )
    out = pd.DataFrame(rows)
    out["run_id"] = out["run_id"].astype(str).str.strip()
    out = out.sort_values("run_id").drop_duplicates(subset=["run_id"], keep="last")
    return out.reset_index(drop=True)


def _load_risk_reasons_by_run(broker: str, target_run_ids: set[str]) -> pd.DataFrame:
    exec_dir = OUTPUT_DIR / "execution"
    files = sorted(exec_dir.glob(f"{broker}_risk_gates_*.csv"))
    rows: list[dict[str, object]] = []
    for fp in files:
        run_id = _extract_run_id_from_filename(fp.name, broker=broker, kind="risk_gates")
        if not run_id:
            continue
        if target_run_ids and run_id not in target_run_ids:
            continue
        try:
            df = pd.read_csv(fp)
        except Exception:
            df = pd.DataFrame()

        reason_counter: Counter[str] = Counter()
        if not df.empty and "reasons" in df.columns:
            for txt in df["reasons"].astype(str).fillna(""):
                for tok in str(txt).split(","):
                    reason = _normalize_reason_token(tok)
                    if reason != "unknown":
                        reason_counter[reason] += 1
        top_reason, top_count = _top_reason(reason_counter)
        rows.append(
            {
                "run_id": run_id,
                "risk_block_reason_top": top_reason,
                "risk_block_reason_top_count": int(top_count),
                "risk_block_reason_total": int(sum(reason_counter.values())),
                "risk_block_reason_breakdown": _counter_to_json(reason_counter),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "run_id",
                "risk_block_reason_top",
                "risk_block_reason_top_count",
                "risk_block_reason_total",
                "risk_block_reason_breakdown",
            ]
        )
    out = pd.DataFrame(rows)
    out["run_id"] = out["run_id"].astype(str).str.strip()
    out = out.sort_values("run_id").drop_duplicates(subset=["run_id"], keep="last")
    return out.reset_index(drop=True)


def _load_expected(trades_file: Path) -> pd.DataFrame:
    df = pd.read_csv(trades_file)
    if df.empty:
        return pd.DataFrame()
    if "entry_date" not in df.columns or "portfolio_ret" not in df.columns:
        return pd.DataFrame()
    df["entry_date"] = pd.to_datetime(df["entry_date"], errors="coerce").dt.normalize()
    for c in ("portfolio_ret", "excess_ret", "total_exposure"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["entry_date", "portfolio_ret"])
    if df.empty:
        return pd.DataFrame()
    agg_spec: dict[str, tuple[str, object]] = {
        "expected_trade_count": ("portfolio_ret", "count"),
        "expected_ret_pct": ("portfolio_ret", lambda s: float(np.mean(s) * 100.0)),
    }
    if "excess_ret" in df.columns:
        agg_spec["expected_excess_ret_pct"] = ("excess_ret", lambda s: float(np.mean(s) * 100.0))
    if "total_exposure" in df.columns:
        agg_spec["expected_exposure_pct"] = ("total_exposure", lambda s: float(np.mean(s) * 100.0))

    out = df.groupby("entry_date", as_index=False).agg(**agg_spec).sort_values("entry_date")
    if "expected_excess_ret_pct" not in out.columns:
        out["expected_excess_ret_pct"] = np.nan
    if "expected_exposure_pct" not in out.columns:
        out["expected_exposure_pct"] = np.nan
    out["trade_date"] = out["entry_date"].dt.strftime("%Y-%m-%d")
    return out.drop(columns=["entry_date"])


def _load_actual(ledger_file: Path) -> pd.DataFrame:
    df = pd.read_csv(ledger_file)
    if df.empty:
        return pd.DataFrame()
    if "run_id" in df.columns:
        df["run_id"] = df["run_id"].astype(str).str.strip()
    else:
        df["run_id"] = ""
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for c in [
        "nav_pre",
        "nav_post",
        "turnover",
        "filled_orders",
        "partial_orders",
        "blocked_orders",
        "rejected_orders",
        "risk_input_count",
        "risk_blocked_count",
        "risk_style_limits_hit",
        "risk_style_size_limits_hit",
        "risk_style_beta_limits_hit",
        "risk_style_momentum_limits_hit",
        "risk_style_vol_limits_hit",
    ]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        else:
            df[c] = 0.0
    df["actual_ret_pct"] = np.where(df["nav_pre"] > 0, (df["nav_post"] / df["nav_pre"] - 1.0) * 100.0, np.nan)
    return df.sort_values("trade_date").reset_index(drop=True)


def _style_hit_bucket(v: object) -> str:
    x = int(round(_safe_float(v, 0.0)))
    if x <= 0:
        return "hit=0"
    if x == 1:
        return "hit=1"
    if x == 2:
        return "hit=2"
    if x <= 4:
        return "hit=3-4"
    return "hit>=5"


def _dominant_style_driver(row: pd.Series) -> str:
    vals = {
        "size": int(round(_safe_float(row.get("risk_style_size_limits_hit", 0.0), 0.0))),
        "beta": int(round(_safe_float(row.get("risk_style_beta_limits_hit", 0.0), 0.0))),
        "momentum": int(round(_safe_float(row.get("risk_style_momentum_limits_hit", 0.0), 0.0))),
        "vol": int(round(_safe_float(row.get("risk_style_vol_limits_hit", 0.0), 0.0))),
    }
    mx = max(vals.values()) if vals else 0
    if mx <= 0:
        return "none"
    leaders = [k for k, v in vals.items() if v == mx]
    if len(leaders) > 1:
        return "mixed"
    return str(leaders[0])


def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    aa = pd.to_numeric(a, errors="coerce")
    bb = pd.to_numeric(b, errors="coerce")
    mask = aa.notna() & bb.notna()
    aa = aa[mask]
    bb = bb[mask]
    if len(aa) < 3:
        return 0.0
    if float(aa.std(ddof=0)) <= 1e-12 or float(bb.std(ddof=0)) <= 1e-12:
        return 0.0
    c = aa.corr(bb)
    return float(c) if pd.notna(c) else 0.0


def _agg_layer_metrics(layer_type: str, layer_key: str, group_df: pd.DataFrame) -> dict[str, object]:
    matched = group_df[group_df["matched_backtest"] == 1].copy() if "matched_backtest" in group_df.columns else group_df
    ret_gap = pd.to_numeric(matched.get("ret_gap_pct", np.nan), errors="coerce")
    abs_gap = ret_gap.abs()
    style_hit = pd.to_numeric(group_df.get("risk_style_limits_hit", 0.0), errors="coerce").fillna(0.0)
    risk_input = pd.to_numeric(group_df.get("risk_input_count", 0.0), errors="coerce").fillna(0.0)
    style_hit_density = np.where(risk_input > 0, style_hit / risk_input * 100.0, np.nan)
    return {
        "layer_type": str(layer_type),
        "layer_key": str(layer_key),
        "rows": int(len(group_df)),
        "matched_rows": int(len(matched)),
        "coverage_pct": float(len(matched) / max(len(group_df), 1) * 100.0),
        "expected_ret_mean_pct": float(pd.to_numeric(matched.get("expected_ret_pct", np.nan), errors="coerce").mean()),
        "actual_ret_mean_pct": float(pd.to_numeric(matched.get("actual_ret_pct", np.nan), errors="coerce").mean()),
        "ret_gap_mean_pct": float(ret_gap.mean()),
        "ret_gap_mae_pct": float(abs_gap.mean()),
        "ret_gap_abs_p50_pct": float(abs_gap.quantile(0.5)),
        "ret_gap_abs_p90_pct": float(abs_gap.quantile(0.9)),
        "order_block_rate_mean_pct": float(pd.to_numeric(matched.get("order_block_rate_pct", np.nan), errors="coerce").mean()),
        "risk_block_rate_mean_pct": float(pd.to_numeric(matched.get("risk_block_rate_pct", np.nan), errors="coerce").mean()),
        "style_hit_mean": float(style_hit.mean()),
        "style_hit_density_mean_pct": float(pd.Series(style_hit_density, dtype=float).mean()),
    }


def _build_style_gap_attribution(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "layer_type",
        "layer_key",
        "rows",
        "matched_rows",
        "coverage_pct",
        "expected_ret_mean_pct",
        "actual_ret_mean_pct",
        "ret_gap_mean_pct",
        "ret_gap_mae_pct",
        "ret_gap_abs_p50_pct",
        "ret_gap_abs_p90_pct",
        "order_block_rate_mean_pct",
        "risk_block_rate_mean_pct",
        "style_hit_mean",
        "style_hit_density_mean_pct",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    work = df.copy()
    for c in [
        "risk_style_limits_hit",
        "risk_style_size_limits_hit",
        "risk_style_beta_limits_hit",
        "risk_style_momentum_limits_hit",
        "risk_style_vol_limits_hit",
        "risk_input_count",
    ]:
        if c not in work.columns:
            work[c] = 0.0
        work[c] = pd.to_numeric(work[c], errors="coerce").fillna(0.0)
    if "matched_backtest" not in work.columns:
        work["matched_backtest"] = 0

    work["style_hit_bucket"] = work["risk_style_limits_hit"].apply(_style_hit_bucket)
    work["style_driver"] = work.apply(_dominant_style_driver, axis=1)

    rows: list[dict[str, object]] = []
    hit_order = {"hit=0": 0, "hit=1": 1, "hit=2": 2, "hit=3-4": 3, "hit>=5": 4}
    for k, g in work.groupby("style_hit_bucket", dropna=False):
        rows.append(_agg_layer_metrics("style_hit_bucket", str(k), g))
    for k, g in work.groupby("style_driver", dropna=False):
        rows.append(_agg_layer_metrics("style_driver", str(k), g))

    out = pd.DataFrame(rows, columns=cols)
    if out.empty:
        return out
    out["_layer_rank"] = np.where(
        out["layer_type"] == "style_hit_bucket",
        out["layer_key"].map(hit_order).fillna(99).astype(int),
        99,
    )
    out = out.sort_values(["layer_type", "_layer_rank", "layer_key"]).drop(columns=["_layer_rank"])
    return out.reset_index(drop=True)


def _split_codes(raw: object) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    out: list[str] = []
    for tok in s.split(","):
        code = normalize_ts_code(tok)
        if code:
            out.append(code)
    return out


def _split_weights(raw: object) -> list[float]:
    s = str(raw or "").strip()
    if not s:
        return []
    out: list[float] = []
    for tok in s.split(","):
        try:
            v = float(tok)
        except Exception:
            continue
        if np.isfinite(v):
            out.append(float(v))
    return out


def _load_expected_code_map(trades_file: Path) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    try:
        df = pd.read_csv(trades_file, usecols=["entry_date", "codes", "weights"])
    except Exception:
        try:
            df = pd.read_csv(trades_file)
        except Exception:
            return out
    if df.empty or "entry_date" not in df.columns or "codes" not in df.columns:
        return out
    dt = pd.to_datetime(df["entry_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.assign(trade_date=dt)
    df = df[df["trade_date"].notna()].copy()
    for _, row in df.iterrows():
        d = str(row.get("trade_date") or "").strip()
        if not d:
            continue
        codes = _split_codes(row.get("codes", ""))
        weights = _split_weights(row.get("weights", ""))
        if d not in out:
            out[d] = {"codes": set(), "weight_map": {}}
        for i, code in enumerate(codes):
            out[d]["codes"].add(code)
            if i < len(weights):
                out[d]["weight_map"][code] = float(weights[i])
    return out


def _load_order_detail_by_run(broker: str, target_run_ids: set[str]) -> pd.DataFrame:
    exec_dir = OUTPUT_DIR / "execution"
    files = sorted(exec_dir.glob(f"{broker}_orders_*.csv"))
    rows: list[pd.DataFrame] = []
    for fp in files:
        run_id = _extract_run_id_from_filename(fp.name, broker=broker, kind="orders")
        if not run_id:
            continue
        if target_run_ids and run_id not in target_run_ids:
            continue
        try:
            df = pd.read_csv(fp, dtype={"code": str})
        except Exception:
            continue
        if df.empty:
            continue
        df["run_id"] = df.get("run_id", run_id)
        df["run_id"] = df["run_id"].astype(str).str.strip()
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        else:
            df["trade_date"] = ""
        if "signal_date" in df.columns:
            df["signal_date"] = pd.to_datetime(df["signal_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        else:
            df["signal_date"] = ""
        if "code" in df.columns:
            df["code"] = normalize_ts_code_series(df["code"])
        else:
            df["code"] = ""
        for c in ["requested_qty", "filled_qty", "rank"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
            else:
                df[c] = 0.0
        if "status" not in df.columns:
            df["status"] = "unknown"
        df["status"] = df["status"].astype(str).str.strip().str.lower()
        if "reason" not in df.columns:
            df["reason"] = "unknown"
        df["reason"] = df["reason"].apply(_normalize_reason_token)
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out = out[out["run_id"].astype(str).str.strip() != ""].copy()
    return out.reset_index(drop=True)


def _build_tick_replay(
    report_df: pd.DataFrame,
    trades_file: Path,
    broker: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    detail_cols = [
        "run_id",
        "signal_date",
        "trade_date",
        "code",
        "side",
        "rank",
        "status",
        "reason",
        "requested_qty",
        "filled_qty",
        "fill_rate_pct",
        "expected_in_backtest",
        "expected_weight",
        "matched_backtest",
        "expected_ret_pct",
        "actual_ret_pct",
        "ret_gap_pct",
        "risk_style_limits_hit",
        "risk_block_rate_pct",
        "order_block_rate_pct",
    ]
    if report_df is None or report_df.empty:
        empty = pd.DataFrame(columns=detail_cols)
        return empty, pd.DataFrame(), {"rows": 0, "runs": 0}

    target_run_ids = set(report_df.get("run_id", pd.Series(dtype=str)).astype(str).str.strip().tolist())
    order_df = _load_order_detail_by_run(broker=broker, target_run_ids=target_run_ids)
    if order_df.empty:
        empty = pd.DataFrame(columns=detail_cols)
        return empty, pd.DataFrame(), {"rows": 0, "runs": int(len(target_run_ids))}

    expected_map = _load_expected_code_map(trades_file)
    base_cols = [
        "run_id",
        "trade_date",
        "matched_backtest",
        "expected_ret_pct",
        "actual_ret_pct",
        "ret_gap_pct",
        "risk_style_limits_hit",
        "risk_block_rate_pct",
        "order_block_rate_pct",
    ]
    base = report_df.copy()
    for c in base_cols:
        if c not in base.columns:
            base[c] = np.nan if c not in {"run_id", "trade_date"} else ""
    base["run_id"] = base["run_id"].astype(str).str.strip()
    base["trade_date"] = pd.to_datetime(base["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    base = base[base_cols].drop_duplicates(subset=["run_id"], keep="last")

    merged = order_df.merge(base, on="run_id", how="left", suffixes=("", "_r"))
    merged["trade_date"] = merged["trade_date"].fillna(merged.get("trade_date_r", ""))
    merged = merged.drop(columns=[c for c in merged.columns if c.endswith("_r")], errors="ignore")

    expected_flags: list[int] = []
    expected_weights: list[float] = []
    for _, row in merged.iterrows():
        trade_date = str(row.get("trade_date") or "").strip()
        code = normalize_ts_code(row.get("code", ""))
        em = expected_map.get(trade_date, {})
        code_set = em.get("codes", set()) if isinstance(em, dict) else set()
        weight_map = em.get("weight_map", {}) if isinstance(em, dict) else {}
        in_expected = int(code in code_set)
        expected_flags.append(in_expected)
        if in_expected:
            expected_weights.append(float(_safe_float(weight_map.get(code, np.nan), np.nan)))
        else:
            expected_weights.append(np.nan)
    merged["expected_in_backtest"] = expected_flags
    merged["expected_weight"] = expected_weights
    merged["fill_rate_pct"] = np.where(
        pd.to_numeric(merged["requested_qty"], errors="coerce").fillna(0.0) > 0,
        pd.to_numeric(merged["filled_qty"], errors="coerce").fillna(0.0)
        / pd.to_numeric(merged["requested_qty"], errors="coerce").fillna(0.0)
        * 100.0,
        np.nan,
    )

    detail = merged.copy()
    for c in detail_cols:
        if c not in detail.columns:
            detail[c] = np.nan
    detail = detail[detail_cols].sort_values(["trade_date", "run_id", "rank", "code"]).reset_index(drop=True)

    layer_rows: list[dict[str, object]] = []
    for (exp_flag, side, status), g in detail.groupby(["expected_in_backtest", "side", "status"], dropna=False):
        gap = pd.to_numeric(g.get("ret_gap_pct", np.nan), errors="coerce")
        abs_gap = gap.abs()
        layer_rows.append(
            {
                "expected_in_backtest": int(_safe_float(exp_flag, 0.0)),
                "side": str(side),
                "status": str(status),
                "rows": int(len(g)),
                "fill_rate_mean_pct": float(pd.to_numeric(g.get("fill_rate_pct", np.nan), errors="coerce").mean()),
                "ret_gap_mean_pct": float(gap.mean()),
                "ret_gap_mae_pct": float(abs_gap.mean()),
                "style_hit_mean": float(pd.to_numeric(g.get("risk_style_limits_hit", np.nan), errors="coerce").mean()),
            }
        )
    layer_df = pd.DataFrame(layer_rows).sort_values(
        ["expected_in_backtest", "side", "status"]
    ) if layer_rows else pd.DataFrame()

    blocked = detail[detail["status"].astype(str).isin(["blocked", "rejected"])].copy()
    reason_top = "none"
    reason_top_count = 0
    if not blocked.empty:
        vc = blocked["reason"].astype(str).value_counts()
        if len(vc) > 0:
            reason_top = str(vc.index[0])
            reason_top_count = int(vc.iloc[0])

    summary = {
        "rows": int(len(detail)),
        "runs": int(detail["run_id"].astype(str).nunique()),
        "expected_member_order_ratio_pct": float(detail["expected_in_backtest"].mean() * 100.0) if len(detail) else 0.0,
        "fill_rate_mean_pct": float(pd.to_numeric(detail["fill_rate_pct"], errors="coerce").mean()) if len(detail) else 0.0,
        "blocked_order_ratio_pct": float((detail["status"].astype(str).isin(["blocked", "rejected"]).sum()) / max(len(detail), 1) * 100.0),
        "ret_gap_mae_pct": float(pd.to_numeric(detail["ret_gap_pct"], errors="coerce").abs().mean()) if len(detail) else 0.0,
        "blocked_reason_top": str(reason_top),
        "blocked_reason_top_count": int(reason_top_count),
    }
    return detail, layer_df, summary


def _dedupe_actual_by_trade_date(actual_df: pd.DataFrame) -> pd.DataFrame:
    """同一交易日保留最后一次 run，避免重复回放污染一致性覆盖率。"""
    if actual_df is None or actual_df.empty or "trade_date" not in actual_df.columns:
        return actual_df
    work = actual_df.copy()
    work["_idx"] = np.arange(len(work))
    work = work.sort_values(["trade_date", "_idx"]).drop_duplicates(subset=["trade_date"], keep="last")
    return work.drop(columns=["_idx"]).reset_index(drop=True)


def _pick_primary_gap_driver(row: pd.Series) -> tuple[str, str]:
    contrib = {
        "cost": abs(_safe_float(row.get("est_cost_pct", 0.0), 0.0)),
        "order_blocking": abs(_safe_float(row.get("order_block_penalty_pct", 0.0), 0.0)),
        "risk_gates": abs(_safe_float(row.get("risk_gate_penalty_pct", 0.0), 0.0)),
        "unexplained": abs(_safe_float(row.get("unexplained_gap_pct", 0.0), 0.0)),
    }
    if max(contrib.values()) <= 1e-12:
        return "none", "none"
    order = ["order_blocking", "risk_gates", "cost", "unexplained"]
    best = order[0]
    for k in order[1:]:
        if contrib[k] > contrib[best]:
            best = k
    if best == "order_blocking":
        reason = str(row.get("order_block_reason_top", "none") or "none")
        return best, f"order_blocking:{reason}"
    if best == "risk_gates":
        reason = str(row.get("risk_block_reason_top", "none") or "none")
        return best, f"risk_gates:{reason}"
    if best == "cost":
        return best, "cost:fee+slippage+stamp_tax"
    return best, "unexplained:model_or_execution"


def _build_consistency(
    expected_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    fee_bps: float,
    slippage_bps: float,
    stamp_tax_bps: float,
    broker: str,
) -> pd.DataFrame:
    if actual_df.empty:
        return pd.DataFrame()
    work = actual_df.copy()
    if "actual_ret_pct" not in work.columns:
        if "nav_pre" in work.columns and "nav_post" in work.columns:
            work["actual_ret_pct"] = np.where(work["nav_pre"] > 0, (work["nav_post"] / work["nav_pre"] - 1.0) * 100.0, np.nan)
        else:
            work["actual_ret_pct"] = np.nan
    merged = work.merge(expected_df, on="trade_date", how="left")

    merged["ret_gap_pct"] = merged["actual_ret_pct"] - merged["expected_ret_pct"]
    merged["total_orders"] = (
        merged["filled_orders"] + merged["partial_orders"] + merged["blocked_orders"] + merged["rejected_orders"]
    )
    merged["order_fill_rate_pct"] = np.where(
        merged["total_orders"] > 0,
        (merged["filled_orders"] + merged["partial_orders"]) / merged["total_orders"] * 100.0,
        np.nan,
    )
    merged["order_block_rate_pct"] = np.where(
        merged["total_orders"] > 0,
        (merged["blocked_orders"] + merged["rejected_orders"]) / merged["total_orders"] * 100.0,
        np.nan,
    )
    merged["risk_block_rate_pct"] = np.where(
        merged["risk_input_count"] > 0,
        merged["risk_blocked_count"] / merged["risk_input_count"] * 100.0,
        np.nan,
    )

    # 成本估算：turnover * (fee + slippage + stamp/2)
    cost_rate = (fee_bps + slippage_bps + stamp_tax_bps * 0.5) / 10000.0
    merged["est_cost_amt"] = merged["turnover"] * cost_rate
    merged["est_cost_pct"] = np.where(merged["nav_pre"] > 0, merged["est_cost_amt"] / merged["nav_pre"] * 100.0, np.nan)

    exp_abs = merged["expected_ret_pct"].abs().fillna(0.0)
    merged["order_block_penalty_pct"] = exp_abs * merged["order_block_rate_pct"].fillna(0.0) / 100.0
    merged["risk_gate_penalty_pct"] = exp_abs * merged["risk_block_rate_pct"].fillna(0.0) / 100.0
    merged["unexplained_gap_pct"] = (
        merged["ret_gap_pct"]
        + merged["est_cost_pct"].fillna(0.0)
        + merged["order_block_penalty_pct"].fillna(0.0)
        + merged["risk_gate_penalty_pct"].fillna(0.0)
    )
    merged["matched_backtest"] = merged["expected_ret_pct"].notna().astype(int)

    # 订单/风控拦截原因（按 run_id 对齐）
    target_run_ids = set(merged["run_id"].astype(str).str.strip().tolist()) if "run_id" in merged.columns else set()
    order_reason_df = _load_order_reasons_by_run(broker=broker, target_run_ids=target_run_ids)
    risk_reason_df = _load_risk_reasons_by_run(broker=broker, target_run_ids=target_run_ids)
    if "run_id" in merged.columns:
        merged["run_id"] = merged["run_id"].astype(str).str.strip()
    if not order_reason_df.empty:
        merged = merged.merge(order_reason_df, on="run_id", how="left")
    if not risk_reason_df.empty:
        merged = merged.merge(risk_reason_df, on="run_id", how="left")

    for c, default in [
        ("order_block_reason_top", "none"),
        ("order_block_reason_top_count", 0),
        ("order_block_reason_total", 0),
        ("order_block_reason_breakdown", "{}"),
        ("risk_block_reason_top", "none"),
        ("risk_block_reason_top_count", 0),
        ("risk_block_reason_total", 0),
        ("risk_block_reason_breakdown", "{}"),
    ]:
        if c not in merged.columns:
            merged[c] = default
        else:
            if isinstance(default, str):
                merged[c] = merged[c].fillna(default).astype(str)
            else:
                merged[c] = pd.to_numeric(merged[c], errors="coerce").fillna(float(default))

    # 偏差主因（按贡献绝对值）
    primary_pairs = merged.apply(_pick_primary_gap_driver, axis=1).tolist()
    merged["primary_gap_driver"] = [x[0] for x in primary_pairs]
    merged["primary_gap_driver_detail"] = [x[1] for x in primary_pairs]
    return merged


def _build_summary(
    df: pd.DataFrame,
    broker: str,
    trades_file: Path,
    ledger_file: Path,
    max_ret_gap_mae_pct: float,
    min_match_coverage_pct: float,
    max_order_block_rate_pct: float,
    max_risk_block_rate_pct: float,
    min_matched_rows: int,
    rate_eval_rows: int = 0,
) -> dict[str, object]:
    base: dict[str, object] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "broker": broker,
        "trades_file": str(trades_file),
        "ledger_file": str(ledger_file),
        "rows": int(len(df)),
        "matched_rows": 0,
        "coverage_pct": 0.0,
        "expected_ret_mean_pct": 0.0,
        "actual_ret_mean_pct": 0.0,
        "ret_gap_mean_pct": 0.0,
        "ret_gap_mae_pct": 0.0,
        "order_fill_rate_mean_pct": 0.0,
        "order_block_rate_mean_pct": 0.0,
        "risk_block_rate_mean_pct": 0.0,
        "est_cost_mean_pct": 0.0,
        "unexplained_gap_mean_pct": 0.0,
        "primary_driver_top": "none",
        "primary_driver_top_count": 0,
        "thresholds": {
            "max_ret_gap_mae_pct": float(max_ret_gap_mae_pct),
            "min_match_coverage_pct": float(min_match_coverage_pct),
            "max_order_block_rate_pct": float(max_order_block_rate_pct),
            "max_risk_block_rate_pct": float(max_risk_block_rate_pct),
            "min_matched_rows": int(min_matched_rows),
            "rate_eval_rows": int(max(0, rate_eval_rows)),
        },
    }
    if df.empty:
        base["checks"] = {
            "matched_rows": {"actual": 0, "limit": int(min_matched_rows), "pass": False},
            "coverage_pct": {"actual": 0.0, "limit": float(min_match_coverage_pct), "pass": False},
            "ret_gap_mae_pct": {"actual": 0.0, "limit": float(max_ret_gap_mae_pct), "pass": False},
            "order_block_rate_mean_pct": {"actual": 0.0, "limit": float(max_order_block_rate_pct), "pass": False},
            "risk_block_rate_mean_pct": {"actual": 0.0, "limit": float(max_risk_block_rate_pct), "pass": False},
        }
        base["consistency_pass"] = False
        base["fail_reasons"] = ["empty_report"]
        return base

    matched = df[df["matched_backtest"] == 1].copy()
    base["matched_rows"] = int(len(matched))
    base["coverage_pct"] = float(len(matched) / max(len(df), 1) * 100.0)
    matched_eval = matched
    if int(rate_eval_rows) > 0 and len(matched) > int(rate_eval_rows):
        matched_eval = matched.sort_values("trade_date").tail(int(rate_eval_rows)).copy()
    base["rate_eval_rows_used"] = int(len(matched_eval))
    if not matched.empty:
        order_block_mean = float(matched_eval["order_block_rate_pct"].mean()) if not matched_eval.empty else 0.0
        risk_block_mean = float(matched_eval["risk_block_rate_pct"].mean()) if not matched_eval.empty else 0.0
        base.update(
            {
                "expected_ret_mean_pct": float(matched["expected_ret_pct"].mean()),
                "actual_ret_mean_pct": float(matched["actual_ret_pct"].mean()),
                "ret_gap_mean_pct": float(matched["ret_gap_pct"].mean()),
                "ret_gap_mae_pct": float(np.mean(np.abs(matched["ret_gap_pct"]))),
                "order_fill_rate_mean_pct": float(matched["order_fill_rate_pct"].mean()),
                "order_block_rate_mean_pct": order_block_mean,
                "risk_block_rate_mean_pct": risk_block_mean,
                "est_cost_mean_pct": float(matched["est_cost_pct"].mean()),
                "unexplained_gap_mean_pct": float(matched["unexplained_gap_pct"].mean()),
            }
        )
        if "primary_gap_driver" in matched.columns:
            vc = matched["primary_gap_driver"].astype(str).value_counts()
            if len(vc) > 0:
                base["primary_driver_top"] = str(vc.index[0])
                base["primary_driver_top_count"] = int(vc.iloc[0])

    checks = {
        "matched_rows": {
            "actual": int(base["matched_rows"]),
            "limit": int(min_matched_rows),
            "pass": int(base["matched_rows"]) >= int(min_matched_rows),
        },
        "coverage_pct": {
            "actual": float(base["coverage_pct"]),
            "limit": float(min_match_coverage_pct),
            "pass": float(base["coverage_pct"]) >= float(min_match_coverage_pct),
        },
        "ret_gap_mae_pct": {
            "actual": float(base["ret_gap_mae_pct"]),
            "limit": float(max_ret_gap_mae_pct),
            "pass": float(base["ret_gap_mae_pct"]) <= float(max_ret_gap_mae_pct),
        },
        "order_block_rate_mean_pct": {
            "actual": float(base["order_block_rate_mean_pct"]),
            "limit": float(max_order_block_rate_pct),
            "pass": float(base["order_block_rate_mean_pct"]) <= float(max_order_block_rate_pct),
        },
        "risk_block_rate_mean_pct": {
            "actual": float(base["risk_block_rate_mean_pct"]),
            "limit": float(max_risk_block_rate_pct),
            "pass": float(base["risk_block_rate_mean_pct"]) <= float(max_risk_block_rate_pct),
        },
    }
    base["checks"] = checks
    fail_reasons = [k for k, v in checks.items() if not bool(v.get("pass", False))]
    base["fail_reasons"] = fail_reasons
    base["consistency_pass"] = len(fail_reasons) == 0
    return base


def _save(df: pd.DataFrame, summary: dict[str, object], broker: str, write_latest: bool) -> tuple[Path, Path]:
    out_dir = OUTPUT_DIR / "risk"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = out_dir / f"exec_consistency_{broker}_{ts}.csv"
    json_file = out_dir / f"exec_consistency_summary_{broker}_{ts}.json"
    df.to_csv(csv_file, index=False, encoding="utf-8-sig")
    json_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if write_latest:
        df.to_csv(out_dir / f"exec_consistency_{broker}_latest.csv", index=False, encoding="utf-8-sig")
        (out_dir / f"exec_consistency_summary_{broker}_latest.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return csv_file, json_file


def _save_style_gap_attribution(
    df: pd.DataFrame,
    broker: str,
    write_latest: bool,
) -> Path:
    out_dir = OUTPUT_DIR / "risk"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = out_dir / f"exec_consistency_style_attribution_{broker}_{ts}.csv"
    df.to_csv(csv_file, index=False, encoding="utf-8-sig")
    if write_latest:
        df.to_csv(
            out_dir / f"exec_consistency_style_attribution_{broker}_latest.csv",
            index=False,
            encoding="utf-8-sig",
        )
    return csv_file


def _save_tick_replay(
    detail_df: pd.DataFrame,
    layer_df: pd.DataFrame,
    summary: dict[str, object],
    broker: str,
    write_latest: bool,
) -> tuple[Path, Path, Path]:
    out_dir = OUTPUT_DIR / "risk"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_file = out_dir / f"exec_tick_replay_{broker}_{ts}.csv"
    layer_file = out_dir / f"exec_tick_replay_layer_{broker}_{ts}.csv"
    summary_file = out_dir / f"exec_tick_replay_summary_{broker}_{ts}.json"
    detail_df.to_csv(detail_file, index=False, encoding="utf-8-sig")
    layer_df.to_csv(layer_file, index=False, encoding="utf-8-sig")
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if write_latest:
        detail_df.to_csv(out_dir / f"exec_tick_replay_{broker}_latest.csv", index=False, encoding="utf-8-sig")
        layer_df.to_csv(out_dir / f"exec_tick_replay_layer_{broker}_latest.csv", index=False, encoding="utf-8-sig")
        (out_dir / f"exec_tick_replay_summary_{broker}_latest.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return detail_file, layer_file, summary_file


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="回测 vs 执行一致性偏差报告")
    p.add_argument("--broker", type=str, default="paper", help="执行通道名（paper/live）")
    p.add_argument("--trades-file", type=str, default=None, help="回测交易明细 quant_trades_*.csv")
    p.add_argument("--ledger-file", type=str, default=None, help="执行账本，如 output/execution/paper_ledger.csv")
    p.add_argument("--fee-bps", type=float, default=8.0, help="成本估算：手续费 bps")
    p.add_argument("--slippage-bps", type=float, default=5.0, help="成本估算：滑点 bps")
    p.add_argument("--stamp-tax-bps", type=float, default=10.0, help="成本估算：印花税 bps")
    p.add_argument(
        "--max-ret-gap-mae-pct",
        type=float,
        default=float(os.environ.get("MFTS_P3_MAX_RET_GAP_MAE_PCT", "2.0")),
        help="门槛：收益偏差 MAE 上限（%）",
    )
    p.add_argument(
        "--min-match-coverage-pct",
        type=float,
        default=float(os.environ.get("MFTS_P3_MIN_MATCH_COVERAGE_PCT", "60.0")),
        help="门槛：回测-执行匹配覆盖率下限（%）",
    )
    p.add_argument(
        "--max-order-block-rate-pct",
        type=float,
        default=float(os.environ.get("MFTS_P3_MAX_ORDER_BLOCK_RATE_PCT", "35.0")),
        help="门槛：订单阻塞率均值上限（%）",
    )
    p.add_argument(
        "--max-risk-block-rate-pct",
        type=float,
        default=float(os.environ.get("MFTS_P3_MAX_RISK_BLOCK_RATE_PCT", "35.0")),
        help="门槛：风控拦截率均值上限（%）",
    )
    p.add_argument(
        "--min-matched-rows",
        type=int,
        default=int(os.environ.get("MFTS_P3_MIN_MATCHED_ROWS", "20")),
        help="门槛：最少匹配样本数",
    )
    p.add_argument(
        "--rate-eval-rows",
        type=int,
        default=int(os.environ.get("MFTS_P3_RATE_EVAL_ROWS", "10")),
        help="门槛计算窗口：订单/风控阻塞率使用最近 N 个匹配样本（0=全部）",
    )
    p.add_argument(
        "--disable-style-gap-attribution",
        action="store_true",
        help="关闭 style_hit 与收益偏差分层归因输出",
    )
    p.add_argument(
        "--disable-tick-replay",
        action="store_true",
        help="关闭逐笔一致性回放输出",
    )
    p.add_argument("--enforce-thresholds", action="store_true", help="若任一门槛不达标则返回非零退出码")
    p.add_argument(
        "--disable-auto-select-trades-file",
        action="store_true",
        help="关闭自动选择 trades 文件（默认按与 ledger 日期重叠度自动择优）",
    )
    p.add_argument(
        "--disable-dedupe-ledger-by-trade-date",
        action="store_true",
        help="关闭 ledger 按交易日去重（默认保留每个交易日最后一次 run）",
    )
    p.add_argument(
        "--disable-restrict-to-expected-window",
        action="store_true",
        help="关闭按 expected 交易日窗口过滤 ledger（默认开启）",
    )
    p.add_argument("--write-latest", action="store_true", help="额外写 latest 文件")
    p.add_argument("--strict", action="store_true", help="找不到输入文件时返回失败")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    broker = str(args.broker or "paper").strip().lower()
    ledger_file = _resolve_ledger_file(args.ledger_file, broker=broker)
    auto_select_trades = not bool(args.disable_auto_select_trades_file)
    trades_file, trades_pick_meta = _resolve_latest_trades_file(
        args.trades_file,
        ledger_file=ledger_file,
        auto_select=auto_select_trades,
    )

    if trades_file is None or ledger_file is None:
        _log(f"输入缺失: trades={trades_file}, ledger={ledger_file}")
        return 1 if args.strict else 0

    if auto_select_trades and trades_pick_meta.get("mode") == "auto_select":
        _log(
            "trades 自动择优: "
            f"selected={trades_pick_meta.get('selected')} "
            f"(latest={trades_pick_meta.get('latest_default')}, "
            f"intersect={trades_pick_meta.get('intersect_count', 0)}, "
            f"ledger_coverage={float(trades_pick_meta.get('ledger_coverage_pct', 0.0)):.2f}%)"
        )

    _log(f"读取回测明细: {trades_file}")
    expected_df = _load_expected(trades_file)
    _log(f"读取执行账本: {ledger_file}")
    actual_df = _load_actual(ledger_file)
    rows_raw = int(len(actual_df))
    dedupe_enabled = not bool(args.disable_dedupe_ledger_by_trade_date)
    if dedupe_enabled:
        actual_df = _dedupe_actual_by_trade_date(actual_df)
    rows_post_dedupe = int(len(actual_df))

    window_start = ""
    window_end = ""
    restrict_window_enabled = not bool(args.disable_restrict_to_expected_window)
    if restrict_window_enabled and (not expected_df.empty) and ("trade_date" in expected_df.columns):
        exp_dt = pd.to_datetime(expected_df["trade_date"], errors="coerce")
        exp_dt = exp_dt.dropna()
        if not exp_dt.empty:
            start_dt = exp_dt.min()
            end_dt = exp_dt.max()
            window_start = start_dt.strftime("%Y-%m-%d")
            window_end = end_dt.strftime("%Y-%m-%d")
            adt = pd.to_datetime(actual_df["trade_date"], errors="coerce")
            mask = (adt >= start_dt) & (adt <= end_dt)
            actual_df = actual_df[mask].copy().reset_index(drop=True)

    rows_used = int(len(actual_df))
    if actual_df.empty:
        _log("执行账本为空，跳过报告。")
        return 1 if args.strict else 0

    report_df = _build_consistency(
        expected_df=expected_df,
        actual_df=actual_df,
        fee_bps=float(args.fee_bps),
        slippage_bps=float(args.slippage_bps),
        stamp_tax_bps=float(args.stamp_tax_bps),
        broker=broker,
    )
    summary = _build_summary(
        report_df,
        broker=broker,
        trades_file=trades_file,
        ledger_file=ledger_file,
        max_ret_gap_mae_pct=float(max(0.0, args.max_ret_gap_mae_pct)),
        min_match_coverage_pct=float(max(0.0, args.min_match_coverage_pct)),
        max_order_block_rate_pct=float(max(0.0, args.max_order_block_rate_pct)),
        max_risk_block_rate_pct=float(max(0.0, args.max_risk_block_rate_pct)),
        min_matched_rows=int(max(0, args.min_matched_rows)),
        rate_eval_rows=int(max(0, args.rate_eval_rows)),
    )
    style_attr_df = pd.DataFrame()
    if not bool(args.disable_style_gap_attribution):
        style_attr_df = _build_style_gap_attribution(report_df)
        if "matched_backtest" in report_df.columns:
            matched = report_df[report_df["matched_backtest"] == 1].copy()
        else:
            matched = report_df.iloc[0:0].copy()
        if not matched.empty:
            style_hit = pd.to_numeric(matched.get("risk_style_limits_hit", 0.0), errors="coerce").fillna(0.0)
            ret_gap = pd.to_numeric(matched.get("ret_gap_pct", np.nan), errors="coerce")
            risk_input = pd.to_numeric(matched.get("risk_input_count", np.nan), errors="coerce")
            style_rate = np.where(risk_input > 0, style_hit / risk_input * 100.0, np.nan)
            summary["style_attribution"] = {
                "enabled": True,
                "layers": int(len(style_attr_df)),
                "corr_style_hit_vs_ret_gap": float(_safe_corr(style_hit, ret_gap)),
                "corr_style_hit_vs_abs_gap": float(_safe_corr(style_hit, ret_gap.abs())),
                "corr_style_hit_rate_vs_abs_gap": float(_safe_corr(pd.Series(style_rate, dtype=float), ret_gap.abs())),
            }
        else:
            summary["style_attribution"] = {
                "enabled": True,
                "layers": int(len(style_attr_df)),
                "corr_style_hit_vs_ret_gap": 0.0,
                "corr_style_hit_vs_abs_gap": 0.0,
                "corr_style_hit_rate_vs_abs_gap": 0.0,
            }
    else:
        summary["style_attribution"] = {"enabled": False, "layers": 0}

    tick_detail_df = pd.DataFrame()
    tick_layer_df = pd.DataFrame()
    tick_summary: dict[str, object] = {}
    if not bool(args.disable_tick_replay):
        tick_detail_df, tick_layer_df, tick_summary = _build_tick_replay(
            report_df=report_df,
            trades_file=trades_file,
            broker=broker,
        )
        tick_summary["enabled"] = True
    else:
        tick_summary = {"enabled": False, "rows": 0, "runs": 0}
    summary["tick_replay"] = tick_summary
    summary["alignment"] = {
        "trades_pick": trades_pick_meta,
        "auto_select_trades_file": bool(auto_select_trades),
        "ledger_dedupe_by_trade_date": bool(dedupe_enabled),
        "restrict_to_expected_window": bool(restrict_window_enabled),
        "rows_raw_ledger": int(rows_raw),
        "rows_after_dedupe": int(rows_post_dedupe),
        "rows_used_for_compare": int(rows_used),
        "window_start": window_start,
        "window_end": window_end,
    }
    csv_file, json_file = _save(report_df, summary, broker=broker, write_latest=bool(args.write_latest))
    style_file: Path | None = None
    if not bool(args.disable_style_gap_attribution):
        style_file = _save_style_gap_attribution(
            style_attr_df,
            broker=broker,
            write_latest=bool(args.write_latest),
        )
    tick_detail_file: Path | None = None
    tick_layer_file: Path | None = None
    tick_summary_file: Path | None = None
    if not bool(args.disable_tick_replay):
        tick_detail_file, tick_layer_file, tick_summary_file = _save_tick_replay(
            tick_detail_df,
            tick_layer_df,
            tick_summary,
            broker=broker,
            write_latest=bool(args.write_latest),
        )
    _log(f"一致性报告已生成: {csv_file}")
    _log(f"一致性汇总已生成: {json_file}")
    if style_file is not None:
        _log(f"style 分层归因已生成: {style_file}")
    if tick_detail_file is not None and tick_layer_file is not None and tick_summary_file is not None:
        _log(f"逐笔一致性明细已生成: {tick_detail_file}")
        _log(f"逐笔一致性分层已生成: {tick_layer_file}")
        _log(f"逐笔一致性汇总已生成: {tick_summary_file}")
    _log(
        "关键指标: "
        f"matched={summary.get('matched_rows', 0)}/{summary.get('rows', 0)}, "
        f"gap_mean={summary.get('ret_gap_mean_pct', 0.0):.4f}%, "
        f"mae={summary.get('ret_gap_mae_pct', 0.0):.4f}%, "
        f"pass={bool(summary.get('consistency_pass', False))}"
    )
    if bool(args.enforce_thresholds) and (not bool(summary.get("consistency_pass", False))):
        _log(f"门槛检查未通过: {','.join(summary.get('fail_reasons', []))}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
