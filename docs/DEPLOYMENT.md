# 部署指南（本地版）

本项目当前采用本地部署，不依赖云服务器。

## 1. 环境准备

```bash
cd /path/to/stock_screener
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 初始化数据

```bash
python data/download_5y_data.py
```

## 3. 启动与运行

```bash
# 启动 Web
python web/app.py
# 访问 http://127.0.0.1:5001

# 执行一次全流程（增量更新 + 扫描 + ML + 验证）
python scripts/daily_all.py
```

## 4. 生产化运行（可选）

若需常驻服务，可在本机使用 gunicorn：

```bash
pip install gunicorn
nohup gunicorn -w 2 -b 127.0.0.1:5001 web.app:app > logs/web.log 2>&1 &
```

## 5. 输出目录说明

- `output/scan/mfts_scan_YYYYMMDD.csv`：每日扫描结果
- `output/scan/mfts_latest.csv`：最新扫描结果
- `output/daily/daily_YYYYMMDD.csv`：ML每日选股结果
- `output/verify/historical_summary.csv`：历史验证汇总
- `output/backtest/*.csv|*.png`：回测与信号统计产物

兼容说明：
- 读取端已支持旧平铺路径回退（例如 `output/daily_YYYYMMDD.csv`）。

## 6. 常见问题

- 数据更新失败：优先在 18:00 后运行，避免交易日数据尚未完全落库。
- 批量行情失败：脚本已内置“新浪 -> 东方财富 -> 串行回退”。
- 命令运行无输出：检查 `logs/*.log` 与终端 traceback。
