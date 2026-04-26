"""研究实验注册表。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path


def _default_registry(base_dir: str | Path) -> Path:
    return Path(base_dir) / "output" / "platform" / "experiments" / "registry.json"


def load_experiment_registry(base_dir: str | Path) -> list[dict[str, object]]:
    path = _default_registry(base_dir)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return []


def build_experiment_record(
    *,
    name: str,
    stage: str,
    params: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
    artifacts: dict[str, object] | None = None,
    lineage: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "experiment_id": f"{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "name": str(name),
        "stage": str(stage),
        "created_at": datetime.now().isoformat(),
        "params": dict(params or {}),
        "metrics": dict(metrics or {}),
        "artifacts": dict(artifacts or {}),
        "lineage": dict(lineage or {}),
    }


def register_experiment(base_dir: str | Path, record: dict[str, object]) -> Path:
    path = _default_registry(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    items = load_experiment_registry(base_dir)
    items.append(record)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
