"""执行通道抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class RebalanceResult:
    """一次再平衡的执行结果。"""

    orders_df: pd.DataFrame
    fills_df: pd.DataFrame
    state: dict[str, object]
    ledger_row: dict[str, object]


class BrokerAdapter(ABC):
    """执行通道统一接口（paper/live 同签名）。"""

    name: str = "unknown"

    @abstractmethod
    def rebalance(
        self,
        *,
        signal_df: pd.DataFrame,
        signal_date: pd.Timestamp,
        trade_date: pd.Timestamp,
        bars_idx: pd.DataFrame,
        run_id: str,
        top_n: int,
        target_total_pos: float,
        max_single_pos: float,
        reset_state: bool = False,
        dry_run: bool = False,
    ) -> RebalanceResult:
        raise NotImplementedError

