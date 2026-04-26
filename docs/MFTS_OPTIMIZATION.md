# MFTS v6.2 优化指南

## 版本说明

**v6.2** 是基于IC分析和ML特征重要性优化的版本，相比v6.1有以下改进：

- T+1平均收益改善 **+0.14%**
- T+5平均收益改善 **+0.84%**

---

## 核心优化

### 1. 因子权重调整

| 因子 | v6.1权重 | v6.2权重 | 依据 |
|------|---------|---------|------|
| ATR% | 1.0 | **3.0** | IC=-0.051（最高） |
| Volume Ratio | 1.0 | **2.5** | ML特征重要性#1 |
| BIAS | 2.5 | 2.5 | 保持 |
| RSI | 1.2 | **1.8** | IC=-0.047 |
| 52W Position | 0 | **2.0** | ML特征重要性#2 |
| ADX | 0.5 | **0.1** | IC=-0.011（最低） |

### 2. 动态阈值

```python
# 根据市场波动性调整
高波动市场: BIAS阈值 = -12%
标准市场:   BIAS阈值 = -8%
低波动市场: BIAS阈值 = -6%
```

### 3. 信号过滤

```python
MIN_ALPHA_SCORE = 5.0    # 最低Alpha评分（v6.1无限制）
MIN_VOLUME_RATIO = 1.2   # 最低量比
MIN_ATR_PERCENT = 3.0    # 避免僵尸股
MAX_POS_52W = 40         # 避免追高
```

### 4. 风控增强

```python
NEW_STOCK_DAYS = 120     # 上市至少120天（v6.1为60天）
MAX_TURNOVER = 25        # 最大换手率
```

---

## 使用方法

### 纯规则选股（v6.2）

```bash
cd /path/to/stock_screener
python scripts/daily_mfts_select.py
```

### v6.2 + ML融合选股

```bash
# 默认 ML权重60% + 规则权重40%
python scripts/research/daily_hybrid_select.py

# 自定义权重
python scripts/research/daily_hybrid_select.py --ml-weight 0.7
```

---

## 回测对比

| 指标 | v6.1 | v6.2 | 改善 |
|------|------|------|------|
| T+1胜率 | 43.34% | 43.34% | - |
| T+1收益 | -0.58% | -0.44% | +0.14% |
| T+5收益 | -1.32% | -0.48% | +0.84% |

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `core/mfts_screener_v62.py` | v6.2核心代码 |
| `scripts/research/daily_hybrid_select.py` | v6.2+ML融合选股 |
| `scripts/history/backtest_v62_compare.py` | v6.1 vs v6.2对比回测 |
