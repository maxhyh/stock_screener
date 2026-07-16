"""
MFTS 智能选股系统 - Web 服务
Flask 应用入口（初始化 + 路由注册）
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import sys

from flask import Flask
from flask.json.provider import DefaultJSONProvider
import numpy as np

# 确保从项目根目录可导入 web 包（兼容 `python web/app.py`）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web.routes import backtest_signal_bp, ml_bp, platform_bp, results_bp


class SafeJSONProvider(DefaultJSONProvider):
    """处理 NaN/Inf 和 numpy 类型（Flask 3.x 兼容）。"""

    def default(self, obj):  # type: ignore[override]
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def create_logger(base_dir: str) -> logging.Logger:
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("MFTS_WEB")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "web_api.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(console_handler)

    return logger


def create_app() -> Flask:
    app = Flask(__name__)
    app.json = SafeJSONProvider(app)

    data_dir = os.path.join(BASE_DIR, "data")
    output_dir = os.path.join(BASE_DIR, "output")
    local_only = os.environ.get("MFTS_LOCAL_ONLY", "true").lower() == "true"
    api_write_token = os.environ.get("MFTS_API_WRITE_TOKEN", "").strip()

    app.config.update(
        {
            "BASE_DIR": BASE_DIR,
            "DATA_DIR": data_dir,
            "ASHARE_DATA_ROOT": os.environ.get("ASHARE_DATA_ROOT", "").strip(),
            "OUTPUT_DIR": output_dir,
            "RESULT_FILE": os.path.join(output_dir, "mfts_latest.csv"),
            "MFTS_LOGGER": create_logger(BASE_DIR),
            "CREATED_AT": datetime.now().isoformat(),
            "LOCAL_ONLY": local_only,
            "API_WRITE_TOKEN": api_write_token,
        }
    )

    app.register_blueprint(results_bp)
    app.register_blueprint(ml_bp)
    app.register_blueprint(backtest_signal_bp)
    app.register_blueprint(platform_bp)
    return app


app = create_app()


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    local_only = app.config.get("LOCAL_ONLY", True)
    default_host = "127.0.0.1" if local_only else "0.0.0.0"
    host = os.getenv("MFTS_HOST", default_host)
    port = int(os.getenv("MFTS_PORT", "5001"))
    app.run(host=host, port=port, debug=debug_mode)
