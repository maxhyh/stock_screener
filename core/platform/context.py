"""平台运行上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DataContext:
    latest_trade_date: str = ""
    data_version: str = ""
    metadata_version: str = ""


@dataclass
class ProfileContext:
    active_profile: str = ""
    label_mode: str = ""
    label_horizon: int = 0


@dataclass
class RunContext:
    run_id: str
    run_type: str
    data: DataContext = field(default_factory=DataContext)
    profile: ProfileContext = field(default_factory=ProfileContext)

