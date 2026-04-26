"""LiveBroker: 实盘执行通道抽象（含 shadow 模式）。"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from core.execution.adapter import BrokerAdapter, RebalanceResult
from core.execution.paper_broker import PaperBroker


class GatewayClient(Protocol):
    """实盘券商网关最小协议。"""

    def get_account_snapshot(self) -> dict[str, object]:
        """返回 cash + positions（结构与 paper state 对齐）。"""
        ...

    def submit_orders(self, orders_df: pd.DataFrame) -> pd.DataFrame:
        """提交订单并返回成交反馈（可异步，至少应返回 status/filled_qty）。"""
        ...


class LiveBroker(BrokerAdapter):
    """
    live_mode:
    - shadow: 用本地撮合模拟实盘流程（默认，便于联调）
    - gateway: 预留真实网关接入（需注入 gateway_client）
    """

    name = "live"

    def __init__(
        self,
        *,
        state_file,
        initial_capital: float,
        lot_size: int,
        fee_bps: float,
        slippage_bps: float,
        stamp_tax_bps: float,
        live_mode: str = "shadow",
        gateway_client: GatewayClient | None = None,
    ) -> None:
        self.live_mode = str(live_mode or "shadow").strip().lower()
        self.gateway_client = gateway_client
        self.shadow_engine = PaperBroker(
            state_file=state_file,
            initial_capital=initial_capital,
            lot_size=lot_size,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            stamp_tax_bps=stamp_tax_bps,
        )

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
        if self.live_mode == "shadow":
            result = self.shadow_engine.rebalance(
                signal_df=signal_df,
                signal_date=signal_date,
                trade_date=trade_date,
                bars_idx=bars_idx,
                run_id=run_id,
                top_n=top_n,
                target_total_pos=target_total_pos,
                max_single_pos=max_single_pos,
                reset_state=reset_state,
                dry_run=dry_run,
            )
            if not result.orders_df.empty:
                result.orders_df["channel_status"] = "shadow_simulated"
            return result

        if self.live_mode == "gateway":
            if self.gateway_client is None:
                raise ValueError("live_mode=gateway requires gateway_client")
            # 真实接入位：先用 shadow 引擎计算目标单，再调用网关提交。
            state = self.gateway_client.get_account_snapshot()
            local = self.shadow_engine.rebalance_on_state(
                state=state,
                signal_df=signal_df,
                signal_date=signal_date,
                trade_date=trade_date,
                bars_idx=bars_idx,
                run_id=run_id,
                top_n=top_n,
                target_total_pos=target_total_pos,
                max_single_pos=max_single_pos,
            )
            if not local.orders_df.empty:
                feedback = self.gateway_client.submit_orders(local.orders_df.copy())
                if isinstance(feedback, pd.DataFrame) and not feedback.empty:
                    # 以网关反馈覆盖状态字段（按 run_id+code+side 对齐）
                    merge_keys = [k for k in ["run_id", "code", "side"] if k in feedback.columns and k in local.orders_df.columns]
                    if merge_keys:
                        merged = local.orders_df.merge(
                            feedback[merge_keys + [c for c in ["status", "filled_qty", "reason"] if c in feedback.columns]],
                            on=merge_keys,
                            how="left",
                            suffixes=("", "_gw"),
                        )
                        for c in ["status", "filled_qty", "reason"]:
                            gw = f"{c}_gw"
                            if gw in merged.columns:
                                merged[c] = merged[gw].where(merged[gw].notna(), merged[c])
                                merged = merged.drop(columns=[gw], errors="ignore")
                        local.orders_df = merged
                        local.orders_df["channel_status"] = "gateway_submitted"
            return local

        raise ValueError(f"Unsupported live_mode: {self.live_mode}")

