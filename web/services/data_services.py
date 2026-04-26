"""Web 数据服务层：将文件读取/验证统计逻辑从路由层剥离。"""

from __future__ import annotations

from datetime import datetime
import glob
import math
import os
from typing import Any

import numpy as np
import pandas as pd


def df_to_json_safe(df: pd.DataFrame) -> list[dict[str, Any]]:
    """将 DataFrame 转换为 JSON 兼容 records，处理 NaN/Inf。"""
    df = df.replace([np.inf, -np.inf], np.nan)
    records = df.to_dict("records")
    for record in records:
        for key, value in record.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                record[key] = None
    return records


def _is_valid_scan_file(path: str) -> bool:
    """校验扫描结果文件结构，避免读到异常全量指标文件。"""
    try:
        cols = pd.read_csv(path, nrows=0).columns
        required = {"代码", "信号"}
        return required.issubset(set(cols)) and len(cols) <= 30
    except Exception:
        return False


def load_scan_results(
    output_dir: str,
    result_file: str,
    date: datetime | None = None,
    fallback_to_previous: bool = True,
    logger=None,
) -> tuple[list[dict[str, Any]], datetime | None]:
    """加载选股结果，返回 (records, actual_date)。"""
    actual_date = date
    scan_dir = os.path.join(output_dir, "scan")
    scan_dirs = [scan_dir, output_dir]

    if date:
        date_str = date.strftime("%Y%m%d")
        file_path = os.path.join(scan_dir, f"mfts_scan_{date_str}.csv")
        if not os.path.exists(file_path):
            file_path = os.path.join(output_dir, f"mfts_scan_{date_str}.csv")
        # 手动指定日期且关闭回退时：不自动回退到最近日期
        if not os.path.exists(file_path) and not fallback_to_previous:
            if logger:
                logger.info(f"指定日期 {date_str} 无扫描结果，且已禁用回退")
            return [], actual_date
        if not os.path.exists(file_path):
            scan_files = []
            for d in scan_dirs:
                scan_files.extend(glob.glob(os.path.join(d, "mfts_scan_*.csv")))
            scan_files = sorted(set(scan_files))
            if scan_files:
                for f in reversed(scan_files):
                    f_date_str = os.path.basename(f).replace("mfts_scan_", "").replace(".csv", "")
                    try:
                        f_date = datetime.strptime(f_date_str, "%Y%m%d")
                        if f_date <= date:
                            file_path = f
                            actual_date = f_date
                            if logger:
                                logger.info(f"请求日期 {date_str} 无数据，使用最近交易日 {f_date_str}")
                            break
                    except Exception:
                        continue
                else:
                    file_path = scan_files[-1]
                    f_date_str = os.path.basename(file_path).replace("mfts_scan_", "").replace(".csv", "")
                    try:
                        actual_date = datetime.strptime(f_date_str, "%Y%m%d")
                    except Exception:
                        pass
            else:
                file_path = result_file
    else:
        file_path = os.path.join(scan_dir, "mfts_latest.csv")
        if not os.path.exists(file_path):
            file_path = result_file

        scan_files = []
        for d in scan_dirs:
            scan_files.extend(glob.glob(os.path.join(d, "mfts_scan_*.csv")))
        scan_files = sorted(set(scan_files))
        if scan_files:
            f_date_str = os.path.basename(scan_files[-1]).replace("mfts_scan_", "").replace(".csv", "")
            try:
                actual_date = datetime.strptime(f_date_str, "%Y%m%d")
            except Exception:
                pass

    if not os.path.exists(file_path):
        if logger:
            logger.warning(f"结果文件不存在: {file_path}")
        return [], actual_date

    if os.path.getsize(file_path) == 0:
        if logger:
            logger.warning(f"结果文件为空: {file_path}")
        return [], actual_date

    if not _is_valid_scan_file(file_path):
        if logger:
            logger.warning(f"结果文件结构异常，尝试回退: {file_path}")
        scan_files = []
        for d in scan_dirs:
            scan_files.extend(glob.glob(os.path.join(d, "mfts_scan_*.csv")))
        scan_files = sorted(set(scan_files))
        fallback = None
        for f in reversed(scan_files):
            if not _is_valid_scan_file(f):
                continue
            if date is not None:
                f_date_str = os.path.basename(f).replace("mfts_scan_", "").replace(".csv", "")
                try:
                    f_date = datetime.strptime(f_date_str, "%Y%m%d")
                except Exception:
                    continue
                if f_date <= date:
                    fallback = f
                    break
            else:
                fallback = f
                break

        if fallback is None and date is not None:
            for f in scan_files:
                if _is_valid_scan_file(f):
                    fallback = f
                    break

        if fallback:
            file_path = fallback
            f_date_str = os.path.basename(file_path).replace("mfts_scan_", "").replace(".csv", "")
            try:
                actual_date = datetime.strptime(f_date_str, "%Y%m%d")
            except Exception:
                pass
            if logger:
                logger.info(f"使用回退结果文件: {file_path}")
        else:
            if logger:
                logger.error("未找到结构正常的扫描结果文件")
            return [], actual_date

    try:
        df = pd.read_csv(file_path, dtype={"代码": str})
        if logger:
            logger.info(f"成功加载{len(df)}条选股结果")
        return df_to_json_safe(df), actual_date
    except pd.errors.EmptyDataError:
        if logger:
            logger.error(f"文件数据为空: {file_path}")
        return [], actual_date
    except Exception as e:
        if logger:
            logger.error(f"读取文件错误: {e}", exc_info=True)
        return [], actual_date


def get_verification_data(codes: list[str], scan_date: datetime, parquet_file: str, logger=None) -> dict[str, Any]:
    """获取 T+1/T+5 验证数据。"""
    if not os.path.exists(parquet_file):
        return {}

    try:
        df = pd.read_parquet(parquet_file)
        df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
        df["ts_code"] = df["ts_code"].astype(str).str.zfill(6)
        if len(df) > 0 and "." in df["ts_code"].iloc[0]:
            df["ts_code"] = df["ts_code"].apply(lambda x: x.split(".")[0])

        trading_dates = sorted(df["trade_date"].unique())

        scan_ts = pd.Timestamp(scan_date)
        if scan_ts.tz is not None:
            scan_ts = scan_ts.tz_localize(None)

        if scan_ts not in trading_dates:
            prior_dates = [d for d in trading_dates if d <= scan_ts]
            if not prior_dates:
                if logger:
                    logger.warning(f"No trading date found on or before {scan_ts}")
                return {}
            scan_ts = prior_dates[-1]

        curr_idx = trading_dates.index(scan_ts)
        verification: dict[str, Any] = {}

        for days, key in [(1, "t1"), (5, "t5")]:
            target_idx = curr_idx + days
            if target_idx >= len(trading_dates):
                continue

            target_day = trading_dates[target_idx]
            target_df = df[df["trade_date"] == target_day]
            for code in codes:
                normalized_code = str(code).zfill(6)
                if "." in normalized_code:
                    normalized_code = normalized_code.split(".")[0]
                row = target_df[target_df["ts_code"] == normalized_code]
                if row.empty:
                    continue

                pct = row["pct_chg"].values[0]
                if code not in verification:
                    verification[code] = {}
                verification[code][key] = {
                    "pct_chg": round(float(pct), 2),
                    "success": bool(pct > 0),
                }

        return verification
    except Exception as e:
        if logger:
            logger.error(f"Error getting verification: {e}", exc_info=True)
        return {}


def calculate_statistics(results: list[dict[str, Any]], verification: dict[str, Any] | None = None) -> dict[str, Any]:
    """计算结果统计。"""
    if not results:
        return {
            "total": 0,
            "extreme_oversold": 0,
            "deep_oversold": 0,
            "trend_signals": 0,
            "verification_rate": 0,
        }

    df = pd.DataFrame(results)
    stats = {
        "total": len(df),
        "extreme_oversold": len(df[df.get("超跌等级", "") == "极度"]) if "超跌等级" in df.columns else 0,
        "deep_oversold": len(df[df.get("超跌等级", "") == "深度"]) if "超跌等级" in df.columns else 0,
        "trend_signals": len(df[df["信号"].str.contains("趋势", na=False)]) if "信号" in df.columns else 0,
    }

    verification = verification or {}
    if verification:
        t1_results = [v.get("t1", {}) for v in verification.values() if "t1" in v]
        if t1_results:
            t1_success = sum(1 for t1 in t1_results if t1.get("success", False))
            stats["verification_rate"] = round(t1_success / len(t1_results) * 100, 1)
            stats["t1_count"] = len(t1_results)
            stats["t1_success"] = t1_success
        else:
            stats["verification_rate"] = 0
            stats["t1_count"] = 0
            stats["t1_success"] = 0

        t5_results = [v.get("t5", {}) for v in verification.values() if "t5" in v]
        if t5_results:
            t5_success = sum(1 for t5 in t5_results if t5.get("success", False))
            stats["t5_rate"] = round(t5_success / len(t5_results) * 100, 1)
            stats["t5_count"] = len(t5_results)
            stats["t5_success"] = t5_success
        else:
            stats["t5_rate"] = 0
            stats["t5_count"] = 0
            stats["t5_success"] = 0
    else:
        stats["verification_rate"] = 0
        stats["t1_count"] = 0
        stats["t5_rate"] = 0
        stats["t5_count"] = 0

    return stats


def get_stock_names(codes: list[str], meta_file: str) -> dict[str, str]:
    """从 stock_info.csv 获取股票名称。"""
    if not os.path.exists(meta_file):
        return {code: code for code in codes}

    try:
        df = pd.read_csv(meta_file)
        if "ts_code" not in df.columns or "name" not in df.columns:
            return {code: code for code in codes}

        def normalize_code(code_str: str) -> str:
            code_str = str(code_str)
            if "." not in code_str:
                if code_str.startswith(("000", "001", "002", "003", "300", "301")):
                    return f"{code_str}.SZ"
                if code_str.startswith("6"):
                    return f"{code_str}.SH"
                return f"{code_str}.SZ"
            return code_str

        df["ts_code_normalized"] = df["ts_code"].apply(normalize_code)
        name_map = dict(zip(df["ts_code_normalized"], df["name"]))
        return {code: name_map.get(code, code) for code in codes}
    except Exception:
        return {code: code for code in codes}


def load_ml_results(output_dir: str, meta_file: str, date_str: str | None = None, logger=None) -> list[dict[str, Any]]:
    """加载 ML 预测结果并映射到前端展示结构。"""
    search_dirs = [os.path.join(output_dir, "daily"), output_dir, os.path.join(output_dir, "ml_predictions")]
    file_path = None

    if date_str:
        patterns = [f"daily_{date_str}.csv", f"prediction_{date_str}.csv"]
        for d in search_dirs:
            if not os.path.exists(d):
                continue
            for pattern in patterns:
                full_path = os.path.join(d, pattern)
                if os.path.exists(full_path):
                    file_path = full_path
                    break
            if file_path:
                break
    else:
        potential_files: list[str] = []
        for d in search_dirs:
            if not os.path.exists(d):
                continue
            potential_files.extend(glob.glob(os.path.join(d, "daily_*.csv")))
            potential_files.extend(glob.glob(os.path.join(d, "prediction_*.csv")))

        if not potential_files:
            return []

        file_path = max(potential_files, key=os.path.getmtime)

    if not file_path or not os.path.exists(file_path):
        return []

    def _to_float(v, default=0.0):
        try:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return default
            return float(v)
        except Exception:
            return default

    try:
        df = pd.read_csv(file_path, dtype={"代码": str, "ts_code": str, "stock": str})
        df = df.rename(columns={"代码": "ts_code", "ML评分": "score", "收盘价": "close", "日期": "trade_date"})

        if "stock" in df.columns and "ts_code" not in df.columns:
            df["ts_code"] = df["stock"].apply(
                lambda x: x[2:] + "." + x[:2] if isinstance(x, str) and len(x) > 2 else x
            )

        if "ts_code" not in df.columns:
            if logger:
                logger.warning(f"ML file missing ts_code/stock/代码 column: {file_path}")
            return []

        if "score" in df.columns:
            df = df.nlargest(50, "score")
        else:
            df = df.head(50)

        codes = df["ts_code"].tolist()
        name_map = get_stock_names(codes, meta_file)

        results: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            code = row.get("ts_code", "")
            score_val = _to_float(row.get("score", row.get("ML评分", 0.0)), 0.0)
            close_val = _to_float(row.get("close", row.get("收盘价", 0.0)), 0.0)
            chg_val = _to_float(row.get("涨跌幅%", row.get("pct_chg", 0.0)), 0.0)
            bias_val = _to_float(row.get("BIAS-20", row.get("BIAS", 0.0)), 0.0)
            z_val = _to_float(row.get("Z-Score", 0.0), 0.0)
            rsi_val = _to_float(row.get("RSI", 0.0), 0.0)
            vol_ratio_val = _to_float(row.get("量比", row.get("Vol比", 0.0)), 0.0)

            results.append(
                {
                    "代码": code,
                    "名称": row.get("名称", name_map.get(code, code)),
                    "信号": f"ML推荐 (Top {idx + 1})",
                    "涨幅%": chg_val,
                    "Alpha评分": f"{score_val:.4f}",
                    "Z-Score": f"{z_val:.2f}",
                    "BIAS": f"{bias_val:.2f}",
                    "Vol比": f"{vol_ratio_val:.2f}",
                    "超跌等级": "ML",
                    # 保留 ML 原始字段，供前端按 ML 模式专用展示
                    "排名": int(row.get("排名", idx + 1)),
                    "收盘价": close_val,
                    "ML评分": score_val,
                    "BIAS-20": bias_val,
                    "RSI": rsi_val,
                    "量比": vol_ratio_val,
                    "涨跌幅%": chg_val,
                    "市场状态": row.get("市场状态", ""),
                    "建议仓位": row.get("建议仓位", ""),
                    "单票上限": row.get("单票上限", ""),
                    "trade_date": row.get("trade_date", ""),
                }
            )

        return results
    except Exception as e:
        if logger:
            logger.error(f"Error loading ML results: {e}", exc_info=True)
        return []
