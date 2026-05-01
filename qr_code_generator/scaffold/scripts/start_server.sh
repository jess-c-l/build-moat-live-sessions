#!/usr/bin/env bash
# 啟動 uvicorn server (預設 port 8000)
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
