# Expert Review Prompt

> 更新日期：2026-07-16
> 审查阶段：ODS 数据与模型证据链 P0 审查，不是 profile promotion 审查

```text
你现在是一位顶级量化策略研究负责人、资深组合经理、A 股量化金融工程专家、
实盘执行与模型风险审查专家。请通过 GitHub 仓库，对这个 A 股日频量化选股、
回测、组合构建和 P2 纸面执行平台进行一次严格、独立、批判性的专业审查。

仓库地址：
https://github.com/maxhyh/stock_screener

审查纪律：

1. 不要迎合项目当前判断，不要做代码风格审美点评。
2. 优先检查会虚增 alpha、低估回撤或污染执行证据的结构性问题。
3. 明确区分：代码直接证明的事实、根据代码作出的推断、因 GitHub 不含共享数据/
   模型二进制/output 而无法验证的事项。
4. 不要引用 ODS 迁移前的回测、P2、v7-v29 或 raw-model 数值证明当前收益。
5. 当前不是升档评审。除非上游 P0 数据和模型契约通过，否则不要建议新建 profile、
   放松风控、运行 promotion，或通过调参修饰收益。

项目定位与当前边界：

- 中国 A 股日频研究与纸面执行平台，链路为：
  数据 -> PIT universe -> 复权研究价格/标签 -> raw ML -> 排名/过滤 -> 组合目标权重
  -> pretrade -> P2 paper replay -> shadow diagnosis -> promotion gate -> memory。
- 默认运行环境是 Conda `stock`；所有验证应使用同一解释器和依赖代际。
- 共享数据根为 `/Users/max/Data/ashare-source-data`，项目只能读取，不能下载、修复、
  覆盖或写入。规范数据位于 `ods/`，分区应由同目录 `manifest.json` 约束。
- `current_snapshot_only` 只能作为当前/描述性快照，不能作为历史 PIT 数据。
- 默认 profile 仍是 `quality_regime`；v7-v29 全部是历史 shadow/diagnostic 档，
  没有任何候选获准升档。
- 默认容量验收规模是人民币 100 万元。20 日只作预警；60/90/120 日才可能成为
  promotion 主证据，但必须在 P0 修复后按同一冻结 ODS generation 全部重建。
- GitHub 不包含共享市场数据、模型 pickle、日志和大规模 output，因此本轮主要审查
  代码契约、数据 lineage、模型方法、执行语义和证据治理，不能独立确认历史收益数值。

请按以下顺序阅读：

1. `README.md`
2. `docs/EXPERT_REVIEW_BRIEF.md`
3. `memory/profile.md`、`memory/actives.md`、`memory/errors.md`
4. `docs/PROJECT_INDEX.md`、`docs/WORKFLOW.md`、`docs/ML_TRAINING.md`
5. `core/data/ashare_ods_loader.py`、`core/data/market_data_gateway.py`
6. `core/mfts_screener.py`、`scripts/train_mfts_lgbm.py`
7. `scripts/quant_raw_model_walkforward_diagnosis.py`
8. `scripts/daily_ml_select.py`、`core/platform/portfolio_engine.py`
9. `core/risk/pretrade.py`、`core/execution/paper_broker.py`
10. `scripts/quant_portfolio_backtest.py`、`scripts/quant_p2_paper_trade.py`
11. `scripts/quant_p2_rolling_replay.py`、`scripts/quant_profile_promotion_review.py`
12. `schemas/promotion_decision.schema.json`、`tests/`

当前项目自查发现以下 P0/P1 风险。请独立验证，不要直接接受这些结论：

1. ODS gateway 明确输出 `unadjusted` 研究 bars；`daily_adj_factor` 虽被关联，尚未
   明确用于 signal-date-safe 的研究特征和 open-to-open 标签。公司行动可能制造
   特征/标签断点。
2. 历史 panel 将窗口末日的 `instrument_master` 关联到整个窗口；历史 master 分区
   未证明是 PIT，可能把当前名称、ST、上市状态和行业带入过去，造成幸存者/PIT 污染。
3. adapter 会读取 manifest，但尚未完整强制 `available_at`、`visible_at`、row count、
   schema/hash、freeze status 和历史 replay 可见性。
4. execution path 用上一日 raw close 构造 `prev_close`，并按板块/ST 固定比例推断
   涨跌停，未优先消费 ODS 的官方 `pre_close`、`up_limit`、`down_limit`。
5. 最新本地模型早于 ODS 迁移，缺少 snapshot digest、price mode、feature schema 和
   loader lineage；模型标签为 H=3，而默认 profile 持有期为 H=8。
6. ODS 迁移前 H8/H10 raw-universe walk-forward 结论仍未通过全 7-fold gate；这些
   结果只能说明旧代际存在模型稳定性问题，不能证明新 ODS 代际已经失败或成功。
7. 默认档历史 daily evidence 曾出现 `score_weight`、portfolio-level industry/ADV/
   impact cap 为 0，以及 regime 单票上限高于 profile 配置的问题。请检查配置是否能
   在 daily selection、portfolio、pretrade、P2 和 promotion 间保持不可漂移的 lineage。
8. 多个过滤器在候选不足时可能 fallback 到未过滤池。请判断哪些只是排序偏好，哪些
   应是 fail-closed 硬门禁，以及 fallback 是否会悄悄恢复被禁股票。
9. 历史 P2 虽有 T+1、涨跌停、停牌、ST、北交所、印花税、ADV、blocked-order、
   reserve pool 和 sell-trap 机制，但必须检查其输入是否来自 signal-date 已知信息，
   target weight 是否被下游重算，以及不可卖仓位是否错误释放现金/风险预算。

请严格按以下结构输出：

A. 总体结论
- 这是可演进平台、复杂回测工程，还是两者混合？
- 当前是否具备可信 alpha 证据？是否可用于真实资金？给出明确 yes/no 结论。

B. P0/P1/P2 问题清单
- 按严重度列出最重要的 8-12 个问题。
- 每项给出文件和尽量精确的行号、失真机制、影响范围、修复方案和回归测试。

C. 数据与 PIT 专项审查
- 审查 ODS snapshot selection、manifest 可见性、冻结/修订、交易日历、as-of join、
  instrument/ST/行业/上市退市状态、BJ/特殊代码和幸存者偏差。
- 判断哪些字段能支持历史 PIT，哪些必须 fail closed，哪些只能作当前描述性信息。

D. 复权与价格语义专项审查
- 给出 adjusted research bars、label prices、raw execution prices、official pre-close/
  limit prices 的专业分层方案。
- 明确前复权/后复权或累计因子在历史 walk-forward 中如何避免使用未来因子。

E. 模型与标签专项审查
- 审查 H=3 模型与 H=8/H=10 目标错配、训练样本、预测符号、split、特征漂移、
  objective、fold 稳定性和 weak-regime 绝对收益失败。
- 给出 full 7-fold raw-universe gate 的最低验收标准，不接受 pooled 指标掩盖坏 fold。

F. 研究到执行链路审查
- 分别评价信号、过滤、排名、组合构建、pretrade、P2 broker、rolling replay 和
  promotion gate。
- 检查 target-weight checksum/lineage、成本、impact、ADV、行业、style、T+1、
  entry/exit tradability、blocked sell、reserve replacement 和 cash drag。

G. 伪 alpha 判断
- 判断历史收益最可能来自真实预测、行业/小盘/流动性 beta、复权/PIT 偏差、
  低容量偏差、执行口径残差、低仓现金防守，还是混合来源。
- 指出当前最危险的三个回测幻觉。

H. P0 修复与证据重建顺序
- 给出未来 2 周和 1 个月的具体顺序。
- 必须明确回答：先修哪些代码和数据契约；每步生成什么 artifact；什么验收失败时
  必须停止；何时才允许重新训练、raw-universe、capacity、daily signals、60/90/120
  P2、shadow 和 formal promotion review。
- 给出从旧证据到新证据的 generation ID/manifest/model/profile lineage 设计建议。

I. 最终决策
- 当前继续停留在数据/模型层，还是可以恢复 capacity/P2/profile？只能选择一个。
- 列出恢复 profile/P2 前必须全部满足的硬条件。
- 如果你不同意项目当前“冻结 profile/P2、先修 P0”的判断，请提供可验证的反证。

请直接指出重大偏差。不要因为项目模块多、测试多或治理流程完整，就默认策略具有
alpha；严格治理只能审查输入证据，不能把错误的数据代际变成可信收益。
```
