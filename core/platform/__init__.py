"""平台核心骨架模块。"""

from core.platform.execution_lifecycle import (
    OrderEvent,
    OrderEventType,
    OrderLifecycleState,
    OrderStatus,
    apply_order_event,
)
from core.platform.context import DataContext, ProfileContext, RunContext
from core.platform.experiment_registry import (
    build_experiment_record,
    load_experiment_registry,
    register_experiment,
)
from core.platform.events import PlatformEvent
from core.platform.monitoring import (
    PlatformHealthSnapshot,
    PlatformMonitor,
    PlatformWarning,
    evaluate_health_warnings,
)
from core.platform.portfolio_engine import (
    PortfolioConstraints,
    PortfolioDecision,
    build_portfolio_decision,
)
from core.platform.profiling import ProfileResult, profile_call
from core.platform.risk_engine import evaluate_pretrade_portfolio
from core.platform.run_manifest import (
    build_run_manifest,
    finalize_run_manifest,
    load_latest_run_manifest,
    write_run_manifest,
)
from core.platform.security_governance import (
    build_config_fingerprint,
    load_security_config,
    record_config_change,
)

__all__ = [
    "OrderEvent",
    "OrderEventType",
    "OrderLifecycleState",
    "OrderStatus",
    "apply_order_event",
    "DataContext",
    "ProfileContext",
    "RunContext",
    "build_experiment_record",
    "load_experiment_registry",
    "register_experiment",
    "PlatformEvent",
    "PlatformHealthSnapshot",
    "PlatformMonitor",
    "PlatformWarning",
    "evaluate_health_warnings",
    "PortfolioConstraints",
    "PortfolioDecision",
    "build_portfolio_decision",
    "ProfileResult",
    "profile_call",
    "evaluate_pretrade_portfolio",
    "build_run_manifest",
    "finalize_run_manifest",
    "load_latest_run_manifest",
    "write_run_manifest",
    "build_config_fingerprint",
    "load_security_config",
    "record_config_change",
]
