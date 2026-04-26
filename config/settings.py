# -*- coding: utf-8 -*-
"""
MFTS 统一配置管理
所有配置项集中在此文件，支持环境变量覆盖

使用方法:
    from config import MFTSConfig, TrainingConfig
    print(MFTSConfig.BUY_DEEP)  # -10.0
"""

import json
import os
from pathlib import Path


# ===========================================
# 硬件配置检测（按内存分档自适应）
# ===========================================
import platform
import subprocess


def resolve_default_label_horizon(profile_file: str | Path | None = None, fallback: int = 8) -> int:
    """
    从量化档位配置读取默认持有期，作为训练标签 horizon 的默认值。
    若读取失败，回退到 fallback。
    """
    try:
        profile_path = Path(profile_file) if profile_file else (Path(__file__).parent / "quant_live_profiles.json")
        if not profile_path.exists():
            return int(fallback)

        with profile_path.open("r", encoding="utf-8") as f:
            root = json.load(f)
        if not isinstance(root, dict):
            return int(fallback)

        # 允许运行时覆盖默认档位，避免研究/执行口径错配。
        # 优先级: MFTS_ACTIVE_PROFILE > MFTS_P2_PROFILE > 配置文件 default_profile
        profile_name = str(
            os.environ.get("MFTS_ACTIVE_PROFILE")
            or os.environ.get("MFTS_P2_PROFILE")
            or root.get("default_profile", "balanced")
        )
        profiles = root.get("profiles", {})
        if not isinstance(profiles, dict):
            return int(fallback)

        cfg = profiles.get(profile_name, {})
        if not isinstance(cfg, dict):
            return int(fallback)

        return max(1, int(cfg.get("holding_days", fallback)))
    except Exception:
        return int(fallback)


def get_system_memory_gb():
    """获取系统内存大小(GB)"""
    try:
        if platform.system() == 'Darwin':  # macOS
            result = subprocess.run(['sysctl', '-n', 'hw.memsize'], 
                                   capture_output=True, text=True)
            return int(result.stdout.strip()) // (1024**3)
        else:
            return 16  # 默认假设足够内存
    except Exception:
        return 16

# 自动检测内存档位
SYSTEM_MEMORY_GB = get_system_memory_gb()
LOW_MEMORY_MODE = SYSTEM_MEMORY_GB <= 8
MID_MEMORY_MODE = 8 < SYSTEM_MEMORY_GB <= 16
HIGH_MEMORY_MODE = SYSTEM_MEMORY_GB > 16


# ===========================================
# 路径配置
# ===========================================
class PathConfig:
    """路径配置 - 支持环境变量覆盖"""
    
    # 项目根目录
    BASE_DIR = Path(os.environ.get(
        'MFTS_BASE_DIR',
        Path(__file__).parent.parent
    ))
    
    # 数据目录
    DATA_DIR = BASE_DIR / "data"
    
    # 输出目录
    OUTPUT_DIR = BASE_DIR / "output"
    
    # 日志目录
    LOG_DIR = BASE_DIR / "logs"
    
    # 模型目录
    MODEL_DIR = BASE_DIR / "models"
    
    # 核心模块目录
    CORE_DIR = BASE_DIR / "core"
    
    # 数据文件
    PARQUET_FILE = DATA_DIR / "daily_all_5y.parquet"
    META_FILE = DATA_DIR / "stock_info.csv"
    
    # 确保目录存在
    @classmethod
    def ensure_dirs(cls):
        """确保所有必要目录存在"""
        for dir_path in [cls.OUTPUT_DIR, cls.LOG_DIR, cls.MODEL_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)


# ===========================================
# MFTS 策略参数
# ===========================================
class MFTSConfig:
    """MFTS v6.1 策略参数 - 对齐 Pine Script 默认值"""
    
    # BIAS 参数
    BIAS_LEN = 20
    BUY_DEEP = -10.0      # 深度超跌阈值
    BUY_MID = -7.0        # 中度超跌阈值
    BUY_LIGHT = -5.0      # 轻度超跌阈值
    
    # Z-Score 参数
    Z_BUY_DEEP = -1.96    # 对应 "标准" 灵敏度
    Z_BUY_MID = -1.50
    
    # Alpha 评分
    PASS_SCORE_THRESHOLD = 4.0  # 对应 "标准" 灵敏度
    
    # 流动性过滤
    LIQUIDITY_THRESHOLD = 50_000_000  # CNY 5000万
    
    # 涨停过滤
    STRICT_LIMIT_FILTER = True
    
    # 风控参数
    ENABLE_VWAP_FILTER = False
    NEW_STOCK_DAYS = 60  # 新股过滤天数

    # 大盘环境过滤（系统性下跌时收紧 L1）
    ENABLE_MARKET_REGIME_FILTER = True
    MARKET_PANIC_DOWN_RATIO = 0.75       # 下跌家数占比
    MARKET_PANIC_MEDIAN_CHG = -1.50      # 当日涨跌幅中位数
    MARKET_PANIC_OVERSOLD_RATIO = 0.20   # 深度超跌占比
    L1_ALPHA_PENALTY_IN_PANIC = 1.5      # 恐慌日抬高 L1 分数门槛
    
    # 数据起始日期（按内存档位控制加载窗口）
    # 8GB: 约1年；16GB: 约3年；32GB+: 约5年
    if LOW_MEMORY_MODE:
        START_DATE_FILTER = '20250201'
    elif MID_MEMORY_MODE:
        START_DATE_FILTER = '20230101'
    else:
        START_DATE_FILTER = '20210101'
    
    @classmethod
    def to_dict(cls):
        """转换为字典格式（兼容旧代码）"""
        return {
            'bias_len': cls.BIAS_LEN,
            'buy_deep': cls.BUY_DEEP,
            'buy_mid': cls.BUY_MID,
            'buy_light': cls.BUY_LIGHT,
            'z_buy_deep': cls.Z_BUY_DEEP,
            'z_buy_mid': cls.Z_BUY_MID,
            'pass_score_threshold': cls.PASS_SCORE_THRESHOLD,
            'liquidity_threshold': cls.LIQUIDITY_THRESHOLD,
            'strict_limit_filter': cls.STRICT_LIMIT_FILTER,
            'enable_vwap_filter': cls.ENABLE_VWAP_FILTER,
            'new_stock_days': cls.NEW_STOCK_DAYS,
            'enable_market_regime_filter': cls.ENABLE_MARKET_REGIME_FILTER,
            'market_panic_down_ratio': cls.MARKET_PANIC_DOWN_RATIO,
            'market_panic_median_chg': cls.MARKET_PANIC_MEDIAN_CHG,
            'market_panic_oversold_ratio': cls.MARKET_PANIC_OVERSOLD_RATIO,
            'l1_alpha_penalty_in_panic': cls.L1_ALPHA_PENALTY_IN_PANIC,
        }


# ===========================================
# 训练参数
# ===========================================
class TrainingConfig:
    """LightGBM 模型训练参数"""
    
    # 数据划分
    TRAIN_START = '2015-01-01'
    TRAIN_END = '2022-12-31'
    VALID_START = '2023-01-01'
    VALID_END = '2023-12-31'
    TEST_START = '2024-01-01'
    TEST_END = '2025-12-26'
    
    # 批处理（按内存档位调整）
    if LOW_MEMORY_MODE:
        BATCH_SIZE = 100
    elif MID_MEMORY_MODE:
        BATCH_SIZE = 300
    else:
        BATCH_SIZE = 500
    
    # 特征选择
    MIN_IC = 0.01     # IC 阈值
    TOP_N_FEATURES = 15

    # 训练标签模式（与实盘执行对齐）
    # close_to_close_t1: 今日收盘->次日收盘（旧）
    # open_to_close_t1: 次日开盘->次日收盘（旧）
    # open_to_open: 次日开盘->(次日+H)开盘，H 由 LABEL_HORIZON 控制（推荐）
    LABEL_MODE = os.environ.get("MFTS_LABEL_MODE", "open_to_open")
    # 默认与实盘 default_profile 持有期保持一致（可由环境变量显式覆盖）
    DEFAULT_PROFILE_HOLDING_DAYS = resolve_default_label_horizon(fallback=8)
    LABEL_HORIZON = int(os.environ.get("MFTS_LABEL_HORIZON", str(DEFAULT_PROFILE_HOLDING_DAYS)))
    
    # LightGBM 参数
    LGBM_PARAMS = {
        'objective': 'regression',
        'metric': 'rmse',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'max_depth': 8,
        'min_data_in_leaf': 100,
        'lambda_l1': 0.1,
        'lambda_l2': 0.1,
        'verbose': -1,
    }
    
    NUM_BOOST_ROUND = 1000
    EARLY_STOPPING_ROUNDS = 50


# ===========================================
# 部署配置
# ===========================================
class DeployConfig:
    """部署相关配置"""
    
    # Web 服务
    WEB_HOST = os.environ.get('MFTS_HOST', '0.0.0.0')
    WEB_PORT = int(os.environ.get('MFTS_PORT', 5001))
    DEBUG_MODE = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    # 本地运行模式（项目已切换为本地部署）
    LOCAL_ONLY = os.environ.get('MFTS_LOCAL_ONLY', 'true').lower() == 'true'
    
    # 日志配置（按内存档位调整）
    LOG_LEVEL = os.environ.get('MFTS_LOG_LEVEL', 'INFO')
    if LOW_MEMORY_MODE:
        LOG_MAX_BYTES = 5 * 1024 * 1024
        LOG_BACKUP_COUNT = 3
    elif MID_MEMORY_MODE:
        LOG_MAX_BYTES = 12 * 1024 * 1024
        LOG_BACKUP_COUNT = 5
    else:
        LOG_MAX_BYTES = 20 * 1024 * 1024
        LOG_BACKUP_COUNT = 8


# ===========================================
# 便捷函数
# ===========================================
def get_config(name: str):
    """
    获取配置类
    
    Args:
        name: 配置名称 ('mfts', 'training', 'deploy', 'path')
    
    Returns:
        对应的配置类
    """
    configs = {
        'mfts': MFTSConfig,
        'training': TrainingConfig,
        'deploy': DeployConfig,
        'path': PathConfig,
    }
    return configs.get(name.lower())


# 初始化时确保目录存在
PathConfig.ensure_dirs()
