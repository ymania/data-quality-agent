#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 Python 3；请先安装 Python 3.11–3.14。"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "首次启动：正在创建 Python 环境…"
  python3 -m venv .venv
fi

if ! .venv/bin/python -c 'import fastapi, uvicorn, pymysql, dotenv, deepagents, langchain_openai, socksio, openpyxl, python_multipart' >/dev/null 2>&1; then
  echo "首次启动：正在安装项目依赖…"
  .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python -m app.launcher
