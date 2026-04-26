# -*- coding: utf-8 -*-
"""
MFTS v6.1 核心选股引擎
完整复刻 TradingView Pine Script MFTS v6.1 指标
"""

import pandas as pd
import numpy as np
import argparse
import os
import sys
import warnings
from pathlib import Path

# Suppress warnings
warnings.filterwarnings('ignore')

# 添加项目根目录到路径
BASE_DIR = os.environ.get('MFTS_BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

# 导入配置和日志模块
try:
    from config.settings import MFTSConfig, PathConfig
    from utils.market_regime import detect_market_regime
    from utils.code_utils import normalize_ts_code, normalize_ts_code_series, limit_ratio_for_stock, limit_ratio_vectorized
    from utils.logger import get_logger, LogContext
    from utils.output_paths import ensure_output_dirs, write_dual_csv
    
    # 使用配置
    DATA_DIR = str(PathConfig.DATA_DIR)
    OUTPUT_DIR = str(PathConfig.OUTPUT_DIR)
    PARQUET_FILE = str(PathConfig.PARQUET_FILE)
    META_FILE = str(PathConfig.META_FILE)
    START_DATE_FILTER = MFTSConfig.START_DATE_FILTER
    PARAMS = MFTSConfig.to_dict()
    
    logger = get_logger(__name__)
except ImportError:
    # 降级模式：配置模块不可用时使用默认值
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    logger = logging.getLogger(__name__)
    logger.warning("Config module not available, using defaults")
    
    DATA_DIR = os.path.join(BASE_DIR, "data")
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    PARQUET_FILE = os.path.join(DATA_DIR, "daily_all.parquet")
    if os.path.exists(os.path.join(DATA_DIR, "daily_all_5y.parquet")):
        PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")
    META_FILE = os.path.join(DATA_DIR, "stock_info.csv")
    START_DATE_FILTER = '20240101'
    PARAMS = {
        'bias_len': 20,
        'buy_deep': -10.0,
        'buy_mid': -7.0,
        'buy_light': -5.0,
        'z_buy_deep': -1.96,
        'z_buy_mid': -1.50,
        'pass_score_threshold': 4.0,
        'liquidity_threshold': 50000000,
        'strict_limit_filter': True,
        'enable_vwap_filter': False,
        'new_stock_days': 60,
        'enable_market_regime_filter': True,
        'market_panic_down_ratio': 0.75,
        'market_panic_median_chg': -1.50,
        'market_panic_oversold_ratio': 0.20,
        'l1_alpha_penalty_in_panic': 1.5,
    }
    from utils.output_paths import ensure_output_dirs, write_dual_csv
    from utils.market_regime import detect_market_regime
    from utils.code_utils import normalize_ts_code, normalize_ts_code_series, limit_ratio_for_stock, limit_ratio_vectorized

OUTPUT_FILE = os.path.join(OUTPUT_DIR, "mfts_v6.1_scan_result.csv")


def load_data():
    """加载股票数据"""
    if not os.path.exists(PARQUET_FILE):
        logger.error(f"Data file not found at {PARQUET_FILE}")
        return None

    logger.info(f"Loading data from {PARQUET_FILE}...")
    df = None
    
    # 方法1: 尝试使用整数过滤（本地格式）
    try:
        start_date_int = int(START_DATE_FILTER)
        df = pd.read_parquet(PARQUET_FILE, filters=[('trade_date', '>=', start_date_int)])
        logger.debug(f"Loaded {len(df)} rows with int filter")
    except Exception as e:
        logger.debug(f"Int filter failed: {type(e).__name__}")
    
    # 方法2: 尝试使用字符串过滤（云端格式）
    if df is None:
        try:
            df = pd.read_parquet(PARQUET_FILE, filters=[('trade_date', '>=', START_DATE_FILTER)])
            logger.debug(f"Loaded {len(df)} rows with str filter")
        except Exception as e:
            logger.debug(f"Str filter failed: {type(e).__name__}")
    
    # 方法3: 加载全部数据后过滤（最慢但最可靠）
    if df is None:
        logger.warning("Filter failed, loading full data...")
        df = pd.read_parquet(PARQUET_FILE)
        try:
            df = df[df['trade_date'].astype(str) >= START_DATE_FILTER]
        except Exception:
            pass  # 保留所有数据

    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    # [Fix] Convert category to string to avoid fillna(0) error
    if 'ts_code' in df.columns:
        df['ts_code'] = normalize_ts_code_series(df['ts_code'])
        df = df[df['ts_code'] != '']

    df = df.sort_values(['ts_code', 'trade_date'])
    
    # [Fix] Explicit Timezone Handling (Asia/Shanghai)
    if df['trade_date'].dt.tz is None:
        df['trade_date'] = df['trade_date'].dt.tz_localize('Asia/Shanghai')
    
    logger.info(f"Loaded {len(df)} rows, {df['ts_code'].nunique()} stocks")
    return df


def load_metadata():
    """加载股票元数据"""
    if not os.path.exists(META_FILE):
        logger.warning(f"Metadata file not found: {META_FILE}")
        return {}
    try:
        meta_df = pd.read_csv(META_FILE, dtype={'ts_code': str})
        if meta_df.empty:
            return {}
        code_col = "ts_code" if "ts_code" in meta_df.columns else ("代码" if "代码" in meta_df.columns else None)
        if code_col is None:
            logger.warning("Metadata missing ts_code/代码 column")
            return {}
        name_col = "name" if "name" in meta_df.columns else ("名称" if "名称" in meta_df.columns else None)
        ind_col = "industry" if "industry" in meta_df.columns else ("行业" if "行业" in meta_df.columns else None)

        work = pd.DataFrame()
        work["ts_code"] = normalize_ts_code_series(meta_df[code_col])
        work["name"] = meta_df[name_col].astype(str).fillna("").str.strip() if name_col else ""
        work["industry"] = meta_df[ind_col].astype(str).fillna("").str.strip() if ind_col else ""
        work = work[work["ts_code"] != ""]
        work = work.drop_duplicates(subset=["ts_code"], keep="last")
        # Convert to recursive dict for fast lookup: code -> {'name': ..., 'industry': ...}
        result = work.set_index('ts_code').to_dict('index')
        logger.debug(f"Loaded metadata for {len(result)} stocks")
        return result
    except (pd.errors.EmptyDataError, pd.errors.ParserError, OSError) as e:
        logger.error(f"Metadata load failed: {e}")
        return {}


def get_limit_ratio(ts_code, name=''):
    """
    [v2.0 新增] 根据股票代码识别涨跌停幅度
    Pine Script Lines 181-219 对应逻辑
    """
    return float(limit_ratio_for_stock(ts_code, name))


def _group_ewm_mean(series, group_keys, alpha=None, span=None, min_periods=0, adjust=False):
    """按股票分组执行 ewm().mean()，避免 transform(lambda ...) 的 Python 开销。"""
    return (
        series.groupby(group_keys, observed=True, sort=False)
        .ewm(alpha=alpha, span=span, min_periods=min_periods, adjust=adjust)
        .mean()
        .reset_index(level=0, drop=True)
    )


def _group_rolling_mean(series, group_keys, window, min_periods=None):
    min_periods = window if min_periods is None else min_periods
    return (
        series.groupby(group_keys, observed=True, sort=False)
        .rolling(window, min_periods=min_periods)
        .mean()
        .reset_index(level=0, drop=True)
    )


def _group_rolling_std(series, group_keys, window, min_periods=None, ddof=1):
    min_periods = window if min_periods is None else min_periods
    return (
        series.groupby(group_keys, observed=True, sort=False)
        .rolling(window, min_periods=min_periods)
        .std(ddof=ddof)
        .reset_index(level=0, drop=True)
    )


def _group_rolling_min(series, group_keys, window, min_periods=None):
    min_periods = window if min_periods is None else min_periods
    return (
        series.groupby(group_keys, observed=True, sort=False)
        .rolling(window, min_periods=min_periods)
        .min()
        .reset_index(level=0, drop=True)
    )


def _group_rolling_max(series, group_keys, window, min_periods=None):
    min_periods = window if min_periods is None else min_periods
    return (
        series.groupby(group_keys, observed=True, sort=False)
        .rolling(window, min_periods=min_periods)
        .max()
        .reset_index(level=0, drop=True)
    )


def _group_rolling_sum(series, group_keys, window, min_periods=None):
    min_periods = window if min_periods is None else min_periods
    return (
        series.groupby(group_keys, observed=True, sort=False)
        .rolling(window, min_periods=min_periods)
        .sum()
        .reset_index(level=0, drop=True)
    )


def _group_rolling_corr(series_x, series_y, group_keys, window, min_periods=None):
    min_periods = window if min_periods is None else min_periods
    mean_x = _group_rolling_mean(series_x, group_keys, window, min_periods=min_periods)
    mean_y = _group_rolling_mean(series_y, group_keys, window, min_periods=min_periods)
    mean_xy = _group_rolling_mean(series_x * series_y, group_keys, window, min_periods=min_periods)
    mean_x2 = _group_rolling_mean(series_x * series_x, group_keys, window, min_periods=min_periods)
    mean_y2 = _group_rolling_mean(series_y * series_y, group_keys, window, min_periods=min_periods)
    cov_xy = mean_xy - mean_x * mean_y
    var_x = (mean_x2 - mean_x * mean_x).clip(lower=0.0)
    var_y = (mean_y2 - mean_y * mean_y).clip(lower=0.0)
    denom = np.sqrt(var_x * var_y)
    corr = cov_xy / denom
    corr = corr.where(denom > 0)
    return corr


def calc_indicators(df):
    """计算 MFTS v6.1 所有技术指标"""
    logger.info("Calculating MFTS v6.1 Indicators (Optimized v2.0)...")

    # 先做数值列清洗，避免上游列类型/缺失导致滚动指标失效
    for col in ['open', 'high', 'low', 'close', 'vol', 'amount']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 兼容部分历史/补数数据缺失成交量：
    # 若 amount 与 close 可用，按 A 股常用关系估算 vol(手) = amount / (close * 100)
    if {'vol', 'amount', 'close'}.issubset(df.columns):
        miss_vol = df['vol'].isna() | (df['vol'] <= 0)
        fillable = miss_vol & df['amount'].notna() & (df['amount'] > 0) & df['close'].notna() & (df['close'] > 0)
        if fillable.any():
            df.loc[fillable, 'vol'] = df.loc[fillable, 'amount'] / (df.loc[fillable, 'close'] * 100.0)

    group_keys = df['ts_code']
    grouped = df.groupby('ts_code', observed=True, sort=False)
    close = df['close']
    high = df['high']
    low = df['low']
    vol = df['vol']
    amount = df['amount']
    open_px = df['open']

    # 基础均线与成交量
    df['ma5'] = _group_rolling_mean(close, group_keys, 5)
    df['ma20'] = _group_rolling_mean(close, group_keys, 20)
    df['ma120'] = _group_rolling_mean(close, group_keys, 120)
    df['ma250'] = _group_rolling_mean(close, group_keys, 250)
    df['vol_ma5'] = _group_rolling_mean(vol, group_keys, 5)
    df['vol_ma20'] = _group_rolling_mean(vol, group_keys, 20)
    df['amount_ma20'] = _group_rolling_mean(amount, group_keys, 20)  # 成交额均值

    # Shifted values for logic checks
    df['close_1'] = grouped['close'].shift(1)
    df['close_5'] = grouped['close'].shift(5)
    df['close_10'] = grouped['close'].shift(10)
    df['close_20'] = grouped['close'].shift(20)
    df['open_1'] = grouped['open'].shift(1)
    df['vol_1'] = grouped['vol'].shift(1)
    df['high_1'] = grouped['high'].shift(1)
    df['low_1'] = grouped['low'].shift(1)

    # ------------------------------------------------------
    # [Core] Z-Score & BIAS (Log Space) - "回归诚实的 Z-Score"
    # ------------------------------------------------------
    df['log_close'] = np.log(close)
    df['log_ma'] = _group_rolling_mean(df['log_close'], group_keys, PARAMS['bias_len'])
    df['log_std'] = _group_rolling_std(df['log_close'], group_keys, PARAMS['bias_len'], ddof=0)

    # Handle division by zero
    df['z_score'] = np.where(df['log_std'] > 0, (df['log_close'] - df['log_ma']) / df['log_std'], 0.0)

    df['ma_bias_base'] = np.exp(df['log_ma'])
    df['bias'] = (df['close'] - df['ma_bias_base']) / df['ma_bias_base'] * 100

    # BIAS 13 (Independent Factor)
    ma13 = _group_rolling_mean(close, group_keys, 13)
    df['bias13'] = (close - ma13) / ma13 * 100

    # ------------------------------------------------------
    # [Alpha] Momentum & Correlation - "v6.1 核心改进"
    # ------------------------------------------------------
    # 动量因子
    df['mom_5'] = grouped['close'].pct_change(5)
    df['mom_20'] = grouped['close'].pct_change(20)

    # 量价相关性 (PV Correlation)
    # [Audit Fix P0-1] 使用 grouped shift 避免跨股票数据污染
    df['log_ret'] = np.log(close / df['close_1']).fillna(0)
    df['vol_safe_prev'] = df['vol_1'].replace(0, np.nan).fillna(vol)
    df['log_vol_chg'] = np.log(vol / df['vol_safe_prev']).fillna(0)

    df['pv_corr_5'] = _group_rolling_corr(df['log_ret'], df['log_vol_chg'], group_keys, 5)
    df['pv_corr_20'] = _group_rolling_corr(df['log_ret'], df['log_vol_chg'], group_keys, 20)

    # 52周位置 (Percent Rank)
    df['high_52w'] = _group_rolling_max(high, group_keys, 252)
    df['low_52w'] = _group_rolling_min(low, group_keys, 252)
    df['high_250'] = _group_rolling_max(high, group_keys, 250)  # [v2.0] 用于高位判断
    df['pos_52w'] = (close - df['low_52w']) / (df['high_52w'] - df['low_52w']) * 100

    # [v2.0 新增] 高位过滤计算
    df['distance_from_high_pct'] = (df['high_250'] - close) / df['high_250'] * 100
    df['is_high_position'] = df['distance_from_high_pct'] < 10  # 距离高点 10% 内

    # ------------------------------------------------------
    # [Risk] Smart Knife / Wyckoff / Patterns
    # ------------------------------------------------------
    # CLV for Smart Knife
    range_hl = high - low
    df['clv'] = np.where(range_hl > 0, ((close - low) - (high - close)) / range_hl, 0.0)

    # Spread for Wyckoff
    df['spread'] = range_hl
    df['avg_spread'] = _group_rolling_mean(df['spread'], group_keys, 20)

    # [v2.0 新增] Wyckoff VPA 因子
    df['is_wide_spread'] = df['spread'] > df['avg_spread'] * 1.5
    df['is_narrow_spread'] = df['spread'] < df['avg_spread'] * 0.7
    df['is_high_volume'] = vol > df['vol_ma20'] * 1.5
    df['is_low_volume'] = vol < df['vol_ma20'] * 0.7

    # 收盘位置 (用于 Stopping Volume)
    df['close_position'] = np.where(range_hl > 0, (close - low) / range_hl, 0.5)

    # [v2.0 新增] 下影线比例 (用于恐慌放量验证)
    df['lower_wick'] = np.minimum(close, open_px) - low
    df['lower_wick_pct'] = np.where(range_hl > 0, df['lower_wick'] / range_hl, 0.0)

    # ------------------------------------------------------
    # [Oscillators] RSI, MACD, KDJ, ATR
    # ------------------------------------------------------
    # RSI 14
    delta = grouped['close'].diff()
    gain = delta.clip(lower=0).fillna(0.0)
    loss = (-delta.clip(upper=0)).fillna(0.0)
    avg_gain = _group_ewm_mean(gain, group_keys, alpha=1 / 14, min_periods=14, adjust=False)
    avg_loss = _group_ewm_mean(loss, group_keys, alpha=1 / 14, min_periods=14, adjust=False)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = _group_ewm_mean(df['close'], group_keys, span=12, adjust=False)
    ema26 = _group_ewm_mean(df['close'], group_keys, span=26, adjust=False)
    df['macd'] = ema12 - ema26
    df['macd_signal'] = _group_ewm_mean(df['macd'], group_keys, span=9, adjust=False)
    df['macd_hist'] = df['macd'] - df['macd_signal']
    df['macd_hist_prev'] = df['macd_hist'].groupby(group_keys, observed=True, sort=False).shift(1)

    # KDJ
    low_9 = _group_rolling_min(low, group_keys, 9)
    high_9 = _group_rolling_max(high, group_keys, 9)
    df['rsv'] = (close - low_9) / (high_9 - low_9) * 100
    df['rsv'] = df['rsv'].fillna(50)

    df['k_val'] = _group_rolling_mean(df['rsv'], group_keys, 3)
    df['d_val'] = _group_rolling_mean(df['k_val'], group_keys, 3)
    df['j_val'] = 3 * df['k_val'] - 2 * df['d_val']

    # MFI
    tp = (high + low + close) / 3
    prev_tp = tp.groupby(group_keys, observed=True, sort=False).shift(1)
    rmf = tp * vol
    pos_flow = pd.Series(np.where(tp > prev_tp, rmf, 0.0), index=df.index)
    neg_flow = pd.Series(np.where(tp < prev_tp, rmf, 0.0), index=df.index)
    pos_sum = _group_rolling_sum(pos_flow, group_keys, 14)
    neg_sum = _group_rolling_sum(neg_flow, group_keys, 14)
    df['mfi'] = 100 - (100 / (1 + pos_sum / neg_sum.replace(0, np.nan)))

    # BB
    std_bb = _group_rolling_std(close, group_keys, 20)
    upper_bb = df['ma20'] + 2 * std_bb
    lower_bb = df['ma20'] - 2 * std_bb
    df['bb_pos'] = (close - lower_bb) / (upper_bb - lower_bb) * 100

    # ATR & Volatility Ratio for Adaptive Thresholds
    tr1 = high - low
    tr2 = (df['high'] - df['close_1']).abs()
    tr3 = (df['low'] - df['close_1']).abs()
    df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['atr'] = _group_rolling_mean(df['tr'], group_keys, 14)

    df['atr_percent'] = (df['atr'] / close) * 100
    df['atr_ma_60'] = _group_rolling_mean(df['atr_percent'], group_keys, 60)
    df['volatility_ratio'] = df['atr_percent'] / df['atr_ma_60'].replace(0, 0.01)
    df['volatility_ratio'] = df['volatility_ratio'].clip(0.7, 1.5)

    # ADX
    up = high - df['high_1']
    down = df['low_1'] - low
    df['plus_dm'] = np.where((up > down) & (up > 0), up, 0.0)
    df['minus_dm'] = np.where((down > up) & (down > 0), down, 0.0)

    tr_smooth = _group_ewm_mean(df['tr'], group_keys, alpha=1 / 14, adjust=False)
    plus_dm_smooth = _group_ewm_mean(df['plus_dm'], group_keys, alpha=1 / 14, adjust=False)
    minus_dm_smooth = _group_ewm_mean(df['minus_dm'], group_keys, alpha=1 / 14, adjust=False)

    df['plus_di'] = 100 * plus_dm_smooth / tr_smooth
    df['minus_di'] = 100 * minus_dm_smooth / tr_smooth

    df['dx'] = 100 * (df['plus_di'] - df['minus_di']).abs() / (df['plus_di'] + df['minus_di'])
    df['adx'] = _group_ewm_mean(df['dx'], group_keys, alpha=1 / 14, adjust=False)

    # High 20 Prev (for Breakout)
    df['high_20_prev'] = _group_rolling_max(df['high_1'], group_keys, 20)

    # [v2.0 新增] OBV 计算
    df['obv_sign'] = np.sign(df['close'] - df['close_1']).fillna(0)
    df['obv_sign'] = np.where(df['close'] == df['close_1'], 0, df['obv_sign'])
    df['obv_delta'] = vol * df['obv_sign']
    df['obv'] = grouped['obv_delta'].cumsum()
    df['obv_ma'] = _group_rolling_mean(df['obv'], group_keys, 20)

    # OBV 背离检测所需的滚动极值
    df['low_20'] = _group_rolling_min(low, group_keys, 20)
    df['low_20_prev'] = df['low_20'].groupby(group_keys, observed=True, sort=False).shift(1)
    df['obv_low_20'] = _group_rolling_min(df['obv'], group_keys, 20)
    df['obv_low_20_prev'] = df['obv_low_20'].groupby(group_keys, observed=True, sort=False).shift(1)

    # [v2.0 新增] VWAP 计算
    # A股日线常用口径: vol 为“手”、amount 为“元”，均价应为 amount / (vol * 100)
    df['vwap'] = np.where(vol > 0, amount / (vol * 100.0), np.nan)

    # [v2.0 新增] 上市天数 (用行数近似)
    df['days_listed'] = grouped.cumcount() + 1

    # ══════════════════════════════════════════════════════════
    # [v3.0] 正交因子 - 与现有超跌因子低相关的新维度
    # ══════════════════════════════════════════════════════════

    # 1. Smart Money Flow (聪明钱流向)
    #    CLV (Close Location Value) × 成交量的滚动累积
    #    高收盘位放量 → 主力吸筹；低收盘位放量 → 主力出货
    df['smart_money_delta'] = df['clv'] * df['vol']
    df['smart_money_5d'] = _group_rolling_sum(df['smart_money_delta'], group_keys, 5, min_periods=1)
    amount_5d = _group_rolling_sum(amount, group_keys, 5, min_periods=1)
    df['smart_money_ratio'] = np.where(
        amount_5d > 0, df['smart_money_5d'] / amount_5d, 0.0
    )

    # 2. Relative Strength vs Market (个股相对强弱)
    #    剥离市场 Beta，留下纯 Alpha
    df['market_median_ret'] = df.groupby('trade_date')['pct_chg'].transform('median')
    df['relative_strength'] = df['pct_chg'] - df['market_median_ret']
    df['rs_5d'] = _group_rolling_sum(df['relative_strength'], group_keys, 5, min_periods=1)
    df['rs_20d'] = _group_rolling_sum(df['relative_strength'], group_keys, 20, min_periods=5)

    # 3. Volatility Compression (波动率压缩)
    #    低波动 → 高波动的转换点往往预示大行情启动
    atr5 = _group_rolling_mean(df['atr_percent'], group_keys, 5, min_periods=3)
    atr20 = _group_rolling_mean(df['atr_percent'], group_keys, 20, min_periods=10)
    df['vol_compression'] = np.where(atr20 > 0, atr5 / atr20, 1.0)

    # 4. Overnight Gap Z-Score (隔夜跳空标准化)
    #    异常的隔夜跳空往往包含未公开信息（盈利公告、重大事件）
    df['overnight_gap'] = open_px / grouped['close'].shift(1) - 1
    gap_mean = _group_rolling_mean(df['overnight_gap'], group_keys, 60, min_periods=20)
    gap_std = _group_rolling_std(df['overnight_gap'], group_keys, 60, min_periods=20)
    df['gap_zscore'] = np.where(gap_std > 0, (df['overnight_gap'] - gap_mean) / gap_std, 0.0)

    # 5. 量价背离强度 (Volume-Price Divergence)
    #    价格创新低但成交量递减 → 空方力竭
    close_20min = _group_rolling_min(close, group_keys, 20)
    vol_20mean_current = _group_rolling_mean(vol, group_keys, 20, min_periods=5)
    vol_20mean_prev = _group_rolling_mean(grouped['vol'].shift(20), group_keys, 20, min_periods=5)
    df['vp_divergence'] = np.where(
        (df['close'] <= close_20min * 1.02) & (vol_20mean_prev > 0),
        vol_20mean_current / vol_20mean_prev - 1,
        0.0
    )

    return df


def calculate_alpha_score(row, adaptive_buy_deep, adaptive_buy_mid, dynamic_z_deep):
    """
    完全复刻 Pine Script 'calc_alpha_voting' (v2.0 优化版)
    """
    points = 0.0

    # --- 0. 扣分项 / 风控 ---
    # Smart Knife (智能飞刀)
    is_clv_low = row['clv'] < -0.7
    is_range_wide = row['spread'] > row['avg_spread'] * 1.5
    is_falling_knife = is_clv_low and is_range_wide and row['close'] < row['open']

    # Liquidity Lock Alpha Penalty
    is_liq_lock = (row['close'] < row['close_1'] * 0.92) and (row['vol'] < row['vol_ma20'] * 0.1)

    if is_liq_lock:
        points -= 10.0
    elif is_falling_knife:
        points -= 5.0

    if is_falling_knife or is_liq_lock:
        return points  # Early exit logic in Pine implies these suppress positive factors

    # --- A. 动量因子 (LightGBM Strongest) ---
    if row['mom_5'] < -0.15:
        points += 2.0
    elif row['mom_5'] < -0.08:
        points += 1.2
    elif row['mom_5'] < -0.03:
        points += 0.5

    if row['mom_20'] < -0.25:
        points += 2.5
    elif row['mom_20'] < -0.15:
        points += 1.5
    elif row['mom_20'] < -0.05:
        points += 0.8

    # --- B. BIAS (使用动态阈值) ---
    if row['bias'] < adaptive_buy_deep * 1.3:
        points += 2.0 if row['vol'] > row['vol_ma20'] else 1.2
    elif row['bias'] < adaptive_buy_deep:
        points += 1.0
    elif row['bias'] < adaptive_buy_mid:
        points += 0.5

    # BIAS 13
    if row['bias13'] < -10:
        points += 1.2
    elif row['bias13'] < -6:
        points += 0.7

    # --- C. 量价相关性 ---
    if not np.isnan(row['pv_corr_5']):
        if row['pv_corr_5'] < -0.3:
            points += 1.0
        elif row['pv_corr_5'] < 0:
            points += 0.4

    if not np.isnan(row['pv_corr_20']):
        if row['pv_corr_20'] < -0.3:
            points += 0.8
        elif row['pv_corr_20'] < 0:
            points += 0.3

    # --- D. Z-Score ---
    if row['z_score'] < dynamic_z_deep:
        points += 1.0
    elif row['z_score'] < PARAMS['z_buy_mid']:
        points += 0.5

    # --- E. BB ---
    if row['bb_pos'] < 20:
        points += 0.7

    # --- F. RSI ---
    if row['rsi'] < 20:
        points += 1.2
    elif row['rsi'] < 30:
        points += 0.6

    # --- G. Others ---
    # KDJ
    if row['j_val'] < 20:
        points += 0.4

    # MFI
    try:
        if row['mfi'] < 30:
            points += 0.4
    except (KeyError, TypeError):
        pass  # MFI 可能不存在或为 NaN

    # MACD Bullish
    if row['macd'] > row['macd_signal'] and row['macd_hist'] > row['macd_hist_prev']:
        points += 0.4

    # --- H. 52 Week Position ---
    if row['pos_52w'] < 30:
        points += 1.0

    # --- I. [v2.0 新增] Wyckoff VPA ---
    # Stopping Volume: 阴线 + 放量 + (窄幅 或 高收盘位)
    is_stopping_volume = (row['close'] < row['open']) and row['is_high_volume'] and \
                         (row['is_narrow_spread'] or row['close_position'] > 0.6)
    if is_stopping_volume:
        points += 1.0

    # --- J. [v2.0 新增] OBV 底部背离 ---
    # price_new_low and obv_not_low
    price_new_low = row['low'] <= row['low_20_prev'] if not pd.isna(row['low_20_prev']) else False
    obv_not_low = row['obv'] > row['obv_low_20_prev'] if not pd.isna(row['obv_low_20_prev']) else False

    if price_new_low and obv_not_low:
        # 额外条件: pv_corr_5 > 0.5 或放量
        if (not np.isnan(row['pv_corr_5']) and row['pv_corr_5'] > 0.5) or row['vol'] > row['vol_ma20'] * 1.5:
            if row['bias'] < adaptive_buy_mid:
                points += 1.0

    return points


def calculate_alpha_score_vectorized(df, adaptive_buy_deep, adaptive_buy_mid, dynamic_z_deep):
    """
    [Optimized] Vectorized implementation of Alpha Scoring
    Fast O(1) operations on entire Series
    """
    points = pd.Series(0.0, index=df.index)

    # --- 0. 扣分项 / 风控 ---
    # Smart Knife (智能飞刀)
    is_clv_low = df['clv'] < -0.7
    is_range_wide = df['spread'] > df['avg_spread'] * 1.5
    is_falling_knife = is_clv_low & is_range_wide & (df['close'] < df['open'])

    # Liquidity Lock Alpha Penalty
    is_liq_lock = (df['close'] < df['close_1'] * 0.92) & (df['vol'] < df['vol_ma20'] * 0.1)

    points = np.where(is_liq_lock, points - 10.0, points)
    # Note: Falling knife penalty is -5.0 but if liq_lock is true, it's -10. 
    # Original logic was exclusive or cumulative? 
    # Original: if liq_lock: -10; elif falling_knife: -5. So exclusive.
    points = np.where((~is_liq_lock) & is_falling_knife, points - 5.0, points)

    # Early Exit Flag (for filtering later)
    # The caller typically filters by score >= threshold. 
    is_risk_triggered = is_liq_lock | is_falling_knife

    # We will accumulate positive points in a separate series and only add them where not risk triggered
    pos_points = pd.Series(0.0, index=df.index)

    # --- A. 动量因子 (LightGBM Strongest) ---
    pos_points += np.where(df['mom_5'] < -0.15, 2.0, 
                  np.where(df['mom_5'] < -0.08, 1.2, 
                  np.where(df['mom_5'] < -0.03, 0.5, 0.0)))

    pos_points += np.where(df['mom_20'] < -0.25, 2.5,
                  np.where(df['mom_20'] < -0.15, 1.5,
                  np.where(df['mom_20'] < -0.05, 0.8, 0.0)))

    # --- B. BIAS (使用动态阈值) ---
    cond_bias_deep_13 = df['bias'] < (adaptive_buy_deep * 1.3)
    cond_bias_deep = df['bias'] < adaptive_buy_deep
    cond_bias_mid = df['bias'] < adaptive_buy_mid
    
    # Volatility confirmation for deep bias
    vol_confirm = df['vol'] > df['vol_ma20']
    
    score_bias = np.where(cond_bias_deep_13, np.where(vol_confirm, 2.0, 1.2),
                 np.where(cond_bias_deep, 1.0,
                 np.where(cond_bias_mid, 0.5, 0.0)))
    pos_points += score_bias

    # BIAS 13
    pos_points += np.where(df['bias13'] < -10, 1.2,
                  np.where(df['bias13'] < -6, 0.7, 0.0))

    # --- C. 量价相关性 ---
    pv5 = df['pv_corr_5'].fillna(100) # Fill with high value to fail < 0 check
    pos_points += np.where(pv5 < -0.3, 1.0,
                  np.where(pv5 < 0, 0.4, 0.0))
    
    pv20 = df['pv_corr_20'].fillna(100)
    pos_points += np.where(pv20 < -0.3, 0.8,
                  np.where(pv20 < 0, 0.3, 0.0))

    # --- D. Z-Score ---
    pos_points += np.where(df['z_score'] < dynamic_z_deep, 1.0,
                  np.where(df['z_score'] < PARAMS['z_buy_mid'], 0.5, 0.0))

    # --- E. BB ---
    pos_points += np.where(df['bb_pos'] < 20, 0.7, 0.0)

    # --- F. RSI ---
    pos_points += np.where(df['rsi'] < 20, 1.2,
                  np.where(df['rsi'] < 30, 0.6, 0.0))

    # --- G. Others ---
    # KDJ
    pos_points += np.where(df['j_val'] < 20, 0.4, 0.0)

    # MFI
    mfi_safe = df['mfi'].fillna(100)
    pos_points += np.where(mfi_safe < 30, 0.4, 0.0)

    # MACD Bullish
    cond_macd = (df['macd'] > df['macd_signal']) & (df['macd_hist'] > df['macd_hist_prev'])
    pos_points += np.where(cond_macd, 0.4, 0.0)

    # --- H. 52 Week Position ---
    pos_points += np.where(df['pos_52w'] < 30, 1.0, 0.0)

    # --- I. Wyckoff VPA ---
    is_stopping = (df['close'] < df['open']) & df['is_high_volume'] & \
                  (df['is_narrow_spread'] | (df['close_position'] > 0.6))
    pos_points += np.where(is_stopping, 1.0, 0.0)

    # --- J. OBV 底部背离 ---
    low_20_prev = df['low_20_prev']
    obv_low_20_prev = df['obv_low_20_prev']
    
    price_new_low = (df['low'] <= low_20_prev) & low_20_prev.notna()
    obv_not_low = (df['obv'] > obv_low_20_prev) & obv_low_20_prev.notna()
    
    cond_extra = ((df['pv_corr_5'] > 0.5) & df['pv_corr_5'].notna()) | \
                 (df['vol'] > df['vol_ma20'] * 1.5)
    
    cond_obv_div = price_new_low & obv_not_low & cond_extra & (df['bias'] < adaptive_buy_mid)
    pos_points += np.where(cond_obv_div, 1.0, 0.0)

    # Final Score
    final_points = np.where(is_risk_triggered, points, points + pos_points)
    return final_points


def scan(df, target_date=None, meta_dict=None):
    if target_date is None:
        target_date = df['trade_date'].max()
    print(f"Scanning for date: {target_date.date() if hasattr(target_date, 'date') else target_date}...")

    if meta_dict is None:
        meta_dict = {}

    # 0. Filter Data for Target Date
    df_day = df[df['trade_date'] == target_date].copy()
    # 实盘约束：不参与北交所 9 开头标的
    if 'ts_code' in df_day.columns:
        df_day = df_day[~df_day['ts_code'].astype(str).str.startswith('9')].copy()
    
    if df_day.empty:
        print("No data for target date.")
        return pd.DataFrame()

    # --- 1. Vectorized Pre-filtering ---
    
    # Basic Validity
    mask_valid = df_day['ma20'].notna() & df_day['vol_ma20'].notna()
    
    # New Stock Filter
    mask_new = df_day['days_listed'] >= PARAMS['new_stock_days']
    
    # Limit Store Lookups (Map Name)
    name_map = {k: v.get('name', '') for k,v in meta_dict.items()}
    df_day['name'] = df_day['ts_code'].map(name_map).fillna('')
    
    # Calculate Limit Ratio Vectorized
    df_day['limit_ratio'] = limit_ratio_vectorized(df_day['ts_code'], df_day['name'])

    # Limit Down Filter
    is_limit_down = (df_day['pct_chg'] < -df_day['limit_ratio'] * 90) & \
                    (df_day['close'] == df_day['low'])
    
    # Halted / No Volume Filter
    is_halted = (df_day['vol'] == 0) | (df_day['amount'] == 0)
    
    # Crash Filter
    cond_crash = (df_day['vol'] > df_day['vol_ma5'] * 2.5) & (df_day['close'] < df_day['open'])

    # Strict Limit Touch Filter
    limit_up_price = df_day['close_1'] * (1 + df_day['limit_ratio'])
    is_limit_touched = df_day['high'] >= limit_up_price * 0.995
    if not PARAMS['strict_limit_filter']:
        is_limit_touched = False 

    # --- 2. Oversold Exemptions (Liquidity Filter) ---
    is_extreme_oversold = (df_day['bias'] < -15) | (df_day['z_score'] < -2.5)
    is_deep_oversold_tier = (df_day['bias'] < -10) | (df_day['z_score'] < -2.0)
    
    liquidity_ok_raw = df_day['amount_ma20'] > PARAMS['liquidity_threshold']
    vol_ratio = np.divide(df_day['vol'], df_day['vol_ma20'], out=np.ones_like(df_day['vol']), where=df_day['vol_ma20']>0)
    df_day['vol_ratio'] = vol_ratio
    
    cond_liq_normal = liquidity_ok_raw & (vol_ratio > 0.6)
    cond_liq_deep = liquidity_ok_raw & (vol_ratio > 0.4)
    
    liquidity_ok = np.where(is_extreme_oversold, True,
                   np.where(is_deep_oversold_tier, cond_liq_deep, cond_liq_normal))

    # Liquidity Lock Patch
    avg_p = (df_day['open'] + df_day['high'] + df_day['low'] + df_day['close']) / 4
    is_liq_lock_patch = (avg_p < df_day['close_1'] * 0.94) & \
                        (df_day['vol'] < df_day['vol_ma20'] * 0.15) & \
                        (df_day['close'] < df_day['close_1'] * 0.92)

    # Combine Filters
    mask_final = mask_valid & mask_new & (~is_limit_down) & (~is_halted) & \
                 (~cond_crash) & (~is_liq_lock_patch) & (~is_limit_touched) & liquidity_ok

    # --- 2.5 Market Regime (大盘环境) ---
    # 用全市场横截面（当日）估计“系统性恐慌日”
    regime = detect_market_regime(
        df_day,
        panic_down_ratio=PARAMS.get('market_panic_down_ratio', 0.75),
        panic_median_chg=PARAMS.get('market_panic_median_chg', -1.50),
        panic_oversold_ratio=PARAMS.get('market_panic_oversold_ratio', 0.20),
    )
    down_ratio = regime['down_ratio']
    median_chg = regime['median_chg']
    deep_os_ratio = regime['deep_oversold_ratio']

    panic_day = (
        PARAMS.get('enable_market_regime_filter', True)
        and regime['state'] == '恐慌'
    )

    logger.info(
        "Market regime | down_ratio=%.3f median_chg=%.2f deep_os_ratio=%.3f panic=%s",
        down_ratio, median_chg, deep_os_ratio, panic_day
    )

    df_scan = df_day[mask_final].copy()
    if df_scan.empty:
        return pd.DataFrame()

    # --- 3. Dynamic Thresholds ---
    is_trend_pass_raw = df_scan['close'] > df_scan['ma120']
    
    # Recalculate boolean series for subset
    is_extreme_os_scan = (df_scan['bias'] < -15) | (df_scan['z_score'] < -2.5)
    is_deep_os_scan = (df_scan['bias'] < -10) | (df_scan['z_score'] < -2.0)
    
    is_trend_pass = is_trend_pass_raw | is_extreme_os_scan | is_deep_os_scan
    
    vr = df_scan['volatility_ratio'].fillna(1.0)
    trend_adjust = np.where(is_trend_pass_raw, 1.0 / vr, vr * 0.85)

    def calc_adaptive(base_val, adjustment):
        base_adj = base_val * adjustment
        upper = base_val * 0.5
        lower = base_val * 1.5
        return np.minimum(upper, np.maximum(lower, base_adj))

    adap_deep = calc_adaptive(PARAMS['buy_deep'], trend_adjust)
    adap_mid = calc_adaptive(PARAMS['buy_mid'], trend_adjust)
    adap_light = calc_adaptive(PARAMS['buy_light'], trend_adjust)
    
    dyn_z_deep = np.where(vr > 1.5, PARAMS['z_buy_deep'] * 0.7, PARAMS['z_buy_deep'])

    # --- 4. Calculate Scores Vectorized ---
    df_scan['alpha_score'] = calculate_alpha_score_vectorized(df_scan, adap_deep, adap_mid, dyn_z_deep)

    # --- 5. Signal Logic ---
    signals_list = pd.Series([[] for _ in range(len(df_scan))], index=df_scan.index)

    # L1: Panic Buy (抢筹)
    is_deep_os_signal = (df_scan['z_score'] < PARAMS['z_buy_deep']) | (df_scan['bias'] < adap_deep)
    
    cond_shrink = df_scan['vol'] < df_scan['vol_ma5'] * 1.2
    cond_red = df_scan['close'] > df_scan['open']
    cond_bot_surge = (df_scan['close'] < df_scan['close_5']) & (df_scan['vol'] > df_scan['vol_ma20'] * 1.5) & cond_red
    
    is_panic_vol = (df_scan['vol'] > df_scan['vol_ma20'] * 1.8) & (df_scan['close'] < df_scan['open']) & \
                   (df_scan['lower_wick_pct'] > 0.4)

    is_confirm = cond_shrink | cond_red | cond_bot_surge | is_panic_vol
    # 系统性恐慌日禁用“纯缩量确认”，防止市场普跌时 L1 爆量误触发
    if panic_day:
        is_confirm = cond_red | cond_bot_surge | is_panic_vol

    l1_threshold = (PARAMS['pass_score_threshold'] - 2.0)
    if panic_day:
        l1_threshold += PARAMS.get('l1_alpha_penalty_in_panic', 1.5)

    l1_mask = is_deep_os_signal & is_confirm & (df_scan['alpha_score'] >= l1_threshold)
    
    def append_sig(mask, sig_name, target_series):
        idxs = mask[mask].index
        for idx in idxs:
            target_series[idx].append(sig_name)
    
    append_sig(l1_mask, "抢筹 (L1)", signals_list)

    # Trend Pullback
    tp_strict = is_trend_pass_raw & \
                (df_scan['close'] <= df_scan['ma20'] * 1.02) & (df_scan['close'] > df_scan['ma20'] * 0.98) & \
                (df_scan['ma5'] > df_scan['ma20']) & cond_red & \
                (df_scan['vol'] > df_scan['vol_ma5'] * 0.7) & (~df_scan['is_high_position'])

    tp_relaxed = is_trend_pass_raw & \
                 (df_scan['close'] <= df_scan['ma20'] * 1.05) & (df_scan['close'] > df_scan['ma20'] * 0.95) & \
                 (df_scan['ma5'] > df_scan['ma20']) & \
                 (df_scan['vol'] > df_scan['vol_ma5'] * 0.5) & (~df_scan['is_high_position'])

    tp_wave = is_trend_pass_raw & (df_scan['close'] > df_scan['ma20']) & \
              (df_scan['close'] <= df_scan['ma5'] * 1.03) & (df_scan['close'] > df_scan['ma5'] * 0.97) & \
              (df_scan['ma5'] > df_scan['ma20']) & (df_scan['adx'] > 20) & cond_red & (~df_scan['is_high_position'])

    trend_pullback = tp_strict | tp_relaxed | tp_wave

    # L2: Build Position
    is_mid_os_k = (df_scan['z_score'] < PARAMS['z_buy_mid']) | (df_scan['bias'] < adap_mid)
    is_mid_not_deep = is_mid_os_k & (~is_deep_os_signal)
    
    pv_ok = (df_scan['close'] > df_scan['open']) | (df_scan['close'] > df_scan['close_1'])
    pv_ok &= (df_scan['vol'] > df_scan['vol_ma5'] * 0.8)
    
    l2_base = (is_mid_not_deep & pv_ok & is_trend_pass) | trend_pullback
    l2_mask = l2_base & (df_scan['alpha_score'] >= PARAMS['pass_score_threshold'])
    
    append_sig(l2_mask, "建仓 (L2)", signals_list)

    # L3: Add Position
    is_light_os = (df_scan['bias'] < adap_light) & (df_scan['bias'] >= adap_mid) & cond_red
    
    l3_trend = (df_scan['bias'] > -3) & (df_scan['bias'] < 2) & is_trend_pass_raw & \
               ((df_scan['adx'] > 25) | (df_scan['plus_di'] > df_scan['minus_di'])) & \
               (df_scan['close'] > df_scan['ma5']) & (df_scan['close'] <= df_scan['ma5'] * 1.015) & \
               cond_red & (~df_scan['is_high_position'])

    l3_cond = (is_light_os | trend_pullback | l3_trend) & is_trend_pass & \
              (df_scan['alpha_score'] >= PARAMS['pass_score_threshold'])

    append_sig(l3_cond, "加仓 (L3)", signals_list)

    # Trend Breakdown
    is_breakout = (df_scan['close'] > df_scan['high_20_prev']) & \
                  (df_scan['vol'] > df_scan['vol_ma20'] * 1.3) & \
                  (df_scan['close'] > df_scan['ma20']) & \
                  (df_scan['adx'] > 25) & \
                  (df_scan['rsi'] < 80) & \
                  (~df_scan['is_high_position']) & is_trend_pass_raw
    
    append_sig(is_breakout, "趋势:突破", signals_list)

    is_momentum = (df_scan['close'] > df_scan['ma5']) & \
                  (df_scan['ma5'] > df_scan['ma20']) & \
                  (df_scan['ma20'] > df_scan['ma120']) & \
                  (df_scan['close'] > df_scan['close_1'] * 1.03) & \
                  (df_scan['rsi'] > 50) & (df_scan['rsi'] < 75) & \
                  (df_scan['vol'] > df_scan['vol_ma5'] * 0.8) & \
                  (df_scan['macd'] > df_scan['macd_signal']) & \
                  (~df_scan['is_high_position'])

    append_sig(is_momentum, "趋势:动量", signals_list)

    bias_5_approx = np.where(df_scan['ma_bias_base'] > 0, 
                             (df_scan['close_5'] - df_scan['ma_bias_base']) / df_scan['ma_bias_base'] * 100, 0)
    
    was_recently_oversold = (bias_5_approx < -8) | (df_scan['bias'] < -5)
    
    is_bot_break = (df_scan['close'] > df_scan['ma20']) & \
                   (df_scan['close_1'] < df_scan['ma20']) & \
                   (df_scan['vol'] > df_scan['vol_ma20'] * 1.5) & \
                   was_recently_oversold & \
                   (~df_scan['is_high_position'])

    append_sig(is_bot_break, "趋势:底部启动", signals_list)

    # --- 6. Format Result ---
    has_signal = signals_list.apply(len) > 0
    df_result = df_scan[has_signal].copy()
    if df_result.empty:
        return pd.DataFrame()

    df_result['signal_list'] = signals_list[has_signal]
    df_result['信号'] = df_result['signal_list'].apply(lambda x: " | ".join(x))
    
    df_result['超跌等级'] = np.where(is_extreme_os_scan[has_signal], '极度',
                           np.where(is_deep_os_scan[has_signal], '深度', '普通'))
    df_result['高位'] = np.where(df_result['is_high_position'], '是', '否')
    
    df_result['涨幅%'] = df_result['pct_chg'].round(2)
    df_result['Alpha评分'] = df_result['alpha_score'].round(1)
    df_result['Z-Score'] = df_result['z_score'].round(2)
    df_result['BIAS'] = df_result['bias'].round(2)
    df_result['Vol比'] = df_result['vol_ratio'].round(2)
    df_result['代码'] = df_result['ts_code']
    df_result['收盘'] = df_result['close']
    df_result['市场状态'] = regime['state']
    df_result['建议仓位'] = regime['position_range']
    df_result['单票上限'] = regime['single_stock_max']
    
    return df_result


def format_output(res_df, meta_dict):
    if not meta_dict:
        res_df['名称'] = res_df['代码']
        res_df['行业'] = ''
        return res_df

    def get_meta(code, field):
        return meta_dict.get(normalize_ts_code(code), {}).get(field, '')

    res_df['名称'] = res_df['代码'].apply(lambda x: get_meta(x, 'name') or normalize_ts_code(x))
    res_df['行业'] = res_df['代码'].apply(lambda x: get_meta(x, 'industry'))

    # Reorder columns
    cols = ['代码', '名称', '信号', '涨幅%', '行业', 'Alpha评分', 'Z-Score', 'BIAS', 'Vol比', '高位', '超跌等级', '收盘', '市场状态', '建议仓位', '单票上限']
    return res_df[[c for c in cols if c in res_df.columns]]


def main(target_date_str=None):
    """主函数：执行选股扫描"""
    logger.info("=" * 60)
    logger.info("MFTS v6.1 选股扫描开始")
    logger.info("=" * 60)
    
    df = load_data()
    if df is None:
        logger.error("数据加载失败，退出")
        return

    # Load metadata first for stock name lookup
    meta_dict = load_metadata()

    # Pre-calc Indicators
    df = calc_indicators(df)

    # [Patch B] Safe Cleaning
    df = df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])

    # [Audit Fix P0-4] 标记长期停牌行，ffill 后排除虚假超跌信号
    df['_is_suspended'] = (df['vol'].isna()) | (df['vol'] <= 0)
    df['_susp_streak'] = df.groupby('ts_code', observed=True)['_is_suspended'].transform(
        lambda x: x.groupby((~x).cumsum()).cumsum()
    )
    # 仅允许在同一股票内前向填充，收紧为最多 3 天
    df = df.groupby('ts_code', observed=True, group_keys=False).apply(lambda g: g.ffill(limit=3))
    # 连续停牌 > 3 天的行，将关键指标置 NaN，scan 时自动排除
    df.loc[df['_susp_streak'] > 3, ['ma5', 'ma20', 'ma120', 'z_score', 'bias']] = np.nan
    df = df.drop(columns=['_is_suspended', '_susp_streak'], errors='ignore')


    target_date = None
    if target_date_str:
        parsed = pd.to_datetime(target_date_str, format="%Y%m%d", errors="coerce")
        if pd.isna(parsed):
            logger.error(f"无效日期格式: {target_date_str}，应为 YYYYMMDD")
            return
        day_mask = df["trade_date"].dt.strftime("%Y%m%d") == target_date_str
        if not day_mask.any():
            logger.error(f"指定日期无数据: {target_date_str}")
            return
        # 取该交易日在数据中的实际时间戳（保留时区信息）
        target_date = df.loc[day_mask, "trade_date"].iloc[0]

    # Execute Scan
    res = scan(df, target_date=target_date, meta_dict=meta_dict)

    if not res.empty:
        final_res = format_output(res, meta_dict)
        
        # 获取扫描日期
        scan_dt = target_date if target_date is not None else df['trade_date'].max()
        scan_date = scan_dt.strftime('%Y%m%d')
        
        logger.info(f"[MFTS v6.1] 选股结果 ({len(final_res)} 只) - {scan_date}")
        print(final_res[['代码', '名称', '信号', '涨幅%', 'Alpha评分', '高位', '超跌等级']].head(20))
        
        # 分层输出（scan 子目录）+ 兼容旧路径双写
        dirs = ensure_output_dirs(OUTPUT_DIR)
        scan_dir = dirs['scan']
        base_dir = Path(OUTPUT_DIR)

        dated_new = scan_dir / f"mfts_scan_{scan_date}.csv"
        dated_legacy = base_dir / f"mfts_scan_{scan_date}.csv"
        write_dual_csv(final_res, dated_new, dated_legacy, index=False, encoding='utf-8-sig')
        logger.info(f"结果已保存至: {dated_new} (兼容写入: {dated_legacy})")

        latest_new = scan_dir / "mfts_latest.csv"
        latest_legacy = base_dir / "mfts_latest.csv"
        write_dual_csv(final_res, latest_new, latest_legacy, index=False, encoding='utf-8-sig')
    else:
        logger.warning("今日无符合 MFTS v6.1 标准的标的")
    
    logger.info("MFTS v6.1 选股扫描完成")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MFTS v6.1 选股扫描")
    parser.add_argument("--date", type=str, help="扫描日期(YYYYMMDD)，默认最新交易日")
    args = parser.parse_args()
    main(target_date_str=args.date)
