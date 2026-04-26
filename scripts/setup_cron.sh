#!/bin/bash
# MFTS 本地定时任务配置脚本

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${VENV_PYTHON:-$(command -v python3 || true)}"
CRON_FILE="/tmp/mfts_cron.txt"

echo "================================"
echo "MFTS 本地定时任务配置"
echo "================================"
echo "项目目录: ${BASE_DIR}"

if [ -z "${PYTHON_BIN}" ]; then
  echo "❌ 未找到 python3，请先安装 Python 3"
  exit 1
fi

if [ ! -x "${PYTHON_BIN}" ]; then
  echo "❌ Python 不可执行: ${PYTHON_BIN}"
  exit 1
fi

mkdir -p "${BASE_DIR}/logs"

echo "Python解释器: ${PYTHON_BIN}"
echo ""
echo "1. 备份当前 crontab..."
crontab -l > "/tmp/crontab_backup_$(date +%Y%m%d_%H%M%S).txt" 2>/dev/null || echo "无现有crontab"

cat > "${CRON_FILE}" <<EOF
# MFTS 本地自动化任务（生产级执行链）
# 时区请与本机保持一致（建议 Asia/Shanghai）
# 优先使用 daily_all.py 作为生产主入口，避免拆分脚本链路造成口径漂移
# daily_all.py 默认会刷新 profile promotion gate latest 工件

# ── 盘后主链路 (T日收盘后) ────────────────────────

# 16:10 盘后主链路：数据更新 + 扫描 + ML + 验证 + P1 + P3 + Promotion Gate
10 16 * * 1-5 cd ${BASE_DIR} && ${PYTHON_BIN} scripts/daily_all.py --mode latest --with-p1 --with-p3-consistency >> logs/cron_daily_all.log 2>&1

# ── 盘前执行链 (T+1日开盘前) ─────────────────────

# 09:15 盘前执行再平衡（开盘前15分钟）
15 9 * * 1-5 cd ${BASE_DIR} && ${PYTHON_BIN} scripts/daily_all.py --mode verify-only --with-p2 --skip-profile-gate >> logs/cron_p2.log 2>&1

# ── 周度任务 ──────────────────────────────────────

# 每周日 20:00 自动再训练检查 (仅检查，不自动触发)
0 20 * * 0 cd ${BASE_DIR} && ${PYTHON_BIN} scripts/auto_retrain.py --check-only >> logs/cron_retrain.log 2>&1

# 每周日 21:00 历史验证（过去30天）
0 21 * * 0 cd ${BASE_DIR} && ${PYTHON_BIN} scripts/verify_historical.py --days 30 >> logs/cron_historical.log 2>&1

# 每周日 22:30 项目记忆进化：从长期记忆刷新 active context 与 nightly review
30 22 * * 0 cd ${BASE_DIR} && ${PYTHON_BIN} scripts/quant_memory_evolve.py >> logs/cron_memory_evolve.log 2>&1

# ── 月度维护 ──────────────────────────────────────

# 每月15日 03:00 清理90天前日志与旧输出
0 3 15 * * find ${BASE_DIR}/logs -name "*.log" -mtime +90 -delete
0 3 15 * * find ${BASE_DIR}/output -name "*.csv" -mtime +90 -delete
EOF

echo ""
echo "2. 定时任务配置内容："
echo "================================"
cat "${CRON_FILE}"
echo "================================"
echo ""

read -r -p "是否安装这些定时任务？(y/n): " REPLY
if [[ "${REPLY}" =~ ^[Yy]$ ]]; then
  # 与现有 crontab 合并，避免覆盖用户已有任务
  (crontab -l 2>/dev/null; echo ""; cat "${CRON_FILE}") | crontab -
  echo "✅ 定时任务已安装"
  echo ""
  echo "当前 crontab:"
  crontab -l
else
  echo "❌ 已取消安装"
  echo "如需手动安装，请运行: crontab ${CRON_FILE}"
fi

echo ""
echo "================================"
echo "配置完成"
echo "================================"
echo "查看日志: tail -f ${BASE_DIR}/logs/*.log"
echo "查看任务: crontab -l"
echo "编辑任务: crontab -e"
echo "删除任务: crontab -r"
