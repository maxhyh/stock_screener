"""平台总览与运维视图服务。"""

from __future__ import annotations

from datetime import datetime
import glob
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.platform import load_experiment_registry, load_latest_run_manifest

_OVERVIEW_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_OPS_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _existing_signature(paths: list[str | Path]) -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for raw in paths:
        path = os.fspath(raw)
        if not os.path.exists(path):
            continue
        stat = os.stat(path)
        signature.append((path, int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(signature)


def _find_latest_file(candidates: list[str]) -> str | None:
    existing = [p for p in candidates if os.path.exists(p)]
    if not existing:
        return None
    return max(existing, key=os.path.getmtime)


def _find_date_file(output_dir: str, prefix: str, ymd: str) -> str | None:
    scan_paths: list[str] = []
    if prefix == "daily":
        scan_paths = [
            os.path.join(output_dir, "daily", f"daily_{ymd}.csv"),
            os.path.join(output_dir, f"daily_{ymd}.csv"),
        ]
    elif prefix == "scan":
        scan_paths = [
            os.path.join(output_dir, "scan", f"mfts_scan_{ymd}.csv"),
            os.path.join(output_dir, f"mfts_scan_{ymd}.csv"),
        ]
    elif prefix == "verify":
        scan_paths = [
            os.path.join(output_dir, "verify", f"verification_{ymd}.csv"),
            os.path.join(output_dir, f"verification_{ymd}.csv"),
        ]
    return _find_latest_file(scan_paths)


def _sanitize_for_json(obj):
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_for_json(v) for v in obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _make_alert(
    alert_id: str,
    severity: str,
    domain: str,
    title: str,
    message: str,
    *,
    metric_path: str | None = None,
    observed_value: Any = None,
    threshold: Any = None,
    comparator: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": alert_id,
        "severity": severity,
        "domain": domain,
        "title": title,
        "message": message,
        "metric_path": metric_path or "",
        "observed_value": observed_value,
        "threshold": threshold,
        "comparator": comparator or "",
        "context": context or {},
    }


def _load_json_file(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_promotion_decision(base_dir: str) -> dict[str, Any]:
    decision_file = Path(base_dir) / "output" / "backtest" / "promotion_decision_latest.json"
    payload = _load_json_file(decision_file)
    if not payload:
        return {}
    payload.setdefault("decision_file", str(decision_file))
    return payload


def _load_promotion_decision_history(base_dir: str, limit: int = 10) -> list[dict[str, Any]]:
    backtest_dir = Path(base_dir) / "output" / "backtest"
    files = sorted(backtest_dir.glob("promotion_decision_*.json"))
    rows: list[dict[str, Any]] = []
    seen_review_ids: set[str] = set()
    for fp in files:
        if fp.name == "promotion_decision_latest.json":
            continue
        payload = _load_json_file(fp)
        if not payload:
            continue
        review_id = str(payload.get("review_id", "") or fp.stem)
        if review_id in seen_review_ids:
            continue
        seen_review_ids.add(review_id)
        evidence = payload.get("evidence", {}) if isinstance(payload.get("evidence"), dict) else {}
        rows.append(
            {
                "review_id": review_id,
                "generated_at": str(payload.get("generated_at", "") or ""),
                "decision": str(payload.get("decision", "") or ""),
                "change_required": bool(payload.get("change_required", False)),
                "expected_current_default_profile": str(payload.get("expected_current_default_profile", "") or ""),
                "final_default_profile": str(payload.get("final_default_profile", "") or ""),
                "candidate_profile": str(payload.get("candidate_profile", "") or ""),
                "reason_code": str(payload.get("reason_code", "") or ""),
                "score_margin": _to_float(evidence.get("score_margin")),
                "candidate_p2_executed_days_total": _to_float(
                    evidence.get("candidate_p2_executed_days_total", evidence.get("winner_p2_executed_days_total"))
                ),
                "candidate_p2_gate_passed": bool(evidence.get("candidate_p2_gate_passed", False)),
                "candidate_research_score": _to_float(evidence.get("winner_research_score")),
                "candidate_ops_score": _to_float(evidence.get("winner_ops_score")),
                "main_ops_score": _to_float(evidence.get("main_ops_score")),
                "decision_file": str(fp),
            }
        )
    rows.sort(key=lambda item: str(item.get("generated_at", "")))
    return rows[-limit:]


def _severity_rank(severity: str) -> int:
    mapping = {"critical": 0, "warning": 1, "info": 2}
    return mapping.get(str(severity or "").lower(), 3)


def _build_alert_summary(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {"critical": 0, "warning": 0, "info": 0, "total": len(alerts), "healthy": len(alerts) == 0}
    for alert in alerts:
        severity = str(alert.get("severity", "")).lower()
        if severity in summary:
            summary[severity] += 1
    summary["healthy"] = summary["total"] == 0
    return summary


def _ops_history_file(base_dir: str) -> Path:
    return Path(base_dir) / "output" / "platform" / "ops" / "alert_history.json"


def _load_ops_alert_history(base_dir: str) -> list[dict[str, Any]]:
    history_file = _ops_history_file(base_dir)
    if not history_file.exists():
        return []
    try:
        payload = json.loads(history_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _write_ops_alert_history(base_dir: str, history: list[dict[str, Any]]) -> None:
    history_file = _ops_history_file(base_dir)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_ops_alert_snapshot(
    generated_at: str,
    platform_summary: dict[str, Any],
    alert_summary: dict[str, Any],
    alerts: list[dict[str, Any]],
    exec_diag: dict[str, Any],
    pretrade_alignment: dict[str, Any],
    capacity_recent: list[dict[str, Any]],
    promotion_decision: dict[str, Any],
) -> dict[str, Any]:
    pretrade_metrics = pretrade_alignment.get("metrics", {}) if isinstance(pretrade_alignment.get("metrics"), dict) else {}
    latest_capacity = capacity_recent[0] if capacity_recent else {}
    alert_ids = [str(item.get("id", "")) for item in alerts]
    promotion_decision_name = str(promotion_decision.get("decision", "") or "")
    promotion_final_profile = str(promotion_decision.get("final_default_profile", "") or "")
    promotion_candidate = str(promotion_decision.get("candidate_profile", "") or "")
    promotion_reason_code = str(promotion_decision.get("reason_code", "") or "")
    promotion_generated_at = str(promotion_decision.get("generated_at", "") or "")
    promotion_change_required = bool(promotion_decision.get("change_required", False))
    promotion_evidence = promotion_decision.get("evidence", {}) if isinstance(promotion_decision.get("evidence"), dict) else {}
    snapshot_key = "|".join(
        [
            generated_at[:10],
            str(platform_summary.get("latest_run_id", "") or ""),
            str(platform_summary.get("latest_run_status", "") or ""),
            str(alert_summary.get("critical", 0)),
            str(alert_summary.get("warning", 0)),
            str(alert_summary.get("info", 0)),
            ",".join(sorted(alert_ids)),
            promotion_decision_name,
            promotion_final_profile,
            promotion_candidate,
            promotion_reason_code,
            promotion_generated_at,
        ]
    )
    return {
        "snapshot_key": snapshot_key,
        "generated_at": generated_at,
        "as_of_date": generated_at[:10],
        "latest_run_id": platform_summary.get("latest_run_id", ""),
        "latest_run_status": platform_summary.get("latest_run_status", "missing"),
        "critical": int(alert_summary.get("critical", 0)),
        "warning": int(alert_summary.get("warning", 0)),
        "info": int(alert_summary.get("info", 0)),
        "total_alerts": int(alert_summary.get("total", 0)),
        "alert_ids": alert_ids,
        "exec_coverage_pct": _to_float(exec_diag.get("coverage_pct")),
        "exec_ret_gap_mae_pct": _to_float(exec_diag.get("ret_gap_mae_pct")),
        "exec_risk_block_rate_mean_pct": _to_float(exec_diag.get("risk_block_rate_mean_pct")),
        "pretrade_match_rate_pct": _to_float(pretrade_metrics.get("match_rate_pct")),
        "pretrade_risk_block_rate_pct": _to_float(pretrade_metrics.get("mean_p2_risk_blocked_rate_pct")),
        "capacity_max_participation_pct": _to_float(latest_capacity.get("max_participation_pct")),
        "capacity_cost_bps": _to_float(latest_capacity.get("estimated_roundtrip_cost_bps")),
        "promotion_decision": promotion_decision_name,
        "promotion_final_default_profile": promotion_final_profile,
        "promotion_candidate_profile": promotion_candidate,
        "promotion_reason_code": promotion_reason_code,
        "promotion_generated_at": promotion_generated_at,
        "promotion_change_required": int(promotion_change_required),
        "promotion_score_margin": _to_float(promotion_evidence.get("score_margin")),
        "promotion_candidate_research_score": _to_float(promotion_evidence.get("winner_research_score")),
        "promotion_candidate_ops_score": _to_float(promotion_evidence.get("winner_ops_score")),
        "promotion_main_ops_score": _to_float(promotion_evidence.get("main_ops_score")),
        "promotion_candidate_p2_days": _to_float(
            promotion_evidence.get("candidate_p2_executed_days_total", promotion_evidence.get("winner_p2_executed_days_total"))
        ),
    }


def _record_ops_alert_snapshot(base_dir: str, snapshot: dict[str, Any], limit: int = 90) -> list[dict[str, Any]]:
    history = _load_ops_alert_history(base_dir)
    if history and history[-1].get("snapshot_key") == snapshot.get("snapshot_key"):
        return history[-limit:]
    history.append(snapshot)
    history = history[-limit:]
    _write_ops_alert_history(base_dir, history)
    return history


def _build_alert_trends(history: list[dict[str, Any]]) -> dict[str, Any]:
    if not history:
        return {
            "series": [],
            "total_alerts": {"latest": 0, "previous": None, "delta": None},
            "critical_alerts": {"latest": 0, "previous": None, "delta": None},
        }

    recent = history[-10:]
    previous = recent[-2] if len(recent) >= 2 else None
    latest = recent[-1]
    return {
        "series": [
            {
                "as_of_date": str(item.get("as_of_date", "") or item.get("generated_at", "")[:10]),
                "generated_at": item.get("generated_at", ""),
                "total_alerts": int(item.get("total_alerts", 0) or 0),
                "critical": int(item.get("critical", 0) or 0),
                "warning": int(item.get("warning", 0) or 0),
                "exec_coverage_pct": _to_float(item.get("exec_coverage_pct")),
                "pretrade_match_rate_pct": _to_float(item.get("pretrade_match_rate_pct")),
            }
            for item in recent
        ],
        "total_alerts": {
            "latest": int(latest.get("total_alerts", 0) or 0),
            "previous": None if previous is None else int(previous.get("total_alerts", 0) or 0),
            "delta": None if previous is None else int(latest.get("total_alerts", 0) or 0) - int(previous.get("total_alerts", 0) or 0),
        },
        "critical_alerts": {
            "latest": int(latest.get("critical", 0) or 0),
            "previous": None if previous is None else int(previous.get("critical", 0) or 0),
            "delta": None if previous is None else int(latest.get("critical", 0) or 0) - int(previous.get("critical", 0) or 0),
        },
    }


def _build_promotion_trends(history: list[dict[str, Any]]) -> dict[str, Any]:
    if not history:
        return {
            "series": [],
            "latest": None,
            "decision_delta": None,
            "score_margin": {"latest": None, "previous": None, "delta": None},
            "candidate_p2_executed_days_total": {"latest": None, "previous": None, "delta": None},
            "promote_count": 0,
            "change_required_count": 0,
        }

    recent = history[-12:]
    previous = recent[-2] if len(recent) >= 2 else None
    latest = recent[-1]

    def _decision_score(item: dict[str, Any] | None) -> float | None:
        if not item:
            return None
        change_required = bool(int(item.get("promotion_change_required", 0) or 0))
        decision = str(item.get("promotion_decision", "") or "").lower()
        if change_required or decision == "promote":
            return 1.0
        if decision == "keep":
            return 0.0
        return None

    def _get(item: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in item:
                return item.get(key)
        return None

    latest_score = _decision_score(latest)
    previous_score = _decision_score(previous)
    latest_margin = _to_float(_get(latest, "score_margin", "promotion_score_margin"))
    previous_margin = None if previous is None else _to_float(_get(previous, "score_margin", "promotion_score_margin"))
    latest_p2_days = _to_float(_get(latest, "candidate_p2_executed_days_total", "candidate_p2_days", "promotion_candidate_p2_days"))
    previous_p2_days = None if previous is None else _to_float(_get(previous, "candidate_p2_executed_days_total", "candidate_p2_days", "promotion_candidate_p2_days"))
    return {
        "series": [
            {
                "as_of_date": str(item.get("as_of_date", "") or item.get("generated_at", "")[:10]),
                "generated_at": item.get("generated_at", ""),
                "decision": str(_get(item, "decision", "promotion_decision") or ""),
                "change_required": bool(_get(item, "change_required", "promotion_change_required") or False),
                "final_default_profile": str(_get(item, "final_default_profile", "promotion_final_default_profile") or ""),
                "candidate_profile": str(_get(item, "candidate_profile", "promotion_candidate_profile") or ""),
                "reason_code": str(_get(item, "reason_code", "promotion_reason_code") or ""),
                "score_margin": _to_float(_get(item, "score_margin", "promotion_score_margin")),
                "candidate_ops_score": _to_float(_get(item, "candidate_ops_score", "promotion_candidate_ops_score")),
                "main_ops_score": _to_float(_get(item, "main_ops_score", "promotion_main_ops_score")),
                "candidate_research_score": _to_float(_get(item, "candidate_research_score", "promotion_candidate_research_score")),
                "candidate_p2_days": _to_float(_get(item, "candidate_p2_executed_days_total", "candidate_p2_days", "promotion_candidate_p2_days")),
            }
            for item in recent
        ],
        "latest": {
            "decision": str(_get(latest, "decision", "promotion_decision") or ""),
            "change_required": bool(_get(latest, "change_required", "promotion_change_required") or False),
            "reason_code": str(_get(latest, "reason_code", "promotion_reason_code") or ""),
            "score_margin": latest_margin,
            "candidate_ops_score": _to_float(_get(latest, "candidate_ops_score", "promotion_candidate_ops_score")),
            "main_ops_score": _to_float(_get(latest, "main_ops_score", "promotion_main_ops_score")),
            "candidate_research_score": _to_float(_get(latest, "candidate_research_score", "promotion_candidate_research_score")),
            "candidate_p2_days": latest_p2_days,
        },
        "decision_delta": None if latest_score is None or previous_score is None else float(latest_score - previous_score),
        "score_margin": {
            "latest": latest_margin,
            "previous": previous_margin,
            "delta": None if latest_margin is None or previous_margin is None else float(latest_margin - previous_margin),
        },
        "candidate_p2_executed_days_total": {
            "latest": latest_p2_days,
            "previous": previous_p2_days,
            "delta": None if latest_p2_days is None or previous_p2_days is None else float(latest_p2_days - previous_p2_days),
        },
        "promote_count": int(sum(1 for item in recent if str(_get(item, "decision", "promotion_decision") or "").lower() == "promote")),
        "change_required_count": int(sum(1 for item in recent if bool(_get(item, "change_required", "promotion_change_required") or False))),
    }


def _build_ops_alerts(
    platform_summary: dict[str, Any],
    exposure_summary: list[dict[str, Any]],
    exposure_industry_top: list[dict[str, Any]],
    capacity_recent: list[dict[str, Any]],
    exec_diag: dict[str, Any],
    pretrade_alignment: dict[str, Any],
    promotion_decision: dict[str, Any],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []

    latest_run_id = str(platform_summary.get("latest_run_id", "") or "").strip()
    latest_run_status = str(platform_summary.get("latest_run_status", "missing") or "missing").lower()
    if not platform_summary.get("platform_output_exists", False):
        alerts.append(
            _make_alert(
                "platform_output_missing",
                "critical",
                "platform",
                "平台输出目录缺失",
                "output/platform 目录不存在，运行清单与实验登记不可用。",
                metric_path="platform.platform_output_exists",
                observed_value=False,
                threshold=True,
                comparator="eq",
            )
        )
    if not latest_run_id or latest_run_status == "missing":
        alerts.append(
            _make_alert(
                "platform_latest_run_missing",
                "critical",
                "platform",
                "缺少最新运行记录",
                "平台没有可读取的最新 run manifest，无法确认最近一次流程是否成功结束。",
                metric_path="platform.latest_run_id",
                observed_value=latest_run_id,
                threshold="non-empty",
                comparator="missing",
            )
        )
    elif latest_run_status in {"failed", "error"}:
        alerts.append(
            _make_alert(
                "platform_latest_run_failed",
                "critical",
                "platform",
                "最新运行失败",
                "最近一次平台运行处于失败状态，需要先检查运行日志和清单结果。",
                metric_path="platform.latest_run_status",
                observed_value=latest_run_status,
                threshold="success",
                comparator="eq",
                context={"run_id": latest_run_id},
            )
        )
    elif latest_run_status == "running":
        alerts.append(
            _make_alert(
                "platform_latest_run_running",
                "warning",
                "platform",
                "最新运行仍在进行中",
                "最近一次平台运行尚未完成，当前运维摘要可能仍处于中间态。",
                metric_path="platform.latest_run_status",
                observed_value=latest_run_status,
                threshold="success",
                comparator="eq",
                context={"run_id": latest_run_id},
            )
        )
    if int(platform_summary.get("experiment_count", 0) or 0) == 0:
        alerts.append(
            _make_alert(
                "platform_experiment_registry_empty",
                "warning",
                "platform",
                "实验登记为空",
                "当前没有实验注册记录，研究结果的版本可追溯性不足。",
                metric_path="platform.experiment_count",
                observed_value=0,
                threshold=1,
                comparator="lt",
            )
        )

    if not promotion_decision:
        alerts.append(
            _make_alert(
                "promotion_decision_missing",
                "warning",
                "governance",
                "缺少档位晋升决策",
                "尚未找到 promotion_decision_latest.json，当前 default_profile 缺少最新研究与执行联合评审记录。",
                metric_path="governance.promotion_decision",
                comparator="missing",
            )
        )
    else:
        decision = str(promotion_decision.get("decision", "") or "").lower()
        if decision == "promote" or bool(promotion_decision.get("change_required", False)):
            alerts.append(
                _make_alert(
                    "promotion_change_required",
                    "warning",
                    "governance",
                    "存在待执行的档位晋升决策",
                    "最新 promotion gate 已建议切换默认档位，但配置尚未应用，需要按治理流程确认并执行。",
                    metric_path="governance.promotion_decision.decision",
                    observed_value=decision,
                    threshold="keep",
                    comparator="eq",
                    context={
                        "final_default_profile": promotion_decision.get("final_default_profile", ""),
                        "candidate_profile": promotion_decision.get("candidate_profile", ""),
                        "reason_code": promotion_decision.get("reason_code", ""),
                    },
                )
            )
        generated_at_raw = str(promotion_decision.get("generated_at", "") or "").strip()
        if generated_at_raw:
            try:
                generated_at = datetime.fromisoformat(generated_at_raw)
            except ValueError:
                generated_at = None
            if generated_at is not None:
                age_days = (datetime.now(generated_at.tzinfo) - generated_at).total_seconds() / 86400.0
                if age_days > 3.0:
                    alerts.append(
                        _make_alert(
                            "promotion_decision_stale",
                            "warning",
                            "governance",
                            "档位晋升决策已过期",
                            "promotion gate 决策文件超过 3 天未刷新，默认档位的治理证据可能已经陈旧。",
                            metric_path="governance.promotion_decision.generated_at",
                            observed_value=generated_at_raw,
                            threshold="3d",
                            comparator="stale",
                            context={"age_days": round(age_days, 2)},
                        )
                    )
        else:
            alerts.append(
                _make_alert(
                    "promotion_decision_generated_at_missing",
                    "warning",
                    "governance",
                    "档位晋升决策缺少时间戳",
                    "promotion gate 决策文件没有 generated_at，无法判断默认档位依据是否仍然新鲜。",
                    metric_path="governance.promotion_decision.generated_at",
                    comparator="missing",
                )
            )

    if not exec_diag:
        alerts.append(
            _make_alert(
                "exec_consistency_data_missing",
                "warning",
                "execution",
                "缺少执行一致性摘要",
                "尚未找到执行一致性摘要文件，无法判断回测预期与纸面执行是否持续对齐。",
                metric_path="risk.exec_consistency",
                comparator="missing",
            )
        )
    else:
        if exec_diag.get("consistency_pass") is False:
            alerts.append(
                _make_alert(
                    "exec_consistency_failed",
                    "critical",
                    "execution",
                    "执行一致性未通过",
                    "执行一致性诊断未通过，说明回测、风控和执行输出之间存在系统性偏差。",
                    metric_path="risk.exec_consistency.consistency_pass",
                    observed_value=False,
                    threshold=True,
                    comparator="eq",
                    context={"primary_driver_top": exec_diag.get("primary_driver_top", "")},
                )
            )
        coverage_pct = _to_float(exec_diag.get("coverage_pct"))
        if coverage_pct is not None and coverage_pct < 95.0:
            alerts.append(
                _make_alert(
                    "exec_coverage_low",
                    "critical" if coverage_pct < 90.0 else "warning",
                    "execution",
                    "执行覆盖率偏低",
                    "可对齐的执行样本覆盖率偏低，说明当前一致性诊断样本并不完整。",
                    metric_path="risk.exec_consistency.coverage_pct",
                    observed_value=coverage_pct,
                    threshold=95.0,
                    comparator="lt",
                )
            )
        ret_gap_mae_pct = _to_float(exec_diag.get("ret_gap_mae_pct"))
        if ret_gap_mae_pct is not None and ret_gap_mae_pct > 0.75:
            alerts.append(
                _make_alert(
                    "exec_return_gap_mae_high",
                    "critical" if ret_gap_mae_pct > 1.5 else "warning",
                    "execution",
                    "执行收益偏差偏大",
                    "执行收益与参考口径之间的平均绝对偏差过大，说明执行层面存在明显摩擦或口径漂移。",
                    metric_path="risk.exec_consistency.ret_gap_mae_pct",
                    observed_value=ret_gap_mae_pct,
                    threshold=0.75,
                    comparator="gt",
                )
            )
        order_block_rate_pct = _to_float(exec_diag.get("order_block_rate_mean_pct"))
        if order_block_rate_pct is not None and order_block_rate_pct > 10.0:
            alerts.append(
                _make_alert(
                    "exec_order_block_rate_high",
                    "critical" if order_block_rate_pct > 20.0 else "warning",
                    "execution",
                    "订单阻塞率偏高",
                    "订单阻塞率偏高，说明可执行性或路由规则正在明显削弱组合落地能力。",
                    metric_path="risk.exec_consistency.order_block_rate_mean_pct",
                    observed_value=order_block_rate_pct,
                    threshold=10.0,
                    comparator="gt",
                )
            )
        risk_block_rate_pct = _to_float(exec_diag.get("risk_block_rate_mean_pct"))
        if risk_block_rate_pct is not None and risk_block_rate_pct > 15.0:
            alerts.append(
                _make_alert(
                    "exec_risk_block_rate_high",
                    "critical" if risk_block_rate_pct > 25.0 else "warning",
                    "execution",
                    "风险拦截率偏高",
                    "风控拦截率偏高，组合在执行前被大量削弱，后续需要检查风险门禁是否过严或元数据是否退化。",
                    metric_path="risk.exec_consistency.risk_block_rate_mean_pct",
                    observed_value=risk_block_rate_pct,
                    threshold=15.0,
                    comparator="gt",
                    context={"primary_driver_top": exec_diag.get("primary_driver_top", "")},
                )
            )

    if not pretrade_alignment:
        alerts.append(
            _make_alert(
                "pretrade_alignment_data_missing",
                "warning",
                "pretrade",
                "缺少前置风控对齐摘要",
                "尚未找到前置风控对齐摘要文件，无法判断信号层与执行层是否保持统一门禁口径。",
                metric_path="risk.pretrade_alignment",
                comparator="missing",
            )
        )
    else:
        metrics = pretrade_alignment.get("metrics", {}) if isinstance(pretrade_alignment.get("metrics"), dict) else {}
        match_rate_pct = _to_float(metrics.get("match_rate_pct"))
        if match_rate_pct is not None and match_rate_pct < 90.0:
            alerts.append(
                _make_alert(
                    "pretrade_match_rate_low",
                    "critical" if match_rate_pct < 80.0 else "warning",
                    "pretrade",
                    "前置风控匹配率偏低",
                    "信号层与执行层的前置风控匹配率偏低，说明两边口径仍存在明显漂移。",
                    metric_path="risk.pretrade_alignment.metrics.match_rate_pct",
                    observed_value=match_rate_pct,
                    threshold=90.0,
                    comparator="lt",
                    context={"top_reason": metrics.get("top_p2_risk_block_reason", "")},
                )
            )
        mean_p2_block_pct = _to_float(metrics.get("mean_p2_risk_blocked_rate_pct"))
        if mean_p2_block_pct is not None and mean_p2_block_pct > 10.0:
            alerts.append(
                _make_alert(
                    "pretrade_risk_block_rate_high",
                    "critical" if mean_p2_block_pct > 20.0 else "warning",
                    "pretrade",
                    "前置风控拦截率偏高",
                    "P2 风控拦截率偏高，说明执行层面被大量削弱，需要继续检查行业、容量和未知元数据门禁。",
                    metric_path="risk.pretrade_alignment.metrics.mean_p2_risk_blocked_rate_pct",
                    observed_value=mean_p2_block_pct,
                    threshold=10.0,
                    comparator="gt",
                    context={"top_reason": metrics.get("top_p2_risk_block_reason", "")},
                )
            )

    if exposure_summary:
        exposure_row = exposure_summary[0]
        avg_hhi = _to_float(exposure_row.get("avg_hhi"))
        if avg_hhi is not None and avg_hhi > 0.18:
            alerts.append(
                _make_alert(
                    "exposure_hhi_high",
                    "critical" if avg_hhi > 0.25 else "warning",
                    "exposure",
                    "组合集中度偏高",
                    "组合平均 HHI 偏高，说明当前持仓结构过于集中。",
                    metric_path="risk.exposure_summary[0].avg_hhi",
                    observed_value=avg_hhi,
                    threshold=0.18,
                    comparator="gt",
                    context={"state": exposure_row.get("state", "")},
                )
            )
        avg_positions = _to_float(exposure_row.get("avg_positions"))
        if avg_positions is not None and avg_positions < 5.0:
            alerts.append(
                _make_alert(
                    "exposure_avg_positions_low",
                    "critical" if avg_positions < 3.0 else "warning",
                    "exposure",
                    "平均持仓数偏低",
                    "平均持仓数偏低，组合分散度不足，单票波动会被明显放大。",
                    metric_path="risk.exposure_summary[0].avg_positions",
                    observed_value=avg_positions,
                    threshold=5.0,
                    comparator="lt",
                    context={"state": exposure_row.get("state", "")},
                )
            )
        avg_exposure_pct = _to_float(exposure_row.get("avg_exposure_pct"))
        if avg_exposure_pct is not None and (avg_exposure_pct > 85.0 or avg_exposure_pct < 20.0):
            alerts.append(
                _make_alert(
                    "exposure_avg_exposure_extreme",
                    "warning",
                    "exposure",
                    "平均仓位处于极端区间",
                    "平均暴露过高或过低，都说明当前策略状态与组合约束可能需要重新校准。",
                    metric_path="risk.exposure_summary[0].avg_exposure_pct",
                    observed_value=avg_exposure_pct,
                    threshold={"low": 20.0, "high": 85.0},
                    comparator="outside",
                    context={"state": exposure_row.get("state", "")},
                )
            )

    if exposure_industry_top:
        top_industry = exposure_industry_top[0]
        avg_weight_pct = _to_float(top_industry.get("avg_weight_pct"))
        max_weight_pct = _to_float(top_industry.get("max_weight_pct"))
        if avg_weight_pct is not None and avg_weight_pct > 30.0:
            alerts.append(
                _make_alert(
                    "industry_weight_concentration_high",
                    "critical" if avg_weight_pct > 40.0 else "warning",
                    "exposure",
                    "行业平均权重过高",
                    "头部行业长期平均权重过高，组合可能正暴露在过度拥挤的单一赛道里。",
                    metric_path="risk.industry_top[0].avg_weight_pct",
                    observed_value=avg_weight_pct,
                    threshold=30.0,
                    comparator="gt",
                    context={"industry": top_industry.get("industry", "")},
                )
            )
        if max_weight_pct is not None and max_weight_pct > 45.0:
            alerts.append(
                _make_alert(
                    "industry_max_weight_too_high",
                    "critical",
                    "exposure",
                    "行业峰值权重过高",
                    "头部行业峰值权重已经偏离分散化要求，需要复核行业限额和未知行业映射。",
                    metric_path="risk.industry_top[0].max_weight_pct",
                    observed_value=max_weight_pct,
                    threshold=45.0,
                    comparator="gt",
                    context={"industry": top_industry.get("industry", "")},
                )
            )

    if not capacity_recent:
        alerts.append(
            _make_alert(
                "capacity_data_missing",
                "warning",
                "capacity",
                "缺少容量摘要",
                "尚未找到容量与成本摘要文件，无法判断当前组合是否仍处于可交易区间。",
                metric_path="risk.capacity_recent",
                comparator="missing",
            )
        )
    else:
        capacity_row = capacity_recent[0]
        max_participation_pct = _to_float(capacity_row.get("max_participation_pct"))
        capacity_multiple = _to_float(capacity_row.get("capacity_multiple"))
        roundtrip_cost_bps = _to_float(capacity_row.get("estimated_roundtrip_cost_bps"))
        if max_participation_pct is not None and max_participation_pct > 15.0:
            alerts.append(
                _make_alert(
                    "capacity_participation_high",
                    "critical" if max_participation_pct > 25.0 else "warning",
                    "capacity",
                    "参与率偏高",
                    "最大参与率偏高，当前组合对成交额的依赖已经开始影响真实可执行性。",
                    metric_path="risk.capacity_recent[0].max_participation_pct",
                    observed_value=max_participation_pct,
                    threshold=15.0,
                    comparator="gt",
                    context={"signal_date": capacity_row.get("signal_date", "")},
                )
            )
        if capacity_multiple is not None and capacity_multiple < 2.0:
            alerts.append(
                _make_alert(
                    "capacity_multiple_low",
                    "critical" if capacity_multiple < 1.2 else "warning",
                    "capacity",
                    "容量倍数偏低",
                    "容量倍数偏低，说明策略可承载资金空间已经开始收缩。",
                    metric_path="risk.capacity_recent[0].capacity_multiple",
                    observed_value=capacity_multiple,
                    threshold=2.0,
                    comparator="lt",
                    context={"signal_date": capacity_row.get("signal_date", "")},
                )
            )
        if roundtrip_cost_bps is not None and roundtrip_cost_bps > 30.0:
            alerts.append(
                _make_alert(
                    "capacity_cost_high",
                    "critical" if roundtrip_cost_bps > 50.0 else "warning",
                    "capacity",
                    "交易成本压力偏高",
                    "估算的往返交易成本偏高，后续需要继续复核滑点和参与率约束。",
                    metric_path="risk.capacity_recent[0].estimated_roundtrip_cost_bps",
                    observed_value=roundtrip_cost_bps,
                    threshold=30.0,
                    comparator="gt",
                    context={"signal_date": capacity_row.get("signal_date", "")},
                )
            )

    alerts.sort(key=lambda item: (_severity_rank(str(item.get("severity", ""))), str(item.get("domain", "")), str(item.get("title", ""))))
    return alerts


def _normalize_stock_code(raw) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return s.zfill(6)


def _build_stock_name_map(meta_file: str, daily_df: pd.DataFrame | None = None, scan_df: pd.DataFrame | None = None) -> dict[str, str]:
    code_to_name: dict[str, str] = {}

    def add_from_df(df: pd.DataFrame | None):
        if df is None or df.empty:
            return
        if "代码" not in df.columns or "名称" not in df.columns:
            return
        sub = df[["代码", "名称"]].copy()
        for code, name in sub.itertuples(index=False, name=None):
            c = _normalize_stock_code(code)
            n = str(name or "").strip()
            if not c or not n or n.lower() == "nan" or n == c:
                continue
            code_to_name[c] = n

    add_from_df(daily_df)
    add_from_df(scan_df)

    if os.path.exists(meta_file):
        try:
            mdf = pd.read_csv(meta_file, dtype=str)
            if {"ts_code", "name"}.issubset(mdf.columns):
                for ts_code, name in mdf[["ts_code", "name"]].itertuples(index=False, name=None):
                    c = _normalize_stock_code(ts_code)
                    n = str(name or "").strip()
                    if c and n and n.lower() != "nan" and c not in code_to_name:
                        code_to_name[c] = n
            elif {"代码", "名称"}.issubset(mdf.columns):
                for code, name in mdf[["代码", "名称"]].itertuples(index=False, name=None):
                    c = _normalize_stock_code(code)
                    n = str(name or "").strip()
                    if c and n and n.lower() != "nan" and c not in code_to_name:
                        code_to_name[c] = n
        except Exception:
            pass

    return code_to_name


def _build_returns_drilldown(trades_df: pd.DataFrame, parquet_file: str) -> dict[str, list[dict[str, Any]]]:
    if trades_df.empty or "exit_date" not in trades_df.columns or "equity" not in trades_df.columns:
        return {"annual": [], "monthly": [], "daily": []}

    tdf = trades_df.copy()
    tdf["exit_date"] = pd.to_datetime(tdf["exit_date"], errors="coerce")
    tdf["equity"] = pd.to_numeric(tdf["equity"], errors="coerce")
    tdf = tdf.dropna(subset=["exit_date", "equity"]).sort_values("exit_date")
    if tdf.empty:
        return {"annual": [], "monthly": [], "daily": []}

    start_day = tdf["exit_date"].min().normalize()
    end_day = tdf["exit_date"].max().normalize()

    if os.path.exists(parquet_file):
        cal = pd.read_parquet(parquet_file, columns=["trade_date"])
        cal_days = pd.to_datetime(cal["trade_date"].astype(str), errors="coerce").dropna().dt.normalize().drop_duplicates()
        cal_days = cal_days[(cal_days >= start_day) & (cal_days <= end_day)].sort_values()
    else:
        cal_days = pd.date_range(start_day, end_day, freq="B")
    if len(cal_days) == 0:
        return {"annual": [], "monthly": [], "daily": []}

    eq_by_exit = tdf.drop_duplicates(subset=["exit_date"], keep="last").set_index("exit_date")["equity"].to_dict()
    rows = []
    prev_eq = 1.0
    cur_eq = 1.0
    for day in cal_days:
        if day in eq_by_exit:
            cur_eq = float(eq_by_exit[day])
        daily_ret = (cur_eq / prev_eq - 1.0) if prev_eq > 0 else 0.0
        rows.append({"date": day, "equity": cur_eq, "daily_return_pct": daily_ret * 100.0})
        prev_eq = cur_eq

    ddf = pd.DataFrame(rows)
    ddf["year"] = ddf["date"].dt.year.astype(int)
    ddf["month"] = ddf["date"].dt.strftime("%Y-%m")

    month_end = ddf.groupby("month", as_index=False).tail(1).copy().sort_values("date")
    month_end["prev_equity"] = month_end["equity"].shift(1).fillna(1.0)
    month_end["return_pct"] = (month_end["equity"] / month_end["prev_equity"] - 1.0) * 100.0

    year_end = ddf.groupby("year", as_index=False).tail(1).copy().sort_values("date")
    year_end["prev_equity"] = year_end["equity"].shift(1).fillna(1.0)
    year_end["return_pct"] = (year_end["equity"] / year_end["prev_equity"] - 1.0) * 100.0

    annual = [{"year": int(r.year), "return_pct": float(r.return_pct), "equity": float(r.equity)} for r in year_end.itertuples(index=False)]
    monthly = [
        {"month": str(r.month), "year": int(str(r.month)[:4]), "return_pct": float(r.return_pct), "equity": float(r.equity)}
        for r in month_end.itertuples(index=False)
    ]
    daily = [
        {
            "date": r.date.strftime("%Y-%m-%d"),
            "month": r.date.strftime("%Y-%m"),
            "year": int(r.date.year),
            "return_pct": float(r.daily_return_pct),
            "equity": float(r.equity),
        }
        for r in ddf.itertuples(index=False)
    ]
    return {"annual": annual, "monthly": monthly, "daily": daily}


def load_platform_overview(cfg: dict[str, Any], date_q: str | None = None) -> dict[str, Any]:
    output_dir = cfg["OUTPUT_DIR"]
    parquet_file = cfg["PARQUET_FILE"]
    meta_file = cfg["META_FILE"]

    ymd = None
    if date_q:
        ymd = datetime.strptime(date_q, "%Y-%m-%d").strftime("%Y%m%d")

    daily_file = _find_date_file(output_dir, "daily", ymd) if ymd else None
    if daily_file is None:
        daily_file = _find_latest_file(
            sorted(set(glob.glob(os.path.join(output_dir, "daily", "daily_*.csv")) + glob.glob(os.path.join(output_dir, "daily_*.csv"))))
        )
    if daily_file is None:
        raise FileNotFoundError("未找到 daily 推荐结果，请先运行 daily_all.py")

    date_token = os.path.basename(daily_file).replace("daily_", "").replace(".csv", "")
    scan_file = _find_date_file(output_dir, "scan", date_token) or _find_latest_file(
        sorted(set(glob.glob(os.path.join(output_dir, "scan", "mfts_scan_*.csv")) + glob.glob(os.path.join(output_dir, "mfts_scan_*.csv"))))
    )
    verify_file = _find_date_file(output_dir, "verify", date_token)
    history_file = _find_latest_file([os.path.join(output_dir, "verify", "history_stats.csv"), os.path.join(output_dir, "history_stats.csv")])
    backtest_file = _find_latest_file([os.path.join(output_dir, "backtest", "quant_backtest_summary.csv"), os.path.join(output_dir, "quant_backtest_summary.csv")])
    opt_file = _find_latest_file([os.path.join(output_dir, "backtest", "quant_optimization_results.csv"), os.path.join(output_dir, "quant_optimization_results.csv")])
    trades_files = sorted(
        set(glob.glob(os.path.join(output_dir, "backtest", "quant_trades_*.csv")) + glob.glob(os.path.join(output_dir, "quant_trades_*.csv")))
    )
    latest_trades_file = trades_files[-1] if trades_files else None

    cache_key = (
        date_q or "",
        os.environ.get("MFTS_WEB_FULL_COVERAGE", "0"),
        _existing_signature([daily_file, scan_file or "", verify_file or "", history_file or "", backtest_file or "", opt_file or "", latest_trades_file or "", meta_file]),
    )
    cached = _OVERVIEW_CACHE.get(cache_key)
    if cached is not None:
        return cached

    daily_df = pd.read_csv(daily_file, dtype={"代码": str})
    if "代码" in daily_df.columns:
        daily_df["代码"] = daily_df["代码"].apply(_normalize_stock_code)
    date_display = f"{date_token[:4]}-{date_token[4:6]}-{date_token[6:8]}" if len(date_token) >= 8 else (date_q or "")

    state = str(daily_df["市场状态"].iloc[0]) if ("市场状态" in daily_df.columns and not daily_df.empty) else ""
    position = str(daily_df["建议仓位"].iloc[0]) if ("建议仓位" in daily_df.columns and not daily_df.empty) else ""
    single_cap = str(daily_df["单票上限"].iloc[0]) if ("单票上限" in daily_df.columns and not daily_df.empty) else ""
    hold_days = int(daily_df["建议持有天数"].iloc[0]) if ("建议持有天数" in daily_df.columns and not daily_df.empty) else None

    scan_df = pd.DataFrame()
    if scan_file and os.path.exists(scan_file):
        scan_df = pd.read_csv(scan_file, dtype={"代码": str})
        if "代码" in scan_df.columns:
            scan_df["代码"] = scan_df["代码"].apply(_normalize_stock_code)

    name_map = _build_stock_name_map(meta_file, daily_df=daily_df, scan_df=scan_df)
    for df in [daily_df, scan_df]:
        if not df.empty and "代码" in df.columns:
            if "名称" not in df.columns:
                df["名称"] = None
            df["名称"] = df.apply(
                lambda row: (
                    name_map.get(str(row.get("代码", "")), str(row.get("代码", "")))
                    if str(row.get("名称", "")).strip() in {"", "nan", str(row.get("代码", "")).strip()}
                    else row.get("名称")
                ),
                axis=1,
            )

    verify_df = pd.DataFrame()
    if verify_file and os.path.exists(verify_file):
        verify_df = pd.read_csv(verify_file, dtype={"代码": str})

    hist_df = pd.DataFrame()
    if history_file and os.path.exists(history_file):
        hist_df = pd.read_csv(history_file)
        if "验证日期" in hist_df.columns:
            hist_df["验证日期"] = pd.to_datetime(hist_df["验证日期"], errors="coerce")
            hist_df = hist_df.dropna(subset=["验证日期"]).sort_values("验证日期")

    backtest_summary: dict[str, Any] = {}
    if backtest_file and os.path.exists(backtest_file):
        bdf = pd.read_csv(backtest_file)
        if not bdf.empty:
            backtest_summary = bdf.iloc[-1].to_dict()

    equity_curve: list[dict[str, Any]] = []
    trade_records: list[dict[str, Any]] = []
    returns_drilldown: dict[str, list[dict[str, Any]]] = {"annual": [], "monthly": [], "daily": []}
    if latest_trades_file and os.path.exists(latest_trades_file):
        tdf = pd.read_csv(latest_trades_file)
        tdf_curve = tdf.copy()
        if not tdf_curve.empty and {"exit_date", "equity"}.issubset(tdf_curve.columns):
            tdf_curve["exit_date"] = pd.to_datetime(tdf_curve["exit_date"], errors="coerce")
            tdf_curve = tdf_curve.dropna(subset=["exit_date"]).sort_values("exit_date").tail(180)
            equity_curve = [{"date": day.strftime("%Y-%m-%d"), "equity": float(value)} for day, value in tdf_curve[["exit_date", "equity"]].itertuples(index=False, name=None)]
        for col in [
            "signal_date",
            "entry_date",
            "exit_date",
            "state",
            "selected_count",
            "valid_count",
            "per_position_weight",
            "total_exposure",
            "avg_stock_ret",
            "portfolio_ret",
            "equity",
            "codes",
        ]:
            if col not in tdf.columns:
                tdf[col] = None
        tdf_recent = tdf.tail(50).copy()
        for date_col in ["signal_date", "entry_date", "exit_date"]:
            if date_col in tdf_recent.columns:
                tdf_recent[date_col] = pd.to_datetime(tdf_recent[date_col], errors="coerce").dt.strftime("%Y-%m-%d").fillna(tdf_recent[date_col].astype(str))
        if "codes" in tdf_recent.columns:
            def _build_positions(codes_str):
                items = [x.strip() for x in str(codes_str or "").split(",") if x and str(x).strip()]
                return [{"code": code, "name": name_map.get(code, code)} for code in [_normalize_stock_code(raw) for raw in items] if code]
            tdf_recent["positions"] = tdf_recent["codes"].apply(_build_positions)
        else:
            tdf_recent["positions"] = [[] for _ in range(len(tdf_recent))]
        trade_records = tdf_recent[
            [
                "signal_date",
                "entry_date",
                "exit_date",
                "state",
                "selected_count",
                "valid_count",
                "per_position_weight",
                "total_exposure",
                "avg_stock_ret",
                "portfolio_ret",
                "equity",
                "codes",
                "positions",
            ]
        ].to_dict("records")
        returns_drilldown = _build_returns_drilldown(tdf, parquet_file)

    optimize_top: list[dict[str, Any]] = []
    if opt_file and os.path.exists(opt_file):
        odf = pd.read_csv(opt_file)
        if not odf.empty:
            odf = odf.sort_values(["pass_hard_filters", "rank_score"], ascending=[False, False]) if "pass_hard_filters" in odf.columns else odf.sort_values("rank_score", ascending=False)
            keep_cols = [
                "rank",
                "pass_hard_filters",
                "top_n",
                "holding_days",
                "max_single_pos",
                "use_regime_position",
                "annual_return_pct",
                "max_drawdown_pct",
                "sharpe",
                "annual_turnover_pct",
            ]
            optimize_top = odf[[col for col in keep_cols if col in odf.columns]].head(5).to_dict("records")

    coverage = int(len(daily_df))
    if os.environ.get("MFTS_WEB_FULL_COVERAGE", "0") == "1" and os.path.exists(parquet_file):
        try:
            cdf = pd.read_parquet(parquet_file, columns=["trade_date", "ts_code"])
            cdf["trade_date"] = pd.to_datetime(cdf["trade_date"].astype(str), errors="coerce").dt.strftime("%Y%m%d")
            day_df = cdf[cdf["trade_date"] == date_token]
            coverage = int(day_df["ts_code"].astype(str).str.split(".").str[0].nunique())
        except Exception:
            coverage = int(len(daily_df))

    verify_stats: dict[str, Any] = {}
    if not verify_df.empty and "实际收益%" in verify_df.columns:
        wins = verify_df["实际收益%"] > 0
        verify_stats = {
            "count": int(len(verify_df)),
            "win_rate_pct": float(wins.mean() * 100),
            "avg_return_pct": float(verify_df["实际收益%"].mean()),
            "max_return_pct": float(verify_df["实际收益%"].max()),
            "min_return_pct": float(verify_df["实际收益%"].min()),
        }

    history_recent: list[dict[str, Any]] = []
    if not hist_df.empty:
        tail = hist_df.tail(60)
        history_recent = [
            {
                "date": day.strftime("%Y-%m-%d"),
                "win_rate_pct": float(win_rate) if pd.notna(win_rate) else 0.0,
                "avg_return_pct": float(avg_ret) if pd.notna(avg_ret) else 0.0,
                "top10_win_rate_pct": float(top10) if pd.notna(top10) else 0.0,
            }
            for day, win_rate, avg_ret, top10 in tail[["验证日期", "整体胜率%", "平均收益%", "Top10胜率%"]].itertuples(index=False, name=None)
        ]

    payload = _sanitize_for_json(
        {
            "success": True,
            "date": date_display,
            "coverage": coverage,
            "daily_summary": {
                "count": int(len(daily_df)),
                "market_state": state,
                "position": position,
                "single_cap": single_cap,
                "hold_days": hold_days,
            },
            "daily_top": daily_df.head(20).to_dict("records"),
            "scan_summary": {"count": int(len(scan_df))},
            "scan_top": scan_df.head(20).to_dict("records"),
            "verify_stats": verify_stats,
            "history_recent": history_recent,
            "backtest_summary": backtest_summary,
            "equity_curve": equity_curve,
            "trade_records": trade_records,
            "returns_drilldown": returns_drilldown,
            "optimize_top": optimize_top,
            "cache": {"key_size": len(cache_key[2]), "target_date": date_q or ""},
        }
    )
    _OVERVIEW_CACHE.clear()
    _OVERVIEW_CACHE[cache_key] = payload
    return payload


def load_platform_ops_overview(cfg: dict[str, Any]) -> dict[str, Any]:
    base_dir = cfg["BASE_DIR"]
    output_dir = os.path.join(base_dir, "output")
    risk_dir = os.path.join(output_dir, "risk")
    backtest_dir = os.path.join(output_dir, "backtest")
    registry_file = os.path.join(output_dir, "platform", "experiments", "registry.json")
    run_dir = os.path.join(output_dir, "platform", "runs")
    promotion_decision_file = os.path.join(backtest_dir, "promotion_decision_latest.json")
    promotion_history_files = sorted(glob.glob(os.path.join(backtest_dir, "promotion_decision_*.json")))
    latest_run = load_latest_run_manifest(base_dir) or {}
    experiments = load_experiment_registry(base_dir)

    risk_files = [
        os.path.join(risk_dir, "risk_exposure_summary_latest.csv"),
        os.path.join(risk_dir, "risk_exposure_industry_latest.csv"),
        os.path.join(risk_dir, "exec_consistency_summary_paper_latest.json"),
        os.path.join(risk_dir, "exec_consistency_paper_latest.csv"),
        os.path.join(risk_dir, "pretrade_alignment_summary_paper_pretrade_diag_latest.json"),
        os.path.join(risk_dir, "capacity_cost_latest.csv"),
        os.path.join(risk_dir, "exec_consistency_style_attribution_paper_latest.csv"),
        promotion_decision_file,
        registry_file,
        run_dir,
        *promotion_history_files,
    ]
    cache_key = ("ops", _existing_signature(risk_files))
    cached = _OPS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    exposure_summary = []
    exposure_industry_top = []
    capacity_recent = []
    style_layers = []
    exec_diag = {}
    pretrade_alignment = {}
    promotion_decision = {}
    promotion_history = []

    exposure_file = os.path.join(risk_dir, "risk_exposure_summary_latest.csv")
    if os.path.exists(exposure_file):
        exposure_df = pd.read_csv(exposure_file)
        exposure_summary = exposure_df.to_dict("records")

    industry_file = os.path.join(risk_dir, "risk_exposure_industry_latest.csv")
    if os.path.exists(industry_file):
        industry_df = pd.read_csv(industry_file)
        sort_col = "avg_weight_pct" if "avg_weight_pct" in industry_df.columns else industry_df.columns[0]
        exposure_industry_top = industry_df.sort_values(sort_col, ascending=False).head(8).to_dict("records")

    exec_file = os.path.join(risk_dir, "exec_consistency_summary_paper_latest.json")
    if os.path.exists(exec_file):
        exec_diag = json.loads(Path(exec_file).read_text(encoding="utf-8"))

    pretrade_file = os.path.join(risk_dir, "pretrade_alignment_summary_paper_pretrade_diag_latest.json")
    if os.path.exists(pretrade_file):
        pretrade_alignment = json.loads(Path(pretrade_file).read_text(encoding="utf-8"))

    capacity_file = os.path.join(risk_dir, "capacity_cost_latest.csv")
    if os.path.exists(capacity_file):
        capacity_df = pd.read_csv(capacity_file)
        if "signal_date" in capacity_df.columns:
            capacity_df = capacity_df.sort_values("signal_date", ascending=False)
        keep_cols = [
            "signal_date",
            "state",
            "total_exposure_pct",
            "position_count",
            "max_participation_pct",
            "estimated_roundtrip_cost_bps",
            "capacity_multiple",
            "portfolio_ret_pct",
        ]
        capacity_recent = capacity_df[[col for col in keep_cols if col in capacity_df.columns]].head(8).to_dict("records")

    style_file = os.path.join(risk_dir, "exec_consistency_style_attribution_paper_latest.csv")
    if os.path.exists(style_file):
        style_df = pd.read_csv(style_file)
        keep_cols = [
            "layer_type",
            "layer_key",
            "coverage_pct",
            "ret_gap_mean_pct",
            "ret_gap_mae_pct",
            "risk_block_rate_mean_pct",
            "style_hit_density_mean_pct",
        ]
        style_layers = style_df[[col for col in keep_cols if col in style_df.columns]].head(10).to_dict("records")

    if os.path.exists(promotion_decision_file):
        promotion_decision = _load_promotion_decision(base_dir)
    promotion_history = _load_promotion_decision_history(base_dir)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    platform_summary = {
        "platform_output_exists": os.path.exists(os.path.join(output_dir, "platform")),
        "latest_run_id": latest_run.get("run_id", ""),
        "latest_run_status": latest_run.get("status", "missing"),
        "latest_run_started_at": latest_run.get("started_at", "") or latest_run.get("created_at", ""),
        "experiment_count": len(experiments),
    }
    alerts = _build_ops_alerts(
        platform_summary,
        exposure_summary,
        exposure_industry_top,
        capacity_recent,
        exec_diag,
        pretrade_alignment,
        promotion_decision,
    )
    alert_summary = _build_alert_summary(alerts)
    alert_snapshot = _build_ops_alert_snapshot(
        generated_at,
        platform_summary,
        alert_summary,
        alerts,
        exec_diag,
        pretrade_alignment,
        capacity_recent,
        promotion_decision,
    )
    alert_history = _record_ops_alert_snapshot(base_dir, alert_snapshot)
    alert_trends = _build_alert_trends(alert_history)
    promotion_trends = _build_promotion_trends(promotion_history)

    payload = _sanitize_for_json(
        {
            "success": True,
            "generated_at": generated_at,
            "platform": platform_summary,
            "alert_summary": alert_summary,
            "alerts": alerts,
            "alert_history": alert_history[-10:],
            "alert_trends": alert_trends,
            "latest_run": latest_run,
            "experiments": experiments[:8],
            "governance": {
                "promotion_decision": promotion_decision,
                "promotion_history": promotion_history,
                "promotion_trends": promotion_trends,
            },
            "risk": {
                "exposure_summary": exposure_summary,
                "industry_top": exposure_industry_top,
                "capacity_recent": capacity_recent,
                "style_layers": style_layers,
                "exec_consistency": exec_diag,
                "pretrade_alignment": pretrade_alignment,
            },
        }
    )
    _OPS_CACHE.clear()
    _OPS_CACHE[cache_key] = payload
    return payload
