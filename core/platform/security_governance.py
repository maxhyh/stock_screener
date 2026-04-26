"""权限、安全与治理基础层。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path


@dataclass
class SecurityConfig:
    local_only: bool
    api_write_token_present: bool
    alert_webhook_present: bool
    active_profile: str


def load_security_config() -> SecurityConfig:
    return SecurityConfig(
        local_only=os.environ.get("MFTS_LOCAL_ONLY", "true").lower() == "true",
        api_write_token_present=bool(os.environ.get("MFTS_API_WRITE_TOKEN", "").strip()),
        alert_webhook_present=bool(os.environ.get("MFTS_ALERT_WEBHOOK", "").strip()),
        active_profile=str(os.environ.get("MFTS_ACTIVE_PROFILE") or os.environ.get("MFTS_P2_PROFILE") or "").strip(),
    )


def build_config_fingerprint(config: SecurityConfig | dict[str, object]) -> str:
    payload = asdict(config) if isinstance(config, SecurityConfig) else dict(config)
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def record_config_change(
    base_dir: str | Path,
    *,
    actor: str,
    scope: str,
    before: dict[str, object],
    after: dict[str, object],
    reason: str,
) -> Path:
    out_dir = Path(base_dir) / "output" / "platform" / "governance"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "config_changes.jsonl"
    record = {
        "timestamp": datetime.now().isoformat(),
        "actor": str(actor),
        "scope": str(scope),
        "reason": str(reason),
        "before": dict(before),
        "after": dict(after),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
