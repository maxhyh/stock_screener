"""
MFTS v6.2 优化版 - 基于IC分析和ML特征重要性
核心优化:
1. 因子权重调整（基于IC和ML特征重要性）
2. 动态阈值机制
3. 信号质量过滤
4. 风险控制增强
"""

import pandas as pd
import numpy as np
import os
import warnings

warnings.filterwarnings('ignore')

# 路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")
META_FILE = os.path.join(DATA_DIR, "stock_info.csv")

# ==========================================
# v6.2 优化参数（基于IC分析和ML结果）
# ==========================================
PARAMS_V62 = {
    # 基础阈值
    'bias_len': 20,
    'buy_deep': -10.0,
    'buy_mid': -7.0,
    'buy_light': -5.0,
    'z_buy_deep': -1.96,
    'z_buy_mid': -1.50,
    
    # v6.2 新增阈值
    'min_alpha_score': 5.0,       # 最低Alpha评分
    'min_volume_ratio': 1.2,      # 最低量比
    'min_atr_percent': 3.0,       # 最低ATR%
    'max_pos_52w': 40,            # 52周位置上限
    
    # 风控参数  
    'liquidity_threshold': 50000000,  # 最低成交额5000万
    'new_stock_days': 120,            # v6.2提高到120天
    'max_turnover': 25,               # 最大换手率
}

# ==========================================
# v6.2 优化权重（基于IC分析和ML特征重要性）
# ==========================================
WEIGHTS_V62 = {
    # IC排名第1: ATR% (IC=-0.051) → 大幅提权
    'atr_percent': 3.0,
    
    # IC排名第2: Volume Ratio (IC=-0.049) + ML最重要特征 → 大幅提权
    'volume_ratio': 2.5,
    
    # IC排名第3-4: BIAS, RSI → 保持/适度提高
    'bias': 2.5,
    'rsi': 1.8,
    
    # ML第2重要: 52W Position → 新增高权重
    'pos_52w': 2.0,
    
    # 其他因子
    'z_score': 1.5,
    'momentum': 1.8,
    'bb_pos': 0.8,
    'kdj': 0.5,
    'mfi': 0.4,
    'macd': 0.3,
    
    # IC最低: ADX (IC=-0.011) → 大幅降权
    'adx': 0.1,
}


def load_metadata():
    """加载股票元数据"""
    if not os.path.exists(META_FILE):
        return {}
    try:
        meta_df = pd.read_csv(META_FILE, dtype={'ts_code': str})
        return dict(zip(meta_df['ts_code'], meta_df['name']))
    except:
        return {}


def get_market_volatility(df, date, lookback=20):
    """
    计算市场整体波动性（用于动态阈值）
    """
    recent = df[df['trade_date'] <= date].tail(lookback * 1000)  # 大致估计
    if len(recent) == 0:
        return 1.0
    
    # 使用市场平均ATR作为波动性指标
    avg_atr = recent['atr_percent'].mean() if 'atr_percent' in recent.columns else 5.0
    
    # 标准化：5%为基准
    return avg_atr / 5.0


def get_dynamic_thresholds(market_volatility):
    """
    v6.2核心优化：动态阈值
    根据市场波动性调整买入阈值
    """
    base_deep = PARAMS_V62['buy_deep']
    base_mid = PARAMS_V62['buy_mid']
    base_z = PARAMS_V62['z_buy_deep']
    
    if market_volatility > 1.5:  # 高波动市场
        # 更严格的阈值
        return {
            'buy_deep': base_deep * 1.2,    # -12%
            'buy_mid': base_mid * 1.2,      # -8.4%
            'z_deep': base_z * 1.1,         # -2.16
        }
    elif market_volatility < 0.7:  # 低波动市场
        # 更宽松的阈值
        return {
            'buy_deep': base_deep * 0.8,    # -8%
            'buy_mid': base_mid * 0.8,      # -5.6%
            'z_deep': base_z * 0.9,         # -1.76
        }
    else:
        # 标准阈值
        return {
            'buy_deep': base_deep,
            'buy_mid': base_mid,
            'z_deep': base_z,
        }


def calculate_alpha_score_v62(row, thresholds):
    """
    v6.2 优化版Alpha评分
    核心改进：基于IC和ML特征重要性调整权重
    """
    points = 0.0
    W = WEIGHTS_V62  # 权重配置
    
    # ---------- 0. 风险扣分 ----------
    # 智能飞刀检测
    try:
        is_clv_low = row['clv'] < -0.7
        is_range_wide = row['spread'] > row['avg_spread'] * 1.5
        is_falling_knife = is_clv_low and is_range_wide and row['close'] < row['open']
        
        if is_falling_knife:
            points -= 5.0
            return points  # 直接退出
    except:
        pass
    
    # 流动性陷阱检测
    try:
        is_liq_lock = (row['close'] < row['close_1'] * 0.92) and (row['vol'] < row['vol_ma20'] * 0.1)
        if is_liq_lock:
            points -= 10.0
            return points
    except:
        pass
    
    # ---------- 1. ATR% 因子（IC最高，权重3.0）----------
    try:
        atr_pct = row['atr_percent'] if 'atr_percent' in row else row.get('atr', 0) / row['close'] * 100
        if atr_pct > 8:
            points += 3.0 * W['atr_percent']  # 高波动，恐慌抛售
        elif atr_pct > 5:
            points += 2.0 * W['atr_percent']
        elif atr_pct > 3:
            points += 1.0 * W['atr_percent']
    except:
        pass
    
    # ---------- 2. Volume Ratio 因子（ML最重要，权重2.5）----------
    try:
        vol_ratio = row['vol'] / row['vol_ma20'] if row['vol_ma20'] > 0 else 1.0
        if vol_ratio > 3.0:
            points += 3.0 * W['volume_ratio']  # 巨量
        elif vol_ratio > 2.0:
            points += 2.0 * W['volume_ratio']
        elif vol_ratio > 1.5:
            points += 1.0 * W['volume_ratio']
        elif vol_ratio > 1.2:
            points += 0.5 * W['volume_ratio']
    except:
        pass
    
    # ---------- 3. BIAS 因子（权重2.5）----------
    try:
        if row['bias'] < thresholds['buy_deep'] * 1.3:
            points += 2.0 * W['bias']
        elif row['bias'] < thresholds['buy_deep']:
            points += 1.5 * W['bias']
        elif row['bias'] < thresholds['buy_mid']:
            points += 0.8 * W['bias']
        
        # BIAS 13
        if row['bias13'] < -10:
            points += 1.2 * W['bias']
        elif row['bias13'] < -6:
            points += 0.6 * W['bias']
    except:
        pass
    
    # ---------- 4. 52W Position（ML第2重要，权重2.0）----------
    try:
        pos_52w = row['pos_52w']
        if pos_52w < 10:
            points += 3.0 * W['pos_52w']  # 接近52周低点
        elif pos_52w < 20:
            points += 2.0 * W['pos_52w']
        elif pos_52w < 30:
            points += 1.0 * W['pos_52w']
        elif pos_52w < 40:
            points += 0.5 * W['pos_52w']
    except:
        pass
    
    # ---------- 5. Z-Score 因子（权重1.5）----------
    try:
        if row['z_score'] < thresholds['z_deep']:
            points += 2.0 * W['z_score']
        elif row['z_score'] < PARAMS_V62['z_buy_mid']:
            points += 1.0 * W['z_score']
    except:
        pass
    
    # ---------- 6. RSI 因子（权重1.8）----------
    try:
        if row['rsi'] < 20:
            points += 2.0 * W['rsi']
        elif row['rsi'] < 30:
            points += 1.2 * W['rsi']
        elif row['rsi'] < 40:
            points += 0.5 * W['rsi']
    except:
        pass
    
    # ---------- 7. Momentum 因子（权重1.8）----------
    try:
        if row['mom_5'] < -0.15:
            points += 2.0 * W['momentum']
        elif row['mom_5'] < -0.08:
            points += 1.2 * W['momentum']
        elif row['mom_5'] < -0.03:
            points += 0.5 * W['momentum']
        
        if row['mom_20'] < -0.25:
            points += 1.5 * W['momentum']
        elif row['mom_20'] < -0.15:
            points += 1.0 * W['momentum']
    except:
        pass
    
    # ---------- 8. BB Position ----------
    try:
        if row['bb_pos'] < 20:
            points += 1.0 * W['bb_pos']
        elif row['bb_pos'] < 30:
            points += 0.5 * W['bb_pos']
    except:
        pass
    
    # ---------- 9. KDJ ----------
    try:
        if row['j_val'] < 20:
            points += 1.0 * W['kdj']
    except:
        pass
    
    # ---------- 10. MFI ----------
    try:
        if row['mfi'] < 30:
            points += 1.0 * W['mfi']
    except:
        pass
    
    # ---------- 11. MACD ----------
    try:
        if row['macd'] > row['macd_signal'] and row['macd_hist'] > row.get('macd_hist_prev', 0):
            points += 1.0 * W['macd']
    except:
        pass
    
    # ---------- 12. ADX（IC最低，权重0.1）----------
    try:
        if row['adx'] > 25:
            points += 1.0 * W['adx']  # 几乎忽略
    except:
        pass
    
    # ---------- 13. v6.2新增：量价背离加分 ----------
    try:
        # 价格创新低但成交量不创新低 = 底部信号
        if row['low'] <= row.get('low_20_prev', row['low']) and row['vol'] > row.get('vol_low_20_prev', row['vol']):
            points += 2.0
    except:
        pass
    
    # ---------- 14. v6.2新增：Wyckoff Spring检测 ----------
    try:
        is_spring = (row['low'] < row.get('low_20_prev', row['low'])) and \
                    (row['close'] > row['open']) and \
                    (row['vol'] > row['vol_ma20'] * 1.5)
        if is_spring:
            points += 3.0  # 强烈买入信号
    except:
        pass
    
    return points


def filter_signals_v62(df):
    """
    v6.2 信号质量过滤
    移除低质量信号
    """
    filtered = df.copy()
    
    # 1. 最低Alpha评分
    if 'alpha_score' in filtered.columns:
        filtered = filtered[filtered['alpha_score'] >= PARAMS_V62['min_alpha_score']]
    
    # 2. 最低量比
    if 'vol_ratio' in filtered.columns:
        filtered = filtered[filtered['vol_ratio'] >= PARAMS_V62['min_volume_ratio']]
    
    # 3. 最低ATR%（过滤僵尸股）
    if 'atr_percent' in filtered.columns:
        filtered = filtered[filtered['atr_percent'] >= PARAMS_V62['min_atr_percent']]
    
    # 4. 52周位置上限（避免追高）
    if 'pos_52w' in filtered.columns:
        filtered = filtered[filtered['pos_52w'] <= PARAMS_V62['max_pos_52w']]
    
    # 5. 成交额过滤
    if 'amount' in filtered.columns:
        filtered = filtered[filtered['amount'] >= PARAMS_V62['liquidity_threshold']]
    
    return filtered


def get_signal_type_v62(alpha_score, row):
    """
    v6.2 信号分类
    """
    if alpha_score >= 15:
        return 'L1_极度超跌'
    elif alpha_score >= 10:
        return 'L2_深度超跌'
    elif alpha_score >= 7:
        return 'L3_中度超跌'
    elif alpha_score >= 5:
        return 'L4_轻度超跌'
    else:
        return None


def scan_v62(df, target_date=None, meta_dict=None, top_n=30):
    """
    v6.2 主扫描函数
    """
    if target_date is None:
        target_date = df['trade_date'].max()
    
    print(f"[v6.2] Scanning for date: {target_date.date() if hasattr(target_date, 'date') else target_date}...")
    
    if meta_dict is None:
        meta_dict = load_metadata()
    
    # 获取目标日期数据
    today_df = df[df['trade_date'] == target_date].copy()
    
    if len(today_df) == 0:
        print(f"No data for {target_date}")
        return pd.DataFrame()
    
    # 计算市场波动性
    market_vol = get_market_volatility(df, target_date)
    print(f"  市场波动性: {market_vol:.2f}")
    
    # 获取动态阈值
    thresholds = get_dynamic_thresholds(market_vol)
    print(f"  动态阈值: BIAS={thresholds['buy_deep']:.1f}%, Z={thresholds['z_deep']:.2f}")
    
    # 计算量比
    today_df['vol_ratio'] = today_df['vol'] / today_df['vol_ma20']
    
    # 计算Alpha评分
    today_df['alpha_score'] = today_df.apply(
        lambda row: calculate_alpha_score_v62(row, thresholds),
        axis=1
    )
    
    # 添加信号类型
    today_df['signal'] = today_df.apply(
        lambda row: get_signal_type_v62(row['alpha_score'], row),
        axis=1
    )
    
    # 过滤有效信号
    valid_df = today_df[today_df['signal'].notna()].copy()
    print(f"  有效信号: {len(valid_df)}/{len(today_df)}")
    
    # v6.2 信号质量过滤
    valid_df = filter_signals_v62(valid_df)
    print(f"  过滤后: {len(valid_df)}")
    
    if len(valid_df) == 0:
        return pd.DataFrame()
    
    # 排序并选择Top N
    result = valid_df.nlargest(top_n, 'alpha_score').copy()
    
    # 添加股票名称
    result['name'] = result['ts_code'].map(meta_dict)
    
    # 整理输出列
    output_cols = ['ts_code', 'name', 'signal', 'alpha_score', 'close', 'pct_chg',
                   'bias', 'z_score', 'rsi', 'vol_ratio', 'atr_percent', 'pos_52w']
    
    for col in output_cols:
        if col not in result.columns:
            result[col] = np.nan
    
    return result[output_cols]


# 兼容性导出
def calculate_alpha_score(row, adaptive_buy_deep, adaptive_buy_mid, dynamic_z_deep):
    """兼容v6.1调用方式"""
    thresholds = {
        'buy_deep': adaptive_buy_deep,
        'buy_mid': adaptive_buy_mid,
        'z_deep': dynamic_z_deep,
    }
    return calculate_alpha_score_v62(row, thresholds)


if __name__ == "__main__":
    print("=" * 70)
    print("MFTS v6.2 优化版测试")
    print("=" * 70)
    
    from mfts_screener import calc_indicators
    
    # 加载数据
    print("\n加载数据...")
    df = pd.read_parquet(PARQUET_FILE)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = df['ts_code'].astype(str)
    
    # 计算指标
    print("计算指标...")
    df = df.sort_values(['ts_code', 'trade_date'])
    df = calc_indicators(df)
    df = df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
    
    # 扫描
    print("\n运行v6.2扫描...")
    result = scan_v62(df)
    
    if len(result) > 0:
        print("\n" + "=" * 70)
        print("TOP 30 推荐股票")
        print("=" * 70)
        print(result.to_string(index=False))
    else:
        print("\n今日无符合条件的股票")
