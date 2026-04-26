#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号端前置风控 vs P2 执行风控 对齐报告。

输出：
1) output/risk/pretrade_alignment_<channel>_<ts>.csv
2) output/risk/pretrade_alignment_summary_<channel>_<ts>.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _parse_date(x: object) -> pd.Timestamp | pd.NaT:
    dt = pd.to_datetime(x, errors="coerce")
    if pd.isna(dt):
        return pd.NaT
    return pd.Timestamp(dt).normalize()


def _fmt_yyyymmdd(dt: pd.Timestamp | pd.NaT) -> str:
    if pd.isna(dt):
        return ""
    return pd.Timestamp(dt).strftime("%Y%m%d")


def _top_reason_from_series(s: pd.Series) -> tuple[str, int]:
    if s is None or s.empty:
        return "none", 0
    cnt: Counter[str] = Counter()
    for txt in s.astype(str).tolist():
        parts = [x.strip() for x in txt.split(",") if x.strip()]
        for p in parts:
            cnt[p] += 1
    if not cnt:
        return "none", 0
    reason, n = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return str(reason), int(n)


def _read_signal_pretrade_meta(risk_dir: Path, yyyymmdd: str) -> dict[str, object]:
    summary_fp = risk_dir / f"signal_pretrade_summary_{yyyymmdd}.json"
    gates_fp = risk_dir / f"signal_pretrade_gates_{yyyymmdd}.csv"
    out: dict[str, object] = {
        "signal_stage": "missing",
        "signal_pool_n": 0,
        "signal_kept_count": 0,
        "signal_blocked_count": 0,
        "signal_blocked_rate_pct": 0.0,
        "signal_top_reason": "none",
        "signal_top_reason_count": 0,
        "signal_topn_eval_enabled": False,
        "signal_topn_input_count": 0,
        "signal_topn_blocked_count": 0,
        "signal_topn_blocked_rate_pct": 0.0,
        "signal_topn_top_reason": "none",
        "signal_topn_top_reason_count": 0,
        "signal_summary_exists": False,
        "signal_gates_exists": False,
    }
    if summary_fp.exists():
        try:
            obj = json.loads(summary_fp.read_text(encoding="utf-8"))
            pre = obj.get("pretrade", {}) if isinstance(obj, dict) else {}
            topn_eval = obj.get("topn_pretrade_eval", {}) if isinstance(obj, dict) else {}
            out.update(
                {
                    "signal_stage": str(pre.get("stage", "unknown")),
                    "signal_pool_n": int(_safe_float(pre.get("pool_n", 0), 0.0)),
                    "signal_kept_count": int(_safe_float(pre.get("kept_count", 0), 0.0)),
                    "signal_blocked_count": int(_safe_float(pre.get("blocked_count", 0), 0.0)),
                    "signal_blocked_rate_pct": float(_safe_float(pre.get("blocked_rate_pct", 0.0), 0.0)),
                    "signal_top_reason": str(pre.get("top_reason", "none") or "none"),
                    "signal_top_reason_count": int(_safe_float(pre.get("top_reason_count", 0), 0.0)),
                    "signal_topn_eval_enabled": bool(topn_eval.get("enabled", False)),
                    "signal_topn_input_count": int(_safe_float(topn_eval.get("input_count", 0), 0.0)),
                    "signal_topn_blocked_count": int(_safe_float(topn_eval.get("blocked_count", 0), 0.0)),
                    "signal_topn_blocked_rate_pct": float(_safe_float(topn_eval.get("blocked_rate_pct", 0.0), 0.0)),
                    "signal_topn_top_reason": str(topn_eval.get("top_reason", "none") or "none"),
                    "signal_topn_top_reason_count": int(_safe_float(topn_eval.get("top_reason_count", 0), 0.0)),
                    "signal_summary_exists": True,
                }
            )
        except Exception:
            pass
    if gates_fp.exists():
        out["signal_gates_exists"] = True
        try:
            gdf = pd.read_csv(gates_fp)
            if int(out["signal_blocked_count"]) <= 0:
                out["signal_blocked_count"] = int(len(gdf))
            if (str(out["signal_top_reason"]) in {"", "none", "unknown"}) and ("reasons" in gdf.columns):
                reason, n = _top_reason_from_series(gdf["reasons"])
                out["signal_top_reason"] = reason
                out["signal_top_reason_count"] = int(n)
            if int(out["signal_pool_n"]) > 0:
                out["signal_blocked_rate_pct"] = float(
                    int(out["signal_blocked_count"]) / max(int(out["signal_pool_n"]), 1) * 100.0
                )
        except Exception:
            pass
    return out


def _read_p2_risk_reason(exec_dir: Path, channel: str, run_id: str) -> tuple[str, int]:
    pats = sorted(exec_dir.glob(f"{channel}_risk_gates_*_{run_id}.csv"))
    if not pats:
        return "none", 0
    fp = pats[-1]
    try:
        df = pd.read_csv(fp)
    except Exception:
        return "none", 0
    if df.empty or ("reasons" not in df.columns):
        return "none", 0
    return _top_reason_from_series(df["reasons"])


def _load_ledger(ledger_file: Path) -> pd.DataFrame:
    if not ledger_file.exists():
        raise FileNotFoundError(f"ledger 文件不存在: {ledger_file}")
    df = pd.read_csv(ledger_file)
    if df.empty:
        return df
    if "signal_date" not in df.columns:
        raise RuntimeError(f"ledger 缺少 signal_date 列: {ledger_file}")
    df["signal_date"] = df["signal_date"].apply(_parse_date)
    df["trade_date"] = df.get("trade_date", pd.Series(dtype=object)).apply(_parse_date)
    df = df.dropna(subset=["signal_date"]).copy()
    if df.empty:
        return df
    # 同一 signal_date 取最新 run（先按 trade_date，再按 run_id）
    if "run_id" not in df.columns:
        df["run_id"] = ""
    df = df.sort_values(["signal_date", "trade_date", "run_id"]).groupby("signal_date", as_index=False).tail(1)
    return df.sort_values("signal_date").reset_index(drop=True)


def _summarize(df: pd.DataFrame) -> dict[str, object]:
    out: dict[str, object] = {"rows": int(len(df))}
    if df.empty:
        out.update(
            {
                "matched_signal_summary_rows": 0,
                "mean_signal_blocked_rate_pct": 0.0,
                "mean_p2_risk_blocked_rate_pct": 0.0,
                "mae_blocked_rate_pct": 0.0,
                "mean_blocked_count_gap": 0.0,
                "p2_gt_signal_rows": 0,
                "p2_gt_signal_ratio_pct": 0.0,
            }
        )
        return out
    has_signal = df["signal_summary_exists"].astype(bool) | df["signal_gates_exists"].astype(bool)
    matched = df[has_signal].copy()
    out["matched_signal_summary_rows"] = int(len(matched))
    if matched.empty:
        out.update(
            {
                "mean_signal_blocked_rate_pct": 0.0,
                "mean_p2_risk_blocked_rate_pct": 0.0,
                "mae_blocked_rate_pct": 0.0,
                "mean_blocked_count_gap": 0.0,
                "p2_gt_signal_rows": 0,
                "p2_gt_signal_ratio_pct": 0.0,
            }
        )
        return out
    s_rate = pd.to_numeric(matched["signal_blocked_rate_pct"], errors="coerce").fillna(0.0)
    p_rate = pd.to_numeric(matched["p2_risk_blocked_rate_pct"], errors="coerce").fillna(0.0)
    gap_cnt = pd.to_numeric(matched["blocked_count_gap"], errors="coerce").fillna(0.0)
    gt = (gap_cnt > 0).sum()
    out.update(
        {
            "mean_signal_blocked_rate_pct": float(s_rate.mean()),
            "mean_p2_risk_blocked_rate_pct": float(p_rate.mean()),
            "mae_blocked_rate_pct": float((p_rate - s_rate).abs().mean()),
            "mean_blocked_count_gap": float(gap_cnt.mean()),
            "p2_gt_signal_rows": int(gt),
            "p2_gt_signal_ratio_pct": float(gt / max(len(matched), 1) * 100.0),
        }
    )
    topn_mask = matched["signal_topn_eval_enabled"].astype(bool)
    topn = matched[topn_mask].copy()
    out["topn_eval_rows"] = int(len(topn))
    if topn.empty:
        out["mean_signal_topn_blocked_rate_pct"] = 0.0
        out["mae_topn_blocked_rate_pct"] = 0.0
    else:
        topn_rate = pd.to_numeric(topn["signal_topn_blocked_rate_pct"], errors="coerce").fillna(0.0)
        p2_rate_topn = pd.to_numeric(topn["p2_risk_blocked_rate_pct"], errors="coerce").fillna(0.0)
        out["mean_signal_topn_blocked_rate_pct"] = float(topn_rate.mean())
        out["mae_topn_blocked_rate_pct"] = float((p2_rate_topn - topn_rate).abs().mean())
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="信号端前置风控与P2执行风控对齐报告")
    p.add_argument("--broker", type=str, default="paper", help="执行通道（用于默认 channel）")
    p.add_argument("--channel", type=str, default="", help="账本通道名（默认等于 broker）")
    p.add_argument("--ledger-file", type=str, default="", help="显式指定 ledger 文件")
    p.add_argument("--min-date", type=str, default="", help="起始日期 YYYYMMDD（可选）")
    p.add_argument("--max-date", type=str, default="", help="结束日期 YYYYMMDD（可选）")
    p.add_argument("--write-latest", action="store_true", help="写入 latest 快捷文件")
    args = p.parse_args()

    broker = str(args.broker or "paper").strip().lower()
    channel = str(args.channel or broker).strip().lower()
    exec_dir = OUTPUT_DIR / "execution"
    risk_dir = OUTPUT_DIR / "risk"
    risk_dir.mkdir(parents=True, exist_ok=True)

    ledger_file = Path(args.ledger_file) if args.ledger_file else (exec_dir / f"{channel}_ledger.csv")
    ledger = _load_ledger(ledger_file)
    if ledger.empty:
        print(f"ledger 为空：{ledger_file}")
        return 0

    min_dt = _parse_date(args.min_date) if str(args.min_date).strip() else pd.NaT
    max_dt = _parse_date(args.max_date) if str(args.max_date).strip() else pd.NaT
    if not pd.isna(min_dt):
        ledger = ledger[ledger["signal_date"] >= min_dt].copy()
    if not pd.isna(max_dt):
        ledger = ledger[ledger["signal_date"] <= max_dt].copy()
    if ledger.empty:
        print("日期过滤后无样本。")
        return 0

    rows = []
    for _, r in ledger.iterrows():
        sig_dt = _parse_date(r.get("signal_date"))
        sig_yyyymmdd = _fmt_yyyymmdd(sig_dt)
        meta = _read_signal_pretrade_meta(risk_dir, sig_yyyymmdd)
        run_id = str(r.get("run_id", "") or "")
        p2_reason, p2_reason_n = _read_p2_risk_reason(exec_dir, channel, run_id) if run_id else ("none", 0)
        p2_input = int(_safe_float(r.get("risk_input_count", 0), 0.0))
        p2_block = int(_safe_float(r.get("risk_blocked_count", 0), 0.0))
        p2_rate = float(_safe_float(r.get("risk_blocked_rate_pct", 0.0), 0.0))
        signal_block = int(_safe_float(meta.get("signal_blocked_count", 0), 0.0))
        rows.append(
            {
                "signal_date": sig_dt.strftime("%Y-%m-%d") if not pd.isna(sig_dt) else "",
                "trade_date": _parse_date(r.get("trade_date")).strftime("%Y-%m-%d")
                if not pd.isna(_parse_date(r.get("trade_date")))
                else "",
                "run_id": run_id,
                "channel": channel,
                "signal_stage": str(meta.get("signal_stage", "missing")),
                "signal_pool_n": int(_safe_float(meta.get("signal_pool_n", 0), 0.0)),
                "signal_kept_count": int(_safe_float(meta.get("signal_kept_count", 0), 0.0)),
                "signal_blocked_count": signal_block,
                "signal_blocked_rate_pct": float(_safe_float(meta.get("signal_blocked_rate_pct", 0.0), 0.0)),
                "signal_top_reason": str(meta.get("signal_top_reason", "none") or "none"),
                "signal_top_reason_count": int(_safe_float(meta.get("signal_top_reason_count", 0), 0.0)),
                "signal_topn_eval_enabled": bool(meta.get("signal_topn_eval_enabled", False)),
                "signal_topn_input_count": int(_safe_float(meta.get("signal_topn_input_count", 0), 0.0)),
                "signal_topn_blocked_count": int(_safe_float(meta.get("signal_topn_blocked_count", 0), 0.0)),
                "signal_topn_blocked_rate_pct": float(_safe_float(meta.get("signal_topn_blocked_rate_pct", 0.0), 0.0)),
                "signal_topn_top_reason": str(meta.get("signal_topn_top_reason", "none") or "none"),
                "signal_topn_top_reason_count": int(_safe_float(meta.get("signal_topn_top_reason_count", 0), 0.0)),
                "signal_summary_exists": bool(meta.get("signal_summary_exists", False)),
                "signal_gates_exists": bool(meta.get("signal_gates_exists", False)),
                "p2_risk_input_count": p2_input,
                "p2_risk_blocked_count": p2_block,
                "p2_risk_blocked_rate_pct": p2_rate,
                "p2_top_reason": p2_reason,
                "p2_top_reason_count": int(p2_reason_n),
                "blocked_count_gap": int(p2_block - signal_block),
                "blocked_rate_gap_pct": float(p2_rate - float(_safe_float(meta.get("signal_blocked_rate_pct", 0.0), 0.0))),
            }
        )

    out_df = pd.DataFrame(rows).sort_values("signal_date").reset_index(drop=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = risk_dir / f"pretrade_alignment_{channel}_{ts}.csv"
    json_file = risk_dir / f"pretrade_alignment_summary_{channel}_{ts}.json"
    out_df.to_csv(csv_file, index=False, encoding="utf-8-sig")

    summary = {
        "broker": broker,
        "channel": channel,
        "ledger_file": str(ledger_file),
        "rows": int(len(out_df)),
        "window_start": str(out_df["signal_date"].min()) if not out_df.empty else "",
        "window_end": str(out_df["signal_date"].max()) if not out_df.empty else "",
        "metrics": _summarize(out_df),
    }
    json_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if bool(args.write_latest):
        latest_csv = risk_dir / f"pretrade_alignment_{channel}_latest.csv"
        latest_json = risk_dir / f"pretrade_alignment_summary_{channel}_latest.json"
        out_df.to_csv(latest_csv, index=False, encoding="utf-8-sig")
        latest_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    m = summary["metrics"]
    print(f"对齐报告已生成: {csv_file}")
    print(f"对齐汇总已生成: {json_file}")
    print(
        "关键指标: "
        f"rows={int(m.get('rows', 0))}, "
        f"matched={int(m.get('matched_signal_summary_rows', 0))}, "
        f"signal_block_rate={float(m.get('mean_signal_blocked_rate_pct', 0.0)):.2f}%, "
        f"p2_block_rate={float(m.get('mean_p2_risk_blocked_rate_pct', 0.0)):.2f}%, "
        f"mae={float(m.get('mae_blocked_rate_pct', 0.0)):.2f}%, "
        f"topn_mae={float(m.get('mae_topn_blocked_rate_pct', 0.0)):.2f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
