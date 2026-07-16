#!/usr/bin/env python3
"""
每日风控报告生成脚本。

功能：
1. 组合净值 / 当日 PnL / 累计 PnL
2. 当前持仓行业分布
3. 各持仓浮动盈亏
4. 明日涨跌停信号标记
5. 大盘状态判断
6. 仓位对账（本地 vs 基准）
7. 推送告警摘要

使用方法:
    python scripts/daily_risk_report.py
    python scripts/daily_risk_report.py --state-file output/execution/paper_portfolio_state.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from utils.code_utils import normalize_ts_code, normalize_ts_code_series, limit_ratio_for_stock
from utils.alert import AlertManager, AlertLevel, get_default_alert_manager
from core.risk.intraday_monitor import IntradayRiskMonitor, IntradayRiskConfig
from core.data import AShareMarketDataGateway
from core.risk.pretrade import load_industry_map as load_ods_industry_map

OUTPUT_DIR = Path(BASE_DIR) / "output"
DEFAULT_STATE = OUTPUT_DIR / "execution" / "paper_portfolio_state.json"


def _load_state(state_file: Path) -> dict:
    """加载组合状态。"""
    if not state_file.exists():
        raise FileNotFoundError(f"状态文件不存在: {state_file}")
    return json.loads(state_file.read_text(encoding="utf-8"))


def _load_latest_prices(codes: list[str]) -> dict[str, dict]:
    """Load the latest ODS bar partition for current holdings."""
    gateway = AShareMarketDataGateway()
    sessions = gateway.available_trade_dates()
    if not sessions:
        return {}
    latest_session = sessions[-1]
    df = gateway.load_bars(latest_session, latest_session)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
    df["ts_code"] = normalize_ts_code_series(df["ts_code"])
    df = df[df["ts_code"].isin(codes)].copy()

    latest_date = df["trade_date"].max()
    latest = df[df["trade_date"] == latest_date].copy()

    result = {}
    for _, row in latest.iterrows():
        code = row["ts_code"]
        result[code] = {
            "close": float(row.get("close", 0)),
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "amount": float(row.get("amount", 0)),
            "trade_date": latest_date.strftime("%Y-%m-%d"),
        }
    return result


def _load_industry_map() -> dict[str, str]:
    """Load industry metadata as of the latest shared ODS session."""
    sessions = AShareMarketDataGateway().available_trade_dates()
    return load_ods_industry_map(asof_date=sessions[-1]) if sessions else {}


def generate_report(state_file: Path) -> str:
    """生成风控报告。"""
    state = _load_state(state_file)
    positions = state.get("positions", {})
    cash = float(state.get("cash", 0))
    nav_prev = float(state.get("nav", cash))

    # 加载最新价格
    codes = [normalize_ts_code(k) for k in positions.keys() if normalize_ts_code(k)]
    price_map = _load_latest_prices(codes) if codes else {}
    industry_map = _load_industry_map()

    # 计算持仓明细
    lines = []
    lines.append("=" * 72)
    lines.append("📊 MFTS 每日风控报告")
    lines.append(f"📅 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 72)

    # 1. 组合概览
    total_market_value = 0.0
    position_details = []
    risk_monitor = IntradayRiskMonitor(IntradayRiskConfig())

    for code_raw, pos in positions.items():
        code = normalize_ts_code(code_raw)
        if not code:
            continue
        qty = int(pos.get("qty", 0))
        if qty <= 0:
            continue
        avg_cost = float(pos.get("avg_cost", 0))
        name = str(pos.get("name", code))

        px_data = price_map.get(code, {})
        current_price = float(px_data.get("close", avg_cost))
        market_value = qty * current_price
        total_market_value += market_value

        pnl = (current_price / avg_cost - 1) * 100 if avg_cost > 0 else 0
        pnl_value = (current_price - avg_cost) * qty

        # 面值退市检查
        delist_check = risk_monitor.check_delisting_risk(code, current_price, name=name)

        industry = industry_map.get(code, "未知")

        position_details.append({
            "code": code,
            "name": name,
            "qty": qty,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "market_value": market_value,
            "pnl_pct": pnl,
            "pnl_value": pnl_value,
            "industry": industry,
            "delist_risk": delist_check.action.name != "NORMAL",
            "delist_msg": delist_check.reason,
        })

    nav = cash + total_market_value
    daily_pnl = nav - nav_prev
    daily_pnl_pct = daily_pnl / nav_prev if nav_prev > 0 else 0

    lines.append(f"\n📈 组合概览")
    lines.append(f"  净值:     ¥{nav:>12,.0f}")
    lines.append(f"  现金:     ¥{cash:>12,.0f}")
    lines.append(f"  市值:     ¥{total_market_value:>12,.0f}")
    lines.append(f"  日盈亏:   ¥{daily_pnl:>12,.0f} ({daily_pnl_pct:+.2%})")
    lines.append(f"  持仓数:   {len(position_details)}")

    # 日内回撤检查
    dd_check = risk_monitor.check_portfolio_drawdown(nav, nav_prev)
    if dd_check.action.name != "NORMAL":
        lines.append(f"\n  🚨 风控触发: {dd_check.reason}")

    # 2. 持仓明细
    if position_details:
        lines.append(f"\n📋 持仓明细")
        lines.append(f"  {'代码':<10} {'名称':<8} {'数量':>6} {'成本':>8} {'现价':>8} {'盈亏%':>7} {'盈亏':>10} {'行业':<6} {'风险':>4}")
        lines.append("  " + "-" * 80)
        for p in sorted(position_details, key=lambda x: x["pnl_pct"]):
            risk_flag = "⚠️" if p["delist_risk"] else "  "
            lines.append(
                f"  {p['code']:<10} {p['name']:<8} {p['qty']:>6} "
                f"{p['avg_cost']:>8.2f} {p['current_price']:>8.2f} "
                f"{p['pnl_pct']:>+6.2f}% ¥{p['pnl_value']:>9,.0f} "
                f"{p['industry']:<6} {risk_flag}"
            )

    # 3. 行业分布
    if position_details:
        lines.append(f"\n🏭 行业分布")
        industry_values = {}
        for p in position_details:
            ind = p["industry"]
            industry_values[ind] = industry_values.get(ind, 0) + p["market_value"]
        for ind, val in sorted(industry_values.items(), key=lambda x: -x[1]):
            pct = val / total_market_value * 100 if total_market_value > 0 else 0
            bar = "█" * max(1, int(pct / 2))
            lines.append(f"  {ind:<10} ¥{val:>10,.0f} ({pct:>5.1f}%) {bar}")

    # 4. 风险预警
    risk_alerts = []
    for p in position_details:
        if p["delist_risk"]:
            risk_alerts.append(f"  🛡 [{p['code']}] {p['name']}: {p['delist_msg']}")
        if p["pnl_pct"] <= -7:
            risk_alerts.append(f"  ⚠️ [{p['code']}] {p['name']}: 浮亏 {p['pnl_pct']:.2f}% 超过止损线")

    if risk_alerts:
        lines.append(f"\n⚠️ 风险预警")
        lines.extend(risk_alerts)
    else:
        lines.append(f"\n✅ 无风险预警")

    lines.append("\n" + "=" * 72)

    report = "\n".join(lines)
    return report


def main():
    parser = argparse.ArgumentParser(description="每日风控报告")
    parser.add_argument(
        "--state-file", type=str,
        default=str(DEFAULT_STATE),
        help="组合状态文件路径",
    )
    parser.add_argument("--push-alert", action="store_true", help="推送告警")
    args = parser.parse_args()

    state_file = Path(args.state_file)

    try:
        report = generate_report(state_file)
        print(report)

        # 保存报告
        report_dir = OUTPUT_DIR / "risk_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = report_dir / f"risk_report_{ts}.txt"
        report_file.write_text(report, encoding="utf-8")
        print(f"\n报告已保存: {report_file}")

        # 推送告警
        if args.push_alert:
            alert = get_default_alert_manager()
            state = _load_state(state_file)
            nav = float(state.get("nav", 0))
            nav_prev = float(state.get("nav_pre", nav))
            daily_pnl = nav - nav_prev
            daily_pnl_pct = daily_pnl / nav_prev if nav_prev > 0 else 0
            positions = state.get("positions", {})
            pos_count = sum(1 for v in positions.values() if int(v.get("qty", 0)) > 0)
            alert.send_daily_summary(
                nav=nav,
                daily_pnl=daily_pnl,
                daily_pnl_pct=daily_pnl_pct,
                positions_count=pos_count,
            )

    except FileNotFoundError as e:
        print(f"❌ {e}")
        print("请确保已运行 paper trade 或指定正确的 state-file 路径")
        sys.exit(1)


if __name__ == "__main__":
    main()
