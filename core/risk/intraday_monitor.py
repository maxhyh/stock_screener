# -*- coding: utf-8 -*-
"""
盘中/日度风控监控模块。

提供三层保护：
1. 组合级别：日内回撤限制
2. 个股级别：单票止损
3. 标的级别：面值退市风险过滤

使用方法:
    from core.risk.intraday_monitor import IntradayRiskMonitor, IntradayRiskConfig, RiskAction

    monitor = IntradayRiskMonitor(IntradayRiskConfig())
    action = monitor.check_portfolio_drawdown(current_nav=980000, day_open_nav=1000000)
    if action == RiskAction.FORCE_LIQUIDATE:
        ...  # 触发全部清仓
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RiskAction(Enum):
    """风控动作枚举"""
    NORMAL = auto()           # 正常交易
    HALT_NEW_BUYS = auto()    # 禁止新买入，允许卖出
    CLOSE_POSITION = auto()   # 关闭指定仓位
    FORCE_LIQUIDATE = auto()  # 全部清仓
    SKIP_ENTRY = auto()       # 跳过入场（面值/退市风险）


@dataclass
class IntradayRiskConfig:
    """盘中风控配置"""
    # 组合级日内回撤限制
    max_daily_loss_pct: float = -0.03       # 日内回撤 > 3% → 禁止新买入
    max_daily_critical_pct: float = -0.05   # 日内回撤 > 5% → 全部清仓
    # 单票止损
    max_single_stock_loss_pct: float = -0.07  # 单票浮亏 > 7%
    # 面值退市保护
    min_close_price: float = 2.0              # 收盘价低于此的不参与
    min_avg_close_price_5d: float = 2.5       # 5日均价低于此的不参与
    # 涨跌停封板保护
    skip_limit_up_entry: bool = True          # 涨停封板不入场
    # 连续亏损保护
    max_consecutive_losses: int = 5           # 连续第 N 笔亏损后降仓
    consecutive_loss_scale: float = 0.50      # 连续亏损后仓位缩放系数


@dataclass
class RiskCheckResult:
    """风控检查结果"""
    action: RiskAction
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class IntradayRiskMonitor:
    """盘中/日度风控监控"""

    def __init__(self, config: IntradayRiskConfig | None = None):
        self.cfg = config or IntradayRiskConfig()
        self._consecutive_losses: int = 0

    # ------------------------------------------------------------------
    # 组合级别
    # ------------------------------------------------------------------
    def check_portfolio_drawdown(
        self, current_nav: float, day_open_nav: float
    ) -> RiskCheckResult:
        """
        盘中组合回撤检查。

        - 日内回撤 > max_daily_critical_pct → 全部清仓
        - 日内回撤 > max_daily_loss_pct     → 禁止新买入
        """
        if day_open_nav <= 0 or current_nav <= 0:
            return RiskCheckResult(RiskAction.NORMAL, "nav_invalid")

        dd = current_nav / day_open_nav - 1.0

        if dd <= self.cfg.max_daily_critical_pct:
            msg = f"日内回撤 {dd:.2%} 超过临界阈值 {self.cfg.max_daily_critical_pct:.2%}"
            logger.warning("🚨 " + msg)
            return RiskCheckResult(
                RiskAction.FORCE_LIQUIDATE, msg,
                {"drawdown_pct": dd, "threshold": self.cfg.max_daily_critical_pct},
            )

        if dd <= self.cfg.max_daily_loss_pct:
            msg = f"日内回撤 {dd:.2%} 超过警戒阈值 {self.cfg.max_daily_loss_pct:.2%}"
            logger.warning("⚠️ " + msg)
            return RiskCheckResult(
                RiskAction.HALT_NEW_BUYS, msg,
                {"drawdown_pct": dd, "threshold": self.cfg.max_daily_loss_pct},
            )

        return RiskCheckResult(RiskAction.NORMAL)

    # ------------------------------------------------------------------
    # 个股级别
    # ------------------------------------------------------------------
    def check_single_stock_loss(
        self, code: str, entry_price: float, current_price: float
    ) -> RiskCheckResult:
        """单票止损检查。"""
        if entry_price <= 0 or current_price <= 0:
            return RiskCheckResult(RiskAction.NORMAL, "price_invalid")

        pnl = current_price / entry_price - 1.0

        if pnl <= self.cfg.max_single_stock_loss_pct:
            msg = (
                f"[{code}] 浮亏 {pnl:.2%} 超过止损阈值 "
                f"{self.cfg.max_single_stock_loss_pct:.2%}"
            )
            logger.warning("⚠️ " + msg)
            return RiskCheckResult(
                RiskAction.CLOSE_POSITION, msg,
                {"code": code, "pnl_pct": pnl, "threshold": self.cfg.max_single_stock_loss_pct},
            )

        return RiskCheckResult(RiskAction.NORMAL)

    # ------------------------------------------------------------------
    # 面值退市风险
    # ------------------------------------------------------------------
    def check_delisting_risk(
        self,
        code: str,
        close_price: float,
        avg_close_5d: float | None = None,
        name: str = "",
    ) -> RiskCheckResult:
        """
        面值退市风险检查。

        2025-2026 年 A 股面值退市已成为主要退市通道。
        收盘价低于 1 元连续 20 个交易日即触发退市。
        我们在 close < min_close_price 时就提前规避。
        """
        if close_price < self.cfg.min_close_price:
            msg = f"[{code}] {name} 收盘价 {close_price:.2f} 低于面值阈值 {self.cfg.min_close_price:.2f}"
            logger.info("🛡 " + msg)
            return RiskCheckResult(
                RiskAction.SKIP_ENTRY, msg,
                {"code": code, "close_price": close_price, "type": "low_price"},
            )

        if avg_close_5d is not None and avg_close_5d < self.cfg.min_avg_close_price_5d:
            msg = (
                f"[{code}] {name} 5日均价 {avg_close_5d:.2f} 低于阈值 "
                f"{self.cfg.min_avg_close_price_5d:.2f}"
            )
            logger.info("🛡 " + msg)
            return RiskCheckResult(
                RiskAction.SKIP_ENTRY, msg,
                {"code": code, "avg_close_5d": avg_close_5d, "type": "low_avg_price"},
            )

        return RiskCheckResult(RiskAction.NORMAL)

    # ------------------------------------------------------------------
    # 连续亏损保护
    # ------------------------------------------------------------------
    def update_trade_result(self, is_win: bool) -> None:
        """更新交易结果，追踪连续亏损。"""
        if is_win:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1

    def get_position_scale(self) -> float:
        """
        根据连续亏损情况返回仓位缩放系数 (0, 1]。
        连续亏损 >= max_consecutive_losses 时降仓。
        """
        if self._consecutive_losses >= self.cfg.max_consecutive_losses:
            logger.warning(
                f"⚠️ 连续亏损 {self._consecutive_losses} 笔，"
                f"仓位缩放至 {self.cfg.consecutive_loss_scale:.0%}"
            )
            return self.cfg.consecutive_loss_scale
        return 1.0

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    # ------------------------------------------------------------------
    # 批量过滤
    # ------------------------------------------------------------------
    def filter_candidates(
        self,
        candidates_df: pd.DataFrame,
        *,
        close_col: str = "收盘价",
        code_col: str = "代码",
        name_col: str = "名称",
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        批量过滤候选标的：面值退市 + 低价保护。

        Returns:
            (通过的 DataFrame, 被拦截的 DataFrame)
        """
        if candidates_df.empty:
            return candidates_df.copy(), pd.DataFrame()

        df = candidates_df.copy()
        close = pd.to_numeric(df.get(close_col, pd.Series(dtype=float)), errors="coerce")

        blocked_mask = close < self.cfg.min_close_price
        kept = df[~blocked_mask].copy()
        blocked = df[blocked_mask].copy()

        if not blocked.empty:
            logger.info(f"🛡 面值退市保护拦截 {len(blocked)} 只标的")

        return kept, blocked


# 便于直接 import
__all__ = [
    "RiskAction",
    "IntradayRiskConfig",
    "RiskCheckResult",
    "IntradayRiskMonitor",
]
