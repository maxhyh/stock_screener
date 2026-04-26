"""回测与信号分析路由。"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

import pandas as pd
from flask import Blueprint, current_app, jsonify, render_template, request

from utils.output_paths import get_output_dirs, list_dual, resolve_file
from web.security import require_mutation_auth

bp = Blueprint("backtest_signal", __name__)


@bp.route("/backtest")
def backtest_page():
    return render_template("backtest.html")


@bp.route("/api/backtest/mfts")
def api_backtest_mfts():
    cfg = current_app.config
    logger = cfg["MFTS_LOGGER"]
    try:
        dirs = get_output_dirs(cfg["OUTPUT_DIR"])
        backtest_files = list_dual(["mfts_backtest_*.csv"], dirs["backtest"], dirs["base"])
        if not backtest_files:
            return jsonify({"success": False, "error": "暂无回测数据，请先运行 python scripts/backtest_mfts_lite.py"})

        def date_key(p):
            m = re.search(r"mfts_backtest_(\d+)", p.name)
            return int(m.group(1)) if m else -1

        latest_file = max(backtest_files, key=date_key)
        df = pd.read_csv(latest_file)
        summary = {
            "total_days": len(df),
            "avg_picks": round(df["picks"].mean(), 1),
            "t1_avg_win": round(df["t1_win"].mean(), 1) if "t1_win" in df.columns else 0,
            "t1_avg_return": round(df["t1_avg"].mean(), 2) if "t1_avg" in df.columns else 0,
            "t5_avg_win": round(df["t5_win"].mean(), 1) if "t5_win" in df.columns else 0,
            "t5_avg_return": round(df["t5_avg"].mean(), 2) if "t5_avg" in df.columns else 0,
            "t10_avg_win": round(df["t10_win"].mean(), 1) if "t10_win" in df.columns else 0,
            "t10_avg_return": round(df["t10_avg"].mean(), 2) if "t10_avg" in df.columns else 0,
        }
        return jsonify({"success": True, "file": os.path.basename(latest_file), "summary": summary, "data": df.to_dict("records")})
    except Exception as e:
        logger.error(f"回测API错误: {e}")
        return jsonify({"success": False, "error": str(e)})


@bp.route("/signal-analysis")
def signal_analysis_page():
    return render_template("signal_analysis.html")


@bp.route("/api/signal/stats")
def api_signal_stats():
    cfg = current_app.config
    logger = cfg["MFTS_LOGGER"]
    dirs = get_output_dirs(cfg["OUTPUT_DIR"])
    stats_file = resolve_file(dirs["backtest"] / "signal_stats.json", dirs["base"] / "signal_stats.json")

    if not stats_file:
        return jsonify({"success": False, "error": "统计数据不存在，请先运行 python scripts/analyze_signal_performance.py"})

    try:
        with open(stats_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        if start_date or end_date:
            ok, auth_resp = require_mutation_auth("signal_stats_recompute")
            if not ok:
                return auth_resp
            cmd = [sys.executable, os.path.join(cfg["BASE_DIR"], "scripts", "analyze_signal_performance.py")]
            if start_date:
                cmd.extend(["--start", start_date])
            if end_date:
                cmd.extend(["--end", end_date])
            subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            stats_file = resolve_file(dirs["backtest"] / "signal_stats.json", dirs["base"] / "signal_stats.json")
            if not stats_file:
                return jsonify({"success": False, "error": "统计数据生成失败"})
            with open(stats_file, "r", encoding="utf-8") as f:
                data = json.load(f)

        return jsonify({"success": True, **data})
    except Exception as e:
        logger.error(f"信号统计API错误: {e}")
        return jsonify({"success": False, "error": str(e)})
