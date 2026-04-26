# MFTS 信号逻辑文档

## 信号触发条件详解

本文档详细说明每种买入信号的触发条件，对应 Pine Script v6.1。

---

## 🔴 L1 抢筹信号 (Deep Oversold)

**Pine Script 对应行**: 780-798

### 触发条件

```
L1 = is_deep_oversold AND is_basic_safe AND is_confirm AND score >= (threshold - 2)
```

| 条件 | 说明 |
|------|------|
| `is_deep_oversold` | Z-Score < -1.96 **或** BIAS < adaptive_buy_deep |
| `is_basic_safe` | 非跌停、非暴跌、非流动性陷阱、涨停未触板 |
| `is_confirm` | 缩量 **或** 红K **或** 底部放量 **或** 恐慌止跌 |
| `score >= 2.0` | Alpha评分 >= (4.0 - 2.0) |

### 确认条件详解

- **缩量**: `volume < vol_ma5 * 1.2`
- **红K**: `close > open`
- **底部放量**: `close < close[5] AND volume > vol_ma20 * 1.5 AND 红K`
- **恐慌止跌**: `volume > vol_ma20 * 1.8 AND 阴线 AND 下影线 > 40%`

---

## 🟠 L2 建仓信号 (Mid Oversold)

**Pine Script 对应行**: 800-802

### 触发条件

```
L2 = ((is_mid_oversold AND NOT is_deep_oversold AND is_trend_pass) OR trend_pullback) 
     AND multi_factor_pass
```

| 条件 | 说明 |
|------|------|
| `is_mid_oversold` | Z-Score < -1.50 **或** BIAS < adaptive_buy_mid |
| `NOT is_deep_oversold` | 排除深度超跌（应由L1处理） |
| `is_trend_pass` | close > MA120 **或** 超跌豁免 |
| `trend_pullback` | 趋势回调买点（见下方） |
| `multi_factor_pass` | Alpha评分 >= 4.0 |

### 趋势回调类型 (Pine Script lines 774-778)

1. **严格版 (strict)**: `close ∈ [MA20*0.98, MA20*1.02] AND MA5 > MA20 AND 红K AND vol > vol_ma5*0.7`
2. **宽松版 (relaxed)**: `close ∈ [MA20*0.95, MA20*1.05] AND MA5 > MA20 AND vol > vol_ma5*0.5`
3. **波浪版 (wave)**: `close > MA20 AND close ∈ [MA5*0.97, MA5*1.03] AND ADX > 20 AND 红K`

---

## 🟣 L3 加仓信号 (Light Oversold / Trend)

**Pine Script 对应行**: 804-807

### 触发条件

```
L3 = (is_light_os OR trend_pullback OR buy_level3_base_trend) 
     AND is_trend_pass AND multi_factor_pass
```

| 条件 | 说明 |
|------|------|
| `is_light_os` | BIAS ∈ [adaptive_buy_mid, adaptive_buy_light) AND 红K |
| `trend_pullback` | 同 L2 的三种回调类型 |
| `buy_level3_base_trend` | BIAS ∈ (-3, 2) AND ADX > 25 AND close 接近 MA5 |

---

## 🔵 趋势追踪信号 (Trend Following)

**Pine Script 对应行**: 812-830

### 1. 突破买入 (Breakout)

```
close > high_20[1] AND volume > vol_ma20 * 1.3 AND ADX > 25 AND RSI < 80
```

### 2. 动量追踪 (Momentum)

```
close > MA5 > MA20 > MA120 AND close > close[5] * 1.03 AND RSI ∈ (50, 75) AND MACD金叉
```

### 3. 底部启动 (Bottom Breakout)

```
close > MA20 AND close[1] < MA20 AND volume > vol_ma20 * 1.5 AND 近期曾超跌
```

---

## 📊 Alpha 评分系统

### 加分项

| 因子 | 条件 | 分值 |
|------|------|------|
| Mom_5 | < -15% | +2.0 |
| Mom_20 | < -25% | +2.5 |
| BIAS | < deep*1.3 + 放量 | +2.0 |
| RSI | < 20 | +1.2 |
| 52周位置 | < 30% | +1.0 |
| Stopping Volume | 阴线+放量+窄幅 | +1.0 |

### 扣分项

| 风险 | 条件 | 分值 |
|------|------|------|
| Falling Knife | CLV < -0.7 + 宽幅 + 阴线 | -5.0 |
| Liquidity Lock | 跌幅 > 8% + 缩量 90% | -10.0 |

---

## 🛡️ 分层豁免机制

| 超跌等级 | BIAS 条件 | Z 条件 | 流动性过滤 | 趋势过滤 |
|----------|----------|--------|------------|----------|
| 极度 | < -15% | < -2.5 | ✅ 豁免 | ✅ 豁免 |
| 深度 | < -10% | < -2.0 | 放宽至 0.4 | ✅ 豁免 |
| 普通 | >= -10% | >= -2.0 | 标准 0.6 | 标准 |
