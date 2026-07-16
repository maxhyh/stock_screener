#!/usr/bin/env python3
"""
对比主档与候选档，解释“研究强但执行弱”的原因。

输出：
1) 一份 CSV 指标对比表
2) 一份 JSON 诊断摘要，重点覆盖：
   - 研究侧稳健性
   - 回测组合结构（换手、行业集中度、仓位形态）
   - P2 执行侧（收益、回撤、换手、阻塞、风险门禁）
   - 下一轮优化建议
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

from quant_profile_ab_compare import _build_cfg, _load_profiles
from quant_portfolio_backtest import backtest_portfolio
from core.risk.pretrade import load_industry_map as load_ods_industry_map
OUTPUT_DIR = BASE_DIR / "output"
BACKTEST_DIR = OUTPUT_DIR / "backtest"
EXEC_DIR = OUTPUT_DIR / "execution"


@dataclass
class ProfileDiagnosis:
    profile: str
    research: dict[str, Any]
    backtest: dict[str, Any]
    execution: dict[str, Any]


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if not np.isfinite(out):
        return float(default)
    return float(out)


def _parse_profiles(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def _find_latest_file(patterns: list[str]) -> str:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(Path(BASE_DIR).glob(pattern))
    existing = [p for p in matches if p.exists()]
    if not existing:
        raise FileNotFoundError(f"未找到工件: {patterns}")
    return str(max(existing, key=lambda p: p.stat().st_mtime_ns))


def _load_industry_map(asof_date: object) -> dict[str, str]:
    return load_ods_industry_map(asof_date=asof_date)


def _normalize_code(raw: Any) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits.zfill(6)


def _parse_codes_weights(row: pd.Series) -> list[tuple[str, float]]:
    codes = [c.strip() for c in str(row.get("codes", "") or "").split(",") if c.strip()]
    weights_raw = [w.strip() for w in str(row.get("weights", "") or "").split(",") if w.strip()]
    if not codes or len(codes) != len(weights_raw):
        return []
    pairs: list[tuple[str, float]] = []
    for code, weight in zip(codes, weights_raw):
        c = _normalize_code(code)
        w = _safe_float(weight, 0.0)
        if not c or w <= 0:
            continue
        pairs.append((c, w))
    return pairs


def _summarize_backtest_structure(trades_df: pd.DataFrame, industry_map: dict[str, str]) -> dict[str, Any]:
    if trades_df.empty:
        return {
            "trade_days": 0,
            "avg_selected_count": 0.0,
            "avg_total_exposure_pct": 0.0,
            "avg_per_position_weight_pct": 0.0,
            "mean_top_industry_weight_pct": 0.0,
            "mean_industry_hhi": 0.0,
            "unknown_industry_share_pct": 0.0,
            "dominant_industry": "",
        }

    industry_rows: list[dict[str, Any]] = []
    top_names: list[str] = []
    for _, row in trades_df.iterrows():
        pairs = _parse_codes_weights(row)
        if not pairs:
            continue
        total_weight = sum(w for _, w in pairs)
        if total_weight <= 0:
            continue
        industry_weights: dict[str, float] = {}
        for code, weight in pairs:
            industry = industry_map.get(code, "") or "未知"
            industry_weights[industry] = industry_weights.get(industry, 0.0) + weight
        shares = np.array([float(v) / total_weight for v in industry_weights.values()], dtype=float)
        top_industry, top_weight = max(industry_weights.items(), key=lambda kv: kv[1])
        top_names.append(str(top_industry))
        industry_rows.append(
            {
                "top_industry": str(top_industry),
                "top_industry_weight_pct": float(top_weight / total_weight * 100.0),
                "industry_hhi": float(np.sum(np.square(shares))),
                "unknown_industry_share_pct": float(industry_weights.get("未知", 0.0) / total_weight * 100.0),
            }
        )

    industry_df = pd.DataFrame(industry_rows)
    dominant_industry = ""
    if top_names:
        dominant_industry = pd.Series(top_names).value_counts().index[0]
    return {
        "trade_days": int(len(trades_df)),
        "avg_selected_count": float(pd.to_numeric(trades_df.get("selected_count", 0), errors="coerce").fillna(0.0).mean()),
        "avg_total_exposure_pct": float(pd.to_numeric(trades_df.get("total_exposure", 0), errors="coerce").fillna(0.0).mean() * 100.0),
        "avg_per_position_weight_pct": float(pd.to_numeric(trades_df.get("per_position_weight", 0), errors="coerce").fillna(0.0).mean() * 100.0),
        "mean_top_industry_weight_pct": float(pd.to_numeric(industry_df.get("top_industry_weight_pct", 0), errors="coerce").fillna(0.0).mean()) if not industry_df.empty else 0.0,
        "mean_industry_hhi": float(pd.to_numeric(industry_df.get("industry_hhi", 0), errors="coerce").fillna(0.0).mean()) if not industry_df.empty else 0.0,
        "unknown_industry_share_pct": float(pd.to_numeric(industry_df.get("unknown_industry_share_pct", 0), errors="coerce").fillna(0.0).mean()) if not industry_df.empty else 0.0,
        "dominant_industry": dominant_industry,
    }


def _summarize_execution_summary(summary_df: pd.DataFrame, profile: str) -> dict[str, Any]:
    sub = summary_df.loc[summary_df["profile"] == profile].copy()
    if sub.empty:
        return {}
    return {
        "window_count": int(len(sub)),
        "executed_days_total": int(pd.to_numeric(sub.get("executed_days", 0), errors="coerce").fillna(0.0).sum()),
        "nav_return_mean_pct": float(pd.to_numeric(sub.get("nav_return_pct", 0), errors="coerce").mean()),
        "nav_return_worst_pct": float(pd.to_numeric(sub.get("nav_return_pct", 0), errors="coerce").min()),
        "max_drawdown_worst_pct": float(pd.to_numeric(sub.get("max_drawdown_pct", 0), errors="coerce").min()),
        "turnover_mean": float(pd.to_numeric(sub.get("turnover_mean", 0), errors="coerce").mean()),
        "exec_block_rate_mean_pct": float(pd.to_numeric(sub.get("exec_block_rate_pct", 0), errors="coerce").mean()),
        "risk_block_rate_mean_pct": float(pd.to_numeric(sub.get("risk_block_rate_pct", 0), errors="coerce").mean()),
        "objective_score_mean": float(pd.to_numeric(sub.get("objective_score", 0), errors="coerce").mean()),
    }


def _load_execution_ledgers(summary_df: pd.DataFrame, profile: str) -> pd.DataFrame:
    sub = summary_df.loc[summary_df["profile"] == profile].copy()
    frames: list[pd.DataFrame] = []
    for channel in sub.get("channel", pd.Series(dtype=str)).astype(str).tolist():
        fp = EXEC_DIR / f"{channel}_ledger.csv"
        if not fp.exists():
            continue
        df = pd.read_csv(fp)
        df["source_channel"] = channel
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["trade_date"] = pd.to_datetime(out.get("trade_date"), errors="coerce")
    out = out.sort_values(["source_channel", "trade_date"]).drop_duplicates(subset=["source_channel", "trade_date"], keep="last")
    return out


def _summarize_risk_gates(summary_df: pd.DataFrame, profile: str) -> dict[str, Any]:
    sub = summary_df.loc[summary_df["profile"] == profile].copy()
    frames: list[pd.DataFrame] = []
    for channel in sub.get("channel", pd.Series(dtype=str)).astype(str).tolist():
        for fp in sorted(EXEC_DIR.glob(f"{channel}_risk_gates_*.csv")):
            try:
                df = pd.read_csv(fp)
            except Exception:
                continue
            if df.empty:
                continue
            df["source_channel"] = channel
            frames.append(df)
    if not frames:
        return {}
    gates = pd.concat(frames, ignore_index=True)
    gates["reasons"] = gates.get("reasons", "").astype(str)
    gates["participation_pct"] = pd.to_numeric(gates.get("participation_pct", 0), errors="coerce").fillna(0.0)
    exploded = gates.assign(reason=gates["reasons"].str.split(";")).explode("reason")
    exploded["reason"] = exploded["reason"].astype(str).str.strip()
    exploded = exploded[exploded["reason"] != ""]
    reason_counts = exploded["reason"].value_counts().to_dict()
    adv_rows = gates[gates["reasons"].str.contains("adv_participation", na=False)].copy()
    return {
        "risk_gate_rows": int(len(gates)),
        "top_reasons": [{"reason": str(k), "count": int(v)} for k, v in list(reason_counts.items())[:5]],
        "adv_block_rows": int(len(adv_rows)),
        "adv_participation_mean_pct": float(adv_rows["participation_pct"].mean()) if not adv_rows.empty else 0.0,
        "adv_participation_max_pct": float(adv_rows["participation_pct"].max()) if not adv_rows.empty else 0.0,
    }


def _summarize_execution_ledgers(ledger_df: pd.DataFrame) -> dict[str, Any]:
    if ledger_df.empty:
        return {}
    for col in [
        "nav_pre",
        "nav_post",
        "cash_post",
        "market_value_post",
        "position_count_post",
        "filled_orders",
        "blocked_orders",
        "rejected_orders",
        "turnover",
        "risk_input_count",
        "risk_blocked_count",
        "risk_blocked_rate_pct",
        "risk_industry_limits_hit",
        "risk_missing_industry_count",
        "risk_unknown_industry_limits_hit",
        "risk_adv_limits_hit",
    ]:
        ledger_df[col] = pd.to_numeric(ledger_df.get(col, 0), errors="coerce").fillna(0.0)
    nav_post = ledger_df["nav_post"].replace(0, np.nan)
    return {
        "executed_rows": int(len(ledger_df)),
        "avg_positions_post": float(ledger_df["position_count_post"].mean()),
        "avg_filled_orders": float(ledger_df["filled_orders"].mean()),
        "avg_turnover": float(ledger_df["turnover"].mean()),
        "avg_turnover_nav_pct": float((ledger_df["turnover"] / nav_post).replace([np.inf, -np.inf], np.nan).fillna(0.0).mean() * 100.0),
        "avg_cash_ratio_pct": float((ledger_df["cash_post"] / nav_post).replace([np.inf, -np.inf], np.nan).fillna(0.0).mean() * 100.0),
        "avg_market_value_ratio_pct": float((ledger_df["market_value_post"] / nav_post).replace([np.inf, -np.inf], np.nan).fillna(0.0).mean() * 100.0),
        "risk_block_rate_mean_pct": float(ledger_df["risk_blocked_rate_pct"].mean()),
        "industry_hit_days": int((ledger_df["risk_industry_limits_hit"] > 0).sum()),
        "unknown_industry_hit_days": int((ledger_df["risk_unknown_industry_limits_hit"] > 0).sum()),
        "adv_hit_days": int((ledger_df["risk_adv_limits_hit"] > 0).sum()),
        "missing_industry_mean": float(ledger_df["risk_missing_industry_count"].mean()),
    }


def _resolve_period(summary_df: pd.DataFrame) -> tuple[str, str]:
    start = pd.to_datetime(summary_df.get("signal_start").astype(str), format="%Y%m%d", errors="coerce").min()
    end = pd.to_datetime(summary_df.get("signal_end").astype(str), format="%Y%m%d", errors="coerce").max()
    if pd.isna(start) or pd.isna(end):
        raise RuntimeError("无法从 P2 summary 推导对比区间")
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _run_backtest_profile(profile_cfg: dict[str, Any], start: str, end: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    args = argparse.Namespace(start=start, end=end, benchmark_file=None, verbose=False)
    cfg = _build_cfg(profile_cfg, args)
    trades_df, metrics = backtest_portfolio(cfg)
    return trades_df, metrics


def _build_findings(main: ProfileDiagnosis, candidate: ProfileDiagnosis) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    cand_exec = candidate.execution
    main_exec = main.execution
    cand_back = candidate.backtest
    main_back = main.backtest
    cand_research = candidate.research
    main_research = main.research

    turnover_gap = _safe_float(cand_exec.get("turnover_mean")) - _safe_float(main_exec.get("turnover_mean"))
    turnover_nav_gap = _safe_float(cand_exec.get("avg_turnover_nav_pct")) - _safe_float(main_exec.get("avg_turnover_nav_pct"))
    backtest_turnover_gap = _safe_float(cand_back.get("annual_turnover_pct")) - _safe_float(main_back.get("annual_turnover_pct"))
    if turnover_gap > 15000 or turnover_nav_gap > 1.5:
        if backtest_turnover_gap > 50:
            turnover_tail = (
                f"回测年化换手也更高（{_safe_float(cand_back.get('annual_turnover_pct')):.1f}% vs "
                f"{_safe_float(main_back.get('annual_turnover_pct')):.1f}%）。"
            )
        elif backtest_turnover_gap < -50:
            turnover_tail = (
                f"但回测年化换手并不更高（{_safe_float(cand_back.get('annual_turnover_pct')):.1f}% vs "
                f"{_safe_float(main_back.get('annual_turnover_pct')):.1f}%），"
                "说明执行层的真实周转摩擦比研究侧预估更重。"
            )
        else:
            turnover_tail = (
                f"回测年化换手接近（{_safe_float(cand_back.get('annual_turnover_pct')):.1f}% vs "
                f"{_safe_float(main_back.get('annual_turnover_pct')):.1f}%）。"
            )
        findings.append(
            {
                "tag": "turnover_cost",
                "title": "候选档执行弱点主要来自更高换手与资金周转",
                "detail": (
                    f"P2 日均 turnover 高出 {turnover_gap:.0f}，"
                    f"turnover/nav 高出 {turnover_nav_gap:.2f}pct；"
                    f"{turnover_tail}"
                ),
            }
        )

    risk_gap = _safe_float(cand_exec.get("risk_block_rate_mean_pct")) - _safe_float(main_exec.get("risk_block_rate_mean_pct"))
    if risk_gap <= 0.5:
        findings.append(
            {
                "tag": "not_hard_risk_gate",
                "title": "执行劣化不是由更严的硬风控拦截主导",
                "detail": (
                    f"候选档 P2 风险拦截率并不更高（{_safe_float(cand_exec.get('risk_block_rate_mean_pct')):.2f}% vs "
                    f"{_safe_float(main_exec.get('risk_block_rate_mean_pct')):.2f}%），"
                    "说明问题更像是成交路径和换手摩擦，而不是门禁把它大量打回。"
                ),
            }
        )

    adv_gap = _safe_float(cand_exec.get("adv_hit_days")) - _safe_float(main_exec.get("adv_hit_days"))
    if adv_gap <= 0 and _safe_float(cand_exec.get("industry_hit_days")) <= _safe_float(main_exec.get("industry_hit_days")) + 1:
        findings.append(
            {
                "tag": "capacity_soft_not_hard",
                "title": "容量问题更多是软摩擦，不是硬 ADV 或行业上限命中",
                "detail": (
                    f"候选档 ADV 命中天数 {int(_safe_float(cand_exec.get('adv_hit_days')))}，"
                    f"行业命中天数 {int(_safe_float(cand_exec.get('industry_hit_days')))}；"
                    "硬门禁命中不高，但更高周转仍在吞噬执行收益。"
                ),
            }
        )

    if _safe_float(cand_exec.get("adv_block_rows")) > _safe_float(main_exec.get("adv_block_rows")):
        findings.append(
            {
                "tag": "adv_participation_hotspot",
                "title": "候选档更容易在具体标的上触发 ADV 参与率阻塞",
                "detail": (
                    f"候选档 adv_participation 阻塞记录更多（{int(_safe_float(cand_exec.get('adv_block_rows')))} vs "
                    f"{int(_safe_float(main_exec.get('adv_block_rows')))}），"
                    f"阻塞样本平均 participation={_safe_float(cand_exec.get('adv_participation_mean_pct')):.2f}% ，"
                    f"峰值可到 {_safe_float(cand_exec.get('adv_participation_max_pct')):.2f}% 。"
                ),
            }
        )

    industry_gap = _safe_float(cand_back.get("mean_top_industry_weight_pct")) - _safe_float(main_back.get("mean_top_industry_weight_pct"))
    hhi_gap = _safe_float(cand_back.get("mean_industry_hhi")) - _safe_float(main_back.get("mean_industry_hhi"))
    if industry_gap > 1.5 or hhi_gap > 0.01:
        findings.append(
            {
                "tag": "industry_concentration",
                "title": "候选档存在更高的行业集中倾向",
                "detail": (
                    f"回测结构里，候选档 top industry 平均权重高出 {industry_gap:.2f}pct，"
                    f"industry HHI 高出 {hhi_gap:.4f}。"
                ),
            }
        )
    else:
        findings.append(
            {
                "tag": "industry_not_primary",
                "title": "行业分布不是当前执行落后的主因",
                "detail": (
                    f"候选档与主档的行业集中度差异有限（top industry {industry_gap:.2f}pct，HHI {hhi_gap:.4f}），"
                    "更值得优先压的是换手与组合周转。"
                ),
            }
        )

    score_gap = _safe_float(cand_research.get("objective_score")) - _safe_float(main_research.get("objective_score"))
    exec_score_gap = _safe_float(cand_exec.get("objective_score_mean")) - _safe_float(main_exec.get("objective_score_mean"))
    findings.append(
        {
            "tag": "research_vs_execution_gap",
            "title": "候选档的优势主要停留在研究层，还没有完整穿透到执行层",
            "detail": (
                f"rolling compare objective 多出 {score_gap:.2f}，"
                f"但 P2 objective 反而低 {abs(exec_score_gap):.2f}。"
            ),
        }
    )
    return findings


def _profile_row(
    profile: str,
    research: dict[str, Any],
    backtest_metrics: dict[str, Any],
    backtest_structure: dict[str, Any],
    execution_summary: dict[str, Any],
    execution_ledger: dict[str, Any],
    risk_gate_summary: dict[str, Any],
) -> ProfileDiagnosis:
    backtest = dict(backtest_metrics)
    backtest.update(backtest_structure)
    execution = dict(execution_summary)
    execution.update(execution_ledger)
    execution.update(risk_gate_summary)
    return ProfileDiagnosis(profile=profile, research=research, backtest=backtest, execution=execution)


def main() -> int:
    p = argparse.ArgumentParser(description="分析 quant profile 的研究-执行落差")
    p.add_argument("--config", type=str, default=str(BASE_DIR / "config" / "quant_live_profiles.json"))
    p.add_argument("--profiles", type=str, default="quality_regime,quality_regime_candidate")
    p.add_argument("--rolling-summary", type=str, default="")
    p.add_argument("--p2-summary", type=str, default="")
    p.add_argument("--start", type=str, default="")
    p.add_argument("--end", type=str, default="")
    args = p.parse_args()

    profiles = _parse_profiles(args.profiles)
    if len(profiles) != 2:
        raise ValueError("当前诊断脚本需要两个 profile：主档与候选档")
    main_profile, candidate_profile = profiles

    rolling_summary_file = args.rolling_summary or _find_latest_file(
        [
            "output/backtest/quant_profile_rolling_compare_summary_latest.csv",
            "output/backtest/quant_profile_rolling_compare_summary_*.csv",
            "output/quant_profile_rolling_compare_summary_latest.csv",
            "output/quant_profile_rolling_compare_summary_*.csv",
        ]
    )
    p2_summary_file = args.p2_summary or _find_latest_file(
        [
            "output/backtest/p2_rolling_replay_summary_latest.csv",
            "output/backtest/p2_rolling_replay_summary_*.csv",
        ]
    )

    root = _load_profiles(os.path.abspath(args.config))
    profile_cfgs = root.get("profiles", {})
    if main_profile not in profile_cfgs or candidate_profile not in profile_cfgs:
        raise RuntimeError(f"未在配置中找到档位: {profiles}")

    rolling_df = pd.read_csv(rolling_summary_file)
    p2_summary_df = pd.read_csv(p2_summary_file)
    p2_summary_df = p2_summary_df[p2_summary_df["profile"].isin(profiles)].copy()
    if p2_summary_df.empty:
        raise RuntimeError("P2 summary 中没有目标档位")

    start, end = (args.start, args.end) if args.start and args.end else _resolve_period(p2_summary_df)
    _log(f"研究摘要: {rolling_summary_file}")
    _log(f"P2 摘要: {p2_summary_file}")
    _log(f"回测诊断区间: {start} ~ {end}")

    industry_map = _load_industry_map(end)

    diagnosis_items: list[ProfileDiagnosis] = []
    for profile in profiles:
        _log(f"回测结构诊断: {profile}")
        trades_df, metrics = _run_backtest_profile(profile_cfgs[profile], start, end)
        structure = _summarize_backtest_structure(trades_df, industry_map)
        research_row = rolling_df.loc[rolling_df["profile"] == profile].head(1)
        research = research_row.iloc[0].to_dict() if not research_row.empty else {}
        execution_summary = _summarize_execution_summary(p2_summary_df, profile)
        ledger_df = _load_execution_ledgers(p2_summary_df, profile)
        execution_ledger = _summarize_execution_ledgers(ledger_df)
        risk_gate_summary = _summarize_risk_gates(p2_summary_df, profile)
        diagnosis_items.append(
            _profile_row(profile, research, metrics, structure, execution_summary, execution_ledger, risk_gate_summary)
        )

    diag_map = {item.profile: item for item in diagnosis_items}
    findings = _build_findings(diag_map[main_profile], diag_map[candidate_profile])

    rows: list[dict[str, Any]] = []
    for item in diagnosis_items:
        for bucket_name, bucket in [("research", item.research), ("backtest", item.backtest), ("execution", item.execution)]:
            for metric, value in bucket.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    rows.append({"profile": item.profile, "bucket": bucket_name, "metric": metric, "value": value})
    cmp_df = pd.DataFrame(rows)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = BACKTEST_DIR / f"quant_profile_execution_gap_diagnosis_{ts}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    cmp_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profiles": profiles,
        "period": {"start": start, "end": end},
        "artifacts": {
            "rolling_summary_file": os.path.abspath(rolling_summary_file),
            "p2_summary_file": os.path.abspath(p2_summary_file),
            "comparison_csv": str(csv_path),
        },
        "profiles_detail": {
            item.profile: {
                "research": item.research,
                "backtest": item.backtest,
                "execution": item.execution,
            }
            for item in diagnosis_items
        },
        "findings": findings,
        "recommendations": [
            "优先压缩候选档换手与 turnover/nav，而不是继续加进攻参数。",
            "下一轮候选档应先做容量友好化改造，例如降低 ML blend 的交易敏感度、提高 refactor floor、增加 turnover 惩罚。",
            "若继续保留 TopN 扩张，应同步加入更强的组合层行业/容量约束，而不是只依赖执行前门禁兜底。",
        ],
    }
    json_path = BACKTEST_DIR / f"quant_profile_execution_gap_diagnosis_{ts}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("研究-执行落差诊断")
    print("=" * 72)
    for finding in findings:
        print(f"- [{finding['tag']}] {finding['title']}: {finding['detail']}")
    print(f"comparison_csv={csv_path}")
    print(f"summary_json={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
