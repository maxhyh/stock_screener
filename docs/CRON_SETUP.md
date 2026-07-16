# MFTS 本地定时任务指南

> **状态：暂停安装。** 本文保留为历史自动化设计参考。当前只读 ODS 迁移后的
> 复权、PIT、官方交易约束和模型 lineage P0 问题尚未闭环，不应安装旧 cron，
> 不应自动下载数据、重训模型、刷新 P2 或 promotion evidence。

未来恢复定时任务时，必须使用
`/opt/homebrew/Caskroom/miniforge/base/envs/stock/bin/python`，只读
`/Users/max/Data/ashare-source-data/ods`，并先通过 `scripts/project_doctor.py`、
manifest/PIT/data-generation gate。以下命令和时间表在恢复前均不属于生产建议。

当前推荐把 `scripts/daily_all.py` 作为日常生产编排入口，而不是把
`daily_incremental_update.py`、`daily_ml_select.py`、`daily_verify.py`、
`quant_p2_paper_trade.py` 这些脚本拆开分别调度。原因很简单：

- `daily_all.py` 已经是项目定义的生产主链路。
- 它默认会刷新 profile promotion gate 的 latest 工件。
- 统一入口能减少数据、风控、执行和档位治理的口径漂移。

## 推荐方案

使用项目内脚本自动生成并安装 cron：

```bash
cd /path/to/stock_screener
bash scripts/setup_cron.sh
```

脚本会自动：

- 识别当前项目目录
- 使用当前 `python3`（或 `VENV_PYTHON` 指定的解释器）
- 生成并安装本地 `crontab`
- 用 `daily_all.py` 写入盘后主链路和盘前执行链
- 让 promotion gate 跟随盘后主链路自动刷新

## 默认任务计划

安装脚本会写入以下任务：

- 工作日 16:10：`daily_all.py --mode latest --with-p1 --with-p3-consistency`
  - 覆盖数据更新、扫描、ML 选股、验证、P1、P3 和 profile promotion gate
- 工作日 09:15：`daily_all.py --mode verify-only --with-p2 --skip-profile-gate`
  - 仅走盘前纸面执行链，避免重复刷新 promotion gate
- 周日 20:00：`auto_retrain.py --check-only`
- 周日 21:00：`verify_historical.py --days 30`
- 每月15日 03:00：清理 90 天前日志/CSV

## 常用命令

```bash
# 查看任务
crontab -l

# 编辑任务
crontab -e

# 删除全部任务（谨慎）
crontab -r

# 查看日志
tail -f logs/cron_daily_all.log
tail -f logs/cron_p2.log
tail -f logs/historical.log
```

## 手动配置示例

如果你不想运行安装脚本，可手动添加（请替换路径）：

```cron
10 16 * * 1-5 cd /path/to/stock_screener && /path/to/python scripts/daily_all.py --mode latest --with-p1 --with-p3-consistency >> logs/cron_daily_all.log 2>&1
15 9 * * 1-5 cd /path/to/stock_screener && /path/to/python scripts/daily_all.py --mode verify-only --with-p2 --skip-profile-gate >> logs/cron_p2.log 2>&1
0 20 * * 0 cd /path/to/stock_screener && /path/to/python scripts/auto_retrain.py --check-only >> logs/cron_retrain.log 2>&1
0 21 * * 0 cd /path/to/stock_screener && /path/to/python scripts/verify_historical.py --days 30 >> logs/historical.log 2>&1
```

## Promotion Gate 说明

盘后主链路默认会执行 `scripts/quant_refresh_promotion_gate.py`，并刷新：

- `output/backtest/quant_profile_rolling_compare_summary_latest.csv`
- `output/backtest/p2_rolling_replay_summary_latest.csv`
- `output/backtest/quant_profile_promotion_review_latest.csv`
- `output/backtest/promotion_decision_latest.json`

注意：

- 这一步会自动产出最新治理结论，但**不会**自动修改 `default_profile`。
- 默认档位变更仍应通过 `scripts/quant_apply_promotion_decision.py` 严格按决策文件执行。

## macOS 用户说明

macOS 除了 `cron`，也可以用 `launchd`。若你已经在用 `launchd`，可继续使用，不冲突。

## 故障排查

- 任务不执行：先检查 `crontab -l` 是否存在目标任务。
- 任务执行失败：先看 `logs/*.log` 的 traceback。
- 命令行可运行但 cron 失败：通常是环境变量差异，请在命令里写绝对路径的 Python。
