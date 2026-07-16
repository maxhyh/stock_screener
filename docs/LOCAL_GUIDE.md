# MFTS 本地运行指南

## 环境配置

本项目已配置好本地运行环境，**无需依赖云服务器**。当前推荐通过项目脚本启动前端，避免手动环境差异。

### 前置条件
- macOS 系统
- Anaconda/Miniconda 已安装
- `stock` 虚拟环境已创建，或使用本机实际 Python 路径覆盖 `MFTS_PYTHON`

### 依赖版本
- Python: 3.10
- AkShare: 1.16.72 (兼容 Mac 的版本)
- Flask, Pandas, LightGBM 等核心组件

---

## 日常使用

### 1. 启动 Web 服务
```bash
conda activate stock
cd /path/to/stock_screener
scripts/start_web.sh
```
访问: http://127.0.0.1:5001

停止后台服务：
```bash
screen -S stock_screener_web -X quit
```

如机器使用不同环境：
```bash
MFTS_PYTHON=/path/to/python scripts/start_web.sh
```

### 2. 每日 ODS 覆盖检查与运行 (收盘后)
```bash
conda activate stock
cd /path/to/stock_screener
python scripts/daily_all.py
```

此脚本会先验证共享只读 ODS 覆盖目标交易日，再执行：
1. MFTS 规则选股扫描
2. ML 模型预测

可选扩展（平台化）：
```bash
# 追加 P1 风险归因 + P2 纸面 OMS（建议先 dry-run）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-broker paper --p2-dry-run

# 追加 P3 一致性偏差报告
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --with-p3-consistency --p2-broker paper --p3-broker paper --p2-dry-run
```

### 3. 单独执行选股扫描
```bash
python core/mfts_screener.py
```

### 4. 检查共享数据源
```bash
export ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data
python scripts/project_doctor.py
```

### 5. 信号绩效分析 (新增)
```bash
python scripts/analyze_signal_performance.py
```
- 功能：分析历史选股信号的胜率、收益率
- 支持：按信号类型、超跌等级、月度趋势分析
- 结果：可在 Web 界面 "信号绩效分析" 页面查看 (http://127.0.0.1:5001/signal-analysis)

### 6. 平台化模块（P1/P2）
```bash
# P1 风险暴露/归因/容量
python scripts/quant_p1_analytics.py --write-latest

# P2 纸面 OMS
python scripts/quant_p2_paper_trade.py --broker paper --write-latest
python scripts/quant_p2_paper_trade.py --broker live --live-mode shadow --write-latest
python scripts/quant_p2_paper_trade.py --broker paper --use-recommendation --recommend-rank 1 --dry-run --write-latest

# 一键编排透传推荐参数到 P2
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-broker paper --p2-dry-run --p2-use-recommendation --p2-recommend-rank 1

# 反过拟合流水线（先WF找稳定区，再robust优化）
python scripts/quant_anti_overfit_pipeline.py --start 2025-01-01 --end 2026-03-20

# P3 一致性报告
python scripts/quant_exec_consistency_report.py --broker paper --write-latest
```

---

## 故障排除

### AkShare 相关问题
如果遇到 `curl_cffi` 安装错误，使用以下版本：
```bash
pip install akshare==1.16.72 --no-cache-dir
```

### LightGBM `libomp.dylib` 缺失（macOS）
如果运行 `daily_ml_select.py` 报 `Library not loaded: @rpath/libomp.dylib`：
```bash
brew install libomp
```
然后重启终端并重新激活环境再执行脚本。

### 共享 ODS 不可用
本项目只读共享 ODS，不能自行下载或修复。请联系数据供应链维护方，并用
`python scripts/project_doctor.py` 确认恢复后的覆盖情况。

---

*最后更新: 2026-04-28*
