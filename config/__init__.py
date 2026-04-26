# -*- coding: utf-8 -*-
"""
MFTS 配置模块
统一管理所有配置项
"""

from .settings import (
    MFTSConfig,
    TrainingConfig,
    DeployConfig,
    PathConfig,
    get_config,
)

__all__ = [
    'MFTSConfig',
    'TrainingConfig', 
    'DeployConfig',
    'PathConfig',
    'get_config',
]
