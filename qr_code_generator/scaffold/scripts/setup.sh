#!/usr/bin/env bash
# 一次性環境準備:建 venv + 安裝套件
set -e
cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  echo "✓ venv 建立完成"
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install --upgrade 'sqlalchemy>=2.0.40'
echo "✓ 套件安裝完成"
