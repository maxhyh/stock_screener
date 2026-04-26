# 项目索引

> 更新时间：2026-04-27

## 1. 生产主入口

按优先级只看这几处：

1. `python scripts/daily_all.py`
2. `python scripts/daily_incremental_update.py`
3. `python scripts/daily_ml_select.py`
4. `python core/mfts_screener.py`
5. `python web/app.py`

不确定从哪里开始时，默认从 `daily_all.py` 和 `web/app.py` 入手。

## 2. 目录职责

- `core/`：规则引擎、风控、执行抽象，属于核心业务代码
- `scripts/`：生产编排、训练、回测、修复、研究脚本
- `web/`：Flask 应用、路由、页面展示
- `config/`：统一配置入口
- `utils/`：公共工具函数
- `data/`：数据下载、适配和元数据缓存
- `tests/`：单元测试与链路测试
- `docs/`：流程、策略、部署、维护文档
- `archive/`：归档代码，仅供参考
- `output/`：运行产物，不作为源码维护
- `logs/`：日志产物，不作为源码维护

## 3. 代码主链路

### 数据层

- `data/download_5y_data.py`：首次全量下载
- `scripts/daily_incremental_update.py`：日更/补数
- `data/data_adapter.py`：外部数据格式转项目主数据格式

### 策略层

- `core/mfts_screener.py`：MFTS 规则扫描主实现
- `core/mfts_screener_v62.py`：v6.2 实验/对比版本
- `utils/signal_quality.py`：信号质量评分
- `utils/signal_refactor.py`：特征重构评分
- `utils/market_regime.py`：市场状态识别

### 交易与风控层

- `core/risk/pretrade.py`：前置风控硬门禁
- `core/execution/adapter.py`：执行抽象接口
- `core/execution/paper_broker.py`：纸面执行
- `core/execution/live_broker.py`：实盘/影子执行
- `core/platform/portfolio_engine.py`：capacity/crowding-aware 组合权重引擎

### 编排层

- `scripts/daily_all.py`：生产总编排
- `scripts/daily_ml_select.py`：每日推荐
- `scripts/daily_verify.py`：收益验证
- `scripts/quant_p1_analytics.py`：P1 风险分析
- `scripts/quant_p2_paper_trade.py`：P2 执行
- `scripts/quant_p2_rolling_replay.py`：P2 长窗滚动回放
- `scripts/quant_p2_shadow_diagnosis.py`：P2 shadow 诊断
- `scripts/quant_profile_promotion_review.py`：档位升档门禁
- `scripts/quant_exec_consistency_report.py`：P3 一致性

当前 profile 治理基线：`quality_regime` 仍为默认档；v7/v8/v9 均为 shadow 档。v9 聚焦 capacity-safe reserve 和 blocked-order 状态机，不能绕过 promotion gate。

### 展示层

- `web/app.py`：应用工厂与路由注册入口
- `web/routes/`：蓝图路由
- `web/services/`：数据服务层

## 4. scripts 分层

详情看 `scripts/README.md`，这里只保留核心判断：

- 生产运行：`daily_*`, `quant_p1_analytics.py`, `quant_p2_paper_trade.py`, `quant_exec_consistency_report.py`
- 研究回测：`quant_*`, `research/*`, `history/*`, `backtest_mfts_lite.py`, `analyze_signal_performance.py`
- 修复维护：`fix_*`, `repair_*`, `project_doctor.py`
- 兼容历史：`history/backtest_5y.py`, `history/backtest_comparison.py`, `history/backtest_mfts_6m.py`, `history/backtest_v62_compare.py`
- 已归档旧实现：`archive/scripts/backtest.py`, `archive/scripts/optimize.py`, `archive/scripts/qlib_integration.py`

## 5. 当前整理约定

- 根 README 负责导航，不再承担全部细节说明
- `docs/PROJECT_INDEX.md` 是代码入口索引
- `docs/WORKFLOW.md` 负责“怎么跑”
- `scripts/README.md` 负责“脚本能不能用、该不该用”
- 重复主题文档尽量合并，不再平行新增

## 6. 维护建议

- 日常只维护生产主链路，研究脚本按需整理
- 新增脚本前，先判断能否合并进现有脚本
- 新增文档前，先判断现有文档是否可以补充
- 临时分析脚本若不复用，应尽快归档或删除
- 一次性调试脚本统一进入 `archive/scripts/`
