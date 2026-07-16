"""promotion_decision.json schema loading and validation."""

from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BASE_DIR / "schemas" / "promotion_decision.schema.json"


def load_promotion_decision_schema(schema_path: str | Path | None = None) -> dict[str, object]:
    path = Path(schema_path) if schema_path else SCHEMA_PATH
    if not path.exists():
        raise FileNotFoundError(f"未找到 promotion decision schema: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_strict(path: str | Path) -> dict[str, object]:
    file_path = Path(path)

    def _hook(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"JSON 包含重复 key: {key}")
            out[key] = value
        return out

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=_hook)
    if not isinstance(data, dict):
        raise ValueError("promotion_decision 顶层必须是对象")
    return data


def _validate_with_builtin_rules(payload: dict[str, object]) -> None:
    required = {
        "schema_version",
        "generated_at",
        "review_id",
        "expected_current_default_profile",
        "final_default_profile",
        "candidate_profile",
        "decision",
        "change_required",
        "reason_code",
        "rationale",
        "evidence",
        "artifacts",
    }
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise ValueError(f"promotion_decision 缺少字段: {', '.join(missing)}")

    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("schema_version 必须为 1")

    decision = str(payload.get("decision", "")).strip().lower()
    if decision not in {"keep", "promote"}:
        raise ValueError(f"decision 非法: {decision}")

    expected_current = str(payload.get("expected_current_default_profile", "")).strip()
    final_default = str(payload.get("final_default_profile", "")).strip()
    if not expected_current or not final_default:
        raise ValueError("expected_current_default_profile / final_default_profile 不能为空")

    generated_at = str(payload.get("generated_at", "")).strip()
    if not generated_at:
        raise ValueError("generated_at 不能为空")
    try:
        from datetime import datetime

        datetime.fromisoformat(generated_at)
    except Exception as exc:
        raise ValueError(f"generated_at 不是合法 ISO 时间: {generated_at}") from exc

    change_required = bool(payload.get("change_required", False))
    if change_required != (final_default != expected_current):
        raise ValueError("change_required 与 final_default_profile / expected_current_default_profile 不一致")

    if decision == "promote" and not change_required:
        raise ValueError("decision=promote 时 change_required 必须为 true")
    if decision == "keep" and final_default != expected_current:
        raise ValueError("decision=keep 时 final_default_profile 应等于 expected_current_default_profile")

    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("evidence 必须是对象")
    for key in [
        "main_score",
        "candidate_score",
        "score_margin",
        "candidate_p2_executed_days_total",
        "min_p2_executed_days",
        "candidate_p2_gate_passed",
        "candidate_promotion_hard_gate_passed",
        "candidate_execution_parity_passed",
    ]:
        if key not in evidence:
            raise ValueError(f"evidence 缺少字段: {key}")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("artifacts 必须是对象")
    for key in ["review_csv", "review_meta_json"]:
        if not str(artifacts.get(key, "")).strip():
            raise ValueError(f"artifacts.{key} 不能为空")


def validate_promotion_decision_payload(
    payload: dict[str, object],
    *,
    schema_path: str | Path | None = None,
) -> None:
    _validate_with_builtin_rules(payload)

    try:
        import jsonschema  # type: ignore
    except Exception:
        return

    schema = load_promotion_decision_schema(schema_path)
    jsonschema.validate(instance=payload, schema=schema)
