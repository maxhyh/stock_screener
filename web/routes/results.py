"""结果与系统基础路由。"""

from __future__ import annotations

from datetime import datetime, timedelta
import glob
import math
import os
import re
import shutil
import subprocess
import sys

import pandas as pd
import numpy as np
from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory

from web.services import calculate_statistics, get_verification_data, load_platform_overview, load_scan_results
from web.security import require_mutation_auth
from core.data import AShareMarketDataGateway

bp = Blueprint("results", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/scanner")
def scanner_legacy():
    """保留旧入口别名，避免历史书签失效。"""
    return render_template("index.html")


@bp.route("/favicon.ico")
def favicon():
    """处理浏览器默认 favicon 请求，避免 404 噪音。"""
    static_dir = os.path.join(current_app.config["BASE_DIR"], "web", "static")
    icon_path = os.path.join(static_dir, "favicon.ico")
    if os.path.exists(icon_path):
        return send_from_directory(static_dir, "favicon.ico", mimetype="image/x-icon")
    return ("", 204)


def _find_latest_file(candidates: list[str]) -> str | None:
    existing = [p for p in candidates if os.path.exists(p)]
    if not existing:
        return None
    return max(existing, key=os.path.getmtime)


def _find_date_file(output_dir: str, prefix: str, ymd: str) -> str | None:
    # 统一构造（支持新旧目录）
    scan_paths: list[str] = []
    if prefix == "daily":
        scan_paths = [
            os.path.join(output_dir, "daily", f"daily_{ymd}.csv"),
            os.path.join(output_dir, f"daily_{ymd}.csv"),
        ]
    elif prefix == "scan":
        scan_paths = [
            os.path.join(output_dir, "scan", f"mfts_scan_{ymd}.csv"),
            os.path.join(output_dir, f"mfts_scan_{ymd}.csv"),
        ]
    elif prefix == "verify":
        scan_paths = [
            os.path.join(output_dir, "verify", f"verification_{ymd}.csv"),
            os.path.join(output_dir, f"verification_{ymd}.csv"),
        ]
    return _find_latest_file(scan_paths)


def _build_returns_drilldown(trades_df: pd.DataFrame, parquet_file: str) -> dict:
    """
    构建收益率钻取结构：
    - annual: 年收益率
    - monthly: 月收益率
    - daily: 交易日每日收益率（无调仓日为0）
    """
    if trades_df.empty or "exit_date" not in trades_df.columns or "equity" not in trades_df.columns:
        return {"annual": [], "monthly": [], "daily": []}

    tdf = trades_df.copy()
    tdf["exit_date"] = pd.to_datetime(tdf["exit_date"], errors="coerce")
    tdf["equity"] = pd.to_numeric(tdf["equity"], errors="coerce")
    tdf = tdf.dropna(subset=["exit_date", "equity"]).sort_values("exit_date")
    if tdf.empty:
        return {"annual": [], "monthly": [], "daily": []}

    start_day = tdf["exit_date"].min().normalize()
    end_day = tdf["exit_date"].max().normalize()

    # 用主数据交易日历补齐，保证“交易日每日收益”连续。
    if os.path.exists(parquet_file):
        cal = pd.read_parquet(parquet_file, columns=["trade_date"])
        cal_days = pd.to_datetime(cal["trade_date"].astype(str), errors="coerce").dropna().dt.normalize().drop_duplicates()
        cal_days = cal_days[(cal_days >= start_day) & (cal_days <= end_day)].sort_values()
    else:
        cal_days = pd.date_range(start_day, end_day, freq="B")
    if len(cal_days) == 0:
        return {"annual": [], "monthly": [], "daily": []}

    eq_by_exit = tdf.drop_duplicates(subset=["exit_date"], keep="last").set_index("exit_date")["equity"].to_dict()
    rows = []
    prev_eq = 1.0
    cur_eq = 1.0
    for d in cal_days:
        if d in eq_by_exit:
            cur_eq = float(eq_by_exit[d])
        daily_ret = (cur_eq / prev_eq - 1.0) if prev_eq > 0 else 0.0
        rows.append({"date": d, "equity": cur_eq, "daily_return_pct": daily_ret * 100.0})
        prev_eq = cur_eq

    ddf = pd.DataFrame(rows)
    ddf["year"] = ddf["date"].dt.year.astype(int)
    ddf["month"] = ddf["date"].dt.strftime("%Y-%m")

    # 月收益：月末净值相对上月月末净值
    month_end = ddf.groupby("month", as_index=False).tail(1).copy().sort_values("date")
    month_end["prev_equity"] = month_end["equity"].shift(1).fillna(1.0)
    month_end["return_pct"] = (month_end["equity"] / month_end["prev_equity"] - 1.0) * 100.0

    # 年收益：年末净值相对上年末净值
    year_end = ddf.groupby("year", as_index=False).tail(1).copy().sort_values("date")
    year_end["prev_equity"] = year_end["equity"].shift(1).fillna(1.0)
    year_end["return_pct"] = (year_end["equity"] / year_end["prev_equity"] - 1.0) * 100.0

    annual = [
        {"year": int(r.year), "return_pct": float(r.return_pct), "equity": float(r.equity)}
        for r in year_end.itertuples(index=False)
    ]
    monthly = [
        {
            "month": str(r.month),
            "year": int(str(r.month)[:4]),
            "return_pct": float(r.return_pct),
            "equity": float(r.equity),
        }
        for r in month_end.itertuples(index=False)
    ]
    daily = [
        {
            "date": r.date.strftime("%Y-%m-%d"),
            "month": r.date.strftime("%Y-%m"),
            "year": int(r.date.year),
            "return_pct": float(r.daily_return_pct),
            "equity": float(r.equity),
        }
        for r in ddf.itertuples(index=False)
    ]
    return {"annual": annual, "monthly": monthly, "daily": daily}


def _sanitize_for_json(obj):
    """将 NaN/Inf 与 numpy 标量递归转换为 JSON 安全类型。"""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_for_json(v) for v in obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def _normalize_stock_code(raw) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    # 兼容 000001.SZ / sz000001 / bj920000 / 920000 等
    m = re.search(r"(\d{6})", s)
    return m.group(1) if m else s.zfill(6)


@bp.route("/health")
def health_check():
    cfg = current_app.config
    logger = cfg["MFTS_LOGGER"]

    result_file = cfg["RESULT_FILE"]
    base_dir = cfg["BASE_DIR"]
    output_dir = cfg["OUTPUT_DIR"]
    try:
        gateway = AShareMarketDataGateway(cfg.get("ASHARE_DATA_ROOT") or None)
        sessions = gateway.available_trade_dates()
        latest_ods_session = sessions[-1] if sessions else ""
        metadata = gateway.load_stock_info(latest_ods_session) if latest_ods_session else pd.DataFrame()
    except Exception:
        latest_ods_session = ""
        metadata = pd.DataFrame()

    checks = {
        "flask_running": True,
        "data_source": "ashare_ods",
        "data_file_exists": bool(latest_ods_session),
        "data_latest_trade_date": latest_ods_session,
        "result_file_exists": os.path.exists(result_file),
        "meta_file_exists": not metadata.empty,
    }
    if latest_ods_session:
        latest_dt = pd.Timestamp(latest_ods_session)
        age_hours = max(0.0, (pd.Timestamp.now().tz_localize(None).normalize() - latest_dt).total_seconds() / 3600.0)
        checks["data_age_hours"] = round(age_hours, 1)
        checks["data_is_fresh"] = age_hours < 72.0

    if os.path.exists(result_file):
        mtime = os.path.getmtime(result_file)
        last_update = datetime.fromtimestamp(mtime)
        age_hours = (datetime.now().timestamp() - mtime) / 3600
        checks["result_age_hours"] = round(age_hours, 1)
        checks["result_is_fresh"] = age_hours < 24
        checks["result_last_update"] = last_update.strftime("%Y-%m-%d %H:%M:%S")
        try:
            checks["result_count"] = len(pd.read_csv(result_file))
        except Exception:
            checks["result_count"] = 0

    try:
        disk_usage = shutil.disk_usage(base_dir)
        checks["disk_free_gb"] = round(disk_usage.free / 1024 / 1024 / 1024, 1)
        checks["disk_total_gb"] = round(disk_usage.total / 1024 / 1024 / 1024, 1)
        checks["disk_usage_percent"] = round((disk_usage.used / disk_usage.total) * 100, 1)
        checks["disk_ok"] = checks["disk_free_gb"] > 1
    except OSError:
        checks["disk_ok"] = True

    try:
        root_count = len([f for f in os.listdir(output_dir) if f.startswith("mfts_scan_")])
        scan_subdir = os.path.join(output_dir, "scan")
        sub_count = len([f for f in os.listdir(scan_subdir) if f.startswith("mfts_scan_")]) if os.path.exists(scan_subdir) else 0
        checks["historical_scans"] = root_count + sub_count
    except OSError:
        checks["historical_scans"] = 0

    is_healthy = all(
        [
            checks["flask_running"],
            checks["data_file_exists"],
            checks.get("data_is_fresh", False),
            checks.get("disk_ok", True),
        ]
    )
    status_code = 200 if is_healthy else 503

    return (
        jsonify(
            {
                "status": "healthy" if is_healthy else "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "version": "MFTS v6.1",
                "checks": checks,
            }
        ),
        status_code,
    )


@bp.route("/api/results")
def api_results():
    cfg = current_app.config
    logger = cfg["MFTS_LOGGER"]

    logger.info(f"API请求: /api/results, 参数: {request.args}")
    date_str = request.args.get("date")

    scan_date = None
    if date_str:
        try:
            scan_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as e:
            logger.warning(f"无效日期格式 {date_str}: {e}")

    if scan_date is None:
        scan_files = sorted(glob.glob(os.path.join(cfg["OUTPUT_DIR"], "mfts_scan_*.csv")))
        if scan_files:
            latest_file = scan_files[-1]
            date_part = os.path.basename(latest_file).replace("mfts_scan_", "").replace(".csv", "")
            try:
                scan_date = datetime.strptime(date_part, "%Y%m%d")
                logger.info(f"使用最新扫描日期: {scan_date.strftime('%Y-%m-%d')}")
            except ValueError:
                scan_date = datetime.now()
        else:
            scan_date = datetime.now()
            if scan_date.weekday() >= 5:
                scan_date -= timedelta(days=scan_date.weekday() - 4)

    results, actual_date = load_scan_results(
        cfg["OUTPUT_DIR"],
        cfg["RESULT_FILE"],
        scan_date,
        fallback_to_previous=(date_str is None),
        logger=logger,
    )
    if actual_date:
        scan_date = actual_date

    if date_str is not None and not results:
        return jsonify(
            {
                "success": True,
                "date": scan_date.strftime("%Y-%m-%d") if scan_date else date_str,
                "results": [],
                "verification": {},
                "stats": {
                    "total": 0,
                    "extreme_oversold": 0,
                    "deep_oversold": 0,
                    "trend_signals": 0,
                    "verification_rate": 0,
                    "t5_rate": 0,
                    "t1_count": 0,
                    "t5_count": 0,
                },
                "message": "该日期暂无扫描结果（可能因低覆盖门槛被跳过或尚未重算）",
            }
        )

    codes = [r.get("代码", "") for r in results]
    verification = get_verification_data(codes, scan_date, cfg.get("ASHARE_DATA_ROOT") or None, logger=logger)
    stats = calculate_statistics(results, verification)

    return jsonify(
        {
            "success": True,
            "date": scan_date.strftime("%Y-%m-%d") if scan_date else "",
            "results": results,
            "verification": verification,
            "stats": stats,
        }
    )


@bp.route("/api/results/date_status")
def api_results_date_status():
    """查询某个日期的扫描结果可用性（用于前端日期提示）。"""
    cfg = current_app.config
    date_str = request.args.get("date", "")

    try:
        q_date = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return jsonify({"success": False, "error": "日期格式错误，应为 YYYY-MM-DD"}), 400

    ymd = q_date.strftime("%Y%m%d")
    output_dir = cfg["OUTPUT_DIR"]
    scan_paths = [
        os.path.join(output_dir, "scan", f"mfts_scan_{ymd}.csv"),
        os.path.join(output_dir, f"mfts_scan_{ymd}.csv"),
    ]
    has_scan = any(os.path.exists(p) for p in scan_paths)
    if has_scan:
        return jsonify(
            {
                "success": True,
                "date": date_str,
                "status": "available",
                "message": "该日期已有扫描结果，可直接查看。",
            }
        )

    # 无扫描文件时，检查共享 ODS 单日覆盖，帮助定位原因。
    coverage = 0
    try:
        day = q_date.strftime("%Y-%m-%d")
        df = AShareMarketDataGateway(cfg.get("ASHARE_DATA_ROOT") or None).load_bars(day, day)
        coverage = int(df["ts_code"].astype(str).str.extract(r"(\d{6})", expand=False).nunique())
    except Exception:
        coverage = 0

    stage_min = int(os.environ.get("MFTS_STAGE_MIN_STOCKS", "3000"))
    if coverage == 0:
        status = "no_data"
        message = "该日期共享 ODS 无数据，请由外部数据供应链确认覆盖。"
    elif coverage < stage_min:
        status = "low_coverage"
        message = f"该日期覆盖仅 {coverage}，低于门槛 {stage_min}，通常会被策略跳过。"
    else:
        status = "not_built"
        message = "该日期有主数据但暂无扫描结果，可执行重算生成。"

    suggestion = (
        "python scripts/daily_all.py --mode catchup --rebuild-days 30 "
        "--stage-min-stocks 3000 --verify-min-stocks 3000"
    )
    return jsonify(
        {
            "success": True,
            "date": date_str,
            "status": status,
            "coverage": int(coverage),
            "stage_min_stocks": stage_min,
            "message": message,
            "suggestion": suggestion,
        }
    )


@bp.route("/api/trading_days")
def api_trading_days():
    """返回最近 N 天交易日列表（YYYY-MM-DD），供前端日历控件禁用非交易日。"""
    cfg = current_app.config
    lookback_days = request.args.get("lookback_days", default=365, type=int)
    lookback_days = max(30, min(lookback_days, 2000))

    try:
        sessions = AShareMarketDataGateway(cfg.get("ASHARE_DATA_ROOT") or None).available_trade_dates()
        dt = pd.to_datetime(pd.Series(sessions), errors="coerce").dropna()
        if dt.empty:
            return jsonify({"success": True, "trading_days": []})

        max_day = dt.max().normalize()
        min_day = (max_day - timedelta(days=lookback_days)).normalize()
        dt = dt[(dt >= min_day) & (dt <= max_day)]
        trading_days = sorted(dt.dt.strftime("%Y-%m-%d").unique().tolist())

        return jsonify(
            {
                "success": True,
                "lookback_days": lookback_days,
                "min_date": min_day.strftime("%Y-%m-%d"),
                "max_date": max_day.strftime("%Y-%m-%d"),
                "trading_days": trading_days,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/platform/overview")
def api_platform_overview():
    """交易平台总览：聚合推荐、扫描、验证、回测、优化结果。"""
    date_q = request.args.get("date", "").strip()
    try:
        payload = load_platform_overview(current_app.config, date_q or None)
    except ValueError:
        return jsonify({"success": False, "error": "日期格式应为 YYYY-MM-DD"}), 400
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        current_app.config["MFTS_LOGGER"].error(f"平台总览加载失败: {exc}", exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500
    return jsonify(payload)


@bp.route("/api/run_scan", methods=["POST"])
def api_run_scan():
    cfg = current_app.config
    ok, auth_resp = require_mutation_auth("run_scan")
    if not ok:
        return auth_resp
    try:
        payload = request.get_json(silent=True) or {}
        date_str = str(payload.get("date", "") or "").strip()
        if date_str and not re.match(r"^\d{8}$", date_str):
            return jsonify({"success": False, "error": "date 参数格式应为 YYYYMMDD"}), 400

        # 统一口径：直接调用主扫描引擎，产出 mfts_scan_YYYYMMDD.csv
        script_path = os.path.join(cfg["BASE_DIR"], "core", "mfts_screener.py")
        cmd = [sys.executable, script_path]
        if date_str:
            cmd.extend(["--date", date_str])

        result = subprocess.run(
            cmd,
            cwd=cfg["BASE_DIR"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        return jsonify(
            {
                "success": result.returncode == 0,
                "command": cmd,
                "output": result.stdout,
                "error": result.stderr,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@bp.route("/api/download_data", methods=["POST"])
def api_download_data():
    return jsonify(
        {
            "success": False,
            "error": "此项目只读消费共享 A 股 ODS；数据下载和更新由外部数据供应链维护。",
        }
    ), 410


@bp.route("/api/stock_data/<code>")
def api_stock_data(code: str):
    cfg = current_app.config
    output_dir = cfg["OUTPUT_DIR"]
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)
        gateway = AShareMarketDataGateway(cfg.get("ASHARE_DATA_ROOT") or None)
        df = gateway.load_bars(start_date, end_date)
        norm_code = str(code).strip().split(".")[0].zfill(6)
        ts = df["ts_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna("").str.zfill(6)
        df = df[ts == norm_code]
        if df.empty:
            return jsonify({"success": False, "error": "Stock not found"})

        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
        df = df[df["trade_date"] >= start_date].sort_values("trade_date")

        data = {
            "dates": df["trade_date"].dt.strftime("%Y-%m-%d").tolist(),
            "ohlc": df[["open", "close", "low", "high"]].values.tolist(),
            "vols": df["vol"].tolist(),
        }
        # 关联最近交易记录
        trade_files = sorted(
            set(
                glob.glob(os.path.join(output_dir, "backtest", "quant_trades_*.csv"))
                + glob.glob(os.path.join(output_dir, "quant_trades_*.csv"))
            )
        )
        related_trades = []
        if trade_files:
            tdf = pd.read_csv(trade_files[-1])
            if "codes" in tdf.columns and not tdf.empty:
                m = tdf["codes"].astype(str).str.contains(rf"(?:^|,){norm_code}(?:,|$)", regex=True, na=False)
                sub = tdf[m].copy().tail(20)
                keep = [c for c in ["signal_date", "entry_date", "exit_date", "portfolio_ret", "equity", "codes"] if c in sub.columns]
                related_trades = sub[keep].to_dict("records")

        latest = df.iloc[-1]
        metadata = gateway.load_stock_info(latest["trade_date"])
        name_map = {
            str(ts_code).split(".")[0].zfill(6): str(name)
            for ts_code, name in metadata[["ts_code", "name"]].itertuples(index=False, name=None)
        } if {"ts_code", "name"}.issubset(metadata.columns) else {}
        snapshot = {
            "code": norm_code,
            "name": name_map.get(norm_code, norm_code),
            "last_date": latest["trade_date"].strftime("%Y-%m-%d"),
            "last_close": float(latest["close"]) if pd.notna(latest["close"]) else None,
            "last_open": float(latest["open"]) if pd.notna(latest["open"]) else None,
            "last_high": float(latest["high"]) if pd.notna(latest["high"]) else None,
            "last_low": float(latest["low"]) if pd.notna(latest["low"]) else None,
        }
        return jsonify({"success": True, "data": data, "snapshot": snapshot, "related_trades": related_trades})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
