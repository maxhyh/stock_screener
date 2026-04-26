# 平台化骨架 Phase 1

本轮不是“完整做完 8 个平台能力”，而是为每一项补上可落地、可扩展的第一层基础设施。

## 新增基础层

1. 真实交易执行层
- `core/platform/execution_lifecycle.py`
- 提供订单状态机、重试计数、部分成交/撤单/拒单/失败的统一生命周期模型。

2. 统一的组合与风险引擎
- `core/platform/portfolio_engine.py`
- `core/platform/risk_engine.py`
- 提供组合约束、统一权重构建、行业上限和组合暴露汇总。

3. 数据版本化与可复现
- `core/platform/context.py`
- `core/platform/run_manifest.py`
- 为主流程生成 `run manifest`，记录 `run_id`、参数、数据版本、配置 fingerprint、步骤结果。

4. 研究平台能力
- `core/platform/experiment_registry.py`
- 提供实验注册、模型/指标/lineage 记录能力。

5. 观测、告警与运维
- `core/platform/events.py`
- `core/platform/monitoring.py`
- 定义统一平台健康快照与告警规则，复用 `utils.alert.py` 发送消息。

6. 服务化 / API 化
- `web/routes/platform.py`
- 暴露平台健康、最新运行、实验注册表查询接口。

7. 权限、安全与治理
- `core/platform/security_governance.py`
- 统一读取安全配置、生成配置 fingerprint、记录配置变更日志。

8. 性能体系
- `core/platform/profiling.py`
- `scripts/platform_profile_baseline.py`
- 提供 profiling 基线工具，先从 `calc_indicators()` 建立样本级耗时与内存基线。

## 已接入主链路

- `scripts/daily_all.py`
  - 写入 `output/platform/runs/*.json`
  - 失败/成功会产出平台级运行记录
- `scripts/train_mfts_lgbm.py`
  - 训练完成后登记实验注册表
- `web/app.py`
  - 注册平台路由

## 下一阶段

1. 把 `execution_lifecycle` 真正接入 `live_broker.py` 的 gateway 提交流程。
2. 把 `portfolio_engine` 下沉成回测/P2/前置风控的共同入口，而不只是基础模块。
3. 在 `daily_all.py` 之外，把 `quant_portfolio_backtest.py`、`quant_p2_paper_trade.py` 也纳入 `run manifest`。
4. 把实验注册扩展到 walk-forward、optimize、anti-overfit 流程。
