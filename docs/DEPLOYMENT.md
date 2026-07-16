# 本地运行指南

本项目仅支持本地研究和纸面执行，不接真实券商。默认 Python 环境为
Conda `stock`，市场数据来自共享只读 ODS。

## 1. 环境契约

```bash
cd /path/to/stock_screener
export ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data
conda run -n stock python scripts/project_doctor.py
```

不要为本项目创建新的 `.venv`，不要运行旧下载器，也不要向
`ASHARE_DATA_ROOT` 写入、修复或生成任何文件。

## 2. 数据契约

- 生产读取入口：`core/data/ashare_ods_loader.py`、`core/data/market_data_gateway.py`
- 规范数据目录：`$ASHARE_DATA_ROOT/ods/`
- 每个分区必须保留并校验同目录 `manifest.json`
- `current_snapshot_only` 只能用于当前/描述性信息，不能作为历史 PIT 数据
- `data/daily_all_5y.parquet`、旧 metadata CSV 和下载脚本已经退出生产链

## 3. 启动前端

```bash
scripts/start_web.sh
```

默认地址为 `http://127.0.0.1:5001`。启动脚本会使用 `stock` 环境，并避免
重复启动同名 `screen` 会话。

## 4. 手动运行

```bash
conda run -n stock python scripts/project_doctor.py
conda run -n stock python scripts/daily_ml_select.py
conda run -n stock python scripts/daily_all.py
```

当前存在复权研究价格、历史 PIT universe、官方涨跌停字段和模型 lineage
等 P0 审查项。在这些问题修复并重建同代际证据前，日常入口仅用于开发和
诊断，不代表策略已具备实盘或升档条件。

## 5. 输出目录

- `output/daily/`：日信号和 profile-isolated signal artifacts
- `output/backtest/`：回测、P2、shadow、promotion 和诊断 artifacts
- `logs/`：运行日志
- `models/`：本地模型 artifact，不提交 GitHub

所有输出都应记录 ODS snapshot/manifest、loader、模型和 profile lineage。
