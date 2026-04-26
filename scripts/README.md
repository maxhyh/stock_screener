# 脚本分层说明

## 使用原则

- 优先使用“生产主链路”脚本
- 研究/分析脚本按需运行，不要混入日常生产
- 修复/维护脚本仅在排障时使用

## A. 生产主链路

- `daily_all.py`：生产编排总入口
- `daily_incremental_update.py`：主数据增量更新
- `daily_ml_select.py`：ML 每日推荐
- `daily_verify.py`：推荐验证
- `daily_mfts_select.py`：规则扫描的单独入口
- `quant_p1_analytics.py`：P1 风险暴露/归因/容量报告
- `quant_p2_paper_trade.py`：P2 纸面交易执行
- `quant_exec_consistency_report.py`：P3 回测/执行一致性报告
- `quant_memory_evolve.py`：项目记忆系统刷新；从长期记忆提取可复用条目到 `memory/actives.md`

## B. 回测与参数研究

- `quant_portfolio_backtest.py`：组合回测主入口
- `quant_optimize.py`：参数优化
- `quant_walk_forward.py`：Walk-forward 稳健性评估
- `quant_anti_overfit_pipeline.py`：抗过拟合流水线
- `run_quant_profile.py`：档位回测入口
- `quant_profile_ab_compare.py`：不同档位对比
- `quant_signal_refactor_compare.py`：特征重构前后对比
- `quant_signal_pretrade_alignment_report.py`：信号与前置风控对齐分析
- `research/capacity_estimation.py`：容量估计

## C. 历史生成与数据补齐

- `history/generate_historical_scans.py`
- `history/generate_historical_scans_6m.py`
- `history/generate_historical_ml.py`
- `verify_historical.py`
- `build_benchmark_hs300.py`
- `migrate_outputs.py`

## D. 训练与因子分析

- `train_mfts_lgbm.py`
- `research/analyze_factor_ic.py`
- `analyze_signal_performance.py`
- `research/daily_hybrid_select.py`
- `batch_ml_predict.py`
- `auto_retrain.py`
- `research/capacity_estimation.py`

## E. 修复与运维工具

- `project_doctor.py`：项目健康检查
- `quant_memory_evolve.py --check`：检查项目记忆文件是否完整
- `fix_missing_data.py`：历史缺口检测/补数
- `fix_volume_unit_by_date.py`：成交量单位修复
- `repair_missing_volume.py`：成交量缺失修复
- `repair_missing_ohlc.py`：OHLC 缺失修复
- `daily_risk_report.py`：日风险报告
- `setup_local.sh`
- `setup_cron.sh`

## F. 兼容/历史脚本

- `history/backtest_5y.py`
- `history/backtest_comparison.py`
- `backtest_mfts_lite.py`
- `history/backtest_mfts_6m.py`
- `history/backtest_v62_compare.py`

以下脚本实现已迁移到 `archive/scripts/`，不再作为 `scripts/` 主目录入口保留：

- `archive/scripts/backtest.py`
- `archive/scripts/optimize.py`
- `archive/scripts/qlib_integration.py`
- `archive/scripts/debug_download.py`

## 建议约定

- 新增脚本前，先判断能否并入现有主链路脚本
- 新脚本必须在本文件登记用途
- 若脚本只服务一次性分析，完成后应归档或删除，避免长期堆积
