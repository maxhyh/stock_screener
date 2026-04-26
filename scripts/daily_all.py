#!/usr/bin/env python3
"""
MFTS 综合编排脚本（支持 latest / catchup / verify-only）

使用方法:
    python scripts/daily_all.py
    python scripts/daily_all.py --mode latest
    python scripts/daily_all.py --mode catchup --catchup-days 10
    python scripts/daily_all.py --mode verify-only
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# 项目路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config.settings import resolve_default_label_horizon
from core.platform import (
    PlatformHealthSnapshot,
    PlatformMonitor,
    build_config_fingerprint,
    build_run_manifest,
    finalize_run_manifest,
    evaluate_health_warnings,
    load_security_config,
    write_run_manifest,
)
from utils.output_paths import ensure_output_dirs, get_output_dirs, list_dual
from utils.trade_calendar import nearest_trade_day_on_or_before, previous_trade_day, trade_dates_between

OUTPUT_DIR = Path(BASE_DIR) / "output"
STATE_FILE = OUTPUT_DIR / "pipeline_state.json"
DATA_FILE = Path(BASE_DIR) / "data" / "daily_all_5y.parquet"

# Python 解释器：优先环境变量，默认当前解释器
VENV_PYTHON = os.environ.get("VENV_PYTHON") or sys.executable
if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = sys.executable


def log(msg):
    """带时间戳日志。"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")


def run_script(
    script_path: str,
    description: str = "",
    script_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> bool:
    """运行子脚本并返回是否成功。"""
    if not os.path.exists(script_path):
        log(f"❌ 脚本不存在: {script_path}")
        return False

    cmd = [VENV_PYTHON, script_path]
    if script_args:
        cmd.extend(script_args)

    log(f"▶️ 开始: {description or script_path}")
    start_time = datetime.now()
    try:
        env = os.environ.copy()
        if extra_env:
            env.update({k: str(v) for k, v in extra_env.items()})
        result = subprocess.run(cmd, cwd=BASE_DIR, env=env)
        elapsed = (datetime.now() - start_time).total_seconds()
        if result.returncode == 0:
            log(f"✅ 完成: {description} (耗时 {elapsed:.1f}秒)")
            gc.collect()
            return True
        log(f"❌ 失败: {description} (返回码: {result.returncode}, 耗时 {elapsed:.1f}秒)")
        gc.collect()
        return False
    except KeyboardInterrupt:
        log(f"⚠️ 用户中断: {description}")
        raise
    except Exception as e:
        log(f"❌ 异常: {description} - {e}")
        gc.collect()
        return False


def get_auto_target_date() -> str:
    """自动目标日期（收盘前取上一交易日，周末回退到周五）。"""
    now = datetime.now()
    cutoff_hour = int(os.environ.get("MFTS_AUTO_TARGET_CUTOFF_HOUR", "18"))
    target_day = now.date()
    # A股当日数据通常在收盘后再稳定可用，收盘前默认使用上一交易日。
    if int(now.hour) < cutoff_hour:
        target_day = previous_trade_day(target_day, parquet_file=DATA_FILE)
    else:
        target_day = nearest_trade_day_on_or_before(target_day, parquet_file=DATA_FILE)
    return target_day.strftime("%Y%m%d")


def load_latest_data_date() -> str | None:
    """读取当前主数据最新交易日（YYYYMMDD）。"""
    if not DATA_FILE.exists():
        return None
    df = pd.read_parquet(DATA_FILE, columns=["trade_date"])
    if df.empty:
        return None
    d = pd.to_datetime(df["trade_date"].astype(str), errors="coerce").dropna()
    if d.empty:
        return None
    return d.max().strftime("%Y%m%d")


def business_dates_between(start_yyyymmdd: str, end_yyyymmdd: str) -> list[str]:
    """返回 (start, end] 区间的工作日日期（YYYYMMDD）。"""
    return trade_dates_between(start_yyyymmdd, end_yyyymmdd, parquet_file=DATA_FILE)


def load_trade_calendar_info() -> tuple[list[str], dict[str, int]]:
    """读取交易日与每日覆盖数。"""
    if not DATA_FILE.exists():
        return [], {}
    df = pd.read_parquet(DATA_FILE, columns=["trade_date", "ts_code"])
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="coerce")
    df = df.dropna(subset=["trade_date"])
    df["date_str"] = df["trade_date"].dt.strftime("%Y%m%d")
    dates = sorted(df["date_str"].unique().tolist())
    counts = df.groupby("date_str")["ts_code"].nunique().to_dict()
    return dates, counts


def load_industry_coverage() -> dict[str, object]:
    """
    读取元数据行业覆盖率。
    返回示例:
    {
      "file": ".../data/stock_info.csv",
      "rows": 5500,
      "industry_nonempty": 4400,
      "coverage_pct": 80.0,
      "ok": True
    }
    """
    data_dir = Path(BASE_DIR) / "data"
    candidates = [data_dir / "stock_info.csv", data_dir / "stock_metadata.csv", data_dir / "stock_basic.csv"]
    for fp in candidates:
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp, dtype=str)
        except Exception:
            continue
        if df.empty:
            continue
        ind_col = "industry" if "industry" in df.columns else ("行业" if "行业" in df.columns else None)
        if ind_col is None:
            continue
        ind = df[ind_col].where(~df[ind_col].isna(), "").astype(str).str.strip()
        ind = ind.replace({"nan": "", "None": "", "NONE": ""})
        nonempty = int((ind != "").sum())
        rows = int(len(df))
        cov = float(nonempty / max(rows, 1) * 100.0)
        return {
            "file": str(fp),
            "rows": rows,
            "industry_nonempty": nonempty,
            "coverage_pct": cov,
            "ok": True,
        }
    return {
        "file": "",
        "rows": 0,
        "industry_nonempty": 0,
        "coverage_pct": 0.0,
        "ok": False,
    }


def list_stage_dates(prefix: str, subdir_key: str) -> set[str]:
    """读取阶段产物已存在的日期集合。"""
    ensure_output_dirs(OUTPUT_DIR)
    dirs = get_output_dirs(OUTPUT_DIR)
    files = list_dual([f"{prefix}_*.csv"], dirs[subdir_key], dirs["base"])
    out = set()
    pat = re.compile(rf"{prefix}_(\d{{8}})\.csv$")
    for p in files:
        m = pat.match(p.name)
        if m:
            out.add(m.group(1))
    return out


def calc_missing_dates(trade_dates: list[str], existing: set[str], latest_date: str, catchup_days: int) -> list[str]:
    """
    计算补齐日期：
    - 仅在最近 catchup_days 个交易日窗口内补齐
    - 只补 <= latest_date 的交易日
    """
    window = trade_dates[-catchup_days:] if catchup_days > 0 else trade_dates
    return [d for d in window if d <= latest_date and d not in existing]


def calc_rebuild_dates(trade_dates: list[str], latest_date: str, rebuild_days: int) -> list[str]:
    """计算重算日期窗口（忽略已有文件）。"""
    if rebuild_days <= 0:
        return []
    window = trade_dates[-rebuild_days:]
    return [d for d in window if d <= latest_date]


def filter_dates_by_coverage(
    targets: list[str],
    trade_counts: dict[str, int],
    min_stocks: int,
) -> tuple[list[str], list[str]]:
    """
    按当日覆盖股票数过滤目标日期。
    返回 (保留日期, 跳过日期)。
    """
    if min_stocks <= 0:
        return targets, []
    keep = [d for d in targets if trade_counts.get(d, 0) >= min_stocks]
    skipped = [d for d in targets if d not in keep]
    return keep, skipped


def auto_ml_lookback_days(rebuild_days: int) -> int:
    """
    自动计算 ML 回看窗口，避免 rebuild 场景因窗口不足导致指标为空。
    经验值：回看窗口 >= 重算窗口 + 220（日历日缓冲，覆盖 MA120/滚动指标清洗）。
    """
    env_default = int(os.environ.get("MFTS_ML_LOOKBACK_DAYS", "450"))
    if rebuild_days <= 0:
        return env_default
    return max(env_default, rebuild_days + 220)


def calc_verify_targets(
    trade_dates: list[str],
    trade_counts: dict[str, int],
    ml_dates: set[str],
    verify_dates: set[str],
    mode: str,
    catchup_days: int,
    min_verify_stocks: int,
    label_mode: str,
    label_horizon: int,
) -> list[str]:
    """
    计算待验证推荐日（pred_date）：
    - pred_date 必须有下一交易日，才能做 T+1
    - 默认不重复验证已存在 verification 文件日期
    """
    if len(trade_dates) < 2:
        return []

    mode_norm = str(label_mode or "open_to_open").strip().lower()
    horizon = max(1, int(label_horizon))
    if mode_norm == "open_to_open_t2":
        mode_norm = "open_to_open"
        horizon = 1
    required_future_days = horizon + 1 if mode_norm == "open_to_open" else 1

    valid_pred_dates = []
    trade_set = set(trade_dates)
    for i in range(len(trade_dates) - 1):
        pred = trade_dates[i]
        nxt = trade_dates[i + 1]
        # open_to_open 需要 pred 后至少 (horizon+1) 个交易日，避免“最近日必失败”
        if (len(trade_dates) - i - 1) < required_future_days:
            continue
        verify_day = trade_dates[i + required_future_days]
        nxt_coverage = trade_counts.get(nxt, 0)
        verify_coverage = trade_counts.get(verify_day, 0)
        if (
            pred in ml_dates
            and pred not in verify_dates
            and nxt in trade_set
            and nxt_coverage >= min_verify_stocks
            and verify_coverage >= min_verify_stocks
        ):
            valid_pred_dates.append(pred)

    if mode == "latest":
        return valid_pred_dates[-1:] if valid_pred_dates else []

    if mode == "catchup":
        window = set(trade_dates[-catchup_days:] if catchup_days > 0 else trade_dates)
        return [d for d in valid_pred_dates if d in window]

    # verify-only 默认走 catchup 窗口
    window = set(trade_dates[-catchup_days:] if catchup_days > 0 else trade_dates)
    return [d for d in valid_pred_dates if d in window]


def calc_verify_targets_for_rebuild(
    trade_dates: list[str],
    trade_counts: dict[str, int],
    ml_dates: set[str],
    rebuild_days: int,
    min_verify_stocks: int,
    mode: str,
    label_mode: str,
    label_horizon: int,
) -> list[str]:
    """
    重算模式下的验证目标：
    - 仅在最近 rebuild_days 窗口内
    - 不考虑 verification 既有产物，始终重算
    - pred_date 的下一交易日覆盖数需达标
    """
    if len(trade_dates) < 2 or rebuild_days <= 0:
        return []

    mode_norm = str(label_mode or "open_to_open").strip().lower()
    horizon = max(1, int(label_horizon))
    if mode_norm == "open_to_open_t2":
        mode_norm = "open_to_open"
        horizon = 1
    required_future_days = horizon + 1 if mode_norm == "open_to_open" else 1

    window = set(trade_dates[-rebuild_days:])
    valid_pred_dates: list[str] = []
    for i in range(len(trade_dates) - 1):
        pred = trade_dates[i]
        nxt = trade_dates[i + 1]
        if pred not in window:
            continue
        if (len(trade_dates) - i - 1) < required_future_days:
            continue
        verify_day = trade_dates[i + required_future_days]
        if (
            pred in ml_dates
            and trade_counts.get(nxt, 0) >= min_verify_stocks
            and trade_counts.get(verify_day, 0) >= min_verify_stocks
        ):
            valid_pred_dates.append(pred)

    if mode == "latest":
        return valid_pred_dates[-1:] if valid_pred_dates else []
    return valid_pred_dates


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"runs": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"runs": []}


def save_state(run_record: dict) -> None:
    state = load_state()
    state.setdefault("runs", []).append(run_record)
    # 仅保留最近 200 次记录
    state["runs"] = state["runs"][-200:]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def summarize(results: dict[str, bool]) -> bool:
    print("=" * 70)
    log("日更新完成总结")
    print("=" * 70)
    for step, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        log(f"  {step}: {status}")
    all_success = all(results.values())
    if all_success:
        log("🎉 所有任务执行成功!")
    else:
        log("⚠️ 部分任务失败，请检查日志")
    log(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    return all_success


def main() -> bool:
    parser = argparse.ArgumentParser(description="MFTS 综合日更新")
    parser.add_argument(
        "--mode",
        choices=["latest", "catchup", "verify-only"],
        default="catchup",
        help="运行模式: latest(只跑最新) / catchup(补齐缺口) / verify-only(仅验证)",
    )
    parser.add_argument(
        "--catchup-days",
        type=int,
        default=int(os.environ.get("MFTS_CATCHUP_DAYS", "10")),
        help="补齐窗口交易日数量（默认10）",
    )
    parser.add_argument(
        "--verify-min-stocks",
        type=int,
        default=int(os.environ.get("MFTS_VERIFY_MIN_STOCKS", "3000")),
        help="验证交易日最小覆盖股票数（默认3000）",
    )
    parser.add_argument(
        "--verify-strict",
        action="store_true",
        help="验证严格模式：无可验证样本时按失败处理（默认跳过不失败）",
    )
    parser.add_argument(
        "--stage-min-stocks",
        type=int,
        default=int(os.environ.get("MFTS_STAGE_MIN_STOCKS", "3000")),
        help="扫描/ML 阶段最小覆盖股票数（默认3000，<=0表示关闭）",
    )
    parser.add_argument(
        "--rebuild-days",
        type=int,
        default=int(os.environ.get("MFTS_REBUILD_DAYS", "0")),
        help="重算最近N个交易日（>0时覆盖已有扫描/ML/验证结果）",
    )
    parser.add_argument(
        "--with-p1",
        action="store_true",
        help="追加执行 P1 平台化分析（风险暴露/归因/容量报告）",
    )
    parser.add_argument(
        "--with-p2",
        action="store_true",
        help="追加执行 P2 纸面 OMS（订单/成交/审计日志）",
    )
    parser.add_argument(
        "--p1-capital-base",
        type=float,
        default=float(os.environ.get("MFTS_CAPITAL_BASE", "5000000")),
        help="P1 容量评估资金规模（元）",
    )
    parser.add_argument(
        "--p1-adv-participation",
        type=float,
        default=float(os.environ.get("MFTS_ADV_PARTICIPATION", "0.05")),
        help="P1 单票成交额参与率上限(0~1)",
    )
    parser.add_argument(
        "--p2-initial-capital",
        type=float,
        default=float(os.environ.get("MFTS_PAPER_CAPITAL", "1000000")),
        help="P2 纸面账户初始资金（首次生效）",
    )
    parser.add_argument(
        "--p2-top-n",
        type=int,
        default=int(os.environ.get("MFTS_PAPER_TOP_N", "10")),
        help="P2 纸面 OMS 目标持仓数",
    )
    parser.add_argument(
        "--p2-max-single-pos",
        type=float,
        default=float(os.environ.get("MFTS_PAPER_MAX_SINGLE_POS", "0.06")),
        help="P2 单票上限(0~1)",
    )
    parser.add_argument(
        "--p2-default-total-pos",
        type=float,
        default=float(os.environ.get("MFTS_PAPER_DEFAULT_TOTAL_POS", "0.60")),
        help="P2 默认总仓(0~1)",
    )
    parser.add_argument(
        "--p2-state-file",
        type=str,
        default=os.environ.get("MFTS_PAPER_STATE_FILE", ""),
        help="P2 持仓状态文件路径（可选）",
    )
    parser.add_argument(
        "--p2-broker",
        type=str,
        default=os.environ.get("MFTS_EXEC_BROKER", "paper"),
        help="P2 执行通道（当前支持: paper/live）",
    )
    parser.add_argument(
        "--p2-live-mode",
        type=str,
        default=os.environ.get("MFTS_LIVE_MODE", "shadow"),
        help="P2 live 模式（shadow/gateway）",
    )
    parser.add_argument(
        "--p2-disable-pretrade-risk",
        action="store_true",
        help="P2 关闭下单前风控硬门禁",
    )
    parser.add_argument(
        "--p2-risk-blacklist-file",
        type=str,
        default=os.environ.get("MFTS_RISK_BLACKLIST_FILE", ""),
        help="P2 下单前风控黑名单文件路径（可选）",
    )
    parser.add_argument(
        "--p2-risk-max-industry-weight",
        type=float,
        default=float(os.environ.get("MFTS_RISK_MAX_INDUSTRY_WEIGHT", "0.35")),
        help="P2 单行业目标权重上限(0~1)",
    )
    parser.add_argument(
        "--p2-risk-max-adv-participation",
        type=float,
        default=float(os.environ.get("MFTS_RISK_MAX_ADV_PARTICIPATION", "0.05")),
        help="P2 单票成交额参与率上限(0~1)",
    )
    parser.add_argument(
        "--p2-risk-min-price",
        type=float,
        default=float(os.environ.get("MFTS_RISK_MIN_PRICE", "2.0")),
        help="P2 最低开盘价过滤",
    )
    parser.add_argument(
        "--p2-risk-max-style-size-exposure-abs",
        type=float,
        default=float(os.environ.get("MFTS_RISK_MAX_STYLE_SIZE_EXPOSURE_ABS", "0.0")),
        help="P2 风格门禁：Size 暴露绝对值上限（<=0 关闭）",
    )
    parser.add_argument(
        "--p2-risk-max-style-beta-exposure-abs",
        type=float,
        default=float(os.environ.get("MFTS_RISK_MAX_STYLE_BETA_EXPOSURE_ABS", "0.0")),
        help="P2 风格门禁：Beta 暴露绝对值上限（<=0 关闭）",
    )
    parser.add_argument(
        "--p2-risk-max-style-momentum-exposure-abs",
        type=float,
        default=float(os.environ.get("MFTS_RISK_MAX_STYLE_MOMENTUM_EXPOSURE_ABS", "0.0")),
        help="P2 风格门禁：Momentum 暴露绝对值上限（<=0 关闭）",
    )
    parser.add_argument(
        "--p2-risk-max-style-vol-exposure-abs",
        type=float,
        default=float(os.environ.get("MFTS_RISK_MAX_STYLE_VOL_EXPOSURE_ABS", "0.0")),
        help="P2 风格门禁：Vol 暴露绝对值上限（<=0 关闭）",
    )
    parser.add_argument(
        "--p2-risk-style-lb-short",
        type=int,
        default=int(os.environ.get("MFTS_RISK_STYLE_LB_SHORT", "20")),
        help="P2 风格门禁：短窗回看（Momentum/Vol）",
    )
    parser.add_argument(
        "--p2-risk-style-lb-beta",
        type=int,
        default=int(os.environ.get("MFTS_RISK_STYLE_LB_BETA", "60")),
        help="P2 风格门禁：Beta 回看窗口",
    )
    parser.add_argument(
        "--p2-dry-run",
        action="store_true",
        help="P2 仅模拟，不落地持仓状态",
    )
    parser.add_argument(
        "--p2-use-recommendation",
        action="store_true",
        help="P2 自动读取优化推荐参数（覆盖 top_n/max_single_pos）",
    )
    parser.add_argument(
        "--p2-recommend-file",
        type=str,
        default=os.environ.get("MFTS_RECOMMEND_FILE", ""),
        help="P2 推荐参数表路径（可选）",
    )
    parser.add_argument(
        "--p2-recommend-rank",
        type=int,
        default=int(os.environ.get("MFTS_RECOMMEND_RANK", "1")),
        help="P2 推荐参数序号（默认第1名）",
    )
    parser.add_argument(
        "--p2-recommend-keep-signal-position",
        action="store_true",
        help="P2 使用推荐参数时，仍保留信号文件中的建议仓位",
    )
    parser.add_argument(
        "--with-p3-consistency",
        action="store_true",
        help="追加执行 P3 一致性报告（回测 vs 执行）",
    )
    parser.add_argument(
        "--p3-broker",
        type=str,
        default=os.environ.get("MFTS_P3_BROKER", ""),
        help="P3 一致性报告使用的执行通道（默认跟随 p2-broker）",
    )
    parser.add_argument(
        "--p3-fee-bps",
        type=float,
        default=float(os.environ.get("MFTS_P3_FEE_BPS", "8.0")),
        help="P3 成本估算手续费 bps",
    )
    parser.add_argument(
        "--p3-slippage-bps",
        type=float,
        default=float(os.environ.get("MFTS_P3_SLIPPAGE_BPS", "5.0")),
        help="P3 成本估算滑点 bps",
    )
    parser.add_argument(
        "--p3-stamp-tax-bps",
        type=float,
        default=float(os.environ.get("MFTS_P3_STAMP_TAX_BPS", "10.0")),
        help="P3 成本估算印花税 bps",
    )
    parser.add_argument(
        "--p3-max-ret-gap-mae-pct",
        type=float,
        default=float(os.environ.get("MFTS_P3_MAX_RET_GAP_MAE_PCT", "2.0")),
        help="P3 门槛：收益偏差 MAE 上限（%）",
    )
    parser.add_argument(
        "--p3-min-match-coverage-pct",
        type=float,
        default=float(os.environ.get("MFTS_P3_MIN_MATCH_COVERAGE_PCT", "60.0")),
        help="P3 门槛：回测-执行匹配覆盖率下限（%）",
    )
    parser.add_argument(
        "--p3-max-order-block-rate-pct",
        type=float,
        default=float(os.environ.get("MFTS_P3_MAX_ORDER_BLOCK_RATE_PCT", "35.0")),
        help="P3 门槛：订单阻塞率均值上限（%）",
    )
    parser.add_argument(
        "--p3-max-risk-block-rate-pct",
        type=float,
        default=float(os.environ.get("MFTS_P3_MAX_RISK_BLOCK_RATE_PCT", "35.0")),
        help="P3 门槛：风控拦截率均值上限（%）",
    )
    parser.add_argument(
        "--p3-min-matched-rows",
        type=int,
        default=int(os.environ.get("MFTS_P3_MIN_MATCHED_ROWS", "20")),
        help="P3 门槛：最少匹配样本数",
    )
    parser.add_argument(
        "--p3-rate-eval-rows",
        type=int,
        default=int(os.environ.get("MFTS_P3_RATE_EVAL_ROWS", "10")),
        help="P3 门槛计算窗口：订单/风控阻塞率使用最近 N 个匹配样本（0=全部）",
    )
    parser.add_argument(
        "--p3-enforce-thresholds",
        action="store_true",
        default=os.environ.get("MFTS_P3_ENFORCE_THRESHOLDS", "false").lower() in {"1", "true", "yes", "on"},
        help="P3 若一致性门槛不达标则返回失败",
    )
    parser.add_argument(
        "--disable-industry-coverage-gate",
        action="store_true",
        help="关闭行业覆盖率门禁（默认开启）",
    )
    parser.add_argument(
        "--min-industry-coverage-pct",
        type=float,
        default=float(os.environ.get("MFTS_MIN_INDUSTRY_COVERAGE_PCT", "80.0")),
        help="行业覆盖率门禁阈值（默认80）",
    )
    parser.add_argument(
        "--skip-profile-gate",
        action="store_true",
        help="跳过 profile promotion gate 刷新（默认执行）",
    )
    parser.add_argument(
        "--promotion-lookback-months",
        type=int,
        default=int(os.environ.get("MFTS_PROMOTION_LOOKBACK_MONTHS", "10")),
        help="profile gate: rolling compare 回看月数",
    )
    parser.add_argument(
        "--promotion-train-months",
        type=int,
        default=int(os.environ.get("MFTS_PROMOTION_TRAIN_MONTHS", "4")),
        help="profile gate: rolling compare train months",
    )
    parser.add_argument(
        "--promotion-test-months",
        type=int,
        default=int(os.environ.get("MFTS_PROMOTION_TEST_MONTHS", "2")),
        help="profile gate: rolling compare test months",
    )
    parser.add_argument(
        "--promotion-step-months",
        type=int,
        default=int(os.environ.get("MFTS_PROMOTION_STEP_MONTHS", "1")),
        help="profile gate: rolling compare step months",
    )
    parser.add_argument(
        "--promotion-p2-windows",
        type=str,
        default=os.environ.get("MFTS_PROMOTION_P2_WINDOWS", "60,90,120"),
        help="profile gate: P2 replay windows",
    )
    parser.add_argument(
        "--promotion-min-p2-executed-days",
        type=int,
        default=int(os.environ.get("MFTS_MIN_P2_EXECUTED_DAYS", "20")),
        help="profile gate: promotion 所需最少 P2 执行天数",
    )
    parser.add_argument(
        "--promotion-min-promote-margin",
        type=float,
        default=float(os.environ.get("MFTS_MIN_PROMOTE_MARGIN", "1.0")),
        help="profile gate: 候选档超过主档所需的最小 promotion_score 差值",
    )
    args = parser.parse_args()

    # 运行时统一“活跃档位”，用于 ML/验证默认持有期与执行口径对齐。
    active_profile = str(os.environ.get("MFTS_ACTIVE_PROFILE", "")).strip()
    if not active_profile:
        p2_profile = str(os.environ.get("MFTS_P2_PROFILE", "")).strip()
        if p2_profile:
            os.environ["MFTS_ACTIVE_PROFILE"] = p2_profile
            active_profile = p2_profile

    verify_label_mode = str(os.environ.get("MFTS_VERIFY_LABEL_MODE", "open_to_open")).strip()
    verify_label_horizon = int(
        os.environ.get(
            "MFTS_VERIFY_LABEL_HORIZON",
            str(resolve_default_label_horizon(fallback=8)),
        )
    )

    total_steps = 4 + int(args.with_p1) + int(args.with_p2) + int(args.with_p3_consistency) + int(not args.skip_profile_gate)
    step_no = 1

    print("=" * 70)
    print("MFTS 综合日更新")
    print("=" * 70)
    log(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Python: {VENV_PYTHON}")
    log(
        "模式: "
        f"{args.mode}, 补齐窗口: {args.catchup_days} 交易日, "
        f"扫描/ML覆盖门槛: {args.stage_min_stocks}, 验证覆盖门槛: {args.verify_min_stocks}, "
        f"重算窗口: {args.rebuild_days}, "
        f"P1: {args.with_p1}, P2: {args.with_p2}, P3: {args.with_p3_consistency}, "
        f"PromotionGate: {not args.skip_profile_gate}"
    )
    if active_profile:
        log(f"活跃档位: {active_profile}")
    log(f"验证口径: {verify_label_mode}, horizon={verify_label_horizon}")
    print()

    results: dict[str, bool] = {}
    security_cfg = load_security_config()
    manifest = build_run_manifest(
        run_type=f"daily_all_{args.mode}",
        argv=sys.argv,
        params={
            "mode": args.mode,
            "catchup_days": int(args.catchup_days),
            "rebuild_days": int(args.rebuild_days),
            "with_p1": bool(args.with_p1),
            "with_p2": bool(args.with_p2),
            "with_p3_consistency": bool(args.with_p3_consistency),
        },
        tracked_files={
            "daily_data": DATA_FILE,
            "stock_meta": Path(BASE_DIR) / "data" / "stock_info.csv",
            "profile_config": Path(BASE_DIR) / "config" / "quant_live_profiles.json",
        },
        config_fingerprint=build_config_fingerprint(security_cfg),
    )
    manifest_path = write_run_manifest(BASE_DIR, manifest)
    monitor = PlatformMonitor()
    run_record = {
        "run_id": manifest.run_id,
        "platform_manifest": str(manifest_path),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode,
        "catchup_days": args.catchup_days,
        "rebuild_days": args.rebuild_days,
        "active_profile": active_profile,
        "verify_label_mode": verify_label_mode,
        "verify_label_horizon": verify_label_horizon,
        "steps": {},
    }

    def _finish() -> bool:
        ok = bool(all(results.values())) if results else False
        run_record["finished_at"] = datetime.now().isoformat(timespec="seconds")
        save_state(run_record)
        coverage_info = run_record.get("industry_coverage", {}) if isinstance(run_record.get("industry_coverage", {}), dict) else {}
        warnings = evaluate_health_warnings(
            PlatformHealthSnapshot(
                data_fresh=bool(coverage_info.get("ok", True)),
                data_coverage_pct=float(coverage_info.get("coverage_pct", 100.0)),
            )
        )
        finalize_run_manifest(
            manifest_path,
            status="success" if ok else "failed",
            step_results=run_record["steps"],
            notes=[w.title for w in warnings],
        )
        monitor.emit_warnings(warnings)
        monitor.emit_pipeline_result(run_record["run_id"], ok, run_record["steps"])
        return summarize(results)

    industry_gate_enabled = not bool(args.disable_industry_coverage_gate)
    industry_gate_passed = True
    industry_cov_info: dict[str, object] = {}

    # Step 1: 数据更新（verify-only 跳过）
    if args.mode != "verify-only":
        log("=" * 50)
        log(f"Step {step_no}/{total_steps}: 数据更新")
        log("=" * 50)
        incremental_script = os.path.join(BASE_DIR, "scripts", "daily_incremental_update.py")
        if os.path.exists(incremental_script):
            if args.mode == "catchup":
                latest_data_date = load_latest_data_date()
                auto_target = get_auto_target_date()
                if latest_data_date is None:
                    ok = run_script(incremental_script, description="增量数据更新")
                    run_record["data_targets"] = [auto_target]
                else:
                    gap_dates = business_dates_between(latest_data_date, auto_target)
                    # 仅补齐最近窗口，避免一次追太久
                    gap_dates = gap_dates[-args.catchup_days:] if args.catchup_days > 0 else gap_dates
                    if not gap_dates:
                        log(f"ℹ️ 数据已更新到最新目标日 {auto_target}，跳过")
                        ok = True
                        run_record["data_targets"] = []
                    else:
                        log(f"ℹ️ 待补数据日期: {', '.join(gap_dates)}")
                        all_ok = True
                        failed_targets: list[str] = []
                        for d in gap_dates:
                            step_ok = run_script(
                                incremental_script,
                                description=f"增量数据更新 {d}",
                                script_args=["--target-date", d],
                            )
                            all_ok = all_ok and step_ok
                            if not step_ok:
                                failed_targets.append(d)

                        # catchup 场景允许“前序日失败、后续日成功补齐”：
                        # 只要最终主数据已追到目标日，即视为数据更新成功。
                        final_latest = load_latest_data_date()
                        reached_target = bool(final_latest) and int(final_latest) >= int(auto_target)
                        if not all_ok and reached_target:
                            log(
                                "ℹ️ 数据更新存在中间失败，但最终已追到目标日 "
                                f"{auto_target}（latest={final_latest}），继续后续步骤"
                            )
                            ok = True
                        else:
                            ok = all_ok

                        run_record["data_targets"] = gap_dates
                        if failed_targets:
                            run_record["data_failed_targets"] = failed_targets
            elif args.mode == "latest":
                auto_target = get_auto_target_date()
                latest_data_date = load_latest_data_date()
                if latest_data_date and int(latest_data_date) >= int(auto_target):
                    log(
                        "ℹ️ 主数据已覆盖目标日，跳过增量更新: "
                        f"latest={latest_data_date}, target={auto_target}"
                    )
                    ok = True
                    run_record["data_targets"] = []
                else:
                    ok = run_script(
                        incremental_script,
                        description=f"增量数据更新 {auto_target}",
                        script_args=["--target-date", auto_target],
                    )
                    run_record["data_targets"] = [auto_target]
            else:
                ok = run_script(incremental_script, description="增量数据更新")
                run_record["data_targets"] = []
        else:
            full_script = os.path.join(BASE_DIR, "data", "download_5y_data.py")
            log("⚠️ 增量脚本不存在，回退全量下载")
            ok = run_script(full_script, description="全量数据下载")
            run_record["data_targets"] = []
        results["data_update"] = ok
        run_record["steps"]["data_update"] = ok
        print()
        if not ok:
            log("⛔ 数据更新失败，停止后续步骤")
            results.setdefault("mfts_scan", False)
            results.setdefault("ml_select", False)
            results.setdefault("verify", False)
            run_record["steps"].setdefault("mfts_scan", False)
            run_record["steps"].setdefault("ml_select", False)
            run_record["steps"].setdefault("verify", False)
            return _finish()
        step_no += 1
    else:
        results["data_update"] = True
        run_record["steps"]["data_update"] = True
        step_no += 1

    trade_dates, trade_counts = load_trade_calendar_info()
    if not trade_dates:
        log("❌ 无可用交易日数据，终止")
        results["mfts_scan"] = False
        results["ml_select"] = False
        results["verify"] = False
        run_record["steps"]["mfts_scan"] = False
        run_record["steps"]["ml_select"] = False
        run_record["steps"]["verify"] = False
        return _finish()

    latest_trade = trade_dates[-1]
    run_record["latest_trade_date"] = latest_trade

    # 行业覆盖率门禁（仅对 P2/P3 生效）
    if industry_gate_enabled and (args.with_p2 or args.with_p3_consistency):
        industry_cov_info = load_industry_coverage()
        run_record["industry_coverage"] = industry_cov_info
        cov = float(industry_cov_info.get("coverage_pct", 0.0))
        thr = max(0.0, float(args.min_industry_coverage_pct))
        if (not bool(industry_cov_info.get("ok", False))) or cov < thr:
            industry_gate_passed = False
            log(
                "⛔ 行业覆盖率门禁未通过: "
                f"coverage={cov:.2f}% < threshold={thr:.2f}% | file={industry_cov_info.get('file', '')}"
            )
            log("⛔ 将阻断 P2 / P3 步骤，避免在失真行业风控下继续执行。")
        else:
            log(
                "✅ 行业覆盖率门禁通过: "
                f"coverage={cov:.2f}% >= threshold={thr:.2f}% | file={industry_cov_info.get('file', '')}"
            )
    else:
        run_record["industry_coverage"] = {
            "enabled": industry_gate_enabled,
            "skipped": True,
        }

    # Step 2: MFTS 扫描（verify-only 跳过）
    if args.mode != "verify-only":
        log("=" * 50)
        log(f"Step {step_no}/{total_steps}: MFTS 扫描")
        log("=" * 50)
        scan_script = os.path.join(BASE_DIR, "core", "mfts_screener.py")
        scan_existing = list_stage_dates("mfts_scan", "scan")
        if args.rebuild_days > 0:
            scan_targets = calc_rebuild_dates(trade_dates, latest_trade, args.rebuild_days)
            log(f"ℹ️ 扫描重算模式：最近 {args.rebuild_days} 个交易日")
        elif args.mode == "latest":
            scan_targets = [latest_trade]
        else:
            scan_targets = calc_missing_dates(trade_dates, scan_existing, latest_trade, args.catchup_days)
        scan_targets, scan_skipped = filter_dates_by_coverage(scan_targets, trade_counts, args.stage_min_stocks)
        if scan_skipped:
            log(
                "ℹ️ 扫描跳过低覆盖日期: "
                f"{', '.join(scan_skipped)} (阈值 {args.stage_min_stocks})"
            )
            run_record["scan_skipped_low_coverage"] = scan_skipped
        if not scan_targets:
            log("ℹ️ 扫描结果已齐全，跳过")
            results["mfts_scan"] = True
            run_record["scan_targets"] = []
        else:
            log(f"ℹ️ 待补扫描日期: {', '.join(scan_targets)}")
            all_ok = True
            for d in scan_targets:
                ok = run_script(scan_script, description=f"MFTS 扫描 {d}", script_args=["--date", d])
                all_ok = all_ok and ok
            results["mfts_scan"] = all_ok
            run_record["scan_targets"] = scan_targets
        run_record["steps"]["mfts_scan"] = results["mfts_scan"]
        print()
        if not results["mfts_scan"]:
            log("⛔ MFTS 扫描失败，停止后续步骤")
            results.setdefault("ml_select", False)
            results.setdefault("verify", False)
            run_record["steps"].setdefault("ml_select", False)
            run_record["steps"].setdefault("verify", False)
            return _finish()
        step_no += 1
    else:
        results["mfts_scan"] = True
        run_record["steps"]["mfts_scan"] = True
        step_no += 1

    # Step 3: ML 选股（verify-only 跳过）
    if args.mode != "verify-only":
        log("=" * 50)
        log(f"Step {step_no}/{total_steps}: ML 选股")
        log("=" * 50)
        ml_script = os.path.join(BASE_DIR, "scripts", "daily_ml_select.py")
        ml_lookback = auto_ml_lookback_days(args.rebuild_days)
        ml_forward = int(os.environ.get("MFTS_ML_FORWARD_BUFFER_DAYS", "2"))
        ml_env = {
            "MFTS_ML_LOOKBACK_DAYS": str(ml_lookback),
            "MFTS_ML_FORWARD_BUFFER_DAYS": str(ml_forward),
            # 信号端前置风控：默认与 P2 保持同一套阈值，减少“信号可选、执行被拦”的口径漂移。
            "MFTS_SIGNAL_PRETRADE_GATE": "false" if args.p2_disable_pretrade_risk else "true",
            "MFTS_SIGNAL_PRETRADE_CAPITAL_BASE": str(max(100000.0, float(args.p2_initial_capital))),
            "MFTS_RISK_MAX_INDUSTRY_WEIGHT": str(min(max(float(args.p2_risk_max_industry_weight), 0.05), 1.0)),
            "MFTS_RISK_MAX_ADV_PARTICIPATION": str(min(max(float(args.p2_risk_max_adv_participation), 0.001), 0.50)),
            "MFTS_RISK_MIN_PRICE": str(max(0.0, float(args.p2_risk_min_price))),
            "MFTS_RISK_MAX_STYLE_SIZE_EXPOSURE_ABS": str(max(0.0, float(args.p2_risk_max_style_size_exposure_abs))),
            "MFTS_RISK_MAX_STYLE_BETA_EXPOSURE_ABS": str(max(0.0, float(args.p2_risk_max_style_beta_exposure_abs))),
            "MFTS_RISK_MAX_STYLE_MOMENTUM_EXPOSURE_ABS": str(max(0.0, float(args.p2_risk_max_style_momentum_exposure_abs))),
            "MFTS_RISK_MAX_STYLE_VOL_EXPOSURE_ABS": str(max(0.0, float(args.p2_risk_max_style_vol_exposure_abs))),
            "MFTS_RISK_STYLE_LB_SHORT": str(max(5, int(args.p2_risk_style_lb_short))),
            "MFTS_RISK_STYLE_LB_BETA": str(max(10, int(args.p2_risk_style_lb_beta))),
        }
        if args.p2_risk_blacklist_file:
            ml_env["MFTS_RISK_BLACKLIST_FILE"] = str(args.p2_risk_blacklist_file)
        log(
            "ℹ️ ML 自动窗口: "
            f"MFTS_ML_LOOKBACK_DAYS={ml_lookback}, "
            f"MFTS_ML_FORWARD_BUFFER_DAYS={ml_forward}"
        )
        ml_existing = list_stage_dates("daily", "daily")
        if args.rebuild_days > 0:
            ml_targets = calc_rebuild_dates(trade_dates, latest_trade, args.rebuild_days)
            log(f"ℹ️ ML 重算模式：最近 {args.rebuild_days} 个交易日")
        elif args.mode == "latest":
            ml_targets = [latest_trade]
        else:
            ml_targets = calc_missing_dates(trade_dates, ml_existing, latest_trade, args.catchup_days)
        ml_targets, ml_skipped = filter_dates_by_coverage(ml_targets, trade_counts, args.stage_min_stocks)
        if ml_skipped:
            log(
                "ℹ️ ML 跳过低覆盖日期: "
                f"{', '.join(ml_skipped)} (阈值 {args.stage_min_stocks})"
            )
            run_record["ml_skipped_low_coverage"] = ml_skipped
        if not ml_targets:
            log("ℹ️ ML 推荐已齐全，跳过")
            results["ml_select"] = True
            run_record["ml_targets"] = []
        else:
            log(f"ℹ️ 待补 ML 日期: {', '.join(ml_targets)}")
            all_ok = True
            for d in ml_targets:
                ok = run_script(
                    ml_script,
                    description=f"ML 选股 {d}",
                    script_args=["--date", d],
                    extra_env=ml_env,
                )
                all_ok = all_ok and ok
            results["ml_select"] = all_ok
            run_record["ml_targets"] = ml_targets
        run_record["steps"]["ml_select"] = results["ml_select"]
        print()
        if not results["ml_select"]:
            log("⛔ ML 选股失败，停止后续步骤")
            results.setdefault("verify", False)
            run_record["steps"].setdefault("verify", False)
            return _finish()
        step_no += 1
    else:
        results["ml_select"] = True
        run_record["steps"]["ml_select"] = True
        step_no += 1

    # Step 4: 验证（T+1，按交易日）
    log("=" * 50)
    log(f"Step {step_no}/{total_steps}: 胜率验证")
    log("=" * 50)
    verify_script = os.path.join(BASE_DIR, "scripts", "daily_verify.py")
    if not os.path.exists(verify_script):
        log("⚠️ 验证脚本不存在，跳过")
        results["verify"] = True
        run_record["verify_targets"] = []
    else:
        ml_dates = list_stage_dates("daily", "daily")
        if args.rebuild_days > 0:
            verify_targets = calc_verify_targets_for_rebuild(
                trade_dates=trade_dates,
                trade_counts=trade_counts,
                ml_dates=ml_dates,
                rebuild_days=args.rebuild_days,
                min_verify_stocks=args.verify_min_stocks,
                mode=args.mode,
                label_mode=verify_label_mode,
                label_horizon=verify_label_horizon,
            )
            log(f"ℹ️ 验证重算模式：最近 {args.rebuild_days} 个交易日")
        else:
            verify_dates = list_stage_dates("verification", "verify")
            verify_targets = calc_verify_targets(
                trade_dates,
                trade_counts,
                ml_dates,
                verify_dates,
                args.mode,
                args.catchup_days,
                args.verify_min_stocks,
                verify_label_mode,
                verify_label_horizon,
            )
        if not verify_targets:
            log("ℹ️ 无待验证推荐日（或已全部完成）")
            results["verify"] = True
            run_record["verify_targets"] = []
        else:
            log(f"ℹ️ 待验证推荐日期: {', '.join(verify_targets)}")
            all_ok = True
            for d in verify_targets:
                ok = run_script(
                    verify_script,
                    description=f"验证推荐表现 {d}",
                    script_args=[
                        "--date",
                        d,
                        "--label-mode",
                        str(verify_label_mode),
                        "--label-horizon",
                        str(max(1, int(verify_label_horizon))),
                    ],
                    extra_env={"MFTS_VERIFY_STRICT": "true" if args.verify_strict else "false"},
                )
                all_ok = all_ok and ok
            results["verify"] = all_ok
            run_record["verify_targets"] = verify_targets
    run_record["steps"]["verify"] = results["verify"]
    print()
    step_no += 1

    # Step 5: P1 风险/归因/容量分析（可选）
    if args.with_p1:
        log("=" * 50)
        log(f"Step {step_no}/{total_steps}: P1 风险归因分析")
        log("=" * 50)
        p1_script = os.path.join(BASE_DIR, "scripts", "quant_p1_analytics.py")
        p1_args = [
            "--capital-base",
            str(max(100000.0, float(args.p1_capital_base))),
            "--adv-participation",
            str(min(max(float(args.p1_adv_participation), 0.005), 0.50)),
            "--write-latest",
        ]
        if not os.path.exists(p1_script):
            log("⚠️ P1 脚本不存在，跳过")
            results["p1_analytics"] = True
            run_record["p1_skipped"] = "script_not_found"
        else:
            ok = run_script(p1_script, description="P1 风险归因分析", script_args=p1_args)
            results["p1_analytics"] = ok
        run_record["steps"]["p1_analytics"] = results.get("p1_analytics", True)
        print()
        step_no += 1

    # Step 6: P2 纸面 OMS（可选）
    if args.with_p2:
        log("=" * 50)
        log(f"Step {step_no}/{total_steps}: P2 纸面 OMS 执行")
        log("=" * 50)
        if industry_gate_enabled and (not industry_gate_passed):
            log("⛔ P2 被行业覆盖率门禁阻断。")
            results["p2_oms"] = False
            run_record["steps"]["p2_oms"] = False
            run_record["p2_blocked_by_industry_gate"] = True
            print()
            step_no += 1
        else:
            p2_script = os.path.join(BASE_DIR, "scripts", "quant_p2_paper_trade.py")
            p2_args = [
                "--date",
                latest_trade,
                "--broker",
                str(args.p2_broker),
                "--live-mode",
                str(args.p2_live_mode),
                "--initial-capital",
                str(max(100000.0, float(args.p2_initial_capital))),
                "--top-n",
                str(max(1, int(args.p2_top_n))),
                "--max-single-pos",
                str(min(max(float(args.p2_max_single_pos), 0.0), 1.0)),
                "--default-total-pos",
                str(min(max(float(args.p2_default_total_pos), 0.0), 1.0)),
                "--risk-max-industry-weight",
                str(min(max(float(args.p2_risk_max_industry_weight), 0.05), 1.0)),
                "--risk-max-adv-participation",
                str(min(max(float(args.p2_risk_max_adv_participation), 0.001), 0.50)),
                "--risk-min-price",
                str(max(0.0, float(args.p2_risk_min_price))),
                "--risk-max-style-size-exposure-abs",
                str(max(0.0, float(args.p2_risk_max_style_size_exposure_abs))),
                "--risk-max-style-beta-exposure-abs",
                str(max(0.0, float(args.p2_risk_max_style_beta_exposure_abs))),
                "--risk-max-style-momentum-exposure-abs",
                str(max(0.0, float(args.p2_risk_max_style_momentum_exposure_abs))),
                "--risk-max-style-vol-exposure-abs",
                str(max(0.0, float(args.p2_risk_max_style_vol_exposure_abs))),
                "--risk-style-lb-short",
                str(max(5, int(args.p2_risk_style_lb_short))),
                "--risk-style-lb-beta",
                str(max(10, int(args.p2_risk_style_lb_beta))),
                "--write-latest",
            ]
            if args.p2_state_file:
                p2_args.extend(["--state-file", str(args.p2_state_file)])
            if args.p2_disable_pretrade_risk:
                p2_args.append("--disable-pretrade-risk")
            if args.p2_risk_blacklist_file:
                p2_args.extend(["--risk-blacklist-file", str(args.p2_risk_blacklist_file)])
            if args.p2_dry_run:
                p2_args.append("--dry-run")
            if args.p2_use_recommendation:
                p2_args.append("--use-recommendation")
            if args.p2_recommend_file:
                p2_args.extend(["--recommend-file", str(args.p2_recommend_file)])
            if int(args.p2_recommend_rank) > 0:
                p2_args.extend(["--recommend-rank", str(int(args.p2_recommend_rank))])
            if args.p2_recommend_keep_signal_position:
                p2_args.append("--recommend-keep-signal-position")
            if not os.path.exists(p2_script):
                log("⚠️ P2 脚本不存在，跳过")
                results["p2_oms"] = True
                run_record["p2_skipped"] = "script_not_found"
            else:
                ok = run_script(p2_script, description=f"P2 纸面 OMS {latest_trade}", script_args=p2_args)
                results["p2_oms"] = ok
            run_record["steps"]["p2_oms"] = results.get("p2_oms", True)
            print()
            step_no += 1

    # Step 7: P3 回测-执行一致性报告（可选）
    if args.with_p3_consistency:
        log("=" * 50)
        log(f"Step {step_no}/{total_steps}: P3 一致性报告")
        log("=" * 50)
        if industry_gate_enabled and (not industry_gate_passed):
            log("⛔ P3 被行业覆盖率门禁阻断。")
            results["p3_consistency"] = False
            run_record["steps"]["p3_consistency"] = False
            run_record["p3_blocked_by_industry_gate"] = True
            print()
        else:
            p3_script = os.path.join(BASE_DIR, "scripts", "quant_exec_consistency_report.py")
            broker_name = str(args.p3_broker or args.p2_broker or "paper")
            p3_args = [
                "--broker",
                broker_name,
                "--fee-bps",
                str(max(0.0, float(args.p3_fee_bps))),
                "--slippage-bps",
                str(max(0.0, float(args.p3_slippage_bps))),
                "--stamp-tax-bps",
                str(max(0.0, float(args.p3_stamp_tax_bps))),
                "--max-ret-gap-mae-pct",
                str(max(0.0, float(args.p3_max_ret_gap_mae_pct))),
                "--min-match-coverage-pct",
                str(max(0.0, float(args.p3_min_match_coverage_pct))),
                "--max-order-block-rate-pct",
                str(max(0.0, float(args.p3_max_order_block_rate_pct))),
                "--max-risk-block-rate-pct",
                str(max(0.0, float(args.p3_max_risk_block_rate_pct))),
                "--min-matched-rows",
                str(max(0, int(args.p3_min_matched_rows))),
                "--rate-eval-rows",
                str(max(0, int(args.p3_rate_eval_rows))),
                "--write-latest",
            ]
            if args.p3_enforce_thresholds:
                p3_args.append("--enforce-thresholds")
            if not os.path.exists(p3_script):
                log("⚠️ P3 脚本不存在，跳过")
                results["p3_consistency"] = True
                run_record["p3_skipped"] = "script_not_found"
            else:
                ok = run_script(p3_script, description=f"P3 一致性报告 {broker_name}", script_args=p3_args)
                results["p3_consistency"] = ok
            run_record["steps"]["p3_consistency"] = results.get("p3_consistency", True)
            print()
        step_no += 1

    # Step 8: Profile Promotion Gate（默认执行）
    if not args.skip_profile_gate:
        log("=" * 50)
        log(f"Step {step_no}/{total_steps}: Profile Promotion Gate")
        log("=" * 50)
        gate_script = os.path.join(BASE_DIR, "scripts", "quant_refresh_promotion_gate.py")
        gate_args = [
            "--lookback-months",
            str(max(1, int(args.promotion_lookback_months))),
            "--train-months",
            str(max(1, int(args.promotion_train_months))),
            "--test-months",
            str(max(1, int(args.promotion_test_months))),
            "--step-months",
            str(max(1, int(args.promotion_step_months))),
            "--p2-windows",
            str(args.promotion_p2_windows),
            "--min-p2-executed-days",
            str(max(1, int(args.promotion_min_p2_executed_days))),
            "--min-promote-margin",
            str(float(args.promotion_min_promote_margin)),
        ]
        if not os.path.exists(gate_script):
            log("⚠️ Profile gate 脚本不存在，跳过")
            results["profile_gate"] = True
            run_record["profile_gate_skipped"] = "script_not_found"
        else:
            ok = run_script(gate_script, description="Profile Promotion Gate", script_args=gate_args)
            results["profile_gate"] = ok
        run_record["steps"]["profile_gate"] = results.get("profile_gate", True)
        print()

    return _finish()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
