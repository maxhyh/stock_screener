# 文档导航

## 先看这里

- 日常运行入口：看根目录 `README.md`
- 专家审查入口：看 `docs/EXPERT_REVIEW_BRIEF.md`
- 专家审查提示词：看 `docs/EXPERT_REVIEW_PROMPT.md`
- 代码与目录总览：看 `docs/PROJECT_INDEX.md`
- 文档与 Skill 体系审查：看 `docs/DOCUMENTATION_AND_SKILLS.md`
- 每日操作步骤：看 `docs/WORKFLOW.md`
- 脚本分层与用途：看 `scripts/README.md`
- Codex 工程纪律：看 `skills/audit-a-share-quant-project/references/codex-engineering-discipline.md`
- 当前 P0 修复设计：看 `superpowers/specs/2026-07-16-p0-evidence-remediation-design.md`
- 当前 P0 修复总控计划：看 `superpowers/plans/2026-07-16-p0-evidence-remediation-master.md`

## 文档分层

### 1. 运行与维护

- `PROJECT_INDEX.md`：代码库总览、主入口、目录职责、维护约定
- `DOCUMENTATION_AND_SKILLS.md`：文档职责边界、skill 清单、重复/冲突审查
- `WORKFLOW.md`：日常操作流程、生产链路、常用命令
- `LOCAL_GUIDE.md`：本地部署与运行说明
- `DEPLOYMENT.md`：部署说明
- `CRON_SETUP.md`：历史定时任务设计；当前 P0 数据/模型问题闭环前暂停安装
- `../skills/audit-a-share-quant-project/references/codex-engineering-discipline.md`：Codex 在本项目中的工程纪律与验证边界

### 2. 策略与研究

- `EXPERT_REVIEW_BRIEF.md`：外部专家审查简报；提交给专家前必须刷新到最新 artifacts
- `EXPERT_REVIEW_PROMPT.md`：可复制给专家的完整审查提示词
- `SIGNAL_LOGIC.md`：MFTS 信号与规则逻辑
- `ML_TRAINING.md`：模型训练与标签口径
- `MFTS_OPTIMIZATION.md`：历史优化记录与策略演进
- `OPTIMIZATION_STATUS.md`：ODS 迁移前的平台化/优化历史流水；不能作为当前证据
- `PLATFORM_REFACTOR_BLUEPRINT.md`：历史 P1/P2/P3 平台化蓝图

### 3. 任务与历史

- `TODO.md`：历史待办记录；当前路线以 memory 为准
- `archive/README.md`：归档文档入口
- `archive/SERVER_GUIDE.md`：旧服务器部署说明
- `archive/scripts/README.md`：归档脚本入口

## 维护原则

- 根 README 只保留“怎么开始”和“去哪看”
- `PROJECT_INDEX.md` 是代码结构的单一索引
- `WORKFLOW.md` 只写操作流程，不重复堆砌架构说明
- 研究结论文档优先更新原文，不再新增同主题重复文档
- 当前工作状态先以 ODS manifests/data-quality、模型 lineage、`memory/profile.md` 和 `memory/actives.md` 为准；只有同一数据代际的 P2/shadow/promotion artifacts 才能参与升档判断
- 外部专家审查不是每轮默认动作；只有不确定、战略分叉或接近升档时才刷新审查包
