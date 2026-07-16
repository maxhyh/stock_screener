# ML 训练与 Raw-Universe 验证

> 当前状态：训练入口可用于诊断，但新模型不得进入 profile/P2，直到复权价格、
> 历史 PIT universe、manifest lineage 和标签 horizon 契约完成修复与验证。

## 1. 环境与数据

```bash
cd /path/to/stock_screener
export ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data
conda run -n stock python scripts/project_doctor.py
```

训练只读取共享 ODS，不下载或修改源数据。研究特征和 open-to-open 标签必须
使用 signal-date-safe 的复权价格；纸面执行必须保留原始成交价格和官方交易约束。

## 2. 标签契约

- 默认 profile `quality_regime` 当前 `holding_days=8`，因此默认研究 horizon 是 H=8。
- 训练、模型元数据、daily inference、raw-universe walk-forward 和 profile 必须使用同一 label mode/horizon。
- 当前模型 artifact 若仍为 H=3，不得用于 H=8 profile 或任何 promotion evidence。
- H=8/H=10 对照必须先通过完整 7-fold raw-universe gate，不能只看聚合均值。

## 3. 训练命令

```bash
conda run -n stock python scripts/train_mfts_lgbm.py \
  --label-mode open_to_open --label-horizon 8

conda run -n stock python scripts/train_mfts_lgbm.py \
  --label-mode open_to_open --label-horizon 10
```

模型 artifact 必须记录 `label_mode`、`label_horizon`、feature schema/version、
ODS datasets/snapshots/manifest digests、research price mode、训练验证日期边界和
代码/loader generation identity。

## 4. Raw-Universe Gate

在创建 profile 或运行 capacity/P2 前，至少验证：

- 全市场 eligible universe，而不是最终推荐子样本
- 7-fold walk-forward top bucket absolute return
- top-minus-pool spread、RankIC、hit rate 和 fold stability
- 行业、size、liquidity、beta、momentum 中性残差表现
- 2025Q4、2026Q1/Q2 等失效 fold 的独立结果
- 数据/特征漂移和样本覆盖

任一 fold 的绝对 top bucket 明显为负，或模型 horizon/lineage 不匹配时，停止
capacity、P2 和新 profile 工作。正确结果是保留负证据，不是继续堆 overlay。

## 5. 每日推理

```bash
conda run -n stock python scripts/daily_ml_select.py --top 30
```

每日 artifact 必须携带模型与 ODS lineage。next-day 实际涨跌停、停牌、成交额
只能用于事后 replay 诊断，不得进入 signal-date 选股或权重生成。
