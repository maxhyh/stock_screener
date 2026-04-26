#!/usr/bin/env python3
"""
依据 promotion_decision.json 更新 default_profile。

约束：
1) 只有 decision == PROMOTE 才允许修改 default_profile
2) 默认只接受 promotion_decision_latest.json 或显式指定文件
3) 不直接做策略判断，只消费 gate 决策结果
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from utils.promotion_decision import (
    load_json_strict,
    load_promotion_decision_schema,
    validate_promotion_decision_payload,
)


BASE_DIR = Path(__file__).resolve().parents[1]
PROFILE_FILE = BASE_DIR / "config" / "quant_live_profiles.json"
BACKTEST_DIR = BASE_DIR / "output" / "backtest"
SCHEMA_FILE = BASE_DIR / "schemas" / "promotion_decision.schema.json"


def main() -> int:
    p = argparse.ArgumentParser(description="应用 promotion_decision.json 到 quant_live_profiles.json")
    p.add_argument("--decision-file", type=str, default=str(BACKTEST_DIR / "promotion_decision_latest.json"))
    p.add_argument("--config", type=str, default=str(PROFILE_FILE))
    p.add_argument("--schema-file", type=str, default=str(SCHEMA_FILE))
    p.add_argument("--dry-run", action="store_true", help="只检查，不写入配置")
    args = p.parse_args()

    decision_file = Path(args.decision_file).resolve()
    config_file = Path(args.config).resolve()
    schema_file = Path(args.schema_file).resolve()
    if not decision_file.exists():
        raise FileNotFoundError(f"未找到 decision 文件: {decision_file}")
    if not config_file.exists():
        raise FileNotFoundError(f"未找到 config 文件: {config_file}")
    load_promotion_decision_schema(schema_file)

    decision = load_json_strict(decision_file)
    validate_promotion_decision_payload(decision, schema_path=schema_file)
    if str(decision.get("decision", "")).lower() != "promote":
        raise RuntimeError(f"decision != PROMOTE，拒绝修改 default_profile: {decision.get('decision')}")

    target_profile = str(decision.get("final_default_profile", "")).strip()
    if not target_profile:
        raise RuntimeError("final_default_profile 为空")

    root = json.loads(config_file.read_text(encoding="utf-8"))
    profiles = root.get("profiles", {})
    if target_profile not in profiles:
        raise RuntimeError(f"目标 profile 不存在于配置中: {target_profile}")

    current = str(root.get("default_profile", "")).strip()
    expected_current = str(decision.get("expected_current_default_profile", "")).strip()
    if expected_current and current != expected_current:
        raise RuntimeError(
            f"default_profile 已变更，拒绝覆盖: current={current}, expected={expected_current}"
        )
    if current == target_profile:
        print(f"default_profile 已是 {target_profile}，无需修改")
        return 0

    print(f"default_profile: {current} -> {target_profile}")
    if args.dry_run:
        return 0

    root["default_profile"] = target_profile
    config_file.write_text(json.dumps(root, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已更新 {config_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
