# -*- coding: utf-8 -*-
"""
MFTS 统一日志模块
支持文件 + 控制台双输出、日志轮转、结构化格式

使用方法:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Processing data...")
    logger.error("Failed to load file", exc_info=True)
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

# 尝试导入配置，如果失败则使用默认值
try:
    from config.settings import PathConfig, DeployConfig
    LOG_DIR = PathConfig.LOG_DIR
    LOG_LEVEL = DeployConfig.LOG_LEVEL
    LOG_MAX_BYTES = DeployConfig.LOG_MAX_BYTES
    LOG_BACKUP_COUNT = DeployConfig.LOG_BACKUP_COUNT
except ImportError:
    # 回退默认值
    LOG_DIR = Path(__file__).parent.parent / "logs"
    LOG_LEVEL = 'INFO'
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5

# 确保日志目录存在
LOG_DIR = Path(LOG_DIR)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 全局日志格式
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 缓存已创建的 logger
_loggers = {}


def setup_logging(
    level: str = None,
    log_file: str = None,
    console: bool = True,
    file_output: bool = True,
):
    """
    配置全局日志系统
    
    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        log_file: 日志文件名（默认 mfts.log）
        console: 是否输出到控制台
        file_output: 是否输出到文件
    """
    level = level or LOG_LEVEL
    log_file = log_file or 'mfts.log'
    
    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # 清除现有处理器
    root_logger.handlers.clear()
    
    # 创建格式化器
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    
    # 控制台处理器
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        root_logger.addHandler(console_handler)
    
    # 文件处理器（带轮转）
    if file_output:
        log_path = LOG_DIR / log_file
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8',
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        root_logger.addHandler(file_handler)
    
    # 抑制第三方库的过多日志
    for lib in ['urllib3', 'requests', 'werkzeug', 'flask']:
        logging.getLogger(lib).setLevel(logging.WARNING)
    
    return root_logger


def get_logger(name: str = None, level: str = None) -> logging.Logger:
    """
    获取或创建一个 logger 实例
    
    Args:
        name: logger 名称（通常使用 __name__）
        level: 日志级别（可选，默认使用全局配置）
    
    Returns:
        logging.Logger 实例
    
    Example:
        logger = get_logger(__name__)
        logger.info("Processing started")
        logger.warning("Low memory warning")
        logger.error("Failed to connect", exc_info=True)
    """
    name = name or 'mfts'
    
    # 检查缓存
    if name in _loggers:
        return _loggers[name]
    
    # 确保根日志器已配置
    if not logging.getLogger().handlers:
        setup_logging()
    
    # 创建 logger
    logger = logging.getLogger(name)
    
    if level:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    _loggers[name] = logger
    return logger


class LogContext:
    """
    日志上下文管理器，用于追踪操作耗时
    
    Example:
        with LogContext(logger, "Processing data"):
            # 执行操作
            process_data()
        # 自动输出: "Processing data completed in 2.34s"
    """
    
    def __init__(self, logger: logging.Logger, operation: str, level: int = logging.INFO):
        self.logger = logger
        self.operation = operation
        self.level = level
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.log(self.level, f"{self.operation} started...")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        
        if exc_type is None:
            self.logger.log(self.level, f"{self.operation} completed in {elapsed:.2f}s")
        else:
            self.logger.error(
                f"{self.operation} failed after {elapsed:.2f}s: {exc_val}",
                exc_info=True
            )
        
        return False  # 不抑制异常


# 便捷函数
def log_function_call(logger: logging.Logger):
    """
    装饰器：记录函数调用和耗时
    
    Example:
        @log_function_call(logger)
        def my_function(x, y):
            return x + y
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            func_name = func.__name__
            logger.debug(f"Calling {func_name}...")
            start = datetime.now()
            try:
                result = func(*args, **kwargs)
                elapsed = (datetime.now() - start).total_seconds()
                logger.debug(f"{func_name} completed in {elapsed:.2f}s")
                return result
            except Exception as e:
                elapsed = (datetime.now() - start).total_seconds()
                logger.error(f"{func_name} failed after {elapsed:.2f}s: {e}", exc_info=True)
                raise
        return wrapper
    return decorator
