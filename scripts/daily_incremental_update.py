#!/usr/bin/env python3
"""
增量数据更新脚本
只下载最新交易日的数据并追加到现有Parquet文件

使用方法:
    python scripts/daily_incremental_update.py
"""

import argparse
import akshare as ak
import pandas as pd
import numpy as np
import datetime
import os
import sys
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import warnings

warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from utils.code_utils import normalize_ts_code_series as _normalize_ts_code_series_util
from utils.trade_calendar import nearest_trade_day_on_or_before, previous_trade_day

DATA_DIR = os.path.join(BASE_DIR, "data")
PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")
META_FILE = os.path.join(DATA_DIR, "stock_info.csv")
INDUSTRY_CACHE_FILE = os.path.join(DATA_DIR, "industry_map_cache.csv")

RETRY_COUNT = 3
DEBUG_MODE = False  # 关闭调试模式，只显示进度条
# 根据机器能力动态设置并发（M5/16G 可安全提高）
CPU_COUNT = max(2, (os.cpu_count() or 4))
# 多日缺口补历史（东方财富区间接口）支持安全并发
# 可通过环境变量 MFTS_RANGE_WORKERS 覆盖，便于本机按网络/性能调优
RANGE_WORKERS = int(os.environ.get("MFTS_RANGE_WORKERS", str(min(24, CPU_COUNT * 2))))
# 多日区间补数最低成功率（低于该阈值视为失败，避免写入严重缺失数据）
MIN_RANGE_SUCCESS_RATIO = float(os.environ.get("MFTS_MIN_RANGE_SUCCESS_RATIO", "0.30"))
# 当日（或补数日期）最低覆盖股票数，低于阈值直接失败，避免污染主数据
MIN_DAILY_COVERAGE = int(os.environ.get("MFTS_MIN_DAILY_COVERAGE", "3000"))
# 历史补数优先腾讯接口（更快），失败自动回退东方财富
PREFER_TX_RANGE = os.environ.get("MFTS_PREFER_TX_RANGE", "true").lower() == "true"
# 行业映射并发与质量门槛
INDUSTRY_WORKERS = int(os.environ.get("MFTS_INDUSTRY_WORKERS", str(min(12, CPU_COUNT))))
MIN_INDUSTRY_COVERAGE = float(os.environ.get("MFTS_MIN_INDUSTRY_COVERAGE", "0.60"))
# 当行业覆盖低于该目标时，触发更重的新浪板块兜底抓取
INDUSTRY_FALLBACK_TARGET_COVERAGE = float(
    os.environ.get("MFTS_INDUSTRY_FALLBACK_TARGET_COVERAGE", "0.80")
)


def fetch_batch_spot_data():
    """
    批量获取当日行情（单日模式优先路径）
    优先新浪 stock_zh_a_spot，失败后回退东方财富 stock_zh_a_spot_em。

    Returns:
        tuple[pd.DataFrame|None, dict|None, str|None]: (原始DataFrame, 列映射, 数据源名称)
    """
    # 方法1: 新浪财经批量接口（部分网络环境更稳定）
    for attempt in range(3):
        try:
            if attempt > 0:
                print(f"   新浪接口第{attempt + 1}次尝试...")
                time.sleep(2 * attempt)
            df_spot = ak.stock_zh_a_spot()
            if df_spot is not None and not df_spot.empty:
                rename_map = {
                    '代码': 'ts_code',
                    '最新价': 'close',
                    '今开': 'open',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'vol',
                    '成交额': 'amount',
                    '涨跌幅': 'pct_chg',
                }
                return df_spot, rename_map, '新浪'
        except Exception as e:
            if attempt < 2:
                print(f"⚠️ 新浪接口尝试{attempt + 1}失败: {str(e)[:60]}, 重试中...")
            else:
                print(f"⚠️ 新浪接口失败: {str(e)[:80]}")

    # 方法2: 东方财富批量接口（备用）
    for attempt in range(3):
        try:
            if attempt > 0:
                print(f"   东方财富接口第{attempt + 1}次尝试...")
                time.sleep(2 * attempt)
            df_spot = ak.stock_zh_a_spot_em()
            if df_spot is not None and not df_spot.empty:
                rename_map = {
                    '代码': 'ts_code',
                    '最新价': 'close',
                    '开盘': 'open',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'vol',
                    '成交额': 'amount',
                    '涨跌幅': 'pct_chg',
                    '换手率': 'turnover_rate',
                }
                return df_spot, rename_map, '东方财富'
        except Exception as e:
            if attempt < 2:
                print(f"⚠️ 东方财富尝试{attempt + 1}失败: {str(e)[:60]}, 重试中...")
            else:
                print(f"❌ 东方财富接口失败: {str(e)[:80]}")

    return None, None, None


def normalize_spot_volume_unit(df, source_name=""):
    """
    统一批量接口成交量单位到“手”。
    经验规则：
    - 若 amount / (vol * close) 的中位数接近 1，说明 vol 以“股”为单位 -> 需 /100
    - 若接近 100，说明 vol 已是“手” -> 不处理
    """
    if df is None or df.empty:
        return df, {"converted": False, "ratio_median": None}

    needed = {'vol', 'amount', 'close'}
    if not needed.issubset(set(df.columns)):
        return df, {"converted": False, "ratio_median": None}

    vol = pd.to_numeric(df['vol'], errors='coerce')
    amt = pd.to_numeric(df['amount'], errors='coerce')
    close = pd.to_numeric(df['close'], errors='coerce')

    valid = (vol > 0) & (amt > 0) & (close > 0)
    if valid.sum() < 50:
        return df, {"converted": False, "ratio_median": None}

    ratio = (amt[valid] / (vol[valid] * close[valid])).replace([np.inf, -np.inf], np.nan).dropna()
    if ratio.empty:
        return df, {"converted": False, "ratio_median": None}

    ratio_median = float(ratio.median())

    # ratio ~ 1 => vol in shares, convert to hands
    if ratio_median < 20:
        df = df.copy()
        df['vol'] = pd.to_numeric(df['vol'], errors='coerce') / 100.0
        return df, {"converted": True, "ratio_median": ratio_median}

    return df, {"converted": False, "ratio_median": ratio_median}


def get_latest_trade_date():
    """获取最新交易日期"""
    today = datetime.date.today()
    return nearest_trade_day_on_or_before(today, parquet_file=PARQUET_FILE).strftime("%Y%m%d")


def get_previous_trade_date(date_obj):
    """获取前一个交易日（优先真实交易日历）。"""
    return previous_trade_day(date_obj, parquet_file=PARQUET_FILE)


def get_stock_list():
    """
    获取所有A股代码
    优先使用现有数据中的股票列表，API失效时仍可正常工作
    """
    print("获取股票列表...")
    
    # 方法1: 从现有parquet数据中提取（主用，最可靠）
    try:
        if os.path.exists(PARQUET_FILE):
            print("  从现有数据中提取股票列表...")
            df = pd.read_parquet(PARQUET_FILE)
            # 确保trade_date是字符串格式
            df['trade_date'] = df['trade_date'].astype(str).str.replace('-', '')
            # 使用sort_values获取最近数据（避免nlargest的类型问题）
            df_sorted = df.sort_values('trade_date', ascending=False)
            recent = df_sorted.head(100000)  # 获取最新10万行数据
            codes = _normalize_ts_code_series_util(recent['ts_code'])
            codes = codes[codes != ''].unique().tolist()
            print(f"✅ 从历史数据提取到 {len(codes)} 只股票")
            return codes
    except Exception as e:
        print(f"⚠️ 从历史数据提取失败: {e}")
    
    # 方法2: 尝试使用 stock_info.csv（备用）
    try:
        if os.path.exists(META_FILE):
            print("  从元数据文件读取...")
            meta_df = pd.read_csv(META_FILE)
            if 'ts_code' in meta_df.columns:
                codes = _normalize_ts_code_series_util(meta_df['ts_code'])
                codes = codes[codes != ''].unique().tolist()
                print(f"✅ 从元数据文件获取到 {len(codes)} 只股票")
                return codes
    except Exception as e:
        print(f"⚠️ 从元数据文件读取失败: {e}")
    
    # 方法3: 尝试API（最后备用）
    try:
        df = ak.stock_zh_a_spot_em()
        codes = _normalize_ts_code_series_util(df['代码'])
        codes = codes[codes != ''].unique().tolist()
        print(f"✅ 从API获取到 {len(codes)} 只股票")
        return codes
    except Exception as e:
        print(f"❌ API获取失败: {e}")
    
    print("❌ 所有方法均失败，无法获取股票列表")
    return []


def normalize_trade_date_series(series):
    """统一日期格式为 YYYYMMDD 字符串，兼容 int/str/datetime/带连字符格式。"""
    dt = pd.to_datetime(series.astype(str), errors='coerce')
    normalized = dt.dt.strftime('%Y%m%d')
    return normalized


def normalize_ts_code_series(series):
    """统一股票代码为 6 位数字字符串（去后缀、补零）。"""
    return _normalize_ts_code_series_util(series)


def _safe_fetch_df(fetcher, retries=3, sleep_base=1.0):
    """带重试的数据抓取包装，失败返回 None。"""
    for i in range(max(1, int(retries))):
        try:
            df = fetcher()
            if df is not None and isinstance(df, pd.DataFrame):
                return df
        except Exception:
            pass
        if i < retries - 1:
            time.sleep(float(sleep_base) * (i + 1) + random.uniform(0, 0.3))
    return None


def _load_old_metadata(meta_file: str) -> pd.DataFrame:
    if not os.path.exists(meta_file):
        return pd.DataFrame(columns=["ts_code", "name", "industry"])
    try:
        df = pd.read_csv(meta_file, dtype={"ts_code": str})
    except Exception:
        return pd.DataFrame(columns=["ts_code", "name", "industry"])
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "name", "industry"])
    code_col = "ts_code" if "ts_code" in df.columns else ("代码" if "代码" in df.columns else None)
    if code_col is None:
        return pd.DataFrame(columns=["ts_code", "name", "industry"])
    name_col = "name" if "name" in df.columns else ("名称" if "名称" in df.columns else None)
    ind_col = "industry" if "industry" in df.columns else ("行业" if "行业" in df.columns else None)
    out = pd.DataFrame()
    out["ts_code"] = normalize_ts_code_series(df[code_col])
    out["name"] = df[name_col].astype(str).fillna("").str.strip() if name_col else ""
    out["industry"] = df[ind_col].astype(str).fillna("").str.strip() if ind_col else ""
    out["industry"] = out["industry"].replace({"nan": "", "None": ""})
    out = out[out["ts_code"] != ""].drop_duplicates(subset=["ts_code"], keep="last")
    return out


def _metadata_coverage(meta_df: pd.DataFrame) -> float:
    if meta_df is None or meta_df.empty:
        return 0.0
    ind = meta_df.get("industry", pd.Series([""] * len(meta_df), index=meta_df.index)).astype(str).str.strip()
    ind = ind.replace({"nan": "", "None": ""})
    return float((ind != "").mean())


def _load_industry_cache(cache_file: str) -> dict[str, str]:
    if not os.path.exists(cache_file):
        return {}
    try:
        cdf = pd.read_csv(cache_file, dtype={"ts_code": str})
    except Exception:
        return {}
    if cdf.empty or "ts_code" not in cdf.columns or "industry" not in cdf.columns:
        return {}
    cdf = cdf.copy()
    cdf["ts_code"] = normalize_ts_code_series(cdf["ts_code"])
    cdf["industry"] = cdf["industry"].astype(str).fillna("").str.strip()
    cdf["industry"] = cdf["industry"].replace({"nan": "", "None": ""})
    cdf = cdf[(cdf["ts_code"] != "") & (cdf["industry"] != "")]
    cdf = cdf.drop_duplicates(subset=["ts_code"], keep="last")
    return dict(zip(cdf["ts_code"], cdf["industry"]))


def _save_industry_cache(cache_file: str, industry_map: dict[str, str]) -> None:
    if not industry_map:
        return
    cdf = pd.DataFrame(
        {
            "ts_code": list(industry_map.keys()),
            "industry": list(industry_map.values()),
        }
    )
    cdf["ts_code"] = normalize_ts_code_series(cdf["ts_code"])
    cdf["industry"] = cdf["industry"].astype(str).fillna("").str.strip()
    cdf = cdf[(cdf["ts_code"] != "") & (cdf["industry"] != "")]
    cdf = cdf.drop_duplicates(subset=["ts_code"], keep="last")
    if cdf.empty:
        return
    cdf.to_csv(cache_file, index=False, encoding="utf-8")


def _fetch_industry_map_from_ak() -> dict[str, str]:
    """
    抓取行业映射：
    1) 获取行业板块列表
    2) 并发抓取板块成分股
    """
    board_df = _safe_fetch_df(lambda: ak.stock_board_industry_name_em(), retries=3, sleep_base=1.2)
    if board_df is None or board_df.empty or "板块名称" not in board_df.columns:
        return {}
    boards = [str(x).strip() for x in board_df["板块名称"].dropna().tolist() if str(x).strip()]
    if not boards:
        return {}

    industry_map: dict[str, str] = {}

    def _fetch_cons(ind_name: str):
        df = _safe_fetch_df(lambda: ak.stock_board_industry_cons_em(symbol=ind_name), retries=2, sleep_base=0.8)
        if df is None or df.empty or "代码" not in df.columns:
            return ind_name, []
        codes = normalize_ts_code_series(df["代码"])
        codes = [c for c in codes.tolist() if c]
        return ind_name, codes

    with ThreadPoolExecutor(max_workers=max(1, INDUSTRY_WORKERS)) as executor:
        futures = {executor.submit(_fetch_cons, b): b for b in boards}
        for fut in as_completed(futures):
            ind_name, codes = fut.result()
            for c in codes:
                industry_map[c] = ind_name

    return industry_map


def _extract_industry_map_from_spot(df_spot: pd.DataFrame) -> dict[str, str]:
    """从批量 spot 快照中提取行业映射（若接口直接提供行业字段）。"""
    if df_spot is None or df_spot.empty:
        return {}
    code_col = "代码" if "代码" in df_spot.columns else ("ts_code" if "ts_code" in df_spot.columns else None)
    if code_col is None:
        return {}

    ind_col = None
    for c in ("所处行业", "所属行业", "行业", "industry", "行业板块", "板块"):
        if c in df_spot.columns:
            ind_col = c
            break
    if ind_col is None:
        return {}

    work = df_spot[[code_col, ind_col]].copy()
    work["ts_code"] = normalize_ts_code_series(work[code_col])
    work["industry"] = work[ind_col].astype(str).fillna("").str.strip()
    work["industry"] = work["industry"].replace({"nan": "", "None": ""})
    work = work[(work["ts_code"] != "") & (work["industry"] != "")].drop_duplicates(subset=["ts_code"], keep="last")
    if work.empty:
        return {}
    return dict(zip(work["ts_code"], work["industry"]))


def _fetch_industry_map_from_spot_em() -> dict[str, str]:
    """
    备用行业抓取：直接从东方财富批量 spot 提取行业字段。
    场景：行业板块接口不可用时，尽量维持基础行业覆盖。
    """
    df_em = _safe_fetch_df(lambda: ak.stock_zh_a_spot_em(), retries=2, sleep_base=1.0)
    if df_em is None or df_em.empty:
        return {}
    return _extract_industry_map_from_spot(df_em)


def _extract_sector_pairs_from_sector_spot(df_sector_spot: pd.DataFrame) -> list[tuple[str, str]]:
    """从板块快照中提取 (sector_query, industry_name) 列表。"""
    if df_sector_spot is None or df_sector_spot.empty:
        return []

    label_col = None
    for c in ("label", "板块代码", "sector", "id"):
        if c in df_sector_spot.columns:
            label_col = c
            break

    name_col = None
    for c in ("板块", "板块名称", "名称", "name", "行业"):
        if c in df_sector_spot.columns:
            name_col = c
            break

    if label_col is None and name_col is None:
        return []

    labels = (
        df_sector_spot[label_col]
        .astype(str)
        .fillna("")
        .str.strip()
        .replace({"nan": "", "None": ""})
        if label_col is not None
        else pd.Series([""] * len(df_sector_spot), index=df_sector_spot.index)
    )
    names = (
        df_sector_spot[name_col]
        .astype(str)
        .fillna("")
        .str.strip()
        .replace({"nan": "", "None": ""})
        if name_col is not None
        else pd.Series([""] * len(df_sector_spot), index=df_sector_spot.index)
    )

    pairs: list[tuple[str, str]] = []
    for idx in df_sector_spot.index:
        sector_query = labels.loc[idx] or names.loc[idx]
        industry_name = names.loc[idx] or labels.loc[idx]
        if not sector_query or not industry_name:
            continue
        pairs.append((sector_query, industry_name))
    if not pairs:
        return []
    return list(dict.fromkeys(pairs))


def _extract_codes_from_sector_detail(df_sector_detail: pd.DataFrame) -> list[str]:
    """从板块成分明细中提取股票代码列表。"""
    if df_sector_detail is None or df_sector_detail.empty:
        return []
    code_col = None
    for c in ("代码", "股票代码", "code", "证券代码", "symbol"):
        if c in df_sector_detail.columns:
            code_col = c
            break
    if code_col is None:
        return []
    codes = normalize_ts_code_series(df_sector_detail[code_col])
    return [c for c in codes.tolist() if c]


def _fetch_industry_map_from_sina_sectors() -> dict[str, str]:
    """
    新浪板块兜底行业映射：
    - 优先 indicator=行业，再尝试 新浪行业
    - 对每个板块抓取成分股，并映射到板块名
    """
    indicators = ("行业", "新浪行业")
    industry_map: dict[str, str] = {}

    for indicator in indicators:
        spot_df = _safe_fetch_df(
            lambda ind=indicator: ak.stock_sector_spot(indicator=ind),
            retries=2,
            sleep_base=1.0,
        )
        sector_pairs = _extract_sector_pairs_from_sector_spot(spot_df)
        if not sector_pairs:
            continue

        def _fetch_one_sector(sector_query: str, industry_name: str):
            detail_df = _safe_fetch_df(
                lambda s=sector_query: ak.stock_sector_detail(sector=s),
                retries=2,
                sleep_base=0.8,
            )
            return industry_name, _extract_codes_from_sector_detail(detail_df)

        with ThreadPoolExecutor(max_workers=max(1, INDUSTRY_WORKERS)) as executor:
            futures = {
                executor.submit(_fetch_one_sector, sector_query, industry_name): (sector_query, industry_name)
                for sector_query, industry_name in sector_pairs
            }
            for fut in as_completed(futures):
                industry_name, codes = fut.result()
                if not codes:
                    continue
                for code in codes:
                    # 保留更高优先级来源（先写入者）
                    industry_map.setdefault(code, industry_name)

    return industry_map


def _build_metadata_from_spot(df_spot: pd.DataFrame) -> pd.DataFrame:
    """基于 spot 快照构建标准化元数据表。"""
    if df_spot is None or df_spot.empty:
        return pd.DataFrame(columns=["ts_code", "name", "industry"])
    if ("代码" not in df_spot.columns) or ("名称" not in df_spot.columns):
        return pd.DataFrame(columns=["ts_code", "name", "industry"])
    meta_df = df_spot[["代码", "名称"]].rename(columns={"代码": "ts_code", "名称": "name"}).copy()
    meta_df["ts_code"] = normalize_ts_code_series(meta_df["ts_code"])
    meta_df["name"] = meta_df["name"].astype(str).fillna("").str.strip()
    spot_industry_map = _extract_industry_map_from_spot(df_spot)
    meta_df["industry"] = meta_df["ts_code"].map(spot_industry_map).fillna("").astype(str).str.strip()
    meta_df["industry"] = meta_df["industry"].replace({"nan": "", "None": ""})
    meta_df = meta_df[meta_df["ts_code"] != ""].drop_duplicates(subset=["ts_code"], keep="last")
    return meta_df


def _merge_industry_into_metadata(base_meta: pd.DataFrame, industry_map: dict[str, str], old_meta: pd.DataFrame) -> pd.DataFrame:
    """合并行业：优先新抓取，其次旧元数据。"""
    if base_meta is None or base_meta.empty:
        return pd.DataFrame(columns=["ts_code", "name", "industry"])
    out = base_meta.copy()
    if "industry" not in out.columns:
        out["industry"] = ""
    # 先保留 spot 自带行业，再用行业映射补齐
    out["industry"] = out["industry"].astype(str).fillna("").str.strip()
    out["industry"] = out["industry"].replace({"nan": "", "None": ""})
    miss_spot = out["industry"] == ""
    out.loc[miss_spot, "industry"] = out.loc[miss_spot, "ts_code"].map(industry_map).fillna("")
    out["industry"] = out["industry"].replace({"nan": "", "None": ""})

    if old_meta is not None and not old_meta.empty and "ts_code" in old_meta.columns and "industry" in old_meta.columns:
        old_ind = old_meta.copy()
        old_ind["ts_code"] = normalize_ts_code_series(old_ind["ts_code"])
        old_ind["industry"] = old_ind["industry"].astype(str).fillna("").str.strip()
        old_ind["industry"] = old_ind["industry"].replace({"nan": "", "None": ""})
        old_map = (
            old_ind[old_ind["industry"] != ""][["ts_code", "industry"]]
            .drop_duplicates(subset=["ts_code"], keep="last")
            .set_index("ts_code")["industry"]
            .to_dict()
        )
        miss = out["industry"] == ""
        out.loc[miss, "industry"] = out.loc[miss, "ts_code"].map(old_map).fillna("")
    return out


def _apply_industry_completeness_gate(new_meta: pd.DataFrame, old_meta: pd.DataFrame, min_coverage: float):
    """
    行业完整率门禁：
    - 若旧数据已达阈值，但新数据低于阈值，则拒绝降级（保留旧元数据）。
    """
    new_cov = _metadata_coverage(new_meta)
    old_cov = _metadata_coverage(old_meta)
    gate_hit = (old_cov >= float(min_coverage)) and (new_cov < float(min_coverage))
    if gate_hit and old_meta is not None and not old_meta.empty:
        return old_meta.copy(), True, new_cov, old_cov
    return new_meta.copy(), False, new_cov, old_cov


def build_metadata_with_industry(df_spot: pd.DataFrame, meta_file: str = META_FILE, cache_file: str = INDUSTRY_CACHE_FILE) -> tuple[pd.DataFrame, dict]:
    """
    构建带行业的元数据，含缓存与完整率门禁。
    返回: (final_meta, stats)
    """
    old_meta = _load_old_metadata(meta_file)
    base_meta = _build_metadata_from_spot(df_spot)
    if base_meta.empty:
        return old_meta, {"used_old_only": True, "new_coverage": 0.0, "old_coverage": _metadata_coverage(old_meta), "gate_hit": False}

    cache_map = _load_industry_cache(cache_file)
    fresh_map = _fetch_industry_map_from_ak()
    spot_fallback_map: dict[str, str] = {}
    sina_fallback_map: dict[str, str] = {}
    # 行业板块接口失效时，回退到批量 spot 的行业字段。
    if not fresh_map:
        spot_fallback_map = _fetch_industry_map_from_spot_em()
    merged_map = dict(cache_map)
    merged_map.update({k: v for k, v in fresh_map.items() if str(v).strip()})
    merged_map.update({k: v for k, v in spot_fallback_map.items() if str(v).strip()})

    merged_meta = _merge_industry_into_metadata(base_meta, merged_map, old_meta)
    pre_sina_coverage = _metadata_coverage(merged_meta)
    fallback_trigger_coverage = max(
        float(MIN_INDUSTRY_COVERAGE),
        min(max(float(INDUSTRY_FALLBACK_TARGET_COVERAGE), 0.0), 1.0),
    )
    if pre_sina_coverage < fallback_trigger_coverage:
        sina_fallback_map = _fetch_industry_map_from_sina_sectors()
        if sina_fallback_map:
            for code, industry in sina_fallback_map.items():
                if code not in merged_map and str(industry).strip():
                    merged_map[code] = industry
            merged_meta = _merge_industry_into_metadata(base_meta, merged_map, old_meta)

    final_meta, gate_hit, new_cov, old_cov = _apply_industry_completeness_gate(
        merged_meta,
        old_meta,
        min_coverage=MIN_INDUSTRY_COVERAGE,
    )

    # 保护 name：优先最新 spot；若 gate 触发且旧元数据保留，则用 spot 名称覆盖同代码旧名称
    if gate_hit and not final_meta.empty:
        name_map = base_meta.set_index("ts_code")["name"].to_dict()
        final_meta = final_meta.copy()
        final_meta["name"] = final_meta["ts_code"].map(name_map).fillna(final_meta.get("name", "")).astype(str)

    # 更新缓存（缓存不受 gate 影响，可积累行业映射）
    if merged_map:
        _save_industry_cache(cache_file, merged_map)

    stats = {
        "used_old_only": False,
        "gate_hit": bool(gate_hit),
        "new_coverage": float(new_cov),
        "old_coverage": float(old_cov),
        "final_coverage": float(_metadata_coverage(final_meta)),
        "fresh_industry_count": int(len(fresh_map)),
        "spot_fallback_industry_count": int(len(spot_fallback_map)),
        "sina_fallback_industry_count": int(len(sina_fallback_map)),
        "cached_industry_count": int(len(cache_map)),
        "pre_sina_coverage": float(pre_sina_coverage),
        "fallback_trigger_coverage": float(fallback_trigger_coverage),
    }
    return final_meta, stats


def _fetch_spot_for_metadata() -> pd.DataFrame | None:
    """抓取元数据所需批量行情：优先东财，失败回退新浪。"""
    try:
        df_spot = ak.stock_zh_a_spot_em()
        if df_spot is not None and not df_spot.empty:
            return df_spot
    except Exception:
        pass
    try:
        df_spot = ak.stock_zh_a_spot()
        if df_spot is not None and not df_spot.empty:
            return df_spot
    except Exception:
        pass
    return None


def refresh_stock_metadata(meta_file: str = META_FILE, cache_file: str = INDUSTRY_CACHE_FILE) -> tuple[bool, dict]:
    """刷新股票元数据（名称+行业），失败不抛异常。"""
    try:
        print("\n更新股票元数据...")
        df_spot = _fetch_spot_for_metadata()
        meta_df, meta_stats = build_metadata_with_industry(
            df_spot=df_spot,
            meta_file=meta_file,
            cache_file=cache_file,
        )
        if meta_df is None or meta_df.empty:
            print("⚠️ 元数据为空，保留旧文件")
            return False, meta_stats

        meta_df = meta_df[["ts_code", "name", "industry"]].copy()
        meta_df.to_csv(meta_file, index=False, encoding="utf-8")
        print(
            "✅ 元数据已更新 | "
            f"行业覆盖: {meta_stats.get('final_coverage', 0.0):.2%} "
            f"(new={meta_stats.get('new_coverage', 0.0):.2%}, old={meta_stats.get('old_coverage', 0.0):.2%}) "
            f"| gate_hit={meta_stats.get('gate_hit', False)} "
            f"| ak={meta_stats.get('fresh_industry_count', 0)} "
            f"| em_spot={meta_stats.get('spot_fallback_industry_count', 0)} "
            f"| sina={meta_stats.get('sina_fallback_industry_count', 0)}"
        )
        if meta_stats.get("final_coverage", 0.0) < MIN_INDUSTRY_COVERAGE:
            print(
                f"⚠️ 行业覆盖率低于阈值 {MIN_INDUSTRY_COVERAGE:.0%}，"
                "请检查行业接口可用性；当前已尽量保留历史行业映射。"
            )
        return True, meta_stats
    except Exception as e:
        print(f"⚠️ 元数据更新失败（不影响主数据）: {e}")
        return False, {}


def backfill_ohlc_fields(new_df: pd.DataFrame, existing_df: pd.DataFrame) -> pd.DataFrame:
    """
    回填 OHLC 缺失，避免单日批量接口缺 open 导致下游验证回退。
    规则（尽量保守）：
    1) open 缺失：优先前收(close_1)，否则用当日 close
    2) high/low 缺失：用 max/min(open, close)
    3) 强制价格区间一致：确保 low <= min(open, close) <= max(open, close) <= high
    """
    if new_df is None or new_df.empty:
        return new_df

    req_cols = {'ts_code', 'trade_date', 'close'}
    if not req_cols.issubset(set(new_df.columns)):
        return new_df

    work = new_df.copy()
    for col in ['open', 'high', 'low', 'close']:
        if col not in work.columns:
            work[col] = np.nan
        work[col] = pd.to_numeric(work[col], errors='coerce')

    # 仅用历史 close 计算前收，避免同日值污染
    hist = existing_df[['ts_code', 'trade_date', 'close']].copy()
    hist['ts_code'] = normalize_ts_code_series(hist['ts_code'])
    hist['trade_date'] = normalize_trade_date_series(hist['trade_date'])
    hist['close'] = pd.to_numeric(hist['close'], errors='coerce')

    merged = pd.concat(
        [
            hist.assign(_is_new=0),
            work[['ts_code', 'trade_date', 'close']].assign(_is_new=1),
        ],
        ignore_index=True,
    )
    merged = merged.sort_values(['ts_code', 'trade_date', '_is_new'])
    merged['close_1'] = merged.groupby('ts_code')['close'].shift(1)
    prev_close_map = (
        merged[merged['_is_new'] == 1][['ts_code', 'trade_date', 'close_1']]
        .drop_duplicates(subset=['ts_code', 'trade_date'], keep='last')
    )
    work = work.merge(prev_close_map, on=['ts_code', 'trade_date'], how='left')

    # 1) open 回填
    miss_open = work['open'].isna() | (work['open'] <= 0)
    fill_open_prev = miss_open & work['close_1'].notna() & (work['close_1'] > 0)
    fill_open_close = miss_open & (~fill_open_prev) & work['close'].notna() & (work['close'] > 0)
    if fill_open_prev.any():
        work.loc[fill_open_prev, 'open'] = work.loc[fill_open_prev, 'close_1']
    if fill_open_close.any():
        work.loc[fill_open_close, 'open'] = work.loc[fill_open_close, 'close']

    # 2) high/low 回填
    oc_max = work[['open', 'close']].max(axis=1)
    oc_min = work[['open', 'close']].min(axis=1)
    miss_high = work['high'].isna() | (work['high'] <= 0)
    miss_low = work['low'].isna() | (work['low'] <= 0)
    work.loc[miss_high & oc_max.notna(), 'high'] = oc_max[miss_high & oc_max.notna()]
    work.loc[miss_low & oc_min.notna(), 'low'] = oc_min[miss_low & oc_min.notna()]

    # 3) 区间一致性修正
    work['high'] = np.nanmax(np.vstack([work['high'].values, oc_max.values]), axis=0)
    work['low'] = np.nanmin(np.vstack([work['low'].values, oc_min.values]), axis=0)

    # 日志
    patched_open = int((fill_open_prev | fill_open_close).sum())
    patched_high = int(miss_high.sum())
    patched_low = int(miss_low.sum())
    if patched_open > 0 or patched_high > 0 or patched_low > 0:
        print(
            "ℹ️ OHLC缺失回填: "
            f"open={patched_open}, high={patched_high}, low={patched_low} "
            "(open优先前收，其次收盘)"
        )

    work = work.drop(columns=['close_1'], errors='ignore')
    return work


def safe_download_single_day(code, date_str):
    """
    下载单只股票的单日数据
    双API支持：优先腾讯(稳定)，失败时回退到东方财富
    """
    # 北交所股票 (8/9/4开头) - API不稳定，且数量少，跳过
    # 这些股票在MFTS选股中占比很小，不影响主要功能
    if code.startswith(('8', '9', '4')):
        return None  # 静默跳过，不打印错误
    
    # 方法1: 使用腾讯接口 (主用) - 更稳定
    try:
        time.sleep(random.uniform(0.05, 0.15))
        
        # 转换代码格式: 
        # 深市: 000/001/002/003/300/301 开头 -> sz
        # 沪市: 6 开头 -> sh
        if code.startswith(('000', '001', '002', '003', '300', '301')):
            prefix = 'sz'
        elif code.startswith('6'):
            prefix = 'sh'
        else:
            # 其他未知格式，尝试东方财富
            return _download_via_eastmoney(code, date_str)
        
        symbol_code = f'{prefix}{code}'
        
        # 获取完整历史数据
        df_full = ak.stock_zh_a_daily(symbol=symbol_code, adjust="qfq")
        
        if df_full is not None and not df_full.empty:
            # 确保按日期排序
            df_full = df_full.sort_values('date').reset_index(drop=True)
            df_full['date'] = pd.to_datetime(df_full['date']).dt.strftime('%Y%m%d')
            
            # 计算涨跌幅 (pct_chg = (今日收盘 / 昨日收盘 - 1) * 100)
            df_full['prev_close'] = df_full['close'].shift(1)
            df_full['pct_chg'] = (df_full['close'] / df_full['prev_close'] - 1) * 100
            
            # 过滤目标日期
            df = df_full[df_full['date'] == date_str].copy()
            
            if not df.empty:
                # 标准化列名 (腾讯接口)
                rename_map = {
                    'date': 'trade_date',
                    'open': 'open',
                    'close': 'close',
                    'high': 'high',
                    'low': 'low',
                    'volume': 'vol',  # 腾讯接口用 volume
                    'turnover': 'turnover_rate',  # 腾讯接口用 turnover
                }
                
                df = df.rename(columns=rename_map)
                df['ts_code'] = code
                
                # 选择需要的列
                target_cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 
                              'close', 'vol', 'amount', 'pct_chg', 'turnover_rate']
                available_cols = [c for c in target_cols if c in df.columns]
                
                return df[available_cols]
    
    except Exception as e:
        # 腾讯接口失败，尝试东方财富接口
        if DEBUG_MODE:
            print(f"\n[DEBUG] {code} 腾讯接口失败: {str(e)[:100]}")
    
    # 回退到东方财富接口
    return _download_via_eastmoney(code, date_str)


def _download_via_eastmoney(code, date_str):
    """
    使用东方财富接口下载数据（备用方案）
    增加延迟避免被限流
    """
    for i in range(RETRY_COUNT):
        try:
            # 增加延迟，避免连接被拒绝
            time.sleep(random.uniform(0.5, 1.0) * (i + 1))
            
            df = ak.stock_zh_a_hist(
                symbol=code, 
                period="daily", 
                start_date=date_str, 
                end_date=date_str, 
                adjust="qfq"
            )
            
            if df is None or df.empty:
                return None
            
            # 标准化列名 (东方财富接口)
            rename_map = {
                '日期': 'trade_date', '开盘': 'open', '收盘': 'close',
                '最高': 'high', '最低': 'low', '成交量': 'vol',
                '成交额': 'amount', '换手率': 'turnover_rate',
                '涨跌幅': 'pct_chg', '振幅': 'amplitude', '涨跌额': 'change'
            }
            df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
            df['ts_code'] = code
            
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')
            
            target_cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 
                          'close', 'vol', 'amount', 'pct_chg', 'turnover_rate']
            final_cols = [c for c in target_cols if c in df.columns]
            
            return df[final_cols]
            
        except Exception as e:
            if DEBUG_MODE and i == 0:
                print(f"\n[DEBUG] {code} 东方财富接口失败: {str(e)[:80]}")
            if i == RETRY_COUNT - 1:
                return None
            time.sleep(2.0 * (i + 1))  # 更长的重试延迟
    
    return None


def download_stock_daterange(code, start_date, end_date):
    """
    下载单只股票的日期范围数据（用于填补多日缺口）
    使用东方财富 stock_zh_a_hist 接口
    """
    if code.startswith(('8', '9', '4')):
        return None

    # 优先腾讯接口（通常更快），失败后回退东方财富
    if PREFER_TX_RANGE:
        tx_df = _download_daterange_via_tencent(code, start_date, end_date)
        if tx_df is not None and not tx_df.empty:
            return tx_df

    # 回退东方财富接口
    for i in range(RETRY_COUNT):
        try:
            time.sleep(random.uniform(0.05, 0.15))
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )
            
            if df is None or df.empty:
                return None
            
            rename_map = {
                '日期': 'trade_date', '开盘': 'open', '收盘': 'close',
                '最高': 'high', '最低': 'low', '成交量': 'vol',
                '成交额': 'amount', '换手率': 'turnover_rate',
                '涨跌幅': 'pct_chg',
            }
            df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
            df['ts_code'] = code
            
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')
            
            target_cols = ['ts_code', 'trade_date', 'open', 'high', 'low',
                          'close', 'vol', 'amount', 'pct_chg', 'turnover_rate']
            final_cols = [c for c in target_cols if c in df.columns]
            return df[final_cols]
            
        except Exception as e:
            if DEBUG_MODE and i == 0:
                print(f"\n[DEBUG] {code} 区间下载失败: {str(e)[:80]}")
            if i == RETRY_COUNT - 1:
                return None
            time.sleep(1.0 * (i + 1))
    
    return None


def _download_daterange_via_tencent(code, start_date, end_date):
    """使用腾讯区间历史接口下载单只股票数据（优先路径）。"""
    # 腾讯接口要求市场前缀
    if code.startswith(('000', '001', '002', '003', '300', '301')):
        symbol = f"sz{code}"
    elif code.startswith('6'):
        symbol = f"sh{code}"
    else:
        return None

    for i in range(RETRY_COUNT):
        try:
            # 腾讯接口速度通常更快，降低基础等待时间
            time.sleep(random.uniform(0.01, 0.05))

            df = ak.stock_zh_a_hist_tx(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is None or df.empty:
                return None

            rename_map = {
                'date': 'trade_date', '日期': 'trade_date',
                'open': 'open', '开盘': 'open',
                'close': 'close', '收盘': 'close',
                'high': 'high', '最高': 'high',
                'low': 'low', '最低': 'low',
                'amount': 'amount', '成交额': 'amount',
                'volume': 'vol', '成交量': 'vol',
                'turnover': 'turnover_rate', '换手率': 'turnover_rate',
                'pct_chg': 'pct_chg', '涨跌幅': 'pct_chg',
            }
            df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
            df['ts_code'] = code

            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date'], errors='coerce').dt.strftime('%Y%m%d')

            # 腾讯接口某些情况下不返回 pct_chg，按收盘价补算
            if 'pct_chg' not in df.columns and 'close' in df.columns:
                close = pd.to_numeric(df['close'], errors='coerce')
                prev_close = close.shift(1)
                df['pct_chg'] = (close / prev_close - 1) * 100

            target_cols = ['ts_code', 'trade_date', 'open', 'high', 'low',
                          'close', 'vol', 'amount', 'pct_chg', 'turnover_rate']
            final_cols = [c for c in target_cols if c in df.columns]
            return df[final_cols]

        except Exception as e:
            if DEBUG_MODE and i == 0:
                print(f"\n[DEBUG] {code} 腾讯区间下载失败: {str(e)[:80]}")
            if i == RETRY_COUNT - 1:
                return None
            time.sleep(0.5 * (i + 1))

    return None


def validate_date_yyyymmdd(date_str):
    """校验日期格式 YYYYMMDD。"""
    try:
        datetime.datetime.strptime(date_str, "%Y%m%d")
        return True
    except Exception:
        return False


def incremental_update(target_date_override=None):
    """增量更新：默认更新到最新交易日；可通过 target_date_override 精确补指定交易日。"""
    
    print("=" * 70)
    print("MFTS 增量数据更新")
    print("=" * 70)
    
    # 1. 检查现有数据
    if not os.path.exists(PARQUET_FILE):
        print(f"❌ 数据文件不存在: {PARQUET_FILE}")
        print("请先运行 download_5y_data.py 下载完整数据")
        return False
    
    # 2. 读取现有数据的最新日期
    print(f"\n读取现有数据: {PARQUET_FILE}")
    try:
        existing_df = pd.read_parquet(PARQUET_FILE)
        raw_ts = existing_df['ts_code'].astype(str)
        raw_date = existing_df['trade_date'].astype(str)
        needs_cleanup = (
            raw_ts.str.len().ne(6).any()
            or raw_ts.str.contains(r'[^0-9.]', regex=True).any()
            or raw_date.str.contains('-', regex=False).any()
        )

        # 统一历史脏数据格式，避免后续比较/过滤错误
        existing_df['trade_date'] = normalize_trade_date_series(existing_df['trade_date'])
        existing_df['ts_code'] = normalize_ts_code_series(existing_df['ts_code'])
        existing_df = existing_df.dropna(subset=['trade_date', 'ts_code'])

        # 一次性清洗回写：避免“代码格式混乱导致最新日无数据”
        if needs_cleanup:
            print("⚠️ 检测到历史数据代码/日期格式不一致，先执行归一化清洗...")
            cleaned_df = existing_df.sort_values(['ts_code', 'trade_date'])
            cleaned_df = cleaned_df.drop_duplicates(subset=['ts_code', 'trade_date'], keep='last')
            cleaned_df['ts_code'] = cleaned_df['ts_code'].astype('category')
            cleaned_df.to_parquet(PARQUET_FILE, index=False, compression='snappy')
            print("✅ 历史数据归一化完成")
            existing_df = cleaned_df

        existing_dates = existing_df['trade_date'].unique()
        latest_existing = max(existing_dates)
        print(f"✅ 现有数据最新日期: {latest_existing}")
        print(f"   数据行数: {len(existing_df):,}")
        print(f"   股票数量: {existing_df['ts_code'].nunique()}")
    except Exception as e:
        print(f"❌ 读取现有数据失败: {e}")
        return False
    
    # 3. 确定需要更新的日期
    auto_target_date = get_latest_trade_date()
    target_date = auto_target_date
    manual_target_mode = False
    if target_date_override:
        if not validate_date_yyyymmdd(target_date_override):
            print(f"❌ 无效日期格式: {target_date_override}，应为 YYYYMMDD")
            return False
        target_date = target_date_override
        manual_target_mode = True

    print(f"\n目标更新日期: {target_date}")
    
    # 确保类型一致进行比较
    latest_existing_str = str(latest_existing)[:10].replace('-', '')  # 转换为YYYYMMDD格式
    
    # 手动模式允许“补历史某天”，即便该日期早于当前最新日期
    if (target_date <= latest_existing_str) and (not manual_target_mode):
        print(f"✅ 数据已是最新（已包含 {target_date}），无需更新")
        refresh_stock_metadata(meta_file=META_FILE, cache_file=INDUSTRY_CACHE_FILE)
        return True
    
    # 4. 检测数据缺口
    latest_dt = datetime.datetime.strptime(latest_existing_str, '%Y%m%d')
    next_day_str = (latest_dt + datetime.timedelta(days=1)).strftime('%Y%m%d')
    has_multi_day_gap = next_day_str < target_date
    backfill_single_date_mode = manual_target_mode and (target_date <= latest_existing_str)
    
    # 5. 检查更新时机（仅对单日更新生效，多日缺口历史数据随时可下载）
    now = datetime.datetime.now()
    current_hour = now.hour
    
    if current_hour < 18 and (not manual_target_mode):
        if has_multi_day_gap:
            # 多日缺口：历史数据随时可下载，仅提醒今日数据可能不完整
            print(f"\n💡 检测到多日数据缺口，历史数据随时可补充")
            if current_hour < 15:
                # 今天还没收盘，下载截止到昨天
                yesterday = previous_trade_day(now.date(), parquet_file=PARQUET_FILE)
                target_date = yesterday.strftime('%Y%m%d')
                print(f"   市场未收盘，本次更新截至昨日: {target_date}")
                if target_date <= latest_existing_str:
                    print(f"✅ 历史数据已是最新，今日数据请收盘后再更新")
                    refresh_stock_metadata(meta_file=META_FILE, cache_file=INDUSTRY_CACHE_FILE)
                    return True
        else:
            # 单日更新：需要今日数据，检查时间
            print(f"\n⚠️ 当前时间: {now.strftime('%H:%M')}")
            print("提示: A股行情数据通常在收盘后(18:00)才完全更新到API")
            if current_hour < 15:
                print("  - 市场尚未收盘，无法获取今日数据")
                print("  - 建议: 15:30后再运行")
                return False
            else:
                print("  - 市场已收盘，但数据可能尚未更新")
                print("  - 建议: 18:00-19:00之间运行更稳定")
                if not sys.stdin.isatty():
                    print("\n检测到非交互环境，跳过人工确认并退出（避免任务阻塞）")
                    return False
                response = input("\n是否继续尝试下载? (y/n): ").lower()
                if response != 'y':
                    print("取消更新，请稍后再试")
                    return False

    # 若上面调整了 target_date，需要基于最终目标日期重算 gap 判断
    has_multi_day_gap = next_day_str < target_date

    if backfill_single_date_mode:
        # ===== 手动补指定历史交易日 =====
        print(f"\n📢 手动补数模式：补指定交易日 {target_date}")
        codes = get_stock_list()
        if not codes:
            return False

        new_data = []
        success_count = 0
        fail_count = 0
        mode_text = "腾讯优先+东财回退" if PREFER_TX_RANGE else "东财"
        print(f"   历史单日补数: {target_date} ({mode_text}, 并发 {RANGE_WORKERS})")
        with ThreadPoolExecutor(max_workers=RANGE_WORKERS) as executor:
            future_to_code = {
                executor.submit(download_stock_daterange, code, target_date, target_date): code
                for code in codes
            }
            for future in tqdm(as_completed(future_to_code), total=len(future_to_code), desc="补充下载进度"):
                try:
                    res = future.result()
                    if res is not None and not res.empty:
                        new_data.append(res)
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception:
                    fail_count += 1

        total_codes = len(codes)
        success_ratio = (success_count / total_codes) if total_codes else 0.0
        print(f"   历史单日补数成功率: {success_ratio:.1%} ({success_count}/{total_codes})")
        if success_ratio < MIN_RANGE_SUCCESS_RATIO:
            print(f"❌ 历史单日补数成功率过低（阈值 {MIN_RANGE_SUCCESS_RATIO:.0%}），终止更新以避免污染主数据")
            return False

        if not new_data:
            print("❌ 未能下载到任何新数据")
            return False

        new_df = pd.concat(new_data, ignore_index=True)
        print(f"\n✅ 成功下载 {success_count} 只股票，失败 {fail_count} 只")
    elif has_multi_day_gap:
        # ===== 多日缺口模式：逐股下载日期范围 =====
        print(f"\n⚠️ 检测到多日数据缺口!")
        print(f"   已有数据截至: {latest_existing_str}")
        print(f"   目标更新至:   {target_date}")
        print(f"   需要补充:     {next_day_str} ~ {target_date}")
        print(f"\n📢 使用多日缺口补数模式...")

        codes = get_stock_list()
        if not codes:
            return False

        new_data = []
        success_count = 0
        fail_count = 0

        # 当目标日期是“今天”时，历史缺口先补到“昨日”，再用批量接口补“今日”
        today_str = datetime.date.today().strftime('%Y%m%d')
        range_end_date = target_date
        append_today_via_batch = False
        if target_date == today_str:
            yesterday_str = get_previous_trade_date(datetime.date.today()).strftime('%Y%m%d')
            if next_day_str <= yesterday_str:
                range_end_date = yesterday_str
            append_today_via_batch = True

        if next_day_str <= range_end_date:
            mode_text = "腾讯优先+东财回退" if PREFER_TX_RANGE else "东财"
            print(f"   历史区间补数: {next_day_str} ~ {range_end_date} ({mode_text}, 并发 {RANGE_WORKERS})")
            with ThreadPoolExecutor(max_workers=RANGE_WORKERS) as executor:
                future_to_code = {
                    executor.submit(download_stock_daterange, code, next_day_str, range_end_date): code
                    for code in codes
                }
                for future in tqdm(as_completed(future_to_code), total=len(future_to_code), desc="补充下载进度"):
                    try:
                        res = future.result()
                        if res is not None and not res.empty:
                            new_data.append(res)
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception:
                        fail_count += 1

            # 历史区间补数质量检查：成功率过低时直接失败，避免写入“看似成功”的坏数据
            total_codes = len(codes)
            success_ratio = (success_count / total_codes) if total_codes else 0.0
            print(f"   历史区间补数成功率: {success_ratio:.1%} ({success_count}/{total_codes})")
            if success_ratio < MIN_RANGE_SUCCESS_RATIO:
                print(f"❌ 历史区间补数成功率过低（阈值 {MIN_RANGE_SUCCESS_RATIO:.0%}），终止更新以避免污染主数据")
                return False

        # 今日数据优先走批量接口（更快）
        if append_today_via_batch:
            print(f"   今日数据补数: {target_date} (批量接口)")
            df_spot, rename_map, source_name = fetch_batch_spot_data()
            if df_spot is not None and not df_spot.empty and rename_map is not None:
                today_df = df_spot.rename(columns=rename_map).copy()
                today_df['trade_date'] = target_date
                target_cols = ['ts_code', 'trade_date', 'open', 'high', 'low',
                              'close', 'vol', 'amount', 'pct_chg', 'turnover_rate']
                available_cols = [c for c in target_cols if c in today_df.columns]
                today_df = today_df[available_cols]

                today_df, norm_info = normalize_spot_volume_unit(today_df, source_name=source_name or "")
                if norm_info.get("converted"):
                    print(f"   ℹ️ [{source_name}] 成交量单位已归一化（股->手），ratio中位数={norm_info.get('ratio_median'):.2f}")
                elif norm_info.get("ratio_median") is not None:
                    print(f"   ℹ️ [{source_name}] 成交量单位检测 ratio中位数={norm_info.get('ratio_median'):.2f}（无需转换）")

                today_df = today_df[today_df['close'].notna() & (today_df['close'] > 0)]
                if not today_df.empty:
                    new_data.append(today_df)
                    print(f"   ✅ [{source_name}] 今日批量补数成功: {len(today_df)} 只")
                else:
                    print("   ⚠️ 今日批量接口返回为空，跳过今日补数")
            else:
                print("   ⚠️ 今日批量接口不可用，跳过今日补数")

        if not new_data:
            print("❌ 未能下载到任何新数据")
            return False
        
        new_df = pd.concat(new_data, ignore_index=True)
        
        # 统计下载的日期分布
        date_counts = new_df['trade_date'].value_counts().sort_index()
        print(f"\n✅ 成功下载 {success_count} 只股票，失败 {fail_count} 只")
        print(f"   覆盖交易日:")
        for d, cnt in date_counts.items():
            print(f"     {d}: {cnt} 只股票")
    
    else:
        # ===== 单日更新模式：使用批量API（极速） =====
        print(f"📊 需要下载 {target_date} 的数据")
        print(f"\n📢 使用批量API下载 (极速模式)...")

        df_spot, rename_map, source_name = fetch_batch_spot_data()

        if df_spot is not None and not df_spot.empty and rename_map is not None:
            print(f"✅ [{source_name}] 获取到 {len(df_spot)} 只股票的实时数据")

            new_df = df_spot.rename(columns=rename_map)
            new_df['trade_date'] = target_date
            
            target_cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 
                          'close', 'vol', 'amount', 'pct_chg', 'turnover_rate']
            available_cols = [c for c in target_cols if c in new_df.columns]
            new_df = new_df[available_cols]

            new_df, norm_info = normalize_spot_volume_unit(new_df, source_name=source_name or "")
            if norm_info.get("converted"):
                print(f"ℹ️ [{source_name}] 成交量单位已归一化（股->手），ratio中位数={norm_info.get('ratio_median'):.2f}")
            elif norm_info.get("ratio_median") is not None:
                print(f"ℹ️ [{source_name}] 成交量单位检测 ratio中位数={norm_info.get('ratio_median'):.2f}（无需转换）")
            
            new_df = new_df[new_df['close'].notna() & (new_df['close'] > 0)]
            
            print(f"✅ 有效数据: {len(new_df)} 只股票")
            
        else:
            # 批量API失败，回退到逐个下载模式
            print("\n❌ 批量接口均失败，回退到逐个下载模式...")
            
            codes = get_stock_list()
            if not codes:
                return False
                
            new_data = []
            for code in tqdm(codes, desc="下载进度"):
                try:
                    res = safe_download_single_day(code, target_date)
                    if res is not None and not res.empty:
                        new_data.append(res)
                except Exception:
                    pass
            
            if not new_data:
                print("❌ 未能下载到任何新数据")
                return False
                
            new_df = pd.concat(new_data, ignore_index=True)
    
    print(f"✅ 新数据行数: {len(new_df):,}")

    # 标准化关键字段，避免日期/代码混格式导致下游筛选异常
    new_df['trade_date'] = normalize_trade_date_series(new_df['trade_date'])
    new_df['ts_code'] = normalize_ts_code_series(new_df['ts_code'])
    new_df = new_df.dropna(subset=['trade_date', 'ts_code'])
    new_df = new_df.drop_duplicates(subset=['ts_code', 'trade_date'], keep='last')
    
    # 7. 数据类型优化
    numeric_cols = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg', 'turnover_rate']
    for col in numeric_cols:
        if col in new_df.columns:
            new_df[col] = pd.to_numeric(new_df[col], errors='coerce')

    # 7.1 OHLC 缺失回填（防止批量接口 open 全缺失）
    new_df = backfill_ohlc_fields(new_df, existing_df)

    # 7.2 成交量缺失回填（基于 amount/close 推算，单位手）
    if {'vol', 'amount', 'close'}.issubset(new_df.columns):
        miss_vol = new_df['vol'].isna() | (new_df['vol'] <= 0)
        fillable = miss_vol & new_df['amount'].notna() & (new_df['amount'] > 0) & new_df['close'].notna() & (new_df['close'] > 0)
        if fillable.any():
            new_df.loc[fillable, 'vol'] = new_df.loc[fillable, 'amount'] / (new_df.loc[fillable, 'close'] * 100.0)
            print(f"ℹ️ 成交量缺失已回填: {int(fillable.sum())} 行（基于 amount/close 估算）")

    # 7.5 覆盖门禁：任一新增交易日低于阈值则拒绝写入
    if MIN_DAILY_COVERAGE > 0:
        date_coverage = new_df.groupby('trade_date')['ts_code'].nunique().sort_index()
        low_cov = date_coverage[date_coverage < MIN_DAILY_COVERAGE]
        if not low_cov.empty:
            print(f"\n❌ 覆盖门禁触发（阈值: {MIN_DAILY_COVERAGE}）")
            for d, cnt in low_cov.items():
                print(f"   {d}: {cnt} 只股票")
            print("   为避免污染主数据，本次更新已终止且不会写入 parquet。")
            return False
    
    # 8. 合并到现有数据
    print("\n合并到现有数据...")
    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    
    # 去重（以防万一）
    combined_df = combined_df.drop_duplicates(subset=['ts_code', 'trade_date'], keep='last')
    
    # 排序
    combined_df = combined_df.sort_values(['ts_code', 'trade_date'])
    
    # 优化类型
    combined_df['ts_code'] = normalize_ts_code_series(combined_df['ts_code']).astype('category')
    
    print(f"✅ 合并后总行数: {len(combined_df):,}")
    print(f"   日期范围: {combined_df['trade_date'].min()} - {combined_df['trade_date'].max()}")
    
    # 9. 保存
    print(f"\n保存到 {PARQUET_FILE}...")
    try:
        combined_df.to_parquet(PARQUET_FILE, index=False, compression='snappy')
        print("✅ 数据保存成功!")
    except Exception as e:
        print(f"❌ 保存失败: {e}")
        return False
    
    # 10. 更新元数据（可选）
    refresh_stock_metadata(meta_file=META_FILE, cache_file=INDUSTRY_CACHE_FILE)
    
    print("\n" + "=" * 70)
    print("✅ 增量更新完成!")
    print("=" * 70)
    return True


def main():
    parser = argparse.ArgumentParser(description="MFTS 增量数据更新")
    parser.add_argument(
        "--target-date",
        type=str,
        help="指定更新/补数到某个日期(YYYYMMDD)。可用于补历史某天。",
    )
    args = parser.parse_args()

    success = incremental_update(target_date_override=args.target_date)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
