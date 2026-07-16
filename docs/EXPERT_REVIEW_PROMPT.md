# Expert Review Prompt

> 更新日期：2026-07-16

下面的提示词用于对 GitHub 当前快照做一次独立、批判性的 A 股量化审查。本轮审查的重点已从“继续调 profile”转向数据 PIT、复权、模型代际一致性和 ODS 证据重建。

```text
你现在是一位顶级量化策略研究负责人、资深组合经理、A 股量化金融工程专家、实盘执行与风控审查专家。请你通过 GitHub 仓库对这个 A 股日频量化选股、回测、组合构建与 P2 纸面执行平台做一次严格、独立、批判性审查。

仓库地址：
https://github.com/maxhyh/stock_screener

请不要迎合，也不要把精力放在代码风格审美上。你的核心任务是判断：

1. 当前策略是否已经证明有可持续、可执行 alpha。
2. 数据、特征、标签、回测和 P2 证据是否存在 look-ahead、PIT 污染、幸存者偏差、复权错误或修订后快照污染。
3. A 股 T+1、涨跌停、停牌、ST/风险警示、除权除息、印花税、北交所、ADV 容量和卖出阻塞是否被专业处理。
4. 研究层、组合层、pretrade、P2 broker 和 promotion evidence 是否真正同口径。
5. 项目是真实可演进的量化平台，还是一套复杂筛选器和回测工程。

项目定位：

- 中国 A 股日频选股与纸面执行平台。
- 链路为“数据 -> 原始特征/标签 -> ML/quality/refactor 排名 -> 组合目标权重 -> pretrade -> P2 paper replay -> shadow diagnosis -> promotion gate -> memory”。
- 默认 profile 仍是 `quality_regime`，所有 v7-v29 候选都只是 shadow/diagnostic，没有正式升档。
- 默认容量验收为 100 万元人民币，20 日只用于预警，60/90/120 日才是 promotion 主证据。
- 项目已切换到共享只读 ODS 数据源，不提交市场大数据、模型 pickle、日志和 output 流水。

请先阅读：

- `README.md`
- `docs/EXPERT_REVIEW_BRIEF.md`
- `docs/PROJECT_INDEX.md`
- `docs/WORKFLOW.md`
- `memory/profile.md`
- `memory/actives.md`
- `memory/errors.md`
- `config/quant_live_profiles.json`
- `core/data/ashare_ods_loader.py`
- `core/data/market_data_gateway.py`
- `core/mfts_screener.py`
- `scripts/train_mfts_lgbm.py`
- `scripts/daily_ml_select.py`
- `core/platform/portfolio_engine.py`
- `core/risk/pretrade.py`
- `core/execution/paper_broker.py`
- `scripts/quant_portfolio_backtest.py`
- `scripts/quant_p2_paper_trade.py`
- `scripts/quant_p2_rolling_replay.py`
- `scripts/quant_profile_promotion_review.py`
- `tests/`

当前已知但尚未修复的关键风险，请你独立验证，不要直接接受项目结论：

1. ODS 行情网关明确输出 `unadjusted` 价格。`daily_adj_factor` 被 join，但研究特征和 open-to-open 标签尚未明确使用复权价格。
2. 历史 panel 使用窗口末日的 `instrument_master` 关联整个窗口。现有历史 master 分区可能含有当前名称、ST 和行业信息，未证明是 PIT。
3. adapter 会读取 manifest，但尚未强制校验 `available_at`/`visible_at`、row count、schema/hash 和 freeze status；最新快照也可能被历史 replay 直接选中。
4. 执行层用上一日 raw close 构造 `prev_close`，并通过板块/ST 固定比例推断涨跌停，没有优先使用 ODS 已提供的 `pre_close`/`up_limit`/`down_limit`。
5. 当前最新本地模型早于 ODS 切换，模型包不含数据 snapshot/price mode/feature-version lineage；其标签 H=3，而默认 profile 持有 H=8。
6. 旧 H8/H10 raw-universe walk-forward 结论为 `raw_walkforward_alpha_failed`，fold 通过率约 42.86%。在该问题修复前，不应继续新建 profile 或跑 promotion。
7. 数据源切换前的 P2、promotion、raw-model 和 profile artifacts 只能作为历史诊断，不能证明当前 ODS 代际的年化收益。
8. 默认档最新 daily evidence 显示最终组合使用 `score_weight`，portfolio-level industry/ADV/impact cap 为 0，且 regime 导出的单票上限为 6%，高于 profile 配置的 4%。
9. 多个过滤器在候选数不足时会 fallback 回未过滤池；请判断这些是合理的连续性机制，还是会使“硬门禁”变成无法审计的软偏好。

请严格回答以下问题：

A. 总体判断：这是真实可演进的量化平台，还是复杂回测工程？当前可否用于真实资金？
B. 按 P0/P1/P2 排序列出最严重的 8 个问题，每条给出文件/行号、影响和修复方案。
C. 专项审查 ODS snapshot/manifest/PIT 逻辑，判断是否有未来信息、修订后快照和幸存者偏差。
D. 专项审查复权方案，明确研究价格、标签价格和执行价格应如何分离，同时不引入新的 look-ahead。
E. 审查 H=3 模型与 H=8 profile 的错配，并评价当前 ML score 是否还有投资意义。
F. 评价信号层、过滤层、排名层、组合层、pretrade、P2 broker 和 promotion gate。
G. 判断当前所谓收益最可能来自真实 alpha、行业/小盘/流动性暴露、数据偏差、执行口径残差，还是混合来源。
H. 判断当前是否应继续 profile/capacity/P2 工作，还是应先完成 PIT/复权/模型重训。
I. 给出未来 2 周和 1 个月的具体修复顺序、验收门槛和“什么情况下必须停止”。
J. 如果你不同意项目当前的自我评估，请直接指出，不要妥协表述。

请将“已从代码直接验证的事实”、“根据代码做的推断”和“因 GitHub 不含大数据/模型/output 而无法验证的事项”分开陈述。
```
