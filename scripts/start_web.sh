#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${MFTS_PYTHON:-/opt/homebrew/Caskroom/miniforge/base/envs/stock/bin/python}"
HOST="${MFTS_HOST:-127.0.0.1}"
PORT="${MFTS_PORT:-5001}"
SESSION="${MFTS_WEB_SESSION:-stock_screener_web}"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/web_screen.log"

mkdir -p "${LOG_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python not found or not executable: ${PYTHON_BIN}" >&2
  echo "Set MFTS_PYTHON=/path/to/python or create the stock environment." >&2
  exit 1
fi

cd "${ROOT_DIR}"

screen_output="$(screen -list 2>/dev/null || true)"
if printf "%s\n" "${screen_output}" | grep -Eq "[0-9]+[.]${SESSION}([[:space:]]|$)"; then
  echo "Web server is already running in screen session: ${SESSION}"
else
  screen -dmS "${SESSION}" bash -lc \
    "cd '${ROOT_DIR}' && MFTS_HOST='${HOST}' MFTS_PORT='${PORT}' MFTS_LOCAL_ONLY='${MFTS_LOCAL_ONLY:-true}' exec '${PYTHON_BIN}' web/app.py >> '${LOG_FILE}' 2>&1"
  echo "Started web server in screen session: ${SESSION}"
fi

echo "Frontend: http://${HOST}:${PORT}"
echo "Log file: ${LOG_FILE}"
echo "Stop: screen -S ${SESSION} -X quit"
