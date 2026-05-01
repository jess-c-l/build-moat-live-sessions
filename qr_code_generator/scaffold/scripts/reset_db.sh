#!/usr/bin/env bash
# 清掉 SQLite DB(會清掉所有 token 跟 scan 紀錄)
set -e
cd "$(dirname "$0")/.."
rm -f qr_code.db
echo "✓ qr_code.db 已清除"
