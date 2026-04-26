# -*- coding: utf-8 -*-
"""
告警推送模块：支持微信企业号、钉钉、Telegram 推送。

使用方法:
    from utils.alert import AlertManager, AlertLevel

    alert = AlertManager(webhook_url="https://...", alert_type="wechat_work")
    alert.send(AlertLevel.WARN, "数据延迟", "今日数据更新延迟超过30分钟")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """告警级别"""
    INFO = auto()       # 每日正常日志
    WARN = auto()       # 数据覆盖率下降、部分订单未成交
    ERROR = auto()      # 对账差异、连接断开
    CRITICAL = auto()   # 日内回撤触发、系统异常


class AlertManager:
    """统一告警推送管理器"""

    def __init__(
        self,
        webhook_url: str | None = None,
        alert_type: str = "console",  # console / wechat_work / dingtalk / telegram
        *,
        enabled: bool = True,
        min_level: AlertLevel = AlertLevel.INFO,
    ):
        self.webhook_url = webhook_url or os.environ.get("MFTS_ALERT_WEBHOOK", "")
        self.alert_type = str(alert_type or os.environ.get("MFTS_ALERT_TYPE", "console")).strip().lower()
        self.enabled = enabled
        self.min_level = min_level
        self._history: list[dict[str, Any]] = []

    def send(self, level: AlertLevel, title: str, content: str) -> bool:
        """
        发送告警。

        Returns:
            True 如果发送成功（或 console 模式），False 如果失败
        """
        if not self.enabled:
            return True
        if level.value < self.min_level.value:
            return True

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        emoji = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARN: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨",
        }.get(level, "📢")

        full_msg = f"{emoji} [{level.name}] {title}\n{content}\n⏰ {ts}"

        # 记录历史
        self._history.append({
            "timestamp": ts,
            "level": level.name,
            "title": title,
            "content": content,
        })

        # Console 模式（默认）
        if self.alert_type == "console" or not self.webhook_url:
            if level == AlertLevel.CRITICAL:
                logger.critical(full_msg)
            elif level == AlertLevel.ERROR:
                logger.error(full_msg)
            elif level == AlertLevel.WARN:
                logger.warning(full_msg)
            else:
                logger.info(full_msg)
            print(full_msg)
            return True

        # Webhook 推送
        try:
            return self._send_webhook(level, title, content, full_msg)
        except Exception as e:
            logger.error(f"告警推送失败: {e}")
            print(full_msg)  # 回退到 console
            return False

    def _send_webhook(
        self, level: AlertLevel, title: str, content: str, full_msg: str
    ) -> bool:
        """通过 webhook 推送告警"""
        import urllib.request
        import urllib.error

        if self.alert_type == "wechat_work":
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": full_msg,
                },
            }
        elif self.alert_type == "dingtalk":
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"[{level.name}] {title}",
                    "text": full_msg,
                },
            }
        elif self.alert_type == "telegram":
            # Telegram Bot API: webhook_url = https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>
            payload = {
                "text": full_msg,
                "parse_mode": "Markdown",
            }
        else:
            payload = {"text": full_msg}

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                if status == 200:
                    logger.info(f"告警推送成功: [{level.name}] {title}")
                    return True
                else:
                    logger.warning(f"告警推送状态码异常: {status}")
                    return False
        except urllib.error.URLError as e:
            logger.error(f"告警推送网络错误: {e}")
            return False

    def send_daily_summary(
        self,
        nav: float,
        daily_pnl: float,
        daily_pnl_pct: float,
        positions_count: int,
        trade_count: int = 0,
        extra_info: str = "",
    ) -> bool:
        """发送每日运行摘要"""
        content = (
            f"📊 每日运行摘要\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"净值: ¥{nav:,.0f}\n"
            f"日盈亏: ¥{daily_pnl:,.0f} ({daily_pnl_pct:+.2%})\n"
            f"持仓数: {positions_count}\n"
            f"今日交易: {trade_count} 笔\n"
        )
        if extra_info:
            content += f"\n{extra_info}"

        level = AlertLevel.INFO
        if daily_pnl_pct <= -0.03:
            level = AlertLevel.ERROR
        elif daily_pnl_pct <= -0.01:
            level = AlertLevel.WARN

        return self.send(level, "MFTS 每日摘要", content)

    def send_reconciliation_alert(self, summary: str, has_critical: bool) -> bool:
        """发送对账告警"""
        level = AlertLevel.CRITICAL if has_critical else AlertLevel.WARN
        return self.send(level, "仓位对账结果", summary)

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)


def get_default_alert_manager() -> AlertManager:
    """从环境变量创建默认告警管理器"""
    return AlertManager(
        webhook_url=os.environ.get("MFTS_ALERT_WEBHOOK", ""),
        alert_type=os.environ.get("MFTS_ALERT_TYPE", "console"),
        enabled=os.environ.get("MFTS_ALERT_ENABLED", "true").lower() in {"1", "true", "yes"},
    )


__all__ = ["AlertLevel", "AlertManager", "get_default_alert_manager"]
