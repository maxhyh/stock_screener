"""平台统一事件模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class PlatformEvent:
    event_type: str
    level: str
    title: str
    content: str
    run_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        if not payload["created_at"]:
            payload["created_at"] = datetime.now().isoformat()
        return payload

