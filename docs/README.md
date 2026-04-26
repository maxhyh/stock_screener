# 文档导航

## 先看这里

- 日常运行入口：看根目录 `README.md`
- 专家审查入口：看 `docs/EXPERT_REVIEW_BRIEF.md`
- 专家审查提示词：看 `docs/EXPERT_REVIEW_PROMPT.md`
- 代码与目录总览：看 `docs/PROJECT_INDEX.md`
- 每日操作步骤：看 `docs/WORKFLOW.md`
- 脚本分层与用途：看 `scripts/README.md`

## 文档分层

### 1. 运行与维护

- `PROJECT_INDEX.md`：代码库总览、主入口、目录职责、维护约定
- `WORKFLOW.md`：日常操作流程、生产链路、常用命令
- `LOCAL_GUIDE.md`：本地部署与运行说明
- `DEPLOYMENT.md`：部署说明
- `CRON_SETUP.md`：定时任务配置

### 2. 策略与研究

- `EXPERT_REVIEW_BRIEF.md`：外部专家审查简报与当前 v7/v8 关键问题
- `EXPERT_REVIEW_PROMPT.md`：可复制给专家的完整审查提示词
- `SIGNAL_LOGIC.md`：MFTS 信号与规则逻辑
- `ML_TRAINING.md`：模型训练与标签口径
- `MFTS_OPTIMIZATION.md`：历史优化记录与策略演进
- `OPTIMIZATION_STATUS.md`：当前平台化/优化状态
- `PLATFORM_REFACTOR_BLUEPRINT.md`：P1/P2/P3 平台化蓝图

### 3. 任务与历史

- `TODO.md`：待办事项
- `archive/README.md`：归档文档入口
- `archive/SERVER_GUIDE.md`：旧服务器部署说明
- `archive/scripts/README.md`：归档脚本入口

## 维护原则

- 根 README 只保留“怎么开始”和“去哪看”
- `PROJECT_INDEX.md` 是代码结构的单一索引
- `WORKFLOW.md` 只写操作流程，不重复堆砌架构说明
- 研究结论文档优先更新原文，不再新增同主题重复文档
