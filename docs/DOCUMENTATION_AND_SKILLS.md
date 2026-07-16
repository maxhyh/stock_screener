# 文档与 Skill 体系审查

> 更新时间：2026-07-16

## 1. 当前结论

本项目目前只有一个仓库内本地 skill：

- `skills/audit-a-share-quant-project`

这个设计是合理的。当前项目的大多数维护任务都围绕同一条 A 股量化链路展开：数据、信号、回测、组合、P2 执行、shadow 诊断、promotion gate、memory。继续保留一个 repo-specific skill，比拆成多个互相重叠的 skill 更稳。

当前没有发现仓库内多个 skill 重复触发或互相冲突的问题。项目 Skill 已统一为 `stock` Conda 环境、只读 ODS 数据源和数据代际优先审查。文档侧仍需防范两类风险：

- 部分早期文档保留旧下载器、本地 parquet、`.venv`、早期 profile 和 MFTS v6.1 等历史描述。
- ODS 迁移前的 P2、回测和 raw-model 数值仍存在于历史文档，容易被误当成当前可比证据。

处理原则：文档入口要分工清楚，策略事实以最新 artifacts、`config/quant_live_profiles.json`、promotion review 和 memory 为准；历史优化文档只作为背景，不作为当前 promotion 依据。

## 2. 信息源优先级

遇到冲突时，按这个顺序判断：

1. 当前只读 ODS manifests、数据质量检查和同代际 artifact lineage。
2. 当前模型的 label/horizon/feature schema 与 raw-universe walk-forward 证据。
3. 最新同代际 artifacts：P2 rolling replay、shadow diagnosis、promotion review、测试结果。
4. `config/quant_live_profiles.json`：profile 定义和当前 `default_profile`。
5. `memory/profile.md`、`memory/actives.md`、`memory/errors.md`：当前操作约束和已知陷阱。
6. `AGENTS.md`：agent 操作规则。
7. `docs/PROJECT_INDEX.md`、`docs/README.md`：仓库结构和文档导航。
8. `docs/EXPERT_REVIEW_BRIEF.md`、`docs/EXPERT_REVIEW_PROMPT.md`：外部审查包，提交给专家前必须刷新。
9. `docs/OPTIMIZATION_STATUS.md`、`docs/TODO.md`、`docs/MFTS_OPTIMIZATION.md`：历史优化记录，不能直接当作当前状态。

Memory 是证据路由，不是 promotion 真相。promotion 仍必须由 `scripts/quant_profile_promotion_review.py` 和生成 artifacts 决定。

## 3. Skill 清单

| Skill | 路径 | 职责 | 是否保留 | 冲突风险 |
| --- | --- | --- | --- | --- |
| `audit-a-share-quant-project` | `skills/audit-a-share-quant-project/SKILL.md` | 本项目 A 股量化审计、维护、执行可信、文档/架构体检 | 保留，作为唯一 repo-specific skill | 低 |

### 相关但不属于仓库的外部 skill

- `skill-creator`：用于创建或更新 skill 的通用规范。它是元工具，不应替代本项目 skill。
- `a-share-pine-audit`：面向 TradingView Pine Script 审计。仅在 Pine 脚本任务中使用，不应介入 Python 平台维护。
- GitHub / browser / documents 等插件 skill：工具型能力，不属于项目治理 skill。

## 4. Skill 结构评价

`audit-a-share-quant-project` 的结构符合 skill-creator 原则：

- `SKILL.md` 保留核心触发规则、审计顺序、维护模式。
- `references/` 存放细则：
  - `project-map.md`：代码入口和热点。
  - `maintenance-loop.md`：循环维护流程。
  - `codex-engineering-discipline.md`：Codex 工程纪律。
  - `priority-model.md`：问题优先级。
  - `audit-checklist.md`：审计清单。
  - `output-template.md`：输出格式。
- `scripts/` 存放确定性工具：
  - `find_audit_hotspots.py`
  - `build_maintenance_snapshot.py`
- `agents/openai.yaml` 提供 UI 元数据。

当前 skill 没有必要拆分。除非未来出现稳定、独立、反复执行且触发边界清晰的新工作流，例如“前端设计审计”或“P2 promotion artifact 打包”，否则继续更新现有 skill。

## 5. 重复与冲突审查

### 有意重复，保留

- `AGENTS.md` 与 `agent.md`：`AGENTS.md` 是权威；`agent.md` 是兼容入口。
- `docs/EXPERT_REVIEW_BRIEF.md` 与 `docs/EXPERT_REVIEW_PROMPT.md`：brief 是证据说明，prompt 是给专家复制的任务书。
- `AGENTS.md` 与 `codex-engineering-discipline.md`：前者是短规则，后者是详细工程契约。

### 需要警惕的重复

- `README.md` 和 `docs/WORKFLOW.md` 都包含运行命令。README 只保留快速入口；细流程放 `WORKFLOW.md`。
- `docs/OPTIMIZATION_STATUS.md` 和 `docs/EXPERT_REVIEW_BRIEF.md` 都记录策略演进。前者作为历史流水，后者只在需要专家审查前刷新。
- `docs/TODO.md` 仍有早期项目计划痕迹。不要用它判断当前 profile 状态。

### 已发现并修正的冲突

- 早期文档中的 `balanced` 默认档描述已过期；当前 `default_profile` 是 `quality_regime`。
- 早期“当前 holding_days=3”描述已过期；当前 `quality_regime.holding_days=8`。
- skill 目录中的 Python 缓存产物不属于 skill 内容，应保持清理。
- 旧 `daily_incremental_update.py`、`data/download_5y_data.py` 和 `data/daily_all_5y.parquet` 已退出生产数据链；当前只读入口是 `core/data/ashare_ods_loader.py` 与 `core/data/market_data_gateway.py`。
- 项目默认 Python 环境统一为 Conda `stock`，活动文档不再推荐 `.venv`。
- ODS 迁移前 artifacts 被标记为历史诊断，不能与迁移后的证据混合用于 promotion。

## 6. 文档职责边界

| 文档 | 职责 | 更新频率 | 注意事项 |
| --- | --- | --- | --- |
| `README.md` | 新人入口、快速启动、当前状态摘要 | 中 | 不承载完整策略历史 |
| `docs/README.md` | 文档导航 | 中 | 新增文档必须登记 |
| `docs/PROJECT_INDEX.md` | 代码入口与目录职责 | 中 | 代码结构变化时更新 |
| `docs/WORKFLOW.md` | 日常操作命令 | 中 | 不写 promotion 结论 |
| `docs/LOCAL_GUIDE.md` | 本机环境与前端启动 | 低 | 与 `scripts/start_web.sh` 保持一致 |
| `docs/EXPERT_REVIEW_BRIEF.md` | 专家审查证据包 | 按需 | 提交 GitHub 审查前必须刷新 |
| `docs/EXPERT_REVIEW_PROMPT.md` | 专家提示词 | 按需 | 必须和 brief 同步 |
| `docs/OPTIMIZATION_STATUS.md` | 历史优化流水 | 低 | 标记为历史，不作当前真相 |
| `docs/TODO.md` | 历史和人工待办 | 低 | 不作为当前路线图 |
| `memory/*.md` | 自我演化记忆 | 每轮有意义工作后 | 不能覆盖 promotion gate |

## 7. 维护规则

- 新增文档前，优先判断是否能更新 `docs/README.md`、`docs/PROJECT_INDEX.md`、`docs/WORKFLOW.md` 或本文件。
- 新增 skill 前，必须说明它为什么不能并入 `audit-a-share-quant-project`。
- 专家审查前必须刷新：
  - `docs/EXPERT_REVIEW_BRIEF.md`
  - `docs/EXPERT_REVIEW_PROMPT.md`
  - `docs/PROJECT_INDEX.md`
  - `memory/actives.md`
- 若文档与 fresh P2/shadow/promotion evidence 冲突，fresh evidence 胜出，并应修正文档。
- 若数据 manifest、PIT、复权、模型 horizon 或 lineage 存在 P0 问题，先冻结 profile/P2；此时 fresh P2 也不能覆盖上游数据可信度失败。
- 当前修复路线以 `docs/superpowers/specs/2026-07-16-p0-evidence-remediation-design.md` 和 `docs/superpowers/plans/2026-07-16-p0-evidence-remediation-master.md` 为准；阶段计划是执行清单，历史优化文档不能覆盖其停止条件。
