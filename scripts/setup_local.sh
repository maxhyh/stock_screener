#!/bin/bash
echo "=== 设置本地运行环境 ==="
echo "正在安装依赖..."

# 安装基础依赖
pip install -r requirements.txt

# 单独安装关键组件 (可能会因编译问题失败，建议使用 conda)
echo "尝试安装 akshare 和 pyarrow..."
pip install akshare pyarrow --upgrade

if [ $? -eq 0 ]; then
    echo "✅ 依赖安装成功!"
else
    echo "⚠️ 部分依赖安装失败。"
    echo "如果是 Mac 用户，建议使用 Conda 安装:"
    echo "conda install -c conda-forge akshare pyarrow lightgbm flask pandas"
fi

echo ""
echo "=== 启动命令 ==="
echo "1. 启动Web服务: python web/app.py"
echo "2. 全流程日更: python scripts/daily_all.py (数据更新 + 扫描 + ML + 验证)"
echo "3. 仅增量更新: python scripts/daily_incremental_update.py"
echo "4. 立即扫描: python core/mfts_screener.py"
