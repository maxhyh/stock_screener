"""ML 相关路由。"""

from __future__ import annotations

from datetime import datetime, timedelta
import glob
import os
import re

import pandas as pd
from flask import Blueprint, current_app, jsonify, render_template, request

from web.services import calculate_statistics, get_verification_data, load_ml_results

bp = Blueprint("ml", __name__)


@bp.route("/api/ml/daily/<date>")
def api_ml_daily(date: str):
    logger = current_app.config["MFTS_LOGGER"]
    output_dir = current_app.config["OUTPUT_DIR"]

    if not re.match(r"^\d{8}$", date):
        return jsonify({"success": False, "error": "日期格式错误，应为YYYYMMDD"}), 400

    try:
        file_path = os.path.join(output_dir, "daily", f"daily_{date}.csv")
        if not os.path.exists(file_path):
            file_path = os.path.join(output_dir, f"daily_{date}.csv")
        if not os.path.abspath(file_path).startswith(os.path.abspath(output_dir)):
            logger.warning(f"路径遍历尝试: {date}")
            return jsonify({"success": False, "error": "非法路径"}), 403

        if not os.path.exists(file_path):
            return jsonify({"success": False, "error": f"未找到{date}的选股记录"}), 404

        df = pd.read_csv(file_path)
        logger.info(f"成功加载ML选股数据: {date}, {len(df)}条")
        return jsonify({"success": True, "date": date, "count": len(df), "results": df.to_dict("records")})
    except Exception as e:
        logger.error(f"加载ML选股数据失败 {date}: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/ml/latest")
def api_ml_latest():
    output_dir = current_app.config["OUTPUT_DIR"]
    try:
        files = []
        daily_sub = os.path.join(output_dir, "daily")
        if os.path.exists(daily_sub):
            files.extend([f for f in os.listdir(daily_sub) if f.startswith("daily_") and f.endswith(".csv")])
        files.extend([f for f in os.listdir(output_dir) if f.startswith("daily_") and f.endswith(".csv")])
        files = sorted(set(files))
        if not files:
            return jsonify({"success": False, "error": "暂无选股记录"})

        latest_file = sorted(files)[-1]
        date = latest_file.replace("daily_", "").replace(".csv", "")
        latest_path = os.path.join(daily_sub, latest_file) if os.path.exists(os.path.join(daily_sub, latest_file)) else os.path.join(output_dir, latest_file)
        df = pd.read_csv(latest_path)
        return jsonify({"success": True, "date": date, "count": len(df), "results": df.to_dict("records")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@bp.route("/api/ml/verification/<date>")
def api_ml_verification(date: str):
    output_dir = current_app.config["OUTPUT_DIR"]
    try:
        file_path = os.path.join(output_dir, "verify", f"verification_{date}.csv")
        if not os.path.exists(file_path):
            file_path = os.path.join(output_dir, f"verification_{date}.csv")
        if not os.path.exists(file_path):
            return jsonify({"success": False, "error": f"未找到{date}的验证记录"}), 404

        df = pd.read_csv(file_path)
        stats = {
            "win_rate": df["盈利"].mean() * 100 if "盈利" in df.columns else 0,
            "avg_return": df["实际收益%"].mean() if "实际收益%" in df.columns else 0,
            "top10_win_rate": df.head(10)["盈利"].mean() * 100 if "盈利" in df.columns and len(df) >= 10 else 0,
            "top10_avg_return": df.head(10)["实际收益%"].mean() if "实际收益%" in df.columns and len(df) >= 10 else 0,
            "max_return": df["实际收益%"].max() if "实际收益%" in df.columns else 0,
            "min_return": df["实际收益%"].min() if "实际收益%" in df.columns else 0,
        }
        return jsonify({"success": True, "date": date, "stats": stats, "details": df.to_dict("records")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@bp.route("/api/ml/stats/summary")
def api_ml_stats_summary():
    output_dir = current_app.config["OUTPUT_DIR"]
    try:
        history_file = os.path.join(output_dir, "verify", "history_stats.csv")
        if not os.path.exists(history_file):
            history_file = os.path.join(output_dir, "history_stats.csv")
        if not os.path.exists(history_file):
            return jsonify({"success": False, "error": "暂无历史统计数据"})

        df = pd.read_csv(history_file)
        summary = {
            "total_days": len(df),
            "overall_win_rate": df["整体胜率%"].mean(),
            "avg_return": df["平均收益%"].mean(),
            "top10_win_rate": df["Top10胜率%"].mean(),
            "top10_avg_return": df["Top10平均收益%"].mean(),
            "recent_10": df.tail(10)[["验证日期", "整体胜率%", "平均收益%", "Top10胜率%"]].to_dict("records"),
        }
        return jsonify({"success": True, "summary": summary})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@bp.route("/ml")
def ml_page():
    return render_template("ml_daily.html")


@bp.route("/api/ml/results_combined")
def api_ml_results_combined():
    cfg = current_app.config
    logger = cfg["MFTS_LOGGER"]

    date_str = request.args.get("date")
    req_date = None
    date_param = None

    if date_str:
        try:
            req_date = datetime.strptime(date_str, "%Y-%m-%d")
            date_param = req_date.strftime("%Y%m%d")
        except Exception:
            req_date = None
            date_param = None
    else:
        ml_files = sorted(
            set(
                glob.glob(os.path.join(cfg["OUTPUT_DIR"], "daily_*.csv"))
                + glob.glob(os.path.join(cfg["OUTPUT_DIR"], "daily", "daily_*.csv"))
            )
        )
        if ml_files:
            latest_file = ml_files[-1]
            date_part = os.path.basename(latest_file).replace("daily_", "").replace(".csv", "")
            date_param = date_part
            try:
                req_date = datetime.strptime(date_part, "%Y%m%d")
                logger.info(f"使用最新ML文件日期: {date_param}")
            except Exception:
                req_date = datetime.now()
        else:
            req_date = datetime.now()
            if req_date.weekday() >= 5:
                req_date -= timedelta(days=req_date.weekday() - 4)
            date_param = req_date.strftime("%Y%m%d")

    results = load_ml_results(cfg["OUTPUT_DIR"], cfg.get("ASHARE_DATA_ROOT") or None, date_param, logger=logger)

    if results:
        codes = [r["代码"] for r in results]
        if results[0].get("trade_date"):
            try:
                result_date = datetime.strptime(str(results[0]["trade_date"]), "%Y%m%d")
            except Exception:
                result_date = req_date if req_date else datetime.now()
        else:
            result_date = req_date if req_date else datetime.now()
        verification = get_verification_data(codes, result_date, cfg.get("ASHARE_DATA_ROOT") or None, logger=logger)
    else:
        verification = {}

    if results and "trade_date" in results[0]:
        try:
            td = str(results[0]["trade_date"])
            date_display = td if "-" in td else f"{td[:4]}-{td[4:6]}-{td[6:8]}"
        except Exception:
            date_display = req_date.strftime("%Y-%m-%d") if req_date else datetime.now().strftime("%Y-%m-%d")
    else:
        date_display = req_date.strftime("%Y-%m-%d") if req_date else datetime.now().strftime("%Y-%m-%d")

    stats = calculate_statistics(results, verification)

    return jsonify(
        {
            "success": True,
            "results": results,
            "info": "ML Results",
            "date": date_display,
            "stats": stats,
            "verification": verification,
        }
    )


@bp.route("/ml/history")
def ml_history_page():
    return render_template("ml_history.html")


@bp.route("/api/ml/history/summary")
def api_ml_history_summary():
    output_dir = current_app.config["OUTPUT_DIR"]
    try:
        summary_file = os.path.join(output_dir, "verify", "historical_summary.csv")
        if not os.path.exists(summary_file):
            summary_file = os.path.join(output_dir, "historical_summary.csv")
        if not os.path.exists(summary_file):
            return jsonify({"success": False, "error": "暂无历史汇总数据，请先运行 verify_historical.py"})

        df = pd.read_csv(summary_file)
        return jsonify({"success": True, "data": df.to_dict("records")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@bp.route("/api/ml/history/detail/<date>")
def api_ml_history_detail(date: str):
    output_dir = current_app.config["OUTPUT_DIR"]
    try:
        detail_file = os.path.join(output_dir, "verify", f"verification_extended_{date}.csv")
        if not os.path.exists(detail_file):
            detail_file = os.path.join(output_dir, f"verification_extended_{date}.csv")
        if not os.path.exists(detail_file):
            return jsonify({"success": False, "error": f"未找到{date}的详细验证数据"})

        df = pd.read_csv(detail_file)
        return jsonify({"success": True, "date": date, "data": df.to_dict("records")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
