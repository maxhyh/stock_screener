# Expert Review Prompt

Copy the following prompt for an external expert review.

```text
你现在是一位顶级量化策略研究负责人、资深组合经理、A 股量化金融工程专家、实盘执行与风控审查专家。请你通过 GitHub 仓库对这个 A 股日频量化选股与纸面执行平台做一次严格、专业、批判性的项目审查。

仓库地址：
https://github.com/maxhyh/stock_screener

请不要做代码风格审美点评，重点审查：
1. 策略逻辑是否有真实、可持续 alpha。
2. 回测是否可信，是否存在 look-ahead bias、选择偏差、幸存者偏差、执行可得性高估。
3. A 股机制是否处理专业，包括 T+1、涨跌停、停牌、ST、北交所过滤、印花税、ADV 容量、行业拥挤和主题抱团。
4. 研究层收益是否能穿透到 P2 paper 执行层。
5. 组合构建是否专业，是否显式约束行业、单票、ADV participation、风格暴露、换手和成本。
6. promotion gate 是否足够严格，是否能防止“研究强、执行弱”的 profile 升档。
7. 当前 v7/v8/v9 优化方向是否正确，是否还存在伪 alpha 或执行口径残差。

项目背景：
这是一个面向中国 A 股市场的日频量化选股与纸面执行平台。系统目标不是直接接真实券商，而是先把“研究 -> 信号 -> 回测 -> 风控 -> 纸面执行 -> 一致性诊断 -> 档位治理 -> 自我记忆演化”这条链路打磨到专业水准。

核心模块请重点查看：
- `README.md`
- `docs/PROJECT_INDEX.md`
- `docs/EXPERT_REVIEW_BRIEF.md`
- `config/quant_live_profiles.json`
- `core/platform/portfolio_engine.py`
- `core/risk/pretrade.py`
- `scripts/daily_ml_select.py`
- `scripts/quant_portfolio_backtest.py`
- `scripts/quant_p2_paper_trade.py`
- `scripts/quant_p2_rolling_replay.py`
- `scripts/quant_p2_shadow_diagnosis.py`
- `scripts/quant_alpha_execution_attribution.py`
- `scripts/quant_profile_promotion_review.py`
- `schemas/promotion_decision.schema.json`
- `memory/README.md`
- `memory/actives.md`
- `memory/learnings.md`
- `tests/`

当前策略结构：
- 研究信号层包括 ML 分数、signal quality、feature refactor/stability、liquidity、execution overlay。
- 排名层负责候选排序，但目标方向是让最终持仓权重由组合层决定。
- 过滤层包含 ST、涨跌停、停牌、最低价格、最低成交额、行业约束、ADV participation、风格暴露等。
- 组合层正在向 capacity/crowding-aware optimizer 演进。
- 执行层包括 P2 paper trade、rolling replay、shadow diagnosis、execution consistency。
- 治理层通过 promotion review 和 schema gate 控制 profile 升档，默认不允许只凭研究回测升档。

当前关键状态：
- 默认档仍为 `quality_regime`。
- v7 `quality_regime_candidate_v7_industry_balance` 行业集中被压住，但收益还没有穿透到执行层。
- v7 60/90/120 P2 执行后 NAV 仍弱，60/90 日仓位利用率不足。
- v7 invested-weight 行业集中约 31.86%，NAV-weight 行业集中约 6.21%，行业治理方向是对的。
- v7 ADV blocked rows 约 105，仍未达到小于 100 的硬目标。
- 2026 年 3 月底 blocked order 集中爆发，主要来自 `entry_not_tradable / exit_not_tradable`，不是单纯 ADV。
- 当前不应升档 v7；v8 `quality_regime_candidate_v8_reserve_pool` 已修复一部分“容量约束后现金过高”问题，方式是扩展候选池、clip 后递补、P2 pretrade 阶段对买入不可交易/ADV/行业阻塞做 reserve 替换。
- v8 使用 profile 隔离 daily 信号重跑了 60/90/120 P2：NAV 约 `-5.33% / -11.74% / -16.09%`，MDD 约 `-8.10% / -12.78% / -16.79%`，target-weight mean 约 `34.3% / 36.1% / 37.2%`。
- v8 行业均值约束改善，但 ADV/risk blocked rows 仍很重；shadow diagnosis 约 `1017` ADV blocked rows，3 月底和 4 月初仍有 `entry_not_tradable / exit_not_tradable` 集中爆发。
- v8 alpha attribution 不支持升档：raw ML top、optimizer、P2 fill 的平均 forward return 均为负。v8 应继续 shadow，不允许直接升档。
- v9 `quality_regime_candidate_v9_exec_state` 是新建 shadow 档，不是 promotion candidate。它不放松风控追收益，而是把 reserve pool 上游改成 capacity-safe 排序，并在 P2 broker 中加入 blocked-order 状态机。
- v9 重点处理 2026-03-30、2026-04-07 这类买入不可交易和卖出阻塞集中爆发：blocked sell 会被记录为持续状态，达到阈值时可冻结新买入，避免把卖不掉的风险当作可释放现金/风险预算。
- v9 的新增证据字段包括 `portfolio_rank_score`、`reserve_safe_score`、`reserve_capacity_score`、`blocked_sell_current_weight`、`blocked_exit_buy_freeze`、`blocked_exit_freeze_orders`、`blocked_state_max_consecutive_days` 等。v9 仍需要独立 60/90/120 P2 replay 后才可评价，不允许凭实现本身升档。

请输出：
A. 总体判断：这个项目更像真实可演进的量化平台，还是复杂回测工程？
B. 最严重的 5 个策略/回测/执行问题，按优先级排序。
C. 对信号层、过滤层、排名层、组合层、执行层、治理层分别评价。
D. 判断当前收益最可能来自真实 alpha、行业/小盘暴露、低容量偏差、执行口径残差，还是混合来源。
E. 明确指出当前最可能的伪 alpha 来源。
F. 审查 v7/v8 方向是否正确，以及 v9 capacity-safe reserve 和 blocked-order 状态机是否真正解决执行断点。
G. 检查 promotion gate 是否足以阻止错误升档。
H. 给出未来 2 周和 1 个月最应该做的具体改造，不要泛泛而谈。
I. 如果你认为某些模块不可信或有重大偏差，请直接指出，不要迎合。
```
