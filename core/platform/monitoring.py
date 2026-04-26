"""平台观测、告警与健康评估。"""

from __future__ import annotations

from dataclasses import dataclass

from utils.alert import AlertLevel, AlertManager


@dataclass
class PlatformHealthSnapshot:
    data_fresh: bool = True
    data_coverage_pct: float = 100.0
    risk_block_rate_pct: float = 0.0
    order_block_rate_pct: float = 0.0
    nav_drawdown_pct: float = 0.0
    exec_diff_pct: float = 0.0


@dataclass
class PlatformWarning:
    level: AlertLevel
    title: str
    content: str


def evaluate_health_warnings(snapshot: PlatformHealthSnapshot) -> list[PlatformWarning]:
    warnings: list[PlatformWarning] = []
    if not snapshot.data_fresh:
        warnings.append(PlatformWarning(AlertLevel.ERROR, "数据更新异常", "主数据或元数据已超过允许新鲜度"))
    if snapshot.data_coverage_pct < 80.0:
        warnings.append(
            PlatformWarning(
                AlertLevel.CRITICAL,
                "行业覆盖率过低",
                f"当前覆盖率 {snapshot.data_coverage_pct:.2f}%，低于平台要求",
            )
        )
    if snapshot.risk_block_rate_pct >= 35.0:
        warnings.append(
            PlatformWarning(AlertLevel.WARN, "风控拒单率偏高", f"当前风控拒单率 {snapshot.risk_block_rate_pct:.2f}%")
        )
    if snapshot.order_block_rate_pct >= 20.0:
        warnings.append(
            PlatformWarning(AlertLevel.WARN, "订单阻塞率偏高", f"当前订单阻塞率 {snapshot.order_block_rate_pct:.2f}%")
        )
    if snapshot.nav_drawdown_pct <= -0.05:
        warnings.append(
            PlatformWarning(AlertLevel.ERROR, "净值异常回撤", f"当前回撤 {snapshot.nav_drawdown_pct:.2%}")
        )
    if snapshot.exec_diff_pct >= 0.03:
        warnings.append(
            PlatformWarning(AlertLevel.ERROR, "执行回测偏差偏大", f"当前偏差 {snapshot.exec_diff_pct:.2%}")
        )
    return warnings


class PlatformMonitor:
    """面向编排与平台服务的统一监控入口。"""

    def __init__(self, alert_manager: AlertManager | None = None) -> None:
        self.alert_manager = alert_manager or AlertManager()

    def emit_warnings(self, warnings: list[PlatformWarning]) -> int:
        sent = 0
        for warning in warnings:
            if self.alert_manager.send(warning.level, warning.title, warning.content):
                sent += 1
        return sent

    def emit_pipeline_result(self, run_id: str, ok: bool, step_results: dict[str, object]) -> bool:
        level = AlertLevel.INFO if ok else AlertLevel.ERROR
        title = "量化平台主流程结果"
        content = f"run_id={run_id}\nstatus={'ok' if ok else 'failed'}\nsteps={step_results}"
        return self.alert_manager.send(level, title, content)
